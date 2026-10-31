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
import bz2, csv, datetime, gzip, hashlib, io, json, operator, os, re, shutil, sqlite3, sys, tarfile, time, urllib.error, urllib.parse, urllib.request, zipfile, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qbcore as core  # noqa: E402
import qbscaffold as sc  # noqa: E402
import qbkeystone as ks  # noqa: E402

VERSION = "1.0.0"
UA = "QueryBook-harvester/%s (+https://github.com/ghoward333777-png/projectx; personal research tool; bulk files, one stream per dataset)" % VERSION
BATCH = 500_000                    # facts per transaction (bigger batches touch each page of the fingerprint B-tree less often)
CACHE_MB = 128                     # SQLite page cache per agent
LOG_EVERY = 1_000_000              # a harvest-log entry per million new facts (and at the end of each part)
FOLDER = "shards"
MAX_AGENTS = min(64, max(16, os.cpu_count() or 1))   # one process per agent: up to every core of the machine
MIN_FREE_GB = 10                   # every agent stops between batches when the disk has less free than this
AREA = {"language": "language", "stem": "stem", "facts": "history"}
READ_BUFFER = 1 << 20              # bytes read from a decompressed stream at a time
CSV_MAX = 1 << 24
csv.field_size_limit(CSV_MAX)


# ------------------------------------------------------------------------------------------------ reading files
class Meter:
    """how far the current part has got, on the publisher's own scale: compressed bytes read of the file's size, or rows of a
    known count. One per agent process (each agent is its own process), read into the shard's meta with every batch."""

    def __init__(self):
        self.start(0, "bytes")

    def start(self, total, unit="bytes"):
        self.total, self.unit, self.done = int(total or 0), unit, 0


METER = Meter()


class _Count(io.RawIOBase):
    """a raw stream that counts the bytes read through it into METER"""

    def __init__(self, raw):
        self.raw = raw

    def readable(self):
        return True

    def readinto(self, b):
        n = self.raw.readinto(b)
        METER.done += n or 0
        return n


def _size(r, url):
    if url.startswith("file://"):
        return os.fstat(r.fileno()).st_size
    return int(r.headers.get("Content-Length") or 0)


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
    with _open(url) as r, gzip.GzipFile(fileobj=_Count(r)) as g:
        METER.start(_size(r, url))
        for line in io.BufferedReader(g, READ_BUFFER):      # a big buffer: 1.4x faster line splitting than GzipFile's own
            yield line.decode("utf-8", "replace").rstrip("\r\n")


def text_lines(url):
    with _open(url) as r:
        METER.start(_size(r, url))
        for line in io.TextIOWrapper(io.BufferedReader(_Count(r)), encoding="utf-8", errors="replace"):
            yield line.rstrip("\r\n")


