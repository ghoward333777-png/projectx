"""qbbulk — bulk harvesting: whole open datasets, streamed by parallel agents into fact shards. The fast lane beside the
harvest teams.

The harvest teams ask sites for a page of items at a time, politely, once a turn — right for live sources, far too slow
for the open datasets that publish everything as one file. Here each dataset is one agent (its own process): it streams
the publisher's file — gzip, zip (read in place over HTTP ranges, nothing downloaded first), tar — row by row, turns
every row into facts by a fixed rule, and writes them into its own shard (one SQLite file per dataset in the Commons
folder's shards/), so agents never wait on each other. One agent writes about 80,000 facts a second; four run at once.

Rules kept, as everywhere in QueryBook:
  * only sources the admin approved in the policy registry (checked at the start and between batches); the master
    harvesting switch and the Stop button stop every agent between batches;
  * every fact names its dataset, the file part and the row it came from (provenance), and the file's version;
  * the harvest log (hash-chained) gets an entry for every million facts and at the end of each part;
  * no AI model: rows become facts by a written rule; computed facts (qbscaffold) name the rule they follow;
  * resumable: each part records the rows done in the same transaction as their facts; a stopped agent continues there.

Shard layout (compact — about 110 bytes a fact): facts(fp, s, p, o, part, row) keyed by the first 16 bytes of the same
SHA-256 fingerprint the Commons uses; predicates; parts (file, version, rows, facts, done); progress (for the rate);
links (a source page per fact, where there is one); slots (recurring-event editions expected and filled).

Run: python qbbulk.py run --commons <shared folder> [--datasets a,b] [--agents 4] [--max-rows N]
"""
import bz2, csv, datetime, gzip, io, json, os, sqlite3, sys, tarfile, time, urllib.error, urllib.parse, urllib.request, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qbcore as core  # noqa: E402
import qbscaffold as sc  # noqa: E402

VERSION = "1.0.0"
UA = "QueryBook-harvester/%s (personal research tool; bulk files, one stream per dataset)" % VERSION
BATCH = 50_000                     # facts per transaction
LOG_EVERY = 1_000_000              # a harvest-log entry per million new facts (and at the end of each part)
FOLDER = "shards"
AREA = {"language": "language", "stem": "stem", "facts": "history"}
CSV_MAX = 1 << 24
csv.field_size_limit(CSV_MAX)


# ------------------------------------------------------------------------------------------------ reading files
def _req(url, extra=None):
    return urllib.request.Request(url, headers=dict({"User-Agent": UA}, **(extra or {})))


def _open(url, timeout=120):
    """a streaming response (http/https) or a local file (file://, for tests)"""
    if url.startswith("file://"):
        return open(urllib.request.url2pathname(urllib.parse.urlsplit(url).path), "rb")
    return urllib.request.urlopen(_req(url), timeout=timeout)


class RangeFile(io.RawIOBase):
    """a remote file read by HTTP byte ranges, so a zip's members can be streamed without downloading the whole file"""

    def __init__(self, url):
        self.url, self.pos = url, 0
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA}), timeout=60) as r:
            self.size = int(r.headers["Content-Length"])
            self.version = r.headers.get("Last-Modified") or ""

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def readinto(self, b):
        if self.pos >= self.size:
            return 0
        end = min(self.size, self.pos + len(b)) - 1
        for attempt in range(4):
            try:
                with urllib.request.urlopen(_req(self.url, {"Range": "bytes=%d-%d" % (self.pos, end)}), timeout=120) as r:
                    data = r.read()
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        b[:len(data)] = data
        self.pos += len(data)
        return len(data)


def _seekable(url):
    if url.startswith("file://"):
        return open(urllib.request.url2pathname(urllib.parse.urlsplit(url).path), "rb")
    return io.BufferedReader(RangeFile(url), buffer_size=4 << 20)


def gz_lines(url):
    with _open(url) as r, gzip.GzipFile(fileobj=r) as g:
        for line in g:
            yield line.decode("utf-8", "replace").rstrip("\r\n")


def text_lines(url):
    with _open(url) as r:
        for line in io.TextIOWrapper(r, encoding="utf-8", errors="replace"):
            yield line.rstrip("\r\n")


def zip_lines(url, member_suffix):
    with zipfile.ZipFile(_seekable(url)) as z:
        name = next(n for n in z.namelist() if n.endswith(member_suffix))
        with z.open(name) as f:
            for line in io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace"):
                yield line.rstrip("\r\n")


def tar_member_lines(url, member_suffix, comp="bz2"):
    with _open(url) as r, tarfile.open(fileobj=r, mode="r|" + comp) as t:
        for m in t:
            if m.name.endswith(member_suffix):
                f, rest = t.extractfile(m), b""          # a streamed member cannot seek: split lines by hand
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    lines = (rest + chunk).split(b"\n")
                    rest = lines.pop()
                    for line in lines:
                        yield line.decode("utf-8", "replace").rstrip("\r")
                if rest:
                    yield rest.decode("utf-8", "replace").rstrip("\r")
                return


