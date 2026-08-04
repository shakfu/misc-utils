#!/usr/bin/env python3

"""Tests for rm_deadlinks.py"""

import tempfile
from pathlib import Path

from rm_deadlinks import delete_dead_symlinks


class TestDeleteDeadSymlinks:
    """Test delete_dead_symlinks."""

    def test_deletes_broken_symlink(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "missing"
            link = root / "broken"
            link.symlink_to(target)
            assert link.is_symlink()

            delete_dead_symlinks(tmpdir)

            assert not link.is_symlink()
            assert not link.exists(follow_symlinks=False)

    def test_keeps_valid_symlink(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "real.txt"
            target.write_text("ok")
            link = root / "good"
            link.symlink_to(target)

            delete_dead_symlinks(tmpdir)

            assert link.is_symlink()
            assert link.resolve() == target.resolve()

    def test_keeps_regular_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            regular = root / "file.txt"
            regular.write_text("keep")

            delete_dead_symlinks(tmpdir)

            assert regular.read_text() == "keep"

    def test_scans_nested_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            nested = root / "a" / "b"
            nested.mkdir(parents=True)
            link = nested / "broken"
            link.symlink_to(nested / "gone")

            delete_dead_symlinks(tmpdir)

            assert not link.is_symlink()
