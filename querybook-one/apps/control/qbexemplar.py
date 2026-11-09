"""qbexemplar — the exemplar library: best-in-class examples QueryBook learns from, never reasons with.

An exemplar is a learning object — a video, a sound, an image or a drill text — that QueryBook keeps, measures with its own
deterministic tools and learns from. Where it came from is recorded (the generator or recording, the script it was asked
to perform, the date, the request), and so is everything QueryBook measured in it. It is never a Fact Unit and is never
cited as evidence about the world.

  * Takes.     Each line of a script (an "item", e.g. P07 of Pamela's speech script) may have several takes.
  * Scores.    QueryBook's own measurements of a take (words heard, face kept, mouth in view, shape ranges), each a number,
               plus pass/fail checks with their reasons. Nothing scores itself: the generator is never asked.
  * Selection. Best-in-class = the passing take with the highest overall score (ties: the earlier take). The library
               proposes it; the admin approves it (admin passphrase). The approved take becomes the item's exemplar,
               the other takes are kept as "also ran" with their scores, a replaced exemplar is "retired" — never deleted.
  * Frozen.    Files are stored by their SHA-256, so the same file always has the same id and the same scores, and a
               changed file is caught (verify()).

The library lives in the shared folder (~/QueryBook-Data/commons/exemplars), so all the applications see one library.
Standard library only. No AI model: generating takes is the admin's separate tool (tools/generate_exemplars.py), which
runs outside the agents and the applications.
"""
import hashlib, json, os, re, shutil, tempfile, threading, time

VERSION = "1.0.0"
KINDS = {"video": (".mp4", ".webm", ".mov"), "audio": (".wav", ".mp3", ".ogg", ".m4a"), "image": (".jpg", ".jpeg", ".png", ".webp"),
         "text": (".txt", ".json", ".md")}
CTYPE = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".wav": "audio/wav", ".mp3": "audio/mpeg",
         ".ogg": "audio/ogg", ".m4a": "audio/mp4", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
         ".webp": "image/webp", ".txt": "text/plain; charset=utf-8", ".json": "application/json", ".md": "text/plain; charset=utf-8"}
STATUSES = ("candidate", "exemplar", "also_ran", "rejected", "retired")
SECRET = re.compile(r"(AIza[0-9A-Za-z_\-]{20,}|AQ\.[0-9A-Za-z_\-]{20,}|sk-[0-9A-Za-z_\-]{16,}|ghp_[0-9A-Za-z]{20,}|-----BEGIN [A-Z ]+KEY-----)")
SAFE = re.compile(r"[^A-Za-z0-9_.\-]+")                # (no ":" — folder names must work on Windows too)


class LibraryError(ValueError):
    pass


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _clean(s, n=4000):
    return SECRET.sub("[withheld]", str(s or ""))[:n]


def _slug(s):
    s = SAFE.sub("-", str(s or "").strip()).strip("-.")
    if not s:
        raise LibraryError("A name is required.")
    return s[:80]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def kind_of(name):
    ext = os.path.splitext(name)[1].lower()
    for k, exts in KINDS.items():
        if ext in exts:
            return k
    raise LibraryError("Not a supported exemplar file: %s" % (ext or name))


def default_folder(app_folder=None):
    try:
        from qbcommons import commons_folder
        base = commons_folder(app_folder)
    except Exception:
        base = os.path.join(os.path.expanduser("~"), "QueryBook-Data", "commons")
    return os.path.join(base, "exemplars")


def overall(scores):
    """the take's overall score: its own "overall" if measured, else the mean of its 0-1 scores (deterministic)"""
    if not scores:
        return None
    if isinstance(scores.get("overall"), (int, float)):
        return float(scores["overall"])
    v = [float(x) for x in scores.values() if isinstance(x, (int, float)) and 0 <= x <= 1]
    return round(sum(v) / len(v), 4) if v else None


