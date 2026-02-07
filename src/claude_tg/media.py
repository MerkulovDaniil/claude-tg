"""Handle incoming photos and files from Telegram."""
import os
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

    async def save_photo(self, photo: PhotoSize, bot) -> str:
        """Download a photo and return local path."""
        file = await bot.get_file(photo.file_id)
        ext = Path(file.file_path).suffix if file.file_path else ".jpg"
        local_path = os.path.join(self.upload_dir, f"photo_{photo.file_unique_id}{ext}")
        await file.download_to_drive(local_path)
        self._files.append(local_path)
        logger.info(f"Saved photo: {local_path}")
        return local_path

    async def save_document(self, doc: Document, bot) -> str:
        """Download a document and return local path."""
        file = await bot.get_file(doc.file_id)
        filename = doc.file_name or f"file_{doc.file_unique_id}"
        local_path = os.path.join(self.upload_dir, filename)
        await file.download_to_drive(local_path)
        self._files.append(local_path)
        logger.info(f"Saved document: {local_path}")
        return local_path

    async def save_voice(self, voice: Voice, bot) -> str:
        """Download a voice message and return local path."""
        file = await bot.get_file(voice.file_id)
        local_path = os.path.join(self.upload_dir, f"voice_{voice.file_unique_id}.ogg")
        await file.download_to_drive(local_path)
        self._files.append(local_path)
        logger.info(f"Saved voice: {local_path}")
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

    def cleanup(self):
        """Remove all tracked files."""
        for path in self._files:
            try:
                os.remove(path)
                logger.debug(f"Cleaned up: {path}")
            except OSError:
                pass
        self._files.clear()

    def cleanup_all(self):
        """Remove entire upload directory contents (for startup cleanup)."""
        self.cleanup()
        try:
            for f in os.listdir(self.upload_dir):
                try:
                    os.remove(os.path.join(self.upload_dir, f))
                except OSError:
                    pass
        except OSError:
            pass
