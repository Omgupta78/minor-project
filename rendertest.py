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

    base = dict(
        active_page="",
        match_threshold=0.50,
        student_total=len(students),
        nav_classes=classes,
        classes=classes,
        class_id=cid,
        today="2026-09-09",
    )

    cases = [
        ("index.html", dict(base, active_page="dashboard", students=students,
                            stats=stats, recent=sessions[:5])),
        ("students_page.html", dict(base, active_page="students", students=students,
                                    summary={s["id"]: s for s in summary})),
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
        print(f"OK  {name:<22} {len(html):>6} bytes   fake-data leaks: {leaks or 'none'}")

    # Empty-workspace states must not crash either.
    empty = dict(base, classes=[], nav_classes=[], class_id=None, students=[],
                 student_total=0, stats=dict(students=0, sessions_today=0,
                 present_today=0, total_sessions=0, avg_percent=0.0, defaulters=0))
    h = env.get_template("index.html").render(**dict(empty, active_page="dashboard", recent=[]))
    with open(RENDER_DIR / "index_empty.html", "w") as fh:
        fh.write(h)
    print(f"OK  index.html (empty)     {len(h):>6} bytes")

    h = env.get_template("students_page.html").render(**dict(empty, active_page="students", summary={}))
    with open(RENDER_DIR / "students_empty.html", "w") as fh:
        fh.write(h)
    print(f"OK  students (empty)       {len(h):>6} bytes")

    h = env.get_template("records.html").render(**dict(empty, active_page="records",
            sessions=[], summary=[], start="", end=""))
    with open(RENDER_DIR / "records_empty.html", "w") as fh:
        fh.write(h)
    print(f"OK  records (empty)        {len(h):>6} bytes")

print("\nALL TEMPLATES RENDER")
