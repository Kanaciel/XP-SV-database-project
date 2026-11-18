import os
import re
from typing import Optional

# Windows error codes from WNetAddConnection2, in plain words.
_HINTS = {
    53: "the computer was not found on the network (off, unplugged, or wrong IP)",
    67: "the computer or share name was not found (off, wrong IP, or wrong share name)",
    64: "the network connection dropped",
    86: "wrong password",
    1326: "wrong username or password",
    1219: "Windows is already connected to that computer with a different username",
    1909: "the account on that computer is locked out",
    1330: "the password on that computer has expired",
    1331: "the account on that computer is disabled",
    1385: "that account is not allowed to log in over the network",
}
# Codes meaning the computer can't be reached at all: no point trying anything else.
UNREACHABLE = {53, 67, 64, 121, 1203, 1231, 1232}


class ShareLoginError(RuntimeError):
    def __init__(self, winerror: Optional[int], message: str):
        super().__init__(message)
        self.winerror = winerror


def share_root(unc_path: str) -> str:
    """\\\\server\\share\\sub\\dir -> \\\\server\\share"""
    match = re.match(r"^\\\\[^\\]+\\[^\\]+", unc_path)
    if not match:
        raise ValueError(f"Not a UNC share path: {unc_path}")
    return match.group(0)


def is_accessible(unc_path: str) -> bool:
    """True if this PC can already open the folder, e.g. because Windows is
    still logged in to that computer (Explorer, a mapped drive, saved
    credentials in Credential Manager) or the share needs no login."""
    try:
        if unc_path.startswith("\\\\"):
            # trailing backslash: a bare \\server\share root is only a dir with it
            return os.path.isdir(unc_path.rstrip("\\/") + "\\")
        return os.path.isdir(unc_path)
    except OSError:
        return False


def connect_share(unc_path: str, username: str, password: str) -> None:
    """Open an authenticated SMB connection to \\\\server\\share (Windows only).

    Raises ShareLoginError with a readable reason. Error 1219 (Windows is
    already connected to that server, possibly as another user) is not an
    error here: the caller checks access afterwards.
    """
    # Imported here so the rest of the project (and its tests) can be
    # imported on machines without pywin32.
    import pywintypes
    import win32netcon
    import win32wnet

    nr = win32wnet.NETRESOURCE()
    nr.dwType = win32netcon.RESOURCETYPE_DISK
    nr.lpRemoteName = share_root(unc_path)

    try:
        win32wnet.WNetAddConnection2(nr, password, username, 0)
    except pywintypes.error as e:
        if e.winerror == 1219:
            return
        hint = _HINTS.get(e.winerror, e.strerror)
        raise ShareLoginError(e.winerror, f"{hint} (Windows error {e.winerror})") from e
