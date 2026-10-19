"""qbcore — the small, shared core of the QueryBook dedicated applications.

Each application folder carries its own identical copy of this file, so the three
applications never share code at run time and one can never break another.
`python tools/sync_core.py` copies the master in `_core/` into each application, and
each application's self-test checks that its copy matches the master when present.

Design rules (they exist because the full-featured prototype lost data):
  * One SQLite database per application, in a data folder OUTSIDE the program folder.
    Upgrading or replacing the program never touches the data.
  * Every write is one transaction under one lock; WAL journal, synchronous=FULL.
    A crash leaves the database either before or after a write, never half-written.
  * The database is checked at start-up. A damaged database is never written to.
  * A verified backup is taken at start-up (when the data changed) and before every
    import; the last BACKUPS_KEPT are kept. `python app.py restore` restores one.
  * Imports from the old QueryBook store are READ-ONLY. The old store is never opened
    for writing, never indexed, never modified.
  * Standard library only. No pip installs.
"""
import bz2, contextlib, datetime, gzip, hashlib, json, lzma, os, re, shutil, socket, sqlite3, struct
import platform, sys, threading, time, traceback, urllib.error, urllib.parse, urllib.request, uuid, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CORE_VERSION = "1.7.0"
BACKUPS_KEPT = 10


# ----------------------------------------------------------------------------- utilities
def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_cs():
    """UTC time to the hundredth of a second (activity log)."""
    d = datetime.datetime.now(datetime.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%02dZ" % (d.microsecond // 10000)


def norm(s):
    """Lower-case, single-spaced text used for matching and fingerprints."""
    return " ".join(str(s or "").strip().lower().split())


def fingerprint(*parts):
    """SHA-256 over normalized parts. Same content gives the same fingerprint everywhere."""
    return hashlib.sha256("|".join(norm(p) for p in parts).encode("utf-8")).hexdigest()


def app_dir(file):
    return os.path.dirname(os.path.abspath(file))


# ----------------------------------------------------------------------------- data folder
def data_folder(app_id, program_dir):
    """Where this application keeps its data. Order: environment variable
    QB_<APP>_DATA, then config.json in the program folder, then ~/QueryBook-Data/<app>."""
    env = os.environ.get("QB_%s_DATA" % app_id.upper())
    if env:
        return os.path.abspath(os.path.expanduser(env))
    cfg = os.path.join(program_dir, "config.json")
    try:
        with open(cfg, encoding="utf-8") as f:
            p = json.load(f).get("data_folder")
        if p:
            return os.path.abspath(os.path.expanduser(p))
    except (OSError, ValueError):
        pass
    return os.path.join(os.path.expanduser("~"), "QueryBook-Data", app_id)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def set_data_folder(program_dir, folder):
    cfg = os.path.join(program_dir, "config.json")
    tmp = cfg + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"data_folder": os.path.abspath(os.path.expanduser(folder))}, f, indent=2)
    os.replace(tmp, cfg)


# ----------------------------------------------------------------------------- database
class DatabaseDamaged(Exception):
    pass


class Store:
    """One SQLite database with serialized, transactional writes and automatic backups.

    schema: list of SQL scripts; script i upgrades the database from version i to i+1.
    """

    def __init__(self, folder, app_id, schema, log=None):
        self.folder = folder
        self.app_id = app_id
        self.path = os.path.join(folder, app_id + ".sqlite")
        self.backup_dir = os.path.join(folder, "backups")
        self.log = log or (lambda *a: None)
        self._lock = threading.RLock()
        self._local = threading.local()
        self.read_only = False
        self.damage = None
        self.cloud = None                 # CloudLink, when Google Cloud is configured (off-site copy of every backup)
        os.makedirs(self.backup_dir, exist_ok=True)
        self._check()
        self.schema_len = len(schema)
        if not self.read_only:
            self._migrate(schema)

    # -- connections
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def conn(self):
        db = getattr(self._local, "db", None)
        if db is None:
            db = self._connect()
            self._local.db = db
        return db

    def _check(self):
        if not os.path.exists(self.path):
            return
        try:
            db = sqlite3.connect(self.path, timeout=30)
            r = db.execute("PRAGMA quick_check").fetchone()[0]
            db.close()
        except sqlite3.DatabaseError as e:
            r = str(e)
        if r != "ok":
            self.read_only = True
            self.damage = r
            self.log("DATABASE CHECK FAILED: %s — the database will not be written to." % r)

    def _migrate(self, schema):
        with self.write() as db:
            db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
            db.execute("""CREATE TABLE IF NOT EXISTS qb_activity (id INTEGER PRIMARY KEY, at TEXT NOT NULL, task TEXT NOT NULL,
                          status TEXT NOT NULL, detail TEXT, ms INTEGER, items INTEGER)""")
            row = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            v = int(row[0]) if row else 0
            for i in range(v, len(schema)):
                for stmt in _split_sql(schema[i]):
                    db.execute(stmt)
                db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)", (str(i + 1),))
            if not row:
                db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('created', ?)", (now_iso(),))

    # -- reads and writes
    def query(self, sql, args=()):
        return [dict(r) for r in self.conn().execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        r = self.conn().execute(sql, args).fetchone()
        return dict(r) if r is not None else None

    def scalar(self, sql, args=(), default=None):
        r = self.conn().execute(sql, args).fetchone()
        return r[0] if r is not None and r[0] is not None else default

    @contextlib.contextmanager
    def write(self):
        """One transaction, one writer. Commits on success, rolls back on any error."""
        if self.read_only:
            raise DatabaseDamaged("The database failed its check (%s). Nothing was written. "
                                  "Run: python app.py restore" % self.damage)
        with self._lock:
            db = self.conn()
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def meta_get(self, key, default=None):
        return self.scalar("SELECT value FROM meta WHERE key=?", (key,), default)

    def meta_set(self, key, value, db=None):
        sql, args = "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, str(value))
        if db is not None:
            db.execute(sql, args)
        else:
            with self.write() as d:
                d.execute(sql, args)

    # -- activity log: every major task, with outcome and duration
    def activity(self, task, status="ok", detail="", ms=None, items=None):
        self.log("ACTIVITY", task, status, detail, "%sms" % ms if ms is not None else "")
        if self.read_only:
            return
        try:
            with self.write() as db:
                db.execute("INSERT INTO qb_activity(at, task, status, detail, ms, items) VALUES(?,?,?,?,?,?)",
                           (now_cs(), str(task)[:200], status, str(detail or "")[:1000], ms, items))
                n = db.execute("SELECT max(id) FROM qb_activity").fetchone()[0] or 0
                if n % 500 == 0:
                    db.execute("DELETE FROM qb_activity WHERE id <= ?", (n - 20000,))     # keep the newest 20,000
        except Exception as e:
            self.log("activity log write failed:", repr(e))

    def activities(self, limit=200, task=None):
        if task:
            return self.query("SELECT * FROM qb_activity WHERE task LIKE ? ORDER BY id DESC LIMIT ?", ("%" + task + "%", limit))
        return self.query("SELECT * FROM qb_activity ORDER BY id DESC LIMIT ?", (limit,))

    # -- backups
    def data_version(self):
        """Changes whenever committed data changes (used to skip redundant backups)."""
        try:
            st = os.stat(self.path)
            wal = self.path + "-wal"
            wst = os.stat(wal).st_size if os.path.exists(wal) else 0
            return "%d-%d-%d" % (st.st_size, int(st.st_mtime), wst)
        except OSError:
            return ""

    # -- redundancy: a verified second copy of every backup in another folder (e.g. an external drive)
    def mirror_dir(self):
        env = os.environ.get("QB_%s_MIRROR" % self.app_id.upper())
        if env:
            return os.path.abspath(os.path.expanduser(env))
        try:
            with open(os.path.join(self.folder, "mirror.json"), encoding="utf-8") as f:
                d = json.load(f).get("folder")
            return os.path.abspath(os.path.expanduser(d)) if d else None
        except (OSError, ValueError):
            return None

    def set_mirror(self, folder):
        p = os.path.join(self.folder, "mirror.json")
        if not folder or str(folder).lower() in ("off", "none", ""):
            if os.path.exists(p):
                os.remove(p)
            self.activity("Backup mirror switched off", "ok")
            return None
        d = os.path.abspath(os.path.expanduser(folder))
        if os.path.normcase(d).startswith(os.path.normcase(os.path.abspath(self.folder))):
            raise UserError("The mirror must be in another folder (better: another drive), not inside the data folder.")
        os.makedirs(os.path.join(d, self.app_id), exist_ok=True)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"folder": d}, f)
        os.replace(p + ".tmp", p)
        self.activity("Backup mirror set", "ok", redact(d))
        b = self.backups()
        if b:
            self._mirror(b[0]["path"])
        return d

    def mirror_backups(self):
        d = self.mirror_dir()
        if not d or not os.path.isdir(os.path.join(d, self.app_id)):
            return []
        m = os.path.join(d, self.app_id)
        return [{"name": n, "path": os.path.join(m, n), "bytes": os.path.getsize(os.path.join(m, n)), "mirror": True}
                for n in sorted(os.listdir(m), reverse=True) if n.endswith(".sqlite")]

    def _mirror(self, src):
        """Copy one backup to the mirror and prove the copy: same SHA-256 and a passing database check."""
        d = self.mirror_dir()
        if not d:
            return None
        t0 = time.time()
        try:
            m = os.path.join(d, self.app_id)
            os.makedirs(m, exist_ok=True)
            dest = os.path.join(m, os.path.basename(src))
            shutil.copy2(src, dest + ".part")
            os.replace(dest + ".part", dest)
            same = _sha256(src) == _sha256(dest)
            c = sqlite3.connect(dest)
            ok = same and c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            c.close()
            if not ok:
                os.remove(dest)
                raise RuntimeError("mirror copy did not match the backup")
            for old in self.mirror_backups()[BACKUPS_KEPT:]:
                os.remove(old["path"])
            self.activity("Backup mirrored", "ok", os.path.basename(dest), int((time.time() - t0) * 1000))
            return dest
        except Exception as e:
            self.log("ERROR", "backup mirror failed:", repr(e))
            self.activity("Backup mirrored", "failed", redact(e), int((time.time() - t0) * 1000))
            return None

    def backups(self):
        out = []
        for name in sorted(os.listdir(self.backup_dir), reverse=True):
            if name.endswith(".sqlite"):
                p = os.path.join(self.backup_dir, name)
                out.append({"name": name, "path": p, "bytes": os.path.getsize(p)})
        return out

    def backup(self, reason="manual", force=False):
        """Copy the live database with SQLite's online backup, verify the copy, keep the newest."""
        if self.read_only or not os.path.exists(self.path):
            return None
        ver = self.data_version()
        last = self.backups()
        marker = os.path.join(self.backup_dir, "last-backup.json")
        try:
            with open(marker, encoding="utf-8") as f:
                prev = json.load(f)
        except (OSError, ValueError):
            prev = {}
        if not force and last and prev.get("version") == ver:
            return last[0]["path"]
        t0 = time.time()
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        dest = os.path.join(self.backup_dir, "%s-%s-%s.sqlite" % (self.app_id, stamp, re.sub(r"\W+", "", reason)[:20]))
        with self._lock:
            src = self.conn()
            out = sqlite3.connect(dest)
            src.backup(out)
            ok = out.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            out.close()
        if not ok:
            os.remove(dest)
            raise RuntimeError("backup copy failed its check; previous backups kept")
        tmp = marker + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": self.data_version(), "time": now_iso(), "file": os.path.basename(dest)}, f)
        os.replace(tmp, marker)
        for old in self.backups()[BACKUPS_KEPT:]:
            os.remove(old["path"])
        self.log("backup written: %s" % os.path.basename(dest))
        self.activity("Backup (%s)" % reason, "ok", os.path.basename(dest), int((time.time() - t0) * 1000))
        self._mirror(dest)
        if self.cloud:
            self.cloud.enqueue(dest)
        return dest

    def restore(self, backup_path):
        """Replace the database with a backup. The current file is kept as *.replaced-<time>."""
        db = sqlite3.connect(backup_path)
        ok = db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        db.close()
        if not ok:
            raise RuntimeError("that backup is damaged; choose another")
        mine = getattr(self._local, "db", None)
        if mine is not None:                      # Windows cannot rename a file this process still has open
            mine.close()
            self._local.db = None
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        for ext in ("", "-wal", "-shm"):
            p = self.path + ext
            if os.path.exists(p):
                os.replace(p, self.path + ".replaced-" + stamp + ext.replace("-", "."))
        shutil.copyfile(backup_path, self.path)
        return self.path

    def status(self):
        return {"database": self.path, "folder": self.folder, "read_only": self.read_only,
                "damage": self.damage, "bytes": os.path.getsize(self.path) if os.path.exists(self.path) else 0,
                "schema_version": self.meta_get("schema_version"), "created": self.meta_get("created"),
                "last_backup": (self.backups() or [{}])[0].get("name"), "backups": len(self.backups())}


