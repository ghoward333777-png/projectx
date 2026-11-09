"""qbvault — backups of every saved fact to another drive (the backup drive), checked, dated, and never thinned blindly.

The shared folder (the Commons and every bulk dataset) and the applications' own data folders are copied to a folder the
admin chooses on another drive. Each backup is a GENERATION: a dated list of every file and the facts it holds. The files
themselves are kept once in an object store, so a dataset that has not changed since the last backup costs nothing more
(no hard links needed: works on NTFS, exFAT and Mac drives alike).

Rules:
  * a database is copied with SQLite's own online backup (one consistent snapshot, while the harvest keeps writing), then
    opened and checked (PRAGMA quick_check) and its fact count read; a plain file is checked by SHA-256. A generation is
    written only when every one of its files passed — a half or unchecked backup never counts as one;
  * thinning keeps the newest generations (setting `keep`, 7 by default) AND, for every file, the generation that holds the
    most facts it ever had — so a dataset that shrinks (by a fault or a mistake) can always be brought back to its best;
  * a backup that finds a dataset with fewer facts than in the last backup (more than its removed duplicates explain) says
    so loudly; the older, fuller copy stays protected by the rule above;
  * restoring only ADDS: facts a backup holds that the live dataset lacks are merged back (qbbulk.merge_into); a live file
    that is missing altogether is copied back. Nothing live is ever deleted or overwritten;
  * the newest backup is one of the copies the start-up check (qbbulk.restore_missing) compares with, so missing facts come
    back by themselves when the backup drive is connected.

Settings: <shared folder>/backup.json {"folder": "E:\\\\QB-Backup", "keep": 7, "every_hours": 24, "on": true}. Progress:
<shared folder>/backup-status.json. Layout on the backup drive: <folder>/QueryBook-Backup/{objects,generations}.

Run: python qbvault.py backup|status|restore|self-test --commons <shared folder> [--to <backup folder>]
"""
import datetime, hashlib, json, os, shutil, sqlite3, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "1.0.0"
NAME = "QueryBook-Backup"
KEEP = 7                          # newest generations kept (plus each file's fullest generation)
EVERY_HOURS = 24                  # automatic backups: at most this often, while the harvest runs and the drive is connected
PLAIN_MAX = 256 << 20             # plain (non-database) files up to this size are backed up; bigger ones are listed as skipped
SKIP_DIRS = {"_cache", "_slots", "_agents", "_results", "trace", "dumps", "backups", "__pycache__", NAME}
SKIP_PARTS = (".set-aside", ".replaced-", ".draining", ".pulling")
SKIP_SUFFIX = ("-wal", "-shm", "-journal", ".tmp", ".part", ".lock")
SQLITE_HEAD = b"SQLite format 3\x00"


# ------------------------------------------------------------------------------------------------ settings
def _cfg_path(cf):
    return os.path.join(cf, "backup.json")


