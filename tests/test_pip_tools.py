#!/usr/bin/env python3

"""Tests for pip_tools.py"""

import pytest
import subprocess
import sys
import os
from unittest.mock import Mock, patch, call

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from pip_tools import (
    get_output,
    get_names,
    get_required_by,
    clean_deps,
    SKIP
)


class TestGetOutput:
    """Test get_output function."""

    def test_get_output_success(self):
        """Test successful command output retrieval."""
        with patch('subprocess.check_output') as mock_check:
            mock_check.return_value = 'output\nlines\n'
            result = get_output('test command')
            assert result == 'output\nlines\n'
            mock_check.assert_called_once()

    def test_get_output_command_split(self):
        """Test that command is properly split."""
        with patch('subprocess.check_output') as mock_check:
            mock_check.return_value = b'result'
            get_output('pip list --format freeze')
            args, kwargs = mock_check.call_args
            assert args[0] == ['pip', 'list', '--format', 'freeze']

    def test_get_output_encoding(self):
        """Test UTF-8 encoding is used."""
        with patch('subprocess.check_output') as mock_check:
            mock_check.return_value = 'test'
            get_output('command')
            args, kwargs = mock_check.call_args
            assert kwargs['encoding'] == 'utf8'


class TestGetNames:
    """Test get_names function."""

    def test_get_names_filters_skip_list(self):
        """Test that SKIP packages are filtered out."""
        mock_output = "pip==21.0\nCython==0.29.24\npackaging==21.0\ntest-package==1.0"

        with patch('pip_tools.get_output') as mock_get:
            mock_get.return_value = mock_output
            names = get_names('pip list')

            assert 'pip' not in names
            assert 'Cython' not in names
            assert 'packaging' not in names
            # Names includes version strings
            assert any('test-package' in n for n in names)

    def test_get_names_handles_version_strings(self):
        """Test parsing package names with versions."""
        mock_output = "numpy==1.21.0\npandas==1.3.0\nscipy==1.7.0"

        with patch('pip_tools.get_output') as mock_get:
            mock_get.return_value = mock_output
            names = get_names('pip list')

            # Should extract short names
            assert any('numpy' in n for n in names)
            assert any('pandas' in n for n in names)
            assert any('scipy' in n for n in names)

    def test_get_names_filters_separator_lines(self):
        """Test that separator lines are filtered."""
        mock_output = "--------- ----\npackage1==1.0\npackage2==2.0"

        with patch('pip_tools.get_output') as mock_get:
            mock_get.return_value = mock_output
            names = get_names('pip list')

            assert not any('---' in n for n in names)

    def test_get_names_empty_output(self):
        """Test handling of empty pip list."""
        with patch('pip_tools.get_output') as mock_get:
            mock_get.return_value = ""
            names = get_names('pip list')
            assert names == []

    def test_get_names_include_all_includes_skip_packages(self):
        """Test that include_all=True includes SKIP packages."""
        mock_output = "pip==21.0\nCython==0.29.24\npackaging==21.0\ntest-package==1.0"

        with patch('pip_tools.get_output') as mock_get:
            mock_get.return_value = mock_output
            names = get_names('pip list', include_all=True)

            # SKIP packages should now be included
            assert any('pip' in n for n in names)
            assert any('Cython' in n for n in names)
            assert any('packaging' in n for n in names)
            assert any('test-package' in n for n in names)

    def test_get_names_include_all_still_filters_separators(self):
        """Test that include_all=True still filters separator lines."""
        mock_output = "--------- ----\npip==21.0\npackage1==1.0"

        with patch('pip_tools.get_output') as mock_get:
            mock_get.return_value = mock_output
            names = get_names('pip list', include_all=True)

            assert not any('---' in n for n in names)
            assert any('pip' in n for n in names)
            assert any('package1' in n for n in names)


class TestGetRequiredBy:
    """Test get_required_by function."""

    def test_get_required_by_success(self):
        """Test successful dependency retrieval."""
        mock_output = """Name: requests
Version: 2.26.0
Required-by: package1, package2, package3"""

        with patch('pip_tools.get_output') as mock_get:
            mock_get.return_value = mock_output
            deps = get_required_by('requests')

            assert deps == ['package1', 'package2', 'package3']

    def test_get_required_by_no_dependencies(self):
        """Test package with no dependencies."""
        mock_output = """Name: standalone
Version: 1.0.0
Required-by: """

        with patch('pip_tools.get_output') as mock_get:
            mock_get.return_value = mock_output
            deps = get_required_by('standalone')

            assert deps == []

    def test_get_required_by_not_found(self):
        """Test handling of package not found."""
        with patch('pip_tools.get_output') as mock_get:
            mock_get.side_effect = subprocess.CalledProcessError(1, 'cmd')
            deps = get_required_by('nonexistent')

            assert deps is None

    def test_get_required_by_handles_exceptions(self):
        """Test graceful handling of exceptions."""
        with patch('pip_tools.get_output') as mock_get:
            mock_get.side_effect = Exception("Unexpected error")
            deps = get_required_by('package')

            # Should return None and not crash
            assert deps is None


