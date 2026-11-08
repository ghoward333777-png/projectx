@echo off
rem QueryBook launcher for Windows. Double-click, or run from a terminal with extra flags.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m querybook serve --open %*
) else (
  python -m querybook serve --open %*
)
if errorlevel 1 pause
