# QueryBook Writing Skills — the user's plan, and what is built

Status: 2026-11-13. The plan is the user's ("QueryBook Writing Skills Plan", 13 November 2026). This file records it in
brief and says honestly what exists. It lives in the window as **✍️ AI text gen**, beside Language and Translate; the
user's intention is to build and perfect it over the following days.

## The plan in one page

QueryBook learns to write by holding writing knowledge as structured, retrievable rules at five layers, and produces a
document by plan → draft → critique → revise. It does not learn by imitating source text.

1. **Grammar.** Every clause is a *topic* (what the reader already holds) and a *comment* (what is new). A paragraph
   relates its topics in one of four ways:

   | Framework | Topic rule | Use for | Check |
   |---|---|---|---|
   | Constant theme | Each sentence opens on the same subject | Definitions, profiles | Flag over about six sentences as static |
   | Linking | Each sentence opens on the previous comment | Processes, causes, narrative | Each topic appears in the comment before it |
   | Index | The whole is named, then each part | Taxonomies, components | An umbrella sentence, every later topic a member |
   | Theme preview | Destinations announced, then visited in order | Reports, chapters | Headings match the preview word for word, in order |

   Three rules above all genres: name the whole before the parts; keep structural terms constant; local links must
   serve the paragraph's purpose.

2. **Five layers**: sentence flow, paragraph pattern, document structure, rhetorical situation, domain convention.
3. **Genre library**: one record per document type — purpose and reader, blueprint, moves, framework defaults,
   register, evidence rules, hard constraints, failure modes as testable checks, provenance. 38 records in 7 families
   in the first build.
4. **Source learning**: 40 listed guides mined in five waves for their rules, in QueryBook's own words, each with its
   source; a person reviews a record before it is used.
5. **Writing machine**: brief → select genre → build blueprint → bind facts → draft → critique at all five layers; a
   failed check sends the draft back; the writer and the critic read the same record.
6. **Evaluation**: automatic checks per layer, plus human checks; a benchmark set and blind comparison against
   human-written exemplars; every non-fiction claim traced to a held fact.
7. **Roadmap**: phase 0 grammar (source-free) → 1 core genres → 2 technical and business → 3 academic and journalism →
   4 fiction → 5 scale.

## The user's decisions (2026-11-13) and the aim

"Our plan is to build a machine - and everything must coordinate with the user."

| # | Decision | What it means here |
|---|---|---|
| 1 | Do all genres; order is not important; this is one-time machine learning | No phase ordering by genre. The library holds every form as a row |
| 2 | All sources — eventually hundreds, learned once | A source register; a page is learned from once and never again |
| 3 | The top 10 legal sources, from top universities and law repositories | Found by search on 2026-11-13 and listed in the register (wave "Legal — the ten") |
| 4 | Users review as composition begins and progresses; no separate review needed at this stage | The machine works in steps the user sees: plan → draft → the user's notes → revised draft |
| 5 | Adapt to the user's style, or apply a template from a growing library | Style is measured from the user's own writing, or chosen from templates; both live in one list |

The aim: "all genres, all New York Times Book genres, all academic disciplines, all topics - universally … the most
authoritative and skilled writing engine in the AI industry." The design answer is that a document is a **form** (genre)
written in a **field** (discipline or topic) in a **style**, and all three are data rows.

### The ten legal sources

| Source | Kind |
|---|---|
| Georgetown Law Writing Center — guides and handouts (already in the plan) | University |
| Columbia Law School Writing Center — legal writing resources | University |
| Duke Law — legal writing resources | University |
| Yale (Poorvu Center) — writing resources for law students | University |
| University of Maryland Carey Law — Legal Writing Center | University |
| CUNY School of Law — Legal Writing Center | University |
| Cornell Legal Information Institute — Wex and the introduction to legal citation | University law repository |
| U.S. Securities and Exchange Commission — A Plain English Handbook | Government |
| Office of the Federal Register — plain language and drafting legal documents | Government |
| UK Office of the Parliamentary Counsel — drafting guidance | Government |

