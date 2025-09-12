import json
import subprocess
from types import SimpleNamespace
import yaml

def shell_output(cmd):
    return [line.strip() for line in subprocess.check_output(
        cmd.split(), encoding='utf8').splitlines() if line]

def get_pkg_names():
    return shell_output('brew list')

def get_pkg_desc(name):
    return subprocess.check_output(
        ['brew', 'info', name], encoding='utf8').splitlines()[1]

def get_pkg_info(name):
    return SimpleNamespace(**json.loads(subprocess.check_output(
        ['brew', 'info', '--json', name], encoding='utf8'))[0])

def get_all_pkg_info(pkgs):
    d = {}
    for p in get_pkg_names():
        try:
            d[p] = get_pkg_desc(p)
        except:
            print(f'ERROR: {p}')
    return d


def get_pkgs():
    d = {}
    for name in get_pkg_names():
        p = get_pkg_info(name)
        d[p.name] = dict(
            desc=p.desc, 
            build_deps=p.build_dependencies, 
            deps=p.dependencies)
    return d


def dump():
    d = get_pkgs()
    try:
        import yaml
        with open('pkgs.yml', 'w') as f:
            yaml.dump(d, f)
    except ImportError:            
        with open('pkgs.json', 'w') as f:
            json.dump(d, f)
    return d
