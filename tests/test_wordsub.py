#!/usr/bin/env python3
"""Tests for wordsub.py"""

import io
import os
from pathlib import Path

import pytest

from wordsub import (
    DEFAULT_EXCLUDES,
    load_dictionary,
    split_lines,
    DEFAULT_SUFFIXES,
    SUBSTITUTIONS,
    DirectoryProgress,
    Totals,
    WordSub,
    iter_matches,
    main,
    normalize_suffix,
    recase,
    run,
)


@pytest.fixture
def tree(tmp_path):
    """A small tree with matches in visible, hidden and excluded locations."""
    (tmp_path / "a.md").write_text("a load-bearing wall\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.md").write_text("no match here\nanother load-bearing beam\n")
    (tmp_path / "notes.txt").write_text("load-bearing in a txt file\n")
    git = tmp_path / ".git"
    git.mkdir()
    (git / "config.md").write_text("load-bearing\n")
    hidden_dir_file = tmp_path / ".hidden"
    hidden_dir_file.mkdir()
    (hidden_dir_file / "c.md").write_text("load-bearing\n")
    (tmp_path / ".dotfile.md").write_text("load-bearing\n")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "d.md").write_text("load-bearing\n")
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "e.md").write_text("load-bearing\n")
    return tmp_path


class TestDictionary:
    def test_seed_entry_present(self):
        assert SUBSTITUTIONS["load-bearing"] == "structural"

    def test_empty_dictionary_rejected(self):
        with pytest.raises(ValueError):
            WordSub(substitutions={})

    def test_custom_dictionary(self):
        ws = WordSub(substitutions={"foo": "bar"})
        text, count = ws.replace_text("foo and load-bearing")
        assert count == 1
        assert text == "bar and load-bearing"

    def test_module_dictionary_not_mutated_by_instance(self):
        ws = WordSub()
        ws.substitutions["extra"] = "term"
        assert "extra" not in SUBSTITUTIONS


