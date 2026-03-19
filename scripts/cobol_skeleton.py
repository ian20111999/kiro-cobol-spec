#!/usr/bin/env python3
"""Extract structural skeleton from a COBOL program in an AS/400 spool file.

Parses COPY FILE format spool files and produces a JSON skeleton containing
divisions, file definitions, paragraphs, calls, copy members, and key variables.

Usage:
    python3 cobol_skeleton.py <spool_file> [--program PROGNAME]

Output: JSON to stdout.
"""
import argparse
import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# Import spool_splitter from same directory
# ---------------------------------------------------------------------------
_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _script_dir)
from encoding import open_as400
try:
    from spool_splitter import parse_records, find_program_starts
except ImportError:
    # Fallback: define minimal helpers inline if spool_splitter is missing
    def parse_records(lines):
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
        return records, "COPY_FILE"

    find_program_starts = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Regex patterns compiled once
RE_IDENT_DIV = re.compile(r"IDENTIFICATION\s+DIVISION", re.IGNORECASE)
RE_PROGRAM_ID = re.compile(r"PROGRAM-ID\.\s+(\w+)", re.IGNORECASE)
RE_ENVIRON_DIV = re.compile(r"ENVIRONMENT\s+DIVISION", re.IGNORECASE)
RE_DATA_DIV = re.compile(r"DATA\s+DIVISION", re.IGNORECASE)
RE_PROC_DIV = re.compile(r"PROCEDURE\s+DIVISION", re.IGNORECASE)
RE_PROC_DIV_USING = re.compile(
    r"PROCEDURE\s+DIVISION\s+USING\s+([\w-]+)", re.IGNORECASE
)
RE_FILE_SECTION = re.compile(r"FILE\s+SECTION", re.IGNORECASE)
RE_WS_SECTION = re.compile(r"WORKING-STORAGE\s+SECTION", re.IGNORECASE)
RE_LINKAGE_SECTION = re.compile(r"LINKAGE\s+SECTION", re.IGNORECASE)

# SELECT statement
RE_SELECT = re.compile(
    r"SELECT\s+([\w-]+)\s+ASSIGN\s+TO\s+([\w-]+)", re.IGNORECASE
)
# ORGANIZATION
RE_ORGANIZATION = re.compile(r"ORGANIZATION\s+([\w]+)", re.IGNORECASE)
# ACCESS MODE
RE_ACCESS_MODE = re.compile(r"ACCESS\s+MODE\s+([\w]+)", re.IGNORECASE)
# FILE STATUS
RE_FILE_STATUS = re.compile(r"FILE\s+STATUS\s+([\w-]+)", re.IGNORECASE)
# FD entry
RE_FD = re.compile(r"FD\s+([\w-]+)", re.IGNORECASE)
# COPY member  (COPY name OF lib  or  COPY name.)
RE_COPY = re.compile(
    r"COPY\s+([\w-]+)\s+(?:OF\s+([\w-]+))?", re.IGNORECASE
)
RE_COPY_SIMPLE = re.compile(r"COPY\s+([\w-]+)\s*\.", re.IGNORECASE)
# CALL "program" USING ... (literal call)
RE_CALL = re.compile(r'CALL\s+["\'](\w+)["\']', re.IGNORECASE)
# CALL variable USING ... (dynamic call)
RE_CALL_DYNAMIC = re.compile(r'CALL\s+([A-Z][\w-]+)(?:\s+USING|\s*\.)', re.IGNORECASE)
# EXEC SQL ... END-EXEC
RE_EXEC_SQL = re.compile(r'EXEC\s+SQL', re.IGNORECASE)
RE_END_EXEC = re.compile(r'END-EXEC', re.IGNORECASE)
# COMMIT / ROLLBACK
RE_COMMIT = re.compile(r'\bCOMMIT\b', re.IGNORECASE)
RE_ROLLBACK = re.compile(r'\bROLLBACK\b', re.IGNORECASE)
# ACCEPT FROM DATE/TIME/DAY/DAY-OF-WEEK / DISPLAY UPON
RE_ACCEPT_FROM = re.compile(
    r'ACCEPT\s+([\w-]+)\s+FROM\s+(DATE|TIME|DAY(?:-OF-WEEK)?|LOCAL-DATA|COMMAND-LINE)',
    re.IGNORECASE,
)
RE_DISPLAY_UPON = re.compile(
    r'DISPLAY\s+.*?\s+UPON\s+([\w-]+)', re.IGNORECASE
)
# 88-level condition names
RE_88_LEVEL = re.compile(
    r'88\s+([\w-]+)\s+VALUE\s+(.*)', re.IGNORECASE
)
# REDEFINES
RE_REDEFINES = re.compile(
    r'(\d{2})\s+([\w-]+)\s+REDEFINES\s+([\w-]+)', re.IGNORECASE
)
# PERFORM THRU/THROUGH
RE_PERFORM_THRU = re.compile(
    r'PERFORM\s+([\w-]+)\s+(?:THRU|THROUGH)\s+([\w-]+)', re.IGNORECASE
)
# SPECIAL-NAMES LOCAL-DATA
RE_SPECIAL_NAMES = re.compile(r'SPECIAL-NAMES', re.IGNORECASE)
RE_LOCAL_DATA = re.compile(r'LOCAL-DATA', re.IGNORECASE)
# Level number + field name + PIC
RE_LEVEL_FIELD = re.compile(
    r"(\d{2})\s+([\w-]+)\s*(?:\.\s*$|.*?PIC\s+([\w()\.SV9X+-]+))",
    re.IGNORECASE,
)
RE_LEVEL_GROUP = re.compile(r"(\d{2})\s+([\w-]+)\s*\.\s*$", re.IGNORECASE)

