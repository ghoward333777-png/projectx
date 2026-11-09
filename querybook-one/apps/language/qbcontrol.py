"""Global controls set from the QueryBook Control Panel and obeyed by all three applications.

The rules live in the shared database (Commons settings), so every application reads the same ones:

  * targeting — what harvesting concentrates on: topics (words), applications, online harvesters and sources.
    Targeted tasks run first and get a larger budget; with "only targeted" everything else waits.
  * filtering — what may enter the shared facts: words a fact must not / must contain, a year range, the domains
    and the licence classes allowed. A harvested fact that fails a filter is not saved (and is counted).

Plus the plumbing the Control Panel needs to manage the applications: each application records its address when
it starts, and stops when the panel asks with the panel's key (a random secret kept in the shared folder, so only a
program on this computer that can read the shared folder can stop an application).

Deterministic and local: plain rules, no model, no network.
"""
import json, os, re, secrets, threading

import qbcore as core

TARGET_KEY, FILTER_KEY = "control:target", "control:filter"
DOMAIN_NAMES = {"language": "language", "stem": "stem", "history": "history"}
APP_OF_DOMAIN = {"language": "language", "stem": "stem", "history": "facts"}
TARGET_DEFAULT = {"topics": [], "apps": [], "harvesters": [], "sources": [], "only": False, "boost": 2.0}
FILTER_DEFAULT = {"exclude_words": [], "require_words": [], "years": None, "domains": [], "licence_classes": []}
_YEAR = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)")


def _words(v):
    if isinstance(v, str):
        v = re.split(r"[,;\n]", v)
    out = []
    for w in v or []:
        w = " ".join(str(w).split()).strip().lower()
        if w and w not in out:
            out.append(w[:80])
    return out[:50]


def clean(kind, rules):
    """Validate and normalise a set of rules (raises UserError on nonsense)."""
    r = dict(TARGET_DEFAULT if kind == "target" else FILTER_DEFAULT)
    rules = rules or {}
    if kind == "target":
        r["topics"] = _words(rules.get("topics"))
        r["apps"] = [a for a in _words(rules.get("apps")) if a in ("language", "stem", "facts")]
        r["harvesters"] = _words(rules.get("harvesters"))
        r["sources"] = _words(rules.get("sources"))
        r["only"] = bool(rules.get("only"))
        try:
            r["boost"] = max(1.0, min(5.0, float(rules.get("boost", 2.0))))
        except (TypeError, ValueError):
            raise core.UserError("The budget boost must be a number from 1 to 5.")
        if r["only"] and not (r["topics"] or r["apps"] or r["harvesters"] or r["sources"]):
            raise core.UserError("\"Only targeted\" needs a target: give topics, applications, harvesters or sources.")
    elif kind == "filter":
        r["exclude_words"] = _words(rules.get("exclude_words"))
        r["require_words"] = _words(rules.get("require_words"))
        r["domains"] = [d for d in _words(rules.get("domains")) if d in DOMAIN_NAMES]
        r["licence_classes"] = _words(rules.get("licence_classes"))
        y = rules.get("years")
        if y:
            try:
                a, b = int(y[0]), int(y[1])
            except (TypeError, ValueError, IndexError):
                raise core.UserError("The year range needs two years, e.g. 1800 and 1950.")
            if a > b:
                a, b = b, a
            r["years"] = [a, b]
    else:
        raise core.UserError("Unknown rule kind (target or filter).")
    return r


def get(commons, kind):
    key = TARGET_KEY if kind == "target" else FILTER_KEY
    try:
        return clean(kind, json.loads(commons.setting(key) or "{}"))
    except (ValueError, core.UserError):
        return dict(TARGET_DEFAULT if kind == "target" else FILTER_DEFAULT)


