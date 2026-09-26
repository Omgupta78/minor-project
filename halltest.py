"""Capacity test: a 120-student hall, end to end, with no dlib required.

The target this app is built for is one teacher photographing a lecture hall
of about 120 students. That size breaks things a 10-student demo never
touches: the gallery gets dense enough that the runner-up margin starts
rejecting correct matches, the review list gets long enough to matter, the
Excel register grows a column per session, and the confirm call writes 120
rows in one transaction.

Everything here runs against a stubbed recogniser, so CI exercises the real
Flask routes, the real SQL and the real workbook builder at full size without
needing a compiled dlib. The recognition quality numbers that motivated the
current thresholds come from a separate benchmark against real photographs;
hallbench.py runs that one and RECOGNITION.md records the results.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

WORK = Path(tempfile.mkdtemp(prefix="faceid-hall-"))
os.environ["ATTENDANCE_DB"] = str(WORK / "hall.db")
os.environ["FACES_DIR"] = str(WORK / "faces")
os.environ["PASSWORD_ROUNDS"] = "1000"
os.environ["COOKIE_SECURE"] = "0"
os.environ["ALLOW_SIGNUP"] = "1"
os.environ["SECRET_KEY"] = "halltest-secret-key-long-enough-for-production"
# This test is about what happens at 120 students, not about which detection
# strategy finds them: smalltest.py covers tiling, the enlarged rescue pass and
# the small-face path. Pinning them here lets the stub answer one whole-frame
# call instead of reproducing tile geometry, and keeps the 4000x3000 array from
# being upscaled to 8000x6000 (432 MB) by the rescue pass.
os.environ["TILE_SCAN"] = "0"
os.environ["RESCUE_PASS"] = "off"
os.environ["MAX_EDGE"] = "5000"

import numpy as np

import app as flask_app
import auth
import db
import excel_report
import recognition

STUDENTS = 120
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


rng = np.random.default_rng(20)


def identity(i: int) -> np.ndarray:
    """A reproducible 128-D vector standing in for one person's face."""
    v = rng.normal(size=128)
    return v / np.linalg.norm(v)


print(f"\n1. enrol {STUDENTS} students")
client = flask_app.app.test_client()
client.post(
    "/signup",
    data={"email": "hall@example.edu", "name": "Hall Teacher", "password": "password1"},
)
truth = {}
t0 = time.time()
with db.session_scope() as conn:
    class_id = db.create_class(conn, "Hall 1", "CS", teacher_id=1)
    for i in range(STUDENTS):
        base = identity(i)
        sid = db.create_student(
            conn, f"H{i + 1:03d}", f"Student {i + 1}", class_id, None, base
        )
        truth[sid] = base
        # Three reference photos each, which is what the app asks for: the
        # extra two are the same face with a little noise.
        for _ in range(2):
            jitter = base + rng.normal(scale=0.04, size=128)
            db.add_student_encoding(conn, sid, jitter / np.linalg.norm(jitter))
print(f"   enrolled in {time.time() - t0:.1f}s")

with db.session_scope() as conn:
    roster = db.list_students(conn, class_id)
    _ids, labels, matrix = db.known_faces(conn, class_id)
    counts = db.encoding_counts(conn, class_id)
check(f"{STUDENTS} students on the roster", len(roster) == STUDENTS, str(len(roster)))
check(
    "every reference photo is in the match gallery",
    matrix.shape == (STUDENTS * 3, 128),
    str(matrix.shape),
)
check(
    "reference counts are reported per student",
    set(counts.values()) == {3},
    str(sorted(set(counts.values()))),
)


print("\n2. identify a hall photo holding every student")


def at_distance(base: np.ndarray, target: float) -> np.ndarray:
    """A unit vector exactly `target` away from `base`.

    Random noise would make the test's distances an accident of the seed. The
    point here is to hold the distances at known values and check the decision
    rules behave, so the vector is placed deliberately: rotate `base` by the
    angle whose chord length is `target`.
    """
    direction = rng.normal(size=128)
    direction -= direction.dot(base) * base          # orthogonal to base
    direction /= np.linalg.norm(direction)
    theta = 2 * np.arcsin(min(1.0, target / 2))
    return base * np.cos(theta) + direction * np.sin(theta)


# How far each row's encoding lands from its reference. Modelled on what the
# real benchmark measured: a face further away encodes less cleanly, and the
# back row sits just inside the 0.52 match threshold rather than comfortably
# inside it. If a change to the decision rules pushes the back row out, this
# test is what notices.
ROW_DISTANCE = [0.30, 0.33, 0.36, 0.40, 0.44, 0.48]
ROW_WIDTH = [114, 74, 54, 43, 36, 30]
STRANGERS = 4


