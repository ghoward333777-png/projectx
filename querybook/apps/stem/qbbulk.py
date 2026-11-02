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
import qbtrace as qt  # noqa: E402  (instrumentation: every stage, every I/O, every failure → <shared folder>/trace/*.jsonl)
TR, _NS, _WALL = qt.TR, qt._NS, qt._WALL

VERSION = "1.0.0"
UA = "QueryBook-harvester/%s (+https://github.com/ghoward333777-png/projectx; personal research tool; bulk files, one stream per dataset)" % VERSION
BATCH = 500_000                    # facts per transaction (bigger batches touch each page of the fingerprint B-tree less often)
CACHE_MB = 128                     # SQLite page cache per agent
LOG_EVERY = 1_000_000              # a harvest-log entry per million new facts (and at the end of each part)
FOLDER = "shards"
MAX_AGENTS = min(64, max(16, os.cpu_count() or 1))   # one process per agent: up to every core of the machine
RETRY_ROUNDS = 200                 # a refused dataset is retried this many times in one run (about 10 hours at RETRY_WAIT_S)
RETRY_WAIT_S = 180
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
        t = _NS()
        n = self.raw.readinto(b)
        TR.add("net_read", _NS() - t, 1, n or 0)
        TR.chunk_wall = _WALL()
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


# ------------------------------------------------------------------------------------------------ polite downloading
# Publishers cap the connections one computer may hold (Wikimedia answers "429 Too Many Requests" beyond a few). Every
# agent process takes a CONNECTION SLOT for the server before it downloads and gives it back after; a server that says
# "slow down" (429/503) is left alone for its Retry-After (at least COOL_S) and the agent moves to another server holding
# the identical file, or waits. A refusal is never a failure.
COOL_S = 120
REFUSED = (429, 503)


def _host(url):
    return (urllib.parse.urlsplit(url).hostname or "local").lower()


def _replace(tmp, dst, tries=40):
    """os.replace that waits out Windows' sharing rule: a file another program is reading at that instant cannot be replaced
    (PermissionError), so try again for a few seconds instead of failing (the Control Panel reads these files every few seconds)"""
    for i in range(tries):
        try:
            os.replace(tmp, dst)
            return True
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.05 + 0.05 * i)
    return False


