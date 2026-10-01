@echo off
REM ============================================================
REM   QueryBook - SECURE REMOTE MODE (Windows)
REM   Listens on your whole network so you can watch/control it
REM   from your phone over a PRIVATE network (e.g. Tailscale),
REM   and requires a PASSWORD. Use on a private network only.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "CFG=%~dp0querybook_store.txt"
set "STORE=C:\QueryBook\store"
if exist "%CFG%" set /p STORE=<"%CFG%"
if not exist "!STORE!" mkdir "!STORE!" 2>nul

echo ============================================================
echo   QueryBook - SECURE REMOTE MODE
echo ============================================================
echo.
echo Saving facts to: !STORE!
echo.
set "PW="
set /p "PW=Set an access password (anyone with it can view/control): "
if "!PW!"=="" ( echo A password is required for remote mode. & pause & exit /b 1 )

python --version >nul 2>&1
if errorlevel 1 ( echo Python not found. Install from https://www.python.org/downloads/ and tick "Add to PATH". & pause & exit /b 1 )
if not exist "qb_api.py" ( echo qb_api.py missing from this folder. & pause & exit /b 1 )

set "QB_DATA_DIR=!STORE!"
set "QB_BIND=0.0.0.0:8090"
set "QB_ACCESS_TOKEN=!PW!"
set "QB_CHAT_HTML=%~dp0chat.html"
set "QB_CONSOLE_HTML=%~dp0console.html"
set "QB_DASHBOARD_HTML=%~dp0dashboard.html"
set "QB_LANGUAGE_HTML=%~dp0language.html"
set "QB_GUIDE_HTML=%~dp0guide.html"
set "QB_MONITOR_HTML=%~dp0monitor.html"
set "QB_VOICE_HTML=%~dp0voice.html"

REM free a stale server on 8090 so you get this version
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8090" ^| findstr LISTENING') do (
  taskkill /F /PID %%P >nul 2>&1
)

echo.
echo ============================================================
echo   SECURE REMOTE MODE is ON (password required).
echo   On THIS PC:      http://127.0.0.1:8090/monitor
echo   From your phone/laptop on the same private network
echo   (e.g. Tailscale), open:
echo        http://THIS-PC-NAME:8090/monitor
echo   and sign in with the password you just set.
echo   Find THIS-PC-NAME / IP in your Tailscale app.
echo ============================================================
echo.
start "QueryBook (remote)" cmd /c python qb_api.py
ping -n 3 127.0.0.1 >nul
start "" http://127.0.0.1:8090/monitor
echo Leave the small server window open while it runs. Close it to stop.
pause
