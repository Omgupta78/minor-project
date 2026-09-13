"""
authtest.py - checks for teacher accounts, password hashing and isolation.

Runs on the standard library alone: no Flask, no dlib, no network. Every test
builds a real SQLite database in memory, including a deliberately *old-schema*
one to prove the migration works on a database that already has a term of
attendance in it.

    python3 authtest.py
"""
from __future__ import annotations

import sqlite3
import sys
import time

import auth

FAILS = 0
CHECKS = 0

# Real cost is 240k rounds; tests use a token cost so the suite stays fast.
FAST = 1000


def check(label: str, ok: bool, detail: str = "") -> bool:
    global FAILS, CHECKS
    CHECKS += 1
    if ok:
        print(f"  [ok]   {label}")
    else:
        FAILS += 1
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))
    return ok


def section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


# The schema as it shipped in the single-teacher build, complete with the two
# global constraints that make multi-teacher use impossible.
OLD_SCHEMA = """
CREATE TABLE classes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    subject     TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (name, subject)
);

CREATE TABLE students (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    roll_no     TEXT    NOT NULL UNIQUE,
    name        TEXT    NOT NULL,
    class_id    INTEGER REFERENCES classes (id) ON DELETE SET NULL,
    photo_path  TEXT,
    encoding    BLOB,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id     INTEGER NOT NULL REFERENCES classes (id) ON DELETE CASCADE,
    date         TEXT    NOT NULL,
    period       TEXT    NOT NULL DEFAULT '1',
    taken_by     TEXT    NOT NULL DEFAULT '',
    total_faces  INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (class_id, date, period)
);

CREATE TABLE attendance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    student_id  INTEGER NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    status      TEXT    NOT NULL CHECK (status IN ('present', 'absent', 'late')),
    confidence  REAL,
    method      TEXT    NOT NULL DEFAULT 'face' CHECK (method IN ('face', 'manual')),
    marked_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (session_id, student_id)
);
"""


