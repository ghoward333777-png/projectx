# QueryBook — Canonical Engine Specification
**Gate 0 deliverable · v1.0 (draft for approval) · 2026‑09‑30**
Single source of truth for the QueryBook prototype. Describes the **frozen baseline**
`QueryBook-baseline-v9.15` (commit `df76b58`) exactly as it behaves — no aspiration mixed in.
Aspirational/roadmap items are labelled **[ROADMAP]**. This is the reference all later gates
measure against, and the document set (Bible/Registry/Patent) is reconciled to at Gate 3.

---

## 1. Purpose & product surfaces
QueryBook is one engine serving three surfaces:
- **Q&A application** — question → retrieve verified Fact Units → gate → cited answer **or honest UNKNOWN**.
- **Chatbot** — same engine; an LLM may *phrase* verified facts, never assert them.
- **LLM competitor** — the moat is the guarantee: deterministic, sourced, reproducible, **cannot hallucinate**; plus learning language, meaning, translation and pronunciation **without an LLM**.

Language, speech and communication are **integral** to the engine (one integrated system), not a side track.

## 2. The Covenant — invariants (must hold at every gate)
| # | Invariant | Verification |
|---|-----------|--------------|
| C1 | No LLM grounds meaning or asserts a fact | code‑path audit; `qb_language.LLM_LOCKOUT=True` drops any grounding suggestor; zero LLM‑sourced asserted facts |
| C2 | Every asserted fact carries a traceable source | each Fact Unit has `sources[]` + `certification`; provenance audit |
| C3 | Determinism: identical input → identical output | `fingerprint()` is a pure function of normalized (s,p,o,polarity); property test |
| C4 | Unknown → refuse (no invention) | gate returns `UNKNOWN`; composer emits the Without‑Information Rule text |
| C5 | Dedup: identical meaning → identical fingerprint → stored once | `add()` skips on existing fingerprint |
| C6 | LLM permitted only to (a) phrase verified facts, (b) propose candidates that are then store‑verified; never to assert | non‑assertion tests on chat/hypothesis/simulation/reasoning |

## 3. Fact Unit contract (from `ufcs_store.make_packet`)
A Fact Unit is a JSON object, `ufcs_version "1.0"`:
```
fuid                 = H(canonical(s,p,o,polarity), source_id, ingested)   # per-ingest id
fact_type            = "assertion"
domain               = e.g. "mathematics", "language", "hypothesis", "simulation", "derived"
nucleus              = { subject, predicate, object }
polarity             = "+" | "-"
semantic_fingerprint = H(norm(s), norm(p), norm(o), polarity)              # content identity
confidence.trust_score
sources[]            = [{ id, name, class, reputation }]
certification        = { authority_class, trust_score }
temporal.ingested    = ISO-8601 UTC
safety               = { classification, acl }
```
- **`_norm`**: trims + lowercases + collapses whitespace, so `"  France "`/`"FRANCE"` share one fingerprint (C3).
- **`H`**: SHA‑256, 64‑hex.
- **Identity = `semantic_fingerprint`** (dedup key). Two facts with the same normalized (s,p,o,polarity) are the same fact (C5).

## 4. Storage & determinism
- **Blocks**: append‑only gzip JSONL under `<store>/blocks/` (target size configurable; default 1 GB compressed). Prototype uses `compresslevel=1` for speed.
- **Index**: SQLite `<store>/index.sqlite`, WAL, autocommit + a process‑wide write lock + commit‑per‑batch (fixes "database is locked"). Tables: `fp(fingerprint,block)`, `nuc(fp,subject,predicate,object,trust,block)`.
- **Manifest**: `<store>/manifest.json`, atomic + merging writes (delta counters); `facts`, per‑domain `facts_dom_*`, `blocks`, `duplicates`, `last_verify`.
- **Continuous mode**: bounded flush increments so a stop request halts promptly (baseline fix); block‑file `getsize` tolerant of mid‑rotation.
- **Determinism**: same generator + inputs ⇒ identical fingerprints ⇒ identical dedup ⇒ identical store (C3). Built‑in QC re‑opens and re‑reads after a completed harvest to prove on‑disk.

## 5. FQL + Prime‑Directive gate
- **FQL** (`st.fql(subject,predicate,trust_min,limit)`) and keyword `search()`; every result set yields a **response_provenance_hash (RPH)** binding the answer to the fingerprints used.
- **Gate** (`qb_chat.gate`) classifies retrieval:
  - `VERIFIED` — usable facts, no functional contradiction.
  - `CONTRADICTED` — a **functional** predicate holds ≥2 different objects (competing values shown, no winner picked).
  - `UNKNOWN` — nothing at/above trust threshold → refuse (C4).
  - **Multi‑valued predicates** (`is_a`, `part_of`, `located_in`, …) may hold several objects without contradiction; **functional** ones (`has_capital`, …) cannot.
- **Chat pipeline**: PLAN → RETRIEVE → GATE → COMPOSE → CHECK; every factual sentence must map to a cited Fact Unit; LLM optional and only for language, never for truth (C6).

