"""Claude Code CLI subprocess manager with persistent streaming process."""
import asyncio
import json
import logging
import os
import signal
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import AsyncIterator

logger = logging.getLogger(__name__)


class EventType(Enum):
    INIT = auto()
    TEXT_DELTA = auto()
    TOOL_START = auto()
    TOOL_USE = auto()
    TOOL_RESULT = auto()
    RESULT = auto()


@dataclass
class RunnerEvent:
    type: EventType
    text: str = ""
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    is_error: bool = False
    session_id: str = ""
    duration_ms: int = 0
    num_turns: int = 0
    cost_usd: float = 0.0


# Queue sentinel types — signal EOF or errors from the background reader.


@dataclass
class _EOF:
    """Process stdout closed."""
    stderr: str = ""
    returncode: int = 0


@dataclass
class _Error:
    """Background reader crashed."""
    message: str = ""


class StreamParser:
    """Parse NDJSON stream events from Claude Code CLI."""

    def parse(self, data: dict) -> RunnerEvent | None:
        event_type = data.get("type")

        if event_type == "system":
            return self._parse_system(data)
        elif event_type == "stream_event":
            return self._parse_stream_event(data)
        elif event_type == "assistant":
            return self._parse_assistant(data)
        elif event_type == "user":
            return self._parse_user(data)
        elif event_type == "result":
            return self._parse_result(data)
        return None

    def _parse_system(self, data: dict) -> RunnerEvent | None:
        if data.get("subtype") == "init":
            return RunnerEvent(
                type=EventType.INIT,
                session_id=data.get("session_id", ""),
            )
        return None

    def _parse_stream_event(self, data: dict) -> RunnerEvent | None:
        inner = data.get("event", {})
        inner_type = inner.get("type")

        if inner_type == "content_block_delta":
            delta = inner.get("delta", {})
            if delta.get("type") == "text_delta":
                return RunnerEvent(
                    type=EventType.TEXT_DELTA,
                    text=delta.get("text", ""),
                )

        elif inner_type == "content_block_start":
            block = inner.get("content_block", {})
            if block.get("type") == "tool_use":
                return RunnerEvent(
                    type=EventType.TOOL_START,
                    tool_name=block.get("name", ""),
                )

        return None

    def _parse_assistant(self, data: dict) -> RunnerEvent | None:
        content = data.get("message", {}).get("content", [])
        for block in content:
            if block.get("type") == "tool_use":
                return RunnerEvent(
                    type=EventType.TOOL_USE,
                    tool_name=block.get("name", ""),
                    tool_input=block.get("input", {}),
                )
        return None

    def _parse_user(self, data: dict) -> RunnerEvent | None:
        content = data.get("message", {}).get("content", [])
        for block in content:
            if block.get("type") == "tool_result":
                raw = block.get("content", "")
                return RunnerEvent(
                    type=EventType.TOOL_RESULT,
                    text=raw,
                    is_error=block.get("is_error", False),
                )
        return None

    def _parse_result(self, data: dict) -> RunnerEvent:
        return RunnerEvent(
            type=EventType.RESULT,
            session_id=data.get("session_id", ""),
            duration_ms=data.get("duration_ms", 0),
            num_turns=data.get("num_turns", 0),
            cost_usd=data.get("total_cost_usd", 0.0),
            text=data.get("result", ""),
        )


_BUILTIN_TOOLS = [
    "Bash()", "Edit()", "MultiEdit()", "Write()", "Read()",
    "Glob()", "Grep()", "WebFetch()", "WebSearch()",
    "Task()", "TodoWrite()", "NotebookEdit()", "NotebookRead()",
]


def _discover_mcp_servers(work_dir: str) -> list[str]:
    """Read registered MCP server names from Claude config files."""
    from pathlib import Path

    servers = set()
    for path in [
        Path.home() / ".claude.json",
        Path(work_dir) / ".mcp.json",
    ]:
        if path.is_file():
            try:
                with open(path) as f:
                    data = json.load(f)
                for name in data.get("mcpServers", {}):
                    servers.add(f"mcp__{name}")
            except (json.JSONDecodeError, OSError):
                pass
    return sorted(servers)


