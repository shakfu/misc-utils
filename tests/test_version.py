#!/usr/bin/env python3

"""Tests for version.py"""

from unittest.mock import MagicMock, patch

import version as version_mod


class TestParseAndBump:
    def test_parse_version(self):
        assert version_mod.parse_version("1.2.3") == (1, 2, 3)

    def test_bump_patch(self):
        assert version_mod.bump_version("1.2.3", "patch") == "1.2.4"

    def test_bump_minor(self):
        assert version_mod.bump_version("1.2.3", "minor") == "1.3.0"

    def test_bump_major(self):
        assert version_mod.bump_version("1.2.3", "major") == "2.0.0"


class TestVersionFileHelpers:
    def test_get_and_update_versions(self, tmp_path):
        init = tmp_path / "src" / "buylog" / "__init__.py"
        init.parent.mkdir(parents=True)
        init.write_text('__version__ = "0.1.0"\n')

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nversion = "0.1.0"\n')

        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("## [Unreleased]\n\n## [0.1.0]\n")

        with patch.object(version_mod, "INIT_FILE", init), \
             patch.object(version_mod, "PYPROJECT_FILE", pyproject), \
             patch.object(version_mod, "CHANGELOG_FILE", changelog):
            assert version_mod.get_init_version() == "0.1.0"
            assert version_mod.get_pyproject_version() == "0.1.0"
            assert version_mod.get_changelog_version() == "0.1.0"

            consistent, versions = version_mod.check_consistency()
            assert consistent
            assert versions["init"] == "0.1.0"

            version_mod.update_init_version("0.1.1")
            version_mod.update_pyproject_version("0.1.1")
            version_mod.update_changelog_version("0.1.0", "0.1.1")

            assert version_mod.get_init_version() == "0.1.1"
            assert version_mod.get_pyproject_version() == "0.1.1"
            assert "## [0.1.1]" in changelog.read_text()

    def test_inconsistent_versions(self, tmp_path):
        init = tmp_path / "src" / "buylog" / "__init__.py"
        init.parent.mkdir(parents=True)
        init.write_text('__version__ = "0.1.0"\n')
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('version = "0.2.0"\n')
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("## [0.1.0]\n")

        with patch.object(version_mod, "INIT_FILE", init), \
             patch.object(version_mod, "PYPROJECT_FILE", pyproject), \
             patch.object(version_mod, "CHANGELOG_FILE", changelog):
            consistent, versions = version_mod.check_consistency()
            assert not consistent
            assert versions["init"] == "0.1.0"
            assert versions["pyproject"] == "0.2.0"


class TestGitTagHelpers:
    def test_check_tag_exists(self):
        result = MagicMock(stdout="v1.0.0\n")
        with patch.object(version_mod, "run_git_command", return_value=result):
            assert version_mod.check_tag_exists("1.0.0") is True

    def test_check_tag_missing(self):
        result = MagicMock(stdout="")
        with patch.object(version_mod, "run_git_command", return_value=result):
            assert version_mod.check_tag_exists("1.0.0") is False

    def test_create_git_tag_success(self):
        result = MagicMock(returncode=0, stderr="")
        with patch.object(version_mod, "run_git_command", return_value=result):
            assert version_mod.create_git_tag("1.2.3") is True

    def test_push_git_tag_failure(self):
        result = MagicMock(returncode=1, stderr="denied")
        with patch.object(version_mod, "run_git_command", return_value=result):
            assert version_mod.push_git_tag("1.2.3") is False


class TestVersionMain:
    def _patch_files(self, tmp_path, ver="0.1.0"):
        init = tmp_path / "src" / "buylog" / "__init__.py"
        init.parent.mkdir(parents=True)
        init.write_text(f'__version__ = "{ver}"\n')
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(f'version = "{ver}"\n')
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text(f"## [Unreleased]\n\n## [{ver}]\n")
        return init, pyproject, changelog

    def test_main_status(self, tmp_path, capsys):
        init, pyproject, changelog = self._patch_files(tmp_path)
        with patch.object(version_mod, "INIT_FILE", init), \
             patch.object(version_mod, "PYPROJECT_FILE", pyproject), \
             patch.object(version_mod, "CHANGELOG_FILE", changelog), \
             patch.object(version_mod, "check_tag_exists", return_value=False), \
             patch("sys.argv", ["version.py"]):
            assert version_mod.main() == 0
        out = capsys.readouterr().out
        assert "Current version: 0.1.0" in out
        assert "does not exist" in out

    def test_main_inconsistent(self, tmp_path):
        init, pyproject, changelog = self._patch_files(tmp_path)
        pyproject.write_text('version = "9.9.9"\n')
        with patch.object(version_mod, "INIT_FILE", init), \
             patch.object(version_mod, "PYPROJECT_FILE", pyproject), \
             patch.object(version_mod, "CHANGELOG_FILE", changelog), \
             patch("sys.argv", ["version.py"]):
            assert version_mod.main() == 1

    def test_main_bump(self, tmp_path):
        init, pyproject, changelog = self._patch_files(tmp_path)
        with patch.object(version_mod, "INIT_FILE", init), \
             patch.object(version_mod, "PYPROJECT_FILE", pyproject), \
             patch.object(version_mod, "CHANGELOG_FILE", changelog), \
             patch("sys.argv", ["version.py", "bump", "patch"]), \
             patch("builtins.input", return_value="y"):
            assert version_mod.main() == 0
        assert '__version__ = "0.1.1"' in init.read_text()
        assert 'version = "0.1.1"' in pyproject.read_text()
        assert "## [0.1.1]" in changelog.read_text()

    def test_main_bump_abort(self, tmp_path):
        init, pyproject, changelog = self._patch_files(tmp_path)
        with patch.object(version_mod, "INIT_FILE", init), \
             patch.object(version_mod, "PYPROJECT_FILE", pyproject), \
             patch.object(version_mod, "CHANGELOG_FILE", changelog), \
             patch("sys.argv", ["version.py", "bump"]), \
             patch("builtins.input", return_value="n"):
            assert version_mod.main() == 0
        assert '__version__ = "0.1.0"' in init.read_text()

    def test_main_unknown_command(self, tmp_path):
        init, pyproject, changelog = self._patch_files(tmp_path)
        with patch.object(version_mod, "INIT_FILE", init), \
             patch.object(version_mod, "PYPROJECT_FILE", pyproject), \
             patch.object(version_mod, "CHANGELOG_FILE", changelog), \
             patch("sys.argv", ["version.py", "nope"]):
            assert version_mod.main() == 1
