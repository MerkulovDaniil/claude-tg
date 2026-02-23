# claude-tg

Claude Code CLI <-> Telegram bridge. Chat with Claude Code from your phone — full agentic experience through Telegram with token-level streaming.

## Install

```bash
pip install claude-tg
```

## Quick Start

```bash
export TELEGRAM_BOT_TOKEN="your_bot_token"   # from @BotFather
export TELEGRAM_CHAT_ID="your_chat_id"       # your Telegram user ID
export CLAUDE_WORK_DIR="/path/to/project"    # optional, defaults to cwd

claude-tg
```

On first run, the built-in MCP server for file sending is auto-registered in Claude Code.

## Commands

| Command | Description |
|---------|-------------|
| `/clear` | Reset session (new context) |
| `/compact` | Compact conversation context |
| `/cancel` | Stop current task |
| `/cost` | Show session cost |
| `/model <name>` | Switch model (no args = show current) |
| `/restart` | Full process restart (picks up CLI/config changes) |

Inline **Cancel** button is shown on every message during processing.

## Media

- **Photos** — sent to Claude as file references, Claude can read/analyze them
- **Documents** — same for files (PDF, code, etc.)

## Voice Messages

Voice messages are transcribed via Groq Whisper API and sent to Claude as text.

```bash
# Install with voice support
pip install 'claude-tg[voice]'

# Set your Groq API key (free at console.groq.com)
export GROQ_API_KEY="your_groq_api_key"
```

Without `GROQ_API_KEY`, the bot replies with a setup hint when a voice message is received.

## Triggers (External Prompts)

Enable a localhost HTTP server so cron jobs, scripts, or other processes can inject prompts into your chat:

```bash
export CLAUDE_TG_TRIGGER_PORT=9357   # any free port
```

Then trigger from anywhere:

```bash
curl -s -d "Run the /morning skill" localhost:9357
# → ok
```

- The response appears as a normal chat message — you can reply and continue the conversation
- If Claude is busy, the prompt queues and processes after the current task
- Localhost only — not exposed to the network

## File Sending (MCP)

Claude can send files back to you via the built-in MCP server:

- `send_telegram_file(file_path, caption?, temp_file?)` — sends a file to your Telegram
- `temp_file=True` (default) — file is deleted after sending (for generated/temporary files)
- `temp_file=False` — file is preserved (for existing project files)

The MCP server (`claude-tg-mcp`) is auto-registered on launch. No manual setup needed.

## Running as Root (VPS / Servers)

Claude Code CLI blocks `--dangerously-skip-permissions` for root. `claude-tg` handles this automatically:

- **Non-root** — uses `--dangerously-skip-permissions` as usual
- **Root** — uses `--allowedTools` with dynamically discovered MCP servers (reads `~/.claude.json` and `.mcp.json`)

All registered MCP servers and built-in tools are allowed automatically. No hardcoded server names.

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
| `CLAUDE_TG_TRIGGER_PORT` | — | Localhost port for external triggers (e.g. `9357`) |
| `CLAUDE_TG_MCP_EXCLUDE` | — | Comma-separated MCP servers to exclude (e.g. `telegram,garmin`) |
| `CLAUDE_TG_MCP_CONFIG` | — | Explicit MCP config JSON path (overrides auto-generation) |

## MCP Isolation

When running `claude-tg` alongside an interactive `claude` CLI session in the same directory, both processes start duplicate MCP servers from the same `.mcp.json`. Servers with exclusive resources (e.g. Telegram's Telethon session, Garmin tokens) will deadlock.

**Automatic isolation** — just list the conflicting servers to exclude:

```bash
export CLAUDE_TG_MCP_EXCLUDE="telegram"

# Or via CLI
claude-tg --mcp-exclude telegram,garmin
```

`claude-tg` reads your `.mcp.json` at startup, removes the excluded servers, and passes an auto-generated config via `--strict-mcp-config`. New servers added to `.mcp.json` are automatically available — no manual sync needed.

For full control, you can also provide an explicit config file via `CLAUDE_TG_MCP_CONFIG` (takes precedence over `--mcp-exclude`).

## Systemd (VPS deployment)

```bash
# Install
uv tool install 'claude-tg[voice]'

# Create service
cat > /etc/systemd/system/claude-tg.service << 'EOF'
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
EOF

systemctl enable --now claude-tg
```

## Features

- Token-level streaming with adaptive rate limiting
- Automatic message chaining for long outputs (splits at ~3800 chars)
- Photo, file, and voice message support
- Built-in MCP server for sending files back to the user
- Inline cancel button on every message
- Message queuing — send messages while Claude is working, they process after
- Session auto-reset after inactivity
- Compact tool call display with emoji icons
- Root-compatible — auto-discovers and allows all MCP tools
- Auto-registration of MCP server in Claude Code
- In-place restart via `/restart` (no need to touch the server)
- External triggers — cron/scripts can inject prompts via localhost HTTP

## Requirements

- Python 3.11+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- Telegram bot token from [@BotFather](https://t.me/BotFather)
