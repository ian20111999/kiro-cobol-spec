#!/usr/bin/env python3
"""AS/400 Data Fetcher — Collect all program information from AS/400.

Automatically discovers library, source file, referenced files/programs,
field schemas (DSPFFD), file relations (DSPDBR), and source code.

Usage:
    python3 as400_fetcher.py PFD0062
    python3 as400_fetcher.py PFD0062 --output result.json
    python3 as400_fetcher.py PFD0062 --host 192.168.1.1 --user QPGMR
    python3 as400_fetcher.py PFD0062 --source-only
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Import connector from same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from as400_connector import AS400Connection


# System libraries to exclude when auto-discovering user programs
SYSTEM_LIBRARIES = frozenset({
    "QSYS", "QSYS2", "QGPL", "QTEMP", "QUSRSYS", "QHLPSYS",
    "QUSRTOOL", "QPDA", "QRPG", "QCBL", "QPGM",
    "QSYSDIR", "QRECOVERY", "QRPLOBJ", "QIDU",
})

# Common source physical files for COBOL/CL/DDS
COMMON_SRC_FILES = [
    "QCBLSRC", "QCBLLESRC", "QCLSRC", "QCLLESRC",
    "QDDSSRC", "QRPGSRC", "QRPGLESRC",
]

# Working library for temporary outfiles
WORK_LIB = "QTEMP"


def _outfile_name(prefix: str) -> str:
    """Generate a short unique outfile name (max 10 chars)."""
    return f"{prefix}{os.getpid() % 100000:05d}"


class AS400Fetcher:
    """Fetch all program-related data from AS/400.

    Uses standard CL commands with OUTPUT(*OUTFILE) to extract:
    - Program object info (DSPOBJD)
    - Program references (DSPPGMREF)
    - File field definitions (DSPFFD)
    - File relations (DSPDBR)
    - Source code (CPYTOSTMF)
    """

    def __init__(self, connection: AS400Connection):
        self.conn = connection

    # ------------------------------------------------------------------
    # Program Discovery
    # ------------------------------------------------------------------

    def find_program(self, name: str) -> dict:
        """Find a program object across all libraries.

        Uses DSPOBJD with OBJ(*ALL/{name}).
        Filters out system libraries to select user program.

        Returns dict with: name, library, text, source_file,
        source_library, source_member, object_type.
        """
        outfile = _outfile_name("QFOBJ")
        cl_cmd = (
            f"DSPOBJD OBJ(*ALL/{name}) OBJTYPE(*PGM *SRVPGM) "
            f"DETAIL(*FULL) OUTPUT(*OUTFILE) "
            f"OUTFILE({WORK_LIB}/{outfile})"
        )

        try:
            rows = self.conn.fetch_outfile(cl_cmd, WORK_LIB, outfile)
        except RuntimeError as e:
            raise RuntimeError(f"Program {name} not found on system: {e}")

        if not rows:
            raise RuntimeError(f"Program {name} not found on system.")

        # Prefer user libraries over system libraries
        user_rows = [
            r for r in rows
            if r.get("ODLBNM", "").strip().upper() not in SYSTEM_LIBRARIES
        ]
        row = user_rows[0] if user_rows else rows[0]

        return {
            "name": row.get("ODOBNM", "").strip(),
            "library": row.get("ODLBNM", "").strip(),
            "text": row.get("ODOBTX", "").strip(),
            "source_file": row.get("ODSRCF", "").strip(),
            "source_library": row.get("ODSRCL", "").strip(),
            "source_member": row.get("ODSRCM", "").strip(),
            "object_type": row.get("ODOBTP", "").strip(),
        }

    def find_source_member(self, library: str, program: str) -> tuple:
        """Find the source file/library/member for a program.

        First tries DSPOBJD DETAIL(*FULL) for embedded source info.
        Falls back to searching common source files (QCBLSRC, etc.).

        Returns (src_file, src_lib, src_member).
        Raises RuntimeError if not found.
        """
        # Try DSPOBJD first
        try:
            info = self.find_program(program)
            sf = info.get("source_file", "")
            sl = info.get("source_library", "")
            sm = info.get("source_member", "")
            if sf and sl and sm:
                return (sf, sl, sm)
        except RuntimeError:
            pass

        # Search common source files
        for src_file in COMMON_SRC_FILES:
            try:
                self.conn.run_cl(
                    f"CHKOBJ OBJ({library}/{src_file}) OBJTYPE(*FILE) MBR({program})"
                )
                return (src_file, library, program)
            except RuntimeError:
                continue

        raise RuntimeError(
            f"Source member for {program} not found in {library}. "
            f"Searched: {', '.join(COMMON_SRC_FILES)}"
        )

    # ------------------------------------------------------------------
    # Program References (DSPPGMREF)
    # ------------------------------------------------------------------

    def get_program_refs(self, library: str, program: str) -> dict:
        """Get all file and program references for a program.

        Uses DSPPGMREF to discover:
        - Referenced files (name, library, usage: I/O/B/U)
        - Referenced programs (name, library)

        Returns dict with 'files' and 'programs' lists.
        """
        outfile = _outfile_name("QFREF")
        cl_cmd = (
            f"DSPPGMREF PGM({library}/{program}) "
            f"OUTPUT(*OUTFILE) OUTFILE({WORK_LIB}/{outfile})"
        )

        try:
            rows = self.conn.fetch_outfile(cl_cmd, WORK_LIB, outfile)
        except RuntimeError:
            return {"files": [], "programs": []}

        usage_map = {
            "I": "INPUT",
            "O": "OUTPUT",
            "B": "BOTH",
            "U": "UPDATE",
        }

        files = []
        programs = []
        seen_files = set()
        seen_programs = set()

        for row in rows:
            ref_name = row.get("WHRFNM", "").strip()
            ref_lib = row.get("WHRFLIB", "").strip()
            ref_type = row.get("WHRFTP", "").strip()
            usage_code = row.get("WHFIUS", "").strip()

            if not ref_name:
                continue

            # Resolve *LIBL to the program's own library
            resolved_lib = ref_lib if ref_lib != "*LIBL" else library

            if ref_type == "*FILE":
                key = f"{resolved_lib}/{ref_name}"
                if key not in seen_files:
                    seen_files.add(key)
                    files.append({
                        "name": ref_name,
                        "library": resolved_lib,
                        "usage": usage_map.get(usage_code, "UNKNOWN"),
                    })
            elif ref_type in ("*PGM", "*SRVPGM"):
                key = f"{resolved_lib}/{ref_name}"
                if key not in seen_programs and ref_name != program:
                    seen_programs.add(key)
                    programs.append({
                        "name": ref_name,
                        "library": resolved_lib,
                    })

        return {"files": files, "programs": programs}

    # ------------------------------------------------------------------
    # File Schema (DSPFFD)
    # ------------------------------------------------------------------

    def get_file_schema(self, library: str, filename: str) -> dict:
        """Get file field definitions via DSPFFD.

        Returns dict with:
        - fields: list of {name, type, length, decimal, colhdg, text}
        - keys: list of key field names
        - record_format: first record format name
        """
        outfile = _outfile_name("QFFFD")
        cl_cmd = (
            f"DSPFFD FILE({library}/{filename}) "
            f"OUTPUT(*OUTFILE) OUTFILE({WORK_LIB}/{outfile})"
        )

        try:
            rows = self.conn.fetch_outfile(cl_cmd, WORK_LIB, outfile)
        except RuntimeError:
            return {"fields": [], "keys": [], "record_format": ""}

        fields = []
        keys = []
        record_format = ""
        seen_fields = set()

        for row in rows:
            field_name = row.get("WHFLDI", "").strip()
            if not field_name or field_name in seen_fields:
                continue
            seen_fields.add(field_name)

            if not record_format:
                record_format = row.get("WHNAME", "").strip()

            field_type = row.get("WHFLDT", "").strip()
            field_len = int(row.get("WHFLDB", "0") or "0")
            field_dec = int(row.get("WHFLDD", "0") or "0")
            field_text = row.get("WHFTXT", "").strip()

            # Build COLHDG from up to 3 heading parts
            colhdg_parts = []
            for suffix in ("WHCHD1", "WHCHD2", "WHCHD3"):
                part = row.get(suffix, "").strip()
                if part:
                    colhdg_parts.append(part)
            colhdg = " ".join(colhdg_parts)

            # Check if key field (non-zero key sequence)
            key_seq = row.get("WHKSEQ", "").strip()
            if key_seq and key_seq not in ("0", ""):
                keys.append(field_name)

            fields.append({
                "name": field_name,
                "type": field_type,
                "length": field_len,
                "decimal": field_dec,
                "colhdg": colhdg,
                "text": field_text,
            })

        return {
            "fields": fields,
            "keys": keys,
            "record_format": record_format,
        }

    # ------------------------------------------------------------------
    # File Relations (DSPDBR)
    # ------------------------------------------------------------------

    def get_file_relations(self, library: str, filename: str) -> list:
        """Get file dependencies (LF over PF) via DSPDBR.

        Returns list of {dependent, dep_library, type} dicts.
        """
        outfile = _outfile_name("QFDBR")
        cl_cmd = (
            f"DSPDBR FILE({library}/{filename}) "
            f"OUTPUT(*OUTFILE) OUTFILE({WORK_LIB}/{outfile})"
        )

        try:
            rows = self.conn.fetch_outfile(cl_cmd, WORK_LIB, outfile)
        except RuntimeError:
            return []

        relations = []
        seen = set()
        for row in rows:
            dep_file = row.get("DBFRLF", "").strip()
            dep_lib = row.get("DBFRLIB", "").strip()
            if not dep_file or dep_file in seen:
                continue
            seen.add(dep_file)
            relations.append({
                "dependent": dep_file,
                "dep_library": dep_lib,
                "type": "LF",
            })

        return relations

    # ------------------------------------------------------------------
    # Source Code Retrieval
    # ------------------------------------------------------------------

    def get_source_code(self, src_lib: str, src_file: str, member: str) -> str:
        """Retrieve source code from a source physical file member.

        Uses CPYTOSTMF to copy the member to an IFS temp file,
        then reads it back.

        Returns the source text as a string.
        """
        ifs_path = f"/tmp/cobol_spec_{member}.txt"

        cl_cmd = (
            f"CPYTOSTMF "
            f"FROMMBR('/QSYS.LIB/{src_lib}.LIB/{src_file}.FILE/{member}.MBR') "
            f"TOSTMF('{ifs_path}') STMFOPT(*REPLACE) "
            f"STMFCODPAG(1208)"
        )

        try:
            self.conn.run_cl(cl_cmd)
        except RuntimeError as e:
            raise RuntimeError(
                f"Failed to copy source {src_lib}/{src_file}/{member}: {e}"
            )

        source = self.conn.read_ifs_file(ifs_path)

        # Cleanup temp file
        try:
            self.conn.run_cl(f"RMVLNK OBJLNK('{ifs_path}')")
        except RuntimeError:
            pass

        return source

    # ------------------------------------------------------------------
    # Program Object Text
    # ------------------------------------------------------------------

    def get_program_text(self, library: str, program: str) -> str:
        """Get the object text description for a program."""
        try:
            info = self.find_program(program)
            return info.get("text", "")
        except RuntimeError:
            return ""

    # ------------------------------------------------------------------
    # Main Collection Method
    # ------------------------------------------------------------------

    def collect_all(self, program_name: str) -> dict:
        """Collect all data for a program in one call.

        Steps:
          1. Find program object -> library, source info
          2. Retrieve source code (CPYTOSTMF)
          3. Get program references -> files + called programs
          4. For each referenced file -> DSPFFD schema + DSPDBR relations
          5. For each referenced program -> DSPOBJD object text
          6. Format source for pipeline compatibility

        Returns a structured dict suitable for JSON serialization.
        """
        _log = lambda msg: print(msg, file=sys.stderr)

        # 1. Find program
        _log(f"[1/6] Finding program {program_name}...")
        pgm_info = self.find_program(program_name)
        pgm_lib = pgm_info["library"]
        _log(f"       Found in {pgm_lib}: {pgm_info['text']}")

        # 2. Get source code
        _log("[2/6] Retrieving source code...")
        src_file = pgm_info.get("source_file", "")
        src_lib = pgm_info.get("source_library", "")
        src_member = pgm_info.get("source_member", "") or program_name

        source_code = ""
        source_file_path = ""

        if src_file and src_lib:
            try:
                source_code = self.get_source_code(src_lib, src_file, src_member)
                source_file_path = f"/tmp/cobol_spec_{src_member}.txt"
                _log(f"       Source: {src_lib}/{src_file}({src_member})")
            except RuntimeError as e:
                _log(f"       Warning: {e}")

        if not source_code:
            try:
                src_file, src_lib, src_member = self.find_source_member(
                    pgm_lib, program_name
                )
                source_code = self.get_source_code(src_lib, src_file, src_member)
                source_file_path = f"/tmp/cobol_spec_{src_member}.txt"
                _log(f"       Source found: {src_lib}/{src_file}({src_member})")
            except RuntimeError as e:
                _log(f"       Warning: Could not find source: {e}")

        # 3. Get program references
        _log("[3/6] Getting program references (DSPPGMREF)...")
        refs = self.get_program_refs(pgm_lib, program_name)
        ref_files = refs["files"]
        ref_programs = refs["programs"]
        _log(f"       Files: {len(ref_files)}, Programs: {len(ref_programs)}")

        # 4. Get file schemas and relations
        _log("[4/6] Getting file schemas (DSPFFD) and relations (DSPDBR)...")
        for f in ref_files:
            lib = f.get("library", pgm_lib)
            name = f["name"]
            try:
                schema = self.get_file_schema(lib, name)
                f["schema"] = schema
                _log(f"       {name}: {len(schema['fields'])} fields, "
                     f"{len(schema['keys'])} keys")
            except Exception as e:
                f["schema"] = {"fields": [], "keys": [], "record_format": ""}
                _log(f"       {name}: schema error - {e}")

            try:
                relations = self.get_file_relations(lib, name)
                f["relations"] = relations
                if relations:
                    _log(f"       {name}: {len(relations)} dependent files")
            except Exception:
                f["relations"] = []

        # 5. Get referenced program info
        _log("[5/6] Getting referenced program info...")
        for p in ref_programs:
            lib = p.get("library", pgm_lib)
            name = p["name"]
            try:
                text = self.get_program_text(lib, name)
                p["text"] = text
                _log(f"       {name}: {text or '(no description)'}")
            except Exception:
                p["text"] = ""

        # 6. Save source in pipeline-compatible format
        _log("[6/6] Formatting output...")
        if source_code and source_file_path:
            self._save_compatible_source(
                source_code, src_member, src_file, source_file_path
            )

        result = {
            "program": {
                "name": pgm_info["name"],
                "library": pgm_lib,
                "text": pgm_info["text"],
                "source_file": src_file,
                "source_library": src_lib,
                "source_member": src_member,
            },
            "source_code": source_code,
            "source_file_path": source_file_path,
            "referenced_files": ref_files,
            "referenced_programs": ref_programs,
        }

        _log(f"\nCollection complete for {program_name}.")
        return result

    @staticmethod
    def _save_compatible_source(
        source: str, member: str, src_file: str, path: str
    ):
        """Save source in a format compatible with the existing pipeline.

        Adds a member header so that format_normalizer -> spool_splitter ->
        cobol_skeleton can process it without modification.
        """
        header_lines = [
            f"5769CB1  V4R4M0  000000  AS/400 COBOL Source",
            f"Member . . . . . :  {member}",
            f"Source File  . . :  {src_file}",
            "=" * 60,
        ]
        formatted = "\n".join(header_lines) + "\n" + source

        try:
            Path(path).write_text(formatted, encoding="utf-8")
        except OSError:
            pass


# ======================================================================
# CLI
# ======================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Fetch all program information from AS/400"
    )
    parser.add_argument("program", help="Program name to fetch (e.g. PFD0062)")
    parser.add_argument(
        "--output", "-o",
        help="Output JSON file path (default: stdout)",
    )
    parser.add_argument("--host", help="AS/400 hostname (overrides config)")
    parser.add_argument("--user", help="AS/400 username (overrides config)")
    parser.add_argument("--password", help="AS/400 password (prefer env var)")
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="Only fetch source code, skip full analysis",
    )

    args = parser.parse_args()

    # Connect
    conn = AS400Connection(
        host=args.host,
        user=args.user,
        password=args.password,
    )

    if not conn.connect():
        print("Error: Could not connect to AS/400.", file=sys.stderr)
        print("Run: python3 as400_connector.py --setup", file=sys.stderr)
        sys.exit(1)

    print(f"Connected via {conn.method}", file=sys.stderr)

    try:
        fetcher = AS400Fetcher(conn)

        if args.source_only:
            pgm_info = fetcher.find_program(args.program)
            source = fetcher.get_source_code(
                pgm_info["source_library"],
                pgm_info["source_file"],
                pgm_info.get("source_member") or args.program,
            )
            if args.output:
                Path(args.output).write_text(source, encoding="utf-8")
                print(f"Source saved to {args.output}", file=sys.stderr)
            else:
                print(source)
        else:
            result = fetcher.collect_all(args.program)
            output_json = json.dumps(result, indent=2, ensure_ascii=False)

            if args.output:
                Path(args.output).write_text(output_json, encoding="utf-8")
                print(f"Output saved to {args.output}", file=sys.stderr)
            else:
                print(output_json)

    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
