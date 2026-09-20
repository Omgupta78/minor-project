#!/usr/bin/env bash
# One-command local start for macOS and Linux.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
PORT="${PORT:-5000}"
if ! command -v "$PY" >/dev/null 2>&1; then echo "ERROR: $PY not found. Install Python 3.10-3.12 first."; exit 1; fi
if [ ! -d .venv ]; then "$PY" -m venv .venv; fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt || {
  echo "Full install failed; installing the web-only dependencies. Scanning may be unavailable."
  python -m pip install --quiet Flask==3.0.3 Werkzeug==3.0.6 openpyxl==3.1.5 numpy==1.26.4 Pillow==10.4.0 pillow-heif==0.18.0
}
export OPEN_BROWSER="${OPEN_BROWSER:-1}" PORT COOKIE_SECURE="${COOKIE_SECURE:-0}" PRODUCTION=0
if [ -z "${SECRET_KEY:-}" ]; then
  mkdir -p instance
  if [ ! -f instance/secret_key ]; then python -c "import secrets; print(secrets.token_hex(32))" > instance/secret_key; fi
  SECRET_KEY="$(cat instance/secret_key)"; export SECRET_KEY
fi
exec python wsgi.py
