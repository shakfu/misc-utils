"""Tests for mover.py."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

import mover


def make_repo(
    root: Path,
    name: str,
    *,
    claude_md: str | None = None,
    claude_dir: dict[str, str] | None = None,
    git: bool = True,
    git_as_file: bool = False,
) -> Path:
    """Create a directory tree that looks like a repository on disk."""
    repo = root / name
    repo.mkdir(parents=True, exist_ok=True)
    if git:
        if git_as_file:
            (repo / ".git").write_text("gitdir: ../.git/modules/thing\n")
        else:
            (repo / ".git").mkdir()
            (repo / ".git" / "config").write_text("[core]\n")
    if claude_md is not None:
        (repo / mover.CLAUDE_FILE).write_text(claude_md)
    if claude_dir is not None:
        target = repo / mover.CLAUDE_DIR
        target.mkdir()
        for rel, content in claude_dir.items():
            path = target / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    return repo


@pytest.fixture(autouse=True)
def isolated_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every test at a root that does not exist.

    Without this a test that exercises the default code path would archive
    the real ~/.claude, or worse, restore over it.
    """
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-such-root"))


def make_root(path: Path, entries: dict[str, str]) -> Path:
    """Create a stand-in for the user-level configuration directory."""
    path.mkdir(parents=True, exist_ok=True)
    for rel, content in entries.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return path


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "src"
    path.mkdir()
    return path


@pytest.fixture
def target(tmp_path: Path) -> Path:
    path = tmp_path / "dst"
    path.mkdir()
    return path


class TestDetection:
    def test_repo_with_both_artifacts_is_found(self, source: Path) -> None:
        make_repo(source, "alpha", claude_md="# alpha", claude_dir={"a.md": "a"})

        repos = mover.find_repos(source)

        assert len(repos) == 1
        assert repos[0].path == source / "alpha"
        assert repos[0].has_file
        assert repos[0].has_dir

    def test_repo_with_only_claude_md_is_found(self, source: Path) -> None:
        make_repo(source, "alpha", claude_md="# alpha")

        (repo,) = mover.find_repos(source)

        assert repo.has_file
        assert not repo.has_dir

    def test_repo_with_only_claude_dir_is_found(self, source: Path) -> None:
        make_repo(source, "alpha", claude_dir={"settings.json": "{}"})

        (repo,) = mover.find_repos(source)

        assert not repo.has_file
        assert repo.has_dir

    def test_repo_without_artifacts_is_ignored(self, source: Path) -> None:
        make_repo(source, "alpha")

        assert mover.find_repos(source) == []

    def test_non_repo_with_artifacts_is_ignored(self, source: Path) -> None:
        make_repo(source, "alpha", claude_md="# alpha", git=False)

        assert mover.find_repos(source) == []

    def test_git_file_counts_as_a_repo(self, source: Path) -> None:
        make_repo(source, "alpha", claude_md="# alpha", git_as_file=True)

        (repo,) = mover.find_repos(source)

        assert repo.path == source / "alpha"

    def test_claude_md_must_be_a_file(self, source: Path) -> None:
        repo = make_repo(source, "alpha")
        (repo / mover.CLAUDE_FILE).mkdir()

        assert mover.find_repos(source) == []

    def test_claude_dir_must_be_a_directory(self, source: Path) -> None:
        repo = make_repo(source, "alpha")
        (repo / mover.CLAUDE_DIR).write_text("not a directory")

        assert mover.find_repos(source) == []

    def test_repos_are_found_at_arbitrary_depth(self, source: Path) -> None:
        make_repo(source / "a" / "b" / "c", "deep", claude_md="# deep")

        (repo,) = mover.find_repos(source)

        assert repo.path == source / "a" / "b" / "c" / "deep"

    def test_source_itself_may_be_the_repo(self, source: Path) -> None:
        make_repo(source.parent, source.name, claude_md="# self")

        (repo,) = mover.find_repos(source)

        assert repo.path == source

    def test_multiple_repos_are_all_found(self, source: Path) -> None:
        make_repo(source, "alpha", claude_md="# alpha")
        make_repo(source / "nest", "beta", claude_dir={"x.md": "x"})

        found = {repo.path.name for repo in mover.find_repos(source)}

        assert found == {"alpha", "beta"}


