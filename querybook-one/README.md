# QueryBook (one window)

The new version of QueryBook, built from the QueryBook suite itself, so every feature it has keeps working:

- Language Builder: translation, speech, avatars, lip reading and the rest.
- Math, Science & Engineering.
- History & News.
- Video Studio.
- The Control Panel's harvesting.

They now open in **one window**, with one start file and Python inside.

Stage 1 of the rebuild planned in `docs/querybook-rebuild/` (the 407-feature inventory and screen blueprint).

## For the user

1. Unzip `QueryBook.zip`.
2. Close the old QueryBook windows; they use the same data and the same ports.
3. Double-click `START-QueryBook.bat`.

Your data stays on `D:\QB`, as named in `data-folder.txt`, following the same rule as the suite. If the drive isn't connected, nothing starts.

## What's here

| Folder | What it is |
|---|---|
| `apps/` | The suite's applications (from `claude/lucid-brahmagupta-ak4f6m`, Control Panel 1.36) plus `shell/`, the one window |
| `apps/shell/` | Starts every application in the background, follows `data-folder.txt`, and serves the window with its area rail, role switch and Ask box (`ask.py`) |
| `apps/_core/qbmath.py` | The network-memory and routing arithmetic as pure functions; `qbsynapse` and `qbdsn` call it |
| `lean/` | Lean 4 + Mathlib proofs; see below |
| `rust/qbcore/` | Rust port: every STEM formula, `qbmath`, and Python's exact `round()` |
| `tools/` | `gen_lean.py` and `gen_rust.py` generate the proofs, the Rust formulas and the test vectors from the Python; `build_bundle.py` builds `QueryBook.zip` |
| `tests/` | Ask logic, Lean/Rust kept in step with the Python, and the Rust-compatibility guard |

## Book Query and the sample-ebook library

QueryBook was designed to give anchored answers about one ebook. **📚 Book Query** (left rail, under Ask, for every role; also the button at the top of the Ask page) does that for a library of 19 public-domain books (`apps/shell/library/`): step 1 choose a book (search, nonfiction / fiction / book-vs-today filters), step 2 ask it — suggested questions grouped by what the book can answer, earlier questions, the contents (read any chapter, every sentence a Fact Unit), answers quoted with their anchors. A newer QueryBook closes an older copy still running (which kept the browser on the old version); the version shows beside the name.

- **Nonfiction:** Gibbon, *Decline and Fall*; Smith, *Wealth of Nations*; Plato, *Republic*; Machiavelli, *The Prince*; Marcus Aurelius, *Meditations*; Sun Tzu, *The Art of War*; Thoreau, *Walden* and *Civil Disobedience*; Douglass, *Narrative*; Comstock, *A Text-Book of Astronomy*.
- **Fiction:** *Pride and Prejudice*, *Frankenstein*, *Moby-Dick*, *Alice in Wonderland*, *The Adventures of Sherlock Holmes*, *Dracula*, *A Tale of Two Cities*, *The Count of Monte Cristo*, *War and Peace*, *Tom Sawyer*.

Each book has four layers:

1. **Original text** (`text.txt.gz`): the public-domain text only, with the Project Gutenberg header, licence and trademark removed, so it is a QueryBook edition. `meta.json` keeps the provenance (Gutenberg number, address, date fetched) and the rights note, including that Project Gutenberg does not endorse it.
2. **Fact and narrative units** (`book.json.gz`, built by `tools/build_library.py`, deterministic, `--check` in the tests):
   - every sentence is a Fact Unit with a fingerprint (`FU-…`) and its part, chapter, § and ¶ anchor;
   - each unit has a kind: definition, measurement (with its quantities), law, observation, procedure, assertion, note or table;
   - for fiction, the curated characters and their aliases, appearances, families and the co-occurrence network;
   - other proper names, and every year mentioned.
