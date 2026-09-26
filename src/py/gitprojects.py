#!/usr/bin/env python3
"""Export git projects to JSON, and clone them back from it.

    gitprojects.py scan ~/src -o projects.json      # local projects
    gitprojects.py github USER -o projects.json     # USER's GitHub repos (needs gh)
    gitprojects.py clone projects.json ~/src

The JSON maps each project name to a clone URL. ``clone`` recreates each
project as ``DEST/<name>`` and skips names that already exist.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


def scan(directory: Path) -> dict[str, str]:
    """Return ``{name: origin_url}`` for each git project directly under *directory*.

    Projects without an ``origin`` remote are reported on stderr and omitted.
    """
    projects: dict[str, str] = {}
    for p in sorted(directory.iterdir()):
        if not (p.is_dir() and (p / ".git").exists()):
            continue
        result = subprocess.run(
            ["git", "-C", str(p), "remote", "get-url", "origin"],
            capture_output=True, text=True,
        )
        url = result.stdout.strip()
        if result.returncode or not url:
            print(f"no origin, skipping: {p.name}", file=sys.stderr)
            continue
        projects[p.name] = url
    return projects


def github(user: str, limit: int, ssh: bool, source: bool,
           no_archived: bool) -> dict[str, str]:
    """Return ``{name: clone_url}`` for *user*'s GitHub repos via ``gh repo list``.

    Raises:
        subprocess.CalledProcessError: if ``gh`` fails, e.g. unknown user or no auth.
    """
    field = "sshUrl" if ssh else "url"
    cmd = ["gh", "repo", "list", user, "--limit", str(limit), "--json", f"name,{field}"]
    if source:
        cmd.append("--source")
    if no_archived:
        cmd.append("--no-archived")
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return {r["name"]: r[field] for r in sorted(json.loads(out), key=lambda r: r["name"])}


def write(projects: dict[str, str], output: Path) -> None:
    """Write *projects* as JSON to *output*, or stdout if it is ``-``."""
    text = json.dumps(projects, indent=2) + "\n"
    if str(output) == "-":
        sys.stdout.write(text)
    else:
        output.write_text(text)


def load(path: Path) -> dict[str, str]:
    """Load and validate a projects file.

    Raises:
        ValueError: if the file is not a ``{name: url}`` object of strings, or
            a name is not a single path component inside the destination.
    """
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object of {name: url}")
    for name, url in data.items():
        if not isinstance(url, str) or not url:
            raise ValueError(f"{name!r}: url must be a non-empty string")
        # Reject names that would clone outside DEST, e.g. "../x" or "/abs".
        if name in ("", ".", "..") or Path(name).name != name:
            raise ValueError(f"{name!r}: not a valid project directory name")
    return data


def clone(projects: dict[str, str], dest: Path) -> list[str]:
    """Clone each project into ``dest/<name>`` unless it exists. Return failed names."""
    dest.mkdir(parents=True, exist_ok=True)
    failed = []
    for name, url in projects.items():
        target = dest / name
        if target.exists():
            print(f"exists, skipping: {name}")
            continue
        print(f"cloning: {name} <- {url}")
        # "--" stops a url beginning with "-" being read as a git option.
        if subprocess.run(["git", "clone", "--", url, str(target)]).returncode:
            failed.append(name)
    return failed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export git projects to JSON, or clone them from it.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="write {name: origin_url} for projects in DIR")
    p_scan.add_argument("directory", type=Path, metavar="DIR")
    p_gh = sub.add_parser("github", help="write {name: clone_url} for USER's GitHub repos")
    p_gh.add_argument("user", metavar="USER", help="GitHub user or organization")
    p_gh.add_argument("-L", "--limit", type=int, default=10000,
                      help="maximum repos to list (default: 10000)")
    p_gh.add_argument("--ssh", action="store_true", help="use SSH clone URLs, not HTTPS")
    p_gh.add_argument("--source", action="store_true", help="omit forks")
    p_gh.add_argument("--no-archived", action="store_true", help="omit archived repos")

    for p in (p_scan, p_gh):
        p.add_argument("-o", "--output", type=Path, default=Path("projects.json"),
                       help="output file, or - for stdout (default: projects.json)")

    p_clone = sub.add_parser("clone", help="clone projects from JSON into DEST")
    p_clone.add_argument("projects", type=Path, metavar="JSON")
    p_clone.add_argument("dest", type=Path, metavar="DEST")

    args = parser.parse_args(argv)

    if args.command == "scan":
        if not args.directory.is_dir():
            parser.error(f"not a directory: {args.directory}")
        write(scan(args.directory), args.output)
        return 0

    if args.command == "github":
        if shutil.which("gh") is None:
            parser.error("github requires the gh CLI: https://cli.github.com")
        try:
            projects = github(args.user, args.limit, args.ssh, args.source, args.no_archived)
        except subprocess.CalledProcessError as e:
            print(f"gh failed: {e.stderr.strip()}", file=sys.stderr)
            return 1
        write(projects, args.output)
        return 0

    try:
        projects = load(args.projects)
    except (OSError, ValueError) as e:  # json.JSONDecodeError is a ValueError
        parser.error(f"{args.projects}: {e}")
    failed = clone(projects, args.dest)
    if failed:
        print(f"failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
