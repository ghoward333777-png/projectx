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

### Harvesting fail-safe — never regress (`apps/_core/qbbulk.py`: `intent`, `ensure_on`, `keep_alive`, `rest`, `watchdog_info`)

- The user has lost many hours to harvests that ran without adding a fact. Harvesting health is judged by NEW FACTS
  (`total_gathered` rising), never by activity (bytes, rows, a churning drive).
- Start = ON until Stop (`_intent.json`). `ensure_on` starts the engine whenever it is on and not running; only
  `stop(auto=False)` (the Stop button) switches it off — internal stops must pass `auto=True`.
- Never one long all-or-nothing disk job: `merge_into` works in 256 saved pieces and `restore_missing` resumes and never
  merges an unchanged copy twice (`_restored.json`). The user's log showed the old merge churning the external drive for
  hours, restarted from zero by the fail-safe itself. "starting:" (getting ready) is work with its own progress.
- Harvesting never waits for the add-back: `restore_missing` runs in a background thread of the runner and holds out only
  the dataset it is merging (`Supervisor.hold`). The Control Panel log records "harvest: 0 facts a minute - why" every 10 min.
- An agent never queues to file at the end of a part: `Shard.merge(wait=False)` there (blocking only at `STAGE_CAP` or the
  end of the dataset). Blocking there left 15 of 16 lanes idle for hours.
- A runner whose process exists is alive (`_runner_alive`, heartbeat up to 15 min late): the heartbeat file is on the busy drive.
- One dataset reading 45 min without a new fact is rested (`DRY_DATASET_S`). The Control Panel's `drive_guard` pauses
  harvesting while the data drive fails its probe or gives I/O errors, and resumes by itself. Excessive pauses raise an
  alert and turn the window's header pill red (`/api/bulk/health`, `/api/shell/harvest`).
- `keep_alive` ladder with no new fact: 1 h restart, 2 h hard restart, 3 h rest the dry datasets 6 h (`_rest.json`, honoured
  by `Supervisor.check`). An advancing filing is exempt for at most `WORK_MAX_S`. Keep the page and diagnostics text honest.

### Relevance — the measure is answerable questions, not fact count (`qbrelevance.py`, `sense.py`, `qbbulk.WikidataHot`)

- 1.5 billion facts could not answer "Who is Ed Sullivan?" and took Babe Ruth for a baseball card. Never judge the store by
  its size: judge it by the relevance test (198 well-known subjects, 12 fields; daily; Harvesting → Relevance).
- Popularity = Wikipedia page views first (`hot-most-read`, `wd_views`: summed over sampled months so lasting subjects beat
  news spikes), then fame (Wikipedias with an article), then facts held. Views are an added signal, never the only one, and
  never outrank the kind the question expects.
- Icons first (`ICONS`, `WikidataIcons`, `hot-top-*`): the best known of each type people ask about (teams, athletes, bands,
  screen, leaders, landmarks), by fame, weighted for the user's culture (`bulk:culture`), the best 50 of every type in turn.
  The user's priority is types and iconic subjects "in line with culture" — incoming-link counts are NOT fame.
- People say part of a name ("the Dodgers"): `wd_names` word index + `by_part_of_name`; an exact name is only an edge, fame
  outweighs it. A prefix-only search result is never an answer: say so and queue the subject.
- The hot list first — the user's order ("Prioritize the hot list - so it builds immediately - and other harvest domains wait"):
  `hot-seed` reads the icons list shipped in `apps/_core/hot_seed.json` (rebuild with `tools/build_hot_seed.py`) from the first
  minute; `Supervisor.hot_first` starts no other dataset while the hot list has work (valve: 30 min without a new hot fact).
  When the records service refuses (429) records come through the query service (`wdqs_entities`). Names are tried with and
  without "The" (`name_forms`). Do not loosen any of these.
- A refused records service is answered in this order: the per-record address (`entitydata_entities`), then the query service
  in halving batches (`wdqs_entities`). The query service alone lost most facts of famous subjects — never make it the first.
- One name of an item must hold EVERY word asked, short words too (`wd_names`), and a full name matched exactly outweighs fame
  (`sense.choose`): "Ed Sullivan" was answered with Boris Vian (pen name Vernon Sullivan).
