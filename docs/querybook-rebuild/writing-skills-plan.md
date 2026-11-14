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

(Superseded: see "Source learning — first pass done" below.) New York Times book categories are not yet a table of their own: eight book forms exist (proposal, non-fiction,
how-to, memoir, biography, picture book, young adult, textbook chapter) and the list of that newspaper's categories
should be taken from its own page, not from memory.

## Source learning — first pass done (2026-11-13, window 1.8.2)

The user: "Start source learning on all sources now." Six readers (models, in the build session) took the register in
parallel. For each source: find one to three guide pages on the source's own site, read the site's robots rules, read
the page, restate its advice as rules in their own words. `tools/build_learned.py` is the gate: a known genre and layer,
no run of seven of the page's words, the page hashed and not kept. Result: **817 rules from 69 pages of 32 sources**, in
`apps/shell/genres_learned.json`. They join each genre's record (its own rules first, the sources taking turns) and
appear in the plan and in the drafter's instructions. The page texts were deleted after hashing.

Not read — and nothing was written for them from memory:

| Source | Why |
|---|---|
| ams | Not read: the AMS site refused automated access. The statement page on www.ametsoc.org (Best Practices for Publicly Sharing Weather Information Via Social Media) returned |
| harvard | Not read: writingcenter.fas.harvard.edu returned HTTP 403 (Access Denied) to every request, including robots.txt and two guide pages (/strategies-essay-writing and /thesi |
| melbourne | blocked: the site answered every request (robots.txt and two guide pages) with an anti-bot challenge page (HTTP 403), from both curl and the web fetch tool; not bypassed, |
| michigan-sweetland | blocked: the site answered every request (robots.txt and two guide pages) with an anti-bot challenge page (HTTP 403), from both curl and the web fetch tool; not bypassed, |
| monash | Not read. www.monash.edu answered HTTP 403 with a bot challenge page for robots.txt and for one Excel at Writing guide page (two attempts, two tools); the block was not b |
| purdue-owl | Not read. owl.purdue.edu could not be reached from this session: curl failed TLS verification (the server's certificate chain could not be verified; verification was not  |
| scribbr | Not read: www.scribbr.com robots.txt allows the guide pages, but the site returned HTTP 403 (a Cloudflare bot challenge) for two guide pages (/dissertation/literature-rev |
| stagemilk | Not read: www.stagemilk.com returned HTTP 403 for both pages tried (how-to-write-a-monologue and what-is-a-monologue). robots.txt allowed them; no bypass attempted. |
| stc | Not read. https://www.stc.org/ and one other page (https://www.stc.org/about-stc/defining-technical-communication/) both returned only a placeholder saying the website is |
| uagc | Not read. https://writingcenter.uagc.edu/writing-white-paper (robots.txt allows it) redirected twice to a Cloudflare Turnstile challenge page (/challenge?destination=/wri |
| unc | Not read, by choice of the reader - needs the caller's decision. writingcenter.unc.edu/robots.txt allows 'User-agent: *' (empty Disallow for content pages), so the brief' |

Two points for the user:

- **UNC's site allows general automated readers but names AI crawlers (including Anthropic's) as not allowed.** The
  reader therefore did not read it. STC's site carries a "no AI training" signal. Both were respected. If the user
  wants those sources, the honest routes are to ask the site, or to enter the rules by hand from their own reading.
- Sites that answered with a bot challenge (Harvard, Monash, Melbourne, Michigan, Scribbr, UAGC, StageMilk, AMS) may
  load normally from the user's own computer: "Learn from a source" in the window reads one page at a time there.

Thin or off-target: Yale's law page had no writing advice, so a Poorvu page on writing public comments was used;
Maryland's guides are behind a login, so only its public seminar-paper criteria were read; Stanford's page read was on
citation only; Poynter yielded five rules. The licence terms of each site are still to be recorded from its own page.

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
| The genre records' skeletons are a first draft from general knowledge | Learned rules now sit beside them; the skeletons (sections, moves, register) have not yet been rewritten from the learned rules |
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

## VOICE — the user's guidelines for writing with AI (adopted 2026-11-14, shell 1.9.0)

Source: the user's guide "Writing With AI Without Losing Your Voice". Five pitfalls of AI writing are answered by five
standards, and the person stays responsible for truth, perspective, meaning and the final decision.

| Pitfall | Standard | In the engine (`apps/shell/writing.py`) |
|---|---|---|
| Confident inaccuracy | **V**erified | `claims`: every name-date-number, quotation, "research shows", superlative, causal and absolute claim is listed and labelled unverified / interpretive / opinion. Nothing is ever labelled verified — a citation is not a verification; only the person who opened the source can say so |
| The broken record | **O**wned | Stock phrases (`STOCK`); how many of the writer's own details (names, numbers) survive in the draft (`own_details`) |
| Smart but empty | **I**nsightful | Sentences of abstract nouns with no example, reason or case; no reason given anywhere; no objection or limit; the meaning-test questions are asked |
| Clarity lost in noise | **C**lear | Abstract nouns on weak verbs, sentences over 35 words, official-sounding words (`JARGON`) |
| Predictable and boring | **E**ngaging | A paragraph that repeats an earlier one, three sentences opening alike, an opening with nothing left open, an ending that does not answer the opening |

Where it acts:

- **Before drafting** (the plan step, never skipped): the ownership interview (ten questions), the thesis to complete
  ("Most people believe … I believe …") and what the brief leaves unsaid. The person's answers go to the drafter as
  *the writer's own material*.
- **While drafting**: `VOICE_RULES` are part of `writer_brief` for every non-fiction document — only supplied facts,
  experiences, quotations and sources; `[needs evidence: …]` where support is missing; claims matched to their evidence;
  the writer's details and wording kept; no stock filler; actors named; every paragraph new.
- **After drafting**: every draft and revision is read by `voice_audit` (rules, no AI) and shown under the critic's reading.
- **VOICE check** (a task of AI text gen): paste any draft. The rules point and ask; with a key, a model adds an editor's
  second reading that does not rewrite and may not call anything verified (`assist.VOICE_EDITOR`), labelled as made by AI.
- **For the person, not a machine**: truth, fairness and privacy, meaning, and the final decision are listed on every audit.

Not built yet: the interview as a one-question-at-a-time conversation that pushes back on vague answers; checking that a
cited source exists and supports the wording (needs the source opened — the audit only says to do it); cultural-flattening
detection beyond the writer's lost details; the say-it-aloud and independent-reader tests.

## Story check — the user's tips for fiction (2026-11-14, shell 1.9.1)

From the user's notes on a talk about habits common in manuscripts (the rules are in QueryBook's words; the talk itself was
not read and is not marked as a learned source). VOICE is for non-fiction; a story is read for these six instead
(`writing.fiction_audit`, `FICTION_RULES`, task `write.story_check`; the story drafter is bound by the same rules).

| Habit | The fix | What the rules can see |
|---|---|---|
| Dialogue too formal, like a therapy session | Make it messy and real | Spoken lines without contractions; feelings explained in tidy sentences; no one interrupts or trails off; speeches over 30 words |
| Point of view drift | One scene, one head | Two named characters' thoughts in one scene |
| Stakes that never land | Name the personal, human cost | "lose everything", "the fate of the world" and the like |
| The pacing plateau | Match sentence length to the scene's heat | Sentences all of one length |
| First page starts too early | Open where the trouble begins | A waking-up routine in the first 150 words |
| The overwritten everything | Trust nouns and verbs; use white space | "-ly" words, stacked adjectives, paragraphs over 170 words |

The notes arrived with their first lines cut off: the name of the dialogue habit is inferred from its fix, and any tips
before it are not in the engine.

## The engine after 2026-11-14 (shell 1.11.0) — type first, analysis and generation, everything under the user's control

The user: "users must be asked to define what type of document they want to generate or analyze"; "the Writing Engine needs to
be used for both AI analysis and generation"; "every aspect of writing must be placed at the control of the user — so that the
resulting text reads like human writing and not generic AI writing."

**1. The universal document types** (`tools/doctypes_source.txt` → `tools/build_doctypes.py` → `apps/shell/doctypes.json`).
The user's master taxonomy, kept as written: 45 domains, 917 types, the parts each type is expected to have (212 types have
parts stated by the list, for the type or for its group), and 20 purposes. The page asks for **1. Area → 2. Type** before
anything is planned or checked; nothing is guessed. A type QueryBook holds a full record for (★, 54 of them) uses that record
with its learned rules; any other type is planned from the list's own parts, in the list's order
(`writing.genre_from_type`), and says so. Legal, patent, medical, investment and insurance types carry their caution
("a draft for a qualified lawyer" …). Not built: the deeper ontology the list describes (Level 1–4 objects, entities, claims,
authority, rights on every ingested document); parsing an ingested document into its parts.

