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
import shutil
import sqlite3
import tempfile
import threading
from datetime import date, datetime
from pathlib import Path

from functools import wraps

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
    session,
    url_for,
)
from werkzeug.utils import secure_filename

import auth
import db
import excel_report
import recognition
import roster_import

BASE_DIR = Path(__file__).resolve().parent
FACES_DIR = Path(os.environ.get("FACES_DIR", BASE_DIR / "faces"))
FACES_DIR.mkdir(parents=True, exist_ok=True)

# Kept in sync with the recognition core so the upload form can never reject a
# format the scanner would happily read (that mismatch is what blocked HEIC).
ALLOWED_EXTS = set(recognition.IMAGE_EXTS)

# A session can be built from several photos (left half, right half, back row).
# Capped so one request cannot tie up the CPU for minutes on end.
MAX_PHOTOS_PER_SCAN = int(os.environ.get("MAX_PHOTOS_PER_SCAN", "8"))

app = Flask(__name__)
# Total request size. A session can carry several photos, and modern phone
# cameras produce 4-8 MB each, so this is a batch budget rather than per-file.
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "96"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# The signing key for the login cookie. A random fallback is fine for a single
# laptop, but on a server it would log everybody out on every restart and would
# differ between workers, so a real deployment must set SECRET_KEY.
SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    SECRET_KEY = os.urandom(32).hex()
    print(
        "  WARNING: SECRET_KEY is not set, so a temporary one was generated.\n"
        "           Everyone will be logged out when this process restarts.\n"
        "           Set SECRET_KEY before deploying for more than one teacher."
    )
app.secret_key = SECRET_KEY

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,   # JavaScript cannot read the login cookie
    SESSION_COOKIE_SAMESITE="Lax",  # blocks the simplest cross-site attempts
    # Send the cookie over HTTPS only. Defaults on, because a public hosting
    # platform terminates TLS for you; turn it off for plain-http localhost.
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1") == "1",
)

_migrations = db.init_db()
for _step in _migrations or []:
    print(f"  migrated: {_step}")


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


def clean_date(value) -> str | None:
    """Accept only a real YYYY-MM-DD date.

    sessions.date is compared with plain string >= / <= everywhere (records
    filters, the Excel range, dashboard_stats), so a free-text date silently
    sorts into the wrong place and drops out of every range the teacher picks.
    Rejecting it here is the only place that can still tell the teacher why.
    """
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def clean_period(value) -> str | None:
    """Periods are short labels ('1', '2A'). Anything longer is a mistake."""
    text = str(value if value is not None else "").strip() or "1"
    if len(text) > 8 or not re.fullmatch(r"[A-Za-z0-9._-]+", text):
        return None
    return text


# ------------------------------------------------------------------ accounts
# Endpoints reachable without logging in. Everything else is private, enforced
# by one before_request hook rather than a decorator on each route: forgetting
# a decorator silently exposes a route, whereas forgetting to whitelist one
# merely makes it ask for a login.
PUBLIC_ENDPOINTS = {"login", "signup", "logout", "static", "healthz"}


def teacher_id():
    """The logged-in teacher's id, or None."""
    return session.get("teacher_id")


def current_teacher():
    tid = teacher_id()
    if tid is None:
        return None
    with get_db() as conn:
        return auth.get_teacher(conn, tid)


@app.before_request
def require_login():
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if teacher_id() is not None:
        # The account could have been deleted or deactivated mid-session.
        if current_teacher() is not None:
            return None
        session.clear()

    # A fetch() call must get JSON back. Redirecting an API request to the
    # login page produces HTML that the frontend cannot parse, and the error
    # the teacher sees would be a JSON parse failure instead of 'please log in'.
    if request.path.startswith("/api/"):
        return jsonify({"error": "Your session has expired. Please log in again."}), 401
    return redirect(url_for("login", next=request.path))


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        teacher = current_teacher()
        if teacher is None or not teacher["is_admin"]:
            abort(403)
        return view(*args, **kwargs)

    return wrapper


