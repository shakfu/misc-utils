#!/usr/bin/env python3

import argparse
import sqlite3
from pathlib import Path
from typing import Optional

import webloc


class LinksDB:
    """Database for storing webloc file links."""

    def __init__(self, db_path: Optional[str | Path] = None):
        """
        Initialize the LinksDB.

        Args:
            db_path: Path to the SQLite database file. Defaults to 'links.db' in current directory.
        """
        self.db_path = Path(db_path) if db_path else Path.cwd() / 'links.db'
        self._init_db()

    def _init_db(self):
        """Initialize the database table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS links (
                    name TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    file_path TEXT NOT NULL
                )
            """)
            conn.commit()

    def store_from_dir(self, directory: str | Path, overwrite: bool = False) -> None:
        """
        Recursively scan directory for .webloc files and store them in the database.

        Args:
            directory: Directory to scan for .webloc files
            overwrite: If True, overwrite existing entries. If False, skip existing entries.
        """
        directory = Path(directory)
        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")

        webloc_files = list(directory.rglob("*.webloc"))
        print(f"Found {len(webloc_files)} .webloc file(s)")

        stored_count = 0
        skipped_count = 0

        with sqlite3.connect(self.db_path) as conn:
            for webloc_file in webloc_files:
                try:
                    url = webloc.read(str(webloc_file))
                    name = webloc_file.stem

                    # Check if entry already exists
                    cursor = conn.execute(
                        "SELECT name FROM links WHERE name = ?",
                        (name,)
                    )
                    exists = cursor.fetchone() is not None

                    if exists and not overwrite:
                        skipped_count += 1
                        continue

                    if exists and overwrite:
                        conn.execute(
                            "UPDATE links SET url = ?, file_path = ? WHERE name = ?",
                            (url, str(webloc_file), name)
                        )
                        print(f"updating: {name} -> {url}")
                    else:
                        conn.execute(
                            "INSERT INTO links (name, url, file_path) VALUES (?, ?, ?)",
                            (name, url, str(webloc_file))
                        )
                        print(f"storing: {name} -> {url}")

                    stored_count += 1
                    conn.commit()

                except Exception as e:
                    print(f"Error processing {webloc_file}: {e}")
                    continue

        print(f"\nSummary: {stored_count} stored, {skipped_count} skipped")

    def get_all_links(self) -> list[tuple[str, str, str]]:
        """
        Retrieve all links from the database.

        Returns:
            List of tuples (name, url, file_path)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT name, url, file_path FROM links ORDER BY name")
            return cursor.fetchall()


def main():
    parser = argparse.ArgumentParser(
        description="Recursively scan directory for .webloc files and store in SQLite database"
    )
    parser.add_argument(
        "directory",
        type=str,
        help="Directory to scan for .webloc files"
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Path to links.db file (defaults <directory>/_links.db)"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing entries instead of skipping them"
    )

    args = parser.parse_args()

    directory = Path(args.directory)
    if not directory.exists():
        raise FileNotFoundError(f"does not exist: {directory}")
        return

    if not args.db:
        db_path = directory / "_links.db"
        db = LinksDB(db_path=db_path)
    else:
        db = LinksDB(db_path=args.db)
    db.store_from_dir(directory, overwrite=args.overwrite)


if __name__ == '__main__':
    main()
