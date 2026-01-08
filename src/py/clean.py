#!/usr/bin/env python3
"""
This script recursively scans a given path and applies a cleaning 'action'
to matching files and folders. By default files and folders matching the
specified (.endswith) patterns are deleted. Alternatively, _quoted_ glob
patterns can used with the '-g' option.

By design, the script lists targets and asks permission before applying
cleaning actions. It should be easy to extend this script with further
cleaning actions and more intelligent pattern matching techniques.

The getch (single key confirmation) functionality comes courtesy of
http://code.activestate.com/recipes/134892/

To use it, place the script in your path and call it something like 'clean':

    Usage: clean [options] patterns

            deletes files/folder patterns:
                clean .svn .pyc
                clean -p /tmp/folder .svn .csv .bzr .pyc
                clean -g "*.pyc"
                clean -g "*/._*"
                clean -ng "*.py"

            converts line endings from windows to unix:
                clean -e .py
                clean -e -p /tmp/folder .py

    Options:
      -h, --help            show this help message and exit
      -p PATH, --path=PATH  set path
      -n, --negated         clean everything except specified patterns
      -e, --endings         clean line endings
      -v, --verbose

"""

import os, sys, shutil
from fnmatch import fnmatch
import argparse
from os.path import join, isdir, isfile


# to enable single-character confirmation of choices
try:
    import tty, termios
    def getch(txt):
        print(txt, end=' ', flush=True)
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch
except ImportError:
    import msvcrt
    def getch(txt):
        print(txt, end=' ')
        return msvcrt.getch()

# -----------------------------------------------------
# main class

