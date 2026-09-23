@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (set "PYCMD=py -3") else (set "PYCMD=python")
%PYCMD% --version >nul 2>&1
if errorlevel 1 (echo ERROR: Python was not found.& exit /b 1)
if not exist ".venv" %PYCMD% -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
if errorlevel 1 (
  echo Full install failed; installing web-only dependencies. Scanning may be unavailable.
  python -m pip install --quiet Flask==3.1.3 Werkzeug==3.1.6 openpyxl==3.1.5 numpy==1.26.4 Pillow==12.3.0 pillow-heif==1.3.0
)
set OPEN_BROWSER=1
set COOKIE_SECURE=0
set PRODUCTION=0
if not exist "instance" mkdir instance
if not exist "instance\secret_key" python -c "import secrets; print(secrets.token_hex(32))" > instance\secret_key
for /f "usebackq delims=" %%K in ("instance\secret_key") do set SECRET_KEY=%%K
python wsgi.py
pause
