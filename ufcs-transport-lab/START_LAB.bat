@echo off
REM ============================================================
REM  QueryBook UFCS-FQL Lab - one-click start for Windows.
REM  Double-click this file. The first run downloads a private
REM  copy of PHP, ffmpeg and zstd into this folder (about 235 MB,
REM  no admin rights, nothing installed system-wide), then opens
REM  the lab in your browser.
REM ============================================================
setlocal
title QueryBook UFCS-FQL Lab
cd /d "%~dp0"

echo ============================================================
echo   Starting the QueryBook UFCS-FQL Lab...
echo ============================================================
echo.

REM --- 1. Find Python ---------------------------------------------------------
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo [PROBLEM] Python is not installed ^(or not on PATH^).
  echo.
  echo   1. Download it from:  https://www.python.org/downloads/
  echo   2. During setup, TICK the box "Add Python to PATH".
  echo   3. Then double-click START_LAB.bat again.
  echo.
  pause
  exit /b 1
)

REM --- 2. Set up (first run only) and start ------------------------------------
%PY% qb_lab.py %*

echo.
echo ============================================================
echo   The lab has stopped.
echo   If you saw [PROBLEM] above, follow its instructions, or
echo   double-click CHECK_LAB.bat for a plain-English diagnosis.
echo ============================================================
pause
endlocal