class Cleaner(object):
    """recursively cleans patterns of files/directories
    """
    def __init__(self, path, patterns, dry_run=False):
        self.path = path
        self.patterns = patterns
        self.dry_run = dry_run
        self.matchers = {
            # a matcher is a boolean function which takes a string and tries
            # to match it against any one of the specified patterns,
            # returning False otherwise
            'endswith': lambda s: any(s.endswith(p) for p in patterns),
            'glob': lambda s: any(fnmatch(s, p) for p in patterns),
        }
        self.actions = {
            # action: (path_operating_func, matcher)
            'endswith_delete': (self.delete, 'endswith'),
            'glob_delete': (self.delete, 'glob'),
            'convert': (self.clean_endings, 'endswith'),
        }
        self.targets = []
        self.cum_size = 0.0

    def __repr__(self):
        return "<Cleaner: path:%s , patterns:%s>" % (
            self.path, self.patterns)

    def _apply(self, func, confirm=False):
        """applies a function to each target path
        """
        i = 0
        desc = func.__doc__.strip()
        for target in self.targets:
            if confirm:
                question = "\n%s '%s' (y/n/q)? " % (desc, target)
                answer = getch(question)
                if answer in ['y', 'Y']:
                    if self.dry_run:
                        self.log("Would %s '%s'" % (desc, target))
                    else:
                        func(target)
                    i += 1
                elif answer in ['q']: #i.e. quit
                    break
                else:
                    continue
            else:
                if self.dry_run:
                    self.log("Would %s '%s'" % (desc, target))
                else:
                    func(target)
                i += 1
        if i:
            action_word = "Would apply" if self.dry_run else "Applied"
            self.log("%s '%s' to %s items (%sK)" % (
                action_word, desc, i, int(round(self.cum_size/1024.0, 0))))
        else:
            self.log('No action taken')

    @staticmethod
    def _onerror(func, path, exc_info):
        """ Error handler for shutil.rmtree.

            If the error is due to an access error (read only file)
            it attempts to add write permission and then retries.

            If the error is for another reason it re-raises the error.

            Usage : ``shutil.rmtree(path, onerror=onerror)``

            original code by Michael Foord
            bug fix suggested by Kun Zhang

        """
        import stat
        if not os.access(path, os.W_OK):
            # Is the error an access error ?
            os.chmod(path, stat.S_IWUSR)
            func(path)
        else:
            raise

    def log(self, txt):
        print('\n' + txt)

    def do(self, action, negate=False):
        """finds pattern and approves action on results
        """
        func, matcher = self.actions[action]
        if not negate:
            show = lambda p: p if self.matchers[matcher](p) else None
        else:
            show = lambda p: p if not self.matchers[matcher](p) else None

        results = self.walk(self.path, show)
        if results:
            question = "%s item(s) found. Apply '%s' to all (y/n/c)? " % (
                len(results), func.__doc__.strip())
            answer = getch(question)
            self.targets = results
            if answer in ['y','Y']:
                self._apply(func)
            elif answer in ['c', 'C']:
                self._apply(func, confirm=True)
            else:
                self.log("Action cancelled.")
        else:
            self.log("No results.")

    def walk(self, path, func, log=True):
        """walk path recursively collecting results of function application
        """
        results = []
        def visit(root, target, prefix):
            for i in target:
                item = join(root, i)
                obj = func(item)
                if obj:
                    results.append(obj)
                    self.cum_size += os.path.getsize(obj)
                    if log:
                        print(prefix, obj)
        for root, dirs, files in os.walk(path):
            visit(root, dirs, ' +-->')
            visit(root, files,' |-->')
        return results

    def delete(self, path):
        """delete path
        """
        if isfile(path):
            os.remove(path)
        if isdir(path):
            shutil.rmtree(path, onerror=self._onerror)

    def clean_endings(self, path):
        """convert windows endings to unix endings
        """
        with open(path) as old:
            lines = old.readlines()
        string = "".join(l.rstrip()+'\n' for l in lines)
        with open(path, 'w') as new:
            new.write(string)

    @classmethod
    def cmdline(cls):
        parser = argparse.ArgumentParser(
            description='Recursively cleans patterns of files/directories',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  Delete files/folder patterns:
    clean .svn .pyc
    clean -p /tmp/folder .svn .csv .bzr .pyc
    clean -g "*.pyc"
    clean -g "*/._*"
    clean -gn "*.py"

  Convert line endings from windows to unix:
    clean -e .py
    clean -e -p /tmp/folder .py

  Dry run mode (show what would be deleted without deleting):
    clean --dry-run .pyc .pyo
    clean -d -g "*.pyc"
        """)

        arg = opt = parser.add_argument
        arg('patterns', nargs='*', help='Patterns to match (e.g., .pyc .pyo)')
        opt('-p', '--path', default='.', help='Set path to search (default: current directory)')
        opt('-n', '--negated', action='store_true', help='Clean everything except specified patterns')
        opt('-e', '--endings', action='store_true', help='Clean line endings (convert windows to unix)')
        opt('-g', '--glob', action='store_true', help='Use glob patterns instead of endswith matching')
        opt('-a', '--all', action='store_true', help='Clean all detritus (default patterns)')
        opt('-d', '--dry-run', action='store_true', help='Show what would be cleaned without actually doing it')
        opt('-v', '--verbose', action='store_true', help='Verbose output')

        args = parser.parse_args()

        # Default patterns when none specified
        if len(args.patterns) == 0:
            args.patterns = ['.pyc', '.DS_Store', '__pycache__']
            cleaner = cls(args.path, args.patterns, dry_run=args.dry_run)
            cleaner.do('endswith_delete')
            if args.all:
                args.patterns = ["*/._*"]
                cleaner = cls(args.path, args.patterns, dry_run=args.dry_run)
                cleaner.do('glob_delete')
            sys.exit()

        if args.verbose:
            print('Options:', args)
            print('Finding patterns: %s in %s' % (args.patterns, args.path))

        cleaner = cls(args.path, args.patterns, dry_run=args.dry_run)

        # convert line endings from windows to unix
        if args.endings and args.negated:
            cleaner.do('convert', negate=True)
        elif args.endings:
            cleaner.do('convert', negate=False)

        # glob delete
        elif args.negated and args.glob:
            cleaner.do('glob_delete', negate=True)
        elif args.glob:
            cleaner.do('glob_delete')

        # endswith delete (default)
        elif args.negated:
            cleaner.do('endswith_delete', negate=True)
        else:
            cleaner.do('endswith_delete')

if __name__ == '__main__':
    Cleaner.cmdline()
