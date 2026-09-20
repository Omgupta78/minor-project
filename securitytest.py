"""Fast tests for the hardened WSGI middleware; no dlib required."""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("ATTENDANCE_DB", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-characters")
os.environ.setdefault("COOKIE_SECURE", "0")
os.environ.setdefault("LOGIN_RATE_LIMIT", "2")

from flask import Flask
import security_runtime

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]

@app.get("/")
def home():
    return "<html><body><form method='post'></form></body></html>"

@app.post("/login")
def login():
    return "ok"

security_runtime._INSTALLED = False
security_runtime._ATTEMPTS.clear()
security_runtime._harden_database = lambda: None
security_runtime.install_security(app)
client = app.test_client()

r = client.get("/")
assert r.status_code == 200
assert b"/static/security.js" in r.data
assert r.headers["X-Frame-Options"] == "DENY"

assert client.post("/login", data={"email": "a@example.com"}).status_code == 403
headers = {"Origin": "http://localhost"}
assert client.post("/login", data={"email": "a@example.com"}, headers=headers).status_code == 200
assert client.post("/login", data={"email": "a@example.com"}, headers=headers).status_code == 429

print("securitytest: all checks passed")
