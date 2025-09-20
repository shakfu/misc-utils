#!/usr/bin/env python3
"""
Script to remove trailing whitespace from files.

Usage:
    python scripts/remove_trailing_whitespace.py [file1] [file2] ...

If no files are specified, processes all files in the current directory recursively.
"""

import argparse
from pathlib import Path
from typing import TypeAlias

# types aliases
PathLike: TypeAlias = Path | str


class FileCleaner:
    VALID_EXTENSIONS: set[str] = {
        ".py", ".pyx", ".pxd", ".pxi",
        ".c", ".h", ".cpp", ".hpp",
        ".rs", ".go", "java", ".js", ".ts",
    }
    def __init__(self, file_path: PathLike, dry_run: bool= False):
        self.file_path = Path(file_path)
        self.dry_run = dry_run
        self.n_lines_cleaned = 0

    def clean(self):
        """main cleaning method"""
        if self.can_clean():
            print(f"cleaning: {self.file_path}")
            self.remove_trailing_whitespace()

    def remove_trailing_whitespace(self) -> bool:
        """Remove trailing whitespace from a file."""
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            modified = False
            cleaned_lines = []

            for line in lines:
                # Remove trailing whitespace but preserve the line ending
                if line.endswith('\n'):
                    cleaned_line = line.rstrip() + '\n'
                else:
                    cleaned_line = line.rstrip()

                if cleaned_line != line:
                    self.n_lines_cleaned += 1
                    modified = True

                cleaned_lines.append(cleaned_line)

            if modified:
                prefix = ""
                if not self.dry_run:
                    with open(self.file_path, 'w', encoding='utf-8') as f:
                        f.writelines(cleaned_lines)
                else:
                    prefix = "DRY-RUN-"
                print(f"{prefix}Cleaned: {self.n_lines_cleaned} lines in {self.file_path}")
                return True
            else:
                return False

        except IOError as e:
            print(f"Error processing {self.file_path}: {e}")
            return False

    def can_clean(self) -> bool:
        """Check if file should be processed (text files only)."""

        if not self.file_path.is_file():
            return False

        # Skip hidden files and directories
        if any(part.startswith('.') for part in self.file_path.parts):
            return False

        # Skip build directories
        skip_dirs = {'build', '__pycache__', '.git', 'node_modules', 'venv', '.venv'}
        if any(part in skip_dirs for part in self.file_path.parts):
            return False

        if self.file_path.suffix.lower() in self.VALID_EXTENSIONS:
            return True

        return False


def main():
    parser = argparse.ArgumentParser(description='Remove trailing whitespace from files')
    parser.add_argument('paths', default=".", nargs='*', help='Files/Dirs to process (default: recursive)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without modifying files')

    args = parser.parse_args()

    files_to_process = []
    if args.paths:
        for path in args.paths:
            p = Path(path)
            if p.exists():
                if p.is_file():
                    files_to_process.append(p)
                if p.is_dir():
                    for f in p.iterdir():
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
            cleaner = FileCleaner(file_path, dry_run=args.dry_run)
            cleaner.clean()
        except IOError as e:
            print(f"Error processing {file_path}: {e}")

if __name__ == '__main__':
    main()