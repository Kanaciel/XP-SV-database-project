
"""Manage master accounts. Run this on the PC that hosts the web app.

    python manage_accounts.py add khang --name "Khang"
    python manage_accounts.py list
    python manage_accounts.py passwd khang
    python manage_accounts.py disable khang
    python manage_accounts.py enable khang
    python manage_accounts.py delete khang --yes
"""
import argparse
import getpass
import sys

import accounts


def ask_new_password():
    pw = getpass.getpass("Password (typing is hidden): ")
    if getpass.getpass("Repeat password: ") != pw:
        sys.exit("The two passwords do not match. Nothing was changed.")
    return pw


def main():
    p = argparse.ArgumentParser(description="Manage master accounts")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="create a master account")
    a.add_argument("username")
    a.add_argument("--name", help="display name shown on the page")
    sub.add_parser("list", help="show all accounts")
    for name, text in (("passwd", "change a password"), ("disable", "block an account"),
                       ("enable", "unblock an account"), ("delete", "delete an account")):
        x = sub.add_parser(name, help=text)
        x.add_argument("username")
        if name == "delete":
            x.add_argument("--yes", action="store_true", help="do not ask for confirmation")

    args = p.parse_args()
    accounts.init_accounts_db()

    try:
        if args.cmd == "add":
            accounts.create_account(args.username, ask_new_password(), args.name)
            print(f"Master account '{args.username}' created.")
        elif args.cmd == "list":
            rows = accounts.list_accounts()
            if not rows:
                print("No accounts yet. Create one with: python manage_accounts.py add <username>")
            for r in rows:
                state = "active" if r["is_active"] else "DISABLED"
                print(f"{r['username']:<20} {r['role']:<8} {state:<9} created {r['created_at']}  "
                      f"last login {r['last_login'] or '-'}")
        elif args.cmd == "passwd":
            ok = accounts.set_password(args.username, ask_new_password())
            print("Password changed." if ok else "No such account.")
        elif args.cmd in ("disable", "enable"):
            ok = accounts.set_active(args.username, args.cmd == "enable")
            print(f"Account {args.cmd}d." if ok else "No such account.")
        elif args.cmd == "delete":
            if not args.yes and input(f"Delete '{args.username}'? Type yes to confirm: ").strip() != "yes":
                sys.exit("Cancelled.")
            print("Account deleted." if accounts.delete_account(args.username) else "No such account.")
    except ValueError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()

    