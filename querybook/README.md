# QueryBook prototype

A working prototype of QueryBook: a Kindle-style e-reader where a reader asks the
book questions and every answer is built **only from the book's own Fact Units**,
cites the passage behind each sentence, and never reaches past the page the
reader is on. Written in Rust as one self-contained binary (`qb`) for an Ubuntu
server. The source of truth for features is the QueryBook Feature Registry v65
(293 features); doctrine follows the QueryBook Master Bible. See
[FEATURES.md](FEATURES.md) for the feature-by-feature map.

```
 EPUB/DOCX/TXT ─┐                                   ┌─ Kindle-style reader (web, phone, tablet)
 UFCS feed ─────┤ D1 extract → D0 safety → D3 validate → D2 store ─┐   │  ask · who's who · recap · timeline
 (149M facts)   │  rules │ Claude │ your own LLM server               │   │  flashcards · quiz · notes · highlights
                └────────────────────────────────────────────────────┘   │
                        signed hash-linked ledger (Merkle per batch)      │
 reader ── D9 ── D8 scope (entitlement + reading position) ── D4 FQL ── attractor ── D7 grounded text ── citations
```

## What it does today

* **Reader simulation.** Paginated e-ink style reader with an optional device
  frame, location/percentage/time-left footer, page-turn by tap, swipe or keys,
  Paper/Sepia/Night themes, text size, margins, line spacing, highlights in four
  colours, private notes, contents with the unread part greyed out. Works on
  desktop and phones (the QueryBook panel becomes a bottom sheet).
* **QueryBook panel.** Free questions plus one-tap Who's who, Story so far, This
  chapter, Timeline, Flashcards (spaced repetition) and Quiz. Every sentence
  carries citation numbers; tapping one previews the source quote, location,
  confidence, trust, engine and verification without a new query, and jumps to
  the passage. "Inspect record" shows the full Fact Unit, its ledger node and a
  verified Merkle inclusion proof. "Why this answer" shows the FQL that ran, the
  attractor convergence, the context-lock key and the output hash.
* **Spoiler shield.** The reader's scope is bounded by the furthest point read
  *before* retrieval: later records are not traversable at all. If the answer is
  later in the book the reader is told so, without content. (Authors,
  instructors and researchers are exempt, per QBF-C196.)
* **Honest failure.** "The book doesn't say" when nothing grounded exists;
  clarification when a name is ambiguous; records whose quoted span cannot be
  found in the book are kept and disclosed but never ground an answer.
* **Determinism.** Same question + same context-lock key ⇒ byte-identical
  answer (tested). The key covers device, entitlement and reading position,
  locale, register, audience, posture, traversal costs, convergence regime and
  the store version.
* **Governance.** Every domain crossing is checked against the D0 transfer
  matrix (absent = deny; D7→D2, D9→D2, D13→D4 … are denied and tested). Writes
  to the substrate need a permit that only a satisfied D1/D5/D8/D10/D12→D2
  conversion can mint. Every admission, election and erasure is a signed,
  hash-linked ledger node with a keyed checksum over the safety evaluation.
* **Privacy.** History is retained by default and erasable per session or
  account; notes are owner-only records; full data export; erasures are
  ledgered without their content.
* **Language pipeline.** Ingestion runs QueryBook's own seven-stage language
  pipeline (below) by default: no model, no network, the same book always
  gives the same records, each anchored to its EPUB CFI and sentence.
* **World knowledge.** Facts imported from UFCS feeds or harvested from
  Wikidata answer questions on their own (the "World knowledge" desk on the
  library page, `qb ask world "…"`) or alongside a book, labelled "outside this
  book".
* **Knowledge lattice.** A structure of general knowledge (20 domains, 158
  classes, 158 slots) that predicts what each fact cell holds before it is
  harvested, then harvests only the open cells and confirms or refutes each
  prediction (below).
* **Admin.** Upload books with a rights declaration, watch ingestion jobs,
  see what readers ask per book (author feedback, with the unanswered ones
  flagged), manage users, see UFCS feeds, verify the ledger.

## Quick start (development)

