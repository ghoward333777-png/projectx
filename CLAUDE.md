# Book Intelligence Studio — engine invariants

Dependency-free PHP 8.1+ app (no Composer, no database, no API keys). Run locally with
`php -S 127.0.0.1:8082` and run every test in `tests/` (plain `php tests/<name>.php`)
before shipping. A JS mirror of the whole engine lives outside the repo for the test
dashboard; any change to outline or prose generation must be ported there and verified
byte-for-byte (compare `word/document.xml` md5 across engines) before publishing.

## Manuscript composition rules (do not regress)

These rules fixed the "bad manuscript" defect where drafts printed the editorial plan
as prose. Keep them intact in `BookIntelligenceEngine::composeExpandedChapterDraft()`:

- **Never emit meta-language.** No "Editorial development plan", no talk of outlines,
  purposes, drafting, chapters explaining themselves, or readers being taught how the
  book is built. The prose discusses the subject; it never discusses writing about it.
- **Strip instruction verbs from outline clauses** before using them in prose or
  headings (`$subject()` in the composer). Outline details are imperatives addressed
  to the writer; the manuscript must convert them to subjects.
- **Sections come from the chapter's own detail clauses** — heading per clause
  (≤52 chars, word-boundary cut, trailing stopwords trimmed), five paragraphs per
  section from the rotating discussion templates. No generic scaffold headings.
- **Close every chapter with a `The takeaway` section.**
  `IllustrationStudio::takeawayQuote()` and the Quality Lab takeaway metric read it.
- **Genre-aware outlines** in `suggestTableOfContents()`: social/cultural topics get
  the narrated-history arc (current state → past contrast → origins → evidence →
  solutions; concrete titles, never "systems"/"frameworks"); practical topics get the
  how-to arc; curated outlines exist for teen jobs and gender-relations topics.
  `reviewOutline()` (the Nonfiction Outline Editor) scores outlines against 12 rules —
  keep new outlines passing 100.
- **Word contents page**: plain text + dot-leader tab + page number from the page
  plan. No `<w:hyperlink>` anywhere in the export; keep the chapter bookmarks.
- **User-supplied outlines** via `AmazonBookWriter::parseOutline()` (one chapter per
  line, optional `| purpose | detail`) must keep flowing into `writeBook()` untouched.

## Manuscript development (first run ends in prose)

