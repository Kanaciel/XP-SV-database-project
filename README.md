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
9. [Adding a data column](#adding-a-data-column)
10. [Adding a report format](#adding-a-report-format)
11. [Logs and troubleshooting](#logs-and-troubleshooting)
12. [Stable and testing folders](#stable-and-testing-folders)

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
| `settings.py` | Interval, delays, paths and similar options. Each one can be overridden with an environment variable. |
| `logging_setup.py` | Writes logs to the console and to `logs/scanner.log`. |
| `tests/` | Automated tests (pytest). |

## Setup

You need Windows, Python 3.8+ and network access to the stations.

```powershell
pip install -r requirements.txt        # beautifulsoup4, pywin32
pip install -r requirements-dev.txt    # adds pytest, only needed for testing
```

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

4. **Do a small trial scan.** It parses at most 5 new files per station and loops every minute:
   ```powershell
   $env:XPSV_MAX_FILES_PER_TARGET="5"
   $env:XPSV_SCAN_INTERVAL_MINUTES="1"
   python RunScanner.py
   ```
   Watch for `Scan end: ... inserted N` and for any `ERROR` lines, then stop with **Ctrl+C**.
   Afterwards, clear the overrides with `Remove-Item env:XPSV_*` (or close PowerShell).

5. **Spot-check the data**, for example the newest reports:
   ```powershell
   python -c "import sqlite3; c=sqlite3.connect('test_reports.db'); [print(r) for r in c.execute('SELECT id, test_station, result, test_datetime_iso, file_name FROM test_reports ORDER BY id DESC LIMIT 10')]"
   ```

## Running the scanner

```powershell
python RunScanner.py
```

On every start it:
- creates the database if it doesn't exist and adds any new columns from `schema.py`;
- copies the stations from `config.py` into the database, only if there are none yet;
- encrypts any password still stored as plain text.

Then it scans every enabled station, waits for the scan interval, and repeats. Stop it with
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

Defaults live in `settings.py`. To override one, set an environment variable before starting
(PowerShell: `$env:NAME="value"`; cmd: `set NAME=value`).

| Variable | Default | Meaning |
|---|---|---|
| `XPSV_DB_PATH` | `test_reports.db` next to the scripts | database file |
| `XPSV_LOG_DIR` | `logs\` next to the scripts | log folder |
| `XPSV_LOG_LEVEL` | `INFO` | `DEBUG` also logs every parsed file |
| `XPSV_SCAN_INTERVAL_MINUTES` | `30` | pause between scan cycles |
| `XPSV_FILE_DELAY_SECONDS` | `0.05` | pause after each new file (eases the load on stations) |
| `XPSV_BATCH_SIZE` | `100` | reports saved per database commit |
| `XPSV_MAX_FILES_PER_TARGET` | `None` (no limit) | cap on new files per station per cycle, useful for testing |
| `XPSV_DB_BUSY_TIMEOUT` | `30` | seconds to wait if another program is writing to the database |
| `XPSV_DPAPI_SCOPE` | `user` | `user` or `machine`, see [Passwords](#passwords) |

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
| `Reached max_files=...` | `XPSV_MAX_FILES_PER_TARGET` is set; remove it for a full scan. |

The scanner never stops because of one bad file or one unreachable station; it logs the
error and moves on. A failed cycle is retried at the next interval.

For more detail, start with `$env:XPSV_LOG_LEVEL="DEBUG"`.

## Stable and testing folders

- `scanner_stable/` holds the code that is known to work. This is the one that runs day to day.
- `scanner_testing/` holds new or changed code being tried out, with its own copy of the database.

To promote a tested version, stop the stable scanner and copy the testing folder's `.py` files,
`tests\` and `requirements*.txt` over the stable folder. Keep the stable `test_reports.db`;
it is upgraded automatically on the next start. Then start it again.

Databases, logs and `secret_key.txt` are in `.gitignore` and are never committed.
