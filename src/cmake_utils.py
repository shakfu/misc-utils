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

    def __init__(self, name, url, branch=None, recursive_clone=False, 
                common_install=True, options=None):
        self.name = name
        self.url = url
        self.branch = branch or ""
        self.recursive_clone = recursive_clone
        self.common_install = common_install
        self.options = options or {}

    def cmd(self, shellcmd, cwd='.'):
        if isinstance(shellcmd, str):
            shellcmd = shellcmd.split()
        try:
            return subprocess.check_call(shellcmd, cwd=cwd)
        except subprocess.CalledProcessError as e:
            print(f"Error running command: {' '.join(shellcmd)}")
            print(f"Exit code: {e.returncode}")
            raise
        except FileNotFoundError as e:
            print(f"Command not found: {shellcmd[0]}")
            print("Please ensure required tools are installed (git, cmake)")
            raise

    def cmds(self, shellcmds, cwd='.'):
        assert isinstance(shellcmds, list), "shellcmds must a list"
        for shellcmd in shellcmds:
            self.cmd(shellcmd, cwd=cwd)

    def build(self):
        print("name:", self.name)
        print("url:", self.url)
        print("branch:", self.branch)
        print("recursive_clone:", self.recursive_clone)
        print("common_install:", self.common_install)
        print("options:", self.options)

        cmake_opts = " ".join(f"-D{k}={v}" for k,v in self.options.items())
        self.DEPS.mkdir(parents=True, exist_ok=True)
        src_dir = self.DEPS / 'src' / self.name
        build_dir = self.DEPS / 'build' / self.name
        if self.common_install:
            install_dir = self.DEPS
        else:
            install_dir = self.DEPS / 'install' / self.name
        if src_dir.exists():
            if build_dir.exists():
                shutil.rmtree(build_dir)
            if install_dir.exists() and not self.common_install:
                shutil.rmtree(install_dir)
        else:
            src_dir.mkdir(parents=True, exist_ok=True)
            recursive = "--recursive" if self.recursive_clone else ""
            if self.branch:
                self.cmd(f"git clone --depth=1 {recursive} --branch {self.branch} {self.url} {src_dir}")
            else:
                self.cmd(f"git clone --depth=1 {recursive} {self.url} {src_dir}")

        # build
        build_dir.mkdir(parents=True, exist_ok=True)
        self.cmd(f"cmake -S {src_dir} -B {build_dir} {cmake_opts}")
        self.cmd(f"cmake --build {build_dir}")
        self.cmd(f"cmake --install {build_dir} --prefix {install_dir}")
