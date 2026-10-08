@echo off
REM ============================================================
REM  QueryBook - one-click start for Windows.
REM  Double-click this file. It finds your data automatically,
REM  starts the app, and opens it in your browser.
REM  Nothing is moved or deleted.
REM ============================================================
setlocal enableextensions enabledelayedexpansion
title QueryBook
cd /d "%~dp0"

echo ============================================================
echo   Starting QueryBook...
echo ============================================================
echo.

REM --- 1. Find Python ---------------------------------------------------------
set "PY="
where py        >nul 2>&1 && set "PY=py"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo [PROBLEM] Python is not installed ^(or not on PATH^).
  echo.
  echo   1. Download it from:  https://www.python.org/downloads/
  echo   2. During setup, TICK the box "Add Python to PATH".
  echo   3. Then double-click START_QUERYBOOK.bat again.
  echo.
  pause
  exit /b 1
)

REM --- 2. Find your data folder automatically --------------------------------
REM Honour an existing QB_DATA_DIR; otherwise auto-locate the richest store
REM under D:\QB, this folder, and your user profile.
if not defined QB_DATA_DIR (
  for /f "usebackq delims=" %%p in (`%PY% qb_find_store.py --best "D:\QB" "%USERPROFILE%" 2^>nul`) do set "QB_DATA_DIR=%%p"
)

if defined QB_DATA_DIR (
  echo Using your data folder:  !QB_DATA_DIR!
) else (
  echo No existing data found yet - a new library will be created and kept in:
  echo    %USERPROFILE%\.querybook\store
  echo    ^(your future data stays here for every version - it will not vanish on upgrade^)
)
echo.

REM --- 3. Open the browser shortly after the server starts -------------------
start "" cmd /c "timeout /t 3 >nul & start "" http://127.0.0.1:8099/"

REM --- 4. Run the app (foreground; this window shows its log) -----------------
echo Opening http://127.0.0.1:8099/ in your browser...
echo (Leave this window open while you use QueryBook. Close it to stop.)
echo.
%PY% qb_api.py

echo.
echo ============================================================
echo   QueryBook has stopped.
echo   If you saw an error above, run  CHECK_QUERYBOOK.bat  for a
echo   plain-English diagnosis.
echo ============================================================
pause
endlocal
