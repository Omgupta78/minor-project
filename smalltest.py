"""Tests for far-away / small-face recognition.

Covers the pieces added so the back row of a classroom photo is recognised:
automatic tiling, crop-and-enlarge encoding of small faces, original-photo
coordinates, and the wider review band for distant faces.

Runs without dlib, OpenCV or Flask installed -- face_recognition is stubbed:

    python smalltest.py
"""

from __future__ import annotations

import numpy as np

import recognition

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'OK  ' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n== {title}")


class Stub:
    """Stands in for face_recognition.

    face_locations returns the configured boxes only for the full-size image it
    was built for; any other size (an enlarged crop) either reports the box it
    is told to report, or nothing, so the fallback path can be tested too.
    """

    def __init__(self, shape, boxes, crop_box=None, encoding=None):
        self.shape = tuple(shape)
        self.boxes = list(boxes)
        self.crop_box = crop_box
        self.encoding = np.zeros(128) if encoding is None else np.asarray(encoding)
        self.locate_calls: list[tuple] = []
        self.encode_calls: list[dict] = []

    def face_locations(self, image, number_of_times_to_upsample=1, model="hog"):
        shape = np.asarray(image).shape[:2]
        self.locate_calls.append(shape)
        if shape == self.shape:
            return list(self.boxes)
        return [self.crop_box] if self.crop_box else []

    def face_encodings(self, image, boxes, num_jitters=1):
        self.encode_calls.append(
            {
                "shape": np.asarray(image).shape[:2],
                "boxes": [tuple(int(v) for v in b) for b in boxes],
                "num_jitters": num_jitters,
            }
        )
        return [self.encoding for _ in boxes]

    def face_distance(self, matrix, encoding):
        return np.linalg.norm(np.asarray(matrix) - np.asarray(encoding), axis=1)


def with_stub(stub):
    recognition._fr = lambda: stub  # type: ignore[assignment]
    return stub


# --------------------------------------------------------------- auto tiling
section("should_tile decides when full-resolution tiling is worth it")

mode, forced = recognition.TILE_MODE, recognition.TILE_SCAN
recognition.TILE_MODE, recognition.TILE_SCAN = "auto", False
check(
    "a 12 MP phone photo is tiled",
    recognition.should_tile(3024, 4032) is True,
)
check(
    "a photo small enough to need no shrinking is not tiled",
    recognition.should_tile(900, 1200) is False,
)
check(
    "a photo just over MAX_EDGE but under one tile is not tiled",
    recognition.should_tile(700, recognition.TILE_SIZE - 1) is False,
)

recognition.TILE_MODE, recognition.TILE_SCAN = "0", False
check(
    "TILE_SCAN=0 switches tiling off even for a huge photo",
    recognition.should_tile(3024, 4032) is False,
)

recognition.TILE_MODE, recognition.TILE_SCAN = "1", True
check(
    "TILE_SCAN=1 forces tiling on a small photo",
    recognition.should_tile(400, 400) is True,
)
recognition.TILE_MODE, recognition.TILE_SCAN = "auto", False


# ---------------------------------------------------------------- cropping
section("cropping a distant face out of the original photo")

rng = np.random.default_rng(11)
photo = rng.integers(0, 255, size=(600, 800, 3)).astype(np.uint8)

# A 60 px face in the middle: margin 0.45 adds 27 px on each side.
crop, off_x, off_y = recognition.crop_with_margin(photo, (300, 360, 360, 300), 0.45)
check(
    "the crop is the face plus a margin",
    crop.shape[:2] == (114, 114),
    str(crop.shape),
)
check("the offset locates the crop in the photo", (off_x, off_y) == (273, 273))

# A face against the top-left corner cannot be padded past the edge.
edge_crop, edge_x, edge_y = recognition.crop_with_margin(photo, (0, 60, 60, 0), 0.45)
check(
    "a face on the edge is clamped to the photo, not padded past it",
    (edge_x, edge_y) == (0, 0) and edge_crop.shape[:2] == (87, 87),
    f"{(edge_x, edge_y)} {edge_crop.shape}",
)

