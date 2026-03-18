#!/usr/bin/env python3
"""Batch inventory scanner for AS/400 spool files.

Scans one or more .txt spool files (or a directory), runs spool_splitter
on each, and produces a consolidated JSON inventory of all programs and
DDS components found.

Usage:
    python3 batch_inventory.py /path/to/folder
    python3 batch_inventory.py file1.txt file2.txt file3.txt
"""
import argparse
import glob
import json
import os
import sys

# ---------------------------------------------------------------------------
# Import spool_splitter from same directory
# ---------------------------------------------------------------------------
_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _script_dir)
from spool_splitter import parse_spool


def scan_file(path):
    """Parse a single spool file and return structured inventory entry."""
    result = parse_spool(path)
    summary = result.get("summary", {})
    components = result.get("components", [])

    # Determine if any DSPF exists in this spool (for type_hint)
    has_dspf = summary.get("dds_dspf", 0) > 0

    # Extract COBOL programs
    cobol_programs = []
    for comp in components:
        if comp.get("type") == "COBOL_PROGRAM":
            lines = (comp.get("line_end", 0) or 0) - (comp.get("line_start", 0) or 0)
            type_hint = "INTERACTIVE" if has_dspf else "BATCH"
            cobol_programs.append({
                "name": comp.get("name", "UNKNOWN"),
                "lines": max(lines, 0),
                "type_hint": type_hint,
            })

    # Extract DDS component names
    dds_components = [
        comp.get("name", "")
        for comp in components
        if comp.get("type", "").startswith("DDS_")
    ]

    # Extract CL programs
    cl_programs = [
        comp.get("name", "UNKNOWN")
        for comp in components
        if comp.get("type") == "CL_PROGRAM"
    ]

    return {
        "file": os.path.basename(path),
        "path": os.path.abspath(path),
        "summary": summary,
        "cobol_programs": cobol_programs,
        "dds_components": dds_components,
        "cl_programs": cl_programs,
    }


def batch_scan(paths):
    """Scan multiple paths and produce consolidated inventory."""
    # Resolve paths: if a path is a directory, glob *.txt inside it
    txt_files = []
    scan_path = None
    for p in paths:
        if os.path.isdir(p):
            scan_path = os.path.abspath(p)
            found = sorted(glob.glob(os.path.join(p, "*.txt")))
            txt_files.extend(found)
        elif os.path.isfile(p):
            txt_files.append(p)
        else:
            print(f"Warning: skipping {p} (not found)", file=sys.stderr)

    if not txt_files:
        print("Error: no .txt files found.", file=sys.stderr)
        sys.exit(1)

    if scan_path is None:
        scan_path = os.path.abspath(os.path.dirname(txt_files[0]))

    files = []
    all_programs = []
    total_programs = 0

    for txt in txt_files:
        try:
            entry = scan_file(txt)
        except Exception as e:
            print(f"Warning: failed to parse {txt}: {e}", file=sys.stderr)
            continue

        files.append(entry)
        total_programs += len(entry["cobol_programs"])

        for prog in entry["cobol_programs"]:
            all_programs.append({
                "name": prog["name"],
                "source_file": entry["file"],
                "lines": prog["lines"],
                "type_hint": prog["type_hint"],
            })

    return {
        "scan_path": scan_path,
        "total_files": len(files),
        "total_programs": total_programs,
        "files": files,
        "all_programs": all_programs,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Batch scan AS/400 spool files and produce a consolidated JSON inventory.",
        epilog="Examples:\n"
               "  %(prog)s /path/to/folder\n"
               "  %(prog)s file1.txt file2.txt file3.txt\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="One or more .txt files or directories to scan.",
    )
    args = parser.parse_args()

    result = batch_scan(args.paths)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
