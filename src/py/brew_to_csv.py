#!/usr/bin/env python3
"""Export brew packages to CSV - wrapper around brew_tools.py

This is a convenience script. For full functionality, use brew_tools.py directly.
"""

from brew_tools import dump_to_csv

if __name__ == '__main__':
    dump_to_csv('names.csv')
