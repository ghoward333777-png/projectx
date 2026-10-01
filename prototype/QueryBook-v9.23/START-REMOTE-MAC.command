#!/bin/bash
# ============================================================
#   QueryBook - SECURE REMOTE MODE (macOS / Linux)
#   Listens on your whole network (for Tailscale / LAN) and
#   requires a PASSWORD. Use on a private network only.
# ============================================================
cd "$(dirname "$0")" || exit 1
DIR="$(pwd)"

STORE="$HOME/QueryBook/store"
[ -f "$DIR/querybook_store.txt" ] && STORE="$(cat "$DIR/querybook_store.txt")"
mkdir -p "$STORE" 2>/dev/null

echo "============================================================"
echo "  QueryBook - SECURE REMOTE MODE"
echo "============================================================"
echo "Saving facts to: $STORE"
echo
read -r -s -p "Set an access password (anyone with it can view/control): " PW
echo
[ -z "$PW" ] && { echo "A password is required for remote mode."; exit 1; }

command -v python3 >/dev/null 2>&1 || { echo "Install Python 3 first."; exit 1; }

# free a stale server on 8090
if command -v lsof >/dev/null 2>&1; then
  for pid in $(lsof -ti tcp:8090 2>/dev/null); do kill -9 "$pid" 2>/dev/null; done
fi

export QB_DATA_DIR="$STORE"
export QB_BIND="0.0.0.0:8090"
export QB_ACCESS_TOKEN="$PW"
export QB_CHAT_HTML="$DIR/chat.html"
export QB_CONSOLE_HTML="$DIR/console.html"
export QB_DASHBOARD_HTML="$DIR/dashboard.html"
export QB_LANGUAGE_HTML="$DIR/language.html"
export QB_GUIDE_HTML="$DIR/guide.html"
export QB_MONITOR_HTML="$DIR/monitor.html"
export QB_VOICE_HTML="$DIR/voice.html"

echo
echo "============================================================"
echo "  SECURE REMOTE MODE is ON (password required)."
echo "  On this computer:  http://127.0.0.1:8090/monitor"
echo "  From another device on your private network (Tailscale):"
echo "       http://THIS-MACHINE-NAME:8090/monitor"
echo "  and sign in with the password you just set."
echo "============================================================"
echo
( sleep 2; open "http://127.0.0.1:8090/monitor" 2>/dev/null || xdg-open "http://127.0.0.1:8090/monitor" 2>/dev/null ) &
python3 qb_api.py
