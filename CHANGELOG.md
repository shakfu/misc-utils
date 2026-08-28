# Changelog

## 2026-08-29

- Fixed `webloc_to_md.py`, which ignored its `root` argument: the `os.walk` loop variable shadowed the parameter, so every scan walked the working directory instead, and `gen_md(".")` ran unconditionally under `__main__` — any invocation, `--help` included, silently wrote `_RESEARCH.md` into wherever it was called from. It now has a real CLI (`root`, `--title`, `--output`), rejects a root that is not a directory, and names each heading relative to the scan root rather than passing an absolute path through `lstrip('./')`, which stripped characters rather than a prefix. The tests mocked `os.walk` and chdir'd into the fixture, which is exactly why they passed over the bug; they now exercise the real walk.

- Type-annotated every script in `src/py` and wired `mypy --strict` into the build: `[tool.mypy]` in `pyproject.toml` checks the whole directory, `make typecheck` runs it, and `types-PyYAML` joins the dev group so the optional YAML paths in `brew_tools.py` check too. Vendored `src/py/thirdparty/` is excluded to keep it re-syncable. Annotating flushed out several latent defects: `webloc_to_md.py` rebound `webloc` from `str` to `Path` and reused `f` for both a filename and a file handle, `git_status_checker.py` declared `-> dict` on a function that returns `None` on every failure path (now a `RepoStatus` TypedDict), and `dedupe.py` could call `min()` on a list holding `None`. `mover.py`'s `_inspect` is now generic in the `ArtifactSet` subclass it builds rather than flattening `Repo` and `Bundle` to the base class, and `dedupe.py`'s macOS-only `os.chflags` call is guarded so the module checks on other platforms.

## 2026-08-28

- Added `mkdesktop.py`: writes a freedesktop `.desktop` launcher for an executable, validating the menu categories against the spec's related-category tables and running `desktop-file-validate` on the result (including under `--dry-run`), whose exit status it now propagates. Literal percent signs are doubled and the file/URL field codes are checked for the spec's one-per-`Exec` limit, since a stray `%` in a path otherwise produces an entry every launcher rejects. `--action` emits `[Desktop Action]` groups for the right-click menu, `--install-icon` copies an icon into the hicolor theme and references it by name so the entry survives the source moving, and `--list`/`--remove` manage what has been installed, `--remove` taking a themed icon with the entry it belongs to.

- Added `wordsub.py`: scans a file tree for a term dictionary, built in or given with `--dict`, and optionally substitutes in place. Matching is whole-word and case-insensitive with the substitute recased to the spelling it replaced, since a prose vocabulary has to be found in every casing it is written in; `--case-sensitive` narrows both to the exact dictionary spelling and `--exact-fix` decouples them, reporting every casing but rewriting only the exact one and marking the rest `[manual]`. Only `.md` files are scanned, the dictionary being prose: widening the walk to source trees flags identifiers and URLs. Scan mode exits 1 when matches remain, so it is usable as a CI check. `treesed.py` remains the tool for one-off arbitrary patterns.

## 2026-02-07

- Removed `webloc` external dependency; replaced with stdlib `plistlib` in `store_links.py` and `dump-links.py`
- Project now has zero external runtime dependencies
