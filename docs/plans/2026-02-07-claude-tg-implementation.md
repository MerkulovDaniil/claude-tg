# claude-tg Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a pip-installable `claude-tg` package that bridges Claude Code CLI to Telegram with native terminal-like streaming UX.

**Architecture:** Thin bridge — Telegram bot receives messages, spawns `claude -p` subprocess with `--output-format stream-json --include-partial-messages`, parses NDJSON stream, and renders output back to Telegram with adaptive rate-limited message editing and automatic message chaining for long outputs.

**Tech Stack:** Python 3.11+, python-telegram-bot 21+, asyncio subprocess

---

### Task 1: Package skeleton — pyproject.toml + config

**Files:**
- Create: `pyproject.toml`
- Create: `src/claude_tg/__init__.py`
- Create: `src/claude_tg/config.py`

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "claude-tg"
version = "0.1.0"
description = "Claude Code <-> Telegram bridge"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
dependencies = [
    "python-telegram-bot>=21.0",
]

[project.scripts]
claude-tg = "claude_tg.__main__:main"
```

**Step 2: Create src/claude_tg/__init__.py**

```python
"""claude-tg: Claude Code <-> Telegram bridge."""
__version__ = "0.1.0"
```

**Step 3: Create src/claude_tg/config.py**

```python
"""Configuration from environment variables."""
import os
import sys


class Config:
    """Load and validate configuration from env vars."""

    def __init__(self):
        self.bot_token: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id: int = int(os.environ.get("TELEGRAM_CHAT_ID", "0"))
        self.work_dir: str = os.environ.get("CLAUDE_WORK_DIR", os.getcwd())
        self.verbose: bool = os.environ.get("CLAUDE_TG_VERBOSE", "0") == "1"
        self.model: str | None = os.environ.get("CLAUDE_TG_MODEL")
        self.max_budget: float | None = (
            float(v) if (v := os.environ.get("CLAUDE_TG_MAX_BUDGET")) else None
        )
        self.session_timeout: int = int(
            os.environ.get("CLAUDE_TG_SESSION_TIMEOUT", "3600")
        )
        self.update_interval: float = float(
            os.environ.get("CLAUDE_TG_UPDATE_INTERVAL", "2.0")
        )

    def validate(self) -> list[str]:
        """Return list of validation errors. Empty = valid."""
        errors = []
        if not self.bot_token:
            errors.append("TELEGRAM_BOT_TOKEN is required")
        if not self.chat_id:
            errors.append("TELEGRAM_CHAT_ID is required")
        if not os.path.isdir(self.work_dir):
            errors.append(f"CLAUDE_WORK_DIR '{self.work_dir}' is not a directory")
        return errors
```

**Step 4: Verify package can be imported**

Run: `cd /path/to/claude-tg && pip install -e .`
Expected: successful install, `python -c "from claude_tg.config import Config; print('ok')"`

**Step 5: Commit**

```bash
git add pyproject.toml src/
git commit -m "feat: claude-tg package skeleton with config"
```

---

### Task 2: formatter.py — Markdown to Telegram HTML

**Files:**
- Create: `src/claude_tg/formatter.py`
- Create: `tests/test_formatter.py`

**Step 1: Write tests**

```python
"""Tests for Markdown -> Telegram HTML conversion."""
from claude_tg.formatter import md_to_html, escape_html, format_tool_call


class TestEscapeHtml:
    def test_escapes_angle_brackets(self):
        assert escape_html("a < b > c") == "a &lt; b &gt; c"

    def test_escapes_ampersand(self):
        assert escape_html("a & b") == "a &amp; b"

    def test_no_double_escape(self):
        assert escape_html("&amp;") == "&amp;amp;"


class TestMdToHtml:
    def test_bold(self):
        assert md_to_html("**hello**") == "<b>hello</b>"

    def test_italic(self):
        assert md_to_html("*hello*") == "<i>hello</i>"

    def test_inline_code(self):
        assert md_to_html("`foo()`") == "<code>foo()</code>"

    def test_code_block(self):
        result = md_to_html("```python\nprint('hi')\n```")
        assert '<pre><code class="language-python">' in result
        assert "print(&#x27;hi&#x27;)" in result or "print('hi')" in result

    def test_code_block_no_lang(self):
        result = md_to_html("```\nsome code\n```")
        assert "<pre><code>" in result

    def test_link(self):
        assert md_to_html("[click](http://x.com)") == '<a href="http://x.com">click</a>'

    def test_no_bold_inside_code(self):
        result = md_to_html("`**not bold**`")
        assert "<b>" not in result

    def test_code_block_preserves_content(self):
        result = md_to_html("```\n**not bold** <html>\n```")
        assert "<b>" not in result
        assert "&lt;html&gt;" in result

    def test_underscore_in_identifiers(self):
        result = md_to_html("use `send_message` function")
        assert "send_message" in result
        assert "<i>" not in result

    def test_plain_text_escaped(self):
        result = md_to_html("x < 5 && y > 3")
        assert "&lt;" in result
        assert "&gt;" in result
        assert "&amp;" in result

    def test_mixed_formatting(self):
        result = md_to_html("**bold** and *italic* and `code`")
        assert "<b>bold</b>" in result
        assert "<i>italic</i>" in result
        assert "<code>code</code>" in result

    def test_fallback_on_empty(self):
        assert md_to_html("") == ""

    def test_multiline_text(self):
        text = "line 1\nline 2\n**bold line**"
        result = md_to_html(text)
        assert "<b>bold line</b>" in result


