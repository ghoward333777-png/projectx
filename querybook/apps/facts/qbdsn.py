"""qbdsn — Answer routing for the bulk fact lookup: Central, DSN, or Shadow.

  Central  every dataset store is asked in turn until enough facts are found (the way QueryBook has always looked up).
  DSN      the Digital Synaptic Network: only the stores whose learned pathways say they hold this kind of subject are
           asked, strongest first; stores that never answer for a kind weaken and stop being asked; when the strong
           pathways find nothing, every store is asked (nothing is ever lost to routing) and the pathways learn from it.
  Shadow   Central answers. The DSN answers the same lookup in the background and every difference is written to the
           Shadow comparison log, which the health report summarises — evidence before the DSN is trusted.

The stress test (querybook/sim) found the central pipeline faster and slightly more accurate on one machine; the DSN pays
off when the facts are spread over many stores or computers. So Central is the default, and Shadow is how to find out on
real data whether the DSN helps.

Learned pathways are saved in shards/_dsn.json: each one is auditable (strength, facts found, empty answers, last used).
When the DSN is switched back on after being off, every pathway is pulled halfway back to neutral, so routes learned on an
older set of stores are re-checked rather than trusted. Facts are never stored here: only routes.

Standard library only. Deterministic: the same lookups in the same order give the same routes.
"""
import json, os, re, threading, time

MODES = ("central", "shadow", "dsn")
MODE_TEXT = {"central": "Central — every store is asked (the default)",
             "shadow": "Shadow — Central answers; the DSN runs beside it and every difference is logged",
             "dsn": "DSN — only the stores the learned pathways point to are asked"}
SETTING = "answer:routing"
THETA, ETA, SILENCE, DRIFT, EXPLORE_EVERY = 0.30, 0.10, 0.15, 0.002, 25
MAX_KINDS = 2000
LOG_MAX = 5_000_000
VERDICT_MIN = 50

_LOCK = threading.RLock()
_QUEUE = []
_WORKER = {"t": None}


def _bulk():
    import qbbulk
    return qbbulk


def _folder(commons):
    return os.path.join(commons.folder, _bulk().FOLDER)


def routes_path(commons):
    return os.path.join(_folder(commons), "_dsn.json")


def log_path(commons):
    return os.path.join(_folder(commons), "_dsn-shadow.jsonl")


def mode(commons):
    m = (commons.setting(SETTING, "central") or "central").strip().lower()
    return m if m in MODES else "central"


def kind(text):
    """the kind of subject a lookup asks about: its first word, lower case, digits dropped ("PubChem CID 2244" -> "pubchem");
    a lookup that starts with a number is kind "#" """
    w = (text or "").strip().split()
    if not w:
        return ""
    k = re.sub(r"[^a-z]", "", w[0].lower())
    return k or "#"


# ------------------------------------------------------------------------------------------------ learned pathways
def _load(commons):
    try:
        with open(routes_path(commons), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("kinds"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"kinds": {}, "lookups": 0, "re_checked": None}


def _save(commons, d):
    os.makedirs(_folder(commons), exist_ok=True)
    if len(d["kinds"]) > MAX_KINDS:                     # forget the kinds used longest ago
        keep = sorted(d["kinds"].items(), key=lambda kv: -max([x.get("last", 0) for x in kv[1].values()] or [0]))[:MAX_KINDS]
        d["kinds"] = dict(keep)
    p = routes_path(commons)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, separators=(",", ":"))
    os.replace(tmp, p)


def set_mode(commons, new):
    new = (new or "").strip().lower()
    if new not in MODES:
        raise ValueError("Answer routing must be one of: Central, Shadow, DSN.")
    old = mode(commons)
    commons.set_setting(SETTING, new)
    note = ""
    if old == "central" and new != "central":           # back on: re-check what was learned, do not trust it blindly
        with _LOCK:
            d = _load(commons)
            n = 0
            for syns in d["kinds"].values():
                for s in syns.values():
                    s["s"] = round(s["s"] + (0.5 - s["s"]) / 2, 4)
                    n += 1
            d["re_checked"] = time.time()
            if n:
                _save(commons, d)
                note = " · %d learned pathway(s) pulled halfway back to neutral, to be re-checked as lookups come in" % n
    return {"mode": new, "summary": "Answer routing: %s%s" % (MODE_TEXT[new], note)}


