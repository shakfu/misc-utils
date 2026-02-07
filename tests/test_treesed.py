#!/usr/bin/env python3
"""Tests for treesed.py"""

import os
import tempfile
from pathlib import Path

import pytest

from treesed import FileMatches, FileReplacement, TreeSed, main


class TestCollectTree:
    def test_collects_files_recursively(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.txt").write_text("aaa")
            sub = root / "sub"
            sub.mkdir()
            (sub / "b.txt").write_text("bbb")
            (sub / "c.txt").write_text("ccc")

            files = TreeSed.collect_tree(root)
            names = sorted(p.name for p in files)
            assert names == ["a.txt", "b.txt", "c.txt"]

    def test_returns_only_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "file.txt").write_text("x")
            (root / "subdir").mkdir()

            files = TreeSed.collect_tree(root)
            assert all(p.is_file() for p in files)
            assert len(files) == 1

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert TreeSed.collect_tree(tmpdir) == []

    def test_returns_sorted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for name in ["c.txt", "a.txt", "b.txt"]:
                (root / name).write_text(name)

            files = TreeSed.collect_tree(root)
            assert files == sorted(files)

    def test_accepts_string_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "f.txt").write_text("x")
            files = TreeSed.collect_tree(tmpdir)
            assert len(files) == 1


class TestCollectFiles:
    def test_filters_to_existing_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            f1 = root / "exists.txt"
            f1.write_text("x")
            d = root / "adir"
            d.mkdir()

            files = TreeSed.collect_files([f1, d, root / "nope.txt"])
            assert files == [f1]

    def test_empty_input(self):
        assert TreeSed.collect_files([]) == []

    def test_accepts_strings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("x")
            files = TreeSed.collect_files([str(f)])
            assert len(files) == 1
            assert files[0] == f


class TestCompilePattern:
    def test_literal_escapes_special_chars(self):
        ts = TreeSed()
        pat = ts.compile_pattern("$10.00")
        assert pat.search("$10.00") is not None
        assert pat.search("X10X00") is None

    def test_regex_mode_preserves_pattern(self):
        ts = TreeSed(use_regex=True)
        pat = ts.compile_pattern(r"\d+")
        assert pat.search("abc123") is not None
        assert pat.search("abc") is None

    def test_case_insensitive_default(self):
        ts = TreeSed()
        pat = ts.compile_pattern("hello")
        assert pat.search("HELLO") is not None

    def test_case_sensitive(self):
        ts = TreeSed(case_sensitive=True)
        pat = ts.compile_pattern("hello")
        assert pat.search("HELLO") is None
        assert pat.search("hello") is not None


class TestSearchFile:
    def test_finds_matches_with_line_numbers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("foo\nbar\nfoo again\n")

            ts = TreeSed()
            compiled = ts.compile_pattern("foo")
            result = ts.search_file(compiled, f)

            assert result is not None
            assert result.count == 2
            assert result.line_numbers == [1, 3]

    def test_returns_none_on_no_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("nothing here\n")

            ts = TreeSed()
            compiled = ts.compile_pattern("missing")
            assert ts.search_file(compiled, f) is None

    def test_returns_none_for_unreadable_file(self):
        ts = TreeSed()
        compiled = ts.compile_pattern("test")
        assert ts.search_file(compiled, Path("/nonexistent/file.txt")) is None

    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "empty.txt"
            f.write_text("")

            ts = TreeSed()
            compiled = ts.compile_pattern("test")
            assert ts.search_file(compiled, f) is None


