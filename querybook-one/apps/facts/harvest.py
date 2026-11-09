"""The History & News harvest team (see qbcommons for the four agents).

What it harvests into the Commons: every fact here that has at least one documented source (never an AI
service — the application refuses those), each source as separate evidence, and the latest news
headlines as "reported by" (not confirmed) until someone adds them as facts. It refreshes the news
feeds you added, a few per cycle.

What it asks of the other applications: Math, Science & Engineering checks that each person's birth and
death dates give a possible lifespan.
What it answers for them: whether a documented source records a statement.
"""
import datetime

import qbcommons as cm

LIC_SOURCE = "facts are not copyrightable; source cited"
LIC_HEADLINE = "headline quoted with a link to the publisher"
BUDGET = {"facts": 300, "feeds": 5, "headlines": 200, "feed_age_h": 6}
BIRTH = ("born on", "date of birth")
DEATH = ("died on", "date of death")


def hours_ago(h):
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=h)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class FactsAdapter(cm.Adapter):
    def budgets(self):
        return {"facts": BUDGET["facts"], "feeds": BUDGET["feeds"], "headlines": BUDGET["headlines"]}

    def __init__(self, app, dates, old_kind, single_valued):
        self.app = app
        self.dates = dates
        self.old_kind = old_kind
        self.single = single_valued

    def _sourced_sql(self):
        return """EXISTS (SELECT 1 FROM fact_sources fs JOIN sources s ON s.id = fs.source_id WHERE fs.fact_id = f.id AND s.kind <> ?)"""

    # ------------------------------------------------------------------ Strategist
    def survey(self, ctx):
        q = self.app.store.scalar
        cutoff = hours_ago(BUDGET["feed_age_h"])
        return {"facts": q("SELECT count(*) FROM facts", default=0),
                "sourced": q("SELECT count(*) FROM facts f WHERE " + self._sourced_sql(), (self.old_kind,), 0),
                "sourced_not_shared": q("SELECT count(*) FROM facts f WHERE f.id > ? AND " + self._sourced_sql(), (ctx.cursor("facts"), self.old_kind), 0),
                "feeds": q("SELECT count(*) FROM feeds WHERE url NOT LIKE 'https://www.youtube.com/#%'", default=0),
                "feeds_due": q("SELECT count(*) FROM feeds WHERE url NOT LIKE 'https://www.youtube.com/#%' AND (last_fetched IS NULL OR last_fetched < ?)", (cutoff,), 0),
                "headlines_not_shared": q("SELECT count(*) FROM headlines WHERE id > ?", (ctx.cursor("headlines"),), 0)}

    def strategy(self, sv, ctx):
        goals = []
        n_open = ctx.commons.store.scalar("SELECT count(*) FROM requests WHERE to_app = 'facts' AND status = 'open'", default=0)
        if n_open:
            goals.append({"goal": "Answer %d checks from the other applications" % n_open, "priority": 1,
                          "why": "they asked whether a documented source records a statement"})
        if sv["sourced_not_shared"]:
            goals.append({"goal": "Share the sourced facts", "priority": 2,
                          "why": "%d facts with documented sources are not in the Commons yet; birth and death dates go to Math & Science for a lifespan check" % sv["sourced_not_shared"]})
        news_ok = ctx.source_ok("news-headlines")
        if not news_ok and (sv["feeds_due"] or sv["headlines_not_shared"]):
            goals.append({"goal": "Leave news headlines out", "priority": 5,
                          "why": "the policy registry blocks headlines (the publishers' own wording); a news item enters the store "
                                 "only when you add it as a fact with its source"})
        if sv["feeds_due"] and news_ok:
            goals.append({"goal": "Refresh the news feeds", "priority": 3,
                          "why": "%d of your %d feeds were last read more than %d hours ago" % (sv["feeds_due"], sv["feeds"], BUDGET["feed_age_h"])})
        if (sv["headlines_not_shared"] or sv["feeds_due"]) and news_ok:
            goals.append({"goal": "Share the latest headlines as reported", "priority": 4,
                          "why": "news is shared as 'reported by', never as confirmed, until it is added as a fact with its source"})
        return {"goals": goals, "budget": BUDGET,
                "sources": [{"name": "Your sources: books, newspapers, archives, records, people", "licence": LIC_SOURCE, "use": "sourced facts"},
                            {"name": "Your news feeds", "licence": LIC_HEADLINE, "use": "reported headlines"},
                            {"name": "AI services", "licence": "—", "use": "never: refused as sources"}]}

    # ------------------------------------------------------------------ Planner
    def plan(self, st, ctx):
        names = {g["goal"] for g in st["goals"]}
        why = {g["goal"]: g["why"] for g in st["goals"]}
        tasks = []
        if "Share the sourced facts" in names:
            lim = int(ctx.budget("facts", BUDGET["facts"]))
            tasks.append({"action": "facts", "title": "Share up to %d sourced facts" % lim, "target": {"after": ctx.cursor("facts"), "limit": lim},
                          "source": "history-user-sources", "budget_key": "facts", "why": why["Share the sourced facts"]})
        if "Refresh the news feeds" in names:
            cutoff = hours_ago(BUDGET["feed_age_h"])
            feeds = self.app.store.query("""SELECT id, name FROM feeds WHERE url NOT LIKE 'https://www.youtube.com/#%' AND (last_fetched IS NULL OR last_fetched < ?)
                                            ORDER BY coalesce(last_fetched, ''), id LIMIT ?""", (cutoff, int(ctx.budget("feeds", BUDGET["feeds"]))))
            for f in feeds:
                tasks.append({"action": "feed", "title": "Read the feed %s" % f["name"], "target": {"feed": f["id"]}, "source": "news-headlines",
                              "budget_key": "feeds", "why": why["Refresh the news feeds"]})
        if "Share the latest headlines as reported" in names:
            lim = int(ctx.budget("headlines", BUDGET["headlines"]))
            tasks.append({"action": "headlines", "title": "Share up to %d headlines as reported" % lim, "target": {"limit": lim},
                          "source": "news-headlines", "budget_key": "headlines", "why": why["Share the latest headlines as reported"]})
        return tasks

    # ------------------------------------------------------------------ Harvester
    def execute(self, task, ctx):
        a, t = task["action"], task.get("target") or {}
        if a == "facts":
            rows = self.app.store.query("SELECT f.* FROM facts f WHERE f.id > ? AND " + self._sourced_sql() + " ORDER BY f.id LIMIT ?",
                                        (t["after"], self.old_kind, t["limit"]))
            items = [self._fact(r) for r in rows]
            return {"items": items, "cursor": {"facts": rows[-1]["id"]} if rows else {}, "detail": "%d facts" % len(items)}
        if a == "feed":
            r = self.app.fetch_feed(t["feed"])
            return {"items": [], "detail": "%s new headlines (%s)" % (r.get("new_headlines"), r.get("status"))}
        if a == "headlines":
            # read the cursor now: a feed task earlier in this plan may have added headlines
            rows = self.app.store.query("""SELECT h.*, f.name AS feed_name FROM headlines h JOIN feeds f ON f.id = h.feed_id
                                           WHERE h.id > ? ORDER BY h.id LIMIT ?""", (ctx.cursor("headlines"), t["limit"]))
            items = [{"subject": h["title"][:300], "predicate": "reported by", "object": h["author"] or h["feed_name"],
                      "statement": h["summary"][:500] if h["summary"] else None,
                      "evidence": [{"method": "report", "source": h["author"] or h["feed_name"], "licence": LIC_HEADLINE, "url": h["link"],
                                    "detail": "published %s" % (h["published"] or "date not given")}],
                      "reasoning": ["Read from the feed %s; shared as reported, not confirmed." % h["feed_name"]]} for h in rows]
            return {"items": items, "cursor": {"headlines": rows[-1]["id"]} if rows else {}, "detail": "%d headlines" % len(items)}
        raise ValueError("unknown task %s" % a)

    def _date(self, text):
        try:
            d = self.dates.parse(text)
        except Exception:
            return None
        return {"year": d["year"], "month": d["month"], "day": d["day"], "label": d["label"]} if d and not d["approx"] else None

    def _fact(self, r):
        srcs = self.app.store.query("""SELECT s.*, fs.quote, fs.page FROM fact_sources fs JOIN sources s ON s.id = fs.source_id
                                       WHERE fs.fact_id = ? AND s.kind <> ? ORDER BY s.name""", (r["id"], self.old_kind))
        pred = r["predicate"] or ("happened on" if r["date_text"] else "is recorded as")
        obj = r["object"] or (r["date_text"] if r["date_text"] and not r["predicate"] else r["statement"])
        item = {"subject": r["subject"], "predicate": pred, "object": obj, "statement": r["statement"],
                "evidence": [{"method": "source", "source": s["name"] + (" (%s)" % s["author"] if s["author"] else ""), "licence": LIC_SOURCE,
                              "url": s["url"], "quote": (s["quote"] or "")[:300] or None,
                              "detail": "; ".join(x for x in (s["kind"], ("p. " + s["page"]) if s["page"] else None, s["published"]) if x)} for s in srcs],
                "reasoning": ["Recorded in History & News with %d documented source%s." % (len(srcs), "" if len(srcs) == 1 else "s")],
                "checks": []}
        if r["disputed"]:
            item["reasoning"].append("Other sources give a different value for this; History & News shows them side by side.")
        if (r["predicate"] or "") in DEATH:
            born = self.app.store.one("SELECT object, date_text FROM facts WHERE lower(subject) = lower(?) AND predicate IN (?, ?) ORDER BY id LIMIT 1",
                                      (r["subject"],) + BIRTH)
            b = born and self._date(born["date_text"] or born["object"])
            d = self._date(r["date_text"] or r["object"])
            if b and d:
                item["checks"].append({"kind": "lifespan", "payload": {"subject": r["subject"], "born": b, "died": d}})
                item["reasoning"].append("Asked Math, Science & Engineering whether born %s and died %s give a possible lifespan." % (b["label"], d["label"]))
        return item

    # ------------------------------------------------------------------ Curator upkeep: keep shared facts in step with their sources
    def curate(self, ctx):
        """Re-share a window of already-shared facts, so sources added or removed since are reflected."""
        after, upto = ctx.cursor("resync"), ctx.cursor("facts")
        rows = self.app.store.query("SELECT f.* FROM facts f WHERE f.id > ? AND f.id <= ? AND " + self._sourced_sql() + " ORDER BY f.id LIMIT ?",
                                    (after, upto, self.old_kind, BUDGET["facts"]))
        ctx.commons.set_setting("cursor:facts:resync", rows[-1]["id"] if len(rows) == BUDGET["facts"] else 0)
        return [dict(self._fact(r), sync=True) for r in rows]

    # ------------------------------------------------------------------ checks for the other applications
    def verifiers(self, ctx):
        return {"sourced": self.check_sourced}

    def check_sourced(self, p):
        rows = self.app.store.query("SELECT f.id, f.object, f.statement FROM facts f WHERE lower(f.subject) = lower(?) AND coalesce(f.predicate, '') = lower(?) AND "
                                    + self._sourced_sql(), (p.get("subject") or "", p.get("predicate") or "", self.old_kind))
        if not rows:
            return {"verdict": "cannot_check", "detail": "no documented source here mentions it",
                    "reasoning": ["Searched History & News for %s — %s with a documented source; none found." % (p.get("subject"), p.get("predicate"))]}
        want = " ".join(str(p.get("object") or "").lower().split())
        same = [r for r in rows if " ".join(str(r["object"] or "").lower().split()) == want]
        if same:
            return {"verdict": "supports", "detail": "recorded with a documented source (fact %d)" % same[0]["id"],
                    "reasoning": ["History & News records the same value with a documented source."]}
        if (p.get("predicate") or "").lower() in self.single:
            return {"verdict": "contradicts", "detail": "sources here give %s" % ", ".join(sorted({str(r["object"]) for r in rows})),
                    "reasoning": ["This can have only one value, and the documented sources here give a different one."]}
        return {"verdict": "cannot_check", "detail": "sources here record other values, which may also be true",
                "reasoning": ["The predicate can have several values; a different one does not rule this out."]}
