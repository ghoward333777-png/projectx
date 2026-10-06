@echo off
rem Start the QueryBook UFCS-FQL Lab dashboard on Windows.
rem   start.bat          http://127.0.0.1:8091
rem   start.bat 9000     another port
cd /d "%~dp0"
set PORT=%1
if "%PORT%"=="" set PORT=8091

where php >nul 2>nul
if errorlevel 1 (
  echo PHP is not installed. Download PHP 8.3 for Windows from https://windows.php.net/download and add it to PATH.
  echo Then open a new terminal and run start.bat again. Or use Docker: docker compose up
  pause
  exit /b 1
)
php bin\doctor.php
if errorlevel 1 (
  pause
  exit /b 1
)
echo.
echo QueryBook UFCS-FQL Lab: http://127.0.0.1:%PORT%   (close this window to stop)
start "" http://127.0.0.1:%PORT%
php -d upload_max_filesize=256M -d post_max_size=256M -S 127.0.0.1:%PORT% -t web
