"""qbcommons — the Commons: one fact database shared by the three QueryBook applications, and the
agent teams that fill it.

Each application keeps its own database for its own work (word cards, saved answers, sources and
feeds). Facts it is prepared to stand behind go into the Commons, a single SQLite database in a
shared folder (~/QueryBook-Data/commons, or QB_COMMONS_DATA), where the other two applications can
read them, check them and add their own evidence and reasoning.

Every application runs a team of four agents, in this order, each recorded in the Commons:

  Strategist  surveys what this application knows and what the Commons lacks, and devises a strategy:
              ranked goals, the sources allowed under the licence policy, and a budget for the cycle.
  Planner     turns the strategy into a plan of concrete, bounded tasks.
  Harvester   executes the tasks and stages what it harvested (facts, evidence, reasoning, and checks
              to ask of the other applications). Nothing is written yet.
  Curator     saves the staged facts in one transaction per batch (duplicates merge, evidence
              accumulates), answers the checks the other applications asked of this one, recomputes
              each touched fact's status and takes a backup.

Cooperation: a fact can carry check requests (for example "is this lifespan possible?"). Each kind of
check belongs to the application able to answer it (CHECKS). That application's Curator answers it
the next time its team runs, and the answer becomes evidence on the fact, with the reasoning steps.
No application runs another's code: they cooperate only through the shared database.

Agents are deterministic programs, not AI models: the same inputs always give the same strategy, plan
and facts. Writes use the same safe store as each application (one transaction, WAL, synchronous=FULL,
checked at start-up, verified backups). Standard library only.
"""
import json, os, threading, time

import qbcore as core
import qbharvest as hv
import qbonline as ol

COMMONS_VERSION = "1.0.0"
APPS = {"language": "Language Builder", "stem": "Math, Science & Engineering", "facts": "History & News"}
DOMAINS = {"language": "language", "stem": "stem", "facts": "history"}
ROLES = [("strategist", "Strategist", "Devises the harvest strategy"),
         ("planner", "Planner", "Turns the strategy into a plan of tasks"),
         ("harvester", "Harvester", "Executes the plan and stages what it finds"),
         ("curator", "Curator", "Saves and manages the harvested facts; answers checks")]
# which application answers each kind of check
CHECKS = {"lifespan": "stem", "date_order": "stem", "calendar_date": "stem", "arithmetic": "stem", "element": "stem",
          "unit": "stem", "term": "language", "translation": "language", "sourced": "facts"}
CHECK_NAMES = {"lifespan": "Is the lifespan possible?", "date_order": "Are the dates in order?",
               "calendar_date": "Is it a real calendar date?", "arithmetic": "Does the arithmetic hold?",
               "element": "Is it a known chemical element?", "unit": "Does the unit conversion hold?",
               "term": "Is the English word in the dictionary?", "translation": "Is the translation in the dictionary?",
               "sourced": "Does a documented source record it?"}
STATUSES = ["verified", "corroborated", "sourced", "reported", "unsourced", "disputed", "rejected"]
CONFIDENCE = {"verified": 1.0, "corroborated": 0.9, "sourced": 0.75, "reported": 0.4, "unsourced": 0.2, "disputed": 0.3, "rejected": 0.0}
METHODS = ("recompute", "reference", "source", "report", "learned", "cross-check", "consistency")
# checks that confirm the claim itself; the others only test that it is possible (they can refute, never confirm)
CONFIRMING = {"arithmetic", "unit", "translation", "sourced"}
VERDICTS = ("supports", "contradicts", "cannot_check")
POLICIES = {"research": "Research and demonstration: every source, non-commercial ones marked",
            "commercial": "Commercial: sources whose licence forbids commercial use are not harvested"}
BATCH = 400
AUTO_EVERY_S = 1800

SCHEMA = ["""
CREATE TABLE facts (
  id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, domain TEXT NOT NULL, subject TEXT NOT NULL,
  predicate TEXT NOT NULL, object TEXT NOT NULL, statement TEXT, origin_app TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'unsourced', confidence REAL NOT NULL DEFAULT 0.2, created TEXT NOT NULL, updated TEXT NOT NULL
);
CREATE INDEX facts_domain ON facts(domain, status);
CREATE INDEX facts_sp ON facts(subject, predicate);
CREATE TABLE evidence (
  id INTEGER PRIMARY KEY, fact_id INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE, app TEXT NOT NULL, agent TEXT NOT NULL,
  method TEXT NOT NULL, source TEXT NOT NULL, licence TEXT, url TEXT, quote TEXT, verdict TEXT NOT NULL, detail TEXT,
  at TEXT NOT NULL, UNIQUE (fact_id, app, method, source)
);
CREATE INDEX evidence_fact ON evidence(fact_id);
CREATE TABLE reasoning (
  id INTEGER PRIMARY KEY, fact_id INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE, app TEXT NOT NULL, agent TEXT NOT NULL,
  step INTEGER NOT NULL, text TEXT NOT NULL, at TEXT NOT NULL, UNIQUE (fact_id, app, agent, text)
);
CREATE INDEX reasoning_fact ON reasoning(fact_id);
CREATE TABLE requests (
  id INTEGER PRIMARY KEY, fact_id INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE, kind TEXT NOT NULL, payload TEXT NOT NULL,
  fingerprint TEXT NOT NULL UNIQUE, from_app TEXT NOT NULL, to_app TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
  verdict TEXT, detail TEXT, created TEXT NOT NULL, answered TEXT
);
CREATE INDEX requests_open ON requests(to_app, status);
CREATE TABLE team (
  app TEXT NOT NULL, role TEXT NOT NULL, last_run TEXT, last_status TEXT, last_summary TEXT, last_ms INTEGER,
  runs INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (app, role)
);
CREATE TABLE strategies (id INTEGER PRIMARY KEY, app TEXT NOT NULL, created TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE plans (id INTEGER PRIMARY KEY, app TEXT NOT NULL, strategy_id INTEGER, created TEXT NOT NULL, status TEXT NOT NULL, summary TEXT);
CREATE TABLE tasks (
  id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE, app TEXT NOT NULL, step INTEGER NOT NULL,
  action TEXT NOT NULL, title TEXT NOT NULL, target TEXT, status TEXT NOT NULL DEFAULT 'queued', items INTEGER, started TEXT,
  finished TEXT, detail TEXT
);
CREATE INDEX tasks_plan ON tasks(plan_id);
CREATE TABLE agent_log (id INTEGER PRIMARY KEY, at TEXT NOT NULL, app TEXT NOT NULL, role TEXT NOT NULL, message TEXT NOT NULL, ms INTEGER);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)
""", hv.SCHEMA]


