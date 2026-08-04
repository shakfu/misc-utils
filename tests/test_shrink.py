"""Tests for the `shrink` universal-binary thinner.

Run with `make test` from /Users/sa/bin, or `pytest tests/`.
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

BIN = Path(__file__).resolve().parent.parent
SHRINK_PATH = BIN / "shrink"

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="shrink is macOS-only")


def _load_shrink():
    spec = importlib.util.spec_from_loader(
        "shrink_module", importlib.machinery.SourceFileLoader("shrink_module", str(SHRINK_PATH))
    )
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations through sys.modules, so register first.
    sys.modules["shrink_module"] = module
    spec.loader.exec_module(module)
    return module


shrink = _load_shrink()

HAVE_CLANG = shutil.which("clang") is not None
needs_clang = pytest.mark.skipif(not HAVE_CLANG, reason="clang required to build test binaries")

SOURCE = "int main(void){return 0;}\n"


@pytest.fixture(scope="session")
def source_file(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("src") / "t.c"
    path.write_text(SOURCE)
    return path


def _build(source: Path, out: Path, *arches: str) -> Path:
    cmd = ["clang"]
    for arch in arches:
        cmd += ["-arch", arch]
    cmd += ["-o", str(out), str(source)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


@pytest.fixture(scope="session")
def fat_binary(source_file, tmp_path_factory) -> Path:
    return _build(source_file, tmp_path_factory.mktemp("fat") / "fat", "arm64", "x86_64")


@pytest.fixture(scope="session")
def thin_binary(source_file, tmp_path_factory) -> Path:
    return _build(source_file, tmp_path_factory.mktemp("thin") / "thin", shrink.native_arch())


@pytest.fixture(scope="session")
def foreign_binary(source_file, tmp_path_factory) -> Path:
    """A thin binary that deliberately lacks the host architecture."""
    other = "x86_64" if shrink.native_arch() == "arm64" else "arm64"
    return _build(source_file, tmp_path_factory.mktemp("foreign") / "foreign", other)


@pytest.fixture(scope="session")
def fat_foreign_binary(source_file, tmp_path_factory) -> Path:
    """A *universal* binary whose slices are all foreign to the host."""
    arches = ("x86_64", "x86_64h") if shrink.native_arch() == "arm64" else ("arm64", "arm64e")
    out = tmp_path_factory.mktemp("fatforeign") / "fatforeign"
    try:
        parts = [_build(source_file, out.with_suffix(f".{a}"), a) for a in arches]
        subprocess.run(["lipo", "-create", *map(str, parts), "-output", str(out)],
                       check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"cannot build a foreign universal binary here: {exc}")
    return out


def make_bundle(root: Path, name: str, executable: Path, resources: bool = True) -> Path:
    bundle = root / name
    macos = bundle / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    shutil.copy2(executable, macos / "Demo")
    (bundle / "Contents" / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<plist version="1.0"><dict>'
        "<key>CFBundleExecutable</key><string>Demo</string>"
        "<key>CFBundleIdentifier</key><string>com.test.demo</string>"
        "<key>CFBundlePackageType</key><string>APPL</string>"
        "</dict></plist>\n"
    )
    if resources:
        res = bundle / "Contents" / "Resources"
        res.mkdir()
        (res / "data.txt").write_text("payload\n")
        (res / "link").symlink_to("data.txt")
    return bundle


def archs_of(path: Path) -> set[str]:
    out = subprocess.run(["lipo", "-archs", str(path)], capture_output=True, text=True)
    return set(out.stdout.split())


def run_process(target: Path, **kwargs):
    """Mirrors the CLI defaults: in-place unless --copy is given."""
    options = dict(in_place=True, dry_run=False, check_signature=True)
    options.update(kwargs)
    return shrink.process(target, shrink.native_arch(), **options)


# ---------------------------------------------------------------------------
# Mach-O inspection
# ---------------------------------------------------------------------------


@needs_clang
def test_inspect_detects_fat_slices(fat_binary):
    info = shrink.inspect_macho(fat_binary, fat_binary.stat().st_size)
    assert info is not None and info.is_fat
    assert {s.family for s in info.slices} == {"arm64", "x86_64"}
    assert all(s.size > 0 for s in info.slices)


@needs_clang
def test_inspect_detects_thin_binary(thin_binary):
    info = shrink.inspect_macho(thin_binary, thin_binary.stat().st_size)
    assert info is not None and not info.is_fat


def test_inspect_rejects_non_macho(tmp_path):
    path = tmp_path / "plain.txt"
    path.write_text("not a binary at all")
    assert shrink.inspect_macho(path, path.stat().st_size) is None


def test_inspect_rejects_java_class_file(tmp_path):
    """0xCAFEBABE is also the Java class magic; a version number is not a slice count."""
    path = tmp_path / "Foo.class"
    path.write_bytes(struct.pack(">II", 0xCAFEBABE, 0x00000041) + b"\x00" * 64)
    assert shrink.inspect_macho(path, path.stat().st_size) is None


def test_inspect_rejects_out_of_bounds_fat_header(tmp_path):
    path = tmp_path / "bogus"
    header = struct.pack(">II", 0xCAFEBABE, 1)
    entry = struct.pack(">iiIII", 0x01000007, 3, 4096, 1 << 30, 12)
    path.write_bytes(header + entry)
    assert shrink.inspect_macho(path, path.stat().st_size) is None


# ---------------------------------------------------------------------------
# The data-loss regression: never thin away the only slice
# ---------------------------------------------------------------------------


@needs_clang
def test_refuses_universal_bundle_without_host_arch(tmp_path, fat_foreign_binary):
    """The bug that destroyed bundles: ditto exits 0 while dropping the executable."""
    bundle = make_bundle(tmp_path, "Foreign.app", fat_foreign_binary)
    executable = bundle / "Contents" / "MacOS" / "Demo"
    before = executable.read_bytes()

    result = run_process(bundle)

    assert result.status == shrink.SKIPPED
    assert "not contain" in result.reason
    assert executable.exists(), "the original executable must survive a refused thin"
    assert executable.read_bytes() == before


@needs_clang
def test_mixed_bundle_is_refused_by_the_copy_strategy(tmp_path, fat_binary, fat_foreign_binary):
    """ditto is all-or-nothing per target, so a copy must not be attempted here."""
    bundle = make_bundle(tmp_path, "Mixed.app", fat_binary)
    foreign = bundle / "Contents" / "Resources" / "Legacy.a"
    shutil.copy2(fat_foreign_binary, foreign)
    before = (bundle / "Contents" / "MacOS" / "Demo").read_bytes()

    result = run_process(bundle, in_place=False)

    assert result.status == shrink.SKIPPED
    assert "drop --copy" in result.reason
    assert (bundle / "Contents" / "MacOS" / "Demo").read_bytes() == before
    assert foreign.exists()


@needs_clang
def test_mixed_bundle_thins_what_it_can_in_place(tmp_path, fat_binary, fat_foreign_binary):
    bundle = make_bundle(tmp_path, "Mixed.app", fat_binary)
    foreign = bundle / "Contents" / "Resources" / "Legacy.a"
    shutil.copy2(fat_foreign_binary, foreign)
    foreign_before = foreign.read_bytes()

    result = run_process(bundle, in_place=True)

    assert result.status == shrink.THINNED, result.reason
    assert archs_of(bundle / "Contents" / "MacOS" / "Demo") == {shrink.native_arch()}
    assert foreign.read_bytes() == foreign_before, "binaries without the target arch stay untouched"
    assert "leaving 1 binary alone" in result.detail


@needs_clang
def test_ditto_alone_would_have_destroyed_it(tmp_path, fat_foreign_binary):
    """Documents why the pre-check exists: ditto succeeds and produces no executable."""
    bundle = make_bundle(tmp_path, "Victim.app", fat_foreign_binary)
    copy = tmp_path / "Victim.app__tmp"
    proc = subprocess.run(
        ["ditto", "--arch", shrink.native_arch(), str(bundle), str(copy)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, "ditto reports success even when it drops binaries"
    assert not (copy / "Contents" / "MacOS" / "Demo").exists()


@needs_clang
def test_thin_foreign_binary_is_left_alone(tmp_path, foreign_binary):
    lib = tmp_path / "libforeign.so"
    shutil.copy2(foreign_binary, lib)
    result = run_process(lib)
    assert result.status == shrink.SKIPPED
    assert "already single-architecture" in result.reason
    assert lib.exists() and lib.stat().st_size > 0


def test_verify_copy_flags_missing_files(tmp_path):
    src = tmp_path / "src"
    (src / "Contents").mkdir(parents=True)
    (src / "Contents" / "a.txt").write_text("a")
    (src / "Contents" / "b.txt").write_text("b")
    before = shrink.scan(src)

    dst = tmp_path / "dst"
    (dst / "Contents").mkdir(parents=True)
    (dst / "Contents" / "a.txt").write_text("a")
    after = shrink.scan(dst)

    problem = shrink.verify_copy(before, after)
    assert problem is not None and "missing" in problem


def test_verify_copy_accepts_faithful_copy(tmp_path):
    src = tmp_path / "src"
    (src / "Contents").mkdir(parents=True)
    (src / "Contents" / "a.txt").write_text("a")
    (src / "Contents" / "link").symlink_to("a.txt")
    shutil.copytree(src, tmp_path / "dst", symlinks=True)
    assert shrink.verify_copy(shrink.scan(src), shrink.scan(tmp_path / "dst")) is None


# ---------------------------------------------------------------------------
# Thinning, both strategies
# ---------------------------------------------------------------------------


@needs_clang
@pytest.mark.parametrize("in_place", [False, True])
def test_thins_bundle_and_preserves_contents(tmp_path, fat_binary, in_place):
    bundle = make_bundle(tmp_path, "Demo.app", fat_binary)
    executable = bundle / "Contents" / "MacOS" / "Demo"
    assert len(archs_of(executable)) == 2

    result = run_process(bundle, in_place=in_place)

    assert result.status == shrink.THINNED, result.reason
    assert archs_of(executable) == {shrink.native_arch()}
    assert result.after < result.before
    assert (bundle / "Contents" / "Resources" / "data.txt").read_text() == "payload\n"
    assert (bundle / "Contents" / "Resources" / "link").is_symlink()
    assert (bundle / "Contents" / "Info.plist").exists()
    assert os.access(executable, os.X_OK)


@needs_clang
@pytest.mark.parametrize("in_place", [False, True])
def test_thins_bare_binary(tmp_path, fat_binary, in_place):
    lib = tmp_path / "libdemo.dylib"
    shutil.copy2(fat_binary, lib)
    result = run_process(lib, in_place=in_place)
    assert result.status == shrink.THINNED, result.reason
    assert archs_of(lib) == {shrink.native_arch()}


@pytest.fixture(scope="session")
def fat_archive(source_file, tmp_path_factory) -> Path:
    """A universal static library: a fat wrapper around per-arch ar archives."""
    work = tmp_path_factory.mktemp("archive")
    parts = []
    for arch in ("arm64", "x86_64"):
        obj = work / f"o_{arch}.o"
        lib = work / f"lib_{arch}.a"
        subprocess.run(["clang", "-c", "-arch", arch, "-o", str(obj), str(source_file)],
                       check=True, capture_output=True)
        subprocess.run(["ar", "rcs", str(lib), str(obj)], check=True, capture_output=True)
        parts.append(lib)
    out = work / "libfat.a"
    subprocess.run(["lipo", "-create", *map(str, parts), "-output", str(out)],
                   check=True, capture_output=True)
    return out


@needs_clang
@pytest.mark.parametrize("in_place", [False, True])
def test_thins_universal_static_library(tmp_path, fat_archive, in_place):
    """Thinning a fat .a yields an ar archive, not a Mach-O file; that must be accepted."""
    lib = tmp_path / "libdemo.a"
    shutil.copy2(fat_archive, lib)
    assert len(archs_of(lib)) == 2

    result = run_process(lib, in_place=in_place)

    assert result.status == shrink.THINNED, result.reason
    assert archs_of(lib) == {shrink.native_arch()}
    assert lib.read_bytes()[:8] == b"!<arch>\n"


def test_inspect_accepts_ar_archives(tmp_path):
    path = tmp_path / "lib.a"
    path.write_bytes(b"!<arch>\n" + b"\x00" * 64)
    info = shrink.inspect_macho(path, path.stat().st_size)
    assert info is not None and not info.is_fat


@needs_clang
def test_thinned_bundle_keeps_a_valid_signature(tmp_path, fat_binary):
    bundle = make_bundle(tmp_path, "Signed.app", fat_binary)
    subprocess.run(["codesign", "-s", "-", "--force", str(bundle)], check=True, capture_output=True)
    assert shrink.is_signed(bundle)

    result = run_process(bundle)

    assert result.status == shrink.THINNED, result.reason
    assert shrink.is_signed(bundle), "thinning must not invalidate the code signature"


@needs_clang
def test_second_run_is_a_no_op(tmp_path, fat_binary):
    bundle = make_bundle(tmp_path, "Twice.app", fat_binary)
    assert run_process(bundle).status == shrink.THINNED
    again = run_process(bundle)
    assert again.status == shrink.SKIPPED
    assert "already single-architecture" in again.reason


@needs_clang
def test_dry_run_changes_nothing(tmp_path, fat_binary):
    bundle = make_bundle(tmp_path, "Dry.app", fat_binary)
    executable = bundle / "Contents" / "MacOS" / "Demo"
    before = executable.read_bytes()

    result = run_process(bundle, dry_run=True)

    assert result.status == shrink.PLANNED
    assert result.after < result.before, "a dry run should still estimate the saving"
    assert executable.read_bytes() == before


@needs_clang
@pytest.mark.parametrize("name", [
    "My App {weird}.app",
    'Quote"s.app',
    "Semi;colon && rm.app",
    "Dollar $HOME `x`.app",
    "Spaces  and 'ticks'.app",
])
def test_handles_hostile_filenames(tmp_path, fat_binary, name):
    """Regression: the previous implementation went through os.system + str.format."""
    bundle = make_bundle(tmp_path, name, fat_binary)
    result = run_process(bundle)
    assert result.status == shrink.THINNED, result.reason
    assert archs_of(bundle / "Contents" / "MacOS" / "Demo") == {shrink.native_arch()}
    assert sorted(p.name for p in tmp_path.iterdir()) == [name], "no stray scratch files"


@needs_clang
def test_no_scratch_directories_left_behind(tmp_path, fat_binary):
    bundle = make_bundle(tmp_path, "Clean.app", fat_binary)
    run_process(bundle)
    leftovers = [p.name for p in tmp_path.rglob("*shrink-*")]
    assert leftovers == []


def test_skips_symlinked_target(tmp_path):
    real = tmp_path / "Real.app"
    real.mkdir()
    link = tmp_path / "Link.app"
    link.symlink_to(real)
    result = run_process(link)
    assert result.status == shrink.SKIPPED
    assert "symlink" in result.reason
    assert link.is_symlink()


def test_missing_target_fails(tmp_path):
    result = run_process(tmp_path / "Nope.app")
    assert result.status == shrink.FAILED
    assert "no such" in result.reason.lower()


def test_directory_without_binaries_is_skipped(tmp_path):
    plain = tmp_path / "Empty.bundle"
    (plain / "Contents").mkdir(parents=True)
    (plain / "Contents" / "readme.txt").write_text("hello")
    result = run_process(plain)
    assert result.status == shrink.SKIPPED
    assert "no Mach-O" in result.reason


# ---------------------------------------------------------------------------
# Discovery, arch detection and CLI
# ---------------------------------------------------------------------------


def test_discover_matches_only_known_suffixes(tmp_path):
    for name in ("A.app", "B.vst3", "C.txt", "D.bundle"):
        (tmp_path / name).mkdir()
    found = {p.name for p in shrink.discover(tmp_path, shrink.DEFAULT_ENDINGS, recursive=False)}
    assert found == {"A.app", "B.vst3", "D.bundle"}


def test_discover_recursive_does_not_descend_into_matches(tmp_path):
    outer = tmp_path / "sub" / "Outer.app"
    (outer / "Contents" / "Frameworks" / "Inner.framework").mkdir(parents=True)
    found = {p.name for p in shrink.discover(tmp_path, shrink.DEFAULT_ENDINGS, recursive=True)}
    assert found == {"Outer.app"}, "nested bundles are handled by thinning the outer one"


def test_cli_defaults_to_in_place():
    parser = shrink.build_parser()
    assert parser.parse_args([]).copy is False, "the default strategy is in-place"
    assert parser.parse_args(["--copy"]).copy is True
    assert parser.parse_args(["--in-place"]).copy is False


def test_cli_rejects_both_strategies():
    with pytest.raises(SystemExit):
        shrink.build_parser().parse_args(["--copy", "--in-place"])


@needs_clang
def test_cli_default_run_thins_a_mixed_bundle(tmp_path, fat_binary, fat_foreign_binary,
                                              monkeypatch, capsys):
    """End to end: the default strategy thins what it can instead of refusing."""
    bundle = make_bundle(tmp_path, "Mixed.app", fat_binary)
    foreign = bundle / "Contents" / "Resources" / "Legacy.a"
    shutil.copy2(fat_foreign_binary, foreign)
    foreign_before = foreign.read_bytes()
    monkeypatch.chdir(tmp_path)
    for handler in list(shrink.LOG.handlers):
        shrink.LOG.removeHandler(handler)

    assert shrink.main(["--quiet"]) == 0

    assert archs_of(bundle / "Contents" / "MacOS" / "Demo") == {shrink.native_arch()}
    assert foreign.read_bytes() == foreign_before


def test_native_arch_is_a_real_arch():
    assert shrink.native_arch() in {"arm64", "x86_64"}


def test_human_readable_sizes():
    assert shrink.human(512) == "512B"
    assert shrink.human(1536) == "1.5KB"
    assert shrink.human(5 * 1024 * 1024) == "5.0MB"


@needs_clang
def test_cli_dry_run_reports_json(tmp_path, fat_binary, monkeypatch, capsys):
    make_bundle(tmp_path, "Cli.app", fat_binary)
    monkeypatch.chdir(tmp_path)
    for handler in list(shrink.LOG.handlers):
        shrink.LOG.removeHandler(handler)

    code = shrink.main(["--dry-run", "--json", "--quiet"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["arch"] == shrink.native_arch()
    assert [r["status"] for r in payload["results"]] == [shrink.PLANNED]
    assert payload["results"][0]["bytes_saved"] > 0


@needs_clang
def test_cli_exit_code_is_one_on_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for handler in list(shrink.LOG.handlers):
        shrink.LOG.removeHandler(handler)
    assert shrink.main(["--quiet", str(tmp_path / "Missing.app")]) == 1