class TestNesting:
    def test_nested_repos_are_skipped_by_default(self, source: Path) -> None:
        outer = make_repo(source, "outer", claude_md="# outer")
        make_repo(outer / "vendor", "inner", claude_md="# inner")

        found = [repo.path.name for repo in mover.find_repos(source)]

        assert found == ["outer"]

    def test_nested_repos_are_found_with_nested_flag(self, source: Path) -> None:
        outer = make_repo(source, "outer", claude_md="# outer")
        make_repo(outer / "vendor", "inner", claude_md="# inner")

        found = {repo.path.name for repo in mover.find_repos(source, nested=True)}

        assert found == {"outer", "inner"}

    def test_nested_search_under_a_repo_source(self, source: Path) -> None:
        make_repo(source.parent, source.name, claude_md="# self")
        make_repo(source / "vendor", "inner", claude_md="# inner")

        found = {repo.path.name for repo in mover.find_repos(source, nested=True)}

        assert found == {source.name, "inner"}


class TestPruning:
    @pytest.mark.parametrize("pruned", ["node_modules", ".venv", "__pycache__"])
    def test_noisy_directories_are_not_searched(
        self, source: Path, pruned: str
    ) -> None:
        make_repo(source / pruned, "alpha", claude_md="# alpha")

        assert mover.find_repos(source) == []

    def test_git_internals_are_not_searched(self, source: Path) -> None:
        repo = make_repo(source, "alpha", claude_md="# alpha")
        make_repo(repo / ".git" / "modules", "inner", claude_md="# inner")

        found = [r.path.name for r in mover.find_repos(source, nested=True)]

        assert found == ["alpha"]

    def test_symlink_cycle_does_not_hang(self, source: Path) -> None:
        make_repo(source, "alpha", claude_md="# alpha")
        (source / "loop").symlink_to(source, target_is_directory=True)

        found = [repo.path.name for repo in mover.find_repos(source)]

        assert found == ["alpha"]


class TestCopy:
    def test_artifacts_land_in_a_folder_named_after_the_repo(
        self, source: Path, target: Path
    ) -> None:
        make_repo(
            source,
            "alpha",
            claude_md="# alpha",
            claude_dir={"settings.json": "{}", "agents/one.md": "one"},
        )

        mover.copy_artifacts(mover.find_repos(source), target)

        assert (target / "alpha" / mover.CLAUDE_FILE).read_text() == "# alpha"
        assert (target / "alpha" / mover.CLAUDE_DIR / "settings.json").read_text() == "{}"
        assert (
            target / "alpha" / mover.CLAUDE_DIR / "agents" / "one.md"
        ).read_text() == "one"

    def test_only_present_artifacts_are_copied(
        self, source: Path, target: Path
    ) -> None:
        make_repo(source, "alpha", claude_md="# alpha")

        mover.copy_artifacts(mover.find_repos(source), target)

        assert (target / "alpha" / mover.CLAUDE_FILE).is_file()
        assert not (target / "alpha" / mover.CLAUDE_DIR).exists()

    def test_unrelated_repo_files_are_not_copied(
        self, source: Path, target: Path
    ) -> None:
        repo = make_repo(source, "alpha", claude_md="# alpha")
        (repo / "README.md").write_text("readme")

        mover.copy_artifacts(mover.find_repos(source), target)

        assert sorted(p.name for p in (target / "alpha").iterdir()) == [
            mover.CLAUDE_FILE
        ]

    def test_dry_run_writes_nothing(self, source: Path, target: Path) -> None:
        make_repo(source, "alpha", claude_md="# alpha")

        copied = mover.copy_artifacts(
            mover.find_repos(source), target, dry_run=True
        )

        assert list(copied) == [source / "alpha"]
        assert list(target.iterdir()) == []

    def test_stale_destination_directory_is_replaced(
        self, source: Path, target: Path
    ) -> None:
        make_repo(source, "alpha", claude_dir={"keep.md": "new"})
        stale = target / "alpha" / mover.CLAUDE_DIR
        stale.mkdir(parents=True)
        (stale / "gone.md").write_text("old")

        mover.copy_artifacts(
            mover.find_repos(source), target, collision=mover.CollisionPolicy.OVERWRITE
        )

        assert (stale / "keep.md").read_text() == "new"
        assert not (stale / "gone.md").exists()