```bash
cd querybook
cargo build --release                       # Rust 1.80+; produces target/release/qb
cp config/querybook.example.toml qb.toml    # edit data_dir to e.g. ./data
./target/release/qb -c qb.toml ingest ~/books/pride-and-prejudice.epub --rights public-domain
./target/release/qb -c qb.toml ask pride-and-prejudice-bbd82e "Who is Mr. Collins?" --at 1000
QB_ADMIN_PASSWORD='choose-one' ./target/release/qb -c qb.toml serve
# open http://127.0.0.1:8090  — first start creates reader/reader and admin/<QB_ADMIN_PASSWORD>
```

`qb` works while the server is running (ingest, import, ask, verify share the
data directory; the index writer lock is taken only while writing).

## Preparing your library (tonight)

1. **Formats.** EPUB is best (chapters and paragraphs survive). DOCX, HTML, TXT
   and Markdown work. PDF: convert first (`ebook-convert book.pdf book.epub`
   from Calibre) so paragraphs survive. Kindle files (AZW/AZW3/KFX/MOBI) are
   DRM-protected and cannot be ingested: use a DRM-free EPUB of a work you hold
   the rights to.
2. **Rights.** Every book needs a declaration: `public-domain`, `author-owned`,
   `licensed` or `publisher-licensed`, plus an optional note (Gutenberg number,
   contract reference). Public-domain works are open to every reader; others
   are granted per reader (`qb grant <user> <work>`).
3. **Manifest.** Put the files in one folder and list them in a CSV
   (see [config/library-manifest.example.csv](config/library-manifest.example.csv)):

   ```csv
   path,rights,rights_note,genre,id
   austen-pride.epub,public-domain,Gutenberg #1342,fiction,
   my-novel.docx,author-owned,,fiction,my-novel
   ```
4. **Estimate, then ingest.**

   ```bash
   qb -c qb.toml estimate --manifest library.csv --engine claude     # requests, tokens, $ — spends nothing
   qb -c qb.toml ingest --manifest library.csv                        # language engine: free, on your server
   qb -c qb.toml ingest --manifest library.csv --engines language,rules,claude --replace   # higher-quality records
   ```

   One failing book does not stop the run; each book prints a JSON report
   (records admitted, refused, unverified quotes, tokens used, ledger node).

## Extraction engines

Engines run only at ingestion, never on the query path. Each is a registered
source class: two engines agreeing on a fact raise its diversity; one engine
repeating itself does not (QBF-C023). Configure them in the TOML:

| id | kind | where it runs | notes |
|---|---|---|---|
| `language` | built in (default) | your server, no network | The seven-stage language pipeline below. Relations ("Elizabeth is the wife of Mr. Darcy"), traits with negation, speech attribution, conservative pronoun resolution. |
| `rules` | built in | your server, no network | Deterministic pattern baseline. Agreeing with `language` raises a record's diversity (two methods, two source classes). |
| `claude` | Anthropic API | Anthropic | Model `claude-opus-5`, JSON-schema output, server-side refusal fallback (`fallbacks: "default"`). Needs `ANTHROPIC_API_KEY`. |
| `local` | OpenAI-compatible | **your own server** (vLLM, Ollama, llama.cpp, TGI…) | Set `base_url` and `model`. Same prompt and conversion as Claude. |

Model output is converted record by record (QBF-C021): ungoverned predicates
are refused; every quoted span is checked against the passage it cites
(QBF-C024) and a record whose span does not resolve is admitted *marked
unverified* and excluded from answers; every record carries the engine and the
prompt hash (QBF-C022). Both model engines were tested against a mock of each
API; they have not yet been run against the live services from this
environment.

## The language pipeline (ingestion)

QueryBook learns a text through deterministic stages before anything is
queried (`src/d1/language/`):

| stage | what happens | where |
|---|---|---|
| 1 Segmentation | paragraphs, sentences, clauses (main, coordinate, subordinate, relative with antecedent, reported speech) | `d1/parse.rs`, `d1/segment.rs`, `language/parse.rs` |
| 2 Parsing | tokens, rule-based UPOS tagging with contextual repair, chunks (NP/VP/PP/ADJP/ADVP), UD-style dependencies | `language/tag.rs`, `language/parse.rs` |
| 3 Entities & relations | named entities (people, places, organisations), dates, quantities, acronyms; verb-class predicate classification | `language/ner.rs` |
| 4 Fact Unit construction | subject–predicate–object with semantic type (event, description, attribute, relation, state, speech, claim) onto governed predicates | `language/construct.rs` |
| 5 Anchoring | each record carries its EPUB CFI (`epubcfi(/6/4[idref]!/4/64)`), paragraph position, spine item and sentence number | `d1/parse.rs` |
| 6 Embedding | random-indexing vectors (128-d, no training): record + context window + graph alignment; concept vectors stored per work | `language/embed.rs` |
| 7 QBE integration | the question is embedded in the same space; semantic closeness raises a candidate's attractor bias, after scope resolution | `d4/query.rs` |

