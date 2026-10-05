# runtests

`runtests.py` runs the smoke-test runners of three projects in sequence:

| Project | Runner | Tests |
|-|-|-|
| cyllama | `scripts/rwt.py` | the wheel from PyPI |
| inferna | `scripts/rwt.py` | the wheel from PyPI |
| chimera | `scripts/rat.py` | the latest GitHub release binary |

It sequences the runners and adds no test logic of its own. Stdlib only.

## Usage

```sh
./runtests.py              # test-all on cuda, then vulkan, for each project
./runtests.py --report     # the same, then open the HTML report
./runtests.py --dry-run    # print the six commands, run nothing
```

The default runs six commands, one project at a time:

```
cyllama: rwt.py run --cuda test-all, then rwt.py run --vulkan test-all
inferna: rwt.py run --cuda test-all, then rwt.py run --vulkan test-all
chimera: rat.py run --cuda test-all, then rat.py run --vulkan test-all
```

`run` installs, tests, then cleans. `--step test` skips install and clean, but needs a venv per backend to exist already.

A failure does not stop the sequence. The exit code is the worst runner exit code. A summary lists each project and backend with its result and minutes.

## Options

| Flag | Effect |
|-|-|
| `PROJECT ...` | run a subset, in the order given |
| `--cuda`, `--vulkan`, `--cpu`, `--metal`, `--rocm`, `--sycl` | replace the default backends; several run in the order given |
| `--target T` | test target (default: `test-all`) |
| `--fast` | each runner's short cycle in place of the target |
| `--timeout SECS` | per-test timeout for every runner |
| `--step run\|test` | `run` (default) installs, tests, cleans; `test` uses what is installed |
| `--args PROJECT=ARGS` | extra flags for one project's runner; repeatable |
| `--version PROJECT=X` | install release X of one project instead of the latest; repeatable; `--step run` only |
| `--root DIR` | directory holding the checkouts (default: `~/projects`) |
| `--fail-fast` | stop at the first failure and list what did not run |
| `--report` | open the all-projects HTML report at the end |
| `--dry-run` | print the commands only |

Test a local build instead of a release:

```sh
./runtests.py --args chimera="--bin build/chimera"
./runtests.py --vulkan --step test inferna    # the wheel already in inferna/.venv-vulkan
```

## Comparing versions

The report compares versions of the same project, backend and target. It needs runs of two versions. To record a baseline from the previous releases:

```sh
./runtests.py --version cyllama=0.5.1 --version inferna=0.5.1 --version chimera=0.4.1
./runtests.py --report     # the latest releases, then the report
```

Versions are ordered by number, so the baseline can be recorded before or after the newer release. A case an old release cannot run shows as "now passing" in the comparison rather than as a regression.

## Results

Each runner records every run in `~/config/runs/db.sqlite` (`$RUNS_DB` overrides it). A run stores:

- version, artifact hash, git commit, host;

- each case's status and seconds;

- tokens/s for the gen cases (chimera: only binaries with `gen --stats`, i.e. after 0.5.0);

- size and sha256 of each image the sd cases write.

Read the history with any of the three runners, from that project's checkout:

| Command | Output |
|-|-|
| `scripts/rwt.py runs` | text table of recent runs (`--all-projects` for every project) |
| `scripts/rwt.py runs diff [A] [B]` | text, case by case; no ids compares the latest run with the previous one |
| `scripts/rwt.py report` | HTML report, opened in the browser |

In chimera the runner is `scripts/rat.py`; the commands are the same.

The HTML report shows, in order:

1. version over version: per project, backend and target, the newest version against the next one below it, with a verdict per case and measure;

2. recent runs;

3. backends side by side: the latest run of each backend, per project;

4. per project, backend and target: the latest-vs-previous run diff and a trend chart per case. A dashed line on a chart marks a version change.

Sections 1 and 4 need two versions or two runs of the same project, backend and target. `report` takes `--all-projects`, `-o FILE`, `-n N` and `--no-open`.

The report is written beside the database. The database is not under `~/.config` because snap browsers cannot read hidden directories.

## Tests

```sh
uv run --no-project --with pytest pytest test_runtests.py
```

The tests use fake runners in a temporary `--root`; nothing is installed.
