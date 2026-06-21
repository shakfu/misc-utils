#!/usr/bin/env python3
"""diff2html.py -- render diffs as colored HTML, two ways.

Methods (-m/--method):
  git      run `git diff` and convert its unified output to colored HTML
           (red deletions, green additions, blue hunk headers). This is the
           default.
  difflib  use the standard library's difflib.HtmlDiff to render a
           side-by-side HTML table.

Inputs (pick one of the two forms):
  --from REF [--to REF] --path PATH
           two git revisions of a file; omit --to to compare REF against the
           current working-tree copy at PATH.
  --file-a PATH --file-b PATH
           two files on disk.

The optional --clean filter strips drafting-note blockquotes (lines matching
--clean-pattern) and squeezes the resulting blank lines before diffing,
mirroring bylaws/diff-clean-bylaws.sh so the diff shows only operative text.

Examples:
  # colored git diff of two commits of a file, operative-only, to a file
  diff2html.py --from 70bb427 --to HEAD --path bylaws/_bylaws.qmd --clean \\
      -o diff.html
  # a commit vs the working tree
  diff2html.py --from HEAD --path bylaws/_bylaws.qmd -o diff.html
  # side-by-side difflib view of two files, whole document
  diff2html.py -m difflib --file-a old.md --file-b new.md --full -o diff.html
"""
from __future__ import annotations

import argparse
import difflib
import html
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def run(cmd):
    """Run a command, returning (returncode, stdout, stderr)."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def git_show(ref, path):
    """Return the contents of PATH at git revision REF."""
    code, out, err = run(["git", "show", f"{ref}:{path}"])
    if code != 0:
        raise SystemExit(f"git show {ref}:{path} failed: {err.strip()}")
    return out


def clean_text(text, pattern):
    """Drop lines matching PATTERN and squeeze consecutive blanks (cat -s)."""
    rx = re.compile(pattern)
    out, blank = [], False
    for ln in text.splitlines():
        if rx.match(ln):
            continue
        if ln.strip() == "":
            if blank:
                continue
            blank = True
        else:
            blank = False
        out.append(ln)
    return "\n".join(out) + "\n"


def classify(line):
    """Map a unified-diff line to a CSS class name."""
    if line.startswith(("+++", "---")):
        return "filehdr"
    if line.startswith(
        ("diff ", "index ", "new file", "deleted file", "rename ", "similarity ")
    ):
        return "meta"
    if line.startswith("@@"):
        return "hunk"
    if line.startswith("+"):
        return "add"
    if line.startswith("-"):
        return "del"
    if line.startswith("\\"):  # "\ No newline at end of file"
        return "meta"
    return "ctx"


# --------------------------------------------------------------------------- #
# git method
# --------------------------------------------------------------------------- #
def _relabel(diff, old_label, new_label):
    """Rewrite the header lines of a --no-index diff to friendly labels."""
    res = []
    for ln in diff.splitlines():
        if ln.startswith("--- "):
            res.append(f"--- {old_label}")
        elif ln.startswith("+++ "):
            res.append(f"+++ {new_label}")
        elif ln.startswith("diff --git"):
            res.append(f"diff --git {old_label} {new_label}")
        else:
            res.append(ln)
    return "\n".join(res) + ("\n" if res else "")


def git_no_index(a_text, b_text, old_label, new_label, context):
    """Diff two in-memory blobs via `git diff --no-index`, with friendly labels."""
    with tempfile.TemporaryDirectory() as d:
        pa, pb = os.path.join(d, "a"), os.path.join(d, "b")
        Path(pa).write_text(a_text)
        Path(pb).write_text(b_text)
        code, out, err = run(
            ["git", "diff", "--no-index", f"--unified={context}", pa, pb]
        )
    if code not in (0, 1):  # 1 just means "files differ"
        raise SystemExit(err.strip() or "git diff --no-index failed")
    return _relabel(out, old_label, new_label)


def make_git_diff(args):
    """Return the unified-diff text for the requested inputs (git method)."""
    if args.file_a or args.file_b:
        if not (args.file_a and args.file_b):
            raise SystemExit("--file-a and --file-b must be given together")
        a, b = Path(args.file_a).read_text(), Path(args.file_b).read_text()
        if args.clean:
            a = clean_text(a, args.clean_pattern)
            b = clean_text(b, args.clean_pattern)
        return git_no_index(a, b, args.file_a, args.file_b, args.context)

    if args.from_ref and args.path:
        old_label = f"{args.from_ref}:{args.path}"
        new_label = (
            f"{args.to_ref}:{args.path}"
            if args.to_ref
            else f"{args.path} (working tree)"
        )
        if args.clean:
            a = clean_text(git_show(args.from_ref, args.path), args.clean_pattern)
            b_raw = (
                git_show(args.to_ref, args.path)
                if args.to_ref
                else Path(args.path).read_text()
            )
            b = clean_text(b_raw, args.clean_pattern)
            return git_no_index(a, b, old_label, new_label, args.context)
        cmd = ["git", "diff", f"--unified={args.context}", args.from_ref]
        if args.to_ref:
            cmd.append(args.to_ref)
        cmd += ["--", args.path]
        code, out, err = run(cmd)
        if code not in (0, 1):
            raise SystemExit(err.strip() or "git diff failed")
        return out

    if args.from_ref:  # tree-wide diff (multiple files)
        if args.clean:
            print(
                "warning: --clean is ignored for a tree-wide diff (use --path)",
                file=sys.stderr,
            )
        rng = f"{args.from_ref}..{args.to_ref}" if args.to_ref else args.from_ref
        code, out, err = run(["git", "diff", f"--unified={args.context}", rng])
        if code not in (0, 1):
            raise SystemExit(err.strip() or "git diff failed")
        return out

    raise SystemExit("specify --from (with optional --to/--path) or --file-a/--file-b")


_CSS = """
:root { color-scheme: light dark; }
body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; margin: 1.5rem; }
h1 { font-size: 1.1rem; }
.diff { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 12.5px; line-height: 1.45; border: 1px solid #d0d7de;
        border-radius: 6px; overflow-x: auto; }