def _split_sql(script):
    return [s.strip() for s in script.split(";") if s.strip()]


# ----------------------------------------------------------------------------- logging
def make_logger(folder, app_id):
    path = os.path.join(folder, app_id + ".log")
    lock = threading.Lock()

    def log(*parts):
        line = "%s  %s\n" % (now_iso(), " ".join(str(p) for p in parts))
        with lock:
            try:
                if os.path.exists(path) and os.path.getsize(path) > 2_000_000:
                    os.replace(path, path + ".1")
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line)
            except OSError:
                pass
        if parts and str(parts[0]) in ERROR_MARKS:
            for hook in list(log.hooks):
                try:
                    hook(line)
                except Exception:
                    pass
    log.path = path
    log.hooks = []
    return log


ERROR_MARKS = ("ERROR", "JOB FAILED")


# ----------------------------------------------------------------------------- old QueryBook store (read-only)
_PK = struct.Struct("<32sBfHHHH")
_OPENERS = {".gz": gzip.open, ".bz2": bz2.open, ".xz": lzma.open}


def find_old_store(path):
    """Return the folder that holds the old store's blocks/ (accepts the store folder or its parent)."""
    path = os.path.abspath(os.path.expanduser(path or ""))
    for cand in (path, os.path.join(path, "store")):
        if os.path.isdir(os.path.join(cand, "blocks")) or os.path.exists(os.path.join(cand, "manifest.json")) \
                or any(n.startswith("language_model") for n in _listdir(cand)):
            return cand
    return None


def _listdir(p):
    try:
        return os.listdir(p)
    except OSError:
        return []