def set_rules(commons, kind, rules, passphrase="", actor="control panel"):
    """Change the global rules. They change what all three applications harvest, so the admin passphrase is
    required once the admin has set one (as for every other harvesting policy)."""
    if commons.approvals.admin_set():
        commons.approvals._require(passphrase or "")
    r = clean(kind, rules)
    with commons.store.write() as db:
        commons.set_setting(TARGET_KEY if kind == "target" else FILTER_KEY, json.dumps(r, sort_keys=True), db)
        commons.agent_log(db, "control", "%s %s: %s" % (actor, "set the target" if kind == "target" else "set the filter", describe(kind, r)))
    return r


def active(kind, r):
    if kind == "target":
        return bool(r["topics"] or r["apps"] or r["harvesters"] or r["sources"])
    return bool(r["exclude_words"] or r["require_words"] or r["years"] or r["domains"] or r["licence_classes"])


def describe(kind, r):
    """The rules in one plain sentence."""
    if not active(kind, r):
        return "none (everything)"
    parts = []
    if kind == "target":
        if r["topics"]:
            parts.append("topics " + ", ".join(r["topics"]))
        if r["apps"]:
            parts.append("applications " + ", ".join(r["apps"]))
        if r["harvesters"]:
            parts.append("harvesters " + ", ".join(r["harvesters"]))
        if r["sources"]:
            parts.append("sources " + ", ".join(r["sources"]))
        parts.append(("only these" if r["only"] else "these first") + ", budget ×%g" % r["boost"])
    else:
        if r["exclude_words"]:
            parts.append("leave out facts mentioning " + ", ".join(r["exclude_words"]))
        if r["require_words"]:
            parts.append("keep only facts mentioning " + " or ".join(r["require_words"]))
        if r["years"]:
            parts.append("years %d–%d" % tuple(r["years"]))
        if r["domains"]:
            parts.append("domains " + ", ".join(r["domains"]))
        if r["licence_classes"]:
            parts.append("licence classes " + ", ".join(r["licence_classes"]))
    return "; ".join(parts)


def _text(item):
    return " ".join(str(item.get(k) or "") for k in ("subject", "predicate", "object", "statement")).lower()


def _has(text, word):
    return re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", text) is not None


# ----------------------------------------------------------------------------- targeting (the planner obeys it)
def task_targeted(task, r, app_id):
    """Does a planned task fall inside the target? (topics match its title / target / why)"""
    if not active("target", r):
        return False
    if r["apps"] and app_id in r["apps"]:
        return True
    act = task.get("action") or ""
    if r["harvesters"] and act.startswith("online:") and act.split(":", 1)[1].lower() in r["harvesters"]:
        return True
    if r["sources"] and (task.get("source") or "").lower() in r["sources"]:
        return True
    if r["topics"]:
        text = " ".join([task.get("title") or "", task.get("why") or "", json.dumps(task.get("target") or {}, ensure_ascii=False)]).lower()
        return any(_has(text, w) for w in r["topics"])
    return False


def order_tasks(tasks, r, app_id):
    """Targeted tasks first (marked, with the budget boost); with "only targeted" the others are skipped with the
    reason. Upkeep and cross-checks are never skipped by targeting (they keep the shared facts honest)."""
    if not active("target", r):
        return tasks
    hit, rest = [], []
    for t in tasks:
        (hit if task_targeted(t, r, app_id) else rest).append(t)
    for t in hit:
        t["_targeted"] = True
    if r["only"]:
        for t in rest:
            t["_skip"] = "outside the Control Panel's target (%s)" % describe("target", r)
    return hit + rest


def on_target(item, r):
    return bool(r["topics"]) and any(_has(_text(item), w) for w in r["topics"])


