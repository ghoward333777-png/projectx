# QueryBook Language Intelligence — architecture

Status: design, 2026-11-12. Nothing in this document is built yet except the parts listed under "What exists".

## The aim, stated honestly

QueryBook should understand and produce language with six skills: dialect translation, accent adaptation for the
listener, grammar, rhetoric, composition, and analysis and replication of writing style.

"Exceed the LLMs" needs a precise meaning, because a rule-based system will not out-write a large model at open-ended
fluent prose. What QueryBook can do that a model alone cannot:

| QueryBook can | A model alone |
|---|---|
| Give the same answer every time | Varies run to run |
| Name the rule behind every change | Cannot show its reasons |
| Measure the result (style distance, meaning kept, intelligibility) | Asserts quality |
| Control sound at the level of single phonemes | Has no handle on audio |
| Keep every factual statement tied to a stored fact | Invents |
| Treat a dialect as a system with its own rules | Treats it as noisy standard language |

So the design is: **a deterministic linguistic core that analyses, constrains, checks and measures; a model used as one
component for drafting, never as the judge.** Where a model is used the result is labelled, as everywhere else in
QueryBook.

## What exists and is reused

| Piece | Where | Role here |
|---|---|---|
| Dialect Parameter Clusters (phonology, lexicon, morphosyntax, prosody, sociolect) | `apps/language/dialect.py` | The dialect model; extended |
| Pronunciation resolution (heteronyms, per-engine forms, IPA) | `pronounce.py` | The sound plan |
| Function-word lists | `function_words.py` | Style fingerprint |
| Speech engines, voice DSP, formant voice | `tts.py`, `voicedsp.py`, `speech.py` | Rendering sound |
| Speech science measurement (SSP-1) | `speechsci.py` | Measuring what was said |
| Offline translator (lexicon, g2p, quality checks, language ID) | `ui/translate/src/core` | Cross-language layer |
| 139-language registry, online gateway | `lablangs.py` | Coverage |
| Author persona and its consent gate | `persona.py` | The model for style consent |
| Prose controls (hygiene, rhythm, revision report), outline arcs | Book Studio | Composition |
| Plan → evidence → compose → verify | `qbcompose.py` | Grounded generation |
| Kinds of things, fame, the fact store | `sense.py`, `qbbulk.py` | Meaning |
| 19 public-domain books | `apps/shell/library` | Style test set |

## The centre: one record for every utterance

Every skill reads and writes the same record, the **Utterance Record**. It keeps three things apart that most systems
blur: what is meant, how it is worded, and how it sounds.

```
Utterance Record
  meaning    the statements made, as meaning atoms; each linked to a fact when one exists
  form       tokens, lemmas, parts of speech, phrases, clauses, sentence type, tense, voice, person
  discourse  what each sentence does (claim, evidence, concession, example), how sentences connect
  rhetoric   devices found, the appeal each passage makes, audience and purpose
  style      the measurable habits of this text (see Style)
  variety    language, dialect, register — as detected, with confidence
  sound      the pronunciation plan: phonemes, stress, phrasing, pitch contour, rate
```

Every transformation is a function from one record to another that changes named layers and leaves the others alone:

| Skill | Changes | Must keep |
|---|---|---|
| Dialect translation | form, variety, sound | meaning |
| Accent adaptation | sound only | meaning, form |
| Grammar correction | form | meaning, variety |
| Rhetoric | discourse, rhetoric, form | meaning |
| Composition | everything, from a plan | the facts it was given |
| Style replication | form, style, rhetoric | meaning |

That table is the test plan as well: after each transformation the "must keep" layers are compared, and a change there is
a failure.

## Layers

```
6  Measurement      proficiency tests, scores kept over time
5  Verification     meaning kept? grammar valid? style within distance? facts cited?
4  Generation       planner -> realiser; a model may draft, inside the constraints
3  Transformations  the six skills
2  Resources        lexicons, dialect clusters, grammar rules, device catalogue, style profiles, facts
1  Analysis         text -> Utterance Record (per language)
0  Foundation       hygiene, tokens, language and dialect identification, scripts
```

Layers 0–3, 5 and 6 are deterministic, standard library, written as pure modules so they can be ported to Rust like
`qbmath`, `modes` and `sense`. Layer 4 may call a model.

## The six skills

### 1. Dialect translation

A dialect is a system. Translation goes dialect → meaning → dialect, never by word swaps on the surface.

- Each Dialect Parameter Cluster gains rules in both directions, each with its conditions and a cited source.
- Three rule kinds: lexical (word and sense), constructional (habitual "be", double modals, "fixin' to"), and pragmatic
  (politeness, address forms).
- Register is carried separately from dialect: informal standard English is not a dialect.
- What has no equivalent is kept and marked, never dropped or guessed.
- Guard: only documented features are used. No invented spellings to make a dialect "sound" like itself.
- Detection gives a variety and a confidence; below a threshold it says so and does not translate.

### 2. Accent adaptation for the listener

The words stay the same; only the sound layer changes. Three operations on the pronunciation plan:

| Operation | What it does |
|---|---|
| Adapt | Move the speaker's sounds toward the listener's accent where that helps understanding |
| Add | Render the text in a chosen accent |
| Remove | Move toward a chosen reference accent |

- Works on phonemes, stress, rhythm and intonation — the phonology and prosody parts of the dialect clusters.
- Stage A: synthesised speech, where QueryBook controls every phoneme. This is practical now.
- Stage B: recorded speech (changing a real voice). Much harder, and it needs the speaker's consent through the same
  gate as voice cloning.
