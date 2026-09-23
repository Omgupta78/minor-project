"""Render every template with real data to catch Jinja errors before deploy."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE = BASE_DIR / "instance"
RENDER_DIR = BASE_DIR / "render"

# Renders the templates against whatever selftest.py left in instance/test.db.
os.environ["ATTENDANCE_DB"] = str(INSTANCE / "test.db")

from jinja2 import Environment, FileSystemLoader

import db

env = Environment(loader=FileSystemLoader(str(BASE_DIR / "templates")))
env.globals["get_flashed_messages"] = lambda **k: [
    ("success", "Student added successfully."),
    ("error", "No face detected in that photo."),
    ("warning", "One photo was rejected and the rest were kept."),
]
# Static assets must resolve to real files, otherwise the screenshots below
# render unstyled and silently "pass". Relative paths work from /data/render.
def _url_for(endpoint, **kw):
    if endpoint == "static":
        return "static/" + kw["filename"]
    return "#"


env.globals["url_for"] = _url_for

FAKE = ("94.2", "94%", "CS-2024", "2024000")

RENDER_DIR.mkdir(parents=True, exist_ok=True)

with db.session_scope() as conn:
    classes = db.list_classes(conn)
    cid = classes[0]["id"]
    students = db.list_students(conn, cid)
    summary = db.attendance_summary(conn, cid)
    sessions = db.list_sessions(conn, cid)
    stats = db.dashboard_stats(conn, cid)
    sid = sessions[0]["id"]
    sess = db.get_session(conn, sid)
    rows = db.session_rows(conn, sid)

    # The nav shows the logged-in teacher's name and a logout button, so the
    # templates must be rendered with a teacher present as well as without.
    teacher = {"id": 1, "name": "Prof. A. Sharma", "email": "a.sharma@school.edu",
               "is_admin": 1}

    base = dict(
        active_page="",
        match_threshold=0.50,
        student_total=len(students),
        nav_classes=classes,
        classes=classes,
        class_id=cid,
        today="2026-09-09",
        teacher=teacher,
        max_photos_per_scan=8,
        max_enrol_photos=5,
    )

    cases = [
        ("index.html", dict(base, active_page="dashboard", students=students,
                            stats=stats, recent=sessions[:5])),
        ("students_page.html", dict(base, active_page="students", students=students,
                                    summary={s["id"]: s for s in summary},
                                    references=db.encoding_counts(conn, cid))),
        ("records.html", dict(base, active_page="records", sessions=sessions,
                              summary=summary, stats=stats,
                              start="2026-08-01", end="2026-09-09")),
        ("session_detail.html", dict(base, active_page="records", session=sess, rows=rows,
                                     present=sum(1 for r in rows if r["status"] == "present"),
                                     absent=sum(1 for r in rows if r["status"] == "absent"))),
    ]

    for name, ctx in cases:
        html = env.get_template(name).render(**ctx)
        with open(RENDER_DIR / name, "w") as fh:
            fh.write(html)
        leaks = [t for t in FAKE if t in html]
        assert "{{" not in html, f"{name}: an unrendered Jinja expression survived"
        if name == "index.html":
            # A missing context value would render as "const MAX_PHOTOS = ;"
            # which is a syntax error that takes the whole page's JS with it.
            assert "const MAX_PHOTOS = 8;" in html, "photo limit did not render"
        print(f"OK  {name:<22} {len(html):>6} bytes   fake-data leaks: {leaks or 'none'}")

    # Empty-workspace states must not crash either.
    empty = dict(base, classes=[], nav_classes=[], class_id=None, students=[],
                 student_total=0, stats=dict(students=0, sessions_today=0,
                 present_today=0, total_sessions=0, avg_percent=0.0, defaulters=0))
    h = env.get_template("index.html").render(**dict(empty, active_page="dashboard", recent=[]))
    with open(RENDER_DIR / "index_empty.html", "w") as fh:
        fh.write(h)
    print(f"OK  index.html (empty)     {len(h):>6} bytes")

    h = env.get_template("students_page.html").render(**dict(empty, active_page="students", summary={}, references={}))
    with open(RENDER_DIR / "students_empty.html", "w") as fh:
        fh.write(h)
    print(f"OK  students (empty)       {len(h):>6} bytes")

    h = env.get_template("records.html").render(**dict(empty, active_page="records",
            sessions=[], summary=[], start="", end=""))
    with open(RENDER_DIR / "records_empty.html", "w") as fh:
        fh.write(h)
    print(f"OK  records (empty)        {len(h):>6} bytes")

    # The login and signup pages stand alone, and are the first thing every
    # teacher in the world sees, so a Jinja error there locks everyone out.
    class _Args:
        @staticmethod
        def get(key, default=None):
            return {"next": "/records"}.get(key, default)

    env.globals["request"] = type("_Req", (), {"args": _Args})()

    for name, ctx in (
        ("login.html", dict(email="a.sharma@school.edu")),
        ("signup.html", dict(email="", name="", first_ever=True)),
        ("signup_closed.html", dict(email="a@b.edu", name="A B", first_ever=False)),
    ):
        template = "signup.html" if name.startswith("signup") else name
        h = env.get_template(template).render(**ctx)
        with open(RENDER_DIR / name, "w") as fh:
            fh.write(h)
        # A login form that posts nowhere, or a page whose stylesheet did not
        # resolve, is broken in a way that still "renders".
        assert 'name="password"' in h, f"{name}: no password field"
        assert "static/app.css" in h, f"{name}: stylesheet not linked"
        print(f"OK  {name:<22} {len(h):>6} bytes")

    # Nobody logged in: the nav must not offer a logout button or a name.
    h = env.get_template("index.html").render(
        **dict(base, active_page="dashboard", students=students, stats=stats,
               recent=sessions[:5], teacher=None))
    assert "/logout" not in h, "logged-out nav still shows a logout control"
    assert teacher["name"] not in h, "logged-out nav still shows a teacher name"
    print(f"OK  index.html (no login)  {len(h):>6} bytes")

# A flashed warning used to fall through to the success branch, so a rejected
# enrolment photo was reported with a green tick.
warned = env.get_template("base.html").render(**dict(base, active_page=""))
assert "bg-warn-light" in warned, "a warning flash is not styled as a warning"
assert warned.count("check_circle") == 1, "a warning flash shows the success icon"
print("OK  warning flashes styled distinctly")

# The dashboard carries ~600 lines of inline JavaScript. A syntax error there
# takes the whole page down while the template still "renders", so parse it.
import re, shutil, subprocess, tempfile
node = shutil.which("node")
if node:
    checked = 0
    for name in ("index.html", "session_detail.html", "records.html", "students_page.html"):
        page = (RENDER_DIR / name).read_text()
        for i, block in enumerate(re.findall(r"<script>(.*?)</script>", page, re.S)):
            if not block.strip():
                continue
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
                fh.write(block)
                path = fh.name
            result = subprocess.run([node, "--check", path], capture_output=True, text=True)
            assert result.returncode == 0, f"{name} script #{i}:\n{result.stderr}"
            checked += 1
    print(f"OK  {checked} inline script block(s) parse")
else:
    print("--  node not found, skipping the JavaScript syntax check")

print("\nALL TEMPLATES RENDER")
