# QueryBook — Language & Speech Technology Specification

**Technical specification · v1.0 · 2026-10-01**

Authoritative description of the technology QueryBook uses to **learn, ground, translate,
pronounce and speak** human language. It documents the engine as built in the prototype
reference implementation and refined through the v9.x line. Third-party dependencies are
described **generically, by the role they fill** — each is an *open-source component* behind
a stable internal interface, never a hard-wired product — so the specification stays true as
individual components are substituted for a commercial deployment. Where a capability is not
yet built, it is labelled **[ROADMAP]**.

This subsystem is **integral to QueryBook**, not a separate system: the Language Expression
Layer (LEL) is a QueryBook subsystem, co-grounded with the Fact Unit / FQL / UFCS core, and it
is consolidated as such across the canon (Canonical Engine Spec §1, §6, §13; the Bible
consolidation amendment of 2026-10-01; the Registry consolidation revision; and the single
QueryBook-first Provisional Patent Application in which the LEL is an integral, co-grounded
subsystem).

This document is scoped to the language/speech subsystem. The whole-engine contract (Fact
Unit, store, gate, API surface) lives in *QueryBook-Canonical-Engine-Specification*; this
specification references it where the language subsystem builds on it and does not restate it.

---

## 1. Purpose & scope

QueryBook learns and produces language **deterministically, from auditable sources, without a
large language model (LLM) in the truth path**. The language subsystem delivers five
capabilities as one integrated pipeline:

1. **Structural acquisition** — learn a language's sound-and-shape structure from raw text.
2. **Semantic grounding** — attach auditable meaning to vocabulary.
3. **Translation** — map between languages word-by-word from auditable bilingual data, with a
   coverage figure and no guessing.
4. **Pronunciation** — derive a phonetic transcription (IPA), syllable count and stress for any
   word in any supported language.
5. **Speech** — produce real, language-correct audio, offline, on commodity Windows and macOS
   machines, or state honestly that it cannot.

Every output is a **Fact Unit** (§4) or a **deterministic rendering of Fact Units**, carrying
its source and trust. The subsystem never invents a meaning, a translation or a pronunciation
it cannot source.

## 2. Covenant — the invariants this subsystem must hold

These restate, for the language subsystem, the engine-wide covenant (C1–C6). They are not
goals; they are constraints verified at every gate.

| # | Invariant | How the language subsystem honors it |
|---|-----------|--------------------------------------|
| L1 | **No LLM grounds meaning or asserts a fact.** | A hard lockout flag drops any LLM-backed grounding suggestor before Phase 2 runs; meaning comes only from a bundled dictionary and the verified store. |
| L2 | **Every asserted fact carries a traceable source.** | Each meaning/translation/pronunciation Fact Unit records a source id, human-readable source name, source class and trust score. |
| L3 | **Determinism: identical input → identical output.** | All of structure, grounding, translation and rule-seeded pronunciation are pure functions of normalized input; audio from a given engine for given text is reproducible. |
| L4 | **Unknown → refuse, never invent.** | Unknown words in translation are passed through and flagged; a word with no phonemizer yields a null pronunciation, not a fabricated one; a missing voice returns an honest "cannot speak" message with a remedy. |
| L5 | **Open-source components are pluggable, not load-bearing identities.** | Every external component sits behind an internal role interface (phonemizer, dictionary, bilingual map, voice engine, SQL index, compression). The engine's guarantees do not depend on which implementation fills a role. |
| L6 | **No fabricated audio.** | When no real voice exists for a language, the subsystem refuses rather than emit a synthetic or placeholder clip presented as speech. |

## 3. Open-source component roster (described by role)

QueryBook is **dependency-free in its own code** — the reference implementation adds no package
manager, no database server and no network services of its own. It composes a small set of
open-source components, each addressed only through the role it fills:

