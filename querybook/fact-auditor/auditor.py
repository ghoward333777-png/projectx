#!/usr/bin/env python3
"""QueryBook Fact Auditor — a stand-alone legitimacy, accuracy and citation audit of every harvested fact.

A separate program: it shares no code with the QueryBook applications and never writes to their data. It opens the
shared fact folder READ-ONLY (SQLite "mode=ro"), shows every fact, and for each one shows

  * the Fact Unit       — the stored record: fingerprint, subject / predicate / object, domain, status, confidence;
  * the UFCS fact packet — the same fact as a UFCS 1.0 packet (nucleus, polarity, semantic fingerprint, FUID, sources,
                           certification, temporal, safety, provenance);
  * the associated packets — one UFCS packet per piece of evidence (each source, each recomputation, each cross-check
                           between applications) and, for bulk facts, the dataset record it was read from;
  * the audit           — legitimacy (approved source, unrestricted licence, recorded harvest, no third-party wording,
                           intact harvest log), accuracy (fingerprint recomputes, well-formed values, evidence verdicts,
                           status earned, conflicting values, lifespans, coordinates) and citation (a source for every
                           claim, a well-formed link, a link to the exact record). Online, on request: every citation
                           link is fetched, and Wikidata facts are re-read from Wikidata and compared value by value.

Fact stores it reads (any that exist in the chosen folder):
  commons.sqlite          the shared facts of Language, Math/Science/Engineering and History & News, with evidence,
                          reasoning, cross-checks and the hash-chained harvest log
  shards/*.sqlite         the bulk harvest (Wikidata dump lanes, PubChem, NCBI Taxonomy, NOAA, GNIS, USDA, Tatoeba, ...)
  manifest.json + blocks/ a UFCS store of JSON packets (block_*.jsonl.gz)

Standard library only. Run:  python auditor.py   (then open http://127.0.0.1:8300)
    python auditor.py --data <folder>          use this fact folder
    python auditor.py audit --data <folder> [--full] [--sample N] [--online N] [--out report.json]
    python auditor.py self-test
"""
import csv, datetime, glob, gzip, hashlib, html, io, json, os, re, sqlite3, sys, threading, time, urllib.error, urllib.parse
import urllib.request, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.0.0"
PORT = 8300
HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(HERE, "auditor-settings.json")
REPORTS = os.path.join(HERE, "reports")
UA = "QueryBook-Fact-Auditor/%s (read-only audit; https://www.wikidata.org/wiki/Wikidata:Data_access)" % VERSION

# ------------------------------------------------------------------------------------------------ reference tables
# licence classes with no condition on the reuser (any other class is a legitimacy failure unless the admin accepted it)
UNRESTRICTED = {"public-domain", "cc0", "facts", "us-federal", "computed", "user-facts"}
TEXT_FREE = {"public-domain", "cc0", "us-federal", "computed"}       # classes whose own wording may be stored
STATUS_CONFIDENCE = {"verified": 1.0, "corroborated": 0.9, "sourced": 0.75, "reported": 0.4, "unsourced": 0.2,
                     "disputed": 0.3, "rejected": 0.0}
SOURCE_METHODS = ("reference", "source", "learned")                  # a named outside source
AREA_OF_APP = {"language": "language", "stem": "stem", "facts": "history"}

# the bulk datasets: shard key → (title, area, registry source key or None for computed, licence, record-link rule)
DATASETS = {
    "pubchem-computed": ("PubChem — NCBI-computed compound properties", "stem", "pubchem-computed",
                         "US government work (NLM); NCBI-computed properties only", "pubchem"),
    "ncbi-taxonomy": ("NCBI Taxonomy — every named organism", "stem", "ncbi-taxonomy", "US government work (NCBI)", None),
    "noaa-ghcn-daily": ("NOAA GHCN-Daily — weather station observations", "stem", "noaa", "Public domain (NOAA)", "noaa"),
    "usgs-gnis": ("USGS GNIS — official US place and feature names", "history", "usgs-gnis", "Public domain (USGS)", "gnis"),
    "usda-fooddata-central": ("USDA FoodData Central — foods and their nutrients", "stem", "usda-fooddata-central",
                              "CC0 1.0 (USDA)", "usda"),
    "tatoeba-cc0": ("Tatoeba — example sentences marked CC0", "language", "tatoeba-cc0", "CC0 1.0 (sentences marked CC0)", "tatoeba"),
    "calendar-scaffold": ("Calendar scaffold — computed dates, holidays, seasons, election days", "history", None,
                          "QueryBook's own computation from published rules", None),
    "wikidata-series": ("Recurring events — slots filled from Wikidata", "history", "wikidata", "CC0 1.0 (Wikidata)", "wikidata"),
    "mit-ocw": ("MIT OpenCourseWare — the course catalog", "stem", "mit-ocw-catalog", "Facts only (course catalog)", None),
}
for _lane in range(1, 65):
    DATASETS["wikidata-dump-%d" % _lane] = ("Wikidata — the full dump, lane %d" % _lane, "history", "wikidata", "CC0 1.0 (Wikidata)", "wikidata")

# values that a thing has only one of: two different values for one subject is a conflict worth a look
SINGLE_VALUED = {"date of birth", "date of death", "place of birth", "place of death", "atomic number", "chemical symbol"}
DATE_PREDICATES = {"date of birth", "date of death", "inception", "dissolved", "point in time", "publication date",
                   "date of first performance", "start time", "end time", "launch date", "born", "died"}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september",
                                       "october", "november", "december"], 1)}
QID_END = re.compile(r"\((Q\d+)\)\s*$")
QID_ONLY = re.compile(r"^Q(\d+)$")


def norm(s):
    return " ".join(str(s or "").strip().lower().split())


def qb_fingerprint(*parts):
    """QueryBook's content address: SHA-256 over the normalised parts joined by '|'."""
    return hashlib.sha256("|".join(norm(p) for p in parts).encode("utf-8")).hexdigest()


def ufcs_fingerprint(s, p, o, polarity="+"):
    """the UFCS semantic fingerprint (as in the UFCS reference engine): normalised nucleus and polarity"""
    return hashlib.sha256("|".join([norm(s), norm(p), norm(o), polarity]).encode("utf-8")).hexdigest()


def ufcs_fuid(s, p, o, polarity, source_id, ingested):
    content = json.dumps({"o": o, "p": p, "pol": polarity, "s": s}, sort_keys=True)
    return hashlib.sha256("|".join([content, str(source_id), str(ingested)]).encode("utf-8")).hexdigest()


def fact_status(evidence):
    """the status a fact earns from its evidence (an independent re-implementation of the published rule)"""
    sup = [e for e in evidence if e["verdict"] == "supports"]
    con = [e for e in evidence if e["verdict"] == "contradicts"]
    if con and sup:
        return "disputed"
    if con:
        return "rejected"
    if any(e["method"] == "recompute" for e in sup):
        return "verified"
    sources = {norm(e["source"]) for e in sup if e["method"] in ("reference", "source", "learned")}
    checkers = {e["app"] for e in sup if e["method"] == "cross-check"}
    if len(sources) >= 2 or (sources and checkers):
        return "corroborated"
    if sources:
        return "sourced"
    if any(e["method"] == "report" for e in sup):
        return "reported"
    return "unsourced"


def record_link(rule, subject):
    """a link to the exact record a bulk fact was read from"""
    if not rule:
        return None
    tail = subject.rsplit(" ", 1)[-1].strip("()")
    if rule == "wikidata":
        m = QID_END.search(subject)
        return "https://www.wikidata.org/wiki/" + m.group(1) if m else None
    if rule == "pubchem":
        return "https://pubchem.ncbi.nlm.nih.gov/compound/" + tail
    if rule == "noaa":
        bits = subject.split()
        return "https://www.ncei.noaa.gov/cdo-web/datasets/GHCND/stations/GHCND:%s/detail" % bits[2] if len(bits) > 2 else None
    if rule == "gnis":
        return "https://edits.nationalmap.gov/apps/gaz-domestic/public/summary/" + tail
    if rule == "usda":
        return "https://fdc.nal.usda.gov/food-details/%s/nutrients" % tail
    if rule == "tatoeba":
        return "https://tatoeba.org/en/sentences/show/" + tail
    return None


def url_ok(u):
    try:
        p = urllib.parse.urlparse(u or "")
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc) and "." in p.netloc


def parse_date(text):
    """(year, month, day) from the date forms the stores use, else None. Month/day may be None (year precision)."""
    t = str(text or "").strip()
    m = re.match(r"^([+-]?\d{1,6})(?:-(\d{2})(?:-(\d{2}))?)?(?:T.*)?$", t)
    if m:
        y, mo, d = int(m.group(1)), m.group(2) and int(m.group(2)), m.group(3) and int(m.group(3))
    else:
        m = re.match(r"^(\d{1,2}) ([A-Za-z]+),? (-?\d{1,6})$", t) or None
        if m and m.group(2).lower() in MONTHS:
            y, mo, d = int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))
        else:
            m = re.match(r"^([A-Za-z]+) (\d{1,2}),? (-?\d{1,6})$", t)
            if m and m.group(1).lower() in MONTHS:
                y, mo, d = int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))
            else:
                return None
    if mo in (0, None):
        mo = None
    if d in (0, None):
        d = None
    if mo is not None and not 1 <= mo <= 12:
        return None
    if d is not None:
        if mo is None:
            return None
        try:
            datetime.date(max(1, min(y, 9999)), mo, d)
        except ValueError:
            return None
    return (y, mo, d)


