"""MCP server for sending files to Telegram."""
import os
import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("claude-tg")

OUTBOX = (Path(tempfile.gettempdir()) / "claude-tg-outbox").resolve()


@mcp.tool()
async def send_telegram_file(file_path: str, caption: str = "") -> str:
    """Send a file to the user via Telegram.

    For temporary/generated files: save them in the outbox directory first
    (see get_outbox_path), they will be auto-deleted after sending.
    For existing project files: pass the path directly, the file will be preserved.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return "Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set"

    path = Path(file_path).resolve()
    if not path.is_file():
        return f"Error: File not found: {file_path}"

    from telegram import Bot

    bot = Bot(token=token)
    async with bot:
        with path.open("rb") as f:
            await bot.send_document(
                chat_id=int(chat_id),
                document=f,
                filename=path.name,
                caption=caption or None,
            )

    # Auto-delete only files from the outbox temp directory
    try:
        path.relative_to(OUTBOX)
        path.unlink(missing_ok=True)
    except ValueError:
        pass

    return f"File {path.name} sent to Telegram"


@mcp.tool()
def get_outbox_path() -> str:
    """Get the outbox directory path for temporary files. Save generated files here before sending — they will be auto-deleted after delivery."""
    OUTBOX.mkdir(parents=True, exist_ok=True)
    return str(OUTBOX)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
