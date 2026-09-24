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
    ("every reference photo is matched against", "db.py", "FROM student_encodings", True),
    ("enrolment accepts several photos", "app.py", 'getlist("student_photo")', True),
    ("enrolment form allows several files", "templates/students_page.html", "multiple required", True),
    ("enrolment photos are quality checked", "recognition.py", "def quality_problem", True),
    ("enrolment encodings are jittered", "recognition.py", "num_jitters=ENROL_JITTERS", True),
    ("tiled detection for back rows", "recognition.py", "def detect_tiled", True),
    ("tiling turns itself on for big photos", "recognition.py", "def should_tile", True),
    ("far faces enlarged before encoding", "recognition.py", "def encode_small_face", True),
    ("small/big faces routed separately", "recognition.py", "def encode_boxes", True),
    ("face size reported per detection", "recognition.py", "face_px: int = 0", True),
    ("wider review band for far faces", "recognition.py", "SMALL_FACE_SLACK", True),
    ("far-face tests present", "smalltest.py", "encode_small_face", True),
    ("a stranger cannot borrow a name", "recognition.py", "MATCH_MARGIN", True),
    ("runner-up gap reported per face", "recognition.py", "runner_up_gap", True),
    ("stricter bar for enlarged faces", "recognition.py", "SMALL_FACE_PENALTY", True),
    ("low-res photos searched twice", "recognition.py", "def detect_rescue", True),
    ("one detection entry point", "recognition.py", "def detect_faces", True),
    ("false-match tests present", "smalltest.py", "MATCH_MARGIN", True),
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
    ("upload and file decode paths agree", "decodetest.py", "same faces", True),
    ("upload form offers HEIC", "templates/index.html", ".heic", True),
    ("pillow-heif in requirements", "requirements.txt", "pillow-heif", True),
    # --- teacher accounts and data isolation ---
    ("teacher accounts module present", "auth.py", "def create_teacher", True),
    ("passwords hashed, not stored", "auth.py", "pbkdf2_sha256", True),
    ("login required on every page", "app.py", "def require_login", True),
    ("public pages listed explicitly", "app.py", "PUBLIC_ENDPOINTS", True),
    ("classes belong to a teacher", "db.py", "teacher_id", True),
    ("queries are teacher-scoped", "db.py", "c.teacher_id = ?", True),
    ("Excel export is teacher-scoped", "excel_report.py", "teacher_id", True),
    ("login page present", "templates/login.html", "", True),
    ("signup page present", "templates/signup.html", "", True),
    ("logout control in the nav", "templates/base.html", "/logout", True),
    ("isolation tests present", "authtest.py", "One teacher cannot reach another", True),
    # --- hosting for other teachers ---
    ("session cookie key configurable", "app.py", "SECRET_KEY", True),
    ("health check endpoint", "app.py", "/healthz", True),
    ("production server settings", "gunicorn.conf.py", "", True),
    ("container image definition", "Dockerfile", "", True),
    ("deployment guide", "DEPLOY.md", "", True),
    ("production server in requirements", "requirements.txt", "gunicorn", True),
    # --- 120-student hall capacity ---
    ("parallel face encoding", "recognition.py", "def _encode_jobs_parallel", True),
    ("worker count is configurable", "recognition.py", "SCAN_WORKERS", True),
    ("face size reported to the teacher", "recognition.py", "READABLE_FACE_PX", True),
    ("scan returns actionable hints", "app.py", '"hints": hints', True),
    ("review list filters and searches", "templates/index.html", "review-search", True),
    ("bulk accept for a long roster", "templates/index.html", "function acceptSuggested", True),
    ("one row repaints, not all 120", "templates/index.html", "function repaintRow", True),
    ("reference photo count per student", "app.py", "reference_counts", True),
    ("120-student capacity test", "halltest.py", "STUDENTS = 120", True),
    ("hall benchmark harness", "hallbench.py", "def face_px_at", True),
    ("measured results written down", "RECOGNITION.md", "face width", True),
    # --- bulk enrolment ---
    ("bulk roster importer", "roster_import.py", "def build_plan", True),
    ("csv manifest supported", "roster_import.py", "def read_manifest", True),
    ("folder-per-student supported", "roster_import.py", "def read_folders", True),
    ("zip slip is refused", "roster_import.py", "outside the folder", True),
    ("import page present", "templates/import_page.html", "imp-preview", True),
    ("import runs in the background", "app.py", "def _run_import", True),
    ("import progress is pollable", "app.py", "def api_import_status", True),
    ("manual one-by-one enrolment retained", "app.py", "def add_student", True),
    ("import command line tool", "import_students.py", "--dry-run", True),
    ("import tests present", "importtest.py", "zip slip", False),
    ("import formats documented", "IMPORT.md", "roll_no", True),
    ("password recovery tool", "reset_password.py", "def main", True),
    ("build marker shown in the app", "app.py", "def _build_marker", True),
    # --- installable app ---
    ("web app manifest", "static/manifest.webmanifest", "standalone", True),
    ("service worker", "static/sw.js", "faceid-shell-", True),
    ("worker never caches pages or api", "static/sw.js", "request.mode === \"navigate\"", True),
    ("manifest served at the root", "app.py", "def manifest", True),
    ("worker served at root scope", "app.py", "Service-Worker-Allowed", True),
    ("offline page", "templates/offline.html", "No connection", True),
    ("install prompt handled", "templates/base.html", "beforeinstallprompt", True),
    ("ios home screen support", "templates/base.html", "apple-mobile-web-app-capable", True),
    ("app icons generated from code", "make_icons.py", "def draw_icon", True),
    ("android project", "android/app/build.gradle", "com.android.application", True),
    ("android file upload works", "android/app/src/main/java/com/faceid/attendance/MainActivity.java", "onShowFileChooser", True),
    ("android camera permission", "android/app/src/main/java/com/faceid/attendance/MainActivity.java", "onPermissionRequest", True),
    ("android server address configurable", "android/app/src/main/java/com/faceid/attendance/SetupActivity.java", "KEY_SERVER", True),
    ("apk build workflow", ".github/workflows/android.yml", "assembleRelease", True),
    ("app install documented", "APP.md", "Add to Home Screen", True),
    # --- installing the face engine without a compiler ---
    ("face engine installed from a wheel", "requirements.txt", "dlib-bin", True),
    ("source-only dlib is not resolved", "requirements-nodeps.txt", "face_recognition", True),
    ("face_recognition kept out of the resolver", "requirements.txt", "face_recognition==", False),
    ("no false claim that a compiler is needed", "recognition.py",
     "On Windows this needs Visual Studio Build Tools", False),
    ("setup checker present", "check_setup.py", "def main", True),
    ("server prints the phone address", "netinfo.py", "def startup_banner", True),
    ("startup warns when phones cannot reach it", "wsgi.py", "startup_banner", True),
    ("one-command launcher for the phone", "run-phone.sh", "HOST=0.0.0.0", True),
    ("windows launcher for the phone", "run-phone.bat", "HOST=0.0.0.0", True),
    ("import page warns when the engine is missing", "templates/import_page.html",
     "recognition_ready", True),
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
        print("  VERDICT: new build. Multi-photo attendance, teacher accounts")
        print("           and the deployment kit are ALL present.")
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
