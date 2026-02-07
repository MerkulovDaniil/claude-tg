# claude-tg

Claude Code CLI <-> Telegram bridge. Seamless terminal experience through Telegram.

## Quick Start

```bash
pip install -e .

export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"
export CLAUDE_WORK_DIR="/path/to/project"

claude-tg
```

## Commands

| Command | Description |
|---------|-------------|
| `/clear` | Reset session |
| `/compact` | Compact conversation context |
| `/cancel` | Stop current task |
| `/cost` | Show session cost |
| `/model <name>` | Switch model |

Regular messages go directly to Claude Code.

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | *required* | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | *required* | Your chat ID |
| `CLAUDE_WORK_DIR` | `cwd` | Working directory for Claude |
| `CLAUDE_TG_VERBOSE` | `0` | Show tool results (`1` to enable) |
| `CLAUDE_TG_MODEL` | — | Override Claude model |
| `CLAUDE_TG_MAX_BUDGET` | — | Max budget in USD |
| `CLAUDE_TG_SESSION_TIMEOUT` | `3600` | Auto-reset after N seconds of inactivity |
| `CLAUDE_TG_UPDATE_INTERVAL` | `2.0` | Telegram message update interval (seconds) |

## CLI flags

```
claude-tg --work-dir /path/to/project --verbose
```

## Features

- Token-level streaming with adaptive rate limiting
- Automatic message chaining for long outputs
- Photo and file uploads (passed to Claude via file references)
- Inline cancel button
- Session auto-reset after inactivity
- Compact tool call display (verbose mode available)

## Requirements

- Python 3.11+
- Claude Code CLI installed and authenticated
- Telegram bot token