# ------------------------------------------------------------------------------------------------ opening the stores
def ro(path):
    """open an SQLite file read-only; the auditor never writes to QueryBook's data"""
    uri = "file:" + urllib.request.pathname2url(os.path.abspath(path)) + "?mode=ro"
    try:
        db = sqlite3.connect(uri, uri=True, timeout=30, check_same_thread=False)
        db.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
    except sqlite3.Error:
        db = sqlite3.connect(uri.replace("mode=ro", "mode=ro&immutable=1"), uri=True, timeout=30, check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db


def candidate_folders():
    """where QueryBook keeps its shared facts on this computer (first match wins in the UI)"""
    out = []
    env = os.environ.get("QB_COMMONS_DATA")
    if env:
        out.append(env)
    home = os.path.expanduser("~")
    base = os.path.join(home, "QueryBook-Data")
    for cj in glob.glob(os.path.join(base, "*", "commons.json")):
        try:
            with open(cj, encoding="utf-8") as f:
                p = json.load(f).get("folder")
            if p:
                out.append(p)
        except (OSError, ValueError):
            pass
    out.append(os.path.join(base, "commons"))
    seen, res = set(), []
    for p in out:
        a = os.path.abspath(os.path.expanduser(p))
        if a not in seen and looks_like_store(a):
            seen.add(a)
            res.append(a)
    return res


def looks_like_store(folder):
    return os.path.isfile(os.path.join(folder, "commons.sqlite")) or bool(glob.glob(os.path.join(folder, "shards", "*.sqlite"))) \
        or os.path.isfile(os.path.join(folder, "manifest.json"))


class Data:
    """every fact store in one folder, read-only"""

    def __init__(self, folder):
        self.folder = os.path.abspath(os.path.expanduser(folder or ""))
        self.lock = threading.Lock()
        self.commons = None
        cp = os.path.join(self.folder, "commons.sqlite")
        if os.path.isfile(cp):
            self.commons = ro(cp)
        self.shards = {}
        for p in sorted(glob.glob(os.path.join(self.folder, "shards", "*.sqlite"))):
            key = os.path.basename(p)[:-len(".sqlite")]
            try:
                db = ro(p)
                db.execute("SELECT 1 FROM facts LIMIT 1").fetchone()
                self.shards[key] = db
            except sqlite3.Error:
                pass
        self.labels = []
        for p in sorted(glob.glob(os.path.join(self.folder, "shards", "*.sqlite.labels"))):
            try:
                self.labels.append(ro(p))
            except sqlite3.Error:
                pass
        self.ufcs = self.folder if os.path.isfile(os.path.join(self.folder, "manifest.json")) and \
            os.path.isdir(os.path.join(self.folder, "blocks")) else None
        self.props = {}
        try:
            with open(os.path.join(self.folder, "shards", "wikidata-properties.json"), encoding="utf-8") as f:
                for pid, (_kind, name) in (json.load(f).get("props") or {}).items():
                    self.props.setdefault(name, pid)
        except (OSError, ValueError, TypeError):
            pass
        self._registry = None
        self._chain = None
        self._has_hid = False
        if self.commons is not None:
            cols = {r[1] for r in self.commons.execute("PRAGMA table_info(evidence)")}
            self._has_hid = "harvest_id" in cols

    # -- what is here
    def stores(self):
        out = []
        if self.commons is not None:
            n = self.commons.execute("SELECT count(*) FROM facts").fetchone()[0]
            out.append({"id": "commons", "title": "Shared facts (Language, STEM, History & News)", "facts": n, "kind": "commons"})
        for key, db in self.shards.items():
            try:
                r = db.execute("SELECT value FROM meta WHERE key = 'facts'").fetchone()
                n = int(json.loads(r[0])) if r else db.execute("SELECT count(*) FROM facts").fetchone()[0]
            except (sqlite3.Error, ValueError, TypeError):
                n = 0
            ds = DATASETS.get(key)
            out.append({"id": "b:" + key, "title": ds[0] if ds else key, "facts": n, "kind": "bulk"})
        if self.ufcs:
            try:
                with open(os.path.join(self.ufcs, "manifest.json"), encoding="utf-8") as f:
                    m = json.load(f)
                n = int(m.get("facts") or m.get("total_facts") or 0)
            except (OSError, ValueError, TypeError):
                n = 0
            out.append({"id": "ufcs", "title": "UFCS packet store (blocks)", "facts": n, "kind": "ufcs"})
        return out

    def registry(self):
        if self._registry is None:
            reg = {}
            if self.commons is not None:
                try:
                    for r in self.commons.execute("SELECT * FROM policy_sources"):
                        reg[r["key"]] = dict(r)
                except sqlite3.Error:
                    pass
            self._registry = reg
        return self._registry

    def chain(self):
        """the harvest log's hash chain, checked once per opening (it only grows)"""
        if self._chain is None:
            res = {"ok": True, "entries": 0, "present": False}
            if self.commons is not None:
                try:
                    prev, n = "0" * 64, 0
                    for r in self.commons.execute("SELECT * FROM harvest_log ORDER BY id"):
                        row = {k: r[k] for k in ("at", "app", "domain", "action", "title", "source_key", "licence_class", "decision",
                                                 "items", "new", "merged", "seconds", "reason", "budget_key", "turn_id", "policy_version")}
                        h = hashlib.sha256((prev + json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)).encode("utf-8")).hexdigest()
                        if r["prev_hash"] != prev or h != r["hash"]:
                            res = {"ok": False, "entries": n, "broken_at": r["id"], "present": True}
                            break
                        prev, n = r["hash"], n + 1
                    else:
                        res = {"ok": True, "entries": n, "last_hash": prev, "present": n > 0}
                except sqlite3.Error as e:
                    res = {"ok": False, "entries": 0, "error": str(e), "present": False}
            self._chain = res
        return self._chain

    def qlabels(self, qids):
        want, out = sorted({int(q) for q in qids}), {}
        for db in self.labels:
            if not want:
                break
            for i in range(0, len(want), 500):
                chunk = want[i:i + 500]
                try:
                    out.update(db.execute("SELECT q, label FROM labels WHERE q IN (%s)" % ",".join("?" * len(chunk)), chunk).fetchall())
                except sqlite3.Error:
                    break
            want = [q for q in want if q not in out]
        return out

    # -- listing every fact
    def list(self, store="", q="", after="", limit=50, status=""):
        """one page of facts; `after` is the cursor the previous page returned"""
        limit = max(1, min(int(limit or 50), 500))
        stores = [s["id"] for s in self.stores()]
        if store:
            stores = [s for s in stores if s == store]
        start_store, start_key = "", ""
        if after:
            start_store, _, start_key = after.partition("|")
        rows = []
        started = not start_store
        for sid in stores:
            if not started:
                if sid != start_store:
                    continue
                started = True
                key = start_key
            else:
                key = ""
            got = self._page(sid, q, key, limit - len(rows), status)
            rows.extend(got)
            if len(rows) >= limit:
                last = rows[-1]
                return {"facts": rows, "next": "%s|%s" % (last["store"], last["_key"])}
        return {"facts": rows, "next": None}

    def _page(self, sid, q, key, n, status):
        out = []
        q = (q or "").strip()
        if sid == "commons":
            where, args = ["id > ?"], [int(key or 0)]
            if status:
                where.append("status = ?"); args.append(status)
            if re.fullmatch(r"[0-9a-f]{64}", q):
                where.append("fingerprint = ?"); args.append(q)
            elif q:                                     # anywhere in the subject or object (any case)
                where.append("(subject LIKE ? ESCAPE '!' OR object LIKE ? ESCAPE '!')")
                pat = "%" + q.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
                args += [pat, pat]
            for r in self.commons.execute("SELECT id, domain, subject, predicate, object, status, confidence FROM facts WHERE %s ORDER BY id LIMIT ?"
                                          % " AND ".join(where), args + [n]):
                out.append({"id": "c-%d" % r["id"], "store": sid, "_key": str(r["id"]), "domain": r["domain"], "subject": r["subject"],
                            "predicate": r["predicate"], "object": r["object"], "status": r["status"], "confidence": r["confidence"]})
        elif sid.startswith("b:"):
            if status and status != "sourced" and status != "computed":
                return out
            skey = sid[2:]
            db = self.shards[skey]
            ds = DATASETS.get(skey)
            st = "computed" if ds and ds[2] is None else "sourced"
            if status and status != st:
                return out
            where, args = ["f.fp > ?"], [bytes.fromhex(key) if key else b""]
            if re.fullmatch(r"[0-9a-f]{32}", q):
                where = ["f.fp = ?"]; args = [bytes.fromhex(q)]
            elif q:
                cap = q[:1].upper() + q[1:]
                where.append("(f.s >= ? AND f.s < ? OR f.s >= ? AND f.s < ?)")
                args += [q, q + "￿", cap, cap + "￿"]
            for r in db.execute("SELECT f.fp, f.s, pr.name AS p, f.o FROM facts f JOIN predicates pr ON pr.id = f.p WHERE %s "
                                "ORDER BY f.fp LIMIT ?" % " AND ".join(where), args + [n]):
                out.append({"id": "b-%s-%s" % (skey, r["fp"].hex()), "store": sid, "_key": r["fp"].hex(), "domain": ds[1] if ds else "",
                            "subject": r["s"], "predicate": r["p"], "object": r["o"], "status": st,
                            "confidence": 1.0 if st == "computed" else 0.75})
            self._label_objects(out)
        elif sid == "ufcs":
            skip_to = int(key or 0)
            i = 0
            for i, pk in self._ufcs_iter(skip_to):
                nu = pk.get("nucleus") or {}
                if q and not norm(nu.get("subject")).startswith(norm(q)):
                    continue
                out.append({"id": "u-%s" % pk.get("semantic_fingerprint"), "store": sid, "_key": str(i + 1), "domain": pk.get("domain", ""),
                            "subject": nu.get("subject"), "predicate": nu.get("predicate"), "object": nu.get("object"),
                            "status": "ufcs", "confidence": (pk.get("confidence") or {}).get("trust_score")})
                if len(out) >= n:
                    break
        return out

    def _label_objects(self, rows):
        qs = [int(m.group(1)) for r in rows for m in [QID_ONLY.match(r["object"] or "")] if m]
        if qs:
            lab = self.qlabels(qs)
            for r in rows:
                m = QID_ONLY.match(r["object"] or "")
                if m and int(m.group(1)) in lab:
                    r["object_label"] = "%s (Q%s)" % (lab[int(m.group(1))], m.group(1))

    def _ufcs_iter(self, skip=0):
        i = -1
        for p in sorted(glob.glob(os.path.join(self.ufcs, "blocks", "block_*.jsonl.gz"))):
            with gzip.open(p, "rt", encoding="utf-8") as f:
                for line in f:
                    i += 1
                    if i < skip:
                        continue
                    try:
                        yield i, json.loads(line)
                    except ValueError:
                        continue

    # -- one fact in full
    def fact(self, fid):
        kind, _, rest = fid.partition("-")
        if kind == "c" and self.commons is not None:
            return self._commons_fact(int(rest))
        if kind == "b":
            skey, _, fph = rest.rpartition("-")
            if skey in self.shards:
                return self._bulk_fact(skey, fph)
        if kind == "u" and self.ufcs:
            return self._ufcs_fact(rest)
        return None

    def _commons_fact(self, cid):
        db = self.commons
        r = db.execute("SELECT * FROM facts WHERE id = ?", (cid,)).fetchone()
        if not r:
            return None
        f = dict(r)
        ev = [dict(e) for e in db.execute("SELECT * FROM evidence WHERE fact_id = ? ORDER BY id", (cid,))]
        reasoning = [dict(x) for x in db.execute("SELECT app, agent, step, text, at FROM reasoning WHERE fact_id = ? ORDER BY app, agent, step", (cid,))]
        try:
            reqs = [dict(x) for x in db.execute("SELECT * FROM requests WHERE fact_id = ? ORDER BY id", (cid,))]
        except sqlite3.Error:
            reqs = []
        harvests = {}
        if self._has_hid:
            ids = sorted({e["harvest_id"] for e in ev if e.get("harvest_id")})
            for h in ids:
                x = db.execute("SELECT * FROM harvest_log WHERE id = ?", (h,)).fetchone()
                if x:
                    harvests[h] = dict(x)
        unit = {"id": "c-%d" % cid, "store": "commons", "store_title": "Shared facts (commons.sqlite)",
                "fingerprint": f["fingerprint"], "fingerprint_rule": "sha256(norm(domain) | norm(subject) | norm(predicate) | norm(object))",
                "domain": f["domain"], "subject": f["subject"], "predicate": f["predicate"], "object": f["object"],
                "statement": f.get("statement"), "polarity": "+", "status": f["status"], "confidence": f["confidence"],
                "origin": f["origin_app"], "created": f["created"], "updated": f["updated"],
                "location": "commons.sqlite → facts.id %d" % cid}
        related = [dict(x) for x in db.execute("SELECT id, predicate, object, status FROM facts WHERE subject = ? AND id <> ? ORDER BY id LIMIT 200",
                                                (f["subject"], cid))]
        for x in related:
            x["id"] = "c-%d" % x["id"]
        return {"unit": unit, "evidence": ev, "reasoning": reasoning, "requests": reqs, "harvests": harvests, "related": related}

    def _bulk_fact(self, skey, fph):
        db = self.shards[skey]
        r = db.execute("SELECT f.fp, f.s, pr.name AS p, pr.rule, f.o, f.row, pa.name AS part, pa.url, pa.version, pa.started, pa.finished "
                       "FROM facts f JOIN predicates pr ON pr.id = f.p JOIN parts pa ON pa.id = f.part WHERE f.fp = ?",
                       (bytes.fromhex(fph),)).fetchone()
        if not r:
            return None
        ds = DATASETS.get(skey)
        area = ds[1] if ds else ""
        link = None
        try:
            x = db.execute("SELECT url FROM links WHERE fp = ?", (r["fp"],)).fetchone()
            link = x[0] if x else None
        except sqlite3.Error:
            pass
        link = link or record_link(ds[4] if ds else None, r["s"])
        unit = {"id": "b-%s-%s" % (skey, fph), "store": "b:" + skey, "store_title": (ds[0] if ds else skey) + " (shards/%s.sqlite)" % skey,
                "fingerprint": fph, "fingerprint_rule": "first 16 bytes of sha256(norm(area) | norm(subject) | norm(predicate) | norm(object))",
                "domain": area, "subject": r["s"], "predicate": r["p"], "object": r["o"], "statement": None, "polarity": "+",
                "status": "computed" if ds and ds[2] is None else "sourced", "confidence": 1.0 if ds and ds[2] is None else 0.75,
                "origin": "bulk: " + skey, "created": r["started"], "updated": r["finished"] or r["started"],
                "location": "shards/%s.sqlite → %s, row %d" % (skey, r["part"], r["row"] + 1)}
        m = QID_ONLY.match(r["o"] or "")
        if m:
            lab = self.qlabels([int(m.group(1))])
            if int(m.group(1)) in lab:
                unit["object_label"] = "%s (Q%s)" % (lab[int(m.group(1))], m.group(1))
        dataset = {"key": skey, "title": ds[0] if ds else skey, "source_key": ds[2] if ds else None, "licence": ds[3] if ds else None,
                   "part": r["part"], "part_url": r["url"], "edition": r["version"], "row": r["row"] + 1, "record_link": link,
                   "rule": r["rule"]}
        related = []
        for x in db.execute("SELECT f.fp, pr.name AS p, f.o FROM facts f JOIN predicates pr ON pr.id = f.p WHERE f.s = ? AND f.fp <> ? LIMIT 300",
                            (r["s"], r["fp"])):
            related.append({"id": "b-%s-%s" % (skey, x["fp"].hex()), "predicate": x["p"], "object": x["o"], "status": unit["status"]})
        self._label_objects(related)
        return {"unit": unit, "dataset": dataset, "related": related, "evidence": [], "reasoning": [], "requests": [], "harvests": {}}

    def _ufcs_fact(self, sfp):
        for _i, pk in self._ufcs_iter(0):
            if pk.get("semantic_fingerprint") == sfp:
                nu = pk.get("nucleus") or {}
                unit = {"id": "u-" + sfp, "store": "ufcs", "store_title": "UFCS packet store", "fingerprint": sfp,
                        "fingerprint_rule": "sha256(norm(subject) | norm(predicate) | norm(object) | polarity)", "domain": pk.get("domain"),
                        "subject": nu.get("subject"), "predicate": nu.get("predicate"), "object": nu.get("object"),
                        "polarity": pk.get("polarity", "+"), "status": "ufcs", "confidence": (pk.get("confidence") or {}).get("trust_score"),
                        "origin": "UFCS store", "created": (pk.get("temporal") or {}).get("ingested"), "updated": None,
                        "location": "blocks/*.jsonl.gz"}
                return {"unit": unit, "stored_packet": pk, "related": [], "evidence": [], "reasoning": [], "requests": [], "harvests": {}}
        return None


