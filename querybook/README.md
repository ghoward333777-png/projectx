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
   qb -c qb.toml ingest --manifest library.csv --engines rules        # free, runs entirely on your server
   qb -c qb.toml ingest --manifest library.csv --engines rules,claude --replace   # higher-quality records
   ```

   One failing book does not stop the run; each book prints a JSON report
   (records admitted, refused, unverified quotes, tokens used, ledger node).

## Extraction engines

Engines run only at ingestion, never on the query path. Each is a registered
source class: two engines agreeing on a fact raise its diversity; one engine
repeating itself does not (QBF-C023). Configure them in the TOML:

| id | kind | where it runs | notes |
|---|---|---|---|
| `rules` | built in | your server, no network | Deterministic baseline. Good at names, speech, appositives, "X was a …", events; weaker at pronoun-only sentences. |
| `claude` | Anthropic API | Anthropic | Model `claude-opus-5`, JSON-schema output, server-side refusal fallback (`fallbacks: "default"`). Needs `ANTHROPIC_API_KEY`. |
| `local` | OpenAI-compatible | **your own server** (vLLM, Ollama, llama.cpp, TGI…) | Set `base_url` and `model`. Same prompt and conversion as Claude. |

Model output is converted record by record (QBF-C021): ungoverned predicates
are refused; every quoted span is checked against the passage it cites
(QBF-C024) and a record whose span does not resolve is admitted *marked
unverified* and excluded from answers; every record carries the engine and the
prompt hash (QBF-C022). Both model engines were tested against a mock of each
API; they have not yet been run against the live services from this
environment.

## Importing the UFCS fact feed (149 million facts)

1. Copy [config/ufcs-mapping.example.toml](config/ufcs-mapping.example.toml) and
   point its JSON pointers at your envelope fields (subject, predicate, object,
   evidence α/β or confidence+weight, certification, provenance, links, text).
   Set the API URL, auth header and pagination (cursor or offset).
2. Dry-run against a sample: `qb import-ufcs --mapping feed.toml --file sample.ndjson --dry-run`
   — prints admitted/refused counts with sample reasons, writes nothing.
3. Run it: `UFCS_TOKEN=… qb import-ufcs --mapping feed.toml`. It is resumable:
   the cursor is saved after each committed page; re-running continues.

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

## Command reference

| command | purpose |
|---|---|
| `qb ingest <files/dirs> --rights R [--engines rules,claude] [--manifest m.csv] [--replace]` | add books |
| `qb estimate <files> --engine claude` | requests, tokens, cost before spending |
| `qb ask <work> "<question>" [--mode who\|recap\|summary\|timeline\|explore\|flashcards\|quiz] [--at POS] [--world] [--json]` | query from the terminal |
| `qb import-ufcs --mapping m.toml [--file f.ndjson] [--dry-run] [--limit N]` | import a UFCS feed |
| `qb bench-synthetic --facts N` | measure import and query at scale on this machine |
| `qb export-qbf <work> out.qbf` | a work's records as a QBF frame stream (offline/compact) |
| `qb verify` | verify the whole ledger (links, keyed checksums, signatures) |
| `qb stats` · `qb user` · `qb grant` · `qb serve` | operations |

## Tests

```bash
cargo test --release     # 19 unit + 8 end-to-end invariant tests
```

The invariants cover determinism under the context lock, the structural
spoiler bound, owner-only annotations, ledger verification and denied
transfers, pre-computed answer invalidation on revision, citation resolution
against the source text, and UFCS re-validation/corroboration.

## Known limits of this prototype

* The `rules` engine is a baseline; answer quality with it reads like
  well-chosen quotations. Claude or your own model produces properly atomic
  records ("Mr. Collins is the heir of the Longbourn estate").
* Concept identity across books and between books and UFCS is by label only;
  there is no cross-corpus ontology alignment yet.
* The attractor network, traversal budget and competitive candidate resolution
  are implemented digitally; analog realization (QBF-C070..C073) is out of
  scope.
* Features outside the reading slice (robotics, VR/3D, commerce, agents,
  forecasting, colorization, cyber-defence…) are not implemented; FEATURES.md
  lists them.
