# QueryBook Knowledge Demand Engine

Status: the user's design, adopted 2026-11-13. It is to be a permanent subsystem of the harvesting engine, not a one-time
list. Sections 1–9 are the specification. Section 10 says what is built today; section 11 what is not.

## 1. The principle

**Harvest by demonstrated information demand; validate by authoritative evidence.**

Demand decides what to investigate, when, which relationships matter and which predicates to fill first. Demand never
decides whether a claim is true, whether a person is historically important, whether an accusation is credible, or
whether popularity equals merit.

One correction is kept in view: Wikipedia page views measure which articles are read, not the words people typed into a
search box.

## 2. Four kinds of record, never mixed

| Record | Example | Is it a fact about the subject? |
|---|---|---|
| Observed metric | "Article X had Y page views in period Z" | No |
| Observed navigation | "Readers moved from article A to article B, N times" | No |
| Inferred intent | "Readers may be seeking predicate P" | No — always labelled as inferred |
| Verified fact | "A has relationship P to B, according to source S" | Yes — the only UFCS assertion |

## 3. Signal families — measurements that are never interchangeable

| Family | Sources | Tells QueryBook |
|---|---|---|
| Information consumption | Wikimedia page views, top pages | What people read |
| Navigation | Wikimedia Clickstream (monthly, aggregate) | How readers move between subjects |
| Entity prominence | Wikidata, QRank | Which entities attract broad attention |
| Search demand | Google Trends (API is in alpha: a connector is designed, access is conditional) | What people search for |
| News attention | GDELT | What media is discussing |
| Scholarly importance | OpenAlex | What research publishes and cites |
| Historical documentary presence | Library of Congress, Chronicling America | What appears in the historical American record |

Three roles are kept apart: **discovery** sources say what people care about; **structural** sources say how knowledge is
connected; **evidentiary** sources say whether an assertion is supportable.

### Source Qualification Gate

No source is harvested automatically until it has a ledger entry: `SOURCE_ID`, name, type, authority class, access
method, API, bulk download, structured data, licence, attribution requirement, commercial-use status, known restrictions,
update frequency, entity types, predicate types, geographic scope, temporal scope, confidence class, last reviewed. If
the licence is uncertain: no bulk ingest; it goes to review.

## 4. Demand is several measurements

Current, Persistent, Event-driven, Recurring, Historical, Cross-language, Navigational, Search-origin,
Knowledge-expansion. Scores (each stored by measurement period, never overwritten): `CURRENT_DEMAND`,
`PERSISTENT_DEMAND`, `VELOCITY`, `SPIKE`, `CROSS_LANGUAGE`, `NAVIGATION_CENTRALITY`, `SEARCH_ORIGIN`,
`RELATIONSHIP_EXPANSION`, `HARVEST_GAP`, `HARVEST_PRIORITY`.

Temporal classes, each kept with the numbers behind it: evergreen, rising, falling, breaking, event spike, seasonal,
anniversary-driven, resurgent, volatile, newly emerging.

### The demand record

```
demand_record_id, project, article_title, page_id, wikidata_qid, period_start, period_end, period_type, rank, pageviews,
source_class, access_mode, agent_class, retrieved_at, source_license, raw_record_hash
```

Missing measurements stay missing. Nothing is fabricated.

## 5. From article to entity

`article title → redirect resolution → canonical page → Wikidata QID → QueryBook entity → aliases`. A redirect's views
count for the canonical subject, and the redirect phrase is kept as a demand keyword: it shows the words people use.

Noise is classified, not thrown away: a disambiguation page is demand for an ambiguous term; a list page is umbrella
demand whose members are candidates; a date page is recurring calendar demand. Main Page, search, portal, category and
administrative pages are excluded.

Subjects are multi-label across: people, events, places and landmarks, organizations, creative works, concepts and
topics, products and technologies, biological and natural entities.

## 6. Keywords, predicates, questions

