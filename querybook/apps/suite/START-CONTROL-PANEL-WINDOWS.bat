@echo off
REM QueryBook Control Panel - double-click to open the one panel for all three applications.
cd /d "%~dp0"
REM Optional: a file data-folder.txt beside this one names the folder holding the QueryBook data (e.g. D:\qb, also
REM on an external drive). The shared facts are used from FOLDER\commons if it holds them, else from FOLDER itself; a
REM program's own data is used from FOLDER\language, \stem, \facts or \control when that folder exists. If the drive is
REM not connected, nothing starts: the data is never split between two drives.
set "QBD="
if exist "%~dp0data-folder.txt" set /p QBD=<"%~dp0data-folder.txt"
if not defined QBD goto qbgo
if not exist "%QBD%\" (
  echo.
  echo  The QueryBook data folder %QBD% cannot be found.
  echo  If it is on an external drive, connect the drive and double-click this file again.
  echo  To use the usual folder instead, delete data-folder.txt next to this file.
  echo.
  pause
  exit /b 1
)
set "QB_COMMONS_DATA=%QBD%\commons"
if exist "%QBD%\commons.sqlite" set "QB_COMMONS_DATA=%QBD%"
if exist "%QBD%\language\" set "QB_LANGUAGE_DATA=%QBD%\language"
if exist "%QBD%\stem\" set "QB_STEM_DATA=%QBD%\stem"
if exist "%QBD%\facts\" set "QB_FACTS_DATA=%QBD%\facts"
if exist "%QBD%\control\" set "QB_CONTROL_DATA=%QBD%\control"
echo  QueryBook data: %QB_COMMONS_DATA%
:qbgo
start "QueryBook Control Panel" cmd /c "QueryBook-Control-Panel\START-WINDOWS.bat"