class TestCollisions:
    @pytest.fixture
    def duplicates(self, source: Path) -> list[mover.Repo]:
        make_repo(source / "one", "dup", claude_md="# first")
        make_repo(source / "two", "dup", claude_md="# second")
        return sorted(mover.find_repos(source), key=lambda r: str(r.path))

    def test_suffix_policy_keeps_both(
        self, duplicates: list[mover.Repo], target: Path
    ) -> None:
        mover.copy_artifacts(
            duplicates, target, collision=mover.CollisionPolicy.SUFFIX
        )

        assert (target / "dup" / mover.CLAUDE_FILE).read_text() == "# first"
        assert (target / "dup-2" / mover.CLAUDE_FILE).read_text() == "# second"

    def test_skip_policy_keeps_the_first(
        self, duplicates: list[mover.Repo], target: Path
    ) -> None:
        copied = mover.copy_artifacts(
            duplicates, target, collision=mover.CollisionPolicy.SKIP
        )

        assert list(copied) == [duplicates[0].path]
        assert (target / "dup" / mover.CLAUDE_FILE).read_text() == "# first"
        assert not (target / "dup-2").exists()

    def test_overwrite_policy_keeps_the_last(
        self, duplicates: list[mover.Repo], target: Path
    ) -> None:
        mover.copy_artifacts(
            duplicates, target, collision=mover.CollisionPolicy.OVERWRITE
        )

        assert (target / "dup" / mover.CLAUDE_FILE).read_text() == "# second"
        assert not (target / "dup-2").exists()

    def test_suffix_policy_avoids_preexisting_directories(
        self, source: Path, target: Path
    ) -> None:
        make_repo(source, "alpha", claude_md="# alpha")
        (target / "alpha").mkdir()

        mover.copy_artifacts(mover.find_repos(source), target)

        assert (target / "alpha-2" / mover.CLAUDE_FILE).read_text() == "# alpha"


