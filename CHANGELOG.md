# Changelog

## Unreleased — code-base review fixes

### Fixed (data loss and deployment)
- `maintenance.py` resolved `students.photo_path` against the working
  directory instead of `FACES_DIR`. Every enrolled photo was reported as an
  orphan, so `--delete-orphans` would have deleted the whole face library.
- `Dockerfile` declared `VOLUME ["/data"]` before the `chown` to the non-root
  user. Docker discards volume changes made after the declaration, leaving
  `/data` owned by root and the container unable to write the database.
- Enrolment photos beyond the first were never recorded in the database, and
  re-enrolling or deleting a student left them on disk. Extra encodings now
  store their filename, and both paths clean up after themselves.

### Fixed (correctness)
- `db.create_class` returned `cur.lastrowid` after an `INSERT OR IGNORE` that
  inserted nothing, which on a reused connection is the previous insert's id:
  asking for an existing class handed back a different one. It also created a
  duplicate class on every run for an unclaimed class, because SQLite does not
  apply a UNIQUE constraint across NULLs.
- `/api/attendance/update` answered an HTML 500 when the student and session
  belonged to different classes of the same teacher; it now answers JSON 404.
- `/api/session/confirm` accepted any string as a date or period. A malformed
  date dropped the session out of every range filter and the Excel register.
- Flashed `warning` messages were styled and iconed as successes, so a
  rejected enrolment photo was reported with a green tick.
- Removing a student whose name contains an apostrophe broke the confirmation
  dialog.

### Fixed (security and resources)
- Stored XSS on the attendance page: student names and roll numbers were
  written into `innerHTML` unescaped.
- The login rate limiter kept one unbounded bucket per (IP, email) pair, so
  posting a fresh address each time exhausted the worker's memory.
- `render.yaml` disabled the `Secure` flag on the session cookie although
  Render serves the app over HTTPS.
- A scan read every row of `student_encodings` on the server, not just the
  class being scanned.

### Changed
- The photo-per-scan and photo-per-enrolment limits are published to the
  templates instead of being hardcoded in JavaScript, so `MAX_PHOTOS_PER_SCAN`
  now takes effect in the browser as well as on the server.
- The launcher scripts' offline fallback installs the same versions as
  `requirements.txt` rather than an older stack.
- Regenerated `static/app.css`; the committed copy was missing `bg-bdr`.

### Added
- `apitest.py`, an end-to-end HTTP suite covering the API fixes above, plus
  regression checks in `selftest.py`, `securitytest.py` and `rendertest.py`.

## 1.0.0 — Final submission — 2026-09-22

### Product
- Teacher accounts with per-teacher data isolation.
- Class, student, session and attendance management.
- Multi-photo face-recognition attendance with teacher confirmation.
- Confidence/review states, duplicate handling and manual corrections.
- Excel attendance export and responsive mobile-first interface.

### Recognition
- Multiple reference photographs per student.
- Enrolment quality checks for face size, sharpness and brightness.
- Tiled detection, small-face enlargement and low-resolution rescue pass.
- Runner-up margin and small-face penalty to reduce false identification.
- Calibration utility with precision, recall and zero-false-positive gates.

### Security and operations
- PBKDF2 password hashing and teacher ownership checks.
- CSRF validation, login rate limiting and security headers.
- Fixed-secret production validation and 12-hour sessions.
- Same-class attendance integrity and attendance-change audit records.
- SQLite WAL/busy-timeout hardening, maintenance backups and orphan reporting.
- Docker, Gunicorn, Render blueprint and persistent-storage guidance.

### Verification
- Authentication, database, recognition, image, template, calibration and security suites.
- Dependency vulnerability audit.
- Dockerfile validation.
- GitHub Actions checks passing before final merge.

### Declared limitations
- No liveness or anti-spoofing model.
- No email password reset or SSO.
- Teacher review is mandatory; recognition output is not auto-saved.
- Biometric consent, retention and legal compliance remain the deployment owner's responsibility.
