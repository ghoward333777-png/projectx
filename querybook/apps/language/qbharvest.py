"""qbharvest — the harvesting policy registry and the automated harvesting engine, shared by the three QueryBook
applications through the Commons database.

  Policy registry  every source a harvest team may read, with its licence, its licence class and its status
                   (approved / blocked / pending). Only classes that put NO condition on QueryBook are approved by
                   default: public domain, CC0, facts (not protected by copyright — QueryBook stores the facts, not
                   anyone's wording), US federal government works, QueryBook's own calculations, and facts the admin
                   entered with their citation. Attribution, share-alike, non-commercial, no-derivatives, someone
                   else's wording, restrictive terms of service and unknown licences are blocked. Parameters
                   (budgets, rotation weights, schedule) live here too, and every change is versioned.
  Engine           decides which application harvests next — alternating language, STEM and history — so that
                   checks one application asked of another are answered on the very next turn, domains that are
                   producing only duplicates back off (less volume), and no domain runs twice in a row while
                   another has work (less waiting).
  Learner          after every turn, compares the measured results (new facts per second, share of new vs
                   duplicate facts, failures, how long checks waited) with the current parameters and RECOMMENDS
                   changes. Nothing it recommends takes effect until the admin approves it with the admin
                   passphrase; approvals and rejections are kept.
  Harvest record   every task — harvested, blocked or skipped — is logged with its source, licence class and the
                   reason it was harvested; each entry carries the hash of the one before (tamper-evident) and the
                   log is archived to monthly JSON-lines files in the Commons folder.

Deterministic programs, not AI models. Standard library only.
"""
import datetime, hashlib, hmac, json, os, secrets

import qbcore as core

ENGINE_VERSION = "1.0.0"

SCHEMA = """
CREATE TABLE policy_sources (
  id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, name TEXT NOT NULL, apps TEXT NOT NULL, kind TEXT, licence TEXT NOT NULL,
  licence_class TEXT NOT NULL, url TEXT, licence_url TEXT, status TEXT NOT NULL, reason TEXT, added_by TEXT NOT NULL, added TEXT NOT NULL,
  decided_by TEXT, decided_at TEXT
);
CREATE TABLE policy_params (key TEXT PRIMARY KEY, value TEXT NOT NULL, description TEXT, updated TEXT NOT NULL, updated_by TEXT NOT NULL);
CREATE TABLE policy_versions (id INTEGER PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL, change TEXT NOT NULL, reason TEXT);
CREATE TABLE harvest_log (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, app TEXT NOT NULL, domain TEXT NOT NULL, action TEXT NOT NULL, title TEXT,
  source_key TEXT, licence_class TEXT, decision TEXT NOT NULL, items INTEGER, new INTEGER, merged INTEGER, seconds REAL,
  reason TEXT, budget_key TEXT, turn_id INTEGER, policy_version INTEGER, prev_hash TEXT NOT NULL, hash TEXT NOT NULL
);
CREATE INDEX harvest_log_app ON harvest_log(app, action, id);
CREATE TABLE recommendations (
  id INTEGER PRIMARY KEY, created TEXT NOT NULL, app TEXT, kind TEXT NOT NULL, title TEXT NOT NULL, rationale TEXT NOT NULL,
  evidence TEXT, change TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'pending',
  decided_by TEXT, decided_at TEXT, note TEXT
);
CREATE TABLE engine_turns (
  id INTEGER PRIMARY KEY, started TEXT NOT NULL, ended TEXT, app TEXT NOT NULL, domain TEXT NOT NULL, reason TEXT, scores TEXT, result TEXT
);
CREATE TABLE app_heartbeat (app TEXT PRIMARY KEY, at REAL NOT NULL, version TEXT);
ALTER TABLE evidence ADD COLUMN harvest_id INTEGER
"""

DOMAIN_OF = {"language": "language", "stem": "stem", "facts": "history"}

