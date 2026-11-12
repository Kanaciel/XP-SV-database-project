import os
import sqlite3
from contextlib import closing
from typing import Any, Dict, List, Optional, Set

from config import NetworkTarget


def normalize_path(path: str) -> str:
    """Cheap, filesystem-free path key (no network round trip).

    Used both when seeding the "already seen" cache from the database and
    when checking files found on disk, so the two always compare equally.
    """
    return os.path.normcase(os.path.abspath(path))


class DatabaseManager:
    COLUMNS = (
        "full_serial_number", "po_number", "part_number", "serial_number",
        "result", "test_datetime", "file_modification_time", "program_name",
        "operator", "test_station", "file_name", "file_path",
    )

    def __init__(self, db_path: str = "test_reports.db"):
        self.db_path = db_path
        self._initialize_schema()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _initialize_schema(self):
        with closing(self._get_connection()) as conn:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS test_reports (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        full_serial_number TEXT,
                        po_number TEXT,
                        part_number TEXT,
                        serial_number TEXT,
                        result TEXT,
                        test_datetime TEXT,
                        file_modification_time TEXT,
                        program_name TEXT,
                        operator TEXT,
                        test_station TEXT,
                        file_name TEXT,
                        file_path TEXT UNIQUE
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS network_targets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        path TEXT NOT NULL UNIQUE,
                        test_station TEXT,
                        parser_type TEXT NOT NULL DEFAULT 'auto',
                        enabled INTEGER NOT NULL DEFAULT 1,
                        username TEXT,
                        password TEXT
                    )
                """)

    # ------------------------------------------------------------------
    # Password handling. Stored as plain text for now. When you add
    # encryption, change ONLY these two methods; everything else already
    # goes through them.
    # ------------------------------------------------------------------
    @staticmethod
    def _encode_password(plain: Optional[str]) -> Optional[str]:
        return plain  # TODO: encrypt

    @staticmethod
    def _decode_password(stored: Optional[str]) -> Optional[str]:
        return stored  # TODO: decrypt

    # ------------------------------------------------------------------
    # Network targets
    # ------------------------------------------------------------------
    def get_targets(self, include_disabled: bool = True) -> List[NetworkTarget]:
        query = (
            "SELECT path, test_station, parser_type, enabled, username, password "
            "FROM network_targets"
        )
        if not include_disabled:
            query += " WHERE enabled = 1"
        query += " ORDER BY id"

        with closing(self._get_connection()) as conn:
            rows = conn.execute(query).fetchall()

        return [
            NetworkTarget(
                path=r[0],
                test_station=r[1],
                parser_type=r[2],
                enabled=bool(r[3]),
                username=r[4],
                password=self._decode_password(r[5]),
            )
            for r in rows
        ]

    def upsert_target(self, target: NetworkTarget) -> None:
        """Add a target, or update it if its path already exists."""
        with closing(self._get_connection()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO network_targets
                        (path, test_station, parser_type, enabled, username, password)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        test_station = excluded.test_station,
                        parser_type  = excluded.parser_type,
                        enabled      = excluded.enabled,
                        username     = excluded.username,
                        password     = excluded.password
                    """,
                    (
                        target.path,
                        target.test_station,
                        target.parser_type,
                        int(target.enabled),
                        target.username,
                        self._encode_password(target.password),
                    ),
                )

    def set_target_enabled(self, path: str, enabled: bool) -> bool:
        with closing(self._get_connection()) as conn:
            with conn:
                cur = conn.execute(
                    "UPDATE network_targets SET enabled = ? WHERE path = ?",
                    (int(enabled), path),
                )
                return cur.rowcount > 0

    def delete_target(self, path: str) -> bool:
        with closing(self._get_connection()) as conn:
            with conn:
                cur = conn.execute(
                    "DELETE FROM network_targets WHERE path = ?", (path,)
                )
                return cur.rowcount > 0

    def seed_targets_if_empty(self, targets: List[NetworkTarget]) -> int:
        """Copy initial targets into the table, only if it has no rows yet."""
        with closing(self._get_connection()) as conn:
            count = conn.execute("SELECT COUNT(*) FROM network_targets").fetchone()[0]
        if count > 0:
            return 0
        for t in targets:
            self.upsert_target(t)
        return len(targets)

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------
    def load_known_paths(self) -> Set[str]:
        """Return every file path already stored, normalized for lookup."""
        with closing(self._get_connection()) as conn:
            rows = conn.execute("SELECT file_path FROM test_reports")
            return {normalize_path(r[0]) for r in rows if r[0]}

    def insert_reports(self, rows: List[Dict[str, Any]]) -> int:
        """Insert many reports in a single transaction.

        Returns the number of rows actually inserted (rows whose file_path
        already exists are ignored by the UNIQUE constraint).
        """
        if not rows:
            return 0

        placeholders = ", ".join("?" for _ in self.COLUMNS)
        query = (
            f"INSERT OR IGNORE INTO test_reports ({', '.join(self.COLUMNS)}) "
            f"VALUES ({placeholders})"
        )
        values = [tuple(r.get(c) for c in self.COLUMNS) for r in rows]

        with closing(self._get_connection()) as conn:
            before = conn.total_changes
            with conn:  # one transaction / one commit for the whole batch
                conn.executemany(query, values)
            return conn.total_changes - before

    def insert_report(self, data: Dict[str, Any]) -> bool:
        """Single-row insert, kept for backwards compatibility."""
        return self.insert_reports([data]) > 0
