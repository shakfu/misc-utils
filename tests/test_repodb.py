#!/usr/bin/env python3
"""Tests for repodb.py"""

import json
import sqlite3
import subprocess
from unittest.mock import patch

import pytest

from repodb import (GitRepoDB, clone, flatten, github, host_of, info, main, owner_of,
                    read_pairs, scan)

HOST = "https://git.example.com/"


def git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True)


@pytest.fixture
def remotes(tmp_path, monkeypatch):
    """Bare repos alice/alpha, alice/beta, bob/alpha, reachable at HOST/<owner>/<name>.git.

    git's url.<base>.insteadOf, set through GIT_CONFIG_* env vars, rewrites
    HOST to the local directory, so clones are real but need no network.
    """
    root = tmp_path / "remotes"
    urls = {}
    for owner, name in [("alice", "alpha"), ("alice", "beta"), ("bob", "alpha")]:
        work = tmp_path / "work" / owner / name
        work.mkdir(parents=True)
        git("-C", str(work), "init", "-q")
        (work / "README").write_text(f"{owner}/{name}")
        git("-C", str(work), "add", ".")
        git("-C", str(work), "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-qm", "init")
        git("clone", "-q", "--bare", str(work), str(root / owner / f"{name}.git"))
        urls[owner, name] = f"{HOST}{owner}/{name}.git"
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.{root}/.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", HOST)
    return urls


@pytest.fixture
def src(tmp_path):
    """A projects dir: repos with owned origins, one local origin, one without, a plain dir."""
    root = tmp_path / "src"
    for name, url in [("a", "https://github.com/u/a.git"), ("b", "git@gitlab.com:v/b.git"),
                      ("local", "/some/path/local.git")]:
        (root / name).mkdir(parents=True)
        git("-C", str(root / name), "init", "-q")
        git("-C", str(root / name), "remote", "add", "origin", url)
    (root / "noremote").mkdir()
    git("-C", str(root / "noremote"), "init", "-q")
    (root / "plain").mkdir()
    return root


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "state" / "repos.sqlite"


def run(db_path, *args):
    return main(["--db", str(db_path), *map(str, args)])


def write_json(path, data):
    path.write_text(json.dumps(data))
    return path


def cloned_targets(sp):
    return [c.args[0][-1] for c in sp.call_args_list]


@pytest.fixture
def fake_git():
    with patch("repodb.subprocess.run") as sp:
        sp.return_value = subprocess.CompletedProcess([], 0)
        yield sp


@pytest.mark.parametrize("url, owner", [
    ("https://github.com/u/r.git", "u"),
    ("https://github.com/u/r", "u"),
    ("http://GitHub.com/u/r", "u"),
    ("git@github.com:u/r.git", "u"),
    ("ssh://git@github.com/u/r", "u"),
    ("ssh://git@ssh.github.com:443/u/r", "u"),
    ("git+ssh://git@github.com/u/r", "u"),
    ("https://gitlab.com/u/r.git", "u"),
    ("https://gitlab.com/group/sub/r.git", "group"),
    ("https://codeberg.org/u/r.git", "u"),
    ("https://github.com/u", None),
    ("/local/path/r.git", None),
    ("file:///local/path/r.git", None),
    ("./a/b", None),
])
def test_owner_of(url, owner):
    assert owner_of(url) == owner


@pytest.mark.parametrize("url, host", [
    ("https://GitHub.com/u/r", "github.com"),
    ("git@gitlab.com:u/r.git", "gitlab.com"),
    ("ssh://git@codeberg.org:22/u/r", "codeberg.org"),
    ("/local/r.git", None),
])
def test_host_of(url, host):
    assert host_of(url) == host


