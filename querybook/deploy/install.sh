#!/usr/bin/env bash
# Build and install QueryBook on Ubuntu 22.04/24.04. Run from the querybook/ directory: sudo bash deploy/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v cargo >/dev/null 2>&1; then
  apt-get update && apt-get install -y build-essential curl pkg-config
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
  source "$HOME/.cargo/env"
fi

cargo build --release
install -m 0755 target/release/qb /usr/local/bin/qb

id querybook >/dev/null 2>&1 || useradd --system --home /var/lib/querybook --shell /usr/sbin/nologin querybook
install -d -o querybook -g querybook -m 0750 /var/lib/querybook
install -d -m 0755 /etc/querybook
[ -f /etc/querybook/querybook.toml ] || install -m 0644 config/querybook.example.toml /etc/querybook/querybook.toml
if [ ! -f /etc/querybook/env ]; then
  cat > /etc/querybook/env <<'ENV'
# Secrets for the QueryBook service (read by systemd). Keep this file 0600.
QB_ADMIN_PASSWORD=change-me
# ANTHROPIC_API_KEY=
# UFCS_TOKEN=
ENV
  chmod 0600 /etc/querybook/env
fi
install -m 0644 deploy/querybook.service /etc/systemd/system/querybook.service
systemctl daemon-reload
echo
echo "Installed. Next:"
echo "  sudoedit /etc/querybook/env            # set QB_ADMIN_PASSWORD (and API keys)"
echo "  sudo systemctl enable --now querybook"
echo "  sudo -u querybook qb -c /etc/querybook/querybook.toml ingest --manifest /path/library.csv --engines rules"