# COBOL scope terminators and keywords that look like paragraph names but are not
SCOPE_TERMINATORS = frozenset({
    "END-IF", "END-READ", "END-WRITE", "END-REWRITE", "END-DELETE",
    "END-START", "END-EVALUATE", "END-PERFORM", "END-CALL", "END-SEARCH",
    "END-COMPUTE", "END-STRING", "END-UNSTRING", "END-ACCEPT",
    "END-DISPLAY", "END-MULTIPLY", "END-DIVIDE", "END-ADD",
    "END-SUBTRACT", "END-RETURN", "END-INVOKE",
})

COBOL_VERBS = frozenset({
    "GOBACK", "STOP", "EXIT", "FD", "SD", "COPY", "MOVE", "IF", "ELSE",
    "EVALUATE", "PERFORM", "READ", "WRITE", "REWRITE", "DELETE", "START",
    "OPEN", "CLOSE", "DISPLAY", "ACCEPT", "ADD", "SUBTRACT", "MULTIPLY",
    "DIVIDE", "COMPUTE", "CALL", "STRING", "UNSTRING", "SEARCH",
    "INITIALIZE", "SET", "CONTINUE", "RETURN", "INSPECT", "SORT",
    "MERGE", "RELEASE", "GENERATE", "INITIATE", "TERMINATE", "USE",
    "ALTER", "GO", "WHEN", "NOT", "ALSO", "THEN", "THRU", "THROUGH",
    "GIVING", "USING", "INTO", "FROM", "BY", "WITH", "ON", "AT",
    "AFTER", "BEFORE", "UNTIL", "VARYING", "LABEL", "RECORDS",
    "STANDARD", "OMITTED", "SECTION", "DIVISION", "PROCEDURE",
    "IDENTIFICATION", "ENVIRONMENT", "CONFIGURATION", "DATA",
    "WORKING-STORAGE", "LINKAGE", "FILE-CONTROL", "INPUT-OUTPUT",
    "SPECIAL-NAMES", "SOURCE-COMPUTER", "OBJECT-COMPUTER",
    "PROCESS", "GRAPHIC",
})


def clean_content(content):
    """Strip leading change/version markers from spool record content.

    AS/400 spool records may have leading date stamps (YYMMDD), version
    markers (V1.1), pipe chars for change bars, TESTOF markers, etc.

    Note: 'TESTOF*' means the line is a comment (the * is in column 7).
    We strip the 'TESTOF' marker but preserve the '*' comment indicator.
    """
    s = content
    # Strip leading spaces
    s = s.lstrip()
    # Handle TESTOF* specially: strip TESTOF but keep * (comment indicator)
    s = re.sub(r"^TESTOF(?=\*)", "", s)
    # Strip optional leading date (6 digits)
    s = re.sub(r"^\d{6}\s*", "", s)
    # Strip version markers like V1.1, V2.0, etc.
    s = re.sub(r"^V\d+\.\d+\s*", "", s)
    # Strip change bar pipes
    s = re.sub(r"^\|?\s*", "", s)
    # Strip XDXD markers
    s = re.sub(r"^XDXD\s*", "", s)
    return s.strip()


def is_comment(content):
    """Check if the content line is a COBOL comment.

    In AS/400 COBOL spool output, the content area may have:
    - A 6-digit date stamp or change marker (e.g., 050316, TESTOF, XDXD)
    - A version marker (e.g., V1.1)
    - A pipe char for change bars
    After these markers, column 7 may contain '*' indicating a comment.

    Special case: 'TESTOF*' means the marker is TESTOF and the * is the
    comment indicator in column 7.
    """
    cleaned = content.lstrip()

    # Check for TESTOF* specifically -- the * IS the comment indicator
    if re.match(r"^TESTOF\*", cleaned):
        return True

    # Remove date/version markers
    cleaned = re.sub(r"^\d{6}\s*", "", cleaned)
    cleaned = re.sub(r"^V\d+\.\d+\s*", "", cleaned)
    cleaned = re.sub(r"^\|?\s*", "", cleaned)
    cleaned = re.sub(r"^(?:XDXD)\s*", "", cleaned)
    return cleaned.startswith("*")


# ---------------------------------------------------------------------------
# Record slicing  --  find the range of records for a specific program
# ---------------------------------------------------------------------------

def find_program_range(records, program_name=None):
    """Return (start_idx, end_idx) in records[] for the target program.

    If program_name is None, returns the last COBOL program in the spool
    (which is typically the main program in multi-member spool files).
    """
    re_pgmid = re.compile(r"PROGRAM-ID\.\s+(\w+)", re.IGNORECASE)

    # Collect all COBOL program boundaries
    programs = []  # (start_idx, pgm_name)
    i = 0
    while i < len(records):
        fl, rn, ct = records[i]
        cleaned = clean_content(ct)
        if RE_IDENT_DIV.search(cleaned):
            # Look backwards for PROCESS GRAPHIC
            start_idx = i
            if i > 0 and re.search(r"PROCESS\s+.*GRAPHIC", clean_content(records[i-1][2]), re.IGNORECASE):
                start_idx = i - 1
            # Find PROGRAM-ID in next ~30 records
            pgm_name = "UNKNOWN"
            for j in range(i, min(i + 30, len(records))):
                m = re_pgmid.search(clean_content(records[j][2]))
                if m:
                    pgm_name = m.group(1).rstrip(".")
                    break
            programs.append((start_idx, pgm_name))
        i += 1

    if not programs:
        return 0, len(records)

    # Find target program
    target_idx = None
    if program_name:
        for idx, (start, name) in enumerate(programs):
            if name.upper() == program_name.upper():
                target_idx = idx
                break
        if target_idx is None:
            # Try partial match
            for idx, (start, name) in enumerate(programs):
                if program_name.upper() in name.upper() or name.upper() in program_name.upper():
                    target_idx = idx
                    break
        if target_idx is None:
            print(
                f"Warning: Program '{program_name}' not found. "
                f"Available: {[p[1] for p in programs]}. Using last program.",
                file=sys.stderr,
            )
            target_idx = len(programs) - 1
    else:
        # Default to last program (usually the main one)
        target_idx = len(programs) - 1

    start_rec_idx = programs[target_idx][0]
    if target_idx + 1 < len(programs):
        end_rec_idx = programs[target_idx + 1][0]
    else:
        end_rec_idx = len(records)

    return start_rec_idx, end_rec_idx


