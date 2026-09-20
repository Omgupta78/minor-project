"""Safe operational checks and cleanup for FaceID Attendance.

Default mode only reports. Pass --delete-orphans to remove unreferenced files,
and always take a backup first.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import db


def referenced_photos(conn) -> set[Path]:
    paths = {Path(r[0]).resolve() for r in conn.execute("SELECT photo_path FROM students WHERE photo_path IS NOT NULL")}
    try:
        paths.update(Path(r[0]).resolve() for r in conn.execute("SELECT photo_path FROM student_encodings WHERE photo_path IS NOT NULL"))
    except sqlite3.OperationalError:
        pass
    return paths


def backup(destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = destination / f"faceid-backup-{stamp}.tar.gz"
    db_copy = destination / f"attendance-{stamp}.db"
    with db.connect() as source, sqlite3.connect(db_copy) as target:
        source.backup(target)
    with tarfile.open(out, "w:gz") as archive:
        archive.add(db_copy, arcname="attendance.db")
        if db.FACES_DIR.exists() if hasattr(db, "FACES_DIR") else False:
            archive.add(db.FACES_DIR, arcname="faces")
    db_copy.unlink(missing_ok=True)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete-orphans", action="store_true")
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    if args.backup_dir:
        print("backup:", backup(args.backup_dir))
    faces = Path(__import__("os").environ.get("FACES_DIR", Path(__file__).parent / "faces")).resolve()
    with db.session_scope() as conn:
        refs = referenced_photos(conn)
    orphans = sorted(p for p in faces.rglob("*") if p.is_file() and p.name != ".gitkeep" and p.resolve() not in refs)
    for path in orphans:
        print("orphan:", path)
        if args.delete_orphans:
            path.unlink()
    print(f"{len(orphans)} orphan photo(s); {'deleted' if args.delete_orphans else 'report only'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