class TestInfo:
    def fields(self, lines):
        return {k: v.strip() for k, v in (line.split(":", 1) for line in lines)}

    def test_current(self, db_path):
        with GitRepoDB(db_path) as db:
            db.add([("r", "https://github.com/alice/r"), ("s", "git@github.com:Alice/s.git"),
                    ("r", "https://gitlab.com/bob/r"), ("t", "https://github.com/carol/t")])
        f = self.fields(info(db_path, top=2))
        assert f["database"].startswith(f"{db_path} (")
        assert f["format"] == "current, keyed by (owner, name)"
        assert f["projects"] == "4"
        assert f["owners"] == "3"
        assert f["hosts"] == "github.com 3, gitlab.com 1"
        assert f["top owners"] == "alice 2, bob 1"
        assert f["shared names"] == "r (alice, bob)"
        assert "no owner" not in f

    def test_unsupported_schema(self, db_path):
        old_db(db_path, [("r", "https://github.com/a/r", "a")])
        f = self.fields(info(db_path))
        assert f["format"] == "unsupported (primary key ['name'])"
        assert list(f) == ["database", "format"]

    def test_empty_file(self, tmp_path):
        empty = tmp_path / "empty.sqlite"
        sqlite3.connect(empty).close()
        f = self.fields(info(empty))
        assert f["format"] == "no repos table"
        assert list(f) == ["database", "format"]

    def test_main(self, db_path, capsys):
        with GitRepoDB(db_path) as db:
            db.add([("r", "https://github.com/a/r")])
        capsys.readouterr()
        assert run(db_path, "info") == 0
        out = capsys.readouterr().out.splitlines()
        assert out[0] == f"database:     {db_path} ({db_path.stat().st_size / 1024:.1f}KB)"
        # Every value starts in the same column.
        assert {len(line) - len(line.split(":", 1)[1].lstrip()) for line in out} == {14}

    def test_main_missing_does_not_create(self, db_path, capsys):
        assert run(db_path, "info") == 1
        assert f"no database at {db_path}" in capsys.readouterr().err
        assert not db_path.parent.exists()

    def test_main_not_sqlite(self, tmp_path, capsys):
        bad = tmp_path / "bad.sqlite"
        bad.write_text("not a database" * 100)
        assert run(bad, "info") == 1
        assert "bad.sqlite" in capsys.readouterr().err


class TestGitRepoDB:
    def test_creates_parent_dir(self, db_path):
        with GitRepoDB(db_path):
            pass
        assert db_path.is_file()

    def test_same_name_different_owners(self, db_path):
        with GitRepoDB(db_path) as db:
            db.add([("r", "https://github.com/alice/r"), ("r", "git@gitlab.com:bob/r.git")])
            assert db.rows() == [("alice", "r", "https://github.com/alice/r"),
                                 ("bob", "r", "git@gitlab.com:bob/r.git")]

    def test_add_updates_changed_url(self, db_path, capsys):
        with GitRepoDB(db_path) as db:
            db.add([("r", "https://github.com/a/r")])
            db.add([("r", "https://github.com/a/r")])
            db.add([("r", "git@github.com:A/r.git")])  # owner and key match case-insensitively
            assert db.rows() == [("a", "r", "git@github.com:A/r.git")]
        assert capsys.readouterr().out.splitlines() == [
            "added: a/r <- https://github.com/a/r",
            "updated: A/r <- git@github.com:A/r.git",
        ]

    def test_add_rejects_ownerless_url_atomically(self, db_path, capsys):
        with GitRepoDB(db_path) as db:
            with pytest.raises(ValueError, match="no owner"):
                db.add([("ok", "https://github.com/a/ok"), ("bad", "/x/bad")])
            assert db.rows() == []
        assert capsys.readouterr().out == ""  # no "added:" for a rolled-back row

    @pytest.mark.parametrize("owner, name", [(None, "r"), ("", "r"), ("a", ""), ("a", None)])
    def test_schema_rejects_empty_or_null(self, db_path, owner, name):
        with GitRepoDB(db_path) as db, pytest.raises(sqlite3.IntegrityError):
            db.conn.execute("INSERT INTO repos (owner, name, url) VALUES (?, ?, 'u')",
                            (owner, name))

    def test_rows_owner_filter_is_case_insensitive(self, db_path):
        with GitRepoDB(db_path) as db:
            db.add([("z", "https://github.com/Alice/z"), ("a", "https://github.com/alice/a"),
                    ("o", "https://github.com/bob/o")])
            assert [n for _, n, _ in db.rows("ALICE")] == ["a", "z"]

    def test_by_owner(self, db_path):
        with GitRepoDB(db_path) as db:
            db.add([("z", "https://github.com/bob/z"), ("b", "git@github.com:Alice/b.git"),
                    ("a", "https://github.com/alice/a")])
            # Mixed-case owners share a group, spelled as in its first project by name.
            assert db.by_owner() == {
                "alice": {"a": "https://github.com/alice/a", "b": "git@github.com:Alice/b.git"},
                "bob": {"z": "https://github.com/bob/z"},
            }

    def test_remove(self, db_path):
        with GitRepoDB(db_path) as db:
            db.add([("r", "https://github.com/alice/r"), ("r", "https://github.com/bob/r"),
                    ("s", "https://github.com/bob/s")])
            assert db.remove(["ALICE/r", "s"]) == [("alice", "r", "https://github.com/alice/r"),
                                                   ("bob", "s", "https://github.com/bob/s")]
            assert db.rows() == [("bob", "r", "https://github.com/bob/r")]

    @pytest.mark.parametrize("specs, message", [
        (["alice/s", "missing"], "'missing': no such project"),
        (["alice/s", "r"], "'r': ambiguous, use one of alice/r, bob/r"),
        (["carol/r"], "'carol/r': no such project"),
    ])
    def test_remove_is_atomic(self, db_path, specs, message):
        with GitRepoDB(db_path) as db:
            db.add([("r", "https://github.com/alice/r"), ("r", "https://github.com/bob/r"),
                    ("s", "https://github.com/alice/s")])
            with pytest.raises(ValueError) as e:
                db.remove(specs)
            assert str(e.value) == message
            assert len(db.rows()) == 3

    def test_persists_across_connections(self, db_path):
        with GitRepoDB(db_path) as db:
            db.add([("r", "https://github.com/a/r")])
        with GitRepoDB(db_path) as db:
            assert db.rows() == [("a", "r", "https://github.com/a/r")]


