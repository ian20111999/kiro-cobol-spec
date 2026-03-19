#!/usr/bin/env python3
"""Format normalizer and pre-processor for AS/400 exported text files.

Handles 8+ format variants found in real AS/400 .txt exports:
  - SEU SOURCE LISTING (most common)
  - COPY FILE spool output
  - DSPFFD query reports (field-level file descriptions)
  - MSGFILE (message file exports)
  - Multi-member concatenated files
  - SEU annotation artifacts (Aefa / | marks)

Run this BEFORE any parser to get clean, structured input.

Usage:
    python3 format_normalizer.py <file_or_dir> [--json] [--verbose]

API:
    from format_normalizer import normalize, detect_format
    result = normalize("/path/to/file.txt")
"""
import argparse
import glob
import json
import os
import re
import sys

# Import encoding module from same directory
_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _script_dir)
from encoding import detect_encoding, open_as400


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def detect_format(path):
    """Detect the format of an AS/400 exported text file.

    Scans the first 30 lines for header keywords.

    Returns one of:
        'SEU'       — SEU SOURCE LISTING
        'COPY_FILE' — COPY FILE spool output
        'DSPFFD'    — DSPFFD query report (field descriptions)
        'MSGFILE'   — Message file export
        'UNKNOWN'   — Unrecognized format
    """
    with open_as400(path) as f:
        header_lines = []
        for i, line in enumerate(f):
            if i >= 30:
                break
            header_lines.append(line)

    header_text = "".join(header_lines)

    # DSPFFD: look for DSPFFD-specific markers
    if re.search(r"Display\s+File\s+Field\s+Description", header_text, re.IGNORECASE):
        return "DSPFFD"
    # Alternative DSPFFD detection: columnar field headers
    if re.search(r"Field\s+Level\s+.*Type\s+.*Length", header_text, re.IGNORECASE):
        return "DSPFFD"
    if "QUERY NAME" in header_text.upper():
        return "DSPFFD"

    # Message file
    if re.search(r"Message\s+File", header_text, re.IGNORECASE):
        return "MSGFILE"
    if re.search(r"Message\s+Description", header_text, re.IGNORECASE):
        return "MSGFILE"

    # SEU SOURCE LISTING
    if "SEU SOURCE LISTING" in header_text:
        return "SEU"

    # COPY FILE
    if "COPY FILE" in header_text:
        return "COPY_FILE"

    # Fallback heuristics
    for line in header_lines:
        if "SEQNBR" in line:
            return "SEU"
        if "RCDNBR" in line:
            return "COPY_FILE"

    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Annotation cleaning
# ---------------------------------------------------------------------------

def clean_annotations(lines):
    """Remove SEU editor annotation artifacts (Aefa / | marks).

    These appear as extra characters between the sequence number and the
    DDS 'A' form type indicator, breaking column alignment.

    Pattern: line number + whitespace + (Aefa or |) + whitespace + A-spec
    Fix: replace the annotation with spaces to preserve column alignment.

    Returns (cleaned_lines, count_cleaned).
    """
    # Pattern matches: seq_number + space + annotation + space before DDS content
    re_annotation = re.compile(
        r"^(\s*\d+\s+)"           # group 1: line prefix (seq number + spaces)
        r"(?:Aefa|\|)"            # annotation artifact
        r"(\s+)"                  # spaces after artifact
        r"(A\s)"                  # DDS form type 'A' at correct position
    )

    cleaned = []
    count = 0
    for line in lines:
        m = re_annotation.match(line)
        if m:
            # Replace annotation with spaces (same width) to keep alignment
            prefix = m.group(1)
            # The annotation is typically 4-5 chars, replace with spaces
            artifact_len = m.start(2) - m.end(1) + len("Aefa")  # approximate
            replacement = prefix + " " * (m.start(3) - m.end(1)) + line[m.start(3):]
            cleaned.append(replacement)
            count += 1
        else:
            cleaned.append(line)

    return cleaned, count


# ---------------------------------------------------------------------------
# Multi-member splitting
# ---------------------------------------------------------------------------

