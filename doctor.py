"""doctor.py - tells you which version of this app your folder contains.

Run it from inside the project folder:

    python doctor.py

It needs nothing installed - no Flask, no dlib, no virtual environment. It
only reads the files on disk and reports whether multi-photo attendance is
present, and if not, exactly why.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(rel: str) -> str | None:
    path = ROOT / rel
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# (label, file, needle, must_be_present)
CHECKS: list[tuple[str, str, str, bool]] = [
    ("backend accepts a list of photos", "app.py", 'getlist("photos")', True),
    ("photo-per-session limit exists", "app.py", "MAX_PHOTOS_PER_SCAN", True),
    ("upload cap raised for many photos", "app.py", "MAX_UPLOAD_MB", True),
    ("multi-image recognition", "recognition.py", "def identify_many", True),
    ("best-sighting merge across photos", "recognition.py", "def merge_across_images", True),
    ("scan counts use images_scanned", "recognition.py", '"images_scanned": len(per_image)', True),
    ("scan counts cannot clobber images", "recognition.py", '"images": len(per_image)', False),
    ("several reference photos per student", "db.py", "def add_student_encoding", True),
    ("every reference photo is matched against", "db.py", "FROM student_encodings ORDER BY id", True),
    ("enrolment accepts several photos", "app.py", 'getlist("student_photo")', True),
    ("enrolment form allows several files", "templates/students_page.html", "multiple required", True),
    ("enrolment photos are quality checked", "recognition.py", "def quality_problem", True),
    ("enrolment encodings are jittered", "recognition.py", "num_jitters=ENROL_JITTERS", True),
    ("tiled detection for back rows", "recognition.py", "def detect_tiled", True),
    ("accuracy harness with a threshold sweep", "accuracy.py", "def sweep", True),
    ("file picker allows multi-select", "templates/index.html", "multiple", True),
    ("no capture attr blocking mobile multi-select", "templates/index.html", 'capture="environment"', False),
    ("thumbnail strip in the UI", "templates/index.html", "thumb-strip", True),
    ("photos are sent as a list", "templates/index.html", 'fd.append("photos"', True),
    ("offline stylesheet present", "static/app.css", "", True),
    ("offline icons present", "static/icons.js", "", True),
    ("no Tailwind CDN dependency", "templates/base.html", "cdn.tailwindcss.com", False),
    ("iPhone HEIC photos accepted", "recognition.py", "HEIF_EXTS", True),
    ("HEIC fallback decoder for scans", "recognition.py", "def decode_with_pillow", True),
    ("upload form offers HEIC", "templates/index.html", ".heic", True),
    ("pillow-heif in requirements", "requirements.txt", "pillow-heif", True),
]


def main() -> int:
    print()
    print("  FaceID Attendance - version check")
    print("  " + "=" * 52)
    print(f"  Folder: {ROOT}")
    print()

    missing_files: list[str] = []
    failures: list[str] = []

    for label, rel, needle, want in CHECKS:
        content = read(rel)
        if content is None:
            missing_files.append(rel)
            print(f"  [MISSING FILE] {label}")
            print(f"                 {rel} does not exist")
            failures.append(label)
            continue

        found = True if needle == "" else (needle in content)
        ok = found is want
        print(f"  [{'OK  ' if ok else 'FAIL'}] {label}")
        if not ok:
            failures.append(label)

    print()
    print("  " + "=" * 52)

    if not failures:
        print("  VERDICT: new build. Multi-photo attendance IS present.")
        print()
        print("  If the browser still shows a single-photo page, it is caching.")
        print("  Stop the server, then hard-reload:")
        print("      Windows / Linux : Ctrl + Shift + R")
        print("      macOS           : Cmd + Shift + R")
        print("  Or open a private window. Confirm the upload area reads")
        print('  "Drop one or more photos of the class here".')
        return 0

    print(f"  VERDICT: OLD BUILD - {len(failures)} check(s) failed.")
    print("  This folder does NOT have the multi-photo feature.")
    print()
    if missing_files:
        print("  Files not found here: " + ", ".join(sorted(set(missing_files))))
        print("  You may also be running doctor.py from the wrong folder.")
        print()
    print("  Fix: unzip faceid-attendance.zip and copy these over this folder:")
    print("      app.py  recognition.py  db.py  excel_report.py")
    print("      templates/   static/")
    print("  Then restart the server and hard-reload the browser.")
    print()
    print("  The GitHub repo (Omgupta78/minor-project) also holds this build,")
    print("  so `git pull` is another way to get the multi-photo code.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
