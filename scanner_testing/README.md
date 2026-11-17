# Test report scanner (backend)

The scanner collects test reports from the test stations into one SQLite database.

Every cycle (30 minutes by default) it walks the shared `Reports` folder on each test station
and finds report files it hasn't seen yet. It parses each new file and stores one row per
report in `test_reports.db`. The web app reads that database.

```
 test stations (SMB shares)        scanner (this folder)                    web app
 \\172.24.120.248\Reports  ─┐
 \\172.24.123.61\Reports   ─┼─►  RunScanner ─► scanner ─► parsers ─►  test_reports.db  ─►  app.py
 \\172.24.122.194\Reports  ─┘         ▲                                     ▲
                                      └── network_targets table ◄── manage_targets.py
```

## Contents

1. [Files](#files)
2. [Setup](#setup)
3. [Testing a new version](#testing-a-new-version)
4. [Running the scanner](#running-the-scanner)
5. [Managing stations](#managing-stations)
6. [Passwords](#passwords)
7. [Settings](#settings)
8. [The database](#the-database)
9. [Sharing the database with the web app](#sharing-the-database-with-the-web-app)
10. [Adding a data column](#adding-a-data-column)
11. [Adding a report format](#adding-a-report-format)
12. [Logs and troubleshooting](#logs-and-troubleshooting)
13. [Stable and testing folders](#stable-and-testing-folders)

## Files

| File | What it does |
|---|---|
| `RunScanner.py` | Entry point. Opens the database, then scans every enabled station in a loop. |
| `scanner.py` | Scans one station: logs in, walks the folder, skips files it already knows, parses new files and saves them in batches. |
| `parsers.py` | Turns one report file into a dict of fields. Holds one parser per report format, plus the date formats. |
| `schema.py` | **The** list of report columns. Edit this to add data columns. |
| `database.py` | All SQLite access: creates and upgrades tables, inserts reports, reads and writes stations. |
| `credentials.py` | Encrypts and decrypts station passwords (Windows DPAPI). |
| `network_auth.py` | Logs in to a Windows share with a username and password. |
| `manage_targets.py` | Command-line tool to add, edit, pause and remove stations and to set passwords. |
| `config.py` | `NetworkTarget` definition, plus the starting station list (used only when the database is empty). |
| `settings.py` | Interval, delays, paths and similar options, read from `scanner_settings.env` or environment variables. |
| `scanner_settings.example.env` | Template for `scanner_settings.env`. |
| `logging_setup.py` | Writes logs to the console and to `logs/scanner.log`. |
| `tests/` | Automated tests (pytest). |
| `..\main.py` | (project folder) Starts the scanner and/or the web app from one window. See [Running the scanner](#running-the-scanner). |
| `..\requirements.txt` | (project folder) Packages for the scanner and the web app, installed into `..\.venv`. `requirements-dev.txt` adds pytest. |

## Setup

You need Windows, Python 3.8+ and network access to the stations.

Everything is installed once, into **one** virtual environment (`.venv`) in the **project
folder** (the one holding `main.py`, `scanner_stable\`, `scanner_testing\` and `web app\`).
The scanner and the web app share it, and the one `requirements.txt` there lists the
packages of both. In the project folder:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1               # prompt now starts with (.venv)
pip install -r requirements.txt          # beautifulsoup4, pywin32, flask, waitress
pip install -r requirements-dev.txt      # adds pytest, only needed for testing
```

Activate it again in every new terminal before running anything (`.venv\Scripts\Activate.ps1`
from the project folder; in cmd: `.venv\Scripts\activate.bat`). It stays active when you `cd`
into a subfolder. If PowerShell refuses to run the script, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once. You can also skip activating and
call the venv's Python directly: `.venv\Scripts\python.exe main.py`.

Don't commit the `.venv` folder (it is per-PC and large); recreate it from `requirements.txt` instead.
Keep `.venv/` in `.gitignore` when you turn that file back on.

When a new package is needed, add it to the project folder's `requirements.txt` and run
`pip install -r requirements.txt` again.

## Testing a new version

Do this in the **testing** folder, never in the stable one.

1. **Run the automated tests.** They don't need the network or real stations:
   ```powershell
   python -m pytest tests
   ```
   Every test should pass.

2. **Use a copy of the real data.** New code may upgrade the database (add columns, encrypt
   passwords), so test on a copy:
   ```powershell
   copy ..\scanner_stable\test_reports.db .
   ```

3. **Check the stations and set passwords.** See [Managing stations](#managing-stations).
   ```powershell
   python manage_targets.py list
   ```

4. **Do a small trial scan.** Create `scanner_settings.env` with these two lines (or see
   [Settings](#settings) for environment variables), so it parses at most 5 new files per
   station and loops every minute:
   ```
   XPSV_MAX_FILES_PER_TARGET=5
   XPSV_SCAN_INTERVAL_MINUTES=1
   ```
   Then run `python RunScanner.py`. Watch for `Scan end: ... inserted N` and for any `ERROR`
   lines, then stop with **Ctrl+C**. Delete those lines afterwards.

5. **Spot-check the data**, for example the newest reports:
   ```powershell
   python -c "import sqlite3; c=sqlite3.connect('test_reports.db'); [print(r) for r in c.execute('SELECT id, test_station, result, test_datetime_iso, file_name FROM test_reports ORDER BY id DESC LIMIT 10')]"
   ```

## Running the scanner

The easy way, from the project folder with the venv active:

```powershell
python main.py                 # scanner + web app, using scanner_stable
python main.py --testing       # scanner + web app, using scanner_testing
python main.py scanner         # only the scanner
python main.py web             # only the web app
```

`main.py` starts each program as its own process, shows their output in one window
(every line tagged `[scanner]` or `[web]`), prints the links to open the web app once it is up
(Ctrl+click them), and points both at the same database (the scanner
folder's `XPSV_DB_PATH`, by default its `test_reports.db`). **Ctrl+C** stops both, giving the
scanner time to save. If one of them crashes, the other keeps running and `main.py` prints a
warning. It never imports their code, so each still runs on its own too:

```powershell
cd scanner_stable
python RunScanner.py
```

On every start the scanner:
- creates the database if it doesn't exist and adds any new columns from `schema.py`;
- copies the stations from `config.py` into the database, only if there are none yet;
- encrypts any password still stored as plain text.

It also logs which settings differ from the defaults. Then it scans every enabled station, waits for the scan interval, and repeats. Stop it with
**Ctrl+C**; reports already parsed are saved before it exits.

Files it has already seen are skipped without being opened, so later cycles are fast.

## Managing stations

The stations live in the `network_targets` table. Manage them with `manage_targets.py`.
Editing `config.py` has no effect once the database has stations.
You **don't need to restart** the scanner after a change; it re-reads the list every cycle.

| Task | Command |
|---|---|
| List all stations | `python manage_targets.py list` |
| Add a station (no login) | `python manage_targets.py add "\\172.24.125.10\Reports" --station "Chroma 3"` |
| Add a station with a login | `python manage_targets.py add "\\172.24.125.10\Reports" --station "Chroma 3" --username "172.24.125.10\scanner"` (it asks for the password) |
| Rename a station / change its user | Run `add` again with the same path and only the options you want to change. Press Enter at the password prompt to keep the current one. |
| Change a password | `python manage_targets.py set-password "\\172.24.123.61\Reports"` |
| Pause / resume a station | `python manage_targets.py disable "<path>"` / `enable "<path>"` |
| Remove a station | `python manage_targets.py delete "<path>"` (its reports stay in the database) |
| Change a station's IP / path | `delete` the old path, then `add` the new one |
| Force a report parser | `python manage_targets.py add "<path>" --parser html` (see [Adding a report format](#adding-a-report-format)) |

Tips:
- Always put the path in quotes. Write it exactly as `list` shows it.
- If `--station` is left out, the station name is taken from the IP in the path.
- `python manage_targets.py --help` and `python manage_targets.py add --help` list every option.
- By default the tool works on `test_reports.db` in its own folder. Use `--db <file>` to point it at another database.

## Passwords

- **Never** put a password in `config.py` or any other file that goes into git.
- `manage_targets.py` reads passwords at a hidden prompt and stores them **encrypted** with
  Windows DPAPI. The key belongs to the Windows account that saved the password, so a copied
  `test_reports.db` is useless on another PC or under another account.
- Set the passwords **while logged in as the Windows account that runs the scanner**. If
  the scanner has to run under a different account (for example as a service), first set
  `XPSV_DPAPI_SCOPE=machine`, then set the passwords. With that setting, any account on
  that PC can decrypt them.
- If the log says a password could not be decrypted, set it again with `set-password`.
- Older databases with plain-text passwords are encrypted automatically at startup. You can
  also do it by hand with `python manage_targets.py encrypt-existing`.
- `list` only ever shows `password=set` or `password=none`, never the password itself.

## Settings

Every setting has a default (table below). You can change them in two ways.

**Option 1: settings file (recommended on the station PC).** Copy
`scanner_settings.example.env` to `scanner_settings.env` in the scanner folder, remove the `#` in
front of the lines you want, and change the values:

```
XPSV_SCAN_INTERVAL_MINUTES=10
XPSV_MAX_FILES_PER_TARGET=5
```

It works no matter which terminal you use or how the scanner is started (double-click, Task
Scheduler, ...). Restart the scanner after editing it.

**Option 2: environment variables.** These apply only to the terminal window they are set in,
and they win over the file. The syntax differs between shells, and mixing them up is the usual
cause of errors:

| Shell (prompt looks like) | Correct | Common mistake |
|---|---|---|
| PowerShell (`PS C:\...>`) | `$env:XPSV_SCAN_INTERVAL_MINUTES = "10"` | `set XPSV_...=10` silently does nothing in PowerShell |
| cmd (`C:\...>`) | `set XPSV_SCAN_INTERVAL_MINUTES=10` | `$env:XPSV_...="10"` gives *"The filename, directory name, or volume label syntax is incorrect"* |

To remove an override: PowerShell `Remove-Item env:XPSV_SCAN_INTERVAL_MINUTES`, cmd
`set XPSV_SCAN_INTERVAL_MINUTES=`, or close the window.

Quotes and spaces around values are ignored. Relative paths count from the scanner folder.
At startup the log shows which settings were changed and where from, e.g.
`Settings: XPSV_SCAN_INTERVAL_MINUTES=10 (from scanner_settings.env)`. A bad value stops the
scanner with a one-line message such as
`Settings error: XPSV_SCAN_INTERVAL_MINUTES must be a whole number (or None), got 'ten'`.

| Variable | Default | Meaning |
|---|---|---|
| `XPSV_DB_PATH` | `test_reports.db` next to the scripts | database file |
| `XPSV_LOG_DIR` | `logs\` next to the scripts | log folder |
| `XPSV_LOG_LEVEL` | `info` | `debug`, `info`, `warning` or `error`; `debug` also logs every parsed file |
| `XPSV_SCAN_INTERVAL_MINUTES` | `30` | pause between scan cycles |
| `XPSV_FILE_DELAY_SECONDS` | `0.05` | pause after each new file (eases the load on stations) |
| `XPSV_BATCH_SIZE` | `100` | reports saved per database commit |
| `XPSV_MAX_FILES_PER_TARGET` | `None` (no limit) | cap on new files per station per cycle, useful for testing |
| `XPSV_DB_BUSY_TIMEOUT` | `30` | seconds to wait if another program is writing to the database |
| `XPSV_DPAPI_SCOPE` | `user` | `user` or `machine`, see [Passwords](#passwords) |
| `XPSV_SETTINGS_FILE` | `scanner_settings.env` next to the scripts | use a different settings file (environment variable only) |

## The database

SQLite file `test_reports.db`, in WAL mode, so the web app can read while the scanner writes.

**`test_reports`**: one row per report file.

| Column | Example | Notes |
|---|---|---|
| `id` | `1234` | Never changes. The web app's notes and ATE checks refer to it. |
| `full_serial_number` | `400000009486~102413-01~01~V25470002` | as written in the report |
| `po_number` / `part_number` / `serial_number` | `400000009486` / `102413-01` / `V25470002` | split from the full serial (parts 1, 2 and 4 of `a~b~c~d`) |
| `result` | `PASS` | always one of `PASS`, `FAIL`, `ABORTED`, `UNKNOWN` |
| `test_datetime` | `2026/03/05 03:00:39 PM` | date text exactly as in the report |
| `test_datetime_iso` | `2026-03-05T15:00:39` | the same date in ISO format; use this for sorting and filtering |
| `file_modification_time` | `2026-03-05T15:01:02` | when the file was last changed |
| `program_name`, `operator` | | from the report |
| `test_station` | `Chroma 2` | station name from `network_targets` |
| `file_name`, `file_path` | | `file_path` is unique, so a file is never stored twice |

Indexed columns (fast to search): serial numbers, PO, part, result, station and `test_datetime_iso`.

**`network_targets`**: the stations (`path`, `test_station`, `parser_type`, `enabled`,
`username`, and `password` encrypted).

## Sharing the database with the web app

The scanner and the web app (`web app/`) are separate programs. Neither imports the other's
code; the only thing they share is `test_reports.db`. Either one can be stopped, restarted or
upgraded without the other.

```
 scanner ──writes──►  test_reports.db  ──reads (read-only)──►  web app
                                                                  │
                      accounts.db, notes.db, ate_checks.db  ◄─────┘  web app's own files
```

**Who owns what**

| Data | Owner | Where |
|---|---|---|
| Report rows (`test_reports`), stations (`network_targets`) | scanner | `test_reports.db` |
| Logins, notes, ATE checks (everything an admin edits) | web app | its own `.db` files in `web app/` |

The web app opens `test_reports.db` read-only, so it can never change a report. Admin edits
live in the web app's own files and point at a report by its `id`. A rescan therefore never
overwrites an admin's note or tick.

**Pointing the web app at the scanner's database**

`main.py` does this for you. When you start the web app by hand, put the path in `web app\db_path.txt` (one line; relative paths are relative to `web app\`):

```
../scanner_stable/test_reports.db
```

Use `../scanner_testing/test_reports.db` while trying out a new scanner version. Instead of the file,
the environment variable `TEST_REPORTS_DB` also works and wins over it. With neither, the web app
falls back to `web app\test_reports.db`. On start-up it prints which file it reads, and warns if
the file or a column it needs is missing.

**Running the web app**

Normally `python main.py` starts it together with the scanner (see
[Running the scanner](#running-the-scanner)), already pointed at the right database. It uses
the same `.venv` and `requirements.txt` as the scanner (see [Setup](#setup)).

Before the first start, create an admin login (asks for a password):

```powershell
cd "web app"
python manage_accounts.py add <name> --name "Full Name"
```

Other account commands: `python manage_accounts.py list | passwd | disable | enable | delete <name>`.

To start only the web app: `python main.py web`, or `python app.py` inside `web app\` (it then
reads the database named in `db_path.txt`).

It serves on port 5000 to the whole network (waitress), at `http://<this PC's IP>:5000/?token=...`.
The token is the environment variable `KO_PHAI_TEST_THI_CUT` (defaults to `123`; change it for
real use). For development with auto-reload on `127.0.0.1` only, set `$env:DEV = "1"` first and
run `python app.py` directly.

**The scanner's promises** (checked by `tests/test_web_app_contract.py`; if one of those tests
fails, the change would break the web app):

1. The columns `id`, `full_serial_number`, `po_number`, `part_number`, `serial_number`,
   `result` and `file_path` always exist. New columns are fine: the web app shows every column.
2. A report's `id` never changes, and a deleted `id` is never handed out again. Rescans skip
   files already stored instead of replacing them.
3. The file stays in WAL mode, so the web app can read while the scanner writes and the
   reverse. Both sides wait for a lock (scanner `XPSV_DB_BUSY_TIMEOUT`, web app 10 s) instead
   of failing.

**Rules that follow from this**

- Run the scanner and the web app on the same PC as `test_reports.db`. WAL mode does not work
  over a network share, so don't point either one at `\\server\...`.
- Never delete `test_reports.db` to "start fresh". The new file would hand out the old ids to
  other reports, and every note and ATE check would land on the wrong report. If you must,
  delete `notes.db` and `ate_checks.db` along with it.
- Don't copy `test_reports.db` while the scanner runs; stop it first, or copy the `-wal`
  file along with it.

## Adding a data column

1. Add one line to `REPORT_COLUMNS` in `schema.py`:
   ```python
   ReportColumn("firmware_version"),                 # or indexed=True if you filter by it
   ```
2. Make the parser(s) return it from `extract_fields()` in `parsers.py`:
   ```python
   "firmware_version": _search(r"Firmware\s*:\s*(\S+)", content),
   ```
3. Start the scanner. The column is added to the existing database automatically.

Rules:
- Older rows have `NULL` in the new column. They aren't re-parsed automatically.
- Never rename or delete a column in `schema.py`; existing databases keep it anyway. Add a new one instead.
- A parser may return keys that aren't in `schema.py`. They are simply ignored.

## Adding a report format

Each report format has its own parser class in `parsers.py`. A parser only extracts fields;
the shared base class takes care of file name, path and modification time, splitting the
serial number, normalizing the result, and converting the date.

### A new file type (e.g. `.csv`)

```python
@register_parser(".csv", name="csv")
class CsvReportParser(BaseReportParser):
    def extract_fields(self, path, file_name):
        text = path.read_text(encoding="utf-8", errors="ignore")
        return {
            "full_serial_number": _search(r"Serial\s*:\s*(.*)", text),
            "program_name": ...,
            "operator": ...,
            "test_datetime": ...,
            "result": ...,           # PASS/PASSED/FAIL/FAILED/ABORTED, any case
        }
```

### Same extension, different layout (e.g. another brand's `.html`)

Several parsers can share an extension. There are two ways to pick the right one, and you
can use both:

**a) Auto-detect from the file content.** Give the new parser a `detect()` method that looks
at the start of the file (first 8 KB) and returns `True` if the file is in its format:

```python
@register_parser(".htm", ".html", name="brandx_html")
class BrandXHtmlParser(BaseReportParser):
    @classmethod
    def detect(cls, head):
        return "BrandX Test Report" in head      # something unique to this brand

    def extract_fields(self, path, file_name):
        ...
```

For each `.htm`/`.html` file, the parsers that have a `detect()` are asked in turn. If none
says yes, the original `html` parser (the default) is used, so existing stations keep
working unchanged.

**b) Fix the parser per station.** If a station only ever produces one format:

```powershell
python manage_targets.py add "\\172.24.130.5\Reports" --parser brandx_html
```

That station then always uses that parser and skips detection. `--parser auto` switches
detection back on.

### Steps for a new format

1. Get a few sample reports (a PASS, a FAIL and an aborted one if possible).
2. Write the parser and add a test in `tests/test_parsers.py`. See the existing tests that
   use a small sample report.
3. If the reports use a new date format, add it to `DATETIME_FORMATS` in `parsers.py`.
4. Run `python -m pytest tests`, then do a trial scan in the testing folder.

## Logs and troubleshooting

Logs are written to `logs\scanner.log` (5 files of 5 MB each, oldest deleted) and to the console.

| Log message | Meaning / fix |
|---|---|
| `No usable password for ...` | The station has a username but no password, or it couldn't be decrypted. Run `set-password`. |
| `Could not decrypt a stored password` | It was saved by another Windows account or PC. Run `set-password` again as the scanner's account. |
| `Could not log in to ...` | Wrong username or password, or the station is off or unreachable. |
| `Cannot access ...` | A folder or file on the share can't be read (permissions, or the station went offline mid-scan). |
| `Could not parse ...` | One file failed to parse; the rest continue. The file is retried next cycle. |
| `database is locked` | Another program held the database longer than `XPSV_DB_BUSY_TIMEOUT`. |
| `Settings error: ...` | A value in `scanner_settings.env` or an environment variable is wrong; the message says which. |
| `Reached max_files=...` | `XPSV_MAX_FILES_PER_TARGET` is set; remove it for a full scan. |

The scanner never stops because of one bad file or one unreachable station; it logs the
error and moves on. A failed cycle is retried at the next interval.

For more detail, set `XPSV_LOG_LEVEL=debug` in `scanner_settings.env`.

## Stable and testing folders

- `scanner_stable/` holds the code that is known to work. This is the one that runs day to day.
- `scanner_testing/` holds new or changed code being tried out, with its own copy of the database.

To promote a tested version, stop the stable scanner and copy the testing folder's `.py` files
and `tests\` over the stable folder (if the new code needs a new package, it is already in the
project folder's `requirements.txt`; run `pip install -r requirements.txt`). Keep the stable `test_reports.db`;
it is upgraded automatically on the next start. Then start it again.

Databases, logs and `secret_key.txt` are in `.gitignore` and are never committed.
