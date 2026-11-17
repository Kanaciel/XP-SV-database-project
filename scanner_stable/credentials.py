"""Encryption for the network-share passwords stored in the database.

Passwords are encrypted with Windows DPAPI (part of pywin32, which the
scanner already needs). DPAPI ties the encryption key to the Windows
account (or, in "machine" scope, to this PC), so a copy of the .db file is
useless anywhere else, and nobody needs to manage a key file.

Stored format:  "dpapi:v1:<base64 blob>"
Anything without that prefix is a legacy plain-text password; it still
works, and DatabaseManager.encrypt_legacy_passwords() upgrades it.
"""
import base64
from typing import Optional

import settings

PREFIX = "dpapi:v1:"
# App-specific extra secret mixed into the encryption. Not a key on its own,
# just stops other programs' DPAPI blobs being swapped in.
_ENTROPY = b"XP-SV-database-project/network-targets"

_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_CRYPTPROTECT_LOCAL_MACHINE = 0x4


class CredentialError(RuntimeError):
    pass


def _win32crypt():
    try:
        import win32crypt  # pywin32
    except ImportError as e:
        raise CredentialError(
            "Password encryption needs Windows and pywin32 (pip install pywin32)."
        ) from e
    return win32crypt


def _flags() -> int:
    flags = _CRYPTPROTECT_UI_FORBIDDEN
    if settings.DPAPI_SCOPE == "machine":
        flags |= _CRYPTPROTECT_LOCAL_MACHINE
    return flags


def _protect(data: bytes) -> bytes:
    return _win32crypt().CryptProtectData(data, "XP-SV share password", _ENTROPY, None, None, _flags())


def _unprotect(blob: bytes) -> bytes:
    return _win32crypt().CryptUnprotectData(blob, _ENTROPY, None, None, _CRYPTPROTECT_UI_FORBIDDEN)[1]


def is_encrypted(stored: Optional[str]) -> bool:
    return bool(stored) and stored.startswith(PREFIX)


def encrypt(plain: Optional[str]) -> Optional[str]:
    if plain is None or plain == "":
        return None
    blob = _protect(plain.encode("utf-8"))
    return PREFIX + base64.b64encode(blob).decode("ascii")


def decrypt(stored: Optional[str]) -> Optional[str]:
    if stored is None or stored == "":
        return None
    if not is_encrypted(stored):
        return stored  # legacy plain text
    try:
        blob = base64.b64decode(stored[len(PREFIX):])
        return _unprotect(blob).decode("utf-8")
    except CredentialError:
        raise
    except Exception as e:
        raise CredentialError(
            "Could not decrypt a stored password. It was probably saved by a "
            "different Windows account or PC. Set it again with "
            "'python manage_targets.py set-password <path>'."
        ) from e
