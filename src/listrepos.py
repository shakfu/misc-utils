#!/usr/bin/env python3

import dbm
import os
from pathlib import Path

from typing import Optional


class GitRepoDB:
    DB_PATH = Path(__file__).parent / 'urls.db'
    SRC_DIR = Path('~/src').expanduser()

    def __init__(self, src_dir: Optional[str | Path] = None, db_path: Optional[str | Path] = None):
        self.src_dir = Path(src_dir) if src_dir else self.SRC_DIR
        self.db_path = Path(db_path) if db_path else self.DB_PATH

    @property
    def urls(self) -> list[str]:
        with dbm.open(self.db_path) as db:
            return sorted(url.decode() for url in db.values())
    @property
    def projects(self) -> list[str]:
        with dbm.open(self.db_path) as db:
            return sorted(name.decode() for name in db.keys())

    def collect(self):
        self.store_from_dir(self.SRC_DIR)

    def store_from_dir(self, directory: str | Path) -> None:
        _urls = self.get_from_dir(directory)
        self.store(_urls)

    def store_from_string(self, urlstr: str) -> None:
        _urls = [Path(p) for p in urlstr.splitlines()]
        self.store(_urls)

    def get_from_dir(self, directory: str | Path) -> list[Path]:
        src_dir = Path(directory)
        src_urls = set()
        for p in src_dir.iterdir():
            if p.is_dir():
                try:
                    cfg = p / '.git' / 'config'
                    assert cfg.is_file()
                    with open(cfg) as f:
                        lines = f.readlines()
                        lines = [line.strip() for line in lines]
                        for line in lines:
                            if line.startswith('url') and line.endswith('.git'):
                                url = line.lstrip('url = ')
                                src_urls.add(Path(url))
                except AssertionError:
                    pass
        return sorted(src_urls)

    def store(self, urls: list[Path]) -> None:
        with dbm.open(self.db_path, 'c') as db:
            for url in urls:
                if url.stem in db:
                    print('skipping:', url.stem)
                    continue
                print('storing:', url.stem)
                db[url.stem] = str(url)

    def dump(self, to_path: str = 'urls.txt'):
        with open(to_path, 'w') as f:
            f.write("\n".join(self.urls))


if __name__ == '__main__':
    db = GitRepoDB()
    db.collect()

