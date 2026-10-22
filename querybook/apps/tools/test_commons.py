#!/usr/bin/env python3
"""End-to-end test of the Commons: the three applications share one database (each in its own process,
as on a real computer), their four-agent teams harvest into it, and they check each other's facts.

Also: the status rules, the licence policy, crash safety of a harvest, and determinism (two separate
runs from the same inputs give the same shared facts, evidence and reasoning)."""
import json, os, sqlite3, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "_core"))
import qbcore as core
import qbcommons as cm
import qbharvest as hv
import qbonline as ol

os.environ["QB_OFFLINE"] = "1"              # the end-to-end runs below never go online; the online harvesters are tested with stubs

FACTS_SETUP = r"""
f = [({"statement": "Albert Einstein was born on 14 March 1879.", "subject": "Albert Einstein", "predicate": "born on", "object": "14 March 1879", "category": "People", "date": "14 March 1879"},
      [{"name": "Einstein: His Life and Universe", "kind": "book", "author": "Walter Isaacson", "quote": "born in Ulm"}]),
     ({"statement": "Albert Einstein died on 18 April 1955.", "subject": "Albert Einstein", "predicate": "died on", "object": "18 April 1955", "category": "People", "date": "18 April 1955"},
      [{"name": "Einstein: His Life and Universe", "kind": "book", "author": "Walter Isaacson"}, {"name": "The New York Times, 19 April 1955", "kind": "newspaper"}]),
     ({"statement": "Test Person was born in 1700.", "subject": "Test Person", "predicate": "born on", "object": "1700", "category": "People", "date": "1700"},
      [{"name": "Parish register", "kind": "government record"}]),
     ({"statement": "Test Person died in 1900.", "subject": "Test Person", "predicate": "died on", "object": "1900", "category": "People", "date": "1900"},
      [{"name": "Parish register", "kind": "government record"}]),
     ({"statement": "The Magna Carta was sealed in June 1215.", "subject": "Magna Carta", "category": "History", "date": "June 1215"}, [])]
for fact, srcs in f:
    a.add_fact(fact, srcs)
"""

STEM_SETUP = r"""
r = a.ask("12 × 7")
a.save("calc", "12 × 7", "84", r["detail"])
"""


def run_app(app, data, commons, setup="", cycle=True, policy=None):
    code = ("import sys, json, os; sys.path.insert(0, %r); os.chdir(%r)\nimport app as M\na = M.open_app(%r)\n" % (os.path.join(ROOT, app), os.path.join(ROOT, app), data)
            + setup + ("\na.commons.set_setting('licence_policy', %r)\n" % policy if policy else "")
            + ("\nprint('RESULT ' + json.dumps(a.team.cycle('test')))\n" if cycle else ""))
    env = dict(os.environ, QB_COMMONS_DATA=commons)
    p = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, env=env, timeout=600)
    if p.returncode != 0:
        raise RuntimeError("%s failed:\n%s" % (app, p.stderr[-3000:]))
    out = [l for l in p.stdout.splitlines() if l.startswith("RESULT ")]
    return json.loads(out[-1][7:]) if out else None


def db(commons):
    c = sqlite3.connect(os.path.join(commons, "commons.sqlite"))
    c.row_factory = sqlite3.Row
    return c


def one_world(tmp, policy=None):
    commons = os.path.join(tmp, "commons")
    res = {}
    res["facts1"] = run_app("facts", os.path.join(tmp, "facts"), commons, FACTS_SETUP, policy=policy)
    res["stem"] = run_app("stem", os.path.join(tmp, "stem"), commons, STEM_SETUP)
    res["language"] = run_app("language", os.path.join(tmp, "language"), commons)
    res["facts2"] = run_app("facts", os.path.join(tmp, "facts"), commons)
    return commons, res


def snapshot(commons):
    c = db(commons)
    facts = sorted(tuple(r) for r in c.execute("SELECT fingerprint, status, origin_app FROM facts"))
    ev = sorted(tuple(r) for r in c.execute("SELECT f.fingerprint, e.app, e.method, e.source, e.verdict, coalesce(e.detail, '') FROM evidence e JOIN facts f ON f.id = e.fact_id"))
    rs = sorted(tuple(r) for r in c.execute("SELECT f.fingerprint, r.app, r.step, r.text FROM reasoning r JOIN facts f ON f.id = r.fact_id"))
    return core.fingerprint(json.dumps([facts, ev, rs]))


