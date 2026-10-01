# QueryBook Translate — Product & Engineering Specification

**Spinoff product specification · v1.0 · 2026-10-01 · working name "QueryBook Translate"**

A smartphone/tablet **universal speech translator** — the kind of experience sold as a
dedicated handheld device, delivered as an app — built on QueryBook's deterministic,
provenance-tracked language technology (the Language Expression Layer, LEL, and its
subsystems). This document is engineering-ready: it can be handed to mobile, ML, backend,
UX, and QA teams. Third-party dependencies are named only **by role, as substitutable
open-source components**, consistent with the QueryBook canon.

> **Relationship to QueryBook.** This is a spinoff *product* built on QueryBook's language
> subsystem; it is not a new engine. It inherits QueryBook's covenant unchanged and reuses the
> engine's deterministic language functions. See *QueryBook — Language & Speech Technology
> Specification* (the subsystem detail) and the *Canonical Engine Specification* (the
> whole-engine contract). Where this product needs a capability QueryBook does not yet own
> deterministically — principally **acoustic speech recognition** — that boundary is stated
> plainly in §2 rather than papered over.

---

## 0. Hard constraint — offline-first, cloud strictly optional

> **The device MUST operate with no Internet connection. A cloud connection is optional and may
> be absent permanently.** Every core function — speech-to-text, language/dialect detection,
> translation (with coverage), pronunciation, and spoken output — runs **entirely on the device**
> for any **installed** language pack. The app is fully usable in airplane mode, in another
> country with no data plan, and on a device that has never been online after setup.
>
> Cloud is never on the critical path. It does exactly two things, both optional and both
> requiring the user to be online *and* to opt in: (a) **deliver language packs** (one-time
> download, after which that language works forever offline), and (b) offer **optional
> enhancement** — higher-fluency MT or higher-fidelity voices — when available. If the network is
> absent, slow, or declined, the app silently uses the on-device path and says so; it never
> blocks, errors, or degrades to "no translation" for an installed language.
>
> This is natural for QueryBook: the engine is already **dependency-free and deterministic** —
> no server, no account, no API key — so offline is the default state, not a fallback mode.

## 1. Product vision & positioning

**One line.** Point your phone at a conversation, speak, and hear it back in another language —
**fully offline**, in any language or script — from a translator that **never makes up words**.

**The category.** "Trendy TV" pocket translators (and the big-tech translate apps) are neural,
end-to-end, and cloud-tethered. They are fluent and they are confident — including when they
are **wrong**, because a probabilistic model will always emit *something*. For a traveler in a
hospital, a border, or a contract conversation, a confident wrong translation is the dangerous
failure mode.

**The QueryBook difference (the moat).** QueryBook Translate is built on a deterministic,
provenance-tracked core that:

- **Never fabricates a translation.** Every rendered word comes from an auditable source; a
  word it does not know is **passed through and flagged**, never invented (QueryBook covenant
  C4/L4).
- **Shows its work.** Every translation carries a **coverage %** (how much was translated from
  a known source) and per-word provenance. The user always knows what is trustworthy.
- **Is reproducible.** The same input yields the same output — a property no end-to-end neural
  translator can guarantee.
- **Is tiny and fast.** The deterministic core is rules + dictionaries, not multi-gigabyte
  neural weights, so it fits the "minimum RAM / minimal storage" bar by construction (§8).
- **Works offline and speaks with a real voice** via the self-contained open-source speech
  engine QueryBook already bundles.

Positioning statement: *the honest universal translator — as fast and pocketable as the
gadgets, but the only one that tells you when it isn't sure instead of guessing.*

## 2. What QueryBook provides, and the one honest boundary

A speech translator is a pipeline of five stages. QueryBook's deterministic engine owns four of
them; the fifth — turning **audio into text** — is acoustic recognition, which is inherently
statistical and which QueryBook does not today implement. The design is explicit about this so
the covenant is never overstated.