# licence class → (allowed by default, why)
LICENCE_CLASSES = {
    "public-domain": (True, "No copyright: free to use with no conditions."),
    "cc0": (True, "Dedicated to the public domain (CC0): no conditions."),
    "facts": (True, "Facts and defined values are not protected by copyright; QueryBook stores the facts, never anyone's wording."),
    "us-federal": (True, "A work of the US federal government: no US copyright (17 U.S.C. § 105)."),
    "computed": (True, "Calculated by QueryBook itself."),
    "user-facts": (True, "Facts the admin entered with their citation; no third-party wording is shared."),
    "attribution": (False, "Requires attribution (e.g. CC BY): a condition on QueryBook."),
    "share-alike": (False, "Share-alike (e.g. CC BY-SA, GFDL): would impose its licence on QueryBook."),
    "non-commercial": (False, "Non-commercial only (e.g. CC BY-NC): restricts how QueryBook may be used."),
    "no-derivatives": (False, "No derivatives (CC BY-ND): forbids adapting the material."),
    "copyrighted-text": (False, "Someone else's wording (articles, headlines, books): protected by copyright."),
    "terms-of-service": (False, "Website or API terms restrict reuse."),
    "unknown": (False, "The licence has not been established: blocked until the admin classifies it."),
}
# classes whose wording itself may be stored (otherwise only the facts are kept and quotes are dropped)
TEXT_FREE = {"public-domain", "cc0", "us-federal", "computed"}

SEED_SOURCES = [
    # key, name, apps, kind, licence, class, url, reason
    ("webster-1913", "Webster's Unabridged Dictionary (1913)", "language", "dictionary", "Public domain (published 1913)", "public-domain",
     "https://www.gutenberg.org/ebooks/29765", "English meanings: out of copyright."),
    ("muse-bilingual", "MUSE bilingual dictionaries (Facebook AI Research)", "language", "word lists", "CC BY-NC 4.0", "non-commercial",
     "https://github.com/facebookresearch/MUSE", "Non-commercial licence: would restrict QueryBook. Replace with an unrestricted source."),
    ("codata-2018", "CODATA 2018 recommended values (NIST)", "stem", "reference table", "Facts / defined values", "facts",
     "https://physics.nist.gov/cuu/Constants/", "Physical constants are measured or defined values (facts)."),
    ("iupac-atomic-weights", "IUPAC standard atomic weights", "stem", "reference table", "Facts", "facts",
     "https://iupac.qmul.ac.uk/AtWt/", "Atomic numbers and weights are facts."),
    ("si-definitions", "SI unit definitions (BIPM SI Brochure, NIST SP 811)", "stem", "reference table", "Facts / defined values", "facts",
     "https://www.bipm.org/en/publications/si-brochure", "Exact unit factors are definitions (facts); no brochure text is copied."),
    ("stem-computed", "QueryBook Math, Science & Engineering calculations", "stem", "computation", "Computed by QueryBook", "computed", None,
     "Molar masses, derived constants and checks calculated here."),
    ("stem-saved-answers", "Verified saved answers (recomputed)", "stem", "computation", "Computed by QueryBook", "computed", None,
     "The admin's own calculations, recomputed before sharing."),
    ("history-user-sources", "Facts entered in History & News with their sources", "facts", "user records", "Facts with citation", "user-facts", None,
     "Facts and dates are not copyrightable; the citation is kept, quotes from the source are not shared."),
    ("news-headlines", "News feed headlines", "facts", "news feeds", "Publishers' copyright", "copyrighted-text", None,
     "Headlines are the publishers' wording: not harvested. Add a fact by hand with its source instead."),
]

