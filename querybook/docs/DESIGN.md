# QueryBook — unified prototype design

QueryBook puts four separate apps on one shared database:

| App | Answers a question with | Collection |
|---|---|---|
| **Language** | a dictionary entry: headword, numbered senses with part of speech, usage examples taken from the whole library (highlighted), and related words | `Language` |
| **STEM** | a worked solution: the result, every intermediate step, the variables substituted, then matching formulas and quantities from the library | `Stem` |
| **History** | a timeline: dated events in order, grouped into eras, filtered by any date range in the question (years, BCE, decades, centuries) | `History` |
| **Video Studio** | a storyboard: timed scenes, each with narration and a visual brief, drawn from all four collections. It is saved as a render job and rendered to MP4 with captions | `Video` |

The apps stay separate. Each has its own enrichment code, its own answer format
and its own UI page, and each can run as its own process on its own port. What
they share is the **FQL document store** and its **change feed**, so whatever
one app or harvester writes, every other app can query and sees immediately.

## 1. Architecture

```
                 ┌────────────── sources ──────────────┐
  drop folder ──▶│ FolderSource  (inbox/<domain>/*.txt  │
  RSS / Atom  ──▶│ FeedSource    .md .json .jsonl .csv) │──┐  continuous: Harvester thread,
  Source docs ──▶│ (declared in FQL at runtime)         │  │  per-source interval
                 └──────────────────────────────────────┘  │
  POST /api/ingest (any app, any script) ──────────────────┤  real time: synchronous push
                                                           ▼
              IngestPipeline: normalise → content hash (dedupe) → classify
                              → per-domain enrich() → store.create()
                                                           │
                       ┌───────────────────────────────────▼───────────────┐
                       │   FQL document store  (querybook.fqldb)           │
                       │   collections: Language Stem History Video        │
                       │                Source IngestLog  (+ any you make) │
                       │   full-text index · append-only change journal    │
                       └──────┬───────────────┬───────────────┬────────────┘
                     FQL queries        /api/stream (SSE)   FQL console
                              │               │               │
        ┌─────────────┬───────┴─────┬─────────┴───┬───────────┴─┐
        │ Language UI │   STEM UI   │ History UI  │  Video UI   │   Hub UI (all four,
        │ :8091 or    │ :8092 or    │ :8093 or    │ :8094 or    │   ask-every-app, FQL
        │ hub /language│ hub /stem  │ hub /history│ hub /video  │   console, live feed)
        └─────────────┴─────────────┴─────────────┴─────────────┘   :8090
```

**Deployment modes** (all share one database file):

- `querybook serve` runs the hub with all four apps and the harvester in one process.
- `querybook app <domain>` runs one app on its own port. Start as many as you like, side by side.
- `querybook harvest` runs ingestion on its own, so the UIs can stay read-only.

Several processes can write to the database at once. The store uses SQLite in
WAL mode underneath, and the change journal lives in the database file itself,
so the real-time feed also works across processes. A tested example: a document
pushed to the hub shows up on a standalone History app's stream.

### Source layout

```
querybook/
  querybook/core/        Rust-portable core (no I/O policy, plain data at every boundary)
    model.py             Document, ChangeEvent, RawItem, IngestResult (frozen dataclasses)
    interfaces.py        DocumentStore / Source / DomainApp protocols: the swap points
    text.py              text kernel: normalise, tokenize, FNV-1a hash, classify
    lexicons.txt         domain lexicons, shared verbatim with the Rust crate
    store.py             FQL document store
    fql/                 lexer → parser (AST) → evaluator
  querybook/ingest/      pipeline, sources (folder, RSS/Atom), harvester
  querybook/apps/        language.py stem.py history.py video.py (+ base envelope)
  querybook/server/      stdlib HTTP server, SSE stream
  querybook/ui/          hub.html + one page per domain, common.css/js (no CDN, works offline)
  querybook/samples/     starter library, loaded on first run
  contracts/             JSON Schemas for every wire shape + golden text vectors
  rust/querybook-core/   Rust port: text kernel, FQL lexer, contract types/traits
  tests/                 unittest suite (39 tests)
```

## 2. The common FQL database

### Why an embedded FQL engine

