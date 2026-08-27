#!/usr/bin/env python3
"""
wordsub - Scan a file tree for a fixed vocabulary of words and optionally
substitute the preferred alternatives.

The vocabulary is the SUBSTITUTIONS mapping below, or a file given with
--dict: each key is a term to flag, each value is what it should become. A
dictionary file holds one 'term -> substitute' per line, ignores blank lines
and # comments, and rejects a term given twice. Matching is whole-word
(a term never matches inside a longer word) and case-insensitive, so every
spelling of a term is found, and the substitute is recased to match the
spelling it replaces: Load-bearing becomes Structural, LOAD-BEARING becomes
STRUCTURAL. --case-sensitive narrows both matching and rewriting to the exact
dictionary spelling. --exact-fix decouples the two: every casing is reported,
but only the exact dictionary spelling is rewritten and the rest are marked
[manual] for a human to judge.

Only .md files are scanned, since the dictionary is a prose vocabulary:
a 240k-file tree of source repositories holds 2,917 of them, and the
rest are never opened. --ext adds or replaces extensions and --all-files
drops the restriction. A file named directly on the command line is
scanned whatever its extension.

Dot-prefixed files and directories are pruned by default, so .git, .venv
and similar trees are never read or rewritten; --hidden includes them.
Build output and dependency trees are pruned by name as well (see
DEFAULT_EXCLUDES), and --exclude adds more names.

Scan mode is the default; --replace rewrites files in place.

CLI usage:
    usage: wordsub [-h] [--replace] [--case-sensitive] [--exact-fix]
                   [--no-preserve-case] [--ext EXT] [--all-files] [--hidden]
                   [--exclude NAME] [--dict FILE] [--max-bytes N] [--list]
                   [--quiet] [--no-progress] [path]

    positional arguments:
      path                  Directory to scan recursively, or a single file
                            (default: current directory)

    options:
      -h, --help            show this help message and exit
      --replace, -r         Rewrite files in place (default: report only)
      --case-sensitive, -c  Match only the exact dictionary spelling
                            (default: any casing)
      --exact-fix           Report every casing but rewrite only the exact
                            dictionary spelling
      --no-preserve-case    Insert the replacement verbatim instead of
                            recasing it to match the text it replaces
      --ext EXT             Extension to scan; repeatable, replaces the
                            default of md
      --all-files           Scan every file regardless of extension
      --hidden              Include dot-prefixed files and directories
      --exclude NAME        Directory name to prune; repeatable
      --dict FILE           Read the term dictionary from FILE
      --max-bytes N         Skip files larger than N bytes (default: 5242880)
      --list                Print the substitution dictionary and exit
      --quiet, -q           Print only the summary line
      --no-progress         Do not report the directory being walked

    Matches print as each file is read, not after the walk finishes, so a
    large tree reports its first hit immediately. The directory being read is
    reported on a single rewritten stderr line carrying a directory and file
    count, erased before each match line and off automatically when stderr is
    not a terminal, so piped output is unaffected. --quiet suppresses the
    match lines, not the progress line.

    Exit status: 0 if no matches remain after the run, 1 if any do, 2 on a
    usage, path or dictionary error. Scan mode always exits 1 on a match, and --replace
    exits 1 only when --exact-fix left something for manual review. Either
    mode is therefore usable as a CI check.

    A path that cannot be read, or a file that cannot be written, is named
    on stderr and forces exit 2, in either mode. Otherwise a --replace run
    that rewrote nothing because every file was read-only would report
    success and exit 0.

    Rewrites go through a temporary file in the same directory, moved over
    the original, so an interrupted run leaves the old file rather than a
    truncated one. A file without write permission is refused and reported,
    not renamed over.

Library usage:
    from wordsub import WordSub, SUBSTITUTIONS, load_dictionary

    ws = WordSub()                         # or substitutions=load_dictionary(f)
    results = ws.scan_tree('.')            # collect everything
    changed = ws.replace_tree('.')
    totals = run(ws, Path('.'))            # or stream, printing as it goes
"""

from __future__ import annotations

import argparse
import errno
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator, Mapping, TextIO

# The predefined vocabulary: term -> substitute.
SUBSTITUTIONS: dict[str, str] = {
    "load-bearing": "structural",
}

