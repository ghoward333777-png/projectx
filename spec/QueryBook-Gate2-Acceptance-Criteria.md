# QueryBook — Gate 2 Acceptance Criteria (per component)

**Gate 2 deliverable · v1.0 · 2026‑09‑30**
Explicit pass/fail criteria for every subsystem. Nothing is built, changed, or
"fixed" without a criterion it must meet. Each criterion names **how it is
measured** and **where it is verified today** (a Gate 1 harness check, a live
run, or a gate that will verify it). Criteria trace to the Canonical Engine
Spec (`QueryBook-Canonical-Engine-Spec.md`) sections shown in brackets.

Legend for *Verified by*: **G1‑engine** = `gate1/qb_gate1_harness.py`;
**G1‑ui** = `gate1/qb_gate1_ui.py`; **G3** = proven at Gate 3 hardening;
**G5** = proven by Rust parity tests; **G6** = proven at the scale/security audit.

---

## A. Covenant invariants (must hold at every gate) [spec §2]

| ID | Component | PASS criterion | FAIL if | Measure | Verified by |
|----|-----------|----------------|---------|---------|-------------|
| AC‑C1 | LLM lockout | `LLM_LOCKOUT is True`; the Phase‑2 grounder never invokes a passed suggestor; zero `means_confirmed`/LLM‑sourced *asserted* facts | any suggestor callable is invoked, or any asserted fact carries an LLM source | count suggestor invocations = 0; SQL count of LLM‑sourced asserted facts = 0 | **G1‑engine** ✓ |
| AC‑C2 | Provenance | every stored fact carries a non‑empty `sources[]` (with an id) and a `certification.authority_class` + `trust_score` | any stored fact lacks a source or certification | read back a stored packet; assert fields present | **G1‑engine** ✓ |
| AC‑C3 | Determinism | identical normalized `(s,p,o,polarity)` → identical `semantic_fingerprint`; a full suite run yields a byte‑identical signature across **N≥5** consecutive runs | any signature drift across runs; any case/space variant producing a different fingerprint | SHA‑256 signature compare across runs | **G1‑engine** ✓ (5/5, `937f6413…`) |
| AC‑C4 | Refuse on unknown | gate returns `UNKNOWN` for empty/sub‑threshold retrieval; composer emits the Without‑Information Rule and invents nothing | any fabricated content when no fact supports it | assert verdict + composed text | **G1‑engine** ✓ |
| AC‑C5 | Dedup | a second identical fact is skipped; store count unchanged | a duplicate fingerprint is stored twice | add twice; assert store holds 1 | **G1‑engine** ✓ |
| AC‑C6 | LLM never asserts | a trust‑<0.5 hypothesis/simulation fact is excluded from every answer by the default gate; the 12 agent roles are all `built`; roadmap‑engine set empty | any low‑trust proposal reaches a composed answer | gate a trust‑0.4 fact → `UNKNOWN`; inspect `ROLES`/`_ROADMAP_ENGINE` | **G1‑engine** ✓ |

## B. Fact Unit & Store [spec §3, §4]

| ID | Component | PASS criterion | Measure | Verified by |
|----|-----------|----------------|---------|-------------|
| AC‑B1 | Fact Unit shape | packet carries `ufcs_version, fuid, fact_type, domain, nucleus{s,p,o}, polarity, semantic_fingerprint, confidence.trust_score, sources[], certification, temporal.ingested, safety` | field audit on `make_packet` | **G1‑engine** ✓ |
| AC‑B2 | Fingerprint | SHA‑256, 64 hex; pure function of normalized nucleus + polarity; distinct objects differ | assert length/charset/collision | **G1‑engine** ✓ |
| AC‑B3 | Round‑trip | a written fact reads back byte‑identical after store reopen | write → close → reopen → get | **G1‑engine** ✓ |
| AC‑B4 | Blocks/index/manifest integrity | gzip JSONL blocks + SQLite index (`fp`, `nuc`) + atomic merging manifest stay consistent; `reconcile_manifest` makes the counter match the index | harvest, reopen, reconcile; counts agree | **G1‑engine** (round‑trip/dedup) ✓; **G3** (fuzz) |
| AC‑B5 | 24×7 continuous mode | a stop request halts within a bounded flush; a mid‑rotation block file never crashes flush | threaded start/stop; no exception; thread exits | baseline `qb_selftest` "24×7 stop control" ✓; **G3** (stress) |
| AC‑B6 | Resume‑and‑grow | re‑harvesting an existing store increases the count (no stall) | two harvests; second > first | baseline `qb_selftest` ✓ |

