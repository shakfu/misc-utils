#!/usr/bin/env python3

"""Tests for listrepos.py"""

import dbm
import tempfile
from pathlib import Path

from listrepos import GitRepoDB


class TestGitRepoDBInit:
    def test_defaults(self):
        db = GitRepoDB()
        assert db.src_dir == Path("~/src").expanduser()
        assert db.db_path.name == "urls.db"

    def test_custom_paths(self):
        db = GitRepoDB(src_dir="/tmp/src", db_path="/tmp/urls.db")
        assert db.src_dir == Path("/tmp/src")
        assert db.db_path == Path("/tmp/urls.db")


class TestGitRepoDBStoreAndRead:
    def test_store_and_read_urls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "urls.db"
            db = GitRepoDB(db_path=db_path)
            db.store([
                Path("https://github.com/user/alpha.git"),
                Path("https://github.com/user/beta.git"),
            ])

            assert db.projects == ["alpha", "beta"]
            # pathlib collapses '//' when Path is stringified
            assert any(u.endswith("github.com/user/alpha.git") for u in db.urls)
            assert any(u.endswith("github.com/user/beta.git") for u in db.urls)

    def test_store_skips_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "urls.db"
            db = GitRepoDB(db_path=db_path)
            db.store([Path("https://github.com/user/alpha.git")])
            db.store([Path("https://github.com/user/alpha.git")])

            with dbm.open(str(db_path), "r") as raw:
                assert len(list(raw.keys())) == 1

    def test_dump_writes_urls_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "urls.db"
            out = Path(tmpdir) / "urls.txt"
            db = GitRepoDB(db_path=db_path)
            db.store([Path("https://github.com/user/alpha.git")])
            db.dump(to_path=str(out))

            assert "github.com/user/alpha.git" in out.read_text()


class TestGitRepoDBGetFromDir:
    def test_reads_url_from_git_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir)
            repo = src / "myrepo"
            (repo / ".git").mkdir(parents=True)
            (repo / ".git" / "config").write_text(
                "[remote \"origin\"]\n"
                "\turl = https://github.com/user/myrepo.git\n"
            )

            db = GitRepoDB(src_dir=src, db_path=src / "urls.db")
            urls = db.get_from_dir(src)

            assert Path("https://github.com/user/myrepo.git") in urls

    def test_skips_dirs_without_git(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir)
            (src / "not-a-repo").mkdir()

            db = GitRepoDB(src_dir=src, db_path=src / "urls.db")
            assert db.get_from_dir(src) == []

    def test_store_from_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir)
            repo = src / "proj"
            (repo / ".git").mkdir(parents=True)
            (repo / ".git" / "config").write_text(
                "url = https://github.com/user/proj.git\n"
            )

            db = GitRepoDB(src_dir=src, db_path=src / "urls.db")
            db.store_from_dir(src)

            assert "proj" in db.projects

    def test_store_from_string(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = GitRepoDB(db_path=Path(tmpdir) / "urls.db")
            db.store_from_string(
                "https://github.com/user/one.git\n"
                "https://github.com/user/two.git\n"
            )
            assert db.projects == ["one", "two"]