| Stage | Who provides it | Deterministic & auditable? |
|---|---|---|
| **1. Audio → text (ASR)** | On-device **open-source ASR** (acoustic front-end), tiered; optional cloud ASR only as an online *enhancement*, never a requirement | **No** — acoustic recognition is probabilistic by nature. Treated as *untrusted input*: the user sees the live transcript and can correct it before it is trusted. |
| **2. Text normalization + language ID** | **QueryBook** (deterministic hygiene + dictionary-scored LID) | **Yes** |
| **3. Text → translation** | **QueryBook** deterministic dictionary/delta MT (on-device); optional QueryBook cloud MT for fluency | **Yes** — coverage-reported, no-guess, provenance-tracked |
| **4. Pronunciation (IPA, syllables, stress)** | **QueryBook** rule-seeded G2P + open-source phonemizer ladder | **Yes** |
| **5. Text → speech (TTS)** | **QueryBook** engine-selection ladder (bundled open-source engine / OS voice); honest refusal, no fabricated audio | **Yes** (rendering is acoustic, but the decision path and refusal are deterministic) |

**Honesty principle.** The acoustic edge (stages 1 and the waveform of 5) is probabilistic
because physics and speech make it so; *any* translator shares that. Everything QueryBook adds —
from text onward — is deterministic, sourced, and refuses rather than invents. The product's
promise is scoped precisely to that: **"we never fabricate a translation,"** not "we never
mis-hear." The UI reflects this by always showing the recognized text for confirmation and by
marking low-confidence ASR spans.

## 3. Product behavior & modes

**Core loop.** Tap mic → speak Language A → live transcript appears (ASR) → QueryBook detects
language/dialect, normalizes, translates → target text shown in native script with coverage →
spoken aloud in Language B. Round-trip target: sub-second for on-device Tier-1 pairs (§13).

**Modes.**
- **Conversation** — two-way, turn-taking A ↔ B; auto-detects which language was just spoken.
- **One-way** — traveler speaks one language, output pinned to another.
- **Text** — type/paste → translation + pronunciation + optional transliteration.
- **Phrasebook** — save translations for fully offline recall and playback; categorized.
- **Camera / OCR (roadmap)** — point at a sign/menu; OCR → same deterministic text pipeline.