def old_store_hints():
    """Old QueryBook stores this computer remembers (read-only): folders named in ~/.querybook/config.json,
    and ~/.querybook/store. Returns existing store folders, most likely first."""
    home = os.path.join(os.path.expanduser("~"), ".querybook")
    cands = []
    try:
        with open(os.path.join(home, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        vals = list(cfg.values()) if isinstance(cfg, dict) else []
        for v in vals:
            if isinstance(v, dict):
                vals.extend(v.values())
            elif isinstance(v, str) and len(v) < 500:
                cands.append(v)
    except (OSError, ValueError):
        pass
    cands.append(os.path.join(home, "store"))
    out = []
    for c in cands:
        s = find_old_store(c) if c else None
        if s and s not in out:
            out.append(s)
    return out


def old_store_summary(store):
    out = {"folder": store, "blocks": 0, "manifest": {}, "language_models": []}
    try:
        with open(os.path.join(store, "manifest.json"), encoding="utf-8") as f:
            out["manifest"] = json.load(f)
    except (OSError, ValueError):
        pass
    out["blocks"] = len([n for n in _listdir(os.path.join(store, "blocks")) if n.startswith("block_")])
    out["language_models"] = sorted(n for n in _listdir(store) if n.startswith("language_model") and n.endswith(".json"))
    return out


def iter_old_records(store, domains=None, should_stop=None):
    """Yield every readable record from the old store's blocks, read-only.

    Handles JSON-lines and packed blocks, gzip/bz2/xz. A damaged line or a truncated
    block is skipped; everything readable before it is still yielded.
    Each record is normalized to {subject, predicate, object, polarity, domain, trust, source, raw}.
    """
    bdir = os.path.join(store, "blocks")
    want = set(domains) if domains else None
    for name in sorted(_listdir(bdir)):
        if not name.startswith("block_"):
            continue
        if should_stop and should_stop():
            return
        p = os.path.join(bdir, name)
        ext = os.path.splitext(name)[1]
        opener = _OPENERS.get(ext, open)
        packed = ".pack." in name
        try:
            if packed:
                with opener(p, "rb") as f:
                    while True:
                        head = f.read(_PK.size)
                        if len(head) < _PK.size:
                            break
                        fp, pol, trust, sl, pl, ol, dl = _PK.unpack(head)
                        s, pr, o, d = f.read(sl), f.read(pl), f.read(ol), f.read(dl)
                        rec = {"subject": s.decode("utf-8", "replace"), "predicate": pr.decode("utf-8", "replace"),
                               "object": o.decode("utf-8", "replace"), "polarity": "+" if pol else "-",
                               "domain": d.decode("utf-8", "replace"), "trust": round(trust, 6), "source": None, "raw": None}
                        if want is None or rec["domain"] in want:
                            yield rec
            else:
                with opener(p, "rt", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            r = json.loads(line)
                        except ValueError:
                            continue
                        rec = normalize_old_record(r)
                        if rec and (want is None or rec["domain"] in want):
                            yield rec
        except (OSError, EOFError, lzma.LZMAError, ValueError, struct.error):
            continue


def normalize_old_record(r):
    if not isinstance(r, dict):
        return None
    n = r.get("nucleus") or {}
    if not n.get("subject"):
        return None
    src = (r.get("sources") or [None])[0]
    trust = (r.get("certification") or {}).get("trust_score")
    if trust is None:
        trust = (r.get("confidence") or {}).get("trust_score", 0.5)
    return {"subject": str(n.get("subject")), "predicate": str(n.get("predicate", "")), "object": str(n.get("object", "")),
            "polarity": r.get("polarity", "+"), "domain": str(r.get("domain", "general")), "trust": float(trust or 0),
            "source": src if isinstance(src, dict) else None, "raw": r}


def iter_old_language_models(store):
    """Yield (file name, model dict) for each language_model*.json, read-only; damaged files skipped."""
    for name in sorted(_listdir(store)):
        if name.startswith("language_model") and (name.endswith(".json") or name.endswith(".json.bak")):
            try:
                with open(os.path.join(store, name), encoding="utf-8") as f:
                    m = json.load(f)
                if isinstance(m, dict):
                    yield name, m
            except (OSError, ValueError):
                continue


# ----------------------------------------------------------------------------- web server
class Api:
    """Route table: api.get("/api/x")(fn) / api.post("/api/x")(fn). fn(params) -> JSON-able."""

    def __init__(self):
        self.routes = {}

    def get(self, path):
        def deco(fn):
            self.routes[("GET", path)] = fn
            return fn
        return deco

    def post(self, path):
        def deco(fn):
            self.routes[("POST", path)] = fn
            return fn
        return deco


class UserError(Exception):
    """An error whose message is shown to the user as-is."""


_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8",
          ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".wav": "audio/wav", ".json": "application/json",
          ".mjs": "application/javascript; charset=utf-8", ".wasm": "application/wasm", ".task": "application/octet-stream",
          ".webm": "video/webm", ".mp4": "video/mp4"}


ACTION_NAMES = {}          # path -> readable task name for the activity log (apps may add their own)


def _summary(out):
    """A short, content-free description of an action's result for the activity log."""
    if not isinstance(out, dict):
        return ""
    keep = []
    for k, v in out.items():
        if isinstance(v, bool) or (isinstance(v, (int, float)) and not isinstance(v, bool)):
            keep.append("%s=%s" % (k, v))
        elif k in ("state", "status", "name", "kind", "backup", "result") and isinstance(v, str):
            keep.append("%s=%s" % (k, v[:60]))
    return ", ".join(keep[:8])


def make_handler(api, ui_dir, log, app_name, store=None):
    class Handler(BaseHTTPRequestHandler):
        server_version = app_name.replace(" ", "")
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        def _host_ok(self):
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost", "[::1]")

        def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            extra = dict(extra or {})
            if code == 200 and ctype.split(";")[0].split("/")[0] in ("audio", "video"):
                extra["Accept-Ranges"] = "bytes"           # lets players seek (and lip-sync scrub) inside recordings
                rng = re.match(r"bytes=(\d*)-(\d*)$", (self.headers.get("Range") or "").strip())
                if rng and (rng.group(1) or rng.group(2)):
                    n = len(body)
                    if rng.group(1):
                        a, b = int(rng.group(1)), min(n - 1, int(rng.group(2) or n - 1))
                    else:
                        a, b = max(0, n - int(rng.group(2))), n - 1
                    if a >= n or a > b:
                        extra["Content-Range"] = "bytes */%d" % n
                        code, body = 416, b""
                    else:
                        extra["Content-Range"] = "bytes %d-%d/%d" % (a, b, n)
                        code, body = 206, body[a:b + 1]
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if "Cache-Control" not in (extra or {}):
                self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            try:
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass                                   # the page was closed or reloaded before the answer arrived

        def _dispatch(self, method):
            if not self._host_ok():
                return self._send(403, {"error": "This application only answers on this computer."})
            url = urllib.parse.urlsplit(self.path)
            params = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query).items()}
            if method == "POST":
                origin = self.headers.get("Origin")
                if origin and urllib.parse.urlsplit(origin).hostname not in ("127.0.0.1", "localhost"):
                    return self._send(403, {"error": "Requests from other sites are refused."})
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                if raw:
                    if "application/json" not in (self.headers.get("Content-Type") or ""):
                        return self._send(415, {"error": "JSON body required."})
                    try:
                        body = json.loads(raw.decode("utf-8"))
                    except ValueError:
                        return self._send(400, {"error": "Body is not valid JSON."})
                    if isinstance(body, dict):
                        params.update(body)
            fn = api.routes.get((method, url.path))
            if fn is None:
                if method == "GET":
                    return self._static(url.path)
                return self._send(404, {"error": "No such action."})
            t0 = time.time()
            logged = method == "POST" or url.path.endswith((".csv", ".txt"))
            task = ACTION_NAMES.get(url.path, url.path)

            def note(status, detail=""):
                if logged and store is not None:
                    store.activity(task, status, detail, int((time.time() - t0) * 1000))
            try:
                out = fn(params)
                if isinstance(out, tuple) and len(out) == 2 and isinstance(out[0], (bytes, bytearray)):
                    note("ok", "%d bytes" % len(out[0]))
                    return self._send(200, bytes(out[0]), out[1])
                note("ok", _summary(out))
                return self._send(200, out if out is not None else {"ok": True}, extra={"X-QB-Ms": str(int((time.time() - t0) * 1000))})
            except (UserError, DatabaseDamaged) as e:
                note("refused", str(e))
                return self._send(400, {"error": str(e)})
            except ValueError as e:
                if str(e).startswith(("invalid literal for int()", "could not convert string to float")):
                    note("refused", "a number was expected")
                    return self._send(400, {"error": "A number was expected."})
                note("error", repr(e))
                log("ERROR", method, url.path, repr(e), traceback.format_exc().replace("\n", " | "))
                return self._send(500, {"error": "Something went wrong: %s" % e})
            except Exception as e:
                note("error", repr(e))
                log("ERROR", method, url.path, repr(e), traceback.format_exc().replace("\n", " | "))
                return self._send(500, {"error": "Something went wrong: %s" % e})

        def _static(self, path):
            if path in ("", "/"):
                path = "/index.html"
            rel = os.path.normpath(urllib.parse.unquote(path).lstrip("/"))
            if rel.startswith("..") or os.path.isabs(rel):
                return self._send(404, {"error": "Not found."})
            p = os.path.join(ui_dir, rel)
            if not os.path.isfile(p):
                return self._send(404, {"error": "Not found."})
            with open(p, "rb") as f:
                data = f.read()
            # bundled libraries and models do not change between versions of a file name: let the browser keep them
            cache = {"Cache-Control": "max-age=604800"} if rel.replace("\\", "/").startswith("vendor/") else None
            self._send(200, data, _TYPES.get(os.path.splitext(p)[1], "application/octet-stream"), extra=cache)

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

    return Handler


def free_port(preferred):
    for port in [preferred] + list(range(preferred + 10, preferred + 60)):
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no free port near %d" % preferred)


def serve(app_name, api, ui_dir, port, log, open_browser=True, on_start=None, store=None):
    port = free_port(port)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(api, ui_dir, log, app_name, store))
    httpd.daemon_threads = True
    url = "http://127.0.0.1:%d/" % port
    print("\n  %s is running at %s" % (app_name, url))
    print("  Leave this window open while you use it. Close it (or press Ctrl+C) to stop.\n")
    log("started", url)
    if on_start:
        on_start(url)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        log("stopped")


# ----------------------------------------------------------------------------- background jobs
class Jobs:
    """One background job at a time (imports, bulk work), with progress the UI can poll."""

    def __init__(self, log, store=None):
        self.log = log
        self.store = store
        self.lock = threading.Lock()
        self.current = None
        self.last = None
        self._stop = threading.Event()

    def start(self, name, fn):
        with self.lock:
            if self.current and self.current["state"] == "running":
                raise UserError("'%s' is still running. Wait for it to finish or stop it." % self.current["name"])
            self._stop.clear()
            job = {"name": name, "state": "running", "done": 0, "total": None, "message": "", "started": now_cs(), "result": None,
                   "_t0": time.time(), "_seen": 0, "steps": 0}
            self.current = job
        if self.store:
            self.store.activity(name, "started")

        def progress(done, total=None, message="", **extra):
            # extra: optional whole-job fields such as overall (0..1), stage, stage_no, stages
            job["done"], job["total"], job["message"] = done, total, message
            job.update(extra)
            job["steps"] += 1

        def run():
            try:
                job["result"] = fn(progress, self._stop.is_set)
                job["state"] = "stopped" if self._stop.is_set() else "finished"
            except Exception as e:
                job["state"] = "failed"
                job["message"] = str(e)
                self.log("JOB FAILED", name, repr(e), traceback.format_exc().replace("\n", " | "))
            job["ended"] = now_cs()
            job["elapsed"] = round(time.time() - job["_t0"], 2)
            self.last = job
            if self.store:
                self.store.activity(name, job["state"], (job["message"] if job["state"] == "failed" else _summary(job["result"])),
                                    int(job["elapsed"] * 1000), job["steps"])
        threading.Thread(target=run, daemon=True).start()
        return job

    def stop(self):
        self._stop.set()

    def status(self):
        j = self.current
        if not j:
            return {"state": "idle"}
        out = {k: v for k, v in j.items() if not k.startswith("_")}
        el = (time.time() - j["_t0"]) if j["state"] == "running" else j.get("elapsed", 0)
        out["elapsed"] = round(el, 2)
        out["updates_per_s"] = round(j["steps"] / el, 2) if el > 0 else None
        if j["state"] == "running" and j.get("total") and j["done"]:
            # speed and time left from the current stage's own counter
            rate = j["done"] / max(el, 0.001)
            out["rate"] = round(rate, 1)
            out["eta_s"] = round(max(0, (j["total"] - j["done"]) / rate), 1) if rate > 0 else None
        if j["state"] == "running" and j.get("overall"):
            # time left for the whole job, from its overall fraction
            out["overall_eta_s"] = round(el * (1 - j["overall"]) / j["overall"], 1)
        return out


