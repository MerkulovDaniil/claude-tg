"""Persistent conversation log — unified history of all messages in the TG chat.

Captures everything the user sees in Telegram: their messages, trigger prompts,
DIRECT alerts, and Feanor's responses. Skills/heartbeat/worker read this to get
the same context the user has.
"""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path


class ConversationLog:
    """Append-only JSONL conversation log with reading support."""

    def __init__(self, work_dir: str, filename: str = "data/conversation_log.jsonl"):
        self.path = Path(work_dir) / filename
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, entry: dict):
        entry["ts"] = datetime.now(timezone.utc).isoformat()
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def log_user(self, text: str):
        """User message from Telegram."""
        self._write({"role": "user", "text": text})

    def log_assistant(self, text: str):
        """Feanor's response (final text shown in TG)."""
        if text.strip():
            self._write({"role": "assistant", "text": text})

    def log_trigger(self, text: str, source: str = ""):
        """Trigger prompt (heartbeat, worker, morning, evening, etc)."""
        entry = {"role": "trigger", "text": text}
        if source:
            entry["source"] = source
        self._write(entry)

    def log_direct(self, text: str, source: str = ""):
        """DIRECT message (sent to TG without Claude processing)."""
        entry = {"role": "direct", "text": text}
        if source:
            entry["source"] = source
        self._write(entry)

    def get_recent(self, limit: int = 50, max_chars: int = 30000) -> list[dict]:
        """Read recent entries, respecting both count and size limits."""
        if not self.path.exists():
            return []

        # Read from the end efficiently
        lines = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return []

        # Take last `limit` lines
        recent_lines = lines[-limit:]

        entries = []
        total_chars = 0
        for line in reversed(recent_lines):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            text_len = len(entry.get("text", ""))
            if total_chars + text_len > max_chars and entries:
                break
            entries.append(entry)
            total_chars += text_len

        entries.reverse()
        return entries

    def format_context(self, limit: int = 30, max_chars: int = 20000) -> str:
        """Format recent messages as readable context for injection into prompts."""
        entries = self.get_recent(limit=limit, max_chars=max_chars)
        if not entries:
            return ""

        lines = []
        for e in entries:
            role = e.get("role", "?")
            text = e.get("text", "")
            ts = e.get("ts", "")
            # Compact timestamp: just HH:MM
            time_str = ""
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                    time_str = dt.strftime("%H:%M")
                except ValueError:
                    pass

            # Truncate very long messages
            if len(text) > 500:
                text = text[:500] + "…"

            prefix = {"user": "👤", "assistant": "🤖", "trigger": "📥", "direct": "📢"}.get(role, "?")
            source = e.get("source", "")
            source_tag = f" [{source}]" if source else ""
            lines.append(f"[{time_str}] {prefix}{source_tag} {text}")

        return "\n".join(lines)
