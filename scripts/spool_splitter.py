#!/usr/bin/env python3
"""Split AS/400 spool file into component inventory.

Parses COPY FILE or SEU SOURCE LISTING format spool files and identifies
DDS (PF/LF/DSPF), COBOL, and CL program boundaries.

Usage:
    python3 spool_splitter.py <spool_file>

Output: JSON inventory to stdout.
"""
import argparse
import json
import re
import sys
from os.path import basename


def parse_records(lines):
    """Extract (file_line, rcdnbr, content) tuples from raw lines."""
    # Detect format
    is_copy_file = any("COPY FILE" in l for l in lines[:20])
    is_seu = any("SEU SOURCE LISTING" in l for l in lines[:20])
    fmt = "COPY_FILE" if is_copy_file else "SEU_LISTING" if is_seu else "UNKNOWN"

    re_rec = re.compile(r"^\s+(\d+)\s{2,}(.*)$")
    re_skip = re.compile(
        r"^\s*(5770\w+\s+V\d+R\d+M\d+|"
        r"(RCDNBR|SEQNBR)\s*\*\.\.\.\+|"
        r"(From file|To file|Record length|Record format|SOURCE FILE|MEMBER)\s)"
    )

    records = []
    for i, raw in enumerate(lines):
        line = raw.rstrip()
        if not line.strip():
            continue
        if re_skip.match(line):
            continue
        if "E N D  O F  S O U R C E" in line:
            continue
        if "E N D   O F   C O M P U T E R" in line:
            continue
        if "records copied to member" in line:
            continue
        m = re_rec.match(line)
        if m:
            records.append((i + 1, int(m.group(1)), m.group(2)))
    return records, fmt


def find_program_starts(records):
    """Identify COBOL and CL program boundaries."""
    re_ident = re.compile(r"^\s*IDENTIFICATION\s+DIVISION", re.IGNORECASE)
    re_process = re.compile(r"^\s*PROCESS\s+.*GRAPHIC", re.IGNORECASE)
    re_pgmid = re.compile(r"^\s*PROGRAM-ID\.\s+(\w+)", re.IGNORECASE)
    re_cl_pgm = re.compile(r"^\s*PGM\b")
    re_cl_verify = re.compile(
        r"^\s*(DCL\w*|CHGVAR|CALLPRC|CALL\b|MONMSG|CHGDTAARA|RTVDTAARA|"
        r"SNDPGMMSG|RCVMSG|OVRDBF|DLTOVR|IF\b|ELSE\b|DO\b|ENDDO|"
        r"GOTO|CHGJOB|ADDLIBLE|RMVLIBLE|SBMJOB|RTVJOBA)\b"
    )

    starts = []  # (rec_idx, type, file_line, rcdnbr)

    i = 0
    while i < len(records):
        fl, rn, ct = records[i]

        # COBOL: IDENTIFICATION DIVISION
        if re_ident.match(ct):
            # Check if PROCESS GRAPHIC is the previous record
            start_idx = i
            if i > 0 and re_process.match(records[i - 1][2]):
                start_idx = i - 1
            starts.append((start_idx, "COBOL", records[start_idx][0], records[start_idx][1]))
            i += 1
            continue

        # CL: PGM keyword (only if NOT inside a COBOL program)
        if re_cl_pgm.match(ct):
            # Verify it's CL by checking subsequent lines
            is_cl = False
            for j in range(i + 1, min(i + 5, len(records))):
                if re_cl_verify.match(records[j][2]):
                    is_cl = True
                    break
            # Also accept bare PGM at end of file (driver programs)
            if not is_cl and ct.strip() == "PGM":
                is_cl = True
            if is_cl:
                starts.append((i, "CL", fl, rn))
            i += 1
            continue

        i += 1

    # Sort by record index
    starts.sort(key=lambda x: x[0])

    # Remove CL entries that fall within a COBOL range
    # (COBOL extends until the next program start)
    cleaned = []
    for s in starts:
        if s[1] == "CL":
            # Check if this CL is between a COBOL start and the next start
            # This shouldn't happen since we process sequentially, but be safe
            pass
        cleaned.append(s)

    return cleaned


