@echo off
REM One-command start for Windows. Double-click this file, or run it from cmd.
REM
REM Creates a virtual environment, installs what it can, starts the server
REM and opens http://127.0.0.1:5000 in your browser.
REM
REM The face engine (dlib) is installed separately from the rest on purpose:
REM it is the one dependency that commonly fails to build, and that failure
REM should not stop the app from starting. Every page still works without it.

setlocal
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (set "PYCMD=py -3") else (set "PYCMD=python")

%PYCMD% --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python was not found.
  echo Install Python 3.10-3.12 from python.org and tick "Add Python to PATH".
  pause
  exit /b 1
)

if not exist ".venv" (
  echo [1/3] Creating virtual environment ^(.venv^)...
  %PYCMD% -m venv .venv
) else (
  echo [1/3] Using existing virtual environment ^(.venv^)
)

call .venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip

echo [2/3] Installing web dependencies...
python -m pip install --quiet "Flask>=3.0.0" "Werkzeug>=3.0.0" "openpyxl>=3.1.0" "numpy>=1.24.0,<2.0.0" "Pillow>=10.0.0" "pillow-heif>=0.13.0"

python -c "import face_recognition" >nul 2>&1
if %errorlevel%==0 (
  echo       Face engine already installed.
) else (
  echo       Installing face engine ^(this can take several minutes^)...
  REM dlib-bin is a prebuilt wheel: no Visual Studio build tools needed.
  python -m pip install --quiet dlib-bin
  if errorlevel 1 python -m pip install --quiet "dlib>=19.24.0"
  python -m pip install --quiet "face_recognition>=1.3.0" "face-recognition-models>=0.3.0" "opencv-python>=4.8.0"

  python -c "import face_recognition" >nul 2>&1
  if errorlevel 1 (
    echo.
    echo       NOTE: the face engine did not install.
    echo       The app will still start and every page will work, but
    echo       scanning is disabled. To fix it, install
    echo       "Visual Studio Build Tools" with the
    echo       "Desktop development with C++" workload, then run this again.
    echo.
  )
)

echo [3/3] Starting the server...
set OPEN_BROWSER=1
python app.py

echo.
echo Server stopped.
pause