def cached(url, folder):
    """a whole file kept in the shard cache (for archives that must be read twice); resumed by byte range"""
    if url.startswith("file://"):
        return urllib.request.url2pathname(urllib.parse.urlsplit(url).path)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, os.path.basename(urllib.parse.urlsplit(url).path))
    if os.path.exists(path):
        return path
    part = path + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    with urllib.request.urlopen(_req(url, {"Range": "bytes=%d-" % have} if have else None), timeout=120) as r, open(part, "ab" if have else "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
    os.replace(part, path)
    return path


# ------------------------------------------------------------------------------------------------ datasets
class Dataset:
    """One open dataset. parts(): [(name, url)]; rows(part, url, state) yields raw rows; facts(part, row, state) turns one
    row into [(subject, predicate, object)]. Everything is a fixed rule: the same file gives the same facts."""
    key = title = app = source = licence = why = ""
    approx = ""
    rule = {}                    # predicate -> the rule it follows (computed datasets)

    def parts(self):
        return []

    def prepare(self, run):
        return {}

    def rows(self, part, url, state):
        return gz_lines(url)

    def facts(self, part, row, state):
        return []

    def link(self, subject):
        return None


class PubChem(Dataset):
    key, title, app, source = "pubchem-computed", "PubChem — NCBI-computed compound properties", "stem", "pubchem-computed"
    licence = "US government work (NLM); NCBI-computed properties only"
    why = "every compound's formula, mass and identifiers, computed by NCBI — the backbone of chemistry questions"
    approx = "about 120 million compounds × 4 properties"
    BASE = "https://ftp.ncbi.nlm.nih.gov/pubchem/Compound/Extras/"

    def parts(self):
        return [("CID-Mass", self.BASE + "CID-Mass.gz"), ("CID-InChI-Key", self.BASE + "CID-InChI-Key.gz"), ("CID-SMILES", self.BASE + "CID-SMILES.gz")]

    def facts(self, part, row, state):
        c = row.split("\t")
        s = "PubChem CID " + c[0]
        if part == "CID-Mass" and len(c) >= 3:
            return [(s, "molecular formula", c[1]), (s, "monoisotopic mass (Da)", c[2])]
        if part == "CID-InChI-Key" and len(c) >= 3:
            return [(s, "InChIKey", c[2])]
        if part == "CID-SMILES" and len(c) >= 2:
            return [(s, "SMILES", c[1])]
        return []

    def link(self, subject):
        return "https://pubchem.ncbi.nlm.nih.gov/compound/" + subject.rsplit(" ", 1)[-1]


class Taxonomy(Dataset):
    key, title, app, source = "ncbi-taxonomy", "NCBI Taxonomy — every named organism", "stem", "ncbi-taxonomy"
    licence = "US government work (NCBI)"
    why = "the classification of life: each organism's rank, its parent group and its common names"
    approx = "about 2.7 million taxa, about 10 million facts"
    URL = "https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz"

    def parts(self):
        return [("nodes", self.URL), ("common names", self.URL)]

    def prepare(self, run):
        path = cached(self.url_for("nodes"), run.cache)
        names, common = {}, []
        with tarfile.open(path, "r:gz") as t:
            for line in io.TextIOWrapper(t.extractfile("names.dmp"), encoding="utf-8", errors="replace"):
                c = [x.strip() for x in line.split("|")]
                if len(c) >= 4:
                    if c[3] == "scientific name":
                        names[c[0]] = c[2] or c[1]          # the unique name when the name is shared ("Morus <angiosperm>")
                    elif c[3] in ("genbank common name", "common name"):
                        common.append((c[0], c[1]))
        return {"path": path, "names": names, "common": common}

    def url_for(self, part):
        return self.URL

    def rows(self, part, url, state):
        if part == "common names":
            return iter(state["common"])
        def gen():
            with tarfile.open(state["path"], "r:gz") as t:
                for line in io.TextIOWrapper(t.extractfile("nodes.dmp"), encoding="utf-8", errors="replace"):
                    yield line
        return gen()

    def facts(self, part, row, state):
        names = state["names"]
        if part == "common names":
            tid, name = row
            return [(names[tid], "common name", name)] if tid in names else []
        c = [x.strip() for x in row.split("|")]
        if len(c) < 3 or c[0] not in names:
            return []
        s = names[c[0]]
        out = [(s, "NCBI Taxonomy ID", c[0])]
        if c[2] and c[2] != "no rank":
            out.append((s, "taxonomic rank", c[2]))
        if c[1] != c[0] and c[1] in names:
            out.append((s, "parent taxon", names[c[1]]))
        return out


class Weather(Dataset):
    key, title, app, source = "noaa-ghcn-daily", "NOAA GHCN-Daily — weather station observations", "stem", "noaa"
    licence = "Public domain (NOAA)"
    why = "measured daily temperatures, rain and snow at about 100,000 stations — quality-flagged readings left out"
    approx = "about 30–40 million observations a year"
    BASE = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/"
    ELEMENTS = {"TMAX": ("maximum temperature (°C)", 10), "TMIN": ("minimum temperature (°C)", 10), "PRCP": ("precipitation (mm)", 10),
                "SNOW": ("snowfall (mm)", 1), "SNWD": ("snow depth (mm)", 1)}

    def __init__(self, years=None):
        this = datetime.date.today().year
        self.years = years or list(range(this - 1, this - 11, -1))     # the last ten complete years, newest first

    def parts(self):
        return [("stations", self.BASE + "ghcnd-stations.txt")] + [("year %d" % y, self.BASE + "by_year/%d.csv.gz" % y) for y in self.years]

    def rows(self, part, url, state):
        return text_lines(url) if part == "stations" else gz_lines(url)

    def facts(self, part, row, state):
        if part == "stations":
            sid = row[0:11].strip()
            if not sid:
                return []
            s = "Weather station " + sid
            out = [(s, "name", row[41:71].strip()), (s, "latitude", row[12:20].strip()), (s, "longitude", row[21:30].strip())]
            if row[31:37].strip() not in ("", "-999.9"):
                out.append((s, "elevation (m)", row[31:37].strip()))
            if row[38:40].strip():
                out.append((s, "US state or Canadian province", row[38:40].strip()))
            return out
        c = row.split(",")
        if len(c) < 6 or c[2] not in self.ELEMENTS or c[5]:          # c[5]: quality flag — flagged readings are left out
            return []
        pred, div = self.ELEMENTS[c[2]]
        d = c[1]
        try:
            v = int(c[3])
        except ValueError:
            return []
        val = ("%.1f" % (v / div)) if div != 1 else str(v)
        return [("Weather station %s on %s-%s-%s" % (c[0], d[:4], d[4:6], d[6:8]), pred, val)]

    def link(self, subject):
        return "https://www.ncei.noaa.gov/cdo-web/datasets/GHCND/stations/GHCND:%s/detail" % subject.split()[2]


class GNIS(Dataset):
    key, title, app, source = "usgs-gnis", "USGS GNIS — official US place and feature names", "facts", "usgs-gnis"
    licence = "Public domain (USGS)"
    why = "every named place, stream, summit and building in the United States, with its state, county and coordinates"
    approx = "about 1 million features × 5 facts"
    URL = "https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/DomesticNames/DomesticNames_National_Text.zip"

    def parts(self):
        return [("domestic names", self.URL)]

    def rows(self, part, url, state):
        return zip_lines(url, "DomesticNames_National.txt")

    def facts(self, part, row, state):
        c = row.split("|")
        if len(c) < 17 or not c[0].isdigit():
            return []
        s = "%s (GNIS %s)" % (c[1], c[0])
        out = [(s, "feature class", c[2]), (s, "state", c[3])]
        if c[5]:
            out.append((s, "county", c[5]))
        if c[15] and c[16] and c[15] != "0":
            out += [(s, "latitude", c[15]), (s, "longitude", c[16])]
        return out

    def link(self, subject):
        return "https://edits.nationalmap.gov/apps/gaz-domestic/public/summary/" + subject.rsplit(" ", 1)[-1].rstrip(")")


class FoodData(Dataset):
    key, title, app, source = "usda-fooddata-central", "USDA FoodData Central — foods and their nutrients", "stem", "usda-fooddata-central"
    licence = "CC0 1.0 (USDA)"
    why = "what is in food: nutrients per 100 g for about two million foods"
    approx = "about 2 million foods, about 26 million nutrient values"
    URL = "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_csv_2026-04-30.zip"

    def parts(self):
        return [("foods", self.URL), ("nutrients", self.URL)]

    def prepare(self, run):
        nut = {}
        for i, r in enumerate(csv.reader(zip_lines(self.URL if not run.url_override(self.key, "nutrients") else run.url_override(self.key, "nutrients"), "/nutrient.csv"))):
            if i and len(r) >= 3:
                nut[r[0]] = "%s (%s per 100 g or 100 ml)" % (r[1], r[2].lower())
        return {"nutrients": nut}

    def rows(self, part, url, state):
        return csv.reader(zip_lines(url, "/food.csv" if part == "foods" else "/food_nutrient.csv"))

    def facts(self, part, row, state):
        if not row or not row[0].strip('"').isdigit():
            return []
        if part == "foods":
            s = "FoodData Central food %s" % row[0]
            out = [(s, "description", row[2])] if len(row) > 2 and row[2] else []
            if len(row) > 1 and row[1]:
                out.append((s, "data type", row[1].replace("_", " ")))
            return out
        if len(row) < 4 or row[2] not in state["nutrients"] or row[3] == "":
            return []
        return [("FoodData Central food %s" % row[1], state["nutrients"][row[2]], row[3])]

    def link(self, subject):
        return "https://fdc.nal.usda.gov/food-details/%s/nutrients" % subject.rsplit(" ", 1)[-1]


class Tatoeba(Dataset):
    key, title, app, source = "tatoeba-cc0", "Tatoeba — example sentences marked CC0", "language", "tatoeba-cc0"
    licence = "CC0 1.0 (only the sentences their authors marked CC0)"
    why = "real example sentences in hundreds of languages, for the Language Builder"
    approx = "about 560,000 sentences"
    URL = "https://downloads.tatoeba.org/exports/sentences_CC0.tar.bz2"

    def parts(self):
        return [("sentences", self.URL)]

    def rows(self, part, url, state):
        return tar_member_lines(url, "sentences_CC0.csv")

    def facts(self, part, row, state):
        c = row.split("\t")
        if len(c) < 3 or not c[0].isdigit() or not c[2]:
            return []
        s = "Tatoeba sentence " + c[0]
        return [(s, "text", c[2]), (s, "language (ISO 639-3)", c[1])]

    def link(self, subject):
        return "https://tatoeba.org/en/sentences/show/" + subject.rsplit(" ", 1)[-1]


class Calendar(Dataset):
    key, title, app, source = "calendar-scaffold", "Calendar scaffold — computed dates, holidays, seasons, election days", "facts", None
    licence = "QueryBook's own computation from published rules"
    why = "what can be known in advance: every date's weekday, Easter, equinoxes and solstices, US holidays and election days"
    approx = "about 450,000 facts for 1600–2200"

    def parts(self):
        return [("years", ""), ("dates", "")]

    def rows(self, part, url, state):
        return iter(range(sc.FIRST_YEAR, sc.LAST_YEAR + 1))

    def facts(self, part, row, state):
        out = sc.year_facts(row) if part == "years" else sc.date_facts(row)
        for s, p, o, rule in out:
            self.rule.setdefault(p, rule)
        return [(s, p, o) for s, p, o, rule in out]


class Series(Dataset):
    key, title, app, source = "wikidata-series", "Recurring events — the scaffold's slots filled from Wikidata", "facts", "wikidata"
    licence = "CC0 1.0 (Wikidata)"
    why = "who won and where it was held, for every edition of the major recurring events — one query per series"
    approx = "a few thousand facts; the slots show which editions are still open"
    ENDPOINT = "https://query.wikidata.org/sparql"
    GAP_S = 60                         # Wikidata's query service: one query a minute at most (its current limit)

    def parts(self):
        return [(k, self.ENDPOINT) for k in sc.SERIES]

    def rows(self, part, url, state):
        last = state.get("_last", 0)
        if time.time() - last < self.GAP_S and last:
            time.sleep(self.GAP_S - (time.time() - last))
        if url.startswith("file://"):
            with _open(url) as r:
                body = json.loads(r.read())
        else:
            q = urllib.parse.urlencode({"query": sc.query(part), "format": "json"})
            for attempt in range(5):
                try:
                    with urllib.request.urlopen(_req(url + "?" + q, {"Accept": "application/sparql-results+json"}), timeout=120) as r:
                        body = json.loads(r.read())
                    break
                except urllib.error.HTTPError as e:
                    if e.code not in (429, 503) or attempt == 4:
                        raise
                    time.sleep(max(self.GAP_S, int(e.headers.get("Retry-After") or 0)))
        state["_last"] = time.time()
        return iter(sc.slot_facts(part, body["results"]["bindings"]))

    def facts(self, part, row, state):
        s, p, o, year, url = row
        state.setdefault("_links", {})[s] = url
        state.setdefault("_filled", set()).add((part, year))
        return [(s, p, o)]


def catalog():
    return {d.key: d for d in (PubChem(), Taxonomy(), Weather(), GNIS(), FoodData(), Tatoeba(), Calendar(), Series())}


# ------------------------------------------------------------------------------------------------ the shard
SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (fp BLOB PRIMARY KEY, s TEXT NOT NULL, p INTEGER NOT NULL, o TEXT NOT NULL, part INTEGER NOT NULL,
  row INTEGER NOT NULL) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS facts_s ON facts(s);
CREATE TABLE IF NOT EXISTS predicates (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, rule TEXT);
CREATE TABLE IF NOT EXISTS parts (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, url TEXT, version TEXT, rows INTEGER NOT NULL DEFAULT 0,
  facts INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0, started TEXT, finished TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS progress (at REAL PRIMARY KEY, facts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS links (fp BLOB PRIMARY KEY, url TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS slots (series TEXT NOT NULL, year INTEGER NOT NULL, filled INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (series, year)) WITHOUT ROWID;
"""


def shard_path(commons_folder, key):
    return os.path.join(commons_folder, FOLDER, key + ".sqlite")


def fp(domain, s, p, o):
    return bytes.fromhex(core.fingerprint(domain, s, p, o))[:16]


class Shard:
    def __init__(self, commons_folder, key):
        os.makedirs(os.path.join(commons_folder, FOLDER), exist_ok=True)
        self.db = sqlite3.connect(shard_path(commons_folder, key), timeout=60)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self.preds = {n: i for i, n in self.db.execute("SELECT id, name FROM predicates")}

    def meta(self, key, default=None):
        r = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return json.loads(r[0]) if r else default

    def set_meta(self, key, value):
        self.db.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, json.dumps(value)))

    def part(self, name, url):
        self.db.execute("INSERT OR IGNORE INTO parts(name, url) VALUES(?, ?)", (name, url))
        return self.db.execute("SELECT id, rows, facts, done FROM parts WHERE name = ?", (name,)).fetchone()

    def pred(self, name, rule=None):
        if name not in self.preds:
            self.db.execute("INSERT OR IGNORE INTO predicates(name, rule) VALUES(?, ?)", (name, rule))
            self.preds[name] = self.db.execute("SELECT id FROM predicates WHERE name = ?", (name,)).fetchone()[0]
        return self.preds[name]

    def write(self, part_id, rows, rows_done, links=None):
        """one transaction: the facts, the part's progress and the running total — a restart resumes exactly here"""
        before = self.db.total_changes
        self.db.executemany("INSERT OR IGNORE INTO facts(fp, s, p, o, part, row) VALUES(?,?,?,?,?,?)", rows)
        new = self.db.total_changes - before
        if links:
            self.db.executemany("INSERT OR IGNORE INTO links(fp, url) VALUES(?, ?)", links)
        self.db.execute("UPDATE parts SET rows = ?, facts = facts + ? WHERE id = ?", (rows_done, new, part_id))
        total = (self.meta("facts", 0) or 0) + new
        self.set_meta("facts", total)
        now = time.time()
        self.db.execute("INSERT OR REPLACE INTO progress(at, facts) VALUES(?, ?)", (now, total))
        self.db.execute("DELETE FROM progress WHERE at < ?", (now - 2 * 86400,))
        self.db.commit()
        return new


# ------------------------------------------------------------------------------------------------ one agent
class Run:
    """what an agent needs: the Commons (registry, master switch, harvest log), its shard, the stop signals"""

    def __init__(self, commons_folder, ds, max_rows=None):
        import qbcommons as cm
        self.folder, self.ds, self.max_rows = commons_folder, ds, max_rows
        self.commons = cm.Commons(commons_folder, ds.app)
        self.commons.registry.ensure()            # the researched sources and the admin's decisions (never overrides a decision)
        self.cache = os.path.join(commons_folder, FOLDER, "_cache")
        self.stopfile = os.path.join(commons_folder, FOLDER, "_runner.stop")

    def url_override(self, key, part):
        """tests and mirrors: the setting bulk:url:<dataset>:<part> replaces the publisher's address"""
        return self.commons.setting("bulk:url:%s:%s" % (key, part))

    def stopped(self):
        import qbharvest as hv
        if os.path.exists(self.stopfile):
            return "stopped from the Control Panel"
        if not hv.master_running(self.commons):
            return "harvesting switched off (master switch)"
        if self.ds.source:
            ok, cls, why = self.commons.registry.check(self.ds.source)
            if not ok:
                return "source not approved in the policy registry: " + why
        return None

    def log(self, part, a, b, items, new, secs, decision="harvested", reason=None):
        cls = self.commons.registry.check(self.ds.source)[1] if self.ds.source else "own-computation"
        with self.commons.store.write() as db:
            self.commons.harvest_log.write(db, self.ds.app, "bulk:" + self.ds.key, "%s — %s: rows %d–%d" % (self.ds.title, part, a + 1, b),
                                           self.ds.source or "computed", cls, decision, reason or self.ds.why, items, new, max(0, items - new), round(secs, 2))


def run_dataset(commons_folder, key, max_rows=None):
    """One agent: stream every part of one dataset into its shard. Returns a summary."""
    ds = catalog()[key]
    run = Run(commons_folder, ds, max_rows)
    sh = Shard(commons_folder, key)
    domain = AREA[ds.app]
    sh.set_meta("state", "running"); sh.set_meta("pid", os.getpid()); sh.set_meta("started", core.now_iso()); sh.set_meta("error", None)
    sh.db.commit()
    why = run.stopped()
    if why:
        sh.set_meta("state", "blocked" if "registry" in why else "stopped"); sh.set_meta("error", why); sh.db.commit()
        if "registry" in why:
            run.log("all parts", 0, 0, 0, 0, 0, "blocked", why)
        return {"dataset": key, "state": "blocked" if "registry" in why else "stopped", "why": why}
    total_new, t_start = 0, time.time()
    try:
        state = ds.prepare(run)
        for name, url in ds.parts():
            url = run.url_override(key, name) or url
            pid, done_rows, pfacts, done = sh.part(name, url)
            if done:
                continue
            sh.db.execute("UPDATE parts SET started = coalesce(started, ?), version = ? WHERE id = ?", (core.now_iso(), _version(url), pid))
            sh.db.commit()
            row_no, buf, links, t0, log_from, log_new = 0, [], [], time.time(), done_rows, 0
            limit = None if max_rows is None else done_rows + max_rows
            for raw in ds.rows(name, url, state):
                if row_no < done_rows:                  # resume: skip what an earlier run already saved
                    row_no += 1
                    continue
                for s, p, o in ds.facts(name, raw, state):
                    if s and o:
                        f = fp(domain, s, p, o)
                        buf.append((f, s, sh.pred(p, ds.rule.get(p)), o, pid, row_no))
                        if state.get("_links") and s in state["_links"]:
                            links.append((f, state["_links"][s]))
                row_no += 1
                if len(buf) >= BATCH:
                    new = sh.write(pid, buf, row_no, links)
                    total_new += new; log_new += new; buf, links = [], []
                    if log_new >= LOG_EVERY:
                        run.log(name, log_from, row_no, row_no - log_from, log_new, time.time() - t0)
                        log_from, log_new, t0 = row_no, 0, time.time()
                    why = run.stopped()
                    if why:
                        raise _Stop(why)
                if limit is not None and row_no >= limit:
                    break
            new = sh.write(pid, buf, row_no, links)
            total_new += new; log_new += new
            for series, year in state.pop("_filled", set()):
                sh.db.execute("INSERT INTO slots(series, year, filled) VALUES(?, ?, 1) ON CONFLICT(series, year) DO UPDATE SET filled = 1", (series, year))
            if key == "wikidata-series":
                for y in sc.expected_years(name):
                    sh.db.execute("INSERT OR IGNORE INTO slots(series, year, filled) VALUES(?, ?, 0)", (name, y))
            finished = limit is None or row_no < limit
            if finished:
                sh.db.execute("UPDATE parts SET done = 1, finished = ? WHERE id = ?", (core.now_iso(), pid))
            sh.db.commit()
            run.log(name, log_from, row_no, row_no - log_from, log_new, time.time() - t0)
            state.pop("_links", None)
            why = run.stopped()
            if why:
                raise _Stop(why)
        all_done = all(d for (d,) in sh.db.execute("SELECT done FROM parts"))
        sh.set_meta("state", "done" if all_done else "paused"); sh.set_meta("finished", core.now_iso()); sh.db.commit()
        return {"dataset": key, "state": "done" if all_done else "paused", "new": total_new, "seconds": round(time.time() - t_start, 1)}
    except _Stop as e:
        sh.set_meta("state", "stopped"); sh.set_meta("error", str(e)); sh.db.commit()
        return {"dataset": key, "state": "stopped", "why": str(e), "new": total_new}
    except Exception as e:
        sh.set_meta("state", "failed"); sh.set_meta("error", "%s: %s" % (type(e).__name__, str(e)[:300])); sh.db.commit()
        return {"dataset": key, "state": "failed", "why": str(e)[:300], "new": total_new}
    finally:
        sh.db.close()


class _Stop(Exception):
    pass


def _version(url):
    """the file's version as its publisher states it (Last-Modified), so every fact can be traced to one edition"""
    if not url.startswith("http"):
        return url and "local file"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA}), timeout=30) as r:
            return r.headers.get("Last-Modified") or ""
    except Exception:
        return ""


def _agent(args):
    folder, key, max_rows = args
    return run_dataset(folder, key, max_rows)


def run(commons_folder, keys=None, agents=4, max_rows=None):
    """the runner: up to `agents` datasets at once, one process each; heartbeat in shards/_runner.json"""
    import multiprocessing
    keys = keys or list(catalog())
    folder = os.path.join(commons_folder, FOLDER)
    os.makedirs(folder, exist_ok=True)
    stop = os.path.join(folder, "_runner.stop")
    if os.path.exists(stop):
        os.remove(stop)
    hb = os.path.join(folder, "_runner.json")
    results = []

    def beat(note):
        with open(hb + ".tmp", "w") as f:
            json.dump({"heartbeat": time.time(), "pid": os.getpid(), "agents": agents, "datasets": keys, "note": note, "results": results}, f)
        os.replace(hb + ".tmp", hb)
    beat("starting")
    with multiprocessing.Pool(max(1, min(agents, len(keys)))) as pool:
        pending = pool.imap_unordered(_agent, [(commons_folder, k, max_rows) for k in keys])
        while True:
            try:
                results.append(pending.next(timeout=2))
                beat("%d of %d datasets finished this run" % (len(results), len(keys)))
            except multiprocessing.TimeoutError:
                beat("running")
            except StopIteration:
                break
    beat("finished")
    return results


# ------------------------------------------------------------------------------------------------ reading shards
def _ro(path):
    return sqlite3.connect("file:%s?mode=ro" % urllib.request.pathname2url(path), uri=True, timeout=5)


def status(commons_folder, commons=None):
    """every dataset: approval, state, facts, rows per part, rate, size; the runner's heartbeat"""
    out, folder = [], os.path.join(commons_folder, FOLDER)
    now = time.time()
    for key, ds in catalog().items():
        approved, why = True, ""
        if ds.source and commons is not None:
            approved, cls, why = commons.registry.check(ds.source)
        row = {"key": key, "title": ds.title, "app": ds.app, "area": AREA[ds.app], "source": ds.source or "computed", "licence": ds.licence,
               "why": ds.why, "approx": ds.approx, "approved": approved, "approval": why, "state": "not started", "facts": 0,
               "last_minute": 0, "last_hour": 0, "bytes": 0, "parts": [], "error": None}
        p = shard_path(commons_folder, key)
        if os.path.exists(p):
            row["bytes"] = sum(os.path.getsize(p + x) for x in ("", "-wal") if os.path.exists(p + x))
            try:
                db = _ro(p)
                meta = {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM meta")}
                row.update(state=meta.get("state", "not started"), facts=meta.get("facts", 0) or 0, error=meta.get("error"))
                for secs, k in ((60, "last_minute"), (3600, "last_hour")):
                    r = db.execute("SELECT facts FROM progress WHERE at <= ? ORDER BY at DESC LIMIT 1", (now - secs,)).fetchone()
                    first = db.execute("SELECT min(at) FROM progress").fetchone()[0]
                    base = r[0] if r else (0 if first is None or first > now - secs else row["facts"])
                    row[k] = max(0, row["facts"] - base)
                row["parts"] = [dict(zip(("name", "rows", "facts", "done", "version", "finished"), r))
                                for r in db.execute("SELECT name, rows, facts, done, version, finished FROM parts ORDER BY id")]
                if key == "wikidata-series":
                    row["slots"] = [dict(zip(("series", "expected", "filled"), r)) for r in
                                    db.execute("SELECT series, count(*), sum(filled) FROM slots GROUP BY series ORDER BY series")]
                db.close()
            except sqlite3.Error as e:
                row["error"] = "shard unreadable: %s" % e
            if row["state"] == "running" and not _alive(commons_folder):
                row["state"] = "paused"
        out.append(row)
    rs = {}
    try:
        with open(os.path.join(folder, "_runner.json")) as f:
            rs = json.load(f)
    except (OSError, ValueError):
        pass
    rs["alive"] = bool(rs) and now - rs.get("heartbeat", 0) < 30 and rs.get("note") != "finished"
    return {"version": VERSION, "datasets": out, "runner": rs, "total": sum(d["facts"] for d in out),
            "last_minute": sum(d["last_minute"] for d in out), "last_hour": sum(d["last_hour"] for d in out),
            "bytes": sum(d["bytes"] for d in out)}


def _alive(commons_folder):
    try:
        with open(os.path.join(commons_folder, FOLDER, "_runner.json")) as f:
            rs = json.load(f)
        return time.time() - rs.get("heartbeat", 0) < 30 and rs.get("note") != "finished"
    except (OSError, ValueError):
        return False


def by_area(commons_folder):
    """{area: {"facts", "last_minute", "last_hour"}} for the live ticker (cheap: shard meta only)"""
    out = {}
    for d in status(commons_folder)["datasets"]:
        a = out.setdefault(d["area"], {"facts": 0, "last_minute": 0, "last_hour": 0})
        for k in a:
            a[k] += d[k]
    return out


def search(commons_folder, text, limit=50):
    """facts whose subject starts with `text` (exact case first, then capitalised), across every shard"""
    out = []
    text = (text or "").strip()
    if not text:
        return out
    for key, ds in catalog().items():
        p = shard_path(commons_folder, key)
        if not os.path.exists(p) or len(out) >= limit:
            continue
        db = _ro(p)
        for t in dict.fromkeys((text, text[:1].upper() + text[1:])):
            for s, pr, o, part, row in db.execute(
                    "SELECT f.s, pr.name, f.o, pa.name, f.row FROM facts f JOIN predicates pr ON pr.id = f.p JOIN parts pa ON pa.id = f.part "
                    "WHERE f.s >= ? AND f.s < ? LIMIT ?", (t, t + "￿", limit - len(out))):
                out.append({"subject": s, "predicate": pr, "object": o, "dataset": ds.title, "source": ds.source or "computed",
                            "licence": ds.licence, "provenance": "%s, row %d" % (part, row + 1), "link": ds.link(s), "status": "computed" if not ds.source else "sourced"})
        db.close()
    return out[:limit]


# ------------------------------------------------------------------------------------------------ control (the Control Panel)
def start(commons, keys, agents, passphrase, program_dir):
    """start the bulk runner (admin): a separate program, so the applications stay responsive"""
    import subprocess
    commons.approvals._require(passphrase or "")
    if _alive(commons.folder):
        return {"summary": "bulk harvesting is already running", **status(commons.folder, commons)}
    keys = [k for k in (keys or list(catalog())) if k in catalog()]
    if not keys:
        raise ValueError("Choose at least one dataset.")
    agents = max(1, min(int(agents or 4), 16))
    path = os.path.join(program_dir, "qbbulk.py")
    kw = {"creationflags": 0x00000008 | 0x00000200} if os.name == "nt" else {"start_new_session": True}
    subprocess.Popen([sys.executable, path, "run", "--commons", commons.folder, "--datasets", ",".join(keys), "--agents", str(agents)],
                     cwd=program_dir, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    with commons.store.write() as db:
        commons.agent_log(db, "engine", "Bulk harvesting started: %s (%d agents)" % (", ".join(keys), agents))
    return {"summary": "bulk harvesting is starting: %d dataset(s), %d agent(s)" % (len(keys), agents), **status(commons.folder, commons)}


def stop(commons):
    folder = os.path.join(commons.folder, FOLDER)
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "_runner.stop"), "w").close()
    return {"summary": "every bulk agent stops after its current batch (it resumes there next time)", **status(commons.folder, commons)}


def add_routes(api, commons, program_dir):
    commons.registry.ensure()
    @api.get("/api/bulk")
    def bulk_status(p):
        return status(commons.folder, commons)

    @api.post("/api/bulk/start")
    def bulk_start(p):
        try:
            return start(commons, p.get("datasets"), p.get("agents") or 4, p.get("passphrase"), program_dir)
        except ValueError as e:
            raise core.UserError(str(e))

    @api.post("/api/bulk/stop")
    def bulk_stop(p):
        return stop(commons)

    @api.get("/api/bulk/search")
    def bulk_search(p):
        return {"facts": search(commons.folder, p.get("q") or "", int(p.get("limit") or 50))}


# ------------------------------------------------------------------------------------------------ self-test
def self_test():
    """every reader and rule on small local files in the publishers' own formats; resume; stop; registry block; ticker"""
    import shutil, tempfile
    import qbcommons as cm
    out = []
    ok = lambda n, c, d="": out.append((n, bool(c), d))
    out += [("scaffold: " + n, g, "") for n, g in sc.self_test()]
    tmp = tempfile.mkdtemp()
    try:
        url = lambda name: "file://" + urllib.request.pathname2url(os.path.join(tmp, name))
        with gzip.open(os.path.join(tmp, "CID-Mass.gz"), "wt") as f:
            f.write("".join("%d\tC%dH%dO\t%d.0\t%d.0\n" % (i, i, 2 * i, 16 + 14 * i, 16 + 14 * i) for i in range(1, 3001)))
        with gzip.open(os.path.join(tmp, "CID-SMILES.gz"), "wt") as f:
            f.write("2244\tCC(=O)OC1=CC=CC=C1C(=O)O\n")
        with gzip.open(os.path.join(tmp, "CID-InChI-Key.gz"), "wt") as f:
            f.write("2244\tInChI=1S/C9H8O4\tBSYNRYMUTXBXSQ-UHFFFAOYSA-N\n")
        with zipfile.ZipFile(os.path.join(tmp, "gnis.zip"), "w") as z:
            z.writestr("Text/DomesticNames_National.txt", "﻿feature_id|feature_name|feature_class|state_name|state_numeric|county_name|county_numeric|map_name|"
                       "date_created|date_edited|bgn_type|bgn_authority|bgn_date|prim_lat_dms|prim_long_dms|prim_lat_dec|prim_long_dec\r\n"
                       "399|Agua Sal Creek|Stream|Arizona|04|Apache|001|Fire Dance Mesa|02/08/1980|||||362740N|1092842W|36.4611122|-109.4784394\r\n")
        with gzip.open(os.path.join(tmp, "2024.csv.gz"), "wt") as f:
            f.write("USW00094728,20240101,TMAX,72,,,W,\nUSW00094728,20240101,TMIN,-11,,,W,\nUSW00094728,20240102,PRCP,25,,X,W,\nUSW00094728,20240101,AWND,30,,,W,\n")
        with open(os.path.join(tmp, "stations.txt"), "w") as f:
            f.write("USW00094728  40.7789  -73.9692   39.6 NY NEW YORK CNTRL PK TWR                 HCN 72506\n")
        with open(os.path.join(tmp, "nobel.json"), "w") as f:
            json.dump({"results": {"bindings": [{"year": {"value": "1921"}, "valueLabel": {"value": "Albert Einstein"},
                                                 "item": {"value": "http://www.wikidata.org/entity/Q937"}}]}}, f)
        with tarfile.open(os.path.join(tmp, "cc0.tar.bz2"), "w:bz2") as t:
            data = "330998\teng\tChildren who spend more time outdoors have a lower risk of myopia.\t2019-01-12\n1\tfra\tBonjour.\t2019-01-12\n".encode()
            ti = tarfile.TarInfo("sentences_CC0.csv"); ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
        cf = os.path.join(tmp, "commons")
        c = cm.Commons(cf, "stem")
        c.registry.ensure()
        for k, v in (("bulk:url:pubchem-computed:CID-Mass", url("CID-Mass.gz")), ("bulk:url:pubchem-computed:CID-SMILES", url("CID-SMILES.gz")),
                     ("bulk:url:pubchem-computed:CID-InChI-Key", url("CID-InChI-Key.gz")), ("bulk:url:usgs-gnis:domestic names", url("gnis.zip"))):
            c.set_setting(k, v)
        for s in ("pubchem-computed", "usgs-gnis", "noaa", "wikidata"):
            ok("dataset source %s is approved in the registry" % s, c.registry.check(s)[0])
        global BATCH
        old, BATCH = BATCH, 1000
        try:
            r1 = run_dataset(cf, "pubchem-computed", max_rows=1500)
            r2 = run_dataset(cf, "pubchem-computed")
        finally:
            BATCH = old
        st = {d["key"]: d for d in status(cf, c)["datasets"]}
        pc = st["pubchem-computed"]
        ok("PubChem: formula and mass per compound, plus SMILES and InChIKey; a capped run resumes where it stopped (no fact twice)",
           r1["state"] == "paused" and r2["state"] == "done" and pc["facts"] == 3000 * 2 + 2 and pc["parts"][0]["rows"] == 3000, (r1, r2, pc["facts"]))
        hits = search(cf, "PubChem CID 2244")
        ok("search: a compound's facts with dataset, row and the PubChem page", any(h["predicate"] == "SMILES" and h["link"].endswith("/compound/2244")
                                                                                       and h["provenance"].startswith("CID-SMILES, row 1") for h in hits), hits[:2])
        logged = c.store.query("SELECT action, decision, new, source_key FROM harvest_log WHERE action LIKE 'bulk:%'")
        ok("harvest log: each part's facts are logged with the source (hash chain intact)", logged and all(r["source_key"] == "pubchem-computed" for r in logged)
           and c.harvest_log.verify().get("ok", True) is not False, logged[:3])
        g = run_dataset(cf, "usgs-gnis")
        hits = search(cf, "Agua Sal Creek")
        ok("GNIS: a zip read in place, the place's class, state, county and coordinates", g["state"] == "done" and
           {h["predicate"] for h in hits} == {"feature class", "state", "county", "latitude", "longitude"}, hits)
        w = Weather([2024])
        rows = [f for line in gz_lines(url("2024.csv.gz")) for f in w.facts("year 2024", line, {})]
        ok("weather: tenths of a degree become °C, flagged readings and other elements are left out",
           rows == [("Weather station USW00094728 on 2024-01-01", "maximum temperature (°C)", "7.2"),
                    ("Weather station USW00094728 on 2024-01-01", "minimum temperature (°C)", "-1.1")], rows)
        stn = w.facts("stations", next(text_lines(url("stations.txt"))), {})
        ok("weather: stations get their name, coordinates, elevation and state", ("Weather station USW00094728", "name", "NEW YORK CNTRL PK TWR") in stn
           and ("Weather station USW00094728", "elevation (m)", "39.6") in stn, stn)
        tt = Tatoeba()
        rows = [f for line in tar_member_lines(url("cc0.tar.bz2"), "sentences_CC0.csv") for f in tt.facts("sentences", line, {})]
        ok("Tatoeba: CC0 sentences streamed from the tar.bz2, with their language", rows[:2] == [("Tatoeba sentence 330998", "text",
           "Children who spend more time outdoors have a lower risk of myopia."), ("Tatoeba sentence 330998", "language (ISO 639-3)", "eng")]
           and len(rows) == 4, rows)
        se = Series()
        se.GAP_S = 0
        f = [x for row in se.rows("nobel-physics", url("nobel.json"), {}) for x in se.facts("nobel-physics", row, {})]
        ok("series: a slot is filled only from the source's answer", f == [("Nobel Prize in Physics 1921", "laureate", "Albert Einstein")], f)
        cal = Calendar()
        yf = cal.facts("years", 2024, {})
        ok("calendar: computed facts name their rule", ("Year 2024", "Easter Sunday (Western churches)", "2024-03-31") in yf and cal.rule.get("date"), yf[:3])
        with c.store.write() as db:
            db.execute("UPDATE policy_sources SET status = 'blocked' WHERE key = 'usgs-gnis'")
        b = run_dataset(cf, "usgs-gnis")
        ok("a source blocked in the registry is not harvested (and the refusal is logged)", b["state"] == "blocked"
           and c.store.scalar("SELECT count(*) FROM harvest_log WHERE action = 'bulk:usgs-gnis' AND decision = 'blocked'", default=0) == 1, b)
        ar = by_area(cf)
        ok("ticker: shard facts counted per area", ar["stem"]["facts"] == 6002 and ar["history"]["facts"] == 5, ar)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run")
    r.add_argument("--commons", required=True)
    r.add_argument("--datasets", default="")
    r.add_argument("--agents", type=int, default=4)
    r.add_argument("--max-rows", type=int, default=None)
    s = sp.add_parser("status")
    s.add_argument("--commons", required=True)
    sp.add_parser("self-test")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        for res in run(a.commons, [k for k in a.datasets.split(",") if k] or None, a.agents, a.max_rows):
            print(json.dumps(res))
    elif a.cmd == "status":
        print(json.dumps(status(a.commons), indent=1, default=str))
    else:
        res = self_test()
        for n, g, d in res:
            print(("  [OK]   " if g else "  [FAIL] ") + n + ("" if g else "  — %s" % (d,)))
        print("\n  %d of %d checks passed" % (sum(1 for x in res if x[1]), len(res)))
        return 0 if all(x[1] for x in res) else 1


if __name__ == "__main__":
    sys.exit(main())
