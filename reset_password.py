"""
reset_password.py - get back into the app when a teacher forgets their password.

change_password() in the web app needs the old password, which is no help to
somebody who has forgotten it, and there is no email server here to send a
reset link to. So recovery is done the way it is done for a single-file
database: from the machine the database lives on.

    python reset_password.py --list                      who has an account
    python reset_password.py --email you@college.edu     set a new password
    python reset_password.py --email you@college.edu --password "new one"

This grants no access that the person running it does not already have. The
database file is right there; anyone who can run this could already read or
replace it. What it does not do is print or recover the old password -- those
are stored as PBKDF2 hashes and cannot be reversed, which is the point.

Passwords are never passed on the command line unless you insist: without
--password you are prompted, and the typing is not echoed or kept in your
shell history.
"""
from __future__ import annotations

import argparse
import getpass
import sys

import auth
import db


def show_accounts(conn) -> int:
    rows = conn.execute(
        "SELECT id, email, name, is_admin, active, last_login FROM teachers ORDER BY id"
    ).fetchall()
    if not rows:
        print("There are no accounts in this database yet.")
        print("Start the app and open /signup -- the first account is always allowed,")
        print("even when ALLOW_SIGNUP is 0.")
        return 1
    print(f"{len(rows)} account(s) in {db.DB_PATH}:\n")
    print(f"  {'email':<34}{'name':<24}{'admin':<7}{'active':<8}last login")
    for row in rows:
        print(f"  {row['email']:<34}{row['name'][:22]:<24}"
              f"{'yes' if row['is_admin'] else 'no':<7}"
              f"{'yes' if row['active'] else 'NO':<8}{row['last_login'] or 'never'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.strip().split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--list", action="store_true", help="show the accounts and stop")
    parser.add_argument("--email", help="the account to reset")
    parser.add_argument(
        "--password",
        help="the new password; omit it to be prompted, which is safer "
             "because it keeps the password out of your shell history",
    )
    parser.add_argument(
        "--activate", action="store_true",
        help="also re-enable the account if it was deactivated",
    )
    args = parser.parse_args()

    db.init_db()

    with db.session_scope() as conn:
        if args.list or not args.email:
            code = show_accounts(conn)
            if not args.email:
                if code == 0:
                    print("\nReset one with:  python reset_password.py --email <address>")
                return code
            print()

        row = auth.get_teacher_by_email(conn, args.email)
        if row is None:
            print(f"No account with the email {args.email}.")
            print("Run with --list to see which addresses exist.")
            return 2

        password = args.password
        if not password:
            password = getpass.getpass(f"New password for {row['email']}: ")
            again = getpass.getpass("Type it again: ")
            if password != again:
                print("Those did not match. Nothing was changed.")
                return 3

        problem = auth.password_problem(password)
        if problem:
            print(f"{problem} Nothing was changed.")
            return 4

        conn.execute(
            "UPDATE teachers SET password_hash = ? WHERE id = ?",
            (auth.hash_password(password), row["id"]),
        )
        if args.activate:
            conn.execute("UPDATE teachers SET active = 1 WHERE id = ?", (row["id"],))

    print(f"\nDone. {args.email} can sign in with the new password.")
    if not args.activate and not row["active"]:
        print("Note: that account is deactivated, so it still cannot sign in.")
        print("Run again with --activate to re-enable it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
