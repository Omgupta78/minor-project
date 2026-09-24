"""Checks for bulk roster import. No dlib, no Flask, no network.

The parsing is where bulk import goes wrong: a roll number split on its own
hyphen, a name lost because the file was called IMG_2831.jpg, a zip that
writes outside the folder it claims to be. All of that is decided before a
single face is encoded, so all of it is testable here.
"""
from __future__ import annotations

import csv
import io
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from PIL import Image

import roster_import as ri

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


WORK = Path(tempfile.mkdtemp(prefix="importtest-"))


def photo(path: Path, colour=(200, 170, 150)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (240, 240), colour).save(path, "JPEG", quality=85)
    return path


print("\n1. reading a roll number and a name out of a label")
cases = [
    ("CS-001 Ravi Kumar", "CS-001", "Ravi Kumar"),
    ("CS-001_Ravi_Kumar", "CS-001", "Ravi Kumar"),
    ("21-CSE-014 Priya  Singh", "21-CSE-014", "Priya Singh"),
    ("2024CS0091_Aarav_Mehta", "2024CS0091", "Aarav Mehta"),
    ("CS-002 Ana María Gómez", "CS-002", "Ana María Gómez"),
    ("CS-003", "CS-003", ""),
]
for label, roll, name in cases:
    got = ri.split_label(label)
    check(f"'{label}' -> roll '{roll}', name '{name}'", got == (roll, name), str(got))

check(
    "a hyphen inside a roll number is never a separator",
    ri.split_label("CS-001 Ravi")[0] == "CS-001",
    "splitting on '-' would give roll 'CS' and name '001 Ravi'",
)

print("\n2. trailing photo numbers are not part of the name")
for stem, expected in [
    ("CS-001_Ravi_Kumar_2", "CS-001_Ravi_Kumar"),
    ("CS-001_Ravi_Kumar-3", "CS-001_Ravi_Kumar"),
    ("CS-001_Ravi_Kumar 10", "CS-001_Ravi_Kumar"),
    ("CS-001_Ravi_Kumar", "CS-001_Ravi_Kumar"),
    ("CS-001_Agent_007", "CS-001_Agent"),
]:
    check(f"'{stem}' -> '{expected}'", ri.strip_photo_index(stem) == expected,
          ri.strip_photo_index(stem))

print("\n3. one folder per student")
root = WORK / "folders"
photo(root / "CS-001 Ravi Kumar" / "front.jpg")
photo(root / "CS-001 Ravi Kumar" / "left.jpg")
photo(root / "CS-002 Priya Singh" / "1.jpg")
photo(root / "CS-003 Empty Student" / "notes.txt").unlink()
(root / "CS-003 Empty Student").mkdir(parents=True, exist_ok=True)
(root / "CS-003 Empty Student" / "notes.txt").write_text("no photo here")
photo(root / "CS-004 Nested Student" / "photos" / "a.jpg")
(root / ".DS_Store").write_text("junk")

plan = ri.build_plan(root)
check("the layout is detected as one folder per student", plan.layout == "folders", plan.layout)
check("three students are ready", len(plan.usable) == 3, str([s.roll_no for s in plan.usable]))
ravi = next(s for s in plan.students if s.roll_no == "CS-001")
check("both of Ravi's photos are found", len(ravi.photos) == 2, str(len(ravi.photos)))
check("his name is read from the folder", ravi.name == "Ravi Kumar", ravi.name)
nested = next(s for s in plan.students if s.roll_no == "CS-004")
check("a photo one level deeper is still found", len(nested.photos) == 1)
empty = next(s for s in plan.students if s.roll_no == "CS-003")
check("a student with no photo is reported, not imported", not empty.usable and empty.problems)
check("macOS junk is ignored", all(".DS_Store" not in s.roll_no for s in plan.students))

print("\n4. flat files in one folder")
root = WORK / "flat"
photo(root / "CS-001_Ravi_Kumar.jpg")
photo(root / "CS-001_Ravi_Kumar_2.jpg")
photo(root / "CS-002_Priya_Singh.jpg")
photo(root / "IMG_2831.jpg")
plan = ri.build_plan(root)
check("the layout is detected as flat", plan.layout == "flat", plan.layout)
ravi = next((s for s in plan.students if s.roll_no == "CS-001"), None)
check("the two photos of one student are grouped", ravi is not None and len(ravi.photos) == 2,
      "" if ravi is None else str(len(ravi.photos)))
check("the name survives the photo number", ravi is not None and ravi.name == "Ravi Kumar",
      "" if ravi is None else ravi.name)
camera = next((s for s in plan.students if s.roll_no.upper() == "IMG"), None)
check(
    "a camera filename is flagged rather than enrolled as a student",
    camera is not None and not camera.usable,
    "IMG_2831.jpg was accepted as a real student",
)

print("\n5. a CSV manifest")
root = WORK / "manifest"
root.mkdir(parents=True, exist_ok=True)
photo(root / "photos" / "a.jpg")
photo(root / "photos" / "b.jpg")
photo(root / "photos" / "c.jpg")
(root / "students.csv").write_text(
    "Roll No,Student Name,Photo\n"
    "CS-001,Ravi Kumar,photos/a.jpg\n"
    "CS-001,Ravi Kumar,photos/b.jpg\n"
    "CS-002,\"Singh, Priya\",photos/c.jpg\n"
    ",,\n",
    encoding="utf-8",
)
plan = ri.build_plan(root)
check("the manifest is detected", plan.layout == "manifest", plan.layout)
check("two students are read", len(plan.usable) == 2, str([s.roll_no for s in plan.usable]))
ravi = next(s for s in plan.students if s.roll_no == "CS-001")
check("two rows for one roll number become two photos", len(ravi.photos) == 2, str(len(ravi.photos)))
priya = next(s for s in plan.students if s.roll_no == "CS-002")
check("a comma inside a quoted name survives", priya.name == "Singh, Priya", priya.name)
check("a blank trailing row is ignored", len(plan.students) == 2, str(len(plan.students)))

