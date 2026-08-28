#!/usr/bin/env python3
"""Collect and restore Claude configuration across git repositories.

The ``collect`` direction walks a source tree looking for git repositories,
and for each repository that contains a ``CLAUDE.md`` file and/or a
``.claude`` directory, copies those artifacts into a per-repository folder
inside an archive directory.

The ``restore`` direction reverses that: it walks a destination tree for git
repositories, matches each one against a folder of the same name in the
archive, and copies the archived artifacts back into the repository.

The user-level configuration directory (``~/.claude``) is handled alongside
the repositories, archived under the reserved folder name ``ROOT``.
"""

from __future__ import annotations

import argparse
import fnmatch
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

CLAUDE_FILE = "CLAUDE.md"
CLAUDE_DIR = ".claude"

# The archive folder that holds the user-level configuration directory rather
# than a repository. No repository may claim this name.
ROOT_NAME = "ROOT"

# Entries of the user-level configuration directory that are runtime state
# rather than configuration: session transcripts, caches, logs, and
# credentials. They dominate the directory's size, they change constantly,
# and some of them are sensitive, so archiving them by default would be both
# wasteful and a disclosure risk. Patterns are fnmatch-style and apply only
# to the top level, so a legitimately named file deeper in the tree survives.
ROOT_EXCLUDES = (
    ".credentials.json",
    ".last-*",
    "*.lock",
    "*.log",
    "backups",
    "cache",
    "daemon*",
    "debug",
    "downloads",
    "file-history",
    "history.jsonl",
    "ide",
    "jobs",
    "paste-cache",
    "projects",
    "session-env",
    "sessions",
    "shell-snapshots",
    "statsig",
    "stats-cache.json",
    "tasks",
    "telemetry",
    "todos",
)

# Directories that are never worth descending into. ``.git`` is excluded
# because a repository's own metadata cannot contain another repository we
# care about; the rest are large, generated, and vendored trees.
PRUNE_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".tox",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "site-packages",
    }
)

log = logging.getLogger("mover")


class CollisionPolicy:
    """What to do when two repositories want the same archive folder."""

    SUFFIX = "suffix"
    SKIP = "skip"
    OVERWRITE = "overwrite"

    ALL = (SUFFIX, SKIP, OVERWRITE)


class ExistingPolicy:
    """What to do when a repository already holds an artifact being restored."""

    OVERWRITE = "overwrite"
    SKIP = "skip"
    BACKUP = "backup"

    ALL = (OVERWRITE, SKIP, BACKUP)


# Lets _inspect hand back the same subclass it was asked to build.
T = TypeVar("T", bound="ArtifactSet")


@dataclass(frozen=True)
class ArtifactSet:
    """A directory, and which Claude artifacts it holds."""

    path: Path
    has_file: bool
    has_dir: bool

    @property
    def artifacts(self) -> list[Path]:
        found: list[Path] = []
        if self.has_file:
            found.append(self.path / CLAUDE_FILE)
        if self.has_dir:
            found.append(self.path / CLAUDE_DIR)
        return found


class Repo(ArtifactSet):
    """The root of a git repository."""


class Bundle(ArtifactSet):
    """One repository's worth of artifacts inside an archive directory."""


def is_git_repo(path: Path) -> bool:
    """Return True if *path* is the root of a git repository.

    A ``.git`` entry may be a directory (normal clone) or a file (submodule or
    linked worktree, where it holds a ``gitdir:`` pointer). Both count.
    """
    return (path / ".git").exists()


def root_config_dir() -> Path:
    """Return the user-level configuration directory.

    ``CLAUDE_CONFIG_DIR`` relocates it wholesale, so honour that before
    falling back to ``~/.claude``.
    """
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(override).expanduser() if override else Path.home() / CLAUDE_DIR


def has_claude_file(path: Path) -> bool:
    return (path / CLAUDE_FILE).is_file()


def has_claude_dir(path: Path) -> bool:
    return (path / CLAUDE_DIR).is_dir()


