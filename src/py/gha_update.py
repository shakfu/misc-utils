#!/usr/bin/env python3
"""
Update GitHub Actions pins and cibuildwheel version pins to the latest releases.

Scans workflow files for `uses: owner/repo@ref` entries and rewrites each ref to
the latest published release, preserving the pinning style already in use:

    uses: actions/checkout@v4            -> @v5
    uses: actions/checkout@v4.1.7        -> @v5.0.1
    uses: actions/checkout@<sha> # v4.1.7 -> @<new-sha> # v5.0.1

Version pins for cibuildwheel (`cibuildwheel==x.y.z`) are updated from PyPI in
workflows, pyproject.toml, requirements files and similar build config.

Refs that are branches (main, master, ...) and local or docker actions are left
alone and reported as skipped.

A directory argument is one project root and searches are anchored there. Pass
-r to walk a directory of checkouts instead; every project shares one version
cache, so an action looked up for the first repo is free for the rest.

Exit codes: 0 nothing to do or changes written, 1 lookup errors, 2 updates are
available (only with --check).

Examples:
    gha_update.py                       # update the repo in the current directory
    gha_update.py -d ~/src/myproject    # dry run against another checkout
    gha_update.py -r ~/src              # sweep every project under a directory
    gha_update.py --check               # CI gate: fail if anything is stale
    gha_update.py --same-major          # stay within the current major version
    gha_update.py .github/workflows/ci.yml

Set GITHUB_TOKEN (or GH_TOKEN) to raise the GitHub API rate limit from 60 to
5000 requests per hour.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Sequence

# A decoded JSON document, as the GitHub and PyPI endpoints return it.
Json = dict[str, Any] | list[Any]

GITHUB_API = "https://api.github.com"
PYPI_API = "https://pypi.org/pypi"
USER_AGENT = "gha-update/1.0"

# Files searched for `uses:` pins.
WORKFLOW_GLOBS = (
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    ".github/actions/**/action.yml",
    ".github/actions/**/action.yaml",
    "action.yml",
    "action.yaml",
)

# Additional files searched for cibuildwheel version pins. Every glob is
# anchored at the project root: none may reach into a sibling project, or
# pointing the tool at a directory of repositories would update pins in files it
# found while silently missing the workflows next to them.
PIN_GLOBS = (
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "tox.ini",
    "noxfile.py",
    "Makefile",
    "requirements*.txt",
    "requirements/*.txt",
    "azure-pipelines.yml",
    ".cirrus.yml",
    ".travis.yml",
    "appveyor.yml",
)

# Directories never descended into when searching for projects.
PRUNE_DIRS = frozenset(
    {
        "node_modules",
        "__pycache__",
        "site-packages",
        "venv",
        "env",
        "build",
        "dist",
        "target",
        "vendor",
        "third_party",
    }
)

DEFAULT_MAX_DEPTH = 6

# Packages whose `==`/`~=` pins are refreshed from PyPI.
PINNED_PACKAGES = ("cibuildwheel",)

BOLD_CYAN = "\033[1;36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"

USES_RE = re.compile(
    r"""^(?P<prefix>\s*(?:-\s+)?uses:\s*)
         (?P<quote>['"]?)
         (?P<value>[^\s'"#]+)
         (?P=quote)
         (?P<suffix>\s*(?:\#.*)?)$""",
    re.VERBOSE,
)

VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)(?:[-_.]?([A-Za-z][\w.+-]*))?$")

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _package_pin_re(package: str) -> re.Pattern[str]:
    """Match a `package==1.2.3` style requirement pin anywhere in a line."""
    return re.compile(
        r"(?<![\w.-])(?P<name>"
        + re.escape(package)
        + r")(?P<extras>\[[^\]]*\])?(?P<space>\s*)(?P<op>==|~=|>=)(?P<space2>\s*)"
        r"(?P<version>\d[\w.+!-]*)"
    )


# ---------------------------------------------------------------------------
# version helpers
# ---------------------------------------------------------------------------


def parse_version(text: str) -> tuple[tuple[int, ...], str] | None:
    """
    Parse a version-like ref into (numeric components, prerelease suffix).

    Returns None when the text is not a version, e.g. a branch name or a SHA.
    """
    if not text:
        return None
    match = VERSION_RE.match(text.strip())
    if not match:
        return None
    numbers = tuple(int(part) for part in match.group(1).split("."))
    return numbers, match.group(2) or ""


def is_prerelease(text: str) -> bool:
    """Whether a version string carries a prerelease suffix such as rc1."""
    parsed = parse_version(text)
    return bool(parsed and parsed[1])


def version_sort_key(text: str) -> tuple[Any, ...]:
    """Sort key ordering versions numerically, with prereleases before releases."""
    parsed = parse_version(text)
    if parsed is None:
        return ((), 0)
    numbers, pre = parsed
    padded = numbers + (0,) * (4 - len(numbers)) if len(numbers) < 4 else numbers
    return (padded, 0 if pre else 1, pre)


def is_sha(ref: str) -> bool:
    """Whether a ref is a full 40 character commit SHA."""
    return bool(SHA_RE.match(ref))


def target_ref(current: str, latest: str) -> str | None:
    """
    Render `latest` using the pinning granularity of `current`.

    A major-only pin such as v4 stays major-only, v4.1 keeps two components and
    a full pin keeps three. Returns None when either side is not a version, or
    when the current pin is already at or beyond the latest release.
    """
    current_parsed = parse_version(current)
    latest_parsed = parse_version(latest)
    if current_parsed is None or latest_parsed is None:
        return None
    if version_sort_key(current) >= version_sort_key(latest):
        return None

    depth = len(current_parsed[0])
    numbers = latest_parsed[0][:depth]
    rendered = ".".join(str(n) for n in numbers)
    if depth >= len(latest_parsed[0]) and latest_parsed[1]:
        rendered += latest_parsed[1]
    prefix = "v" if current.lstrip().startswith(("v", "V")) else ""
    new_ref = prefix + rendered
    return new_ref if new_ref != current else None


# ---------------------------------------------------------------------------
# parsing and rewriting workflow lines
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UsesRef:
    """A parsed `uses:` entry from a workflow file."""

    repo: str  # owner/name
    subpath: str  # trailing path within the repo, "" when absent
    ref: str  # tag, branch or SHA as written
    comment: str  # trailing comment text without the leading '#'


def parse_uses_line(line: str) -> UsesRef | None:
    """
    Parse a `uses:` line into its parts.

    Returns None for lines that are not `uses:` entries, and for local (./path)
    or docker:// actions which have no release stream to follow.
    """
    match = USES_RE.match(line.rstrip("\r"))
    if not match:
        return None

    value = match.group("value")
    if value.startswith((".", "/")) or "://" in value:
        return None
    if "@" not in value:
        return None

    path, _, ref = value.rpartition("@")
    parts = path.split("/")
    if len(parts) < 2 or not all(parts[:2]):
        return None

    comment = ""
    suffix = match.group("suffix")
    if "#" in suffix:
        comment = suffix.split("#", 1)[1].strip()

    return UsesRef(
        repo="/".join(parts[:2]),
        subpath="/".join(parts[2:]),
        ref=ref,
        comment=comment,
    )


def update_comment(comment: str, new_tag: str) -> str:
    """
    Refresh the version token inside a trailing comment.

    An empty comment becomes the tag; a comment holding a version token has that
    token replaced; anything else is preserved untouched.
    """
    if not comment:
        return new_tag
    tokens = comment.split()
    for index, token in enumerate(tokens):
        if parse_version(token.strip("(),[]")) is not None:
            tokens[index] = token.replace(token.strip("(),[]"), new_tag, 1)
            return " ".join(tokens)
    return comment


def render_uses_line(line: str, new_ref: str, new_comment: str | None = None) -> str:
    """Rewrite a `uses:` line with a new ref and, optionally, a new comment."""
    stripped = line.rstrip("\r")
    carriage = line[len(stripped):]
    match = USES_RE.match(stripped)
    if not match:
        return line

    path = match.group("value").rpartition("@")[0]
    quote = match.group("quote")
    suffix = match.group("suffix")

    if new_comment is not None:
        comment_match = re.match(r"^(\s*)#(\s*)(.*)$", suffix)
        if comment_match:
            spacing = comment_match.group(2) or " "
            suffix = f"{comment_match.group(1)}#{spacing}{new_comment}"
        else:
            suffix = f"  # {new_comment}"

    return f"{match.group('prefix')}{quote}{path}@{new_ref}{quote}{suffix}{carriage}"


# ---------------------------------------------------------------------------
# remote lookups
# ---------------------------------------------------------------------------


class VersionLookupError(Exception):
    """A version lookup failed."""


def http_json(
    url: str, token: str | None = None, timeout: float = 15.0
) -> Json:
    """Fetch and decode a JSON document, raising LookupError_ on failure."""
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            document: Json = json.load(response)
        return document
    except urllib.error.HTTPError as exc:
        if exc.code == 403 and "rate limit" in str(exc.headers).lower():
            raise VersionLookupError(f"{url}: rate limited (set GITHUB_TOKEN)") from exc
        raise VersionLookupError(f"{url}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise VersionLookupError(f"{url}: {exc}") from exc


class VersionSource:
    """
    Resolves latest releases from the GitHub and PyPI APIs.

    Results are memoised so a workflow using the same action repeatedly costs a
    single request.
    """

    def __init__(
        self,
        token: str | None = None,
        allow_prerelease: bool = False,
        fetch: Callable[[str, str | None], Json] | None = None,
    ) -> None:
        self.token = token
        self.allow_prerelease = allow_prerelease
        self._fetch = fetch or (lambda url, tok: http_json(url, tok))
        self._tags: dict[str, str] = {}
        self._shas: dict[tuple[str, str], str] = {}
        self._pypi: dict[str, str] = {}

    def _get(self, url: str) -> Json:
        return self._fetch(url, self.token)

    def latest_tag(self, repo: str) -> str:
        """Latest release tag for an action repository."""
        if repo in self._tags:
            return self._tags[repo]
        try:
            data = self._get(f"{GITHUB_API}/repos/{repo}/releases/latest")
            tag = data.get("tag_name", "") if isinstance(data, dict) else ""
        except VersionLookupError:
            tag = ""
        if not tag or (is_prerelease(tag) and not self.allow_prerelease):
            tag = self._latest_from_tags(repo)
        if not tag:
            raise VersionLookupError(f"{repo}: no released version found")
        self._tags[repo] = tag
        return tag

    def _latest_from_tags(self, repo: str) -> str:
        """Fall back to the tag list for repos without GitHub releases."""
        data = self._get(f"{GITHUB_API}/repos/{repo}/tags?per_page=100")
        names = [item["name"] for item in data if isinstance(item, dict) and "name" in item]
        candidates = [
            name
            for name in names
            if parse_version(name) and (self.allow_prerelease or not is_prerelease(name))
        ]
        return max(candidates, key=version_sort_key, default="")

    def tag_sha(self, repo: str, tag: str) -> str:
        """Commit SHA a tag points at, dereferencing annotated tag objects."""
        key = (repo, tag)
        if key in self._shas:
            return self._shas[key]
        data = self._get(f"{GITHUB_API}/repos/{repo}/git/ref/tags/{tag}")
        obj: dict[str, Any] = data.get("object", {}) if isinstance(data, dict) else {}
        sha: str = obj.get("sha", "")
        if obj.get("type") == "tag" and sha:
            tag_obj = self._get(f"{GITHUB_API}/repos/{repo}/git/tags/{sha}")
            if isinstance(tag_obj, dict):
                sha = tag_obj.get("object", {}).get("sha", sha)
        if not is_sha(sha):
            raise VersionLookupError(f"{repo}: could not resolve {tag} to a commit")
        self._shas[key] = sha
        return sha

    def latest_package(self, package: str) -> str:
        """Latest version of a package on PyPI."""
        if package in self._pypi:
            return self._pypi[package]
        data = self._get(f"{PYPI_API}/{package}/json")
        version = data.get("info", {}).get("version", "") if isinstance(data, dict) else ""
        if not version:
            raise VersionLookupError(f"{package}: no version on PyPI")
        self._pypi[package] = version
        return version


# ---------------------------------------------------------------------------
# updating
# ---------------------------------------------------------------------------


@dataclass
class Change:
    """A single pin that was updated."""

    path: Path
    line_no: int
    name: str
    old: str
    new: str


@dataclass
class Skip:
    """A pin that was deliberately left alone, with the reason why."""

    path: Path
    line_no: int
    name: str
    ref: str
    reason: str


@dataclass
class Result:
    """Outcome of a run."""

    changes: list[Change] = field(default_factory=list)
    skips: list[Skip] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    files_changed: list[Path] = field(default_factory=list)


class Updater:
    """Applies version updates to workflow and build configuration files."""

    def __init__(
        self,
        source: VersionSource,
        same_major: bool = False,
        packages: Sequence[str] = PINNED_PACKAGES,
        only: Sequence[str] | None = None,
    ) -> None:
        self.source = source
        self.same_major = same_major
        self.packages = tuple(packages)
        self.only = tuple(only) if only else ()
        self.result = Result()

    def _selected(self, repo: str) -> bool:
        """Whether a repo is in the --only filter (empty filter selects all)."""
        if not self.only:
            return True
        return any(pattern.lower() in repo.lower() for pattern in self.only)

    def update_uses(self, path: Path, text: str) -> str:
        """Rewrite every updatable `uses:` pin in a workflow file's text."""
        lines = text.split("\n")
        for index, line in enumerate(lines):
            parsed = parse_uses_line(line)
            if parsed is None or not self._selected(parsed.repo):
                continue

            pinned_sha = is_sha(parsed.ref)
            current_version = parsed.comment.split()[0] if pinned_sha and parsed.comment else parsed.ref
            if not pinned_sha and parse_version(parsed.ref) is None:
                self.result.skips.append(
                    Skip(path, index + 1, parsed.repo, parsed.ref, "not a version pin")
                )
                continue

            try:
                latest = self.source.latest_tag(parsed.repo)
            except VersionLookupError as exc:
                self.result.errors.append(str(exc))
                continue

            if self.same_major and not self._same_major(current_version, latest):
                self.result.skips.append(
                    Skip(path, index + 1, parsed.repo, parsed.ref, f"major bump to {latest}")
                )
                continue

            if pinned_sha:
                lines[index] = self._update_sha_pin(path, index, line, parsed, latest)
                continue

            new_ref = target_ref(parsed.ref, latest)
            if new_ref is None:
                continue
            lines[index] = render_uses_line(line, new_ref)
            self.result.changes.append(
                Change(path, index + 1, parsed.repo, parsed.ref, new_ref)
            )
        return "\n".join(lines)

    def _update_sha_pin(
        self, path: Path, index: int, line: str, parsed: UsesRef, latest: str
    ) -> str:
        """Repoint a SHA pin at the latest tag, refreshing its version comment."""
        current_version = parsed.comment.split()[0] if parsed.comment else ""
        if current_version and target_ref(current_version, latest) is None:
            return line
        try:
            sha = self.source.tag_sha(parsed.repo, latest)
        except VersionLookupError as exc:
            self.result.errors.append(str(exc))
            return line
        if sha == parsed.ref:
            return line
        self.result.changes.append(
            Change(
                path,
                index + 1,
                parsed.repo,
                f"{parsed.ref[:12]} ({current_version or 'unknown'})",
                f"{sha[:12]} ({latest})",
            )
        )
        return render_uses_line(line, sha, update_comment(parsed.comment, latest))

    def _same_major(self, current: str, latest: str) -> bool:
        """Whether two versions share a major component."""
        current_parsed = parse_version(current)
        latest_parsed = parse_version(latest)
        if current_parsed is None or latest_parsed is None:
            return True
        return current_parsed[0][:1] == latest_parsed[0][:1]

    def update_pins(self, path: Path, text: str) -> str:
        """Rewrite `package==version` pins for the tracked packages."""
        for package in self.packages:
            pattern = _package_pin_re(package)
            if not pattern.search(text):
                continue
            try:
                latest = self.source.latest_package(package)
            except VersionLookupError as exc:
                self.result.errors.append(str(exc))
                continue

            def replace(
                match: re.Match[str], latest: str = latest, package: str = package
            ) -> str:
                current = match.group("version")
                line_no = text.count("\n", 0, match.start()) + 1
                if match.group("op") == ">=":
                    self.result.skips.append(
                        Skip(path, line_no, package, f">={current}", "lower bound")
                    )
                    return match.group(0)
                if target_ref(current, latest) is None:
                    return match.group(0)
                new_version = target_ref(current, latest) or latest
                self.result.changes.append(
                    Change(path, line_no, package, current, new_version)
                )
                return (
                    f"{match.group('name')}{match.group('extras') or ''}"
                    f"{match.group('space')}{match.group('op')}"
                    f"{match.group('space2')}{new_version}"
                )

            text = pattern.sub(replace, text)
        return text

    def update_text(self, path: Path, text: str, is_workflow: bool) -> str:
        """Apply every update this file is eligible for and return the new text."""
        updated = self.update_uses(path, text) if is_workflow else text
        return self.update_pins(path, updated)


# ---------------------------------------------------------------------------
# file discovery
# ---------------------------------------------------------------------------


def iter_files(root: Path, globs: Iterable[str]) -> Iterator[Path]:
    """Yield existing files under root matching any of the globs, in order."""
    seen: set[Path] = set()
    for pattern in globs:
        for path in sorted(root.glob(pattern)):
            if path.is_file() and path not in seen:
                seen.add(path)
                yield path


def discover(root: Path) -> list[tuple[Path, bool]]:
    """
    Collect the files to process.

    Each entry is (path, is_workflow); workflow files get `uses:` updates in
    addition to package pin updates.
    """
    workflows = list(iter_files(root, WORKFLOW_GLOBS))
    targets: list[tuple[Path, bool]] = [(path, True) for path in workflows]
    workflow_set = set(workflows)
    for path in iter_files(root, PIN_GLOBS):
        if path not in workflow_set:
            targets.append((path, False))
    return targets


def is_project_root(path: Path) -> bool:
    """
    Whether a directory looks like the root of a project.

    A workflow directory is the strongest signal; a git repository counts too,
    so repos carrying only cibuildwheel pins are still found.
    """
    workflows = path / ".github" / "workflows"
    if workflows.is_dir() and any(
        item.suffix in {".yml", ".yaml"} for item in workflows.iterdir()
    ):
        return True
    return (path / ".git").exists()


def find_project_roots(root: Path, max_depth: int = DEFAULT_MAX_DEPTH) -> list[Path]:
    """
    Find project roots at or below a directory.

    Descent stops at each project found, so repositories nested inside another
    checkout (submodules, vendored trees) are left to their own upstream.
    """
    roots: list[Path] = []

    def walk(directory: Path, depth: int) -> None:
        if is_project_root(directory):
            roots.append(directory)
            return
        if depth >= max_depth:
            return
        try:
            entries = sorted(item for item in directory.iterdir() if item.is_dir())
        except OSError as exc:
            print(f"Warning: cannot read {directory}: {exc}", file=sys.stderr)
            return
        for entry in entries:
            if entry.name in PRUNE_DIRS or entry.name.startswith("."):
                continue
            walk(entry, depth + 1)

    walk(root, 0)
    return roots


def targets_from_args(
    paths: Sequence[Path],
    recursive: bool = False,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> list[tuple[Path, bool]]:
    """
    Resolve CLI path arguments into (path, is_workflow) pairs.

    Directories are treated as project roots, or searched for project roots when
    recursive. Files given explicitly are always processed, which is the way to
    reach a pin file living outside the standard layout.
    """
    targets: list[tuple[Path, bool]] = []
    seen: set[Path] = set()

    def add(path: Path, is_workflow: bool) -> None:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            targets.append((path, is_workflow))

    for path in paths:
        if path.is_dir():
            roots = find_project_roots(path, max_depth) if recursive else [path]
            for project in roots:
                for target, is_workflow in discover(project):
                    add(target, is_workflow)
        elif path.is_file():
            add(path, path.suffix in {".yml", ".yaml"})
        else:
            print(f"Warning: {path} does not exist", file=sys.stderr)
    return targets


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def format_report(result: Result, verbose: bool, dry_run: bool) -> str:
    """Render a human readable summary of a run."""
    lines: list[str] = []
    by_file: dict[Path, list[Change]] = {}
    for change in result.changes:
        by_file.setdefault(change.path, []).append(change)

    for path, changes in by_file.items():
        lines.append(f"\n{BOLD_CYAN}{path}{RESET}")
        for change in changes:
            lines.append(
                f"  line {change.line_no}: {change.name}  "
                f"{change.old} {GREEN}->{RESET} {change.new}"
            )

    if verbose and result.skips:
        lines.append(f"\n{YELLOW}Skipped{RESET}")
        for skip in result.skips:
            lines.append(
                f"  {skip.path}:{skip.line_no}: {skip.name}@{skip.ref} ({skip.reason})"
            )

    if result.errors:
        lines.append(f"\n{YELLOW}Errors{RESET}")
        for error in sorted(set(result.errors)):
            lines.append(f"  {error}")

    if not result.changes:
        lines.append("\nEverything is already up to date.")
    else:
        verb = "would update" if dry_run else "updated"
        lines.append(
            f"\n{verb.capitalize()} {len(result.changes)} pin(s) "
            f"in {len(by_file)} file(s)."
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Update GitHub Actions and cibuildwheel pins to the latest versions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[Path(".")],
        help="Repository roots or specific files (default: current directory)",
    )
    parser.add_argument(
        "-d", "--dry-run",
        action="store_true",
        help="Show what would change without writing files",
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Search each directory for project roots instead of treating it as one",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=DEFAULT_MAX_DEPTH,
        metavar="N",
        help=f"How deep --recursive searches (default: {DEFAULT_MAX_DEPTH})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit 2 if any pin is out of date",
    )
    parser.add_argument(
        "--same-major",
        action="store_true",
        help="Do not cross major version boundaries",
    )
    parser.add_argument(
        "--only",
        action="append",
        metavar="SUBSTRING",
        help="Only update actions whose repo matches (repeatable)",
    )
    parser.add_argument(
        "--package",
        action="append",
        metavar="NAME",
        help=f"Package pins to refresh from PyPI (default: {', '.join(PINNED_PACKAGES)})",
    )
    parser.add_argument(
        "--pre",
        action="store_true",
        help="Consider prerelease versions",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Also report skipped pins",
    )
    return parser


def main(argv: Sequence[str] | None = None, source: VersionSource | None = None) -> int:
    args = build_parser().parse_args(argv)
    dry_run = args.dry_run or args.check

    targets = targets_from_args(args.paths, args.recursive, args.max_depth)
    if not targets:
        hint = "" if args.recursive else " (use -r to search for projects)"
        print(
            f"No workflow or build configuration files found{hint}.",
            file=sys.stderr,
        )
        return 1

    if source is None:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        source = VersionSource(token=token, allow_prerelease=args.pre)

    updater = Updater(
        source,
        same_major=args.same_major,
        packages=args.package or PINNED_PACKAGES,
        only=args.only,
    )

    pending: list[tuple[Path, str]] = []
    for path, is_workflow in targets:
        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            updater.result.errors.append(f"{path}: {exc}")
            continue
        updated = updater.update_text(path, original, is_workflow)
        if updated != original:
            updater.result.files_changed.append(path)
            pending.append((path, updated))

    if not dry_run:
        for path, content in pending:
            try:
                path.write_text(content, encoding="utf-8")
            except OSError as exc:
                updater.result.errors.append(f"{path}: {exc}")

    print(format_report(updater.result, args.verbose, dry_run))

    if updater.result.errors:
        return 1
    if args.check and updater.result.changes:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
