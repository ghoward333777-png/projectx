"""History app — answers come back as a chronological timeline, grouped into
eras, filtered by any date range in the question."""

from __future__ import annotations

import re
from typing import Any

from querybook.apps.base import DomainApp, QueryContext, fql_str, source_ref
from querybook.core.model import DOMAIN_COLLECTIONS
from querybook.core.text import STOPWORDS, sentences, tokenize

ERA_YEAR = re.compile(r"\b(\d{1,4})\s*(BCE|BC|CE|AD)\b", re.I)
PLAIN_YEAR = re.compile(r"(?<![\d.,$£€])\b(1\d{3}|20\d{2})(s?)\b(?!\s?(?:%|kg|km|m\b|g\b|mph|°))")
CENTURY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\s+century(?:\s+(BCE|BC|CE|AD))?", re.I)
ENTITY = re.compile(r"\b([A-Z][a-z]+(?:\s+(?:of\s+|the\s+|de\s+|von\s+)?[A-Z][a-z]+)+)\b")
ERAS = ((-10**6, 499, "Ancient"), (500, 1499, "Medieval"), (1500, 1799, "Early modern"),
        (1800, 1945, "Modern"), (1946, 10**6, "Contemporary"))


def era_of(year: int) -> str:
    return next(name for lo, hi, name in ERAS if lo <= year <= hi)


def year_label(year: int) -> str:
    if year < 0:
        return f"{-year} BCE"
    return f"{year} CE" if year < 1000 else str(year)


def find_years(text: str) -> list[int]:
    years: list[int] = []
    for m in ERA_YEAR.finditer(text):
        y = int(m.group(1))
        years.append(-y if m.group(2).upper() in ("BC", "BCE") else y)
    masked = ERA_YEAR.sub(" ", text)
    years += [int(m.group(1)) for m in PLAIN_YEAR.finditer(masked)]
    return years


def parse_range(q: str) -> tuple[int | None, int | None, str]:
    """Pull a year range out of a question; returns (from, to, remaining topic text)."""
    lo = hi = None
    rest = q
    m = CENTURY.search(q)
    if m:
        n, bce = int(m.group(1)), (m.group(2) or "").upper() in ("BC", "BCE")
        lo, hi = ((-(n * 100), -((n - 1) * 100 + 1)) if bce else ((n - 1) * 100 + 1, n * 100))
        rest = q[:m.start()] + q[m.end():]
    else:
        years = find_years(q)
        decade = re.search(r"\b(1\d{3}|20\d{2})s\b", q)
        if len(years) >= 2:
            lo, hi = min(years[:2]), max(years[:2])
        elif decade:
            lo = int(decade.group(1))
            hi = lo + (99 if lo % 100 == 0 else 9)
        elif len(years) == 1:
            if re.search(r"\b(?:after|since)\b", q, re.I):
                lo, hi = years[0], None
            elif re.search(r"\b(?:before|until|prior to)\b", q, re.I):
                lo, hi = None, years[0]
            else:
                lo = hi = years[0]
        rest = PLAIN_YEAR.sub(" ", ERA_YEAR.sub(" ", q))
    rest = re.sub(r"\b(?:between|from|to|and|in|during|after|before|since|until|the|what|happened|history|of|"
                  r"timeline|events?|when|did|was|were)\b", " ", rest, flags=re.I)
    return lo, hi, " ".join(rest.replace("?", " ").replace("-", " ").split())