DEFAULT_PARAMS = {
    "rotation.check_weight": (2.0, "How strongly waiting cross-checks pull an application's turn forward"),
    "rotation.repeat_penalty": (5.0, "Penalty for giving the same domain two turns in a row while another has work"),
    "rotation.turn_timeout_s": (900, "A turn not finished within this time is given up (the application may have closed)"),
    "rotation.active_window_s": (180, "An application counts as running if it checked in within this time"),
    "rotation.idle_backoff_max_s": (14400, "Longest pause for a domain that is producing nothing new"),
    "schedule.tick_s": (30, "How often each application asks the engine whether it is its turn"),
}


def _now():
    return core.now_cs()


def _hash(prev, row):
    return hashlib.sha256((prev + json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)).encode("utf-8")).hexdigest()


class Registry:
    """The harvesting policy registry (sources, licence classes, parameters, versions)."""

    def __init__(self, commons):
        self.c = commons
        self.store = commons.store

    def ensure(self, app_id=None, budgets=None):
        """Seed the built-in sources and default parameters (never overwriting the admin's decisions); register an
        application's budget defaults as parameters."""
        if self.store.read_only:
            return
        with self.store.write() as db:
            for key, name, apps, kind, lic, cls, url, why in SEED_SOURCES:
                ok = LICENCE_CLASSES[cls][0]
                db.execute("""INSERT OR IGNORE INTO policy_sources(key, name, apps, kind, licence, licence_class, url, status, reason, added_by, added)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (key, name, apps, kind, lic, cls, url, "approved" if ok else "blocked", why, "system", _now()))
            for key, (val, desc) in DEFAULT_PARAMS.items():
                db.execute("INSERT OR IGNORE INTO policy_params(key, value, description, updated, updated_by) VALUES(?,?,?,?,?)",
                           (key, json.dumps(val), desc, _now(), "system"))
            for k, v in (budgets or {}).items():
                db.execute("INSERT OR IGNORE INTO policy_params(key, value, description, updated, updated_by) VALUES(?,?,?,?,?)",
                           ("budget.%s.%s" % (app_id, k), json.dumps(v), "%s: how much one turn harvests (%s)" % (app_id, k), _now(), "system"))

    # -- sources
    def source(self, key):
        return self.store.one("SELECT * FROM policy_sources WHERE key = ?", (key,))

    def sources(self):
        return self.store.query("SELECT * FROM policy_sources ORDER BY apps, key")

    def check(self, key):
        """(allowed?, licence class, reason) for one source key. Unknown keys are registered as pending/unknown."""
        if not key:
            return False, "unknown", "no source named"
        s = self.source(key)
        if s is None:
            with self.store.write() as db:
                db.execute("""INSERT OR IGNORE INTO policy_sources(key, name, apps, kind, licence, licence_class, status, reason, added_by, added)
                              VALUES(?,?,?,?,?,?,?,?,?,?)""", (key, key, self.c.app_id, "unregistered", "unknown", "unknown", "pending",
                                                              "seen in a harvest plan; licence not yet established", "engine", _now()))
            return False, "unknown", "source not in the registry (registered as pending)"
        if s["status"] != "approved":
            return False, s["licence_class"], "%s: %s" % (s["status"], s["reason"] or LICENCE_CLASSES.get(s["licence_class"], (0, ""))[1])
        return True, s["licence_class"], "approved: " + (s["reason"] or "")

    def set_source(self, key, status, actor, reason, db=None, licence_class=None):
        if status not in ("approved", "blocked", "pending"):
            raise core.UserError("status must be approved, blocked or pending")
        s = self.source(key)
        if not s:
            raise core.UserError("No such source.")
        cls = licence_class or s["licence_class"]
        if cls not in LICENCE_CLASSES:
            raise core.UserError("Unknown licence class.")

        def run(d):
            d.execute("UPDATE policy_sources SET status = ?, licence_class = ?, reason = ?, decided_by = ?, decided_at = ? WHERE key = ?",
                      (status, cls, reason, actor, _now(), key))
            self._version(d, actor, {"source": key, "status": status, "licence_class": cls, "was": [s["status"], s["licence_class"]]}, reason)
        if db is not None:
            run(db)
        else:
            with self.store.write() as d:
                run(d)

    def add_source(self, key, name, apps, kind, licence, licence_class, url, actor, reason):
        if licence_class not in LICENCE_CLASSES:
            raise core.UserError("Unknown licence class.")
        with self.store.write() as db:
            db.execute("""INSERT INTO policy_sources(key, name, apps, kind, licence, licence_class, url, status, reason, added_by, added)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (key, name, apps, kind, licence, licence_class, url, "pending", reason, actor, _now()))
            self._version(db, actor, {"source_added": key, "licence_class": licence_class}, reason)

    # -- parameters
    def param(self, key, default=None):
        v = self.store.scalar("SELECT value FROM policy_params WHERE key = ?", (key,))
        return json.loads(v) if v is not None else default

    def params(self):
        out = self.store.query("SELECT * FROM policy_params ORDER BY key")
        for r in out:
            r["value"] = json.loads(r["value"])
        return out

    def set_param(self, key, value, actor, reason, db=None):
        def run(d):
            old = d.execute("SELECT value FROM policy_params WHERE key = ?", (key,)).fetchone()
            d.execute("""INSERT INTO policy_params(key, value, description, updated, updated_by) VALUES(?,?,?,?,?)
                         ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated = excluded.updated, updated_by = excluded.updated_by""",
                      (key, json.dumps(value), None, _now(), actor))
            self._version(d, actor, {"param": key, "value": value, "was": json.loads(old[0]) if old else None}, reason)
        if db is not None:
            run(db)
        else:
            with self.store.write() as d:
                run(d)

    def _version(self, db, actor, change, reason):
        db.execute("INSERT INTO policy_versions(at, actor, change, reason) VALUES(?,?,?,?)", (_now(), actor, json.dumps(change, ensure_ascii=False), reason))

    def version(self):
        return self.store.scalar("SELECT max(id) FROM policy_versions", default=0)

    def versions(self, limit=100):
        out = self.store.query("SELECT * FROM policy_versions ORDER BY id DESC LIMIT ?", (limit,))
        for r in out:
            r["change"] = json.loads(r["change"])
        return out


