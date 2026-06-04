#!/usr/bin/env python3
"""Reflow Markdown/prose text between hard-wrapped and soft-wrapped forms.

Two modes:

  unwrap (default)  Join the hard-wrapped lines of each paragraph or list item
                    into one long logical line, so the editor soft-wraps it. This
                    is the "lines exceed a fixed width and are word-wrapped by the
                    viewer" style.
  wrap              Hard-wrap each logical line to a fixed column width (--width),
                    the "fixed-length lines with explicit breaks" style.

The two modes are inverses, so `wrap` then `unwrap` (or vice versa) round-trips
the prose content (whitespace runs collapse to single spaces).

Structure that must NOT be reflowed is passed through verbatim:
  - fenced code blocks (``` or ~~~), including their contents,
  - tables (any line containing '|'),
  - ATX headings (#, ##, ...),
  - horizontal rules (---, ***, ___),
  - blank lines,
  - standalone indented lines (>=4 spaces / a tab) outside a list.

List items keep their marker and leading indent; nested items stay separate
items. In wrap mode, continuation lines are hanging-indented under the item text.

Caveats: a prose line that happens to contain '|' is treated as a table row and
left alone. Markdown hard line breaks (two trailing spaces or a trailing '\\') are
not preserved across an unwrap.

Usage:
  reflow.py [FILE ...] [--mode {unwrap,wrap}] [--width N] [--in-place]
  reflow.py CHANGELOG.md --mode unwrap --in-place
  cat notes.md | reflow.py --mode wrap --width 88 > wrapped.md

With no FILE, reads stdin and writes stdout. --in-place rewrites each FILE
(ignored when reading stdin).
"""
import argparse
import re
import sys
import textwrap

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


def reflow(text, mode='unwrap', width=88):
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


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Reflow Markdown/prose between hard-wrapped and soft-wrapped forms.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('files', nargs='*', help='files to reflow (default: stdin -> stdout)')
    ap.add_argument('--mode', choices=('unwrap', 'wrap'), default='unwrap',
                    help='unwrap = one line per paragraph/item (default); wrap = hard-wrap to --width')
    ap.add_argument('--width', type=int, default=88,
                    help='column width for --mode wrap (default: 88)')
    ap.add_argument('--in-place', action='store_true',
                    help='rewrite each FILE in place instead of writing to stdout')
    args = ap.parse_args(argv)

    if args.width < 1:
        ap.error('--width must be >= 1')

    if not args.files:
        sys.stdout.write(reflow(sys.stdin.read(), args.mode, args.width))
        return 0

    for path in args.files:
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        result = reflow(src, args.mode, args.width)
        if args.in_place:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(result)
        else:
            sys.stdout.write(result)
    return 0


if __name__ == '__main__':
    sys.exit(main())
