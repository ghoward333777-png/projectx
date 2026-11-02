"""Instrumentation for the harvest: every process, every I/O, every stage a UFCS record passes through — and every failure —
written to plain log files (JSON Lines) that can be read back, exported and analysed (tools/trace_report.py).

Where:  <shared folder>\\trace\\<process>-<date>.jsonl   (D:\\QB\\commons\\trace with a data drive). One file per process and
        day, so the agents (one process each) never wait for each other to log.

What each line is ("ev"):
  run        an agent or team starts / ends: dataset, pid, settings, totals
  stages     time and counts per stage since the last line (every batch): source (read + decompress + parse), rule, filter,
             fingerprint, buffer, sort, db_insert, db_links, db_progress, db_commit, progress_mark, stop_check, harvest_log,
             net_wait (waiting for a connection slot), net_connect (to first byte), net_read, starved (the parser waited for the
             network), decompress — each {n, ms, bytes}. Durations are measured with a monotonic clock in nanoseconds.
  batch      one committed batch: rows from–to, facts offered / new, wall-clock times of its first row, last row and commit,
             network and decompressed bytes in it
  record     one UFCS record followed end to end (a fixed 1-in-N sample chosen by its fingerprint, so the same records are
             followed every run): wall-clock nanosecond stamps of chunk arrival, decompression, row parsed, rule, fingerprint,
             buffered, sorted, inserted, committed — and whether it was new or a duplicate
  io         one network exchange: host, status, time to first byte, seconds, bytes
  fail       every failure: where, kind, error type and message, the traceback's last lines, dataset/part/row, retried or not
  span       a timed step of a harvest team (strategist, planner, each task, curator, checks) with its outcome
  event      anything else worth a timestamp (stopped, waiting to retry, dedupe, heartbeat trouble)

Cost: a few nanosecond-clock reads per row (about 0.2 µs each) and one log line per batch; the sampled records add one line
per N records (default N = 10,000: about 300 lines a minute at 3 million facts a minute). The setting trace:sample changes N
(1 = every record — only for short tests: a billion records would be about 400 GB of log), trace:on = off stops it all.
"""
import gzip, json, os, socket, sys, threading, time, traceback, zipfile

DEFAULT_SAMPLE = 10_000
_NS = time.perf_counter_ns
_WALL = time.time_ns


