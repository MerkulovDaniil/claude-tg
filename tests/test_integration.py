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
