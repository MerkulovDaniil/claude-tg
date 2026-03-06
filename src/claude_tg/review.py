"""Generic Tinder-style artifact review system.

Presents items from configured sources one-by-one with inline buttons.
All domain knowledge comes from {work_dir}/review_sources.json — this
module has zero knowledge of what is being reviewed.
"""

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Callback data prefix — all review callbacks start with "rv:"
CB_PREFIX = "rv:"

# Lines starting with these prefixes are stripped from captions
_HEADER_PREFIXES = ("#", "**", "---", "## ")


@dataclass
class ReviewSource:
    """A configured source of reviewable artifacts."""

    id: str
    name: str
    dir: str
    patterns: dict  # {"text": "{slug}_post.md", "video": "...", "extra": [...]}
    actions: dict[str, str]  # button_label -> destination_dir
    preview: str = "video"  # "video", "document", "text"

    def discover(self) -> list["Artifact"]:
        """Scan directory for artifacts matching the text pattern."""
        if not os.path.isdir(self.dir):
            return []

        text_tpl = self.patterns.get("text", "")
        if not text_tpl:
            return []

        # Extract slug by matching the text pattern against actual files
        prefix = text_tpl.split("{slug}")[0]
        suffix = text_tpl.split("{slug}")[1] if "{slug}" in text_tpl else ""

        artifacts = []
        for entry in sorted(os.listdir(self.dir)):
            if entry.startswith(prefix) and entry.endswith(suffix):
                slug = entry[len(prefix) : len(entry) - len(suffix) if suffix else len(entry)]
                if not slug:
                    continue
                artifact = self._build_artifact(slug)
                if artifact:
                    artifacts.append(artifact)
        return artifacts

    def count(self) -> int:
        return len(self.discover())

    def _build_artifact(self, slug: str) -> "Artifact | None":
        """Build an Artifact if its required text file exists."""
        files = {}
        for key, tpl in self.patterns.items():
            if key == "extra":
                continue
            path = os.path.join(self.dir, tpl.format(slug=slug))
            if os.path.isfile(path):
                files[key] = path
        if "text" not in files:
            return None
        # Add extra files if they exist
        for tpl in self.patterns.get("extra", []):
            path = os.path.join(self.dir, tpl.format(slug=slug))
            if os.path.isfile(path):
                files[f"extra:{tpl}"] = path
        return Artifact(slug=slug, source=self, files=files)

    def get_artifact(self, slug: str) -> "Artifact | None":
        return self._build_artifact(slug)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract JSON frontmatter from between --- markers. Returns (meta, body)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    fm_raw = text[3:end].strip()
    body = text[end + 3:].lstrip("\n")
    try:
        meta = json.loads(fm_raw)
    except (json.JSONDecodeError, ValueError):
        return {}, text
    return meta, body


@dataclass
class Artifact:
    """A single reviewable item."""

    slug: str
    source: ReviewSource
    files: dict[str, str]  # key -> absolute path
    _meta: dict = field(default_factory=dict, repr=False)
    _body: str = field(default="", repr=False)
    _parsed: bool = field(default=False, repr=False)

    def _ensure_parsed(self):
        if self._parsed:
            return
        self._parsed = True
        text_path = self.files.get("text")
        if not text_path:
            return
        try:
            raw = Path(text_path).read_text(encoding="utf-8")
        except OSError:
            return
        self._meta, self._body = _parse_frontmatter(raw)

    @property
    def meta(self) -> dict:
        self._ensure_parsed()
        return self._meta

    @property
    def title(self) -> str:
        name = self.meta.get("title")
        if name:
            return name
        return self.slug.replace("_", " ").title()

    def get_actions(self) -> dict[str, str] | None:
        """Per-item actions from frontmatter, or None to use source defaults."""
        return self.meta.get("actions")

    def read_caption(self, max_len: int = 800) -> str:
        """Read summary from frontmatter or extract from body."""
        self._ensure_parsed()
        summary = self._meta.get("summary")
        if summary:
            return summary

        body = self._body
        if not body:
            return self.title

        lines = body.split("\n")
        body_lines = []
        in_header = True
        for line in lines:
            stripped = line.strip()
            if in_header:
                if not stripped or any(stripped.startswith(p) for p in _HEADER_PREFIXES):
                    continue
                in_header = False
            body_lines.append(line)

        clean = "\n".join(body_lines).strip()
        if len(clean) > max_len:
            clean = clean[:max_len].rsplit("\n", 1)[0] + "\n..."
        return clean or self.title


