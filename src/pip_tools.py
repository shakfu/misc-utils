#!/usr/bin/env python3
"""pip package management and cleanup tools.

This module can be invoked as 'pip_tools' or 'pip_reset' for convenience.
When invoked as 'pip_reset', it shows the extended SKIP list.
"""

import os
import argparse
import subprocess
import sys
from pathlib import Path

# Basic SKIP list - packages essential for pip functionality
SKIP = [
    "Cython",
    "packaging",
    "pip",
    "setuptools",
    "virtualenv",
    "wheel",
]

# Extended SKIP list - additional packages to keep during reset
SKIP_EXTENDED = [
    'build',
    'cffi',
    'Cython',
    'ipython',
    'isort',
    'Jinja2',
    'memray',
    'msgspec',
    'mypy',
    'nanobind',
    'numpy',
    'packaging',
    'pip',
    'pybind11',
    'pydantic',
    'pylint',
    'pytest',
    'PyYAML',
    'radian',
    'rpl',
    'ruff',
    'scipy',
    'setuptools',
    'signalflow',
    'virtualenv',
    'wheel',
]


def print_dot():
    """Print a dot for progress indication."""
    sys.stdout.write(".")
    sys.stdout.flush()


def get_output(cmd: str) -> str:
    """Execute command and return output.

    Args:
        cmd: Command to execute

    Returns:
        Command output as string
    """
    return subprocess.check_output(
        cmd.split(), encoding="utf8", stderr=subprocess.DEVNULL
    )


def get_names(cmd: str) -> list[str]:
    """Get package names from pip command output.

    Args:
        cmd: pip command to execute

    Returns:
        List of package names (excluding SKIP list)
    """
    pkgs = get_output(cmd)
    lines = pkgs.splitlines()
    shortname = ""
    names = [line.split()[0].strip() for line in lines]
    _names = []
    for name in names:
        if "==" in name:
            shortname = name.split("==")[0]
        if name in SKIP or shortname in SKIP or name.startswith("-----"):
            continue
        _names.append(name)
    return _names


def get_required_by(name: str) -> list[str] | None:
    """Get list of packages that require the given package.

    Args:
        name: Package name

    Returns:
        List of package names that require this package, or None on error
    """
    deps = None
    try:
        info = get_output(f"pip show {name}")
        lines = info.splitlines()
        for line in lines:
            if line.startswith("Required-by: "):
                _line = line.replace("Required-by: ", "")
                deps = _line.split(", ") if _line else []
    except subprocess.CalledProcessError as e:
        print(f"Warning: Could not get info for package '{name}'")
    except Exception as e:
        print(f"Error getting info for '{name}': {e}")
    return deps


def clean_deps():
    """Clean up unused dependencies.

    Finds packages that are not required by any other package
    and suggests them for removal.
    """
    required_by = set()
    not_required_by = set()
    singles = set()

    names = get_names("pip list")

    print("Analyzing package dependencies...", file=sys.stderr)
    for name in names:
        req_by_list = get_required_by(name)
        if not req_by_list:
            not_required_by.add(name)
        else:
            required_by.update(set(req_by_list))
        print_dot()

    print(file=sys.stderr)
    for pkg in not_required_by:
        if pkg in required_by:
            continue
        if pkg in SKIP:
            continue
        singles.add(pkg)

    if singles:
        print("Packages not required by others (can be uninstalled):")
        for pkg in sorted(singles):
            print(f"  - {pkg}")
        print()
        print(f"To uninstall all: pip uninstall -y {' '.join(sorted(singles))}")
    else:
        print("No unused packages found.")


def reset_pip():
    """Reset pip to initial state.

    Uninstalls all packages except those in SKIP list.
    """
    names = get_names("pip list --format=freeze --exclude-editable")

    if not names:
        print("No packages to uninstall (only SKIP list packages remain).")
        return

    print(f"Will uninstall {len(names)} packages...")
    for name in names:
        try:
            print(f"Uninstalling {name}...", end=" ")
            subprocess.run(
                ["pip3", "uninstall", "-y", "--break-system-packages", name],
                check=True,
                capture_output=True
            )
            print("✓")
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed: {e}")
        except Exception as e:
            print(f"✗ Error: {e}")

    print(f"\nUninstallation complete. {len(names)} packages processed.")


def show_skip_list():
    """Show the extended SKIP list and reinstall instructions."""
    print("Recommended packages to keep (Extended SKIP list):")
    print()
    for pkg in sorted(SKIP_EXTENDED):
        print(f"  - {pkg}")
    print()
    print("Reset workflow:")
    print()
    print("  1. Reset pip (uninstall all except basic SKIP list):")
    print("     pip_tools --reset")
    print()
    print("  2. Reinstall essential packages:")
    print(f"     pip3 install {' '.join(sorted(SKIP_EXTENDED))}")
    print()
    print("Other commands:")
    print("  pip_tools --clean         # Find unused dependencies")
    print("  pip_tools --show-skip     # Show this help")


def reset_pip2():
    """Reset pip to initial state (alternative method - deprecated)."""
    print("Warning: reset_pip2() is deprecated. Use reset_pip() instead.", file=sys.stderr)
    reset_pip()


def show_info_mode():
    """Info mode when invoked as pip_reset (backward compatibility)."""
    print("=" * 60)
    print("pip_reset - Package Reset Helper")
    print("=" * 60)
    print()
    show_skip_list()


if __name__ == "__main__":
    # Detect if invoked as pip_reset
    invoked_as = Path(sys.argv[0]).name
    is_pip_reset = invoked_as in ['pip_reset', 'pip_reset.py']

    if is_pip_reset:
        # pip_reset mode - show info and SKIP list
        show_info_mode()
    else:
        # Full pip_tools mode with argparse
        parser = argparse.ArgumentParser(
            prog='pip_tools',
            description='pip package management and cleanup tools',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  # Find unused dependencies
  pip_tools --clean
  pip_tools -c

  # Reset pip (uninstall all except SKIP list)
  pip_tools --reset
  pip_tools -r

  # Show extended SKIP list
  pip_tools --show-skip
  pip_reset  # (convenience shortcut)

  # Combine with other commands
  pip_tools --clean && pip uninstall -y package-name
            """
        )

        parser.add_argument(
            "-c", "--clean",
            action="store_true",
            help="Find and suggest removal of unused dependencies"
        )
        parser.add_argument(
            "-r", "--reset",
            action="store_true",
            help="Uninstall all packages except SKIP list"
        )
        parser.add_argument(
            "--show-skip",
            action="store_true",
            help="Show extended SKIP list and reinstall instructions"
        )

        args = parser.parse_args()

        if args.clean:
            clean_deps()
        elif args.reset:
            print("WARNING: This will uninstall all pip packages except:", file=sys.stderr)
            for pkg in SKIP:
                print(f"  - {pkg}", file=sys.stderr)
            print(file=sys.stderr)
            response = input("Continue? [y/N]: ")
            if response.lower() in ['y', 'yes']:
                reset_pip()
            else:
                print("Cancelled.")
        elif args.show_skip:
            show_skip_list()
        else:
            parser.print_help()