## C. FQL, Gate & Chat pipeline [spec §5]

| ID | Component | PASS criterion | Measure | Verified by |
|----|-----------|----------------|---------|-------------|
| AC‑D1 | FQL + RPH | every result set yields a response‑provenance hash binding the answer to the fingerprints used | inspect `fql`/`retrieve` return | **G1‑engine** (indirect); **G3** (explicit RPH test) |
| AC‑D2 | Gate VERIFIED | clean single‑valued facts → `VERIFIED` with usable set | assert verdict | **G1‑engine** ✓ |
| AC‑D3 | Gate CONTRADICTED | a **functional** predicate holding ≥2 objects → `CONTRADICTED`; competing values shown, no winner | assert verdict | **G1‑engine** ✓ |
| AC‑D4 | Multi‑valued tolerance | a `MULTI_VALUED` predicate holding ≥2 objects → `VERIFIED` (not a contradiction) | assert verdict | **G1‑engine** ✓ |
| AC‑D5 | Cite‑or‑refuse compose | every factual sentence maps to a cited Fact Unit; LLM optional and only for phrasing | compose/check path; citation coverage = 100% | **G3** (citation‑coverage test on a fact set) |

## D. Language phases (all deterministic, no LLM) [spec §6]

| ID | Component | PASS criterion | Measure | Verified by |
|----|-----------|----------------|---------|-------------|
| AC‑P1 | Phase 1 SLPL | learning writes metric Fact Units (domain `language`); the four Transition‑Gate thresholds (τ1,τ2,τ3,ε) are computed; vocabulary grows; **no** semantic facts emitted in Phase 1 | `learn()` returns metrics + `facts_written>0`; gate checks present | **G1‑engine** ✓ |
| AC‑P2 | Phase 2 semantic | grounding is deterministic (identical results on re‑run), sourced from Webster's 1913 (`means`) and the store (`grounded_by_fact`); no network, no LLM | ground the same words twice → identical facts/defs; Webster source present | **G1‑engine** ✓ |
| AC‑P3 | Phase 3 multilingual | es+fr available; `translation_<lang>` facts written deterministically from the bundled bilingual set; **license flagged** (CC BY‑NC demo) until replaced | acquire twice → identical count; `available_languages` ⊇ {es,fr} | **G1‑engine** ✓ |
| AC‑P4a | Phase 4 analysis | `analyze_pronunciation` is deterministic (phonemes, syllables, 1≤stress≤syllables); `speech_analyze` writes `pronunciation`/`syllable_count`/`stress_syllable` facts | analyze twice → identical; analyzed>0 | **G1‑engine** ✓ |
| AC‑P4b | Phase 4 audio | real audio only via OS TTS; when no engine is present `speak()` returns `wav_bytes=None` + an honest hint and **never fabricates**; never raises | call on the host; assert shape + honesty | **G1‑engine** ✓ |

## E. Agent family [spec §7]

| ID | Component | PASS criterion | Measure | Verified by |
|----|-----------|----------------|---------|-------------|
| AC‑E1 | Roster | exactly the 12 specified roles exist, each `status="built"`; `_ROADMAP_ENGINE == {}` | inspect `ROLES` | **G1‑engine** ✓ |
| AC‑E2 | deterministic/web/grounded_qa/watch | each runs a cycle without asserting anything uncited; web crawl is polite (rate‑limited, robots‑aware) | **G3** per‑agent cycle test | **G3** |
| AC‑E3 | hypothesis / simulation | proposals land only in the isolated `hypothesis`/`simulation` domain at trust<0.5; each is store‑verified (corroborated/contradicted/open); nothing proposed becomes an asserted fact; refuses gracefully with no provider | **G3** (with a mock proposer) + AC‑C6 gate exclusion ✓ | **G1‑engine** (isolation) ✓; **G3** (full cycle) |
| AC‑E4 | reasoning | deductive transitive closure over VERIFIED premises asserts derived facts, each carrying its premises as provenance and trust decaying per hop; induction/abduction are non‑asserting | **G3** closure test (premises→derived, trust monotonic‑decreasing) | **G3** |
| AC‑E5 | planner | decomposes a goal into ordered intents; **halts on ambiguity** (asks, never guesses); plan is a non‑asserting proposal in a `plan` domain | **G3** ambiguity‑halt test | **G3** |