def zip_lines(url, member_suffix):
    with zipfile.ZipFile(_seekable(url)) as z:
        name = next(n for n in z.namelist() if n.endswith(member_suffix))
        size = z.getinfo(name).compress_size
        METER.start(size)
        with z.open(name) as f:
            for i, line in enumerate(io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace")):
                if not i & 0x3FFF:                      # the member's compressed bytes still to read
                    METER.done = size - getattr(f, "_compress_left", size)
                yield line.rstrip("\r\n")
            METER.done = size


def tar_member_lines(url, member_suffix, comp="bz2"):
    with _open(url) as r, tarfile.open(fileobj=_Count(r), mode="r|" + comp) as t:
        METER.start(_size(r, url))
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


# ------------------------------------------------------------------------------------------------ multi-member gzip, by byte range
GZ_SIG = b"\x1f\x8b\x08\x00\x00\x00\x00\x00"      # a gzip member header as Wikimedia's dumper writes it (no name, no time)


def _ranged(url, start, stop):
    """compressed bytes of url from `start` to the end of the file (local file:// too); reconnects where it broke"""
    if url.startswith("file://"):
        with _open(url) as f:
            f.seek(start)
            for b in iter(lambda: f.read(1 << 20), b""):
                if stop["now"]:
                    return
                yield b
        return
    pos, tries = start, 0
    while not stop["now"]:
        try:
            with urllib.request.urlopen(_req(url, {"Range": "bytes=%d-" % pos}), timeout=120) as r:
                if r.status != 206 and pos:
                    raise OSError("the server ignored the byte range")
                while not stop["now"]:
                    b = r.read(1 << 20)
                    if not b:
                        return
                    pos += len(b); tries = 0
                    yield b
        except (OSError, urllib.error.URLError):
            tries += 1
            if tries > 8:
                raise
            time.sleep(min(60, 2 ** tries))


def _prefetch(chunks, stop, depth=32):
    """download on a thread so the connection keeps draining while this process parses; stops with the reader"""
    import queue, threading
    q = queue.Queue(depth)

    def pump():
        try:
            for c in chunks:
                while not stop["now"]:
                    try:
                        q.put(c, timeout=1); break
                    except queue.Full:
                        pass
                if stop["now"]:
                    return
        except Exception as e:                  # handed to the reader, which raises it
            q.put(e)
        finally:
            q.put(None)
    threading.Thread(target=pump, daemon=True).start()
    while True:
        c = q.get()
        if c is None:
            return
        if isinstance(c, Exception):
            raise c
        yield c


def gz_member_lines(url, start, end):
    """the lines of every gzip member whose header lies in [start, end) — a byte range of a multi-member file decoded on
    its own, so several agents can share one file; METER counts the compressed bytes of the range"""
    METER.start(end - start)
    stop = {"now": False}
    try:
        buf, off, d, rest = b"", start, None, b""         # off = the file offset of buf[0]
        for c in _prefetch(_ranged(url, start, stop), stop):
            buf += c
            while True:
                if d is None:                            # find the next member header (checked: the bytes may occur inside data)
                    i = buf.find(GZ_SIG)
                    while i != -1 and len(buf) - i >= 64:
                        try:
                            zlib.decompressobj(31).decompress(buf[i:i + 4096]); break
                        except zlib.error:
                            i = buf.find(GZ_SIG, i + 1)
                    if i == -1 or len(buf) - i < 64:
                        keep = max(0, len(buf) - 64); off += keep; buf = buf[keep:]
                        break
                    if off + i >= end:
                        METER.done = end - start
                        return
                    d = zlib.decompressobj(31); off += i; buf = buf[i:]
                out = d.decompress(buf)
                if out:
                    out = rest + out
                    lines = out.split(b"\n")
                    rest = lines.pop()
                    yield from lines
                if d.eof:
                    off += len(buf) - len(d.unused_data); buf = d.unused_data; d = None
                    if rest:
                        yield rest; rest = b""
                    METER.done = min(end, off) - start
                    if off >= end:
                        return
                    continue
                off += len(buf); buf = b""
                METER.done = min(end, off) - start
                break
    finally:
        stop["now"] = True


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
            METER.start(len(state["common"]), "rows")
            return iter(state["common"])
        METER.start(len(state["names"]), "rows")
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
        METER.start(sc.LAST_YEAR - sc.FIRST_YEAR + 1, "years")
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
                    if e.code not in (429, 503):
                        raise
                    if attempt == 4:
                        raise Busy("Wikidata's query service asked us to slow down (HTTP %d); the open slots are filled on the next run" % e.code)
                    time.sleep(max(self.GAP_S, int(e.headers.get("Retry-After") or 0)))
        state["_last"] = time.time()
        found = sc.slot_facts(part, body["results"]["bindings"])
        METER.start(len(found), "editions")
        return iter(found)

    def facts(self, part, row, state):
        s, p, o, year, url = row
        state.setdefault("_links", {})[s] = url
        state.setdefault("_filled", set()).add((part, year))
        return [(s, p, o)]


class MitOcw(Dataset):
    key, title, app, source = "mit-ocw", "MIT OpenCourseWare — the course catalog", "stem", "mit-ocw-catalog"
    licence = "Facts only (course catalog); OCW's own materials are CC BY-NC-SA 4.0 and are not copied"
    why = "every free MIT course: its number, title, department, school, instructors, level, term, topics and what it offers"
    approx = "about 2,600 courses × 15 facts"
    URL = "https://api.learn.mit.edu/api/v1/courses/?platform=ocw&limit=100"
    GAP_S = 1.0                        # one page a second: about 26 requests for the whole catalog

    def parts(self):
        return [("courses", self.URL)]

    def rows(self, part, url, state):
        if url.startswith("file://"):
            with _open(url) as r:
                yield from json.loads(r.read())["results"]
            return
        first = True
        while url:
            if not first:
                time.sleep(self.GAP_S)
            first = False
            for attempt in range(4):
                try:
                    with urllib.request.urlopen(_req(url, {"Accept": "application/json"}), timeout=120) as r:
                        body = json.loads(r.read())
                    break
                except urllib.error.HTTPError as e:
                    if e.code not in (429, 503):
                        raise
                    if attempt == 3:
                        raise Busy("MIT Learn asked us to slow down (HTTP %d); the catalog continues on the next run" % e.code)
                    time.sleep(max(30, int(e.headers.get("Retry-After") or 0)))
            if not METER.total:
                METER.start(int(body.get("count") or 0), "courses")
            yield from body.get("results") or []
            url = body.get("next")

    def facts(self, part, c, state):
        """catalog facts only — never the course description or any course material (MIT's wording, CC BY-NC-SA)"""
        nums = (c.get("course") or {}).get("course_numbers") or []
        primary = next((n["value"] for n in nums if n.get("listing_type") == "primary"), nums[0]["value"] if nums else None)
        run = next((r for r in c.get("runs") or [] if r.get("id") == c.get("best_run_id")), (c.get("runs") or [None])[0]) or {}
        term = " ".join(str(x) for x in (run.get("semester"), run.get("year")) if x)
        if not primary or not c.get("title"):
            return []
        s = "MIT course %s%s" % (primary, " (%s)" % term if term else "")
        out = [(s, "title", c["title"].strip()), (s, "offered by", "MIT OpenCourseWare")]
        if term:
            out.append((s, "taught in", term))
        for n in nums:
            if n["value"] != primary:
                out.append((s, "also listed as", n["value"]))
        for d in c.get("departments") or []:
            out.append((s, "department", d["name"]))
            if (d.get("school") or {}).get("name"):
                out.append((s, "school", d["school"]["name"]))
        for i in run.get("instructors") or []:
            if i.get("full_name"):
                out.append((s, "instructor", i["full_name"].strip()))
        for lv in run.get("level") or []:
            out.append((s, "level", lv["name"]))
        for t in c.get("ocw_topics") or []:
            out.append((s, "topic", t))
        for f in c.get("course_feature") or []:
            out.append((s, "includes", f))
        if c.get("url"):
            state.setdefault("_links", {})[s] = c["url"]
        return out


class WikidataDump(Dataset):
    """the whole of Wikidata from its weekly entity dump (CC0), read by several agents at once: the dump is one gzip file of
    many independent members, so it is cut into 1 GiB parts and lane k of n takes every n-th part. Each entity line becomes
    facts by a fixed rule — truthy statements (preferred rank, else normal; never deprecated) of the properties below.
    Subjects read "Albert Einstein (Q937)"; an object that is another item is kept as its Q-id and shown with its English
    label (each lane keeps the labels of its entities beside its shard)."""
    URL = "https://dumps.wikimedia.org/wikidatawiki/entities/latest-all.json.gz"
    PART = 1 << 30
    LANES = 16                         # 16 datasets; the agents setting decides how many run at once (one CPU core each)
    PROPS = {
        "P31": "instance of", "P279": "subclass of", "P21": "sex or gender", "P27": "country of citizenship", "P106": "occupation",
        "P569": "date of birth", "P570": "date of death", "P19": "place of birth", "P20": "place of death", "P17": "country",
        "P131": "located in", "P30": "continent", "P36": "capital", "P1376": "capital of", "P625": "coordinates", "P1082": "population",
        "P2046": "area", "P2044": "elevation (m)", "P571": "inception", "P576": "dissolved", "P577": "publication date", "P50": "author",
        "P57": "director", "P86": "composer", "P175": "performer", "P112": "founded by", "P159": "headquarters", "P169": "chief executive",
        "P35": "head of state", "P6": "head of government", "P37": "official language", "P38": "currency", "P166": "award received",
        "P39": "position held", "P69": "educated at", "P800": "notable work", "P26": "spouse", "P22": "father", "P25": "mother",
        "P1346": "winner", "P276": "location", "P585": "point in time", "P991": "successful candidate", "P136": "genre",
        "P495": "country of origin", "P1412": "languages spoken", "P2048": "height", "P1086": "atomic number", "P356": "DOI",
        "P1433": "published in", "P921": "main subject", "P225": "taxon name", "P171": "parent taxon", "P105": "taxon rank",
        "P407": "language of work", "P123": "publisher", "P364": "original language", "P1191": "date of first performance"}
    # every property of these kinds is kept (Wikidata's own catalogue, read once per run); external identifiers (catalogue
    # numbers in other databases), media file names, shapes, tables and lexical data are cross-references, not knowledge
    KEEP_TYPES = {"WikibaseItem", "Quantity", "String", "Url", "Time", "Monolingualtext", "GlobeCoordinate"}
    # Wikimedia's own housekeeping: links between category, list, template and Commons pages, not knowledge
    SKIP_PROPS = {"P373", "P910", "P301", "P971", "P4224", "P360", "P1753", "P1754", "P1423", "P1424", "P3876", "P2354", "P1204",
                  "P935", "P1151", "P1465", "P1792", "P1464", "P7084", "P8464", "P5008", "P6104", "P6365", "P3858", "P2559"}
    PROPS_QUERY = 'SELECT ?p ?t ?l WHERE { ?p wikibase:propertyType ?t . OPTIONAL { ?p rdfs:label ?l FILTER(LANG(?l)="en") } }'
    app, source = "facts", "wikidata"
    licence = "CC0 1.0 (Wikidata)"
    approx = "about 115 million items — about a billion facts (every knowledge property)"

    def __init__(self, lane=1, lanes=None):
        self.lane, self.lanes = lane, lanes or self.LANES
        self.key = "wikidata-dump-%d" % lane
        self.title = "Wikidata — the full dump, lane %d of %d" % (lane, self.lanes)
        self.why = ("the prototype's main source: people, places, works, organisations, taxa and their dates — every item of "
                    "Wikidata, streamed by %d agents side by side" % self.lanes)
        self.size, self.edition, self.base, self.props = None, "", None, dict(self.PROPS)

    def catalogue(self, folder, fetch=True):
        """{property: name} for every property of a kept kind — QueryBook's own names for the ones it named before (so earlier
        shards keep their predicates), else Wikidata's English label. Read from Wikidata once and kept beside the shards;
        without it (no network) the lane keeps the named core properties only."""
        path = os.path.join(folder, FOLDER, "wikidata-properties.json")
        cat = None
        try:
            with open(path, encoding="utf-8") as f:
                cat = json.load(f)
            if time.time() - cat.get("read", 0) > 7 * 86400:
                cat = None if fetch else cat
        except (OSError, ValueError):
            cat = None
        if cat is None and fetch:
            q = urllib.parse.urlencode({"query": self.PROPS_QUERY, "format": "json"})
            try:
                with urllib.request.urlopen(_req("https://query.wikidata.org/sparql?" + q, {"Accept": "application/sparql-results+json"}), timeout=180) as r:
                    rows = json.loads(r.read())["results"]["bindings"]
                cat = {"read": time.time(), "props": {b["p"]["value"].rsplit("/", 1)[-1]: [b["t"]["value"].rsplit("#", 1)[-1], (b.get("l") or {}).get("value")]
                                                     for b in rows}}
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(cat, f)
                os.replace(path + ".tmp", path)
            except Exception:
                cat = None
        out = dict(self.PROPS)
        if cat:
            for pid, (typ, label) in cat["props"].items():
                if typ in self.KEEP_TYPES and pid not in out and pid not in self.SKIP_PROPS:
                    out[pid] = label or pid
        return out

    def _head(self, url):
        if url.startswith("file://"):
            return os.path.getsize(urllib.request.url2pathname(urllib.parse.urlsplit(url).path)), "local file"
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA}), timeout=60) as r:
            lm = r.headers.get("Last-Modified") or ""
            try:
                ed = datetime.datetime.strptime(lm, "%a, %d %b %Y %H:%M:%S GMT").strftime("%Y-%m-%d")
            except ValueError:
                ed = "latest"
            return int(r.headers["Content-Length"]), ed

    def parts(self):
        url = self.base or self.URL
        self.size, self.edition = self._head(url)
        n = -(-self.size // self.PART)
        return [("%s part %04d of %04d" % (self.edition, i + 1, n), "%s#%d-%d" % (url, i * self.PART, min(self.size, (i + 1) * self.PART)))
                for i in range(n) if i % self.lanes == self.lane - 1]

    def prepare(self, run):
        self.base = run.commons.setting("bulk:url:wikidata-dump")      # a mirror or a local copy of the dump (and tests)
        if (run.commons.setting("bulk:wikidata:properties") or "all") == "all":
            self.props = self.catalogue(run.folder, fetch=not (self.base or "").startswith("file://"))
        db = sqlite3.connect(shard_path(run.folder, self.key) + ".labels")
        db.execute("CREATE TABLE IF NOT EXISTS labels (q INTEGER PRIMARY KEY, label TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS keystones (k TEXT PRIMARY KEY, facts INTEGER NOT NULL)")
        db.commit()
        return {"_labeldb": db, "_labelbuf": []}

    def rows(self, part, url, state):
        base, _, rng = url.partition("#")
        a, b = (int(x) for x in rng.split("-"))
        try:
            for line in gz_member_lines(base, a, b):
                if len(line) > 2 and line[0] == 0x7B:          # '{': an entity (skips "[", "]" and separators)
                    yield line
        finally:
            self._flush(state)

    def _flush(self, state):
        buf, db, kc = state.get("_labelbuf"), state.get("_labeldb"), state.get("_kc")
        if db is None:
            return
        if buf:
            db.executemany("INSERT OR REPLACE INTO labels(q, label) VALUES(?, ?)", buf)
            buf.clear()
        if kc:
            db.executemany("INSERT INTO keystones(k, facts) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET facts = facts + excluded.facts", kc.items())
            kc.clear()
        db.commit()

    @staticmethod
    def value(dv):
        t, v = dv.get("type"), dv.get("value")
        if t == "wikibase-entityid":
            return v.get("id") or "Q%d" % v["numeric-id"]
        if t == "time":
            tm, pr = v["time"], v.get("precision", 11)
            y, m, d = tm[1:].split("T")[0].rsplit("-", 2)
            y = ("-" if tm[0] == "-" else "") + y.lstrip("0").rjust(4, "0")
            return "%s-%s-%s" % (y, m, d) if pr >= 11 else "%s-%s" % (y, m) if pr == 10 else y
        if t == "quantity":
            unit = v.get("unit", "1").rsplit("/", 1)[-1]
            return v["amount"].lstrip("+") + ("" if unit == "1" else " " + unit)
        if t == "globecoordinate":                       # places on Earth only (not on the Moon or Mars)
            if (v.get("globe") or "").rsplit("/", 1)[-1] not in ("Q2", ""):
                return None
            return "%.5f, %.5f" % (v["latitude"], v["longitude"])
        if t == "monolingualtext":
            return v["text"].strip() or None if v.get("language") in ("en", "mul") else None
        if t == "string":                                # also URLs; blank values are not facts
            return v.strip() or None
        return None

    def facts(self, part, line, state):
        if line.endswith(b","):
            line = line[:-1]
        try:
            e = json.loads(line)
        except ValueError:
            return []
        L = e.get("labels") or {}
        lab = (L.get("en") or L.get("mul") or {}).get("value")
        if not lab or e.get("type") != "item":
            return []
        q = e["id"]
        buf = state["_labelbuf"]
        buf.append((int(q[1:]), lab))
        if len(buf) >= 200_000:
            self._flush(state)
        claims = e.get("claims") or {}
        cls = {((x.get("mainsnak") or {}).get("datavalue") or {}).get("value", {}).get("id") for x in claims.get("P31", ())}
        if cls & ks.WIKIMEDIA_INTERNAL:                 # a category, disambiguation, template or list page: Wikimedia's own pages
            return []
        s, out, props = "%s (%s)" % (lab, q), [], self.props
        for p, sts in claims.items():
            name = props.get(p)
            if not name:
                continue
            best = [x for x in sts if x.get("rank") == "preferred"] or [x for x in sts if x.get("rank") == "normal"]
            for st in best:
                dv = (st.get("mainsnak") or {}).get("datavalue")
                if dv:
                    v = self.value(dv)
                    if v:
                        out.append((s, name, v))
        if out:
            state.setdefault("_links", {})[s] = "https://www.wikidata.org/wiki/" + q
            k = ks.entity_keystone(cls - {None}, claims.keys())
            if k:                                       # measured coverage per keystone domain (qbkeystone)
                kc = state.setdefault("_kc", {})
                kc[k] = kc.get(k, 0) + len(out)
        return out

    def link(self, subject):
        m = re.search(r"\((Q\d+)\)$", subject)
        return "https://www.wikidata.org/wiki/" + m.group(1) if m else None


def lane_keystones(commons_folder, key):
    """{keystone: facts} a Wikidata lane has counted (qbkeystone.coverage scales it to the shard's count)"""
    p = shard_path(commons_folder, key) + ".labels"
    if not os.path.exists(p):
        return {}
    db = _ro(p)
    try:
        return dict(db.execute("SELECT k, facts FROM keystones"))
    except sqlite3.Error:
        return {}
    finally:
        db.close()


QID = re.compile(r"\bQ(\d+)\b")


def wd_labels(commons_folder, qids):
    """English labels for Q-numbers, from every lane's label file"""
    want, out = sorted(set(qids)), {}
    for lane in range(1, WikidataDump.LANES + 1):
        p = shard_path(commons_folder, "wikidata-dump-%d" % lane) + ".labels"
        if not want or not os.path.exists(p):
            continue
        db = _ro(p)
        for i in range(0, len(want), 500):
            chunk = want[i:i + 500]
            out.update(db.execute("SELECT q, label FROM labels WHERE q IN (%s)" % ",".join("?" * len(chunk)), chunk).fetchall())
        db.close()
        want = [x for x in want if x not in out]
    return out


def catalog():
    return {d.key: d for d in (PubChem(), Taxonomy(), Weather(), GNIS(), FoodData(), Tatoeba(), Calendar(), Series(), MitOcw()) + tuple(WikidataDump(k) for k in range(1, WikidataDump.LANES + 1))}


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


_FP = operator.itemgetter(0)


def shard_path(commons_folder, key):
    return os.path.join(commons_folder, FOLDER, key + ".sqlite")


def fp(domain, s, p, o):
    return bytes.fromhex(core.fingerprint(domain, s, p, o))[:16]


def fingerprinter(domain):
    """fp(domain, s, p, o) for one domain, about twice as fast and byte-for-byte the same: core.fingerprint is
    sha256("|".join(norm(x))) with norm(x) = " ".join(str(x or "").strip().lower().split()). For a str x, str(x or "") is
    x, and strip() is redundant before split() (both drop the same str.isspace characters; lower() never makes or
    removes whitespace), so norm(x) == " ".join(x.lower().split()). The domain and each predicate are normalised once;
    the subject once per run of facts with the same subject; digest() is the bytes hexdigest() spells. Anything that is
    not a str goes through core.norm itself. The self-test compares it with core.fingerprint on awkward text."""
    head, preds, sha, norm = core.norm(domain) + "|", {}, hashlib.sha256, core.norm
    last = [None, ""]

    def f(s, p, o):
        mid = preds.get(p)
        if mid is None:
            mid = preds[p] = "|" + norm(p) + "|"
        if type(s) is str:
            if s is not last[0]:
                last[0], last[1] = s, " ".join(s.lower().split())
            ns = last[1]
        else:
            ns = norm(s)
        no = " ".join(o.lower().split()) if type(o) is str else norm(o)
        return sha((head + ns + mid + no).encode("utf-8")).digest()[:16]
    return f


class Shard:
    def __init__(self, commons_folder, key):
        os.makedirs(os.path.join(commons_folder, FOLDER), exist_ok=True)
        self.db = sqlite3.connect(shard_path(commons_folder, key), timeout=60)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")                 # WAL + NORMAL: a crash never corrupts or splits a batch
        self.db.execute("PRAGMA cache_size=-%d" % (CACHE_MB * 1024))   # a whole batch's dirty pages stay in memory until commit
        self.db.execute("PRAGMA journal_size_limit=%d" % (64 << 20))  # the WAL file shrinks back after each checkpoint
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
        # in fingerprint order, so each B-tree page is visited once per batch. The sort is stable: of two facts with one
        # fingerprint the earlier row still comes first and is the one kept — the shard is the same as unsorted.
        rows.sort(key=_FP)
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
        keep = float(self.commons.setting("bulk:min_free_gb") or MIN_FREE_GB)
        free = shutil.disk_usage(self.folder).free / 1e9
        if free < keep:
            return "the disk is nearly full: %.1f GB free, bulk harvesting keeps at least %g GB (setting bulk:min_free_gb)" % (free, keep)
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
    fpr = fingerprinter(AREA[ds.app])
    sh.set_meta("state", "running"); sh.set_meta("pid", os.getpid()); sh.set_meta("started", core.now_iso()); sh.set_meta("error", None)
    sh.db.commit()
    why = run.stopped()
    if why:
        sh.set_meta("state", "blocked" if "registry" in why else "stopped"); sh.set_meta("error", why); sh.db.commit()
        if "registry" in why:
            run.log("all parts", 0, 0, 0, 0, 0, "blocked", why)
        return {"dataset": key, "state": "blocked" if "registry" in why else "stopped", "why": why}
    total_new, t_start, filtered = 0, time.time(), 0
    import qbcontrol as ctl
    flt = ctl.get(run.commons, "filter")
    flt = flt if ctl.active("filter", flt) else None
    area = AREA[ds.app]
    ev = [{"licence_class": run.commons.registry.check(ds.source)[1] if ds.source else "computed"}]
    try:
        state = ds.prepare(run)
        plist = ds.parts()
        for part_no, (name, url) in enumerate(plist, 1):
            url = run.url_override(key, name) or url
            pid, done_rows, pfacts, done = sh.part(name, url)
            if done:
                continue
            sh.db.execute("UPDATE parts SET started = coalesce(started, ?), version = ? WHERE id = ?", (core.now_iso(), _version(url), pid))
            sh.db.commit()
            row_no, buf, links, t0, log_from, log_new = 0, [], [], time.time(), done_rows, 0
            limit = None if max_rows is None else done_rows + max_rows
            METER.start(0, "bytes")
            rows, end = iter(ds.rows(name, url, state)), object()
            pg = {"part": name, "part_no": part_no, "parts": len(plist), "since": time.time(), "done_at_start": None}
            while row_no < done_rows and next(rows, end) is not end:    # resume: skip what an earlier run already saved
                row_no += 1
            side = shard_path(commons_folder, key) + ".progress"
            _mark(sh, pg, row_no, side); sh.db.commit()
            facts_of, preds, rule, add = ds.facts, sh.preds, ds.rule, buf.append
            for raw in rows:
                found = facts_of(name, raw, state)
                if flt:                                 # the Control Panel's filter binds bulk facts too
                    kept = [f for f in found if ctl.check_item({"subject": f[0], "predicate": f[1], "object": f[2], "evidence": ev}, flt, area) is None]
                    filtered += len(found) - len(kept)
                    found = kept
                lk = state.get("_links")
                for s, p, o in found:
                    if s and o:
                        f = fpr(s, p, o)
                        pi = preds.get(p)
                        if pi is None:
                            pi = sh.pred(p, rule.get(p))
                        add((f, s, pi, o, pid, row_no))
                        if lk and s in lk:
                            links.append((f, lk[s]))
                row_no += 1
                if not row_no & 0x1FFFF:                # about every 130,000 rows: the meter into a side file (no commit)
                    _mark(None, pg, row_no, side)
                if len(buf) >= BATCH:
                    _mark(sh, pg, row_no, side)
                    new = sh.write(pid, buf, row_no, links)
                    total_new += new; log_new += new; buf, links = [], []
                    add = buf.append
                    if log_new >= LOG_EVERY:
                        run.log(name, log_from, row_no, row_no - log_from, log_new, time.time() - t0)
                        log_from, log_new, t0 = row_no, 0, time.time()
                    why = run.stopped()
                    if why:
                        raise _Stop(why)
                if limit is not None and row_no >= limit:
                    break
            _mark(sh, pg, row_no, side)
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
            run.log(name, log_from, row_no, row_no - log_from, log_new, time.time() - t0,
                    reason=(ds.why + "; %d facts left out by the Control Panel's filter" % filtered) if filtered else None)
            state.pop("_links", None)
            why = run.stopped()
            if why:
                raise _Stop(why)
        all_done = all(d for (d,) in sh.db.execute("SELECT done FROM parts"))
        sh.set_meta("state", "done" if all_done else "paused"); sh.set_meta("finished", core.now_iso()); sh.db.commit()
        return {"dataset": key, "state": "done" if all_done else "paused", "new": total_new, "filtered": filtered,
                "seconds": round(time.time() - t_start, 1)}
    except _Stop as e:
        sh.set_meta("state", "stopped"); sh.set_meta("error", str(e)); sh.db.commit()
        return {"dataset": key, "state": "stopped", "why": str(e), "new": total_new}
    except Busy as e:
        sh.set_meta("state", "paused"); sh.set_meta("error", str(e)); sh.db.commit()
        run.log("source busy", 0, 0, 0, 0, time.time() - t_start, "failed", str(e))
        return {"dataset": key, "state": "paused", "why": str(e), "new": total_new}
    except Exception as e:
        sh.set_meta("state", "failed"); sh.set_meta("error", "%s: %s" % (type(e).__name__, str(e)[:300])); sh.db.commit()
        return {"dataset": key, "state": "failed", "why": str(e)[:300], "new": total_new}
    finally:
        sh.db.close()


def _mark(sh, pg, row_no, side=None):
    """the part's progress: into the shard's meta (committed with the next batch), or between batches into a small side
    file — a commit there would cost about 8% of the agent's speed"""
    if METER.unit != "bytes":
        METER.done = row_no
    if pg["done_at_start"] is None:
        pg["done_at_start"] = METER.done
    pg.update(done=METER.done, total=METER.total, unit=METER.unit, rows=row_no, at=time.time())
    if sh is not None:
        sh.set_meta("progress", pg)
    if side:
        try:
            with open(side + ".tmp", "w") as f:
                json.dump(pg, f)
            os.replace(side + ".tmp", side)
        except OSError:
            pass


class _Stop(Exception):
    pass


class Busy(Exception):
    """the publisher asked us to slow down: the dataset pauses (what is saved stays saved) and resumes on the next run"""


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
    beat("removing duplicates across shards")
    try:
        gone = dedupe(commons_folder)
    except sqlite3.Error as e:
        gone = {"error": str(e)}
    results.append({"dedupe": gone})
    beat("finished")
    return results


def dedupe(commons_folder):
    """one fact, one record across every shard: a fingerprint held by an earlier shard (catalog order) is removed from the
    later ones. Within a shard the fingerprint is the key, so a repeat never enters; across shards a repeat can arrive when
    a new edition of a file moves a record between agents (a new weekly Wikidata dump shifts items between lanes).
    The fingerprint includes the area, so only shards of one area can share facts. Runs when every agent has finished."""
    keys = [k for k in catalog() if os.path.exists(shard_path(commons_folder, k))]
    removed = {}
    for j, kj in enumerate(keys):
        earlier = [k for k in keys[:j] if AREA[catalog()[k].app] == AREA[catalog()[kj].app]]
        if not earlier:
            continue
        sh = Shard(commons_folder, kj)
        try:
            gone = 0
            for ki in earlier:
                sh.db.execute("ATTACH DATABASE ? AS e", (shard_path(commons_folder, ki),))
                before = sh.db.total_changes
                sh.db.execute("DELETE FROM links WHERE fp IN (SELECT fp FROM e.facts)")
                links = sh.db.total_changes - before
                sh.db.execute("DELETE FROM facts WHERE fp IN (SELECT fp FROM e.facts)")
                gone += sh.db.total_changes - before - links
                sh.db.commit()
                sh.db.execute("DETACH DATABASE e")
            if gone:
                sh.set_meta("facts", max(0, (sh.meta("facts", 0) or 0) - gone))
                sh.set_meta("duplicates_removed", (sh.meta("duplicates_removed", 0) or 0) + gone)
                sh.db.commit()
                removed[kj] = gone
        finally:
            sh.db.close()
    return removed


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
                pgm = meta.get("progress")
                try:                                    # the side file is newer between batches
                    with open(p + ".progress") as f:
                        pgs = json.load(f)
                    if not pgm or (pgs.get("at") or 0) > (pgm.get("at") or 0):
                        pgm = pgs
                except (OSError, ValueError):
                    pass
                row["progress"] = _progress(pgm, now)
                for secs, k in ((60, "last_minute"), (3600, "last_hour")):
                    r = db.execute("SELECT facts FROM progress WHERE at <= ? ORDER BY at DESC LIMIT 1", (now - secs,)).fetchone()
                    first = db.execute("SELECT min(at) FROM progress").fetchone()[0]
                    base = r[0] if r else (0 if first is None or first > now - secs else row["facts"])
                    row[k] = max(0, row["facts"] - base)
                row["parts"] = [dict(zip(("name", "rows", "facts", "done", "version", "finished"), r))
                                for r in db.execute("SELECT name, rows, facts, done, version, finished FROM parts ORDER BY id")]
                pg = row["progress"]
                if pg:                                  # overall: every finished part counts, plus the share of the current one
                    others = sum(1 for x in row["parts"] if x["done"] and x["name"] != pg["part"])
                    pg["overall"] = 1.0 if row["state"] == "done" else round(min(1.0, (others + (pg["fraction"] or 0)) / max(1, pg["parts"])), 4)
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
    return {"version": VERSION, "cores": os.cpu_count() or 1, "max_agents": MAX_AGENTS, "datasets": out, "runner": rs, "total": sum(d["facts"] for d in out),
            "last_minute": sum(d["last_minute"] for d in out), "last_hour": sum(d["last_hour"] for d in out),
            "bytes": sum(d["bytes"] for d in out)}


def _progress(pg, now):
    """the saved meter → part and overall fraction, rate and time left (None when nothing is measured yet)"""
    if not pg:
        return None
    total, done = pg.get("total") or 0, pg.get("done") or 0
    frac = min(1.0, done / total) if total else None
    secs = max(0.001, (pg.get("at") or now) - (pg.get("since") or now))
    rate = max(0, done - (pg.get("done_at_start") or 0)) / secs if secs > 1 else None
    eta = (total - done) / rate if rate and total and done < total else None
    parts = pg.get("parts") or 1
    overall = ((pg.get("part_no", 1) - 1) + (frac or 0)) / parts
    return dict(pg, fraction=frac, overall=round(overall, 4), rate=rate, eta_s=round(eta) if eta else None)


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
    qs = [int(m) for r in out if r["source"] == "wikidata" for m in QID.findall(r["object"])]
    if qs:
        lab = wd_labels(commons_folder, qs)
        for r in out:
            if r["source"] == "wikidata":
                r["object"] = QID.sub(lambda m: "%s (Q%s)" % (lab[int(m.group(1))], m.group(1)) if int(m.group(1)) in lab else m.group(0), r["object"])
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
    import qbcontrol as ctl, qbkeystone as ks
    keys = ks.order(keys, commons.folder, commons, ctl.get(commons, "target"))   # the admin's target, then keystone priority
    agents = MAX_AGENTS if not agents or int(agents) <= 0 else max(1, min(int(agents), MAX_AGENTS))   # 0 = full speed
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
            return start(commons, p.get("datasets"), p.get("agents", 4), p.get("passphrase"), program_dir)   # 0 = full speed
        except ValueError as e:
            raise core.UserError(str(e))

    @api.post("/api/bulk/stop")
    def bulk_stop(p):
        return stop(commons)

    @api.get("/api/keystones")
    def keystones(p):
        import qbkeystone as ks
        cov = ks.coverage(commons.folder, commons)
        return dict(cov, probes=ks.probes(cov["keystones"]))

    @api.get("/api/bulk/diagnose")
    def bulk_diagnose(p):
        import qbconnections as qc
        own = getattr(api, "own_folder", None)
        return {"checks": diagnose(commons, qc.google_folders(program_dir, own))}

    @api.post("/api/bulk/move-folder")
    def bulk_move(p):
        import qbconnections as qc
        try:
            return move_folder(commons, qc.google_folders(program_dir, getattr(api, "own_folder", None)), p.get("folder"), p.get("passphrase"))
        except ValueError as e:
            raise core.UserError(str(e))

    @api.get("/api/bulk/search")
    def bulk_search(p):
        return {"facts": search(commons.folder, p.get("q") or "", int(p.get("limit") or 50))}


# ------------------------------------------------------------------------------------------------ "why so slow?"
def diagnose(commons, folders=None, probe=True):
    """every reason the bulk agents might not be running at full speed, each with what to do. folders: {program: data folder}
    (to check all four programs share one Commons)."""
    import qbharvest as hv
    out = []

    def add(name, ok, detail, fix=""):
        out.append({"check": name, "ok": bool(ok), "detail": detail, "fix": "" if ok else fix})
    st = status(commons.folder, commons)
    add("Admin passphrase", True, "set — type it on the Bulk harvesting tab" if commons.approvals.admin_set()
        else "none set — every button works without one", "")
    add("Master harvesting switch", hv.master_running(commons), "on" if hv.master_running(commons) else "OFF — every agent stops at once",
        "Turn harvesting on: Control Panel → Overview → master switch, or the ▶ Start all harvesting button.")
    rs = st["runner"]
    alive = rs.get("alive")
    add("Bulk agents running", alive, ("running: %s" % rs.get("note")) if alive else
        ("not running (last: %s)" % (rs.get("note") or "never started")),
        "Bulk harvesting tab → ⚡ Full speed. The agents then run for hours (Wikidata) and stop by themselves.")
    shards = os.path.join(commons.folder, FOLDER)
    os.makedirs(shards, exist_ok=True)
    free = shutil.disk_usage(shards).free / 1e9
    keep = float(commons.setting("bulk:min_free_gb") or MIN_FREE_GB)
    add("Free space where the facts are stored", free >= max(keep, 200), "%.0f GB free at %s" % (free, shards),
        ("Under %g GB the agents pause. " % keep if free < keep else "") +
        "A full Wikidata pass needs about 100–200 GB. Move the shared folder to a large drive (e.g. your 20 TB drive): "
        "Bulk harvesting → type the new folder → Move the shared folder.")
    if folders:
        import qbcommons as cm
        where = {app: os.path.abspath(cm.commons_folder(f)) for app, f in folders.items()}
        where["this Control Panel"] = os.path.abspath(commons.folder)
        same = len(set(where.values())) == 1
        add("All programs share one fact store", same, "all use %s" % next(iter(where.values())) if same else
            "; ".join("%s → %s" % kv for kv in where.items()),
            "Bulk harvesting → Move the shared folder (it points all four programs at one folder), then restart them.")
    states = {}
    for d in st["datasets"]:
        states.setdefault(d["state"], []).append(d["key"])
    bad = [(d["key"], d["error"]) for d in st["datasets"] if d["error"] and d["state"] in ("failed", "blocked", "stopped", "paused")]
    add("Datasets without errors", not bad, ", ".join("%s: %d" % (k, len(v)) for k, v in sorted(states.items())) +
        ("" if not bad else " — " + "; ".join("%s: %s" % (k, (e or "")[:120]) for k, e in bad[:5])),
        "Read each error above: 'disk is nearly full' → move the folder; 'not approved' → approve the source on the Harvesting page; "
        "'switched off' → master switch; a network error → check the server's internet connection or firewall.")
    blocked = [d["key"] for d in st["datasets"] if not d["approved"]]
    add("Sources approved in the registry", not blocked, "all approved" if not blocked else "not approved: " + ", ".join(blocked),
        "Harvesting page → Sources → approve them (admin passphrase).")
    add("Facts arriving", st["last_hour"] > 0, "%s bulk facts in total, %s in the last hour" % (format(st["total"], ","), format(st["last_hour"], ",")),
        "If the agents are running but nothing arrives, look at the dataset errors above.")
    if probe:
        for name, url in (("Wikidata dumps", WikidataDump.URL), ("NCBI (PubChem, Taxonomy)", "https://ftp.ncbi.nlm.nih.gov/pubchem/Compound/Extras/")):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA}), timeout=20) as r:
                    add("Reach " + name, True, "HTTP %d" % r.status)
            except Exception as e:
                add("Reach " + name, False, "%s: %s" % (type(e).__name__, str(e)[:120]),
                    "The server cannot download from this site: check its internet connection, proxy or firewall.")
    add("CPU cores for agents", (os.cpu_count() or 1) >= 4, "%d cores — Full speed runs %d agents" % (os.cpu_count() or 1, MAX_AGENTS), "")
    return out


