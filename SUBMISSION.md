# FaceID Attendance — Final Project Submission

**Version:** 1.0.0  
**Author:** Om Gupta  
**Repository:** https://github.com/Omgupta78/minor-project  
**License:** All rights reserved

## Abstract

FaceID Attendance is a teacher-operated classroom attendance system built with
Python, Flask, dlib/face_recognition, SQLite and openpyxl. A teacher enrols
students with reference photographs, captures one or more classroom images,
reviews the suggested identities, corrects mistakes and confirms the session.
The system then stores attendance and produces a formatted Excel report.

The model never saves attendance automatically. Human confirmation is a core
safety requirement because face recognition can miss students or produce an
incorrect suggestion under poor lighting, distance, blur, occlusion or pose.

## Objectives

1. Reduce the time required to take classroom attendance.
2. Support several classroom photos so distant and partially visible students
   are less likely to be missed.
3. Keep a teacher in control of every saved attendance record.
4. Store classes, students, sessions and marks in a structured database.
5. Produce useful term-level attendance reports.
6. Document accuracy, privacy and operational limitations honestly.

## Main features

- Teacher signup, login and password hashing.
- Per-teacher class and data isolation.
- Student enrolment using up to five reference photographs.
- Photo-quality rejection for small, dark, bright or blurry faces.
- Multi-photo classroom scanning and best-sighting selection.
- Matched, review and unknown recognition states.
- Manual Present/Absent/Late corrections.
- Unique class/date/period attendance sessions.
- Attendance summary, register grid, detailed records and Excel export.
- HEIC/HEIF and EXIF-orientation support for phone photographs.
- Mobile-first interface that works without CDN dependencies.
- Docker and Render deployment configuration.

## Architecture

```text
Browser
   │
   ▼
Flask routes (app.py)
   ├── authentication and ownership (auth.py)
   ├── SQLite data layer (db.py)
   ├── face pipeline (recognition.py)
   ├── Excel reports (excel_report.py)
   └── hardened launcher (wsgi.py)
          ├── CSRF and rate limiting (security_runtime.py)
          └── attendance integrity/audit (integrity_runtime.py)
```

## Recognition workflow

1. Validate and decode each uploaded image.
2. Apply EXIF orientation and constrain processing size.
3. Detect faces using full-image, tiled or rescue detection as appropriate.
4. Enlarge small face crops before encoding.
5. Compare each encoding against enrolled reference encodings.
6. Require a sufficient distance threshold and runner-up margin.
7. Merge duplicate sightings and select the best image per student.
8. Present results to the teacher for correction.
9. Save only after explicit confirmation.

## Database entities

- `teachers`: account, password hash and account state.
- `classes`: teacher-owned class and subject.
- `students`: class roster and primary face encoding.
- `student_encodings`: additional reference encodings.
- `sessions`: one class/date/period attendance event.
- `attendance`: student status, confidence and marking method.
- `attendance_audit`: previous/new status and the teacher responsible.

## Running locally

### Windows

```text
Double-click run.bat
```

### macOS/Linux

```bash
chmod +x run.sh
./run.sh
```

Open `http://127.0.0.1:5000` and create the first teacher account.

## Manual setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python wsgi.py
```

## Automated verification

```bash
python authtest.py
python selftest.py
python smalltest.py
python qualitytest.py
python multitest.py
python heictest.py
python rendertest.py
python calibrationtest.py
python doctor.py
python securitytest.py
python build_css.py
```

GitHub Actions additionally runs `pip-audit` and validates the Dockerfile. The
final submission branch was merged only after the logic and Docker jobs passed.

## Accuracy evaluation

Create unseen images under `testset/<roll-number>/` and strangers under
`testset/unknown/`, then run:

```bash
python calibrate.py --folder testset --class-id 1
```

The release gate requires zero false positives, precision of at least 0.98 and
recall of at least 0.80 on the supplied evaluation set. Results are specific to
the camera, room, enrolled class and test photographs; they are not universal
accuracy claims.

## Security and privacy

- Passwords use salted PBKDF2-HMAC-SHA256 hashes.
- Production refuses a missing or short secret key.
- CSRF checks, login throttling and secure response headers are installed by
  the `wsgi.py` entry point.
- Teachers cannot access another teacher's classes or students.
- Attendance cannot connect a student to a session from another class.
- Student photos, databases, environment files and generated reports are
  excluded from the current Git tree.
- One private installation per school is recommended.

## Limitations

- There is no liveness detection; a printed or screen-displayed face may fool
  the model.
- Accuracy varies with lighting, distance, blur, pose, occlusion and demographic
  characteristics.
- Password reset by email and SSO are not implemented.
- SQLite is suitable for a small school deployment, not thousands of concurrent
  users.
- Deployment owners must obtain consent and define deletion/retention policies
  for biometric data.
- Teacher supervision and confirmation remain mandatory.

## Demonstration sequence

1. Sign in as a teacher.
2. Create a class.
3. Enrol two or more students with clear reference photographs.
4. Upload one or more classroom images.
5. Run identification and explain matched/review/unknown states.
6. Correct one attendance status manually.
7. Confirm and save the session.
8. Open Records and download the Excel report.
9. Explain the calibration utility and declared limitations.

## Final status

Version 1.0.0 contains the complete academic demonstration workflow, automated
regression tests, production launch configuration, security hardening and
explicit model/privacy limitations. It is suitable for supervised project
evaluation and a controlled school pilot after consent, calibration and backup
requirements are completed.
