"""qbkeystone — the keystone domains: what the harvest should cover, in what order, and how far it has got — measured.

Adopted from the UFCS prototype's planning engine (its 20 keystone domains in five phases, the "unlocks" graph, the
priority score and the growth / saturation states), with its flaws removed:

  * one definition, here, used by every program (the prototype kept two copies that could drift);
  * coverage is MEASURED from the facts actually held (shards and the shared store), never an estimated yield;
  * novelty is measured from the harvest log (new facts ÷ records read), never a fixed guess; a domain is
    "saturated" only when its sources have been read in quantity and almost nothing new arrives;
  * the priority steers collection: the bulk runner starts datasets in this order (the prototype's priorities lived
    in the browser and never reached its importer); the admin's Control Panel target still comes first;
  * probe questions are offered to the fact gatherer (an LLM finds, the page must confirm) — never answered here.

No AI model, no network: fixed rules over local counts.
"""
import collections, datetime, json, os, re

PHASE_WEIGHT = {0: 2000, 1: 1500, 2: 1000, 3: 500, 4: 100}
SATURATED_NOVELTY = 0.01            # under 1% of records read are new …
SATURATED_MIN_READ = 1_000_000      # … over at least a million records read: the sources have little left to give

# key: (label, phase, directly unlocks, probe questions for the fact gatherer — {month} {year} filled with the current month)
KEYSTONES = {
    "mathematics": ("Mathematics", 0, ["physics", "technology_computing", "economics_finance"],
                    ["Which mathematical problems or conjectures were reported solved in {year}?",
                     "Who received the Fields Medal or the Abel Prize most recently?"]),
    "scientific_concepts": ("Scientific concepts and literature", 0, ["physics", "chemistry_materials", "medicine_health", "astronomy"],
                            ["Which scientific discoveries were announced in {month} {year}?"]),
    "technology_computing": ("Technology and computing", 0, ["products_objects", "transportation"],
                             ["Which major software or programming language versions were released in {month} {year}?"]),
    "languages": ("Languages", 0, ["culture_arts", "law_governance"],
                  ["Which words were added to major English dictionaries in {year}?"]),
    "geographic_entities": ("Places and geography", 1, ["nation_states", "transportation", "food_agriculture"],
                            ["Which cities or regions changed their official name in {year}?"]),
    "human_individuals": ("People", 1, ["organizations", "culture_arts", "historical_events"],
                          ["Which notable people died in {month} {year}?", "Who won the Nobel Prizes in {year}?"]),
    "historical_events": ("Events and history", 1, ["nation_states", "law_governance"],
                          ["Which national elections were held in {month} {year}, and who won?",
                           "Which major international sporting championships ended in {month} {year}, and who won?"]),
    "life_forms": ("Living things", 1, ["medicine_health", "food_agriculture"],
                   ["Which new animal or plant species were described in {year}?"]),
    "nation_states": ("Countries and states", 2, ["law_governance", "economics_finance"],
                      ["Which countries changed head of state or head of government in {month} {year}?"]),
    "law_governance": ("Law and government", 2, ["organizations"],
                       ["Which major laws were enacted in {month} {year}?"]),
    "organizations": ("Organisations", 2, ["products_objects", "economics_finance"],
                      ["Which large companies appointed a new chief executive in {month} {year}?"]),
    "culture_arts": ("Culture and the arts", 2, [],
                     ["Which films, books or albums won major awards in {year}?"]),
    "physics": ("Physics", 3, ["astronomy", "chemistry_materials"],
                ["Which physics results were announced in {month} {year}?"]),
    "chemistry_materials": ("Chemistry and materials", 3, ["medicine_health", "products_objects"],
                            ["Which new chemical elements, compounds or materials were reported in {year}?"]),
    "medicine_health": ("Medicine and health", 3, ["food_agriculture"],
                        ["Which new medicines were approved by the FDA in {month} {year}?"]),
    "economics_finance": ("Economics and finance", 3, ["products_objects"],
                          ["What were the latest official inflation and unemployment figures published in {month} {year}?"]),
    "astronomy": ("Astronomy and space", 3, [],
                  ["Which space missions launched in {month} {year}?"]),
    "products_objects": ("Products and objects", 4, ["transportation"],
                         ["Which notable products were launched in {month} {year}?"]),
    "food_agriculture": ("Food and agriculture", 4, [], ["Which crop harvest records or estimates were published in {year}?"]),
    "transportation": ("Transport", 4, [], ["Which new airports, railway lines or bridges opened in {year}?"]),
}