# ---------------------------------------------------------------------------
# Division boundary detection within a program's record range
# ---------------------------------------------------------------------------

def find_division_boundaries(records, start_idx, end_idx):
    """Return dict mapping division names to their record index ranges."""
    divs = {}
    div_order = []

    for i in range(start_idx, end_idx):
        fl, rn, ct = records[i]
        cleaned = clean_content(ct)
        if is_comment(ct):
            continue
        if RE_IDENT_DIV.search(cleaned):
            div_order.append(("IDENTIFICATION", i))
        elif RE_ENVIRON_DIV.search(cleaned):
            div_order.append(("ENVIRONMENT", i))
        elif RE_DATA_DIV.search(cleaned):
            div_order.append(("DATA", i))
        elif RE_PROC_DIV.search(cleaned):
            div_order.append(("PROCEDURE", i))

    for idx, (name, rec_i) in enumerate(div_order):
        next_i = div_order[idx + 1][1] if idx + 1 < len(div_order) else end_idx
        divs[name] = (rec_i, next_i)

    return divs


# ---------------------------------------------------------------------------
# Section boundary detection within DATA DIVISION
# ---------------------------------------------------------------------------

def find_data_sections(records, data_start, data_end):
    """Return dict mapping section names to record index ranges within DATA DIVISION."""
    sections = {}
    sec_order = []

    for i in range(data_start, data_end):
        fl, rn, ct = records[i]
        cleaned = clean_content(ct)
        if is_comment(ct):
            continue
        if RE_FILE_SECTION.search(cleaned):
            sec_order.append(("FILE", i))
        elif RE_WS_SECTION.search(cleaned):
            sec_order.append(("WORKING-STORAGE", i))
        elif RE_LINKAGE_SECTION.search(cleaned):
            sec_order.append(("LINKAGE", i))

    for idx, (name, rec_i) in enumerate(sec_order):
        next_i = sec_order[idx + 1][1] if idx + 1 < len(sec_order) else data_end
        sections[name] = (rec_i, next_i)

    return sections


# ---------------------------------------------------------------------------
# ENVIRONMENT DIVISION parsing  --  SELECT statements
# ---------------------------------------------------------------------------

def parse_select_statements(records, env_start, env_end):
    """Parse all SELECT ... ASSIGN TO statements and their continuations."""
    selects = []  # list of dict
    current = None

    for i in range(env_start, env_end):
        fl, rn, ct = records[i]
        cleaned = clean_content(ct)
        if is_comment(ct):
            continue

        # New SELECT statement
        m = RE_SELECT.search(cleaned)
        if m:
            if current:
                selects.append(current)
            fd_name = m.group(1)
            assign_target = m.group(2)
            current = {
                "fd_name": fd_name,
                "assign_target": assign_target,
                "organization": None,
                "access_mode": None,
                "file_status": None,
                "line": fl,
                "rcdnbr": rn,
            }
            # Parse device and file from assign target
            _parse_assign_target(current, assign_target)
            continue

        if current:
            # Continuation lines
            m_org = RE_ORGANIZATION.search(cleaned)
            if m_org:
                current["organization"] = m_org.group(1).upper()

            m_acc = RE_ACCESS_MODE.search(cleaned)
            if m_acc:
                current["access_mode"] = m_acc.group(1).upper()

            m_st = RE_FILE_STATUS.search(cleaned)
            if m_st:
                current["file_status"] = m_st.group(1)

    if current:
        selects.append(current)

    return selects


def _parse_assign_target(select_dict, target):
    """Parse device-file from ASSIGN TO target like DATABASE-LFDXXX or WORKSTATION-MFDYYY-SI."""
    parts = target.split("-", 1)
    if len(parts) >= 2:
        device = parts[0].upper()
        remainder = parts[1]
        select_dict["device"] = device
        # For WORKSTATION, the file might have -SI or -SN suffix
        if device == "WORKSTATION":
            # Remove format indicator suffix (-SI, -SN, etc.)
            file_name = re.sub(r"-(SI|SN|CI|CN)$", "", remainder, flags=re.IGNORECASE)
            select_dict["logical_file"] = file_name
        else:
            select_dict["logical_file"] = remainder
    else:
        select_dict["device"] = "UNKNOWN"
        select_dict["logical_file"] = target


# ---------------------------------------------------------------------------
# DATA DIVISION  --  FD entries
# ---------------------------------------------------------------------------

def parse_fd_entries(records, file_start, file_end):
    """Parse FD entries from FILE SECTION."""
    fds = []
    for i in range(file_start, file_end):
        fl, rn, ct = records[i]
        cleaned = clean_content(ct)
        if is_comment(ct):
            continue
        m = RE_FD.match(cleaned)
        if m:
            fds.append({"fd_name": m.group(1), "line": fl, "rcdnbr": rn})
    return fds


# ---------------------------------------------------------------------------
# COPY members
# ---------------------------------------------------------------------------