| Role (internal interface) | What QueryBook asks of it | Open-source class used in the reference bundle | Substitutable? |
|---|---|---|---|
| **Runtime** | Execute the deterministic engine | A widely-available, standard-library-complete general-purpose runtime | Yes — production target is a compiled systems language **[ROADMAP]** |
| **Embedded SQL index** | Fast fingerprint/triple lookup over the fact store | An embedded, serverless, public-domain SQL engine | Yes |
| **Block compression** | Shrink append-only fact blocks on disk | A ubiquitous open-source lossless compression format | Yes |
| **Monolingual dictionary** | English word → definition, for semantic grounding | A bundled **public-domain** English dictionary dataset | Yes |
| **Bilingual dictionaries** | English ↔ L2 word maps, for translation and the multilingual delta | Bundled open-source bilingual word-vector dictionaries | Yes — see §13 |
| **Phonemizer** | Word → IPA for non-English languages, when present | A bundled **open-source offline grapheme-to-phoneme / speech engine** | Yes — rule tables are the built-in fallback |
| **Voice engine** | Text → audio (WAV) in a named language | The host OS's built-in text-to-speech service, or the bundled open-source speech engine | Yes |

**Why this matters for the product.** The engine's defensible properties — determinism,
provenance, no-LLM grounding, offline operation — are QueryBook's own. The open-source
components are commodities that fill named roles. Any one can be replaced (for licensing,
quality or platform reasons) without touching the engine's contract, because each is reached
only through its interface (L5).

## 4. Substrate: the Fact Unit (summary)

Language outputs are stored as Fact Units, the engine's atomic record. A Fact Unit is a JSON
object with a normalized subject-predicate-object **nucleus**, a polarity, a content-identity
**semantic fingerprint** (SHA-256 over the normalized nucleus + polarity), a **trust score**,
a **sources** list and a UTC ingest time. Two facts with the same normalized meaning share one
fingerprint and are stored once (dedup). The store is append-only compressed blocks plus an
embedded SQL index; identical inputs reproduce an identical store byte-for-byte. The full
contract is in the Canonical Engine Specification.

Every predicate the language subsystem writes is listed in §11.

## 5. Phase 1 — Structural-acoustic acquisition (SLPL)

**Goal.** Learn a language's *structure* — its sounds, shapes and co-occurrence regularities —
from raw text, **with semantics deliberately suppressed**, and decide objectively when that
structure is learned well enough to ground meaning on top of it.

**Model.** A bounded cumulative model is maintained over ingested text:

- **Grapheme inventory** and frequencies.
- **Phoneme inventory**, seeded by a deterministic English grapheme-to-phoneme (G2P) map
  (digraph table + single-letter table; target inventory ≈ 44 English phonemes).
- **Lexicon** with frequencies (capped at 60,000 distinct words).
- **Bigrams / trigrams** (capped at 200,000 each) for co-occurrence.
- **Syllable** statistics and **prosody** counters (sentence length mean/variance, question and
  exclamation rates).
- A **recent-novelty window** (the last ~4,000 trigrams) for saturation.

Caps bound memory: this is a prototype learner, not a corpus warehouse.

**Transition Gate.** Phase 1 completion is a measured, one-way latch over four normalized
metrics against calibrated thresholds (prototype calibration shown):

| Metric | Definition | Threshold | Direction |
|---|---|---|---|
| Phonemic completeness (τ1) | distinct phonemes / 44 | ≥ 0.80 | higher passes |
| Lexical stability (τ2) | top-word overlap between successive ingests | ≥ 0.70 | higher passes |
| Co-occurrence density (τ3) | distinct bigrams / distinct words | ≥ 1.50 | higher passes |
| Pattern saturation (ε) | recent novel-trigram rate | < 0.20 | **lower** passes |

The gate opens only when **all four** hold; once opened it **latches** (Phase 2 becomes
eligible and stays eligible). A single 0–100 "% toward Phase 1 complete" is reported as the
mean of the four normalized fractions, so the UI can show honest progress. All metrics are
pure functions of the ingested text (L3). Output: metric Fact Units in domain `language`.

