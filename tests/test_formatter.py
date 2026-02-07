"""Tests for Markdown -> Telegram HTML conversion."""
from claude_tg.formatter import md_to_html, escape_html, format_tool_call


class TestEscapeHtml:
    def test_escapes_angle_brackets(self):
        assert escape_html("a < b > c") == "a &lt; b &gt; c"

    def test_escapes_ampersand(self):
        assert escape_html("a & b") == "a &amp; b"

    def test_no_double_escape(self):
        assert escape_html("&amp;") == "&amp;amp;"


class TestMdToHtml:
    def test_bold(self):
        assert md_to_html("**hello**") == "<b>hello</b>"

    def test_italic(self):
        assert md_to_html("*hello*") == "<i>hello</i>"

    def test_inline_code(self):
        assert md_to_html("`foo()`") == "<code>foo()</code>"

    def test_code_block(self):
        result = md_to_html("```python\nprint('hi')\n```")
        assert '<pre><code class="language-python">' in result
        assert "print(&#x27;hi&#x27;)" in result or "print('hi')" in result

    def test_code_block_no_lang(self):
        result = md_to_html("```\nsome code\n```")
        assert "<pre><code>" in result

    def test_link(self):
        assert md_to_html("[click](http://x.com)") == '<a href="http://x.com">click</a>'

    def test_no_bold_inside_code(self):
        result = md_to_html("`**not bold**`")
        assert "<b>" not in result

    def test_code_block_preserves_content(self):
        result = md_to_html("```\n**not bold** <html>\n```")
        assert "<b>" not in result
        assert "&lt;html&gt;" in result

    def test_underscore_in_identifiers(self):
        result = md_to_html("use `send_message` function")
        assert "send_message" in result
        assert "<i>" not in result

    def test_plain_text_escaped(self):
        result = md_to_html("x < 5 && y > 3")
        assert "&lt;" in result
        assert "&gt;" in result
        assert "&amp;" in result

    def test_mixed_formatting(self):
        result = md_to_html("**bold** and *italic* and `code`")
        assert "<b>bold</b>" in result
        assert "<i>italic</i>" in result
        assert "<code>code</code>" in result

    def test_fallback_on_empty(self):
        assert md_to_html("") == ""

    def test_multiline_text(self):
        text = "line 1\nline 2\n**bold line**"
        result = md_to_html(text)
        assert "<b>bold line</b>" in result


class TestFormatToolCall:
    def test_read(self):
        result = format_tool_call("Read", {"file_path": "/src/main.py"})
        assert "📂" in result
        assert "main.py" in result

    def test_edit(self):
        result = format_tool_call("Edit", {"file_path": "/src/main.py"})
        assert "✏️" in result

    def test_write(self):
        result = format_tool_call("Write", {"file_path": "/tests/test.py"})
        assert "📝" in result

    def test_bash(self):
        result = format_tool_call("Bash", {"command": "npm test"})
        assert "▶️" in result
        assert "npm test" in result

    def test_grep(self):
        result = format_tool_call("Grep", {"pattern": "TODO", "glob": "**/*.py"})
        assert "🔍" in result

    def test_unknown_tool(self):
        result = format_tool_call("SomeTool", {"arg": "val"})
        assert "🔧" in result
        assert "SomeTool" in result