def split_members(lines, path=None):
    """Split a multi-member concatenated file at E N D  O F  S O U R C E markers.

    Returns a list of member dicts:
        [{"name": "MEMBER1", "lines": [...], "start": 1, "end": 51}, ...]

    Each member retains its own SEU header for independent parsing.
    """
    EOS_MARKER = "E N D  O F  S O U R C E"

    # Find all EOS positions
    eos_positions = []
    for i, line in enumerate(lines):
        if EOS_MARKER in line:
            eos_positions.append(i)

    # If no EOS marker or only one at the very end, it's a single member
    if len(eos_positions) <= 1:
        member_name = _extract_member_name(lines)
        if not member_name and path:
            member_name = os.path.splitext(os.path.basename(path))[0]
        member_type = _detect_member_type(lines)
        return [{
            "name": member_name or "UNKNOWN",
            "type": member_type,
            "lines": lines,
            "start": 1,
            "end": len(lines),
        }]

    # Split into multiple members
    members = []
    prev_end = 0
    for eos_idx in eos_positions:
        member_lines = lines[prev_end:eos_idx + 1]
        if not member_lines or all(not l.strip() for l in member_lines):
            prev_end = eos_idx + 1
            continue

        member_name = _extract_member_name(member_lines)
        member_type = _detect_member_type(member_lines)
        members.append({
            "name": member_name or f"MEMBER_{len(members) + 1}",
            "type": member_type,
            "lines": member_lines,
            "start": prev_end + 1,  # 1-based
            "end": eos_idx + 1,     # 1-based, inclusive
        })
        prev_end = eos_idx + 1

    # Any remaining lines after the last EOS marker
    if prev_end < len(lines):
        remaining = lines[prev_end:]
        if any(l.strip() for l in remaining):
            member_name = _extract_member_name(remaining)
            member_type = _detect_member_type(remaining)
            members.append({
                "name": member_name or f"MEMBER_{len(members) + 1}",
                "type": member_type,
                "lines": remaining,
                "start": prev_end + 1,
                "end": len(lines),
            })

    return members


def _extract_member_name(lines):
    """Extract member name from SEU/COPY FILE header lines."""
    for line in lines[:20]:
        # SEU: MEMBER . . . . . . :   MEMBERNAME
        m = re.search(r"MEMBER[\s.]*[:.]?\s+(\S+)", line)
        if m and "MEMBER" in line:
            return m.group(1).strip()
        # COPY FILE: Member . . . . : MEMBERNAME
        m = re.search(r"Member[\s.]*[:.]?\s+(\S+)", line)
        if m:
            return m.group(1).strip()
    return None


def _detect_member_type(lines):
    """Detect what type of source this member contains."""
    content = "".join(lines[:50])

    # Check for DDS content (A-spec records)
    if re.search(r"^\s*\d+\s+A\s+R\s+\w+", content, re.MULTILINE):
        # Has record format — is it PF, LF, or DSPF?
        if re.search(r"PFILE\(", content) or re.search(r"JFILE\(", content):
            return "DDS_LF"
        if re.search(r"\bSFL\b", content):
            return "DDS_DSPF"
        return "DDS_PF"

    # Check for COBOL
    if re.search(r"IDENTIFICATION\s+DIVISION", content, re.IGNORECASE):
        return "COBOL"

    # Check for CL
    if re.search(r"^\s*\d+\s+PGM\b", content, re.MULTILINE):
        return "CL"

    return "UNKNOWN"


# ---------------------------------------------------------------------------
# DSPFFD report parser
# ---------------------------------------------------------------------------

def parse_dspffd(path):
    """Parse a DSPFFD query report into a structure compatible with dds_parser output.

    DSPFFD reports use fixed-width columns with field descriptions.
    This parser handles multi-page reports with PAGE markers.

    Returns a dict compatible with dds_parser.parse_physical_logical().
    """
    with open_as400(path) as f:
        lines = f.readlines()

    result = {
        "file": os.path.splitext(os.path.basename(path))[0],
        "source": "DSPFFD",
        "record_format": None,
        "ref_file": None,
        "pfile": None,
        "jfile": None,
        "join_specs": [],
        "unique": False,
        "dynslt": False,
        "text": None,
        "fields": [],
        "keys": [],
        "select_omit": [],
    }

    # Parse header for file name
    for line in lines[:20]:
        m = re.search(r"File[\s.]*[:.]?\s+(\S+)", line, re.IGNORECASE)
        if m:
            result["file"] = m.group(1).strip()
        m = re.search(r"Record format[\s.]*[:.]?\s+(\S+)", line, re.IGNORECASE)
        if m:
            result["record_format"] = m.group(1).strip()

    # Find field data lines
    # DSPFFD format typically has columns:
    #   Field, Level, Type, Length, Dec, Description/COLHDG
    # We look for lines that start with a field name pattern
    re_field_line = re.compile(
        r"^\s*(\w{1,10})\s+"          # field name (1-10 chars)
        r"(\d+)\s+"                    # level
        r"([APSBYL])\s+"              # data type
        r"(\d+)\s+"                    # length
        r"(\d*)\s*"                    # decimal (optional)
        r"(.*)$"                       # rest (description/COLHDG)
    )

    for line in lines:
        # Skip page headers and rulers
        if "PAGE" in line.upper() and re.search(r"\d+/\d+/\d+", line):
            continue
        if "Display File Field" in line:
            continue
        if re.match(r"^\s*$", line):
            continue
        if re.match(r"^\s*[-=]+\s*$", line):
            continue

        m = re_field_line.match(line)
        if m:
            name = m.group(1).strip()
            dec_str = m.group(5).strip()
            field = {
                "name": name,
                "alias": None,
                "type": m.group(3).strip(),
                "length": int(m.group(4)),
                "decimal": int(dec_str) if dec_str else None,
                "ref": False,
                "text": m.group(6).strip() if m.group(6).strip() else None,
                "colhdg": None,
            }
            result["fields"].append(field)

    return result


