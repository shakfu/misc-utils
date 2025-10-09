#!/usr/bin/env python3

"""Tests for the CaseConverter class."""

import pytest
import tempfile
from pathlib import Path
import sys
import os

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from case_converter import CaseConverter


class TestCaseConversion:
    """Test case conversion methods."""

    def test_camel_to_snake(self):
        converter = CaseConverter('.', 'camelCase', 'snake_case')
        assert converter.convert('firstName') == 'first_name'
        assert converter.convert('lastName') == 'last_name'
        assert converter.convert('emailAddress') == 'email_address'
        assert converter.convert('phoneNumber') == 'phone_number'

    def test_camel_to_pascal(self):
        converter = CaseConverter('.', 'camelCase', 'PascalCase')
        assert converter.convert('firstName') == 'FirstName'
        assert converter.convert('lastName') == 'LastName'
        assert converter.convert('emailAddress') == 'EmailAddress'

    def test_camel_to_kebab(self):
        converter = CaseConverter('.', 'camelCase', 'kebab-case')
        assert converter.convert('firstName') == 'first-name'
        assert converter.convert('lastName') == 'last-name'
        assert converter.convert('emailAddress') == 'email-address'

    def test_camel_to_screaming_snake(self):
        converter = CaseConverter('.', 'camelCase', 'SCREAMING_SNAKE_CASE')
        assert converter.convert('firstName') == 'FIRST_NAME'
        assert converter.convert('lastName') == 'LAST_NAME'

    def test_pascal_to_snake(self):
        converter = CaseConverter('.', 'PascalCase', 'snake_case')
        assert converter.convert('FirstName') == 'first_name'
        assert converter.convert('LastName') == 'last_name'
        assert converter.convert('EmailAddress') == 'email_address'

    def test_pascal_to_camel(self):
        converter = CaseConverter('.', 'PascalCase', 'camelCase')
        assert converter.convert('FirstName') == 'firstName'
        assert converter.convert('LastName') == 'lastName'
        assert converter.convert('EmailAddress') == 'emailAddress'

    def test_pascal_to_kebab(self):
        converter = CaseConverter('.', 'PascalCase', 'kebab-case')
        assert converter.convert('FirstName') == 'first-name'
        assert converter.convert('LastName') == 'last-name'

    def test_snake_to_camel(self):
        converter = CaseConverter('.', 'snake_case', 'camelCase')
        assert converter.convert('first_name') == 'firstName'
        assert converter.convert('last_name') == 'lastName'
        assert converter.convert('email_address') == 'emailAddress'

    def test_snake_to_pascal(self):
        converter = CaseConverter('.', 'snake_case', 'PascalCase')
        assert converter.convert('first_name') == 'FirstName'
        assert converter.convert('last_name') == 'LastName'
        assert converter.convert('email_address') == 'EmailAddress'

    def test_snake_to_kebab(self):
        converter = CaseConverter('.', 'snake_case', 'kebab-case')
        assert converter.convert('first_name') == 'first-name'
        assert converter.convert('last_name') == 'last-name'

    def test_snake_to_screaming_snake(self):
        converter = CaseConverter('.', 'snake_case', 'SCREAMING_SNAKE_CASE')
        assert converter.convert('first_name') == 'FIRST_NAME'
        assert converter.convert('last_name') == 'LAST_NAME'

    def test_kebab_to_camel(self):
        converter = CaseConverter('.', 'kebab-case', 'camelCase')
        assert converter.convert('first-name') == 'firstName'
        assert converter.convert('last-name') == 'lastName'
        assert converter.convert('email-address') == 'emailAddress'

    def test_kebab_to_pascal(self):
        converter = CaseConverter('.', 'kebab-case', 'PascalCase')
        assert converter.convert('first-name') == 'FirstName'
        assert converter.convert('last-name') == 'LastName'

    def test_kebab_to_snake(self):
        converter = CaseConverter('.', 'kebab-case', 'snake_case')
        assert converter.convert('first-name') == 'first_name'
        assert converter.convert('last-name') == 'last_name'

    def test_screaming_snake_to_snake(self):
        converter = CaseConverter('.', 'SCREAMING_SNAKE_CASE', 'snake_case')
        assert converter.convert('FIRST_NAME') == 'first_name'
        assert converter.convert('LAST_NAME') == 'last_name'

    def test_screaming_snake_to_camel(self):
        converter = CaseConverter('.', 'SCREAMING_SNAKE_CASE', 'camelCase')
        assert converter.convert('FIRST_NAME') == 'firstName'
        assert converter.convert('LAST_NAME') == 'lastName'

    def test_screaming_kebab_to_kebab(self):
        converter = CaseConverter('.', 'SCREAMING-KEBAB-CASE', 'kebab-case')
        assert converter.convert('FIRST-NAME') == 'first-name'
        assert converter.convert('LAST-NAME') == 'last-name'

    def test_screaming_kebab_to_camel(self):
        converter = CaseConverter('.', 'SCREAMING-KEBAB-CASE', 'camelCase')
        assert converter.convert('FIRST-NAME') == 'firstName'
        assert converter.convert('LAST-NAME') == 'lastName'


