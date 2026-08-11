"""Tests for the `dedupe` duplicate cloner and fat-binary thinner.

Run with `make test`, or `uv run pytest`.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEDUPE_PATH = ROOT / "src" / "py" / "dedupe.py"

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="dedupe is macOS-only")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_loader(
        name, importlib.machinery.SourceFileLoader(name, str(path))
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


dedupe = _load("dedupe_module", DEDUPE_PATH)

HAVE_CLANG = shutil.which("clang") is not None
needs_clang = pytest.mark.skipif(not HAVE_CLANG, reason="clang required to build test binaries")

BLOCK = dedupe.DEFAULT_MIN_SIZE


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def payload(marker: bytes = b"a", size: int = BLOCK * 3) -> bytes:
    return (marker * 64)[:64] + bytes(size - 64)


def foreign_fat_bytes() -> bytes:
    """A universal binary whose slices are armv7 and arm64_32.

    Neither runs on any Mac, so nothing can be thinned away from it. Building
    one needs toolchains that are no longer shipped, so the header is written
    by hand; only the fat header is ever parsed.
    """
    header = struct.pack(">II", 0xCAFEBABE, 2)
    entries = (struct.pack(">iiIII", 12, 9, 4096, 1024, 12)               # armv7
               + struct.pack(">iiIII", 12 | 0x02000000, 1, 8192, 1024, 12))  # arm64_32
    body = bytearray(9216)
    body[0:len(header) + len(entries)] = header + entries
    return bytes(body)


def run_cli(*argv: str) -> int:
    return dedupe.main(list(argv))


@pytest.fixture(autouse=True)
def quiet_logging():
    dedupe.configure_logging(0, quiet=True)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """Two identical files, one unique file, one file too small to matter."""
    data = payload(b"dup")
    write(tmp_path / "one.bin", data)
    write(tmp_path / "sub" / "two.bin", data)
    write(tmp_path / "other.bin", payload(b"other"))
    write(tmp_path / "tiny.txt", b"tiny")
    return tmp_path


@pytest.fixture(scope="session")
def source_file(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("csrc") / "t.c"
    path.write_text("int main(void){return 0;}\n")
    return path


@pytest.fixture(scope="session")
def fat_template(source_file, tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("fat") / "fat"
    subprocess.run(["clang", "-arch", "arm64", "-arch", "x86_64", "-o", str(out),
                    str(source_file)], check=True, capture_output=True)
    return out


# ---------------------------------------------------------------------------
# Walking
# ---------------------------------------------------------------------------


def test_walk_collects_regular_files_only(tree: Path):
    (tree / "link.bin").symlink_to(tree / "one.bin")
    (tree / "dirlink").symlink_to(tree / "sub")
    names = sorted(e.path.name for e in dedupe.walk([tree], ()))
    assert names == ["one.bin", "other.bin", "tiny.txt", "two.bin"]


def test_walk_honours_excludes(tree: Path):
    names = sorted(e.path.name for e in dedupe.walk([tree], ("sub", "*.txt")))
    assert names == ["one.bin", "other.bin"]


def test_walk_accepts_a_file_as_a_root(tree: Path):
    entries = dedupe.walk([tree / "one.bin"], ())
    assert [e.path.name for e in entries] == ["one.bin"]


def test_walk_reports_unreadable_roots(tmp_path: Path, caplog):
    with caplog.at_level("ERROR", logger="dedupe"):
        assert dedupe.walk([tmp_path / "missing"], ()) == []
    assert "cannot read" in caplog.text


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


def test_finds_identical_files(tree: Path):
    groups = dedupe.find_duplicates(dedupe.walk([tree], ()), BLOCK)
    assert len(groups) == 1
    group = groups[0]
    assert [p.name for p in group.members] == ["one.bin", "two.bin"]
    assert group.reclaimable == group.size


def test_ignores_files_below_the_minimum_size(tmp_path: Path):
    small = b"identical" * 8
    write(tmp_path / "a", small)
    write(tmp_path / "b", small)
    assert dedupe.find_duplicates(dedupe.walk([tmp_path], ()), BLOCK) == []
    assert len(dedupe.find_duplicates(dedupe.walk([tmp_path], ()), 1)) == 1


def test_same_size_different_content_is_not_a_duplicate(tmp_path: Path):
    write(tmp_path / "a", b"\x01" * BLOCK * 2)
    write(tmp_path / "b", b"\x02" * BLOCK * 2)
    assert dedupe.find_duplicates(dedupe.walk([tmp_path], ()), BLOCK) == []


def test_content_differing_only_past_the_partial_prefix(tmp_path: Path):
    size = dedupe.PARTIAL_BYTES * 2
    head = b"h" * dedupe.PARTIAL_BYTES
    write(tmp_path / "a", head + b"a" * dedupe.PARTIAL_BYTES)
    write(tmp_path / "b", head + b"b" * dedupe.PARTIAL_BYTES)
    write(tmp_path / "c", head + b"a" * dedupe.PARTIAL_BYTES)
    groups = dedupe.find_duplicates(dedupe.walk([tmp_path], ()), BLOCK)
    assert len(groups) == 1
    assert [p.name for p in groups[0].members] == ["a", "c"]
    assert groups[0].size == size


def test_hard_links_alone_are_not_duplicates(tmp_path: Path):
    write(tmp_path / "a", payload())
    os.link(tmp_path / "a", tmp_path / "b")
    assert dedupe.find_duplicates(dedupe.walk([tmp_path], ()), BLOCK) == []


def test_hard_links_are_collapsed_to_one_member(tmp_path: Path):
    data = payload()
    write(tmp_path / "a", data)
    os.link(tmp_path / "a", tmp_path / "a2")
    write(tmp_path / "b", data)
    groups = dedupe.find_duplicates(dedupe.walk([tmp_path], ()), BLOCK)
    assert len(groups) == 1
    assert sorted(p.name for p in groups[0].members) == ["a", "b"]
    assert groups[0].linked == {str(tmp_path / "a"): [str(tmp_path / "a2")]}


def test_groups_never_span_devices(tmp_path: Path, monkeypatch):
    data = payload()
    write(tmp_path / "a", data)
    write(tmp_path / "b", data)
    entries = dedupe.walk([tmp_path], ())
    moved = [dedupe.Entry(path=e.path, dev=index, ino=e.ino, size=e.size, nlink=e.nlink)
             for index, e in enumerate(entries)]
    assert dedupe.find_duplicates(moved, BLOCK) == []


# ---------------------------------------------------------------------------
# Plan shape and ordering
# ---------------------------------------------------------------------------


def test_items_are_ordered_by_decreasing_recovery(tmp_path: Path):
    write(tmp_path / "small_a", payload(b"s", BLOCK * 2))
    write(tmp_path / "small_b", payload(b"s", BLOCK * 2))
    big = payload(b"L", BLOCK * 20)
    for name in ("big_a", "big_b", "big_c"):
        write(tmp_path / name, big)
    plan = dedupe.build_plan(
        [tmp_path], "arm64", [],
        dedupe.build_items(
            dedupe.find_duplicates(dedupe.walk([tmp_path], ()), BLOCK), [], "arm64"), BLOCK)
    recoveries = [item["reclaimable_bytes"] for item in plan["items"]]
    assert recoveries == sorted(recoveries, reverse=True)
    assert plan["items"][0]["count"] == 3
    assert plan["totals"]["reclaimable_bytes"] == sum(recoveries)


def test_a_hard_linked_member_becomes_the_source(tmp_path: Path):
    data = payload()
    write(tmp_path / "aaa", data)          # sorts first, so it would be the source
    write(tmp_path / "zzz", data)
    os.link(tmp_path / "zzz", tmp_path / "zzz2")
    groups = dedupe.find_duplicates(dedupe.walk([tmp_path], ()), BLOCK)
    item = dedupe.build_items(groups, [], "arm64")[0]
    assert item["keep"] == str(tmp_path / "zzz")
    assert item["replace"] == [str(tmp_path / "aaa")]


def test_scan_writes_an_absolute_and_reloadable_plan(tree: Path, tmp_path_factory, monkeypatch):
    out = tmp_path_factory.mktemp("plans") / "plan.json"
    monkeypatch.chdir(tree)
    assert run_cli("scan", ".", "-o", str(out)) == 0
    plan = dedupe.load_plan(out)
    assert plan["version"] == dedupe.PLAN_VERSION
    assert all(Path(root).is_absolute() for root in plan["roots"])
    item = plan["items"][0]
    assert item["kind"] == dedupe.DUPLICATE
    assert Path(item["keep"]).is_absolute()
    assert all(Path(p).is_absolute() for p in item["replace"])


def test_load_plan_rejects_foreign_documents(tmp_path: Path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"items": []}))
    with pytest.raises(ValueError, match="version"):
        dedupe.load_plan(path)
    path.write_text(json.dumps({"version": dedupe.PLAN_VERSION}))
    with pytest.raises(ValueError, match="items"):
        dedupe.load_plan(path)


def test_apply_rejects_an_unreadable_plan(tmp_path: Path):
    assert run_cli("apply", str(tmp_path / "nope.json")) == 2


# ---------------------------------------------------------------------------
# Cloning
# ---------------------------------------------------------------------------


def apply_plan(tree: Path, tmp_path_factory, *extra: str) -> tuple[int, dict]:
    plan_path = tmp_path_factory.mktemp("plan") / "plan.json"
    assert run_cli("scan", str(tree), "-o", str(plan_path)) == 0
    plan = json.loads(plan_path.read_text())
    return run_cli("apply", str(plan_path), *extra), plan


def test_apply_clones_duplicates_and_keeps_content(tree: Path, tmp_path_factory):
    original = (tree / "sub" / "two.bin").read_bytes()
    code, _ = apply_plan(tree, tmp_path_factory)
    assert code == 0
    assert (tree / "sub" / "two.bin").read_bytes() == original
    assert (tree / "one.bin").read_bytes() == original
    assert (tree / "other.bin").exists()


def test_apply_preserves_the_destination_identity(tree: Path, tmp_path_factory):
    destination = tree / "sub" / "two.bin"
    os.chmod(destination, 0o640)
    os.utime(destination, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
    before = destination.lstat()
    assert apply_plan(tree, tmp_path_factory)[0] == 0
    after = destination.lstat()
    assert after.st_mode == before.st_mode
    assert after.st_mtime_ns == before.st_mtime_ns
    assert after.st_ino != before.st_ino  # swapped in, not written through


def test_apply_leaves_no_scratch_files(tree: Path, tmp_path_factory):
    assert apply_plan(tree, tmp_path_factory)[0] == 0
    assert not [p for p in tree.rglob(".*") if "dedupe-" in p.name]


def test_dry_run_changes_nothing(tree: Path, tmp_path_factory):
    before = {p: p.lstat().st_ino for p in tree.rglob("*.bin")}
    code, _ = apply_plan(tree, tmp_path_factory, "--dry-run")
    assert code == 0
    assert {p: p.lstat().st_ino for p in tree.rglob("*.bin")} == before


def test_a_stale_plan_is_skipped_rather_than_obeyed(tree: Path, tmp_path_factory):
    plan_path = tmp_path_factory.mktemp("plan") / "plan.json"
    assert run_cli("scan", str(tree), "-o", str(plan_path)) == 0
    changed = payload(b"changed")
    (tree / "sub" / "two.bin").write_bytes(changed)
    assert run_cli("apply", str(plan_path)) == 0
    assert (tree / "sub" / "two.bin").read_bytes() == changed


def test_a_hard_linked_destination_is_left_alone(tmp_path: Path, tmp_path_factory):
    data = payload()
    write(tmp_path / "keep.bin", data)
    write(tmp_path / "linked.bin", data)
    os.link(tmp_path / "linked.bin", tmp_path / "linked2.bin")

    plan_path = tmp_path_factory.mktemp("plan") / "plan.json"
    assert run_cli("scan", str(tmp_path), "-o", str(plan_path)) == 0
    plan = json.loads(plan_path.read_text())
    # Force the linked file to be the destination, which apply must refuse.
    plan["items"][0]["keep"] = str(tmp_path / "keep.bin")
    plan["items"][0]["replace"] = [str(tmp_path / "linked.bin")]
    plan_path.write_text(json.dumps(plan))

    before = (tmp_path / "linked.bin").lstat()
    assert run_cli("apply", str(plan_path)) == 0
    after = (tmp_path / "linked.bin").lstat()
    assert after.st_ino == before.st_ino
    assert after.st_nlink == 2


def test_a_vanished_destination_is_skipped(tree: Path, tmp_path_factory):
    plan_path = tmp_path_factory.mktemp("plan") / "plan.json"
    assert run_cli("scan", str(tree), "-o", str(plan_path)) == 0
    (tree / "sub" / "two.bin").unlink()
    assert run_cli("apply", str(plan_path)) == 0


def test_clone_file_reports_a_failure_without_touching_the_destination(tmp_path: Path):
    source = write(tmp_path / "src", payload())
    destination = write(tmp_path / "dst", payload())
    before = destination.read_bytes()
    ok, message = dedupe.clone_file(source, destination, verify=True, expected="not-the-digest")
    assert not ok
    assert "does not match" in message
    assert destination.read_bytes() == before
    assert not list(tmp_path.glob(".*dedupe-*"))


def test_apply_refuses_a_volume_that_is_not_apfs(tree: Path, tmp_path_factory, monkeypatch):
    plan_path = tmp_path_factory.mktemp("plan") / "plan.json"
    assert run_cli("scan", str(tree), "-o", str(plan_path)) == 0
    monkeypatch.setattr(dedupe, "mount_table", lambda: [("/", "hfs")])
    before = (tree / "sub" / "two.bin").lstat().st_ino
    assert run_cli("apply", str(plan_path)) == 2
    assert (tree / "sub" / "two.bin").lstat().st_ino == before


# ---------------------------------------------------------------------------
# Volumes
# ---------------------------------------------------------------------------


def test_filesystem_of_picks_the_longest_mount_point(tmp_path: Path):
    table = dedupe.mount_table()
    assert dedupe.filesystem_of(tmp_path, table) is not None
    fake = sorted([("/", "hfs"), ("/System/Volumes/Data", "apfs")],
                  key=lambda row: len(row[0]), reverse=True)
    assert dedupe.filesystem_of(Path("/System/Volumes/Data/x"), fake) == "apfs"
    assert dedupe.filesystem_of(Path("/Applications"), fake) == "hfs"


def test_mount_table_is_parsed(tmp_path: Path):
    table = dedupe.mount_table()
    assert table, "mount produced no usable rows"
    assert all(point.startswith("/") and fstype for point, fstype in table)


# ---------------------------------------------------------------------------
# Universal binaries
# ---------------------------------------------------------------------------


@needs_clang
def test_universal_binaries_are_listed_with_their_bundle(fat_template: Path, tmp_path: Path):
    binary = tmp_path / "App.app" / "Contents" / "MacOS" / "App"
    binary.parent.mkdir(parents=True)
    shutil.copy(fat_template, binary)
    loose = tmp_path / "loose.dylib"
    shutil.copy(fat_template, loose)

    root = tmp_path.resolve()
    fat = dedupe.find_universal(dedupe.walk([root], ()), [root])
    targets = {f.path.name: f.target for f in fat}
    assert targets["App"] == root / "App.app"
    assert targets["loose.dylib"] == root / "loose.dylib"
    assert all(f.reclaimable(dedupe.shrink.native_arch()) > 0 for f in fat)


@needs_clang
def test_a_bundle_above_the_root_is_not_claimed(fat_template: Path, tmp_path: Path):
    inner = tmp_path / "App.app" / "Contents" / "MacOS"
    inner.mkdir(parents=True)
    shutil.copy(fat_template, inner / "App")
    fat = dedupe.find_universal(dedupe.walk([inner], ()), [inner.resolve()])
    assert fat[0].target == (inner / "App").resolve()


def test_a_binary_without_a_native_slice_is_not_planned(tmp_path: Path):
    """No host runs armv7 or arm64_32, so such a binary has nothing to give up."""
    write(tmp_path / "foreign.dylib", foreign_fat_bytes())
    root = tmp_path.resolve()
    fat = dedupe.find_universal(dedupe.walk([root], ()), [root])
    arch = dedupe.shrink.native_arch()
    assert len(fat) == 1
    assert fat[0].reclaimable(arch) == 0

    items = dedupe.build_items([], fat, arch)
    assert items[0]["has_native_slice"] is False
    assert dedupe.unique_targets(items) == []


def test_a_binary_without_a_native_slice_stays_out_of_the_plan(tmp_path: Path,
                                                               tmp_path_factory):
    write(tmp_path / "foreign.dylib", foreign_fat_bytes())
    out = tmp_path_factory.mktemp("plan") / "plan.json"
    assert run_cli("scan", str(tmp_path), "-o", str(out)) == 0
    assert json.loads(out.read_text())["items"] == []


@needs_clang
def test_apply_thins_before_it_clones(fat_template: Path, tmp_path: Path, tmp_path_factory):
    """A fat binary that is also a duplicate must end up thin *and* shared.

    Cloning first would be undone by the thinning that follows, so this is the
    ordering guarantee the tool makes.
    """
    first = tmp_path / "prog"
    second = tmp_path / "sub" / "prog"
    second.parent.mkdir()
    shutil.copy(fat_template, first)
    shutil.copy(fat_template, second)
    fat_size = first.stat().st_size

    code, plan = apply_plan(tmp_path, tmp_path_factory)
    assert code == 0
    kinds = {item["kind"] for item in plan["items"]}
    assert kinds == {dedupe.DUPLICATE, dedupe.UNIVERSAL}

    arch = dedupe.shrink.native_arch()
    for path in (first, second):
        assert path.stat().st_size < fat_size
        info = dedupe.shrink.inspect_macho(path, path.stat().st_size)
        assert info is not None and not info.is_fat
    assert first.read_bytes() == second.read_bytes()
    assert subprocess.run(["lipo", "-info", str(first)], capture_output=True,
                          text=True).stdout.strip().endswith(arch)


@needs_clang
def test_run_scans_and_applies_in_one_pass(fat_template: Path, tmp_path: Path,
                                           tmp_path_factory):
    data = payload(b"run")
    write(tmp_path / "a.bin", data)
    write(tmp_path / "b.bin", data)
    shutil.copy(fat_template, tmp_path / "prog")
    out = tmp_path_factory.mktemp("plan") / "plan.json"

    assert run_cli("run", str(tmp_path), "-o", str(out)) == 0
    plan = dedupe.load_plan(out)
    assert plan["items"]
    size = (tmp_path / "prog").stat().st_size
    assert not dedupe.shrink.inspect_macho(tmp_path / "prog", size).is_fat
    assert (tmp_path / "a.bin").read_bytes() == data


def test_nothing_to_do_is_success(tmp_path: Path, tmp_path_factory):
    write(tmp_path / "only", payload())
    out = tmp_path_factory.mktemp("plan") / "plan.json"
    assert run_cli("scan", str(tmp_path), "-o", str(out)) == 0
    assert json.loads(out.read_text())["items"] == []
    assert run_cli("apply", str(out)) == 0


def test_scan_can_be_narrowed_to_one_kind(tree: Path, tmp_path_factory):
    out = tmp_path_factory.mktemp("plan") / "plan.json"
    assert run_cli("scan", str(tree), "-o", str(out), "--no-duplicates") == 0
    assert json.loads(out.read_text())["items"] == []
