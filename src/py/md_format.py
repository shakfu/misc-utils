#!/usr/bin/env python3
"""Markdown text formatters, merged behind one CLI.

Transforms, each available as a subcommand:

  space    Insert a blank line between adjacent markdown list items, so each
           bullet is its own loose-list paragraph. Idempotent.
  reflow   Reflow prose/Markdown between hard-wrapped and soft-wrapped forms
           (--mode unwrap|wrap, --width N).
  all      Apply reflow then space in one pass (reflow's --mode/--width apply).

  'all' is the default: if the first argument is not a subcommand name (and is
  not -h/--help), 'all' is assumed, so `md_format.py notes.md` runs the combined
  transform. Pass `space` or `reflow` explicitly to run just that one.

All subcommands share the same input/output handling:

  - With no PATH, read stdin and write stdout.
  - With one or more file PATHs, transform each (stdout by default, or rewrite
    the file with --in-place).
  - With --recursive, treat directory PATHs as roots and process every file
    matching --glob beneath them, skipping --exclude directory names.

Examples:
  md_format.py space notes.md
  md_format.py space -r -i docs --glob '**/*.md'
  cat notes.md | md_format.py reflow --mode wrap --width 88
  md_format.py reflow --mode unwrap -i CHANGELOG.md
  md_format.py all --mode wrap --width 88 -i notes.md
  md_format.py notes.md            # 'all' assumed
  md_format.py --mode wrap notes.md  # 'all' assumed, flags forwarded
"""
import argparse
import re
import sys
import textwrap
from pathlib import Path

DEFAULT_EXCLUDE = {".git", ".build", "build", "node_modules", ".venv", "venv"}


# --------------------------------------------------------------------------- #
# space: blank lines between adjacent bullets (from space_bullets.py)
# --------------------------------------------------------------------------- #

BULLET_RE = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s")


def is_bullet(line: str) -> bool:
    return bool(BULLET_RE.match(line))


def space_bullets(text: str) -> str:
    """Insert a blank line between adjacent list items. Idempotent."""
    lines = text.splitlines()
    out: list[str] = []
    prev_in_list = False
    for line in lines:
        if is_bullet(line) and prev_in_list and out and out[-1] != "":
            out.append("")
        out.append(line)
        if line.strip() == "":
            prev_in_list = False
        elif is_bullet(line):
            prev_in_list = True
        else:
            # Indented continuation belongs to the previous bullet; anything
            # else breaks the list.
            prev_in_list = prev_in_list and line.startswith((" ", "\t"))
    result = "\n".join(out)
    if text.endswith("\n"):
        result += "\n"
    return result


# --------------------------------------------------------------------------- #
# reflow: hard-wrap <-> soft-wrap (from reflow.py)
# --------------------------------------------------------------------------- #

LIST_RE = re.compile(r'^(\s*)([-*+]|\d+[.)])(\s+)(.*)$')
HEADING_RE = re.compile(r'^\s{0,3}#{1,6}(\s|$)')
HR_RE = re.compile(r'^\s*([-*_])(\s*\1){2,}\s*$')
FENCE_RE = re.compile(r'^\s*(```+|~~~+)')


class Unit:
    """A reflowable logical block: one paragraph or one list item.

    prefix       printed before the first rendered line (indent + any marker).
    cont_indent  indent applied to wrapped continuation lines (wrap mode only).
    parts        the source line fragments, joined with single spaces.
    """

    __slots__ = ('prefix', 'cont_indent', 'parts')

    def __init__(self, prefix, cont_indent, first):
        self.prefix = prefix
        self.cont_indent = cont_indent
        self.parts = [first]

    def text(self):
        return ' '.join(p.strip() for p in self.parts if p.strip())


def _render(unit, mode, width):
    text = unit.text()
    if mode == 'unwrap':
        return [unit.prefix + text]
    wrapped = textwrap.fill(
        text,
        width=width,
        initial_indent=unit.prefix,
        subsequent_indent=unit.cont_indent,
        break_long_words=False,   # don't split a long URL/token mid-word
        break_on_hyphens=False,   # don't split hyphenated identifiers
    )
    return wrapped.split('\n')


