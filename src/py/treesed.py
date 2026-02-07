#!/usr/bin/env python3
"""
treesed - Recursive search and replace across file trees.

A tool for searching and optionally replacing text patterns across files,
either recursively through a directory tree or in specific files.

Translated to python from the original perl script by Rick Jansen (1996).

CLI usage:
    usage: treesed [-h] (--tree | --files FILE [FILE ...]) [--case-sensitive]
                   [--regex] [--no-backup] [--quiet]
                   pattern [replacement]

    Recursive search and replace across file trees.

    positional arguments:
      pattern               Search pattern (literal by default, regex with
                            --regex)
      replacement           Replacement string (omit for search-only mode)

    options:
      -h, --help            show this help message and exit
      --tree                Recursively search all files under the current
                            directory
      --files FILE [FILE ...]
                            Specific files to process
      --case-sensitive, -c  Case-sensitive matching (default: case-insensitive)
      --regex, -x           Treat pattern as a regular expression (default:
                            literal)
      --no-backup           Skip creating backup files when replacing
      --quiet, -q           Suppress progress output (headers and dots)

Library usage:
    from treesed import TreeSed

    ts = TreeSed()
    files = TreeSed.collect_tree('.')
    results = ts.search('needle', files)
    replacements = ts.replace('old', 'new', files)
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass
class FileMatches:
    """Result of searching a single file for pattern matches."""

    path: Path
    count: int
    line_numbers: list[int] = field(default_factory=list)


@dataclass
class FileReplacement:
    """Result of replacing a pattern in a single file."""

    path: Path
    count: int
    backup_path: Path | None = None


class TreeSed:
    """Recursive search and replace engine.

    Args:
        case_sensitive: If True, matching is case-sensitive. Default False
            (matching the original treesed behavior).
        use_regex: If True, treat patterns as regular expressions. Default
            False (patterns are treated as literal strings).
    """

    def __init__(
        self, case_sensitive: bool = False, use_regex: bool = False
    ):
        self.case_sensitive = case_sensitive
        self.use_regex = use_regex

    def compile_pattern(self, pattern: str) -> re.Pattern:
        """Compile a search pattern into a regular expression.

        If use_regex is False, the pattern is escaped for literal matching.
        """
        if not self.use_regex:
            pattern = re.escape(pattern)
        flags = 0 if self.case_sensitive else re.IGNORECASE
        return re.compile(pattern, flags)

    def search_file(
        self, pattern: re.Pattern, path: Path
    ) -> FileMatches | None:
        """Search a single file for pattern matches.

        Returns FileMatches if any matches found, None otherwise.
        Silently skips files that cannot be read.
        """
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except (OSError, IOError):
            return None

        line_numbers = []
        for i, line in enumerate(lines, 1):
            if pattern.search(line):
                line_numbers.append(i)

        if not line_numbers:
            return None

        return FileMatches(
            path=path, count=len(line_numbers), line_numbers=line_numbers
        )

    def search(
        self, pattern: str, files: Iterable[Path | str]
    ) -> list[FileMatches]:
        """Search multiple files for a pattern.

        Args:
            pattern: The search pattern (literal or regex per config).
            files: Iterable of file paths to search.

        Returns:
            List of FileMatches for files containing matches.
        """
        compiled = self.compile_pattern(pattern)
        results = []
        for path in files:
            match = self.search_file(compiled, Path(path))
            if match is not None:
                results.append(match)
        return results

    def replace_file(
        self,
        pattern: re.Pattern,
        replacement: str,
        path: Path,
        backup: bool = True,
    ) -> FileReplacement | None:
        """Replace pattern matches in a single file.

        Reads the file line by line, applies replacements, and optionally
        creates a backup (with PID suffix) before writing changes.

        Returns FileReplacement if any replacements were made, None otherwise.
        """
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                original_lines = f.readlines()
        except (OSError, IOError):
            return None

        # In literal mode, escape backslashes in replacement so re.subn
        # does not interpret sequences like \1 or \n.
        repl = replacement
        if not self.use_regex:
            repl = replacement.replace("\\", "\\\\")

        new_lines = []
        lines_changed = 0
        for line in original_lines:
            new_line, n = pattern.subn(repl, line)
            if n > 0:
                lines_changed += 1
            new_lines.append(new_line)

        if lines_changed == 0:
            return None

        backup_path = None
        if backup:
            backup_path = Path(f"{path}.{os.getpid()}")
            try:
                with open(backup_path, "w", encoding="utf-8") as f:
                    f.writelines(original_lines)
            except (OSError, IOError):
                return None

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except (OSError, IOError):
            if backup_path and backup_path.exists():
                with open(path, "w", encoding="utf-8") as f:
                    f.writelines(original_lines)
            return None

        return FileReplacement(
            path=path, count=lines_changed, backup_path=backup_path
        )

    def replace(
        self,
        pattern: str,
        replacement: str,
        files: Iterable[Path | str],
        backup: bool = True,
    ) -> list[FileReplacement]:
        """Replace a pattern in multiple files.

        Args:
            pattern: The search pattern (literal or regex per config).
            replacement: The replacement string.
            files: Iterable of file paths to process.
            backup: If True, create backup files before modifying.

        Returns:
            List of FileReplacement for files that were modified.
        """
        compiled = self.compile_pattern(pattern)
        results = []
        for path in files:
            result = self.replace_file(
                compiled, replacement, Path(path), backup=backup
            )
            if result is not None:
                results.append(result)
        return results

    @staticmethod
    def collect_tree(root: Path | str = ".") -> list[Path]:
        """Recursively collect all regular files under root.

        Returns a sorted list of Path objects.
        """
        root = Path(root)
        return sorted(p for p in root.rglob("*") if p.is_file())

    @staticmethod
    def collect_files(paths: Iterable[str | Path]) -> list[Path]:
        """Filter an iterable of paths to only include existing regular files."""
        return [Path(p) for p in paths if Path(p).is_file()]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for treesed."""
    parser = argparse.ArgumentParser(
        prog="treesed",
        description="Recursive search and replace across file trees.",
        epilog="Translated to python from the original perl script by Rick Jansen (1996)",
    )
    parser.add_argument(
        "pattern",
        help="Search pattern (literal by default, regex with --regex)",
    )
    parser.add_argument(
        "replacement",
        nargs="?",
        default=None,
        help="Replacement string (omit for search-only mode)",
    )

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--tree",
        action="store_true",
        help="Recursively search all files under the current directory",
    )
    source.add_argument(
        "--files",
        nargs="+",
        metavar="FILE",
        help="Specific files to process",
    )

    parser.add_argument(
        "--case-sensitive",
        "-c",
        action="store_true",
        help="Case-sensitive matching (default: case-insensitive)",
    )
    parser.add_argument(
        "--regex",
        "-x",
        action="store_true",
        help="Treat pattern as a regular expression (default: literal)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating backup files when replacing",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress output (headers and dots)",
    )

    args = parser.parse_args(argv)

    ts = TreeSed(case_sensitive=args.case_sensitive, use_regex=args.regex)

    if args.tree:
        files = TreeSed.collect_tree()
    else:
        files = TreeSed.collect_files(args.files)

    if not files:
        print("No input files", file=sys.stderr)
        return 1

    is_replace = args.replacement is not None
    if not args.quiet:
        print(f"search_pattern: {args.pattern}")
        if is_replace:
            print(f"replacement_pattern: {args.replacement}")
        print(f"\n** {'EDIT' if is_replace else 'Search'} mode\n")

    compiled = ts.compile_pattern(args.pattern)
    col = 0

    for path in files:
        result = ts.search_file(compiled, path)

        if not args.quiet:
            sys.stdout.write(".")
            col += 1
            if col >= 50:
                sys.stdout.write("\n")
                col = 0

        if result:
            if not args.quiet and col > 0:
                sys.stdout.write("\n")
                col = 0
            line_str = " ".join(map(str, result.line_numbers))
            print(
                f"{result.path}: {result.count} matches on lines: {line_str}"
            )

            if is_replace:
                rep = ts.replace_file(
                    compiled,
                    args.replacement,
                    path,
                    backup=not args.no_backup,
                )
                if rep:
                    print(
                        f"Replaced {args.pattern} -> {args.replacement}"
                        f" on {rep.count} lines in {rep.path}"
                    )

    if not args.quiet and col > 0:
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