**UX essentials.**
- One primary screen, one big mic button, two language chips (source may be **Auto**).
- **Latency-first**: show partial transcript as the user speaks; stabilize on pause.
- **The trust layer (unique to this product):** a coverage meter (e.g., "96% translated from
  dictionary"), per-word underlines for **untranslated/flagged** words, and a tap-to-see-source
  provenance panel. A clear **offline / cloud-enhanced** indicator.
- Low-friction: no deep menus; dialect and cloud are overridable but sensible by default.

## 4. Universal coverage — auto-sensing, dialects, every script

The product must support **all languages, character sets, and dialects**. Concretely:

**4.1 Auto source-language sensing.** Default source = **Auto**. Two complementary detectors:
- **Acoustic LID** (open-source, on-device, ~1–2 s window) picks the ASR model while the user
  is still speaking.
- **QueryBook text LID** (deterministic): once text exists, it is scored against every
  installed dictionary and returns a ranked best guess **with a confidence value** — the same
  `detect_language` logic QueryBook already ships. If confidence is low, the app asks the user
  to confirm rather than guessing silently (covenant-consistent).

**4.2 Dialects.** A language → dialect hierarchy (e.g., Arabic: MSA, Egyptian, Gulf, Levantine;
English: US/UK/IN/AU/NG; Spanish: ES/MX/CO/AR). After LID, a dialect profile is selected from
acoustic features, lexical choice, and orthography. ASR uses dialect acoustic/lexical models
where available; QueryBook applies **dialect-aware normalization** (colloquial → standard form)
before deterministic translation. Auto by default, manual override for precision.

**4.3 Every script and character set.** Full Unicode, not Latin-only:
- **Rendering**: OS-level Unicode with correct shaping (Arabic joining, Indic conjuncts),
  **RTL/LTR** bidi, and font fallback for rare scripts. Scripts explicitly in scope: Latin,
  Cyrillic, Greek, Arabic (Arabic/Persian/Urdu), Hebrew, Devanagari and other Indic (Bengali,
  Tamil, Telugu, …), CJK (Chinese/Japanese/Korean), Thai/Lao/Khmer/Burmese, Ethiopic, and more.
- **Normalization** (QueryBook hygiene, deterministic): NFC, diacritic and half/full-width
  folding, invisible-character stripping, **mixed-script** handling (e.g., Arabic + Latin),
  preserved numbers and named entities across scripts.
- **Output**: native script always; **optional transliteration** (e.g., Arabic → Latin) for
  users who cannot read the script; TTS where a voice exists, honest refusal otherwise.

## 5. Architecture (diagram-ready)

```
 ┌──────────────────────────────── MOBILE CLIENT (iOS / Android / tablet) ───────────────────────────────┐
 │  UI LAYER                                                                                              │
 │    Conversation · One-way · Text · Phrasebook · Settings(packs) · System Monitor(dev)                  │
 │    Trust layer: coverage meter · flagged-word underlines · provenance panel · offline/cloud badge      │
 │                                                                                                        │
 │  AUDIO & VOICE                         ON-DEVICE DETERMINISTIC CORE (QueryBook LEL)                     │
 │    Audio capture (OS APIs) ─┐          ┌─ Text normalization / hygiene (deterministic)                 │
 │    TTS playback (OS out)  ──┘          │  Language ID (dictionary-scored) + Dialect profile            │
 │                                        │  Deterministic MT: dictionary/delta, coverage %, no-guess     │
 │  ACOUSTIC FRONT-END (open-source)      │  Pronunciation: rule-seeded G2P + phonemizer ladder           │
 │    Acoustic LID ─► Streaming ASR ──────┤  Speech-out: engine-selection ladder, no fabricated audio     │
 │    (probabilistic; shown for confirm)  └─ Permanent QC battery (deterministic self-check)              │
 │                                                                                                        │
 │  LANGUAGE PACK MANAGER   (download / load / unload / storage accounting; dynamic, lazy)                │
 └───────────────────────────────┬────────────────────────────────────────────────────────────────────┘
                                  │  HTTPS (encrypted) — used only when online AND permitted
 ┌────────────────────────────────▼─────────────── QUERYBOOK CLOUD (optional) ──────────────────────────┐
 │  API gateway (auth, rate-limit, routing)                                                               │
 │  QueryBook cloud MT (full engine / neural roadmap) · cloud ASR · cloud TTS · LID/dialect service       │
 │  Model-selection & routing (local vs cloud, by device, pair, bandwidth, user preference)               │
 │  Telemetry & optimization (anonymized; opt-in)                                                         │
 │  Every cloud response carries provenance + coverage, so the trust layer works online too.              │
 └────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Client is the default and is complete offline for Tier-1 (§7). Cloud is an *enhancement*, never
a silent dependency; the app always states when a result came from the cloud.

## 6. The deterministic pipeline (QueryBook integration)

Each stage names the QueryBook function it maps to, so the integration is concrete.

1. **Capture** audio frames (OS APIs); stream to the acoustic front-end.
2. **Acoustic LID** → choose ASR model; **streaming ASR** → partial then stabilized text. This
   text is **untrusted input**, shown for confirmation.
3. **Normalize** (QueryBook deterministic hygiene): NFC, spacing, invisible chars, script
   folding, mixed-script, numbers/entities preserved.
4. **Language/dialect ID** (QueryBook `detect_language`, dictionary-scored, ranked + confidence);
   confirm with user if low confidence.
5. **Translate** (QueryBook deterministic MT): word-by-word through the pivot from bundled
   bilingual dictionaries; known words rendered (with alternatives), **unknown words passed
   through and flagged**, **coverage %** reported. No guessing, no LLM. For long/complex
   sentences the router may call **QueryBook cloud MT** (fuller, fluency-oriented) — still
   returned with provenance and coverage, and only when online and permitted.
6. **Pronounce** (QueryBook): phrase-level single-call transcription so the displayed IPA
   matches the spoken audio; syllables and stress derived deterministically.
7. **Speak** (QueryBook engine-selection ladder): bundled open-source engine for non-English, OS
   built-in voice where it carries the language, culture-matched OS voice on the platform that
   has one; **honest refusal with a remedy** when no real voice exists — **never fabricated
   audio**.
8. **Self-check** (QueryBook permanent QC battery): per language, confirm IPA is produced,
   syllable counts are sane, and a phrase synthesizes to a valid waveform; surfaced in the
   System Monitor.

## 7. Language & dialect tiers

Tiering is about **on-device footprint and quality**, not about whether a language needs the
cloud. **Every installed pack translates fully offline** (per §0); the tiers differ only in how
large/accurate the on-device pack is and whether an *optional* cloud enhancement exists. Cloud is
used to **download** a pack once; after that the language works offline forever.

**Tier 1 — flagship on-device (offline; no enhancement needed).** Local deterministic MT +
pronunciation + voice + a local ASR front-end, at full quality. High-usage, travel/business-
relevant, mature acoustic data.
- English (US/UK/IN/AU/NG), Spanish (ES/MX/CO/AR), French (FR/CA/West-Africa), German, Italian,
  Portuguese (PT/BR), Mandarin (CN/TW), Japanese, Korean, Arabic (MSA/Egyptian/Gulf/Levantine),
  Hindi, Russian.
- Pack budget: **8–40 MB** per language (QueryBook MT is dictionaries + rule tables, far smaller
  than neural MT; the ASR acoustic model dominates the pack). Dialect adapters 1–6 MB.

**Tier 2 — standard on-device (offline; optional cloud enhancement).** Full offline path — local
deterministic MT, pronunciation, a local voice, and an on-device ASR model — at good quality;
when online and permitted, an *optional* cloud call can raise ASR/MT/voice fidelity. Nothing here
requires the cloud to function.
- Turkish, Dutch, Polish, Thai, Vietnamese, Indonesian, Malay, Persian, Urdu, Bengali, Swahili,
  Hebrew. Pack budget: **5–20 MB**.

**Tier 3 — compact on-device (offline; download-on-demand; graceful degradation).** Low-resource,
sparse acoustic/text data. The pack is still **downloaded once and then fully offline**, but is
smaller and more approximate: deterministic dictionary MT with coverage always works; where a
Tier-3 language has no on-device acoustic model yet, **text mode** and **pronunciation** work
offline and speech-in/out degrade gracefully with a clear notice — the app never silently fails
and never requires a live connection to translate an installed language.
- Amharic, Yoruba, Zulu, Hausa, Burmese, Khmer, Lao, Nepali, Pashto, Somali, Indigenous
  languages (Quechua, Navajo, Māori, …). On-device footprint: **2–8 MB** installed (dictionary MT
  + LID + G2P; acoustic/voice added when available).

Promotion between tiers is data-driven (telemetry, when the user has opted into it) and
reversible. **A device with no network still translates every pack the user has installed**, in
any tier.

## 8. RAM & storage — why QueryBook meets "minimum by construction"

The user's hard constraint is *minimum RAM, minimal storage, still powerful/accurate/fast*.
QueryBook's deterministic core is a **structural advantage** here, not a tuning exercise:

- **The translation + pronunciation core is rules + dictionaries, not neural weights.** A
  bilingual dictionary and a per-language G2P rule table are **kilobytes to a few megabytes**;
  there is no multi-hundred-MB MT model to hold in RAM. This is the single biggest reason the
  app can be tiny where neural translators cannot.
- **Base app < 120 MB**; idle RAM < 150 MB; active translation < 350 MB (dominated by the ASR
  acoustic model, which is the only large component and is streamed).
- **Dynamic load / unload**: load only the current pair's assets; release on language switch or
  idle (QueryBook functions are stateless per call, so unloading is safe).
- **Streaming inference**: process audio in small chunks; never buffer whole utterances unless
  required.
- **Shared assets**: shared pivot dictionaries and shared G2P sub-tables across related
  languages (e.g., Romance) reduce footprint further.
- **Deterministic = cacheable**: identical inputs reuse cached results (QueryBook already
  memoizes phonemizer calls), cutting both latency and compute.

## 9. Asset & model compression plan

The compressible assets differ from a neural-only app because QueryBook's core is symbolic.

- **Bilingual dictionaries & LID word sets** → store as a compressed **FST / double-array trie**
  (shared prefixes, minimal perfect hashing); Brotli/zstd on disk, memory-mapped at run time so
  they are not fully resident in RAM.
- **G2P rule tables** → already tiny; ship as compact rule lists; share sub-tables across
  related languages.
- **ASR acoustic models** (the one heavy asset) → distilled from a larger teacher, **8-bit (or
  4-bit where hardware allows) quantized**, attention heads/layers pruned to a WER budget;
  streaming/conformer-style for low latency. Tier-1 target 10–25 MB.
- **Voices / phoneme data** → the bundled open-source speech engine's compact voice + phoneme
  data; cloud voices optional for higher fidelity.
- **Packaging** → one pack = {ASR model, dictionary/MT, LID, G2P table, dialect adapters, voice,
  normalization rules}; Brotli-compressed; **delta-patch** updates; lazy-download dialect
  adapters and voices.

## 10. The covenant & trust layer (the product's defensible core)

QueryBook Translate inherits the QueryBook covenant unchanged, surfaced as user-visible trust:

- **No fabricated translation.** Unknown words are flagged and passed through, never invented.
- **Coverage is always shown.** The user sees how much of the utterance was translated from a
  known source; low coverage is a visible warning, not a hidden risk.
- **Provenance on tap.** Each rendered word can show its source (dictionary entry / cloud
  engine). 
- **Deterministic & reproducible.** Same input → same output; a demonstrable property for
  high-stakes use (medical, legal, border).
- **No fabricated audio.** If no real voice exists for a language, the app says so and still
  shows the (correct) pronunciation, rather than emitting a fake voice.
- **The acoustic edge is labeled, not hidden.** Recognized text is always shown for confirmation;
  low-confidence ASR spans are marked. The promise is "we never make up a translation," stated
  exactly.
- **Privacy by default.** On-device path requires no network; audio and text are **not stored**
  unless the user opts in; cloud calls are encrypted and opt-in; telemetry is anonymized.
  GDPR/CCPA aligned.

## 11. QueryBook cloud services & integration spec (optional)

**Cloud is strictly optional (per §0).** The app is a complete offline product without any of
the services below; they add (a) pack delivery and (b) optional online enhancement, and every
cloud response carries the same provenance + coverage so the trust layer behaves identically
online or off. The client is built **network-absent by default** — it starts, runs, and
translates every installed pack with the radios off — and only reaches for these endpoints when
the user is online, has opted in, and a result would benefit. Endpoints (client calls the
gateway, which routes):

- `POST /model-selection` — in: device profile, language pair, bandwidth, offline/online,
  user preference → out: per-stage local-vs-cloud plan + model IDs + confidence.
- `POST /lid` — audio snippet or text → language code + confidence.
- `POST /dialect` — language + audio/text → dialect code + confidence.
- `POST /asr` — audio stream + language/dialect + mode → transcript + timing + confidence.
- `POST /mt` — source text + src lang/dialect + target → translation + **coverage** +
  per-word provenance + alternatives (QueryBook covenant preserved server-side).
- `POST /tts` — text + language/dialect + voice ID → audio stream.
- `POST /telemetry` — anonymized metrics → ack.

**Routing**: offline or low-bandwidth → local; online + complex/long/Tier-2/3 + permitted →
cloud. **Fallback**: cloud unavailable → local where possible, and the app tells the user quality
may be reduced. **Low LID/dialect confidence** → confirm with user or re-run with cloud LID.

## 12. System Monitor (developer / power-user mode)

Reuses QueryBook's diagnostics/QC ethos (the engine already exposes `espeak_status`,
`pronunciation_qc`, diagnostics). Displays: active models and sizes; RAM and storage per pack;
latency per stage (ASR / normalize / LID / MT / TTS); cloud-vs-local usage; LID and dialect
confidence; QC battery pass score. Controls: force offline / force cloud; enable/disable specific
models; logging toggle.

## 13. Performance requirements

| Budget | Target |
|---|---|
| ASR partial output | < 150 ms |
| Full on-device translation (Tier 1) | < 500 ms round-trip |
| Cloud translation | < 1.2 s |
| App idle RAM | < 150 MB |
| Active translation RAM | < 350 MB |
| Base app storage | < 120 MB |
| Tier-1 pack | 8–40 MB · Tier-2 5–20 MB · Tier-3 < 3 MB |
| Deterministic reproducibility | identical input → identical output (hard requirement) |
| Offline availability | 100% of core functions for installed packs, no network (hard requirement) |
| Cloud dependency for core function | none — cloud is pack delivery + optional enhancement only |

## 14. Security, privacy & QA

- **Security/privacy**: encrypted cloud calls; no audio/text stored without opt-in; anonymized
  telemetry; on-device default needs no network; GDPR/CCPA.
- **Offline QA (gating):** with all radios off, 100% of core functions — speech-to-text,
  LID/dialect, translation with coverage, pronunciation, and spoken output — must work for every
  installed pack, on a device that has never been online since setup. This is a release gate, not
  a nice-to-have.
- **Functional QA**: all language pairs; dialect detection/override; every script; offline↔online
  transitions (including network dropping mid-utterance with no visible failure); the trust layer
  (coverage, flags, provenance) correctness.
- **Stress QA**: long utterances; noisy environments; rapid language switching; low storage /
  low memory devices.
- **Localization QA**: RTL layouts; CJK/Indic shaping; mixed-script; transliteration.
- **Covenant QA**: assert the app never emits a translated word with no source; coverage is
  always reported; audio is never fabricated — automated via the QueryBook QC battery extended
  with translation-coverage assertions.

## 15. Development roadmap

- **Phase 0 — Foundations (2–3 wk):** finalize tiers; sign off this spec; repos/CI; agree
  QueryBook cloud API contracts; confirm the open-source ASR/phonemizer/voice components per role.
- **Phase 1 — Mobile skeleton (4–6 wk):** UI (conversation/text/phrasebook/settings), audio
  capture + playback, pack manager (mock), System Monitor (stubbed), translation flow on stubs.
- **Phase 2 — On-device deterministic core (6–10 wk):** integrate the QueryBook language
  functions (normalize, LID, dictionary MT + coverage, G2P, speech ladder, QC) + Tier-1 ASR;
  the trust layer; RAM/storage tuning; dynamic load/unload. **Milestone: fully offline Tier-1
  translation that never fabricates.**
- **Phase 3 — QueryBook cloud (6–8 wk):** gateway client; `/model-selection` routing;
  Tier-2/3 via cloud; telemetry. **Milestone: full language coverage with honest fallback.**
- **Phase 4 — UX, scripts, dialects (4–6 wk):** RTL/CJK/Indic/mixed-script; transliteration;
  dialect overrides; conversation/phrasebook polish.
- **Phase 5 — QA, hardening, launch (6–8 wk):** functional/stress/localization/covenant tests;
  privacy review; final latency/footprint tuning; iOS/Android release candidates.

## 16. Licensing posture (for commercial launch)

As in the QueryBook language spec, each third-party component is reached through a role interface
and is substitutable. Two to resolve before commercial release: the bundled **open-source speech
engine** may be strong-copyleft (invoke across a process boundary or substitute a
permissively-licensed/self-owned voice engine); the demonstration **bilingual dictionaries** may
be non-commercial (substitute permissive/self-owned bilingual data). The deterministic engine and
the covenant are QueryBook's own and carry no such restriction.

## 17. Open decisions for the team

1. **Product name & brand** ("QueryBook Translate" is a placeholder).
2. **Acoustic ASR source** — which open-source on-device ASR family fills the role (quality vs
   size vs license), and the distillation/quantization target per Tier-1 language.
3. **Cloud MT depth** — whether cloud MT is the current deterministic engine at scale, the neural
   LEL roadmap embodiment, or both behind the router (all must preserve coverage/provenance).
4. **Dictionary sourcing** — permissive/self-owned bilingual data to replace NC demo data, and
   coverage targets per language.
5. **Camera/OCR mode** — in launch scope or a fast-follow.

---

*QueryBook Translate is the QueryBook covenant in a traveler's pocket: as fast and small as the
gadget translators, and the only one that refuses to make up what it does not know. The
deterministic language core is QueryBook's own; the acoustic front-end and the speech engine are
substitutable open-source components addressed by role.*