# which keystone each bulk dataset feeds (the Wikidata lanes count their entities one by one: CLASSES below)
DATASETS = {"pubchem-computed": "chemistry_materials", "ncbi-taxonomy": "life_forms", "noaa-ghcn-daily": "geographic_entities",
            "usgs-gnis": "geographic_entities", "usda-fooddata-central": "food_agriculture", "tatoeba-cc0": "languages",
            "calendar-scaffold": "historical_events", "wikidata-series": "historical_events", "mit-ocw": "scientific_concepts"}
COMMONS_DOMAIN = {"language": "languages", "stem": "scientific_concepts", "history": "historical_events"}

# Wikidata "instance of" classes → keystone (the most common classes; anything else falls back on its properties)
CLASSES = {}
for _k, _qs in {
    "human_individuals": "Q5",
    "geographic_entities": "Q486972 Q515 Q532 Q3957 Q23397 Q4022 Q8502 Q54050 Q35666 Q39816 Q23442 Q5119 Q1549591 Q15284 Q747074 Q484170 "
                           "Q2039348 Q3024240 Q13100073 Q15640612 Q12323 Q46831 Q355304 Q166735 Q185113 Q47521 Q40080",
    "life_forms": "Q16521 Q310890 Q23038290",
    "scientific_concepts": "Q13442814 Q1980247 Q7318358 Q591041 Q1266946 Q187685",
    "astronomy": "Q523 Q318 Q3863 Q83373 Q1153690 Q2154519 Q67206691 Q1457376 Q13632 Q2247863 Q1332364 Q11282 Q11276 Q204107 Q72802727",
    "chemistry_materials": "Q11173 Q113145171 Q59199015 Q11344 Q79529 Q214609",
    "medicine_health": "Q7187 Q8054 Q12136 Q277338 Q12140 Q28885102 Q169872",
    "organizations": "Q43229 Q4830453 Q783794 Q3918 Q9842 Q163740 Q31855 Q891723 Q2085381 Q875538 Q15936437 Q16917 Q38723 Q476028",
    "culture_arts": "Q11424 Q7366 Q482994 Q5398426 Q571 Q3305213 Q47461344 Q105543609 Q134556 Q7725634 Q21198342 Q838948 Q21191270 Q860861",
    "historical_events": "Q1656682 Q178561 Q198 Q40231 Q27020041 Q16510064 Q18608583 Q1190554 Q13406554 Q46190676",
    "nation_states": "Q6256 Q3624078 Q3024240",
    "law_governance": "Q7748 Q820655 Q2334719 Q4164871 Q7188 Q1752346 Q15238777",
    "languages": "Q34770 Q1288568 Q33742 Q25295 Q38058796",
    "products_objects": "Q2424752 Q10929058 Q1183543 Q22811234",
    "transportation": "Q1248784 Q55488 Q34442 Q12280 Q11446 Q1420 Q15056995 Q928830 Q2551525",
    "food_agriculture": "Q2095 Q746549 Q10675206 Q1364 Q11004 Q10990",
    "economics_finance": "Q8142 Q11691 Q1166072",
    "mathematics": "Q24034552 Q65943 Q11538 Q49008 Q21199 Q1936384",
    "technology_computing": "Q7397 Q9143 Q341 Q166142 Q35127 Q7889 Q1639024 Q20826013",
    "physics": "Q107715 Q47574 Q1311670 Q2329 Q193886",
}.items():
    for _q in _qs.split():
        CLASSES.setdefault(_q, _k)
WIKIMEDIA_INTERNAL = {"Q4167836", "Q4167410", "Q11266439", "Q13406463", "Q17633526", "Q15184295", "Q19842659"}


