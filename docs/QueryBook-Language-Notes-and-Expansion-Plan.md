# QueryBook — Language & Speech: Notes, Observations, and Expansion Plan

**2026-09-30**
How the prototype learned to read, ground, translate, and speak — **with no LLM** —
in well under an hour (English + Spanish), the bugs we hit and fixed along the way,
and the plan for the next six languages, five of which now have speech and await only
a licensed translation lexicon.

---

## Part 1 — The path we took (no LLMs)

The design decision that made everything else follow: **an LLM can prove a connection
works, never that a returned meaning is true**, so an LLM can never satisfy the
provenance mandate. We locked it out of language understanding (`LLM_LOCKOUT = True`)
and built each phase from auditable, deterministic sources.

**Phase 1 — structural (SLPL).** Learn the *shape* of English with semantics switched
off: grapheme inventory, rule-seeded grapheme-to-phoneme, syllables, lexical stability,
co-occurrence density, prosody proxies. Four Transition-Gate thresholds (phonemic
completeness, lexical stability, co-occurrence density, pattern saturation) latch
one-way when all are met. A background agent ingests a bundled public-domain starter
corpus (pangrams for letter coverage, nursery rhymes, common-word sentences). Every
measurement is a provenance-tracked Fact Unit in the `language` domain.

**Phase 2 — semantic grounding.** Meaning is attached only from sources we can point
at: a bundled **public-domain dictionary (Webster's 1913, ~5,052 words)** writing
`english word "w" · means · <definition>`, and **self-grounding** against verified Fact
Units the word already appears in (`grounded_by_fact`). Deterministic, no internet, no
model. A future "suggestor" may only propose a meaning that is accepted where it agrees
with the dictionary, which stays the authority.

**Phase 3 — multilingual delta.** The Delta Acquisition Model, approximated
deterministically: reuse the English foundation and learn only the *delta* — the
word-to-word mapping — from a bundled bilingual dictionary, stored as
`english word "w" · translation_<lang> · <term>`. Spanish and French shipped as the
first targets.

**Phase 4 — speech.** Two honest parts. **4a** deterministic pronunciation analysis
(phonemes, syllables, heuristic stress, punctuation prosody) → `pronunciation`,
`syllable_count`, `stress_syllable` facts. **4b** real audio via the computer's built-in
voice (Windows SAPI, macOS `say`, Linux espeak-ng). If no voice engine is present it
says so and never fabricates audio.

### Why it was so fast (the honest reason)
There are **no model weights to train**. Every phase is deterministic table-building,
dictionary lookup, and rule application:
- Phase 1 needs only enough corpus to satisfy four thresholds (hundreds of facts, a few
  hundred cycles).
- Phase 2 is dictionary lookups over the learned vocabulary.
- Phase 3 is delta lookups against a bilingual list.
- Phase 4a is per-word grapheme-to-phoneme conversion.

That is seconds-to-minutes of ordinary CPU work, not GPU-hours of gradient descent — so
English + Spanish reaching "learned and speaking" in under ~30 minutes is expected, not
surprising. The same determinism is why it reproduces exactly and why it can't
hallucinate: identical inputs always yield identical Fact Units.

## Part 2 — Bugs faced and fixed

| # | Symptom | Root cause | Fix |
|---|---------|-----------|-----|
| 1 | Phase-4 self-test flaky; `FileNotFoundError` in `ufcs_store.flush()` | 24×7 continuous mode flushed unbounded and `getsize` hit a block file mid-rotation | `getsize` wrapped in try/except; bounded continuous-mode flush increments; a `stopped` flag skips post-verify. Now part of the frozen baseline; self-test stable. |
| 2 | 24×7 harvest wouldn't stop promptly | stop request only checked between large flushes | cooperative stop token honored on the bounded flush boundary |
| 3 | Dead GitHub download links | a "/" in the branch name breaks the `/raw/` URL path | use the `refs/heads/<branch>` raw URL form |
| 4 | "Language Lab link is dead" | a **stale server** on port 8090 kept serving an old page | launchers now kill any process on 8090 before starting, and print the direct `/language` URL |
| 5 | Webster's cited as "1937" | typo in an edit | corrected to 1913 (public domain) |
| 6 | Gate wrongly flagged `is_a`/`part_of` with several values as a contradiction | contradiction check didn't distinguish functional from multi-valued predicates | added the `MULTI_VALUED` set; only functional predicates flag contradictions |
| 7 | "Phase 4 is stalled / 0 facts" | the running install was **v9.14**, which predates Phase 4, so `lang_speech` correctly refused as roadmap | ship v9.15 (Phase 4 built); verified the agent writes 59 pronunciation facts when driven exactly as the Start button does |
| 8 | Phase-4 agent could appear stuck at the start | it blocks if Phase 1 has produced no vocabulary yet | it now reports "build English first, then Phase 4 analyzes pronunciation" rather than spinning |

Standing (not a bug): the bundled bilingual data is a **CC BY-NC demonstration set** to be
replaced with a permissively-licensed source before commercial use.

## Part 3 — Adding the next six languages

**Two independent capabilities per language:** *speech* (pronounce + voice) and
*translation* (the Phase-3 delta). They have different requirements, which is why the
plan treats them separately.

### Status now (shipped in v9.16)
Speech — pronunciation analysis + real audio — is **implemented and verified** for all
of the requested languages via the OS phonemizer `espeak-ng --ipa` (deterministic;
identical across runs; sourced to espeak-ng, a fixed auditable tool, never an LLM):

| Language | Speech (v9.16) | Sample IPA | Translation (Phase 3) |
|----------|----------------|-----------|-----------------------|
| French — Romance | ✅ built | maison → /mɛzˈɔ̃/ | ✅ **works now** (bundled lexicon) |
| German — Germanic | ✅ built | Haus → /hˈaʊs/ | ⏳ needs a licensed en↔de lexicon |
| Portuguese — Romance | ✅ built | casa → /kˈazɐ/ | ⏳ needs a licensed en↔pt lexicon |
| Italian — Romance | ✅ built | casa → /kˈaza/ | ⏳ needs a licensed en↔it lexicon |
| Swedish — Germanic (North) | ✅ built | hus → /hˈʉs/ | ⏳ needs a licensed en↔sv lexicon |
| Dutch — Germanic (West) | ✅ built | huis → /hˈœys/ | ⏳ needs a licensed en↔nl lexicon |

(Spanish already had both; French translation was already bundled.)

### Why translation isn't just "typed in"
Adding translation facts means writing `english word "w" · translation_<lang> · <term>`
into the store. **Every asserted fact must carry an auditable source (covenant C2).** If
the model typed the translations, the model would be the source — the exact thing the
engine forbids. So the five new languages **register and then refuse** ("no bilingual
data for 'de'") until their lexicon is present, rather than fabricate. This refusal is
the covenant working, not a gap in the code: the moment a licensed `en↔X` file is added,
that language's translation activates unchanged.

### Work plan per language (translation)
1. **Source a license-clean en↔X bilingual lexicon.** Candidates to evaluate (verify the
   exact licence before bundling): FreeDict (`eng-deu`, `eng-por`, `eng-ita`, `eng-swe`,
   `eng-nld`); Wiktionary-derived sets such as Wiktextract/Kaikki (attribution terms);
   or a public-domain bilingual dictionary. Replace the CC BY-NC demo set at the same time.
2. **Bundle it** into `qb_bilingual.json.gz` under the language key, with a source +
   licence note recorded (the data carries its own provenance).
3. **No code change** — `acquire_language(store, "<lang>")` is data-driven and already
   registered; it will write translation Fact Units on the next run.
4. **Validate**: `available_languages()` includes the language; a fixed word list produces
   the same translation facts on repeat runs (determinism); each fact cites the lexicon.

### Suggested order
1. **French** — already complete (speech + translation); expand coverage + relicense.
2. **German, Dutch, Swedish** (Germanic) — closest to the English foundation, so the delta
   is smallest and transfer is cleanest.
3. **Portuguese, Italian** (Romance) — mirror the Spanish path already proven.

### Acceptance criteria (per language, Gate-2 style)
- **Speech:** `analyze_pronunciation(word, lang)` returns deterministic IPA; `speech_analyze`
  writes `pronunciation`/`syllable_count`/`stress_syllable` facts sourced to espeak-ng;
  audio renders via the language voice or reports unavailable (never fabricated). *(Met in v9.16.)*
- **Translation:** with the lexicon bundled, `acquire_language` writes `translation_<lang>`
  facts deterministically, each citing the lexicon; without it, the engine refuses cleanly.

### Effort estimate
- Speech: **done** (v9.16).
- Translation per language: roughly **half a day to a day** each, almost all of it sourcing
  and licence-clearing the lexicon; the engine work is zero.

## Part 4 — How to try the multilingual speech now (v9.16)
Run the v9.16 build, open the **Language Lab**, and in the Phase-4 "Analyze & Speak"
control pick a language from the new selector, type a word (e.g. German "Haus"), and
press the button: you'll get the IPA, syllable and stress analysis, and — if a voice
engine is installed — audio in that language's voice. On Linux install `espeak-ng`;
Windows and macOS have a built-in voice.
