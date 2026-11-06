@echo off
cd /d "%~dp0"
echo QueryBook stress test (stress) - this window shows progress; the report goes to dsn-results
where python >nul 2>nul
if %errorlevel%==0 (python dsn_stress.py stress) else (py dsn_stress.py stress)
echo.
echo Finished. The report is in the dsn-results folder.
pause
