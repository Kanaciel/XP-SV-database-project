from abc import ABC, abstractmethod
import os, re
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

class BaseReportParser(ABC):
    @abstractmethod
    def parse(self, file_path: str) -> dict:
        pass

    @staticmethod
    def parse_full_serial(raw_serial: str):
        if not raw_serial:
            return None, None, None
        parts = raw_serial.strip().split("~")
        if len(parts) == 4:
            return parts[0].strip(), parts[1].strip(), parts[3].strip()
        return None, None, None

    @staticmethod
    def normalize_result(raw_result):
        if not raw_result:
            return "UNKNOWN"

        result = raw_result.strip().upper()

        result_mapping = {
            "PASS": "PASS",
            "PASSED": "PASS",
            "FAIL": "FAIL",
            "FAILED": "FAIL",
            "ABORTED": "ABORTED",
        }

        return result_mapping.get(result, "UNKNOWN")


class TextReportParser(BaseReportParser):
    def parse(self, file_path: str) -> dict:
        abs_path = Path(file_path).resolve()

        file_name = abs_path.name
        file_path = str(abs_path)
        file_modification_time = datetime.fromtimestamp(
        abs_path.stat().st_mtime
            ).isoformat()

        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            # Extract serial number
            serial_match = re.search(
                    r"(?:Serial\s+No|Serial\s+Number)\s*:\s*(.*?)(?=\r?\n|$)",
                    content,
                    re.IGNORECASE,
                )
        full_serial_number = serial_match.group(1).strip() if serial_match else None
        
            # Extract program name
        program_match = re.search(
                r"(?:Test\s+Program\s+Name|Program\s+Name)\s*:\s*(.*?)(?=\r?\n|$)",
                content,
                re.IGNORECASE,
            )
        program_name = program_match.group(1).strip() if program_match else None
        
            # Extract operator / inspector / username
        operator_match = re.search(
                r"(?:Inspector|Username|Operator)\s*:\s*(.*?)(?=\r?\n|$)",
                content,
                re.IGNORECASE,
            )
        operator = operator_match.group(1).strip() if operator_match else None
        
            # Extract timestamp from report body
        datetime_match = re.search(
                r"(?:System\s+Time\s*:\s*(.*?)(?=\r?\n|$))|"
                r"(\d{4}/\d{2}/\d{2}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)|"
                r"(\d{1,2}-[A-Za-z]{3}-\d{2}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)",
                content,
                re.IGNORECASE,
            )
        test_datetime = None
        if datetime_match:
                test_datetime = next(
                    (g for g in datetime_match.groups() if g is not None), ""
                ).strip()
        
            # Extract PASS / FAIL result from file body or fallback to filename
        result_match = re.search(
                r"(?:UUT|Test\s+Result)\s*:\s*(PASS|PASSED|FAIL|FAILED|ABORTED)",
                content,
                re.IGNORECASE,
            )
        if result_match:
                result = result_match.group(1).upper()
                result = self.normalize_result(result)
        else:
                fn_match = re.search(r"\b(PASS|FAIL)\b", file_name or "", re.IGNORECASE)
                result = fn_match.group(1).upper() if fn_match else "UNKNOWN"
                result = self.normalize_result(result)
        
        po_number, part_number, serial_number = self.parse_full_serial(
                full_serial_number
            )

        return {
                "file_name": file_name,
                "file_path": file_path,
                "file_modification_time": file_modification_time,
                "full_serial_number": full_serial_number,
                "po_number": po_number,
                "part_number": part_number,
                "serial_number": serial_number,
                "program_name": program_name,
                "test_datetime": test_datetime,
                "operator": operator,
                "result": result,
                "test_station": None,
            }

class HTMLReportParser(BaseReportParser):
    def parse(self, file_path: str) -> dict:
        """
            Extracts test report metadata from local file, network path, or HTML string.
                    """
        abs_path = Path(file_path).resolve()

        file_name = abs_path.name
        file_path = str(abs_path)

        file_modification_time = datetime.fromtimestamp(
            abs_path.stat().st_mtime
        ).isoformat()

        with open(abs_path, "r", encoding="iso-8859-1") as f:
            html_content = f.read()    
        soup = BeautifulSoup(html_content, "html.parser")
        text_content = soup.get_text(" ", strip=True)
        
        def extract_field(pattern):
            match = re.search(pattern, text_content, re.IGNORECASE)
            return match.group(1).strip() if match else None
        
        program_name = extract_field(r"Program Name:\s*(.*?)\s*Serial Number:")
        full_serial_number = extract_field(r"Serial Number:\s*(.*?)\s*Operator:")
        operator = extract_field(r"Operator:\s*(.*?)\s*Step\s+ID\b")
        test_datetime = extract_field(                r"(\d{1,2}-[A-Za-z]{3}-\d{2}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)"
            )
        raw_result = extract_field(r"\bUUT\s*:?\s*(PASS|PASSED|FAIL|FAILED|ABORTED)\b")
        result = self.normalize_result(raw_result)
        
        po_number, part_number, serial_number = self.parse_full_serial(
                full_serial_number
            )
        
        return {
                "file_name": file_name,
                "file_path": file_path,
                "file_modification_time": file_modification_time,
                "full_serial_number": full_serial_number,
                "po_number": po_number,
                "part_number": part_number,
                "serial_number": serial_number,
                "program_name": program_name,
                "test_datetime": test_datetime,
                "operator": operator,
                "result": result,
                "test_station": None,
            }
        

class ReportParserFactory:
    @staticmethod
    def get_parser(file_path: str) -> BaseReportParser:
        ext = Path(file_path).suffix.lower()
        if ext in ['.htm', '.html']:
            return HTMLReportParser()
        elif ext in ['.txt', '.log']:
            return TextReportParser()
        raise ValueError(f"Unsupported file format: {ext}")