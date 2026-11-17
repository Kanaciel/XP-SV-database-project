import logging
import os
import sqlite3
from contextlib import closing
from typing import Any, Dict, Iterable, List, Optional, Set

import credentials
from config import NetworkTarget
from parsers import normalize_datetime
from schema import COLUMN_NAMES, REPORT_COLUMNS

log = logging.getLogger(__name__)


def normalize_path(path: str) -> str:
    """Cheap, filesystem-free path key (no network round trip).

    Used both when seeding the "already seen" cache from the database and
    when checking files found on disk, so the two always compare equally.
    """
    return os.path.normcase(os.path.abspath(path))


class DatabaseManager:
    # Kept for code that still imports it; the real list lives in schema.py.
    COLUMNS = COLUMN_NAMES

    def __init__(self, db_path: str = "test_reports.db", busy_timeout: float = 30.0):
        self.db_path = str(db_path)
        self.busy_timeout = busy_timeout
        self._initialize_schema()

    def _get_connection(self) -> sqlite3.Connection:
        # timeout: wait for locks held by other processes (e.g. the web app)
        # instead of failing immediately with "database is locked".
        conn = sqlite3.connect(self.db_path, timeout=self.busy_timeout)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ------------------------------------------------------------------
    # Schema & migrations
    # ------------------------------------------------------------------
    def _initialize_schema(self):
        with closing(self._get_connection()) as conn:
            # WAL lets the web app read while the scanner writes.
            conn.execute("PRAGMA journal_mode = WAL")
            with conn:
                column_defs = ",\n".join(
                    f"{c.name} {c.sql_type}{' UNIQUE' if c.unique else ''}"
                    for c in REPORT_COLUMNS
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS test_reports (\n"
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
                    f"{column_defs})"
                )
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
                added = self._add_missing_columns(conn)
                for col in REPORT_COLUMNS:
                    if col.indexed:
                        conn.execute(
                            f"CREATE INDEX IF NOT EXISTS idx_test_reports_{col.name} "
                            f"ON test_reports ({col.name})"
                        )
        if added:
            log.info("Added new column(s) to test_reports: %s", ", ".join(added))
        self._backfill_datetime_iso()

    def _add_missing_columns(self, conn: sqlite3.Connection) -> List[str]:
        """ALTER TABLE for every column in schema.py the table doesn't have yet."""
        existing = {r[1] for r in conn.execute("PRAGMA table_info(test_reports)")}
        added = []
        for col in REPORT_COLUMNS:
            if col.name not in existing:
                conn.execute(f"ALTER TABLE test_reports ADD COLUMN {col.name} {col.sql_type}")
                added.append(col.name)
        return added

    def _backfill_datetime_iso(self) -> None:
        """Fill test_datetime_iso for rows stored before that column existed."""
        with closing(self._get_connection()) as conn:
            rows = conn.execute(
                "SELECT id, test_datetime FROM test_reports "
                "WHERE test_datetime_iso IS NULL AND test_datetime IS NOT NULL"
            ).fetchall()
            updates = [(iso, rid) for rid, raw in rows
                       if (iso := normalize_datetime(raw)) is not None]
            if updates:
                with conn:
                    conn.executemany(
                        "UPDATE test_reports SET test_datetime_iso = ? WHERE id = ?", updates
                    )
                log.info("Backfilled test_datetime_iso for %d rows.", len(updates))

    # ------------------------------------------------------------------
    # Password handling. All reads/writes of the password column go
    # through these two methods (see credentials.py).
    # ------------------------------------------------------------------
    @staticmethod
    def _encode_password(plain: Optional[str]) -> Optional[str]:
        return credentials.encrypt(plain)

    @staticmethod
    def _decode_password(stored: Optional[str]) -> Optional[str]:
        return credentials.decrypt(stored)

    def encrypt_legacy_passwords(self) -> int:
        """Encrypt any password still stored as plain text. Returns how many."""
        with closing(self._get_connection()) as conn:
            rows = conn.execute(
                "SELECT id, password FROM network_targets "
                "WHERE password IS NOT NULL AND password <> ''"
            ).fetchall()
            legacy = [(rid, pw) for rid, pw in rows if not credentials.is_encrypted(pw)]
            if not legacy:
                return 0
            with conn:
                conn.executemany(
                    "UPDATE network_targets SET password = ? WHERE id = ?",
                    [(self._encode_password(pw), rid) for rid, pw in legacy],
                )
        return len(legacy)

    # ------------------------------------------------------------------
    # Network targets
    # ------------------------------------------------------------------
    def get_targets(self, include_disabled: bool = True,
                    with_passwords: bool = True) -> List[NetworkTarget]:
        query = (
            "SELECT path, test_station, parser_type, enabled, username, password "
            "FROM network_targets"
        )
        if not include_disabled:
            query += " WHERE enabled = 1"
        query += " ORDER BY id"

        with closing(self._get_connection()) as conn:
            rows = conn.execute(query).fetchall()

        targets = []
        for r in rows:
            password = None
            if with_passwords and r[5]:
                try:
                    password = self._decode_password(r[5])
                except credentials.CredentialError as e:
                    # One unreadable password must not stop the others.
                    log.error("Target %s: %s", r[0], e)
            targets.append(NetworkTarget(
                path=r[0], test_station=r[1], parser_type=r[2],
                enabled=bool(r[3]), username=r[4], password=password,
            ))
        return targets

    def paths_with_password(self) -> Set[str]:
        with closing(self._get_connection()) as conn:
            rows = conn.execute(
                "SELECT path FROM network_targets WHERE password IS NOT NULL AND password <> ''"
            ).fetchall()
        return {r[0] for r in rows}

    def get_target(self, path: str) -> Optional[NetworkTarget]:
        for t in self.get_targets(with_passwords=False):
            if t.path == path:
                return t
        return None

    def upsert_target(self, target: NetworkTarget, keep_password: bool = False) -> None:
        """Add a target, or update it if its path already exists.

        keep_password=True leaves an existing stored password untouched
        (useful when editing station name / username only).
        """
        pw_update = "" if keep_password else ", password = excluded.password"
        with closing(self._get_connection()) as conn:
            with conn:
                conn.execute(
                    f"""
                    INSERT INTO network_targets
                        (path, test_station, parser_type, enabled, username, password)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        test_station = excluded.test_station,
                        parser_type  = excluded.parser_type,
                        enabled      = excluded.enabled,
                        username     = excluded.username
                        {pw_update}
                    """,
                    (
                        target.path, target.test_station, target.parser_type,
                        int(target.enabled), target.username,
                        self._encode_password(target.password),
                    ),
                )

    def set_target_password(self, path: str, password: Optional[str]) -> bool:
        with closing(self._get_connection()) as conn:
            with conn:
                cur = conn.execute(
                    "UPDATE network_targets SET password = ? WHERE path = ?",
                    (self._encode_password(password), path),
                )
                return cur.rowcount > 0

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
                cur = conn.execute("DELETE FROM network_targets WHERE path = ?", (path,))
                return cur.rowcount > 0

    def seed_targets_if_empty(self, targets: Iterable[NetworkTarget]) -> int:
        """Copy initial targets into the table, only if it has no rows yet."""
        targets = list(targets)
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
        already exists are ignored by the UNIQUE constraint). Keys a parser
        returns that are not in schema.py are ignored.
        """
        if not rows:
            return 0

        placeholders = ", ".join("?" for _ in COLUMN_NAMES)
        query = (
            f"INSERT OR IGNORE INTO test_reports ({', '.join(COLUMN_NAMES)}) "
            f"VALUES ({placeholders})"
        )
        values = [tuple(r.get(c) for c in COLUMN_NAMES) for r in rows]

        with closing(self._get_connection()) as conn:
            before = conn.total_changes
            with conn:  # one transaction / one commit for the whole batch
                conn.executemany(query, values)
            return conn.total_changes - before

    def insert_report(self, data: Dict[str, Any]) -> bool:
        """Single-row insert, kept for backwards compatibility."""
        return self.insert_reports([data]) > 0
