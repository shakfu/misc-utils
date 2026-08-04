#!/usr/bin/env python3

"""Tests for webloc_to_md.py"""

import os
import plistlib
import tempfile
from pathlib import Path
from unittest.mock import patch

from webloc_to_md import gen_md, get_link


def _write_webloc(path: Path, url: str) -> None:
    with open(path, "wb") as f:
        plistlib.dump({"URL": url}, f)


class TestGetLink:
    """Test get_link."""

    def test_formats_markdown_link(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            webloc = Path(tmpdir) / "Example Site.webloc"
            _write_webloc(webloc, "https://example.com/page")

            result = get_link(tmpdir, "Example Site.webloc")

            assert result == "- [Example Site](https://example.com/page)"


class TestGenMd:
    """Test gen_md."""

    def test_writes_research_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_webloc(root / "Alpha.webloc", "https://a.example/")
            nested = root / "sub"
            nested.mkdir()
            _write_webloc(nested / "Beta.webloc", "https://b.example/")

            with patch("webloc_to_md.os.walk") as mock_walk:
                mock_walk.return_value = [
                    (str(root), ["sub"], ["Alpha.webloc"]),
                    (str(nested), [], ["Beta.webloc"]),
                ]
                old = os.getcwd()
                try:
                    os.chdir(tmpdir)
                    gen_md(tmpdir, title="My Links")
                finally:
                    os.chdir(old)

            out = (root / "_RESEARCH.md").read_text()
            assert out.startswith("# My Links")
            assert "- [Alpha](https://a.example/)" in out
            assert "- [Beta](https://b.example/)" in out
            assert "## " in out

    def test_ignores_non_webloc_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "notes.txt").write_text("ignore")
            _write_webloc(root / "Keep.webloc", "https://keep.example/")

            with patch("webloc_to_md.os.walk") as mock_walk:
                mock_walk.return_value = [
                    (str(root), [], ["notes.txt", "Keep.webloc"]),
                ]
                old = os.getcwd()
                try:
                    os.chdir(tmpdir)
                    gen_md(tmpdir)
                finally:
                    os.chdir(old)

            out = (root / "_RESEARCH.md").read_text()
            assert "Keep" in out
            assert "notes" not in out
