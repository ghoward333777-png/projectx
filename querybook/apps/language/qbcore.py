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
import sys, threading, time, traceback, urllib.parse, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CORE_VERSION = "1.0.0"
BACKUPS_KEPT = 10


# ----------------------------------------------------------------------------- utilities
def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        os.makedirs(self.backup_dir, exist_ok=True)
        self._check()
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
    return log


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
          ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".wav": "audio/wav", ".json": "application/json"}


def make_handler(api, ui_dir, log, app_name):
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
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

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
            try:
                out = fn(params)
                if isinstance(out, tuple) and len(out) == 2 and isinstance(out[0], (bytes, bytearray)):
                    return self._send(200, bytes(out[0]), out[1])
                return self._send(200, out if out is not None else {"ok": True})
            except (UserError, DatabaseDamaged) as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:
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
            self._send(200, data, _TYPES.get(os.path.splitext(p)[1], "application/octet-stream"))

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


def serve(app_name, api, ui_dir, port, log, open_browser=True, on_start=None):
    port = free_port(port)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(api, ui_dir, log, app_name))
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

    def __init__(self, log):
        self.log = log
        self.lock = threading.Lock()
        self.current = None
        self.last = None
        self._stop = threading.Event()

    def start(self, name, fn):
        with self.lock:
            if self.current and self.current["state"] == "running":
                raise UserError("'%s' is still running. Wait for it to finish or stop it." % self.current["name"])
            self._stop.clear()
            job = {"name": name, "state": "running", "done": 0, "total": None, "message": "", "started": now_iso(), "result": None}
            self.current = job

        def progress(done, total=None, message=""):
            job["done"], job["total"], job["message"] = done, total, message

        def run():
            try:
                job["result"] = fn(progress, self._stop.is_set)
                job["state"] = "stopped" if self._stop.is_set() else "finished"
            except Exception as e:
                job["state"] = "failed"
                job["message"] = str(e)
                self.log("JOB FAILED", name, repr(e), traceback.format_exc().replace("\n", " | "))
            job["ended"] = now_iso()
            self.last = job
        threading.Thread(target=run, daemon=True).start()
        return job

    def stop(self):
        self._stop.set()

    def status(self):
        return self.current or {"state": "idle"}


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
    """True when this app's qbcore.py matches the master copy in ../_core (or no master is present)."""
    master = os.path.join(os.path.dirname(program_dir), "_core", "qbcore.py")
    mine = os.path.join(program_dir, "qbcore.py")
    if not os.path.exists(master):
        return True
    with open(master, "rb") as a, open(mine, "rb") as b:
        return a.read() == b.read()


# ----------------------------------------------------------------------------- command line
def run_cli(app):
    """Common command line for every application.

    python app.py                 start (opens the browser)
    python app.py --no-browser    start without opening a browser
    python app.py --selftest      run the self-test in a temporary folder
    python app.py where           show the data folder
    python app.py set-data DIR    use DIR as the data folder from now on
    python app.py backup          take a backup now
    python app.py restore [N]     list backups, or restore backup number N
    python app.py import-old DIR  import from an old QueryBook store (read-only)
    """
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help", "help"):
        print(run_cli.__doc__)
        return 0
    if args and args[0] == "--selftest":
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
    if args and args[0] == "restore":
        b = inst.store.backups()
        if len(args) < 2:
            for i, x in enumerate(b, 1):
                print("  [%d] %s  (%d KB)" % (i, x["name"], x["bytes"] // 1024))
            print("\nTo restore one: python app.py restore NUMBER   (close the app first)")
            return 0
        k = int(args[1]) - 1
        print("Restored:", inst.store.restore(b[k]["path"]))
        return 0
    if args and args[0] == "import-old":
        if len(args) < 2:
            print("usage: python app.py import-old FOLDER")
            return 2
        res = inst.import_old(args[1], lambda d, t=None, m="": print("\r  %s %s" % (d, m), end=""), lambda: False)
        print("\n", json.dumps(res, indent=2))
        return 0
    serve(app.APP_NAME, inst.api, os.path.join(app.program_dir, "ui"), app.PORT, inst.log,
          open_browser="--no-browser" not in args)
    return 0