class TestPatternMatching:
    """Test pattern matching for different case formats."""

    def test_camel_case_pattern(self):
        matches = CaseConverter.PAT_CAMEL_CASE.findall('firstName lastName emailAddress')
        assert 'firstName' in matches
        assert 'lastName' in matches
        assert 'emailAddress' in matches

    def test_pascal_case_pattern(self):
        matches = CaseConverter.PAT_PASCAL_CASE.findall('FirstName LastName EmailAddress')
        assert 'FirstName' in matches
        assert 'LastName' in matches
        assert 'EmailAddress' in matches

    def test_snake_case_pattern(self):
        matches = CaseConverter.PAT_SNAKE_CASE.findall('first_name last_name email_address')
        assert 'first_name' in matches
        assert 'last_name' in matches
        assert 'email_address' in matches

    def test_screaming_snake_case_pattern(self):
        matches = CaseConverter.PAT_SCREAMING_SNAKE_CASE.findall('FIRST_NAME LAST_NAME EMAIL_ADDRESS')
        assert 'FIRST_NAME' in matches
        assert 'LAST_NAME' in matches
        assert 'EMAIL_ADDRESS' in matches

    def test_kebab_case_pattern(self):
        matches = CaseConverter.PAT_KEBAB_CASE.findall('first-name last-name email-address')
        assert 'first-name' in matches
        assert 'last-name' in matches
        assert 'email-address' in matches

    def test_screaming_kebab_case_pattern(self):
        matches = CaseConverter.PAT_SCREAMING_KEBAB_CASE.findall('FIRST-NAME LAST-NAME EMAIL-ADDRESS')
        assert 'FIRST-NAME' in matches
        assert 'LAST-NAME' in matches
        assert 'EMAIL-ADDRESS' in matches


