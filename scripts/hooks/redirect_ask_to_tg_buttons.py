#!/usr/bin/env python3
"""PreToolUse hook: in claude-tg sessions, block AskUserQuestion and steer
to mcp__claude-tg__ask_user_with_buttons (renders InlineKeyboardMarkup so the
user sees actual buttons in Telegram).

Detection: own cgroup contains the claude-tg.service unit. Works without any
runner changes because systemd places child processes in the unit's cgroup.

Bypass: if /proc/self/cgroup can't be read (non-systemd / containerised
environment), no-op — better to allow than to false-block.
"""
import json
import sys

CGROUP_MARKER = "claude-tg.service"


def in_telegram_session() -> bool:
    try:
        with open("/proc/self/cgroup", "r", encoding="utf-8") as f:
            return CGROUP_MARKER in f.read()
    except OSError:
        return False


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    if data.get("tool_name") != "AskUserQuestion":
        return 0

    if not in_telegram_session():
        return 0

    sys.stderr.write(
        "AskUserQuestion is unavailable in Telegram — its inline UI doesn't "
        "render in TG, so the user sees the question text without tappable "
        "options. Use mcp__claude-tg__ask_user_with_buttons instead: it sends "
        "an InlineKeyboardMarkup. Signature: ask_user_with_buttons("
        "question: str, options: list[str], multi_select: bool = False, "
        "timeout: int = 120) -> str. One question per call (loop for several)."
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
