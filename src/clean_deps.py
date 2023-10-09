import subprocess
import sys

SKIP = [
    '------------------',
    'Cython',
    'Package',
    'pip',
    'setuptools',
    'wheel',
]

def print_dot():
    sys.stdout.write('.')
    sys.stdout.flush()

def get_output(cmds):
    return subprocess.check_output(
        cmds.split(), encoding='utf8', stderr=subprocess.DEVNULL)

def get_names():
    lines = get_output('pip list')
    lines = lines.splitlines()
    names = [line.split()[0].strip() for line in lines]
    _names = []
    for name in names:
        if name in SKIP or name.startswith('-----'):
            continue
        _names.append(name)
    return _names

def get_required_by(name) -> list[str]:
    deps = None
    try:
        lines = get_output(f'pip show {name}')
        lines = lines.splitlines()
        for line in lines:
            if line.startswith('Required-by: '):
                _line = line.replace('Required-by: ', '')
                deps = _line.split() 
    except subprocess.CalledProcessError as e:
        pass
    return deps

def main():
    required_by = set()
    not_required_by = set()
    singles = set()

    names = get_names()

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

    print('singles: ', singles)
    print("can by uninstalled by: 'pip uninstall -y {}'".format(' '.join(singles)))

if __name__ == '__main__':
    main()