def find_repos(
    source: Path, *, nested: bool = False, require_artifacts: bool = True
) -> list[Repo]:
    """Find git repositories under *source*.

    By default only repositories that already carry a Claude artifact are
    returned, which is what collecting needs. Restoring passes
    ``require_artifacts=False``, because a repository with nothing in it is
    precisely the one most in need of a restore.

    The walk does not follow symlinks, so cyclic links cannot trap it. It also
    stops descending once a repository root is found; ``nested=True`` keeps
    descending so that submodules and vendored repositories are reported too.
    """
    repos: list[Repo] = []

    if is_git_repo(source):
        repo = _inspect(source, Repo, require_artifacts=require_artifacts)
        if repo is not None:
            repos.append(repo)
        if not nested:
            return repos

    for dirpath, dirnames, _ in os.walk(source, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in PRUNE_DIRS)
        here = Path(dirpath)

        keep: list[str] = []
        for name in dirnames:
            child = here / name
            if not is_git_repo(child):
                keep.append(name)
                continue
            repo = _inspect(child, Repo, require_artifacts=require_artifacts)
            if repo is not None:
                repos.append(repo)
            if nested:
                keep.append(name)
        dirnames[:] = keep

    return repos


def find_bundles(archive: Path) -> list[Bundle]:
    """Find per-repository artifact folders directly under *archive*.

    The search is deliberately shallow: ``collect`` writes a flat archive, so
    anything deeper is a repository's own content rather than a bundle.
    """
    if not archive.is_dir():
        return []

    bundles = []
    for entry in sorted(archive.iterdir()):
        if not entry.is_dir():
            continue
        bundle = _inspect(entry, Bundle)
        if bundle is not None:
            bundles.append(bundle)
    return bundles


def _inspect(
    path: Path, kind: type[T], *, require_artifacts: bool = True
) -> T | None:
    file_found = has_claude_file(path)
    dir_found = has_claude_dir(path)
    if require_artifacts and not (file_found or dir_found):
        log.debug("skipping %s: no Claude artifacts", path)
        return None
    return kind(path=path, has_file=file_found, has_dir=dir_found)


def _unique_destination(target: Path, name: str, taken: set[str]) -> Path:
    """Return an unused destination directory name derived from *name*."""
    candidate = name
    counter = 1
    while candidate in taken or (target / candidate).exists():
        counter += 1
        candidate = f"{name}-{counter}"
    taken.add(candidate)
    return target / candidate


def _copy(source_path: Path, destination: Path, *, merge: bool = False) -> None:
    """Copy a file or directory, replacing whatever is already there.

    With *merge*, an existing destination directory is overlaid rather than
    replaced, so files present only in the destination survive.
    """
    if source_path.is_dir():
        if destination.exists() and not merge:
            shutil.rmtree(destination)
        shutil.copytree(source_path, destination, symlinks=True, dirs_exist_ok=merge)
    else:
        shutil.copy2(source_path, destination)


def _backup(path: Path) -> Path:
    """Rename *path* out of the way, and return where it went."""
    candidate = path.with_name(path.name + ".bak")
    counter = 1
    while candidate.exists():
        counter += 1
        candidate = path.with_name(f"{path.name}.bak.{counter}")
    path.rename(candidate)
    return candidate


def _top_level_ignore(
    root: Path, patterns: tuple[str, ...]
) -> Callable[[str, list[str]], set[str]]:
    """Build a ``copytree`` ignore callback that filters only *root*'s entries."""

    def ignore(dirpath: str, names: list[str]) -> set[str]:
        if Path(dirpath) != root:
            return set()
        return {
            name
            for name in names
            if any(fnmatch.fnmatch(name, pattern) for pattern in patterns)
        }

    return ignore