class Tracer:
    def __init__(self):
        self.on, self.sample, self.folder, self.proc = False, 0, None, "process"
        self.st, self._buf, self._lock, self._f, self._day = {}, [], threading.Lock(), None, None
        self.ctx = {}
        self.chunk_wall = self.decomp_wall = 0           # the newest chunk's arrival / decompression (wall ns)
        self.net_bytes = self.decomp_bytes = 0

    # -- set-up
    def configure(self, folder, proc, sample=DEFAULT_SAMPLE, on=True, **ctx):
        self.close()
        self.on, self.folder, self.proc = bool(on and folder), folder, "".join(c if c.isalnum() or c in "-_." else "_" for c in proc)
        self.sample = max(0, int(sample or 0))
        self.ctx = dict(ctx, host=socket.gethostname(), pid=os.getpid())
        self.st = {}
        if self.on:
            os.makedirs(folder, exist_ok=True)
        return self

    def from_commons(self, commons, proc, **ctx):
        """settings from the shared database: trace:on (default on), trace:sample (default 10,000)"""
        try:
            on = (commons.setting("trace:on", "on") or "on") != "off"
            sample = int(commons.setting("trace:sample", DEFAULT_SAMPLE) or 0)
        except Exception:
            on, sample = True, DEFAULT_SAMPLE
        return self.configure(os.path.join(commons.folder, "trace"), proc, sample, on, **ctx)

    # -- measuring
    def add(self, stage, ns, n=1, nbytes=0):
        s = self.st.get(stage)
        if s is None:
            s = self.st[stage] = [0, 0, 0, 0]
        s[0] += n; s[1] += ns; s[2] += nbytes
        if ns > s[3]:
            s[3] = ns

    def sampled(self, fp):
        """deterministic 1-in-N choice by fingerprint (the same records are followed in every run and on every computer)"""
        return self.on and self.sample > 0 and int.from_bytes(fp[:4], "big") % self.sample == 0

    # -- writing
    def _line(self, d, now=False):
        if not self.on:
            return
        d.setdefault("t", _WALL())
        with self._lock:
            self._buf.append(json.dumps(d, ensure_ascii=False, default=str, separators=(",", ":")))
            if now or len(self._buf) >= 200:
                self._write()

    def _write(self):
        if not self._buf:
            return
        day = time.strftime("%Y%m%d")
        try:
            if self._f is None or self._day != day:
                if self._f:
                    self._f.close()
                self._f = open(os.path.join(self.folder, "%s-%s.jsonl" % (self.proc, day)), "a", encoding="utf-8")
                self._day = day
            self._f.write("\n".join(self._buf) + "\n")
            self._f.flush()
        except OSError as e:                       # logging never stops the harvest; the trouble is said once on stderr
            print("trace log not written: %s" % e, file=sys.stderr)
        self._buf = []

    def event(self, ev, **fields):
        self._line(dict(fields, ev=ev, proc=self.proc), now=ev in ("run", "fail"))

    def io(self, host, status, seconds, nbytes=0, ttfb=None, **extra):
        self._line(dict(extra, ev="io", proc=self.proc, host=host, status=status, s=round(seconds, 4), bytes=nbytes,
                        ttfb=None if ttfb is None else round(ttfb, 4)))

    def fail(self, where, exc, retried=False, **ctx):
        key = (where, type(exc).__name__ if isinstance(exc, BaseException) else str(exc))
        minute = int(time.time() // 60)
        fl = self.__dict__.setdefault("_flood", {})
        m, n, dropped = fl.get(key, (minute, 0, 0))
        if m != minute:
            if dropped:
                self._line({"ev": "fail_suppressed", "proc": self.proc, "where": key[0], "kind": key[1], "count": dropped, "minute": m}, now=True)
            m, n, dropped = minute, 0, 0
        if n >= 20:                                # the same failure again and again: counted, not written each time
            fl[key] = (m, n, dropped + 1)
            return
        fl[key] = (m, n + 1, dropped)
        self._fail(where, exc, retried, **ctx)

    def _fail(self, where, exc, retried=False, **ctx):
        tb = traceback.format_exception(type(exc), exc, exc.__traceback__) if isinstance(exc, BaseException) else []
        self._line(dict(ctx, ev="fail", proc=self.proc, where=where, kind=type(exc).__name__ if isinstance(exc, BaseException) else str(exc),
                        msg=str(exc)[:500], retried=bool(retried), tb=[l.strip() for l in "".join(tb).strip().splitlines()[-6:]]), now=True)

    def record(self, rec):
        rec["ev"], rec["proc"] = "record", self.proc
        self._line(rec)

    def span(self, name, seconds, ok=True, **extra):
        self._line(dict(extra, ev="span", proc=self.proc, name=name, s=round(seconds, 4), ok=bool(ok)))

    def flush_stages(self, **ctx):
        """the stage totals since the last call, as one line (then reset)"""
        if not self.on or not self.st:
            return
        st, self.st = self.st, {}
        self._line(dict(ctx, ev="stages", proc=self.proc,
                        stages={k: {"n": v[0], "ms": round(v[1] / 1e6, 3), "bytes": v[2], "max_ms": round(v[3] / 1e6, 3)} for k, v in st.items()}))

    def close(self):
        with self._lock:
            self._write()
            if self._f:
                try:
                    self._f.close()
                except OSError:
                    pass
            self._f = None


TR = Tracer()                                     # one per process (every bulk agent is its own process)


class timed:
    """with timed("stage"): ...  — adds the time to the stage"""
    __slots__ = ("stage", "t", "nbytes")

    def __init__(self, stage, nbytes=0):
        self.stage, self.nbytes = stage, nbytes

    def __enter__(self):
        self.t = _NS()
        return self

    def __exit__(self, *a):
        TR.add(self.stage, _NS() - self.t, 1, self.nbytes)
        return False


# ------------------------------------------------------------------------------------------------ storage: internal vs external
def bench_storage(folder, mb=256, rows=300_000, label=None):
    """how fast a folder's drive does what the harvest does, measured in that folder (then removed):
    sequential write + flush to disk, sequential read, small synced writes (commit latency), and the bulk agents' own
    pattern — batches of fingerprint-keyed rows into a WAL SQLite file, committed. Returns MB/s, ms and rows/s."""
    import hashlib, shutil, sqlite3
    d = os.path.join(folder, ".qb-storage-test-%d" % os.getpid())
    os.makedirs(d, exist_ok=True)
    out = {"label": label or folder, "folder": os.path.abspath(folder), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        try:
            out["free_gb"] = round(shutil.disk_usage(folder).free / 1e9, 1)
        except OSError:
            pass
        blob = os.urandom(1 << 20)
        p = os.path.join(d, "seq.bin")
        t0 = time.perf_counter()
        with open(p, "wb") as f:
            for _ in range(mb):
                f.write(blob)
            f.flush(); os.fsync(f.fileno())
        out["seq_write_mb_s"] = round(mb / (time.perf_counter() - t0), 1)
        t0 = time.perf_counter()
        with open(p, "rb") as f:
            while f.read(1 << 22):
                pass
        out["seq_read_mb_s"] = round(mb / (time.perf_counter() - t0), 1)   # may be served from memory: read it as an upper bound
        os.remove(p)
        lat = []
        with open(os.path.join(d, "sync.bin"), "wb") as f:
            for _ in range(50):
                f.write(blob[:4096]); f.flush()
                t1 = time.perf_counter(); os.fsync(f.fileno()); lat.append(time.perf_counter() - t1)
        lat.sort()
        out["fsync_ms_median"], out["fsync_ms_p95"] = round(lat[len(lat) // 2] * 1000, 2), round(lat[int(len(lat) * 0.95)] * 1000, 2)
        db = sqlite3.connect(os.path.join(d, "shard.sqlite"))
        db.execute("PRAGMA journal_mode=WAL"); db.execute("PRAGMA synchronous=NORMAL"); db.execute("PRAGMA cache_size=-131072")
        db.execute("CREATE TABLE facts (fp BLOB PRIMARY KEY, s TEXT, p INTEGER, o TEXT, part INTEGER, row INTEGER) WITHOUT ROWID")
        batch = 100_000
        t0 = time.perf_counter(); commits = []
        for b in range(0, rows, batch):
            data = sorted((hashlib.sha256(b"%d" % i).digest()[:16], "Q%d" % i, 1, "value %d" % i, 1, i) for i in range(b, min(rows, b + batch)))
            db.executemany("INSERT OR IGNORE INTO facts VALUES (?,?,?,?,?,?)", data)
            t1 = time.perf_counter(); db.commit(); commits.append(time.perf_counter() - t1)
        el = time.perf_counter() - t0
        db.close()
        out["sqlite_rows_s"] = round(rows / el)
        out["sqlite_commit_ms_max"] = round(max(commits) * 1000, 1)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return out


def compare_storage(folders, mb=256, rows=300_000):
    """bench_storage on each {label: folder}; the result names the faster drive for the bulk agents' own pattern"""
    res = []
    for label, f in folders.items():
        try:
            res.append(bench_storage(f, mb, rows, label))
        except Exception as e:
            res.append({"label": label, "folder": f, "error": "%s: %s" % (type(e).__name__, e)})
    good = [r for r in res if "sqlite_rows_s" in r]
    best = max(good, key=lambda r: r["sqlite_rows_s"]) if good else None
    return {"drives": res, "fastest_for_facts": best["label"] if best else None,
            "ratio": round(best["sqlite_rows_s"] / min(r["sqlite_rows_s"] for r in good), 2) if len(good) > 1 else None}


# ------------------------------------------------------------------------------------------------ analysis
TOP = ["open_commons", "open_shard", "resume_skip", "source", "rule", "filter", "fingerprint", "buffer", "sort", "db_insert",
       "db_links", "db_progress", "db_commit", "progress_mark", "stop_check", "harvest_log"]
INSIDE_SOURCE = ["net_wait", "net_connect", "net_read", "starved", "decompress"]
WAITS = {"net_wait": "waiting for a free connection slot (our own limit per server)",
         "starved": "the parser waiting for downloaded bytes (network slower than parsing)",
         "polite_gap": "our pause between requests to one site",
         "net_connect": "connecting to the server and waiting for its first byte"}
STEPS = ["chunk", "decompressed", "row", "rule", "buffered", "sorted", "inserted", "committed"]


def _pct(v, q):
    if not v:
        return None
    v = sorted(v)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]


def analyze(lines):
    """the logs → where the time goes, every congestion and slow I/O, the drives, every failure — and what to change"""
    ds, procs, hosts, fails, spans, storage, events, recs = {}, set(), {}, {}, {}, [], [], []
    t_min = t_max = None
    for l in lines:
        ev, t = l.get("ev"), l.get("t")
        procs.add(l.get("proc"))
        if t:
            t_min = t if t_min is None or t < t_min else t_min
            t_max = t if t_max is None or t > t_max else t_max
        key = l.get("dataset") or (("app:" + l["app"]) if l.get("app") else (l.get("proc") or "?").split("-")[0])
        d = ds.setdefault(key, {"stages": {}, "batches": [], "runs": [], "first": t, "last": t, "new": 0, "offered": 0})
        if t:
            d["first"] = min(d["first"] or t, t); d["last"] = max(d["last"] or t, t)
        if ev == "stages":
            for k, v in l["stages"].items():
                a = d["stages"].setdefault(k, {"n": 0, "ms": 0.0, "bytes": 0, "max_ms": 0.0})
                a["n"] += v["n"]; a["ms"] += v["ms"]; a["bytes"] += v["bytes"]; a["max_ms"] = max(a["max_ms"], v["max_ms"])
        elif ev == "batch":
            d["batches"].append(l); d["new"] += l.get("new") or 0; d["offered"] += l.get("offered") or 0
        elif ev == "run":
            d["runs"].append(l)
        elif ev == "io":
            h = hosts.setdefault(l.get("host") or "?", {"n": 0, "bytes": 0, "s": 0.0, "ttfb": [], "status": {}, "ends": {}})
            h["n"] += 1; h["bytes"] += l.get("bytes") or 0; h["s"] += l.get("s") or 0
            if l.get("ttfb") is not None:
                h["ttfb"].append(l["ttfb"])
            h["status"][str(l.get("status"))] = h["status"].get(str(l.get("status")), 0) + 1
            h["ends"][str(l.get("end"))] = h["ends"].get(str(l.get("end")), 0) + 1
        elif ev in ("fail", "fail_suppressed"):
            k = (l.get("where"), l.get("kind"), l.get("host") or l.get("dataset") or l.get("app") or "", l.get("code"))
            f = fails.setdefault(k, {"where": k[0], "kind": k[1], "about": k[2], "code": k[3], "count": 0, "retried": 0,
                                     "first": t, "last": t, "example": l.get("msg"), "tb": l.get("tb")})
            f["count"] += l.get("count", 1) if ev == "fail_suppressed" else 1; f["retried"] += bool(l.get("retried")); f["last"] = t
        elif ev == "span":
            sp = spans.setdefault(l["name"], {"s": [], "failed": 0})
            sp["s"].append(l.get("s") or 0); sp["failed"] += not l.get("ok", True)
        elif ev == "storage":
            storage.append(l)
        elif ev == "record":
            recs.append(l)
        elif ev in ("congestion", "dedupe", "dedupe_pair", "round"):
            events.append(l)
    out = {"span_s": round((t_max - t_min) / 1e9, 1) if t_min else 0, "processes": len(procs), "datasets": [], "congestion": [],
           "io": [], "failures": [], "teams": [], "records": None, "storage": storage[-6:], "advice": []}
    for key, d in sorted(ds.items()):
        st = d["stages"]
        if not st and not d["batches"]:
            continue
        top = {k: st[k]["ms"] for k in TOP if k in st}
        busy = sum(top.values()) or 0.0
        ran = [r.get("seconds") for r in d["runs"] if r.get("phase") == "end" and r.get("seconds")]
        wall = sum(ran) if ran else ((d["last"] or 0) - (d["first"] or 0)) / 1e9      # time the agents ran (not the gaps between runs)
        commits = [ (b["committed"] - b["inserted"]) / 1e6 for b in d["batches"] if b.get("committed") and b.get("inserted")]
        row = {"dataset": key, "wall_s": round(wall, 1), "facts_new": d["new"], "facts_offered": d["offered"],
               "facts_per_min": round(d["new"] / wall * 60) if wall > 0 else None, "measured_ms": round(busy, 1),
               "stages": [{"stage": k, "ms": round(v, 1), "share": round(v / busy, 4) if busy else 0, "n": st[k]["n"],
                           "us_per_item": round(v * 1000 / st[k]["n"], 2) if st[k]["n"] else None, "max_ms": st[k]["max_ms"]}
                          for k, v in sorted(top.items(), key=lambda kv: -kv[1])],
               "inside_source": {k: {"ms": round(st[k]["ms"], 1), "n": st[k]["n"], "mb": round(st[k]["bytes"] / 1e6, 1)} for k in INSIDE_SOURCE if k in st},
               "commit_ms_p50": _pct(commits, 0.5), "commit_ms_p95": _pct(commits, 0.95), "commit_ms_max": max(commits) if commits else None,
               "batches": len(d["batches"])}
        row["bottleneck"] = _verdict(row, st)
        out["datasets"].append(row)
        for k, v in st.items():
            if k in WAITS or k.startswith("db_lock_wait"):
                if v["ms"] > 0:
                    out["congestion"].append({"where": key, "what": WAITS.get(k, "waiting for the shared database's write lock (%s)" % k.split(":")[-1]),
                                              "stage": k, "total_s": round(v["ms"] / 1000, 2), "times": v["n"], "worst_s": round(v["max_ms"] / 1000, 2),
                                              "share_of_busy": round(v["ms"] / busy, 4) if busy else None})
        if commits and _pct(commits, 0.95) and _pct(commits, 0.95) > 2000:
            out["congestion"].append({"where": key, "what": "slow disk commits (the drive)", "stage": "db_commit", "total_s": round(sum(commits) / 1000, 1),
                                      "times": len(commits), "worst_s": round(max(commits) / 1000, 2), "share_of_busy": None})
    for e in events:
        if e["ev"] == "congestion":
            out["congestion"].append({"where": e.get("proc"), "what": e.get("what"), "stage": "event", "total_s": e.get("waited_s"), "times": 1,
                                      "worst_s": e.get("waited_s"), "share_of_busy": None})
    out["congestion"].sort(key=lambda c: -(c["total_s"] or 0))
    for h, v in sorted(hosts.items(), key=lambda kv: -kv[1]["bytes"]):
        refused = sum(n for s_, n in v["status"].items() if s_ in ("429", "503"))
        out["io"].append({"host": h, "requests": v["n"], "mb": round(v["bytes"] / 1e6, 1), "mb_s": round(v["bytes"] / 1e6 / v["s"], 2) if v["s"] else None,
                          "ttfb_p50": _pct(v["ttfb"], 0.5), "ttfb_p95": _pct(v["ttfb"], 0.95), "status": v["status"], "ends": v["ends"], "refused": refused})
        if refused:
            out["congestion"].append({"where": h, "what": "the server refused us (HTTP 429/503: slow down)", "stage": "io", "total_s": None,
                                      "times": refused, "worst_s": None, "share_of_busy": None})
    out["failures"] = sorted(fails.values(), key=lambda f: -f["count"])
    out["teams"] = [{"name": k, "count": len(v["s"]), "median_s": _pct(v["s"], 0.5), "p95_s": _pct(v["s"], 0.95), "failed": v["failed"]}
                    for k, v in sorted(spans.items(), key=lambda kv: -sum(kv[1]["s"]))]
    if recs:
        deltas = {}
        for r in recs:
            w = r.get("w") or {}
            prev = None
            for st_ in STEPS:
                if w.get(st_):
                    if prev:
                        deltas.setdefault("%s→%s" % (prev[0], st_), []).append((w[st_] - prev[1]) / 1e6)
                    prev = (st_, w[st_])
            first = next((w[x] for x in STEPS if w.get(x)), None)
            if first and w.get("committed"):
                deltas.setdefault("first byte seen → committed (whole path)", []).append((w["committed"] - first) / 1e6)
        out["records"] = {"followed": len(recs), "outcomes": {o: sum(1 for r in recs if r.get("outcome") == o) for o in ("new", "duplicate", "missing")},
                          "steps_ms": [{"step": k, "p50": round(_pct(v, 0.5), 3), "p95": round(_pct(v, 0.95), 3), "max": round(max(v), 3)}
                                       for k, v in deltas.items()]}
    out["advice"] = _advice(out)
    return out


def _verdict(row, st):
    if not row["stages"]:
        return "nothing measured"
    first = row["stages"][0]
    k = first["stage"]
    ins = row["inside_source"]
    if k == "source":
        starved, dec, wait = ins.get("starved", {}).get("ms", 0), ins.get("decompress", {}).get("ms", 0), ins.get("net_wait", {}).get("ms", 0)
        if wait > first["ms"] * 0.3:
            return "connection-slot congestion: agents queue for the few connections a server allows"
        if starved > first["ms"] * 0.4:
            return "network-bound: the parser waits for bytes (%.0f%% of reading time)" % (100 * starved / first["ms"])
        if dec > first["ms"] * 0.4:
            return "CPU-bound in decompression"
        return "reading and parsing the source (CPU)"
    if k in ("db_commit", "db_insert", "db_links", "db_progress"):
        return "disk-bound: writing the shard (%s %.0f%%)" % (k, 100 * first["share"])
    if k in ("rule", "fingerprint", "buffer", "sort", "filter"):
        return "CPU-bound: %s (%.0f%%)" % (k, 100 * first["share"])
    return "%s (%.0f%%)" % (k, 100 * first["share"])


def _advice(o):
    a = []
    for d in o["datasets"]:
        b = d["bottleneck"]
        if b.startswith("network-bound"):
            a.append("%s: network-bound — more connections or mirrors help; more agents do not." % d["dataset"])
        elif b.startswith("connection-slot"):
            a.append("%s: agents queue for connection slots — raise the per-server connections if the server allows it, or add mirrors." % d["dataset"])
        elif b.startswith("disk-bound"):
            a.append("%s: disk-bound — a faster drive for the shards (compare the drives), or larger batches, would help." % d["dataset"])
        elif b.startswith("CPU-bound"):
            a.append("%s: CPU-bound — more agents (cores) help; the slowest stage is named above." % d["dataset"])
    for c in o["congestion"][:5]:
        if c["stage"].startswith("db_lock_wait") and (c["total_s"] or 0) > 10:
            a.append("The shared database is a meeting point: %s s spent queueing for its write lock (%s)." % (c["total_s"], c["where"]))
    if o["storage"]:
        last = o["storage"][-1]
        if last.get("fastest_for_facts"):
            a.append("Drives: %s is faster for the agents' writes (×%s)." % (last["fastest_for_facts"], last.get("ratio")))
    if o["failures"]:
        f = o["failures"][0]
        a.append("Most frequent failure: %s %s (%s) — %d times." % (f["where"], f["kind"], f["about"], f["count"]))
    return a


def text_report(o):
    L = ["QueryBook harvest instrumentation — %s s of logs from %d processes" % (o["span_s"], o["processes"]), ""]
    for d in o["datasets"]:
        L.append("%s: %s new facts (%s offered) in %s s = %s/min; bottleneck: %s" % (d["dataset"], format(d["facts_new"], ","), format(d["facts_offered"], ","),
                                                                             d["wall_s"], format(d["facts_per_min"] or 0, ","), d["bottleneck"]))
        for s_ in d["stages"][:8]:
            L.append("    %-14s %6.1f%%  %10.1f ms  %s µs each (%s times)" % (s_["stage"], 100 * s_["share"], s_["ms"], s_["us_per_item"], format(s_["n"], ",")))
        if d["inside_source"]:
            L.append("    inside source: " + ", ".join("%s %.0f ms%s" % (k, v["ms"], (" %.1f MB" % v["mb"]) if v["mb"] else "") for k, v in d["inside_source"].items()))
        if d["commit_ms_p50"] is not None:
            L.append("    disk commit per batch: median %.1f ms, p95 %.1f ms, worst %.1f ms" % (d["commit_ms_p50"], d["commit_ms_p95"], d["commit_ms_max"]))
    L += ["", "CONGESTION AND WAITING (largest first)"] + ["  %-28s %-60s %s s total, %s times, worst %s s" % (c["where"], c["what"], c["total_s"], c["times"], c["worst_s"])
                                                         for c in o["congestion"][:20]]
    L += ["", "NETWORK I/O"] + ["  %-34s %5d requests %9.1f MB  %s MB/s  first byte p50 %s s p95 %s s  status %s" % (
        h["host"], h["requests"], h["mb"], h["mb_s"], h["ttfb_p50"], h["ttfb_p95"], h["status"]) for h in o["io"][:20]]
    if o["records"]:
        r = o["records"]
        L += ["", "RECORDS FOLLOWED END TO END: %d (%s)" % (r["followed"], r["outcomes"])] + [
            "  %-44s p50 %10.3f ms  p95 %10.3f ms  max %10.3f ms" % (s_["step"], s_["p50"], s_["p95"], s_["max"]) for s_ in r["steps_ms"]]
    if o["storage"]:
        L += ["", "DRIVES"] + ["  %s" % json.dumps(s_.get("drives") or s_, ensure_ascii=False)[:400] for s_ in o["storage"]]
    L += ["", "FAILURES (grouped)"] + ["  %4d× %s %s %s %s — %s%s" % (f["count"], f["where"], f["kind"], f["about"], f["code"] or "", (f["example"] or "")[:120],
                                                                   " (retried %d)" % f["retried"] if f["retried"] else "") for f in o["failures"][:30]]
    if o["teams"]:
        L += ["", "HARVEST TEAMS"] + ["  %-40s %5d× median %s s p95 %s s failed %d" % (t["name"], t["count"], t["median_s"], t["p95_s"], t["failed"]) for t in o["teams"][:20]]
    L += ["", "WHAT TO CHANGE"] + ["  * " + a for a in o["advice"]]
    return "\n".join(L)


# ------------------------------------------------------------------------------------------------ export
def export(trace_folder, out_zip=None, days=None):
    """every log file (or those of the last `days` days) in one zip to send for analysis. Returns (path, files, bytes)."""
    files = sorted(f for f in os.listdir(trace_folder) if f.endswith((".jsonl", ".jsonl.gz"))) if os.path.isdir(trace_folder) else []
    if days:
        cut = time.time() - days * 86400
        files = [f for f in files if os.path.getmtime(os.path.join(trace_folder, f)) >= cut]
    out_zip = out_zip or os.path.join(os.path.dirname(trace_folder), "trace-export-%s.zip" % time.strftime("%Y%m%d-%H%M%S"))
    raw = 0
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            p = os.path.join(trace_folder, f)
            raw += os.path.getsize(p)
            z.write(p, f)
    return out_zip, len(files), raw


def read_lines(paths, since_ns=0, max_seconds=None):
    """every log line from files, folders or exported zips — read line by line (never a whole file at once); lines older
    than since_ns are skipped; reading stops after max_seconds (a partial answer beats none)"""
    t_end = time.time() + max_seconds if max_seconds else None

    def parse(name, it):
        for raw in it:
            if t_end and time.time() > t_end:
                return
            line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            if not line.strip():
                continue
            if since_ns:
                k = line.rfind('"t":')
                if k != -1:
                    try:
                        if int(line[k + 4:].split(",")[0].split("}")[0]) < since_ns:
                            continue
                    except ValueError:
                        pass
            try:
                yield json.loads(line)
            except ValueError:
                yield {"ev": "fail", "where": "trace log", "kind": "unreadable line", "msg": line[:200], "proc": name}

    def from_bytes(name, data):
        if name.endswith(".gz"):
            data = gzip.decompress(data)
        yield from parse(name, data.splitlines())
    for p in paths:
        if os.path.isdir(p):
            yield from read_lines([os.path.join(p, f) for f in sorted(os.listdir(p)) if f.endswith((".jsonl", ".jsonl.gz", ".zip"))],
                                  since_ns, max_seconds)
        elif p.endswith(".zip"):
            with zipfile.ZipFile(p) as z:
                for n in sorted(z.namelist()):
                    if n.endswith((".jsonl", ".jsonl.gz")):
                        yield from from_bytes(n, z.read(n))
        elif p.endswith(".gz") and os.path.isfile(p):
            with gzip.open(p, "rb") as f:
                yield from parse(p, f)
        elif os.path.isfile(p):
            with open(p, "rb") as f:
                yield from parse(p, f)


def self_test():
    import tempfile
    res = []
    ok = lambda n, c, d="": res.append((n, bool(c), d))
    with tempfile.TemporaryDirectory() as tmp:
        t = Tracer().configure(os.path.join(tmp, "trace"), "bulk-test", sample=4)
        t.add("rule", 1500, 3); t.add("rule", 500, 1, 10)
        t.flush_stages(dataset="x")
        t.io("example.org", 206, 0.5, 1 << 20, ttfb=0.1)
        try:
            raise ValueError("bad row")
        except ValueError as e:
            t.fail("rule", e, dataset="x", row=7)
        t.record({"fp": "00", "t": {"row": 1}})
        t.event("run", phase="end")
        t.close()
        lines = list(read_lines([os.path.join(tmp, "trace")]))
        evs = [l["ev"] for l in lines]
        ok("every kind of line is written and read back", set(evs) >= {"stages", "io", "fail", "record", "run"}, evs)
        st = next(l for l in lines if l["ev"] == "stages")["stages"]["rule"]
        ok("stage totals add up (count, time, bytes, slowest)", st["n"] == 4 and st["ms"] == 0.002 and st["bytes"] == 10 and st["max_ms"] == 0.002, st)
        f = next(l for l in lines if l["ev"] == "fail")
        ok("a failure keeps where, what and the traceback", f["kind"] == "ValueError" and f["row"] == 7 and any("bad row" in x for x in f["tb"]), f)
        ok("sampling is fixed by the fingerprint (1 in N)", [t.sampled(bytes([0, 0, 0, i])) for i in range(8)] == [True, False, False, False] * 2)
        z, n, raw = export(os.path.join(tmp, "trace"))
        ok("logs export to one zip and read back from it", n == 1 and len(list(read_lines([z]))) == len(lines), (n, raw))
        sb = compare_storage({"here": tmp, "here again": tmp}, mb=8, rows=20_000)
        ok("storage benchmark: write, read, fsync and the agents' SQLite pattern measured per drive",
           sb["fastest_for_facts"] and all(k in sb["drives"][0] for k in ("seq_write_mb_s", "fsync_ms_median", "sqlite_rows_s"))
           and not os.listdir(tmp + "/trace") == [], sb)
        fl = Tracer().configure(os.path.join(tmp, "flood"), "flood")
        for i in range(500):
            fl.fail("rule", ValueError("same bad row %d" % i), dataset="x")
        fl.close()
        lines_fl = list(read_lines([os.path.join(tmp, "flood")]))
        ok("a failure repeated 500 times in a minute is written 20 times (the rest counted later), not 500",
           sum(1 for l in lines_fl if l["ev"] == "fail") == 20, len(lines_fl))
        off = Tracer().configure(os.path.join(tmp, "off"), "x", on=False)
        off.event("run"); off.close()
        ok("switched off: nothing is written", not os.path.exists(os.path.join(tmp, "off")))
    return res


if __name__ == "__main__":
    if sys.argv[1:2] == ["self-test"]:
        r = self_test()
        for n, g, d in r:
            print("  [%s] %s%s" % ("OK" if g else "FAIL", n, "" if g else " — %s" % (d,)))
        print("  %d of %d checks passed" % (sum(1 for x in r if x[1]), len(r)))
        sys.exit(0 if all(x[1] for x in r) else 1)
    if sys.argv[1:2] == ["export"] and len(sys.argv) > 2:
        print(export(sys.argv[2]))
    if sys.argv[1:2] == ["report"] and len(sys.argv) > 2:      # python qbtrace.py report FOLDER-or-ZIP [...]
        print(text_report(analyze(read_lines(sys.argv[2:]))))
    if sys.argv[1:2] == ["drives"] and len(sys.argv) > 3:      # python qbtrace.py drives C:\Users\me D:\QB
        print(json.dumps(compare_storage({p: p for p in sys.argv[2:]}), indent=1))
