#!/usr/bin/env python3
"""
Version management script for buylog.

Checks version consistency across:
- src/buylog/__init__.py (__version__)
- pyproject.toml (version)
- CHANGELOG.md (first non-Unreleased version header)

Usage:
    python version.py              # Check and display current version
    python version.py bump         # Bump patch version (default)
    python version.py bump patch   # Bump patch version (0.1.8 -> 0.1.9)
    python version.py bump minor   # Bump minor version (0.1.8 -> 0.2.0)
    python version.py bump major   # Bump major version (0.1.8 -> 1.0.0)
    python version.py tag          # Create and push git tag for current version
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

# File paths relative to script location
SCRIPT_DIR = Path(__file__).parent
INIT_FILE = SCRIPT_DIR / "src" / "buylog" / "__init__.py"
PYPROJECT_FILE = SCRIPT_DIR / "pyproject.toml"
CHANGELOG_FILE = SCRIPT_DIR / "CHANGELOG.md"

# Regex patterns
INIT_VERSION_PATTERN = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
PYPROJECT_VERSION_PATTERN = re.compile(r'^version\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
CHANGELOG_VERSION_PATTERN = re.compile(r'^## \[(\d+\.\d+\.\d+)\]', re.MULTILINE)


def get_init_version() -> Optional[str]:
    """Extract version from __init__.py."""
    content = INIT_FILE.read_text()
    match = INIT_VERSION_PATTERN.search(content)
    return match.group(1) if match else None


def get_pyproject_version() -> Optional[str]:
    """Extract version from pyproject.toml."""
    content = PYPROJECT_FILE.read_text()
    match = PYPROJECT_VERSION_PATTERN.search(content)
    return match.group(1) if match else None


def get_changelog_version() -> Optional[str]:
    """Extract first non-Unreleased version from CHANGELOG.md."""
    content = CHANGELOG_FILE.read_text()
    match = CHANGELOG_VERSION_PATTERN.search(content)
    return match.group(1) if match else None


def check_consistency() -> tuple[bool, dict[str, Optional[str]]]:
    """Check if all versions are consistent."""
    versions = {
        "init": get_init_version(),
        "pyproject": get_pyproject_version(),
        "changelog": get_changelog_version(),
    }

    unique_versions = set(v for v in versions.values() if v is not None)
    consistent = len(unique_versions) == 1

    return consistent, versions


def parse_version(version: str) -> tuple[int, int, int]:
    """Parse semver string into tuple."""
    parts = version.split(".")
    return int(parts[0]), int(parts[1]), int(parts[2])


def bump_version(version: str, bump_type: str = "patch") -> str:
    """Bump version according to semver."""
    major, minor, patch = parse_version(version)

    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    else:  # patch
        return f"{major}.{minor}.{patch + 1}"


def update_init_version(new_version: str) -> None:
    """Update version in __init__.py."""
    content = INIT_FILE.read_text()
    new_content = INIT_VERSION_PATTERN.sub(f'__version__ = "{new_version}"', content)
    INIT_FILE.write_text(new_content)


def update_pyproject_version(new_version: str) -> None:
    """Update version in pyproject.toml."""
    content = PYPROJECT_FILE.read_text()
    new_content = PYPROJECT_VERSION_PATTERN.sub(f'version = "{new_version}"', content)
    PYPROJECT_FILE.write_text(new_content)


def update_changelog_version(old_version: str, new_version: str) -> None:
    """Update CHANGELOG.md: move Unreleased content to new version."""
    content = CHANGELOG_FILE.read_text()

    # Replace [Unreleased] section with new version
    # Pattern: ## [Unreleased]\n\n## [old_version]
    # Replace with: ## [Unreleased]\n\n## [new_version]\n\n## [old_version]
    unreleased_pattern = re.compile(
        rf"(## \[Unreleased\])\s*\n\n(## \[{re.escape(old_version)}\])"
    )

    if unreleased_pattern.search(content):
        # There's content under Unreleased that's already been versioned
        # Just update the version number
        new_content = content.replace(f"## [{old_version}]", f"## [{new_version}]", 1)
    else:
        # Standard case: Unreleased has content, need to create new version section
        new_content = content.replace(
            "## [Unreleased]\n",
            f"## [Unreleased]\n\n## [{new_version}]\n",
            1,
        )

    CHANGELOG_FILE.write_text(new_content)


def run_git_command(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command."""
    return subprocess.run(
        ["git"] + args,
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
        check=check,
    )


