#!/usr/bin/env python3

"""Tests for rpkg.py"""

from unittest.mock import patch

import rpkg


class TestRpkgMain:
    def test_install_invokes_rscript(self):
        with patch("rpkg.subprocess.run") as mock_run, \
             patch("sys.argv", ["rpkg.py", "install", "dplyr", "ggplot2"]):
            rpkg.main()
            assert mock_run.called
            cmd = mock_run.call_args[0][0]
            assert "Rscript -e" in cmd
            assert "install.packages" in cmd
            assert "dplyr" in cmd
            assert "ggplot2" in cmd
            assert rpkg.REPO in cmd

    def test_update_invokes_rscript(self):
        with patch("rpkg.subprocess.run") as mock_run, \
             patch("sys.argv", ["rpkg.py", "update"]):
            rpkg.main()
            cmd = mock_run.call_args[0][0]
            assert "update.packages" in cmd
            assert rpkg.REPO in cmd

    def test_remove_invokes_rscript(self):
        with patch("rpkg.subprocess.run") as mock_run, \
             patch("sys.argv", ["rpkg.py", "remove", "dplyr"]):
            rpkg.main()
            cmd = mock_run.call_args[0][0]
            assert "remove.packages" in cmd
            assert "dplyr" in cmd
