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
        self._chunks: list[str] = []
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
    """Stream Claude output to Telegram with adaptive rate limiting and automatic message chaining."""

    def __init__(self, bot, chat_id: int, update_interval: float = 2.0, reply_markup: InlineKeyboardMarkup | None = None):
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
        self._current_msg = await self.bot.send_message(chat_id=self.chat_id, text="⏳ Thinking...", reply_markup=self.reply_markup)
        self._first_msg = self._current_msg
        return self._current_msg

    async def push_text(self, text: str):
        self.chain.append_text(text)
        self._dirty = True
        await self._maybe_update()

    async def push_tool_call(self, line: str):
        self.chain.append_tool_call(line)
        self._dirty = True
        await self._maybe_update()

    async def push_tool_result(self, html: str):
        self.chain.append_text(html)
        self._dirty = True
        await self._maybe_update()

    async def _maybe_update(self):
        now = time.time()
        if now - self._last_update < self.update_interval:
            return
        await self._flush()

    async def _flush(self):
        async with self._lock:
            if not self._dirty or not self._current_msg:
                return
            if self.chain.needs_new_message:
                completed = self.chain.complete_current()
                await self._edit_message(self._current_msg, completed, reply_markup=None)
                self._current_msg = await self.bot.send_message(
                    chat_id=self.chat_id, text="⏳ ...", reply_markup=self.reply_markup,
                    reply_to_message_id=self._first_msg.message_id,
                )
            display = self.chain.render()
            if display.strip():
                await self._edit_message(self._current_msg, display, reply_markup=self.reply_markup)
            self._last_update = time.time()
            self._dirty = False

    async def finalize(self, footer: str = "", cancelled: bool = False):
        async with self._lock:
            if cancelled:
                self.chain._current = "🛑 Cancelled\n\n" + self.chain._current
            if footer:
                self.chain.set_footer(footer)
            display = self.chain.render()
            if display.strip() and self._current_msg:
                await self._edit_message(self._current_msg, display, reply_markup=None)

    async def _edit_message(self, msg: Message, text: str, reply_markup: InlineKeyboardMarkup | None):
        try:
            html_text = md_to_html(text)
            await msg.edit_text(html_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup, disable_web_page_preview=True)
        except BadRequest as e:
            if "message is not modified" in str(e).lower():
                return
            try:
                await msg.edit_text(text, reply_markup=reply_markup)
            except BadRequest:
                pass
        except Exception:
            pass
