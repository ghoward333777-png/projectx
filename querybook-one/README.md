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

QueryBook was designed to give anchored answers about one ebook. **📚 Book Query** (left rail, under Ask, for every role; also the button at the top of the Ask page) does that for a library of 22 (three of them Bibles: King James, American Standard and World English — public-domain translations only; `tools/build_bibles.py`). The first 19 are public-domain books (`apps/shell/library/`): step 1 choose a book (search, nonfiction / fiction / book-vs-today filters), step 2 ask it — suggested questions grouped by what the book can answer, earlier questions, the contents (read any chapter, every sentence a Fact Unit), answers quoted with their anchors. A newer QueryBook closes an older copy still running (which kept the browser on the old version); the version shows beside the name.

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

## AI Capabilities (window 1.5.0)

A page in the window ("✨ AI Capabilities", `apps/shell/ui/capspage.js`) with one tile for each of the twelve things QueryBook's AI does:

| # | Capability | What it does here |
|---|---|---|
| 1 | Ask / Search | A question goes to the Ask page (facts with sources); Book Query. |
| 2 | Summarize | Short summary, key points or one sentence of a pasted text. |
| 3 | Write / Create | Email, letter, report, essay, story, announcement, or a clearer rewrite. |
| 4 | Organize | Sort and remove repeats, group into topics, outline, table, actions and dates. |
| 5 | Analyze | Statistics of numbers or a table, a text's measures, two texts compared, claims checked against the facts. |
| 6 | Develop / Project | A goal becomes a phased plan with tasks to tick off; projects are saved. |
| 7 | Tools | Calculator, unit converter, dictionary, chemistry, word count, fact checker, read aloud, STEM, Video Studio. |
| 8 | Processes / Workflows | Chains of steps (five starters; build and save your own). |
| 9 | Agent(s) | A goal in words: the agent chooses the steps, runs them and shows each one; the harvest agents. |
| 10 | Chatbot | A conversation answered from the facts; follow-ups remember the subject. |
| 11 | Translate / Languages | Quick translation; the Language and Translate areas. |
| 12 | Learn / Study | Tutorial, quiz, flashcards, connections (the Ask page's modes); study questions from your own text. |

- **Who does the work:** `apps/shell/caps.py` is the rule-based engine (pure, no AI: a summary is the text's own sentences, numbers are computed). `apps/shell/assist.py` adds Claude or Gemini when a key is saved and "Use AI" is on. Every result says who made it.
- **Checks on the model:** numbers are always computed by the rules (the model only comments); a model grouping that loses or changes an item is refused; a chat reply is marked "general knowledge" unless facts were found.
- **Storage:** workflows and projects are small files in `<data>/shell` (`workflows.json`, `projects.json`).
- **Routes:** `GET /api/shell/caps`, `POST /api/shell/caps/run`. Tests: `tests/test_capabilities.py`.

## Changes made to the suite's code

- **Language Lab** (the Language area's first tab, `#learn`): one screen and one text, in five steps:
  1. Pick the two languages, then a word from the 4,500-word lists.
  2. Type or say a sentence.
  3. Translate it. Phrases come from the offline dictionaries and any remaining word from the word lists, and every word shows where it came from.
  4. Hear it (any voice, speed, whisper) while each word lights up; **Talking clip** makes a Gemini / ElevenLabs video of a face saying it.
  5. Say it yourself and see which words were heard.

  Server side: `language/labtext.py` and `/api/lablang/*`.
- **The Language page in four steps** (Language 1.57): the first tab is "Words · Translate · Speech · Avatar". A strip at the top shows 1 Words → 2 Translate → 3 Speech → 4 Avatar speech and turns green as each is done. Tapping a word, or pressing Translate, shows the translation beside the input and speaks it at once; step 4 has one button, "Avatar speaks it", and says whether the video has its key. Nothing was removed: repeat, hear the original, the drawn mouth guide, practice and Talking clips are under "More".
- **Translation and speech in every language restored** (Language 1.55, `language/lablangs.py`):
  - **Lab languages:** the Lab lists every language QueryBook can translate. The Builder's 17 languages with word lists come first, then the 12 dictionary packs. With a Google or Gemini key, all 139 languages of the QueryBook Translate registry are listed.
  - **Online translation:** used for languages with no offline data, or words the dictionaries lack. Google Translate (the Google Cloud key) is tried first, then Gemini (the Speech key or the Control Panel key). It is always labelled, and the offline word-by-word result stays visible.
  - **Speech:** the espeak-ng voice for the language (about 100 languages), else the browser's own voice.
  - **Translate tab:** QueryBook Translate (also on the window's rail as 🌐 Translate) uses the Language app as its online gateway (`/api/translate/config`, `/api/translate-gateway/mt`), with provenance on every result.
  - **Avatar:** the Lab avatar speaks the sentence at once while the Gemini / HeyGen video is made. Talking clips now also find a Gemini key saved only in the Control Panel; that missing key was why the avatar stayed silent.
- **Lip-sync: Gemini / ElevenLabs talking clips** (Language 1.54, back to what worked in 1.52). A face says the words in a video made by Gemini; when Gemini cannot, the chosen voice (e.g. ElevenLabs) speaks and HeyGen animates the portrait. Speech → Talking clips, the Speak page's "Make a talking clip of this", and Language Lab step 4, where a human avatar from the library (Pamela and the starter faces) says the sentence in that video, in place. The local face engine tried in 1.53 was removed at the user's request (kept in git history, commit 82e15af).
## Relevance — what people ask, first (engine 1.40, Control Panel 1.40, window 1.7)

After three weeks the store held 1.5 billion facts, had no record of Ed Sullivan and took Babe Ruth for a baseball card. Three causes, each fixed in the engine:

| Cause | Fix |
|---|---|
| **The source was never finished.** Parts of the Wikidata dump are named by weekly edition, so each new edition sent every lane back to part 1. The later parts were never read. | Lanes read never-read positions first (`unread_first`); no new edition is fetched until the current one is finished (`edition_progress`, at most 56 days). `dump_coverage` reports how much was ever read. |
| **No notion of what matters.** A 150 GB file was read in file order. | **Hot lattices** (`WikidataHot`, 14 of them: people by field, places, monuments, institutions, events, works, everyday things). Each asks Wikidata for the items of a kind, most linked-to first, and reads each one's whole record. They start before everything else. |
| **No grasp of what kind of thing a match is.** The Ask box took the first sixty facts whose subject began with the words. | `find_entities` finds every thing with the name, best known first (fame = Wikipedias with an article, then facts held), with all its facts. `sense.py` gives each its kind, prefers the kind the question expects and the thing itself over things made about it, puts record numbers last, and says who or what it is. |

- **What people read** (engine 1.41, `hot-most-read`): the 1,000 most-read English Wikipedia articles of each sampled month (every month of the last two years, then one a quarter back to 2015; Wikimedia page views, public domain). Each article's Wikidata record is read whole and its views are added up over the months, so lasting subjects outweigh a week in the news. It starts right after the demand agent. Views rank matches in `find_entities` and `sense.choose`, ahead of fame and facts held, but never ahead of the kind the question asks for. Verified live for the page-view service and the title-to-record step; the hot lattices' own ordering is still tested against a stand-in only (Wikidata's search throttled the build machine).
- **Icons first, and part of a name** (engine 1.43): "What are the Dodgers" listed only references.
  - **Part of a name:** the team is "Los Angeles Dodgers"; the lookup knew exact names and recorded other names only. A word index of well-known names (`names` table, `wd_names`, `name_words`) now finds every well-known thing whose name holds all the words asked; `sense.choose` gives an exact name an edge that fame overcomes. Records read earlier are indexed once (`index_names`).
  - **A weak fallback no longer passes as an answer:** when only names that *begin* with the words are found, the answer says so and the subject goes to the demand agent, which remembers the name it was asked under.
  - **Icons tier** (`ICONS`, `WikidataIcons`, keys `hot-top-*`, tier 0): the best known of each type people ask about, ranked by fame (Wikipedias with an article) and weighted for the user's culture (`bulk:culture`, United States by default). Seven sets: teams, athletes, music, screen, leaders and writers, places and landmarks, culture and events. Each takes the best 50 of every type in turn, types in listed order, so every MLB, NFL, NBA, MLS and WNBA team is in the first batches. Runs before everything but the demand agent.
  - **Why:** the hot lattices rank by how often Wikidata's records point at an item, which is not fame.
  - **Measured live:** the teams set listed 2,166 teams in 307 s with every code confirmed (MLB 35, NFL 53, NBA 38, MLS 27, WNBA 22). That run predates the take-turns ordering, which is tested with a stand-in only.
- **The hot list first** (engine 1.44): "Who are the Beatles?" — no record, while 893,059 facts a minute were being added elsewhere.
  - **"The":** the Ask box drops "the"; the record is "The Beatles". Every name is now tried with and without its article (`name_forms`).
  - **Read at once** (`hot-seed`, `WikidataSeed`, `apps/_core/hot_seed.json`): listing an icons set takes 5 to 15 minutes, two at a time, so a new start read nobody for half an hour. The ranked icons list now ships inside QueryBook (built by `tools/build_hot_seed.py`) and is read from the first minute, 250 subjects to a batch.
  - **Everything else waits** (`Supervisor.hot_first`, `HOT_WAIT_S`): while the hot list (seed, icons, most-read, hot lattices) has work, no other dataset is started. Safety valve: if the hot list adds nothing for 30 minutes the others run until it moves again, so harvesting never stands still. The demand agent and the complete domains are not part of the gate.
  - **A second way to read records** (`wdqs_entities`, `wdqs_find`, `wdqs_titles`, `api_refused`): when Wikidata's records service refuses the computer (HTTP 429), records are read through its query service and put into the same shape; the refusal is remembered for 15 minutes. The lattices' own ranking exists only in the records service, so they wait.
  - **Measured live:** six subjects (The Beatles, Dodgers, Yankees, Ed Sullivan, Babe Ruth, Michael Jackson) read into an empty store in 12–17 s by each route, and all six then found by the names people use ("Beatles", "the Dodgers", "Yankees").
- **The wrong person, and Moses** (engine 1.45): "Who is Ed Sullivan?" was answered with Boris Vian; Moses was not held.
  - **Every word of the name:** "Ed" is too short for the word index, so "Sullivan" alone matched Vian's pen name Vernon Sullivan, and he is better known. One name of an item must now hold every word asked (`wd_names`), and a full name matched exactly outweighs fame (`sense.choose`).
  - **The backup reader was losing most of the hot list:** on batches of famous subjects the query service cut its answer off and the whole part failed. Records refused by the records service are now read from Wikidata's per-record address (`entitydata_entities`: whole records, two at a time), and only what that refuses goes to the query service, in batches of 25 that are halved when cut off. Measured live on 500 icons with the records service refused: 48,825 facts in 287 s, against 13,303 facts in 602 s before.
  - **Two more icons sets** (`faith-thought-science`, `arts-business-works`): biblical figures, prophets, gods, popes, philosophers, scientists, inventors, explorers; painters, composers, architects, founders, companies, characters and the best-known works. Every code's label checked.
  - **"At a glance" printed `[object HTMLElement]`:** fixed (`akProfile`).
- **The network of nets, categories, and icons by leadership, wealth and influence** (engine 1.46):
  - **Network of nets** (`hot-circle`, `WikidataCircle`, `CIRCLE_TIES`, `circle_wave`): every hot record read notes what it is tied to — family, partners, teachers and pupils, predecessors and successors, members, founders, leaders, owners, makers and casts, places, events, works, honours, schools, employers, offices (86 Wikidata properties, every label checked). Those are ring 1; `hot-circle` reads them, the most tied-to first, and their ties become ring 2, then ring 3 (`CIRCLE_RINGS`). It works in waves of 5,000, lists the next wave five minutes after the last, never reads a subject twice, and runs beside the other harvests (it has no end, so nothing waits for it). Wikidata has no "friend" property; "significant person", "partner", "relative" and "influenced by" are the nearest.
  - **Measured live:** from three icons (The Beatles, Moses, Ed Sullivan) ring 1 was 135 subjects — Lennon, McCartney, Harrison, Starr, Aaron, Joshua, Exodus, Liverpool, CBS — read in 52 s (5,192 facts); ring 2 then held 1,530.
  - **Categories** (`ICON_CATEGORIES`, `icon_category`, `icon_categories`): every kind an icons set asks for belongs to one of twelve — Government and leadership, Religion, Literature, Culture and history, News and media, Entertainment, Music, Sports, Science and technology, Business and wealth, Arts, Places. Shown on Harvesting → Relevance.
  - **Three more icons sets:** `government-leadership` (heads of state and government of every country, Nobel laureates, judges, diplomats, commanders), `wealth-technology` (everyone with a net worth on record, chief executives, engineers, programmers, public companies, software, websites), `news-media` (journalists, news presenters, newspapers, magazines, broadcasters, stations).
- **A person's best-known role** (`sense.known_for`, `ROLES`; window 1.7.6): a record lists every occupation in no order of importance. Four signs from the person's own facts rank them: the one-line description and the order it names them in; facts that back a role up (teams and a sport, positions held, instruments and labels, awards and works whose names say the field); the highest office held; the record's own order as a tie-break. The answer says "Best known as …; also …" and the Ask page shows why. Checked on real records: Reagan → President of the United States (also actor); Schwarzenegger → actor (also bodybuilder, politician); Michael Jordan → basketball player; Ed Sullivan → television presenter.
- **Top Americans 1400–2026** — the plan for the American Historical People Graph is in `docs/querybook-rebuild/top-americans-1400-2026.md`, with what exists for it and what is not built.
- **Demand intelligence, first slice** (engine 1.47; design in `docs/querybook-rebuild/knowledge-demand-engine.md`): each month's page-view measurement is kept as taken — subject, month, views, rank, source (`demand` table) — beside the running total. `demand_class` labels a subject evergreen, recurring, rising, falling, event spike or seen once and returns the numbers the label rests on (model `WDIE-1.0`). Harvesting → Relevance shows the classes and the subjects read most persistently, stated as measurements, not importance. The rest of the design (clickstream, qualifiers and references on facts, coverage auditor, source ledger, outside sensors) is not built; the document lists it.
- **Complete facts: dates, sources and rank** (engine 1.48, window 1.7.8; plan in `docs/querybook-rebuild/complete-facts-plan.md`): a harvested statement used to keep its main value only. Now each keeps when it held (start, end, point in time), its other qualifiers, its rank and up to three sources (`statement_context`), stored beside the fact in a `context` table so the fact store and every fingerprint are untouched. Hot datasets keep everything; the dump lanes keep dates, qualifiers and rank. `hot-context` re-reads the well-known records already held, best known first, and adds their context without writing a second copy of any fact. Answers say roles with their years; the Ask page shows each fact's period and "Stated in". Checked on real records: Babe Ruth "Played for Boston Red Sox (1914–1919), New York Yankees (1920–1934), Boston Braves (1935)"; Reagan's presidency 1981-01-20 to 1989-01-20 with its source.
- **AI text gen, coordinated with the user** (window 1.8.0): the library is now 71 document forms in 10 families, 42 fields (each with its citation system and standard of evidence), 12 style templates and a register of 44 sources including ten legal ones. **Plan it** shows the plan first; **Write it to this plan** drafts and judges; **Revise to my notes** applies the user's own notes, as often as wanted. **Learn my style** measures 14 habits from the user's own writing and saves them as numbers. **Learn from a source** reads one page once (robots rules first) and keeps its advice as rules in QueryBook's own words. Nothing has been learned from a source yet.
- **✍️ AI text gen — writing skills** (window 1.7.9; the user's plan and the built / not-built list in `docs/querybook-rebuild/writing-skills-plan.md`): a new item in the rail beside Language and Translate. `writing.py` holds the grammar (each sentence's topic and comment; a paragraph's pattern — constant theme, linking, index — and the theme-preview check) and a five-layer critic; `genres.json` holds 38 document types in 7 families as data. **Any document** plans from the genre's record, has a model draft to that plan from the brief and QueryBook's facts, and has the critic judge the draft and send it back once. **Check a draft** and **Show the flow** need no AI. The genre records are a first draft from general knowledge, not yet reconciled with sources or reviewed by a person, and every result says so.
- **Complete domains, in tiers** (engine 1.42, `hot-all-<name>`, `DOMAINS`): 100% of the people Wikidata records in a domain, not just the best-known few thousand. The whole list comes from Wikidata's query service (the occupation and every narrower kind under it), best known first; records are then read 500 people to a batch.
  - Tier 1, people who face the public: actors, authors, television and radio, music, models, speakers, officials, athletes.
  - Tier 2, key jobs in critical fields: medicine, engineering, science, law, business, finance, teaching, flight.
  - Tier 3, other well-known fields: art, film-making, religion, scholarship, exploration.
  - Order: demand agent, most-read, hot lattices, tier 1, tier 2, tier 3, then everything else.
  - Every Wikidata code was checked against its label on 2026-11-12 and is checked again at each listing; a mismatch is left out and reported. Four wrong or useless codes were removed from the hot lattices.
  - Measured live: models 45,500 people listed in 26 s; television and radio 361,249 in 202 s, with Ed Sullivan at rank 1,618. Not measured: how long reading several million records takes on the user's connection.
- **Demand agent** (`hot-demand`): a question that finds nothing, or only the wrong kind of thing, is queued and fetched by name within minutes. It records which lattice each such subject belongs to; those lattices are harvested first.
- **Relevance test** (`qbrelevance.py`): 198 well-known subjects in 12 fields. Each must resolve to the right kind of thing with the facts that make an answer. Runs daily by itself; score, breakdown, misses and diagnosis are on Harvesting → Relevance and in the diagnostics; every miss goes to the demand agent.
- **Recorded from now on:** each item's description, other names and fame.
- **Not verified live:** Wikidata's service refused this build machine (HTTP 429), so the lattices and the demand agent are tested against a stand-in only.

- **Lanes no longer queue to file after every part (engine 1.39):** seen in the user's screenshot — 15 of 16 Wikidata lanes at "0 facts/min", each having read its 1 GB file and waiting its turn to file (one at a time on an external drive). At the end of a part a lane now files only if the slot is free or 20 million facts wait; otherwise it reads its next part. Everything still staged is filed at the end of the dataset. Fewer, larger filings; no idle lanes.
- **Harvest first, add back in the background (engine 1.38, Control Panel 1.39):** until 1.37 nothing was harvested until every copy of every dataset had been compared and merged, which on a large store is hours of "0 facts a minute" after every start. Now the merge runs in the background one dataset at a time: only that dataset waits, the others harvest from the first minute, and the headline says what is being added back. The Control Panel log writes a harvest line every 10 minutes while it runs and adds nothing, and one when facts flow again.
- **The churn fixed at its cause (engine 1.37, Control Panel 1.38, window 1.6):** found in the user's `control.log`.
  - **Cause:** at every start the engine adds back facts held in another copy of a dataset. That merge was one all-or-nothing step: hours of disk work with nothing to show, started again from nothing when interrupted, and repeated at every start for a copy whose count could never be "accounted for". The 30-minute "nothing moved" check itself interrupted it.
  - **Merge in pieces:** 256 pieces, each saved as done; an interruption resumes at the piece reached; the count rises as it works; a copy once merged is not merged again while unchanged (`_restored.json`).
  - **Getting ready is work:** the fail-safe follows the merge's own progress and no longer restarts an engine that is getting ready; the page says what it is doing and how far.
  - **Alive means the process is there:** the heartbeat file is on the data drive, and a busy drive delays it. An engine whose process is running is no longer taken for dead, doubled, and ended after 5 minutes.
  - **Churn per dataset:** a dataset that reads for 45 minutes without one new fact is rested (6 h, then 12 h, then 24 h) while the others carry on.
  - **Drive guard:** the data drive is tested every pass. If it does not answer, or its databases give read/write errors 3 times in 5 minutes, harvesting pauses and resumes by itself after the drive has answered for 3 minutes. Repeated errors write one log line per 10 minutes, not one every 20 seconds.
  - **Alerts:** no new fact for 20 minutes, getting ready for 30, or a drive pause raises an alert, and the window's header shows a harvest indicator on every page (green, amber, red with a banner).
- **Harvesting fail-safe (engine 1.36, Control Panel 1.37):** judged by new facts, not by activity.
  - **On until Stop:** pressing Start switches harvesting on; it stays on until Stop is pressed. With no engine running (after a reboot, a crash, an update into a new folder, a restart cut short) it is started again within 3 minutes. A leftover stop mark no longer keeps it stopped.
  - **No new fact:** at 1 hour the engine is restarted; at 2 hours restarted hard (every process ended, stale marks cleared); at 3 hours the datasets that add nothing are rested for 6 hours so the others take their place. One new fact resets this. A filing that is advancing is left alone, for at most 4 hours.
  - **Start with Windows:** while harvesting is on, the Windows start-up entry follows the folder QueryBook runs from now (each download unpacks into a new one). It stays off only if you turned it off.
  - **Said plainly:** the Harvesting page and the diagnostics say how long since the last new fact, what the fail-safe did and will do next, what is busy and what is resting. "Running, 0 facts a minute" for 30 minutes is no longer shown as ok.
  - **False errors removed:** a caller closing its connection early (the window's status polling) is no longer logged as an application error.
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
