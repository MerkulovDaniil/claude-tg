"""Telegram message streaming with rate limiting and message chaining."""
import os
import time
import random
import asyncio
import logging
from telegram import Message, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest

from .formatter import md_to_html

logger = logging.getLogger(__name__)

# Rich Messages (Bot API 10.3): Telegram renders GFM markdown natively — tables,
# headings, LaTeX, task lists, <details>. Claude already writes GFM, so we hand it
# over as is instead of squeezing it into the old HTML subset. PTB 22.x doesn't
# know rich_message, hence the raw request. CLAUDE_TG_RICH=0 turns it off.
RICH_ENABLED = os.environ.get("CLAUDE_TG_RICH", "1") != "0"

# Native streaming (Bot API 10.4): the reply grows in an ephemeral draft
# (sendRichMessageDraft) with Telegram's own stop button instead of a
# "⏳ Thinking..." message that we keep editing. A draft lives ~30 s, so it is
# re-sent while tools run; the finished text is persisted with sendRichMessage.
# If Telegram rejects drafts, the stream falls back to the edit path.
# CLAUDE_TG_DRAFT=0 turns it off.
DRAFT_ENABLED = RICH_ENABLED and os.environ.get("CLAUDE_TG_DRAFT", "1") != "0"
DRAFT_KEEPALIVE = 20.0
THINKING_TAG = "<tg-thinking>Thinking...</tg-thinking>"


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

    # Atomic-message delimiter — same marker pulse.sh splits on. When it appears
    # in the streamed text, the buffer before it is finalized as its own Telegram
    # message and a fresh one starts. Keeps the convention uniform: ===MSG=== in
    # the model output → separate messages everywhere, not literal text in chat.
    SPLIT_MARKER = "===MSG==="

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
        # Draft mode state
        self.draft_mode = DRAFT_ENABLED
        self.draft_id: int | None = None
        self._draft_ids: set[int] = set()
        self._draft_text = ""
        self._draft_sent_at = 0.0
        self._keepalive_task: asyncio.Task | None = None
        self._closed = False

    async def start(self) -> Message | None:
        if self.draft_mode:
            self._new_draft()
            if await self._send_draft(self._draft_view()):
                self._keepalive_task = asyncio.create_task(self._keepalive())
                return None
            self.draft_mode = False
        self._current_msg = await self.bot.send_message(chat_id=self.chat_id, text="⏳ Thinking...", reply_markup=self.reply_markup)
        self._first_msg = self._current_msg
        return self._current_msg

    # --- Draft mode -------------------------------------------------------

    def owns_draft(self, draft_id) -> bool:
        return draft_id in self._draft_ids

    def _new_draft(self):
        self.draft_id = random.randint(1, 2**31 - 1)
        self._draft_ids.add(self.draft_id)

    async def _send_draft(self, markdown: str) -> bool:
        try:
            await self.bot.do_api_request("sendRichMessageDraft", api_kwargs={
                "chat_id": self.chat_id, "draft_id": self.draft_id,
                "rich_message": {"markdown": markdown}, "can_stop": True,
            })
        except Exception as e:
            logger.warning(f"Draft send failed: {e} (text length: {len(markdown)})")
            return False
        self._draft_text = markdown
        self._draft_sent_at = time.time()
        return True

    def _draft_view(self) -> str:
        display = self.chain.render().rstrip()
        body = f"{display}\n\n{THINKING_TAG}" if display else THINKING_TAG
        return f"{body}\n\n{self._stop_row()}"

    def _stop_row(self) -> str:
        # Своя кнопка «стоп» в черновике: нативную (can_stop, Bot API 10.4 от
        # 09.11.2026) клиенты Дани 16.11 не показывали — он остался без отмены.
        # draft_id в data: нажатие на чужой/старый черновик не убьёт новый ход.
        return ('<tg-button-row align="right"><tg-button type="callback_data" '
                f'style="danger" data="claude_cancel:{self.draft_id}">🛑 Стоп</tg-button>'
                '</tg-button-row>')

    async def _push_draft(self):
        """Show the current buffer as a draft; on failure switch to the edit path."""
        if await self._send_draft(self._draft_view()):
            return
        logger.warning("Drafts rejected — falling back to message edits")
        self.draft_mode = False
        self._stop_keepalive()
        self._current_msg = await self.bot.send_message(chat_id=self.chat_id, text="⏳ ...", reply_markup=self.reply_markup)
        self._first_msg = self._current_msg
        display = self.chain.render()
        if display.strip():
            await self._edit_message(self._current_msg, display, reply_markup=self.reply_markup)

    async def _keepalive(self):
        """Re-send the draft before Telegram drops it (long tool calls, no text)."""
        try:
            while True:
                await asyncio.sleep(5)
                if self._closed or not self.draft_mode:
                    return
                if time.time() - self._draft_sent_at < DRAFT_KEEPALIVE:
                    continue
                async with self._lock:
                    if self._closed or not self.draft_mode:
                        return
                    await self._send_draft(self._draft_text or THINKING_TAG)
        except asyncio.CancelledError:
            pass

    def _stop_keepalive(self):
        if self._keepalive_task and self._keepalive_task is not asyncio.current_task():
            self._keepalive_task.cancel()
        self._keepalive_task = None

    async def _send_final(self, text: str):
        """Persist a finished chunk: rich → HTML → plain text."""
        if RICH_ENABLED:
            try:
                await self.bot.do_api_request("sendRichMessage", api_kwargs={
                    "chat_id": self.chat_id, "rich_message": {"markdown": text}})
                return
            except Exception as e:
                logger.warning(f"Rich send failed, falling back to HTML: {e} (text length: {len(text)})")
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=md_to_html(text),
                                        parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            return
        except Exception as e:
            logger.warning(f"HTML send failed: {e}")
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=text[:4096], disable_web_page_preview=True)
        except Exception as e:
            logger.error(f"All send methods failed: {e}")

    async def push_text(self, text: str):
        self.chain.append_text(text)
        self._dirty = True
        # Split the stream into separate messages on ===MSG===. A delimiter that
        # straddles two deltas (e.g. "===MS" then "G===") just matches once the
        # remainder arrives — `in` is False until then, so nothing leaks.
        while self.SPLIT_MARKER in self.chain._current:
            before, after = self.chain._current.split(self.SPLIT_MARKER, 1)
            if before.strip():
                self.chain._current = before
                await self.start_new_message()  # finalize `before`, open fresh placeholder
            self.chain._current = after  # drop the delimiter; continue with the rest
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
            if self.draft_mode:
                if not self._dirty or self._closed:
                    return
                if self.chain.needs_new_message:
                    await self._send_final(self.chain.complete_current())
                    self._new_draft()
                await self._push_draft()
                self._last_update = time.time()
                self._dirty = False
                return
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

    async def start_new_message(self):
        """Finalize current message and start a fresh one for continued output."""
        async with self._lock:
            if self.draft_mode:
                if self._closed:
                    return
                display = self.chain.render()
                if display.strip():
                    await self._send_final(display)
                self.chain = MessageChain()
                self._dirty = False
                self._last_update = 0.0
                self._new_draft()
                await self._push_draft()
                return
            display = self.chain.render()
            if display.strip() and self._current_msg:
                await self._edit_message(self._current_msg, display, reply_markup=None)
            elif self._current_msg:
                try:
                    await self._current_msg.delete()
                except Exception:
                    pass

            # Reset for new content
            self.chain = MessageChain()
            self._dirty = False
            self._last_update = 0.0

            self._current_msg = await self.bot.send_message(
                chat_id=self.chat_id,
                text="⏳ ...",
                reply_markup=self.reply_markup,
            )
            self._first_msg = self._current_msg

    async def finalize(self, footer: str = "", cancelled: bool = False):
        async with self._lock:
            if self.draft_mode:
                if self._closed:
                    return  # cancel already finalized this turn
                self._closed = True
                self._stop_keepalive()
            if cancelled:
                self.chain._current = "🛑 Cancelled\n\n" + self.chain._current
            if footer:
                self.chain.set_footer(footer)

            # Silent pulse: treat bare "---" as no content
            raw = self.chain._current.strip()
            if raw.strip("-") == "" and len(raw) <= 5 and raw:
                if self._current_msg:
                    try:
                        await self._current_msg.delete()
                    except Exception:
                        pass
                return

            has_content = bool(self.chain._current.strip() or self.chain._chunks)
            display = self.chain.render()

            if self.draft_mode:
                # Draft vanishes by itself once a message is sent (or in ~30 s).
                if self.chain._current.strip() and display.strip():
                    await self._send_final(display)
                return

            if has_content and display.strip() and self._current_msg:
                await self._edit_message(self._current_msg, display, reply_markup=None)
            elif self._current_msg:
                # No real content (footer-only or empty) — delete placeholder
                try:
                    await self._current_msg.delete()
                except Exception:
                    pass

    async def _edit_rich(self, msg: Message, text: str, reply_markup: InlineKeyboardMarkup | None) -> bool:
        """Edit as a rich message. True = done (or nothing changed), False = use the HTML path."""
        kwargs = {"chat_id": self.chat_id, "message_id": msg.message_id,
                  "rich_message": {"markdown": text}}
        if reply_markup is not None:
            kwargs["reply_markup"] = reply_markup.to_dict()
        try:
            await self.bot.do_api_request("editMessageText", api_kwargs=kwargs)
            return True
        except BadRequest as e:
            if "message is not modified" in str(e).lower():
                return True
            logger.warning(f"Rich edit failed, falling back to HTML: {e} (text length: {len(text)})")
        except Exception as e:
            logger.warning(f"Rich edit error, falling back to HTML: {e}")
        return False

    async def _edit_message(self, msg: Message, text: str, reply_markup: InlineKeyboardMarkup | None):
        if RICH_ENABLED and await self._edit_rich(msg, text, reply_markup):
            return
        try:
            html_text = md_to_html(text)
            await msg.edit_text(html_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup, disable_web_page_preview=True)
            return
        except BadRequest as e:
            if "message is not modified" in str(e).lower():
                return
            logger.warning(f"HTML edit failed: {e} (text length: {len(text)})")
        except Exception as e:
            logger.warning(f"HTML edit error: {e}")

        # Fallback: plain text (no parse_mode)
        try:
            await msg.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
            return
        except BadRequest as e:
            if "message is not modified" in str(e).lower():
                return
            logger.warning(f"Plain text edit failed: {e}")
        except Exception as e:
            logger.warning(f"Plain text edit error: {e}")

        # Last resort: send new message
        try:
            self._current_msg = await self.bot.send_message(
                chat_id=self.chat_id, text=text[:4096], reply_markup=reply_markup,
            )
            logger.info("Fell back to sending new message")
        except Exception as e:
            logger.error(f"All message methods failed: {e}")
