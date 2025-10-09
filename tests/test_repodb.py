#!/usr/bin/env python3

"""Tests for repodb.py"""

import pytest
import sys
import os
import tempfile
import dbm
from pathlib import Path
from unittest.mock import Mock, patch, call

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from repodb import GitRepoDB, list_repos


class TestGitRepoDBInit:
    """Test GitRepoDB initialization."""

    def test_initialization_defaults(self):
        """Test initialization with default values."""
        db = GitRepoDB()
        assert db.src_dir == Path('~/src').expanduser()
        assert str(db.db_path).endswith('urls.db')

    def test_initialization_custom_paths(self):
        """Test initialization with custom paths."""
        db = GitRepoDB(src_dir='/custom/src', db_path='/custom/db.db')
        assert db.src_dir == Path('/custom/src')
        assert db.db_path == Path('/custom/db.db')


class TestGitRepoDBProperties:
    """Test GitRepoDB properties."""

    def test_urls_property(self):
        """Test urls property."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / 'test.db'
            db = GitRepoDB(db_path=db_path)

            # Store some test URLs
            with dbm.open(str(db_path), 'c') as dbm_db:
                dbm_db['repo1'] = 'https://github.com/user/repo1.git'
                dbm_db['repo2'] = 'https://github.com/user/repo2.git'

            urls = db.urls
            assert len(urls) == 2
            assert 'https://github.com/user/repo1.git' in urls
            assert 'https://github.com/user/repo2.git' in urls

    def test_urls_property_empty_db(self):
        """Test urls property with non-existent database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / 'nonexistent.db'
            db = GitRepoDB(db_path=db_path)

            # Should return empty list gracefully
            urls = db.urls
            assert urls == []

    def test_projects_property(self):
        """Test projects property."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / 'test.db'
            db = GitRepoDB(db_path=db_path)

            # Store some test projects
            with dbm.open(str(db_path), 'c') as dbm_db:
                dbm_db['repo1'] = 'https://github.com/user/repo1.git'
                dbm_db['repo2'] = 'https://github.com/user/repo2.git'

            projects = db.projects
            assert len(projects) == 2
            assert 'repo1' in projects
            assert 'repo2' in projects

    def test_projects_property_empty_db(self):
        """Test projects property with non-existent database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / 'nonexistent.db'
            db = GitRepoDB(db_path=db_path)

            # Should return empty list gracefully
            projects = db.projects
            assert projects == []


class TestGitRepoDBGetFromDir:
    """Test get_from_dir method."""

    def test_get_from_dir_with_git_repos(self):
        """Test getting URLs from directory with git repos."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir)

            # Create mock git repo directories
            repo1 = src_dir / 'repo1'
            repo2 = src_dir / 'repo2'
            repo1.mkdir()
            repo2.mkdir()
            (repo1 / '.git').mkdir()
            (repo2 / '.git').mkdir()

            db = GitRepoDB(src_dir=src_dir)

            # Mock subprocess to return URLs
            with patch('subprocess.run') as mock_run:
                def side_effect(*args, **kwargs):
                    cmd = args[0] if args else []
                    cmd_str = ' '.join(cmd)
                    if 'repo1' in cmd_str:
                        return Mock(stdout='https://github.com/user/repo1.git\n', returncode=0)
                    elif 'repo2' in cmd_str:
                        return Mock(stdout='https://github.com/user/repo2.git\n', returncode=0)
                    # If no match, raise error (no remote configured)
                    from subprocess import CalledProcessError
                    raise CalledProcessError(1, cmd)

                mock_run.side_effect = side_effect

                urls = db.get_from_dir(src_dir)

                assert len(urls) == 2
                assert Path('https://github.com/user/repo1.git') in urls
                assert Path('https://github.com/user/repo2.git') in urls

    def test_get_from_dir_handles_non_git_dirs(self):
        """Test that non-git directories are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir)

            # Create regular directory (no .git)
            regular_dir = src_dir / 'regular'
            regular_dir.mkdir()

            db = GitRepoDB(src_dir=src_dir)
            urls = db.get_from_dir(src_dir)

            assert len(urls) == 0

    def test_get_from_dir_handles_errors(self):
        """Test error handling for repositories without remotes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir)

            # Create git repo directory
            repo = src_dir / 'repo'
            repo.mkdir()
            (repo / '.git').mkdir()

            db = GitRepoDB(src_dir=src_dir)

            # Mock subprocess to raise error (no remote configured)
            with patch('subprocess.run') as mock_run:
                mock_run.side_effect = Exception("No remote")

                # Should handle error gracefully
                urls = db.get_from_dir(src_dir)
                assert len(urls) == 0


class TestGitRepoDBStore:
    """Test store method."""

    def test_store_urls(self):
        """Test storing URLs in database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / 'test.db'
            db = GitRepoDB(db_path=db_path)

            urls = [
                Path('https://github.com/user/repo1.git'),
                Path('https://github.com/user/repo2.git')
            ]

            db.store(urls)

            # Verify URLs were stored
            with dbm.open(str(db_path), 'r') as dbm_db:
                assert b'repo1' in dbm_db
                assert b'repo2' in dbm_db

    def test_store_skips_existing(self):
        """Test that existing entries are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / 'test.db'
            db = GitRepoDB(db_path=db_path)

            # Store initial URL
            urls = [Path('https://github.com/user/repo1.git')]
            db.store(urls)

            # Try to store same URL again
            with patch('builtins.print') as mock_print:
                db.store(urls)
                # Should print "skipping"
                calls = [str(call) for call in mock_print.call_args_list]
                assert any('skipping' in call.lower() for call in calls)


class TestGitRepoDBDump:
    """Test dump method."""

    def test_dump_to_file(self):
        """Test dumping URLs to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / 'test.db'
            output_path = Path(tmpdir) / 'urls.txt'
            db = GitRepoDB(db_path=db_path)

            # Store some URLs
            with dbm.open(str(db_path), 'c') as dbm_db:
                dbm_db['repo1'] = 'https://github.com/user/repo1.git'
                dbm_db['repo2'] = 'https://github.com/user/repo2.git'

            db.dump(str(output_path))

            # Verify file contents
            content = output_path.read_text()
            assert 'https://github.com/user/repo1.git' in content
            assert 'https://github.com/user/repo2.git' in content