def main():
    c = core.Checks()
    # status rules
    S = cm.fact_status
    c.check("status: recomputed fact is verified", S([{"verdict": "supports", "method": "recompute", "source": "x", "app": "stem"}]) == "verified")
    c.check("status: two sources corroborate", S([{"verdict": "supports", "method": "source", "source": "a", "app": "facts"},
                                                  {"verdict": "supports", "method": "source", "source": "b", "app": "facts"}]) == "corroborated")
    c.check("status: a source plus another application's confirming check corroborate",
            S([{"verdict": "supports", "method": "source", "source": "a", "app": "facts"}, {"verdict": "supports", "method": "cross-check", "source": "c", "app": "language"}]) == "corroborated")
    c.check("status: a consistency check cannot raise a fact", S([{"verdict": "supports", "method": "source", "source": "a", "app": "facts"},
                                                                {"verdict": "supports", "method": "consistency", "source": "c", "app": "stem"}]) == "sourced")
    c.check("status: support and contradiction make a dispute (no winner picked)",
            S([{"verdict": "supports", "method": "source", "source": "a", "app": "facts"}, {"verdict": "contradicts", "method": "consistency", "source": "c", "app": "stem"}]) == "disputed")
    c.check("status: news is only reported", S([{"verdict": "supports", "method": "report", "source": "BBC", "app": "facts"}]) == "reported")
    c.check("licence: CC BY-NC is non-commercial", cm.is_non_commercial("CC BY-NC 4.0") and cm.is_non_commercial("CC BY-NC-SA 4.0"))
    c.check("licence: CC BY-SA and public domain are commercial", not cm.is_non_commercial("CC BY-SA 4.0") and not cm.is_non_commercial("public domain"))

    # crash safety: a harvest that fails while saving leaves nothing half-written and its cursor unmoved
    class Broken(cm.Adapter):
        def plan(self, st, ctx):
            return [{"action": "x", "title": "two good items and a bad one", "source": "stem-computed", "why": "test"}]

        def execute(self, task, ctx):
            ok = {"subject": "s", "predicate": "p", "object": "o", "evidence": [{"method": "reference", "source": "r"}]}
            return {"items": [ok, dict(ok, object="o2"), dict(ok, object="")], "cursor": {"k": 3}}
    with tempfile.TemporaryDirectory() as tmp:
        com = cm.Commons(tmp, "stem")
        team = cm.Team(com, Broken())
        try:
            team.cycle("test")
            failed = False
        except ValueError:
            failed = True
        c.check("a failed save is rolled back whole", failed and com.store.scalar("SELECT count(*) FROM facts") == 0)
        c.check("its cursor does not move", com.cursor("k") == 0)
        c.check("the failure is recorded against the agent", com.store.scalar("SELECT last_status FROM team WHERE app = 'stem' AND role = 'curator'") == "failed")
        c.check("the team can run again afterwards", not team.state["running"])
        com.store.conn().close()

    # the Control Panel's global rules, obeyed inside a real harvest cycle
    import qbcontrol as ctl

    class Two(cm.Adapter):
        def plan(self, st, ctx):
            return [{"action": "a", "title": "Rivers of Europe", "source": "stem-computed", "why": "test"},
                    {"action": "b", "title": "Volcanoes of Iceland", "source": "stem-computed", "why": "test"}]

        def execute(self, task, ctx):
            ev = [{"method": "reference", "source": "r"}]
            n = ctx.budget("x", 2)
            return {"items": [{"subject": "%s %d" % (task["title"], i), "predicate": "p", "object": "football" if i == 0 else "ok %d" % i,
                               "evidence": ev} for i in range(n)]}
    with tempfile.TemporaryDirectory() as tmp:
        com = cm.Commons(tmp, "stem")
        team = cm.Team(com, Two())
        ctl.set_rules(com, "target", {"topics": ["volcanoes"], "boost": 2})
        ctl.set_rules(com, "filter", {"exclude_words": ["football"]})
        out = team.cycle("test")
        tasks = com.store.query("SELECT action, step, detail FROM tasks ORDER BY step")
        c.check("control: the targeted task runs first, with the budget boost", tasks[0]["action"] == "b" and "targeted" in tasks[0]["detail"]
                and com.store.scalar("SELECT count(*) FROM facts WHERE subject LIKE 'Volcanoes%'") == 3, tasks)
        c.check("control: the filter keeps excluded facts out and says so", out["filtered"] == 2 and
                com.store.scalar("SELECT count(*) FROM facts WHERE object = 'football'") == 0 and "left out by the Control Panel" in tasks[0]["detail"], out)
        ctl.set_rules(com, "target", {"topics": ["volcanoes"], "only": True})
        out = team.cycle("test")
        c.check("control: with \"only targeted\" the other tasks are skipped, logged with why", com.store.scalar(
            "SELECT count(*) FROM harvest_log WHERE action = 'a' AND reason LIKE '%outside the Control Panel%'") == 1, out)
        com.store.conn().close()


    # policy registry, admin approvals, the engine's rotation and the learner (one Commons, no applications)
    with tempfile.TemporaryDirectory() as tmp:
        com = cm.Commons(tmp, "stem")
        reg, ap, eng, hl = com.registry, com.approvals, com.engine, com.harvest_log
        reg.ensure("stem", {"constants": 40})
        c.check("registry: seeded sources with licence classes", reg.source("webster-1913")["status"] == "approved"
                and reg.source("muse-bilingual")["status"] == "blocked" and reg.source("news-headlines")["status"] == "blocked")
        approved = set(hv.ADMIN_DECISIONS[0][3])
        held = set(hv.ADMIN_DECISIONS[1][3])
        c.check("admin decision 2026-10-19: the approved researched sources are approved, with the admin's words and conditions",
                all(reg.source(k)["status"] == "approved" and reg.source(k)["decided_by"] == "admin" and "2026-10-19" in reg.source(k)["reason"] for k in approved))
        c.check("admin decision: sources with a copyright risk a program cannot check are held back, with why",
                all(reg.source(k)["status"] == "pending" and "Held back" in reg.source(k)["reason"] for k in held) and not reg.check("fsi-courses")[0])
        c.check("admin decision: every approval is a policy version", sum(1 for v in reg.versions(200) if v["change"].get("status") == "approved") == len(approved))
        c.check("research: restricted ones are recorded as blocked with the reason",
                reg.source("mit-ocw")["status"] == "blocked" and reg.source("nist-webbook")["licence_class"] == "copyrighted-text" and reg.source("openstax")["reason"])
        # (1.47) sources researched since the admin's decisions wait for the admin too
        NEW_147 = {k for k, *_x in hv.RESEARCHED_SOURCES if hv.LICENCE_CLASSES[_x[4]][0]} - approved - held
        res = [r for r in ap.list("pending") if r["kind"] == "new source"]
        c.check("research: the held sources still wait for the admin; the approved ones' requests are marked applied",
                {r["change"]["key"] for r in res} == held | NEW_147 and len([r for r in ap.list("applied") if r["kind"] == "new source"]) == len(approved), [r["change"]["key"] for r in res])
        reg.ensure("stem", {})
        c.check("research: seeding again adds nothing twice", len([r for r in ap.list("pending") if r["kind"] == "new source"]) == len(res))
        c.check("registry: an application's budgets become parameters", reg.param("budget.stem.constants") == 40)
        ok, cls, why = reg.check("some-new-site")
        c.check("registry: an unknown source is blocked and registered as pending", not ok and reg.source("some-new-site")["status"] == "pending")
        try:
            ap.decide(1, True, "whatever")
            no_admin = False
        except core.UserError:
            no_admin = True
        c.check("approvals: nothing is decided before the admin passphrase is set", no_admin)
        ap.set_admin("correct horse")
        c.check("approvals: the passphrase is checked", ap.check_admin("correct horse") and not ap.check_admin("wrong horse"))
        with com.store.write() as d:
            for i in range(4):
                hl.write(d, "stem", "constants", "batch %d" % i, "codata-2018", "facts", "harvested", "test", items=40, new=40, seconds=0.5, budget_key="constants")
            for i in range(3):
                hl.write(d, "stem", "flaky", "flaky %d" % i, "stem-computed", "computed", "failed", "test")
            hl.write(d, "stem", "web", "web", "some-new-site", "unknown", "blocked", "test")
        made = com.learner.review("stem")
        recs = ap.list("pending")
        kinds = {r["kind"] for r in recs}
        c.check("learner: recommends bigger batches, pausing a failing task and classifying a source", made >= 3 and {"speed", "reliability", "source"} <= kinds,
                [(r["kind"], r["title"]) for r in recs])
        c.check("learner: the same recommendation is never made twice", com.learner.review("stem") == 0)
        c.check("learner: recommendations change nothing until approved", reg.param("budget.stem.constants") == 40)
        speed = next(r for r in recs if r["kind"] == "speed")
        try:
            ap.decide(speed["id"], True, "wrong horse")
            refused = False
        except core.UserError:
            refused = True
        v0 = reg.version()
        c.check("approvals: a wrong passphrase changes nothing", refused and reg.param("budget.stem.constants") == 40)
        ap.decide(speed["id"], True, "correct horse")
        c.check("approvals: an approved change is applied and versioned", reg.param("budget.stem.constants") == 60 and reg.version() > v0
                and ap.list("applied")[0]["id"] == speed["id"])
        pause = next(r for r in recs if r["kind"] == "reliability")
        ap.decide(pause["id"], False, "correct horse", "keep trying")
        c.check("approvals: a rejected change is not applied", reg.param("disabled.stem.flaky") is None and ap.list("rejected")[0]["id"] == pause["id"])
        try:
            ap.admin_source("muse-bilingual", "approved", "correct horse", "test")
            guarded = False
        except core.UserError:
            guarded = True
        c.check("approvals: a restricted licence needs an explicit acceptance", guarded and reg.source("muse-bilingual")["status"] == "blocked")
        ap.admin_source("some-new-site", "approved", "correct horse", "checked: CC0", licence_class="cc0")
        c.check("approvals: the admin can classify and approve a source", reg.check("some-new-site")[0])
        fsi = next(r for r in res if r["change"]["key"] == "fsi-courses")
        ap.decide(fsi["id"], True, "correct horse")
        c.check("approvals: approving a held source in the app makes it harvestable", reg.check("fsi-courses")[0] and not reg.check("fhwa-federal-authored")[0])
        reg.ensure("stem", {})
        c.check("an admin decision made in the app is never overridden", reg.source("fsi-courses")["status"] == "approved")
        v = hl.verify()
        c.check("harvest log: the hash chain verifies", v["ok"] and v["entries"] == 8, v)
        com.store.conn().execute("UPDATE harvest_log SET new = 0 WHERE id = 2")
        com.store.conn().commit()
        c.check("harvest log: tampering is detected", hl.verify() == {"ok": False, "entries": 1, "broken_at": 2})
        # the engine: first come, then alternation, then backoff for an application that found nothing
        t1 = eng.claim("language")
        c.check("engine: the first application gets a turn", t1 and t1["app"] == "language")
        c.check("engine: nobody else starts while a turn is running", eng.claim("stem") is None)
        eng.finish(t1, {"new": 100, "seconds": 1})
        eng.heartbeat("stem"); eng.heartbeat("facts")
        c.check("engine: the application that just harvested waits its turn", eng.claim("language") is None)
        t2 = eng.claim("stem") or eng.claim("facts")
        c.check("engine: another domain goes next", t2 and t2["app"] in ("stem", "facts"), t2)
        eng.finish(t2, {"new": 0, "seconds": 1})
        t3 = eng.claim({"stem": "facts", "facts": "stem"}[t2["app"]]) or eng.claim("language")
        c.check("engine: then a different domain again", t3 is not None and t3["app"] != t2["app"], t3)
        eng.finish(t3, {"new": 5, "seconds": 1})
        c.check("engine: an application that found nothing new backs off", eng.claim(t2["app"]) is None)
        # the master control
        class Stub:
            pass
        stub = Stub(); stub.commons, stub.app_id, stub.state = com, "stem", {"running": True}
        cm.harvest_control(stub, "stop", "all")
        c.check("master: Stop all — no application gets a turn", all(eng.claim(a) is None for a in ("language", "stem", "facts")))
        c.check("master: Stop all — a running harvest stops between tasks", cm.Context(com).stop())
        st = cm.harvest_control(stub, "start", "selected", ["language"], ["natural-earth-places"])
        c.check("master: Start selected — only the ticked ones (and a ticked harvester's application) are on",
                st["master"] == "running" and {a["app"] for a in st["apps"] if a["on"]} == {"language", "facts"}
                and [h["name"] for h in st["harvesters"] if h["on"]] == ["natural-earth-places"], st)
        c.check("master: an application switched off gets no turn", eng.claim("stem") is None)
        cm.harvest_control(stub, "stop", "selected", ["language"], [])
        c.check("master: Stop selected — only the ticked ones stop", not cm.control_state(com)["apps"][0]["on"] and cm.control_state(com)["apps"][2]["on"])
        st = cm.harvest_control(stub, "start", "all")
        c.check("master: Start all — everything back on", st["master"] == "running" and all(x["on"] for x in st["apps"] + st["harvesters"])
                and not cm.Context(com).stop())
        try:
            cm.harvest_control(stub, "start", "selected", [], [])
            empty = False
        except core.UserError:
            empty = True
        c.check("master: Start selected with nothing ticked is refused", empty)
        com.store.conn().close()

    # the online harvesters, with the internet replaced by recorded answers
    FIX = {
        "natural-earth": {"features": [{"properties": {"name": "Paris", "adm0name": "France", "adm1name": "Ile-de-France", "latitude": 48.8667,
                                                       "longitude": 2.3333, "featurecla": "Admin-0 capital", "pop_max": 11000000}},
                                       {"properties": {"name": "Lyon", "adm0name": "France", "adm1name": "Auvergne-Rhone-Alpes", "latitude": 45.75,
                                                       "longitude": 4.85, "featurecla": "Admin-1 region capital", "pop_max": 1400000}}]},
        "frus": b'''<volumes xmlns="http://history.state.gov/ns/1.0"><volume id="frus1861"><title type="complete">Message of the
            President</title><published>1861</published><coverage>1860 to 1861</coverage></volume></volumes>''',
    }
    calls = []

    def fake(url, kind="json", timeout=60, headers=None):
        calls.append((url, headers))
        if "api.si.edu" in url:
            return {"response": {"rowCount": 2, "rows": [
                {"id": "a", "title": "Wright Flyer", "content": {"descriptiveNonRepeating": {"record_ID": "nasm_A19610048000", "data_source": "National Air and Space Museum",
                 "record_link": "https://airandspace.si.edu/collection/id/nasm_A19610048000", "metadata_usage": {"access": "CC0"}},
                 "indexedStructured": {"date": ["1900s"], "object_type": ["Aircraft"], "place": ["North Carolina"], "topic": ["Aviation"]}}},
                {"id": "b", "title": "Not open", "content": {"descriptiveNonRepeating": {"record_ID": "x1", "metadata_usage": {"access": "Usage conditions apply"}}}}]}}
        if "fdc/v1" in url:
            return [{"fdcId": 1750340, "description": "Apples, fuji, with skin, raw", "foodNutrients": [
                {"number": "208", "name": "Energy", "amount": 64.7, "unitName": "KCAL"}, {"number": "999", "name": "Other", "amount": 1, "unitName": "G"}]}]
        if "catalog.archives.gov" in url:
            return {"body": {"hits": {"hits": [
                {"_id": "305268", "_source": {"record": {"naId": 305268, "title": "Telegram from Orville Wright", "levelOfDescription": "item",
                 "useRestriction": {"status": "Unrestricted"}, "productionDates": [{"year": 1903, "month": 12, "day": 17}],
                 "ancestors": [{"levelOfDescription": "series", "title": "Wright Brothers Papers"}]}}},
                {"_id": "9", "_source": {"record": {"naId": 9, "title": "Restricted", "useRestriction": {"status": "Restricted - Partly"}}}}]}}}
        if "api.dp.la" in url:
            return {"count": 1, "docs": [{"id": "abc", "isShownAt": "https://example.org/item/abc", "dataProvider": {"name": "Library of Congress"},
                    "sourceResource": {"title": ["Brooklyn Bridge"], "date": [{"displayDate": "1883"}], "subject": [{"name": "Bridges"}], "spatial": [{"name": "New York"}]}}]}
        if "api.europeana.eu" in url:
            return {"totalResults": 1, "items": [{"id": "/9200/abc", "title": ["Map of Europe"], "year": ["1570"], "country": ["Belgium"],
                    "dataProvider": ["KBR"], "type": "IMAGE", "dcCreator": ["http://viaf.org/1", "Abraham Ortelius"], "guid": "https://www.europeana.eu/item/9200/abc?utm=x"}]}
        if "natural-earth" in url:
            return FIX["natural-earth"]
        if "frus-metadata" in url:
            return FIX["frus"]
        if "v1.1/search" in url:
            return {"total": 1, "objectIDs": [436535]}
        if "/objects/436535" in url:
            return {"objectID": 436535, "title": "Wheat Field with Cypresses", "artistDisplayName": "Vincent van Gogh", "objectDate": "1889",
                    "medium": "Oil on canvas", "culture": "", "department": "European Paintings", "objectURL": "https://www.metmuseum.org/art/collection/search/436535"}
        if "esearch" in url:
            return {"esearchresult": {"count": "1", "idlist": ["9606"]}}
        if "esummary" in url:
            return {"result": {"uids": ["9606"], "9606": {"status": "active", "scientificname": "Homo sapiens", "commonname": "human", "division": "primates"}}}
        if "list=search" in url:
            return {"query": {"searchinfo": {"totalhits": 1}, "search": [{"title": "Q142"}]}}
        if "wbgetentities" in url and "Q142" in url:
            return {"entities": {"Q142": {"labels": {"en": {"value": "France"}}, "claims": {
                "P36": [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": "Q90"}}}}],
                "P30": [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": "Q46"}}}}],
                "P297": [{"rank": "normal", "mainsnak": {"datavalue": {"value": "FR"}}}],
                "P571": [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"time": "+1792-09-22T00:00:00Z", "precision": 11}}}}]}}}}
        if "wbgetentities" in url:
            return {"entities": {"Q90": {"labels": {"en": {"value": "Paris"}}}, "Q46": {"labels": {"en": {"value": "Europe"}}}}}
        raise ol.SourceBusy("no fixture for " + url)
    ol.FETCH = fake
    del os.environ["QB_OFFLINE"]
    try:
        items, nxt, _ = ol._natural_earth(0, 10)
        c.check("online: Natural Earth gives country, coordinates, capital, region — biggest first",
                {(i["subject"], i["predicate"], i["object"]) for i in items} >= {("city Paris (France)", "is capital of", "France"),
                                                                                 ("city Paris (France)", "coordinates", "48.8667, 2.3333")}
                and items[0]["subject"] == "city Paris (France)" and nxt is None)
        items, _, _ = ol._frus(0, 10)
        c.check("online: FRUS volumes give title, publication and coverage", ("FRUS volume frus1861", "covers the years", "1860 to 1861") in
                {(i["subject"], i["predicate"], i["object"]) for i in items})
        items, _, _ = ol._met(0, 10)
        c.check("online: The Met gives artist, date, medium", ("artwork \u201cWheat Field with Cypresses\u201d (Met 436535)", "artist", "Vincent van Gogh") in
                {(i["subject"], i["predicate"], i["object"]) for i in items})
        items, nxt, _ = ol._ncbi(0, 10)
        c.check("online: NCBI Taxonomy gives common names, then moves to the next group", ("organism Homo sapiens", "common name", "human") in
                {(i["subject"], i["predicate"], i["object"]) for i in items} and nxt == ol.TAXA_STEP)
        items, _, _ = ol._wikidata("P31=Q3624078", ol._countries, 0, 10)
        c.check("online: Wikidata countries resolve capital and continent names", {("country France", "capital", "Paris"), ("country France", "continent", "Europe"),
                ("country France", "ISO 3166-1 code", "FR")} <= {(i["subject"], i["predicate"], i["object"]) for i in items})
        c.check("online: Wikidata dates keep their precision", ol._year({"time": "+1991-00-00T00:00:00Z", "precision": 9}) == "1991"
                and ol._year({"time": "-0500-00-00T00:00:00Z", "precision": 9}) == "500 BC")
        with tempfile.TemporaryDirectory() as tmp:
            ol.save_key(tmp, "api.data.gov", "SECRETKEY1234")
            ol._KEYS["folder"] = tmp
            trip = lambda r: {(i["subject"], i["predicate"], i["object"]) for i in r[0]}
            c.check("keyed: Smithsonian takes only CC0 records", trip(ol._smithsonian("history_culture")(0, 10)) >=
                    {("Smithsonian object \u201cWright Flyer\u201d (nasm_A19610048000)", "held by", "National Air and Space Museum")} and
                    not any("Not open" in i[0] for i in trip(ol._smithsonian("history_culture")(0, 10))))
            c.check("keyed: USDA gives nutrients per 100 g", ("food Apples, fuji, with skin, raw", "energy per 100 g", "64.7 kcal") in trip(ol._fdc(0, 10)))
            ol.save_key(tmp, "nara", "NARAKEY")
            nr = trip(ol._nara(0, 10))
            c.check("keyed: National Archives takes only Unrestricted records, key sent as a header",
                    ("National Archives record \u201cTelegram from Orville Wright\u201d (NAID 305268)", "date", "1903-12-17") in nr and
                    not any("Restricted" == i[0] for i in nr) and calls[-1][1].get("x-api-key") == "NARAKEY" and "NARAKEY" not in calls[-1][0])
            ol.save_key(tmp, "dpla", "DPLAKEY")
            c.check("keyed: DPLA records by topic", ("DPLA item \u201cBrooklyn Bridge\u201d (abc)", "date", "1883") in trip(ol._dpla(0, 10)))
            ol.save_key(tmp, "europeana", "EUKEY")
            eu = trip(ol._europeana(0, 10))
            c.check("keyed: Europeana keeps named creators, drops link-only ones", ("Europeana record \u201cMap of Europe\u201d (/9200/abc)", "creator", "Abraham Ortelius") in eu
                    and not any(i[2].startswith("http") for i in eu))
            st = ol.key_status(tmp)
            c.check("keys: stored owner-only, shown only as a hint", all(k["set"] for k in st if k["service"] != "gemini") and st[0]["hint"] == "\u20261234" and
                    (os.name == "nt" or (os.stat(os.path.join(tmp, "api-keys.json")).st_mode & 0o077) == 0))
            ol.save_key(tmp, "api.data.gov", "")

        with tempfile.TemporaryDirectory() as tmp:
            com = cm.Commons(tmp, "facts")

            class Quiet(cm.Adapter):
                pass
            team = cm.Team(com, Quiet())
            out = team.cycle("test")
            d = com.store
            c.check("online: the team plans and runs the approved online harvesters", out["new"] > 0 and
                    d.scalar("SELECT count(*) FROM tasks WHERE action LIKE 'online:%' AND status = 'done'") >= 3, out)
            c.check("online: every online fact is logged with its source and why", d.scalar(
                "SELECT count(*) FROM harvest_log WHERE action LIKE 'online:%' AND decision = 'harvested' AND source_key IN ('natural-earth', 'frus', 'met-open-access', 'wikidata') AND reason <> ''") >= 3)
            c.check("online: facts only — no wording stored from researched sources", d.scalar("SELECT count(*) FROM evidence WHERE quote IS NOT NULL") == 0)
            c.check("online: a finished source is not planned again", com.cursor("online:natural-earth-places") == -1 and
                    not any(t["action"] == "online:natural-earth-places" for t in ol.plan(cm.Context(com), "facts")))
            com.registry.set_source("met-open-access", "blocked", "admin", "test")
            c.check("keys: harvesters needing a key wait for it", not any(t["action"] in ("online:nara-records", "online:dpla-items") for t in ol.plan(cm.Context(com), "facts")))
            ol.save_key(tmp, "dpla", "DPLAKEY")
            c.check("keys: once the key is saved its harvester is planned", any(t["action"] == "online:dpla-items" for t in ol.plan(cm.Context(com), "facts")))
            c.check("keys: no key ever reaches the database, log or evidence", not any(
                "DPLAKEY" in json.dumps(r) or "SECRETKEY" in json.dumps(r) for t in ("harvest_log", "evidence", "settings", "tasks") for r in d.query("SELECT * FROM %s" % t)))
            com.set_setting("harvester:dpla-items", "off")
            c.check("master: a harvester switched off is not planned", not any(t["action"] == "online:dpla-items" for t in ol.plan(cm.Context(com), "facts")))
            com.set_setting("harvester:dpla-items", "on")
            com.set_setting("harvest:master", "stopped")
            try:
                team.run_in_background()
                refused = False
            except core.UserError:
                refused = True
            c.check("master: Run now is refused while harvesting is stopped", refused)
            com.set_setting("harvest:master", "running")
            c.check("online: a source the admin blocks is not harvested", not any(t["source"] == "met-open-access" for t in ol.plan(cm.Context(com), "facts")))
            com.set_setting("online:facts", "off")
            c.check("online: harvesting online can be switched off", ol.plan(cm.Context(com), "facts") == [])

            def busy(url, kind="json", timeout=60, headers=None):
                raise ol.SourceBusy("asked to slow down (HTTP 429)")
            ol.FETCH = busy
            com.set_setting("online:facts", "on")
            com.set_setting("cursor:facts:online:frus-volumes", 0)
            out2 = team.cycle("test")
            c.check("online: a site that asks us to slow down fails only its task, logged with why", "slow down" in (d.scalar(
                "SELECT reason FROM harvest_log WHERE decision = 'failed' ORDER BY id DESC LIMIT 1") or "") and com.cursor("online:frus-volumes") == 0, out2)
            com.store.conn().close()
    finally:
        ol.FETCH = ol._fetch
        os.environ["QB_OFFLINE"] = "1"

    with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2, tempfile.TemporaryDirectory() as tmp3:
        commons, res = one_world(tmp1)
        d = db(commons)
        q = lambda sql, a=(): d.execute(sql, a).fetchone()[0]
        c.check("one shared database for three applications", q("SELECT count(DISTINCT origin_app) FROM facts") == 3, res)
        c.check("every application ran all four agents", q("SELECT count(*) FROM team WHERE last_status = 'ok'") == 12,
                [tuple(r) for r in d.execute("SELECT app, role, last_status, last_summary FROM team")])
        c.check("each team stored a strategy and a plan", q("SELECT count(DISTINCT app) FROM strategies") == 3 and q("SELECT count(DISTINCT app) FROM plans") == 3)
        c.check("plans were executed task by task", q("SELECT count(*) FROM tasks WHERE status = 'done'") >= 6 and q("SELECT count(*) FROM tasks WHERE status = 'failed'") == 0)
        died = d.execute("SELECT * FROM facts WHERE subject = 'Albert Einstein' AND predicate = 'died on'").fetchone()
        c.check("history fact shared with both its sources (corroborated)", died and died["status"] == "corroborated", died and dict(died))
        ev = d.execute("SELECT * FROM evidence WHERE fact_id = ? AND app = 'stem'", (died["id"],)).fetchone()
        c.check("Math & Science checked the lifespan for History & News", ev and ev["verdict"] == "supports" and "76" in ev["detail"], ev and dict(ev))
        c.check("its reasoning is kept with the fact", q("SELECT count(*) FROM reasoning WHERE fact_id = ? AND app = 'stem'", (died["id"],)) >= 2)
        bad = d.execute("SELECT * FROM facts WHERE subject = 'Test Person' AND predicate = 'died on'").fetchone()
        c.check("an impossible lifespan is disputed, not silently accepted", bad and bad["status"] == "disputed", bad and dict(bad))
        c.check("a fact without a source is not shared", q("SELECT count(*) FROM facts WHERE subject = 'Magna Carta'") == 0)
        iron = d.execute("SELECT id FROM facts WHERE subject = 'element Fe (Iron)' AND predicate = 'atomic number'").fetchone()
        lev = d.execute("SELECT * FROM evidence WHERE fact_id = ? AND app = 'language'", (iron["id"],)).fetchone() if iron else None
        c.check("the Language Builder checked the element name for Math & Science", lev and lev["verdict"] == "supports" and lev["method"] == "consistency", lev and dict(lev))
        c.check("molar masses are recomputed (verified)", q("SELECT status FROM facts WHERE subject = 'compound H2O'") == "verified")
        c.check("derived constant R is reference + recomputed (verified)", q("SELECT status FROM facts WHERE subject = 'constant R (molar gas constant)'") == "verified")
        c.check("saved answer recomputed and shared", q("SELECT status FROM facts WHERE subject = '12 × 7'") == "verified")
        c.check("English meanings shared (public domain)", q("SELECT count(*) FROM facts WHERE domain = 'language' AND predicate = 'means'") == 500)
        c.check("registry: MUSE (non-commercial) is blocked, so no translation is shared", q("SELECT count(*) FROM evidence WHERE licence LIKE '%BY-NC%'") == 0
                and q("SELECT status FROM policy_sources WHERE key = 'muse-bilingual'") == "blocked")
        c.check("registry: Webster 1913 (public domain) is approved", q("SELECT status FROM policy_sources WHERE key = 'webster-1913'") == "approved")
        lang_goals = json.loads(d.execute("SELECT body FROM strategies WHERE app = 'language' ORDER BY id DESC LIMIT 1").fetchone()[0])["goals"]
        c.check("the Strategist says why translations are held back", any(g["goal"] == "Hold translations back" for g in lang_goals), lang_goals)
        c.check("every harvest is logged with its source and why",
                q("SELECT count(*) FROM harvest_log WHERE decision = 'harvested'") >= 6 and
                q("SELECT count(*) FROM harvest_log WHERE decision = 'harvested' AND (source_key IS NULL OR source_key = '' OR reason = '')") == 0,
                [dict(r) for r in d.execute("SELECT app, action, source_key, reason FROM harvest_log LIMIT 8")])
        c.check("harvesting alternates language, STEM and history", q("SELECT count(DISTINCT domain) FROM harvest_log WHERE decision = 'harvested'") == 3)
        c.check("news headlines (copyrighted text) are blocked, and the block is logged",
                q("SELECT count(*) FROM harvest_log WHERE source_key = 'news-headlines' AND decision = 'harvested'") == 0)
        c.check("each shared fact's evidence points at its harvest record",
                q("SELECT count(*) FROM evidence WHERE app = 'language' AND method = 'reference' AND harvest_id IS NULL") == 0 and
                q("SELECT count(*) FROM evidence e JOIN harvest_log h ON h.id = e.harvest_id") > 500)
        c.check("history evidence keeps no third-party wording (quotes stripped)",
                q("SELECT count(*) FROM evidence WHERE app = 'facts' AND method = 'source' AND detail LIKE '%\u201c%'") == 0)
        ver = cm.Commons(commons, "facts").harvest_log.verify()
        c.check("the harvest log's hash chain verifies", ver["ok"] and ver["entries"] >= 6, ver)
        c.check("the harvest log is archived to a monthly file",
                any(n.startswith("harvest-") and n.endswith(".jsonl") for n in os.listdir(os.path.join(commons, "archives"))))
        c.check("no check left waiting", q("SELECT count(*) FROM requests WHERE status = 'open'") == 0,
                [tuple(r) for r in d.execute("SELECT kind, to_app, status FROM requests WHERE status='open' LIMIT 5")])
        c.check("checks crossed between all three applications",
                {tuple(r) for r in d.execute("SELECT DISTINCT from_app, to_app FROM requests")} >= {("facts", "stem"), ("stem", "language")})
        c.check("harvest cursors advanced", q("SELECT value FROM settings WHERE key = 'cursor:language:definitions'") == "500")
        c.check("shared database passes its integrity check", q("PRAGMA integrity_check") == "ok")
        c.check("shared database is backed up", len([n for n in os.listdir(os.path.join(commons, "backups")) if n.endswith(".sqlite")]) >= 1)
        # a second cycle continues from the cursors rather than repeating
        r2 = run_app("language", os.path.join(tmp1, "language"), commons)
        c.check("the next cycle harvests the next batch", q("SELECT count(*) FROM facts WHERE domain = 'language' AND predicate = 'means'") == 1000 and r2["new"] > 0, r2)
        # two applications harvesting at the same moment: SQLite serializes them, nothing is lost
        env = dict(os.environ, QB_COMMONS_DATA=commons)
        procs = [subprocess.Popen([sys.executable, "-B", os.path.join(ROOT, a, "app.py"), "harvest"], cwd=os.path.join(ROOT, a), env=dict(env, **{"QB_%s_DATA" % a.upper(): os.path.join(tmp1, a)}),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for a in ("language", "stem", "facts")]
        outs = [p.communicate(timeout=600) for p in procs]
        c.check("three applications harvesting at once all finish", all(p.returncode == 0 for p in procs), [o[1][-500:] for o in outs])
        c.check("concurrent harvests leave the database sound", q("PRAGMA integrity_check") == "ok" and
                q("SELECT count(*) FROM facts WHERE domain = 'language' AND predicate = 'means'") == 1500)
        d.close()
        # determinism: the same inputs, in a separate world, give the same Commons
        commons2, _ = one_world(tmp2)
        commons_a, _ = one_world(os.path.join(tmp2, "again"))
        c.check("deterministic: two fresh runs are identical", snapshot(commons2) == snapshot(commons_a))
        # commercial licence policy: MUSE is left out
        commons3 = os.path.join(tmp3, "commons")
        run_app("language", os.path.join(tmp3, "language"), commons3, policy="commercial", cycle=False)
        r = run_app("language", os.path.join(tmp3, "language"), commons3)
        d3 = db(commons3)
        goals = json.loads(d3.execute("SELECT body FROM strategies ORDER BY id DESC LIMIT 1").fetchone()[0])["goals"]
        c.check("commercial policy: no non-commercial source harvested", d3.execute("SELECT count(*) FROM evidence WHERE licence LIKE '%NC%'").fetchone()[0] == 0 and r["new"] == 500, r)
        c.check("commercial policy: the Strategist says why translations are held back", any(g["goal"] == "Hold translations back" for g in goals), goals)
        d3.close()
    return c.report("Commons (shared database and harvest teams)")


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
