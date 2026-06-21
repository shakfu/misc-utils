#!/usr/bin/env python3
"""Rename .wav files in a directory using a sequential naming scheme.

Naming scheme:
  First 36:  a, b, c, ..., z, 0, 1, ..., 9
  Next 36:   aa, bb, cc, ..., zz, 00, 11, ..., 99
  Next 36:   aaa, bbb, ccc, ..., zzz, 000, 111, ..., 999
  ...and so on, increasing repetition count each cycle.
"""

import argparse
import os
import string
import sys

CHARSET = list(string.ascii_lowercase) + [str(d) for d in range(10)]  # 36 chars
MAX_FILES = 72  # 2 cycles of 36 (single + double characters)


def generate_name(index: int) -> str:
    """Generate the sequential name for a given 0-based index."""
    cycle = index // len(CHARSET)  # how many full cycles completed
    pos = index % len(CHARSET)     # position within current cycle
    repeat = cycle + 1             # repetition count
    return CHARSET[pos] * repeat


def rename_wav_files(directory: str, dry_run: bool = False) -> list[tuple[str, str]]:
    """Rename all .wav files in directory according to the naming scheme.

    Files are sorted by name before renaming to ensure deterministic order.
    Returns list of (old_name, new_name) tuples.
    """
    wav_files = sorted(
        f for f in os.listdir(directory)
        if f.lower().endswith(".wav") and os.path.isfile(os.path.join(directory, f))
    )

    if not wav_files:
        print("No .wav files found in", directory)
        return []

    if len(wav_files) > MAX_FILES:
        print(
            f"Error: found {len(wav_files)} .wav files, maximum is {MAX_FILES}",
            file=sys.stderr,
        )
        return []

    renames = []
    # Two-pass rename to avoid collisions: first rename to temp names, then to final.
    temp_names = []
    for i, old_name in enumerate(wav_files):
        new_name = generate_name(i) + ".wav"
        temp_name = f"__wav_rename_tmp_{i}__.wav"
        temp_names.append((old_name, temp_name, new_name))
        renames.append((old_name, new_name))

    if dry_run:
        for old_name, new_name in renames:
            print(f"  {old_name} -> {new_name}")
        return renames

    # Pass 1: rename to temp
    for old_name, temp_name, _ in temp_names:
        os.rename(
            os.path.join(directory, old_name),
            os.path.join(directory, temp_name),
        )

    # Pass 2: rename to final
    for _, temp_name, new_name in temp_names:
        os.rename(
            os.path.join(directory, temp_name),
            os.path.join(directory, new_name),
        )

    for old_name, new_name in renames:
        print(f"  {old_name} -> {new_name}")

    print(f"\nRenamed {len(renames)} file(s).")
    return renames


def main():
    parser = argparse.ArgumentParser(
        description="Rename .wav files using sequential A-Z, 0-9 naming scheme."
    )
    parser.add_argument("directory", help="Directory containing .wav files")
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Show what would be renamed without actually renaming",
    )
    args = parser.parse_args()

    directory = os.path.abspath(args.directory)
    if not os.path.isdir(directory):
        print(f"Error: '{directory}' is not a directory", file=sys.stderr)
        sys.exit(1)

    rename_wav_files(directory, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
