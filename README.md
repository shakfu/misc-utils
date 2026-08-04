# misc-utils

Useful utilities and scripts

## Repository Management
- `repodb.py` - Git repository database management for tracking remote URLs
- `listrepos.py` - List git repositories from database
- `git_status_checker.py` - Check git status across repositories

## Package Management
- `pip_tools.py` - Python package management utilities (list, update packages)
- `brew_tools.py` - Homebrew package listing and export (CSV/JSON/YAML)
- `dump_brew_pkgs.py` - Export Homebrew packages to YAML/JSON
- `brew_to_csv.py` - Export Homebrew packages to CSV
- `rpkg.py` - R package install/update/remove helper

## File and System Utilities
- `clean.py` - Recursively clean files and detritus by extension or glob pattern
- `clean_file.py` - Remove trailing whitespace and emojis from files
- `rm_deadlinks.py` - Delete broken symbolic links
- `case_converter.py` - Rename identifiers between case styles
- `treesed.py` - Recursive find-and-replace across a directory tree
- `wav_renamer.py` - Batch-rename WAV files
- `webloc_to_md.py` - Convert macOS `.webloc` files to markdown links
- `dump-links.py` - Extract `.webloc` links to an HTML page
- `store_links.py` - Recursively scan `.webloc` files into SQLite
- `webloc2md` - C++ converter for `.webloc` files to markdown

## Text and Diff Tools
- `md_format.py` - Reflow and space markdown (stdin/files/recursive)
- `diff2html.py` - Render git or file diffs as colored HTML

## Build and Development Tools
- `cmake_utils.py` - CMake dependency builder utilities
- `shrink.py` - Thin universal binaries / reduce app sizes (macOS)
- `version.py` - Semver consistency check/bump/tag helper
- `update.sh` - System update script with colorized output
- `renderMd` - R markdown document renderer with multiple output formats
- `appify.sh` - Convert shell scripts to macOS `.app` bundles

## Testing

Python tests use [pytest](https://pytest.org/) via [uv](https://docs.astral.sh/uv/):

```bash
make test
```

Equivalent: `uv run pytest`. The C++ `webloc2md` tool has its own suite under `src/cpp/webloc2md` (`make test` there).
