#!/usr/bin/env python3

"""Converts camelCase to snake_case in a file or directory.

camelCase looks like this:
    firstName
    lastName
    emailAddress
    phoneNumber
    addressLine1

snake_case looks like this:
    first_name
    last_name
    email_address
    phone_number
    address_line_1
"""

import os
import re
from pathlib import Path

class CamelCaseToSnakeCaseConverter:
    """Converts camelCase to snake_case in a file or directory."""

    FILE_EXTENSIONS = ['.c', '.h', '.py', '.md']

    def __init__(self, directory_path: str | Path, file_extensions: list[str] = FILE_EXTENSIONS, recursive: bool = False, dry_run: bool = False):
        self.directory_path = directory_path
        self.file_extensions = file_extensions
        self.recursive = recursive
        self.dry_run = dry_run
        self.regex = re.compile(r'(?<!^)(?=[A-Z])')

    def convert(self, name: str) -> str:
        """Converts a camelCase string to snake_case."""
        return self.regex.sub('_', name).lower()

    def process_file(self,filepath: str | Path):
        """Reads a file, converts camelCase to snake_case, and writes back.
        
        Finds all camelCase words (e.g., 'firstName', 'camelCaseString')
        and replace them with their snake_case equivalent.
        This regex looks for a word starting with a lowercase letter,
        followed by one or more alphanumeric characters,
        and then potentially more words starting with an uppercase letter.
        It's a balance to avoid converting things that aren't intended to be converted.
        
        Args:
            filepath: The path to the file to convert.
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            modified_content = re.sub(r'\b[a-z]+(?:[A-Z][a-z0-9]*)*\b',
                lambda match: self.convert(match.group(0)), content)

            if content != modified_content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(modified_content)
                print(f"Converted '{filepath}'")
            else:
                print(f"No changes needed in '{filepath}'")

        except Exception as e:
            print(f"Error processing file '{filepath}': {e}")

    def process_directory(self):
        """Recursively converts camelCase to snake_case in all files within a directory.
        
        Args:
            directory_path: The path to the directory to convert.
            recursive: Whether to convert files recursively.
            dry_run: Whether to dry run the conversion.
        """
        directory_path = Path(self.directory_path)
        if not directory_path.exists():
            print(f"Directory '{directory_path}' does not exist.")
            return
        
        if not directory_path.is_dir():
            print(f"Directory '{directory_path}' is not a directory.")
            return

        if self.recursive:
            for root, _, files in os.walk(directory_path):
                for filename in files:
                    filepath = os.path.join(root, filename)
                    if self.dry_run:
                        print(f"Would convert '{filepath}'")
                    else:
                        self.process_file(filepath)
        else:
            for f in directory_path.iterdir():
                if f.is_file():
                    if self.dry_run:
                        print(f"Would convert '{f}'")
                    else:
                        self.process_file(f)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Convert camelCase to snake_case in a directory.')
    parser.add_argument('directory', type=str, help='The directory to convert.')
    parser.add_argument('-r', '--recursive', action='store_true', help='Convert files recursively.')
    parser.add_argument('-d', '--dry-run', action='store_true', help='Dry run the conversion.')
    args = parser.parse_args()
    converter = CamelCaseToSnakeCaseConverter(args.directory, args.recursive, args.dry_run)
    converter.process_directory()

