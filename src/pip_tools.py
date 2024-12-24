#!/usr/bin/env python3
import os
import argparse
import subprocess
import sys

SKIP = [
    "Cython",
    "packaging",
    "pip",
    "setuptools",
    "virtualenv",
    "wheel",
]


def print_dot():
    sys.stdout.write(".")
    sys.stdout.flush()


def get_output(cmd: str) -> str:
    return subprocess.check_output(
        cmd.split(), encoding="utf8", stderr=subprocess.DEVNULL
    )


def get_names(cmd: str) -> list[str]:
    pkgs = get_output(cmd)
    lines = pkgs.splitlines()
    shortname = ""
    names = [line.split()[0].strip() for line in lines]
    _names = []
    for name in names:
        if "==" in name:
            shortname = name.split("==")[0]
        if name in SKIP or shortname in SKIP or name.startswith("-----"):
            continue
        _names.append(name)
    return _names


def get_required_by(name: str) -> list[str] | None:
    deps = None
    try:
        info = get_output(f"pip show {name}")
        lines = info.splitlines()
        for line in lines:
            if line.startswith("Required-by: "):
                _line = line.replace("Required-by: ", "")
                deps = _line.split()
    except subprocess.CalledProcessError:
        pass
    return deps


def clean_deps():
    """Clean up unused dependencies"""
    required_by = set()
    not_required_by = set()
    singles = set()

    names = get_names("pip list")

    for name in names:
        # print(name)
        req_by_list = get_required_by(name)
        if not req_by_list:
            not_required_by.add(name)
        else:
            required_by.update(set(req_by_list))
            # print(name, get_required_by(name))
        print_dot()

    print()
    for pkg in not_required_by:
        if pkg in required_by:
            continue
        if pkg in SKIP:
            continue
        singles.add(pkg)

    print("singles: ", singles)
    print("can by uninstalled by: 'pip uninstall -y {}'".format(" ".join(singles)))


def reset_pip():
    """Reset pip to initial state"""
    names = get_names("pip list --format=freeze --exclude-editable")
    for name in names:
        os.system(f"pip3 uninstall -y --break-system-packages {name}")


def reset_pip2():
    """Reset pip to initial state"""
    os.system(
        "pip list --format=freeze --exclude-editable | xargs pip uninstall -y --break-system-packages"
    )
    os.system(
        "pip install --upgrade --break-system-packages pip setuptools wheel virtualenv"
    )


def main():
    parser = argparse.ArgumentParser(description="pip cleanup tools")
    parser.add_argument(
        "-c", "--clean", action="store_true", help="clean up unused dependencies"
    )
    parser.add_argument("-r", "--reset", action="store_true", help="reset pip")

    args = parser.parse_args()
    if args.clean:
        clean_deps()
    elif args.reset:
        reset_pip()


if __name__ == "__main__":
    main()