big = recognition._upscale(crop, 2.5)
check(
    "enlarging multiplies both sides",
    big.shape[:2] == (285, 285),
    str(big.shape),
)
check("enlarging by 1.0 is a no-op", recognition._upscale(crop, 1.0).shape == crop.shape)
check("the enlarged crop keeps its 3 colour channels", big.shape[2] == 3)


# ------------------------------------------------- encoding one small face
section("a small face is enlarged before it is encoded")

stub = with_stub(Stub(shape=(600, 800), boxes=[]))
encoding = recognition.encode_small_face(photo, (300, 360, 360, 300))
call = stub.encode_calls[0]
check("an encoding comes back", encoding is not None)
check(
    "the face is encoded at roughly UPSCALE_FACE_PX, not its original 60 px",
    min(call["boxes"][0][1] - call["boxes"][0][3], call["boxes"][0][2] - call["boxes"][0][0])
    >= recognition.UPSCALE_FACE_PX - 2,
    str(call["boxes"][0]),
)
check(
    "the enlarged crop is what gets handed to the encoder",
    call["shape"] == (285, 285),
    str(call["shape"]),
)
check(
    "a distant face is encoded with several jitters to average out noise",
    call["num_jitters"] == recognition.SMALL_FACE_JITTERS,
    str(call["num_jitters"]),
)
check(
    "the detector is re-run on the enlarged crop",
    (285, 285) in stub.locate_calls,
    str(stub.locate_calls),
)

# When the detector does find the face again in the enlarged crop, that better
# aligned box is the one used.
stub = with_stub(Stub(shape=(600, 800), boxes=[], crop_box=(20, 260, 265, 25)))
recognition.encode_small_face(photo, (300, 360, 360, 300))
check(
    "a box found in the enlarged crop wins over the scaled-up one",
    stub.encode_calls[0]["boxes"] == [(20, 260, 265, 25)],
    str(stub.encode_calls[0]["boxes"]),
)

# The upscale factor is capped, so a 10 px speck is not blown up 15x.
stub = with_stub(Stub(shape=(600, 800), boxes=[]))
recognition.encode_small_face(photo, (300, 310, 310, 300))
capped = stub.encode_calls[0]["shape"][0] / 19  # crop is 10px + 2*4px margin
check(
    "the enlargement factor is capped by MAX_UPSCALE",
    capped <= recognition.MAX_UPSCALE + 0.1,
    str(capped),
)


# ------------------------------------------------------ routing big vs small
section("big faces keep the fast batched path")

big_box = (0, 200, 200, 0)      # 200 px, front row
small_box = (300, 360, 360, 300)  # 60 px, back row
stub = with_stub(Stub(shape=(600, 800), boxes=[]))
encodings = recognition.encode_boxes(photo, [big_box, small_box])

check("one encoding per detected face, in order", len(encodings) == 2)
check(
    "the big face is encoded in one batched call on the full photo",
    stub.encode_calls[0]["shape"] == (600, 800)
    and stub.encode_calls[0]["boxes"] == [big_box],
    str(stub.encode_calls[0]),
)
check(
    "the big face is not enlarged or jittered",
    stub.encode_calls[0]["num_jitters"] == 1,
)
check(
    "only the small face takes the crop-and-enlarge path",
    len(stub.encode_calls) == 2 and stub.encode_calls[1]["shape"] == (285, 285),
    str([c["shape"] for c in stub.encode_calls]),
)

stub = with_stub(Stub(shape=(600, 800), boxes=[]))
recognition.encode_boxes(photo, [big_box, big_box])
check(
    "a photo of only near faces costs exactly one encode call",
    len(stub.encode_calls) == 1,
    str(len(stub.encode_calls)),
)


# -------------------------------------------------------------- identify()
section("identify reports far faces honestly")

room = rng.integers(0, 255, size=(400, 400, 3)).astype(np.uint8)
near = (0, 160, 160, 0)      # 160 px
far = (200, 260, 260, 200)   # 60 px
labels = [{"id": 7, "name": "Asha", "roll_no": "12"}]


