"""The data drive: with a data-folder.txt beside the suite's launchers, EVERY QueryBook program keeps ALL its data there
(D:\\QB\\language, \\stem, \\facts, \\control, \\video and the shared facts in D:\\QB\\commons) — never on C:.

On every start the data from the old place (C:\\Users\\<you>\\QueryBook-Data\\..., and any shared folder chosen earlier
with "Move the shared folder") is brought over by itself:

  * a file the data drive does not have yet is copied there;
  * a database both places have: the one holding MORE facts wins. The data drive's own copy is never deleted — it is
    renamed "<name>.set-aside-<date>" next to it;
  * the old place is never changed or deleted.

Databases are copied whole with their write-ahead log and folded together on the data drive, then checked before they are
put in place, so a copy is never half a database. One program does this at a time (a lock folder on the data drive);
the others wait. Everything done is written to <data drive>\\data-moved.log.
"""
import json, os, shutil, sqlite3, sys, time

LOCK = ".qb-moving"
APPS = ("language", "stem", "facts", "control", "video")
STALE_LOCK_S = 12 * 3600


class DriveMissing(SystemExit):
    pass


def root_for(program_dir):
    """the folder named in data-folder.txt beside the launchers (the parent of the program's folder), or None"""
    p = os.path.join(os.path.dirname(os.path.abspath(program_dir)), "data-folder.txt")
    try:
        with open(p, encoding="utf-8-sig") as f:
            lines = [l.strip().strip('"') for l in f.read().splitlines() if l.strip()]
    except OSError:
        return None
    return os.path.abspath(os.path.expanduser(lines[0])) if lines else None


def require(root):
    if not os.path.isdir(root):
        raise DriveMissing("\n  The QueryBook data folder %s cannot be found.\n  If it is on an external drive, connect the drive and "
                           "start again.\n  Nothing was started, so no data is written anywhere else.\n" % root)
    return root


def commons_in(root):
    return root if os.path.exists(os.path.join(root, "commons.sqlite")) else os.path.join(root, "commons")


# ------------------------------------------------------------------------------------------------ where the old data is
def old_places(home=None, program_dirs=()):
    """[(kind, folder)] — kind is an application id or "commons" — wherever earlier versions kept data"""
    base = os.path.join(home or os.path.expanduser("~"), "QueryBook-Data")
    out = []
    for a in APPS:
        out.append((a, os.path.join(base, a)))
    commons = [os.path.join(base, "commons")]
    for a in APPS:                                          # a shared folder chosen with "Move the shared folder"
        try:
            with open(os.path.join(base, a, "commons.json"), encoding="utf-8") as f:
                p = json.load(f).get("folder")
            if p:
                commons.append(os.path.abspath(os.path.expanduser(p)))
        except (OSError, ValueError, AttributeError):
            pass
    for d in program_dirs:                                  # python app.py set-data FOLDER
        try:
            with open(os.path.join(d, "config.json"), encoding="utf-8") as f:
                p = json.load(f).get("data_folder")
            a = os.path.basename(d.rstrip("\\/"))
            kind = {"QueryBook-Language": "language", "QueryBook-STEM": "stem", "QueryBook-History-News": "facts",
                    "QueryBook-Control-Panel": "control", "QueryBook-Video-Studio": "video"}.get(a, a)
            if p and kind in APPS:
                out.append((kind, os.path.abspath(os.path.expanduser(p))))
        except (OSError, ValueError, AttributeError):
            pass
    seen = set()
    for c in commons:
        if os.path.normcase(c) not in seen:
            seen.add(os.path.normcase(c))
            out.append(("commons", c))
    return out


# ------------------------------------------------------------------------------------------------ comparing databases
def _facts(path):
    """facts a database holds: a bulk shard's own total, else the rows of its facts table, else None"""
    try:
        db = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/").replace("?", "%3f").replace("#", "%23"), uri=True, timeout=20)
    except sqlite3.Error:
        return None
    try:
        try:
            r = db.execute("SELECT value FROM meta WHERE key = 'facts'").fetchone()
            if r is not None:
                return int(json.loads(r[0]) or 0)
        except (sqlite3.Error, ValueError, TypeError):
            pass
        try:
            return int(db.execute("SELECT max(rowid) FROM facts").fetchone()[0] or 0)
        except sqlite3.Error:
            return None
    finally:
        db.close()


