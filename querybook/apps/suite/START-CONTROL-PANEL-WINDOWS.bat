@echo off
REM QueryBook Control Panel - double-click to open the one panel for all three applications.
cd /d "%~dp0"
REM Optional: a file data-folder.txt beside this one names the folder holding the QueryBook data (e.g. D:\qb, also
REM on an external drive). The shared facts are used from FOLDER\commons if it holds them, else from FOLDER itself; a
REM program's own data is ALWAYS kept in FOLDER\language, \stem, \facts, \control and \video. Data earlier versions kept
REM on C: is brought over by itself on start (the old copy is left as it was). If the drive is not connected, nothing
REM starts: the data is never split between two drives.
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
set "QB_LANGUAGE_DATA=%QBD%\language"
set "QB_STEM_DATA=%QBD%\stem"
set "QB_FACTS_DATA=%QBD%\facts"
set "QB_CONTROL_DATA=%QBD%\control"
set "QB_VIDEO_DATA=%QBD%\video"
echo  QueryBook data: %QB_COMMONS_DATA%
:qbgo
start "QueryBook Control Panel" cmd /c "QueryBook-Control-Panel\START-WINDOWS.bat"
