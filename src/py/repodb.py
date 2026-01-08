#!/usr/bin/env python3
"""Manage a database of git repository URLs.

This module can be invoked as 'repodb' or 'listrepos' for convenience.
When invoked as 'listrepos', it defaults to listing projects.
"""

import dbm
import os
import sys
from pathlib import Path
from typing import Optional


class GitRepoDB:
    """Database for managing git repository URLs."""

    DB_PATH = Path(__file__).parent / 'urls.db'
    SRC_DIR = Path('~/src').expanduser()

    def __init__(self, src_dir: Optional[str | Path] = None, db_path: Optional[str | Path] = None):
        """Initialize GitRepoDB.

        Args:
            src_dir: Directory containing git repositories (default: ~/src)
            db_path: Path to database file (default: src/urls.db)
        """
        self.src_dir = Path(src_dir) if src_dir else self.SRC_DIR
        self.db_path = Path(db_path) if db_path else self.DB_PATH

    @property
    def urls(self) -> list[str]:
        """Get all URLs from the database."""
        try:
            with dbm.open(str(self.db_path), 'r') as db:
                return sorted(url.decode() for url in db.values())
        except Exception:
            return []

    @property
    def projects(self) -> list[str]:
        """Get all project names from the database."""
        try:
            with dbm.open(str(self.db_path), 'r') as db:
                return sorted(name.decode() for name in db.keys())
        except Exception:
            return []

    def collect(self):
        """Collect repos from the default source directory."""
        self.store_from_dir(self.src_dir)

    def store_from_dir(self, directory: str | Path) -> None:
        """Store repository URLs from a directory.

        Args:
            directory: Directory to scan for git repositories
        """
        _urls = self.get_from_dir(directory)
        self.store(_urls)

    def store_from_string(self, urlstr: str) -> None:
        """Store repository URLs from a string.

        Args:
            urlstr: Newline-separated list of URLs
        """
        _urls = [Path(p) for p in urlstr.splitlines()]
        self.store(_urls)

    def get_from_dir(self, directory: str | Path) -> list[Path]:
        """Get git remote URLs from all repos in a directory.

        Uses subprocess to call git config for robust parsing.

        Args:
            directory: Directory to scan

        Returns:
            List of repository URLs
        """
        import subprocess

        src_dir = Path(directory)
        src_urls = set()

        if not src_dir.exists():
            print(f"Warning: Directory {src_dir} does not exist", file=sys.stderr)
            return []

        for p in src_dir.iterdir():
            if p.is_dir() and (p / '.git').exists():
                try:
                    # Use git config to get remote URL properly
                    result = subprocess.run(
                        ['git', '-C', str(p), 'config', '--get', 'remote.origin.url'],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    url = result.stdout.strip()
                    if url:
                        src_urls.add(Path(url))
                except subprocess.CalledProcessError:
                    # No remote.origin.url configured
                    pass
                except Exception as e:
                    print(f"Warning: Could not get URL for {p.name}: {e}", file=sys.stderr)

        return sorted(src_urls)

    def store(self, urls: list[Path]) -> None:
        """Store URLs in the database.

        Args:
            urls: List of repository URLs to store
        """
        with dbm.open(str(self.db_path), 'c') as db:
            for url in urls:
                if url.stem in db:
                    print('skipping:', url.stem)
                    continue
                print('storing:', url.stem)
                db[url.stem] = str(url)

    def dump(self, to_path: str = 'urls.txt'):
        """Dump all URLs to a file.

        Args:
            to_path: Output file path
        """
        with open(to_path, 'w') as f:
            f.write("\n".join(self.urls))


def list_repos():
    """List all repositories (listrepos compatibility mode)."""
    db = GitRepoDB()

    try:
        projects = db.projects
        if projects:
            for project in projects:
                print(project)
        else:
            print("No projects found. Run 'repodb --collect' to collect repositories first.", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Run 'repodb --collect' to collect repositories first.", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    import argparse

    # Detect if invoked as listrepos
    invoked_as = Path(sys.argv[0]).name
    is_listrepos = invoked_as in ['listrepos', 'listrepos.py']

    if is_listrepos:
        # Simple listrepos mode - just list projects
        list_repos()
    else:
        # Full repodb mode with argparse
        parser = argparse.ArgumentParser(
            prog='repodb',
            description='Manage a database of git repository URLs',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  # Collect repos from default ~/src directory
  repodb --collect
  repodb  # (same as --collect if no other action specified)

  # Collect from custom directory
  repodb --collect --src-dir /path/to/repos

  # Use custom database path
  repodb --db-path /path/to/db.db --collect

  # List all projects
  repodb --list
  listrepos  # (convenience shortcut)

  # List all URLs
  repodb --list-urls

  # Dump URLs to file
  repodb --dump urls.txt

  # Combine options
  repodb --src-dir ~/projects --list
            """
        )

        parser.add_argument('--src-dir', type=str, default=None,
                          help='Source directory containing git repos (default: ~/src)')
        parser.add_argument('--db-path', type=str, default=None,
                          help='Path to database file (default: src/urls.db)')
        parser.add_argument('--list', '-l', action='store_true',
                          help='List all project names')
        parser.add_argument('--list-urls', '-u', action='store_true',
                          help='List all URLs')
        parser.add_argument('--dump', '-d', type=str, metavar='FILE',
                          help='Dump URLs to file')
        parser.add_argument('--collect', '-c', action='store_true',
                          help='Collect repos from source directory')

        args = parser.parse_args()

        db = GitRepoDB(src_dir=args.src_dir, db_path=args.db_path)

        # Determine action
        if args.list:
            projects = db.projects
            if projects:
                for project in projects:
                    print(project)
            else:
                print("No projects found. Run 'repodb --collect' first.", file=sys.stderr)
                sys.exit(1)
        elif args.list_urls:
            urls = db.urls
            if urls:
                for url in urls:
                    print(url)
            else:
                print("No URLs found. Run 'repodb --collect' first.", file=sys.stderr)
                sys.exit(1)
        elif args.dump:
            db.dump(args.dump)
            print(f"URLs dumped to {args.dump}")
        else:
            # Default action: collect
            db.collect()
            print(f"Collected {len(db.projects)} repositories")
