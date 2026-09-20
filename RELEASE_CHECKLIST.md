# Production release checklist

A green UI is not a production release. Complete every blocking item for each
school deployment.

## 1. Build and regression
- [ ] `python doctor.py` reports the current build.
- [ ] All offline suites pass locally or in GitHub Actions.
- [ ] Login, signup, logout, ownership and Excel export work in real Flask.
- [ ] A database backup restores on a separate machine.

## 2. Recognition acceptance
Build `testset/<roll number>/` from unseen photos and `testset/unknown/` with at
least ten people who are not enrolled.

```bash
python calibrate.py --folder testset --class-id 1
```

- [ ] Calibration passes with zero false positives, precision >= 0.98 and
      recall >= 0.80.
- [ ] Apply the generated threshold only after reviewing the JSON report.
- [ ] Re-test after changing camera, room, model or enrolment set.
- [ ] Teacher review remains mandatory; never auto-save model output.

## 3. Privacy and consent
- [ ] School has lawful basis and verifiable consent for every student.
- [ ] A retention period and deletion owner are named.
- [ ] Faces, database, `.env`, reports and backups are absent from Git/history.
- [ ] Staff understand there is no liveness/anti-spoofing control.

## 4. Hosting
- [ ] Fixed random `SECRET_KEY`; HTTPS; `COOKIE_SECURE=1`.
- [ ] `ALLOW_SIGNUP=0` after approved teachers register.
- [ ] Persistent storage for database and faces.
- [ ] Proxy accepts 64 MB uploads and has a 300-second timeout.
- [ ] `/healthz` monitored; encrypted backups and restore drills scheduled.
- [ ] Prefer one instance per school over a global biometric database.

## 5. Pilot
- [ ] Run at least five supervised sessions.
- [ ] Record misses, wrong names, processing time and manual corrections.
- [ ] No wrong-name result may be silently accepted.
- [ ] A named human can disable service and revert to manual attendance.