def entity_keystone(classes, props):
    """the keystone of one Wikidata entity: its first known class, else by what it has (coordinates → a place,
    a taxon name → a living thing, a DOI → literature). None for Wikimedia's own pages."""
    if classes & WIKIMEDIA_INTERNAL:
        return None
    for q in classes:
        k = CLASSES.get(q)
        if k:
            return k
    if "P225" in props:
        return "life_forms"
    if "P356" in props:
        return "scientific_concepts"
    if "P625" in props:
        return "geographic_entities"
    if "P569" in props:
        return "human_individuals"
    return "other"


def unlocks():
    """every keystone's transitive unlocks (breadth first), as the prototype precomputed them"""
    out = {}
    for k in KEYSTONES:
        seen, todo = set(), list(KEYSTONES[k][2])
        while todo:
            n = todo.pop(0)
            if n not in seen:
                seen.add(n)
                todo += KEYSTONES[n][2]
        out[k] = sorted(seen)
    return out


# ------------------------------------------------------------------------------------------------ measuring
def _novelty(commons):
    """per bulk dataset: records read and new facts in its recent harvest-log entries (the latest ~10)"""
    out = collections.defaultdict(lambda: [0, 0])
    if commons is None:
        return out
    rows = commons.store.query("SELECT action, items, new FROM harvest_log WHERE action LIKE 'bulk:%' AND decision = 'harvested' "
                               "ORDER BY id DESC LIMIT 2000")
    seen = collections.Counter()
    for r in rows:
        key = r["action"][5:]
        if seen[key] < 10:
            seen[key] += 1
            out[key][0] += r["items"] or 0
            out[key][1] += r["new"] or 0
    return out


def coverage(commons_folder, commons=None):
    """each keystone: facts held (measured), the datasets feeding it, measured novelty and the state
    (not started / growing / saturated), the priority score and the order the bulk runner uses"""
    import qbbulk
    facts = collections.Counter()
    feeds = collections.defaultdict(set)
    st = qbbulk.status(commons_folder, commons)
    for d in st["datasets"]:
        if not d["facts"]:
            continue
        if d["key"].startswith("wikidata-dump-"):
            share = qbbulk.lane_keystones(commons_folder, d["key"])
            tot = sum(share.values()) or 1
            for k, n in share.items():                       # scaled to the shard's count (deduplication may have removed some)
                facts[k] += round(d["facts"] * n / tot)
                feeds[k].add("wikidata")
        else:
            k = DATASETS.get(d["key"])
            if k:
                facts[k] += d["facts"]
                feeds[k].add(d["key"])
    if commons is not None:
        for r in commons.store.query("SELECT domain, count(*) AS n FROM facts GROUP BY domain"):
            k = COMMONS_DOMAIN.get(r["domain"])
            if k:
                facts[k] += r["n"]
                feeds[k].add("shared facts")
    nov = _novelty(commons)
    lanes = [k for k in nov if k.startswith("wikidata-dump-")]
    wd_read, wd_new = sum(nov[k][0] for k in lanes), sum(nov[k][1] for k in lanes)
    ul = unlocks()
    biggest = max(facts.values() or [1])
    rows = []
    for k, (label, phase, direct, probes) in KEYSTONES.items():
        read = sum(nov[d][0] for d, kk in DATASETS.items() if kk == k) + (wd_read if "wikidata" in feeds[k] else 0)
        new = sum(nov[d][1] for d, kk in DATASETS.items() if kk == k) + (wd_new if "wikidata" in feeds[k] else 0)
        novelty = new / read if read else None
        state = ("not started" if not facts[k] else
                 "saturated" if read >= SATURATED_MIN_READ and novelty is not None and novelty < SATURATED_NOVELTY else "growing")
        share = facts[k] / biggest if biggest else 0
        score = PHASE_WEIGHT[phase] + len(ul[k]) * 120 + len(direct) * 60 + round((1 - share) * 300)
        if state == "saturated":
            score //= 4
        rows.append({"key": k, "label": label, "phase": phase, "unlocks": direct, "unlocks_all": ul[k], "facts": facts[k],
                     "feeds": sorted(feeds[k]), "read": read, "new": new, "novelty": None if novelty is None else round(novelty, 4),
                     "state": state, "score": score})
    if facts.get("other"):
        rows.append({"key": "other", "label": "Other (not yet classified)", "phase": None, "unlocks": [], "unlocks_all": [],
                     "facts": facts["other"], "feeds": sorted(feeds["other"]), "read": 0, "new": 0, "novelty": None,
                     "state": "growing", "score": 0})
    rows.sort(key=lambda r: -r["score"])
    return {"keystones": rows, "total": sum(facts.values()),
            "rules": {"saturated": "novelty under %g%% over at least %s records read" % (SATURATED_NOVELTY * 100, format(SATURATED_MIN_READ, ",")),
                      "score": "phase weight (2000 … 100) + 120 per keystone it unlocks (transitively) + 60 per direct unlock "
                               "+ up to 300 for the least-covered; a saturated keystone counts a quarter"}}


