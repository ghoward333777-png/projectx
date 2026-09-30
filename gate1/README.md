# QueryBook — Gate 1 Test Harness

**Gate 1 of the foolproof phased development plan.** A single-command, flake-free
automated suite that proves the Canonical Engine Spec's covenant invariants
(C1–C6) plus core behaviour against the **frozen baseline**
`QueryBook-baseline-v9.15`. The harness imports the baseline read-only; it never
modifies it.

## Run it

```bash
bash gate1/run-gate1.sh          # engine x3 + UI render check
bash gate1/run-gate1.sh 5        # engine x5
python3 gate1/qb_gate1_harness.py   # engine only (default 3 runs)
python3 gate1/qb_gate1_ui.py        # UI render only
```

Exit code `0` iff every check passes on every run, the deterministic signature
is identical across runs, and every page renders with zero JS errors.

## What it proves

### Engine harness (`qb_gate1_harness.py`) — 17 checks

| Invariant | Check |
|---|---|
| **C1** no LLM grounds meaning | Phase-2 grounder drops any suggestor and never calls it; `LLM_LOCKOUT` is `True`; zero `means_confirmed` facts from an injected suggestion |
| **C2** every fact has provenance | stored fact retains `sources[]` + `certification` |
| **C3** determinism | fingerprint is pure/normalized/collision-free; identical nuclei collapse to one identity; **signature identical across all N runs** |
| **C4** unknown → refuse | gate returns `VERIFIED` / `CONTRADICTED` / `UNKNOWN`; functional vs multi-valued predicates; composer emits the Without-Information Rule |
| **C5** dedup | identical meaning stored once |
| **C6** LLM never asserts | a trust-0.4 hypothesis is gated out of every answer; agent family = 12 roles all `built`, roadmap engine empty |
| Phases 1–4 | SLPL structural learning; deterministic dictionary grounding (Webster's 1913); multilingual delta (es/fr); pronunciation analysis + honest OS-TTS status |

The suite runs **N consecutive times** and fails if any run is red **or** if the
deterministic signature drifts between runs — this is what would have caught the
24×7-stop race before it ever reached a user.

### UI render check (`qb_gate1_ui.py`)

Boots the real baseline `qb_api` server against a small throwaway store and drives
a headless Chromium (Node Playwright) over every page route — `/dashboard`,
`/language`, `/chat`, `/console`, `/guide` — failing on any JavaScript console
error or uncaught page error. Self-contained: the server is started and stopped
within the process, nothing is left running.

## Latest evidence

- Engine: **17/17 checks, 5/5 runs green, one identical signature** (`937f6413bbd6474b`).
- UI: **5/5 pages HTTP 200 with 0 JS errors**, green on 3 consecutive runs.
