"""Claude Code CLI subprocess manager with stream-json parsing."""
import asyncio
import json
import signal
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import AsyncIterator


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
    import os
    from pathlib import Path

    servers = set()
    # Check both user-level and project-level MCP configs
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
    """Manages Claude Code CLI subprocess with streaming."""

    def __init__(self, work_dir: str, model: str | None = None, max_budget: float | None = None):
        self.work_dir = work_dir
        self.model = model
        self.max_budget = max_budget
        self.session_id: str | None = None
        self.process: asyncio.subprocess.Process | None = None
        self.is_running = False
        self._parser = StreamParser()

    def clear_session(self):
        self.session_id = None

    async def run(self, prompt: str) -> AsyncIterator[RunnerEvent]:
        """Run Claude Code and yield parsed events."""
        self.is_running = True

        cmd = [
            "claude",
            "-p", prompt,
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
        ]

        import os
        if os.getuid() != 0:
            cmd.append("--dangerously-skip-permissions")
        else:
            # Root can't use --dangerously-skip-permissions
            # Discover MCP servers and allow all tools dynamically
            mcp_servers = _discover_mcp_servers(self.work_dir)
            cmd.extend(["--allowedTools"] + _BUILTIN_TOOLS + mcp_servers)

        if self.session_id:
            cmd.extend(["--resume", self.session_id])
        if self.model:
            cmd.extend(["--model", self.model])
        if self.max_budget:
            cmd.extend(["--max-budget-usd", str(self.max_budget)])

        try:
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.work_dir,
                limit=100 * 1024 * 1024,  # 100MB
            )

            async for line in self.process.stdout:
                line_str = line.decode().strip()
                if not line_str:
                    continue
                try:
                    data = json.loads(line_str)
                    event = self._parser.parse(data)
                    if event:
                        # Capture session_id from init or result
                        if event.session_id and event.type in (EventType.INIT, EventType.RESULT):
                            self.session_id = event.session_id
                        yield event
                except json.JSONDecodeError:
                    yield RunnerEvent(type=EventType.TEXT_DELTA, text=line_str)

            await self.process.wait()

            if self.process.returncode and self.process.returncode != 0:
                stderr = await self.process.stderr.read()
                if stderr:
                    yield RunnerEvent(
                        type=EventType.TEXT_DELTA,
                        text=f"\n❌ Error: {stderr.decode().strip()}",
                    )
        finally:
            self.is_running = False
            self.process = None

    async def cancel(self) -> None:
        """Cancel the running process."""
        if not self.process:
            return
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
            self.is_running = False
            self.process = None