class TestRecase:
    @pytest.mark.parametrize(
        "found,expected",
        [
            ("load-bearing", "structural"),
            ("Load-bearing", "Structural"),
            ("LOAD-BEARING", "STRUCTURAL"),
            ("Load-Bearing", "Structural"),
            ("Load-BEARING", "Structural"),
            ("LOAD-bearing", "Structural"),
            ("LoAd-BeArInG", "Structural"),
            ("lOAD-BEARING", "structural"),
            ("lOaD-bEaRiNg", "structural"),
        ],
    )
    def test_styles(self, found, expected):
        assert recase(found, "structural") == expected

    def test_leading_capital_survives_unreproducible_casing(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text("Load-BEARING walls carry weight.\n")
        WordSub().replace_file(path)
        assert path.read_text() == "Structural walls carry weight.\n"


class TestScanText:
    def test_finds_term(self):
        ws = WordSub()
        matches = ws.scan_text("a load-bearing wall")
        assert len(matches) == 1
        m = matches[0]
        assert m.found == "load-bearing"
        assert m.replacement == "structural"
        assert m.line_number == 1
        assert m.column == 3

    def test_reports_line_numbers(self):
        ws = WordSub()
        matches = ws.scan_text("x\nload-bearing\ny\nload-bearing\n")
        assert [m.line_number for m in matches] == [2, 4]

    def test_multiple_on_one_line(self):
        ws = WordSub()
        matches = ws.scan_text("load-bearing and load-bearing")
        assert [m.column for m in matches] == [1, 18]

    def test_case_insensitive_by_default(self):
        ws = WordSub()
        matches = ws.scan_text("LOAD-BEARING and Load-Bearing")
        assert len(matches) == 2
        assert [m.replacement for m in matches] == ["STRUCTURAL", "Structural"]

    def test_replacement_recased_per_match(self):
        ws = WordSub()
        text = "A Load-bearing wall, a load-bearing beam, LOAD-BEARING too."
        assert [m.replacement for m in ws.scan_text(text)] == [
            "Structural",
            "structural",
            "STRUCTURAL",
        ]

    def test_case_sensitive_mode(self):
        ws = WordSub(case_sensitive=True)
        assert ws.scan_text("LOAD-BEARING and Load-Bearing") == []
        assert len(ws.scan_text("load-bearing")) == 1

    def test_no_preserve_case(self):
        ws = WordSub(preserve_case=False)
        matches = ws.scan_text("LOAD-BEARING")
        assert matches[0].replacement == "structural"

    def test_preserve_case_inert_when_case_sensitive(self):
        ws = WordSub(case_sensitive=True, preserve_case=True)
        assert ws.preserve_case is False
        assert ws.scan_text("load-bearing")[0].replacement == "structural"

    def test_term_normalisation_follows_mode(self):
        assert WordSub().scan_text("LOAD-BEARING")[0].term == "load-bearing"
        ws = WordSub(case_sensitive=True)
        assert ws.scan_text("load-bearing")[0].term == "load-bearing"

    def test_whole_word_only(self):
        ws = WordSub()
        assert ws.scan_text("nonload-bearing") == []
        assert ws.scan_text("load-bearings") == []
        assert ws.scan_text("load-bearing_wall") == []

    def test_punctuation_boundaries_match(self):
        ws = WordSub()
        assert len(ws.scan_text('"load-bearing", yes.')) == 1

    def test_longest_term_wins(self):
        ws = WordSub(substitutions={"load": "x", "load-bearing": "structural"})
        matches = ws.scan_text("load-bearing")
        assert len(matches) == 1
        assert matches[0].replacement == "structural"


class TestSuffixFilter:
    def test_default_is_markdown_only(self):
        assert DEFAULT_SUFFIXES == frozenset({".md"})
        assert WordSub().suffixes == frozenset({".md"})

    def test_non_markdown_skipped(self, tree):
        names = {p.name for p in WordSub().collect_tree(tree)}
        assert "notes.txt" not in names
        assert names == {"a.md", "b.md"}

    def test_non_markdown_skipped_under_hidden(self, tree):
        names = {p.name for p in WordSub(include_hidden=True).collect_tree(tree)}
        assert "notes.txt" not in names

    def test_non_markdown_never_rewritten(self, tree):
        WordSub().replace_tree(tree)
        assert (tree / "notes.md").exists() is False
        assert (tree / "notes.txt").read_text() == (
            "load-bearing in a txt file\n"
        )

    @pytest.mark.parametrize("name", ["a.MD", "a.Md"])
    def test_extension_match_is_case_insensitive(self, tmp_path, name):
        (tmp_path / name).write_text("load-bearing\n")
        assert len(WordSub().collect_tree(tmp_path)) == 1

    def test_custom_suffixes(self, tree):
        ws = WordSub(suffixes=["txt"])
        assert [p.name for p in ws.collect_tree(tree)] == ["notes.txt"]

    def test_multiple_suffixes(self, tree):
        ws = WordSub(suffixes=[".md", ".txt"])
        names = {p.name for p in ws.collect_tree(tree)}
        assert names == {"a.md", "b.md", "notes.txt"}

    def test_none_scans_every_file(self, tree):
        ws = WordSub(suffixes=None)
        assert ws.suffixes is None
        names = {p.name for p in ws.collect_tree(tree)}
        assert names == {"a.md", "b.md", "notes.txt"}

    def test_extensionless_file_skipped_by_default(self, tmp_path):
        (tmp_path / "README").write_text("load-bearing\n")
        assert WordSub().collect_tree(tmp_path) == []

    def test_explicit_file_root_bypasses_the_filter(self, tree):
        target = tree / "notes.txt"
        assert WordSub().collect_tree(target) == [target]
        assert len(WordSub().scan_tree(target)) == 1

    def test_wanted_predicate(self):
        ws = WordSub()
        assert ws.wanted(Path("a/b.md")) is True
        assert ws.wanted(Path("a/b.txt")) is False
        assert WordSub(suffixes=None).wanted(Path("a/b.txt")) is True

    @pytest.mark.parametrize(
        "given,expected",
        [
            ("md", ".md"),
            (".md", ".md"),
            ("*.md", ".md"),
            ("MD", ".md"),
            (" .Rmd ", ".rmd"),
        ],
    )
    def test_normalize_suffix(self, given, expected):
        assert normalize_suffix(given) == expected


class TestCollectTree:
    def test_skips_dot_directories(self, tree):
        ws = WordSub()
        names = {p.name for p in ws.collect_tree(tree)}
        assert names == {"a.md", "b.md"}

    def test_skips_dot_files(self, tree):
        ws = WordSub()
        assert not any(p.name == ".dotfile.md" for p in ws.collect_tree(tree))

    def test_hidden_included_on_request(self, tree):
        ws = WordSub(include_hidden=True)
        names = {p.name for p in ws.collect_tree(tree)}
        assert {"config.md", ".dotfile.md", "c.md", "e.md"} <= names

    def test_excluded_directories_pruned(self, tree):
        ws = WordSub()
        assert not any(
            "__pycache__" in p.parts for p in ws.collect_tree(tree)
        )
        assert "__pycache__" in DEFAULT_EXCLUDES

    def test_dot_venv_pruned(self, tree):
        ws = WordSub()
        assert not any(".venv" in p.parts for p in ws.collect_tree(tree))
        assert ws.is_hidden(".venv") is True

    def test_dot_venv_walked_with_hidden(self, tree):
        ws = WordSub(include_hidden=True)
        assert any(".venv" in p.parts for p in ws.collect_tree(tree))

    @pytest.mark.parametrize(
        "name", ["venv", "env", "build", "dist", "node_modules", "__pycache__"]
    )
    def test_build_and_dependency_trees_pruned(self, tmp_path, name):
        (tmp_path / "keep.md").write_text("load-bearing\n")
        target = tmp_path / name
        target.mkdir()
        (target / "skip.md").write_text("load-bearing\n")
        assert name in DEFAULT_EXCLUDES
        ws = WordSub()
        assert [p.name for p in ws.collect_tree(tmp_path)] == ["keep.md"]

    @pytest.mark.parametrize("name", ["venv", "build", "dist"])
    def test_excluded_by_name_stays_pruned_under_hidden(self, tmp_path, name):
        (tmp_path / name).mkdir()
        (tmp_path / name / "skip.md").write_text("load-bearing\n")
        ws = WordSub(include_hidden=True)
        assert ws.collect_tree(tmp_path) == []

    def test_excluded_name_reachable_as_explicit_root(self, tmp_path):
        build = tmp_path / "build"
        build.mkdir()
        (build / "a.md").write_text("load-bearing\n")
        assert len(WordSub().scan_tree(build)) == 1

    def test_custom_excludes_replace_defaults(self, tree):
        ws = WordSub(excludes={"sub"})
        names = {p.name for p in ws.collect_tree(tree)}
        assert "b.md" not in names
        assert names == {"a.md", "d.md"}

    def test_single_file_root(self, tree):
        ws = WordSub()
        target = tree / "a.md"
        assert ws.collect_tree(target) == [target]

    def test_hidden_single_file_root_is_honoured(self, tree):
        ws = WordSub()
        target = tree / ".dotfile.md"
        assert ws.collect_tree(target) == [target]

    def test_sorted(self, tmp_path):
        for name in ["c.md", "a.md", "b.md"]:
            (tmp_path / name).write_text("x")
        ws = WordSub()
        files = ws.collect_tree(tmp_path)
        assert files == sorted(files)

    def test_symlinks_skipped(self, tmp_path):
        (tmp_path / "real.md").write_text("load-bearing\n")
        (tmp_path / "link.md").symlink_to(tmp_path / "real.md")
        ws = WordSub()
        assert [p.name for p in ws.collect_tree(tmp_path)] == ["real.md"]

    def test_empty_directory(self, tmp_path):
        assert WordSub().collect_tree(tmp_path) == []


class TestReadText:
    def test_text_returned_without_error(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text("load-bearing\n")
        assert WordSub().read_text(path) == ("load-bearing\n", None)

    def test_binary_skipped(self, tmp_path):
        path = tmp_path / "bin.dat"
        path.write_bytes(b"load-bearing\x00load-bearing")
        assert WordSub().read_text(path) == (None, None)

    def test_invalid_utf8_skipped(self, tmp_path):
        path = tmp_path / "bad.md"
        path.write_bytes(b"load-bearing \xff\xfe\n")
        assert WordSub().read_text(path) == (None, None)

    def test_oversized_skipped(self, tmp_path):
        path = tmp_path / "big.md"
        path.write_text("load-bearing\n" * 100)
        assert WordSub(max_bytes=10).read_text(path) == (None, None)

    def test_missing_file_is_a_failure_not_a_skip(self, tmp_path):
        text, error = WordSub().read_text(tmp_path / "nope.md")
        assert text is None
        assert error is not None

    def test_policy_skip_reports_no_result(self, tmp_path):
        path = tmp_path / "big.md"
        path.write_text("load-bearing\n" * 100)
        assert WordSub(max_bytes=10).scan_file(path) is None


class TestScanTree:
    def test_reports_visible_matches_only(self, tree):
        results = WordSub().scan_tree(tree)
        assert {r.path.name for r in results} == {"a.md", "b.md"}
        assert sum(r.count for r in results) == 2

    def test_hidden_matches_with_flag(self, tree):
        results = WordSub(include_hidden=True).scan_tree(tree)
        assert sum(r.count for r in results) == 6

    def test_no_matches(self, tmp_path):
        (tmp_path / "a.md").write_text("nothing to see\n")
        assert WordSub().scan_tree(tmp_path) == []

    def test_iter_matches_flattens(self, tree):
        results = WordSub().scan_tree(tree)
        assert len(list(iter_matches(results))) == 2

    def test_scan_does_not_modify_files(self, tree):
        before = (tree / "a.md").read_text()
        WordSub().scan_tree(tree)
        assert (tree / "a.md").read_text() == before


class TestReplace:
    def test_rewrites_visible_files(self, tree):
        results = WordSub().replace_tree(tree)
        assert sum(r.replaced for r in results) == 2
        assert (tree / "a.md").read_text() == "a structural wall\n"
        assert "structural beam" in (tree / "sub" / "b.md").read_text()

    def test_leaves_dot_directories_untouched(self, tree):
        WordSub().replace_tree(tree)
        assert (tree / ".git" / "config.md").read_text() == "load-bearing\n"
        assert (tree / ".dotfile.md").read_text() == "load-bearing\n"

    def test_replaces_hidden_with_flag(self, tree):
        WordSub(include_hidden=True).replace_tree(tree)
        assert (tree / ".git" / "config.md").read_text() == "structural\n"

    def test_rewrites_every_casing_recased(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text("Load-bearing and LOAD-BEARING and load-bearing\n")
        results = WordSub().replace_tree(tmp_path)
        assert sum(r.replaced for r in results) == 3
        assert path.read_text() == "Structural and STRUCTURAL and structural\n"

    def test_case_sensitive_mode_rewrites_exact_spelling_only(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text("Load-bearing and LOAD-BEARING and load-bearing\n")
        WordSub(case_sensitive=True).replace_tree(tmp_path)
        assert path.read_text() == "Load-bearing and LOAD-BEARING and structural\n"

    def test_preserves_crlf_line_endings(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_bytes(b"load-bearing\r\nsecond\r\n")
        WordSub().replace_tree(tmp_path)
        assert path.read_bytes() == b"structural\r\nsecond\r\n"

    def test_unchanged_file_not_rewritten(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text("nothing here\n")
        mtime = path.stat().st_mtime_ns
        assert WordSub().replace_file(path) is None
        assert path.stat().st_mtime_ns == mtime

    def test_binary_file_untouched(self, tmp_path):
        path = tmp_path / "bin.md"
        data = b"load-bearing\x00"
        path.write_bytes(data)
        WordSub().replace_tree(tmp_path)
        assert path.read_bytes() == data

    def test_replace_is_idempotent(self, tree):
        WordSub().replace_tree(tree)
        assert WordSub().replace_tree(tree) == []


class TestExactFix:
    MIXED = "A Load-bearing wall, a load-bearing beam, LOAD-BEARING too.\n"

    def test_reports_every_casing(self):
        ws = WordSub(exact_fix=True)
        matches = ws.scan_text(self.MIXED)
        assert [m.found for m in matches] == [
            "Load-bearing",
            "load-bearing",
            "LOAD-BEARING",
        ]

    def test_marks_only_exact_spelling_fixable(self):
        ws = WordSub(exact_fix=True)
        matches = ws.scan_text(self.MIXED)
        assert [m.fixable for m in matches] == [False, True, False]

    def test_manual_property_lists_the_rest(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text(self.MIXED)
        result = WordSub(exact_fix=True).scan_file(path)
        assert [m.found for m in result.manual] == [
            "Load-bearing",
            "LOAD-BEARING",
        ]

    def test_replaces_exact_spelling_only(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text(self.MIXED)
        results = WordSub(exact_fix=True).replace_tree(tmp_path)
        assert sum(r.replaced for r in results) == 1
        assert path.read_text() == (
            "A Load-bearing wall, a structural beam, LOAD-BEARING too.\n"
        )

    def test_replace_text_counts_fixable_only(self):
        text, count = WordSub(exact_fix=True).replace_text(self.MIXED)
        assert count == 1
        assert "structural beam" in text
        assert "Load-bearing wall" in text

    def test_manual_only_file_reported_but_untouched(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text("Load-bearing only\n")
        results = WordSub(exact_fix=True).replace_tree(tmp_path)
        assert len(results) == 1
        assert results[0].replaced == 0
        assert len(results[0].manual) == 1
        assert path.read_text() == "Load-bearing only\n"

    def test_suggestion_still_recased(self):
        ws = WordSub(exact_fix=True)
        matches = ws.scan_text("Load-bearing")
        assert matches[0].replacement == "Structural"
        assert matches[0].fixable is False

    def test_leftovers_survive_a_second_pass(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text(self.MIXED)
        ws = WordSub(exact_fix=True)
        ws.replace_tree(tmp_path)
        results = ws.replace_tree(tmp_path)
        assert sum(r.replaced for r in results) == 0
        assert sum(len(r.manual) for r in results) == 2

    def test_redundant_under_case_sensitive(self):
        ws = WordSub(case_sensitive=True, exact_fix=True)
        assert ws.exact_fix is False
        matches = ws.scan_text(self.MIXED)
        assert [m.found for m in matches] == ["load-bearing"]
        assert matches[0].fixable is True

    def test_default_mode_marks_everything_fixable(self):
        matches = WordSub().scan_text(self.MIXED)
        assert all(m.fixable for m in matches)


class TestDirectoryProgress:
    def make(self, **kwargs):
        stream = io.StringIO()
        return stream, DirectoryProgress(stream=stream, enabled=True, **kwargs)

    def test_writes_rewritable_line(self):
        stream, progress = self.make(width=80)
        progress(Path("a/b"))
        assert stream.getvalue() == "\rscanning [1 dir, 0 files] a/b"

    def test_counter_increments(self):
        stream, progress = self.make(width=80)
        progress(Path("a"))
        progress(Path("b"))
        assert "scanning [2 dirs, 0 files] b" in stream.getvalue()
        assert progress.count == 2

    def test_pads_over_a_longer_previous_line(self):
        stream, progress = self.make(width=80)
        progress(Path("a-very-long-directory-name"))
        progress(Path("b"))
        written = stream.getvalue().split("\r")[-1]
        assert written.startswith("scanning [2 dirs, 0 files] b")
        assert len(written) == len(
            "scanning [1 dir, 0 files] a-very-long-directory-name"
        )

    def test_truncates_the_path_not_the_counter(self):
        stream, progress = self.make(width=40)
        progress(Path("/a/very/deep/path/to/somewhere"))
        line = stream.getvalue().lstrip("\r")
        assert len(line) <= 39
        assert line.startswith("scanning [1 dir, 0 files] ...")
        assert line.endswith("somewhere")

    def test_short_path_is_not_truncated(self):
        stream, progress = self.make(width=80)
        progress(Path("/a/b"))
        assert stream.getvalue().lstrip("\r") == "scanning [1 dir, 0 files] /a/b"

    def test_tick_redraws_every_n_files(self):
        stream, progress = self.make(width=80, every=3)
        progress(Path("a"))
        stream.truncate(0), stream.seek(0)
        for _ in range(2):
            progress.tick()
        assert stream.getvalue() == ""
        progress.tick()
        assert "3 files" in stream.getvalue()
        assert progress.files == 3

    def test_tick_is_a_noop_when_disabled(self):
        stream = io.StringIO()
        progress = DirectoryProgress(stream=stream, enabled=False, every=1)
        progress.tick()
        assert stream.getvalue() == ""
        assert progress.files == 0

    def test_absurdly_narrow_width(self):
        stream, progress = self.make(width=10)
        progress(Path("/a/very/deep/path"))
        line = stream.getvalue().lstrip("\r")
        assert len(line) <= 9

    def test_clear_erases_the_line(self):
        stream, progress = self.make(width=80)
        progress(Path("a"))
        progress.clear()
        written = "scanning [1 dir, 0 files] a"
        assert stream.getvalue().endswith("\r" + " " * len(written) + "\r")

    def test_clear_without_output_is_a_noop(self):
        stream, progress = self.make(width=80)
        progress.clear()
        assert stream.getvalue() == ""

    def test_disabled_writes_nothing(self):
        stream = io.StringIO()
        progress = DirectoryProgress(stream=stream, enabled=False)
        progress(Path("a"))
        progress.clear()
        assert stream.getvalue() == ""
        assert progress.count == 0

    def test_auto_disabled_for_non_tty(self):
        stream = io.StringIO()
        progress = DirectoryProgress(stream=stream)
        assert progress.enabled is False
        progress(Path("a"))
        assert stream.getvalue() == ""

    def test_auto_enabled_for_tty(self):
        class Tty(io.StringIO):
            def isatty(self):
                return True

        progress = DirectoryProgress(stream=Tty(), width=80)
        assert progress.enabled is True


class TestProgressDuringWalk:
    def test_reports_each_directory(self, tree):
        seen = []
        WordSub().scan_tree(tree, progress=seen.append)
        assert [p.name for p in seen] == [tree.name, "sub"]

    def test_reports_directories_holding_no_matches(self, tmp_path):
        (tmp_path / "empty").mkdir()
        (tmp_path / "empty" / "nested").mkdir()
        seen = []
        WordSub().scan_tree(tmp_path, progress=seen.append)
        assert [p.name for p in seen] == [tmp_path.name, "empty", "nested"]

    def test_skips_pruned_directories(self, tree):
        seen = []
        WordSub().scan_tree(tree, progress=seen.append)
        names = {p.name for p in seen}
        assert ".git" not in names
        assert "__pycache__" not in names

    def test_replace_tree_reports_too(self, tree):
        seen = []
        WordSub().replace_tree(tree, progress=seen.append)
        assert [p.name for p in seen] == [tree.name, "sub"]

    def test_fires_before_the_files_are_read(self, tree):
        order = []
        ws = WordSub()
        for path in ws.iter_tree(tree, progress=lambda d: order.append(d.name)):
            order.append(path.name)
        assert order.index(tree.name) < order.index("a.md")
        assert order.index("sub") < order.index("b.md")

    def test_single_file_root_reports_nothing(self, tree):
        seen = []
        WordSub().scan_tree(tree / "a.md", progress=seen.append)
        assert seen == []

    def test_no_progress_callback_is_optional(self, tree):
        assert len(WordSub().scan_tree(tree)) == 2


class TestStreaming:
    def test_prints_each_file_as_it_is_read(self, tmp_path, capsys):
        for i in range(3):
            (tmp_path / f"{i}.md").write_text("load-bearing\n")
        totals = run(WordSub(), tmp_path)
        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 3
        assert totals.matches == 3 and totals.files == 3

    def test_output_precedes_the_end_of_the_walk(self, tmp_path, capsys):
        (tmp_path / "a.md").write_text("load-bearing\n")
        slow = tmp_path / "z-later"
        slow.mkdir()
        (slow / "b.md").write_text("load-bearing\n")
        seen = []
        ws = WordSub()

        class Watcher(DirectoryProgress):
            def __call__(self, directory):
                seen.append(("dir", directory.name))

        run(ws, tmp_path, progress=Watcher(enabled=False))
        out = capsys.readouterr().out
        assert out.count("-> structural") == 2

    def test_totals_for_replace(self, tmp_path):
        (tmp_path / "a.md").write_text("A Load-bearing and a load-bearing\n")
        totals = run(WordSub(exact_fix=True), tmp_path, replace=True, quiet=True)
        assert totals == Totals(
            matches=2, files=1, replaced=1, changed=1, manual=1
        )

    def test_quiet_suppresses_lines_not_counts(self, tmp_path, capsys):
        (tmp_path / "a.md").write_text("load-bearing\n")
        totals = run(WordSub(), tmp_path, quiet=True)
        assert capsys.readouterr().out == ""
        assert totals.matches == 1

    def test_clears_progress_before_each_print(self, tmp_path, capsys):
        (tmp_path / "a.md").write_text("load-bearing\n")
        stream = io.StringIO()
        progress = DirectoryProgress(stream=stream, enabled=True, width=80)
        run(WordSub(), tmp_path, progress=progress)
        assert stream.getvalue().endswith("\r")
        assert "scanning" in stream.getvalue()

    def test_progress_ticks_once_per_file(self, tmp_path):
        for i in range(5):
            (tmp_path / f"{i}.md").write_text("nothing\n")
        progress = DirectoryProgress(enabled=True, stream=io.StringIO())
        run(WordSub(), tmp_path, quiet=True, progress=progress)
        assert progress.files == 5

    def test_no_progress_argument_is_optional(self, tmp_path):
        (tmp_path / "a.md").write_text("load-bearing\n")
        assert run(WordSub(), tmp_path, quiet=True).matches == 1


class TestMain:
    def test_scan_reports_and_exits_one(self, tree, capsys):
        assert main([str(tree)]) == 1
        out = capsys.readouterr().out
        assert "a.md:1:3: load-bearing -> structural" in out
        assert "found 2 in 2 files" in out

    def test_scan_clean_tree_exits_zero(self, tmp_path, capsys):
        (tmp_path / "a.md").write_text("clean\n")
        assert main([str(tmp_path)]) == 0
        assert "found 0 in 0 files" in capsys.readouterr().out

    def test_scan_does_not_write(self, tree):
        main([str(tree)])
        assert (tree / "a.md").read_text() == "a load-bearing wall\n"

    def test_replace_exits_zero_and_writes(self, tree, capsys):
        assert main(["--replace", str(tree)]) == 0
        assert (tree / "a.md").read_text() == "a structural wall\n"
        assert "replaced 2 in 2 files" in capsys.readouterr().out

    def test_replace_skips_git(self, tree):
        main(["-r", str(tree)])
        assert (tree / ".git" / "config.md").read_text() == "load-bearing\n"

    def test_hidden_flag(self, tree, capsys):
        assert main(["--hidden", str(tree)]) == 1
        assert "found 6 in 6 files" in capsys.readouterr().out

    def test_dot_venv_untouched_by_replace(self, tree):
        main(["-r", str(tree)])
        assert (tree / ".venv" / "lib" / "e.md").read_text() == "load-bearing\n"

    def test_exclude_flag(self, tree, capsys):
        assert main(["--exclude", "sub", str(tree)]) == 1
        assert "found 1 in 1 files" in capsys.readouterr().out

    def test_quiet_prints_summary_only(self, tree, capsys):
        main(["--quiet", str(tree)])
        out = capsys.readouterr().out.strip().splitlines()
        assert out == ["found 2 in 2 files"]

    def test_case_insensitive_by_default(self, tmp_path, capsys):
        (tmp_path / "a.md").write_text("LOAD-BEARING\n")
        assert main([str(tmp_path)]) == 1
        assert "LOAD-BEARING -> STRUCTURAL" in capsys.readouterr().out

    def test_replace_recases_every_casing(self, tmp_path, capsys):
        path = tmp_path / "a.md"
        path.write_text("A Load-bearing wall, a load-bearing beam, LOAD-BEARING.\n")
        assert main(["-r", str(tmp_path)]) == 0
        assert path.read_text() == (
            "A Structural wall, a structural beam, STRUCTURAL.\n"
        )
        assert "replaced 3 in 1 files" in capsys.readouterr().out

    def test_case_sensitive_flag(self, tmp_path, capsys):
        (tmp_path / "a.md").write_text("LOAD-BEARING\n")
        assert main(["--case-sensitive", str(tmp_path)]) == 0
        assert "found 0 in 0 files" in capsys.readouterr().out

    def test_case_sensitive_short_flag(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text("Load-bearing and load-bearing\n")
        assert main(["-r", "-c", str(tmp_path)]) == 0
        assert path.read_text() == "Load-bearing and structural\n"

    def test_no_preserve_case_flag(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text("LOAD-BEARING\n")
        main(["-r", "--no-preserve-case", str(tmp_path)])
        assert path.read_text() == "structural\n"

    def test_single_file_argument(self, tree, capsys):
        assert main([str(tree / "a.md")]) == 1
        assert "found 1 in 1 files" in capsys.readouterr().out

    def test_list_prints_dictionary(self, capsys):
        assert main(["--list"]) == 0
        assert capsys.readouterr().out == "load-bearing -> structural\n"

    def test_missing_path_exits_two(self, tmp_path, capsys):
        assert main([str(tmp_path / "nope")]) == 2
        assert "no such path" in capsys.readouterr().err

    def test_default_path_is_cwd(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "a.md").write_text("load-bearing\n")
        monkeypatch.chdir(tmp_path)
        assert main([]) == 1
        assert "found 1 in 1 files" in capsys.readouterr().out

    def test_exact_fix_reports_all_marks_manual(self, tmp_path, capsys):
        (tmp_path / "a.md").write_text(
            "A Load-bearing wall, a load-bearing beam.\n"
        )
        assert main(["--exact-fix", str(tmp_path)]) == 1
        out = capsys.readouterr().out
        assert "Load-bearing -> Structural [manual]" in out
        assert "load-bearing -> structural\n" in out
        assert "found 2 in 1 files" in out
        assert "1 left for manual review" in out

    def test_exact_fix_replaces_one_of_two(self, tmp_path, capsys):
        path = tmp_path / "a.md"
        path.write_text("A Load-bearing wall, a load-bearing beam.\n")
        assert main(["-r", "--exact-fix", str(tmp_path)]) == 1
        assert path.read_text() == (
            "A Load-bearing wall, a structural beam.\n"
        )
        out = capsys.readouterr().out
        assert "replaced 1 in 1 files" in out
        assert "1 left for manual review" in out

    def test_exact_fix_exits_zero_when_nothing_manual(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text("a load-bearing beam\n")
        assert main(["-r", "--exact-fix", str(tmp_path)]) == 0
        assert path.read_text() == "a structural beam\n"

    def test_no_manual_marker_in_default_mode(self, tmp_path, capsys):
        (tmp_path / "a.md").write_text("Load-bearing\n")
        main([str(tmp_path)])
        out = capsys.readouterr().out
        assert "[manual]" not in out
        assert "left for manual review" not in out

    def test_replace_summary_counts_changed_files_only(self, tmp_path, capsys):
        (tmp_path / "a.md").write_text("load-bearing\n")
        (tmp_path / "b.md").write_text("Load-bearing\n")
        main(["-r", "--exact-fix", str(tmp_path)])
        assert "replaced 1 in 1 files" in capsys.readouterr().out

    def test_ext_flag_replaces_the_default(self, tree, capsys):
        assert main(["--ext", "txt", str(tree)]) == 1
        out = capsys.readouterr().out
        assert "notes.txt" in out
        assert "a.md" not in out
        assert "found 1 in 1 files" in out

    def test_ext_flag_repeatable(self, tree, capsys):
        assert main(["--ext", "md", "--ext", "txt", str(tree)]) == 1
        assert "found 3 in 3 files" in capsys.readouterr().out

    def test_ext_accepts_a_dotted_or_globbed_form(self, tree, capsys):
        assert main(["--ext", "*.txt", str(tree)]) == 1
        assert "found 1 in 1 files" in capsys.readouterr().out

    def test_all_files_flag(self, tree, capsys):
        assert main(["--all-files", str(tree)]) == 1
        assert "found 3 in 3 files" in capsys.readouterr().out

    def test_default_run_is_markdown_only(self, tree, capsys):
        assert main([str(tree)]) == 1
        out = capsys.readouterr().out
        assert "notes.txt" not in out
        assert "found 2 in 2 files" in out

    def test_replace_leaves_non_markdown_alone(self, tree):
        main(["-r", str(tree)])
        assert (tree / "notes.txt").read_text() == (
            "load-bearing in a txt file\n"
        )

    def test_no_progress_on_non_tty(self, tree, capsys):
        main([str(tree)])
        assert capsys.readouterr().err == ""

    def test_no_progress_flag(self, tree, capsys):
        assert main(["--no-progress", str(tree)]) == 1
        assert capsys.readouterr().err == ""

    def test_progress_stays_off_stdout(self, tree, capsys):
        main([str(tree)])
        assert "scanning" not in capsys.readouterr().out

    def test_max_bytes_flag(self, tree, capsys):
        assert main(["--max-bytes", "5", str(tree)]) == 0


@pytest.fixture
def readonly_file(tmp_path):
    """A matching file that cannot be written."""
    path = tmp_path / "ro.md"
    path.write_text("a load-bearing wall\n")
    os.chmod(path, 0o444)
    yield path
    os.chmod(path, 0o644)


@pytest.fixture
def unreadable_dir(tmp_path):
    """A directory holding a match that the walk cannot enter."""
    path = tmp_path / "locked"
    path.mkdir()
    (path / "z.md").write_text("load-bearing\n")
    (tmp_path / "open.md").write_text("load-bearing\n")
    os.chmod(path, 0o000)
    yield path
    os.chmod(path, 0o755)


@pytest.mark.skipif(
    os.geteuid() == 0, reason="root bypasses the permission bits under test"
)
class TestWriteFailures:
    def test_error_recorded(self, readonly_file):
        result = WordSub().replace_file(readonly_file)
        assert result.error is not None
        assert result.replaced == 0
        assert result.count == 1

    def test_file_left_alone(self, readonly_file):
        WordSub().replace_file(readonly_file)
        assert readonly_file.read_text() == "a load-bearing wall\n"

    def test_error_is_none_on_success(self, tmp_path):
        path = tmp_path / "ok.md"
        path.write_text("load-bearing\n")
        assert WordSub().replace_file(path).error is None

    def test_error_is_none_when_nothing_to_replace(self, tmp_path):
        path = tmp_path / "manual.md"
        path.write_text("Load-Bearing\n")
        ws = WordSub(exact_fix=True)
        assert ws.replace_file(path).error is None

    def test_run_counts_and_names_it(self, readonly_file, capsys):
        totals = run(WordSub(), readonly_file.parent, replace=True)
        assert totals.failed == 1
        assert totals.replaced == 0
        assert "ro.md" in capsys.readouterr().err

    def test_quiet_does_not_suppress_the_error(self, readonly_file, capsys):
        run(WordSub(), readonly_file.parent, replace=True, quiet=True)
        assert "ro.md" in capsys.readouterr().err

    def test_scan_mode_does_not_report_it(self, readonly_file, capsys):
        totals = run(WordSub(), readonly_file.parent)
        assert totals.failed == 0
        assert capsys.readouterr().err == ""

    def test_main_exits_two(self, readonly_file, capsys):
        assert main(["--replace", str(readonly_file.parent)]) == 2
        err = capsys.readouterr().err
        assert "ro.md" in err
        assert "1 path could not be processed" in err

    def test_main_summary_still_printed(self, readonly_file, capsys):
        main(["--replace", str(readonly_file.parent)])
        assert "replaced 0 in 0 files" in capsys.readouterr().out


@pytest.mark.skipif(
    os.geteuid() == 0, reason="root bypasses the permission bits under test"
)
class TestWalkFailures:
    def test_on_error_called(self, unreadable_dir):
        seen = []
        list(WordSub().iter_tree(unreadable_dir.parent, on_error=seen.append))
        assert len(seen) == 1
        assert seen[0].filename == str(unreadable_dir)

    def test_readable_files_still_yielded(self, unreadable_dir):
        found = WordSub().collect_tree(unreadable_dir.parent)
        assert [p.name for p in found] == ["open.md"]

    def test_callback_is_optional(self, unreadable_dir):
        assert WordSub().collect_tree(unreadable_dir.parent)

    def test_run_counts_and_names_it(self, unreadable_dir, capsys):
        totals = run(WordSub(), unreadable_dir.parent)
        assert totals.failed == 1
        assert totals.matches == 1
        assert str(unreadable_dir) in capsys.readouterr().err

    def test_main_scan_exits_two(self, unreadable_dir, capsys):
        assert main([str(unreadable_dir.parent)]) == 2
        assert "1 path could not be processed" in capsys.readouterr().err

    def test_main_replace_exits_two(self, unreadable_dir, capsys):
        assert main(["--replace", str(unreadable_dir.parent)]) == 2
        assert (unreadable_dir.parent / "open.md").read_text() == "structural\n"

    def test_clean_tree_still_exits_zero(self, tmp_path, capsys):
        (tmp_path / "a.md").write_text("nothing here\n")
        assert main([str(tmp_path)]) == 0
        assert capsys.readouterr().err == ""

    def test_scan_tree_forwards_the_callback(self, unreadable_dir):
        seen = []
        WordSub().scan_tree(unreadable_dir.parent, on_error=seen.append)
        assert len(seen) == 1

    def test_replace_tree_forwards_the_callback(self, unreadable_dir):
        seen = []
        WordSub().replace_tree(unreadable_dir.parent, on_error=seen.append)
        assert len(seen) == 1


@pytest.fixture
def unreadable_file(tmp_path):
    """A matching file the walk finds but cannot open."""
    path = tmp_path / "locked.md"
    path.write_text("a load-bearing wall\n")
    os.chmod(path, 0o000)
    yield path
    os.chmod(path, 0o644)


@pytest.mark.skipif(
    os.geteuid() == 0, reason="root bypasses the permission bits under test"
)
class TestReadFailures:
    def test_scan_file_records_the_error(self, unreadable_file):
        result = WordSub().scan_file(unreadable_file)
        assert result.error is not None
        assert result.matches == []

    def test_replace_file_records_the_error(self, unreadable_file):
        result = WordSub().replace_file(unreadable_file)
        assert result.error is not None
        assert result.replaced == 0

    def test_run_counts_and_names_it(self, unreadable_file, capsys):
        totals = run(WordSub(), unreadable_file.parent)
        assert totals.failed == 1
        assert "locked.md" in capsys.readouterr().err

    def test_not_counted_as_a_scanned_file(self, unreadable_file, capsys):
        totals = run(WordSub(), unreadable_file.parent)
        assert totals.files == 0
        assert totals.matches == 0
        assert "->" not in capsys.readouterr().out

    def test_main_exits_two(self, unreadable_file, capsys):
        assert main([str(unreadable_file.parent)]) == 2
        assert "1 path could not be processed" in capsys.readouterr().err

    def test_policy_skip_is_not_a_failure(self, tmp_path, capsys):
        (tmp_path / "big.md").write_text("load-bearing\n" * 100)
        assert main(["--max-bytes", "10", str(tmp_path)]) == 0
        assert capsys.readouterr().err == ""


class TestAtomicWrite:
    def test_content_replaced(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text("a load-bearing wall\n")
        WordSub().replace_file(path)
        assert path.read_text() == "a structural wall\n"

    def test_mode_preserved(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text("load-bearing\n")
        os.chmod(path, 0o640)
        WordSub().replace_file(path)
        assert oct(path.stat().st_mode)[-3:] == "640"

    def test_no_temporary_left_behind(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text("load-bearing\n")
        WordSub().replace_file(path)
        assert [p.name for p in tmp_path.iterdir()] == ["a.md"]

    def test_inode_changes_original_never_truncated(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text("load-bearing\n")
        before = path.stat().st_ino
        WordSub().replace_file(path)
        assert path.stat().st_ino != before

    def test_temporary_name_is_pruned_by_a_concurrent_walk(self, tmp_path):
        (tmp_path / ".a.md.xyz.tmp").write_text("load-bearing\n")
        assert WordSub().collect_tree(tmp_path) == []

    def test_unwritable_directory_reported(self, tmp_path):
        if os.geteuid() == 0:
            pytest.skip("root bypasses the permission bits under test")
        path = tmp_path / "a.md"
        path.write_text("load-bearing\n")
        os.chmod(tmp_path, 0o555)
        try:
            result = WordSub().replace_file(path)
        finally:
            os.chmod(tmp_path, 0o755)
        assert result.error is not None
        assert result.replaced == 0
        assert path.read_text() == "load-bearing\n"

    def test_no_temporary_left_after_a_failure(self, tmp_path):
        if os.geteuid() == 0:
            pytest.skip("root bypasses the permission bits under test")
        path = tmp_path / "a.md"
        path.write_text("load-bearing\n")
        os.chmod(tmp_path, 0o555)
        try:
            WordSub().replace_file(path)
        finally:
            os.chmod(tmp_path, 0o755)
        assert [p.name for p in tmp_path.iterdir()] == ["a.md"]

    def test_read_only_file_is_refused_not_renamed_over(self, tmp_path):
        if os.geteuid() == 0:
            pytest.skip("root bypasses the permission bits under test")
        path = tmp_path / "a.md"
        path.write_text("load-bearing\n")
        os.chmod(path, 0o444)
        try:
            result = WordSub().replace_file(path)
            assert result.error == "Permission denied"
            assert path.read_text() == "load-bearing\n"
            assert [p.name for p in tmp_path.iterdir()] == ["a.md"]
        finally:
            os.chmod(path, 0o644)


class TestLineSplitting:
    @pytest.mark.parametrize("char", ["\x0b", "\x0c", "\x1c", "\x85", "\u2028", "\u2029"])
    def test_not_treated_as_a_line_break(self, char):
        text = f"a{char}load-bearing b\nload-bearing c\n"
        assert [m.line_number for m in WordSub().scan_text(text)] == [1, 2]

    def test_newline_numbering_unchanged(self):
        text = "x\nload-bearing\ny\nload-bearing\n"
        assert [m.line_number for m in WordSub().scan_text(text)] == [2, 4]

    def test_crlf_numbering_and_column(self):
        matches = WordSub().scan_text("one\r\nload-bearing\r\n")
        assert (matches[0].line_number, matches[0].column) == (2, 1)

    def test_column_measured_from_the_line_start(self):
        text = "a\x0c load-bearing\n"
        m = WordSub().scan_text(text)[0]
        assert (m.line_number, m.column) == (1, 4)

    def test_trailing_newline_adds_no_match(self):
        assert len(WordSub().scan_text("load-bearing\n")) == 1

    def test_replacement_unaffected_by_the_split(self):
        text = "a\x0cload-bearing\n"
        assert WordSub().replace_text(text) == ("a\x0cstructural\n", 1)

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("a\nb", ["a", "b"]),
            ("a\r\nb", ["a", "b"]),
            ("a\n", ["a", ""]),
            ("", [""]),
            ("a\x0cb", ["a\x0cb"]),
            ("a\u2028b", ["a\u2028b"]),
        ],
    )
    def test_split_lines(self, text, expected):
        assert split_lines(text) == expected


class TestDictionaryFile:
    def write(self, tmp_path, body):
        path = tmp_path / "terms.txt"
        path.write_text(body)
        return path

    def test_parses_entries(self, tmp_path):
        path = self.write(tmp_path, "load-bearing -> structural\nfoo -> bar\n")
        assert load_dictionary(path) == {
            "load-bearing": "structural",
            "foo": "bar",
        }

    def test_ignores_blanks_and_comments(self, tmp_path):
        path = self.write(
            tmp_path, "# a note\n\n   \n  # indented\nfoo -> bar\n"
        )
        assert load_dictionary(path) == {"foo": "bar"}

    def test_whitespace_around_the_separator_is_optional(self, tmp_path):
        path = self.write(tmp_path, "foo->bar\n")
        assert load_dictionary(path) == {"foo": "bar"}

    def test_multi_word_term(self, tmp_path):
        path = self.write(tmp_path, "in order to -> to\n")
        ws = WordSub(substitutions=load_dictionary(path))
        assert ws.replace_text("in order to go") == ("to go", 1)

    @pytest.mark.parametrize(
        "body",
        ["foo bar\n", "-> bar\n", "foo ->\n", "  ->  \n"],
    )
    def test_malformed_line_rejected(self, tmp_path, body):
        with pytest.raises(ValueError):
            load_dictionary(self.write(tmp_path, body))

    def test_error_names_the_line(self, tmp_path):
        path = self.write(tmp_path, "foo -> bar\nbroken\n")
        with pytest.raises(ValueError, match=":2:"):
            load_dictionary(path)

    def test_duplicate_term_rejected(self, tmp_path):
        path = self.write(tmp_path, "foo -> bar\nfoo -> baz\n")
        with pytest.raises(ValueError, match="twice"):
            load_dictionary(path)

    def test_empty_file_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="no entries"):
            load_dictionary(self.write(tmp_path, "# nothing\n"))

    def test_missing_file_raises_oserror(self, tmp_path):
        with pytest.raises(OSError):
            load_dictionary(tmp_path / "nope.txt")

    def test_cli_uses_the_file(self, tmp_path, capsys):
        target = tmp_path / "a.md"
        target.write_text("a load-bearing wall\n")
        terms = self.write(tmp_path, "wall -> partition\n")
        assert main(["--dict", str(terms), "--replace", str(tmp_path)]) == 0
        assert target.read_text() == "a load-bearing partition\n"

    def test_cli_list_prints_the_file(self, tmp_path, capsys):
        terms = self.write(tmp_path, "foo -> bar\n")
        assert main(["--dict", str(terms), "--list"]) == 0
        assert capsys.readouterr().out == "foo -> bar\n"

    def test_list_without_dict_prints_the_builtin(self, capsys):
        assert main(["--list"]) == 0
        assert capsys.readouterr().out == "load-bearing -> structural\n"

    def test_cli_reports_a_bad_file(self, tmp_path, capsys):
        terms = self.write(tmp_path, "broken\n")
        assert main(["--dict", str(terms), str(tmp_path)]) == 2
        assert "expected" in capsys.readouterr().err

    def test_cli_reports_a_missing_file(self, tmp_path, capsys):
        assert main(["--dict", str(tmp_path / "nope.txt"), str(tmp_path)]) == 2
        assert capsys.readouterr().err.startswith("wordsub:")


class TestValidation:
    def test_case_colliding_terms_rejected(self):
        with pytest.raises(ValueError, match="differ only in case"):
            WordSub(substitutions={"foo": "a", "FOO": "b"})

    def test_case_colliding_terms_allowed_when_case_sensitive(self):
        ws = WordSub(substitutions={"foo": "a", "FOO": "b"}, case_sensitive=True)
        assert ws.replace_text("foo FOO") == ("a b", 2)

    def test_distinct_terms_still_accepted(self):
        assert WordSub(substitutions={"foo": "a", "bar": "b"})

    @pytest.mark.parametrize("value", [0, -1])
    def test_max_bytes_below_one_rejected(self, value):
        with pytest.raises(ValueError, match="max_bytes"):
            WordSub(max_bytes=value)

    @pytest.mark.parametrize("value", ["0", "-1"])
    def test_cli_max_bytes_below_one_rejected(self, value):
        with pytest.raises(SystemExit) as exc:
            main(["--max-bytes", value, "."])
        assert exc.value.code == 2

    @pytest.mark.parametrize("given", ["", " ", "*", "."])
    def test_empty_extension_rejected(self, given):
        with pytest.raises(ValueError, match="empty"):
            normalize_suffix(given)

    def test_cli_empty_extension_exits_two(self, tree, capsys):
        assert main(["--ext", "", str(tree)]) == 2
        assert "empty" in capsys.readouterr().err

    def test_compound_extension_matches(self, tmp_path):
        (tmp_path / "x.tar.gz").write_text("load-bearing\n")
        (tmp_path / "y.gz").write_text("load-bearing\n")
        ws = WordSub(suffixes=["tar.gz"])
        assert [p.name for p in ws.collect_tree(tmp_path)] == ["x.tar.gz"]

    def test_compound_extension_via_cli(self, tmp_path, capsys):
        (tmp_path / "x.tar.gz").write_text("load-bearing\n")
        assert main(["--ext", "tar.gz", str(tmp_path)]) == 1

    def test_simple_extension_unaffected(self, tree):
        names = {p.name for p in WordSub().collect_tree(tree)}
        assert names == {"a.md", "b.md"}


class TestBinaryDetection:
    def test_nul_past_the_first_block_is_still_binary(self, tmp_path):
        path = tmp_path / "late.md"
        path.write_bytes(b"load-bearing\n" + b"a" * 9000 + b"\0" + b"tail\n")
        assert WordSub().read_text(path) == (None, None)

    def test_such_a_file_is_never_rewritten(self, tmp_path):
        path = tmp_path / "late.md"
        body = b"load-bearing\n" + b"a" * 9000 + b"\0" + b"load-bearing\n"
        path.write_bytes(body)
        assert WordSub().replace_file(path) is None
        assert path.read_bytes() == body

    def test_line_endings_survive_the_byte_read(self, tmp_path):
        path = tmp_path / "crlf.md"
        path.write_bytes(b"a load-bearing wall\r\n")
        WordSub().replace_file(path)
        assert path.read_bytes() == b"a structural wall\r\n"


class TestProgressEnabledIsResolvedOnce:
    def test_isatty_consulted_once(self):
        class Counting(io.StringIO):
            calls = 0

            def isatty(self):
                type(self).calls += 1
                return False

        stream = Counting()
        progress = DirectoryProgress(stream=stream)
        for _ in range(5):
            progress.tick()
        assert progress.enabled is False
        assert Counting.calls == 1

    def test_forced_value_still_wins(self):
        progress = DirectoryProgress(stream=io.StringIO(), enabled=True)
        assert progress.enabled is True