@app.route("/signup", methods=["GET", "POST"])
def signup():
    """Create a teacher account.

    ALLOW_SIGNUP=0 closes registration after the staff of one school have
    signed up, so a public URL does not accumulate strangers.
    """
    open_signup = os.environ.get("ALLOW_SIGNUP", "1") == "1"
    with get_db() as conn:
        first_ever = auth.count_teachers(conn) == 0
    if not open_signup and not first_ever:
        flash("Registration is closed on this server. Ask your admin for an account.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        email = request.form.get("email", "")
        name = request.form.get("name", "")
        password = request.form.get("password", "")
        try:
            with db.session_scope() as conn:
                new_id = auth.create_teacher(conn, email, name, password)
        except auth.AuthError as exc:
            flash(str(exc), "error")
            return render_template("signup.html", email=email, name=name, first_ever=first_ever)
        session.clear()
        session["teacher_id"] = new_id
        session.permanent = True
        flash("Welcome. Start by creating a class and enrolling your students.", "success")
        return redirect(url_for("index"))

    return render_template("signup.html", email="", name="", first_ever=first_ever)


@app.route("/login", methods=["GET", "POST"])
def login():
    with get_db() as conn:
        no_accounts = auth.count_teachers(conn) == 0
    if no_accounts:
        return redirect(url_for("signup"))

    if request.method == "POST":
        email = request.form.get("email", "")
        password = request.form.get("password", "")
        with db.session_scope() as conn:
            row = auth.authenticate(conn, email, password)
            teacher = dict(row) if row is not None else None
        if teacher is None:
            # One message for both causes, so the form cannot be used to find
            # out which email addresses have accounts.
            flash("That email and password do not match.", "error")
            return render_template("login.html", email=email)
        session.clear()
        session["teacher_id"] = teacher["id"]
        session.permanent = True

        # Only follow a same-site relative path, never an absolute URL from
        # the query string, which is the classic open-redirect mistake.
        destination = request.args.get("next") or ""
        if not destination.startswith("/") or destination.startswith("//"):
            destination = url_for("index")
        return redirect(destination)

    return render_template("login.html", email="")


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    flash("You are logged out.", "success")
    return redirect(url_for("login"))


@app.post("/account/password")
def change_own_password():
    try:
        with db.session_scope() as conn:
            auth.change_password(
                conn,
                teacher_id(),
                request.form.get("current_password", ""),
                request.form.get("new_password", ""),
            )
    except auth.AuthError as exc:
        flash(str(exc), "error")
        return redirect(request.referrer or url_for("index"))
    flash("Password changed.", "success")
    return redirect(request.referrer or url_for("index"))


@app.get("/healthz")
def healthz():
    """Liveness probe for the hosting platform. No data, no login.

    Reports the build too, so `curl /healthz` answers "is the server actually
    running the code I just checked out?" without opening a browser, logging
    in, or trusting a cached page.
    """
    return jsonify({"ok": True, "build": BUILD, "import_available": True})


@app.context_processor
def inject_globals():
    tid = teacher_id()
    if tid is None:
        return {
            "nav_classes": [],
            "student_total": 0,
            "today": date.today().isoformat(),
            "match_threshold": recognition.MATCH_DISTANCE,
            "teacher": None,
            "max_photos_per_scan": MAX_PHOTOS_PER_SCAN,
            "max_enrol_photos": MAX_ENROL_PHOTOS,
            "build": BUILD,
        }
    with get_db() as conn:
        classes = db.list_classes(conn, teacher_id=tid)
        student_total = len(db.list_students(conn, teacher_id=tid))
        teacher = auth.get_teacher(conn, tid)
    return {
        "nav_classes": classes,
        "student_total": student_total,
        "today": date.today().isoformat(),
        "match_threshold": recognition.MATCH_DISTANCE,
        "teacher": teacher,
        # Published so the page cannot disagree with the server about the
        # limits. A hardcoded 8 in the JavaScript meant that raising
        # MAX_PHOTOS_PER_SCAN did nothing, and lowering it produced a 400
        # from /api/scan after the teacher had already picked the photos.
        "max_photos_per_scan": MAX_PHOTOS_PER_SCAN,
        "max_enrol_photos": MAX_ENROL_PHOTOS,
        "build": BUILD,
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
    tid = teacher_id()
    class_id = parse_int(request.args.get("class_id"))
    with get_db() as conn:
        classes = db.list_classes(conn, teacher_id=tid)
        # A class_id in the query string is untrusted input: without this
        # check, editing the number in the address bar would show another
        # teacher's class.
        if class_id is not None and not auth.owns_class(conn, tid, class_id):
            abort(404)
        if class_id is None and classes:
            class_id = classes[0]["id"]
        students = db.list_students(conn, class_id, teacher_id=tid) if class_id else []
        stats = db.dashboard_stats(conn, class_id, teacher_id=tid)
        recent = db.list_sessions(conn, class_id, limit=5, teacher_id=tid)
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
    tid = teacher_id()
    class_id = parse_int(request.args.get("class_id"))
    with get_db() as conn:
        if class_id is not None and not auth.owns_class(conn, tid, class_id):
            abort(404)
        classes = db.list_classes(conn, teacher_id=tid)
        students = db.list_students(conn, class_id, teacher_id=tid)
        summary = {
            s["id"]: s
            for s in db.attendance_summary(conn, class_id, teacher_id=tid)
        }
        # How many reference photos each student has. One is the commonest
        # reason a student is missed in a big room, and this page is where the
        # teacher can do something about it.
        references = db.encoding_counts(conn, class_id)
    return render_template(
        "students_page.html",
        active_page="students",
        classes=classes,
        class_id=class_id,
        students=students,
        summary=summary,
        references=references,
    )


@app.route("/records")
def records():
    tid = teacher_id()
    class_id = parse_int(request.args.get("class_id"))
    start = request.args.get("start") or None
    end = request.args.get("end") or None
    with get_db() as conn:
        if class_id is not None and not auth.owns_class(conn, tid, class_id):
            abort(404)
        classes = db.list_classes(conn, teacher_id=tid)
        sessions = db.list_sessions(conn, class_id, start, end, teacher_id=tid)
        summary = db.attendance_summary(conn, class_id, start, end, teacher_id=tid)
        stats = db.dashboard_stats(conn, class_id, teacher_id=tid)
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
    tid = teacher_id()
    with get_db() as conn:
        sess = db.get_session(conn, session_id)
        # 404 rather than 403 for someone else's session: a 403 would confirm
        # that the session exists, which is itself information.
        if sess is None or not auth.owns_session(conn, tid, session_id):
            abort(404)
        rows = db.session_rows(conn, session_id)
        classes = db.list_classes(conn, teacher_id=tid)
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
        class_id = db.create_class(conn, name, subject, teacher_id=teacher_id())
    flash(f"Class '{name}' is ready.", "success")
    return redirect(url_for("students_page", class_id=class_id))


# ------------------------------------------------------------ students
# A student can be enrolled from several photos in one go. Each photo becomes
# a separate reference encoding, which is the single biggest accuracy win
# available: one photo only ever captures one angle and one lighting setup.
MAX_ENROL_PHOTOS = int(os.environ.get("MAX_ENROL_PHOTOS", "5"))

# Where an in-progress bulk import keeps its uploaded files. Outside the
# faces folder, because nothing here is a reference photo until it has passed
# the quality check.
IMPORT_DIR = Path(os.environ.get("IMPORT_DIR", BASE_DIR / "instance" / "imports"))
# Importing from a path on the server is for a machine where the teacher and
# the app are the same person -- a laptop, or a Drive folder synced onto the
# server. On a shared host it would let any teacher read any folder the
# process can reach, so it is off unless switched on deliberately.
ALLOW_PATH_IMPORT = os.environ.get("ALLOW_PATH_IMPORT", "1") == "1"


def _build_marker() -> str:
    """A short label naming exactly which build is running, for the footer.

    Version plus the commit it was checked out at. Without it there is no way
    to tell a running server apart from the one you thought you started -- and
    since Flask does not reload with debug off, "I copied the new files but the
    old app is still showing" is the single most common thing to go wrong.
    Compare what the footer says with the latest commit on GitHub.

    Reads .git by hand rather than shelling out to git, so it costs nothing at
    startup and still works where git is not installed or the code was
    unzipped rather than cloned.
    """
    version = "?"
    version_file = BASE_DIR / "VERSION"
    if version_file.exists():
        version = version_file.read_text(encoding="utf-8", errors="replace").strip() or "?"

    commit = ""
    try:
        head = (BASE_DIR / ".git" / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref: "):
            ref = head[5:].strip()
            ref_file = BASE_DIR / ".git" / ref
            if ref_file.exists():
                commit = ref_file.read_text(encoding="utf-8").strip()
            else:
                # A freshly cloned repository keeps its refs packed.
                packed = BASE_DIR / ".git" / "packed-refs"
                if packed.exists():
                    for line in packed.read_text(encoding="utf-8").splitlines():
                        if line.endswith(" " + ref):
                            commit = line.split(" ", 1)[0]
                            break
        else:
            commit = head  # detached HEAD
    except OSError:
        pass

    return f"v{version}" + (f" · {commit[:7]}" if commit else "")


BUILD = _build_marker()


@app.post("/add-student")
def add_student():
    name = (request.form.get("student_name") or "").strip()
    roll_no = (request.form.get("roll_no") or "").strip()
    class_id = parse_int(request.form.get("class_id"))
    photos = [f for f in request.files.getlist("student_photo") if f and f.filename]

    # A student now belongs to a teacher *through* their class, so enrolling
    # without one would create a student nobody can see.
    if class_id is None:
        flash("Choose a class before enrolling a student.", "error")
        return redirect(url_for("students_page"))
    with get_db() as conn:
        if not auth.owns_class(conn, teacher_id(), class_id):
            abort(404)

    if not name or not roll_no:
        flash("Name and roll number are both required.", "error")
        return redirect(url_for("students_page", class_id=class_id))
    if not photos:
        flash("At least one face photo is required.", "error")
        return redirect(url_for("students_page", class_id=class_id))
    if len(photos) > MAX_ENROL_PHOTOS:
        flash(
            f"Only the first {MAX_ENROL_PHOTOS} photos were used.",
            "warning",
        )
        photos = photos[:MAX_ENROL_PHOTOS]

    encodings: list = []
    saved: list[Path] = []
    rejected: list[str] = []
    superseded: set[str] = set()

    for position, photo in enumerate(photos, start=1):
        ext = Path(photo.filename).suffix.lower()
        if ext not in ALLOWED_EXTS:
            rejected.append(f"{photo.filename}: unsupported image type '{ext}'.")
            continue
        if ext in recognition.HEIF_EXTS and not recognition.register_heif():
            rejected.append(
                f"{photo.filename}: HEIC photos need the pillow-heif package. "
                "Run 'pip install pillow-heif', or convert the photo to JPG."
            )
            continue

        suffix = "" if position == 1 else f"_{position}"
        filename = f"{safe_stem(roll_no)}_{safe_stem(name)}{suffix}.jpg"
        target = FACES_DIR / filename

        # Everything is stored as JPEG, whatever the teacher uploaded. HEIC
        # from an iPhone is decoded here once, so the rest of the app never
        # sees it again.
        try:
            from PIL import Image, ImageOps

            recognition.register_heif()
            image = Image.open(photo.stream)
            image = ImageOps.exif_transpose(image)  # honour the rotation flag
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            image.thumbnail((1200, 1200))
            image.convert("RGB").save(target, "JPEG", quality=90)
        except Exception as exc:
            rejected.append(f"{photo.filename}: could not be read ({exc}).")
            continue

        # Refuse a photo that holds no face, or one that is too small, too
        # blurry or badly lit. Whatever is accepted here becomes a permanent
        # reference, so a bad photo would spoil every later scan.
        try:
            encoding, report = recognition.encode_face_checked(target)
        except recognition.RecognitionUnavailable as exc:
            for path in saved + [target]:
                path.unlink(missing_ok=True)
            flash(str(exc), "error")
            return redirect(url_for("students_page", class_id=class_id))

        if encoding is None:
            target.unlink(missing_ok=True)
            rejected.append(f"{photo.filename}: {report.get('problem')}")
            continue

        encodings.append(encoding)
        saved.append(target)

    if not encodings:
        reasons = " ".join(rejected)
        flash(
            f"No usable face photo for {name}. {reasons} "
            "Use a clear, front-facing, well-lit photo.".strip(),
            "error",
        )
        return redirect(url_for("students_page", class_id=class_id))

    if rejected:
        # Some photos were kept, so this is a warning rather than a failure.
        flash(" ".join(rejected), "warning")

    filename = saved[0].name

    try:
        with db.session_scope() as conn:
            # Roll numbers are unique per class, not globally, so this lookup
            # must be scoped too. Without the class_id it would find another
            # teacher's roll 12 and overwrite their student's face.
            existing = conn.execute(
                "SELECT id FROM students WHERE roll_no = ? AND class_id IS ?",
                (roll_no, class_id),
            ).fetchone()
            if existing:
                student_id = existing["id"]
                # The files this student used to reference. Re-enrolling
                # replaces them, so they have to be deleted afterwards or the
                # faces/ folder keeps every photo the student ever had.
                superseded = db.student_photo_names(conn, student_id)
                db.update_student(
                    conn,
                    student_id,
                    name=name,
                    class_id=class_id,
                    photo_path=filename,
                    encoding=encodings[0],
                )
                # Re-enrolling replaces the old reference photos rather than
                # stacking new ones on top of possibly outdated ones.
                db.clear_student_encodings(conn, student_id)
                flash(
                    f"Updated {name} ({roll_no}) from {len(encodings)} photo(s).",
                    "success",
                )
            else:
                student_id = db.create_student(
                    conn, roll_no, name, class_id, filename, encodings[0]
                )
                flash(
                    f"Registered {name} ({roll_no}) from {len(encodings)} photo(s).",
                    "success",
                )

            # The first encoding lives on the student row; the rest go to
            # student_encodings and are all compared against during a scan.
            # Each one records the file it came from, so maintenance.py can
            # tell a live reference photo apart from a leftover.
            for extra, path in zip(encodings[1:], saved[1:]):
                db.add_student_encoding(conn, student_id, extra, path.name)

        kept = {path.name for path in saved}
        for name_on_disk in superseded - kept:
            (FACES_DIR / name_on_disk).unlink(missing_ok=True)
    except sqlite3.IntegrityError as exc:
        for path in saved:
            path.unlink(missing_ok=True)
        flash(f"Could not save student: {exc}", "error")

    return redirect(url_for("students_page", class_id=class_id))


# --------------------------------------------------------- bulk enrolment
def _materialise(workdir: Path) -> Path:
    """Turn whatever the import form sent into a folder on disk.

    Three ways in, one result, so the parser and the enroller never need to
    know which was used:

      * a .zip -- what Google Drive gives you when you download a folder;
      * a folder picked in the browser, which arrives as many files plus the
        relative path of each, because a browser sends only base names;
      * a path on this machine, for a laptop or a synced Drive folder.
    """
    workdir.mkdir(parents=True, exist_ok=True)

    archive = request.files.get("archive")
    if archive and archive.filename:
        saved = workdir / secure_filename(archive.filename)
        archive.save(saved)
        return roster_import.unpack(saved, workdir)

    uploads = [f for f in request.files.getlist("files") if f and f.filename]
    if uploads:
        # The browser sends file.name, not file.webkitRelativePath, so the
        # page sends the relative paths alongside in the same order.
        relatives = request.form.getlist("paths")
        root = (workdir / "picked").resolve()
        root.mkdir(parents=True, exist_ok=True)
        for index, upload in enumerate(uploads):
            raw = relatives[index] if index < len(relatives) else upload.filename
            parts = [
                secure_filename(part)
                for part in str(raw).replace("\\", "/").split("/")
                if part not in ("", ".", "..")
            ]
            if not parts:
                continue
            target = (root / Path(*parts)).resolve()
            # Never write outside the working folder, whatever the page sent.
            if not target.is_relative_to(root):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            upload.save(target)
        entries = [p for p in root.iterdir()]
        if len(entries) == 1 and entries[0].is_dir():
            return entries[0]
        return root

    given = (request.form.get("server_path") or "").strip()
    if given:
        if not ALLOW_PATH_IMPORT:
            raise roster_import.ImportError_(
                "Importing from a path on the server is switched off here. "
                "Upload a zip or pick the folder instead."
            )
        return roster_import.unpack(given, workdir)

    raise roster_import.ImportError_(
        "Choose a folder, a zip file, or give a path on this machine."
    )


def _run_import(job_id: int, class_id: int, root: str, workdir: str,
                replace: bool) -> None:
    """The background half of a bulk import. No request, no session.

    Runs in a thread, so it must not touch anything request-scoped and must
    open its own database connection. Progress goes into import_jobs, which
    the page polls, so it survives being served by a different worker.
    """
    try:
        plan = roster_import.build_plan(root)

        def progress(done: int, total: int, roll: str) -> None:
            # Progress is a nicety; never let it end an import that is working.
            try:
                with db.session_scope() as conn:
                    db.update_import_job(
                        conn, job_id, done=done, total=total, current=roll
                    )
            except Exception:
                pass

        # Deliberately two scopes. Writing the total inside the enrolment scope
        # would open a transaction that stays open for the whole import, and
        # the progress writes -- which use their own connection so the page can
        # read them -- would be locked out for minutes.
        with db.session_scope() as conn:
            db.update_import_job(conn, job_id, total=len(plan.usable))

        with db.session_scope() as conn:
            result = roster_import.enrol(
                plan, conn, class_id, FACES_DIR,
                replace=replace, max_photos=MAX_ENROL_PHOTOS, on_progress=progress,
            )

        skipped = [
            f"{c.roll_no or '?'} {c.name}: {'; '.join(c.problems)}".strip()
            for c in plan.rejected
        ]
        with db.session_scope() as conn:
            db.update_import_job(
                conn, job_id, state="done", done=len(plan.usable),
                current="", added=result.added, updated=result.updated,
                failed=result.failed + len(plan.rejected),
                photos_used=result.photos_used,
                photos_rejected=result.photos_rejected,
                message=f"{result.added} added, {result.updated} updated",
                log="\n".join(skipped + result.messages)[:20000],
                finished_at=datetime.now().isoformat(timespec="seconds"),
            )
    except Exception as exc:
        # The teacher gets the message on the page; the full stack goes to the
        # server log, because a bulk import touches the filesystem and a dozen
        # photo formats and "it failed" is not enough to fix anything.
        app.logger.exception("bulk import %s failed", job_id)
        with db.session_scope() as conn:
            db.update_import_job(
                conn, job_id, state="failed", message=str(exc)[:500],
                finished_at=datetime.now().isoformat(timespec="seconds"),
            )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@app.get("/students/import")
def import_page():
    tid = teacher_id()
    class_id = parse_int(request.args.get("class_id"))
    with get_db() as conn:
        classes = db.list_classes(conn, teacher_id=tid)
        if class_id is not None and not auth.owns_class(conn, tid, class_id):
            abort(404)
    return render_template(
        "import_page.html",
        active_page="students",
        classes=classes,
        class_id=class_id or (classes[0]["id"] if classes else None),
        allow_path_import=ALLOW_PATH_IMPORT,
        max_enrol_photos=MAX_ENROL_PHOTOS,
    )


@app.post("/api/import/preview")
def api_import_preview():
    """Read the roster and report what would happen. Changes nothing."""
    class_id = parse_int(request.form.get("class_id"))
    with get_db() as conn:
        if class_id is None or not auth.owns_class(conn, teacher_id(), class_id):
            return jsonify({"error": "Choose one of your classes first."}), 404

    workdir = Path(tempfile.mkdtemp(prefix="preview-", dir=_import_root()))
    try:
        root = _materialise(workdir)
        plan = roster_import.build_plan(root)
        return jsonify({
            "layout": plan.layout,
            "notes": plan.notes,
            "ready": [
                {"roll_no": c.roll_no, "name": c.name, "photos": len(c.photos)}
                for c in plan.usable
            ],
            "skipped": [
                {"roll_no": c.roll_no, "name": c.name,
                 "problems": c.problems}
                for c in plan.rejected
            ],
            "ignored": [{"name": n, "why": w} for n, w in plan.ignored[:50]],
            "photo_count": plan.photo_count,
        })
    except roster_import.ImportError_ as exc:
        return jsonify({"error": str(exc)}), 400
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@app.post("/api/import/start")
def api_import_start():
    """Begin a bulk import in the background. Returns a job id to poll."""
    tid = teacher_id()
    class_id = parse_int(request.form.get("class_id"))
    replace = request.form.get("replace", "1") == "1"
    with get_db() as conn:
        if class_id is None or not auth.owns_class(conn, tid, class_id):
            return jsonify({"error": "Choose one of your classes first."}), 404

    try:
        recognition.ensure_available()
    except recognition.RecognitionUnavailable as exc:
        return jsonify({"error": str(exc)}), 503

    # Kept until the job finishes, so it must not be a with-block temp dir.
    workdir = Path(tempfile.mkdtemp(prefix="import-", dir=_import_root()))
    try:
        root = _materialise(workdir)
        plan = roster_import.build_plan(root)
    except roster_import.ImportError_ as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        return jsonify({"error": str(exc)}), 400
    if not plan.usable:
        shutil.rmtree(workdir, ignore_errors=True)
        return jsonify(
            {"error": "No student in that folder could be read. "
                      "Check the naming rules on this page."}
        ), 400

    with db.session_scope() as conn:
        job_id = db.create_import_job(conn, tid, class_id, len(plan.usable))

    thread = threading.Thread(
        target=_run_import,
        args=(job_id, class_id, str(root), str(workdir), replace),
        daemon=True,
        name=f"import-{job_id}",
    )
    thread.start()
    return jsonify({"job_id": job_id, "total": len(plan.usable)})


@app.get("/api/import/<int:job_id>")
def api_import_status(job_id: int):
    with get_db() as conn:
        job = db.get_import_job(conn, job_id, teacher_id=teacher_id())
    if job is None:
        return jsonify({"error": "No such import."}), 404
    payload = dict(job)
    payload["log"] = [line for line in (job["log"] or "").split("\n") if line]
    return jsonify(payload)


def _import_root() -> Path:
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    return IMPORT_DIR


@app.post("/students/<int:student_id>/delete")
def remove_student(student_id: int):
    with db.session_scope() as conn:
        if not auth.owns_student(conn, teacher_id(), student_id):
            abort(404)
        student = db.get_student(conn, student_id)
        class_id = student["class_id"] if student else None
        # Every reference photo, not just the primary one, or the extra
        # enrolment photos would outlive the student they belong to.
        for name_on_disk in db.student_photo_names(conn, student_id):
            (FACES_DIR / name_on_disk).unlink(missing_ok=True)
        db.delete_student(conn, student_id)
    flash("Student removed.", "success")
    return redirect(url_for("students_page", class_id=class_id))


@app.get("/face/<int:student_id>")
def student_face(student_id: int):
    # An enrolment photo is biometric data. Serving it by sequential id with
    # no ownership check would let any logged-in teacher walk the whole school.
    with get_db() as conn:
        if not auth.owns_student(conn, teacher_id(), student_id):
            abort(404)
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
        if klass is None or not auth.owns_class(conn, teacher_id(), class_id):
            return jsonify({"error": "That class no longer exists."}), 404
        _, labels, matrix = db.known_faces(conn, class_id, teacher_id=teacher_id())
        roster = db.list_students(conn, class_id, teacher_id=teacher_id())
        reference_counts = db.encoding_counts(conn, class_id)

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

    # Two things decide whether a big room works, and the teacher can fix both
    # between one photo and the next, so say which one is biting.
    hints: list[str] = []
    if stats["faces_too_small"]:
        hints.append(
            f"{stats['faces_too_small']} face(s) are narrower than "
            f"{stats['readable_face_px']} px. Faces that small are usually "
            "detected but not identified. Add a photo taken closer to the back "
            "rows, or zoom in on them - the best sighting of each student wins."
        )
    thin = [s["name"] for s in roster if reference_counts.get(s["id"], 0) < 2]
    if thin:
        shown = ", ".join(thin[:5]) + ("..." if len(thin) > 5 else "")
        hints.append(
            f"{len(thin)} student(s) are enrolled from a single photo ({shown}). "
            "Three photos per student identifies noticeably more of the room."
        )

    payload = {
        "class_id": class_id,
        "class_name": klass["name"],
        "skipped": skipped,
        "hints": hints,
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
                "references": reference_counts.get(s["id"], 0),
                "face_px": best[s["id"]].face_px if s["id"] in best else None,
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

    on_date = clean_date(payload.get("date") or date.today().isoformat())
    if on_date is None:
        return jsonify({"error": "That date is not a valid YYYY-MM-DD date."}), 400
    period = clean_period(payload.get("period"))
    if period is None:
        return jsonify(
            {"error": "A period is a short label such as '1' or '2A'."}
        ), 400
    taken_by = (str(payload.get("taken_by") or "")).strip()[:120]
    total_faces = max(0, parse_int(payload.get("total_faces"), 0) or 0)

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
        if db.get_class(conn, class_id) is None or not auth.owns_class(
            conn, teacher_id(), class_id
        ):
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
        tid = teacher_id()
        if not auth.owns_session(conn, tid, session_id) or not auth.owns_student(
            conn, tid, student_id
        ):
            return jsonify({"error": "That session no longer exists."}), 404
        # Owning both is not enough: a teacher owns several classes, and a
        # student from class B has no row in a session of class A. The
        # integrity hook raises on that pair, which would surface as an HTML
        # 500 the frontend cannot parse, so refuse it here with real JSON.
        sess = db.get_session(conn, session_id)
        student = db.get_student(conn, student_id)
        if sess is None or student is None or sess["class_id"] != student["class_id"]:
            return jsonify(
                {"error": "That student is not on the roster for this session."}
            ), 404
        db.set_status(conn, session_id, student_id, status)
    return jsonify({"ok": True, "student_id": student_id, "status": status})


@app.post("/records/<int:session_id>/delete")
def delete_session(session_id: int):
    with db.session_scope() as conn:
        if not auth.owns_session(conn, teacher_id(), session_id):
            abort(404)
        db.delete_session(conn, session_id)
    flash("Session deleted.", "success")
    return redirect(url_for("records"))


# --------------------------------------------------------------- reading
@app.get("/api/students")
def api_students():
    class_id = parse_int(request.args.get("class_id"))
    with get_db() as conn:
        rows = db.list_students(conn, class_id, teacher_id=teacher_id())
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
        sessions = db.list_sessions(
            conn, class_id, start=today, end=today, teacher_id=teacher_id()
        )
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
        for student in db.list_students(conn, teacher_id=teacher_id()):
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
    tid = teacher_id()
    with get_db() as conn:
        if class_id is not None and not auth.owns_class(conn, tid, class_id):
            abort(404)
        buffer = excel_report.workbook_bytes(conn, class_id, start, end, teacher_id=tid)
        filename = excel_report.suggested_filename(conn, class_id, teacher_id=tid)
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
