#!/usr/bin/env python3
"""Dump brew packages to YAML/JSON - wrapper around brew_tools.py

This is a convenience script. For full functionality, use brew_tools.py directly.
"""

from brew_tools import dump_to_yaml, dump_to_json

if __name__ == '__main__':
    # Try YAML first, fall back to JSON if PyYAML not available
    try:
        import yaml
        dump_to_yaml('pkgs.yml')
    except ImportError:
        dump_to_json('pkgs.json')