**2. Analysis** (`writing.analyze_document`, task `write.analyze`). An existing document is read for its likely type (by its
expected parts appearing as headings, or its name at the top), likely purpose, point of view, formality, tone, passive share,
sentence habits and nearest style templates. Every line is a likelihood with what it rests on; "the rules cannot tell" is an
answer. **Write with these settings** carries the reading into generation.

**3. The writer's controls** (`writing.CONTROLS`, `controls_brief`, `controls_check`). Tone and second tone, point of view,
formality, sentence length, reader level, contractions, feeling, humour, certainty, detail, how to open, how to end, length.
A setting overrides the type's usual manner; one left alone follows the type and the style. What a rule can measure (point of
view, contractions, length, sentence length) is checked against the draft; tone is left to the person's ear and said to be.

**4. The style template library** (`STYLES`, `STYLE_GROUPS` in `tools/build_genres.py`; task `write.styles`). 42 templates in
seven kinds — Everyday, Business, News and media, Academic and technical, Legal and official, Persuasion, Storytelling — each
a description, what it is good for and its habits as numbers; described by manner, never by a named author. The user's own
measured styles sit in the same library.

**5. Structure for the reader** (`writing.essay_audit`, `ESSAY_RULES`): title that builds curiosity; introduction that poses a
problem; index and discussion at every level; a constellation of key terms; a conclusion that returns to the problem and widens
it. **Story check** now has nine habits: the six above plus a coming event with a clock, chapter endings left open, and
planted things paid off (the last is the writer's to trace: rules cannot follow a thread across a book).

**6. Sources read on 2026-11-14** (the sites the user named): MIT OpenCourseWare (29 rules), Reedsy's public guides (33),
Purdue OWL (28) — 90 rules, through the same gate as before. Not learned from: OpenLearn (only a rendering of its pages could
be had, so the copy check could not be made honestly), Quill and Write & Improve (tools: their public pages give no writing
advice), Class Central (refused automated readers), Coursera (teaching needs an account). Google Docs outline view is a tip
about a tool, not a source. Shipped total: 907 rules from 78 pages of 35 sources.

## The document wizard (shell 1.12.0)

The user (2026-11-14): "a user-friendly wizard for generating documents; allowing users to define what type of document, their
goal, length, style, voice, tone, etc. — using best practices and proven approaches to composition."

AI text gen opens on **🧭 Document wizard** (`cpWizard` in `ui/capspage.js`). Seven steps, in the order a writer works:

1. **Type** — find it by name across the 917 types, or browse by area. Required; never guessed.
2. **Goal** — what it is about (required), its purpose (the 20 purposes), what the reader should do afterwards, who the reader is,
   what it must and must not do.
3. **Length** — six plain presets or an exact word count; how much detail.
4. **Style** — one of the templates, by kind, or the type's own; the field.
5. **Voice & tone** — point of view, tone, formality, feeling, humour, certainty, reader level, sentences, contractions, how to
   open and end.
6. **Your material** — what only the writer knows, with the interview questions as prompts.
7. **Plan & write** — a summary with a Change button on every line; the plan is shown before a word is written; then the draft
   (checked by the critic, VOICE and the settings), then revision to the writer's notes.

Only steps 1 and 2 are required; anything skipped follows the type. Each step carries one line of composition practice (purpose
and reader before words; length is a decision; plan, draft, revise). The wizard sets the same state as "Any document", so the
two always agree, and choices are remembered between visits. It adds no new server code: it drives `write.doc`.
