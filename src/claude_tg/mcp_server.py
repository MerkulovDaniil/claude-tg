"""MCP server for sending files and reading conversation history."""
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .conversation_log import ConversationLog

mcp = FastMCP("claude-tg")


@mcp.tool()
async def send_telegram_file(file_path: str, caption: str = "", temp_file: bool = True) -> str:
    """Send a file to the user via Telegram.

    temp_file=True (default): file was created specifically for sending and will be deleted after delivery.
    temp_file=False: file is part of the project and will be preserved.
    """
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

    if temp_file:
        path.unlink(missing_ok=True)

    return f"File {path.name} sent to Telegram"


@mcp.tool()
async def get_conversation_context(limit: int = 30, max_chars: int = 20000) -> str:
    """Get recent Telegram conversation history — messages the user sees in chat.

    Includes: user messages, Feanor responses, trigger prompts (heartbeat/worker),
    and DIRECT alerts. Use this to understand the full dialog context.
    """
    work_dir = os.environ.get("CLAUDE_WORK_DIR", os.getcwd())
    log = ConversationLog(work_dir)
    context = log.format_context(limit=limit, max_chars=max_chars)
    return context or "(no conversation history yet)"


def main():
    mcp.run()


if __name__ == "__main__":
    main()
