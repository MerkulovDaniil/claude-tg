"""Tests for Telegram streaming and message chaining."""
import pytest
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
        assert len(completed) <= 60
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
