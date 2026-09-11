"""
db.py - SQLite data layer for the Face Recognition Attendance System.

Uses only the Python standard library (sqlite3) plus numpy for the encoding
blobs, so there is nothing extra to install and it behaves identically on
Windows, Linux and macOS.

Why a database instead of CSV files?
  * ABSENT students become knowable. A CSV of present names cannot answer
    "what is Ravi's attendance percentage" - a table of (session, student,
    status) can.
  * Face encodings are cached as BLOBs, so the app does not re-encode every
    photo in faces/ on every startup.
  * Roll numbers, classes, subjects and periods become real fields instead of
    numbers invented in JavaScript.

Tables
------
classes      one row per class/section + subject a teacher takes
students     the roster; holds the cached 128-D face encoding
sessions     one row per "teacher clicked a photo" event (class+date+period)
attendance   one row per student per session, status present/absent/late
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date as _date
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("ATTENDANCE_DB", BASE_DIR / "instance" / "attendance.db"))

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS classes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    subject     TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (name, subject)
);

CREATE TABLE IF NOT EXISTS students (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    roll_no     TEXT    NOT NULL UNIQUE,
    name        TEXT    NOT NULL,
    class_id    INTEGER REFERENCES classes (id) ON DELETE SET NULL,
    photo_path  TEXT,
    encoding    BLOB,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Extra reference photos for a student. One photo captures one angle and one
-- lighting condition, which is the main cause of missed matches. Every
-- encoding here is compared against during a scan and the closest one wins,
-- so adding photos can only ever improve recognition.
-- students.encoding stays as the first/primary encoding so old databases and
-- old code keep working.
CREATE TABLE IF NOT EXISTS student_encodings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    encoding    BLOB    NOT NULL,
    photo_path  TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_student_encodings_student
    ON student_encodings (student_id);

CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id     INTEGER NOT NULL REFERENCES classes (id) ON DELETE CASCADE,
    date         TEXT    NOT NULL,                    -- YYYY-MM-DD
    period       TEXT    NOT NULL DEFAULT '1',
    taken_by     TEXT    NOT NULL DEFAULT '',
    total_faces  INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (class_id, date, period)
);

CREATE TABLE IF NOT EXISTS attendance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    student_id  INTEGER NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    status      TEXT    NOT NULL CHECK (status IN ('present', 'absent', 'late')),
    confidence  REAL,
    method      TEXT    NOT NULL DEFAULT 'face' CHECK (method IN ('face', 'manual')),
    marked_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (session_id, student_id)
);

CREATE INDEX IF NOT EXISTS idx_students_class   ON students (class_id);
CREATE INDEX IF NOT EXISTS idx_sessions_class   ON sessions (class_id, date);
CREATE INDEX IF NOT EXISTS idx_attendance_sess  ON attendance (session_id);
CREATE INDEX IF NOT EXISTS idx_attendance_stud  ON attendance (student_id);
"""

# Roll numbers sort naturally (2 before 10) with this expression.
ROLL_ORDER = "ORDER BY LENGTH(s.roll_no), s.roll_no"


# --------------------------------------------------------------- connection
def connect(db_path: Optional[os.PathLike | str] = None) -> sqlite3.Connection:
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session_scope(db_path: Optional[os.PathLike | str] = None):
    """Commit on success, roll back on error, always close."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[os.PathLike | str] = None) -> None:
    with session_scope(db_path) as conn:
        conn.executescript(SCHEMA)


# ------------------------------------------------------------ encoding blob
def encode_to_blob(encoding: np.ndarray) -> bytes:
    return np.asarray(encoding, dtype=np.float64).tobytes()


def blob_to_encoding(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float64)


# ------------------------------------------------------------------ classes
def create_class(conn, name: str, subject: str = "") -> int:
    cur = conn.execute(
        "INSERT OR IGNORE INTO classes (name, subject) VALUES (?, ?)",
        (name.strip(), subject.strip()),
    )
    if cur.lastrowid:
        return cur.lastrowid
    row = conn.execute(
        "SELECT id FROM classes WHERE name = ? AND subject = ?",
        (name.strip(), subject.strip()),
    ).fetchone()
    return row["id"]


def list_classes(conn) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT c.*,
               (SELECT COUNT(*) FROM students s
                 WHERE s.class_id = c.id AND s.active = 1) AS student_count,
               (SELECT COUNT(*) FROM sessions x WHERE x.class_id = c.id) AS session_count
          FROM classes c
         ORDER BY c.name, c.subject
        """
    ).fetchall()


