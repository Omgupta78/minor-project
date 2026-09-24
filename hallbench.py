"""Measure recognition against a large-room photo, row by row.

accuracy.py answers "how good is the recogniser on my test photos". This
answers the different question a hall forces on you: "how far back in the room
does it still work, and what happens when 120 students are enrolled instead of
ten". Both matter, and the second one is the reason the defaults in
recognition.py are what they are -- see RECOGNITION.md for the numbers this
produced.

Two ways to run it.

1. Against a real classroom photograph you have ground truth for::

       python hallbench.py --photo hall.jpg --truth hall.json --class-id 1

   hall.json is a list of {"roll_no": "CS-001", "box": [left, top, right,
   bottom]} in the photo's own pixel coordinates.

2. Against a composed room, built from a labelled folder in the same layout
   accuracy.py expects -- one sub-folder per roll number, at least two photos
   in each. One photo enrols the student, another is seated in the room::

       python hallbench.py --compose testset --rows 6 --per-row 20

   The composed room places each row at the face size a phone really produces
   at that distance, so the output is a curve of identification rate against
   face width. That curve is the whole answer to "will the back row work":
   it is pixels on the face that decide it, not the threshold.

Needs dlib. Nothing in CI depends on it; halltest.py covers the 120-student
capacity path with a stub instead.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

# A phone at the front of a hall: ~70 degrees horizontal, a 16 cm face.
FOV_DEGREES = 70.0
FACE_METRES = 0.16


def face_px_at(distance_m: float, image_width: int) -> float:
    frame = 2 * distance_m * math.tan(math.radians(FOV_DEGREES) / 2)
    return image_width * FACE_METRES / frame


def compose(folder: Path, out: Path, rows: int, per_row: int,
            width: int, height: int, front_m: float, back_m: float) -> list[dict]:
    """Build a room photo out of a labelled folder. Returns the ground truth."""
    from PIL import Image, ImageEnhance, ImageFilter

    people = sorted(
        p for p in folder.iterdir()
        if p.is_dir() and len(list(p.glob("*.[jJ][pP][gG]"))) >= 2
    )
    needed = rows * per_row
    if len(people) < needed:
        raise SystemExit(
            f"{folder} has {len(people)} students with two or more photos; "
            f"{needed} are needed for {rows} rows of {per_row}."
        )
    random.shuffle(people)
    chosen = people[:needed]

    canvas = Image.new("RGB", (width, height), (46, 44, 42))
    truth: list[dict] = []
    step = (back_m - front_m) / max(1, rows - 1)

    for row in range(rows):
        distance = front_m + row * step
        target = face_px_at(distance, width)
        for column in range(per_row):
            person = chosen[row * per_row + column]
            shots = sorted(person.glob("*.[jJ][pP][gG]"))
            seated = Image.open(shots[1]).convert("RGB")
            # A portrait is mostly surround; the face is roughly the middle
            # 45%, so the tile has to be that much bigger than the face.
            tile = max(8, int(round(target / 0.45)))
            thumb = seated.resize((tile, tile), Image.LANCZOS)
            if row >= rows // 2:                      # distance costs detail
                thumb = thumb.filter(ImageFilter.GaussianBlur(0.12 * (row - 1)))
                thumb = ImageEnhance.Contrast(thumb).enhance(1.0 - 0.05 * row)
            spread = width * (0.34 + 0.62 * (front_m / distance) ** 0.55)
            x = int((width - spread) / 2 + spread * (column + 0.5) / per_row - tile / 2)
            y = int(height * (0.30 + 0.62 * (1 - row / max(1, rows - 1)) ** 1.25) - tile / 2)
            canvas.paste(thumb, (x, y))
            truth.append({
                "roll_no": person.name,
                "row": row,
                "face_px": round(target, 1),
                "enrol": str(shots[0]),
                "box": [x + int(tile * .28), y + int(tile * .24),
                        x + int(tile * .72), y + int(tile * .80)],
            })

    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, "JPEG", quality=88)
    return truth


def overlap(face, box) -> float:
    """Intersection over union of a detected face and a ground-truth box."""
    iw = max(0, min(face.right, box[2]) - max(face.left, box[0]))
    ih = max(0, min(face.bottom, box[3]) - max(face.top, box[1]))
    inner = iw * ih
    if inner <= 0:
        return 0.0
    area = (face.right - face.left) * (face.bottom - face.top)
    other = (box[2] - box[0]) * (box[3] - box[1])
    return inner / (area + other - inner)


def report(photo: Path, truth: list[dict], class_id, enrol_from_truth: bool) -> int:
    import db
    import recognition

    if enrol_from_truth:
        print(f"Enrolling {len(truth)} students from their reference photos...")
        started = time.time()
        db.init_db()
        with db.session_scope() as conn:
            class_id = db.create_class(conn, "Hall benchmark", "")
            for seat in truth:
                encoding, quality = recognition.encode_face_checked(seat["enrol"])
                if encoding is None:
                    print(f"  rejected {seat['roll_no']}: {quality.get('problem')}")
                    continue
                db.create_student(conn, seat["roll_no"], seat["roll_no"],
                                  class_id, None, encoding)
        print(f"  done in {time.time() - started:.0f}s")

    with db.session_scope() as conn:
        _ids, labels, matrix = db.known_faces(conn, class_id)
    if not len(matrix):
        raise SystemExit("No enrolled faces. Enrol students, or pass --compose.")

    image = recognition.load_image(str(photo))
    print(f"\nPhoto {image.shape[1]}x{image.shape[0]}, "
          f"gallery {len(matrix)} references for "
          f"{len({label['id'] for label in labels})} students")
    print(f"workers={recognition.worker_count(len(truth))} "
          f"threshold={recognition.MATCH_DISTANCE} "
          f"margin={recognition.MATCH_MARGIN} "
          f"penalty={recognition.SMALL_FACE_PENALTY}")

    # identify() detects internally, so the timed detect_faces call below is
    # only there to attribute the cost -- it is a component of the scan, not
    # an addition to it. Adding the two together would overstate the total.
    started = time.time()
    boxes = recognition.detect_faces(image)
    detect_seconds = time.time() - started
    started = time.time()
    faces = recognition.identify(image, matrix, labels)
    scan_seconds = time.time() - started
    print(f"{len(boxes)} faces, scanned in {scan_seconds:.1f}s "
          f"(detection {detect_seconds:.1f}s of it, "
          f"encoding and matching {scan_seconds - detect_seconds:.1f}s)")

    rows: dict[int, list[dict]] = {}
    for seat in truth:
        rows.setdefault(seat.get("row", 0), []).append(seat)

    print(f"\n{'row':>4}{'face px':>9}{'detected':>12}{'identified':>13}{'wrong':>7}")
    totals = [0, 0, 0, 0]
    for row in sorted(rows):
        seats = rows[row]
        detected = identified = wrong = 0
        for seat in seats:
            best, score = None, 0.0
            for face in faces:
                value = overlap(face, seat["box"])
                if value > score:
                    best, score = face, value
            if score < 0.25:
                continue
            detected += 1
            if best.student_id is None:
                continue
            if best.roll_no == seat["roll_no"]:
                identified += 1
            else:
                wrong += 1
        totals = [totals[0] + len(seats), totals[1] + detected,
                  totals[2] + identified, totals[3] + wrong]
        print(f"{row + 1:>4}{seats[0].get('face_px', 0):>9.0f}"
              f"{detected:>8}/{len(seats):<3}{identified:>9}/{len(seats):<3}{wrong:>7}")
    print(f"{'all':>4}{'':>9}{totals[1]:>8}/{totals[0]:<3}"
          f"{totals[2]:>9}/{totals[0]:<3}{totals[3]:>7}")

    matched = sum(1 for f in faces if f.status == "matched")
    print(f"\nauto-marked present: {matched}   "
          f"needs review: {sum(1 for f in faces if f.status == 'review')}   "
          f"unknown: {sum(1 for f in faces if f.status == 'unknown')}")
    print("A row whose faces are detected but not identified has run out of "
          "pixels, not out of threshold. Photograph those rows closer.")
    return 0 if totals[3] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--photo", type=Path)
    parser.add_argument("--truth", type=Path)
    parser.add_argument("--class-id", type=int, default=None)
    parser.add_argument("--compose", type=Path, metavar="FOLDER")
    parser.add_argument("--rows", type=int, default=6)
    parser.add_argument("--per-row", type=int, default=20)
    parser.add_argument("--width", type=int, default=4000)
    parser.add_argument("--height", type=int, default=3000)
    parser.add_argument("--front", type=float, default=4.0, help="metres")
    parser.add_argument("--back", type=float, default=15.0, help="metres")
    parser.add_argument("--out", type=Path, default=Path("instance/hall.jpg"))
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args()

    random.seed(args.seed)

    if args.compose:
        if not args.compose.is_dir():
            print(f"No such folder: {args.compose}")
            return 2
        truth = compose(args.compose, args.out, args.rows, args.per_row,
                        args.width, args.height, args.front, args.back)
        args.out.with_suffix(".json").write_text(json.dumps(truth, indent=1))
        print(f"Composed {args.out} with {len(truth)} students")
        for row in range(args.rows):
            distance = args.front + (args.back - args.front) * row / max(1, args.rows - 1)
            print(f"  row {row + 1}: {distance:>4.1f} m -> "
                  f"face ~{face_px_at(distance, args.width):.0f} px")
        return report(args.out, truth, None, enrol_from_truth=True)

    if not (args.photo and args.truth):
        parser.error("give --photo and --truth, or --compose FOLDER")
    if not args.photo.exists():
        print(f"No such photo: {args.photo}")
        return 2
    truth = json.loads(args.truth.read_text())
    return report(args.photo, truth, args.class_id, enrol_from_truth=False)


if __name__ == "__main__":
    sys.exit(main())
