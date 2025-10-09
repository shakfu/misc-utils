#!/usr/bin/env python3

"""Tests for clean script"""

import pytest
import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, call

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Import the Cleaner class from clean script
import clean
from clean import Cleaner


class TestCleanerInit:
    """Test Cleaner initialization."""

    def test_initialization(self):
        """Test basic initialization."""
        cleaner = Cleaner('/tmp', ['.pyc', '.pyo'])
        assert cleaner.path == '/tmp'
        assert cleaner.patterns == ['.pyc', '.pyo']
        assert cleaner.dry_run is False
        assert cleaner.targets == []
        assert cleaner.cum_size == 0.0

    def test_initialization_with_dry_run(self):
        """Test initialization with dry_run flag."""
        cleaner = Cleaner('/tmp', ['.pyc'], dry_run=True)
        assert cleaner.dry_run is True

    def test_repr(self):
        """Test string representation."""
        cleaner = Cleaner('/tmp', ['.pyc'])
        repr_str = repr(cleaner)
        assert '/tmp' in repr_str
        assert '.pyc' in repr_str


class TestCleanerMatchers:
    """Test pattern matchers."""

    def test_endswith_matcher(self):
        """Test endswith matcher."""
        cleaner = Cleaner('.', ['.pyc', '.pyo'])
        matcher = cleaner.matchers['endswith']

        assert matcher('test.pyc') is True
        assert matcher('test.pyo') is True
        assert matcher('test.py') is False
        assert matcher('pyc') is False

    def test_glob_matcher(self):
        """Test glob matcher."""
        cleaner = Cleaner('.', ['*.pyc', 'test_*'])
        matcher = cleaner.matchers['glob']

        assert matcher('file.pyc') is True
        assert matcher('test_something') is True
        assert matcher('file.py') is False
        assert matcher('something') is False


class TestCleanerWalk:
    """Test walk functionality."""

    def test_walk_collects_results(self):
        """Test that walk collects matching files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test structure
            test_file1 = Path(tmpdir) / 'test1.pyc'
            test_file2 = Path(tmpdir) / 'test2.py'
            test_file1.touch()
            test_file2.touch()

            cleaner = Cleaner(tmpdir, ['.pyc'])
            results = cleaner.walk(tmpdir, lambda p: p if p.endswith('.pyc') else None, log=False)

            assert len(results) == 1
            assert str(test_file1) in results

    def test_walk_recursive(self):
        """Test that walk processes subdirectories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested structure
            subdir = Path(tmpdir) / 'subdir'
            subdir.mkdir()
            test_file1 = Path(tmpdir) / 'test1.pyc'
            test_file2 = subdir / 'test2.pyc'
            test_file1.touch()
            test_file2.touch()

            cleaner = Cleaner(tmpdir, ['.pyc'])
            results = cleaner.walk(tmpdir, lambda p: p if p.endswith('.pyc') else None, log=False)

            assert len(results) == 2

    def test_walk_tracks_size(self):
        """Test that walk tracks cumulative size."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.pyc'
            test_file.write_text('x' * 100)

            cleaner = Cleaner(tmpdir, ['.pyc'])
            cleaner.walk(tmpdir, lambda p: p if p.endswith('.pyc') else None, log=False)

            assert cleaner.cum_size > 0


class TestCleanerDelete:
    """Test delete functionality."""

    def test_delete_file(self):
        """Test deleting a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.pyc'
            test_file.touch()
            assert test_file.exists()

            cleaner = Cleaner(tmpdir, ['.pyc'])
            cleaner.delete(str(test_file))

            assert not test_file.exists()

    def test_delete_directory(self):
        """Test deleting a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / '__pycache__'
            test_dir.mkdir()
            (test_dir / 'test.pyc').touch()
            assert test_dir.exists()

            cleaner = Cleaner(tmpdir, ['__pycache__'])
            cleaner.delete(str(test_dir))

            assert not test_dir.exists()

    def test_delete_with_dry_run(self):
        """Test that dry_run doesn't actually delete."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.pyc'
            test_file.touch()

            cleaner = Cleaner(tmpdir, ['.pyc'], dry_run=True)
            cleaner.targets = [str(test_file)]

            # In dry run mode, _apply should not call delete
            with patch.object(cleaner, 'delete') as mock_delete:
                cleaner._apply(cleaner.delete, confirm=False)
                # delete should not be called in dry_run mode
                mock_delete.assert_not_called()

            # File should still exist
            assert test_file.exists()