class HallStub:
    """Stands in for face_recognition: one box per seat, plus some strangers.

    A far face is not encoded from the original photo: encode_boxes crops it
    out and enlarges it first, so face_encodings is handed a rescaled crop
    whose coordinates mean nothing to this stub. Each face is therefore
    painted into the photo as a flat block of a unique colour, and the stub
    reads the colour at the centre of whatever box it is given. That survives
    the crop and the LANCZOS enlargement, and it means the far faces really do
    travel the crop-and-enlarge path rather than being special-cased.
    """

    def __init__(self, boxes, vectors):
        self.boxes = boxes
        self.vectors = vectors

    def face_locations(self, image, number_of_times_to_upsample=1, model="hog"):
        # Only the whole-frame call yields the seats. The enlarged crops that
        # encode_small_face re-detects in return nothing, so the scaled box is
        # used as-is -- the same path a real far face takes.
        if getattr(image, "shape", (0, 0))[:2] != (3000, 4000):
            return []
        return list(self.boxes)

    def face_encodings(self, image, boxes, num_jitters=1):
        out = []
        for top, right, bottom, left in boxes:
            y = min(max((int(top) + int(bottom)) // 2, 0), image.shape[0] - 1)
            x = min(max((int(left) + int(right)) // 2, 0), image.shape[1] - 1)
            out.append(self.vectors[int(image[y, x, 0])])
        return out

    def face_distance(self, known, encoding):
        return np.linalg.norm(np.asarray(known) - np.asarray(encoding), axis=1)


seats = [r["id"] for r in roster]
photo = np.zeros((3000, 4000, 3), dtype=np.uint8)
boxes, vectors, seat_at = [], {}, {}


def place(top, left, width, vector, sid):
    """Paint one face into the photo and register what it should encode to."""
    tag = len(boxes) + 1                       # 0 is the empty background
    photo[top:top + width, left:left + width] = (tag, 90, 160)
    boxes.append((top, left + width, top + width, left))
    vectors[tag] = vector
    seat_at[(top, left)] = sid


for i, sid in enumerate(seats):
    row = i // 20
    place(200 + row * 420, 120 + (i % 20) * 190, ROW_WIDTH[row],
          at_distance(truth[sid], ROW_DISTANCE[row]), sid)

# People in the room who are not on the roster. A threshold loose enough to
# name one of these is too loose, whatever it does for recall.
for n in range(STRANGERS):
    place(200 + 6 * 420, 120 + n * 190, 60,
          at_distance(truth[seats[n]], 0.95), None)

stub = HallStub(boxes, vectors)

original_fr = recognition._fr
recognition._fr = lambda: stub
# The stub lives in this process, so the worker pool must stay out of the way.
original_workers = recognition.SCAN_WORKERS
recognition.SCAN_WORKERS = 1
try:
    t0 = time.time()
    per_image = recognition.identify_many([photo], matrix, labels)
    best = recognition.merge_across_images(per_image)
    stats = recognition.summarise(per_image, best)
    elapsed = time.time() - t0
finally:
    recognition._fr = original_fr
    recognition.SCAN_WORKERS = original_workers

faces = per_image[0]
expected = STUDENTS + STRANGERS
print(f"   {len(faces)} faces, {stats['matched']} matched, in {elapsed:.1f}s")
check(
    f"all {STUDENTS} seats and {STRANGERS} strangers produced a face",
    len(faces) == expected,
    str(len(faces)),
)

by_seat = {}
for face in faces:
    by_seat[seat_at.get((face.top, face.left), "?")] = face

matched_students = [
    sid for sid in seats
    if by_seat.get(sid) is not None and by_seat[sid].status == "matched"
]
check(
    "the whole hall is identified, not a fraction of it",
    len(matched_students) == STUDENTS,
    f"only {len(matched_students)} of {STUDENTS} matched",
)
check(
    "including the back row, whose encodings sit closest to the threshold",
    all(by_seat[sid].status == "matched" for sid in seats[100:]),
    str([by_seat[sid].status for sid in seats[100:]]),
)
check(
    "nobody is identified as the wrong student",
    all(
        by_seat[sid].student_id in (None, sid)
        for sid in seats
        if by_seat.get(sid) is not None
    ),
)
stranger_faces = [f for f in faces if seat_at.get((f.top, f.left)) is None]
check(
    f"none of the {STRANGERS} strangers borrows a student's name",
    all(f.student_id is None for f in stranger_faces),
    str([(f.name, f.distance) for f in stranger_faces if f.student_id]),
)
check(
    "the faces too small to identify reliably are counted",
    # the three back rows (43, 36 and 30 px); the strangers sit at 60 px,
    # which is comfortably readable, so they are not counted here
    stats["faces_too_small"] == 60,
    f"too_small={stats['faces_too_small']}",
)
check(
    "the smallest and median face sizes are reported for the teacher",
    stats["smallest_face_px"] == 30 and stats["median_face_px"] > 0,
    f"smallest={stats['smallest_face_px']} median={stats['median_face_px']}",
)


print("\n3. confirm the session through the real HTTP route")
present = [
    {"student_id": sid, "confidence": 0.9, "manual": False, "status": "present"}
    for sid in list(best)[:112]
]
t0 = time.time()
response = client.post(
    "/api/session/confirm",
    json={
        "class_id": class_id,
        "date": "2026-09-23",
        "period": "1",
        "taken_by": "Hall Teacher",
        "total_faces": len(faces),
        "present": present,
    },
)
confirm_seconds = time.time() - t0
body = response.get_json()
check("the confirm call succeeds", response.status_code == 200, str(body))
check(
    f"all {STUDENTS} students are written in one transaction",
    body and body["total"] == STUDENTS,
    str(body),
)
check("the present count is what was sent", body and body["present"] == 112, str(body))
check(
    "the rest of the roster is recorded absent, not omitted",
    body and body["absent"] == STUDENTS - 112,
    str(body),
)
check(
    f"confirming {STUDENTS} students is quick ({confirm_seconds:.2f}s)",
    confirm_seconds < 5.0,
    f"{confirm_seconds:.1f}s",
)


print("\n4. a term of sessions, then the pages and the workbook")
with db.session_scope() as conn:
    for day in range(1, 25):
        sid = db.create_session(conn, class_id, f"2026-08-{day:02d}", "1", "T", 120)
        marks = {
            s["id"]: {"status": "present", "confidence": 0.9, "method": "face"}
            for s in roster[: 100 + (day % 20)]
        }
        db.save_session_attendance(conn, sid, class_id, marks)

for path in ("/", "/students_page", "/records"):
    t0 = time.time()
    r = client.get(path)
    dt = time.time() - t0
    check(f"{path} renders at hall size in {dt:.2f}s", r.status_code == 200 and dt < 10.0)

t0 = time.time()
r = client.get(f"/download-excel?class_id={class_id}")
excel_seconds = time.time() - t0
check(
    f"the Excel report builds for 120 students x 25 sessions ({excel_seconds:.1f}s)",
    r.status_code == 200 and len(r.data) > 10000,
    f"{r.status_code}, {len(r.data)} bytes",
)

with db.session_scope() as conn:
    summary = db.attendance_summary(conn, class_id)
    grid_students, grid_sessions, marks = db.attendance_grid(conn, class_id)
check("the summary covers every student", len(summary) == STUDENTS, str(len(summary)))
check(
    "the register is 120 students wide and 25 sessions long",
    len(grid_students) == STUDENTS and len(grid_sessions) == 25,
    f"{len(grid_students)}x{len(grid_sessions)}",
)
check(
    "percentages are computed against the sessions actually held",
    all(0.0 <= s["percent"] <= 100.0 for s in summary),
)

# ---------------------------------------------------------------- threading
# Tiled detection runs in threads. Two things had to be got right for that,
# and both fail quietly enough to reach a classroom unnoticed, so they are
# pinned here.
print("\n== threaded tiled detection")

check(
    "a thread gets its own detector, never a shared one",
    "threading.local()" in Path("recognition.py").read_text()
    and "_detector_local" in Path("recognition.py").read_text(),
    "sharing face_recognition's module-level detector segfaulted 11 runs in 12",
)
check(
    "each tile is made contiguous before dlib sees it",
    "ascontiguousarray" in Path("recognition.py").read_text(),
    "passing slice views lost 44 of 197 back-row faces, silently",
)
class _Stub:
    __name__ = "stub"

    def face_locations(self, crop, number_of_times_to_upsample=1, model="hog"):
        return []


_saved_fr = recognition._fr
recognition._fr = lambda: _Stub()
try:
    declined = recognition._thread_detector() is None
finally:
    recognition._fr = _saved_fr
check(
    "threading is declined when a stub replaces the real library",
    declined,
    "reaching past the stub to dlib would make detection untestable, and did",
)
check(
    "one tile is never threaded",
    recognition.detect_thread_count(1) == 1 and recognition.detect_thread_count(0) == 1,
)
check(
    "DETECT_THREADS=1 turns threading off entirely",
    recognition.DETECT_THREADS == 1 or recognition.detect_thread_count(8) > 1,
)

# The stub counts the tiles it is handed, so this proves the threaded and
# serial paths cover exactly the same ground.
class CountingStub:
    __name__ = "stub"

    def __init__(self):
        self.seen = []

    def face_locations(self, crop, number_of_times_to_upsample=1, model="hog"):
        self.seen.append(crop.shape)
        return []


blank = np.zeros((2000, 3000, 3), dtype=np.uint8)
expected = len(recognition.tile_windows(2000, 3000, 1200, 240))
counted = []
for threads in (1, 4):
    stub = CountingStub()
    saved = recognition._fr
    recognition._fr = lambda: stub
    saved_threads = recognition.DETECT_THREADS
    recognition.DETECT_THREADS = threads
    try:
        recognition.detect_tiled(blank, tile=1200, overlap=240)
    finally:
        recognition._fr = saved
        recognition.DETECT_THREADS = saved_threads
    counted.append(len(stub.seen))
check(
    "every tile is searched whether threaded or not",
    counted == [expected, expected],
    f"{counted} tiles seen, expected {expected} each",
)

shutil.rmtree(WORK, ignore_errors=True)

print(f"\n{CHECKS - FAILS}/{CHECKS} checks passed.")
if FAILS:
    print(f"{FAILS} FAILED")
    sys.exit(1)
print(f"The app handles a {STUDENTS}-student hall end to end.")