# Directory names pruned in addition to dot-prefixed ones. These are build
# output and dependency trees, where a rewrite would be discarded or would
# edit third-party source. A virtualenv named .venv is already covered by the
# dot rule; venv and env catch the undotted spellings.
DEFAULT_EXCLUDES: frozenset[str] = frozenset(
    {
        "__pycache__",
        "node_modules",
        "venv",
        "env",
        "build",
        "dist",
    }
)

MAX_FILE_BYTES = 5 * 1024 * 1024

# File extensions scanned unless told otherwise. The dictionary is a prose
# vocabulary, so markdown is where it belongs; widening this to source trees
# would flag identifiers and URLs that happen to contain a term.
DEFAULT_SUFFIXES: frozenset[str] = frozenset({".md"})

# Distinguishes "caller said nothing" from "caller said scan everything".
_UNSET: object = object()


def normalize_suffix(suffix: str) -> str:
    """Return *suffix* as a lowercase dotted extension.

    Accepts md, .md, *.md and MD alike. A compound extension such as tar.gz
    is kept whole; wanted() matches those against the whole file name.

    Raises ValueError for a suffix with nothing left after the dot, which
    would otherwise be accepted and then match no file at all.
    """
    suffix = suffix.strip().lstrip("*")
    if not suffix.startswith("."):
        suffix = "." + suffix
    suffix = suffix.lower()
    if suffix == ".":
        raise ValueError("extension must not be empty")
    return suffix


@dataclass
class Match:
    """A single term occurrence.

    fixable is False for a match that --exact-fix reports but declines to
    rewrite, because its casing differs from the dictionary spelling.
    """

    path: Path
    line_number: int
    column: int
    term: str
    found: str
    replacement: str
    fixable: bool = True


@dataclass
class FileResult:
    """Per-file scan or replace outcome.

    error holds the reason the file could not be rewritten, and is None on
    success. Without it a failed write is indistinguishable from a file that
    needed no change, since both report replaced 0.
    """

    path: Path
    matches: list[Match] = field(default_factory=list)
    replaced: int = 0
    error: str | None = None

    @property
    def count(self) -> int:
        return len(self.matches)

    @property
    def manual(self) -> list[Match]:
        """Matches reported but deliberately not rewritten."""
        return [m for m in self.matches if not m.fixable]


