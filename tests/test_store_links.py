#!/usr/bin/env python3

"""Tests for store_links.py"""

import plistlib
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from store_links import LinksDB, main


def _write_webloc(path: Path, url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        plistlib.dump({"URL": url}, f)


class TestLinksDB:
    def test_init_creates_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "links.db"
            LinksDB(db_path=db_path)
            assert db_path.exists()
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='links'"
                ).fetchone()
                assert row is not None

    def test_store_from_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_webloc(root / "Alpha.webloc", "https://a.example/")
            nested = root / "sub"
            _write_webloc(nested / "Beta.webloc", "https://b.example/")

            db = LinksDB(db_path=root / "links.db")
            db.store_from_dir(root)

            links = db.get_all_links()
            names = {n for n, _, _ in links}
            assert names == {"Alpha", "Beta"}
            urls = {u for _, u, _ in links}
            assert "https://a.example/" in urls
            assert "https://b.example/" in urls

    def test_store_skips_existing_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_webloc(root / "Same.webloc", "https://first.example/")
            db = LinksDB(db_path=root / "links.db")
            db.store_from_dir(root)

            _write_webloc(root / "Same.webloc", "https://second.example/")
            db.store_from_dir(root)

            links = db.get_all_links()
            assert len(links) == 1
            assert links[0][1] == "https://first.example/"

    def test_store_overwrite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_webloc(root / "Same.webloc", "https://first.example/")
            db = LinksDB(db_path=root / "links.db")
            db.store_from_dir(root)

            _write_webloc(root / "Same.webloc", "https://second.example/")
            db.store_from_dir(root, overwrite=True)

            links = db.get_all_links()
            assert len(links) == 1
            assert links[0][1] == "https://second.example/"

    def test_store_missing_directory_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = LinksDB(db_path=Path(tmpdir) / "links.db")
            with pytest.raises(FileNotFoundError):
                db.store_from_dir(Path(tmpdir) / "missing")

    def test_get_all_links_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = LinksDB(db_path=Path(tmpdir) / "links.db")
            assert db.get_all_links() == []


class TestStoreLinksMain:
    def test_main_uses_default_db_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_webloc(root / "X.webloc", "https://x.example/")

            with patch("sys.argv", ["store_links.py", str(root)]):
                main()

            db_path = root / "_links.db"
            assert db_path.exists()
            db = LinksDB(db_path=db_path)
            assert db.get_all_links()[0][0] == "X"

    def test_main_missing_directory_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "nope"
            with patch("sys.argv", ["store_links.py", str(missing)]):
                with pytest.raises(FileNotFoundError):
                    main()
