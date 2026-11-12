
"""Master accounts, stored in their own small database file (accounts.db).

Passwords are never stored: only a salted hash is saved, so even someone who
copies accounts.db cannot read them.
"""
import datetime
import os
import re
import sqlite3

from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
ACCOUNTS_DB_PATH = os.path.join(BASE_DIR, "accounts.db")

MIN_PASSWORD_LEN = 8
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")

# Used so a wrong username takes as long to reject as a wrong password
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def _connect():
    con = sqlite3.connect(ACCOUNTS_DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _public(row):
    """Account info that is safe to keep in memory / show (no password hash)."""
    return {"id": row["id"], "username": row["username"],
            "display_name": row["display_name"], "role": row["role"]}


def init_accounts_db():
    con = _connect()
    try:
        with con:
            con.execute("""CREATE TABLE IF NOT EXISTS accounts (
                               id            INTEGER PRIMARY KEY AUTOINCREMENT,
                               username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
                               display_name  TEXT,
                               password_hash TEXT NOT NULL,
                               role          TEXT NOT NULL DEFAULT 'master',
                               is_active     INTEGER NOT NULL DEFAULT 1,
                               created_at    TEXT NOT NULL,
                               last_login    TEXT)""")
    finally:
        con.close()


def _check_new_password(password):
    if len(password) < MIN_PASSWORD_LEN:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")


def create_account(username, password, display_name=None, role="master"):
    username = username.strip()
    if not USERNAME_RE.match(username):
        raise ValueError("Username must be 3-32 characters: letters, digits, _ . -")
    _check_new_password(password)
    con = _connect()
    try:
        with con:
            con.execute(
                "INSERT INTO accounts (username, display_name, password_hash, role, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (username, display_name or None, generate_password_hash(password), role, _now()))
    except sqlite3.IntegrityError:
        raise ValueError(f"Username '{username}' already exists.")
    finally:
        con.close()


def authenticate(username, password):
    """Return the account (dict) if username + password are right and the account
    is active, otherwise None."""
    con = _connect()
    try:
        row = con.execute("SELECT * FROM accounts WHERE username = ?", (username.strip(),)).fetchone()
        if row is None or not row["is_active"]:
            check_password_hash(_DUMMY_HASH, password)
            return None
        if not check_password_hash(row["password_hash"], password):
            return None
        with con:
            con.execute("UPDATE accounts SET last_login = ? WHERE id = ?", (_now(), row["id"]))
        return _public(row)
    finally:
        con.close()


def get_active_account(account_id):
    """Used on every request, so disabling/deleting an account takes effect at once."""
    con = _connect()
    try:
        row = con.execute("SELECT * FROM accounts WHERE id = ? AND is_active = 1", (account_id,)).fetchone()
        return _public(row) if row else None
    finally:
        con.close()


def list_accounts():
    con = _connect()
    try:
        return [dict(r) for r in con.execute(
            "SELECT id, username, display_name, role, is_active, created_at, last_login "
            "FROM accounts ORDER BY id")]
    finally:
        con.close()


def set_password(username, password):
    _check_new_password(password)
    con = _connect()
    try:
        with con:
            cur = con.execute("UPDATE accounts SET password_hash = ? WHERE username = ?",
                              (generate_password_hash(password), username.strip()))
        return cur.rowcount > 0
    finally:
        con.close()


def set_active(username, active):
    con = _connect()
    try:
        with con:
            cur = con.execute("UPDATE accounts SET is_active = ? WHERE username = ?",
                              (1 if active else 0, username.strip()))
        return cur.rowcount > 0
    finally:
        con.close()


def delete_account(username):
    con = _connect()
    try:
        with con:
            cur = con.execute("DELETE FROM accounts WHERE username = ?", (username.strip(),))
        return cur.rowcount > 0
    finally:
        con.close()

        