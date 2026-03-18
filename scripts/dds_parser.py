#!/usr/bin/env python3
"""
DDS (Data Description Specification) Parser for AS/400 source files.

Parses two source formats:
  1. SEU SOURCE LISTING (.txt files from WRKMBRPDM / DSPPFM)
  2. COPY FILE spool output (embedded DDS in spool files)

Outputs field definitions as JSON to stdout.

Usage:
  python3 dds_parser.py <dds_file>                              # physical/logical file
  python3 dds_parser.py <dds_file> --dspf                       # display file
  python3 dds_parser.py <spool_file> --spool --start N --end M  # DDS section in spool
"""

import argparse
import json
import os
import re
import sys


# ---------------------------------------------------------------------------
# Constants: DDS column positions (1-based) and their 0-based index offset
# within an 80-column DDS source record.
#
#   DDS Col  Purpose                   Width
#   -------  -------                   -----
#   1-5      Not used / sequence       5
#   6        Form type (always 'A')    1
#   7        Comment ('*') / Not used  1
#   7-16     Condition indicators      10 (overlaps col 7)
#   17       Name type (R/K/S/O/' ')   1
#   18       Reserved                  1
#   19-28    Name                      10
#   29       Reference indicator (R)   1
#   30-34    Length                     5
#   35       Data type (A/P/S/B/Y/O)   1
#   36-37    Decimal positions          2
#   38       Usage (DSPF: B/I/O/H/P)   1
#   39-41    Line/Row (DSPF)            3
#   42-44    Position/Col (DSPF)        3
#   45-80    Keywords/Functions         36
# ---------------------------------------------------------------------------

# In a DDS 80-column record (0-based indexing):
#   index 0-4  = cols 1-5   (not used)
#   index 5    = col 6      (form type)
#   index 6    = col 7      (comment)
#   index 6-15 = cols 7-16  (condition indicators area)
#   index 16   = col 17     (name type)
#   index 17   = col 18     (reserved)
#   index 18-27 = cols 19-28 (name, 10 chars)
#   index 28   = col 29     (reference indicator)
#   index 29-33 = cols 30-34 (length, 5 chars)
#   index 34   = col 35     (data type)
#   index 35-36 = cols 36-37 (decimal positions)
#   index 37   = col 38     (usage for DSPF)
#   index 38-40 = cols 39-41 (row for DSPF)
#   index 41-43 = cols 42-44 (col for DSPF)
#   index 44+  = cols 45+   (keywords)

# Offsets within the 80-column DDS record (0-based)
_O_FORMTYPE = 5
_O_COMMENT = 6
_O_IND_START = 6
_O_IND_END = 16   # exclusive
_O_NAMETYPE = 16
_O_NAME_START = 18
_O_NAME_END = 28   # exclusive
_O_REF = 28
_O_LEN_START = 29
_O_LEN_END = 34    # exclusive
_O_DTYPE = 34
_O_DEC_START = 35
_O_DEC_END = 37    # exclusive
_O_USAGE = 37      # DSPF only
_O_ROW_START = 38  # DSPF only
_O_ROW_END = 41    # exclusive
_O_COL_START = 41  # DSPF only
_O_COL_END = 44    # exclusive
_O_KW_START = 44   # keywords start


# ---------------------------------------------------------------------------
# Format detection and line extraction
# ---------------------------------------------------------------------------

def _is_skip_line(line: str) -> bool:
    """Return True if this line is a header/ruler/blank that should be skipped."""
    s = line.strip()
    if not s:
        return True
    if 'SEU SOURCE LISTING' in line:
        return True
    if 'SOURCE FILE' in line and '. . .' in line:
        return True
    if 'MEMBER' in line and '. . .' in line:
        return True
    if 'SEQNBR*' in line:
        return True
    # Match the RCDNBR ruler line but not SFLRCDNBR keyword
    if re.search(r'(?<!\w)RCDNBR(?!\w)', line) and 'SFL' not in line:
        return True
    if 'E N D  O F  S O U R C E' in line:
        return True
    if s.startswith('5770WDS') or s.startswith('5770SS1'):
        return True
    if 'COPY FILE' in line:
        return True
    if re.match(r'^From file|^To file|^Record length', s):
        return True
    return False


