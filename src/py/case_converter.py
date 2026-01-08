#!/usr/bin/env python3

"""Converts between various case formats in files or directories.

Supported case formats:
- camelCase: firstName, lastName
- PascalCase: FirstName, LastName
- snake_case: first_name, last_name
- SCREAMING_SNAKE_CASE: FIRST_NAME, LAST_NAME
- kebab-case: first-name, last-name
- SCREAMING-KEBAB-CASE: FIRST-NAME, LAST-NAME
"""

import os
import re
import fnmatch
from pathlib import Path
from typing import Callable


class CaseConverter:
    """Converts between various case formats in files or directories."""

    FILE_EXTENSIONS = ['.c', '.h', '.py', '.md', '.js', '.ts', '.java', '.cpp', '.hpp']

    # Regex patterns for identifying different case formats
    PAT_CAMEL_CASE = re.compile(r'\b[a-z]+(?:[A-Z][a-z0-9]*)+\b')
    PAT_PASCAL_CASE = re.compile(r'\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+\b')
    PAT_SNAKE_CASE = re.compile(r'\b[a-z]+(?:_[a-z0-9]+)+\b')
    PAT_SCREAMING_SNAKE_CASE = re.compile(r'\b[A-Z]+(?:_[A-Z0-9]+)+\b')
    PAT_KEBAB_CASE = re.compile(r'\b[a-z]+(?:-[a-z0-9]+)+\b')
    PAT_SCREAMING_KEBAB_CASE = re.compile(r'\b[A-Z]+(?:-[A-Z0-9]+)+\b')

    # Conversion helper patterns
    PAT_WORD_BOUNDARY = re.compile(r'(?<!^)(?=[A-Z])')
    PAT_DELIMITER_SPLIT = re.compile(r'[_-]')

    SUPPORTED_FORMATS = [
        'camelCase',
        'PascalCase',
        'snake_case',
        'SCREAMING_SNAKE_CASE',
        'kebab-case',
        'SCREAMING-KEBAB-CASE'
    ]

    def __init__(
        self,
        directory_path: str | Path,
        from_format: str,
        to_format: str,
        file_extensions: list[str] | None = None,
        recursive: bool = False,
        dry_run: bool = False,
        prefix: str = '',
        suffix: str = '',
        glob_pattern: str | None = None,
        word_filter: str | None = None
    ):
        """Initialize the case converter.

        Args:
            directory_path: Path to the directory or file to convert.
            from_format: Source case format (e.g., 'camelCase', 'snake_case').
            to_format: Target case format (e.g., 'PascalCase', 'kebab-case').
            file_extensions: List of file extensions to process. Defaults to FILE_EXTENSIONS.
            recursive: Whether to process files recursively.
            dry_run: Whether to perform a dry run without making changes.
            prefix: Prefix to add to converted words.
            suffix: Suffix to add to converted words.
            glob_pattern: Glob pattern to filter files (e.g., '*test*.py').
            word_filter: Regex pattern to filter which words get converted.
        """
        self.directory_path = Path(directory_path)
        self.from_format = from_format
        self.to_format = to_format
        self.file_extensions = file_extensions or self.FILE_EXTENSIONS
        self.recursive = recursive
        self.dry_run = dry_run
        self.prefix = prefix
        self.suffix = suffix
        self.glob_pattern = glob_pattern
        self.word_filter_pattern = re.compile(word_filter) if word_filter else None

        # Validate formats
        if from_format not in self.SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported from_format: {from_format}. Supported: {self.SUPPORTED_FORMATS}")
        if to_format not in self.SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported to_format: {to_format}. Supported: {self.SUPPORTED_FORMATS}")

        # Get the appropriate regex pattern and conversion function
        self.source_pattern = self._get_pattern_for_format(from_format)
        self.convert_func = self._get_converter(from_format, to_format)

    def _get_pattern_for_format(self, format_name: str) -> re.Pattern:
        """Get the regex pattern for a specific case format."""
        pattern_map = {
            'camelCase': self.PAT_CAMEL_CASE,
            'PascalCase': self.PAT_PASCAL_CASE,
            'snake_case': self.PAT_SNAKE_CASE,
            'SCREAMING_SNAKE_CASE': self.PAT_SCREAMING_SNAKE_CASE,
            'kebab-case': self.PAT_KEBAB_CASE,
            'SCREAMING-KEBAB-CASE': self.PAT_SCREAMING_KEBAB_CASE,
        }
        return pattern_map[format_name]

    def _split_words(self, text: str, from_format: str) -> list[str]:
        """Split a string into words based on its format."""
        if from_format in ['camelCase', 'PascalCase']:
            # Split on uppercase letters
            words = self.PAT_WORD_BOUNDARY.split(text)
            return [w.lower() for w in words if w]
        elif from_format in ['snake_case', 'SCREAMING_SNAKE_CASE']:
            # Split on underscores
            return [w.lower() for w in text.split('_') if w]
        elif from_format in ['kebab-case', 'SCREAMING-KEBAB-CASE']:
            # Split on hyphens
            return [w.lower() for w in text.split('-') if w]
        else:
            return [text.lower()]

    def _join_words(self, words: list[str], to_format: str) -> str:
        """Join words into a string based on the target format."""
        if not words:
            return ''

        # Generate base conversion
        if to_format == 'camelCase':
            result = words[0].lower() + ''.join(w.capitalize() for w in words[1:])
        elif to_format == 'PascalCase':
            result = ''.join(w.capitalize() for w in words)
        elif to_format == 'snake_case':
            result = '_'.join(w.lower() for w in words)
        elif to_format == 'SCREAMING_SNAKE_CASE':
            result = '_'.join(w.upper() for w in words)
        elif to_format == 'kebab-case':
            result = '-'.join(w.lower() for w in words)
        elif to_format == 'SCREAMING-KEBAB-CASE':
            result = '-'.join(w.upper() for w in words)
        else:
            result = ''.join(words)

        # Add prefix and suffix
        return f"{self.prefix}{result}{self.suffix}"

    def _get_converter(self, from_format: str, to_format: str) -> Callable[[str], str]:
        """Get the conversion function for the specified formats."""
        def convert(text: str) -> str:
            words = self._split_words(text, from_format)
            return self._join_words(words, to_format)
        return convert

    def convert(self, name: str) -> str:
        """Convert a string from the source format to the target format.

        Args:
            name: The string to convert.

        Returns:
            The converted string, or the original string if filtered out.
        """
        # Apply word filter if provided
        if self.word_filter_pattern and not self.word_filter_pattern.match(name):
            return name  # Return unchanged if doesn't match filter

        return self.convert_func(name)

    def _matches_glob(self, filepath: Path) -> bool:
        """Check if filepath matches the glob pattern.

        Args:
            filepath: The path to check.

        Returns:
            True if no glob pattern is set or if the path matches the pattern.
        """
        if not self.glob_pattern:
            return True

        # Match against the filename
        if fnmatch.fnmatch(filepath.name, self.glob_pattern):
            return True

        # Also try matching against the full relative path
        try:
            rel_path = filepath.relative_to(self.directory_path)
            if fnmatch.fnmatch(str(rel_path), self.glob_pattern):
                return True
        except ValueError:
            pass

        return False

    def process_file(self, filepath: str | Path):
        """Process a file, converting matching strings from one case to another.

        Args:
            filepath: The path to the file to convert.
        """
        filepath = Path(filepath)

        # Check file extension
        if filepath.suffix not in self.file_extensions:
            return

        # Check glob pattern
        if not self._matches_glob(filepath):
            return

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            # Replace all matches of the source pattern
            modified_content = self.source_pattern.sub(
                lambda match: self.convert(match.group(0)),
                content
            )

            if content != modified_content:
                if self.dry_run:
                    print(f"Would convert '{filepath}'")
                else:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(modified_content)
                    print(f"Converted '{filepath}'")
            else:
                if not self.dry_run:
                    print(f"No changes needed in '{filepath}'")

        except Exception as e:
            print(f"Error processing file '{filepath}': {e}")

    def process_directory(self):
        """Process all files in a directory, converting case formats.

        Processes files based on the recursive flag and file extensions.
        """
        if not self.directory_path.exists():
            print(f"Path '{self.directory_path}' does not exist.")
            return

        # If it's a single file, process it directly
        if self.directory_path.is_file():
            self.process_file(self.directory_path)
            return

        # Otherwise, process directory
        if not self.directory_path.is_dir():
            print(f"Path '{self.directory_path}' is not a directory or file.")
            return

        if self.recursive:
            for root, _, files in os.walk(self.directory_path):
                for filename in files:
                    filepath = os.path.join(root, filename)
                    self.process_file(filepath)
        else:
            for f in self.directory_path.iterdir():
                if f.is_file():
                    self.process_file(f)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Convert between various case formats in files.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert camelCase to snake_case
  case_converter.py --from-camel --to-snake mydir/

  # Convert PascalCase to kebab-case recursively
  case_converter.py --from-pascal --to-kebab -r mydir/

  # Dry run conversion from snake_case to camelCase
  case_converter.py --from-snake --to-camel -d myfile.py

  # Add prefix to all converted words
  case_converter.py --from-camel --to-snake --prefix old_ mydir/

  # Add suffix to all converted words
  case_converter.py --from-snake --to-camel --suffix _new mydir/

  # Only process files matching glob pattern
  case_converter.py --from-camel --to-snake -r --glob '*test*.py' mydir/

  # Only convert words matching regex pattern
  case_converter.py --from-camel --to-snake --word-filter '^get.*' mydir/

  # Combine multiple features
  case_converter.py --from-camel --to-snake --prefix legacy_ \\
    --word-filter '^get.*' --glob 'utils/*.py' -r src/
        """
    )

    # Format specification (mutually exclusive groups for from/to)
    from_group = parser.add_mutually_exclusive_group(required=True)
    from_group.add_argument('--from-camel', action='store_const', const='camelCase', dest='from_format',
                           help='Convert FROM camelCase')
    from_group.add_argument('--from-pascal', action='store_const', const='PascalCase', dest='from_format',
                           help='Convert FROM PascalCase')
    from_group.add_argument('--from-snake', action='store_const', const='snake_case', dest='from_format',
                           help='Convert FROM snake_case')
    from_group.add_argument('--from-screaming-snake', action='store_const', const='SCREAMING_SNAKE_CASE', dest='from_format',
                           help='Convert FROM SCREAMING_SNAKE_CASE')
    from_group.add_argument('--from-kebab', action='store_const', const='kebab-case', dest='from_format',
                           help='Convert FROM kebab-case')
    from_group.add_argument('--from-screaming-kebab', action='store_const', const='SCREAMING-KEBAB-CASE', dest='from_format',
                           help='Convert FROM SCREAMING-KEBAB-CASE')

    to_group = parser.add_mutually_exclusive_group(required=True)
    to_group.add_argument('--to-camel', action='store_const', const='camelCase', dest='to_format',
                         help='Convert TO camelCase')
    to_group.add_argument('--to-pascal', action='store_const', const='PascalCase', dest='to_format',
                         help='Convert TO PascalCase')
    to_group.add_argument('--to-snake', action='store_const', const='snake_case', dest='to_format',
                         help='Convert TO snake_case')
    to_group.add_argument('--to-screaming-snake', action='store_const', const='SCREAMING_SNAKE_CASE', dest='to_format',
                         help='Convert TO SCREAMING_SNAKE_CASE')
    to_group.add_argument('--to-kebab', action='store_const', const='kebab-case', dest='to_format',
                         help='Convert TO kebab-case')
    to_group.add_argument('--to-screaming-kebab', action='store_const', const='SCREAMING-KEBAB-CASE', dest='to_format',
                         help='Convert TO SCREAMING-KEBAB-CASE')

    # Path argument
    parser.add_argument('path', type=str, help='The directory or file to convert.')

    # Optional arguments
    parser.add_argument('-r', '--recursive', action='store_true',
                       help='Convert files recursively.')
    parser.add_argument('-d', '--dry-run', action='store_true',
                       help='Dry run the conversion.')
    parser.add_argument('-e', '--extensions', nargs='+',
                       help='File extensions to process (e.g., .py .js)')
    parser.add_argument('--prefix', type=str, default='',
                       help='Prefix to add to all converted words.')
    parser.add_argument('--suffix', type=str, default='',
                       help='Suffix to add to all converted words.')
    parser.add_argument('--glob', type=str, dest='glob_pattern',
                       help='Glob pattern to filter files (e.g., "*test*.py", "utils/*").')
    parser.add_argument('--word-filter', type=str, dest='word_filter',
                       help='Regex pattern to filter which words get converted (e.g., "^get.*" for getters).')

    args = parser.parse_args()

    try:
        converter = CaseConverter(
            directory_path=args.path,
            from_format=args.from_format,
            to_format=args.to_format,
            file_extensions=args.extensions,
            recursive=args.recursive,
            dry_run=args.dry_run,
            prefix=args.prefix,
            suffix=args.suffix,
            glob_pattern=args.glob_pattern,
            word_filter=args.word_filter
        )
        converter.process_directory()
    except ValueError as e:
        parser.error(str(e))
