"""CLI entry point for claude-tg."""
import json
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
    parser.add_argument(
        "--mcp-config",
        help="Path to MCP config JSON (uses --strict-mcp-config, isolates from other Claude sessions)",
    )
    args = parser.parse_args()

    # CLI args override env vars
    if args.work_dir:
        os.environ["CLAUDE_WORK_DIR"] = args.work_dir
    if args.verbose:
        os.environ["CLAUDE_TG_VERBOSE"] = "1"
    if args.mcp_config:
        os.environ["CLAUDE_TG_MCP_CONFIG"] = args.mcp_config

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
    """Register claude-tg MCP server in .mcp.json (no CLI dependency)."""
    logger = logging.getLogger(__name__)
    mcp_path = Path(work_dir) / ".mcp.json"
    entry = {"type": "stdio", "command": "claude-tg-mcp", "args": [], "env": {}}
    try:
        data = json.loads(mcp_path.read_text()) if mcp_path.exists() else {}
        servers = data.setdefault("mcpServers", {})
        if servers.get("claude-tg") == entry:
            logger.debug("claude-tg MCP server already registered")
            return
        servers["claude-tg"] = entry
        mcp_path.write_text(json.dumps(data, indent=2) + "\n")
        logger.info("Registered claude-tg MCP server in .mcp.json")
    except Exception as e:
        logger.warning(f"MCP registration failed: {e}")


if __name__ == "__main__":
    main()