def order(keys, commons_folder, commons=None, target=None):
    """the order the bulk runner starts datasets in: the admin's target first (sources or applications named in the
    Control Panel's targeting rules), then by keystone priority; the Wikidata lanes keep their own order"""
    try:
        score = {r["key"]: r["score"] for r in coverage(commons_folder, commons)["keystones"]}
    except Exception:
        score = {}
    t = target or {}
    srcs, apps = set(t.get("sources") or []), set(t.get("apps") or [])

    def rank(key):
        import qbbulk
        ds = qbbulk.catalog().get(key)
        targeted = bool(ds and ((ds.source or "") in srcs or ds.app in apps or key in srcs))
        k = "human_individuals" if key.startswith("wikidata-dump-") else DATASETS.get(key)
        lane = int(key.rsplit("-", 1)[1]) if key.startswith("wikidata-dump-") else 0
        return (0 if targeted else 1, -score.get(k, 0), lane, key)
    return sorted(keys, key=rank)


def probes(rows=None, today=None, limit=12):
    """questions for the fact gatherer, growing keystones first (highest priority first); filled with this month"""
    today = today or datetime.date.today()
    month = today.strftime("%B")
    order_ = [r["key"] for r in rows if r["key"] in KEYSTONES and r["state"] != "saturated"] if rows else list(KEYSTONES)
    out = []
    for k in order_:
        for q in KEYSTONES[k][3]:
            out.append({"keystone": k, "label": KEYSTONES[k][0], "question": q.format(month=month, year=today.year)})
    return out[:limit]


def self_test():
    out = []
    ok = lambda n, c, d="": out.append((n, bool(c), d))
    ok("20 keystones in 5 phases, every unlock names a keystone", len(KEYSTONES) == 20 and {v[1] for v in KEYSTONES.values()} == set(range(5))
       and all(u in KEYSTONES for v in KEYSTONES.values() for u in v[2]))
    ul = unlocks()
    ok("transitive unlocks: mathematics reaches astronomy through physics", "astronomy" in ul["mathematics"], ul["mathematics"])
    ok("an entity's keystone by class, else by its properties, never for Wikimedia pages",
       entity_keystone({"Q5"}, set()) == "human_individuals" and entity_keystone({"Q999999999"}, {"P625"}) == "geographic_entities"
       and entity_keystone({"Q4167410"}, {"P625"}) is None and entity_keystone(set(), set()) == "other")
    ok("unknown classes stay unclassified, never guessed", entity_keystone({"Q123456789"}, set()) == "other")
    p = probes(None, datetime.date(2026, 10, 27))
    ok("probe questions are filled with the month and year", p and all("{" not in x["question"] for x in p)
       and any("October 2026" in x["question"] for x in p), p[:2])
    ok("every dataset maps to a keystone", all(v in KEYSTONES for v in DATASETS.values()))
    return out


if __name__ == "__main__":
    import sys
    res = self_test()
    for n, g, d in res:
        print(("  [OK]   " if g else "  [FAIL] ") + n + ("" if g else "  — %s" % (d,)))
    print("\n  %d of %d checks passed" % (sum(1 for x in res if x[1]), len(res)))
    sys.exit(0 if all(x[1] for x in res) else 1)
