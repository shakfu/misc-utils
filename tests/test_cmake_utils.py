#!/usr/bin/env python3

"""Tests for cmake_utils.py"""

import pytest
import subprocess
import sys
import os
from pathlib import Path
from unittest.mock import Mock, patch, call

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from cmake_utils import DepBuilder


class TestDepBuilder:
    """Test DepBuilder class functionality."""

    def test_initialization(self):
        """Test DepBuilder initialization."""
        builder = DepBuilder(
            name='test-lib',
            url='https://github.com/test/test-lib.git',
            branch='main',
            recursive_clone=True,
            common_install=False,
            options={'ENABLE_TESTING': False}
        )

        assert builder.name == 'test-lib'
        assert builder.url == 'https://github.com/test/test-lib.git'
        assert builder.branch == 'main'
        assert builder.recursive_clone is True
        assert builder.common_install is False
        assert builder.options == {'ENABLE_TESTING': False}

    def test_initialization_defaults(self):
        """Test DepBuilder with default values."""
        builder = DepBuilder(
            name='test-lib',
            url='https://github.com/test/test-lib.git'
        )

        assert builder.branch == ""
        assert builder.recursive_clone is False
        assert builder.common_install is True
        assert builder.options == {}

    def test_cmd_string_split(self):
        """Test cmd() splits string commands correctly."""
        builder = DepBuilder('test', 'url')

        with patch('subprocess.check_call') as mock_check_call:
            builder.cmd('git clone repo')
            mock_check_call.assert_called_once_with(['git', 'clone', 'repo'], cwd='.')

    def test_cmd_list_passthrough(self):
        """Test cmd() passes list commands through."""
        builder = DepBuilder('test', 'url')

        with patch('subprocess.check_call') as mock_check_call:
            builder.cmd(['git', 'clone', 'repo'])
            mock_check_call.assert_called_once_with(['git', 'clone', 'repo'], cwd='.')

    def test_cmd_custom_cwd(self):
        """Test cmd() respects custom working directory."""
        builder = DepBuilder('test', 'url')

        with patch('subprocess.check_call') as mock_check_call:
            builder.cmd('ls', cwd='/tmp')
            mock_check_call.assert_called_once_with(['ls'], cwd='/tmp')

    def test_cmd_handles_called_process_error(self):
        """Test cmd() handles subprocess errors."""
        builder = DepBuilder('test', 'url')

        with patch('subprocess.check_call') as mock_check_call:
            mock_check_call.side_effect = subprocess.CalledProcessError(1, 'cmd')

            with pytest.raises(subprocess.CalledProcessError):
                builder.cmd('failing-command')

    def test_cmd_handles_file_not_found_error(self):
        """Test cmd() handles missing command errors."""
        builder = DepBuilder('test', 'url')

        with patch('subprocess.check_call') as mock_check_call:
            mock_check_call.side_effect = FileNotFoundError()

            with pytest.raises(FileNotFoundError):
                builder.cmd('nonexistent-command')

    def test_cmds_multiple_commands(self):
        """Test cmds() executes multiple commands."""
        builder = DepBuilder('test', 'url')

        with patch('subprocess.check_call') as mock_check_call:
            builder.cmds(['git status', 'git pull'], cwd='/tmp')

            assert mock_check_call.call_count == 2
            assert mock_check_call.call_args_list == [
                call(['git', 'status'], cwd='/tmp'),
                call(['git', 'pull'], cwd='/tmp')
            ]

    def test_cmds_requires_list(self):
        """Test cmds() requires list input."""
        builder = DepBuilder('test', 'url')

        with pytest.raises(AssertionError):
            builder.cmds('not-a-list')

    @patch('cmake_utils.DepBuilder.cmd')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.mkdir')
    @patch('shutil.rmtree')
    def test_build_new_dependency(self, mock_rmtree, mock_mkdir, mock_exists, mock_cmd):
        """Test building a new dependency from scratch."""
        # Setup: src_dir doesn't exist
        mock_exists.return_value = False

        builder = DepBuilder(
            name='libtest',
            url='https://github.com/test/libtest.git',
            options={'BUILD_TESTING': False}
        )

        builder.build()

        # Should clone, build, and install
        assert mock_cmd.call_count == 4

        # Verify git clone was called
        git_clone_call = [c for c in mock_cmd.call_args_list if 'git clone' in str(c)]
        assert len(git_clone_call) == 1

        # Verify cmake commands were called
        cmake_calls = [c for c in mock_cmd.call_args_list if 'cmake' in str(c)]
        assert len(cmake_calls) == 3  # configure, build, install

    @patch('cmake_utils.DepBuilder.cmd')
    @patch('pathlib.Path.exists')
    @patch('shutil.rmtree')
    def test_build_existing_dependency(self, mock_rmtree, mock_exists, mock_cmd):
        """Test rebuilding an existing dependency."""
        # Setup: src_dir exists, build_dir exists
        mock_exists.return_value = True

        builder = DepBuilder(
            name='libtest',
            url='https://github.com/test/libtest.git'
        )

        builder.build()

        # Should remove build dir and rebuild
        assert mock_rmtree.called

        # Should not clone (src already exists)
        git_clone_call = [c for c in mock_cmd.call_args_list if 'git clone' in str(c)]
        assert len(git_clone_call) == 0

    @patch('cmake_utils.DepBuilder.cmd')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.mkdir')
    def test_build_with_branch(self, mock_mkdir, mock_exists, mock_cmd):
        """Test building with specific branch."""
        mock_exists.return_value = False

        builder = DepBuilder(
            name='libtest',
            url='https://github.com/test/libtest.git',
            branch='develop'
        )

        builder.build()

        # Check that branch was included in git clone
        git_clone_calls = [str(c) for c in mock_cmd.call_args_list if 'git clone' in str(c)]
        assert any('--branch develop' in call for call in git_clone_calls)

    @patch('cmake_utils.DepBuilder.cmd')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.mkdir')
    def test_build_recursive_clone(self, mock_mkdir, mock_exists, mock_cmd):
        """Test building with recursive submodule clone."""
        mock_exists.return_value = False

        builder = DepBuilder(
            name='libtest',
            url='https://github.com/test/libtest.git',
            recursive_clone=True
        )

        builder.build()

        # Check that --recursive was included in git clone
        git_clone_calls = [str(c) for c in mock_cmd.call_args_list if 'git clone' in str(c)]
        assert any('--recursive' in call for call in git_clone_calls)

    @patch('cmake_utils.DepBuilder.cmd')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.mkdir')
    def test_build_with_cmake_options(self, mock_mkdir, mock_exists, mock_cmd):
        """Test building with CMake options."""
        mock_exists.return_value = False

        builder = DepBuilder(
            name='libtest',
            url='https://github.com/test/libtest.git',
            options={
                'BUILD_TESTING': False,
                'BUILD_SHARED_LIBS': True,
                'CMAKE_BUILD_TYPE': 'Release'
            }
        )

        builder.build()

        # Check that cmake options were passed
        cmake_config_calls = [str(c) for c in mock_cmd.call_args_list if 'cmake -S' in str(c)]
        assert len(cmake_config_calls) == 1

        cmake_call = cmake_config_calls[0]
        assert 'BUILD_TESTING=False' in cmake_call
        assert 'BUILD_SHARED_LIBS=True' in cmake_call
        assert 'CMAKE_BUILD_TYPE=Release' in cmake_call


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