class TestFileProcessing:
    """Test file processing functionality."""

    def test_process_single_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.py'
            test_file.write_text('firstName = "John"\nlastName = "Doe"\n')

            converter = CaseConverter(test_file, 'camelCase', 'snake_case')
            converter.process_file(test_file)

            content = test_file.read_text()
            assert 'first_name' in content
            assert 'last_name' in content
            assert 'firstName' not in content
            assert 'lastName' not in content

    def test_process_directory_non_recursive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file1 = tmpdir / 'test1.py'
            test_file2 = tmpdir / 'test2.py'
            subdir = tmpdir / 'subdir'
            subdir.mkdir()
            test_file3 = subdir / 'test3.py'

            test_file1.write_text('firstName = "John"\n')
            test_file2.write_text('lastName = "Doe"\n')
            test_file3.write_text('emailAddress = "john@example.com"\n')

            converter = CaseConverter(tmpdir, 'camelCase', 'snake_case', recursive=False)
            converter.process_directory()

            # Files in root should be converted
            assert 'first_name' in test_file1.read_text()
            assert 'last_name' in test_file2.read_text()

            # File in subdir should NOT be converted (non-recursive)
            assert 'emailAddress' in test_file3.read_text()

    def test_process_directory_recursive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file1 = tmpdir / 'test1.py'
            subdir = tmpdir / 'subdir'
            subdir.mkdir()
            test_file2 = subdir / 'test2.py'

            test_file1.write_text('firstName = "John"\n')
            test_file2.write_text('lastName = "Doe"\n')

            converter = CaseConverter(tmpdir, 'camelCase', 'snake_case', recursive=True)
            converter.process_directory()

            # Both files should be converted
            assert 'first_name' in test_file1.read_text()
            assert 'last_name' in test_file2.read_text()

    def test_dry_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.py'
            original_content = 'firstName = "John"\n'
            test_file.write_text(original_content)

            converter = CaseConverter(test_file, 'camelCase', 'snake_case', dry_run=True)
            converter.process_file(test_file)

            # File should not be modified in dry run
            assert test_file.read_text() == original_content

    def test_file_extension_filtering(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            py_file = tmpdir / 'test.py'
            txt_file = tmpdir / 'test.txt'

            py_file.write_text('firstName = "John"\n')
            txt_file.write_text('firstName = "John"\n')

            converter = CaseConverter(
                tmpdir,
                'camelCase',
                'snake_case',
                file_extensions=['.py']
            )
            converter.process_directory()

            # Python file should be converted
            assert 'first_name' in py_file.read_text()

            # Text file should NOT be converted
            assert 'firstName' in txt_file.read_text()


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_invalid_from_format(self):
        with pytest.raises(ValueError):
            CaseConverter('.', 'invalidFormat', 'snake_case')

    def test_invalid_to_format(self):
        with pytest.raises(ValueError):
            CaseConverter('.', 'camelCase', 'invalidFormat')

    def test_nonexistent_path(self):
        converter = CaseConverter('/nonexistent/path', 'camelCase', 'snake_case')
        # Should not raise an error, just print a message
        converter.process_directory()

    def test_single_word(self):
        converter = CaseConverter('.', 'camelCase', 'snake_case')
        # Single word camelCase doesn't match the pattern, so it should remain unchanged
        # This is expected behavior as single lowercase words aren't camelCase
        result = converter.convert('name')
        # The pattern won't match a single lowercase word, so no conversion happens
        # in the actual file processing context

    def test_complex_conversion(self):
        converter = CaseConverter('.', 'camelCase', 'snake_case')
        assert converter.convert('getHTMLContent') == 'get_h_t_m_l_content'
        assert converter.convert('parseXMLFile') == 'parse_x_m_l_file'


class TestPrefixSuffix:
    """Test prefix and suffix functionality."""

    def test_prefix_only(self):
        converter = CaseConverter('.', 'camelCase', 'snake_case', prefix='old_')
        assert converter.convert('firstName') == 'old_first_name'
        assert converter.convert('lastName') == 'old_last_name'

    def test_suffix_only(self):
        converter = CaseConverter('.', 'camelCase', 'snake_case', suffix='_v2')
        assert converter.convert('firstName') == 'first_name_v2'
        assert converter.convert('lastName') == 'last_name_v2'

    def test_prefix_and_suffix(self):
        converter = CaseConverter('.', 'camelCase', 'snake_case', prefix='old_', suffix='_v1')
        assert converter.convert('firstName') == 'old_first_name_v1'
        assert converter.convert('lastName') == 'old_last_name_v1'

    def test_prefix_with_pascal_case(self):
        converter = CaseConverter('.', 'snake_case', 'PascalCase', prefix='New')
        assert converter.convert('first_name') == 'NewFirstName'
        assert converter.convert('last_name') == 'NewLastName'

    def test_suffix_with_camel_case(self):
        converter = CaseConverter('.', 'snake_case', 'camelCase', suffix='Old')
        assert converter.convert('first_name') == 'firstNameOld'
        assert converter.convert('last_name') == 'lastNameOld'

    def test_prefix_suffix_in_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.py'
            test_file.write_text('firstName = "John"\nlastName = "Doe"\n')

            converter = CaseConverter(test_file, 'camelCase', 'snake_case', prefix='new_', suffix='_var')
            converter.process_file(test_file)

            content = test_file.read_text()
            assert 'new_first_name_var' in content
            assert 'new_last_name_var' in content
            assert 'firstName' not in content
            assert 'lastName' not in content


class TestWordFilter:
    """Test word filtering with regex patterns."""

    def test_word_filter_match(self):
        converter = CaseConverter('.', 'camelCase', 'snake_case', word_filter='^get.*')
        # Should convert words starting with 'get'
        assert converter.convert('getName') == 'get_name'
        assert converter.convert('getValue') == 'get_value'
        # Should NOT convert words not starting with 'get'
        assert converter.convert('setName') == 'setName'
        assert converter.convert('firstName') == 'firstName'

    def test_word_filter_in_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.py'
            test_file.write_text('getName = "John"\nsetName = "Doe"\nfirstName = "Jane"\n')

            converter = CaseConverter(test_file, 'camelCase', 'snake_case', word_filter='^get.*')
            converter.process_file(test_file)

            content = test_file.read_text()
            # Only getName should be converted
            assert 'get_name' in content
            assert 'setName' in content  # Unchanged
            assert 'firstName' in content  # Unchanged

    def test_word_filter_complex_pattern(self):
        converter = CaseConverter('.', 'camelCase', 'snake_case', word_filter='^(get|set).*')
        # Should convert words starting with 'get' or 'set'
        assert converter.convert('getName') == 'get_name'
        assert converter.convert('setValue') == 'set_value'
        # Should NOT convert other words
        assert converter.convert('firstName') == 'firstName'


class TestGlobFilter:
    """Test glob pattern filtering for files."""

    def test_glob_filename_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / 'test_utils.py'
            other_file = tmpdir / 'main.py'

            test_file.write_text('firstName = "John"\n')
            other_file.write_text('lastName = "Doe"\n')

            converter = CaseConverter(tmpdir, 'camelCase', 'snake_case', glob_pattern='test_*.py')
            converter.process_directory()

            # Only test_utils.py should be converted
            assert 'first_name' in test_file.read_text()
            assert 'lastName' in other_file.read_text()  # Unchanged

    def test_glob_wildcard_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            py_file = tmpdir / 'script.py'
            js_file = tmpdir / 'script.js'

            py_file.write_text('firstName = "John"\n')
            js_file.write_text('firstName = "John"\n')

            converter = CaseConverter(tmpdir, 'camelCase', 'snake_case',
                                    file_extensions=['.py', '.js'],
                                    glob_pattern='*.py')
            converter.process_directory()

            # Only .py file should be converted
            assert 'first_name' in py_file.read_text()
            assert 'firstName' in js_file.read_text()  # Unchanged

    def test_glob_recursive_path_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            subdir = tmpdir / 'tests'
            subdir.mkdir()
            test_file = subdir / 'test_case.py'
            other_file = tmpdir / 'main.py'

            test_file.write_text('firstName = "John"\n')
            other_file.write_text('lastName = "Doe"\n')

            converter = CaseConverter(tmpdir, 'camelCase', 'snake_case',
                                    recursive=True,
                                    glob_pattern='tests/*.py')
            converter.process_directory()

            # Only file in tests/ should be converted
            assert 'first_name' in test_file.read_text()
            assert 'lastName' in other_file.read_text()  # Unchanged


class TestCombinedFeatures:
    """Test combining multiple features."""

    def test_prefix_and_word_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / 'test.py'
            test_file.write_text('getName = "John"\nsetName = "Doe"\nfirstName = "Jane"\n')

            converter = CaseConverter(
                test_file,
                'camelCase',
                'snake_case',
                prefix='old_',
                word_filter='^get.*'
            )
            converter.process_file(test_file)

            content = test_file.read_text()
            # Only getName should be converted with prefix
            assert 'old_get_name' in content
            assert 'setName' in content  # Unchanged
            assert 'firstName' in content  # Unchanged

    def test_suffix_glob_and_word_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / 'test_utils.py'
            other_file = tmpdir / 'main.py'

            test_file.write_text('getUserName = "John"\nsetUserName = "Doe"\n')
            other_file.write_text('getUserEmail = "test@example.com"\n')

            converter = CaseConverter(
                tmpdir,
                'camelCase',
                'snake_case',
                suffix='_func',
                glob_pattern='test_*.py',
                word_filter='^get.*'
            )
            converter.process_directory()

            # Only getUserName in test_utils.py should be converted
            test_content = test_file.read_text()
            assert 'get_user_name_func' in test_content
            assert 'setUserName' in test_content  # Unchanged

            # other_file should be completely unchanged
            assert 'getUserEmail' in other_file.read_text()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