class TestFormatToolCall:
    def test_read(self):
        result = format_tool_call("Read", {"file_path": "/src/main.py"})
        assert "📂" in result
        assert "main.py" in result

    def test_edit(self):
        result = format_tool_call("Edit", {"file_path": "/src/main.py"})
        assert "✏️" in result

    def test_write(self):
        result = format_tool_call("Write", {"file_path": "/tests/test.py"})
        assert "📝" in result

    def test_bash(self):
        result = format_tool_call("Bash", {"command": "npm test"})
        assert "▶️" in result
        assert "npm test" in result

    def test_grep(self):
        result = format_tool_call("Grep", {"pattern": "TODO", "glob": "**/*.py"})
        assert "🔍" in result

    def test_unknown_tool(self):
        result = format_tool_call("SomeTool", {"arg": "val"})
        assert "🔧" in result
        assert "SomeTool" in result
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_formatter.py -v`
Expected: FAIL (module not found)

**Step 3: Implement formatter.py**

```python
"""Convert Claude's Markdown output to Telegram HTML."""
import re


def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#x27;").replace('"', "&quot;")


def md_to_html(text: str) -> str:
    """
    Convert Markdown to Telegram-compatible HTML.

    Strategy: extract code blocks first (protect them), convert inline
    formatting, then reassemble.
    """
    if not text:
        return ""

    # Extract code blocks and replace with placeholders
    blocks: list[str] = []

    def _save_block(m: re.Match) -> str:
        lang = m.group(1) or ""
        code = escape_html(m.group(2))
        cls = f' class="language-{lang}"' if lang else ""
        blocks.append(f"<pre><code{cls}>{code}</code></pre>")
        return f"\x00BLOCK{len(blocks) - 1}\x00"

    result = re.sub(r"```(\w*)\n(.*?)```", _save_block, text, flags=re.DOTALL)

    # Extract inline code
    inline_codes: list[str] = []

    def _save_inline(m: re.Match) -> str:
        inline_codes.append(f"<code>{escape_html(m.group(1))}</code>")
        return f"\x00INLINE{len(inline_codes) - 1}\x00"

    result = re.sub(r"`([^`\n]+)`", _save_inline, result)

    # Escape remaining HTML
    result = escape_html(result)

    # Bold **...**
    result = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", result)

    # Italic *...* (not inside words, not **)
    result = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", result)

    # Links [text](url)
    result = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', result)

    # Restore inline code
    for i, code in enumerate(inline_codes):
        result = result.replace(f"\x00INLINE{i}\x00", code)

    # Restore code blocks
    for i, block in enumerate(blocks):
        result = result.replace(f"\x00BLOCK{i}\x00", block)

    return result


# Tool call icons
_TOOL_ICONS = {
    "Read": "📂",
    "Edit": "✏️",
    "Write": "📝",
    "Bash": "▶️",
    "Grep": "🔍",
    "Glob": "🔍",
    "Task": "🤖",
    "WebSearch": "🌐",
    "WebFetch": "🌐",
}


def format_tool_call(name: str, input_data: dict) -> str:
    """Format a tool call as a compact one-liner."""
    icon = _TOOL_ICONS.get(name, "🔧")

    if name in ("Read", "Edit", "Write"):
        path = input_data.get("file_path", "")
        # Show just filename or last 2 path components
        short = "/".join(path.rsplit("/", 2)[-2:]) if "/" in path else path
        return f"{icon} {name}: {short}"

    if name == "Bash":
        cmd = input_data.get("command", "")
        # Truncate long commands
        display = cmd[:60] + "..." if len(cmd) > 60 else cmd
        return f"{icon} Bash: {display}"

    if name in ("Grep", "Glob"):
        pattern = input_data.get("pattern", "")
        return f"{icon} {name}: {pattern}"

    # Fallback
    return f"{icon} {name}"


