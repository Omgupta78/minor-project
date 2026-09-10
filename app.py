"""
app.py - Face Recognition Attendance System (web app).

Teacher flow, exactly as the project brief asks for it:

    1. Pick the class and period.
    2. Click / upload one photo of the classroom.
    3. The app detects every face, identifies the students, and shows the
       result with real confidence scores for the teacher to review.
    4. The teacher confirms. Everyone recognised is marked PRESENT and the
       rest of the roster is automatically marked ABSENT.
    5. Download the full Excel report at any time.

Run:
    python app.py                      # http://127.0.0.1:5000
    FLASK_DEBUG=1 python app.py        # dev mode
"""
from __future__ import annotations

import base64
import os
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)
from werkzeug.utils import secure_filename

import db
import excel_report
import recognition

BASE_DIR = Path(__file__).resolve().parent
FACES_DIR = Path(os.environ.get("FACES_DIR", BASE_DIR / "faces"))
FACES_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# A session can be built from several photos (left half, right half, back row).
# Capped so one request cannot tie up the CPU for minutes on end.
MAX_PHOTOS_PER_SCAN = int(os.environ.get("MAX_PHOTOS_PER_SCAN", "8"))

app = Flask(__name__)
# Total request size. A session can carry several photos, and modern phone
# cameras produce 4-8 MB each, so this is a batch budget rather than per-file.
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "64"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())

db.init_db()


# --------------------------------------------------------------- helpers
def get_db() -> sqlite3.Connection:
    return db.connect()


def safe_stem(text: str) -> str:
    """Filesystem-safe stem. Prevents ../ path traversal from a form field."""
    cleaned = secure_filename(text).strip("._") or "student"
    return re.sub(r"[^A-Za-z0-9_-]+", "_", cleaned)[:60]


def parse_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@app.context_processor
def inject_globals():
    with get_db() as conn:
        classes = db.list_classes(conn)
        student_total = len(db.list_students(conn))
    return {
        "nav_classes": classes,
        "student_total": student_total,
        "today": date.today().isoformat(),
        "match_threshold": recognition.MATCH_DISTANCE,
    }


@app.errorhandler(413)
def too_large(_):
    return jsonify(
        {
            "error": f"Those photos total more than {MAX_UPLOAD_MB} MB. "
            "Send fewer at a time, or raise MAX_UPLOAD_MB."
        }
    ), 413


# ----------------------------------------------------------------- pages
@app.route("/")
def index():
    class_id = parse_int(request.args.get("class_id"))
    with get_db() as conn:
        classes = db.list_classes(conn)
        if class_id is None and classes:
            class_id = classes[0]["id"]
        students = db.list_students(conn, class_id) if class_id else []
        stats = db.dashboard_stats(conn, class_id)
        recent = db.list_sessions(conn, class_id, limit=5)
    return render_template(
        "index.html",
        active_page="dashboard",
        classes=classes,
        class_id=class_id,
        students=students,
        stats=stats,
        recent=recent,
    )


@app.route("/students_page")
def students_page():
    class_id = parse_int(request.args.get("class_id"))
    with get_db() as conn:
        classes = db.list_classes(conn)
        students = db.list_students(conn, class_id)
        summary = {s["id"]: s for s in db.attendance_summary(conn, class_id)}
    return render_template(
        "students_page.html",
        active_page="students",
        classes=classes,
        class_id=class_id,
        students=students,
        summary=summary,
    )


@app.route("/records")
def records():
    class_id = parse_int(request.args.get("class_id"))
    start = request.args.get("start") or None
    end = request.args.get("end") or None
    with get_db() as conn:
        classes = db.list_classes(conn)
        sessions = db.list_sessions(conn, class_id, start, end)
        summary = db.attendance_summary(conn, class_id, start, end)
        stats = db.dashboard_stats(conn, class_id)
    return render_template(
        "records.html",
        active_page="records",
        classes=classes,
        class_id=class_id,
        sessions=sessions,
        summary=summary,
        stats=stats,
        start=start or "",
        end=end or "",
    )


@app.route("/records/<int:session_id>")
def session_detail(session_id: int):
    with get_db() as conn:
        sess = db.get_session(conn, session_id)
        if sess is None:
            abort(404)
        rows = db.session_rows(conn, session_id)
        classes = db.list_classes(conn)
    present = sum(1 for r in rows if r["status"] in ("present", "late"))
    return render_template(
        "session_detail.html",
        active_page="records",
        classes=classes,
        session=sess,
        rows=rows,
        present=present,
        absent=len(rows) - present,
    )