3. **Enrichment** (`modern.json`): each entry is tied by pattern to the exact book sentence it judges, and the build fails if that sentence is not found. It holds what is established today, a status (Confirmed / Refined / Superseded / Incorrect / Historically significant / Historical context), named sources, the relationship and why the claim was reasonable then. Layers so far:
   - Comstock: 27 entries, plus 12 discoveries since 1903;
   - Gibbon: 7;
   - historical context for *War and Peace*, *A Tale of Two Cities* and *Monte Cristo*.
4. **Answer provenance:** every quotation in an answer links to its paragraph in the original text and shows its Fact Unit ID.

`bookq.py` does the answering. It is pure and Rust-ready (in the Rust-compatibility guard), and handles:

- BM25 retrieval over the units, accent-insensitive;
- "since the book was published", "still correct", "current values" and "why was it reasonable then";
- relationship networks, family and character tracing, and fictional vs historical figures;
- timelines, evidence in story order (observed vs deduced), and who narrates.

## How Book Query answers (the answer engine, `_core/qbcompose.py`)

1. **Plan the search.** A model turns the question into the phrases and names the book probably uses ("Why did Thoreau go to the woods?" → "went to the woods", "live deliberately"). It does not answer at this step.
2. **Gather the evidence.** `bookq.evidence()` scores paragraphs, not single sentences: the best unit, coverage of the question's words, chapter and section titles, character aliases with or without accents, and reasons for "why" questions. The best paragraphs are numbered P1, P2, … (B2-P3 when several books are asked).
3. **Compose the answer.** Claude (`claude-opus-5-5`, structured JSON output, refusals fall back server-side), else Gemini. The model answers the exact question first, then gives the supporting points; for several books, what each book says and where they agree or differ. Every sentence cites its passages.
4. **Verify.** A sentence citing a passage it was not given, or sharing no real words with what it cites, is removed. Nothing uncited survives. "Not in the book" is a valid answer.

Without a key, the rules answer (`bookq.compose_rules`). They pick the sentence that fits the question's type: a number for "how far", a date for "when", a reason for "why", "X is …" for "what is X". The sentence is quoted unchanged. Book Query uses the Claude or Gemini key saved in the Control Panel (Harvesting → API keys), with a switch on the page.

Measured on hard questions across seven books, the passage holding the real answer was in the evidence for three of seven without a search plan, and for seven of seven with one, usually as P1:

- Thoreau's "live deliberately";
- Elizabeth's "a most beloved sister";
- Ishmael's "escaped alone";
- the Red-Headed League's tunnel;
- Natásha marrying Pierre;
- "safer to be feared than loved";
- justice as minding one's own business.

**Several books at once.** Book Query → "📚 Ask several books at once": pick two to eight books, ask once. Each book is searched separately, and the answer gives each book's view with citations to its book, chapter and paragraph. Questions that ask for a list (networks, family tracing, timelines, "what changed since the book", evidence in story order) keep their exact list answers.

## Book Harvester (Control Panel → Books, `#books`; rail: Operate → Book Harvester)

`_core/qbbooks.py` is the Harvesting Engine's book and document pipeline:

source → harvester → rights gate → metadata → format normaliser → document structure → Fact Units → Book Query

| # | Source | Status | How |
|---|---|---|---|
| 1 | Project Gutenberg | active | Its machine-readable catalog (`pg_catalog.csv.gz`, cached weekly) is filtered by type, language, subject and bookshelf, then ranked by downloads (OPDS search). The plain text is downloaded at a 2-second pace. A header marked "copyrighted" is refused. |
| 2 | Internet Archive | active | Scanned documents: the advanced-search API and the item's OCR text, cleaned (hyphenation, page numbers). An item is ingested only if published in 1930 or earlier; otherwise it is held. The item's licence field is recorded but not trusted (it labels Gutenberg texts "GPL"). |
| 3 | HathiTrust | research only | Approved noncommercial research access. Volumes you hold are imported from a folder; each Rights Record says "licensed for noncommercial research". |
| 4 | Standard Ebooks | by address | One book by its page address (bulk ZIPs are for Patrons Circle members). The EPUB is read in spine order and its headings become chapters. |
| 5 | Government and other public documents | by address | HTML or text with the rights the admin declares; "unknown" is held. PDF is held with an explanation, because reading PDFs and OCR are the next stage. |