class Slots:
    """connections per server, shared by every agent process through lock files (the system releases a dead process's lock)"""

    def __init__(self, commons_folder, halt=None):
        self.dir = os.path.join(commons_folder, FOLDER, "_slots")
        os.makedirs(self.dir, exist_ok=True)
        self.halt, self._checked = halt, 0.0

    def _lock(self, host, i):
        f = open(os.path.join(self.dir, "%s-%d.lock" % (host, i)), "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except OSError:
            f.close()
            return None

    def release(self, f):
        if f is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            f.close()

    def cooling(self, host):
        try:
            with open(os.path.join(self.dir, host + ".cool")) as f:
                return max(0.0, float(f.read() or 0) - time.time())
        except (OSError, ValueError):
            return 0.0

    def cool(self, host, seconds):
        until = time.time() + seconds
        if self.cooling(host) + time.time() < until:
            tmp = os.path.join(self.dir, "%s.cool.%d" % (host, os.getpid()))
            with open(tmp, "w") as f:
                f.write(str(until))
            _replace(tmp, os.path.join(self.dir, host + ".cool"))

    def acquire(self, sources, stop):
        """(url, lock) on the first server with a free connection that is not cooling down; waits while every one is busy.
        sources: [(url, connections)]. Raises _Stop when the run is stopped meanwhile."""
        while not stop["now"]:
            for url, n in sources:
                host = _host(url)
                if self.cooling(host):
                    continue
                for i in range(max(1, int(n))):
                    f = self._lock(host, i)
                    if f:
                        return url, f
            if self.halt and time.time() - self._checked > 15:
                self._checked = time.time()
                why = self.halt()
                if why:
                    raise _Stop(why)
            time.sleep(2)
        return None, None


def _retry_after(e):
    try:
        return int(e.headers.get("Retry-After") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0


# ------------------------------------------------------------------------------------------------ multi-member gzip, by byte range
GZ_SIG = b"\x1f\x8b\x08\x00\x00\x00\x00\x00"      # a gzip member header as Wikimedia's dumper writes it (no name, no time)


def _ranged(url, start, stop, sources=None, slots=None):
    """compressed bytes of url from `start` to the end of the file (local file:// too); reconnects where it broke.
    With sources [(url, connections)] and slots, each connection takes a slot on one of the servers holding the identical
    file, and a server that refuses (429/503) is left to cool down while another one, or a later turn, carries on."""
    if url.startswith("file://"):
        with _open(url) as f:
            f.seek(start)
            for b in iter(lambda: f.read(1 << 20), b""):
                if stop["now"]:
                    return
                yield b
        return
    sources = sources or [(url, 1)]
    pos, tries, refused = start, 0, 0
    while not stop["now"]:
        t = _NS()
        src, lock = slots.acquire(sources, stop) if slots else (sources[0][0], None)
        TR.add("net_wait", _NS() - t)                 # waiting for a free connection slot (congestion at our end)
        if src is None:
            return
        t_conn, got = _NS(), 0
        try:
            with urllib.request.urlopen(_req(src, {"Range": "bytes=%d-" % pos}), timeout=120) as r:
                ttfb = (_NS() - t_conn) / 1e9
                TR.add("net_connect", _NS() - t_conn)
                if r.status != 206 and pos:
                    raise OSError("the server ignored the byte range")
                while not stop["now"]:
                    t = _NS()
                    b = r.read(1 << 20)
                    TR.add("net_read", _NS() - t, 1, len(b))
                    TR.chunk_wall = _WALL()
                    if not b:
                        TR.io(_host(src), r.status, (_NS() - t_conn) / 1e9, got, ttfb, url=src[-80:], end="complete")
                        return
                    pos += len(b); tries = 0; refused = 0; got += len(b)
                    yield b
                TR.io(_host(src), r.status, (_NS() - t_conn) / 1e9, got, ttfb, url=src[-80:], end="stopped")
        except urllib.error.HTTPError as e:
            TR.io(_host(src), e.code, (_NS() - t_conn) / 1e9, got, None, url=src[-80:], end="refused" if e.code in REFUSED else "error")
            TR.fail("network", e, retried=True, host=_host(src), code=e.code, offset=pos)
            if e.code in REFUSED:                     # "slow down": not a failure — let that server cool down
                wait = max(COOL_S, _retry_after(e))
                refused += 1
                if slots:
                    slots.cool(_host(src), wait)
                else:
                    if refused > 30:
                        raise Busy("%s keeps refusing (HTTP %d): paused, resumes on the next run" % (_host(src), e.code))
                    time.sleep(min(600, wait))
                continue
            tries += 1
            if tries > 8:
                raise
            time.sleep(min(60, 2 ** tries))
        except (OSError, urllib.error.URLError) as e:
            TR.io(_host(src), None, (_NS() - t_conn) / 1e9, got, None, url=src[-80:], end="broken")
            TR.fail("network", e, retried=tries < 8, host=_host(src), offset=pos)
            tries += 1
            if tries > 8:
                raise
            time.sleep(min(60, 2 ** tries))
        finally:
            if slots:
                slots.release(lock)


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
        t = _NS()
        c = q.get()
        TR.add("starved", _NS() - t)              # the parser waited for the network (network-bound when large)
        if c is None:
            return
        if isinstance(c, Exception):
            raise c
        yield c


def gz_member_lines(url, start, end, sources=None, slots=None):
    """the lines of every gzip member whose header lies in [start, end) — a byte range of a multi-member file decoded on
    its own, so several agents can share one file; METER counts the compressed bytes of the range"""
    METER.start(end - start)
    stop = {"now": False}
    try:
        buf, off, d, rest = b"", start, None, b""         # off = the file offset of buf[0]
        for c in _prefetch(_ranged(url, start, stop, sources, slots), stop):
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
                t = _NS()
                out = d.decompress(buf)
                TR.add("decompress", _NS() - t, 1, len(out))
                TR.decomp_wall = _WALL()
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
    why = ("every edition of the recurring events Wikidata records — winner, place, country, dates, participants, its own name — "
           "with each edition linked to the one before and after: one query per series (a lattice of slots)")
    approx = "tens of thousands of facts; the slots show which editions are still open"
    ENDPOINT = "https://query.wikidata.org/sparql"
    # Wikidata's query service allows each client a share of query time per minute. The pause after a query is twice the
    # time the query took (at least GAP_S), so the harvester uses well under half of that share; a 429 doubles the pause.
    GAP_S = 2.0
    MAX_GAP_S = 120.0

    def parts(self):
        return [(k, self.ENDPOINT) for k in sc.SERIES]

    def rows(self, part, url, state):
        last, gap = state.get("_last", 0), state.get("_gap", self.GAP_S)
        if last and time.time() - last < gap:
            time.sleep(gap - (time.time() - last))
        t0 = time.time()
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
                    state["_gap"] = gap = min(self.MAX_GAP_S, max(gap * 2, 10))
                    time.sleep(max(gap, _retry_after(e)))
        state["_last"] = time.time()
        state["_gap"] = max(self.GAP_S, min(self.MAX_GAP_S, max(2 * (time.time() - t0), state.get("_gap", self.GAP_S) * 0.75)))
        found = sc.slot_facts(part, body["results"]["bindings"])
        METER.start(len(found), "editions")
        return iter(found)

    def facts(self, part, row, state):
        s, p, o, year, url = row
        state.setdefault("_links", {})[s] = url
        state.setdefault("_filled", set()).add((part, year))
        return [(s, p, o)]


class WikidataLattice(Dataset):
    """EVERY recurring event series Wikidata knows, found by Wikidata itself and harvested in batches — the lattice.

    Discovery (three grouped queries, about a minute, refreshed weekly) lists every series with at least five editions:
    league and competition seasons (P3450, about 5,900 series), series of dated events (P179: conferences, festivals,
    synods, award ceremonies, elections, trade fairs...; about 3,600) and recurring events whose editions are instances of
    them (about 140). The editions of up to 200 series (at most 1,500 editions) are then read in ONE query: each edition's
    series, date, start and end, winner, place, country, successful candidate and number of participants, and each edition
    is linked to the one before and after it in date order. Facts are written exactly as the dump lanes write them (same
    subject "Name (Q-id)", predicate names, Q-id objects and date precision), so where the two overlap one copy is kept."""
    key, title, app, source = "wikidata-lattice", "Recurring events — every series Wikidata knows, harvested by batches", "facts", "wikidata"
    licence = "CC0 1.0 (Wikidata)"
    why = ("sports seasons, tournaments, elections, festivals, conferences, award ceremonies, synods, trade fairs: every series Wikidata "
           "records, found automatically and read 200 series per query, each edition linked to the one before and after it")
    approx = "about 9,700 series, 240,000 editions, 1-2 million facts in roughly 200 queries"
    ENDPOINT = "https://query.wikidata.org/sparql"
    LINKS = ("P3450", "P179", "P31")
    MIN_EDITIONS = 5
    BATCH_SERIES, BATCH_EDITIONS = 200, 1500
    GAP_S, MAX_GAP_S = 2.0, 120.0
    DISCOVER = {
        "P3450": "SELECT ?s (COUNT(?e) AS ?n) WHERE { ?e wdt:P3450 ?s } GROUP BY ?s HAVING(COUNT(?e) >= %d)",
        "P179": "SELECT ?s (COUNT(?e) AS ?n) WHERE { ?e wdt:P179 ?s; wdt:P585|wdt:P580 ?d } GROUP BY ?s HAVING(COUNT(?e) >= %d)",
        "P31": "SELECT ?s (COUNT(?e) AS ?n) WHERE { ?e wdt:P31 ?s. ?s wdt:P31 wd:Q15275719. ?e wdt:P585|wdt:P580 ?d } GROUP BY ?s HAVING(COUNT(?e) >= %d)"}
    ITEM_PROPS = ("P1346", "P276", "P17", "P991")
    TIME_PROPS = ("P585", "P580", "P582")
    NAMES = {"P3450": "sports season of league or competition", "P179": "part of the series", "P31": "instance of", "P1346": "winner",
             "P276": "location", "P17": "country", "P991": "successful candidate", "P585": "point in time", "P580": "start time",
             "P582": "end time", "P1132": "number of participants"}
    # one query per batch: the editions of up to 200 series, every property an OPTIONAL lookup on an edition already found
    # (index-friendly: about 7 s for 200 series / 1,500-2,000 editions); dates with their precision, best rank only
    EDITION_Q = ("SELECT ?e ?eLabel ?w ?loc ?cty ?cand ?n ?s ?dt ?dp ?st ?sp ?en ?ep WHERE { VALUES ?s { %s } ?e wdt:%s ?s. "
                 "OPTIONAL { ?e wdt:P1346 ?w } OPTIONAL { ?e wdt:P276 ?loc } OPTIONAL { ?e wdt:P17 ?cty } OPTIONAL { ?e wdt:P991 ?cand } "
                 "OPTIONAL { ?e wdt:P1132 ?n } "
                 "OPTIONAL { ?e p:P585 ?a. ?a a wikibase:BestRank; psv:P585 ?av. ?av wikibase:timeValue ?dt; wikibase:timePrecision ?dp } "
                 "OPTIONAL { ?e p:P580 ?b. ?b a wikibase:BestRank; psv:P580 ?bv. ?bv wikibase:timeValue ?st; wikibase:timePrecision ?sp } "
                 "OPTIONAL { ?e p:P582 ?c. ?c a wikibase:BestRank; psv:P582 ?cv. ?cv wikibase:timeValue ?en; wikibase:timePrecision ?ep } "
                 "SERVICE wikibase:label { bd:serviceParam wikibase:language \"en,mul\". ?e rdfs:label ?eLabel } }")
    COLS = (("w", "P1346"), ("loc", "P276"), ("cty", "P17"), ("cand", "P991"), ("s", None), ("n", "P1132"),
            (("dt", "dp"), "P585"), (("st", "sp"), "P580"), (("en", "ep"), "P582"))

    def discovery_path(self, folder):
        return os.path.join(folder, FOLDER, "wikidata-lattice-series.json")

    def prepare(self, run):
        self.folder = run.folder
        self.base = run.commons.setting("bulk:url:wikidata-lattice")       # tests: a local answer file
        names = WikidataDump(1).catalogue(run.folder, fetch=not (self.base or "").startswith("file://"))
        self.names = {pid: names.get(pid) or default for pid, default in self.NAMES.items()}
        db = sqlite3.connect(shard_path(run.folder, self.key) + ".labels")
        db.execute("CREATE TABLE IF NOT EXISTS labels (q INTEGER PRIMARY KEY, label TEXT NOT NULL)")
        db.commit()
        return {"_labeldb": db}

    def _query(self, q, state):
        """one SPARQL query, paced: the pause after it is 1.2 times its own time (at least GAP_S) — under half of the query
        service's per-client allowance; a refusal doubles the pause"""
        last, gap = state.get("_last", 0), state.get("_gap", self.GAP_S)
        if last and time.time() - last < gap:
            time.sleep(gap - (time.time() - last))
        t0 = time.time()
        for attempt in range(6):
            try:
                req = urllib.request.Request(self.ENDPOINT, data=urllib.parse.urlencode({"query": q, "format": "json"}).encode(),
                                             headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
                with urllib.request.urlopen(req, timeout=180) as r:
                    body = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code not in REFUSED + (502, 504):
                    raise
                if attempt == 5:
                    raise Busy("Wikidata's query service asked us to slow down (HTTP %d); the lattice continues on the next run" % e.code)
                state["_gap"] = gap = min(self.MAX_GAP_S, max(gap * 2, 10))
                time.sleep(max(gap, _retry_after(e)))
        state["_last"] = time.time()
        state["_gap"] = max(self.GAP_S, min(self.MAX_GAP_S, max(1.2 * (time.time() - t0), state.get("_gap", self.GAP_S) * 0.75)))
        return body["results"]["bindings"]

    def discover(self, folder, state, fetch=True):
        """{link: [[series qid, editions], ...]}, kept beside the shards for a week"""
        path = self.discovery_path(folder)
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            if not fetch or time.time() - d.get("read", 0) < 7 * 86400:
                return d
        except (OSError, ValueError):
            if not fetch:
                return {"read": 0, "date": "none", "links": {}}
        d = {"read": time.time(), "date": core.now_iso()[:10], "links": {}}
        for link, q in self.DISCOVER.items():
            rows = self._query(q % self.MIN_EDITIONS, state)
            d["links"][link] = sorted([b["s"]["value"].rsplit("/", 1)[-1], int(b["n"]["value"])] for b in rows)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(path + ".tmp", path)
        return d

    @classmethod
    def batches(cls, series):
        """[[qid, editions], ...] → groups of at most BATCH_SERIES series and BATCH_EDITIONS editions (a giant series alone)"""
        out, cur, n = [], [], 0
        for q, k in series:
            if cur and (len(cur) >= cls.BATCH_SERIES or n + k > cls.BATCH_EDITIONS):
                out.append(cur); cur, n = [], 0
            cur.append(q); n += k
        if cur:
            out.append(cur)
        return out

    def parts(self):
        fetch = not (self.base or "").startswith("file://")
        d = self.discover(self.folder, {}, fetch)
        out = []
        for link in self.LINKS:
            bs = self.batches(d["links"].get(link, []))
            for i, b in enumerate(bs, 1):
                out.append(("%s discovery %s batch %d of %d" % (d["date"], link, i, len(bs)), "%s#%s:%s" % (self.base or self.ENDPOINT, link, ",".join(b))))
        return out

    def rows(self, part, url, state):
        base, _, spec = url.partition("#")
        link, _, qs = spec.partition(":")
        if base.startswith("file://"):
            with _open(base) as r:
                rows = json.loads(r.read())["results"]["bindings"]
        else:
            rows = self._query(self.EDITION_Q % (" ".join("wd:" + q for q in qs.split(",")), link), state)
        METER.start(len(rows), "rows")
        return iter(self.edition_facts(rows, link, getattr(self, "names", None) or dict(self.NAMES), state))

    @staticmethod
    def _time(t, prec):
        tm = t if t[:1] in "+-" else "+" + t
        y, m, d = tm[1:].split("T")[0].rsplit("-", 2)
        y = ("-" if tm[0] == "-" else "") + y.lstrip("0").rjust(4, "0")
        return "%s-%s-%s" % (y, m, d) if prec >= 11 else "%s-%s" % (y, m) if prec == 10 else y

    @classmethod
    def edition_facts(cls, rows, link, names, state=None):
        """bindings → [(subject, predicate, object)] in the dump's own form, plus each edition's neighbours in date order"""
        out, seen, labels, when, series_of = [], set(), {}, {}, {}
        qid = lambda v: v.rsplit("/", 1)[-1]
        for b in rows:
            e = qid(b["e"]["value"])
            lab = (b.get("eLabel") or {}).get("value", "")
            if not lab or lab == e:
                continue
            labels[e] = lab
            subj = "%s (%s)" % (lab, e)
            for col, pid in cls.COLS:
                if isinstance(col, tuple):
                    if col[0] not in b:
                        continue
                    try:
                        v = cls._time(b[col[0]]["value"], int(b[col[1]]["value"]))
                    except (KeyError, ValueError):
                        continue
                    if pid in ("P585", "P580"):
                        when.setdefault(e, b[col[0]]["value"].lstrip("+"))
                elif col not in b:
                    continue
                elif pid == "P1132":
                    try:
                        n = float(b[col]["value"])
                    except ValueError:
                        continue
                    v = str(int(n)) if n == int(n) else str(n)
                else:
                    v = qid(b[col]["value"])
                    if not (v[:1] == "Q" and v[1:].isdigit()):
                        continue
                    if col == "s":
                        series_of.setdefault(e, set()).add(v)
                f = (subj, names.get(pid or link) or (pid or link), v)
                if f not in seen:
                    seen.add(f); out.append(f)
        by_series = {}
        for e, ss in series_of.items():
            if e in when:
                for sq in ss:
                    by_series.setdefault(sq, []).append((when[e], e))
        for sq, eds in by_series.items():                  # the lattice: each edition linked to its neighbours in date order
            eds.sort()
            for (_, a), (_, b2) in zip(eds, eds[1:]):
                for f in (("%s (%s)" % (labels[a], a), "next edition (by date)", b2), ("%s (%s)" % (labels[b2], b2), "previous edition (by date)", a)):
                    if f not in seen:
                        seen.add(f); out.append(f)
        if state is not None and state.get("_labeldb") is not None and labels:
            state["_labeldb"].executemany("INSERT OR REPLACE INTO labels(q, label) VALUES(?, ?)", [(int(q[1:]), l) for q, l in labels.items()])
            state["_labeldb"].commit()
        return out

    def facts(self, part, row, state):
        state.setdefault("_links", {})[row[0]] = "https://www.wikidata.org/wiki/" + row[0].rsplit("(", 1)[-1].rstrip(")")
        return [row]

    def link(self, subject):
        m = re.search(r"\((Q\d+)\)$", subject)
        return "https://www.wikidata.org/wiki/" + m.group(1) if m else None


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
        self.mirrors, self.sources, self.slots = list(self.MIRRORS), None, None

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

    # servers holding the identical dump file, with the connections each is asked for. Before use each one must report
    # exactly the same size and Last-Modified as the file the parts are cut from (so the bytes are the same edition).
    MIRRORS = [("https://dumps.wikimedia.your.org/other/wikibase/wikidatawiki/latest-all.json.gz", 4),
               ("https://ftp.acc.umu.se/mirror/wikimedia.org/other/wikibase/wikidatawiki/latest-all.json.gz", 3),
               ("https://dumps.wikimedia.org/other/wikibase/wikidatawiki/latest-all.json.gz", 2)]
    PRIMARY_CONNECTIONS = 2                 # Wikimedia's own server: a couple of connections per computer

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

    def _head_full(self, url):
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA}), timeout=30) as r:
            return int(r.headers["Content-Length"]), r.headers.get("Last-Modified") or ""

    def _sources(self, url):
        """(the file the parts are cut from, [(url, connections)] holding identical bytes)"""
        if url.startswith("file://"):
            return url, [(url, 1)]
        cands = [(url, self.PRIMARY_CONNECTIONS)] + [m for m in self.mirrors if m[0] != url]
        seen, base, ref = [], None, None
        for u, n in cands:
            try:
                size, lm = self._head_full(u)
            except urllib.error.HTTPError as e:
                if e.code in REFUSED:
                    seen.append((u, n, None))             # busy now: usable later if it holds the same file
                continue
            except Exception:
                continue
            if ref is None:
                base, ref = u, (size, lm)
                seen.append((u, n, ref))
            elif (size, lm) == ref:
                seen.append((u, n, ref))
        if ref is None:
            raise Busy("every server holding the Wikidata dump refused or failed to answer: paused, resumes on the next run")
        # a server that was busy at the check is only used if it is the official one (same file by definition)
        return base, [(u, n) for u, n, r in seen if r == ref or (r is None and u in (self.URL, self.MIRRORS[-1][0]))]

    def parts(self):
        url = self.base or self.URL
        url, self.sources = self._sources(url)
        self.size, self.edition = self._head(url)
        n = -(-self.size // self.PART)
        return [("%s part %04d of %04d" % (self.edition, i + 1, n), "%s#%d-%d" % (url, i * self.PART, min(self.size, (i + 1) * self.PART)))
                for i in range(n) if i % self.lanes == self.lane - 1]

    def prepare(self, run):
        self.base = run.commons.setting("bulk:url:wikidata-dump")      # a mirror or a local copy of the dump (and tests)
        try:                                                            # bulk:wikidata:mirrors = [[url, connections], ...] replaces the list
            self.mirrors = [tuple(m) for m in json.loads(run.commons.setting("bulk:wikidata:mirrors") or "null")] or list(self.MIRRORS)
        except (ValueError, TypeError):
            self.mirrors = list(self.MIRRORS)
        self.slots = Slots(run.folder, halt=run.stopped)
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
        sources = getattr(self, "sources", None) or [(base, self.PRIMARY_CONNECTIONS)]
        try:
            for line in gz_member_lines(base, a, b, sources, getattr(self, "slots", None)):
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
    for lane in list(range(1, WikidataDump.LANES + 1)) + ["lattice"]:
        p = shard_path(commons_folder, "wikidata-dump-%d" % lane if lane != "lattice" else "wikidata-lattice") + ".labels"
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
    return {d.key: d for d in (PubChem(), Taxonomy(), Weather(), GNIS(), FoodData(), Tatoeba(), Calendar(), Series(), MitOcw()) + tuple(WikidataDump(k) for k in range(1, WikidataDump.LANES + 1)) + (WikidataLattice(),)}


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


class WriteSlots(Slots):
    """at most N agents write to the data drive at once. Many agents writing to one hard disk at the same time make it
    seek between them all the time (1 Nov 2026: a USB disk fell to about 1 MB/s with 28 writers); the others go on reading
    and parsing meanwhile and write when a slot is free. 0 = no limit (an internal SSD)."""

    def __init__(self, commons_folder, n):
        super().__init__(commons_folder)
        self.n = max(0, int(n or 0))

    def take(self):
        if not self.n:
            return None
        t = _NS()
        while True:
            for i in range(self.n):
                f = self._lock("disk-write", i)
                if f:
                    TR.add("disk_wait", _NS() - t)    # congestion at the drive, measured
                    return f
            time.sleep(0.05)


def write_slots(commons):
    """the setting bulk:write_slots, else automatic: 2 when the shared folder is on another drive than the system's own
    (an external disk), no limit on the system drive"""
    v = commons.setting("bulk:write_slots")
    if v not in (None, ""):
        return int(v)
    drive = os.path.splitdrive(os.path.abspath(commons.folder))[0].upper()
    system = (os.environ.get("SystemDrive") or "").upper()
    return 2 if drive and system and drive != system else 0


class Shard:
    wslots = None

    def __init__(self, commons_folder, key):
        os.makedirs(os.path.join(commons_folder, FOLDER), exist_ok=True)
        self.db = sqlite3.connect(shard_path(commons_folder, key), timeout=60)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")                 # WAL + NORMAL: a crash never corrupts or splits a batch
        self.db.execute("PRAGMA cache_size=-%d" % (CACHE_MB * 1024))   # a whole batch's dirty pages stay in memory until commit
        self.db.execute("PRAGMA journal_size_limit=%d" % (256 << 20))  # the WAL file shrinks back after each checkpoint
        self.db.execute("PRAGMA wal_autocheckpoint=20000")           # fewer, larger checkpoints: far fewer seeks on a hard disk
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
        t = _NS()
        rows.sort(key=_FP)
        t1 = _NS(); TR.add("sort", t1 - t, len(rows)); self.walls = {"sorted": _WALL()}
        slot = self.wslots.take() if self.wslots else None
        try:
            return self._write(part_id, rows, rows_done, links, before, t1)
        finally:
            if slot is not None:
                self.wslots.release(slot)

    def _write(self, part_id, rows, rows_done, links, before, t1):
        self.db.executemany("INSERT OR IGNORE INTO facts(fp, s, p, o, part, row) VALUES(?,?,?,?,?,?)", rows)
        new = self.db.total_changes - before
        t2 = _NS(); TR.add("db_insert", t2 - t1, len(rows)); self.walls["inserted"] = _WALL()
        if links:
            self.db.executemany("INSERT OR IGNORE INTO links(fp, url) VALUES(?, ?)", links)
        t3 = _NS(); TR.add("db_links", t3 - t2, len(links or ()))
        self.db.execute("UPDATE parts SET rows = ?, facts = facts + ? WHERE id = ?", (rows_done, new, part_id))
        total = (self.meta("facts", 0) or 0) + new
        self.set_meta("facts", total)
        now = time.time()
        self.db.execute("INSERT OR REPLACE INTO progress(at, facts) VALUES(?, ?)", (now, total))
        self.db.execute("DELETE FROM progress WHERE at < ?", (now - 2 * 86400,))
        t4 = _NS(); TR.add("db_progress", t4 - t3)
        self.db.commit()                                              # the disk: WAL append (+ checkpoint now and then)
        TR.add("db_commit", _NS() - t4, 1, len(rows)); self.walls["committed"] = _WALL()
        return new


# ------------------------------------------------------------------------------------------------ one agent
class Run:
    """what an agent needs: the Commons (registry, master switch, harvest log), its shard, the stop signals"""

    def __init__(self, commons_folder, ds, max_rows=None):
        import qbcommons as cm
        self.folder, self.ds, self.max_rows = commons_folder, ds, max_rows
        # no whole-file check here: every agent (up to one per core) checking a shared database of millions of rows on an
        # external drive at once kept them all waiting at the start; the programs check it when they start
        self.commons = cm.Commons(commons_folder, ds.app, check=False)
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
    t_open = _NS()
    run = Run(commons_folder, ds, max_rows)
    TR.from_commons(run.commons, "bulk-%s-%d" % (key, os.getpid()), dataset=key)
    TR.add("open_commons", _NS() - t_open)
    t = _NS()
    sh = Shard(commons_folder, key)
    sh.wslots = WriteSlots(commons_folder, write_slots(run.commons))
    TR.add("open_shard", _NS() - t)
    TR.event("run", phase="start", dataset=key, app=ds.app, sample=TR.sample, max_rows=max_rows, folder=commons_folder)
    fpr = fingerprinter(AREA[ds.app])
    sh.set_meta("state", "running"); sh.set_meta("pid", os.getpid()); sh.set_meta("started", core.now_iso()); sh.set_meta("error", None)
    sh.db.commit()
    why = run.stopped()
    if why:
        sh.set_meta("state", "blocked" if "registry" in why else "stopped"); sh.set_meta("error", why); sh.db.commit()
        if "registry" in why:
            run.log("all parts", 0, 0, 0, 0, 0, "blocked", why)
        TR.event("run", phase="end", dataset=key, state="blocked" if "registry" in why else "stopped", why=why)
        TR.close()
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
            t = _NS()
            rows, end = iter(ds.rows(name, url, state)), object()
            pg = {"part": name, "part_no": part_no, "parts": len(plist), "since": time.time(), "done_at_start": None}
            while row_no < done_rows and next(rows, end) is not end:    # resume: skip what an earlier run already saved
                row_no += 1
            TR.add("resume_skip", _NS() - t, max(0, row_no))
            TR.event("part", phase="start", dataset=key, part=name, part_no=part_no, parts=len(plist), resume_row=row_no, url=str(url)[-120:])
            side = shard_path(commons_folder, key) + ".progress"
            _mark(sh, pg, row_no, side); sh.db.commit()
            facts_of, preds, rule, add = ds.facts, sh.preds, ds.rule, buf.append
            tr_on, sampled, pending = TR.on, TR.sampled, []
            bt = {"first_row": None, "row_from": row_no, "net0": METER.done}
            t_src = _NS()
            for raw in rows:
                t_row = _NS()
                TR.add("source", t_row - t_src)       # read + decompress + parse of this row (network waits included)
                if bt["first_row"] is None:
                    bt["first_row"] = _WALL()
                try:
                    found = facts_of(name, raw, state)
                except Exception as e:                 # one bad row is reported and skipped, never the whole part
                    TR.fail("rule", e, dataset=key, part=name, row=row_no, raw=str(raw)[:300])
                    found = ()
                t_rule = _NS()
                TR.add("rule", t_rule - t_row, 1, len(found))
                if flt:                                 # the Control Panel's filter binds bulk facts too
                    kept = [f for f in found if ctl.check_item({"subject": f[0], "predicate": f[1], "object": f[2], "evidence": ev}, flt, area) is None]
                    filtered += len(found) - len(kept)
                    found = kept
                    TR.add("filter", _NS() - t_rule, len(found))
                lk = state.get("_links")
                t_fp = 0
                for s, p, o in found:
                    if s and o:
                        t1 = _NS()
                        f = fpr(s, p, o)
                        t_fp += _NS() - t1
                        pi = preds.get(p)
                        if pi is None:
                            pi = sh.pred(p, rule.get(p))
                        add((f, s, pi, o, pid, row_no))
                        if lk and s in lk:
                            links.append((f, lk[s]))
                        if tr_on and sampled(f):        # this record is followed from the first byte to the commit
                            w = _WALL()
                            pending.append({"fp": f.hex(), "dataset": key, "part": name, "row": row_no, "s": str(s)[:120], "p": p,
                                            "o": str(o)[:120], "w": {"chunk": TR.chunk_wall or None, "decompressed": TR.decomp_wall or None,
                                                                    "row": w - (_NS() - t_row), "rule": w - (_NS() - t_rule), "buffered": w}})
                t_src = _NS()
                TR.add("fingerprint", t_fp, len(found))
                TR.add("buffer", t_src - t_rule - t_fp)
                row_no += 1
                if not row_no & 0x1FFFF:                # about every 130,000 rows: the meter into a side file (no commit)
                    with qt.timed("progress_mark"):
                        _mark(None, pg, row_no, side)
                if len(buf) >= BATCH:
                    with qt.timed("progress_mark"):
                        _mark(sh, pg, row_no, side)
                    new = _batch(sh, pid, buf, row_no, links, pending, bt, key, name)
                    total_new += new; log_new += new; buf, links, pending = [], [], []
                    add = buf.append
                    bt = {"first_row": None, "row_from": row_no, "net0": METER.done}
                    if log_new >= LOG_EVERY:
                        with qt.timed("harvest_log"):
                            run.log(name, log_from, row_no, row_no - log_from, log_new, time.time() - t0)
                        log_from, log_new, t0 = row_no, 0, time.time()
                    with qt.timed("stop_check"):
                        why = run.stopped()
                    if why:
                        raise _Stop(why)
                    t_src = _NS()
                if limit is not None and row_no >= limit:
                    break
            with qt.timed("progress_mark"):
                _mark(sh, pg, row_no, side)
            new = _batch(sh, pid, buf, row_no, links, pending, bt, key, name)
            total_new += new; log_new += new
            TR.event("part", phase="end", dataset=key, part=name, rows=row_no, new=total_new)
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
        TR.event("run", phase="end", dataset=key, state="done" if all_done else "paused", new=total_new, filtered=filtered,
                 seconds=round(time.time() - t_start, 2))
        return {"dataset": key, "state": "done" if all_done else "paused", "new": total_new, "filtered": filtered,
                "seconds": round(time.time() - t_start, 1)}
    except _Stop as e:
        sh.set_meta("state", "stopped"); sh.set_meta("error", str(e)); sh.db.commit()
        TR.event("run", phase="end", dataset=key, state="stopped", why=str(e), new=total_new, seconds=round(time.time() - t_start, 2))
        return {"dataset": key, "state": "stopped", "why": str(e), "new": total_new}
    except Busy as e:
        sh.set_meta("state", "paused"); sh.set_meta("error", str(e)); sh.db.commit()
        run.log("source busy", 0, 0, 0, 0, time.time() - t_start, "failed", str(e))
        TR.fail("source busy", e, retried=True, dataset=key)
        TR.event("run", phase="end", dataset=key, state="paused", why=str(e), new=total_new, seconds=round(time.time() - t_start, 2))
        return {"dataset": key, "state": "paused", "why": str(e), "new": total_new, "retry": True}
    except Exception as e:
        TR.fail("agent", e, dataset=key)
        import http.client
        network = isinstance(e, (urllib.error.URLError, http.client.HTTPException, ConnectionError, TimeoutError)) and \
            getattr(e, "errno", None) not in (28,)                      # ENOSPC (disk full) is not the network
        sh.set_meta("state", "paused" if network else "failed")
        sh.set_meta("error", "%s: %s%s" % (type(e).__name__, str(e)[:300], " — retried automatically" if network else "")); sh.db.commit()
        TR.event("run", phase="end", dataset=key, state="paused" if network else "failed", why=str(e)[:300], new=total_new,
                 seconds=round(time.time() - t_start, 2))
        return {"dataset": key, "state": "paused" if network else "failed", "why": str(e)[:300], "new": total_new, "retry": network}
    finally:
        TR.flush_stages(dataset=key)
        TR.close()
        sh.db.close()


def _batch(sh, pid, buf, row_no, links, pending, bt, key, part):
    """write one batch, then log its timeline, the stage totals since the last batch and the records followed in it"""
    n_offered = len(buf)
    new = sh.write(pid, buf, row_no, links)
    if not TR.on:
        return new
    w = getattr(sh, "walls", {})
    if pending:
        got = dict(sh.db.execute("SELECT fp, part || ':' || row FROM facts WHERE fp IN (%s)" % ",".join("?" * len(pending)),
                                 [bytes.fromhex(r["fp"]) for r in pending]))
        for r in pending:
            r["w"].update(w)
            here = got.get(bytes.fromhex(r["fp"]))
            r["outcome"] = "new" if here == "%d:%d" % (pid, r["row"]) else "duplicate" if here else "missing"
            TR.record(r)
    TR.event("batch", dataset=key, part=part, row_from=bt["row_from"], row_to=row_no, offered=n_offered, new=new,
             first_row=bt["first_row"], last_row=_WALL(), **{k: w.get(k) for k in ("sorted", "inserted", "committed")},
             source_progress=METER.done - bt["net0"], unit=METER.unit)
    TR.flush_stages(dataset=key, part=part, row=row_no)
    return new


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
            _replace(side + ".tmp", side, tries=5)
        except OSError:
            pass


class _Stop(Exception):
    pass


class Busy(Exception):
    """the publisher asked us to slow down: the dataset pauses (what is saved stays saved) and resumes on the next run"""


_VERSIONS = {}


def _version(url):
    """the file's version as its publisher states it (Last-Modified), so every fact can be traced to one edition
    (asked once per file per process: many parts share one file)"""
    if not url.startswith("http"):
        return url and "local file"
    base = url.split("#", 1)[0]
    if base in _VERSIONS:
        return _VERSIONS[base]
    try:
        with urllib.request.urlopen(urllib.request.Request(base, method="HEAD", headers={"User-Agent": UA}), timeout=30) as r:
            _VERSIONS[base] = r.headers.get("Last-Modified") or ""
    except Exception:
        return ""
    return _VERSIONS[base]


def _agent(args):
    folder, key, max_rows = args
    try:
        return run_dataset(folder, key, max_rows)
    except Exception as e:                      # never lets one agent's surprise end the whole run: it is retried later
        return {"dataset": key, "state": "paused", "why": "%s: %s" % (type(e).__name__, str(e)[:300]), "new": 0, "retry": True}


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
    TR.configure(os.path.join(commons_folder, "trace"), "runner-%d" % os.getpid(), on=True)
    TR.event("run", phase="start", role="runner", agents=agents, datasets=keys, cores=os.cpu_count())

    def beat(note):
        # a heartbeat that cannot be written this second (the Control Panel was reading it, or the drive was busy) is
        # skipped, never fatal: in 1.15 one such moment on Windows ended the whole run
        try:
            with open(hb + ".tmp", "w") as f:
                json.dump({"heartbeat": time.time(), "pid": os.getpid(), "agents": agents, "datasets": keys, "note": note,
                           "results": results[-200:]}, f)
            _replace(hb + ".tmp", hb)
        except OSError as e:
            TR.fail("heartbeat", e, retried=True)
    beat("starting")
    todo, rounds = list(keys), 0
    while todo:
        got = []
        with multiprocessing.Pool(max(1, min(agents, len(todo)))) as pool:
            pending = pool.imap_unordered(_agent, [(commons_folder, k, max_rows) for k in todo])
            while True:
                try:
                    got.append(pending.next(timeout=2))
                    beat("%d of %d datasets finished this run" % (len(results) + len(got), len(keys)))
                except multiprocessing.TimeoutError:
                    beat("running")
                except StopIteration:
                    break
        results.extend(got)
        # datasets a server refused or the network dropped are run again after a pause — they resume where they stopped
        todo = [r["dataset"] for r in got if r.get("retry")]
        rounds += 1
        TR.event("round", round=rounds, finished={r["dataset"]: r.get("state") for r in got}, retry=todo)
        if not todo or rounds > RETRY_ROUNDS or os.path.exists(stop):
            break
        until = time.time() + RETRY_WAIT_S
        while time.time() < until and not os.path.exists(stop):
            beat("waiting to retry %d dataset(s) a server refused or the network dropped (round %d)" % (len(todo), rounds))
            time.sleep(2)
        if os.path.exists(stop):
            break
    beat("removing duplicates across shards")
    t = time.time()
    try:
        gone = dedupe(commons_folder)
    except sqlite3.Error as e:
        TR.fail("dedupe", e)
        gone = {"error": str(e)}
    TR.event("dedupe", seconds=round(time.time() - t, 2), removed=gone)
    TR.event("run", phase="end", role="runner", rounds=rounds, results=[{k: r.get(k) for k in ("dataset", "state", "new", "why")} for r in results if "dataset" in r])
    TR.close()
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
                t_d = time.time()
                before = sh.db.total_changes
                sh.db.execute("DELETE FROM links WHERE fp IN (SELECT fp FROM e.facts)")
                links = sh.db.total_changes - before
                sh.db.execute("DELETE FROM facts WHERE fp IN (SELECT fp FROM e.facts)")
                gone += sh.db.total_changes - before - links
                sh.db.commit()
                TR.event("dedupe_pair", shard=kj, against=ki, removed=sh.db.total_changes - before - links, seconds=round(time.time() - t_d, 3))
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


_STATUS = {}
_STATUS_LOCK = __import__("threading").Lock()


def status_cached(commons_folder, commons=None, max_age=10.0):
    """status(), at most every max_age seconds; while one is being computed (a busy drive) the last one is given at once.
    The Control Panel asks every 2 seconds — on a saturated drive each full status took longer than that and piled up."""
    hit = _STATUS.get(commons_folder)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    if not _STATUS_LOCK.acquire(blocking=hit is None):
        return hit[1]
    try:
        val = status(commons_folder, commons)
        _STATUS[commons_folder] = (time.time(), val)
        return val
    finally:
        _STATUS_LOCK.release()


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
    _launch(commons.folder, keys, agents, program_dir)
    with commons.store.write() as db:
        commons.agent_log(db, "engine", "Bulk harvesting started: %s (%d agents)" % (", ".join(keys), agents))
    return {"summary": "bulk harvesting is starting: %d dataset(s), %d agent(s)" % (len(keys), agents), **status(commons.folder, commons)}


def _launch(commons_folder, keys, agents, program_dir):
    import subprocess
    path = os.path.join(program_dir, "qbbulk.py")
    kw = {"creationflags": 0x08000000 | 0x00000200} if os.name == "nt" else {"start_new_session": True}
    subprocess.Popen([sys.executable, path, "run", "--commons", commons_folder, "--datasets", ",".join(keys), "--agents", str(agents)],
                     cwd=program_dir, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)


def full_speed(commons, program_dir, why="Start all harvesting", launch=None):
    """the master switch's own start: every approved dataset, one agent per core (as the Control Panel's ⚡ Full speed) —
    the path that brings in tens of millions of facts. Nothing to do when the agents already run."""
    if _alive(commons.folder):
        return {"bulk": "already running"}
    if os.environ.get("QB_OFFLINE") and launch is None:      # self-tests never download
        return {"bulk": "offline"}
    keys = [k for k, ds in catalog().items() if not ds.source or commons.registry.check(ds.source)[0]]
    if not keys:
        return {"bulk": "no approved dataset"}
    import qbcontrol as ctl, qbkeystone as ks
    keys = ks.order(keys, commons.folder, commons, ctl.get(commons, "target"))
    folder = os.path.join(commons.folder, FOLDER)
    os.makedirs(folder, exist_ok=True)
    try:
        os.remove(os.path.join(folder, "_runner.stop"))
    except OSError:
        pass
    (launch or _launch)(commons.folder, keys, MAX_AGENTS, program_dir)
    with commons.store.write() as db:
        commons.agent_log(db, "engine", "%s: bulk agents started at full speed (%d datasets, %d agents)" % (why, len(keys), MAX_AGENTS))
    return {"bulk": "started", "datasets": len(keys), "agents": MAX_AGENTS}


def runner_state(commons_folder):
    try:
        with open(os.path.join(commons_folder, FOLDER, "_runner.json")) as f:
            rs = json.load(f)
    except (OSError, ValueError):
        return {"running": False, "note": "never started"}
    return {"running": _alive(commons_folder), "note": rs.get("note"), "agents": rs.get("agents"), "datasets": len(rs.get("datasets") or [])}


RESUME_GAP_S = 600                 # at most one automatic restart every 10 minutes


def resume_if_crashed(commons, program_dir, now=None, launch=None):
    """the runner ended without finishing (the computer slept, the window was closed, the drive dropped out) and nobody
    pressed Stop: start it again on the same datasets — every agent resumes where its shard stopped. Returns what it did,
    or None. (Since 1.23 the red Stop is the only way to stop the agents; the old master switch no longer applies.)"""
    import qbharvest as hv
    folder = os.path.join(commons.folder, FOLDER)
    now = now or time.time()
    try:
        with open(os.path.join(folder, "_runner.json")) as f:
            rs = json.load(f)
    except (OSError, ValueError):
        return None
    if rs.get("note") == "finished" or now - rs.get("heartbeat", now) < 60 or os.path.exists(os.path.join(folder, "_runner.stop")):
        return None
    mark = os.path.join(folder, "_runner.resumed")
    try:
        if now - os.path.getmtime(mark) < RESUME_GAP_S:
            return None
    except OSError:
        pass
    keys = [k for k in (rs.get("datasets") or []) if k in catalog()]
    if not keys:
        return None
    open(mark, "w").close()
    (launch or _launch)(commons.folder, keys, int(rs.get("agents") or MAX_AGENTS), program_dir)
    with commons.store.write() as db:
        commons.agent_log(db, "engine", "Bulk harvesting resumed by itself: the runner had stopped without finishing (last: %s)"
                          % (rs.get("note") or "?"))
    return {"resumed": keys, "agents": int(rs.get("agents") or MAX_AGENTS), "last_note": rs.get("note")}


def stop(commons):
    folder = os.path.join(commons.folder, FOLDER)
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "_runner.stop"), "w").close()
    return {"summary": "every bulk agent stops after its current batch (it resumes there next time)", **status(commons.folder, commons)}


