
import os
import secrets
import sqlite3
import datetime
import threading
import time
from flask import (Flask, render_template, jsonify, request, abort,
                   session, redirect, url_for, g)

import accounts

app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "test_reports.db")

API_TOKEN = os.environ.get("KO_PHAI_TEST_THI_CUT", "123")
PAGE_SIZE = 50

# ---- Login (master accounts) ----------------------------------------------
# The key that signs the login cookie. It is created once and saved in
# secret_key.txt so logins survive a restart. Keep that file private.
SECRET_KEY_PATH = os.path.join(BASE_DIR, "secret_key.txt")


def load_secret_key():
    env = os.environ.get("TEST_REPORTS_SECRET")
    if env:
        return env
    if os.path.exists(SECRET_KEY_PATH):
        with open(SECRET_KEY_PATH, encoding="utf-8") as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(SECRET_KEY_PATH, "w", encoding="utf-8") as f:
        f.write(key)
    return key


app.secret_key = load_secret_key()
app.config.update(
    SESSION_COOKIE_NAME="test_reports_session",   # own name: cookies are shared between ports
    SESSION_COOKIE_HTTPONLY=True,                 # JavaScript cannot read the cookie
    SESSION_COOKIE_SAMESITE="Lax",                # not sent with requests from other websites
    PERMANENT_SESSION_LIFETIME=datetime.timedelta(hours=8),
)

accounts.init_accounts_db()

# Slow down password guessing: max 5 wrong attempts per PC in 5 minutes
MAX_FAILS, FAIL_WINDOW = 5, 300
_fails = {}
_fails_lock = threading.Lock()


def recent_fails(ip):
    now = time.time()
    with _fails_lock:
        _fails[ip] = [t for t in _fails.get(ip, []) if now - t < FAIL_WINDOW]
        return len(_fails[ip])


def add_fail(ip):
    with _fails_lock:
        _fails.setdefault(ip, []).append(time.time())


def clear_fails(ip):
    with _fails_lock:
        _fails.pop(ip, None)


def current_master():
    """The logged-in master account (dict) or None. Re-checked against accounts.db
    on every request, so a disabled or deleted account loses access immediately."""
    if not hasattr(g, "master"):
        g.master = None
        uid = session.get("uid")
        if uid:
            g.master = accounts.get_active_account(uid)
            if g.master is None:
                session.clear()
    return g.master


@app.context_processor
def inject_master():
    return {"master": current_master()}


# View modes shown as buttons above the filters: (key, label).
# To add a new mode later: add it here, then add a matching block in index.html.
MODES = [
    ("table", "Table"),
    ("graph", "Graph"),
]
DEFAULT_MODE = "table"

# Columns shown in the table when the page is first opened (all others are hidden
# until ticked). Names must match the database column names.
DEFAULT_COLUMNS = ["id", "full_serial_number", "result", "ate_check", "note", "file_path"]

# Filters shown on the page: column name -> "like" (contains) or "exact"
FILTERS = {
    "po_number": "like",
    "part_number": "like",
    "serial_number": "like",
    "result": "exact",
}


# ---- ATE check (verified ticks) ------------------------------------------
# Stored in its OWN small database file, so test_reports.db is never modified
# and the ticks survive if you replace test_reports.db with a newer copy.
ATE_DB_PATH = os.path.join(BASE_DIR, "ate_checks.db")
ATE_COLUMN = "ate_check"      # virtual column, not part of test_reports


def init_ate_db():
    con = sqlite3.connect(ATE_DB_PATH, timeout=10)
    try:
        with con:
            con.execute("""CREATE TABLE IF NOT EXISTS ate_checks (
                               report_id  INTEGER PRIMARY KEY,
                               checked_at TEXT NOT NULL,
                               checked_ip TEXT)""")
            cols = [r[1] for r in con.execute("PRAGMA table_info(ate_checks)")]
            if "checked_by" not in cols:          # older file: add the new column
                con.execute("ALTER TABLE ate_checks ADD COLUMN checked_by TEXT")
    finally:
        con.close()

# ---- Notes (written by masters, readable by everyone) ---------------------
# Also in its own file, so test_reports.db is never modified.
NOTES_DB_PATH = os.path.join(BASE_DIR, "notes.db")
NOTE_COLUMN = "note"          # virtual column, not part of test_reports
MAX_NOTE_LEN = 1000


def init_notes_db():
    con = sqlite3.connect(NOTES_DB_PATH, timeout=10)
    try:
        with con:
            con.execute("""CREATE TABLE IF NOT EXISTS report_notes (
                               report_id  INTEGER PRIMARY KEY,
                               note       TEXT NOT NULL,
                               updated_at TEXT NOT NULL,
                               updated_by TEXT)""")
    finally:
        con.close()