def collect_root(
    archive: Path,
    *,
    root: Path | None = None,
    excludes: tuple[str, ...] = ROOT_EXCLUDES,
    dry_run: bool = False,
) -> Path | None:
    """Copy the user-level configuration directory into ``ROOT`` under *archive*.

    Returns the archive folder written, or None if there is no such directory.
    Pass ``excludes=()`` to archive runtime state as well.
    """
    root = root or root_config_dir()
    if not root.is_dir():
        log.warning("no user-level configuration directory at %s", root)
        return None

    dest = archive / ROOT_NAME
    log.info("%s -> %s", root, dest / CLAUDE_DIR)
    if dry_run:
        return dest

    dest.mkdir(parents=True, exist_ok=True)
    destination = dest / CLAUDE_DIR
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(
        root,
        destination,
        symlinks=True,
        ignore=_top_level_ignore(root, excludes) if excludes else None,
    )
    return dest


def restore_root(
    bundle: Bundle,
    *,
    root: Path | None = None,
    on_existing: str = ExistingPolicy.OVERWRITE,
    dry_run: bool = False,
) -> Path | None:
    """Copy an archived ``ROOT`` bundle back over the user-level directory.

    The live directory is never deleted outright: archived files are overlaid
    onto it, so the runtime state that ``collect_root`` deliberately left out
    of the archive survives the restore. ``backup`` is the exception and is
    the way to ask for the archived state exactly -- it moves the existing
    directory aside first, leaving a clean copy.

    Returns the directory written, or None if nothing was.
    """
    root = root or root_config_dir()
    if not bundle.has_dir:
        log.warning("%s holds no %s directory", bundle.path, CLAUDE_DIR)
        return None

    source_path = bundle.path / CLAUDE_DIR
    merge = True
    if root.exists():
        if on_existing == ExistingPolicy.SKIP:
            log.warning("keeping existing %s", root)
            return None
        if on_existing == ExistingPolicy.BACKUP:
            merge = False
            if not dry_run:
                log.info("backed up %s", _backup(root))

    log.info("%s -> %s", source_path, root)
    if not dry_run:
        root.parent.mkdir(parents=True, exist_ok=True)
        _copy(source_path, root, merge=merge)
    return root


def copy_artifacts(
    repos: list[Repo],
    target: Path,
    *,
    collision: str = CollisionPolicy.SUFFIX,
    reserved: frozenset[str] = frozenset({ROOT_NAME}),
    dry_run: bool = False,
) -> dict[Path, Path]:
    """Copy each repository's Claude artifacts into *target*.

    Returns a mapping of repository path to the archive folder that was used.
    Repositories skipped because of a name collision are absent from it.

    Names in *reserved* are never handed to a repository, so a repository that
    happens to be called ``ROOT`` cannot displace the user-level bundle.
    """
    taken: set[str] = set(reserved)
    copied: dict[Path, Path] = {}

    for repo in repos:
        name = repo.path.name
        if collision == CollisionPolicy.SUFFIX:
            dest = _unique_destination(target, name, taken)
        else:
            dest = target / name
            if name in reserved:
                log.warning("skipping %s: %s is a reserved name", repo.path, name)
                continue
            if dest.exists() or name in taken:
                if collision == CollisionPolicy.SKIP:
                    log.warning("skipping %s: %s already exists", repo.path, dest)
                    continue
                log.warning("overwriting %s with %s", dest, repo.path)
            taken.add(name)

        log.info("%s -> %s", repo.path, dest)
        if not dry_run:
            dest.mkdir(parents=True, exist_ok=True)

        for source_path in repo.artifacts:
            log.debug("  copy %s", source_path.name)
            if not dry_run:
                _copy(source_path, dest / source_path.name)

        copied[repo.path] = dest

    return copied