`qb analyze book.epub --from 120 --limit 5` prints every stage for a few
sentences (tokens/POS, clauses, trees, dependencies, entities, facts).

## World knowledge from Wikidata

`qb harvest-wikidata --pack config/harvest/wikidata-basics.toml --import config/harvest/wikidata-mapping.toml`
runs a pack of SPARQL queries (geography, science, mathematics, engineering,
history — 55 queries, ~21,000 facts) politely against the Wikidata Query
Service, writes each query's results as UFCS envelopes (resumable per query),
and imports them through the ordinary D1 path. Wikidata is CC0. Set `contact`
in the pack to a way Wikimedia can reach you (it goes in the User-Agent).

## The knowledge lattice (structure first, facts later)

Instead of harvesting the world query by query, QueryBook first lays down a
**lattice**: [config/lattice/knowledge-lattice.toml](config/lattice/knowledge-lattice.toml)
names 20 domains → 58 subdomains → 158 classes (each a Wikidata class plus a
notability floor), and [slots.toml](config/lattice/slots.toml) names the 158
attributes a member can carry. Every (member × slot) pair is a **cell**. The
structure was drafted with AI and every id was checked live against Wikidata.

```bash
qb lattice validate --live      # structure + every Q-/P-id exists with the right datatype
qb lattice census               # members per class + how often Wikidata fills each slot
qb lattice expect               # predict cell values from the lattice's rules
qb lattice fill --budget 300 --import config/harvest/wikidata-mapping.toml
                                # harvest only open cells, then confirm every prediction
qb lattice report               # coverage, rule precision, calibration, work remaining
qb lattice predict --engine claude --only people.physicist   # optional: a model recalls open cells
qb lattice propose --engine claude --domain astro --out astro-proposal.toml   # optional: extend the structure
```

How the prediction speeds the harvest up:

* **Presence is known in advance.** The census says, per class, how often each
  slot is filled (every sovereign state has a capital, 64 % of elements have a
  discoverer). Cells are expected before any value is fetched, and a column
  that is 0 % filled is never queried.
