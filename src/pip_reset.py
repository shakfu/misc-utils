#!/usr/bin/env python3

import subprocess
import sys

SKIP = [
    # '------------------',
    'black',
    'build',
    'cffi',
    'Cython',
    'dawdreamer',
    'ipython',
    'isort',
    'Jinja2',
    'memray',
    'msgspec',
    'mypy',
    'nanobind',
    'numpy',
    'pedalboard',
    'pip',
    'pybind11',
    'pydantic',
    'pylint',
    'pytest',
    'pytube',
    'PyYAML',
    'radian',
    'rpl',
    'ruff',
    'scipy',
    'setuptools',
    'signalflow',
    'virtualenv',
    'wheel',
]


def print_dot():
    sys.stdout.write(".")
    sys.stdout.flush()


def get_output(cmds) -> str:
    return subprocess.check_output(
        cmds.split(), encoding="utf8", stderr=subprocess.DEVNULL
    )


def get_names() -> list[str]:
    pkgs = get_output("pip list")
    lines = pkgs.splitlines()
    names = [line.split()[0].strip() for line in lines]
    _names = []
    for name in names:
        if name in SKIP or name.startswith("-----"):
            continue
        _names.append(name)
    return _names


def main():
    names = get_names()
    # print("can by uninstalled by: 'pip uninstall -y {}'".format(" ".join(names)))
    print("'pip3 install -y {}'".format(" ".join(SKIP)))


if __name__ == "__main__":
    main()