The engine draft is pass 1 — development directions, never the finished book.
`ManuscriptDeveloper` + `bin/develop-manuscript.php` execute passes 2 (AI
writer per chapter) and 3 (AI editor per chapter) and assemble the developed
chapters back through the exporters; `writeBook()` accepts finished texts via
`developed_chapters`. Keep the writer/editor prompts carrying the hard rules
(real prose only, follow the draft directions, no fabricated precision, "The
takeaway" closer, exact format contract). Default Anthropic model:
`claude-opus-5`. `BookProjectStore` records every generation's TOC + manuscript
under `projects/` — keep the auto-save in `amazon-book-writer.php` and the CLI.

## Prose quality controls

- **Hygiene**: `ManuscriptHygiene::clean()` runs on every developed chapter and
  `cleanLine()` on every pasted outline row — NFC normalization (skipped
  gracefully without ext-intl), invisible-character stripping, exotic spaces to
  ordinary spaces, LF line endings, collapsed runs, one blank line between
  paragraphs. Deterministic; keep it that way.
- **Rhythm**: the style contract carries a RHYTHM AND VARIETY section (sentence
  and paragraph variation, banned filler transitions, no repeated openings) and
  each chapter gets a rotating cadence directive so neighbours don't share one
  voice.
- **Revision**: the editor prompt does structural work (reorder weak argument
  order, compress circling passages, spend the words on the thinnest claim) and
  `ManuscriptDeveloper::revisionReport()` flags chapters wanting a human pass —
  deterministic, local, no API cost — surfaced in the writer results page.

## QueryBook (do not regress)

QueryBook (`QueryBook.php` + `query-book.php`) is the reader-side answer layer
from the original QueryBook concept: answers in many forms, all linked to a
target book.

**Canon of record.** The QueryBook canon is CONFIDENTIAL and lives OUTSIDE
this repository — never commit it or quote it at length here. It is
documented in the owner's Claude artifacts: the **QueryBook Master Bible**
artifact (Feature Inventory v59 — 279 features, 341 claims, domains D0–D14,
the additive covenant, the canon record), assembled from **Bible v2.1**
(Pass 113, with later passes — Pass 118 as of the Fact Unit Integration Map
artifact), alongside the Core Technology Overview v9 and the Core Tech
Reconciliation artifacts. The uploaded "Canonical Core Technology
Specification" is an EARLIER layer of the spec; when it and the artifact
canon disagree, the artifact canon wins (its superseded style-enum map was
removed from this module by owner decision, Sept 13, 2026 — the expository,
argumentative, and descriptive modes it motivated remain shipped). Consult
the artifacts (Artifact tool, `action: "list"`) before re-deriving any of
this.

This module is the studio-scale realization of the canon's output layer:

- `QueryBook::CANONICAL_D4_MODES` maps the canon's D4 user-facing modes
  (Standard Q&A, Guided Exploration, Discussion, Tutorial, Semantic
  Exploration, Timeline Reconstruction, Edition Comparison, Flashcard
  Generation) to this module's modes and forms. Keep the map total.
- `QueryBook::REGISTERS` carries the canon's D7 expressive registers
  (plain, formal, academic, instructional, narrative, supportive,
  authoritative): exactly one per response, VOICING ONLY — a register
  never alters evidence, hedges, or claims — and an unregistered register
  is refused, never approximated.
- Every answer returns a `context_key` (the canon's Context Lock):
  determinism is asserted between two answers only when their keys match.
- `QueryBook::DOMAINS` plays the audience-model role (vocabulary, domain
  expertise, detail level); `max_words` is the output-length constraint.
- Grounding: every answer cites the chapters it came from, and tailoring
  never adds claims the book doesn't carry.
- **The additive covenant applies here**: once a mode, register, domain, or
  form ships, it is never removed — the contract test enforces the floor.
- **Community Query Mode was removed from the invention** (owner decision,
  Aug 29, 2026). Never add community, shared-query, or cross-reader
  features to this module.
- The "output templates available to all users" rule below is recorded
  HERE — this file is the availability policy's home.

- **Output templates are available to all users.** Every answer mode
  (`QueryBook::MODES` — Q&A, conversational, research, executive brief,
  tutorial, study, quotes), every domain profile (`QueryBook::DOMAINS`), and
  every output form (`QueryBook::FORMS` — summaries, analysis, synopsis,
  abstract, outline, glossary, FAQ, study guide, key quotes, reading plan,
  comparisons, document reports, related questions) is exposed to every user
  on `query-book.php` with no account, login, payment, or API key — and ships
  in the hosting package so it stays that way on self-hosted installs. Never
  gate a template behind a tier, flag, or key.
- One dispatcher serves them all: `QueryBook::request($form, $options)` over
  the `FORMS` catalog; new forms get a `FORMS` entry, a `request()` arm, page
  exposure, and coverage in `tests/querybook-contract.php`.
- Answers are tailored per industry/domain via the `domain` option; tailoring
  reframes and appends — it never fabricates content the book doesn't carry.
- Deterministic and local: same book + same question/form = same output.
  Every deliverable renders via `renderMarkdown()`/`renderPlainText()` and
  downloads as .md/.txt/.json.
- The Quality Lab's `queryBookPlan()` (quiz/takeaway/learning path) is a
  separate, older slice — keep it working; it is not a substitute for the page.

## Housekeeping

- New app files must be added to `SitePackageExporter::FILES` or the hosting zip
  self-test fails.
- Deterministic output is a feature: same inputs must produce the same book.
- Voice cloning stays behind the explicit consent gate (`voice_consent` / `--consent`).