# ------------------------------------------------------------------------------------------------ UFCS packets
def _packet(unit, sources, certification, ingested, fact_type="assertion", extra=None):
    s, p, o, pol = unit["subject"], unit["predicate"], unit["object"], unit.get("polarity", "+")
    src_id = sources[0]["id"] if sources else "SRC-UNKNOWN"
    pk = {"ufcs_version": "1.0", "fuid": ufcs_fuid(s, p, o, pol, src_id, ingested or ""), "fact_type": fact_type,
          "domain": unit.get("domain") or "general", "nucleus": {"subject": s, "predicate": p, "object": o}, "polarity": pol,
          "semantic_fingerprint": ufcs_fingerprint(s, p, o, pol), "confidence": {"trust_score": certification.get("trust_score")},
          "sources": sources, "certification": certification, "temporal": {"ingested": ingested},
          "safety": {"classification": "PUBLIC", "acl": ["reader"]}}
    if extra:
        pk.update(extra)
    return pk


def packets(full, data):
    """(the UFCS fact packet, [associated packets]) for one fact — deterministic: the same fact gives the same packets"""
    u = full["unit"]
    reg = data.registry()
    prov = {"store": u["store_title"], "location": u["location"], "querybook_fingerprint": u["fingerprint"],
            "fingerprint_rule": u["fingerprint_rule"]}
    assoc = []
    if u["store"] == "ufcs":
        pk = dict(full["stored_packet"])
        pk.setdefault("provenance", prov)
        return pk, assoc
    if u["store"] == "commons":
        srcs, seen = [], set()
        for e in full["evidence"]:
            h = full["harvests"].get(e.get("harvest_id")) if e.get("harvest_id") else None
            skey = (h or {}).get("source_key")
            cls = (h or {}).get("licence_class") or (reg.get(skey) or {}).get("licence_class")
            sid = skey or "%s:%s" % (e["app"], norm(e["source"])[:60])
            src = {"id": sid, "name": e["source"], "class": e["method"], "licence": e.get("licence"), "licence_class": cls,
                   "url": e.get("url") or (reg.get(skey) or {}).get("url"), "app": e["app"]}
            if sid not in seen and e["verdict"] == "supports" and e["method"] in SOURCE_METHODS + ("report", "recompute"):
                seen.add(sid)
                srcs.append(src)
            kind = "attestation" if e["method"] in SOURCE_METHODS + ("report",) else \
                "recomputation" if e["method"] == "recompute" else "cross_check" if e["method"] == "cross-check" else "consistency_check"
            trust = 1.0 if e["verdict"] == "supports" and e["method"] == "recompute" else \
                0.75 if e["verdict"] == "supports" else 0.0 if e["verdict"] == "contradicts" else None
            assoc.append(_packet(u, [src], {"authority_class": e["method"], "trust_score": trust, "verdict": e["verdict"],
                                            "checked_by": "%s / %s" % (e["app"], e["agent"])}, e["at"], kind,
                                 {"evidence": {"method": e["method"], "verdict": e["verdict"], "detail": e.get("detail"),
                                               "quote": e.get("quote"), "harvest": ({"id": h["id"], "at": h["at"], "action": h["action"],
                                                                                     "title": h["title"], "decision": h["decision"],
                                                                                     "hash": h["hash"]} if h else None)}}))
        for rq in full["requests"]:
            try:
                payload = json.loads(rq["payload"] or "{}")
            except ValueError:
                payload = rq["payload"]
            assoc.append(_packet(u, [{"id": "app:" + rq["to_app"], "name": "QueryBook %s application" % rq["to_app"], "class": "cross-check"}],
                                 {"authority_class": "cross-check", "trust_score": None, "verdict": rq.get("verdict") or "open",
                                  "checked_by": rq["to_app"]}, rq.get("answered") or rq["created"], "check_request",
                                 {"request": {"kind": rq["kind"], "payload": payload, "from": rq["from_app"], "to": rq["to_app"],
                                              "status": rq["status"], "detail": rq.get("detail")}}))
        best = max((c for c in (s.get("licence_class") for s in srcs) if c), key=lambda c: c in UNRESTRICTED, default=None)
        main = _packet(u, srcs, {"authority_class": u["status"], "trust_score": u["confidence"], "licence_class": best,
                                 "evidence_count": len(full["evidence"])}, u["created"], "assertion",
                       {"statement": u.get("statement"), "provenance": prov})
        return main, assoc
    ds = full["dataset"]
    rs = reg.get(ds["source_key"]) if ds["source_key"] else None
    src = {"id": ds["source_key"] or "computed:" + ds["key"], "name": ds["title"], "class": "computed" if not ds["source_key"] else "dataset",
           "licence": ds["licence"], "licence_class": (rs or {}).get("licence_class") or ("computed" if not ds["source_key"] else None),
           "url": ds["record_link"] or ds["part_url"]}
    main = _packet(u, [src], {"authority_class": u["status"], "trust_score": u["confidence"], "licence_class": src["licence_class"]},
                   u["created"], "assertion", {"provenance": prov})
    assoc.append(_packet(u, [dict(src, url=ds["part_url"])], {"authority_class": "dataset_record", "trust_score": u["confidence"],
                                                               "verdict": "supports", "checked_by": "bulk reader (fixed rule)"},
                         u["created"], "source_record",
                         {"record": {"dataset": ds["key"], "part": ds["part"], "row": ds["row"], "edition": ds["edition"],
                                     "download": ds["part_url"], "record_link": ds["record_link"], "rule": ds["rule"]}}))
    return main, assoc


# ------------------------------------------------------------------------------------------------ the audit
def _chk(group, cid, name, result, detail):
    return {"group": group, "id": cid, "name": name, "result": result, "detail": detail}


