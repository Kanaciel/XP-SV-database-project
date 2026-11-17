"""Runtime settings for the scanner.

Every value has a default. To change one, use EITHER (environment variables win):

  1. A settings file (easiest): copy scanner_settings.example.env to
     scanner_settings.env in this folder and edit it, e.g.
         XPSV_SCAN_INTERVAL_MINUTES=10
  2. An environment variable, set in the same window before starting:
         PowerShell:  $env:XPSV_SCAN_INTERVAL_MINUTES = "10"
         cmd:         set XPSV_SCAN_INTERVAL_MINUTES=10

Quotes and spaces around values are ignored. Relative paths are relative to
this folder, not to wherever the terminal was opened.
"""
import os
from pathlib import Path
from typing import Dict, Optional

PROJECT_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = Path(os.environ.get("XPSV_SETTINGS_FILE", "").strip().strip("\"'")
                     or PROJECT_DIR / "scanner_settings.env")


class SettingsError(SystemExit):
    """Bad setting: stops the program with a readable message, not a traceback."""

    def __init__(self, message: str):
        super().__init__(f"Settings error: {message}")


def _clean(raw: Optional[str]) -> Optional[str]:
    """Strip spaces and one pair of surrounding quotes; '' becomes None."""
    if raw is None:
        return None
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value or None


def _read_settings_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    for lineno, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SettingsError(f"{path.name} line {lineno}: expected NAME=value, got {line!r}")
        name, value = line.split("=", 1)
        name = name.strip()
        if name.lower().startswith("set "):          # tolerate pasted cmd syntax
            name = name[4:].strip()
        values[name.lstrip("$").replace("env:", "")] = value
    return values


_FILE_VALUES = _read_settings_file(SETTINGS_FILE)
SOURCES: Dict[str, str] = {}  # name -> where its value came from (for the log)


def _get(name: str) -> Optional[str]:
    for source, raw in (("environment", os.environ.get(name)),
                        (SETTINGS_FILE.name, _FILE_VALUES.get(name))):
        value = _clean(raw)
        if value is not None:
            SOURCES[name] = source
            return value
    return None


def _int(name: str, default: Optional[int]) -> Optional[int]:
    value = _get(name)
    if value is None:
        return default
    if value.lower() == "none":
        return None
    try:
        return int(value)
    except ValueError:
        raise SettingsError(f"{name} must be a whole number (or None), got {value!r}") from None


def _float(name: str, default: float) -> float:
    value = _get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        raise SettingsError(f"{name} must be a number, got {value!r}") from None


def _path(name: str, default: Path) -> Path:
    value = _get(name)
    if value is None:
        return default
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    return path if path.is_absolute() else PROJECT_DIR / path


def _choice(name: str, default: str, choices) -> str:
    value = (_get(name) or default).lower()
    if value not in choices:
        raise SettingsError(f"{name} must be one of {', '.join(choices)}, got {value!r}")
    return value


# Where the SQLite database lives. Defaults to next to this script.
DB_PATH = _path("XPSV_DB_PATH", PROJECT_DIR / "test_reports.db")

# Where log files go (rotated automatically).
LOG_DIR = _path("XPSV_LOG_DIR", PROJECT_DIR / "logs")
LOG_LEVEL = _choice("XPSV_LOG_LEVEL", "info", ("debug", "info", "warning", "error")).upper()

SCAN_INTERVAL_SECONDS = (_int("XPSV_SCAN_INTERVAL_MINUTES", 30) or 30) * 60
FILE_DELAY_SECONDS = _float("XPSV_FILE_DELAY_SECONDS", 0.05)
BATCH_SIZE = _int("XPSV_BATCH_SIZE", 100) or 100

# Limit on NEW files parsed per target per cycle. None = no limit.
MAX_FILES_PER_TARGET = _int("XPSV_MAX_FILES_PER_TARGET", None)

# Seconds a connection waits for a lock held by another process
# (e.g. the web app reading) before giving up.
DB_BUSY_TIMEOUT_SECONDS = _float("XPSV_DB_BUSY_TIMEOUT", 30.0)

# Password encryption scope for Windows DPAPI:
#   "user"    - only the Windows account that saved the password can read it
#               (default, most secure; run the scanner as that same account).
#   "machine" - any account on this PC can read it (use if the scanner runs
#               as a service under a different account).
DPAPI_SCOPE = _choice("XPSV_DPAPI_SCOPE", "user", ("user", "machine"))


def describe() -> str:
    """One line per setting that isn't at its default, for the startup log."""
    if not SOURCES:
        return "all settings at their defaults"
    return "; ".join(f"{name}={_get(name)} (from {src})" for name, src in sorted(SOURCES.items()))
