#!/usr/bin/env python3
"""
Script to remove trailing whitespace and optionally emojies from files.

usage: clean_file.py [-h] [-e] [-d] [paths ...]

Remove trailing whitespace and emojis from files

positional arguments:
  paths                Files/Dirs to process (default: recursive)

options:
  -h, --help           show this help message and exit
  -e, --remove-emojis  Remove any emojis from the file
  -d, --dry-run        Show what would be changed without modifying files
"""

import argparse
import re
from pathlib import Path
from typing import TypeAlias

# types aliases
PathLike: TypeAlias = Path | str


class FileCleaner:
    VALID_EXTENSIONS: set[str] = {
        ".py",
        ".pyx",
        ".pxd",
        ".pxi",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".rs",
        ".go",
        ".java",
        ".js",
        ".ts",
        ".md",
        ".qmd",
    }

    # Unicode ranges for emoji detection
    EMOJI_PATTERN = re.compile(
        r"[\U0001F600-\U0001F64F]|"  # emoticons
        r"[\U0001F300-\U0001F5FF]|"  # symbols & pictographs
        r"[\U0001F680-\U0001F6FF]|"  # transport & map symbols
        r"[\U0001F1E0-\U0001F1FF]|"  # flags (iOS)
        r"[\U00002702-\U000027B0]|"  # dingbats
        r"[\U000024C2-\U0001F251]"  # enclosed characters
    )

    def __init__(
        self, file_path: PathLike, remove_emojis: bool = False, dry_run: bool = False
    ):
        self.file_path = Path(file_path)
        self.remove_emojis_flag = remove_emojis
        self.dry_run = dry_run
        self.n_lines_cleaned = 0
        self.n_emojis_removed = 0

    def clean(self):
        """main cleaning method"""
        if self.can_clean():
            print(f"cleaning: {self.file_path}")
            self.remove_trailing_whitespace()
            if self.remove_emojis_flag:
                self.remove_emojis()

    def remove_trailing_whitespace(self) -> None:
        """Remove trailing whitespace from a file."""
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            modified = False
            cleaned_lines = []

            for line in lines:
                # Remove trailing whitespace but preserve the line ending
                if line.endswith("\n"):
                    cleaned_line = line.rstrip() + "\n"
                else:
                    cleaned_line = line.rstrip()

                if cleaned_line != line:
                    self.n_lines_cleaned += 1
                    modified = True

                cleaned_lines.append(cleaned_line)

            if modified:
                prefix = ""
                if not self.dry_run:
                    with open(self.file_path, "w", encoding="utf-8") as f:
                        f.writelines(cleaned_lines)
                else:
                    prefix = "DRY-RUN-"
                print(
                    f"{prefix}Cleaned: {self.n_lines_cleaned} lines in {self.file_path}"
                )

        except IOError as e:
            print(f"Error processing {self.file_path}: {e}")

    def remove_emojis(self) -> None:
        """Remove emojis from a file while preserving structure."""
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Count emojis before removal
            emojis_found = self.EMOJI_PATTERN.findall(content)

            if not emojis_found:
                return

            # Remove emojis
            cleaned_content = self.EMOJI_PATTERN.sub("", content)

            # Track removed emojis
            self.n_emojis_removed = len(emojis_found)

            prefix = ""
            if not self.dry_run:
                with open(self.file_path, "w", encoding="utf-8") as f:
                    f.write(cleaned_content)
            else:
                prefix = "DRY-RUN-"

            print(
                f"{prefix}Removed: {self.n_emojis_removed} emojis from {self.file_path}"
            )

        except IOError as e:
            print(f"Error processing {self.file_path}: {e}")

    def can_clean(self) -> bool:
        """Check if file should be processed (text files only)."""

        if not self.file_path.is_file():
            return False

        # Skip hidden files and directories
        if any(part.startswith(".") for part in self.file_path.parts):
            return False

        # Skip build directories
        skip_dirs = {"build", "__pycache__", ".git", "node_modules", "venv", ".venv"}
        if any(part in skip_dirs for part in self.file_path.parts):
            return False

        if self.file_path.suffix.lower() in self.VALID_EXTENSIONS:
            return True

        return False


def main():
    parser = argparse.ArgumentParser(
        description="Remove trailing whitespace and emojis from files"
    )
    parser.add_argument(
        "paths",
        default=".",
        nargs="*",
        help="Files/Dirs to process (default: recursive)",
    )
    parser.add_argument(
        "-e",
        "--remove-emojis",
        action="store_true",
        help="Remove any emojis from the file",
    )
    parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying files",
    )

    args = parser.parse_args()

    files_to_process = []
    if args.paths:
        for path in args.paths:
            p = Path(path)
            if p.exists():
                if p.is_file():
                    files_to_process.append(p)
                elif p.is_dir():
                    # Recursively find all files
                    for f in p.rglob('*'):
                        if f.is_file():
                            files_to_process.append(f)
            else:
                print(f"{p} doesn't exist")
                continue

    for file_path in files_to_process:
        if not file_path.exists():
            print(f"Warning: {file_path} does not exist")
            continue

        if not file_path.is_file():
            continue

        try:
            cleaner = FileCleaner(
                file_path, remove_emojis=args.remove_emojis, dry_run=args.dry_run
            )
            cleaner.clean()
        except IOError as e:
            print(f"Error processing {file_path}: {e}")


if __name__ == "__main__":
    main()
