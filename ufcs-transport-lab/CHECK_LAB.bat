@echo off
REM QueryBook UFCS-FQL Lab - plain-English health check. Changes nothing.
setlocal
title QueryBook UFCS-FQL Lab - check
cd /d "%~dp0"
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo [PROBLEM] Python is not installed. Get it from https://www.python.org/downloads/
  echo           and TICK "Add Python to PATH" during setup.
  pause
  exit /b 1
)
%PY% qb_lab.py check
echo.
echo Only [PROBLEM] and [NEED] items matter. [OPTIONAL] and [opt] items never stop the lab.
pause
endlocal
