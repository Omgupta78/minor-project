"""Smoke test for the data + report layers (no dlib required)."""
import os
import random
from datetime import date, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE = BASE_DIR / "instance"
INSTANCE.mkdir(parents=True, exist_ok=True)

os.environ["ATTENDANCE_DB"] = str(INSTANCE / "test.db")
Path(os.environ["ATTENDANCE_DB"]).unlink(missing_ok=True)

import numpy as np

import db
import excel_report
import recognition

random.seed(7)
np.random.seed(7)

print("1. init schema")
db.init_db()

NAMES = [
    "Om Gupta", "Rakesh Sharma", "Ravi Kumar", "Sushant Rai", "Priya Singh",
    "Aman Verma", "Neha Patel", "Karan Mehta", "Divya Nair", "Rohit Yadav",
]

with db.session_scope() as conn:
    print("2. create class + students")
    cid = db.create_class(conn, "CSE 3rd Year A", "DBMS")
    for i, name in enumerate(NAMES, start=1):
        db.create_student(
            conn, f"CS-{i:03d}", name, cid, f"cs{i:03d}.jpg", np.random.rand(128)
        )
    students = db.list_students(conn, cid)
    assert len(students) == 10, len(students)
    print(f"   {len(students)} students, roll order: {[s['roll_no'] for s in students][:3]} ...")

    print("3. encoding blob round-trip")
    ids, labels, matrix = db.known_faces(conn, cid)
    assert matrix.shape == (10, 128), matrix.shape
    print(f"   matrix {matrix.shape} dtype {matrix.dtype}")

    print("4. simulate 12 sessions")
    today = date.today()
    for d in range(12):
        day = today - timedelta(days=(11 - d))
        present = {}
        for s in students:
            # student 10 is a deliberate defaulter
            chance = 0.25 if s["roll_no"] == "CS-010" else 0.9
            if random.random() < chance:
                present[s["id"]] = {
                    "confidence": round(random.uniform(0.55, 0.98), 3),
                    "method": "face",
                }
        sid = db.create_session(
            conn, cid, day.isoformat(), "1", "Prof. Sharma", len(present)
        )
        db.save_session_attendance(conn, sid, cid, present)

    print("5. re-running the same session must not duplicate rows")
    sid = db.create_session(conn, cid, today.isoformat(), "1", "Prof. Sharma", 5)
    res = db.save_session_attendance(conn, sid, cid, {students[0]["id"]: {"confidence": 0.9}})
    assert res["total"] == 10, res
    total_rows = conn.execute("SELECT COUNT(*) c FROM attendance").fetchone()["c"]
    assert total_rows == 120, total_rows
    print(f"   attendance rows = {total_rows} (12 sessions x 10 students)")

    print("6. manual override")
    db.set_status(conn, sid, students[1]["id"], "present")
    row = conn.execute(
        "SELECT status, method FROM attendance WHERE session_id=? AND student_id=?",
        (sid, students[1]["id"]),
    ).fetchone()
    assert (row["status"], row["method"]) == ("present", "manual"), tuple(row)
    print(f"   -> {row['status']} / {row['method']}")

    print("7. summary + defaulters")
    summary = db.attendance_summary(conn, cid)
    for s in summary:
        flag = "  <-- DEFAULTER" if s["defaulter"] else ""
        print(f"   {s['roll_no']}  {s['name']:<16} {s['present']:>2}/{s['held']:<2} {s['percent']:>5}%{flag}")
    assert any(s["defaulter"] for s in summary), "expected a defaulter"

    print("8. grid + detailed records")
    st, se, marks = db.attendance_grid(conn, cid)
    print(f"   grid {len(st)} students x {len(se)} sessions, {len(marks)} marks")
    assert len(marks) == 120
    details = db.detailed_records(conn, cid)
    assert len(details) == 120

    print("9. dashboard stats")
    print("  ", db.dashboard_stats(conn, cid))

    print("10. build excel workbook")
    wb = excel_report.build_workbook(conn, cid)
    assert wb.sheetnames == [
        "Summary", "Attendance Grid", "Detailed Records", "Session Log"
    ], wb.sheetnames
    out = INSTANCE / "attendance_demo.xlsx"
    wb.save(out)
    print(f"   sheets: {wb.sheetnames}")
    print(f"   saved {out} ({out.stat().st_size} bytes)")

    print("11. filtered + all-class workbooks")
    excel_report.build_workbook(conn, cid, start=(today - timedelta(days=3)).isoformat())
    excel_report.build_workbook(conn, None)
    print("   ok")

print("12. empty-database workbook must not crash")
os.environ["ATTENDANCE_DB"] = str(INSTANCE / "empty.db")
(INSTANCE / "empty.db").unlink(missing_ok=True)
import importlib
importlib.reload(db)
db.init_db()
with db.session_scope() as conn:
    excel_report.build_workbook(conn, None).save(INSTANCE / "empty.xlsx")
print("   ok")

print("13. confidence ramp is monotonic and honest")
for d in (0.20, 0.35, 0.45, 0.50, 0.55, 0.65, 0.80):
    print(f"   distance {d:.2f} -> confidence {recognition.distance_to_confidence(d):.3f}")
vals = [recognition.distance_to_confidence(d) for d in (0.2, 0.35, 0.5, 0.65, 0.8)]
assert vals == sorted(vals, reverse=True), vals

print("\nALL CHECKS PASSED")