FQL is the Fauna Query Language. Fauna's hosted database service shut down in
2025, so QueryBook does not depend on a remote FQL server. Instead it ships an
**embedded FQL engine** that implements the FQL v10 style
(`Collection.where(...).order(...) { projection }`) over a local, file-based
document store. The `DocumentStore` protocol is the seam: a remote FQL backend,
or a Rust store, can replace it without touching the apps.

### Data model

- **Documents** are schemaless JSON objects in named collections (`^[A-Z]\w*$`).
  Every document has `id`, `coll` and `ts` (microseconds).
- **Ids are deterministic.** An id is derived from the collection plus a content
  hash, so the same text always gets the same id. Re-harvesting is a no-op, and
  the same inputs produce the same database.
- **Common ingested fields:** `title`, `body`, `source`, `url`, `domain`,
  `classified {auto, scores}`, `ingested_us`. Each domain then adds its own:
  - Language: `term`, `pos`, `definition`, `definitions[]`, `keywords[]`, `lang`
  - STEM: `subject`, `formulas[{expr,lhs,rhs,vars}]`, `quantities[{value,unit}]`
  - History: `events[{year,label,text}]`, `start_year`, `end_year`, `era`, `entities[]`
  - Video: `est_duration_s`, `shots[]`. Render jobs also carry
    `kind:"render_job"`, `status`, `scenes[]`, `srt` and `video_file`.
- **System collections:** `Source` (harvest configuration) and `IngestLog` (errors).

Full shapes are in `contracts/*.schema.json`.

### FQL dialect reference

```
// sets (lazy), arrays, projection
Language.all()                                  Language.where(.pos == "noun")
History.search("printing press").take(5)        Stem.byId("731498193449157449")
History.all().order(.start_year, desc(.title))  Language.firstWhere(.term == "lucid")
History.where(.start_year < 0) { title, start_year, span: .end_year - .start_year }
Stem.all().flatMap(.formulas).map(.expr).distinct()

// lambdas and let
let modern = History.where(.era == "Modern")
modern.map(d => d.title + " (" + d.start_year + ")")

// writes (CLI --write, or "allow writes" in the hub console)
Language.create({ term: "lucid", pos: "adjective", definition: "clear" })
Language.firstWhere(.term == "lucid").update({ pos: null })      // null removes a field
Source.create({ kind: "feed", url: "https://…/rss", domain: "history", interval: 600 })

Collection.all()                                // collections and counts
```

| Category | Supported |
|---|---|
| Collection | `all where firstWhere byId search(text[, limit]) create count` |
| Set / Array | `where map flatMap order take drop first last firstWhere count isEmpty nonEmpty includes any every distinct reverse concat toArray toSet` |
| Document | field access, `.id .coll .ts`, `update replace delete exists` |
| String | `.length includes startsWith endsWith toLowerCase toUpperCase trim split slice` |
| Expressions | `== != < <= > >= && \|\| ! + - * / %`, `asc()/desc()`, `.field` shorthand, `x => …`, `(a, b) => …`, `let`, `[…]`, `{…}`, `// comments` |

The dialect is lenient where harvested data is messy. A missing field reads as
`null`, comparisons against `null` are false, and `null.field` is `null`.
Errors carry a stable `code` and a character `pos`: `syntax_error`, `type_error`,
`unbound_variable`, `invalid_field_access`, `invalid_method`,
`invalid_argument`, `divide_by_zero`, `readonly`.

`search()` is QueryBook's extension: BM25-ranked full-text search with stopwords
dropped and titles weighted 4×. Stock Fauna FQL has no full-text search.

Every domain answer lists the exact FQL it ran, and each UI shows it in the
"FQL used" panel.

## 3. Continuous and real-time harvesting and ingestion