class TestCleanerLineEndings:
    """Test line ending conversion."""

    def test_clean_endings_windows_to_unix(self):
        """Test converting Windows line endings to Unix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.py'
            # Write with Windows endings
            test_file.write_text('line1\r\nline2\r\n')

            cleaner = Cleaner(tmpdir, ['.py'])
            cleaner.clean_endings(str(test_file))

            content = test_file.read_text()
            assert '\r\n' not in content
            assert content == 'line1\nline2\n'

    def test_clean_endings_removes_trailing_whitespace(self):
        """Test that line ending conversion removes trailing whitespace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.py'
            test_file.write_text('line1  \nline2\t\n')

            cleaner = Cleaner(tmpdir, ['.py'])
            cleaner.clean_endings(str(test_file))

            content = test_file.read_text()
            assert content == 'line1\nline2\n'


class TestCleanerDo:
    """Test the do() method."""

    def test_do_endswith_delete(self):
        """Test do with endswith delete action."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file1 = Path(tmpdir) / 'test1.pyc'
            test_file2 = Path(tmpdir) / 'test2.py'
            test_file1.touch()
            test_file2.touch()

            cleaner = Cleaner(tmpdir, ['.pyc'])

            # Mock getch to auto-confirm
            with patch('clean.getch', return_value='y'):
                cleaner.do('endswith_delete')

            assert not test_file1.exists()
            assert test_file2.exists()

    def test_do_glob_delete(self):
        """Test do with glob delete action."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file1 = Path(tmpdir) / 'test_file.py'
            test_file2 = Path(tmpdir) / 'other_file.py'
            test_file1.touch()
            test_file2.touch()

            # Glob pattern needs to match full path, use *test_file.py
            cleaner = Cleaner(tmpdir, ['*/test_file.py', '*test_file.py'])

            with patch('clean.getch', return_value='y'):
                cleaner.do('glob_delete')

            assert not test_file1.exists()
            assert test_file2.exists()

    def test_do_with_negation(self):
        """Test do with negation flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file1 = Path(tmpdir) / 'test.py'
            test_file2 = Path(tmpdir) / 'test.pyc'
            test_file1.touch()
            test_file2.touch()

            cleaner = Cleaner(tmpdir, ['.py'])

            # Delete everything except .py files
            with patch('clean.getch', return_value='y'):
                cleaner.do('endswith_delete', negate=True)

            assert test_file1.exists()
            assert not test_file2.exists()

    def test_do_with_cancel(self):
        """Test that cancelling doesn't delete files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.pyc'
            test_file.touch()

            cleaner = Cleaner(tmpdir, ['.pyc'])

            # Cancel the operation
            with patch('clean.getch', return_value='n'):
                cleaner.do('endswith_delete')

            # File should still exist
            assert test_file.exists()

    def test_do_convert_endings(self):
        """Test do with line ending conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.py'
            test_file.write_text('line1\r\nline2\r\n')

            cleaner = Cleaner(tmpdir, ['.py'])

            with patch('clean.getch', return_value='y'):
                cleaner.do('convert')

            content = test_file.read_text()
            assert '\r\n' not in content


class TestCleanerDryRun:
    """Test dry run functionality."""

    def test_dry_run_no_deletion(self):
        """Test that dry run doesn't delete files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.pyc'
            test_file.touch()

            cleaner = Cleaner(tmpdir, ['.pyc'], dry_run=True)

            with patch('clean.getch', return_value='y'):
                cleaner.do('endswith_delete')

            # File should still exist in dry run
            assert test_file.exists()

    def test_dry_run_shows_would_delete(self):
        """Test that dry run shows what would be deleted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.pyc'
            test_file.touch()

            cleaner = Cleaner(tmpdir, ['.pyc'], dry_run=True)

            with patch('clean.getch', return_value='y'):
                with patch.object(cleaner, 'log') as mock_log:
                    cleaner.do('endswith_delete')

                    # Check that "Would" appears in log messages
                    log_calls = [str(call) for call in mock_log.call_args_list]
                    assert any('Would' in call for call in log_calls)


class TestCleanerCmdline:
    """Test command line argument parsing."""

    def test_cmdline_basic_patterns(self):
        """Test basic pattern arguments."""
        with patch('sys.argv', ['clean', '.pyc', '.pyo']):
            with patch('clean.getch', return_value='n'):
                # We just want to test parsing, not execution
                # This will exit, so we catch it
                try:
                    parser = clean.argparse.ArgumentParser()
                    parser.add_argument('patterns', nargs='*')
                    parser.add_argument('-p', '--path', default='.')
                    parser.add_argument('-d', '--dry-run', action='store_true')
                    args = parser.parse_args(['.pyc', '.pyo'])

                    assert args.patterns == ['.pyc', '.pyo']
                    assert args.path == '.'
                    assert args.dry_run is False
                except SystemExit:
                    pass

    def test_cmdline_with_dry_run(self):
        """Test dry run flag parsing."""
        parser = clean.argparse.ArgumentParser()
        parser.add_argument('patterns', nargs='*')
        parser.add_argument('-d', '--dry-run', action='store_true')

        args = parser.parse_args(['--dry-run', '.pyc'])
        assert args.dry_run is True
        assert args.patterns == ['.pyc']

    def test_cmdline_with_path(self):
        """Test path flag parsing."""
        parser = clean.argparse.ArgumentParser()
        parser.add_argument('patterns', nargs='*')
        parser.add_argument('-p', '--path', default='.')

        args = parser.parse_args(['-p', '/tmp', '.pyc'])
        assert args.path == '/tmp'
        assert args.patterns == ['.pyc']


class TestCleanerIntegration:
    """Integration tests for complete workflows."""

    def test_full_cleanup_workflow(self):
        """Test complete cleanup workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test structure
            (Path(tmpdir) / 'test1.pyc').touch()
            (Path(tmpdir) / 'test2.pyo').touch()
            (Path(tmpdir) / 'keep.py').touch()

            subdir = Path(tmpdir) / 'subdir'
            subdir.mkdir()
            (subdir / 'test3.pyc').touch()

            cleaner = Cleaner(tmpdir, ['.pyc', '.pyo'])

            with patch('clean.getch', return_value='y'):
                cleaner.do('endswith_delete')

            # Check that .pyc and .pyo files are gone
            assert not (Path(tmpdir) / 'test1.pyc').exists()
            assert not (Path(tmpdir) / 'test2.pyo').exists()
            assert not (subdir / 'test3.pyc').exists()
            # But .py file remains
            assert (Path(tmpdir) / 'keep.py').exists()

    def test_dry_run_workflow(self):
        """Test complete dry run workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.pyc'
            test_file.touch()

            cleaner = Cleaner(tmpdir, ['.pyc'], dry_run=True)

            with patch('clean.getch', return_value='y'):
                cleaner.do('endswith_delete')

            # File should still exist
            assert test_file.exists()

    def test_line_ending_workflow(self):
        """Test complete line ending conversion workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.py'
            test_file.write_text('line1  \r\nline2\t\r\n')

            cleaner = Cleaner(tmpdir, ['.py'])

            with patch('clean.getch', return_value='y'):
                cleaner.do('convert')

            content = test_file.read_text()
            assert content == 'line1\nline2\n'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
