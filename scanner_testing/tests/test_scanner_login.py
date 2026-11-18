"""Logging in to a station: with and without an existing Windows login."""
import pytest

import scanner as scanner_mod
from config import NetworkTarget
from network_auth import ShareLoginError, share_root
from scanner import NetworkReportScanner

PATH = r"\\172.24.123.61\Reports"


@pytest.fixture
def env(monkeypatch):
    """Fake Windows: records login attempts; .accessible = already logged in."""
    state = type("S", (), {"logins": [], "accessible": False, "login_error": None})()

    def fake_connect(path, user, pw):
        state.logins.append((path, user, pw))
        if state.login_error:
            raise state.login_error

    monkeypatch.setattr(scanner_mod, "connect_share", fake_connect)
    monkeypatch.setattr(scanner_mod, "is_accessible", lambda p: state.accessible)
    return state


def target(password=None):
    return NetworkTarget(path=PATH, username=r"s12674\nhr", password=password)


def test_never_logged_in_uses_stored_password(env):
    assert NetworkReportScanner.ensure_access(target("pw"))
    assert env.logins == [(PATH, r"s12674\nhr", "pw")]


def test_never_logged_in_and_no_password_skips(env, caplog):
    assert not NetworkReportScanner.ensure_access(target())
    assert env.logins == []
    assert "set-password" in caplog.text


def test_already_logged_in_needs_no_password(env):
    env.accessible = True
    assert NetworkReportScanner.ensure_access(target())
    assert env.logins == []


def test_already_logged_in_with_wrong_password_still_scans(env, caplog):
    env.accessible = True
    env.login_error = ShareLoginError(1326, "wrong username or password")
    assert NetworkReportScanner.ensure_access(target("bad"))
    assert "already logged in" in caplog.text


def test_wrong_password_and_not_logged_in_skips(env):
    env.login_error = ShareLoginError(1326, "wrong username or password")
    assert not NetworkReportScanner.ensure_access(target("bad"))


def test_unreachable_computer_skips_without_waiting_on_access_check(env, monkeypatch):
    env.login_error = ShareLoginError(53, "not found")
    monkeypatch.setattr(scanner_mod, "is_accessible", lambda p: pytest.fail("should not be called"))
    assert not NetworkReportScanner.ensure_access(target("pw"))


def test_target_without_username_needs_no_login(env):
    assert NetworkReportScanner.ensure_access(NetworkTarget(path=PATH))
    assert env.logins == []


def test_share_root():
    assert share_root(PATH + r"\sub\dir") == PATH
    with pytest.raises(ValueError):
        share_root("C:\\local")
