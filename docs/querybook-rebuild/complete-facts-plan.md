# Complete facts: dates, sources and rank — what is built, and the plan for the facts already held

Status: 2026-11-13, engine 1.48. Stages 0 and 1 are built and tested. Stages 2–6 are the plan; nothing in them is built.

## The gap

A Wikidata statement says more than subject → predicate → object. It says **when** it held (start time, end time, point
in time), carries other qualifiers (whom an office-holder replaced, the work an award was for), has a **rank**
(preferred, normal, deprecated) and names its **sources** (stated in, reference address, date retrieved).

Until 1.48 the harvester kept the main value only: "Ronald Reagan — position held — Governor of California", with no
years and no source. About 1.5 billion facts in the store are in that state.

## How the context is stored

Beside the fact, never inside it. The dataset's label file gains a `context` table keyed by item, predicate and value
exactly as the fact is stored:

| Column | Holds |
|---|---|
| `rank` | preferred / normal |
| `start`, `end`, `at` | start time, end time, point in time, each at its own precision |
| `quals` | the other qualifiers, by property name |
| `refs` | up to three sources: stated in, address, retrieved, published, title, imported from |

Consequences:

- The fact store and every fingerprint are unchanged. Nothing is rewritten on the data drive.
- A fact read a second time gains its context without becoming a second fact.
- A statement with no dates, qualifiers, sources or special rank stores nothing extra.

## Stage 0 — every new harvest keeps the context (built)

| Route | Dates and qualifiers | Rank | Sources |
|---|---|---|---|
| Hot list, icons, circle, most-read, demand, lattices, complete domains | Yes | Yes | Yes |
| Dump lanes (the bulk of Wikidata) | Yes | Yes | No — see stage 2 |
| Records that arrive through the query service (last-resort route) | No | No | No — marked to be read again |

Answers use it: "Played for Boston Red Sox (1914–1919), New York Yankees (1920–1934), Boston Braves (1935)". The Ask
page shows each fact's period, qualifiers and "Stated in". Nothing is shown when the store holds no date.

Measured on three real records (Reagan, The Beatles, Babe Ruth): 308 facts, 172 with context, 83 dated, 133 with a
named source.

## Stage 1 — the well-known records already held (built; runs by itself)

`hot-context` lists every record held that is written about in five or more Wikipedias and was read before 1.48, the
best known first, and reads it again in waves of 5,000. It writes **no facts** (they are held already; a second copy
would be counted twice) — only the context. It blocks nothing, waits for nothing, and is exempt from the "no new fact"
rest, since adding no fact is what it is for.

Progress is on Harvesting → Relevance: statements with context, dated, sourced, records done, records waiting.

Speed: the records service gives 50 records a request; the fallback measured about 100 records a minute. How long the
stage takes depends on how many well-known records the store holds, which the page will show as "waiting" once 1.48
runs on it. I have not measured that on the real store.

## Stage 2 — the rest of the 1.5 billion (plan)

Most facts came from the dump lanes. Three options, in my order of preference:

| Option | How | Cost | Completes |
|---|---|---|---|
| A. With the next edition | The lanes already write context for every statement they pass, held or not. When the next Wikidata edition is read, every statement in it gets its dates, qualifiers and rank. | Nothing extra to build. Some extra disk (measure on the first parts before committing). | When that edition has been read — weeks at current speed |
| B. A context-only pass over the dump already on the drive | Read the local dump file again, extracting context only: no facts written, no fingerprints computed. | New code (a lane mode). Fast, since nothing is merged. | Days rather than weeks |
| C. Extend stage 1 below five Wikipedias | Lower `CONTEXT_FAME` step by step. | None to build; millions of single-record requests. | Too slow for the long tail |

Recommendation: A happens anyway. Build B if the wait is unacceptable. Do not use C beyond the well-known records.

**Sources for the lanes** are off (`CONTEXT_LANE_REFS`). Most Wikidata statements carry a reference, so keeping them
for a billion statements could add tens of gigabytes to the external drive. Decide after measuring the size on one part.

## Stage 3 — facts that are not from Wikidata (plan)

PubChem, the taxonomy, weather stations, place names, food data and the others have no per-fact qualifiers. Their date
and source exist at the level of the file: its edition, its licence, its address. Those are already recorded per part.
The plan is to show the part's edition as the fact's "as of" date, and to leave rank empty rather than invent one.

## Stage 4 — values that were superseded (plan)

Today a preferred statement hides the normal ones for the same property, and deprecated statements are dropped. That
loses history: earlier populations, former names, offices held before. The plan is to keep superseded values as dated
history beside the current value — clearly marked as not current — and to keep deprecated ones out of answers entirely.

## Stage 5 — confidence per fact (plan)

With rank and sources held, a per-fact confidence becomes computable instead of asserted: number of independent
sources, kind of source (a named work or institution against "imported from Wikipedia"), rank, and agreement between
sources. This is the per-fact confidence the Top Americans plan calls for. The weights are to be agreed before any
number is shown.

## Stage 6 — roles with periods in the analysis (plan)

`sense.known_for` ranks a person's roles without using their dates. With periods held it can say what a person was at a
given time, order a career, and feed era prominence. It also allows "who held this office in 1850".

## What is not verified

- Nothing was run against the real 1.5-billion-fact store.
- The dump lanes' context was tested through the shared record reader, not by reading a real dump part.
- Disk growth for the lanes is an estimate, not a measurement.