class Library:
    def __init__(self, folder=None, app_folder=None):
        self.folder = os.path.abspath(folder or default_folder(app_folder))
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ storage
    def _dir(self, skill, item):
        return os.path.join(self.folder, _slug(skill), _slug(item))

    def _manifests(self):
        if not os.path.isdir(self.folder):
            return
        for skill in sorted(os.listdir(self.folder)):
            sd = os.path.join(self.folder, skill)
            if not os.path.isdir(sd):
                continue
            for item in sorted(os.listdir(sd)):
                idir = os.path.join(sd, item)
                if not os.path.isdir(idir):
                    continue
                for f in sorted(os.listdir(idir)):
                    if f.endswith(".exemplar.json"):
                        yield os.path.join(idir, f)

    def _load(self, path):
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        m["_manifest"] = path
        return m

    def _save(self, m):
        path = m.pop("_manifest")
        d = os.path.dirname(path)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=1, sort_keys=True, ensure_ascii=False)
        os.replace(tmp, path)
        m["_manifest"] = path
        return m

    def _find(self, eid):
        eid = str(eid or "")
        for p in self._manifests():
            if os.path.basename(p) == eid + ".exemplar.json":
                return self._load(p)
        raise LibraryError("No such exemplar: %s" % eid)

    # ------------------------------------------------------------------ adding takes
    def add(self, src, skill, item, script="", origin=None, subject=None, consent=None, notes=""):
        """Add one take (a file path). Returns its manifest. The same file added twice is the same take."""
        if not os.path.isfile(src):
            raise LibraryError("No such file: %s" % src)
        kind = kind_of(src)
        ext = os.path.splitext(src)[1].lower()
        digest = sha256_file(src)
        eid = digest[:16]
        d = self._dir(skill, item)
        with self._lock:
            os.makedirs(d, exist_ok=True)
            mpath = os.path.join(d, eid + ".exemplar.json")
            if os.path.exists(mpath):
                return self._public(self._load(mpath))
            dst = os.path.join(d, eid + ext)
            if not os.path.exists(dst):
                shutil.copyfile(src, dst + ".part")
                os.replace(dst + ".part", dst)
            o = dict(origin or {})
            for k in list(o):
                o[k] = _clean(o[k]) if isinstance(o[k], str) else o[k]
            if o.get("prompt"):
                o["prompt_sha256"] = hashlib.sha256(o["prompt"].encode("utf-8")).hexdigest()
            gen = o.get("model") or o.get("generator") or o.get("source") or "unknown source"
            m = {"id": eid, "sha256": digest, "bytes": os.path.getsize(dst), "file": os.path.basename(dst), "kind": kind,
                 "skill": _slug(skill), "item": _slug(item), "script": _clean(script, 2000), "subject": _clean(subject, 200) or None,
                 "consent": _clean(consent, 400) or None, "origin": o, "notes": _clean(notes, 1000),
                 "label": "learning object — %s" % ("generated by " + gen if o.get("model") else "from " + gen),
                 "added": _now(), "status": "candidate", "scores": {}, "checks": [], "overall": None, "history": [],
                 "_manifest": mpath}
            m["history"].append({"at": m["added"], "event": "added"})
            return self._public(self._save(m))

    # ------------------------------------------------------------------ measuring
    def advise(self, eid, notes, by):
        """an outside opinion of a take (e.g. a second transcript): kept beside the scores, never part of them or of the choice"""
        with self._lock:
            m = self._find(eid)
            m.setdefault("advisory", {}).update({str(k)[:60]: (round(float(v), 4) if isinstance(v, (int, float)) else _clean(v, 400))
                                                 for k, v in (notes or {}).items()})
            m["history"].append({"at": _now(), "event": "advisory note", "by": _clean(by, 100)})
            return self._public(self._save(m))

    def score(self, eid, scores, checks=(), by="QueryBook measurement"):
        """Record QueryBook's own measurements of a take. checks: [{"name", "ok", "detail"}]."""
        with self._lock:
            m = self._find(eid)
            m["scores"].update({str(k)[:60]: (round(float(v), 4) if isinstance(v, (int, float)) else _clean(v, 200))
                                for k, v in (scores or {}).items()})
            if checks:
                byname = {c["name"]: c for c in m["checks"]}
                for c in checks:
                    byname[str(c["name"])[:60]] = {"name": str(c["name"])[:60], "ok": bool(c.get("ok")), "detail": _clean(c.get("detail"), 300)}
                m["checks"] = [byname[k] for k in sorted(byname)]
            m["overall"] = overall(m["scores"])
            m["history"].append({"at": _now(), "event": "scored", "by": _clean(by, 100), "overall": m["overall"]})
            if m["status"] == "candidate" and any(not c["ok"] for c in m["checks"]):
                m["history"].append({"at": _now(), "event": "fails a check", "checks": [c["name"] for c in m["checks"] if not c["ok"]]})
            return self._public(self._save(m))

    @staticmethod
    def passes(m):
        return m["overall"] is not None and all(c["ok"] for c in m["checks"])

    # ------------------------------------------------------------------ best in class
    def takes(self, skill, item):
        return [self._public(self._load(p)) for p in self._manifests()
                if os.path.basename(os.path.dirname(p)) == _slug(item) and os.path.basename(os.path.dirname(os.path.dirname(p))) == _slug(skill)]

    def best(self, skill, item):
        """the best-in-class proposal for one item: the passing take with the highest overall score (ties: earlier take)"""
        ts = [t for t in self.takes(skill, item) if t["status"] in ("candidate", "exemplar", "also_ran") and self.passes(t)]
        if not ts:
            return None
        return sorted(ts, key=lambda t: (-t["overall"], t["added"], t["id"]))[0]

    def proposals(self, skill=None):
        """items whose best passing take is not yet their exemplar — what the admin is asked to approve"""
        out = []
        for (sk, it) in sorted({(m["skill"], m["item"]) for m in self.list(skill=skill)}):
            b = self.best(sk, it)
            if b and b["status"] != "exemplar":
                cur = next((t for t in self.takes(sk, it) if t["status"] == "exemplar"), None)
                out.append({"skill": sk, "item": it, "proposed": b["id"], "overall": b["overall"],
                            "current": cur and cur["id"], "current_overall": cur and cur["overall"]})
        return out

    def approve(self, eid, require_admin, note=""):
        """make a take its item's exemplar (admin only): the others become also-ran, a replaced exemplar is retired"""
        require_admin()
        with self._lock:
            m = self._find(eid)
            if not self.passes(m):
                raise LibraryError("This take has not passed every check, so it cannot be the exemplar.")
            for p in self._manifests():
                o = self._load(p)
                if o["skill"] != m["skill"] or o["item"] != m["item"] or o["id"] == m["id"]:
                    continue
                new = "retired" if o["status"] == "exemplar" else "also_ran" if o["status"] == "candidate" else o["status"]
                if new != o["status"]:
                    o["status"] = new
                    o["history"].append({"at": _now(), "event": new, "because": "take %s approved" % m["id"]})
                    self._save(o)
            m["status"] = "exemplar"
            m["history"].append({"at": _now(), "event": "approved", "by": "admin", "note": _clean(note, 300)})
            return self._public(self._save(m))

    def reject(self, eid, require_admin, reason=""):
        require_admin()
        with self._lock:
            m = self._find(eid)
            m["status"] = "rejected"
            m["history"].append({"at": _now(), "event": "rejected", "by": "admin", "reason": _clean(reason, 300)})
            return self._public(self._save(m))

    # ------------------------------------------------------------------ reading
    @staticmethod
    def _public(m):
        return {k: v for k, v in m.items() if not k.startswith("_")}

    def get(self, eid):
        return self._public(self._find(eid))

    def path(self, eid):
        m = self._find(eid)
        return os.path.join(os.path.dirname(m["_manifest"]), m["file"])

    def list(self, skill=None, item=None, status=None):
        out = []
        for p in self._manifests():
            m = self._load(p)
            if (skill and m["skill"] != _slug(skill)) or (item and m["item"] != _slug(item)) or (status and m["status"] != status):
                continue
            out.append(self._public(m))
        return out

    def exemplars(self, skill):
        """the approved exemplar of every item of a skill, by item"""
        return {m["item"]: m for m in self.list(skill=skill, status="exemplar")}

    def summary(self):
        ms = self.list()
        by = {}
        for m in ms:
            s = by.setdefault(m["skill"], {"items": set(), "takes": 0, **{k: 0 for k in STATUSES}, "origins": {}})
            s["items"].add(m["item"]); s["takes"] += 1; s[m["status"]] += 1
            g = m["origin"].get("model") or m["origin"].get("source") or "unknown"
            s["origins"][g] = s["origins"].get(g, 0) + 1
        for s in by.values():
            s["items"] = len(s["items"])
        return {"folder": self.folder, "version": VERSION, "takes": len(ms), "skills": by,
                "proposals": len(self.proposals()), "rule": "exemplars are learning objects: measured by QueryBook, approved by the admin, never facts"}

    def verify(self):
        """re-hash every stored file: a file changed since it was added is reported (its scores no longer apply)"""
        bad = []
        for p in self._manifests():
            m = self._load(p)
            f = os.path.join(os.path.dirname(p), m["file"])
            if not os.path.exists(f):
                bad.append({"id": m["id"], "problem": "file missing"})
            elif sha256_file(f) != m["sha256"]:
                bad.append({"id": m["id"], "problem": "file changed since it was added"})
        return {"checked": sum(1 for _ in self._manifests()), "problems": bad}