def commons_folder(app_folder=None):
    """The shared folder. Order: QB_COMMONS_DATA, then commons.json in the application's data folder,
    then ~/QueryBook-Data/commons — the same for all three applications unless you change it."""
    env = os.environ.get("QB_COMMONS_DATA")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    if app_folder:
        try:
            with open(os.path.join(app_folder, "commons.json"), encoding="utf-8") as f:
                p = json.load(f).get("folder")
            if p:
                return os.path.abspath(os.path.expanduser(p))
        except (OSError, ValueError):
            pass
    return os.path.join(os.path.expanduser("~"), "QueryBook-Data", "commons")


def set_commons_folder(app_folder, folder):
    p = os.path.join(app_folder, "commons.json")
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump({"folder": os.path.abspath(os.path.expanduser(folder))}, f, indent=2)
    os.replace(p + ".tmp", p)


def is_non_commercial(licence):
    """True for licences that forbid commercial use (CC BY-NC, BY-NC-SA, "non-commercial use only", ...)."""
    low = " %s " % (licence or "").lower().replace("-", " ").replace(",", " ")
    return " nc " in low or "non commercial" in low or "noncommercial" in low


def fact_status(evidence):
    """The status a fact earns from its evidence. Deterministic; never picks a winner in a dispute."""
    sup = [e for e in evidence if e["verdict"] == "supports"]
    con = [e for e in evidence if e["verdict"] == "contradicts"]
    if con and sup:
        return "disputed"
    if con:
        return "rejected"
    if any(e["method"] == "recompute" for e in sup):
        return "verified"
    sources = {core.norm(e["source"]) for e in sup if e["method"] in ("reference", "source", "learned")}
    checkers = {e["app"] for e in sup if e["method"] == "cross-check"}
    if len(sources) >= 2 or (sources and checkers):
        return "corroborated"
    if sources:
        return "sourced"
    if any(e["method"] == "report" for e in sup):
        return "reported"
    return "unsourced"


