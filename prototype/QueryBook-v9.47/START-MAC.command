#!/bin/bash
# ============================================================
#   QueryBook - ONE-CLICK start for Mac.  Double-click this file.
#   (First time: right-click -> Open -> Open to clear the security prompt.)
#   Finds (or installs) Python, runs a self-check, starts the app,
#   and opens it in your browser. The FIRST launch asks where to keep
#   your data (point it at your external drive); it then remembers for
#   50 launches. Nothing is moved or deleted.
# ============================================================
cd "$(dirname "$0")"

echo "============================================================"
echo "  QueryBook - starting up"
echo "============================================================"
echo

# --- 1. Find Python; try Homebrew if missing --------------------------------
PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python is needed. Trying to install it (Homebrew)..."
  command -v brew >/dev/null 2>&1 && brew install python && PY=python3
fi
if ! command -v "$PY" >/dev/null 2>&1; then
  echo
  echo "[PROBLEM] Could not find or install Python automatically."
  echo "  Opening the download page. Install Python 3, then re-open this file."
  open "https://www.python.org/downloads/" 2>/dev/null
  read -n 1 -s -r -p "Press any key to close."; exit 1
fi
if [ ! -f qb_api.py ]; then echo "[PROBLEM] qb_api.py is missing from this folder."; read -n 1 -s -r; exit 1; fi

# --- 2. Self-diagnostic (plain-English; changes nothing) --------------------
echo "Running a quick self-check..."; echo
"$PY" qb_doctor.py
echo

# --- 3. Free the port if an old QueryBook is still running ------------------
STALE=$(lsof -ti tcp:8099 2>/dev/null)
if [ -n "$STALE" ]; then
  echo "  Stopping a previous QueryBook on port 8099..."
  kill $STALE 2>/dev/null; sleep 1
  lsof -ti tcp:8099 2>/dev/null | xargs kill -9 2>/dev/null; sleep 1
fi

# --- 4. Open the browser shortly after start --------------------------------
( sleep 4; open "http://127.0.0.1:8099/dashboard" >/dev/null 2>&1 ) &

echo "------------------------------------------------------------"
echo " Starting QueryBook."
echo " * The FIRST launch asks WHERE to keep your data - point it at"
echo "   your external drive (or press Enter for the suggested one)."
echo " * It then remembers your choice for the next 50 launches."
echo " * Leave this window open while you use QueryBook; close it to stop."
echo " * Your browser opens at  http://127.0.0.1:8099/dashboard"
echo "------------------------------------------------------------"
echo

# --- 5. Run the app in THIS window so the data question is visible ----------
"$PY" qb_api.py

echo
echo "============================================================"
echo "  QueryBook has stopped."
echo "  For a health check any time, run  CHECK-QUERYBOOK.command"
echo "  To change where your data lives:  $PY qb_api.py configure"
echo "============================================================"
read -n 1 -s -r -p "Press any key to close."