def extract_copy_members(records, start_idx, end_idx):
    """Extract all COPY member names (with library info) from a range of records."""
    members = []
    seen = set()
    for i in range(start_idx, end_idx):
        fl, rn, ct = records[i]
        cleaned = clean_content(ct)
        if is_comment(ct):
            continue
        # COPY name OF lib  or  COPY name.
        m = RE_COPY.search(cleaned)
        if m:
            member_name = m.group(1)
            library = m.group(2) if m.group(2) else None
            # Skip DD-* format references (these are DDS record format copies)
            if not member_name.upper().startswith("DD-"):
                if member_name not in seen:
                    if library:
                        members.append({"name": member_name, "library": library})
                    else:
                        # Try simple COPY name. match
                        members.append(member_name)
                    seen.add(member_name)
    return members


# ---------------------------------------------------------------------------
# LINKAGE SECTION fields
# ---------------------------------------------------------------------------

def parse_linkage_fields(records, link_start, link_end):
    """Parse field definitions from LINKAGE SECTION."""
    fields = []
    re_field = re.compile(
        r"(\d{2})\s+([\w-]+)\s+(.*)", re.IGNORECASE
    )
    re_pic = re.compile(r"PIC\s+([\w()\.SV9X+-]+)", re.IGNORECASE)

    for i in range(link_start, link_end):
        fl, rn, ct = records[i]
        cleaned = clean_content(ct)
        if is_comment(ct):
            continue

        m = re_field.match(cleaned)
        if m:
            level = m.group(1)
            name = m.group(2)
            rest = m.group(3)
            pic_m = re_pic.search(rest)
            if pic_m:
                pic = pic_m.group(1).rstrip(".")
            else:
                pic = "GROUP"
            fields.append({
                "level": level,
                "name": name,
                "pic": pic,
            })
            continue

        # Also match lines like: 01  LK-AREA.  (group level with period)
        m2 = RE_LEVEL_GROUP.match(cleaned)
        if m2:
            level = m2.group(1)
            name = m2.group(2)
            fields.append({
                "level": level,
                "name": name,
                "pic": "GROUP",
            })

    return fields


# ---------------------------------------------------------------------------
# WORKING-STORAGE key variables
# ---------------------------------------------------------------------------

def extract_key_variables(records, ws_start, ws_end):
    """Extract switches, counters, work tables, 88-levels, and REDEFINES from WORKING-STORAGE."""
    switches = []
    counters = []
    work_tables = []
    condition_names = []   # 88-level
    redefines = []         # REDEFINES
    seen_sw = set()
    seen_ct = set()
    seen_wt = set()

    re_field_def = re.compile(
        r"(\d{2})\s+([\w-]+)", re.IGNORECASE
    )
    re_occurs = re.compile(r"OCCURS\s+(\d+)", re.IGNORECASE)
    re_pic = re.compile(r"PIC\s+([\w()\.SV9X+-]+)", re.IGNORECASE)

    last_parent_field = None

    for i in range(ws_start, ws_end):
        fl, rn, ct = records[i]
        cleaned = clean_content(ct)
        if is_comment(ct):
            continue

        m = re_field_def.match(cleaned)
        if not m:
            continue

        level = m.group(1)
        name = m.group(2)

        # 88-level condition names
        if level == "88":
            m88 = RE_88_LEVEL.match(cleaned)
            if m88:
                condition_names.append({
                    "name": m88.group(1),
                    "values": m88.group(2).rstrip(".").strip(),
                    "parent": last_parent_field,
                })
            continue

        # REDEFINES
        m_redef = RE_REDEFINES.match(cleaned)
        if m_redef:
            redefines.append({
                "level": m_redef.group(1),
                "name": m_redef.group(2),
                "redefines": m_redef.group(3),
            })

        # Track parent field for 88-level
        if level != "88":
            last_parent_field = name

        # Work tables with OCCURS
        occ_m = re_occurs.search(cleaned)
        if occ_m and level in ("01", "05"):
            desc = f"{name} OCCURS {occ_m.group(1)}"
            if desc not in seen_wt:
                work_tables.append(desc)
                seen_wt.add(desc)
            continue

        # Switches: names starting with SW-
        if name.upper().startswith("SW-"):
            if name not in seen_sw:
                switches.append(name)
                seen_sw.add(name)
            continue

        # Status/counter variables: names starting with ST-
        if name.upper().startswith("ST-") and level != "01":
            if name not in seen_ct:
                counters.append(name)
                seen_ct.add(name)
            continue

    return {
        "switches": switches,
        "counters": counters,
        "work_tables": work_tables,
        "condition_names_88": condition_names,
        "redefines": redefines,
    }


# ---------------------------------------------------------------------------
# PROCEDURE DIVISION parsing
# ---------------------------------------------------------------------------

def is_paragraph_name(name):
    """Check if a cleaned token is a valid COBOL paragraph name (not a scope terminator or verb)."""
    upper = name.upper()
    if upper in SCOPE_TERMINATORS:
        return False
    if upper in COBOL_VERBS:
        return False
    # Must contain at least one letter
    if not re.search(r"[A-Z]", upper):
        return False
    # Reject if it looks like a data name used in MOVE target context
    # Valid paragraph names typically have a numeric prefix or are well-structured
    # We accept: NNNN-name patterns, and other alphanumeric names that end with
    # common suffixes like -S, -RTN, -EXIT, etc.
    return True