class Commons:
    """The shared database. Every application opens the same file; SQLite serializes the writers."""

    def __init__(self, folder, app_id, log=None):
        os.makedirs(folder, exist_ok=True)
        self.folder = folder
        self.app_id = app_id
        self.log = log or (lambda *a: None)
        self.store = core.Store(folder, "commons", SCHEMA, self.log)
        self.registry = hv.Registry(self)            # harvesting policy registry
        self.harvest_log = hv.HarvestLog(self)       # every harvest, its source and why (hash-chained, archived)
        self.approvals = hv.Approvals(self, self.registry)
        self.engine = hv.Engine(self, self.registry)
        self.learner = hv.Learner(self, self.registry, self.approvals)

    # -- settings shared by all applications
    def setting(self, key, default=None):
        return self.store.scalar("SELECT value FROM settings WHERE key = ?", (key,), default)

    def set_setting(self, key, value, db=None):
        sql, args = "INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (key, str(value))
        if db is not None:
            db.execute(sql, args)
        else:
            with self.store.write() as d:
                d.execute(sql, args)

    def policy(self):
        p = self.setting("licence_policy", "research")
        return p if p in POLICIES else "research"

    def cursor(self, key, default=0):
        v = self.setting("cursor:%s:%s" % (self.app_id, key))
        return int(v) if v is not None else default

    # -- facts
    def save(self, db, item, agent="curator"):
        """Save one harvested item inside the caller's transaction. Returns (fact_id, new?)."""
        domain = item.get("domain") or DOMAINS[self.app_id]
        s, p, o = (str(item[k]).strip() for k in ("subject", "predicate", "object"))
        if not (s and p and o):
            raise ValueError("a fact needs a subject, predicate and object")
        fp = core.fingerprint(domain, s, p, o)
        now = core.now_iso()
        row = db.execute("SELECT id FROM facts WHERE fingerprint = ?", (fp,)).fetchone()
        new = row is None
        if new:
            fid = db.execute("""INSERT INTO facts(fingerprint, domain, subject, predicate, object, statement, origin_app, created, updated)
                                VALUES(?,?,?,?,?,?,?,?,?)""", (fp, domain, s, p, o[:2000], item.get("statement"), self.app_id, now, now)).lastrowid
        else:
            fid = row[0]
        if item.get("sync") and not new:            # the item is this application's whole current evidence for the fact
            db.execute("DELETE FROM evidence WHERE fact_id = ? AND app = ? AND method NOT IN ('cross-check', 'consistency')", (fid, self.app_id))
        for e in item.get("evidence") or []:
            self.add_evidence(db, fid, e, agent)
        for i, text in enumerate(item.get("reasoning") or [], 1):
            db.execute("INSERT OR IGNORE INTO reasoning(fact_id, app, agent, step, text, at) VALUES(?,?,?,?,?,?)",
                       (fid, self.app_id, agent, i, str(text)[:1000], now))
        for chk in item.get("checks") or []:
            self.ask(db, fid, chk["kind"], chk.get("payload") or {})
        self.restatus(db, fid)
        return fid, new

    def add_evidence(self, db, fid, e, agent):
        if e.get("method") not in METHODS:
            raise ValueError("unknown evidence method %r" % e.get("method"))
        verdict = e.get("verdict") or "supports"
        if verdict not in VERDICTS:
            raise ValueError("unknown verdict %r" % verdict)
        db.execute("""INSERT INTO evidence(fact_id, app, agent, method, source, licence, url, quote, verdict, detail, at)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(fact_id, app, method, source) DO UPDATE SET
                      verdict=excluded.verdict, detail=excluded.detail, licence=excluded.licence, url=excluded.url,
                      quote=excluded.quote, at=excluded.at""",
                   (fid, self.app_id, agent, e["method"], str(e.get("source") or "")[:300], e.get("licence"), e.get("url"),
                    (e.get("quote") or None) and str(e["quote"])[:1000], verdict, (e.get("detail") or None) and str(e["detail"])[:1000],
                    core.now_iso()))

    def restatus(self, db, fid):
        ev = [{"verdict": r[0], "method": r[1], "source": r[2], "app": r[3]}
              for r in db.execute("SELECT verdict, method, source, app FROM evidence WHERE fact_id = ?", (fid,))]
        st = fact_status(ev)
        db.execute("UPDATE facts SET status = ?, confidence = ?, updated = ? WHERE id = ? AND status <> ?",
                   (st, CONFIDENCE[st], core.now_iso(), fid, st))
        return st

    # -- cooperation: checks one application asks of another
    def ask(self, db, fid, kind, payload):
        if kind not in CHECKS:
            raise ValueError("unknown check %r" % kind)
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        db.execute("""INSERT OR IGNORE INTO requests(fact_id, kind, payload, fingerprint, from_app, to_app, created)
                      VALUES(?,?,?,?,?,?,?)""", (fid, kind, body, core.fingerprint(fid, kind, body), self.app_id, CHECKS[kind], core.now_iso()))

    def open_requests(self, limit=500):
        return self.store.query("SELECT * FROM requests WHERE to_app = ? AND status = 'open' ORDER BY id LIMIT ?", (self.app_id, limit))

    def answer(self, db, req, result):
        verdict = result.get("verdict") if result.get("verdict") in VERDICTS else "cannot_check"
        method = "cross-check" if req["kind"] in CONFIRMING else "consistency"
        self.add_evidence(db, req["fact_id"], {"method": method, "source": "%s: %s" % (APPS[self.app_id], CHECK_NAMES[req["kind"]]),
                                               "verdict": verdict, "detail": result.get("detail")}, "curator")
        for i, text in enumerate(result.get("reasoning") or [], 1):
            db.execute("INSERT OR IGNORE INTO reasoning(fact_id, app, agent, step, text, at) VALUES(?,?,?,?,?,?)",
                       (req["fact_id"], self.app_id, "curator", i, str(text)[:1000], core.now_iso()))
        db.execute("UPDATE requests SET status = 'answered', verdict = ?, detail = ?, answered = ? WHERE id = ?",
                   (verdict, (result.get("detail") or "")[:1000], core.now_iso(), req["id"]))
        return self.restatus(db, req["fact_id"])

    # -- reading
    def summary(self):
        q = self.store.query
        return {"folder": self.folder, "database": self.store.path, "read_only": self.store.read_only, "policy": self.policy(),
                "policies": POLICIES, "version": COMMONS_VERSION,
                "facts": self.store.scalar("SELECT count(*) FROM facts", default=0),
                "by_domain": q("SELECT domain, status, count(*) AS n FROM facts GROUP BY domain, status ORDER BY domain, status"),
                "evidence_by_app": q("SELECT app, method, count(*) AS n FROM evidence GROUP BY app, method ORDER BY app, method"),
                "requests": q("SELECT from_app, to_app, kind, status, count(*) AS n FROM requests GROUP BY from_app, to_app, kind, status ORDER BY to_app, kind"),
                "shared": self.store.scalar("SELECT count(*) FROM (SELECT fact_id FROM evidence GROUP BY fact_id HAVING count(DISTINCT app) > 1)", default=0)}

    def search(self, text="", domain=None, status=None, limit=50):
        where, args = [], []
        if text:
            where.append("(subject LIKE ? OR object LIKE ? OR statement LIKE ?)")
            args += ["%" + text + "%"] * 3
        if domain:
            where.append("domain = ?")
            args.append(domain)
        if status:
            where.append("status = ?")
            args.append(status)
        sql = "SELECT f.*, (SELECT count(DISTINCT app) FROM evidence e WHERE e.fact_id = f.id) AS apps FROM facts f"
        sql += (" WHERE " + " AND ".join(where)) if where else ""
        return self.store.query(sql + " ORDER BY f.updated DESC, f.id DESC LIMIT ?", args + [min(int(limit or 50), 500)])

    def fact(self, fid):
        f = self.store.one("SELECT * FROM facts WHERE id = ?", (fid,))
        if not f:
            raise core.UserError("That shared fact no longer exists.")
        f["evidence"] = self.store.query("SELECT * FROM evidence WHERE fact_id = ? ORDER BY app, method, source", (fid,))
        f["reasoning"] = self.store.query("SELECT * FROM reasoning WHERE fact_id = ? ORDER BY app, agent, step", (fid,))
        f["requests"] = self.store.query("SELECT * FROM requests WHERE fact_id = ? ORDER BY id", (fid,))
        return f

    def agent_log(self, db, role, message, ms=None):
        db.execute("INSERT INTO agent_log(at, app, role, message, ms) VALUES(?,?,?,?,?)", (core.now_cs(), self.app_id, role, str(message)[:2000], ms))
        n = db.execute("SELECT max(id) FROM agent_log").fetchone()[0] or 0
        if n % 500 == 0:
            db.execute("DELETE FROM agent_log WHERE id <= ?", (n - 20000,))


