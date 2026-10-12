#!/bin/bash
# QueryBook - plain-English health check for Mac. Double-click to run.
# (First time: right-click -> Open -> Open to clear the security prompt.)
cd "$(dirname "$0")"
PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python is not installed. Get it from https://www.python.org/downloads/ and re-open this file."
  read -n 1 -s -r -p "Press any key to close."; exit 1
fi
"$PY" qb_doctor.py
echo
read -n 1 -s -r -p "Press any key to close."
