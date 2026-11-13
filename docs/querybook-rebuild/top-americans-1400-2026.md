# QueryBook: Top Americans 1400–2026 (the American Historical People Graph)

Status: the user's plan and strategy, adopted 2026-11-13. This file is the specification. The last two sections say what
QueryBook already has for it and what is not built yet. Nothing here is built unless that section says so.

## 1. Objective

A legally reusable, source-traceable database of historically prominent people associated with what became the United
States, ranked across time rather than by present-day celebrity.

| Target | People |
|---|---|
| Prototype 1 | 25,000 |
| Comprehensive | 100,000+ |

These are design targets, not counts taken from any source. The schema is designed for millions from day one.

## 2. "American-associated" — five inclusion classes

American-associated ≠ American-born ≠ U.S. citizen. The record keeps the distinction.

| Class | Who |
|---|---|
| A. Indigenous America | People of Indigenous nations within territories that became the United States. Never retroactively labelled U.S. citizens. Association: "Indigenous North America / present-day United States". |
| B. Pre-U.S. territorial America | 1400–1775, connected to territories later part of the United States: Indigenous leaders, explorers, missionaries, colonial leaders, settlers, military figures, merchants, writers, scientists. |
| C. U.S. nationals / citizens | Associated through nationality or citizenship. |
| D. American-born | Born in the United States, including those later associated elsewhere. |
| E. American-impact | Foreign-born people whose careers or influence became substantially associated with the United States. |

Fields on every candidate:

- `US_ASSOCIATION_TYPE`: Indigenous, Born_US, US_Citizen, Colonial_America, Territorial_America, Immigrant_American,
  Career_American, Cultural_American, Political_American, Other_Significant_US_Association. More than one may apply.
- `US_ASSOCIATION_CONFIDENCE`: 0–100.
- `US_ASSOCIATION_EVIDENCE`: the facts and sources behind the classification, so it can be audited.

## 3. Time architecture — eleven eras

Raw popularity is not comparable across centuries: the record is far denser for modern people. Prominence is normalised
within an era.

| Era | Years | Working name |
|---|---|---|
| I | 1400–1499 | Pre-Columbian / Contact Horizon |
| II | 1500–1599 | Early Contact |
| III | 1600–1699 | Colonial Formation |
| IV | 1700–1775 | Late Colonial |
| V | 1776–1799 | Founding |
| VI | 1800–1849 | Early Republic |
| VII | 1850–1899 | Expansion / Civil War / Industrialization |
| VIII | 1900–1945 | Early Modern America |
| IX | 1946–1979 | Postwar America |
| X | 1980–1999 | Late 20th Century |
| XI | 2000–2026 | Contemporary America |

These are QueryBook's own categories, not Pantheon's or Wikidata's.

## 4. Several rankings, never one

| Score | Measures |
|---|---|
| Historical Significance | Long-term historical impact |
| Cultural Recognition | How recognisable the person remains |
| Contemporary Popularity | Current public attention |
| Era Prominence | Standing against people of the same period |
| Domain Prominence | Standing within the person's field |
| QueryBook Composite Prominence (QB-P) | The combined index |

So "the most significant Americans of the 1700s" and "the most popular Americans alive today" are different queries.

### QB-P starting weights (the user's proposal, to be tuned)

| Component | Weight |
|---|---|
| Historical visibility | 25% |
| Cross-language recognition | 20% |
| Institutional significance | 20% |
| Public attention | 15% |
| Source density | 10% |
| Longevity | 10% |

QueryBook builds its own transparent measure from independently recorded attributes. It does not reproduce Pantheon's.

### Against modern-celebrity bias

Five signals are recorded apart: Current Attention, Persistent Attention, Historical Penetration (books, archives,
encyclopedias, collections), Cross-Cultural Penetration (languages and regions), Era Dominance. A 22-year-old with huge
traffic in 2026 does not outrank Abraham Lincoln.

### Time-aware popularity

`PROMINENCE_AS_OF`: every popularity measurement carries its measurement period. That allows "who had the most attention
in 2025" and "who stayed prominent for fifty years".

## 5. Facts and rankings are stored apart

