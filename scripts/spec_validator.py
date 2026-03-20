#!/usr/bin/env python3
"""Validate spec completeness against skeleton.json (v4.0 — 7-chapter format).

Usage:
    python3 spec_validator.py <spec.md> <skeleton.json>

Checks (13 total):
  1. paragraphs    — Every paragraph in skeleton described in Section 6.3
  2. files         — Every file in skeleton listed in Section 4
  3. calls         — Every CALL target in Section 5
  4. screen        — Display file formats covered (INTERACTIVE only)
  5. linkage       — LINKAGE SECTION documented in Section 3
  6. remnants      — No TODO/TBD remnants
  7. io_modes      — OPEN modes match skeleton in Section 4
  8. sql_section   — SQL operations in Section 6 (if has EXEC SQL)
  9. cross_refs    — File/program names consistent across Sections 4+5+6
  10. markdown     — Heading hierarchy and table format
  11. summary      — Section 1 non-empty, 1-3 sentences  [NEW]
  12. classification — Section 2 complete               [NEW]
  13. erd          — Section 7.1 ERD exists (if 2+ files) [NEW]
"""
import argparse
import json
import re
import sys


def load_skeleton(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return json.load(f)


def load_spec(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# ------------------------------------------------------------------
# Check 1: Paragraphs → Section 6.3
# ------------------------------------------------------------------

def check_paragraphs(spec, skeleton):
    """Check that every paragraph is described in the spec."""
    issues = []
    paragraphs = skeleton.get("paragraphs", [])
    for p in paragraphs:
        name = p["name"]
        if name not in spec:
            issues.append(f"MISSING paragraph: {name}")
    covered = sum(1 for p in paragraphs if p["name"] in spec)
    total = len(paragraphs)
    pct = (covered / total * 100) if total > 0 else 100
    return {
        "check": "paragraphs",
        "section": "6.3",
        "total": total,
        "covered": covered,
        "missing": total - covered,
        "coverage_pct": round(pct, 1),
        "issues": issues,
        "pass": len(issues) == 0,
    }


# ------------------------------------------------------------------
# Check 2: Files → Section 4
# ------------------------------------------------------------------

def check_files(spec, skeleton):
    """Check that every file has a definition in Section 4."""
    issues = []
    files = skeleton.get("files", [])
    for f in files:
        fd_name = f.get("fd_name", "")
        logical = f.get("logical_file", fd_name)
        if fd_name not in spec and logical not in spec:
            issues.append(f"MISSING file: {fd_name} ({logical})")
    covered = len(files) - len(issues)
    return {
        "check": "files",
        "section": "4",
        "total": len(files),
        "covered": covered,
        "missing": len(issues),
        "issues": issues,
        "pass": len(issues) == 0,
    }


# ------------------------------------------------------------------
# Check 3: Calls → Section 5
# ------------------------------------------------------------------

def check_calls(spec, skeleton):
    """Check that every CALL target is in Section 5 table."""
    issues = []
    calls = skeleton.get("calls", [])
    targets = list(set(c.get("target", "") for c in calls))
    for target in targets:
        if target not in spec:
            issues.append(f"MISSING call target: {target}")
    covered = len(targets) - len(issues)
    return {
        "check": "calls",
        "section": "5",
        "total": len(targets),
        "covered": covered,
        "missing": len(issues),
        "issues": issues,
        "pass": len(issues) == 0,
    }


# ------------------------------------------------------------------
# Check 4: Screen → Section 6.3 (INTERACTIVE only)
# ------------------------------------------------------------------

def check_screen(spec, skeleton):
    """Check display file fields coverage (INTERACTIVE only)."""
    if skeleton.get("type") != "INTERACTIVE":
        return {"check": "screen", "section": "6.3", "skip": True, "pass": True}

    issues = []
    dspf = skeleton.get("display_file", {})
    if not dspf:
        return {
            "check": "screen",
            "section": "6.3",
            "total": 0,
            "issues": ["No display_file in skeleton"],
            "pass": False,
        }

    formats = dspf.get("record_formats", [])
    for fmt in formats:
        if fmt not in spec:
            issues.append(f"MISSING record format: {fmt}")

    return {
        "check": "screen",
        "section": "6.3",
        "display_file": dspf.get("name", ""),
        "formats": formats,
        "issues": issues,
        "pass": len(issues) == 0,
    }


# ------------------------------------------------------------------
# Check 5: Linkage → Section 3
# ------------------------------------------------------------------

def check_linkage(spec, skeleton):
    """Check LINKAGE SECTION documentation in Section 3."""
    linkage = skeleton.get("linkage", {})
    if not linkage or not linkage.get("fields"):
        return {"check": "linkage", "section": "3", "skip": True, "pass": True}

    issues = []
    using_name = linkage.get("using", "")
    if using_name and using_name not in spec:
        issues.append(f"MISSING linkage parameter: {using_name}")

    if "參數說明" not in spec and "LINKAGE" not in spec and "CALL USING" not in spec:
        issues.append("MISSING section: 3. 參數說明")

    return {
        "check": "linkage",
        "section": "3",
        "using": using_name,
        "fields": len(linkage.get("fields", [])),
        "issues": issues,
        "pass": len(issues) == 0,
    }


# ------------------------------------------------------------------
# Check 6: Remnants
# ------------------------------------------------------------------

def check_remnants(spec):
    """Check for TODO/TBD remnants.

    Excludes business-term usages of '待確認' (e.g. 待確認記錄/交易/資料).
    """
    issues = []
    simple_patterns = [
        (r"TODO", "TODO found"),
        (r"TBD", "TBD found"),
        (r"FIXME", "FIXME found"),
        (r"\?\?\?", "??? found"),
    ]
    for pattern, msg in simple_patterns:
        matches = re.findall(pattern, spec)
        if matches:
            issues.append(f"{msg} ({len(matches)} occurrences)")

    # For 待確認, exclude business-term usages
    tbd_matches = [
        m for m in re.finditer(r"待確認", spec)
        if not re.search(r"待確認[記交資]", spec[m.start():m.start() + 6])
    ]
    if tbd_matches:
        issues.append(f"待確認 found ({len(tbd_matches)} occurrences)")

    return {
        "check": "remnants",
        "section": "all",
        "issues": issues,
        "pass": len(issues) == 0,
    }


# ------------------------------------------------------------------
# Check 7: I/O Modes → Section 4
# ------------------------------------------------------------------

def check_io_modes(spec, skeleton):
    """Check that each file's OPEN mode is consistent with skeleton."""
    files = skeleton.get("files", [])
    if not files:
        return {"check": "io_modes", "section": "4", "skip": True, "pass": True}

    issues = []
    for f in files:
        fd_name = f.get("fd_name", "")
        logical = f.get("logical_file", "")
        if fd_name not in spec and logical not in spec:
            io_mode = f.get("io_mode", "INPUT")
            issues.append(f"File {fd_name} ({io_mode}) not in spec")

    return {
        "check": "io_modes",
        "section": "4",
        "total": len(files),
        "issues": issues,
        "pass": len(issues) == 0,
    }


# ------------------------------------------------------------------
# Check 8: SQL Section → Section 6
# ------------------------------------------------------------------

def check_sql_section(spec, skeleton):
    """Check SQL operations are documented in Section 6."""
    sql_stmts = skeleton.get("sql_statements", [])
    if not sql_stmts:
        return {"check": "sql_section", "section": "6", "skip": True, "pass": True}

    issues = []
    if "SQL" not in spec and "sql" not in spec.lower():
        issues.append("Program has EXEC SQL but spec has no SQL mention")

    return {
        "check": "sql_section",
        "section": "6",
        "sql_count": len(sql_stmts),
        "issues": issues,
        "pass": len(issues) == 0,
    }


# ------------------------------------------------------------------
# Check 9: Cross-References → Sections 4+5+6
# ------------------------------------------------------------------

def check_cross_references(spec, skeleton):
    """Check that file names in spec match skeleton files."""
    issues = []
    skeleton_files = set()
    for f in skeleton.get("files", []):
        skeleton_files.add(f.get("fd_name", "").upper())
        lf = f.get("logical_file", "")
        if lf:
            skeleton_files.add(lf.upper())

    spec_file_refs = set()
    for m in re.finditer(r'(?:LFD|FFD|MFD)\w+', spec, re.IGNORECASE):
        spec_file_refs.add(m.group(0).upper())

    for ref in spec_file_refs:
        base = ref
        for prefix in ("LFD", "FFD", "MFD"):
            if base.startswith(prefix):
                base = base[len(prefix):]
                break
        found = any(
            base in sf or ref in sf or sf in ref
            for sf in skeleton_files
        )
        if not found and skeleton_files:
            issues.append(f"Spec references {ref} not in skeleton files")

    return {
        "check": "cross_references",
        "section": "4+5+6",
        "issues": issues,
        "pass": len(issues) == 0,
    }


# ------------------------------------------------------------------
# Check 10: Markdown Structure
# ------------------------------------------------------------------

def check_markdown_structure(spec):
    """Validate heading hierarchy and table column consistency."""
    issues = []
    lines = spec.split("\n")

    # Check heading hierarchy
    prev_level = 0
    for i, line in enumerate(lines):
        m = re.match(r'^(#{1,6})\s', line)
        if m:
            level = len(m.group(1))
            if prev_level > 0 and level > prev_level + 1:
                issues.append(
                    f"Line {i+1}: Heading jumps from H{prev_level} to H{level}"
                )
            prev_level = level

    # Check table column consistency
    in_table = False
    table_cols = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cols = stripped.count("|") - 1
            if not in_table:
                in_table = True
                table_cols = cols
            else:
                if cols != table_cols and cols > 0:
                    issues.append(
                        f"Line {i+1}: Table column mismatch "
                        f"(expected {table_cols}, got {cols})"
                    )
        else:
            in_table = False
            table_cols = 0

    return {
        "check": "markdown_structure",
        "section": "all",
        "issues": issues,
        "pass": len(issues) == 0,
    }


# ------------------------------------------------------------------
# Check 11: Summary → Section 1  [NEW]
# ------------------------------------------------------------------

def check_summary(spec):
    """Check that Section 1 (簡述) is non-empty and 1-3 sentences."""
    issues = []

    # Find Section 1 content
    m = re.search(
        r'##\s*1\.\s*簡述\s*\n(.*?)(?=\n##\s*2\.|\Z)',
        spec,
        re.DOTALL,
    )
    if not m:
        issues.append("MISSING section: 1. 簡述")
        return {"check": "summary", "section": "1", "issues": issues, "pass": False}

    content = m.group(1).strip()
    if not content or content.startswith("{"):
        issues.append("Section 1 (簡述) is empty or contains placeholder")
    else:
        # Count sentences (rough: split by 。or .)
        sentences = [s for s in re.split(r'[。.！!]', content) if s.strip()]
        if len(sentences) > 5:
            issues.append(
                f"Section 1 too long ({len(sentences)} sentences, expected 1-3)"
            )

    return {
        "check": "summary",
        "section": "1",
        "issues": issues,
        "pass": len(issues) == 0,
    }


# ------------------------------------------------------------------
# Check 12: Classification → Section 2  [NEW]
# ------------------------------------------------------------------

def check_classification(spec):
    """Check that Section 2 (程式分類) is complete."""
    issues = []

    m = re.search(
        r'##\s*2\.\s*程式分類\s*\n(.*?)(?=\n##\s*3\.|\Z)',
        spec,
        re.DOTALL,
    )
    if not m:
        issues.append("MISSING section: 2. 程式分類")
        return {
            "check": "classification",
            "section": "2",
            "issues": issues,
            "pass": False,
        }

    content = m.group(1)
    required_fields = ["程式代號", "程式名稱", "程式類型"]
    for field in required_fields:
        if field not in content:
            issues.append(f"Section 2 missing field: {field}")

    valid_types = ["主程式", "副程式", "批次程式", "報表程式", "畫面程式"]
    has_type = any(t in content for t in valid_types)
    if not has_type:
        issues.append("Section 2: no recognized program type found")

    return {
        "check": "classification",
        "section": "2",
        "issues": issues,
        "pass": len(issues) == 0,
    }


# ------------------------------------------------------------------
# Check 13: ERD → Section 7.1  [NEW]
# ------------------------------------------------------------------

def check_erd(spec, skeleton):
    """Check ERD diagram exists when program uses 2+ files."""
    files = skeleton.get("files", [])
    if len(files) < 2:
        return {"check": "erd", "section": "7.1", "skip": True, "pass": True}

    issues = []
    if "erDiagram" not in spec and "資料關聯圖" not in spec:
        issues.append(
            f"Program uses {len(files)} files but Section 7.1 has no ERD"
        )

    return {
        "check": "erd",
        "section": "7.1",
        "file_count": len(files),
        "issues": issues,
        "pass": len(issues) == 0,
    }


# ------------------------------------------------------------------
# Main Validation
# ------------------------------------------------------------------

def validate(spec_path, skeleton_path):
    spec = load_spec(spec_path)
    skeleton = load_skeleton(skeleton_path)

    results = [
        check_paragraphs(spec, skeleton),    # 1
        check_files(spec, skeleton),         # 2
        check_calls(spec, skeleton),         # 3
        check_screen(spec, skeleton),        # 4
        check_linkage(spec, skeleton),       # 5
        check_remnants(spec),                # 6
        check_io_modes(spec, skeleton),      # 7
        check_sql_section(spec, skeleton),   # 8
        check_cross_references(spec, skeleton),  # 9
        check_markdown_structure(spec),      # 10
        check_summary(spec),                 # 11 [NEW]
        check_classification(spec),          # 12 [NEW]
        check_erd(spec, skeleton),           # 13 [NEW]
    ]

    all_pass = all(r["pass"] for r in results)
    total_issues = sum(len(r.get("issues", [])) for r in results)

    para_check = results[0]
    quality = {
        "paragraph_coverage": para_check.get("coverage_pct", 100),
        "total_checks": len(results),
        "checks_passed": sum(1 for r in results if r["pass"]),
        "checks_skipped": sum(1 for r in results if r.get("skip", False)),
    }

    return {
        "spec_file": spec_path.split("/")[-1],
        "skeleton_file": skeleton_path.split("/")[-1],
        "program": skeleton.get("program", "UNKNOWN"),
        "all_pass": all_pass,
        "total_issues": total_issues,
        "quality": quality,
        "checks": results,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Validate COBOL spec completeness against skeleton JSON (13 checks)."
    )
    parser.add_argument("spec", help="Path to the spec markdown file (.md).")
    parser.add_argument("skeleton", help="Path to the skeleton JSON file.")
    args = parser.parse_args()

    result = validate(args.spec, args.skeleton)

    # Print report
    print(f"Validation Report: {result['program']}")
    print(f"{'=' * 60}")
    print(f"Spec: {result['spec_file']}")
    print(f"Skeleton: {result['skeleton_file']}")
    q = result.get("quality", {})
    print(
        f"Quality: {q.get('checks_passed', 0)}/{q.get('total_checks', 0)} checks passed, "
        f"paragraph coverage {q.get('paragraph_coverage', 0)}%"
    )
    print()

    for check in result["checks"]:
        name = check["check"].upper()
        section = check.get("section", "")
        status = "PASS" if check["pass"] else "FAIL"
        skip = check.get("skip", False)
        section_tag = f" [S{section}]" if section else ""

        if skip:
            print(f"  [{name:18s}]{section_tag} SKIP (not applicable)")
            continue

        total = check.get("total", "")
        covered = check.get("covered", "")
        detail = f" ({covered}/{total})" if total != "" else ""
        pct = check.get("coverage_pct")
        pct_str = f" [{pct}%]" if pct is not None else ""
        print(f"  [{name:18s}]{section_tag} {status}{detail}{pct_str}")

        for issue in check.get("issues", []):
            print(f"    - {issue}")

    print()
    if result["all_pass"]:
        print("RESULT: ALL 13 CHECKS PASSED")
    else:
        print(f"RESULT: {result['total_issues']} ISSUE(S) FOUND")

    # JSON to stderr for programmatic use
    print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)

    sys.exit(0 if result["all_pass"] else 1)


if __name__ == "__main__":
    main()
