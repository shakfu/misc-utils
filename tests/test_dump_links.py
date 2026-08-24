#!/usr/bin/env python3

"""Tests for dump_links.py"""

import os
import plistlib
import tempfile
from pathlib import Path

import dump_links


def _write_webloc(path: Path, url: str) -> None:
    with open(path, "wb") as f:
        plistlib.dump({"URL": url}, f)


class TestDumpLinks:
    """Test dump()."""

    def test_writes_html_with_links(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_webloc(root / "First.webloc", "https://first.example/")
            _write_webloc(root / "Second.webloc", "https://second.example/")

            old = os.getcwd()
            try:
                os.chdir(tmpdir)
                dump_links.dump(tmpdir)
                html = Path("links.html").read_text()
            finally:
                os.chdir(old)

            assert "<h1>Links</h1>" in html
            assert '<a href="https://first.example/">First</a>' in html
            assert '<a href="https://second.example/">Second</a>' in html
            assert html.startswith("<html>")
