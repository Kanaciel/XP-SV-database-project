import importlib

import pytest

import settings


def load(monkeypatch, tmp_path, env=None, file_text=None):
    for name in list(__import__("os").environ):
        if name.startswith("XPSV_"):
            monkeypatch.delenv(name)
    f = tmp_path / "scanner_settings.env"
    if file_text is not None:
        f.write_text(file_text)
    monkeypatch.setenv("XPSV_SETTINGS_FILE", str(f))
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    return importlib.reload(settings)


@pytest.fixture(autouse=True)
def restore(monkeypatch):
    yield
    monkeypatch.undo()
    importlib.reload(settings)


def test_defaults(monkeypatch, tmp_path):
    s = load(monkeypatch, tmp_path)
    assert s.SCAN_INTERVAL_SECONDS == 30 * 60
    assert s.MAX_FILES_PER_TARGET is None
    assert s.DB_PATH == s.PROJECT_DIR / "test_reports.db"
    assert s.describe() == "all settings at their defaults"


def test_quotes_and_spaces_are_ignored(monkeypatch, tmp_path):
    # What cmd's  set XPSV_MAX_FILES_PER_TARGET="5"  actually stores.
    s = load(monkeypatch, tmp_path, env={"XPSV_MAX_FILES_PER_TARGET": ' "5" '})
    assert s.MAX_FILES_PER_TARGET == 5


def test_settings_file_and_env_priority(monkeypatch, tmp_path):
    text = "# comment\nXPSV_SCAN_INTERVAL_MINUTES = 10\nset XPSV_BATCH_SIZE=50\n$env:XPSV_LOG_LEVEL=\"debug\"\nXPSV_DB_PATH='data/x.db'\n"
    s = load(monkeypatch, tmp_path, env={"XPSV_SCAN_INTERVAL_MINUTES": "2"}, file_text=text)
    assert s.SCAN_INTERVAL_SECONDS == 120          # environment wins
    assert s.BATCH_SIZE == 50
    assert s.LOG_LEVEL == "DEBUG"
    assert s.DB_PATH.parent.parent == s.PROJECT_DIR  # relative to the scanner folder
    assert "from environment" in s.describe()


def test_bad_value_gives_clear_message(monkeypatch, tmp_path):
    with pytest.raises(SystemExit, match="XPSV_SCAN_INTERVAL_MINUTES must be a whole number"):
        load(monkeypatch, tmp_path, env={"XPSV_SCAN_INTERVAL_MINUTES": "ten"})
    with pytest.raises(SystemExit, match="XPSV_DPAPI_SCOPE must be one of"):
        load(monkeypatch, tmp_path, env={"XPSV_DPAPI_SCOPE": "everyone"})
