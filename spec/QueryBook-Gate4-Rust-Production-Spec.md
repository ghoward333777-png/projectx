# QueryBook — Gate 4 Rust Production Specification

**Gate 4 deliverable · v1.0 · 2026‑09‑30**
The architecture for the production build. The Python prototype
(`QueryBook-baseline-v9.15`) proves the concept and is the **parity oracle**; the
production engine is Rust, optimized for RAM/storage, deployed as an Ubuntu SaaS.
Nothing here weakens the Covenant (spec §2) — it moves the guarantees into the
type system. No Rust ships until this spec and its budgets are approved (Gate 4
exit), then module‑by‑module with parity tests against the prototype (Gate 5).

## 1. Goals & non‑goals
- **Goals:** byte‑for‑byte fact identity parity with the prototype; ≤ ~120 B/fact
  all‑in on disk; deterministic; the Covenant enforced by types; horizontal read
  scaling; safe 24×7 continuous harvest.
- **Non‑goals (this gate):** rewriting the LLM proposer/phrasing layer (stays a
  network boundary), the neural LEL/vocoder (roadmap), and the web UI (reused).

## 2. Workspace layout (crates)
```
querybook/
  qb-core        // Fact Unit, _norm, fingerprint, fuid, SHA-256 — no deps, the parity heart
  qb-store       // append-only blocks + index (LSM), manifest, write lock
  qb-fql         // FQL + Prime-Directive gate (VERIFIED/CONTRADICTED/UNKNOWN)
  qb-lang        // Phases 1–4 (deterministic), ported from qb_language
  qb-agents      // agent family; LLM roles behind a Proposer trait (network boundary)
  qb-api         // HTTP surface (axum or hyper), mirrors qb_api routes
  qb-parity      // cross-language parity harness vs the Python oracle
  qbd            // the server binary
```
Dependency policy: `qb-core` is **dependency‑free** (own SHA‑256), mirroring the
prototype's ethos and guaranteeing the fingerprint has no external surface.
Outer crates may use vetted crates (hashing‑free) — pinned, `cargo-audit`ed.

## 3. Fact Unit — the identity contract [spec §3]
`norm(s) = s.trim().to_lowercase()` with **all Unicode‑whitespace runs collapsed
to a single U+0020** (matches Python `" ".join(str(s).strip().lower().split())`).
- `fingerprint(s,p,o,polarity) = SHA256_hex( norm(s) ⧺ "|" ⧺ norm(p) ⧺ "|" ⧺ norm(o) ⧺ "|" ⧺ polarity )`.
- `fuid(...) = SHA256_hex( content ⧺ "|" ⧺ source_id ⧺ "|" ⧺ ingested )` where
  `content` is Python‑compatible `json.dumps({"o","p","pol","s"}, sort_keys=True,
  ensure_ascii=True)` with separators `", "` / `": "` — i.e. keys sorted `o,p,pol,s`,
  non‑ASCII escaped as `\uXXXX`, control chars per JSON. **This exact byte string is
  reproduced in Rust** (see qb‑parity), because the fingerprint/fuid must match the
  prototype's stored data on migration.
- **Identity = `semantic_fingerprint`** (dedup key); `fuid` is per‑ingest.
- Parity is contractual: **AC‑R1/R2** (Gate 2) require byte‑identical output on a
  shared vector set drawn from the prototype.

## 4. Binary on‑disk format & the ~120 B/fact budget
Per stored fact, target all‑in ≈ **120 bytes**:
| Component | Bytes (approx) | Note |
|---|---|---|
| fingerprint | 32 | raw SHA‑256 (not the 64‑hex text) |
| trust | 4 | f32 |
| polarity + flags | 1 | bitfield |
| domain id | 2 | interned (domain dictionary) |
| s/p/o | variable | interned string ids + small residual; short‑string table + block‑local dictionary |
| index entry amortized | ~ | LSM key = fingerprint prefix → (block, offset) |
The prototype's gzip‑JSONL is replaced by **columnar, dictionary‑encoded, LZ4‑framed
blocks** (subject/predicate/object interned per block; the high‑cardinality object
residual dominates). 1 B facts ≈ **120 GB**; server fixed cost ≈ **5 GB**; so
`disk ≈ 5 GB + facts × 120 B`. Budget is validated under load at Gate 6.

