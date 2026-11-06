"""qbdump — download once, read locally: the weekly Wikidata dump fetched ONE time to the data drive, then every lane reads
its share from that copy at disk speed (Control Panel 1.33, bulk engine 1.31).

Why: streaming, every lane fetched its own part over the internet, and the servers allow only a few connections per
computer, so 13 of 16 lanes waited and a restarted lane read its part from the start again (about 1 million facts an
hour). Downloaded once, no lane ever waits for the internet and a restart costs seconds.

How the one download works:
  1. SOURCES — Wikimedia's own server and the official mirrors are asked for the file's size and date (HEAD). Only a
     server holding exactly the same file (same size and Last-Modified) is used; each one gets at most its own number of
     connections (Wikimedia 2, the mirrors 3 or 4), so no server's limit is ever passed.
  2. PIECES — the file is cut into 64 MiB pieces. Every connection takes the next missing piece from whichever server
     it belongs to; a server that says "slow down" (429/503) cools down and its pieces go to the others. Each piece must
     arrive whole (its exact length, at its exact offset) or it is fetched again. Done pieces are written to a state
     file as they land, so a stop, a crash or an unplugged drive resumes at the next missing piece.
  3. CHECK — the finished file is checked against the MD5 Wikimedia publishes for that dump (wikidata-YYYYMMDD-md5sums.txt).
     A file that does not match is never used: it is set aside and fetched again. Where no checksum is published, the
     exact size from every server is the check, and the report says so.
  4. READY — the file and ready.json (edition, size, date, checksum, how it was made) sit in
     <dumps folder>/wikidata/<edition>/. The lanes read the newest ready edition; the two newest editions are kept.

The dumps folder is the setting bulk:dumps:folder (default: <shared folder>/dumps) — for example the large external drive.
"""
import datetime, hashlib, json, os, queue, re, shutil, threading, time, urllib.error, urllib.parse, urllib.request

VERSION = "1.0.0"
PIECE = 64 << 20                       # 64 MiB pieces: about 2,500 for the 157 GB dump
FILE = "latest-all.json.gz"
KEEP = 2                               # ready editions kept (the one the lanes read and the one before)
COOL_S = 120                           # a server that says "slow down" rests this long (or as long as it asks)
MAX_PIECE_TRIES = 8                    # a piece failing this often in one run ends the run (it resumes on the next)
MD5_INDEX = "https://dumps.wikimedia.org/wikidatawiki/entities/"
UA = "QueryBook-dump-download/%s (+https://github.com/ghoward333777-png/projectx; one download per weekly dump)" % VERSION
REFUSED = (429, 503)


class Busy(Exception):
    """not now (a server, the drive, the disk): resumes on the next try"""


def _req(url, extra=None, method=None):
    return urllib.request.Request(url, headers=dict({"User-Agent": UA}, **(extra or {})), method=method)


def edition_of(last_modified):
    """the edition as the lanes name it (the same rule as the streaming lanes: Last-Modified as YYYY-MM-DD)"""
    try:
        return datetime.datetime.strptime(last_modified, "%a, %d %b %Y %H:%M:%S GMT").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return "latest"


def head(url, timeout=30):
    with urllib.request.urlopen(_req(url, method="HEAD"), timeout=timeout) as r:
        return int(r.headers["Content-Length"]), r.headers.get("Last-Modified") or ""


def folder_for(commons_folder, setting=None):
    """where dumps are kept: the setting bulk:dumps:folder, else <shared folder>/dumps"""
    return os.path.abspath(os.path.expanduser(setting)) if setting else os.path.join(commons_folder, "dumps")