## 6. The four language phases (all deterministic, no LLM)
| Phase | Agent kind | What it does | Output | Status |
|---|---|---|---|---|
| 1 Structural (SLPL) | `language` | grapheme inventory, rule‑seeded G2P, syllables, lexical stability, co‑occurrence, prosody; semantics suppressed; drives 4 Transition‑Gate thresholds (τ1 phonemic, τ2 lexical, τ3 co‑occurrence, ε saturation) to a one‑way latch | metric Fact Units (domain `language`) | BUILT |
| 2 Semantic grounding | `lang_semantic` | meaning from a bundled **public‑domain dictionary** (Webster's 1913) + self‑grounding against verified store | `means`, `grounded_by_fact` | BUILT |
| 3 Multilingual delta | `lang_multilingual` | reuse English foundation; learn only the delta to L2 from a bundled bilingual dictionary (es, fr; **CC BY‑NC demo — replace before commercial**) | `translation_<lang>` | BUILT |
| 4 Speech | `lang_speech` | (4a) deterministic pronunciation analysis (G2P phonemes, syllables, stress, prosody) → Fact Units; (4b) real audio via **OS built‑in TTS** (SAPI/`say`/espeak‑ng), never fabricated | `pronunciation`, `syllable_count`, `stress_syllable`; on‑demand WAV | BUILT |
| — full neural LEL / neural vocoder | — | trained parameter model; 7‑stage neural speech | — | [ROADMAP] preferred embodiment |

## 7. Agent family (`qb_agents`, exposed at `/api/agent_roles`)
| Kind | Purpose | LLM policy | Status |
|---|---|---|---|
| `deterministic` | per‑domain rule‑based harvest | none | BUILT |
| `web` | polite crawl + extract | optional extractor | BUILT |
| `grounded_qa` | cite‑or‑refuse Q&A each cycle | phrasing only | BUILT |
| `watch` | re‑answer a standing question; flag changes | phrasing only | BUILT |
| `language` / `lang_semantic` / `lang_multilingual` / `lang_speech` | Phases 1–4 (§6) | **none** (locked out) | BUILT |
| `hypothesis` | LLM proposes candidate facts → **store‑verified** (corroborated/contradicted/open), isolated `hypothesis` domain, trust < 0.5 | propose only, never assert | BUILT |
| `simulation` | LLM projects scenario consequences → store‑verified, isolated `simulation` domain | propose only | BUILT |
| `reasoning` | **deduction asserts** (deterministic transitive closure over verified premises, trust decays per hop, premises as provenance); **induction/abduction propose** (LLM, non‑asserting) | mixed, gated | BUILT |
| `planner` | decompose a goal into ordered intents; **halts on ambiguity**; plan is a non‑asserting proposal | propose only | BUILT |

Roadmap engine set is **empty**: every specified agent is reduced to practice deterministically; full neural forms remain [ROADMAP].

## 8. The LLM‑parity creativity loop  *(owner‑raised; specify here, document at Gate 3)*
**Intent:** reach **equal‑or‑superior LLM‑level creativity and language skill without hallucination.**
**Loop (to be built on the existing agents + archive):**
1. **Hypothesize / simulate** — the hypothesis & simulation agents generate candidate "answers"/continuations (LLM as a *proposer*).
2. **Archive** — every candidate + its verification verdict is recorded (event log / store), timestamped.
3. **Analyze & graph** — trend the archived records over time (coverage, corroboration rate, novelty, contradiction rate).
4. **Measure parity** — an explicit benchmark comparing QueryBook's grounded output to LLM output on **creativity** and **language** tasks, scored on quality **and** on the covenant metrics (citations, zero‑fabrication).
**Covenant compliance:** the LLM only *proposes*; nothing it generates becomes an asserted fact without independent store verification (C6). "Superiority" is defined as *matching LLM fluency/creativity while guaranteeing provenance and zero hallucination.*
**Status:** components exist (hypothesis, simulation, archive/log); the **named loop, the graphing, and the parity benchmark are [ROADMAP]** — to be designed in Gate 2 (criteria) and built in Gate 3+.
**Open spec questions for you:** (a) what corpus/tasks define the creativity+language benchmark? (b) what is the pass bar for "equal" vs "superior"? (c) is the LLM used here local‑only, or any provider?

## 9. API surface (stdlib HTTP, `qb_api`)
GET: `/api/stats /sample /harvest_status /perf /mirror /log /keepawake /agents /agent_roles /selftest /domain_logic /domains /health /fql /verify /get /version` and `/api/language/{status,phases,sources,grounding,multilingual,speech}` and `/api/{hypotheses,plans}`.
POST: `/api/chat /harvest /agents /agents/control /providers /provider_test /fact /keepawake /language/ingest /language/speak /mirror`.

## 10. Traceability map (to be completed & verified in Gate 0 close‑out)
| Spec item | Code | Bible | Registry | Patent |
|---|---|---|---|---|
| Fact Unit (§3) | `ufcs_store.make_packet/fingerprint` | Fact Unit chapter | Fact Unit / Domain 4 | FIG 10, 27, 28 |
| Gate/FQL (§5) | `qb_chat.gate`, `ufcs_store.fql` | Prime Directive | Reasoning/§8 | FIG 14, 15, 22 |
| Phases 1–4 (§6) | `qb_language`, agent branches | Language Architecture + amendments | 16.x, [184]‑[191] | FIG 1‑8 |
| Agents (§7) | `qb_agents` | Reasoning Family amendment | 17.x, [186]‑[189] | — |
| Creativity loop (§8) | hypothesis/simulation + `qb_log` | **gap → Gate 3** | **gap → Gate 3** | **gap → Gate 3** |
*(Cells marked "gap" are what "update everything" resolves at Gate 3.)*

## 11. Baseline reference
`QueryBook-baseline-v9.15`, commit `df76b58`. Source + `BASELINE-CHECKSUMS.md5` in `prototype/QueryBook-baseline-v9.15/`. Self‑test 7/7 all_ok on 3 consecutive runs.

## 12. Gate 0 exit criteria (your approval)
1. This spec matches the frozen baseline (no aspiration presented as built). 2. Every covenant invariant (§2) has a stated check. 3. The creativity loop (§8) is specified with open questions surfaced. 4. Freeze tag + checksums exist (§11). 5. Traceability map (§10) accepted, with the Gate‑3 gaps agreed.
