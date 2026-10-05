#!/usr/bin/env python3
"""Run the smoke-test runners of cyllama, inferna and chimera one after another.

Each project has its own runner -- ``scripts/rwt.py`` in cyllama and inferna,
``scripts/rat.py`` in chimera -- and this script only sequences them. With no
options it runs ``test-all`` on cuda, then on vulkan, for each project in turn,
each through the runner's ``run`` step (install, test, clean): ``test`` alone
needs a venv per backend to exist already, which an unattended run cannot
assume. Each runner records its results in the shared run history
(``~/config/runs/db.sqlite``), so ``--report`` ends with the cross-project HTML
report rather than this script keeping results of its own.

A failing project does not stop the sequence unless ``--fail-fast`` is given:
the projects are independent, and one bad wheel says nothing about the others.
The exit code is the worst of the runners' exit codes.

Examples:
    ./runtests.py                             # cuda then vulkan, test-all, every project
    ./runtests.py --report                    # the same, then open the report
    ./runtests.py --vulkan                    # one backend only
    ./runtests.py --fast                      # the short cycle in place of test-all
    ./runtests.py cyllama chimera             # a subset, in the order given
    ./runtests.py --cpu --step test           # test what is already installed
    ./runtests.py --args chimera="--bin build/chimera"
    ./runtests.py --version cyllama=0.5.1 --version inferna=0.5.1 --version chimera=0.4.1
    ./runtests.py --dry-run                   # print the commands only
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time
from pathlib import Path

# Project -> its runner, relative to the project's checkout.
RUNNERS: dict[str, str] = {
    "cyllama": "scripts/rwt.py",
    "inferna": "scripts/rwt.py",
    "chimera": "scripts/rat.py",
}
BACKENDS: tuple[str, ...] = ("cpu", "metal", "cuda", "vulkan", "rocm", "sycl")
DEFAULT_BACKENDS: tuple[str, ...] = ("cuda", "vulkan")
DEFAULT_TARGET = "test-all"
STEPS: tuple[str, ...] = ("run", "test")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run cyllama's, inferna's and chimera's test runners in sequence.",
        epilog="example: runtests.py --report   (cuda then vulkan, test-all, every project)",
    )
    p.add_argument(
        "projects",
        nargs="*",
        choices=[*RUNNERS, []],  # [] lets an empty list pass the choices check
        metavar="PROJECT",
        help=f"projects to run, in order (default: {' '.join(RUNNERS)})",
    )
    for b in BACKENDS:
        p.add_argument(
            f"--{b}",
            dest="backends",
            action="append_const",
            const=b,
            help=f"test the {b} backend (repeatable flags run in the order given; default: "
            f"{', then '.join(DEFAULT_BACKENDS)})",
        )
    p.add_argument(
        "--step",
        choices=STEPS,
        default="run",
        help="`run` installs, tests and cleans; `test` tests what is installed (default: run)",
    )
    p.add_argument(
        "--target",
        default=DEFAULT_TARGET,
        metavar="TARGET",
        help=f"test target for every run (default: {DEFAULT_TARGET})",
    )
    p.add_argument("--fast", action="store_true", help="pass --fast to `run` (the short cycle)")
    p.add_argument("--timeout", type=float, metavar="SECS", help="per-test timeout passed to every runner")
    p.add_argument(
        "--args",
        action="append",
        default=[],
        metavar="PROJECT=ARGS",
        help='extra arguments for one project\'s runner, e.g. chimera="--bin build/chimera" (repeatable)',
    )
    p.add_argument(
        "--version",
        dest="versions",
        action="append",
        default=[],
        metavar="PROJECT=X",
        help="install release X of one project instead of the latest, e.g. to record a baseline "
        "for the report's version comparison (repeatable; --step run only)",
    )
    p.add_argument(
        "--root",
        type=Path,
        default=Path("~/projects"),
        help="directory holding the checkouts (default: ~/projects)",
    )
    p.add_argument("--fail-fast", action="store_true", help="stop at the first project that fails")
    p.add_argument("--report", action="store_true", help="open the all-projects HTML report at the end")
    p.add_argument("--dry-run", action="store_true", help="print the commands without running them")
    return p


def split_project(flag: str, value: str) -> tuple[str, str]:
    """``PROJECT=REST`` -> (project, rest), for --args and --version."""
    name, sep, rest = value.partition("=")
    if not sep or name not in RUNNERS:
        raise ValueError(f"{flag} expects PROJECT=... with PROJECT one of {', '.join(RUNNERS)}: {value!r}")
    return name, rest


def parse_extra(args_values: list[str], version_values: list[str]) -> dict[str, list[str]]:
    """``--args`` and ``--version`` values -> {project: extra argv}. Both runners
    spell the version pin ``--version``; repeats for one project accumulate."""
    extra: dict[str, list[str]] = {}
    for value in args_values:
        name, rest = split_project("--args", value)
        extra.setdefault(name, []).extend(shlex.split(rest))
    for value in version_values:
        name, version = split_project("--version", value)
        if not version:
            raise ValueError(f"--version {value!r} names no version")
        extra.setdefault(name, []).extend(["--version", version])
    return extra


def command(args: argparse.Namespace, project: str, backend: str, extra: list[str]) -> list[str]:
    """The runner invocation for `project` on `backend`."""
    script = args.root.expanduser() / project / RUNNERS[project]
    cmd = [sys.executable, str(script), args.step, f"--{backend}"]
    if args.timeout is not None:
        cmd += ["--timeout", f"{args.timeout:g}"]
    cmd += extra
    # --fast names its own targets, so it replaces the target rather than joining it.
    cmd += ["--fast"] if args.fast else [args.target]
    return cmd


def run(cmd: list[str], cwd: Path) -> int:
    print(f"$ {shlex.join(cmd)}", flush=True)
    try:
        return subprocess.run(cmd, cwd=cwd).returncode
    except KeyboardInterrupt:
        return 130


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    projects = args.projects or list(RUNNERS)
    backends = args.backends or list(DEFAULT_BACKENDS)
    if args.fast and args.step != "run":
        parser.error("--fast only applies to --step run")
    if args.fast and args.target != DEFAULT_TARGET:
        parser.error("--fast names its own targets; drop --target")
    if args.versions and args.step != "run":
        parser.error("--version installs a release, so it needs --step run")
    try:
        extra = parse_extra(args.args, args.versions)
    except ValueError as e:
        parser.error(str(e))

    root = args.root.expanduser()
    missing = [p for p in projects if not (root / p / RUNNERS[p]).is_file()]
    if missing and not args.dry_run:
        for p in missing:
            print(f"error: no runner at {root / p / RUNNERS[p]}", file=sys.stderr)
        return 2

    plan = [(project, backend) for project in projects for backend in backends]
    results: list[tuple[str, str, int, float]] = []
    for project, backend in plan:
        cmd = command(args, project, backend, extra.get(project, []))
        if args.dry_run:
            print(f"would run (in {root / project}): {shlex.join(cmd)}")
            continue
        print(f"\n######## {project} {backend} ########", flush=True)
        started = time.monotonic()
        rc = run(cmd, root / project)
        results.append((project, backend, rc, time.monotonic() - started))
        if rc == 130 or (rc != 0 and args.fail_fast):
            break

    if args.dry_run:
        return 0

    print("\n######## summary ########")
    for project, backend, rc, secs in results:
        status = "PASS" if rc == 0 else f"FAIL (rc={rc})"
        print(f"  {project:<8} {backend:<7} {status:<14} {secs / 60:6.1f} min")
    not_run = plan[len(results) :]
    if not_run:
        print(f"  not run: {', '.join(f'{p} {b}' for p, b in not_run)}")
    worst = max((rc for *_, rc, _ in results), default=0)

    if args.report and results:
        # Any runner writes the same cross-project report; use the last one that ran.
        last = results[-1][0]
        run([sys.executable, str(root / last / RUNNERS[last]), "report", "--all-projects"], root / last)
    return worst


if __name__ == "__main__":
    sys.exit(main())