- Measured, not asserted: a confusion model per listener background predicts which sounds are misheard; the result is
  checked with the existing speech-science measurement.
- Framing matters. This is a listener's choice for intelligibility, opt-in. No accent is treated as a defect.

### 3. Grammar

- A rule grammar per language: agreement, tense and aspect, articles, word order, punctuation, sentence boundaries.
- Three outputs for each finding: the correction, the rule by name, and an example — so it teaches as well as fixes.
- Dialect-aware: a construction that is regular in the detected variety is not an error. It is reported as "regular in
  this dialect; in the standard it would be …".
- Constraint: QueryBook is standard-library only, so this is its own rule engine (pattern rules over tagged tokens, the
  approach rule-based checkers use), not an imported parser.
- Ties to the Language Lab: every rule links to practice.

### 4. Rhetoric

- A catalogue of devices with detection rules: repetition figures (anaphora, epistrophe), balance (antithesis, tricolon,
  chiasmus), questions, direct address, and so on.
- Argument structure: claim, evidence, warrant, concession, rebuttal.
- Appeals: to character, to feeling, to reasoning — with the passages that make each.
- Fallacy patterns, flagged for a person to judge.
- Two confidence classes, always shown. Structural devices are found by rule. Devices that depend on meaning (metaphor,
  irony) need a model and are marked "model-judged".
- Applying rhetoric: given an audience and a purpose, propose rewrites that add or remove named devices; the meaning
  check then runs.

### 5. Composition

Plan → outline → paragraphs → sentences, with a check at each step.

- Genre schemas: the outline arcs Book Studio already has, plus letter, report, essay, speech, story.
- Paragraph craft: topic sentence, development, known-before-new ordering, connectives that match the actual relation.
- The existing rhythm and hygiene controls and the revision report apply.
- Every factual sentence is tied to a fact or passage (the `qbcompose` rule: no uncited sentence).
- A model may draft a paragraph; the deterministic layer decides whether it meets the plan, the grammar, the style
  profile and the facts, and sends it back with named faults if not.

### 6. Style: analysis and replication

Analysis produces a **Style Profile** — numbers, not adjectives:

- Sentence length: average, spread, and the pattern of long and short.
- Function-word frequencies (the established basis of authorship work).
- Punctuation habits; vocabulary richness and word length; favourite constructions.
- Rates of each rhetorical device; paragraph length; point of view, tense, register.

Replication is a loop with a measured stopping rule:

1. Draft under the profile.
2. Measure the distance between the draft's profile and the target's.
3. Name the features furthest off, revise those, and repeat until within the threshold.

Test, using the 19 books already in the library:
- Attribution: given an unseen passage, name its author. This proves the analysis sees real style.
- Imitation: text written "in the style of" an author must be attributed to that author by the same classifier, while a
  plagiarism check confirms no sentence was copied.

Guard: replicating a living person's style needs their consent, recorded as the voice persona's consent is. Output is
never presented as written by that person.

## Verification — what makes it trustworthy

| Check | Method |
|---|---|
| Meaning kept | The meaning atoms before and after must match; any difference is listed |
| Facts | Every factual sentence cites a stored fact or passage |
| Grammar | The result passes the grammar of its target variety |
| Style | Distance to the target profile is under the threshold |
| Sound | The measured speech matches the pronunciation plan |
| Nothing copied | No sentence of a style source appears in the output |

A result that fails is not shown as finished. It is shown with the failed check.

## Measurement — a proficiency test, like the relevance test

One suite per skill, run on demand and daily, scores kept over time on one card:

| Skill | Test | Number |
|---|---|---|
| Dialect | Round trip: dialect → standard → dialect | Meaning kept, constructions recovered |
| Accent | Predicted and measured intelligibility for a listener profile | Change against the unadapted speech |
| Grammar | A corpus of seeded errors and correct dialect sentences | Found, missed, wrongly flagged |
| Rhetoric | Annotated speeches | Devices found, by confidence class |
| Composition | Plans with known facts | Plan followed, sentences cited |
| Style | Attribution and imitation on the library | Accuracy; imitation accepted |

## Build order

| Stage | What | Why first |
|---|---|---|
| 1 | Utterance Record and English analysis; Style Profile and the attribution test | Small, measurable, uses the library already there |
| 2 | Grammar rules for English with explanations; dialect awareness | Every other skill checks against it |
| 3 | Dialect translation for the English varieties already clustered; accent for synthesised speech | Builds on existing dialect and speech code |
| 4 | Rhetoric catalogue; composition planner with model drafting and deterministic checks | Needs 1–3 as its checks |
| 5 | Other languages, one at a time; recorded-voice accent work behind consent | Each needs its own rules and data |

## Open questions and risks

- **Meaning atoms are the hard part.** Comparing meaning before and after is easy for statements tied to facts and hard
  for opinion, tone and implication. Stage 1 must show how far a rule-based comparison goes before the rest relies on it.
- **Coverage by language.** Rule grammars and dialect clusters are written per language. English first; each further
  language is real work, not a switch.
- **Dialect data needs sources.** Every feature should cite published description. Where none is found the feature stays
  out.
- **Recorded-voice accent change** is research-grade and may not reach usable quality with local tools.
- **Where the model stays ahead.** Open-ended drafting and meaning-dependent rhetoric will lean on a model for a long
  time. The design accepts that and confines it.
