#!/bin/bash
# ============================================================
#   QueryBook - FIND MY STATION.  Double-click this file on
#   your DEV / monitoring device (NOT the learning station).
#   It listens on your network and prints the exact links to
#   open the station's Monitor. No IP typing, no static IP.
# ============================================================
cd "$(dirname "$0")" || exit 1
PY=python3
command -v python3 >/dev/null 2>&1 || PY=python
if [ ! -f qb_api.py ]; then echo "qb_api.py is missing from this folder."; read -r _; exit 1; fi
echo
echo "Searching your network for the QueryBook station..."
echo "(The station must be running, and both devices on the same network.)"
echo
"$PY" qb_api.py discover
echo
echo "Tip: copy one of the http://... links above into your browser."
read -r -p "Press Return to close."
