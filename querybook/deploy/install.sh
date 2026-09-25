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
# UFCS_TOKEN=
# Backups (README: "Backups to Google Drive"). Keep a copy of the passphrase
# somewhere safe outside this server: without it no backup can be restored.
# QB_BACKUP_PASSPHRASE=
# QB_DRIVE_CLIENT_ID=
# QB_DRIVE_CLIENT_SECRET=
ENV
  chmod 0600 /etc/querybook/env
fi
install -m 0644 deploy/querybook.service /etc/systemd/system/querybook.service
install -d -o querybook -g querybook -m 0750 /var/backups/querybook
install -m 0644 deploy/querybook-backup.service /etc/systemd/system/querybook-backup.service
install -m 0644 deploy/querybook-backup.timer /etc/systemd/system/querybook-backup.timer
systemctl daemon-reload
echo
echo "Installed. Next:"
echo "  sudoedit /etc/querybook/env            # set QB_ADMIN_PASSWORD"
echo "  sudo systemctl enable --now querybook"
echo "  sudo -u querybook qb -c /etc/querybook/querybook.toml ingest --manifest /path/library.csv"
echo "Backups to Google Drive (see README), once the env file has the backup settings:"
echo "  sudo systemd-run --pty --uid=querybook -p EnvironmentFile=/etc/querybook/env /usr/local/bin/qb -c /etc/querybook/querybook.toml drive-auth"
echo "  sudo systemctl enable --now querybook-backup.timer"