class TestSearch:
    def test_case_insensitive_literal_search(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("Hello World\nhello world\nHELLO WORLD\nfoo bar\n")

            ts = TreeSed()
            results = ts.search("hello", [f])

            assert len(results) == 1
            assert results[0].count == 3
            assert results[0].line_numbers == [1, 2, 3]

    def test_case_sensitive_search(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("Hello World\nhello world\nHELLO WORLD\n")

            ts = TreeSed(case_sensitive=True)
            results = ts.search("hello", [f])

            assert len(results) == 1
            assert results[0].count == 1
            assert results[0].line_numbers == [2]

    def test_regex_search(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("foo123\nbar456\nfoo789\n")

            ts = TreeSed(use_regex=True)
            results = ts.search(r"foo\d+", [f])

            assert len(results) == 1
            assert results[0].count == 2
            assert results[0].line_numbers == [1, 3]

    def test_literal_escapes_regex_chars(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("price is $10.00\nfoo\n")

            ts = TreeSed()
            results = ts.search("$10.00", [f])

            assert len(results) == 1
            assert results[0].count == 1

    def test_no_matches_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("nothing here\n")

            ts = TreeSed()
            assert ts.search("missing", [f]) == []

    def test_search_multiple_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f1 = Path(tmpdir) / "a.txt"
            f1.write_text("needle in haystack\n")
            f2 = Path(tmpdir) / "b.txt"
            f2.write_text("no match\n")
            f3 = Path(tmpdir) / "c.txt"
            f3.write_text("another needle\n")

            ts = TreeSed()
            results = ts.search("needle", [f1, f2, f3])

            assert len(results) == 2
            paths = [r.path for r in results]
            assert f1 in paths
            assert f3 in paths


class TestReplaceFile:
    def test_basic_replace_with_backup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("Hello World\nfoo bar\n")

            ts = TreeSed()
            compiled = ts.compile_pattern("Hello")
            result = ts.replace_file(compiled, "Goodbye", f)

            assert result is not None
            assert result.count == 1
            assert result.backup_path is not None
            assert result.backup_path.exists()
            assert result.backup_path.read_text() == "Hello World\nfoo bar\n"
            assert f.read_text() == "Goodbye World\nfoo bar\n"

    def test_replace_without_backup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("Hello World\n")

            ts = TreeSed()
            compiled = ts.compile_pattern("Hello")
            result = ts.replace_file(compiled, "Goodbye", f, backup=False)

            assert result is not None
            assert result.backup_path is None
            assert f.read_text() == "Goodbye World\n"

    def test_no_match_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            original = "no match here\n"
            f.write_text(original)

            ts = TreeSed()
            compiled = ts.compile_pattern("missing")
            assert ts.replace_file(compiled, "found", f) is None
            assert f.read_text() == original

    def test_backup_has_pid_suffix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("hello\n")

            ts = TreeSed()
            compiled = ts.compile_pattern("hello")
            result = ts.replace_file(compiled, "bye", f)

            assert result.backup_path.name == f"test.txt.{os.getpid()}"

    def test_unreadable_file_returns_none(self):
        ts = TreeSed()
        compiled = ts.compile_pattern("test")
        assert ts.replace_file(
            compiled, "x", Path("/nonexistent/file.txt")
        ) is None


class TestReplace:
    def test_basic_replace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("Hello World\nfoo bar\n")

            ts = TreeSed()
            results = ts.replace("Hello", "Goodbye", [f], backup=False)

            assert len(results) == 1
            assert results[0].count == 1
            assert f.read_text() == "Goodbye World\nfoo bar\n"

    def test_replace_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("Hello HELLO hello\n")

            ts = TreeSed()
            results = ts.replace("hello", "bye", [f], backup=False)

            assert len(results) == 1
            assert f.read_text() == "bye bye bye\n"

    def test_replace_case_sensitive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("Hello HELLO hello\n")

            ts = TreeSed(case_sensitive=True)
            results = ts.replace("hello", "bye", [f], backup=False)

            assert len(results) == 1
            assert f.read_text() == "Hello HELLO bye\n"

    def test_replace_no_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            original = "no match here\n"
            f.write_text(original)

            ts = TreeSed()
            results = ts.replace("missing", "found", [f])

            assert results == []
            assert f.read_text() == original

    def test_replace_counts_lines_not_occurrences(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("foo foo foo\nbar\nfoo\n")

            ts = TreeSed()
            results = ts.replace("foo", "baz", [f], backup=False)

            assert len(results) == 1
            # 2 lines contain "foo", even though there are 4 occurrences
            assert results[0].count == 2
            assert f.read_text() == "baz baz baz\nbar\nbaz\n"

    def test_replace_regex_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("foo123 bar456\n")

            ts = TreeSed(use_regex=True)
            results = ts.replace(r"\d+", "NUM", [f], backup=False)

            assert len(results) == 1
            assert f.read_text() == "fooNUM barNUM\n"

    def test_replace_multiple_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f1 = Path(tmpdir) / "a.txt"
            f1.write_text("old value\n")
            f2 = Path(tmpdir) / "b.txt"
            f2.write_text("no match\n")
            f3 = Path(tmpdir) / "c.txt"
            f3.write_text("old stuff\n")

            ts = TreeSed()
            results = ts.replace("old", "new", [f1, f2, f3], backup=False)

            assert len(results) == 2
            assert f1.read_text() == "new value\n"
            assert f2.read_text() == "no match\n"
            assert f3.read_text() == "new stuff\n"

    def test_replace_with_backup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("old\n")

            ts = TreeSed()
            results = ts.replace("old", "new", [f], backup=True)

            assert len(results) == 1
            assert results[0].backup_path is not None
            assert results[0].backup_path.exists()
            assert results[0].backup_path.read_text() == "old\n"
            assert f.read_text() == "new\n"

    def test_literal_replacement_preserves_backslashes(self):
        """In literal mode, backslashes in replacement are not interpreted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("foo\n")

            ts = TreeSed()
            results = ts.replace("foo", r"bar\nbaz", [f], backup=False)

            assert len(results) == 1
            # Should be literal \n, not a newline
            assert f.read_text() == "bar\\nbaz\n"

    def test_regex_replacement_interprets_backreferences(self):
        """In regex mode, backreferences in replacement work."""
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("hello world\n")

            ts = TreeSed(use_regex=True)
            results = ts.replace(
                r"(hello) (world)", r"\2 \1", [f], backup=False
            )

            assert len(results) == 1
            assert f.read_text() == "world hello\n"


class TestMain:
    def test_search_mode(self, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("Hello World\nfoo bar\nhello again\n")

            ret = main(["hello", "--files", str(f)])

            assert ret == 0
            out = capsys.readouterr().out
            assert "Search mode" in out
            assert "2 matches" in out

    def test_replace_mode(self, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("Hello World\n")

            ret = main(["Hello", "Goodbye", "--files", str(f)])

            assert ret == 0
            out = capsys.readouterr().out
            assert "EDIT mode" in out
            assert "Replaced" in out
            assert f.read_text() == "Goodbye World\n"

    def test_no_files_error(self, capsys):
        ret = main(["pattern", "--files", "/nonexistent/file.txt"])

        assert ret == 1
        err = capsys.readouterr().err
        assert "No input files" in err

    def test_quiet_mode(self, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("Hello\n")

            ret = main(["hello", "--files", str(f), "--quiet"])

            assert ret == 0
            out = capsys.readouterr().out
            assert "search_pattern" not in out
            assert "Search mode" not in out
            # Results still shown
            assert "1 matches" in out

    def test_tree_mode(self, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.txt").write_text("needle here\n")
            sub = Path(tmpdir) / "sub"
            sub.mkdir()
            (sub / "b.txt").write_text("needle there\n")

            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                ret = main(["needle", "--tree"])
            finally:
                os.chdir(old_cwd)

            assert ret == 0
            out = capsys.readouterr().out
            assert "2 matches" not in out  # 1 per file, not aggregated
            assert "1 matches on lines: 1" in out

    def test_no_backup_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("old\n")

            main(["old", "new", "--files", str(f), "--no-backup"])

            assert f.read_text() == "new\n"
            backup = Path(f"{f}.{os.getpid()}")
            assert not backup.exists()

    def test_case_sensitive_flag(self, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("Hello\nhello\nHELLO\n")

            ret = main(
                ["hello", "--files", str(f), "--case-sensitive"]
            )

            assert ret == 0
            out = capsys.readouterr().out
            assert "1 matches" in out

    def test_regex_flag(self, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.txt"
            f.write_text("foo123\nbar456\nbaz\n")

            ret = main([r"\d+", "--files", str(f), "--regex"])

            assert ret == 0
            out = capsys.readouterr().out
            assert "2 matches" in out

    def test_mutually_exclusive_tree_and_files(self):
        with pytest.raises(SystemExit):
            main(["pattern", "--tree", "--files", "a.txt"])

    def test_requires_source(self):
        with pytest.raises(SystemExit):
            main(["pattern"])