def load_dictionary(path: Path | str) -> dict[str, str]:
    """Read a term dictionary from *path*.

    One entry per line, ``term -> substitute``. Blank lines and lines whose
    first non-space character is # are ignored. A term may contain spaces;
    matching is whole-word either way.

    Raises ValueError, naming the line, for a line without a separator, for
    an empty term or substitute, and for a term given twice. OSError from
    the read is left to the caller.
    """
    entries: dict[str, str] = {}
    text = Path(path).read_text(encoding="utf-8")
    for number, raw in enumerate(split_lines(text), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        term, separator, replacement = line.partition("->")
        term, replacement = term.strip(), replacement.strip()
        if not separator or not term or not replacement:
            raise ValueError(f"{path}:{number}: expected 'term -> substitute'")
        if term in entries:
            raise ValueError(f"{path}:{number}: {term!r} given twice")
        entries[term] = replacement
    if not entries:
        raise ValueError(f"{path}: no entries")
    return entries


def split_lines(text: str) -> list[str]:
    """Split *text* into lines on newlines alone, stripping a trailing CR.

    str.splitlines also breaks on form feed, U+0085, U+2028 and U+2029. A
    single one of those in a file shifts every later line number away from
    what an editor, grep and git report for it, which breaks the
    path:line:column output the tool exists to produce. A lone CR is not a
    line break here either, matching grep and git rather than splitlines.
    """
    return [
        line[:-1] if line.endswith("\r") else line for line in text.split("\n")
    ]


def recase(found: str, replacement: str) -> str:
    """Recase *replacement* to match the casing style of *found*.

    Handles the four styles that occur in prose: all lower, all upper, title
    case over every segment ("Load-Bearing"), and a leading capital
    ("Load-bearing", and "Load-BEARING" with it). Internal casing the tool
    cannot reproduce is normalised, but the leading capital is kept, since
    dropping it rewrites the first word of a sentence in lower case.

    Text that starts lower case without being all lower ("lOAD-BEARING") is
    returned verbatim: there is no casing there to carry over.
    """
    if found.islower():
        return replacement
    if found.isupper():
        return replacement.upper()
    if found == found.title():
        return replacement.title()
    if found[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


class DirectoryProgress:
    """Transient one-line report of the directory being walked.

    Written to stderr and rewritten in place with a carriage return, so it
    never enters the match listing on stdout and leaves no trace once
    cleared. Disabled automatically when the stream is not a terminal.

    Args:
        stream: Where to write. Defaults to sys.stderr, resolved per call.
        enabled: Force on or off. Default None: on only for a terminal.
        width: Line width to truncate to. Default None: ask the terminal.
        every: Redraw after this many files within one directory. A single
            directory can hold tens of thousands of files, so a line that
            only moved per directory would still look stalled.
    """

    def __init__(
        self,
        stream: TextIO | None = None,
        enabled: bool | None = None,
        width: int | None = None,
        every: int = 200,
    ):
        self._stream = stream
        self._enabled = enabled
        self.width = width
        self.every = every
        self.count = 0
        self.files = 0
        self.directory = Path(".")
        self._last_len = 0

    @property
    def stream(self) -> TextIO:
        return sys.stderr if self._stream is None else self._stream

    @property
    def enabled(self) -> bool:
        """Whether to draw at all, resolved once and remembered.

        tick() consults this per file, and a terminal does not stop being
        one mid-walk, so the isatty call is made on first use rather than
        once per candidate file.
        """
        if self._enabled is None:
            try:
                self._enabled = self.stream.isatty()
            except (AttributeError, ValueError):
                self._enabled = False
        return self._enabled

    def _fit(self, prefix: str, path: str) -> str:
        """Fit prefix + path to the line width.

        Only the path is truncated, and from the left, so the counter stays
        visible and the deepest directory names survive.
        """
        width = self.width
        if width is None:
            width = shutil.get_terminal_size(fallback=(80, 24)).columns
        room = width - 1 - len(prefix)
        if len(path) <= room:
            return prefix + path
        if room < 8:
            return (prefix + path)[: max(0, width - 1)]
        return prefix + "..." + path[-(room - 3) :]

    def _draw(self) -> None:
        dirs = f"{self.count} dir" + ("" if self.count == 1 else "s")
        files = f"{self.files} file" + ("" if self.files == 1 else "s")
        prefix = f"scanning [{dirs}, {files}] "
        line = self._fit(prefix, str(self.directory))
        pad = " " * max(0, self._last_len - len(line))
        self.stream.write(f"\r{line}{pad}")
        self.stream.flush()
        self._last_len = len(line)

    def __call__(self, directory: Path) -> None:
        """Report *directory* as the one now being walked."""
        if not self.enabled:
            return
        self.count += 1
        self.directory = directory
        self._draw()

    def tick(self) -> None:
        """Count one file read, redrawing every *every* files."""
        if not self.enabled:
            return
        self.files += 1
        if self.files % self.every == 0:
            self._draw()

    def clear(self) -> None:
        """Erase the progress line, leaving the cursor at column zero."""
        if not self.enabled or not self._last_len:
            return
        self.stream.write("\r" + " " * self._last_len + "\r")
        self.stream.flush()
        self._last_len = 0


class WordSub:
    """Whole-word scanner and substituter over a fixed vocabulary.

    Args:
        substitutions: Mapping of term to substitute. Defaults to the
            module-level SUBSTITUTIONS.
        case_sensitive: If True, terms match only in the spelling given in
            the dictionary. Default False: any casing matches.
        preserve_case: If True (the default), the substitute is recased to
            match the text it replaces. Ignored when case_sensitive is True,
            since an exact match needs no recasing.
        exact_fix: If True, matching stays case-insensitive but only the
            exact dictionary spelling is rewritten; other casings are
            reported with fixable False. Ignored when case_sensitive is
            True, where every match is exact by construction.
        include_hidden: If True, dot-prefixed files and directories are
            walked instead of pruned.
        excludes: Directory names to prune, in addition to dot-prefixed
            ones. Defaults to DEFAULT_EXCLUDES.
        suffixes: File extensions to scan. Defaults to DEFAULT_SUFFIXES
            (.md). Pass None to scan every file regardless of extension. A
            path named directly as the root is scanned whatever its
            extension.
        max_bytes: Files larger than this are skipped.
    """

    def __init__(
        self,
        substitutions: Mapping[str, str] | None = None,
        case_sensitive: bool = False,
        preserve_case: bool = True,
        exact_fix: bool = False,
        include_hidden: bool = False,
        excludes: Iterable[str] | None = None,
        suffixes: Iterable[str] | None | object = _UNSET,
        max_bytes: int = MAX_FILE_BYTES,
    ):
        self.substitutions = dict(
            SUBSTITUTIONS if substitutions is None else substitutions
        )
        if not self.substitutions:
            raise ValueError("substitutions must not be empty")
        if not case_sensitive:
            folded: dict[str, str] = {}
            for term in self.substitutions:
                clash = folded.setdefault(term.lower(), term)
                if clash != term:
                    raise ValueError(
                        f"terms {clash!r} and {term!r} differ only in case, "
                        "so only one of them could ever be applied"
                    )
        if max_bytes < 1:
            raise ValueError("max_bytes must be at least 1")
        self.case_sensitive = case_sensitive
        self.preserve_case = preserve_case and not case_sensitive
        self.exact_fix = exact_fix and not case_sensitive
        self.include_hidden = include_hidden
        self.excludes = frozenset(
            DEFAULT_EXCLUDES if excludes is None else excludes
        )
        if suffixes is _UNSET:
            self.suffixes: frozenset[str] | None = DEFAULT_SUFFIXES
        elif suffixes is None:
            self.suffixes = None
        else:
            self.suffixes = frozenset(
                normalize_suffix(x) for x in suffixes  # type: ignore[union-attr]
            )
        self._compound = frozenset(
            s for s in (self.suffixes or ()) if s.count(".") > 1
        )
        self.max_bytes = max_bytes
        self.pattern = self._compile()
        self._lookup = {
            (k if case_sensitive else k.lower()): v
            for k, v in self.substitutions.items()
        }

    def _compile(self) -> re.Pattern:
        """Build one alternation over all terms, longest first.

        Longest-first ordering makes an overlapping term win over its own
        prefix. Lookarounds are used instead of \\b so that terms starting or
        ending in punctuation still get whole-word treatment.
        """
        terms = sorted(self.substitutions, key=len, reverse=True)
        alternation = "|".join(re.escape(t) for t in terms)
        flags = 0 if self.case_sensitive else re.IGNORECASE
        return re.compile(rf"(?<!\w)(?:{alternation})(?!\w)", flags)

    def is_fixable(self, found: str) -> bool:
        """True if matched text *found* should be rewritten.

        Always True unless exact_fix is set, in which case only text
        matching a dictionary key verbatim qualifies.
        """
        return not self.exact_fix or found in self.substitutions

    def substitute_for(self, found: str) -> str:
        """Return the substitute for matched text *found*, recased if enabled."""
        key = found if self.case_sensitive else found.lower()
        replacement = self._lookup[key]
        if self.preserve_case:
            return recase(found, replacement)
        return replacement

    # -- traversal ---------------------------------------------------------

    def is_hidden(self, name: str) -> bool:
        """True if *name* is dot-prefixed (and hidden paths are not included)."""
        return not self.include_hidden and name.startswith(".")

    def wanted(self, path: Path) -> bool:
        """True if *path* has one of the scanned extensions.

        The common case is a single lookup on Path.suffix, which is what
        keeps a walk over a large tree cheap. A compound extension such as
        .tar.gz is not a Path.suffix at all, so those - and only those - are
        matched against the whole file name.
        """
        if self.suffixes is None:
            return True
        if path.suffix.lower() in self.suffixes:
            return True
        if not self._compound:
            return False
        name = path.name.lower()
        return any(name.endswith(s) for s in self._compound)

    def iter_tree(
        self,
        root: Path | str = ".",
        progress: Callable[[Path], None] | None = None,
        on_error: Callable[[OSError], None] | None = None,
    ) -> Iterator[Path]:
        """Yield candidate files under *root* in directory order.

        Only files whose extension is in suffixes are yielded, which is what
        keeps a walk over a tree of source repositories cheap: the other
        files are never opened. Prunes dot-prefixed directories (.git among
        them) and any name in excludes. Symlinks are skipped, directories
        and files alike, so a tree is never rewritten twice through one.

        A *root* that is itself a file is yielded alone, whatever its
        extension, and a root that is a symlink is followed to its target,
        since naming a path is an explicit request. Both are deliberate: the
        filters exist to keep a walk from wandering, not to overrule a path
        the caller typed.

        progress, if given, is called once per directory entered, before its
        files are yielded, so a caller can show where a long walk has got to.
        Directories holding no candidate files are reported too, since those
        are exactly the stretches where a walk looks stalled.

        on_error, if given, is called with the OSError for each directory
        that could not be read; that directory is then skipped. Without it
        an unreadable directory is skipped silently and the walk reports on
        whatever subset happened to be readable.
        """
        root = Path(root)
        if root.is_file():
            yield root
            return

        for dirpath, dirnames, filenames in os.walk(root, onerror=on_error):
            dirnames[:] = sorted(
                d
                for d in dirnames
                if not self.is_hidden(d) and d not in self.excludes
            )
            if progress is not None:
                progress(Path(dirpath))
            for name in sorted(filenames):
                if self.is_hidden(name):
                    continue
                path = Path(dirpath) / name
                if not self.wanted(path):
                    continue
                if path.is_symlink() or not path.is_file():
                    continue
                yield path

    def collect_tree(self, root: Path | str = ".") -> list[Path]:
        """Return every candidate file under *root* as a list."""
        return list(self.iter_tree(root))

    def read_text(self, path: Path) -> tuple[str | None, str | None]:
        """Read *path* as UTF-8 text preserving line endings.

        Returns (text, None) on success, (None, None) for a file skipped by
        policy - too large, binary, or not UTF-8 - and (None, reason) for a
        file the operating system refused to read. The two are separated
        because a skip is a decision and a refusal is a failure the caller
        has to report.

        The whole file is checked for a NUL byte, not a leading sample, so a
        binary file is never rewritten on the strength of a clean opening.
        max_bytes bounds what is held in memory, and decoding the bytes
        rather than opening in text mode preserves line endings verbatim.
        """
        try:
            if path.stat().st_size > self.max_bytes:
                return None, None
            data = path.read_bytes()
        except OSError as exc:
            return None, exc.strerror or str(exc)
        if b"\0" in data:
            return None, None
        try:
            return data.decode("utf-8"), None
        except UnicodeDecodeError:
            return None, None

    # -- scanning ----------------------------------------------------------

    def scan_text(self, text: str, path: Path | str = "") -> list[Match]:
        """Return every term occurrence in *text*, in reading order."""
        path = Path(path)
        matches: list[Match] = []
        for lineno, line in enumerate(split_lines(text), 1):
            for m in self.pattern.finditer(line):
                found = m.group(0)
                matches.append(
                    Match(
                        path=path,
                        line_number=lineno,
                        column=m.start() + 1,
                        term=found if self.case_sensitive else found.lower(),
                        found=found,
                        replacement=self.substitute_for(found),
                        fixable=self.is_fixable(found),
                    )
                )
        return matches

    def scan_file(self, path: Path | str) -> FileResult | None:
        """Scan one file.

        Returns None if the file has no matches or was skipped by policy. A
        file the operating system refused to read comes back with no matches
        and error set, so the caller can report it rather than count it
        clean.
        """
        path = Path(path)
        text, error = self.read_text(path)
        if error is not None:
            return FileResult(path=path, error=error)
        if text is None:
            return None
        matches = self.scan_text(text, path)
        if not matches:
            return None
        return FileResult(path=path, matches=matches)

    def scan_tree(
        self,
        root: Path | str = ".",
        progress: Callable[[Path], None] | None = None,
        on_error: Callable[[OSError], None] | None = None,
    ) -> list[FileResult]:
        """Scan every candidate file under *root*."""
        results = []
        for path in self.iter_tree(root, progress, on_error):
            result = self.scan_file(path)
            if result is not None:
                results.append(result)
        return results

    # -- replacing ---------------------------------------------------------

    def replace_text(self, text: str) -> tuple[str, int]:
        """Return *text* with every fixable term substituted, plus the count.

        Under exact_fix, occurrences whose casing differs from the dictionary
        spelling are left as they are and not counted.
        """
        count = 0

        def _sub(m: re.Match) -> str:
            nonlocal count
            found = m.group(0)
            if not self.is_fixable(found):
                return found
            count += 1
            return self.substitute_for(found)

        return self.pattern.sub(_sub, text), count

    def write_atomic(self, path: Path, text: str) -> None:
        """Replace *path* with *text* without ever truncating the original.

        The new text is written to a temporary file in the same directory,
        flushed to disk, given the original's mode, and moved over the
        original with os.replace, which is atomic on POSIX and Windows. A
        crash or a full disk therefore leaves either the old file or the new
        one, never a truncated one. The temporary name is dot-prefixed, so a
        concurrent walk prunes it under the same rule that prunes .git.

        Mode is copied; owner and extended attributes are not, since neither
        can be set without privileges the tool does not ask for.

        Raises OSError, which the caller records.
        """
        fd, tmp = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            shutil.copymode(path, tmp)
            os.replace(tmp, path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def replace_file(self, path: Path | str) -> FileResult | None:
        """Rewrite one file in place.

        Returns None if the file held no matches or was skipped by policy. A
        file whose matches are all [manual] under exact_fix comes back with
        replaced 0 so the caller can still report them. The file is only
        written when there is at least one substitution.

        A read that fails, a write that fails, and a target the caller has
        no write permission for all come back with replaced 0 and error set.
        The permission check is explicit because the atomic write renames
        over the target, which POSIX permits on a read-only file whenever
        its directory is writable; without the check the tool would rewrite
        files their owner had marked against exactly that.
        """
        path = Path(path)
        text, error = self.read_text(path)
        if error is not None:
            return FileResult(path=path, error=error)
        if text is None:
            return None
        matches = self.scan_text(text, path)
        if not matches:
            return None
        new_text, count = self.replace_text(text)
        if count == 0 or new_text == text:
            return FileResult(path=path, matches=matches, replaced=0)
        if not os.access(path, os.W_OK):
            return FileResult(
                path=path,
                matches=matches,
                replaced=0,
                error=os.strerror(errno.EACCES),
            )
        try:
            self.write_atomic(path, new_text)
        except OSError as exc:
            return FileResult(
                path=path,
                matches=matches,
                replaced=0,
                error=exc.strerror or str(exc),
            )
        return FileResult(path=path, matches=matches, replaced=count)

    def replace_tree(
        self,
        root: Path | str = ".",
        progress: Callable[[Path], None] | None = None,
        on_error: Callable[[OSError], None] | None = None,
    ) -> list[FileResult]:
        """Rewrite every candidate file under *root* that contains a term."""
        results = []
        for path in self.iter_tree(root, progress, on_error):
            result = self.replace_file(path)
            if result is not None:
                results.append(result)
        return results


def iter_matches(results: Iterable[FileResult]) -> Iterator[Match]:
    """Flatten per-file results into a single stream of matches."""
    for result in results:
        yield from result.matches


def report(results: Iterable[FileResult]) -> None:
    """Print one line per match, marking those left for a human."""
    for m in iter_matches(results):
        mark = "" if m.fixable else " [manual]"
        print(
            f"{m.path}:{m.line_number}:{m.column}: "
            f"{m.found} -> {m.replacement}{mark}",
            flush=True,
        )


@dataclass
class Totals:
    """Running counts over a streamed run."""

    matches: int = 0
    files: int = 0
    replaced: int = 0
    changed: int = 0
    manual: int = 0
    failed: int = 0


def run(
    ws: WordSub,
    root: Path,
    replace: bool = False,
    quiet: bool = False,
    progress: DirectoryProgress | None = None,
) -> Totals:
    """Walk *root*, reporting each file as it is read.

    Results are printed per file rather than collected and dumped at the
    end, so a tree of a quarter of a million files produces its first line
    in under a second instead of after the whole walk. The progress line is
    erased before each print and redrawn by the next directory.

    Directories that cannot be read, and files that cannot be read or
    written, are counted in totals.failed and named on stderr, so they are
    not mistaken for a clean tree. --quiet does not suppress them.
    """
    progress = progress or DirectoryProgress(enabled=False)
    totals = Totals()

    def fail(target: object, reason: str) -> None:
        totals.failed += 1
        progress.clear()
        print(f"wordsub: {target}: {reason}", file=sys.stderr, flush=True)

    def walk_error(exc: OSError) -> None:
        fail(exc.filename, exc.strerror or str(exc))

    for path in ws.iter_tree(root, progress, walk_error):
        progress.tick()
        result = ws.replace_file(path) if replace else ws.scan_file(path)
        if result is None:
            continue
        if result.error is not None:
            fail(result.path, result.error)
        if not result.matches:
            continue
        totals.files += 1
        totals.matches += result.count
        totals.replaced += result.replaced
        totals.changed += 1 if result.replaced else 0
        totals.manual += len(result.manual)
        if not quiet:
            progress.clear()
            report([result])

    progress.clear()
    return totals


def positive_int(value: str) -> int:
    """argparse type for a count that must be at least 1."""
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for wordsub."""
    parser = argparse.ArgumentParser(
        prog="wordsub",
        description=(
            "Scan a directory tree for a dictionary of words and optionally "
            "replace them with their substitutes."
        ),
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Directory to scan recursively, or a single file (default: .)",
    )
    parser.add_argument(
        "--replace",
        "-r",
        action="store_true",
        help="Rewrite files in place (default: report only)",
    )
    parser.add_argument(
        "--case-sensitive",
        "-c",
        action="store_true",
        help="Match only the exact dictionary spelling (default: any casing)",
    )
    parser.add_argument(
        "--exact-fix",
        action="store_true",
        help=(
            "Report every casing but rewrite only the exact dictionary "
            "spelling"
        ),
    )
    parser.add_argument(
        "--no-preserve-case",
        action="store_true",
        help="Insert the replacement verbatim instead of recasing it",
    )
    parser.add_argument(
        "--ext",
        action="append",
        metavar="EXT",
        help="Extension to scan; repeatable, replaces the default of md",
    )
    parser.add_argument(
        "--all-files",
        action="store_true",
        help="Scan every file regardless of extension",
    )
    parser.add_argument(
        "--hidden",
        action="store_true",
        help="Include dot-prefixed files and directories",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        metavar="NAME",
        help="Directory name to prune; repeatable",
    )
    parser.add_argument(
        "--dict",
        dest="dictionary",
        metavar="FILE",
        help=(
            "Read the term dictionary from FILE, one 'term -> substitute' "
            "per line (default: the built-in dictionary)"
        ),
    )
    parser.add_argument(
        "--max-bytes",
        type=positive_int,
        metavar="N",
        default=MAX_FILE_BYTES,
        help=f"Skip files larger than N bytes (default: {MAX_FILE_BYTES})",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the substitution dictionary and exit",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Print only the summary line",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Do not report the directory being walked",
    )

    args = parser.parse_args(argv)

    substitutions = SUBSTITUTIONS
    if args.dictionary:
        try:
            substitutions = load_dictionary(args.dictionary)
        except (OSError, ValueError) as exc:
            print(f"wordsub: {exc}", file=sys.stderr)
            return 2

    if args.list:
        for term, replacement in sorted(substitutions.items()):
            print(f"{term} -> {replacement}")
        return 0

    root = Path(args.path)
    if not root.exists():
        print(f"wordsub: no such path: {root}", file=sys.stderr)
        return 2

    excludes = DEFAULT_EXCLUDES | set(args.exclude or ())
    if args.all_files:
        suffixes = None
    elif args.ext:
        suffixes = args.ext
    else:
        suffixes = DEFAULT_SUFFIXES
    try:
        ws = WordSub(
            substitutions=substitutions,
            case_sensitive=args.case_sensitive,
            preserve_case=not args.no_preserve_case,
            exact_fix=args.exact_fix,
            include_hidden=args.hidden,
            excludes=excludes,
            suffixes=suffixes,
            max_bytes=args.max_bytes,
        )
    except ValueError as exc:
        print(f"wordsub: {exc}", file=sys.stderr)
        return 2

    progress = DirectoryProgress(
        enabled=False if args.no_progress else None
    )

    totals = run(
        ws,
        root,
        replace=args.replace,
        quiet=args.quiet,
        progress=progress,
    )

    if args.replace:
        print(f"replaced {totals.replaced} in {totals.changed} files")
        if totals.manual:
            print(f"{totals.manual} left for manual review")
    else:
        print(f"found {totals.matches} in {totals.files} files")
        if totals.manual:
            print(f"{totals.manual} left for manual review")

    if totals.failed:
        plural = "" if totals.failed == 1 else "s"
        print(
            f"wordsub: {totals.failed} path{plural} could not be processed",
            file=sys.stderr,
        )
        return 2
    if args.replace:
        return 1 if totals.manual else 0
    return 1 if totals.matches else 0


if __name__ == "__main__":
    sys.exit(main())