# ---------------------------------------------------------------------------------------------- web routes
def add_routes(api, lib, require_admin):
    g, p = api.get, api.post

    def _file(q):
        path = lib.path(q.get("id"))
        with open(path, "rb") as f:
            return (f.read(), CTYPE.get(os.path.splitext(path)[1].lower(), "application/octet-stream"))
    g("/api/exemplars")(lambda q: {"summary": lib.summary(), "takes": lib.list(q.get("skill"), q.get("item"), q.get("status"))})
    g("/api/exemplars/get")(lambda q: lib.get(q.get("id")))
    g("/api/exemplars/file")(_file)
    g("/api/exemplars/proposals")(lambda q: {"proposals": lib.proposals(q.get("skill"))})
    g("/api/exemplars/verify")(lambda q: lib.verify())
    p("/api/exemplars/score")(lambda q: lib.score(q.get("id"), q.get("scores") or {}, q.get("checks") or (), q.get("by") or "QueryBook measurement"))
    p("/api/exemplars/approve")(lambda q: lib.approve(q.get("id"), lambda: require_admin(q.get("passphrase")), q.get("note") or ""))
    p("/api/exemplars/reject")(lambda q: lib.reject(q.get("id"), lambda: require_admin(q.get("passphrase")), q.get("reason") or ""))