def config(cf):
    try:
        with open(_cfg_path(cf), encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        c = {}
    return {"folder": c.get("folder") or "", "keep": int(c.get("keep") or KEEP), "every_hours": float(c.get("every_hours") or EVERY_HOURS),
            "on": c.get("on", True) is not False}


def save_config(cf, folder=None, keep=None, every_hours=None, on=None):
    c = config(cf)
    if folder is not None:
        folder = str(folder).strip().strip('"')
        if folder:
            full = os.path.abspath(os.path.expanduser(folder))
            if not os.path.isabs(os.path.expanduser(folder)):
                raise ValueError("Give the whole folder, with its drive — e.g. E:\\QB-Backup")
            drive = os.path.splitdrive(full)[0]
            if drive and not os.path.exists(drive + os.sep):
                raise ValueError("The drive %s is not connected." % drive)
            if _same_drive(full, cf):
                raise ValueError("The backup must be on ANOTHER drive than the shared folder (%s): a backup on the same drive "
                                 "is lost with it." % cf)
            os.makedirs(full, exist_ok=True)
            folder = full
        c["folder"] = folder
    if keep is not None:
        c["keep"] = max(2, int(keep))
    if every_hours is not None:
        c["every_hours"] = max(1.0, float(every_hours))
    if on is not None:
        c["on"] = on in (True, "on", "true", 1, "1")
    with open(_cfg_path(cf) + ".tmp", "w", encoding="utf-8") as f:
        json.dump(c, f, indent=1)
    os.replace(_cfg_path(cf) + ".tmp", _cfg_path(cf))
    return c


def _same_drive(a, b):
    try:
        if os.name == "nt":
            return os.path.splitdrive(os.path.abspath(a))[0].upper() == os.path.splitdrive(os.path.abspath(b))[0].upper()
        a = os.path.abspath(a)
        while not os.path.exists(a) and os.path.dirname(a) != a:     # a folder not made yet: the drive it would be on
            a = os.path.dirname(a)
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def vault_dir(cf, folder=None):
    """<backup folder>/QueryBook-Backup when a backup folder is set and its drive is connected, else None"""
    folder = folder or config(cf)["folder"]
    if not folder or not os.path.isdir(folder):
        return None
    v = os.path.join(folder, NAME)
    os.makedirs(os.path.join(v, "objects"), exist_ok=True)
    os.makedirs(os.path.join(v, "generations"), exist_ok=True)
    return v


# ------------------------------------------------------------------------------------------------ what is backed up
def _is_db(path):
    try:
        with open(path, "rb") as f:
            return f.read(16) == SQLITE_HEAD
    except OSError:
        return False


def _skip_file(name):
    return name.endswith(SKIP_SUFFIX) or any(p in name for p in SKIP_PARTS) or name in ("backup-status.json",)


def _walk(root, prefix):
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith("."))
        for fn in sorted(files):
            if _skip_file(fn):
                continue
            p = os.path.join(d, fn)
            yield prefix + os.path.relpath(p, root).replace(os.sep, "/"), p


def items(cf):
    """[(name, path)] — every file to back up. A bulk dataset is read from its NEWEST copy (the working copy on the internal
    drive while one exists, else its home copy); the applications' data folders beside the shared folder are included."""
    import qbbulk
    cat = qbbulk.catalog()
    out, seen = [], set()
    for name, p in _walk(cf, "commons/"):
        if name.startswith("commons/%s/" % qbbulk.FOLDER):
            base = name[len("commons/%s/" % qbbulk.FOLDER):]
            key = base[:-len(".sqlite")] if base.endswith(".sqlite") else base[:-len(".sqlite.labels")] if base.endswith(".sqlite.labels") else None
            if key in cat:
                p = qbbulk.shard_path(cf, key) + (".labels" if base.endswith(".labels") else "")
        out.append((name, p)); seen.add(name)
    for key in cat:                                     # a dataset that exists only as a working copy (no home copy yet)
        for sfx in ("", ".labels"):
            name = "commons/%s/%s.sqlite%s" % (qbbulk.FOLDER, key, sfx)
            p = qbbulk.shard_path(cf, key) + sfx
            if name not in seen and os.path.exists(p):
                out.append((name, p)); seen.add(name)
    parent = os.path.dirname(os.path.abspath(cf))
    try:
        import qbdrive
        apps = qbdrive.APPS
    except Exception:
        apps = ("language", "stem", "facts", "control", "video")
    for a in apps:
        d = os.path.join(parent, a)
        if os.path.isdir(d) and os.path.abspath(d) != os.path.abspath(cf):
            out += list(_walk(d, "app/%s/" % a))
    return out


def _sig(path):
    """changes whenever the file's content can have changed: size and time of the file and of its write-ahead log"""
    s = os.stat(path)
    w = path + "-wal"
    ws = os.stat(w) if os.path.exists(w) else None
    if ws is not None and ws.st_size == 0:              # an empty log holds nothing (readers touch its time)
        ws = None
    return [s.st_size, s.st_mtime_ns, ws.st_size if ws else 0, ws.st_mtime_ns if ws else 0]


def _meta(conn):
    try:
        rows = dict(conn.execute("SELECT key, value FROM meta WHERE key IN ('facts', 'duplicates_removed', 'staged')"))
        return {k: json.loads(v) for k, v in rows.items()}
    except sqlite3.Error:
        return {}