- **Presets:** Phase 1 (100 books) and Phase 2 (1,000 books) across ten subjects, most read first.
- **Structure:** detected automatically (`bookq.auto_rules`). On the bundled books it matches the hand-tuned rules, for example 366 chapters of *War and Peace*. A text with no headings, such as an OCR scan, is cut into numbered sections.
- **Rights Record:** every book carries one: work, author, source and id, original publication, rights status, territory, source file (address, format, size, SHA-256), ingestion date, transformation (normaliser, parser, OCR) and human review. Admins mark books reviewed in the tab.
- **Block list:** Darwin.
- **Where books go:** `<data folder>/library/<id>/`, in the same form as the bundled books, listed in its `catalog.json`. Book Query lists them beside the 19 bundled books.
- **The job:** runs in the background, resumes after a restart, and Stop finishes the current book first.
- **Self-test:** 19 checks against a stand-in for every site.
- **Live check:** the 3 most-read Gutenberg astronomy books harvested in about 1 s each; one Internet Archive scan (1889) ingested from OCR; undated and post-1930 items held.

## Changes made to the suite's code

- **Language Lab** (the Language area's first tab, `#learn`): one screen and one text, in five steps:
  1. Pick the two languages, then a word from the 4,500-word lists.
  2. Type or say a sentence.
  3. Translate it. Phrases come from the offline dictionaries and any remaining word from the word lists, and every word shows where it came from.
  4. Hear it (any voice, speed, whisper) while each word lights up; **Talking clip** makes a Gemini / ElevenLabs video of a face saying it.
  5. Say it yourself and see which words were heard.

  Server side: `language/labtext.py` and `/api/lablang/*`.
- **The Language page made plain** (Language 1.56): the first tab is now "Translate & Avatar", three steps top to bottom: 1 Translate, 2 Listen, 3 Avatar says it (pick a face, one button), then optional practice. A line says whether the avatar video has the key it needs. Nothing was removed: the word list, voice choices, the drawn mouth guide and Talking clips sit under "More options".
- **Translation and speech in every language restored** (Language 1.55, `language/lablangs.py`):
  - **Lab languages:** the Lab lists every language QueryBook can translate. The Builder's 17 languages with word lists come first, then the 12 dictionary packs. With a Google or Gemini key, all 139 languages of the QueryBook Translate registry are listed.
  - **Online translation:** used for languages with no offline data, or words the dictionaries lack. Google Translate (the Google Cloud key) is tried first, then Gemini (the Speech key or the Control Panel key). It is always labelled, and the offline word-by-word result stays visible.
  - **Speech:** the espeak-ng voice for the language (about 100 languages), else the browser's own voice.
  - **Translate tab:** QueryBook Translate (also on the window's rail as 🌐 Translate) uses the Language app as its online gateway (`/api/translate/config`, `/api/translate-gateway/mt`), with provenance on every result.
  - **Avatar:** the Lab avatar speaks the sentence at once while the Gemini / HeyGen video is made. Talking clips now also find a Gemini key saved only in the Control Panel; that missing key was why the avatar stayed silent.
- **Lip-sync: Gemini / ElevenLabs talking clips** (Language 1.54, back to what worked in 1.52). A face says the words in a video made by Gemini; when Gemini cannot, the chosen voice (e.g. ElevenLabs) speaks and HeyGen animates the portrait. Speech → Talking clips, the Speak page's "Make a talking clip of this", and Language Lab step 4, where a human avatar from the library (Pamela and the starter faces) says the sentence in that video, in place. The local face engine tried in 1.53 was removed at the user's request (kept in git history, commit 82e15af).
- **24 × 7 harvesting:**
  - The Control Panel restarts the engine cleanly (Stop, save, Start) when harvesting is on and nothing has moved for 30 minutes: no fact gathered or filed, no byte downloaded. Each restart is logged and shown.
  - The one window restarts any program that ends, or stops answering for about 3 minutes.
  - "Start with Windows" now launches `START-QueryBook.bat`. It used to point at the old suite's file, which isn't in QueryBook.zip.
- Speech: voice options (whisper, female, croak, grandpa) now apply to every language. British voices used to drop them. The female whisper is espeak-ng's `whisperf`. Breathy whispers are recognised on every espeak-ng version. `tools/speech_probe.py` tabulates what changes the outcome on each system.
- **Farm out** (Control Panel → Farm out, `#farm`): give datasets or Wikidata lanes to another Windows PC or Mac, by computer name and IP address.
  - **No duplicate work:** each dataset goes to one machine only, and this server's harvester skips it.
  - **The harvester:** download a ready-to-run zip. It carries Python inside on Windows, and uses python3 on a Mac. It runs the same bulk engine, refuses to run on another machine or IP address, and seals what it gathers to the server's public key.
  - **What the harvester's user sees:** only a tally of record types and counts. **Back up to drive** copies the sealed files to an external drive.
  - **Import:** **Import from a drive** opens the files with the server's private key, checks each one against its assignment, and adds the facts without duplicates.
  - **Code:** `_core/qbseal.py` (X25519 and an encrypt-then-MAC box, standard library only, RFC 7748 vectors) and `_core/qbfarm.py`. The end-to-end check is `tools/farm_e2e.py`.
- The Control Panel's tabs can be opened by link (`#bulk`, `#facts`, `#farm`), so the window's areas land on the right tab. The Control Panel's own tab code used to ignore the link.
- Language Builder falls back to the whole of Webster's 1913 for words outside its 5,052 common words. It holds 101,080 headwords and is built by `apps/tools/build_webster_full.py` from Project Gutenberg #29765; "obsequious" now has a meaning.
- `qbsynapse` and `qbdsn` compute through `qbmath.py`. The results are identical and their self-tests pass.
- The test runner works on Windows: it uses UTF-8 output, and test temporary folders tolerate files Windows still has open. This applies to test runs only.

## Verified formula math

| Lean file | Proves | Mirrors |
|---|---|---|
| `Formulas.lean` (generated) | Every solution of the 35 STEM formulas, put back into its formula, gives the original quantity (76 theorems) | `apps/stem/science.py` |
| `Units.lean`, `UnitExamples.lean` (generated) | Conversions round-trip, converting through another unit changes nothing, temperature scales invert; 16 of STEM's own exact conversions | `apps/stem/units.py` |
| `Synapse.lean` | Network-memory strength stays in [0, 1] under any sequence of events; consolidated connections fade more slowly; the threshold stays within 0.30–0.70 | `apps/_core/qbmath.py`, `qbsynapse.py` |
| `Routing.lean` | Pathway strengths stay in [0, 1] under any sequence of lookups; recovery never overshoots 0.5; every new pathway is asked | `apps/_core/qbmath.py`, `qbdsn.py` |
| `Degrees.lean` | Sine in degrees is positive between 0° and 180°; `asind` inverts `sind` | STEM's degree functions |

`.github/workflows/querybook-one.yml` runs on every push:
- `lake build` (the Lean proofs);
- `cargo test` (the Rust port must equal the Python exactly);
- every application's self-test on Windows, macOS and Linux;
- the Windows bundle test: unzip, start with the bundled Python only, ask a word and a conversion.

## Developing

```bash
python -m unittest discover -s tests -t .
```

```bash
cd apps && python -B tools/run_all_tests.py
```

```bash
python tools/gen_lean.py && python tools/gen_rust.py
```

```bash
cd rust/qbcore && cargo test --release
```

After editing `apps/_core`, run `python apps/tools/sync_core.py` (the suite keeps a copy of the core in each application).
