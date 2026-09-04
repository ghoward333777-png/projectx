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
- **Visuals are chosen by the selection formula**, not fixed heuristics:
  `IllustrationStudio::selectVisual()` scores each section's text 0–3 on nine
  signals (comparability, temporal dynamics, magnitude, proportion, mechanism,
  anchoring, structure, data density, decision support) and takes
  argmax(Wp + Ws + Wn) — primary decision tree (3), secondary signals (0–3),
  narrative-function tie-breaker (2). Comparisons→table, change over
  time→line graph, rankings→bar chart, part-to-whole→pie, processes→step
  diagram, abstractions→figure, real people/places→the chapter's AI image.
  Deterministic; `tests/visual-selection-contract.php` pins the tree, the
  scoring bounds, the tie-breakers, and the instruction pairing (a practice
  chapter's step diagram always ships with its worksheet).
  **The render gate**: a figure exists only when the text supplies its
  content — extracted time series, shares, quantities, or narrated steps
  (`extractTimeSeries` / `extractShares` / `extractQuantities` /
  `extractSteps`). No extractable data means no figure: never chart the
  document's own word counts, never emit decorative emblems. Data figures
  carry their `data_rows`.
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

## Housekeeping

- New app files must be added to `SitePackageExporter::FILES` or the hosting zip
  self-test fails.
- Deterministic output is a feature: same inputs must produce the same book.
- Voice cloning stays behind the explicit consent gate (`voice_consent` / `--consent`).