class HarvestLog:
    """Every harvest task, its source and why — hash-chained, archived monthly."""

    def __init__(self, commons):
        self.c = commons
        self.store = commons.store

    def write(self, db, app, action, title, source_key, licence_class, decision, reason, items=0, new=0, merged=0, seconds=0.0,
              budget_key=None, turn_id=None, policy_version=None):
        prev = db.execute("SELECT hash FROM harvest_log ORDER BY id DESC LIMIT 1").fetchone()
        prev = prev[0] if prev else "0" * 64
        row = {"at": _now(), "app": app, "domain": DOMAIN_OF.get(app, app), "action": action, "title": (title or "")[:300],
               "source_key": source_key, "licence_class": licence_class, "decision": decision, "items": int(items), "new": int(new),
               "merged": int(merged), "seconds": round(float(seconds), 3), "reason": (reason or "")[:1000], "budget_key": budget_key,
               "turn_id": turn_id, "policy_version": policy_version}
        h = _hash(prev, row)
        cols = list(row) + ["prev_hash", "hash"]
        return db.execute("INSERT INTO harvest_log(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))),
                          [row[k] for k in row] + [prev, h]).lastrowid

    def verify(self):
        prev, n = "0" * 64, 0
        for r in self.store.query("SELECT * FROM harvest_log ORDER BY id"):
            row = {k: r[k] for k in ("at", "app", "domain", "action", "title", "source_key", "licence_class", "decision", "items", "new",
                                     "merged", "seconds", "reason", "budget_key", "turn_id", "policy_version")}
            if r["prev_hash"] != prev or _hash(prev, row) != r["hash"]:
                return {"ok": False, "entries": n, "broken_at": r["id"]}
            prev, n = r["hash"], n + 1
        return {"ok": True, "entries": n, "last_hash": prev}

    def recent(self, app=None, decision=None, limit=200):
        where, args = [], []
        if app:
            where.append("app = ?"); args.append(app)
        if decision:
            where.append("decision = ?"); args.append(decision)
        sql = "SELECT * FROM harvest_log" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?"
        return self.store.query(sql, args + [min(int(limit), 2000)])

    def archive(self):
        """Append the entries not yet archived to <commons>/archives/harvest-YYYY-MM.jsonl (one file per month)."""
        last = int(self.c.setting("archive:last_id", 0) or 0)
        rows = self.store.query("SELECT * FROM harvest_log WHERE id > ? ORDER BY id LIMIT 20000", (last,))
        if not rows:
            return {"archived": 0}
        folder = os.path.join(self.c.folder, "archives")
        os.makedirs(folder, exist_ok=True)
        by_month = {}
        for r in rows:
            by_month.setdefault(r["at"][:7], []).append(r)
        for month, rs in by_month.items():
            with open(os.path.join(folder, "harvest-%s.jsonl" % month), "a", encoding="utf-8") as f:
                for r in rs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        self.c.set_setting("archive:last_id", rows[-1]["id"])
        return {"archived": len(rows), "folder": folder}