def classify_paragraph_group(name):
    """Classify paragraph into a group based on its numeric/alphanumeric prefix.

    COBOL paragraph names in AS/400 programs often use a numbering scheme:
    0xxx/1xxx = INIT, 2xxx = READ, 3xxx-4xxx = MAIN, 5xxx = END, 9xxx = ERROR.
    Some programs use hex-style prefixes like 3C00, 3D00, 3E00, 3F00 which
    should be treated as MAIN group (they extend the 3xxx range).
    """
    # Try to extract leading alphanumeric prefix before the first hyphen
    m = re.match(r"([0-9A-Fa-f]+)-", name)
    if not m:
        # Try just leading digits
        m = re.match(r"(\d+)", name)
        if not m:
            return "OTHER"

    prefix_str = m.group(1)

    # Try parsing as a pure integer first
    try:
        prefix = int(prefix_str)
    except ValueError:
        # Hex-style prefix like "3C00", "3D10", "3E00", "3F00"
        # Use the first digit to determine the group
        first_digit = int(prefix_str[0])
        if first_digit <= 1:
            return "INIT"
        elif first_digit == 2:
            return "READ"
        elif first_digit <= 4:
            return "MAIN"
        elif first_digit == 5:
            return "END"
        elif first_digit >= 9:
            return "ERROR"
        return "OTHER"

    if prefix < 2000:
        return "INIT"
    elif prefix < 3000:
        return "READ"
    elif prefix < 5000:
        return "MAIN"
    elif prefix < 6000:
        return "END"
    elif prefix >= 9000:
        return "ERROR"
    else:
        return "OTHER"


def parse_procedure_division(records, proc_start, proc_end):
    """Parse paragraphs, CALLs, SQL, COMMIT/ROLLBACK, ACCEPT FROM, PERFORM THRU
    from PROCEDURE DIVISION.

    A key challenge is distinguishing paragraph names from continuation lines.
    In COBOL, a paragraph name appears at margin A (columns 8-11) as a word
    followed by a period. However, continuation lines for multi-line statements
    (MOVE ... TO ... target., CALL ... USING ... arg., CLOSE file1 file2 file3.)
    can also appear as a single word + period.

    The critical heuristic: a paragraph name can only appear when the previous
    non-comment, non-blank record ended the prior statement (ended with a period).
    If the previous statement was not yet terminated, this line is a continuation.
    """
    paragraphs = []
    calls = []
    sql_statements = []
    commit_rollback = []
    accept_from_list = []
    perform_thru_list = []

    # Current paragraph context for associating CALLs
    current_para = None

    # Track whether the previous statement was complete
    prev_statement_ended = True  # Start of PROCEDURE DIVISION is a boundary

    # EXEC SQL multi-line accumulation
    in_exec_sql = False
    sql_buffer = ""
    sql_start_line = None

    for i in range(proc_start, proc_end):
        fl, rn, ct = records[i]
        cleaned = clean_content(ct)

        if is_comment(ct):
            continue

        # Skip blank/empty content lines
        if not cleaned:
            continue

        # Skip COBOL page eject directive (/ in column 7 area)
        if cleaned == "/":
            continue

        # --- EXEC SQL detection (multi-line) ---
        if RE_EXEC_SQL.search(cleaned):
            in_exec_sql = True
            sql_buffer = cleaned
            sql_start_line = fl
            # Check if END-EXEC on same line
            if RE_END_EXEC.search(cleaned):
                in_exec_sql = False
                sql_type = _classify_sql(sql_buffer)
                sql_statements.append({
                    "type": sql_type,
                    "line": sql_start_line,
                    "paragraph": current_para,
                })
                sql_buffer = ""
            continue
        if in_exec_sql:
            sql_buffer += " " + cleaned
            if RE_END_EXEC.search(cleaned):
                in_exec_sql = False
                sql_type = _classify_sql(sql_buffer)
                sql_statements.append({
                    "type": sql_type,
                    "line": sql_start_line,
                    "paragraph": current_para,
                })
                sql_buffer = ""
            continue

        # Detect paragraph names:
        para_m = re.match(r"^([A-Z0-9][\w-]+)\s*\.\s*$", cleaned, re.IGNORECASE)
        if para_m and prev_statement_ended:
            name = para_m.group(1)
            if is_paragraph_name(name):
                has_structured_prefix = bool(
                    re.match(r"[0-9][0-9A-Fa-f]{0,3}-", name)
                )
                if has_structured_prefix:
                    para_entry = {
                        "name": name,
                        "line": fl,
                        "rcdnbr": rn,
                        "group": classify_paragraph_group(name),
                    }
                    paragraphs.append(para_entry)
                    current_para = name

        # Detect CALL statements (literal)
        call_m = RE_CALL.search(cleaned)
        if call_m:
            target = call_m.group(1)
            call_entry = {
                "target": target,
                "line": fl,
                "rcdnbr": rn,
                "call_type": "literal",
            }
            if current_para:
                call_entry["paragraph"] = current_para
            calls.append(call_entry)
        else:
            # Detect dynamic CALL (CALL variable)
            dyn_m = RE_CALL_DYNAMIC.search(cleaned)
            if dyn_m:
                var_name = dyn_m.group(1)
                # Exclude known COBOL keywords that might match
                if var_name.upper() not in COBOL_VERBS and var_name.upper() not in SCOPE_TERMINATORS:
                    call_entry = {
                        "target": var_name,
                        "line": fl,
                        "rcdnbr": rn,
                        "call_type": "dynamic",
                    }
                    if current_para:
                        call_entry["paragraph"] = current_para
                    calls.append(call_entry)

        # Detect COMMIT/ROLLBACK
        if RE_COMMIT.search(cleaned) and not RE_EXEC_SQL.search(cleaned):
            commit_rollback.append({
                "type": "COMMIT",
                "line": fl,
                "paragraph": current_para,
            })
        if RE_ROLLBACK.search(cleaned) and not RE_EXEC_SQL.search(cleaned):
            commit_rollback.append({
                "type": "ROLLBACK",
                "line": fl,
                "paragraph": current_para,
            })

        # Detect ACCEPT FROM
        acc_m = RE_ACCEPT_FROM.search(cleaned)
        if acc_m:
            accept_from_list.append({
                "target_var": acc_m.group(1),
                "source": acc_m.group(2).upper(),
                "line": fl,
                "paragraph": current_para,
            })

        # Detect PERFORM THRU/THROUGH
        thru_m = RE_PERFORM_THRU.search(cleaned)
        if thru_m:
            perform_thru_list.append({
                "from": thru_m.group(1),
                "to": thru_m.group(2),
                "line": fl,
                "paragraph": current_para,
            })

        # Update statement termination tracking
        stripped = cleaned.rstrip()
        prev_statement_ended = stripped.endswith(".")

    return {
        "paragraphs": paragraphs,
        "calls": calls,
        "sql_statements": sql_statements,
        "commit_rollback": commit_rollback,
        "accept_from": accept_from_list,
        "perform_thru": perform_thru_list,
    }


