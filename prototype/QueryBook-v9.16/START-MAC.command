#!/bin/bash
# ============================================================
#   QueryBook - Mac.  Double-click this file.
#   (First time: right-click -> Open -> Open to clear the security prompt.)
#   It asks WHERE to save facts (external drive) right away,
#   then remembers your choice for next time.
# ============================================================
cd "$(dirname "$0")"

CFG="$(dirname "$0")/querybook_store.txt"
LAST=""
[ -f "$CFG" ] && LAST="$(cat "$CFG")"

echo "============================================================"
echo "  QueryBook - choose where to save facts"
echo "============================================================"
echo
echo "Where should facts be saved?"
echo
echo "  FASTEST: type  i  to use your internal drive (~/QueryBook/store)."
echo "           Internal SSD harvests MUCH faster than USB; copy the store"
echo "           folder to an external drive later - it is just files."
echo
echo "  Or pick an EXTERNAL volume below:"
i=0
declare -a VOLS
for v in /Volumes/*; do
  [ -d "$v" ] || continue
  i=$((i+1)); VOLS[$i]="$v"
  echo "    $i)  $v"
done
if [ "$i" -eq 0 ]; then echo "    (no external volumes found)"; fi
echo
[ -n "$LAST" ] && echo "  Last time you used:  $LAST"
echo

STORE=""
while [ -z "$STORE" ]; do
  read -p "Type i (internal, fast), a number above, a full path; Enter = reuse last: " SEL
  if [ -z "$SEL" ] && [ -n "$LAST" ]; then
    STORE="$LAST"
  elif [[ "$SEL" == "i" || "$SEL" == "I" ]]; then
    STORE="$HOME/QueryBook/store"
  elif [[ "$SEL" =~ ^[0-9]+$ ]] && [ -n "${VOLS[$SEL]}" ]; then
    STORE="${VOLS[$SEL]}/QueryBook/store"
  elif [[ "$SEL" == /* ]]; then
    STORE="$SEL"
  else
    echo "  Please type i, one of the numbers listed, or a full path."; continue
  fi
done

# make sure the parent volume exists and the folder can be created
PARENT="$(dirname "$STORE")"
if ! mkdir -p "$STORE" 2>/dev/null; then
  echo "Could not create $STORE - is the drive plugged in and writable?"
  read -n 1 -s -r -p "Press any key to close."; exit 1
fi
echo "$STORE" > "$CFG"

PY=python3
command -v $PY >/dev/null 2>&1 || PY=python
if ! command -v $PY >/dev/null 2>&1 ; then
  echo "Python was not found. Install it from https://www.python.org/downloads/ and re-open this file."
  read -n 1 -s -r -p "Press any key to close."; exit 1
fi
if [ ! -f qb_api.py ]; then echo "qb_api.py is missing from this folder."; read -n 1 -s -r; exit 1; fi

export QB_DATA_DIR="$STORE"
export QB_BIND="127.0.0.1:8090"
export QB_CHAT_HTML="$PWD/chat.html"
export QB_CONSOLE_HTML="$PWD/console.html"
export QB_DASHBOARD_HTML="$PWD/dashboard.html"
export QB_LANGUAGE_HTML="$PWD/language.html"
export QB_GUIDE_HTML="$PWD/guide.html"

echo
echo "============================================================"
echo "  Saving facts to:  $STORE"
echo "  Starting QueryBook..."
echo "============================================================"
echo

# Free port 8090 if a previous QueryBook is STILL running on it. A stale server
# keeps serving an OLD page, and the usual symptom is a dead "Language Lab" link.
STALE=$(lsof -ti tcp:8090 2>/dev/null)
if [ -n "$STALE" ]; then
  echo "  A previous QueryBook is still running on port 8090 - stopping it so you"
  echo "  get this version (a stale server is why a link like Language Lab goes dead)..."
  kill $STALE 2>/dev/null; sleep 1
  lsof -ti tcp:8090 2>/dev/null | xargs kill -9 2>/dev/null; sleep 1
fi

$PY qb_api.py &
SRV=$!
sleep 2
open "http://127.0.0.1:8090/dashboard" 2>/dev/null

echo "QueryBook is open in your browser:"
echo "   Dashboard:     http://127.0.0.1:8090/dashboard"
echo "   Language Lab:  http://127.0.0.1:8090/language   (open this directly if the menu link ever fails)"
echo
echo "  1) Click \"Start harvest\" (or \"Run 24x7\") to collect facts."
echo "  2) Click \"24x7 Awake: OFF\" to keep this Mac from sleeping."
echo "  3) Try the Language Lab (teach English) and the Guide from the top menu."
echo
echo "Leave this window open while it runs. Press Ctrl+C or close it to stop."
wait $SRV
