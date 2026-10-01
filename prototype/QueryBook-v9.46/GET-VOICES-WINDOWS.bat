@echo off
REM ============================================================
REM   QueryBook — GET VOICES (one time).  Double-click this.
REM   Installs espeak-ng (free, open-source) so QueryBook can
REM   SPEAK every language — Spanish, French, German, etc. —
REM   with a real voice, offline, no account, no cloud.
REM   After it installs, restart QueryBook (START-WINDOWS.bat).
REM ============================================================
setlocal
cd /d "%~dp0"
set "MSI=%TEMP%\espeak-ng-x64.msi"
set "URL=https://github.com/espeak-ng/espeak-ng/releases/download/1.51/espeak-ng-X64.msi"

echo.
echo Downloading the espeak-ng voice engine (about 6 MB)...
echo From: %URL%
echo.

REM Win10/11 ship curl.exe; fall back to PowerShell if needed.
where curl >nul 2>&1
if %errorlevel%==0 (
  curl -L -o "%MSI%" "%URL%"
) else (
  powershell -NoProfile -Command "try{Invoke-WebRequest -Uri '%URL%' -OutFile '%MSI%'}catch{exit 1}"
)

if not exist "%MSI%" (
  echo.
  echo Could not download automatically. You can install it by hand:
  echo   1) Open %URL% in your browser
  echo   2) Run the downloaded file and click through the installer
  echo   3) Restart QueryBook
  echo.
  pause
  exit /b 1
)

echo.
echo Starting the espeak-ng installer. Click "Next" / "Install" / "Finish".
echo (If Windows asks for permission, click Yes.)
echo.
start "" /wait msiexec /i "%MSI%"

echo.
echo ============================================================
echo   Done. Now CLOSE QueryBook's black server window and
echo   start it again with START-WINDOWS.bat.
echo   Then Analyze ^& Speak will speak every language.
echo ============================================================
pause