class HistoryApp(DomainApp):
    key = "history"
    title = "History"
    collection = DOMAIN_COLLECTIONS["history"]
    tagline = "Timelines, eras and the evidence behind them"
    placeholder = "Topic or period — e.g. printing press, or 1750 to 1850"
    examples = ("printing press", "1750 to 1850", "Roman Republic", "20th century")

    def enrich(self, title: str, body: str) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        for s in sentences(f"{title}. {body}" if title else body):
            for y in dict.fromkeys(find_years(s)):  # every distinct year in the sentence is its own event
                events.append({"year": y, "label": year_label(y), "text": s[:300]})
        events = events[:60]
        years = [e["year"] for e in events] or find_years(f"{title} {body}")
        counts: dict[str, int] = {}
        for m in ENTITY.finditer(body):
            name = m.group(1)
            if name.split()[0].lower() not in STOPWORDS:
                counts[name] = counts.get(name, 0) + 1
        entities = [k for k, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]]
        out: dict[str, Any] = {"events": events, "entities": entities}
        if years:
            out.update(start_year=min(years), end_year=max(years), era=era_of(min(years)))
        return out

    def respond(self, ctx: QueryContext, query: str) -> dict[str, Any]:
        lo, hi, topic = parse_range(query)
        docs: list[dict[str, Any]] = []
        if topic:
            docs = ctx.docs(f"History.search({fql_str(topic)}).take(40)")
        if lo is not None or hi is not None:
            conds = [".start_year != null"]
            if hi is not None:
                conds.append(f".start_year <= {hi}")
            if lo is not None:
                conds.append(f".end_year >= {lo}")
            in_range = ctx.docs(f"History.where({' && '.join(conds)}).order(.start_year).take(200)")
            if topic:
                ids = {d["id"] for d in in_range}
                docs = [d for d in docs if d["id"] in ids] or docs
            else:
                docs = in_range
        topic_toks = {t for t in tokenize(topic) if t not in STOPWORDS and len(t) > 2}
        events, seen = [], set()
        for rank, doc in enumerate(docs):
            for ev in doc.get("events") or []:
                y = ev.get("year")
                if not isinstance(y, int):
                    continue
                if (lo is not None and y < lo) or (hi is not None and y > hi):
                    continue
                if topic_toks and rank >= 3 and not topic_toks & set(tokenize(ev.get("text", ""))):
                    continue
                key = (y, ev.get("text", ""))
                if key in seen:
                    continue
                seen.add(key)
                events.append({"year": y, "label": year_label(y), "era": era_of(y), "text": ev.get("text", ""),
                               "title": doc.get("title", ""), "id": doc.get("id")})
        # Dated facts the QueryBook suite already holds (Commons + bulk shards) join the timeline.
        store_facts = ctx.store_facts(topic or query, 40)
        for f in store_facts:
            text = f"{f.get('subject', '')} — {f.get('predicate', '')}: {f.get('object', '')}"
            for y in dict.fromkeys(find_years(str(f.get("object", "")))):
                if (lo is not None and y < lo) or (hi is not None and y > hi) or (y, text) in seen:
                    continue
                seen.add((y, text))
                events.append({"year": y, "label": year_label(y), "era": era_of(y), "text": text,
                               "title": f.get("dataset") or f"Commons · {f.get('status', '')}", "id": f.get("id")})
        events.sort(key=lambda e: (e["year"], e["text"]))
        events = events[:80]
        eras: list[dict[str, Any]] = []
        for e in events:
            if eras and eras[-1]["era"] == e["era"]:
                eras[-1]["count"] += 1
                eras[-1]["to"] = e["label"]
            else:
                eras.append({"era": e["era"], "count": 1, "from": e["label"], "to": e["label"]})
        span = (f" between {year_label(lo)} and {year_label(hi)}" if lo is not None and hi is not None and lo != hi
                else f" in {year_label(lo)}" if lo is not None and lo == hi
                else f" from {year_label(lo)}" if lo is not None else f" up to {year_label(hi)}" if hi is not None else "")
        summary = (f"{len(events)} dated event{'s' if len(events) != 1 else ''}{span} across {len(eras)} "
                   f"era{'s' if len(eras) != 1 else ''}." if events else f"No dated events{span} yet.")
        return {"kind": "timeline", "summary": summary, "subject": topic or query, "topic": topic,
                "store_facts": store_facts[:12],
                "range": {"from": lo, "to": hi}, "events": events, "eras": eras,
                "sources": [source_ref(d) for d in docs[:15]]}
