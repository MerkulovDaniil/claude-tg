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

    def test_cleanup_keep_preserves_files(self):
        keep_path = os.path.join(self.tmpdir, "keep.txt")
        wipe_path = os.path.join(self.tmpdir, "wipe.txt")
        for p in (keep_path, wipe_path):
            with open(p, "w") as f:
                f.write("x")
            self.handler._files.append(p)
        self.handler.cleanup(keep=[keep_path])
        assert os.path.exists(keep_path), "kept file should survive cleanup"
        assert not os.path.exists(wipe_path), "non-kept file should be removed"
        assert keep_path in self.handler._files
        assert wipe_path not in self.handler._files

    def test_cleanup_all_preserves_recent(self):
        import time as _t
        recent = os.path.join(self.tmpdir, "recent.txt")
        old = os.path.join(self.tmpdir, "old.txt")
        with open(recent, "w") as f:
            f.write("r")
        with open(old, "w") as f:
            f.write("o")
        # Backdate `old` by 2 days
        old_ts = _t.time() - 2 * 86400
        os.utime(old, (old_ts, old_ts))
        self.handler._files.extend([recent, old])
        self.handler.cleanup_all(max_age_seconds=86400)
        assert os.path.exists(recent), "recent file must not be wiped on startup"
        assert not os.path.exists(old), "stale file should be wiped on startup"
