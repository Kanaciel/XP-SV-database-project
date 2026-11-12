import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from config import NetworkTarget
from database import DatabaseManager, normalize_path
from network_auth import connect_share
from parsers import ReportParserFactory

log = logging.getLogger(__name__)


class NetworkReportScanner:
    def __init__(self, db_manager: DatabaseManager, batch_size: int = 100):
        self.db = db_manager
        self.batch_size = batch_size

        # In-memory cache of every file path already stored. Checking this
        # set is nearly free, so known files are skipped without being
        # opened, parsed, or throttled.
        self.known_paths = self.db.load_known_paths()
        log.info("Loaded %d known file paths.", len(self.known_paths))

    @staticmethod
    def resolve_test_station(target: NetworkTarget, current_path: str) -> str:
        """Station name: the configured one, else the server/IP of the share."""
        if target.test_station:
            return target.test_station

        # \\172.24.120.248\Reports -> "172.24.120.248". (pathlib can't be
        # used here: it treats \\server\share as one "drive" part.)
        match = re.match(r"^[\\/]{2}([^\\/]+)", target.path)
        if match:
            return match.group(1)

        # Not a UNC path (e.g. a local folder): use the folder name.
        return Path(target.path.rstrip("\\/")).name or target.path

    def scan_target(
        self,
        target: NetworkTarget,
        max_files: Optional[int] = None,
        delay_seconds: float = 0.5,
    ):
        """Scan one target.

        max_files limits how many NEW files get parsed per target (files
        already in the database don't count toward it).
        delay_seconds is only applied after parsing a new file.
        """
        if not target.enabled:
            log.info("Skipping disabled target %s", target.path)
            return

        # Reconnect every cycle: Windows drops idle SMB sessions, and
        # re-connecting to a live session is harmless.
        if target.username:
            if not target.password:
                log.error(
                    "No usable password for %s (user %s). Set one with: "
                    'python manage_targets.py set-password "%s"',
                    target.path, target.username, target.path,
                )
                return
            try:
                connect_share(target.path, target.username, target.password)
            except Exception as e:
                log.error("Could not log in to %s as %s: %s", target.path, target.username, e)
                return

        log.info("Scan start: %s", target.path)

        # os.path.join omits the separator after a bare UNC share root
        # (\\server\share), so os.walk would build child paths like
        # \\server\shareFolder instead of \\server\share\Folder. A trailing
        # backslash makes Python treat the share root as a directory.
        walk_root = target.path.rstrip("\\/") + "\\"

        stats = {
            "seen": 0,
            "skipped_known": 0,
            "unsupported": 0,
            "parsed": 0,
            "inserted": 0,
            "duplicates": 0,
            "errors": 0,
        }
        pending = []  # parsed rows waiting for the next batch insert

        def handle_error(err):
            stats["errors"] += 1
            log.warning("Cannot access %s: %s", err.filename, err)

        def flush():
            if not pending:
                return
            batch = list(pending)
            pending.clear()
            try:
                added = self.db.insert_reports(batch)
            except Exception:
                stats["errors"] += len(batch)
                log.exception("Database insert of %d reports failed", len(batch))
                return
            stats["inserted"] += added
            stats["duplicates"] += len(batch) - added
            for row in batch:
                self.known_paths.add(normalize_path(row["file_path"]))
            log.info("Inserted %d/%d reports.", added, len(batch))

        try:
            for root, dirs, files in os.walk(walk_root, onerror=handle_error):
                station_name = self.resolve_test_station(target, root)

                for file in files:
                    stats["seen"] += 1
                    full_path = os.path.join(root, file)

                    # Fast path: already stored -> no I/O, no delay.
                    if normalize_path(full_path) in self.known_paths:
                        stats["skipped_known"] += 1
                        continue

                    # Fast path: unsupported extension -> no delay.
                    try:
                        parser = ReportParserFactory.get_parser(full_path, target.parser_type)
                    except ValueError:
                        stats["unsupported"] += 1
                        continue

                    if max_files is not None and stats["parsed"] >= max_files:
                        log.info("Reached max_files=%d for %s.", max_files, target.path)
                        return stats

                    # Slow path: new file -> parse, queue, throttle.
                    try:
                        data = parser.parse(full_path)
                        data["test_station"] = station_name
                        stats["parsed"] += 1
                        pending.append(data)
                        log.debug("Parsed %s | %s", data["result"], full_path)

                        if len(pending) >= self.batch_size:
                            flush()

                    except Exception as e:
                        stats["errors"] += 1
                        log.warning("Could not parse %s: %s", full_path, e)

                    if delay_seconds > 0:
                        time.sleep(delay_seconds)

        except Exception:
            stats["errors"] += 1
            log.exception("Scan of %s stopped early", target.path)

        finally:
            # Always write out whatever is queued, including on early
            # return (test limit), errors, or Ctrl+C.
            flush()
            log.info(
                "Scan end: %s | seen %d | already known %d | unsupported %d | "
                "parsed %d | inserted %d | duplicates %d | errors %d",
                target.path, stats["seen"], stats["skipped_known"], stats["unsupported"],
                stats["parsed"], stats["inserted"], stats["duplicates"], stats["errors"],
            )
        return stats