def old_db(path, rows):
    """Create a table keyed by name alone, the pre-(owner, name) layout."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE repos ("
                 " name TEXT PRIMARY KEY, url TEXT NOT NULL, owner TEXT COLLATE NOCASE)")
    conn.executemany("INSERT INTO repos VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


class TestUnsupportedSchema:
    def test_open_refuses_and_leaves_table(self, db_path):
        old_db(db_path, [("r", "https://github.com/a/r", "a")])
        with pytest.raises(ValueError, match=r"unsupported schema, primary key \['name'\]"):
            GitRepoDB(db_path)
        conn = sqlite3.connect(db_path)
        assert conn.execute("SELECT name, url FROM repos").fetchall() == [
            ("r", "https://github.com/a/r")]

    def test_main_exits_1(self, db_path, capsys):
        old_db(db_path, [])
        with pytest.raises(SystemExit) as e:
            run(db_path, "list")
        assert "unsupported schema" in str(e.value.code)


def test_scan(src, capsys):
    assert scan(src) == [("a", "https://github.com/u/a.git"), ("b", "git@gitlab.com:v/b.git")]
    err = capsys.readouterr().err
    assert "no origin, skipping: noremote" in err
    assert "no owner in origin url, skipping: local" in err


def test_flatten_rejects_repeated_name():
    with pytest.raises(ValueError, match="'r': held by more than one owner; use --group"):
        flatten([("r", "u1"), ("r", "u2")])


def test_flatten_ignores_case():
    # Foo and foo are one directory on a case-insensitive filesystem.
    with pytest.raises(ValueError, match="'foo': held by more than one owner \\(as 'Foo'\\)"):
        flatten([("Foo", "u1"), ("foo", "u2")])
    assert flatten([("a", "u1"), ("b", "u2")]) == {"a": "u1", "b": "u2"}


@pytest.mark.parametrize("data", [
    [], {"a": 1}, {"a": ""}, {"../x": "u"}, {"/abs": "u"}, {"a/b": "u"}, {"..": "u"}, {"": "u"},
    {"o": {"a": 1}}, {"o": {"../x": "u"}}, {"o": {"a": "u"}, "b": "u"},
])
def test_read_pairs_rejects_malformed(tmp_path, data):
    with pytest.raises(ValueError):
        read_pairs(write_json(tmp_path / "p.json", data))


def test_read_pairs_grouped_keeps_repeated_names(tmp_path):
    f = write_json(tmp_path / "p.json", {"x": {"r": "https://github.com/a/r"},
                                         "y": {"r": "https://github.com/b/r"}})
    assert read_pairs(f) == [("r", "https://github.com/a/r"), ("r", "https://github.com/b/r")]


class TestClone:
    def test_flat_skips_existing(self, remotes, tmp_path, capsys):
        dest = tmp_path / "dest"
        (dest / "alpha").mkdir(parents=True)
        rows = [("alice", "alpha", remotes["alice", "alpha"]),
                ("alice", "beta", remotes["alice", "beta"])]
        assert clone(rows, dest) == []
        assert not (dest / "alpha" / "README").exists()
        assert (dest / "beta" / "README").read_text() == "alice/beta"
        assert "exists, skipping: alpha" in capsys.readouterr().out

    def test_by_owner(self, remotes, tmp_path):
        dest = tmp_path / "dest"
        rows = [(o, n, u) for (o, n), u in remotes.items()]
        assert clone(rows, dest, by_owner=True) == []
        assert (dest / "alice" / "alpha" / "README").read_text() == "alice/alpha"
        assert (dest / "bob" / "alpha" / "README").read_text() == "bob/alpha"

    def test_rejects_unsafe_name(self, tmp_path, fake_git):
        assert clone([("a", "../escape", "u")], tmp_path) == ["../escape"]
        fake_git.assert_not_called()

    def test_by_owner_rejects_unsafe_owner(self, tmp_path, fake_git):
        rows = [(owner_of("https://github.com/../r"), "r", "https://github.com/../r")]
        assert clone(rows, tmp_path, by_owner=True) == ["../r"]
        fake_git.assert_not_called()

    def test_by_owner_fails_ownerless(self, tmp_path, fake_git):
        assert clone([(None, "l", "/x/l")], tmp_path, by_owner=True) == ["l"]
        fake_git.assert_not_called()

    def test_reports_git_failure(self, remotes, tmp_path):
        rows = [("alice", "alpha", remotes["alice", "alpha"]),
                ("alice", "gone", f"{HOST}alice/gone.git")]
        assert clone(rows, tmp_path / "dest") == ["gone"]
        assert (tmp_path / "dest" / "alpha" / "README").exists()


class TestMain:
    def test_scan_export_roundtrip(self, src, db_path, tmp_path):
        out = tmp_path / "p.json"
        assert run(db_path, "scan", src) == 0
        assert run(db_path, "export", "-o", out) == 0
        assert json.loads(out.read_text()) == {
            "a": "https://github.com/u/a.git", "b": "git@gitlab.com:v/b.git"}

    def test_scan_rejects_non_directory(self, db_path, tmp_path):
        with pytest.raises(SystemExit):
            run(db_path, "scan", tmp_path / "missing")

    def test_export_owner_filter(self, src, db_path, tmp_path):
        out = tmp_path / "p.json"
        run(db_path, "scan", src)
        assert run(db_path, "export", "--owner", "V", "-o", out) == 0
        assert json.loads(out.read_text()) == {"b": "git@gitlab.com:v/b.git"}

    def test_export_flat_rejects_repeated_name(self, remotes, db_path, tmp_path, capsys):
        with GitRepoDB(db_path) as db:
            db.add([(n, u) for (_, n), u in remotes.items()])
        with pytest.raises(SystemExit):
            run(db_path, "export", "-o", tmp_path / "p.json")
        assert "'alpha': held by more than one owner; use --group" in capsys.readouterr().err
        assert not (tmp_path / "p.json").exists()

    def test_export_grouped_roundtrip(self, remotes, db_path, tmp_path):
        with GitRepoDB(db_path) as db:
            db.add([(n, u) for (_, n), u in remotes.items()])
        out = tmp_path / "p.json"
        assert run(db_path, "export", "-g", "-o", out) == 0
        assert json.loads(out.read_text()) == {
            "alice": {"alpha": remotes["alice", "alpha"], "beta": remotes["alice", "beta"]},
            "bob": {"alpha": remotes["bob", "alpha"]},
        }
        other = tmp_path / "other.sqlite"
        assert run(other, "import", out) == 0
        with GitRepoDB(db_path) as a, GitRepoDB(other) as b:
            assert a.rows() == b.rows()

    # Mixed hosts, URL forms, and owner case. Names are unique so the flat form holds them.
    ROUNDTRIP = [
        ("b", "git@github.com:Alice/b.git"),
        ("a", "https://github.com/alice/a"),
        ("t", "https://gitlab.com/jobol/t.git"),
        ("v", "ssh://git@codeberg.org:22/uzu/v.git"),
        ("z", "https://github.com/bob/z"),
    ]

    @pytest.mark.parametrize("flags", [[], ["-g"]])
    def test_export_import_export_roundtrip(self, db_path, tmp_path, flags):
        with GitRepoDB(db_path) as db:
            db.add(self.ROUNDTRIP)
        first, second = tmp_path / "1.json", tmp_path / "2.json"
        other = tmp_path / "other.sqlite"
        assert run(db_path, "export", *flags, "-o", first) == 0
        assert run(other, "import", first) == 0
        assert run(other, "export", *flags, "-o", second) == 0
        with GitRepoDB(db_path) as a, GitRepoDB(other) as b:
            assert a.rows() == b.rows()
            assert len(b.rows()) == len(self.ROUNDTRIP)
        assert second.read_bytes() == first.read_bytes()

    @pytest.mark.parametrize("data", [
        {"a": "https://github.com/alice/a", "t": "https://gitlab.com/jobol/t.git"},
        {"alice": {"a": "https://github.com/alice/a", "r": "https://github.com/alice/r"},
         "bob": {"r": "git@github.com:bob/r.git"}},
    ])
    def test_import_export_reproduces_canonical_json(self, db_path, tmp_path, data):
        # Canonical: sorted keys, group keys equal to the URL owner.
        grouped = isinstance(next(iter(data.values())), dict)
        src, out = tmp_path / "in.json", tmp_path / "out.json"
        src.write_text(json.dumps(data, indent=2) + "\n")
        assert run(db_path, "import", src) == 0
        assert run(db_path, "export", *(["-g"] if grouped else []), "-o", out) == 0
        assert out.read_text() == src.read_text()

    def test_import_ownerless_prints_nothing(self, db_path, tmp_path, capsys):
        f = write_json(tmp_path / "p.json", {"ok": "https://github.com/a/ok", "bad": "/x/bad"})
        with pytest.raises(SystemExit):
            run(db_path, "import", f)
        out = capsys.readouterr()
        assert out.out == ""
        assert "'bad': no owner" in out.err

    def test_clone_flat_rejects_names_differing_in_case(self, db_path, tmp_path, fake_git):
        with GitRepoDB(db_path) as db:
            db.add([("Foo", "https://github.com/alice/Foo"), ("foo", "https://github.com/bob/foo")])
        with pytest.raises(SystemExit):
            run(db_path, "clone", tmp_path / "d")
        fake_git.assert_not_called()

    def test_import_then_list(self, db_path, tmp_path, capsys):
        f = write_json(tmp_path / "p.json", {"r": "https://github.com/a/r",
                                             "s": "https://gitlab.com/b/s"})
        assert run(db_path, "import", f) == 0
        capsys.readouterr()
        assert run(db_path, "list", "--urls", "--owner", "a") == 0
        assert capsys.readouterr().out == "https://github.com/a/r\n"

    @pytest.mark.parametrize("content", ["{not json", '{"r": "/x/local"}'])
    def test_import_rejects_malformed_or_ownerless(self, db_path, tmp_path, content):
        f = tmp_path / "p.json"
        f.write_text(content)
        with pytest.raises(SystemExit):
            run(db_path, "import", f)
        with GitRepoDB(db_path) as db:
            assert db.rows() == []

    def test_list_flat_and_grouped(self, remotes, db_path, capsys):
        with GitRepoDB(db_path) as db:
            db.add([(n, u) for (_, n), u in remotes.items()])
        capsys.readouterr()
        assert run(db_path, "list") == 0
        assert capsys.readouterr().out == "alpha\nbeta\nalpha\n"
        assert run(db_path, "list", "-g") == 0
        assert capsys.readouterr().out == "alice\n  alpha\n  beta\nbob\n  alpha\n"
        assert run(db_path, "list", "-g", "-u", "--owner", "BOB") == 0
        assert capsys.readouterr().out == f"bob\n  {remotes['bob', 'alpha']}\n"

    @pytest.mark.parametrize("flags", [[], ["-g"]])
    def test_list_empty(self, db_path, capsys, flags):
        assert run(db_path, "list", *flags) == 1
        assert "no projects" in capsys.readouterr().err

    def test_remove(self, db_path, capsys):
        with GitRepoDB(db_path) as db:
            db.add([("r", "https://github.com/a/r"), ("s", "https://github.com/a/s")])
        capsys.readouterr()
        assert run(db_path, "remove", "a/r") == 0
        assert capsys.readouterr().out == "removed: a/r <- https://github.com/a/r\n"
        assert run(db_path, "remove", "s", "nope") == 1
        assert "'nope': no such project; nothing removed" in capsys.readouterr().err
        with GitRepoDB(db_path) as db:
            assert [n for _, n, _ in db.rows()] == ["s"]

    @pytest.mark.parametrize("args", [
        [], ["--all"], ["--owner", "a"], ["a/r", "--owner", "a", "--all"], ["a/r", "--all"],
    ])
    def test_remove_rejects_bad_arguments(self, db_path, args):
        with GitRepoDB(db_path) as db:
            db.add([("r", "https://github.com/a/r")])
        with pytest.raises(SystemExit):
            run(db_path, "remove", *args)
        with GitRepoDB(db_path) as db:
            assert len(db.rows()) == 1

    def test_remove_owner_all(self, db_path, capsys):
        with GitRepoDB(db_path) as db:
            db.add([("r", "https://github.com/a/r"), ("s", "https://github.com/A/s"),
                    ("r", "https://github.com/b/r")])
        capsys.readouterr()
        assert run(db_path, "remove", "--owner", "A", "--all") == 0
        assert capsys.readouterr().out == (
            "removed: a/r <- https://github.com/a/r\n"
            "removed: A/s <- https://github.com/A/s\n")
        with GitRepoDB(db_path) as db:
            assert db.rows() == [("b", "r", "https://github.com/b/r")]
        assert run(db_path, "remove", "--owner", "a", "--all") == 1
        assert "'a': no projects for this owner" in capsys.readouterr().err

    def test_listrepos_alias(self, db_path, capsys):
        with GitRepoDB(db_path) as db:
            db.add([("r", "https://github.com/a/r")])
        with patch("sys.argv", ["/bin/listrepos.py"]), patch("repodb.DB_PATH", db_path):
            assert main() == 0
        assert capsys.readouterr().out.splitlines()[-1] == "r"

    def test_clone_from_db_grouped(self, remotes, db_path, tmp_path):
        with GitRepoDB(db_path) as db:
            db.add([(n, u) for (_, n), u in remotes.items()])
        assert run(db_path, "clone", tmp_path / "d", "-g") == 0
        assert (tmp_path / "d" / "bob" / "alpha" / "README").read_text() == "bob/alpha"
        assert (tmp_path / "d" / "alice" / "alpha" / "README").read_text() == "alice/alpha"

    def test_clone_from_db_flat_rejects_repeated_name(self, remotes, db_path, tmp_path,
                                                      fake_git):
        with GitRepoDB(db_path) as db:
            db.add([(n, u) for (_, n), u in remotes.items()])
        with pytest.raises(SystemExit):
            run(db_path, "clone", tmp_path / "d")
        fake_git.assert_not_called()

    def test_clone_from_db_flat_with_owner(self, remotes, db_path, tmp_path):
        with GitRepoDB(db_path) as db:
            db.add([(n, u) for (_, n), u in remotes.items()])
        assert run(db_path, "clone", tmp_path / "d", "--owner", "bob") == 0
        assert (tmp_path / "d" / "alpha" / "README").read_text() == "bob/alpha"

    def test_clone_from_db_reports_failures(self, remotes, db_path, tmp_path):
        with GitRepoDB(db_path) as db:
            db.add([("alpha", remotes["alice", "alpha"]), ("gone", f"{HOST}x/gone.git")])
        assert run(db_path, "clone", tmp_path / "d") == 1
        assert (tmp_path / "d" / "alpha" / "README").exists()

    def test_clone_from_flat_json_allows_local_urls(self, tmp_path, db_path, fake_git):
        f = write_json(tmp_path / "p.json", {"l": "/x/l.git"})
        assert run(db_path, "clone", tmp_path / "d", "--json", f) == 0
        assert cloned_targets(fake_git) == [str(tmp_path / "d" / "l")]
        assert not db_path.exists()

    def test_clone_from_grouped_json(self, remotes, db_path, tmp_path):
        data = {"ignored": {"alpha": remotes["alice", "alpha"]},
                "keys": {"alpha": remotes["bob", "alpha"]}}
        f = write_json(tmp_path / "p.json", data)
        with pytest.raises(SystemExit):  # flat: both would clone to DEST/alpha
            run(db_path, "clone", tmp_path / "d", "--json", f)
        assert run(db_path, "clone", tmp_path / "d", "--json", f, "-g") == 0
        assert (tmp_path / "d" / "alice" / "alpha" / "README").read_text() == "alice/alpha"
        assert (tmp_path / "d" / "bob" / "alpha" / "README").read_text() == "bob/alpha"

    def test_clone_json_with_owner_is_error(self, db_path, tmp_path):
        f = write_json(tmp_path / "p.json", {})
        with pytest.raises(SystemExit):
            run(db_path, "clone", tmp_path / "d", "--json", f, "--owner", "u")


GH_OUT = json.dumps([
    {"name": "zed", "url": "https://github.com/u/zed", "sshUrl": "git@github.com:u/zed.git"},
    {"name": "abc", "url": "https://github.com/u/abc", "sshUrl": "git@github.com:u/abc.git"},
])


def fake_run(stdout):
    def run(cmd, **kw):
        run.cmd = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
    return run


class TestGithub:
    def test_https_sorted(self):
        fr = fake_run(GH_OUT)
        with patch("repodb.subprocess.run", fr):
            result = github("u", 50, ssh=False, source=True, no_archived=False)
        assert result == [("abc", "https://github.com/u/abc"), ("zed", "https://github.com/u/zed")]
        assert fr.cmd[:4] == ["gh", "repo", "list", "u"]
        assert "--source" in fr.cmd and "--no-archived" not in fr.cmd
        assert fr.cmd[fr.cmd.index("--json") + 1] == "name,url"

    def test_ssh(self):
        with patch("repodb.subprocess.run", fake_run(GH_OUT)):
            result = github("u", 50, ssh=True, source=False, no_archived=True)
        assert ("zed", "git@github.com:u/zed.git") in result

    def test_main_requires_gh(self, db_path):
        with patch("repodb.shutil.which", return_value=None), pytest.raises(SystemExit):
            run(db_path, "github", "u")

    def test_main_reports_gh_failure(self, db_path, capsys):
        err = subprocess.CalledProcessError(1, ["gh"], stderr="Could not resolve to a User\n")
        with patch("repodb.shutil.which", return_value="/bin/gh"), \
             patch("repodb.subprocess.run", side_effect=err):
            assert run(db_path, "github", "u") == 1
        assert "Could not resolve" in capsys.readouterr().err

    def test_main_stores_with_owner(self, db_path):
        with patch("repodb.shutil.which", return_value="/bin/gh"), \
             patch("repodb.subprocess.run", fake_run(GH_OUT)):
            assert run(db_path, "github", "u") == 0
        with GitRepoDB(db_path) as db:
            assert db.by_owner("u") == {
                "u": {"abc": "https://github.com/u/abc", "zed": "https://github.com/u/zed"}}