def audit(full, data):
    """every offline check for one fact: [{group, id, name, result: pass|warn|fail|info, detail}] and the overall verdict"""
    u = full["unit"]
    reg = data.registry()
    out = []
    bulk = u["store"].startswith("b:")
    ufcs = u["store"] == "ufcs"
    # ---------------- legitimacy
    if ufcs:
        pk = full["stored_packet"]
        srcs = pk.get("sources") or []
        out.append(_chk("Legitimacy", "L1", "Named source", "pass" if srcs else "fail",
                        ", ".join("%s (%s)" % (s.get("name"), s.get("class")) for s in srcs) or "the packet names no source"))
    elif bulk:
        ds = full["dataset"]
        if ds["source_key"] is None:
            out.append(_chk("Legitimacy", "L1", "Approved source", "pass", "computed by QueryBook from published rules: %s" % ds["licence"]))
            out.append(_chk("Legitimacy", "L2", "Unrestricted licence", "pass", "computed"))
        else:
            rs = reg.get(ds["source_key"])
            if rs is None:
                out.append(_chk("Legitimacy", "L1", "Approved source", "warn" if not reg else "fail",
                                "'%s' is not in the policy registry%s" % (ds["source_key"], " (no registry in this folder)" if not reg else "")))
            else:
                out.append(_chk("Legitimacy", "L1", "Approved source", "pass" if rs["status"] == "approved" else "fail",
                                "%s — %s%s" % (rs["name"], rs["status"], (" by %s on %s" % (rs.get("decided_by"), rs.get("decided_at"))) if rs.get("decided_at") else "")))
            cls = (rs or {}).get("licence_class")
            out.append(_chk("Legitimacy", "L2", "Unrestricted licence", "pass" if cls in UNRESTRICTED else "fail" if cls else "warn",
                            "%s (%s)" % (ds["licence"], cls or "class unknown")))
        out.append(_chk("Legitimacy", "L3", "Harvest recorded", "pass" if ds["part"] else "fail",
                        "%s, row %d (edition %s)" % (ds["part"], ds["row"], ds["edition"] or "?")))
        out.append(_chk("Legitimacy", "L4", "No third-party wording", "pass", "bulk facts keep the values only"))
    else:
        ev = full["evidence"]
        srcs = [e for e in ev if e["method"] in SOURCE_METHODS + ("report",)]
        bad, notes, classes = [], [], set()
        for e in srcs:
            h = full["harvests"].get(e.get("harvest_id")) if e.get("harvest_id") else None
            skey = (h or {}).get("source_key")
            rs = reg.get(skey) if skey else None
            cls = (h or {}).get("licence_class") or (rs or {}).get("licence_class")
            classes.add(cls)
            if rs is not None and rs["status"] != "approved":
                bad.append("%s is %s in the registry" % (rs["name"], rs["status"]))
            elif rs is None and skey:
                bad.append("'%s' is not in the registry" % skey)
            notes.append("%s%s" % (e["source"], " → %s (%s)" % (skey, rs["status"]) if rs else ""))
        computed = any(e["method"] == "recompute" for e in ev)
        if not srcs and not computed:
            out.append(_chk("Legitimacy", "L1", "Approved source", "warn", "no outside source and no recomputation is recorded"))
        else:
            out.append(_chk("Legitimacy", "L1", "Approved source", "fail" if bad else "pass",
                            "; ".join(bad) if bad else "; ".join(notes) or "computed here"))
        known = {c for c in classes if c}
        restricted = sorted(c for c in known if c not in UNRESTRICTED)
        out.append(_chk("Legitimacy", "L2", "Unrestricted licence", "fail" if restricted else "pass" if known or computed else "warn",
                        ("restricted: " + ", ".join(restricted)) if restricted else ", ".join(sorted(known)) or ("computed" if computed else "no licence class recorded")))
        if data._has_hid:
            missing = [e["source"] for e in srcs if not e.get("harvest_id")]
            linked = [e for e in srcs if e.get("harvest_id")]
            notharv = [e["source"] for e in linked if (full["harvests"].get(e["harvest_id"]) or {}).get("decision") not in ("harvested", None)]
            if not srcs:
                out.append(_chk("Legitimacy", "L3", "Harvest recorded", "info", "no outside source to trace"))
            else:
                out.append(_chk("Legitimacy", "L3", "Harvest recorded", "fail" if notharv else "warn" if missing else "pass",
                                ("harvest record not 'harvested': " + ", ".join(notharv)) if notharv else
                                ("no harvest record for: " + ", ".join(missing)) if missing else
                                "%d harvest record(s) traced" % len({e['harvest_id'] for e in linked})))
        else:
            out.append(_chk("Legitimacy", "L3", "Harvest recorded", "info", "this Commons predates harvest tracing"))
        quoted = [e for e in ev if e.get("quote")]
        offending = []
        for e in quoted:
            h = full["harvests"].get(e.get("harvest_id")) if e.get("harvest_id") else None
            cls = (h or {}).get("licence_class") or (reg.get((h or {}).get("source_key")) or {}).get("licence_class")
            if cls not in TEXT_FREE:
                offending.append("%s (%s)" % (e["source"], cls or "class unknown"))
        out.append(_chk("Legitimacy", "L4", "No third-party wording", "fail" if offending else "pass",
                        ("quotes kept from: " + ", ".join(offending)) if offending else
                        "%d quote(s), all from text-free sources" % len(quoted) if quoted else "no quotes stored"))
        ch = data.chain()
        if ch.get("present") or not ch.get("ok"):
            out.append(_chk("Legitimacy", "L5", "Harvest log intact", "pass" if ch["ok"] else "fail",
                            "hash chain verifies over %d entries" % ch["entries"] if ch["ok"] else
                            "hash chain broken at entry %s" % ch.get("broken_at", "?")))
    # ---------------- accuracy
    s, p, o = u["subject"] or "", u["predicate"] or "", u["object"] or ""
    if bulk:
        want = hashlib.sha256("|".join([norm(u["domain"]), norm(s), norm(p), norm(o)]).encode("utf-8")).hexdigest()[:32]
        ok = want == u["fingerprint"]
    elif ufcs:
        want = ufcs_fingerprint(s, p, o, u.get("polarity", "+"))
        ok = want == u["fingerprint"]
    else:
        want = qb_fingerprint(u["domain"], s, p, o)
        ok = want == u["fingerprint"]
        if not ok and len(o) == 2000:
            out.append(_chk("Accuracy", "A1", "Fingerprint recomputes", "warn", "the object was stored cut at 2000 characters"))
            ok = None
    if ok is not None:
        out.append(_chk("Accuracy", "A1", "Fingerprint recomputes", "pass" if ok else "fail",
                        "content and address agree" if ok else "stored %s… ≠ recomputed %s… — the record was altered" % (u["fingerprint"][:12], want[:12])))
    probs = []
    if not s.strip() or not p.strip() or not o.strip():
        probs.append("an empty part")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏﻿]", s + p + o):
        probs.append("invisible or control characters")
    pl = norm(p)
    if pl in DATE_PREDICATES or pl.startswith("date ") or pl.endswith(" date"):
        d = parse_date(o)
        if d is None:
            probs.append("'%s' is not a valid date" % o[:40])
        elif d[0] > datetime.date.today().year + 1 and pl in ("date of birth", "date of death", "inception", "dissolved"):
            probs.append("date in the future")
    if pl == "coordinates":
        m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$", o)
        if not m or not (-90 <= float(m.group(1)) <= 90 and -180 <= float(m.group(2)) <= 180):
            probs.append("coordinates out of range or malformed")
    if pl == "atomic number" and not (o.strip().isdigit() and 1 <= int(o.strip()) <= 200):
        probs.append("atomic number is not a whole number 1–200")
    if pl == "population":
        m = re.match(r"^\s*(-?[\d.]+)", o)
        if not m or float(m.group(1)) < 0:
            probs.append("population is not a non-negative number")
    out.append(_chk("Accuracy", "A2", "Well-formed value", "fail" if probs else "pass", "; ".join(probs) or "subject, predicate and object are well-formed"))
    if not bulk and not ufcs:
        ev = full["evidence"]
        con = [e for e in ev if e["verdict"] == "contradicts"]
        sup = [e for e in ev if e["verdict"] == "supports"]
        cant = [e for e in ev if e["verdict"] == "cannot_check"]
        out.append(_chk("Accuracy", "A3", "Evidence agrees", "fail" if con else "pass" if sup else "warn",
                        ("contradicted by: " + "; ".join("%s (%s)" % (e["source"], e.get("detail") or "") for e in con)) if con else
                        "%d supporting, %d could not check" % (len(sup), len(cant))))
        earned = fact_status(ev)
        conf_ok = abs((u["confidence"] or 0) - STATUS_CONFIDENCE.get(u["status"], -1)) < 1e-9
        out.append(_chk("Accuracy", "A4", "Status earned", "pass" if earned == u["status"] and conf_ok else "fail",
                        "status '%s' (confidence %s) is what its evidence earns" % (u["status"], u["confidence"]) if earned == u["status"] and conf_ok else
                        "stored '%s' (confidence %s) but its evidence earns '%s' (confidence %s)" % (u["status"], u["confidence"], earned, STATUS_CONFIDENCE[earned])))
        srcnames = {norm(e["source"]) for e in sup if e["method"] in SOURCE_METHODS}
        recomputed = any(e["method"] == "recompute" for e in sup)
        crossed = {e["app"] for e in sup if e["method"] == "cross-check"}
        out.append(_chk("Accuracy", "A5", "Independent confirmation", "pass" if recomputed or len(srcnames) >= 2 or (srcnames and crossed) else "info",
                        "recomputed exactly" if recomputed else "%d independent source(s), %d cross-checking application(s)" % (len(srcnames), len(crossed))))
    if pl in SINGLE_VALUED:
        other = [r for r in full["related"] if norm(r["predicate"]) == pl and norm(r["object"]) != norm(o)]
        if pl.startswith("date of"):
            mine = parse_date(o)
            other = [r for r in other if parse_date(r["object"]) is None or mine is None or parse_date(r["object"])[0] != mine[0]]
        out.append(_chk("Accuracy", "A6", "No conflicting value", "warn" if other else "pass",
                        ("other value(s) held for the same subject: " + ", ".join((r.get("object_label") or r["object"])[:60] for r in other[:5])) if other else
                        "the only '%s' held for this subject" % p))
    if pl in ("date of birth", "date of death") and parse_date(o):
        mine = parse_date(o)[0]                          # this fact's own year against every opposite date held
        other = "date of death" if pl == "date of birth" else "date of birth"
        opp = [parse_date(x["object"]) for x in full["related"] if norm(x["predicate"]) == other]
        opp = [x[0] for x in opp if x]
        if opp:
            spans = [(mine, y) if pl == "date of birth" else (y, mine) for y in opp]
            okspan = [s2 for s2 in spans if 0 <= s2[1] - s2[0] <= 125]
            b, dd = (okspan or spans)[0]
            # a bare round year (1700) is often a century- or decade-precision date stored as a year: not proof of an error
            vague = not okspan and any(x["object"].strip().lstrip("+-").isdigit() and int(x["object"]) % 10 == 0
                                       for x in full["related"] + [{"object": o, "predicate": p}]
                                       if norm(x["predicate"]) in ("date of birth", "date of death") and parse_date(x["object"])
                                       and parse_date(x["object"])[0] in (b, dd))
            out.append(_chk("Accuracy", "A7", "Possible lifespan", "pass" if okspan else "warn" if vague else "fail",
                            "born %d, died %d: %d years%s" % (b, dd, dd - b, "" if okspan else
                                                               " — a round year may be a century or decade, not an exact year" if vague else
                                                               " — not a possible life")))
    # ---------------- citation
    if bulk:
        ds = full["dataset"]
        out.append(_chk("Citation", "C1", "Source cited", "pass", "%s — %s" % (ds["title"], ds["licence"])))
        out.append(_chk("Citation", "C2", "Link well-formed", "pass" if url_ok(ds["part_url"]) else "fail" if ds["source_key"] else "info",
                        ds["part_url"] or "computed: no download"))
        out.append(_chk("Citation", "C3", "Exact record cited", "pass" if ds["record_link"] else "info" if not ds["source_key"] else "warn",
                        ds["record_link"] or ("computed fact: the rule is the citation" if not ds["source_key"] else
                                              "file part and row only: %s, row %d" % (ds["part"], ds["row"]))))
    elif ufcs:
        srcs = full["stored_packet"].get("sources") or []
        urls = [x.get("url") for x in srcs if x.get("url")]
        out.append(_chk("Citation", "C1", "Source cited", "pass" if srcs else "fail", ", ".join(str(x.get("name")) for x in srcs) or "none"))
        out.append(_chk("Citation", "C2", "Link well-formed", "pass" if urls and all(url_ok(x) for x in urls) else "info", ", ".join(urls) or "the packet carries no link"))
    else:
        ev = full["evidence"]
        cited, uncited, links = [], [], []
        for e in ev:
            if e["method"] in SOURCE_METHODS + ("report",):
                h = full["harvests"].get(e.get("harvest_id")) if e.get("harvest_id") else None
                ru = (reg.get((h or {}).get("source_key")) or {}).get("url")
                u2 = e.get("url") or ru
                (cited if u2 else uncited).append(e["source"])
                if u2:
                    links.append((u2, bool(e.get("url"))))
        computed = [e for e in ev if e["method"] in ("recompute", "cross-check", "consistency")]
        if not cited and not uncited:
            out.append(_chk("Citation", "C1", "Source cited", "pass" if computed else "fail",
                            "computed or checked here (%d step(s) recorded)" % len(computed) if computed else "no source and no computation"))
        else:
            out.append(_chk("Citation", "C1", "Source cited", "warn" if uncited else "pass",
                            ("no link for: " + ", ".join(uncited)) if uncited else "every source has a link (%d)" % len(cited)))
        if links:
            badl = [x for x, _ in links if not url_ok(x)]
            out.append(_chk("Citation", "C2", "Link well-formed", "fail" if badl else "pass", ", ".join(badl) or ", ".join(sorted({x for x, _ in links}))[:300]))
            exact = [x for x, own in links if own]
            out.append(_chk("Citation", "C3", "Exact record cited", "pass" if exact else "info",
                            "the evidence links to the record" if exact else "the link is the source's home page from the registry, not the record"))
    verdict = "fail" if any(c["result"] == "fail" for c in out) else "warn" if any(c["result"] == "warn" for c in out) else "pass"
    return {"verdict": verdict, "checks": out}


# ------------------------------------------------------------------------------------------------ online checks (on request)
def fetch(url, timeout=12, want_json=False):
    base = url.split("#", 1)[0]
    req = urllib.request.Request(base, headers={"User-Agent": UA, "Accept": "application/json" if want_json else "*/*"})
    for method in (("GET",) if want_json else ("HEAD", "GET")):
        req.method = method
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(4 << 20) if want_json else (r.read(2048) if method == "GET" else b"")
                return {"url": base, "status": r.status, "ok": 200 <= r.status < 400, "final": r.geturl(),
                        "json": json.loads(body.decode("utf-8")) if want_json else None}
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code in (403, 405, 501):
                continue
            return {"url": base, "status": e.code, "ok": False, "error": str(e.reason)}
        except (urllib.error.URLError, OSError, ValueError) as e:
            return {"url": base, "status": None, "ok": False, "error": str(getattr(e, "reason", e))}
    return {"url": base, "status": None, "ok": False, "error": "no answer"}


def _wd_value(dv):
    v = (dv or {}).get("value")
    t = (dv or {}).get("type")
    if t == "wikibase-entityid":
        return "Q%s" % v.get("numeric-id") if isinstance(v, dict) else str(v)
    if t == "time":
        return v.get("time", "")
    if t == "quantity":
        return v.get("amount", "")
    if t == "monolingualtext":
        return v.get("text", "")
    if t == "globecoordinate":
        return "%s, %s" % (v.get("latitude"), v.get("longitude"))
    return str(v)


def _same(stored, live, kind):
    if kind == "time":
        t = live.lstrip("+")
        neg = t.startswith("-")
        date = t.lstrip("-").split("T")[0]
        y, _, rest = date.partition("-")
        ds = parse_date(stored)
        if ds is None:
            return False
        ly = -int(y) if neg else int(y)
        if ds[0] != ly:
            return False
        mo, _, dd = rest.partition("-")
        return (ds[1] in (None, int(mo or 0) or None)) and (ds[2] in (None, int(dd or 0) or None))
    if kind == "quantity":
        m = re.match(r"^\s*([+-]?[\d.eE+-]+)", stored)
        try:
            return m is not None and abs(float(m.group(1)) - float(live)) <= 1e-9 * max(1.0, abs(float(live)))
        except ValueError:
            return False
    if kind == "globecoordinate":
        try:
            a = [float(x) for x in stored.split(",")]
            b = [float(x) for x in live.split(",")]
            return abs(a[0] - b[0]) < 1e-3 and abs(a[1] - b[1]) < 1e-3
        except (ValueError, IndexError):
            return False
    return norm(stored) == norm(live)


