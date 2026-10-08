#!/usr/bin/env python3
"""
ufcs_store.py — a local, dependency-free UFCS Fact store for heavy harvesting.

Stores UFCS Fact Units on your workstation as ~1 GB gzip-compressed blocks, with a
content-addressed SQLite index for dedupe and lookup. Standard library only
(json, gzip, sqlite3, hashlib, struct, argparse) — no pip installs, no server.

Store layout (a directory):
    <store>/manifest.json          run/config + rollup counters
    <store>/index.sqlite           fingerprint -> block_id  (dedupe + get)
    <store>/blocks/block_00000.jsonl.gz ...   the facts, one JSON packet per line

Commands:
    harvest   generate N deterministic facts (primes, squares, cubes, ...) and store them
    ingest    load facts from a JSONL file (or stdin) into the store
    stats     show block count, fact count, raw vs compressed bytes, ratio, dedupe
    get       fetch one fact by its semantic fingerprint
    verify    recompute a claim's fingerprint and look it up (VERIFIED if present)

Examples:
    python3 ufcs_store.py harvest ./mystore --count 5000000
    python3 ufcs_store.py ingest  ./mystore facts.jsonl
    cat facts.jsonl | python3 ufcs_store.py ingest ./mystore -
    python3 ufcs_store.py stats   ./mystore
    python3 ufcs_store.py verify  ./mystore "Hydrogen" "has_atomic_number" "1"

Block size defaults to ~1 GiB *compressed*; change with --block-mb.
"""
import argparse, bz2, gzip, hashlib, json, lzma, os, sqlite3, struct, sys, threading, time

# codec name -> (opener, file extension). All support text and binary modes.
# gzip uses compresslevel=1 (fast): on external/USB drives, level-9 compression is the
# dominant harvesting bottleneck; level 1 writes many times faster for a modest size
# increase, which is the right trade for throughput. Override with QB_GZIP_LEVEL.
_GZIP_LEVEL = int(os.environ.get("QB_GZIP_LEVEL", "1") or "1")
def _gzip_fast(*a, **k):
    k.setdefault("compresslevel", _GZIP_LEVEL)
    return gzip.open(*a, **k)
CODECS = {"gzip": (_gzip_fast, "gz"), "bz2": (bz2.open, "bz2"), "xz": (lzma.open, "xz")}

# Process-wide write serializer. Every writer in THIS process (harvest agents,
# language ingest, user-created facts, web harvester) shares one store on disk but
# opens its own SQLite connection. Without serialization those connections collide
# ("database is locked") and their non-atomic manifest writes race ("Expecting value:
# line 1 column 1"). This reentrant lock makes every write region exclusive AND every
# write commits before the lock is released, so no open transaction ever outlives the
# lock — which is what actually prevents the lock-contention error.
WRITE_LOCK = threading.RLock()

# Binary "packed" record: fingerprint(32B raw) + polarity + trust(f32) + 4 length fields,
# then subject/predicate/object/domain UTF-8 bytes. Drops the JSON wrapper for density.
_PK = struct.Struct("<32sBfHHHH")   # fp, pol(1/0), trust, slen, plen, olen, dlen
def pack_record(rec, fp_hex, trust):
    n = rec["nucleus"]
    s = str(n["subject"]).encode(); p = str(n["predicate"]).encode()
    o = str(n["object"]).encode();  d = str(rec.get("domain", "")).encode()
    pol = 1 if rec.get("polarity", "+") == "+" else 0
    return _PK.pack(bytes.fromhex(fp_hex), pol, float(trust), len(s), len(p), len(o), len(d)) + s + p + o + d
def iter_packed(f):
    hs = _PK.size
    while True:
        head = f.read(hs)
        if len(head) < hs: break
        fp, pol, trust, sl, pl, ol, dl = _PK.unpack(head)
        s = f.read(sl); p = f.read(pl); o = f.read(ol); d = f.read(dl)
        yield {"semantic_fingerprint": fp.hex(), "polarity": "+" if pol else "-",
               "certification": {"trust_score": round(trust, 6)}, "domain": d.decode(),
               "nucleus": {"subject": s.decode(), "predicate": p.decode(), "object": o.decode()}}

# ---------- content addressing (matches the UFCS reference engine) ----------
def _h(*parts): return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
def _norm(s):   return " ".join(str(s).strip().lower().split())

def fingerprint(subject, predicate, obj, polarity="+"):
    return _h(_norm(subject), _norm(predicate), _norm(obj), polarity)

def fuid(subject, predicate, obj, polarity, source_id, ingested):
    content = json.dumps({"o": obj, "p": predicate, "pol": polarity, "s": subject}, sort_keys=True)
    return _h(content, source_id, ingested)

def make_packet(subject, predicate, obj, polarity="+", domain="general",
                source=("SRC-GEN", "Deterministic generator", "reference", 1.0), trust=0.99):
    ingested = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    sfp = fingerprint(subject, predicate, obj, polarity)
    return {
        "ufcs_version": "1.0",
        "fuid": fuid(subject, predicate, obj, polarity, source[0], ingested),
        "fact_type": "assertion",
        "domain": domain,
        "nucleus": {"subject": subject, "predicate": predicate, "object": obj},
        "polarity": polarity,
        "semantic_fingerprint": sfp,
        "confidence": {"trust_score": trust},
        "sources": [{"id": source[0], "name": source[1], "class": source[2], "reputation": source[3]}],
        "certification": {"authority_class": source[2], "trust_score": trust},
        "temporal": {"ingested": ingested},
        "safety": {"classification": "PUBLIC", "acl": ["reader"]},
    }

