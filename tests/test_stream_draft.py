"""Draft-mode streaming (Bot API 10.4 sendRichMessageDraft) with a fake bot."""
import asyncio
import pytest
from telegram import Update

from claude_tg import stream as stream_mod
from claude_tg.stream import TelegramStream, THINKING_TAG


class FakeBot:
    def __init__(self, reject_drafts=False):
        self.calls = []
        self.reject_drafts = reject_drafts
        self.sent = []

    async def do_api_request(self, method, api_kwargs=None):
        if method == "sendRichMessageDraft" and self.reject_drafts:
            raise RuntimeError("METHOD_NOT_ALLOWED")
        self.calls.append((method, api_kwargs))
        return True

    async def send_message(self, chat_id, text, **kw):
        msg = FakeMsg(self)
        self.sent.append(text)
        return msg


class FakeMsg:
    message_id = 1

    def __init__(self, bot):
        self.bot = bot

    async def edit_text(self, *a, **kw):
        pass

    async def delete(self):
        pass


def methods(bot):
    return [m for m, _ in bot.calls]


@pytest.fixture(autouse=True)
def draft_on(monkeypatch):
    monkeypatch.setattr(stream_mod, "DRAFT_ENABLED", True)
    monkeypatch.setattr(stream_mod, "RICH_ENABLED", True)


def test_start_sends_thinking_draft_not_message():
    async def run():
        bot = FakeBot()
        s = TelegramStream(bot, 42, update_interval=0)
        assert await s.start() is None
        assert bot.sent == []
        m, kw = bot.calls[0]
        assert m == "sendRichMessageDraft"
        assert kw["can_stop"] is True and kw["draft_id"] > 0
        assert kw["rich_message"]["markdown"] == THINKING_TAG
        await s.finalize()
    asyncio.run(run())


def test_text_streams_as_draft_and_persists_once():
    async def run():
        bot = FakeBot()
        s = TelegramStream(bot, 42, update_interval=0)
        await s.start()
        await s.push_text("Привет")
        assert bot.calls[-1][1]["rich_message"]["markdown"].startswith("Привет")
        await s.finalize(footer="⏱ 1s")
        await s.finalize(cancelled=True)  # second finalize must not duplicate
        finals = [kw for m, kw in bot.calls if m == "sendRichMessage"]
        assert len(finals) == 1
        assert "Привет" in finals[0]["rich_message"]["markdown"]
        assert "⏱ 1s" in finals[0]["rich_message"]["markdown"]
    asyncio.run(run())


def test_split_marker_persists_first_part_and_new_draft():
    async def run():
        bot = FakeBot()
        s = TelegramStream(bot, 42, update_interval=0)
        await s.start()
        first = s.draft_id
        await s.push_text("один===MSG===два")
        await s.finalize()
        finals = [kw["rich_message"]["markdown"] for m, kw in bot.calls if m == "sendRichMessage"]
        assert finals == ["один", "два"]
        assert s.draft_id != first and s.owns_draft(first)
    asyncio.run(run())


def test_empty_turn_sends_nothing():
    async def run():
        bot = FakeBot()
        s = TelegramStream(bot, 42, update_interval=0)
        await s.start()
        await s.finalize(footer="⏱ 1s")
        assert "sendRichMessage" not in methods(bot)
    asyncio.run(run())


def test_rejected_drafts_fall_back_to_thinking_message():
    async def run():
        bot = FakeBot(reject_drafts=True)
        s = TelegramStream(bot, 42, update_interval=0)
        msg = await s.start()
        assert msg is not None and bot.sent == ["⏳ Thinking..."]
        assert s.draft_mode is False
        await s.finalize()
    asyncio.run(run())


def test_ptb_keeps_unknown_stop_update_in_api_kwargs():
    raw = {"update_id": 7, "stopped_message_generation": {
        "chat": {"id": 42, "type": "private"}, "draft_id": 123}}
    upd = Update.de_json(raw, None)
    assert upd.api_kwargs["stopped_message_generation"]["draft_id"] == 123
