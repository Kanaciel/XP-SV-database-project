from config import NetworkTarget
from database import DatabaseManager

db = DatabaseManager("test_reports.db")
for t in db.get_targets():
    print(t.path, t.test_station, t.enabled, t.username)

# example update
db.upsert_target(NetworkTarget(
    path=r"\\172.24.125.10\Reports",
    test_station="Chroma 3",
    username=r"172.24.125.10\scanner",   # omit both if no login needed
    password="secret",
))

# pausing a station
db.set_target_enabled(r"\\172.24.122.194\Reports", False)   # True to resume


# delete station
db.delete_target(r"\\172.24.122.194\Reports")