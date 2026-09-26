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


print("\n7. the server tells a phone what address to use")
import netinfo

bound_local = netinfo.startup_banner("127.0.0.1", 5000)
check(
    "bound to localhost, it says phones cannot reach it",
    "CANNOT reach" in bound_local and "HOST=0.0.0.0" in bound_local,
    "the commonest cause of 'the app cannot connect' is silent otherwise",
)
check(
    "and it does not offer an address that would not work",
    "In the phone app, type" not in bound_local,
)

bound_all = netinfo.startup_banner("0.0.0.0", 5000)
check("bound to all networks, it offers an address", "phone app" in bound_all)
check(
    "never 127.0.0.1 as the phone address (that means the phone itself)",
    not any(u.startswith("http://127.") for u in netinfo.phone_urls(5000)),
    str(netinfo.phone_urls(5000)),
)
check(
    "loopback and link-local addresses are rejected",
    not netinfo.usable("127.0.0.1") and not netinfo.usable("169.254.3.4")
    and netinfo.usable("192.168.1.14"),
)
check("the firewall, the other silent cause, is mentioned", "firewall" in bound_all)


print("\n8. the camera works over plain http, where mediaDevices does not exist")
# Reported from a phone at http://172.31.75.211:5000: "Camera error: Cannot
# read properties of undefined (reading 'getUserMedia')". navigator.mediaDevices
# is present only in a secure context, so on the LAN address the phone app uses
# it is undefined, and the old code read straight through it.
home = client.get("/").get_data(as_text=True)
check(
    "the page never reads .getUserMedia without checking mediaDevices first",
    "liveCameraAvailable()" in home
    and home.index("function liveCameraAvailable") < home.index("mediaDevices.getUserMedia"),
    "a plain-http phone gets a TypeError instead of a camera",
)
check(
    "there is a capture input to fall back to",
    'id="camera-input"' in home and 'capture="environment"' in home,
)
check(
    "openCamera uses it when there is no live camera",
    "if (!liveCameraAvailable()) { useNativeCamera(); return; }" in home,
)
check(
    "the gallery picker stays multi-select and captureless",
    'id="file-input"' in home and 'multiple' in home.split('id="file-input"')[1][:120],
    "capture silently overrides multiple, so the two inputs must stay separate",
)
check(
    "the live path asks for a usable resolution",
    "width: { ideal: 3840 }" in home,
    "the default stream is ~640x480, where a back row is unidentifiable",
)

android = Path("android/app/src/main/java/com/faceid/attendance/MainActivity.java")
if android.exists():
    java = android.read_text()
    check(
        "the WebView launches the camera itself for a capture input",
        "isCaptureEnabled()" in java and "ACTION_IMAGE_CAPTURE" in java,
        "createIntent() drops capture, so the APK would open a file browser",
    )
    check(
        "the output uri is in the clip data, not only the extra",
        "setClipData" in java and "FLAG_GRANT_WRITE_URI_PERMISSION" in java,
        "a uri in an extra carries no grant and the photo comes back empty",
    )
    manifest = Path("android/app/src/main/AndroidManifest.xml").read_text()
    check(
        "the camera is visible to resolveActivity on Android 11+",
        "<queries>" in manifest and "IMAGE_CAPTURE" in manifest,
        "package visibility hides it and capture falls back silently",
    )
    check("the capture provider is registered and not exported",
          "CaptureProvider" in manifest and 'android:exported="false"' in manifest)

    # The app's whole source sat inside a directory called "attendance", and an
    # unanchored .gitignore rule meant for a data folder matched it at depth.
    # Everything built here and nothing was in the repository.
    if Path(".git").exists():
        import subprocess
        tracked = subprocess.run(
            ["git", "ls-files", "android/app/src/main/java"],
            capture_output=True, text=True,
        ).stdout.split()
        on_disk = [str(f) for f in Path("android/app/src/main/java").rglob("*.java")]
        check(
            "every Android source file is actually in the repository",
            len(tracked) >= len(on_disk) > 0,
            f"{len(tracked)} tracked, {len(on_disk)} on disk -- a clone cannot build the app",
        )


print("\n9. /diag answers 'why is the camera not working' with facts")
d = anon.get("/diag")
check("it is reachable without signing in", d.status_code == 200, str(d.status_code))
body = d.get_data(as_text=True)
check(
    "it reports what the server's own template contains",
    "Camera opens from a label" in body and "Capture input present" in body,
    "otherwise an old download and a cached page look identical",
)
check(
    "it tells the APK apart from a browser",
    "wv" in body and "the APK" in body,
    "a WebView needs a rebuilt app, not a re-download -- different cure",
)
check(
    "it offers the real control to try",
    'capture="environment"' in body and 'for="diag-camera"' in body,
)
check("it names the build", flask_app.BUILD.split(" ")[0] in body)


print("\n10. maintenance keeps enrolled photos and removes only strays")
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