def dsn_search(commons, text, limit=50, learn=True):
    """the DSN lookup: (facts, stores asked, stores held, fell back to every store)"""
    bk = _bulk()
    text = (text or "").strip()
    held = bk.stores(commons.folder)
    if not text:
        return [], 0, len(held), False
    k = kind(text)
    with _LOCK:
        d = _load(commons)
        syn = d["kinds"].setdefault(k, {})
        d["lookups"] = d.get("lookups", 0) + 1
        nth = sum(x.get("n", 0) for x in syn.values())
        for key, _ in held:
            s = syn.setdefault(key, {"s": 0.5, "hits": 0, "empty": 0, "last": 0, "n": 0})
            if s["s"] < 0.5:
                s["s"] += DRIFT * (0.5 - s["s"])          # weak pathways recover slowly: re-sensitisation
        ranked = sorted(held, key=lambda kd: (-syn[kd[0]]["s"], kd[0]))
        strong = [kd for kd in ranked if syn[kd[0]]["s"] >= THETA]
        weak = [kd for kd in ranked if syn[kd[0]]["s"] < THETA]
        if weak and nth and nth % EXPLORE_EVERY == 0:    # now and then one weak pathway is tried again
            strong.append(weak.pop(0))
        out, asked, fell_back = [], 0, False

        def ask(batch):
            nonlocal asked
            for key, ds in batch:
                if len(out) >= limit:
                    break
                asked += 1
                try:
                    got = bk.search_store(commons.folder, key, ds, text, limit - len(out))
                except Exception:
                    got = []
                s = syn[key]
                s["n"] += 1
                s["last"] = int(time.time())
                if learn:
                    if got:
                        s["s"] += ETA * (1 - s["s"]); s["hits"] += 1
                    else:
                        s["s"] -= SILENCE * s["s"]; s["empty"] += 1
                    s["s"] = round(s["s"], 4)
                out.extend(got)
        ask(strong)
        if not out and weak:                             # nothing on the strong pathways: ask everyone, and learn
            fell_back = True
            ask(weak)
        _save(commons, d)
    return out[:limit], asked, len(held), fell_back


def pathways(commons, top=8):
    """the learned pathways, auditable: per kind the stores it points to, strongest first"""
    d = _load(commons)
    rows = []
    for k, syns in d["kinds"].items():
        best = sorted(syns.items(), key=lambda kv: -kv[1]["s"])
        rows.append({"kind": k, "lookups": max([x.get("n", 0) for x in syns.values()] or [0]),
                     "strong": [{"store": key, "strength": round(x["s"], 3), "facts_found": x["hits"], "empty": x["empty"]}
                                for key, x in best if x["s"] >= THETA][:top],
                     "weak": sum(1 for x in syns.values() if x["s"] < THETA)})
    rows.sort(key=lambda r: -r["lookups"])
    return {"kinds": len(rows), "lookups": d.get("lookups", 0), "re_checked": d.get("re_checked"), "rows": rows[:50]}


# ------------------------------------------------------------------------------------------------ answering
def _keys(facts):
    return {(f["subject"], f["predicate"], f["object"], f["dataset"]) for f in facts}


def _log(commons, rec):
    p = log_path(commons)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if os.path.exists(p) and os.path.getsize(p) > LOG_MAX:
            os.replace(p, p + ".1")                      # one older file is kept
        with _LOCK, open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
    except OSError:
        pass


