#!/usr/bin/env python3

"""Tests for webloc_to_md.py"""

import os
import plistlib
from pathlib import Path

import pytest

from webloc_to_md import gen_md, get_link, main


def _write_webloc(path: Path, url: str) -> None:
    with open(path, "wb") as f:
        plistlib.dump({"URL": url}, f)


@pytest.fixture
def tree(tmp_path):
    """A small tree of .webloc files, one nested a level down."""
    _write_webloc(tmp_path / "Alpha.webloc", "https://a.example/")
    (tmp_path / "notes.txt").write_text("ignore")
    nested = tmp_path / "sub"
    nested.mkdir()
    _write_webloc(nested / "Beta.webloc", "https://b.example/")
    return tmp_path


class TestGetLink:
    def test_formats_markdown_link(self, tmp_path):
        _write_webloc(tmp_path / "Example Site.webloc", "https://example.com/page")
        result = get_link(str(tmp_path), "Example Site.webloc")
        assert result == "- [Example Site](https://example.com/page)"

    def test_name_comes_from_the_stem_not_the_url(self, tmp_path):
        _write_webloc(tmp_path / "My Notes.webloc", "https://x.example/")
        assert get_link(str(tmp_path), "My Notes.webloc").startswith("- [My Notes]")


class TestGenMd:
    def test_collects_links_from_every_level(self, tree, tmp_path):
        out = gen_md(str(tree), title="My Links", output=tmp_path / "out.md")
        assert out.startswith("# My Links")
        assert "- [Alpha](https://a.example/)" in out
        assert "- [Beta](https://b.example/)" in out

    def test_ignores_non_webloc_files(self, tree, tmp_path):
        assert "notes" not in gen_md(str(tree), output=tmp_path / "out.md")

    def test_scans_the_given_root_not_the_working_directory(self, tree, tmp_path):
        """The regression: gen_md used to walk '.' and ignore its argument."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        old = os.getcwd()
        try:
            os.chdir(elsewhere)
            out = gen_md(str(tree), output=tmp_path / "out.md")
        finally:
            os.chdir(old)
        assert "- [Alpha](https://a.example/)" in out

    def test_headings_are_relative_to_the_root(self, tree, tmp_path):
        out = gen_md(str(tree), output=tmp_path / "out.md")
        assert "## sub" in out
        # The scan root is named, never spelled as an absolute path.
        assert f"## {tree.name}" in out
        assert str(tree) not in out

    def test_writes_the_output_file(self, tree, tmp_path):
        target = tmp_path / "links.md"
        out = gen_md(str(tree), output=target)
        assert target.read_text() == out

    def test_empty_tree_still_writes_a_title(self, tmp_path):
        root = tmp_path / "empty"
        root.mkdir()
        out = gen_md(str(root), title="Nothing", output=tmp_path / "out.md")
        assert out.startswith("# Nothing")
        assert "- [" not in out


class TestMain:
    def test_defaults_to_the_working_directory(self, tree, monkeypatch):
        monkeypatch.chdir(tree)
        assert main([]) == 0
        assert "- [Alpha](https://a.example/)" in (tree / "_RESEARCH.md").read_text()

    def test_root_title_and_output_flags(self, tree, tmp_path):
        target = tmp_path / "custom.md"
        assert main([str(tree), "-t", "Bookmarks", "-o", str(target)]) == 0
        text = target.read_text()
        assert text.startswith("# Bookmarks")
        assert "- [Beta](https://b.example/)" in text

    def test_missing_directory_is_rejected(self, tmp_path):
        with pytest.raises(SystemExit):
            main([str(tmp_path / "absent")])

    def test_help_does_not_write_anything(self, tmp_path, monkeypatch):
        """--help used to fall through to a scan of the working directory."""
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as excinfo:
            main(["--help"])
        assert excinfo.value.code == 0
        assert not (tmp_path / "_RESEARCH.md").exists()
