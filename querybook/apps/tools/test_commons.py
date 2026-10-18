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
      [{"name": "Einstein: His Life and Universe", "kind": "book", "author": "Walter Isaacson"}]),
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
            return [{"action": "x", "title": "two good items and a bad one"}]

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

    with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2, tempfile.TemporaryDirectory() as tmp3:
        commons, res = one_world(tmp1)
        d = db(commons)
        q = lambda sql, a=(): d.execute(sql, a).fetchone()[0]
        c.check("one shared database for three applications", q("SELECT count(DISTINCT origin_app) FROM facts") == 3, res)
        c.check("every application ran all four agents", q("SELECT count(*) FROM team WHERE last_status = 'ok'") == 12,
                [tuple(r) for r in d.execute("SELECT app, role, last_status, last_summary FROM team")])
        c.check("each team stored a strategy and a plan", q("SELECT count(DISTINCT app) FROM strategies") == 3 and q("SELECT count(DISTINCT app) FROM plans") == 3)
        c.check("plans were executed task by task", q("SELECT count(*) FROM tasks WHERE status = 'done'") >= 8 and q("SELECT count(*) FROM tasks WHERE status = 'failed'") == 0)
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
        c.check("translations shared and marked non-commercial", q("SELECT count(*) FROM evidence WHERE licence LIKE '%BY-NC%'") > 1000)
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