def _ro(path):
    return sqlite3.connect("file:%s?mode=ro" % urllib.request.pathname2url(os.path.abspath(path)), uri=True, timeout=60)


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ------------------------------------------------------------------------------------------------ generations
def generations(v):
    """every complete generation, newest first: [manifest]"""
    out = []
    g = os.path.join(v, "generations")
    for fn in sorted(os.listdir(g), reverse=True) if os.path.isdir(g) else []:
        if fn.endswith(".json"):
            try:
                with open(os.path.join(g, fn), encoding="utf-8") as f:
                    m = json.load(f)
                m["_file"] = fn
                out.append(m)
            except (OSError, ValueError):
                pass
    return out


def _facts_of(e):
    return (e.get("facts") or 0) + (e.get("staged") or 0)


def prune(v, keep):
    """thin the backups: keep the newest `keep` generations and, for every file, the generation holding the most facts it ever
    had; then remove the objects no kept generation refers to. Returns the generations removed."""
    gens = generations(v)
    keepset = {m["_file"] for m in gens[:max(2, keep)]}
    best = {}
    for m in gens:                                      # newest first: of equal counts the newest is kept
        for e in m["items"]:
            if e.get("facts") is not None and (e["name"] not in best or _facts_of(e) > best[e["name"]][0]):
                best[e["name"]] = (_facts_of(e), m["_file"])
    keepset |= {f for _, f in best.values()}
    gone = []
    for m in gens:
        if m["_file"] not in keepset:
            os.remove(os.path.join(v, "generations", m["_file"]))
            gone.append(m["_file"])
    used = {e["object"] for m in generations(v) for e in m["items"]}
    objroot = os.path.join(v, "objects")
    for d, dirs, files in os.walk(objroot):
        for fn in files:
            rel = os.path.relpath(os.path.join(d, fn), v).replace(os.sep, "/")
            if rel not in used:
                try:
                    os.remove(os.path.join(d, fn))
                except OSError:
                    pass
    return gone


# ------------------------------------------------------------------------------------------------ status file
def _status_path(cf):
    return os.path.join(cf, "backup-status.json")


def _say(cf, **kw):
    kw["at"] = time.time()
    try:
        with open(_status_path(cf) + ".tmp", "w", encoding="utf-8") as f:
            json.dump(kw, f)
        os.replace(_status_path(cf) + ".tmp", _status_path(cf))
    except OSError:
        pass


def _lock(cf):
    import qbbulk
    return qbbulk.Slots(cf)._lock("backup", 0)


def running(cf):
    import qbbulk
    lk = _lock(cf)
    if lk:
        qbbulk.Slots(cf).release(lk)
        return False
    return True


