# QueryBook Agent Protection & Deception Layer

Technical specification and implementation record, QueryBook v9.64.

This file is both the specification and its traceability record. It can be handed to Claude Code
or another engineer as-is: each requirement names the code that implements it and the automated
check that proves it. Run every check with `python qb_selftest.py` (it also runs at every server
start).

## 1. Objectives

- **Primary.** Prevent any QueryBook agent, or an external AI such as OpenClaw, from being
  targeted, exploited or used as an attack vector.
- **Secondary.** Detect and contain hostile activity early through deception, and keep
  tamper-evident, non-repudiable records of all agent activity and security events.

## 2. Threat model

| Adversary | Examples |
|---|---|
| Autonomous AI exploiters | OpenClaw-class agents, multi-agent swarms, recursive exploit loops |
| Humans with automated tools | sqlmap, nuclei, ffuf, scripted requests |
| A hijacked legitimate agent | A real OpenClaw turned by prompt injection hidden in a file or web page |

Key risks: prompt injection and agent hijacking, unauthorized UFCS command execution, lateral
movement through agents, theft of local files through an agent, and log tampering to hide activity.

## 3. Architecture

```
caller (OpenClaw / MCP client / HTTP)
   │
   ▼
HTTP gate (qb_api → qb_shield.http_gate)      honeypages · honeytokens · isolation · rate limit
   │
   ▼
Agent Gateway (qb_shield.execute)             A: identity, token, RBAC, allow-list, replay window
   ├─ isolated? ──────────────► Decoy environment (qb_decoy, synthetic only)   C
   ├─ honeycode / tripwire / honeytoken / honeypot agent ─► event bus ─► isolate ─► decoy   D, T
   ├─ AI-aware firewall + anomaly detection ─► deny / throttle / isolate        F
   ▼
real handler (chat, verify, Open Claw, ledger, NFT)
   │
every decision ─► Immutable log (qb_seclog): hash chain · Merkle checkpoints · write-once files
                  · optional mirror · optional blockchain anchor                 L
```

## 4. Requirements and where they are implemented

### 4.1 Agent access control

| Id | Requirement | Implementation | Proof (QC check) |
|---|---|---|---|
| A1 | All agent calls go through one hardened Agent Gateway | `qb_shield.execute`; `POST /agent/execute`; the MCP server (`qb_mcp.py`) routes every `tools/call` through it | qb_mcp: "tools/call goes through the gateway" |
| A2 | Every call carries agent, caller, session, command, scope and timestamp | Required fields are checked; the timestamp must fall within a ±300 s replay window | qb_shield: "missing fields rejected", "stale timestamp rejected (replay)" |
| A3 | RBAC for callers, and a per-agent allow-list that never expands dynamically | Roles operator/user/agent/guest. Callers prove identity with an HMAC-derived token (`python qb_shield.py token <caller>`). Allow-lists live in `shield_policy.json` and change only by hand-editing plus a restart; no API can change them | qb_shield: "command outside allow-list rejected", "wrong caller token rejected", "guest may not ingest" |
| A4 | Unknown agent ids, or commands outside the allow-list, are rejected | Same | qb_shield: "unknown agent rejected" |

### 4.2 Deception and honeycode

| Id | Requirement | Implementation | Proof |
|---|---|---|---|
| D1 | Fake privileged UFCS commands and endpoints that legitimate code never uses | `HONEYCODE`: `ufcs.super_admin.export_all`, `agent.root_control.override`, `ufcs.vault.dump_keys`, `ufcs.admin.disable_audit`, `agent.registry.grant_all`, `store.raw_sql_exec` and more. They are never listed in MCP `tools/list` | qb_mcp: "honeycode is never advertised" |
| D2 | A honeycode call raises a high-severity event and goes to containment | `HONEYCODE_TRIGGERED` on the event bus → `isolate()` → decoy response | qb_shield: "honeycode → decoy + isolation" |
| D3 | Honeytokens (credentials, API keys, UFCS command keys, agent ids, DB rows) placed where attackers look | 28 per-install values derived from a local secret: API key, UFCS command key, admin password, JWT, agent id, DB token and root token. They are planted in `.env.production.bak`, `qb_admin_credentials.json.bak`, the honeypages, and the decoy's own "exports" and "vault" | Server start prints the count and the planted files |
| D4 | Any honeytoken use counts as confirmed malicious | Every gateway request and every HTTP request (query, headers, body) is scanned, and a match triggers `HONEYTOKEN_USED` → isolation | qb_shield: "honeytoken use → isolation"; live test: a fake key read from disk and sent in a header isolated the client |

### 4.3 Tripwires and honeypots

