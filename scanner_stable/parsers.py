"""Report parsers.

To support a new report format, write a subclass of BaseReportParser that
implements extract_fields(), then register it for its file extensions:

    @register_parser(".htm", ".html", name="brandx_html")
    class BrandXHtmlParser(BaseReportParser):
        @classmethod
        def detect(cls, head):
            # head = first few KB of the file. Return True if it's ours.
            return "BrandX Test Report" in head

        def extract_fields(self, path, file_name):
            ...
            return {"full_serial_number": ..., "result": ..., ...}

The base class adds file name/path/modification time, splits the serial
number, normalizes the result and the date, so a parser only extracts.

Choosing a parser for a file:
  * If the station's parser_type is set (manage_targets.py --parser NAME),
    that parser is always used for that station.
  * Otherwise ("auto"), the parsers registered for the file's extension are
    asked in turn via detect(); the first that says yes wins. If none does,
    the extension's default parser (registered with default=True, or the
    first one registered) is used.
"""
import re
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Type

from bs4 import BeautifulSoup

# Formats seen in reports so far. Add new ones here.
DATETIME_FORMATS = (
    "%Y/%m/%d %I:%M:%S %p",   # 2026/03/05 03:00:39 PM
    "%d-%b-%y %I:%M:%S %p",   # 5-Mar-26 3:00:39 PM
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %H:%M:%S",
    # Some stations write a 24-hour time AND an AM/PM marker
    # ("2025/09/17 16:31:03 PM"). Tried last, so normal 12-hour times win.
    "%Y/%m/%d %H:%M:%S %p",
)


def normalize_datetime(raw: Optional[str]) -> Optional[str]:
    """Turn a report's date text into ISO 8601, or None if unrecognised."""
    if not raw:
        return None
    text = " ".join(raw.split())
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            continue
    return None


RESULT_MAPPING = {
    "PASS": "PASS",
    "PASSED": "PASS",
    "FAIL": "FAIL",
    "FAILED": "FAIL",
    "ABORTED": "ABORTED",
}


class BaseReportParser(ABC):
    name: str = ""  # set by @register_parser

    @classmethod
    def detect(cls, head: str) -> bool:
        """Return True if `head` (start of the file) looks like this format.

        Only needed when several parsers share an extension.
        """
        return False

    @abstractmethod
    def extract_fields(self, path: Path, file_name: str) -> dict:
        """Read the file and return the report-specific fields.

        Expected keys (missing ones become NULL): full_serial_number,
        program_name, operator, test_datetime, result.
        """

    def parse(self, file_path: str) -> dict:
        abs_path = Path(file_path).resolve()
        record = {
            "file_name": abs_path.name,
            "file_path": str(abs_path),
            "file_modification_time": datetime.fromtimestamp(
                abs_path.stat().st_mtime
            ).isoformat(),
            "test_station": None,  # filled in by the scanner
        }
        record.update(self.extract_fields(abs_path, abs_path.name))

        record["result"] = self.normalize_result(record.get("result"))
        po, part, serial = self.parse_full_serial(record.get("full_serial_number"))
        record.setdefault("po_number", po)
        record.setdefault("part_number", part)
        record.setdefault("serial_number", serial)
        record["test_datetime_iso"] = normalize_datetime(record.get("test_datetime"))
        return record

    @staticmethod
    def parse_full_serial(raw_serial: Optional[str]) -> Tuple[Optional[str], ...]:
        if not raw_serial:
            return None, None, None
        parts = raw_serial.strip().split("~")
        if len(parts) == 4:
            return parts[0].strip(), parts[1].strip(), parts[3].strip()
        return None, None, None

    @staticmethod
    def normalize_result(raw_result: Optional[str]) -> str:
        if not raw_result:
            return "UNKNOWN"
        return RESULT_MAPPING.get(raw_result.strip().upper(), "UNKNOWN")


def _search(pattern: str, text: str) -> Optional[str]:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else None


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------
_BY_EXTENSION: Dict[str, List[Type[BaseReportParser]]] = {}
_DEFAULT_FOR_EXTENSION: Dict[str, Type[BaseReportParser]] = {}
_BY_NAME: Dict[str, Type[BaseReportParser]] = {}

DETECT_BYTES = 8192  # how much of a file detect() gets to look at


