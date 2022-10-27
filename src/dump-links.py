#!/usr/bin/env python3 

import os
import webloc

tmpl = """\
<html>
<head>
</head>
<body>
<h1>Links</h1>
<ul>
{links}
</ul>
</body>
"""


def dump(path: str):
    _links = []
    for i in os.listdir(path):
        p = os.path.join(path, i)
        url = webloc.read(p)
        txt = i[:-7]
        _link = f'<li><a href="{url}">{txt}</a></li>\n'
        _links.append(_link)
    links = "\n".join(_links)
    with open('links.html', 'w') as f:
        f.write(tmpl.format(links=links))

