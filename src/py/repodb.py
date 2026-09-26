#!/usr/bin/env python3
"""Keep a SQLite database of git project clone URLs, and clone from it.

    repodb.py scan ~/src                        # add local projects' origin URLs
    repodb.py github USER                       # add USER's GitHub repos (needs gh)
    repodb.py export --owner USER -o projects.json
    repodb.py import projects.json
    repodb.py clone ~/src [--owner USER | --json projects.json] [--group]
    repodb.py list [--urls] [--owner USER] [--group]
    repodb.py remove OWNER/NAME [NAME ...] | --owner USER --all
    repodb.py info                              # schema, counts, hosts; read-only

Each row is ``(owner, name, url)``, keyed by ``(owner, name)``. The owner is
the first path component after the host in the URL (``alice`` in
``github.com/alice/r`` or ``git@gitlab.com:alice/r``), and every row must have
one, so local-path and ``file://`` remotes are not stored. Owner and name
compare case-insensitively.

The JSON form is ``{name: url}``, or with ``--group`` ``{owner: {name: url}}``.
Both forms are read back; group keys are ignored on read, since owner is
derived from the URL. ``clone`` recreates each project as ``DEST/<name>``, or
with ``--group`` ``DEST/<owner>/<name>``, and skips targets that already
exist. The flat forms reject a name held by two owners.

Invoked as ``listrepos`` it runs ``list``.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable, Sequence

DB_PATH = Path("~/.local/share/repodb/repos.sqlite").expanduser()
SRC_DIR = Path("~/src").expanduser()

# https://host/O/R, ssh://git@host:22/O/R, git@host:O/R.git; host needs a dot.
OWNER = re.compile(
    r"^(?:[a-z][a-z0-9+.-]*://)?(?:[^@/]+@)?([\w-]+(?:\.[\w-]+)+)(?::\d+)?[:/]([^/]+)/[^/]",
    re.I)

Row = tuple[str, str, str]  # (owner, name, url)


def owner_of(url: str) -> str | None:
    """Return the owner in a ``host/owner/repo`` *url*, or None if it has none."""
    m = OWNER.match(url)
    return m.group(2) if m else None


def host_of(url: str) -> str | None:
    """Return the lower-cased host in a ``host/owner/repo`` *url*, or None."""
    m = OWNER.match(url)
    return m.group(1).lower() if m else None


def primary_key(conn: sqlite3.Connection) -> list[str]:
    """Return the primary-key columns of ``repos``, or [] if there is no such table."""
    return [r[1] for r in conn.execute("PRAGMA table_info(repos)") if r[5]]


def info(db_path: Path, top: int = 5) -> list[str]:
    """Describe the database at *db_path* without writing to it.

    Raises:
        sqlite3.Error: if the file cannot be opened as a database.
    """
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        pk = primary_key(conn)
        current = pk == GitRepoDB.KEY
        rows = conn.execute("SELECT owner, name, url FROM repos").fetchall() if current else []
    finally:
        conn.close()
    fields = [("database", f"{db_path} ({db_path.stat().st_size / 1024:.1f}KB)"),
              ("format", "current, keyed by (owner, name)" if current else
               f"unsupported (primary key {pk})" if pk else "no repos table")]
    if current:
        owners: dict[str, list[str]] = {}  # lower-cased owner -> [spelling, names...]
        hosts: dict[str, int] = {}
        names: dict[str, list[str]] = {}  # lower-cased name -> owners
        for owner, name, url in rows:
            owners.setdefault(owner.lower(), [owner]).append(name)
            host = host_of(url) or "?"
            hosts[host] = hosts.get(host, 0) + 1
            names.setdefault(name.lower(), []).append(owner)

        def counts(items: Iterable[tuple[str, int]]) -> str:
            return ", ".join(f"{k} {n}" for k, n in items) or "-"

        by_size = sorted(owners.values(), key=lambda o: (-(len(o) - 1), o[0].lower()))
        shared = sorted((n, o) for n, o in names.items() if len(o) > 1)
        fields += [
            ("projects", str(len(rows))),
            ("owners", str(len(owners))),
            ("hosts", counts(sorted(hosts.items(), key=lambda h: (-h[1], h[0])))),
            ("top owners", counts((o[0], len(o) - 1) for o in by_size[:top])),
            ("shared names", ", ".join(f"{n} ({', '.join(o)})" for n, o in shared) or "-"),
        ]
    return [f"{k + ':':<14}{v}" for k, v in fields]


class GitRepoDB:
    """SQLite table of ``(owner, name, url)``, keyed by ``(owner, name)``."""

    KEY = ["owner", "name"]
    SCHEMA = (
        "CREATE TABLE IF NOT EXISTS repos ("
        " owner TEXT NOT NULL COLLATE NOCASE CHECK (owner <> ''),"
        " name TEXT NOT NULL COLLATE NOCASE CHECK (name <> ''),"
        " url TEXT NOT NULL CHECK (url <> ''),"
        " PRIMARY KEY (owner, name))"
    )

    def __init__(self, db_path: str | Path = DB_PATH):
        """Open or create the database.

        Raises:
            ValueError: if an existing ``repos`` table has another primary key.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute(self.SCHEMA)
        if (pk := primary_key(self.conn)) != self.KEY:
            self.conn.close()
            raise ValueError(f"{self.db_path}: unsupported schema, primary key {pk}")

    def __enter__(self) -> GitRepoDB:
        return self

    def __exit__(self, *exc: object) -> None:
        self.conn.close()

    def add(self, projects: Iterable[tuple[str, str]]) -> None:
        """Insert or update ``(name, url)`` pairs, printing each one added or changed.

        Raises:
            ValueError: if a url has no owner; nothing is written.
        """
        rows = []
        for name, url in projects:
            owner = owner_of(url)
            if owner is None:
                raise ValueError(f"{name!r}: no owner in url {url!r}")
            rows.append((owner, name, url))
        changes = []
        with self.conn:
            for owner, name, url in rows:
                row = self.conn.execute(
                    "SELECT url FROM repos WHERE owner = ? AND name = ?",
                    (owner, name)).fetchone()
                if row and row[0] == url:
                    continue
                changes.append(f"{'updated' if row else 'added'}: {owner}/{name} <- {url}")
                self.conn.execute(
                    "INSERT INTO repos (owner, name, url) VALUES (?, ?, ?)"
                    " ON CONFLICT (owner, name) DO UPDATE SET url = excluded.url",
                    (owner, name, url),
                )
        for line in changes:  # after the commit, so a rollback prints nothing
            print(line)

    def remove(self, specs: Iterable[str]) -> list[Row]:
        """Delete projects given as ``owner/name`` or a bare ``name``; return the rows.

        Raises:
            ValueError: if a spec matches no row, or a bare name matches several;
                nothing is deleted.
        """
        removed: list[Row] = []
        with self.conn:
            for spec in specs:
                owner, _, name = spec.rpartition("/")
                sql = "SELECT owner, name, url FROM repos WHERE name = ?"
                if owner:
                    matches = self.conn.execute(sql + " AND owner = ?", (name, owner)).fetchall()
                else:
                    matches = self.conn.execute(sql, (name,)).fetchall()
                if not matches:
                    raise ValueError(f"{spec!r}: no such project")
                if len(matches) > 1:
                    raise ValueError(f"{spec!r}: ambiguous, use one of "
                                     + ", ".join(f"{o}/{n}" for o, n, _ in matches))
                self.conn.execute("DELETE FROM repos WHERE owner = ? AND name = ?",
                                  matches[0][:2])
                removed.append(matches[0])
        return removed

    def remove_owner(self, owner: str) -> list[Row]:
        """Delete every project of *owner*; return the rows.

        Raises:
            ValueError: if *owner* has no projects.
        """
        removed = self.rows(owner)
        if not removed:
            raise ValueError(f"{owner!r}: no projects for this owner")
        with self.conn:
            self.conn.execute("DELETE FROM repos WHERE owner = ?", (owner,))
        return removed

    def rows(self, owner: str | None = None) -> list[Row]:
        """Return rows sorted by owner then name, optionally only *owner*'s."""
        sql = "SELECT owner, name, url FROM repos"
        order = " ORDER BY owner, name"
        if owner is None:
            return self.conn.execute(sql + order).fetchall()
        return self.conn.execute(sql + " WHERE owner = ?" + order, (owner,)).fetchall()

    def by_owner(self, owner: str | None = None) -> dict[str, dict[str, str]]:
        """Return ``{owner: {name: url}}``, owners sorted."""
        groups: dict[str, dict[str, str]] = {}
        spelling: dict[str, str] = {}  # one group per owner regardless of case; first spelling wins
        for o, name, url in self.rows(owner):
            groups.setdefault(spelling.setdefault(o.lower(), o), {})[name] = url
        return groups


