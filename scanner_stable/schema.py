"""Single source of truth for the test_reports table.

To add a new data column:
  1. Add a ReportColumn below.
  2. Make the parser(s) put a value under that key in the dict they return.
That's it: on next start the database adds the column to existing files
automatically (ALTER TABLE), and inserts pick it up.

Never rename or remove a column here; existing databases keep it. Add a new
one instead.
"""
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class ReportColumn:
    name: str
    sql_type: str = "TEXT"
    indexed: bool = False  # add an index if the web app filters/sorts by it
    unique: bool = False   # only honoured when the table is first created


REPORT_COLUMNS: Tuple[ReportColumn, ...] = (
    ReportColumn("full_serial_number", indexed=True),
    ReportColumn("po_number", indexed=True),
    ReportColumn("part_number", indexed=True),
    ReportColumn("serial_number", indexed=True),
    ReportColumn("result", indexed=True),
    ReportColumn("test_datetime"),  # raw text, exactly as in the report
    ReportColumn("file_modification_time"),
    ReportColumn("program_name"),
    ReportColumn("operator"),
    ReportColumn("test_station", indexed=True),
    ReportColumn("file_name"),
    ReportColumn("file_path", unique=True),  # one row per report file
    # ISO 8601 ("2026-03-05T15:00:39") version of test_datetime, so dates
    # sort and filter correctly. NULL if the raw text could not be read.
    ReportColumn("test_datetime_iso", indexed=True),
)

COLUMN_NAMES: Tuple[str, ...] = tuple(c.name for c in REPORT_COLUMNS)
