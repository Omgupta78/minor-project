# Security policy

## Supported deployment
The recommended model is one private instance per school. Use HTTPS, persistent
storage, daily encrypted backups and `ALLOW_SIGNUP=0` after staff register.
Never enable Flask debug mode on a shared network.

Required production settings:
- a fixed random `SECRET_KEY`;
- `COOKIE_SECURE=1` behind HTTPS;
- database and face folders on persistent, access-controlled storage;
- operating-system and Python dependency updates;
- restricted network access where possible.

## Biometric data
Student photographs and embeddings are sensitive biometric data. Collect
verifiable consent, publish retention/deletion rules, minimise access, and give
schools a process to remove a student. Never commit `faces/`, databases,
exports or `.env` files. Purge Git history if these were committed before.

## Reporting a vulnerability
Do not open a public issue containing credentials, student data, face images or
a working exploit. Contact the repository owner privately with personal data
removed.

## Non-goals
The release does not provide email password reset, liveness detection, a
tamper-evident audit log, SSO, central key management or compliance by itself.
Deployment owners remain responsible for those controls.
