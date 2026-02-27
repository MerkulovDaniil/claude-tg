# claude-tg

**Full Claude Code — in Telegram.** Not a chatbot wrapper. The real agentic CLI with tools, MCP servers, and file access, streamed to your phone with live token updates.

```
pip install claude-tg
```

## Why this exists

Every Telegram bridge for Claude spawns a **new process per message** and scrapes stdout. That means cold starts, no context between turns, and no way to interact while Claude is thinking.

claude-tg keeps a **single persistent Claude Code process** alive using the official `--input-format stream-json` protocol. The same streaming interface the terminal uses internally.

**What this gives you:**
- **Zero startup delay** — process is already running, first token appears instantly
- **Mid-turn messages** — send something while Claude is working, it arrives in-context (not queued)
- **Every tool works** — Bash, file I/O, MCP servers, web search — exactly like terminal
- **Real streaming** — token-by-token updates to Telegram, not periodic polling

~1,500 lines of Python. No framework, no database, no Docker.

## Quick start

```bash
export TELEGRAM_BOT_TOKEN="..."    # from @BotFather
export TELEGRAM_CHAT_ID="..."      # your Telegram user ID
claude-tg
```

On first run, the built-in MCP server for file sending is auto-registered.

## How it works

```
Telegram ←→ bot.py (python-telegram-bot)
                ↕
            runner.py (persistent subprocess)
                ↕ stdin/stdout (NDJSON stream-json)
            Claude Code CLI
                ↕
            MCP servers, tools, files
```

`runner.py` manages a single long-lived Claude process. Messages go to stdin as NDJSON. Events stream from stdout line by line. When a turn completes, the process stays alive for the next one.

A background reader continuously drains stdout into an asyncio queue, preventing pipe buffer deadlocks during mid-turn injection.

`stream.py` handles the Telegram side — buffering tokens, splitting long outputs into message chains at ~3800 chars, rate-limiting edits to stay within API limits.

`bot.py` ties it together: debouncing rapid messages, injecting mid-turn, handling media and voice.

## Features

### Streaming & persistence
- Token-level streaming with automatic message chaining (long responses split across messages)
- Persistent process across all conversation turns
- Session resume on reconnect
- Auto-reset after configurable inactivity timeout

### Mid-turn interaction
- Send messages while Claude is working — they're injected via stdin into the running conversation
- Messages are debounced (0.5s) so rapid typing merges into one
- Cancel button on every response

### Media
- **Photos & documents** → saved locally, passed to Claude as file references
- **Voice messages** → transcribed via Groq Whisper (free), then sent as text
- **Files from Claude** → sent back to Telegram via built-in MCP server

### External automation (triggers)
```bash
export CLAUDE_TG_TRIGGER_PORT=9357
```

```bash
# Prompt goes through Claude
curl -d "Summarize today's git log" localhost:9357

# Bypass Claude, send directly to Telegram
curl -d "DIRECT:Deploy complete ✅" localhost:9357
```

Prompts queue if Claude is busy. Localhost only — no auth needed, no exposure.

Use this for cron jobs, monitoring scripts, heartbeats, CI/CD notifications.

### Conversation log
All messages (user, assistant, triggers, direct) are persisted to `data/conversation_log.jsonl`. The built-in MCP tool `get_conversation_context` lets Claude read recent chat history for context continuity across sessions.

### Commands
| Command | Description |
|---------|-------------|
| `/clear` | Reset session |
| `/compact` | Compact conversation context |
| `/cancel` | Stop current task |
| `/cost` | Show session spend |
| `/model <name>` | Switch model on the fly |
| `/restart` | In-place process restart |

## Running as a service (VPS)

```bash
uv tool install claude-tg
```

```ini
# /etc/systemd/system/claude-tg.service
[Unit]
Description=Claude TG
After=network-online.target

[Service]
Type=simple
EnvironmentFile=/path/to/.env
Environment=PATH=/root/.local/bin:/usr/local/bin:/usr/bin
ExecStart=/root/.local/bin/claude-tg --work-dir /root
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now claude-tg
```

> **Running as root?** Claude Code blocks `--dangerously-skip-permissions` for root. claude-tg detects this and switches to `--allowedTools` with auto-discovered MCP servers from `~/.claude.json` and `.mcp.json`.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | *required* | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | *required* | Your Telegram user ID |
| `CLAUDE_WORK_DIR` | cwd | Working directory for Claude |
| `CLAUDE_TG_MODEL` | — | Override Claude model |
| `CLAUDE_TG_MAX_BUDGET` | — | Max budget in USD |
| `CLAUDE_TG_TRIGGER_PORT` | — | Localhost port for triggers |
| `CLAUDE_TG_VERBOSE` | `0` | Show tool results in chat |
| `CLAUDE_TG_SESSION_TIMEOUT` | `3600` | Auto-reset after inactivity (sec) |
| `CLAUDE_TG_UPDATE_INTERVAL` | `2.0` | Telegram edit interval (sec) |
| `GROQ_API_KEY` | — | Groq key for voice transcription |

## Requirements

- Python 3.11+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- Telegram bot from [@BotFather](https://t.me/BotFather)

## License

MIT