def compare(commons, text, limit, central, c_asked, c_ms, held):
    """run the DSN on the same lookup and log how it compares with Central's answer"""
    t = time.perf_counter()
    dfacts, d_asked, _, fell = dsn_search(commons, text, limit)
    d_ms = (time.perf_counter() - t) * 1000
    ck, dk = _keys(central), _keys(dfacts)
    complete = len(central) < limit                     # Central found everything there is
    if complete:
        missed, extra = len(ck - dk), len(dk - ck)
        agree = not missed and not extra
    else:                                               # both stop at the limit: compared by whether the DSN also filled it
        missed, extra = max(0, limit - len(dfacts)), 0
        agree = len(dfacts) >= limit
    rec = {"at": round(time.time(), 1), "mode": "shadow", "q": text[:120], "kind": kind(text), "limit": limit, "stores": held,
           "complete": complete, "agree": agree, "missed": missed, "extra": extra, "fell_back": fell,
           "central": {"n": len(central), "asked": c_asked, "ms": round(c_ms, 1)},
           "dsn": {"n": len(dfacts), "asked": d_asked, "ms": round(d_ms, 1)}}
    _log(commons, rec)
    return rec


def _worker(commons):
    while True:
        with _LOCK:
            if not _QUEUE:
                _WORKER["t"] = None
                return
            job = _QUEUE.pop(0)
        try:
            compare(commons, *job)
        except Exception:
            pass


def _shadow(commons, *job, wait=False):
    if wait:
        return compare(commons, *job)
    with _LOCK:
        if len(_QUEUE) >= 20:                           # never let the comparison pile up behind a busy page
            return None
        _QUEUE.append(job)
        if _WORKER["t"] is None:
            _WORKER["t"] = threading.Thread(target=_worker, args=(commons,), daemon=True, name="qb-dsn-shadow")
            _WORKER["t"].start()
    return None


def lookup(commons, text, limit=50, wait=False):
    """the bulk lookup, routed as the setting says. wait: run the Shadow comparison now (tests) instead of in the background"""
    bk = _bulk()
    m = mode(commons)
    text = (text or "").strip()
    t = time.perf_counter()
    if m == "dsn":
        facts, asked, held, fell = dsn_search(commons, text, limit)
        ms = (time.perf_counter() - t) * 1000
        if text and held:
            _log(commons, {"at": round(time.time(), 1), "mode": "dsn", "q": text[:120], "kind": kind(text), "stores": held,
                           "fell_back": fell, "dsn": {"n": len(facts), "asked": asked, "ms": round(ms, 1)}})
    else:
        facts, asked, held = bk.search_central(commons.folder, text, limit)
        ms = (time.perf_counter() - t) * 1000
        fell = False
        if m == "shadow" and text and held:            # nothing to compare before any store exists
            _shadow(commons, text, limit, [dict(f) for f in facts], asked, ms, held, wait=wait)
    facts = bk.label_wikidata(commons.folder, facts)[:limit]
    by = {"central": "Central", "shadow": "Central (DSN compared in Shadow)", "dsn": "DSN"}[m]
    return {"facts": facts, "routing": m, "answered_by": by, "stores_asked": asked, "stores": held, "fell_back": fell,
            "ms": round(ms, 1), "summary": "%s · asked %d of %d store(s)%s · %.0f ms" % (
                by, asked, held, " (strong pathways found nothing: every store asked)" if fell else "", ms)}


# ------------------------------------------------------------------------------------------------ the health report
def read_log(commons, since):
    out = []
    for p in (log_path(commons) + ".1", log_path(commons)):
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("at", 0) >= since:
                        out.append(r)
        except OSError:
            pass
    return out


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0


