@echo off
REM QueryBook History ^& News - double-click to start. Leave the window open while you use it.
title QueryBook History ^& News
cd /d "%~dp0"
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY where python >nul 2>nul && set PY=python
if not defined PY (
  echo.
  echo  Python 3 is not installed on this computer.
  echo  Install it from https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^),
  echo  then double-click this file again.
  echo.
  start "" https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% app.py %*
if errorlevel 1 (
  echo.
  echo  QueryBook History ^& News stopped with an error. The details are above and in the log file in your data folder.
  pause
)
