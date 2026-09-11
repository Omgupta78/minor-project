"""Tests for the accuracy work: multi-photo enrolment, photo quality gate,
tiled detection and the accuracy metrics.

Runs without dlib, OpenCV or Flask installed. The face_recognition calls are
stubbed so the logic around them can be checked on any machine:

    python qualitytest.py
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

import numpy as np

import accuracy
import db
import recognition

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'OK  ' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n== {title}")


# --------------------------------------------------------------- stub of dlib
class StubFR:
    """Stands in for the face_recognition module."""

    def __init__(self, boxes=None, encoding=None):
        self.boxes = boxes if boxes is not None else [(10, 190, 190, 10)]
        self.encoding = encoding if encoding is not None else np.zeros(128)
        self.jitters_seen: list = []
        self.crops_seen: list = []

    def face_locations(self, image, number_of_times_to_upsample=1, model="hog"):
        self.crops_seen.append(np.asarray(image).shape[:2])
        height, width = np.asarray(image).shape[:2]
        # Only return boxes that fit inside the image handed to us, so a tile
        # that is too small reports nothing.
        return [b for b in self.boxes if b[2] <= height and b[1] <= width]

    def face_encodings(self, image, boxes, num_jitters=1):
        self.jitters_seen.append(num_jitters)
        return [self.encoding for _ in boxes]

    def face_distance(self, matrix, encoding):
        return np.linalg.norm(np.asarray(matrix) - np.asarray(encoding), axis=1)


def with_stub(stub):
    recognition._fr = lambda: stub  # type: ignore[assignment]
    return stub


# ------------------------------------------------------------------- quality
section("photo quality scoring")

rng = np.random.default_rng(7)
sharp = rng.integers(0, 255, size=(120, 120, 3)).astype(np.uint8)
# A smooth gradient is the blurriest possible image with the same brightness.
gradient = np.tile(np.linspace(0, 255, 120, dtype=np.uint8), (120, 1))
blurry = np.dstack([gradient] * 3)

check(
    "noise scores sharper than a smooth gradient",
    recognition.sharpness_of(sharp) > recognition.sharpness_of(blurry) * 10,
    f"{recognition.sharpness_of(sharp):.1f} vs {recognition.sharpness_of(blurry):.1f}",
)
check("a blurred image falls under the threshold", recognition.sharpness_of(blurry) < recognition.MIN_SHARPNESS)
check("a tiny crop cannot crash the blur score", recognition.sharpness_of(np.zeros((2, 2, 3))) == 0.0)

metrics = recognition.assess_face(sharp, (10, 110, 110, 10))
check("assess_face measures the box width", metrics["face_px"] == 100, str(metrics))
check("assess_face reports brightness", 0 < metrics["brightness"] < 256, str(metrics))
check(
    "a box outside the image does not crash",
    recognition.assess_face(sharp, (500, 600, 700, 500))["face_px"] == 0,
)

check(
    "a small face is rejected",
    "pixels across" in (recognition.quality_problem({"face_px": 40, "sharpness": 900, "brightness": 120}) or ""),
)
check(
    "a blurry face is rejected",
    "blurry" in (recognition.quality_problem({"face_px": 200, "sharpness": 3, "brightness": 120}) or ""),
)
check(
    "a dark face is rejected",
    "too dark" in (recognition.quality_problem({"face_px": 200, "sharpness": 900, "brightness": 10}) or ""),
)
check(
    "an over-exposed face is rejected",
    "over-exposed" in (recognition.quality_problem({"face_px": 200, "sharpness": 900, "brightness": 250}) or ""),
)
check(
    "a good face passes",
    recognition.quality_problem({"face_px": 200, "sharpness": 900, "brightness": 120}) is None,
)


# ------------------------------------------------------ enrolment encoding
section("enrolment encoding")

stub = with_stub(StubFR(boxes=[(10, 190, 190, 10)]))
encoding, report = recognition.encode_enrolment(sharp * 0 + sharp)  # 120x120 noise
check("a face larger than the frame is not detected", encoding is None and report["faces"] == 0, str(report))

big = rng.integers(0, 255, size=(400, 400, 3)).astype(np.uint8)
stub = with_stub(StubFR(boxes=[(10, 190, 190, 10)], encoding=np.ones(128)))
encoding, report = recognition.encode_enrolment(big)
check("a good enrolment photo is encoded", encoding is not None, str(report))
check("the quality report is attached", report["face_px"] == 180 and report["problem"] is None, str(report))
check(
    "enrolment uses jitter for a cleaner reference vector",
    stub.jitters_seen == [recognition.ENROL_JITTERS] and recognition.ENROL_JITTERS > 1,
    str(stub.jitters_seen),
)

stub = with_stub(StubFR(boxes=[(10, 50, 50, 10)]))  # 40px face
encoding, report = recognition.encode_enrolment(big)
check("a too-small face is refused with a reason", encoding is None and "pixels across" in report["problem"], str(report))
check("a refused photo is never encoded", stub.jitters_seen == [], str(stub.jitters_seen))

stub = with_stub(StubFR(boxes=[(0, 100, 100, 0), (0, 400, 400, 0)]))
encoding, report = recognition.encode_enrolment(big)
check("the largest face wins when a photo holds two", report["face_px"] == 400, str(report))


# ------------------------------------------------------- tiled detection
section("tiled detection")

windows = recognition.tile_windows(800, 600, tile=1200, overlap=240)
check("a small photo is one window", windows == [(0, 0, 600, 800)], str(windows))

windows = recognition.tile_windows(2000, 3000, tile=1200, overlap=240)
check("a large photo is split into tiles", len(windows) > 1, str(len(windows)))
check(
    "every tile stays inside the photo",
    all(x >= 0 and y >= 0 and x + w <= 3000 and y + h <= 2000 for x, y, w, h in windows),
)
check(
    "the tiles reach the far edges",
    max(x + w for x, y, w, h in windows) == 3000 and max(y + h for x, y, w, h in windows) == 2000,
)
check("tiles overlap so edge faces are not lost", sorted({x for x, y, w, h in windows})[1] < 1200)

box = (100, 200, 200, 100)
# The same face seen from the neighbouring tile: heavily overlapping, and a
# little larger because that tile saw more of it.
near_duplicate = (95, 210, 210, 95)
far = (900, 1000, 1000, 900)
check("the same face seen twice overlaps heavily", recognition._overlap_ratio(box, near_duplicate) > 0.8)
check("two different faces do not overlap", recognition._overlap_ratio(box, far) == 0.0)
merged = recognition.merge_boxes([box, near_duplicate, far])
check("duplicate detections are merged", len(merged) == 2, str(merged))
check("merged boxes come back in reading order", merged == sorted(merged, key=lambda b: (b[0], b[3])), str(merged))
check("the larger view of a face is the one kept", merged[0] == near_duplicate, str(merged))

# A face at (1150..1250) straddles the 1200px tile boundary, so it is only
# found because the tiles overlap.
stub = with_stub(StubFR(boxes=[(50, 150, 150, 50)]))
boxes = recognition.detect_tiled(np.zeros((2000, 3000, 3), dtype=np.uint8), tile=1200, overlap=240)
check("tiled detection returns whole-image coordinates", all(b[1] <= 3000 and b[2] <= 2000 for b in boxes), str(boxes[:3]))
check("every tile was actually searched", len(stub.crops_seen) == len(windows), f"{len(stub.crops_seen)} vs {len(windows)}")
check("overlapping tiles do not produce duplicate faces", len(boxes) == len(recognition.merge_boxes(boxes)), str(len(boxes)))


# ------------------------------------------- several reference photos per student
section("several reference photos per student")

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "quality.db"
    db.init_db(path)
    with db.session_scope(path) as conn:
        class_id = db.create_class(conn, "CSE-A", "Minor Project")
        first = np.zeros(128)
        first[0] = 1.0
        student_id = db.create_student(conn, "CS-1", "Asha", class_id, "a.jpg", first)

        side = np.zeros(128)
        side[1] = 1.0
        other = np.zeros(128)
        other[2] = 1.0
        db.add_student_encoding(conn, student_id, side, "a_2.jpg")
        db.add_student_encoding(conn, student_id, other, "a_3.jpg")

        ids, labels, matrix = db.known_faces(conn, class_id)
        check("all three photos are in the match matrix", matrix.shape == (3, 128), str(matrix.shape))
        check("every row points at the same student", set(ids) == {student_id}, str(ids))
        check("every row carries the student's name", {label["name"] for label in labels} == {"Asha"}, str(labels))
        check("the photo count is reported for the roster", db.encoding_counts(conn, class_id)[student_id] == 3)

        # A face that looks like the side-on photo still resolves to Asha,
        # which is the whole point of storing more than one reference.
        distances = np.linalg.norm(matrix - side, axis=1)
        best = int(np.argmin(distances))
        check("a side-on face matches via the extra photo", labels[best]["id"] == student_id and distances[best] == 0.0)

        db.clear_student_encodings(conn, student_id)
        _ids, _labels, matrix = db.known_faces(conn, class_id)
        check("clearing the extras leaves the primary encoding", matrix.shape == (1, 128), str(matrix.shape))

        # A student enrolled before this feature existed has no primary
        # encoding; the first photo added has to fill that slot.
        blank_id = db.create_student(conn, "CS-2", "Ravi", class_id, None, None)
        db.add_student_encoding(conn, blank_id, other)
        row = conn.execute("SELECT encoding FROM students WHERE id = ?", (blank_id,)).fetchone()
        check("the first photo of an old student becomes the primary", row["encoding"] is not None)
        extras = conn.execute(
            "SELECT COUNT(*) AS n FROM student_encodings WHERE student_id = ?", (blank_id,)
        ).fetchone()["n"]
        check("it is not stored twice", extras == 0, str(extras))

    # An old database with no student_encodings table must still load.
    legacy = Path(tmp) / "legacy.db"
    db.init_db(legacy)
    with sqlite3.connect(legacy) as raw:
        raw.execute("DROP TABLE student_encodings")
    with db.session_scope(legacy) as conn:
        db.create_student(conn, "CS-9", "Old", None, "o.jpg", np.ones(128))
        _ids, _labels, matrix = db.known_faces(conn)
        check("a database from an older build still loads", matrix.shape == (1, 128), str(matrix.shape))


# ------------------------------------------------------------ accuracy maths
section("accuracy metrics")

check("a correct name is a hit", accuracy.classify("CS-1", "CS-1") == "hit")
check("the wrong name is caught", accuracy.classify("CS-1", "CS-2") == "wrong_name")
check("naming a stranger is a false alarm", accuracy.classify(None, "CS-2") == "false_alarm")
check("failing to name a student is a miss", accuracy.classify("CS-1", None) == "miss")
check("ignoring a stranger is correct", accuracy.classify(None, None) == "correct_pass")

metrics = accuracy.evaluate(
    [
        {"truth": "CS-1", "predicted": "CS-1"},
        {"truth": "CS-2", "predicted": "CS-2"},
        {"truth": "CS-3", "predicted": None},
        {"truth": "CS-4", "predicted": "CS-5"},
        {"truth": None, "predicted": "CS-6"},
        {"truth": None, "predicted": None},
    ]
)
# 2 hits, 2 false positives (one wrong name + one false alarm),
# 2 false negatives (one miss + the same wrong name).
check("precision is computed correctly", metrics["precision"] == 0.5, str(metrics))
check("recall is computed correctly", metrics["recall"] == 0.5, str(metrics))
check("F1 is computed correctly", metrics["f1"] == 0.5, str(metrics))
check("a wrong name counts against both sides", metrics["false_positives"] == 2 and metrics["false_negatives"] == 2, str(metrics))
check("empty input cannot divide by zero", accuracy.evaluate([])["precision"] == 0.0)

samples = [
    {"truth": "CS-1", "nearest": "CS-1", "distance": 0.31},
    {"truth": "CS-2", "nearest": "CS-2", "distance": 0.55},
    {"truth": None, "nearest": "CS-3", "distance": 0.66},
    {"truth": "CS-4", "nearest": None, "distance": None},
]
tight = accuracy.evaluate(accuracy.apply_threshold(samples, 0.40))
loose = accuracy.evaluate(accuracy.apply_threshold(samples, 0.60))
wide = accuracy.evaluate(accuracy.apply_threshold(samples, 0.70))
check("a tighter threshold finds fewer students", tight["true_positives"] == 1 and loose["true_positives"] == 2)
check("a looser threshold lets strangers in", wide["false_positives"] == 1 and loose["false_positives"] == 0, str(wide))
check("an undetected face stays a miss at any threshold", wide["miss"] == 1, str(wide))

rows = accuracy.sweep(samples)
check("the sweep covers 0.35 to 0.70", rows[0]["threshold"] == 0.35 and rows[-1]["threshold"] == 0.7, str(len(rows)))
check("recall never falls as the threshold grows", all(rows[i]["recall"] <= rows[i + 1]["recall"] for i in range(len(rows) - 1)))
# Several thresholds tie on F1 here, and report() breaks the tie toward the
# tighter one, because a tight threshold is the safer default in a classroom.
best = max(rows, key=lambda r: (r["f1"], -r["threshold"]))
check("the sweep picks the tightest of the best thresholds", best["threshold"] == 0.55, str([(r["threshold"], r["f1"]) for r in rows]))
check("the best threshold beats the default", best["f1"] > rows[6]["f1"], str(best))

lines = accuracy.histogram([0.1, 0.12, 0.9])
check("the histogram bins distances", len(lines) == 12 and "#" in lines[1], str(lines[:2]))
check("an empty histogram is handled", "no distances" in accuracy.histogram([])[0])
check("unknown folder names are recognised", "unknown" in accuracy.UNKNOWN_FOLDERS and "stranger" in accuracy.UNKNOWN_FOLDERS)


print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} CHECK(S) FAILED:")
    for item in FAILURES:
        print(f"  - {item}")
    sys.exit(1)
print("ALL ACCURACY CHECKS PASSED")