## 6. Phase 2 — Semantic grounding (deterministic)

**Goal.** Attach auditable meaning to vocabulary, once Phase 1 has latched — **without an LLM**.

**Two deterministic sources, two predicates:**

1. **Dictionary meaning.** For an English headword found in the bundled public-domain
   dictionary, write `english word "<w>" · means · <definition>` at trust **0.9**, sourced to
   the dictionary.
2. **Self-grounding link.** For the same word, search the verified store and link it to
   **real-world knowledge facts** it appears in — `english word "<w>" · grounded_by_fact ·
   <s p o>` at trust ≤ **0.85**, sourced to the store. Language bookkeeping predicates
   (`means`, `grounded_by_fact`, grapheme/phoneme records) are explicitly excluded from
   linking, so grounding attaches to knowledge, not to its own scaffolding.

**Covenant hook (L1).** The grounder exposes an optional `suggestor(word)` parameter for a
*future validated mode* in which a candidate meaning would be accepted **only if it agrees with
the dictionary** (meaningful word-overlap test). While the LLM lockout flag is set — its state
in the shipped engine — any suggestor passed in is dropped before it can run. The hook is
specified and inert; meaning today comes only from the dictionary and the store.

## 7. Phase 3 — Multilingual delta (deterministic translation)

**Goal.** Reuse the English foundation and learn only the **delta** to a second language — the
word-to-word mapping — from bundled open-source bilingual dictionaries. No LLM, no network, no
fabrication.

**Supported languages (reference bundle):** English plus Spanish, French, German, Italian,
Portuguese, Dutch, Swedish — eight speakable languages.

**Language detection.** Given text, tokenize and score it against every bundled dictionary's
word set; report the best match with a confidence percentage and the top ranked alternatives,
so the UI can show its reasoning and the user can override. Deterministic; falls back to
English when nothing matches.

**Translation.** Word-by-word through English (English must be one side of any pair). For each
token: look it up in the direction's bilingual map; if known, render the first option and
expose up to three alternatives; if unknown, **pass it through unchanged and flag it**.
Capitalization of the source word is preserved. The result carries the rendered translation, a
per-word breakdown, and a **coverage percentage** (known words / total words) so the user can
trust exactly what was and was not translated (L4). Every rendered word traces to the
auditable dictionary.

## 8. Pronunciation subsystem (grapheme-to-phoneme)

**Goal.** For any word in any supported language, produce an IPA transcription, a syllable
count and the primary-stress syllable — deterministically, and always available even with no
voice engine installed.

**English.** A built-in rule-seeded G2P (digraph + single-letter tables) with a syllable
counter and a stress heuristic. Pure function, no external component.

**Other languages — a preference ladder (most accurate first):**

1. **Open-source phonemizer, when present.** If the bundled offline phonemizer is available,
   QueryBook calls it for the IPA. Calls are **cached** per (word, language) to avoid
   re-spawning, **logged** to a bounded ring buffer for diagnostics, and **time-bounded** so
   the UI never blocks.
2. **Built-in rule tables (fallback).** A bundled, pure-code rule-seeded G2P table exists for
   each non-English language (ordered longest-match regex rules: digraphs/trigraphs and
   context-sensitive rules before single letters). This guarantees a pronunciation with **no
   install, no engine, offline** — labelled *approximate* and sourced accordingly (lower
   trust, ~0.65).
3. **Null, never fabricated.** A word with no phonemizer and no rule table yields an explicit
   null IPA (L4), not a guess.

**Syllables and stress.** Syllable count is the number of IPA vowel nuclei (a fixed IPA-vowel
set). Rule-fallback stress follows a per-language rule (penultimate for Spanish/Italian/
Portuguese, final for French, initial for German/Dutch/Swedish); phonemizer output carries its
own stress marks, from which the primary-stress syllable is derived.

