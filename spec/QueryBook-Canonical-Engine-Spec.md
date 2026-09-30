# QueryBook — Canonical Engine Specification
**Gate 0 deliverable · v1.1 (§8 answered; ratify at Gate 2) · 2026‑09‑30**
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

## 8. The LLM‑parity creativity loop  *(owner‑raised; specified here, ratified at Gate 2, documented at Gate 3)*
**Intent:** reach **equal‑or‑superior LLM‑level creativity and language skill without hallucination.**
**Loop (to be built on the existing agents + archive):**
1. **Hypothesize / simulate** — the hypothesis & simulation agents generate candidate "answers"/continuations (LLM as a *proposer*).
2. **Archive** — every candidate + its verification verdict is recorded (event log / store), timestamped.
3. **Analyze & graph** — trend the archived records over time (coverage, corroboration rate, novelty, contradiction rate).
4. **Measure parity** — an explicit benchmark comparing QueryBook's grounded output to a pinned reference LLM on **creativity** and **language** tasks, scored on quality **and** on the covenant metrics (citations, zero‑fabrication).
**Covenant compliance:** the LLM only *proposes*; nothing it generates becomes an asserted fact without independent store verification (C6). "Superiority" is defined as *matching LLM fluency/creativity while guaranteeing provenance and zero hallucination.*
**Status:** components exist (hypothesis, simulation, archive/log); the **named loop, the graphing, and the parity benchmark are [ROADMAP]** — designed in Gate 2 (criteria), built in Gate 3+.

### 8.1 Answered spec questions *(proposed defaults — ratify or adjust at Gate 2)*

**(a) What corpus/tasks define the creativity + language benchmark?**
A fixed, versioned, license‑clean set — **QB‑CreativityBench v1** — checked into the repo with per‑item gold answers or rubrics, a `LICENSE` note per source, and a `manifest.json` recording size and provenance. Sources are public‑domain / permissively licensed only (consistent with C2 and the whole project's source discipline). Four task families (≈200 items total, fixed):
1. **Grounded factual Q&A** — questions whose answers *are* in the store (measures citation coverage + accuracy) **plus a held‑out set the store does NOT contain** (measures honest‑UNKNOWN / refuse rate). Sources: Webster's 1913, Project Gutenberg reference texts, other public‑domain reference corpora.
2. **Language fluency** — prompts requiring fluent multi‑paragraph explanation/summary; scored by the deterministic linguistic metrics already in the engine (rhythm/variety/hygiene) plus a blind judge panel (§b).
3. **Creative composition** — constrained creative tasks (metaphor for X, continue a scenario) where the hypothesis/simulation agents propose and the store verifies; measures novelty + coherence + **zero fabrication** (every asserted claim cited).
4. **Multilingual + speech** — a fixed translate‑and‑pronounce list scored deterministically against the bundled bilingual (es/fr) and G2P references (Phases 3–4).
The set is versioned; a benchmark change bumps the version and never edits v1 in place (reproducibility).

**(b) What is the pass bar for "equal" vs "superior"?**
Two independent axes, both required:
- **Quality axis** — blind, pre‑registered judge panel scores QueryBook output against a pinned reference LLM on the same items (judges do not know which is which). Report `quality_ratio = QB_score / LLM_score`.
- **Covenant axis** — measured on QueryBook only: **100 %** of asserted facts carry a citation, **0** fabricated facts, and deterministic reproduction across **N ≥ 3** runs (identical export md5).
Bars:
- **EQUAL** ⇔ `quality_ratio ≥ 0.95` **AND** covenant axis perfect.
- **SUPERIOR** ⇔ `quality_ratio ≥ 1.00` **AND** covenant axis perfect.
Because the reference LLM cannot structurally achieve *cited, zero‑fabrication, deterministic* output, once quality parity is reached QueryBook is categorically ahead on the covenant axis — that is the operational meaning of "superior." All scores are reported against the **specific pinned baseline**, never "an LLM" generically.

**(c) Is the LLM local‑only, or any provider?**
Distinguish two roles:
- **Proposer** (hypothesis / simulation / answer‑phrasing inside QueryBook): **provider‑agnostic but covenant‑bound.** Any provider — local or hosted — may be plugged in, because nothing it emits is asserted without store verification (C6). For a reproducible benchmark run the proposer must be **pinned** (fixed model + fixed decoding/seed where the provider allows) and recorded in the run manifest. Production SaaS **prefers a local, pinned model** for determinism and privacy; hosted providers are permitted when pinned and logged.
- **Benchmark comparator**: a **named, version‑pinned frontier LLM**, recorded per run, so the comparison is reproducible and always attributable to a specific baseline.

These three answers become the seed of the Gate‑2 acceptance criteria for the creativity loop; the benchmark corpus, scoring harness, and graphing are built in Gate 3+.

## 9. API surface (stdlib HTTP, `qb_api`)
GET: `/api/stats /sample /harvest_status /perf /mirror /log /keepawake /agents /agent_roles /selftest /domain_logic /domains /health /fql /verify /get /version` and `/api/language/{status,phases,sources,grounding,multilingual,speech}` and `/api/{hypotheses,plans}`.
POST: `/api/chat /harvest /agents /agents/control /providers /provider_test /fact /keepawake /language/ingest /language/speak /mirror`.

## 10. Traceability map (to be completed & verified in Gate 0 close‑out)
| Spec item | Code | Bible | Registry | Patent |
|---|---|---|---|---|
| Fact Unit (§3) | `ufcs_store.make_packet/fingerprint` | Fact Unit chapter | Fact Unit / Domain 4 | FIG 10, 27, 28 |
| Gate/FQL (§5) | `qb_chat.gate`, `ufcs_store.fql` | Prime Directive | Reasoning/§8 | FIG 14, 15, 22 |
| Phases 1–4 (§6) | `qb_language`, agent branches | Language Architecture + amendments (incl. Phase 4 amendment, 2026‑09‑30) | 16.x, [184]‑[191] | FIG 1‑8; PPA [0021]‑[0025] |
| Agents (§7) | `qb_agents` | Reasoning Family amendment | 17.x, [186]‑[189] | PPA [0023] |
| Creativity loop (§8) | hypothesis/simulation + `qb_log` | Bible amendment "Phase 4 Speech and the LLM‑Parity Creativity Loop" (2026‑09‑30) | [192] 17.9 | PPA [0026] (preferred/prophetic) |
*(The former "gap → Gate 3" cells were resolved at Gate 3, 2026‑09‑30; see `QueryBook-Gate3-Lockstep-Verification.md`.)*

## 11. Baseline reference
`QueryBook-baseline-v9.15`, commit `df76b58`. Source + `BASELINE-CHECKSUMS.md5` in `prototype/QueryBook-baseline-v9.15/`. Self‑test 7/7 all_ok on 3 consecutive runs.

## 12. Gate 0 exit criteria (your approval)
1. This spec matches the frozen baseline (no aspiration presented as built). 2. Every covenant invariant (§2) has a stated check. 3. The creativity loop (§8) is specified, with the three open questions answered as proposed defaults (§8.1) for ratification at Gate 2. 4. Freeze tag + checksums exist (§11). 5. Traceability map (§10) accepted, with the Gate‑3 gaps agreed.