def format_tool_result(result: str, max_length: int = 1000) -> str:
    """Format a tool result as an expandable blockquote."""
    text = result[:max_length]
    if len(result) > max_length:
        text += f"\n... ({len(result)} chars total)"
    return f"<blockquote expandable>{escape_html(text)}</blockquote>"
```

**Step 4: Run tests**

Run: `pytest tests/test_formatter.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/claude_tg/formatter.py tests/test_formatter.py
git commit -m "feat: markdown to telegram HTML formatter with tool call formatting"
```

---

### Task 3: runner.py — Claude Code subprocess with stream-json parsing

**Files:**
- Create: `src/claude_tg/runner.py`
- Create: `tests/test_runner.py`

**Step 1: Write tests**

```python
"""Tests for Claude Code stream-json event parsing."""
import json
import pytest
from claude_tg.runner import StreamParser, RunnerEvent, EventType


def make_text_delta(text: str) -> dict:
    return {
        "type": "stream_event",
        "event": {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": text},
        },
        "session_id": "test-session",
    }


def make_tool_start(name: str, tool_id: str = "toolu_123") -> dict:
    return {
        "type": "stream_event",
        "event": {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": tool_id, "name": name, "input": {}},
        },
        "session_id": "test-session",
    }


def make_assistant_tool_use(name: str, input_data: dict) -> dict:
    return {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "id": "toolu_123", "name": name, "input": input_data}
            ]
        },
        "session_id": "test-session",
    }


def make_tool_result(content: str, is_error: bool = False) -> dict:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "content": content,
                    "is_error": is_error,
                    "tool_use_id": "toolu_123",
                }
            ],
        },
        "session_id": "test-session",
    }


def make_result(session_id: str = "test-session", duration_ms: int = 5000, num_turns: int = 3, cost: float = 0.05) -> dict:
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": duration_ms,
        "num_turns": num_turns,
        "total_cost_usd": cost,
        "session_id": session_id,
        "result": "final text",
    }


def make_init(session_id: str = "test-session") -> dict:
    return {
        "type": "system",
        "subtype": "init",
        "session_id": session_id,
        "tools": ["Bash", "Read"],
        "model": "claude-sonnet-4-5-20250929",
    }


