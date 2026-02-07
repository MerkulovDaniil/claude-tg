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