def flatten(pairs: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Return ``{name: url}``.

    Raises:
        ValueError: if a name appears twice, ignoring case, since both would
            map to ``DEST/<name>`` on a case-insensitive filesystem.
    """
    projects: dict[str, str] = {}
    seen: dict[str, str] = {}  # lower-cased name -> first spelling
    for name, url in pairs:
        if (first := seen.get(name.lower())) is not None:
            raise ValueError(f"{name!r}: held by more than one owner"
                             f"{'' if first == name else f' (as {first!r})'}; use --group")
        seen[name.lower()] = name
        projects[name] = url
    return projects


def scan(directory: Path) -> list[tuple[str, str]]:
    """Return ``(name, origin_url)`` for each git project directly under *directory*.

    Projects without an ``origin`` remote, or whose url has no owner, are
    reported on stderr and omitted.
    """
    projects = []
    for p in sorted(directory.iterdir()):
        if not (p.is_dir() and (p / ".git").exists()):
            continue
        result = subprocess.run(
            ["git", "-C", str(p), "remote", "get-url", "origin"],
            capture_output=True, text=True,
        )
        url = result.stdout.strip()
        if result.returncode or not url:
            print(f"no origin, skipping: {p.name}", file=sys.stderr)
        elif owner_of(url) is None:
            print(f"no owner in origin url, skipping: {p.name} ({url})", file=sys.stderr)
        else:
            projects.append((p.name, url))
    return projects


def github(user: str, limit: int, ssh: bool, source: bool,
           no_archived: bool) -> list[tuple[str, str]]:
    """Return ``(name, clone_url)`` for *user*'s GitHub repos via ``gh repo list``.

    Raises:
        subprocess.CalledProcessError: if ``gh`` fails, e.g. unknown user or no auth.
    """
    field = "sshUrl" if ssh else "url"
    cmd = ["gh", "repo", "list", user, "--limit", str(limit), "--json", f"name,{field}"]
    if source:
        cmd.append("--source")
    if no_archived:
        cmd.append("--no-archived")
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return sorted((r["name"], r[field]) for r in json.loads(out))


def write(projects: dict[str, str] | dict[str, dict[str, str]], output: Path) -> None:
    """Write *projects* as JSON to *output*, or stdout if it is ``-``."""
    text = json.dumps(projects, indent=2) + "\n"
    if str(output) == "-":
        sys.stdout.write(text)
    else:
        output.write_text(text)


def valid_name(name: str) -> bool:
    """True if *name* is a single path component, so ``DEST/name`` stays in DEST."""
    return name not in ("", ".", "..") and Path(name).name == name


def read_pairs(path: Path) -> list[tuple[str, str]]:
    """Load and validate a flat or grouped projects file as ``(name, url)`` pairs.

    A name may repeat across groups; `flatten` rejects that.

    Raises:
        ValueError: if the file is neither ``{name: url}`` nor
            ``{owner: {name: url}}``, or a name is not a single path component.
    """
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object of {name: url} or {owner: {name: url}}")
    if data and all(isinstance(v, dict) for v in data.values()):
        items = [item for group in data.values() for item in group.items()]
    else:
        items = list(data.items())
    for name, url in items:
        if not isinstance(url, str) or not url:
            raise ValueError(f"{name!r}: url must be a non-empty string")
        if not valid_name(name):
            raise ValueError(f"{name!r}: not a valid project directory name")
    return items


def clone(rows: Iterable[tuple[str | None, str, str]], dest: Path,
          by_owner: bool = False) -> list[str]:
    """Clone each ``(owner, name, url)`` into ``dest/<name>`` unless it exists.

    With *by_owner*, clone into ``dest/<owner>/<name>``; a row without an
    owner then fails. Return the failed targets.
    """
    dest.mkdir(parents=True, exist_ok=True)
    failed = []
    for owner, name, url in rows:
        if by_owner and owner is None:
            print(f"no owner in url, skipping: {name} ({url})", file=sys.stderr)
            failed.append(name)
            continue
        parts = [owner, name] if by_owner and owner else [name]
        rel = Path(*parts)
        # The database can be edited outside repodb, and an owner parsed from
        # a url can be "..", so check every component stays inside DEST.
        if not all(map(valid_name, parts)):
            print(f"invalid name, skipping: {str(rel)!r}", file=sys.stderr)
            failed.append(str(rel))
            continue
        target = dest / rel
        if target.exists():
            print(f"exists, skipping: {rel}")
            continue
        print(f"cloning: {rel} <- {url}")
        # "--" stops a url beginning with "-" being read as a git option.
        if subprocess.run(["git", "clone", "--", url, str(target)]).returncode:
            failed.append(str(rel))
    return failed


def report(failed: list[str]) -> int:
    """Print failed clone names to stderr; return the exit status."""
    if failed:
        print(f"failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


# Subcommand handlers: each takes the parsed args and the parser (for
# parser.error) and returns the exit status.

Handler = Callable[[argparse.Namespace, argparse.ArgumentParser], int]


def open_db(args: argparse.Namespace) -> GitRepoDB:
    """Open ``args.db``, exiting with status 1 if its schema is unsupported."""
    try:
        return GitRepoDB(args.db)
    except ValueError as e:
        raise SystemExit(str(e))


def cmd_scan(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if not args.directory.is_dir():
        parser.error(f"not a directory: {args.directory}")
    with open_db(args) as db:
        db.add(scan(args.directory))
    return 0


def cmd_github(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if shutil.which("gh") is None:
        parser.error("github requires the gh CLI: https://cli.github.com")
    try:
        projects = github(args.user, args.limit, args.ssh, args.source, args.no_archived)
    except subprocess.CalledProcessError as e:
        print(f"gh failed: {e.stderr.strip()}", file=sys.stderr)
        return 1
    with open_db(args) as db:
        db.add(projects)
    return 0


def cmd_import(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    with open_db(args) as db:
        try:
            db.add(read_pairs(args.json))
        except (OSError, ValueError) as e:  # json.JSONDecodeError is a ValueError
            parser.error(f"{args.json}: {e}")
    return 0


def cmd_export(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    with open_db(args) as db:
        if args.group:
            write(db.by_owner(args.owner), args.output)
            return 0
        try:
            projects = flatten((n, u) for _, n, u in db.rows(args.owner))
        except ValueError as e:
            parser.error(str(e))
    write(projects, args.output)
    return 0


def cmd_list(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    with open_db(args) as db:
        rows = db.rows(args.owner)
        groups = db.by_owner(args.owner) if args.group else {}
    if not rows:
        print("no projects; run 'repodb scan' or 'repodb github USER'", file=sys.stderr)
        return 1
    if args.group:
        for owner, projects in groups.items():
            print(owner)
            for name, url in projects.items():
                print(f"  {url if args.urls else name}")
    else:
        print("\n".join(url if args.urls else name for _, name, url in rows))
    return 0


def cmd_remove(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    # One flag must not delete many rows, so --owner needs --all as well.
    if bool(args.specs) == bool(args.owner):
        parser.error("give SPEC ... or --owner OWNER --all, not both or neither")
    if bool(args.owner) != args.all:
        parser.error("--owner and --all go together")
    with open_db(args) as db:
        try:
            removed = db.remove_owner(args.owner) if args.owner else db.remove(args.specs)
        except ValueError as e:
            print(f"{e}; nothing removed", file=sys.stderr)
            return 1
    for o, n, u in removed:
        print(f"removed: {o}/{n} <- {u}")
    return 0


def cmd_info(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if not args.db.is_file():
        print(f"no database at {args.db}", file=sys.stderr)
        return 1
    try:
        print("\n".join(info(args.db)))
    except sqlite3.Error as e:
        print(f"{args.db}: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_clone(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.json:
        if args.owner:
            parser.error("--owner filters the database; it does not apply with --json")
        try:
            pairs = read_pairs(args.json)
        except (OSError, ValueError) as e:
            parser.error(f"{args.json}: {e}")
        rows: list[tuple[str | None, str, str]] = [(owner_of(u), n, u) for n, u in pairs]
    else:
        with open_db(args) as db:
            rows = list(db.rows(args.owner))
    if not args.group:
        try:
            flatten((n, u) for _, n, u in rows)
        except ValueError as e:
            parser.error(str(e))
    return report(clone(rows, args.dest, args.group))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="repodb", description="Keep a database of git project URLs, and clone from it.")
    parser.add_argument("--db", type=Path, default=DB_PATH,
                        help=f"database file (default: {DB_PATH})")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, handler: Handler, help: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help)
        p.set_defaults(handler=handler)
        return p

    p = add("scan", cmd_scan, "add origin URLs of projects in DIR")
    p.add_argument("directory", type=Path, nargs="?", default=SRC_DIR, metavar="DIR",
                   help=f"default: {SRC_DIR}")

    p = add("github", cmd_github, "add USER's GitHub repos (needs gh)")
    p.add_argument("user", metavar="USER", help="GitHub user or organization")
    p.add_argument("-L", "--limit", type=int, default=10000,
                   help="maximum repos to list (default: 10000)")
    p.add_argument("--ssh", action="store_true", help="use SSH clone URLs, not HTTPS")
    p.add_argument("--source", action="store_true", help="omit forks")
    p.add_argument("--no-archived", action="store_true", help="omit archived repos")

    p = add("import", cmd_import, "add projects from a JSON file, flat or grouped")
    p.add_argument("json", type=Path, metavar="JSON")

    p = add("export", cmd_export, "write projects as {name: url} JSON")
    p.add_argument("-o", "--output", type=Path, default=Path("projects.json"),
                   help="output file, or - for stdout (default: projects.json)")
    p.add_argument("-g", "--group", action="store_true", help="write {owner: {name: url}}")
    p.add_argument("--owner", help="only this owner's projects")

    p = add("list", cmd_list, "print project names")
    p.add_argument("-u", "--urls", action="store_true", help="print URLs instead")
    p.add_argument("-g", "--group", action="store_true", help="group by owner")
    p.add_argument("--owner", help="only this owner's projects")

    p = add("remove", cmd_remove, "delete projects from the database; cloned directories are kept")
    p.add_argument("specs", nargs="*", metavar="SPEC",
                   help="OWNER/NAME, or NAME if only one owner has it")
    p.add_argument("--owner", help="remove every project of this owner; needs --all")
    p.add_argument("--all", action="store_true", help="confirm --owner")

    add("info", cmd_info, "describe the database; read-only")

    p = add("clone", cmd_clone, "clone projects into DEST")
    p.add_argument("dest", type=Path, metavar="DEST")
    p.add_argument("--json", type=Path, metavar="FILE",
                   help="clone from this JSON file instead of the database")
    p.add_argument("-g", "--group", action="store_true", help="clone into DEST/OWNER/NAME")
    p.add_argument("--owner", help="only this owner's projects")

    if Path(sys.argv[0]).stem == "listrepos" and argv is None:
        argv = ["list"]
    args = parser.parse_args(argv)
    handler: Handler = args.handler
    return handler(args, parser)


if __name__ == "__main__":
    sys.exit(main())
