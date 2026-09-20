# Security policy

## Supported deployment
Use one private instance per school, HTTPS, persistent access-controlled storage,
daily encrypted backups and `ALLOW_SIGNUP=0`. Launch through `wsgi.py` (or
`gunicorn ... wsgi:app`), never `app:app`, so CSRF, rate limiting, database
hardening and production-secret validation are active. Never enable Flask debug
mode on a shared network.

Required settings:
- fixed random `SECRET_KEY` (production refuses a missing/short key);
- `PRODUCTION=1`, `COOKIE_SECURE=1`, and HTTPS;
- persistent database/face folders and tested backups;
- one Gunicorn worker while SQLite and CPU-heavy recognition are used;
- OS and dependency security updates.

## Biometric data
Photos and embeddings are sensitive biometric data. Collect verifiable consent,
publish retention/deletion rules, minimise access, and provide student deletion.
Never commit faces, databases, exports, backups or `.env` files. Current-tree
deletion is not history deletion: use `git filter-repo`, rotate the public repo if
necessary, and verify old commits when any biometric file was previously pushed.

## Controls included
The hardened entry point provides same-origin/session CSRF validation, login
rate limiting, a 12-hour session lifetime, security headers, SQLite WAL/busy
timeout settings, closed-by-default signup, and a same-class guard for attendance
mutations whose route contains both IDs.

## Reporting
Do not open a public issue containing credentials, student data, face images or
a working exploit. Contact the repository owner privately with personal data removed.

## Non-goals
There is still no email password reset, liveness detection, tamper-evident audit
log, SSO, central key management or automatic legal compliance. Teacher review
is mandatory and deployment owners remain responsible for consent and retention.