class Context:
    """What an application's agents see: the Commons, the licence policy and the harvest cursors."""

    def __init__(self, commons, stop=None):
        self.commons = commons
        self.policy = commons.policy()
        self.stop = stop or (lambda: False)
        self.registry = commons.registry

    def budget(self, key, default):
        """How much one turn harvests for `key`: the approved parameter budget.<app>.<key> (else the default)."""
        v = self.registry.param("budget.%s.%s" % (self.commons.app_id, key), default)
        return v if isinstance(v, (int, float)) and v > 0 else default

    def source_ok(self, key):
        """Is this source approved in the policy registry?"""
        return self.registry.check(key)[0]

    def cursor(self, key, default=0):
        return self.commons.cursor(key, default)

    def allowed(self, licence):
        return self.policy != "commercial" or not is_non_commercial(licence)

    def have(self, domain, subject, predicate, obj):
        return self.commons.store.scalar("SELECT 1 FROM facts WHERE fingerprint = ?", (core.fingerprint(domain, subject, predicate, obj),)) is not None


class Adapter:
    """What each application supplies to its team. Every method is deterministic.
    Every task names its source ("source": registry key), why it is harvested ("why") and, when its size can be
    tuned, its budget key ("budget_key"); items may name a different source per evidence ("source_key")."""

    def budgets(self):                          # default budgets, registered as policy parameters
        return {}

    def survey(self, ctx):                      # Strategist: what is known, what is missing
        return {}

    def strategy(self, survey, ctx):            # Strategist: {"goals": [{"goal", "why", "priority"}], "sources": [...], "budget": {...}}
        return {"goals": [], "sources": [], "budget": {}}

    def plan(self, strategy, ctx):              # Planner: [{"action", "title", "target": {...}}]
        return []

    def execute(self, task, ctx):               # Harvester: {"items": [...], "cursor": {key: value}, "detail": str}
        return {"items": []}

    def verifiers(self, ctx):                   # Curator: {check kind: fn(payload) -> {"verdict", "detail", "reasoning"}}
        return {}

    def curate(self, ctx):                      # Curator: extra upkeep (re-verification); returns [item, ...] to save
        return []