def shadow_summary(commons, hours=24):
    recs = read_log(commons, time.time() - hours * 3600)
    sh = [r for r in recs if r.get("mode") == "shadow"]
    ds = [r for r in recs if r.get("mode") == "dsn"]
    o = {"hours": hours, "shadow": len(sh), "dsn_answered": len(ds)}
    if sh:
        o.update(agreed=round(100.0 * sum(1 for r in sh if r["agree"]) / len(sh), 1),
                 missed_lookups=sum(1 for r in sh if r["missed"]), missed_facts=sum(r["missed"] for r in sh),
                 fell_back=sum(1 for r in sh if r.get("fell_back")),
                 central_asked=round(sum(r["central"]["asked"] for r in sh) / len(sh), 1),
                 dsn_asked=round(sum(r["dsn"]["asked"] for r in sh) / len(sh), 1),
                 central_ms=round(_median([r["central"]["ms"] for r in sh]), 1), dsn_ms=round(_median([r["dsn"]["ms"] for r in sh]), 1),
                 examples=[{"q": r["q"], "missed": r["missed"], "central": r["central"]["n"], "dsn": r["dsn"]["n"]}
                           for r in sh if r["missed"]][-5:])
        if len(sh) < VERDICT_MIN:
            o["verdict"] = "too few lookups yet (%d of %d) — keep Central" % (len(sh), VERDICT_MIN)
        elif o["missed_lookups"]:
            o["verdict"] = "the DSN missed facts in %d lookup(s) — keep Central" % o["missed_lookups"]
        elif o["dsn_ms"] < o["central_ms"]:
            o["verdict"] = "the DSN matched every answer and was faster — DSN is safe to try"
        else:
            o["verdict"] = "the DSN matched every answer but was not faster — no reason to switch yet"
    if ds:
        o.update(dsn_fell_back=sum(1 for r in ds if r.get("fell_back")), dsn_asked_alone=round(sum(r["dsn"]["asked"] for r in ds) / len(ds), 1),
                 dsn_ms_alone=round(_median([r["dsn"]["ms"] for r in ds]), 1))
    return o


def health_lines(commons, hours=24):
    m = mode(commons)
    L = ["Answer routing: %s" % {"central": "CENTRAL", "shadow": "SHADOW (Central answers, the DSN is compared)", "dsn": "DSN"}[m]]
    s = shadow_summary(commons, hours)
    if s["shadow"]:
        L.append("Shadow test (last %d h): %s lookups · the DSN agreed in %.1f%% · missed facts in %d · stores asked: DSN %.1f, Central %.1f · "
                 "time: DSN %.0f ms, Central %.0f ms" % (hours, format(s["shadow"], ","), s["agreed"], s["missed_lookups"], s["dsn_asked"],
                                                         s["central_asked"], s["dsn_ms"], s["central_ms"]))
        L.append("Shadow verdict: " + s["verdict"])
    elif m == "shadow":
        L.append("Shadow test: no lookups yet — use Look up bulk facts; every lookup is compared")
    if s["dsn_answered"]:
        L.append("DSN answered (last %d h): %s lookups · %.1f store(s) asked on average · every store asked in %d (strong pathways found nothing)"
                 % (hours, format(s["dsn_answered"], ","), s["dsn_asked_alone"], s["dsn_fell_back"]))
    return L