def create_git_tag(version: str) -> bool:
    """Create git tag for version."""
    tag = f"v{version}"
    try:
        result = run_git_command(["tag", tag])
        if result.returncode == 0:
            print(f"Created tag: {tag}")
            return True
        else:
            print(f"Failed to create tag: {result.stderr}")
            return False
    except subprocess.CalledProcessError as e:
        print(f"Failed to create tag: {e.stderr}")
        return False


def push_git_tag(version: str) -> bool:
    """Push git tag to origin."""
    tag = f"v{version}"
    try:
        result = run_git_command(["push", "origin", tag])
        if result.returncode == 0:
            print(f"Pushed tag: {tag}")
            return True
        else:
            print(f"Failed to push tag: {result.stderr}")
            return False
    except subprocess.CalledProcessError as e:
        print(f"Failed to push tag: {e.stderr}")
        return False


def check_tag_exists(version: str) -> bool:
    """Check if tag already exists."""
    tag = f"v{version}"
    result = run_git_command(["tag", "-l", tag], check=False)
    return tag in result.stdout


def main() -> int:
    """Main entry point."""
    args = sys.argv[1:]

    # Check consistency first
    consistent, versions = check_consistency()

    print("Version Status:")
    print(f"  __init__.py:   {versions['init'] or 'NOT FOUND'}")
    print(f"  pyproject.toml: {versions['pyproject'] or 'NOT FOUND'}")
    print(f"  CHANGELOG.md:   {versions['changelog'] or 'NOT FOUND'}")
    print()

    if not consistent:
        print("ERROR: Versions are inconsistent!")
        return 1

    current_version = versions["init"]
    if not current_version:
        print("ERROR: Could not determine current version")
        return 1

    print(f"Current version: {current_version}")
    print()

    # No args - just display status
    if not args:
        if check_tag_exists(current_version):
            print(f"Tag v{current_version} exists")
        else:
            print(f"Tag v{current_version} does not exist")
        return 0

    command = args[0]

    if command == "bump":
        bump_type = args[1] if len(args) > 1 else "patch"
        if bump_type not in ("major", "minor", "patch"):
            print(f"ERROR: Invalid bump type '{bump_type}'. Use: major, minor, patch")
            return 1

        new_version = bump_version(current_version, bump_type)
        print(f"Bumping {bump_type}: {current_version} -> {new_version}")

        confirm = input("Proceed? [Y/n]: ").strip().lower()
        if confirm and confirm != "y":
            print("Aborted")
            return 0

        update_init_version(new_version)
        update_pyproject_version(new_version)
        update_changelog_version(current_version, new_version)

        print()
        print("Updated files:")
        print(f"  - {INIT_FILE}")
        print(f"  - {PYPROJECT_FILE}")
        print(f"  - {CHANGELOG_FILE}")
        print()
        print(f"New version: {new_version}")
        print()
        print("Next steps:")
        print("  1. Review changes: git diff")
        print("  2. Commit: git add -A && git commit -m 'Bump version to {}'".format(new_version))
        print("  3. Tag: python version.py tag")

        return 0

    elif command == "tag":
        if check_tag_exists(current_version):
            print(f"Tag v{current_version} already exists")
            push_anyway = input("Push existing tag? [y/N]: ").strip().lower()
            if push_anyway == "y":
                return 0 if push_git_tag(current_version) else 1
            return 0

        print(f"Will create and push tag: v{current_version}")
        confirm = input("Proceed? [Y/n]: ").strip().lower()
        if confirm and confirm != "y":
            print("Aborted")
            return 0

        if not create_git_tag(current_version):
            return 1

        push_confirm = input("Push tag to origin? [Y/n]: ").strip().lower()
        if push_confirm and push_confirm != "y":
            print("Tag created but not pushed")
            return 0

        return 0 if push_git_tag(current_version) else 1

    else:
        print(f"Unknown command: {command}")
        print()
        print("Usage:")
        print("  python version.py              # Check version consistency")
        print("  python version.py bump [type]  # Bump version (patch/minor/major)")
        print("  python version.py tag          # Create and push git tag")
        return 1


if __name__ == "__main__":
    sys.exit(main())
