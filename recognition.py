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


def encode_face(image_path: os.PathLike | str) -> Optional[np.ndarray]:
    """Return the 128-D encoding of the single face in an enrolment photo.

    Returns None when no face is found, so the caller can reject the upload
    instead of silently registering a student who can never be recognised.
    """
    fr = _fr()
    image = load_image(str(image_path))
    boxes = fr.face_locations(image, number_of_times_to_upsample=1)
    if not boxes:
        return None
    if len(boxes) > 1:
        # Enrolment photos should hold one face; use the largest if not.
        boxes = [max(boxes, key=lambda b: (b[2] - b[0]) * (b[1] - b[3]))]
    encodings = fr.face_encodings(image, boxes)
    return encodings[0] if encodings else None


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

    small, scale = _limit_size(rgb_image)
    boxes = fr.face_locations(
        small, number_of_times_to_upsample=UPSAMPLE, model=DETECTION_MODEL
    )
    if not boxes:
        return []
    encodings = fr.face_encodings(small, boxes)

    faces: list[Face] = []
    for box, encoding in zip(boxes, encodings):
        top, right, bottom, left = (int(v / scale) for v in box)
        face = Face(
            top=top, right=right, bottom=bottom, left=left, image_index=image_index
        )

        if len(known_matrix):
            distances = fr.face_distance(known_matrix, encoding)
            best = int(np.argmin(distances))
            dist = float(distances[best])
            face.distance = round(dist, 4)
            face.confidence = distance_to_confidence(dist, threshold)
            if dist <= threshold:
                face.status = "matched"
                face.student_id = labels[best]["id"]
                face.name = labels[best]["name"]
                face.roll_no = labels[best]["roll_no"]
            elif dist <= review_threshold:
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
    return {
        "images": len(per_image),
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
