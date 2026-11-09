@echo off
rem VeriWave: the QueryBook AI model. Starts QueryBook's applications too (or uses a QueryBook window already open).
cd /d "%~dp0"
where python >nul 2>nul && (python veriwave.py %*) || (py -3 veriwave.py %*)
pause
