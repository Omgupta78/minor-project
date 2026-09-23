"""The two image paths must agree, or a scan silently loses most of the class.

A photo reaches the recogniser two ways:

  * enrolment calls load_image(), which goes through Pillow by way of
    face_recognition.load_image_file;
  * a scan calls decode_image_bytes() on the bytes of the upload.

Those used to be different decoders, and that was not a tidiness problem. When
cv2.imdecode is the first image decode to run in a process, dlib's HOG
detector is crippled for the rest of that process's life -- on a 4000x3000
photograph of 120 students the identical array yielded 7 faces instead of 121,
and 0 on the next call. Enrolment, which never touched OpenCV, looked perfect
throughout, so nothing in the test suite noticed that every real scan of a
large room was losing most of the students in it.

This file is the guard. It builds a picture, runs it through both paths, and
insists they agree -- on the pixels, and, when dlib is installed, on the faces
actually found. It needs no dlib to run: without it the pixel checks still
catch a decoder swap, and the detection check reports that it was skipped.
"""
from __future__ import annotations

import io
import sys

import numpy as np
from PIL import Image, ImageDraw

import recognition

CHECKS = 0
FAILS = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global CHECKS, FAILS
    CHECKS += 1
    if condition:
        print(f"  [ok]   {label}")
    else:
        FAILS += 1
        print(f"  [FAIL] {label} {detail}")


def sample_photo(width=900, height=600) -> bytes:
    """A deterministic picture with enough structure to survive JPEG."""
    image = Image.new("RGB", (width, height), (36, 40, 48))
    draw = ImageDraw.Draw(image)
    for i in range(24):
        x = 20 + (i % 8) * 108
        y = 30 + (i // 8) * 190
        draw.ellipse([x, y, x + 88, y + 118], fill=(210 - i * 4, 180, 150 + i * 2))
        draw.rectangle([x + 20, y + 40, x + 34, y + 54], fill=(30, 30, 30))
        draw.rectangle([x + 54, y + 40, x + 68, y + 54], fill=(30, 30, 30))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=92)
    return buffer.getvalue()


print("\n1. both decoders return the same pixels")
raw = sample_photo()
by_pillow = recognition.decode_with_pillow(raw)
by_upload = recognition.decode_image_bytes(raw)

check("decode_image_bytes returns an image", by_upload is not None)
check(
    "it is RGB, 8-bit, with the expected shape",
    by_upload is not None
    and by_upload.dtype == np.uint8
    and by_upload.shape == (600, 900, 3),
    "" if by_upload is None else f"{by_upload.dtype} {by_upload.shape}",
)
check(
    "the upload path and the Pillow path agree pixel for pixel",
    by_upload is not None and np.array_equal(by_upload, by_pillow),
)
check(
    "channels are in RGB order, not OpenCV's BGR",
    # the backdrop is (36, 40, 48): blue is the largest channel. Reversed, red
    # would be. This is the check that catches a missing colour conversion.
    by_upload is not None and by_upload[5, 5, 2] > by_upload[5, 5, 0],
    "" if by_upload is None else str(by_upload[5, 5]),
)
check("a non-image is rejected rather than guessed at", recognition.decode_image_bytes(b"not an image") is None)
check("empty bytes are rejected", recognition.decode_image_bytes(b"") is None)


print("\n2. Pillow is the primary decoder, OpenCV only the fallback")
# Reading the source is crude, but the ordering is the whole fix and a future
# edit that swaps it back would otherwise be caught by nothing until a teacher
# scanned a real hall.
source = recognition.decode_image_bytes.__doc__ or ""
check(
    "the ordering is documented where someone would change it",
    "Pillow first" in source,
    "decode_image_bytes lost the comment explaining why the order matters",
)
import inspect

full = inspect.getsource(recognition.decode_image_bytes)
# The docstring explains the bug and names cv2.imdecode while doing so, so
# compare the statements rather than the whole source.
body = full[full.index('"""', full.index('"""') + 3) + 3:]
check(
    "Pillow is tried before OpenCV in the code itself",
    body.index("decode_with_pillow(data)") < body.index("cv2.imdecode"),
)


print("\n3. the two paths find the same faces")
try:
    recognition.ensure_available()
except recognition.RecognitionUnavailable:
    print("  --     dlib is not installed, skipping the detection comparison")
else:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "sample.jpg"
        path.write_bytes(raw)
        # Order matters: decode the upload FIRST, in a process that has not yet
        # decoded anything, which is exactly the situation a scan is in.
        upload_faces = recognition.detect_faces(recognition.decode_image_bytes(raw))
        file_faces = recognition.detect_faces(recognition.load_image(str(path)))

    check(
        "an uploaded photo detects the same number of faces as the same file on disk",
        len(upload_faces) == len(file_faces),
        f"upload {len(upload_faces)} vs file {len(file_faces)}",
    )
    check(
        "and detection does not degrade on a second call in the same process",
        len(recognition.detect_faces(recognition.decode_image_bytes(raw)))
        == len(upload_faces),
        "the second scan in a worker found a different number of faces",
    )

print(f"\n{CHECKS - FAILS}/{CHECKS} checks passed.")
if FAILS:
    print(f"{FAILS} FAILED")
    sys.exit(1)
print("Both image paths agree.")
