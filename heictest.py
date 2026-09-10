"""heictest.py - checks that iPhone HEIC photos can get through the pipeline.

Run:  python heictest.py

Why this exists
---------------
An iPhone saves photos as .heic. Two things used to block them:

1. /add-student rejected the file by extension before ever opening it.
2. /api/scan decoded uploads with OpenCV, which cannot read HEIC at all, so
   the photo was silently listed as "skipped" instead of being scanned.

This suite needs no camera, no dlib and no OpenCV. Where a real HEIC decoder
is unavailable it substitutes a stub, so the *logic* is still verified on any
machine. If pillow-heif is installed, a genuine HEIC file is encoded and
decoded end to end.
"""
import io
import sys
import types
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import numpy as np
from PIL import Image

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  OK   {label}")
    else:
        print(f"  FAIL {label}   {detail}")
        failures.append(label)


# OpenCV is not installed here (and is not needed for this test). Stub it so
# imports succeed and imdecode reports "I cannot read this", exactly as it
# behaves when handed real HEIC bytes.
if "cv2" not in sys.modules:
    try:
        import cv2  # noqa: F401
    except Exception:
        stub = types.ModuleType("cv2")
        stub.IMREAD_COLOR = 1
        stub.COLOR_BGR2RGB = 4
        stub.imdecode = lambda *a, **k: None      # mimics HEIC being unreadable
        stub.cvtColor = lambda frame, code: frame[:, :, ::-1]
        sys.modules["cv2"] = stub
        print("  ..   OpenCV absent: using a stub that rejects the bytes")

import recognition  # noqa: E402

print("\n[1] extensions accepted by the pipeline")
check(".heic is a known image extension", ".heic" in recognition.IMAGE_EXTS)
check(".heif is a known image extension", ".heif" in recognition.IMAGE_EXTS)
check("ordinary formats still accepted",
      {".jpg", ".png", ".webp"} <= recognition.IMAGE_EXTS)

print("\n[2] the upload form and the scanner agree")
# app.py needs Flask, so read the source instead of importing it.
app_src = (BASE_DIR / "app.py").read_text(encoding="utf-8")
check("ALLOWED_EXTS is derived from recognition.IMAGE_EXTS",
      "ALLOWED_EXTS = set(recognition.IMAGE_EXTS)" in app_src,
      "a hardcoded second list is what rejected .heic")
check("a missing pillow-heif gives an install hint",
      "pip install pillow-heif" in app_src)
check("enrolment applies EXIF rotation", "exif_transpose" in app_src)

print("\n[3] fallback decoding when OpenCV refuses the bytes")
buf = io.BytesIO()
Image.new("RGB", (64, 48), (200, 60, 60)).save(buf, format="PNG")
png_bytes = buf.getvalue()

decoded = recognition.decode_image_bytes(png_bytes)
check("decode_image_bytes falls back to Pillow", decoded is not None,
      "OpenCV returned None and nothing caught it")
if decoded is not None:
    check("decoded shape is (h, w, 3) RGB", decoded.shape == (48, 64, 3),
          str(decoded.shape))
    check("colour channels are RGB, not BGR",
          tuple(int(v) for v in decoded[0][0]) == (200, 60, 60),
          str(decoded[0][0]))

check("garbage bytes still return None",
      recognition.decode_image_bytes(b"this is not an image") is None)
check("empty upload returns None", recognition.decode_image_bytes(b"") is None)

print("\n[4] sideways phone photos are straightened")
# EXIF orientation 6 = "rotate 90 CW on display". Without exif_transpose the
# faces come out on their side and the detector misses most of the class.
tall = Image.new("RGB", (40, 20), (10, 120, 200))
exif = tall.getexif()
exif[274] = 6  # 274 = Orientation
rot = io.BytesIO()
tall.save(rot, format="JPEG", exif=exif)
straight = recognition.decode_with_pillow(rot.getvalue())
check("EXIF orientation is applied",
      straight is not None and straight.shape[:2] == (40, 20),
      f"got {None if straight is None else straight.shape[:2]}, wanted (40, 20)")

print("\n[5] pillow-heif availability")
heif_ok = recognition.register_heif()
check("register_heif() is callable and idempotent",
      recognition.register_heif() == heif_ok)
if heif_ok:
    import pillow_heif  # noqa: F401

    real = io.BytesIO()
    Image.new("RGB", (32, 32), (12, 200, 90)).save(real, format="HEIF")
    out = recognition.decode_image_bytes(real.getvalue())
    check("a real HEIC file decodes", out is not None and out.shape == (32, 32, 3))
else:
    print("  ..   pillow-heif not installed here, so the real-HEIC decode is")
    print("       skipped. It ships in requirements.txt and run.sh/run.bat")
    print("       install it, so HEIC works on your machine.")

print()
if failures:
    print(f"{len(failures)} CHECK(S) FAILED: " + ", ".join(failures))
    sys.exit(1)
print("ALL HEIC CHECKS PASSED")
