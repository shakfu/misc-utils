#!/usr/bin/env python3
"""dedupe - reclaim disk space on APFS by cloning duplicates and thinning fat binaries.

The tool runs in two halves that can be used separately.

``scan`` walks the given roots and records two kinds of waste: files whose
contents are byte-for-byte identical, and universal (fat) Mach-O binaries that
carry architectures this machine cannot run. Everything found is written to a
JSON plan, as one ``items`` array ordered by how many bytes each entry can
recover, largest first.

``apply`` consumes that plan. Universal binaries are thinned first, by handing
them to ``shrink.py``; duplicates are then collapsed with ``cp -c``, which asks
APFS to clone the file so both paths share the same blocks until one of them is
written to. Doing it in that order matters: thinning rewrites a file, so a clone
created first would be broken apart again moments later.

Safety notes
------------
A plan is a snapshot, and the filesystem moves underneath it. Rather than trust
the recorded digests, ``apply`` re-hashes every member of a group immediately
before touching anything and requires them to still be identical to each other;
the recorded digest is only a hint. This is also what lets thinning run first -
two identical fat binaries thin to two identical thin binaries, which no longer
match the plan but still match each other.

Nothing is overwritten in place. Each clone is made under a temporary name
beside its destination, checked, given the destination's original permissions,
ownership, timestamps and flags, and only then moved over the destination with
an atomic rename. An interrupted run leaves every original intact.

Files with more than one hard link are never used as a destination: replacing
one would silently detach it from the rest of its link group. Symlinks, special
files and anything smaller than one allocation block are ignored, the last
because cloning cannot recover a fraction of a block.

Extended attributes are inherited from the source of a clone, not the
destination, so a destination's own xattrs (a quarantine flag, for instance) do
not survive the swap.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import logging
import os
import re
import stat as statmod
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import shrink  # noqa: E402  (sibling script; path fixed up above)

LOG = logging.getLogger("dedupe")

PLAN_VERSION = 1

DUPLICATE = "duplicate"
UNIVERSAL = "universal"

# APFS allocates in 4 KiB blocks, so cloning anything smaller recovers nothing.
DEFAULT_MIN_SIZE = 4096

# Bytes read for the cheap pre-filter that separates same-size files before
# any of them is hashed in full.
PARTIAL_BYTES = 65536

# Volume-level bookkeeping that belongs to macOS rather than to the user. It is
# large, it churns, and rewriting any of it is a bad idea.
DEFAULT_EXCLUDES = (
    ".DocumentRevisions-V100",
    ".fseventsd",
    ".Spotlight-V100",
    ".TemporaryItems",
    ".Trashes",
    ".vol",
)

# Directory suffixes that make a directory a bundle. A binary inside one is
# handed to shrink as part of its bundle, so the code signature is checked
# against the whole bundle rather than against a fragment of it.
BUNDLE_SUFFIXES = tuple(
    s for s in shrink.DEFAULT_ENDINGS if s not in (".dylib", ".so", ".a")
)

human = shrink.human
plural = shrink.plural


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    """One regular file seen during the walk."""

    path: Path
    dev: int
    ino: int
    size: int
    nlink: int


def excluded(name: str, path: Path, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(str(path), p) for p in patterns)


def walk(roots: list[Path], patterns: tuple[str, ...]) -> list[Entry]:
    """Collect regular files under *roots*, never following symlinks.

    Directories are visited at most once per device/inode pair, so a tree that
    is reachable by more than one path is not scanned twice.
    """
    entries: list[Entry] = []
    seen_dirs: set[tuple[int, int]] = set()
    stack: list[Path] = []

    def add_file(path: Path, stat: os.stat_result) -> None:
        entries.append(
            Entry(path=path, dev=stat.st_dev, ino=stat.st_ino, size=stat.st_size,
                  nlink=stat.st_nlink)
        )

    for root in roots:
        try:
            stat = root.lstat()
        except OSError as exc:
            LOG.error("cannot read %s: %s", root, exc)
            continue
        if statmod.S_ISLNK(stat.st_mode):
            LOG.info("skipping %s: is a symlink", root)
        elif statmod.S_ISDIR(stat.st_mode):
            stack.append(root)
        elif statmod.S_ISREG(stat.st_mode):
            add_file(root, stat)
        else:
            LOG.info("skipping %s: not a regular file or directory", root)

    while stack:
        directory = stack.pop()
        try:
            listing = list(os.scandir(directory))
        except OSError as exc:
            LOG.debug("%s: cannot list (%s)", directory, exc)
            continue
        for item in listing:
            path = Path(item.path)
            if excluded(item.name, path, patterns):
                LOG.debug("%s: excluded", path)
                continue
            try:
                if item.is_symlink():
                    continue
                stat = item.stat(follow_symlinks=False)
            except OSError as exc:
                LOG.debug("%s: cannot stat (%s)", path, exc)
                continue
            if item.is_dir(follow_symlinks=False):
                key = (stat.st_dev, stat.st_ino)
                if key not in seen_dirs:
                    seen_dirs.add(key)
                    stack.append(path)
            elif statmod.S_ISREG(stat.st_mode):
                add_file(path, stat)
    return entries


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


def digest(path: Path, limit: int | None = None) -> str | None:
    """BLAKE2b of *path*, or of its first *limit* bytes. None if unreadable."""
    hasher = hashlib.blake2b(digest_size=32)
    try:
        with open(path, "rb") as handle:
            if limit is None:
                while chunk := handle.read(1 << 20):
                    hasher.update(chunk)
            else:
                remaining = limit
                while remaining > 0 and (chunk := handle.read(min(1 << 20, remaining))):
                    hasher.update(chunk)
                    remaining -= len(chunk)
    except OSError as exc:
        LOG.debug("%s: cannot hash (%s)", path, exc)
        return None
    return hasher.hexdigest()


@dataclass
class DupGroup:
    """Files on one device with identical contents."""

    digest: str
    size: int
    device: int
    members: list[Path]           # one per distinct inode, sorted
    linked: dict[str, list[str]] = field(default_factory=dict)  # member -> hard links to it

    @property
    def reclaimable(self) -> int:
        return self.size * max(0, len(self.members) - 1)


def _sort_key(path: Path) -> tuple[int, str]:
    return (len(path.parts), str(path))


def find_duplicates(entries: list[Entry], min_size: int) -> list[DupGroup]:
    """Group identical files, cheapest test first: size, then head, then whole file.

    Hard links are collapsed to their inode before anything is hashed - they
    already share storage, so a group of nothing but links to one inode is not
    a duplicate at all.
    """
    by_size: dict[tuple[int, int], list[Entry]] = {}
    for entry in entries:
        if entry.size >= min_size:
            by_size.setdefault((entry.dev, entry.size), []).append(entry)

    candidates = [group for group in by_size.values() if len(group) > 1]
    LOG.debug("%s share a size with at least one other file",
              plural(sum(len(g) for g in candidates), "file"))

    groups: list[DupGroup] = []
    for same_size in candidates:
        by_inode: dict[int, list[Entry]] = {}
        for entry in same_size:
            by_inode.setdefault(entry.ino, []).append(entry)
        if len(by_inode) < 2:
            continue  # every path here is a hard link to the same inode

        unique = [min(links, key=lambda e: _sort_key(e.path)) for links in by_inode.values()]
        size = unique[0].size
        device = unique[0].dev

        buckets: list[list[Entry]] = [unique]
        if size > PARTIAL_BYTES:
            partial: dict[str, list[Entry]] = {}
            for entry in unique:
                head = digest(entry.path, PARTIAL_BYTES)
                if head is not None:
                    partial.setdefault(head, []).append(entry)
            buckets = [b for b in partial.values() if len(b) > 1]

        for bucket in buckets:
            if len(bucket) < 2:
                continue
            full: dict[str, list[Entry]] = {}
            for entry in bucket:
                whole = digest(entry.path)
                if whole is not None:
                    full.setdefault(whole, []).append(entry)
            for value, matched in full.items():
                if len(matched) < 2:
                    continue
                members = sorted((e.path for e in matched), key=_sort_key)
                linked = {
                    str(e.path): sorted(str(p.path) for p in by_inode[e.ino] if p.path != e.path)
                    for e in matched if e.nlink > 1
                }
                groups.append(DupGroup(digest=value, size=size, device=device,
                                       members=members,
                                       linked={k: v for k, v in linked.items() if v}))
    return groups


# ---------------------------------------------------------------------------
# Universal binaries
# ---------------------------------------------------------------------------


@dataclass
class FatFile:
    path: Path
    size: int
    slices: tuple[shrink.Slice, ...]
    target: Path  # what shrink is asked to thin: the enclosing bundle, or the file

    def native_bytes(self, arch: str) -> int:
        matching = [s.size for s in self.slices if s.family == arch or s.arch == arch]
        return min(matching) if matching else 0

    def reclaimable(self, arch: str) -> int:
        keep = self.native_bytes(arch)
        return max(0, self.size - keep) if keep else 0


def bundle_for(path: Path, roots: list[Path]) -> Path | None:
    """The outermost bundle directory containing *path*, if it lies under a root.

    A binary is thinned as part of its bundle so that shrink validates the code
    signature of the whole bundle. A bundle that starts above every scan root is
    ignored, because the caller did not ask for anything outside those roots.
    """
    found: Path | None = None
    for parent in reversed(path.parents):  # outermost first
        if parent.name.endswith(BUNDLE_SUFFIXES):
            found = parent
            break
    if found is None:
        return None
    if any(found == root or root in found.parents for root in roots):
        return found
    return None


def find_universal(entries: list[Entry], roots: list[Path]) -> list[FatFile]:
    """Every fat Mach-O under the roots, with the shrink target it belongs to."""
    fat: list[FatFile] = []
    for entry in entries:
        if entry.size < 8:
            continue
        macho = shrink.inspect_macho(entry.path, entry.size)
        if macho is None or not macho.is_fat:
            continue
        target = bundle_for(entry.path, roots) or entry.path
        fat.append(FatFile(path=entry.path, size=entry.size, slices=macho.slices, target=target))
    return fat


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

# One entry of the plan, and the plan itself. Both are plain JSON documents,
# so their values are heterogeneous by construction.
Item = dict[str, Any]
Plan = dict[str, Any]


def build_items(
    groups: list[DupGroup], fat: list[FatFile], arch: str
) -> list[Item]:
    """One list of everything worth doing, biggest recovery first.

    A file can appear in both halves of the plan - two copies of the same fat
    binary are a duplicate group and two binaries to thin. Since thinning runs
    first, such a group is credited only with what the *thinned* copies will
    save, so the two estimates do not claim the same bytes twice.
    """
    thinned_size = {str(b.path): b.native_bytes(arch) for b in fat if b.native_bytes(arch)}

    items: list[Item] = []
    for group in groups:
        # A member that carries hard links can never be a destination, so it is
        # promoted to be the source instead of being skipped later.
        members = list(group.members)
        pinned = [p for p in members if str(p) in group.linked]
        if pinned:
            lead = min(pinned, key=_sort_key)
            members = [lead] + [p for p in members if p != lead]
        keep, *replace = members
        after_thinning = [thinned_size.get(str(p)) for p in group.members]
        thinned = [s for s in after_thinning if s is not None]
        size = min(thinned) if len(thinned) == len(after_thinning) else group.size
        items.append({
            "kind": DUPLICATE,
            "size_bytes": group.size,
            "reclaimable_bytes": size * max(0, len(group.members) - 1),
            "count": len(group.members),
            "digest": group.digest,
            "device": group.device,
            "keep": str(keep),
            "replace": [str(p) for p in replace],
            "hard_links": group.linked,
        })
    for binary in fat:
        items.append({
            "kind": UNIVERSAL,
            "size_bytes": binary.size,
            "reclaimable_bytes": binary.reclaimable(arch),
            "path": str(binary.path),
            "target": str(binary.target),
            "archs": sorted({s.arch for s in binary.slices}),
            "keep_arch": arch,
            "has_native_slice": binary.native_bytes(arch) > 0,
        })
    items.sort(key=lambda i: (-i["reclaimable_bytes"], -i["size_bytes"],
                              i.get("keep") or i.get("path", "")))
    return items


def build_plan(roots: list[Path], arch: str, entries: list[Entry],
               items: list[Item], min_size: int) -> Plan:
    duplicate_bytes = sum(i["reclaimable_bytes"] for i in items if i["kind"] == DUPLICATE)
    binary_bytes = sum(i["reclaimable_bytes"] for i in items if i["kind"] == UNIVERSAL)
    return {
        "version": PLAN_VERSION,
        "tool": "dedupe",
        "roots": [str(r) for r in roots],
        "arch": arch,
        "min_size_bytes": min_size,
        "scanned": {"files": len(entries), "bytes": sum(e.size for e in entries)},
        "totals": {
            "duplicate_reclaimable_bytes": duplicate_bytes,
            "binary_reclaimable_bytes": binary_bytes,
            "reclaimable_bytes": duplicate_bytes + binary_bytes,
        },
        "items": items,
    }


def write_plan(plan: Plan, destination: Path) -> None:
    if str(destination) == "-":
        json.dump(plan, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return
    destination.write_text(json.dumps(plan, indent=2) + "\n")


def load_plan(source: Path) -> Plan:
    text = sys.stdin.read() if str(source) == "-" else source.read_text()
    plan = json.loads(text)
    if not isinstance(plan, dict) or "items" not in plan:
        raise ValueError("not a dedupe plan: no 'items' array")
    version = plan.get("version")
    if version != PLAN_VERSION:
        raise ValueError(f"plan version {version} is not supported (expected {PLAN_VERSION})")
    return plan


# ---------------------------------------------------------------------------
# Volumes
# ---------------------------------------------------------------------------


_MOUNT_LINE = re.compile(r"^(?P<device>\S+) on (?P<point>.+?) \((?P<options>[^)]*)\)\s*$")


def mount_table() -> list[tuple[str, str]]:
    """(mount point, filesystem type) pairs, longest mount point first."""
    try:
        proc = subprocess.run(["/sbin/mount"], capture_output=True, text=True, check=False)
    except OSError as exc:
        LOG.debug("cannot run mount (%s)", exc)
        return []
    table = []
    for line in proc.stdout.splitlines():
        match = _MOUNT_LINE.match(line)
        if match:
            fstype = match.group("options").split(",")[0].strip()
            table.append((match.group("point"), fstype))
    return sorted(table, key=lambda row: len(row[0]), reverse=True)


def filesystem_of(path: Path, table: list[tuple[str, str]]) -> str | None:
    """The filesystem type holding *path*, or None if it cannot be determined."""
    resolved = str(path.resolve())
    for point, fstype in table:
        if resolved == point or resolved.startswith(point.rstrip("/") + "/"):
            return fstype
    return None


# ---------------------------------------------------------------------------
# Applying the plan
# ---------------------------------------------------------------------------

CLONED = "cloned"
THINNED = "thinned"
SKIPPED = "skipped"
PLANNED = "planned"
FAILED = "failed"


@dataclass
class Action:
    kind: str
    target: str
    status: str
    reason: str
    saved: int = 0


def copy_metadata(source_stat: os.stat_result, destination: Path) -> None:
    """Give *destination* the identity the file it is about to replace had."""
    os.chmod(destination, statmod.S_IMODE(source_stat.st_mode))
    os.utime(destination, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
    try:
        os.chown(destination, source_stat.st_uid, source_stat.st_gid)
    except OSError as exc:
        LOG.debug("%s: cannot restore ownership (%s)", destination, exc)
    flags = getattr(source_stat, "st_flags", 0)
    if flags:
        # chflags is BSD/macOS only; absent when this runs elsewhere.
        chflags = getattr(os, "chflags", None)
        try:
            if chflags is not None:
                chflags(destination, flags)
        except OSError as exc:
            LOG.debug("%s: cannot restore flags (%s)", destination, exc)


def clone_file(source: Path, destination: Path, verify: bool,
               expected: str | None) -> tuple[bool, str]:
    """Replace *destination* with an APFS clone of *source*.

    The clone is built beside the destination and swapped in atomically, so the
    destination is either the file it was or a verified copy of the source, and
    never a half-written thing in between.
    """
    try:
        original = destination.lstat()
    except OSError as exc:
        return False, f"cannot stat destination: {exc}"

    scratch = destination.with_name(f".{destination.name}.dedupe-{os.getpid()}")
    if scratch.exists() or scratch.is_symlink():
        try:
            scratch.unlink()
        except OSError as exc:
            return False, f"cannot clear scratch file {scratch.name}: {exc}"

    proc = subprocess.run(["cp", "-c", "--", str(source), str(scratch)],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout).strip() or f"cp exited {proc.returncode}"
        _remove(scratch)
        return False, message
    if not scratch.exists():
        return False, "cp reported success but produced no file"

    cloned_size = scratch.lstat().st_size
    if cloned_size != original.st_size:
        _remove(scratch)
        return False, f"clone is {human(cloned_size)}, expected {human(original.st_size)}"
    if verify and expected is not None and digest(scratch) != expected:
        _remove(scratch)
        return False, "clone does not match the content it replaces"

    try:
        copy_metadata(original, scratch)
        os.replace(scratch, destination)
    except OSError as exc:
        _remove(scratch)
        return False, f"cannot swap in the clone: {exc}"
    return True, ""


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def current_digests(paths: list[Path]) -> dict[Path, str | None]:
    return {path: digest(path) for path in paths}


def apply_duplicate(item: Item, dry_run: bool, verify: bool) -> list[Action]:
    """Clone one duplicate group, after proving its members are still identical."""
    keep = Path(item["keep"])
    replace = [Path(p) for p in item["replace"]]
    actions: list[Action] = []

    try:
        keep_stat = keep.lstat()
    except OSError as exc:
        return [Action(DUPLICATE, str(keep), FAILED, f"source is gone: {exc}")]

    # The size recorded in the plan is only a label: thinning legitimately
    # changes it moments earlier in this same run. What has to hold is that the
    # files are identical to each other right now, at their current size.
    size = keep_stat.st_size
    reference = digest(keep)
    if reference is None:
        return [Action(DUPLICATE, str(keep), FAILED, "source cannot be read")]

    for destination in replace:
        name = str(destination)
        try:
            stat = destination.lstat()
        except OSError as exc:
            actions.append(Action(DUPLICATE, name, SKIPPED, f"no longer present: {exc}"))
            continue
        if statmod.S_ISLNK(stat.st_mode) or not statmod.S_ISREG(stat.st_mode):
            actions.append(Action(DUPLICATE, name, SKIPPED, "no longer a regular file"))
            continue
        if (stat.st_dev, stat.st_ino) == (keep_stat.st_dev, keep_stat.st_ino):
            actions.append(Action(DUPLICATE, name, SKIPPED,
                                  "already the same file as the source"))
            continue
        if stat.st_dev != keep_stat.st_dev:
            actions.append(Action(DUPLICATE, name, SKIPPED,
                                  "on a different volume; cloning cannot cross volumes"))
            continue
        if stat.st_nlink > 1:
            actions.append(Action(DUPLICATE, name, SKIPPED,
                                  f"has {stat.st_nlink} hard links; replacing it would "
                                  "detach it from the others"))
            continue
        if digest(destination) != reference:
            actions.append(Action(DUPLICATE, name, SKIPPED,
                                  "contents differ from the source now; the plan is stale"))
            continue
        if dry_run:
            actions.append(Action(DUPLICATE, name, PLANNED,
                                  f"would be cloned from {keep}", saved=size))
            continue
        ok, message = clone_file(keep, destination, verify, reference)
        if ok:
            actions.append(Action(DUPLICATE, name, CLONED, f"cloned from {keep}", saved=size))
        else:
            actions.append(Action(DUPLICATE, name, FAILED, message))
    return actions


def apply_universal(targets: list[Path], arch: str, dry_run: bool,
                    check_signature: bool) -> list[Action]:
    actions: list[Action] = []
    for target in targets:
        result = shrink.process(target, arch, in_place=True, dry_run=dry_run,
                                check_signature=check_signature)
        status = {
            shrink.THINNED: THINNED,
            shrink.PLANNED: PLANNED,
            shrink.SKIPPED: SKIPPED,
            shrink.FAILED: FAILED,
        }[result.status]
        actions.append(Action(UNIVERSAL, str(target), status, result.reason,
                              saved=result.saved))
        if status in (THINNED, PLANNED):
            LOG.info("  %s: %s (%s)", status, target, result.detail or result.reason)
        elif status == SKIPPED:
            LOG.debug("  skipped %s: %s", target, result.reason)
        else:
            LOG.error("  failed %s: %s", target, result.reason)
    return actions


def unique_targets(items: list[Item]) -> list[Path]:
    """Shrink targets in plan order, each named once."""
    ordered: list[Path] = []
    seen: set[str] = set()
    for item in items:
        if item["kind"] != UNIVERSAL or not item.get("has_native_slice", True):
            continue
        target = item["target"]
        if target not in seen:
            seen.add(target)
            ordered.append(Path(target))
    return ordered


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def report_plan(plan: Plan, limit: int) -> None:
    items = plan["items"]
    totals = plan["totals"]
    scanned = plan["scanned"]
    LOG.info("scanned %s holding %s", plural(scanned["files"], "file"), human(scanned["bytes"]))
    duplicates = [i for i in items if i["kind"] == DUPLICATE]
    binaries = [i for i in items if i["kind"] == UNIVERSAL]
    LOG.info("%s of duplicates (%s) and %s carrying foreign architectures (%s)",
             plural(len(duplicates), "group"), human(totals["duplicate_reclaimable_bytes"]),
             plural(len(binaries), "universal binary", "universal binaries"),
             human(totals["binary_reclaimable_bytes"]))
    for item in items[:limit]:
        if item["kind"] == DUPLICATE:
            LOG.info("  %8s  %s copies of %s",
                     human(item["reclaimable_bytes"]), item["count"], item["keep"])
        else:
            LOG.info("  %8s  %s [%s] -> %s",
                     human(item["reclaimable_bytes"]), item["path"],
                     ",".join(item["archs"]), item["keep_arch"])
    if len(items) > limit:
        LOG.info("  ... and %d more", len(items) - limit)
    LOG.info("total recoverable: %s", human(totals["reclaimable_bytes"]))


def summarize(actions: list[Action], elapsed: float) -> None:
    counts = {status: sum(1 for a in actions if a.status == status)
              for status in (CLONED, THINNED, PLANNED, SKIPPED, FAILED)}
    saved = sum(a.saved for a in actions if a.status in (CLONED, THINNED, PLANNED))
    parts = []
    if counts[PLANNED]:
        parts.append(f"{counts[PLANNED]} would be changed")
    if counts[CLONED]:
        parts.append(f"{counts[CLONED]} cloned")
    if counts[THINNED]:
        parts.append(f"{counts[THINNED]} thinned")
    parts += [f"{counts[SKIPPED]} skipped", f"{counts[FAILED]} failed"]
    verb = "recoverable" if counts[PLANNED] else "recovered"
    LOG.info("done in %.2fs: %s, %s %s", elapsed, ", ".join(parts), human(saved), verb)
    for action in actions:
        if action.status == FAILED:
            LOG.warning("  left unchanged: %s (%s)", action.target, action.reason)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def configure_logging(verbose: int, quiet: bool) -> None:
    level = logging.WARNING if quiet else (logging.DEBUG if verbose else logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        "%(levelname)s %(message)s" if level == logging.DEBUG else "%(message)s"))
    handler.setLevel(level)
    for existing in list(LOG.handlers):
        LOG.removeHandler(existing)
    LOG.setLevel(level)
    LOG.addHandler(handler)
    for existing in list(shrink.LOG.handlers):
        shrink.LOG.removeHandler(existing)
    shrink.LOG.setLevel(level)
    shrink.LOG.addHandler(handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dedupe",
        description="Find duplicate files and universal binaries, then reclaim the space "
                    "with APFS clones and by thinning binaries to this machine's architecture.",
    )
    parser.add_argument("--verbose", "-v", action="count", default=0, help="per-file detail")
    parser.add_argument("--quiet", "-q", action="store_true", help="warnings and errors only")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_scan_options(target: argparse.ArgumentParser) -> None:
        target.add_argument("roots", nargs="*", default=["."],
                            help="directories or files to scan (default: the current directory)")
        target.add_argument("--min-size", type=int, default=DEFAULT_MIN_SIZE,
                            help=f"ignore files smaller than this many bytes "
                                 f"(default: {DEFAULT_MIN_SIZE}, one APFS block)")
        target.add_argument("--exclude", action="append", default=[],
                            help="glob matched against each name and full path (repeatable)")
        target.add_argument("--arch", help="architecture to keep (default: this machine's)")
        target.add_argument("--no-duplicates", action="store_true",
                            help="do not look for duplicate files")
        target.add_argument("--no-binaries", action="store_true",
                            help="do not look for universal binaries")
        target.add_argument("--top", type=int, default=20,
                            help="entries to print from the plan (default: 20)")

    def add_apply_options(target: argparse.ArgumentParser) -> None:
        target.add_argument("--dry-run", "-n", action="store_true",
                            help="report what would change without writing anything")
        target.add_argument("--no-verify", action="store_true",
                            help="skip re-reading each clone after it is made")
        target.add_argument("--no-verify-signature", action="store_true",
                            help="skip shrink's codesign check on validly signed bundles")
        target.add_argument("--keep-going", "-k", action="store_true",
                            help="continue after a failure (default: stop)")
        target.add_argument("--force", action="store_true",
                            help="proceed even if the volume does not report itself as APFS")

    scan = sub.add_parser("scan", help="write a JSON plan of what could be reclaimed")
    add_scan_options(scan)
    scan.add_argument("--output", "-o", default="dedupe-plan.json",
                      help="where to write the plan, or - for stdout "
                           "(default: dedupe-plan.json)")

    apply_cmd = sub.add_parser("apply", help="carry out a plan written by scan")
    apply_cmd.add_argument("plan", nargs="?", default="dedupe-plan.json",
                           help="plan to read, or - for stdin (default: dedupe-plan.json)")
    add_apply_options(apply_cmd)

    run = sub.add_parser("run", help="scan and then apply in one pass")
    add_scan_options(run)
    add_apply_options(run)
    run.add_argument("--output", "-o", default="dedupe-plan.json",
                     help="where to write the plan it applies (default: dedupe-plan.json)")
    return parser


def do_scan(args: argparse.Namespace) -> Plan:
    # Absolute, symlink-free roots: a plan outlives the shell that made it, so
    # every path it records has to mean the same thing from any directory.
    roots = [Path(r).expanduser().resolve() for r in (args.roots or ["."])]
    arch = args.arch or shrink.native_arch()
    patterns = DEFAULT_EXCLUDES + tuple(args.exclude)

    started = time.monotonic()
    entries = walk(roots, patterns)
    LOG.debug("walked %s in %.2fs", plural(len(entries), "file"), time.monotonic() - started)

    groups = [] if args.no_duplicates else find_duplicates(entries, args.min_size)
    fat = [] if args.no_binaries else find_universal(entries, roots)
    fat = [f for f in fat if f.reclaimable(arch) > 0]

    items = build_items(groups, fat, arch)
    plan = build_plan(roots, arch, entries, items, args.min_size)
    report_plan(plan, args.top)
    return plan


def check_cloning_is_possible(plan: Plan, force: bool) -> bool:
    """Cloning needs APFS; thinning does not, so this is only asked when needed."""
    table = mount_table()
    for root in plan.get("roots", []):
        fstype = filesystem_of(Path(root), table)
        if fstype and fstype != "apfs":
            message = f"{root} is on {fstype}, not APFS; cp -c cannot clone there"
            if not force:
                LOG.error("%s (use --force to try anyway)", message)
                return False
            LOG.warning("%s - continuing because --force was given", message)
    return True


def do_apply(plan: Plan, args: argparse.Namespace) -> int:
    items = plan["items"]
    arch = plan.get("arch") or shrink.native_arch()
    started = time.monotonic()
    actions: list[Action] = []

    duplicates = [i for i in items if i["kind"] == DUPLICATE]
    if duplicates and not check_cloning_is_possible(plan, args.force):
        return 2

    # Thinning rewrites files, which would break any clone made first, so the
    # binaries are dealt with before a single block is shared.
    targets = unique_targets(items)
    if targets:
        LOG.info("thinning %s to %s",
                 plural(len(targets), "target"), arch)
        actions += apply_universal(targets, arch, args.dry_run,
                                   not args.no_verify_signature)
        if not args.keep_going and any(a.status == FAILED for a in actions):
            LOG.error("stopping after a failure (--keep-going continues instead)")
            summarize(actions, time.monotonic() - started)
            return 1

    if duplicates:
        LOG.info("cloning %s of duplicates", plural(len(duplicates), "group"))
    for item in duplicates:
        results = apply_duplicate(item, args.dry_run, not args.no_verify)
        for action in results:
            if action.status in (CLONED, PLANNED):
                LOG.info("  %s: %s", action.status, action.target)
            elif action.status == SKIPPED:
                LOG.debug("  skipped %s: %s", action.target, action.reason)
            else:
                LOG.error("  failed %s: %s", action.target, action.reason)
        actions += results
        if not args.keep_going and any(a.status == FAILED for a in results):
            LOG.error("stopping after a failure (--keep-going continues instead)")
            break

    summarize(actions, time.monotonic() - started)
    return 1 if any(a.status == FAILED for a in actions) else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose, args.quiet)

    if sys.platform != "darwin":
        LOG.error("dedupe relies on APFS cloning and Mach-O thinning; it only works on macOS")
        return 2

    if args.command in ("scan", "run"):
        plan = do_scan(args)
        write_plan(plan, Path(args.output))
        if str(args.output) != "-":
            LOG.info("plan written to %s", args.output)
        if args.command == "scan":
            return 0
    else:
        try:
            plan = load_plan(Path(args.plan))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            LOG.error("cannot read plan: %s", exc)
            return 2

    if not plan["items"]:
        LOG.info("nothing to do")
        return 0
    return do_apply(plan, args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        LOG.warning("interrupted: every original is intact, but scratch files named "
                    ".*.dedupe-* may be left behind and can be deleted")
        sys.exit(130)