def online(full, data):
    """fetch every citation link and, for Wikidata facts, re-read the entity and compare the value"""
    u = full["unit"]
    urls = []
    if u["store"].startswith("b:"):
        ds = full["dataset"]
        urls = [x for x in (ds["record_link"], ds["part_url"]) if x]
    elif u["store"] == "commons":
        reg = data.registry()
        for e in full["evidence"]:
            if e.get("url"):
                urls.append(e["url"])
            h = full["harvests"].get(e.get("harvest_id")) if e.get("harvest_id") else None
            ru = (reg.get((h or {}).get("source_key")) or {}).get("url")
            if ru:
                urls.append(ru)
    elif u["store"] == "ufcs":
        urls = [x.get("url") for x in full["stored_packet"].get("sources") or [] if x.get("url")]
    links = [fetch(x) for x in list(dict.fromkeys(urls))[:8]]
    recheck = None
    m = QID_END.search(u["subject"] or "")
    is_wd = u["store"].startswith("b:") and (DATASETS.get(u["store"][2:]) or ("",) * 5)[2] == "wikidata"
    if m and is_wd:
        pid = data.props.get(u["predicate"])
        if not pid:
            recheck = {"result": "warn", "detail": "no Wikidata property is known for '%s' (property list not in this folder)" % u["predicate"]}
        else:
            r = fetch("https://www.wikidata.org/wiki/Special:EntityData/%s.json" % m.group(1), want_json=True)
            if not r.get("ok"):
                recheck = {"result": "warn", "detail": "Wikidata did not answer: %s" % (r.get("error") or r.get("status"))}
            else:
                ent = (r["json"].get("entities") or {})
                ent = next(iter(ent.values()), {}) if ent else {}
                claims = (ent.get("claims") or {}).get(pid) or []
                vals = [(c.get("mainsnak") or {}).get("datavalue") for c in claims if c.get("rank") != "deprecated"]
                vals = [v for v in vals if v]
                live = [(_wd_value(v), v.get("type")) for v in vals]
                hit = any(_same(u["object"], lv, kind) for lv, kind in live)
                recheck = {"result": "pass" if hit else "fail", "property": pid, "live_values": [lv for lv, _ in live][:10],
                           "detail": ("Wikidata still says this (%s)" % pid) if hit else
                           ("Wikidata no longer says this: %s now holds %s" % (pid, ", ".join(lv for lv, _ in live[:5]) or "no value"))}
    return {"links": links, "source_recheck": recheck,
            "summary": "%d of %d link(s) answered" % (sum(1 for x in links if x["ok"]), len(links))}


# ------------------------------------------------------------------------------------------------ the store-wide audit
class AuditRun:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"running": False}
        self.report = None
        self._stop = False

    def start(self, data, sample=2000, full=False, online_n=0):
        with self.lock:
            if self.state.get("running"):
                raise ValueError("an audit is already running")
            self._stop = False
            self.state = {"running": True, "done": 0, "started": time.time(), "store": "", "sample": sample, "full": full}
        threading.Thread(target=self._run, args=(data, sample, full, online_n), daemon=True).start()

    def stop(self):
        self._stop = True

    def _run(self, data, sample, full, online_n):
        try:
            self.report = run_audit(data, sample, full, online_n, progress=self._progress, stop=lambda: self._stop)
            path = save_report(self.report)
            self.state.update(running=False, finished=time.time(), saved=path)
        except Exception as e:                        # the audit reports its own failure; the server keeps running
            self.state.update(running=False, error="%s: %s" % (type(e).__name__, e))

    def _progress(self, store, done):
        self.state.update(store=store, done=done)


def run_audit(data, sample=2000, full=False, online_n=0, progress=None, stop=None):
    t0 = time.time()
    rep = {"tool": "QueryBook Fact Auditor %s" % VERSION, "folder": data.folder, "started": _iso(t0), "full": bool(full),
           "sample_per_store": None if full else sample, "stores": {}, "checks": {}, "verdicts": {"pass": 0, "warn": 0, "fail": 0},
           "issues": [], "online": [], "harvest_log": data.chain()}
    done = 0
    online_left = int(online_n or 0)
    for st in data.stores():
        sid = st["id"]
        srep = {"title": st["title"], "facts_held": st["facts"], "audited": 0, "pass": 0, "warn": 0, "fail": 0}
        rep["stores"][sid] = srep
        after = ""
        while True:
            if stop and stop():
                rep["stopped"] = True
                break
            want = 200 if full else min(200, sample - srep["audited"])
            if want <= 0:
                break
            page = data.list(store=sid, after=after, limit=want)
            if not page["facts"]:
                break
            for row in page["facts"]:
                f = data.fact(row["id"])
                if not f:
                    continue
                a = audit(f, data)
                srep["audited"] += 1
                srep[a["verdict"]] += 1
                rep["verdicts"][a["verdict"]] += 1
                for c in a["checks"]:
                    k = "%s %s" % (c["id"], c["name"])
                    rep["checks"].setdefault(k, {"group": c["group"], "pass": 0, "warn": 0, "fail": 0, "info": 0})[c["result"]] += 1
                    if c["result"] in ("fail", "warn") and len(rep["issues"]) < 5000:
                        rep["issues"].append({"fact": row["id"], "store": sid, "subject": f["unit"]["subject"], "predicate": f["unit"]["predicate"],
                                              "object": f["unit"]["object"], "check": k, "result": c["result"], "detail": c["detail"]})
                if online_left > 0:
                    online_left -= 1
                    o = online(f, data)
                    rep["online"].append({"fact": row["id"], "subject": f["unit"]["subject"], "predicate": f["unit"]["predicate"],
                                          "links": [(x["url"], x["status"], x["ok"]) for x in o["links"]], "source_recheck": o["source_recheck"]})
                    time.sleep(0.2)
                done += 1
                if progress and not done % 100:
                    progress(sid, done)
            after = page["next"]
            if not after:
                break
        if rep.get("stopped"):
            break
    rep["finished"] = _iso(time.time())
    rep["seconds"] = round(time.time() - t0, 1)
    rep["audited"] = done
    if progress:
        progress("", done)
    return rep


def _iso(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def save_report(rep):
    os.makedirs(REPORTS, exist_ok=True)
    path = os.path.join(REPORTS, "audit-%s.json" % rep["started"].replace(":", "").replace("-", ""))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=1, ensure_ascii=False)
    return path


def report_csv(rep):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["fact", "store", "subject", "predicate", "object", "check", "result", "detail"])
    for i in rep.get("issues", []):
        w.writerow([i["fact"], i["store"], i["subject"], i["predicate"], i["object"], i["check"], i["result"], i["detail"]])
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------ the web app
class App:
    def __init__(self, folder=None):
        self.data = None
        self.run = AuditRun()
        self.set_folder(folder or self._saved() or next(iter(candidate_folders()), None))

    def _saved(self):
        try:
            with open(SETTINGS, encoding="utf-8") as f:
                return json.load(f).get("folder")
        except (OSError, ValueError):
            return None

    def set_folder(self, folder, save=False):
        if not folder:
            self.data = None
            return
        if not os.path.isdir(folder) or not looks_like_store(folder):
            raise ValueError("No QueryBook facts found in %s (looked for commons.sqlite, shards/*.sqlite or a UFCS store)." % folder)
        self.data = Data(folder)
        if save:
            try:
                with open(SETTINGS, "w", encoding="utf-8") as f:
                    json.dump({"folder": self.data.folder}, f)
            except OSError:
                pass

    def need(self):
        if self.data is None:
            raise ValueError("Choose the QueryBook fact folder first (Settings).")
        return self.data

    def detail(self, fid):
        d = self.need()
        f = d.fact(fid)
        if not f:
            raise KeyError("No such fact: %s" % fid)
        main, assoc = packets(f, d)
        return {"unit": f["unit"], "packet": main, "packets": assoc, "audit": audit(f, d), "evidence": f["evidence"],
                "reasoning": f["reasoning"], "requests": f["requests"], "dataset": f.get("dataset"),
                "related": f["related"][:100], "related_total": len(f["related"])}

    def handle(self, method, path, query, body):
        if path == "/api/info":
            d = self.data
            return {"version": VERSION, "folder": d.folder if d else None, "found": candidate_folders(),
                    "stores": d.stores() if d else [], "registry": len(d.registry()) if d else 0,
                    "harvest_log": d.chain() if d else None, "read_only": True}
        if path == "/api/folder" and method == "POST":
            self.set_folder(body.get("folder", "").strip(), save=True)
            return {"ok": True, "folder": self.data.folder}
        if path == "/api/facts":
            return self.need().list(query.get("store", ""), query.get("q", ""), query.get("after", ""), query.get("limit", 50), query.get("status", ""))
        if path == "/api/fact":
            return self.detail(query.get("id", ""))
        if path == "/api/fact/online" and method == "POST":
            d = self.need()
            f = d.fact(body.get("id", ""))
            if not f:
                raise KeyError("No such fact")
            return online(f, d)
        if path == "/api/sources":
            d = self.need()
            return {"registry": sorted(d.registry().values(), key=lambda r: (r["status"], r["key"])),
                    "datasets": [dict(zip(("key", "title", "area", "source_key", "licence"), (k,) + v[:4]), held=k in d.shards)
                                 for k, v in DATASETS.items() if k in d.shards or not k.startswith("wikidata-dump-")]}
        if path == "/api/audit/start" and method == "POST":
            self.run.start(self.need(), int(body.get("sample") or 2000), bool(body.get("full")), min(200, int(body.get("online") or 0)))
            return {"ok": True}
        if path == "/api/audit/stop" and method == "POST":
            self.run.stop()
            return {"ok": True}
        if path == "/api/audit/status":
            r = self.run.report
            return {"state": self.run.state, "report": dict({k: v for k, v in r.items() if k != "issues"}, issues=r["issues"][:300],
                                                             issue_total=len(r["issues"])) if r else None}
        raise KeyError("Unknown address: " + path)