def _detect_format(lines: list[str]) -> str:
    """Detect whether the file is SEU SOURCE LISTING or COPY FILE spool."""
    for line in lines[:20]:
        if 'SEU SOURCE LISTING' in line:
            return 'seu'
        if 'COPY FILE' in line:
            return 'spool'
    for line in lines[:20]:
        if 'RCDNBR' in line:
            return 'spool'
        if 'SEQNBR' in line:
            return 'seu'
    return 'seu'


def _find_dds_start_col(lines: list[str], fmt: str) -> int:
    """
    Find the raw character position where DDS column 1 begins.

    For SEU: the ruler line 'SEQNBR*...+...' has '*' at DDS col 1.
    For SPOOL: the ruler line 'RCDNBR  *...+...' has '*' at DDS col 1.

    Returns the 0-based position in the raw line where DDS col 1 starts.
    """
    for line in lines[:30]:
        if fmt == 'seu' and 'SEQNBR*' in line:
            return line.index('*')
        if fmt == 'spool' and 'RCDNBR' in line:
            idx = line.find('*')
            if idx >= 0:
                return idx
    # Fallback defaults based on observed files
    return 8 if fmt == 'seu' else 16


def _extract_dds_record(line: str, dds_col1: int) -> str | None:
    """
    Extract the 80-column DDS record from a raw line.

    Returns the DDS record (padded to 80 chars) or None if the line
    should be skipped.
    """
    if _is_skip_line(line):
        return None

    # The DDS record starts at dds_col1 in the raw line
    if len(line) <= dds_col1:
        return None

    dds = line[dds_col1:]

    # Verify form type is 'A' at position 5
    if len(dds) <= _O_FORMTYPE:
        return None
    if dds[_O_FORMTYPE] != 'A':
        return None

    # Pad to at least 80 chars and strip trailing date/whitespace
    # (SEU listings append a date like '  02/03/10' after column 80)
    dds = dds[:80].ljust(80)
    return dds


def _extract_metadata_seu(lines: list[str]) -> dict:
    """Extract file-level metadata from SEU SOURCE LISTING headers."""
    meta = {'source': None, 'member': None}
    for line in lines[:20]:
        m = re.search(r'SOURCE FILE[\s.]*\s+(\S+)', line)
        if m:
            meta['source'] = m.group(1)
        m = re.search(r'MEMBER[\s.]*\s+(\S+)', line)
        if m and 'MEMBER' in line and '. . .' in line:
            meta['member'] = m.group(1)
    return meta


def _extract_metadata_spool(lines: list[str]) -> dict:
    """Extract file-level metadata from COPY FILE spool headers."""
    meta = {'source': None, 'member': None}
    for line in lines[:20]:
        m = re.search(r'From file[\s.]*:\s+(\S+)', line)
        if m:
            meta['source'] = m.group(1)
        m = re.search(r'Member[\s.]*:\s+(\S+)', line)
        if m:
            meta['member'] = m.group(1)
    return meta


# ---------------------------------------------------------------------------
# DDS A-spec column parser
# ---------------------------------------------------------------------------

