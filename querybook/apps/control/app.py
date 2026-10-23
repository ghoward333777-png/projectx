#!/usr/bin/env python3
"""QueryBook Control Panel — one place to see and manage the three applications (Language, STEM, History & News).

    python app.py                 start (opens the browser at http://127.0.0.1:8100/)
    python app.py --no-browser    start without opening a browser
    python app.py --selftest      run the self-test in a temporary folder

What it does
  * Applications: which are running (each records its address in the shared database when it starts), their version,
    health, harvest switch and last turn; start, stop, open, "harvest now" and diagnose each one.
  * Global harvesting: start or stop all harvesting (or a selection of applications and online harvesters) at once,
    and set every running application harvesting now.
  * Targeting: topics, applications, harvesters and sources to concentrate on — first, or only — with a budget boost.
  * Filtering: what may enter the shared facts (words to leave out or require, years, domains, licence classes),
    with a dry run on the facts already shared. All three applications obey both (qbcontrol.py).
  * Transparency: every action — from a button or the assistant — is written to the audit trail with what changed.
  * Monitoring and alerts: the panel checks the applications and the harvest every 20 s and raises alerts (an
    application that stopped, failing harvests, a filter that lets almost nothing in, approvals waiting); alerts
    clear themselves when the condition ends, or can be dismissed.
  * Diagnostics for every section, and an assistant that answers questions and works the panel from plain
    sentences. The assistant is rule-based (no language model): it understands a fixed set of requests, says
    exactly what it did, and asks before stopping anything.

The global rules change what all three applications harvest, so changing them needs the admin passphrase once the
admin has set one (the same passphrase as the harvesting policy).
"""
import json, os, subprocess, sys, threading, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import qbcore as core
import qbcommons as cm
import qbcontrol as ctl
import qbonline as ol
import assistant
import qbselfknow
import qbexemplar
import qbcampaign
import qbdirective

APP_ID = "control"
APP_NAME = "QueryBook Control Panel"
VERSION = "1.3.0"
PORT = 8100
program_dir = HERE

APPS = {"language": {"name": "Language Builder", "domain": "language", "port": 8101, "folders": ["language", "QueryBook-Language"]},
        "stem": {"name": "Math, Science & Engineering", "domain": "stem", "port": 8102, "folders": ["stem", "QueryBook-STEM"]},
        "facts": {"name": "History & News", "domain": "history", "port": 8103, "folders": ["facts", "QueryBook-History-News"]}}
MONITOR_S = 20

SCHEMA = ["""
CREATE TABLE audit (id INTEGER PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT,
                    result TEXT, ok INTEGER NOT NULL DEFAULT 1);
CREATE TABLE alerts (id INTEGER PRIMARY KEY, key TEXT NOT NULL, level TEXT NOT NULL, app TEXT, text TEXT NOT NULL, first TEXT NOT NULL,
                     last TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', resolved TEXT);
CREATE INDEX alerts_key ON alerts(key, status);
CREATE TABLE chat (id INTEGER PRIMARY KEY, at TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL, data TEXT);
CREATE TABLE samples (id INTEGER PRIMARY KEY, at TEXT NOT NULL, body TEXT NOT NULL)
"""]

_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))     # the applications are on this computer


def _call(url, path, data=None, timeout=3.0):
    req = urllib.request.Request(url.rstrip("/") + path, data=None if data is None else json.dumps(data).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="GET" if data is None else "POST")
    try:
        with _NO_PROXY.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error")
        except Exception:
            msg = None
        raise core.UserError(msg or "the application answered %s" % e.code)