| Id | Requirement | Implementation | Proof |
|---|---|---|---|
| T1 | Never-legitimate code paths with tempting names | `TRIPWIRES`: `debug_root_dump`, `internal_vault_access`, `log.purge_all`, `log.rewrite`, `seclog.delete`, `shield.disable`, `shield.release_all`. Also the URLs `/debug/root_dump`, `/internal/vault/*`, `/.env`, `/.git/config`, `/admin`, `/api/v1/admin/*`, `/backup.sql`, `/wp-login.php` and more, with breadcrumbs in `/robots.txt` | qb_shield: "tripwire → containment", "HTTP honeypage serves decoy + isolates client" |
| T2 | Tripwire hits log full context and contain at once | The event carries caller, agent, command and a parameter hash; the client, user agent and tools are recorded | live test: section 7 |
| T3 | Honeypot agents with synthetic data only | `qb.root-maintenance`, `qb.vault-keeper`, `qb.super-admin` → `HONEYPOT_TOUCHED` → decoy | qb_shield: "honeypot agent → engagement" |

### 4.4 AI-aware firewall and anomaly detection

| Id | Requirement | Implementation | Proof |
|---|---|---|---|
| F1 | Scan prompts and payloads for injection, jailbreak and self-modification; limit size and complexity per caller | `scan_text()` signatures: ignore-instructions, reveal-secrets, role hijack, fake system tags, tool-call injection, self-modification, exfiltration URLs, command execution, recursive agent spawning, hidden Unicode tag characters, invisible/bidi text, NFKC-obfuscated injection, long base64 blobs. Limits: 256 KB payload, 64 KB string, nesting depth 24 | qb_shield: "prompt injection blocked", "hidden unicode tag smuggling detected", "normal question not flagged" |
| F2 | Detect unusual volume, command combinations and autonomous scanning | 60 s window per session: command enumeration, repeated rejections, probing of unknown commands, machine-regular timing (low jitter) | qb_shield: "enumeration detected and isolated" |
| F3 | Block or throttle exploit signatures and sessions over threshold | Signature match → `FIREWALL_BLOCKED`. Token-bucket rate limit per caller and role. An anomaly score ≥ 6 → isolation | live test: injection denied in 1.1 ms |

Untrusted content gets the same scanning. Files ingested by Open Claw are data, never
instructions: segments that read like instructions to an AI are stored at trust 0.2 with the flag
`untrusted_instruction_like`. That is below the 0.5 trust gate, so they can never be cited as an
answer.

### 4.5 Containment and adversary engagement

| Id | Requirement | Implementation | Proof |
|---|---|---|---|
| C1 | On any trigger, isolate the session; from then on it reaches only the decoy | `isolate()` keys the session, the client, and the caller (the caller only when it proved its identity, so nobody can lock out a real agent by borrowing its name). The isolation list persists across restarts. Release is CLI-only (`python qb_shield.py release <id>`); `POST /api/security/release` always refuses | qb_shield: "isolated session only reaches the decoy", "impersonating a caller does not lock out the real caller", "no HTTP path can release isolation" |
| C2 | The decoy keeps answering plausibly and logs everything | `qb_decoy.respond()` returns the same shapes as the real agents (facts, exports, vault keys, agent lists, SQL rows). Every call is recorded with its command, user agent and fingerprinted tool (sqlmap, nuclei, python-requests, curl, openclaw, …). This is observation only: QueryBook never takes action against anyone | qb_shield: "isolated HTTP client gets decoy API data" |
| C3 | No path from the decoy back to production | `qb_decoy.py` imports only `hashlib`, `json` and `time`, and QC enforces that | qb_shield: "decoy imports no production module" |

The operator's own browser keeps working. On 127.0.0.1, clients are identified by address plus
User-Agent, so a local scanning tool is isolated without locking out the dashboard.

### 4.6 Immutable logging and provenance

