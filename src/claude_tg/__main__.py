"""CLI entry point for claude-tg."""
import json
import subprocess
import sys
import argparse
import logging
import os
from pathlib import Path

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

    _ensure_mcp(config.work_dir)

    bot = ClaudeTelegramBot(config)
    bot.run()


def _ensure_mcp(work_dir: str):
    """Register claude-tg MCP server in Claude Code project settings if needed."""
    # Check both .claude/settings.json and .mcp.json
    for config_name in (".claude/settings.json", ".mcp.json"):
        config_file = Path(work_dir) / config_name
        if config_file.exists():
            try:
                data = json.loads(config_file.read_text())
                if "claude-tg" in data.get("mcpServers", {}):
                    return
            except (json.JSONDecodeError, KeyError):
                pass

    try:
        subprocess.run(
            ["claude", "mcp", "add", "claude-tg", "--scope", "project", "--", "claude-tg-mcp"],
            cwd=work_dir,
            capture_output=True,
            check=True,
        )
        logging.getLogger(__name__).info("Registered claude-tg MCP server")
    except FileNotFoundError:
        logging.getLogger(__name__).warning("claude CLI not found, skipping MCP registration")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode().strip()
        if "already exists" in stderr:
            return
        logging.getLogger(__name__).warning(f"MCP registration failed: {stderr}")


if __name__ == "__main__":
    main()
