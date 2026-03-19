#!/usr/bin/env python3
"""Shared encoding detection for AS/400 exported text files.

Most AS/400 .txt files exported via FTP or WRKMBRPDM are Big5 (CCSID 950)
encoded. This module provides reliable detection and a convenience opener.

Usage:
    from encoding import detect_encoding, open_as400

    enc = detect_encoding("myfile.txt")           # -> "big5"
    with open_as400("myfile.txt") as f:          # auto-detect encoding
        lines = f.readlines()

CLI:
    python3 encoding.py <file>                   # print detected encoding
    python3 encoding.py --help
"""
import argparse
import io
import os
import re
import sys


def detect_encoding(path, sample_size=10000):
    """Detect the encoding of an AS/400 exported text file.

    Strategy:
      1. Read the first `sample_size` bytes.
      2. Try Big5 decode — if it succeeds and contains CJK characters, return 'big5'.
      3. Try UTF-8 decode — if it succeeds, return 'utf-8'.
      4. Fallback to 'big5' (with errors='replace' expected by caller).

    Returns one of: 'big5', 'utf-8', 'big5-fallback'.
    """
    with open(path, "rb") as f:
        raw = f.read(sample_size)

    if not raw:
        return "utf-8"

    # --- Try Big5 ---
    try:
        decoded = raw.decode("big5")
        # Check for CJK characters (common in Traditional Chinese AS/400 files)
        # CJK Unified Ideographs: U+4E00..U+9FFF
        # CJK Compatibility Ideographs: U+F900..U+FAFF
        # Bopomofo: U+3100..U+312F
        # CJK punctuation: U+3000..U+303F
        if re.search(r"[\u4e00-\u9fff\u3000-\u303f\uf900-\ufaff]", decoded):
            return "big5"
    except (UnicodeDecodeError, ValueError):
        pass

    # --- Try UTF-8 ---
    try:
        raw.decode("utf-8")
        return "utf-8"
    except (UnicodeDecodeError, ValueError):
        pass

    # --- Fallback: Big5 with errors='replace' ---
    return "big5-fallback"


def open_as400(path):
    """Open an AS/400 exported text file with auto-detected encoding.

    Returns a file-like object (text mode) that the caller can use
    in a `with` statement.

    For 'big5-fallback', uses errors='replace' to handle malformed bytes.
    """
    enc = detect_encoding(path)

    if enc == "big5-fallback":
        return open(path, "r", encoding="big5", errors="replace")
    elif enc == "big5":
        return open(path, "r", encoding="big5", errors="replace")
    else:
        return open(path, "r", encoding="utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser(
        description="Detect encoding of AS/400 exported text files."
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="One or more files to detect encoding for.",
    )
    args = parser.parse_args()

    for path in args.files:
        if not os.path.isfile(path):
            print(f"NOT FOUND: {path}", file=sys.stderr)
            continue
        enc = detect_encoding(path)
        print(f"{enc}\t{path}")


if __name__ == "__main__":
    main()
