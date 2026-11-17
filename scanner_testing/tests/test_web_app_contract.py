"""The promises the scanner makes to the web app.

The web app never imports scanner code. The two only share test_reports.db,
so these tests pin down what the web app relies on. If one of them fails,
a scanner change would break the web app: fix the change, not the test.
(See README, "Sharing the database with the web app".)
"""
import sqlite3
from pathlib import Path

from database import DatabaseManager
from schema import COLUMN_NAMES

# Columns the web app filters on or shows by default (web app/app.py: NEEDED_COLUMNS).
WEB_APP_COLUMNS = {"id", "full_serial_number", "result", "file_path",
                   "po_number", "part_number", "serial_number"}


def _read_only(path) -> sqlite3.Connection:
    # Exactly how the web app opens the file.
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=10)


def _row(n):
    return {"file_path": f"r{n}.txt", "full_serial_number": f"PO~PN~01~SN{n}", "result": "PASS"}


def test_web_app_columns_exist(tmp_path):
    db = DatabaseManager(tmp_path / "t.db")
    cols = {r[1] for r in sqlite3.connect(db.db_path).execute("PRAGMA table_info(test_reports)")}
    assert WEB_APP_COLUMNS <= cols
    assert WEB_APP_COLUMNS - {"id"} <= set(COLUMN_NAMES)


def test_report_ids_never_change_or_get_reused(tmp_path):
    # Notes and ATE checks in the web app are keyed by test_reports.id.
    db = DatabaseManager(tmp_path / "t.db")
    db.insert_reports([_row(1), _row(2)])
    con = sqlite3.connect(db.db_path)
    before = dict(con.execute("SELECT file_path, id FROM test_reports"))

    db.insert_reports([_row(1), _row(3)])          # rescan sees r1 again
    DatabaseManager(db.db_path)                    # restart = migrations run again
    after = dict(con.execute("SELECT file_path, id FROM test_reports"))
    assert {k: after[k] for k in before} == before

    con.execute("DELETE FROM test_reports WHERE file_path = 'r3.txt'")
    con.commit()
    db.insert_reports([_row(4)])
    new_id = con.execute("SELECT id FROM test_reports WHERE file_path = 'r4.txt'").fetchone()[0]
    assert new_id > after["r3.txt"]                # AUTOINCREMENT: a deleted id is never handed out again


def test_web_app_can_read_while_scanner_writes(tmp_path):
    db = DatabaseManager(tmp_path / "t.db")
    db.insert_reports([_row(1)])
    con = sqlite3.connect(db.db_path)
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    writer = sqlite3.connect(db.db_path)
    writer.execute("BEGIN IMMEDIATE")              # scanner mid-batch, holding the write lock
    writer.execute("INSERT INTO test_reports (file_path) VALUES ('r2.txt')")
    reader = _read_only(db.db_path)
    assert reader.execute("SELECT COUNT(*) FROM test_reports").fetchone()[0] == 1  # not blocked
    writer.commit()
    assert reader.execute("SELECT COUNT(*) FROM test_reports").fetchone()[0] == 2  # sees the commit


def test_scanner_can_write_while_web_app_reads(tmp_path):
    db = DatabaseManager(tmp_path / "t.db", busy_timeout=2)
    reader = _read_only(db.db_path)
    reader.execute("BEGIN")
    reader.execute("SELECT COUNT(*) FROM test_reports").fetchone()  # open read transaction
    assert db.insert_reports([_row(1)]) == 1
    reader.rollback()


def test_read_only_uri_handles_spaces_and_hash(tmp_path):
    folder = tmp_path / "class VGU edition #2"
    folder.mkdir()
    db = DatabaseManager(folder / "test_reports.db")
    db.insert_reports([_row(1)])
    assert _read_only(db.db_path).execute("SELECT COUNT(*) FROM test_reports").fetchone()[0] == 1
