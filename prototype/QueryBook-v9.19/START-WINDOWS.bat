@echo off
REM ============================================================
REM   QueryBook - Windows.  Double-click this file.
REM   It asks WHERE to save facts (external drive) right away,
REM   then remembers your choice for next time.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "CFG=%~dp0querybook_store.txt"
set "LAST="
if exist "%CFG%" set /p LAST=<"%CFG%"

echo ============================================================
echo   QueryBook - choose where to save facts
echo ============================================================
echo.
echo Where should facts be saved?
echo.
echo   FASTEST: type  C   to use your internal drive  (C:\QueryBook\store).
echo            Internal SSD harvests MUCH faster than USB. You can copy the
echo            store folder to an external drive later - it is just files.
echo.
echo   Or type an EXTERNAL drive letter below. Detected drives:
echo.
for %%D in (D E F G H I J K L M N O P Q R S T U V W X Y Z) do (
  if exist %%D:\ echo     %%D:\
)
echo.
if defined LAST echo   Last time you used:  !LAST!
echo.

:ASK
set "SEL="
if defined LAST (
  set /p "SEL=Type C (internal, fast), a drive letter, or a full path; Enter = reuse last: "
) else (
  set /p "SEL=Type C for internal (fast), or an external drive letter (e.g. E): "
)

REM --- resolve the choice into STORE ---
if "!SEL!"=="" (
  if defined LAST ( set "STORE=!LAST!" ) else ( echo Please type a drive letter. & goto ASK )
) else (
  set "RAW=!SEL!"
  REM strip trailing backslash
  if "!RAW:~-1!"=="\" set "RAW=!RAW:~0,-1!"
  echo !RAW!| findstr /r "[:\\]" >nul
  if errorlevel 1 (
    REM single letter given -> build a path on that drive
    set "STORE=!RAW!:\QueryBook\store"
  ) else (
    set "STORE=!RAW!"
  )
)

REM --- make sure the drive exists and the folder can be created ---
set "DRV=!STORE:~0,2!"
if not exist "!DRV!\" (
  echo.
  echo Drive !DRV! is not available. Is the external drive plugged in?
  echo.
  goto ASK
)
if not exist "!STORE!" mkdir "!STORE!" 2>nul
if not exist "!STORE!" ( echo Could not create !STORE! - check the drive is not full or write-protected. & pause & exit /b 1 )

REM --- remember the choice ---
> "%CFG%" echo !STORE!

python --version >nul 2>&1
if errorlevel 1 (
  echo Python was not found. Install it from https://www.python.org/downloads/
  echo During install, TICK "Add Python to PATH", then double-click this file again.
  pause & exit /b 1
)
if not exist "qb_api.py" ( echo qb_api.py is missing from this folder. & pause & exit /b 1 )

set "QB_DATA_DIR=!STORE!"
set "QB_BIND=127.0.0.1:8090"
set "QB_CHAT_HTML=%~dp0chat.html"
set "QB_CONSOLE_HTML=%~dp0console.html"
set "QB_DASHBOARD_HTML=%~dp0dashboard.html"
set "QB_LANGUAGE_HTML=%~dp0language.html"
set "QB_GUIDE_HTML=%~dp0guide.html"
set "QB_MONITOR_HTML=%~dp0monitor.html"

echo.
echo ============================================================
echo   Saving facts to:  !STORE!
echo   Starting QueryBook...
echo ============================================================
echo.

REM Free port 8090 if a previous QueryBook is STILL running on it. A stale server
REM keeps serving an OLD page - the usual symptom is a dead "Language Lab" link.
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8090" ^| findstr LISTENING') do (
  echo   Stopping a previous QueryBook on port 8090 ^(PID %%P^) so you get this version...
  taskkill /F /PID %%P >nul 2>&1
)

start "QueryBook server" cmd /c python qb_api.py
ping -n 3 127.0.0.1 >nul
start "" http://127.0.0.1:8090/dashboard

echo QueryBook is open in your browser:
echo    Dashboard:     http://127.0.0.1:8090/dashboard
echo    Language Lab:  http://127.0.0.1:8090/language   (open this directly if the menu link ever fails)
echo.
echo  1) Click "Start harvest" (or "Run 24x7") to collect facts.
echo  2) Click "24x7 Awake: OFF" to keep this PC from sleeping.
echo  3) Try the Language Lab (teach English) and the Guide from the top menu.
echo.
echo Leave the small server window open while it runs. Close it to stop.
echo.
pause
