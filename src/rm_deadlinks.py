#!/usr/bin/env python3

import os
from pathlib import Path


def delete_dead_symlinks(directory: str):
    """Deletes dead (broken) symbolic links within a specified directory."""
    for root, _, files in os.walk(directory):
        for name in files:
            path = Path(root) / name
            if path.is_symlink():
                if not path.readlink().exists():
                    print(f"Deleting broken symlink: {path}")
                    path.unlink()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(
        description=delete_dead_symlinks.__doc__)
    parser.add_argument("directory",
        help="target folder to scan for dead links")
    args = parser.parse_args()
    delete_dead_symlinks(args.directory)