# ----------------------------------------------------------------------------- internal diagnostics
REQUIRED_FILES = ("app.py", "qbcore.py", "qbcommons.py", "qbharvest.py", "gcloud.py", os.path.join("ui", "index.html"), os.path.join("ui", "app.js"),
                  os.path.join("ui", "qb.js"), os.path.join("ui", "qb.css"))


def redact(text):
    """Remove the home folder, user names and tokens from text that may leave this computer."""
    t = str(text or "")
    home = os.path.expanduser("~")
    for h in {home, home.replace("\\", "/"), home.replace("/", "\\")}:
        if h and len(h) > 2:
            t = t.replace(h, "~")
    t = re.sub(r"(?i)([a-z]:\\users\\|/home/|/users/)[^\\/\s'\"]+", r"\1<user>", t)
    t = re.sub(r"(?i)(gh[pousr]_|github_pat_)[A-Za-z0-9_]{10,}", "<token>", t)
    return t


def _check(cid, name, status, detail="", value=None):
    return {"id": cid, "name": name, "status": status, "detail": detail, "value": value}


class Diagnostics:
    """Checks the application's own health. Never reads or reports the user's content."""

    def __init__(self, app_id, app_name, version, program_dir, store, log, jobs=None, extra=None):
        self.app_id, self.app_name, self.version = app_id, app_name, version
        self.program_dir, self.store, self.log, self.jobs = program_dir, store, log, jobs
        self.extra = extra
        self.started = time.time()
        self.last = None
        self._lock = threading.Lock()

    def errors_since(self, hours=24, limit=10):
        """Error lines from the application's log in the last `hours` (newest last), first line only, redacted."""
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
        out = []
        p = getattr(self.log, "path", None)
        lines = []
        if p and os.path.exists(p):
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()[-5000:]
            except OSError:
                lines = []
        for line in lines:
            parts = line.split("  ", 1)
            if len(parts) < 2 or not parts[1].startswith(ERROR_MARKS + ("DATABASE CHECK FAILED", "startup backup failed")):
                continue
            try:
                when = datetime.datetime.strptime(parts[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
            except ValueError:
                continue
            if when >= cutoff:
                msg = parts[1].split(" | ")[0].split(" Traceback (most recent call last)")[0].strip()   # no traceback
                out.append({"time": parts[0], "message": redact(msg)[:300]})
        return out[-limit:], len(out)

    def run(self):
        with self._lock:
            checks = []
            v = sys.version_info
            checks.append(_check("python", "Python version", "ok" if v >= (3, 8) else "fail", "%d.%d.%d" % v[:3]))
            missing = [f for f in REQUIRED_FILES if not os.path.isfile(os.path.join(self.program_dir, f))]
            checks.append(_check("files", "Program files present", "fail" if missing else "ok",
                                 ", ".join(missing) if missing else "%d files" % len(REQUIRED_FILES)))
            folder = self.store.folder
            try:
                probe = os.path.join(folder, ".write-test-%d" % os.getpid())
                with open(probe, "w") as f:
                    f.write("ok")
                os.remove(probe)
                checks.append(_check("writable", "Data folder can be written", "ok"))
            except OSError as e:
                checks.append(_check("writable", "Data folder can be written", "fail", redact(e)))
            try:
                free = shutil.disk_usage(folder).free
                st = "fail" if free < 200 * 2**20 else "warn" if free < 2**30 else "ok"
                checks.append(_check("disk", "Free disk space", st, "%.1f GB free" % (free / 2**30), round(free / 2**30, 2)))
            except OSError as e:
                checks.append(_check("disk", "Free disk space", "warn", redact(e)))
            if self.store.read_only:
                checks.append(_check("database", "Database check", "fail",
                                     "damaged at start-up (%s): writes are refused; restore a backup" % self.store.damage))
            else:
                try:
                    db = sqlite3.connect(self.store.path, timeout=30)
                    r = db.execute("PRAGMA quick_check").fetchone()[0]
                    db.close()
                    checks.append(_check("database", "Database check", "ok" if r == "ok" else "fail", "quick_check: %s" % r))
                except sqlite3.DatabaseError as e:
                    checks.append(_check("database", "Database check", "fail", redact(e)))
            try:
                sv = int(self.store.meta_get("schema_version") or 0)
                want = getattr(self.store, "schema_len", None)
                ok = want is None or sv == want
                checks.append(_check("schema", "Database layout version", "ok" if ok else "fail",
                                     "version %d%s" % (sv, "" if ok else " (expected %d)" % want)))
            except Exception as e:
                checks.append(_check("schema", "Database layout version", "fail", redact(e)))
            size = os.path.getsize(self.store.path) if os.path.exists(self.store.path) else 0
            wal = self.store.path + "-wal"
            walsize = os.path.getsize(wal) if os.path.exists(wal) else 0
            checks.append(_check("size", "Database size", "warn" if walsize > 200 * 2**20 else "ok",
                                 "%.1f MB (journal %.1f MB)" % (size / 2**20, walsize / 2**20), round(size / 2**20, 2)))
            b = self.store.backups()
            if not b:
                checks.append(_check("backup", "Backups", "warn", "no backup yet"))
            else:
                age_h = (time.time() - os.path.getmtime(b[0]["path"])) / 3600
                try:
                    bdb = sqlite3.connect(b[0]["path"])
                    bok = bdb.execute("PRAGMA quick_check").fetchone()[0] == "ok"
                    bdb.close()
                except sqlite3.DatabaseError:
                    bok = False
                st = "fail" if not bok else "warn" if age_h > 24 * 14 else "ok"
                checks.append(_check("backup", "Backups", st, "%d kept; newest %s old%s"
                                     % (len(b), _age(age_h), "" if bok else "; NEWEST BACKUP FAILED ITS CHECK"), len(b)))
            md = self.store.mirror_dir()
            if not md:
                checks.append(_check("mirror", "Backup mirror (second copy)", "ok", "not set — recommended: a folder on another drive (Diagnostics page, or python app.py set-mirror E:\\QB-Mirror)"))
            else:
                mb = self.store.mirror_backups()
                if not mb:
                    checks.append(_check("mirror", "Backup mirror (second copy)", "fail" if b else "warn", "no copy in the mirror yet"))
                else:
                    same = bool(b) and mb[0]["name"] == b[0]["name"] and _sha256(mb[0]["path"]) == _sha256(b[0]["path"])
                    checks.append(_check("mirror", "Backup mirror (second copy)", "ok" if same else "warn",
                                         "%d copies; newest %s" % (len(mb), "matches the newest backup" if same else "is older than the newest backup")))
            errs, n = self.errors_since(24)
            checks.append(_check("errors", "Errors in the last 24 hours", "ok" if n == 0 else "fail" if n >= 20 else "warn", "%d" % n, n))
            if self.jobs is not None:
                j = self.jobs.status()
                last = self.jobs.last or {}
                st = "warn" if last.get("state") == "failed" else "ok"
                detail = ("running: %s" % j.get("name")) if j.get("state") == "running" else \
                    ("last job failed: %s" % redact(last.get("message"))[:200] if st == "warn" else "idle")
                checks.append(_check("jobs", "Background work", st, detail))
            cl = getattr(self, "cloud", None)
            if cl:
                try:
                    checks += cl.checks()
                except Exception as e:
                    checks.append(_check("google", "Google Cloud", "warn", redact(repr(e))[:300]))
            if self.extra:
                try:
                    checks += self.extra()
                except Exception as e:
                    checks.append(_check("app", "Application checks", "fail", redact(repr(e))[:300]))
            order = {"fail": 2, "warn": 1, "ok": 0}
            overall = max((c["status"] for c in checks), key=lambda x: order[x]) if checks else "ok"
            bad = [c["name"] for c in checks if c["status"] != "ok"]
            self.store.activity("Diagnostics", overall, ("; ".join(bad) if bad else "all %d checks OK" % len(checks)))
            self.last = {"app": self.app_name, "app_id": self.app_id, "version": self.version, "core": CORE_VERSION, "time": now_iso(),
                         "overall": overall, "checks": checks, "errors": errs, "error_count": n,
                         "uptime": _age((time.time() - self.started) / 3600),
                         "environment": {"python": "%d.%d.%d" % v[:3], "os": platform.system() + " " + platform.release(),
                                         "machine": platform.machine(), "sqlite": sqlite3.sqlite_version}}
            if cl:
                cl.send_metrics(self.last)
            return self.last

    def text(self, report=None):
        r = report or self.last or self.run()
        lines = ["%s %s - diagnostics %s" % (r["app"], r["version"], r["time"]), "Overall: %s" % r["overall"].upper(), ""]
        for c in r["checks"]:
            lines.append("[%-4s] %s%s" % (c["status"].upper(), c["name"], (" - " + str(c["detail"])) if c["detail"] else ""))
        lines += ["", "Environment: Python %(python)s, %(os)s, %(machine)s, SQLite %(sqlite)s" % r["environment"], "Up for: " + r["uptime"]]
        if r["errors"]:
            lines += ["", "Recent errors:"] + ["  %s  %s" % (e["time"], e["message"]) for e in r["errors"]]
        return redact("\n".join(lines)) + "\n"


def _age(hours):
    if hours < 1:
        return "%d min" % max(0, round(hours * 60))
    if hours < 48:
        return "%.0f h" % hours
    return "%.0f days" % (hours / 24)


# ----------------------------------------------------------------------------- monitoring connection (GitHub)
class MonitorError(Exception):
    pass


FREQUENCIES = {"problems_daily": "problems at once, plus a daily check-in", "problems": "problems only",
               "hourly": "problems at once, plus an hourly check-in"}
DEFAULT_REPO = "ghoward333777-png/projectx"
FENCE = "`" * 3


class Monitor:
    """Sends health reports to the development repository on GitHub, as comments on one issue per
    application and computer. Reports contain health data only - never facts, words or answers.
    Needs a fine-grained GitHub token limited to that one repository, with Issues: Read and write."""

    def __init__(self, folder, app_id, app_name, version, log):
        self.path = os.path.join(folder, "monitor.json")
        self.app_id, self.app_name, self.version, self.log = app_id, app_name, version, log
        self.api_base = os.environ.get("QB_GITHUB_API", "https://api.github.com").rstrip("/")
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._thread = None
        self.cfg = self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                c = json.load(f)
            if not isinstance(c, dict):
                c = {}
        except (OSError, ValueError):
            c = {}
        c.setdefault("enabled", False)
        c.setdefault("repo", DEFAULT_REPO)
        c.setdefault("token", "")
        c.setdefault("label", "")
        c.setdefault("frequency", "problems_daily")
        c.setdefault("install_id", uuid.uuid4().hex[:8])
        c.setdefault("sent", {})
        c.setdefault("outbox", [])
        return c

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, indent=2)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)

    def public(self):
        c = self.cfg
        t = c.get("token") or ""
        return {"enabled": c["enabled"], "repo": c["repo"], "label": c["label"], "frequency": c["frequency"], "frequencies": FREQUENCIES,
                "token_set": bool(t), "token_hint": ("..." + t[-4:]) if len(t) > 8 else "", "install_id": c["install_id"],
                "issue_number": c.get("issue_number"), "issue_url": c.get("issue_url"), "last_sent": c.get("last_sent"),
                "last_status": c.get("last_status"), "last_heartbeat": c.get("last_heartbeat"), "waiting": len(c["outbox"]),
                "title": self.title()}

    def configure(self, enabled=None, repo=None, token=None, label=None, frequency=None):
        with self._lock:
            if repo is not None:
                repo = re.sub(r"^https?://github\.com/", "", repo.strip()).strip("/")
                if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", repo):
                    raise UserError("Repository must look like owner/name, for example %s" % DEFAULT_REPO)
                if repo != self.cfg["repo"]:
                    self.cfg.pop("issue_number", None)
                    self.cfg.pop("issue_url", None)
                self.cfg["repo"] = repo
            if token:
                token = token.strip()
                if not re.fullmatch(r"[A-Za-z0-9_]{20,255}", token):
                    raise UserError("That does not look like a GitHub token.")
                self.cfg["token"] = token
            if label is not None:
                new = re.sub(r"[^\w .-]", "", label)[:40].strip()
                if new != self.cfg["label"]:
                    self.cfg.pop("issue_number", None)
                    self.cfg.pop("issue_url", None)
                self.cfg["label"] = new
            if frequency is not None:
                if frequency not in FREQUENCIES:
                    raise UserError("Unknown frequency.")
                self.cfg["frequency"] = frequency
            if enabled is not None:
                if enabled and not self.cfg.get("token"):
                    raise UserError("Paste a GitHub token first.")
                self.cfg["enabled"] = bool(enabled)
            self._save()
        self._wake.set()
        return self.public()

    def disconnect(self):
        with self._lock:
            self.cfg.update(enabled=False, token="")
            self._save()
        return self.public()

    def title(self):
        return "[QueryBook monitor] %s · %s" % (self.app_name, self.cfg.get("label") or "install " + self.cfg["install_id"])

    def _req(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.api_base + path, data=data, method=method, headers={
            "Authorization": "Bearer " + self.cfg.get("token", ""), "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "QueryBook-%s/%s" % (self.app_id, self.version),
            "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
                return json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as e:
            msg = {401: "GitHub refused the token (it may be wrong or expired).",
                   403: "The token is not allowed to do this - it needs Issues: Read and write on %s." % self.cfg["repo"],
                   404: "Repository %s not found, or the token cannot see it." % self.cfg["repo"],
                   410: "Issues are turned off for %s." % self.cfg["repo"]}.get(e.code, "GitHub answered %d." % e.code)
            raise MonitorError(msg)
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise MonitorError("Could not reach GitHub: %s" % redact(getattr(e, "reason", e)))

    def _ensure_issue(self):
        repo = self.cfg["repo"]
        num = self.cfg.get("issue_number")
        if num:
            try:
                if self._req("GET", "/repos/%s/issues/%d" % (repo, num)).get("state") == "open":
                    return num
            except MonitorError:
                pass
        for page in (1, 2, 3):
            items = self._req("GET", "/repos/%s/issues?state=open&per_page=100&page=%d" % (repo, page))
            for it in items:
                if it.get("title") == self.title() and "pull_request" not in it:
                    self.cfg["issue_number"], self.cfg["issue_url"] = it["number"], it.get("html_url")
                    return it["number"]
            if len(items) < 100:
                break
        body = ("Health reports from **%s** on one computer (install `%s`).\n\n"
                "Each comment is one report: the result of the application's built-in checks, its version and its environment. "
                "Reports never contain the user's facts, words, answers or file names.\n\n"
                "Close this issue to start a fresh one with the next report.") % (self.app_name, self.cfg["install_id"])
        it = self._req("POST", "/repos/%s/issues" % repo, {"title": self.title(), "body": body})
        self.cfg["issue_number"], self.cfg["issue_url"] = it["number"], it.get("html_url")
        return it["number"]

    def compose(self, kind, report):
        icon = {"ok": "🟢", "warn": "🟡", "fail": "🔴"}[report["overall"]]
        brief = kind == "Check-in" and report["overall"] == "ok"
        rows = [c for c in report["checks"] if c["id"] in ("database", "backup", "errors", "disk")] if brief else report["checks"]
        lines = ["### %s %s - %s" % (icon, kind, report["overall"].upper()), "",
                 "**%s %s** (core %s) · install `%s`%s · %s · up %s" % (
                     report["app"], report["version"], report["core"], self.cfg["install_id"],
                     " (%s)" % self.cfg["label"] if self.cfg.get("label") else "", report["time"], report["uptime"]),
                 "", "| Check | Result | Detail |", "|---|---|---|"]
        for c in rows:
            lines.append("| %s | %s | %s |" % (c["name"], c["status"].upper(), str(c["detail"]).replace("|", "/")))
        env = report["environment"]
        lines += ["", "Python %s · %s · %s · SQLite %s" % (env["python"], env["os"], env["machine"], env["sqlite"])]
        if report["errors"]:
            lines += ["", "<details><summary>%d error(s) in the last 24 hours</summary>" % report["error_count"], "", FENCE]
            lines += ["%s  %s" % (e["time"], e["message"].replace(FENCE, "'''")) for e in report["errors"]]
            lines += [FENCE, "</details>"]
        lines += ["", "<sub>Sent automatically by the application's monitoring connection. Health data only.</sub>"]
        return redact("\n".join(lines))

    def send(self, kind, report):
        """Post one report now and return the comment's address. A failed report waits in the outbox."""
        body = self.compose(kind, report)
        with self._lock:
            if not self.cfg.get("token"):
                raise MonitorError("No GitHub token is set.")
            try:
                num = self._ensure_issue()
                for queued in list(self.cfg["outbox"]):
                    self._req("POST", "/repos/%s/issues/%d/comments" % (self.cfg["repo"], num), {"body": queued})
                    self.cfg["outbox"].remove(queued)
                c = self._req("POST", "/repos/%s/issues/%d/comments" % (self.cfg["repo"], num), {"body": body})
                if getattr(self, "store", None):
                    self.store.activity("Monitoring report sent (%s)" % kind, "ok", self.cfg["repo"])
                self.cfg["last_sent"], self.cfg["last_status"] = now_iso(), "sent: %s" % kind.lower()
                if kind in ("Test", "Check-in"):        # a test report counts as the day's check-in
                    self.cfg["last_heartbeat_ts"], self.cfg["last_heartbeat"] = time.time(), now_iso()
                self._save()
                return c.get("html_url") or self.cfg.get("issue_url")
            except MonitorError as e:
                if getattr(self, "store", None):
                    self.store.activity("Monitoring report (%s)" % kind, "failed", str(e))
                if kind != "Test":
                    self.cfg["outbox"] = (self.cfg["outbox"] + [body])[-20:]
                self.cfg["last_status"] = "not sent: %s" % e
                self._save()
                raise

    def due(self, report, now=None):
        """('Problem', signature), ('Check-in', None) or None."""
        if not self.cfg["enabled"] or not self.cfg.get("token"):
            return None
        now = now or time.time()
        if report["overall"] != "ok":
            sig = "%s:%s:%d" % (report["overall"], ",".join(sorted(c["id"] for c in report["checks"] if c["status"] != "ok")),
                                min(report["error_count"], 99))
            if now - self.cfg["sent"].get(sig, 0) > 6 * 3600:
                return "Problem", sig
        if self.cfg["frequency"] == "problems":
            return None
        gap = 3600 if self.cfg["frequency"] == "hourly" else 24 * 3600
        if now - self.cfg.get("last_heartbeat_ts", 0) >= gap - 60:
            return "Check-in", None
        return None

    def tick(self, diagnostics, now=None):
        report = diagnostics.run()
        d = self.due(report, now)
        if not d:
            return None
        kind, sig = d
        try:
            url = self.send(kind, report)
        except MonitorError as e:
            self.log("monitor: report not sent:", e)
            return None
        t = now or time.time()
        with self._lock:
            if sig:
                self.cfg["sent"] = {k: v for k, v in self.cfg["sent"].items() if t - v < 7 * 86400}
                self.cfg["sent"][sig] = t
            # any report proves the connection; a problem report also counts as the day's check-in
            self.cfg["last_heartbeat_ts"] = t
            self.cfg["last_heartbeat"] = now_iso()
            self._save()
        return url

    def on_error(self, line):
        self._wake.set()

    def start(self, diagnostics):
        if self._thread:
            return

        def loop():
            time.sleep(20)
            while True:
                try:
                    self.tick(diagnostics)
                except Exception as e:
                    self.log("monitor: check failed:", repr(e))
                woke = self._wake.wait(3600)
                self._wake.clear()
                if woke:
                    time.sleep(60)          # let a burst of errors finish, then report it once
        self._thread = threading.Thread(target=loop, daemon=True, name="monitor")
        self._thread.start()


# ----------------------------------------------------------------------------- Google Cloud link (optional)
class CloudLink:
    """Off-site backups to Cloud Storage and health metrics to Cloud Monitoring, in the background.
    Nothing here blocks the application; every attempt is in the activity log with its time to 0.01 s."""

    def __init__(self, store, app_id, app_name, log):
        import gcloud
        self.gc_mod = gcloud
        self.store, self.app_id, self.app_name, self.log = store, app_id, app_name, log
        self.settings = gcloud.Settings(store.folder)
        self.g = gcloud.Google(self.settings, log)
        self.state_path = os.path.join(store.folder, "cloud-state.json")
        self._q, self._busy = [], False
        self._lock = threading.Lock()
        self.host = re.sub(r"[^A-Za-z0-9_\-]", "-", socket.gethostname())[:60] or "computer"

    def state(self):
        try:
            with open(self.state_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _set_state(self, **kw):
        st = self.state(); st.update(kw)
        with open(self.state_path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(st, f)
        os.replace(self.state_path + ".tmp", self.state_path)

    def prefix(self):
        return "querybook/%s/%s/" % (self.app_id, self.host)

    def storage_ready(self):
        c = self.settings.public()
        return c["storage_on"] and c["bucket"] and c["service_account"]

    def enqueue(self, path):
        if not self.storage_ready():
            return
        with self._lock:
            self._q.append(path)
            if self._busy:
                return
            self._busy = True
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self):
        while True:
            with self._lock:
                if not self._q:
                    self._busy = False
                    return
                path = self._q.pop()                     # newest first; older queued copies are superseded
                self._q.clear()
            self.upload_backup(path)

    def upload_backup(self, path, progress=None):
        t0 = time.time()
        name = self.prefix() + os.path.basename(path)
        try:
            meta = self.g.upload(path, name, progress)
            self._set_state(last_upload=now_cs(), last_object=name, last_md5=meta.get("md5Hash"), last_bytes=int(meta.get("size", 0)),
                            last_error=None, last_seconds=round(time.time() - t0, 2))
            keep = self.settings.public()["keep"]
            for old in self.g.list(self.prefix())[keep:]:
                self.g.delete(old["name"])
            self.store.activity("Cloud backup uploaded", "ok", "%s (MD5 matched)" % name, int((time.time() - t0) * 1000))
            return meta
        except Exception as e:
            msg = self.settings.scrub(e)
            self._set_state(last_error=msg, last_error_at=now_cs())
            self.store.activity("Cloud backup uploaded", "failed", msg, int((time.time() - t0) * 1000))
            self.log("ERROR", "cloud backup failed:", msg)
            return None

    def send_metrics(self, report):
        c = self.settings.public()
        if not (c["monitoring_on"] and c["service_account"] and c["project_id"]):
            return
        order = {"ok": 0, "warn": 1, "fail": 2}
        vals = {"health": order.get(report["overall"], 2), "checks_failed": sum(1 for x in report["checks"] if x["status"] == "fail"),
                "checks_warned": sum(1 for x in report["checks"] if x["status"] == "warn"), "error_count": int(report.get("error_count") or 0),
                "uptime_hours": round((time.time() - getattr(self, "started", time.time())) / 3600, 2)}

        def go():
            t0 = time.time()
            try:
                self.g.write_metrics(self.app_id, self.host, vals)
                self._set_state(last_metrics=now_cs(), metrics_error=None)
                self.store.activity("Cloud Monitoring report", "ok", "health=%s" % report["overall"], int((time.time() - t0) * 1000))
            except Exception as e:
                self._set_state(metrics_error=self.settings.scrub(e), metrics_error_at=now_cs())
                self.store.activity("Cloud Monitoring report", "failed", self.settings.scrub(e), int((time.time() - t0) * 1000))
        threading.Thread(target=go, daemon=True).start()

    def checks(self):
        C = _check
        c = self.settings.public()
        if not (c["api_key_set"] or c["service_account"]):
            return [C("google", "Google Cloud", "ok", "not connected (optional) — connect on the Diagnostics page")]
        out = [C("google", "Google Cloud", "ok", "API key %s; service account %s" % ("set" if c["api_key_set"] else "not set",
                                                                                   c["service_account"]["client_email"] if c["service_account"] else "not set"))]
        st = self.state()
        if c["service_account"]:
            t0 = time.time()
            try:
                self.g.token()
                out.append(C("google_auth", "Google sign-in (service account)", "ok", "token in %.2f s" % (time.time() - t0)))
            except Exception as e:
                out.append(C("google_auth", "Google sign-in (service account)", "fail", self.settings.scrub(e)[:200]))
        if c["storage_on"]:
            b = self.store.backups()
            if st.get("last_error") and (st.get("last_error_at") or "") > (st.get("last_upload") or ""):
                out.append(C("cloud_backup", "Cloud Storage backup", "fail", "last upload failed: %s" % st["last_error"][:200]))
            elif not st.get("last_upload"):
                out.append(C("cloud_backup", "Cloud Storage backup", "warn", "no upload yet — press 'Back up to Cloud now'"))
            else:
                same = b and st.get("last_object", "").endswith(b[0]["name"])
                out.append(C("cloud_backup", "Cloud Storage backup", "ok" if same else "warn",
                             "newest upload %s, %s, MD5 matched; %s" % (st["last_upload"], _kb(st.get("last_bytes", 0)),
                                                                      "same as the newest local backup" if same else "a newer local backup is waiting")))
        if c["monitoring_on"]:
            if st.get("metrics_error") and (st.get("metrics_error_at") or "") > (st.get("last_metrics") or ""):
                out.append(C("cloud_monitoring", "Cloud Monitoring", "warn", "last report failed: %s" % st["metrics_error"][:200]))
            else:
                out.append(C("cloud_monitoring", "Cloud Monitoring", "ok", "last report %s" % (st.get("last_metrics") or "not yet (sent after this check)")))
        return out


def _first_run_google(cloud, diag, program_dir):
    """A personalised copy may carry google-setup.json next to the program ({"api_key": …} or {"code": "QBSETUP-…"}).
    On first start it is moved into the private settings of every QueryBook application on this computer and the
    file is deleted, so the key does not stay in the program folder."""
    f = os.path.join(program_dir, "google-setup.json")
    if not os.path.isfile(f):
        return
    try:
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh) or {}
        vals = cloud.gc_mod.decode_setup_code(d["code"]) if d.get("code") else {k: d[k] for k in ("api_key", "project_id", "bucket") if d.get(k)}
        applied = []
        for other in ("language", "stem", "facts"):
            folder = diag.store.folder if other == diag.app_id else data_folder(other, os.path.join(os.path.dirname(program_dir), other))
            try:
                os.makedirs(folder, exist_ok=True)
                st = cloud.gc_mod.Settings(folder)
                if other == diag.app_id or not st.api_key():
                    st.save(vals)
                    applied.append(other)
            except (OSError, ValueError):
                pass
        diag.store.activity("Google settings installed from this copy", "ok", "applied to: " + ", ".join(applied))
    except Exception as e:
        diag.store.activity("Google settings installed from this copy", "failed", redact(e))
    finally:
        try:
            os.remove(f)
        except OSError:
            pass


def _google_siblings(app_id):
    """Other QueryBook applications on this computer that already hold Google settings (to copy them)."""
    out = []
    for other in ("language", "stem", "facts"):
        if other == app_id:
            continue
        f = os.path.join(data_folder(other, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", other)), "google.json")
        if os.path.isfile(f):
            out.append({"app": other, "path": f})
    return out


def _kb(n):
    return "%.1f MB" % (n / 2**20) if n >= 2**20 else "%d KB" % (n // 1024)


def add_diagnostics(api, diag, monitor, program_dir):
    """Register the diagnostics and monitoring routes every application shares."""
    monitor.store = diag.store
    cloud = CloudLink(diag.store, diag.app_id, diag.app_name, diag.log)
    cloud.started = diag.started
    diag.store.cloud = cloud
    diag.cloud = cloud
    _first_run_google(cloud, diag, program_dir)

    @api.get("/api/gcloud")
    def gcloud_get(p):
        return {"settings": cloud.settings.public(), "state": cloud.state(), "prefix": cloud.prefix(), "last": cloud.g.last,
                "siblings": _google_siblings(diag.app_id)}

    @api.post("/api/gcloud")
    def gcloud_set(p):
        try:
            cloud.settings.save(p)
        except ValueError as e:
            raise UserError(str(e))
        cloud.g._tok = None
        diag.store.activity("Google Cloud settings saved", "ok", ", ".join(k for k in ("api_key", "service_account_json", "bucket", "storage_on", "monitoring_on") if k in p))
        return gcloud_get(p)

    @api.get("/api/gcloud/setup-script")
    def gcloud_setup_script(p):
        return {"script": cloud.gc_mod.SETUP_SCRIPT}

    @api.post("/api/gcloud/setup-code")
    def gcloud_setup_code(p):
        """Apply the one-paste setup code — to this application and (by default) every QueryBook application on this computer."""
        try:
            vals = cloud.gc_mod.decode_setup_code(p.get("code"))
            cloud.settings.save(vals)
        except ValueError as e:
            raise UserError(str(e))
        cloud.g._tok = None
        applied = [diag.app_id]
        if p.get("all_apps", True) not in (False, "false"):
            for other in ("language", "stem", "facts"):
                if other == diag.app_id:
                    continue
                folder = data_folder(other, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", other))
                try:
                    os.makedirs(folder, exist_ok=True)
                    cloud.gc_mod.Settings(folder).save(vals)
                    applied.append(other)
                except (OSError, ValueError):
                    pass
        diag.store.activity("Google Cloud set up from a setup code", "ok", "applied to: " + ", ".join(applied))
        out = gcloud_get(p)
        out["applied_to"] = applied
        return out

    @api.post("/api/gcloud/forget")
    def gcloud_forget(p):
        cloud.settings.forget(); cloud.g._tok = None
        diag.store.activity("Google Cloud disconnected", "ok")
        return gcloud_get(p)

    @api.post("/api/gcloud/copy-from")
    def gcloud_copy(p):
        src = dict((s["app"], s["path"]) for s in _google_siblings(diag.app_id)).get(p.get("app"))
        if not src:
            raise UserError("No Google settings found for that application.")
        with open(src, encoding="utf-8") as f:
            cfg = json.load(f)
        cloud.settings._write(cfg); cloud.g._tok = None
        diag.store.activity("Google Cloud settings copied", "ok", "from " + p.get("app"))
        return gcloud_get(p)

    @api.post("/api/gcloud/test")
    def gcloud_test(p):
        """Try every connected Google service now and report each result with its time."""
        out, c = [], cloud.settings.public()

        def step(name, fn):
            t0 = time.time()
            try:
                detail = fn()
                out.append({"service": name, "ok": True, "seconds": round(time.time() - t0, 2), "detail": detail})
            except Exception as e:
                out.append({"service": name, "ok": False, "seconds": round(time.time() - t0, 2), "detail": cloud.settings.scrub(e)[:300]})
        if c["service_account"]:
            step("Sign-in (service account)", lambda: (cloud.g.token(), "token received")[1])
            if c["bucket"]:
                step("Cloud Storage bucket", lambda: "bucket %s in %s" % ((lambda i: (i.get("name"), i.get("location")))(cloud.g.bucket_info())))
            if c["project_id"]:
                step("Cloud Monitoring", lambda: (cloud.g.write_metrics(diag.app_id, cloud.host, {"test": 1}), "test metric written")[1])
        else:
            out.append({"service": "Service account", "ok": False, "seconds": 0, "detail": "not added — needed for Cloud Storage and Monitoring"})
        if c["api_key_set"]:
            step("API key (YouTube Data API)", lambda: "%d result(s)" % len(cloud.g.youtube_search("QueryBook test", 1)))
            if diag.app_id == "language":
                import io, math, struct, wave
                b = io.BytesIO()
                with wave.open(b, "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                    w.writeframes(b"".join(struct.pack("<h", int(3000 * math.sin(i / 8.0))) for i in range(8000)))
                step("Speech-to-Text", lambda: "answered (%s)" % (cloud.g.recognize(b.getvalue())["transcript"] or "no words in a test tone, as expected"))
        else:
            out.append({"service": "API key", "ok": False, "seconds": 0, "detail": "not added — needed for Speech-to-Text, Text-to-Speech and YouTube"})
        diag.store.activity("Google Cloud test", "ok" if all(x["ok"] for x in out) else "failed",
                            "; ".join("%s: %s" % (x["service"], "ok" if x["ok"] else "failed") for x in out))
        return {"results": out}

    @api.post("/api/gcloud/backup-now")
    def gcloud_backup_now(p):
        if not cloud.storage_ready():
            raise UserError("Add a service account and a bucket, and switch on Cloud Storage backups first.")

        def run(prog, stop):
            path = diag.store.backup("cloud", force=True) or diag.store.backups()[0]["path"]
            with cloud._lock:
                cloud._q.clear()
            meta = cloud.upload_backup(path, lambda d, t: prog(d, t, "uploading %s of %s" % (_kb(d), _kb(t))))
            if not meta:
                raise RuntimeError(cloud.state().get("last_error") or "upload failed")
            return {"object": meta.get("name"), "bytes": int(meta.get("size", 0)), "md5_matched": True}
        return diag.jobs.start("Back up to Cloud Storage", run) if diag.jobs else run(lambda *a: None, lambda: False)

    @api.get("/api/gcloud/backups")
    def gcloud_backups(p):
        try:
            return {"backups": cloud.g.list(cloud.prefix())}
        except Exception as e:
            raise UserError(cloud.settings.scrub(e))

    @api.post("/api/gcloud/fetch")
    def gcloud_fetch(p):
        name = p.get("name") or ""
        if not name.startswith(cloud.prefix()) or "/" in name[len(cloud.prefix()):]:
            raise UserError("That is not one of this application's cloud backups.")
        dest = os.path.join(diag.store.backup_dir, os.path.basename(name))
        cloud.g.download(name, dest)
        c = sqlite3.connect(dest)
        ok = c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        c.close()
        if not ok:
            os.remove(dest)
            raise UserError("The downloaded copy failed its database check and was discarded.")
        diag.store.activity("Cloud backup downloaded", "ok", os.path.basename(name))
        return {"saved": os.path.basename(dest), "note": "Saved with the local backups. To restore: close the app, run python app.py restore, choose it."}

    @api.post("/api/gcloud/alert")
    def gcloud_alert(p):
        try:
            r = cloud.g.create_alert(diag.app_id, diag.app_name)
        except Exception as e:
            raise UserError(cloud.settings.scrub(e))
        diag.store.activity("Cloud Monitoring alert created", "ok", r.get("name", ""))
        return {"policy": r.get("name"), "display_name": r.get("displayName")}

    @api.get("/api/diagnostics")
    def diagnostics(p):
        return diag.last or diag.run()

    @api.post("/api/diagnostics/run")
    def diagnostics_run(p):
        return diag.run()

    @api.get("/api/mirror")
    def mirror_get(p):
        st = diag.store
        return {"folder": st.mirror_dir(), "copies": [{"name": x["name"], "kb": x["bytes"] // 1024} for x in st.mirror_backups()[:10]]}

    @api.post("/api/mirror")
    def mirror_set(p):
        d = diag.store.set_mirror(p.get("folder") or "off")
        return {"folder": d, "copies": len(diag.store.mirror_backups())}

    @api.get("/api/diagnostics/report.txt")
    def diagnostics_text(p):
        return diag.text(diag.run()).encode("utf-8"), "text/plain; charset=utf-8"

    @api.post("/api/selftest")
    def selftest(p):
        import subprocess
        kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
        try:
            r = subprocess.run([sys.executable, "-B", os.path.join(program_dir, "app.py"), "--selftest"], cwd=program_dir,
                               capture_output=True, text=True, timeout=600, **kw)
        except subprocess.TimeoutExpired:
            raise UserError("The self-test took longer than 10 minutes and was stopped.")
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0:
            diag.log("ERROR", "self-test failed:", " / ".join(l.strip() for l in out.splitlines() if "[FAIL]" in l)[:500])
        return {"passed": r.returncode == 0, "output": redact(out)[-20000:]}

    @api.get("/api/activity")
    def activity(p):
        return {"activity": diag.store.activities(min(1000, int(p.get("limit") or 200)), p.get("task") or None)}

    @api.get("/api/monitor")
    def monitor_get(p):
        return monitor.public()

    @api.post("/api/monitor")
    def monitor_set(p):
        return monitor.configure(p.get("enabled"), p.get("repo"), p.get("token"), p.get("label"), p.get("frequency"))

    @api.post("/api/monitor/disconnect")
    def monitor_disconnect(p):
        return monitor.disconnect()

    @api.get("/api/monitor/preview")
    def monitor_preview(p):
        return {"title": monitor.title(), "body": monitor.compose("Check-in", diag.run())}

    @api.post("/api/monitor/test")
    def monitor_test(p):
        try:
            url = monitor.send("Test", diag.run())
        except MonitorError as e:
            raise UserError(str(e))
        return {"sent": True, "url": url, "monitor": monitor.public()}


# ----------------------------------------------------------------------------- self-test helpers
class Checks:
    def __init__(self):
        self.results = []

    def check(self, name, cond, detail=""):
        self.results.append((bool(cond), name, detail))
        return bool(cond)

    def report(self, title):
        ok = sum(1 for r in self.results if r[0])
        print("\n%s — self-test" % title)
        for good, name, detail in self.results:
            print("  [%s] %s%s" % ("OK" if good else "FAIL", name, (" — " + str(detail)) if (detail and not good) else ""))
        print("  %d of %d checks passed\n" % (ok, len(self.results)))
        return ok == len(self.results)


def core_matches_master(program_dir):
    """True when this app's shared modules match the master copies in ../_core (or no master is present)."""
    for name in ("qbcore.py", "qbcommons.py", "qbharvest.py"):
        master = os.path.join(os.path.dirname(program_dir), "_core", name)
        mine = os.path.join(program_dir, name)
        if not os.path.exists(master):
            continue
        if not os.path.exists(mine):
            return False
        with open(master, "rb") as a, open(mine, "rb") as b:
            if a.read() != b.read():
                return False
    return True


# ----------------------------------------------------------------------------- command line
def _harvest_cli(inst, cmd, a):
    import getpass
    c, team = inst.commons, inst.team
    sub = a[0] if a else "status"
    try:
        if cmd == "harvest-engine":
            if sub == "status":
                st = c.engine.status()
                for h in st["heartbeats"]:
                    print("  %-9s last heard %6.0f s ago" % (h["app"], h["seconds_ago"]))
                for t in st["turns"][:10]:
                    print("  turn %-4d %s %-8s %s" % (t["id"], t["started"][:19], t["domain"], t["reason"]))
                print("  pending approvals: %d   policy version: %s" % (len(c.approvals.list("pending")), c.registry.version()))
            elif sub == "turn":
                out = team.engine_turn("command line")
                print(json.dumps(out, indent=2) if out else "Not this application's turn (another is harvesting, or it is backing off).")
            elif sub == "log":
                for h in reversed(c.harvest_log.recent(limit=int(a[1]) if len(a) > 1 else 30)):
                    print("  #%-5d %s %-8s %-9s %-22s %3d new  %s" % (h["id"], h["at"][:19], h["domain"], h["decision"], h["source_key"] or "", h["new"], h["reason"][:80]))
            elif sub == "verify":
                v = c.harvest_log.verify()
                print(json.dumps(v, indent=2))
                return 0 if v["ok"] else 1
            elif sub == "archive":
                print(json.dumps(c.harvest_log.archive(), indent=2))
            elif sub in ("review", "pending"):
                if sub == "review":
                    print("New recommendations:", c.learner.review(team.app_id))
                for r in c.approvals.list("pending"):
                    print("  #%-4d [%s] %s\n        %s" % (r["id"], r["kind"], r["title"], r["rationale"]))
            else:
                print("unknown: harvest-engine", sub)
                return 2
            return 0
        if sub == "set-pass":
            old = getpass.getpass("Current admin passphrase: ") if c.approvals.admin_set() else None
            c.approvals.set_admin(getpass.getpass("New admin passphrase (8+ characters): "), old)
            print("Admin passphrase saved.")
        elif sub in ("approve", "reject") and len(a) > 1:
            print(c.approvals.decide(int(a[1]), sub == "approve", getpass.getpass("Admin passphrase: "), " ".join(a[2:])))
        elif sub == "source" and len(a) > 2:
            cls = next((x for x in a[3:] if not x.startswith("--")), None)
            c.approvals.admin_source(a[1], a[2], getpass.getpass("Admin passphrase: "), "admin decision (command line)", cls, "--accept-restriction" in a)
            print("Registry updated.")
        else:
            print("usage: harvest-admin set-pass | approve ID | reject ID | source KEY STATUS [CLASS] [--accept-restriction]")
            return 2
        return 0
    except UserError as e:
        print(e)
        return 1


def run_cli(app):
    """Common command line for every application.

    python app.py                 start (opens the browser)
    python app.py --no-browser    start without opening a browser
    python app.py --selftest      run the self-test in a temporary folder
    python app.py where           show the data folder
    python app.py set-data DIR    use DIR as the data folder from now on
    python app.py backup          take a backup now
    python app.py restore [N]     list backups (and mirror copies), or restore number N
    python app.py set-mirror DIR  keep a verified second copy of every backup in DIR (off to stop)
    python app.py import-old DIR  import from an old QueryBook store (read-only)
    python app.py diagnose        run the internal diagnostics and print the report
    python app.py harvest         run this application's harvest team once (shared database)
    python app.py harvest-engine status|turn|log [N]|verify|archive|review|pending
                                  the harvesting engine: rotation, one engine turn, the harvest log, its hash chain
    python app.py harvest-admin set-pass | approve ID | reject ID | source KEY approved|blocked|pending [CLASS] [--accept-restriction]
                                  admin decisions (asks for the admin passphrase)
    """
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help", "help"):
        print(run_cli.__doc__)
        return 0
    if args and args[0] == "--selftest":
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:             # never touch the real shared database
            os.environ["QB_COMMONS_DATA"] = os.path.join(tmp, "commons")
            return 0 if app.selftest() else 1
    if args and args[0] == "set-data":
        if len(args) < 2:
            print("usage: python app.py set-data FOLDER")
            return 2
        set_data_folder(app.program_dir, args[1])
        print("Data folder set to", os.path.abspath(os.path.expanduser(args[1])))
        return 0
    if args and args[0] == "where":
        print(data_folder(app.APP_ID, app.program_dir))
        return 0
    inst = app.open_app()
    if args and args[0] == "backup":
        print("Backup written:", inst.store.backup("manual", force=True))
        return 0
    if args and args[0] == "set-mirror":
        if len(args) < 2:
            print("usage: python app.py set-mirror FOLDER   (or: set-mirror off)")
            return 2
        d = inst.store.set_mirror(args[1])
        print("Backup mirror:", d or "off")
        return 0
    if args and args[0] == "restore":
        b = inst.store.backups() + inst.store.mirror_backups()
        if len(args) < 2:
            for i, x in enumerate(b, 1):
                print("  [%d] %s  (%d KB)%s" % (i, x["name"], x["bytes"] // 1024, "  [mirror]" if x.get("mirror") else ""))
            print("\nTo restore one: python app.py restore NUMBER   (close the app first)")
            return 0
        k = int(args[1]) - 1
        print("Restored:", inst.store.restore(b[k]["path"]))
        return 0
    if args and args[0] == "diagnose":
        r = inst.diag.run()
        print(inst.diag.text(r))
        return 0 if r["overall"] != "fail" else 1
    if args and args[0] == "import-old":
        if len(args) < 2:
            print("usage: python app.py import-old FOLDER")
            return 2
        res = inst.import_old(args[1], lambda d, t=None, m="": print("\r  %s %s" % (d, m), end=""), lambda: False)
        print("\n", json.dumps(res, indent=2))
        return 0
    if args and args[0] == "harvest":
        if not getattr(inst, "team", None):
            print("The shared database (Commons) could not be opened; see the log.")
            return 1
        print("Shared database:", inst.commons.store.path)
        print(json.dumps(inst.team.cycle("command line"), indent=2))
        return 0
    if args and args[0] in ("harvest-engine", "harvest-admin"):
        if not getattr(inst, "team", None):
            print("The shared database (Commons) could not be opened; see the log.")
            return 1
        return _harvest_cli(inst, args[0], args[1:])
    if args and args[0] in getattr(inst, "CLI_COMMANDS", {}):
        return inst.CLI_COMMANDS[args[0]](args[1:])
    if getattr(inst, "monitor", None):
        inst.monitor.start(inst.diag)
    if hasattr(inst, "autostart"):
        inst.autostart()
    if getattr(inst, "team", None):
        inst.team.start_schedule()
    inst.store.activity("Application started", "ok", "version %s" % app.VERSION)
    serve(app.APP_NAME, inst.api, os.path.join(app.program_dir, "ui"), app.PORT, inst.log,
          open_browser="--no-browser" not in args, store=inst.store)
    inst.store.activity("Application stopped", "ok")
    return 0