# ----------------------------------------------------------------------------- filtering (the curator obeys it)
def check_item(item, r, domain):
    """None when the fact may be saved, else the reason it may not."""
    if r["domains"] and domain not in r["domains"]:
        return "domain %s is filtered out" % domain
    text = _text(item)
    for w in r["exclude_words"]:
        if _has(text, w):
            return "mentions “%s”" % w
    if r["require_words"] and not any(_has(text, w) for w in r["require_words"]):
        return "mentions none of " + ", ".join(r["require_words"])
    if r["years"]:
        ys = [int(y) for y in _YEAR.findall(text)]
        if ys and not any(r["years"][0] <= y <= r["years"][1] for y in ys):
            return "its years (%s) are outside %d–%d" % (", ".join(str(y) for y in ys[:3]), r["years"][0], r["years"][1])
    if r["licence_classes"]:
        cls = {(e.get("licence_class") or "").lower() for e in item.get("evidence") or []} - {""}
        if cls and not cls & set(r["licence_classes"]):
            return "licence class %s is filtered out" % ", ".join(sorted(cls))
    return None


def apply_filter(items, r, domain):
    """(kept items, number dropped, a few example reasons)."""
    if not active("filter", r):
        return items, 0, []
    kept, why = [], []
    for it in items:
        reason = check_item(it, r, it.get("domain") or domain)
        if reason is None:
            kept.append(it)
        elif len(why) < 3:
            why.append("%s — %s" % (str(it.get("subject"))[:60], reason))
    return kept, len(items) - len(kept), why


def preview(commons, r, limit=2000):
    """Dry run of a filter over the most recent shared facts: how many would it have let in?"""
    r = clean("filter", r)
    rows = commons.store.query("SELECT f.id, f.domain, f.subject, f.predicate, f.object, f.statement FROM facts f ORDER BY f.id DESC LIMIT ?", (int(limit),))
    lic = {}
    if r["licence_classes"] and rows:
        ids = [x["id"] for x in rows]
        for j in range(0, len(ids), 500):
            part = ids[j:j + 500]
            for e in commons.store.query("SELECT e.fact_id, p.licence_class FROM evidence e LEFT JOIN policy_sources p ON p.key = e.source "
                                         "WHERE e.fact_id IN (%s)" % ",".join("?" * len(part)), part):
                lic.setdefault(e["fact_id"], []).append({"licence_class": e["licence_class"]})
    kept, dropped, ex = 0, {}, []
    for x in rows:
        reason = check_item(dict(x, evidence=lic.get(x["id"], [])), r, x["domain"])
        if reason is None:
            kept += 1
        else:
            dropped[x["domain"]] = dropped.get(x["domain"], 0) + 1
            if len(ex) < 8:
                ex.append({"subject": x["subject"], "predicate": x["predicate"], "object": str(x["object"])[:80], "why": reason})
    return {"checked": len(rows), "kept": kept, "dropped": sum(dropped.values()), "dropped_by_domain": dropped, "examples": ex,
            "rules": describe("filter", r)}


# ----------------------------------------------------------------------------- managing the applications
def token(folder):
    """The Control Panel's key, created once in the shared folder (readable by programs on this computer only)."""
    path = os.path.join(folder, "control.key")
    if not os.path.exists(path):
        os.makedirs(folder, exist_ok=True)
        with open(path, "w") as f:
            f.write(secrets.token_hex(24))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    with open(path) as f:
        return f.read().strip()


def register(commons, app_id, url, version):
    """An application records where it is running, so the Control Panel can find it."""
    commons.set_setting("url:%s" % app_id, json.dumps({"url": url, "version": version, "pid": os.getpid(), "at": core.now_iso()}))


def add_routes(api, commons, quit_fn):
    """What every application offers the Control Panel: its global rules, and a stop on the panel's key."""

    @api.get("/api/control/rules")
    def rules(p):
        t, f = get(commons, "target"), get(commons, "filter")
        return {"target": t, "filter": f, "target_text": describe("target", t), "filter_text": describe("filter", f)}

    @api.post("/api/control/quit")
    def quit_(p):
        if not secrets.compare_digest(str(p.get("key") or ""), token(commons.folder)):
            raise core.UserError("Only the Control Panel on this computer can stop the application.")
        threading.Timer(0.3, quit_fn).start()
        return {"stopping": True}
