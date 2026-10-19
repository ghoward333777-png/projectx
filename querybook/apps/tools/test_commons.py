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


    # policy registry, admin approvals, the engine's rotation and the learner (one Commons, no applications)
    with tempfile.TemporaryDirectory() as tmp:
        com = cm.Commons(tmp, "stem")
        reg, ap, eng, hl = com.registry, com.approvals, com.engine, com.harvest_log
        reg.ensure("stem", {"constants": 40})
        c.check("registry: seeded sources with licence classes", reg.source("webster-1913")["status"] == "approved"
                and reg.source("muse-bilingual")["status"] == "blocked" and reg.source("news-headlines")["status"] == "blocked")
        c.check("research: unrestricted researched sources wait for the admin (none approved)",
                reg.source("natural-earth")["status"] == "pending" and reg.source("wikidata")["status"] == "pending" and not reg.check("usgs-gnis")[0])
        c.check("research: restricted ones are recorded as blocked with the reason",
                reg.source("mit-ocw")["status"] == "blocked" and reg.source("nist-webbook")["licence_class"] == "copyrighted-text" and reg.source("openstax")["reason"])
        res = [r for r in ap.list("pending") if r["kind"] == "new source"]
        c.check("research: one approval request per unrestricted source", len(res) == sum(1 for x in __import__("qbharvest").RESEARCHED_SOURCES
                                                                                            if __import__("qbharvest").LICENCE_CLASSES[x[5]][0]), len(res))
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
        ne = next(r for r in res if r["change"]["key"] == "natural-earth")
        ap.decide(ne["id"], True, "correct horse")
        c.check("approvals: approving a researched source makes it harvestable", reg.check("natural-earth")[0] and not reg.check("usgs-gnis")[0])
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
        com.store.conn().close()

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
