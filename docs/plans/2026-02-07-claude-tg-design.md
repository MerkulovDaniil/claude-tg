# claude-tg: Claude Code <-> Telegram Bridge

## Overview

Minimal Python library that bridges a Claude Code CLI session to Telegram.
Install, set 3 env vars, run one command — get a native terminal-like experience in Telegram.

```bash
pip install claude-tg
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="123456"
claude-tg --work-dir /projects/my-app
```

## Package Structure

```
claude-tg/
├── pyproject.toml
├── src/
│   └── claude_tg/
│       ├── __init__.py
│       ├── __main__.py      # CLI entry point (claude-tg command)
│       ├── bot.py            # Telegram bot setup + handlers
│       ├── runner.py         # Claude Code subprocess + stream-json parsing
│       ├── stream.py         # Telegram message streaming (rate limiting, message chaining)
│       ├── formatter.py      # Markdown -> Telegram HTML conversion
│       ├── media.py          # Photo/file download, cleanup
│       └── config.py         # Env var loading + validation
```

## Configuration

### Required env vars
- `TELEGRAM_BOT_TOKEN` — bot token from @BotFather
- `TELEGRAM_CHAT_ID` — authorized user's chat ID

### Optional env vars (all have defaults)
- `CLAUDE_WORK_DIR` — working directory for Claude Code (default: cwd). Also settable via `--work-dir` CLI flag.
- `CLAUDE_TG_VERBOSE=0|1` — show tool results in expandable blockquotes (default: 0)
- `CLAUDE_TG_MODEL` — model name: `sonnet`, `opus`, or full model ID (default: not set, uses Claude Code default)
- `CLAUDE_TG_MAX_BUDGET` — max USD per session (default: not set)
- `CLAUDE_TG_SESSION_TIMEOUT` — seconds of inactivity before auto-reset (default: 3600)
- `CLAUDE_TG_UPDATE_INTERVAL` — streaming update interval in seconds (default: 2.0)

## Streaming UX

### Flow
```
User sends message
        ↓
[⏳ Thinking...]                    ← message with Cancel button
        ↓
[Tokens stream in, updated ~2s]    ← single message, live-updating
[📂 Read src/auth.py]              ← tool calls shown inline
[More text tokens...]
        ↓
[At ~3800 chars → new message]     ← chain continues in new message
[Streaming continues here...]
        ↓
[Final message, Cancel removed]
[⏱ 18s · 5 turns]                 ← footer (no cost)
```

### Rate limiting
- Update interval: 2 seconds (configurable via `CLAUDE_TG_UPDATE_INTERVAL`)
- Safe within Telegram's ~30 edits/minute limit
- "Message not modified" errors silently ignored

### Message chaining
- Threshold: ~3800 characters (reserve for HTML overhead + footer)
- When threshold reached during streaming: send current message as final, create new message, continue streaming
- All chained messages linked via reply-to for visual threading

### Tool call display

**Default (compact):**
One line per tool call with icon by type:
- `📂 Read src/main.py`
- `✏️ Edit src/main.py`
- `🔍 Grep "TODO" **/*.py`
- `▶️ Bash npm test`
- `📝 Write tests/test_auth.py`
- `🔧 ToolName` (fallback for unknown tools)

**Verbose (`CLAUDE_TG_VERBOSE=1`):**
Same + tool result in expandable blockquote:
```html
📂 Read src/main.py
<blockquote expandable>file contents here...</blockquote>
```

### Footer
After completion: `⏱ {duration}s · {num_turns} turns`
No cost displayed.

## Formatting

- **HTML mode exclusively** — MarkdownV2 escaping is impractical for dynamic content
- Convert Claude's Markdown output to Telegram HTML:
  - `**bold**` → `<b>bold</b>`
  - `*italic*` → `<i>italic</i>`
  - `` `code` `` → `<code>code</code>`
  - ```` ```lang\ncode\n``` ```` → `<pre><code class="language-lang">code</code></pre>`
  - Links `[text](url)` → `<a href="url">text</a>`
- Escape `<`, `>`, `&` in all non-formatted text
- Fallback to plain text if HTML parsing fails

## Media Handling

### Incoming photos
1. Download max resolution to `$TMPDIR/claude-tg-uploads/`
2. Send prompt: `[User sent a photo: /path/to/photo.jpg]\n{caption}`
3. Claude reads via `Read` tool (multimodal)
4. Files cleaned up on session end

### Incoming documents
1. Download with original filename to `$TMPDIR/claude-tg-uploads/`
2. Send prompt: `[User sent a file: /path/to/report.pdf]\n{caption}`
3. Claude reads via `Read` tool (supports .py, .pdf, .txt, images, etc.)
4. Files cleaned up on session end

### Voice messages (v2, not implemented in v1)
- `media.py` has the hook (`handle_voice`) returning "Voice not supported yet"
- Architecture ready for optional STT integration later

### Debounce
- 0.5 second buffer for all input types (text, photos, files)
- Multiple messages/files within window combined into single prompt

### Cleanup
- Upload files deleted on session clear/reset (not after each response)
- On bot startup: clean leftover uploads from previous run

## Session Management

### Lifecycle
- Session = Claude Code session_id + uploads folder
- Persists across messages via `--resume SESSION_ID`
- Auto-reset after configurable inactivity timeout (default: 1 hour)
- On reset: delete uploads, drop session_id

### Commands

| Command | Action |
|---------|--------|
| `/clear` | Reset session — new session_id, delete uploads |
| `/compact` | Send `/compact` to Claude Code to compress context |
| `/cost` | Show accumulated session cost (from result events) |
| `/cancel` | Kill running subprocess (SIGTERM → SIGKILL after 2s) |
| `/model <name>` | Switch model for current session |

Regular text messages → prompt in current session.

## Claude Code CLI Integration

### Command construction
```
claude -p "{prompt}"
  --output-format stream-json
  --verbose
  --include-partial-messages
  --dangerously-skip-permissions
  [--resume SESSION_ID]
  [--model MODEL]
  [--max-budget-usd BUDGET]
```

### Stream event handling

| Event type | Action |
|------------|--------|
| `system.init` | Log session info, store session_id |
| `stream_event` → `content_block_delta` → `text_delta` | Append to buffer, trigger display update |
| `stream_event` → `content_block_start` → `tool_use` | Show tool call line |
| `assistant` (with tool_use content) | In verbose mode, prepare for tool result |
| `user` (tool_result) | In verbose mode, show in expandable blockquote |
| `result` | Store session_id, accumulate cost/duration/turns, show footer |
| `stream_event` → `message_delta` | Track stop_reason |

### Error handling
- Non-zero exit + stderr → show error message
- Process crash → show partial output + error
- Timeout → not enforced (Claude Code has its own budget limits)

## Authorization

Single-user only: `TELEGRAM_CHAT_ID` checked on every update.
Unauthorized messages silently ignored (logged at WARNING level).

## Out of Scope (v1)

- Multi-user support
- Voice message transcription
- File output from Claude (screenshots, generated files)
- Webhook mode (polling only)
- Custom system prompts via env var
- VPS control commands
