"""Tests for runtests.py, against fake runners in a temporary --root."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import runtests  # noqa: E402

FAKE_RUNNER = """
import json, os, sys
from pathlib import Path
log = Path(os.environ["RUNTESTS_LOG"])
with log.open("a") as f:
    f.write(json.dumps([Path(__file__).parents[1].name, Path.cwd().name, *sys.argv[1:]]) + "\\n")
fail = os.environ.get("RUNTESTS_FAIL", "")
backend = next((a for a in sys.argv if a.startswith("--") and a[2:] in {backends}), "")
key = Path(__file__).parents[1].name + " " + backend
sys.exit(3 if key == fail else 0)
""".replace("{backends}", repr(set(runtests.BACKENDS)))


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A --root with a fake runner per project that logs its argv and cwd."""
    for project, runner in runtests.RUNNERS.items():
        script = tmp_path / project / runner
        script.parent.mkdir(parents=True)
        script.write_text(FAKE_RUNNER)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("RUNTESTS_LOG", str(log))
    return tmp_path


def calls(root):
    import json

    path = root / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_default_plan_is_cuda_then_vulkan_test_all_per_project(root):
    assert runtests.main(["--root", str(root)]) == 0
    assert calls(root) == [
        ["cyllama", "cyllama", "run", "--cuda", "test-all"],
        ["cyllama", "cyllama", "run", "--vulkan", "test-all"],
        ["inferna", "inferna", "run", "--cuda", "test-all"],
        ["inferna", "inferna", "run", "--vulkan", "test-all"],
        ["chimera", "chimera", "run", "--cuda", "test-all"],
        ["chimera", "chimera", "run", "--vulkan", "test-all"],
    ]


def test_subset_backends_and_extra_args(root):
    argv = ["--root", str(root), "--vulkan", "--cpu", "--timeout", "600", "--args", "chimera=--bin build/chimera"]
    assert runtests.main([*argv, "chimera", "cyllama"]) == 0
    assert calls(root) == [
        ["chimera", "chimera", "run", "--vulkan", "--timeout", "600", "--bin", "build/chimera", "test-all"],
        ["chimera", "chimera", "run", "--cpu", "--timeout", "600", "--bin", "build/chimera", "test-all"],
        ["cyllama", "cyllama", "run", "--vulkan", "--timeout", "600", "test-all"],
        ["cyllama", "cyllama", "run", "--cpu", "--timeout", "600", "test-all"],
    ]


def test_fast_replaces_the_target(root):
    assert runtests.main(["--root", str(root), "--cuda", "--fast", "inferna"]) == 0
    assert calls(root) == [["inferna", "inferna", "run", "--cuda", "--fast"]]


def test_failure_continues_and_returns_worst(root, monkeypatch, capsys):
    monkeypatch.setenv("RUNTESTS_FAIL", "inferna --cuda")
    assert runtests.main(["--root", str(root)]) == 3
    assert len(calls(root)) == 6
    out = capsys.readouterr().out
    assert "inferna  cuda    FAIL (rc=3)" in out
    assert "chimera  vulkan  PASS" in out


def test_fail_fast_stops_and_lists_the_rest(root, monkeypatch, capsys):
    monkeypatch.setenv("RUNTESTS_FAIL", "cyllama --vulkan")
    assert runtests.main(["--root", str(root), "--fail-fast"]) == 3
    assert len(calls(root)) == 2
    assert "not run: inferna cuda, inferna vulkan, chimera cuda, chimera vulkan" in capsys.readouterr().out


def test_report_runs_last_runner(root):
    assert runtests.main(["--root", str(root), "--cpu", "cyllama", "chimera", "--report"]) == 0
    assert calls(root)[-1] == ["chimera", "chimera", "report", "--all-projects"]


def test_dry_run_runs_nothing(root, capsys):
    assert runtests.main(["--root", str(root), "--dry-run"]) == 0
    assert calls(root) == []
    assert capsys.readouterr().out.count("would run") == 6


def test_missing_runner(tmp_path, capsys):
    assert runtests.main(["--root", str(tmp_path), "--cpu", "cyllama"]) == 2
    assert "no runner at" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["--fast", "--step", "test"],
        ["--fast", "--target", "test-gen-1"],
        ["--args", "nope=--x"],
        ["--args", "chimera"],
        ["--version", "cyllama"],
        ["--version", "cyllama="],
        ["--version", "nope=1.0"],
        ["--version", "cyllama=0.5.1", "--step", "test"],
        ["notaproject"],
    ],
)
def test_bad_arguments(root, argv):
    with pytest.raises(SystemExit) as e:
        runtests.main(["--root", str(root), *argv])
    assert e.value.code == 2


def test_version_pins_per_project(root):
    argv = ["--root", str(root), "--cuda", "--version", "cyllama=0.5.1", "--version", "chimera=0.4.1"]
    assert runtests.main([*argv, "cyllama", "inferna", "chimera"]) == 0
    assert calls(root) == [
        ["cyllama", "cyllama", "run", "--cuda", "--version", "0.5.1", "test-all"],
        ["inferna", "inferna", "run", "--cuda", "test-all"],
        ["chimera", "chimera", "run", "--cuda", "--version", "0.4.1", "test-all"],
    ]