- **Keywords**: identity (titles, redirects, aliases), descriptive (lead, categories, classes), structural (section
  headings), relationship (linked entities), demand-discovery (redirect phrases, clickstream neighbours). Ranked by
  specificity, structural importance, relationship strength, demand contribution and persistence.
- **Predicates**: from Wikidata properties, infobox labels, section headings, relations in text and clickstream.
  Libraries per kind — person, event, landmark, venue, organization, work, scientific topic — and a Predicate Demand
  Profile per entity class: given a person, which relationships to harvest first.
- **Questions**: generated per kind (who is this, why famous, when and where born, what offices, how did they die…).
  These are intent templates, marked as extrapolated, never recorded user queries.

`Predicate demand = subject demand × predicate relevance × evidence of reader navigation × persistence × coverage gap ×
source availability` — QueryBook's own calculation, not a Wikimedia metric.

## 7. Harvest gap and priority

For each high-demand subject, expected coverage for its kind is compared with what is held. Each predicate is one of:
complete, partial, contradictory, weakly sourced, stale, absent, not applicable, needs review.

`Harvest priority = demand strength × persistence × knowledge gap × predicate importance × source opportunity ×
strategic domain weight × confidence need`, with modifiers for under-representation, historical importance,
acceleration, contradiction, weak sourcing and licence clarity. **Knowledge deficit can matter more than popularity**: a
moderately popular subject with 75 facts outranks a hugely popular one with 25,000. The formula is versioned
(`WDIE-1.0`); a change of weights is a new version so earlier rankings can be reproduced.

A demand score and an evidence confidence are separate on every assertion. Demand 98 with confidence 21 raises
verification priority; it is never shown as fact.

## 8. The universal extraction rule

> Every harvested major noun, named entity, person, organization, place, landmark, venue, event, work, concept, product,
> icon or historically material subject is evaluated as a potential canonical QueryBook entity. Every factual assertion
> about it is normalised, where it makes sense, into subject → predicate → object, with its qualifiers, provenance,
> source identifiers, time and place, confidence and verification status. Significant objects re-enter the candidate
> pipeline. Popularity and demand determine harvesting priority; they do not determine truth.

- Wikidata statements are ingested whole: subject, predicate, object, **qualifiers, references and rank** — not
  flattened.
- Predicates are normalised to one canonical FQL predicate, keeping the source's own predicate and wording, the mapping
  confidence and the mapping version. Predicates form a hierarchy (created → wrote, invented, designed, founded).
- "Icon" is a QueryBook analytical class, not a fact, unless a reliable source says so.
- Recursive expansion is bounded: importance, demand, structural importance and source thresholds, a depth budget, and
  identity resolution before any new candidate.
- The unit of production is the verified relationship, not the harvested page.

## 9. Safeguards and cycles

- **Breaking news** is staged: demand detected → provisional facts → stabilisation review → historical consolidation.
- **Sensitive subjects** (deaths, crimes, accusations, medical conditions, minors, private individuals, ongoing trials):
  allegation kept apart from adjudicated fact, statement dates and sources kept, no inferred motives, higher source
  requirements, human review before publication.
- **Quality tests**: duplicates, redirect double counting, bots, one-day distortion, modern-media and English-language
  bias, missing Indigenous and pre-digital history, celebrity over-representation, predicate hallucination, licence
  omissions.
- **Cycles**: daily (top pages, spikes, urgent gaps), weekly (clusters, velocity, rebalance), monthly (top lists,
  clickstream, persistent demand, snapshots), quarterly (taxonomy, templates, recalibration, a frozen index version).

New data domains: `QB_DEMAND_SUBJECT`, `_MEASUREMENT`, `_KEYWORD`, `_PREDICATE`, `_CLUSTER`, `_EDGE`, `_TREND`,
`_INFERENCE`, `QB_COVERAGE_GAP`, `QB_HARVEST_PRIORITY`, `QB_HARVEST_ASSIGNMENT`, `QB_SCORING_MODEL`, `QB_SOURCE_LEDGER`.
The American Historical People Graph (`top-americans-1400-2026.md`) is one consumer of this layer.

