# QueryBook — Gate 6 Scale, Security & Provenance Audit Plan

**Gate 6 deliverable · v1.0 · 2026‑09‑30 · EXECUTES AFTER the Gate 5 Rust build**
This is the audit methodology and its pass/fail bars. It is a **plan, not a result**:
the load numbers and the security/provenance findings are produced by *running* this
plan against the completed Rust engine (Gate 5). It is written now so the bar is set
before the build, per the gated discipline. Criteria trace to Gate 2 (AC‑R4) and the
Covenant (spec §2).

## 1. Scale / load audit
**Target model (from Gate 4 §4):** `disk ≈ 5 GB + facts × 120 B`; validate it.

**Traffic tiers to run** (facts ingested/day): **1 M · 50 M · 100 M · 500 M · 1 B**.
For each tier, a sustained run plus a 24×7 soak:

| Metric | How measured | PASS bar |
|---|---|---|
| Ingest throughput | facts/sec sustained over ≥1 h | meets the tier's required rate with ≤70 % of a defined core budget |
| Dedup lookup | p50/p99 fingerprint point-lookup latency | p99 < 1 ms at 100 M; < 5 ms at 1 B (SSD) |
| Query (FQL+gate) | p50/p99 over a fixed query mix | p99 < 50 ms at 100 M |
| RAM | RSS at steady state | within the declared budget; no unbounded growth over the soak |
| Disk/fact | total store bytes ÷ facts | **within ±15 % of 120 B/fact** (AC‑R4) |
| Compaction | read p99 during compaction vs idle | back‑pressure keeps read p99 within 2× idle; a 24×7 writer never starves reads |
| Continuous‑stop | stop token honoured under full load | halts within one bounded flush; **N consecutive soak/stop runs green** (the Gate‑1 signature‑drift guard, ported to Rust) |

**Method:** a deterministic generator (seeded) drives ingest; a separate reader pool
drives the query mix; metrics via the engine's own counters + OS sampling. Every run
is repeatable (same seed ⇒ same store bytes after canonical compaction — a determinism
re‑check at scale).

## 2. Security review
**Threat model & controls to audit:**
- **Write authority.** One writer credential vs. read‑only API tokens; verify a read
  token cannot mutate. Per‑domain ACLs enforced from the Fact Unit `safety` field.
- **Proposer egress boundary.** The LLM `Proposer` trait is the *only* outbound network
  path. Verify: (a) a compromised/hostile proposer still cannot assert a fact (C6 holds
  by type); (b) keys come from env/secret store and never appear in logs, errors, or the
  store; (c) egress is allow‑listed.
- **Input hardening.** Fuzz the block reader, index reader, FQL parser, and HTTP/JSON
  surface (`cargo fuzz`); no panic/UB on malformed input; bounded memory per request.
- **Supply chain.** `cargo audit` + `cargo deny` clean; `qb-core` stays dependency‑free;
  pinned versions; reproducible build.
- **Isolation.** hypothesis/simulation/plan domains cannot be promoted to asserted facts;
  a red‑team attempt to get a proposal returned as a verified answer must fail.

**PASS bar:** no High/Critical finding open; every covenant‑relevant control has a test.

## 3. Provenance audit (Covenant enforcement at scale)
- **C2 scan.** Walk the entire store; assert **every** `AssertedFact` has a non‑empty
  `sources[]` with a resolvable id and a `certification`. Zero exceptions.
- **C1 scan.** Assert **zero** asserted facts originate from an LLM (source class audit);
  `LLM_LOCKOUT` equivalent holds in the language path.
- **C4/C6 replay.** Replay the Gate‑1/Gate‑2 verdict and non‑assertion suites against the
  Rust engine at scale; UNKNOWN→refuse and "low‑trust proposal never answered" must hold.
- **C3 replay.** Rebuild a store from the same seed; assert identical fingerprints and
  identical canonical bytes.

**PASS bar:** all four scans clean over the full store; any exception is a release blocker.

## 4. Deliverables
A dated audit report per tier (numbers + graphs), a security findings log with
dispositions, and a provenance‑scan attestation. These become the evidence for the
Gate 6 sign‑off.

## 5. Gate 6 exit criteria (approval)
1. Every traffic tier meets its throughput/latency bars; the 120 B/fact budget holds (±15 %).
2. 24×7 soak + stop is green across N consecutive runs.
3. No open High/Critical security finding; the proposer boundary and write‑authority controls are proven.
4. All four provenance/covenant scans are clean over the full store.
