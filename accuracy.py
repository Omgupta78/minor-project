"""Measure how well the recogniser actually performs.

Without this you can only say "it seems better". With it you can write a real
sentence in the report, such as "recall rose from 0.71 to 0.89 after enrolling
three photos per student".

How to use it
-------------
1. Enrol your students as usual through the app.
2. Build a labelled test set of photos the app has never seen, one folder per
   student, the folder named with that student's roll number::

       testset/
           CS-2024001/  img1.jpg  img2.jpg
           CS-2024002/  img3.jpg
           unknown/     stranger1.jpg      <- optional, see below

   Photos in a folder called "unknown" (or "stranger", or "none") are people
   who are NOT enrolled. They measure false positives, which matter more than
   anything else here: wrongly marking a student present is worse than
   missing one.
3. Run::

       python accuracy.py --folder testset --class-id 1

The metrics
-----------
* precision = of the faces we named, how many were right. Low precision means
  the app puts the wrong name on students.
* recall    = of the faces we should have named, how many we did. Low recall
  means students get marked absent while sitting in the room.
* The threshold sweep re-scores the same photos at many MATCH_DISTANCE values
  so you can pick the best one for your class instead of guessing.

The scoring functions at the top take plain numbers and no image libraries, so
they are unit tested by qualitytest.py.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Iterable, Optional, Sequence

UNKNOWN_FOLDERS = {"unknown", "unknowns", "stranger", "strangers", "none", "other"}


# --------------------------------------------------------------- scoring
def classify(
    truth: Optional[str],
    predicted: Optional[str],
) -> str:
    """Bucket one decision.

    * hit           - named the right student
    * wrong_name    - named a student, but the wrong one (a false positive)
    * false_alarm   - named a student for a face that is not enrolled
    * miss          - named nobody, but should have
    * correct_pass  - named nobody for a face that is not enrolled
    """
    if truth is None:
        return "false_alarm" if predicted is not None else "correct_pass"
    if predicted is None:
        return "miss"
    return "hit" if predicted == truth else "wrong_name"


def evaluate(records: Sequence[dict]) -> dict:
    """Turn a list of {truth, predicted} decisions into metrics.

    A "wrong_name" counts as both a false positive and a missed identification,
    which is the honest reading: the student who was there was not found, and
    somebody else was falsely marked present.
    """
    buckets = {
        "hit": 0,
        "wrong_name": 0,
        "false_alarm": 0,
        "miss": 0,
        "correct_pass": 0,
    }
    for record in records:
        buckets[classify(record.get("truth"), record.get("predicted"))] += 1

    true_pos = buckets["hit"]
    false_pos = buckets["wrong_name"] + buckets["false_alarm"]
    false_neg = buckets["miss"] + buckets["wrong_name"]

    precision = true_pos / (true_pos + false_pos) if true_pos + false_pos else 0.0
    recall = true_pos / (true_pos + false_neg) if true_pos + false_neg else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    total = len(records)
    correct = buckets["hit"] + buckets["correct_pass"]

    return {
        "faces": total,
        "true_positives": true_pos,
        "false_positives": false_pos,
        "false_negatives": false_neg,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(correct / total, 4) if total else 0.0,
        **buckets,
    }


def apply_threshold(
    samples: Sequence[dict],
    threshold: float,
) -> list[dict]:
    """Re-decide every sample at a given distance threshold.

    A sample is {truth, nearest, distance}: who it really is, who the closest
    enrolled student was, and how far away. Nothing is re-encoded, so a sweep
    over twenty thresholds costs no extra recognition work.
    """
    out = []
    for sample in samples:
        distance = sample.get("distance")
        accepted = distance is not None and distance <= threshold
        out.append(
            {
                "truth": sample.get("truth"),
                "predicted": sample.get("nearest") if accepted else None,
            }
        )
    return out


def sweep(
    samples: Sequence[dict],
    thresholds: Iterable[float] = None,
) -> list[dict]:
    """Score the same samples at many thresholds, best F1 first in the report."""
    if thresholds is None:
        thresholds = [round(0.35 + 0.025 * i, 3) for i in range(15)]  # 0.35-0.70
    results = []
    for threshold in thresholds:
        metrics = evaluate(apply_threshold(samples, threshold))
        metrics["threshold"] = threshold
        results.append(metrics)
    return results


def histogram(
    values: Sequence[float],
    bins: int = 12,
    low: float = 0.0,
    high: float = 1.0,
    width: int = 40,
) -> list[str]:
    """A text histogram of match distances.

    Two clear humps, one near zero and one far out, means the thresholds have
    an easy job. One smeared hump means the enrolment photos are the problem,
    and no threshold will save you.
    """
    if not values:
        return ["(no distances recorded)"]
    counts = [0] * bins
    span = (high - low) / bins
    for value in values:
        index = int((value - low) / span) if span else 0
        counts[min(max(index, 0), bins - 1)] += 1
    peak = max(counts) or 1
    lines = []
    for i, count in enumerate(counts):
        start = low + i * span
        bar = "#" * int(round(width * count / peak))
        lines.append(f"  {start:4.2f}-{start + span:4.2f} | {bar:<{width}} {count}")
    return lines


# ------------------------------------------------------------- collection
def collect_samples(folder: Path, class_id: Optional[int] = None) -> list[dict]:
    """Encode every test photo and find its nearest enrolled student.

    Imports are local so the scoring functions above stay importable on a
    machine without dlib installed.
    """
    import numpy as np

    import db
    import recognition

    recognition.ensure_available()
    fr = recognition._fr()

    with db.session_scope() as conn:
        _ids, labels, matrix = db.known_faces(conn, class_id)
    if not len(matrix):
        raise SystemExit(
            "No enrolled students with encodings were found. Enrol students "
            "first, or pass a different --class-id."
        )
    print(f"Comparing against {len(matrix)} reference photos.")

    samples: list[dict] = []
    for student_dir in sorted(p for p in folder.iterdir() if p.is_dir()):
        truth = None if student_dir.name.lower() in UNKNOWN_FOLDERS else student_dir.name
        for image_path in sorted(student_dir.iterdir()):
            if image_path.suffix.lower() not in recognition.IMAGE_EXTS:
                continue
            image = recognition.load_image(str(image_path))
            boxes = fr.face_locations(image, number_of_times_to_upsample=1)
            if not boxes:
                # Counts as a miss: a face that should have been found was not.
                samples.append(
                    {
                        "truth": truth,
                        "nearest": None,
                        "distance": None,
                        "file": str(image_path),
                    }
                )
                continue
            box = max(boxes, key=lambda b: (b[2] - b[0]) * (b[1] - b[3]))
            encodings = fr.face_encodings(image, [box])
            if not encodings:
                continue
            distances = fr.face_distance(matrix, encodings[0])
            best = int(np.argmin(distances))
            samples.append(
                {
                    "truth": truth,
                    "nearest": labels[best]["roll_no"],
                    "distance": float(distances[best]),
                    "file": str(image_path),
                }
            )
    return samples


def report(samples: Sequence[dict], threshold: float) -> None:
    metrics = evaluate(apply_threshold(samples, threshold))

    print(f"\nAt MATCH_DISTANCE = {threshold}")
    print(f"  faces tested       {metrics['faces']}")
    print(f"  correct name       {metrics['hit']}")
    print(f"  wrong name         {metrics['wrong_name']}")
    print(f"  false alarm        {metrics['false_alarm']}  (not enrolled, named anyway)")
    print(f"  missed             {metrics['miss']}")
    print(f"  correctly ignored  {metrics['correct_pass']}")
    print(f"  precision          {metrics['precision']}")
    print(f"  recall             {metrics['recall']}")
    print(f"  F1                 {metrics['f1']}")

    matched = [s["distance"] for s in samples if s.get("distance") is not None and s.get("truth") == s.get("nearest")]
    others = [s["distance"] for s in samples if s.get("distance") is not None and s.get("truth") != s.get("nearest")]

    print("\nDistance to the correct student (want these low):")
    for line in histogram(matched):
        print(line)
    print("\nDistance when the nearest was the wrong person (want these high):")
    for line in histogram(others):
        print(line)

    print("\nThreshold sweep:")
    print("  thresh  precision  recall     F1")
    rows = sweep(samples)
    for row in rows:
        print(
            f"  {row['threshold']:<7} {row['precision']:<10} "
            f"{row['recall']:<10} {row['f1']}"
        )
    best = max(rows, key=lambda r: (r["f1"], -r["threshold"]))
    print(
        f"\nBest F1 at MATCH_DISTANCE={best['threshold']} "
        f"(precision {best['precision']}, recall {best['recall']})."
    )
    print("Set it with:  set MATCH_DISTANCE=" + str(best["threshold"]))
    print(
        "Be cautious raising it much above 0.6 \u2014 that is where different "
        "people start matching each other."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--folder",
        default="testset",
        help="folder of labelled test photos, one sub-folder per roll number",
    )
    parser.add_argument(
        "--class-id",
        type=int,
        default=None,
        help="limit the comparison to one class (recommended)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=float(os.environ.get("MATCH_DISTANCE", "0.50")),
        help="distance threshold to report on in detail",
    )
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"No such folder: {folder}")
        print("Create it with one sub-folder per student, named by roll number.")
        return 1

    samples = collect_samples(folder, args.class_id)
    if not samples:
        print("No test photos were found.")
        return 1
    report(samples, args.threshold)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