def matrix_at(distance: float) -> np.ndarray:
    """One reference vector sitting exactly `distance` from the stub encoding."""
    row = np.zeros(128)
    row[0] = distance
    return np.array([row])


stub = with_stub(Stub(shape=(400, 400), boxes=[near, far]))
faces = recognition.identify(room, matrix_at(0.20), labels)
check("one Face per detection", len(faces) == 2)
by_px = {f.face_px: f for f in faces}
check(
    "each face records how many pixels wide it was",
    sorted(by_px) == [60, 160],
    str(sorted(by_px)),
)
check("the near face is not flagged as enlarged", by_px[160].upscaled is False)
check("the far face is flagged as enlarged", by_px[60].upscaled is True)
check(
    "a close match is accepted for the far face too",
    by_px[60].status == "matched" and by_px[60].student_id == 7,
    by_px[60].status,
)

# Distance 0.63: past REVIEW_DISTANCE (0.60) but inside the far-face slack.
stub = with_stub(Stub(shape=(400, 400), boxes=[near, far]))
faces = recognition.identify(room, matrix_at(0.63), labels)
by_px = {f.face_px: f for f in faces}
check(
    "a borderline far face is offered for review instead of being dropped",
    by_px[60].status == "review" and by_px[60].name == "Asha",
    by_px[60].status,
)
check(
    "the same distance on a near face stays unknown -- no invented matches",
    by_px[160].status == "unknown",
    by_px[160].status,
)

# Nothing is auto-accepted just because it was far away.
stub = with_stub(Stub(shape=(400, 400), boxes=[far]))
faces = recognition.identify(room, matrix_at(0.55), labels)
check(
    "a far face past MATCH_DISTANCE is never auto-marked present",
    faces[0].status == "review",
    faces[0].status,
)

# Boxes must come back in original-photo coordinates even when the photo was
# shrunk for detection.
original_limit = recognition._limit_size
recognition._limit_size = lambda rgb: (np.asarray(rgb)[::2, ::2], 0.5)  # type: ignore[assignment]
stub = with_stub(Stub(shape=(200, 200), boxes=[(50, 80, 80, 50)]))
faces = recognition.identify(room, matrix_at(0.20), labels)
recognition._limit_size = original_limit  # type: ignore[assignment]
check(
    "a box detected on the shrunk copy is mapped back to the full photo",
    (faces[0].top, faces[0].right, faces[0].bottom, faces[0].left)
    == (100, 160, 160, 100),
    str((faces[0].top, faces[0].right, faces[0].bottom, faces[0].left)),
)
# The mapped-back box is 60 px, so it takes the crop path -- and the crop must
# be cut from the 400x400 original (114 px + 2.5x = 285), not from the 200x200
# copy detection ran on (which would give roughly half that).
check(
    "the crop is cut from the full-resolution photo, not the shrunk copy",
    [c["shape"] for c in stub.encode_calls] == [(285, 285)],
    str([c["shape"] for c in stub.encode_calls]),
)

# A face the encoder cannot handle is still reported, so the teacher sees it.
class NoEncoding(Stub):
    def face_encodings(self, image, boxes, num_jitters=1):
        super().face_encodings(image, boxes, num_jitters)
        return []


stub = with_stub(NoEncoding(shape=(400, 400), boxes=[far]))
faces = recognition.identify(room, matrix_at(0.20), labels)
check(
    "a detected but unencodable face is reported as unknown, not swallowed",
    len(faces) == 1 and faces[0].status == "unknown" and faces[0].face_px == 60,
    str(faces),
)

check(
    "face_px and upscaled reach the JSON the browser gets",
    {"face_px", "upscaled"} <= set(faces[0].to_dict()),
    str(sorted(faces[0].to_dict())),
)

recognition.TILE_MODE, recognition.TILE_SCAN = mode, forced

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed:")
    for item in FAILURES:
        print(f"  - {item}")
    raise SystemExit(1)
print("All small-face checks passed.")
