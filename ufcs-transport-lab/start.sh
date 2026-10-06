#!/usr/bin/env sh
# Start the QueryBook UFCS-FQL Lab dashboard and open it in the browser.
#   ./start.sh            http://127.0.0.1:8091
#   ./start.sh 9000       another port
#   HOST=0.0.0.0 ./start.sh   reachable from other machines
set -eu
cd "$(dirname "$0")"
PORT="${1:-${PORT:-8091}}"
HOST="${HOST:-127.0.0.1}"

if ! command -v php >/dev/null 2>&1; then
    echo "PHP is not installed. Run ./install.sh first (or: docker compose up)."
    exit 1
fi
php bin/doctor.php >/dev/null 2>&1 || { php bin/doctor.php; exit 1; }

URL="http://127.0.0.1:$PORT"
echo "QueryBook UFCS-FQL Lab: $URL   (Ctrl+C to stop)"
if [ "${NO_BROWSER:-0}" != "1" ]; then
    ( sleep 1
      if command -v open >/dev/null 2>&1; then open "$URL"
      elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
      fi ) >/dev/null 2>&1 &
fi
exec php -d upload_max_filesize=256M -d post_max_size=256M -S "$HOST:$PORT" -t web