def parse_dds_section(records, end_idx):
    """Parse DDS components from records[0..end_idx)."""
    re_rec_fmt = re.compile(r"^A\s+R\s+(\w+)")
    re_pfile = re.compile(r"PFILE\((\w+)\)")
    re_jfile = re.compile(r"JFILE\(([^)]+)\)")
    re_ref = re.compile(r"REF\((\w+)\)")
    re_key = re.compile(r"^A\s+K\s+(\w+)")
    re_unique = re.compile(r"\bUNIQUE\b")
    re_sfl = re.compile(r"\bSFL\b")
    re_sflctl = re.compile(r"SFLCTL\((\w+)\)")
    re_text = re.compile(r"TEXT\('([^']+)'\)")
    re_select = re.compile(r"^A\s+[SO]\s+(\w+)")
    re_dspsiz = re.compile(r"DSPSIZ\(")

    components = []
    current = None
    file_level_ref = None
    file_level_unique = False
    last_dspf_prefix = None

    for idx in range(end_idx):
        fl, rn, ct = records[idx]

        # File-level attributes (before first record format)
        if not current:
            rm = re_ref.search(ct)
            if rm:
                file_level_ref = rm.group(1)
            if re_unique.search(ct):
                file_level_unique = True
            if re_dspsiz.search(ct):
                # This is a DSPF file-level attribute
                pass

        # Record format start
        # Scan for TEXT on any line (not just record format lines)
        text_m_any = re_text.search(ct)
        if text_m_any and current and not current.get("text"):
            current["text"] = text_m_any.group(1).strip()

        m = re_rec_fmt.match(ct)
        if m:
            rec_name = m.group(1)
            pfile_m = re_pfile.search(ct)
            jfile_m = re_jfile.search(ct)
            is_sfl = bool(re_sfl.search(ct))
            is_sflctl = bool(re_sflctl.search(ct))
            text_m = re_text.search(ct)

            # Determine if this should merge with previous DSPF
            should_merge = False
            if current and current.get("is_dspf"):
                # Check if name shares prefix with DSPF
                dspf_base = current["record_formats"][0]
                if rec_name.startswith(dspf_base) or is_sflctl:
                    should_merge = True

            if should_merge:
                current["record_formats"].append(rec_name)
                continue

            # Close previous component
            if current:
                current["line_end"] = fl - 1
                current["rcdnbr_end"] = rn - 1
                components.append(current)

            # Determine type
            if jfile_m:
                ctype = "DDS_LF"
            elif pfile_m:
                ctype = "DDS_LF"
            elif is_sfl:
                ctype = "DDS_DSPF"
            else:
                ctype = "DDS_PF"

            # Parse JFILE targets
            jfile_targets = []
            if jfile_m:
                jfile_targets = [
                    t.strip() for t in jfile_m.group(1).split()
                    if t.strip()
                ]

            current = {
                "record_format": rec_name,
                "record_formats": [rec_name],
                "line_start": fl,
                "rcdnbr_start": rn,
                "line_end": None,
                "rcdnbr_end": None,
                "type": ctype,
                "keys": [],
                "unique": file_level_unique,
                "ref_file": file_level_ref,
                "pfile": pfile_m.group(1) if pfile_m else None,
                "jfile": jfile_targets if jfile_targets else None,
                "text": text_m.group(1).strip() if text_m else "",
                "is_dspf": is_sfl or is_sflctl,
            }
            # Reset file-level attributes for next component
            file_level_ref = None
            file_level_unique = False
            continue

        # Attributes within current component
        if current:
            km = re_key.match(ct)
            if km:
                current["keys"].append(km.group(1))
            if re_unique.search(ct) and "A*" not in ct:
                current["unique"] = True
            pm = re_pfile.search(ct)
            if pm and not current["pfile"]:
                current["pfile"] = pm.group(1)
                current["type"] = "DDS_LF"
            jm = re_jfile.search(ct)
            if jm and not current.get("jfile"):
                current["jfile"] = [
                    t.strip() for t in jm.group(1).split() if t.strip()
                ]
                current["type"] = "DDS_LF"
            rm = re_ref.search(ct)
            if rm and not current["ref_file"]:
                current["ref_file"] = rm.group(1)
            if re_sflctl.search(ct):
                current["is_dspf"] = True
                current["type"] = "DDS_DSPF"
            # DSPSIZ after a non-DSPF component means a new DSPF is starting
            # Close current and start tracking file-level attrs
            if re_dspsiz.search(ct) and not current.get("is_dspf"):
                current["line_end"] = fl - 1
                current["rcdnbr_end"] = rn - 1
                components.append(current)
                current = None
                file_level_unique = False
                file_level_ref = None
                # Don't continue - fall through to file-level tracking below
        if not current:
            # Before first record or between components, check for file-level attrs
            if re_unique.search(ct):
                file_level_unique = True
            rm = re_ref.search(ct)
            if rm:
                file_level_ref = rm.group(1)

    # Close last component
    if current:
        if end_idx > 0:
            current["line_end"] = records[end_idx - 1][0]
            current["rcdnbr_end"] = records[end_idx - 1][1]
        components.append(current)

    # Post-process: merge adjacent DSPF-related components
    merged = []
    dspf_group = None
    for comp in components:
        if comp["is_dspf"]:
            if dspf_group is None:
                dspf_group = comp
            else:
                dspf_group["record_formats"].extend(comp["record_formats"])
                dspf_group["line_end"] = comp["line_end"]
                dspf_group["rcdnbr_end"] = comp["rcdnbr_end"]
        else:
            # Check if this non-DSPF component should be merged with active DSPF
            # (e.g. M0062BTM follows M0062/M0062CTL)
            if dspf_group:
                base = dspf_group["record_formats"][0]
                if comp["record_format"].startswith(base):
                    dspf_group["record_formats"].extend(comp["record_formats"])
                    dspf_group["line_end"] = comp["line_end"]
                    dspf_group["rcdnbr_end"] = comp["rcdnbr_end"]
                    continue
                merged.append(dspf_group)
                dspf_group = None
            merged.append(comp)
    if dspf_group:
        merged.append(dspf_group)

    # Name components
    for comp in merged:
        rf = comp["record_format"]
        if comp["type"] == "DDS_LF":
            comp["name"] = "LFD" + rf
        elif comp["type"] == "DDS_PF":
            comp["name"] = "FFD" + rf
        elif comp["type"] == "DDS_DSPF":
            comp["name"] = rf

    return merged