def _classify_sql(sql_text):
    """Classify an EXEC SQL block by its SQL statement type."""
    upper = sql_text.upper()
    if "DECLARE" in upper and "CURSOR" in upper:
        return "DECLARE CURSOR"
    if "OPEN" in upper:
        # Distinguish SQL OPEN (cursor) from COBOL OPEN (file)
        if "EXEC" in upper:
            return "OPEN CURSOR"
    if "FETCH" in upper:
        return "FETCH"
    if "CLOSE" in upper:
        return "CLOSE CURSOR"
    if "INSERT" in upper:
        return "INSERT"
    if "UPDATE" in upper:
        return "UPDATE"
    if "DELETE" in upper:
        return "DELETE"
    if "SELECT" in upper:
        if "INTO" in upper:
            return "SELECT INTO"
        return "SELECT"
    if "COMMIT" in upper:
        return "COMMIT"
    if "ROLLBACK" in upper:
        return "ROLLBACK"
    if "INCLUDE" in upper:
        return "INCLUDE"
    return "OTHER"


# ---------------------------------------------------------------------------
# Display file detection
# ---------------------------------------------------------------------------

def detect_display_file(selects, records, data_start, data_end):
    """Detect the display file (WORKSTATION) and its record formats."""
    display = None
    for sel in selects:
        if sel.get("device", "").upper() == "WORKSTATION":
            display = {
                "name": sel["logical_file"],
                "fd_name": sel["fd_name"],
                "record_formats": [],
            }
            break

    if not display:
        return None

    # Find record formats by scanning for COPY DD-formatname-O OF displayfile
    re_dd_copy = re.compile(
        r"COPY\s+DD-([\w]+)-[OI]\w*\s+OF\s+" + re.escape(display["name"]),
        re.IGNORECASE,
    )
    seen_formats = set()
    for i in range(data_start, data_end):
        fl, rn, ct = records[i]
        cleaned = clean_content(ct)
        if is_comment(ct):
            continue
        m = re_dd_copy.search(cleaned)
        if m:
            fmt = m.group(1)
            if fmt not in seen_formats:
                display["record_formats"].append(fmt)
                seen_formats.add(fmt)

    # If no COPY DD- found, try to infer from FD 01 records or WS COPY
    if not display["record_formats"]:
        # Look for record format names derived from the display file name
        base = display["name"].replace("MFD", "M").replace("DFD", "D")
        # Generic search
        re_fmt = re.compile(r"DD-(" + re.escape(base[:4]) + r"\w+)-", re.IGNORECASE)
        for i in range(data_start, data_end):
            fl, rn, ct = records[i]
            cleaned = clean_content(ct)
            m = re_fmt.search(cleaned)
            if m:
                fmt = m.group(1)
                if fmt not in seen_formats:
                    display["record_formats"].append(fmt)
                    seen_formats.add(fmt)

    return display


# ---------------------------------------------------------------------------
# Determine program type
# ---------------------------------------------------------------------------

def determine_program_type(selects, has_linkage, has_main_loop, proc_using):
    """Determine program type: INTERACTIVE, BATCH, REPORT, SUBPROGRAM."""
    has_workstation = any(
        s.get("device", "").upper() == "WORKSTATION" for s in selects
    )
    has_printer = any(
        s.get("device", "").upper() == "PRINTER" for s in selects
    )

    evidence = ""

    if has_workstation:
        for s in selects:
            if s.get("device", "").upper() == "WORKSTATION":
                evidence = f"SELECT {s['fd_name']} ASSIGN TO {s['assign_target']}"
                break
        return "INTERACTIVE", evidence

    if has_linkage and proc_using and not has_main_loop:
        evidence = f"PROCEDURE DIVISION USING {proc_using}"
        return "SUBPROGRAM", evidence

    if has_linkage and proc_using:
        evidence = f"PROCEDURE DIVISION USING {proc_using}"
        # If it has a main loop, it's likely a subprogram that loops internally
        return "SUBPROGRAM", evidence

    if has_printer:
        for s in selects:
            if s.get("device", "").upper() == "PRINTER":
                evidence = f"SELECT {s['fd_name']} ASSIGN TO {s['assign_target']}"
                break
        return "REPORT", evidence

    # Default: BATCH
    evidence = "No WORKSTATION or PRINTER file; default classification"
    return "BATCH", evidence


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

