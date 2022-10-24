#!/usr/bin/env python3

"""rpkg.py: manage r package services."""

import argparse
import logging
import os

REPO='https://cran.rstudio.com'

def main():
    """Main commandline entry point to application."""

    logging.basicConfig(
         level=logging.INFO,
         format= '%(asctime)s [%(levelname)-8s] %(name)s.%(funcName)s: %(message)s',
         datefmt='%H:%M:%S'
    )

    log = logging.getLogger('rpkg')


    def scmd(shellcmd, *args, **kwds):
        """utility function to call shell commands.
        """
        shellcmd = shellcmd.format(*args, **kwds)
        log.info(shellcmd)
        os.system(shellcmd)

    def rcmd(cmd, *args, **kwds):
        """utility function to call r functions
        """
        r_cmd = cmd.format(*args, **kwds)
        shell_cmd = f'Rscript -e "{r_cmd}"'
        scmd(shell_cmd)

    def srcmd(cmd, *args, **kwds):
        """utility function to call r functions
        """
        r_cmd = cmd.format(*args, **kwds)
        shell_cmd = f'Rscript -e "{r_cmd}"'
        #print(shell_cmd)
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
