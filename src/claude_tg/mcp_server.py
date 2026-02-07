"""MCP server for sending files to Telegram."""
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("claude-tg")


@mcp.tool()
async def send_telegram_file(file_path: str, caption: str = "", delete_after: bool = True) -> str:
    """Send a file to the user via Telegram. Use when the user asks to receive or download a file. Set delete_after=False when sending existing project files that should be preserved."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return "Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set"

    path = Path(file_path)
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
    if delete_after:
        path.unlink(missing_ok=True)
    return f"File {path.name} sent to Telegram"


def main():
    mcp.run()


if __name__ == "__main__":
    main()