def get_note_map(ids):
    """{report_id: {"text": ..., "at": ..., "by": ...}} for the given report ids."""
    if not ids:
        return {}
    con = sqlite3.connect(NOTES_DB_PATH, timeout=10)
    try:
        marks = ",".join("?" * len(ids))
        rows = con.execute(
            f"SELECT report_id, note, updated_at, updated_by FROM report_notes WHERE report_id IN ({marks})", ids)
        return {r[0]: {"text": r[1], "at": r[2], "by": r[3]} for r in rows}
    finally:
        con.close()


init_notes_db()


def get_ate_map(ids):
    """{report_id: {"at": ..., "ip": ..., "by": ...}} for the given report ids."""
    if not ids:
        return {}
    con = sqlite3.connect(ATE_DB_PATH, timeout=10)
    try:
        marks = ",".join("?" * len(ids))
        rows = con.execute(
            f"SELECT report_id, checked_at, checked_ip, checked_by FROM ate_checks WHERE report_id IN ({marks})", ids)
        return {r[0]: {"at": r[1], "ip": r[2], "by": r[3]} for r in rows}
    finally:
        con.close()


init_ate_db()


def check_token():
    token = request.args.get("token") or request.headers.get("X-Token")
    if token != API_TOKEN:
        abort(401)


def connect():
    # Read-only: the web app can never modify the database
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def like_pattern(text):
    # Escape % and _ so the user's text is matched literally
    text = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{text}%"


def build_where(values, skip=()):
    clauses, params = [], []
    for col, mode in FILTERS.items():
        if col in skip:
            continue
        v = values.get(col, "").strip()
        if not v:
            continue
        if mode == "like":
            clauses.append(f"{col} LIKE ? ESCAPE '\\'")
            params.append(like_pattern(v))
        else:
            clauses.append(f"{col} = ?")
            params.append(v)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


PASS_LABELS = {"PASS", "PASSED"}
FAIL_LABELS = {"FAIL", "FAILED"}


def summarize(values):
    """Counts for the Graph mode. Uses the PO / part / serial filters but ignores
    the Result filter. Both charts are counted from the SAME set of reports."""
    where, params = build_where(values, skip=("result",))
    con = connect()
    try:
        counts = con.execute(
            "SELECT UPPER(TRIM(COALESCE(result, ''))) AS r, COUNT(*) "
            f"FROM test_reports{where} GROUP BY r", params).fetchall()

        # ATE check: join with the ticks file (read-only) and split the SAME reports
        con.execute("ATTACH DATABASE ? AS ate", (ATE_DB_PATH,))
        ate_checked, ate_unchecked = con.execute(
            "SELECT COALESCE(SUM(a.report_id IS NOT NULL), 0), COALESCE(SUM(a.report_id IS NULL), 0) "
            "FROM test_reports AS t LEFT JOIN ate.ate_checks AS a ON a.report_id = t.id"
            f"{where}", params).fetchone()
    finally:
        con.close()

    total = passed = failed = 0
    other = {}
    for label, n in counts:
        total += n
        if label in PASS_LABELS:
            passed += n
        elif label in FAIL_LABELS:
            failed += n
        else:
            other[label or "(empty)"] = n
    return {"total": total, "pass": passed, "fail": failed,
            "other": sum(other.values()), "other_detail": other,
            "ate_checked": ate_checked, "ate_unchecked": ate_unchecked}


def query_reports(values, page):
    where, params = build_where(values)
    con = connect()
    try:
        total = con.execute(f"SELECT COUNT(*) FROM test_reports{where}", params).fetchone()[0]
        cur = con.execute(
            f"SELECT * FROM test_reports{where} ORDER BY id LIMIT ? OFFSET ?",
            params + [PAGE_SIZE, (page - 1) * PAGE_SIZE],
        )
        columns = [d[0] for d in cur.description]
        rows = [dict(r) for r in cur.fetchall()]
        results = [r[0] for r in con.execute(
            "SELECT DISTINCT result FROM test_reports WHERE result IS NOT NULL AND result <> '' ORDER BY result")]
        overall = con.execute("SELECT COUNT(*) FROM test_reports").fetchone()[0]
    finally:
        con.close()
    return columns, rows, results, total, overall


