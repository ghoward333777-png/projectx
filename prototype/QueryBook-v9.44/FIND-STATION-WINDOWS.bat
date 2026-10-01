@echo off
REM ============================================================
REM   QueryBook - FIND MY STATION.  Double-click this file on
REM   your DEV / monitoring device (NOT the learning station).
REM   It listens on your network and prints the exact links to
REM   open the station's Monitor. No IP typing, no static IP.
REM ============================================================
cd /d "%~dp0"
python --version >nul 2>&1
if errorlevel 1 (
  py --version >nul 2>&1
  if errorlevel 1 (
    echo Python was not found. Install it from https://www.python.org/downloads/
    pause & exit /b 1
  )
  set "PY=py"
) else (
  set "PY=python"
)
if not exist "qb_api.py" ( echo qb_api.py is missing from this folder. & pause & exit /b 1 )
echo.
echo Searching your network for the QueryBook station...
echo (The station must be running, and both devices on the same network.)
echo.
%PY% qb_api.py discover
echo.
echo Tip: copy one of the http://... links above into your browser.
pause