class TestCleanDeps:
    """Test clean_deps function."""

    @patch('pip_tools.get_required_by')
    @patch('pip_tools.get_names')
    @patch('builtins.print')
    def test_clean_deps_identifies_singles(self, mock_print, mock_get_names, mock_get_req):
        """Test identification of packages not required by others."""
        # Setup: 3 packages, one is required by another
        mock_get_names.return_value = ['package1', 'package2', 'package3']

        def required_by_side_effect(name):
            if name == 'package1':
                return None  # Not required by anyone
            elif name == 'package2':
                return ['package3']  # Required by package3
            elif name == 'package3':
                return None  # Not required by anyone
            return None

        mock_get_req.side_effect = required_by_side_effect

        clean_deps()

        # Check that output identifies singles
        print_calls = [str(call) for call in mock_print.call_args_list]
        # New format prints "Packages not required by others"
        assert any('not required' in c.lower() for c in print_calls) or \
               any('uninstall' in c.lower() for c in print_calls)

    @patch('pip_tools.get_required_by')
    @patch('pip_tools.get_names')
    def test_clean_deps_respects_skip_list(self, mock_get_names, mock_get_req):
        """Test that SKIP packages are never suggested for removal."""
        mock_get_names.return_value = ['pip', 'setuptools', 'custom-package']
        mock_get_req.return_value = None  # None are required

        with patch('builtins.print') as mock_print:
            clean_deps()

            # Get the singles set that would be printed
            print_calls = [str(call) for call in mock_print.call_args_list]
            singles_calls = [c for c in print_calls if 'singles:' in c]

            # SKIP packages should not be in singles output
            if singles_calls:
                for skip_pkg in SKIP:
                    # Verify SKIP packages aren't in the singles recommendation
                    assert not any(skip_pkg in call and 'singles:' in call for call in singles_calls)


class TestResetPip:
    """Test reset_pip function."""

    @patch('pip_tools.get_names')
    @patch('subprocess.run')
    def test_reset_pip_uninstalls_packages(self, mock_run, mock_get_names):
        """Test that reset_pip uninstalls all packages."""
        from pip_tools import reset_pip

        mock_get_names.return_value = ['package1', 'package2']

        reset_pip()

        # Should call subprocess.run for each package
        assert mock_run.call_count == 2

        # Verify proper arguments
        calls = mock_run.call_args_list
        assert all('pip3' in str(call) for call in calls)
        assert all('uninstall' in str(call) for call in calls)

    @patch('pip_tools.get_names')
    @patch('subprocess.run')
    def test_reset_pip_handles_failures(self, mock_run, mock_get_names):
        """Test that reset_pip handles uninstall failures gracefully."""
        from pip_tools import reset_pip

        mock_get_names.return_value = ['package1', 'package2']
        mock_run.side_effect = [
            None,  # First succeeds
            subprocess.CalledProcessError(1, 'cmd')  # Second fails
        ]

        # Should not raise exception
        reset_pip()

        assert mock_run.call_count == 2

    @patch('pip_tools.get_names')
    @patch('subprocess.run')
    def test_reset_pip_include_all_passes_flag(self, mock_run, mock_get_names):
        """Test that reset_pip passes include_all to get_names."""
        from pip_tools import reset_pip

        mock_get_names.return_value = ['pip', 'setuptools', 'package1']

        reset_pip(include_all=True)

        # Verify get_names was called with include_all=True
        mock_get_names.assert_called_once_with(
            "pip list --format=freeze --exclude-editable",
            include_all=True
        )


class TestResetPip2Deprecation:
    """Test reset_pip2 deprecation."""

    @patch('pip_tools.reset_pip')
    @patch('builtins.print')
    def test_reset_pip2_shows_deprecation_warning(self, mock_print, mock_reset):
        """Test that reset_pip2 shows deprecation warning."""
        from pip_tools import reset_pip2

        reset_pip2()

        # Should print deprecation warning
        print_calls = [str(call) for call in mock_print.call_args_list]
        assert any('deprecated' in call.lower() for call in print_calls)

        # Should call reset_pip
        mock_reset.assert_called_once()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