## 5. Index / LSM design
- **Primary:** fingerprint → (block_id, offset). An LSM (memtable + leveled SSTables)
  keyed by the 32‑byte fingerprint; dedup is a point lookup before append.
- **Secondary:** `(subject, predicate)` → posting list for FQL; `(predicate)` and a
  trust‑bucketed skip for gate thresholds.
- Bloom filters per SSTable on the fingerprint key make the dedup check ~O(1) with
  bounded false‑positive I/O. Compaction is deterministic and back‑pressured so a
  24×7 writer never starves reads.

## 6. Concurrency model
- **Single writer, many readers** per store shard (replaces the prototype's
  process‑wide write lock). The writer owns the memtable; readers see immutable
  SSTables + a snapshot of the memtable via an epoch/`arc-swap`‑style handoff.
- **Continuous harvest** runs on the writer with **bounded flush increments** and a
  cooperative stop token (the Rust form of the baseline's stop‑race fix) — proven by
  a stress test that must pass N consecutive runs (the Gate 1 discipline, ported).
- **Sharding** by fingerprint prefix gives horizontal write throughput and read
  parallelism; a query fans out and merges with a stable order for determinism.

## 7. The Covenant in the type system [spec §2]
- `AssertedFact` can be constructed **only** by `Store::commit`, which requires a
  `Provenance { sources: NonEmpty<Source>, certification }` — **C2 is unrepresentable
  to violate** (no source ⇒ won't compile).
- Retrieval returns a `Verdict` enum `{ Verified(Vec<Cited>), Contradicted(..), Unknown }`;
  the composer accepts only `Verified`/`Contradicted`, and `Unknown` has **no**
  answer‑bearing variant — **C4** by construction.
- The LLM lives behind a `trait Proposer { fn propose(..) -> Vec<Candidate>; }`. A
  `Candidate` has **no** path to `AssertedFact` except through `Store::verify` →
  low‑trust isolated domain; there is no `From<Candidate> for AssertedFact` — **C6/C1**
  by construction.
- `fingerprint`/`fuid` are pure `fn`s of their inputs (no clock, no RNG) — **C3**.

## 8. Determinism
Same generator + inputs ⇒ identical fingerprints ⇒ identical dedup ⇒ identical
store bytes after canonical compaction. A `--verify` mode re‑reads a completed
store and recomputes fingerprints. The Gate‑1 "signature across N runs" guard is
reproduced as a Rust integration test.

## 9. API surface
`qb-api` mirrors the prototype routes (spec §9) on `axum`/`hyper`; same JSON
shapes, so the existing dashboard/Language Lab HTML is reused unchanged. The
`/api/language/speak` audio path shells to the OS TTS exactly as the prototype.

## 10. Migration & parity strategy [Gate 5]
1. Freeze a **parity vector set** exported from the Python oracle (nucleus tuples +
   their fingerprints/fuids), covering normalization (case, whitespace runs,
   punctuation), ASCII, and Unicode (`ensure_ascii` escaping) edges.
2. `qb-core` recomputes and must match **byte‑for‑byte** (AC‑R1/R2). This is a
   committed, runnable test — the first thing built at Gate 5.
3. Each further module ships with a parity test against the prototype's behaviour
   (dedup, gate verdicts, phase outputs) before it is accepted.
4. A one‑time importer reads prototype gzip‑JSONL blocks and writes native blocks,
   asserting fingerprints are preserved.

## 11. Security (preview; audited at Gate 6)
- Read‑only API tokens vs. a single writer credential; per‑domain ACLs from the
  Fact Unit `safety` field.
- The Proposer network boundary is the only egress; keys from env/secret store,
  never logged; the covenant means a compromised proposer can still never assert.
- Provenance audit: a scan proving no `AssertedFact` lacks a traceable source.

## 12. Gate 4 exit criteria (approval)
1. Workspace/crate split and the dependency‑free `qb-core` boundary accepted.
2. The Fact Unit identity contract (§3) matches the prototype exactly (proven at G5).
3. The ~120 B/fact budget and `5 GB + facts×120 B` sizing accepted as the Gate 6 target.
4. The type‑system encoding of C1–C6 (§7) accepted.
5. The parity strategy (§10) accepted as the gate on every Gate 5 module.
