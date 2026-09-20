"""Report/clean orphan face files and create consistent backups."""
from __future__ import annotations

import argparse
import os
import sqlite3
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import db


def faces_dir() -> Path:
    return Path(os.environ.get("FACES_DIR", Path(__file__).parent / "faces")).resolve()


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
    archive_path = destination / f"faceid-backup-{stamp}.tar.gz"
    db_copy = destination / f"attendance-{stamp}.db"
    with db.connect() as source, sqlite3.connect(db_copy) as target:
        source.backup(target)
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(db_copy, arcname="attendance.db")
        if faces_dir().exists():
            archive.add(faces_dir(), arcname="faces")
    db_copy.unlink(missing_ok=True)
    return archive_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete-orphans", action="store_true")
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    if args.backup_dir:
        print("backup:", backup(args.backup_dir))
    root = faces_dir()
    with db.session_scope() as conn:
        refs = referenced_photos(conn)
    orphans = sorted(p for p in root.rglob("*") if p.is_file() and p.name != ".gitkeep" and p.resolve() not in refs)
    for path in orphans:
        print("orphan:", path)
        if args.delete_orphans:
            path.unlink()
    print(f"{len(orphans)} orphan photo(s); {'deleted' if args.delete_orphans else 'report only'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