class Handler(BaseHTTPRequestHandler):
    app = None
    server_version = "QueryBookFactAuditor/" + VERSION

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _local(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def do_GET(self):
        self._do("GET")

    def do_POST(self):
        self._do("POST")

    def _do(self, method):
        if not self._local():
            return self._send(403, json.dumps({"error": "local use only"}))
        u = urllib.parse.urlparse(self.path)
        query = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path in ("/", "/index.html"):
                return self._send(200, PAGE, "text/html; charset=utf-8",
                                  {"Content-Security-Policy": "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:"})
            if u.path == "/api/audit/report.json":
                r = self.app.run.report
                if not r:
                    return self._send(404, json.dumps({"error": "no audit has run yet"}))
                return self._send(200, json.dumps(r, indent=1, ensure_ascii=False), extra={"Content-Disposition": "attachment; filename=fact-audit.json"})
            if u.path == "/api/audit/report.csv":
                r = self.app.run.report
                if not r:
                    return self._send(404, json.dumps({"error": "no audit has run yet"}))
                return self._send(200, report_csv(r), "text/csv; charset=utf-8", {"Content-Disposition": "attachment; filename=fact-audit-issues.csv"})
            if u.path == "/api/export.jsonl":
                return self._export(query)
            body = {}
            if method == "POST":
                if self.headers.get("Origin") and not re.match(r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$", self.headers["Origin"]):
                    return self._send(403, json.dumps({"error": "cross-site request refused"}))
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(min(n, 1 << 20)).decode("utf-8") or "{}") if n else {}
            out = self.app.handle(method, u.path, query, body)
            return self._send(200, json.dumps(out, ensure_ascii=False, default=str))
        except KeyError as e:
            return self._send(404, json.dumps({"error": str(e.args[0] if e.args else e)}))
        except (ValueError, sqlite3.Error) as e:
            return self._send(400, json.dumps({"error": str(e)}))

    def _export(self, query):
        """the facts of one store as UFCS packets, one per line (with their associated packets)"""
        d = self.app.need()
        limit = max(1, min(int(query.get("limit") or 10000), 1000000))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Content-Disposition", "attachment; filename=ufcs-packets.jsonl")
        self.end_headers()
        after, n = "", 0
        while n < limit:
            page = d.list(store=query.get("store", ""), q=query.get("q", ""), after=after, limit=min(200, limit - n))
            for row in page["facts"]:
                f = d.fact(row["id"])
                if f:
                    main, assoc = packets(f, d)
                    main = dict(main, associated_packets=assoc, audit=audit(f, d))
                    self.wfile.write((json.dumps(main, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
                    n += 1
            after = page["next"]
            if not after:
                break


# ------------------------------------------------------------------------------------------------ the page
PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fact Auditor</title>
<style>
:root{--bg:#f6f7f9;--panel:#fff;--ink:#16181d;--muted:#5d6470;--line:#dde1e7;--accent:#2f5bd3;--accent-ink:#fff;
--pass:#1d7a46;--pass-bg:#e5f4ec;--warn:#8a5a00;--warn-bg:#fdf1d6;--fail:#b3261e;--fail-bg:#fbe5e3;--info:#43506a;--info-bg:#eaeef5;
--code:#f1f3f6;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#111317;--panel:#1a1d23;--ink:#e8eaee;--muted:#9aa2b0;--line:#2c3139;
--accent:#7b9cff;--accent-ink:#0b0d12;--pass:#6fd39b;--pass-bg:#16301f;--warn:#f0c060;--warn-bg:#33280f;--fail:#ff8a80;--fail-bg:#3a1714;
--info:#b6c2d9;--info-bg:#222833;--code:#14171c}}
:root[data-theme=dark]{--bg:#111317;--panel:#1a1d23;--ink:#e8eaee;--muted:#9aa2b0;--line:#2c3139;--accent:#7b9cff;--accent-ink:#0b0d12;
--pass:#6fd39b;--pass-bg:#16301f;--warn:#f0c060;--warn-bg:#33280f;--fail:#ff8a80;--fail-bg:#3a1714;--info:#b6c2d9;--info-bg:#222833;--code:#14171c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;padding:12px 16px;border-bottom:1px solid var(--line);background:var(--panel)}
header h1{font-size:17px;margin:0}header .sub{color:var(--muted);font-size:12.5px}
nav{display:flex;gap:4px;padding:0 16px;background:var(--panel);border-bottom:1px solid var(--line);overflow-x:auto}
nav button{border:0;background:none;padding:10px 12px;color:var(--muted);cursor:pointer;font:inherit;border-bottom:2px solid transparent}
nav button.on{color:var(--ink);border-bottom-color:var(--accent)}
main{padding:16px;max-width:1500px;margin:0 auto}.tab{display:none}.tab.on{display:block}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px;margin-bottom:14px}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
input,select{font:inherit;padding:7px 9px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink);min-width:0}
button.b{font:inherit;padding:7px 12px;border-radius:6px;border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer}
button.p{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}button:disabled{opacity:.5;cursor:default}
.split{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);gap:14px}@media (max-width:980px){.split{grid-template-columns:1fr}}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
th{font-weight:600;color:var(--muted);font-size:12px}tr.fact{cursor:pointer}tr.fact:hover,tr.fact.sel{background:var(--info-bg)}
.muted{color:var(--muted)}.small{font-size:12px}.mono{font-family:var(--mono);font-size:12px}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:600;white-space:nowrap}
.pass{color:var(--pass);background:var(--pass-bg)}.warn{color:var(--warn);background:var(--warn-bg)}.fail{color:var(--fail);background:var(--fail-bg)}
.info{color:var(--info);background:var(--info-bg)}
pre{background:var(--code);border:1px solid var(--line);border-radius:6px;padding:10px;overflow:auto;max-height:420px;font:12px/1.4 var(--mono);margin:6px 0}
details{border:1px solid var(--line);border-radius:6px;padding:6px 10px;margin:6px 0}summary{cursor:pointer}
h2{font-size:15px;margin:0 0 8px}h3{font-size:13.5px;margin:14px 0 6px}
.kv{display:grid;grid-template-columns:150px minmax(0,1fr);gap:4px 10px}.kv div:nth-child(odd){color:var(--muted)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.stat{border:1px solid var(--line);border-radius:8px;padding:10px}
.stat b{display:block;font-size:20px}.err{color:var(--fail)}.scroll{overflow-x:auto}
</style></head><body>
<header><div><h1>QueryBook Fact Auditor</h1><div class="sub" id="where">Legitimacy, accuracy and citation audit — read-only</div></div></header>
<nav><button class="on" data-t="facts">Facts</button><button data-t="audit">Audit</button><button data-t="sources">Sources</button><button data-t="settings">Settings</button></nav>
<main>
<section class="tab on" id="t-facts">
 <div class="card"><div class="row">
  <select id="store" aria-label="Fact store"><option value="">All stores</option></select>
  <select id="status" aria-label="Status"><option value="">Any status</option></select>
  <input id="q" placeholder="Subject starts with… or a fingerprint" style="flex:1;min-width:200px" aria-label="Search">
  <button class="b p" id="go">Show facts</button><span class="muted small" id="count"></span></div></div>
 <div class="split">
  <div class="card"><div class="scroll"><table><thead><tr><th>Subject</th><th>Predicate</th><th>Object</th><th>Status</th></tr></thead><tbody id="list"></tbody></table></div>
   <div class="row" style="margin-top:10px"><button class="b" id="more" disabled>Next page</button><a class="small" id="exp" href="#">Download these facts as UFCS packets (JSONL)</a></div></div>
  <div class="card" id="detail"><p class="muted">Choose a fact to see its Fact Unit, its UFCS fact packet, the packets associated with it and its audit.</p></div>
 </div>
</section>
<section class="tab" id="t-audit">
 <div class="card"><h2>Audit the whole store</h2>
  <p class="muted small">Every offline check on every fact audited. Sampling takes the first facts of each store in fingerprint order, which is an even spread. Online checks fetch each citation link and re-read Wikidata facts from Wikidata.</p>
  <div class="row"><label>Facts per store <input id="sample" type="number" value="2000" min="1" style="width:110px"></label>
   <label><input id="full" type="checkbox"> every fact (can take hours on billions)</label>
   <label>Online re-checks <input id="online" type="number" value="0" min="0" max="200" style="width:80px"></label>
   <button class="b p" id="run">Run audit</button><button class="b" id="stop">Stop</button></div>
  <p id="ast" class="small"></p></div>
 <div id="arep"></div>
</section>
<section class="tab" id="t-sources"><div class="card" id="srcs"><p class="muted">Loading…</p></div></section>
<section class="tab" id="t-settings"><div class="card"><h2>Fact folder</h2>
 <p class="muted small">The folder QueryBook keeps its shared facts in (the one the Control Panel's "Move the shared folder" points at). It is opened read-only: the auditor never changes a fact.</p>
 <div class="row"><input id="folder" style="flex:1;min-width:260px" aria-label="Folder"><button class="b p" id="setf">Use this folder</button></div>
 <p class="small" id="found"></p><p class="small err" id="ferr"></p></div></section>
</main>
<script>
const $=s=>document.querySelector(s);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const J=(o)=>esc(JSON.stringify(o,null,1));
async function api(p,b){const r=await fetch(p,b?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)}:{});
 const j=await r.json().catch(()=>({error:"bad answer"}));if(!r.ok)throw new Error(j.error||r.status);return j}
const badge=r=>`<span class="badge ${esc(r)}">${esc(r)}</span>`;
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>{document.querySelectorAll("nav button").forEach(x=>x.classList.toggle("on",x===b));
 document.querySelectorAll(".tab").forEach(t=>t.classList.toggle("on",t.id==="t-"+b.dataset.t));if(b.dataset.t==="sources")sources()});
let next=null,info=null;
async function load(){try{info=await api("/api/info")}catch(e){$("#where").textContent=e.message;return}
 $("#where").textContent=info.folder?`${info.folder} · read-only · v${info.version}`:"No fact folder chosen yet — see Settings";
 $("#folder").value=info.folder||(info.found[0]||"");
 $("#found").innerHTML=info.found.length?"Found on this computer: "+info.found.map(esc).join("; "):"No QueryBook fact folder found automatically.";
 const total=info.stores.reduce((a,s)=>a+s.facts,0);
 $("#store").innerHTML=`<option value="">All stores (${total.toLocaleString()} facts)</option>`+info.stores.map(s=>`<option value="${esc(s.id)}">${esc(s.title)} — ${s.facts.toLocaleString()}</option>`).join("");
 $("#status").innerHTML='<option value="">Any status</option>'+["verified","corroborated","sourced","reported","unsourced","disputed","rejected","computed"].map(s=>`<option>${s}</option>`).join("");
 if(info.folder)facts(true)}
async function facts(reset){const p=new URLSearchParams({store:$("#store").value,q:$("#q").value,status:$("#status").value,limit:50});
 if(!reset&&next)p.set("after",next);
 $("#exp").href="/api/export.jsonl?"+new URLSearchParams({store:$("#store").value,q:$("#q").value,limit:10000});
 try{const r=await api("/api/facts?"+p);next=r.next;$("#more").disabled=!next;
  const rows=r.facts.map(f=>`<tr class="fact" data-id="${esc(f.id)}"><td>${esc(f.subject)}</td><td>${esc(f.predicate)}</td><td>${esc(f.object_label||f.object)}</td><td>${badge(f.status==="rejected"||f.status==="disputed"?"fail":f.status==="unsourced"||f.status==="reported"?"warn":"pass").replace(/>[a-z]+</,">"+esc(f.status)+"<")}</td></tr>`).join("");
  if(reset)$("#list").innerHTML=rows;else $("#list").insertAdjacentHTML("beforeend",rows);
  $("#count").textContent=$("#list").children.length+" shown";
  document.querySelectorAll("tr.fact").forEach(t=>t.onclick=()=>{document.querySelectorAll("tr.fact.sel").forEach(x=>x.classList.remove("sel"));t.classList.add("sel");show(t.dataset.id)})}
 catch(e){$("#list").innerHTML=`<tr><td colspan="4" class="err">${esc(e.message)}</td></tr>`}}
$("#go").onclick=()=>facts(true);$("#more").onclick=()=>facts(false);$("#q").onkeydown=e=>{if(e.key==="Enter")facts(true)};
async function show(id){const d=$("#detail");d.innerHTML='<p class="muted">Loading…</p>';
 try{const f=await api("/api/fact?id="+encodeURIComponent(id));const u=f.unit,a=f.audit;
  const groups=["Legitimacy","Accuracy","Citation"].map(g=>{const cs=a.checks.filter(c=>c.group===g);
   return `<h3>${g}</h3><table>${cs.map(c=>`<tr><td style="width:70px">${badge(c.result)}</td><td style="width:200px">${esc(c.id)} ${esc(c.name)}</td><td class="small">${esc(c.detail)}</td></tr>`).join("")}</table>`}).join("");
  const kv=[["Subject",u.subject],["Predicate",u.predicate],["Object",u.object_label?u.object_label+"  ["+u.object+"]":u.object],["Domain",u.domain],["Status",u.status],["Confidence",u.confidence],
   ["Fingerprint",u.fingerprint],["Fingerprint rule",u.fingerprint_rule],["Origin",u.origin],["Stored in",u.location],["Created",u.created],["Updated",u.updated]].concat(u.statement?[["Statement",u.statement]]:[])
   .map(([k,v])=>`<div>${esc(k)}</div><div class="${k.startsWith("Finger")?"mono":""}">${esc(v)}</div>`).join("");
  const pk=f.packets.map((p,i)=>`<details><summary>${badge(p.certification.verdict==="contradicts"?"fail":p.certification.verdict==="supports"?"pass":"info").replace(/>[a-z_]+</,">"+esc(p.fact_type)+"<")} ${esc(p.sources[0]?.name||"")} <span class="muted small">${esc(p.certification.verdict||"")} · ${esc(p.temporal.ingested||"")}</span></summary><pre>${J(p)}</pre></details>`).join("")||'<p class="muted small">No associated packets.</p>';
  const rel=f.related.map(r=>`<tr class="fact" data-id="${esc(r.id)}"><td>${esc(r.predicate)}</td><td>${esc(r.object_label||r.object)}</td></tr>`).join("");
  d.innerHTML=`<div class="row" style="justify-content:space-between"><h2 style="margin:0">${esc(u.subject)}</h2>${badge(a.verdict)}</div>
   <p class="muted small">${esc(u.store_title)}</p>
   <div class="row"><button class="b" id="onl">Check citations &amp; source online</button><button class="b" id="cp">Copy UFCS packet</button></div><div id="onr" class="small"></div>
   ${groups}
   <h3>Fact Unit</h3><div class="kv small">${kv}</div>
   <h3>UFCS fact packet</h3><pre id="mainpk">${J(f.packet)}</pre>
   <h3>Associated UFCS packets (${f.packets.length})</h3>${pk}
   ${f.reasoning.length?`<h3>Reasoning</h3><ol class="small">${f.reasoning.map(r=>`<li>${esc(r.app)} / ${esc(r.agent)}: ${esc(r.text)}</li>`).join("")}</ol>`:""}
   <h3>Other facts about this subject (${f.related_total})</h3><div class="scroll"><table class="small">${rel||'<tr><td class="muted">none held</td></tr>'}</table></div>`;
  d.querySelectorAll("tr.fact").forEach(t=>t.onclick=()=>show(t.dataset.id));
  $("#cp").onclick=()=>navigator.clipboard?.writeText(JSON.stringify(f.packet,null,1));
  $("#onl").onclick=async()=>{$("#onl").disabled=true;$("#onr").textContent="Checking online…";
   try{const o=await api("/api/fact/online",{id});
    $("#onr").innerHTML=`<p>${esc(o.summary)}</p><table>${o.links.map(l=>`<tr><td>${badge(l.ok?"pass":"fail")}</td><td class="mono">${esc(l.url)}</td><td>${esc(l.status??l.error)}</td></tr>`).join("")}</table>`+
     (o.source_recheck?`<p>${badge(o.source_recheck.result)} Source re-check: ${esc(o.source_recheck.detail)}</p>`:"")}
   catch(e){$("#onr").innerHTML=`<span class="err">${esc(e.message)}</span>`}$("#onl").disabled=false}}
 catch(e){d.innerHTML=`<p class="err">${esc(e.message)}</p>`}}
let poll=null;
$("#run").onclick=async()=>{try{await api("/api/audit/start",{sample:+$("#sample").value,full:$("#full").checked,online:+$("#online").value});status();poll=setInterval(status,1500)}
 catch(e){$("#ast").innerHTML=`<span class="err">${esc(e.message)}</span>`}};
$("#stop").onclick=()=>api("/api/audit/stop",{});
async function status(){const s=await api("/api/audit/status");const st=s.state;
 $("#ast").textContent=st.running?`Auditing… ${st.done.toLocaleString()} facts${st.store?" ("+st.store+")":""}`:st.error?"Failed: "+st.error:st.saved?"Saved to "+st.saved:"";
 if(!st.running&&poll){clearInterval(poll);poll=null}
 const r=s.report;if(!r)return;
 const pct=n=>r.audited?(100*n/r.audited).toFixed(1)+"%":"–";
 $("#arep").innerHTML=`<div class="card"><h2>Result</h2><div class="stats">
  <div class="stat"><span class="muted small">Facts audited</span><b>${r.audited.toLocaleString()}</b><span class="small muted">${esc(r.seconds)} s</span></div>
  <div class="stat"><span class="muted small">Pass</span><b style="color:var(--pass)">${r.verdicts.pass.toLocaleString()}</b><span class="small">${pct(r.verdicts.pass)}</span></div>
  <div class="stat"><span class="muted small">Warnings</span><b style="color:var(--warn)">${r.verdicts.warn.toLocaleString()}</b><span class="small">${pct(r.verdicts.warn)}</span></div>
  <div class="stat"><span class="muted small">Failures</span><b style="color:var(--fail)">${r.verdicts.fail.toLocaleString()}</b><span class="small">${pct(r.verdicts.fail)}</span></div>
  <div class="stat"><span class="muted small">Harvest log</span><b>${r.harvest_log.ok?"intact":"BROKEN"}</b><span class="small">${esc(r.harvest_log.entries)} entries</span></div></div>
  <div class="row" style="margin-top:10px"><a href="/api/audit/report.json">Download the full report (JSON)</a><a href="/api/audit/report.csv">Download the issues (CSV)</a></div></div>
  <div class="card"><h2>By check</h2><div class="scroll"><table><tr><th>Group</th><th>Check</th><th>Pass</th><th>Warn</th><th>Fail</th><th>Info</th></tr>
  ${Object.entries(r.checks).sort().map(([k,c])=>`<tr><td>${esc(c.group)}</td><td>${esc(k)}</td><td>${c.pass}</td><td>${c.warn}</td><td>${c.fail}</td><td>${c.info}</td></tr>`).join("")}</table></div></div>
  <div class="card"><h2>By store</h2><div class="scroll"><table><tr><th>Store</th><th>Held</th><th>Audited</th><th>Pass</th><th>Warn</th><th>Fail</th></tr>
  ${Object.entries(r.stores).map(([k,s])=>`<tr><td>${esc(s.title)}</td><td>${s.facts_held.toLocaleString()}</td><td>${s.audited}</td><td>${s.pass}</td><td>${s.warn}</td><td>${s.fail}</td></tr>`).join("")}</table></div></div>
  ${r.online.length?`<div class="card"><h2>Online re-checks</h2><table>${r.online.map(o=>`<tr><td>${esc(o.subject)}</td><td>${esc(o.predicate)}</td><td>${o.source_recheck?badge(o.source_recheck.result)+" "+esc(o.source_recheck.detail):""}</td><td class="small">${o.links.map(l=>esc(l[1]??"no answer")).join(", ")}</td></tr>`).join("")}</table></div>`:""}
  <div class="card"><h2>Issues (${r.issue_total.toLocaleString()}${r.issue_total>300?", first 300 shown":""})</h2><div class="scroll"><table class="small"><tr><th></th><th>Fact</th><th>Check</th><th>Detail</th></tr>
  ${r.issues.map(i=>`<tr class="fact" data-id="${esc(i.fact)}"><td>${badge(i.result)}</td><td>${esc(i.subject)} — ${esc(i.predicate)} — ${esc(i.object)}</td><td>${esc(i.check)}</td><td>${esc(i.detail)}</td></tr>`).join("")}</table></div></div>`;
 document.querySelectorAll("#arep tr.fact").forEach(t=>t.onclick=()=>{document.querySelector('nav button[data-t=facts]').click();show(t.dataset.id)})}
async function sources(){try{const s=await api("/api/sources");
 $("#srcs").innerHTML=`<h2>Policy registry (${s.registry.length})</h2><div class="scroll"><table class="small"><tr><th>Source</th><th>Licence</th><th>Class</th><th>Status</th><th>Decided</th></tr>
 ${s.registry.map(r=>`<tr><td>${esc(r.name)}<div class="muted mono">${esc(r.key)}</div></td><td>${esc(r.licence)}</td><td>${badge(["public-domain","cc0","facts","us-federal","computed","user-facts"].includes(r.licence_class)?"pass":"fail").replace(/>[a-z]+</,">"+esc(r.licence_class)+"<")}</td><td>${esc(r.status)}</td><td>${esc(r.decided_by||"")} ${esc(r.decided_at||"")}</td></tr>`).join("")}</table></div>
 <h2 style="margin-top:16px">Bulk datasets</h2><table class="small"><tr><th>Dataset</th><th>Area</th><th>Source</th><th>Licence</th><th>Held here</th></tr>
 ${s.datasets.map(d=>`<tr><td>${esc(d.title)}</td><td>${esc(d.area)}</td><td class="mono">${esc(d.source_key||"computed")}</td><td>${esc(d.licence)}</td><td>${d.held?"yes":""}</td></tr>`).join("")}</table>`}
 catch(e){$("#srcs").innerHTML=`<p class="err">${esc(e.message)}</p>`}}
$("#setf").onclick=async()=>{$("#ferr").textContent="";try{await api("/api/folder",{folder:$("#folder").value});load()}catch(e){$("#ferr").textContent=e.message}};
load();status().catch(()=>{});
</script></body></html>
"""


# ------------------------------------------------------------------------------------------------ self-test
def _fixture(folder):
    """a tiny QueryBook-shaped folder: a Commons with sourced, verified, tampered, disputed and quoted facts, a harvest log,
    and one bulk shard"""
    os.makedirs(os.path.join(folder, "shards"), exist_ok=True)
    db = sqlite3.connect(os.path.join(folder, "commons.sqlite"))
    db.executescript("""
CREATE TABLE facts (id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, domain TEXT NOT NULL, subject TEXT NOT NULL, predicate TEXT NOT NULL,
  object TEXT NOT NULL, statement TEXT, origin_app TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'unsourced', confidence REAL NOT NULL DEFAULT 0.2,
  created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE evidence (id INTEGER PRIMARY KEY, fact_id INTEGER NOT NULL, app TEXT NOT NULL, agent TEXT NOT NULL, method TEXT NOT NULL,
  source TEXT NOT NULL, licence TEXT, url TEXT, quote TEXT, verdict TEXT NOT NULL, detail TEXT, at TEXT NOT NULL, harvest_id INTEGER);
CREATE TABLE reasoning (id INTEGER PRIMARY KEY, fact_id INTEGER NOT NULL, app TEXT NOT NULL, agent TEXT NOT NULL, step INTEGER NOT NULL, text TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE requests (id INTEGER PRIMARY KEY, fact_id INTEGER NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE,
  from_app TEXT NOT NULL, to_app TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', verdict TEXT, detail TEXT, created TEXT NOT NULL, answered TEXT);
CREATE TABLE policy_sources (id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, name TEXT NOT NULL, apps TEXT NOT NULL, kind TEXT, licence TEXT NOT NULL,
  licence_class TEXT NOT NULL, url TEXT, licence_url TEXT, status TEXT NOT NULL, reason TEXT, added_by TEXT NOT NULL, added TEXT NOT NULL, decided_by TEXT, decided_at TEXT);
CREATE TABLE harvest_log (id INTEGER PRIMARY KEY, at TEXT NOT NULL, app TEXT NOT NULL, domain TEXT NOT NULL, action TEXT NOT NULL, title TEXT,
  source_key TEXT, licence_class TEXT, decision TEXT NOT NULL, items INTEGER, new INTEGER, merged INTEGER, seconds REAL, reason TEXT, budget_key TEXT,
  turn_id INTEGER, policy_version INTEGER, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
""")
    T = "2026-10-31T12:00:00Z"
    db.execute("INSERT INTO policy_sources(key,name,apps,licence,licence_class,url,status,added_by,added) VALUES(?,?,?,?,?,?,?,?,?)",
               ("natural-earth", "Natural Earth", "facts", "Public domain", "public-domain", "https://www.naturalearthdata.com/", "approved", "system", T))
    db.execute("INSERT INTO policy_sources(key,name,apps,licence,licence_class,url,status,added_by,added) VALUES(?,?,?,?,?,?,?,?,?)",
               ("muse-bilingual", "MUSE", "language", "CC BY-NC 4.0", "non-commercial", "https://github.com/facebookresearch/MUSE", "blocked", "system", T))
    db.execute("INSERT INTO policy_sources(key,name,apps,licence,licence_class,url,status,added_by,added) VALUES(?,?,?,?,?,?,?,?,?)",
               ("wikidata", "Wikidata", "facts", "CC0", "cc0", "https://www.wikidata.org/", "approved", "admin", T))
    prev = "0" * 64
    for i, (src, cls) in enumerate((("natural-earth", "public-domain"), ("muse-bilingual", "non-commercial")), 1):
        row = {"at": T, "app": "facts", "domain": "history", "action": "places", "title": "batch", "source_key": src, "licence_class": cls,
               "decision": "harvested", "items": 1, "new": 1, "merged": 0, "seconds": 0.1, "reason": "test", "budget_key": None, "turn_id": None,
               "policy_version": 1}
        h = hashlib.sha256((prev + json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)).encode("utf-8")).hexdigest()
        db.execute("INSERT INTO harvest_log(id,at,app,domain,action,title,source_key,licence_class,decision,items,new,merged,seconds,reason,budget_key,"
                   "turn_id,policy_version,prev_hash,hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (i, T, "facts", "history", "places", "batch", src, cls, "harvested", 1, 1, 0, 0.1, "test", None, None, 1, prev, h))
        prev = h

    def fact(dom, s, p, o, status, conf, fp=None):
        return db.execute("INSERT INTO facts(fingerprint,domain,subject,predicate,object,origin_app,status,confidence,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
                          (fp or qb_fingerprint(dom, s, p, o), dom, s, p, o, "facts", status, conf, T, T)).lastrowid

    def ev(fid, method, source, verdict="supports", url=None, quote=None, hid=None, app="facts"):
        db.execute("INSERT INTO evidence(fact_id,app,agent,method,source,url,quote,verdict,at,harvest_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (fid, app, "curator", method, source, url, quote, verdict, T, hid))
    a = fact("history", "Paris", "capital of", "France", "sourced", 0.75)
    ev(a, "reference", "Natural Earth populated places", url="https://www.naturalearthdata.com/downloads/", hid=1)
    b = fact("stem", "2 + 2", "equals", "4", "verified", 1.0)
    ev(b, "recompute", "exact arithmetic", app="stem")
    c = fact("history", "Lyon", "population", "513275", "sourced", 0.75, fp="0" * 64)          # tampered address
    ev(c, "reference", "Natural Earth populated places", hid=1)
    d = fact("language", "chat", "means", "cat", "sourced", 0.75)                               # restricted source + quote
    ev(d, "reference", "MUSE bilingual", quote="le chat — the cat", hid=2, app="language")
    e = fact("history", "Ada Lovelace", "date of birth", "1815-12-10", "corroborated", 0.9)     # status claims more than earned
    ev(e, "reference", "Natural Earth populated places", hid=1)
    f2 = fact("history", "Ada Lovelace", "date of death", "1852-11-27", "disputed", 0.3)
    ev(f2, "reference", "Natural Earth populated places", hid=1)
    ev(f2, "consistency", "STEM: Is the lifespan possible?", verdict="contradicts", app="stem")
    g = fact("history", "Ada Lovelace", "date of birth", "1915-12-10", "unsourced", 0.2)        # a second, conflicting birth date
    db.execute("INSERT INTO requests(fact_id,kind,payload,fingerprint,from_app,to_app,status,verdict,created,answered) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (f2, "lifespan", '{"born": 1815, "died": 1852}', "x1", "facts", "stem", "answered", "contradicts", T, T))
    db.commit()
    db.close()
    sh = sqlite3.connect(os.path.join(folder, "shards", "wikidata-dump-1.sqlite"))
    sh.executescript("""CREATE TABLE facts (fp BLOB PRIMARY KEY, s TEXT NOT NULL, p INTEGER NOT NULL, o TEXT NOT NULL, part INTEGER NOT NULL, row INTEGER NOT NULL) WITHOUT ROWID;
CREATE INDEX facts_s ON facts(s); CREATE TABLE predicates (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, rule TEXT);
CREATE TABLE parts (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, url TEXT, version TEXT, rows INTEGER NOT NULL DEFAULT 0, facts INTEGER NOT NULL DEFAULT 0,
 done INTEGER NOT NULL DEFAULT 0, started TEXT, finished TEXT);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL); CREATE TABLE links (fp BLOB PRIMARY KEY, url TEXT NOT NULL) WITHOUT ROWID;""")
    sh.execute("INSERT INTO predicates(id, name) VALUES(1, 'date of birth'), (2, 'country of citizenship'), (3, 'coordinates')")
    sh.execute("INSERT INTO parts(id, name, url, version, started) VALUES(1, '2026-10-27 part 0001 of 0146', "
               "'https://dumps.wikimedia.org/wikidatawiki/entities/latest-all.json.gz#0-1073741824', 'Tue, 27 Oct 2026', ?)", (T,))
    rows = [("Albert Einstein (Q937)", 1, "date of birth", "1879-03-14"), ("Albert Einstein (Q937)", 2, "country of citizenship", "Q183"),
            ("Somewhere (Q1)", 3, "coordinates", "123.0, 45.0")]
    for i, (s, pi, pn, o) in enumerate(rows):
        fpb = hashlib.sha256("|".join(["history", norm(s), norm(pn), norm(o)]).encode("utf-8")).digest()[:16]
        sh.execute("INSERT INTO facts VALUES(?,?,?,?,?,?)", (fpb, s, pi, o, 1, i))
    sh.execute("INSERT INTO meta VALUES('facts', '3')")
    sh.commit()
    sh.close()
    lb = sqlite3.connect(os.path.join(folder, "shards", "wikidata-dump-1.sqlite.labels"))
    lb.execute("CREATE TABLE labels (q INTEGER PRIMARY KEY, label TEXT NOT NULL)")
    lb.execute("INSERT INTO labels VALUES(183, 'Germany')")
    lb.commit()
    lb.close()


def self_test():
    import tempfile
    res = []

    def check(name, ok, detail=""):
        res.append((name, bool(ok), detail))
    with tempfile.TemporaryDirectory() as tmp:
        _fixture(tmp)
        before = {p: os.path.getmtime(p) for p in glob.glob(os.path.join(tmp, "**", "*"), recursive=True)}
        d = Data(tmp)
        st = {s["id"]: s["facts"] for s in d.stores()}
        check("finds the Commons and the bulk shard", st.get("commons") == 7 and st.get("b:wikidata-dump-1") == 3, st)
        allf = []
        page = d.list(limit=4)
        allf += page["facts"]
        while page["next"]:
            page = d.list(after=page["next"], limit=4)
            allf += page["facts"]
        check("lists every fact across stores, page by page", len(allf) == 10 and len({f["id"] for f in allf}) == 10, len(allf))
        check("Wikidata objects shown with their labels", any(f.get("object_label") == "Germany (Q183)" for f in allf))
        check("search: shared facts by any part of subject or object; bulk by subject prefix", [f["subject"] for f in d.list(q="aris")["facts"]] == ["Paris"]
              and [f["subject"] for f in d.list(store="b:wikidata-dump-1", q="albert")["facts"]] == ["Albert Einstein (Q937)"] * 2
              and d.list(q="50%_")["facts"] == [])
        V = {}
        for f in allf:
            full = d.fact(f["id"])
            V[(f["subject"], f["predicate"], f["object"])] = (audit(full, d), full)
        chk = lambda key, cid: next(c for c in V[key][0]["checks"] if c["id"] == cid)
        check("a sourced fact from an approved, public-domain source passes", V[("Paris", "capital of", "France")][0]["verdict"] == "pass",
              V[("Paris", "capital of", "France")][0])
        check("a recomputed fact passes with no outside source", V[("2 + 2", "equals", "4")][0]["verdict"] == "pass", V[("2 + 2", "equals", "4")][0])
        check("accuracy: an altered record fails the fingerprint check", chk(("Lyon", "population", "513275"), "A1")["result"] == "fail")
        check("legitimacy: a blocked, non-commercial source fails", chk(("chat", "means", "cat"), "L1")["result"] == "fail"
              and chk(("chat", "means", "cat"), "L2")["result"] == "fail")
        check("legitimacy: third-party wording from a restricted source fails", chk(("chat", "means", "cat"), "L4")["result"] == "fail")
        check("accuracy: a status the evidence does not earn fails", chk(("Ada Lovelace", "date of birth", "1815-12-10"), "A4")["result"] == "fail")
        check("accuracy: a contradicted fact fails 'evidence agrees'", chk(("Ada Lovelace", "date of death", "1852-11-27"), "A3")["result"] == "fail")
        check("accuracy: two different birth dates are flagged", chk(("Ada Lovelace", "date of birth", "1815-12-10"), "A6")["result"] == "warn")
        check("accuracy: an impossible lifespan fails", chk(("Ada Lovelace", "date of birth", "1915-12-10"), "A7")["result"] == "fail")
        check("accuracy: out-of-range coordinates fail", chk(("Somewhere (Q1)", "coordinates", "123.0, 45.0"), "A2")["result"] == "fail")
        ein = V[("Albert Einstein (Q937)", "date of birth", "1879-03-14")]
        check("bulk Wikidata fact: approved, fingerprint recomputes, exact record cited", ein[0]["verdict"] == "pass"
              and chk(("Albert Einstein (Q937)", "date of birth", "1879-03-14"), "C3")["detail"] == "https://www.wikidata.org/wiki/Q937", ein[0])
        check("legitimacy: the harvest log's hash chain verifies", d.chain()["ok"] and d.chain()["entries"] == 2)
        main, assoc = packets(V[("Ada Lovelace", "date of death", "1852-11-27")][1], d)
        check("UFCS packet: version, nucleus, semantic fingerprint and FUID", main["ufcs_version"] == "1.0" and main["nucleus"]["object"] == "1852-11-27"
              and main["semantic_fingerprint"] == ufcs_fingerprint("Ada Lovelace", "date of death", "1852-11-27") and len(main["fuid"]) == 64)
        check("the fact packet lists its sources, not its checks", [x["class"] for x in main["sources"]] == ["reference"], main["sources"])
        check("associated packets: one per evidence and one per cross-check", sorted(p["fact_type"] for p in assoc) ==
              ["attestation", "check_request", "consistency_check"], [p["fact_type"] for p in assoc])
        check("packets are deterministic", packets(V[("Ada Lovelace", "date of death", "1852-11-27")][1], d) == (main, assoc))
        bm, ba = packets(ein[1], d)
        check("bulk fact: packet cites Wikidata and the dump record", bm["sources"][0]["id"] == "wikidata" and ba[0]["fact_type"] == "source_record"
              and ba[0]["record"]["row"] == 1)
        rep = run_audit(d, sample=100)
        check("store-wide audit covers every fact and counts verdicts", rep["audited"] == 10 and sum(rep["verdicts"].values()) == 10
              and rep["verdicts"]["fail"] >= 5, rep["verdicts"])
        check("issues export as CSV", report_csv(rep).count("\n") == len(rep["issues"]) + 1)
        check("date reader: ISO, year-only, named months; rejects 31 February", parse_date("1879-03-14") == (1879, 3, 14) and parse_date("0500") == (500, None, None)
              and parse_date("10 December 1815") == (1815, 12, 10) and parse_date("1815-02-31") is None)
        check("source re-check compares Wikidata values", _same("1879-03-14", "+1879-03-14T00:00:00Z", "time") and _same("0500", "+0500-00-00T00:00:00Z", "time")
              and not _same("1879-03-15", "+1879-03-14T00:00:00Z", "time") and _same("83000", "+83000", "quantity"))
        app = App(tmp)
        det = app.detail(allf[0]["id"])
        check("web app: one fact's Fact Unit, UFCS packet, associated packets and audit", {"unit", "packet", "packets", "audit"} <= set(det))
        for db in [d.commons] + list(d.shards.values()) + d.labels:
            db.close()
        after = {p: os.path.getmtime(p) for p in glob.glob(os.path.join(tmp, "**", "*"), recursive=True)}
        check("read-only: no file in the fact folder was created or changed", before == after, set(after) ^ set(before))
    return res


# ------------------------------------------------------------------------------------------------ main
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="QueryBook Fact Auditor %s — legitimacy, accuracy and citation audit (read-only)" % VERSION)
    ap.add_argument("cmd", nargs="?", default="serve", choices=["serve", "audit", "self-test"])
    ap.add_argument("--data", help="the QueryBook fact folder (default: found automatically)")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--full", action="store_true", help="audit: every fact (default: a sample per store)")
    ap.add_argument("--sample", type=int, default=2000)
    ap.add_argument("--online", type=int, default=0, help="audit: re-check this many facts online")
    ap.add_argument("--out", help="audit: write the report here (default: reports/)")
    a = ap.parse_args(argv)
    if a.cmd == "self-test":
        res = self_test()
        for n, ok, det in res:
            print(("  [OK]   " if ok else "  [FAIL] ") + n + ("" if ok else "  — %s" % (det,)))
        print("\n  %d of %d checks passed" % (sum(1 for r in res if r[1]), len(res)))
        return 0 if all(r[1] for r in res) else 1
    folder = a.data or next(iter(candidate_folders()), None)
    if a.cmd == "audit":
        if not folder:
            print("No QueryBook fact folder found: pass --data <folder>.")
            return 2
        d = Data(folder)
        rep = run_audit(d, a.sample, a.full, a.online, progress=lambda s, n: print("  %s facts audited %s" % (format(n, ","), s), flush=True))
        path = a.out or save_report(rep)
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                json.dump(rep, f, indent=1, ensure_ascii=False)
        v = rep["verdicts"]
        print("Audited %s facts in %s s: %s pass, %s warn, %s fail. Harvest log %s. Report: %s"
              % (format(rep["audited"], ","), rep["seconds"], format(v["pass"], ","), format(v["warn"], ","), format(v["fail"], ","),
                 "intact" if rep["harvest_log"]["ok"] else "BROKEN", path))
        return 0
    app = App(a.data)
    Handler.app = app
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = "http://127.0.0.1:%d/" % a.port
    print("QueryBook Fact Auditor %s — %s\nFact folder: %s (read-only)\nPress Ctrl+C to stop." % (VERSION, url, app.data.folder if app.data else "not found yet — choose it in Settings"))
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
