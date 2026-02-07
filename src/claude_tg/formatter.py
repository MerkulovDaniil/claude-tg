"""Convert Claude's Markdown output to Telegram HTML."""
import re


def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#x27;").replace('"', "&quot;")


def md_to_html(text: str) -> str:
    """
    Convert Markdown to Telegram-compatible HTML.

    Strategy: extract code blocks first (protect them), convert inline
    formatting, then reassemble.
    """
    if not text:
        return ""

    # Extract code blocks and replace with placeholders
    blocks: list[str] = []

    def _save_block(m: re.Match) -> str:
        lang = m.group(1) or ""
        code = escape_html(m.group(2))
        cls = f' class="language-{lang}"' if lang else ""
        blocks.append(f"<pre><code{cls}>{code}</code></pre>")
        return f"\x00BLOCK{len(blocks) - 1}\x00"

    result = re.sub(r"```(\w*)\n(.*?)```", _save_block, text, flags=re.DOTALL)

    # Extract inline code
    inline_codes: list[str] = []

    def _save_inline(m: re.Match) -> str:
        inline_codes.append(f"<code>{escape_html(m.group(1))}</code>")
        return f"\x00INLINE{len(inline_codes) - 1}\x00"

    result = re.sub(r"`([^`\n]+)`", _save_inline, result)

    # Escape remaining HTML
    result = escape_html(result)

    # Bold **...**
    result = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", result)

    # Italic *...* (not inside words, not **)
    result = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", result)

    # Links [text](url)
    result = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', result)

    # Restore inline code
    for i, code in enumerate(inline_codes):
        result = result.replace(f"\x00INLINE{i}\x00", code)

    # Restore code blocks
    for i, block in enumerate(blocks):
        result = result.replace(f"\x00BLOCK{i}\x00", block)

    return result


# Tool call icons
_TOOL_ICONS = {
    "Read": "\U0001f4c2",
    "Edit": "\u270f\ufe0f",
    "Write": "\U0001f4dd",
    "Bash": "\u25b6\ufe0f",
    "Grep": "\U0001f50d",
    "Glob": "\U0001f50d",
    "Task": "\U0001f916",
    "WebSearch": "\U0001f310",
    "WebFetch": "\U0001f310",
}


def format_tool_call(name: str, input_data: dict) -> str:
    """Format a tool call as a compact one-liner."""
    icon = _TOOL_ICONS.get(name, "\U0001f527")

    if name in ("Read", "Edit", "Write"):
        path = input_data.get("file_path", "")
        # Show just filename or last 2 path components
        short = "/".join(path.rsplit("/", 2)[-2:]) if "/" in path else path
        return f"{icon} {name}: {short}"

    if name == "Bash":
        cmd = input_data.get("command", "")
        # Truncate long commands
        display = cmd[:60] + "..." if len(cmd) > 60 else cmd
        return f"{icon} Bash: {display}"

    if name in ("Grep", "Glob"):
        pattern = input_data.get("pattern", "")
        return f"{icon} {name}: {pattern}"

    # Fallback
    return f"{icon} {name}"


def format_tool_result(result: str, max_length: int = 1000) -> str:
    """Format a tool result as an expandable blockquote."""
    text = result[:max_length]
    if len(result) > max_length:
        text += f"\n... ({len(result)} chars total)"
    return f"<blockquote expandable>{escape_html(text)}</blockquote>"
