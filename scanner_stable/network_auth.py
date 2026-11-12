import re

import pywintypes
import win32netcon
import win32wnet


def connect_share(unc_path: str, username: str, password: str) -> None:
    """Open an authenticated SMB connection to \\\\server\\share (Windows only)."""
    match = re.match(r"^\\\\[^\\]+\\[^\\]+", unc_path)
    if not match:
        raise ValueError(f"Not a UNC share path: {unc_path}")

    nr = win32wnet.NETRESOURCE()
    nr.dwType = win32netcon.RESOURCETYPE_DISK
    nr.lpRemoteName = match.group(0)

    try:
        win32wnet.WNetAddConnection2(nr, password, username, 0)
    except pywintypes.error as e:
        # 1219 = a connection to this server already exists; reuse it.
        if e.winerror != 1219:
            raise
