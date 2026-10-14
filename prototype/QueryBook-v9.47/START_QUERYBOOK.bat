@echo off
REM ============================================================
REM  QueryBook - ONE-CLICK start for Windows.  Double-click this.
REM  It finds (or installs) Python, runs a self-check, starts the
REM  app, and opens it in your browser. The FIRST time it asks
REM  where to keep your data (point it at your external drive);
REM  after that it remembers for 50 launches. Nothing is deleted.
REM ============================================================
setlocal enableextensions enabledelayedexpansion
title QueryBook
cd /d "%~dp0"

echo ============================================================
echo   QueryBook - starting up
echo ============================================================
echo.

REM --- 1. Find Python; try to install it automatically if missing ------------
set "PY="
where py        >nul 2>&1 && set "PY=py"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo Python is needed. Trying to install it automatically ^(winget^)...
  where winget >nul 2>&1 && winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  where py     >nul 2>&1 && set "PY=py"
  if not defined PY ( where python >nul 2>&1 && set "PY=python" )
)
if not defined PY (
  echo.
  echo [PROBLEM] Could not find or install Python automatically.
  echo   Opening the download page. Install Python, TICK "Add Python to PATH",
  echo   then double-click this file again.
  start "" https://www.python.org/downloads/
  pause & exit /b 1
)
if not exist "qb_api.py" ( echo [PROBLEM] qb_api.py is missing from this folder. & pause & exit /b 1 )

REM --- 1b. Show WHICH VERSION this folder is, so you never run an old copy ----
echo ------------------------------------------------------------
for /f "delims=" %%V in ('%PY% qb_api.py version 2^>nul') do echo   %%V
echo   Folder: %~dp0
echo ------------------------------------------------------------
echo.

REM --- 2. Self-diagnostic (plain-English; changes nothing) --------------------
echo Running a quick self-check...
echo.
%PY% qb_doctor.py
echo.

REM --- 3. Free the port if an old QueryBook is still running ------------------
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8099" ^| findstr LISTENING') do (
  echo   Stopping a previous QueryBook on port 8099 ^(PID %%P^)...
  taskkill /F /PID %%P >nul 2>&1
)

REM --- 4. (The server opens your browser itself, at the correct address.) -----

echo ------------------------------------------------------------
echo  Starting QueryBook.
echo  * The FIRST launch asks WHERE to keep your data - point it at
echo    your external drive (or press Enter for the suggested one).
echo  * It then remembers your choice for the next 50 launches.
echo  * Leave this window open while you use QueryBook; close it to stop.
echo  * Your browser opens at  http://127.0.0.1:8099/dashboard
echo ------------------------------------------------------------
echo.

REM --- 5. Run the app in THIS window so the data question is visible ----------
%PY% qb_api.py

echo.
echo ============================================================
echo   QueryBook has stopped.
echo   For a health check any time, double-click  CHECK_QUERYBOOK.bat
echo   To change where your data lives:  %PY% qb_api.py configure
echo ============================================================
pause
endlocal
