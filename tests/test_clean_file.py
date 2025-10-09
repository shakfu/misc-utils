#!/usr/bin/env python3

"""Tests for clean_file.py"""

import pytest
import tempfile
import sys
import os
from pathlib import Path

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from clean_file import FileCleaner


class TestFileCleaner:
    """Test FileCleaner class functionality."""

    def test_remove_trailing_whitespace(self):
        """Test removal of trailing whitespace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.py'
            test_file.write_text('line1   \nline2\t\t\nline3\n')

            cleaner = FileCleaner(test_file, remove_emojis=False, dry_run=False)
            cleaner.remove_trailing_whitespace()

            content = test_file.read_text()
            assert content == 'line1\nline2\nline3\n'
            assert cleaner.n_lines_cleaned == 2

    def test_remove_trailing_whitespace_preserves_empty_lines(self):
        """Test that empty lines are preserved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.py'
            test_file.write_text('line1\n\nline3\n')

            cleaner = FileCleaner(test_file, remove_emojis=False, dry_run=False)
            cleaner.remove_trailing_whitespace()

            content = test_file.read_text()
            assert content == 'line1\n\nline3\n'

    def test_dry_run_whitespace(self):
        """Test dry-run mode doesn't modify files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.py'
            original_content = 'line1   \nline2\n'
            test_file.write_text(original_content)

            cleaner = FileCleaner(test_file, remove_emojis=False, dry_run=True)
            cleaner.remove_trailing_whitespace()

            content = test_file.read_text()
            assert content == original_content

    def test_remove_emojis(self):
        """Test emoji removal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.py'
            # Use actual emoji characters (these might render as boxes in some editors)
            test_file.write_text('Hello 😀 World 😊\nTest\n')

            cleaner = FileCleaner(test_file, remove_emojis=True, dry_run=False)
            cleaner.remove_emojis()

            content = test_file.read_text()
            assert '😀' not in content
            assert '😊' not in content
            assert 'Hello' in content
            assert 'World' in content
            assert cleaner.n_emojis_removed == 2

    def test_remove_emojis_preserves_text(self):
        """Test emoji removal preserves regular text."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.py'
            test_file.write_text('print("Hello World")\n')

            cleaner = FileCleaner(test_file, remove_emojis=True, dry_run=False)
            cleaner.remove_emojis()

            content = test_file.read_text()
            assert 'print("Hello World")' in content

    def test_remove_emojis_flag_controls_execution(self):
        """Test that remove_emojis flag controls whether emoji removal runs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.py'
            original_content = 'Test 😀 content\n'
            test_file.write_text(original_content)

            # With flag = False, emojis should not be removed
            cleaner = FileCleaner(test_file, remove_emojis=False, dry_run=False)
            cleaner.clean()

            content = test_file.read_text()
            # Emoji should still be there when flag is False
            assert '😀' in content

            # With flag = True, emoji removal should run
            test_file.write_text('Test 😊 content\n')
            cleaner = FileCleaner(test_file, remove_emojis=True, dry_run=False)
            cleaner.clean()

            content = test_file.read_text()
            assert '😊' not in content
            assert 'Test' in content
            assert 'content' in content

    def test_can_clean_valid_extensions(self):
        """Test file extension filtering."""
        with tempfile.TemporaryDirectory() as tmpdir:
            py_file = Path(tmpdir) / 'test.py'
            py_file.touch()
            cleaner = FileCleaner(py_file)
            assert cleaner.can_clean() is True

            js_file = Path(tmpdir) / 'test.js'
            js_file.touch()
            cleaner = FileCleaner(js_file)
            assert cleaner.can_clean() is True

            txt_file = Path(tmpdir) / 'test.txt'
            txt_file.touch()
            cleaner = FileCleaner(txt_file)
            assert cleaner.can_clean() is False

    def test_can_clean_skips_hidden_files(self):
        """Test that hidden files are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hidden_file = Path(tmpdir) / '.hidden.py'
            hidden_file.touch()
            cleaner = FileCleaner(hidden_file)
            assert cleaner.can_clean() is False

    def test_can_clean_skips_build_directories(self):
        """Test that build directories are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            build_dir = Path(tmpdir) / 'build'
            build_dir.mkdir()
            test_file = build_dir / 'test.py'
            test_file.touch()
            cleaner = FileCleaner(test_file)
            assert cleaner.can_clean() is False

            pycache_dir = Path(tmpdir) / '__pycache__'
            pycache_dir.mkdir()
            test_file = pycache_dir / 'test.py'
            test_file.touch()
            cleaner = FileCleaner(test_file)
            assert cleaner.can_clean() is False

    def test_clean_integration(self):
        """Test full cleaning workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.py'
            test_file.write_text('line1   \nline2\t\nHello 😀\n')

            cleaner = FileCleaner(test_file, remove_emojis=True, dry_run=False)
            cleaner.clean()

            content = test_file.read_text()
            # Whitespace should be removed
            lines = content.split('\n')
            assert lines[0] == 'line1'
            assert lines[1] == 'line2'
            # Emojis should be removed
            assert '😀' not in content
            assert 'Hello' in content

    def test_invalid_file_path(self):
        """Test handling of invalid file paths."""
        cleaner = FileCleaner('/nonexistent/path/file.py')
        assert cleaner.can_clean() is False

    def test_java_extension_fixed(self):
        """Test that .java extension is recognized (was a typo)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            java_file = Path(tmpdir) / 'Test.java'
            java_file.touch()
            cleaner = FileCleaner(java_file)
            assert cleaner.can_clean() is True
            assert '.java' in FileCleaner.VALID_EXTENSIONS

    def test_no_changes_needed(self):
        """Test when file has no trailing whitespace or emojis."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.py'
            test_file.write_text('line1\nline2\nline3\n')

            cleaner = FileCleaner(test_file, remove_emojis=True, dry_run=False)
            cleaner.remove_trailing_whitespace()

            # n_lines_cleaned should be 0
            assert cleaner.n_lines_cleaned == 0

    def test_mixed_line_endings(self):
        """Test handling of mixed line endings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.py'
            # Windows style line endings with trailing spaces
            test_file.write_text('line1  \r\nline2\t\r\nline3\n', newline='')

            cleaner = FileCleaner(test_file, remove_emojis=False, dry_run=False)
            cleaner.remove_trailing_whitespace()

            content = test_file.read_text()
            # Trailing whitespace should be removed, line endings preserved
            lines = content.splitlines(keepends=True)
            assert all(not line[:-1].endswith((' ', '\t')) if len(line) > 1 else True for line in lines)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