def restore_artifacts(
    bundles: list[Bundle],
    repos: list[Repo],
    *,
    on_existing: str = ExistingPolicy.OVERWRITE,
    merge: bool = False,
    dry_run: bool = False,
) -> dict[Path, Path]:
    """Copy archived artifacts back into the repositories they came from.

    Bundles are matched to repositories by directory name. A bundle with no
    matching repository, or with more than one, is reported and left alone:
    guessing which of two same-named repositories owns a bundle is worse than
    doing nothing. The reserved ``ROOT`` bundle is not a repository and is
    passed over here; ``restore_root`` handles it.

    Returns a mapping of bundle path to the repository it was restored into.
    Bundles that were unmatched, ambiguous, or fully skipped are absent.
    """
    by_name: dict[str, list[Repo]] = {}
    for repo in repos:
        by_name.setdefault(repo.path.name, []).append(repo)

    restored: dict[Path, Path] = {}

    for bundle in bundles:
        name = bundle.path.name
        if name == ROOT_NAME:
            log.debug("skipping %s: handled as the user-level directory", bundle.path)
            continue
        candidates = by_name.get(name, [])
        if not candidates:
            log.warning("no repository named %s; leaving %s alone", name, bundle.path)
            continue
        if len(candidates) > 1:
            log.warning(
                "%s matches %d repositories, skipping: %s",
                bundle.path,
                len(candidates),
                ", ".join(str(c.path) for c in candidates),
            )
            continue

        repo = candidates[0]
        log.info("%s -> %s", bundle.path, repo.path)

        wrote = False
        for source_path in bundle.artifacts:
            destination = repo.path / source_path.name
            if destination.exists():
                if on_existing == ExistingPolicy.SKIP:
                    log.warning("  keeping existing %s", destination)
                    continue
                if on_existing == ExistingPolicy.BACKUP and not dry_run:
                    log.info("  backed up %s", _backup(destination).name)
            log.debug("  restore %s", source_path.name)
            if not dry_run:
                _copy(source_path, destination, merge=merge)
            wrote = True

        if wrote:
            restored[bundle.path] = repo.path

    return restored


