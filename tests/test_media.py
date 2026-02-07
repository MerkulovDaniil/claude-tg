"""Tests for media handling."""
import os
import tempfile
import pytest
from claude_tg.media import MediaHandler


class TestMediaHandler:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.handler = MediaHandler(upload_dir=self.tmpdir)

    def teardown_method(self):
        self.handler.cleanup()
        if os.path.exists(self.tmpdir):
            os.rmdir(self.tmpdir)

    def test_build_prompt_photo(self):
        path = os.path.join(self.tmpdir, "photo.jpg")
        open(path, "w").close()
        self.handler._files.append(path)
        result = self.handler.build_prompt("describe this", [path], [])
        assert "[User sent a photo:" in result
        assert "describe this" in result

    def test_build_prompt_document(self):
        path = os.path.join(self.tmpdir, "report.pdf")
        open(path, "w").close()
        self.handler._files.append(path)
        result = self.handler.build_prompt("analyze", [], [path])
        assert "[User sent a file:" in result

    def test_build_prompt_text_only(self):
        result = self.handler.build_prompt("hello", [], [])
        assert result == "hello"

    def test_cleanup_removes_files(self):
        path = os.path.join(self.tmpdir, "test.txt")
        with open(path, "w") as f:
            f.write("test")
        self.handler._files.append(path)
        self.handler.cleanup()
        assert not os.path.exists(path)

    def test_cleanup_on_empty(self):
        self.handler.cleanup()  # should not raise
