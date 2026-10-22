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
| **Self-Knowledge Layer (SKL)**: QueryBook describes itself accurately, with sources — every Overview section and twelve reasoning aspects (deterministic, atomic, world model, predictive, neuromorphic, hypothesis, simulation, deduction, feedback, self-improvement, RSI, self-knowledge) labelled built / partly built / specified / not planned, checked against its own code, with a contradiction check and a gap agenda (Registry 383–391) | `qb_selfknow.py` (same file as `apps/_core/qbselfknow.py`), `/api/self`, `/api/self/ask` | `/self` |

The specification, with requirement-to-code-to-test traceability and the live attack test, is in
[`QueryBook-v9.64/SECURITY-SPEC.md`](QueryBook-v9.64/SECURITY-SPEC.md).

## Documents

| Document | File |
|---|---|
| Core Technology Overview v15 (§56 The Self-Knowledge Layer added) | [`docs/QueryBook_Core_Technology_Overview_v15_Addendum_Oct22.docx`](docs/) (+ `.pdf`) |
| QueryBook Bible v2.1, Pass 119 (Chapter 130 The Self-Knowledge Layer added to Pass 118) | [`docs/QueryBook_Bible_v2.1_Pass_119_SelfKnowledgeLayer.docx`](docs/) (+ `.pdf`) |
| Composite Feature Registry v70 (391 features; SKL 383–391, ALG-20/21, FIG. 57) | [`patent/registry/QueryBook_Composite_Feature_Registry_v70.xlsx`](patent/registry/) |
| Provisional, synchronized, with the self-knowledge layer (FIG. 57, claims 358–362), clean and changes-highlighted | [`patent/prov_oct9/Prov_Patent_Oct9_SYNCED_SelfKnowledge_*`](patent/prov_oct9/) |
| Drawings FIG. 1–57 and their description | [`patent/prov_oct9/QueryBook_Drawings_FIG1-57_SelfKnowledge.pdf`](patent/prov_oct9/), `QueryBook_Drawings_Description_FIG1-57.*` |

All SKL wording comes from one file, [`docs/source/skl_text.py`](docs/source/skl_text.py); the build scripts beside it
(and `patent/registry/source/build_v70.py`, `patent/prov_oct9/source/self_knowledge/`) only add — no earlier text changes.

## Checks

```
python qb_selftest.py        # 12 checks: core store + all new modules, including the self-knowledge layer
python qb_shield.py --qc     # 25 · python qb_seclog.py --qc  # 11 · python qb_openclaw.py --qc  # 30
python qb_mcp.py --qc        # 7  · python qb_nft.py --qc     # 16 (offline test vectors)
```
