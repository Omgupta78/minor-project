"""
import_students.py - enrol a whole class from a folder or a zip, from the
command line.

This is the path to use for a full roster. Encoding a reference photo takes
about a second, so 120 students with three photos each is several minutes of
work -- longer than a web request may live. The web page runs the same import
as a background job, but a terminal has no timeout at all, so for the first
big import this is the calmer option.

    # see what would happen, change nothing
    python import_students.py roster/ --class "CSE 3rd Year A" --dry-run

    # do it
    python import_students.py roster/ --class "CSE 3rd Year A" --subject DBMS

    # a folder downloaded from Google Drive arrives as a zip; that works too
    python import_students.py ~/Downloads/CSE-3A.zip --class "CSE 3rd Year A"

The accepted folder layouts, and how photos should be named, are in
IMPORT.md. Run with --dry-run first: it prints exactly which students were
recognised and why any were skipped, without touching the database.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

import auth
import db
import recognition
import roster_import


def pick_teacher(conn, email: str | None) -> int | None:
    """Whose roster is this? Classes belong to a teacher, so one is required."""
    if email:
        row = auth.get_teacher_by_email(conn, email)
        if row is None:
            raise SystemExit(f"No account with the email {email}.")
        return int(row["id"])
    rows = conn.execute(
        "SELECT id, email, name FROM teachers WHERE active = 1 ORDER BY id"
    ).fetchall()
    if not rows:
        raise SystemExit(
            "There are no teacher accounts yet. Start the app and sign up first."
        )
    if len(rows) == 1:
        return int(rows[0]["id"])
    print("Several accounts exist. Say which one with --teacher EMAIL:")
    for row in rows:
        print(f"  {row['email']}  ({row['name']})")
    raise SystemExit(2)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.strip().split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Folder layouts and photo naming are documented in IMPORT.md.",
    )
    parser.add_argument("source", type=Path, help="a folder, or a .zip of one")
    parser.add_argument("--class", dest="class_name", required=True,
                        help="the class to enrol into; created if new")
    parser.add_argument("--subject", default="")
    parser.add_argument("--teacher", default=None,
                        help="email of the owning account (needed if several exist)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would happen and change nothing")
    parser.add_argument("--skip-existing", action="store_true",
                        help="leave students who are already enrolled alone "
                             "(the default replaces their photos)")
    parser.add_argument("--max-photos", type=int, default=5,
                        help="reference photos to keep per student (default 5)")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="roster-") as workdir:
        try:
            root = roster_import.unpack(args.source, workdir)
            plan = roster_import.build_plan(root)
        except roster_import.ImportError_ as exc:
            print(f"FAILED: {exc}")
            return 2

        print(roster_import.describe(plan))
        print()

        if not plan.usable:
            print("Nothing to import. Fix the problems above and run it again.")
            print("IMPORT.md explains the folder layouts and photo naming.")
            return 1

        if args.dry_run:
            print(f"Dry run: {len(plan.usable)} student(s) would be enrolled "
                  f"from {sum(len(s.photos) for s in plan.usable)} photo(s).")
            print("Nothing was changed. Run again without --dry-run to do it.")
            return 0

        try:
            recognition.ensure_available()
        except recognition.RecognitionUnavailable as exc:
            print(f"FAILED: {exc}")
            return 3

        db.init_db()
        started = time.time()
        with db.session_scope() as conn:
            teacher_id = pick_teacher(conn, args.teacher)
            class_id = db.create_class(
                conn, args.class_name, args.subject, teacher_id=teacher_id
            )
            print(f"Enrolling into '{args.class_name}' (class {class_id}) "
                  f"for teacher {teacher_id}.")
            print("Each photo takes about a second to encode.\n")

            def progress(done: int, total: int, roll: str) -> None:
                elapsed = time.time() - started
                rate = done / elapsed if elapsed > 0 else 0
                left = (total - done) / rate if rate > 0 else 0
                sys.stdout.write(
                    f"\r  {done}/{total}  {roll:<16} "
                    f"about {int(left // 60)}m {int(left % 60):02d}s left   "
                )
                sys.stdout.flush()

            result = roster_import.enrol(
                plan, conn, class_id,
                faces_dir=Path(os.environ.get("FACES_DIR", Path(__file__).parent / "faces")),
                replace=not args.skip_existing,
                max_photos=args.max_photos,
                on_progress=progress,
            )

        print("\n")
        print(f"Added   : {result.added}")
        print(f"Updated : {result.updated}")
        print(f"Failed  : {result.failed}")
        print(f"Photos  : {result.photos_used} used, {result.photos_rejected} rejected")
        print(f"Took    : {time.time() - started:.0f}s")
        if result.messages:
            print("\nPer-photo notes:")
            for message in result.messages[:40]:
                print(f"  {message}")
            if len(result.messages) > 40:
                print(f"  ... and {len(result.messages) - 40} more")
        print("\nOpen the Students page to check the roster.")
        return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
