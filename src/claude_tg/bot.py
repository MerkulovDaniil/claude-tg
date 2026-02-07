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