| Path | Latency | How |
|---|---|---|
| Drop folder | about 1 s | `FolderSource` polls `inbox/` every second, using stdlib polling that behaves the same on NTFS, APFS and ext4. A file in `inbox/history/` is filed under History; files elsewhere are auto-classified. Formats: `.txt .md .json .jsonl .csv`. Files still being written (modified under 0.4 s ago) are skipped until they settle. |
| Feeds | per source | `FeedSource` reads RSS 2.0 and Atom. Remembering entry ids means each entry is ingested once. |
| Runtime config | ≤5 s | The harvester re-reads the `Source` collection every 5 s. Creating a feed document from any FQL console starts harvesting it, and deleting or disabling the document stops it. No restart. |
| Push | immediate | `POST /api/ingest` with one item or an array of up to 1000. The hub has a form for it. |
| CLI batch | immediate | `querybook ingest <files or folders> [--domain d]` |

**Pipeline:** NFC normalisation and invisible-character stripping, then a
content hash (which makes re-ingestion a no-op), then the classifier (lexicon
scores plus a years heuristic; a hint from the folder or the request wins),
then that domain's `enrich()`, then `store.create()`. Each write appends to the
change journal.

**Real-time delivery:** `GET /api/stream?coll=&since=` is Server-Sent Events
tailing the journal. Every page subscribes to it:

- The hub's live feed and document counts update on every change.
- A domain page shows "N new documents arrived since this answer — Refresh answer".
- Video Studio's render-job panel moves through `rendering` to `rendered` live,
  then shows the player.

Resume after a disconnect uses `Last-Event-ID`.

**Failure isolation:** a broken feed records `last_error` (shown in the hub's
Harvesters table) and an `IngestLog` document. It never stops the other sources.

## 4. Domain-specific user interfaces

All five pages are plain HTML, CSS and JavaScript served by the local server,
with no CDN, so they work offline. They support light and dark mode and
reflow down to phone width. Each domain page has the same frame: ask box,
example chips, live banner, a Sources panel and an "FQL used" panel. The answer
area in the middle is built for that domain's answer:

- **Language:** a dictionary card in serif type, with a large headword,
  italic part of speech and numbered senses. Below it are "In use" quotations
  with the word highlighted and tagged by the collection they came from, then
  related-word chips that re-query on click.
- **STEM:** a large monospace result (`F = m * a = 686.7`), a numbered list of
  worked steps (`m = 70`, `70 × 9.81 = 686.7`), a formulas table (formula,
  variables, source), a quantities table and subject tags. The evaluator is a
  safe AST walker: numbers, operators, parentheses, standard functions and the
  constants pi, e, tau, g and c; `^`, `×`, `÷`, `²`, `√` and `2x` are accepted.
- **History:** era bands (Ancient, Medieval, Early modern, Modern,
  Contemporary) with spans and counts, above a vertical timeline with year
  markers. Understands "1750 to 1850", "44 BC", "the 1960s", "20th century",
  "after 1900".
- **Video Studio:** a scene-timing strip, a 16:9 storyboard grid (timecode,
  heading, narration, visual brief), the `.srt` captions, and a render panel
  that renders, shows live status and plays or downloads the MP4. Rendering
  uses ffmpeg if it is installed: H.264 with a soft caption track, and text
  cards when a system font is found (Segoe UI or Arial on Windows, Arial or
  Helvetica on macOS). Without ffmpeg, the storyboard and captions still work
  and the UI says how to install it.
- **Hub:** "Ask every app" sends one question to all apps side by side, with a
  one-line answer from each and links to the full views. It also has app tiles
  with live document counts, the FQL console (examples, write toggle,
  Ctrl/⌘+Enter), the push-ingest form, the live change feed and the harvester
  status table.

## 5. Windows and macOS

- **Pure standard library**, Python 3.10 or newer (tested on 3.10 to 3.13).
  The same code runs on Windows 10/11 and on macOS on Apple silicon or Intel.
  There are no compiled dependencies to install.
- **Data folder:** set by `data_folder` in `querybook.ini`, next to the
  launchers. It ships set to `D:\QueryBook`. If it is left blank, Windows uses
  `D:\QueryBook` when a D: drive exists, otherwise `%LOCALAPPDATA%\QueryBook`;
  macOS uses `~/Library/Application Support/QueryBook`. `--home` and
  `QUERYBOOK_HOME` override all of these.
- **Existing data stores:** `watch_folders` in `querybook.ini` lists folders
  that already hold your material (for example on D:). The harvester reads them
  continuously and read-only: it never writes, moves or deletes anything there,
  and it skips files over 20 MB.
