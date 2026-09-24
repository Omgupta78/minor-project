"""
check_setup.py - tell me why this machine cannot run the app.

Run it when something says a package is missing:

    python check_setup.py

It reports what is installed, what is not, and the exact command to fix it. It
changes nothing and needs no arguments.

doctor.py answers a different question -- "is this folder the new version of
the code" -- by reading files. This one asks "can this Python actually run it"
by trying to import things.
"""
from __future__ import annotations

import importlib
import platform
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent

# (import name, why it is needed, which requirements file installs it)
CHECKS = [
    ("flask", "the web server", "requirements.txt"),
    ("werkzeug", "request handling", "requirements.txt"),
    ("numpy", "face encodings are arrays", "requirements.txt"),
    ("PIL", "reading and resizing photos", "requirements.txt"),
    ("pillow_heif", "iPhone HEIC photos", "requirements.txt"),
    ("cv2", "image decoding fallback", "requirements.txt"),
    ("openpyxl", "the Excel report", "requirements.txt"),
    ("dlib", "the face recognition engine", "requirements.txt (as dlib-bin)"),
    ("face_recognition", "face detection and encoding", "requirements-nodeps.txt"),
]

# dlib-bin publishes wheels for these. Outside the range there is no wheel for
# any platform and pip would have to compile from source, which is the thing
# this project is arranged to avoid.
SUPPORTED = ((3, 10), (3, 14))


def main() -> int:
    print()
    print("  FaceID Attendance - setup check")
    print("  " + "=" * 52)
    print(f"  Python   : {sys.version.split()[0]} ({platform.python_implementation()})")
    print(f"  Platform : {platform.system()} {platform.machine()}")
    print(f"  Running  : {sys.executable}")
    print(f"  Folder   : {BASE}")
    print()

    problems: list[str] = []

    version = sys.version_info[:2]
    if not (SUPPORTED[0] <= version <= SUPPORTED[1]):
        low = ".".join(str(n) for n in SUPPORTED[0])
        high = ".".join(str(n) for n in SUPPORTED[1])
        print(f"  [FAIL] Python {version[0]}.{version[1]} has no pre-built face engine")
        problems.append(
            f"Python {version[0]}.{version[1]} is outside {low}-{high}. There is no "
            f"dlib-bin wheel for it, so the engine cannot be installed without a "
            f"C++ compiler. Install Python {high} and make the virtual environment "
            f"again."
        )
    else:
        print(f"  [ok  ] Python {version[0]}.{version[1]} has a pre-built face engine")

    missing: list[tuple[str, str]] = []
    for module, why, where in CHECKS:
        try:
            importlib.import_module(module)
        except Exception as exc:
            print(f"  [FAIL] {module:<18} {why}")
            print(f"         {type(exc).__name__}: {str(exc)[:90]}")
            missing.append((module, where))
        else:
            print(f"  [ok  ] {module:<18} {why}")

    # The one mistake that looks like everything else is broken.
    in_venv = sys.prefix != sys.base_prefix
    venv = BASE / ".venv"
    if not in_venv and venv.exists():
        print()
        print("  [WARN] this Python is not the project's virtual environment")
        problems.append(
            "You are running the system Python, but the project installed its "
            f"packages into {venv}. Activate it first:\n"
            "      Windows : .venv\\\\Scripts\\\\activate\n"
            "      Mac/Linux: source .venv/bin/activate\n"
            "  or just use ./run.sh (run.bat on Windows), which does it for you."
        )

    print()
    print("  " + "=" * 52)

    if not missing and not problems:
        print("  Everything needed is installed. The app will run, scanning included.")
        print()
        return 0

    if missing:
        needs_nodeps = any(w.startswith("requirements-nodeps") for _m, w in missing)
        print("  Missing: " + ", ".join(m for m, _w in missing))
        print()
        print("  Install with BOTH of these, in this order:")
        print("      pip install -r requirements.txt")
        print("      pip install --no-deps -r requirements-nodeps.txt")
        print()
        if needs_nodeps or any(m == "dlib" for m, _w in missing):
            print("  The second line is not optional. face_recognition asks for the")
            print("  'dlib' package, which PyPI ships as source only -- so a normal")
            print("  install tries to compile C++ and fails. --no-deps lets it use")
            print("  dlib-bin, the pre-built wheel, instead.")
            print()
            print("  You do NOT need Visual Studio, CMake or any compiler.")
            print()

    for problem in problems:
        print("  " + problem.replace("\n", "\n  "))
        print()

    print("  Everything except face scanning works without the engine:")
    print("  classes, students, records and the Excel report are all fine.")
    print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