def _size(path):
    return sum(os.path.getsize(path + x) for x in ("", "-wal") if os.path.exists(path + x))


def _copy_file(src, dst, say, label=None):
    """copy in 8 MB pieces, telling how far it is every few seconds (a large store takes a while on a USB drive)"""
    total, done, t0, last = os.path.getsize(src), 0, time.time(), 0.0
    with open(src, "rb") as a, open(dst, "wb") as b:
        while True:
            buf = a.read(8 << 20)
            if not buf:
                break
            b.write(buf)
            done += len(buf)
            now = time.time()
            if total > (256 << 20) and now - last > 5:
                last = now
                rate = done / max(0.001, now - t0)
                msg = "copying %s: %.1f of %.1f GB, %.0f MB/s, about %d min left" % (label or os.path.basename(src), done / 1e9, total / 1e9,
                                                                                   rate / 1e6, max(0, (total - done) / max(rate, 1)) // 60)
                say("  " + msg)
                _progress(msg)
        b.flush()
        os.fsync(b.fileno())


_PROGRESS = [None]


def _progress(msg):
    """what the program holding the lock is doing, for the others waiting for it"""
    if _PROGRESS[0]:
        try:
            with open(_PROGRESS[0], "w", encoding="utf-8") as f:
                json.dump({"at": time.time(), "pid": os.getpid(), "doing": msg}, f)
        except OSError:
            pass


def _copy_db(src, dst, say=lambda *a: None):
    """the database and its write-ahead log, folded together on the destination and checked, then put in place"""
    tmp = dst + ".copying"
    for x in ("", "-wal", "-shm"):
        if os.path.exists(tmp + x):
            os.remove(tmp + x)
    _copy_file(src, tmp, say, os.path.basename(src))
    if os.path.exists(src + "-wal"):
        shutil.copyfile(src + "-wal", tmp + "-wal")
    db = sqlite3.connect(tmp, timeout=60)
    try:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        ok = db.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        db.close()
    if ok != "ok":
        raise RuntimeError("the copy of %s failed its check (%s); the old copy is untouched" % (src, ok))
    for x in ("-wal", "-shm"):
        if os.path.exists(tmp + x):
            os.remove(tmp + x)
    os.replace(tmp, dst)


def _set_aside(dst, stamp):
    """rename the data drive's own copy out of the way. Raises PermissionError when a program has it open (Windows)."""
    to = "%s.set-aside-%s" % (dst, stamp)
    os.replace(dst, to)                                # first: fails (and changes nothing) while the file is in use
    for x in ("-wal", "-shm"):
        if os.path.exists(dst + x):
            try:
                os.replace(dst + x, to + x)
            except OSError:
                pass
    return to


def _busy(folder):
    """a bulk runner still writing in the old shared folder (heartbeat in the last minute)"""
    try:
        with open(os.path.join(folder, "shards", "_runner.json")) as f:
            rs = json.load(f)
        return time.time() - rs.get("heartbeat", 0) < 60 and rs.get("note") != "finished"
    except (OSError, ValueError):
        return False


def _stamp_of(path):
    st = os.stat(path)
    w = path + "-wal"
    return [st.st_size + (os.path.getsize(w) if os.path.exists(w) else 0), int(st.st_mtime)]


def merge(src, dst, log, stamp, done=None, say=lambda *a: None):
    """everything in src that dst lacks, and every fact database where src holds MORE FACTS (counted, never guessed from the
    file size). A source already handled and unchanged since (`done`, the manifest) is skipped. Live data first, backups last.
    Returns (files copied, databases replaced)."""
    copied = replaced = 0
    done = {} if done is None else done
    todo = []
    for d, dirs, files in os.walk(src):
        dirs[:] = [x for x in dirs if not x.startswith(".") and x != "__pycache__"]
        for f in sorted(files):
            if f.endswith(("-wal", "-shm", ".copying", ".progress")) or ".set-aside-" in f or f.startswith("_runner") or f.startswith(".qb-"):
                continue
            rel = os.path.relpath(os.path.join(d, f), src)
            todo.append((("backups" in rel.replace("\\", "/").split("/")), rel))
    for _, rel in sorted(todo):
        s, t = os.path.join(src, rel), os.path.normpath(os.path.join(dst, rel))
        try:
            mark = _stamp_of(s)
            if done.get(s) == mark:
                continue                                    # handled before and not changed since
            os.makedirs(os.path.dirname(t), exist_ok=True)
            if rel.endswith(".sqlite"):
                if not os.path.exists(t):
                    log("copy  %s  (%s facts)" % (s, _facts(s)))
                    _copy_db(s, t, say)
                    copied += 1
                else:
                    a, b = _facts(s), _facts(t)
                    if a is not None and b is not None and a > b:
                        try:
                            aside = _set_aside(t, stamp)
                        except PermissionError:
                            log("in use: %s is open in a running program, so the bigger old copy (%s facts against %s) waits — "
                                "it is brought over on the next START-ALL" % (t, a, b))
                            continue                        # not marked done: tried again next time
                        log("newer %s holds more facts (%s against %s): it replaces the data drive's copy, kept as %s" % (s, a, b, aside))
                        _copy_db(s, t, say)
                        replaced += 1
            elif not os.path.exists(t):
                shutil.copy2(s, t)
                copied += 1
            done[s] = mark
        except Exception as e:                      # one file never stops the rest; it is tried again on the next start
            log("could not copy %s yet (%s: %s) — tried again on the next start" % (s, type(e).__name__, e))
    return copied, replaced


class _FileLock:
    """one program at a time brings data over; the system releases the lock of a program that was closed or crashed"""

    def __init__(self, path):
        self.path, self.f = path, None

    def try_lock(self):
        f = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.f = f
            return True
        except OSError:
            f.close()
            return False

    def release(self):
        if self.f:
            try:
                if os.name == "nt":
                    import msvcrt
                    self.f.seek(0)
                    msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            self.f.close()
            self.f = None


def bring_over(root, program_dir=None, home=None, say=print, only=None):
    """bring the old data onto the data drive (see the module text). Safe to run on every start: what was brought over
    and has not changed since is not looked at again. only: the kinds to handle (a program's own folder at its start;
    everything — the shared facts too — from START-ALL)."""
    require(root)
    try:                                            # the folder lock of 1.17–1.20 could outlive a closed window
        legacy = os.path.join(root, LOCK)
        if os.path.isdir(legacy):
            os.rmdir(legacy)
    except OSError:
        pass
    lock = _FileLock(os.path.join(root, LOCK + ".lock"))
    prog = os.path.join(root, LOCK + ".json")
    t_wait = told = 0.0
    while not lock.try_lock():
        now = time.time()
        if not t_wait:
            t_wait = now
        if now - told > 15:
            told = now
            try:
                with open(prog, encoding="utf-8") as f:
                    doing = json.load(f).get("doing")
            except (OSError, ValueError):
                doing = None
            say("  Another QueryBook window is bringing data onto %s%s — this one starts when it is done." % (root, (": " + doing) if doing else ""))
        time.sleep(2)
    _PROGRESS[0] = prog
    stamp = time.strftime("%Y%m%d-%H%M%S")
    lines = []
    man_path = os.path.join(root, ".qb-moved.json")
    try:
        with open(man_path, encoding="utf-8") as f:
            done = json.load(f)
    except (OSError, ValueError):
        done = {}

    def log(msg):
        lines.append(msg)
        say("  " + msg)
    try:
        progs = []
        if program_dir:
            suite = os.path.dirname(os.path.abspath(program_dir))
            progs = [os.path.join(suite, d) for d in os.listdir(suite) if os.path.isdir(os.path.join(suite, d))]
        total = [0, 0]
        for kind, src in old_places(home, progs):
            if only and kind not in only:
                continue
            dst = commons_in(root) if kind == "commons" else os.path.join(root, kind)
            if not os.path.isdir(src) or os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dst)):
                continue
            if os.path.normcase(os.path.abspath(dst)).startswith(os.path.normcase(os.path.abspath(src)) + os.sep):
                continue
            if kind == "commons" and _busy(src):
                log("the old shared folder %s is still being written by bulk agents of an older version: close every QueryBook "
                    "window (and its agents) — it is brought over on the next start" % src)
                continue
            _progress("bringing over %s" % src)
            c, r = merge(src, dst, log, stamp, done, say)
            total[0] += c
            total[1] += r
            try:
                tmp = man_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(done, f)
                os.replace(tmp, man_path)
            except OSError:
                pass
        if lines:
            with open(os.path.join(root, "data-moved.log"), "a", encoding="utf-8") as f:
                f.write("\n%s\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), "\n".join(lines)))
        return {"copied": total[0], "replaced": total[1], "log": lines}
    finally:
        _PROGRESS[0] = None
        try:
            os.remove(prog)
        except OSError:
            pass
        lock.release()


def self_test():
    import tempfile
    res = []
    ok = lambda n, c, d="": res.append((n, bool(c), d))

    def shard(path, facts, wal_rows=0):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        db = sqlite3.connect(path)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS facts (fp BLOB PRIMARY KEY, s TEXT)")
        db.executemany("INSERT INTO facts(s) VALUES(?)", [("f%d" % i,) for i in range(facts)])
        db.execute("INSERT OR REPLACE INTO meta VALUES('facts', ?)", (json.dumps(facts),))
        db.commit()
        return db                                         # left open: its write-ahead log stays beside it, as in a crash
    with tempfile.TemporaryDirectory() as tmp:
        home, root = os.path.join(tmp, "home"), os.path.join(tmp, "D", "QB")
        old = os.path.join(home, "QueryBook-Data")
        keep = [shard(os.path.join(old, "commons", "shards", "wikidata-1.sqlite"), 5000),
                shard(os.path.join(old, "commons", "shards", "pubchem.sqlite"), 300),
                shard(os.path.join(old, "commons", "commons.sqlite"), 40)]
        os.makedirs(os.path.join(old, "facts"))
        keep.append(shard(os.path.join(old, "facts", "facts.sqlite"), 77))
        open(os.path.join(old, "facts", "notes.txt"), "w").write("mine")
        os.makedirs(root)
        keep += [shard(os.path.join(root, "commons", "shards", "wikidata-1.sqlite"), 12),     # fresh, smaller: replaced
                 shard(os.path.join(root, "commons", "shards", "pubchem.sqlite"), 900)]      # newer, bigger: kept
        for db in keep[-2:]:
            db.close()
        before = sorted(os.listdir(os.path.join(old, "commons", "shards")))
        r = bring_over(root, home=home, say=lambda *a: None)
        cs = os.path.join(root, "commons", "shards")
        ok("the old shared facts come onto the data drive: a bigger old database replaces a fresh one",
           _facts(os.path.join(cs, "wikidata-1.sqlite")) == 5000 and r["replaced"] == 1, r)
        ok("the data drive's own copy is kept, renamed, never deleted", any(".set-aside-" in f and f.startswith("wikidata-1") for f in os.listdir(cs)))
        ok("a database the data drive holds more of is left alone", _facts(os.path.join(cs, "pubchem.sqlite")) == 900)
        ok("databases are copied with their write-ahead log folded in, and are whole",
           _facts(os.path.join(root, "commons", "commons.sqlite")) == 40 and not os.path.exists(os.path.join(root, "commons", "commons.sqlite.copying")),
           _facts(os.path.join(root, "commons", "commons.sqlite")))
        ok("each program's own data comes over too", _facts(os.path.join(root, "facts", "facts.sqlite")) == 77
           and open(os.path.join(root, "facts", "notes.txt")).read() == "mine")
        ok("the old place is never changed", sorted(os.listdir(os.path.join(old, "commons", "shards"))) == before
           and _facts(os.path.join(old, "commons", "shards", "wikidata-1.sqlite")) == 5000)
        r2 = bring_over(root, home=home, say=lambda *a: None)
        ok("running again changes nothing (safe on every start)", r2["copied"] == 0 and r2["replaced"] == 0, r2)
        ok("a record of what was brought over", "wikidata-1" in open(os.path.join(root, "data-moved.log"), encoding="utf-8").read())
        ok("no lock left behind", not os.path.exists(os.path.join(root, LOCK)))
        # 1.21: what stalled every program on 1 Nov 2026
        os.makedirs(os.path.join(old, "control")); os.makedirs(os.path.join(root, "control"))
        for p_, n in ((os.path.join(old, "control", "control.sqlite"), 3000), (os.path.join(root, "control", "control.sqlite"), 10)):
            db = sqlite3.connect(p_); db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            db.executemany("INSERT INTO meta VALUES (?, ?)", [("k%d" % i, "x" * 50) for i in range(n)]); db.commit(); db.close()
        r3 = bring_over(root, home=home, say=lambda *a: None)
        ok("a program's own database (no fact count) on both drives is never replaced because the old file is bigger",
           r3["replaced"] == 0 and not any(".set-aside-" in f for f in os.listdir(os.path.join(root, "control"))), r3)
        os.makedirs(os.path.join(root, LOCK))                    # the folder lock a closed 1.20 window left behind
        r4 = bring_over(root, home=home, say=lambda *a: None)
        ok("a lock left by a closed window never blocks the start", r4 is not None and not os.path.isdir(os.path.join(root, LOCK)))
        import threading
        held = _FileLock(os.path.join(root, LOCK + ".lock")); held.try_lock()
        with open(os.path.join(root, LOCK + ".json"), "w") as f:
            json.dump({"doing": "copying wikidata-1.sqlite: 1.0 of 9.0 GB"}, f)
        said = []
        threading.Timer(1.5, held.release).start()
        t0 = time.time()
        bring_over(root, home=home, say=said.append)
        ok("while another window brings data over, the waiting window says what it is doing, then starts",
           time.time() - t0 >= 1.4 and any("wikidata-1" in x for x in said), said)
        os.makedirs(os.path.join(old, "stem")); open(os.path.join(old, "stem", "a.txt"), "w").write("s")
        r5 = bring_over(root, home=home, say=lambda *a: None, only=["facts"])
        ok("a program at its start brings over only its own folder", r5["copied"] == 0 and not os.path.exists(os.path.join(root, "stem", "a.txt")), r5)
        for db in keep[:-2]:
            db.close()
        suite = os.path.join(tmp, "suite")
        os.makedirs(os.path.join(suite, "QueryBook-STEM"))
        open(os.path.join(suite, "data-folder.txt"), "w").write("%s\r\n" % root)
        ok("data-folder.txt beside the launchers names the data drive", root_for(os.path.join(suite, "QueryBook-STEM")) == root)
        try:
            require(os.path.join(tmp, "E", "missing"))
            ok("a missing data drive stops the program (nothing written elsewhere)", False)
        except SystemExit:
            ok("a missing data drive stops the program (nothing written elsewhere)", True)
    return res


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "self-test":
        r = self_test()
        for n, g, d in r:
            print("  [%s] %s%s" % ("OK" if g else "FAIL", n, "" if g else " — %s" % (d,)))
        print("  %d of %d checks passed" % (sum(1 for _, g, _ in r if g), len(r)))
        sys.exit(0 if all(g for _, g, _ in r) else 1)
    if len(sys.argv) > 1:                       # START-ALL: python qbdrive.py D:\QB  — everything, before the programs start
        root = os.path.abspath(sys.argv[1])
        print("  Checking for QueryBook data still on this computer's own drive to bring onto %s ..." % root)
        try:
            r = bring_over(root, os.path.dirname(os.path.abspath(__file__)), say=print)
        except SystemExit as e:
            print(e)
            sys.exit(1)
        print("  Data on %s is ready: %d file(s) brought over now, %d database(s) replaced by a bigger old copy." % (root, r["copied"], r["replaced"]))