def extract_skeleton(spool_path, program_name=None):
    """Extract the structural skeleton of a COBOL program from a spool file."""
    with open_as400(spool_path) as f:
        lines = f.readlines()

    records, fmt = parse_records(lines)

    if not records:
        return {"error": "No records found in spool file"}

    # Find target program range
    start_idx, end_idx = find_program_range(records, program_name)

    # Identify the COBOL program name from PROGRAM-ID paragraph
    # "program" = COBOL program name from PROGRAM-ID
    # "program_id" = spool/job identifier (derived from header comments or filename)
    program = None
    program_id = None
    for i in range(start_idx, min(start_idx + 50, end_idx)):
        fl, rn, ct = records[i]
        cleaned = clean_content(ct)
        m = RE_PROGRAM_ID.search(cleaned)
        if m:
            program = m.group(1).rstrip(".")
            break

    if not program:
        program = program_name

    # program_id is derived from spool file name or header comments
    spool_base = os.path.splitext(os.path.basename(spool_path))[0]

    # Look for program_id in header comments using common AS/400 patterns:
    #   程式名稱 : XXXX, 程式代號 : XXXX, PROGRAM : XXXX, PGM-ID : XXXX, etc.
    re_pgm_label = re.compile(
        r"(?:程式[名代][稱號]|PGM[\s-]*ID|PROGRAM)\s*[:=：]\s*([A-Z0-9][A-Z0-9_-]{2,})",
        re.IGNORECASE,
    )
    for i in range(start_idx, min(start_idx + 80, end_idx)):
        fl, rn, ct = records[i]
        cleaned = clean_content(ct)
        if is_comment(ct):
            m = re_pgm_label.search(cleaned)
            if m:
                program_id = m.group(1).strip()
                break

    if not program_id:
        program_id = spool_base

    # Find division boundaries
    divs = find_division_boundaries(records, start_idx, end_idx)

    # ---- ENVIRONMENT DIVISION ----
    selects = []
    if "ENVIRONMENT" in divs:
        env_s, env_e = divs["ENVIRONMENT"]
        selects = parse_select_statements(records, env_s, env_e)

    # ---- DATA DIVISION ----
    files_info = []
    copy_members = []
    linkage_fields = []
    key_vars = {"switches": [], "counters": [], "work_tables": []}
    display_file = None
    has_linkage = False

    if "DATA" in divs:
        data_s, data_e = divs["DATA"]
        sections = find_data_sections(records, data_s, data_e)

        # FILE SECTION: FD entries
        if "FILE" in sections:
            fs_s, fs_e = sections["FILE"]
            fd_entries = parse_fd_entries(records, fs_s, fs_e)

        # WORKING-STORAGE
        if "WORKING-STORAGE" in sections:
            ws_s, ws_e = sections["WORKING-STORAGE"]
            key_vars = extract_key_variables(records, ws_s, ws_e)

        # LINKAGE SECTION
        if "LINKAGE" in sections:
            has_linkage = True
            lk_s, lk_e = sections["LINKAGE"]
            linkage_fields = parse_linkage_fields(records, lk_s, lk_e)

        # COPY members from entire DATA DIVISION
        copy_members = extract_copy_members(records, data_s, data_e)

        # Also collect COPY members from ENVIRONMENT and PROCEDURE divisions
        if "ENVIRONMENT" in divs:
            env_s, env_e = divs["ENVIRONMENT"]
            env_copies = extract_copy_members(records, env_s, env_e)
            seen = set(copy_members)
            for c in env_copies:
                if c not in seen:
                    copy_members.append(c)
                    seen.add(c)

        # Display file detection
        display_file = detect_display_file(selects, records, data_s, data_e)

    # Also collect COPY members from PROCEDURE DIVISION
    if "PROCEDURE" in divs:
        proc_s, proc_e = divs["PROCEDURE"]
        proc_copies = extract_copy_members(records, proc_s, proc_e)
        seen = set(copy_members)
        for c in proc_copies:
            if c not in seen:
                copy_members.append(c)
                seen.add(c)

    # ---- Build file details by merging SELECT + FD + OPEN info ----
    files_info = _build_file_details(selects, records, start_idx, end_idx)

    # ---- ENVIRONMENT DIVISION: SPECIAL-NAMES LOCAL-DATA detection ----
    has_local_data = False
    special_names_info = {}
    if "ENVIRONMENT" in divs:
        env_s, env_e = divs["ENVIRONMENT"]
        for i in range(env_s, env_e):
            fl_e, rn_e, ct_e = records[i]
            cleaned_e = clean_content(ct_e)
            if is_comment(ct_e):
                continue
            if RE_LOCAL_DATA.search(cleaned_e):
                has_local_data = True
            if RE_SPECIAL_NAMES.search(cleaned_e):
                special_names_info["line"] = fl_e

    # ---- PROCEDURE DIVISION ----
    paragraphs = []
    calls = []
    sql_statements = []
    commit_rollback = []
    accept_from_list = []
    perform_thru_list = []
    proc_using = None
    has_main_loop = False

    if "PROCEDURE" in divs:
        proc_s, proc_e = divs["PROCEDURE"]

        # Check PROCEDURE DIVISION USING
        fl, rn, ct = records[proc_s]
        cleaned = clean_content(ct)
        m_using = RE_PROC_DIV_USING.search(cleaned)
        if m_using:
            proc_using = m_using.group(1)

        # Detect main PERFORM loop (PERFORM xxxx UNTIL SW-EOJ)
        for i in range(proc_s, min(proc_s + 30, proc_e)):
            fl2, rn2, ct2 = records[i]
            cleaned2 = clean_content(ct2)
            if re.search(r"UNTIL\s+SW-EOJ", cleaned2, re.IGNORECASE):
                has_main_loop = True
                break

        proc_result = parse_procedure_division(records, proc_s, proc_e)
        paragraphs = proc_result["paragraphs"]
        calls = proc_result["calls"]
        sql_statements = proc_result["sql_statements"]
        commit_rollback = proc_result["commit_rollback"]
        accept_from_list = proc_result["accept_from"]
        perform_thru_list = proc_result["perform_thru"]

    # ---- Determine program type ----
    prog_type, type_evidence = determine_program_type(
        selects, has_linkage, has_main_loop, proc_using
    )

    # ---- Build result ----
    result = {
        "program": program,
        "program_id": program_id,
        "type": prog_type,
        "type_evidence": type_evidence,
        "files": files_info,
    }

    if display_file:
        result["display_file"] = display_file

    if has_linkage:
        linkage_data = {}
        if proc_using:
            linkage_data["using"] = proc_using
        if linkage_fields:
            linkage_data["fields"] = linkage_fields
        result["linkage"] = linkage_data

    result["paragraphs"] = [
        {"name": p["name"], "line": p["line"], "group": p["group"]}
        for p in paragraphs
    ]

    # Deduplicate calls by (target, line)
    seen_calls = set()
    unique_calls = []
    for c in calls:
        key = (c["target"], c["line"])
        if key not in seen_calls:
            unique_calls.append(c)
            seen_calls.add(key)
    result["calls"] = [
        {
            "target": c["target"],
            "line": c["line"],
            "call_type": c.get("call_type", "literal"),
            **({"paragraph": c["paragraph"]} if "paragraph" in c else {}),
        }
        for c in unique_calls
    ]

    result["copy_members"] = copy_members
    result["key_variables"] = key_vars

    # ---- New: SQL statements ----
    if sql_statements:
        result["sql_statements"] = sql_statements

    # ---- New: COMMIT/ROLLBACK (transaction boundaries) ----
    if commit_rollback:
        result["commit_rollback"] = commit_rollback

    # ---- New: ACCEPT FROM (system date/time/LDA) ----
    if accept_from_list:
        result["accept_from"] = accept_from_list

    # ---- New: PERFORM THRU ----
    if perform_thru_list:
        result["perform_thru"] = perform_thru_list

    # ---- New: SPECIAL-NAMES / LOCAL-DATA ----
    if has_local_data:
        result["has_local_data"] = True

    return result


