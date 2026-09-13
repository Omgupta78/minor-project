"""
auth.py - teacher accounts, password hashing and per-teacher data isolation.

Why this file exists
--------------------
Until now the app had no concept of "who is using it". That is fine for one
teacher on one laptop and completely wrong for a shared deployment: anyone who
could reach the URL could see every class, every student's face and every
attendance record.

Three things are needed before several teachers can share one instance:

  1. Accounts, with passwords stored as salted hashes (never plaintext).
  2. An owner on every class, so queries can be scoped to one teacher.
  3. Uniqueness rules that are per-teacher rather than global. The original
     schema had UNIQUE(name, subject) on classes and UNIQUE(roll_no) on
     students, which means the *second* teacher to create "CSE 3rd Year A",
     or to enrol a student with roll number "1", would be rejected. SQLite
     cannot drop a constraint in place, so those two tables are rebuilt.

Standard library only: hashlib.pbkdf2_hmac, so there is no bcrypt/passlib/
argon2 wheel to compile. PBKDF2-HMAC-SHA256 at 240k rounds is a defensible
choice and is what Django shipped as its default for years.

Nothing here imports Flask, so all of it is unit-testable without a web
server (see authtest.py).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from typing import Optional

ALGORITHM = "pbkdf2_sha256"

# Cost of one password check. Raising this is the single best defence against
# an offline dictionary attack if the database file is ever stolen. Overridable
# so the test suite can run fast without weakening production.
ROUNDS = int(os.environ.get("PASSWORD_ROUNDS", "240000"))

SALT_BYTES = 16
MIN_PASSWORD_LEN = 8

# Deliberately permissive. Email validation by regex is a losing game; this
# catches typos like a missing @ or a trailing dot and nothing more. The real
# check is whether the teacher can log in.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

TEACHER_SCHEMA = """
CREATE TABLE IF NOT EXISTS teachers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    email          TEXT    NOT NULL UNIQUE,
    name           TEXT    NOT NULL,
    password_hash  TEXT    NOT NULL,
    is_admin       INTEGER NOT NULL DEFAULT 0,
    active         INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    last_login     TEXT
);

CREATE INDEX IF NOT EXISTS idx_teachers_email ON teachers (email);
"""


class AuthError(Exception):
    """Raised for a failure the teacher should see, e.g. duplicate email."""


# ------------------------------------------------------------------ passwords
def hash_password(
    password: str,
    *,
    rounds: Optional[int] = None,
    salt: Optional[bytes] = None,
) -> str:
    """Return a self-describing hash string.

    Format: pbkdf2_sha256$<rounds>$<salt hex>$<derived key hex>

    Storing the algorithm and cost alongside the hash means the cost can be
    raised later without invalidating existing passwords: an old hash still
    verifies against its own recorded rounds.
    """
    if not isinstance(password, str) or not password:
        raise AuthError("Password must not be empty.")
    rounds = int(rounds or ROUNDS)
    salt = salt or secrets.token_bytes(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return f"{ALGORITHM}${rounds}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of a password against a stored hash.

    Returns False rather than raising on malformed input, so a corrupt row
    cannot turn into a 500 on the login page.
    """
    if not isinstance(password, str) or not isinstance(stored, str):
        return False
    parts = stored.split("$")
    if len(parts) != 4:
        return False
    algorithm, rounds_text, salt_hex, expected_hex = parts
    if algorithm != ALGORITHM:
        return False
    try:
        rounds = int(rounds_text)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)
    except ValueError:
        return False
    if rounds < 1 or not salt or not expected:
        return False
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(derived, expected)


def needs_rehash(stored: str, *, rounds: Optional[int] = None) -> bool:
    """True if a valid hash was made with a weaker cost than we now use."""
    target = int(rounds or ROUNDS)
    parts = (stored or "").split("$")
    if len(parts) != 4 or parts[0] != ALGORITHM:
        return True
    try:
        return int(parts[1]) < target
    except ValueError:
        return True


# ----------------------------------------------------------------- validation
def normalise_email(email: Optional[str]) -> str:
    return (email or "").strip().lower()


def email_problem(email: str) -> Optional[str]:
    email = normalise_email(email)
    if not email:
        return "Email is required."
    if len(email) > 254:
        return "That email address is too long."
    if not EMAIL_RE.match(email):
        return "That does not look like an email address."
    return None