def reflow(text: str, mode: str = 'unwrap', width: int = 88) -> str:
    """Reflow a document string and return the transformed string."""
    had_trailing_nl = text.endswith('\n')
    out = []
    unit = None
    in_fence = False
    fence_marker = None

    def flush():
        nonlocal unit
        if unit is not None:
            out.extend(_render(unit, mode, width))
            unit = None

    for raw in text.splitlines():
        line = raw

        # Fenced code: emit verbatim until a matching closing fence.
        m = FENCE_RE.match(line)
        if in_fence:
            out.append(line)
            if m and m.group(1)[0] == fence_marker[0] and len(m.group(1)) >= len(fence_marker):
                in_fence, fence_marker = False, None
            continue
        if m:
            flush()
            out.append(line)
            in_fence, fence_marker = True, m.group(1)
            continue

        # Blank line: paragraph/list-item separator.
        if line.strip() == '':
            flush()
            out.append(line)
            continue

        # Pass-through structures (heading, horizontal rule, table row).
        if HEADING_RE.match(line) or HR_RE.match(line) or '|' in line:
            flush()
            out.append(line)
            continue

        # List item start (also handles nested items: each starts a new unit).
        lm = LIST_RE.match(line)
        if lm:
            flush()
            leading, marker, _gap, content = lm.groups()
            prefix = leading + marker + ' '
            unit = Unit(prefix, ' ' * len(prefix), content)
            continue

        # Standalone indented line outside any unit: treat as code, keep as-is.
        if unit is None and (line.startswith('    ') or line.startswith('\t')):
            out.append(line)
            continue

        # Otherwise: paragraph text, or a continuation of the open unit.
        if unit is None:
            leading = line[:len(line) - len(line.lstrip())]
            unit = Unit(leading, leading, line.lstrip())
        else:
            unit.parts.append(line)

    flush()
    result = '\n'.join(out)
    if had_trailing_nl:
        result += '\n'
    return result


# --------------------------------------------------------------------------- #
# Shared CLI plumbing
# --------------------------------------------------------------------------- #

def gather_files(parser, paths, recursive, glob, exclude):
    """Expand PATH arguments into a sorted list of files to process.

    Directory PATHs are only allowed with --recursive, in which case they are
    globbed; plain files are taken as-is.
    """
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            if not recursive:
                parser.error(f"{p} is a directory; pass --recursive to process it")
            matched = sorted(
                f for f in p.glob(glob)
                if f.is_file() and not any(part in exclude for part in f.parts)
            )
            if not matched:
                print(f"no files matched {glob!r} under {p}", file=sys.stderr)
            files.extend(matched)
        elif p.exists():
            files.append(p)
        else:
            parser.error(f"no such file or directory: {p}")
    return files


def run(parser, args, transform) -> int:
    """Drive `transform` (str -> str) over stdin or the resolved file list."""
    if args.in_place and not args.paths:
        parser.error("--in-place requires a PATH (cannot rewrite stdin)")
    if args.recursive and not args.paths:
        parser.error("--recursive requires a directory PATH")

    # stdin -> stdout
    if not args.paths:
        sys.stdout.write(transform(sys.stdin.read()))
        return 0

    exclude = set(args.exclude) if args.exclude else DEFAULT_EXCLUDE
    files = gather_files(parser, args.paths, args.recursive, args.glob, exclude)

    changed_count = 0
    for f in files:
        src = f.read_text(encoding="utf-8")
        result = transform(src)
        if args.in_place:
            if result != src:
                f.write_text(result, encoding="utf-8")
                changed_count += 1
                print(f"rewrote: {f}")
        elif args.recursive:
            # Many files, not rewriting: report what would change, not content.
            if result != src:
                changed_count += 1
                print(f"would rewrite: {f}")
        else:
            sys.stdout.write(result)

    if args.recursive and not args.in_place and changed_count:
        print(
            f"\n{changed_count} file(s) would change. "
            f"Re-run with --in-place to apply.",
            file=sys.stderr,
        )
    return 0