def _build_file_details(selects, records, start_idx, end_idx):
    """Merge SELECT, FD, and OPEN information into file detail records."""
    # Build IO mode map from OPEN statements
    io_modes = {}
    re_open = re.compile(r"OPEN\s+(INPUT|OUTPUT|I-O|EXTEND)", re.IGNORECASE)

    i = start_idx
    while i < end_idx:
        fl, rn, ct = records[i]
        cleaned = clean_content(ct)
        if is_comment(ct):
            i += 1
            continue

        m = re_open.search(cleaned)
        if m:
            mode = m.group(1).upper()
            # The files follow the OPEN mode keyword, possibly spanning multiple lines
            # Extract all file names from this and continuation lines
            text = cleaned[m.end():]
            # Gather continuation lines
            j = i + 1
            while j < end_idx:
                fl2, rn2, ct2 = records[j]
                cleaned2 = clean_content(ct2)
                if is_comment(ct2):
                    j += 1
                    continue
                # Check if this is a continuation (doesn't start a new statement)
                if re.match(r"^(OPEN|CLOSE|READ|WRITE|PERFORM|MOVE|IF|EVALUATE|CALL|DISPLAY|ACCEPT|GOBACK|STOP|EXIT|ADD|SUBTRACT|MULTIPLY|DIVIDE|COMPUTE|STRING|UNSTRING|SEARCH|INITIALIZE|SET|INSPECT|GO|ALTER|\d{4}-)", cleaned2, re.IGNORECASE):
                    break
                # Also break if it looks like a new OPEN
                if re_open.search(cleaned2):
                    break
                text += " " + cleaned2
                j += 1

            # Parse file names from the aggregated text
            # Remove period at end
            text = text.rstrip().rstrip(".")
            file_names = re.findall(r"\b([A-Z][\w-]+)\b", text, re.IGNORECASE)
            for fn in file_names:
                fn_upper = fn.upper()
                # Skip COBOL keywords
                if fn_upper in ("INPUT", "OUTPUT", "I-O", "EXTEND", "ARE",
                                "STANDARD", "OMITTED", "LABEL", "RECORDS",
                                "WITH", "LOCK", "NO", "REWIND"):
                    continue
                io_modes[fn_upper] = mode

        i += 1

    # Build file info list from SELECT statements
    files = []
    for sel in selects:
        fd_name = sel["fd_name"]
        logical_file = sel.get("logical_file", "")
        device = sel.get("device", "DATABASE")

        # Determine physical file (for DATABASE files, logical_file is the AS/400 file)
        physical_file = None  # We don't track PF separately here

        io_mode = io_modes.get(fd_name.upper(), "INPUT")
        status_var = sel.get("file_status")

        file_entry = {
            "fd_name": fd_name,
            "logical_file": logical_file,
            "physical_file": physical_file,
            "io_mode": io_mode,
        }

        if status_var:
            file_entry["status_var"] = status_var

        if sel.get("organization"):
            file_entry["organization"] = sel["organization"]

        if sel.get("access_mode"):
            file_entry["access_mode"] = sel["access_mode"]

        files.append(file_entry)

    return files


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract COBOL program skeleton from AS/400 spool file."
    )
    parser.add_argument(
        "spool_file",
        help="Path to the spool file (COPY FILE format).",
    )
    parser.add_argument(
        "--program",
        default=None,
        help="Target program name (PROGRAM-ID value). "
             "Defaults to last COBOL program in the spool.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        default=True,
        help="Pretty-print JSON output (default: True).",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Compact JSON output (no indentation).",
    )

    args = parser.parse_args()

    if not os.path.isfile(args.spool_file):
        print(f"Error: File not found: {args.spool_file}", file=sys.stderr)
        sys.exit(1)

    result = extract_skeleton(args.spool_file, args.program)

    indent = None if args.compact else 2
    print(json.dumps(result, indent=indent, ensure_ascii=False))


if __name__ == "__main__":
    main()
