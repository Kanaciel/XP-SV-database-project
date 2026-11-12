import sqlite3

import pytest

import credentials
from config import NetworkTarget
from database import DatabaseManager
from schema import COLUMN_NAMES

OLD_SCHEMA = """
CREATE TABLE test_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_serial_number TEXT, po_number TEXT, part_number TEXT, serial_number TEXT,
    result TEXT, test_datetime TEXT, file_modification_time TEXT, program_name TEXT,
    operator TEXT, test_station TEXT, file_name TEXT, file_path TEXT UNIQUE);
CREATE TABLE network_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL UNIQUE, test_station TEXT,
    parser_type TEXT NOT NULL DEFAULT 'auto', enabled INTEGER NOT NULL DEFAULT 1,
    username TEXT, password TEXT);
"""


def test_new_database_has_all_columns(tmp_path):
    db = DatabaseManager(tmp_path / "t.db")
    conn = sqlite3.connect(db.db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(test_reports)")]
    assert cols == ["id", *COLUMN_NAMES]


def test_old_database_is_migrated_and_backfilled(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute("INSERT INTO test_reports (test_datetime, file_path) VALUES "
                 "('2026/03/05 03:00:39 PM', 'a'), (NULL, 'b')")
    conn.commit()
    conn.close()

    DatabaseManager(path)
    conn = sqlite3.connect(path)
    rows = conn.execute("SELECT id, file_path, test_datetime_iso FROM test_reports ORDER BY id").fetchall()
    assert rows == [(1, "a", "2026-03-05T15:00:39"), (2, "b", None)]  # ids unchanged


def test_insert_skips_duplicates_and_unknown_keys(tmp_path):
    db = DatabaseManager(tmp_path / "t.db")
    row = {"file_path": "x", "result": "PASS", "not_a_column": 1}
    assert db.insert_reports([row, dict(row)]) == 1
    assert db.insert_reports([row]) == 0
    assert db.load_known_paths()


def test_passwords_are_encrypted_at_rest(tmp_path, fake_dpapi):
    db = DatabaseManager(tmp_path / "t.db")
    db.upsert_target(NetworkTarget(path=r"\\h\R", username=" u ", password="hunter2"))
    stored = sqlite3.connect(db.db_path).execute("SELECT username, password FROM network_targets").fetchone()
    assert stored[0] == "u"
    assert stored[1].startswith(credentials.PREFIX) and "hunter2" not in stored[1]
    assert db.get_targets()[0].password == "hunter2"
    assert "hunter2" not in repr(db.get_targets()[0])


def test_legacy_plaintext_passwords_get_encrypted(tmp_path, fake_dpapi):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute(r"INSERT INTO network_targets (path, username, password) VALUES ('\\h\R', 'u', 'plain')")
    conn.commit()
    conn.close()

    db = DatabaseManager(path)
    assert db.encrypt_legacy_passwords() == 1
    assert db.encrypt_legacy_passwords() == 0
    raw = sqlite3.connect(path).execute("SELECT password FROM network_targets").fetchone()[0]
    assert raw.startswith(credentials.PREFIX)
    assert db.get_targets()[0].password == "plain"


def test_keep_password_on_edit(tmp_path, fake_dpapi):
    db = DatabaseManager(tmp_path / "t.db")
    db.upsert_target(NetworkTarget(path="p", username="u", password="pw"))
    db.upsert_target(NetworkTarget(path="p", test_station="S", username="u"), keep_password=True)
    t = db.get_targets()[0]
    assert t.test_station == "S" and t.password == "pw"


def test_undecryptable_password_does_not_break_other_targets(tmp_path, fake_dpapi, monkeypatch):
    db = DatabaseManager(tmp_path / "t.db")
    db.upsert_target(NetworkTarget(path="a", username="u", password="pw"))
    db.upsert_target(NetworkTarget(path="b"))

    def boom(blob):
        raise OSError("wrong account")
    monkeypatch.setattr(credentials, "_unprotect", boom)
    targets = db.get_targets()
    assert [t.path for t in targets] == ["a", "b"]
    assert targets[0].password is None


def test_encrypt_without_windows_raises(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "win32crypt", None)
    with pytest.raises(credentials.CredentialError):
        credentials.encrypt("x")