def password_problem(password: Optional[str]) -> Optional[str]:
    """Length only.

    Composition rules ('one capital, one symbol') push people towards
    Passw0rd! and are no longer recommended by NIST. Length is what matters.
    """
    if not password:
        return "Password is required."
    if len(password) < MIN_PASSWORD_LEN:
        return f"Use at least {MIN_PASSWORD_LEN} characters."
    if len(password) > 1024:
        return "That password is unreasonably long."
    return None


def name_problem(name: Optional[str]) -> Optional[str]:
    if not (name or "").strip():
        return "Name is required."
    if len((name or "").strip()) > 120:
        return "That name is too long."
    return None


# --------------------------------------------------------------- schema/migrate
def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def _table_sql(conn: sqlite3.Connection, table: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return (row[0] if row and row[0] else "")


def _rebuild_classes(conn: sqlite3.Connection) -> None:
    """Give classes a teacher_id and make (teacher, name, subject) unique.

    Existing rows get teacher_id = NULL, which means 'unclaimed'. The first
    account created on an upgraded database adopts them, so a teacher who has
    been using the single-user build does not lose a term of data.
    """
    conn.executescript(
        """
        CREATE TABLE classes_new (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id  INTEGER REFERENCES teachers (id) ON DELETE CASCADE,
            name        TEXT    NOT NULL,
            subject     TEXT    NOT NULL DEFAULT '',
            created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE (teacher_id, name, subject)
        );

        INSERT INTO classes_new (id, teacher_id, name, subject, created_at)
            SELECT id, NULL, name, subject, created_at FROM classes;

        DROP TABLE classes;
        ALTER TABLE classes_new RENAME TO classes;

        CREATE INDEX IF NOT EXISTS idx_classes_teacher ON classes (teacher_id);
        """
    )


def _rebuild_students(conn: sqlite3.Connection) -> None:
    """Replace the global UNIQUE(roll_no) with UNIQUE(class_id, roll_no).

    Roll number 1 exists in every class in the world. Keeping it globally
    unique would mean the first teacher to enrol a roll 1 locks out everyone
    else on the same instance.
    """
    conn.executescript(
        """
        CREATE TABLE students_new (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            roll_no     TEXT    NOT NULL,
            name        TEXT    NOT NULL,
            class_id    INTEGER REFERENCES classes (id) ON DELETE SET NULL,
            photo_path  TEXT,
            encoding    BLOB,
            active      INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE (class_id, roll_no)
        );

        INSERT INTO students_new
            (id, roll_no, name, class_id, photo_path, encoding, active, created_at)
            SELECT id, roll_no, name, class_id, photo_path, encoding, active,
                   created_at
            FROM students;

        DROP TABLE students;
        ALTER TABLE students_new RENAME TO students;

        CREATE INDEX IF NOT EXISTS idx_students_class ON students (class_id);
        """
    )


def ensure_schema(conn: sqlite3.Connection) -> list[str]:
    """Create the teachers table and migrate old databases in place.

    Safe to call on every start: each step is guarded, so this is a no-op on
    an already-migrated database. Returns the list of steps performed, which
    the startup log and the tests both use.

    Foreign keys are turned off for the duration. SQLite would otherwise
    cascade-delete the children of the table being dropped and rebuilt.
    """
    done: list[str] = []
    conn.executescript(TEACHER_SCHEMA)

    needs_class_rebuild = _table_exists(conn, "classes") and (
        "teacher_id" not in _columns(conn, "classes")
    )
    # Detect the old global constraint by reading the stored DDL. A rebuilt
    # table carries UNIQUE (class_id, roll_no) instead.
    students_sql = _table_sql(conn, "students").replace("\n", " ")
    needs_student_rebuild = _table_exists(conn, "students") and (
        "UNIQUE (class_id, roll_no)" not in students_sql
        and "UNIQUE(class_id, roll_no)" not in students_sql
    )

    if not (needs_class_rebuild or needs_student_rebuild):
        return done

    foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        if needs_class_rebuild:
            _rebuild_classes(conn)
            done.append("classes: added teacher_id, scoped UNIQUE per teacher")
        if needs_student_rebuild:
            _rebuild_students(conn)
            done.append("students: roll_no now unique per class, not globally")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute(f"PRAGMA foreign_keys = {'ON' if foreign_keys else 'OFF'}")
    return done


# -------------------------------------------------------------------- accounts
def count_teachers(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0])


def get_teacher(conn: sqlite3.Connection, teacher_id: int):
    return conn.execute(
        "SELECT * FROM teachers WHERE id = ? AND active = 1", (teacher_id,)
    ).fetchone()


