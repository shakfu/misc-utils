#!/usr/bin/env python3
"""Tests for wav_renamer.py"""

import os
import tempfile
from pathlib import Path

import pytest

from wav_renamer import CHARSET, MAX_FILES, generate_name, rename_wav_files


class TestGenerateName:
    def test_first_char_is_a(self):
        assert generate_name(0) == "a"

    def test_first_cycle_letters(self):
        for i, ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
            assert generate_name(i) == ch

    def test_first_cycle_digits(self):
        for i in range(10):
            assert generate_name(26 + i) == str(i)

    def test_second_cycle_doubles(self):
        assert generate_name(36) == "aa"
        assert generate_name(37) == "bb"
        assert generate_name(62) == "00"
        assert generate_name(71) == "99"

    def test_third_cycle_triples(self):
        assert generate_name(72) == "aaa"
        assert generate_name(73) == "bbb"

    def test_boundary_last_of_first_cycle(self):
        assert generate_name(35) == "9"

    def test_charset_length(self):
        assert len(CHARSET) == 36


class TestRenameWavFiles:
    def test_renames_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["beat1.wav", "beat2.wav", "beat3.wav"]:
                (Path(tmpdir) / name).write_bytes(b"RIFF")

            result = rename_wav_files(tmpdir)

            assert len(result) == 3
            assert result[0] == ("beat1.wav", "a.wav")
            assert result[1] == ("beat2.wav", "b.wav")
            assert result[2] == ("beat3.wav", "c.wav")

            actual_files = sorted(os.listdir(tmpdir))
            assert actual_files == ["a.wav", "b.wav", "c.wav"]

    def test_sorts_before_renaming(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["z_last.wav", "a_first.wav", "m_mid.wav"]:
                (Path(tmpdir) / name).write_bytes(b"RIFF")

            result = rename_wav_files(tmpdir)

            assert result[0][0] == "a_first.wav"
            assert result[1][0] == "m_mid.wav"
            assert result[2][0] == "z_last.wav"

    def test_empty_directory(self, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = rename_wav_files(tmpdir)

            assert result == []
            assert "No .wav files" in capsys.readouterr().out

    def test_ignores_non_wav_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "song.wav").write_bytes(b"RIFF")
            (Path(tmpdir) / "readme.txt").write_text("ignore me")
            (Path(tmpdir) / "data.mp3").write_bytes(b"\x00")

            result = rename_wav_files(tmpdir)

            assert len(result) == 1
            assert result[0] == ("song.wav", "a.wav")
            assert "readme.txt" in os.listdir(tmpdir)
            assert "data.mp3" in os.listdir(tmpdir)

    def test_case_insensitive_wav_extension(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "loud.WAV").write_bytes(b"RIFF")
            (Path(tmpdir) / "quiet.Wav").write_bytes(b"RIFF")

            result = rename_wav_files(tmpdir)

            assert len(result) == 2

    def test_exceeds_max_files(self, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(MAX_FILES + 1):
                (Path(tmpdir) / f"file_{i:04d}.wav").write_bytes(b"RIFF")

            result = rename_wav_files(tmpdir)

            assert result == []
            assert "maximum" in capsys.readouterr().err.lower()

    def test_exactly_max_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(MAX_FILES):
                (Path(tmpdir) / f"file_{i:04d}.wav").write_bytes(b"RIFF")

            result = rename_wav_files(tmpdir)

            assert len(result) == MAX_FILES
            actual_files = sorted(os.listdir(tmpdir))
            assert len(actual_files) == MAX_FILES

    def test_dry_run_does_not_rename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_names = ["alpha.wav", "beta.wav"]
            for name in original_names:
                (Path(tmpdir) / name).write_bytes(b"RIFF")

            result = rename_wav_files(tmpdir, dry_run=True)

            assert len(result) == 2
            assert result[0] == ("alpha.wav", "a.wav")
            actual_files = sorted(os.listdir(tmpdir))
            assert actual_files == sorted(original_names)

    def test_dry_run_output(self, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.wav").write_bytes(b"RIFF")

            rename_wav_files(tmpdir, dry_run=True)

            out = capsys.readouterr().out
            assert "test.wav -> a.wav" in out

    def test_ignores_subdirectories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "real.wav").write_bytes(b"RIFF")
            subdir = Path(tmpdir) / "fake.wav"
            subdir.mkdir()

            result = rename_wav_files(tmpdir)

            assert len(result) == 1
            assert result[0] == ("real.wav", "a.wav")

    def test_handles_collision_via_temp_names(self):
        """Renaming a.wav and b.wav should work even though the target
        name 'a.wav' already exists as a source file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.wav").write_bytes(b"content_a")
            (Path(tmpdir) / "b.wav").write_bytes(b"content_b")

            result = rename_wav_files(tmpdir)

            assert len(result) == 2
            assert (Path(tmpdir) / "a.wav").read_bytes() == b"content_a"
            assert (Path(tmpdir) / "b.wav").read_bytes() == b"content_b"

    def test_single_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "only.wav").write_bytes(b"RIFF")

            result = rename_wav_files(tmpdir)

            assert result == [("only.wav", "a.wav")]
            assert os.listdir(tmpdir) == ["a.wav"]
