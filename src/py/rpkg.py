#!/usr/bin/env python3

"""rpkg.py: manage r package services."""

import argparse
import logging
import subprocess
from typing import Any

REPO='https://cran.rstudio.com'

def main() -> None:
    """Main commandline entry point to application."""

    logging.basicConfig(
         level=logging.INFO,
         format= '%(asctime)s [%(levelname)-8s] %(name)s.%(funcName)s: %(message)s',
         datefmt='%H:%M:%S'
    )

    log = logging.getLogger('rpkg')


    def scmd(shellcmd: str, *args: Any, **kwds: Any) -> None:
        """Run a shell command via subprocess, logging it first."""
        shellcmd = shellcmd.format(*args, **kwds)
        log.info(shellcmd)
        subprocess.run(shellcmd, shell=True, check=False)

    def rcmd(cmd: str, *args: Any, **kwds: Any) -> None:
        """Build and run an Rscript -e invocation."""
        r_cmd = cmd.format(*args, **kwds)
        shell_cmd = f'Rscript -e "{r_cmd}"'
        scmd(shell_cmd)

    def srcmd(cmd: str, *args: Any, **kwds: Any) -> None:
        """Build and run an Rscript -e invocation."""
        r_cmd = cmd.format(*args, **kwds)
        shell_cmd = f'Rscript -e "{r_cmd}"'
        scmd(shell_cmd)

    parser = argparse.ArgumentParser()
    # parser.add_argument('--foo', action='store_true', help='foo help')

    subparsers = parser.add_subparsers(help='sub-command help', dest='command')

    # install
    install = subparsers.add_parser('install', help='install packages')
    install.add_argument('package', nargs="+", help='packages to install')

    # update
    update = subparsers.add_parser('update', help='update packages')

    # remove
    remove = subparsers.add_parser('remove', help='remove packages')
    remove.add_argument('package', nargs="+", help='packages to install')

    args = parser.parse_args()

    # print(args)

    if args.command == 'install':
        log.info('INSTALL')
        packages = str(args.package).lstrip('[').rstrip(']')
        srcmd(f"install.packages(c({packages}), repos=c('{REPO}'))")

    if args.command == 'update':
        log.info('UPDATE')
        srcmd(f"update.packages(ask=F, repos=c('{REPO}'))")

    if args.command == 'remove':
        log.info('REMOVE')
        packages = str(args.package).lstrip('[').rstrip(']')
        srcmd(f"remove.packages(c({packages}))")


if __name__ == '__main__':
    main()