def add_routes(api, commons, program_dir):
    commons.registry.ensure()
    @api.get("/api/bulk")
    def bulk_status(p):
        return status_cached(commons.folder, commons)

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

    # -- instrumentation: the trace logs analysed, exported, the drives compared
    tfolder = lambda: os.path.join(commons.folder, "trace")

    @api.get("/api/trace/report")
    def trace_report(p):
        hours = float(p.get("hours") or 2)              # the last 2 hours by default: hours of logs from 28 agents are big
        files = []
        cut = time.time() - hours * 3600
        if os.path.isdir(tfolder()):
            files = [os.path.join(tfolder(), f) for f in sorted(os.listdir(tfolder()))
                     if f.endswith((".jsonl", ".jsonl.gz")) and os.path.getmtime(os.path.join(tfolder(), f)) >= cut]
        t0 = time.time()
        o = qt.analyze(l for l in qt.read_lines(files, since_ns=int(cut * 1e9), max_seconds=90))
        return {"report": o, "text": "Last %g hour(s) of logs, %d file(s), analysed in %s s\n\n" % (hours, len(files), round(time.time() - t0, 1))
                + qt.text_report(o), "files": len(files), "folder": tfolder(),
                "settings": {"on": (commons.setting("trace:on", "on") or "on") != "off", "sample": int(commons.setting("trace:sample", qt.DEFAULT_SAMPLE) or 0)}}

    @api.post("/api/trace/export")
    def trace_export(p):
        path, n, raw = qt.export(tfolder(), days=float(p.get("days") or 0) or None)
        return {"zip": path, "files": n, "mb": round(raw / 1e6, 1), "zip_mb": round(os.path.getsize(path) / 1e6, 1),
                "summary": "%d log file(s) packed into %s — send this file for analysis" % (n, path)}

    @api.post("/api/trace/settings")
    def trace_settings(p):
        if "on" in p:
            commons.set_setting("trace:on", "on" if p.get("on") in (True, "true", "on", 1) else "off")
        if p.get("sample") is not None:
            commons.set_setting("trace:sample", max(0, int(p["sample"])))
        return {"on": commons.setting("trace:on", "on") != "off", "sample": int(commons.setting("trace:sample", qt.DEFAULT_SAMPLE) or 0),
                "summary": "applies to agents started from now on"}

    @api.post("/api/trace/drives")
    def trace_drives(p):
        """the internal drive (the user's home folder, C: on Windows) against the data folder's drive (e.g. D:\\QB)"""
        folders = {"internal drive (%s)" % os.path.splitdrive(os.path.expanduser("~"))[0] or os.path.expanduser("~"): os.path.expanduser("~"),
                   "data drive (%s)" % (os.path.splitdrive(commons.folder)[0] or commons.folder): os.path.dirname(commons.folder)}
        for extra in (p.get("folders") or []):
            folders[extra] = extra
        r = qt.compare_storage(folders, mb=int(p.get("mb") or 256), rows=int(p.get("rows") or 300_000))
        t = qt.Tracer().configure(tfolder(), "drives-%d" % os.getpid())
        t._line(dict(r, ev="storage", proc=t.proc), now=True)
        t.close()
        return r

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
    rs = st["runner"]
    alive = rs.get("alive")
    add("Bulk agents running", alive, ("running: %s" % rs.get("note")) if alive else
        ("not running (last: %s)" % (rs.get("note") or "never started")),
        "Bulk harvesting tab → ⚡ Full speed. The agents then run for hours (Wikidata) and stop by themselves. Since 1.16 the "
        "Control Panel restarts agents that ended without finishing (while the master switch is on), within a minute or so.")
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
        "'switched off' → master switch; 'HTTP 429 Too Many Requests' → the server asked to slow down: since 1.14 the agents share a few "
        "connections per server, spread over the Wikidata mirrors and retry by themselves — press ⚡ Full speed to resume; "
        "another network error → check the server's internet connection or firewall.")
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
    ws = write_slots(commons)
    add("Agents writing to the data drive at once", True,
        ("%d at a time (the shared folder is on another drive than the system's: an external disk slows down badly when many "
         "agents write at once; the others keep reading and parsing meanwhile)" % ws) if ws else "no limit (system drive)",
        "Setting bulk:write_slots (0 = no limit).")
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
        c.set_setting("trace:sample", 7)
        try:
            r1 = run_dataset(cf, "pubchem-computed", max_rows=1500)
            r2 = run_dataset(cf, "pubchem-computed")
        finally:
            BATCH = old
        import threading as _th
        ws = WriteSlots(cf, 1)
        a = ws.take(); got = []
        th = _th.Thread(target=lambda: got.append(ws.take())); th.start(); time.sleep(0.4)
        waited = not got
        ws.release(a); th.join(5); ws.release(got[0] if got else None)
        c.set_setting("bulk:write_slots", 3)
        ok("write slots: with 1 slot a second agent waits for the drive until the first has written; the setting is read",
           waited and got and write_slots(c) == 3)
        t0 = time.time(); s1 = status_cached(cf, c); s2 = status_cached(cf, c)
        ok("the Control Panel's status is computed at most every 10 s (the second ask is instant)", s1 is s2 and time.time() - t0 < 30)
        old_ns = int((time.time() + 3600) * 1e9)
        ok("analysis reads only the hours asked for", list(qt.read_lines([os.path.join(cf, "trace")], since_ns=old_ns)) == [])
        tl = list(qt.read_lines([os.path.join(cf, "trace")]))
        an = qt.analyze(tl)
        pc = next((d for d in an["datasets"] if d["dataset"] == "pubchem-computed"), None)
        ok("instrumentation: every batch, its stage times and the records followed end to end are logged and analysed",
           pc and pc["batches"] >= 3 and {"source", "rule", "fingerprint", "db_insert", "db_commit"} <= {x["stage"] for x in pc["stages"]}
           and an["records"] and an["records"]["followed"] > 0 and all(r.get("w", {}).get("committed") for r in tl if r["ev"] == "record"),
           (pc and pc["stages"], an["records"]))
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
        # the lattice (1.15): every series Wikidata knows, read in batches, written exactly as the dump lanes write facts
        W = "http://www.wikidata.org/entity/"
        ans = {"results": {"bindings": [
            {"e": {"value": W + "Q10"}, "eLabel": {"value": "1999 World Series"}, "s": {"value": W + "Q265538"}, "w": {"value": W + "Q213417"},
             "dt": {"value": "1999-10-23T00:00:00Z"}, "dp": {"value": "11"}, "cty": {"value": W + "Q30"}},
            {"e": {"value": W + "Q11"}, "eLabel": {"value": "2000 World Series"}, "s": {"value": W + "Q265538"}, "w": {"value": W + "Q213417"},
             "st": {"value": "2000-10-21T00:00:00Z"}, "sp": {"value": "9"}, "n": {"value": "2"}},
            {"e": {"value": W + "Q12"}, "eLabel": {"value": "Q12"}, "s": {"value": W + "Q265538"}}]}}
        with open(os.path.join(tmp, "lattice.json"), "w") as f:
            json.dump(ans, f)
        with open(os.path.join(cf, FOLDER, "wikidata-lattice-series.json"), "w") as f:
            json.dump({"read": time.time(), "date": "2026-10-31", "links": {"P3450": [["Q265538", 3]], "P179": [], "P31": []}}, f)
        c.set_setting("bulk:url:wikidata-lattice", url("lattice.json"))
        rl = run_dataset(cf, "wikidata-lattice")
        sh_ = sqlite3.connect(shard_path(cf, "wikidata-lattice"))
        lf = {(a, p_, o) for a, p_, o in sh_.execute("SELECT f.s, pr.name, f.o FROM facts f JOIN predicates pr ON pr.id = f.p")}
        sh_.close()
        ok("lattice: editions read in one batch, in the dump's own form (Q-id objects, dates at their precision)",
           rl["state"] == "done" and {("1999 World Series (Q10)", "winner", "Q213417"), ("1999 World Series (Q10)", "point in time", "1999-10-23"),
                                      ("2000 World Series (Q11)", "start time", "2000"), ("2000 World Series (Q11)", "number of participants", "2"),
                                      ("1999 World Series (Q10)", "sports season of league or competition", "Q265538")} <= lf, (rl, sorted(lf)))
        ok("lattice: each edition is linked to the one before and after it; a nameless edition is skipped",
           ("1999 World Series (Q10)", "next edition (by date)", "Q11") in lf and ("2000 World Series (Q11)", "previous edition (by date)", "Q10") in lf
           and not any(a.endswith("(Q12)") for a, _p, _o in lf))
        fpd = fingerprinter("history")
        ok("lattice: a fact the dump also holds has the same fingerprint (so one copy is kept)",
           fpd("1999 World Series (Q10)", "winner", "Q213417") == fp("history", "1999 World Series (Q10)", "winner", "Q213417"))
        ok("lattice: batches of at most 200 series and 1,500 editions; a giant series alone",
           WikidataLattice.batches([["Q1", 1000], ["Q2", 600], ["Q3", 5], ["Q4", 3000]]) == [["Q1"], ["Q2", "Q3"], ["Q4"]])
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
        ok("series: a slot is filled only from the source's answer (plus its place in the lattice)",
           f == [("Nobel Prize in Physics 1921", "edition of", "Nobel Prize in Physics"), ("Nobel Prize in Physics 1921", "laureate", "Albert Einstein")], f)
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
        # polite downloading (1.14): connection slots per server, a refusing server cools down, identical mirrors carry on
        sl = Slots(tmp)
        st0 = {"now": False}
        a1, a2 = sl.acquire([("https://a.example/f", 2)], st0), sl.acquire([("https://a.example/f", 2)], st0)
        a3 = sl.acquire([("https://a.example/f", 2), ("https://b.example/f", 1)], st0)
        ok("slots: at most N connections per server; the next agent takes another server", a1[0] == a2[0] == "https://a.example/f"
           and a3[0] == "https://b.example/f", (a1[0], a2[0], a3[0]))
        for x in (a1, a2, a3):
            sl.release(x[1])
        blob = bytes(range(256)) * 4096
        calls = []

        class _R:
            def __init__(self, data):
                self.data, self.status = data, 206
            def read(self, n):
                d, self.data = self.data[:n], self.data[n:]
                return d
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        def fake(req, timeout=None):
            u = req.full_url
            calls.append(_host(u))
            if "a.example" in u:
                raise urllib.error.HTTPError(u, 429, "Too Many Requests", {"Retry-After": "300"}, None)
            start = int(req.headers["Range"].split("=")[1].split("-")[0])
            return _R(blob[start:])
        urllib.request.urlopen, time.sleep = fake, (lambda s: None)
        try:
            got = b"".join(_ranged("https://a.example/f", 1000, {"now": False}, [("https://a.example/f", 2), ("https://b.example/f", 1)], Slots(tmp)))
        finally:
            urllib.request.urlopen, time.sleep = real_open, real_sleep
        ok("a server that answers 429 cools down (Retry-After honoured) and a mirror with the same file carries on — same bytes",
           got == blob[1000:] and calls[:2] == ["a.example", "b.example"] and Slots(tmp).cooling("a.example") > 250, (len(got), calls[:4]))
        wd = WikidataDump(1)
        heads = {"https://dumps.wikimedia.org/wikidatawiki/entities/latest-all.json.gz": (100, "Tue"), "https://m1.example/x.gz": (100, "Tue"),
                 "https://m2.example/x.gz": (99, "Tue"), "https://m3.example/x.gz": (100, "Mon")}
        wd.mirrors = [("https://m1.example/x.gz", 3), ("https://m2.example/x.gz", 3), ("https://m3.example/x.gz", 3)]
        wd._head_full = lambda u: heads[u]
        base, srcs = wd._sources(wd.URL)
        ok("mirrors are used only when they hold the identical file (same size and date)", base == wd.URL and
           [u for u, _ in srcs] == [wd.URL, "https://m1.example/x.gz"], srcs)
        def refuse(u):
            raise urllib.error.HTTPError(u, 429, "Too Many Requests", {}, None)
        wd._head_full = refuse
        try:
            wd._sources(wd.URL); held = False
        except Busy:
            held = True
        ok("when every server refuses, the dataset pauses (and the runner retries it) instead of failing", held)
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
        nlat = sqlite3.connect(shard_path(cf, "wikidata-lattice")).execute("SELECT count(*) FROM facts").fetchone()[0]
        ok("ticker: shard facts counted per area", ar["stem"]["facts"] == 6002 and ar["history"]["facts"] == 5 + 6 + nlat, ar)   # series + dump fixture + lattice
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
