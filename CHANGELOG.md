# Changelog

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