# ------------------------------------------------------------------------------------------------ what is on the drive
def editions(dumps_folder):
    """[ready.json, …] of every ready edition, newest first"""
    base = os.path.join(dumps_folder, "wikidata")
    out = []
    if os.path.isdir(base):
        for d in os.listdir(base):
            p = os.path.join(base, d, "ready.json")
            try:
                with open(p, encoding="utf-8") as f:
                    r = json.load(f)
            except (OSError, ValueError):
                continue
            path = os.path.join(base, d, FILE)
            if os.path.isfile(path) and os.path.getsize(path) == r.get("size"):
                out.append(dict(r, path=path))
    return sorted(out, key=lambda r: r.get("edition") or "", reverse=True)


def ready(dumps_folder):
    """the newest ready edition (with its path), or None"""
    e = editions(dumps_folder)
    return e[0] if e else None


def progress(dumps_folder):
    """the download now under way, from its state file: {edition, size, pieces, done, bytes, rate_mb_s, sources, phase}"""
    base = os.path.join(dumps_folder, "wikidata")
    best = None
    if os.path.isdir(base):
        for d in os.listdir(base):
            p = os.path.join(base, d, "download.json")
            try:
                with open(p, encoding="utf-8") as f:
                    s = json.load(f)
            except (OSError, ValueError):
                continue
            if not os.path.exists(os.path.join(base, d, "ready.json")) and (best is None or s.get("edition", "") > best.get("edition", "")):
                best = s
    if not best:
        return None
    n = best.get("pieces") or 1
    done = len(best.get("done") or [])
    out = {k: best.get(k) for k in ("edition", "size", "pieces", "phase", "sources", "rate_mb_s", "started", "updated", "checked_bytes", "note")}
    out.update(done_pieces=done, share=round(done / n, 4), bytes=min(best.get("size") or 0, done * PIECE))
    left = (best.get("size") or 0) - out["bytes"]
    out["eta_s"] = round(left / (best["rate_mb_s"] * 1e6)) if best.get("rate_mb_s") else None
    return out


def discard_partials(dumps_folder):
    """remove downloads under way (no ready.json) from a folder no longer used; returns their editions"""
    base, gone = os.path.join(dumps_folder, "wikidata"), []
    if os.path.isdir(base):
        for d in os.listdir(base):
            p = os.path.join(base, d)
            if os.path.isdir(p) and not os.path.exists(os.path.join(p, "ready.json")):
                shutil.rmtree(p, ignore_errors=True)
                gone.append(d)
    return gone


def prune(dumps_folder, keep=KEEP):
    """only the newest `keep` ready editions stay (an older one is no longer read by any lane)"""
    gone = []
    for r in editions(dumps_folder)[keep:]:
        shutil.rmtree(os.path.dirname(r["path"]), ignore_errors=True)
        gone.append(r["edition"])
    return gone


# ------------------------------------------------------------------------------------------------ the published checksum
def published_md5(size, last_modified, index=MD5_INDEX, days=10):
    """the MD5 Wikimedia publishes for the dated dump of this exact size: the dump is dated by the day it STARTED, a day or
    more before its Last-Modified, so the days before are tried. (md5, dated name) or (None, why)."""
    try:
        lm = datetime.datetime.strptime(last_modified, "%a, %d %b %Y %H:%M:%S GMT")
    except (TypeError, ValueError):
        return None, "the file's date is unknown"
    for k in range(days + 1):
        d = (lm - datetime.timedelta(days=k)).strftime("%Y%m%d")
        name = "wikidata-%s-all.json.gz" % d
        try:
            s, _ = head("%s%s/%s" % (index, d, name))
        except Exception:
            continue
        if s != size:
            continue
        try:
            with urllib.request.urlopen(_req("%s%s/wikidata-%s-md5sums.txt" % (index, d, d)), timeout=60) as r:
                for line in r.read().decode("utf-8", "replace").splitlines():
                    parts = line.split()
                    if len(parts) == 2 and parts[1] == name and re.fullmatch(r"[0-9a-f]{32}", parts[0]):
                        return parts[0], name
        except Exception as e:
            return None, "the checksum list for %s could not be read (%s)" % (d, e)
        return None, "no checksum listed for %s" % name
    return None, "no dated dump of this size found in the %d days before %s" % (days, lm.strftime("%Y-%m-%d"))


