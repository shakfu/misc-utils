#!/usr/bin/env python3
"""
Check git status of all project folders in a directory.
Reports only projects with uncommitted, staged, or untracked changes.
"""

import argparse
import subprocess
import sys
from pathlib import Path

# ANSI color codes
BOLD_CYAN = "\033[1;36m"
RESET = "\033[0m"


def is_git_repo(path: Path) -> bool:
    """Check if a directory is a git repository."""
    return (path / ".git").exists()


def get_git_status(repo_path: Path) -> dict:
    """
    Get git status for a repository.
    Returns dict with status info or None if not a git repo.
    """
    if not is_git_repo(repo_path):
        return None

    result = {
        "path": repo_path,
        "staged": [],
        "modified": [],
        "untracked": [],
        "has_changes": False,
    }

    try:
        # Get porcelain status for easy parsing
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if proc.returncode != 0:
            return None

        for line in proc.stdout.splitlines():
            if not line:
                continue

            index_status = line[0]
            worktree_status = line[1]
            filename = line[3:]

            # Staged changes (index has modifications)
            if index_status in "MADRC":
                result["staged"].append(filename)

            # Modified in worktree but not staged
            if worktree_status == "M":
                result["modified"].append(filename)

            # Untracked files
            if index_status == "?" and worktree_status == "?":
                result["untracked"].append(filename)

        result["has_changes"] = bool(
            result["staged"] or result["modified"] or result["untracked"]
        )

    except subprocess.TimeoutExpired:
        print(f"Warning: timeout checking {repo_path}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Warning: error checking {repo_path}: {e}", file=sys.stderr)
        return None

    return result


def format_status(status: dict) -> str:
    """Format status dict into readable output."""
    lines = [f"\n{BOLD_CYAN}{status['path']}{RESET}"]

    if status["staged"]:
        lines.append(f"  Staged ({len(status['staged'])}):")
        for f in status["staged"][:5]:
            lines.append(f"    {f}")
        if len(status["staged"]) > 5:
            lines.append(f"    ... and {len(status['staged']) - 5} more")

    if status["modified"]:
        lines.append(f"  Modified ({len(status['modified'])}):")
        for f in status["modified"][:5]:
            lines.append(f"    {f}")
        if len(status["modified"]) > 5:
            lines.append(f"    ... and {len(status['modified']) - 5} more")

    if status["untracked"]:
        lines.append(f"  Untracked ({len(status['untracked'])}):")
        for f in status["untracked"][:5]:
            lines.append(f"    {f}")
        if len(status["untracked"]) > 5:
            lines.append(f"    ... and {len(status['untracked']) - 5} more")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Check git status of project folders in a directory"
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Directory containing project folders",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Only show folder names, not details",
    )
    args = parser.parse_args()

    if not args.directory.is_dir():
        print(f"Error: {args.directory} is not a directory", file=sys.stderr)
        sys.exit(1)

    dirty_repos = []

    for entry in sorted(args.directory.iterdir()):
        if not entry.is_dir():
            continue

        status = get_git_status(entry)
        if status and status["has_changes"]:
            dirty_repos.append(status)

    if not dirty_repos:
        print("All repositories are clean.")
        return

    print(f"Found {len(dirty_repos)} repository(ies) with changes:")

    for status in dirty_repos:
        if args.quiet:
            print(f"{BOLD_CYAN}{status['path'].name}{RESET}")
        else:
            print(format_status(status))


if __name__ == "__main__":
    main()