class TestCli:
    def test_end_to_end(self, source: Path, tmp_path: Path) -> None:
        make_repo(source, "alpha", claude_md="# alpha", claude_dir={"s.json": "{}"})
        make_repo(source / "nest", "beta")
        out = tmp_path / "created" / "here"

        code = mover.main(["collect", str(source), str(out)])

        assert code == 0
        assert (out / "alpha" / mover.CLAUDE_FILE).read_text() == "# alpha"
        assert not (out / "beta").exists()

    def test_missing_source_is_an_error(self, tmp_path: Path) -> None:
        argv = ["collect", str(tmp_path / "nope"), str(tmp_path / "out")]

        assert mover.main(argv) == 2

    def test_target_may_not_equal_source(self, source: Path) -> None:
        assert mover.main(["collect", str(source), str(source)]) == 2

    def test_target_equality_survives_relative_paths(
        self, source: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(source)

        assert mover.main(["collect", str(source), "."]) == 2

    def test_no_matches_still_succeeds(self, source: Path, target: Path) -> None:
        make_repo(source, "alpha")

        assert mover.main(["collect", str(source), str(target)]) == 0
        assert list(target.iterdir()) == []

    def test_dry_run_does_not_create_the_target(
        self, source: Path, tmp_path: Path
    ) -> None:
        make_repo(source, "alpha", claude_md="# alpha")
        out = tmp_path / "out"

        assert mover.main(["collect", str(source), str(out), "--dry-run"]) == 0
        assert not out.exists()

    def test_nested_flag_is_wired_through(
        self, source: Path, target: Path
    ) -> None:
        outer = make_repo(source, "outer", claude_md="# outer")
        make_repo(outer / "vendor", "inner", claude_md="# inner")

        assert mover.main(["collect", str(source), str(target), "--nested"]) == 0
        assert (target / "inner" / mover.CLAUDE_FILE).read_text() == "# inner"

    def test_collision_flag_is_wired_through(
        self, source: Path, target: Path
    ) -> None:
        make_repo(source / "one", "dup", claude_md="# first")
        make_repo(source / "two", "dup", claude_md="# second")

        argv = ["collect", str(source), str(target), "--on-collision", "skip"]

        assert mover.main(argv) == 0
        assert not (target / "dup-2").exists()

    def test_target_nested_in_source_is_not_re_copied(
        self, source: Path
    ) -> None:
        """A target inside the source must not pick up its own output."""
        make_repo(source, "alpha", claude_md="# alpha")
        out = source / "collected"

        assert mover.main(["collect", str(source), str(out)]) == 0

        assert not (out / "collected").exists()
        assert (out / "alpha" / mover.CLAUDE_FILE).read_text() == "# alpha"

    def test_a_command_is_required(self) -> None:
        with pytest.raises(SystemExit):
            mover.main([])


def make_bundle(
    archive: Path,
    name: str,
    *,
    claude_md: str | None = None,
    claude_dir: dict[str, str] | None = None,
) -> Path:
    """Create an archive folder of the shape ``collect`` produces."""
    return make_repo(
        archive, name, claude_md=claude_md, claude_dir=claude_dir, git=False
    )


class TestBundleDiscovery:
    def test_bundles_are_found(self, target: Path) -> None:
        make_bundle(target, "alpha", claude_md="# alpha")
        make_bundle(target, "beta", claude_dir={"s.json": "{}"})

        found = {b.path.name for b in mover.find_bundles(target)}

        assert found == {"alpha", "beta"}

    def test_folders_without_artifacts_are_ignored(self, target: Path) -> None:
        make_bundle(target, "empty")

        assert mover.find_bundles(target) == []

    def test_loose_files_are_ignored(self, target: Path) -> None:
        (target / "notes.txt").write_text("hi")

        assert mover.find_bundles(target) == []

    def test_search_is_shallow(self, target: Path) -> None:
        """A repo's own nested CLAUDE.md must not be mistaken for a bundle."""
        bundle = make_bundle(target, "alpha", claude_md="# alpha")
        make_bundle(bundle, "sub", claude_md="# sub")

        found = [b.path.name for b in mover.find_bundles(target)]

        assert found == ["alpha"]

    def test_missing_archive_yields_nothing(self, tmp_path: Path) -> None:
        assert mover.find_bundles(tmp_path / "nope") == []


class TestRestore:
    def test_artifacts_land_in_the_matching_repo(
        self, source: Path, target: Path
    ) -> None:
        repo = make_repo(source, "alpha")
        make_bundle(target, "alpha", claude_md="# alpha", claude_dir={"s.json": "{}"})

        mover.restore_artifacts(
            mover.find_bundles(target),
            mover.find_repos(source, require_artifacts=False),
        )

        assert (repo / mover.CLAUDE_FILE).read_text() == "# alpha"
        assert (repo / mover.CLAUDE_DIR / "s.json").read_text() == "{}"

    def test_repo_may_be_at_any_depth(self, source: Path, target: Path) -> None:
        repo = make_repo(source / "a" / "b", "alpha")
        make_bundle(target, "alpha", claude_md="# alpha")

        mover.restore_artifacts(
            mover.find_bundles(target),
            mover.find_repos(source, require_artifacts=False),
        )

        assert (repo / mover.CLAUDE_FILE).read_text() == "# alpha"

    def test_non_repos_are_never_written_to(self, source: Path, target: Path) -> None:
        plain = make_repo(source, "alpha", git=False)
        make_bundle(target, "alpha", claude_md="# alpha")

        restored = mover.restore_artifacts(
            mover.find_bundles(target),
            mover.find_repos(source, require_artifacts=False),
        )

        assert restored == {}
        assert not (plain / mover.CLAUDE_FILE).exists()

    def test_unmatched_bundle_is_reported(
        self, source: Path, target: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        make_repo(source, "alpha")
        make_bundle(target, "orphan", claude_md="# orphan")

        with caplog.at_level("WARNING"):
            restored = mover.restore_artifacts(
                mover.find_bundles(target),
                mover.find_repos(source, require_artifacts=False),
            )

        assert restored == {}
        assert "orphan" in caplog.text

    def test_ambiguous_bundle_is_skipped(
        self, source: Path, target: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        one = make_repo(source / "one", "dup")
        two = make_repo(source / "two", "dup")
        make_bundle(target, "dup", claude_md="# dup")

        with caplog.at_level("WARNING"):
            restored = mover.restore_artifacts(
                mover.find_bundles(target),
                mover.find_repos(source, require_artifacts=False),
            )

        assert restored == {}
        assert not (one / mover.CLAUDE_FILE).exists()
        assert not (two / mover.CLAUDE_FILE).exists()
        assert "2 repositories" in caplog.text

    def test_dry_run_writes_nothing(self, source: Path, target: Path) -> None:
        repo = make_repo(source, "alpha")
        make_bundle(target, "alpha", claude_md="# alpha")

        restored = mover.restore_artifacts(
            mover.find_bundles(target),
            mover.find_repos(source, require_artifacts=False),
            dry_run=True,
        )

        assert list(restored) == [target / "alpha"]
        assert not (repo / mover.CLAUDE_FILE).exists()

    def test_round_trip_is_faithful(self, source: Path, target: Path) -> None:
        repo = make_repo(
            source,
            "alpha",
            claude_md="# alpha",
            claude_dir={"settings.json": "{}", "agents/one.md": "one"},
        )
        mover.copy_artifacts(mover.find_repos(source), target)
        shutil.rmtree(repo / mover.CLAUDE_DIR)
        (repo / mover.CLAUDE_FILE).unlink()

        mover.restore_artifacts(
            mover.find_bundles(target),
            mover.find_repos(source, require_artifacts=False),
        )

        assert (repo / mover.CLAUDE_FILE).read_text() == "# alpha"
        assert (repo / mover.CLAUDE_DIR / "settings.json").read_text() == "{}"
        assert (repo / mover.CLAUDE_DIR / "agents" / "one.md").read_text() == "one"


class TestRestoreExistingPolicy:
    @pytest.fixture
    def repo(self, source: Path) -> Path:
        return make_repo(
            source, "alpha", claude_md="# local", claude_dir={"local.md": "local"}
        )

    @pytest.fixture
    def archive(self, target: Path) -> Path:
        return make_bundle(
            target, "alpha", claude_md="# archived", claude_dir={"archived.md": "arch"}
        )

    def restore(self, source: Path, target: Path, **kwargs: object) -> dict:
        return mover.restore_artifacts(
            mover.find_bundles(target),
            mover.find_repos(source, require_artifacts=False),
            **kwargs,
        )

    def test_overwrite_replaces_both_artifacts(
        self, source: Path, target: Path, repo: Path, archive: Path
    ) -> None:
        self.restore(source, target, on_existing=mover.ExistingPolicy.OVERWRITE)

        assert (repo / mover.CLAUDE_FILE).read_text() == "# archived"
        assert (repo / mover.CLAUDE_DIR / "archived.md").exists()
        assert not (repo / mover.CLAUDE_DIR / "local.md").exists()

    def test_skip_leaves_both_artifacts(
        self, source: Path, target: Path, repo: Path, archive: Path
    ) -> None:
        restored = self.restore(source, target, on_existing=mover.ExistingPolicy.SKIP)

        assert restored == {}
        assert (repo / mover.CLAUDE_FILE).read_text() == "# local"
        assert (repo / mover.CLAUDE_DIR / "local.md").exists()

    def test_skip_still_fills_in_what_is_missing(
        self, source: Path, target: Path, repo: Path, archive: Path
    ) -> None:
        (repo / mover.CLAUDE_FILE).unlink()

        restored = self.restore(source, target, on_existing=mover.ExistingPolicy.SKIP)

        assert list(restored) == [archive]
        assert (repo / mover.CLAUDE_FILE).read_text() == "# archived"
        assert (repo / mover.CLAUDE_DIR / "local.md").exists()

    def test_backup_preserves_what_it_replaces(
        self, source: Path, target: Path, repo: Path, archive: Path
    ) -> None:
        self.restore(source, target, on_existing=mover.ExistingPolicy.BACKUP)

        assert (repo / mover.CLAUDE_FILE).read_text() == "# archived"
        assert (repo / f"{mover.CLAUDE_FILE}.bak").read_text() == "# local"
        assert (repo / mover.CLAUDE_DIR / "archived.md").exists()
        assert (repo / f"{mover.CLAUDE_DIR}.bak" / "local.md").exists()

    def test_backup_does_not_clobber_an_earlier_backup(
        self, source: Path, target: Path, repo: Path, archive: Path
    ) -> None:
        (repo / f"{mover.CLAUDE_FILE}.bak").write_text("# older")

        self.restore(source, target, on_existing=mover.ExistingPolicy.BACKUP)

        assert (repo / f"{mover.CLAUDE_FILE}.bak").read_text() == "# older"
        assert (repo / f"{mover.CLAUDE_FILE}.bak.2").read_text() == "# local"

    def test_merge_keeps_local_files_in_the_claude_dir(
        self, source: Path, target: Path, repo: Path, archive: Path
    ) -> None:
        self.restore(source, target, merge=True)

        assert (repo / mover.CLAUDE_DIR / "archived.md").exists()
        assert (repo / mover.CLAUDE_DIR / "local.md").exists()

    def test_merge_still_overwrites_colliding_files(
        self, source: Path, target: Path, repo: Path, archive: Path
    ) -> None:
        (archive / mover.CLAUDE_DIR / "local.md").write_text("from archive")

        self.restore(source, target, merge=True)

        assert (repo / mover.CLAUDE_DIR / "local.md").read_text() == "from archive"


class TestRestoreCli:
    def test_end_to_end(self, source: Path, target: Path) -> None:
        repo = make_repo(source, "alpha")
        make_bundle(target, "alpha", claude_md="# alpha")
        make_bundle(target, "orphan", claude_md="# orphan")

        assert mover.main(["restore", str(target), str(source)]) == 0
        assert (repo / mover.CLAUDE_FILE).read_text() == "# alpha"

    def test_missing_archive_is_an_error(self, source: Path, tmp_path: Path) -> None:
        assert mover.main(["restore", str(tmp_path / "nope"), str(source)]) == 2

    def test_missing_destination_is_an_error(
        self, target: Path, tmp_path: Path
    ) -> None:
        assert mover.main(["restore", str(target), str(tmp_path / "nope")]) == 2

    def test_destination_may_not_equal_archive(self, source: Path) -> None:
        assert mover.main(["restore", str(source), str(source)]) == 2

    def test_empty_archive_still_succeeds(self, source: Path, target: Path) -> None:
        repo = make_repo(source, "alpha")

        assert mover.main(["restore", str(target), str(source)]) == 0
        assert not (repo / mover.CLAUDE_FILE).exists()

    def test_destination_without_repos_still_succeeds(
        self, source: Path, target: Path
    ) -> None:
        make_bundle(target, "alpha", claude_md="# alpha")

        assert mover.main(["restore", str(target), str(source)]) == 0

    def test_flags_are_wired_through(self, source: Path, target: Path) -> None:
        outer = make_repo(source, "outer")
        inner = make_repo(outer / "vendor", "inner", claude_md="# local")
        make_bundle(target, "inner", claude_md="# archived")

        argv = [
            "restore",
            str(target),
            str(source),
            "--nested",
            "--on-existing",
            "backup",
        ]

        assert mover.main(argv) == 0
        assert (inner / mover.CLAUDE_FILE).read_text() == "# archived"
        assert (inner / f"{mover.CLAUDE_FILE}.bak").read_text() == "# local"

    def test_dry_run_writes_nothing(self, source: Path, target: Path) -> None:
        repo = make_repo(source, "alpha")
        make_bundle(target, "alpha", claude_md="# alpha")

        assert mover.main(["restore", str(target), str(source), "--dry-run"]) == 0
        assert not (repo / mover.CLAUDE_FILE).exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics")
def test_unreadable_target_parent_is_reported(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    try:
        assert mover.main(["collect", str(source), str(locked / "out")]) == 2
    finally:
        locked.chmod(0o700)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A stand-in user-level directory holding config and runtime state."""
    return make_root(
        tmp_path / "home" / ".claude",
        {
            "CLAUDE.md": "# global",
            "settings.json": "{}",
            "skills/one/SKILL.md": "one",
            "skills/one/cache/keep.txt": "nested",
            "projects/session.jsonl": "transcript",
            "history.jsonl": "history",
            "cache/blob": "blob",
            "daemon.log": "log",
            ".credentials.json": "secret",
        },
    )


class TestRootLocation:
    def test_config_dir_env_var_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "elsewhere"))

        assert mover.root_config_dir() == tmp_path / "elsewhere"

    def test_falls_back_to_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

        assert mover.root_config_dir() == Path.home() / mover.CLAUDE_DIR


class TestCollectRoot:
    def test_archived_under_the_reserved_name(self, target: Path, root: Path) -> None:
        dest = mover.collect_root(target, root=root)

        assert dest == target / mover.ROOT_NAME
        archived = target / mover.ROOT_NAME / mover.CLAUDE_DIR
        assert (archived / "CLAUDE.md").read_text() == "# global"
        assert (archived / "settings.json").read_text() == "{}"
        assert (archived / "skills" / "one" / "SKILL.md").read_text() == "one"

    @pytest.mark.parametrize(
        "excluded",
        ["projects", "history.jsonl", "cache", "daemon.log", ".credentials.json"],
    )
    def test_runtime_state_is_left_behind(
        self, target: Path, root: Path, excluded: str
    ) -> None:
        mover.collect_root(target, root=root)

        assert not (target / mover.ROOT_NAME / mover.CLAUDE_DIR / excluded).exists()

    def test_exclusions_apply_only_at_the_top_level(
        self, target: Path, root: Path
    ) -> None:
        """A nested directory sharing an excluded name must survive."""
        mover.collect_root(target, root=root)

        nested = (
            target
            / mover.ROOT_NAME
            / mover.CLAUDE_DIR
            / "skills"
            / "one"
            / "cache"
            / "keep.txt"
        )
        assert nested.read_text() == "nested"

    def test_empty_excludes_archives_everything(
        self, target: Path, root: Path
    ) -> None:
        mover.collect_root(target, root=root, excludes=())

        archived = target / mover.ROOT_NAME / mover.CLAUDE_DIR
        assert (archived / "projects" / "session.jsonl").exists()
        assert (archived / ".credentials.json").exists()

    def test_a_second_collect_replaces_the_first(
        self, target: Path, root: Path
    ) -> None:
        mover.collect_root(target, root=root)
        (root / "settings.json").unlink()

        mover.collect_root(target, root=root)

        archived = target / mover.ROOT_NAME / mover.CLAUDE_DIR
        assert not (archived / "settings.json").exists()
        assert (archived / "CLAUDE.md").exists()

    def test_missing_root_is_reported(
        self, target: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("WARNING"):
            assert mover.collect_root(target, root=tmp_path / "nope") is None

        assert "no user-level configuration directory" in caplog.text
        assert not (target / mover.ROOT_NAME).exists()

    def test_dry_run_writes_nothing(self, target: Path, root: Path) -> None:
        assert mover.collect_root(target, root=root, dry_run=True) is not None
        assert not (target / mover.ROOT_NAME).exists()

    def test_the_archive_is_a_bundle(self, target: Path, root: Path) -> None:
        """collect_root's output must be discoverable by the restore side."""
        mover.collect_root(target, root=root)

        (bundle,) = mover.find_bundles(target)

        assert bundle.path.name == mover.ROOT_NAME
        assert bundle.has_dir


class TestReservedName:
    def test_suffix_policy_yields_the_reserved_name_to_root(
        self, source: Path, target: Path
    ) -> None:
        make_repo(source, mover.ROOT_NAME, claude_md="# repo named ROOT")

        mover.copy_artifacts(mover.find_repos(source), target)

        assert (target / f"{mover.ROOT_NAME}-2" / mover.CLAUDE_FILE).exists()
        assert not (target / mover.ROOT_NAME).exists()

    @pytest.mark.parametrize("policy", ["skip", "overwrite"])
    def test_other_policies_refuse_the_reserved_name(
        self, source: Path, target: Path, policy: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        make_repo(source, mover.ROOT_NAME, claude_md="# repo named ROOT")

        with caplog.at_level("WARNING"):
            copied = mover.copy_artifacts(
                mover.find_repos(source), target, collision=policy
            )

        assert copied == {}
        assert "reserved" in caplog.text
        assert not (target / mover.ROOT_NAME).exists()

    def test_a_real_root_bundle_is_not_disturbed(
        self, source: Path, target: Path, root: Path
    ) -> None:
        mover.collect_root(target, root=root)
        make_repo(source, mover.ROOT_NAME, claude_md="# repo named ROOT")

        mover.copy_artifacts(mover.find_repos(source), target)

        archived = target / mover.ROOT_NAME / mover.CLAUDE_DIR
        assert (archived / "CLAUDE.md").read_text() == "# global"


class TestRestoreRoot:
    @pytest.fixture
    def bundle(self, target: Path, root: Path) -> mover.Bundle:
        mover.collect_root(target, root=root)
        return mover.find_bundles(target)[0]

    def test_archived_config_is_written_back(
        self, bundle: mover.Bundle, tmp_path: Path
    ) -> None:
        destination = tmp_path / "fresh" / ".claude"

        assert mover.restore_root(bundle, root=destination) == destination
        assert (destination / "CLAUDE.md").read_text() == "# global"
        assert (destination / "skills" / "one" / "SKILL.md").read_text() == "one"

    def test_live_runtime_state_survives(
        self, bundle: mover.Bundle, root: Path
    ) -> None:
        """Restoring must not delete what collect deliberately excluded."""
        (root / "CLAUDE.md").write_text("# stale")

        mover.restore_root(bundle, root=root)

        assert (root / "CLAUDE.md").read_text() == "# global"
        assert (root / "projects" / "session.jsonl").read_text() == "transcript"
        assert (root / ".credentials.json").read_text() == "secret"

    def test_skip_leaves_an_existing_directory_alone(
        self, bundle: mover.Bundle, root: Path
    ) -> None:
        (root / "CLAUDE.md").write_text("# stale")

        result = mover.restore_root(
            bundle, root=root, on_existing=mover.ExistingPolicy.SKIP
        )

        assert result is None
        assert (root / "CLAUDE.md").read_text() == "# stale"

    def test_backup_moves_the_old_directory_aside(
        self, bundle: mover.Bundle, root: Path
    ) -> None:
        (root / "CLAUDE.md").write_text("# stale")

        mover.restore_root(bundle, root=root, on_existing=mover.ExistingPolicy.BACKUP)

        assert (root / "CLAUDE.md").read_text() == "# global"
        assert not (root / "projects").exists()
        aside = root.with_name(f"{root.name}.bak")
        assert (aside / "CLAUDE.md").read_text() == "# stale"
        assert (aside / "projects" / "session.jsonl").read_text() == "transcript"

    def test_dry_run_writes_nothing(self, bundle: mover.Bundle, tmp_path: Path) -> None:
        destination = tmp_path / "fresh" / ".claude"

        assert mover.restore_root(bundle, root=destination, dry_run=True) is not None
        assert not destination.exists()

    def test_bundle_without_a_claude_dir_is_reported(
        self, target: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        make_bundle(target, mover.ROOT_NAME, claude_md="# stray")
        (stray,) = mover.find_bundles(target)

        with caplog.at_level("WARNING"):
            assert mover.restore_root(stray, root=tmp_path / "fresh") is None

        assert "holds no" in caplog.text

    def test_repo_restore_passes_over_the_root_bundle(
        self, source: Path, target: Path, root: Path
    ) -> None:
        mover.collect_root(target, root=root)
        make_repo(source, "alpha")
        make_bundle(target, "alpha", claude_md="# alpha")

        restored = mover.restore_artifacts(
            mover.find_bundles(target),
            mover.find_repos(source, require_artifacts=False),
        )

        assert list(restored) == [target / "alpha"]
        assert not (source / mover.ROOT_NAME).exists()


class TestRootCli:
    def test_collect_includes_root_by_default(
        self, source: Path, target: Path, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(root))
        make_repo(source, "alpha", claude_md="# alpha")

        assert mover.main(["collect", str(source), str(target)]) == 0
        assert (
            target / mover.ROOT_NAME / mover.CLAUDE_DIR / "CLAUDE.md"
        ).read_text() == "# global"
        assert (target / "alpha" / mover.CLAUDE_FILE).exists()

    def test_collect_honours_no_root(
        self, source: Path, target: Path, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(root))
        make_repo(source, "alpha", claude_md="# alpha")

        assert mover.main(["collect", str(source), str(target), "--no-root"]) == 0
        assert not (target / mover.ROOT_NAME).exists()

    def test_collect_root_flag_overrides_the_location(
        self, source: Path, target: Path, root: Path
    ) -> None:
        assert mover.main(["collect", str(source), str(target), "--root", str(root)]) == 0
        assert (target / mover.ROOT_NAME / mover.CLAUDE_DIR / "settings.json").exists()

    def test_collect_root_all_keeps_runtime_state(
        self, source: Path, target: Path, root: Path
    ) -> None:
        argv = ["collect", str(source), str(target), "--root", str(root), "--root-all"]

        assert mover.main(argv) == 0
        archived = target / mover.ROOT_NAME / mover.CLAUDE_DIR
        assert (archived / "projects" / "session.jsonl").exists()

    def test_round_trip_through_the_cli(
        self, source: Path, target: Path, root: Path, tmp_path: Path
    ) -> None:
        make_repo(source, "alpha", claude_md="# alpha")
        destination = tmp_path / "restored" / ".claude"

        assert mover.main(["collect", str(source), str(target), "--root", str(root)]) == 0
        argv = ["restore", str(target), str(source), "--root", str(destination)]
        assert mover.main(argv) == 0

        assert (destination / "CLAUDE.md").read_text() == "# global"
        assert (destination / "skills" / "one" / "SKILL.md").read_text() == "one"
        assert not (destination / "projects").exists()

    def test_restore_honours_no_root(
        self, source: Path, target: Path, root: Path, tmp_path: Path
    ) -> None:
        mover.collect_root(target, root=root)
        make_repo(source, "alpha")
        destination = tmp_path / "restored" / ".claude"

        argv = [
            "restore",
            str(target),
            str(source),
            "--root",
            str(destination),
            "--no-root",
        ]

        assert mover.main(argv) == 0
        assert not destination.exists()

    def test_restore_dry_run_leaves_the_root_alone(
        self, source: Path, target: Path, root: Path
    ) -> None:
        mover.collect_root(target, root=root)
        make_repo(source, "alpha")
        (root / "CLAUDE.md").write_text("# stale")

        argv = ["restore", str(target), str(source), "--root", str(root), "--dry-run"]

        assert mover.main(argv) == 0
        assert (root / "CLAUDE.md").read_text() == "# stale"
