"""CLI entry point for claude-tg."""
import sys
import argparse
import logging
import os

from .config import Config
from .bot import ClaudeTelegramBot


def main():
    parser = argparse.ArgumentParser(
        description="Claude Code <-> Telegram bridge",
        prog="claude-tg",
    )
    parser.add_argument(
        "--work-dir",
        help="Working directory for Claude Code (default: current directory)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show tool results in expandable blockquotes",
    )
    args = parser.parse_args()

    # CLI args override env vars
    if args.work_dir:
        os.environ["CLAUDE_WORK_DIR"] = args.work_dir
    if args.verbose:
        os.environ["CLAUDE_TG_VERBOSE"] = "1"

    # Configure logging
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=getattr(logging, log_level, logging.INFO),
    )

    config = Config()
    errors = config.validate()
    if errors:
        for e in errors:
            print(f"Error: {e}", file=sys.stderr)
        print(
            "\nRequired env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID",
            file=sys.stderr,
        )
        sys.exit(1)

    bot = ClaudeTelegramBot(config)
    bot.run()


if __name__ == "__main__":
    main()