## F. LLM‑parity creativity loop [spec §8, §8.1]

| ID | Component | PASS criterion | Measure | Verified by |
|----|-----------|----------------|---------|-------------|
| AC‑F1 | Benchmark corpus | **QB‑CreativityBench v1** exists: fixed, versioned, license‑clean, ~200 items across the four task families with gold answers/rubrics + a per‑source LICENSE note | corpus manifest present + license audit | **G3** (build corpus) |
| AC‑F2 | Archive & graph | every proposal + its verification verdict is recorded (timestamped) and trended (coverage, corroboration, novelty, contradiction rate) | archive schema + a rendered trend | **G3** |
| AC‑F3 | Parity score | blind, pre‑registered panel vs. a **pinned** reference LLM → `quality_ratio`; covenant axis measured on QB (100% cited, 0 fabricated, deterministic N≥3) | run the harness; report both axes | **G3/G6** |
| AC‑F4 | EQUAL / SUPERIOR bar | **EQUAL** ⇔ quality_ratio ≥ 0.95 ∧ perfect covenant; **SUPERIOR** ⇔ quality_ratio ≥ 1.00 ∧ perfect covenant | threshold check | **G3/G6** |
| AC‑F5 | Provider policy | proposer provider‑agnostic but pinned+logged per run (local preferred in prod); comparator a named, version‑pinned LLM recorded per run | run manifest names both | **G3** |

*AC‑F1…F5 are the ratify‑at‑Gate‑2 defaults from spec §8.1; adjust the 0.95 bar, the task mix, or the provider policy here if desired.*

## G. UI [spec §9]

| ID | Component | PASS criterion | Measure | Verified by |
|----|-----------|----------------|---------|-------------|
| AC‑G1 | Zero JS errors | `/dashboard /language /chat /console /guide` each load HTTP 200 with **zero** console/page errors against the live server | headless Chromium over each route | **G1‑ui** ✓ (5/5, 0 errors) |
| AC‑G2 | No input clobber | background polling never overwrites a field the user is editing (the `_phSig` guard) | **G3** interaction test | **G3** |

## H. Rust production build [spec §4; plan Gates 4–7]

| ID | Component | PASS criterion | Verified by |
|----|-----------|----------------|-------------|
| AC‑R1 | Fingerprint parity | Rust `fingerprint()` produces byte‑identical SHA‑256 to the Python baseline on a shared vector set | **G5** parity test |
| AC‑R2 | Fact Unit parity | Rust‑serialized Fact Unit matches the baseline's `semantic_fingerprint` and field contract | **G5** |
| AC‑R3 | Covenant in the type system | UNKNOWN/refuse and "LLM cannot assert" are enforced by types, not convention | **G5** review + tests |
| AC‑R4 | RAM/storage budget | ≈120 B/fact all‑in; server ≈ 5 GB fixed + facts×120 B, validated under load | **G6** load test |
| AC‑R5 | Deploy | reproducible Ubuntu SaaS deploy with monitoring, backup/restore, tiered storage | **G7** runbook + live |

---

## Gate 2 exit criteria (approval)
1. Every shipped/roadmap component above has an explicit, measurable pass/fail criterion.
2. Each criterion names its measurement and where it is (or will be) verified.
3. The already‑green criteria (marked ✓) match the Gate 1 evidence.
4. The creativity‑loop defaults (AC‑F*) are ratified or adjusted.
5. No component advances at Gate 3+ without a criterion here to meet.
