# QueryBook v9.64

QueryBook v9.64 is built on v9.63 (`prototype/QueryBook-v9.47` on branch `claude/cool-allen-a1a5uw`).
Run it on Windows by double-clicking `START_QUERYBOOK.bat`. Plain-language notes are in
`READ_ME_FIRST.txt`.

## What v9.64 adds

| Feature | Files | Page |
|---|---|---|
| Real on-chain NFTs: ERC-721 certificates, lineage, revocation, ownership checks, transfer and NFT licensing (Registry 101, 109–118). Test networks by default | `qb_nft.py`, `contracts/QueryBookProvenance.sol` (+ compiled `.json`) | `/openclaw` |
| Open Claw ingestion of any file, using the OpenClaw Interpreter and the Artifact Segmenter | `qb_openclaw.py` | `/openclaw` |
| OpenClaw agent support: MCP server through the Agent Gateway, plus an OpenClaw skill | `qb_mcp.py`, `openclaw/querybook/SKILL.md`, `openclaw/README.txt` | — |
| Agent Protection & Deception layer: gateway, honeycode, honeytokens, tripwires, honeypots, AI-aware firewall, anomaly detection, containment and decoy environment | `qb_shield.py`, `qb_decoy.py`, `shield_policy.json` | `/security` |
| Tamper-evident security log: hash chain, Merkle checkpoints, write-once files, mirror, blockchain anchoring and proofs | `qb_seclog.py` | `/security` |

The specification, with requirement-to-code-to-test traceability and the live attack test, is in
[`QueryBook-v9.64/SECURITY-SPEC.md`](QueryBook-v9.64/SECURITY-SPEC.md).

## Checks

```
python qb_selftest.py        # 11 checks: core store + all new modules (89 sub-checks)
python qb_shield.py --qc     # 25 · python qb_seclog.py --qc  # 11 · python qb_openclaw.py --qc  # 30
python qb_mcp.py --qc        # 7  · python qb_nft.py --qc     # 16 (offline test vectors)
```
