"""Tests for git_status_checker.py"""

import subprocess
import tempfile
from pathlib import Path

import pytest

from git_status_checker import get_git_status, is_git_repo


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test repos."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def init_git_repo(path: Path) -> None:
    """Initialize a git repo at path."""
    path.mkdir(exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path, capture_output=True, check=True
    )


class TestIsGitRepo:
    def test_is_git_repo_true(self, temp_dir):
        repo = temp_dir / "repo"
        init_git_repo(repo)
        assert is_git_repo(repo) is True

    def test_is_git_repo_false(self, temp_dir):
        non_repo = temp_dir / "not_a_repo"
        non_repo.mkdir()
        assert is_git_repo(non_repo) is False


class TestGetGitStatus:
    def test_clean_repo(self, temp_dir):
        repo = temp_dir / "clean_repo"
        init_git_repo(repo)

        # Create and commit a file
        (repo / "file.txt").write_text("content")
        subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True)

        status = get_git_status(repo)
        assert status is not None
        assert status["has_changes"] is False
        assert status["staged"] == []
        assert status["modified"] == []
        assert status["untracked"] == []

    def test_untracked_files(self, temp_dir):
        repo = temp_dir / "untracked_repo"
        init_git_repo(repo)

        # Create an untracked file
        (repo / "untracked.txt").write_text("content")

        status = get_git_status(repo)
        assert status is not None
        assert status["has_changes"] is True
        assert "untracked.txt" in status["untracked"]

    def test_staged_files(self, temp_dir):
        repo = temp_dir / "staged_repo"
        init_git_repo(repo)

        # Create and stage a file
        (repo / "staged.txt").write_text("content")
        subprocess.run(["git", "add", "staged.txt"], cwd=repo, check=True)

        status = get_git_status(repo)
        assert status is not None
        assert status["has_changes"] is True
        assert "staged.txt" in status["staged"]

    def test_modified_files(self, temp_dir):
        repo = temp_dir / "modified_repo"
        init_git_repo(repo)

        # Create, commit, then modify a file
        (repo / "file.txt").write_text("original")
        subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True)
        (repo / "file.txt").write_text("modified")

        status = get_git_status(repo)
        assert status is not None
        assert status["has_changes"] is True
        assert "file.txt" in status["modified"]

    def test_not_a_git_repo(self, temp_dir):
        non_repo = temp_dir / "not_a_repo"
        non_repo.mkdir()

        status = get_git_status(non_repo)
        assert status is None
