@echo off
REM QueryBook Control Panel - double-click to open the one panel for all three applications.
cd /d "%~dp0"
start "QueryBook Control Panel" cmd /c "QueryBook-Control-Panel\START-WINDOWS.bat"
