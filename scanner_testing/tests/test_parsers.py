from parsers import ReportParserFactory, normalize_datetime, register_parser, BaseReportParser

import pytest

TXT = """Test Program Name : HPT5K0TS400BOK
Serial No : 400000009486~102413-01~01~V25470002
Inspector : root
System Time : 2026/03/05 03:00:39 PM
UUT : PASSED
"""

HTML = """<html><body><table>
<tr><td>Program Name:</td><td>FLX FrontEnd</td></tr>
<tr><td>Serial Number:</td><td>4000001~102413-01~01~V2547</td></tr>
<tr><td>Operator:</td><td>TE</td></tr>
<tr><td>Step ID</td><td>5-Mar-26 3:00:39 PM</td></tr>
<tr><td>UUT: FAILED</td></tr>
</table></body></html>"""


def test_text_report(tmp_path):
    f = tmp_path / "report-PASS.txt"
    f.write_text(TXT)
    r = ReportParserFactory.get_parser(str(f)).parse(str(f))
    assert r["program_name"] == "HPT5K0TS400BOK"
    assert r["po_number"] == "400000009486"
    assert r["part_number"] == "102413-01"
    assert r["serial_number"] == "V25470002"
    assert r["operator"] == "root"
    assert r["result"] == "PASS"
    assert r["test_datetime"] == "2026/03/05 03:00:39 PM"
    assert r["test_datetime_iso"] == "2026-03-05T15:00:39"
    assert r["file_name"] == "report-PASS.txt"


def test_text_result_falls_back_to_file_name(tmp_path):
    f = tmp_path / "00003-root-FAIL.txt"
    f.write_text("nothing useful here")
    r = ReportParserFactory.get_parser(str(f)).parse(str(f))
    assert r["result"] == "FAIL"
    assert r["full_serial_number"] is None and r["serial_number"] is None


def test_html_report(tmp_path):
    f = tmp_path / "r.HTM"
    f.write_text(HTML, encoding="iso-8859-1")
    r = ReportParserFactory.get_parser(str(f)).parse(str(f))
    assert r["program_name"] == "FLX FrontEnd"
    assert r["operator"] == "TE"
    assert r["result"] == "FAIL"
    assert r["test_datetime_iso"] == "2026-03-05T15:00:39"


def test_unsupported_extension():
    with pytest.raises(ValueError):
        ReportParserFactory.get_parser("x.pdf")


def test_register_new_parser(tmp_path):
    @register_parser(".csvtest")
    class CsvParser(BaseReportParser):
        def extract_fields(self, path, file_name):
            return {"result": "passed", "full_serial_number": "a~b~c~d"}

    f = tmp_path / "x.csvtest"
    f.write_text("")
    r = ReportParserFactory.get_parser(str(f)).parse(str(f))
    assert r["result"] == "PASS" and r["serial_number"] == "d"


@pytest.mark.parametrize("raw,iso", [
    ("2026/03/05 03:00:39 PM", "2026-03-05T15:00:39"),
    ("5-Mar-26 3:00:39 AM", "2026-03-05T03:00:39"),
    ("15-Jul-25 12:05:00 PM", "2025-07-15T12:05:00"),
    ("2025/09/17 16:31:03 PM", "2025-09-17T16:31:03"),
    ("2025/09/17 12:30:00 AM", "2025-09-17T00:30:00"),
    ("garbage", None),
    (None, None),
])
def test_normalize_datetime(raw, iso):
    assert normalize_datetime(raw) == iso


def test_detect_picks_matching_parser_for_shared_extension(tmp_path):
    @register_parser(".multi", name="multi_a", default=True)
    class A(BaseReportParser):
        def extract_fields(self, path, file_name):
            return {"program_name": "A"}

    @register_parser(".multi", name="multi_b")
    class B(BaseReportParser):
        @classmethod
        def detect(cls, head):
            return "BrandB Report" in head

        def extract_fields(self, path, file_name):
            return {"program_name": "B"}

    b_file = tmp_path / "b.multi"
    b_file.write_text("<html>BrandB Report ...</html>")
    other = tmp_path / "a.multi"
    other.write_text("<html>something else</html>")

    assert ReportParserFactory.get_parser(str(b_file)).parse(str(b_file))["program_name"] == "B"
    assert ReportParserFactory.get_parser(str(other)).parse(str(other))["program_name"] == "A"
    # A station forced to one parser always gets that one.
    assert isinstance(ReportParserFactory.get_parser(str(b_file), "multi_a"), A)


def test_forced_parser_errors():
    with pytest.raises(ValueError):
        ReportParserFactory.get_parser("x.html", "no_such_parser")
    with pytest.raises(ValueError):
        ReportParserFactory.get_parser("x.txt", "html")  # html parser can't read .txt


def test_builtin_parser_names():
    assert {"text", "html"} <= set(ReportParserFactory.parser_names())