class Team:
    """The four agents of one application, run in order as one harvest cycle."""

    def __init__(self, commons, adapter, log=None):
        self.commons = commons
        self.app_id = commons.app_id
        self.adapter = adapter
        commons.registry.ensure(commons.app_id, dict(adapter.budgets(), **ol.budgets(commons.app_id)))
        self.log = log or (lambda *a: None)
        self._lock = threading.Lock()
        self.state = {"running": False, "role": None, "last": None, "started": None}
        self._timer = None

    def _role(self, role, status, summary, ms):
        with self.commons.store.write() as db:
            db.execute("""INSERT INTO team(app, role, last_run, last_status, last_summary, last_ms, runs) VALUES(?,?,?,?,?,?,1)
                          ON CONFLICT(app, role) DO UPDATE SET last_run=excluded.last_run, last_status=excluded.last_status,
                          last_summary=excluded.last_summary, last_ms=excluded.last_ms, runs=runs+1""",
                       (self.app_id, role, core.now_cs(), status, str(summary)[:1000], ms))
            self.commons.agent_log(db, role, summary, ms)

    def _policy_filter(self, item, task_source, reg):
        """Drop evidence from sources the registry does not approve; drop quotes (third-party wording) unless the
        source's licence class allows storing its text. An item left without evidence is not saved."""
        ev = []
        for e in item.get("evidence") or []:
            key = e.get("source_key") or task_source
            ok, cls, _ = reg.check(key)
            if not ok:
                continue
            e = dict(e, source_key=key, licence_class=cls)
            src = reg.source(key) or {}
            if cls not in hv.TEXT_FREE or src.get("added_by") == "research":   # researched sources: facts only, never wording
                e.pop("quote", None)
            ev.append(e)
        if not ev and item.get("evidence"):
            return None
        return dict(item, evidence=ev)

    def cycle(self, trigger="manual", stop=None, turn=None):
        """Strategist → Planner → (policy check) → Harvester → Curator. Every task is checked against the policy
        registry before it runs and logged — harvested, blocked or skipped — with its source and why."""
        if self.commons.store.read_only:
            raise core.UserError("The shared database failed its check; nothing was harvested.")
        if not self._lock.acquire(blocking=False):
            raise core.UserError("This application's harvest team is already working.")
        out = {"app": self.app_id, "trigger": trigger}
        reg, hlog = self.commons.registry, self.commons.harvest_log
        t_cycle = time.time()
        try:
            self.state.update(running=True, started=core.now_cs())
            ctx = Context(self.commons, stop)
            store = self.commons.store
            pv = reg.version()
            # 1. Strategist
            self.state["role"] = "strategist"
            t0 = time.time()
            survey = self.adapter.survey(ctx)
            strat = self.adapter.strategy(survey, ctx)
            online = ol.plan(ctx, self.app_id)
            if online:
                strat.setdefault("goals", []).append({"goal": "Harvest approved online sources", "priority": 4,
                                                      "why": "%d open sources the admin approved: %s" % (len(online), "; ".join(t["title"] for t in online))})
            strat["survey"] = survey
            strat["policy"] = "registry version %s" % pv
            strat["open_checks"] = store.scalar("SELECT count(*) FROM requests WHERE to_app = ? AND status = 'open'", (self.app_id,), 0)
            with store.write() as db:
                sid = db.execute("INSERT INTO strategies(app, created, body) VALUES(?,?,?)",
                                 (self.app_id, core.now_cs(), json.dumps(strat, ensure_ascii=False, default=str))).lastrowid
                db.execute("DELETE FROM strategies WHERE app = ? AND id NOT IN (SELECT id FROM strategies WHERE app = ? ORDER BY id DESC LIMIT 50)",
                           (self.app_id, self.app_id))
            out["strategy"] = "%d goals" % len(strat.get("goals") or [])
            self._role("strategist", "ok", "; ".join(g["goal"] for g in strat.get("goals") or []) or "nothing to do", int((time.time() - t0) * 1000))
            # 2. Planner, then the policy check of every task
            self.state["role"] = "planner"
            t0 = time.time()
            tasks = self.adapter.plan(strat, ctx) + online
            allowed, blocked = [], 0
            with store.write() as db:
                pid = db.execute("INSERT INTO plans(app, strategy_id, created, status, summary) VALUES(?,?,?,?,?)",
                                 (self.app_id, sid, core.now_cs(), "running", "%d tasks" % len(tasks))).lastrowid
                db.execute("DELETE FROM plans WHERE app = ? AND id NOT IN (SELECT id FROM plans WHERE app = ? ORDER BY id DESC LIMIT 50)",
                           (self.app_id, self.app_id))
            for i, t in enumerate(tasks, 1):
                ok, cls, why = reg.check(t.get("source"))
                if ok and reg.param("disabled.%s.%s" % (self.app_id, t["action"]), False):
                    ok, why = False, "paused by an approved recommendation"
                with store.write() as db:
                    tid = db.execute("INSERT INTO tasks(plan_id, app, step, action, title, target, status, detail) VALUES(?,?,?,?,?,?,?,?)",
                                     (pid, self.app_id, i, t["action"], t["title"], json.dumps(t.get("target") or {}, ensure_ascii=False),
                                      "queued" if ok else "skipped", None if ok else "blocked by policy: " + why)).lastrowid
                    if not ok:
                        blocked += 1
                        hlog.write(db, self.app_id, t["action"], t["title"], t.get("source"), cls, "blocked",
                                   "%s — not harvested: %s" % (t.get("why") or "", why), turn_id=(turn or {}).get("id"), policy_version=pv)
                if ok:
                    allowed.append((tid, t, cls))
            out["plan"] = "%d tasks (%d blocked by policy)" % (len(tasks), blocked)
            self._role("planner", "ok", ("; ".join(t["title"] for t in tasks) or "no tasks") + ("; %d blocked by policy" % blocked if blocked else ""),
                       int((time.time() - t0) * 1000))
            # 3. Harvester: stages items per task; writes only task progress
            self.state["role"] = "harvester"
            t0 = time.time()
            staged, cursors, failed = [], {}, 0
            for tid, t, cls in allowed:
                if ctx.stop():
                    with store.write() as db:
                        db.execute("UPDATE tasks SET status = 'skipped', detail = 'stopped' WHERE id = ?", (tid,))
                    continue
                with store.write() as db:
                    db.execute("UPDATE tasks SET status = 'running', started = ? WHERE id = ?", (core.now_cs(), tid))
                ts = time.time()
                try:
                    r = (ol.execute(t, ctx) if t["action"].startswith("online:") else self.adapter.execute(t, ctx)) or {}
                    items = [x for x in (self._policy_filter(i, t.get("source"), reg) for i in r.get("items") or []) if x]
                    staged.append((tid, t, cls, items, time.time() - ts, None))
                    cursors.update(r.get("cursor") or {})
                    st, detail = "done", r.get("detail") or ""
                except Exception as e:
                    failed += 1
                    items, st, detail = [], "failed", str(e)
                    staged.append((tid, t, cls, [], time.time() - ts, str(e)))
                    self.log("harvest task failed:", t["title"], repr(e))
                with store.write() as db:
                    db.execute("UPDATE tasks SET status = ?, items = ?, finished = ?, detail = ? WHERE id = ?",
                               (st, len(items), core.now_cs(), detail[:1000], tid))
            n_staged = sum(len(x[3]) for x in staged)
            out["harvested"] = n_staged
            self._role("harvester", "failed" if failed and failed == len(allowed) else "ok",
                       "%d items staged from %d tasks%s" % (n_staged, len(allowed), (", %d failed" % failed) if failed else ""),
                       int((time.time() - t0) * 1000))
            # 4. Curator: save task by task (each task's facts and its log entry in one transaction), answer checks, upkeep
            self.state["role"] = "curator"
            t0 = time.time()
            new = merged = 0
            upkeep = [x for x in (self._policy_filter(i, None, reg) for i in (self.adapter.curate(ctx) or [])) if x]
            if upkeep:
                staged.append((None, {"action": "upkeep", "title": "Keep shared facts in step with their sources",
                                      "why": "re-check facts already shared", "source": None}, None, upkeep, 0.0, None))
            for tid, t, cls, items, secs, err in staged:
                if err:
                    with store.write() as db:
                        hlog.write(db, self.app_id, t["action"], t["title"], t.get("source"), cls, "failed", (t.get("why") or "") + " — " + err,
                                   seconds=secs, budget_key=t.get("budget_key"), turn_id=(turn or {}).get("id"), policy_version=pv)
                    continue
                for k in range(0, max(1, len(items)), BATCH):
                    with store.write() as db:
                        tn = tm = 0
                        fids = []
                        for item in items[k:k + BATCH]:
                            fid, is_new = self.commons.save(db, item)
                            fids.append(fid)
                            tn += is_new; tm += not is_new
                        new += tn; merged += tm
                        srcs = sorted({e.get("source_key") or "" for i in items[k:k + BATCH] for e in i.get("evidence") or []})
                        hid = hlog.write(db, self.app_id, t["action"], t["title"] + ("" if k == 0 else " (part %d)" % (k // BATCH + 1)),
                                         t.get("source") or ",".join(srcs), cls or "mixed", "harvested" if t["action"] != "upkeep" else "refreshed",
                                         t.get("why") or "", len(items[k:k + BATCH]), tn, tm, secs if k == 0 else 0.0, t.get("budget_key"),
                                         (turn or {}).get("id"), pv)
                        for j in range(0, len(fids), 500):
                            part = fids[j:j + 500]
                            db.execute("UPDATE evidence SET harvest_id = ? WHERE app = ? AND harvest_id IS NULL AND fact_id IN (%s)"
                                       % ",".join("?" * len(part)), [hid, self.app_id] + part)
            with store.write() as db:
                for key, v in cursors.items():                  # cursors move only when what they cover is saved
                    self.commons.set_setting("cursor:%s:%s" % (self.app_id, key), v, db)
            answered, verdicts = 0, {}
            fns = self.adapter.verifiers(ctx)
            for req in self.commons.open_requests():
                fn = fns.get(req["kind"])
                try:
                    res = fn(json.loads(req["payload"])) if fn else {"verdict": "cannot_check", "detail": "this application has no check for this"}
                except Exception as e:
                    res = {"verdict": "cannot_check", "detail": "the check failed: %s" % e}
                with store.write() as db:
                    self.commons.answer(db, req, res)
                answered += 1
                verdicts[res.get("verdict", "cannot_check")] = verdicts.get(res.get("verdict", "cannot_check"), 0) + 1
            with store.write() as db:
                db.execute("UPDATE plans SET status = ?, summary = ? WHERE id = ?",
                           ("done" if not failed else "done with failures", "%d tasks (%d blocked), %d new facts, %d merged, %d checks answered"
                            % (len(tasks), blocked, new, merged, answered), pid))
            out.update(new=new, merged=merged, upkeep=len(upkeep), checks_answered=answered, verdicts=verdicts, blocked=blocked,
                       seconds=round(time.time() - t_cycle, 2))
            self._role("curator", "ok", "%d new facts, %d merged (%d from upkeep), %d checks answered %s"
                       % (new, merged, len(upkeep), answered, json.dumps(verdicts) if verdicts else ""), int((time.time() - t0) * 1000))
            if new or merged or answered:
                try:
                    store.backup("harvest")
                except Exception as e:                  # another application may be pruning the same backups
                    self.log("commons backup:", e)
            try:
                self.commons.harvest_log.archive()
                out["recommendations"] = self.commons.learner.review(self.app_id)
            except Exception as e:
                self.log("harvest archive / review:", e)
            self.state["last"] = dict(out, finished=core.now_cs())
            return out
        except Exception as e:
            self.state["last"] = {"error": str(e), "finished": core.now_cs()}
            try:
                self._role(self.state["role"] or "strategist", "failed", str(e), None)
            except Exception:
                pass
            raise
        finally:
            self.state.update(running=False, role=None)
            self._lock.release()

    def engine_turn(self, trigger="engine"):
        """Ask the engine whether it is this application's turn; if so, run a cycle and report back."""
        turn = self.commons.engine.claim(self.app_id)
        if not turn:
            return None
        try:
            out = self.cycle("%s: %s" % (trigger, turn["reason"]), turn=turn)
        except Exception as e:
            out = {"error": str(e), "new": 0, "checks_answered": 0}
        self.commons.engine.finish(turn, out)
        return out

    def run_in_background(self, trigger="manual"):
        if self.state["running"]:
            raise core.UserError("This application's harvest team is already working.")

        def go():
            turn = self.commons.engine.manual(self.app_id, "started by hand")
            try:
                out = self.cycle(trigger, turn=turn)
            except Exception as e:
                out = {"error": str(e), "new": 0, "checks_answered": 0}
                self.log("harvest cycle failed:", repr(e))
            self.commons.engine.finish(turn, out)
        threading.Thread(target=go, daemon=True).start()
        return {"started": True}

    def auto(self):
        return self.commons.setting("auto:%s" % self.app_id, "on") == "on"

    def start_schedule(self, first_delay=20, every=None):
        """Automatic harvesting: every few seconds (schedule.tick_s) ask the harvesting engine whose turn it is; the
        engine alternates language, STEM and history across the running applications."""
        def tick(delay):
            def run():
                try:
                    if self.auto() and not self.state["running"]:
                        self.engine_turn("automatic")
                    else:
                        self.commons.engine.heartbeat(self.app_id, hv.ENGINE_VERSION)
                except Exception as e:
                    self.log("automatic harvest failed:", repr(e))
                tick(every or float(self.commons.registry.param("schedule.tick_s", 30)))
            self._timer = threading.Timer(delay, run)
            self._timer.daemon = True
            self._timer.start()
        tick(first_delay)

    def status(self):
        st = self.commons.store
        strat = st.one("SELECT * FROM strategies WHERE app = ? ORDER BY id DESC LIMIT 1", (self.app_id,))
        if strat:
            strat["body"] = json.loads(strat["body"])
        plan = st.one("SELECT * FROM plans WHERE app = ? ORDER BY id DESC LIMIT 1", (self.app_id,))
        if plan:
            plan["tasks"] = st.query("SELECT * FROM tasks WHERE plan_id = ? ORDER BY step", (plan["id"],))
        roles = {(r["app"], r["role"]): r for r in st.query("SELECT * FROM team")}
        teams = [{"app": a, "name": APPS[a], "agents": [dict(roles.get((a, k)) or {}, role=k, title=t, duty=d) for k, t, d in ROLES]}
                 for a in APPS]
        return {"app": self.app_id, "state": self.state, "auto": self.auto(), "strategy": strat, "plan": plan, "teams": teams,
                "log": st.query("SELECT * FROM agent_log ORDER BY id DESC LIMIT 60"), "checks": CHECK_NAMES, "check_owner": CHECKS,
                "commons": self.commons.summary()}


def add_routes(api, team, app_folder):
    """The Commons pages every application shares."""
    c = team.commons

    @api.get("/api/commons/status")
    def status(p):
        return team.status()

    @api.post("/api/commons/run")
    def run(p):
        return team.run_in_background("manual")

    @api.post("/api/commons/settings")
    def settings(p):
        if p.get("policy"):
            if p["policy"] not in POLICIES:
                raise core.UserError("Unknown licence policy.")
            c.set_setting("licence_policy", p["policy"])
        if p.get("auto") in ("on", "off"):
            c.set_setting("auto:%s" % team.app_id, p["auto"])
        if p.get("online") in ("on", "off"):
            c.set_setting("online:%s" % team.app_id, p["online"])
        return team.status()

    @api.post("/api/commons/facts")
    def facts(p):
        return {"facts": c.search(p.get("q") or "", p.get("domain") or None, p.get("status") or None, p.get("limit") or 50)}

    @api.post("/api/commons/fact")
    def fact(p):
        return c.fact(int(p.get("id")))

    @api.post("/api/commons/folder")
    def folder(p):
        if not (p.get("folder") or "").strip():
            raise core.UserError("Give the shared folder's path.")
        set_commons_folder(app_folder, p["folder"])
        return {"folder": commons_folder(app_folder), "restart": True}

    # -- the harvesting engine, policy registry, approvals and harvest log
    @api.get("/api/harvest/status")
    def h_status(p):
        return harvest_status(team)

    @api.post("/api/harvest/admin")
    def h_admin(p):
        return c.approvals.set_admin(p.get("new") or "", p.get("old") or None)

    @api.post("/api/harvest/decide")
    def h_decide(p):
        return c.approvals.decide(p.get("id"), bool(p.get("approve")), p.get("passphrase") or "", p.get("note") or "")

    @api.post("/api/harvest/source")
    def h_source(p):
        return c.approvals.admin_source(p.get("key"), p.get("status"), p.get("passphrase") or "", p.get("reason") or "",
                                        p.get("licence_class") or None, bool(p.get("accept_restriction")))

    @api.post("/api/harvest/source_add")
    def h_source_add(p):
        c.approvals._require(p.get("passphrase") or "")
        key = "".join(ch for ch in (p.get("key") or "").lower() if ch.isalnum() or ch in "-_.")
        if not key or not (p.get("name") or "").strip():
            raise core.UserError("Give the source a short key and a name.")
        c.registry.add_source(key, p["name"].strip(), p.get("apps") or "", p.get("kind") or "", p.get("licence") or "",
                              p.get("licence_class") or "unknown", p.get("url") or "", "admin", p.get("reason") or "added by the admin")
        return {"ok": True, "key": key}

    @api.post("/api/harvest/param")
    def h_param(p):
        c.approvals._require(p.get("passphrase") or "")
        val = p.get("value")
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except ValueError:
                pass
        c.registry.set_param(p.get("key"), val, "admin", p.get("reason") or "set by the admin")
        return {"ok": True}

    @api.post("/api/harvest/key")
    def h_key(p):
        c.approvals._require(p.get("passphrase") or "")
        try:
            ol.save_key(c.folder, p.get("service"), p.get("key") or "")
        except ValueError as e:
            raise core.UserError(str(e))
        return {"keys": ol.key_status(c.folder)}

    @api.post("/api/harvest/dpla_request")
    def h_dpla(p):
        c.approvals._require(p.get("passphrase") or "")
        try:
            return ol.request_dpla_key(p.get("email"))
        except ValueError as e:
            raise core.UserError(str(e))
        except Exception as e:
            raise core.UserError("DPLA did not accept the request: %s" % e)

    @api.post("/api/harvest/log")
    def h_log(p):
        return {"log": c.harvest_log.recent(p.get("app") or None, p.get("decision") or None, p.get("limit") or 200)}

    @api.post("/api/harvest/verify")
    def h_verify(p):
        return c.harvest_log.verify()

    @api.post("/api/harvest/archive")
    def h_archive(p):
        return c.harvest_log.archive()

    @api.post("/api/harvest/review")
    def h_review(p):
        return {"made": c.learner.review(team.app_id), "pending": c.approvals.list("pending")}


def harvest_status(team):
    """Everything the Harvesting page shows: the rotation, approvals, registry, parameters and learning metrics."""
    c = team.commons
    st = c.store
    metrics = st.query("""SELECT app, domain, count(*) AS tasks, sum(decision = 'harvested') AS harvested, sum(decision = 'blocked') AS blocked,
                          sum(decision = 'failed') AS failed, sum(items) AS items, sum(new) AS new, sum(merged) AS merged,
                          round(sum(seconds), 1) AS seconds FROM harvest_log GROUP BY app ORDER BY app""")
    for m in metrics:
        m["new_share"] = round((m["new"] or 0) / m["items"], 3) if m["items"] else None
        m["facts_per_s"] = round((m["new"] or 0) / m["seconds"], 1) if m["seconds"] else None
    trend = st.query("""SELECT substr(at, 1, 10) AS day, domain, sum(new) AS new, sum(items) AS items, round(sum(seconds), 1) AS seconds
                        FROM harvest_log WHERE decision = 'harvested' GROUP BY day, domain ORDER BY day DESC LIMIT 60""")
    return {"app": team.app_id, "auto": team.auto(), "running": team.state["running"], "engine": c.engine.status(),
            "online": c.setting("online:%s" % team.app_id, "on") != "off", "keys": ol.key_status(c.folder), "offline_env": bool(os.environ.get("QB_OFFLINE")),
            "harvesters": [{"name": k, "app": h[0], "source": h[1], "title": h[2], "why": h[3],
                            "approved": c.registry.check(h[1])[0], "needs_key": ol.NEEDS_KEY.get(k),
                            "cursor": c.store.scalar("SELECT value FROM settings WHERE key = ?",
                                                                                                ("cursor:%s:online:%s" % (h[0], k),))}
                           for k, h in ol.HARVESTERS.items()],
            "admin_set": c.approvals.admin_set(), "pending": c.approvals.list("pending"), "decided": c.approvals.list(None, 40),
            "sources": c.registry.sources(), "classes": {k: {"allowed": v[0], "why": v[1]} for k, v in hv.LICENCE_CLASSES.items()},
            "params": c.registry.params(), "versions": c.registry.versions(40), "policy_version": c.registry.version(),
            "metrics": metrics, "trend": trend, "log_entries": st.scalar("SELECT count(*) FROM harvest_log", default=0),
            "archive_folder": os.path.join(c.folder, "archives")}


def attach(app, app_id, adapter):
    """Give an application its Commons, its team and the shared pages. A Commons that cannot be opened
    never stops the application: its own work goes on and the shared page says why."""
    try:
        app.commons = Commons(commons_folder(app.folder), app_id, app.log)
        app.team = Team(app.commons, adapter, app.log)
        add_routes(app.api, app.team, app.folder)
    except Exception as e:
        app.log("shared database (Commons) unavailable:", repr(e))
        app.commons = app.team = None
        why = str(e)

        @app.api.get("/api/commons/status")
        def unavailable(p):
            raise core.UserError("The shared database could not be opened (%s). This application works on its own meanwhile." % why)

        @app.api.get("/api/harvest/status")
        def h_unavailable(p):
            raise core.UserError("The shared database could not be opened (%s); the harvesting engine needs it." % why)
    return app.team