print("\n6. spreadsheet reality: BOM, odd headings, semicolon photo lists")
root = WORK / "manifest2"
root.mkdir(parents=True, exist_ok=True)
photo(root / "x1.jpg")
photo(root / "x2.jpg")
(root / "roster.csv").write_bytes(
    "﻿Enrollment No,Full Name,Images\n"
    "CS-009,Neha Patel,x1.jpg;x2.jpg\n".encode("utf-8")
)
plan = ri.build_plan(root)
check("a UTF-8 BOM does not hide the first column", len(plan.usable) == 1,
      "; ".join(p for s in plan.students for p in s.problems))
neha = plan.students[0]
check("'Enrollment No' is accepted as the roll column", neha.roll_no == "CS-009", neha.roll_no)
check("'Full Name' is accepted as the name column", neha.name == "Neha Patel", neha.name)
check("a semicolon list gives two photos", len(neha.photos) == 2, str(len(neha.photos)))

print("\n7. a manifest with no photo column matches by filename")
root = WORK / "manifest3"
root.mkdir(parents=True, exist_ok=True)
photo(root / "CS-011_someone.jpg")
photo(root / "CS-011_someone_2.jpg")
photo(root / "CS-012_other.jpg")
(root / "students.csv").write_text(
    "roll_no,name\nCS-011,Kiran Rao\nCS-012,Meera Joshi\n", encoding="utf-8"
)
plan = ri.build_plan(root)
check("both students are matched to their files", len(plan.usable) == 2,
      str([(s.roll_no, len(s.photos)) for s in plan.students]))
check("the name comes from the manifest, not the filename",
      plan.students[0].name == "Kiran Rao", plan.students[0].name)

print("\n8. problems are reported, not guessed at")
root = WORK / "bad"
root.mkdir(parents=True, exist_ok=True)
(root / "students.csv").write_text("something,else\n1,2\n", encoding="utf-8")
try:
    ri.build_plan(root)
    check("a manifest without a roll column is refused", False, "no error raised")
except ri.ImportError_ as exc:
    check("a manifest without a roll column is refused with a useful message",
          "roll" in str(exc).lower() and "name" in str(exc).lower(), str(exc))

root = WORK / "dupes"
photo(root / "CS-001 Ravi Kumar" / "a.jpg")
photo(root / "cs-001 Ravi Kumar" / "a.jpg")
plan = ri.build_plan(root)
check(
    "two roll numbers differing only in case are flagged",
    any("differ only in case" in p for s in plan.students for p in s.problems),
    str([s.problems for s in plan.students]),
)

print("\n9. zip files, including hostile ones")
root = WORK / "zips"
root.mkdir(parents=True, exist_ok=True)
good = root / "class.zip"
with zipfile.ZipFile(good, "w") as z:
    src = photo(WORK / "tmp" / "p.jpg")
    z.write(src, "CSE 3A/CS-001 Ravi Kumar/front.jpg")
    z.write(src, "CSE 3A/CS-002 Priya Singh/front.jpg")
    z.writestr("CSE 3A/__MACOSX/._junk", "junk")
unpacked = ri.unpack(good, WORK / "zipwork")
plan = ri.build_plan(unpacked)
check("a Drive-style zip imports", len(plan.usable) == 2, str([s.roll_no for s in plan.usable]))
check("the single wrapping folder is stepped into", plan.layout == "folders", plan.layout)

evil = root / "evil.zip"
with zipfile.ZipFile(evil, "w") as z:
    z.writestr("../../escaped.txt", "pwned")
try:
    ri.unpack(evil, WORK / "evilwork")
    check("a zip that writes outside its folder is refused", False, "extraction was allowed")
except ri.ImportError_ as exc:
    check("a zip that writes outside its folder is refused", "outside" in str(exc), str(exc))
check(
    "and nothing was written outside",
    not (WORK / "evilwork").joinpath("..", "escaped.txt").resolve().exists(),
)

notzip = root / "notes.txt"
notzip.write_text("hello")
try:
    ri.unpack(notzip, WORK / "w2")
    check("a non-zip file is refused", False)
except ri.ImportError_ as exc:
    check("a non-zip file is refused with advice", "zip" in str(exc).lower(), str(exc))

print("\n10. stored photo names are safe")
for roll, name in [("CS-001", "Ravi Kumar"), ("../../etc", "pa/ss wd"),
                   ("CS-2", "Ana María Gómez")]:
    generated = ri.safe_filename(roll, name, 1)
    check(
        f"'{roll}' + '{name}' -> '{generated}'",
        "/" not in generated and ".." not in generated and generated.endswith(".jpg"),
        generated,
    )
check("a second photo gets a distinct name",
      ri.safe_filename("CS-001", "Ravi", 2) != ri.safe_filename("CS-001", "Ravi", 1))

print("\n11. the plan describes itself for a dry run")
text = ri.describe(ri.build_plan(WORK / "folders"))
check("the summary names the layout and the counts",
      "folders" in text and "students ready" in text, text[:80])

shutil.rmtree(WORK, ignore_errors=True)

print(f"\n{CHECKS - FAILS}/{CHECKS} checks passed.")
if FAILS:
    print(f"{FAILS} FAILED")
    sys.exit(1)
print("All roster import checks passed.")
