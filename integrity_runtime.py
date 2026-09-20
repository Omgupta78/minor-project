"""Database-level attendance integrity and audit hooks."""
from __future__ import annotations

import inspect
from flask import has_request_context, session


def install() -> None:
    import db
    original = getattr(db, "set_status", None)
    if original is None or getattr(original, "_integrity_wrapped", False):
        return

    with db.session_scope() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS attendance_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                teacher_id INTEGER,
                old_status TEXT,
                new_status TEXT NOT NULL,
                changed_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_attendance_audit_session ON attendance_audit(session_id)")

    signature = inspect.signature(original)

    def guarded(*args, **kwargs):
        bound = signature.bind_partial(*args, **kwargs)
        values = bound.arguments
        conn = values.get("conn")
        session_id = values.get("session_id")
        student_id = values.get("student_id")
        status = values.get("status")
        if conn is None or session_id is None or student_id is None:
            return original(*args, **kwargs)
        classes = conn.execute(
            """SELECT x.class_id AS session_class, s.class_id AS student_class
                 FROM sessions x CROSS JOIN students s
                WHERE x.id = ? AND s.id = ?""",
            (session_id, student_id),
        ).fetchone()
        if classes is None or classes["session_class"] != classes["student_class"]:
            raise ValueError("Student and attendance session must belong to the same class")
        previous = conn.execute(
            "SELECT status FROM attendance WHERE session_id = ? AND student_id = ?",
            (session_id, student_id),
        ).fetchone()
        result = original(*args, **kwargs)
        new_status = status or conn.execute(
            "SELECT status FROM attendance WHERE session_id = ? AND student_id = ?",
            (session_id, student_id),
        ).fetchone()["status"]
        teacher_id = session.get("teacher_id") if has_request_context() else None
        conn.execute(
            """INSERT INTO attendance_audit
               (session_id, student_id, teacher_id, old_status, new_status)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, student_id, teacher_id, previous["status"] if previous else None, new_status),
        )
        return result

    guarded._integrity_wrapped = True
    db.set_status = guarded