# ---------- store ----------
class UFCSStore:
    def __init__(self, path, block_mb=1024, codec="gzip", pack=False, no_fql=False):
        self.path = path
        self.blocks_dir = os.path.join(path, "blocks")
        self.manifest_path = os.path.join(path, "manifest.json")
        self.index_path = os.path.join(path, "index.sqlite")
        self.block_target = block_mb * 1024 * 1024        # target compressed bytes per block
        os.makedirs(self.blocks_dir, exist_ok=True)
        # isolation_level=None -> autocommit mode. Writes are made transactional explicitly
        # (BEGIN/COMMIT) inside WRITE_LOCK; this stops the CREATE TABLE/PRAGMA below from
        # opening an implicit transaction that lingers for the life of the connection and
        # blocks every other agent ("database is locked"). This is the core concurrency fix.
        with WRITE_LOCK:
            self.db = sqlite3.connect(self.index_path, timeout=60, isolation_level=None)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA busy_timeout=60000")   # concurrent domain agents wait, never crash
            self.db.execute("PRAGMA synchronous=NORMAL")
            self.db.execute("CREATE TABLE IF NOT EXISTS fp (fingerprint TEXT PRIMARY KEY, block INTEGER)")
            self.db.execute("CREATE TABLE IF NOT EXISTS nuc (fp TEXT PRIMARY KEY, subject TEXT, predicate TEXT, object TEXT, trust REAL, block INTEGER)")
            self.db.execute("CREATE INDEX IF NOT EXISTS nuc_sp ON nuc(subject, predicate)")
        self.manifest = self._load_manifest()
        # Concurrency: many store instances share manifest.json. Each tracks its OWN
        # deltas for the additive counters and a set of keys it wants to force, and
        # _save_manifest merges those into the freshly-read on-disk file — so instance A
        # never wipes instance B's counter or resume key. (Fixes the "same 7.5M on every
        # agent / 0 on others" counter race.)
        self._delta = {"facts": 0, "duplicates": 0, "raw_bytes": 0}
        self._force = {}
        # existing store keeps its settings; a new store adopts the requested ones
        self.codec  = self.manifest.get("codec", codec)
        self.pack   = self.manifest.get("pack", pack)
        self.no_fql = self.manifest.get("no_fql", no_fql)
        self.manifest["codec"] = self.codec; self.manifest["pack"] = self.pack; self.manifest["no_fql"] = self.no_fql
        self._force.update(codec=self.codec, pack=self.pack, no_fql=self.no_fql)
        self._open, self._cext = CODECS[self.codec]
        self._ext = ("pack" if self.pack else "jsonl") + "." + self._cext
        self._mode_w = "ab" if self.pack else "at"
        self._blk = None            # open block handle
        self._blk_id = self.manifest["blocks"] - 1 if self.manifest["blocks"] else -1

    def _default_manifest(self):
        return {"blocks": 0, "facts": 0, "duplicates": 0, "raw_bytes": 0,
                "block_mb": self.block_target // (1024*1024)}

    def _load_manifest(self):
        # Tolerant read: a concurrent writer or an interrupted run can leave the file
        # momentarily empty or truncated. Never crash on that — fall back to defaults.
        try:
            if os.path.exists(self.manifest_path):
                with open(self.manifest_path, encoding="utf-8") as f:
                    data = f.read()
                if data.strip():
                    return json.loads(data)
        except (ValueError, OSError):
            pass
        return self._default_manifest()

    def _bump(self, key, n):
        """Record an additive change to a shared counter (applied as a delta on save)."""
        self.manifest[key] = self.manifest.get(key, 0) + n
        self._delta[key] = self._delta.get(key, 0) + n

    def _set_key(self, key, val):
        """Set a manifest key that this instance owns (resume key, blocks, last_verify)."""
        self.manifest[key] = val
        self._force[key] = val

    def _save_manifest(self):
        # Atomic + MERGING write. Under the process lock: re-read the on-disk manifest,
        # apply THIS instance's counter deltas and forced keys onto it, then os.replace()
        # a temp file in. Atomic write fixes "Expecting value: line 1 column 1"; the merge
        # fixes concurrent instances clobbering each other's counters/resume keys.
        with WRITE_LOCK:
            disk = self._load_manifest()
            for k, d in self._delta.items():
                if d:
                    disk[k] = disk.get(k, 0) + d
            self._delta = {"facts": 0, "duplicates": 0, "raw_bytes": 0}
            for k, v in self._force.items():
                disk[k] = v
            disk.setdefault("block_mb", self.block_target // (1024 * 1024))
            self.manifest = disk
            # Best-effort: if the store directory vanished (e.g. a self-test tempdir was
            # cleaned while a harvest thread was still finishing), don't crash the thread.
            try:
                tmp = self.manifest_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(disk, f, indent=2)
                # atomic rename is enough for this rollup counter; we deliberately do NOT
                # fsync — a per-batch fsync is the main harvesting stall on external/USB
                # drives, and the boot-time reconcile repairs the counter after a crash.
                os.replace(tmp, self.manifest_path)
            except OSError:
                pass

    def _block_path(self, i): return os.path.join(self.blocks_dir, f"block_{i:05d}.{self._ext}")

    def _open_block(self):
        # continue the last block if it is under target, else start a new one
        if self._blk_id >= 0 and os.path.getsize(self._block_path(self._blk_id)) < self.block_target:
            pass
        else:
            self._blk_id += 1
            self._set_key("blocks", self._blk_id + 1)
        if self.pack:
            self._blk = self._open(self._block_path(self._blk_id), "ab")
        else:
            self._blk = self._open(self._block_path(self._blk_id), "at", encoding="utf-8")

    _CHECK_EVERY = 8192   # flush + size-check cadence (per-record flush is far too slow at scale)

    def add(self, rec):
        """Add one packet; dedupe by semantic_fingerprint. Returns True if stored, False if dup.
        Serialized + committed under WRITE_LOCK so concurrent agents never collide."""
        with WRITE_LOCK:
            if self._blk is None: self._open_block()       # ensure a valid block id before indexing
            n = rec["nucleus"]
            fp = rec.get("semantic_fingerprint") or fingerprint(n["subject"], n["predicate"], n["object"], rec.get("polarity", "+"))
            try:
                self.db.execute("INSERT INTO fp(fingerprint, block) VALUES(?,?)", (fp, self._blk_id))
            except sqlite3.IntegrityError:
                self._bump("duplicates", 1)
                return False
            trust = (rec.get("certification") or {}).get("trust_score",
                     (rec.get("confidence") or {}).get("trust_score", 0.0))
            if not self.no_fql:
                self.db.execute("INSERT OR IGNORE INTO nuc(fp, subject, predicate, object, trust, block) VALUES(?,?,?,?,?,?)",
                                (fp, _norm(n["subject"]), _norm(n["predicate"]), str(n["object"]), trust, self._blk_id))
            if self.pack:
                blob = pack_record(rec, fp, trust); self._blk.write(blob); wrote = len(blob)
            else:
                line = json.dumps(rec, separators=(",", ":")); self._blk.write(line + "\n"); wrote = len(line) + 1
            self._bump("facts", 1)
            self._bump("raw_bytes", wrote)
            self._bump("facts_dom_" + (str(rec.get("domain") or "general")), 1)  # per-domain tally
            self._since = getattr(self, "_since", 0) + 1
            if self._since >= self._CHECK_EVERY:
                self._since = 0
                self._blk.flush()
                self.db.commit()          # keep the write transaction short (no long-held lock)
                if os.path.getsize(self._block_path(self._blk_id)) >= self.block_target:
                    self._blk.close(); self._blk = None
            return True

    def flush(self):
        with WRITE_LOCK:
            if self._blk is not None: self._blk.flush()
            self.db.commit(); self._save_manifest()

    def close(self):
        with WRITE_LOCK:
            if self._blk is not None:
                self._blk.close(); self._blk = None
            try:
                self.db.commit(); self._save_manifest()
            finally:
                self.db.close()

    def compressed_bytes(self):
        return sum(os.path.getsize(os.path.join(self.blocks_dir, f))
                   for f in os.listdir(self.blocks_dir) if f.endswith(("." + self._ext)))

    def fql(self, subject=None, predicate=None, trust_min=0.0, limit=10, exclude_below=True):
        """FQL: joint structure + trust query, trust-ranked, with a response provenance hash."""
        sql = "SELECT subject, predicate, object, trust, fp FROM nuc WHERE trust>=?"
        args = [trust_min]
        if subject:   sql += " AND subject=?";   args.append(_norm(subject))
        if predicate: sql += " AND predicate=?"; args.append(_norm(predicate))
        sql += " ORDER BY trust DESC LIMIT ?"; args.append(limit)
        rows = self.db.execute(sql, args).fetchall()
        rph = _h("RPH", *[r[4] for r in rows])
        return rows, rph

    def search(self, text, trust_min=0.0, limit=10):
        """Keyword fallback for FQL: match tokens against subject/object via LIKE, trust-ranked.
        Slower than the exact (subject,predicate) index, but lets a plain-language question
        find facts when the caller can't name the exact subject. Returns (rows, rph)."""
        toks = [t for t in _norm(text).split() if len(t) > 1]
        if not toks:
            return [], _h("RPH")
        where = " OR ".join("subject LIKE ? OR object LIKE ?" for _ in toks)
        args = []
        for t in toks:
            args += [f"%{t}%", f"%{t}%"]
        sql = (f"SELECT subject, predicate, object, trust, fp FROM nuc "
               f"WHERE trust>=? AND ({where}) ORDER BY trust DESC LIMIT ?")
        rows = self.db.execute(sql, [trust_min] + args + [limit]).fetchall()
        return rows, _h("RPH", *[r[4] for r in rows])

    def iter_all(self):
        for i in range(self.manifest["blocks"]):
            p = self._block_path(i)
            if not os.path.exists(p): continue
            if self.pack:
                with self._open(p, "rb") as f:
                    for rec in iter_packed(f): yield rec
            else:
                with self._open(p, "rt", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line: yield json.loads(line)

    def get(self, fp):
        row = self.db.execute("SELECT block FROM fp WHERE fingerprint=?", (fp,)).fetchone()
        if not row: return None
        if self.pack:
            with self._open(self._block_path(row[0]), "rb") as f:
                for rec in iter_packed(f):
                    if rec["semantic_fingerprint"] == fp: return rec
        else:
            with self._open(self._block_path(row[0]), "rt", encoding="utf-8") as f:
                for line in f:
                    rec = json.loads(line)
                    if rec.get("semantic_fingerprint") == fp: return rec
        return None

# ---------- in-process harvest + save self-test (used by the GUI, no subprocess) ----------
def det_records(start_n=1):
    """Infinite stream of deterministic Fact Units, yielding (n, packet) starting at start_n.
    Factorials only for n<=170 (they get astronomically large); everything else scales fine."""
    import math
    n = int(start_n) if int(start_n) >= 1 else 1
    while True:
        yield n, make_packet(f"{n}²", "equals", str(n * n), domain="mathematics")
        yield n, make_packet(f"{n}³", "equals", str(n * n * n), domain="mathematics")
        if n <= 170:
            yield n, make_packet(f"{n}!", "equals", str(math.factorial(n)), domain="mathematics")
        yield n, make_packet(f"{n}×{n}", "equals", str(n * n), domain="mathematics")
        yield n, make_packet(f"{n}+{n}", "equals", str(n + n), domain="mathematics")
        n += 1

def geo_records(start_n=1):
    """Geometry facts by rule: circle area/circumference, square area/perimeter."""
    import math
    n = int(start_n) if int(start_n) >= 1 else 1
    while True:
        yield n, make_packet(f"circle radius {n}", "area", str(round(math.pi * n * n, 4)), domain="geometry")
        yield n, make_packet(f"circle radius {n}", "circumference", str(round(2 * math.pi * n, 4)), domain="geometry")
        yield n, make_packet(f"square side {n}", "area", str(n * n), domain="geometry")
        yield n, make_packet(f"square side {n}", "perimeter", str(4 * n), domain="geometry")
        n += 1

def arithmetic_records(start_n=1):
    """Arithmetic tables by rule: n × 1..12."""
    n = int(start_n) if int(start_n) >= 1 else 1
    while True:
        for b in range(1, 13):
            yield n, make_packet(f"{n} × {b}", "equals", str(n * b), domain="arithmetic")
        n += 1

# ---------------------------------------------------------------------------
# Staged ingestion domains (Wave 2): History, News, Culture, Art.
# Each generator is FINITE and yields either (a) rule-TRUE facts (definitionally
# true, trust 0.99, like the math domains) or (b) curated public-domain reference
# facts stored as ATTRIBUTED claims (source names the reference; 'recorded by X'
# is not 'asserted true'). Nothing is fabricated; sample/news items are labelled.
# ---------------------------------------------------------------------------
_HIST_SRC = ("SRC-HIST", "Public-domain historical reference", "attributed", 0.9)
_CURATED_HISTORY = [
    ("476", "Western Roman Empire falls"), ("1066", "Norman conquest of England"),
    ("1215", "Magna Carta sealed"), ("1440", "Gutenberg printing press"),
    ("1492", "Columbus crosses the Atlantic"), ("1543", "Copernicus publishes heliocentrism"),
    ("1687", "Newton publishes the Principia"), ("1776", "US Declaration of Independence"),
    ("1789", "French Revolution begins"), ("1804", "Haitian independence"),
    ("1859", "Darwin publishes On the Origin of Species"), ("1865", "US Civil War ends"),
    ("1885", "First automobile (Benz)"), ("1903", "First powered flight (Wright)"),
    ("1945", "Second World War ends"), ("1947", "Transistor invented"),
    ("1969", "First Moon landing"), ("1989", "World Wide Web proposed"),
    ("1991", "Public Internet expands"), ("2007", "First smartphone era begins"),
]

def history_records(start_n=1):
    """Curated attributed milestones, then rule-TRUE temporal facts over years 1..2025."""
    import datetime
    idx = int(start_n) if int(start_n) >= 1 else 1
    k = len(_CURATED_HISTORY)
    n = idx
    # Phase A: curated attributed events.
    while n <= k:
        yr, desc = _CURATED_HISTORY[n - 1]
        yield n, make_packet("year %s" % yr, "recorded_event", desc, domain="history",
                             source=_HIST_SRC, trust=0.9)
        n += 1
    # Phase B: rule-true temporal facts (definitionally true) for each year.
    for yr in range(1, 2026):
        n += 1
        century = (yr - 1) // 100 + 1
        decade = (yr // 10) * 10
        leap = (yr % 4 == 0 and (yr % 100 != 0 or yr % 400 == 0))
        yield n, make_packet("year %d" % yr, "in_century", str(century), domain="history")
        yield n, make_packet("year %d" % yr, "in_decade", "%ds" % decade, domain="history")
        yield n, make_packet("year %d" % yr, "is_leap_year", "yes" if leap else "no", domain="history")

_NEWS_SRC = ("SRC-NEWS-SAMPLE", "Bundled EXAMPLE news item (not live)", "attributed", 0.5)
_SAMPLE_NEWS = [
    ("Example Daily", "reports a local council approved a new transit line"),
    ("Example Wire", "reports researchers published an open dataset"),
    ("Example Times", "reports a regional festival drew record attendance"),
    ("Example Post", "reports a new public library branch opened"),
    ("Example Herald", "reports a city adopted a tree-planting program"),
]

def news_records(start_n=1):
    """Bundled EXAMPLE attributed items (clearly not live news). Live news is web-agent driven."""
    idx = int(start_n) if int(start_n) >= 1 else 1
    for i in range(idx, len(_SAMPLE_NEWS) + 1):
        outlet, claim = _SAMPLE_NEWS[i - 1]
        yield i, make_packet(outlet, "sample_reports", claim, domain="news",
                             source=_NEWS_SRC, trust=0.5)

_CULT_SRC = ("SRC-CULT", "Public-domain cultural reference", "attributed", 0.9)
_CURATED_CULTURE = [
    ("Romance languages", "descend_from", "Latin"), ("Japanese tea ceremony", "origin", "Japan"),
    ("Flamenco", "origin", "Andalusia, Spain"), ("Haiku", "form", "Japanese 5-7-5 verse"),
    ("Diwali", "is_a", "festival of lights"), ("Lunar New Year", "observed_in", "East Asia"),
    ("Oktoberfest", "origin", "Munich, Germany"), ("Capoeira", "origin", "Brazil"),
    ("Gamelan", "is_a", "Indonesian ensemble music"), ("Origami", "is_a", "Japanese paper folding"),
]

def culture_records(start_n=1):
    """Curated attributed cultural reference facts, then rule-true calendar facts."""
    idx = int(start_n) if int(start_n) >= 1 else 1
    k = len(_CURATED_CULTURE)
    n = idx
    while n <= k:
        s, p, o = _CURATED_CULTURE[n - 1]
        yield n, make_packet(s, p, o, domain="culture", source=_CULT_SRC, trust=0.9)
        n += 1
    months = [("January",31),("February",28),("March",31),("April",30),("May",31),("June",30),
              ("July",31),("August",31),("September",30),("October",31),("November",30),("December",31)]
    for name, days in months:
        n += 1
        yield n, make_packet(name, "days_in_common_year", str(days), domain="culture")

_ART_SRC = ("SRC-ART", "Public-domain art reference", "attributed", 0.9)
_CURATED_ART = [
    ("Mona Lisa", "painted_by", "Leonardo da Vinci"), ("The Starry Night", "painted_by", "Vincent van Gogh"),
    ("Impressionism", "period", "late 19th century"), ("Cubism", "founded_by", "Picasso and Braque"),
    ("The Night Watch", "painted_by", "Rembrandt"), ("Guernica", "painted_by", "Pablo Picasso"),
    ("Baroque", "period", "17th century"), ("Surrealism", "period", "early 20th century"),
    ("The Great Wave", "created_by", "Hokusai"), ("Renaissance", "origin", "15th-century Italy"),
]

def art_records(start_n=1):
    """Curated attributed art-history facts, then rule-true color facts (grayscale hex)."""
    idx = int(start_n) if int(start_n) >= 1 else 1
    k = len(_CURATED_ART)
    n = idx
    while n <= k:
        s, p, o = _CURATED_ART[n - 1]
        yield n, make_packet(s, p, o, domain="art", source=_ART_SRC, trust=0.9)
        n += 1
    for v in range(0, 256):
        n += 1
        yield n, make_packet("grayscale level %d" % v, "hex", "#%02x%02x%02x" % (v, v, v), domain="art")

# Per-domain harvest logic + the AI strategy each domain uses.
DOMAIN_GEN = {
    "mathematics": det_records,
    "geometry": geo_records,
    "arithmetic": arithmetic_records,
    "history": history_records,
    "news": news_records,
    "culture": culture_records,
    "art": art_records,
}
DOMAIN_STRATEGY = {
    "mathematics": "Entity-first + confidence-weighted extraction",
    "geometry":    "Adaptive depth + ontology alignment",
    "arithmetic":  "Parallel batch generation",
    "history":     "Curated attributed events + rule-true temporal facts",
    "news":        "Attributed web harvest (sample seed bundled; live via web agent)",
    "culture":     "Curated attributed references + rule-true calendar facts",
    "art":         "Curated attributed works + rule-true color facts",
}
def domain_list():
    return [{"domain": d, "strategy": DOMAIN_STRATEGY.get(d, "structured"),
             "kind": "deterministic"} for d in DOMAIN_GEN]


def _read_manifest_file(store_path):
    """Tolerant standalone manifest read (no connection/locks); {} if missing/corrupt."""
    p = os.path.join(store_path, "manifest.json")
    try:
        with open(p, encoding="utf-8") as f:
            data = f.read()
        return json.loads(data) if data.strip() else {}
    except (ValueError, OSError):
        return {}


def manifest_value(store_path, key, default=0):
    return _read_manifest_file(store_path).get(key, default)


def domain_counts(store_path):
    """{domain: fact_count} from the per-domain tallies, for the Domain Navigator."""
    m = _read_manifest_file(store_path)
    return {k[len("facts_dom_"):]: v for k, v in m.items()
            if k.startswith("facts_dom_") and isinstance(v, (int, float))}

def _resume_key(domain):
    return "det_n" if domain == "mathematics" else "det_n_" + domain

def harvest_into(store_path, count, codec="gzip", block_mb=1024, progress=None, should_stop=None,
                 resume=True, domain="mathematics", batch=100000, verify=True):
    """FAST batched, RESUMING, per-domain harvest. Every run adds NEW facts (no 1M restart).
    count<=0 runs forever (24x7) until should_stop(). Batched disk+index writes make it
    ~2x+ faster per core than the old per-fact path; run several domains at once (agents) for
    much higher aggregate throughput. Returns total facts in the store."""
    gen = DOMAIN_GEN.get(domain, det_records)
    st = UFCSStore(store_path, block_mb, codec)
    key = _resume_key(domain)
    start_n = int(st.manifest.get(key, 0)) if resume else 1
    if resume and start_n <= 0 and domain == "mathematics":
        F = int(st.manifest.get("facts", 0))          # legacy store estimate (math only)
        if F <= 0:      start_n = 1
        elif F <= 850:  start_n = F // 5 + 1
        else:           start_n = 170 + (F - 850) // 4 + 1
    if start_n < 1:
        start_n = 1
    forever = (count is None or int(count) <= 0)
    # In continuous (24x7) mode, flush in smaller increments so a stop request is prompt:
    # the pending buffer at stop is bounded, so we never block on gzipping a huge batch.
    flush_batch = min(batch, 10000) if forever else batch
    made = 0; cur = start_n; sample_fp = None
    facts_before = int(st.manifest.get("facts", 0))
    buf = []; fprows = []; nucrows = []
    if st._blk is None:
        st._open_block()

    def flush():
        if not buf:
            return
        # Serialize the whole batch write and COMMIT inside the lock so no open write
        # transaction survives past the lock release (prevents "database is locked").
        with WRITE_LOCK:
            st.db.executemany("INSERT OR IGNORE INTO fp(fingerprint,block) VALUES(?,?)", fprows)
            if not st.no_fql:
                st.db.executemany("INSERT OR IGNORE INTO nuc(fp,subject,predicate,object,trust,block) VALUES(?,?,?,?,?,?)", nucrows)
            st._blk.write("".join(buf))
            st._bump("facts", len(buf))
            st._bump("facts_dom_" + domain, len(buf))   # per-domain tally for the Navigator
            st._set_key(key, cur)
            buf.clear(); fprows.clear(); nucrows.clear()
            st._blk.flush()
            st.db.commit()
            st._save_manifest()   # cheap now (no fsync) — keeps the live UI count fresh
            try:
                sz = os.path.getsize(st._block_path(st._blk_id))
            except OSError:
                sz = 0            # block file mid-rotation / not yet on disk → not full yet
            if sz >= st.block_target:
                st._blk.close(); st._blk = None; st._open_block()

    stopped = False
    try:
        for nn, rec in gen(start_n):
            if should_stop and should_stop():
                stopped = True
                break
            cur = nn
            f = rec["semantic_fingerprint"]; n = rec["nucleus"]
            if sample_fp is None:
                sample_fp = f
            trust = (rec.get("certification") or {}).get("trust_score", 0.99)
            fprows.append((f, st._blk_id))
            nucrows.append((f, _norm(n["subject"]), _norm(n["predicate"]), str(n["object"]), trust, st._blk_id))
            buf.append(json.dumps(rec, separators=(",", ":")) + "\n")
            made += 1
            if len(buf) >= flush_batch:
                flush()
                if progress: progress(made, st.manifest["facts"])
            elif progress and (made % 5000 == 0):
                # lightweight metering tick (no write) so facts/sec + counters stay live
                # even with a large write batch
                progress(made, facts_before + made)
            if not forever and made >= int(count):
                break
        flush()
        st._set_key(key, cur + 1)
        st.flush()
        if progress: progress(made, st.manifest["facts"])
    finally:
        st.close()
    # ---- built-in QUALITY CONTROL: independently re-open and prove the harvest is on disk ----
    # Skipped for background agents (verify=False): re-opening the store every cycle is
    # pure connection churn and adds nothing when a cycle harvests only a few thousand facts.
    if verify and not stopped:
        _verify_store(store_path, facts_before, sample_fp)
    v = UFCSStore(store_path); total = v.manifest.get("facts", 0); v.db.close()
    return total


def reconcile_manifest(store_path):
    """One-time truth pass: set the manifest's fact/duplicate counters to what is
    ACTUALLY in the index. Repairs counters left wrong by the old concurrency race
    (e.g. every agent showing the same 7.5M, or 0). Cheap enough to run once at boot."""
    try:
        st = UFCSStore(store_path)
    except Exception:
        return None
    try:
        true_facts = st.db.execute("SELECT COUNT(*) FROM fp").fetchone()[0]
        before = int(st.manifest.get("facts", 0))
        if true_facts != before:
            st._set_key("facts", true_facts)
            st.flush()
        return {"was": before, "now": true_facts}
    except Exception:
        return None
    finally:
        st.close()


def _verify_store(store_path, facts_before, sample_fp):
    """Re-open the store from scratch and confirm the harvest is really persisted:
    the fact count grew (or was already full) AND a just-written fact reads back.
    Records the result in manifest['last_verify'] so the UI can show pass/fail."""
    res = {"ok": False, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "facts_before": facts_before, "facts_after": 0, "sample_ok": None, "detail": ""}
    try:
        v = UFCSStore(store_path)
        after = int(v.manifest.get("facts", 0))
        res["facts_after"] = after
        sample_ok = True
        if sample_fp is not None:
            sample_ok = v.get(sample_fp) is not None
            res["sample_ok"] = sample_ok
        grew_or_full = after >= facts_before      # never lost data
        res["ok"] = bool(after > 0 and sample_ok and grew_or_full)
        res["detail"] = (f"{after:,} facts on disk"
                         + ("" if sample_fp is None else f"; sample fact read back = {sample_ok}"))
        v._set_key("last_verify", res)
        v.close()
    except Exception as e:
        try:
            v2 = UFCSStore(store_path); res["detail"] = "verify error: " + str(e)
            v2._set_key("last_verify", res); v2.close()
        except Exception:
            pass
    return res


def save_self_test(base_dir):
    """Prove we can create a store and read it back under base_dir.
    Returns (ok, facts, path, error)."""
    import shutil
    p = os.path.join(base_dir, "_selftest")
    try:
        os.makedirs(base_dir, exist_ok=True)
        if os.path.exists(p):
            shutil.rmtree(p, ignore_errors=True)
        st = UFCSStore(p, 1024, "gzip")
        for rec in deterministic_facts(50):
            st.add(rec)
        st.close()
        st2 = UFCSStore(p)
        facts = st2.manifest["facts"]
        st2.db.close()
        shutil.rmtree(p, ignore_errors=True)
        return (facts >= 50, facts, p, None)
    except Exception as e:
        return (False, 0, p, str(e))


# ---------- deterministic harvest ----------
def _primes(n):
    out = []; c = 2
    while len(out) < n:
        ok = True
        for q in out:
            if q * q > c: break
            if c % q == 0: ok = False; break
        if ok: out.append(c)
        c += 1
    return out

def deterministic_facts(count):
    """Yield up to `count` genuinely computable facts across math domains."""
    i = 0
    # squares, cubes, multiplication, factorials, then primes as a stream
    n = 1
    while i < count:
        for subj, pred, obj in (
            (f"{n}²", "equals", str(n * n)),
            (f"{n}³", "equals", str(n * n * n)),
            (f"{n}!", "equals", str(__import__('math').factorial(n)) if n <= 170 else "overflow"),
            (f"{n}×{n}", "equals", str(n * n)),
            (f"{n}+{n}", "equals", str(n + n)),
        ):
            if obj == "overflow": continue
            yield make_packet(subj, pred, obj, domain="mathematics")
            i += 1
            if i >= count: return
        n += 1

# ---------- CLI ----------
def cmd_harvest(a):
    forever = (a.count is None or a.count <= 0)
    if forever:
        print("  RUN-FOREVER mode (--count 0): harvesting new facts until you press Ctrl+C…", flush=True)
    last = [0]
    def prog(made, total):
        if made - last[0] >= 100000 or made == 0:
            last[0] = made
            print(f"  +{made:,} generated · {total:,} stored total", flush=True)
    try:
        harvest_into(a.store, a.count, a.codec, a.block_mb, progress=prog, resume=True)
    except KeyboardInterrupt:
        print("\n  stopped by user.", flush=True)
    _report(a.store)

def cmd_ingest(a):
    st = UFCSStore(a.store, a.block_mb, a.codec, a.pack, a.no_fql)
    src = sys.stdin if a.file == "-" else open(a.file)
    n = 0
    for line in src:
        line = line.strip()
        if not line: continue
        st.add(json.loads(line)); n += 1
        if n % 100000 == 0: st.flush(); print(f"  ingested {n:,}", flush=True)
    st.close()
    if src is not sys.stdin: src.close()
    _report(a.store)

def cmd_stats(a): _report(a.store)

def _report(path):
    st = UFCSStore(path)
    facts = st.manifest["facts"]; raw = st.manifest["raw_bytes"]; comp = st.compressed_bytes()
    ratio = (raw / comp) if comp else 0
    print("\n=== UFCS store ===")
    print(f"  path            {path}")
    print(f"  codec           {st.codec}{'  + packed binary' if st.pack else ''}")
    print(f"  fql index       {'OFF (--no-fql-index)' if st.no_fql else 'on'}")
    print(f"  blocks          {st.manifest['blocks']}  (~{st.manifest['block_mb']} MB target each)")
    print(f"  facts stored    {facts:,}")
    print(f"  duplicates      {st.manifest['duplicates']:,}  (skipped by fingerprint)")
    print(f"  raw bytes       {raw/1e6:,.1f} MB  ({raw/facts:.0f} B/fact)" if facts else "  raw bytes 0")
    print(f"  compressed      {comp/1e6:,.1f} MB  ({comp/facts:.0f} B/fact)" if facts else "  compressed 0")
    print(f"  compression     {ratio:.2f}x")
    idx = sum(os.path.getsize(os.path.join(path, f)) for f in os.listdir(path) if f.startswith("index.sqlite"))
    total = comp + idx
    print(f"  index (sqlite)  {idx/1e6:,.1f} MB")
    if facts:
        print(f"  ON-DISK TOTAL   {total/1e6:,.1f} MB  ({total/facts:.0f} B/fact all-in)")
        print(f"  capacity        1 TB -> {1e12/(comp/facts)/1e9:,.1f} B facts (blocks only) · "
              f"{1e12/(total/facts)/1e9:,.1f} B facts (all-in) · 20 TB -> {20e12/(total/facts)/1e9:,.1f} B all-in")
    st.db.close()

def cmd_get(a):
    st = UFCSStore(a.store); rec = st.get(a.fingerprint); st.db.close()
    print(json.dumps(rec, indent=2) if rec else "not found")

def cmd_verify(a):
    st = UFCSStore(a.store)
    fp = fingerprint(a.subject, a.predicate, a.object)
    rec = st.get(fp); st.db.close()
    print(f"fingerprint {fp}")
    print("VERIFIED — present in store" if rec else "UNKNOWN — not in store")
    if rec: print(json.dumps(rec, indent=2))

def cmd_export(a):
    import shutil
    st = UFCSStore(a.store)
    outf = os.path.join(a.out, "f"); os.makedirs(outf, exist_ok=True)
    n = 0
    for rec in st.iter_all():
        fp = rec.get("semantic_fingerprint")
        if not fp: continue
        d = os.path.join(outf, fp[:2]); os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, fp + ".json"), "w") as f:
            f.write(json.dumps(rec, separators=(",", ":")))
        n += 1
        if n % 100000 == 0: print(f"  exported {n:,} objects", flush=True)
    bdir = os.path.join(a.out, "blocks"); os.makedirs(bdir, exist_ok=True)
    for f in os.listdir(st.blocks_dir):
        shutil.copy2(os.path.join(st.blocks_dir, f), os.path.join(bdir, f))
    if a.console and os.path.exists(a.console):
        shutil.copy2(a.console, os.path.join(a.out, "index.html"))
    with open(os.path.join(a.out, "manifest.json"), "w") as f:
        json.dump({"facts": n, "codec": st.codec, "packed": st.pack, "layout": "content-addressed /f/<fp[:2]>/<fp>.json"}, f, indent=2)
    st.db.close()
    print(f"exported {n:,} content-addressed objects + {len(os.listdir(bdir))} blocks -> {a.out}")

def cmd_query(a):
    st = UFCSStore(a.store)
    if st.no_fql:
        st.db.close()
        print("This store was built with --no-fql-index; structured FQL is unavailable.\n"
              "Dedupe and `get`/`verify` by fingerprint still work. Re-ingest without --no-fql-index to enable FQL.")
        return
    rows, rph = st.fql(a.subject, a.predicate, a.trust_min, a.limit); st.db.close()
    print(f"FQL  subject={a.subject!r}  predicate={a.predicate!r}  trust>={a.trust_min}")
    for s, p, o, t, fp in rows:
        print(f"  [{t:.3f}]  {s}  {p}  {o}   {fp[:12]}…")
    print(f"  {len(rows)} result(s) · response_provenance_hash {rph[:24]}…")

def main():
    ap = argparse.ArgumentParser(description="Local UFCS Fact block store (1 GB gzip blocks + SQLite index).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    def add_block(p):
        p.add_argument("--block-mb", type=int, default=1024, help="target compressed block size in MB (default 1024 = 1 GiB)")
        p.add_argument("--codec", choices=list(CODECS), default="gzip", help="block compression: gzip (fast), bz2/xz (denser, slower). Fixed once the store exists.")
        p.add_argument("--pack", action="store_true", help="binary packed blocks: much denser, but stores the minimal Fact Unit (nucleus+polarity+fingerprint+trust+domain), not the full JSON packet")
        p.add_argument("--no-fql-index", action="store_true", dest="no_fql", help="skip the FQL structure index (dedupe + get still work; cuts most index disk overhead)")

    p = sub.add_parser("harvest", help="generate N deterministic facts and store them")
    p.add_argument("store"); p.add_argument("--count", type=int, default=1000000); add_block(p); p.set_defaults(fn=cmd_harvest)

    p = sub.add_parser("ingest", help="load facts from a JSONL file (or - for stdin)")
    p.add_argument("store"); p.add_argument("file"); add_block(p); p.set_defaults(fn=cmd_ingest)

    p = sub.add_parser("stats", help="show store statistics"); p.add_argument("store"); p.set_defaults(fn=cmd_stats)
    p = sub.add_parser("get", help="fetch a fact by fingerprint"); p.add_argument("store"); p.add_argument("fingerprint"); p.set_defaults(fn=cmd_get)

    p = sub.add_parser("export", help="write a content-addressed object tree for CDN/Bunny deploy")
    p.add_argument("store"); p.add_argument("out"); p.add_argument("--console", default=None, help="optional console HTML to place at index.html")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("query", aliases=["fql"], help="FQL: joint structure + trust query")
    p.add_argument("store")
    p.add_argument("--subject", default=None)
    p.add_argument("--predicate", default=None)
    p.add_argument("--trust-min", type=float, default=0.0, dest="trust_min")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(fn=cmd_query)
    p = sub.add_parser("verify", help="verify a subject/predicate/object claim")
    p.add_argument("store"); p.add_argument("subject"); p.add_argument("predicate"); p.add_argument("object"); p.set_defaults(fn=cmd_verify)

    a = ap.parse_args(); a.fn(a)

if __name__ == "__main__":
    main()
