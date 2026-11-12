from config import NetworkTarget
from database import DatabaseManager
from scanner import NetworkReportScanner


def test_target_with_username_but_no_password_is_skipped(tmp_path, monkeypatch):
    import scanner as scanner_mod
    called = []
    monkeypatch.setattr(scanner_mod, "connect_share", lambda *a: called.append(a))
    s = NetworkReportScanner(DatabaseManager(tmp_path / "t.db"))
    s.scan_target(NetworkTarget(path=r"\\h\R", username="u"))
    assert called == []


def test_station_name_falls_back_to_server_ip():
    resolve = NetworkReportScanner.resolve_test_station
    assert resolve(NetworkTarget(path=r"\\172.24.1.2\Reports"), r"\\172.24.1.2\Reports\sub") == "172.24.1.2"
    assert resolve(NetworkTarget(path=r"\\h\R", test_station="Chroma 9"), r"\\h\R") == "Chroma 9"
    assert resolve(NetworkTarget(path="/data/reports/"), "/data/reports") == "reports"
