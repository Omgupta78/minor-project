"""
migrate_to_db.py - one-time import of the old CSV-era data into SQLite.

What it does
------------
1. Creates the database schema.
2. Creates a class (default "CSE - Minor Project", override with --class).
3. Enrols every image in faces/ as a student, auto-assigning roll numbers,
   and caches the 128-D encoding so the app starts instantly.
4. Replays every attendance/*.csv file as a session: names in the CSV become
   PRESENT, everyone else in the roster becomes ABSENT.

Usage
-----
    python migrate_to_db.py
    python migrate_to_db.py --class "CSE 3rd Year" --subject "DBMS" --prefix CS24
    python migrate_to_db.py --skip-encodings      # roster only, no dlib needed
"""
from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime
from pathlib import Path

import db
import recognition

BASE_DIR = Path(__file__).resolve().parent
FACES_DIR = BASE_DIR / "faces"
CSV_DIR = BASE_DIR / "attendance"


def parse_csv_date(filename: str) -> str | None:
    """The old files were named yy-mm-dd.csv."""
    stem = Path(filename).stem
    for fmt in ("%y-%m-%d", "%Y-%m-%d", "%d-%m-%Y", "%d-%m-%y"):
        try:
            return datetime.strptime(stem, fmt).date().isoformat()
        except ValueError:
            continue
    match = re.search(r"(\d{2,4})-(\d{2})-(\d{2})", stem)
    if match:
        year = int(match.group(1))
        year += 2000 if year < 100 else 0
        return f"{year:04d}-{match.group(2)}-{match.group(3)}"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--class", dest="class_name", default="CSE - Minor Project")
    parser.add_argument("--subject", default="")
    parser.add_argument("--prefix", default="CS", help="roll number prefix")
    parser.add_argument("--skip-encodings", action="store_true")
    args = parser.parse_args()

    db.init_db()
    print(f"database : {db.DB_PATH}")

    with db.session_scope() as conn:
        class_id = db.create_class(conn, args.class_name, args.subject)
        print(f"class    : {args.class_name} (id {class_id})")

        # ---- 1. students from faces/ -------------------------------------
        existing = {r["name"].lower(): r["id"] for r in db.list_students(conn)}
        seq = len(existing)
        enrolled, skipped = 0, []

        if not FACES_DIR.exists():
            print(f"faces    : {FACES_DIR} not found, skipping enrolment")
        else:
            images = [
                p
                for p in sorted(FACES_DIR.iterdir())
                if p.suffix.lower() in recognition.IMAGE_EXTS
            ]
            print(f"faces    : {len(images)} image(s) found")
            for path in images:
                name = path.stem.replace("_", " ").strip().title()
                if name.lower() in existing:
                    print(f"  = {name} already enrolled")
                    continue

                encoding = None
                if not args.skip_encodings:
                    try:
                        encoding = recognition.encode_face(path)
                    except recognition.RecognitionUnavailable as exc:
                        print(f"\n{exc}\n(re-run with --skip-encodings to build the roster only)")
                        return
                    if encoding is None:
                        skipped.append(path.name)
                        print(f"  ! no face found in {path.name}")

                seq += 1
                roll_no = f"{args.prefix}-{seq:03d}"
                sid = db.create_student(
                    conn, roll_no, name, class_id, path.name, encoding
                )
                existing[name.lower()] = sid
                enrolled += 1
                mark = "+" if encoding is not None else "~"
                print(f"  {mark} {roll_no}  {name}")

        # ---- 2. replay old CSV files -------------------------------------
        by_name = {r["name"].lower(): r["id"] for r in db.list_students(conn, class_id)}
        sessions_made = 0

        if not CSV_DIR.exists():
            print(f"csv      : {CSV_DIR} not found, nothing to replay")
        else:
            files = sorted(CSV_DIR.glob("*.csv"))
            print(f"csv      : {len(files)} file(s) found")
            for path in files:
                on_date = parse_csv_date(path.name)
                if on_date is None:
                    print(f"  ? cannot read a date from {path.name}, skipped")
                    continue

                present: dict[int, dict] = {}
                with path.open(newline="", encoding="utf-8-sig") as handle:
                    for row in csv.DictReader(handle):
                        raw = (row.get("Name") or row.get("name") or "").strip()
                        if not raw:
                            continue
                        sid = by_name.get(raw.lower()) or by_name.get(
                            raw.replace("_", " ").title().lower()
                        )
                        if sid is None:
                            continue
                        present[sid] = {"confidence": None, "method": "face"}

                session_id = db.create_session(
                    conn, class_id, on_date, "1", "imported", len(present)
                )
                result = db.save_session_attendance(conn, session_id, class_id, present)
                sessions_made += 1
                print(
                    f"  + {on_date}  present {result['present']}  absent {result['absent']}"
                )

    print("\ndone.")
    print(f"  students enrolled : {enrolled}")
    print(f"  sessions imported : {sessions_made}")
    if skipped:
        print(f"  no face detected  : {', '.join(skipped)}")
        print("  replace those photos and run: curl -X POST localhost:5000/api/reload-faces")
    print("\nnext: python app.py")


if __name__ == "__main__":
    main()