class Approvals:
    """AI-recommended changes waiting for the admin, and the admin passphrase that decides them."""

    def __init__(self, commons, registry):
        self.c, self.reg, self.store = commons, registry, commons.store

    # -- admin passphrase (PBKDF2-SHA256)
    def admin_set(self):
        return bool(self.c.setting("admin:pass"))

    def set_admin(self, new, old=None):
        if len(new or "") < 8:
            raise core.UserError("Choose an admin passphrase of at least 8 characters.")
        if self.admin_set() and not self.check_admin(old):
            raise core.UserError("The current admin passphrase is not correct.")
        salt = secrets.token_hex(16)
        h = hashlib.pbkdf2_hmac("sha256", new.encode("utf-8"), bytes.fromhex(salt), 200000).hex()
        self.c.set_setting("admin:pass", salt + "$" + h)
        with self.store.write() as db:
            self.reg._version(db, "admin", {"admin_passphrase": "set"}, "admin passphrase set or changed")
        return {"ok": True}

    def check_admin(self, passphrase):
        v = self.c.setting("admin:pass")
        if not v or not passphrase:
            return False
        salt, h = v.split("$", 1)
        return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), bytes.fromhex(salt), 200000).hex(), h)

    def _require(self, passphrase):
        if not self.admin_set():
            raise core.UserError("Set the admin passphrase first (Harvesting tab → Admin).")
        if not self.check_admin(passphrase):
            raise core.UserError("Admin passphrase not correct — nothing was changed.")

    # -- recommendations
    def recommend(self, db, app, kind, title, rationale, evidence, change):
        fp = core.fingerprint(kind, app or "", json.dumps(change, sort_keys=True))
        cur = db.execute("""INSERT OR IGNORE INTO recommendations(created, app, kind, title, rationale, evidence, change, fingerprint)
                            VALUES(?,?,?,?,?,?,?,?)""", (_now(), app, kind, title, rationale, json.dumps(evidence, default=str), json.dumps(change), fp))
        return cur.rowcount

    def list(self, status=None, limit=200):
        sql = "SELECT * FROM recommendations" + (" WHERE status = ?" if status else "") + " ORDER BY id DESC LIMIT ?"
        out = self.store.query(sql, ([status] if status else []) + [limit])
        for r in out:
            r["evidence"], r["change"] = json.loads(r["evidence"] or "null"), json.loads(r["change"])
        return out

    def decide(self, rid, approve, passphrase, note=""):
        self._require(passphrase)
        r = self.store.one("SELECT * FROM recommendations WHERE id = ?", (int(rid),))
        if not r:
            raise core.UserError("No such recommendation.")
        if r["status"] != "pending":
            raise core.UserError("Already decided (%s)." % r["status"])
        change = json.loads(r["change"])
        with self.store.write() as db:
            if approve:
                why = "approved recommendation #%d: %s" % (r["id"], r["title"])
                if change["type"] == "param":
                    self.reg.set_param(change["key"], change["value"], "admin", why, db)
                elif change["type"] == "source":
                    self.reg.set_source(change["key"], change["status"], "admin", why, db, change.get("licence_class"))
                status = "applied" if change["type"] in ("param", "source") else "acknowledged"
            else:
                status = "rejected"
            db.execute("UPDATE recommendations SET status = ?, decided_by = 'admin', decided_at = ?, note = ? WHERE id = ?",
                       (status, _now(), (note or "")[:500], r["id"]))
        return {"id": r["id"], "status": status}

    def admin_source(self, key, status, passphrase, reason, licence_class=None, accept_restriction=False):
        """The admin's own registry decision. Approving a restricted licence class needs an explicit acceptance."""
        self._require(passphrase)
        cls = licence_class or (self.reg.source(key) or {}).get("licence_class")
        if status == "approved" and cls in LICENCE_CLASSES and not LICENCE_CLASSES[cls][0] and not accept_restriction:
            raise core.UserError("This licence class (%s) puts restrictions on QueryBook: %s Tick the acceptance box to approve it anyway."
                                 % (cls, LICENCE_CLASSES[cls][1]))
        self.reg.set_source(key, status, "admin", reason or "admin decision", licence_class=licence_class)
        return {"ok": True}


