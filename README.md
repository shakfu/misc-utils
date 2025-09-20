# misc-utils

Useful utilities and scripts

## Repository Management
- `repodb.py` - Git repository database management for tracking remote URLs
- `listrepos.py` - List git repositories from database

## Package Management
- `pip_tools.py` - Python package management utilities (list, update packages)
- `pip_reset.py` - Reset Python packages by uninstalling non-core packages
- `dump_brew_pkgs.py` - Export Homebrew package information
- `brew_to_csv.py` - Convert Homebrew package data to CSV format
- `rpkg` - R package management utility

## File and System Utilities
- `clean` - Recursively clean files and detritus by extension or glob pattern
- `clean_file.py` - Remove trailing whitespace and emojis from files
- `rm_deadlinks.py` - Delete broken symbolic links
- `webloc_to_md.py` - Convert macOS .webloc files to markdown links
- `dump-links.py` - Extract and dump links from .webloc files to HTML

## Build and Development Tools
- `cmake_utils.py` - CMake dependency builder utilities
- `update` - System update script with colorized output
- `renderMd` - R markdown document renderer with multiple output formats
- `shrink` - Reduce file sizes of binaries and applications
- `appify.sh` - Convert shell scripts to macOS .app bundles