def _parse_dds_record(dds: str, is_dspf: bool = False) -> dict:
    """
    Parse one 80-column DDS record into a structured dict.

    `dds` is exactly 80 characters, starting at DDS column 1.
    DDS column N is at index (N-1).
    """
    r = {}

    # Form type (col 6, index 5)
    r['form_type'] = dds[_O_FORMTYPE]

    # Comment check (col 7, index 6)
    r['is_comment'] = (dds[_O_COMMENT] == '*')
    if r['is_comment']:
        return r

    # Condition indicators (cols 7-16, indices 6-15)
    ind_area = dds[_O_IND_START:_O_IND_END]
    r['indicators'] = _parse_indicators(ind_area)
    r['output_ind'] = (ind_area[0] == 'O')

    # Name type (col 17, index 16)
    nt = dds[_O_NAMETYPE]
    r['name_type'] = nt if nt in ('R', 'K', 'S', 'O', 'J') else ''

    # Name (cols 19-28, indices 18-27)
    r['name'] = dds[_O_NAME_START:_O_NAME_END].strip()

    # Reference indicator (col 29, index 28)
    r['ref'] = (dds[_O_REF] == 'R')

    # Length (cols 30-34, indices 29-33)
    len_str = dds[_O_LEN_START:_O_LEN_END].strip()
    r['length'] = int(len_str) if len_str.isdigit() else None

    # Data type (col 35, index 34)
    dt = dds[_O_DTYPE]
    r['data_type'] = dt if dt.strip() else None

    # Decimal positions (cols 36-37, indices 35-36)
    dec_str = dds[_O_DEC_START:_O_DEC_END].strip()
    r['decimal'] = int(dec_str) if dec_str.isdigit() else None

    if is_dspf:
        # Usage (col 38, index 37)
        u = dds[_O_USAGE]
        r['usage'] = u if u.strip() else None

        # Row (cols 39-41, indices 38-40)
        row_str = dds[_O_ROW_START:_O_ROW_END].strip()
        r['row'] = int(row_str) if row_str.isdigit() else None

        # Column (cols 42-44, indices 41-43)
        col_str = dds[_O_COL_START:_O_COL_END].strip()
        r['col'] = int(col_str) if col_str.isdigit() else None

    # Keywords (cols 45-80, indices 44-79)
    r['keywords_raw'] = dds[_O_KW_START:].rstrip()

    return r


def _parse_indicators(ind_area: str) -> list[int]:
    """
    Parse condition indicators from the 10-character area (DDS cols 7-16).

    Layout (0-based within this 10-char area):
      [0]:   Not-indicator or 'O' for output conditioning or blank
      [1-2]: First indicator (2 digits, or N+digit for NOT)
      [3]:   spacer
      [4-5]: Second indicator
      [6]:   spacer
      [7-8]: Third indicator
      [9]:   spacer

    Real examples from ind_area (10 chars):
      '  31      '  -> indicator 31
      'O 51      '  -> output-conditioned, indicator 51
      ' N81      '  -> NOT indicator 81
      '  31  83  '  -> indicators 31 and 83
      '  94      '  -> indicator 94
    """
    area = ind_area.ljust(10)
    indicators = []

    # Three indicator slots at positions 1-2, 4-5, 7-8
    for start in (1, 4, 7):
        chunk = area[start:start + 2]
        if chunk.strip() == '':
            continue
        if chunk.isdigit():
            indicators.append(int(chunk))
            continue

    # If positional parse gave results, return them; otherwise use regex fallback
    if indicators:
        return indicators

    # Regex fallback: find all indicator patterns
    for m in re.finditer(r'(N?)(\d{1,2})', area):
        neg = m.group(1) == 'N'
        num = int(m.group(2))
        if num == 0:
            continue
        indicators.append(-num if neg else num)

    return indicators


# ---------------------------------------------------------------------------
# Keyword helpers
# ---------------------------------------------------------------------------

def _extract_keyword(raw: str, keyword: str) -> str | None:
    """
    Extract a keyword value from raw keywords string.

    KEYWORD(value) -> returns 'value'
    KEYWORD        -> returns '' (present, no parens)
    Not found      -> returns None
    """
    pattern = rf'\b{re.escape(keyword)}\(([^)]*)\)'
    m = re.search(pattern, raw, re.IGNORECASE)
    if m:
        return m.group(1)
    if re.search(rf'\b{re.escape(keyword)}\b', raw, re.IGNORECASE):
        return ''
    return None


def _extract_quoted_value(raw: str, keyword: str) -> str | None:
    """
    Extract keyword value, stripping surrounding single quotes.
    TEXT(' some text ') -> 'some text'
    """
    val = _extract_keyword(raw, keyword)
    if val is None:
        return None
    m = re.match(r"^'(.*)'$", val.strip())
    if m:
        return m.group(1).strip()
    return val.strip()


