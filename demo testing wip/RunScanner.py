import time
from pathlib import Path
from datetime import datetime

from config import TARGET_CONFIGS
from database import DatabaseManager
from scanner import NetworkReportScanner


# Configuration
SCAN_INTERVAL_SECONDS = 15 * 60
FILE_DELAY_SECONDS = 0.5

# Start with a small test. Change to None for a full scan.
MAX_FILES_PER_TARGET = 20


def main():
    # Store the database alongside this script, regardless
    # of which directory the terminal was opened in.
    project_dir = Path(__file__).resolve().parent
    db_path = project_dir / "test_reports.db"

    print(f"[STARTUP] Database: {db_path}")

    # Creates the database and tables if they do not exist.
    db = DatabaseManager(str(db_path))

    # First run only: copy the targets from config.py into the database.
    seeded = db.seed_targets_if_empty(TARGET_CONFIGS)
    if seeded:
        print(f"[STARTUP] Seeded {seeded} network targets from config.py.")

    scanner = NetworkReportScanner(db)

    print("[STARTUP] Scanner is running. Press Ctrl+C to stop.")

    try:
        while True:
            scan_started = datetime.now()
            print(
                f"\n[{scan_started:%Y-%m-%d %H:%M:%S}] "
                "Starting scan cycle."
            )

            # Re-read targets every cycle so edits to the table
            # (new IPs, changed passwords, enable/disable) apply
            # without restarting the scanner.
            targets = db.get_targets()
            if not targets:
                print("[WARNING] No network targets in the database.")

            for target in targets:
                scanner.scan_target(
                    target,
                    max_files=MAX_FILES_PER_TARGET,
                    delay_seconds=FILE_DELAY_SECONDS,
                )

            print(
                f"\n[WAIT] Next scan cycle in "
                f"{SCAN_INTERVAL_SECONDS // 60} minutes."
            )
            time.sleep(SCAN_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Scanner stopped by user.")


if __name__ == "__main__":
    main()
