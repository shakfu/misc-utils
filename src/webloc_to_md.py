#!/usr/bin/env python3

import os
import plistlib
from pathlib import Path


def get_link(root: str, webloc: str):
	root = Path(root)
	webloc = root / webloc
	name = webloc.stem
	with open(webloc, 'rb') as f:
		url = plistlib.load(f).get("URL")
	mdlink = f"- [{name}]({url})"
	return mdlink

def gen_md(root, title="Research Links"):
	md = [f"# {title}"]
	for root, folders, files in os.walk('.'):
		print(root)
		md.append("") # empty line
		md.append(f"## {root.lstrip('./')}")
		for f in files:
			if f.endswith('.webloc'):
				link = get_link(root, f)
				md.append("")
				md.append(link)

	with open("_RESEARCH.md", "w") as f:
		f.write("\n".join(md))

gen_md(".")