# ---------------------------------------------------------------------------
# Multi-line continuation assembly
# ---------------------------------------------------------------------------

def _assemble_continued_lines(dds_records: list[str]) -> list[str]:
    """
    Merge continuation lines into the preceding line.

    A continuation line has: form type 'A', no comment, no name type, no name.
    Its keyword area appends to the previous line. If the previous keyword
    area ends with '-', the dash is removed and content concatenated directly.
    """
    assembled = []
    i = 0
    while i < len(dds_records):
        current = dds_records[i]
        # Only attempt to merge continuations if current is NOT a comment
        if current[_O_COMMENT] != '*':
            while i + 1 < len(dds_records):
                nxt = dds_records[i + 1]
                # Next line must be non-comment
                if nxt[_O_COMMENT] == '*':
                    break
                # Must have no name type and no name
                if nxt[_O_NAMETYPE].strip():
                    break
                if nxt[_O_NAME_START:_O_NAME_END].strip():
                    break
                # If indicators are present, it's a separate spec line, not continuation
                ind_area = nxt[_O_IND_START:_O_IND_END].strip()
                kw_area = nxt[_O_KW_START:].rstrip()
                if ind_area:
                    break
                if not kw_area:
                    break
                # Pure continuation: no indicators, just keyword content
                cur_kw = current[_O_KW_START:].rstrip()
                if cur_kw.endswith('-'):
                    current = current[:_O_KW_START] + cur_kw[:-1] + kw_area
                else:
                    current = current[:_O_KW_START] + cur_kw + kw_area
                current = current.ljust(80)
                i += 1
        assembled.append(current)
        i += 1
    return assembled


# ---------------------------------------------------------------------------
# Physical / Logical file parser
# ---------------------------------------------------------------------------