def move_folder(commons, folders, target, passphrase):
    """admin: point every program at a new shared folder (e.g. a large drive). The current facts are copied there when the new
    folder is empty; the programs use it after a restart."""
    import qbcommons as cm
    commons.approvals._require(passphrase or "")
    target = os.path.abspath(os.path.expanduser(target or ""))
    if not target or target == os.path.abspath(commons.folder):
        raise ValueError("Give a new folder, e.g. E:\\QueryBook-Data\\commons")
    if _alive(commons.folder):
        raise ValueError("Stop the bulk agents first (■ Stop all), then move the folder.")
    os.makedirs(target, exist_ok=True)
    copied = False
    if not os.listdir(target):
        shutil.copytree(commons.folder, target, dirs_exist_ok=True)
        copied = True
    for app, f in folders.items():
        os.makedirs(f, exist_ok=True)
        cm.set_commons_folder(f, target)
    with commons.store.write() as db:
        commons.agent_log(db, "control", "Shared folder moved to %s for %s" % (target, ", ".join(folders)))
    return {"folder": target, "copied": copied, "programs": sorted(folders),
            "summary": "All programs now use %s%s. Close all four programs and start them again (START-ALL)." % (target, " (current facts copied)" if copied else "")}

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
        c.set_setting("bulk:min_free_gb", 1e9)
        g = run_dataset(cf, "calendar-scaffold", max_rows=1)
        ok("disk guard: no agent starts when the disk has less free than the setting keeps", g["state"] == "stopped" and "disk" in g["why"], g)
        c.set_setting("bulk:min_free_gb", 0)
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
        sdb = _ro(shard_path(cf, "pubchem-computed"))
        stored = sdb.execute("SELECT f.fp, f.s, pr.name, f.o FROM facts f JOIN predicates pr ON pr.id = f.p ORDER BY f.row LIMIT 50").fetchall()
        sdb.close()
        fast, odd = fingerprinter("stem"), [" A b ", "İstanbul", "STRASSE ß", "x 　y", "\x1c\x85z", "a|b", "", 2024, 3.5, None]
        same_fp = all(f == fp("stem", s, p, o) for f, s, p, o in stored) and all(
            fast(s, p, o) == fp("stem", s, p, o) for s in odd for p in ("p", " P q ") for o in odd)
        ok("PubChem: formula and mass per compound, plus SMILES and InChIKey; a capped run resumes where it stopped (no fact twice); "
           "fingerprints are the Commons' own", r1["state"] == "paused" and r2["state"] == "done" and pc["facts"] == 3000 * 2 + 2
           and pc["parts"][0]["rows"] == 3000 and len(stored) == 50 and same_fp, (r1, r2, pc["facts"], same_fp))
        pg = pc.get("progress") or {}
        ok("progress: each part measured on the publisher's own scale (compressed bytes of the file), with the overall share",
           pg.get("unit") == "bytes" and pg.get("total") == os.path.getsize(os.path.join(tmp, "CID-Mass.gz")) and pg.get("fraction") == 1.0
           and pg.get("part") == "CID-Mass" and pg.get("overall") == 1.0, pg)
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
        mo, st = MitOcw(), {}
        course = {"title": "Linear Algebra", "best_run_id": 1, "url": "https://ocw.mit.edu/courses/18-06-linear-algebra-spring-2010/",
                  "description": "MIT's own wording, never stored", "course": {"course_numbers": [{"value": "18.06", "listing_type": "primary"}]},
                  "runs": [{"id": 1, "semester": "Spring", "year": 2010, "instructors": [{"full_name": "Prof. Gilbert Strang"}],
                            "level": [{"name": "Undergraduate"}]}], "departments": [{"name": "Mathematics", "school": {"name": "School of Science"}}],
                  "ocw_topics": ["Linear Algebra"], "course_feature": ["Lecture Videos"]}
        of = mo.facts("courses", course, st)
        ok("MIT OCW: catalog facts only (number, title, instructor, term, topics), never the description", ("MIT course 18.06 (Spring 2010)",
           "instructor", "Prof. Gilbert Strang") in of and ("MIT course 18.06 (Spring 2010)", "title", "Linear Algebra") in of
           and not any("wording" in o for _, _, o in of) and st["_links"]["MIT course 18.06 (Spring 2010)"].startswith("https://ocw.mit.edu/"), of)
        import gzip as _gz
        ents = [{"type": "item", "id": "Q%d" % q, "labels": {"en": {"value": name}}, "claims": {
                    "P569": [{"rank": "normal", "mainsnak": {"datavalue": {"type": "time", "value": {"time": "+1879-03-14T00:00:00Z", "precision": 11}}}}],
                    "P27": [{"rank": "deprecated", "mainsnak": {"datavalue": {"type": "wikibase-entityid", "value": {"id": "Q183"}}}},
                            {"rank": "normal", "mainsnak": {"datavalue": {"type": "wikibase-entityid", "value": {"id": "Q30"}}}}]}}
                for q, name in ((937, "Albert Einstein"), (30, "United States"), (5, "human"))]
        dump = os.path.join(tmp, "dump.json.gz")
        with open(dump, "wb") as f:                     # one gzip member per entity, as Wikimedia writes it
            f.write(_gz.compress(b"[\n", mtime=0))
            for i, e in enumerate(ents):
                f.write(_gz.compress((json.dumps(e) + (",\n" if i < 2 else "\n")).encode(), mtime=0))
            f.write(_gz.compress(b"]\n", mtime=0))
        size = os.path.getsize(dump)
        cut = size // 2
        both = [x for a_, b_ in ((0, cut), (cut, size)) for x in gz_member_lines("file://" + dump, a_, b_)]
        ok("Wikidata dump: two byte ranges read on their own give every entity exactly once",
           sorted(json.loads(x.rstrip(b","))["id"] for x in both if x[:1] == b"{") == ["Q30", "Q5", "Q937"], both)
        wd = WikidataDump(1, 1)
        c.set_setting("bulk:url:wikidata-dump", "file://" + dump)
        WikidataDump.LANES, lanes_was = 1, WikidataDump.LANES
        try:
            r = run_dataset(cf, "wikidata-dump-1")
            hits = search(cf, "Albert Einstein")
        finally:
            WikidataDump.LANES = lanes_was
        ok("Wikidata dump: truthy statements only (a deprecated one is skipped), objects shown with their label",
           r["state"] == "done" and {(h["predicate"], h["object"]) for h in hits} == {("date of birth", "1879-03-14"),
           ("country of citizenship", "United States (Q30)")} and hits[0]["link"] == "https://www.wikidata.org/wiki/Q937", (r, hits))
        wd = WikidataDump(1, 1)
        os.makedirs(os.path.join(cf, FOLDER), exist_ok=True)
        with open(os.path.join(cf, FOLDER, "wikidata-properties.json"), "w") as f:
            json.dump({"read": time.time(), "props": {"P1449": ["Monolingualtext", "nickname"], "P214": ["ExternalId", "VIAF ID"],
                                                      "P373": ["String", "Commons category"], "P8888": ["WikibaseItem", "favourite thing"]}}, f)
        wd.props = wd.catalogue(cf, fetch=False)
        def ent(q, claims, cls="Q5"):
            c = {"P31": [{"rank": "normal", "mainsnak": {"datavalue": {"type": "wikibase-entityid", "value": {"id": cls}}}}]}
            for pid, dv in claims.items():
                c[pid] = [{"rank": "normal", "mainsnak": {"datavalue": dv}}]
            return json.dumps({"type": "item", "id": q, "labels": {"en": {"value": "X"}}, "claims": c}).encode()
        st_ = {"_labelbuf": [], "_labeldb": None}
        got = {p_ for _, p_, _ in wd.facts("p", ent("Q1", {"P1449": {"type": "monolingualtext", "value": {"text": "Ace", "language": "en"}},
                                                        "P214": {"type": "string", "value": "12345"}, "P373": {"type": "string", "value": "X"},
                                                        "P8888": {"type": "wikibase-entityid", "value": {"id": "Q2"}},
                                                        "P625": {"type": "globecoordinate", "value": {"latitude": 1, "longitude": 2, "globe": "http://www.wikidata.org/entity/Q405"}}}), st_)}
        ok("Wikidata: every knowledge property kept by its English name; external identifiers, Wikimedia housekeeping and "
           "coordinates on other globes left out", got == {"instance of", "nickname", "favourite thing"}, got)
        ok("Wikidata: Wikimedia's own pages (categories, lists, templates) give no facts",
           wd.facts("p", ent("Q3", {"P8888": {"type": "wikibase-entityid", "value": {"id": "Q2"}}}, cls="Q4167836"), st_) == [])
        os.remove(os.path.join(cf, FOLDER, "wikidata-properties.json"))
        se = Series()
        se.GAP_S = 0
        f = [x for row in se.rows("nobel-physics", url("nobel.json"), {}) for x in se.facts("nobel-physics", row, {})]
        ok("series: a slot is filled only from the source's answer", f == [("Nobel Prize in Physics 1921", "laureate", "Albert Einstein")], f)
        real_open, real_sleep = urllib.request.urlopen, time.sleep
        def busy(*a, **k):
            raise urllib.error.HTTPError("https://query.wikidata.org/sparql", 429, "Too Many Requests", {}, None)
        urllib.request.urlopen, time.sleep = busy, (lambda s: None)
        try:
            se2 = Series(); se2.GAP_S = 0
            try:
                list(se2.rows("nobel-physics", se2.ENDPOINT, {}))
                paused = False
            except Busy:
                paused = True
        finally:
            urllib.request.urlopen, time.sleep = real_open, real_sleep
        ok("series: when Wikidata keeps refusing (HTTP 429) the dataset pauses to resume later — it does not fail", paused)
        cal = Calendar()
        yf = cal.facts("years", 2024, {})
        ok("calendar: computed facts name their rule", ("Year 2024", "Easter Sunday (Western churches)", "2024-03-31") in yf and cal.rule.get("date"), yf[:3])
        with c.store.write() as db:
            db.execute("UPDATE policy_sources SET status = 'blocked' WHERE key = 'usgs-gnis'")
        b = run_dataset(cf, "usgs-gnis")
        ok("a source blocked in the registry is not harvested (and the refusal is logged)", b["state"] == "blocked"
           and c.store.scalar("SELECT count(*) FROM harvest_log WHERE action = 'bulk:usgs-gnis' AND decision = 'blocked'", default=0) == 1, b)
        shutil.copy(shard_path(cf, "wikidata-dump-1"), shard_path(cf, "wikidata-dump-2"))   # the same items arriving in another lane
        dd = dedupe(cf)
        ok("deduplication: a fact held by one shard is removed from every later one (6 repeats here), and the counts follow",
           dd == {"wikidata-dump-2": 6} and len(search(cf, "Albert Einstein")) == 2 and dedupe(cf) == {}, dd)
        ar = by_area(cf)
        ok("ticker: shard facts counted per area", ar["stem"]["facts"] == 6002 and ar["history"]["facts"] == 5 + 6, ar)   # 5 series + 6 from the dump fixture
        import qbcontrol as ctl
        kc = lane_keystones(cf, "wikidata-dump-1")
        ok("keystones: each Wikidata entity's facts counted under its domain (no class given: a date of birth means a person)",
           kc == {"human_individuals": 6}, kc)
        cov = ks.coverage(cf, c)
        row = {r["key"]: r for r in cov["keystones"]}
        ok("coverage is measured from the facts held, with each keystone's sources and state",
           row["human_individuals"]["facts"] == 6 and "wikidata" in row["human_individuals"]["feeds"]
           and row["chemistry_materials"]["facts"] >= 3000 and row["astronomy"]["state"] == "not started", [(r["key"], r["facts"]) for r in cov["keystones"]][:6])
        o = ks.order(["usgs-gnis", "pubchem-computed", "calendar-scaffold"], cf, c, {"sources": ["usgs-gnis"]})
        ok("runner order: the admin's target first, then keystone priority", o[0] == "usgs-gnis" and len(o) == 3, o)
        for x in ("wikidata-dump-1", "wikidata-dump-2"):
            for ext in ("", "-wal", "-shm", ".labels", ".progress"):
                if os.path.exists(shard_path(cf, x) + ext):
                    os.remove(shard_path(cf, x) + ext)
        with c.store.write() as db:
            c.set_setting(ctl.FILTER_KEY, json.dumps({"exclude_words": ["united states"]}), db)
        r = run_dataset(cf, "wikidata-dump-1")
        hits = search(cf, "Albert Einstein")
        ok("the Control Panel's filter binds bulk facts too (and the harvest log says how many it left out)",
           r["filtered"] == 2 and not search(cf, "United States") and len(hits) == 2
           and c.store.scalar("SELECT count(*) FROM harvest_log WHERE action = 'bulk:wikidata-dump-1' AND reason LIKE '%left out by the Control Panel%'", default=0) >= 1,
           (r, hits))
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
    r.add_argument("--agents", type=int, default=4, help="0 = full speed: one agent per CPU core")
    r.add_argument("--max-rows", type=int, default=None)
    s = sp.add_parser("status")
    s.add_argument("--commons", required=True)
    sp.add_parser("self-test")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        for res in run(a.commons, [k for k in a.datasets.split(",") if k] or None, a.agents if a.agents > 0 else MAX_AGENTS, a.max_rows):
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
