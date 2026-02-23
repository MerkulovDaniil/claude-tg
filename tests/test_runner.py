"""Tests for Claude Code stream-json event parsing and MCP config isolation."""
import json
import os
import pytest
from claude_tg.runner import (
    StreamParser, RunnerEvent, EventType,
    _discover_mcp_servers, _build_mcp_config, ClaudeRunner,
)


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


class TestDiscoverMcpServers:
    def test_reads_from_custom_mcp_config(self, tmp_path):
        """When mcp_config is set, only that file is read."""
        custom = tmp_path / "custom-mcp.json"
        custom.write_text(json.dumps({
            "mcpServers": {
                "oura": {"command": "python3", "args": []},
                "todoist": {"command": "npx", "args": []},
            }
        }))
        # This file should be ignored when custom config is provided
        project_mcp = tmp_path / ".mcp.json"
        project_mcp.write_text(json.dumps({
            "mcpServers": {
                "telegram": {"command": "mcp-telegram", "args": []},
            }
        }))

        result = _discover_mcp_servers(str(tmp_path), mcp_config=str(custom))
        assert "mcp__oura" in result
        assert "mcp__todoist" in result
        assert "mcp__telegram" not in result

    def test_default_reads_project_mcp(self, tmp_path):
        """Without mcp_config, reads from .mcp.json in work_dir."""
        project_mcp = tmp_path / ".mcp.json"
        project_mcp.write_text(json.dumps({
            "mcpServers": {"garmin": {"command": "garth", "args": []}}
        }))
        result = _discover_mcp_servers(str(tmp_path))
        assert "mcp__garmin" in result

    def test_missing_custom_config_returns_empty(self, tmp_path):
        """Non-existent mcp_config file returns no servers."""
        result = _discover_mcp_servers(str(tmp_path), mcp_config=str(tmp_path / "nope.json"))
        assert result == []

    def test_malformed_json_returns_empty(self, tmp_path):
        """Malformed JSON is silently ignored."""
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        result = _discover_mcp_servers(str(tmp_path), mcp_config=str(bad))
        assert result == []


class TestBuildMcpConfig:
    def test_excludes_servers(self, tmp_path):
        """Excluded servers are removed from generated config."""
        mcp = tmp_path / ".mcp.json"
        mcp.write_text(json.dumps({
            "mcpServers": {
                "telegram": {"command": "mcp-telegram", "args": []},
                "todoist": {"command": "npx", "args": []},
                "oura": {"command": "python3", "args": []},
            }
        }))
        result = _build_mcp_config(str(tmp_path), exclude=["telegram"])
        assert result is not None
        with open(result) as f:
            data = json.load(f)
        servers = data["mcpServers"]
        assert "telegram" not in servers
        assert "todoist" in servers
        assert "oura" in servers
        os.unlink(result)

    def test_exclude_multiple(self, tmp_path):
        mcp = tmp_path / ".mcp.json"
        mcp.write_text(json.dumps({
            "mcpServers": {
                "telegram": {"command": "x"},
                "garmin": {"command": "y"},
                "todoist": {"command": "z"},
            }
        }))
        result = _build_mcp_config(str(tmp_path), exclude=["telegram", "garmin"])
        with open(result) as f:
            data = json.load(f)
        assert list(data["mcpServers"].keys()) == ["todoist"]
        os.unlink(result)

    def test_empty_exclude_keeps_all(self, tmp_path):
        mcp = tmp_path / ".mcp.json"
        mcp.write_text(json.dumps({
            "mcpServers": {"a": {"command": "x"}, "b": {"command": "y"}}
        }))
        result = _build_mcp_config(str(tmp_path), exclude=[])
        with open(result) as f:
            data = json.load(f)
        assert len(data["mcpServers"]) == 2
        os.unlink(result)

    def test_no_config_files_returns_none(self, tmp_path):
        result = _build_mcp_config(str(tmp_path), exclude=["x"])
        assert result is None

    def test_exclude_nonexistent_server_is_harmless(self, tmp_path):
        mcp = tmp_path / ".mcp.json"
        mcp.write_text(json.dumps({
            "mcpServers": {"todoist": {"command": "npx"}}
        }))
        result = _build_mcp_config(str(tmp_path), exclude=["nonexistent"])
        with open(result) as f:
            data = json.load(f)
        assert "todoist" in data["mcpServers"]
        os.unlink(result)


class TestClaudeRunnerMcpConfig:
    def test_stores_mcp_config(self):
        runner = ClaudeRunner(work_dir="/tmp", mcp_config="/path/to/mcp.json")
        assert runner.mcp_config == "/path/to/mcp.json"
        assert runner.effective_mcp_config == "/path/to/mcp.json"

    def test_auto_generates_config_by_default(self, tmp_path):
        """Even without explicit config, auto-generates isolated MCP config."""
        mcp = tmp_path / ".mcp.json"
        mcp.write_text(json.dumps({
            "mcpServers": {"todoist": {"command": "npx"}}
        }))
        runner = ClaudeRunner(work_dir=str(tmp_path))
        assert runner.mcp_config is None
        assert runner.effective_mcp_config is not None

    def test_mcp_exclude_generates_auto_config(self, tmp_path):
        mcp = tmp_path / ".mcp.json"
        mcp.write_text(json.dumps({
            "mcpServers": {
                "telegram": {"command": "x"},
                "todoist": {"command": "y"},
            }
        }))
        runner = ClaudeRunner(work_dir=str(tmp_path), mcp_exclude=["telegram"])
        assert runner.effective_mcp_config is not None
        with open(runner.effective_mcp_config) as f:
            data = json.load(f)
        assert "telegram" not in data["mcpServers"]
        assert "todoist" in data["mcpServers"]

    def test_explicit_config_overrides_exclude(self):
        runner = ClaudeRunner(
            work_dir="/tmp",
            mcp_config="/explicit.json",
            mcp_exclude=["telegram"],
        )
        assert runner.effective_mcp_config == "/explicit.json"