**Phrase-accurate analysis (refined, v9.47).** For the "analyze and speak" surface, a whole
phrase is transcribed in **one** phonemizer call rather than word-by-word. This is both faster
(one process, not one per word) and, critically, makes the **displayed IPA identical to what
the voice engine actually speaks** — eliminating the earlier mismatch where the panel showed a
rule-fallback transcription while the audio came from the phonemizer. English and the
no-phonemizer case keep the instant rule path.

## 9. Speech output subsystem (text-to-speech)

**Goal.** Produce real, language-correct WAV audio offline, on commodity machines, or refuse
honestly.

**Engine-selection ladder** (the engine chosen is reported with every clip):

1. **Non-English + bundled open-source speech engine present → use it.** The reliable
   multilingual path on every OS. Language-voice selected explicitly; time-bounded; logged.
2. **Non-English on macOS → the OS built-in voice service.** Always present; a matching
   language voice is selected when installed, otherwise the default voice speaks (with a note
   on how to add the language voice). Output is converted to WAV.
3. **Non-English on Windows → a matching OS voice (culture-matched) if one is installed.** If
   none exists, QueryBook **refuses and tells the user how to get a real voice in one click**
   (L6) — it does **not** emit fabricated audio.
4. **English → the OS built-in voice service** (or the bundled engine), always available.

**No fabricated audio (L6).** An earlier prototype included a pure-code formant synthesizer as
a last resort. It was **removed** from the playback path: it produced robotic, and at times
corrupt, output and was far too slow for sentence-length input. The engine now prefers a real
bundled open-source voice engine and, failing that, refuses with a remedy. Pronunciation (IPA)
remains available in every case, with or without a voice.

**Self-containment (refined through v9.4x).** So that the app "assumes nothing" about a user's
machine, the reference bundle ships the open-source speech engine **inside the application** —
the engine binary, its runtime support libraries and its phoneme data — so Windows and macOS
users with none of the usual tools installed still get real audio in every supported language
with no install, no account and no cloud. A one-click installer remains only as a fallback.

## 10. Quality-control subsystem (permanent)

QC is **deterministic, local and LLM-free** — safe to run at any time, at no API cost. It is a
standing gate on the voice subsystem, not a one-off test.

**Pronunciation & speech QC battery (refined, v9.47).** For each language, a fixed set of known
words with expected syllable counts is checked three ways: (a) an IPA transcription is
produced; (b) the syllable count is sane (within ±1 of expected); and (c) a short phrase
actually **synthesizes to a valid WAV** (RIFF header, non-trivial length, decodable duration).
It returns a per-language report plus an overall pass score and an `all_ok` flag, exposed on a
read-only status endpoint and a one-click "Pronunciation QC (all languages)" control. Reference
run: Spanish/French/German scored **13/13 (100%)** with real ~1-second clips per language.

**Supporting controls (engine-wide, applied to language output):**

- **Text hygiene.** Every developed line is normalized deterministically — Unicode
  normalization (degrading gracefully when the normalizer extension is absent), invisible-
  character stripping, exotic spaces folded to ordinary spaces, consistent line endings,
  collapsed runs. Deterministic by contract.
- **Engine self-test.** A phonemizer self-test (a known word → expected IPA, with a timing)
  and a runtime-dependency presence check are exposed on a status endpoint, so the voice
  stack's health is inspectable at any point.
- **Rhythm & revision controls** for developed prose (sentence/paragraph variation, rotating
  cadence, structural revision pass) — deterministic, local, no API cost.

## 11. Determinism & provenance — predicate and source ledger

Every language Fact Unit records where it came from and how much to trust it:

| Predicate | Written by | Source class (generic) | Trust |
|---|---|---|---|
| structural metrics (phoneme/grapheme/bigram counts, gate values) | Phase 1 | internal-derived (deterministic learner) | 0.85 |
| `means` | Phase 2 | bundled public-domain dictionary | 0.90 |
| `grounded_by_fact` | Phase 2 | verified store (self-grounding) | ≤ 0.85 |
| `translation_<lang>` | Phase 3 | bundled open-source bilingual dictionary | per dictionary |
| `pronunciation` (English) | Phase 4a | rule-seeded G2P | 0.70 |
| `pronunciation` (other, phonemizer) | Phase 4a | open-source phonemizer | per source |
| `pronunciation` (other, rules) | Phase 4a | rule-seeded G2P (approximate) | 0.65 |
| `syllable_count`, `stress_syllable` | Phase 4a | same as the pronunciation it accompanies | 0.70 |

Audio (Phase 4b) is produced **on demand** and not stored as a fact; the clip reports the
engine that produced it. Unknown/unsupported cases produce **no** fact rather than a
fabricated one.

## 12. Packaging & portability

- **Offline and self-contained.** No internet, account or API key is required for any language
  capability. The engine, the dictionaries and the bundled voice engine ship with the app.
- **Cross-platform.** Windows (OS voice service, or the bundled engine), macOS (OS voice
  service), and the bundled open-source engine as the universal fallback.
- **Deterministic packaging.** The bundle is reproducible; a housekeeping self-test enforces
  that every application file is registered, so a published package cannot silently omit a
  component.

## 13. Licensing posture for commercial / SaaS deployment

The architecture is built so licensing is a **substitution**, not a rewrite (L5). Two notes
govern a move from prototype to commercial product:

- **Copyleft voice engine.** The bundled open-source speech engine in the reference bundle is
  distributed under a **strong copyleft** license. For commercial/SaaS distribution, either
  invoke it as a separately-installed program across a process boundary, or substitute a
  permissively-licensed or self-owned voice engine behind the same voice-engine interface.
- **Non-commercial bilingual data.** The bundled bilingual dictionaries are **demo data under a
  non-commercial license**. Before commercial use, substitute permissively-licensed or
  self-owned bilingual data behind the same bilingual-map interface. The monolingual
  dictionary is public-domain and carries no such restriction.

Because each component is reached only through its role interface, these substitutions change
the bundle, not the engine's contract or behavior.

## 14. Roadmap embodiments [ROADMAP]

The deterministic subsystem specified above is the shipped, defensible baseline. The preferred
long-term embodiments extend it without weakening the covenant:

- **Neural Language-Embedding Learner (LEL)** and **neural vocoder** — a trained-parameter
  model for cross-lingual alignment and natural multi-stage speech, replacing the approximate
  rule fallback while preserving provenance and determinism of the *decision* path.
- **Production runtime** — the engine re-implemented in a compiled systems language for the
  production (SaaS) tier, verified in lockstep against the reference implementation.
- **Broader language coverage** — additional languages added purely by supplying their
  role-interface data (dictionary, bilingual map, phonemizer/rule table), with no engine change.

## 15. Component-role summary

| QueryBook capability | Owned by QueryBook (defensible) | Filled by an open-source component (commodity, pluggable) |
|---|---|---|
| Structural acquisition & transition gate | Learner, metrics, one-way latch | Runtime |
| Semantic grounding | Deterministic grounder, covenant lockout, store self-grounding | Monolingual dictionary, SQL index |
| Translation & detection | Word-by-word translator, coverage accounting, detector | Bilingual dictionaries |
| Pronunciation | Rule-seeded G2P tables, syllable/stress derivation, preference ladder | Phonemizer (optional) |
| Speech | Engine-selection ladder, honest refusal, no-fabrication rule | Voice engine (OS or bundled) |
| Quality control | QC battery, hygiene, self-test, provenance ledger | Runtime |
| Persistence & determinism | Fact Unit, fingerprint, dedup, reproducible store | SQL index, compression |

---

*QueryBook's defensible technology is the deterministic, provenance-tracked, LLM-free language
engine described here. The open-source components it composes are commodities, each addressed
by role and replaceable without altering the engine's guarantees.*