* **Values are predicted by regularities** (`[[rule]]`): inverse relations (a
  country's capital lies in that country), symmetry (borders), chains (a city's
  continent is its country's continent), constants (planets orbit the Sun) and
  class modes (a value shared by ≥ 80 % of observed members). Predictions made
  for cells already observed are measured at once, so every rule's precision is
  known before its forecasts are trusted.
* **Fetching is targeted.** `fill` asks only for open cells, `batch` members
  per query (`VALUES`), instead of scanning whole classes (which times out on
  large classes). Columns carrying forecasts from still-uncertain rules go
  first — each outcome there changes what the lattice believes most — then
  columns by expected facts per query.

Predictions are D5 expectations (QBF-C102): they live beside the fact store,
never in it (induction may not write). A refuted prediction is attributed to the
lowest level that explains it — a multi-valued premise is a conceptual error,
not a broken rule (QBF-C103/C104); a refutation by a contested record revises
nothing and is kept as a finding (QBF-C105). Per-band calibration gaps become
proposals to the operator, never automatic changes (QBF-C101). A model's
predictions are the least trusted level and are compared by normalized name.

## Importing the UFCS fact feed (149 million facts)

1. Copy [config/ufcs-mapping.example.toml](config/ufcs-mapping.example.toml) and
   point its JSON pointers at your envelope fields (subject, predicate, object,
   evidence α/β or confidence+weight, certification, provenance, links, text).
   Set the API URL, auth header and pagination (cursor or offset).
2. Dry-run against a sample: `qb import-ufcs --mapping feed.toml --file sample.ndjson --dry-run`
   — prints admitted/refused counts with sample reasons, writes nothing.
3. Run it: `UFCS_TOKEN=… qb import-ufcs --mapping feed.toml`. It is resumable:
   the cursor is saved after each committed page; re-running continues.

**The QueryBook UFCS format** (the Prototype Test Kit's record layout) has a
ready mapping: [config/ufcs-mapping.querybook.toml](config/ufcs-mapping.querybook.toml).

```bash
qb import-ufcs --mapping config/ufcs-mapping.querybook.toml --file ufcs_sample.jsonl --dry-run
qb import-ufcs --mapping config/ufcs-mapping.querybook.toml --file ufcs_sample.jsonl
qb ask world "What is the capital of France?"
```

On the kit's 242 records: 162 assertions admitted, 80 restatements merged as
corroboration, 0 refused; re-importing changes nothing. Each record's
`semantic_fingerprint` is recomputed on arrival and a record altered in transit
is refused. Polarity `-` is a refutation ("It is not the case that Pluto is a
planet"). Each source class in `sources[]` is its own class, so agreement across
classes raises diversity and trust. Members of an `UNRESOLVED` contradiction
cluster are marked contested, and all 8 seeded clusters answer with the
higher-trust member. Only `PUBLIC` records are readable by readers. Asked one
question per assertion, 140 of 144 first answers are right. The kit is kept as
a regression test (`tests/data/ufcs_sample.jsonl`).

For the 149M feed, fill in `[source]` in that mapping with the bulk endpoint
(URL, auth, cursor or offset paging). The contract documents `POST /v1/query`
but no paged export yet.

Envelopes are re-validated on arrival (schema, governed predicate — unseen
predicates are registered and ledgered — safety, optional identity check). A
canonically identical assertion is merged as corroboration into the immutable
adjustment history instead of being stored twice. Readers switch imported
knowledge on per question ("World knowledge"); citations from it are labelled
"outside this book".

**Measured on this 4-core build box** (synthetic UFCS-shaped records, real
import path): 2,000,000 records at ~19–20k records/s sustained (13k/s including
the final index merge); FQL retrieve+load p50 9.3 ms / p95 9.9 ms at 2M
records; 988 bytes per record on disk (zstd-compressed QBF frames + index).
**Projected for 149M**: ≈150 GB disk and several hours of import on 4 cores
(less with more cores and NVMe). Query latency at 149M is a projection, not a
measurement; run `qb bench-synthetic --facts N` on the target server to measure.

## Deploying on Ubuntu

```bash
sudo bash deploy/install.sh        # builds, installs /usr/local/bin/qb, creates the querybook user,
                                   # /etc/querybook, /var/lib/querybook and a systemd unit
sudoedit /etc/querybook/env        # QB_ADMIN_PASSWORD, ANTHROPIC_API_KEY, UFCS_TOKEN
sudo systemctl enable --now querybook
```

Put nginx (or Caddy) with TLS in front — see [deploy/nginx.conf](deploy/nginx.conf).
Back up `/var/lib/querybook` (it holds the store, the index and the ledger keys).
Change the demo passwords with `qb user reader --password …`.

## Backups to Google Drive

The facts, index and ledger stay on the server's disk, where answers are fast.
Each night a backup is written, encrypted with your passphrase, uploaded to a
"QueryBook backups" folder in your Google Drive, and the newest 7 are kept.
Only you can read the backups: Google stores ciphertext, and QueryBook's access
to your Drive is limited to the files it created itself (`drive.file` scope).

**One-time setup (about 10 minutes, in a browser):**

1. Go to <https://console.cloud.google.com/>, create a project (e.g. "QueryBook"),
   and under *APIs & Services → Library* enable the **Google Drive API**.
2. *APIs & Services → OAuth consent screen*: choose **External**, fill in the app
   name and your email, add the scope `.../auth/drive.file`, then **Publish app**
   (status "In production"). `drive.file` needs no Google review. Apps left in
   "Testing" have their authorisation expire after 7 days.
3. *APIs & Services → Credentials → Create credentials → OAuth client ID*,
   application type **TVs and Limited Input devices**. Copy the client ID and secret.
4. On the server, add to `/etc/querybook/env`:

   ```
   QB_BACKUP_PASSPHRASE=a long passphrase you also keep somewhere safe
   QB_DRIVE_CLIENT_ID=….apps.googleusercontent.com
   QB_DRIVE_CLIENT_SECRET=…
   ```
5. Authorise once. It prints a short code; enter it at google.com/device on
   your phone, signed in to the Google account whose Drive should hold the backups:

   ```bash
   sudo systemd-run --pty --uid=querybook -p EnvironmentFile=/etc/querybook/env \
     /usr/local/bin/qb -c /etc/querybook/querybook.toml drive-auth
   sudo systemctl enable --now querybook-backup.timer      # nightly at ~03:17
   sudo systemctl start querybook-backup                   # one now, to check
   ```

**Restore** (into a new, empty directory; the ledger is verified before you use it):

```bash
qb backup --list                                            # backups in Drive
qb restore --from-drive latest --into /var/lib/querybook-restored
qb restore --file querybook-20260925-031700.qbk --into /var/lib/querybook-restored
```

**What a backup is.** The snapshot is consistent: no import can commit while it
is taken. It contains the database, the search index and the ledger keys,
compressed with zstd, then encrypted with XChaCha20-Poly1305 using a key derived
from the passphrase (Argon2id). Any altered, reordered or truncated byte is
detected, and a wrong passphrase is refused. Every backup and upload is recorded
in the ledger.

**Size.** For 149M facts expect a ~60–80 GB backup and a Google One 2 TB plan.
Uploads resume after interruptions. The local copy is deleted once the upload's
size matches; use `--keep-local` to keep it. Without Drive, `qb backup --out DIR`
writes encrypted backups locally.

**Keep the passphrase outside the server** (password manager, printed copy).
It is the only way to open a backup, and it is not stored in Drive.

## Command reference

| command | purpose |
|---|---|
| `qb ingest <files/dirs> --rights R [--engines rules,claude] [--manifest m.csv] [--replace]` | add books |
| `qb estimate <files> --engine claude` | requests, tokens, cost before spending |
| `qb ask <work> "<question>" [--mode who\|recap\|summary\|timeline\|explore\|flashcards\|quiz] [--at POS] [--world] [--json]` | query from the terminal |
| `qb import-ufcs --mapping m.toml [--file f.ndjson\|dir] [--dry-run] [--limit N]` | import a UFCS feed (file or directory) |
| `qb harvest-wikidata [--pack p.toml] [--only geography,...] [--import mapping.toml]` | harvest a Wikidata query pack |
| `qb lattice validate\|census\|expect\|fill\|confirm\|report\|predict\|propose` | the knowledge lattice |
| `qb analyze book.epub [--from POS] [--limit N] [--json]` | show the language pipeline's stages |
| `qb ask world "<question>"` | ask the imported world knowledge alone |
| `qb bench-synthetic --facts N` | measure import and query at scale on this machine |
| `qb export-qbf <work> out.qbf` | a work's records as a QBF frame stream (offline/compact) |
| `qb verify` | verify the whole ledger (links, keyed checksums, signatures) |
| `qb backup [--drive] [--keep 7] [--list]` · `qb restore --from-drive latest\|--file F --into DIR` · `qb drive-auth` | encrypted backups (Google Drive) |
| `qb stats` · `qb user` · `qb grant` · `qb serve` | operations |

## Tests

```bash
cargo test --release     # 34 unit + 12 end-to-end invariant tests
```

The invariants cover determinism under the context lock, the structural
spoiler bound, owner-only annotations, ledger verification and denied
transfers, pre-computed answer invalidation on revision, citation resolution
against the source text, UFCS re-validation/corroboration, the language
pipeline (same book ⇒ same records, CFI anchors and vectors) and the lattice
cycle (predict → harvest → confirm/refute with attribution, nothing predicted
ever written as fact).

## Known limits of this prototype

* The `language` and `rules` engines are deterministic and free, but they read
  like a careful parser, not a reader: some descriptions come out awkward.
  Claude or your own model produces properly atomic records ("Mr. Collins is
  the heir of the Longbourn estate"); run them together for diversity.
* The lattice reads only the facts about its own members (in batches through
  the index), so its memory grows with the lattice (~300k members), not with
  the size of the fact store.
* Concept identity across books and between books and UFCS is by label only;
  there is no cross-corpus ontology alignment yet.
* The attractor network, traversal budget and competitive candidate resolution
  are implemented digitally; analog realization (QBF-C070..C073) is out of
  scope.
* Features outside the reading slice (robotics, VR/3D, commerce, agents,
  forecasting, colorization, cyber-defence…) are not implemented; FEATURES.md
  lists them.
