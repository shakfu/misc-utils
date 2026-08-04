#!/usr/bin/env python3
"""shrink - thin universal (fat) Mach-O bundles and binaries down to one architecture.

Design notes
------------
`ditto --arch <arch>` is the supported way to thin a bundle, but it is not safe
to drive blindly: when the requested architecture is not present in a binary it
still exits 0 and simply omits that binary from the output. A naive
"ditto to temp; rm -rf original; mv temp original" therefore destroys bundles.

By default each universal binary is therefore rewritten individually: ditto
produces a thinned copy beside it, that copy is checked, and only then does an
atomic rename put it in place. Nothing else in the target is touched, binaries
that lack the requested architecture are left alone rather than lost, and an
interrupted run leaves a working target.

`--copy` selects the older whole-target approach instead. It still never
removes an original until the replacement has been independently verified -
every regular file, symlink and binary present before must still be present
afterwards - but it needs scratch space equal to the target and, because ditto
is all-or-nothing per target, it must refuse targets that hold any binary
without the requested architecture.

Every decision is logged with the reason behind it, so a run explains not just
what was changed but why everything else was left alone.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import platform
import shutil
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

LOG = logging.getLogger("shrink")

# Bundle/binary suffixes searched for when no explicit target is given.
DEFAULT_ENDINGS = (
    ".app",
    ".appex",
    ".bundle",
    ".component",
    ".framework",
    ".kext",
    ".plugin",
    ".vst",
    ".vst3",
    ".dylib",
    ".so",
    ".a",
)

# ---------------------------------------------------------------------------
# Mach-O inspection (pure Python: no subprocess per file)
# ---------------------------------------------------------------------------

FAT_MAGIC = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF
# MH_MAGIC / MH_CIGAM / MH_MAGIC_64 / MH_CIGAM_64, read as big-endian uint32.
THIN_MAGICS = frozenset((0xFEEDFACE, 0xCEFAEDFE, 0xFEEDFACF, 0xCFFAEDFE))
# A universal static library is a fat wrapper around ar archives, so thinning
# one yields a plain archive rather than a Mach-O file. Both count as valid.
AR_MAGIC = b"!<arch>\n"

_ABI64 = 0x01000000
_ABI64_32 = 0x02000000
_SUBTYPE_MASK = 0x00FFFFFF  # strip capability bits (e.g. arm64e pointer-auth ABI)

# cputype -> family name, mirroring the names `lipo`/`ditto` accept.
_CPU_FAMILY = {
    7: "i386",
    7 | _ABI64: "x86_64",
    12: "arm",
    12 | _ABI64: "arm64",
    12 | _ABI64_32: "arm64_32",
    18: "ppc",
    18 | _ABI64: "ppc64",
}

# (cputype, cpusubtype) -> exact slice name, for the cases that matter.
_CPU_EXACT = {
    (7 | _ABI64, 8): "x86_64h",
    (12 | _ABI64, 1): "arm64v8",
    (12 | _ABI64, 2): "arm64e",
    (12, 9): "armv7",
    (12, 11): "armv7s",
    (12, 12): "armv7k",
}

# A fat header holds few slices; a larger count means we mis-detected the magic
# (0xCAFEBABE is also the Java class-file magic).
_MAX_FAT_ARCHS = 32


@dataclass(frozen=True)
class Slice:
    """One architecture slice inside a universal binary."""

    arch: str
    family: str
    size: int


@dataclass
class MachO:
    """A Mach-O file found inside a target."""

    rel: str
    size: int
    slices: tuple[Slice, ...]  # empty => already a single-architecture file

    @property
    def is_fat(self) -> bool:
        return bool(self.slices)


def _arch_names(cputype: int, cpusubtype: int) -> tuple[str, str]:
    """Return (exact slice name, architecture family) for a fat_arch entry."""
    subtype = cpusubtype & _SUBTYPE_MASK
    family = _CPU_FAMILY.get(cputype, f"cputype{cputype}")
    exact = _CPU_EXACT.get((cputype, subtype), family)
    return exact, family


def inspect_macho(path: Path, size: int) -> MachO | None:
    """Classify *path*; return None if it is not a Mach-O file.

    A returned MachO with no slices is a thin (single-architecture) binary.
    """
    if size < 8:
        return None
    try:
        with open(path, "rb") as handle:
            header = handle.read(8)
            if len(header) < 8:
                return None
            if header == AR_MAGIC:
                return MachO(rel="", size=size, slices=())
            magic, second = struct.unpack(">II", header)
            if magic in THIN_MAGICS:
                return MachO(rel="", size=size, slices=())
            if magic not in (FAT_MAGIC, FAT_MAGIC_64):
                return None

            nfat = second
            if not 1 <= nfat <= _MAX_FAT_ARCHS:
                LOG.debug("%s: 0xCAFEBABE with %d entries, not a fat Mach-O", path, nfat)
                return None

            wide = magic == FAT_MAGIC_64
            record = 32 if wide else 20
            table = handle.read(record * nfat)
            if len(table) < record * nfat:
                return None
    except OSError as exc:
        LOG.debug("%s: unreadable (%s)", path, exc)
        return None

    slices: list[Slice] = []
    for index in range(nfat):
        chunk = table[index * record : (index + 1) * record]
        if wide:
            cputype, cpusubtype, offset, slice_size, _align, _res = struct.unpack(">iiQQII", chunk)
        else:
            cputype, cpusubtype, offset, slice_size, _align = struct.unpack(">iiIII", chunk)
        if offset + slice_size > size or slice_size <= 0:
            LOG.debug("%s: fat entry %d out of bounds, not a fat Mach-O", path, index)
            return None
        arch, family = _arch_names(cputype, cpusubtype)
        slices.append(Slice(arch=arch, family=family, size=slice_size))

    return MachO(rel="", size=size, slices=tuple(slices))


# ---------------------------------------------------------------------------
# Filesystem inventory
# ---------------------------------------------------------------------------


@dataclass
class Inventory:
    """Everything known about a target before or after an operation."""

    root: Path
    files: dict[str, int] = field(default_factory=dict)  # rel path -> size
    links: dict[str, str] = field(default_factory=dict)  # rel path -> link target
    dirs: set[str] = field(default_factory=set)
    machos: list[MachO] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(self.files.values())

    @property
    def fat_machos(self) -> list[MachO]:
        return [m for m in self.machos if m.is_fat]


def scan(root: Path) -> Inventory:
    """Walk *root* (a file or a directory) without following symlinks."""
    inv = Inventory(root=root)

    def record_file(rel: str, path: Path) -> None:
        try:
            size = path.lstat().st_size
        except OSError as exc:
            LOG.debug("%s: cannot stat (%s)", path, exc)
            return
        inv.files[rel] = size
        macho = inspect_macho(path, size)
        if macho is not None:
            inv.machos.append(MachO(rel=rel, size=size, slices=macho.slices))

    if root.is_file() and not root.is_symlink():
        record_file("", root)
        return inv

    stack = [(root, "")]
    while stack:
        directory, prefix = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            LOG.debug("%s: cannot list (%s)", directory, exc)
            continue
        for entry in entries:
            rel = f"{prefix}{entry.name}"
            if entry.is_symlink():
                try:
                    inv.links[rel] = os.readlink(entry.path)
                except OSError:
                    inv.links[rel] = "?"
            elif entry.is_dir(follow_symlinks=False):
                inv.dirs.add(rel)
                stack.append((Path(entry.path), rel + "/"))
            else:
                record_file(rel, Path(entry.path))
    return inv


# ---------------------------------------------------------------------------
# Host architecture
# ---------------------------------------------------------------------------


def _sysctl(name: str) -> str | None:
    try:
        out = subprocess.run(
            ["sysctl", "-n", name], capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def native_arch() -> str:
    """The architecture of the hardware, not of the interpreter.

    Under Rosetta 2 `platform.machine()` reports x86_64 on an Apple Silicon Mac;
    thinning to that would strip the arch the machine actually runs natively.
    """
    reported = platform.machine()
    if reported == "x86_64" and _sysctl("hw.optional.arm64") == "1":
        LOG.info(
            "host reports x86_64 but hardware is arm64 (running under Rosetta); "
            "using arm64 - override with --arch x86_64 if that is intentional"
        )
        return "arm64"
    return reported


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

THINNED = "thinned"
SKIPPED = "skipped"
PLANNED = "planned"  # --dry-run: would have been thinned
FAILED = "failed"


@dataclass
class Result:
    target: Path
    status: str
    reason: str
    before: int = 0
    after: int = 0
    elapsed: float = 0.0
    detail: str = ""  # what the scan found, logged just above the outcome

    @property
    def saved(self) -> int:
        return max(0, self.before - self.after)


def human(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num_bytes) < 1024 or unit == "GB":
            return f"{num_bytes:.0f}{unit}" if unit == "B" else f"{num_bytes:.1f}{unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f}GB"


def plural(count: int, noun: str, plural_form: str | None = None) -> str:
    return f"{count} {noun if count == 1 else (plural_form or noun + 's')}"


# ---------------------------------------------------------------------------
# Thinning
# ---------------------------------------------------------------------------


def run_ditto(arch: str, src: Path, dst: Path) -> tuple[bool, str]:
    """Copy *src* to *dst* keeping only *arch*. Returns (ok, message)."""
    proc = subprocess.run(
        ["ditto", "--arch", arch, str(src), str(dst)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip() or f"ditto exited {proc.returncode}"
    # ditto exits 0 even when it produced nothing at all.
    if not dst.exists():
        return False, "ditto reported success but produced no output"
    return True, ""


def verify_copy(before: Inventory, after: Inventory) -> str | None:
    """Return a human-readable reason the copy is unusable, or None if it is sound."""
    missing_files = sorted(set(before.files) - set(after.files))
    if missing_files:
        shown = ", ".join(missing_files[:5])
        more = f" (+{len(missing_files) - 5} more)" if len(missing_files) > 5 else ""
        return (f"{plural(len(missing_files), 'file')} missing from the thinned copy: "
                f"{shown}{more}")

    missing_links = sorted(set(before.links) - set(after.links))
    if missing_links:
        return (f"{plural(len(missing_links), 'symlink')} missing from the thinned copy: "
                f"{missing_links[0]}")

    after_machos = {m.rel for m in after.machos}
    lost_machos = sorted({m.rel for m in before.machos} - after_machos)
    if lost_machos:
        return (f"{plural(len(lost_machos), 'binary', 'binaries')} no longer a usable binary "
                f"after thinning: {lost_machos[0]}")

    empty = sorted(rel for rel, size in after.files.items()
                   if size == 0 and before.files.get(rel, 0) > 0)
    if empty:
        return f"{plural(len(empty), 'file')} truncated to zero bytes: {empty[0]}"
    return None


def is_signed(path: Path) -> bool:
    proc = subprocess.run(
        ["codesign", "-v", "--no-strict", str(path)], capture_output=True, text=True, check=False
    )
    return proc.returncode == 0


def swap_in(new: Path, target: Path) -> None:
    """Replace *target* with *new*, keeping the old copy until the swap succeeds."""
    parked = target.with_name(f"{target.name}.shrink-old-{os.getpid()}")
    os.rename(target, parked)
    try:
        os.rename(new, target)
    except OSError:
        os.rename(parked, target)  # put the original back before re-raising
        raise
    if parked.is_dir() and not parked.is_symlink():
        shutil.rmtree(parked, ignore_errors=True)
    else:
        parked.unlink(missing_ok=True)


def remove_partial(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists() or path.is_symlink():
        try:
            path.unlink()
        except OSError:
            pass


def thin_by_copy(target: Path, arch: str, inv: Inventory, check_signature: bool) -> Result:
    """Whole-target copy via ditto, verified before the original is touched."""
    started = time.monotonic()
    scratch = target.with_name(f"{target.name}.shrink-new-{os.getpid()}")
    remove_partial(scratch)

    free = shutil.disk_usage(target.parent).free
    if free < inv.total_bytes:
        return Result(
            target, FAILED,
            f"only {human(free)} free on the volume, need at least {human(inv.total_bytes)} "
            "for a verified copy (drop --copy to rewrite binaries individually instead)",
            elapsed=time.monotonic() - started,
        )

    signed = check_signature and is_signed(target)
    if check_signature:
        LOG.debug("%s: code signature %s before thinning", target.name,
                  "valid" if signed else "absent or invalid")

    ok, message = run_ditto(arch, target, scratch)
    if not ok:
        remove_partial(scratch)
        return Result(target, FAILED, message, elapsed=time.monotonic() - started)

    after = scan(scratch)
    problem = verify_copy(inv, after)
    if problem is not None:
        remove_partial(scratch)
        return Result(target, FAILED, f"refusing to replace original: {problem}",
                      elapsed=time.monotonic() - started)

    if signed and not is_signed(scratch):
        remove_partial(scratch)
        return Result(target, FAILED,
                      "refusing to replace original: the code signature no longer "
                      "validates after thinning",
                      elapsed=time.monotonic() - started)

    try:
        swap_in(scratch, target)
    except OSError as exc:
        remove_partial(scratch)
        return Result(target, FAILED, f"could not swap in the thinned copy: {exc}",
                      elapsed=time.monotonic() - started)

    return Result(target, THINNED, "verified thinned copy swapped in",
                  before=inv.total_bytes, after=after.total_bytes,
                  elapsed=time.monotonic() - started)


def thin_in_place(target: Path, arch: str, inv: Inventory, check_signature: bool,
                  binaries: list[MachO] | None = None) -> Result:
    """Rewrite only the universal binaries, one atomic file replacement each.

    Avoids copying the whole bundle, so it is much faster on large targets and
    needs scratch space only for the biggest single binary. Each binary is
    replaced atomically, so an interrupted run leaves a working target with a
    mix of thinned and untouched binaries rather than a broken one.
    """
    started = time.monotonic()
    signed = check_signature and is_signed(target)
    LOG.debug("%s: code signature %s before thinning", target.name,
              "valid" if signed else "absent, invalid, or not checked")
    rewritten = 0
    after_bytes = inv.total_bytes

    for macho in (inv.fat_machos if binaries is None else binaries):
        path = target if macho.rel == "" else target / macho.rel
        scratch = path.with_name(f".{path.name}.shrink-{os.getpid()}")
        remove_partial(scratch)
        ok, message = run_ditto(arch, path, scratch)
        if not ok:
            remove_partial(scratch)
            return Result(target, FAILED,
                          f"{macho.rel or path.name}: {message} "
                          f"({plural(rewritten, 'binary', 'binaries')} already rewritten)",
                          elapsed=time.monotonic() - started)
        new_size = scratch.stat().st_size
        if new_size == 0 or inspect_macho(scratch, new_size) is None:
            remove_partial(scratch)
            return Result(target, FAILED,
                          f"{macho.rel or path.name}: thinned output is not a usable binary; "
                          "the original was left in place",
                          elapsed=time.monotonic() - started)
        try:
            os.replace(scratch, path)
        except OSError as exc:
            remove_partial(scratch)
            return Result(target, FAILED, f"{macho.rel or path.name}: {exc}",
                          elapsed=time.monotonic() - started)
        LOG.debug("%s: %s %s -> %s", target.name, macho.rel or path.name,
                  human(macho.size), human(new_size))
        after_bytes -= macho.size - new_size
        rewritten += 1

    if signed and not is_signed(target):
        return Result(target, FAILED,
                      f"code signature no longer validates after rewriting "
                      f"{plural(rewritten, 'binary', 'binaries')}; "
                      "the target may need to be re-signed or restored from a copy",
                      before=inv.total_bytes, after=after_bytes,
                      elapsed=time.monotonic() - started)

    return Result(target, THINNED,
                  f"rewrote {plural(rewritten, 'universal binary', 'universal binaries')} in place",
                  before=inv.total_bytes, after=after_bytes,
                  elapsed=time.monotonic() - started)


# ---------------------------------------------------------------------------
# Per-target driver
# ---------------------------------------------------------------------------


def process(target: Path, arch: str, *, in_place: bool, dry_run: bool,
            check_signature: bool) -> Result:
    started = time.monotonic()

    if target.is_symlink():
        return Result(target, SKIPPED, "is a symlink; thinning would replace the link itself",
                      elapsed=time.monotonic() - started)
    if not target.exists():
        return Result(target, FAILED, "no such file or directory",
                      elapsed=time.monotonic() - started)

    inv = scan(target)
    fat = inv.fat_machos
    LOG.debug("%s: %s, %s Mach-O, %s universal, %s on disk",
              target.name, plural(len(inv.files), "file"), len(inv.machos), len(fat),
              human(inv.total_bytes))

    if not inv.machos:
        return Result(target, SKIPPED, "contains no Mach-O binaries",
                      elapsed=time.monotonic() - started)
    if not fat:
        count = len(inv.machos)
        return Result(target, SKIPPED,
                      "the only Mach-O binary is already single-architecture" if count == 1
                      else f"all {count} Mach-O binaries are already single-architecture",
                      elapsed=time.monotonic() - started)

    def has_arch(macho: MachO) -> bool:
        return any(s.family == arch or s.arch == arch for s in macho.slices)

    # ditto exits 0 while silently omitting binaries that lack `arch`, so a
    # whole-target copy has to be refused outright when any binary lacks it.
    # Rewriting binaries individually can still thin the rest safely.
    thinnable = [m for m in fat if has_arch(m)]
    lacking = [m for m in fat if not has_arch(m)]
    if lacking:
        first = lacking[0]
        present = ",".join(sorted({s.arch for s in first.slices}))
        problem = (f"{plural(len(lacking), 'universal binary', 'universal binaries')} "
                   f"{'does' if len(lacking) == 1 else 'do'} not contain {arch} "
                   f"({first.rel or target.name} has {present})")
        if not thinnable:
            return Result(target, SKIPPED, f"{problem}; nothing here can be thinned safely",
                          elapsed=time.monotonic() - started)
        if not in_place:
            return Result(
                target, SKIPPED,
                f"{problem}; the --copy strategy would delete "
                f"{'it' if len(lacking) == 1 else 'them'} - drop --copy to thin the other "
                f"{len(thinnable)} and leave those alone",
                elapsed=time.monotonic() - started,
            )

    archs_present = sorted({s.arch for m in thinnable for s in m.slices})
    keep = sum(min(s.size for s in m.slices if s.family == arch or s.arch == arch)
               for m in thinnable)
    estimate = max(0, sum(m.size for m in thinnable) - keep)
    detail = (f"{plural(len(thinnable), 'universal binary', 'universal binaries')} "
              f"[{','.join(archs_present)}] -> {arch}, about {human(estimate)} recoverable")
    if lacking:
        detail += (f"; leaving {plural(len(lacking), 'binary', 'binaries')} alone "
                   f"(no {arch} slice)")

    if dry_run:
        return Result(target, PLANNED, "would be thinned; nothing written in dry-run mode",
                      before=inv.total_bytes, after=inv.total_bytes - estimate,
                      elapsed=time.monotonic() - started, detail=detail)

    if in_place:
        result = thin_in_place(target, arch, inv, check_signature, binaries=thinnable)
    else:
        result = thin_by_copy(target, arch, inv, check_signature)
    result.detail = detail
    return result


# ---------------------------------------------------------------------------
# Discovery and CLI
# ---------------------------------------------------------------------------


def discover(root: Path, endings: tuple[str, ...], recursive: bool) -> list[Path]:
    """Find candidate targets under *root*, never descending into a match."""
    found: list[Path] = []
    if not recursive:
        try:
            entries = sorted(os.scandir(root), key=lambda e: e.name)
        except OSError as exc:
            LOG.error("cannot list %s: %s", root, exc)
            return found
        return [Path(e.path) for e in entries if e.name.endswith(endings)]

    for dirpath, dirnames, filenames in os.walk(root):
        matched = [d for d in dirnames if d.endswith(endings)]
        for name in matched:
            found.append(Path(dirpath) / name)
        dirnames[:] = [d for d in dirnames if d not in set(matched)]
        found.extend(Path(dirpath) / f for f in filenames if f.endswith(endings))
    return sorted(found)


def configure_logging(verbosity: int, quiet: bool, log_file: str | None) -> None:
    level = logging.WARNING if quiet else (logging.DEBUG if verbosity else logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    handlers[0].setFormatter(logging.Formatter("%(levelname)s %(message)s"
                                               if level == logging.DEBUG else "%(message)s"))
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        file_handler.setLevel(logging.DEBUG)
        handlers.append(file_handler)
    LOG.setLevel(logging.DEBUG if log_file else level)
    handlers[0].setLevel(level)
    for handler in handlers:
        LOG.addHandler(handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shrink",
        description="Thin universal Mach-O bundles and binaries to a single architecture.",
        epilog="With no targets, scans the current directory for known bundle suffixes.",
    )
    parser.add_argument("targets", nargs="*", help="bundles or binaries to thin")
    parser.add_argument("--target", "-t", action="append", default=[],
                        dest="target_flags", help=argparse.SUPPRESS)  # back-compat
    parser.add_argument("--arch", "-a", help="architecture to keep (default: this machine's)")
    strategy = parser.add_mutually_exclusive_group()
    strategy.add_argument("--in-place", action="store_true",
                          help="rewrite each universal binary individually (the default)")
    strategy.add_argument("--copy", action="store_true",
                          help="copy the whole target with ditto and verify the copy before "
                               "replacing the original; slower, needs scratch space equal to the "
                               "target, and must refuse targets holding any binary without ARCH")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="report what would change and how much would be recovered")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="search subdirectories when discovering targets")
    parser.add_argument("--ext", action="append", default=[],
                        help="additional suffix to treat as a target (repeatable)")
    parser.add_argument("--jobs", "-j", type=int, default=0,
                        help="targets to process concurrently (default: 4)")
    parser.add_argument("--no-verify-signature", action="store_true",
                        help="skip the codesign check on targets that were validly signed")
    parser.add_argument("--keep-going", "-k", action="store_true",
                        help="continue after a failure (default: stop)")
    parser.add_argument("--json", action="store_true",
                        help="write a machine-readable report to stdout")
    parser.add_argument("--log-file", help="also write a timestamped debug log here")
    parser.add_argument("--verbose", "-v", action="count", default=0, help="per-file detail")
    parser.add_argument("--quiet", "-q", action="store_true", help="warnings and errors only")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose, args.quiet, args.log_file)

    if sys.platform != "darwin":
        LOG.error("shrink thins Mach-O binaries and only works on macOS")
        return 2
    if shutil.which("ditto") is None:
        LOG.error("ditto not found on PATH; cannot thin anything")
        return 2

    arch = args.arch or native_arch()
    endings = DEFAULT_ENDINGS + tuple(
        e if e.startswith(".") else f".{e}" for e in args.ext
    )

    explicit = [Path(t) for t in args.targets + args.target_flags]
    if explicit:
        targets = explicit
        LOG.info("examining %s, keeping %s", plural(len(targets), "explicit target"), arch)
    else:
        root = Path.cwd()
        targets = discover(root, endings, args.recursive)
        LOG.debug("candidate suffixes: %s", " ".join(endings))
        LOG.info("scanned %s%s: %s to examine, keeping %s",
                 root, " recursively" if args.recursive else "",
                 plural(len(targets), "candidate"), arch)
        if not targets:
            LOG.info("nothing matched; use --recursive or --ext to widen the search")
            return 0

    in_place = not args.copy
    jobs = max(1, min(args.jobs or 4, len(targets)))
    if args.dry_run:
        LOG.info("dry run: nothing will be modified")
    elif in_place:
        LOG.info("strategy: rewrite each universal binary in place, one atomic replacement each "
                 "(no full-target copy, scratch space only for the largest binary)")
    else:
        LOG.info("strategy: copy each target with ditto and verify the copy before replacing the "
                 "original (needs scratch space equal to the target; drop --copy to avoid that)")

    started = time.monotonic()
    results: list[Result] = []

    def run_one(target: Path) -> Result:
        return process(target, arch, in_place=in_place, dry_run=args.dry_run,
                       check_signature=not args.no_verify_signature)

    if jobs == 1:
        for target in targets:
            result = run_one(target)
            report(result)
            results.append(result)
            if result.status == FAILED and not args.keep_going:
                LOG.error("stopping after a failure (--keep-going continues instead)")
                break
    else:
        LOG.debug("processing %s with %d workers", plural(len(targets), "target"), jobs)
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = [pool.submit(run_one, target) for target in targets]
            for index, future in enumerate(futures):
                result = future.result()
                report(result)
                results.append(result)
                if result.status == FAILED and not args.keep_going:
                    cancelled = sum(1 for f in futures[index + 1:] if f.cancel())
                    LOG.error("stopping after a failure; %d queued target(s) cancelled "
                              "(--keep-going continues instead)", cancelled)
                    break

    summarize(results, time.monotonic() - started)
    if args.json:
        json.dump(
            {
                "arch": arch,
                "results": [
                    {
                        "target": str(r.target),
                        "status": r.status,
                        "reason": r.reason,
                        "bytes_before": r.before,
                        "bytes_after": r.after,
                        "bytes_saved": r.saved,
                        "seconds": round(r.elapsed, 3),
                    }
                    for r in results
                ],
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
    return 1 if any(r.status == FAILED for r in results) else 0


def report(result: Result) -> None:
    """One block per target: what was found, then what was done about it."""
    name = result.target.name or str(result.target)
    if result.detail:
        LOG.info("%s: %s", name, result.detail)
    if result.status == THINNED:
        LOG.info("  thinned: %s -> %s, saved %s in %.2fs (%s)",
                 human(result.before), human(result.after), human(result.saved),
                 result.elapsed, result.reason)
    elif result.status == PLANNED:
        LOG.info("  %s", result.reason)
    elif result.status == SKIPPED:
        LOG.info("%s%s", "  skipped: " if result.detail else f"skipped {name}: ", result.reason)
    else:
        LOG.error("%sunchanged - %s", "  failed: " if result.detail else f"failed {name}: ",
                  result.reason)


def summarize(results: list[Result], elapsed: float) -> None:
    counts = {status: sum(1 for r in results if r.status == status)
              for status in (THINNED, PLANNED, SKIPPED, FAILED)}
    saved = sum(r.saved for r in results)
    parts = [f"{counts[THINNED]} thinned"] if not counts[PLANNED] else [
        f"{counts[PLANNED]} would be thinned"]
    parts += [f"{counts[SKIPPED]} skipped", f"{counts[FAILED]} failed"]
    verb = "recoverable" if counts[PLANNED] else "recovered"
    LOG.info("done in %.2fs: %s, %s %s", elapsed, ", ".join(parts), human(saved), verb)
    for result in results:
        if result.status == FAILED:
            LOG.warning("  left unchanged: %s (%s)", result.target, result.reason)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        LOG.warning("interrupted: originals are intact, but scratch copies named "
                    "*.shrink-new-* or .*.shrink-* may be left behind and can be deleted")
        sys.exit(130)