@app.route("/")
def index():
    check_token()
    values = {c: request.args.get(c, "") for c in FILTERS}
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1

    columns, rows, results, total, overall = query_reports(values, page)
    pages = max(1, -(-total // PAGE_SIZE))   # ceiling division

    view = request.args.get("view", DEFAULT_MODE)
    if view not in dict(MODES):
        view = DEFAULT_MODE
    stats = summarize(values) if view == "graph" else None

    # Table mode: add the virtual "ate_check" column (right after "result")
    # and load which of the shown reports are already verified.
    ate, notes = {}, {}
    if view == "table":
        pos = columns.index("result") + 1 if "result" in columns else len(columns)
        columns = columns[:pos] + [ATE_COLUMN, NOTE_COLUMN] + columns[pos:]
        ids = [r["id"] for r in rows]
        ate = get_ate_map(ids)
        notes = get_note_map(ids)       # Graph mode never reads notes

    # Current filters + token, reused by the pagination links
    keep = {k: v for k, v in values.items() if v.strip()}
    keep["token"] = request.args.get("token")

    return render_template("index.html", columns=columns, rows=rows, results=results,
                           values=values, total=total, overall=overall,
                           page=page, pages=pages, keep=keep, page_size=PAGE_SIZE,
                           stats=stats, view=view, modes=MODES, default_cols=DEFAULT_COLUMNS,
                           ate=ate, notes=notes, max_note_len=MAX_NOTE_LEN,
                           can_edit=current_master() is not None,
                           token=request.args.get("token"))




@app.route("/login", methods=["GET", "POST"])
def login():
    check_token()
    token = request.args.get("token")
    view = request.args.get("view", DEFAULT_MODE)
    if view not in dict(MODES):
        view = DEFAULT_MODE

    error, status = None, 200
    if request.method == "POST":
        ip = request.remote_addr
        if recent_fails(ip) >= MAX_FAILS:
            error, status = "Too many wrong attempts. Please wait 5 minutes and try again.", 429
        else:
            acc = accounts.authenticate(request.form.get("username", ""), request.form.get("password", ""))
            if acc:
                clear_fails(ip)
                session.clear()
                session["uid"] = acc["id"]
                session.permanent = True
                return redirect(url_for("index", token=token, view=view))
            add_fail(ip)
            error, status = "Wrong username or password.", 401
    return render_template("login.html", token=token, view=view, error=error), status


@app.route("/logout", methods=["POST"])
def logout():
    check_token()
    session.clear()
    return redirect(url_for("index", token=request.args.get("token")))


@app.route("/api/ate/<int:report_id>", methods=["POST"])
def api_ate(report_id):
    check_token()
    master = current_master()
    if master is None:                      # viewers may look, but never change
        return jsonify(error="Master login required"), 401
    checked = bool((request.get_json(silent=True) or {}).get("checked"))

    con = connect()                      # main DB: read-only, only to confirm the report exists
    try:
        exists = con.execute("SELECT 1 FROM test_reports WHERE id = ?", (report_id,)).fetchone()
    finally:
        con.close()
    if not exists:
        abort(404)

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ate = sqlite3.connect(ATE_DB_PATH, timeout=10)
    try:
        with ate:
            if checked:
                # keeps the first verification time if it is already ticked
                ate.execute("INSERT OR IGNORE INTO ate_checks (report_id, checked_at, checked_ip, checked_by) VALUES (?, ?, ?, ?)",
                            (report_id, now, request.remote_addr, master["username"]))
            else:
                ate.execute("DELETE FROM ate_checks WHERE report_id = ?", (report_id,))
        row = ate.execute("SELECT checked_at, checked_by FROM ate_checks WHERE report_id = ?", (report_id,)).fetchone()
    finally:
        ate.close()
    return jsonify(ok=True, checked=bool(row), checked_at=row[0] if row else None,
                   checked_by=row[1] if row else None)


@app.route("/api/note/<int:report_id>", methods=["POST"])
def api_note(report_id):
    check_token()
    master = current_master()
    if master is None:                      # viewers may read notes, never change them
        return jsonify(error="Master login required"), 401

    note = (request.get_json(silent=True) or {}).get("note", "")
    if not isinstance(note, str):
        return jsonify(error="Invalid note"), 400
    note = note.replace("\r\n", "\n").strip()
    if len(note) > MAX_NOTE_LEN:
        return jsonify(error=f"Note is too long (max {MAX_NOTE_LEN} characters)"), 400

    con = connect()                      # main DB: read-only, only to confirm the report exists
    try:
        exists = con.execute("SELECT 1 FROM test_reports WHERE id = ?", (report_id,)).fetchone()
    finally:
        con.close()
    if not exists:
        abort(404)

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db = sqlite3.connect(NOTES_DB_PATH, timeout=10)
    try:
        with db:
            if note:
                db.execute("INSERT OR REPLACE INTO report_notes (report_id, note, updated_at, updated_by) "
                           "VALUES (?, ?, ?, ?)", (report_id, note, now, master["username"]))
            else:                        # an empty note removes it
                db.execute("DELETE FROM report_notes WHERE report_id = ?", (report_id,))
    finally:
        db.close()
    return jsonify(ok=True, note=note,
                   updated_at=now if note else None,
                   updated_by=master["username"] if note else None)

@app.route("/api/reports")
def api_reports():
    check_token()
    values = {c: request.args.get(c, "") for c in FILTERS}
    _, rows, _, _, _ = query_reports(values, 1)
    return jsonify(rows)


if __name__ == "__main__":
    if os.environ.get("DEV") == "1":
        app.run(host="127.0.0.1", port=5000, debug=True)
    else:
        from waitress import serve
        print("Serving on http://0.0.0.0:5000")
        serve(app, host="0.0.0.0", port=5000)

#access web link: http://127.0.0.1:5000/?token=123      

#To run:
#cd "c:\visual studio code\project\web app"
#.venv\Scripts\Activate.ps1
#$env:DEV="1"
#python app.py

#password:12345678