def parse_physical_logical(dds_records: list[str], metadata: dict) -> dict:
    """Parse a physical or logical file DDS and return structured dict."""
    result = {
        'file': metadata.get('member'),
        'source': metadata.get('source'),
        'record_format': None,
        'ref_file': None,
        'pfile': None,
        'jfile': None,
        'join_specs': [],
        'unique': False,
        'dynslt': False,
        'text': None,
        'fields': [],
        'keys': [],
        'select_omit': [],
    }

    assembled = _assemble_continued_lines(dds_records)
    current_field = None

    for dds in assembled:
        p = _parse_dds_record(dds, is_dspf=False)
        if p.get('is_comment'):
            continue

        kw = p.get('keywords_raw', '')
        name_type = p.get('name_type', '')
        name = p.get('name', '')

        # --- File-level or continuation keywords (no name, no name type) ---
        if not name and not name_type:
            ref_val = _extract_keyword(kw, 'REF')
            if ref_val is not None:
                result['ref_file'] = ref_val if ref_val else None
            if _extract_keyword(kw, 'UNIQUE') is not None:
                result['unique'] = True
            pfile = _extract_keyword(kw, 'PFILE')
            if pfile is not None:
                result['pfile'] = pfile
            # JFILE (JOIN logical file)
            jfile = _extract_keyword(kw, 'JFILE')
            if jfile is not None:
                result['jfile'] = jfile
            # DYNSLT (dynamic select)
            if _extract_keyword(kw, 'DYNSLT') is not None:
                result['dynslt'] = True
            # Continuation for previous field
            if current_field and kw.strip():
                _apply_field_keywords(current_field, kw)
            continue

        # --- Record format ---
        if name_type == 'R':
            result['record_format'] = name
            text = _extract_quoted_value(kw, 'TEXT')
            if text:
                result['text'] = text
            pfile = _extract_keyword(kw, 'PFILE')
            if pfile is not None:
                result['pfile'] = pfile
            jfile = _extract_keyword(kw, 'JFILE')
            if jfile is not None:
                result['jfile'] = jfile
            current_field = None
            continue

        # --- JOIN specification (name_type 'J') ---
        if name_type == 'J':
            # J-spec: JOIN(from to) with JFLD on continuation
            join_val = _extract_keyword(kw, 'JOIN')
            jfld_val = _extract_keyword(kw, 'JFLD')
            join_entry = {}
            if join_val:
                parts = join_val.split()
                if len(parts) >= 2:
                    join_entry['from_file'] = parts[0]
                    join_entry['to_file'] = parts[1]
            if jfld_val:
                parts = jfld_val.split()
                if len(parts) >= 2:
                    join_entry['from_field'] = parts[0]
                    join_entry['to_field'] = parts[1]
            if join_entry:
                result['join_specs'].append(join_entry)
            current_field = None
            continue

        # --- Key ---
        if name_type == 'K':
            descend = _extract_keyword(kw, 'DESCEND') is not None
            result['keys'].append({'name': name, 'descend': descend})
            current_field = None
            continue

        # --- Select/Omit ---
        if name_type in ('S', 'O'):
            entry = {
                'type': 'select' if name_type == 'S' else 'omit',
                'field': name,
            }
            cmp_val = _extract_keyword(kw, 'CMP')
            if cmp_val:
                entry['comparison'] = cmp_val
            comp_val = _extract_keyword(kw, 'COMP')
            if comp_val:
                entry['comparison'] = comp_val
            if _extract_keyword(kw, 'ALL') is not None:
                entry['all'] = True
            result['select_omit'].append(entry)
            current_field = None
            continue

        # --- Field definition ---
        if name:
            field = {
                'name': name,
                'alias': None,
                'type': p.get('data_type'),
                'length': p.get('length'),
                'decimal': p.get('decimal'),
                'ref': p.get('ref', False),
                'text': None,
                'colhdg': None,
            }
            _apply_field_keywords(field, kw)

            # Default type inference for inline-defined fields
            if field['length'] is not None and field['type'] is None:
                if field['decimal'] is not None:
                    field['type'] = 'P'  # packed decimal default for numeric
                else:
                    field['type'] = 'A'  # alpha default

            result['fields'].append(field)
            current_field = field

    # Assign key positions to fields
    for i, key in enumerate(result['keys']):
        for field in result['fields']:
            if field['name'] == key['name']:
                field['key_position'] = i + 1
                break

    return result


def _apply_field_keywords(field: dict, kw_raw: str):
    """Apply keywords from raw text to a physical/logical field dict."""
    alias = _extract_keyword(kw_raw, 'ALIAS')
    if alias:
        field['alias'] = alias

    text = _extract_quoted_value(kw_raw, 'TEXT')
    if text:
        field['text'] = text

    colhdg = _extract_quoted_value(kw_raw, 'COLHDG')
    if colhdg:
        field['colhdg'] = colhdg

    edtcde = _extract_keyword(kw_raw, 'EDTCDE')
    if edtcde is not None:
        field['edtcde'] = edtcde

    edtwrd = _extract_quoted_value(kw_raw, 'EDTWRD')
    if edtwrd is not None:
        field['edtwrd'] = edtwrd

    # DATFMT / TIMFMT
    datfmt = _extract_keyword(kw_raw, 'DATFMT')
    if datfmt is not None:
        field['datfmt'] = datfmt

    timfmt = _extract_keyword(kw_raw, 'TIMFMT')
    if timfmt is not None:
        field['timfmt'] = timfmt

    # DFT (default value)
    dft = _extract_keyword(kw_raw, 'DFT')
    if dft is not None:
        # Strip quotes if present
        m = re.match(r"^'(.*)'$", dft.strip())
        field['dft'] = m.group(1) if m else dft.strip()

    # Validation keywords: CHECK, RANGE, VALUES, COMP
    check = _extract_keyword(kw_raw, 'CHECK')
    if check is not None:
        field['check'] = check

    range_val = _extract_keyword(kw_raw, 'RANGE')
    if range_val is not None:
        field['range'] = range_val

    values_val = _extract_keyword(kw_raw, 'VALUES')
    if values_val is not None:
        field['values'] = values_val

    comp_val = _extract_keyword(kw_raw, 'COMP')
    if comp_val is not None:
        field['comp'] = comp_val

    # CONCAT (logical file: combine multiple physical fields)
    concat = _extract_keyword(kw_raw, 'CONCAT')
    if concat is not None:
        field['concat'] = concat

    # SST (logical file: substring of physical field)
    sst = _extract_keyword(kw_raw, 'SST')
    if sst is not None:
        field['sst'] = sst

    # ALWNULL
    if _extract_keyword(kw_raw, 'ALWNULL') is not None:
        field['alwnull'] = True

    # CCSID
    ccsid = _extract_keyword(kw_raw, 'CCSID')
    if ccsid is not None:
        field['ccsid'] = ccsid