def md5_file(path, meter=None, stop=None):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(8 << 20), b""):
            h.update(b)
            if meter:
                meter(len(b))
            if stop and stop():
                raise Busy("stopped while checking the file")
    return h.hexdigest()


# ------------------------------------------------------------------------------------------------ the one download
class Download:
    """fetch(): the dump into <dumps>/wikidata/<edition>/, piece by piece over every server holding it. Returns ready.json.
    meter(n): called with every byte count written or checked (the agent's progress); stop(): a reason to stop, or None."""

    def __init__(self, dumps_folder, sources, meter=None, stop=None, log=None, piece=PIECE, md5_index=MD5_INDEX, min_free_gb=10):
        self.folder, self.sources = dumps_folder, [(u, max(1, int(n))) for u, n in sources]
        self.meter, self.stop, self.log = meter or (lambda n: None), stop or (lambda: None), log or (lambda *a: None)
        self.piece, self.md5_index, self.min_free = piece, md5_index, min_free_gb * 1e9
        self.lock = threading.Lock()

    # -- which servers hold the same file
    def check_sources(self):
        ref, ok, notes = None, [], []
        for u, n in self.sources:
            try:
                size, lm = head(u)
            except urllib.error.HTTPError as e:
                notes.append("%s: HTTP %d" % (_host(u), e.code)); continue
            except Exception as e:
                notes.append("%s: %s" % (_host(u), str(e)[:80])); continue
            if ref is None:
                ref = (size, lm)
            if (size, lm) == ref:
                ok.append((u, n))
            else:
                notes.append("%s holds another edition (%s), not used" % (_host(u), lm))
        if not ok:
            raise Busy("no server holding the Wikidata dump answered (%s): resumes on the next try" % "; ".join(notes))
        return ref[0], ref[1], ok, notes

    def fetch(self):
        size, lm, sources, notes = self.check_sources()
        ed = edition_of(lm)
        d = os.path.join(self.folder, "wikidata", ed)
        os.makedirs(d, exist_ok=True)
        final, ready_p = os.path.join(d, FILE), os.path.join(d, "ready.json")
        r = ready(self.folder)
        if r and r.get("edition") == ed:
            return dict(r, already=True)
        part, state_p = final + ".part", os.path.join(d, "download.json")
        try:
            with open(state_p, encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError):
            st = {}
        n = -(-size // self.piece)
        if st.get("size") != size or st.get("last_modified") != lm or st.get("piece") != self.piece or not os.path.exists(part):
            st = {"edition": ed, "size": size, "last_modified": lm, "piece": self.piece, "pieces": n, "done": [], "started": time.time()}
        need = size - (os.path.getsize(part) if os.path.exists(part) else 0)
        free = shutil.disk_usage(d).free
        if free - need < self.min_free:
            raise Busy("the dumps folder needs %.0f GB more than it has free (%.0f GB free on %s): choose a bigger drive in the "
                       "Control Panel (Bulk harvesting → Download once → folder)" % ((need + self.min_free - free) / 1e9, free / 1e9, d))
        if not os.path.exists(part):
            with open(part, "wb") as f:
                f.truncate(size)                          # the whole file reserved at once (no fragmentation, no surprise)
        st.update(phase="downloading", sources=[{"host": _host(u), "connections": c, "bytes": 0} for u, c in sources], note="; ".join(notes))
        self._save(state_p, st)
        done = set(st["done"])
        todo = queue.Queue()
        for i in range(n):
            if i not in done:
                todo.put(i)
        tries, fail, cool = {}, [], {}
        t0, got0 = time.time(), 0
        self.log("download: %s, %d of %d pieces to fetch from %s" % (ed, todo.qsize(), n, ", ".join(_host(u) for u, _ in sources)))

        def worker(src_i):
            url = sources[src_i][0]
            host = _host(url)
            fh = open(part, "r+b")
            try:
                while not fail:
                    why = self.stop()
                    if why:
                        fail.append(Busy(why)); return
                    if cool.get(host, 0) > time.time():
                        time.sleep(1); continue
                    try:
                        i = todo.get_nowait()
                    except queue.Empty:
                        return
                    a = i * self.piece
                    b = min(size, a + self.piece) - 1
                    try:
                        with urllib.request.urlopen(_req(url, {"Range": "bytes=%d-%d" % (a, b)}), timeout=120) as resp:
                            cr = resp.headers.get("Content-Range") or ""
                            if resp.status != 206 or not cr.startswith("bytes %d-%d/" % (a, b)):
                                raise OSError("%s ignored the byte range (%s)" % (host, cr or resp.status))
                            fh.seek(a)
                            left = b - a + 1
                            while left:
                                chunk = resp.read(min(1 << 20, left))
                                if not chunk:
                                    raise OSError("%s ended the piece early" % host)
                                fh.write(chunk); left -= len(chunk)
                                self.meter(len(chunk))
                                with self.lock:
                                    st["sources"][src_i]["bytes"] += len(chunk)
                        fh.flush()
                        with self.lock:
                            done.add(i)
                            if len(done) % 4 == 0 or not todo.qsize():
                                el = max(1e-6, time.time() - t0)
                                st["done"] = sorted(done)
                                st["rate_mb_s"] = round(sum(s["bytes"] for s in st["sources"]) / el / 1e6, 2)
                                st["updated"] = time.time()
                                self._save(state_p, st)
                    except urllib.error.HTTPError as e:
                        todo.put(i)
                        if e.code in REFUSED:
                            try:
                                wait = int(e.headers.get("Retry-After") or 0)
                            except (TypeError, ValueError):
                                wait = 0
                            cool[host] = time.time() + max(COOL_S, wait)
                        else:
                            self._failed(i, tries, fail, "%s HTTP %d" % (host, e.code))
                            time.sleep(5)
                    except Exception as e:
                        todo.put(i)
                        self._failed(i, tries, fail, "%s: %s" % (host, str(e)[:120]))
                        time.sleep(5)
            finally:
                fh.close()
        threads = [threading.Thread(target=worker, args=(k,), daemon=True, name="dump-%s-%d" % (_host(u), j))
                   for k, (u, c) in enumerate(sources) for j in range(c)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        st["done"] = sorted(done)
        st["updated"] = time.time()
        self._save(state_p, st)
        if fail:
            raise fail[0] if isinstance(fail[0], Busy) else Busy(str(fail[0]))
        if len(done) < n:
            raise Busy("%d of %d pieces still missing (the servers were busy): resumes on the next try" % (n - len(done), n))
        # the check
        st["phase"] = "checking"; st["checked_bytes"] = 0
        self._save(state_p, st)
        md5_want, about = published_md5(size, lm, self.md5_index)
        self.log("download: checking %s (%s)" % (ed, "published MD5 " + md5_want if md5_want else about))
        checked = [0]

        def m(k):
            checked[0] += k
            self.meter(k)
            if checked[0] % (1 << 30) < k:
                st["checked_bytes"] = checked[0]; self._save(state_p, st)
        got = md5_file(part, m, self.stop)
        if md5_want and got != md5_want:
            os.remove(part)
            os.remove(state_p)
            raise Busy("the downloaded file does not match Wikimedia's published checksum (MD5 %s, expected %s): it was removed and "
                       "is fetched again" % (got, md5_want))
        os.replace(part, final)
        rd = {"edition": ed, "size": size, "last_modified": lm, "md5": got, "checked": "published MD5 matches (%s)" % about if md5_want
              else "size matches every server; %s" % about, "sources": st["sources"], "seconds": round(time.time() - st["started"]),
              "finished": time.time(), "version": VERSION}
        self._save(ready_p, rd)
        os.remove(state_p)
        gone = prune(self.folder)
        self.log("download: %s ready (%s)%s" % (ed, rd["checked"], "; removed older editions " + ", ".join(gone) if gone else ""))
        return dict(rd, path=final, removed=gone)

    def _failed(self, i, tries, fail, why):
        tries[i] = tries.get(i, 0) + 1
        if tries[i] >= MAX_PIECE_TRIES and not fail:
            fail.append(Busy("piece %d failed %d times (%s): the download resumes on the next try" % (i + 1, tries[i], why)))

    @staticmethod
    def _save(path, obj):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        for k in range(40):
            try:
                os.replace(tmp, path); return
            except PermissionError:                     # Windows: a reader has it open this instant
                time.sleep(0.05 * (k + 1))


def _host(url):
    return (urllib.parse.urlsplit(url).hostname or "local").lower()


# ------------------------------------------------------------------------------------------------ self-test
def self_test():
    """a stand-in server (byte ranges, a refusing mirror, another edition, a published MD5) and the whole cycle"""
    import gzip, http.server, random, tempfile
    checks = []

    def ok(name, cond, detail=""):
        checks.append((name, bool(cond), str(detail)[:200]))
    td = tempfile.mkdtemp()
    try:
        rnd = random.Random(7)
        data = b"".join(gzip.compress(("{\"id\":\"Q%d\"}\n" % i).encode() * 50, mtime=0) for i in range(400))
        data += bytes(rnd.getrandbits(8) for _ in range(5000))
        md5 = hashlib.md5(data).hexdigest()
        lm = "Mon, 02 Nov 2026 10:00:00 GMT"
        hits = {"refuse": 0}

        class H(http.server.BaseHTTPRequestHandler):
            def _body(self):
                p = self.path
                if p.startswith("/entities/20261031/wikidata-20261031-md5sums.txt"):
                    return ("%s  wikidata-20261031-all.json.gz\n" % (WANT[0])).encode(), None
                if p.startswith("/entities/20261031/wikidata-20261031-all.json.gz"):
                    return data, lm
                if p.startswith("/entities/"):
                    return None, None
                if p.startswith("/other/"):
                    return data[:-1], lm                  # another edition: not the same file
                return data, lm

            def do_HEAD(self):
                b, l = self._body()
                if b is None:
                    self.send_response(404); self.end_headers(); return
                self.send_response(200); self.send_header("Content-Length", str(len(b))); self.send_header("Last-Modified", l or lm); self.end_headers()

            def do_GET(self):
                b, l = self._body()
                if b is None:
                    self.send_response(404); self.end_headers(); return
                if self.path.startswith("/busy/") and hits["refuse"] < 3:
                    hits["refuse"] += 1
                    self.send_response(429); self.send_header("Retry-After", "1"); self.end_headers(); return
                rg = self.headers.get("Range")
                if rg:
                    a, z = (int(x) for x in rg.split("=")[1].split("-"))
                    chunk = b[a:z + 1]
                    self.send_response(206); self.send_header("Content-Range", "bytes %d-%d/%d" % (a, z, len(b)))
                else:
                    chunk = b; self.send_response(200)
                self.send_header("Content-Length", str(len(chunk))); self.end_headers(); self.wfile.write(chunk)

            def log_message(self, *a):
                pass
        WANT = [md5]
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        global COOL_S
        cool0, COOL_S = COOL_S, 1
        try:
            dumps = os.path.join(td, "dumps")
            srcs = [(base + "/main/" + FILE, 2), (base + "/busy/" + FILE, 3), (base + "/other/" + FILE, 3)]
            moved = [0]
            dl = Download(dumps, srcs, meter=lambda n: moved.__setitem__(0, moved[0] + n), piece=4096, md5_index=base + "/entities/", min_free_gb=0)
            r = dl.fetch()
            ok("downloaded once from the servers holding the same file, checked against the published MD5",
               r["md5"] == md5 and "published MD5 matches" in r["checked"] and open(r["path"], "rb").read() == data, r.get("checked"))
            ok("a server holding another edition is not used", all(s["host"] == "127.0.0.1" for s in r["sources"]) and len(r["sources"]) == 2, r["sources"])
            ok("a server that says slow down (429) rests; the others carry on", hits["refuse"] == 3)
            ok("the edition is named as the streaming lanes name it (no work is repeated)", r["edition"] == "2026-11-02" and ready(dumps)["edition"] == "2026-11-02")
            ok("asked again for the same edition: nothing is downloaded", Download(dumps, srcs, piece=4096, md5_index=base + "/entities/", min_free_gb=0).fetch().get("already"))
            # resume: a stop after a few pieces, then the rest
            dumps2 = os.path.join(td, "dumps2")
            calls = [0]

            def stop_soon():
                calls[0] += 1
                return "stopped from the Control Panel" if calls[0] > 6 else None
            try:
                Download(dumps2, srcs[:1], stop=stop_soon, piece=512, md5_index=base + "/entities/", min_free_gb=0).fetch(); stopped = False
            except Busy:
                stopped = True
            pg = progress(dumps2)
            ok("a stopped download keeps its finished pieces", stopped and pg and 0 < pg["done_pieces"] < pg["pieces"], pg)
            r2 = Download(dumps2, srcs[:1], piece=512, md5_index=base + "/entities/", min_free_gb=0).fetch()
            ok("…and resumes at the next missing piece", r2["md5"] == md5 and progress(dumps2) is None)
            # a wrong checksum: never used
            WANT[0] = "0" * 32
            dumps3 = os.path.join(td, "dumps3")
            try:
                Download(dumps3, srcs[:1], piece=4096, md5_index=base + "/entities/", min_free_gb=0).fetch(); bad = False
            except Busy as e:
                bad = "checksum" in str(e)
            ok("a file that does not match the published checksum is removed, never used", bad and ready(dumps3) is None)
            WANT[0] = md5
            # not enough room
            try:
                Download(os.path.join(td, "d4"), srcs[:1], piece=4096, md5_index=base + "/entities/", min_free_gb=10 ** 9).fetch(); room = False
            except Busy as e:
                room = "bigger drive" in str(e)
            ok("too little free space: it says how much more is needed and where to choose another drive", room)
            # two editions kept
            for ed in ("2026-10-19", "2026-10-26"):
                p = os.path.join(dumps, "wikidata", ed)
                os.makedirs(p, exist_ok=True)
                open(os.path.join(p, FILE), "wb").write(b"x")
                json.dump({"edition": ed, "size": 1}, open(os.path.join(p, "ready.json"), "w"))
            half = os.path.join(td, "old-place", "wikidata", "2026-11-09")
            os.makedirs(half)
            open(os.path.join(half, FILE + ".part"), "wb").write(b"x")
            ok("a half download left in a folder no longer used is removed (a ready copy there is kept)",
               discard_partials(os.path.join(td, "old-place")) == ["2026-11-09"] and not os.path.exists(half))
            gone = prune(dumps)
            ok("only the two newest ready editions are kept", gone == ["2026-10-19"] and [e["edition"] for e in editions(dumps)] == ["2026-11-02", "2026-10-26"], gone)
            ok("the dumps folder is the setting, else <shared>/dumps", folder_for("/x") == os.path.join("/x", "dumps") and folder_for("/x", "/big/qb").endswith("qb"))
        finally:
            COOL_S = cool0
            srv.shutdown()
    finally:
        shutil.rmtree(td, ignore_errors=True)
    return checks


if __name__ == "__main__":
    res = self_test()
    for n, g, d in res:
        print("ok  " if g else "FAIL", n, "" if g else d)
    print("%d of %d checks passed" % (sum(g for _, g, _ in res), len(res)))