def register_parser(*extensions: str, name: Optional[str] = None,
                    default: bool = False) -> Callable[[Type[BaseReportParser]], Type[BaseReportParser]]:
    """Register a parser for file extensions under a unique name."""
    def decorator(cls):
        cls.name = name or cls.__name__
        if cls.name in _BY_NAME and _BY_NAME[cls.name] is not cls:
            raise ValueError(f"Parser name already used: {cls.name}")
        _BY_NAME[cls.name] = cls
        cls.extensions = tuple(e.lower() for e in extensions)
        for ext in cls.extensions:
            _BY_EXTENSION.setdefault(ext, []).append(cls)
            if default or ext not in _DEFAULT_FOR_EXTENSION:
                _DEFAULT_FOR_EXTENSION[ext] = cls
        return cls
    return decorator


def _read_head(file_path: str) -> str:
    with open(file_path, "r", encoding="iso-8859-1", errors="ignore") as f:
        return f.read(DETECT_BYTES)


@register_parser(".txt", ".log", name="text", default=True)
class TextReportParser(BaseReportParser):
    def extract_fields(self, path: Path, file_name: str) -> dict:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        line_value = r"\s*:\s*(.*?)(?=\r?\n|$)"
        fields = {
            "full_serial_number": _search(r"(?:Serial\s+No|Serial\s+Number)" + line_value, content),
            "program_name": _search(r"(?:Test\s+Program\s+Name|Program\s+Name)" + line_value, content),
            "operator": _search(r"(?:Inspector|Username|Operator)" + line_value, content),
        }

        datetime_match = re.search(
            r"(?:System\s+Time\s*:\s*(.*?)(?=\r?\n|$))|"
            r"(\d{4}/\d{2}/\d{2}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)|"
            r"(\d{1,2}-[A-Za-z]{3}-\d{2}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)",
            content,
            re.IGNORECASE,
        )
        fields["test_datetime"] = None
        if datetime_match:
            fields["test_datetime"] = next(
                (g for g in datetime_match.groups() if g is not None), ""
            ).strip()

        # PASS / FAIL from the body, or fall back to the file name.
        result = _search(r"(?:UUT|Test\s+Result)\s*:\s*(PASS|PASSED|FAIL|FAILED|ABORTED)", content)
        if result is None:
            result = _search(r"\b(PASS|FAIL)\b", file_name or "")
        fields["result"] = result
        return fields


@register_parser(".htm", ".html", name="html", default=True)
class HTMLReportParser(BaseReportParser):
    def extract_fields(self, path: Path, file_name: str) -> dict:
        with open(path, "r", encoding="iso-8859-1") as f:
            html_content = f.read()
        text = BeautifulSoup(html_content, "html.parser").get_text(" ", strip=True)

        return {
            "program_name": _search(r"Program Name:\s*(.*?)\s*Serial Number:", text),
            "full_serial_number": _search(r"Serial Number:\s*(.*?)\s*Operator:", text),
            "operator": _search(r"Operator:\s*(.*?)\s*Step\s+ID\b", text),
            "test_datetime": _search(
                r"(\d{1,2}-[A-Za-z]{3}-\d{2}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)", text
            ),
            "result": _search(r"\bUUT\s*:?\s*(PASS|PASSED|FAIL|FAILED|ABORTED)\b", text),
        }


class ReportParserFactory:
    @staticmethod
    def supported_extensions():
        return tuple(sorted(_BY_EXTENSION))

    @staticmethod
    def parser_names():
        return tuple(sorted(_BY_NAME))

    @staticmethod
    def get_parser(file_path: str, parser_type: Optional[str] = "auto") -> BaseReportParser:
        """Pick the parser for a file. Raises ValueError if none applies."""
        ext = Path(file_path).suffix.lower()
        candidates = _BY_EXTENSION.get(ext)
        if not candidates:
            raise ValueError(f"Unsupported file format: {ext}")

        if parser_type and parser_type != "auto":
            cls = _BY_NAME.get(parser_type)
            if cls is None:
                raise ValueError(f"Unknown parser_type {parser_type!r}; "
                                 f"choose from {', '.join(ReportParserFactory.parser_names())}")
            if ext not in cls.extensions:
                raise ValueError(f"Parser {parser_type} does not handle {ext} files")
            return cls()

        if len(candidates) > 1:
            try:
                head = _read_head(file_path)
            except OSError:
                head = ""  # the default parser will report the read error
            for cls in candidates:
                if cls.detect(head):
                    return cls()
        return _DEFAULT_FOR_EXTENSION[ext]()