# ---------------------------------------------------------------------------
# DSPF parser
# ---------------------------------------------------------------------------

def parse_dspf(dds_records: list[str], metadata: dict) -> dict:
    """Parse a display file DDS and return structured dict."""
    result = {
        'file': metadata.get('member'),
        'source': metadata.get('source'),
        'screen_size': None,
        'record_formats': [],
    }

    # For DSPF, we handle continuations carefully -- indicator-conditioned
    # attribute lines must NOT be merged.
    assembled = _assemble_continued_lines(dds_records)

    current_format = None
    current_field = None

    for dds in assembled:
        p = _parse_dds_record(dds, is_dspf=True)
        if p.get('is_comment'):
            continue

        kw = p.get('keywords_raw', '')
        name_type = p.get('name_type', '')
        name = p.get('name', '')
        indicators = p.get('indicators', [])

        # --- File-level keywords (before any record format) ---
        if not name and not name_type and current_format is None:
            dspsiz = _extract_keyword(kw, 'DSPSIZ')
            if dspsiz:
                m = re.match(r'(\d+)\s+(\d+)', dspsiz)
                if m:
                    result['screen_size'] = f"{m.group(1)}x{m.group(2)}"
            continue

        # --- Record format ---
        if name_type == 'R':
            current_format = {
                'name': name,
                'type': None,
                'sfl_size': None,
                'sfl_page': None,
                'fields': [],
                'function_keys': [],
                'indicators': [],
                'keywords': [],
            }
            _apply_format_keywords(current_format, kw, indicators)
            result['record_formats'].append(current_format)
            current_field = None
            continue

        if current_format is None:
            continue

        # --- Named field ---
        if name and not name_type:
            field = {
                'name': name,
                'alias': None,
                'type': p.get('data_type'),
                'length': p.get('length'),
                'decimal': p.get('decimal'),
                'usage': p.get('usage'),
                'row': p.get('row'),
                'col': p.get('col'),
                'ref': p.get('ref', False),
                'indicators': [x for x in indicators if x != 0],
                'dspatr': [],
                'edtcde': None,
                'edtwrd': None,
                'color': None,
                'text': None,
                'msgid': None,
            }
            _apply_dspf_field_keywords(field, kw, indicators)

            # Default type inference
            if field['length'] is not None and field['type'] is None:
                if field['decimal'] is not None:
                    field['type'] = 'P'
                else:
                    field['type'] = 'A'

            current_format['fields'].append(field)
            current_field = field
            continue

        # --- Unnamed line within a format ---
        if not name and not name_type:
            # Check if this is a literal constant (has row/col position or
            # quoted string in keywords) -- these are screen text, not field attributes
            row = p.get('row')
            col = p.get('col')
            is_literal = False
            if (row is not None or col is not None) and kw.startswith("'"):
                is_literal = True

            # Always apply format-level keywords
            _apply_format_keywords(current_format, kw, indicators)

            if is_literal:
                # Literal constant -- reset current field context
                current_field = None
            elif current_field is not None:
                # Field continuation: add attributes/keywords to current field
                _apply_dspf_field_keywords(current_field, kw, indicators)
            continue

    return result