# ------------------------------------------------------------------------------------------------ self-test
def self_test():
    import shutil, tempfile, sqlite3
    import qbbulk as bk
    out = []

    def ok(name, cond, detail=""):
        out.append(bool(cond))
        print(("ok   " if cond else "FAIL ") + name + ("" if cond else "  " + str(detail)[:400]))

    class FakeCommons:
        def __init__(self, folder):
            self.folder, self.s = folder, {}

        def setting(self, k, d=None):
            return self.s.get(k, d)

        def set_setting(self, k, v, db=None):
            self.s[k] = str(v)

    class DS:
        def __init__(self, key):
            self.key, self.title, self.source, self.licence = key, "Store " + key, "test", "CC0"

        def link(self, s):
            return None

    tmp = tempfile.mkdtemp()
    saved = (bk.catalog, bk.wd_labels)
    try:
        c = FakeCommons(tmp)
        prefixes = {"a": "Alpha", "b": "Beta", "c": "Gamma", "d": "Delta", "e": "Epsilon", "f": "Zeta"}
        dss = {k: DS(k) for k in prefixes}
        bk.catalog = lambda: dss
        bk.wd_labels = lambda folder, qs: {}
        for k, pre in prefixes.items():
            p = bk.shard_path(tmp, k)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            db = sqlite3.connect(p)
            db.executescript("CREATE TABLE facts(s TEXT, p INTEGER, o TEXT, part INTEGER, row INTEGER); CREATE INDEX fs ON facts(s);"
                             "CREATE TABLE predicates(id INTEGER PRIMARY KEY, name TEXT); CREATE TABLE parts(id INTEGER PRIMARY KEY, name TEXT);"
                             "INSERT INTO predicates VALUES(1, 'value'); INSERT INTO parts VALUES(1, 'part1');")
            db.executemany("INSERT INTO facts VALUES(?, 1, ?, 1, ?)", [("%s %d" % (pre, i), "v%d" % i, i) for i in range(200)])
            if k == "a":                                 # one store also holds a few Gamma subjects
                db.executemany("INSERT INTO facts VALUES(?, 1, ?, 1, ?)", [("Gamma extra %d" % i, "x", 900 + i) for i in range(3)])
            db.commit(); db.close()
        ok("the default routing is Central", mode(c) == "central")
        r = lookup(c, "Gamma 1", 50)
        ok("Central asks the stores in turn until it has enough", r["routing"] == "central" and len(r["facts"]) == 50 and r["stores_asked"] == 3, r["summary"])
        r = lookup(c, "Zeta 7", 50)
        ok("Central asks every store when the facts are in the last one", r["stores_asked"] == 6 and len(r["facts"]) == 11, r["summary"])
        ok("a wrong routing value is refused", _raises(lambda: set_mode(c, "sideways")))
        set_mode(c, "shadow")
        for i in range(60):
            lookup(c, "Gamma %d" % (i % 20), 50, wait=True)
        for i in range(60):
            lookup(c, "Delta %d" % (i % 20), 50, wait=True)
        s = shadow_summary(c)
        ok("Shadow: Central answers and every lookup is compared in the log", s["shadow"] == 120 and s["agreed"] == 100.0, s)
        ok("Shadow: the DSN learns to ask fewer stores than Central", s["dsn_asked"] < s["central_asked"], s)
        ok("Shadow: the verdict needs enough lookups and says what to do", "DSN" in s["verdict"] or "Central" in s["verdict"], s)
        hl = health_lines(c)
        ok("the health report carries the routing and the Shadow comparison", hl[0].startswith("Answer routing: SHADOW") and "Shadow test" in hl[1]
           and "Shadow verdict" in hl[2], hl)
        r = lookup(c, "Gamma extra", 50, wait=True)
        ok("Shadow: a lookup whose facts sit in an unexpected store is still answered fully (strong pathways empty -> every store)",
           len(r["facts"]) == 3, r)
        set_mode(c, "dsn")
        r = lookup(c, "Delta 7", 50)
        ok("DSN: answers from the learned pathways, asking fewer stores", r["routing"] == "dsn" and r["facts"] and r["stores_asked"] < 6, r["summary"])
        r = lookup(c, "Epsilon 3", 50)
        ok("DSN: a new kind of lookup still finds its facts (neutral pathways ask every store first)", r["facts"], r)
        pw = pathways(c)
        g = next(x for x in pw["rows"] if x["kind"] == "gamma")
        ok("every learned pathway is auditable: strength, facts found, empty answers", g["strong"] and "facts_found" in g["strong"][0] and g["weak"] >= 3, g)
        set_mode(c, "central")
        r = set_mode(c, "dsn")
        ok("switching the DSN back on re-checks what it learned (pathways pulled toward neutral)", "re-checked" in r["summary"], r)
        hl = health_lines(c)
        ok("the health report counts the lookups the DSN answered", any(x.startswith("DSN answered") for x in hl), hl)
        ok("kinds: first word, lower case, digits dropped", kind("PubChem CID 2244") == "pubchem" and kind("2030 events") == "#" and kind("") == "")
    finally:
        bk.catalog, bk.wd_labels = saved
        shutil.rmtree(tmp, ignore_errors=True)
    print("%d of %d checks passed" % (sum(out), len(out)))
    return all(out)


def _raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


if __name__ == "__main__":
    import sys
    sys.exit(0 if self_test() else 1)
