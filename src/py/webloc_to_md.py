#!/usr/bin/env python3

"""Collect the .webloc files under a directory into a markdown link list."""

import argparse
import os
import plistlib
from pathlib import Path
from typing import Sequence

DEFAULT_OUTPUT = "_RESEARCH.md"


def get_link(root: str, webloc: str) -> str:
	"""Render one .webloc file as a markdown list item."""
	path = Path(root) / webloc
	name = path.stem
	with open(path, 'rb') as f:
		url = plistlib.load(f).get("URL")
	mdlink = f"- [{name}]({url})"
	return mdlink


def gen_md(
	root: str,
	title: str = "Research Links",
	output: str | os.PathLike[str] = DEFAULT_OUTPUT,
) -> str:
	"""Walk *root*, write its links to *output* and return the markdown.

	Each directory becomes a heading named relative to *root*, so the output
	does not leak the absolute path the scan started from.
	"""
	base = Path(root)
	label = base.resolve().name or str(base)
	md = [f"# {title}"]
	for dirpath, _folders, files in os.walk(root):
		print(dirpath)
		relative = Path(dirpath).relative_to(base)
		md.append("")  # empty line
		md.append(f"## {label if relative == Path('.') else relative}")
		for name in sorted(files):
			if name.endswith('.webloc'):
				link = get_link(dirpath, name)
				md.append("")
				md.append(link)

	text = "\n".join(md)
	Path(output).write_text(text)
	return text


def main(argv: Sequence[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		"root", nargs="?", default=".", help="directory to scan (default: .)"
	)
	parser.add_argument(
		"-t", "--title", default="Research Links", help="title of the H1 heading"
	)
	parser.add_argument(
		"-o", "--output", default=DEFAULT_OUTPUT,
		help=f"file to write (default: {DEFAULT_OUTPUT})",
	)
	args = parser.parse_args(argv)
	if not os.path.isdir(args.root):
		parser.error(f"no such directory: {args.root}")
	gen_md(args.root, title=args.title, output=args.output)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
