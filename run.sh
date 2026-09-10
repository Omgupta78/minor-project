#!/usr/bin/env bash
# One-command start for macOS and Linux.
#
#     ./run.sh
#
# Creates a virtual environment, installs what it can, starts the server and
# opens http://127.0.0.1:5000 in your browser.
#
# The face engine (dlib) is installed separately from the rest, on purpose: it
# is the one dependency that commonly fails to build, and a failure there
# should not stop the app from starting. Every page still works without it.

set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
PORT="${PORT:-5000}"

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "ERROR: $PY not found. Install Python 3.10-3.12 first."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "[1/3] Creating virtual environment (.venv)..."
  "$PY" -m venv .venv
else
  echo "[1/3] Using existing virtual environment (.venv)"
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip

echo "[2/3] Installing web dependencies..."
python -m pip install --quiet \
  "Flask>=3.0.0" "Werkzeug>=3.0.0" "openpyxl>=3.1.0" \
  "numpy>=1.24.0,<2.0.0" "Pillow>=10.0.0" "pillow-heif>=0.13.0"

if python -c "import face_recognition" >/dev/null 2>&1; then
  echo "      Face engine already installed."
else
  echo "      Installing face engine (this can take several minutes)..."
  if ! python -m pip install --quiet "dlib>=19.24.0" 2>/dev/null; then
    echo "      Source build failed, trying the prebuilt dlib-bin wheel..."
    python -m pip install --quiet dlib-bin || true
  fi
  python -m pip install --quiet "face_recognition>=1.3.0" "face-recognition-models>=0.3.0" \
    "opencv-python>=4.8.0" || true

  if ! python -c "import face_recognition" >/dev/null 2>&1; then
    echo
    echo "      NOTE: the face engine did not install."
    echo "      The app will still start and every page will work, but"
    echo "      scanning is disabled. To fix it install a compiler:"
    echo "        macOS:  xcode-select --install && brew install cmake"
    echo "        Ubuntu: sudo apt install build-essential cmake python3-dev"
    echo "      then run this script again."
    echo
  fi
fi

echo "[3/3] Starting the server..."
export OPEN_BROWSER="${OPEN_BROWSER:-1}"
export PORT
exec python app.py
