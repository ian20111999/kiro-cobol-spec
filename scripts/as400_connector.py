#!/usr/bin/env python3
"""AS/400 Connection Manager — Auto-detect SSH/ODBC/ibm_db.

Provides a unified interface for connecting to IBM i (AS/400) systems.
Automatically detects available connection methods and uses the best one.

Connection detection order:
  1. SSH (most universal, Mac built-in)
  2. ODBC (requires IBM i Access ODBC Driver)
  3. ibm_db (requires ibm_db Python package)

Configuration sources (in priority order):
  1. Constructor parameters
  2. Environment variables: AS400_HOST, AS400_USER, AS400_PASSWORD
  3. Config file: ~/.cobol-spec/config.json

Usage:
    python3 as400_connector.py --test                    # Test connection
    python3 as400_connector.py --setup                   # Interactive setup
    python3 as400_connector.py --run-cl "DSPOBJD ..."    # Execute CL command
"""

import argparse
import csv
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG_DIR = Path.home() / ".cobol-spec"
CONFIG_FILE = CONFIG_DIR / "config.json"


class AS400Connection:
    """Unified AS/400 connection interface.

    Supports SSH, ODBC, and ibm_db backends with automatic detection.
    All CL command execution and IFS file access goes through this class.
    """

    def __init__(self, host=None, user=None, password=None):
        self.host = host or os.environ.get("AS400_HOST", "")
        self.user = user or os.environ.get("AS400_USER", "")
        self.password = password or os.environ.get("AS400_PASSWORD", "")
        self.method = None  # "ssh", "odbc", "ibm_db"
        self._odbc_conn = None
        self._ibm_conn = None

        # Load from config if not provided
        if not self.host:
            self._load_config()

    def _load_config(self):
        """Load connection settings from config file."""
        if CONFIG_FILE.exists():
            try:
                cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                self.host = self.host or cfg.get("host", "")
                self.user = self.user or cfg.get("user", "")
                # Password only from env var, never stored in config
            except (json.JSONDecodeError, OSError):
                pass

    def _save_config(self):
        """Save host/user to config file. Never saves password."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cfg = {"host": self.host, "user": self.user}
        CONFIG_FILE.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Auto-detect and establish connection. Returns True on success."""
        if not self.host or not self.user:
            return False

        # Try SSH first (most universal, Mac built-in)
        if self._try_ssh():
            self.method = "ssh"
            return True

        # Try ODBC
        if self._try_odbc():
            self.method = "odbc"
            return True

        # Try ibm_db
        if self._try_ibm_db():
            self.method = "ibm_db"
            return True

        return False

    def _try_ssh(self) -> bool:
        """Test SSH connectivity with a simple echo command."""
        if not shutil.which("ssh"):
            return False
        try:
            result = subprocess.run(
                [
                    "ssh",
                    "-o", "BatchMode=yes",
                    "-o", "ConnectTimeout=5",
                    "-o", "StrictHostKeyChecking=accept-new",
                    f"{self.user}@{self.host}",
                    "echo", "COBOL_SPEC_OK",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.returncode == 0 and "COBOL_SPEC_OK" in result.stdout
        except (subprocess.TimeoutExpired, OSError):
            return False

    def _try_odbc(self) -> bool:
        """Test ODBC connectivity via IBM i Access ODBC Driver."""
        try:
            import pyodbc

            conn_str = (
                f"DRIVER={{IBM i Access ODBC Driver}};"
                f"SYSTEM={self.host};"
                f"UID={self.user};"
            )
            if self.password:
                conn_str += f"PWD={self.password};"
            self._odbc_conn = pyodbc.connect(conn_str, timeout=10)
            return True
        except Exception:
            return False

    def _try_ibm_db(self) -> bool:
        """Test ibm_db connectivity."""
        try:
            import ibm_db

            conn_str = (
                f"DATABASE={self.host};HOSTNAME={self.host};"
                f"PORT=446;PROTOCOL=TCPIP;UID={self.user};"
            )
            if self.password:
                conn_str += f"PWD={self.password};"
            self._ibm_conn = ibm_db.connect(conn_str, "", "")
            return self._ibm_conn is not None
        except Exception:
            return False

    def test_connection(self) -> dict:
        """Test all connection methods and return detailed status."""
        result = {
            "host": self.host,
            "user": self.user,
            "connected": False,
            "method": None,
            "methods_tried": [],
        }

        if not self.host or not self.user:
            result["error"] = "Missing host or user. Run --setup first."
            return result

        for method_name, method_fn in [
            ("ssh", self._try_ssh),
            ("odbc", self._try_odbc),
            ("ibm_db", self._try_ibm_db),
        ]:
            result["methods_tried"].append(method_name)
            if method_fn():
                result["connected"] = True
                result["method"] = method_name
                self.method = method_name
                break

        if not result["connected"]:
            result["error"] = "All connection methods failed."

        return result

    # ------------------------------------------------------------------
    # CL Command Execution
    # ------------------------------------------------------------------

    def run_cl(self, command: str) -> str:
        """Execute a CL command and return stdout output.

        Raises RuntimeError if the command fails.
        """
        if self.method == "ssh":
            return self._ssh_cl(command)
        elif self.method == "odbc":
            return self._odbc_cl(command)
        elif self.method == "ibm_db":
            return self._ibm_db_cl(command)
        else:
            raise ConnectionError("Not connected. Call connect() first.")

    def _ssh_cl(self, command: str) -> str:
        """Execute CL command via SSH using the 'system' utility."""
        # Escape single quotes for shell
        cl_escaped = command.replace("'", "'\\''")
        ssh_cmd = f"system '{cl_escaped}'"
        result = subprocess.run(
            ["ssh", f"{self.user}@{self.host}", ssh_cmd],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"CL command failed: {stderr}")
        return result.stdout

    def _odbc_cl(self, command: str) -> str:
        """Execute CL command via ODBC QCMDEXC stored procedure."""
        cl_escaped = command.replace("'", "''")
        cursor = self._odbc_conn.cursor()
        cursor.execute(f"CALL QSYS2.QCMDEXC('{cl_escaped}')")
        return "OK"

    def _ibm_db_cl(self, command: str) -> str:
        """Execute CL command via ibm_db QCMDEXC."""
        import ibm_db

        cl_escaped = command.replace("'", "''")
        ibm_db.exec_immediate(
            self._ibm_conn, f"CALL QSYS2.QCMDEXC('{cl_escaped}')"
        )
        return "OK"

    # ------------------------------------------------------------------
    # OUTFILE Workflow: CL + OUTPUT(*OUTFILE) -> CPYTOIMPF -> CSV -> parse
    # ------------------------------------------------------------------

    def fetch_outfile(
        self, cl_cmd: str, outfile_lib: str, outfile_name: str
    ) -> list:
        """Execute CL with OUTPUT(*OUTFILE), convert to CSV, return parsed rows.

        Strategy:
          1. Run CL command (caller includes OUTPUT(*OUTFILE) OUTFILE(...))
          2. CPYTOIMPF → CSV in IFS
          3. Read CSV via SSH cat or SQL
          4. Cleanup temp files

        Returns list of dicts (one per record).
        """
        ifs_path = f"/tmp/cobol_spec_{outfile_name}.csv"

        # Step 1: Run the CL command
        try:
            self.run_cl(cl_cmd)
        except RuntimeError:
            # Outfile might already exist; delete and retry
            try:
                self.run_cl(f"DLTF FILE({outfile_lib}/{outfile_name})")
            except RuntimeError:
                pass
            self.run_cl(cl_cmd)

        # Step 2: Convert outfile to CSV in IFS via CPYTOIMPF
        cpytoimpf_cmd = (
            f"CPYTOIMPF FROMFILE({outfile_lib}/{outfile_name}) "
            f"TOSTMF('{ifs_path}') MBROPT(*REPLACE) "
            f"STMFCODPAG(*PCASCII) RCDDLM(*CRLF) "
            f"STRDLM(*DBLQUOTE) FLDDLM(',') ADDCOLNAM(*SQL)"
        )
        self.run_cl(cpytoimpf_cmd)

        # Step 3: Read CSV from IFS
        csv_text = self.read_ifs_file(ifs_path)

        # Step 4: Cleanup
        try:
            self.run_cl(f"DLTF FILE({outfile_lib}/{outfile_name})")
        except RuntimeError:
            pass
        try:
            self.run_cl(f"RMVLNK OBJLNK('{ifs_path}')")
        except RuntimeError:
            pass

        return self._parse_csv(csv_text)

    # ------------------------------------------------------------------
    # IFS File Access
    # ------------------------------------------------------------------

    def read_ifs_file(self, path: str) -> str:
        """Read a file from the Integrated File System (IFS)."""
        if self.method == "ssh":
            result = subprocess.run(
                ["ssh", f"{self.user}@{self.host}", f"cat '{path}'"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to read IFS file {path}: {result.stderr}")
            return result.stdout
        elif self.method in ("odbc", "ibm_db"):
            return self._sql_read_ifs(path)
        else:
            raise ConnectionError("Not connected.")

    def _sql_read_ifs(self, path: str) -> str:
        """Read an IFS file via SQL table function."""
        path_escaped = path.replace("'", "''")
        sql = (
            "SELECT CAST(LINE AS VARCHAR(32740)) AS LINE "
            f"FROM TABLE(QSYS2.IFS_READ(PATH_NAME => '{path_escaped}'))"
        )
        if self.method == "odbc":
            cursor = self._odbc_conn.cursor()
            cursor.execute(sql)
            lines = [row[0] for row in cursor.fetchall()]
            return "\n".join(lines)
        elif self.method == "ibm_db":
            import ibm_db

            stmt = ibm_db.exec_immediate(self._ibm_conn, sql)
            lines = []
            row = ibm_db.fetch_assoc(stmt)
            while row:
                lines.append(row.get("LINE", ""))
                row = ibm_db.fetch_assoc(stmt)
            return "\n".join(lines)
        return ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_csv(csv_text: str) -> list:
        """Parse CSV text (with header row) into list of dicts."""
        text = csv_text.strip()
        if not text:
            return []
        reader = csv.DictReader(io.StringIO(text))
        return [
            {k: v.strip() if isinstance(v, str) else v for k, v in row.items()}
            for row in reader
        ]

    def close(self):
        """Close any open connections."""
        if self._odbc_conn:
            try:
                self._odbc_conn.close()
            except Exception:
                pass
            self._odbc_conn = None
        if self._ibm_conn:
            try:
                import ibm_db

                ibm_db.close(self._ibm_conn)
            except Exception:
                pass
            self._ibm_conn = None


# ======================================================================
# CLI
# ======================================================================


def interactive_setup():
    """Interactive configuration wizard."""
    print("=== AS/400 Connection Setup ===\n")
    host = input("AS/400 hostname or IP: ").strip()
    user = input("Username: ").strip()

    if not host or not user:
        print("Error: host and user are required.")
        sys.exit(1)

    conn = AS400Connection(host=host, user=user)
    conn._save_config()

    print(f"\nConfig saved to {CONFIG_FILE}")
    print("Note: Password is NOT saved on disk.")
    print("  Use AS400_PASSWORD env var or SSH key auth.\n")

    print("Testing connection...")
    result = conn.test_connection()
    if result["connected"]:
        print(f"SUCCESS — connected via {result['method']}")
    else:
        print(f"FAILED — tried: {', '.join(result['methods_tried'])}")
        print(f"Error: {result.get('error', 'Unknown')}")
        print("\nTroubleshooting:")
        print("  SSH:    ssh-keygen && ssh-copy-id user@host")
        print("  ODBC:   pip install pyodbc + IBM i Access Client Solutions")
        print("  ibm_db: pip install ibm_db")
    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="AS/400 Connection Manager — auto-detect SSH/ODBC/ibm_db"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--test", action="store_true", help="Test connection")
    group.add_argument("--setup", action="store_true", help="Interactive setup wizard")
    group.add_argument("--run-cl", metavar="CMD", help="Execute a CL command")

    parser.add_argument("--host", help="AS/400 hostname (overrides config)")
    parser.add_argument("--user", help="AS/400 username (overrides config)")
    parser.add_argument("--password", help="AS/400 password (prefer env var)")

    args = parser.parse_args()

    if args.setup:
        interactive_setup()
        return

    conn = AS400Connection(
        host=args.host,
        user=args.user,
        password=args.password,
    )

    if args.test:
        result = conn.test_connection()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        conn.close()
        sys.exit(0 if result["connected"] else 1)

    if args.run_cl:
        if not conn.connect():
            print("Error: Could not connect to AS/400.", file=sys.stderr)
            print("Run: python3 as400_connector.py --setup", file=sys.stderr)
            sys.exit(1)
        try:
            output = conn.run_cl(args.run_cl)
            print(output)
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            conn.close()


if __name__ == "__main__":
    main()
