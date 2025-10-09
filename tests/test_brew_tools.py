#!/usr/bin/env python3

"""Tests for brew_tools.py"""

import pytest
import sys
import os
import json
from unittest.mock import Mock, patch, call, mock_open
from pathlib import Path

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from brew_tools import (
    shell_output,
    get_pkg_names,
    get_pkg_desc,
    get_pkg_info,
    get_all_pkg_info,
    get_detailed_pkgs,
    get_installed_json,
    dump_to_csv,
    dump_to_json,
    dump_to_yaml
)


class TestShellOutput:
    """Test shell_output function."""

    def test_shell_output_basic(self):
        """Test basic shell output."""
        with patch('subprocess.check_output') as mock_check:
            mock_check.return_value = 'line1\nline2\nline3\n'  # Already decoded by encoding='utf8'
            result = shell_output('test command')
            assert result == ['line1', 'line2', 'line3']

    def test_shell_output_filters_empty_lines(self):
        """Test that empty lines are filtered."""
        with patch('subprocess.check_output') as mock_check:
            mock_check.return_value = 'line1\n\nline2\n\n'  # Already decoded by encoding='utf8'
            result = shell_output('test command')
            assert result == ['line1', 'line2']


class TestGetPkgNames:
    """Test get_pkg_names function."""

    def test_get_pkg_names(self):
        """Test getting package names."""
        with patch('brew_tools.shell_output') as mock_shell:
            mock_shell.return_value = ['pkg1', 'pkg2', 'pkg3']
            result = get_pkg_names()
            assert result == ['pkg1', 'pkg2', 'pkg3']
            mock_shell.assert_called_once_with('brew list')


class TestGetPkgDesc:
    """Test get_pkg_desc function."""

    def test_get_pkg_desc_success(self):
        """Test successful package description retrieval."""
        with patch('subprocess.check_output') as mock_check:
            mock_check.return_value = 'line0\nPackage description\nline2'
            result = get_pkg_desc('test-pkg')
            assert result == 'Package description'

    def test_get_pkg_desc_error(self):
        """Test error handling."""
        with patch('subprocess.check_output') as mock_check:
            mock_check.side_effect = Exception("Error")
            result = get_pkg_desc('test-pkg')
            assert result == ""


class TestGetPkgInfo:
    """Test get_pkg_info function."""

    def test_get_pkg_info_success(self):
        """Test successful package info retrieval."""
        mock_json = json.dumps([{
            'name': 'test-pkg',
            'desc': 'Test description',
            'dependencies': ['dep1', 'dep2'],
            'build_dependencies': []
        }])

        with patch('subprocess.check_output') as mock_check:
            mock_check.return_value = mock_json
            result = get_pkg_info('test-pkg')

            assert result.name == 'test-pkg'
            assert result.desc == 'Test description'
            assert result.dependencies == ['dep1', 'dep2']

    def test_get_pkg_info_error(self):
        """Test error handling."""
        with patch('subprocess.check_output') as mock_check:
            mock_check.side_effect = Exception("Error")
            result = get_pkg_info('test-pkg')
            assert result is None


class TestGetInstalledJson:
    """Test get_installed_json function."""

    def test_get_installed_json_success(self):
        """Test successful JSON retrieval."""
        mock_data = [
            {'name': 'pkg1', 'versions': {'stable': '1.0'}},
            {'name': 'pkg2', 'versions': {'stable': '2.0'}}
        ]

        with patch('subprocess.check_output') as mock_check:
            mock_check.return_value = json.dumps(mock_data)
            result = get_installed_json()
            assert len(result) == 2
            assert result[0]['name'] == 'pkg1'

    @patch('builtins.print')
    def test_get_installed_json_error(self, mock_print):
        """Test error handling."""
        with patch('subprocess.check_output') as mock_check:
            from subprocess import CalledProcessError
            mock_check.side_effect = CalledProcessError(1, 'brew')
            result = get_installed_json()
            assert result == []


class TestDumpToCsv:
    """Test dump_to_csv function."""

    @patch('brew_tools.get_installed_json')
    @patch('builtins.open', new_callable=mock_open)
    def test_dump_to_csv(self, mock_file, mock_get_json):
        """Test CSV export."""
        mock_get_json.return_value = [
            {
                'name': 'pkg1',
                'versions': {'stable': '1.0'},
                'desc': 'Package 1'
            },
            {
                'name': 'pkg2',
                'versions': {'stable': '2.0'},
                'desc': 'Package 2'
            }
        ]

        dump_to_csv('test.csv')

        # Verify file was opened for writing
        mock_file.assert_called_once_with('test.csv', 'w', newline='')


class TestDumpToJson:
    """Test dump_to_json function."""

    @patch('brew_tools.get_detailed_pkgs')
    @patch('builtins.open', new_callable=mock_open)
    def test_dump_to_json(self, mock_file, mock_get_pkgs):
        """Test JSON export."""
        mock_get_pkgs.return_value = {
            'pkg1': {'desc': 'Package 1', 'deps': [], 'build_deps': []},
            'pkg2': {'desc': 'Package 2', 'deps': ['dep1'], 'build_deps': []}
        }

        dump_to_json('test.json')

        # Verify file was opened for writing
        mock_file.assert_called_once_with('test.json', 'w')


class TestDumpToYaml:
    """Test dump_to_yaml function."""

    @patch('brew_tools.get_detailed_pkgs')
    @patch('builtins.open', new_callable=mock_open)
    def test_dump_to_yaml_with_yaml_installed(self, mock_file, mock_get_pkgs):
        """Test YAML export when yaml is available."""
        mock_get_pkgs.return_value = {
            'pkg1': {'desc': 'Package 1', 'deps': [], 'build_deps': []}
        }

        # Mock yaml module and its dump function
        mock_yaml = Mock()
        mock_yaml.dump = Mock()

        with patch.dict('sys.modules', {'yaml': mock_yaml}):
            # Need to reload the function to pick up the mock
            dump_to_yaml('test.yml')

            # Verify file was opened for writing
            mock_file.assert_called_once_with('test.yml', 'w')

    @patch('brew_tools.dump_to_json')
    def test_dump_to_yaml_without_yaml(self, mock_dump_json):
        """Test YAML export falls back to JSON when yaml not available."""
        # Remove yaml from modules if it exists
        with patch.dict('sys.modules', {'yaml': None}):
            with patch('builtins.__import__', side_effect=ImportError):
                dump_to_yaml('test.yml')
                # Should fall back to JSON
                mock_dump_json.assert_called_once()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
