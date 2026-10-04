@echo off
REM Plain-English health check for QueryBook. Double-click to run.
setlocal enableextensions
title QueryBook - Check
cd /d "%~dp0"
set "PY="
where py        >nul 2>&1 && set "PY=py"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo Python is not installed. Get it from https://www.python.org/downloads/
  echo During setup, tick "Add Python to PATH". Then run this again.
  pause & exit /b 1
)
%PY% qb_doctor.py
echo.
pause
endlocal