class TestStreamParser:
    def setup_method(self):
        self.parser = StreamParser()

    def test_text_delta(self):
        event = self.parser.parse(make_text_delta("hello"))
        assert event.type == EventType.TEXT_DELTA
        assert event.text == "hello"

    def test_tool_start(self):
        event = self.parser.parse(make_tool_start("Read"))
        assert event.type == EventType.TOOL_START
        assert event.tool_name == "Read"

    def test_assistant_tool_use(self):
        event = self.parser.parse(
            make_assistant_tool_use("Read", {"file_path": "/tmp/test.py"})
        )
        assert event.type == EventType.TOOL_USE
        assert event.tool_name == "Read"
        assert event.tool_input == {"file_path": "/tmp/test.py"}

    def test_tool_result(self):
        event = self.parser.parse(make_tool_result("file contents here"))
        assert event.type == EventType.TOOL_RESULT
        assert event.text == "file contents here"

    def test_tool_result_error(self):
        event = self.parser.parse(make_tool_result("not found", is_error=True))
        assert event.type == EventType.TOOL_RESULT
        assert event.is_error is True

    def test_result(self):
        event = self.parser.parse(make_result())
        assert event.type == EventType.RESULT
        assert event.session_id == "test-session"
        assert event.duration_ms == 5000
        assert event.num_turns == 3

    def test_init(self):
        event = self.parser.parse(make_init())
        assert event.type == EventType.INIT
        assert event.session_id == "test-session"

    def test_unknown_event_returns_none(self):
        event = self.parser.parse({"type": "system", "subtype": "hook_started"})
        assert event is None

    def test_message_stop_returns_none(self):
        event = self.parser.parse(
            {"type": "stream_event", "event": {"type": "message_stop"}, "session_id": "x"}
        )
        assert event is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_runner.py -v`
Expected: FAIL

**Step 3: Implement runner.py**

```python
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
            "--dangerously-skip-permissions",
        ]

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
```

**Step 4: Run tests**

Run: `pytest tests/test_runner.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/claude_tg/runner.py tests/test_runner.py
git commit -m "feat: claude code subprocess runner with stream-json parser"
```

---

### Task 4: stream.py — Telegram message streaming with chaining

**Files:**
- Create: `src/claude_tg/stream.py`
- Create: `tests/test_stream.py`

**Step 1: Write tests for MessageChain logic**

```python
"""Tests for Telegram streaming and message chaining."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from claude_tg.stream import MessageChain


class TestMessageChain:
    """Test the message buffer and chaining logic (no Telegram calls)."""

    def test_append_text(self):
        chain = MessageChain(max_length=100)
        chain.append_text("hello")
        assert chain.current_text == "hello"

    def test_needs_new_message_when_full(self):
        chain = MessageChain(max_length=50)
        chain.append_text("x" * 51)
        assert chain.needs_new_message is True

    def test_no_new_message_when_under_limit(self):
        chain = MessageChain(max_length=100)
        chain.append_text("short")
        assert chain.needs_new_message is False

    def test_split_preserves_text(self):
        chain = MessageChain(max_length=50)
        chain.append_text("a" * 30)
        chain.append_text("b" * 30)
        completed = chain.complete_current()
        assert len(completed) <= 60  # the first chunk
        assert chain.current_text  # remainder in new buffer

    def test_append_tool_call(self):
        chain = MessageChain(max_length=200)
        chain.append_text("some text\n")
        chain.append_tool_call("📂 Read: main.py")
        assert "📂 Read: main.py" in chain.current_text

    def test_footer(self):
        chain = MessageChain(max_length=200)
        chain.append_text("response text")
        chain.set_footer("⏱ 5s · 2 turns")
        assert "⏱ 5s · 2 turns" in chain.render()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_stream.py -v`
Expected: FAIL

**Step 3: Implement stream.py**

```python
"""Telegram message streaming with rate limiting and message chaining."""
import time
import asyncio
from telegram import Message, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest

from .formatter import md_to_html


class MessageChain:
    """Buffer text and manage splitting across Telegram messages."""

    def __init__(self, max_length: int = 3800):
        self.max_length = max_length
        self._chunks: list[str] = []  # completed chunks
        self._current: str = ""
        self._footer: str = ""

    @property
    def current_text(self) -> str:
        return self._current

    @property
    def needs_new_message(self) -> bool:
        return len(self._current) > self.max_length

    def append_text(self, text: str):
        self._current += text

    def append_tool_call(self, line: str):
        if self._current and not self._current.endswith("\n"):
            self._current += "\n"
        self._current += line + "\n"

    def complete_current(self) -> str:
        """Finalize current buffer and start new one. Returns completed text."""
        # Find a good split point near the limit
        text = self._current
        if len(text) <= self.max_length:
            completed = text
            self._current = ""
        else:
            split_at = text.rfind("\n", 0, self.max_length)
            if split_at < self.max_length // 2:
                split_at = self.max_length
            completed = text[:split_at]
            self._current = text[split_at:].lstrip("\n")
        self._chunks.append(completed)
        return completed

    def set_footer(self, footer: str):
        self._footer = footer

    def render(self) -> str:
        """Render current buffer with footer for display."""
        text = self._current
        if self._footer:
            text = text.rstrip() + "\n\n" + self._footer
        return text


class TelegramStream:
    """
    Stream Claude output to Telegram with adaptive rate limiting
    and automatic message chaining.
    """

    def __init__(
        self,
        bot,
        chat_id: int,
        update_interval: float = 2.0,
        reply_markup: InlineKeyboardMarkup | None = None,
    ):
        self.bot = bot
        self.chat_id = chat_id
        self.update_interval = update_interval
        self.reply_markup = reply_markup
        self.chain = MessageChain()
        self._current_msg: Message | None = None
        self._first_msg: Message | None = None
        self._last_update: float = 0.0
        self._lock = asyncio.Lock()
        self._dirty = False

    async def start(self) -> Message:
        """Send the initial 'Thinking...' message."""
        self._current_msg = await self.bot.send_message(
            chat_id=self.chat_id,
            text="⏳ Thinking...",
            reply_markup=self.reply_markup,
        )
        self._first_msg = self._current_msg
        return self._current_msg

    async def push_text(self, text: str):
        """Add text and update display if interval elapsed."""
        self.chain.append_text(text)
        self._dirty = True
        await self._maybe_update()

    async def push_tool_call(self, line: str):
        """Add a tool call line."""
        self.chain.append_tool_call(line)
        self._dirty = True
        await self._maybe_update()

    async def push_tool_result(self, html: str):
        """Add a tool result (already formatted as HTML)."""
        self.chain.append_text(html)
        self._dirty = True
        await self._maybe_update()

    async def _maybe_update(self):
        """Update Telegram message if enough time has passed."""
        now = time.time()
        if now - self._last_update < self.update_interval:
            return
        await self._flush()

    async def _flush(self):
        """Force update to Telegram."""
        async with self._lock:
            if not self._dirty or not self._current_msg:
                return

            # Check if we need a new message
            if self.chain.needs_new_message:
                completed = self.chain.complete_current()
                await self._edit_message(self._current_msg, completed, reply_markup=None)
                # Create new message as reply to first for threading
                self._current_msg = await self.bot.send_message(
                    chat_id=self.chat_id,
                    text="⏳ ...",
                    reply_markup=self.reply_markup,
                    reply_to_message_id=self._first_msg.message_id,
                )

            display = self.chain.render()
            if display.strip():
                await self._edit_message(
                    self._current_msg, display, reply_markup=self.reply_markup
                )

            self._last_update = time.time()
            self._dirty = False

    async def finalize(self, footer: str = "", cancelled: bool = False):
        """Final update: set footer, remove cancel button."""
        async with self._lock:
            if cancelled:
                prefix = "🛑 Cancelled\n\n"
                self.chain._current = prefix + self.chain._current

            if footer:
                self.chain.set_footer(footer)

            display = self.chain.render()
            if display.strip() and self._current_msg:
                await self._edit_message(self._current_msg, display, reply_markup=None)

    async def _edit_message(
        self, msg: Message, text: str, reply_markup: InlineKeyboardMarkup | None
    ):
        """Edit message with HTML formatting, fallback to plain text."""
        try:
            html_text = md_to_html(text)
            await msg.edit_text(
                html_text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
        except BadRequest as e:
            if "message is not modified" in str(e).lower():
                return
            # Fallback to plain text
            try:
                await msg.edit_text(text, reply_markup=reply_markup)
            except BadRequest:
                pass
        except Exception:
            pass
```

**Step 4: Run tests**

Run: `pytest tests/test_stream.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/claude_tg/stream.py tests/test_stream.py
git commit -m "feat: telegram streaming with rate limiting and message chaining"
```

---

### Task 5: media.py — Photo/file handling with cleanup

**Files:**
- Create: `src/claude_tg/media.py`
- Create: `tests/test_media.py`

**Step 1: Write tests**

```python
"""Tests for media handling."""
import os
import tempfile
import pytest
from claude_tg.media import MediaHandler


class TestMediaHandler:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.handler = MediaHandler(upload_dir=self.tmpdir)

    def teardown_method(self):
        self.handler.cleanup()
        if os.path.exists(self.tmpdir):
            os.rmdir(self.tmpdir)

    def test_build_prompt_photo(self):
        path = os.path.join(self.tmpdir, "photo.jpg")
        open(path, "w").close()
        self.handler._files.append(path)
        result = self.handler.build_prompt("describe this", [path], [])
        assert "[User sent a photo:" in result
        assert "describe this" in result

    def test_build_prompt_document(self):
        path = os.path.join(self.tmpdir, "report.pdf")
        open(path, "w").close()
        self.handler._files.append(path)
        result = self.handler.build_prompt("analyze", [], [path])
        assert "[User sent a file:" in result

    def test_build_prompt_text_only(self):
        result = self.handler.build_prompt("hello", [], [])
        assert result == "hello"

    def test_cleanup_removes_files(self):
        path = os.path.join(self.tmpdir, "test.txt")
        with open(path, "w") as f:
            f.write("test")
        self.handler._files.append(path)
        self.handler.cleanup()
        assert not os.path.exists(path)

    def test_cleanup_on_empty(self):
        self.handler.cleanup()  # should not raise
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_media.py -v`
Expected: FAIL

**Step 3: Implement media.py**

```python
"""Handle incoming photos and files from Telegram."""
import os
import logging
import tempfile
from pathlib import Path

from telegram import PhotoSize, Document

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


class MediaHandler:
    """Download, track, and clean up user-uploaded media."""

    def __init__(self, upload_dir: str | None = None):
        self.upload_dir = upload_dir or os.path.join(
            tempfile.gettempdir(), "claude-tg-uploads"
        )
        os.makedirs(self.upload_dir, exist_ok=True)
        self._files: list[str] = []

    async def save_photo(self, photo: PhotoSize, bot) -> str:
        """Download a photo and return local path."""
        file = await bot.get_file(photo.file_id)
        ext = Path(file.file_path).suffix if file.file_path else ".jpg"
        local_path = os.path.join(self.upload_dir, f"photo_{photo.file_unique_id}{ext}")
        await file.download_to_drive(local_path)
        self._files.append(local_path)
        logger.info(f"Saved photo: {local_path}")
        return local_path

    async def save_document(self, doc: Document, bot) -> str:
        """Download a document and return local path."""
        file = await bot.get_file(doc.file_id)
        filename = doc.file_name or f"file_{doc.file_unique_id}"
        local_path = os.path.join(self.upload_dir, filename)
        await file.download_to_drive(local_path)
        self._files.append(local_path)
        logger.info(f"Saved document: {local_path}")
        return local_path

    def build_prompt(
        self, text: str, photo_paths: list[str], doc_paths: list[str]
    ) -> str:
        """Build a prompt that includes references to uploaded files."""
        parts = []

        for path in photo_paths:
            parts.append(f"[User sent a photo: {path}]")

        for path in doc_paths:
            parts.append(f"[User sent a file: {path}]")

        if text:
            parts.append(text)

        return "\n".join(parts) if parts else text

    def cleanup(self):
        """Remove all tracked files."""
        for path in self._files:
            try:
                os.remove(path)
                logger.debug(f"Cleaned up: {path}")
            except OSError:
                pass
        self._files.clear()

    def cleanup_all(self):
        """Remove entire upload directory contents (for startup cleanup)."""
        self.cleanup()
        try:
            for f in os.listdir(self.upload_dir):
                try:
                    os.remove(os.path.join(self.upload_dir, f))
                except OSError:
                    pass
        except OSError:
            pass
```

**Step 4: Run tests**

Run: `pytest tests/test_media.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/claude_tg/media.py tests/test_media.py
git commit -m "feat: media handler for photos and documents with cleanup"
```

---

### Task 6: bot.py — Telegram bot handlers and session management

**Files:**
- Create: `src/claude_tg/bot.py`

This is the integration layer — connects all components. Tested via integration tests (Task 8).

**Step 1: Implement bot.py**

```python
"""Telegram bot setup, handlers, and session management."""
import time
import asyncio
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from .config import Config
from .runner import ClaudeRunner, EventType
from .stream import TelegramStream
from .media import MediaHandler
from .formatter import format_tool_call, format_tool_result

logger = logging.getLogger(__name__)


class ClaudeTelegramBot:
    """Main bot class — ties all components together."""

    def __init__(self, config: Config):
        self.config = config
        self.runner = ClaudeRunner(
            work_dir=config.work_dir,
            model=config.model,
            max_budget=config.max_budget,
        )
        self.media = MediaHandler()
        self._stream: TelegramStream | None = None
        self._last_activity: float = time.time()
        self._session_cost: float = 0.0

        # Debounce state
        self._buffer: list[str] = []
        self._buffer_photos: list[str] = []
        self._buffer_docs: list[str] = []
        self._debounce_task: asyncio.Task | None = None
        self._debounce_timeout = 0.5

    def _is_authorized(self, update: Update) -> bool:
        return update.effective_chat and update.effective_chat.id == self.config.chat_id

    def _check_session_timeout(self):
        """Auto-reset session if inactive too long."""
        if (
            self.runner.session_id
            and time.time() - self._last_activity > self.config.session_timeout
        ):
            logger.info("Session timed out, resetting")
            self.runner.clear_session()
            self.media.cleanup()
            self._session_cost = 0.0

    def _touch_activity(self):
        self._last_activity = time.time()

    # --- Commands ---

    async def cmd_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        self.runner.clear_session()
        self.media.cleanup()
        self._session_cost = 0.0
        await update.message.reply_text("🆕 Session cleared.")

    async def cmd_compact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        if self.runner.is_running:
            await update.message.reply_text("⚠️ Claude is busy. Use /cancel first.")
            return
        # Send /compact as a prompt — Claude Code recognizes slash commands
        self._buffer.append("/compact")
        await self._process_buffer(context)

    async def cmd_cost(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        await update.message.reply_text(
            f"💰 Session cost: ${self._session_cost:.4f}"
        )

    async def cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        if not self.runner.is_running:
            await update.message.reply_text("Nothing running.")
            return
        await self.runner.cancel()
        if self._stream:
            await self._stream.finalize(cancelled=True)
            self._stream = None
        await update.message.reply_text("🛑 Cancelled.")

    async def cmd_model(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        if not context.args:
            current = self.runner.model or "default"
            await update.message.reply_text(f"Current model: {current}\nUsage: /model <name>")
            return
        self.runner.model = context.args[0]
        await update.message.reply_text(f"Model set to: {self.runner.model}")

    # --- Cancel callback ---

    async def handle_cancel_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        if query.from_user.id != self.config.chat_id:
            return
        if query.data == "claude_cancel":
            if not self.runner.is_running:
                await query.edit_message_text("Nothing running.")
                return
            await self.runner.cancel()
            if self._stream:
                await self._stream.finalize(cancelled=True)
                self._stream = None

    # --- Message handling ---

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        self._buffer.append(update.message.text)
        await self._schedule_debounce(context)

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        photo = update.message.photo[-1]  # highest resolution
        path = await self.media.save_photo(photo, context.bot)
        self._buffer_photos.append(path)
        if update.message.caption:
            self._buffer.append(update.message.caption)
        await self._schedule_debounce(context)

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        path = await self.media.save_document(update.message.document, context.bot)
        self._buffer_docs.append(path)
        if update.message.caption:
            self._buffer.append(update.message.caption)
        await self._schedule_debounce(context)

    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        await update.message.reply_text("🎤 Voice messages not supported yet.")

    async def _schedule_debounce(self, context: ContextTypes.DEFAULT_TYPE):
        if self._debounce_task:
            self._debounce_task.cancel()
            try:
                await self._debounce_task
            except asyncio.CancelledError:
                pass

        async def _fire():
            await asyncio.sleep(self._debounce_timeout)
            await self._process_buffer(context)

        self._debounce_task = asyncio.create_task(_fire())

    async def _process_buffer(self, context: ContextTypes.DEFAULT_TYPE):
        """Process accumulated buffer."""
        text = "\n".join(self._buffer)
        photos = list(self._buffer_photos)
        docs = list(self._buffer_docs)
        self._buffer.clear()
        self._buffer_photos.clear()
        self._buffer_docs.clear()

        if not text and not photos and not docs:
            return

        self._check_session_timeout()
        self._touch_activity()

        if self.runner.is_running:
            await context.bot.send_message(
                self.config.chat_id, "⚠️ Claude is busy. Use /cancel first."
            )
            return

        # Build prompt with media references
        prompt = self.media.build_prompt(text, photos, docs)

        # Create cancel button
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🛑 Cancel", callback_data="claude_cancel")]]
        )

        # Start streaming
        stream = TelegramStream(
            bot=context.bot,
            chat_id=self.config.chat_id,
            update_interval=self.config.update_interval,
            reply_markup=keyboard,
        )
        self._stream = stream
        await stream.start()

        try:
            async for event in self.runner.run(prompt):
                if event.type == EventType.TEXT_DELTA:
                    await stream.push_text(event.text)

                elif event.type == EventType.TOOL_USE:
                    line = format_tool_call(event.tool_name, event.tool_input)
                    await stream.push_tool_call(line)

                elif event.type == EventType.TOOL_RESULT and self.config.verbose:
                    html = format_tool_result(event.text)
                    await stream.push_tool_result(html)

                elif event.type == EventType.RESULT:
                    self._session_cost += event.cost_usd
                    duration = event.duration_ms // 1000
                    footer = f"⏱ {duration}s · {event.num_turns} turns"
                    await stream.finalize(footer=footer)

            # If no RESULT event came (shouldn't happen, but safety)
            if self.runner.is_running is False and stream == self._stream:
                await stream.finalize()

        except Exception as e:
            logger.exception("Error running Claude")
            try:
                await stream.finalize(footer=f"❌ Error: {str(e)[:200]}")
            except Exception:
                await context.bot.send_message(
                    self.config.chat_id, f"❌ Error: {str(e)[:4000]}"
                )
        finally:
            self._stream = None

    # --- App setup ---

    def build_app(self) -> Application:
        """Build and configure the Telegram Application."""
        app = Application.builder().token(self.config.bot_token).build()

        # Commands
        app.add_handler(CommandHandler("clear", self.cmd_clear))
        app.add_handler(CommandHandler("compact", self.cmd_compact))
        app.add_handler(CommandHandler("cost", self.cmd_cost))
        app.add_handler(CommandHandler("cancel", self.cmd_cancel))
        app.add_handler(CommandHandler("model", self.cmd_model))

        # Callbacks
        app.add_handler(
            CallbackQueryHandler(self.handle_cancel_callback, pattern="^claude_cancel$")
        )

        # Messages (order matters: specific types before catch-all text)
        app.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
        app.add_handler(MessageHandler(filters.Document.ALL, self.handle_document))
        app.add_handler(MessageHandler(filters.VOICE, self.handle_voice))
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text)
        )

        return app

    def run(self):
        """Start the bot (blocking)."""
        # Cleanup leftover uploads from previous run
        self.media.cleanup_all()

        logger.info(f"Starting claude-tg, work_dir={self.config.work_dir}")
        app = self.build_app()
        app.run_polling(allowed_updates=Update.ALL_TYPES)
```

**Step 2: Commit**

```bash
git add src/claude_tg/bot.py
git commit -m "feat: telegram bot with session management, commands, and media support"
```

---

### Task 7: __main__.py — CLI entry point

**Files:**
- Create: `src/claude_tg/__main__.py`

**Step 1: Implement __main__.py**

```python
"""CLI entry point for claude-tg."""
import sys
import argparse
import logging
import os

from .config import Config
from .bot import ClaudeTelegramBot


def main():
    parser = argparse.ArgumentParser(
        description="Claude Code <-> Telegram bridge",
        prog="claude-tg",
    )
    parser.add_argument(
        "--work-dir",
        help="Working directory for Claude Code (default: current directory)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show tool results in expandable blockquotes",
    )
    args = parser.parse_args()

    # CLI args override env vars
    if args.work_dir:
        os.environ["CLAUDE_WORK_DIR"] = args.work_dir
    if args.verbose:
        os.environ["CLAUDE_TG_VERBOSE"] = "1"

    # Configure logging
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=getattr(logging, log_level, logging.INFO),
    )

    config = Config()
    errors = config.validate()
    if errors:
        for e in errors:
            print(f"Error: {e}", file=sys.stderr)
        print(
            "\nRequired env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID",
            file=sys.stderr,
        )
        sys.exit(1)

    bot = ClaudeTelegramBot(config)
    bot.run()


if __name__ == "__main__":
    main()
```

**Step 2: Verify CLI works**

Run: `cd /path/to/claude-tg && python -m claude_tg --help`
Expected: shows help text with --work-dir and --verbose flags

**Step 3: Commit**

```bash
git add src/claude_tg/__main__.py
git commit -m "feat: CLI entry point with argument parsing"
```

---

### Task 8: Integration test — end-to-end smoke test

**Files:**
- Create: `tests/test_integration.py`
- Create: `tests/conftest.py`

**Step 1: Write integration test with mocked subprocess**

```python
"""Integration smoke test — mocked Claude subprocess + mocked Telegram."""
import json
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from claude_tg.config import Config
from claude_tg.bot import ClaudeTelegramBot
from claude_tg.runner import StreamParser, EventType


class TestIntegrationSmoke:
    """Test the full flow with mocked externals."""

    def test_config_validation_missing_token(self):
        config = Config()
        config.bot_token = ""
        config.chat_id = 123
        errors = config.validate()
        assert any("TELEGRAM_BOT_TOKEN" in e for e in errors)

    def test_config_validation_ok(self, tmp_path):
        config = Config()
        config.bot_token = "test"
        config.chat_id = 123
        config.work_dir = str(tmp_path)
        assert config.validate() == []

    def test_parser_full_flow(self):
        """Simulate a complete stream-json session."""
        parser = StreamParser()
        events = []

        # init
        e = parser.parse({"type": "system", "subtype": "init", "session_id": "s1", "tools": [], "model": "sonnet"})
        events.append(e)
        assert e.type == EventType.INIT

        # text streaming
        e = parser.parse({
            "type": "stream_event",
            "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello "}},
            "session_id": "s1",
        })
        events.append(e)
        assert e.type == EventType.TEXT_DELTA

        # tool use
        e = parser.parse({
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/tmp/x"}}]},
            "session_id": "s1",
        })
        events.append(e)
        assert e.type == EventType.TOOL_USE

        # tool result
        e = parser.parse({
            "type": "user",
            "message": {"role": "user", "content": [{"type": "tool_result", "content": "file data", "tool_use_id": "t1"}]},
            "session_id": "s1",
        })
        events.append(e)
        assert e.type == EventType.TOOL_RESULT

        # result
        e = parser.parse({
            "type": "result", "subtype": "success", "is_error": False,
            "duration_ms": 3000, "num_turns": 2, "total_cost_usd": 0.05,
            "session_id": "s1", "result": "done",
        })
        events.append(e)
        assert e.type == EventType.RESULT
        assert e.session_id == "s1"
```

**Step 2: Run tests**

Run: `pytest tests/ -v`
Expected: all PASS

**Step 3: Commit**

```bash
git add tests/
git commit -m "test: integration smoke tests for config and parser flow"
```

---

### Task 9: Cleanup — remove old files, update README

**Files:**
- Delete: `main.py`, `claude_runner.py`, `telegram_io.py`, `vps_control.py`, `requirements.txt`, `feanor-bot.service`, `state.json`, `hello.py`
- Rewrite: `README.md`

**Step 1: Remove old files**

```bash
git rm main.py claude_runner.py telegram_io.py vps_control.py requirements.txt feanor-bot.service hello.py
rm -rf __pycache__
echo "__pycache__/" >> .gitignore
```

**Step 2: Write new README.md**

Content: streamlined version of the design doc focusing on installation and usage. Keep it short — Quick Start, Commands, Configuration table. No internal architecture details.

**Step 3: Run full test suite**

Run: `pytest tests/ -v`
Expected: all PASS

**Step 4: Verify install + CLI**

Run: `pip install -e . && claude-tg --help`
Expected: clean install, help output

**Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove old monolith files, update README for claude-tg"
```

---

## Execution Summary

| Task | Component | Tests |
|------|-----------|-------|
| 1 | pyproject.toml + config.py | — |
| 2 | formatter.py | test_formatter.py |
| 3 | runner.py | test_runner.py |
| 4 | stream.py | test_stream.py |
| 5 | media.py | test_media.py |
| 6 | bot.py | — (integration) |
| 7 | __main__.py | — |
| 8 | Integration tests | test_integration.py |
| 9 | Cleanup + README | — |

Total: 9 tasks, ~7 files of code, ~4 test files.
