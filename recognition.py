"""
recognition.py - the single shared face-recognition core.

Every entry point (the Flask app, the CLI webcam runner, the enrolment tools)
imports from here, so there is exactly one copy of the matching logic instead
of three slightly different ones.

Key behaviours
--------------
* Real confidence scores. The distance returned by dlib is mapped onto a 0-1
  confidence with the standard ramp used by the face_recognition project, so
  the UI can show an honest number instead of a hardcoded "94%".
* Correct per-face labelling. identify() returns one record per detected face,
  in the same order as the detections, so a label can never drift onto the
  wrong box when somebody in the photo is unrecognised.
* Group-photo friendly. A classroom photo has small faces, so detection can
  upsample instead of blindly downscaling the image.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

# Match threshold. Lower is stricter. 0.5 is a good default for dlib's
# 128-D embeddings; 0.45 for a stricter setup, 0.55 if you get too many misses.
MATCH_DISTANCE = float(os.environ.get("MATCH_DISTANCE", "0.50"))

# Faces whose best distance falls between MATCH_DISTANCE and REVIEW_DISTANCE are
# not auto-accepted: they are surfaced to the teacher as "needs review".
REVIEW_DISTANCE = float(os.environ.get("REVIEW_DISTANCE", "0.60"))

# Detection settings for group photos.
UPSAMPLE = int(os.environ.get("FACE_UPSAMPLE", "1"))
DETECTION_MODEL = os.environ.get("FACE_MODEL", "hog")  # "cnn" is slower/better
MAX_EDGE = int(os.environ.get("MAX_EDGE", "1600"))     # cap for very large photos

# Enrolment encoding quality. num_jitters averages the embedding over several
# slightly perturbed crops of the same face, which gives a cleaner reference
# vector. The cost is paid once, at enrolment, never during a scan.
ENROL_JITTERS = int(os.environ.get("ENROL_JITTERS", "10"))

# Thresholds for refusing a bad enrolment photo. Whatever is accepted here
# becomes the permanent reference for that student, so every future scan
# inherits its faults. Refusing the upload is cheaper than debugging later.
MIN_FACE_PX = int(os.environ.get("MIN_FACE_PX", "80"))
MIN_SHARPNESS = float(os.environ.get("MIN_SHARPNESS", "25"))
MIN_BRIGHTNESS = float(os.environ.get("MIN_BRIGHTNESS", "45"))
MAX_BRIGHTNESS = float(os.environ.get("MAX_BRIGHTNESS", "225"))

# Tiled detection. "auto" (the default) tiles only when the photo is big
# enough that shrinking it to MAX_EDGE would throw away the detail the back
# row depends on. "1" forces it always, "0" switches it off.
TILE_MODE = os.environ.get("TILE_SCAN", "auto").strip().lower()
TILE_SCAN = TILE_MODE in {"1", "true", "yes", "on"}  # kept for older callers
TILE_SIZE = int(os.environ.get("TILE_SIZE", "1200"))
TILE_OVERLAP = int(os.environ.get("TILE_OVERLAP", "240"))

# Small (far away) faces. dlib's encoder wants roughly a 150 px face; a
# back-row face is often 60-90 px, and encoding it at that size produces a
# vector too noisy to match. Such faces are cropped out of the ORIGINAL photo
# and enlarged before encoding, which is the single biggest win for the back
# of the room.
SMALL_FACE_PX = int(os.environ.get("SMALL_FACE_PX", "110"))
UPSCALE_FACE_PX = int(os.environ.get("UPSCALE_FACE_PX", "150"))
MAX_UPSCALE = float(os.environ.get("MAX_UPSCALE", "4.0"))
CROP_MARGIN = float(os.environ.get("CROP_MARGIN", "0.45"))
# A few jittered passes average out the noise in an enlarged crop. Only paid
# on small faces, so a front-row-only photo scans at the usual speed.
SMALL_FACE_JITTERS = int(os.environ.get("SMALL_FACE_JITTERS", "2"))
# Distant faces are noisier, so their best distance sits slightly higher even
# when the identification is right. Rather than loosening the match threshold
# (which would invent matches), widen only the review band: a far student is
# then surfaced to the teacher for one click instead of being dropped.
SMALL_FACE_SLACK = float(os.environ.get("SMALL_FACE_SLACK", "0.06"))

# iPhones and recent Android phones shoot HEIC by default, so every layer of
# the pipeline has to accept it: the upload form, the folder enrolment scan,
# and the byte decoder used by /api/scan.
HEIF_EXTS = {".heic", ".heif"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"} | HEIF_EXTS

_HEIF_READY: Optional[bool] = None


def register_heif() -> bool:
    """Teach Pillow to open HEIC/HEIF files. Safe to call repeatedly.

    Returns True when pillow-heif is installed. Everything else keeps working
    when it is missing; only HEIC uploads are affected, and the caller can use
    the return value to print an install hint instead of a cryptic error.
    """
    global _HEIF_READY
    if _HEIF_READY is None:
        try:
            import pillow_heif

            pillow_heif.register_heif_opener()
            _HEIF_READY = True
        except Exception:
            _HEIF_READY = False
    return _HEIF_READY


class RecognitionUnavailable(RuntimeError):
    """Raised when dlib / face_recognition is not installed."""


def _fr():
    """Import face_recognition lazily so the database and Excel layers can be
    used (and unit-tested) on a machine without dlib compiled."""
    try:
        import face_recognition  # noqa: WPS433
    except Exception as exc:  # pragma: no cover - depends on local install
        raise RecognitionUnavailable(
            "face_recognition/dlib is not available. Install with\n"
            "    pip install -r requirements.txt\n"
            "On Windows this needs Visual Studio Build Tools "
            "(Desktop development with C++). See README-run.md."
        ) from exc
    return face_recognition


def distance_to_confidence(distance: float, threshold: float = MATCH_DISTANCE) -> float:
    """Map a face distance onto a 0-1 confidence.

    This is the ramp recommended by the face_recognition project: linear below
    the threshold, then eased so that a very small distance approaches 1.0.
    It is a monotonic transform of the distance, not a calibrated probability,
    and the report should say so.
    """
    distance = float(distance)
    if distance > threshold:
        span = 1.0 - threshold
        value = (1.0 - distance) / (span * 2.0)
        return max(0.0, round(value, 4))
    span = threshold
    value = 1.0 - (distance / (span * 2.0))
    eased = value + ((1.0 - value) * ((value - 0.5) * 2) ** 0.2)
    return min(1.0, round(eased, 4))


@dataclass
class Face:
    """One detected face in an image."""

    top: int
    right: int
    bottom: int
    left: int
    student_id: Optional[int] = None
    name: str = "Unknown"
    roll_no: str = ""
    distance: Optional[float] = None
    confidence: float = 0.0
    status: str = "unknown"  # matched | review | unknown | duplicate | repeat
    # Which uploaded photo this face came from. Lets the UI draw the box on the
    # right image when a session is built from several photos.
    image_index: int = 0
    # How wide the face is in the original photo, and whether it was small
    # enough to be enlarged before encoding. "Nobody was found there" and
    # "somebody was found but is too far away to read" are different problems
    # and the review screen should be able to tell them apart.
    face_px: int = 0
    upscaled: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ loading
def load_image(path_or_bytes) -> np.ndarray:
    """Load an image as an RGB numpy array from a path, bytes or file object."""
    fr = _fr()
    register_heif()  # face_recognition opens files through Pillow
    return fr.load_image_file(path_or_bytes)


def bgr_to_rgb(frame: np.ndarray) -> np.ndarray:
    import cv2

    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def decode_image_bytes(data: bytes) -> Optional[np.ndarray]:
    """Decode raw upload bytes into an RGB array (None if not an image).

    OpenCV cannot read HEIC/HEIF at all, and that is what an iPhone hands over
    when the teacher picks a photo from the camera roll, so anything OpenCV
    rejects gets a second attempt through Pillow.
    """
    try:
        import cv2

        arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if arr is not None:
            return bgr_to_rgb(arr)
    except Exception:
        pass  # fall through to Pillow
    return decode_with_pillow(data)


def decode_with_pillow(data: bytes) -> Optional[np.ndarray]:
    """Fallback decoder for HEIC/HEIF and any other format Pillow understands.

    Also applies the EXIF orientation tag. Phone photos are almost always
    stored landscape with a "rotate me" flag, and a sideways photo makes the
    face detector miss most of the class.
    """
    register_heif()
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            return np.asarray(image.convert("RGB"))
    except Exception:
        return None


def _limit_size(rgb: np.ndarray) -> tuple[np.ndarray, float]:
    """Shrink very large photos so detection stays fast. Returns (image, scale)
    where scale is the factor applied, so boxes can be mapped back."""
    import cv2

    height, width = rgb.shape[:2]
    longest = max(height, width)
    if longest <= MAX_EDGE:
        return rgb, 1.0
    scale = MAX_EDGE / longest
    resized = cv2.resize(rgb, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return resized, scale


# ------------------------------------------------------------ photo quality
def sharpness_of(image: np.ndarray) -> float:
    """Variance of the Laplacian, the standard cheap blur score.

    A sharp face has strong edges, so the second derivative varies a lot. A
    blurred one is smooth, so the variance collapses toward zero.
    """
    gray = np.asarray(image, dtype=np.float64)
    if gray.ndim == 3:
        gray = gray.mean(axis=2)
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return 0.0
    laplacian = (
        -4.0 * gray[1:-1, 1:-1]
        + gray[:-2, 1:-1]
        + gray[2:, 1:-1]
        + gray[1:-1, :-2]
        + gray[1:-1, 2:]
    )
    return float(laplacian.var())


def assess_face(rgb: np.ndarray, box: tuple) -> dict:
    """Measure face size, sharpness and brightness inside one detection box."""
    top, right, bottom, left = (int(v) for v in box)
    crop = np.asarray(rgb)[max(top, 0) : max(bottom, 0), max(left, 0) : max(right, 0)]
    if crop.size == 0:
        return {"face_px": 0, "sharpness": 0.0, "brightness": 0.0}
    return {
        "face_px": int(min(right - left, bottom - top)),
        "sharpness": round(sharpness_of(crop), 2),
        "brightness": round(float(np.asarray(crop, dtype=np.float64).mean()), 1),
    }


def quality_problem(report: dict) -> Optional[str]:
    """Plain-English reason to reject an enrolment photo, or None if usable."""
    face_px = report.get("face_px", 0)
    if face_px < MIN_FACE_PX:
        return (
            f"The face is only {face_px} pixels across; at least {MIN_FACE_PX} "
            "is needed. Move closer or crop the photo to the student."
        )
    if report.get("sharpness", 0.0) < MIN_SHARPNESS:
        return "The photo is too blurry. Hold the camera steady and retake it."
    brightness = report.get("brightness", 0.0)
    if brightness < MIN_BRIGHTNESS:
        return "The photo is too dark. Face a window or switch a light on."
    if brightness > MAX_BRIGHTNESS:
        return (
            "The photo is over-exposed. Avoid a bright window or light "
            "directly behind the student."
        )
    return None


# --------------------------------------------------------- tiled detection
def tile_windows(
    height: int,
    width: int,
    tile: Optional[int] = None,
    overlap: Optional[int] = None,
) -> list[tuple[int, int, int, int]]:
    """Split an image into overlapping (x, y, w, h) windows.

    Detecting inside full-resolution tiles finds the small back-row faces that
    vanish when the whole photo is shrunk to MAX_EDGE. The overlap stops a
    face sitting on a tile boundary from being cut in half by both tiles.
    """
    tile = TILE_SIZE if tile is None else int(tile)
    overlap = TILE_OVERLAP if overlap is None else int(overlap)
    tile = max(64, tile)
    overlap = max(0, min(overlap, tile - 1))
    if height <= tile and width <= tile:
        return [(0, 0, width, height)]

    step = max(1, tile - overlap)

    def starts(total: int) -> list[int]:
        if total <= tile:
            return [0]
        out = list(range(0, total - tile + 1, step))
        if out[-1] + tile < total:
            out.append(total - tile)  # flush the last window to the edge
        return out

    return [
        (x, y, min(tile, width), min(tile, height))
        for y in starts(height)
        for x in starts(width)
    ]


def _overlap_ratio(a: tuple, b: tuple) -> float:
    """Intersection over the smaller box.

    Two tiles that both see the same face return near-identical boxes, so
    "mostly contained in" is the useful test rather than plain IoU.
    """
    a_top, a_right, a_bottom, a_left = a
    b_top, b_right, b_bottom, b_left = b
    inner_h = max(0, min(a_bottom, b_bottom) - max(a_top, b_top))
    inner_w = max(0, min(a_right, b_right) - max(a_left, b_left))
    inner = inner_h * inner_w
    if inner <= 0:
        return 0.0
    smaller = min(
        (a_bottom - a_top) * (a_right - a_left),
        (b_bottom - b_top) * (b_right - b_left),
    )
    return inner / smaller if smaller > 0 else 0.0


def merge_boxes(boxes: Sequence[tuple], threshold: float = 0.4) -> list[tuple]:
    """Drop duplicate detections coming from overlapping tiles.

    Boxes are considered largest-first so the fuller view of a face survives,
    then returned in reading order (top to bottom, left to right).
    """
    kept: list[tuple] = []
    for box in sorted(
        boxes, key=lambda b: (b[2] - b[0]) * (b[1] - b[3]), reverse=True
    ):
        if all(_overlap_ratio(box, other) < threshold for other in kept):
            kept.append(box)
    return sorted(kept, key=lambda b: (b[0], b[3]))


def detect_tiled(
    rgb: np.ndarray,
    tile: Optional[int] = None,
    overlap: Optional[int] = None,
) -> list[tuple]:
    """Detect faces tile by tile at full resolution, in whole-image coords."""
    fr = _fr()
    image = np.asarray(rgb)
    height, width = image.shape[:2]
    found: list[tuple] = []
    for x, y, window_w, window_h in tile_windows(height, width, tile, overlap):
        crop = image[y : y + window_h, x : x + window_w]
        for top, right, bottom, left in fr.face_locations(
            crop, number_of_times_to_upsample=UPSAMPLE, model=DETECTION_MODEL
        ):
            found.append((top + y, right + x, bottom + y, left + x))
    return merge_boxes(found)


def should_tile(height: int, width: int) -> bool:
    """Decide whether this photo needs full-resolution tiled detection.

    Forcing tiling on every photo wastes time on a close-up of six students;
    never tiling loses the back row of a 12 MP hall shot. So the default is
    "auto": tile when the photo is large enough that shrinking it to MAX_EDGE
    would throw detail away, and there is more than one tile's worth of it.
    """
    if TILE_MODE in {"0", "false", "no", "off"}:
        return False
    if TILE_SCAN:
        return True
    longest = max(int(height), int(width))
    return longest > MAX_EDGE and longest > TILE_SIZE


# ------------------------------------------------------- small (far) faces
def crop_with_margin(
    rgb: np.ndarray, box: tuple, margin: Optional[float] = None
) -> tuple[np.ndarray, int, int]:
    """Cut a face out of the photo with some room around it.

    Returns (crop, x_offset, y_offset) so boxes found inside the crop can be
    put back into whole-photo coordinates. The margin matters: dlib's encoder
    expects to see forehead and chin, and a box cropped tight to the detection
    encodes noticeably worse.
    """
    margin = CROP_MARGIN if margin is None else float(margin)
    image = np.asarray(rgb)
    height, width = image.shape[:2]
    top, right, bottom, left = (int(v) for v in box)
    pad_y = int(round((bottom - top) * margin))
    pad_x = int(round((right - left) * margin))
    y0 = max(0, top - pad_y)
    x0 = max(0, left - pad_x)
    y1 = min(height, bottom + pad_y)
    x1 = min(width, right + pad_x)
    return image[y0:y1, x0:x1], x0, y0


def _upscale(crop: np.ndarray, factor: float) -> np.ndarray:
    """Enlarge a crop with Pillow's LANCZOS filter.

    Pillow rather than OpenCV on purpose: it is already a hard dependency for
    HEIC support, so this works even where cv2 is missing.
    """
    from PIL import Image

    image = np.asarray(crop)
    if factor <= 1.0 or image.size == 0:
        return image
    height, width = image.shape[:2]
    size = (max(1, int(round(width * factor))), max(1, int(round(height * factor))))
    return np.asarray(Image.fromarray(image).resize(size, Image.LANCZOS))


def encode_small_face(
    rgb: np.ndarray, box: tuple, fr=None
) -> Optional[np.ndarray]:
    """Encode one distant face by enlarging it first.

    dlib's encoder resizes whatever it is given to roughly 150 px internally.
    Handing it a 70 px back-row face means it upscales a blurry thumbnail with
    a crude filter; the resulting vector is too noisy to match reliably. Doing
    the enlargement ourselves -- from the ORIGINAL photo, with a good filter,
    with margin, then re-detecting so the face is properly framed -- is what
    turns a missed back row into a matched one.
    """
    fr = _fr() if fr is None else fr
    image = np.asarray(rgb)
    top, right, bottom, left = (int(v) for v in box)
    face_px = max(1, min(right - left, bottom - top))
    factor = min(MAX_UPSCALE, max(1.0, UPSCALE_FACE_PX / face_px))

    crop, off_x, off_y = crop_with_margin(image, box)
    if crop.size == 0:
        return None
    big = _upscale(crop, factor)

    inner = (
        int(round((top - off_y) * factor)),
        int(round((right - off_x) * factor)),
        int(round((bottom - off_y) * factor)),
        int(round((left - off_x) * factor)),
    )
    # Re-detect at the enlarged size. A box the detector draws here is better
    # aligned than our scaled-up original, and alignment is most of encoding
    # quality. If it finds nothing, fall back to the scaled box.
    try:
        found = fr.face_locations(big, number_of_times_to_upsample=0)
    except TypeError:  # a stub or older signature
        found = fr.face_locations(big)
    if found:
        inner = max(found, key=lambda b: (b[2] - b[0]) * (b[1] - b[3]))

    encodings = fr.face_encodings(big, [inner], num_jitters=SMALL_FACE_JITTERS)
    return encodings[0] if encodings else None


def encode_boxes(rgb: np.ndarray, boxes: Sequence[tuple]) -> list[Optional[np.ndarray]]:
    """Encode every detected face, enlarging the small ones first.

    Front-row faces are encoded in one batched call exactly as before, so the
    common case costs nothing extra. Only faces narrower than SMALL_FACE_PX
    take the slower crop-and-enlarge path, which is a handful of faces in a
    typical classroom photo.
    """
    fr = _fr()
    image = np.asarray(rgb)
    out: list[Optional[np.ndarray]] = [None] * len(boxes)

    big_enough = [
        i
        for i, b in enumerate(boxes)
        if min(int(b[1]) - int(b[3]), int(b[2]) - int(b[0])) >= SMALL_FACE_PX
    ]
    if big_enough:
        encodings = fr.face_encodings(image, [tuple(boxes[i]) for i in big_enough])
        for index, encoding in zip(big_enough, encodings):
            out[index] = encoding

    for index, box in enumerate(boxes):
        if out[index] is None:
            out[index] = encode_small_face(image, box, fr)
    return out


def encode_enrolment(image: np.ndarray) -> tuple[Optional[np.ndarray], dict]:
    """Encode the one face in an enrolment photo and report on its quality.

    Returns (encoding, report). The encoding is None whenever the photo is not
    good enough to become a reference, and report["problem"] then holds a
    message that can be shown straight to the teacher.
    """
    fr = _fr()
    image = np.asarray(image)
    boxes = fr.face_locations(image, number_of_times_to_upsample=1)
    report: dict = {
        "faces": len(boxes),
        "face_px": 0,
        "sharpness": 0.0,
        "brightness": round(float(image.astype(np.float64).mean()), 1),
        "problem": None,
    }
    if not boxes:
        report["problem"] = "No face was found in this photo."
        return None, report
    if len(boxes) > 1:
        # Enrolment photos should hold one face; use the largest if not.
        boxes = [max(boxes, key=lambda b: (b[2] - b[0]) * (b[1] - b[3]))]

    report.update(assess_face(image, boxes[0]))
    report["problem"] = quality_problem(report)
    if report["problem"]:
        return None, report

    encodings = fr.face_encodings(image, boxes, num_jitters=ENROL_JITTERS)
    if not encodings:
        report["problem"] = "The face could not be encoded. Try a different photo."
        return None, report
    return encodings[0], report


def encode_face_checked(
    image_path: os.PathLike | str,
) -> tuple[Optional[np.ndarray], dict]:
    """encode_enrolment for a file on disk, quality report included."""
    return encode_enrolment(load_image(str(image_path)))


def encode_face(image_path: os.PathLike | str) -> Optional[np.ndarray]:
    """Return the 128-D encoding of the single face in an enrolment photo.

    Returns None when no face is found, so the caller can reject the upload
    instead of silently registering a student who can never be recognised.
    """
    encoding, _report = encode_face_checked(image_path)
    return encoding


def encode_faces_in_folder(folder: os.PathLike | str):
    """Yield (name, path, encoding|None) for every image in a folder."""
    folder = Path(folder)
    if not folder.exists():
        return
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in IMAGE_EXTS:
            continue
        try:
            yield path.stem, path, encode_face(path)
        except RecognitionUnavailable:
            raise
        except Exception as exc:
            print(f"  [faces] error on {path.name}: {exc}")
            yield path.stem, path, None


# ------------------------------------------------------------- identifying
def identify(
    rgb_image: np.ndarray,
    known_matrix: np.ndarray,
    labels: Sequence[dict],
    threshold: float = MATCH_DISTANCE,
    review_threshold: float = REVIEW_DISTANCE,
    image_index: int = 0,
) -> list[Face]:
    """Detect and identify every face in a class photo.

    Returns one Face per detection, in detection order. Each face carries its
    own name/confidence, so labels cannot be shifted onto the wrong box.
    """
    fr = _fr()
    image = np.asarray(rgb_image)
    height, width = image.shape[:2]

    if should_tile(height, width):
        # Full resolution, tile by tile: slower, but keeps small back-row
        # faces big enough for the detector to see them.
        boxes = detect_tiled(image)
    else:
        small, scale = _limit_size(image)
        found = fr.face_locations(
            small, number_of_times_to_upsample=UPSAMPLE, model=DETECTION_MODEL
        )
        # Map back to original-photo coordinates immediately, so encoding and
        # the boxes drawn in the UI both work at full detail.
        boxes = [tuple(int(round(v / scale)) for v in box) for box in found]
    if not boxes:
        return []

    # Small faces are cropped from the original photo and enlarged before
    # encoding; big ones go through one batched call as before.
    encodings = encode_boxes(image, boxes)

    faces: list[Face] = []
    for box, encoding in zip(boxes, encodings):
        top, right, bottom, left = (int(v) for v in box)
        face_px = max(0, min(right - left, bottom - top))
        face = Face(
            top=top,
            right=right,
            bottom=bottom,
            left=left,
            image_index=image_index,
            face_px=face_px,
            upscaled=face_px < SMALL_FACE_PX,
        )
        if encoding is None:
            # Detected but unencodable -- still worth showing as a red box so
            # the teacher knows somebody is there.
            faces.append(face)
            continue

        if len(known_matrix):
            distances = fr.face_distance(known_matrix, encoding)
            best = int(np.argmin(distances))
            dist = float(distances[best])
            face.distance = round(dist, 4)
            face.confidence = distance_to_confidence(dist, threshold)
            # A distant face is noisier, so its best distance sits a little
            # higher even when the answer is right. Widen the review band for
            # those, never the match band: the teacher gets a suggestion to
            # confirm instead of the app inventing a match.
            review_limit = review_threshold + (
                SMALL_FACE_SLACK if face.upscaled else 0.0
            )
            if dist <= threshold:
                face.status = "matched"
                face.student_id = labels[best]["id"]
                face.name = labels[best]["name"]
                face.roll_no = labels[best]["roll_no"]
            elif dist <= review_limit:
                # Close, but not close enough to accept on its own.
                face.status = "review"
                face.student_id = labels[best]["id"]
                face.name = labels[best]["name"]
                face.roll_no = labels[best]["roll_no"]
        faces.append(face)

    return faces


def resolve_duplicates(faces: list[Face]) -> list[Face]:
    """If two faces *within one photo* claim the same student, keep the closest.

    Without this, a photo containing a face plus a poster of that face could
    mark one student twice, and two lookalikes could both grab one identity.

    Note this is deliberately per-photo. The same student appearing in two
    different photos of the same room is normal, not suspicious, and is handled
    by merge_across_images() instead.
    """
    best_for_student: dict[int, Face] = {}
    for face in faces:
        if face.student_id is None:
            continue
        current = best_for_student.get(face.student_id)
        if current is None or (face.distance or 1.0) < (current.distance or 1.0):
            best_for_student[face.student_id] = face

    for face in faces:
        if face.student_id is None:
            continue
        if best_for_student.get(face.student_id) is not face:
            face.status = "duplicate"
            face.student_id = None
            face.name = "Duplicate"
            face.roll_no = ""
    return faces


# -------------------------------------------------- multiple photos per session
def identify_many(
    images: Sequence[np.ndarray],
    known_matrix: np.ndarray,
    labels: Sequence[dict],
    threshold: float = MATCH_DISTANCE,
    review_threshold: float = REVIEW_DISTANCE,
) -> list[list[Face]]:
    """Identify faces across several photos of the same class.

    One classroom photo rarely covers everybody: the back row is small, someone
    is always turned away, and a wide shot loses resolution. Taking two or three
    photos (left half, right half, back row) and merging the results is far more
    reliable than pushing a single wide shot through a bigger upsample.

    Returns one list of Faces per input image, in input order, so the UI can
    draw boxes on the correct photo. Duplicates *within* each photo are resolved
    here; duplicates *across* photos are handled by merge_across_images().
    """
    per_image: list[list[Face]] = []
    for index, rgb in enumerate(images):
        faces = identify(
            rgb,
            known_matrix,
            labels,
            threshold=threshold,
            review_threshold=review_threshold,
            image_index=index,
        )
        per_image.append(resolve_duplicates(faces))
    return per_image


def merge_across_images(per_image: Sequence[Sequence[Face]]) -> dict[int, Face]:
    """Pick the single best sighting of each student across all photos.

    A student standing in two overlapping photos is expected, not suspicious, so
    the extra sightings are marked "repeat" rather than "duplicate" and keep
    their name. Only the closest sighting is used for the attendance mark, which
    means adding more photos can only ever improve a student's confidence.
    """
    best: dict[int, Face] = {}
    for faces in per_image:
        for face in faces:
            if face.student_id is None:
                continue
            current = best.get(face.student_id)
            if current is None or (face.distance or 1.0) < (current.distance or 1.0):
                best[face.student_id] = face

    for faces in per_image:
        for face in faces:
            if face.student_id is None:
                continue
            if best.get(face.student_id) is not face:
                face.status = "repeat"
    return best


def summarise(per_image: Sequence[Sequence[Face]], best: dict[int, Face]) -> dict:
    """Counts for the scan header. Faces are counted per detection, but students
    are counted once no matter how many photos they appear in."""
    flat = [face for faces in per_image for face in faces]
    matched = [f for f in best.values() if f.status == "matched"]
    review = [f for f in best.values() if f.status == "review"]
    # NOTE: these counts are merged into the /api/scan response, which already
    # carries the per-photo detail array under "images". This key must stay
    # "images_scanned" or it would overwrite that array with a number and the
    # browser would try to call .forEach on it.
    return {
        "images_scanned": len(per_image),
        "total_faces": len(flat),
        "matched": len(matched),
        "needs_review": len(review),
        "unknown": sum(1 for f in flat if f.status in ("unknown", "duplicate")),
        "repeats": sum(1 for f in flat if f.status == "repeat"),
    }


def ensure_available() -> None:
    """Raise RecognitionUnavailable if dlib / face_recognition cannot be used.

    Called at startup so the launcher can tell the teacher that the pages will
    work but scanning will not, instead of failing later mid-demo.
    """
    _fr()