- Network of nets — the user's design: `hot-circle` reads everything a hot record is tied to (`CIRCLE_TIES`), then their ties,
  three rings out (`CIRCLE_RINGS`), most tied-to first, in waves. It is NOT in the hot-first gate (it never ends) and complete
  domains do not feed it. Icons are segmented into `ICON_CATEGORIES` (the user's list) and chosen by fame AND by leadership,
  wealth and influence (`government-leadership`, `wealth-technology`, `news-media`). Keep all of it.
- Harvest order: `hot-demand`, `hot-seed`, then `hot-top-*` icons, `hot-circle`, then `hot-most-read`, then the hot lattices (best-known items of each kind,
  most linked-to first), then everything else. Keep `qbkeystone.order` putting `hot-*` first.
- Complete domains (`DOMAINS`, `WikidataDomain`, keys `hot-all-*`) — the user's strategy: until the store is mature, harvest
  100% of chosen domains in tiers (1 public-facing people, 2 key jobs in critical fields, 3 other well-known fields), after
  the hot lattices. Every root carries the label it must have; `domain_discover` re-checks it and leaves a mismatch out.
  Never add a Wikidata code from memory without checking its label (four in `HOT` were wrong).
- The dump lanes read never-read positions first and finish an edition before a new one is fetched. Do not go back to
  "newest edition, part 1" — that is why whole stretches of Wikidata were never read.
- Answers go through `find_entities` + `sense.answer_for`: the kind of each match, the kind the question expects, the thing
  itself above things made about it (a card, a film, an award), fame, identifiers last. Never return "the first match".
- When nothing (or only a thing-about) is held, say so and queue the subject (`/api/bulk/demand`). Never pretend.

### Top Americans 1400–2026 — the user's plan (`docs/querybook-rebuild/top-americans-1400-2026.md`)

- The specification for the American Historical People Graph: five inclusion classes (American-associated ≠ American-born ≠
  U.S. citizen), eleven eras with era-normalised prominence, six scores stored APART from facts, per-fact confidence, the
  identity chain QB-PER → QID → LCNAF → VIAF, a source and licence ledger on every ingestion job, eight phases. Read it before
  building anything about people, rankings or prominence; its sections 12–13 say what exists and what does not.
- A ranking is an analytical output, never a fact. Never rank by raw present-day popularity alone. Never scrape ranking or
  celebrity sites; record a source's licence from its own page before ingesting it.
- A person has several roles: `sense.known_for` (`ROLES`) finds the best known from the person's own facts — the description's
  order first, then facts that back a role up, the highest office, the record's order last. Keep "also" roles; never reduce a
  person to one profession.

### Knowledge Demand Engine — the user's design (`docs/querybook-rebuild/knowledge-demand-engine.md`)

- Principle: harvest by demonstrated demand, validate by authoritative evidence. Four records never mixed: observed metric,
  observed navigation, inferred intent (always labelled), verified fact (the only UFCS assertion). Demand never raises
  confidence, importance or truth.
- Built (1.47): demand measurements by period, never added up or overwritten (`demand` table, `wd_demand`), classified with
  the numbers behind the label (`demand_class`, model `WDIE-1.0` — a change of rules is a new model version).
- Not built: see its section 11 (qualifiers/references on facts, clickstream, coverage auditor, source ledger, outside
  sensors). No new source is ingested before its licence is recorded from the source's own page.

### Complete facts — dates, sources, rank (`docs/querybook-rebuild/complete-facts-plan.md`; engine 1.48)

- Every Wikidata statement kept is harvested with its context (`statement_context`): start / end / point in time, other
  qualifiers, rank, sources. It is stored BESIDE the fact (`context` table in the dataset's label file, keyed by item,
  predicate and stored value; `wd_context`) — never change the facts table or a fingerprint for it.
- Hot datasets keep sources; the dump lanes keep dates, qualifiers and rank only (`CONTEXT_LANE_REFS` off: tens of GB).
- `hot-context` completes well-known records read before 1.48. It writes NO facts (`facts()` returns []), is outside the
  hot-first gate and is exempt from the dry-dataset rest (`no_new_facts_expected`). Keep all three.
- A record that came through the query service has no context (`_partial`): it must stay listed for a later read.
- A date is shown only when the store holds one (`sense.period`, `sense.dated`). Never supply a missing date.

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

- 22 public-domain books (Darwin excluded at the user's request — never add him), three of them Bibles (`bible-kjv`, `bible-asv`,
  `bible-web`, made by `tools/build_bibles.py`: a book of the Bible is a chapter, its chapter a section, a verse a paragraph).
  Only public-domain translations: the NASB, NIV, ESV and the rest of Bible Gateway are under copyright and its terms forbid
  copying — do not add them. Texts are QueryBook editions:
  Project Gutenberg header/licence/trademark removed, provenance and rights kept in `meta.json`.
- After changing `bookq.py`, a `meta.json` or a `modern.json`, run `python tools/build_library.py` (its `--check`
  runs in the tests). Modern/context entries must name sources and match a real sentence of the book.
- The Book Harvester (`apps/_core/qbbooks.py`, Control Panel → Books) writes harvested books to `<data>/library`.
  `bookq.py` lives in `apps/_core` and is copied to every app and to `apps/shell` by `sync_core.py`. Keep the rights gate
  (unknown → held, IA judged by publication year, Gutenberg 'copyrighted' refused) and the Rights Record on every book.
- Book Query answers through `apps/_core/qbcompose.py` (plan -> evidence -> compose -> verify; Claude `claude-opus-5-5` via
  raw HTTP because the bundle is stdlib-only, else Gemini, else `bookq.compose_rules`). Keep the verification: no
  uncited sentence, citations only to supplied passages. Multi-book questions (`books: [...]`) are a core feature.

### Writing skills / AI text gen — the user's plan (`docs/querybook-rebuild/writing-skills-plan.md`)

- In the window it is **✍️ AI text gen**, in the rail beside Language and Translate (the user: "part of the language and speech
  page"). The user is building and perfecting it over days: extend it, do not move or rename it.
- `apps/shell/writing.py` is pure and rule-based (Rust-compat list): the topic–comment tagger, the framework classifier, the
  four checks, the blueprint and the five-layer critic. It invents nothing and marks what it cannot tell as unsure.
- Genres are DATA: edit `tools/build_genres.py`, run it (its `--check` is in the tests). A new genre is a new row, never a
  change to the writer. Rules are in QueryBook's own words; keep no source passages. A record's provenance must stay honest:
  "first draft … the sources have not been learned from yet" until a page of a source really has been.
- The user's decisions (2026-11-13): all genres, any order; all sources, each page learned ONCE (`assist.learn_source`: robots rules
  first, rules in QueryBook's words, a rule repeating the page's wording is dropped, no passage kept); the user reviews AS the
  document is composed (plan → draft → their notes → revision — never skip the plan step); style is the user's own, measured
  from their sample as numbers (`style_profile`; no sentence stored), or a template from the growing library (`STYLES`).
- A document = a form (genre) × a field (`FIELDS`: citation system and evidence standard) × a style. All three are rows in
  `tools/build_genres.py`. The aim is universal coverage: add rows, never special cases. A field's citation system is never a
  licence to invent a source. No source is marked learned unless a page of it really was.
- The writer and the critic read the same record. No genre named → ask, never guess. Legal genres stay "a draft for a
  qualified lawyer"; a crime report never calls an accused person guilty. A model's draft is labelled (`by`).

### AI Capabilities (`querybook-one/apps/shell/caps.py`, `assist.py`, `ui/capspage.js`)

- The user's list of twelve, in this order — keep all twelve tiles: Ask/Search, Summarize, Write/Create, Organize, Analyze,
  Develop/Project, Tools, Processes/Workflows, Agent(s), Chatbot, Translate/Languages, Learn/Study.
- `caps.py` is pure and rule-based (in the Rust-compat list): it must work with no AI key and invent nothing. `assist.py`
  adds Claude/Gemini through `qbcompose.ask_model`; every result carries `by` and the page shows "Made by".
- Capabilities that already have a home open it (Ask page and its modes, Book Query, Language, Translate, STEM, Video,
  Harvest) — do not build second copies. Tests: `tests/test_capabilities.py`.

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