| Id | Requirement | Implementation | Proof |
|---|---|---|---|
| L1 | Log every agent call, security event and firewall decision to an append-only log | `qb_seclog.append()` is the only write operation. It fsyncs each entry, defaulting to `~/.querybook/seclog/` | qb_shield: "every decision logged, log verifies" |
| L2 | Hashed entries, a Merkle tree, and checkpoints to WORM storage | Each entry hash covers the previous one. Every 256 entries (or on demand) a Merkle root is sealed into a write-once checkpoint file: created with O_EXCL, read-only, chained to the previous checkpoint, HMAC-signed. Optional mirror to another drive (`QB_SECLOG_MIRROR`). Optional anchoring of the checkpoint root on a blockchain through the NFT contract | qb_seclog: "checkpoint is write-once", "edited entry detected", "re-hashed forgery still caught by checkpoints", "mirror disagrees with edited primary" |
| L3 | Entries carry agent, caller, command, parameter hash, timestamp, decision and flags | Entry schema: `seq, ts, prev, event, severity, agent_id, caller_id, session_id, ufcs_command, params_hash, decision, flags, detail, hash` | — |
| L4 | A verification API with integrity proofs | `GET /log/verify?start=&end=&chain=1` (chain=1 also checks the on-chain anchors) and `GET /log/proof?seq=N` (Merkle inclusion proof) | qb_seclog: "Merkle inclusion proof valid", "tampered proof rejected" |
| L5 | Nothing may modify existing entries; append only | There is no update or delete API; the file is opened in append mode; checkpoints refuse to overwrite. A request to purge logs is itself a tripwire | qb_seclog: "no update/delete API exists"; live test: `log.purge_all` → isolated, and the log stayed intact |

What makes the log provable to outsiders: on one machine, someone with full control of the
files and keys could rebuild a consistent fake log. Two things prevent that. A **mirror** on
another device, and **blockchain-anchored checkpoints**, which are public and can't be rewritten.
`/log/verify` reports which of these protections the current log actually has.

## 5. Interfaces

| Interface | Contract |
|---|---|
| `POST /agent/execute` | In: `{agent_id, caller_id, caller_token, session_id, ufcs_command, payload, timestamp}`. Out: `{result, security_flags, elapsed_ms}` |
| Security event bus | `HONEYCODE_TRIGGERED`, `HONEYTOKEN_USED`, `TRIPWIRE_EXECUTED`, `HONEYPOT_TOUCHED`, `ANOMALY_DETECTED`, `FIREWALL_BLOCKED`, `ACCESS_DENIED`, `SESSION_ISOLATED`, `DECOY_ENGAGEMENT`, `SESSION_RELEASED`. Consumers: containment, logging, `qb_log`, and anything added with `qb_shield.subscribe(fn)` |
| `POST /log/event` | Appends an `EXTERNAL_EVENT`, attributed to the calling client |
| `GET /log/verify`, `GET /log/proof` | Section 4.6 |
| Decoy environment | Same request and response shapes as production, backed by `qb_decoy` |
| MCP (`qb_mcp.py`) | stdio JSON-RPC: `initialize`, `tools/list`, `tools/call`, `ping`. Each call goes through the gateway as agent `qb.openclaw` |
| Operator CLI | `python qb_shield.py status \| release <id> \| token <caller> \| plant \| verify-log [--chain]` |

## 6. Non-functional requirements

| Requirement | Result |
|---|---|
| Gateway and firewall overhead < 50 ms per call | About 1 ms per call including the handler (QC measures it each run) |
| Fail closed for high-risk actions if logging fails | High-risk commands write a pre-execution log entry; if that write fails, the call is denied with `fail_closed`. The HTTP gate fails closed for `/agent/`, `/log/`, `/api/nft/` and `/api/openclaw/` |
| Auditability | Every decision is in the log; `/log/verify` and `/log/proof` give integrity proofs |

## 7. Live attack test (2026-10-08, real server, sandboxed home folder)

| Attack | Outcome |
|---|---|
| sqlmap requests `/.env` | Fake secrets served; client isolated; `sqlmap` recorded |
| The same scanner calls `/api/stats` | Synthetic decoy data |
| A different tool reuses the planted fake API key from disk | `HONEYTOKEN_USED`; client isolated |
| An agent calls `ufcs.vault.dump_keys` (honeycode) | Fake export; session isolated; the real `mcp-client` caller not locked out |
| An unauthenticated bot enumerates 9 commands | `ANOMALY_DETECTED`; isolated; then served fake "vault keys", which are themselves honeytokens |
| `log.purge_all` | Tripwire; fake "purged" reply; the log still verifies intact |
| Prompt injection from a hijacked OpenClaw | `FIREWALL_BLOCKED` in 1.1 ms |
| `POST /api/security/release` from the attacker | Refused (CLI only) |
| The operator's browser throughout | Every page and API call kept working |
| Log after the test | Intact; Merkle proof valid; checkpoint anchored on a local EVM chain and matched on-chain |

## 8. Out of scope, deliberately

- **Counter-attacks.** QueryBook fingerprints and records what reaches it. It never scans, probes
  or acts against outside systems ("hacking back").
- **Real-money blockchains.** These are refused unless `qb_nft_config.json` sets
  `"allow_mainnet": true`.
- **Host compromise.** An attacker with administrator rights on the PC can stop QueryBook. The
  mirror and the anchors keep the record of what happened up to that point provable.