| Layer | Holds |
|---|---|
| Fact layer | Source-derived assertions with provenance ("X was born in Y") |
| Analytical layer | Scores, rankings, classifications, calculated relationships ("X is the 327th most prominent") |

A ranking is a QueryBook output, never a historical fact.

Confidence is per fact, not per person: name 98, birth year 55, birthplace 72, occupation 95, US association 90.

## 6. Sources, in order of authority

| Tier | Source | Used for |
|---|---|---|
| 1 | Wikidata | Primary discovery layer: QID, names, aliases, birth and death, occupation, citizenship, birthplace, identifiers, relationships, sitelinks. References are kept; statements are not assumed equally authoritative. |
| 2 | Pantheon | Historical-prominence signals and candidates (biographies in more than 15 Wikipedia languages). Its place data is birthplace, not nationality: QueryBook decides American association itself. |
| 3 | Library of Congress Name Authority File | Identity resolution: authorised names and variant forms. |
| 4 | Other authoritative resources | Museums, archives, tribal and institutional sources, for under-represented groups and periods. |

Identity chain: `QB Person ID → Wikidata QID → LCNAF ID → VIAF ID → other identifiers`. A name is never the key. Samuel
Clemens, Mark Twain, "Twain, Mark" and Samuel Langhorne Clemens are one person.

### Legal and provenance ledger — on every ingestion job

`SOURCE_ID`, provider, dataset, URL, retrieved date, licence, allowed use, attribution requirement, raw record hash,
transformation history, UFCS records generated.

### Not done

No manual "top 10,000 Americans" searches. No scraping of IMDb rankings, celebrity sites, "famous people" sites,
proprietary biographies or commercial ranking pages. Candidates are generated from reusable structured sources;
contractors then harvest verified facts about a given `QB-PER-…` identity.

## 7. The person record (UFCS)

| Group | Fields |
|---|---|
| Identity | Canonical name, given name, family name, alternative names, pseudonyms, titles |
| Time | Birth date, death date, precision of each |
| Geography | Birth location, death location, primary residence, associated places |
| Historical geography | Political entity at birth, modern geographic equivalent (essential for 1400–1775) |
| American association | Type, confidence, evidence (section 2) |
| Roles | Every significant role with its period — not one profession |

### Domains — a person may hold several

Government & Politics, Military, Law & Judiciary, Business & Finance, Science, Medicine, Technology, Engineering,
Invention, Education, Religion, Philosophy, Civil Rights & Social Movements, Literature, Journalism & Media, Visual Arts,
Architecture, Music, Stage, Film, Television, Digital Media, Sports, Exploration, Agriculture, Labor, Crime & Criminal
Justice, Activism, Other.

The question is not "what was this person's profession" but "what significant roles did this person hold, and when".
Ronald Reagan: actor, governor, president. Arnold Schwarzenegger: bodybuilder, actor, businessman, governor.

## 8. Pre-1600 recovery track

The written record for 1400–1600 over-represents some populations and European sources. A separate track uses museum,
archival, archaeological, historical and tribal or institutional material. "No Wikipedia page" means the digital record
is thin, not that the person was unimportant.

The prototype deliberately oversamples early periods (minimum coverage for 1400–1599, 1600–1699, 1700–1775, 1776–1799).
Exact quotas are set only after the candidate distribution has been inspected.

## 9. Pipeline

```
Wikidata  →  humans associated with American geography, citizenship, identity
Pantheon  →  historically prominent candidates added
Library of Congress  →  canonical identity reconciliation
Other authoritative resources  →  under-represented categories
Entity resolution  →  duplicates removed
UFCS creation  →  factual claims atomised
Scoring engine  →  prominence calculated
Human review  →  edge cases and high-value identities
QueryBook American People Index
```

## 10. Output — lists are generated, not stored

FQL produces them from facts and ranking attributes: Top Americans of all time, by century, by decade, living, deceased;
top scientists, inventors, political leaders, business leaders, writers, musicians, actors, athletes, civil-rights
leaders, religious leaders, Indigenous leaders, women in American history.

