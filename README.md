# claude-tg

**Full Claude Code on your phone.** Not a chatbot wrapper — the real agentic CLI with tools, MCP servers, and file access, streamed to Telegram with token-level updates.

```
pip install claude-tg     # or: uv tool install claude-tg
```

## What makes this different

Most Telegram bridges for Claude spawn a **new process per message** and parse the output. claude-tg keeps a **persistent Claude Code process** alive using the `--input-format stream-json` protocol — the same streaming interface the CLI uses internally.

This means:

- **No startup delay** — the process is already running, responses begin instantly
- **Mid-turn message injection** — send a message while Claude is working, it arrives in-context (not queued for "after")
- **Full tool access** — every MCP server, every built-in tool, file I/O, Bash — all work exactly like in the terminal
- **Real streaming** — token-by-token updates to Telegram, not periodic polling

~1,500 lines of Python total. No framework, no database, no Docker required.

## Quick start

```bash
export TELEGRAM_BOT_TOKEN="..."    # from @BotFather
export TELEGRAM_CHAT_ID="..."      # your Telegram user ID
claude-tg
```

That's it. On first run, the built-in MCP server for file sending is auto-registered.

## Features

**Core**
- Token-level streaming with automatic message chaining (long outputs split at ~3800 chars)
- Persistent process — one Claude subprocess lives across all turns
- Mid-turn injection — messages sent during processing go directly into the running conversation
- Inline cancel button on every message

**Media**
- Photos and documents sent to Claude as file references
- Voice messages transcribed via Groq Whisper (free API)
- Claude can send files back via built-in MCP server

**Automation**
- Trigger server — cron jobs and scripts inject prompts via `localhost:PORT`
- `DIRECT:` mode — send messages to Telegram bypassing Claude (for notifications)
- Conversation log — persistent chat history in `~/.claude-tg/conversation.log`

**Operations**
- `/clear` — reset session
- `/compact` — compact conversation context
- `/cancel` — stop current task
- `/cost` — show session spend
- `/model <name>` — switch model on the fly
- `/restart` — in-place process restart

## Triggers (external automation)

```bash
export CLAUDE_TG_TRIGGER_PORT=9357
```

```bash
# Run a prompt through Claude
curl -d "Summarize today's git log" localhost:9357

# Send directly to Telegram without Claude
curl -d "DIRECT:Deploy complete ✅" localhost:9357
```

Prompts queue if Claude is busy. Localhost only.

## Voice messages

```bash
export GROQ_API_KEY="..."  # free at console.groq.com
```

Voice → Whisper transcription → Claude. Without the key, voice messages show a setup hint.

## Running on a VPS

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

**Root handling**: Claude Code blocks `--dangerously-skip-permissions` for root. claude-tg detects this and switches to `--allowedTools` with auto-discovered MCP servers from `~/.claude.json` and `.mcp.json`.

## Architecture

```
Telegram ←→ bot.py (python-telegram-bot)
                ↕
            runner.py (persistent subprocess)
                ↕ stdin/stdout (NDJSON stream-json)
            Claude Code CLI
                ↕
            MCP servers, tools, files
```

`runner.py` manages a single long-lived Claude process. Messages are written to stdin as `{"type":"user","message":{"role":"user","content":"..."}}`. Events are read from stdout line by line. When a turn completes (RESULT event), the process stays alive for the next turn.

`stream.py` handles Telegram message updates — buffering tokens, splitting long messages into chains, rate-limiting edits to avoid Telegram API limits.

`bot.py` orchestrates: debouncing rapid messages, injecting mid-turn, managing sessions, handling media and voice.

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
| `CLAUDE_TG_SESSION_TIMEOUT` | `3600` | Auto-reset after inactivity (seconds) |
| `CLAUDE_TG_UPDATE_INTERVAL` | `2.0` | Telegram edit interval (seconds) |
| `GROQ_API_KEY` | — | Groq key for voice transcription |

## Requirements

- Python 3.11+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- Telegram bot from [@BotFather](https://t.me/BotFather)

## License

MIT