def get_teacher_by_email(conn: sqlite3.Connection, email: str):
    return conn.execute(
        "SELECT * FROM teachers WHERE email = ?", (normalise_email(email),)
    ).fetchone()


def create_teacher(
    conn: sqlite3.Connection,
    email: str,
    name: str,
    password: str,
    *,
    rounds: Optional[int] = None,
) -> int:
    """Register a teacher. Raises AuthError with a user-safe message.

    The first account on an instance becomes the admin and adopts any classes
    left over from the single-user build.
    """
    email = normalise_email(email)
    for problem in (email_problem(email), name_problem(name), password_problem(password)):
        if problem:
            raise AuthError(problem)

    first_account = count_teachers(conn) == 0
    try:
        cursor = conn.execute(
            """INSERT INTO teachers (email, name, password_hash, is_admin)
               VALUES (?, ?, ?, ?)""",
            (
                email,
                name.strip(),
                hash_password(password, rounds=rounds),
                1 if first_account else 0,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise AuthError("An account with that email already exists.") from exc

    teacher_id = int(cursor.lastrowid)
    if first_account:
        adopt_unclaimed(conn, teacher_id)
    return teacher_id


def adopt_unclaimed(conn: sqlite3.Connection, teacher_id: int) -> int:
    """Hand pre-account classes to a teacher. Returns how many moved."""
    cursor = conn.execute(
        "UPDATE classes SET teacher_id = ? WHERE teacher_id IS NULL", (teacher_id,)
    )
    return int(cursor.rowcount or 0)


def authenticate(conn: sqlite3.Connection, email: str, password: str):
    """Return the teacher row on success, or None.

    Deliberately does not distinguish 'no such account' from 'wrong password',
    so the login page cannot be used to enumerate who has signed up. A hash is
    verified even when the account does not exist, to keep the response time
    roughly constant.
    """
    row = get_teacher_by_email(conn, email)
    if row is None:
        verify_password(password or "", hash_password("timing-equaliser", rounds=ROUNDS))
        return None
    if not row["active"]:
        return None
    if not verify_password(password or "", row["password_hash"]):
        return None

    if needs_rehash(row["password_hash"]):
        conn.execute(
            "UPDATE teachers SET password_hash = ? WHERE id = ?",
            (hash_password(password), row["id"]),
        )
    conn.execute(
        "UPDATE teachers SET last_login = datetime('now', 'localtime') WHERE id = ?",
        (row["id"],),
    )
    return row


def change_password(
    conn: sqlite3.Connection, teacher_id: int, current: str, new: str
) -> None:
    row = get_teacher(conn, teacher_id)
    if row is None:
        raise AuthError("Account not found.")
    if not verify_password(current or "", row["password_hash"]):
        raise AuthError("Your current password is not correct.")
    problem = password_problem(new)
    if problem:
        raise AuthError(problem)
    conn.execute(
        "UPDATE teachers SET password_hash = ? WHERE id = ?",
        (hash_password(new), teacher_id),
    )


# ------------------------------------------------------------------- ownership
def owns_class(conn: sqlite3.Connection, teacher_id: int, class_id: int) -> bool:
    """The single source of truth for 'may this teacher touch this class'."""
    if class_id is None or teacher_id is None:
        return False
    row = conn.execute(
        "SELECT 1 FROM classes WHERE id = ? AND teacher_id = ?",
        (class_id, teacher_id),
    ).fetchone()
    return row is not None


def owns_student(conn: sqlite3.Connection, teacher_id: int, student_id: int) -> bool:
    row = conn.execute(
        """SELECT 1
             FROM students s
             JOIN classes c ON c.id = s.class_id
            WHERE s.id = ? AND c.teacher_id = ?""",
        (student_id, teacher_id),
    ).fetchone()
    return row is not None


def owns_session(conn: sqlite3.Connection, teacher_id: int, session_id: int) -> bool:
    row = conn.execute(
        """SELECT 1
             FROM sessions sess
             JOIN classes c ON c.id = sess.class_id
            WHERE sess.id = ? AND c.teacher_id = ?""",
        (session_id, teacher_id),
    ).fetchone()
    return row is not None


def class_ids_for(conn: sqlite3.Connection, teacher_id: int) -> list[int]:
    return [
        int(row[0])
        for row in conn.execute(
            "SELECT id FROM classes WHERE teacher_id = ? ORDER BY id", (teacher_id,)
        )
    ]