# ------------------------------------------------------------- classes
@app.post("/classes/add")
def add_class():
    name = (request.form.get("name") or "").strip()
    subject = (request.form.get("subject") or "").strip()
    if not name:
        flash("Class name is required.", "error")
        return redirect(request.referrer or url_for("students_page"))
    with db.session_scope() as conn:
        class_id = db.create_class(conn, name, subject)
    flash(f"Class '{name}' is ready.", "success")
    return redirect(url_for("students_page", class_id=class_id))


# ------------------------------------------------------------ students
@app.post("/add-student")
def add_student():
    name = (request.form.get("student_name") or "").strip()
    roll_no = (request.form.get("roll_no") or "").strip()
    class_id = parse_int(request.form.get("class_id"))
    photo = request.files.get("student_photo")

    if not name or not roll_no:
        flash("Name and roll number are both required.", "error")
        return redirect(url_for("students_page", class_id=class_id))
    if photo is None or not photo.filename:
        flash("A face photo is required.", "error")
        return redirect(url_for("students_page", class_id=class_id))

    ext = Path(photo.filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        flash(f"Unsupported image type '{ext}'. Use JPG, PNG or WEBP.", "error")
        return redirect(url_for("students_page", class_id=class_id))

    filename = f"{safe_stem(roll_no)}_{safe_stem(name)}.jpg"
    target = FACES_DIR / filename

    # Normalise to JPEG (handles HEIC from iPhones when pillow-heif is present).
    try:
        from PIL import Image

        try:
            import pillow_heif

            pillow_heif.register_heif_opener()
        except Exception:
            pass
        image = Image.open(photo.stream)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.thumbnail((1200, 1200))
        image.convert("RGB").save(target, "JPEG", quality=90)
    except Exception as exc:
        flash(f"Could not read that image: {exc}", "error")
        return redirect(url_for("students_page", class_id=class_id))

    # Reject the enrolment if no face can actually be encoded, instead of
    # registering a student who could never be recognised.
    try:
        encoding = recognition.encode_face(target)
    except recognition.RecognitionUnavailable as exc:
        target.unlink(missing_ok=True)
        flash(str(exc), "error")
        return redirect(url_for("students_page", class_id=class_id))

    if encoding is None:
        target.unlink(missing_ok=True)
        flash(
            f"No face detected in the photo for {name}. "
            "Use a clear, front-facing, well-lit photo.",
            "error",
        )
        return redirect(url_for("students_page", class_id=class_id))

    try:
        with db.session_scope() as conn:
            existing = conn.execute(
                "SELECT id FROM students WHERE roll_no = ?", (roll_no,)
            ).fetchone()
            if existing:
                db.update_student(
                    conn,
                    existing["id"],
                    name=name,
                    class_id=class_id,
                    photo_path=filename,
                    encoding=encoding,
                )
                flash(f"Updated {name} ({roll_no}).", "success")
            else:
                db.create_student(conn, roll_no, name, class_id, filename, encoding)
                flash(f"Registered {name} ({roll_no}).", "success")
    except sqlite3.IntegrityError as exc:
        target.unlink(missing_ok=True)
        flash(f"Could not save student: {exc}", "error")

    return redirect(url_for("students_page", class_id=class_id))


@app.post("/students/<int:student_id>/delete")
def remove_student(student_id: int):
    with db.session_scope() as conn:
        student = db.get_student(conn, student_id)
        class_id = student["class_id"] if student else None
        if student and student["photo_path"]:
            (FACES_DIR / student["photo_path"]).unlink(missing_ok=True)
        db.delete_student(conn, student_id)
    flash("Student removed.", "success")
    return redirect(url_for("students_page", class_id=class_id))


@app.get("/face/<int:student_id>")
def student_face(student_id: int):
    with get_db() as conn:
        student = db.get_student(conn, student_id)
    if not student or not student["photo_path"]:
        abort(404)
    return send_from_directory(FACES_DIR, student["photo_path"])


# ---------------------------------------------------------------- scan
def _decode_data_url(data_url: str):
    raw = str(data_url).split(",", 1)[-1]
    try:
        return recognition.decode_image_bytes(base64.b64decode(raw))
    except Exception:
        return None


def _images_from_request() -> tuple[list[tuple[str, object]], list[str]]:
    """Collect every photo in the request, as (label, rgb_array) pairs.

    Accepts multipart uploads under "photos" (many) or "photo" (one, kept for
    backwards compatibility), and base64 data URLs under "images" or "image".

    Returns (images, skipped) so the caller can still scan the good photos and
    tell the teacher which files were unreadable, rather than failing the whole
    batch because one file was a HEIC or a PDF.
    """
    images: list[tuple[str, object]] = []
    skipped: list[str] = []

    for upload in request.files.getlist("photos") + request.files.getlist("photo"):
        if not upload or not upload.filename:
            continue
        decoded = recognition.decode_image_bytes(upload.read())
        if decoded is None:
            skipped.append(upload.filename)
        else:
            images.append((upload.filename, decoded))

    payload = request.get_json(silent=True) or {}
    data_urls = payload.get("images") or []
    if payload.get("image"):
        data_urls = list(data_urls) + [payload["image"]]
    for position, data_url in enumerate(data_urls, start=1):
        decoded = _decode_data_url(data_url)
        label = f"capture {position}"
        if decoded is None:
            skipped.append(label)
        else:
            images.append((label, decoded))

    return images, skipped


@app.post("/api/scan")
def api_scan():
    """Identify faces across one or more class photos.

    Writes NOTHING to the database. Several photos of the same room are merged
    into one roster: each student is credited with their single best sighting,
    so extra photos can only help, never double-count or downgrade anyone.
    """
    class_id = parse_int(request.form.get("class_id")) or parse_int(
        (request.get_json(silent=True) or {}).get("class_id")
    )
    if class_id is None:
        return jsonify({"error": "Select a class before scanning."}), 400

    uploads, skipped = _images_from_request()
    if not uploads:
        detail = f" Could not read: {', '.join(skipped)}." if skipped else ""
        return jsonify({"error": f"No readable image was uploaded.{detail}"}), 400
    if len(uploads) > MAX_PHOTOS_PER_SCAN:
        return jsonify(
            {
                "error": f"Up to {MAX_PHOTOS_PER_SCAN} photos per session. "
                f"You sent {len(uploads)}."
            }
        ), 400

    with get_db() as conn:
        klass = db.get_class(conn, class_id)
        if klass is None:
            return jsonify({"error": "That class no longer exists."}), 404
        _, labels, matrix = db.known_faces(conn, class_id)
        roster = db.list_students(conn, class_id)

    if not len(matrix):
        return jsonify(
            {"error": "No enrolled faces for this class. Add students first."}
        ), 400

    try:
        per_image = recognition.identify_many(
            [image for _, image in uploads], matrix, labels
        )
    except recognition.RecognitionUnavailable as exc:
        return jsonify({"error": str(exc)}), 503

    best = recognition.merge_across_images(per_image)
    stats = recognition.summarise(per_image, best)

    payload = {
        "class_id": class_id,
        "class_name": klass["name"],
        "skipped": skipped,
        "images": [
            {
                "index": index,
                "label": uploads[index][0],
                "width": int(uploads[index][1].shape[1]),
                "height": int(uploads[index][1].shape[0]),
                "faces": [face.to_dict() for face in faces],
            }
            for index, faces in enumerate(per_image)
        ],
        "roster": [
            {
                "id": s["id"],
                "name": s["name"],
                "roll_no": s["roll_no"],
                "detected": (
                    s["id"] in best and best[s["id"]].status == "matched"
                ),
                "status": best[s["id"]].status if s["id"] in best else "absent",
                "confidence": best[s["id"]].confidence if s["id"] in best else None,
                # Which photo produced the best sighting, so the teacher can
                # jump straight to the evidence for a borderline match.
                "photo": best[s["id"]].image_index + 1 if s["id"] in best else None,
            }
            for s in roster
        ],
    }
    payload.update(stats)
    return jsonify(payload)


@app.post("/api/session/confirm")
def api_confirm():
    """Commit a reviewed scan. Present students are written as present and the
    rest of the roster is written as absent, in one transaction."""
    payload = request.get_json(silent=True) or {}
    class_id = parse_int(payload.get("class_id"))
    if class_id is None:
        return jsonify({"error": "Missing class."}), 400

    on_date = payload.get("date") or date.today().isoformat()
    period = str(payload.get("period") or "1")
    taken_by = (payload.get("taken_by") or "").strip()
    total_faces = parse_int(payload.get("total_faces"), 0)

    present: dict[int, dict] = {}
    for item in payload.get("present") or []:
        sid = parse_int(item.get("student_id") if isinstance(item, dict) else item)
        if sid is None:
            continue
        info = item if isinstance(item, dict) else {}
        status = info.get("status", "present")
        if status not in ("present", "late"):
            status = "present"
        present[sid] = {
            "status": status,
            "confidence": info.get("confidence"),
            "method": "manual" if info.get("manual") else "face",
        }

    with db.session_scope() as conn:
        if db.get_class(conn, class_id) is None:
            return jsonify({"error": "That class no longer exists."}), 404
        session_id = db.create_session(
            conn, class_id, on_date, period, taken_by, total_faces
        )
        result = db.save_session_attendance(conn, session_id, class_id, present)

    result.update({"session_id": session_id, "date": on_date, "period": period})
    return jsonify(result)


@app.post("/api/attendance/update")
def api_update_status():
    """Teacher override for a single student in an existing session."""
    payload = request.get_json(silent=True) or {}
    session_id = parse_int(payload.get("session_id"))
    student_id = parse_int(payload.get("student_id"))
    status = payload.get("status")
    if None in (session_id, student_id) or status not in ("present", "absent", "late"):
        return jsonify({"error": "Invalid request."}), 400
    with db.session_scope() as conn:
        db.set_status(conn, session_id, student_id, status)
    return jsonify({"ok": True, "student_id": student_id, "status": status})


@app.post("/records/<int:session_id>/delete")
def delete_session(session_id: int):
    with db.session_scope() as conn:
        db.delete_session(conn, session_id)
    flash("Session deleted.", "success")
    return redirect(url_for("records"))


# --------------------------------------------------------------- reading
@app.get("/api/students")
def api_students():
    class_id = parse_int(request.args.get("class_id"))
    with get_db() as conn:
        rows = db.list_students(conn, class_id)
    return jsonify(
        {
            "students": [
                {
                    "id": r["id"],
                    "roll_no": r["roll_no"],
                    "name": r["name"],
                    "has_encoding": bool(r["has_encoding"]),
                }
                for r in rows
            ]
        }
    )


@app.get("/api/attendance/today")
def api_today():
    class_id = parse_int(request.args.get("class_id"))
    today = date.today().isoformat()
    with get_db() as conn:
        sessions = db.list_sessions(conn, class_id, start=today, end=today)
        records = []
        for sess in sessions:
            for row in db.session_rows(conn, sess["id"]):
                if row["status"] in ("present", "late"):
                    records.append(
                        {
                            "name": row["name"],
                            "roll_no": row["roll_no"],
                            "status": row["status"],
                            "confidence": row["confidence"],
                            "time": (row["marked_at"] or "")[-8:],
                            "period": sess["period"],
                        }
                    )
    return jsonify({"date": today, "records": records})


@app.post("/api/reload-faces")
def api_reload_faces():
    """Re-encode every enrolled photo (use after replacing files in faces/)."""
    updated, failed = 0, []
    with db.session_scope() as conn:
        for student in db.list_students(conn):
            if not student["photo_path"]:
                continue
            path = FACES_DIR / student["photo_path"]
            if not path.exists():
                failed.append(student["name"])
                continue
            try:
                encoding = recognition.encode_face(path)
            except recognition.RecognitionUnavailable as exc:
                return jsonify({"error": str(exc)}), 503
            if encoding is None:
                failed.append(student["name"])
                continue
            db.update_student(conn, student["id"], encoding=encoding)
            updated += 1
    return jsonify({"updated": updated, "failed": failed})


# ----------------------------------------------------------------- excel
@app.get("/download-excel")
def download_excel():
    class_id = parse_int(request.args.get("class_id"))
    start = request.args.get("start") or None
    end = request.args.get("end") or None
    with get_db() as conn:
        buffer = excel_report.workbook_bytes(conn, class_id, start, end)
        filename = excel_report.suggested_filename(conn, class_id)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "") == "1"
    host = os.environ.get("HOST", "127.0.0.1")  # never 0.0.0.0 with debug on
    port = int(os.environ.get("PORT", "5000"))

    # 0.0.0.0 is a bind address, not an address you can type into a browser.
    browse_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = "http://" + browse_host + ":" + str(port)

    try:
        recognition.ensure_available()
        engine = "ready"
    except Exception as exc:
        engine = "NOT INSTALLED (" + type(exc).__name__ + ")"

    print("")
    print("  Face Recognition Attendance System")
    print("  " + "-" * 48)
    print("  Open in your browser:   " + url)
    print("  Face engine:            " + engine)
    if engine != "ready":
        print("                          Every page works, but scanning is")
        print("                          disabled until dlib is installed.")
    if host == "0.0.0.0":
        print("  Reachable from other devices on your network too.")
        print("  Only do that on a network you trust.")
    print("  Press CTRL+C to stop.")
    print("")

    # The launcher scripts set OPEN_BROWSER=1. Skipped in debug mode because
    # the reloader would otherwise open a second tab on every code change.
    if os.environ.get("OPEN_BROWSER", "0") == "1" and not debug:
        import threading
        import webbrowser

        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    app.run(host=host, port=port, debug=debug)