def attach(app):
    """Give an application the shared exemplar library. Never stops the application if it cannot be opened."""
    try:
        appr = getattr(getattr(app, "commons", None), "approvals", None)

        def require_admin(passphrase):
            if appr is None:
                raise LibraryError("The admin approvals are not available, so nothing can be approved here.")
            appr._require(passphrase or "")
        cf = getattr(getattr(app, "commons", None), "folder", None)
        app.exemplars = Library(os.path.join(cf, "exemplars") if cf else None, app_folder=getattr(app, "folder", None))
        add_routes(app.api, app.exemplars, require_admin)
    except Exception as e:
        log = getattr(app, "log", None)
        if log:
            log("exemplar library unavailable:", repr(e))
        app.exemplars = None
    return app.exemplars


# ---------------------------------------------------------------------------------------------- self-test
def self_test():
    out = []
    ok = lambda name, cond: out.append((name, bool(cond)))
    d = tempfile.mkdtemp(prefix="qbexemplar-")
    try:
        lib = Library(os.path.join(d, "lib"))
        srcs = []
        for i, body in enumerate([b"take one", b"take two", b"take three"]):
            f = os.path.join(d, "t%d.mp4" % i)
            open(f, "wb").write(body); srcs.append(f)
        a = lib.add(srcs[0], "speech-video-test", "P01", "see me", {"model": "test-generator", "prompt": "say it key AIza" + "x" * 30})
        ok("adds a take with its origin and label", a["label"] == "learning object — generated by test-generator" and a["status"] == "candidate")
        ok("never stores a key", "AIza" not in json.dumps(a) and "[withheld]" in a["origin"]["prompt"])
        ok("the same file is the same take", lib.add(srcs[0], "speech-video-test", "P01")["id"] == a["id"] and len(lib.takes("speech-video-test", "P01")) == 1)
        b = lib.add(srcs[1], "speech-video-test", "P01", "see me", {"model": "test-generator"})
        c = lib.add(srcs[2], "speech-video-test", "P01", "see me", {"model": "other-generator"})
        lib.score(a["id"], {"words": 0.9, "face": 1.0}, [{"name": "words", "ok": True}])
        lib.score(b["id"], {"words": 1.0, "face": 1.0}, [{"name": "words", "ok": False, "detail": "skipped a word"}])
        lib.score(c["id"], {"words": 0.95, "face": 1.0}, [{"name": "words", "ok": True}])
        best = lib.best("speech-video-test", "P01")
        ok("best in class = highest passing score (a failed check never wins)", best and best["id"] == c["id"])
        try:
            lib.approve(c["id"], lambda: (_ for _ in ()).throw(LibraryError("passphrase")))
            ok("approval needs the admin", False)
        except LibraryError:
            ok("approval needs the admin", lib.get(c["id"])["status"] == "candidate")
        lib.approve(c["id"], lambda: None, "best")
        st = {t["id"]: t["status"] for t in lib.takes("speech-video-test", "P01")}
        ok("approved take is the exemplar, the others also ran", st[c["id"]] == "exemplar" and st[a["id"]] == "also_ran" and st[b["id"]] == "also_ran")
        try:
            lib.approve(b["id"], lambda: None); ok("a failing take cannot be approved", False)
        except LibraryError:
            ok("a failing take cannot be approved", True)
        lib.score(a["id"], {"overall": 0.99})
        lib.approve(a["id"], lambda: None)
        ok("a replaced exemplar is retired, not deleted", lib.get(c["id"])["status"] == "retired" and os.path.exists(lib.path(c["id"])))
        before = lib.get(a["id"])["overall"]; lib.advise(a["id"], {"second_transcript_match": 0.1}, "test")
        ok("an outside opinion never changes the score", lib.get(a["id"])["overall"] == before and lib.get(a["id"])["advisory"]["second_transcript_match"] == 0.1)
        ok("summary counts takes by skill and origin", lib.summary()["skills"]["speech-video-test"]["takes"] == 3)
        open(lib.path(b["id"]), "ab").write(b"!")
        ok("a changed file is caught", [x["id"] for x in lib.verify()["problems"]] == [b["id"]])
        try:
            lib.add(os.path.join(d, "t0.mp4"), "../../etc", "x"); ok("names cannot leave the library", os.path.isdir(os.path.join(lib.folder, "etc")))
        except LibraryError:
            ok("names cannot leave the library", True)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return out


def qc():
    r = self_test()
    for n, good in r:
        print("  [%s] %s" % ("OK" if good else "FAIL", n))
    print("  %d of %d checks passed" % (sum(g for _, g in r), len(r)))
    return all(g for _, g in r)


if __name__ == "__main__":
    import sys
    sys.exit(0 if qc() else 1)
