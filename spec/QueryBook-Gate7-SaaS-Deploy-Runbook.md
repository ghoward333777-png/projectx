# QueryBook — Gate 7 SaaS Deploy Runbook (Ubuntu)

**Gate 7 deliverable · v1.0 · 2026‑09‑30 · EXECUTES AFTER Gates 5–6**
The operational runbook for deploying the Rust engine as a SaaS on a dedicated
Ubuntu server. It is a **runbook, not a live deployment**: the actual deploy needs
the completed Rust binary (Gate 5) and a passed audit (Gate 6), plus a real host,
DNS, and TLS certificates — none of which exist in the prototype sandbox. Written
now so the path is defined and reviewable.

## 1. Target topology
- **Phase A — single node.** One Ubuntu 22.04/24.04 LTS host: `qbd` (the Rust server),
  a reverse proxy for TLS, fast NVMe for the hot store, and a larger tier for cold
  blocks. Sufficient to ~1 B facts given `5 GB + facts × 120 B` (≈125 GB at 1 B).
- **Phase B — sharded.** Shard by fingerprint prefix across nodes (Gate 4 §6); a stateless
  query router fans out and merges. Add read replicas per shard for read scaling.

## 2. Host preparation
```bash
# packages
sudo apt update && sudo apt install -y caddy espeak-ng ufw fail2ban
# dedicated service user, no login
sudo useradd --system --home /var/lib/querybook --shell /usr/sbin/nologin querybook
sudo install -d -o querybook -g querybook /var/lib/querybook /var/log/querybook
# storage tiers
#   /var/lib/querybook/hot   -> NVMe (memtable flush, recent SSTables, index)
#   /var/lib/querybook/cold  -> large disk/object-backed (compacted blocks)
```
`espeak-ng` provides the Phase‑4 OS voice (the engine shells to it, as the prototype does).

## 3. Service (systemd)
`/etc/systemd/system/qbd.service`:
```ini
[Unit]
Description=QueryBook engine (qbd)
After=network-target
[Service]
User=querybook
Environment=QB_DATA_DIR=/var/lib/querybook/hot
Environment=QB_COLD_DIR=/var/lib/querybook/cold
Environment=QB_BIND=127.0.0.1:8099
EnvironmentFile=/etc/querybook/secrets.env      # proposer API keys, never world-readable
ExecStart=/usr/local/bin/qbd
Restart=on-failure
RestartSec=2
# hardening
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/querybook /var/log/querybook
PrivateTmp=true
ProtectHome=true
[Install]
WantedBy=multi-user.target
```
`/etc/querybook/secrets.env` is `chmod 600`, owner `querybook`; keys never logged (Gate 6).

## 4. TLS / reverse proxy (Caddy)
```
querybook.example.com {
    reverse_proxy 127.0.0.1:8099
    encode zstd gzip
    header -Server
    # read-only API tokens vs the single writer credential enforced in qbd, not here
}
```
Caddy obtains/renews Let's Encrypt certs automatically. `qbd` binds loopback only;
all external traffic terminates TLS at the proxy.

## 5. Storage & backup
- **Tiering:** memtable + recent SSTables + index on `hot` (NVMe); compaction migrates
  cold blocks to `cold`. The 120 B/fact budget sets capacity planning.
- **Backup:** blocks are append‑only and content‑addressed, so incremental sync
  (`restic`/`rclone`) of `cold` + a consistent snapshot of `hot` + the manifest is a
  complete backup. Nightly incremental; weekly full; test restore monthly.
- **Restore:** stop `qbd`, restore `cold`+`hot`+manifest, run `qbd --verify` (re‑reads and
  recomputes fingerprints) before re‑enabling writes.

## 6. Monitoring & ops
- Health: `GET /api/health` (liveness + last self‑test) behind the proxy for the LB.
- Metrics: ingest rate, dedup/query p99, RAM RSS, disk/fact, compaction lag, proposer
  egress count — scraped to Prometheus; alert on budget breach or read‑starvation.
- Keep‑awake/watchdog heartbeat (as the prototype) to distinguish a real stall from idle.
- Logs to `/var/log/querybook`, `logrotate` daily, 14‑day retention; **no secrets in logs**.

## 7. Upgrade / rollback
- Blue/green: install the new `qbd` beside the old, start on an alt port, run the Gate‑1
  parity/verdict suite against it, then flip the proxy. Roll back by flipping back.
- On‑disk format changes ship with a one‑time migrator that preserves fingerprints
  (Gate 4 §10) and is dry‑run‑verified before it touches production.

## 8. Security hardening (deploy‑time; audited at Gate 6)
`ufw` allow 80/443 only; `fail2ban` on the proxy; SSH key‑only; automatic security
updates; the service user unprivileged with `ProtectSystem=strict`; secrets file `600`;
proposer egress allow‑listed at the firewall.

## 9. Gate 7 exit criteria (approval)
1. A reproducible deploy from this runbook brings up `qbd` behind TLS with health green.
2. Backup + a test restore (`--verify` clean) succeed.
3. Monitoring/alerts fire on a simulated budget breach and a simulated stall.
4. Blue/green upgrade + rollback demonstrated with the parity suite as the gate.
5. Deploy‑time hardening in §8 verified; ties off the Gate 6 security findings.
