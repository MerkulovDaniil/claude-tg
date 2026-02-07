"""Tests for the MCP server send_telegram_file tool."""
import os
import asyncio
import tempfile
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from claude_tg.mcp_server import send_telegram_file


@pytest.fixture
def tmp_file(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    return f


class TestSendTelegramFile:
    def test_missing_token(self):
        env = {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "123"}
        with patch.dict(os.environ, env, clear=False):
            result = asyncio.run(send_telegram_file("/tmp/x.txt"))
        assert "Error" in result
        assert "TELEGRAM_BOT_TOKEN" in result

    def test_missing_chat_id(self):
        env = {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": ""}
        with patch.dict(os.environ, env, clear=False):
            result = asyncio.run(send_telegram_file("/tmp/x.txt"))
        assert "Error" in result

    def test_file_not_found(self):
        env = {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}
        with patch.dict(os.environ, env, clear=False):
            result = asyncio.run(send_telegram_file("/nonexistent/file.txt"))
        assert "File not found" in result

    def test_successful_send(self, tmp_file):
        env = {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}
        mock_bot = MagicMock()
        mock_bot.send_document = AsyncMock()
        mock_bot.__aenter__ = AsyncMock(return_value=mock_bot)
        mock_bot.__aexit__ = AsyncMock(return_value=False)

        with patch.dict(os.environ, env, clear=False), \
             patch("telegram.Bot", return_value=mock_bot) as mock_cls:
            # Move import inside so patch applies
            result = asyncio.run(send_telegram_file(str(tmp_file), caption="test"))

        mock_cls.assert_called_once_with(token="tok")
        mock_bot.send_document.assert_called_once()
        call_kwargs = mock_bot.send_document.call_args[1]
        assert call_kwargs["chat_id"] == 123
        assert call_kwargs["filename"] == "test.txt"
        assert call_kwargs["caption"] == "test"
        assert "sent to Telegram" in result

    def test_send_without_caption(self, tmp_file):
        env = {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}
        mock_bot = MagicMock()
        mock_bot.send_document = AsyncMock()
        mock_bot.__aenter__ = AsyncMock(return_value=mock_bot)
        mock_bot.__aexit__ = AsyncMock(return_value=False)

        with patch.dict(os.environ, env, clear=False), \
             patch("telegram.Bot", return_value=mock_bot):
            result = asyncio.run(send_telegram_file(str(tmp_file)))

        call_kwargs = mock_bot.send_document.call_args[1]
        assert call_kwargs["caption"] is None
        assert "sent to Telegram" in result

    def test_telegram_error(self, tmp_file):
        env = {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}
        mock_bot = MagicMock()
        mock_bot.send_document = AsyncMock(side_effect=Exception("API error"))
        mock_bot.__aenter__ = AsyncMock(return_value=mock_bot)
        mock_bot.__aexit__ = AsyncMock(return_value=False)

        with patch.dict(os.environ, env, clear=False), \
             patch("telegram.Bot", return_value=mock_bot):
            with pytest.raises(Exception, match="API error"):
                asyncio.run(send_telegram_file(str(tmp_file)))
