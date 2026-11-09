#!/bin/bash
# QueryBook Control Panel — double-click to start (first time: right-click -> Open -> Open). Leave the window open while you use it.
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
  python3 app.py "$@"
else
  echo "Python 3 is not installed. Install it from https://www.python.org/downloads/ and open this file again."
  open "https://www.python.org/downloads/" 2>/dev/null
  read -n 1 -s -r -p "Press any key to close."
fi