The graph: People → Places → Events → Organizations → Works → Inventions → Offices → Movements → Relationships →
Achievements → Controversies → Historical Events → Sources. Example questions:

- The 100 most historically prominent American scientists born 1800–1900 who are associated with an invention.
- American political figures whose prominence rose substantially after their deaths.
- Cultural longevity of actors, musicians, presidents and athletes born 1900–1950, compared.

## 11. Build sequence

| Phase | Work |
|---|---|
| 1 | Candidate universe: Wikidata + Pantheon |
| 2 | American-association classification, aware of historical geography |
| 3 | Identity resolution: Wikidata + Library of Congress + other identifiers |
| 4 | 25,000-person prototype |
| 5 | UFCS factual harvesting |
| 6 | QueryBook Prominence Engine |
| 7 | 100,000+ American-associated people |
| 8 | People → events → organizations → places → works relationship graph |

## 12. What QueryBook already has that this builds on

| Plan item | Exists today | Where |
|---|---|---|
| Wikidata as discovery layer, ranked lists with every code's label checked | Yes | `qbbulk.domain_discover`, `ICONS`, `DOMAINS` |
| Whole Wikidata records read by three routes | Yes | `WikidataHot._entities`, `entitydata_entities`, `wdqs_entities` |
| Cross-language recognition (Wikipedias with an article) | Yes, per record | `fame` table, `wd_fame` |
| Public attention, summed over sampled months | Yes, top 1,000 a month only | `hot-most-read`, `wd_views` |
| Aliases and name forms (Mark Twain / Samuel Clemens) | Yes for well-known items | `alias`, `names` tables, `find_entities` |
| The relationship graph, ring by ring | Yes, three rings | `hot-circle`, `CIRCLE_TIES` |
| Several roles per person, the best known identified | Yes, without periods | `sense.known_for`, `ROLES` |
| Icons in categories; chosen by leadership, wealth, influence | Yes, twelve categories | `ICON_CATEGORIES`, the icons sets |
| Culture weighting for the United States | Yes | `bulk:culture`, `CULTURE` |
| Fact identity and provenance per fact | Yes | `qbcore.fingerprint`, shard `links` |
| Rights gate and rights record | Yes, for books | `qbbooks.rights_record` |

## 13. Not built yet — the honest list

| Item | Needed |
|---|---|
| `QB-PER` person identity and identifier chain | New table keyed by QID with LCNAF, VIAF and other identifiers (Wikidata carries these as P244 and P214: read them from records already harvested) |
| American-association classifier (type, confidence, evidence) | New pure module; rules over citizenship, birthplace, residence, offices, with historical geography (a 1650 birthplace in "Massachusetts Bay Colony" → modern equivalent) |
| Historical geography: political entity at birth vs modern equivalent | A dated table of polities for present-day U.S. territory |
| Eras and era-normalised prominence | Era from birth and active years; percentile within era |
| The six scores and QB-P | Analytical layer, stored apart from facts, each with `PROMINENCE_AS_OF` |
| Roles with periods | Start and end dates are in Wikidata's qualifiers, which the harvester does not keep yet |
| Per-fact confidence | Today a fact has a status, not a 0–100 confidence |
| Pantheon ingest | Its dataset licence and terms must be read and recorded in the ledger before any ingest |
| Library of Congress ingest | Bulk authority files; licence recorded the same way |
| Source ledger on every ingestion job | Extends the existing provenance |
| Pre-1600 recovery track | Sources to be chosen with the user |
| The domain taxonomy of section 7 (29 domains) | Finer than today's twelve icon categories; a mapping from Wikidata occupations |
| Human review queue | Not started |

### Open points to settle before Phase 1 is coded

1. Licences are recorded from the source's own page at ingest time, never from memory. Wikidata's structured data is
   CC0. Pantheon's and the Library of Congress's terms are to be read and written into the ledger first.
2. Signals for "historical visibility", "institutional significance" and "source density" need definitions that can be
   computed. Candidates: count of external identifiers on the record (libraries, archives, museums), count of
   references, presence in LCNAF, number of works about the person held.
3. Era quotas for the prototype wait for the candidate distribution (section 8).
