# Production release checklist

A green UI is not a production release. Complete every blocking item per school.

## Build and regression
- [ ] GitHub Actions passes, including CSS drift, dependency audit, security tests and Dockerfile validation.
- [ ] Login, signup, logout, ownership, same-class attendance and Excel export pass in a real Flask client.
- [ ] Start with `wsgi.py` / `wsgi:app`; never bypass the hardening with `app:app`.
- [ ] A backup made with SQLite backup semantics restores on another machine.

## Recognition acceptance
- [ ] Run `calibrate.py` on unseen per-student and unknown-person photos.
- [ ] Zero false positives, precision >= 0.98 and recall >= 0.80.
- [ ] Also test labelled classroom group photos through the complete `/api/scan` flow.
- [ ] Re-test after changing camera, room, model, threshold or enrolment set.
- [ ] Teacher review remains mandatory; model output is never auto-saved.

## Privacy and consent
- [ ] Lawful basis and verifiable consent exist for every student.
- [ ] A retention period and deletion owner are named.
- [ ] Faces, DB, `.env`, reports and backups are absent from current Git and all history.
- [ ] Run `python maintenance.py` regularly; review before `--delete-orphans`.
- [ ] Staff understand there is no liveness/anti-spoofing control.

## Hosting
- [ ] Fixed 32+ character `SECRET_KEY`; `PRODUCTION=1`; HTTPS; `COOKIE_SECURE=1`.
- [ ] `ALLOW_SIGNUP=0`; approved teachers are provisioned deliberately.
- [ ] Persistent storage, encrypted backups, restore drills and monitored `/healthz`.
- [ ] Proxy accepts 64 MB and has a 300-second timeout.
- [ ] Start with one Gunicorn worker; load-test before increasing concurrency.
- [ ] Prefer one private instance per school.

## Pilot
- [ ] Run at least five supervised sessions and record errors and processing time.
- [ ] No wrong-name result may be silently accepted.
- [ ] A named human can disable service and revert to manual attendance.
