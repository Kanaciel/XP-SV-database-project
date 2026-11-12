import os
import time
from pathlib import Path

from config import NetworkTarget
from database import DatabaseManager, normalize_path
from network_auth import connect_share
from parsers import ReportParserFactory


class NetworkReportScanner:
    def __init__(self, db_manager: DatabaseManager, batch_size: int = 100):
        self.db = db_manager
        self.batch_size = batch_size

        # In-memory cache of every file path already stored. Checking this
        # set is nearly free, so known files are skipped without being
        # opened, parsed, or throttled.
        self.known_paths = self.db.load_known_paths()
        print(f"[STARTUP] Loaded {len(self.known_paths)} known file paths.")

    def resolve_test_station(self, target: NetworkTarget, current_path: str) -> str:
        """Determines station name from manual config, folder name, or IP."""
        if target.test_station:
            return target.test_station

        # Fallback 1: Extract IP address from UNC path
        parts = Path(current_path).parts
        if len(parts) > 1 and parts[0].startswith(r"\\"):
            return parts[1]

        # Fallback 2: Directory folder name
        return Path(current_path).name

    def scan_target(
        self,
        target: NetworkTarget,
        max_files: int = None,
        delay_seconds: float = 0.5,
    ):
        """Scan one target.

        max_files limits how many NEW files get parsed per target (files
        already in the database don't count toward it).
        delay_seconds is only applied after parsing a new file.
        """
        if not target.enabled:
            print(f"[DISABLED] Skipping {target.path}")
            return

        # Reconnect every cycle: Windows drops idle SMB sessions, and
        # re-connecting to a live session is harmless.
        if target.username:
            try:
                connect_share(target.path, target.username, target.password or "")
            except Exception as e:
                print(f"[AUTH ERROR] {target.path}: {e}")
                return

        print(f"\n[SCAN START] {target.path}")

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
            print(f"[ACCESS ERROR] {err.filename}: {err}")

        def flush():
            if not pending:
                return
            batch = list(pending)
            pending.clear()
            try:
                added = self.db.insert_reports(batch)
            except Exception as e:
                stats["errors"] += len(batch)
                print(f"[DB ERROR] Batch of {len(batch)} failed: {e}")
                return
            stats["inserted"] += added
            stats["duplicates"] += len(batch) - added
            for row in batch:
                self.known_paths.add(normalize_path(row["file_path"]))
            print(f"[BATCH] Inserted {added}/{len(batch)} reports.")

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
                        parser = ReportParserFactory.get_parser(full_path)
                    except ValueError:
                        stats["unsupported"] += 1
                        continue

                    if max_files is not None and stats["parsed"] >= max_files:
                        print("[TEST LIMIT] Maximum new-file count reached.")
                        return

                    # Slow path: new file -> parse, queue, throttle.
                    try:
                        data = parser.parse(full_path)
                        data["test_station"] = station_name
                        stats["parsed"] += 1
                        pending.append(data)
                        print(
                            f"[PARSED] {data['result']} | "
                            f"{data['file_name']} | {full_path}"
                        )

                        if len(pending) >= self.batch_size:
                            flush()

                    except Exception as e:
                        stats["errors"] += 1
                        print(f"[ERROR] {full_path}: {e}")

                    if delay_seconds > 0:
                        time.sleep(delay_seconds)

        except Exception as e:
            stats["errors"] += 1
            print(f"[SCAN ERROR] {target.path}: {e}")

        finally:
            # Always write out whatever is queued, including on early
            # return (test limit), errors, or Ctrl+C.
            flush()
            print(
                f"[SCAN SUMMARY] Files seen: {stats['seen']} | "
                f"Already known (skipped): {stats['skipped_known']} | "
                f"Unsupported: {stats['unsupported']} | "
                f"Parsed: {stats['parsed']} | "
                f"Inserted: {stats['inserted']} | "
                f"Duplicates: {stats['duplicates']} | "
                f"Errors: {stats['errors']}"
            )
            print(f"[SCAN END] {target.path}")
