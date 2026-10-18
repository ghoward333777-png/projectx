@echo off
REM QueryBook - double-click to start all three applications, each in its own window.
cd /d "%~dp0"
start "QueryBook Language" cmd /c "QueryBook-Language\START-WINDOWS.bat"
start "QueryBook Math Science Engineering" cmd /c "QueryBook-STEM\START-WINDOWS.bat"
start "QueryBook History and News" cmd /c "QueryBook-History-News\START-WINDOWS.bat"