.line { display: block; white-space: %(white)s; overflow-wrap: %(wrap)s;
        padding: 0 .6rem; border-left: 3px solid transparent; }
.add { background: #e6ffec; border-left-color: #2da44e; }
.del { background: #ffebe9; border-left-color: #cf222e; }
.hunk { background: #ddf4ff; color: #0550ae; }
.filehdr { background: #f6f8fa; color: #57606a; font-weight: 600; }
.meta { background: #f6f8fa; color: #8c959f; }
.ctx { color: #1f2328; }
.legend span { display: inline-block; padding: .1rem .5rem; margin-right: .4rem;
        border-radius: 4px; font-size: 11px; }
"""


def unified_diff_to_html(diff_text, title, wrap=False):
    """Wrap a unified-diff string in a self-contained, colored HTML document."""
    spans = []
    for raw in diff_text.splitlines():
        escaped = html.escape(raw) or "&nbsp;"
        spans.append(f'<span class="line {classify(raw)}">{escaped}</span>')
    body = "\n".join(spans) if spans else '<span class="line ctx">(no differences)</span>'
    css = _CSS % {
        "white": "pre-wrap" if wrap else "pre",
        "wrap": "break-word" if wrap else "normal",
    }
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head><meta charset="utf-8">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>{css}</style></head>\n<body>\n"
        f"<h1>{html.escape(title)}</h1>\n"
        '<p class="legend"><span class="add">added</span>'
        '<span class="del">removed</span><span class="hunk">hunk</span>'
        '<span class="filehdr">file</span></p>\n'
        f'<div class="diff">{body}</div>\n'
        "</body></html>\n"
    )


# --------------------------------------------------------------------------- #
# difflib method
# --------------------------------------------------------------------------- #
def _resolve_pair(args):
    """Return (a_text, b_text, old_label, new_label) for the side-by-side view."""
    if args.file_a or args.file_b:
        if not (args.file_a and args.file_b):
            raise SystemExit("--file-a and --file-b must be given together")
        return (
            Path(args.file_a).read_text(),
            Path(args.file_b).read_text(),
            args.file_a,
            args.file_b,
        )
    if args.from_ref and args.path:
        a = git_show(args.from_ref, args.path)
        b = (
            git_show(args.to_ref, args.path)
            if args.to_ref
            else Path(args.path).read_text()
        )
        old_label = f"{args.from_ref}:{args.path}"
        new_label = (
            f"{args.to_ref}:{args.path}"
            if args.to_ref
            else f"{args.path} (working tree)"
        )
        return a, b, old_label, new_label
    raise SystemExit("difflib method needs --file-a/--file-b or --from + --path")


# difflib (a) tags content cells with the HTML `nowrap` attribute and (b) replaces every
# space with a non-breaking space, so each line becomes one unbreakable token that cannot
# wrap -- the table then grows to the width of the longest line and runs off-screen.
# The override below makes content cells soft-wrap, stretches the table to full width, and
# collapses the line-number / change-marker columns. It only works together with the
# `&nbsp;` -> space substitution in make_difflib_html (which restores breakable spaces);
# `white-space: pre-wrap` then preserves indentation while wrapping on word boundaries, and
# `overflow-wrap: break-word` splits only a token too long to fit (e.g. a URL), not prose.
_DIFFLIB_WRAP_CSS = """
table.diff { table-layout: fixed; width: 100%; }
table.diff td { white-space: pre-wrap !important; overflow-wrap: break-word;
    word-break: normal; vertical-align: top; }
table.diff td.diff_header, table.diff td.diff_next { white-space: nowrap !important; }
/* difflib emits 6 <colgroup>s: [marker][line-no][content] x2. Pin the four narrow
   columns; the two content colgroups (3 and 6) have no width and so split the
   remaining space equally, giving two equal-width text columns. */
table.diff colgroup:nth-of-type(1), table.diff colgroup:nth-of-type(4) { width: 1.6em; }
table.diff colgroup:nth-of-type(2), table.diff colgroup:nth-of-type(5) { width: 3.2em; }
"""


def _inject_wrap_css(doc):
    """Insert the word-wrap CSS override into a difflib HTML document."""
    block = f'<style type="text/css">{_DIFFLIB_WRAP_CSS}</style>'
    if "</head>" in doc:
        return doc.replace("</head>", block + "\n</head>", 1)
    return block + doc


def make_difflib_html(args):
    """Render a side-by-side HTML diff using difflib.HtmlDiff (word-wrapped)."""
    a, b, old_label, new_label = _resolve_pair(args)
    if args.clean:
        a = clean_text(a, args.clean_pattern)
        b = clean_text(b, args.clean_pattern)
    hd = difflib.HtmlDiff(wrapcolumn=args.wrapcolumn or None)
    doc = hd.make_file(
        a.splitlines(),
        b.splitlines(),
        old_label,
        new_label,
        context=not args.full,
        numlines=args.context,
    )
    # Restore breakable spaces so word wrapping can occur (see _DIFFLIB_WRAP_CSS).
    doc = doc.replace("&nbsp;", " ")
    return _inject_wrap_css(doc)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser():
    p = argparse.ArgumentParser(
        prog="diff2html.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "-m",
        "--method",
        choices=["git", "difflib"],
        default="git",
        help="rendering method (default: git)",
    )
    src = p.add_argument_group("inputs")
    src.add_argument("--from", dest="from_ref", metavar="REF", help="old git revision")
    src.add_argument(
        "--to",
        dest="to_ref",
        metavar="REF",
        help="new git revision (omit to compare against the working tree)",
    )
    src.add_argument("--path", help="file path within the repo (used with --from/--to)")
    src.add_argument("--file-a", help="old file on disk")
    src.add_argument("--file-b", help="new file on disk")
    opt = p.add_argument_group("options")
    opt.add_argument(
        "-c",
        "--context",
        type=int,
        default=3,
        help="context lines (git: --unified; difflib: numlines) (default: 3)",
    )
    opt.add_argument(
        "--full",
        action="store_true",
        help="difflib only: show the whole file, not just changed regions",
    )
    opt.add_argument(
        "--clean",
        action="store_true",
        help="strip drafting-note lines (see --clean-pattern) before diffing",
    )
    opt.add_argument(
        "--clean-pattern",
        default=r"^> Drafting note",
        help=r"regex for --clean (default: '^> Drafting note')",
    )
    opt.add_argument(
        "--wrap",
        action="store_true",
        help="git method: wrap long lines instead of horizontal scrolling",
    )
    opt.add_argument(
        "--wrapcolumn",
        type=int,
        default=0,
        help="difflib method: wrap lines at this column (0 = no wrap)",
    )
    opt.add_argument(
        "--title", default="Diff", help="HTML title/heading for the git method"
    )
    opt.add_argument("-o", "--output", help="output HTML file (default: stdout)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.method == "git":
        diff = make_git_diff(args)
        out = unified_diff_to_html(diff, args.title, wrap=args.wrap)
    else:
        out = make_difflib_html(args)
    if args.output:
        Path(args.output).write_text(out)
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
