# Changelog

## Unreleased — 120-student hall capacity

Measured against a 4000x3000 photograph of 120 real people in six rows, front
row 4 m away and back row 15 m away. `RECOGNITION.md` holds the full results
and `hallbench.py` reproduces them.

### Fixed
- **Scanning lost most of the class.** `decode_image_bytes()` decoded uploads
  with OpenCV, and when `cv2.imdecode` is the first image decode in a process
  dlib's detector is crippled for the life of that process: the hall photo
  gave 7 faces instead of 121 through `/api/scan`, and 0 on the next scan in
  the same worker. Enrolment goes through Pillow and was never affected, so
  this looked like "the back of the room doesn't work". Pillow is now the
  primary decoder, OpenCV the fallback, and `decodetest.py` asserts both paths
  detect the same faces.

### Changed — recognition
- `SMALL_FACE_PENALTY` now defaults to 0. At 0.04 it rejected 15 of 97 seated
  students and prevented no false matches at all, because in a hall nearly
  every face is an enlarged one.
- `MATCH_DISTANCE` 0.50 -> 0.52, worth three more students per photo with no
  stranger wrongly named. 0.54 is where that stops being true.
- Faces are encoded across worker processes. dlib holds the GIL so threads
  give 1.02x; four processes give 3.7x, taking a 120-face scan from 36 s to
  18 s. `SCAN_WORKERS` controls it, the pool declines when the caller has no
  `if __name__ == "__main__":` guard (workers would re-run the script), and
  any failure falls back to serial rather than failing the scan.
- The runner-up comparison is vectorised; it ran 120 faces x 600 gallery rows
  in Python on every photo.
- Scans report face sizes (`median_face_px`, `smallest_face_px`,
  `faces_too_small`). Below about 45 px a face is detected but not
  identifiable, and no threshold changes that — the fix is a closer photo, so
  the app now says so.

### Changed — using it with 120 students
- The review list filters, searches and repaints one row per tap instead of
  rebuilding all 120, and offers "accept all suggested" so a hall session is
  not twenty individual clicks.
- The scan returns advice the teacher can act on: how many faces were too
  small to identify, and which students are enrolled from a single photo
  (three photos is worth about seven more students per 120).
- The students page shows each student's reference-photo count and flags
  anyone enrolled from one photo.
- The scan banner shows elapsed seconds; a hall photo takes tens of them.
- `MAX_UPLOAD_MB` 64 -> 96, since eight photos from a 48 MP phone overflowed.

### Added
- `halltest.py` — 120 students end to end (scan, confirm, records, register,
  Excel) against a stub, so CI covers hall scale without dlib.
- `decodetest.py` — the upload and file decode paths must agree.
- `hallbench.py` — composes a hall from a labelled folder and reports
  identification rate against face width, row by row.
- `RECOGNITION.md` — the measurements, including what was tried and rejected.
- `rendertest.py` now parses every inline script block, and CI runs the new
  suites.

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
