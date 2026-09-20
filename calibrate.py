"""Calibrate face-match thresholds on a held-out class dataset.

This command refuses to recommend a threshold unless the test set includes
both enrolled students and strangers and meets an explicit precision floor.
Wrongly marking an absent student present is costlier than asking a teacher to
review an unknown face, so precision is the hard constraint.

Example: python calibrate.py --folder testset --class-id 1
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


def choose_threshold(rows: Sequence[dict], min_precision: float = 0.98,
                     min_recall: float = 0.80,
                     max_false_positives: int = 0) -> dict | None:
    """Choose highest recall among safe rows, then the tighter threshold."""
    eligible = [row for row in rows
        if row.get("precision", 0.0) >= min_precision
        and row.get("recall", 0.0) >= min_recall
        and row.get("false_positives", 0) <= max_false_positives]
    if not eligible:
        return None
    return max(eligible, key=lambda row: (
        row.get("recall", 0.0), row.get("f1", 0.0),
        -row.get("threshold", 1.0)))


def validate_mix(samples: Sequence[dict], min_enrolled: int,
                 min_unknown: int) -> dict:
    enrolled = sum(1 for sample in samples if sample.get("truth") is not None)
    unknown = len(samples) - enrolled
    errors = []
    if enrolled < min_enrolled:
        errors.append(f"need at least {min_enrolled} enrolled test faces; found {enrolled}")
    if unknown < min_unknown:
        errors.append(f"need at least {min_unknown} stranger faces; found {unknown}")
    return {"enrolled": enrolled, "unknown": unknown, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--folder", default="testset")
    parser.add_argument("--class-id", type=int, required=True)
    parser.add_argument("--min-precision", type=float, default=0.98)
    parser.add_argument("--min-recall", type=float, default=0.80)
    parser.add_argument("--max-false-positives", type=int, default=0)
    parser.add_argument("--min-enrolled", type=int, default=30)
    parser.add_argument("--min-unknown", type=int, default=10)
    parser.add_argument("--report", default="instance/model-calibration.json")
    parser.add_argument("--env-output", default=".env.calibrated")
    args = parser.parse_args()
    import accuracy
    if not 0 < args.min_precision <= 1 or not 0 < args.min_recall <= 1:
        parser.error("precision and recall floors must be in (0, 1]")
    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"FAIL: no labelled test folder at {folder}")
        return 2
    samples = accuracy.collect_samples(folder, args.class_id)
    mix = validate_mix(samples, args.min_enrolled, args.min_unknown)
    thresholds = [round(0.30 + i * 0.01, 2) for i in range(31)]
    rows = accuracy.sweep(samples, thresholds)
    chosen = choose_threshold(rows, args.min_precision, args.min_recall,
                              args.max_false_positives)
    passed = not mix["errors"] and chosen is not None
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "class_id": args.class_id,
        "dataset": str(folder),
        "dataset_mix": mix,
        "policy": {"min_precision": args.min_precision,
                   "min_recall": args.min_recall,
                   "max_false_positives": args.max_false_positives,
                   "max_threshold_tested": 0.60},
        "passed": passed, "chosen": chosen, "sweep": rows,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if mix["errors"]:
        for error in mix["errors"]: print("FAIL:", error)
    if chosen is None:
        print("FAIL: no threshold met the safety policy.")
        print("Improve enrolment photos or camera setup; do not hide this by loosening the threshold.")
    if not passed:
        print("Report:", report_path)
        return 1
    threshold = chosen["threshold"]
    review = min(round(threshold + 0.08, 2), 0.65)
    env_path = Path(args.env_output)
    env_path.write_text(
        "# Generated from held-out photos. Review before use.\n"
        f"MATCH_DISTANCE={threshold}\nREVIEW_DISTANCE={review}\n",
        encoding="utf-8")
    print("PASS: calibrated on", mix["enrolled"], "enrolled and",
          mix["unknown"], "stranger faces")
    print("MATCH_DISTANCE=", threshold, sep="")
    print("precision=", chosen["precision"], " recall=", chosen["recall"],
          " F1=", chosen["f1"], sep="")
    print("Report:", report_path)
    print("Config suggestion:", env_path)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
