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

## Built (window 1.7.9)

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
| **The genre records are a first draft from general knowledge.** | No source has been collected. Each site's terms must be checked first. Every record and every document says so. No person has reviewed them (the plan's step 6). |
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

## The plan's decisions, still open

1. Confirm the first 10 genres for phase 1.
2. Approve the added fiction sources, or supply preferred ones.
3. Choose a second legal source for contract drafting.
4. Decide who reviews genre records before use.
5. One house voice, or adapt to each user's style.
