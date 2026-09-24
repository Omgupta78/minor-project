"""End-to-end checks for the HTTP layer. No dlib required.

selftest.py covers the data layer and authtest.py covers the account rules;
neither one ever goes through a request. These checks drive the real Flask
app with a test client, because several defects only existed in the seam
between a route and the layers under it: a JSON endpoint that answered an
HTML 500, a date that went into the database unvalidated, and a photo limit
the page and the server disagreed about.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

WORK = Path(tempfile.mkdtemp(prefix="faceid-apitest-"))
os.environ["ATTENDANCE_DB"] = str(WORK / "attendance.db")
os.environ["FACES_DIR"] = str(WORK / "faces")
os.environ["PASSWORD_ROUNDS"] = "1000"   # keep the suite fast
os.environ["COOKIE_SECURE"] = "0"
os.environ["ALLOW_SIGNUP"] = "1"
os.environ["SECRET_KEY"] = "apitest-secret-key-that-is-long-enough-to-pass"
os.environ["MAX_PHOTOS_PER_SCAN"] = "3"  # deliberately not the default of 8

import numpy as np

import app as flask_app
import db

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


client = flask_app.app.test_client()

print("\n1. accounts and pages")
client.post(
    "/signup",
    data={"email": "t@example.edu", "name": "Teacher", "password": "password1"},
)
check("signing up logs the teacher in", client.get("/").status_code == 200)
client.post("/classes/add", data={"name": "CSE 3A", "subject": "DBMS"})
client.post("/classes/add", data={"name": "CSE 3B", "subject": "DBMS"})
with db.session_scope() as conn:
    classes = db.list_classes(conn)
    class_a, class_b = classes[0]["id"], classes[1]["id"]
    student_a = db.create_student(conn, "1", "Alice", class_a, None, np.random.rand(128))
    student_b = db.create_student(conn, "1", "Bob", class_b, None, np.random.rand(128))
check("two classes were created", len({class_a, class_b}) == 2)

print("\n2. the page and the server agree on the photo limit")
page = client.get("/").get_data(as_text=True)
check(
    "MAX_PHOTOS follows MAX_PHOTOS_PER_SCAN",
    "const MAX_PHOTOS = 3;" in page,
    "the JavaScript still carries its own hardcoded copy",
)

print("\n3. /api/session/confirm validates its input")
ok = client.post("/api/session/confirm", json={"class_id": class_a, "present": []})
check("a normal confirm still works", ok.status_code == 200, str(ok.get_json()))
session_id = ok.get_json()["session_id"]

bad_date = client.post(
    "/api/session/confirm", json={"class_id": class_a, "date": "not-a-date"}
)
check(
    "a malformed date is refused, not stored",
    bad_date.status_code == 400,
    f"got {bad_date.status_code}",
)
check("the refusal is JSON", bad_date.get_json() is not None)

long_period = client.post(
    "/api/session/confirm", json={"class_id": class_a, "period": "x" * 40}
)
check("an absurd period is refused", long_period.status_code == 400)

with db.session_scope() as conn:
    stored = conn.execute("SELECT date, period FROM sessions").fetchall()
check(
    "no rubbish reached the sessions table",
    all(len(r["date"]) == 10 and len(r["period"]) <= 8 for r in stored),
    str([dict(r) for r in stored]),
)

print("\n4. /api/attendance/update answers JSON on every path")
good = client.post(
    "/api/attendance/update",
    json={"session_id": session_id, "student_id": student_a, "status": "present"},
)
check("a student on the roster can be toggled", good.status_code == 200)

# The teacher owns both classes, so the ownership checks pass, but student B
# has no row in a session belonging to class A. This used to reach the
# integrity hook and come back as an HTML 500 that the page could not parse.
cross = client.post(
    "/api/attendance/update",
    json={"session_id": session_id, "student_id": student_b, "status": "present"},
)
check(
    "a student from another class is refused with 404",
    cross.status_code == 404,
    f"got {cross.status_code}",
)
check(
    "and the refusal is JSON, not an HTML error page",
    cross.get_json() is not None and "error" in (cross.get_json() or {}),
    cross.get_data(as_text=True)[:80],
)

print("\n5. face photos are private to their owner")
other = flask_app.app.test_client()
other.post(
    "/signup",
    data={"email": "other@example.edu", "name": "Other", "password": "password1"},
)
check(
    "another teacher cannot fetch an enrolment photo",
    other.get(f"/face/{student_a}").status_code == 404,
)
check(
    "another teacher cannot open the session",
    other.get(f"/records/{session_id}").status_code == 404,
)

print("\n6. the app installs: manifest, worker and offline page")
anon = flask_app.app.test_client()          # nobody signed in
for path, label in (
    ("/manifest.webmanifest", "the manifest"),
    ("/sw.js", "the service worker"),
    ("/offline", "the offline page"),
    ("/favicon.ico", "the favicon"),
):
    # These are fetched before anyone logs in. Redirecting them to the login
    # page makes the install prompt silently never appear.
    check(f"{label} is served without signing in", anon.get(path).status_code == 200,
          f"got {anon.get(path).status_code}")

manifest_body = anon.get("/manifest.webmanifest")
import json as _json
parsed = _json.loads(manifest_body.get_data(as_text=True))
check("the manifest is valid JSON with a name and icons",
      parsed.get("name") and len(parsed.get("icons", [])) >= 2, str(parsed)[:80])
check("it asks to open full-screen", parsed.get("display") == "standalone",
      str(parsed.get("display")))
check("its icons exist", all(anon.get(i["src"]).status_code == 200 for i in parsed["icons"]))
check("it is served as a manifest, not as plain text",
      "manifest" in manifest_body.headers.get("Content-Type", ""),
      manifest_body.headers.get("Content-Type"))

worker = anon.get("/sw.js")
body = worker.get_data(as_text=True)
check("the worker may control the whole app, not just /static",
      worker.headers.get("Service-Worker-Allowed") == "/",
      worker.headers.get("Service-Worker-Allowed"))
check("the build is substituted into the cache name, so a deploy invalidates it",
      "__BUILD__" not in body and flask_app.BUILD.split(" ")[0] in body)
check("the worker refuses to cache pages or API responses",
      'request.mode === "navigate"' in body and "/api/" not in body.split("SHELL")[1][:400],
      "a cached roster would leak between teachers on a shared phone")

for page in ("/login", "/signup"):
    html = anon.get(page).get_data(as_text=True)
    check(f"{page} links the manifest (it is the first page a new install sees)",
          "/manifest.webmanifest" in html)
    check(f"{page} carries the iOS home-screen tags",
          "apple-mobile-web-app-capable" in html)


print("\n7. maintenance keeps enrolled photos and removes only strays")
import maintenance

faces = Path(os.environ["FACES_DIR"])
faces.mkdir(parents=True, exist_ok=True)
(faces / "live.jpg").write_bytes(b"x")
(faces / "live_2.jpg").write_bytes(b"x")
(faces / "stray.jpg").write_bytes(b"x")
with db.session_scope() as conn:
    db.update_student(conn, student_a, photo_path="live.jpg")
    db.add_student_encoding(conn, student_a, np.random.rand(128), "live_2.jpg")
    referenced = maintenance.referenced_photos(conn)
orphans = {
    p.name
    for p in faces.rglob("*")
    if p.is_file() and p.name != ".gitkeep" and p.resolve() not in referenced
}
check(
    "an enrolled photo is not called an orphan",
    "live.jpg" not in orphans,
    "--delete-orphans would have deleted the face library",
)
check("an extra reference photo is not called an orphan", "live_2.jpg" not in orphans)
check("a genuine stray is still found", orphans == {"stray.jpg"}, str(orphans))

shutil.rmtree(WORK, ignore_errors=True)

print(f"\n{CHECKS - FAILS}/{CHECKS} checks passed.")
if FAILS:
    print(f"{FAILS} FAILED")
    sys.exit(1)
print("All API checks passed.")