def parse_spool(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    total_lines = len(lines)
    records, fmt = parse_records(lines)

    re_pgmid = re.compile(r"^\s*PROGRAM-ID\.\s+(\w+)", re.IGNORECASE)
    re_proc_div = re.compile(r"^\s*PROCEDURE\s+DIVISION", re.IGNORECASE)
    re_entry = re.compile(r"^\s*ENTRY\s+['\"](\w+)['\"]", re.IGNORECASE)

    # Find program boundaries
    prog_starts = find_program_starts(records)

    # DDS section: everything before first program
    first_prog_idx = prog_starts[0][0] if prog_starts else len(records)
    dds_comps = parse_dds_section(records, first_prog_idx)

    # Parse each program section
    all_components = []

    # Add DDS components
    for comp in dds_comps:
        entry = {
            "type": comp["type"],
            "name": comp["name"],
            "record_format": comp["record_format"],
            "line_start": comp["line_start"],
            "line_end": comp["line_end"],
        }
        if len(comp.get("record_formats", [])) > 1:
            entry["record_formats"] = comp["record_formats"]
        if comp.get("pfile"):
            entry["base_pf"] = comp["pfile"]
        if comp.get("jfile"):
            entry["jfile"] = comp["jfile"]
            entry["is_join"] = True
        if comp.get("keys"):
            entry["keys"] = comp["keys"]
        if comp.get("unique"):
            entry["unique"] = True
        if comp.get("ref_file"):
            entry["ref_file"] = comp["ref_file"]
        if comp.get("text"):
            entry["text"] = comp["text"]
        all_components.append(entry)

    # Parse program sections
    for pidx, (rec_idx, prog_type, start_line, start_rcdnbr) in enumerate(prog_starts):
        # End boundary
        if pidx + 1 < len(prog_starts):
            next_rec_idx = prog_starts[pidx + 1][0]
            end_line = prog_starts[pidx + 1][2] - 1
        else:
            end_line = records[-1][0] if records else total_lines
            next_rec_idx = len(records)

        if prog_type == "COBOL":
            # Find PROGRAM-ID
            pgm_name = "UNKNOWN"
            proc_div_line = None
            entry_points = []
            for j in range(rec_idx, min(rec_idx + 30, next_rec_idx)):
                fl, rn, ct = records[j]
                m = re_pgmid.match(ct)
                if m:
                    pgm_name = m.group(1).rstrip(".")
                    break

            # Find PROCEDURE DIVISION and ENTRY points
            for j in range(rec_idx, next_rec_idx):
                fl, rn, ct = records[j]
                if re_proc_div.match(ct):
                    proc_div_line = fl
                em = re_entry.match(ct)
                if em:
                    entry_points.append(em.group(1))

            entry = {
                "type": "COBOL_PROGRAM",
                "name": pgm_name,
                "line_start": start_line,
                "line_end": end_line,
            }
            if proc_div_line:
                entry["proc_div_line"] = proc_div_line
            if entry_points:
                entry["entry_points"] = entry_points
                entry["is_subprogram"] = True
            all_components.append(entry)

        elif prog_type == "CL":
            # Infer CL name from PGM label, ENDPGM label, or CALL PGM()
            cl_name = "UNKNOWN"
            re_pgm_label = re.compile(r"^\s*(\w+):\s+PGM\b")
            re_endpgm_label = re.compile(r"^\s*(\w+):\s+ENDPGM")
            re_cl_call = re.compile(r"CALL\s+PGM\((\w+)\)")
            re_sbmjob = re.compile(r"SBMJOB\s+CMD\(CALL\s+PGM\((\w+)\)")
            re_ovrdbf = re.compile(r"OVRDBF\s+FILE\((\w+)\)")

            cl_calls = []
            cl_overrides = []
            for j in range(rec_idx, min(next_rec_idx, rec_idx + 100)):
                fl, rn, ct = records[j]
                # PGM label at start
                pm = re_pgm_label.match(ct)
                if pm and cl_name == "UNKNOWN":
                    cl_name = pm.group(1)
                # ENDPGM label
                em = re_endpgm_label.match(ct)
                if em and cl_name == "UNKNOWN":
                    cl_name = em.group(1)
                # CALL PGM()
                cm = re_cl_call.search(ct)
                if cm:
                    cl_calls.append(cm.group(1))
                    if cl_name == "UNKNOWN":
                        cl_name = cm.group(1) + "CL"
                # SBMJOB CMD(CALL PGM())
                sm = re_sbmjob.search(ct)
                if sm:
                    cl_calls.append(sm.group(1))
                # OVRDBF
                om = re_ovrdbf.search(ct)
                if om:
                    cl_overrides.append(om.group(1))

            cl_entry = {
                "type": "CL_PROGRAM",
                "name": cl_name,
                "line_start": start_line,
                "line_end": end_line,
            }
            if cl_calls:
                cl_entry["calls"] = list(set(cl_calls))
            if cl_overrides:
                cl_entry["overrides"] = list(set(cl_overrides))
            all_components.append(cl_entry)

    # Sort by line_start
    all_components.sort(key=lambda x: x["line_start"])

    # Summary
    summary = {
        "dds_pf": sum(1 for c in all_components if c["type"] == "DDS_PF"),
        "dds_lf": sum(1 for c in all_components if c["type"] == "DDS_LF"),
        "dds_join_lf": sum(
            1 for c in all_components
            if c["type"] == "DDS_LF" and c.get("is_join")
        ),
        "dds_dspf": sum(1 for c in all_components if c["type"] == "DDS_DSPF"),
        "cobol": sum(1 for c in all_components if c["type"] == "COBOL_PROGRAM"),
        "cobol_subprograms": sum(
            1 for c in all_components
            if c["type"] == "COBOL_PROGRAM" and c.get("is_subprogram")
        ),
        "cl": sum(1 for c in all_components if c["type"] == "CL_PROGRAM"),
    }

    return {
        "spool_file": basename(path),
        "total_lines": total_lines,
        "total_records": len(records),
        "format": fmt,
        "summary": summary,
        "components": all_components,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Split AS/400 spool file into component inventory (JSON)."
    )
    parser.add_argument(
        "spool_file",
        help="Path to the spool file (COPY FILE or SEU SOURCE LISTING format).",
    )
    args = parser.parse_args()

    result = parse_spool(args.spool_file)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