def old_database() -> sqlite3.Connection:
    """A pre-accounts database with one class, two students and a session."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(OLD_SCHEMA)
    conn.execute("INSERT INTO classes (name, subject) VALUES ('CSE 3A', 'DBMS')")
    conn.execute(
        "INSERT INTO students (roll_no, name, class_id) VALUES ('1', 'Asha', 1)"
    )
    conn.execute(
        "INSERT INTO students (roll_no, name, class_id) VALUES ('2', 'Ravi', 1)"
    )
    conn.execute(
        "INSERT INTO sessions (class_id, date, period) VALUES (1, '2026-09-01', '1')"
    )
    conn.execute(
        """INSERT INTO attendance (session_id, student_id, status, method)
           VALUES (1, 1, 'present', 'face')"""
    )
    conn.commit()
    return conn


def migrated_database() -> sqlite3.Connection:
    conn = old_database()
    auth.ensure_schema(conn)
    return conn


# ---------------------------------------------------------------- passwords
section("Password hashing")

stored = auth.hash_password("correct horse battery", rounds=FAST)
check("hash is self-describing", stored.startswith(f"{auth.ALGORITHM}${FAST}$"), stored[:40])
check("plaintext never appears in the hash", "correct horse battery" not in stored)
check("correct password verifies", auth.verify_password("correct horse battery", stored))
check("wrong password rejected", not auth.verify_password("wrong horse battery", stored))
check("empty password rejected", not auth.verify_password("", stored))
check(
    "same password hashes differently each time (random salt)",
    auth.hash_password("abc12345", rounds=FAST) != auth.hash_password("abc12345", rounds=FAST),
)
check("malformed hash returns False, does not raise", not auth.verify_password("x", "garbage"))
check("empty stored hash returns False", not auth.verify_password("x", ""))
check("None stored hash returns False", not auth.verify_password("x", None))
check(
    "an unknown algorithm is refused rather than trusted",
    not auth.verify_password("x", "md5$1$aa$bb"),
)
check(
    "non-hex salt is refused rather than raising",
    not auth.verify_password("x", f"{auth.ALGORITHM}$1000$zz$zz"),
)
check("unicode password round-trips", auth.verify_password(
    "paraskevi-\u03b1\u03b2\u03b3", auth.hash_password("paraskevi-\u03b1\u03b2\u03b3", rounds=FAST)
))
check(
    "a 1000-round hash is flagged for upgrade against 240k",
    auth.needs_rehash(stored, rounds=240000),
)
check(
    "a current-cost hash is not flagged",
    not auth.needs_rehash(auth.hash_password("abc12345", rounds=FAST), rounds=FAST),
)

# ---------------------------------------------------------------- validation
section("Input validation")

check("blank email refused", auth.email_problem("") is not None)
check("email without @ refused", auth.email_problem("teacher.example.com") is not None)
check("email without TLD refused", auth.email_problem("teacher@example") is not None)
check("ordinary email accepted", auth.email_problem("teacher@example.com") is None)
check("email is case-insensitive", auth.normalise_email("  Teacher@Example.COM ") == "teacher@example.com")
check("short password refused", auth.password_problem("abc") is not None)
check("8-character password accepted", auth.password_problem("abcd1234") is None)
check("a long passphrase is accepted, not truncated", auth.password_problem("a" * 64) is None)
check("absurd password length refused", auth.password_problem("a" * 2000) is not None)
check("blank name refused", auth.name_problem("   ") is not None)
check("ordinary name accepted", auth.name_problem("Dr R. Sharma") is None)

# ----------------------------------------------------------------- migration
section("Migrating a single-teacher database")

conn = old_database()
steps = auth.ensure_schema(conn)
check("migration reported both rebuilds", len(steps) == 2, str(steps))
columns = [row[1] for row in conn.execute("PRAGMA table_info(classes)")]
check("classes gained teacher_id", "teacher_id" in columns, str(columns))
check("teachers table created", auth.count_teachers(conn) == 0)

check(
    "existing class survived the rebuild",
    conn.execute("SELECT COUNT(*) FROM classes").fetchone()[0] == 1,
)
check(
    "existing students survived the rebuild",
    conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 2,
)
check(
    "existing attendance survived the rebuild",
    conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0] == 1,
)
check(
    "student ids were preserved, so attendance still points at Asha",
    conn.execute(
        """SELECT s.name FROM attendance a JOIN students s ON s.id = a.student_id"""
    ).fetchone()[0]
    == "Asha",
)
check("pre-account classes are left unclaimed", conn.execute(
    "SELECT teacher_id IS NULL FROM classes WHERE id = 1"
).fetchone()[0] == 1)

steps_again = auth.ensure_schema(conn)
check("running the migration twice is a no-op", steps_again == [], str(steps_again))

# The old global constraints are the whole point of the rebuild.
conn3 = migrated_database()
t1 = auth.create_teacher(conn3, "a@example.com", "Teacher A", "abcd1234", rounds=FAST)
t2 = auth.create_teacher(conn3, "b@example.com", "Teacher B", "abcd1234", rounds=FAST)
conn3.execute(
    "INSERT INTO classes (teacher_id, name, subject) VALUES (?, 'CSE 3A', 'DBMS')", (t2,)
)
check(
    "the same class name under a different teacher is allowed now",
    conn3.execute(
        "SELECT COUNT(*) FROM classes WHERE name = 'CSE 3A' AND subject = 'DBMS'"
    ).fetchone()[0]
    == 2,
)
try:
    conn3.execute(
        "INSERT INTO classes (teacher_id, name, subject) VALUES (?, 'CSE 3A', 'DBMS')",
        (t2,),
    )
    duplicate_blocked = False
except sqlite3.IntegrityError:
    duplicate_blocked = True
check("the same teacher still cannot duplicate their own class", duplicate_blocked)

new_class = conn3.execute(
    "SELECT id FROM classes WHERE teacher_id = ?", (t2,)
).fetchone()[0]
conn3.execute(
    "INSERT INTO students (roll_no, name, class_id) VALUES ('1', 'Meera', ?)",
    (new_class,),
)
check(
    "roll number 1 can exist in two different classes",
    conn3.execute("SELECT COUNT(*) FROM students WHERE roll_no = '1'").fetchone()[0] == 2,
)
try:
    conn3.execute(
        "INSERT INTO students (roll_no, name, class_id) VALUES ('1', 'Clash', ?)",
        (new_class,),
    )
    roll_clash_blocked = False
except sqlite3.IntegrityError:
    roll_clash_blocked = True
check("a roll number is still unique inside one class", roll_clash_blocked)

# ------------------------------------------------------------------ accounts
section("Accounts")

conn = migrated_database()
first = auth.create_teacher(conn, "First@Example.com", "First Teacher", "abcd1234", rounds=FAST)
check("first account created", isinstance(first, int) and first > 0)
check("email stored lower-case", auth.get_teacher(conn, first)["email"] == "first@example.com")
check("first account is the admin", auth.get_teacher(conn, first)["is_admin"] == 1)
check(
    "the first account adopts the pre-account class",
    conn.execute("SELECT teacher_id FROM classes WHERE id = 1").fetchone()[0] == first,
)

second = auth.create_teacher(conn, "second@example.com", "Second", "abcd1234", rounds=FAST)
check("second account is not an admin", auth.get_teacher(conn, second)["is_admin"] == 0)
check(
    "the second account adopts nothing",
    conn.execute("SELECT COUNT(*) FROM classes WHERE teacher_id = ?", (second,)).fetchone()[0] == 0,
)

for label, email, name, password in [
    ("duplicate email", "first@example.com", "Impostor", "abcd1234"),
    ("duplicate email in different case", "FIRST@example.com", "Impostor", "abcd1234"),
    ("bad email", "not-an-email", "Someone", "abcd1234"),
    ("short password", "third@example.com", "Someone", "abc"),
    ("blank name", "fourth@example.com", "  ", "abcd1234"),
]:
    try:
        auth.create_teacher(conn, email, name, password, rounds=FAST)
        refused = False
    except auth.AuthError:
        refused = True
    check(f"{label} refused", refused)

check("teacher count is still 2 after the refusals", auth.count_teachers(conn) == 2)

# ------------------------------------------------------------------- login
section("Login")

row = auth.authenticate(conn, "first@example.com", "abcd1234")
check("correct credentials log in", row is not None and row["id"] == first)
check("login is case-insensitive on email", auth.authenticate(conn, "FIRST@EXAMPLE.COM", "abcd1234") is not None)
check("wrong password refused", auth.authenticate(conn, "first@example.com", "nope1234") is None)
check("unknown account refused", auth.authenticate(conn, "ghost@example.com", "abcd1234") is None)
check("blank password refused", auth.authenticate(conn, "first@example.com", "") is None)
check("None password refused", auth.authenticate(conn, "first@example.com", None) is None)
check(
    "last_login is recorded",
    auth.get_teacher(conn, first)["last_login"] is not None,
)

conn.execute("UPDATE teachers SET active = 0 WHERE id = ?", (second,))
check(
    "a deactivated account cannot log in",
    auth.authenticate(conn, "second@example.com", "abcd1234") is None,
)
conn.execute("UPDATE teachers SET active = 1 WHERE id = ?", (second,))

# An unknown email must not be obviously faster than a known one, or the login
# form becomes a way to find out who has an account.
start = time.perf_counter()
auth.authenticate(conn, "first@example.com", "wrong-password")
known = time.perf_counter() - start
start = time.perf_counter()
auth.authenticate(conn, "nobody@example.com", "wrong-password")
unknown = time.perf_counter() - start
check(
    "an unknown email still costs a hash verification",
    unknown > known / 20,
    f"known={known * 1000:.1f}ms unknown={unknown * 1000:.1f}ms",
)

# --------------------------------------------------------------- rehashing
section("Password upgrade on login")

conn_r = migrated_database()
weak = auth.create_teacher(conn_r, "weak@example.com", "Weak", "abcd1234", rounds=FAST)
before = auth.get_teacher(conn_r, weak)["password_hash"]
auth.ROUNDS = FAST * 4
auth.authenticate(conn_r, "weak@example.com", "abcd1234")
after = auth.get_teacher(conn_r, weak)["password_hash"]
check("a weak hash is upgraded on successful login", before != after)
check("the upgraded hash uses the new cost", after.startswith(f"{auth.ALGORITHM}${FAST * 4}$"))
check("the password still works after the upgrade", auth.authenticate(conn_r, "weak@example.com", "abcd1234") is not None)
auth.ROUNDS = 240000

# ------------------------------------------------------------ change password
section("Changing a password")

conn_c = migrated_database()
cid = auth.create_teacher(conn_c, "c@example.com", "C", "abcd1234", rounds=FAST)
for label, current, new in [
    ("wrong current password refused", "wrong123", "newpass123"),
    ("short new password refused", "abcd1234", "abc"),
]:
    try:
        auth.change_password(conn_c, cid, current, new)
        refused = False
    except auth.AuthError:
        refused = True
    check(label, refused)

auth.change_password(conn_c, cid, "abcd1234", "a-much-longer-passphrase")
check("the new password works", auth.authenticate(conn_c, "c@example.com", "a-much-longer-passphrase") is not None)
check("the old password stops working", auth.authenticate(conn_c, "c@example.com", "abcd1234") is None)

# ------------------------------------------------------------------ isolation
section("One teacher cannot reach another's data")

conn = migrated_database()
mine = auth.create_teacher(conn, "mine@example.com", "Mine", "abcd1234", rounds=FAST)
theirs = auth.create_teacher(conn, "theirs@example.com", "Theirs", "abcd1234", rounds=FAST)

conn.execute("INSERT INTO classes (teacher_id, name) VALUES (?, 'Their class')", (theirs,))
their_class = conn.execute("SELECT id FROM classes WHERE teacher_id = ?", (theirs,)).fetchone()[0]
conn.execute(
    "INSERT INTO students (roll_no, name, class_id) VALUES ('7', 'Their student', ?)",
    (their_class,),
)
their_student = conn.execute("SELECT id FROM students WHERE class_id = ?", (their_class,)).fetchone()[0]
conn.execute(
    "INSERT INTO sessions (class_id, date, period) VALUES (?, '2026-09-10', '2')",
    (their_class,),
)
their_session = conn.execute("SELECT id FROM sessions WHERE class_id = ?", (their_class,)).fetchone()[0]

# 'mine' adopted the legacy class 1; 'theirs' owns their own.
check("owner passes the class check", auth.owns_class(conn, theirs, their_class))
check("a stranger fails the class check", not auth.owns_class(conn, mine, their_class))
check("owner passes the student check", auth.owns_student(conn, theirs, their_student))
check("a stranger fails the student check", not auth.owns_student(conn, mine, their_student))
check("owner passes the session check", auth.owns_session(conn, theirs, their_session))
check("a stranger fails the session check", not auth.owns_session(conn, mine, their_session))
check("a missing class id fails rather than raising", not auth.owns_class(conn, mine, 99999))
check("None class id fails rather than raising", not auth.owns_class(conn, mine, None))
check("None teacher id fails (an anonymous visitor owns nothing)", not auth.owns_class(conn, None, their_class))
check(
    "class_ids_for lists only that teacher's classes",
    auth.class_ids_for(conn, theirs) == [their_class],
    str(auth.class_ids_for(conn, theirs)),
)
# PRAGMA foreign_keys is a no-op while a transaction is open, and the inserts
# above left one open. Commit first, or the cascade silently does nothing.
conn.commit()
conn.execute("PRAGMA foreign_keys = ON")
conn.execute("DELETE FROM teachers WHERE id = ?", (theirs,))
check(
    "a deleted teacher's classes are removed by the cascade",
    conn.execute("SELECT COUNT(*) FROM classes WHERE id = ?", (their_class,)).fetchone()[0] == 0,
)

print(f"\n{CHECKS - FAILS}/{CHECKS} checks passed.")
if FAILS:
    print(f"{FAILS} FAILED")
    sys.exit(1)
print("All account and isolation checks passed.")
