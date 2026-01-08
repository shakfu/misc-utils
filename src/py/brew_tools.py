#!/usr/bin/env python3
"""Unified brew package management utilities.

Combines functionality from brew_to_csv.py and dump_brew_pkgs.py.
"""

import csv
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Optional


def shell_output(cmd: str) -> list[str]:
    """Execute shell command and return output lines."""
    return [line.strip() for line in subprocess.check_output(
        cmd.split(), encoding='utf8').splitlines() if line]


def get_pkg_names() -> list[str]:
    """Get list of installed brew package names."""
    return shell_output('brew list')


def get_pkg_desc(name: str) -> str:
    """Get package description from brew info."""
    try:
        output = subprocess.check_output(
            ['brew', 'info', name], encoding='utf8').splitlines()
        return output[1] if len(output) > 1 else ""
    except subprocess.CalledProcessError as e:
        print(f"Error getting description for {name}: {e}")
        return ""
    except Exception as e:
        print(f"Unexpected error for {name}: {e}")
        return ""


def get_pkg_info(name: str) -> Optional[SimpleNamespace]:
    """Get detailed package info as SimpleNamespace."""
    try:
        result = subprocess.check_output(
            ['brew', 'info', '--json', name], encoding='utf8')
        data = json.loads(result)[0]
        return SimpleNamespace(**data)
    except subprocess.CalledProcessError as e:
        print(f"Error getting info for {name}: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON for {name}: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error for {name}: {e}")
        return None


def get_all_pkg_info() -> dict[str, str]:
    """Get description for all installed packages."""
    info_dict = {}
    for pkg_name in get_pkg_names():
        desc = get_pkg_desc(pkg_name)
        if desc:
            info_dict[pkg_name] = desc
    return info_dict


def get_detailed_pkgs() -> dict[str, dict]:
    """Get detailed info (desc, deps, build_deps) for all packages."""
    pkg_dict = {}
    for name in get_pkg_names():
        pkg_info = get_pkg_info(name)
        if pkg_info:
            pkg_dict[pkg_info.name] = {
                'desc': pkg_info.desc,
                'build_deps': pkg_info.build_dependencies,
                'deps': pkg_info.dependencies
            }
    return pkg_dict


def get_installed_json() -> list[dict]:
    """Get full JSON info for all installed packages."""
    try:
        result = subprocess.check_output(
            ['brew', 'info', '--json', '--installed'],
            encoding='utf8'
        )
        return json.loads(result)
    except subprocess.CalledProcessError as e:
        print(f"Error getting installed packages: {e}")
        return []
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        return []


def dump_to_csv(output_file: str = 'brew_packages.csv') -> None:
    """Dump package info to CSV file."""
    pkgs = get_installed_json()

    with open(output_file, 'w', newline='') as csvfile:
        fieldnames = ['name', 'version', 'desc']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for pkg in pkgs:
            writer.writerow({
                'name': pkg['name'],
                'version': pkg['versions']['stable'],
                'desc': pkg['desc'],
            })

    print(f"Exported {len(pkgs)} packages to {output_file}")


def dump_to_yaml(output_file: str = 'brew_packages.yml') -> None:
    """Dump detailed package info to YAML file."""
    try:
        import yaml
    except ImportError:
        print("Error: PyYAML not installed. Install with: pip install pyyaml")
        print("Falling back to JSON output...")
        dump_to_json(output_file.replace('.yml', '.json'))
        return

    pkg_dict = get_detailed_pkgs()

    with open(output_file, 'w') as f:
        yaml.dump(pkg_dict, f, default_flow_style=False)

    print(f"Exported {len(pkg_dict)} packages to {output_file}")


def dump_to_json(output_file: str = 'brew_packages.json') -> None:
    """Dump detailed package info to JSON file."""
    pkg_dict = get_detailed_pkgs()

    with open(output_file, 'w') as f:
        json.dump(pkg_dict, f, indent=2)

    print(f"Exported {len(pkg_dict)} packages to {output_file}")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Manage and export brew package information',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all installed packages
  brew_tools.py --list

  # Export to CSV
  brew_tools.py --csv

  # Export to JSON
  brew_tools.py --json

  # Export to YAML (requires pyyaml)
  brew_tools.py --yaml

  # Custom output file
  brew_tools.py --csv --output my_packages.csv
        """
    )

    parser.add_argument('--list', action='store_true',
                      help='List all installed package names')
    parser.add_argument('--csv', action='store_true',
                      help='Export to CSV format')
    parser.add_argument('--json', dest='json_output', action='store_true',
                      help='Export to JSON format')
    parser.add_argument('--yaml', action='store_true',
                      help='Export to YAML format (requires pyyaml)')
    parser.add_argument('-o', '--output', type=str,
                      help='Output file path')

    args = parser.parse_args()

    # Determine action
    if args.list:
        for pkg in get_pkg_names():
            print(pkg)
    elif args.csv:
        output = args.output or 'brew_packages.csv'
        dump_to_csv(output)
    elif args.json_output:
        output = args.output or 'brew_packages.json'
        dump_to_json(output)
    elif args.yaml:
        output = args.output or 'brew_packages.yml'
        dump_to_yaml(output)
    else:
        # Default: show help
        parser.print_help()
