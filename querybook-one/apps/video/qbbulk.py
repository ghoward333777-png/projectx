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
import bz2, csv, datetime, gzip, hashlib, http.client, io, json, operator, os, re, shutil, sqlite3, sys, tarfile, time, urllib.error, urllib.parse, urllib.request, zipfile, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qbcore as core  # noqa: E402
import qbscaffold as sc  # noqa: E402
import qbkeystone as ks  # noqa: E402
import qbdump  # noqa: E402  (download once, read locally: the Wikidata dump on the data drive)
import qbtrace as qt  # noqa: E402  (instrumentation: every stage, every I/O, every failure → <shared folder>/trace/*.jsonl)
TR, _NS, _WALL = qt.TR, qt._NS, qt._WALL

VERSION = "1.46.0"                 # the bulk engine; an engine of another version still running is replaced on Start
UA = "QueryBook-harvester/%s (+https://github.com/ghoward333777-png/projectx; personal research tool; bulk files, one stream per dataset)" % VERSION
BATCH = 500_000                    # facts per transaction: appended to the shard's stage (see Shard), so a batch costs the same
                                   # whatever the shard's size
STAGE_MIN = 5_000_000              # 1.33: staged facts are folded into the keyed tables once at least this many wait, or half
                                   # the shard's own size, whichever is more — and at the end of every part
STAGE_CAP = 20_000_000             # 1.35: …but never more than this at once. Half of a 100-million-fact shard is 50 million
                                   # facts in one transaction: hours on a data drive, the agent's write slot held all along,
                                   # and every other agent waiting for that slot — the "many hours, no facts" stall
MERGE_SLOTS_EXTERNAL, MERGE_SLOTS_SYSTEM = 1, 2   # 1.35: agents filing (folding a stage) at once — each takes MERGE_CACHE_MB
WAIT_MAX_S = 6 * 3600              # 1.35: an agent "waiting" this long with no progress at all is ended and restarted
CACHE_MB = 128                     # SQLite page cache per agent
MERGE_CACHE_MB = 1024              # 1.33: the page cache while a stage is folded in (the subject index cannot be visited in
                                   # order, so it must stay in memory or every insert reads a page); back to CACHE_MB after
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
        t_wait = time.time()
        while not stop["now"]:
            for url, n in sources:
                host = _host(url)
                if self.cooling(host):
                    continue
                for i in range(max(1, int(n))):
                    f = self._lock(host, i)
                    if f:
                        AGENT["waiting"] = None
                        return url, f
            AGENT["waiting"] = "a download connection"
            if time.time() - t_wait > SLOT_MAX_WAIT_S:   # re-route: give this agent's place to another dataset, come back later
                AGENT["waiting"] = None
                raise Busy("waited %d min for a download connection (the servers allow only a few at a time): another dataset "
                           "takes this place, this one comes back in a few minutes" % (SLOT_MAX_WAIT_S // 60))
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
        self.mirrors, self.sources, self.slots, self.local = list(self.MIRRORS), None, None, None

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
        if self.local:                         # the downloaded copy: named by its own edition, so parts done while
            self.edition = self.local["edition"]   # streaming the same edition are not read again
        n = -(-self.size // self.PART)
        mine = unread_first([i for i in range(n) if i % self.lanes == self.lane - 1], n, getattr(self, "covered", None))
        return [("%s part %04d of %04d" % (self.edition, i + 1, n), "%s#%d-%d" % (url, i * self.PART, min(self.size, (i + 1) * self.PART)))
                for i in mine]

    def prepare(self, run):
        self.base = run.commons.setting("bulk:url:wikidata-dump")      # a mirror or a local copy of the dump (and tests)
        try:                                                            # bulk:wikidata:mirrors = [[url, connections], ...] replaces the list
            self.mirrors = [tuple(m) for m in json.loads(run.commons.setting("bulk:wikidata:mirrors") or "null")] or list(self.MIRRORS)
        except (ValueError, TypeError):
            self.mirrors = list(self.MIRRORS)
        if not self.base and local_mode(run.commons):                 # 1.31: download once, read locally
            dumps = dumps_folder(run.folder, run.commons)
            r = dumps_ready(run.folder, run.commons)
            if not r:
                pg = qbdump.progress(dumps)
                state = WAITING + (" (%d%% downloaded%s)" % (round(100 * pg["share"]), ", about %d min left" % (pg["eta_s"] // 60)
                                                                    if pg.get("eta_s") else "") if pg else " (starting)")
                if not stream_while_downloading(run.commons):
                    raise Busy(state)
                # 1.32: the lane streams meanwhile instead of waiting (it waited, idle, for the whole 157 GB before);
                # the download and the lanes share each server's connections (Slots), and parts streamed now are
                # not read again from the copy, which is named by the same edition
                TR.event("download", note="%s: streaming over the internet while %s" % (self.key, state.replace(WAITING, "the download runs")))
            else:
                self.local, self.base = r, "file://" + urllib.request.pathname2url(r["path"])
        self.slots = Slots(run.folder, halt=run.stopped)
        if (run.commons.setting("bulk:wikidata:properties") or "all") == "all":
            self.props = self.catalogue(run.folder, fetch=not (self.base or "").startswith("file://"))
        db = sqlite3.connect(shard_path(run.folder, self.key) + ".labels")
        db.execute("CREATE TABLE IF NOT EXISTS labels (q INTEGER PRIMARY KEY, label TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS keystones (k TEXT PRIMARY KEY, facts INTEGER NOT NULL)")
        # 1.40 relevance: how well known each item is (the number of Wikipedias with an article about it), and the other
        # names people use for the well-known ones ("FDR", "The Babe") — what lets the Ask box choose the right "Babe Ruth"
        db.execute("CREATE TABLE IF NOT EXISTS fame (q INTEGER PRIMARY KEY, links INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS alias (name TEXT NOT NULL, q INTEGER NOT NULL, PRIMARY KEY (name, q)) WITHOUT ROWID")
        db.execute("CREATE TABLE IF NOT EXISTS names (word TEXT NOT NULL, q INTEGER NOT NULL, PRIMARY KEY (word, q)) WITHOUT ROWID")
        db.commit()
        try:                                             # 1.40: the positions of the dump no lane has ever finished come first
            self.covered = dump_positions_read(run.folder)
        except Exception:
            self.covered = None
        return {"_labeldb": db, "_labelbuf": [], "_famebuf": [], "_aliasbuf": [], "_namebuf": []}

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
        cb = state.get("_circlebuf")
        if cb:                                           # 1.46: the circle of what was read (how many point to it, its nearest ring)
            db.execute("CREATE TABLE IF NOT EXISTS circle (q INTEGER PRIMARY KEY, n INTEGER NOT NULL, ring INTEGER NOT NULL)")
            db.executemany("INSERT INTO circle(q, n, ring) VALUES(?, 1, ?) ON CONFLICT(q) DO UPDATE SET n = n + 1, ring = min(ring, excluded.ring)", cb)
            cb.clear()
        rb = state.get("_readbuf")
        if rb:
            db.execute("CREATE TABLE IF NOT EXISTS circle_read (q INTEGER PRIMARY KEY)")
            db.executemany("INSERT OR IGNORE INTO circle_read(q) VALUES(?)", rb)
            rb.clear()
        fb, ab = state.get("_famebuf"), state.get("_aliasbuf")
        if fb:
            db.executemany("INSERT OR REPLACE INTO fame(q, links) VALUES(?, ?)", fb)
            fb.clear()
        if ab:
            db.executemany("INSERT OR IGNORE INTO alias(name, q) VALUES(?, ?)", ab)
            ab.clear()
        nb = state.get("_namebuf")
        if nb:                                           # 1.43: the words of well-known names ("Dodgers" -> Los Angeles Dodgers)
            db.executemany("INSERT OR IGNORE INTO names(word, q) VALUES(?, ?)", nb)
            nb.clear()
        vb = state.get("_viewbuf")
        if vb:                                           # 1.41: Wikipedia page views, added up over the months sampled
            db.executemany("INSERT INTO views(q, views) VALUES(?, ?) ON CONFLICT(q) DO UPDATE SET views = views + excluded.views, months = months + 1", vb)
            vb.clear()
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
        return self.entity_facts(e, state)

    def entity_facts(self, e, state):
        """one Wikidata entity (as the dump and the API both give it) -> its facts, in the lanes' own form"""
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
            # 1.40 relevance: what the item IS in one line, the other names it goes by, and how well known it is
            links = len(e.get("sitelinks") or ())
            if links:
                d = ((e.get("descriptions") or {}).get("en") or {}).get("value")
                if d:
                    out.append((s, "description", d))
                fb = state.get("_famebuf")
                if fb is not None:
                    fb.append((int(q[1:]), links))
                if links >= FAME_ALIASES:
                    ab, nb = state.get("_aliasbuf"), state.get("_namebuf")
                    said = [lab]
                    for a in ((e.get("aliases") or {}).get("en") or ())[:12]:
                        v = (a.get("value") or "").strip()
                        if v and v != lab:
                            out.append((s, "also known as", v))
                            said.append(v)
                            if ab is not None:
                                ab.append((v.casefold(), int(q[1:])))
                    if nb is not None:                   # 1.43: every word of its names, so part of a name finds it
                        nb.extend((w, int(q[1:])) for w in name_words(" ".join(said)))
            state.setdefault("_links", {})[s] = "https://www.wikidata.org/wiki/" + q
            k = ks.entity_keystone(cls - {None}, claims.keys())
            if k:                                       # measured coverage per keystone domain (qbkeystone)
                kc = state.setdefault("_kc", {})
                kc[k] = kc.get(k, 0) + len(out)
        return out

    def link(self, subject):
        m = re.search(r"\((Q\d+)\)$", subject)
        return "https://www.wikidata.org/wiki/" + m.group(1) if m else None


WAITING = "waiting for the one download of the Wikidata dump to the data drive"


def stream_while_downloading(commons):
    """1.32: while the one download is not ready, the Wikidata lanes stream (sharing connections with it); the admin can
    set bulk:wikidata:while_downloading to wait, as 1.31 did"""
    return (commons.setting("bulk:wikidata:while_downloading") or "stream") != "wait"


def local_mode(commons):
    """download once, read locally (on unless the admin sets bulk:wikidata:local to off, which streams as before 1.31)"""
    return (commons.setting("bulk:wikidata:local") or "on") != "off"


INTERNAL_DUMP_ROOM = 450e9          # the internal drive holds the dump when it has this much free (two editions + the working copies)


def dumps_folder(commons_folder, commons=None):
    """where the dump is kept: the admin's choice (bulk:dumps:folder); else, when the working copies are on the internal
    drive (C:), beside them there if it has room — reading a 157 GB file with 16 lanes at once from a USB hard drive would
    make the data drive the slowest part again; else <shared folder>/dumps"""
    chosen = commons.setting("bulk:dumps:folder") if commons is not None else None
    if chosen:
        return qbdump.folder_for(commons_folder, chosen)
    w = work_dir(commons_folder)
    if w:
        internal = os.path.join(os.path.dirname(w), "dumps")
        if os.path.isdir(os.path.join(internal, "wikidata")):
            return internal
        try:
            base = next(p for p in (os.path.dirname(w), os.path.expanduser("~")) if os.path.isdir(p))
            if shutil.disk_usage(base).free >= INTERNAL_DUMP_ROOM:
                return internal
        except (OSError, StopIteration):
            pass
    return qbdump.folder_for(commons_folder)


def dumps_ready(commons_folder, commons=None):
    """the newest ready copy in the chosen folder or in <shared folder>/dumps (a copy made before the folder changed)"""
    rs = [r for r in (qbdump.ready(f) for f in dict.fromkeys((dumps_folder(commons_folder, commons), qbdump.folder_for(commons_folder)))) if r]
    return max(rs, key=lambda r: r.get("edition") or "") if rs else None


class WikidataDownload(Dataset):
    """the weekly Wikidata dump downloaded ONCE to the data drive (qbdump): every server holding the identical file at
    once, each within its own connection limit, checked against Wikimedia's published MD5. The 16 lanes then read that
    copy at disk speed. No facts of its own; finished, it looks for a new weekly edition once a day."""
    key, app, source = "wikidata-download", "facts", "wikidata"
    title = "Wikidata — one download of the dump to the data drive (the lanes read it from there)"
    licence = "CC0 1.0 (Wikidata)"
    why = "the dump fetched once instead of by 16 lanes over the internet: no lane waits for a connection"
    approx = "about 157 GB, once a week"
    standalone = True

    def sources(self, commons):
        try:
            mirrors = [tuple(m) for m in json.loads(commons.setting("bulk:wikidata:mirrors") or "null")] or list(WikidataDump.MIRRORS)
        except (ValueError, TypeError):
            mirrors = list(WikidataDump.MIRRORS)
        out, hosts = [], {}
        for u, n in [(WikidataDump.URL, WikidataDump.PRIMARY_CONNECTIONS)] + mirrors:
            h = _host(u)                                   # one server, one limit: two addresses on one host share it
            if h in hosts:
                out[hosts[h]] = (out[hosts[h]][0], max(out[hosts[h]][1], int(n)))
            else:
                hosts[h] = len(out); out.append((u, int(n)))
        return out

    def run_alone(self, run):
        r = self._run_alone(run)
        try:                                           # the page shows the last try and why (1.31.2: it said "not started")
            with open(os.path.join(run.folder, FOLDER, "_download_last.json"), "w") as f:
                json.dump(dict(r, at=time.time()), f)
        except OSError:
            pass
        return r

    def _run_alone(self, run):
        if not local_mode(run.commons) or run.commons.setting("bulk:url:wikidata-dump"):
            return {"dataset": self.key, "state": "done", "new": 0, "why": "not used: the lanes stream the dump (bulk:wikidata:local is off)"}
        why = run.stopped()
        if why:
            return {"dataset": self.key, "state": "blocked" if "registry" in why else "stopped", "why": why, "new": 0}
        dumps = dumps_folder(run.folder, run.commons)
        legacy = qbdump.folder_for(run.folder)
        if os.path.abspath(dumps) != os.path.abspath(legacy):     # a half download left on the data drive by 1.33.0: removed
            gone = qbdump.discard_partials(legacy)
            if gone:
                TR.event("download", note="half download on the data drive removed (now kept in %s): %s" % (dumps, ", ".join(gone)))

        # 1.40: finish the edition first. A new edition appears every week, the parts are named by their edition, so every
        # lane began again at part 1 each week — and with a week not being enough, the later parts were NEVER read: the
        # same first parts over and over (the drive working for nothing), whole stretches of Wikidata never in the store.
        cur = dumps_ready(run.folder, run.commons)
        if cur and (run.commons.setting("bulk:wikidata:chase_editions") or "off") != "on":
            pr = edition_progress(run.folder, cur.get("edition") or "")
            try:
                age = (time.time() - time.mktime(time.strptime(cur["edition"], "%Y-%m-%d"))) / 86400
            except (ValueError, KeyError, TypeError):
                age = 0
            if pr["total"] and pr["done"] < pr["total"] and age < KEEP_EDITION_DAYS:
                return {"dataset": self.key, "state": "done", "new": 0, "edition": cur.get("edition"),
                        "why": "keeping edition %s until every lane has read it (%d of %d parts done) — no new edition is fetched before that"
                               % (cur.get("edition"), pr["done"], pr["total"])}

        def meter(n):
            METER.done += n
        log = lambda *a: TR.event("download", note=" ".join(str(x) for x in a))
        try:
            r = qbdump.Download(dumps, self.sources(run.commons), meter=meter, stop=run.stopped, log=log,
                                min_free_gb=float(run.commons.setting("bulk:min_free_gb") or MIN_FREE_GB),
                                slots=Slots(run.folder, halt=run.stopped)).fetch()
        except qbdump.Busy as e:
            stop = "Control Panel" in str(e)
            return {"dataset": self.key, "state": "stopped" if stop else "paused", "why": str(e), "new": 0, "retry": not stop}
        if not r.get("already"):
            run.log("edition %s" % r["edition"], 0, 0, 0, 0, r.get("seconds") or 0, reason="downloaded to %s; %s" % (dumps, r["checked"]))
        return {"dataset": self.key, "state": "done", "new": 0, "edition": r["edition"], "why": "ready: %s" % r["checked"]}


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


PART_NAME_TOP = 6                  # how many of the best-known items found by part of their name are offered
FAME_ALIASES = 5                    # other names are kept for items with an article in at least this many Wikipedias
KEEP_EDITION_DAYS = 56             # an edition is kept until every lane has read it, at most this long
PART_NAME = re.compile(r"^(\S+) part (\d+) of (\d+)$")


def _lane_parts(commons_folder):
    """[(lane, edition, index (1-based), parts in that edition, done)] from every lane's own record of its parts"""
    out = []
    for lane in range(1, WikidataDump.LANES + 1):
        p = shard_path(commons_folder, "wikidata-dump-%d" % lane)
        if not os.path.exists(p):
            continue
        try:
            db = _ro(p)
            rows = db.execute("SELECT name, done FROM parts").fetchall()
            db.close()
        except sqlite3.Error:
            continue
        for name, done in rows:
            m = PART_NAME.match(name or "")
            if m:
                out.append((lane, m.group(1), int(m.group(2)), int(m.group(3)), bool(done)))
    return out


def unread_first(indices, n, covered):
    """a lane's parts of an edition of n parts, those at positions never read before (in any edition) first"""
    if not covered:
        return list(indices)
    read = {int(f * n + 1e-9) for f in covered}
    return sorted(indices, key=lambda i: (i in read, i))


def dump_positions_read(commons_folder):
    """the positions of the Wikidata dump (0..1, the start of each part) that some lane has read to the end in ANY edition.
    The file keeps its order from week to week (new items go to the end), so a position read once is, nearly, read."""
    return sorted({(i - 1) / n for _lane, _ed, i, n, done in _lane_parts(commons_folder) if done and n})


def edition_progress(commons_folder, edition):
    rows = [(i, n, done) for _lane, ed, i, n, done in _lane_parts(commons_folder) if ed == edition]
    total = max((n for _i, n, _d in rows), default=0)
    return {"edition": edition, "done": sum(1 for _i, _n, d in rows if d), "total": total}


def dump_coverage(commons_folder):
    """how much of Wikidata has EVER been read, and what the lanes are on now — the first thing the relevance test reports"""
    rows = _lane_parts(commons_folder)
    if not rows:
        return {"share": 0.0, "parts": 0, "read": 0, "editions": [], "current": None, "text": "No part of the Wikidata dump has been read yet."}
    eds = {}
    for _lane, ed, i, n, done in rows:
        e = eds.setdefault(ed, {"edition": ed, "parts": n, "done": 0, "started": 0})
        e["started"] += 1
        e["done"] += 1 if done else 0
    cur = max(eds)
    n = eds[cur]["parts"] or 1
    read = {int(f * n) for f in dump_positions_read(commons_folder)}
    read = {i for i in read if 0 <= i < n}
    share = len(read) / n
    hist = sorted(eds.values(), key=lambda e: e["edition"])
    never = [e for e in hist if e["done"] < e["parts"]]
    text = ("%d of %d parts of the Wikidata dump (%d%%) have ever been read to the end, counting every edition. " % (len(read), n, round(100 * share))
            + ("%d edition(s) were started and none was finished (%s) — each new weekly edition made the lanes start again at part 1, so the later parts were never reached. "
               % (len(hist), ", ".join("%s: %d of %d" % (e["edition"], e["done"], e["parts"]) for e in hist[-6:])) if hist and len(never) == len(hist) else "")
            + "Since 1.40 the lanes read the never-read parts first and finish an edition before a new one is fetched.")
    return {"share": round(share, 4), "parts": n, "read": len(read), "unread": sorted(set(range(n)) - read)[:200], "editions": hist, "current": cur, "text": text}


def _label_dbs(commons_folder):
    for key in ["hot-demand", "hot-seed", "hot-circle"] + ["hot-top-" + n for n in ICONS] + ["hot-most-read"] + ["hot-" + n for n in HOT] + ["hot-all-" + n for n in DOMAINS] + ["wikidata-dump-%d" % lane for lane in range(1, WikidataDump.LANES + 1)] + ["wikidata-lattice"]:
        p = shard_path(commons_folder, key) + ".labels"
        if os.path.exists(p):
            yield p


def wd_fame(commons_folder, qids):
    """{Q-number: Wikipedias with an article} for the items whose fame is recorded (1.40 on)"""
    want, out = sorted(set(qids)), {}
    for p in _label_dbs(commons_folder):
        if not want:
            break
        try:
            db = _ro(p)
            for i in range(0, len(want), 500):
                chunk = want[i:i + 500]
                out.update(db.execute("SELECT q, links FROM fame WHERE q IN (%s)" % ",".join("?" * len(chunk)), chunk).fetchall())
            db.close()
        except sqlite3.Error:
            continue
        want = [x for x in want if x not in out]
    return out


def wd_alias(commons_folder, name):
    """Q-numbers of the well-known items that go by this other name ("FDR", "The Babe")"""
    out = set()
    for p in _label_dbs(commons_folder):
        try:
            db = _ro(p)
            out.update(q for q, in db.execute("SELECT q FROM alias WHERE name = ?", ((name or "").casefold(),)))
            db.close()
        except sqlite3.Error:
            continue
    return sorted(out)


NAME_CHECK = 5000
NAME_SKIP = frozenset("the of and in on at for to de la le el du von van der den der a an".split())


def name_words(text):
    """the words of a name that tell it from others: lower case, no punctuation, no little words — {"los", "angeles", "dodgers"}"""
    return {w for w in re.findall(r"[^\W_]+", (text or "").casefold()) if len(w) >= 3 and w not in NAME_SKIP}


def wd_names(commons_folder, text, limit=400):
    """1.43 — Q-numbers of the well-known items whose names hold EVERY word asked ("Dodgers" -> Los Angeles Dodgers,
    Brooklyn Dodgers; "Lincoln Memorial" -> Lincoln Memorial). People say part of a name; the store keeps the whole."""
    want = sorted(name_words(text), key=len, reverse=True)
    every = {w for w in re.findall(r"[^\W_]+", (text or "").casefold()) if w not in NAME_SKIP}
    out = set()
    if not want:
        return []
    for p in _label_dbs(commons_folder):
        try:
            db = _ro(p)
            qs = None
            for w in want:
                got = {q for q, in db.execute("SELECT q FROM names WHERE word = ? LIMIT 20000", (w,))}
                qs = got if qs is None else qs & got
                if not qs:
                    break
            # 1.45: ONE name of the item must hold every word asked — the short ones too. "Ed Sullivan" asked the index for
            # "sullivan" alone ("ed" is too short to index) and was answered with Boris Vian, whose pen name is Vernon Sullivan.
            if qs and len(every) > 0:
                keep = set()
                cand = sorted(qs)[:NAME_CHECK]
                for i in range(0, len(cand), 500):
                    chunk = cand[i:i + 500]
                    marks = ",".join("?" * len(chunk))
                    rows = list(db.execute("SELECT q, label FROM labels WHERE q IN (%s)" % marks, chunk))
                    rows += list(db.execute("SELECT q, name FROM alias WHERE q IN (%s)" % marks, chunk))
                    for q, nm in rows:
                        if q not in keep and every <= set(re.findall(r"[^\W_]+", (nm or "").casefold())):
                            keep.add(q)
                qs = keep
            db.close()
            out |= qs or set()
        except sqlite3.Error:
            continue
        if len(out) >= limit:
            break
    return sorted(out)[:limit]


def index_names(commons_folder):
    """the names of the well-known items already read (their fame and labels are on file) put into the word index, once per
    label file — so records harvested before 1.43 are found by part of their name too. Returns how many names were added."""
    added = 0
    for p in _label_dbs(commons_folder):
        try:
            db = sqlite3.connect(p, timeout=30)
            try:
                if db.execute("PRAGMA user_version").fetchone()[0] >= 1:
                    continue
                db.execute("CREATE TABLE IF NOT EXISTS names (word TEXT NOT NULL, q INTEGER NOT NULL, PRIMARY KEY (word, q)) WITHOUT ROWID")
                rows = []
                for q, label in db.execute("SELECT f.q, l.label FROM fame f JOIN labels l ON l.q = f.q WHERE f.links >= ?", (FAME_ALIASES,)):
                    rows += [(w, q) for w in name_words(label)]
                for name, q in db.execute("SELECT name, q FROM alias"):
                    rows += [(w, q) for w in name_words(name)]
                db.executemany("INSERT OR IGNORE INTO names(word, q) VALUES(?, ?)", rows)
                db.execute("PRAGMA user_version = 1")
                db.commit()
                added += len(rows)
            finally:
                db.close()
        except sqlite3.Error:
            continue                                   # busy or older than 1.40 (no fame yet): tried again at the next start
    return added


ENT_SUBJECT = re.compile(r"^(.*) \(Q(\d+)\)$")


def name_forms(text):
    """the ways a name may have been typed: as given, first letter capital, Every Word Capital, ALL CAPITALS (short ones)"""
    t = " ".join((text or "").split())
    forms = [t, t[:1].upper() + t[1:], " ".join(w[:1].upper() + w[1:] for w in t.split(" "))]
    if len(t) <= 6:
        forms.append(t.upper())
    # 1.44: the Ask box drops a leading "the" ("Who are the Beatles?" asks for "Beatles") and the record is "The Beatles":
    # every form is tried with and without its article
    low = t.casefold()
    if low.startswith("the "):
        forms += name_forms(t[4:])
    elif t:
        forms += ["The " + f for f in list(forms)]
    return list(dict.fromkeys(f for f in forms if f))


def find_entities(commons_folder, text, top=5, per=400):
    """1.40 — WHO or WHAT is meant: every thing named exactly `text` (or known by that other name) in every store, the
    best known first, with ALL the facts of the best ones. Before, the Ask box took the first sixty facts whose subject
    began with the words — any "Babe Ruth" (a museum's baseball card), sixty of its facts at random.
    Well known = Wikipedias with an article (fame, recorded from 1.40), then how many facts the store holds about it (a
    famous person has hundreds, a namesake a handful). Returns {"entities": [...], "facts": [...], "asked", "stores"}."""
    forms = name_forms(text)
    held = stores(commons_folder)
    found = {}                                         # subject -> {"n", "stores"}
    if not forms:
        return {"entities": [], "facts": [], "asked": 0, "stores": len(held)}
    alias_q = set()
    for f in dict.fromkeys(x.casefold() for x in forms):
        alias_q.update(wd_alias(commons_folder, f))
    for key, ds in held:
        try:
            db = _ro(shard_path(commons_folder, key))
        except sqlite3.Error:
            continue
        try:
            for f in forms:
                for s_, n_ in db.execute("SELECT s, count(*) FROM facts WHERE (s >= ? AND s < ?) OR s = ? GROUP BY s LIMIT 300",
                                         (f + " (Q", f + " (Q\uffff", f)):
                    e = found.setdefault(s_, {"n": 0, "stores": []})
                    e["n"] += n_
                    e["stores"].append(key)
        except sqlite3.Error:
            pass
        finally:
            db.close()
    if alias_q:                                        # known by another name: the item's own label names its subject
        labs = wd_labels(commons_folder, list(alias_q))
        for qn, lab in labs.items():
            s_ = "%s (Q%d)" % (lab, qn)
            if s_ in found:
                continue
            for key, ds in held:
                try:
                    db = _ro(shard_path(commons_folder, key))
                    n_ = db.execute("SELECT count(*) FROM facts WHERE s = ?", (s_,)).fetchone()[0]
                    db.close()
                except sqlite3.Error:
                    continue
                if n_:
                    e = found.setdefault(s_, {"n": 0, "stores": [], "alias": True})
                    e["n"] += n_
                    e["stores"].append(key)
    # 1.43: part of a name. "Dodgers" is not the name of anything well known — it is a word of "Los Angeles Dodgers". The
    # well-known items whose names hold every word asked are candidates too, the best known of them only.
    have_q = {int(m.group(2)) for s_ in found for m in [ENT_SUBJECT.match(s_)] if m}
    part_q = [q_ for q_ in wd_names(commons_folder, forms[0]) if q_ not in have_q]
    if part_q:
        pv, pf = wd_views(commons_folder, part_q), wd_fame(commons_folder, part_q)
        part_q = sorted(part_q, key=lambda q_: (-(pv.get(q_) or 0), -(pf.get(q_) or 0), q_))[:PART_NAME_TOP]
        for qn, lab in wd_labels(commons_folder, part_q).items():
            s_ = "%s (Q%d)" % (lab, qn)
            if s_ in found:
                continue
            for key, ds in held:
                try:
                    db = _ro(shard_path(commons_folder, key))
                    n_ = db.execute("SELECT count(*) FROM facts WHERE s = ?", (s_,)).fetchone()[0]
                    db.close()
                except sqlite3.Error:
                    continue
                if n_:
                    e = found.setdefault(s_, {"n": 0, "stores": [], "part": True})
                    e["n"] += n_
                    e["stores"].append(key)
    qn_of = {s_: int(m.group(2)) for s_ in found for m in [ENT_SUBJECT.match(s_)] if m}
    fame = wd_fame(commons_folder, list(qn_of.values())) if qn_of else {}
    views = wd_views(commons_folder, list(qn_of.values())) if qn_of else {}
    ents = [{"subject": s_, "qid": ("Q%d" % qn_of[s_]) if s_ in qn_of else None, "facts": e["n"], "fame": fame.get(qn_of.get(s_)),
             "views": views.get(qn_of.get(s_)), "stores": e["stores"], "by_other_name": bool(e.get("alias")),
             "by_part_of_name": bool(e.get("part")), "exact": not e.get("alias") and not e.get("part")} for s_, e in found.items()]
    # best known first: what people read (page views), then how widely it is written about (Wikipedias), then how much is held
    ents.sort(key=lambda e: (-(e["views"] or 0), -(e["fame"] or 0), -e["facts"], e["subject"]))
    cat = catalog()
    facts = []
    for e in ents[:top]:
        got = 0
        for key in dict.fromkeys(e["stores"]):
            ds = cat[key]
            try:
                db = _ro(shard_path(commons_folder, key))
            except sqlite3.Error:
                continue
            try:
                for s_, pr, o, part, row in db.execute(
                        "SELECT f.s, pr.name, f.o, pa.name, f.row FROM facts f JOIN predicates pr ON pr.id = f.p JOIN parts pa ON pa.id = f.part "
                        "WHERE f.s = ? LIMIT ?", (e["subject"], per - got)):
                    facts.append({"subject": s_, "predicate": pr, "object": o, "dataset": ds.title, "source": ds.source or "computed", "licence": ds.licence,
                                  "provenance": "%s, row %d" % (part, row + 1), "link": ds.link(s_), "status": "computed" if not ds.source else "sourced"})
                    got += 1
            except sqlite3.Error:
                pass
            finally:
                db.close()
            if got >= per:
                break
    return {"entities": ents[:25], "facts": label_wikidata(commons_folder, facts), "asked": len(held), "stores": len(held)}


def wd_labels(commons_folder, qids):
    """English labels for Q-numbers, from every lane's label file"""
    want, out = sorted(set(qids)), {}
    for p in _label_dbs(commons_folder):
        if not want:
            break
        db = _ro(p)
        for i in range(0, len(want), 500):
            chunk = want[i:i + 500]
            out.update(db.execute("SELECT q, label FROM labels WHERE q IN (%s)" % ",".join("?" * len(chunk)), chunk).fetchall())
        db.close()
        want = [x for x in want if x not in out]
    return out


# ------------------------------------------------------------------------------------------------ the hot lattices (1.40)
# What people ask about first. The dump lanes read all of Wikidata in the order of a 150 GB file: after three weeks the
# store held 1.5 billion facts and nothing about Ed Sullivan. A hot lattice does the opposite: for one kind of thing
# (television presenters, presidents, monuments, universities, wars...) it asks Wikidata for the items of that kind in
# order of how much the rest of Wikidata links to them — the best known first — and reads each one's whole record. A few
# thousand requests bring the few hundred thousand subjects nearly every question is about; the lanes fill in the rest.
# Each lattice is its own dataset with its own agent, so they run side by side; they are re-read every month.
HOT = {
    "people-politics": ("People — politics and government", 3000, (
        "P106=Q82955", "P39=Q11696", "P39=Q14211", "P106=Q372436", "P106=Q193391", "P106=Q116", "P106=Q16533", "P106=Q40348",
        "P106=Q189290", "P106=Q15253558", "P39=Q30461", "P39=Q13218630", "P39=Q4416090", "P106=Q2304859")),
    "people-entertainment": ("People — film, television, radio and stage", 3000, (
        "P106=Q947873", "P106=Q33999", "P106=Q10800557", "P106=Q10798782", "P106=Q245068", "P106=Q2526255", "P106=Q2722764",
        "P106=Q3282637", "P106=Q28389", "P106=Q4610556", "P106=Q2405480", "P106=Q2259451", "P106=Q5716684", "P106=Q138858")),
    "people-music": ("People — music", 3000, (
        "P106=Q177220", "P106=Q639669", "P106=Q36834", "P106=Q753110", "P106=Q2252262", "P106=Q158852", "P106=Q855091",
        "P106=Q486748", "P106=Q488205", "P106=Q183945", "P106=Q2865819", "P106=Q386854", "P31=Q215380", "P31=Q5741069")),
    "people-arts-letters": ("People — art, literature and ideas", 3000, (
        "P106=Q1028181", "P106=Q1281618", "P106=Q42973", "P106=Q33231", "P106=Q36180", "P106=Q49757", "P106=Q6625963",
        "P106=Q1930187", "P106=Q4964182", "P106=Q214917", "P106=Q644687", "P106=Q5322166", "P106=Q4853732", "P106=Q333634")),
    "people-science-education": ("People — science, invention, medicine and education", 3000, (
        "P106=Q169470", "P106=Q593644", "P106=Q170790", "P106=Q864503", "P106=Q205375", "P106=Q39631", "P106=Q11063",
        "P106=Q188094", "P106=Q201788", "P106=Q37226", "P106=Q1622272", "P106=Q81096", "P106=Q11631", "P106=Q11900058",
        "P106=Q901", "P106=Q212980", "P106=Q2374149", "P106=Q82594")),
    "people-religion": ("People — religion", 3000, (
        "P106=Q42603", "P106=Q1234713", "P106=Q250867", "P106=Q152002", "P106=Q133485", "P106=Q125482", "P106=Q219477",
        "P106=Q432386", "P106=Q733786", "P39=Q19546", "P106=Q15995642", "P106=Q191808", "P106=Q831474", "P31=Q178885")),
    "people-sports": ("People — sport", 3000, (
        "P106=Q10871364", "P106=Q3665646", "P106=Q19204627", "P106=Q937857", "P106=Q11338576", "P106=Q10833314", "P106=Q11303721",
        "P106=Q11513337", "P106=Q11774891", "P106=Q10349745", "P106=Q10843402", "P106=Q2309784", "P106=Q13381572", "P106=Q4009406",
        "P106=Q13141064", "P106=Q10873124")),
    "people-business-society": ("People — business, exploration and public life", 3000, (
        "P106=Q43845", "P106=Q131524", "P106=Q2462658", "P106=Q806798", "P106=Q12362622", "P106=Q8246794",
        "P106=Q3242115", "P106=Q10669499", "P106=Q2095549", "P106=Q15980158", "P106=Q484876")),
    "places": ("Places — countries, states, cities and the natural world", 3000, (
        "P31=Q3624078", "P31=Q6256", "P31=Q35657", "P31=Q515", "P31=Q1549591", "P31=Q5119", "P31=Q1093829", "P31=Q8502",
        "P31=Q4022", "P31=Q23397", "P31=Q23442", "P31=Q46169", "P31=Q5107", "P31=Q9430", "P31=Q8514", "P31=Q34763",
        "P31=Q47168", "P31=Q1637706", "P31=Q174844", "P31=Q133056")),
    "monuments": ("Monuments, landmarks and famous buildings", 3000, (
        "P31=Q4989906", "P31=Q570116", "P1435=Q9259", "P31=Q33506", "P31=Q16970", "P31=Q23413", "P31=Q12280", "P31=Q11303",
        "P31=Q5003624", "P31=Q179700", "P31=Q2977", "P31=Q44539", "P31=Q16560", "P31=Q483110", "P31=Q839954", "P31=Q12518",
        "P31=Q1128397", "P31=Q24354", "P31=Q22698", "P1435=Q19558910")),
    "institutions": ("Institutions — universities, companies, governments, churches, teams, media", 3000, (
        "P31=Q3918", "P31=Q4830453", "P31=Q891723", "P31=Q327333", "P31=Q7278", "P31=Q484652", "P31=Q163740", "P31=Q11032",
        "P31=Q1254874", "P31=Q13027888", "P31=Q13393265", "P31=Q17156793", "P31=Q476028", "P31=Q9174", "P31=Q879146", "P31=Q3914",
        "P31=Q16917", "P31=Q7075", "P31=Q2085381", "P31=Q41298", "P31=Q14350", "P31=Q1616075", "P31=Q11691", "P31=Q8473")),
    "events": ("Events — wars, elections, disasters, discoveries and firsts", 3000, (
        "P31=Q198", "P31=Q178561", "P31=Q10931", "P31=Q47566", "P31=Q40231", "P31=Q3839081", "P31=Q131569", "P31=Q159821",
        "P31=Q7944", "P31=Q3882219", "P31=Q13418847", "P31=Q12184", "P31=Q8065", "P31=Q124757", "P31=Q175331", "P31=Q5389",
        "P31=Q82414", "P31=Q1318941", "P31=Q752783", "P31=Q1190554")),
    "works": ("Works — films, television, music, books and art", 3000, (
        "P31=Q11424", "P31=Q5398426", "P31=Q15416", "P31=Q482994", "P31=Q7725634", "P31=Q571", "P31=Q8261", "P31=Q3305213",
        "P31=Q7889", "P31=Q2743", "P31=Q25379", "P31=Q134556", "P31=Q1004", "P31=Q24856", "P31=Q41298", "P31=Q860861",
        "P31=Q105543609", "P31=Q1344", "P31=Q5185279")),
    "knowledge": ("Things people look up — science, nature, culture and daily life", 3000, (
        "P31=Q11344", "P31=Q12136", "P31=Q634", "P31=Q618779", "P31=Q349", "P31=Q34379", "P31=Q2095", "P31=Q1445650",
        "P31=Q34770", "P31=Q8142", "P31=Q9143", "P31=Q8928", "P31=Q11173", "P31=Q16521",
        "P31=Q43229", "P31=Q11862829", "P31=Q483394", "P31=Q41710", "P31=Q1420", "P31=Q11446")),
}


# ---- 1.44: a second way to read records. Wikidata's records service (api.php) refuses a computer it finds too busy
# ("429 Too Many Requests") — outright, for as long as it likes; its query service is a separate system with its own
# allowance. The hot list read records through the first only: where it was refused, the list was made and nobody was
# read. Now a refusal switches every agent to the query service for a quarter of an hour, then the records service is
# tried again. The query service's answer is put into the records service's own shape, so the facts written are the same.
API_REFUSED_NAME = "_api_refused.json"
API_REFUSED_S = 15 * 60
WDQS_PAUSE_S = 10
WD_E, WD_D = "http://www.wikidata.org/entity/", "http://www.wikidata.org/prop/direct/"


def WDQS_FETCH(sparql):
    """one query to the query service, typed answers: the list of bindings (the tests replace this)"""
    req = urllib.request.Request("https://query.wikidata.org/sparql", data=urllib.parse.urlencode({"query": sparql}).encode(),
                                 headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())["results"]["bindings"]
    except http.client.HTTPException as e:
        raise ValueError("connection dropped: %s" % type(e).__name__)


def wdqs_ask(sparql, folder=None):
    """…taking turns with every other agent (two at a time), and waiting when the service says it is busy"""
    slots = Slots(folder) if folder else None
    lock, t0 = None, time.time()
    while slots is not None and lock is None and time.time() - t0 < 600:
        lock = slots._lock("wikidata-read", 0) or slots._lock("wikidata-read", 1)   # (its own turns: never behind the slow listing queries)
        if lock is None:
            time.sleep(0.3)
    try:
        for attempt in range(4):
            try:
                return WDQS_FETCH(sparql)
            except urllib.error.HTTPError as e:
                if e.code not in REFUSED + (500, 502, 503, 504) or attempt == 3:
                    raise
                time.sleep(max(WDQS_PAUSE_S * (attempt + 1), _retry_after(e)))
            except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError):
                # (ValueError: the service ran out of its minute and cut the answer off mid-way — not an answer at all)
                if attempt == 1:
                    raise
                time.sleep(WDQS_PAUSE_S)
    finally:
        if lock is not None:
            slots.release(lock)


def api_refused(folder, now=None):
    """the records service refused this computer recently: every agent reads through the query service until then"""
    d = _read_json(os.path.join(folder, FOLDER, API_REFUSED_NAME), {}) if folder else {}
    return bool(isinstance(d, dict) and (d.get("until") or 0) > (now or time.time()))


def api_refused_set(folder, why=""):
    if folder:
        _ka_save(os.path.join(folder, FOLDER, API_REFUSED_NAME), {"until": time.time() + API_REFUSED_S, "at": time.time(), "why": str(why)[:200]})


WDQS_BATCH = 25
ENTITY_AT_ONCE = 2                 # records asked for at the same time from the per-record address
ENTITY_PAUSE_S = 3.0               # after it says "too many requests"


def ENTITY_FETCH(qid):
    """one whole record from Wikidata's per-record address (Special:EntityData — not the records service: it answered
    here while that one refused). The record as the records service gives it, or None. (The tests replace this.)"""
    req = urllib.request.Request("https://www.wikidata.org/wiki/Special:EntityData/%s.json" % qid, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            ents = json.loads(r.read()).get("entities") or {}
    except http.client.HTTPException as e:
        raise ValueError("connection dropped: %s" % type(e).__name__)
    return next(iter(ents.values()), None)


def entitydata_entities(qids):
    """1.45 — {Q-id: record}, one record a request, two at a time, slowing down when told to. Measured: 52 records in 4
    seconds, against 50 a minute through the query service. Gives up (returns what it has) when the address refuses
    outright, so the caller reads the rest through the query service."""
    ids = [q for q in dict.fromkeys(qids) if re.fullmatch(r"Q\d+", q or "")]
    out, state = {}, {"fails": 0}

    def one(q):
        for attempt in range(4):
            if state["fails"] >= 12:
                return
            try:
                e = ENTITY_FETCH(q)
                if e and "missing" not in e:
                    out[q] = e
                state["fails"] = 0
                return
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return
                state["fails"] += 1
                time.sleep(max(ENTITY_PAUSE_S * (attempt + 1), min(30, _retry_after(e))) if ENTITY_PAUSE_S else 0)
            except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError):
                state["fails"] += 1
                time.sleep(ENTITY_PAUSE_S)
    import concurrent.futures as _cf
    with _cf.ThreadPoolExecutor(ENTITY_AT_ONCE) as ex:
        list(ex.map(one, ids))
    return out


def wdqs_entities(qids, folder=None):
    """…in batches the query service answers within its minute. A batch it cannot answer (the most-written-about subjects
    have thousands of statements) is halved until it can; a single subject it still cannot answer is left for the next
    run — never the whole part lost for one of them."""
    ids = [q for q in dict.fromkeys(qids) if re.fullmatch(r"Q\d+", q or "")]
    out = {}

    def take(chunk):
        try:
            out.update(_wdqs_entities(chunk, folder))
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError):
            if len(chunk) > 1:
                take(chunk[:len(chunk) // 2])
                take(chunk[len(chunk) // 2:])
    for i in range(0, len(ids), WDQS_BATCH):
        take(ids[i:i + WDQS_BATCH])
    return out


def _wdqs_entities(qids, folder=None):
    """{Q-id: record} for these items, read from the query service and shaped as the records service gives them (labels,
    description, other names, the number of Wikipedias, and every best-rank statement with its value: an item, a date at
    its own precision, a quantity with its unit, a place on Earth, a text). Three small queries per batch."""
    ids = [q for q in dict.fromkeys(qids) if re.fullmatch(r"Q\d+", q or "")]
    if not ids:
        return {}
    vals = " ".join("wd:" + q for q in ids)
    q_of = lambda b, k="s": b[k]["value"].rsplit("/", 1)[-1]
    out = {}
    for b in wdqs_ask("SELECT ?s ?l ?d ?n WHERE { VALUES ?s { %s } ?s wikibase:sitelinks ?n . OPTIONAL { ?s rdfs:label ?l FILTER(LANG(?l) = \"en\") } "
                      "OPTIONAL { ?s schema:description ?d FILTER(LANG(?d) = \"en\") } }" % vals, folder):
        e = out.setdefault(q_of(b), {"type": "item", "id": q_of(b), "labels": {}, "descriptions": {}, "aliases": {"en": []}, "claims": {}, "sitelinks": {}})
        if "l" in b:
            e["labels"]["en"] = {"value": b["l"]["value"]}
        if "d" in b:
            e["descriptions"]["en"] = {"value": b["d"]["value"]}
        try:
            e["sitelinks"] = {"w%d" % i: {} for i in range(int(float(b["n"]["value"])))}
        except (KeyError, ValueError):
            pass
    if not out:
        return {}
    for b in wdqs_ask("SELECT ?s ?a WHERE { VALUES ?s { %s } ?s skos:altLabel ?a FILTER(LANG(?a) = \"en\") }" % vals, folder):
        if q_of(b) in out:
            out[q_of(b)]["aliases"]["en"].append({"value": b["a"]["value"]})
    add = lambda q, pid, dv: out[q]["claims"].setdefault(pid, []).append({"rank": "normal", "mainsnak": {"datavalue": dv}})
    timed, measured = set(), set()
    # dates at their own precision, quantities with their unit (the simple values lose both)
    for b in wdqs_ask("SELECT ?s ?pd ?t ?prec ?amt ?unit WHERE { VALUES ?s { %s } ?s ?p ?st . ?st a wikibase:BestRank ; ?psv ?v . "
                      "?prop wikibase:claim ?p ; wikibase:statementValue ?psv ; wikibase:directClaim ?pd . "
                      "{ ?v wikibase:timeValue ?t ; wikibase:timePrecision ?prec } UNION { ?v wikibase:quantityAmount ?amt ; wikibase:quantityUnit ?unit } }" % vals, folder):
        q, pid = q_of(b), b["pd"]["value"].rsplit("/", 1)[-1]
        if q not in out:
            continue
        if "t" in b:
            t = b["t"]["value"]
            add(q, pid, {"type": "time", "value": {"time": t if t[:1] in "+-" else "+" + t, "precision": int(float(b["prec"]["value"]))}})
            timed.add((q, pid))
        elif "amt" in b:
            a, u = b["amt"]["value"], b["unit"]["value"]
            add(q, pid, {"type": "quantity", "value": {"amount": a if a[:1] in "+-" else "+" + a, "unit": "1" if u.endswith("/Q199") else u}})
            measured.add((q, pid))
    for b in wdqs_ask("SELECT ?s ?p ?o WHERE { VALUES ?s { %s } ?s ?p ?o . FILTER(STRSTARTS(STR(?p), \"%s\")) }" % (vals, WD_D), folder):
        q, pid, o = q_of(b), b["p"]["value"].rsplit("/", 1)[-1], b["o"]
        if q not in out or (q, pid) in timed or (q, pid) in measured:
            continue
        v, dt = o.get("value", ""), o.get("datatype", "")
        if o.get("type") == "uri":
            if v.startswith(WD_E) and re.fullmatch(r"Q\d+", v[len(WD_E):]):
                add(q, pid, {"type": "wikibase-entityid", "value": {"id": v[len(WD_E):]}})
        elif dt.endswith("#dateTime") or dt.endswith("#decimal"):
            continue                                    # (a date or quantity the precise query did not return: left out, not guessed)
        elif dt.endswith("wktLiteral"):
            m = re.fullmatch(r"Point\(([-0-9.eE]+) ([-0-9.eE]+)\)", v)
            if m:                                        # (a place on another globe carries its globe first: skipped, as the lanes do)
                add(q, pid, {"type": "globecoordinate", "value": {"latitude": float(m.group(2)), "longitude": float(m.group(1)), "globe": WD_E + "Q2"}})
        elif o.get("xml:lang"):
            add(q, pid, {"type": "monolingualtext", "value": {"text": v, "language": o["xml:lang"]}})
        elif not dt or dt.endswith("#string"):
            add(q, pid, {"type": "string", "value": v})
    return out


def wdqs_labels(qnums, folder=None):
    out = {}
    ids = sorted(set(qnums))
    for i in range(0, len(ids), 400):
        for b in wdqs_ask("SELECT ?s ?l WHERE { VALUES ?s { %s } ?s rdfs:label ?l FILTER(LANG(?l) = \"en\") }" % " ".join("wd:Q%d" % q for q in ids[i:i + 400]), folder):
            out[int(b["s"]["value"].rsplit("/Q", 1)[-1])] = b["l"]["value"]
    return out


def wdqs_find(name, folder=None, limit=7):
    """the items called `name` (their label or another name of theirs, with and without "The"), the best known first"""
    forms = [f for f in name_forms(name) if '"' not in f and "\\" not in f][:8]
    if not forms:
        return []
    rows = wdqs_ask("SELECT DISTINCT ?s ?n WHERE { VALUES ?l { %s } { ?s rdfs:label ?l } UNION { ?s skos:altLabel ?l } ?s wikibase:sitelinks ?n } "
                    "ORDER BY DESC(?n) LIMIT %d" % (" ".join('"%s"@en' % f for f in forms), limit), folder)
    return [b["s"]["value"].rsplit("/", 1)[-1] for b in rows if b["s"]["value"].rsplit("/", 1)[-1].startswith("Q")]


def wdqs_titles(titles, folder=None):
    """{English Wikipedia article title: Q-id}"""
    ok = [t for t in titles if '"' not in t and "\\" not in t]
    out = {}
    for i in range(0, len(ok), 50):
        for b in wdqs_ask("SELECT ?t ?s WHERE { VALUES ?t { %s } ?a schema:name ?t ; schema:about ?s ; schema:isPartOf <https://en.wikipedia.org/> }"
                          % " ".join('"%s"@en' % t for t in ok[i:i + 50]), folder):
            out[b["t"]["value"]] = b["s"]["value"].rsplit("/", 1)[-1]
    return out


def HOT_FETCH(params):
    """one request to Wikidata's API (the tests replace this)"""
    url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(dict(params, format="json", maxlag=5))
    with urllib.request.urlopen(_req(url), timeout=90) as r:
        return json.loads(r.read())


class WikidataHot(Dataset):
    """ONE hot lattice: the best-known items of each kind it names, the most linked-to first, each item's whole record.
    A part is 50 items of one kind (rank 1-50, 51-100, ...): the parts are ordered by rank across the kinds, so the top
    50 of every kind are read before the next 50 of any. Facts are written exactly as the dump lanes write them (the
    lanes' own entity rule), with the item's description, other names and fame — where the two overlap one copy is kept."""
    app, source, licence = "facts", "wikidata", "CC0 1.0 (Wikidata)"
    PAGE = 50
    GAP_S = 0.6                                       # between two requests of one lattice (Wikidata asks for restraint)

    def __init__(self, name):
        self.name = name
        self.title_short, self.depth, self.finds = HOT[name]
        self.key = "hot-" + name
        self.title = "Hot lattice — " + self.title_short
        self.why = "what people ask about first: the best-known items of each kind, most linked-to first, read directly from Wikidata"
        self.approx = "about %s items in %d kinds, re-read monthly" % (format(self.depth * len(self.finds), ","), len(self.finds))

    def prepare(self, run):
        self.lane = WikidataDump(1)
        self.lane.props = self.lane.catalogue(run.folder, fetch=not os.environ.get("QB_OFFLINE"))
        self.folder = run.folder
        db = sqlite3.connect(shard_path(run.folder, self.key) + ".labels")
        db.execute("CREATE TABLE IF NOT EXISTS labels (q INTEGER PRIMARY KEY, label TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS keystones (k TEXT PRIMARY KEY, facts INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS fame (q INTEGER PRIMARY KEY, links INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS alias (name TEXT NOT NULL, q INTEGER NOT NULL, PRIMARY KEY (name, q)) WITHOUT ROWID")
        db.execute("CREATE TABLE IF NOT EXISTS views (q INTEGER PRIMARY KEY, views INTEGER NOT NULL, months INTEGER NOT NULL DEFAULT 1)")
        db.execute("CREATE TABLE IF NOT EXISTS names (word TEXT NOT NULL, q INTEGER NOT NULL, PRIMARY KEY (word, q)) WITHOUT ROWID")
        db.commit()
        return {"_labeldb": db, "_labelbuf": [], "_famebuf": [], "_aliasbuf": [], "_viewbuf": [], "_namebuf": [], "_known": set(), "_months": {}}

    def parts(self):
        ed = time.strftime("%Y-%m")
        return [("%s %s rank %05d-%05d" % (ed, find, off + 1, off + self.PAGE), "hot#%s#%d" % (find, off))
                for off in range(0, self.depth, self.PAGE) for find in self.finds]

    def _get(self, params, state, tries=5):
        last = state.get("_last", 0)
        if last and time.time() - last < self.GAP_S:
            time.sleep(self.GAP_S - (time.time() - last))
        for attempt in range(tries):
            try:
                slot = self._turn()
                try:
                    r = HOT_FETCH(params)
                finally:
                    if slot is not None:
                        self._slots.release(slot)
                if isinstance(r, dict) and (r.get("error") or {}).get("code") == "maxlag":
                    time.sleep(5 + 5 * attempt)       # Wikidata's own servers are behind: wait as it asks
                    continue
                state["_last"] = time.time()
                return r
            except urllib.error.HTTPError as e:
                if e.code not in REFUSED + (502, 504):
                    raise
                if attempt + 1 < tries:
                    time.sleep(min(20, max(3 * (attempt + 1), _retry_after(e))))
        raise Busy("Wikidata's records service asked us to slow down (HTTP 429)")

    API_AT_ONCE = 3                                   # every lattice together: at most this many requests to Wikidata at a time

    def _turn(self):
        """fifteen lattices each asking at their own pace would be twenty requests a second from one computer: they take
        turns, three at a time (a lock file each, shared by every agent)"""
        if getattr(self, "_slots", None) is None:
            self._slots = Slots(self.folder)
        t0 = time.time()
        while time.time() - t0 < 120:
            for i in range(self.API_AT_ONCE):
                f = self._slots._lock("wikidata-api", i)
                if f:
                    return f
            time.sleep(0.2)
        return None

    def _api(self, params, state):
        """the records service, ONE try: a refusal is remembered for a quarter of an hour (every agent then reads through the
        query service) and raised as Refused — nobody waits minutes on a service that has said no"""
        if api_refused(getattr(self, "folder", None)):
            raise Refused("refused recently")
        try:
            return self._get(params, state, tries=2)
        except Busy as e:
            api_refused_set(getattr(self, "folder", None), str(e))
            raise Refused(str(e))

    def _entities(self, ids, state):
        """the whole records of these items, from the records service or — when it refuses — the query service"""
        ids = [q for q in ids if q]
        out = {}
        try:
            for i in range(0, len(ids), self.PAGE):
                out.update(self._api({"action": "wbgetentities", "ids": "|".join(ids[i:i + self.PAGE]),
                                      "props": "labels|descriptions|aliases|claims|sitelinks", "languages": "en|mul"}, state).get("entities") or {})
            state["_via"] = "records service"
            return out
        except Refused:
            pass
        out = entitydata_entities(ids)                  # the per-record address: whole records, fast
        left = [q for q in ids if q not in out]
        if left:                                         # …and what it would not give, through the query service
            out.update(wdqs_entities(left, getattr(self, "folder", None)))
        state["_via"] = "per-record address" if not left else "per-record address and query service"
        return out

    def rows(self, part, url, state):
        _, find, off = url.split("#")
        try:
            r = self._api({"action": "query", "list": "search", "srsearch": "haswbstatement:" + find, "srnamespace": 0, "srlimit": self.PAGE,
                           "sroffset": int(off), "srsort": "incoming_links_desc", "srprop": ""}, state)
        except Refused:                                    # this ranking exists only in the records service: wait for it
            raise Busy("Wikidata's records service is refusing this computer; this lattice waits (the icons are read through the query service meanwhile)")
        ids = [h["title"] for h in (r.get("query") or {}).get("search", []) if str(h.get("title", "")).startswith("Q")]
        if not ids:
            return iter(())
        ents = self._entities(ids, state)
        rows = [ents[q] for q in ids if q in ents and "missing" not in ents[q]]
        self._name_values(rows, state)
        METER.start(len(rows), "rows")
        return self._each(rows, state)

    def _each(self, rows, state):
        try:
            for r in rows:
                yield r
        finally:
            self.lane._flush(state)                        # fame, other names and labels of this batch are kept

    CIRCLE_RING = 0                                    # the records this dataset reads are the centre of the net (None: not part of it)

    def _circle_note(self, ents, state):
        """1.46 the network of nets: who and what each record read is tied to — family, partners, members, founders, those it
        followed and those who followed it, its places, its events, its works — is noted with the ring it stands on (an
        icon's circle is ring 1, their circle ring 2, ...). hot-circle reads them, the most tied-to of the nearest ring first."""
        ring0 = self.CIRCLE_RING
        if ring0 is None:
            return
        rings = state.get("_rings") or {}
        buf = state.setdefault("_circlebuf", [])
        for e in ents:
            q = str(e.get("id") or "")
            ring = rings.get(int(q[1:]), ring0) if q[1:].isdigit() else ring0
            if ring >= CIRCLE_RINGS:
                continue
            for pid in CIRCLE_TIES:
                for st in (e.get("claims") or {}).get(pid) or ():
                    v = ((st.get("mainsnak") or {}).get("datavalue") or {}).get("value")
                    if isinstance(v, dict) and str(v.get("id", "")).startswith("Q") and v["id"][1:].isdigit() and v["id"] != q:
                        buf.append((int(v["id"][1:]), ring + 1))

    def _name_values(self, ents, state):
        """the labels of the items these records point to (a birthplace, an occupation, a spouse), so their values read as
        names: those no label file holds yet are asked for, 50 at a time, and kept"""
        refs = set()
        for e in ents:
            for sts in (e.get("claims") or {}).values():
                for st in sts:
                    v = ((st.get("mainsnak") or {}).get("datavalue") or {}).get("value")
                    if isinstance(v, dict) and str(v.get("id", "")).startswith("Q"):
                        refs.add(int(v["id"][1:]))
        self._circle_note(ents, state)
        refs -= state["_known"]
        if refs:
            refs -= set(wd_labels(self.folder, list(refs)))
        want = sorted(refs)
        try:
            for i in range(0, len(want), 50):
                r = self._api({"action": "wbgetentities", "ids": "|".join("Q%d" % q for q in want[i:i + 50]), "props": "labels", "languages": "en|mul"}, state)
                for q, e in (r.get("entities") or {}).items():
                    L = e.get("labels") or {}
                    lab = (L.get("en") or L.get("mul") or {}).get("value")
                    if lab and q[1:].isdigit():
                        state["_labelbuf"].append((int(q[1:]), lab))
        except Refused:
            state["_labelbuf"].extend(wdqs_labels(want, getattr(self, "folder", None)).items())
        state["_known"] |= refs
        self.lane._flush(state)

    def facts(self, part, row, state):
        out = self.lane.entity_facts(row, state)
        if len(state.get("_labelbuf") or ()) >= 500:
            self.lane._flush(state)
        return out

    def link(self, subject):
        m = re.search(r"\((Q\d+)\)$", subject)
        return "https://www.wikidata.org/wiki/" + m.group(1) if m else None


DEMAND_NAME, LEARNED_NAME = "_demand.json", "_demand_learned.json"


def demand_note(commons_folder, subject, question="", why=""):
    """1.40 — learn from what was asked: a subject QueryBook could not answer (or answered with the wrong kind of thing)
    is queued for the demand agent, which fetches its record from Wikidata at once. Returns {"queued", "pending"}."""
    subject = " ".join(str(subject or "").split())[:120]
    if len(subject) < 2:
        return {"queued": False, "pending": 0}
    path = os.path.join(commons_folder, FOLDER, DEMAND_NAME)
    q = _read_json(path, [])
    q = q if isinstance(q, list) else []
    row = next((r for r in q if r.get("subject", "").casefold() == subject.casefold()), None)
    if row:
        row.update(n=int(row.get("n") or 1) + 1, last=time.time())
    else:
        q.append({"subject": subject, "question": str(question or "")[:200], "why": str(why or "")[:200], "at": time.time(), "last": time.time(), "n": 1})
    _ka_save(path, q[-3000:])
    return {"queued": True, "pending": sum(1 for r in q if not r.get("done"))}


def demand_list(commons_folder):
    q = _read_json(os.path.join(commons_folder, FOLDER, DEMAND_NAME), [])
    return q if isinstance(q, list) else []


def demand_learned(commons_folder):
    """{lattice: how many asked-for subjects turned out to be of its kinds} — the lattices people's questions land in most
    are harvested first (qbkeystone.order)"""
    d = _read_json(os.path.join(commons_folder, FOLDER, LEARNED_NAME), {})
    return d if isinstance(d, dict) else {}


class WikidataDemand(WikidataHot):
    """The demand agent: every subject that was asked and not found (the Ask box, the relevance test) is looked up by name
    in Wikidata and the best candidates' whole records are read — the person, and the things named after them. It learns
    as it goes: the kinds of the subjects it fetches decide which hot lattices are harvested first."""
    def __init__(self):
        self.name, self.key = "demand", "hot-demand"
        self.title_short, self.depth, self.finds = "what was asked and not found", 0, ()
        self.title = "Demand agent — what was asked and not found, fetched at once"
        self.why = "a question QueryBook could not answer is the best guide to what it lacks: its subject is fetched within minutes"
        self.approx = "as asked"

    def parts(self):
        ed = time.strftime("%Y-%m")
        return [("asked %s: %s" % (ed, r["subject"]), "demand#" + r["subject"]) for r in demand_list(self.folder) if r.get("subject")]

    def rows(self, part, url, state):
        subject = url.split("#", 1)[1]
        try:
            r = self._api({"action": "wbsearchentities", "search": subject, "language": "en", "uselang": "en", "type": "item", "limit": 7}, state)
            ids = [h["id"] for h in r.get("search") or [] if str(h.get("id", "")).startswith("Q")]
        except Refused:
            ids = wdqs_find(subject, self.folder)
        rows = []
        if ids:
            ents = self._entities(ids, state)
            rows = [ents[q] for q in ids if q in ents and "missing" not in ents[q]]
            self._name_values(rows, state)
            self._learn(rows)
            if rows:                                       # 1.43: asked for as "Dodgers", found as Los Angeles Dodgers: remembered
                top = int(rows[0]["id"][1:])
                state["_aliasbuf"].append((subject.casefold(), top))
                state["_namebuf"].extend((w, top) for w in name_words(subject))
        q = demand_list(self.folder)                       # marked: fetched (or nothing by that name in Wikidata)
        for row in q:
            if row.get("subject") == subject:
                row.update(done=time.time(), found=len(rows))
        _ka_save(os.path.join(self.folder, FOLDER, DEMAND_NAME), q)
        METER.start(len(rows), "rows")
        return self._each(rows, state)

    def _learn(self, ents):
        learned = demand_learned(self.folder)
        for e in ents[:1]:                                 # the best match: what kind of thing was asked for
            claims = e.get("claims") or {}
            mine = {"%s=%s" % (p, ((st.get("mainsnak") or {}).get("datavalue") or {}).get("value", {}).get("id"))
                    for p in ("P31", "P106", "P39", "P1435") for st in claims.get(p, ())
                    if isinstance(((st.get("mainsnak") or {}).get("datavalue") or {}).get("value"), dict)}
            for name, (_t, _d, finds) in HOT.items():
                if mine & set(finds):
                    learned[name] = int(learned.get(name) or 0) + 1
        _ka_save(os.path.join(self.folder, FOLDER, LEARNED_NAME), learned)


# ------------------------------------------------------------------------------------------------ what people read (1.41)
VIEWS_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/%04d/%02d/all-days"
VIEWS_FROM = (2015, 7)             # Wikimedia's page-view counts begin here
NOT_ARTICLES = ("Main_Page", "Special:", "Wikipedia:", "Portal:", "File:", "Help:", "Category:", "Template:", "User:", "Talk:", "Draft:", "-", "404.php")


def VIEWS_FETCH(year, month):
    """the 1,000 most-read articles of the English Wikipedia in one month: [(title, views)] (the tests replace this)"""
    try:
        with urllib.request.urlopen(_req(VIEWS_URL % (year, month)), timeout=90) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []                                  # a month Wikimedia has not published (yet)
        raise
    arts = ((d.get("items") or [{}])[0].get("articles")) or []
    return [(a["article"], int(a.get("views") or 0)) for a in arts if not str(a.get("article", "")).startswith(NOT_ARTICLES)]


def views_months(now=None, recent=24):
    """the months sampled: every one of the last two years (what is read now), then one a quarter back to 2015 — so a
    subject that is read year after year counts for more than one that was in the news for a week"""
    t = time.gmtime(now or time.time())
    y, m = (t.tm_year, t.tm_mon - 1) if t.tm_mon > 1 else (t.tm_year - 1, 12)     # the last complete month
    out = []
    while (y, m) >= VIEWS_FROM:
        if len(out) < recent or m in (1, 4, 7, 10):
            out.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out


class WikidataMostRead(WikidataHot):
    """What people actually read: the 1,000 most-read articles of the English Wikipedia, month by month over ten years
    (Wikimedia's own page-view counts, public domain). Each article's Wikidata record is read whole, and its views are
    added up over the months — the direct measure of what people want to know, used to choose which "Babe Ruth" is meant
    and to rank every answer. Rank by rank across the months: the top 50 of every month before the next 50 of any."""
    def __init__(self):
        self.name, self.key = "most-read", "hot-most-read"
        self.title_short, self.depth, self.finds = "the most-read Wikipedia articles, month by month", 1000, ()
        self.title = "Hot lattice — what people read (Wikipedia page views)"
        self.why = "the subjects people look up most, by Wikimedia's own count of page views — the best guide to the questions they will ask"
        self.approx = "about 1,000 articles a month over ten years, re-sampled monthly"

    def parts(self):
        return [("most read %04d-%02d rank %04d-%04d" % (y, m, off + 1, off + self.PAGE), "views#%d#%d#%d" % (y, m, off))
                for off in range(0, self.depth, self.PAGE) for y, m in views_months()]

    def rows(self, part, url, state):
        _, y, m, off = url.split("#")
        key = (int(y), int(m))
        if key not in state["_months"]:
            if len(state["_months"]) > 6:
                state["_months"].clear()
            state["_months"][key] = VIEWS_FETCH(*key)
        chunk = state["_months"][key][int(off):int(off) + self.PAGE]
        if not chunk:
            return iter(())
        by_title = {t.replace("_", " "): v for t, v in chunk}
        rows = []
        try:
            ents = (self._api({"action": "wbgetentities", "sites": "enwiki", "titles": "|".join(by_title), "props": "labels|descriptions|aliases|claims|sitelinks",
                               "languages": "en|mul"}, state).get("entities") or {})
            for q, e in ents.items():
                if "missing" in e or not str(q).startswith("Q"):
                    continue
                title = ((e.get("sitelinks") or {}).get("enwiki") or {}).get("title")
                if title in by_title:
                    state["_viewbuf"].append((int(q[1:]), by_title[title]))
                rows.append(e)
        except Refused:                                    # titles and records through the query service
            q_of = wdqs_titles(list(by_title), self.folder)
            ents = wdqs_entities(list(q_of.values()), self.folder)
            for title, q in q_of.items():
                if q in ents:
                    state["_viewbuf"].append((int(q[1:]), by_title[title]))
                    rows.append(ents[q])
        self._name_values(rows, state)
        METER.start(len(rows), "rows")
        return self._each(rows, state)


# ------------------------------------------------------------------------------------------------ complete domains (1.42)
# 100% of a domain, in tiers. A hot lattice takes the best-known few thousand of a kind; a complete domain takes EVERYONE
# Wikidata records in it: every actor, every author, every athlete. The whole list comes from Wikidata's query service
# (everyone with the occupation, and with every narrower occupation under it — all 935 kinds of athlete), the best known
# first; their records are then read 50 at a time, exactly as the lanes and the lattices write them.
#   tier 1  people who face the public: actors, authors, television and radio, music, models, speakers, officials, athletes
#   tier 2  people in key jobs of critical fields: medicine, engineering, science, law, business and finance, teaching, flight
#   tier 3  people in other well-known fields: the visual arts, film-making, religion, scholarship, exploration
# Each code below was checked against Wikidata's own label on 2026-11-12; the label is checked again at every discovery,
# and a code whose label no longer matches is left out and reported (a wrong code would harvest the wrong people).
# (property, item, the label it must have, with every narrower kind under it)
DOMAINS = {
    "actors": (1, "Every actor", (("P106", "Q33999", "actor", True),)),
    "authors": (1, "Every author and writer", (("P106", "Q36180", "writer", True), ("P106", "Q482980", "author", False))),
    "television-radio": (1, "Every television and radio personality, presenter, journalist and comedian", (
        ("P106", "Q947873", "television presenter", True), ("P106", "Q44508716", "television personality", False), ("P106", "Q270389", "news presenter", False),
        ("P106", "Q18668527", "talk show host", False), ("P106", "Q2722764", "radio personality", True), ("P106", "Q1371925", "announcer", False),
        ("P106", "Q130857", "disc jockey", False), ("P106", "Q15077007", "podcaster", False), ("P106", "Q17125263", "YouTuber", False),
        ("P106", "Q2045208", "Internet celebrity", False), ("P106", "Q2906862", "influencer", False), ("P106", "Q2986228", "sports commentator", False),
        ("P106", "Q245068", "comedian", True), ("P106", "Q1930187", "journalist", True))),
    "music": (1, "Every music recording artist", (
        ("P106", "Q177220", "singer", True), ("P106", "Q639669", "musician", True), ("P106", "Q55960555", "recording artist", False),
        ("P106", "Q36834", "composer", False), ("P106", "Q753110", "songwriter", False), ("P31", "Q215380", "musical group", True))),
    "models": (1, "Every fashion model and pageant contestant", (
        ("P106", "Q4610556", "model", True), ("P106", "Q3357567", "fashion model", False), ("P106", "Q18581305", "beauty pageant contestant", False))),
    "speakers": (1, "Every public speaker, orator, preacher and activist", (
        ("P106", "Q12859263", "orator", False), ("P106", "Q15982858", "motivational speaker", False), ("P106", "Q662729", "public figure", False),
        ("P106", "Q30107072", "televangelist", False), ("P106", "Q432386", "preacher", False), ("P106", "Q15253558", "activist", True))),
    "officials": (1, "Every public official: politicians, judges, diplomats, officers, civil servants", (
        ("P106", "Q82955", "politician", False), ("P106", "Q212238", "civil servant", False), ("P106", "Q599151", "official", False),
        ("P106", "Q16533", "judge", False), ("P106", "Q193391", "diplomat", False), ("P106", "Q372436", "statesperson", False),
        ("P106", "Q189290", "military officer", False), ("P106", "Q116", "monarch", False))),
    "athletes": (1, "Every athlete, professional and amateur, and every coach", (
        ("P106", "Q2066131", "athlete", True), ("P106", "Q50995749", "sportsperson", False), ("P106", "Q41583", "coach", False))),
    "key-professions": (2, "People in key jobs: medicine, engineering, science, law, business, finance, teaching, flight", (
        ("P106", "Q39631", "physician", True), ("P106", "Q81096", "engineer", True), ("P106", "Q901", "scientist", True),
        ("P106", "Q40348", "lawyer", False), ("P106", "Q43845", "businessperson", True), ("P106", "Q131524", "entrepreneur", False),
        ("P106", "Q484876", "chief executive officer", False), ("P106", "Q806798", "banker", False), ("P106", "Q188094", "economist", False),
        ("P106", "Q1622272", "university teacher", False), ("P106", "Q37226", "teacher", False), ("P106", "Q2095549", "aircraft pilot", False),
        ("P106", "Q11631", "astronaut", False), ("P106", "Q205375", "inventor", False), ("P106", "Q42973", "architect", False),
        ("P106", "Q2462658", "manager", False), ("P106", "Q82594", "computer scientist", False), ("P106", "Q212980", "psychologist", False))),
    "arts-faith-scholarship": (3, "People in other well-known fields: art, film-making, religion, scholarship, exploration", (
        ("P106", "Q1028181", "painter", False), ("P106", "Q1281618", "sculptor", False), ("P106", "Q33231", "photographer", False),
        ("P106", "Q5322166", "designer", False), ("P106", "Q644687", "illustrator", False), ("P106", "Q2526255", "film director", False),
        ("P106", "Q3282637", "film producer", False), ("P106", "Q28389", "screenwriter", False), ("P106", "Q5716684", "dancer", False),
        ("P106", "Q42603", "priest", True), ("P106", "Q1234713", "theologian", False), ("P106", "Q152002", "pastor", False),
        ("P106", "Q133485", "rabbi", False), ("P106", "Q125482", "imam", False), ("P106", "Q219477", "missionary", False),
        ("P106", "Q733786", "monk", False), ("P106", "Q191808", "nun", False), ("P106", "Q15995642", "religious leader", False),
        ("P106", "Q4964182", "philosopher", False), ("P106", "Q201788", "historian", False), ("P106", "Q11900058", "explorer", False),
        ("P106", "Q10873124", "chess player", False), ("P106", "Q12362622", "philanthropist", False), ("P106", "Q333634", "translator", False))),
}
# ------------------------------------------------------------------------------------------------ icons (1.43)
# The icons of the culture, first. Before anything else is harvested: the TOP of each type people ask about — the major
# leagues' teams, the best-known athletes, bands and singers, screen stars, films and series, presidents and leaders,
# countries, cities, landmarks, universities, wars, religions, holidays — ranked by how well known each is (the number
# of Wikipedias with an article about it), with a weight for the user's own culture (the United States by default). The
# hot lattices ranked by how often Wikidata's own records point at an item, which is not fame: after hours of harvesting
# "the Dodgers" was still unknown. Each icons set is small and finishes within the hour; the complete domains follow.
# (property, item, the label it must have, with every narrower kind, how many of the best known, an extra condition,
#  the least fame worth asking for — for kinds too large to rank whole)
CULTURE = ("Q30", "United States")         # the setting bulk:culture replaces it ("Q145" for the United Kingdom, ...)
CULTURE_WEIGHT = 1.5
TEAM = "wdt:P31/wdt:P279* wd:Q12973014 ; "   # (Q12973014: sports team, checked) — a league's teams, not its players
ICONS = {
    "sports-teams": (0, "The teams: every major-league team, and the best-known teams of every sport", (
        ("P118", "Q1163715", "Major League Baseball", False, 80, TEAM, 0), ("P118", "Q1215884", "National Football League", False, 80, TEAM, 0),
        ("P118", "Q155223", "National Basketball Association", False, 80, TEAM, 0), ("P118", "Q18543", "Major League Soccer", False, 80, TEAM, 0),
        ("P118", "Q2593221", "Women's National Basketball Association", False, 40, TEAM, 0),
        ("P31", "Q13027888", "baseball team", True, 300, "", 0), ("P31", "Q13393265", "basketball team", True, 300, "", 0),
        ("P31", "Q17156793", "American football team", True, 300, "", 0), ("P31", "Q4498974", "ice hockey team", True, 300, "", 0),
        ("P31", "Q476028", "association football club", False, 400, "", 0), ("P31", "Q1194951", "national sports team", True, 300, "", 0),
        ("P31", "Q847017", "sports club", False, 300, "", 0))),
    "athletes": (0, "The best-known athletes of every sport", (("P106", "Q2066131", "athlete", True, 8000, "", 0),)),
    "music": (0, "The best-known bands, singers and musicians", (
        ("P31", "Q215380", "musical group", True, 4000, "", 0), ("P106", "Q177220", "singer", True, 4000, "", 0),
        ("P106", "Q639669", "musician", True, 4000, "", 0))),
    "screen": (0, "The best-known actors, hosts, comedians, directors, films and television series", (
        ("P106", "Q33999", "actor", True, 5000, "", 0), ("P106", "Q947873", "television presenter", True, 1500, "", 0),
        ("P106", "Q245068", "comedian", True, 1500, "", 0), ("P106", "Q2526255", "film director", False, 1500, "", 0),
        ("P31", "Q11424", "film", False, 4000, "", 25), ("P31", "Q5398426", "television series", False, 2500, "", 15))),
    "leaders-writers": (0, "Presidents, the best-known American politicians, monarchs and writers", (
        ("P39", "Q11696", "President of the United States", False, 100, "", 0), ("P39", "Q14211", "Prime Minister of the United Kingdom", False, 100, "", 0),
        ("P106", "Q82955", "politician", False, 4000, "wdt:P27 wd:Q30 ; ", 0), ("P106", "Q116", "monarch", False, 800, "", 0),
        ("P106", "Q36180", "writer", True, 4000, "", 0))),
    "places-landmarks": (0, "Countries, states, the best-known cities, landmarks, universities and museums", (
        ("P31", "Q6256", "country", False, 300, "", 0), ("P31", "Q3624078", "sovereign state", False, 300, "", 0), ("P31", "Q35657", "U.S. state", False, 60, "", 0),
        ("P31", "Q515", "city", False, 2000, "", 20), ("P31", "Q4989906", "monument", False, 1500, "", 0), ("P31", "Q570116", "tourist attraction", False, 2000, "", 0),
        ("P31", "Q3918", "university", False, 1500, "", 0), ("P31", "Q33506", "museum", False, 1000, "", 0), ("P31", "Q46169", "national park", False, 500, "", 0))),
    "culture-events": (0, "Wars and battles, religions, holidays, sports, instruments, foods, awards and what everyone looks up", (
        ("P31", "Q198", "war", False, 800, "", 0), ("P31", "Q178561", "battle", False, 1500, "", 0), ("P31", "Q9174", "religion", False, 300, "", 0),
        ("P31", "Q1445650", "holiday", False, 500, "", 0), ("P31", "Q349", "sport", False, 500, "", 0), ("P31", "Q34379", "musical instrument", False, 500, "", 0),
        ("P31", "Q2095", "food", False, 800, "", 0), ("P31", "Q618779", "award", False, 800, "", 0), ("P31", "Q167170", "multi-sport event", False, 300, "", 0),
        ("P31", "Q11344", "chemical element", False, 200, "", 0), ("P31", "Q634", "planet", False, 50, "", 0), ("P31", "Q12136", "disease", False, 800, "", 0))),
    # 1.45: "QueryBook does not know who Moses is." The sets above had no place for the figures of faith, thought, science
    # and the arts — the people and works asked about for centuries. (Every code's label checked against Wikidata.)
    "faith-thought-science": (0, "Figures of the Bible and of every faith, gods, popes, philosophers, scientists, inventors and explorers", (
        ("P31", "Q20643955", "human biblical figure", False, 800, "", 0), ("P106", "Q42857", "prophet", False, 300, "", 0),
        ("P31", "Q178885", "deity", True, 800, "", 0), ("P39", "Q19546", "Pope", False, 300, "", 0), ("P31", "Q179461", "religious text", True, 300, "", 0),
        ("P106", "Q4964182", "philosopher", False, 1500, "", 0), ("P106", "Q1234713", "theologian", False, 500, "", 0),
        ("P106", "Q169470", "physicist", False, 1000, "", 0), ("P106", "Q170790", "mathematician", False, 1000, "", 0),
        ("P106", "Q593644", "chemist", False, 800, "", 0), ("P106", "Q205375", "inventor", False, 800, "", 0),
        ("P106", "Q11900058", "explorer", False, 800, "", 0), ("P106", "Q11631", "astronaut", False, 400, "", 0),
        ("P106", "Q188094", "economist", False, 500, "", 0), ("P106", "Q1402561", "military leader", False, 800, "", 0))),
    "arts-business-works": (0, "Painters, composers, architects, founders and companies, characters of myth and story, and the best-known works", (
        ("P106", "Q1028181", "painter", False, 1500, "", 0), ("P106", "Q36834", "composer", False, 1500, "", 0),
        ("P106", "Q1281618", "sculptor", False, 400, "", 0), ("P106", "Q42973", "architect", False, 600, "", 0),
        ("P106", "Q131524", "entrepreneur", False, 1000, "", 0), ("P106", "Q43845", "businessperson", False, 1000, "", 0),
        ("P31", "Q4830453", "business", False, 2000, "", 30), ("P31", "Q22988604", "mythological Greek character", False, 500, "", 0),
        ("P31", "Q3658341", "literary character", False, 500, "", 0), ("P31", "Q7725634", "literary work", False, 2000, "", 20),
        ("P31", "Q3305213", "painting", False, 500, "", 15), ("P31", "Q7889", "video game", False, 800, "", 20),
        ("P31", "Q482994", "album", False, 800, "", 20), ("P31", "Q7366", "song", False, 800, "", 20))),
    # 1.46 — the user: "Use influence, wealth, leadership as a basis of identifying more ICONs."
    "government-leadership": (0, "Leadership: heads of state and of government of every country, Nobel laureates, judges, diplomats, commanders", (
        ("P39", "Q48352", "head of state", True, 2500, "", 0), ("P39", "Q2285706", "head of government", True, 2500, "", 0),
        ("P166", "Q7191", "Nobel Prize", True, 1200, "", 0), ("P106", "Q16533", "judge", False, 500, "", 0),
        ("P106", "Q193391", "diplomat", False, 500, "", 0), ("P106", "Q189290", "military officer", False, 800, "", 0))),
    "wealth-technology": (0, "Wealth and technology: everyone whose fortune is on record, chief executives, engineers, programmers, companies, software, websites", (
        ("P31", "Q5", "human", False, 2500, "wdt:P2218 ?worth ; ", 0),         # (P2218: net worth, checked) — wealth
        ("P106", "Q484876", "chief executive officer", False, 800, "", 0), ("P106", "Q82594", "computer scientist", False, 800, "", 0),
        ("P106", "Q5482740", "programmer", False, 500, "", 0), ("P106", "Q81096", "engineer", False, 800, "", 0),
        ("P31", "Q891723", "public company", False, 1500, "", 15), ("P31", "Q7397", "software", False, 800, "", 15),
        ("P31", "Q35127", "website", False, 800, "", 15))),
    "news-media": (0, "Influence: journalists, news presenters, newspapers, magazines, broadcasters and television stations", (
        ("P106", "Q1930187", "journalist", False, 2500, "", 0), ("P106", "Q270389", "news presenter", False, 500, "", 0),
        ("P31", "Q11032", "newspaper", False, 800, "", 10), ("P31", "Q41298", "magazine", False, 800, "", 10),
        ("P31", "Q15265344", "broadcaster", False, 500, "", 10), ("P31", "Q1616075", "television station", False, 500, "", 10))),
}
# 1.46 — the user: "Segment ICONs into categories - government, religion, literature, culture, news, entertainment, music,
# technology, etc." Every kind an icons set asks for belongs to one category (by its code; a set's own default otherwise).
ICON_CATEGORIES = ("Government and leadership", "Religion", "Literature", "Culture and history", "News and media", "Entertainment",
                   "Music", "Sports", "Science and technology", "Business and wealth", "Arts", "Places")
ICON_SET_CATEGORY = {"sports-teams": "Sports", "athletes": "Sports", "music": "Music", "screen": "Entertainment",
                     "leaders-writers": "Government and leadership", "places-landmarks": "Places", "culture-events": "Culture and history",
                     "faith-thought-science": "Science and technology", "arts-business-works": "Arts",
                     "government-leadership": "Government and leadership", "wealth-technology": "Business and wealth", "news-media": "News and media"}
ICON_CATEGORY = {
    "Q36180": "Literature", "Q7725634": "Literature", "Q3658341": "Literature",
    "Q20643955": "Religion", "Q42857": "Religion", "Q178885": "Religion", "Q19546": "Religion", "Q179461": "Religion", "Q1234713": "Religion",
    "Q9174": "Religion", "Q1445650": "Culture and history", "Q22988604": "Culture and history",
    "Q4964182": "Culture and history", "Q11900058": "Culture and history", "Q1402561": "Government and leadership",
    "Q188094": "Business and wealth", "Q131524": "Business and wealth", "Q43845": "Business and wealth", "Q4830453": "Business and wealth",
    "Q891723": "Business and wealth", "Q484876": "Business and wealth", "Q5": "Business and wealth",
    "Q82594": "Science and technology", "Q5482740": "Science and technology", "Q81096": "Science and technology",
    "Q7397": "Science and technology", "Q35127": "Science and technology", "Q11344": "Science and technology", "Q634": "Science and technology",
    "Q12136": "Science and technology", "Q7889": "Entertainment", "Q482994": "Music", "Q7366": "Music", "Q36834": "Music", "Q34379": "Music",
    "Q349": "Sports", "Q167170": "Sports", "Q3918": "Places", "Q33506": "Places"}


def icon_category(set_name, root_item):
    return ICON_CATEGORY.get(root_item) or ICON_SET_CATEGORY.get(set_name) or "Culture and history"


def icon_categories():
    """{category: [the kinds asked for under it]} over every icons set, in the user's order"""
    out = {c: [] for c in ICON_CATEGORIES}
    for name, (_tier, _title, roots) in ICONS.items():
        for r in roots:
            kind = "people whose fortune is on record" if r[1] == "Q5" else r[2]
            out.setdefault(icon_category(name, r[1]), []).append(kind)
    return out


WDQS = "https://query.wikidata.org/sparql"
DOMAIN_PAUSE_S = 2.0               # between two queries (the query service allows one client a share of its time)
DOMAIN_SLOW_S = 45                 # the query service cuts an answer off at 60 s and sends what it had: slower than this is not trusted


def DOMAIN_QUERY(sparql):
    """one query to Wikidata's query service: [[cell, ...], ...] without the header row (the tests replace this)"""
    req = urllib.request.Request(WDQS, data=urllib.parse.urlencode({"query": sparql}).encode(),
                                 headers={"User-Agent": UA, "Accept": "text/tab-separated-values"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            lines = r.read().decode("utf-8", "replace").split("\n")
    except http.client.HTTPException as e:               # the connection dropped mid-answer: a failed query, not a crash
        raise OSError("connection dropped: %s" % type(e).__name__)
    return [ln.split("\t") for ln in lines[1:] if ln.strip()]


def _qn(cell):
    m = re.search(r"Q(\d+)>?$", cell.strip())
    return int(m.group(1)) if m else None


ICON_BLOCK = 50                    # an icons set takes the best 50 of each of its types in turn, in the order the types are listed


def interleave(lists, block=ICON_BLOCK):
    """the first `block` of every list (in the lists' own order), then the next `block` of each — once each. So the major
    leagues' teams (listed first) are read before the 51st-best-known football club in the world."""
    out, seen = [], set()
    for start in range(0, max((len(x) for x in lists), default=0), block):
        for x in lists:
            for k in x[start:start + block]:
                if k not in seen:
                    seen.add(k)
                    out.append(k)
    return out


def _num(cell):
    try:
        return int(float(cell.strip().strip('"').split('"')[0] or 0))
    except ValueError:
        return 0


def domain_discover(name, query=None, pause=None, table=None, folder=None, culture=None):
    """everything in a domain or an icons set: {"ids": [Q-numbers, best known first], "roots": [...report...], "people": n}.
    Per root: its label is checked; its narrower kinds are listed; the items of each group of kinds are asked for with
    how well known they are (Wikipedias with an article). A group that is slow or fails is halved. A complete domain then
    asks for a kind that still fails WITHOUT the fame (the plain list is fast and complete — nobody is dropped for being
    slow); an icons set, which wants only the best known, leaves that kind out and says so. Icons are weighted for the
    user's culture and cut to the best known of each root."""
    base_query = query or DOMAIN_QUERY
    pause = DOMAIN_PAUSE_S if pause is None else pause
    table = DOMAINS if table is None else table
    tier, title, roots = table[name]
    culture = culture or CULTURE[0]
    slots = Slots(folder) if folder else None

    def query(sparql):
        """the service allows one computer a few queries at a time: every agent takes its turn (two at once), and a refusal waits"""
        lock, t0 = None, time.time()
        while slots is not None and lock is None and time.time() - t0 < 600:
            lock = slots._lock("wikidata-query", 0) or slots._lock("wikidata-query", 1)
            if lock is None:
                time.sleep(0.5)
        try:
            for attempt in range(4):
                try:
                    return base_query(sparql)
                except urllib.error.HTTPError as e:
                    if e.code not in REFUSED or attempt == 3:
                        raise
                    time.sleep(max(15 * (attempt + 1), _retry_after(e)))
        finally:
            if lock is not None:
                slots.release(lock)
    fame, home, report, per_root = {}, set(), [], []
    got = query("SELECT ?i ?l WHERE { VALUES ?i { %s } ?i rdfs:label ?l FILTER(LANG(?l) = \"en\") }" % " ".join(sorted({"wd:" + r[1] for r in roots})))
    labels = {_qn(r[0]): r[1].strip().strip('"').rsplit('"@', 1)[0] for r in got if len(r) > 1 and _qn(r[0])}

    def people(prop, classes, extra, least, ranked_only):
        """{item: fame} for these kinds; splits on trouble"""
        t0 = time.time()
        vals = " ".join("wd:Q%d" % c for c in classes)
        try:
            rows = query("SELECT DISTINCT ?p ?n WHERE { VALUES ?c { %s } ?p wdt:%s ?c ; %swikibase:sitelinks ?n %s}" % (
                vals, prop, extra, "FILTER(?n >= %d) " % least if least else ""))
            if time.time() - t0 < DOMAIN_SLOW_S:
                return {_qn(r[0]): _num(r[1]) if len(r) > 1 else 0 for r in rows if _qn(r[0])}
        except (OSError, ValueError):
            pass
        time.sleep(pause)
        if len(classes) > 1:
            half = len(classes) // 2
            out = people(prop, classes[:half], extra, least, ranked_only)
            out.update(people(prop, classes[half:], extra, least, ranked_only))
            return out
        if ranked_only:
            raise LookupError("too many to rank")
        rows = query("SELECT ?p WHERE { ?p wdt:%s wd:Q%d }" % (prop, classes[0]))      # the plain list: complete, fame unknown
        return {_qn(r[0]): 0 for r in rows if _qn(r[0])}

    def at_home(prop, classes, extra):
        """the items of these kinds that belong to the user's culture (a person's citizenship, a thing's country)"""
        out = set()
        tie = "wdt:P27" if prop in ("P106", "P39") else "wdt:P17"
        for i in range(0, len(classes), 40):
            try:
                time.sleep(pause)
                out |= {_qn(r[0]) for r in query("SELECT DISTINCT ?p WHERE { VALUES ?c { %s } ?p wdt:%s ?c ; %s%s wd:%s }" % (
                    " ".join("wd:Q%d" % c for c in classes[i:i + 40]), prop, extra, tie, culture)) if _qn(r[0])}
            except (OSError, ValueError):
                pass                                    # no weight for this group: it is ranked by fame alone
        return out
    for r in roots:
        prop, q, label, sub = r[0], r[1], r[2], r[3]
        top, extra, least = (r[4], r[5], r[6]) if len(r) > 4 else (None, "", 0)
        qn = int(q[1:])
        if (labels.get(qn) or "").casefold() != label.casefold():
            report.append({"item": q, "expected": label, "found": labels.get(qn), "people": 0, "used": False,
                           "why": "its label is not “%s” — left out, so the wrong things are not harvested" % label})
            continue
        classes = [qn]
        if sub:
            time.sleep(pause)
            classes = sorted({_qn(x[0]) for x in query("SELECT DISTINCT ?c WHERE { ?c wdt:P279* wd:%s }" % q) if _qn(x[0])} | {qn})[:3000]
        mine, lost = {}, 0
        for i in range(0, len(classes), 40):
            time.sleep(pause)
            try:
                mine.update(people(prop, classes[i:i + 40], extra, least, top is not None))
            except LookupError:
                lost += 1
        if top is not None:                             # icons: weighted for the culture, the best known of this root only
            mine_home = at_home(prop, classes, extra) if "wd:" + culture not in extra else set(mine)
            home |= mine_home
            keep = sorted(mine, key=lambda k: (-(mine[k] * (CULTURE_WEIGHT if k in mine_home else 1.0)), k))[:top]
            mine = {k: mine[k] for k in keep}
            per_root.append(keep)
        for k, v in mine.items():
            fame[k] = max(fame.get(k, 0), v)
        report.append(dict({"item": q, "expected": label, "found": labels.get(qn), "kinds": len(classes), "people": len(mine), "used": True},
                           **({"why": "%d kind(s) too large to rank were left out" % lost} if lost else {})))
    ids = sorted(fame, key=lambda k: (-(fame[k] * (CULTURE_WEIGHT if k in home else 1.0)), k))
    if per_root:                                        # icons: the top of every type in turn, the types in their listed order
        ids = interleave(per_root)
    return {"name": name, "tier": tier, "title": title, "read": time.time(), "edition": time.strftime("%Y-%m"), "people": len(ids), "roots": report,
            "ids": ids, "culture": culture}


def domain_path(commons_folder, name, kind="domain"):
    return os.path.join(commons_folder, FOLDER, "_%s-%s.json.gz" % (kind, name))


def domain_load(commons_folder, name, kind="domain"):
    import gzip
    try:
        with gzip.open(domain_path(commons_folder, name, kind), "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, EOFError):
        return None


def domains_report(commons_folder):
    """[{name, tier, title, people, roots, read}] for the page: who is in each complete domain, and which codes were left out"""
    out = []
    for kind, table, prefix in (("icons", ICONS, "hot-top-"), ("domain", DOMAINS, "hot-all-")):
        for name, (tier, title, _roots) in table.items():
            d = domain_load(commons_folder, name, kind) or {}
            out.append({"name": name, "tier": tier, "title": title, "people": d.get("people"), "read": d.get("read"),
                        "roots": d.get("roots") or [], "key": prefix + name, "culture": d.get("culture"),
                        "categories": sorted({icon_category(name, r[1]) for r in _roots}) if kind == "icons" else []})
    return out


class WikidataDomain(WikidataHot):
    """ONE complete domain: everyone in it, the best known first, each person's whole record."""
    BATCH = 500                                        # people per part (ten requests of 50)
    TABLE, KIND = DOMAINS, "domain"
    CIRCLE_RING = None                                 # a complete domain is millions of people: not the centre of the net

    def __init__(self, name):
        self.name = name
        self.tier, self.title_short, self.roots = self.TABLE[name]
        self.depth, self.finds = 0, ()
        self.key = "hot-all-" + name
        self.title = "Complete domain (tier %d) — %s" % (self.tier, self.title_short)
        self.why = "100% of a domain people ask about: everyone Wikidata records in it, the best known first, read directly"
        self.approx = "everyone in the domain, listed afresh every month"

    def _ids(self):
        d = getattr(self, "_disc", None) or domain_load(self.folder, self.name, self.KIND)
        if not d or d.get("edition") != time.strftime("%Y-%m"):
            import gzip
            AGENT["waiting"] = "listing everyone in this domain (Wikidata's query service)"
            try:
                d = domain_discover(self.name, table=self.TABLE, folder=self.folder, culture=getattr(self, "culture", None))
            finally:
                AGENT["waiting"] = None
            path = domain_path(self.folder, self.name, self.KIND)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with gzip.open(path + ".tmp", "wt", encoding="utf-8") as f:
                json.dump(d, f)
            _replace(path + ".tmp", path)
        self._disc = d
        return d

    def parts(self):
        d = self._ids()
        n = len(d["ids"])
        return [("%s everyone in %s %07d-%07d of %07d" % (d["edition"], self.name, i + 1, min(n, i + self.BATCH), n), "domain#%d" % i)
                for i in range(0, n, self.BATCH)]

    def rows(self, part, url, state):
        start = int(url.split("#")[1])
        ids = self._ids()["ids"][start:start + self.BATCH]
        ents = self._entities(["Q%d" % q for q in ids], state)
        rows = [ents[k] for k in ("Q%d" % q for q in ids) if k in ents and "missing" not in ents[k]]
        self._name_values(rows, state)
        METER.start(len(rows), "rows")
        return self._each(rows, state)


class WikidataIcons(WikidataDomain):
    """ONE icons set: the best known of each type it names, weighted for the user's culture — read before anything else."""
    BATCH = 250
    TABLE, KIND = ICONS, "icons"
    CIRCLE_RING = 0

    def __init__(self, name):
        super().__init__(name)
        self.key = "hot-top-" + name
        self.title = "Icons — " + self.title_short
        self.why = "the icons of the culture first: the best known of each type people ask about, ranked by fame, weighted for the user's country"
        self.approx = "the best known of each type, listed afresh every month"

    def prepare(self, run):
        self.culture = (run.commons.setting("bulk:culture") or CULTURE[0]).strip() or CULTURE[0]
        return super().prepare(run)


SEED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hot_seed.json")


def seed_load():
    """the icons list that ships inside QueryBook (tools/build_hot_seed.py): {"made", "ids": [...], "sets": {...}} or None"""
    d = _read_json(SEED_FILE, None)
    return d if isinstance(d, dict) and d.get("ids") else None


# ---- 1.46: the network of nets. The user: "Add every relative, friend, associate, partner, subordinate, successor, etc - of an
# ICON - and do the same thing with their circle. Expand the lattice net - to a network of nets."
# The ties followed (every code's label checked against Wikidata):
CIRCLE_TIES = (
    # family and companions
    "P26", "P40", "P22", "P25", "P3373", "P451", "P1038", "P1290", "P53", "P3342",
    # partners, teachers and pupils, those before and after
    "P1327", "P2652", "P737", "P1066", "P802", "P184", "P185", "P1365", "P1366", "P155", "P156",
    # who leads, founded, owns or belongs
    "P112", "P169", "P488", "P286", "P1037", "P3320", "P2828", "P6", "P35", "P527", "P463", "P54", "P127", "P1830", "P749", "P355",
    # who made it and who is in it
    "P175", "P161", "P57", "P50", "P86", "P58", "P162", "P371", "P676", "P84", "P170", "P725", "P674", "P176", "P178", "P123",
    # places
    "P19", "P20", "P119", "P551", "P159", "P276", "P115", "P740", "P937", "P36", "P840", "P915",
    # events, works, honours, schools, employers, offices
    "P1344", "P710", "P793", "P607", "P800", "P166", "P1411", "P108", "P69", "P102", "P39", "P264", "P361", "P118", "P179",
    "P138", "P144", "P941", "P1441", "P449", "P272")
CIRCLE_RINGS = 3                   # an icon's circle, their circle, and theirs
CIRCLE_WAVE = 5000                 # subjects listed at a time: the net is looked at again when they are read
CIRCLE_AGAIN_S = 300


def circle_wave(commons_folder, limit=None):
    """the next subjects of the net: {"ids": [...], "rings": {q: ring}, "waiting": n} — tied to something already read, not
    read themselves; the nearest ring first, in it the one most records point to"""
    tied, read = {}, set()
    for p in _label_dbs(commons_folder):
        try:
            db = _ro(p)
        except sqlite3.Error:
            continue
        try:
            for q, n, ring in db.execute("SELECT q, n, ring FROM circle"):
                e = tied.get(q)
                tied[q] = (n + (e[0] if e else 0), min(ring, e[1]) if e else ring)
        except sqlite3.Error:
            pass
        for sql in ("SELECT q FROM circle_read", "SELECT q FROM fame"):
            try:
                read.update(q for q, in db.execute(sql))
            except sqlite3.Error:
                pass
        db.close()
    left = sorted((q for q in tied if q not in read), key=lambda q: (tied[q][1], -tied[q][0], q))
    ids = left[:limit or CIRCLE_WAVE]
    return {"ids": ids, "rings": {q: tied[q][1] for q in ids}, "waiting": len(left), "read": len(read)}


def circle_status(commons_folder):
    w = circle_wave(commons_folder, 1)
    return {"waiting": w["waiting"], "read": w["read"]}


class WikidataCircle(WikidataDomain):
    """the network of nets: everything the icons are tied to, then everything THOSE are tied to — never finished, only
    further out. Each wave is the 5,000 most tied-to subjects of the nearest unread ring."""
    BATCH = 250
    CIRCLE_RING = 1

    def __init__(self):
        self.name, self.key = "circle", "hot-circle"
        self.tier, self.title_short, self.roots, self.depth, self.finds = 0, "the circles of the icons", (), 0, ()
        self.title = "Network of nets — the circles of the icons, and their circles"
        self.why = ("every relative, partner, member, founder, successor, place, event and work an icon is tied to; then the same "
                    "for each of those — fame spreading outward ring by ring")
        self.approx = "grows as it reads: three rings out from about 63,000 icons"

    def _ids(self):
        d = getattr(self, "_disc", None)
        if d:
            return d
        path = domain_path(self.folder, "circle", "circle")
        d = domain_load(self.folder, "circle", "circle")
        if d and d.get("ids"):                           # a wave not read to its end is finished first
            w = circle_wave(self.folder, 1)
            done = set()
            for p in _label_dbs(self.folder):
                try:
                    db = _ro(p)
                    done.update(q for q, in db.execute("SELECT q FROM circle_read"))
                    db.close()
                except sqlite3.Error:
                    pass
            if all(q in done for q in d["ids"]):
                d = None
        if not d or not d.get("ids"):
            import gzip
            n = int((d or domain_load(self.folder, "circle", "circle") or {}).get("wave") or 0) + 1
            w = circle_wave(self.folder)
            d = {"ids": w["ids"], "rings": {str(q): r for q, r in w["rings"].items()}, "wave": n, "edition": "wave %06d" % n,
                 "waiting": w["waiting"]}
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with gzip.open(path + ".tmp", "wt", encoding="utf-8") as f:
                json.dump(d, f)
            _replace(path + ".tmp", path)
        self._disc = d
        return d

    def parts(self):
        d = self._ids()
        n = len(d["ids"])
        return [("%s the circles %05d-%05d of %05d" % (d["edition"], i + 1, min(n, i + self.BATCH), n), "domain#%d" % i)
                for i in range(0, n, self.BATCH)]

    def rows(self, part, url, state):
        start = int(url.split("#")[1])
        d = self._ids()
        ids = d["ids"][start:start + self.BATCH]
        state["_rings"] = {q: int((d.get("rings") or {}).get(str(q), 1)) for q in ids}
        state.setdefault("_readbuf", []).extend((q,) for q in ids)      # asked for: not listed again, found or not
        ents = self._entities(["Q%d" % q for q in ids], state)
        rows = [ents[k] for k in ("Q%d" % q for q in ids) if k in ents and "missing" not in ents[k]]
        self._name_values(rows, state)
        METER.start(len(rows), "rows")
        return self._each(rows, state)


class WikidataSeed(WikidataDomain):
    """1.44 — the hot list, IMMEDIATELY. Listing an icons set from Wikidata takes 5 to 15 minutes, two sets at a time: on a
    new start the hot list spent its first half hour asking who is famous and read nobody ("Who are the Beatles?" — no
    record). The answer to that question is shipped inside QueryBook: the icons of every set, ranked, listed when this
    version was built. This dataset reads their records straight away — the first 250 within the first minute — and the
    icons sets then list themselves afresh in their own time."""
    BATCH = 250
    CIRCLE_RING = 0

    def __init__(self):
        self.name, self.key = "seed", "hot-seed"
        self.tier, self.title_short, self.roots, self.depth, self.finds = 0, "the icons list shipped with QueryBook", (), 0, ()
        self.title = "Icons — the list shipped with QueryBook, read at once"
        self.why = "the best-known teams, athletes, bands, screen stars, leaders, places and events, listed in advance so reading starts immediately"
        self.approx = "about 63,000 subjects"

    def _ids(self):
        d = seed_load() or {"ids": [], "made": "none"}
        return {"ids": d["ids"], "edition": "seed " + str(d.get("made"))}

    def parts(self):
        d = self._ids()
        n = len(d["ids"])
        return [("%s icons %07d-%07d of %07d" % (d["edition"], i + 1, min(n, i + self.BATCH), n), "domain#%d" % i) for i in range(0, n, self.BATCH)]


def wd_views(commons_folder, qids):
    """{Q-number: Wikipedia page views, added up over the months sampled} for the items among the most read"""
    want, out = sorted(set(qids)), {}
    for p in _label_dbs(commons_folder):
        if not want:
            break
        try:
            db = _ro(p)
            for i in range(0, len(want), 500):
                chunk = want[i:i + 500]
                for q, v in db.execute("SELECT q, views FROM views WHERE q IN (%s)" % ",".join("?" * len(chunk)), chunk):
                    out[q] = out.get(q, 0) + v
            db.close()
        except sqlite3.Error:
            continue
    return out


def catalog():
    # 1.40: the demand agent and the hot lattices come first — what people ask about is harvested before anything else
    return {d.key: d for d in (WikidataDemand(), WikidataSeed()) + tuple(WikidataIcons(n) for n in ICONS) + (WikidataCircle(), WikidataMostRead()) + tuple(WikidataHot(n) for n in HOT) + tuple(WikidataDomain(n) for n in DOMAINS) + (WikidataDownload(), PubChem(), Taxonomy(), Weather(), GNIS(), FoodData(), Tatoeba(), Calendar(), Series(), MitOcw()) + tuple(WikidataDump(k) for k in range(1, WikidataDump.LANES + 1)) + (WikidataLattice(),)}


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
CREATE TABLE IF NOT EXISTS stage (fp BLOB NOT NULL, s TEXT NOT NULL, p INTEGER NOT NULL, o TEXT NOT NULL, part INTEGER NOT NULL, row INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS stage_links (fp BLOB NOT NULL, url TEXT NOT NULL);
"""


_FP = operator.itemgetter(0)


def home_path(commons_folder, key):
    """where a dataset's facts live for good: the shared folder (D:\\QB\\commons\\shards)"""
    return os.path.join(commons_folder, FOLDER, key + ".sqlite")


# ------------------------------------------------------------------------------------------------ fast working copies (C:) → home (D:)
# The agents write fastest to the computer's own drive (C:): with an external hard disk as home they all wait for it. So a
# dataset being harvested has a WORKING COPY on C: (~/QueryBook-Work); every DRAIN_S seconds one copier writes each working
# copy to its home on D: as one compacted, sequential file (VACUUM INTO — the kind of write a hard disk does fast), one at a
# time. A finished dataset's working copy is removed once its home copy holds the same facts. Readers find the working copy
# first (it is the newest). Off when the shared folder is on the system drive, or with QB_WORK_FOLDER=off.
DRAIN_S = 600
DRAIN_PACE = 3                    # 1.31.1: a working copy is saved at most once per 3x the time its last save took (D: stays
                                  # free for the agents at least two thirds of the time); an unchanged copy is not saved again
WORK_MIN_FREE_GB = 20


def work_dir(commons_folder):
    env = os.environ.get("QB_WORK_FOLDER")
    if env == "off":
        return None
    if env:
        base = env
    else:
        drive = os.path.splitdrive(os.path.abspath(commons_folder))[0].upper()
        system = (os.environ.get("SystemDrive") or "").upper()
        if not (drive and system and drive != system):
            return None
        base = os.path.join(os.path.expanduser("~"), "QueryBook-Work")
    return os.path.join(base, hashlib.sha256(os.path.abspath(commons_folder).lower().encode()).hexdigest()[:10])


def work_path(commons_folder, key):
    w = work_dir(commons_folder)
    return os.path.join(w, key + ".sqlite") if w else None


def shard_path(commons_folder, key):
    """the newest copy of a dataset: its working copy on C: while one exists, else its home on D:"""
    wp = work_path(commons_folder, key)
    if wp and os.path.exists(wp):
        return wp
    return home_path(commons_folder, key)


def _free(folder):
    try:
        return shutil.disk_usage(folder).free
    except OSError:
        return 0


def _sizes(p):
    return sum(os.path.getsize(p + x) for x in ("", "-wal", ".labels", ".labels-wal") if os.path.exists(p + x))


def pull(commons_folder, key):
    """make the dataset's working copy on C: (copying its home copy there first, one dataset at a time). False when
    working copies are off or C: has not room enough — the agent then writes to D: itself."""
    wp = work_path(commons_folder, key)
    if not wp:
        return False
    keep = float(os.environ.get("QB_WORK_MIN_FREE_GB") or WORK_MIN_FREE_GB) * 1e9
    if os.path.exists(wp):
        if _free(os.path.dirname(wp)) >= keep / 2:
            return True
        # re-route: the internal drive is filling up — this dataset's working copy goes home and the agent writes to D:
        try:
            if drain(commons_folder, key, force=True) not in (None, "busy", "no room", "later"):
                for x in ("", "-wal", "-shm", ".labels", ".labels-wal", ".labels-shm", ".progress"):
                    if os.path.exists(wp + x):
                        os.remove(wp + x)
                TR.event("work_copy", dataset=key, action="moved home", why="the internal drive is nearly full")
                return False
        except Exception as e:
            TR.fail("work copy home", e, dataset=key, retried=True)
        return True                               # could not move it yet: keep using it (the agent pauses if C: is full)
    os.makedirs(os.path.dirname(wp), exist_ok=True)
    hp = home_path(commons_folder, key)
    need = _sizes(hp) * 1.3
    free = _free(os.path.dirname(wp))
    if free - need < keep:
        TR.event("work_copy", dataset=key, action="skipped", why="the internal drive has %.0f GB free; working copies keep %.0f GB" % (free / 1e9, keep / 1e9))
        return False
    sl = Slots(commons_folder)
    while True:                                   # one copy at a time: the home disk reads one file in a long run
        lk = sl._lock("work-copy", 0)
        if lk:
            break
        time.sleep(0.5)
    try:
        if os.path.exists(wp):
            return True
        t = time.time()
        for sfx in ("", ".labels"):
            src = hp + sfx
            if not os.path.exists(src):
                continue
            try:
                c = sqlite3.connect(src, timeout=60)
                c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                c.close()
            except sqlite3.Error:
                pass
            _copy_progress(src, wp + sfx + ".pulling", commons_folder, key)
            os.replace(wp + sfx + ".pulling", wp + sfx)
        if os.path.exists(hp + ".progress"):
            shutil.copyfile(hp + ".progress", wp + ".progress")
        TR.event("work_copy", dataset=key, action="made", seconds=round(time.time() - t, 1), mb=round(_sizes(wp) / 1e6, 1))
        return True
    finally:
        try:
            os.remove(os.path.join(work_dir(commons_folder), "_copying.json"))
        except OSError:
            pass
        sl.release(lk)


def _copy_progress(src, dst, commons_folder, key):
    """copy in 8 MB pieces, writing how far it is (for the Harvesting tab) every 2 seconds"""
    total, done, t0, last = os.path.getsize(src), 0, time.time(), 0.0
    note = os.path.join(work_dir(commons_folder), "_copying.json")
    with open(src, "rb") as a, open(dst, "wb") as b:
        while True:
            buf = a.read(8 << 20)
            if not buf:
                break
            b.write(buf)
            done += len(buf)
            if time.time() - last > 2:
                last = time.time()
                try:
                    with open(note + ".tmp", "w") as f:
                        json.dump({"dataset": key, "file": os.path.basename(src), "done": done, "total": total,
                                   "since": t0, "at": last}, f)
                    _replace(note + ".tmp", note, tries=3)
                except OSError:
                    pass


def copying(commons_folder):
    """the copy to C: in progress, if any: {dataset, done, total, rate (bytes/s), eta_s}"""
    w = work_dir(commons_folder)
    if not w:
        return None
    try:
        with open(os.path.join(w, "_copying.json")) as f:
            c = json.load(f)
    except (OSError, ValueError):
        return None
    if time.time() - c.get("at", 0) > 60:
        return None
    el = max(0.001, c["at"] - c["since"])
    c["rate"] = c["done"] / el
    c["eta_s"] = (c["total"] - c["done"]) / c["rate"] if c["rate"] > 0 else None
    return c


def _drained_path(commons_folder):
    return os.path.join(commons_folder, FOLDER, "_drained.json")


def drained(commons_folder):
    try:
        with open(_drained_path(commons_folder)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _meta_of(path):
    try:
        db = _ro(path)
        try:
            return {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM meta WHERE key IN ('facts', 'duplicates_removed')")}
        finally:
            db.close()
    except (sqlite3.Error, ValueError):
        return None


MERGE_PIECES = 256                 # 1.37: a copy is merged in 256 pieces (by the first byte of each fact's fingerprint)


def merge_into(dst_path, src_path, start=0, progress=None, halt=None):
    """every fact of src that dst lacks is added to dst (predicates matched by name); returns how many were added.
    1.37: in 256 pieces, each saved as it is done. Before, the whole copy went in as ONE step — hours of disk work on a
    large dataset with nothing to show, and started again from nothing whenever it was interrupted (so on a store of a
    billion facts it could churn the data drive for a night and never finish). Now an interruption costs one piece:
    start = the piece to resume at; progress(pieces_done, added_so_far) after each; halt() True stops between pieces.
    Returns the number added by this call (see the piece reached through progress)."""
    db = sqlite3.connect(dst_path, timeout=120)
    try:
        db.executescript(SCHEMA)
        db.execute("ATTACH DATABASE ? AS h", (src_path,))
        db.execute("INSERT OR IGNORE INTO predicates(name, rule) SELECT name, rule FROM h.predicates")
        db.execute("INSERT OR IGNORE INTO parts(name, url, version) SELECT name, url, version FROM h.parts")
        db.commit()
        total = 0
        for i in range(max(0, int(start)), MERGE_PIECES):
            if halt and halt():
                break
            lo, hi = bytes([i]), (bytes([i + 1]) if i + 1 < MERGE_PIECES else None)
            where, args = ("f.fp >= ? AND f.fp < ?", (lo, hi)) if hi else ("f.fp >= ?", (lo,))
            if i == 0:
                where, args = "f.fp < ?", (hi,)                      # (an empty fingerprint sorts before every byte)
            before = db.total_changes
            db.execute("""INSERT OR IGNORE INTO facts(fp, s, p, o, part, row)
                          SELECT f.fp, f.s, mp.id, f.o, coalesce(mpt.id, f.part), f.row FROM h.facts f
                          JOIN h.predicates hp ON hp.id = f.p JOIN main.predicates mp ON mp.name = hp.name
                          LEFT JOIN h.parts hpt ON hpt.id = f.part LEFT JOIN main.parts mpt ON mpt.name = hpt.name
                          WHERE """ + where, args)
            added = db.total_changes - before
            lw, la = ("l.fp >= ? AND l.fp < ?", (lo, hi)) if hi else ("l.fp >= ?", (lo,))
            if i == 0:
                lw, la = "l.fp < ?", (hi,)
            db.execute("INSERT OR IGNORE INTO links(fp, url) SELECT l.fp, l.url FROM h.links l WHERE " + lw, la)
            if added:
                r = db.execute("SELECT value FROM meta WHERE key = 'facts'").fetchone()
                db.execute("INSERT INTO meta(key, value) VALUES('facts', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                           (json.dumps((json.loads(r[0]) if r else 0) + added),))
            db.commit()                                              # this piece is kept whatever happens next
            total += added
            if progress:
                progress(i + 1, total)
        db.execute("DETACH DATABASE h")
        return total
    finally:
        db.close()


def _changed_at(wp):
    """the last time anything of a working copy was written (the file, its log, its labels)"""
    return max((os.path.getmtime(wp + x) for x in ("", "-wal", ".labels", ".labels-wal") if os.path.exists(wp + x)), default=0)


def drain(commons_folder, key, force=False, pace=True):
    """write the working copy to its home on D: as one compacted, sequential file; returns the facts it holds (None when
    there is no working copy, "busy" when the home copy is open in a program and cannot be replaced yet, "later" when
    it was saved recently enough for its size). 1.31.1: a copy unchanged since its last save is not written again, and a
    big one is saved less often (DRAIN_PACE) — before, every copy (338 GB in all) was rewritten every 10 minutes, so the
    data drive never rested and every agent queued behind it. force=True (Stop, the end of a run) always saves."""
    wp = work_path(commons_folder, key)
    if not wp or not os.path.exists(wp):
        return None
    if not force:
        rec = drained(commons_folder).get(key) or {}
        if rec.get("snap") and _changed_at(wp) <= rec["snap"] and os.path.exists(home_path(commons_folder, key)):
            return rec.get("facts")                    # nothing new since the copy on D: was taken
        if pace and rec.get("at") and time.time() - rec["at"] < max(DRAIN_S, DRAIN_PACE * float(rec.get("seconds") or 0)):
            return "later"
    hp = home_path(commons_folder, key)
    if not os.path.isdir(commons_folder):
        TR.event("drain", dataset=key, result="waiting", why="the data drive is not connected; the working copy keeps every fact")
        return "busy"
    os.makedirs(os.path.dirname(hp), exist_ok=True)
    if _free(os.path.dirname(hp)) < _sizes(wp) * 1.1 + 1e9:
        TR.event("drain", dataset=key, result="no room", why="the data drive is nearly full; the working copy keeps every fact")
        return "no room"
    hm, wm = _meta_of(hp) if os.path.exists(hp) else None, _meta_of(wp)
    if hm and wm:                                  # never replace a home copy holding facts the working copy lacks (an
        expect = (wm.get("facts") or 0) + (wm.get("duplicates_removed") or 0) - (hm.get("duplicates_removed") or 0)
        if (hm.get("facts") or 0) > expect:        # older engine wrote to D: meanwhile): those facts are merged in first
            added = merge_into(wp, hp)
            TR.event("drain", dataset=key, result="merged", added=added,
                     why="the copy on the data drive held %d facts the working copy lacked; merged before saving" % added)
    t, facts = time.time(), None
    snap = time.time()                                 # the copy holds everything written before this moment
    for sfx in ("", ".labels"):
        src, dst = wp + sfx, hp + sfx
        if not os.path.exists(src):
            continue
        tmp = dst + ".draining"
        if os.path.exists(tmp):
            os.remove(tmp)
        c = sqlite3.connect(src, timeout=120)
        try:
            c.execute("VACUUM INTO ?", (tmp,))          # one consistent snapshot, written front to back
        except sqlite3.Error:
            try:
                os.remove(tmp)                          # never leave half a copy behind (a full disk, the drive gone)
            except OSError:
                pass
            raise
        finally:
            c.close()
        if not sfx:
            v = sqlite3.connect(tmp)
            try:
                r = v.execute("SELECT value FROM meta WHERE key = 'facts'").fetchone()
                facts = int(json.loads(r[0]) or 0) if r else 0
                rd = v.execute("SELECT value FROM meta WHERE key = 'duplicates_removed'").fetchone()
                tdups = int(json.loads(rd[0]) or 0) if rd else 0
            finally:
                v.close()
            hm2 = _meta_of(hp) if os.path.exists(hp) else None
            floor = ((hm2 or {}).get("facts") or 0) - max(0, tdups - ((hm2 or {}).get("duplicates_removed") or 0))
            if facts < floor:                           # 1.33 safeguard: the home copy is never replaced by a smaller one
                os.remove(tmp)
                TR.event("drain", dataset=key, result="refused", facts=facts, home_facts=(hm2 or {}).get("facts"),
                         why="the copy would hold fewer facts than the one on the data drive; the data drive's copy is kept")
                return "busy"
        try:
            for x in ("-wal", "-shm"):                   # an old log beside the home copy must never be applied to the new one
                if os.path.exists(dst + x):
                    os.remove(dst + x)
            _replace(tmp, dst, tries=10)
        except PermissionError:
            os.remove(tmp)
            TR.event("drain", dataset=key, result="busy", why="the home copy is open in a program; tried again next round")
            return "busy"
    if os.path.exists(wp + ".progress"):
        try:
            shutil.copyfile(wp + ".progress", hp + ".progress")
        except OSError:
            pass
    d = drained(commons_folder)
    d[key] = {"at": time.time(), "snap": snap, "facts": facts, "seconds": round(time.time() - t, 1)}
    try:
        with open(_drained_path(commons_folder) + ".tmp", "w") as f:
            json.dump(d, f)
        _replace(_drained_path(commons_folder) + ".tmp", _drained_path(commons_folder))
    except OSError:
        pass
    TR.event("drain", dataset=key, result="saved", facts=facts, seconds=round(time.time() - t, 1), mb=round(os.path.getsize(hp) / 1e6, 1))
    return facts


def other_copies(commons_folder, key):
    """every other copy of a dataset that exists: the home copy on D:, the working copy on C:, and the shared folders of
    earlier versions (~/QueryBook-Data/commons, a folder chosen with "Move the shared folder")"""
    cands = [work_path(commons_folder, key), home_path(commons_folder, key)]
    try:
        import qbdrive
        for kind, folder in qbdrive.old_places():
            if kind == "commons":
                cands.append(os.path.join(folder, FOLDER, key + ".sqlite"))
    except Exception:
        pass
    try:                                              # 1.33: the newest backup on the backup drive, when it is connected
        import qbvault
        cands.append(qbvault.latest_copy(commons_folder, "commons/%s/%s.sqlite" % (FOLDER, key)))
    except Exception:
        pass
    live = os.path.normcase(os.path.abspath(shard_path(commons_folder, key)))
    out, seen = [], {live}
    for p in cands:
        if p and os.path.exists(p) and os.path.normcase(os.path.abspath(p)) not in seen:
            seen.add(os.path.normcase(os.path.abspath(p)))
            out.append(p)
    return out


RESTORED_NAME = "_restored.json"


def _copy_stamp(path, meta):
    """what identifies a copy as it is now: its size, when it was last written, and the facts it says it holds"""
    try:
        return [os.path.getsize(path), int(os.path.getmtime(path)), int((meta or {}).get("facts") or 0)]
    except OSError:
        return None


def restore_missing(commons_folder, say=None, halt=None, hold=None):
    """1.31.2: for every dataset, every other copy is compared with the live one; when a copy holds more facts than the live
    one can account for (its count, plus the duplicates removed from it since), every fact it holds that the live copy lacks
    is added back (merge — nothing is ever deleted). Runs before the agents start, and from the Control Panel.
    1.37: a copy that was merged is written down (_restored.json) and is not merged again while it is unchanged — before,
    a copy whose count the live one could never 'account for' was merged again at EVERY start, for hours each time; and a
    merge that is interrupted resumes at the piece it had reached instead of starting over.
    Returns {dataset: {"from": path, "added": n}} for each dataset that got facts back."""
    out = {}
    led_path = os.path.join(commons_folder, FOLDER, RESTORED_NAME)
    led = _read_json(led_path, {})
    led = led if isinstance(led, dict) else {}
    for key, ds in catalog().items():
        if getattr(ds, "standalone", False):
            continue
        if halt and halt():
            break
        live = shard_path(commons_folder, key)
        for other in other_copies(commons_folder, key):
            lm = _meta_of(live) or {} if os.path.exists(live) else {}
            om = _meta_of(other) or {}
            expect = (lm.get("facts") or 0) + (lm.get("duplicates_removed") or 0) - (om.get("duplicates_removed") or 0)
            if (om.get("facts") or 0) <= expect:
                continue
            stamp, lk = _copy_stamp(other, om), key + "|" + os.path.normcase(os.path.abspath(other))
            rec = led.get(lk) or {}
            if stamp and rec.get("stamp") == stamp and rec.get("done"):
                continue                                    # this very copy was merged already: everything it holds is here
            resume = int(rec.get("piece") or 0) if stamp and rec.get("stamp") == stamp else 0
            had = int(rec.get("added") or 0) if resume else 0
            if say:
                say("adding back facts to %s from another copy (%s holds %s, the live copy %s)%s" % (
                    key, other, format(om.get("facts") or 0, ","), format(lm.get("facts") or 0, ","),
                    " — resuming at %d%%" % (100 * resume // MERGE_PIECES) if resume else ""))
            if not os.path.exists(live):                    # no live copy at all: the fuller copy becomes the home copy
                os.makedirs(os.path.dirname(home_path(commons_folder, key)), exist_ok=True)
                shutil.copyfile(other, home_path(commons_folder, key))
                added, reached = om.get("facts") or 0, MERGE_PIECES
            else:
                state = {"piece": resume}

                def step(piece, added_now, _lk=lk, _stamp=stamp, _had=had, _key=key, _other=other, _om=om, _lm=lm, _state=state):
                    _state["piece"] = piece
                    led[_lk] = {"stamp": _stamp, "piece": piece, "added": _had + added_now, "done": piece >= MERGE_PIECES, "at": time.time()}
                    _ka_save(led_path, led)
                    _restoring(commons_folder, {"key": _key, "from": _other, "facts": _om.get("facts") or 0, "live": _lm.get("facts") or 0,
                                                "piece": piece, "pieces": MERGE_PIECES, "added": _had + added_now})
                    if say:
                        say("adding back facts to %s from another copy: %d%% checked, %s added back so far" % (
                            _key, 100 * piece // MERGE_PIECES, format(_had + added_now, ",")))
                if hold:
                    hold(key, True)                         # 1.38: only this dataset waits; the others harvest meanwhile
                    live = shard_path(commons_folder, key)
                _restoring(commons_folder, {"key": key, "from": other, "facts": om.get("facts") or 0, "live": lm.get("facts") or 0,
                                            "piece": resume, "pieces": MERGE_PIECES, "added": had})
                try:
                    added = merge_into(live, other, resume, step, halt)
                finally:
                    _restoring(commons_folder, None)
                    if hold:
                        hold(key, False)
                reached = state["piece"]
            if stamp and reached >= MERGE_PIECES:
                led[lk] = {"stamp": stamp, "piece": MERGE_PIECES, "added": had + added, "done": True, "at": time.time()}
                _ka_save(led_path, led)
            r = out.setdefault(key, {"added": 0, "from": []})
            r["added"] += added
            r["from"].append(other)
            TR.event("restore", dataset=key, source=other, added=added, piece=reached)
    return out


def _restoring_path(commons_folder):
    return os.path.join(commons_folder, FOLDER, "_restoring.json")


def _restoring(commons_folder, what):
    """1.33: which dataset is having facts added back right now (the page shows the fuller copy's count meanwhile, never a
    fall: the live copy's own count only changes when the whole merge is done)"""
    p = _restoring_path(commons_folder)
    try:
        if what is None:
            if os.path.exists(p):
                os.remove(p)
        else:
            with open(p + ".tmp", "w") as f:
                json.dump(dict(what, at=time.time(), pid=os.getpid()), f)
            _replace(p + ".tmp", p)
    except OSError:
        pass


def restoring_now(commons_folder):
    try:
        with open(_restoring_path(commons_folder)) as f:
            r = json.load(f)
    except (OSError, ValueError):
        return None
    return r if _pid_alive(r.get("pid")) else None


def _pid_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if not h:
                return False
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(h)
            return code.value == 259                  # STILL_ACTIVE
        except Exception:
            return True
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def work_keys(commons_folder):
    w = work_dir(commons_folder)
    if not w or not os.path.isdir(w):
        return []
    return sorted(f[:-7] for f in os.listdir(w) if f.endswith(".sqlite"))


def finish_work(commons_folder, only_changed=False, note=None):
    """after the run: every working copy saved to D:; those of finished datasets removed from C: once D: holds the same
    facts. Returns {dataset: what happened}. only_changed (1.31.2: Stop and the hourly upkeep): a copy unchanged since its
    last save is not written again — Stop no longer rewrites hundreds of GB. note(i, n, key): progress for the page."""
    out = {}
    keys = work_keys(commons_folder)
    for i, key in enumerate(keys, 1):
        if note:
            note(i, len(keys), key)
        try:
            facts = drain(commons_folder, key, force=not only_changed, pace=False)
            wp = work_path(commons_folder, key)
            st = sqlite3.connect(wp)
            try:
                r = dict(st.execute("SELECT key, value FROM meta WHERE key IN ('facts', 'state')").fetchall())
            finally:
                st.close()
            done = json.loads(r.get("state", '""')) == "done"
            if done and facts not in (None, "busy", "no room") and facts == int(json.loads(r.get("facts", "0")) or 0):
                for x in ("", "-wal", "-shm", ".labels", ".labels-wal", ".labels-shm", ".progress"):
                    if os.path.exists(wp + x):
                        os.remove(wp + x)
                out[key] = "saved to D: and removed from C:"
            else:
                out[key] = "saved to D: (working copy kept: the dataset is not finished)" if facts not in (None, "busy", "no room") else str(facts)
        except Exception as e:
            TR.fail("finish working copy", e, dataset=key)
            out[key] = "error: %s" % e
    return out


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


class MergeSlots(Slots):
    """1.35: at most N agents file (fold their stage into the keyed tables) at once, in a pool of its own: an agent filing
    for half an hour no longer holds a write slot, so every other agent keeps appending batches meanwhile. try_take() never
    waits (an agent whose turn has not come keeps staging and tries again next batch); take() waits (the end of a part)."""

    def __init__(self, commons_folder, n):
        super().__init__(commons_folder)
        self.n = max(1, int(n or 1))

    def try_take(self):
        for i in range(self.n):
            f = self._lock("disk-merge", i)
            if f:
                return f
        return None

    def take(self, stop=None):
        while True:
            f = self.try_take()
            if f or (stop and stop()):
                return f
            time.sleep(0.5)


def merge_slots(commons_folder):
    drive = os.path.splitdrive(os.path.abspath(commons_folder))[0].upper()
    system = (os.environ.get("SystemDrive") or "").upper()
    return MERGE_SLOTS_EXTERNAL if drive and system and drive != system else MERGE_SLOTS_SYSTEM


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
    mslots = None

    def __init__(self, commons_folder, key, path=None):
        os.makedirs(os.path.join(commons_folder, FOLDER), exist_ok=True)
        self.path = path or shard_path(commons_folder, key)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=60)
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
        """one transaction: the facts, the part's progress and the running total — a restart resumes exactly here.
        1.33: the facts are APPENDED to the stage (a plain table, written front to back) instead of being inserted into the
        keyed tables. Inserting 500,000 random fingerprints into a keyed table of tens of millions touches nearly every
        page of it, so each batch cost more than the one before (a 40-million-fact lane read and rewrote gigabytes per
        batch, the commits outlasted the supervisor's patience, the agent was ended and its batch lost). The stage is
        folded in by merge(): rarely, sorted, each page once. Returns the new facts merged meanwhile (0 when none was)."""
        t = _NS()
        AGENT["waiting"] = "writing to the disk"        # a long write is progress, not a stall (the supervisor reads this)
        slot = self.wslots.take() if self.wslots else None
        try:
            t1 = _NS(); self.walls = {"sorted": _WALL()}
            new_est = self._new_estimate(rows)                        # before the append: is the sample already held?
            self.db.executemany("INSERT INTO stage(fp, s, p, o, part, row) VALUES(?,?,?,?,?,?)", rows)
            t2 = _NS(); TR.add("db_insert", t2 - t1, len(rows)); self.walls["inserted"] = _WALL()
            if links:
                self.db.executemany("INSERT INTO stage_links(fp, url) VALUES(?, ?)", links)
            t3 = _NS(); TR.add("db_links", t3 - t2, len(links or ()))
            self.db.execute("UPDATE parts SET rows = ? WHERE id = ?", (rows_done, part_id))
            staged = (self.meta("staged", 0) or 0) + len(rows)
            self.set_meta("staged", staged)
            self.set_meta("staged_new", (self.meta("staged_new", 0) or 0) + new_est)
            self._progress()
            t4 = _NS(); TR.add("db_progress", t4 - t3)
            self.db.commit()                                          # the disk: one sequential WAL append
            TR.add("db_commit", _NS() - t4, 1, len(rows)); self.walls["committed"] = _WALL()
        finally:
            if slot is not None:
                self.wslots.release(slot)
            AGENT["waiting"] = None
            TR.add("write", _NS() - t)
        # 1.35: filing happens AFTER the write slot is given back, in the merge pool, and only when it is this agent's turn —
        # otherwise it keeps staging and tries again with its next batch (no agent ever waits here)
        if staged >= min(STAGE_CAP, max(STAGE_MIN, (self.meta("facts", 0) or 0) // 2)):
            ms = self.mslots.try_take() if self.mslots else None
            if ms is None and self.mslots:
                TR.event("merge_deferred", staged=staged, why="another agent is filing; this one keeps reading and staging")
                return 0
            try:
                AGENT["waiting"] = "filing %s facts into the dataset" % format(staged, ",")
                return self._merge()
            finally:
                AGENT["waiting"] = None
                if self.mslots:
                    self.mslots.release(ms)
        return 0

    NEW_SAMPLE = 1000

    def _new_estimate(self, rows):
        """1.35: about how many of these facts are new — a sample of up to 1,000 of them looked up in the facts already held
        (the fingerprint index: a few page reads each). Shown as 'about N new' so a re-read of facts held already (the
        dump read again after a restart, a dataset harvested before) never inflates the total that then falls when filed."""
        if not rows:
            return 0
        held = self.meta("facts", 0) or 0
        if not held:
            return len(rows)
        step = max(1, len(rows) // self.NEW_SAMPLE)
        sample = [r[0] for r in rows[::step]][:self.NEW_SAMPLE]
        hits = 0
        for i in range(0, len(sample), 500):
            chunk = sample[i:i + 500]
            hits += self.db.execute("SELECT count(*) FROM facts WHERE fp IN (%s)" % ",".join("?" * len(chunk)), chunk).fetchone()[0]
        return int(round(len(rows) * (1 - hits / max(1, len(sample)))))

    def _progress(self):
        """the running total for the rate: facts kept plus facts staged (the stage is counted the moment it is written)"""
        now = time.time()
        self.db.execute("INSERT OR REPLACE INTO progress(at, facts) VALUES(?, ?)",
                        (now, (self.meta("facts", 0) or 0) + (self.meta("staged_new", 0) or 0)))   # 1.35: new facts only
        self.db.execute("DELETE FROM progress WHERE at < ?", (now - 2 * 86400,))

    def merge(self, wait=True):
        """fold every staged fact into the keyed tables (the end of a dataset, before dedupe); returns the new facts.
        wait=False (1.39, the end of a part): only if it is this agent's turn — otherwise nothing is filed now, the staged
        facts stay staged (they are on the disk and counted) and the agent reads its next part. Before, every agent
        stopped at the end of EVERY part and queued to file, one at a time on an external drive: with 16 Wikidata lanes
        15 stood idle at "0 facts a minute" for hours, and each shard was rewritten once per 1 GB file."""
        if not self.db.execute("SELECT 1 FROM stage LIMIT 1").fetchone() and not self.meta("staged", 0):
            return 0
        if not wait and self.mslots:
            slot = self.mslots.try_take()
            if slot is None:
                TR.event("merge_deferred", staged=self.meta("staged", 0), why="end of a part, another agent is filing: this one reads its next part")
                return 0
            try:
                AGENT["waiting"] = "filing %s facts into the dataset" % format(self.meta("staged", 0) or 0, ",")
                return self._merge()
            finally:
                self.mslots.release(slot)
                AGENT["waiting"] = None
        AGENT["waiting"] = "waiting for its turn to file (another dataset is filing)"
        slot = self.mslots.take() if self.mslots else None      # 1.35: the merge pool, not a write slot
        try:
            AGENT["waiting"] = "filing %s facts into the dataset" % format(self.meta("staged", 0) or 0, ",")
            return self._merge()
        finally:
            if slot is not None:
                self.mslots.release(slot)
            AGENT["waiting"] = None

    def _merge(self):
        """one transaction, in fingerprint order so each page of the keyed tables is visited once. Of two staged facts with
        one fingerprint the earlier (lower rowid) is offered first and kept, and a fact the shard already holds is never
        replaced — the shard is exactly what inserting batch by batch made. Parts in the order they were staged."""
        t = _NS()
        new = 0
        self.db.execute("PRAGMA cache_size=-%d" % (MERGE_CACHE_MB * 1024))
        # 1.35.2: a filing reports that it is advancing (SQLite steps), so nothing mistakes a long filing on a big shard
        # for a stall. Before, the engine's 30-minute keep-alive saw no new facts during a filing of hours on a
        # billion-fact drive, restarted the engine, the filing rolled back, began again — and nothing was ever filed.
        def step():
            AGENT["filing"] = AGENT.get("filing", 0) + 1
            return 0
        self.db.set_progress_handler(step, FILING_STEP)
        try:
            new = self._fold()
        finally:
            self.db.set_progress_handler(None, 0)
            self.db.execute("PRAGMA cache_size=-%d" % (CACHE_MB * 1024))
            self.db.execute("PRAGMA shrink_memory")
        TR.add("db_merge", _NS() - t, 1, new)
        return new

    def _fold(self):
        new = 0
        for pid, in self.db.execute("SELECT part FROM stage GROUP BY part ORDER BY min(rowid)").fetchall():
            before = self.db.total_changes
            self.db.execute("INSERT OR IGNORE INTO facts(fp, s, p, o, part, row) SELECT fp, s, p, o, part, row FROM stage "
                            "WHERE part = ? ORDER BY fp, rowid", (pid,))
            n = self.db.total_changes - before
            self.db.execute("UPDATE parts SET facts = facts + ? WHERE id = ?", (n, pid))
            new += n
        self.db.execute("INSERT OR IGNORE INTO links(fp, url) SELECT fp, url FROM stage_links ORDER BY fp, rowid")
        self.db.execute("DELETE FROM stage")
        self.db.execute("DELETE FROM stage_links")
        self.set_meta("facts", (self.meta("facts", 0) or 0) + new)
        self.set_meta("staged", 0)
        self.set_meta("staged_new", 0)
        self._progress()
        self.db.commit()
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
        self.on_c = False
        self._chk_at, self._chk = 0.0, None

    def url_override(self, key, part):
        """tests and mirrors: the setting bulk:url:<dataset>:<part> replaces the publisher's address"""
        return self.commons.setting("bulk:url:%s:%s" % (key, part))

    STOP_CHECK_S = 30               # 1.31.1: the registry, the settings and the free space (all on D:) re-read every 30 s,
                                    # not before every batch: a busy data drive no longer holds every agent up

    def stopped(self):
        if os.path.exists(self.stopfile):
            return "stopped from the Control Panel"
        now = time.time()
        if now - self._chk_at < self.STOP_CHECK_S:
            return self._chk
        self._chk = self._stopped_now()
        self._chk_at = time.time()
        return self._chk

    def _stopped_now(self):
        keep = float(self.commons.setting("bulk:min_free_gb") or MIN_FREE_GB)
        w = work_dir(self.folder) if self.on_c else None
        if w and os.path.isdir(w) and _free(w) / 1e9 < keep:
            return "the internal drive (working copies) is nearly full: %.1f GB free — this dataset moves to the data drive and carries on" % (_free(w) / 1e9)
        free = _free(self.folder) / 1e9
        if free < (1 if self.on_c else keep):         # writing on C:, the data drive only needs room for the log
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
    if getattr(ds, "standalone", False):              # a job with no shard of its own (the one dump download)
        try:
            r = ds.run_alone(run)
            TR.event("run", phase="end", dataset=key, state=r.get("state"), why=str(r.get("why") or "")[:300])
            return r
        finally:
            TR.close()
    t = _NS()
    on_c = run.on_c = pull(commons_folder, key)       # the fast working copy on C: (or D: itself when C: has no room)
    TR.add("work_copy", _NS() - t)
    t = _NS()
    sh = Shard(commons_folder, key, work_path(commons_folder, key) if on_c else None)
    sh.wslots = None if on_c else WriteSlots(commons_folder, write_slots(run.commons))
    sh.mslots = MergeSlots(commons_folder, merge_slots(sh.path if on_c else commons_folder))
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
    total_new, t_start, filtered, written = 0, time.time(), 0, 0
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
                AGENT["rows"] = row_no                  # the supervisor sees the skip moving (it is progress, not a stall)
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
                AGENT["rows"] = row_no
                if not row_no & 0x1FFFF:                # about every 130,000 rows: the meter into a side file (no commit)
                    with qt.timed("progress_mark"):
                        _mark(None, pg, row_no, side)
                if len(buf) >= BATCH:
                    with qt.timed("progress_mark"):
                        _mark(sh, pg, row_no, side)
                    written += len(buf)
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
            written += len(buf)
            new = _batch(sh, pid, buf, row_no, links, pending, bt, key, name)
            total_new += new; log_new += new
            finished = limit is None or row_no < limit
            if finished:                                # 1.39: filed now only if it is this agent's turn, or 20 million wait;
                with qt.timed("merge"):                 # otherwise it reads on (everything is filed at the end of the dataset)
                    new = sh.merge(wait=(sh.meta("staged", 0) or 0) >= STAGE_CAP)
                total_new += new; log_new += new
            TR.event("part", phase="end", dataset=key, part=name, rows=row_no, new=total_new)
            for series, year in state.pop("_filled", set()):
                sh.db.execute("INSERT INTO slots(series, year, filled) VALUES(?, ?, 1) ON CONFLICT(series, year) DO UPDATE SET filled = 1", (series, year))
            if key == "wikidata-series":
                for y in sc.expected_years(name):
                    sh.db.execute("INSERT OR IGNORE INTO slots(series, year, filled) VALUES(?, ?, 0)", (name, y))
            if finished:
                sh.db.execute("UPDATE parts SET done = 1, finished = ? WHERE id = ?", (core.now_iso(), pid))
            sh.db.commit()
            run.log(name, log_from, row_no, row_no - log_from, log_new, time.time() - t0,
                    reason=(ds.why + "; %d facts left out by the Control Panel's filter" % filtered) if filtered else None)
            state.pop("_links", None)
            why = run.stopped()
            if why:
                raise _Stop(why)
        with qt.timed("merge"):                         # 1.39: whatever is still staged is filed before the dataset is done
            sh.merge()
        all_done = all(d for (d,) in sh.db.execute("SELECT done FROM parts"))
        sh.set_meta("state", "done" if all_done else "paused"); sh.set_meta("finished", core.now_iso()); sh.db.commit()
        TR.event("run", phase="end", dataset=key, state="done" if all_done else "paused", new=total_new, filtered=filtered,
                 seconds=round(time.time() - t_start, 2))
        return {"dataset": key, "state": "done" if all_done else "paused", "new": total_new, "filtered": filtered,
                "seconds": round(time.time() - t_start, 1)}
    except _Stop as e:
        sh.set_meta("state", "stopped"); sh.set_meta("error", str(e)); sh.db.commit()
        TR.event("run", phase="end", dataset=key, state="stopped", why=str(e), new=total_new, seconds=round(time.time() - t_start, 2))
        return {"dataset": key, "state": "stopped", "why": str(e), "new": total_new, "written": written}
    except Busy as e:
        sh.set_meta("state", "paused"); sh.set_meta("error", str(e)); sh.db.commit()
        run.log("source busy", 0, 0, 0, 0, time.time() - t_start, "failed", str(e))
        TR.fail("source busy", e, retried=True, dataset=key)
        TR.event("run", phase="end", dataset=key, state="paused", why=str(e), new=total_new, seconds=round(time.time() - t_start, 2))
        return {"dataset": key, "state": "paused", "why": str(e), "new": total_new, "written": written, "retry": True}
    except Exception as e:
        TR.fail("agent", e, dataset=key)
        import http.client
        network = isinstance(e, (urllib.error.URLError, http.client.HTTPException, ConnectionError, TimeoutError)) and \
            getattr(e, "errno", None) not in (28,)                      # ENOSPC (disk full) is not the network
        sh.set_meta("state", "paused" if network else "failed")
        sh.set_meta("error", "%s: %s%s" % (type(e).__name__, str(e)[:300], " — retried automatically" if network else "")); sh.db.commit()
        TR.event("run", phase="end", dataset=key, state="paused" if network else "failed", why=str(e)[:300], new=total_new,
                 seconds=round(time.time() - t_start, 2))
        return {"dataset": key, "state": "paused" if network else "failed", "why": str(e)[:300], "new": total_new, "written": written,
                "retry": network}
    finally:
        TR.flush_stages(dataset=key)
        TR.close()
        sh.db.close()


def _batch(sh, pid, buf, row_no, links, pending, bt, key, part):
    """write one batch, then log its timeline, the stage totals since the last batch and the records followed in it"""
    n_offered = len(buf)
    new = sh.write(pid, buf, row_no, links)
    staged = sh.meta("staged", 0) or 0
    if not TR.on:
        return new
    w = getattr(sh, "walls", {})
    if pending:
        fps = [bytes.fromhex(r["fp"]) for r in pending]
        marks = ",".join("?" * len(pending))
        got = dict(sh.db.execute("SELECT fp, part || ':' || row FROM facts WHERE fp IN (%s)" % marks, fps))
        held = {f for f, in sh.db.execute("SELECT fp FROM stage WHERE fp IN (%s)" % marks, fps)} if staged else set()
        for r in pending:
            r["w"].update(w)
            f = bytes.fromhex(r["fp"])
            here = got.get(f)
            r["outcome"] = ("new" if here == "%d:%d" % (pid, r["row"]) else "duplicate" if here else
                            "staged" if f in held else "missing")
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


class Refused(Exception):
    """Wikidata's records service said no; the caller reads another way"""


class Busy(Exception):
    """the publisher asked us to slow down: the dataset pauses (what is saved stays saved) and resumes on the next run"""


_VERSIONS = {}


def _version(url):
    """the file's version as its publisher states it (Last-Modified), so every fact can be traced to one edition
    (asked once per file per process: many parts share one file)"""
    if not url.startswith("http"):
        if url and url.startswith("file://"):            # the downloaded dump: the publisher's date, kept in ready.json
            try:
                p = os.path.join(os.path.dirname(urllib.request.url2pathname(urllib.parse.urlsplit(url.split("#", 1)[0]).path)), "ready.json")
                with open(p, encoding="utf-8") as f:
                    return json.load(f).get("last_modified") or "local file"
            except (OSError, ValueError):
                pass
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
    if not os.path.isdir(folder):
        return {"dataset": key, "state": "paused", "why": "the data drive is not connected (%s)" % folder, "new": 0, "retry": True}
    try:
        return run_dataset(folder, key, max_rows)
    except Exception as e:                      # never lets one agent's surprise end the whole run: it is retried later
        return {"dataset": key, "state": "paused", "why": "%s: %s" % (type(e).__name__, str(e)[:300]), "new": 0, "retry": True}


# ------------------------------------------------------------------------------------------------ the supervisor (1.30)
# Every dataset is its own watched process. The supervisor restarts what ends, ends what stalls, re-routes what waits too
# long, and never gives up: the red Stop is the only way to end it.
AGENT = {"rows": 0, "waiting": None, "filing": 0}            # in each agent process: how far it is, and whether it is waiting on purpose
SLOT_MAX_WAIT_S = 600                           # a lane waiting longer than this for a download connection gives its place up
FILING_STEP = 200000                            # SQLite steps between two "still filing" ticks
STALL_S = 900                                   # no progress for this long (and not waiting on purpose): ended and restarted
SILENT_S = 180                                  # no sign of life for this long: ended and restarted
BACKOFF_S = (60, 120, 300, 600, 900)          # waits before the next try after the 1st, 2nd, ... failure in a row
DRIVE_RETRY_S = 60                              # the data drive unplugged: looked for every minute
RECHECK_DONE_S = 24 * 3600                      # a finished dataset is looked at again daily (new editions of the files)
SUPERVISE_TICK_S = 2


def _agent_alive_info(commons_folder, key):
    """the agent's own heartbeat (what it is doing right now), or None"""
    try:
        with open(os.path.join(commons_folder, FOLDER, "_agents", key + ".json")) as f:
            a = json.load(f)
        return a if time.time() - (a.get("at") or 0) < 120 else None
    except (OSError, ValueError):
        return None


def _alive_dir(commons_folder):
    d = os.path.join(commons_folder, FOLDER, "_agents")
    os.makedirs(d, exist_ok=True)
    return d


def _agent_main(commons_folder, key, max_rows, result_path):
    """one agent process: a heartbeat thread, the dataset, its result in a file"""
    import threading
    alive = os.path.join(_alive_dir(commons_folder), key + ".json")
    done = threading.Event()

    def heartbeat():
        while not done.wait(15):
            try:
                with open(alive + ".tmp", "w") as f:
                    json.dump({"at": time.time(), "pid": os.getpid(), "meter": METER.done, "rows": AGENT["rows"],
                               "waiting": AGENT["waiting"], "filing": AGENT.get("filing", 0)}, f)
                _replace(alive + ".tmp", alive, tries=5)
            except OSError:
                pass
    threading.Thread(target=heartbeat, daemon=True).start()
    if os.name == "nt":                         # keep the computer awake while agents work, windows open or not
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
        except Exception:
            pass
    r = _agent((commons_folder, key, max_rows))
    done.set()
    with open(result_path + ".tmp", "w") as f:
        json.dump(r, f)
    os.replace(result_path + ".tmp", result_path)


HOT_WAIT_S = 30 * 60               # the hot list making no progress this long: the other datasets may run meanwhile
HOT_RETRY_S = 120                  # a hot set that was refused or interrupted is tried again this soon


def hot_first(key):
    """the sets everything else waits for: the icons, what people read, the hot lattices (not the demand agent, which is
    always on, and not the complete domains — millions of records over days — which run after, beside the rest)"""
    return key.startswith("hot-") and key not in ("hot-demand", "hot-circle") and not key.startswith("hot-all-")


def next_try(r, fails):
    """seconds until a dataset is started again, from how it ended (None: not again in this run)"""
    st = (r or {}).get("state")
    if (r or {}).get("dataset") == "hot-demand" and st in ("done", "paused"):
        return 120                               # 1.40: the demand agent looks at its queue every two minutes
    if (r or {}).get("dataset") == "hot-circle" and st in ("done", "paused"):
        return CIRCLE_AGAIN_S                    # 1.46: the net has no end: the next wave is listed five minutes after the last
    if st == "done":
        return RECHECK_DONE_S
    if st == "stopped" and "Control Panel" in str(r.get("why") or ""):
        return None                              # the red Stop
    if st == "blocked":
        return 3600                              # not approved in the registry: looked at again hourly
    if "not connected" in str(r.get("why") or ""):
        return DRIVE_RETRY_S
    if WAITING in str(r.get("why") or ""):
        return 120                               # a lane waiting for the dump download: looks again in 2 minutes
    return BACKOFF_S[min(fails, len(BACKOFF_S) - 1)]


class Supervisor:
    def __init__(self, commons_folder, keys, agents, max_rows=None, mp=None, kill=None):
        import multiprocessing
        self.cf, self.keys, self.agents, self.max_rows = commons_folder, list(keys), max(1, int(agents)), max_rows
        self.mp = mp or multiprocessing.get_context("spawn")
        self.kill = kill or _kill
        self.queue = {k: 0.0 for k in self.keys}            # dataset → when it may start
        self.fails = {k: 0 for k in self.keys}
        self.running = {}                                    # dataset → {proc, started, result, last progress, last change}
        self.events = []
        self.hold = set()                                    # 1.38: datasets having facts added back from another copy right now
        self.hot_done = set()                                # 1.44: hot sets finished in this run
        self.hot_moved, self.hot_bump = None, False          # …and when one of them last made progress (the supervisor's clock)
        self.hot_state = {}
        self.res_dir = os.path.join(commons_folder, FOLDER, "_results")
        os.makedirs(self.res_dir, exist_ok=True)

    def farmed(self, now=None):
        """dataset → machine for every active farm-out assignment, read again at most once a minute"""
        now = now or time.time()
        if now - getattr(self, "_farm_at", 0) > 60:
            self._farm_at = now
            try:
                import qbfarm
                self._farm = qbfarm.farmed_out(self.cf)
            except Exception:
                self._farm = getattr(self, "_farm", {})
        return getattr(self, "_farm", {})

    def note(self, what, key, **kw):
        e = dict(kw, what=what, dataset=key, at=time.time())
        self.events.append(e)
        self.events = self.events[-300:]
        TR.event("supervisor", **e)

    def launch(self, key):
        rp = os.path.join(self.res_dir, key + ".json")
        for p in (rp, os.path.join(_alive_dir(self.cf), key + ".json")):
            if os.path.exists(p):
                os.remove(p)
        pr = self.mp.Process(target=_agent_main, args=(self.cf, key, self.max_rows, rp), daemon=False)
        pr.start()
        self.running[key] = {"proc": pr, "started": time.time(), "result": rp, "progress": None, "changed": time.time()}
        self.note("started", key, pid=pr.pid, attempt=self.fails[key] + 1)

    def _finish(self, key, r, how):
        info = self.running.pop(key)
        if r is None:
            r = {"dataset": key, "state": "paused", "why": how}
        r.setdefault("dataset", key)
        ok = r.get("state") in ("done",)
        self.fails[key] = 0 if ok or r.get("new") or r.get("written") else self.fails[key] + 1   # staged facts are progress too
        wait = next_try(r, max(0, self.fails[key] - 1))
        if hot_first(key):                               # 1.44: the hot list
            if ok:
                self.hot_done.add(key)
            elif wait is not None:
                wait = min(wait, HOT_RETRY_S)            # refused or interrupted: tried again in two minutes, not fifteen
            if ok or r.get("new") or r.get("written"):
                self.hot_bump = True
        if wait is None:
            self.queue.pop(key, None)
        else:
            self.queue[key] = time.time() + wait
        self.note("ended", key, state=r.get("state"), why=str(r.get("why") or how or "")[:200], new=r.get("new"),
                  next_in_s=wait, ran_s=round(time.time() - info["started"]))
        return r

    def check(self, now=None):
        """one look at every agent: collect the ended, end the stalled and the silent, start what may start"""
        now = now or time.time()
        for key in list(self.running):
            info = self.running[key]
            pr = info["proc"]
            if not pr.is_alive():
                try:
                    with open(info["result"]) as f:
                        r = json.load(f)
                except (OSError, ValueError):
                    r = None
                self._finish(key, r, None if r else "the agent ended without a result (exit %s)" % pr.exitcode)
                continue
            try:
                with open(os.path.join(_alive_dir(self.cf), key + ".json")) as f:
                    a = json.load(f)
            except (OSError, ValueError):
                a = None
            if a:
                prog = (a.get("meter"), a.get("rows"), a.get("filing"))      # 1.35.2: a filing advancing is progress
                if prog != info["progress"]:
                    if hot_first(key) and info["progress"] is not None:      # a real step, not a restarted agent's first reading
                        self.hot_moved = now
                    info["progress"], info["changed"], info["waiting_since"] = prog, now, None
                elif a.get("waiting"):                   # waiting on purpose (filing, a connection) is not a stall…
                    info["waiting_since"] = info.get("waiting_since") or now
                    if now - info["waiting_since"] < WAIT_MAX_S:   # …unless it lasts 6 hours without any progress at all
                        info["changed"] = now
            silent = (now - (a or {}).get("at", info["started"])) > SILENT_S
            stalled = (now - info["changed"]) > STALL_S
            if silent or stalled:
                why = ("no sign of life for %d min" % (SILENT_S // 60)) if silent else \
                      ("waiting for %d h without any progress (%s)" % (WAIT_MAX_S // 3600, (a or {}).get("waiting")) if info.get("waiting_since")
                       and now - info["waiting_since"] >= WAIT_MAX_S else "no progress for %d min" % (STALL_S // 60))
                self.kill(pr.pid)
                pr.join(10)
                self._finish(key, None, why + " — ended and restarted where it stopped")
        farmed = self.farmed(now)                    # 1.35: datasets given to another PC (Control Panel → Farm out)
        for key in [k for k in self.running if k in farmed]:
            info = self.running[key]
            self.kill(info["proc"].pid)
            info["proc"].join(10)
            self._finish(key, None, "farmed out to %s — that computer harvests it now (the facts so far are kept)" % farmed[key])
        for key in [k for k in self.running if k in self.hold]:      # 1.38: its own agent steps aside for the merge
            info = self.running[key]
            self.kill(info["proc"].pid)
            info["proc"].join(10)
            self._finish(key, None, "paused while facts are added back to it from another copy — it harvests again right after")
        rested = dict(resting(self.cf, now), **{k: now + 60 for k in self.hold})
        # 1.36: datasets the fail-safe rested (hours without one new fact)
        for key in [k for k in self.running if k in rested and k not in self.hold]:
            info = self.running[key]
            self.kill(info["proc"].pid)
            info["proc"].join(10)
            if key not in self.hold:
                self._finish(key, None, "resting until %s — it ran for hours without one new fact, so other datasets take its place (the facts so far are kept)"
                             % time.strftime("%H:%M", time.localtime(rested[key])))
        # 1.44 — THE HOT LIST FIRST. Until every icons set, the most-read lattice and every hot lattice has finished, nothing
        # else is started: the dump lanes and the other datasets wait (they used to take any slot a hot set left for a
        # moment, and with a billion facts to re-read they then filled the machine while the hot list crawled). One way
        # out: the hot list standing still for 30 minutes (Wikidata refusing every request) — then the others may run, so
        # harvesting never stops altogether, and they step aside again as soon as a hot set moves.
        if self.hot_moved is None or self.hot_bump:
            self.hot_moved, self.hot_bump = now, False
        hot_left = [k for k in self.keys if hot_first(k) and k not in self.hot_done and k not in farmed and k not in rested
                    and (k in self.running or k in self.queue)]
        valve = bool(hot_left) and now - self.hot_moved >= HOT_WAIT_S
        waiting = [k for k in self.queue if not k.startswith("hot-") and k not in self.running]
        self.hot_state = {"left": hot_left, "done": len(self.hot_done), "others_waiting": len(waiting) if hot_left and not valve else 0,
                          "valve": valve, "of": len([k for k in self.keys if hot_first(k)])}
        if hot_left and not valve:                        # the others that were running step aside
            for key in [k for k in self.running if not k.startswith("hot-")]:
                info = self.running[key]
                self.kill(info["proc"].pid)
                info["proc"].join(10)
                self._finish(key, None, "waiting for the hot list (what people ask about is harvested first) — it resumes where it stopped")
        free = self.agents - len(self.running)
        for key in sorted((k for k, t in self.queue.items() if t <= now and k not in self.running and k not in farmed and k not in rested),
                          key=lambda k: self.keys.index(k)):
            if free <= 0:
                break
            if hot_left and not valve and not key.startswith("hot-"):
                continue
            self.launch(key)
            free -= 1

    def stop_all(self, grace=None):
        grace = STOP_GRACE_S if grace is None else grace
        t0 = time.time()
        self.queue = {}
        while self.running and time.time() - t0 < grace:
            self.check()
            self.queue = {}
            time.sleep(1)
        for key, info in list(self.running.items()):
            self.kill(info["proc"].pid)
            self._finish(key, None, "ended by Stop")
        self.queue = {}


def run(commons_folder, keys=None, agents=4, max_rows=None, until=None):
    """the runner: a supervisor that keeps every dataset going (see Supervisor) until the red Stop. Only one at a time.
    until: tests only — a function that ends the run when it returns True."""
    keys = keys or list(catalog())
    folder = os.path.join(commons_folder, FOLDER)
    os.makedirs(folder, exist_ok=True)
    one = Slots(commons_folder)._lock("runner", 0)          # only one engine at a time (released if this process dies)
    if not one:
        return [{"error": "another harvesting engine is already running"}]
    stop = os.path.join(folder, "_runner.stop")
    if os.path.exists(stop):
        os.remove(stop)
    hb = os.path.join(folder, "_runner.json")
    TR.configure(qt.trace_dir(commons_folder), "runner-%d" % os.getpid(), on=True)
    TR.event("run", phase="start", role="runner", agents=agents, datasets=keys, cores=os.cpu_count())
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)   # the computer stays awake while the engine runs
        except Exception:
            pass
    sup = Supervisor(commons_folder, keys, agents, max_rows)

    def beat(note):
        try:
            with open(hb + ".tmp", "w") as f:
                json.dump({"heartbeat": time.time(), "pid": os.getpid(), "version": VERSION, "agents": agents, "datasets": keys,
                           "note": note, "running": sorted(sup.running), "restoring": rnote.get("text") if rnote.get("on") else "", "hot": sup.hot_state, "waiting": {k: round(t - time.time()) for k, t in sup.queue.items()
                                                                                  if k not in sup.running and t > time.time()},
                           "events": sup.events[-60:]}, f)
            _replace(hb + ".tmp", hb)
        except OSError as e:
            TR.fail("heartbeat", e, retried=True)
    import threading
    rnote = {"text": "", "on": False}
    beat("starting")
    # 1.38: facts held in another copy are added back IN THE BACKGROUND, one dataset at a time. Until 1.37 nothing was
    # harvested until every copy of every dataset had been compared and merged — on a store of a billion facts on an
    # external drive that is hours of "0 facts a minute" after every start. Now only the dataset being merged waits
    # (its agent steps aside and returns right after); every other dataset harvests from the first minute.

    def restore_hold(key, on):
        if on:
            sup.hold.add(key)
            t0 = time.time()
            while key in sup.running and time.time() - t0 < 180 and not os.path.exists(stop):
                time.sleep(1)                             # its agent ends after the batch it is writing
        else:
            sup.hold.discard(key)

    def restorer():
        try:
            TR.event("names", indexed=index_names(commons_folder))     # 1.43: part-of-name lookup for records already read
        except Exception as e:
            TR.fail("names", e, retried=True)
        try:
            rnote["on"] = True
            TR.event("restore", result=restore_missing(commons_folder, say=lambda t: rnote.update(text=t),
                                                       halt=lambda: os.path.exists(stop), hold=restore_hold))
        except Exception as e:
            TR.fail("restore", e, retried=True)
        finally:
            rnote.update(on=False, text="")
            sup.hold.clear()
    threading.Thread(target=restorer, daemon=True, name="qb-restore").start()
    drain_stop = threading.Event()

    def drainer():                                    # one copier: working copies on C: → their home on D:, in turn
        wait = min(120, DRAIN_S)
        while not drain_stop.wait(wait):
            t_round = time.time()
            for k in work_keys(commons_folder):
                if drain_stop.is_set():
                    break
                try:
                    drain(commons_folder, k)
                except Exception as e:
                    TR.fail("drain", e, retried=True, dataset=k)
            wait = max(DRAIN_S, 2 * (time.time() - t_round))   # the copier rests twice as long as it worked
    dthread = threading.Thread(target=drainer, daemon=True, name="qb-drain")

    def backer():                                     # 1.33: a checked backup to the backup drive, once a day while harvesting
        import qbvault
        while not drain_stop.wait(600):
            try:
                if qbvault.due(commons_folder) and not qbvault.running(commons_folder):
                    TR.event("backup", result=qbvault.backup(commons_folder, reason="automatic",
                                                             stop=lambda: "Stop pressed" if os.path.exists(stop) else None))
            except Exception as e:
                TR.fail("backup", e, retried=True)
    threading.Thread(target=backer, daemon=True, name="qb-backup").start()
    if work_dir(commons_folder):
        dthread.start()
    last_upkeep = time.time()
    try:
        while not os.path.exists(stop) and not (until and until(sup)):
            try:
                sup.check()
            except Exception as e:                        # the supervisor itself never stops on a surprise
                TR.fail("supervisor", e, retried=True)
            idle = not sup.running
            beat("running: %d agent(s)" % len(sup.running) if sup.running else
                 "waiting: every dataset is finished or waiting for its next try")
            if idle and time.time() - last_upkeep > 3600:    # quiet moments: duplicates across shards, finished copies home
                last_upkeep = time.time()
                try:
                    TR.event("dedupe", removed=dedupe(commons_folder))
                    if work_dir(commons_folder):
                        finish_work(commons_folder, only_changed=True)
                except Exception as e:
                    TR.fail("upkeep", e, retried=True)
            time.sleep(SUPERVISE_TICK_S)
        # 1.31.2 Stop: the agents end after their batch; then only the copies that changed are saved to D: (no duplicate
        # check here — it runs in quiet hours), with a heartbeat every 10 s so the page shows "stopping: saving …" and nothing
        # ends this process halfway through a save
        note = {"text": "stopping: every agent finishes its current batch"}
        hb_stop = threading.Event()

        def stop_beat():
            while not hb_stop.wait(10):
                beat(note["text"])
        beat(note["text"])
        threading.Thread(target=stop_beat, daemon=True, name="qb-stop-beat").start()
        try:
            sup.stop_all()
            drain_stop.set()
            if dthread.is_alive():
                note["text"] = "stopping: the copier finishes the save it is doing"
                dthread.join()

            def say(i, n, k):
                note["text"] = "stopping: saving what changed to the data drive — %s (%d of %d)" % (k, i, n)
                beat(note["text"])
            saved = finish_work(commons_folder, only_changed=True, note=say) if work_dir(commons_folder) else {}
        finally:
            hb_stop.set()
        TR.event("run", phase="end", role="runner", events=sup.events[-50:])
        beat("finished")
        return [{"events": sup.events, "saved_to_data_drive": saved}]
    finally:
        TR.close()
        Slots(commons_folder).release(one)


def dedupe(commons_folder):
    """one fact, one record across every shard: a fingerprint held by an earlier shard (catalog order) is removed from the
    later ones. Within a shard the fingerprint is the key, so a repeat never enters; across shards a repeat can arrive when
    a new edition of a file moves a record between agents (a new weekly Wikidata dump shifts items between lanes).
    The fingerprint includes the area, so only shards of one area can share facts. Runs when every agent has finished."""
    keys = [k for k in catalog() if os.path.exists(shard_path(commons_folder, k))]
    removed = {}
    for k in keys:                                     # 1.33: a stage left by a stopped agent joins its shard first
        sh = Shard(commons_folder, k)
        try:
            sh.merge()
        finally:
            sh.db.close()
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
    try:                                              # 1.35: datasets farmed out to other PCs (shown as such)
        import qbfarm
        _FARMED[commons_folder] = qbfarm.farmed_out(commons_folder)
    except Exception:
        _FARMED[commons_folder] = {}
    for key, ds in catalog().items():
        approved, why = True, ""
        if ds.source and commons is not None:
            approved, cls, why = commons.registry.check(ds.source)
        row = {"key": key, "title": ds.title, "app": ds.app, "area": AREA[ds.app], "source": ds.source or "computed", "licence": ds.licence,
               "why": ds.why, "approx": ds.approx, "approved": approved, "approval": why, "state": "not started", "facts": 0,
               "last_minute": 0, "last_10min": 0, "last_hour": 0, "bytes": 0, "parts": [], "error": None}
        p = shard_path(commons_folder, key)
        if p != home_path(commons_folder, key):
            dr = drained(commons_folder).get(key) or {}
            row["working_copy"] = True
            row["saved_to_data_drive"] = dr.get("at")
        if os.path.exists(p):
            row["bytes"] = sum(os.path.getsize(p + x) for x in ("", "-wal") if os.path.exists(p + x))
            try:
                db = _ro(p)
                meta = {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM meta")}
                row.update(state=meta.get("state", "not started"), facts=meta.get("facts", 0) or 0, error=meta.get("error"),
                           staged=meta.get("staged", 0) or 0,
                           staged_new=meta.get("staged_new", meta.get("staged", 0)) or 0)   # 1.35: about this many of them are new
                pgm = meta.get("progress")
                try:                                    # the side file is newer between batches
                    with open(p + ".progress") as f:
                        pgs = json.load(f)
                    if not pgm or (pgs.get("at") or 0) > (pgm.get("at") or 0):
                        pgm = pgs
                except (OSError, ValueError):
                    pass
                row["progress"] = _progress(pgm, now, live=row["state"] == "running")
                last = db.execute("SELECT facts FROM progress ORDER BY at DESC LIMIT 1").fetchone()
                cur = last[0] if last else row["facts"]          # facts kept + staged, as the progress table counts them
                for secs, k in ((60, "last_minute"), (600, "last_10min"), (3600, "last_hour")):
                    r = db.execute("SELECT facts FROM progress WHERE at <= ? ORDER BY at DESC LIMIT 1", (now - secs,)).fetchone()
                    first = db.execute("SELECT min(at) FROM progress").fetchone()[0]
                    base = r[0] if r else (0 if first is None or first > now - secs else cur)
                    row[k] = max(0, cur - base)
                row["parts"] = [dict(zip(("name", "rows", "facts", "done", "version", "finished"), r))
                                for r in db.execute("SELECT name, rows, facts, done, version, finished FROM parts ORDER BY id")]
                pg = row["progress"]
                if pg:                                  # overall: every finished part counts, plus the share of the current one
                    ed = pg["part"].split(" part ")[0] + " part " if " part " in (pg.get("part") or "") else ""
                    others = sum(1 for x in row["parts"] if x["done"] and x["name"] != pg["part"] and x["name"].startswith(ed))
                    pg["overall"] = 1.0 if row["state"] == "done" else round(min(1.0, (others + (pg["fraction"] or 0)) / max(1, pg["parts"])), 4)
                if key == "wikidata-series":
                    row["slots"] = [dict(zip(("series", "expected", "filled"), r)) for r in
                                    db.execute("SELECT series, count(*), sum(filled) FROM slots GROUP BY series ORDER BY series")]
                db.close()
            except sqlite3.Error as e:
                row["error"] = None if "locked" in str(e) else "shard unreadable: %s" % e
                row["busy"] = "locked" in str(e)
                last = _LAST_COUNT.get((commons_folder, key)) or _saved_counts(commons_folder).get(key)
                if last:                                # busy for a moment (being copied, being written): the last count
                    row["facts"], row["count_from"] = last, "last known (the file is busy right now)"
            if row["state"] == "running" and not _alive(commons_folder):
                row["state"] = "paused"
        rn = restoring_now(commons_folder)
        if rn and rn.get("key") == key and (rn.get("facts") or 0) > row["facts"]:
            row["facts"], row["count_from"] = rn["facts"], "restoring: facts are being added back from %s" % rn.get("from")
            row["restoring"] = rn
        if getattr(ds, "standalone", False):          # the one dump download: its own progress, no shard
            row.update(download_status(commons_folder, commons))
        if row["facts"] and not row.get("count_from"):
            _LAST_COUNT[(commons_folder, key)] = row["facts"]
        # gathered = filed + the NEW facts among those staged (1.35: estimated from a sample of each batch). Staged facts
        # are filed only at the end of a part or every 5-20 million, so filed alone stands still for long stretches; but
        # adding every staged fact (1.34.1) counted facts the store already holds, and the total then FELL when they were
        # filed and skipped — a re-read of the dump on a store of a billion showed 1,004 M, then 1,001 M. Never again:
        # gathered only counts facts that will be kept.
        row["gathered"] = (row["facts"] or 0) + min(row.get("staged_new") or 0, row.get("staged") or 0)
        fo = _FARMED.get(commons_folder, {}).get(key)
        if fo:
            row["farmed_out"] = fo                         # given to another PC: this server does not harvest it
        # 1.35: a dataset changing hands (its agent paused and restarted, its working copy moving between C: and D:) can
        # be unreadable or absent for a moment; it then read as "not started", 0 facts, and the total dipped by millions
        # for one look (Windows, 25-minute test: 56.3 M -> 52.8 M -> 57.8 M). The facts were never gone: show the last
        # count read, and say why, instead of zero.
        lk = (commons_folder, key)
        prev_g = _LAST_GATHERED.get(lk)
        unreadable = row.get("busy") or (row["state"] == "not started" and not os.path.exists(p))
        if prev_g and (unreadable or row["gathered"] < prev_g["gathered"] and not row["facts"] and not row.get("staged")):
            for f_ in ("facts", "staged", "staged_new", "gathered"):
                row[f_] = prev_g.get(f_, row.get(f_))
            row["count_from"] = row.get("count_from") or "last known — the dataset is changing hands (paused, restarting or being moved), its facts are kept"
        else:
            # 1.35.1: the "new" figure is a sample of 1,000 per batch, so a batch with a few duplicates in it (0.2 % —
            # Windows test: 5,000,031 staged, 4,990,136 kept) reads as all new, and the total then fell by those few
            # thousand when the batch was filed. Hold the total where it was until new facts pass it (seconds at
            # harvest speed) and count the difference as already held, rather than show a fall.
            fl = _FLOOR.get(lk)
            if prev_g and not fl and row["facts"] > (prev_g.get("facts") or 0) and row["gathered"] < prev_g["gathered"]:
                fl = _FLOOR[lk] = {"gathered": prev_g["gathered"], "facts": row["facts"]}
                _HELD_AT_FILING[lk] = _HELD_AT_FILING.get(lk, 0) + prev_g["gathered"] - row["gathered"]
            if fl:
                if row["gathered"] >= fl["gathered"] or row["facts"] < fl["facts"]:
                    _FLOOR.pop(lk, None)                  # passed it (or a real fall, which the drops ledger explains)
                else:
                    row["gathered"] = fl["gathered"]
            if row["gathered"]:
                _LAST_GATHERED[lk] = {f_: row.get(f_) for f_ in ("facts", "staged", "staged_new", "gathered")}
        al = _agent_alive_info(commons_folder, key)
        if al and al.get("waiting") and row["state"] == "running":
            row["doing"] = al["waiting"]                   # "filing 20,000,000 facts into the dataset", "a download connection"…
        if key.startswith("hot-") and row.get("parts"):   # a lattice has a thousand small parts: the page gets the count and the last few
            ps = row["parts"]
            row["parts_done"], row["parts_total"] = sum(1 for x in ps if x.get("done")), len(ps)
            row["parts"] = [x for x in ps if not x.get("done")][:2] + [x for x in ps if x.get("done")][-2:]
        out.append(row)
    _count_ledger(commons_folder, out, now)
    _save_counts(commons_folder, out)
    rs = {}
    try:
        with open(os.path.join(folder, "_runner.json")) as f:
            rs = json.load(f)
    except (OSError, ValueError):
        pass
    rs["alive"] = _runner_alive(rs, now)
    w = work_dir(commons_folder)
    try:
        free_c = shutil.disk_usage(w if os.path.isdir(w) else os.path.dirname(w) if os.path.isdir(os.path.dirname(w)) else os.path.expanduser("~")).free if w else None
    except OSError:
        free_c = None
    return {"version": VERSION, "cores": os.cpu_count() or 1, "max_agents": MAX_AGENTS, "datasets": out, "runner": rs, "total": sum(d["facts"] for d in out),
            "total_gathered": sum(d["gathered"] for d in out), "staged": sum(d.get("staged") or 0 for d in out),
            "copying": copying(commons_folder), "working_copies": bool(w), "work_folder": w, "work_free_bytes": free_c, "engine_version": VERSION,
            "last_minute": sum(d["last_minute"] for d in out), "last_hour": sum(d["last_hour"] for d in out),
            "last_10min": sum(d["last_10min"] for d in out), "facts_per_min": round(sum(d["last_10min"] for d in out) / 10),
            "drops": count_drops(commons_folder, now - 7200),
            "keepalive": keepalive_info(commons_folder),
            "watchdog": watchdog_info(commons_folder, rs.get("alive"), now),
            "on_data_drive": sum(((_meta_of(home_path(commons_folder, d["key"])) or {}).get("facts") or 0)
                                 for d in out if os.path.exists(home_path(commons_folder, d["key"]))),
            "already_held_at_filing": sum(v for (cf, _k), v in _HELD_AT_FILING.items() if cf == commons_folder),
            "duplicates_removed": sum((_LAST_DUPS.get((commons_folder, d["key"])) or 0) for d in out),
            "bytes": sum(d["bytes"] for d in out), "download": download_status(commons_folder, commons)["download"]}


def save_download_settings(commons, folder=None, on=None, passphrase=None):
    """the admin chooses where the dump is kept (a folder on any drive: it is created) and whether the lanes read it"""
    commons.approvals._require(passphrase or "")
    if folder is not None:
        folder = str(folder).strip().strip('"')
        if folder:
            if not os.path.isabs(os.path.expanduser(folder)):
                raise ValueError("Give the whole folder, with its drive — e.g. E:\\QB-dumps")
            drive = os.path.splitdrive(os.path.abspath(os.path.expanduser(folder)))[0] or os.sep
            if not os.path.exists(drive + os.sep if drive != os.sep else os.sep):
                raise ValueError("The drive %s is not connected." % drive)
            os.makedirs(os.path.expanduser(folder), exist_ok=True)
        commons.set_setting("bulk:dumps:folder", folder)
    if on is not None:
        commons.set_setting("bulk:wikidata:local", "on" if on in (True, "on", "true", 1, "1") else "off")
    return download_status(commons.folder, commons)["download"]


def download_status(commons_folder, commons=None):
    """the one dump download for the page: where, what is ready, what is under way (with speed and time left)"""
    on = local_mode(commons) if commons is not None else True
    d = dumps_folder(commons_folder, commons)
    r, pg = dumps_ready(commons_folder, commons), qbdump.progress(d)
    try:
        free = shutil.disk_usage(d if os.path.isdir(d) else commons_folder).free
    except OSError:
        free = None
    try:
        with open(os.path.join(commons_folder, FOLDER, "_download_last.json")) as f:
            last = json.load(f)
    except (OSError, ValueError):
        last = None
    state = ("not used" if not on else "running" if pg and _alive(commons_folder) else "paused" if pg else "done" if r else
             (last.get("state") or "not started") if last else "not started")
    out = {"on": on, "folder": d, "folder_setting": (commons.setting("bulk:dumps:folder") or "") if commons is not None else "", "free_bytes": free, "ready": {k: r.get(k) for k in ("edition", "size", "checked", "seconds", "finished", "md5")} if r else None,
           "under_way": pg, "state": state, "last_try": last}
    if pg:
        out["progress"] = {"part": "download %s" % pg.get("edition"), "fraction": pg["share"], "overall": pg["share"], "parts": 1,
                           "eta_s": pg.get("eta_s"), "rate": pg.get("rate_mb_s")}
    return {"download": out, "state": state if on else "done"}


_LAST_COUNT = {}
_LAST_GATHERED = {}
_FLOOR = {}                  # 1.35.1: the total held while a just-filed batch's few duplicates are overtaken
_HELD_AT_FILING = {}
_FARMED = {}                # 1.35: the last full count of each dataset, shown while it changes hands
_LAST_DUPS = {}
_SAVED = {}


def _counts_path(commons_folder):
    return os.path.join(commons_folder, FOLDER, "_counts.json")


def _saved_counts(commons_folder):
    """the last good count of every dataset, kept on disk (1.31.2): a file busy at the moment the page restarts is shown with
    it, never as 0"""
    if commons_folder not in _SAVED:
        try:
            with open(_counts_path(commons_folder)) as f:
                _SAVED[commons_folder] = json.load(f)
        except (OSError, ValueError):
            _SAVED[commons_folder] = {}
    return _SAVED[commons_folder]


def _save_counts(commons_folder, rows):
    saved = _saved_counts(commons_folder)
    new = {r["key"]: r["facts"] for r in rows if r["facts"] and not r.get("count_from")}
    if new and any(saved.get(k) != v for k, v in new.items()):
        saved.update(new)
        try:
            with open(_counts_path(commons_folder) + ".tmp", "w") as f:
                json.dump(saved, f)
            _replace(_counts_path(commons_folder) + ".tmp", _counts_path(commons_folder), tries=5)
        except OSError:
            pass
_LEDGER = {}


def _ledger_path(commons_folder):
    return os.path.join(commons_folder, FOLDER, "_count-drops.jsonl")


def _count_ledger(commons_folder, rows, now):
    """every fall in a dataset's count, written down with its cause: duplicates removed (the same fact held by an earlier
    dataset), the working copy swapped, or unexplained — so a lower total is never a mystery"""
    prev = _LEDGER.get(commons_folder)
    cur = {}
    for r in rows:
        p = shard_path(commons_folder, r["key"])
        dups = None
        if os.path.exists(p) and not r.get("count_from"):
            dups = (_meta_of(p) or {}).get("duplicates_removed") or 0
        cur[r["key"]] = (r["facts"], dups, p)
        if dups is not None:
            _LAST_DUPS[(commons_folder, r["key"])] = dups
    _LEDGER[commons_folder] = cur
    if not prev:
        return
    for k, (f, dups, p) in cur.items():
        if k not in prev or f >= prev[k][0]:
            continue
        pf, pdups, pp = prev[k]
        fell = pf - f
        dd = (dups or 0) - (pdups or 0) if dups is not None and pdups is not None else 0
        cause = ("duplicates removed: the same facts are held by an earlier dataset (one copy is kept)" if dd >= fell * 0.95 else
                 "the working copy and the data-drive copy were swapped (%s → %s)" % (pp, p) if p != pp else
                 "unexplained — please send the health report")
        try:
            with open(_ledger_path(commons_folder), "a") as fh:
                fh.write(json.dumps({"at": now, "dataset": k, "from": pf, "to": f, "fell": fell, "duplicates": dd, "cause": cause}) + "\n")
        except OSError:
            pass
        TR.event("count_drop", dataset=k, before=pf, after=f, duplicates=dd, cause=cause)


def count_drops(commons_folder, since=0):
    out = []
    try:
        with open(_ledger_path(commons_folder)) as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("at", 0) >= since:
                    out.append(e)
    except OSError:
        pass
    return out


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


def hot_line(rs):
    """the hot list in a sentence, from the runner's heartbeat"""
    h = rs.get("hot") or {}
    if not h.get("left"):
        return " The hot list (icons, most-read, lattices) is complete; everything else is harvesting." if h.get("of") and h.get("done") else ""
    if h.get("valve"):
        return (" Hot list: %d of %d sets done, but it has not moved for 30 minutes (Wikidata is refusing requests), so the other datasets run "
                "meanwhile and step aside when it moves again." % (h.get("done") or 0, h.get("of") or 0))
    return " Hot list first: %d of %d sets done, %d running or due; the other %d datasets wait until it is finished." % (
        h.get("done") or 0, h.get("of") or 0, len(h["left"]), h.get("others_waiting") or 0)


def headline(st):
    """the harvest in one sentence: what it is doing, how fast (the last 10 minutes), and the main reason when it is slow"""
    rs = st.get("runner") or {}
    if st.get("copying"):
        c = st["copying"]
        return {"state": "copying", "text": "Getting ready: copying %s to C: (%d%%) before it resumes there." % (
            c["dataset"], 100 * c["done"] / max(1, c["total"]))}
    wd = st.get("watchdog") or {}
    if not rs.get("alive"):
        if wd.get("want") == "on":
            return {"state": "starting", "text": "Harvesting is switched on and the engine is not running — QueryBook is starting it again by itself (within 3 minutes)."}
        return {"state": "stopped", "text": "Stopped. Press ⚡ Start harvesting."}
    if rs.get("version") != VERSION:
        return {"state": "old", "text": "An older harvesting engine is running. Press ■ Stop harvesting, then ⚡ Start harvesting."}
    fpm = st.get("facts_per_min") or 0
    if wd.get("state") == "preparing" and wd.get("text"):
        return {"state": "preparing", "text": wd["text"]}
    if not fpm and wd.get("text") and (wd.get("dry_s") or 0) >= 600:
        run_ = [d for d in st["datasets"] if d.get("state") == "running"]
        busy_ = "; ".join("%s (%s)" % (d["key"], d.get("doing") or "reading") for d in run_[:4])
        return {"state": wd.get("state") or "dry", "text": wd["text"] + hot_line(rs) + ((" Busy now: %s%s." % (busy_, " and %d more" % (len(run_) - 4) if len(run_) > 4 else "")) if busy_ else "")
                + ((" In the background: %s." % rs["restoring"]) if rs.get("restoring") else "")}
    direct = [d["key"] for d in st["datasets"] if d["state"] == "running" and not d.get("working_copy") and st.get("working_copies")]
    why = ""
    filing = [d for d in st["datasets"] if str(d.get("doing") or "").startswith("filing")]
    if filing:                                        # 1.35: say so — the rate dips while staged facts are filed, nothing stopped
        why = " Filing now: %s." % "; ".join("%s (%s)" % (d["key"], d["doing"].replace(" into the dataset", "")) for d in filing[:3])
    if direct:
        why += " Slow because %d dataset(s) write straight to D: (no room on C:)." % len(direct)
    elif fpm < 1_000_000:
        running = [d for d in st["datasets"] if d["state"] == "running"]
        idle = [d for d in running if not d["last_10min"]]
        if running and len(idle) > len(running) / 2:
            why += " %d of %d running datasets added nothing in 10 minutes — most are waiting for a download connection " \
                  "(the servers allow only a few at a time) or still finishing their first batch." % (len(idle), len(running))
    if rs.get("restoring"):
        why += " In the background: %s (that one dataset waits; the others harvest)." % rs["restoring"]
    why = hot_line(rs) + why
    return {"state": "harvesting", "text": "Harvesting: %s facts a minute (last 10 minutes).%s" % (format(fpm, ","), why)}


def _progress(pg, now, live=False):
    """the saved meter → part and overall fraction, rate and time left (None when nothing is measured yet). live (the agent
    is running): the rate is measured up to now, not up to the last mark, so an agent that has stopped moving shows its
    speed falling instead of the speed it last had (1.33: lanes stuck for an hour still read "10 MB/s")"""
    if not pg:
        return None
    total, done = pg.get("total") or 0, pg.get("done") or 0
    frac = min(1.0, done / total) if total else None
    end = max(now, pg.get("at") or now) if live else (pg.get("at") or now)
    secs = max(0.001, end - (pg.get("since") or now))
    rate = max(0, done - (pg.get("done_at_start") or 0)) / secs if secs > 1 else None
    eta = (total - done) / rate if rate and total and done < total else None
    parts = pg.get("parts") or 1
    overall = ((pg.get("part_no", 1) - 1) + (frac or 0)) / parts
    return dict(pg, fraction=frac, overall=round(overall, 4), rate=rate, eta_s=round(eta) if eta else None)


HB_BUSY_S = 15 * 60                # 1.37: a runner whose process is there is alive, even when its heartbeat is this late


def _runner_alive(rs, now=None):
    """1.37: the heartbeat file lives on the data drive, and a drive busy with a large merge or copy can hold a small write
    back for minutes. The engine was then taken for dead: a second one was started on top of it, and after 5 minutes the
    working one was ENDED — in the middle of its work, which began again from the start. Now: a fresh heartbeat, or a
    process that is still there with a heartbeat less than 15 minutes old."""
    if not rs or rs.get("note") == "finished":
        return False
    age = (now or time.time()) - (rs.get("heartbeat") or 0)
    return age < 30 or (age < HB_BUSY_S and _pid_alive(rs.get("pid")))


def _alive(commons_folder):
    try:
        with open(os.path.join(commons_folder, FOLDER, "_runner.json")) as f:
            rs = json.load(f)
        return _runner_alive(rs)
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


def stores(commons_folder):
    """the dataset stores (shards) that exist, in catalogue order: [(key, dataset)]"""
    return [(k, ds) for k, ds in catalog().items() if os.path.exists(shard_path(commons_folder, k))]


def search_store(commons_folder, key, ds, text, limit):
    """facts whose subject starts with `text` (exact case first, then capitalised) in ONE store"""
    out = []
    db = _ro(shard_path(commons_folder, key))
    try:
        for t in dict.fromkeys((text, text[:1].upper() + text[1:])):
            if len(out) >= limit:
                break
            for s, pr, o, part, row in db.execute(
                    "SELECT f.s, pr.name, f.o, pa.name, f.row FROM facts f JOIN predicates pr ON pr.id = f.p JOIN parts pa ON pa.id = f.part "
                    "WHERE f.s >= ? AND f.s < ? LIMIT ?", (t, t + "\uffff", limit - len(out))):
                out.append({"subject": s, "predicate": pr, "object": o, "dataset": ds.title, "source": ds.source or "computed",
                            "licence": ds.licence, "provenance": "%s, row %d" % (part, row + 1), "link": ds.link(s), "status": "computed" if not ds.source else "sourced"})
    finally:
        db.close()
    return out


def label_wikidata(commons_folder, out):
    """Wikidata item numbers in the values shown with their labels"""
    qs = [int(m) for r in out if r["source"] == "wikidata" for m in QID.findall(r["object"])]
    if qs:
        lab = wd_labels(commons_folder, qs)
        for r in out:
            if r["source"] == "wikidata":
                r["object"] = QID.sub(lambda m: "%s (Q%s)" % (lab[int(m.group(1))], m.group(1)) if int(m.group(1)) in lab else m.group(0), r["object"])
    return out


def search_central(commons_folder, text, limit=50):
    """the central lookup: every store in turn until `limit` facts are found — (facts, stores asked, stores held)"""
    out, asked = [], 0
    text = (text or "").strip()
    held = stores(commons_folder)
    if not text:
        return out, 0, len(held)
    for key, ds in held:
        if len(out) >= limit:
            break
        asked += 1
        out += search_store(commons_folder, key, ds, text, limit - len(out))
    return out[:limit], asked, len(held)


def search(commons_folder, text, limit=50):
    """facts whose subject starts with `text` (exact case first, then capitalised), across every shard"""
    return label_wikidata(commons_folder, search_central(commons_folder, text, limit)[0])[:limit]


# ------------------------------------------------------------------------------------------------ control (the Control Panel)
def start(commons, keys, agents, passphrase, program_dir):
    """start the bulk runner (admin): a separate program, so the applications stay responsive"""
    import subprocess
    commons.approvals._require(passphrase or "")
    if stopping(commons.folder):
        raise ValueError("The last Stop is still saving to the data drive — press Start again in a minute (⚡ Start harvesting waits by itself).")
    if _alive(commons.folder):
        if runner_version(commons.folder) != VERSION:
            r = full_speed(commons, program_dir, "Start")
            return {"summary": r.get("summary") or "replacing an older engine", **status(commons.folder, commons)}
        return {"summary": "bulk harvesting is already running", **status_cached(commons.folder, commons)}
    keys = [k for k in (keys or list(catalog())) if k in catalog()]
    if not keys:
        raise ValueError("Choose at least one dataset.")
    import qbcontrol as ctl, qbkeystone as ks
    keys = ks.order(keys, commons.folder, commons, ctl.get(commons, "target"))   # the admin's target, then keystone priority
    agents = MAX_AGENTS if not agents or int(agents) <= 0 else max(1, min(int(agents), MAX_AGENTS))   # 0 = full speed
    _launch(commons.folder, keys, agents, program_dir)
    with commons.store.write() as db:
        commons.agent_log(db, "engine", "Bulk harvesting started: %s (%d agents)" % (", ".join(keys), agents))
    return {"summary": "bulk harvesting is starting: %d dataset(s), %d agent(s)" % (len(keys), agents), **status_cached(commons.folder, commons)}


def _launch(commons_folder, keys, agents, program_dir):
    import subprocess
    path = os.path.join(program_dir, "qbbulk.py")
    kw = {"creationflags": 0x08000000 | 0x00000200} if os.name == "nt" else {"start_new_session": True}
    subprocess.Popen([sys.executable, path, "run", "--commons", commons_folder, "--datasets", ",".join(keys), "--agents", str(agents)],
                     cwd=program_dir, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)


def full_speed(commons, program_dir, why="Start all harvesting", launch=None):
    """the master switch's own start: every approved dataset, one agent per core (as the Control Panel's ⚡ Full speed) —
    the path that brings in tens of millions of facts. Nothing to do when the agents already run."""
    set_intent(commons.folder, True, why)              # 1.36: harvesting is wanted from now until someone presses Stop
    if stopping(commons.folder):                       # 1.31.2: the stop finishes saving first, then this start runs
        import threading

        def after_stop():
            t0 = time.time()
            while stopping(commons.folder) and time.time() - t0 < STOP_SAVE_S:
                time.sleep(5)
            full_speed(commons, program_dir, why + " (after the stop finished saving)", launch)
        threading.Thread(target=after_stop, daemon=True, name="qb-start-after-stop").start()
        return {"bulk": "starting after the stop", "summary": "the last stop is still saving to the data drive; harvesting starts "
                                                             "by itself as soon as that is done"}
    if _alive(commons.folder):
        if runner_version(commons.folder) == VERSION:
            return {"bulk": "already running"}
        # an engine from an older version is still running (it has no window): stop it, then start this one
        import threading
        stop(commons, grace=60, auto=True)

        def later():
            t0 = time.time()
            while (_alive(commons.folder) or _pids(commons.folder)) and time.time() - t0 < 180:
                time.sleep(2)
            full_speed(commons, program_dir, why + " (replacing an older engine)", launch)
        threading.Thread(target=later, daemon=True, name="qb-replace").start()
        return {"bulk": "replacing an older engine", "summary": "an older harvesting engine was still running: it is stopped and this version starts in about a minute"}
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


RESUME_GAP_S = 180                 # at most one automatic restart every 3 minutes


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
    if _pid_alive(rs.get("pid")) and now - rs.get("heartbeat", now) < HB_BUSY_S:
        return None                               # 1.37: its process is there — busy (a slow drive), not crashed
    if now - rs.get("heartbeat", now) >= HB_BUSY_S and rs.get("pid"):
        _kill(int(rs["pid"]))                     # hung for 15 minutes: its lock would keep a new engine out
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


KEEPALIVE_STALL_S = 30 * 60        # 1.35: harvesting "on", agents running, and nothing moved (no fact, no byte) this long: restart
KEEPALIVE_NAME = "_keepalive.json"
# 1.36 — the fail-safe judges by OUTCOME. Agents can read bytes and check rows for hours and add nothing (1.35 saw that as
# "moving" and never acted). No NEW fact for this long while datasets run: 1 a clean restart, 2 a hard restart (every
# process ended, stale marks cleared), 3 the datasets that add nothing are rested so the others take their place.
NOFACT_S = (60 * 60, 120 * 60, 180 * 60)
REST_S = 6 * 3600                  # how long a dataset that adds nothing is rested
DRY_DATASET_S = 45 * 60            # 1.37: ONE dataset reading (rows moving) this long without one new fact is rested — that is
#                                    the drive churning for nothing: records the store already holds, read and thrown away
ALERT_DRY_S = 20 * 60              # 1.37: no new fact this long while harvesting runs: the person is told (page, alert, window)
BUSY_GRACE_S = 20 * 60             # a filing (or the one download, when lanes wait for it) that advanced this recently is real work
WORK_MAX_S = 4 * 3600              # …but not for ever: 4 hours without one new fact and the ladder runs whatever is "busy"
ENSURE_WAIT_S = 120                # switched on and no engine for this long: started again
INTENT_NAME, REST_NAME = "_intent.json", "_rest.json"


def _read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def intent(commons_folder):
    """what the person wants: {"want": "on" | "off" | None, "at", "by"} — on from Start until Stop, across restarts,
    crashes, updates and reboots. Before 1.36 there was no record: an engine that ran and was not stopped counts as on."""
    it = _read_json(os.path.join(commons_folder, FOLDER, INTENT_NAME), None)
    if isinstance(it, dict) and it.get("want") in ("on", "off"):
        return it
    folder = os.path.join(commons_folder, FOLDER)
    if os.path.exists(os.path.join(folder, "_runner.json")) and not os.path.exists(os.path.join(folder, "_runner.stop")):
        return {"want": "on", "at": 0, "by": "an engine was running and Stop was not pressed"}
    return {"want": None, "at": 0, "by": ""}


def set_intent(commons_folder, on, by=""):
    folder = os.path.join(commons_folder, FOLDER)
    cur = _read_json(os.path.join(folder, INTENT_NAME), {})
    if cur.get("want") == ("on" if on else "off"):
        return                                          # unchanged: keep when it was first said
    _ka_save(os.path.join(folder, INTENT_NAME), {"want": "on" if on else "off", "at": time.time(), "by": str(by)[:200]})


def resting(commons_folder, now=None):
    """dataset -> until when it rests (only those still resting)"""
    now = now or time.time()
    r = _read_json(os.path.join(commons_folder, FOLDER, REST_NAME), {})
    return {k: v for k, v in r.items() if isinstance(v, (int, float)) and v > now} if isinstance(r, dict) else {}


def rest(commons_folder, keys, seconds=REST_S, now=None):
    now = now or time.time()
    r = resting(commons_folder, now)
    r.update({k: now + seconds for k in keys})
    _ka_save(os.path.join(commons_folder, FOLDER, REST_NAME), r)
    return r


def hard_stop(commons):
    """level 2: every agent and the runner ended at once (SQLite undoes an unfinished batch; it is read again), and the
    marks a hung process leaves behind are cleared, so the start that follows begins clean"""
    folder = os.path.join(commons.folder, FOLDER)
    open(os.path.join(folder, "_runner.stop"), "w").close()
    ended = []
    for pid in sorted(_agent_pids(commons.folder)):
        _kill(pid)
        ended.append(pid)
    rp = _runner_pid(commons.folder)
    if rp and _pid_alive(rp):
        _kill(rp)
        ended.append(rp)
    d = os.path.join(folder, "_agents")
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.endswith(".json"):
                try:
                    os.remove(os.path.join(d, f))
                except OSError:
                    pass
    hb = os.path.join(folder, "_runner.json")
    rs = _read_json(hb, None)
    if isinstance(rs, dict):                           # the ended runner can no longer say so itself
        rs.update(note="finished", heartbeat=0)
        _ka_save(hb, rs)
    TR.event("keepalive", action="hard stop", ended=ended)
    return ended


def _mins(sec):
    sec = int(sec)
    return "%d h %02d min" % (sec // 3600, sec % 3600 // 60) if sec >= 3600 else "%d min" % (sec // 60)


def keep_alive(commons, program_dir, now=None, st=None, restart=None):
    """24 x 7, called by the Control Panel's monitoring pass (every minute or so). The runner and each agent already
    restart what dies or hangs. This watches the WHOLE engine while it should be working (Start was pressed, Stop was
    not; some dataset is running, not every one finished or waiting on purpose):
      1.35  nothing at all moves (no fact, no byte, no row) for 30 minutes -> a clean restart;
      1.36  no NEW fact for 60 min -> a clean restart; for 2 h -> a hard restart; for 3 h -> the datasets that add
            nothing are rested for 6 hours and the others take their place. One new fact resets the ladder. A filing
            that is advancing (staged facts going into the store) is real work and is not interrupted.
    Every action is written down with its reason and shown on the Harvesting page. Returns what it did, or None."""
    folder = os.path.join(commons.folder, FOLDER)
    now = now or time.time()
    path = os.path.join(folder, KEEPALIVE_NAME)
    ka = _read_json(path, None)
    if not isinstance(ka, dict):
        ka = {"since": now, "sig": None, "restarts": []}
    if os.path.exists(os.path.join(folder, "_runner.stop")) or stopping(commons.folder):
        ka.update(since=now, sig=None, new_at=now)     # stopped on purpose (or a stop still saving): nothing to watch
        _ka_save(path, ka)
        return None
    st = st or status_cached(commons.folder, commons)
    rs = st.get("runner") or {}
    if not rs.get("alive"):
        ka.update(since=now, sig=None, new_at=now)     # a dead runner is ensure_on's / resume_if_crashed's job (same pass)
        _ka_save(path, ka)
        return None
    if str(rs.get("note") or "").startswith("starting"):
        # 1.37: getting ready (adding back facts from another copy) is work, with its own progress — 1.35/1.36 saw
        # "18 datasets running, nothing moving", restarted the engine after 30 minutes, and the merge began again.
        rn = restoring_now(commons.folder) or {}
        psig = [rs.get("note"), rn.get("key"), rn.get("piece"), rn.get("added")]
        if psig != ka.get("prep_sig"):
            ka.update(prep_sig=psig, prep_at=now)
        ka.update(since=now, sig=None, new_at=now, preparing=str(rs.get("note"))[:300], prep_since=ka.get("prep_since") or now, idle=False, working="")
        if now - (ka.get("prep_at") or now) < KEEPALIVE_STALL_S:
            _ka_save(path, ka)
            return None
        why = "getting ready stood still for %d min (%s)" % ((now - ka["prep_at"]) // 60, str(rs.get("note"))[:120])
        ka["restarts"] = (ka.get("restarts") or [])[-49:] + [{"at": now, "why": why, "level": 1, "action": "restarted (it resumes where it stopped)"}]
        ka.update(prep_at=now, prep_sig=None)
        _ka_save(path, ka)
        TR.event("keepalive", action="restart", why=why, level=1)
        if restart:
            restart()
        else:
            stop(commons, grace=STOP_GRACE_S, auto=True)
            full_speed(commons, program_dir, "keep-alive: " + why)
        return {"restarted": True, "why": why, "level": 1, "action": "restarted (it resumes where it stopped)"}
    ka.update(preparing="", prep_since=None)
    running = [d for d in st["datasets"] if d.get("state") == "running"]
    moving = agents_moving(commons.folder)
    dl = ((st.get("download") or {}).get("done") if isinstance(st.get("download"), dict) else None)
    sig = [st.get("total_gathered", st.get("total")), st.get("total"),
           sum(int(((d.get("progress") or {}).get("done")) or 0) for d in st["datasets"]), dl, moving]
    g = st.get("total_gathered", st.get("total")) or 0
    if ka.get("new_total") is None or ka.get("new_at") is None or g > ka["new_total"]:
        ka.update(new_total=g, new_at=now, level=0)    # a new fact: all is well, the ladder starts over
    elif g < ka["new_total"]:
        ka["new_total"] = g
    busy = [[a[0], a[3]] for a in moving if a[3]]      # filings under way, with their step counts
    try:
        waiting_for_download = dl is not None and not stream_while_downloading(commons)
    except Exception:
        waiting_for_download = False
    busy_sig = [busy, dl if waiting_for_download else None]
    if busy_sig != ka.get("busy_sig"):
        ka.update(busy_sig=busy_sig, busy_at=now)
    working = bool(busy or (waiting_for_download and dl)) and now - (ka.get("busy_at") or 0) < BUSY_GRACE_S \
        and now - ka["new_at"] < WORK_MAX_S
    moved = sig != ka.get("sig")
    if moved:
        ka.update(sig=sig, since=now)
    idle_on_purpose = str(rs.get("note") or "").startswith("waiting") or not running
    ka["idle"] = bool(idle_on_purpose)
    ka["working"] = ("filing" if busy else "downloading") if working else ""
    # 1.37 — churn, dataset by dataset: its agent keeps reading (bytes and rows move) and not one new fact comes of it.
    cat = catalog()
    per, mv, filing_keys = ka.get("per") or {}, {a[0]: [a[1], a[2]] for a in moving}, {a[0] for a in moving if a[3]}
    newper, churn = {}, []
    for d in running:
        k_ = d["key"]
        g_ = d.get("gathered", d.get("facts")) or 0
        p_ = per.get(k_)
        if not p_ or g_ > p_["g"] or k_ in filing_keys or getattr(cat.get(k_), "standalone", False) or k_ == "hot-demand":
            p_ = {"g": g_, "at": now, "mv": mv.get(k_), "moved": False}
        else:
            if mv.get(k_) is not None and mv.get(k_) != p_.get("mv"):
                p_.update(mv=mv.get(k_), moved=True)
            p_["g"] = min(p_["g"], g_)
            if p_["moved"] and now - p_["at"] >= DRY_DATASET_S:
                churn.append(k_)
        newper[k_] = p_
    ka["per"] = newper
    if churn:
        counts = ka.get("rest_n") or {}
        for k_ in churn:
            counts[k_] = int(counts.get(k_) or 0) + 1
            rest(commons.folder, [k_], REST_S * min(4, 2 ** (counts[k_] - 1)), now)   # 6 h, then 12 h, then 24 h
            newper.pop(k_, None)
        ka["rest_n"] = counts
        why = "%s read for %s without one new fact (the store already holds what %s reading)" % (
            ", ".join(churn[:6]) + (" and %d more" % (len(churn) - 6) if len(churn) > 6 else ""), _mins(DRY_DATASET_S), "it is" if len(churn) == 1 else "they are")
        action = "rested %d dataset(s) that were reading without adding anything, so the drive stops working for nothing" % len(churn)
        ka["restarts"] = (ka.get("restarts") or [])[-49:] + [{"at": now, "why": why, "level": 3, "action": action}]
        _ka_save(path, ka)
        TR.event("keepalive", action=action, why=why, level=3)
        try:
            with commons.store.write() as db:
                commons.agent_log(db, "engine", "Fail-safe: harvesting %s — %s" % (action, why))
        except Exception:
            pass
        return {"rested": churn, "why": why, "level": 3, "action": action}
    level, why = 0, ""
    if not idle_on_purpose:
        dry = now - ka["new_at"]
        if not moved and now - ka["since"] >= KEEPALIVE_STALL_S:
            level = 1
            why = "nothing moved for %d min (no fact gathered or filed, no byte downloaded) with %d dataset(s) running" % (
                (now - ka["since"]) // 60, len(running))
        elif not working and int(ka.get("level") or 0) < len(NOFACT_S) and dry >= NOFACT_S[int(ka.get("level") or 0)]:
            level = int(ka.get("level") or 0) + 1
            why = "no new fact for %s although %d dataset(s) were running" % (_mins(dry), len(running))
            ka["level"] = level
    if not level:
        _ka_save(path, ka)
        return None
    dry_keys = [d["key"] for d in running if not getattr(cat.get(d["key"]), "standalone", False)]
    action = {1: "restarted", 2: "restarted hard (every process ended, stale marks cleared)",
              3: "rested %d dataset(s) that added nothing for %s, so the others take their place" % (len(dry_keys), _mins(REST_S))}[level]
    if level == 3:
        rest(commons.folder, dry_keys, REST_S, now)
        ka.update(new_at=now, level=0)                 # a fresh ladder for the datasets that now get their turn
    ka["restarts"] = (ka.get("restarts") or [])[-49:] + [{"at": now, "why": why, "level": level, "action": action}]
    ka.update(since=now, sig=None)
    _ka_save(path, ka)
    TR.event("keepalive", action=action, why=why, level=level)
    try:
        with commons.store.write() as db:
            commons.agent_log(db, "engine", "Fail-safe: harvesting %s — %s" % (action, why))
    except Exception:
        pass
    if level == 3:
        return {"rested": dry_keys, "why": why, "level": 3, "action": action}
    if restart:
        restart()
    elif level == 2:
        hard_stop(commons)
        full_speed(commons, program_dir, "fail-safe (hard restart): " + why)
    else:
        stop(commons, grace=STOP_GRACE_S, auto=True)
        full_speed(commons, program_dir, "keep-alive: " + why)   # waits for the stop to finish saving, then starts
    return {"restarted": True, "why": why, "level": level, "action": action}


def ensure_on(commons, program_dir, now=None, launch=None):
    """1.36 fail-safe, called in the same monitoring pass, first: harvesting is switched ON (Start was pressed, Stop was
    not) and no engine is running — after a reboot, a crash, an update into a new folder, a restart that was cut short
    and left its stop mark behind — so it is started. The stop mark alone no longer means 'stopped on purpose': only
    the Stop button does. Also keeps the Windows start-up entry pointing at the folder QueryBook runs from now."""
    now = now or time.time()
    folder = os.path.join(commons.folder, FOLDER)
    it = intent(commons.folder)
    out = None
    if it.get("want") == "on":
        try:
            autostart_follow(commons.folder, program_dir)
        except Exception:
            pass
        if not _alive(commons.folder) and not stopping(commons.folder) and now - (it.get("at") or 0) > ENSURE_WAIT_S:
            mark = os.path.join(folder, "_runner.resumed")
            try:
                recent = now - os.path.getmtime(mark) < RESUME_GAP_S
            except OSError:
                recent = False
            if not recent:
                os.makedirs(folder, exist_ok=True)
                open(mark, "w").close()
                why = "harvesting is switched on and no engine was running"
                r = full_speed(commons, program_dir, "fail-safe: " + why, launch)
                if r.get("bulk") in ("started", "starting after the stop", "replacing an older engine"):
                    ka = _read_json(os.path.join(folder, KEEPALIVE_NAME), None)
                    if not isinstance(ka, dict):
                        ka = {"since": now, "sig": None, "restarts": []}
                    ka["restarts"] = (ka.get("restarts") or [])[-49:] + [{"at": now, "why": why, "level": 0, "action": "started"}]
                    ka.update(since=now, sig=None, new_at=now, level=0)
                    _ka_save(os.path.join(folder, KEEPALIVE_NAME), ka)
                    out = {"started": True, "why": why, "result": r}
    return out


def autostart_follow(commons_folder, program_dir):
    """harvesting switched on: Windows starts QueryBook after a reboot, from the folder it runs from NOW (each download
    unpacks into a new folder; the entry used to keep pointing at the old one). Off only when the person turned it off."""
    if os.path.exists(os.path.join(commons_folder, FOLDER, "_autostart.off")):
        return None
    cur = autostart(program_dir)
    if not cur.get("available") or not os.path.exists(cur.get("starts") or ""):
        return None
    try:
        with open(cur["file"]) as f:
            same = cur["starts"] in f.read()
    except OSError:
        same = False
    return None if same else autostart(program_dir, True)


def watchdog_info(commons_folder, alive=None, now=None):
    """the fail-safe in plain words, for the Harvesting page and the diagnostics"""
    now = now or time.time()
    folder = os.path.join(commons_folder, FOLDER)
    ka = _read_json(os.path.join(folder, KEEPALIVE_NAME), {})
    ka = ka if isinstance(ka, dict) else {}
    it = intent(commons_folder)
    rested = resting(commons_folder, now)
    dry = max(0, now - ka["new_at"]) if ka.get("new_at") else 0
    level = int(ka.get("level") or 0)
    last = (ka.get("restarts") or [None])[-1]
    out = {"want": it.get("want"), "since": it.get("at"), "last_new_at": ka.get("new_at"), "dry_s": int(dry), "level": level,
           "resting": rested, "last_action": last, "actions": len(ka.get("restarts") or []), "state": "ok", "text": ""}
    if not alive:
        return out
    did = (" Last action: %s, %s ago (%s)." % (last.get("action") or "restarted", _mins(now - last["at"]), last.get("why"))) if last and last.get("at") else ""
    rest_txt = (" Resting: %s." % ", ".join("%s until %s" % (k, time.strftime("%H:%M", time.localtime(v))) for k, v in sorted(rested.items())[:6])
                + (" and %d more" % (len(rested) - 6) if len(rested) > 6 else "")) if rested else ""
    if ka.get("preparing"):
        took = max(0, now - (ka.get("prep_since") or now))
        out.update(state="preparing", dry_s=int(took), text="Getting ready before harvesting (%s so far): %s. Each piece is saved as it is done, "
                   "so an interruption no longer starts it over." % (_mins(took), str(ka["preparing"]).replace("starting: ", "")))
        if took >= 30 * 60:
            out["alert"] = {"level": "warn", "text": "Harvesting has been getting ready for %s (%s). No new facts arrive until it is done; it is advancing and resumes where it stopped if interrupted."
                            % (_mins(took), str(ka["preparing"]).replace("starting: ", "")[:160])}
    elif ka.get("idle"):
        out.update(state="caught-up", text="Nothing left to read right now: every dataset is finished, resting or waiting for its next try. "
                   "QueryBook looks again by itself (finished datasets daily, for new editions)." + rest_txt)
    elif ka.get("working"):
        out.update(state="working", text=("No new fact for %s because the engine is %s — real work, not a stall; the count rises when it is done." % (
            _mins(dry), "filing the facts it gathered into the store" if ka["working"] == "filing" else "downloading the Wikidata dump (the lanes wait for it)")) + did)
    elif dry >= 600:
        nxt = next((t for t in NOFACT_S[level:]), None)
        step = {0: "restarts the engine", 1: "restarts it hard (every process ended)", 2: "rests the datasets that add nothing so the others take their place"}.get(level, "")
        out.update(state="dry", text="Running, but no new fact for %s — the agents are reading records the store already holds, or are stuck. "
                   "The fail-safe is watching%s." % (_mins(dry), (": at %s without a new fact it %s" % (_mins(nxt), step)) if nxt and step else "") + did + rest_txt)
    if out["state"] == "dry" and dry >= ALERT_DRY_S:
        out["alert"] = {"level": "warn" if dry < NOFACT_S[0] else "error", "text": "Harvesting has added no new fact for %s. %s" % (
            _mins(dry), "A dataset that reads for 45 min without a new fact is rested; the engine is restarted at 1 h and restarted hard at 2 h." + did)}
    return out


def drive_probe(commons_folder, wait=15):
    """does the data drive answer? a small file written, forced to the disk, read back and removed — in at most `wait`
    seconds (a drive that hangs must not hang the monitor). Returns (ok, why)."""
    import threading
    res = {}

    def go():
        pth = os.path.join(commons_folder, FOLDER, "_probe.%d.tmp" % os.getpid())
        try:
            os.makedirs(os.path.dirname(pth), exist_ok=True)
            with open(pth, "wb") as f:
                f.write(b"querybook")
                f.flush()
                os.fsync(f.fileno())
            with open(pth, "rb") as f:
                good = f.read() == b"querybook"
            os.remove(pth)
            res["r"] = (True, "") if good else (False, "the data drive returned something other than what was written")
        except OSError as e:
            res["r"] = (False, "the data drive refused a small write: %s" % e)
    t = threading.Thread(target=go, daemon=True, name="qb-drive-probe")
    t.start()
    t.join(wait)
    return res.get("r") or (False, "the data drive did not answer within %d seconds" % wait)


DRIVE_STATE = {}                   # commons folder -> {"paused_at", "why"}: set by the Control Panel's drive guard (in memory:
#                                    it must be readable when the drive is not)


def health(commons_folder, commons=None):
    """the harvest in one small answer, for the window's header and the alerts: never raises (the drive may be the problem)"""
    out = {"state": "unknown", "text": "", "alert": None, "facts_per_min": 0, "alive": False}
    ds = DRIVE_STATE.get(commons_folder)
    if ds:
        text = ("Harvesting is paused to protect the data drive: %s. QueryBook tests the drive every minute and starts harvesting again by itself "
                "when it answers. Check its cable and power." % ds.get("why"))
        return dict(out, state="drive", text=text, alert={"level": "error", "text": text})
    try:
        st = status_cached(commons_folder, commons)
        hl, wd = headline(st), st.get("watchdog") or {}
        out.update(state=hl.get("state"), text=hl.get("text"), alert=wd.get("alert"), facts_per_min=st.get("facts_per_min") or 0,
                   alive=bool((st.get("runner") or {}).get("alive")), want=wd.get("want"), total=st.get("total_gathered", st.get("total")))
    except Exception as e:
        out.update(state="unreadable", text="The harvest could not be read just now: %s" % e)
    return out


def _ka_save(path, ka):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w") as f:
            json.dump(ka, f)
        _replace(path + ".tmp", path)
    except OSError:
        pass


def keepalive_info(commons_folder):
    try:
        with open(os.path.join(commons_folder, FOLDER, KEEPALIVE_NAME)) as f:
            ka = json.load(f)
        r = ka.get("restarts") or []
        return {"restarts": len(r), "last": r[-1] if r else None, "watching_since": ka.get("since")}
    except (OSError, ValueError):
        return {"restarts": 0, "last": None}


def _pids(commons_folder):
    """the runner's process and every agent process still marked running in a shard"""
    pids = set()
    try:
        with open(os.path.join(commons_folder, FOLDER, "_runner.json")) as f:
            pids.add(int(json.load(f).get("pid") or 0))
    except (OSError, ValueError, TypeError):
        pass
    for key in catalog():
        p = shard_path(commons_folder, key)
        if not os.path.exists(p):
            continue
        try:
            db = _ro(p)
            meta = dict(db.execute("SELECT key, value FROM meta WHERE key IN ('state', 'pid')").fetchall())
            db.close()
            if json.loads(meta.get("state", '""')) == "running":
                pids.add(int(json.loads(meta.get("pid", "0")) or 0))
        except (sqlite3.Error, ValueError, TypeError):
            pass
    pids.discard(0); pids.discard(os.getpid())
    return pids


def _kill(pid):
    """end a process and everything it started (Windows: taskkill /T; elsewhere its process group)"""
    import subprocess, signal
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30, creationflags=0x08000000)
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (OSError, AttributeError):
                os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


STOP_GRACE_S = 60


def stop(commons, grace=None, wait=False, auto=False):
    """every agent stops after its current batch; any still running after `grace` seconds (an agent from an older version, or
    one waiting hours for a slow disk) is ended — SQLite undoes its unfinished batch, which is read again next time.
    auto: a stop QueryBook makes itself on the way to a restart — harvesting stays switched on (see ensure_on)."""
    import threading
    folder = os.path.join(commons.folder, FOLDER)
    os.makedirs(folder, exist_ok=True)
    if not auto:
        set_intent(commons.folder, False, "Stop pressed")
    open(os.path.join(folder, "_runner.stop"), "w").close()
    grace = STOP_GRACE_S if grace is None else grace

    def enforce():
        t0 = time.time()
        while time.time() - t0 < grace and _agent_pids(commons.folder):
            time.sleep(1)
        left = _agent_pids(commons.folder)
        for pid in left:                              # agents only: the runner is saving what changed to D:
            _kill(pid)
        if left:
            TR.event("stop", ended=sorted(left), why="agent still running %d s after Stop" % grace)
        rp = _runner_pid(commons.folder)              # the runner ends by itself; it is ended only if it ignores Stop or hangs
        t1 = time.time()
        while rp and time.time() - t0 < STOP_SAVE_S:
            hb = _runner_heartbeat(commons.folder)
            if hb.get("note") == "finished" or not _pid_alive(rp):
                return
            if not str(hb.get("note") or "").startswith("stopping") and time.time() - t1 > 30:
                break                                 # it does not react to Stop (an older version, or stuck)
            if time.time() - hb.get("heartbeat", 0) > 120:
                break                                 # it stopped beating while saving: hung
            time.sleep(2)
        if rp and _pid_alive(rp) and _runner_heartbeat(commons.folder).get("note") != "finished":
            _kill(rp)
            TR.event("stop", ended=[rp], why="the runner gave no sign of life for 2 min while stopping")
    th = threading.Thread(target=enforce, daemon=True, name="qb-stop")
    th.start()
    if wait:
        th.join()
    out = {"summary": "harvesting stops: every agent finishes its current batch (any still running after %d s is ended), then what "
                      "changed is saved to the data drive" % grace, **status_cached(commons.folder, commons)}
    _STATUS.pop(commons.folder, None)                 # the next look is fresh: it shows the stop
    return out


STOP_SAVE_S = 3 * 3600             # the longest a stop may spend saving to D: before the runner is ended anyway


def _runner_heartbeat(commons_folder):
    try:
        with open(os.path.join(commons_folder, FOLDER, "_runner.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _runner_pid(commons_folder):
    try:
        return int(_runner_heartbeat(commons_folder).get("pid") or 0) or None
    except (TypeError, ValueError):
        return None


def _pid_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        import subprocess
        try:
            r = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"], capture_output=True, text=True, timeout=20, creationflags=0x08000000)
            return str(pid) in r.stdout
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def agents_moving(commons_folder):
    """1.35.2: every live agent's own progress — bytes read, rows, SQLite steps while filing — as one list. It changes
    while ANY agent advances, so keep_alive never restarts an engine whose agent is in the middle of a long filing
    (only a filing frozen for 30 minutes, not a single step, is a stall)."""
    out = []
    d = os.path.join(commons_folder, FOLDER, "_agents")
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.endswith(".json"):
                try:
                    with open(os.path.join(d, f)) as fh:
                        a = json.load(fh)
                    if time.time() - a.get("at", 0) < 120:
                        out.append([f[:-5], a.get("meter"), a.get("rows"), a.get("filing")])
                except (OSError, ValueError, TypeError):
                    pass
    return out


def _agent_pids(commons_folder):
    """every agent process still alive: from its heartbeat file (every agent, the download too) and from its shard"""
    pids = set()
    d = os.path.join(commons_folder, FOLDER, "_agents")
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.endswith(".json"):
                try:
                    with open(os.path.join(d, f)) as fh:
                        a = json.load(fh)
                    if time.time() - a.get("at", 0) < 60 and a.get("pid"):
                        pids.add(int(a["pid"]))
                except (OSError, ValueError, TypeError):
                    pass
    pids |= {p for p in _pids(commons_folder) if _pid_alive(p)}    # a shard can still say "running" after a crash
    rp = _runner_pid(commons_folder)
    pids.discard(rp or 0); pids.discard(0); pids.discard(os.getpid())
    return pids


def stopping(commons_folder):
    """a stop still under way: the runner saving to D:, or agents not yet ended"""
    hb = _runner_heartbeat(commons_folder)
    return (str(hb.get("note") or "").startswith("stopping") and time.time() - hb.get("heartbeat", 0) < 120) or \
        bool(os.path.exists(os.path.join(commons_folder, FOLDER, "_runner.stop")) and _agent_pids(commons_folder))


def runner_version(commons_folder):
    try:
        with open(os.path.join(commons_folder, FOLDER, "_runner.json")) as f:
            return json.load(f).get("version")
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------------------------------------ the analysis, by email
DELAYS = [   # (words in the measured bottleneck, the delay in plain words, what QueryBook does about it)
    (("connection-slot", "net_wait", "refused", "429", "503", "slow down"),
     "waiting for download connections (each server lets only a few downloads in at a time)",
     "an agent that waits more than 10 minutes gives its place to another dataset and comes back; mirror servers are used when they hold the same file"),
    (("network",), "download speed (the internet connection or the server)",
     "every connection the servers allow is kept busy; nothing to fix on this computer"),
    (("disk", "commit", "drive"), "writing to the drive",
     "facts are written on C: first and copied to D: in the background; when C: fills up, a dataset moves to D: and carries on"),
    (("CPU",), "the processor (every core is busy — the best case)", "nothing needed"),
]


def _runner_events(commons_folder, since):
    try:
        with open(os.path.join(commons_folder, FOLDER, "_runner.json")) as f:
            return [e for e in (json.load(f).get("events") or []) if e.get("at", 0) >= since]
    except (OSError, ValueError):
        return []


def plain_summary(st, o=None, events=(), hours=2, commons=None):
    """the harvest for a person, in a few short lines: health, speed, the main delay and what is done about it,
    what recovered by itself, and what (if anything) to do"""
    rs = st.get("runner") or {}
    fpm = st.get("facts_per_min") or 0
    alive = rs.get("alive")
    old = alive and rs.get("version") not in (None, VERSION)
    if not alive:
        health = "STOPPED"
    elif fpm >= 1_000_000:
        health = "GOOD"
    elif fpm > 0:
        health = "WORKING, BUT SLOW"
    else:
        health = "RUNNING — NO NEW FACTS IN THE LAST 10 MINUTES"
    L = ["QueryBook harvest — %s" % time.strftime("%d %b %Y %H:%M"), "",
         "Health:      %s" % health,
         "Speed now:   %s facts a minute (%s in the last hour)" % (format(fpm, ","), format(st.get("last_hour") or 0, ",")),
         "Facts held:  %s" % format(st.get("total") or 0, ",")]
    if st.get("working_copies") and st.get("on_data_drive") is not None:
        L.append("             %s already saved on the data drive (D:); the rest is in the working copies on C:, saved to D: every 10 minutes"
                 % format(st["on_data_drive"], ","))
    # the main delay, weighed by how long each dataset ran
    weight = {}
    for d in (o or {}).get("datasets") or []:
        b = d.get("bottleneck") or ""
        for i, (words, _, _) in enumerate(DELAYS):
            if any(w.lower() in b.lower() for w in words):
                weight[i] = weight.get(i, 0) + (d.get("wall_s") or 0)
                break
    for c in ((o or {}).get("congestion") or [])[:3]:
        for i, (words, _, _) in enumerate(DELAYS):
            if any(w.lower() in str(c.get("what")).lower() for w in words):
                weight[i] = weight.get(i, 0) + (c.get("total_s") or 0)
                break
    if weight:
        i = max(weight, key=weight.get)
        L += ["Main delay:  %s" % DELAYS[i][1], "             QueryBook: %s." % DELAYS[i][2]]
    else:
        L.append("Main delay:  none measured yet")
    ends = [e for e in events if e.get("what") == "ended" and e.get("state") != "done" and "Stop" not in str(e.get("why"))]
    L.append("Recovered by itself (last %g h): %s" % (hours, ("%d time(s)" % len(ends)) if ends else "nothing needed"))
    for e in ends[-5:]:
        nxt = e.get("next_in_s")
        L.append("  %s  %s — %s%s" % (time.strftime("%H:%M", time.localtime(e.get("at", 0))), e.get("dataset"),
                                       str(e.get("why") or e.get("state"))[:110],
                                       ("; tried again after %s" % qt.fmt_dur(nxt)) if nxt else ""))
    drops = st.get("drops") or []
    if drops:
        dup = sum(d["fell"] for d in drops if d["cause"].startswith("duplicates"))
        other = [d for d in drops if not d["cause"].startswith("duplicates")]
        if dup:
            L.append("Duplicates removed (last %g h): %s — the same facts already held by another dataset; nothing is lost" % (hours, format(dup, ",")))
        for d in other[-3:]:
            L.append("Count fell: %s %s → %s — %s" % (d["dataset"], format(d["from"], ","), format(d["to"], ","), d["cause"]))
    fails = ((o or {}).get("failures") or [])[:3]
    if fails:
        L.append("Problems seen (all retried): " + "; ".join("%s %s ×%d" % (f["where"], f["kind"], f["count"]) for f in fails))
    if not alive:
        todo = "press ⚡ Start harvesting (and tick \"Start QueryBook when Windows starts\" so it never stays stopped)"
    elif old:
        todo = "press ■ Stop harvesting, wait a minute, then ⚡ Start harvesting (an older engine is still running)"
    elif any("not connected" in str(e.get("why")) for e in ends[-3:]):
        todo = "connect the data drive (D:) — the harvest resumes by itself within a minute"
    else:
        todo = "nothing — QueryBook restarts, re-routes and retries by itself"
    if commons is not None:                            # Control Panel 1.34: answer routing and the Shadow comparison
        try:
            import qbdsn
            L += qbdsn.health_lines(commons)
        except Exception as e:                         # the health report must never fail because of this section
            L.append("Answer routing: could not be read (%s)" % e)
    L += ["", "What you need to do: " + todo]
    return "\n".join(L)


def analysis_text(commons, hours=2, max_seconds=120, counter=None):
    """the instrumentation report of the last `hours`, with the one-sentence headline on top"""
    cut = time.time() - hours * 3600
    files = []
    for d in qt.trace_dirs(commons.folder):
        if os.path.isdir(d):
            files += [os.path.join(d, f) for f in sorted(os.listdir(d))
                      if f.endswith((".jsonl", ".jsonl.gz")) and os.path.getmtime(os.path.join(d, f)) >= cut]
    t0, n = time.time(), [0]

    def counted():
        for l in qt.read_lines(files, since_ns=int(cut * 1e9), max_seconds=max_seconds):
            n[0] += 1
            if counter is not None:
                counter["lines"] = n[0]
            yield l
    o = qt.analyze(counted())
    st = status_cached(commons.folder, commons)
    hl = plain_summary(st, o, _runner_events(commons.folder, cut), hours, commons)
    text = (hl + "\n\n\n" + "-" * 70 + "\nTECHNICAL DETAILS (for support — you do not need to read these)\n" +
            "Last %g hour(s) of logs: %d file(s), %s lines, analysed in %s\n\n" % (hours, len(files), format(n[0], ","), qt.fmt_dur(time.time() - t0))
            + qt.text_report(o))
    return text, o, hl, len(files)


def _email_path(commons):
    return os.path.join(commons.folder, "report-email.json")


def email_settings(commons, program_dir=None):
    try:
        with open(_email_path(commons), encoding="utf-8") as f:
            e = json.load(f)
    except (OSError, ValueError):
        e = {}
    if not e.get("to") and program_dir:                # a personal package may name the address beside the launchers
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(program_dir)), "report-email.txt"), encoding="utf-8-sig") as f:
                e["to"] = f.read().strip()
        except OSError:
            pass
    return e


def save_email_settings(commons, to=None, user=None, password=None, every_hours=None):
    e = email_settings(commons)
    if to is not None:
        e["to"] = to.strip()
    if user is not None:
        e["user"] = user.strip()
    if password:
        e["password"] = password.replace(" ", "").strip()     # Google shows app passwords in groups of four
    if every_hours is not None:
        e["every_hours"] = max(0.0, float(every_hours))
    with open(_email_path(commons) + ".tmp", "w", encoding="utf-8") as f:
        json.dump(e, f)
    _replace(_email_path(commons) + ".tmp", _email_path(commons))
    try:
        os.chmod(_email_path(commons), 0o600)
    except OSError:
        pass
    return e


def send_report(commons, program_dir=None, hours=2, smtp=None):
    """analyse and email the report (Gmail: smtp.gmail.com with an app password). Returns what was sent."""
    import smtplib
    from email.message import EmailMessage
    e = email_settings(commons, program_dir)
    to, user, pw = e.get("to"), e.get("user") or e.get("to"), e.get("password")
    if not to or not pw:
        raise ValueError("Set the address and the Gmail app password first (Harvesting → Email the analysis).")
    text, o, hl, nfiles = analysis_text(commons, hours)
    m = EmailMessage()
    lines = {l.split(":", 1)[0].strip(): l.split(":", 1)[1].strip() for l in hl.splitlines() if ":" in l}
    m["Subject"] = "QueryBook harvest %s — %s, %s" % (time.strftime("%Y-%m-%d %H:%M"), lines.get("Health", "?"), lines.get("Speed now", "")[:60])
    m["From"], m["To"] = user, to
    m.set_content(text)
    m.add_attachment(text.encode("utf-8"), maintype="text", subtype="plain", filename="querybook-analysis-%s.txt" % time.strftime("%Y%m%d-%H%M"))
    if smtp is not None:                                 # tests
        smtp(m)
    else:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=60) as sm:
            sm.starttls()
            sm.login(user, pw)
            sm.send_message(m)
    e["last_sent"] = time.time()
    save_email_settings(commons)
    with open(_email_path(commons), encoding="utf-8") as f:
        cur = json.load(f)
    cur["last_sent"] = e["last_sent"]
    with open(_email_path(commons), "w", encoding="utf-8") as f:
        json.dump(cur, f)
    return {"sent_to": to, "headline": hl, "lines": len(text.splitlines()), "summary": "the analysis was emailed to %s" % to}


def email_due(commons, program_dir=None, now=None):
    """the Control Panel's monitor calls this: sends the analysis every `every_hours` (0 = never)"""
    e = email_settings(commons, program_dir)
    every = float(e.get("every_hours") or 0)
    now = now or time.time()
    if not every or not e.get("password") or not e.get("to") or now - float(e.get("last_sent") or 0) < every * 3600:
        return None
    return send_report(commons, program_dir)


# ------------------------------------------------------------------------------------------------ start with Windows
AUTOSTART_NAME = "QueryBook-start.cmd"


def _startup_folder():
    env = os.environ.get("QB_STARTUP_FOLDER")             # tests
    if env:
        return env
    if os.name != "nt" or not os.environ.get("APPDATA"):
        return None
    return os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def autostart(program_dir, on=None):
    """Windows starts QueryBook by itself after a restart (a small file in the Startup folder): the harvest carries on
    after an update, a power cut or a reboot. on=None: just say whether it is set."""
    folder = _startup_folder()
    if not folder:
        return {"available": False, "on": False, "why": "only on Windows"}
    path = os.path.join(folder, AUTOSTART_NAME)
    suite = os.path.dirname(os.path.abspath(program_dir))
    start_all = os.path.join(suite, "START-QueryBook.bat")              # 1.35: the one window (QueryBook.zip)
    if not os.path.exists(start_all):
        start_all = os.path.join(suite, "START-ALL-WINDOWS.bat")        # the separate-windows suite
    if on is True:
        os.makedirs(folder, exist_ok=True)
        with open(path, "w", newline="") as f:              # waits a little first: an external drive is often found late
            f.write("@echo off\r\nREM QueryBook: start after Windows starts (turn off in the Control Panel, Harvesting tab)\r\n"
                    "timeout /t 60 /nobreak >nul\r\nstart \"QueryBook\" /min cmd /c \"%s\"\r\n" % start_all)
    elif on is False and os.path.exists(path):
        os.remove(path)
    return {"available": True, "on": os.path.exists(path), "file": path, "starts": start_all}


def add_routes(api, commons, program_dir):
    commons.registry.ensure()

    @api.get("/api/autostart")
    def autostart_get(p):
        return autostart(program_dir)

    @api.post("/api/autostart")
    def autostart_set(p):
        off = os.path.join(commons.folder, FOLDER, "_autostart.off")   # 1.36: only the person's own "off" keeps it off
        try:
            if p.get("on"):
                if os.path.exists(off):
                    os.remove(off)
            else:
                os.makedirs(os.path.dirname(off), exist_ok=True)
                open(off, "w").close()
        except OSError:
            pass
        return autostart(program_dir, bool(p.get("on")))
    @api.post("/api/bulk/demand")
    def bulk_demand(p):
        return demand_note(commons.folder, p.get("subject") or "", p.get("question") or "", p.get("why") or "")

    @api.get("/api/bulk/demand")
    def bulk_demand_list(p):
        return {"demand": demand_list(commons.folder)[-200:], "learned": demand_learned(commons.folder)}

    @api.get("/api/bulk/entity")
    def bulk_entity(p):
        """1.40: who or what is meant by a name — the best-known match first, with all its facts"""
        return find_entities(commons.folder, p.get("q") or "", int(p.get("top") or 5))

    @api.get("/api/bulk/domains")
    def bulk_domains(p):
        return {"domains": domains_report(commons.folder)}

    @api.get("/api/bulk/coverage")
    def bulk_coverage(p):
        return dump_coverage(commons.folder)

    @api.get("/api/bulk/health")
    def bulk_health(p):
        return health(commons.folder, commons)

    @api.get("/api/bulk")
    def bulk_status(p):
        st = status_cached(commons.folder, commons)
        return dict(st, headline=headline(st))

    @api.post("/api/bulk/start")
    def bulk_start(p):
        try:
            return start(commons, p.get("datasets"), p.get("agents", 4), p.get("passphrase"), program_dir)   # 0 = full speed
        except ValueError as e:
            raise core.UserError(str(e))

    @api.post("/api/bulk/stop")
    def bulk_stop(p):
        return stop(commons)

    @api.post("/api/bulk/restore")
    def bulk_restore(p):
        """find and restore missing facts (1.31.2): every copy of every dataset compared; nothing is deleted"""
        if _alive(commons.folder) or stopping(commons.folder):
            raise core.UserError("Stop harvesting first (and let the stop finish saving). This check also runs by itself at every Start.")
        r = restore_missing(commons.folder)
        _STATUS.pop(commons.folder, None)
        n = sum(v["added"] for v in r.values())
        return {"restored": r, "summary": ("%s facts added back to %d dataset(s)" % (format(n, ","), len(r))) if r else
                "every copy was checked: no dataset was missing facts that another copy holds"}

    @api.get("/api/backup")
    def backup_status(p):
        import qbvault
        return qbvault.status(commons.folder)

    @api.post("/api/backup/settings")
    def backup_settings(p):
        """the backup drive's folder, how many generations to keep, how often (admin)"""
        import qbvault
        commons.approvals._require(p.get("passphrase") or "")
        try:
            qbvault.save_config(commons.folder, p.get("folder"), p.get("keep"), p.get("every_hours"), p.get("on"))
        except ValueError as e:
            raise core.UserError(str(e))
        return qbvault.status(commons.folder)

    @api.post("/api/backup/now")
    def backup_now(p):
        """a backup in the background (the page follows backup-status.json); refused while one runs"""
        import qbvault, threading
        if not qbvault.vault_dir(commons.folder):
            raise core.UserError("Choose a backup folder on a connected drive first.")
        if qbvault.running(commons.folder):
            raise core.UserError("A backup is already running.")

        def go():
            try:
                qbvault.backup(commons.folder, reason="manual")
            except Exception:
                pass                                    # the reason is in backup-status.json
        threading.Thread(target=go, daemon=True, name="qb-backup-now").start()
        return {"started": True}

    @api.post("/api/backup/restore")
    def backup_restore(p):
        """add back from a backup every fact the live datasets lack; copy back missing files. Nothing is deleted."""
        import qbvault
        if _alive(commons.folder) or stopping(commons.folder):
            raise core.UserError("Stop harvesting first (and let the stop finish saving).")
        try:
            r = qbvault.restore(commons.folder, p.get("generation"))
        except RuntimeError as e:
            raise core.UserError(str(e))
        _STATUS.pop(commons.folder, None)
        n = sum(v.get("added", 0) for v in r.values())
        return {"restored": r, "summary": ("%s facts added back, %d file(s) copied back" % (format(n, ","), sum(1 for v in r.values() if v.get("copied"))))
                if r else "the live data already holds everything in that backup"}

    @api.post("/api/bulk/download-settings")
    def bulk_download_settings(p):
        """download once (1.31): on/off, and the folder the dump is kept in (e.g. the large external drive)"""
        try:
            return save_download_settings(commons, p.get("folder"), p.get("on"), p.get("passphrase"))
        except ValueError as e:
            raise core.UserError(str(e))

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
    tfolder = lambda: qt.trace_dir(commons.folder)
    AN = {"state": "idle", "result": None, "started": None, "lines": 0}

    def analyse(hours):
        """in the background: the page never waits for the logs (a busy drive made the answer take longer than people wait)"""
        try:
            text, o, hl, nfiles = analysis_text(commons, hours, counter=AN)
            AN["result"] = {"report": o, "files": nfiles, "folder": tfolder(), "text": text, "summary": hl, "at": time.time()}
        except Exception as e:
            AN["result"] = {"text": "The analysis failed: %s" % e, "files": 0, "folder": tfolder()}
        finally:
            AN["state"] = "done"

    @api.get("/api/trace/report")
    def trace_report(p):
        """starts an analysis (the last `hours`, default 2) unless one is running; answers at once with its state —
        the page asks again until it is done"""
        settings = {"on": (commons.setting("trace:on", "on") or "on") != "off", "sample": int(commons.setting("trace:sample", qt.DEFAULT_SAMPLE) or 0)}
        if p.get("start") and AN["state"] != "working":
            import threading
            AN.update(state="working", result=None, started=time.time(), lines=0)
            threading.Thread(target=analyse, args=(float(p.get("hours") or 2),), daemon=True, name="qb-analyse").start()
        out = dict(AN["result"] or {}, state=AN["state"], settings=settings, folder=tfolder())
        if AN["state"] == "working":
            out["text"] = "Analysing… %s lines read so far (%s)" % (format(AN["lines"], ","), qt.fmt_dur(time.time() - AN["started"]))
        return out

    @api.get("/api/report/plain")
    def report_plain(p):
        """the few-line health report, at once (the main delay comes from the last analysis of the logs, when there is one;
        one is started in the background otherwise)"""
        st = status_cached(commons.folder, commons)
        last = AN["result"] if AN["result"] and time.time() - (AN["result"].get("at") or 0) < 3 * 3600 else None
        if not last and AN["state"] != "working":
            import threading
            AN.update(state="working", result=None, started=time.time(), lines=0)
            threading.Thread(target=analyse, args=(2.0,), daemon=True, name="qb-analyse").start()
        return {"text": plain_summary(st, (last or {}).get("report"), _runner_events(commons.folder, time.time() - 7200), 2, commons),
                "analysing": AN["state"] == "working"}

    @api.get("/api/report/email-settings")
    def email_get(p):
        e = email_settings(commons, program_dir)
        return {"to": e.get("to") or "", "user": e.get("user") or "", "password_set": bool(e.get("password")),
                "every_hours": e.get("every_hours") or 0, "last_sent": e.get("last_sent")}

    @api.post("/api/report/email-settings")
    def email_set(p):
        e = save_email_settings(commons, p.get("to"), p.get("user"), p.get("password") or None, p.get("every_hours"))
        return {"to": e.get("to"), "password_set": bool(e.get("password")), "every_hours": e.get("every_hours") or 0,
                "summary": "saved" + (" — the analysis is emailed every %g hour(s)" % e["every_hours"] if e.get("every_hours") else "")}

    @api.post("/api/report/email-now")
    def email_now(p):
        try:
            return send_report(commons, program_dir, float(p.get("hours") or 2))
        except ValueError as e:
            raise core.UserError(str(e))
        except Exception as e:
            raise core.UserError("The email could not be sent: %s. Check the address and the Gmail app password." % e)

    @api.get("/api/drive/old-copies")
    def old_copies_route(p):
        """the copies of earlier versions still on C: that the data drive holds (safe to delete) and those it cannot vouch for"""
        import qbdrive
        root = qbdrive.root_for(program_dir)
        if not root:
            raise core.UserError("No data drive is set (data-folder.txt beside the launchers).")
        r = qbdrive.old_copies(root, program_dir)
        return {"safe_files": len(r["safe"]), "safe_bytes": r["safe_bytes"], "keep_files": len(r["keep"]), "keep_bytes": r["keep_bytes"],
                "keep_examples": [{"path": x["path"], "why": x["why"]} for x in r["keep"][:15]], "root": root}

    @api.post("/api/drive/delete-old-copies")
    def delete_old_route(p):
        import qbdrive
        if p.get("confirm") != "yes":
            raise core.UserError("Confirm first.")
        root = qbdrive.root_for(program_dir)
        if not root:
            raise core.UserError("No data drive is set (data-folder.txt beside the launchers).")
        return qbdrive.delete_old(root, program_dir, say=lambda *a: None)

    @api.post("/api/trace/export")
    def trace_export(p):
        path, n, raw = qt.export(tfolder(), days=float(p.get("days") or 1),
                                 out_zip=os.path.join(commons.folder, "trace-export-%s.zip" % time.strftime("%Y%m%d-%H%M%S")))
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
        """answered as the Control Panel's Answer routing says: Central, DSN, or Shadow (Central answers, the DSN is compared)"""
        import qbdsn
        return qbdsn.lookup(commons, p.get("q") or "", int(p.get("limit") or 50))

    @api.get("/api/dsn/status")
    def dsn_status(p):
        """the Answer routing setting, the Shadow comparison of the last 24 hours and the learned pathways"""
        import qbdsn
        m = qbdsn.mode(commons)
        net, chk = qbdsn.network(commons), qbdsn.check_networks(commons)
        return {"mode": m, "modes": [{"id": k, "text": qbdsn.MODE_TEXT[k]} for k in qbdsn.MODES],
                "shadow": qbdsn.shadow_summary(commons), "pathways": qbdsn.pathways(commons), "health": qbdsn.health_lines(commons),
                "network": {"stores": net.summary(top=8), "checks": chk.summary(top=8)}}

    @api.post("/api/dsn/mode")
    def dsn_mode(p):
        import qbdsn
        commons.approvals._require(p.get("passphrase") or "")
        try:
            r = qbdsn.set_mode(commons, p.get("mode"))
        except ValueError as e:
            raise core.UserError(str(e))
        with commons.store.write() as db:
            commons.agent_log(db, "engine", r["summary"])
        return r


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
        "A full Wikidata pass needs about 100–200 GB for the facts, plus about 160 GB for each downloaded weekly dump (two are "
        "kept; Bulk harvesting → Download once → folder puts them on any drive). Move the shared folder to a large drive (e.g. your 20 TB drive): "
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
    w = work_dir(commons.folder)
    if w:
        wk = work_keys(commons.folder)
        dr = drained(commons.folder)
        ages = [time.time() - (dr.get(k) or {}).get("at", 0) for k in wk]
        freec = shutil.disk_usage(os.path.dirname(w) if not os.path.isdir(w) else w).free / 1e9 if os.path.isdir(os.path.dirname(w)) else None
        direct = [d["key"] for d in st["datasets"] if d["state"] == "running" and not d.get("working_copy")]
        add("Datasets writing straight to the data drive (slow)", not direct,
            ", ".join(direct) if direct else "none — every running dataset writes to its fast working copy",
            "These had no room on the internal drive (%d GB are kept free there). Free space on C: and press Stop, then Start." % WORK_MIN_FREE_GB)
        add("Fast working copies on the internal drive", True,
            "%d dataset(s) at %s; %s; saved to the data drive every %d min (oldest copy there: %s)" % (
                len(wk), w, ("%.0f GB free there" % freec) if freec is not None else "free space unknown", DRAIN_S // 60,
                ("%d min old" % (max(ages) / 60)) if ages and max(ages) < 1e8 else "not yet saved" if wk else "—"), "")
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
        # 1.26: working copies on the internal drive, saved to the data drive
        cf2 = os.path.join(tmp, "commons-d")
        c2 = cm.Commons(cf2, "stem"); c2.registry.ensure(); c2.set_setting("bulk:min_free_gb", 0)
        for k, v in (("bulk:url:pubchem-computed:CID-Mass", url("CID-Mass.gz")), ("bulk:url:pubchem-computed:CID-SMILES", url("CID-SMILES.gz")),
                     ("bulk:url:pubchem-computed:CID-InChI-Key", url("CID-InChI-Key.gz"))):
            c2.set_setting(k, v)
        old_env = {k: os.environ.get(k) for k in ("QB_WORK_FOLDER", "QB_WORK_MIN_FREE_GB")}
        os.environ["QB_WORK_FOLDER"] = os.path.join(tmp, "internal"); os.environ["QB_WORK_MIN_FREE_GB"] = "0"
        old_b, BATCH = BATCH, 1000
        try:
            w1 = run_dataset(cf2, "pubchem-computed", max_rows=1500)
            wp, hp = work_path(cf2, "pubchem-computed"), home_path(cf2, "pubchem-computed")
            ok("working copy: the agent writes to the internal drive, not the data drive",
               os.path.exists(wp) and not os.path.exists(hp) and shard_path(cf2, "pubchem-computed") == wp, w1)
            n1 = drain(cf2, "pubchem-computed")
            hn = sqlite3.connect(hp).execute("SELECT count(*) FROM facts").fetchone()[0]
            ok("the copier saves it to the data drive whole (the same facts)", n1 == hn == w1["new"] and os.path.exists(wp), (n1, hn, w1))
            at1 = drained(cf2)["pubchem-computed"]["at"]
            ok("1.31.1: an unchanged working copy is not written to the data drive again",
               drain(cf2, "pubchem-computed") == n1 and drained(cf2)["pubchem-computed"]["at"] == at1)
            os.utime(wp, (time.time() + 5, time.time() + 5))           # new facts were written to the working copy
            ok("1.31.1: a changed copy waits its turn (saved at most once per 3x its last saving time, and at least 10 min apart)",
               drain(cf2, "pubchem-computed") == "later" and drained(cf2)["pubchem-computed"]["at"] == at1)
            ok("1.31.1: Stop (or the end of a run) always saves", drain(cf2, "pubchem-computed", force=True) == n1
               and drained(cf2)["pubchem-computed"]["at"] > at1)
            st2 = status(cf2, c2)
            ok("the status says where each dataset is and when it was last saved to the data drive",
               any(d["key"] == "pubchem-computed" and d.get("working_copy") and d.get("saved_to_data_drive") for d in st2["datasets"]))
            fw = finish_work(cf2)
            ok("an unfinished dataset keeps its working copy after the run (it resumes there)", os.path.exists(wp) and "kept" in fw["pubchem-computed"], fw)
            w2 = run_dataset(cf2, "pubchem-computed")
            fw2 = finish_work(cf2)
            hn2 = sqlite3.connect(hp).execute("SELECT count(*) FROM facts").fetchone()[0]
            ok("a finished dataset is saved to the data drive and its working copy removed once the facts match",
               w2["state"] == "done" and not os.path.exists(wp) and hn2 == hn + w2["new"] and "removed" in fw2["pubchem-computed"], (w2, fw2, hn2))
            ok("with no working copy, readers find the home copy", shard_path(cf2, "pubchem-computed") == hp)
            ok("a dataset already on the data drive gets its working copy from there before it resumes",
               pull(cf2, "pubchem-computed") and sqlite3.connect(wp).execute("SELECT count(*) FROM facts").fetchone()[0] == hn2)
            os.environ["QB_WORK_MIN_FREE_GB"] = "1e12"
            os.remove(wp)
            ok("too little room on the internal drive: the agent writes to the data drive itself", pull(cf2, "pubchem-computed") is False)
        finally:
            BATCH = old_b
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        # 1.29: Stop really stops — an engine that does not stop by itself (an older version, a batch stuck on a slow disk) is ended
        import subprocess as _sp
        sleeper = _sp.Popen([sys.executable, "-c", "import time; time.sleep(300)"], start_new_session=True)
        hbp = os.path.join(cf, FOLDER, "_runner.json")
        with open(hbp, "w") as f:
            json.dump({"heartbeat": time.time() + 3600, "pid": sleeper.pid, "note": "running", "datasets": ["calendar-scaffold"]}, f)
        ok("an engine of an older version is noticed (it has no version)", runner_version(cf) is None and _alive(cf))
        stop(c, grace=1, wait=True)
        try:
            sleeper.wait(10); ended = True
        except _sp.TimeoutExpired:
            ended = False; sleeper.kill()
        ok("Stop ends whatever is still running after the grace time", ended)
        os.remove(hbp)
        os.remove(os.path.join(cf, FOLDER, "_runner.stop"))
        sent = []
        save_email_settings(c, to="me@example.org", user="me@example.org", password="abcd efgh ijkl mnop", every_hours=6)
        r_em = send_report(c, smtp=sent.append)
        ok("the analysis is emailed: the plain health report first (health in the subject), details below and attached",
           sent and sent[0]["To"] == "me@example.org" and sent[0].get_body().get_content().startswith("QueryBook harvest")
           and "Health:" in sent[0].get_body().get_content().split("TECHNICAL DETAILS")[0] and "STOPPED" in sent[0]["Subject"]
           and any(a.get_filename().endswith(".txt") for a in sent[0].iter_attachments()), r_em)
        ok("…and again only when it is due (every 6 hours here)", email_due(c) is None and email_settings(c).get("password") == "abcdefghijklmnop")
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
        both = [x for a_, b_ in ((0, cut), (cut, size)) for x in gz_member_lines("file://" + urllib.request.pathname2url(dump), a_, b_)]
        ok("Wikidata dump: two byte ranges read on their own give every entity exactly once",
           sorted(json.loads(x.rstrip(b","))["id"] for x in both if x[:1] == b"{") == ["Q30", "Q5", "Q937"], both)
        wd = WikidataDump(1, 1)
        c.set_setting("bulk:url:wikidata-dump", "file://" + urllib.request.pathname2url(dump))
        WikidataDump.LANES, lanes_was = 1, WikidataDump.LANES
        try:
            r = run_dataset(cf, "wikidata-dump-1")
            hits = search(cf, "Albert Einstein")
        finally:
            WikidataDump.LANES = lanes_was
        ok("Wikidata dump: truthy statements only (a deprecated one is skipped), objects shown with their label",
           r["state"] == "done" and {(h["predicate"], h["object"]) for h in hits} == {("date of birth", "1879-03-14"),
           ("country of citizenship", "United States (Q30)")} and hits[0]["link"] == "https://www.wikidata.org/wiki/Q937", (r, hits))
        # 1.31 download once, read locally: without a ready copy a lane waits for the download; with one it reads it, named by
        # the copy's own edition (so parts streamed before are not read again), its version the publisher's date
        c.set_setting("bulk:url:wikidata-dump", "")
        dumps = os.path.join(tmp, "dumps")
        c.set_setting("bulk:dumps:folder", dumps)
        WikidataDump.LANES = 1
        try:
            ok("1.32: by default the lanes stream while the download runs (they no longer wait idle for 157 GB)",
               stream_while_downloading(c))
            c.set_setting("bulk:wikidata:while_downloading", "wait")      # the 1.31 behaviour, kept as an option (and offline here)
            rw = run_dataset(cf, "wikidata-dump-1")
            ok("download once, set to wait: a lane waits for the one download (looked at again in 2 minutes)",
               rw["state"] == "paused" and WAITING in rw["why"] and next_try(rw, 3) == 120, rw)
            ed_dir = os.path.join(dumps, "wikidata", "2026-11-02")
            os.makedirs(ed_dir)
            shutil.copy(dump, os.path.join(ed_dir, qbdump.FILE))
            with open(os.path.join(ed_dir, "ready.json"), "w") as f:
                json.dump({"edition": "2026-11-02", "size": size, "last_modified": "Mon, 02 Nov 2026 10:00:00 GMT", "checked": "test"}, f)
            for ext in ("", "-wal", "-shm", ".labels", ".progress"):     # the lane from a clean slate: read once from the copy
                if os.path.exists(shard_path(cf, "wikidata-dump-1") + ext):
                    os.remove(shard_path(cf, "wikidata-dump-1") + ext)
            r2 = run_dataset(cf, "wikidata-dump-1")
            sh_ = sqlite3.connect(shard_path(cf, "wikidata-dump-1"))
            pn = sh_.execute("SELECT name, version FROM parts").fetchall()
            sh_.close()
            ok("download once: the lane reads the ready copy from the drive, named by its edition, versioned by the publisher's date",
               r2["state"] == "done" and pn == [("2026-11-02 part 0001 of 0001", "Mon, 02 Nov 2026 10:00:00 GMT")], (r2, pn))
            dsr = status(cf, c)["download"]
            ok("download once: the status page shows the ready edition and where it is kept",
               dsr["ready"]["edition"] == "2026-11-02" and dsr["folder"] == dumps and dsr["on"], dsr)
            src = WikidataDownload().sources(c)
            ok("download once: one server, one connection limit (Wikimedia's two addresses share theirs)",
               len({_host(u) for u, _ in src}) == len(src) and dict((_host(u), n) for u, n in src)["dumps.wikimedia.org"] == WikidataDump.PRIMARY_CONNECTIONS, src)
            c.set_setting("bulk:wikidata:local", "off")
            off = run_dataset(cf, "wikidata-download")
            ok("download once can be switched off (bulk:wikidata:local = off: the lanes stream as before)", off["state"] == "done" and "not used" in off["why"], off)
            c.set_setting("bulk:wikidata:local", "")
        finally:
            WikidataDump.LANES = lanes_was
            c.set_setting("bulk:dumps:folder", "")
            c.set_setting("bulk:wikidata:while_downloading", "")
            c.set_setting("bulk:url:wikidata-dump", "file://" + urllib.request.pathname2url(dump))      # the tests below read the dump file as before
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
        # 1.40 relevance — the hot lattices, the demand agent, fame, and choosing the right "Babe Ruth"
        import sense as _sense
        ent = lambda q, label, claims, links=0, desc=None, aliases=(): {
            "type": "item", "id": q, "labels": {"en": {"value": label}}, "sitelinks": {"w%d" % i: {} for i in range(links)},
            "descriptions": {"en": {"value": desc}} if desc else {}, "aliases": {"en": [{"value": a} for a in aliases]},
            "claims": {pp: [{"rank": "normal", "mainsnak": {"datavalue": dv}} for dv in dvs] for pp, dvs in claims.items()}}
        item = lambda q: {"type": "wikibase-entityid", "value": {"id": q}}
        when = lambda d: {"type": "time", "value": {"time": "+%sT00:00:00Z" % d, "precision": 11}}
        WORLD = {
            "Q213812": ent("Q213812", "Babe Ruth", {"P31": [item("Q5")], "P569": [when("1895-02-06")], "P106": [item("Q10871364")]}, 120,
                           "American baseball player (1895–1948)", ("The Babe", "George Herman Ruth")),
            "Q99": ent("Q99", "Babe Ruth", {"P31": [item("Q809892")]}),
            "Q83807": ent("Q83807", "Ed Sullivan", {"P31": [item("Q5")], "P569": [when("1901-09-28")], "P106": [item("Q947873")]}, 40,
                          "American television host (1901–1974)"),
            "Q334634": ent("Q334634", "Los Angeles Dodgers", {"P31": [item("Q13027888")]}, 70, "baseball team in Los Angeles, California", ("LA Dodgers",)),
            "Q777001": ent("Q777001", "Dodgers", {"P31": [item("Q11424")]}),
            "Q1299": ent("Q1299", "The Beatles", {"P31": [item("Q215380")]}, 150, "English rock band"),
        }
        LABELS = {"Q5": "human", "Q10871364": "baseball player", "Q809892": "baseball card", "Q947873": "television presenter",
                  "Q13027888": "baseball team", "Q11424": "film", "Q215380": "musical group"}
        asked_ = []

        def fake_wd(params):
            asked_.append(params)
            if params.get("list") == "search":
                hit = params["srsearch"].endswith("P106=Q10871364") and int(params["sroffset"]) == 0
                return {"query": {"search": [{"title": "Q213812"}] if hit else [], "searchinfo": {"totalhits": 1}}}
            if params.get("action") == "wbsearchentities":
                return {"search": [{"id": q} for q in {"Ed Sullivan": ["Q83807"], "Babe Ruth": ["Q213812", "Q99"],
                                                       "Dodgers": ["Q334634", "Q777001"]}.get(params["search"], [])]}
            if params.get("titles"):                       # by Wikipedia article title (the most-read lattice)
                by_t = {"Babe Ruth": "Q213812"}
                out_ = {by_t[t]: dict(WORLD[by_t[t]], sitelinks=dict(WORLD[by_t[t]]["sitelinks"], enwiki={"title": t}))
                        for t in params["titles"].split("|") if t in by_t}
                out_["-1"] = {"missing": ""}
                return {"entities": out_}
            ids = params["ids"].split("|")
            if params.get("props") == "labels":
                return {"entities": {q: {"labels": {"en": {"value": LABELS[q]}}} for q in ids if q in LABELS}}
            return {"entities": {q: WORLD[q] for q in ids if q in WORLD}}
        with open(os.path.join(cf, FOLDER, "wikidata-properties.json"), "w") as f:
            json.dump({"read": time.time(), "props": {"P31": ["WikibaseItem", "instance of"], "P569": ["Time", "date of birth"],
                                                      "P106": ["WikibaseItem", "occupation"]}}, f)
        real_fetch, real_hot, off_was, gap_was = HOT_FETCH, dict(HOT), os.environ.get("QB_OFFLINE"), WikidataHot.GAP_S
        try:
            globals()["HOT_FETCH"] = fake_wd
            os.environ["QB_OFFLINE"] = "1"
            WikidataHot.GAP_S = 0
            HOT["people-sports"] = ("People — sport", 100, ("P106=Q10871364", "P106=Q3665646"))
            hot_parts = WikidataHot("people-sports").parts()
            rh = run_dataset(cf, "hot-people-sports")
            dbh = sqlite3.connect(shard_path(cf, "hot-people-sports"))
            hf = {(a, p_, o) for a, p_, o in dbh.execute("SELECT f.s, pr.name, f.o FROM facts f JOIN predicates pr ON pr.id = f.p")}
            dbh.close()
            ok("1.40 hot lattice: the best-known items of each kind are asked for by rank (the top 50 of every kind before the next 50 of any) "
               "and each one's whole record is read, in the dump lanes' own form — with what it IS (description) and its other names",
               rh["state"] == "done" and [n.split(" ", 1)[1] for n, _u in hot_parts] == [
                   "P106=Q10871364 rank 00001-00050", "P106=Q3665646 rank 00001-00050", "P106=Q10871364 rank 00051-00100", "P106=Q3665646 rank 00051-00100"]
               and {("Babe Ruth (Q213812)", "date of birth", "1895-02-06"), ("Babe Ruth (Q213812)", "occupation", "Q10871364"),
                    ("Babe Ruth (Q213812)", "instance of", "Q5"), ("Babe Ruth (Q213812)", "description", "American baseball player (1895–1948)"),
                    ("Babe Ruth (Q213812)", "also known as", "The Babe")} <= hf, (rh, hot_parts[:2], sorted(hf)))
            ok("1.40 hot lattice: how well known each item is (Wikipedias with an article) and the names of the things it points to are kept",
               wd_fame(cf, [213812, 99]) == {213812: 120} and wd_labels(cf, [5, 10871364]) == {5: "human", 10871364: "baseball player"}
               and wd_alias(cf, "the babe") == [213812], (wd_fame(cf, [213812]), wd_labels(cf, [5, 10871364]), wd_alias(cf, "the babe")))
            # the demand agent: asked and not found -> fetched; and it learns which lattice the question landed in
            d0 = demand_note(cf, "Ed Sullivan", "Who is Ed Sullivan?", "no record")
            demand_note(cf, "Babe Ruth", "Who was Babe Ruth?", "only a baseball card")
            demand_note(cf, "Ed Sullivan")
            demand_note(cf, "Dodgers", "What are the Dodgers?")
            rd = run_dataset(cf, "hot-demand")
            dq = {r_["subject"]: r_ for r_ in demand_list(cf)}
            fe = find_entities(cf, "ed sullivan")
            ok("1.40 demand agent: a subject that was asked and not found is fetched by name within minutes (looked at every 2 minutes), its "
               "record is then in the store, and the agent learns which lattice the question landed in (that lattice is harvested first)",
               d0["queued"] and rd["state"] == "done" and dq["Ed Sullivan"]["n"] == 2 and dq["Ed Sullivan"].get("done") and dq["Ed Sullivan"]["found"] == 1
               and [e_["subject"] for e_ in fe["entities"]] == ["Ed Sullivan (Q83807)"] and demand_learned(cf).get("people-entertainment") == 1
               and next_try({"dataset": "hot-demand", "state": "done"}, 0) == 120, (rd, dq, fe["entities"], demand_learned(cf)))
            import qbkeystone as _ks
            order_ = _ks.order(["wikidata-dump-1", "hot-places", "usgs-gnis", "hot-people-entertainment", "hot-demand"], cf)
            ok("1.40: the demand agent and the hot lattices start before everything else, the lattice people's questions land in first",
               order_[:3] == ["hot-demand", "hot-people-entertainment", "hot-places"], order_)
            # 1.41 what people read: Wikipedia's most-read articles, their views added up over the months sampled
            real_vf, real_vm = VIEWS_FETCH, views_months
            try:
                globals()["VIEWS_FETCH"] = lambda y_, m_: [("Babe_Ruth", 500000), ("Some_Article_Wikidata_Lacks", 400000)]
                globals()["views_months"] = lambda now=None, recent=24: [(2026, 10), (2026, 9)]
                mr_parts = WikidataMostRead().parts()
                rm = run_dataset(cf, "hot-most-read")
            finally:
                globals()["VIEWS_FETCH"], globals()["views_months"] = real_vf, real_vm
            vm_ = real_vm(time.mktime((2026, 11, 12, 0, 0, 0, 0, 0, 0)))
            ok("1.41 what people read: the most-read Wikipedia articles month by month (every month of two years, then one a quarter back "
               "to 2015, so lasting subjects outweigh a week in the news), each one's whole record read and its views added up",
               rm["state"] == "done" and len(mr_parts) == 40 and mr_parts[0][0] == "most read 2026-10 rank 0001-0050" and mr_parts[1][0] == "most read 2026-09 rank 0001-0050"
               and wd_views(cf, [213812, 99]) == {213812: 1000000} and vm_[0] == (2026, 10) and len(vm_[:24]) == 24 and vm_[24] == (2024, 10)
               and vm_[-1] == (2015, 7) and all(m_ in (1, 4, 7, 10) for _y, m_ in vm_[24:]), (rm, mr_parts[:2], wd_views(cf, [213812]), vm_[22:27]))
            ok("1.41: page-view articles that are not subjects (the main page, search, project pages) are left out, and the most-read "
               "lattice starts right after the demand agent", "Main_Page".startswith(NOT_ARTICLES) and "Special:Search".startswith(NOT_ARTICLES)
               and not "Babe_Ruth".startswith(NOT_ARTICLES) and _ks.order(["hot-places", "wikidata-dump-1", "hot-most-read", "hot-demand"], cf)[:2]
               == ["hot-demand", "hot-most-read"])
            # 1.42 complete domains: everyone in a domain, the best known first; a wrong code is left out; trouble loses nobody
            E_ = "<http://www.wikidata.org/entity/Q%d>"
            dq_ = []

            def fake_q(sparql):
                dq_.append(sparql)
                if "rdfs:label" in sparql:
                    return [[E_ % 947873, '"television presenter"@en'], [E_ % 270389, '"something else entirely"@en']]
                if "P279*" in sparql:
                    return [[E_ % 947873], [E_ % 555]]
                if "sitelinks" in sparql:
                    if "Q555" in sparql:
                        raise OSError("the query service timed out")       # with the other kind, and alone
                    return [[E_ % 83807, "40"], [E_ % 213812, '"120"^^<http://www.w3.org/2001/XMLSchema#integer>']]
                return [[E_ % 99]]                                         # the plain list of the kind that kept failing
            real_dq, real_dom, pause_was = DOMAIN_QUERY, dict(DOMAINS), DOMAIN_PAUSE_S
            try:
                globals()["DOMAIN_QUERY"], globals()["DOMAIN_PAUSE_S"] = fake_q, 0
                DOMAINS["tv"] = (1, "Every television presenter", (("P106", "Q947873", "television presenter", True), ("P106", "Q270389", "news presenter", False)))
                dd = domain_discover("tv")
                ra = run_dataset(cf, "hot-all-tv")
                dba = sqlite3.connect(shard_path(cf, "hot-all-tv"))
                subj_ = {a for a, in dba.execute("SELECT DISTINCT s FROM facts")}
                dba.close()
                rep_ = next(d_ for d_ in domains_report(cf) if d_["name"] == "tv")
                ord_ = _ks.order(["hot-all-key-professions", "wikidata-dump-1", "hot-all-actors", "hot-places", "hot-demand"], cf)
            finally:
                globals()["DOMAIN_QUERY"], globals()["DOMAIN_PAUSE_S"] = real_dq, pause_was
                DOMAINS.clear(); DOMAINS.update(real_dom)
                for ext in ("", "-wal", "-shm", ".labels", ".labels-wal", ".labels-shm", ".progress"):
                    if os.path.exists(shard_path(cf, "hot-all-tv") + ext):
                        os.remove(shard_path(cf, "hot-all-tv") + ext)
                if os.path.exists(domain_path(cf, "tv")):
                    os.remove(domain_path(cf, "tv"))
            ok("1.42 complete domain: EVERYONE with the occupation and its narrower kinds is listed, the best known first; a kind the query "
               "service fails on is asked for again on its own, then without fame — nobody is dropped; a code whose label no longer matches is "
               "left out and reported", dd["ids"] == [213812, 83807, 99] and dd["people"] == 3
               and [(r_["item"], r_["used"]) for r_ in dd["roots"]] == [("Q947873", True), ("Q270389", False)] and dd["roots"][0]["kinds"] == 2
               and "left out" in dd["roots"][1]["why"] and sum(1 for q_ in dq_ if "sitelinks" in q_) >= 3, (dd, len(dq_)))
            ok("1.42 complete domain: each person's whole record is then read, in batches, exactly as the lanes write it; the page can say "
               "who is in each domain; tier 1 starts after the hot lattices, tier 2 after tier 1, the dump lanes after all of them",
               ra["state"] == "done" and {"Babe Ruth (Q213812)", "Ed Sullivan (Q83807)", "Babe Ruth (Q99)"} <= subj_ and rep_["people"] == 3
               and rep_["key"] == "hot-all-tv" and ord_ == ["hot-demand", "hot-places", "hot-all-actors", "hot-all-key-professions", "wikidata-dump-1"],
               (ra, subj_, rep_, ord_))
            ok("1.42: the domains asked for are there, in tiers — tier 1 the people who face the public", {n_ for n_, d_ in DOMAINS.items() if d_[0] == 1}
               == {"actors", "authors", "television-radio", "music", "models", "speakers", "officials", "athletes"} and DOMAINS["key-professions"][0] == 2
               and DOMAINS["arts-faith-scholarship"][0] == 3 and all(len(r_) == 4 for d_ in DOMAINS.values() for r_ in d_[2]))
            # 1.43 icons: the best known of each type, weighted for the user's culture; a kind too large to rank is left out, said
            iq_ = []

            def fake_i(sparql):
                iq_.append(sparql)
                if "rdfs:label" in sparql:
                    return [[E_ % 13027888, '"baseball team"@en'], [E_ % 11424, '"film"@en']]
                if "wdt:P17 wd:Q30" in sparql:
                    return [[E_ % 2]]                                      # the one that is at home in the United States
                if "sitelinks" in sparql:
                    if "Q11424" in sparql:
                        raise OSError("the query service timed out")
                    return [[E_ % 1, "80"], [E_ % 2, "60"], [E_ % 3, "50"]]
                return [[E_ % 7]]
            real_ic = dict(ICONS)
            try:
                ICONS["t"] = (0, "Teams", (("P31", "Q13027888", "baseball team", False, 2, "", 0), ("P31", "Q11424", "film", False, 5, "", 25)))
                di = domain_discover("t", fake_i, 0, ICONS)
            finally:
                ICONS.clear(); ICONS.update(real_ic)
            ok("1.43 icons: the best known of each type by fame, weighted for the user's culture (an American team with 60 Wikipedias "
               "comes before a foreign one with 80), cut to the top of each type; a kind too large to rank is left out and reported, never "
               "harvested unranked", di["ids"] == [2, 1] and di["culture"] == "Q30" and di["roots"][0]["people"] == 2 and di["roots"][1]["people"] == 0
               and "too large to rank" in di["roots"][1]["why"] and any("FILTER(?n >= 25)" in q_ for q_ in iq_)
               and not any(q_.startswith("SELECT ?p WHERE") for q_ in iq_), (di, len(iq_)))
            ok("1.43 icons: a set takes the best 50 of each of its types in turn, the types in their listed order — every major-league "
               "team (listed first) before the 51st-best-known club of another sport; nothing twice",
               interleave([[1, 2, 3], [4, 2, 5, 6, 7]], 2) == [1, 2, 4, 3, 5, 6, 7] and interleave([]) == []
               and ICONS["sports-teams"][2][0][2] == "Major League Baseball")
            ok("1.43 icons: the sets asked for — teams, athletes, music, screen, leaders, places, culture — start before everything but the "
               "demand agent, then what people read, the lattices, and the complete domains tier by tier",
               set(ICONS) == {"sports-teams", "athletes", "music", "screen", "leaders-writers", "places-landmarks", "culture-events",
                              "faith-thought-science", "arts-business-works", "government-leadership", "wealth-technology", "news-media"}
               and set(ICON_SET_CATEGORY) == set(ICONS) and all(v in ICON_CATEGORIES for v in list(ICON_CATEGORY.values()) + list(ICON_SET_CATEGORY.values()))
               and all(icon_categories()[c] for c in ICON_CATEGORIES) and "head of state" in icon_categories()["Government and leadership"]
               and "journalist" in icon_categories()["News and media"] and "people whose fortune is on record" in icon_categories()["Business and wealth"]
               and "human biblical figure" in icon_categories()["Religion"] and "writer" in icon_categories()["Literature"]
               and _ks.order(["hot-all-actors", "hot-places", "hot-most-read", "wikidata-dump-1", "hot-top-sports-teams", "hot-demand"], cf)
               == ["hot-demand", "hot-top-sports-teams", "hot-most-read", "hot-places", "hot-all-actors", "wikidata-dump-1"]
               and list(catalog())[:3] == ["hot-demand", "hot-seed", "hot-top-sports-teams"])
            # 1.43 part of a name: "Dodgers" is the Los Angeles Dodgers, not an obscure thing called just "Dodgers"
            fd = find_entities(cf, "dodgers")
            jd = _sense.answer_for("What are the Dodgers", "Dodgers", fd["entities"], fd["facts"])
            fp_ = find_entities(cf, "angeles dodgers")
            ldb = sqlite3.connect(shard_path(cf, "hot-demand") + ".labels")
            n_before = ldb.execute("SELECT count(*) FROM names").fetchone()[0]
            ldb.execute("DELETE FROM names"); ldb.execute("PRAGMA user_version = 0"); ldb.commit(); ldb.close()
            gone_ = find_entities(cf, "angeles dodgers")["entities"]
            back_ = index_names(cf)
            ok("1.43: asked for by part of its name, the well-known thing is found (every word asked must be in its name) and preferred "
               "to an obscure thing with exactly that name — and the demand agent remembers the name it was asked under",
               {e_["subject"]: (e_["exact"], e_["by_other_name"] or e_["by_part_of_name"]) for e_ in fd["entities"]}
               == {"Dodgers (Q777001)": (True, False), "Los Angeles Dodgers (Q334634)": (False, True)}
               and jd["entity"]["subject"] == "Los Angeles Dodgers (Q334634)" and jd["said"].startswith("Los Angeles Dodgers — baseball team in Los Angeles")
               and "best-known thing by that name" in jd["entity"]["why"] and [e_["subject"] for e_ in fp_["entities"]] == ["Los Angeles Dodgers (Q334634)"]
               and fp_["entities"][0]["by_part_of_name"] and name_words("The Los Angeles Dodgers") == {"los", "angeles", "dodgers"},
               (fd["entities"], jd["said"], jd["entity"]["why"], fp_["entities"]))
            ok("1.43: records read before the word index existed are put into it once (from their fame, labels and other names)",
               n_before > 0 and gone_ == [] and back_ >= 3 and [e_["subject"] for e_ in find_entities(cf, "angeles dodgers")["entities"]]
               == ["Los Angeles Dodgers (Q334634)"] and index_names(cf) == 0, (n_before, gone_, back_))
            # 1.44 the hot list at once: the icons list shipped with QueryBook is read straight away, no listing first
            import tempfile as _tf2
            seed_was = SEED_FILE
            try:
                sf_ = os.path.join(_tf2.mkdtemp(), "hot_seed.json")
                with open(sf_, "w") as f:
                    json.dump({"made": "2026-11-13", "ids": [1299, 83807]}, f)
                globals()["SEED_FILE"] = sf_
                seed_parts = WikidataSeed().parts()
                rs_ = run_dataset(cf, "hot-seed")
                fbt = find_entities(cf, "Beatles")                  # as the Ask box asks: "Who are the Beatles?" -> "Beatles"
                jbt = _sense.answer_for("Who are the Beatles?", "Beatles", fbt["entities"], fbt["facts"])
            finally:
                globals()["SEED_FILE"] = seed_was
                for ext in ("", "-wal", "-shm", ".labels", ".labels-wal", ".labels-shm", ".progress"):
                    if os.path.exists(shard_path(cf, "hot-seed") + ext):
                        os.remove(shard_path(cf, "hot-seed") + ext)
            ok("1.44: the icons list shipped inside QueryBook is read at once (no half hour of asking Wikidata who is famous first), and "
               "it is the first thing started after the demand agent", rs_["state"] == "done"
               and seed_parts == [("seed 2026-11-13 icons 0000001-0000002 of 0000002", "domain#0")]
               and _ks.order(["hot-top-music", "wikidata-dump-1", "hot-seed", "hot-demand"], cf)[:3] == ["hot-demand", "hot-seed", "hot-top-music"]
               and list(catalog())[:2] == ["hot-demand", "hot-seed"] and hot_first("hot-seed") and not hot_first("hot-demand")
               and not hot_first("hot-all-actors") and not hot_first("wikidata-dump-1"), (rs_, seed_parts))
            # 1.44 the records service refuses (HTTP 429): the same records are read through the query service
            hot_was, wdqs_was, pause_was, asked_w = HOT_FETCH, WDQS_FETCH, WDQS_PAUSE_S, []
            ent_was, epause_was = ENTITY_FETCH, ENTITY_PAUSE_S

            def _no(params):
                raise urllib.error.HTTPError("https://www.wikidata.org/w/api.php", 429, "Too Many Requests", {}, None)

            def _wdqs(sparql):
                asked_w.append(sparql)
                u = lambda q: {"type": "uri", "value": WD_E + q}
                if "ORDER BY DESC(?n)" in sparql:
                    return [{"s": u("Q1299"), "n": {"value": "246"}}] if '"The Beatles"@en' in sparql else []
                if "wikibase:sitelinks ?n" in sparql:
                    return [{"s": u("Q1299"), "l": {"value": "The Beatles"}, "d": {"value": "English rock band"}, "n": {"value": "246"}}]
                if "skos:altLabel ?a" in sparql:
                    return [{"s": u("Q1299"), "a": {"value": "Fab Four"}}]
                if "BestRank" in sparql:
                    return [{"s": u("Q1299"), "pd": {"value": WD_D + "P571"}, "t": {"value": "1960-01-01T00:00:00Z"}, "prec": {"value": "9"}}]
                if "STRSTARTS" in sparql:
                    return [{"s": u("Q1299"), "p": {"value": WD_D + "P31"}, "o": u("Q215380")},
                            {"s": u("Q1299"), "p": {"value": WD_D + "P571"}, "o": {"type": "literal", "value": "1960-01-01T00:00:00Z", "datatype": "http://www.w3.org/2001/XMLSchema#dateTime"}},
                            {"s": u("Q1299"), "p": {"value": WD_D + "P856"}, "o": {"type": "uri", "value": "https://www.thebeatles.com/"}}]
                if "rdfs:label ?l" in sparql:
                    return [{"s": u("Q215380"), "l": {"value": "musical group"}}]
                return []

            try:
                sf_ = os.path.join(_tf2.mkdtemp(), "hot_seed.json")
                with open(sf_, "w") as f:
                    json.dump({"made": "2026-11-13", "ids": [1299]}, f)
                globals().update(SEED_FILE=sf_, HOT_FETCH=_no, WDQS_FETCH=_wdqs, WDQS_PAUSE_S=0, ENTITY_FETCH=lambda q: _no({}), ENTITY_PAUSE_S=0)
                rw_ = run_dataset(cf, "hot-seed")
                refused_ = api_refused(cf)
                fw_ = find_entities(cf, "Beatles")
                ew_ = wdqs_entities(["Q1299"])["Q1299"]
                found_w = wdqs_find("Beatles")
                calls = {"n": 0}

                def _flaky(sparql):
                    calls["n"] += 1
                    if calls["n"] == 1:
                        raise urllib.error.HTTPError("https://query.wikidata.org/sparql", 502, "Bad Gateway", {}, None)
                    return []
                globals()["WDQS_FETCH"] = _flaky
                flaky_ = wdqs_ask("SELECT 1")
                # the per-record address answers: whole records from it; one it refuses comes through the query service
                big = {"n": 0}

                def _cut(sparql):                        # a batch too large is cut off mid-answer: halved until it fits
                    big["n"] += 1
                    if sparql.count("wd:Q") > 1:
                        raise ValueError("cut off")
                    return _wdqs(sparql)
                globals().update(WDQS_FETCH=_cut, ENTITY_FETCH=lambda q: {"type": "item", "id": q, "labels": {"en": {"value": "Thing " + q}}, "claims": {}}
                                 if q != "Q1299" else _no({}))
                ed_ = entitydata_entities(["Q5", "Q1299", "Q6"])
                mix_, st_ = WikidataSeed(), {}
                mix_.folder = cf
                got_ = mix_._entities(["Q5", "Q1299"], st_)
                halved_ = wdqs_entities(["Q1299", "Q7"])
            finally:
                globals().update(SEED_FILE=seed_was, HOT_FETCH=hot_was, WDQS_FETCH=wdqs_was, WDQS_PAUSE_S=pause_was, ENTITY_FETCH=ent_was, ENTITY_PAUSE_S=epause_was)
                for ext in ("", "-wal", "-shm", ".labels", ".labels-wal", ".labels-shm", ".progress"):
                    if os.path.exists(shard_path(cf, "hot-seed") + ext):
                        os.remove(shard_path(cf, "hot-seed") + ext)
                if os.path.exists(os.path.join(cf, FOLDER, API_REFUSED_NAME)):
                    os.remove(os.path.join(cf, FOLDER, API_REFUSED_NAME))
            ok("1.44: Wikidata's records service refuses this computer (HTTP 429) — the hot list reads the same records through the query "
               "service instead of waiting: the band is in the store with its kind, its founding year at its own precision, its other "
               "name and its fame; the refusal is remembered so no agent asks again for a quarter of an hour; a passing 502 is retried",
               rw_["state"] == "done" and rw_["new"] > 0 and refused_ and not api_refused(cf)
               and [e_["subject"] for e_ in fw_["entities"]] == ["The Beatles (Q1299)"] and fw_["entities"][0]["fame"] == 246
               and any(f_["predicate"] == "instance of" and "musical group" in f_["object"] for f_ in fw_["facts"])
               and any(f_["predicate"] == "inception" and f_["object"] == "1960" for f_ in fw_["facts"])
               and [c["mainsnak"]["datavalue"]["type"] for c in ew_["claims"]["P571"]] == ["time"] and "P856" not in ew_["claims"]
               and found_w == ["Q1299"] and flaky_ == [] and calls["n"] == 2, (rw_, refused_, fw_["entities"], [f_ for f_ in fw_["facts"]][:6], found_w, calls))
            ok("1.45: the fast second route — whole records from Wikidata's per-record address, two at a time; a record it refuses is "
               "read through the query service; a batch the query service cuts off is halved, never lost whole",
               sorted(ed_) == ["Q5", "Q6"] and sorted(got_) == ["Q1299", "Q5"] and got_["Q1299"]["labels"]["en"]["value"] == "The Beatles"
               and st_["_via"] == "per-record address and query service" and list(halved_) == ["Q1299"], (sorted(ed_), sorted(got_), st_, list(halved_)))
            # 1.45 "Who is Ed Sullivan?" answered with Boris Vian (pen name Vernon Sullivan, better known than the host)
            def _rec(q, label, desc, wikis, aliases, job):
                return {"type": "item", "id": q, "labels": {"en": {"value": label}}, "descriptions": {"en": {"value": desc}},
                        "aliases": {"en": [{"value": a} for a in aliases]}, "sitelinks": {"w%d" % i: {} for i in range(wikis)},
                        "claims": {"P31": [{"rank": "normal", "mainsnak": {"datavalue": {"type": "wikibase-entityid", "value": {"id": "Q5"}}}}],
                                   "P106": [{"rank": "normal", "mainsnak": {"datavalue": {"type": "wikibase-entityid", "value": {"id": job}}}}]}}
            people_ = {"Q83807": _rec("Q83807", "Ed Sullivan", "American television host (1901-1974)", 46, ["Edward Vincent Sullivan"], "Q947873"),
                       "Q156213": _rec("Q156213", "Boris Vian", "French writer (1920-1959)", 70, ["Vernon Sullivan", "Bison Ravi"], "Q36180")}
            try:
                sf_ = os.path.join(_tf2.mkdtemp(), "hot_seed.json")
                with open(sf_, "w") as f:
                    json.dump({"made": "2026-11-13", "ids": [83807, 156213]}, f)
                globals().update(SEED_FILE=sf_, HOT_FETCH=_no, ENTITY_FETCH=lambda q: people_.get(q), ENTITY_PAUSE_S=0,
                                 WDQS_FETCH=lambda sparql: [{"s": {"value": WD_E + "Q5"}, "l": {"value": "human"}}] if "rdfs:label ?l" in sparql else [])
                re_ = run_dataset(cf, "hot-seed")
                fes = find_entities(cf, "Ed Sullivan")
                jes = _sense.answer_for("who is Ed Sullivan?", "Ed Sullivan", fes["entities"], fes["facts"])
                fsu = find_entities(cf, "Sullivan")
                fvs = find_entities(cf, "Vernon Sullivan")
            finally:
                globals().update(SEED_FILE=seed_was, HOT_FETCH=hot_was, WDQS_FETCH=wdqs_was, ENTITY_FETCH=ent_was, ENTITY_PAUSE_S=epause_was)
                for ext in ("", "-wal", "-shm", ".labels", ".labels-wal", ".labels-shm", ".progress"):
                    if os.path.exists(shard_path(cf, "hot-seed") + ext):
                        os.remove(shard_path(cf, "hot-seed") + ext)
                if os.path.exists(os.path.join(cf, FOLDER, API_REFUSED_NAME)):
                    os.remove(os.path.join(cf, FOLDER, API_REFUSED_NAME))
            ok("1.45: “Who is Ed Sullivan?” was answered with Boris Vian — “Ed” is too short for the word index, so “Sullivan” alone "
               "matched his pen name Vernon Sullivan, and he is better known. Now one name of the item must hold EVERY word asked, and a "
               "full name matched exactly outweighs fame: Ed Sullivan is Ed Sullivan; “Sullivan” and “Vernon Sullivan” still find Vian",
               re_["state"] == "done" and [e_["subject"] for e_ in fes["entities"]] == ["Ed Sullivan (Q83807)"]
               and jes["entity"]["subject"] == "Ed Sullivan (Q83807)" and "Boris" not in jes["said"]
               and "Boris Vian (Q156213)" in [e_["subject"] for e_ in fsu["entities"]]
               and [e_["subject"] for e_ in fvs["entities"]] == ["Boris Vian (Q156213)"], (re_, fes["entities"], jes.get("said"), fsu["entities"], fvs["entities"]))
            # 1.46 the network of nets: an icon's circle, then that circle's circle
            def _tie(e, pid, q):
                e["claims"].setdefault(pid, []).append({"rank": "normal", "mainsnak": {"datavalue": {"type": "wikibase-entityid", "value": {"id": q}}}})
                return e
            net_ = {"Q1299": _tie(_tie(_rec("Q1299", "The Beatles", "English rock band", 246, [], "Q215380"), "P527", "Q1203"), "P740", "Q24826"),
                    "Q1203": _tie(_rec("Q1203", "John Lennon", "English musician (1940-1980)", 230, [], "Q177220"), "P26", "Q117012"),
                    "Q24826": _rec("Q24826", "Liverpool", "city in England", 190, [], "Q515"),
                    "Q117012": _tie(_rec("Q117012", "Yoko Ono", "Japanese artist", 120, [], "Q483501"), "P40", "Q311238"),
                    "Q311238": _tie(_rec("Q311238", "Sean Lennon", "American musician", 50, [], "Q177220"), "P26", "Q999999")}
            asked_net = []

            def _net(q):
                asked_net.append(q)
                return net_.get(q)
            try:
                sf_ = os.path.join(_tf2.mkdtemp(), "hot_seed.json")
                with open(sf_, "w") as f:
                    json.dump({"made": "2026-11-13", "ids": [1299]}, f)
                globals().update(SEED_FILE=sf_, HOT_FETCH=_no, ENTITY_FETCH=_net, ENTITY_PAUSE_S=0, WDQS_FETCH=lambda sparql: [])
                run_dataset(cf, "hot-seed")
                w1 = circle_wave(cf)
                c1 = run_dataset(cf, "hot-circle")
                w2 = circle_wave(cf)
                c2 = run_dataset(cf, "hot-circle")
                c3 = run_dataset(cf, "hot-circle")
                w4 = circle_wave(cf)
                fjl, fyo, fsl = find_entities(cf, "John Lennon"), find_entities(cf, "Yoko Ono"), find_entities(cf, "Sean Lennon")
            finally:
                globals().update(SEED_FILE=seed_was, HOT_FETCH=hot_was, WDQS_FETCH=wdqs_was, ENTITY_FETCH=ent_was, ENTITY_PAUSE_S=epause_was)
                for k_ in ("hot-seed", "hot-circle"):
                    for ext in ("", "-wal", "-shm", ".labels", ".labels-wal", ".labels-shm", ".progress"):
                        if os.path.exists(shard_path(cf, k_) + ext):
                            os.remove(shard_path(cf, k_) + ext)
                for f_ in (os.path.join(cf, FOLDER, API_REFUSED_NAME), domain_path(cf, "circle", "circle")):
                    if os.path.exists(f_):
                        os.remove(f_)
            ok("1.46: the network of nets — the Beatles are read; John Lennon (a member) and Liverpool (where they formed) are their "
               "circle and are read next; Yoko Ono (his wife) is the circle's circle and is read after; Sean Lennon is the third ring; "
               "his own ties are beyond the third ring and are not followed. Nothing is listed twice. The net runs beside the other "
               "harvests (it has no end, so nothing waits for it) and starts right after the icons",
               sorted(w1["ids"]) == [1203, 24826] and set(w1["rings"].values()) == {1} and c1["state"] == "done" and c1["new"] > 0
               and w2["ids"] == [117012] and w2["rings"] == {117012: 2} and c2["state"] == "done"
               and [e_["subject"] for e_ in fjl["entities"]] == ["John Lennon (Q1203)"] and [e_["subject"] for e_ in fyo["entities"]] == ["Yoko Ono (Q117012)"]
               and [e_["subject"] for e_ in fsl["entities"]] == ["Sean Lennon (Q311238)"] and w4["ids"] == [] and "Q999999" not in asked_net
               and asked_net.count("Q1203") == 1 and not hot_first("hot-circle")
               and next_try({"dataset": "hot-circle", "state": "done"}, 0) == CIRCLE_AGAIN_S
               and _ks.order(["hot-most-read", "hot-circle", "hot-top-music", "hot-seed"], cf) == ["hot-seed", "hot-top-music", "hot-circle", "hot-most-read"],
               (w1, c1, w2, c2, c3, w4, asked_net, fjl["entities"], fyo["entities"], fsl["entities"]))
            ok("1.44: “Who are the Beatles?” — the Ask box drops “the”, the record is “The Beatles”: every name is tried with and without "
               "its article, and the band is found and said to be a band", name_forms("Beatles")[:2] == ["Beatles", "The Beatles"]
               and "Beatles" in name_forms("the beatles") and "The Beatles" in name_forms("the beatles")
               and [e_["subject"] for e_ in fbt["entities"]] == ["The Beatles (Q1299)"] and fbt["entities"][0]["exact"]
               and jbt["entity"]["kind"] == "organization" and jbt["said"] == "The Beatles — English rock band." and not jbt["missing"],
               (name_forms("Beatles"), fbt["entities"], jbt["said"]))
            # WHO is meant: the man and the card are both in the store now
            fb = find_entities(cf, "babe ruth")                 # typed in lower case
            jb = _sense.answer_for("Who was Babe Ruth?", "Babe Ruth", fb["entities"], fb["facts"])
            fa = find_entities(cf, "The Babe")
            ok("1.40: every thing with the name is found however it was typed, the best known first (fame, then how much is recorded), with "
               "ALL its facts and their values named — and by its other names too",
               [(e_["subject"], e_["fame"], e_["views"]) for e_ in fb["entities"]] == [("Babe Ruth (Q213812)", 120, 1000000), ("Babe Ruth (Q99)", None, None)]
               and {"human (Q5)", "baseball player (Q10871364)"} <= {f_["object"] for f_ in fb["facts"]}
               and fa["entities"] and fa["entities"][0]["subject"] == "Babe Ruth (Q213812)" and fa["entities"][0]["by_other_name"], (fb["entities"], fa["entities"]))
            ok("1.40 a grasp of reality: Babe Ruth is a person, not the baseball card of the same name — the answer says who he was",
               jb["entity"]["subject"] == "Babe Ruth (Q213812)" and jb["entity"]["kind"] == "human" and not jb["missing"]
               and jb["said"].startswith("Babe Ruth (born 1895) — American baseball player") and [r_["kind"] for r_ in jb["entity"]["ranked"]] == ["human", "depiction"] and "with an article in 120 Wikipedias" in jb["entity"]["why"] and "most-read" in jb["entity"]["why"],
               (jb["said"], jb["entity"]))
        finally:
            globals()["HOT_FETCH"] = real_fetch
            HOT.clear(); HOT.update(real_hot)
            WikidataHot.GAP_S = gap_was
            if off_was is None:
                os.environ.pop("QB_OFFLINE", None)
            else:
                os.environ["QB_OFFLINE"] = off_was
            os.remove(os.path.join(cf, FOLDER, "wikidata-properties.json"))
            for key_ in ("hot-people-sports", "hot-demand", "hot-most-read"):   # the tests that follow count the stores they made themselves
                for ext in ("", "-wal", "-shm", ".labels", ".labels-wal", ".labels-shm", ".progress"):
                    if os.path.exists(shard_path(cf, key_) + ext):
                        os.remove(shard_path(cf, key_) + ext)
            for f_ in (DEMAND_NAME, LEARNED_NAME):
                if os.path.exists(os.path.join(cf, FOLDER, f_)):
                    os.remove(os.path.join(cf, FOLDER, f_))
        # 1.40: how much of the dump was EVER read, the never-read parts first, an edition finished before the next
        real_lp = _lane_parts
        try:
            globals()["_lane_parts"] = lambda c_: [(1, "2026-10-28", 1, 146, True), (1, "2026-11-04", 1, 147, True), (1, "2026-11-04", 17, 147, True),
                                                   (2, "2026-11-04", 2, 147, False), (1, "2026-11-11", 1, 147, False)]
            cov_ = dump_coverage(cf)
            first_ = unread_first([i for i in range(147) if i % 16 == 0], 147, dump_positions_read(cf))
            ep_ = edition_progress(cf, "2026-11-04")
        finally:
            globals()["_lane_parts"] = real_lp
        ok("1.40: the engine knows how much of Wikidata it has EVER read (here 2 of 147 parts across three editions, none finished — each "
           "new weekly edition had sent every lane back to part 1), and a lane now reads its never-read parts first",
           cov_["read"] == 2 and cov_["parts"] == 147 and cov_["current"] == "2026-11-11" and "none was finished" in cov_["text"]
           and first_[:3] == [32, 48, 64] and first_[-2:] == [0, 16] and ep_ == {"edition": "2026-11-04", "done": 2, "total": 147}, (cov_, first_, ep_))
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
    out += _supervisor_tests()
    return out


def _supervisor_tests():
    """the never-stop supervisor, with scripted agents (threads standing in for processes) and a moving clock"""
    import shutil, tempfile, threading
    out = []
    ok = lambda n, c, d="": out.append((n, bool(c), d))
    cf = tempfile.mkdtemp()
    script = {}                                     # dataset → what its agent does: fail / stall / silent / done / work

    class P:
        n = 1000

        def __init__(self, target, args, daemon=False):
            self.args, self.ended, self.exitcode = args, threading.Event(), None
            P.n += 1
            self.pid = P.n
            ALL[self.pid] = self

        def start(self):
            cf_, key, _, rp = self.args
            alive = os.path.join(_alive_dir(cf_), key + ".json")
            how = script[key]
            if how in ("fail", "done"):
                with open(rp, "w") as f:
                    json.dump({"dataset": key, "state": "paused" if how == "fail" else "done", "why": "test", "new": 0}, f)
                self.ended.set()
                self.exitcode = 0
            else:                                       # stall: alive, same progress · silent: no heartbeat · work: moving
                if how != "silent":
                    with open(alive, "w") as f:
                        json.dump({"at": CLOCK[0], "pid": self.pid, "meter": 5, "rows": 5, "waiting": None}, f)

        def is_alive(self):
            if script.get(self.args[1]) == "work" and not self.ended.is_set():
                with open(os.path.join(_alive_dir(self.args[0]), self.args[1] + ".json"), "w") as f:
                    json.dump({"at": CLOCK[0], "pid": self.pid, "meter": CLOCK[0], "rows": CLOCK[0], "waiting": None}, f)
            elif script.get(self.args[1]) == "stall" and not self.ended.is_set():
                with open(os.path.join(_alive_dir(self.args[0]), self.args[1] + ".json"), "w") as f:
                    json.dump({"at": CLOCK[0], "pid": self.pid, "meter": 5, "rows": 5, "waiting": None}, f)
            elif script.get(self.args[1]) == "filing" and not self.ended.is_set():
                with open(os.path.join(_alive_dir(self.args[0]), self.args[1] + ".json"), "w") as f:
                    json.dump({"at": CLOCK[0], "pid": self.pid, "meter": 5, "rows": 5, "waiting": "filing 20,000,000 facts into the dataset"}, f)
            return not self.ended.is_set()

        def join(self, t=None):
            self.ended.wait(t)

    class MP:
        Process = P
    ALL, CLOCK = {}, [time.time()]

    def kill(pid):
        ALL[pid].exitcode = -9
        ALL[pid].ended.set()
    try:
        script.update({"a": "fail", "b": "stall", "c": "silent", "d": "work", "e": "done"})
        sup = Supervisor(cf, list(script), 5, mp=MP, kill=kill)
        sup.check(CLOCK[0])
        ok("supervisor: every dataset gets its own agent", sorted(sup.running) == ["b", "c", "d"] or len(sup.events) >= 5,
           [e["what"] + ":" + e["dataset"] for e in sup.events])
        CLOCK[0] += 5
        sup.check(CLOCK[0])
        ends = {e["dataset"]: e for e in sup.events if e["what"] == "ended"}
        ok("supervisor: a dataset that fails is tried again after a wait (1 min, then 2, 5, 10, 15 — never given up)",
           ends.get("a", {}).get("next_in_s") == BACKOFF_S[0] and "a" in sup.queue, ends.get("a"))
        ok("supervisor: a finished dataset is looked at again the next day (new editions)",
           ends.get("e", {}).get("next_in_s") == RECHECK_DONE_S, ends.get("e"))
        CLOCK[0] += SILENT_S + 5
        sup.check(CLOCK[0])
        ends = {e["dataset"]: e for e in sup.events if e["what"] == "ended"}
        ok("supervisor: an agent with no sign of life for 3 minutes is ended and restarted later",
           "c" in ends and "no sign of life" in ends["c"]["why"]
           and sum(1 for e in sup.events if e["what"] == "started" and e["dataset"] == "c") == 2, ends.get("c"))
        ok("supervisor: an agent that keeps moving is left alone", "d" in sup.running and "d" not in ends)
        CLOCK[0] += STALL_S + 5
        sup.check(CLOCK[0])
        ends = {e["dataset"]: e for e in sup.events if e["what"] == "ended"}
        ok("supervisor: an agent alive but making no progress for 15 minutes is ended and restarted later",
           "b" in ends and "no progress" in ends["b"]["why"] and "b" in sup.queue, ends.get("b"))
        ok("supervisor: the failing dataset was started again after its wait",
           sum(1 for e in sup.events if e["what"] == "started" and e["dataset"] == "a") >= 2)
        fails_before = sup.fails["a"]
        for _ in range(8):
            CLOCK[0] += 3700
            sup.check(CLOCK[0])
        ok("supervisor: repeated failures wait longer each time but never stop (15 minutes at most)",
           sup.fails["a"] > fails_before and "a" in sup.queue and sup.queue["a"] - time.time() <= BACKOFF_S[-1] + 1, sup.fails["a"])
        sup.stop_all(grace=0)
        ok("supervisor: Stop ends every agent and starts nothing new", not sup.running and not sup.queue)
        # 1.35: filing (waiting on purpose) is left alone past 15 minutes, but not for ever
        script["f"] = "filing"
        sup2 = Supervisor(cf, ["f"], 1, mp=MP, kill=kill)
        sup2.check(CLOCK[0])
        for _ in range(4):
            CLOCK[0] += STALL_S
            sup2.check(CLOCK[0])
        ok("1.35 supervisor: an agent filing for an hour (no new rows, but filing) is left alone",
           "f" in sup2.running and not any(e["what"] == "ended" for e in sup2.events), sup2.events[-2:])
        CLOCK[0] += WAIT_MAX_S
        sup2.check(CLOCK[0])
        CLOCK[0] += STALL_S + 5
        sup2.check(CLOCK[0])
        endf = [e for e in sup2.events if e["what"] == "ended" and e["dataset"] == "f"]
        ok("1.35 supervisor: …but waiting 6 hours without any progress at all is ended and restarted, with the reason",
           endf and "6 h without any progress" in endf[0]["why"] and "filing" in endf[0]["why"], endf)
        sup2.stop_all(grace=0)
        # 1.35: a dataset farmed out to another PC is not harvested here (and is handed over if it was running)
        import qbfarm
        script["g"] = "work"
        sup3 = Supervisor(cf, ["g"], 1, mp=MP, kill=kill)
        sup3.check(CLOCK[0])
        was = "g" in sup3.running
        qbfarm.assign(cf, "LAB-PC-2", "", "windows", ["g"], ["g"])
        CLOCK[0] += 61
        sup3.check(CLOCK[0])
        CLOCK[0] += 400
        sup3.check(CLOCK[0])
        endg = [e for e in sup3.events if e["what"] == "ended" and e["dataset"] == "g"]
        ok("1.35 supervisor: a dataset farmed out to another PC is handed over (ended here, facts kept) and not started again",
           was and "g" not in sup3.running and endg and "farmed out to LAB-PC-2" in endg[0]["why"]
           and sum(1 for e in sup3.events if e["what"] == "started" and e["dataset"] == "g") == 1, sup3.events[-3:])
        sup3.stop_all(grace=0)
        # 1.36: a dataset the fail-safe rested is ended here and not started again until its rest is over; others run
        script.update({"h": "work", "i": "work"})
        sup4 = Supervisor(cf, ["h", "i"], 1, mp=MP, kill=kill)
        sup4.check(CLOCK[0])
        first4 = sorted(sup4.running)
        rest(cf, ["h"], 3600, CLOCK[0])
        CLOCK[0] += 5
        sup4.check(CLOCK[0])
        during4 = sorted(sup4.running)
        endh = [e for e in sup4.events if e["what"] == "ended" and e["dataset"] == "h"]
        CLOCK[0] += 1800
        sup4.check(CLOCK[0])
        still4 = sorted(sup4.running)
        kill(sup4.running["i"]["proc"].pid)
        CLOCK[0] += 1900                                   # the rest is over: h may run again
        sup4.check(CLOCK[0]); CLOCK[0] += BACKOFF_S[-1] + 5; sup4.check(CLOCK[0])
        ok("1.36 supervisor: a rested dataset is ended (facts kept) and its place goes to the next one; it runs again after its rest",
           first4 == ["h"] and during4 == ["i"] and still4 == ["i"] and endh and "resting until" in endh[0]["why"]
           and "h" in sup4.running, (first4, during4, still4, sorted(sup4.running), endh[:1]))
        sup4.stop_all(grace=0)
        os.remove(os.path.join(cf, FOLDER, REST_NAME))
        # 1.38: a dataset having facts added back from another copy steps aside; every other dataset harvests meanwhile
        script.update({"j": "work", "l": "work"})
        sup5 = Supervisor(cf, ["j", "l"], 2, mp=MP, kill=kill)
        sup5.check(CLOCK[0])
        both5 = sorted(sup5.running)
        sup5.hold.add("j")
        CLOCK[0] += 5; sup5.check(CLOCK[0])
        held5 = sorted(sup5.running)
        endj = [e for e in sup5.events if e["what"] == "ended" and e["dataset"] == "j"]
        CLOCK[0] += 900; sup5.check(CLOCK[0])
        still5 = sorted(sup5.running)
        sup5.hold.discard("j")
        CLOCK[0] += 5; sup5.check(CLOCK[0])
        ok("1.38 supervisor: while facts are added back to one dataset from another copy, only that dataset waits — the others keep "
           "harvesting (before, nothing was harvested until every copy of every dataset had been merged); it returns right after",
           both5 == ["j", "l"] and held5 == ["l"] and still5 == ["l"] and endj and "added back" in endj[0]["why"]
           and sorted(sup5.running) == ["j", "l"], (both5, held5, still5, sorted(sup5.running), endj[:1]))
        sup5.stop_all(grace=0)
        # 1.44: the hot list first — nothing else starts until it is finished; if it stands still 30 min the others may run
        script.update({"hot-places": "work", "hot-events": "done", "m": "work", "n": "work"})
        sup6 = Supervisor(cf, ["hot-places", "hot-events", "m", "n"], 4, mp=MP, kill=kill)
        sup6.check(CLOCK[0])
        CLOCK[0] += 5; sup6.check(CLOCK[0])
        first6, state6 = sorted(sup6.running), dict(sup6.hot_state)
        script["hot-places"] = "stall"                      # Wikidata refuses: the hot set stands still
        for _ in range(8):
            CLOCK[0] += 300; sup6.check(CLOCK[0])
        valve6, open6 = sup6.hot_state.get("valve"), sorted(k_ for k_ in sup6.running if not k_.startswith("hot-"))
        script["hot-places"] = "work"                       # it moves again: the others step aside
        for _ in range(3):
            CLOCK[0] += 130; sup6.check(CLOCK[0])
        back6 = sorted(sup6.running)
        aside6 = [e for e in sup6.events if e["what"] == "ended" and e["dataset"] in ("m", "n") and "hot list" in e["why"]]
        kill(sup6.running["hot-places"]["proc"].pid) if "hot-places" in sup6.running else None
        script["hot-places"] = "done"
        for _ in range(4):
            CLOCK[0] += 130; sup6.check(CLOCK[0])
        ok("1.44 supervisor: the hot list first — while a hot set is unfinished no other dataset is started (they wait, and the page "
           "says how many); a hot set that is refused is retried within 2 minutes; only when the hot list has stood still for 30 minutes "
           "may the others run, and they step aside the moment it moves; when it is finished, everything else harvests",
           first6 == ["hot-places"] and state6["others_waiting"] == 2 and state6["done"] == 1 and state6["of"] == 2 and valve6 and open6 == ["m", "n"]
           and back6 == ["hot-places"] and len(aside6) >= 2 and sorted(k_ for k_ in sup6.running if not k_.startswith("hot-")) == ["m", "n"]
           and not sup6.hot_state["left"] and "Hot list first: 1 of 2 sets done" in hot_line({"hot": state6})
           and next_try({"dataset": "x", "state": "paused"}, 4) == BACKOFF_S[-1],
           (first6, state6, valve6, open6, back6, len(aside6), sorted(sup6.running), sup6.hot_state))
        sup6.stop_all(grace=0)
        ok("the data drive unplugged: the dataset is looked for again every minute (not given up)",
           next_try(_agent((os.path.join(cf, "no-such-drive"), "a", None)), 4) == DRIVE_RETRY_S)
        # re-routes between the internal drive (working copies) and the data drive
        old_env = {k: os.environ.get(k) for k in ("QB_WORK_FOLDER", "QB_WORK_MIN_FREE_GB")}
        os.environ["QB_WORK_FOLDER"] = os.path.join(cf, "work")
        try:
            wp = work_path(cf, "x")
            os.makedirs(os.path.dirname(wp), exist_ok=True)
            db = sqlite3.connect(wp)
            db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            db.execute("INSERT INTO meta VALUES ('facts', '3'), ('state', '\"running\"')")
            db.commit(); db.close()
            real_free = _free
            globals()["_free"] = lambda folder: 0 if os.path.abspath(folder).startswith(os.path.abspath(cf)) and "work" not in folder else real_free(folder)
            try:
                ok("the data drive full: the working copy keeps every fact and is not copied over (no half files)",
                   drain(cf, "x") == "no room" and not os.path.exists(home_path(cf, "x") + ".draining") and os.path.exists(wp))
            finally:
                globals()["_free"] = real_free
            os.environ["QB_WORK_MIN_FREE_GB"] = "1e12"
            ok("the internal drive full: the dataset's working copy is saved home and the agent carries on writing to the data drive",
               pull(cf, "x") is False and not os.path.exists(wp) and os.path.exists(home_path(cf, "x")))
        finally:
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        os.environ["QB_STARTUP_FOLDER"] = os.path.join(cf, "Startup")
        try:
            pd = os.path.join(cf, "suite", "QueryBook-Control-Panel")
            a1 = autostart(pd, True)
            with open(a1["file"], newline="") as f:
                body = f.read()
            a2 = autostart(pd, False)
            ok("start with Windows: one small file in the Startup folder starts the whole suite (and is removed when turned off)",
               a1["on"] and "START-ALL-WINDOWS.bat" in body and "\r\n" in body and not a2["on"], body)
        finally:
            os.environ.pop("QB_STARTUP_FOLDER", None)
        # counts: a busy shard keeps its last count; a home copy with facts the working copy lacks is merged, never overwritten
        key0 = next(k for k, d in catalog().items() if not getattr(d, "standalone", False))
        os.environ["QB_WORK_FOLDER"] = os.path.join(cf, "work2")
        try:
            def mk(path, fps, dups=0):
                sh = Shard(cf, key0, path)
                pid = sh.pred("name")
                sh.db.execute("INSERT OR IGNORE INTO parts(name, url) VALUES('p1', 'u')")
                sh.db.executemany("INSERT OR IGNORE INTO facts VALUES (?,?,?,?,1,1)", [(bytes([i]) * 16, "s%d" % i, pid, "o") for i in fps])
                sh.set_meta("facts", len(fps)); sh.set_meta("duplicates_removed", dups); sh.set_meta("state", "running")
                sh.db.commit(); sh.db.close()
            hp0, wp0 = home_path(cf, key0), work_path(cf, key0)
            mk(hp0, range(1, 11))                         # D: holds 10 facts (an older engine kept writing there)
            mk(wp0, range(1, 6))                          # the working copy on C: holds only 5 of them
            n = drain(cf, key0)
            db = sqlite3.connect(hp0)
            held = db.execute("SELECT count(*) FROM facts").fetchone()[0]; db.close()
            ok("saving to D: never overwrites facts only the D: copy holds — they are merged in first", n == 10 and held == 10, (n, held))
            st1 = status(cf)
            r1 = [d for d in st1["datasets"] if d["key"] == key0][0]
            sh = Shard(cf, key0, wp0)
            sh.db.execute("DELETE FROM facts WHERE fp IN (SELECT fp FROM facts LIMIT 4)")
            sh.set_meta("facts", 6); sh.set_meta("duplicates_removed", 4); sh.db.commit(); sh.db.close()
            status(cf)
            dr = count_drops(cf)
            ok("a lower count is written down with its cause (here: duplicates held by an earlier dataset — nothing lost)",
               r1["facts"] == 10 and dr and dr[-1]["fell"] == 4 and dr[-1]["cause"].startswith("duplicates"), dr)
            real_ro = _ro
            globals()["_ro"] = lambda path: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")) if key0 in path else real_ro(path)
            try:
                r2 = [d for d in status(cf)["datasets"] if d["key"] == key0][0]
            finally:
                globals()["_ro"] = real_ro
            ok("a dataset busy for a moment keeps its last count (the total never dips to a wrong number)",
               r2["facts"] == 6 and r2.get("count_from"), r2.get("facts"))
            # 1.31.2: facts held by another copy are added back; a busy file keeps its saved count across a restart
            import qbcommons as cm
            c = cm.Commons(cf, "stem")
            k2 = "ncbi-taxonomy"
            mk(home_path(cf, k2), range(1, 21))          # D: holds 20 facts
            mk(work_path(cf, k2), range(1, 6))           # the live copy on C: only 5
            import qbdrive
            oldcf = os.path.join(cf, "old-version")
            os.makedirs(os.path.join(oldcf, FOLDER))
            mk(os.path.join(oldcf, FOLDER, "%s.sqlite" % "noaa-ghcn-daily"), range(30, 60))   # an earlier version's folder holds NOAA facts
            mk(work_path(cf, "noaa-ghcn-daily"), range(30, 40))
            places0 = qbdrive.old_places
            qbdrive.old_places = lambda *a, **k: [("commons", oldcf)]
            try:
                rr = restore_missing(cf)
            finally:
                qbdrive.old_places = places0
            cnt = lambda p_: sqlite3.connect(p_).execute("SELECT count(*) FROM facts").fetchone()[0]
            ok("1.31.2: facts the live copy lacks are added back from the data drive's copy and from an earlier version's folder",
               rr.get(k2, {}).get("added") == 15 and cnt(work_path(cf, k2)) == 20 and rr.get("noaa-ghcn-daily", {}).get("added") == 20
               and cnt(work_path(cf, "noaa-ghcn-daily")) == 30 and cnt(home_path(cf, k2)) == 20, rr)
            ok("1.31.2: run again, nothing more is added (and nothing is ever deleted)", restore_missing(cf) == {} and cnt(home_path(cf, k2)) == 20)
            status(cf)
            _LAST_COUNT.clear(); _SAVED.clear()
            globals()["_ro"] = lambda path: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")) if k2 in path else real_ro(path)
            try:
                r3 = [d for d in status(cf)["datasets"] if d["key"] == k2][0]
            finally:
                globals()["_ro"] = real_ro
            ok("1.31.2: a file busy just after the page restarts shows its saved count, never 0", r3["facts"] == 20 and r3.get("count_from"), r3.get("facts"))
            # Stop saves only what changed; Start during a stop waits for it
            drain(cf, k2, force=True)
            at2 = drained(cf)[k2]["at"]
            fw = finish_work(cf, only_changed=True)
            ok("1.31.2: Stop saves only what changed (an unchanged copy is not rewritten)", drained(cf)[k2]["at"] == at2, fw)
            hb2 = os.path.join(cf, FOLDER, "_runner.json")
            with open(hb2, "w") as f:
                json.dump({"heartbeat": time.time(), "pid": os.getpid(), "note": "stopping: saving what changed to the data drive — noaa (1 of 2)"}, f)
            launched = []
            fs = full_speed(c, os.path.dirname(os.path.abspath(__file__)), "test", launch=lambda *a: launched.append(a))
            ok("1.31.2: Start while a stop is still saving waits for it (no second engine, the Stop signal is not cleared early)",
               fs["bulk"] == "starting after the stop" and not launched and stopping(cf), fs)
            with open(hb2, "w") as f:
                json.dump({"heartbeat": time.time(), "pid": 0, "note": "finished"}, f)
            for _ in range(30):
                if launched:
                    break
                time.sleep(0.5)
            ok("1.31.2: …and starts by itself as soon as the stop has finished", bool(launched) and not stopping(cf))
            os.remove(hb2)
            # 1.31.1: the dump beside the working copies on the internal drive (when it has room), never on the USB drive by default
            global INTERNAL_DUMP_ROOM
            room0, INTERNAL_DUMP_ROOM = INTERNAL_DUMP_ROOM, 0
            try:
                internal = dumps_folder(cf, c)
                ok("1.31.1: with working copies on the internal drive and room there, the dump is kept there",
                   internal == os.path.join(os.path.dirname(work_dir(cf)), "dumps"), internal)
                INTERNAL_DUMP_ROOM = 1e18
                ok("1.31.1: no room on the internal drive: the dump goes to the shared folder", dumps_folder(cf, c) == os.path.join(cf, "dumps"))
                c.set_setting("bulk:dumps:folder", os.path.join(cf, "big-drive"))
                ok("1.31.1: the admin's folder always wins", dumps_folder(cf, c) == os.path.join(cf, "big-drive"))
                c.set_setting("bulk:dumps:folder", "")
                INTERNAL_DUMP_ROOM = 0
                old = os.path.join(cf, "dumps", "wikidata", "2026-10-26")
                os.makedirs(old, exist_ok=True)
                open(os.path.join(old, qbdump.FILE), "wb").write(b"x")
                json.dump({"edition": "2026-10-26", "size": 1}, open(os.path.join(old, "ready.json"), "w"))
                ok("1.31.1: a copy made before the folder changed is still read until a newer one is ready",
                   (dumps_ready(cf, c) or {}).get("edition") == "2026-10-26")
            finally:
                INTERNAL_DUMP_ROOM = room0
            c.set_setting("bulk:min_free_gb", "0")
            rn = Run(cf, catalog()["pubchem-computed"])
            first = rn.stopped()
            c.set_setting("bulk:min_free_gb", "1e15")
            cached_ = rn.stopped()
            rn._chk_at = 0
            later = rn.stopped()
            c.set_setting("bulk:min_free_gb", "")
            ok("1.31.1: the checks between batches (on the data drive) are re-read every 30 s, not before every batch",
               first is None and cached_ is None and later and "nearly full" in later, (first, cached_, later))
        finally:
            os.environ.pop("QB_WORK_FOLDER", None)
        st = {"runner": {"alive": True, "version": VERSION}, "facts_per_min": 250_000, "last_hour": 15_000_000, "total": 900_000_000}
        o = {"datasets": [{"dataset": "x", "wall_s": 600, "bottleneck": "connection-slot congestion: agents queue"},
                          {"dataset": "y", "wall_s": 100, "bottleneck": "disk-bound: writing the shard"}],
             "congestion": [], "failures": [{"where": "x", "kind": "HTTPError", "count": 4}]}
        ev = [{"what": "ended", "dataset": "b", "state": "paused", "why": "no progress for 15 min — ended and restarted", "next_in_s": 60, "at": time.time()}]
        t = plain_summary(st, o, ev)
        ok("the health report is a few plain lines: health, speed, the main delay and what is done about it, recoveries, what to do",
           len(t.splitlines()) <= 14 and "WORKING, BUT SLOW" in t and "download connections" in t and "restarted" in t
           and "What you need to do: nothing" in t, t)
        t2 = plain_summary({"runner": {"alive": False}}, None, [])
        ok("the health report says what to press when the harvest is stopped", "STOPPED" in t2 and "Start harvesting" in t2, t2)
        one = Slots(cf)._lock("runner", 0)
        r = run(cf, ["a"], 1, until=lambda s: True)
        ok("only one harvesting engine at a time: a second one is refused", r and "already running" in str(r[0].get("error")), r)
        Slots(cf).release(one)
    finally:
        shutil.rmtree(cf, ignore_errors=True)
    # 1.33: staged writes — a batch is appended, the keyed tables are folded in rarely and sorted, the result is the same
    cf = tempfile.mkdtemp()
    try:
        sh = Shard(cf, "stage-test")
        p1 = sh.part("p1", "file://x")[0]; p2 = sh.part("p2", "file://y")[0]
        k = lambda n: hashlib.sha256(str(n).encode()).digest()[:16]
        sh.write(p1, [(k(1), "a", 1, "first", p1, 0), (k(2), "b", 1, "x", p1, 1)], 2)
        ok("1.33: a batch goes to the stage, not into the keyed tables (its cost does not grow with the shard)",
           sh.db.execute("SELECT count(*) FROM facts").fetchone()[0] == 0 and sh.meta("staged") == 2
           and sh.db.execute("SELECT rows FROM parts WHERE id = ?", (p1,)).fetchone()[0] == 2)
        sh.write(p1, [(k(1), "a", 1, "second", p1, 2), (k(3), "c", 1, "y", p1, 3)], 4, [(k(3), "https://c")])
        n1 = sh.merge()
        sh.write(p2, [(k(3), "c", 1, "later", p2, 0), (k(4), "d", 1, "z", p2, 1)], 2)
        n2 = sh.merge()
        got = dict(sh.db.execute("SELECT fp, o FROM facts"))
        pf = dict(sh.db.execute("SELECT name, facts FROM parts"))
        ok("1.33: merging keeps the earliest of two staged facts with one fingerprint and never replaces a fact already held",
           n1 == 3 and n2 == 1 and got.get(k(1)) == "first" and got.get(k(3)) == "y" and len(got) == 4, (n1, n2, got))
        ok("1.33: after a merge the counts, parts and links are as batch-by-batch inserts made them, and the stage is empty",
           sh.meta("facts") == 4 and sh.meta("staged") == 0 and pf == {"p1": 3, "p2": 1}
           and sh.db.execute("SELECT count(*) FROM stage").fetchone()[0] == 0
           and sh.db.execute("SELECT url FROM links WHERE fp = ?", (k(3),)).fetchone() == ("https://c",), (pf, sh.meta("facts")))
        ok("1.33: merging an empty stage does nothing", sh.merge() == 0 and sh.meta("facts") == 4)
        ok("1.33: the rate counts staged facts the moment they are written",
           sh.db.execute("SELECT facts FROM progress ORDER BY at DESC LIMIT 1").fetchone()[0] == 4)
        sh.db.close()
        # one window: staged facts are shown as gathered at once, so harvesting never looks stopped during a long part
        sg = Shard(cf, "calendar-scaffold")
        pg_ = sg.part("p1", "file://z")[0]
        sg.write(pg_, [(k(10 + i), "s%d" % i, 1, "o", pg_, i) for i in range(3)], 3)
        sg.db.close()
        st_ = status(cf)
        row_ = next(d for d in st_["datasets"] if d["key"] == "calendar-scaffold")
        ok("staged facts count as gathered on the screen the moment they are read (filed stays the keyed count)",
           row_["facts"] == 0 and row_["staged"] == 3 and row_["gathered"] == 3 and st_["total_gathered"] == 3 and st_["total"] == 0, row_)
        # 1.35: facts the store holds already, read again, are not counted as gathered — the total never falls when filed
        sg = Shard(cf, "calendar-scaffold")
        sg.merge()
        held_ = sg.meta("facts")
        sg.write(pg_, [(k(10 + i), "s%d" % i, 1, "o", pg_, 10 + i) for i in range(3)], 6)       # the same three again
        sg.write(pg_, [(k(50 + i), "t%d" % i, 1, "o", pg_, 20 + i) for i in range(2)], 8)       # two new ones
        sg.db.close()
        r2_ = next(d for d in status(cf)["datasets"] if d["key"] == "calendar-scaffold")
        sg = Shard(cf, "calendar-scaffold"); sg.merge(); after_ = sg.meta("facts"); sg.db.close()
        r3_ = next(d for d in status(cf)["datasets"] if d["key"] == "calendar-scaffold")
        ok("1.35: facts already held, read again, are not counted as new (sampled); only the new ones are, and filing them "
           "never makes the total fall", held_ == 3 and r2_["staged"] == 5 and r2_["gathered"] == 5 and after_ == 5
           and r3_["gathered"] == 5 and r3_["gathered"] >= r2_["gathered"], (held_, r2_.get("staged"), r2_.get("gathered"), after_))
        # 1.35, 24 x 7: keep_alive restarts the engine when nothing moves for 30 min, and only then
        class _C:
            folder = cf
            store = None
        kac, did = _C(), []
        mk = lambda total, done, note="running: 2 agent(s)", alive=True: {"runner": {"alive": alive, "note": note}, "total": total,
            "total_gathered": total, "datasets": [{"key": "a", "state": "running", "progress": {"done": done}}]}
        t0_ = 1_000_000.0
        r1 = keep_alive(kac, "", t0_, mk(10, 5), lambda: did.append(1))
        r2 = keep_alive(kac, "", t0_ + 600, mk(20, 9), lambda: did.append(1))                 # moving: fine
        r3 = keep_alive(kac, "", t0_ + 600 + KEEPALIVE_STALL_S - 60, mk(20, 9), lambda: did.append(1))   # still, not long enough
        r4 = keep_alive(kac, "", t0_ + 600 + KEEPALIVE_STALL_S + 1, mk(20, 9), lambda: did.append(1))    # still for 30 min: restart
        r5 = keep_alive(kac, "", t0_ + 600 + KEEPALIVE_STALL_S + 120, mk(20, 9), lambda: did.append(1))  # just restarted: wait again
        r6 = keep_alive(kac, "", t0_ + 9e5, mk(20, 9, "waiting: every dataset is finished or waiting for its next try"), lambda: did.append(1))
        r7 = keep_alive(kac, "", t0_ + 2e6, mk(20, 9, alive=False), lambda: did.append(1))
        ok("1.35 keep-alive: harvesting that moves is left alone; nothing moving for 30 minutes with datasets running restarts it "
           "once (written down with its reason); waiting on purpose or a dead runner (resumed elsewhere) is not restarted here",
           not any((r1, r2, r3, r5, r6, r7)) and r4 and r4["restarted"] and did == [1] and keepalive_info(cf)["restarts"] == 1
           and "nothing moved for 30 min" in keepalive_info(cf)["last"]["why"], (r3, r4, r5, r6, did, keepalive_info(cf)))
        # 1.35.2: an agent in the middle of a long filing (its SQLite steps advancing, no new fact yet) is never restarted
        # by the keep-alive; a filing frozen for 30 minutes is
        ad_ = _alive_dir(cf)
        def _beat(filing_):
            with open(os.path.join(ad_, "usgs-gnis.json"), "w") as f:
                json.dump({"at": time.time(), "pid": 1, "meter": 5, "rows": 9, "waiting": "filing 20,000,000 facts into the dataset", "filing": filing_}, f)
        kd, kc = [], _C()
        t1_ = t0_ + 5e6
        _beat(1); keep_alive(kac, "", t1_, mk(21, 9), lambda: kd.append(1))
        moving_ = []
        for i in range(1, 7):                            # an hour of filing, a step every 10 minutes
            _beat(1 + i); moving_.append(keep_alive(kac, "", t1_ + i * 600, mk(21, 9), lambda: kd.append(1)))
        wd_filing = watchdog_info(cf, True, t1_ + 3600)
        frozen_ = [keep_alive(kac, "", t1_ + 3600 + i * 600, mk(21, 9), lambda: kd.append(1)) for i in range(1, 5)]
        os.remove(os.path.join(ad_, "usgs-gnis.json"))
        ok("1.35.2 keep-alive: an hour-long filing that is still advancing is left alone (and the page says it is filing, not "
           "stalled); one that then freezes is restarted, once", not any(moving_) and kd == [1] and any(frozen_)
           and wd_filing["state"] == "working" and "filing" in wd_filing["text"], (moving_, frozen_, kd, wd_filing))
        # 1.36 fail-safe, judged by outcome: agents that keep reading (bytes and rows move every look) but add no NEW
        # fact — 1.35 called that "moving" and never acted. 60 min: restart; 2 h: hard restart; 3 h: rest them.
        os.remove(os.path.join(cf, FOLDER, KEEPALIVE_NAME))
        def _busy(n_):
            with open(os.path.join(ad_, "usgs-gnis.json"), "w") as f:
                json.dump({"at": time.time(), "pid": 1, "meter": n_, "rows": n_, "waiting": None, "filing": None}, f)
        t2_, acts_, did2 = t1_ + 1e6, [], []
        for i in range(0, 20):                           # a look every 10 minutes for 3 h 10 min; rows move, the total does not
            _busy(i)
            r_ = keep_alive(kac, "", t2_ + i * 600, mk(40, 9), lambda: did2.append(1))
            if r_:
                acts_.append((i * 10, r_["level"]))
        wd_ = watchdog_info(cf, True, t2_ + 19 * 600 + 700)
        ok("1.36 fail-safe: reading for hours without one new fact is acted on — restart at 60 min, hard restart at 2 h, "
           "and at 3 h the datasets that add nothing are rested so the others take their place; each action is written down",
           acts_ == [(60, 1), (120, 2), (180, 3)] and did2 == [1, 1] and list(resting(cf, t2_ + 181 * 60)) == ["a"]
           and not resting(cf, t2_ + 181 * 60 + REST_S) and keepalive_info(cf)["restarts"] == 3
           and "rested 1 dataset" in keepalive_info(cf)["last"]["action"], (acts_, did2, resting(cf, t2_ + 181 * 60)))
        ok("1.36 fail-safe: the page says so in plain words (no new fact for how long, what the fail-safe does next, what rests)",
           wd_["state"] == "dry" and "no new fact for" in wd_["text"] and "Resting: a until" in wd_["text"] and wd_["actions"] == 3, wd_)
        _busy(99)
        r_new = keep_alive(kac, "", t2_ + 21 * 600, mk(41, 9), lambda: did2.append(1))
        _busy(100)
        r_after = keep_alive(kac, "", t2_ + 21 * 600 + 3000, mk(41, 9), lambda: did2.append(1))
        ok("1.36 fail-safe: one new fact and the ladder starts over (nothing is restarted while facts arrive)",
           not r_new and not r_after and did2 == [1, 1] and watchdog_info(cf, True, t2_ + 21 * 600 + 60)["dry_s"] == 60, (r_new, r_after))
        os.remove(os.path.join(ad_, "usgs-gnis.json"))
        os.remove(os.path.join(cf, FOLDER, REST_NAME))
        # 1.37: adding facts back from another copy — in pieces, resumable, and never the same copy twice
        import tempfile as _tf
        cfo = _tf.mkdtemp()
        KEY_ = "tatoeba-cc0"
        for folder_, lo_, hi_ in ((cf, 0, 300), (cfo, 200, 900)):          # live: 300 facts; the other copy: 700, 100 of them shared
            sh_ = Shard(folder_, KEY_)
            pt_ = sh_.part("p1", "file://z")[0]
            pd_ = sh_.pred("means")
            sh_.write(pt_, [(k(7000 + i), "m%d" % i, pd_, "o", pt_, i) for i in range(lo_, hi_)], hi_ - lo_)
            sh_.merge(); sh_.db.close()
        live_, other_ = shard_path(cf, KEY_), shard_path(cfo, KEY_)
        seen_, calls_ = [], []
        real_oc, real_mi = other_copies, merge_into
        try:
            globals()["other_copies"] = lambda c_, key_: [other_] if key_ == KEY_ else []
            globals()["merge_into"] = lambda d_, s_, start=0, progress=None, halt=None: (calls_.append(start), real_mi(d_, s_, start, progress, halt))[1]
            r_a = restore_missing(cf, say=seen_.append, halt=lambda: len(calls_) and (_read_json(os.path.join(cf, FOLDER, RESTORED_NAME), {}) or {}).get(
                KEY_ + "|" + os.path.normcase(os.path.abspath(other_)), {}).get("piece", 0) >= 100)        # interrupted at piece 100 of 256
            mid_ = (_meta_of(live_) or {}).get("facts")
            led_ = _read_json(os.path.join(cf, FOLDER, RESTORED_NAME), {})[KEY_ + "|" + os.path.normcase(os.path.abspath(other_))]
            r_b = restore_missing(cf, say=seen_.append)                    # started again: resumes, does not start over
            end_ = (_meta_of(live_) or {}).get("facts")
            r_c = restore_missing(cf, say=seen_.append)                    # and again: this copy was merged, nothing to do
            db_ = sqlite3.connect(live_); real_n = db_.execute("SELECT count(*) FROM facts").fetchone()[0]; db_.close()
        finally:
            globals()["other_copies"], globals()["merge_into"] = real_oc, real_mi
        ok("1.37: facts are added back from another copy in pieces, each one kept — interrupted at piece 100 of 256 it resumes there "
           "(nothing is done twice, nothing lost: 300 + 600 = 900), and the count rises while it works",
           led_["piece"] == 100 and not led_["done"] and 300 < mid_ < 900 and calls_[:2] == [0, 100] and end_ == 900 and real_n == 900
           and r_a[KEY_]["added"] + r_b[KEY_]["added"] == 600 and any("resuming at 39%" in t for t in seen_), (led_, mid_, calls_, end_, real_n))
        ok("1.37: a copy that was merged is never merged again while it is unchanged (it used to be merged at every start, for hours)",
           calls_ == [0, 100] and r_c == {}, (calls_, r_c))
        os.remove(live_)
        # 1.37: getting ready is work — an engine adding facts back for an hour is not restarted; one that stands still is
        os.remove(os.path.join(cf, FOLDER, KEEPALIVE_NAME))
        prep_, did3, t3_ = [], [], t0_ + 9e6
        def _prep(i_):
            _restoring(cf, {"key": "usgs-gnis", "from": "x", "facts": 9, "live": 5, "piece": i_, "pieces": 256, "added": i_})
            return mk(50, 9, "starting: adding back facts to usgs-gnis from another copy: %d%% checked" % i_)
        for i in range(0, 8):                                              # 70 minutes, a piece every 10 minutes
            prep_.append(keep_alive(kac, "", t3_ + i * 600, _prep(i), lambda: did3.append(1)))
        wd_p = watchdog_info(cf, True, t3_ + 7 * 600)
        still_ = [keep_alive(kac, "", t3_ + 7 * 600 + j * 600, _prep(7), lambda: did3.append(1)) for j in range(1, 5)]
        _restoring(cf, None)
        ok("1.37 fail-safe: an engine getting ready (adding facts back, piece by piece) for over an hour is left to finish — it was "
           "restarted every 30 minutes before, and began again each time; one that stands still for 30 minutes is restarted, and resumes",
           not any(prep_) and did3 == [1] and wd_p["state"] == "preparing" and "Getting ready" in wd_p["text"] and wd_p.get("alert")
           and headline({"runner": {"alive": True, "version": VERSION}, "watchdog": wd_p, "datasets": []})["state"] == "preparing",
           (prep_, still_, did3, wd_p))
        # 1.37: churn, dataset by dataset — one keeps reading without a new fact while the others add theirs: it alone is rested
        os.remove(os.path.join(cf, FOLDER, KEEPALIVE_NAME))
        def _two(i_, good_):
            for key_, rows_ in (("usgs-gnis", i_), ("ncbi-taxonomy", i_)):
                with open(os.path.join(ad_, key_ + ".json"), "w") as f:
                    json.dump({"at": time.time(), "pid": 1, "meter": rows_, "rows": rows_, "waiting": None, "filing": None}, f)
            return {"runner": {"alive": True, "note": "running: 2 agent(s)"}, "total": 100 + good_, "total_gathered": 100 + good_,
                    "datasets": [{"key": "usgs-gnis", "state": "running", "gathered": 100, "progress": {"done": i_}},
                                 {"key": "ncbi-taxonomy", "state": "running", "gathered": good_, "progress": {"done": i_}}]}
        t4_, churn_ = t3_ + 1e6, []
        for i in range(0, 7):                                              # an hour: one dataset adds facts, the other only reads
            r_ = keep_alive(kac, "", t4_ + i * 600, _two(i, i * 1000), lambda: did3.append(9))
            if r_:
                churn_.append((i * 10, r_.get("rested")))
        for key_ in ("usgs-gnis", "ncbi-taxonomy"):
            os.remove(os.path.join(ad_, key_ + ".json"))
        ok("1.37 fail-safe: a dataset that reads for 45 minutes without one new fact is rested (6 h, then 12 h, then 24 h) while the "
           "datasets that add facts carry on — the drive stops working for nothing; nothing is restarted for it",
           churn_ == [(50, ["usgs-gnis"])] and list(resting(cf, t4_ + 3100)) == ["usgs-gnis"] and 9 not in did3
           and "reading without adding anything" in keepalive_info(cf)["last"]["action"], (churn_, resting(cf, t4_ + 3100)))
        os.remove(os.path.join(cf, FOLDER, REST_NAME))
        # 1.37: the engine's process is there -> it is alive, however late its heartbeat (a busy data drive)
        me_, gone_ = os.getpid(), 2 ** 22 + 12345
        ok("1.37: an engine whose process is running is alive even when its heartbeat is minutes late (a busy drive) — it is no longer "
           "taken for dead, doubled and then ended; a late heartbeat with no process, or 15 minutes of silence, still means dead",
           _runner_alive({"heartbeat": time.time() - 5, "pid": gone_}) and _runner_alive({"heartbeat": time.time() - 400, "pid": me_})
           and not _runner_alive({"heartbeat": time.time() - 400, "pid": gone_}) and not _runner_alive({"heartbeat": time.time() - HB_BUSY_S - 5, "pid": me_})
           and not _runner_alive({"heartbeat": time.time(), "pid": me_, "note": "finished"}))
        pr_ok = drive_probe(cf)
        open(live_ + ".not-a-folder", "w").close()
        pr_bad = drive_probe(live_ + ".not-a-folder", wait=5)
        os.remove(live_ + ".not-a-folder")
        DRIVE_STATE[cf] = {"paused_at": time.time(), "why": "the data drive refused a small write"}
        h_bad = health(cf)
        DRIVE_STATE.pop(cf)
        h_ok = health(cf)
        ok("1.37: the data drive is tested with a small write; while it does not answer, the harvest says it is paused to protect "
           "the drive (and why), and reads normally again afterwards", pr_ok[0] and not pr_bad[0] and "refused" in pr_bad[1]
           and h_bad["state"] == "drive" and h_bad["alert"]["level"] == "error" and h_ok["state"] != "drive", (pr_ok, pr_bad, h_bad, h_ok))
        # 1.36: Start means ON until Stop — an engine that is not running is started again, even with a stop mark left behind
        real_fs, started_ = full_speed, []
        for f_ in ("_runner.json", "_runner.stop", "_runner.resumed", INTENT_NAME):
            if os.path.exists(os.path.join(cf, FOLDER, f_)):
                os.remove(os.path.join(cf, FOLDER, f_))
        try:
            globals()["full_speed"] = lambda c_, pd_, why="", launch=None: (started_.append(why), {"bulk": "started"})[1]
            e0 = ensure_on(kac, "", time.time())                           # never started, nothing said: left alone
            set_intent(cf, True, "Start pressed")
            e1 = ensure_on(kac, "", time.time() + 30)                      # just pressed: the start itself is under way
            open(os.path.join(cf, FOLDER, "_runner.stop"), "w").close()    # a restart cut short left its mark behind
            e2 = ensure_on(kac, "", time.time() + ENSURE_WAIT_S + 5)
            e3 = ensure_on(kac, "", time.time() + ENSURE_WAIT_S + 35)      # at most one start every 3 minutes
            set_intent(cf, False, "Stop pressed")
            os.remove(os.path.join(cf, FOLDER, "_runner.resumed"))
            e4 = ensure_on(kac, "", time.time() + 9e5)                     # Stop was pressed: stays stopped
        finally:
            globals()["full_speed"] = real_fs
        ok("1.36 fail-safe: Start means ON until Stop is pressed — with no engine running it is started again by itself "
           "(after a reboot, a crash, a restart cut short), at most once every 3 minutes; after Stop it stays stopped",
           not e0 and not e1 and e2 and e2["started"] and not e3 and not e4 and len(started_) == 1 and intent(cf)["want"] == "off"
           and "fail-safe" in started_[0], (e0, e1, e2, e3, e4, started_))
        ok("1.36 fail-safe: with harvesting on and no engine, the page says it is starting again by itself (not 'Stopped')",
           headline({"runner": {"alive": False}, "watchdog": {"want": "on"}, "datasets": []})["state"] == "starting"
           and headline({"runner": {"alive": False}, "watchdog": {"want": "off"}, "datasets": []})["state"] == "stopped")
        for f_ in ("_runner.stop", INTENT_NAME):
            if os.path.exists(os.path.join(cf, FOLDER, f_)):
                os.remove(os.path.join(cf, FOLDER, f_))
        # 1.35: a dataset changing hands (file moved for a moment) keeps its count on the screen
        sp_ = shard_path(cf, "calendar-scaffold")
        os.replace(sp_, sp_ + ".moving")
        r4_ = next(d for d in status(cf)["datasets"] if d["key"] == "calendar-scaffold")
        os.replace(sp_ + ".moving", sp_)
        r5_ = next(d for d in status(cf)["datasets"] if d["key"] == "calendar-scaffold")
        ok("1.35: a dataset whose file is moving for a moment keeps its last count on the screen (the total never dips), "
           "and reads its own file again once it is back", r4_["gathered"] == 5 and "changing hands" in str(r4_.get("count_from"))
           and r5_["gathered"] == 5 and not r5_.get("count_from"), (r4_.get("gathered"), r4_.get("count_from"), r5_.get("gathered")))
        # 1.35.1: a batch whose few duplicates the 1,000-fact sample misses: the total holds, never falls, when it is filed
        old_ns = Shard.NEW_SAMPLE
        Shard.NEW_SAMPLE = 1                                # the sample sees only the first fact: the duplicate is missed
        try:
            sg = Shard(cf, "calendar-scaffold")
            sg.write(pg_, [(k(60 + i), "v%d" % i, 1, "o", pg_, 30 + i) for i in range(3)] + [(k(10), "s0", 1, "o", pg_, 33)], 12)
            sg.db.close()
            h1_ = next(d for d in status(cf)["datasets"] if d["key"] == "calendar-scaffold")
            sg = Shard(cf, "calendar-scaffold"); sg.merge(); sg.db.close()
            st2_ = status(cf)
            h2_ = next(d for d in st2_["datasets"] if d["key"] == "calendar-scaffold")
            sg = Shard(cf, "calendar-scaffold")
            sg.write(pg_, [(k(70 + i), "w%d" % i, 1, "o", pg_, 40 + i) for i in range(2)], 14)
            sg.db.close()
            h3_ = next(d for d in status(cf)["datasets"] if d["key"] == "calendar-scaffold")
        finally:
            Shard.NEW_SAMPLE = old_ns
        ok("1.35.1: a filed batch with a duplicate the sample missed holds the total (counted as already held) until new facts "
           "pass it — the total never falls", h1_["gathered"] == 9 and h2_["facts"] == 8 and h2_["gathered"] == 9
           and st2_["already_held_at_filing"] == 1 and h3_["gathered"] == 10, (h1_.get("gathered"), h2_.get("facts"),
           h2_.get("gathered"), st2_.get("already_held_at_filing"), h3_.get("gathered")))
        # 1.35: filing waits its turn in its own pool and never blocks an agent's next batch
        global STAGE_MIN, STAGE_CAP
        old_min, old_cap = STAGE_MIN, STAGE_CAP
        STAGE_MIN = STAGE_CAP = 4
        try:
            sm = Shard(cf, "mit-ocw")
            sm.mslots = MergeSlots(cf, 1)
            pm = sm.part("m1", "file://m")[0]
            busy = MergeSlots(cf, 1).try_take()                # another agent is filing
            got1 = sm.write(pm, [(k(100 + i), "u", 1, "o", pm, i) for i in range(5)], 5)
            staged1 = sm.meta("staged")
            MergeSlots(cf, 1).release(busy)
            got2 = sm.write(pm, [(k(200 + i), "v", 1, "o", pm, i) for i in range(2)], 7)
            ok("1.35: while another agent files, an agent keeps staging (its batch is written, no wait); it files on its "
               "next batch once the pool is free", busy is not None and got1 == 0 and staged1 == 5 and got2 == 7
               and sm.meta("facts") == 7 and sm.meta("staged") == 0, (busy is not None, got1, staged1, got2, sm.meta("facts")))
            # 1.39: at the end of a part an agent no longer queues to file — it files if it is its turn, else it reads on
            busy = MergeSlots(cf, 1).try_take()
            sm.write(pm, [(k(300 + i), "w", 1, "o", pm, i) for i in range(3)], 10)
            d1, st1 = sm.merge(wait=False), sm.meta("staged")
            MergeSlots(cf, 1).release(busy)
            d2 = sm.merge(wait=False)
            ok("1.39: at the end of a part an agent whose turn to file has not come does not wait (15 of 16 lanes used to stand "
               "idle in that queue): its facts stay staged and counted, it reads its next part, and files when the pool is free",
               d1 == 0 and st1 == 3 and d2 == 3 and sm.meta("staged") == 0 and sm.meta("facts") == 10, (d1, st1, d2, sm.meta("facts")))
            sm.db.close()
        finally:
            STAGE_MIN, STAGE_CAP = old_min, old_cap
        ok("1.35: no filing ever takes more than 20 million facts at once (half a big shard used to be one transaction)",
           min(STAGE_CAP, max(STAGE_MIN, 400_000_000 // 2)) == 20_000_000)
    finally:
        shutil.rmtree(cf, ignore_errors=True)
    # 1.34 safeguards: the copier never shrinks the home copy; a restore shows the full count; the backup is a copy at Start
    root = tempfile.mkdtemp()
    try:
        cf = os.path.join(root, "commons"); os.makedirs(cf)
        os.environ["QB_WORK_FOLDER"] = os.path.join(root, "work")
        key = "pubchem-computed"
        sh = Shard(cf, key, home_path(cf, key)); pid = sh.part("p", "file://x")[0]; pr = sh.pred("mass")
        k = lambda n: hashlib.sha256(str(n).encode()).digest()[:16]
        sh.write(pid, [(k(i), "s%d" % i, pr, "o", pid, i) for i in range(40)], 40); sh.merge(); sh.db.close()
        wp = work_path(cf, key); os.makedirs(os.path.dirname(wp), exist_ok=True)
        shutil.copyfile(home_path(cf, key), wp)
        w = sqlite3.connect(wp); w.execute("DELETE FROM facts WHERE fp IN (SELECT fp FROM facts LIMIT 10)")
        w.execute("UPDATE meta SET value = '30' WHERE key = 'facts'"); w.commit(); w.close()      # the working copy lost 10
        g = globals(); real = g["merge_into"]; g["merge_into"] = lambda dst, src: 0                # ...and adding back fails
        try:
            r2 = drain(cf, key, force=True)
        finally:
            g["merge_into"] = real
        hn2 = sqlite3.connect(home_path(cf, key)).execute("SELECT count(*) FROM facts").fetchone()[0]
        r = drain(cf, key, force=True)                                                             # adding back works again
        hn = sqlite3.connect(home_path(cf, key)).execute("SELECT count(*) FROM facts").fetchone()[0]
        ok("1.34: the copier never replaces the data drive's copy with one holding fewer facts", r2 == "busy" and hn2 == 40 and r == 40 and hn == 40, (r, r2, hn, hn2))
        _restoring(cf, {"key": key, "from": "F:\\QB-Backup", "facts": 206_000_000, "live": 30})
        row = next(d for d in status(cf)["datasets"] if d["key"] == key)
        _restoring(cf, None)
        row2 = next(d for d in status(cf)["datasets"] if d["key"] == key)
        ok("1.34: while facts are being added back the page shows the full count with a note, never a drop",
           row["facts"] == 206_000_000 and "restoring" in row.get("count_from", "") and row2["facts"] == 40, (row["facts"], row2["facts"]))
        import qbvault
        bk = os.path.join(root, "backup"); os.makedirs(bk)
        with open(os.path.join(cf, "backup.json"), "w") as f:
            json.dump({"folder": bk}, f)
        qbvault.backup(cf, reason="test")
        ok("1.34: the newest backup is one of the copies checked at Start",
           any(qbvault.NAME in p_ for p_ in other_copies(cf, key)), other_copies(cf, key))
    finally:
        os.environ.pop("QB_WORK_FOLDER", None)
        shutil.rmtree(root, ignore_errors=True)
    pg = {"total": 1000, "done": 600, "done_at_start": 0, "since": 1000.0, "at": 1060.0, "part": "2026-11-06 part 0049 of 0147",
          "part_no": 4, "parts": 10}
    ok("1.33: a running agent's speed is measured up to now — one that stopped moving shows its speed falling",
       abs(_progress(pg, 1060.0, live=True)["rate"] - 10) < 1e-9 and abs(_progress(pg, 1120.0, live=True)["rate"] - 5) < 1e-9
       and abs(_progress(pg, 1120.0)["rate"] - 10) < 1e-9)
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