@dataclass
class ReviewSession:
    """Persisted review state."""

    source_id: str = ""
    queue: list[str] = field(default_factory=list)
    current_index: int = 0
    decisions: dict = field(default_factory=dict)

    def save(self, state_path: str):
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "source_id": self.source_id,
                    "queue": self.queue,
                    "current_index": self.current_index,
                    "decisions": self.decisions,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

    @classmethod
    def load(cls, state_path: str) -> "ReviewSession":
        session = cls()
        if not os.path.isfile(state_path):
            return session
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            session.source_id = data.get("source_id", "")
            session.queue = data.get("queue", [])
            session.current_index = data.get("current_index", 0)
            session.decisions = data.get("decisions", {})
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load review state: %s", e)
        return session

    def build_queue(self, source: ReviewSource):
        self.source_id = source.id
        decided = set(self.decisions.get(source.id, {}).keys())
        pending = [a for a in source.discover() if a.slug not in decided]
        # Sort by priority (lower = more urgent, default 3)
        pending.sort(key=lambda a: a.meta.get("priority", 3))
        self.queue = [a.slug for a in pending]
        self.current_index = 0

    @property
    def current_slug(self) -> str | None:
        if 0 <= self.current_index < len(self.queue):
            return self.queue[self.current_index]
        return None

    @property
    def remaining(self) -> int:
        return max(0, len(self.queue) - self.current_index)

    def advance(self):
        self.current_index += 1

    def record(self, source_id: str, slug: str, action: str):
        if source_id not in self.decisions:
            self.decisions[source_id] = {}
        self.decisions[source_id][slug] = {
            "action": action,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self.advance()


def _load_sources(config_path: str) -> list[ReviewSource]:
    if not os.path.isfile(config_path):
        return []
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return [
            ReviewSource(
                id=s["id"],
                name=s["name"],
                dir=s["dir"],
                patterns=s["pattern"],
                actions=s["actions"],
                preview=s.get("preview", "video"),
            )
            for s in raw
        ]
    except (json.JSONDecodeError, KeyError, OSError) as e:
        logger.error("Failed to load review_sources.json: %s", e)
        return []


def _move_artifact(artifact: Artifact, dest_dir: str):
    """Move all artifact files to destination."""
    os.makedirs(dest_dir, exist_ok=True)
    for path in artifact.files.values():
        if os.path.isfile(path):
            dst = os.path.join(dest_dir, os.path.basename(path))
            shutil.move(path, dst)
            logger.info("Moved %s -> %s", path, dst)


class ReviewHandler:
    """Handles /review command and inline button callbacks."""

    def __init__(self, work_dir: str, chat_id: int):
        self.work_dir = work_dir
        self.chat_id = chat_id
        self._config_path = os.path.join(work_dir, "review_sources.json")
        self._state_path = os.path.join(work_dir, "data", "review_state.json")
        self._session: ReviewSession | None = None
        self._sources: list[ReviewSource] | None = None

    def _get_sources(self) -> list[ReviewSource]:
        # Reload config each time to pick up changes
        self._sources = _load_sources(self._config_path)
        return self._sources

    def _get_session(self) -> ReviewSession:
        if self._session is None:
            self._session = ReviewSession.load(self._state_path)
        return self._session

    def _save_session(self):
        if self._session:
            self._session.save(self._state_path)

    def _find_source(self, source_id: str) -> ReviewSource | None:
        for s in self._get_sources():
            if s.id == source_id:
                return s
        return None

    async def cmd_review(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id != self.chat_id:
            return

        args = context.args or []

        # /review reset — clear state
        if args and args[0] == "reset":
            self._session = ReviewSession()
            self._save_session()
            await update.message.reply_text("🔄 Review state cleared.")
            return

        sources = self._get_sources()
        if not sources:
            await update.message.reply_text("⚙️ No review sources configured.\nAdd review_sources.json to work directory.")
            return

        # Filter to sources that have items
        available = [(s, s.count()) for s in sources]
        available = [(s, c) for s, c in available if c > 0]

        if not available:
            await update.message.reply_text("📭 Nothing to review — all sources empty.")
            return

        # Single source — start directly
        if len(available) == 1:
            source, count = available[0]
            session = self._get_session()
            session.build_queue(source)
            self._save_session()
            await update.message.reply_text(
                f"🎬 <b>{source.name}</b> — {count} items\n"
                f"Use the buttons below each item.",
                parse_mode=ParseMode.HTML,
            )
            await self._send_current(context.bot, update.effective_chat.id)
            return

        # Multiple sources — show picker
        buttons = []
        for source, count in available:
            buttons.append(
                [InlineKeyboardButton(f"{source.name} ({count})", callback_data=f"{CB_PREFIX}src:{source.id}")]
            )
        await update.message.reply_text(
            "📋 Choose a source to review:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    async def cmd_review_item(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /review_<slug> — direct review of a specific item."""
        if update.effective_chat.id != self.chat_id:
            return

        text = update.message.text or ""
        slug = text.split()[0].removeprefix("/review_")
        if not slug:
            await update.message.reply_text("❌ Usage: /review_<item_name>")
            return

        # Search across all sources for this slug
        sources = self._get_sources()
        artifact = None
        source = None
        for s in sources:
            a = s.get_artifact(slug)
            if a:
                artifact = a
                source = s
                break

        if not artifact or not source:
            await update.message.reply_text(f"❌ Item <code>{slug}</code> not found.", parse_mode=ParseMode.HTML)
            return

        # Set up a one-item session so callbacks work
        session = self._get_session()
        session.source_id = source.id
        session.queue = [slug]
        session.current_index = 0
        self._save_session()

        await self._send_current(context.bot, update.effective_chat.id)

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if query.from_user.id != self.chat_id:
            await query.answer()
            return

        data = query.data.removeprefix(CB_PREFIX)
        chat_id = query.message.chat_id
        session = self._get_session()

        # Source selection
        if data.startswith("src:"):
            await query.answer()
            source_id = data[4:]
            source = self._find_source(source_id)
            if not source:
                await query.edit_message_text("❌ Source not found.")
                return
            session.build_queue(source)
            self._save_session()
            await query.edit_message_text(
                f"🎬 <b>{source.name}</b> — {session.remaining} items",
                parse_mode=ParseMode.HTML,
            )
            await self._send_current(context.bot, chat_id)
            return

        # Stop
        if data == "stop":
            await query.answer("⏸ Paused")
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            await context.bot.send_message(
                chat_id,
                f"⏸ Paused. {session.remaining} remaining.\n/review to continue.",
            )
            return

        # Skip
        if data == "skip":
            slug = session.current_slug
            if slug:
                session.record(session.source_id, slug, "skip")
                self._save_session()
            await query.answer("⏭")
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            await self._send_current(context.bot, chat_id)
            return

        # Action button: act:{index}
        if data.startswith("act:"):
            action_idx = int(data[4:])
            source = self._find_source(session.source_id)
            if not source:
                await query.answer("❌ Source lost")
                return

            slug = session.current_slug
            artifact = source.get_artifact(slug) if slug else None

            # Per-item actions take priority over source defaults
            actions = (artifact.get_actions() if artifact else None) or source.actions
            action_labels = list(actions.keys())
            if action_idx >= len(action_labels):
                await query.answer("❌ Unknown action")
                return

            label = action_labels[action_idx]
            dest = actions[label]

            if slug:
                if artifact:
                    _move_artifact(artifact, dest)
                session.record(session.source_id, slug, label)
                self._save_session()

            await query.answer(label)
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            await self._send_current(context.bot, chat_id)
            return

        await query.answer()

    async def _send_current(self, bot: Bot, chat_id: int):
        """Send the current artifact or finish message."""
        session = self._get_session()
        source = self._find_source(session.source_id)

        if not source or session.current_slug is None:
            # Queue finished
            stats = self._format_stats(session)
            await bot.send_message(chat_id, f"🏁 Review complete!\n\n{stats}")
            return

        slug = session.current_slug
        artifact = source.get_artifact(slug)

        if artifact is None:
            # File removed externally — skip
            session.advance()
            self._save_session()
            await self._send_current(bot, chat_id)
            return

        pos = session.current_index + 1
        total = len(session.queue)
        caption_body = artifact.read_caption(max_len=800)
        prio = artifact.meta.get("priority", 3)
        prio_badge = {1: "🔴", 2: "🟡", 3: "⚪"}.get(prio, "⚪")
        header = f"{prio_badge} [{pos}/{total}]  <b>{artifact.title}</b>\n\n"
        caption = header + caption_body

        # Per-item actions (from frontmatter) take priority over source defaults
        item_actions = artifact.get_actions() or source.actions
        action_labels = list(item_actions.keys())

        # Split into rows of max 3 buttons each
        action_buttons = [
            InlineKeyboardButton(label, callback_data=f"{CB_PREFIX}act:{i}")
            for i, label in enumerate(action_labels)
        ]
        rows = []
        for i in range(0, len(action_buttons), 3):
            rows.append(action_buttons[i : i + 3])
        rows.append([
            InlineKeyboardButton("⏭ Skip", callback_data=f"{CB_PREFIX}skip"),
            InlineKeyboardButton("🛑 Stop", callback_data=f"{CB_PREFIX}stop"),
        ])
        keyboard = InlineKeyboardMarkup(rows)

        if source.preview == "video" and "video" in artifact.files:
            if len(caption) > 1024:
                caption = caption[:1020] + "..."
            with open(artifact.files["video"], "rb") as f:
                await bot.send_video(
                    chat_id=chat_id,
                    video=f,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                    supports_streaming=True,
                )
        elif source.preview == "document" and "document" in artifact.files:
            if len(caption) > 1024:
                caption = caption[:1020] + "..."
            with open(artifact.files["document"], "rb") as f:
                await bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
        else:
            # Text preview: send file as document + summary with buttons
            text_path = artifact.files.get("text")
            if text_path and os.path.getsize(text_path) > 2000:
                # Large file — send as document with short caption
                short_caption = header + artifact.read_caption(max_len=400)
                if len(short_caption) > 1024:
                    short_caption = short_caption[:1020] + "..."
                with open(text_path, "rb") as f:
                    await bot.send_document(
                        chat_id=chat_id,
                        document=f,
                        caption=short_caption,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard,
                    )
            else:
                if len(caption) > 4000:
                    caption = caption[:4000] + "..."
                await bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )

    def _format_stats(self, session: ReviewSession) -> str:
        source_decisions = session.decisions.get(session.source_id, {})
        if not source_decisions:
            return "No decisions made."
        counts: dict[str, int] = {}
        for d in source_decisions.values():
            action = d["action"]
            counts[action] = counts.get(action, 0) + 1
        lines = [f"{label}: {count}" for label, count in counts.items()]
        return "\n".join(lines)
