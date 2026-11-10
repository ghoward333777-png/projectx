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

## Housekeeping

- New app files must be added to `SitePackageExporter::FILES` or the hosting zip
  self-test fails.
- Deterministic output is a feature: same inputs must produce the same book.
- Voice cloning stays behind the explicit consent gate (`voice_consent` / `--consent`).

## QueryBook Next (`querybook-next/`)

The new, Rust-compatible Python version of QueryBook. It is NOT the QueryBook
suite: the suite (Language Builder, STEM, History & News, Video Studio, Control
Panel; 50+ versions) lives on branch `claude/lucid-brahmagupta-ak4f6m` under
`querybook/`. Always check that branch and the user's earlier sessions before
building QueryBook features.

- The user's real data is the suite's store on `D:\QB`: `commons\commons.sqlite`
  and `commons\shards\<dataset>.sqlite`, about 1 billion facts. QueryBook Next
  reads it in place and read-only (`core/legacy.py`, FQL `Facts`/`Commons`), and
  writes only to `D:\QB\querybook-next`. Never copy or modify the suite's store.
- Fact identity must match the suite's `qbcore.fingerprint` (verified by
  `contracts/golden_fingerprints.tsv`, generated from the suite's own code).
- Standard library only, Python 3.10+, Windows/macOS.
  `tests/test_rust_compat.py` enforces the Rust rules: no reflection, no
  `**kwargs`, full annotations in `core/` and `ingest/`, frozen dataclasses at
  boundaries.
- Lean 4 specs in `querybook-next/lean/` (classifier, billion-row guard) are
  checked by `lake build` in `.github/workflows/querybook-next.yml`;
  `tests/test_lean_spec.py` keeps their examples equal to the Python behaviour.
  The single-file build is `python tools/build_pyz.py` (deterministic).
- Before shipping, run `python3 -m unittest discover -s tests -t .` from
  `querybook-next/` and `cargo test --release` in
  `querybook-next/rust/querybook-core`. Changes to `core/text.py`,
  `core/lexicons.txt`, `core/fql/lexer.py` or `core/legacy.py` must be ported
  to Rust and their golden vectors regenerated.

## QueryBook one window (`querybook-one/`) — the current QueryBook rebuild

Stage 1 of the plan in `docs/querybook-rebuild/` (407-feature inventory + blueprint). It IS the suite: its
applications (`querybook-one/apps`, from `claude/lucid-brahmagupta-ak4f6m`) plus `apps/shell` (one window,
Ask box). Keep the suite's own conventions: edit `apps/_core` then run `apps/tools/sync_core.py`; every
app's self-test via `apps/tools/run_all_tests.py`. Formula math lives in pure modules (`_core/qbmath.py`,
STEM's `science.py`/`units.py`) with Lean proofs (`querybook-one/lean`, Mathlib, `lake build`) and a Rust
port (`querybook-one/rust/qbcore`); `tools/gen_lean.py` / `tools/gen_rust.py` regenerate them and their
`--check` runs in the tests, so a formula changed in Python must have its proofs and Rust regenerated.
The download is `tools/build_bundle.py` → QueryBook.zip (Python inside, data-folder.txt = D:\QB).

### Lip-sync and talking faces — the user's decision (do not change)

- Lip-sync is done by the **talking clips**: Gemini first, and when Gemini cannot, the chosen voice (e.g. ElevenLabs)
  with HeyGen animating the portrait (`apps/language/talkclip.py`, `ui/talk.js`, Speech → Talking clips, the Speak
  page's "Make a talking clip of this", the Lab's step-4 human avatar: pick a library face, "Avatar says it" plays the Gemini/HeyGen video in place). This is what works for the user. The human avatars (library faces) must always be visible where the user works.
- The local face engine (Language 1.53: face.js, avatarface.js, photoface.js, motionlib, Quality Lab) was tried and
  rejected by the user on 2026-11-10 ("failed lip synching"). Its code is kept in git history at commit 82e15af — do
  not put it back, and do not replace the Gemini/ElevenLabs route, unless the user asks.
- Language Lab languages and translation (1.55, `apps/language/lablangs.py`): every QueryBook Translate registry language
  (139) with Google Translate → Gemini online for what the offline packs/word lists lack (always labelled); espeak-ng
  voice else the browser's voice. QueryBook Translate's online gateway is the Language app (`/api/translate-gateway/mt`).
  Keep it — the user lost this once ("we previously had a good translation tool").
- Never remove or replace a working feature without first checking the git history and the user's earlier sessions
  for why it is there, and asking the user. Removing working features has cost the user days of work.

### Book Query library (`querybook-one/apps/shell/library/`)

- 19 public-domain books (Darwin excluded at the user's request — never add him). Texts are QueryBook editions:
  Project Gutenberg header/licence/trademark removed, provenance and rights kept in `meta.json`.
- After changing `bookq.py`, a `meta.json` or a `modern.json`, run `python tools/build_library.py` (its `--check`
  runs in the tests). Modern/context entries must name sources and match a real sentence of the book.
- The Book Harvester (`apps/_core/qbbooks.py`, Control Panel → Books) writes harvested books to `<data>/library`.
  `bookq.py` lives in `apps/_core` and is copied to every app and to `apps/shell` by `sync_core.py`. Keep the rights gate
  (unknown → held, IA judged by publication year, Gutenberg 'copyrighted' refused) and the Rights Record on every book.
- Book Query answers through `apps/_core/qbcompose.py` (plan -> evidence -> compose -> verify; Claude `claude-opus-5-5` via
  raw HTTP because the bundle is stdlib-only, else Gemini, else `bookq.compose_rules`). Keep the verification: no
  uncited sentence, citations only to supplied passages. Multi-book questions (`books: [...]`) are a core feature.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships
(every function, class, route and file, with what calls what). The session-start hook builds it automatically.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- graphify-out/graph.json is not committed (6 MB, rewritten whole on every build). If it is missing, rebuild it — local AST
  only, about 20 s, and identical every time: `graphify extract . --code-only && graphify cluster-only .` (install with
  `uv tool install graphifyy==0.9.105` if `graphify` is not found). Committed: GRAPH_REPORT.md (the project map),
  graph.html, and .graphify_labels.json — the cluster names, written by hand; when clusters change, name the new ones
  there ("QB1 …" QueryBook one, "QB Next …", "Book Studio …") and rerun `graphify cluster-only .`.
- The synced copies of the QueryBook core and bulk data are left out by .graphifyignore, which
  `.claude/graphify/ignore.py` regenerates from sync_core.py's FILES (read only).
- **Graphify is a Claude Code session tool only — the user's decision.** Never put it in the QueryBook prototype: no
  graphify code, calls or files under `querybook-one/apps`, `querybook-next`, the bundle or QueryBook.zip. Everything
  for it lives in `.claude/` (skill, hooks, `graphify/session-start.sh`, which installs it and builds the graph at
  session start) and `graphify-out/`.
