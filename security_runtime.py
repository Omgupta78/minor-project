"""Security and integrity controls shared by local and production entry points.

The original app remains importable for offline tests. Real launches use wsgi.py,
which installs these controls exactly once.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from flask import abort, jsonify, request, session

_INSTALLED = False
_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)


def _true(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def bootstrap_environment() -> None:
    """Fail closed before app.py can create a per-worker random secret."""
    production = _true("PRODUCTION") or bool(os.environ.get("RENDER"))
    key = os.environ.get("SECRET_KEY", "")
    if production and len(key) < 32:
        raise RuntimeError("SECRET_KEY must be a fixed random value of at least 32 characters in production")
    os.environ.setdefault("ALLOW_SIGNUP", "0")


def _csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def _same_origin(value: str) -> bool:
    try:
        source = urlsplit(value)
        target = urlsplit(request.host_url)
        return source.scheme == target.scheme and source.netloc == target.netloc
    except Exception:
        return False


def _csrf_ok() -> bool:
    expected = session.get("_csrf_token")
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    if expected and supplied and hmac.compare_digest(str(expected), str(supplied)):
        return True
    # Supports the first non-JavaScript form submission while still rejecting
    # cross-site forms. Modern browsers send Origin or Referer on POST.
    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    return bool((origin and _same_origin(origin)) or (referer and _same_origin(referer)))


def _rate_key() -> str:
    email = (request.form.get("email") or "").strip().lower()
    email_hash = hashlib.sha256(email.encode()).hexdigest()[:16]
    return f"{request.remote_addr or 'unknown'}:{email_hash}"


# Cap on how many distinct (ip, email) buckets are remembered. Without it a
# script that posts a different email each time adds one deque per attempt and
# the worker's memory grows until it is killed -- the rate limiter itself
# becomes the denial of service it was added to prevent.
_MAX_BUCKETS = int(os.environ.get("LOGIN_RATE_BUCKETS", "4096"))


def _expire_buckets(now: float, window: int) -> None:
    """Drop buckets whose attempts have all aged out."""
    for key in [k for k, v in _ATTEMPTS.items() if not v or now - v[-1] > window]:
        del _ATTEMPTS[key]


def _login_limited() -> bool:
    now = time.monotonic()
    window = int(os.environ.get("LOGIN_RATE_WINDOW", "900"))
    limit = int(os.environ.get("LOGIN_RATE_LIMIT", "5"))
    if len(_ATTEMPTS) >= _MAX_BUCKETS:
        _expire_buckets(now, window)
        if len(_ATTEMPTS) >= _MAX_BUCKETS:
            # Still full of live buckets: this is an attack, not normal use.
            # Refusing is the safe direction to fail in.
            return True
    bucket = _ATTEMPTS[_rate_key()]
    while bucket and now - bucket[0] > window:
        bucket.popleft()
    if len(bucket) >= limit:
        return True
    bucket.append(now)
    return False


def _classes_match() -> bool:
    values = request.view_args or {}
    session_id = values.get("session_id")
    student_id = values.get("student_id")
    if session_id is None or student_id is None:
        return True
    import db
    with db.session_scope() as conn:
        row = conn.execute(
            """SELECT 1 FROM sessions x JOIN students s ON s.class_id = x.class_id
                 WHERE x.id = ? AND s.id = ?""",
            (session_id, student_id),
        ).fetchone()
    return row is not None


def _harden_database() -> None:
    import db
    original = db.connect
    if getattr(original, "_faceid_hardened", False):
        return

    def connect(*args, **kwargs):
        conn = original(*args, **kwargs)
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    connect._faceid_hardened = True
    db.connect = connect
    with db.session_scope() as conn:
        conn.execute("PRAGMA journal_mode = WAL")


def _inject_client(response):
    if response.mimetype == "text/html" and response.status_code < 400:
        body = response.get_data(as_text=True)
        marker = "</body>"
        tag = '<script src="/static/security.js" defer></script>'
        if marker in body and tag not in body:
            response.set_data(body.replace(marker, tag + marker, 1))
            response.headers.pop("Content-Length", None)
    return response


def install_security(app) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
        hours=int(os.environ.get("SESSION_HOURS", "12"))
    )
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True

    _harden_database()

    @app.before_request
    def security_gate():
        _csrf_token()
        if request.method == "POST" and request.endpoint == "login" and _login_limited():
            return jsonify(error="Too many login attempts. Try again later."), 429
        if request.method not in {"GET", "HEAD", "OPTIONS", "TRACE"} and not _csrf_ok():
            abort(403, description="CSRF validation failed")
        if not _classes_match():
            abort(404)

    @app.after_request
    def security_headers(response):
        response = _inject_client(response)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        response.set_cookie(
            "csrf_token", _csrf_token(), secure=app.config.get("SESSION_COOKIE_SECURE", False),
            httponly=False, samesite="Strict"
        )
        return response
