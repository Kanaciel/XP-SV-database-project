from dataclasses import dataclass, field
from typing import Optional


@dataclass
class NetworkTarget:
    path: str  # UNC path e.g., r"\\172.24.120.248\Reports"
    test_station: Optional[str] = None  # If None, dynamically extract from IP/Folder
    parser_type: str = "auto"
    enabled: bool = True
    username: Optional[str] = None  # e.g. r"172.24.123.61\scanner"; None = no login needed
    # repr=False so the password never shows up if a target is printed/logged.
    password: Optional[str] = field(default=None, repr=False)

    def __post_init__(self):
        # Stray spaces in a username make Windows logins fail silently.
        if self.username is not None:
            self.username = self.username.strip() or None


# Initial targets. These are only used to SEED the database the first time
# (when the network_targets table is empty). After that, the database is the
# source of truth and edits here have no effect.
#
# NEVER put passwords here: this file is committed to git. Set them with
#     python manage_targets.py set-password "\\172.24.123.61\Reports"
# which stores them encrypted in the database.
TARGET_CONFIGS = [
    NetworkTarget(path=r"\\172.24.120.248\Reports", test_station="Chroma 2"),
    NetworkTarget(path=r"\\172.24.123.61\Reports", test_station="NHR", username=r"s12674\nhr"),
    NetworkTarget(path=r"\\172.24.122.194\Reports", test_station="Chroma 1"),
]