def _resolve_pair(destination: Path, source: Path, dry_run: bool) -> Path:
    destination = destination.resolve()
    if destination == source:
        raise ValueError("source and destination directories must differ")
    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)
    return destination


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--nested",
        action="store_true",
        help="also search inside repositories for nested repositories",
    )
    common.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="report what would be copied without writing anything",
    )
    common.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="log each artifact as it is copied",
    )
    common.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="only report warnings and errors",
    )
    common.add_argument(
        "--root",
        type=Path,
        default=None,
        help=(
            "user-level configuration directory to archive as ROOT "
            "(default: $CLAUDE_CONFIG_DIR, else ~/.claude)"
        ),
    )
    common.add_argument(
        "--no-root",
        action="store_true",
        help="leave the user-level configuration directory out entirely",
    )

    parser = argparse.ArgumentParser(
        description=(
            "Copy CLAUDE.md files and .claude directories out of git "
            "repositories into a flat archive, or back again."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)

    collect = commands.add_parser(
        "collect",
        parents=[common],
        help="copy artifacts from repositories into an archive",
        description=(
            "Recurse a source directory for git repositories and copy each "
            "repository's CLAUDE.md and/or .claude directory into a "
            "per-repository folder under the archive directory. The "
            "user-level configuration directory is archived as ROOT."
        ),
    )
    collect.add_argument("source", type=Path, help="directory to search")
    collect.add_argument("archive", type=Path, help="directory to copy artifacts into")
    collect.add_argument(
        "--on-collision",
        choices=CollisionPolicy.ALL,
        default=CollisionPolicy.SUFFIX,
        help=(
            "what to do when two repositories share a directory name "
            "(default: suffix, which appends -2, -3, ...)"
        ),
    )
    collect.add_argument(
        "--root-all",
        action="store_true",
        help=(
            "archive the whole user-level directory, including session "
            "transcripts, caches, logs, and credentials (default: skip those)"
        ),
    )

    restore = commands.add_parser(
        "restore",
        parents=[common],
        help="copy artifacts from an archive back into repositories",
        description=(
            "Recurse a destination directory for git repositories and copy "
            "each matching archive folder's CLAUDE.md and/or .claude "
            "directory back into the repository of the same name. The ROOT "
            "folder is overlaid onto the user-level configuration directory."
        ),
    )
    restore.add_argument("archive", type=Path, help="directory holding the artifacts")
    restore.add_argument(
        "destination", type=Path, help="directory of repositories to restore into"
    )
    restore.add_argument(
        "--on-existing",
        choices=ExistingPolicy.ALL,
        default=ExistingPolicy.OVERWRITE,
        help=(
            "what to do when the repository already has the artifact "
            "(default: overwrite)"
        ),
    )
    restore.add_argument(
        "--merge",
        action="store_true",
        help=(
            "overlay the archived .claude directory onto the repository's "
            "instead of replacing it, keeping files the archive lacks"
        ),
    )

    return parser.parse_args(argv)


def _configure_logging(args: argparse.Namespace) -> None:
    level = logging.INFO
    if args.verbose:
        level = logging.DEBUG
    elif args.quiet:
        level = logging.WARNING
    logging.basicConfig(level=level, format="%(message)s", stream=sys.stderr)


def _collect(args: argparse.Namespace) -> int:
    source = args.source
    if not source.is_dir():
        log.error("source directory does not exist: %s", source)
        return 2
    source = source.resolve()

    try:
        archive = _resolve_pair(args.archive, source, args.dry_run)
    except ValueError as exc:
        log.error("%s", exc)
        return 2
    except OSError as exc:
        log.error("cannot create archive directory: %s", exc)
        return 2

    root_done = False
    if not args.no_root:
        root_done = (
            collect_root(
                archive,
                root=args.root,
                excludes=() if args.root_all else ROOT_EXCLUDES,
                dry_run=args.dry_run,
            )
            is not None
        )

    repos = find_repos(source, nested=args.nested)
    if not repos:
        log.info("no git repositories with Claude artifacts found under %s", source)
        return 0

    copied = copy_artifacts(
        repos, archive, collision=args.on_collision, dry_run=args.dry_run
    )

    verb = "would copy" if args.dry_run else "copied"
    log.info(
        "%s %d of %d repositories%s to %s",
        verb,
        len(copied),
        len(repos),
        f" plus {ROOT_NAME}" if root_done else "",
        archive,
    )
    return 0


def _restore(args: argparse.Namespace) -> int:
    archive = args.archive
    if not archive.is_dir():
        log.error("archive directory does not exist: %s", archive)
        return 2
    archive = archive.resolve()

    destination = args.destination
    if not destination.is_dir():
        log.error("destination directory does not exist: %s", destination)
        return 2
    destination = destination.resolve()
    if destination == archive:
        log.error("source and destination directories must differ")
        return 2

    bundles = find_bundles(archive)
    if not bundles:
        log.info("no Claude artifacts found under %s", archive)
        return 0

    root_done = False
    root_bundles = [b for b in bundles if b.path.name == ROOT_NAME]
    if root_bundles and not args.no_root:
        root_done = (
            restore_root(
                root_bundles[0],
                root=args.root,
                on_existing=args.on_existing,
                dry_run=args.dry_run,
            )
            is not None
        )
    bundles = [b for b in bundles if b.path.name != ROOT_NAME]

    repos = find_repos(destination, nested=args.nested, require_artifacts=False)
    if not repos:
        log.info("no git repositories found under %s", destination)
        return 0

    restored = restore_artifacts(
        bundles,
        repos,
        on_existing=args.on_existing,
        merge=args.merge,
        dry_run=args.dry_run,
    )

    verb = "would restore" if args.dry_run else "restored"
    log.info(
        "%s %d of %d bundles%s into repositories under %s",
        verb,
        len(restored),
        len(bundles),
        f" plus {ROOT_NAME}" if root_done else "",
        destination,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _configure_logging(args)
    if args.command == "collect":
        return _collect(args)
    elif args.command == "restore":
        return _restore(args)
    else:
        raise NotImplementedError("command not implemented")


if __name__ == "__main__":
    raise SystemExit(main())
