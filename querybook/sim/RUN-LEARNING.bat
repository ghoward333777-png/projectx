@echo off
setlocal
cd /d "%~dp0"
title QueryBook stress test (learning over time)
echo QueryBook stress test (learning over time)
echo Folder: %~dp0
echo.
if not exist "%~dp0dsn_stress.py" goto notunzipped
if not exist "%~dp0qb_chat.py" goto notunzipped
if not exist "%~dp0ufcs_store.py" goto notunzipped
set "PY="
rem The bundled Python (in the python folder beside this file) needs nothing installed.
if exist "%~dp0python\python.exe" set PY="%~dp0python\python.exe"
if defined PY goto run
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto run
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto run
echo The bundled Python folder is missing and no Python 3.8 or newer was found on this computer.
echo Extract the whole ZIP again (it includes the python folder), or install Python from python.org.
goto end
:run
echo Using: %PY%
echo This window shows the progress. Do not close it until it says Finished.
echo.
%PY% -X utf8 dsn_stress.py learning
if errorlevel 1 goto failed
echo.
echo Finished. The report is the .md file in: %~dp0dsn-results
goto end
:failed
echo.
echo The test did not finish. The lines above say why; the error is also in %~dp0dsn-results\error.txt
echo Please send a copy of this window (or that file).
goto end
:notunzipped
echo The test files are not in this folder.
echo Windows probably opened this launcher straight from inside the ZIP file.
echo Right-click QueryBook-StressTest.zip, choose "Extract All...", open the extracted folder,
echo and double-click the launcher there.
:end
echo.
pause
