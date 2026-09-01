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

## Housekeeping

- New app files must be added to `SitePackageExporter::FILES` or the hosting zip
  self-test fails.
- Deterministic output is a feature: same inputs must produce the same book.
- Voice cloning stays behind the explicit consent gate (`voice_consent` / `--consent`).
