#!/usr/bin/env python3

"""Tests for diff2html.py"""

import tempfile
from pathlib import Path

import pytest

from diff2html import (
    _inject_wrap_css,
    _relabel,
    classify,
    clean_text,
    main,
    unified_diff_to_html,
)


class TestClassify:
    def test_classes(self):
        assert classify("+++ b/file") == "filehdr"
        assert classify("--- a/file") == "filehdr"
        assert classify("@@ -1,2 +3,4 @@") == "hunk"
        assert classify("+added") == "add"
        assert classify("-removed") == "del"
        assert classify("diff --git a b") == "meta"
        assert classify(" context") == "ctx"
        assert classify("\\ No newline at end of file") == "meta"


class TestCleanText:
    def test_strips_matching_lines_and_squeezes_blanks(self):
        text = "keep\n\n\n> Drafting note: x\n\n\nalso\n"
        result = clean_text(text, r"^> Drafting note")
        assert "> Drafting note" not in result
        assert "keep\n\nalso\n" == result


class TestRelabel:
    def test_rewrites_headers(self):
        diff = (
            "diff --git a/tmp/a b/tmp/b\n"
            "--- a/tmp/a\n"
            "+++ b/tmp/b\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        out = _relabel(diff, "old.md", "new.md")
        assert "diff --git old.md new.md" in out
        assert "--- old.md" in out
        assert "+++ new.md" in out
        assert "-old" in out


class TestUnifiedDiffToHtml:
    def test_wraps_diff_in_html(self):
        diff = "@@ -1 +1 @@\n-old\n+new\n"
        html = unified_diff_to_html(diff, "My Diff")
        assert "<!DOCTYPE html>" in html
        assert "<title>My Diff</title>" in html
        assert 'class="line hunk"' in html
        assert 'class="line del"' in html
        assert 'class="line add"' in html

    def test_empty_diff(self):
        html = unified_diff_to_html("", "Empty")
        assert "(no differences)" in html

    def test_escapes_html(self):
        html = unified_diff_to_html("+<script>\n", "t")
        assert "&lt;script&gt;" in html


class TestInjectWrapCss:
    def test_inserts_before_head_close(self):
        doc = "<html><head></head><body></body></html>"
        out = _inject_wrap_css(doc)
        assert "table.diff" in out
        assert out.index("table.diff") < out.index("</head>")


class TestDiff2HtmlMain:
    def test_git_method_two_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            a = root / "a.txt"
            b = root / "b.txt"
            a.write_text("one\n")
            b.write_text("two\n")
            out = root / "diff.html"

            assert main([
                "--file-a", str(a),
                "--file-b", str(b),
                "-o", str(out),
            ]) == 0

            html = out.read_text()
            assert "<!DOCTYPE html>" in html
            assert "one" in html or "two" in html

    def test_difflib_method_two_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            a = root / "a.txt"
            b = root / "b.txt"
            a.write_text("alpha\n")
            b.write_text("beta\n")
            out = root / "diff.html"

            assert main([
                "-m", "difflib",
                "--file-a", str(a),
                "--file-b", str(b),
                "--full",
                "-o", str(out),
            ]) == 0

            html = out.read_text()
            assert "diff" in html.lower()
            assert "table.diff" in html  # wrap css injected

    def test_requires_inputs(self):
        with pytest.raises(SystemExit):
            main([])

    def test_file_a_alone_errors(self):
        with pytest.raises(SystemExit):
            main(["--file-a", "only.txt"])

    def test_clean_with_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            a = root / "a.md"
            b = root / "b.md"
            a.write_text("keep\n> Drafting note: old\n")
            b.write_text("keep\n> Drafting note: new\nchanged\n")
            out = root / "diff.html"

            assert main([
                "--file-a", str(a),
                "--file-b", str(b),
                "--clean",
                "-o", str(out),
            ]) == 0
            html = out.read_text()
            assert "Drafting note" not in html or "changed" in html
