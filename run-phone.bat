@echo off
REM Start the server so the Android app can reach it.
REM
REM Same as run.bat, but bound to every network instead of this computer only.
REM The default bind is localhost, and from the phone that is indistinguishable
REM from typing the wrong address: it simply cannot connect.
REM
REM     run-phone.bat
REM
REM Then type the address it prints into the phone app.
setlocal
cd /d "%~dp0"
set HOST=0.0.0.0
echo Starting on all networks so your phone can reach this computer.
echo Only do this on a network you trust.
echo.
call run.bat %*