# ------------------------------------------------------------------------------------------------ backup
def backup(cf, folder=None, reason="manual", stop=None, log=None):
    """one generation: every file copied (or, unchanged since the last generation, referred to), checked, then listed.
    Returns a summary; raises RuntimeError when the backup could not be completed (nothing half-done is ever listed)."""
    import qbbulk
    v = vault_dir(cf, folder)
    if not v:
        raise RuntimeError("the backup drive is not connected (or no backup folder is set): %s" % (folder or config(cf)["folder"] or "not set"))
    lk = _lock(cf)
    if not lk:
        raise RuntimeError("a backup is already running")
    say = log or (lambda *a: None)
    t0 = time.time()
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        for d, _, files in os.walk(os.path.join(v, "objects")):        # an interrupted copy leaves only a .tmp: removed
            for fn in files:
                if fn.endswith(".tmp"):
                    os.remove(os.path.join(d, fn))
        prev = generations(v)
        last = {e["name"]: e for e in prev[0]["items"]} if prev else {}
        todo = items(cf)
        done, warnings, skipped, copied_bytes = [], [], [], 0
        for i, (name, path) in enumerate(todo, 1):
            why = stop() if stop else None
            if why:
                raise RuntimeError("stopped: %s" % why)
            if not os.path.exists(path):
                continue
            size = os.path.getsize(path)
            db = _is_db(path)
            if not db and size > PLAIN_MAX:
                skipped.append({"name": name, "bytes": size, "why": "a large plain file (not a database of facts)"})
                continue
            _say(cf, state="running", step="%d of %d" % (i, len(todo)), file=name, started=t0, reason=reason)
            sig = _sig(path)
            old = last.get(name)
            if old and old.get("sig") == sig and os.path.exists(os.path.join(v, old["object"])):
                done.append(dict(old, reused=True))
                continue
            free = shutil.disk_usage(v).free
            if free < size * 1.05 + (1 << 30):
                prune(v, 2)                                 # make room: down to the two newest (each file's fullest stays)
                free = shutil.disk_usage(v).free
                if free < size * 1.05 + (1 << 30):
                    raise RuntimeError("the backup drive is full: %s needs %.1f GB, %.1f GB free" % (name, size / 1e9, free / 1e9))
            safe = name.replace("/", "__")
            ext = ".sqlite" if db else ""
            rel = "objects/%s/%s%s" % (safe, stamp, ext)
            dst = os.path.join(v, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".tmp"
            say("copying %s (%.1f GB)" % (name, size / 1e9))
            e = {"name": name, "object": rel, "sig": sig, "db": db, "source": path}
            if db:
                src = _ro(path)
                try:
                    out = sqlite3.connect(tmp)
                    try:
                        src.backup(out)                     # one consistent snapshot, whatever is being written meanwhile
                    finally:
                        out.close()
                finally:
                    src.close()
                c = sqlite3.connect(tmp)
                try:
                    c.execute("PRAGMA journal_mode=DELETE")   # one self-contained file on the backup drive
                    chk = c.execute("PRAGMA quick_check").fetchone()[0]
                    m = _meta(c)
                finally:
                    c.close()
                if chk != "ok":
                    os.remove(tmp)
                    raise RuntimeError("the copy of %s failed its check (%s): the backup was not completed" % (name, chk))
                e.update(facts=m.get("facts"), staged=m.get("staged") or 0, dups=m.get("duplicates_removed") or 0, check="quick_check ok")
                if old and old.get("facts") is not None and e["facts"] is not None:
                    expect = _facts_of(old) - max(0, e["dups"] - (old.get("dups") or 0))
                    if _facts_of(e) < expect:
                        warnings.append("%s holds %s facts, the last backup %s: the older copy is kept until it is restored or "
                                        "cleared" % (name, format(_facts_of(e), ","), format(_facts_of(old), ",")))
            else:
                shutil.copyfile(path, tmp)
                h = _sha(tmp)
                if h != _sha(path) and _sig(path) == sig:
                    os.remove(tmp)
                    raise RuntimeError("the copy of %s does not match the original: the backup was not completed" % name)
                e.update(sha256=h, check="sha256")
            os.replace(tmp, dst)
            e["bytes"] = os.path.getsize(dst)
            copied_bytes += e["bytes"]
            done.append(e)
        man = {"generation": stamp, "created": datetime.datetime.now().isoformat(timespec="seconds"), "reason": reason, "version": VERSION,
               "engine": qbbulk.VERSION, "source": os.path.abspath(cf), "items": done, "skipped": skipped, "warnings": warnings,
               "facts": sum(_facts_of(e) for e in done if e.get("facts") is not None),
               "copied_bytes": copied_bytes, "seconds": round(time.time() - t0, 1)}
        gp = os.path.join(v, "generations", stamp + ".json")
        with open(gp + ".tmp", "w", encoding="utf-8") as f:
            json.dump(man, f, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(gp + ".tmp", gp)                          # only now does this generation exist
        gone = prune(v, config(cf)["keep"])
        res = {"state": "done", "generation": stamp, "facts": man["facts"], "files": len(done),
               "copied": sum(1 for e in done if not e.get("reused")), "copied_bytes": copied_bytes, "warnings": warnings,
               "skipped": skipped, "pruned": gone, "seconds": man["seconds"], "folder": v}
        _say(cf, **res)
        return res
    except Exception as e:
        _say(cf, state="failed", why=str(e)[:400], started=t0, reason=reason)
        raise
    finally:
        qbbulk.Slots(cf).release(lk)


def due(cf):
    """True when automatic backups are on, the drive is connected and the last good backup is older than every_hours"""
    c = config(cf)
    if not c["on"] or not c["folder"]:
        return False
    v = vault_dir(cf)
    if not v:
        return False
    g = generations(v)
    if not g:
        return True
    try:
        t = datetime.datetime.strptime(g[0]["generation"], "%Y%m%d-%H%M%S").timestamp()
    except (KeyError, ValueError):
        return True
    return time.time() - t >= c["every_hours"] * 3600


def latest_copy(cf, name):
    """the object holding `name` in the newest generation (for qbbulk.restore_missing), or None"""
    try:
        v = vault_dir(cf)
        if not v:
            return None
        for m in generations(v)[:1]:
            for e in m["items"]:
                if e["name"] == name:
                    p = os.path.join(v, e["object"])
                    return p if os.path.exists(p) else None
    except OSError:
        return None
    return None


def status(cf):
    c = config(cf)
    try:
        with open(_status_path(cf), encoding="utf-8") as f:
            last = json.load(f)
    except (OSError, ValueError):
        last = None
    v = vault_dir(cf) if c["folder"] else None
    gens = generations(v) if v else []
    out = {"config": c, "connected": bool(v), "folder": v, "running": running(cf), "last": last,
           "generations": [{"generation": m["generation"], "created": m.get("created"), "facts": m.get("facts"), "files": len(m["items"]),
                            "warnings": m.get("warnings") or [], "reason": m.get("reason")} for m in gens],
           "due": due(cf) if v else False}
    if v:
        u = shutil.disk_usage(v)
        out.update(free_bytes=u.free, total_bytes=u.total)
    if gens:
        out["newest"] = {e["name"]: _facts_of(e) for e in gens[0]["items"] if e.get("facts") is not None}
    return out


# ------------------------------------------------------------------------------------------------ restore (adds only)
def restore(cf, generation=None, names=None):
    """facts a backup holds that the live files lack are added back; a live file that is missing is copied back. Nothing
    live is deleted or overwritten. Returns {name: {"added": n} | {"copied": true}}."""
    import qbbulk
    v = vault_dir(cf)
    if not v:
        raise RuntimeError("the backup drive is not connected")
    gens = generations(v)
    m = next((g for g in gens if g["generation"] == generation), None) if generation else (gens[0] if gens else None)
    if not m:
        raise RuntimeError("no such backup")
    live = dict(items(cf))
    out = {}
    for e in m["items"]:
        if names and e["name"] not in names:
            continue
        src = os.path.join(v, e["object"])
        if not os.path.exists(src):
            continue
        dst = live.get(e["name"]) or _live_path(cf, e["name"])
        if not dst:
            continue
        if not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst + ".restoring")
            os.replace(dst + ".restoring", dst)
            out[e["name"]] = {"copied": True}
        elif e.get("db") and e["name"].startswith("commons/%s/" % qbbulk.FOLDER) and e["name"].endswith(".sqlite"):
            n = qbbulk.merge_into(dst, src)
            if n:
                out[e["name"]] = {"added": n}
    return out


def _live_path(cf, name):
    if name.startswith("commons/"):
        return os.path.join(cf, *name[len("commons/"):].split("/"))
    if name.startswith("app/"):
        a, rest = name[len("app/"):].split("/", 1)
        return os.path.join(os.path.dirname(os.path.abspath(cf)), a, *rest.split("/"))
    return None


# ------------------------------------------------------------------------------------------------ self-test
def self_test():
    import tempfile
    import qbbulk
    out = []
    ok = lambda n, c, d="": out.append((n, bool(c), d))
    root = tempfile.mkdtemp()
    try:
        cf = os.path.join(root, "QB", "commons")
        dest = os.path.join(root, "BACKUP")
        os.makedirs(os.path.join(cf, "shards")); os.makedirs(os.path.join(root, "QB", "stem")); os.makedirs(dest)
        os.environ["QB_WORK_FOLDER"] = "off"
        key = next(k for k, d in qbbulk.catalog().items() if not getattr(d, "standalone", False))
        sh = qbbulk.Shard(cf, key)
        pid = sh.part("p", "file://x")[0]
        k = lambda n: hashlib.sha256(str(n).encode()).digest()[:16]
        pr = sh.pred("test predicate")
        sh.write(pid, [(k(i), "s%d" % i, pr, "o", pid, i) for i in range(50)], 50); sh.merge()
        sh.db.close()
        with open(os.path.join(cf, "registry.json"), "w") as f:
            f.write('{"a": 1}')
        sqlite3.connect(os.path.join(root, "QB", "stem", "store.sqlite")).executescript("CREATE TABLE t(x); INSERT INTO t VALUES(1);")
        try:
            save_config(cf, folder=os.path.join(cf, "bk"))
            same = False
        except ValueError:
            same = True
        ok("the backup folder must be on another drive than the shared folder", same)
        with open(_cfg_path(cf), "w") as f:
            json.dump({"folder": dest, "keep": 2}, f)
        r1 = backup(cf, reason="test")
        names = {e["name"] for e in generations(vault_dir(cf))[0]["items"]}
        ok("a backup copies the bulk datasets, the shared folder's files and the applications' data folders",
           {"commons/shards/%s.sqlite" % key, "commons/registry.json", "app/stem/store.sqlite"} <= names, names)
        ok("each database copy is checked and its facts counted", r1["facts"] == 50 and all(e.get("check") for e in generations(vault_dir(cf))[0]["items"]), r1)
        time.sleep(1.1)
        r2 = backup(cf, reason="test")
        ok("an unchanged file is not copied again", r2["copied"] == 0 and r2["files"] == r1["files"],
           [(e["name"], e["sig"]) for e in generations(vault_dir(cf))[0]["items"] if not e.get("reused")] + [(e["name"], e["sig"]) for e in generations(vault_dir(cf))[1]["items"]])
        sh = qbbulk.Shard(cf, key)
        sh.db.execute("DELETE FROM facts WHERE fp IN (SELECT fp FROM facts LIMIT 20)")
        sh.set_meta("facts", 30); sh.db.commit(); sh.db.close()
        time.sleep(1.1)
        r3 = backup(cf, reason="test")
        ok("a dataset that shrank is reported", r3["warnings"] and "30" in r3["warnings"][0], r3["warnings"])
        for _ in range(3):
            time.sleep(1.1); backup(cf, reason="test")
        gens = generations(vault_dir(cf))
        best = [m for m in gens if any(e["name"] == "commons/shards/%s.sqlite" % key and e.get("facts") == 50 for e in m["items"])]
        ok("thinning keeps the newest generations and the fullest copy of every file", len(gens) == 3 and best, [m["generation"] for m in gens])
        ok("thinning removes the files no kept generation needs", sum(len(f) for _, _, f in os.walk(os.path.join(vault_dir(cf), "objects")))
           <= sum(len(m["items"]) for m in gens))
        rs = restore(cf, generation=best[0]["generation"], names=["commons/shards/%s.sqlite" % key])
        c = sqlite3.connect(qbbulk.shard_path(cf, key))
        n = c.execute("SELECT count(*) FROM facts").fetchone()[0]; c.close()
        ok("restoring adds the missing facts back and deletes nothing", rs.get("commons/shards/%s.sqlite" % key, {}).get("added") == 20 and n == 50, (rs, n))
        os.remove(os.path.join(cf, "registry.json"))
        restore(cf)
        ok("a missing file is copied back", os.path.exists(os.path.join(cf, "registry.json")))
        ok("the newest backup is offered to the start-up check", latest_copy(cf, "commons/shards/%s.sqlite" % key) is not None)
        with open(_cfg_path(cf), "w") as f:
            json.dump({"folder": os.path.join(root, "GONE")}, f)
        try:
            backup(cf); refused = False
        except RuntimeError as e:
            refused = "not connected" in str(e)
        ok("a backup drive that is not connected is reported, nothing is touched", refused and not due(cf))
    finally:
        os.environ.pop("QB_WORK_FOLDER", None)
        shutil.rmtree(root, ignore_errors=True)
    return out


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    for c in ("backup", "status", "restore"):
        p = sp.add_parser(c)
        p.add_argument("--commons", required=True)
        if c == "backup":
            p.add_argument("--to", default=None, help="the backup folder (saved for next time)")
        if c == "restore":
            p.add_argument("--generation", default=None)
    sp.add_parser("self-test")
    a = ap.parse_args(argv)
    if a.cmd == "self-test":
        res = self_test()
        for n, g, d in res:
            print(("  [OK]   " if g else "  [FAIL] ") + n + ("" if g else "  — %s" % (d,)))
        print("\n  %d of %d checks passed" % (sum(1 for x in res if x[1]), len(res)))
        return 0 if all(x[1] for x in res) else 1
    if a.cmd == "backup":
        if a.to:
            save_config(a.commons, folder=a.to)
        print(json.dumps(backup(a.commons, log=print), indent=1))
    elif a.cmd == "status":
        print(json.dumps(status(a.commons), indent=1, default=str))
    else:
        print(json.dumps(restore(a.commons, a.generation), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
