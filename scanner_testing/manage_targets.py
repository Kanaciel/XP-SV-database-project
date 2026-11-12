"""Manage the computers (network shares) the scanner reads from.

Passwords are typed at a hidden prompt and stored encrypted, so they never
appear in code, in git, or in your terminal history.

    python manage_targets.py list
    python manage_targets.py add "\\\\172.24.125.10\\Reports" --station "Chroma 3" --username "172.24.125.10\\scanner"
    python manage_targets.py add "\\\\172.24.130.5\\Reports" --station "BrandX 1" --parser html   # force a parser
    python manage_targets.py set-password "\\\\172.24.123.61\\Reports"
    python manage_targets.py disable "\\\\172.24.122.194\\Reports"
    python manage_targets.py enable  "\\\\172.24.122.194\\Reports"
    python manage_targets.py delete  "\\\\172.24.122.194\\Reports"
    python manage_targets.py encrypt-existing   # one-off: encrypt old plain-text passwords
"""
import argparse
import getpass
import sys

import settings
from config import NetworkTarget
from credentials import CredentialError
from database import DatabaseManager
from parsers import ReportParserFactory


def _ask_password() -> str:
    while True:
        first = getpass.getpass("Password (input hidden): ")
        if not first:
            print("Empty password; nothing saved.")
            return ""
        if getpass.getpass("Repeat password: ") == first:
            return first
        print("Passwords did not match, try again.")


def cmd_list(db, args):
    targets = db.get_targets(with_passwords=False)
    if not targets:
        print("No targets.")
    # Only shows whether a password is stored, never the value.
    with_pw = db.paths_with_password()
    for t in targets:
        print(f"{'ON ' if t.enabled else 'OFF'}  {t.path}  station={t.test_station!r}  "
              f"parser={t.parser_type}  user={t.username!r}  password={'set' if t.path in with_pw else 'none'}")


def cmd_add(db, args):
    existing = db.get_target(args.path)
    target = NetworkTarget(
        path=args.path,
        test_station=args.station if args.station is not None else (existing.test_station if existing else None),
        parser_type=args.parser if args.parser is not None else (existing.parser_type if existing else "auto"),
        enabled=existing.enabled if existing else True,
        username=args.username if args.username is not None else (existing.username if existing else None),
    )
    password = _ask_password() if target.username and not args.no_password else None
    if password:
        target.password = password
        db.upsert_target(target)
    else:
        db.upsert_target(target, keep_password=True)
    print(f"{'Updated' if existing else 'Added'} {args.path}.")


def cmd_set_password(db, args):
    if db.get_target(args.path) is None:
        sys.exit(f"No target with path {args.path}. Run 'list' to see them.")
    pw = _ask_password()
    db.set_target_password(args.path, pw or None)
    print("Password saved (encrypted)." if pw else "Password cleared.")


def cmd_enable(db, args, enabled=True):
    if not db.set_target_enabled(args.path, enabled):
        sys.exit(f"No target with path {args.path}.")
    print(f"{'Enabled' if enabled else 'Disabled'} {args.path}.")


def cmd_delete(db, args):
    if not db.delete_target(args.path):
        sys.exit(f"No target with path {args.path}.")
    print(f"Deleted {args.path}.")


def cmd_encrypt_existing(db, args):
    n = db.encrypt_legacy_passwords()
    print(f"Encrypted {n} plain-text password(s).")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=str(settings.DB_PATH), help="database file (default: %(default)s)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show all targets")

    p = sub.add_parser("add", help="add a target, or update an existing one")
    p.add_argument("path", help=r"UNC share path, e.g. \\172.24.125.10\Reports")
    p.add_argument("--station", help="test station name")
    p.add_argument("--username", help=r"login, e.g. 172.24.125.10\scanner")
    p.add_argument("--parser", choices=("auto", *ReportParserFactory.parser_names()),
                   help="force one report parser for this station (default: auto-detect)")
    p.add_argument("--no-password", action="store_true", help="don't ask for a password")

    for name, help_text in (("set-password", "change or clear a target's password"),
                            ("enable", "resume scanning a target"),
                            ("disable", "pause scanning a target"),
                            ("delete", "remove a target")):
        sub.add_parser(name, help=help_text).add_argument("path")

    sub.add_parser("encrypt-existing", help="encrypt passwords still stored as plain text")

    args = parser.parse_args(argv)
    db = DatabaseManager(args.db)
    handlers = {
        "list": cmd_list,
        "add": cmd_add,
        "set-password": cmd_set_password,
        "enable": lambda d, a: cmd_enable(d, a, True),
        "disable": lambda d, a: cmd_enable(d, a, False),
        "delete": cmd_delete,
        "encrypt-existing": cmd_encrypt_existing,
    }
    try:
        handlers[args.command](db, args)
    except CredentialError as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
