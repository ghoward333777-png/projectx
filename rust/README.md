# QueryBook — Rust production engine (Gates 4–5)

The production build specified in `spec/QueryBook-Gate4-Rust-Production-Spec.md`.
The Python prototype `QueryBook-baseline-v9.15` is the **parity oracle**; every
Rust module must match it before it is accepted (the Gate 5 discipline).

## Status

| Crate | Purpose | State |
|-------|---------|-------|
| `qb-core` | Fact Unit identity — `norm`, `fingerprint`, `fuid`, own SHA-256 | **built + parity-proven** |
| `qb-store` | append-only blocks + LSM index + manifest | spec'd (Gate 4 §4–5) |
| `qb-fql` | FQL + Prime-Directive gate | spec'd (Gate 4) |
| `qb-lang` | Phases 1–4 (deterministic) | spec'd |
| `qb-agents` | agent family; LLM behind a `Proposer` trait | spec'd |
| `qb-api` | HTTP surface (reuses the prototype UI) | spec'd |
| `qbd` | server binary | spec'd |

`qb-core` is **dependency-free** by policy — it carries its own SHA-256 so the
content-address has no external surface, and every function is pure (Covenant C3).

## Build & prove parity

```bash
cd rust
python parity/gen_vectors.py          # export vectors from the Python oracle
cargo test --release                  # unit tests + the parity integration test
cargo run --release --bin parity -- parity/vectors.tsv   # visible parity report
```

## Evidence (2026-09-30)

- `cargo test`: 3 unit tests (SHA-256 known-answer, normalization, fingerprint) + the
  parity integration test — all green.
- `parity`: **14/14 fingerprint and 14/14 fuid byte-identical** to the Python oracle,
  covering case/whitespace normalization, tab/newline collapse, non-ASCII
  (`°C`, `café`, CJK), JSON-escape characters, and an astral-plane emoji
  (surrogate-pair `ensure_ascii` escaping). Satisfies AC-R1 and AC-R2.

## Next (Gate 5, module by module)

`qb-store` next: the binary block format and LSM index from Gate 4 §4–5, each with a
parity test (dedup identity, round-trip, manifest counters) against the prototype,
then `qb-fql` (gate verdicts), `qb-lang` (phase outputs), `qb-agents`, `qb-api`.