class Engine:
    """Turn-taking across the three applications (alternating language, STEM and history)."""

    def __init__(self, commons, registry):
        self.c, self.reg, self.store = commons, registry, commons.store

    def heartbeat(self, app, version=""):
        with self.store.write() as db:
            db.execute("INSERT OR REPLACE INTO app_heartbeat(app, at, version) VALUES(?,?,?)",
                       (app, datetime.datetime.now(datetime.timezone.utc).timestamp(), version))

    def _active(self, db, now):
        win = float(self.reg.param("rotation.active_window_s", 180))
        return [r[0] for r in db.execute("SELECT app FROM app_heartbeat WHERE at >= ? ORDER BY app", (now - win,))]

    def _app_state(self, db, app):
        """Recent productivity of an application: its last finished turns."""
        rows = db.execute("SELECT result, ended FROM engine_turns WHERE app = ? AND ended IS NOT NULL ORDER BY id DESC LIMIT 5", (app,)).fetchall()
        res = [json.loads(r[0] or "{}") for r in rows]
        empty = 0
        for r in res:                                      # consecutive turns that produced nothing new
            if r.get("new", 0) == 0 and r.get("checks_answered", 0) == 0:
                empty += 1
            else:
                break
        rate = [r.get("new", 0) / max(0.5, r.get("seconds", 1.0)) for r in res]
        last_end = rows[0][1] if rows else None
        return {"empty_streak": empty, "rate": sum(rate) / len(rate) if rate else None, "last_end": last_end}

    def claim(self, app):
        """Whose turn is it? Returns the new turn if it is `app`'s, else None. Atomic across processes."""
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        tmo = float(self.reg.param("rotation.turn_timeout_s", 900))
        with self.store.write() as db:
            db.execute("INSERT OR REPLACE INTO app_heartbeat(app, at, version) VALUES(?,?,?)", (app, now, ENGINE_VERSION))
            cur = db.execute("SELECT id, app, started FROM engine_turns WHERE ended IS NULL ORDER BY id DESC LIMIT 1").fetchone()
            if cur:
                started = _ts(cur[2])
                if now - started < tmo:
                    return None                            # someone is harvesting
                db.execute("UPDATE engine_turns SET ended = ?, result = ? WHERE id = ?", (_now(), json.dumps({"timeout": True}), cur[0]))
            active = self._active(db, now)
            if app not in active:
                active.append(app)
            last = db.execute("SELECT app FROM engine_turns ORDER BY id DESC LIMIT 1").fetchone()
            last = last[0] if last else None
            w_check = float(self.reg.param("rotation.check_weight", 2.0))
            w_rep = float(self.reg.param("rotation.repeat_penalty", 5.0))
            back_max = float(self.reg.param("rotation.idle_backoff_max_s", 14400))
            scores, why = {}, {}
            for a in sorted(active):
                st = self._app_state(db, a)
                checks = db.execute("SELECT count(*) FROM requests WHERE to_app = ? AND status = 'open'", (a,)).fetchone()[0]
                s, reasons = 1.0, []
                if st["rate"] is None:
                    s += 3.0; reasons.append("has not harvested yet")
                else:
                    s += min(3.0, st["rate"] / 50.0); reasons.append("recent rate %.1f new facts/s" % st["rate"])
                if checks:
                    s += w_check * min(5, checks) / 5.0 * 3; reasons.append("%d checks waiting for it" % checks)
                if st["empty_streak"]:
                    pause = min(back_max, 60.0 * (4 ** (st["empty_streak"] - 1)))
                    since = now - _ts(st["last_end"]) if st["last_end"] else 1e9
                    if since < pause and not checks:
                        s = -1.0; reasons.append("paused %d s after %d turn(s) with nothing new (less volume)" % (pause, st["empty_streak"]))
                if a == last and len(active) > 1:
                    s -= w_rep; reasons.append("had the last turn (alternate)")
                scores[a], why[a] = round(s, 2), reasons
            best = max(sorted(scores), key=lambda a: scores[a])
            if best != app or scores[best] < 0:
                return None
            reason = "%s's turn: %s" % (DOMAIN_OF[app], "; ".join(why[app]))
            tid = db.execute("INSERT INTO engine_turns(started, app, domain, reason, scores) VALUES(?,?,?,?,?)",
                             (_now(), app, DOMAIN_OF[app], reason, json.dumps({"scores": scores, "why": why}))).lastrowid
        return {"id": tid, "app": app, "reason": reason, "scores": scores}

    def manual(self, app, reason="started by hand"):
        with self.store.write() as db:
            tid = db.execute("INSERT INTO engine_turns(started, app, domain, reason, scores) VALUES(?,?,?,?,?)",
                             (_now(), app, DOMAIN_OF[app], reason, "{}")).lastrowid
        return {"id": tid, "app": app, "reason": reason}

    def finish(self, turn, result):
        with self.store.write() as db:
            db.execute("UPDATE engine_turns SET ended = ?, result = ? WHERE id = ?", (_now(), json.dumps(result, default=str), turn["id"]))

    def status(self):
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        hb = self.store.query("SELECT * FROM app_heartbeat ORDER BY app")
        for h in hb:
            h["seconds_ago"] = round(now - h["at"], 1)
        turns = self.store.query("SELECT * FROM engine_turns ORDER BY id DESC LIMIT 30")
        for t in turns:
            t["result"] = json.loads(t["result"] or "null")
            t["scores"] = json.loads(t["scores"] or "{}")
        return {"version": ENGINE_VERSION, "heartbeats": hb, "turns": turns}


