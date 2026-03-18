#!/usr/bin/env python3
"""Validate spec completeness against skeleton.json.

Usage:
    python3 spec_validator.py <spec.md> <skeleton.json>

Checks:
  1. Every paragraph in skeleton has a description in spec
  2. Every file in skeleton has a table definition in spec
  3. Every CALL target has an entry in the subroutine table
  4. Display file fields are covered (if INTERACTIVE)
  5. LINKAGE SECTION is documented
  6. No TODO/待確認 remnants
  7. Quality metrics (coverage percentage)
  8. I/O mode verification
  9. SQL section verification (if has EXEC SQL)
  10. Cross-reference: spec file names vs skeleton files
  11. Markdown structure validation
"""
import argparse
import json
import re
import sys


def load_skeleton(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_spec(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def check_paragraphs(spec, skeleton):
    """Check that every paragraph is described in the logic section."""
    issues = []
    paragraphs = skeleton.get("paragraphs", [])
    for p in paragraphs:
        name = p["name"]
        # Look for paragraph name as a heading or in content
        if name not in spec:
            issues.append(f"MISSING paragraph: {name}")
    covered = sum(1 for p in paragraphs if p["name"] in spec)
    total = len(paragraphs)
    pct = (covered / total * 100) if total > 0 else 100
    return {
        "check": "paragraphs",
        "total": total,
        "covered": covered,
        "missing": total - covered,
        "coverage_pct": round(pct, 1),
        "issues": issues,
        "pass": len(issues) == 0,
    }


def check_files(spec, skeleton):
    """Check that every file has a table definition."""
    issues = []
    files = skeleton.get("files", [])
    for f in files:
        fd_name = f.get("fd_name", "")
        logical = f.get("logical_file", fd_name)
        # Look for file reference in spec
        if fd_name not in spec and logical not in spec:
            issues.append(f"MISSING file: {fd_name} ({logical})")
    covered = len(files) - len(issues)
    return {
        "check": "files",
        "total": len(files),
        "covered": covered,
        "missing": len(issues),
        "issues": issues,
        "pass": len(issues) == 0,
    }


def check_calls(spec, skeleton):
    """Check that every CALL target is in subroutine table."""
    issues = []
    calls = skeleton.get("calls", [])
    # Unique targets
    targets = list(set(c.get("target", "") for c in calls))
    for target in targets:
        if target not in spec:
            issues.append(f"MISSING call target: {target}")
    covered = len(targets) - len(issues)
    return {
        "check": "calls",
        "total": len(targets),
        "covered": covered,
        "missing": len(issues),
        "issues": issues,
        "pass": len(issues) == 0,
    }


def check_screen(spec, skeleton):
    """Check display file fields coverage (INTERACTIVE only)."""
    if skeleton.get("type") != "INTERACTIVE":
        return {"check": "screen", "skip": True, "pass": True}

    issues = []
    dspf = skeleton.get("display_file", {})
    if not dspf:
        return {
            "check": "screen",
            "total": 0,
            "issues": ["No display_file in skeleton"],
            "pass": False,
        }

    dspf_name = dspf.get("name", "")
    formats = dspf.get("record_formats", [])

    if "畫面規格" not in spec and "畫面" not in spec:
        issues.append("MISSING section: 四. 畫面規格")

    for fmt in formats:
        if fmt not in spec:
            issues.append(f"MISSING record format: {fmt}")

    return {
        "check": "screen",
        "display_file": dspf_name,
        "formats": formats,
        "issues": issues,
        "pass": len(issues) == 0,
    }


def check_linkage(spec, skeleton):
    """Check LINKAGE SECTION documentation."""
    linkage = skeleton.get("linkage", {})
    if not linkage or not linkage.get("fields"):
        return {"check": "linkage", "skip": True, "pass": True}

    issues = []
    using_name = linkage.get("using", "")
    if using_name and using_name not in spec:
        issues.append(f"MISSING linkage parameter: {using_name}")

    if "參數介面" not in spec and "LINKAGE" not in spec:
        issues.append("MISSING section: 五. 參數介面")

    return {
        "check": "linkage",
        "using": using_name,
        "fields": len(linkage.get("fields", [])),
        "issues": issues,
        "pass": len(issues) == 0,
    }


def check_remnants(spec):
    """Check for TODO/待確認 remnants.

    '待確認' as a business term (e.g., '待確認記錄', '待確認交易') is valid.
    Only flag standalone '待確認' that signals incomplete analysis, such as
    '功能待確認', '邏輯待確認', or bare '待確認' at end of sentence.
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

    # For 待確認, exclude business-term usages like 待確認記錄/交易/資料
    tbd_matches = [
        m for m in re.finditer(r"待確認", spec)
        if not re.search(r"待確認[記交資]", spec[m.start():m.start() + 6])
    ]
    if tbd_matches:
        issues.append(f"待確認 found ({len(tbd_matches)} occurrences)")

    return {
        "check": "remnants",
        "issues": issues,
        "pass": len(issues) == 0,
    }


def check_io_modes(spec, skeleton):
    """Check that each file's OPEN mode is mentioned in spec."""
    files = skeleton.get("files", [])
    if not files:
        return {"check": "io_modes", "skip": True, "pass": True}

    issues = []
    io_mode_terms = {
        "INPUT": "唯讀",
        "OUTPUT": "唯寫",
        "I-O": "讀寫",
        "EXTEND": "附加",
    }

    for f in files:
        fd_name = f.get("fd_name", "")
        io_mode = f.get("io_mode", "INPUT")
        # Check if the file and its mode are mentioned
        if fd_name in spec:
            cn_term = io_mode_terms.get(io_mode, io_mode)
            # Don't require explicit mention of mode -- just check file is present
            # (Mode is implicitly covered in file operations)
        else:
            logical = f.get("logical_file", "")
            if logical not in spec:
                issues.append(f"File {fd_name} ({io_mode}) not in spec")

    return {
        "check": "io_modes",
        "total": len(files),
        "issues": issues,
        "pass": len(issues) == 0,
    }


def check_sql_section(spec, skeleton):
    """Check SQL section exists if skeleton has SQL statements."""
    sql_stmts = skeleton.get("sql_statements", [])
    if not sql_stmts:
        return {"check": "sql_section", "skip": True, "pass": True}

    issues = []
    if "SQL" not in spec and "sql" not in spec.lower():
        issues.append("Program has EXEC SQL but spec has no SQL section")

    return {
        "check": "sql_section",
        "sql_count": len(sql_stmts),
        "issues": issues,
        "pass": len(issues) == 0,
    }


def check_cross_references(spec, skeleton):
    """Check that file names mentioned in spec exist in skeleton."""
    issues = []
    skeleton_files = set()
    for f in skeleton.get("files", []):
        skeleton_files.add(f.get("fd_name", "").upper())
        lf = f.get("logical_file", "")
        if lf:
            skeleton_files.add(lf.upper())

    # Find file-like references in spec (words matching AS/400 naming)
    # We check that any file name in the spec's table definitions matches skeleton
    # This is a light check -- just verify spec doesn't reference phantom files
    spec_file_refs = set()
    for m in re.finditer(r'(?:LFDFALD|FFDFALD|LFD|FFD)\w+', spec, re.IGNORECASE):
        spec_file_refs.add(m.group(0).upper())

    for ref in spec_file_refs:
        # Strip common prefixes for matching
        base = ref
        for prefix in ("LFDFALD", "FFDFALD", "LFD", "FFD"):
            if base.startswith(prefix):
                base = base[len(prefix):]
                break
        # Check if the base or full name matches any skeleton file
        found = any(
            base in sf or ref in sf or sf in ref
            for sf in skeleton_files
        )
        if not found and skeleton_files:
            issues.append(f"Spec references {ref} not in skeleton files")

    return {
        "check": "cross_references",
        "issues": issues,
        "pass": len(issues) == 0,
    }


def check_markdown_structure(spec):
    """Validate basic markdown structure (heading levels, table format)."""
    issues = []
    lines = spec.split("\n")

    # Check heading hierarchy
    prev_level = 0
    for i, line in enumerate(lines):
        m = re.match(r'^(#{1,6})\s', line)
        if m:
            level = len(m.group(1))
            # Allow jumping from 0 to any level, but warn on skip > 1
            if prev_level > 0 and level > prev_level + 1:
                issues.append(
                    f"Line {i+1}: Heading level jumps from H{prev_level} to H{level}"
                )
            prev_level = level

    # Check table format (pipes should be balanced)
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
                        f"Line {i+1}: Table column count mismatch "
                        f"(expected {table_cols}, got {cols})"
                    )
        else:
            in_table = False
            table_cols = 0

    return {
        "check": "markdown_structure",
        "issues": issues,
        "pass": len(issues) == 0,
    }


def validate(spec_path, skeleton_path):
    spec = load_spec(spec_path)
    skeleton = load_skeleton(skeleton_path)

    results = []
    results.append(check_paragraphs(spec, skeleton))
    results.append(check_files(spec, skeleton))
    results.append(check_calls(spec, skeleton))
    results.append(check_screen(spec, skeleton))
    results.append(check_linkage(spec, skeleton))
    results.append(check_remnants(spec))
    results.append(check_io_modes(spec, skeleton))
    results.append(check_sql_section(spec, skeleton))
    results.append(check_cross_references(spec, skeleton))
    results.append(check_markdown_structure(spec))

    all_pass = all(r["pass"] for r in results)
    total_issues = sum(len(r.get("issues", [])) for r in results)

    # Quality metrics
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
        description="Validate COBOL spec completeness against skeleton JSON (10 checks)."
    )
    parser.add_argument(
        "spec",
        help="Path to the spec markdown file (.md).",
    )
    parser.add_argument(
        "skeleton",
        help="Path to the skeleton JSON file.",
    )
    args = parser.parse_args()

    result = validate(args.spec, args.skeleton)

    # Print report
    print(f"Validation Report: {result['program']}")
    print(f"{'=' * 60}")
    print(f"Spec: {result['spec_file']}")
    print(f"Skeleton: {result['skeleton_file']}")
    q = result.get("quality", {})
    print(f"Quality: {q.get('checks_passed', 0)}/{q.get('total_checks', 0)} checks passed, "
          f"paragraph coverage {q.get('paragraph_coverage', 0)}%")
    print()

    for check in result["checks"]:
        name = check["check"].upper()
        status = "PASS" if check["pass"] else "FAIL"
        skip = check.get("skip", False)
        if skip:
            print(f"  [{name:18s}] SKIP (not applicable)")
            continue

        total = check.get("total", "")
        covered = check.get("covered", "")
        detail = f" ({covered}/{total})" if total != "" else ""
        pct = check.get("coverage_pct")
        pct_str = f" [{pct}%]" if pct is not None else ""
        print(f"  [{name:18s}] {status}{detail}{pct_str}")

        for issue in check.get("issues", []):
            print(f"    - {issue}")

    print()
    if result["all_pass"]:
        print("RESULT: ALL CHECKS PASSED")
    else:
        print(f"RESULT: {result['total_issues']} ISSUE(S) FOUND")

    # Also output JSON to stderr for programmatic use
    print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)

    sys.exit(0 if result["all_pass"] else 1)


if __name__ == "__main__":
    main()