class ClaudeRunner:
    """Manages a persistent Claude Code CLI subprocess with streaming I/O.

    Uses --input-format stream-json to keep a single process alive across
    multiple conversation turns, eliminating per-turn startup overhead.
    New messages are written to stdin as NDJSON; events are read from stdout.

    A background task continuously reads stdout into an asyncio.Queue,
    preventing pipe buffer deadlocks when injected turns produce unread output.
    """

    def __init__(self, work_dir: str, model: str | None = None, max_budget: float | None = None):
        self.work_dir = work_dir
        self.model = model
        self.max_budget = max_budget
        self.session_id: str | None = None
        self.process: asyncio.subprocess.Process | None = None
        self.is_processing = False
        self._parser = StreamParser()
        self._event_queue: asyncio.Queue[RunnerEvent | _EOF | _Error] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None

    @property
    def process_alive(self) -> bool:
        """True if the Claude subprocess is running."""
        return self.process is not None and self.process.returncode is None

    def clear_session(self):
        self.session_id = None

    async def _ensure_process(self):
        """Start Claude process if not already running."""
        if self.process_alive:
            return

        # Clean up old reader task
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        # Clear stale queue items from previous process
        while not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        cmd = [
            "claude",
            "-p",
            "--output-format", "stream-json",
            "--input-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
        ]

        if os.getuid() != 0:
            cmd.append("--dangerously-skip-permissions")
        else:
            mcp_servers = _discover_mcp_servers(self.work_dir)
            cmd.extend(["--allowedTools"] + _BUILTIN_TOOLS + mcp_servers)

        if self.session_id:
            cmd.extend(["--resume", self.session_id])
        if self.model:
            cmd.extend(["--model", self.model])
        if self.max_budget:
            cmd.extend(["--max-budget-usd", str(self.max_budget)])

        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.work_dir,
            limit=100 * 1024 * 1024,  # 100MB
        )
        logger.info("Started Claude process pid=%s", self.process.pid)

        # Start background stdout reader
        self._reader_task = asyncio.create_task(
            self._stdout_reader(), name=f"stdout-reader-{self.process.pid}"
        )

    async def _send_stdin(self, text: str):
        """Write a user message to stdin as NDJSON."""
        if not self.process_alive or not self.process.stdin:
            raise RuntimeError("Process not alive")

        msg = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": text}
        }, ensure_ascii=False) + "\n"

        self.process.stdin.write(msg.encode())
        await self.process.stdin.drain()

    async def _stdout_reader(self):
        """Background task: continuously read stdout into _event_queue.

        Runs for the entire lifetime of the subprocess. Ensures the pipe
        is always being drained, preventing buffer-full deadlocks.
        """
        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:  # EOF — process exited
                    await self.process.wait()
                    stderr_text = ""
                    if self.process.returncode and self.process.returncode != 0:
                        try:
                            stderr_bytes = await self.process.stderr.read()
                            stderr_text = stderr_bytes.decode().strip()[:2000] if stderr_bytes else ""
                        except Exception:
                            pass
                    await self._event_queue.put(
                        _EOF(stderr=stderr_text, returncode=self.process.returncode or 0)
                    )
                    return

                line_str = line.decode().strip()
                if not line_str:
                    continue

                try:
                    data = json.loads(line_str)
                    event = self._parser.parse(data)
                    if event:
                        if event.session_id and event.type in (EventType.INIT, EventType.RESULT):
                            self.session_id = event.session_id
                        await self._event_queue.put(event)
                except json.JSONDecodeError:
                    await self._event_queue.put(
                        RunnerEvent(type=EventType.TEXT_DELTA, text=line_str)
                    )
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error("Background reader crashed: %s", e)
            await self._event_queue.put(_Error(message=str(e)))

    async def _read_until_result(self) -> AsyncIterator[RunnerEvent]:
        """Yield events from the queue until RESULT or EOF/error sentinel."""
        while True:
            try:
                item = await asyncio.wait_for(self._event_queue.get(), timeout=300)
            except asyncio.TimeoutError:
                logger.error("Queue read timeout (5min) — forcing recovery")
                yield RunnerEvent(
                    type=EventType.TEXT_DELTA,
                    text="\n❌ Timeout waiting for events",
                )
                return

            if isinstance(item, _EOF):
                if item.stderr:
                    yield RunnerEvent(
                        type=EventType.TEXT_DELTA,
                        text=f"\n❌ Error: {item.stderr}",
                    )
                return

            if isinstance(item, _Error):
                yield RunnerEvent(
                    type=EventType.TEXT_DELTA,
                    text=f"\n❌ Reader error: {item.message}",
                )
                return

            yield item
            if item.type == EventType.RESULT:
                return

    async def _drain_pending(self):
        """Drain any pending events from the queue (non-blocking)."""
        drained = 0
        while not self._event_queue.empty():
            try:
                item = self._event_queue.get_nowait()
                drained += 1
                if isinstance(item, _EOF):
                    # Don't lose EOF — put it back for _read_until_result
                    await self._event_queue.put(item)
                    break
            except asyncio.QueueEmpty:
                break
        if drained:
            logger.debug("Drained %d pending queue items", drained)

    async def run(self, prompt: str) -> AsyncIterator[RunnerEvent]:
        """Send prompt and yield events until turn completes (RESULT).

        The process is kept alive after RESULT for subsequent calls.
        If the process died, a new one is started automatically.
        Caller manages is_processing flag.
        """
        try:
            await self._ensure_process()
            await self._drain_pending()
            await self._send_stdin(prompt)
            async for event in self._read_until_result():
                yield event

        except (BrokenPipeError, ConnectionResetError) as e:
            logger.error("Process pipe error: %s", e)
            yield RunnerEvent(
                type=EventType.TEXT_DELTA,
                text=f"\n❌ Process error: {e}",
            )

        finally:
            if not self.process_alive:
                self.process = None

    async def inject(self, prompt: str) -> None:
        """Send a message to the running process mid-turn.

        The CLI queues it and processes after the current turn.
        Orphaned turn events are safely consumed by the background
        reader into the queue and drained on the next run() call.
        """
        if not self.process_alive:
            raise RuntimeError("Cannot inject: process not alive")
        await self._send_stdin(prompt)
        logger.info("Injected mid-turn message (%d chars)", len(prompt))

    async def _cleanup_reader(self):
        """Cancel and await the background reader task."""
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        self._reader_task = None

    async def cancel(self) -> None:
        """Kill the running process (hard stop)."""
        if not self.process:
            return
        await self._cleanup_reader()
        try:
            self.process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(self.process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        except ProcessLookupError:
            pass
        finally:
            self.is_processing = False
            self.process = None

    async def stop(self) -> None:
        """Gracefully stop the process by closing stdin."""
        if not self.process_alive:
            self.process = None
            return
        try:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        except Exception:
            if self.process:
                try:
                    self.process.kill()
                except ProcessLookupError:
                    pass
        finally:
            await self._cleanup_reader()
            self.is_processing = False
            self.process = None
