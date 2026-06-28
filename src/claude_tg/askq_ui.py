"""Shared rendering for ask_user_with_buttons.

Telegram inline-button labels are shown on a single line and get clipped when long;
putting multiple buttons per row clips them even more. So the FULL option text goes
into the message BODY as a numbered list (never truncated), and the buttons are just
compact numbers that map to those lines. For multi-select, ⬜/✅ marks render both in
the body (authoritative, readable) and on the number buttons.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

NUMS_PER_ROW = 5  # number buttons are short → fit several per row without clipping


def build_ask_text(question: str, options: list[str], selected: list[str], multi_select: bool) -> str:
    lines = [question, ""]
    for i, opt in enumerate(options, 1):
        if multi_select:
            mark = "✅" if opt in selected else "⬜"
            lines.append(f"{mark} {i}. {opt}")
        else:
            lines.append(f"{i}. {opt}")
    if multi_select:
        lines.append("")
        lines.append("Жми номера чтобы отметить, потом «Готово».")
    return "\n".join(lines)


def build_ask_keyboard(qid: str, options: list[str], selected: list[str], multi_select: bool) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i, opt in enumerate(options):
        if multi_select:
            mark = "✅" if opt in selected else ""
            label = f"{mark}{i + 1}"
        else:
            label = str(i + 1)
        row.append(InlineKeyboardButton(label, callback_data=f"askq:{qid}:{i}"))
        if len(row) >= NUMS_PER_ROW or i == len(options) - 1:
            buttons.append(row)
            row = []
    buttons.append([InlineKeyboardButton("✏️ Другое", callback_data=f"askq:{qid}:other")])
    if multi_select:
        buttons.append([InlineKeyboardButton("✅ Готово", callback_data=f"askq:{qid}:done")])
    return InlineKeyboardMarkup(buttons)
