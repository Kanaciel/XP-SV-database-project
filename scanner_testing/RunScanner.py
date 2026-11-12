"""Scanner entry point: scans every enabled network target on a loop.

Settings (interval, delay, DB path, ...) live in settings.py and can be
overridden with environment variables. Logs go to logs/scanner.log.
"""
import logging
import sys
import time

import settings
from config import TARGET_CONFIGS
from credentials import CredentialError
from database import DatabaseManager
from logging_setup import setup_logging
from scanner import NetworkReportScanner

log = logging.getLogger("RunScanner")


def run_cycle(db: DatabaseManager, scanner: NetworkReportScanner) -> None:
    # Re-read targets every cycle so edits to the table (new IPs, changed
    # passwords, enable/disable) apply without restarting the scanner.
    targets = db.get_targets()
    if not targets:
        log.warning("No network targets in the database. Add one with manage_targets.py.")

    for target in targets:
        try:
            scanner.scan_target(
                target,
                max_files=settings.MAX_FILES_PER_TARGET,
                delay_seconds=settings.FILE_DELAY_SECONDS,
            )
        except Exception:
            # One broken target must never stop the others.
            log.exception("Unexpected error while scanning %s", target.path)


def main() -> int:
    setup_logging(settings.LOG_DIR, settings.LOG_LEVEL)
    log.info("Database: %s", settings.DB_PATH)

    try:
        # Creates the database / adds new columns if needed.
        db = DatabaseManager(settings.DB_PATH, busy_timeout=settings.DB_BUSY_TIMEOUT_SECONDS)
    except Exception:
        log.exception("Could not open the database; stopping.")
        return 1

    seeded = db.seed_targets_if_empty(TARGET_CONFIGS)
    if seeded:
        log.info("Seeded %d network targets from config.py.", seeded)

    try:
        migrated = db.encrypt_legacy_passwords()
        if migrated:
            log.info("Encrypted %d password(s) that were stored as plain text.", migrated)
    except CredentialError as e:
        log.warning("Plain-text passwords are still in the database: %s", e)

    scanner = NetworkReportScanner(db, batch_size=settings.BATCH_SIZE)
    log.info("Scanner is running. Press Ctrl+C to stop.")

    try:
        while True:
            log.info("Starting scan cycle.")
            try:
                run_cycle(db, scanner)
            except Exception:
                # e.g. the database is briefly unavailable. Keep the
                # service alive and try again next cycle.
                log.exception("Scan cycle failed; will retry next cycle.")

            log.info("Next scan cycle in %d minutes.", settings.SCAN_INTERVAL_SECONDS // 60)
            time.sleep(settings.SCAN_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        log.info("Scanner stopped by user.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