def _apply_format_keywords(fmt: dict, kw_raw: str, indicators: list[int]):
    """Apply record-format-level keywords."""
    # SFL
    if _extract_keyword(kw_raw, 'SFL') is not None and 'SFLCTL' not in kw_raw:
        fmt['type'] = 'SFL'
    sflctl = _extract_keyword(kw_raw, 'SFLCTL')
    if sflctl is not None:
        fmt['type'] = 'SFLCTL'
        fmt['sfl_ref'] = sflctl

    sflsiz = _extract_keyword(kw_raw, 'SFLSIZ')
    if sflsiz is not None:
        try:
            fmt['sfl_size'] = int(sflsiz)
        except ValueError:
            fmt['sfl_size'] = sflsiz

    sflpag = _extract_keyword(kw_raw, 'SFLPAG')
    if sflpag is not None:
        try:
            fmt['sfl_page'] = int(sflpag)
        except ValueError:
            fmt['sfl_page'] = sflpag

    # Function keys: CA01-CA24, CF01-CF24
    for m in re.finditer(r'\b(C[AF])(\d{2})\(([^)]*)\)', kw_raw):
        key_entry = {
            'key': f"{m.group(1)}{int(m.group(2)):02d}",
            'indicator': m.group(3),
        }
        if key_entry not in fmt['function_keys']:
            fmt['function_keys'].append(key_entry)

    # Boolean format keywords
    for kw_name in ['SFLDSP', 'SFLDSPCTL', 'SFLCLR', 'SFLINZ', 'SFLNXTCHG',
                     'OVERLAY', 'PRINT', 'INDARA']:
        if _extract_keyword(kw_raw, kw_name) is not None:
            entry = {'keyword': kw_name}
            if indicators:
                entry['indicators'] = list(indicators)
            existing = [k.get('keyword') for k in fmt.get('keywords', [])]
            if kw_name not in existing or indicators:
                fmt.setdefault('keywords', []).append(entry)

    sflend = _extract_keyword(kw_raw, 'SFLEND')
    if sflend is not None:
        entry = {'keyword': 'SFLEND', 'value': sflend}
        if indicators:
            entry['indicators'] = list(indicators)
        fmt.setdefault('keywords', []).append(entry)

    sflrcdnbr = _extract_keyword(kw_raw, 'SFLRCDNBR')
    if sflrcdnbr is not None:
        fmt.setdefault('keywords', []).append({'keyword': 'SFLRCDNBR', 'value': sflrcdnbr})

    csrloc = _extract_keyword(kw_raw, 'CSRLOC')
    if csrloc is not None:
        entry = {'keyword': 'CSRLOC', 'value': csrloc}
        if indicators:
            entry['indicators'] = list(indicators)
        fmt.setdefault('keywords', []).append(entry)

    help_kw = _extract_keyword(kw_raw, 'HELP')
    if help_kw is not None:
        entry = {'keyword': 'HELP'}
        if help_kw:
            entry['value'] = help_kw
        fmt.setdefault('keywords', []).append(entry)


def _apply_dspf_field_keywords(field: dict, kw_raw: str, indicators: list[int]):
    """Apply keywords and attributes to a DSPF field."""
    alias = _extract_keyword(kw_raw, 'ALIAS')
    if alias:
        field['alias'] = alias

    text = _extract_quoted_value(kw_raw, 'TEXT')
    if text:
        field['text'] = text

    edtcde = _extract_keyword(kw_raw, 'EDTCDE')
    if edtcde is not None:
        field['edtcde'] = edtcde

    edtwrd = _extract_quoted_value(kw_raw, 'EDTWRD')
    if edtwrd is not None:
        field['edtwrd'] = edtwrd

    color = _extract_keyword(kw_raw, 'COLOR')
    if color:
        field['color'] = color

    msgid = _extract_keyword(kw_raw, 'MSGID')
    if msgid:
        field['msgid'] = msgid

    # DSPATR -- may appear on multiple indicator-conditioned lines
    for m in re.finditer(r'DSPATR\(([^)]+)\)', kw_raw):
        attrs = [a.strip() for a in m.group(1).split()]
        for attr in attrs:
            if attr and attr not in field['dspatr']:
                field['dspatr'].append(attr)

    # Collect indicators from continuation lines
    if indicators:
        for ind in indicators:
            if ind != 0 and ind not in field['indicators']:
                field['indicators'].append(ind)