class TestGitRepoDBCollect:
    """Test collect method."""

    @patch.object(GitRepoDB, 'store_from_dir')
    def test_collect(self, mock_store):
        """Test collect method."""
        db = GitRepoDB()
        db.collect()

        # Should call store_from_dir with SRC_DIR
        mock_store.assert_called_once()


class TestGitRepoDBStoreFromDir:
    """Test store_from_dir method."""

    @patch.object(GitRepoDB, 'get_from_dir')
    @patch.object(GitRepoDB, 'store')
    def test_store_from_dir(self, mock_store, mock_get):
        """Test store_from_dir method."""
        mock_get.return_value = [
            Path('https://github.com/user/repo1.git'),
            Path('https://github.com/user/repo2.git')
        ]

        db = GitRepoDB()
        db.store_from_dir('/test/dir')

        mock_get.assert_called_once_with('/test/dir')
        mock_store.assert_called_once()


class TestGitRepoDBStoreFromString:
    """Test store_from_string method."""

    @patch.object(GitRepoDB, 'store')
    def test_store_from_string(self, mock_store):
        """Test store_from_string method."""
        db = GitRepoDB()

        urlstr = """https://github.com/user/repo1.git
https://github.com/user/repo2.git"""

        db.store_from_string(urlstr)

        mock_store.assert_called_once()
        stored_urls = mock_store.call_args[0][0]
        assert len(stored_urls) == 2


class TestListRepos:
    """Test list_repos function."""

    @patch.object(GitRepoDB, 'projects', new_callable=lambda: property(lambda self: ['repo1', 'repo2']))
    def test_list_repos_with_projects(self, mock_projects):
        """Test list_repos with existing projects."""
        with patch('builtins.print') as mock_print:
            # Create a temporary db to avoid exit
            with tempfile.TemporaryDirectory() as tmpdir:
                db_path = Path(tmpdir) / 'test.db'
                with dbm.open(str(db_path), 'c') as db:
                    db['repo1'] = 'url1'
                    db['repo2'] = 'url2'

                # Patch GitRepoDB to use our test db
                with patch('repodb.GitRepoDB') as MockDB:
                    mock_db = Mock()
                    mock_db.projects = ['repo1', 'repo2']
                    MockDB.return_value = mock_db

                    list_repos()

                    # Should print each project
                    assert mock_print.call_count == 2

    def test_list_repos_empty_db(self):
        """Test list_repos with no projects."""
        with patch('repodb.GitRepoDB') as MockDB:
            mock_db = Mock()
            mock_db.projects = []
            MockDB.return_value = mock_db

            with pytest.raises(SystemExit) as exc_info:
                list_repos()

            assert exc_info.value.code == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
