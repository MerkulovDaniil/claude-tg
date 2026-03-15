"""MCP server for sending files, reading conversation history, and asking user questions."""
import asyncio
import json
import os
import uuid
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


@mcp.tool()
async def ask_user_with_buttons(
    question: str,
    options: list[str],
    multi_select: bool = False,
    timeout: int = 120,
) -> str:
    """Ask the user a question with inline keyboard buttons in Telegram.

    Use this instead of AskUserQuestion when communicating through Telegram.
    Renders buttons that the user can tap. Returns the selected option(s).

    For multi_select=True, user can toggle multiple options and press "Done".
    An "Other" option is always added — if selected, waits for text input.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return "Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set"

    # Create queue file
    qid = uuid.uuid4().hex[:8]
    queue_dir = Path(os.environ.get("CLAUDE_WORK_DIR", os.getcwd())) / "data" / "asking_queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    queue_file = queue_dir / f"{qid}.json"

    queue_data = {
        "id": qid,
        "question": question,
        "options": options,
        "multi_select": multi_select,
        "status": "pending",
        "answer": None,
    }
    queue_file.write_text(json.dumps(queue_data, ensure_ascii=False), encoding="utf-8")

    # Build inline keyboard
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

    buttons = []
    row = []
    for i, opt in enumerate(options):
        label = opt if len(opt) <= 30 else opt[:27] + "..."
        if multi_select:
            label = f"⬜ {label}"
        row.append(InlineKeyboardButton(label, callback_data=f"askq:{qid}:{i}"))
        if len(row) >= 2 or i == len(options) - 1:
            buttons.append(row)
            row = []

    # "Other" button
    buttons.append([InlineKeyboardButton("✏️ Другое", callback_data=f"askq:{qid}:other")])

    if multi_select:
        buttons.append([InlineKeyboardButton("✅ Готово", callback_data=f"askq:{qid}:done")])

    keyboard = InlineKeyboardMarkup(buttons)

    bot = Bot(token=token)
    async with bot:
        await bot.send_message(
            chat_id=int(chat_id),
            text=question,
            reply_markup=keyboard,
        )

    # Poll for answer
    elapsed = 0
    poll_interval = 0.5
    while elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        try:
            data = json.loads(queue_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            continue

        if data.get("status") == "answered":
            answer = data["answer"]
            queue_file.unlink(missing_ok=True)
            if isinstance(answer, list):
                return "Selected: " + ", ".join(answer)
            return answer

    # Timeout
    queue_file.unlink(missing_ok=True)
    return "Пользователь не ответил (timeout)"


def main():
    mcp.run()


if __name__ == "__main__":
    main()
