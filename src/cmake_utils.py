#!/usr/bin/env python3

import shutil
import subprocess
from pathlib import Path


class DepBuilder:
    """Front-end to build cmake depedencies in the `build` directory

    Can be used as follows:

    DepBuilder(
        name='libsndfile',
        url='https://github.com/libsndfile/libsndfile.git',
        options=dict(
            ENABLE_EXTERNAL_LIBS=True,
            ENABLE_MPEG=False,
            BUILD_PROGRAMS=False,
            BUILD_TESTING=False,
            BUILD_SHARED_LIBS=False,
        ),
    ).build()

    """
    ROOT = Path.cwd()
    BUILD = ROOT / 'build'
    DEPS = BUILD / 'deps'

    def __init__(self, name, url, branch=None, options=None, common_install=False):
        self.name = name
        self.url = url
        self.branch = branch
        self.options = options or {}
        self.common_install = common_install

    def cmd(self, shellcmd, cwd='.'):
        if isinstance(shellcmd, str):
            shellcmd = shellcmd.split()
        return subprocess.check_call(shellcmd, cwd=cwd)

    def cmds(self, shellcmds, cwd='.'):
        assert isinstance(shellcmds, list), "shellcmds must a list"
        for shellcmd in shellcmds:
            self.cmd(shellcmd, cwd=cwd)

    def build(self):
        print("name:", self.name)
        print("url:", self.url)
        print("branch:", self.branch)
        print("options:", self.options)

        cmake_opts = " ".join(f"-D{k}={v}" for k,v in self.options.items())
        self.DEPS.mkdir(parents=True, exist_ok=True)
        src_dir = self.DEPS / f"{self.name}-src"
        build_dir = self.DEPS / f"{self.name}-build"
        if self.common_install:
            install_dir = self.DEPS
        else:
            install_dir = self.DEPS / f"{self.name}-install"
        if src_dir.exists():
            for folder in [build_dir, install_dir]:
                if folder.exists():
                    shutil.rmtree(folder)
        else:
            src_dir.mkdir(parents=True, exist_ok=True)
            if self.branch:
                self.cmd(f"git clone --depth=1 --branch {self.branch} {self.url} {src_dir}")
            else:
                self.cmd(f"git clone --depth=1 {self.url} {src_dir}")

        # build
        build_dir.mkdir(parents=True, exist_ok=True)
        self.cmd(f"cmake -S {src_dir} -B {build_dir} {cmake_opts}")
        self.cmd(f"cmake --build {build_dir}")
        self.cmd(f"cmake --install {build_dir} --prefix {install_dir}")


