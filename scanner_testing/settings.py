"""Runtime settings for the scanner.

Every value has a sensible default and can be overridden with an
environment variable, so nothing machine-specific has to be edited in code.
Example (Windows cmd):  set XPSV_SCAN_INTERVAL_MINUTES=10
"""
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent


def _env_int(name: str, default):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    if raw.strip().lower() == "none":
        return None
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw and raw.strip() else default


# Where the SQLite database lives. Defaults to next to this script.
DB_PATH = Path(os.environ.get("XPSV_DB_PATH", PROJECT_DIR / "test_reports.db"))

# Where log files go (rotated automatically).
LOG_DIR = Path(os.environ.get("XPSV_LOG_DIR", PROJECT_DIR / "logs"))
LOG_LEVEL = os.environ.get("XPSV_LOG_LEVEL", "INFO").upper()

SCAN_INTERVAL_SECONDS = _env_int("XPSV_SCAN_INTERVAL_MINUTES", 30) * 60
FILE_DELAY_SECONDS = _env_float("XPSV_FILE_DELAY_SECONDS", 0.05)
BATCH_SIZE = _env_int("XPSV_BATCH_SIZE", 100)

# Limit on NEW files parsed per target per cycle. None = no limit.
MAX_FILES_PER_TARGET = _env_int("XPSV_MAX_FILES_PER_TARGET", None)

# Seconds a connection waits for a lock held by another process
# (e.g. the web app reading) before giving up.
DB_BUSY_TIMEOUT_SECONDS = _env_float("XPSV_DB_BUSY_TIMEOUT", 30.0)

# Password encryption scope for Windows DPAPI:
#   "user"    - only the Windows account that saved the password can read it
#               (default, most secure; run the scanner as that same account).
#   "machine" - any account on this PC can read it (use if the scanner runs
#               as a service under a different account).
DPAPI_SCOPE = os.environ.get("XPSV_DPAPI_SCOPE", "user").lower()
