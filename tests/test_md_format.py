#!/usr/bin/env python3

"""Tests for md_format.py"""

import io
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from md_format import (
    inject_default_command,
    is_bullet,
    main,
    reflow,
    space_bullets,
)


class TestIsBullet:
    def test_unordered(self):
        assert is_bullet("- item")
        assert is_bullet("* item")
        assert is_bullet("+ item")

    def test_ordered(self):
        assert is_bullet("1. item")
        assert is_bullet("2) item")

    def test_not_bullet(self):
        assert not is_bullet("plain text")
        assert not is_bullet("# heading")


class TestSpaceBullets:
    def test_inserts_blank_between_adjacent(self):
        text = "- a\n- b\n"
        assert space_bullets(text) == "- a\n\n- b\n"

    def test_idempotent(self):
        text = "- a\n\n- b\n"
        assert space_bullets(text) == text

    def test_preserves_trailing_newline(self):
        assert space_bullets("- a\n- b\n").endswith("\n")
        assert not space_bullets("- a\n- b").endswith("\n")


class TestReflow:
    def test_unwrap_joins_paragraph(self):
        text = "hello\nworld\n"
        assert reflow(text, mode="unwrap") == "hello world\n"

    def test_wrap_hard_wraps(self):
        text = "one two three four five six\n"
        result = reflow(text, mode="wrap", width=10)
        assert "\n" in result.strip()
        assert "one two" in result

    def test_preserves_fenced_code(self):
        text = "```\nline one\nline two\n```\n"
        assert reflow(text, mode="unwrap") == text

    def test_preserves_heading(self):
        text = "# Title\n\npara one\ncontinues\n"
        result = reflow(text, mode="unwrap")
        assert result.startswith("# Title\n")
        assert "para one continues" in result

    def test_list_item_unwrap(self):
        text = "- first line\n  second line\n"
        result = reflow(text, mode="unwrap")
        assert result == "- first line second line\n"


class TestInjectDefaultCommand:
    def test_injects_all(self):
        assert inject_default_command(["notes.md"]) == ["all", "notes.md"]

    def test_keeps_explicit_subcommand(self):
        assert inject_default_command(["space", "notes.md"]) == ["space", "notes.md"]

    def test_keeps_help(self):
        assert inject_default_command(["--help"]) == ["--help"]

    def test_empty_unchanged(self):
        assert inject_default_command([]) == []


class TestMdFormatMain:
    def test_space_stdin(self):
        stdin = io.StringIO("- a\n- b\n")
        stdout = io.StringIO()
        with patch("sys.stdin", stdin), patch("sys.stdout", stdout):
            assert main(["space"]) == 0
        assert stdout.getvalue() == "- a\n\n- b\n"

    def test_default_all_on_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "notes.md"
            path.write_text("- a\n- b\nhello\nworld\n")
            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                assert main([str(path)]) == 0
            out = stdout.getvalue()
            assert "- a\n\n- b" in out
            assert "hello world" in out

    def test_in_place(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "notes.md"
            path.write_text("- a\n- b\n")
            assert main(["space", "-i", str(path)]) == 0
            assert path.read_text() == "- a\n\n- b\n"

    def test_recursive_dry_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.md").write_text("- a\n- b\n")
            (root / "ok.md").write_text("- a\n\n- b\n")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                assert main(["space", "-r", str(root)]) == 0
            assert "would rewrite" in stdout.getvalue()
            assert "would change" in stderr.getvalue()

    def test_width_validation(self):
        with pytest.raises(SystemExit):
            main(["reflow", "--width", "0"])
