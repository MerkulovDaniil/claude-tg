"""Handle incoming photos and files from Telegram."""
import os
import time
import asyncio
import logging
import tempfile
from pathlib import Path

from telegram import PhotoSize, Document, Voice

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


class MediaHandler:
    """Download, track, and clean up user-uploaded media."""

    def __init__(self, upload_dir: str | None = None):
        self.upload_dir = upload_dir or os.path.join(
            tempfile.gettempdir(), "claude-tg-uploads"
        )
        os.makedirs(self.upload_dir, exist_ok=True)
        self._files: list[str] = []
        self._meta: dict[str, dict] = {}  # local_path → {file_id, filename, kind}

    def get_meta(self, local_path: str) -> dict | None:
        return self._meta.get(local_path)

    @staticmethod
    async def _get_file(file_id: str, bot, attempts: int = 3):
        """bot.get_file с ретраями — getFile часто транзиентно падает по сети."""
        for attempt in range(attempts):
            try:
                return await bot.get_file(file_id)
            except Exception as e:
                if attempt < attempts - 1:
                    logger.warning(f"get_file attempt {attempt+1} failed: {e}, retrying...")
                    await asyncio.sleep(1)
                else:
                    raise

    async def save_photo(self, photo: PhotoSize, bot) -> str:
        """Download a photo and return local path."""
        file = await self._get_file(photo.file_id, bot)
        ext = Path(file.file_path).suffix if file.file_path else ".jpg"
        local_path = os.path.join(self.upload_dir, f"photo_{photo.file_unique_id}{ext}")
        await file.download_to_drive(local_path)
        self._files.append(local_path)
        self._meta[local_path] = {
            "file_id": photo.file_id,
            "filename": os.path.basename(local_path),
            "kind": "photo",
        }
        logger.info(f"Saved photo: {local_path}")
        return local_path

    async def save_document(self, doc: Document, bot) -> str:
        """Download a document and return local path."""
        file = await self._get_file(doc.file_id, bot)
        filename = doc.file_name or f"file_{doc.file_unique_id}"
        local_path = os.path.join(self.upload_dir, filename)
        await file.download_to_drive(local_path)
        self._files.append(local_path)
        self._meta[local_path] = {
            "file_id": doc.file_id,
            "filename": filename,
            "kind": "document",
        }
        logger.info(f"Saved document: {local_path}")
        return local_path

    async def save_voice(self, voice: Voice, bot) -> str:
        """Download a voice message and return local path."""
        file = await self._get_file(voice.file_id, bot)
        local_path = os.path.join(self.upload_dir, f"voice_{voice.file_unique_id}.ogg")
        await file.download_to_drive(local_path)
        self._files.append(local_path)
        self._meta[local_path] = {
            "file_id": voice.file_id,
            "filename": os.path.basename(local_path),
            "kind": "voice",
        }
        logger.info(f"Saved voice: {local_path}")
        return local_path

    async def redownload(self, file_id: str, filename: str, bot) -> str:
        """Re-download a file by its Telegram file_id (for recovering wiped uploads)."""
        file = await self._get_file(file_id, bot)
        local_path = os.path.join(self.upload_dir, filename)
        await file.download_to_drive(local_path)
        self._files.append(local_path)
        self._meta[local_path] = {
            "file_id": file_id,
            "filename": filename,
            "kind": "redownload",
        }
        logger.info(f"Redownloaded: {local_path}")
        return local_path

    async def transcribe_voice(self, ogg_path: str, api_key: str) -> str:
        """Transcribe voice message using Groq Whisper API."""
        from groq import Groq

        client = Groq(api_key=api_key)
        with open(ogg_path, "rb") as f:
            transcription = client.audio.transcriptions.create(
                file=(os.path.basename(ogg_path), f),
                model="whisper-large-v3",
            )
        return transcription.text

    def build_prompt(self, text: str, photo_paths: list[str], doc_paths: list[str]) -> str:
        """Build a prompt that includes references to uploaded files."""
        parts = []
        for path in photo_paths:
            parts.append(f"[User sent a photo: {path}]")
        for path in doc_paths:
            parts.append(f"[User sent a file: {path}]")
        if text:
            parts.append(text)
        return "\n".join(parts) if parts else text

    def cleanup(self, keep: list[str] | None = None):
        """Remove tracked files except those in `keep`.

        Files in `keep` (e.g. current buffer) survive cleanup — protects against
        wiping a file that was just downloaded for a turn that's about to start.
        """
        keep_set = set(keep or [])
        survivors: list[str] = []
        for path in self._files:
            if path in keep_set:
                survivors.append(path)
                continue
            try:
                os.remove(path)
                logger.debug(f"Cleaned up: {path}")
            except OSError:
                pass
        self._files = survivors

    def cleanup_all(self, max_age_seconds: int = 86400):
        """Remove tracked files and stale files in upload dir.

        Files younger than `max_age_seconds` are kept — protects against wiping
        a file that arrived seconds before a bot restart, before the new session
        could read it. Default 24h.
        """
        # Wipe tracked files unconditionally except recent ones
        keep_recent: list[str] = []
        cutoff = time.time() - max_age_seconds
        for path in list(self._files):
            try:
                if os.path.getmtime(path) > cutoff:
                    keep_recent.append(path)
                    continue
            except OSError:
                pass
        self.cleanup(keep=keep_recent)

        # Also wipe stray files in upload dir (not tracked by this instance),
        # but only if older than cutoff.
        try:
            for f in os.listdir(self.upload_dir):
                fp = os.path.join(self.upload_dir, f)
                try:
                    if os.path.getmtime(fp) <= cutoff:
                        os.remove(fp)
                        logger.debug(f"Cleaned up stale: {fp}")
                except OSError:
                    pass
        except OSError:
            pass