- **Launchers:** `run_windows.bat` (uses `py -3` or `python`) and
  `run_mac.command` (double-click in Finder). Both start the hub and open the
  browser.
- **Platform details handled:** `pathlib` everywhere; Windows drive colons
  escaped in ffmpeg filter paths; no console window flashing during renders
  (`CREATE_NO_WINDOW`); the server binds to `127.0.0.1` only.
- **Packaging (next step):** `pip install .` gives a `querybook` command (see
  `pyproject.toml`). For a double-click app, use PyInstaller or Briefcase on
  each OS: `pyinstaller -n QueryBook --add-data "querybook/ui:querybook/ui" …`.

## 6. Rust readiness

The Python code is written so each module can be ported on its own, with no
change visible to callers:

1. **Plain data at every boundary.** Frozen dataclasses and JSON values only;
   no Python objects cross a seam. Each record has a matching Rust struct in
   `rust/querybook-core/src/contracts.rs` and a JSON Schema in `contracts/`.
2. **Protocols as traits.** `core/interfaces.py`'s `DocumentStore` and `Source`
   are mirrored by Rust traits with the same method set.
3. **Errors are values with stable codes,** never strings to parse
   (`FQLError.code`, `StoreError.code`), so they map onto Rust enums.
4. **One AST node per frozen dataclass** (`core/fql/ast.py`), which maps onto a
   Rust `enum Node`. The parser is hand-written recursive descent with no
   regular expressions or parser generators, so it ports line for line.
5. **Determinism is tested across languages.** `contracts/golden_text.tsv` is
   generated from Python and checked by both `cargo test` and the Python suite.
   When the Rust binary is built, the Python suite also pipes the vectors
   through it. The lexicons are one file that both sides read
   (`include_str!` in Rust).

**Already ported (std-only crate, `cargo test` passes):** the text kernel
(normalise, tokenize, FNV-1a, content hash, classify) and the FQL lexer,
including character positions and the newline rule.

**Migration order:**

| Step | Port | Rust crates | Python change |
|---|---|---|---|
| 1 ✅ | text kernel, FQL lexer | std | none (parity-tested) |
| 2 | FQL parser + evaluator | std | `core/fql` → PyO3 `querybook_core.run_fql` |
| 3 | document store | `rusqlite` (bundled) or `redb` | `FQLStore` → PyO3 class with the same methods |
| 4 | harvester + pipeline | `notify` (native file events), `reqwest`, `feed-rs` | `ingest/` → background Rust service |
| 5 | server | `axum` + SSE | optional; the Python server keeps working |

Ship as a PyO3/maturin extension (`cdylib`). The dependency block is already
written into `Cargo.toml`, commented out. If `import querybook_core` fails, the
Python reference implementation stays as the fallback. The NFC step is the one
kernel function waiting on a crate (`unicode-normalization`).

## 7. Security and safety

- Listens on `127.0.0.1` by default. Expose it on a network only behind your
  own reverse proxy and authentication.
- FQL from the browser is read-only unless the request sets `write: true`. Each
  app's own queries run read-only; Video Studio's job writes go through the
  store directly.
- The STEM evaluator never calls `eval`. It walks an allowlisted AST and caps
  exponents and factorials.
- Static and render routes resolve the path and refuse anything outside their
  folder; there is a traversal test for this.
- The UI builds every element with `textContent` (no `innerHTML`), so harvested
  text cannot inject markup.
- Feeds are fetched with a 20 s timeout and a 5 MB cap; request bodies are
  capped at 5 MB.

## 8. Known limits of the prototype, and next steps

- **Queries scan.** `where()` reads the whole collection, which is fine up to
  about 100k documents. Next: field indexes, plus pushing `where`/`order` down
  into the store (part of Rust step 3).
- **Enrichment is heuristic** (regexes and lexicons): deterministic, offline and
  free, but shallow. A model-backed enrichment pass can slot into
  `DomainApp.enrich()` per domain.
- **Video narration is text only.** Next: system TTS (`say` on macOS, SAPI on
  Windows) for a voice track, plus images.
- **No accounts or multi-user permissions.** It is a single-user desktop
  prototype.