def add_common_io(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="Markdown file(s), or directory(ies) with --recursive. "
             "Omit to read stdin.",
    )
    sub.add_argument(
        "-i", "--in-place",
        action="store_true",
        help="Rewrite each FILE in place instead of writing to stdout.",
    )
    sub.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Treat directory PATHs as roots and process every --glob match beneath.",
    )
    sub.add_argument(
        "--glob",
        default="**/*.md",
        help="Glob (relative to a directory PATH) used with --recursive "
             "(default: %(default)s).",
    )
    sub.add_argument(
        "--exclude",
        action="append",
        default=None,
        metavar="DIR",
        help="Directory name to skip while recursing. Repeatable. "
             "Defaults to: " + ", ".join(sorted(DEFAULT_EXCLUDE)) + ".",
    )


def add_reflow_opts(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--mode", "-m",
        choices=("unwrap", "wrap"),
        default="unwrap",
        help="unwrap = one line per paragraph/item (default); "
             "wrap = hard-wrap to --width.",
    )
    sub.add_argument(
        "--width", "-w",
        type=int,
        default=88,
        help="Column width for --mode wrap (default: %(default)s).",
    )


SUBCOMMANDS = ("space", "reflow", "all")
DEFAULT_COMMAND = "all"


def inject_default_command(argv):
    """Prepend DEFAULT_COMMAND unless argv already names a subcommand.

    Lets `md_format.py notes.md` mean `md_format.py all notes.md` while keeping
    `space`/`reflow`/`all` as explicit verbs. Only argv[0] is inspected, so a
    subcommand name appearing as a flag value (e.g. `--glob all`) is not mistaken
    for the command. An empty argv is left untouched so argparse emits its usual
    "required subcommand" error, and a leading -h/--help reaches the top-level
    parser instead of being swallowed by the default subcommand.
    """
    if argv and (argv[0] in SUBCOMMANDS or argv[0] in ("-h", "--help")):
        return argv
    if not argv:
        return argv
    return [DEFAULT_COMMAND, *argv]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="md_format.py",
        description="Markdown formatters: space out bullets and/or reflow text.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p_space = sub.add_parser(
        "space",
        help="Insert a blank line between adjacent markdown list items.",
        description="Insert a blank line between adjacent markdown list items "
                    "(unordered -, *, + and ordered 1., 1)). Idempotent: "
                    "already-separated items are left alone.",
    )
    add_common_io(p_space)
    p_space.set_defaults(transform_factory=lambda a: space_bullets)

    p_reflow = sub.add_parser(
        "reflow",
        help="Reflow text between hard-wrapped and soft-wrapped forms.",
        description="Reflow Markdown/prose between hard-wrapped and soft-wrapped "
                    "forms. unwrap joins each paragraph/item to one line; wrap "
                    "hard-wraps to --width. Headings, tables, fenced code, and "
                    "horizontal rules pass through untouched.",
    )
    add_reflow_opts(p_reflow)
    add_common_io(p_reflow)
    p_reflow.set_defaults(
        transform_factory=lambda a: (lambda text: reflow(text, a.mode, a.width))
    )

    p_all = sub.add_parser(
        "all",
        help="Apply reflow then space in one pass.",
        description="Apply both transforms in one pass: reflow first (using "
                    "--mode/--width), then space out adjacent bullets. "
                    "Equivalent to piping reflow into space.",
    )
    add_reflow_opts(p_all)
    add_common_io(p_all)
    p_all.set_defaults(
        transform_factory=lambda a: (
            lambda text: space_bullets(reflow(text, a.mode, a.width))
        )
    )

    return parser


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv and not sys.stdin.isatty():
        # Bare invocation with piped input: act as a filter under DEFAULT_COMMAND.
        # A bare TTY invocation keeps the empty argv so argparse prints usage.
        argv = [DEFAULT_COMMAND]
    argv = inject_default_command(argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in ("reflow", "all") and args.width < 1:
        parser.error("--width must be >= 1")

    transform = args.transform_factory(args)
    return run(parser, args, transform)


if __name__ == "__main__":
    raise SystemExit(main())
