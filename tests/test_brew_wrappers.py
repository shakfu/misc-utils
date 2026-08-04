#!/usr/bin/env python3

"""Tests for brew_to_csv.py and dump_brew_pkgs.py wrappers."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import runpy


ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / "src" / "py"


class TestBrewToCsv:
    """Test brew_to_csv.py entry point."""

    def test_main_calls_dump_to_csv(self):
        with patch("brew_tools.dump_to_csv") as mock_dump:
            runpy.run_path(str(PY / "brew_to_csv.py"), run_name="__main__")
            mock_dump.assert_called_once_with("names.csv")


class TestDumpBrewPkgs:
    """Test dump_brew_pkgs.py entry point."""

    def test_prefers_yaml_when_available(self):
        with patch("brew_tools.dump_to_yaml") as mock_yaml, \
             patch("brew_tools.dump_to_json") as mock_json, \
             patch.dict("sys.modules", {"yaml": MagicMock()}):
            runpy.run_path(str(PY / "dump_brew_pkgs.py"), run_name="__main__")
            mock_yaml.assert_called_once_with("pkgs.yml")
            mock_json.assert_not_called()

    def test_falls_back_to_json_without_yaml(self):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("no yaml")
            return real_import(name, *args, **kwargs)

        with patch("brew_tools.dump_to_yaml") as mock_yaml, \
             patch("brew_tools.dump_to_json") as mock_json, \
             patch("builtins.__import__", side_effect=fake_import):
            runpy.run_path(str(PY / "dump_brew_pkgs.py"), run_name="__main__")
            mock_json.assert_called_once_with("pkgs.json")
            mock_yaml.assert_not_called()
