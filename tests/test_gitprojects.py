#!/usr/bin/env python3
"""Tests for gitprojects.py"""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from gitprojects import clone, github, load, main, scan


def git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True)


@pytest.fixture
def remotes(tmp_path):
    """Two bare repos with one commit each, usable as clone URLs."""
    urls = {}
    for name in ("alpha", "beta"):
        work = tmp_path / "work" / name
        work.mkdir(parents=True)
        git("-C", str(work), "init", "-q")
        (work / "README").write_text(name)
        git("-C", str(work), "add", ".")
        git("-C", str(work), "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-qm", "init")
        bare = tmp_path / "remotes" / f"{name}.git"
        git("clone", "-q", "--bare", str(work), str(bare))
        urls[name] = str(bare)
    return urls


@pytest.fixture
def src(tmp_path):
    """A projects dir: two repos with origin, one without, one plain dir."""
    root = tmp_path / "src"
    for name, url in [("a", "https://github.com/u/a.git"), ("b", "git@github.com:u/b.git")]:
        (root / name).mkdir(parents=True)
        git("-C", str(root / name), "init", "-q")
        git("-C", str(root / name), "remote", "add", "origin", url)
    (root / "noremote").mkdir()
    git("-C", str(root / "noremote"), "init", "-q")
    (root / "plain").mkdir()
    return root


def test_scan(src, capsys):
    assert scan(src) == {"a": "https://github.com/u/a.git", "b": "git@github.com:u/b.git"}
    assert "noremote" in capsys.readouterr().err


def test_main_scan_writes_json(src, tmp_path):
    out = tmp_path / "projects.json"
    assert main(["scan", str(src), "-o", str(out)]) == 0
    assert json.loads(out.read_text())["a"] == "https://github.com/u/a.git"


def test_main_scan_rejects_non_directory(tmp_path):
    with pytest.raises(SystemExit):
        main(["scan", str(tmp_path / "missing")])


@pytest.mark.parametrize("data", [
    [], {"a": 1}, {"a": ""}, {"../x": "u"}, {"/abs": "u"}, {"a/b": "u"}, {"..": "u"}, {"": "u"},
])
def test_load_rejects_malformed(tmp_path, data):
    f = tmp_path / "p.json"
    f.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load(f)


def test_load_rejects_bad_json_via_main(tmp_path):
    f = tmp_path / "p.json"
    f.write_text("{not json")
    with pytest.raises(SystemExit):
        main(["clone", str(f), str(tmp_path / "dest")])


def test_clone_skips_existing(remotes, tmp_path, capsys):
    dest = tmp_path / "dest"
    (dest / "alpha").mkdir(parents=True)
    assert clone(remotes, dest) == []
    assert not (dest / "alpha" / "README").exists()
    assert (dest / "beta" / "README").read_text() == "beta"
    assert "exists, skipping: alpha" in capsys.readouterr().out


def test_clone_reports_failures(remotes, tmp_path):
    projects = {**remotes, "gone": str(tmp_path / "nope.git")}
    f = tmp_path / "p.json"
    f.write_text(json.dumps(projects))
    assert main(["clone", str(f), str(tmp_path / "dest")]) == 1
    assert (tmp_path / "dest" / "alpha" / "README").exists()


def test_roundtrip_scan_then_clone(remotes, tmp_path):
    first = tmp_path / "first"
    assert clone(remotes, first) == []
    f = tmp_path / "p.json"
    assert main(["scan", str(first), "-o", str(f)]) == 0
    assert main(["clone", str(f), str(tmp_path / "second")]) == 0
    assert (tmp_path / "second" / "beta" / "README").read_text() == "beta"


GH_OUT = json.dumps([
    {"name": "zed", "url": "https://github.com/u/zed", "sshUrl": "git@github.com:u/zed.git"},
    {"name": "abc", "url": "https://github.com/u/abc", "sshUrl": "git@github.com:u/abc.git"},
])


def fake_run(stdout):
    def run(cmd, **kw):
        run.cmd = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
    return run


def test_github_https_sorted():
    run = fake_run(GH_OUT)
    with patch("gitprojects.subprocess.run", run):
        result = github("u", 50, ssh=False, source=True, no_archived=False)
    assert list(result) == ["abc", "zed"]
    assert result["abc"] == "https://github.com/u/abc"
    assert run.cmd[:4] == ["gh", "repo", "list", "u"]
    assert "--source" in run.cmd and "--no-archived" not in run.cmd
    assert run.cmd[run.cmd.index("--json") + 1] == "name,url"


def test_github_ssh():
    with patch("gitprojects.subprocess.run", fake_run(GH_OUT)):
        result = github("u", 50, ssh=True, source=False, no_archived=True)
    assert result["zed"] == "git@github.com:u/zed.git"


def test_main_github_requires_gh(tmp_path):
    with patch("gitprojects.shutil.which", return_value=None), pytest.raises(SystemExit):
        main(["github", "u", "-o", str(tmp_path / "p.json")])


def test_main_github_reports_gh_failure(tmp_path, capsys):
    err = subprocess.CalledProcessError(1, ["gh"], stderr="Could not resolve to a User\n")
    with patch("gitprojects.shutil.which", return_value="/bin/gh"), \
         patch("gitprojects.subprocess.run", side_effect=err):
        assert main(["github", "u", "-o", str(tmp_path / "p.json")]) == 1
    assert "Could not resolve" in capsys.readouterr().err
    assert not (tmp_path / "p.json").exists()


def test_main_github_writes_json(tmp_path):
    out = tmp_path / "p.json"
    with patch("gitprojects.shutil.which", return_value="/bin/gh"), \
         patch("gitprojects.subprocess.run", fake_run(GH_OUT)):
        assert main(["github", "u", "-o", str(out)]) == 0
    assert json.loads(out.read_text()) == {
        "abc": "https://github.com/u/abc", "zed": "https://github.com/u/zed"}