def _ts(s):
    if not s:
        return 0.0
    return datetime.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc).timestamp()


class Learner:
    """Reads the harvest record and recommends changes (never applies them)."""

    MIN_RUNS = 3

    def __init__(self, commons, registry, approvals):
        self.c, self.reg, self.ap, self.store = commons, registry, approvals, commons.store

    def review(self, app):
        made = 0
        rows = self.store.query("""SELECT action, budget_key, decision, items, new, merged, seconds, source_key, licence_class FROM harvest_log
                                   WHERE app = ? ORDER BY id DESC LIMIT 300""", (app,))
        by = {}
        for r in rows:
            by.setdefault(r["action"], []).append(r)
        with self.store.write() as db:
            for action, rs in by.items():
                done = [r for r in rs if r["decision"] == "harvested"][:5]
                failed = [r for r in rs[:5] if r["decision"] == "failed"]
                key = next((r["budget_key"] for r in done if r["budget_key"]), None)
                pkey = "budget.%s.%s" % (app, key) if key else None
                cur = self.reg.param(pkey) if pkey else None
                if len(done) >= self.MIN_RUNS and isinstance(cur, (int, float)) and cur > 0:
                    items = sum(r["items"] for r in done)
                    new = sum(r["new"] for r in done)
                    secs = sum(r["seconds"] or 0 for r in done) / len(done)
                    share = new / items if items else 0.0
                    if share >= 0.9 and secs <= 10.0 and cur < 100000:
                        val = int(round(cur * 1.5))
                        made += self.ap.recommend(db, app, "speed", "Harvest more per turn: %s %s → %s" % (pkey, cur, val),
                                                  "The last %d '%s' tasks were %d%% new facts and took %.1f s each on average: larger batches "
                                                  "would finish the same work in fewer turns." % (len(done), action, round(100 * share), secs),
                                                  {"runs": len(done), "new_share": round(share, 3), "mean_seconds": round(secs, 2)},
                                                  {"type": "param", "key": pkey, "value": val})
                    elif items and share <= 0.1 and cur > 10:
                        val = max(10, int(cur // 2))
                        made += self.ap.recommend(db, app, "volume", "Harvest less per turn: %s %s → %s" % (pkey, cur, val),
                                                  "The last %d '%s' tasks were only %d%% new (the rest duplicates): smaller batches "
                                                  "spend less time and storage on facts already held." % (len(done), action, round(100 * share)),
                                                  {"runs": len(done), "new_share": round(share, 3)}, {"type": "param", "key": pkey, "value": val})
                if len(failed) >= 3:
                    made += self.ap.recommend(db, app, "reliability", "Pause the failing task '%s'" % action,
                                              "%d of its last 5 runs failed; pausing it stops wasted turns until the cause is fixed." % len(failed),
                                              {"failures": len(failed)}, {"type": "param", "key": "disabled.%s.%s" % (app, action), "value": True})
            # sources blocked only because nobody has classified their licence yet
            for s in self.store.query("SELECT key, name FROM policy_sources WHERE status = 'pending' AND licence_class = 'unknown'"):
                demand = sum(1 for r in rows if r["source_key"] == s["key"] and r["decision"] == "blocked")
                if demand:
                    made += self.ap.recommend(db, app, "source", "Classify the licence of '%s'" % s["name"],
                                              "Harvest plans asked for this source %d time(s) but its licence is unknown, so it is blocked. "
                                              "Establish the licence; approve only if its class is unrestricted." % demand,
                                              {"blocked_requests": demand}, {"type": "review", "key": s["key"]})
            # checks waiting too long between applications → give them more weight in the rotation
            waits = db.execute("""SELECT avg(strftime('%s', substr(answered, 1, 19)) - strftime('%s', substr(created, 1, 19)))
                                  FROM (SELECT created, answered FROM requests WHERE status = 'answered' ORDER BY id DESC LIMIT 50)""").fetchone()[0]
            tick = float(self.reg.param("schedule.tick_s", 30))
            if waits and waits > 20 * tick:
                cw = float(self.reg.param("rotation.check_weight", 2.0))
                made += self.ap.recommend(db, None, "speed", "Answer cross-checks sooner: rotation.check_weight %s → %s" % (cw, cw + 1),
                                          "Checks waited %.0f s on average before being answered; a higher weight gives the answering "
                                          "application its turn sooner." % waits, {"mean_wait_s": round(waits, 1)},
                                          {"type": "param", "key": "rotation.check_weight", "value": cw + 1})
        return made