class Panel:
    def __init__(self, folder=None, commons_folder=None):
        self.folder = folder or core.data_folder(APP_ID, HERE)
        os.makedirs(self.folder, exist_ok=True)
        self.log = core.make_logger(self.folder, APP_ID)
        self.store = core.Store(self.folder, APP_ID, SCHEMA, self.log)
        self.commons = cm.Commons(commons_folder or cm.commons_folder(self.folder), APP_ID, self.log)
        self.api = core.Api()
        qbselfknow.attach(self, APP_ID, VERSION)          # the Self-Knowledge Layer: /api/self, /api/self/ask
        qbexemplar.attach(self)                           # the shared exemplar library: /api/exemplars
        qbcampaign.add_routes(self.api, self.commons,       # harvest campaigns, the master On/Off, the Google exemplar tools
                              lambda act, sc, ap, hv: self.harvest(act, ap if sc == "selected" else None, hv if sc == "selected" else None),
                              lambda: set(ol.HARVESTERS), HERE)
        qbdirective.add_routes(self.api, self.commons, HERE)  # the Campaign Manager: directives in, wave-scheduled campaigns out
        self.seen = {}                      # application → was it running at the last check
        self.stopping = set()               # stopped from the panel (not an unexpected stop)
        self.procs = {}
        self.last_check = None
        self._routes()

    # ------------------------------------------------------------------ transparency
    def audit(self, actor, action, detail="", result="", ok=True):
        with self.store.write() as db:
            db.execute("INSERT INTO audit(at, actor, action, detail, result, ok) VALUES(?,?,?,?,?,?)",
                       (core.now_cs(), actor, action, str(detail)[:2000], str(result)[:2000], 1 if ok else 0))
            db.execute("DELETE FROM audit WHERE id NOT IN (SELECT id FROM audit ORDER BY id DESC LIMIT 5000)")

    def act(self, actor, action, detail, fn):
        """Run one action and write it, with its outcome, to the audit trail (also when it fails)."""
        try:
            r = fn()
        except Exception as e:
            self.audit(actor, action, detail, str(e), False)
            raise
        self.audit(actor, action, detail, (r.get("summary") if isinstance(r, dict) else None) or json.dumps(r, default=str)[:300])
        return r

    # ------------------------------------------------------------------ the applications
    def where(self, app):
        try:
            return json.loads(self.commons.setting("url:%s" % app) or "null")
        except ValueError:
            return None

    def probe(self, app):
        """Is the application running, and what does it say about itself?"""
        w = self.where(app) or {}
        urls = [w["url"]] if w.get("url") else []
        default = "http://127.0.0.1:%d/" % APPS[app]["port"]
        if default not in urls:
            urls.append(default)
        for u in urls:
            try:
                st = _call(u, "/api/status", timeout=1.5)
                return {"running": True, "url": u, "status": st, "version": (st or {}).get("version") or w.get("version")}
            except Exception:
                continue
        return {"running": False, "url": w.get("url"), "version": w.get("version")}

    def app_folder(self, app):
        parent = os.path.dirname(HERE)
        for f in APPS[app]["folders"]:
            p = os.path.join(parent, f)
            if os.path.isfile(os.path.join(p, "app.py")):
                return p
        return None

    def apps(self):
        hb = {h["app"]: h for h in self.commons.engine.status()["heartbeats"]}
        out = []
        for a, meta in APPS.items():
            pr = self.probe(a)
            st = pr.get("status") or {}
            last = self.commons.store.one("SELECT started, ended, result, reason FROM engine_turns WHERE app = ? ORDER BY id DESC LIMIT 1", (a,))
            if last:
                last["result"] = json.loads(last["result"] or "null")
            facts = self.commons.store.scalar("SELECT count(*) FROM facts WHERE domain = ?", (meta["domain"],), 0)
            out.append({"app": a, "name": meta["name"], "domain": meta["domain"], "running": pr["running"], "url": pr.get("url"),
                        "version": pr.get("version"), "health": st.get("health"), "job": st.get("job"), "facts": facts,
                        "harvest_on": self.commons.setting("auto:%s" % a, "on") != "off",
                        "heartbeat_s": round(time.time() - hb[a]["at"], 1) if a in hb else None, "last_turn": last,
                        "installed": self.app_folder(a) is not None})
        return out

    def start_app(self, app):
        if app not in APPS:
            raise core.UserError("Unknown application: %s" % app)
        if self.probe(app)["running"]:
            return {"summary": "%s is already running" % APPS[app]["name"], "already": True}
        folder = self.app_folder(app)
        if not folder:
            raise core.UserError("%s is not installed next to the Control Panel." % APPS[app]["name"])
        kw = {"creationflags": 0x00000008 | 0x00000200} if os.name == "nt" else {"start_new_session": True}   # detached
        env = dict(os.environ)
        env["QB_COMMONS_DATA"] = self.commons.folder
        self.procs[app] = subprocess.Popen([sys.executable, "app.py", "--no-browser"], cwd=folder, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, **kw)
        self.stopping.discard(app)
        return {"summary": "starting %s (it takes a few seconds)" % APPS[app]["name"], "pid": self.procs[app].pid}

    def stop_app(self, app):
        pr = self.probe(app)
        if not pr["running"]:
            return {"summary": "%s is not running" % APPS[app]["name"]}
        self.stopping.add(app)
        _call(pr["url"], "/api/control/quit", {"key": ctl.token(self.commons.folder)})
        return {"summary": "stopping %s" % APPS[app]["name"]}

    def harvest_now(self, app):
        pr = self.probe(app)
        if not pr["running"]:
            raise core.UserError("%s is not running — start it first." % APPS[app]["name"])
        r = _call(pr["url"], "/api/commons/run", {}, timeout=10)
        return {"summary": "%s is harvesting now" % APPS[app]["name"], "result": r}

    # ------------------------------------------------------------------ global harvesting
    def harvest(self, action, apps=None, harvesters=None, now=False):
        """Start or stop harvesting: everything, or the selected applications and online harvesters."""
        if action not in ("start", "stop"):
            raise core.UserError("action must be start or stop")
        sel = bool(apps or harvesters)
        apps = [a for a in (apps or []) if a in APPS] if sel else list(APPS)
        harvesters = [h for h in (harvesters or []) if h in ol.HARVESTERS] if sel else list(ol.HARVESTERS)
        if sel and action == "start":
            apps = sorted(set(apps) | {ol.HARVESTERS[h][0] for h in harvesters})
        on = "on" if action == "start" else "off"
        c = self.commons
        with c.store.write() as db:
            if not sel or action == "start":
                c.set_setting("harvest:master", "running" if action == "start" else "stopped", db)
            for a in apps:
                c.set_setting("auto:%s" % a, on, db)
            for h in harvesters:
                c.set_setting("harvester:%s" % h, on, db)
            c.agent_log(db, "control", "Control Panel: %s %s" % ("started" if action == "start" else "stopped",
                                                               "all harvesting" if not sel else ", ".join(apps + harvesters)))
        kicked = []
        if action == "start" and now:
            for a in apps:
                try:
                    self.harvest_now(a)
                    kicked.append(a)
                except Exception:
                    pass
        what = "all harvesting" if not sel else "harvesting for " + ", ".join(apps + harvesters)
        return {"summary": "%s %s%s" % ("started" if action == "start" else "stopped", what,
                                       ("; harvesting now in " + ", ".join(kicked)) if kicked else ""), "control": self.control()}

    def control(self):
        return cm.control_state(self.commons)

    # ------------------------------------------------------------------ rules
    def rules(self):
        t, f = ctl.get(self.commons, "target"), ctl.get(self.commons, "filter")
        return {"target": t, "filter": f, "target_text": ctl.describe("target", t), "filter_text": ctl.describe("filter", f),
                "admin_set": self.commons.approvals.admin_set()}

    def set_rules(self, kind, rules, passphrase=""):
        r = ctl.set_rules(self.commons, kind, rules, passphrase)
        return {"summary": "%s: %s" % ("target" if kind == "target" else "filter", ctl.describe(kind, r)), "rules": r}

    # ------------------------------------------------------------------ monitoring and alerts
    def raise_alert(self, db, key, level, text, app=None):
        row = db.execute("SELECT id FROM alerts WHERE key = ? AND status IN ('open', 'dismissed')", (key,)).fetchone()
        if row:
            db.execute("UPDATE alerts SET last = ?, text = ?, level = ? WHERE id = ?", (core.now_cs(), text, level, row[0]))
        else:
            db.execute("INSERT INTO alerts(key, level, app, text, first, last) VALUES(?,?,?,?,?,?)", (key, level, app, text, core.now_cs(), core.now_cs()))

    def check(self):
        """One monitoring pass: look at every application and the harvest, raise and resolve alerts."""
        found = {}
        apps = self.apps()
        for a in apps:
            k = a["app"]
            if self.seen.get(k) and not a["running"] and k not in self.stopping:
                found["down:" + k] = ("error", "%s stopped (it was running at the last check). Start it again from Applications." % a["name"], k)
            if a["running"]:
                self.stopping.discard(k)
                if a["health"] == "fail":
                    found["health:" + k] = ("error", "%s's own diagnostics report a failure — open it and see Diagnostics." % a["name"], k)
                if a["harvest_on"] and a["heartbeat_s"] is not None and a["heartbeat_s"] > 600:
                    found["stale:" + k] = ("warn", "%s is running but has not checked in with the harvesting engine for %d min." % (a["name"], a["heartbeat_s"] // 60), k)
            self.seen[k] = a["running"]
        q = self.commons.store
        fails = q.query("SELECT app, count(*) AS n FROM harvest_log WHERE decision = 'failed' AND at >= ? GROUP BY app",
                        (time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 3600)),))
        for f in fails:
            found["fail:" + f["app"]] = ("warn", "%d harvest task(s) failed in the last hour in %s — see the harvest log." % (f["n"], APPS.get(f["app"], {}).get("name", f["app"])), f["app"])
        turns = q.query("SELECT app, result FROM engine_turns WHERE ended IS NOT NULL ORDER BY id DESC LIMIT 9")
        res = [json.loads(t["result"] or "{}") for t in turns]
        kept = sum(r.get("new", 0) + r.get("merged", 0) for r in res)
        dropped = sum(r.get("filtered", 0) for r in res)
        if dropped >= 20 and dropped > 4 * kept:
            found["strict"] = ("warn", "The filter left out %d of %d harvested facts in the last turns — it may be too strict (Filtering → Preview)." % (dropped, dropped + kept), None)
        rules = self.rules()
        if rules["target"]["only"] and res and all(not r.get("on_target") and not r.get("new") for r in res[:3]):
            found["target-empty"] = ("warn", "\"Only targeted\" is on but the last turns harvested nothing — the target may match no source.", None)
        pend = len(self.commons.approvals.list("pending"))
        if pend:
            found["pending"] = ("info", "%d harvesting recommendation(s) wait for the admin (open any application → Harvesting)." % pend, None)
        if not cm.hv.master_running(self.commons) and (ctl.active("target", rules["target"])):
            found["master-off"] = ("info", "A target is set but all harvesting is stopped.", None)
        with self.store.write() as db:
            for key, (level, text, app) in found.items():
                self.raise_alert(db, key, level, text, app)
            for r in db.execute("SELECT id, key FROM alerts WHERE status IN ('open', 'dismissed')").fetchall():
                if r[1] not in found:
                    db.execute("UPDATE alerts SET status = 'resolved', resolved = ? WHERE id = ?", (core.now_cs(), r[0]))
            db.execute("INSERT INTO samples(at, body) VALUES(?,?)", (core.now_cs(), json.dumps(
                {"facts": q.scalar("SELECT count(*) FROM facts", default=0), "running": [a["app"] for a in apps if a["running"]]})))
            db.execute("DELETE FROM samples WHERE id NOT IN (SELECT id FROM samples ORDER BY id DESC LIMIT 2000)")
        self.last_check = core.now_cs()
        return {"alerts": len(found), "checked": self.last_check}

    def alerts(self, all_=False):
        return self.store.query("SELECT * FROM alerts %s ORDER BY CASE level WHEN 'error' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END, id DESC LIMIT 200"
                                % ("" if all_ else "WHERE status = 'open'"))

    def start_monitor(self):
        def loop():
            while True:
                try:
                    self.check()
                except Exception as e:
                    self.log("monitor:", repr(e))
                time.sleep(MONITOR_S)
        threading.Thread(target=loop, daemon=True, name="qb-control-monitor").start()

    # ------------------------------------------------------------------ diagnostics, section by section
    def diagnose(self, section):
        chk = []
        add = lambda name, ok, detail="": chk.append({"name": name, "status": "ok" if ok is True else ("warn" if ok is None else "fail"), "detail": detail})
        c = self.commons
        if section in ("panel", "all"):
            add("Panel database", not self.store.read_only, self.store.path)
            add("Shared database opens and passes its check", not c.store.read_only, c.store.path)
            try:
                ctl.token(c.folder)
                add("Control key readable (needed to stop applications)", True, os.path.join(c.folder, "control.key"))
            except OSError as e:
                add("Control key readable (needed to stop applications)", False, str(e))
            add("Monitoring running", True if self.last_check else None, "last check %s" % (self.last_check or "not yet"))
        if section in ("apps", "all"):
            for a in self.apps():
                add("%s installed" % a["name"], a["installed"], self.app_folder(a["app"]) or "not found next to the panel")
                add("%s running" % a["name"], True if a["running"] else None, a["url"] or "never started")
                if a["running"]:
                    try:
                        d = _call(a["url"], "/api/diagnostics", timeout=20)
                        bad = [x["name"] for x in d.get("checks", []) if x.get("status") == "fail"]
                        add("%s's own diagnostics" % a["name"], not bad if d.get("overall") != "warn" or bad else None,
                            "overall %s%s" % (d.get("overall"), (": " + ", ".join(bad)) if bad else ""))
                    except Exception as e:
                        add("%s's own diagnostics" % a["name"], False, str(e))
                    add("%s uses this Control Panel's rules" % a["name"], self._same_rules(a["url"]), "reads the same shared database")
        if section in ("harvest", "all"):
            add("Master harvesting switch", True if cm.hv.master_running(c) else None, "running" if cm.hv.master_running(c) else "stopped")
            ok = c.harvest_log.verify()
            add("Harvest log hash chain intact", bool(ok.get("ok")), json.dumps(ok)[:200])
            n = c.store.scalar("SELECT count(*) FROM harvest_log WHERE decision = 'failed'", default=0)
            add("Failed harvest tasks (all time)", True if not n else None, str(n))
            keys = ol.key_status(c.folder)
            missing = [k["title"] for k in keys if not k.get("set")]
            add("Online harvester keys", True if not missing else None, "missing: " + ", ".join(missing) if missing else "all set")
        if section in ("target", "all"):
            r = ctl.get(c, "target")
            add("Target rules valid", True, ctl.describe("target", r))
            if ctl.active("target", r):
                tasks = [{"action": "online:" + k, "title": h[2], "why": h[3], "source": h[1], "app": h[0]} for k, h in ol.HARVESTERS.items()]
                hits = [t["action"][7:] for t in tasks if ctl.task_targeted(t, r, t["app"])]
                add("Online harvesters inside the target", True if hits or r["apps"] or r["topics"] else None,
                    ", ".join(hits) or "none (topics are matched against each task's title when it is planned)")
        if section in ("filter", "all"):
            r = ctl.get(c, "filter")
            add("Filter rules valid", True, ctl.describe("filter", r))
            if ctl.active("filter", r):
                pv = ctl.preview(c, r, 500)
                share = pv["kept"] / pv["checked"] if pv["checked"] else 1
                add("Filter lets facts in (dry run on the latest 500)", True if share >= 0.2 else None,
                    "%d of %d would be kept" % (pv["kept"], pv["checked"]))
        if section in ("assistant", "all"):
            for q, want in assistant.SELF_TEST:
                got = assistant.parse(q)["intent"]
                add("Assistant understands “%s”" % q, got == want, got)
        overall = "fail" if any(x["status"] == "fail" for x in chk) else "warn" if any(x["status"] == "warn" for x in chk) else "ok"
        return {"section": section, "overall": overall, "checks": chk, "at": core.now_cs()}

    def _same_rules(self, url):
        try:
            r = _call(url, "/api/control/rules", timeout=2)
        except Exception:
            return None
        mine = self.rules()
        return r.get("target") == mine["target"] and r.get("filter") == mine["filter"]

    def overview(self):
        s = self.commons.summary()
        by = {}
        for row in s["by_domain"]:
            by.setdefault(row["domain"], {})[row["status"]] = row["n"]
        trend = self.commons.store.query("""SELECT substr(at, 1, 13) AS hour, app, sum(new) AS new, sum(items) AS items FROM harvest_log
                                            WHERE decision = 'harvested' GROUP BY hour, app ORDER BY hour DESC LIMIT 72""")
        turns = self.commons.store.query("SELECT id, app, started, ended, reason, result FROM engine_turns ORDER BY id DESC LIMIT 15")
        for t in turns:
            t["result"] = json.loads(t["result"] or "null")
        return {"facts": s["facts"], "by_domain": by, "shared": s["shared"], "trend": trend, "turns": turns}

    # ------------------------------------------------------------------ routes
    def _routes(self):
        a = self.api

        @a.get("/api/status")
        def status(p):
            return {"app": APP_NAME, "version": VERSION, "health": None, "job": None}

        @a.get("/api/panel/status")
        def panel_status(p):
            return {"version": VERSION, "apps": self.apps(), "control": self.control(), "rules": self.rules(),
                    "harvesters": [{"name": k, "app": h[0], "title": h[2], "source": h[1]} for k, h in ol.HARVESTERS.items()],
                    "alerts": self.alerts(), "overview": self.overview(), "last_check": self.last_check,
                    "licence_classes": sorted(cm.hv.LICENCE_CLASSES)}

        @a.post("/api/panel/app")
        def panel_app(p):
            app, action = p.get("app"), p.get("action")
            if app not in APPS:
                raise core.UserError("Unknown application.")
            fn = {"start": self.start_app, "stop": self.stop_app, "harvest": self.harvest_now}.get(action)
            if not fn:
                raise core.UserError("Unknown action.")
            return self.act(p.get("actor") or "panel", "%s %s" % (action, app), "", lambda: fn(app))

        @a.post("/api/panel/harvest")
        def panel_harvest(p):
            return self.act("panel", "harvest %s" % p.get("action"), json.dumps({k: p.get(k) for k in ("apps", "harvesters", "now")}),
                            lambda: self.harvest(p.get("action"), p.get("apps"), p.get("harvesters"), bool(p.get("now"))))

        @a.post("/api/panel/rules")
        def panel_rules(p):
            kind = p.get("kind")
            return self.act("panel", "set %s" % kind, json.dumps(p.get("rules"), ensure_ascii=False),
                            lambda: self.set_rules(kind, p.get("rules") or {}, p.get("passphrase") or ""))

        @a.post("/api/panel/rules_clear")
        def panel_rules_clear(p):
            kind = p.get("kind")
            return self.act("panel", "clear %s" % kind, "", lambda: self.set_rules(kind, {}, p.get("passphrase") or ""))

        @a.post("/api/panel/preview")
        def panel_preview(p):
            return ctl.preview(self.commons, p.get("rules") or {}, int(p.get("limit") or 2000))

        @a.post("/api/panel/search")
        def panel_search(p):
            return {"facts": self.commons.search(p.get("q") or "", p.get("domain") or None, p.get("status") or None, int(p.get("limit") or 50))}

        @a.post("/api/panel/fact")
        def panel_fact(p):
            return self.commons.fact(int(p.get("id")))

        @a.post("/api/panel/diagnose")
        def panel_diagnose(p):
            r = self.diagnose(p.get("section") or "all")
            self.audit("panel", "diagnose %s" % r["section"], "", "%s (%d checks)" % (r["overall"], len(r["checks"])), r["overall"] != "fail")
            return r

        @a.post("/api/panel/check")
        def panel_check(p):
            return self.check()

        @a.get("/api/panel/alerts")
        def panel_alerts(p):
            return {"alerts": self.alerts(p.get("all") == "1")}

        @a.post("/api/panel/alerts_clear")
        def panel_alerts_clear(p):
            with self.store.write() as db:
                if p.get("id"):
                    db.execute("UPDATE alerts SET status = 'dismissed' WHERE id = ? AND status = 'open'", (int(p["id"]),))
                else:
                    db.execute("UPDATE alerts SET status = 'dismissed' WHERE status = 'open'")
            self.audit("panel", "dismiss alert%s" % ("" if p.get("id") else "s"), str(p.get("id") or "all"))
            return {"alerts": self.alerts()}

        @a.get("/api/panel/audit")
        def panel_audit(p):
            since = self.store.meta_get("audit_view_from", "")
            return {"audit": self.store.query("SELECT * FROM audit WHERE at > ? ORDER BY id DESC LIMIT ?", (since, int(p.get("limit") or 200))),
                    "hidden_before": since or None, "total": self.store.scalar("SELECT count(*) FROM audit", default=0)}

        @a.post("/api/panel/audit_clear")
        def panel_audit_clear(p):
            # the trail itself is kept (transparency): clearing only starts the view afresh; "show all" brings it back
            self.store.meta_set("audit_view_from", "" if p.get("show_all") else core.now_cs())
            return {"ok": True}

        @a.get("/api/panel/chat")
        def panel_chat(p):
            return {"chat": self.store.query("SELECT * FROM chat ORDER BY id DESC LIMIT 60")[::-1]}

        @a.post("/api/panel/chat")
        def panel_chat_say(p):
            msg = (p.get("message") or "").strip()
            if not msg:
                raise core.UserError("Type a question or a request.")
            r = assistant.respond(self, msg, p.get("passphrase") or "", p.get("pending"))
            with self.store.write() as db:
                db.execute("INSERT INTO chat(at, role, text) VALUES(?,?,?)", (core.now_cs(), "you", msg[:2000]))
                db.execute("INSERT INTO chat(at, role, text, data) VALUES(?,?,?,?)", (core.now_cs(), "assistant", r["reply"][:4000],
                                                                                       json.dumps({k: r.get(k) for k in ("did", "needs", "facts")}, default=str)))
            return r

        @a.post("/api/panel/chat_clear")
        def panel_chat_clear(p):
            with self.store.write() as db:
                db.execute("DELETE FROM chat")
            return {"ok": True}

    # ------------------------------------------------------------------ self-test
    @staticmethod
    def selftest():
        return selftest()