def get_class(conn, class_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM classes WHERE id = ?", (class_id,)).fetchone()


def delete_class(conn, class_id: int) -> None:
    conn.execute("DELETE FROM classes WHERE id = ?", (class_id,))


# ----------------------------------------------------------------- students
def create_student(
    conn,
    roll_no: str,
    name: str,
    class_id: Optional[int] = None,
    photo_path: Optional[str] = None,
    encoding: Optional[np.ndarray] = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO students (roll_no, name, class_id, photo_path, encoding)
           VALUES (?, ?, ?, ?, ?)""",
        (
            roll_no.strip(),
            name.strip(),
            class_id,
            photo_path,
            encode_to_blob(encoding) if encoding is not None else None,
        ),
    )
    return cur.lastrowid


def update_student(
    conn,
    student_id: int,
    *,
    name: Optional[str] = None,
    roll_no: Optional[str] = None,
    class_id: Optional[int] = None,
    photo_path: Optional[str] = None,
    encoding: Optional[np.ndarray] = None,
) -> None:
    sets, params = [], []
    if name is not None:
        sets.append("name = ?")
        params.append(name.strip())
    if roll_no is not None:
        sets.append("roll_no = ?")
        params.append(roll_no.strip())
    if class_id is not None:
        sets.append("class_id = ?")
        params.append(class_id)
    if photo_path is not None:
        sets.append("photo_path = ?")
        params.append(photo_path)
    if encoding is not None:
        sets.append("encoding = ?")
        params.append(encode_to_blob(encoding))
    if not sets:
        return
    params.append(student_id)
    conn.execute(f"UPDATE students SET {', '.join(sets)} WHERE id = ?", params)


def delete_student(conn, student_id: int) -> None:
    conn.execute("DELETE FROM students WHERE id = ?", (student_id,))


# ------------------------------------------------- extra reference photos
def add_student_encoding(
    conn,
    student_id: int,
    encoding: np.ndarray,
    photo_path: Optional[str] = None,
) -> int:
    """Store an additional reference encoding for a student.

    If the student has no primary encoding yet (enrolled before this feature,
    or enrolled from a photo with no detectable face) the first one added is
    promoted to the primary slot so old code paths keep working.
    """
    row = conn.execute(
        "SELECT encoding FROM students WHERE id = ?", (student_id,)
    ).fetchone()
    if row is not None and row["encoding"] is None:
        update_student(conn, student_id, encoding=encoding, photo_path=photo_path)
        return 0
    cur = conn.execute(
        """INSERT INTO student_encodings (student_id, encoding, photo_path)
           VALUES (?, ?, ?)""",
        (student_id, encode_to_blob(encoding), photo_path),
    )
    return cur.lastrowid


def encoding_counts(conn, class_id: Optional[int] = None) -> dict[int, int]:
    """How many reference photos each student has, primary included."""
    counts: dict[int, int] = {}
    for row in list_students(conn, class_id):
        counts[row["id"]] = 1 if row["encoding"] is not None else 0
    try:
        rows = conn.execute(
            "SELECT student_id, COUNT(*) AS n FROM student_encodings GROUP BY student_id"
        ).fetchall()
    except Exception:  # table missing on a database created by an older build
        return counts
    for row in rows:
        if row["student_id"] in counts:
            counts[row["student_id"]] += row["n"]
    return counts


def clear_student_encodings(conn, student_id: int) -> None:
    """Drop the extra photos, keeping the primary encoding."""
    conn.execute("DELETE FROM student_encodings WHERE student_id = ?", (student_id,))


def list_students(conn, class_id: Optional[int] = None, active_only: bool = True):
    where = ["1 = 1"]
    params: list = []
    if class_id is not None:
        where.append("s.class_id = ?")
        params.append(class_id)
    if active_only:
        where.append("s.active = 1")
    return conn.execute(
        f"""SELECT s.*, c.name AS class_name, c.subject AS class_subject,
                   (s.encoding IS NOT NULL) AS has_encoding
              FROM students s
              LEFT JOIN classes c ON c.id = s.class_id
             WHERE {' AND '.join(where)}
             {ROLL_ORDER}""",
        params,
    ).fetchall()


def get_student(conn, student_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        """SELECT s.*, c.name AS class_name FROM students s
             LEFT JOIN classes c ON c.id = s.class_id
            WHERE s.id = ?""",
        (student_id,),
    ).fetchone()


def known_faces(conn, class_id: Optional[int] = None):
    """Return (ids, labels, matrix) of every student that has an encoding.

    matrix is an (N, 128) float64 array ready for face_recognition.face_distance.
    """
    rows = [r for r in list_students(conn, class_id) if r["encoding"] is not None]

    # Extra reference photos, keyed by student. A student with three photos
    # contributes three rows to the matrix; they all carry the same label, so
    # whichever one is closest wins and the student is still identified once.
    extra: dict[int, list] = {}
    try:
        for row in conn.execute(
            "SELECT student_id, encoding FROM student_encodings ORDER BY id"
        ):
            extra.setdefault(row["student_id"], []).append(
                blob_to_encoding(row["encoding"])
            )
    except Exception:  # database created before this table existed
        extra = {}

    ids: list[int] = []
    labels: list[dict] = []
    vectors: list[np.ndarray] = []
    for r in rows:
        label = {"id": r["id"], "name": r["name"], "roll_no": r["roll_no"]}
        for vector in [blob_to_encoding(r["encoding"])] + extra.get(r["id"], []):
            ids.append(r["id"])
            labels.append(label)
            vectors.append(vector)

    if vectors:
        matrix = np.vstack(vectors)
    else:
        matrix = np.empty((0, 128), dtype=np.float64)
    return ids, labels, matrix


# ----------------------------------------------------------------- sessions
def create_session(
    conn,
    class_id: int,
    on_date: Optional[str] = None,
    period: str = "1",
    taken_by: str = "",
    total_faces: int = 0,
) -> int:
    on_date = on_date or _date.today().isoformat()
    existing = conn.execute(
        "SELECT id FROM sessions WHERE class_id = ? AND date = ? AND period = ?",
        (class_id, on_date, period),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE sessions SET total_faces = ?, taken_by = ? WHERE id = ?",
            (total_faces, taken_by, existing["id"]),
        )
        return existing["id"]
    cur = conn.execute(
        """INSERT INTO sessions (class_id, date, period, taken_by, total_faces)
           VALUES (?, ?, ?, ?, ?)""",
        (class_id, on_date, period, taken_by, total_faces),
    )
    return cur.lastrowid


def list_sessions(conn, class_id: Optional[int] = None, start=None, end=None, limit=None):
    where, params = ["1 = 1"], []
    if class_id is not None:
        where.append("x.class_id = ?")
        params.append(class_id)
    if start:
        where.append("x.date >= ?")
        params.append(start)
    if end:
        where.append("x.date <= ?")
        params.append(end)
    sql = f"""
        SELECT x.*, c.name AS class_name, c.subject AS class_subject,
               (SELECT COUNT(*) FROM attendance a
                 WHERE a.session_id = x.id AND a.status IN ('present', 'late')) AS present_count,
               (SELECT COUNT(*) FROM attendance a
                 WHERE a.session_id = x.id AND a.status = 'absent') AS absent_count
          FROM sessions x
          JOIN classes c ON c.id = x.class_id
         WHERE {' AND '.join(where)}
         ORDER BY x.date DESC, LENGTH(x.period), x.period DESC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, params).fetchall()


def get_session(conn, session_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        """SELECT x.*, c.name AS class_name, c.subject AS class_subject
             FROM sessions x JOIN classes c ON c.id = x.class_id
            WHERE x.id = ?""",
        (session_id,),
    ).fetchone()


def delete_session(conn, session_id: int) -> None:
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


# --------------------------------------------------------------- attendance
def save_session_attendance(
    conn,
    session_id: int,
    class_id: int,
    present: dict[int, dict],
) -> dict:
    """Write attendance for EVERY student in the class.

    present maps student_id -> {"confidence": float | None, "method": str}.
    Everyone in the roster who is not in that dict is recorded as absent, which
    is what makes percentages and defaulter reports possible later.
    """
    roster = list_students(conn, class_id)
    rows = []
    for stu in roster:
        hit = present.get(stu["id"])
        if hit:
            rows.append(
                (
                    session_id,
                    stu["id"],
                    hit.get("status", "present"),
                    hit.get("confidence"),
                    hit.get("method", "face"),
                )
            )
        else:
            rows.append((session_id, stu["id"], "absent", None, "face"))

    conn.executemany(
        """INSERT INTO attendance (session_id, student_id, status, confidence, method)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (session_id, student_id) DO UPDATE SET
               status     = excluded.status,
               confidence = excluded.confidence,
               method     = excluded.method,
               marked_at  = datetime('now', 'localtime')""",
        rows,
    )
    n_present = sum(1 for r in rows if r[2] in ("present", "late"))
    return {"total": len(rows), "present": n_present, "absent": len(rows) - n_present}


def set_status(conn, session_id: int, student_id: int, status: str) -> None:
    conn.execute(
        """INSERT INTO attendance (session_id, student_id, status, method)
           VALUES (?, ?, ?, 'manual')
           ON CONFLICT (session_id, student_id) DO UPDATE SET
               status    = excluded.status,
               method    = 'manual',
               marked_at = datetime('now', 'localtime')""",
        (session_id, student_id, status),
    )


def session_rows(conn, session_id: int):
    """Roster + status for one session, in roll-number order."""
    sess = get_session(conn, session_id)
    if sess is None:
        return []
    return conn.execute(
        f"""SELECT s.id, s.roll_no, s.name, s.photo_path,
                   COALESCE(a.status, 'absent') AS status,
                   a.confidence, a.method, a.marked_at
              FROM students s
              LEFT JOIN attendance a
                     ON a.student_id = s.id AND a.session_id = ?
             WHERE s.class_id = ? AND s.active = 1
             {ROLL_ORDER}""",
        (session_id, sess["class_id"]),
    ).fetchall()


# ------------------------------------------------------------------ reports
def attendance_summary(conn, class_id: Optional[int] = None, start=None, end=None):
    """Per-student totals and percentage over the selected sessions."""
    where, params = ["s.active = 1"], []
    if class_id is not None:
        where.append("s.class_id = ?")
        params.append(class_id)

    sess_where, sess_params = ["1 = 1"], []
    if class_id is not None:
        sess_where.append("x.class_id = ?")
        sess_params.append(class_id)
    if start:
        sess_where.append("x.date >= ?")
        sess_params.append(start)
    if end:
        sess_where.append("x.date <= ?")
        sess_params.append(end)

    sql = f"""
        WITH sel AS (
            SELECT x.id FROM sessions x WHERE {' AND '.join(sess_where)}
        )
        SELECT s.id, s.roll_no, s.name, c.name AS class_name, c.subject,
               (SELECT COUNT(*) FROM sel) AS held,
               COALESCE(SUM(CASE WHEN a.status IN ('present', 'late') THEN 1 ELSE 0 END), 0) AS present,
               COALESCE(SUM(CASE WHEN a.status = 'absent' THEN 1 ELSE 0 END), 0) AS absent
          FROM students s
          LEFT JOIN classes c ON c.id = s.class_id
          LEFT JOIN attendance a
                 ON a.student_id = s.id AND a.session_id IN (SELECT id FROM sel)
         WHERE {' AND '.join(where)}
         GROUP BY s.id
         {ROLL_ORDER}
    """
    rows = conn.execute(sql, sess_params + params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        held = d["held"] or 0
        d["percent"] = round(d["present"] / held * 100, 1) if held else 0.0
        d["defaulter"] = held > 0 and d["percent"] < 75.0
        out.append(d)
    return out


def attendance_grid(conn, class_id: Optional[int] = None, start=None, end=None):
    """(students, sessions, marks) where marks[(student_id, session_id)] = status."""
    students = list_students(conn, class_id)
    sessions = sorted(
        list_sessions(conn, class_id, start, end),
        key=lambda r: (r["date"], len(r["period"]), r["period"]),
    )
    if not sessions:
        return students, [], {}
    ids = [s["id"] for s in sessions]
    q = f"""SELECT session_id, student_id, status, confidence FROM attendance
             WHERE session_id IN ({','.join('?' * len(ids))})"""
    marks = {
        (r["student_id"], r["session_id"]): r["status"]
        for r in conn.execute(q, ids).fetchall()
    }
    return students, sessions, marks


def detailed_records(conn, class_id: Optional[int] = None, start=None, end=None):
    where, params = ["1 = 1"], []
    if class_id is not None:
        where.append("x.class_id = ?")
        params.append(class_id)
    if start:
        where.append("x.date >= ?")
        params.append(start)
    if end:
        where.append("x.date <= ?")
        params.append(end)
    return conn.execute(
        f"""SELECT x.date, x.period, c.name AS class_name, c.subject,
                   s.roll_no, s.name, a.status, a.confidence, a.method, a.marked_at
              FROM attendance a
              JOIN sessions x ON x.id = a.session_id
              JOIN classes  c ON c.id = x.class_id
              JOIN students s ON s.id = a.student_id
             WHERE {' AND '.join(where)}
             ORDER BY x.date DESC, LENGTH(x.period), x.period, LENGTH(s.roll_no), s.roll_no""",
        params,
    ).fetchall()


def dashboard_stats(conn, class_id: Optional[int] = None) -> dict:
    today = _date.today().isoformat()
    students = len(list_students(conn, class_id))
    sess = list_sessions(conn, class_id, start=today, end=today)
    present_today = sum(s["present_count"] for s in sess)
    summary = attendance_summary(conn, class_id)
    avg = round(sum(s["percent"] for s in summary) / len(summary), 1) if summary else 0.0
    return {
        "students": students,
        "sessions_today": len(sess),
        "present_today": present_today,
        "total_sessions": len(list_sessions(conn, class_id)),
        "avg_percent": avg,
        "defaulters": sum(1 for s in summary if s["defaulter"]),
    }


if __name__ == "__main__":
    init_db()
    print(f"initialised database at {DB_PATH}")
