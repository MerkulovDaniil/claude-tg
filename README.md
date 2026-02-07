# claude-tg

Claude Code CLI <-> Telegram bridge. Full terminal experience through Telegram with token-level streaming.

## Install

```bash
pip install claude-tg

# With voice message support:
pip install claude-tg[voice]
```

## Quick Start

```bash
export TELEGRAM_BOT_TOKEN="your_bot_token"   # from @BotFather
export TELEGRAM_CHAT_ID="your_chat_id"       # your Telegram user ID
export CLAUDE_WORK_DIR="/path/to/project"    # optional, defaults to cwd

claude-tg
```

On first run, the MCP server for file sending is auto-registered in Claude Code.

## Commands

| Command | Description |
|---------|-------------|
| `/clear` | Reset session (new context) |
| `/compact` | Compact conversation context |
| `/cancel` | Stop current task |
| `/cost` | Show session cost |
| `/model <name>` | Switch model (no args = show current) |

Inline **Cancel** button is shown on every message during processing.

## Media

- **Photos** — send a photo to the bot, it gets passed to Claude as a file reference
- **Documents** — same for files (PDF, code, etc.)
- **Voice** — transcribed via Groq Whisper API and sent as text to Claude (requires `GROQ_API_KEY`)

Claude sees the file path and can read/analyze it with its built-in tools.

## File Sending (MCP)

Claude can send files back to you via the built-in MCP server:

- `send_telegram_file(file_path, caption?, temp_file?)` — sends a file to your Telegram
- `temp_file=True` (default) — file is deleted after sending (for generated/temporary files)
- `temp_file=False` — file is preserved (for existing project files)

The MCP server (`claude-tg-mcp`) is auto-registered on first launch. No manual configuration needed.

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | *required* | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | *required* | Your Telegram user ID |
| `CLAUDE_WORK_DIR` | `cwd` | Working directory for Claude |
| `CLAUDE_TG_VERBOSE` | `0` | Show tool results (`1` to enable) |
| `CLAUDE_TG_MODEL` | — | Override Claude model |
| `CLAUDE_TG_MAX_BUDGET` | — | Max budget in USD |
| `CLAUDE_TG_SESSION_TIMEOUT` | `3600` | Auto-reset after N seconds of inactivity |
| `CLAUDE_TG_UPDATE_INTERVAL` | `2.0` | Telegram message update interval (seconds) |
| `GROQ_API_KEY` | — | Groq API key for voice transcription |

## CLI Flags

```
claude-tg --work-dir /path/to/project --verbose
```

## Features

- Token-level streaming with adaptive rate limiting
- Automatic message chaining for long outputs (splits at ~3800 chars)
- Photo and file uploads passed to Claude as file references
- MCP server for sending files back to the user
- Inline cancel button on every message
- Message queuing — send messages while Claude is working, they process after
- Session auto-reset after inactivity
- Compact tool call display with emoji icons
- Voice message transcription via Groq Whisper API
- Auto-registration of MCP server in Claude Code

## Requirements

- Python 3.11+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- Telegram bot token from [@BotFather](https://t.me/BotFather)