## 10. Built today (engine 1.47)

| Design item | What exists | Where |
|---|---|---|
| Monthly top-1,000 collection, English Wikipedia | Every month of the last two years, then one a quarter back to 2015 | `WikidataMostRead`, `VIEWS_FETCH`, `views_months` |
| Demand measurement kept by period, never overwritten | One row per subject and month: views, rank, source | `demand` table, `wd_demand` |
| Temporal classification with its numbers | evergreen, recurring, rising, falling, event spike, seen once; model `WDIE-1.0` | `demand_class`, `demand_report` |
| Article → QID → whole record | By three routes | `_entities`, `entitydata_entities`, `wdqs_titles` |
| Persistent attention summed over months | Yes | `views` table, `wd_views` |
| Cross-language recognition | Wikipedias with an article | `fame` table |
| Aliases as identity keywords; part-of-name lookup | Yes, for well-known items | `alias`, `names`, `find_entities` |
| Subject → predicate → object, entity-first | Every Wikidata record is stored as such facts, each with a link to its source | `entity_facts`, shard `links` |
| Recursive expansion with a depth budget | Three rings, 86 relationship properties, most tied-to first, no subject twice | `hot-circle`, `CIRCLE_TIES`, `CIRCLE_RINGS` |
| Demand → harvest when nothing is held | A question with no record queues its subject, read within minutes | `demand_note`, `WikidataDemand` |
| Asked-about lattices harvested first | The demand agent's learned counts order the hot lattices | `qbkeystone.order` |
| Kinds of things; the thing itself above things about it | Yes | `sense.kind_of`, `sense.choose` |
| Best-known role among several | Yes | `sense.known_for` |
| Answerable-questions test, daily | 198 subjects | `qbrelevance` |
| Demand shown as measurement, not importance | Harvesting → Relevance | Control Panel |

## 11. Not built yet

| Item | Note |
|---|---|
| Daily top pages; article-level daily series; per-platform and per-agent splits | Only monthly top-1,000, all-access |
| Other language editions | English only; "cross-language demand" today is the count of Wikipedias, not views |
| Redirect consolidation; disambiguation, list and date pages classified | Titles are resolved to a QID; redirect phrases are not kept as keywords |
| Clickstream ingest and the navigation graph | Not started |
| Wikidata qualifiers, references and ranks kept on facts | Built in 1.48 for new harvests and for well-known records already held; the rest of the store is the plan in `complete-facts-plan.md` |
| QRank | Not ingested; its terms to be recorded first |
| Google Trends, GDELT, OpenAlex, Library of Congress, Chronicling America | None connected. Each needs its Source Qualification entry first |
| Source ledger / qualification gate as a table | Provenance exists per fact; the ledger does not |
| Keyword extraction from article text, sections, infoboxes | Not started |
| Predicate Demand Profiles per entity class | `sense.IMPORTANT` lists telling predicates per kind by hand; not learned |
| Coverage auditor, harvest-gap score, priority score, assignment objects | Only the all-or-nothing case (nothing held → fetch) |
| Seasonal, anniversary, resurgent, volatile classes; velocity and spike scores | Six classes only, from monthly data |
| Canonical predicate vocabulary with source predicate, mapping confidence, hierarchy | Predicates are Wikidata's labels as they come |
| Breaking-news staging; sensitive-subject review queue | Not started |
| FQL over demand (`TOP subjects WHERE …`) | Not started |

### Suggested order

1. Keep qualifiers, references and rank on harvested Wikidata facts (unlocks roles with dates and per-fact sourcing).
2. Coverage auditor: expected predicates per kind against what is held, giving a harvest-gap score per subject.
3. Source ledger table and the qualification gate; then Clickstream (CC0, monthly files) as the second sensor.
4. Daily top pages and spike detection.
5. One outside sensor at a time, each through the gate: OpenAlex, then Chronicling America, then GDELT.