def open_app():
    return Panel()


def selftest():
    import tempfile
    c = core.Checks() if hasattr(core, "Checks") else None
    passed = failed = 0

    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print("  [OK]", name)
        else:
            failed += 1
            print("  [FAIL]", name, detail)

    with tempfile.TemporaryDirectory() as tmp:
        p = Panel(os.path.join(tmp, "panel"), os.path.join(tmp, "commons"))
        co = p.commons
        # rules: validation, persistence, the admin gate
        t = p.set_rules("target", {"topics": "Moon, eclipse", "apps": ["stem"], "boost": 3})
        check("target saved and described", t["rules"]["topics"] == ["moon", "eclipse"] and "budget ×3" in p.rules()["target_text"], p.rules())
        try:
            p.set_rules("target", {"only": True})
            ok = False
        except core.UserError:
            ok = True
        check("\"only targeted\" without a target is refused", ok)
        co.approvals.set_admin("admin-pass-1")
        try:
            p.set_rules("filter", {"exclude_words": "war"}, "wrong")
            ok = False
        except core.UserError:
            ok = True
        check("once the admin is set, rule changes need the passphrase", ok and not ctl.active("filter", ctl.get(co, "filter")))
        p.set_rules("filter", {"exclude_words": "war", "years": [1800, 1950]}, "admin-pass-1")
        f = ctl.get(co, "filter")
        # the filter as the harvest applies it
        items = [{"subject": "Battle of Hastings", "predicate": "is a", "object": "war battle in 1066"},
                 {"subject": "Telephone", "predicate": "invented", "object": "1876"},
                 {"subject": "Moon landing", "predicate": "happened", "object": "1969"},
                 {"subject": "Gravity", "predicate": "described by", "object": "Newton"}]
        kept, n, why = ctl.apply_filter(items, f, "history")
        check("filter leaves out excluded words and years outside the range; facts without a year pass",
              [i["subject"] for i in kept] == ["Telephone", "Gravity"] and n == 2 and why, (kept, why))
        tr = ctl.get(co, "target")
        tasks = [{"action": "online:wikidata_people", "title": "People", "source": "wikidata"},
                 {"action": "constants", "title": "Moon distances", "source": "nist"}]
        ordered = ctl.order_tasks([dict(x) for x in tasks], tr, "language")
        check("targeted tasks go first, with the boost", ordered[0]["title"] == "Moon distances" and ordered[0].get("_targeted"), ordered)
        only = ctl.clean("target", {"topics": ["moon"], "only": True})
        o2 = ctl.order_tasks([dict(x) for x in tasks], only, "language")
        check("\"only targeted\" skips the rest with the reason", o2[1].get("_skip", "").startswith("outside the Control Panel"), o2)
        # a real shared fact: the dry-run preview
        with co.store.write() as db:
            co.save(db, dict(items[0], domain="history", evidence=[]))
            co.save(db, dict(items[1], domain="history", evidence=[]))
        pv = ctl.preview(co, f)
        check("filter preview counts what would be kept and why the rest would not", pv["checked"] == 2 and pv["kept"] == 1 and pv["examples"], pv)
        # harvesting switches
        r = p.harvest("stop")
        check("mass stop stops the master switch", r["control"]["master"] == "stopped")
        r = p.harvest("start", ["stem"], [])
        check("starting a selection runs only it", r["control"]["master"] == "running" and [x["app"] for x in r["control"]["apps"] if x["on"]] == ["stem"], r["control"])
        # applications (none running in the test)
        ap = p.apps()
        check("the three applications are listed and found installed", [x["app"] for x in ap] == ["language", "stem", "facts"] and all(x["installed"] for x in ap), ap)
        try:
            p.harvest_now("stem")
            ok = False
        except core.UserError as e:
            ok = "not running" in str(e)
        check("harvest now on a stopped application says so", ok)
        # monitoring and alerts
        p.seen["stem"] = True
        p.check()
        al = p.alerts()
        check("an application that stops unexpectedly raises an alert", any(x["key"] == "down:stem" and x["level"] == "error" for x in al), al)
        p.seen["stem"] = False
        p.check()
        check("the alert resolves itself when the condition ends", not any(x["key"] == "down:stem" for x in p.alerts()))
        with co.store.write() as db:
            co.harvest_log.write(db, "facts", "x", "a task", "loc", "public-domain", "failed", "network down")
        p.check()
        check("a failing harvest raises a warning", any(x["key"] == "fail:facts" for x in p.alerts()))
        p.api.routes[("POST", "/api/panel/alerts_clear")]({})
        check("clear dismisses every open alert", not p.alerts())
        # transparency
        p.api.routes[("POST", "/api/panel/harvest")]({"action": "stop"})
        au = p.api.routes[("GET", "/api/panel/audit")]({})
        check("every action is in the audit trail", au["audit"] and au["audit"][0]["action"] == "harvest stop")
        p.api.routes[("POST", "/api/panel/audit_clear")]({})
        au2 = p.api.routes[("GET", "/api/panel/audit")]({})
        check("clearing the audit view keeps the trail itself", not au2["audit"] and au2["total"] >= 1)
        # diagnostics for every section
        d = p.diagnose("all")
        names = " ".join(x["name"] for x in d["checks"])
        check("diagnostics cover the panel, applications, harvest, target, filter and assistant",
              all(k in names for k in ("Shared database", "Language Builder installed", "hash chain", "Target rules", "Filter rules", "Assistant understands")), names)
        check("the assistant passes its own understanding checks", all(x["status"] == "ok" for x in d["checks"] if x["name"].startswith("Assistant")))
        # the assistant at work
        say = lambda m, **k: assistant.respond(p, m, k.get("pw", ""), k.get("pending"))
        r = say("how is everything?")
        check("assistant: status in plain words", "Language Builder" in r["reply"] and "not running" in r["reply"], r["reply"])
        # the Self-Knowledge Layer through the assistant and the API: labelled, sourced, never claiming what is only specified
        r = say("Are you neuromorphic?")
        check("self-knowledge: 'are you neuromorphic?' is answered as specified, with the design section", "not yet built" in r["reply"] and "§3" in r["reply"], r["reply"])
        r = say("can you improve yourself recursively?")
        check("self-knowledge: recursive self-improvement is not planned, by design", "not planned" in r["reply"], r["reply"])
        r = say("how does supervised self-improvement work?")
        check("self-knowledge: built claims carry their source file", "built and tested" in r["reply"] and "qbengineer.py" in r["reply"], r["reply"])
        sk = p.api.routes[("GET", "/api/self")]({})
        check("self-knowledge: /api/self lists every design section and no contradictions", len(sk["sections"]) >= 56 and not sk["contradictions"], sk["contradictions"])
        r = say("focus on volcanoes and earthquakes in history", pw="admin-pass-1")
        check("assistant: sets a target from a sentence", ctl.get(co, "target")["topics"] == ["volcanoes", "earthquakes"]
              and ctl.get(co, "target")["apps"] == ["facts"], (r["reply"], ctl.get(co, "target")))
        r = say("exclude football")
        check("assistant: asks for the passphrase when the admin is set", r.get("needs") == "passphrase", r)
        r = say("exclude football", pw="admin-pass-1")
        check("assistant: adds to the filter", "football" in ctl.get(co, "filter")["exclude_words"] and "war" in ctl.get(co, "filter")["exclude_words"])
        r = say("stop all harvesting")
        check("assistant: asks before stopping", r.get("needs") == "confirm" and cm.hv.master_running(co) is False or r.get("needs") == "confirm", r)
        r2 = say("yes", pending=r.get("pending"))
        check("assistant: does it after “yes” and says what it did", not cm.hv.master_running(co) and r2.get("did"), r2)
        r = say("find telephone")
        check("assistant: searches the shared facts", r.get("facts") and r["facts"][0]["subject"] == "Telephone", r)
        r = say("blorp the snargle")
        check("assistant: unknown requests get the list of what it can do", "I can" in r["reply"], r["reply"])
        check("assistant uses no language model (no network calls in its module)",
              "urllib" not in open(os.path.join(HERE, "assistant.py"), encoding="utf-8").read())
        check("routes registered", all(k in p.api.routes for k in [("GET", "/api/panel/status"), ("POST", "/api/panel/chat"), ("POST", "/api/panel/diagnose")]))
        st = p.api.routes[("GET", "/api/panel/status")]({})
        check("status page data complete", all(k in st for k in ("apps", "control", "rules", "alerts", "overview", "harvesters")))
    print("\n  %d of %d checks passed" % (passed, passed + failed))
    return failed == 0


def main():
    args = sys.argv[1:]
    if args and args[0] == "--selftest":
        return 0 if selftest() else 1
    panel = open_app()
    panel.start_monitor()
    panel.audit("panel", "Control Panel started", "version %s" % VERSION)
    core.serve(APP_NAME, panel.api, os.path.join(HERE, "ui"), PORT, panel.log, open_browser="--no-browser" not in args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
