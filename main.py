"""Start the scanner and/or the web app from one window.

    python main.py                 both, using scanner_stable
    python main.py --testing       both, using scanner_testing
    python main.py scanner         only the scanner
    python main.py web             only the web app

Stop everything with Ctrl+C.

Each program runs as its own child process, exactly as if you had started it by
hand, with the same Python (so the same .venv). This file never imports their
code, so the scanner and the web app stay independent and can still be started
on their own. Both are pointed at the SAME database file: the scanner folder's
XPSV_DB_PATH (from its scanner_settings.env or the environment), default
<scanner folder>/test_reports.db.
"""
import argparse
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web app"
STOP_WAIT_SECONDS = 15   # how long to let a program save its work after Ctrl+C
WEB_PORT = 5000          # must match the port in web app/app.py


def _clean(value):
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def scanner_db_path(scanner_dir: Path) -> Path:
    """Same rule as the scanner's settings.py: env var, then scanner_settings.env, then default."""
    value = _clean(os.environ.get("XPSV_DB_PATH"))
    settings_file = scanner_dir / "scanner_settings.env"
    if not value and settings_file.is_file():
        for line in settings_file.read_text(encoding="utf-8-sig").splitlines():
            name, sep, raw = line.strip().partition("=")
            if sep and not name.startswith("#") and name.strip().lstrip("$").replace("env:", "") == "XPSV_DB_PATH":
                value = _clean(raw)
    path = Path(os.path.expandvars(os.path.expanduser(value or "test_reports.db")))
    return path if path.is_absolute() else (scanner_dir / path).resolve()


def _relay(name: str, stream) -> None:
    """Copy a child's output to this window, each line tagged with its name."""
    for line in iter(stream.readline, ""):
        sys.stdout.write(f"[{name}] {line}")
        sys.stdout.flush()


def start(name: str, script: Path, env: dict) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, script.name], cwd=script.parent, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    threading.Thread(target=_relay, args=(name, proc.stdout), daemon=True).start()
    print(f"[main] started {name} (pid {proc.pid}): {script}")
    return proc


def lan_ip():
    """This PC's address on the network (no traffic is actually sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def wait_for_web(proc, seconds=20) -> bool:
    """True once the web app accepts connections."""
    deadline = time.time() + seconds
    while time.time() < deadline and proc.poll() is None:
        try:
            with socket.create_connection(("127.0.0.1", WEB_PORT), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def print_links() -> None:
    # Same token rule as web app/app.py
    token = os.environ.get("KO_PHAI_TEST_THI_CUT", "123")
    links = [("this PC", "127.0.0.1")]
    links.append(("other PCs, by name", socket.gethostname()))
    ip = lan_ip()
    if ip and not ip.startswith("127."):
        links.append(("other PCs, by IP", ip))
    print("[main] web app is up. Open (Ctrl+click):")
    for label, host in links:
        print(f"[main]   http://{host}:{WEB_PORT}/?token={token}    ({label})")


def stop_all(procs: dict) -> None:
    # Ctrl+C in this window already reached the children (same console);
    # give them time to save their work, then force the rest.
    deadline = time.time() + STOP_WAIT_SECONDS
    for name, proc in procs.items():
        try:
            proc.wait(timeout=max(0.1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            print(f"[main] {name} did not stop in time; ending it.")
            proc.terminate()
            proc.wait()
    print("[main] all stopped.")


def main() -> int:
    p = argparse.ArgumentParser(description="Start the scanner and/or the web app.")
    p.add_argument("which", nargs="?", choices=("both", "scanner", "web"), default="both",
                   help="what to start (default: both)")
    p.add_argument("--testing", action="store_true",
                   help="use scanner_testing instead of scanner_stable")
    p.add_argument("--scanner-folder", metavar="NAME",
                   help="use another scanner folder (overrides --testing)")
    args = p.parse_args()

    scanner_dir = ROOT / (args.scanner_folder or ("scanner_testing" if args.testing else "scanner_stable"))
    if not (scanner_dir / "RunScanner.py").is_file():
        return f"No RunScanner.py in {scanner_dir}"
    if args.which != "scanner" and not (WEB_DIR / "app.py").is_file():
        return f"No app.py in {WEB_DIR}"

    db = scanner_db_path(scanner_dir)
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8",
               XPSV_DB_PATH=str(db),       # scanner writes here
               TEST_REPORTS_DB=str(db))    # web app reads here
    print(f"[main] database: {db}")

    procs = {}
    if args.which in ("both", "scanner"):
        procs["scanner"] = start("scanner", scanner_dir / "RunScanner.py", env)
    if args.which in ("both", "web"):
        if "scanner" in procs:
            time.sleep(2)   # let the scanner create/upgrade the database first
        procs["web"] = start("web", WEB_DIR / "app.py", env)
        if wait_for_web(procs["web"]):
            print_links()
    print("[main] press Ctrl+C to stop.")

    reported = set()
    try:
        while True:
            for name, proc in procs.items():
                if name not in reported and proc.poll() is not None:
                    reported.add(name)
                    others = [n for n in procs if n not in reported]
                    print(f"[main] WARNING: {name} exited with code {proc.returncode}."
                          + (f" {', '.join(others)} keeps running." if others else ""))
            if len(reported) == len(procs):
                return max(proc.returncode for proc in procs.values())
            time.sleep(1)
    except KeyboardInterrupt:
        print("[main] stopping...")
        stop_all(procs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