(U.S. Courts' "essentials for drafting clear legal rules" is listed as well.) Harvard, Stanford and Berkeley were
searched for and no public writing-guide page was confirmed, so they are not listed. Contract drafting is covered by
Georgetown's transactional guides and the SEC handbook; a dedicated contract-drafting source is still wanted.

## Built since (window 1.8.0)

| Decision | What exists | Where |
|---|---|---|
| 1 | 71 genres in 10 families (added: everyday and professional, teaching and learning, books) | `tools/build_genres.py` |
| aim | 42 fields in 8 groups, each with its customary citation system and standard of evidence; a field reaches the writer and the critic | `FIELDS`, `writing.with_field_and_style` |
| 2, 3 | Register of 44 sources in 6 waves, none claimed as learned | `SOURCES`, shown under "Learn from a source" |
| 2 | **Learn from a source**: one page; robots rules read first; a model restates the advice as rules; any rule repeating seven of the page's words in a row is dropped; saved with address, date and page hash; a page is never learned twice; learned rules join their genre's record and its provenance | `assist.learn_source`, `writing.keep_units` |
| 4 | **Plan it** → the plan is shown first → **Write it to this plan** → the draft, judged → **Revise to my notes**, as often as wanted | `assist.write_document` (`stage`), `ui/capspage.js` |
| 5 | **Learn my style**: 14 measured habits from a sample of 150 words or more, saved as numbers (no sentence kept); 12 QueryBook templates; one list; the drafter is told the targets and the critic measures the distance | `writing.style_profile`, `style_distance`, `style_brief`, `STYLES` |

Still true: no source has been learned from yet — learning needs an AI key and is started by the user, a page at a
time. New York Times book categories are not yet a table of their own: eight book forms exist (proposal, non-fiction,
how-to, memoir, biography, picture book, young adult, textbook chapter) and the list of that newspaper's categories
should be taken from its own page, not from memory.

## Built first (window 1.7.9)

| Plan item | What exists | Where |
|---|---|---|
| Topic–comment tagger | Rules, not a parser. Marks a sentence unsure when it finds no verb | `writing.tag` |
| Framework classifier | Constant theme, linking, index; "none" when no pattern holds | `writing.framework` |
| The four checks | Static constant theme; broken chain; stray index member; preview kept in words and order | `check_paragraph`, `check_preview` |
| Genre record schema and library | 38 records, 7 families, stored as data; a new genre is a new row | `tools/build_genres.py` → `apps/shell/genres.json` |
| Failure modes as testable checks | 15 named checks (conclusion first, citations, attribution, the news lead, numbered and imperative steps, a lawyer's review, defined terms, an accusation marked as one, a forecast's likelihood, and others) | `writing.run_check` |
| Blueprint | Sections in order with each move, framework at three scales, fixed terms, register, evidence, hard constraints; what the brief leaves out is asked for | `writing.blueprint`, `brief_gaps` |
| Genre selection | From the document type the brief names; a blend when it names two; none named → asked for, never guessed | `writing.select_genre` |
| Critic at five layers | One reading against the same record; structure first; human checks listed separately | `writing.critique` |
| The machine | brief → genre → blueprint → facts from the store → draft (a model, labelled) → critique → one revision | `assist.write_document` |
| Works with no AI key | The blueprint to write from; "Check a draft" and "Show the flow" need no AI | `assist.check_draft` |
| In the window | ✍️ AI text gen: Any document, Check a draft, Show the flow | `ui/capspage.js`, `ui/shell.js` |

Hard constraints are in the records: legal genres are a draft for a qualified lawyer; a crime report does not call an
accused person guilty; an official weather warning is given as issued.

## Not built — the honest list

| Item | Note |
|---|---|
| **The genre records are a first draft from general knowledge.** | No source has been learned from yet. Every record and every document says so until one has. |
| Source learning, all five waves | Not started |
| Phase 0 exit test | The tagger scores 27 or more of 28 on a sample — but the sample was labelled by the same hand that wrote the rules. Agreement with another person's labels is still to be measured |
| Theme preview as a paragraph class | Checked at document level only |
| Rewrite operations (layer 1) | The critic says what to fix; QueryBook's rules do not rewrite a sentence themselves |
| "Only the failing sections go back" | The whole draft goes back once with the list of failures |
| Claims traced to facts, sentence by sentence | Facts are supplied to the drafter and it is told to use nothing else; the draft is not yet verified claim by claim (Book Query's verifier is the model to follow) |
| Fiction model and story bible | Six fiction records exist; no premise, character or world store |
| Benchmark set, exemplars, blind comparison, reader panels | Not started |
| Per-user style; one house voice | The plan's open decision |
| Thesis-scale planning | A chapter's blueprint exists; nothing holds a preview across chapters |

## Next, in the order that adds most

1. Learn from the sources: wave by wave, a page at a time (needs the user's AI key).
2. Verify a draft's claims against QueryBook's facts sentence by sentence, as Book Query does.
3. Rewrite operations for layers 1 and 2, so the rules can repair a sentence themselves.
4. A whole-book planner: a preview held across chapters, and a story bible for fiction.
5. The benchmark set and blind comparison — the measure of "most skilled".
6. Fields and book categories from authoritative lists (library classifications; the newspaper's own category page).