# ---------------------------------------------------------------------------
# Top-level API
# ---------------------------------------------------------------------------

def parse_dds_file(filepath: str, is_dspf: bool = False) -> dict:
    """Parse a DDS source file and return structured data as dict."""
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        raw_lines = f.readlines()

    fmt = _detect_format(raw_lines)
    dds_col1 = _find_dds_start_col(raw_lines, fmt)

    if fmt == 'spool':
        metadata = _extract_metadata_spool(raw_lines)
    else:
        metadata = _extract_metadata_seu(raw_lines)

    if not metadata.get('member'):
        metadata['member'] = os.path.splitext(os.path.basename(filepath))[0]

    # Extract 80-column DDS records from the first source member only.
    # Multi-member files (multiple SEU listings concatenated) are split
    # at the first 'E N D  O F  S O U R C E' marker.
    dds_records = []
    seen_any_record = False
    for line in raw_lines:
        if seen_any_record and 'E N D  O F  S O U R C E' in line:
            break
        rec = _extract_dds_record(line, dds_col1)
        if rec is not None:
            dds_records.append(rec)
            seen_any_record = True

    if is_dspf:
        return parse_dspf(dds_records, metadata)
    else:
        return parse_physical_logical(dds_records, metadata)


def parse_spool_section(filepath: str, start: int, end: int,
                         is_dspf: bool = False) -> dict:
    """
    Parse a DDS section embedded within a larger spool file.
    `start` and `end` are 1-based line numbers (inclusive).

    The COPY FILE header/ruler may be outside the DDS section range,
    so we scan backwards from `start` to find the format and ruler.
    """
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        raw_lines = f.readlines()

    section = raw_lines[max(0, start - 1):end]

    # COPY FILE format has ONE header/ruler at the very beginning of the
    # spool file, shared by all DDS sections. Always check the file header.
    file_header = raw_lines[:30]
    fmt = _detect_format(file_header)
    dds_col1 = _find_dds_start_col(file_header, fmt)

    # For metadata, use the file header (COPY FILE) or the section (SEU).
    if fmt == 'spool':
        metadata = _extract_metadata_spool(file_header)
    else:
        metadata = _extract_metadata_seu(section)

    if not metadata.get('member'):
        metadata['member'] = os.path.splitext(os.path.basename(filepath))[0]

    dds_records = []
    for line in section:
        rec = _extract_dds_record(line, dds_col1)
        if rec is not None:
            dds_records.append(rec)

    if is_dspf:
        return parse_dspf(dds_records, metadata)
    else:
        return parse_physical_logical(dds_records, metadata)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Parse AS/400 DDS source files and output field definitions as JSON.',
        epilog='Examples:\n'
               '  %(prog)s FFDFALD0.txt\n'
               '  %(prog)s MFD0062.txt --dspf\n'
               '  %(prog)s big_spool.txt --spool --start 100 --end 250\n',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('file', help='Path to DDS source file')
    parser.add_argument('--dspf', action='store_true',
                        help='Parse as display file (DSPF)')
    parser.add_argument('--spool', action='store_true',
                        help='Parse DDS section from within a spool file')
    parser.add_argument('--start', type=int, default=1,
                        help='Start line number (1-based) for --spool mode')
    parser.add_argument('--end', type=int, default=0,
                        help='End line number (1-based, inclusive) for --spool mode')

    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    if args.spool:
        if args.end == 0:
            with open(args.file, 'r', encoding='utf-8', errors='replace') as f:
                args.end = sum(1 for _ in f)
        result = parse_spool_section(args.file, args.start, args.end,
                                      is_dspf=args.dspf)
    else:
        result = parse_dds_file(args.file, is_dspf=args.dspf)

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == '__main__':
    main()