# ---------------------------------------------------------------------------
# Main normalize function
# ---------------------------------------------------------------------------

def normalize(path):
    """Normalize an AS/400 exported text file.

    Performs: encoding detection -> format detection -> annotation cleaning
              -> multi-member splitting -> returns structured result.

    Returns:
        {
            "path": "/full/path/to/file.txt",
            "encoding": "big5",
            "format": "SEU",
            "members": [
                {"name": "MEMBER1", "type": "DDS_PF", "lines": [...],
                 "line_range": [1, 51]},
                ...
            ],
            "warnings": ["Cleaned 4 annotation artifacts"]
        }
    """
    if not os.path.isfile(path):
        return {
            "path": os.path.abspath(path),
            "encoding": None,
            "format": "NOT_FOUND",
            "members": [],
            "warnings": [f"File not found: {path}"],
        }

    warnings = []

    # 1. Detect encoding
    enc = detect_encoding(path)

    # 2. Detect format
    fmt = detect_format(path)

    # 3. Read all lines with correct encoding
    with open_as400(path) as f:
        lines = f.readlines()

    # 4. Clean annotations
    cleaned_lines, annotation_count = clean_annotations(lines)
    if annotation_count > 0:
        warnings.append(f"Cleaned {annotation_count} annotation artifacts")
        lines = cleaned_lines

    # 5. Split members (for SEU and COPY_FILE formats)
    if fmt in ("SEU", "COPY_FILE"):
        members_raw = split_members(lines, path)
    else:
        # Non-standard formats: treat as single member
        member_name = os.path.splitext(os.path.basename(path))[0]
        members_raw = [{
            "name": member_name,
            "type": fmt,
            "lines": lines,
            "start": 1,
            "end": len(lines),
        }]

    # 6. Build member output (without raw lines for JSON output)
    members = []
    for m in members_raw:
        members.append({
            "name": m["name"],
            "type": m["type"],
            "lines": m["lines"],
            "line_range": [m["start"], m["end"]],
        })

    return {
        "path": os.path.abspath(path),
        "encoding": enc,
        "format": fmt,
        "members": members,
        "warnings": warnings,
    }


def normalize_dir(dir_path, verbose=False):
    """Normalize all .txt files in a directory."""
    txt_files = sorted(glob.glob(os.path.join(dir_path, "*.txt")))
    results = []

    for path in txt_files:
        if verbose:
            print(f"Processing: {os.path.basename(path)}...", file=sys.stderr)
        result = normalize(path)
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _make_json_safe(results):
    """Remove raw line data from results for JSON output."""
    safe = []
    for r in results:
        r_copy = dict(r)
        r_copy["members"] = []
        for m in r["members"]:
            m_copy = {k: v for k, v in m.items() if k != "lines"}
            m_copy["line_count"] = len(m.get("lines", []))
            r_copy["members"].append(m_copy)
        safe.append(r_copy)
    return safe


def main():
    parser = argparse.ArgumentParser(
        description="Normalize AS/400 exported text files: detect format, "
                    "clean annotations, split members.",
        epilog="Examples:\n"
               "  %(prog)s myfile.txt\n"
               "  %(prog)s /path/to/source/ --verbose\n"
               "  %(prog)s myfile.txt --json\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "path",
        help="A .txt file or directory to normalize.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output results as JSON.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print progress to stderr.",
    )
    args = parser.parse_args()

    if os.path.isdir(args.path):
        results = normalize_dir(args.path, verbose=args.verbose)
    elif os.path.isfile(args.path):
        results = [normalize(args.path)]
    else:
        print(f"Error: {args.path} not found.", file=sys.stderr)
        sys.exit(1)

    if args.json:
        safe = _make_json_safe(results)
        print(json.dumps(safe, indent=2, ensure_ascii=False))
    else:
        # Human-readable summary
        total_members = 0
        format_counts = {}
        encoding_counts = {}
        total_warnings = 0

        for r in results:
            fmt = r["format"]
            enc = r["encoding"]
            format_counts[fmt] = format_counts.get(fmt, 0) + 1
            encoding_counts[enc] = encoding_counts.get(enc, 0) + 1
            total_members += len(r["members"])
            total_warnings += len(r["warnings"])

            if args.verbose:
                fname = os.path.basename(r["path"])
                members_str = ", ".join(
                    f'{m["name"]}({m["type"]})'
                    for m in r["members"]
                )
                warn_str = f" !! {', '.join(r['warnings'])}" if r["warnings"] else ""
                print(f"  {fname}: {enc}/{fmt} -> [{members_str}]{warn_str}")

        print(f"\nFormat Normalizer Summary")
        print(f"{'=' * 50}")
        print(f"Files scanned:    {len(results)}")
        print(f"Total members:    {total_members}")
        print(f"Formats:          {format_counts}")
        print(f"Encodings:        {encoding_counts}")
        if total_warnings > 0:
            print(f"Warnings:         {total_warnings}")


if __name__ == "__main__":
    main()
