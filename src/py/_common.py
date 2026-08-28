"""_common.py - shared internal utilities for misc-utils scripts.

All functions rely solely on the Python standard library, preserving the
project's zero-external-runtime-dependency constraint.

Modules here are NOT part of any public API and should only be imported by
other scripts within this package.
"""

from __future__ import annotations

import logging
import plistlib
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# ANSI terminal colours
# ---------------------------------------------------------------------------

BOLD_CYAN = "\033[1;36m"
GREEN     = "\033[32m"
YELLOW    = "\033[33m"
RED       = "\033[31m"
RESET     = "\033[0m"

# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------


def shell_output(*cmd: str, timeout: int = 30) -> str:
    """Run *cmd* and return its stdout as a stripped string.

    Raises subprocess.CalledProcessError if the command exits non-zero, and
    subprocess.TimeoutExpired if it does not finish within *timeout* seconds.
    """
    return subprocess.check_output(
        cmd, text=True, timeout=timeout
    ).strip()


# ---------------------------------------------------------------------------
# Human-readable formatting
# ---------------------------------------------------------------------------


def human(num_bytes: float) -> str:
    """Format a byte count as a compact human-readable string (e.g. 1.4MB)."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num_bytes) < 1024 or unit == "GB":
            return f"{num_bytes:.0f}{unit}" if unit == "B" else f"{num_bytes:.1f}{unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f}GB"  # unreachable but satisfies type checkers


def plural(count: int, noun: str, plural_form: str | None = None) -> str:
    """Return *count* with *noun* pluralised appropriately.

    Example::

        plural(1, "file")   -> "1 file"
        plural(3, "file")   -> "3 files"
        plural(3, "person", "people") -> "3 people"
    """
    return f"{count} {noun if count == 1 else (plural_form or noun + 's')}"


# ---------------------------------------------------------------------------
# Webloc / plist helper
# ---------------------------------------------------------------------------


def read_webloc_url(path: Path) -> str | None:
    """Return the URL stored in a ``.webloc`` plist file, or ``None`` on failure."""
    try:
        with path.open("rb") as f:
            url = plistlib.load(f).get("URL")
        return url if isinstance(url, str) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Logging factory
# ---------------------------------------------------------------------------


def configure_logging(
    verbose: bool = False,
    quiet: bool = False,
    name: str = __name__,
) -> logging.Logger:
    """Create and return a logger writing to stderr.

    Level selection:
    - *verbose* -> DEBUG
    - *quiet*   -> WARNING
    - default   -> INFO

    The format is plain ``"%(levelname)s: %(message)s"`` at DEBUG level and
    just ``"%(message)s"`` otherwise, matching the convention used across
    dedupe, shrink, and mover.
    """
    logger = logging.getLogger(name)
    level = logging.DEBUG if verbose else (logging.WARNING if quiet else logging.INFO)
    fmt = "%(levelname)s: %(message)s" if level == logging.DEBUG else "%(message)s"
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(fmt))
    handler.setLevel(level)
    logger.addHandler(handler)
    logger.setLevel(level)
    return logger
