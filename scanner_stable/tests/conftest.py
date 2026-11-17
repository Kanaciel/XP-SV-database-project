import base64
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def fake_dpapi(monkeypatch):
    """Stand-in for win32crypt so encryption can be tested off Windows."""
    mod = types.SimpleNamespace(
        CryptProtectData=lambda data, desc, ent, r, p, f: b"ENC" + base64.b64encode(data),
        CryptUnprotectData=lambda blob, ent, r, p, f: ("desc", base64.b64decode(blob[3:])),
    )
    monkeypatch.setitem(sys.modules, "win32crypt", mod)
    return mod
