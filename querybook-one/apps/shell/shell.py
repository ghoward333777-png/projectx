"""QueryBook — one window for every application.

Double-click START-QueryBook (or run `python shell.py`). This program:

1. finds the data folder exactly as the suite's START-ALL does (data-folder.txt beside the program folders, e.g. D:\\QB;
   if the drive is not connected nothing starts), and brings data earlier versions kept on C: onto it once (qbdrive);
2. starts the Language Builder, Math/Science/Engineering, History & News, Video Studio and the Control Panel in the
   background (no extra windows), each unchanged and still able to run on its own;
3. serves ONE window (http://127.0.0.1:8090/) with every area in a side rail, a Reader/Author/Instructor/Admin switch,
   and an Ask box that answers from all of them at once;
4. stops them all when this window's program is closed.

Standard library only.
"""
from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ask
import assist
import bookq
import caps
import qbcompose
import modes

VERSION = "1.11.0"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PORT = 8090

# program id -> (display name, package folder, development folder, data env var)
PROGRAMS = {
    "control": ("Control Panel", "QueryBook-Control-Panel", "control", "QB_CONTROL_DATA"),
    "language": ("Language Builder", "QueryBook-Language", "language", "QB_LANGUAGE_DATA"),
    "stem": ("Math, Science & Engineering", "QueryBook-STEM", "stem", "QB_STEM_DATA"),
    "facts": ("History & News", "QueryBook-History-News", "facts", "QB_FACTS_DATA"),
    "video": ("Video Studio", "QueryBook-Video-Studio", "video", "QB_VIDEO_DATA"),
}


def program_dir(pid: str) -> str | None:
    _, pkg, dev, _ = PROGRAMS[pid]
    for name in (pkg, dev):
        d = os.path.join(ROOT, name)
        if os.path.isfile(os.path.join(d, "app.py")):
            return d
    return None


def data_folder() -> str | None:
    """the folder named in data-folder.txt beside the program folders (the suite's own rule), or None"""
    p = os.path.join(ROOT, "data-folder.txt")
    try:
        with open(p, encoding="utf-8-sig") as f:
            lines = [l.strip().strip('"') for l in f.read().splitlines() if l.strip() and not l.strip().startswith("#")]
    except OSError:
        return None
    return os.path.abspath(os.path.expanduser(lines[0])) if lines else None


def child_env(root: str | None) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    if root:
        env["QB_COMMONS_DATA"] = root if os.path.exists(os.path.join(root, "commons.sqlite")) else os.path.join(root, "commons")
        for pid, (_, _, dev, var) in PROGRAMS.items():
            env[var] = os.path.join(root, dev)
    return env


class WindowsJob:
    """A Windows job object: when this program ends (even if its window is closed), every application ends with it."""

    def __init__(self) -> None:
        self.handle = None
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.windll.kernel32

            class LIMIT(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

            class IOC(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                             "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

            class EXT(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", LIMIT), ("IoInfo", IOC), ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]

            k32.CreateJobObjectW.restype = wintypes.HANDLE
            job = k32.CreateJobObjectW(None, None)
            info = EXT()
            info.BasicLimitInformation.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if job and k32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info)):
                self.handle = job
                self._k32 = k32
        except Exception:
            self.handle = None

    def add(self, proc: subprocess.Popen) -> None:
        if self.handle is None:
            return
        try:
            import ctypes
            from ctypes import wintypes
            self._k32.OpenProcess.restype = wintypes.HANDLE
            h = self._k32.OpenProcess(0x0101, False, proc.pid)      # PROCESS_SET_QUOTA | PROCESS_TERMINATE
            if h:
                self._k32.AssignProcessToJobObject(wintypes.HANDLE(self.handle), wintypes.HANDLE(h))
                self._k32.CloseHandle(wintypes.HANDLE(h))
        except Exception:
            pass


class Program:
    def __init__(self, pid: str, root: str | None, job: WindowsJob) -> None:
        self.pid, self.root, self.job = pid, root, job
        self.name = PROGRAMS[pid][0]
        self.dir = program_dir(pid)
        self.url: str | None = None
        self.state = "not found" if not self.dir else "starting"
        self.lines: list[str] = []
        self.proc: subprocess.Popen | None = None
        self.started_at = 0.0

    def start(self) -> None:
        if not self.dir:
            return
        self.user_stopped = False
        self.state, self.url, self.started_at = "starting", None, time.time()
        flags = 0x08000000 if os.name == "nt" else 0                 # CREATE_NO_WINDOW: no extra black windows
        self.proc = subprocess.Popen([sys.executable, "-u", "app.py", "--no-browser"], cwd=self.dir, env=child_env(self.root),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     creationflags=flags, encoding="utf-8", errors="replace")
        self.job.add(self.proc)
        threading.Thread(target=self._read, daemon=True, name="qb-shell-" + self.pid).start()

    def _read(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.rstrip()
            self.lines = (self.lines + [line])[-80:]
            if " is running at http" in line:
                self.url = line.split(" is running at ", 1)[1].strip()
                self.state = "running"
        code = self.proc.wait()
        self.state = "stopped" if code == 0 else "stopped with an error (code %s)" % code

    def stop(self) -> None:
        self.user_stopped = True                                     # stopped on purpose: the watcher leaves it alone
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def to_json(self) -> dict:
        return {"id": self.pid, "name": self.name, "url": self.url, "state": self.state,
                "restarts": getattr(self, "restarts", 0), "last_restart": getattr(self, "last_restart", None),
                "output": self.lines[-12:] if self.state not in ("running",) else []}


class Shell:
    def __init__(self) -> None:
        self.root = data_folder()
        self.job = WindowsJob()
        self.programs = {pid: Program(pid, self.root, self.job) for pid in PROGRAMS}
        self.watches = Watches(self.root)
        self.library = Library([os.path.join(HERE, "library"), os.path.join(self.root, "library") if self.root else ""])
        # the AI Capabilities page (caps.py: the twelve capabilities; assist.py: the worker, its workflows and projects)
        self.assist = assist.Assist(self.root or HERE, lambda: qbcompose.load_keys(self.root or ""), self.urls, ask_mode, check_text)

    def prepare_drive(self) -> None:
        if not self.root:
            return
        if not os.path.isdir(self.root):
            print("\n  The QueryBook data folder %s cannot be found." % self.root)
            print("  If it is on an external drive, connect the drive and start QueryBook again.")
            print("  To use the usual folder instead, delete data-folder.txt next to START-QueryBook.\n")
            raise SystemExit(1)
        print("  QueryBook data:", self.root)
        ctl = program_dir("control")
        if ctl and os.path.isfile(os.path.join(ctl, "qbdrive.py")):   # bring what earlier versions kept on C: onto the drive, once
            subprocess.run([sys.executable, os.path.join(ctl, "qbdrive.py"), self.root], cwd=ctl, env=child_env(self.root))

    def start_all(self) -> None:
        self.programs["control"].start()
        time.sleep(1.0)                                              # the Control Panel opens the shared database first
        for pid in ("language", "stem", "facts", "video"):
            self.programs[pid].start()

    def stop_all(self) -> None:
        for p in self.programs.values():
            p.stop()

    def watch(self) -> None:
        """24 x 7: every 15 s — a program that ended unexpectedly is started again (after 10 s, then longer if it keeps
        ending: never more than about 6 times an hour), and one that is running but has not answered for 3 minutes is
        ended and started again. Programs stopped on purpose (Restart button, closing QueryBook) are left alone."""
        import urllib.request
        fails: dict[str, int] = {}
        restarts: dict[str, list[float]] = {}
        while True:
            time.sleep(15)
            for pid, p in self.programs.items():
                if not p.dir or getattr(p, "user_stopped", False) or not p.proc:
                    continue
                now = time.time()
                recent = [t for t in restarts.get(pid, []) if now - t < 3600]
                restarts[pid] = recent
                ended = p.proc.poll() is not None
                hung = False
                if not ended and p.state == "running" and p.url:
                    try:
                        with urllib.request.urlopen(p.url, timeout=30) as r:          # its home page: every program serves one
                            r.read(64)
                        fails[pid] = 0
                    except Exception:
                        fails[pid] = fails.get(pid, 0) + 1
                        hung = fails[pid] >= 6                         # 6 looks, 15 s apart, each waiting 30 s: about 3-4 minutes
                elif not ended and p.state == "starting" and now - p.started_at > 600:
                    hung = True                                      # never said it was running in 10 minutes
                if not (ended or hung):
                    continue
                wait = 10 if len(recent) < 3 else 600                # keeps ending: try every 10 minutes, never give up
                if recent and now - recent[-1] < wait:
                    continue
                why = "it stopped (code %s)" % p.proc.returncode if ended else "it stopped answering"
                print("  %s %s — starting it again." % (p.name, why))
                if hung:
                    try:
                        p.proc.kill()
                        p.proc.wait(timeout=10)
                    except Exception:
                        pass
                fails[pid] = 0
                restarts[pid] = recent + [now]
                p.restarts = getattr(p, "restarts", 0) + 1
                p.last_restart = {"at": now, "why": why}
                p.start()

    def urls(self) -> dict[str, str]:
        return {pid: p.url for pid, p in self.programs.items() if p.url}


# --------------------------------------------------------------------------- the Ask page's modes (modes.py does the arranging)
def ask_mode(body: dict, urls: dict) -> dict:
    """one question in any mode: guided follow-ups resolve 'it' from earlier turns, a claim is looked up by its subject,
    a structured query is subject + what to know; then the facts are gathered (ask.answer) and arranged (modes.compose)"""
    mode = str(body.get("mode") or "qa")
    q = " ".join(str(body.get("q") or "").split())[:500]
    want = ""
    if body.get("subject"):                                  # structured query
        want = str(body.get("want") or "")
        q = modes.structured(str(body.get("subject")), "") or q
    guided = None
    if mode == "guided" and body.get("turns"):
        guided = modes.follow_up(q, [t for t in body.get("turns") or [] if isinstance(t, dict)])
        q = guided["question"]
    asked = q
    if mode == "verify":
        asked = modes.claim_subject(q) or q
    r = ask.answer(asked, urls, bool(body.get("exact")))
    r["question"] = q
    if mode == "verify":
        r["claim"] = q
    out = modes.compose(r, mode, str(body.get("format") or "auto"), str(body.get("register") or "plain"), want, int(body.get("seed") or 0))
    if guided:
        out["guided"] = guided
    return out


def check_text(text: str, urls: dict) -> dict:
    """every claim in a pasted text checked against the facts (each claim's subject asked in parallel)"""
    claims = modes.split_claims(text, 12)
    results: list[dict] = [{} for _ in claims]

    def one(i: int, c: str) -> None:
        subj = modes.claim_subject(c)
        try:
            r = ask.answer(subj, urls) if subj else {"sections": []}
            results[i] = modes.verdict(c, modes.facts_of(r.get("sections") or []))
            results[i]["subject"] = subj
        except Exception as e:                                # one slow lookup never hides the other claims
            results[i] = {"claim": c, "verdict": "UNKNOWN", "facts": [], "subject": subj, "error": str(e)}
    ts = [threading.Thread(target=one, args=(i, c), daemon=True) for i, c in enumerate(claims)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(40)
    tally = {k: sum(1 for x in results if x.get("verdict") == k) for k in ("VERIFIED", "CONTRADICTED", "UNKNOWN")}
    return {"claims": results, "tally": tally}


# --------------------------------------------------------------------------- the sample-ebook library (Book Query)
class Library:
    """Book Query's books: the 19 bundled with QueryBook (library/) and those the Control Panel's Book Harvester gathered
    (<data folder>/library). A book is loaded when first asked about; the last six are kept in memory."""

    def __init__(self, folders: list) -> None:
        self.folders = [f for f in folders if f]
        self.lock = threading.Lock()
        self.cache: dict = {}
        self.order: list = []

    def where(self) -> dict:
        found: dict = {}
        for d in self.folders:
            try:
                for name in sorted(os.listdir(d)):
                    if name not in found and os.path.isfile(os.path.join(d, name, "book.json.gz")):
                        found[name] = os.path.join(d, name)
            except OSError:
                continue
        return found

    def ids(self) -> list:
        return sorted(self.where())

    def get(self, book_id: str) -> tuple:
        place = self.where().get(book_id)
        if not place:
            raise ValueError("There is no book %r in the library." % book_id)
        with self.lock:
            if book_id in self.cache:
                self.order.remove(book_id)
                self.order.append(book_id)
                return self.cache[book_id]
            with gzip.open(os.path.join(place, "book.json.gz"), "rb") as f:
                book = json.loads(f.read().decode("utf-8"))
            entry = (book, bookq.index(book))
            self.cache[book_id] = entry
            self.order.append(book_id)
            while len(self.order) > 6:
                self.cache.pop(self.order.pop(0), None)
            return entry

    def list(self) -> list:
        """every book's card: the bundled catalog, then the harvested one (re-read each time: the harvester adds books)"""
        cards, seen = [], set()
        for d in self.folders:
            try:
                with open(os.path.join(d, "catalog.json"), encoding="utf-8") as f:
                    for c in json.load(f)["books"]:
                        if c.get("id") not in seen:
                            seen.add(c.get("id"))
                            cards.append(c)
            except (OSError, ValueError, KeyError):
                continue
        return cards

    def chapter(self, book_id: str, n: int) -> dict:
        """the Original Text layer of one chapter: its paragraphs, each with its anchor and its Fact Units"""
        book, _ = self.get(book_id)
        ch = bookq.chapter_of(book, n)
        if not ch:
            raise ValueError("No such chapter.")
        paras: list = []
        last = None
        for u in book["units"]:
            if u["chapter"] != n:
                continue
            key = (u["section"], u["para"])
            if key != last:
                paras.append({"anchor": bookq.anchor(book, u), "units": []})
                last = key
            paras[-1]["units"].append({"id": u["id"], "text": u["text"], "kind": u["kind"]})
        chs = [c["n"] for c in book.get("chapters") or []]
        k = chs.index(n)
        return {"book": book_id, "title": book.get("title"), "chapter": ch, "paragraphs": paras[:1500], "more": len(paras) > 1500,
                "prev": chs[k - 1] if k > 0 else None, "next": chs[k + 1] if k + 1 < len(chs) else None}

    def passage(self, book_id: str, unit_id: str) -> dict:
        """the Original Text layer around one Fact Unit: its whole paragraph, the paragraphs before and after"""
        book, _ = self.get(book_id)
        units = book["units"]
        i = next((k for k, u in enumerate(units) if u.get("id") == unit_id), -1)
        if i < 0:
            raise ValueError("No such Fact Unit in this book.")
        u = units[i]
        key = lambda x: (x["chapter"], x["section"], x["para"])
        paras: list = []
        lo = i
        while lo > 0 and units[lo - 1]["chapter"] == u["chapter"]:
            lo -= 1
        hi = i
        while hi + 1 < len(units) and units[hi + 1]["chapter"] == u["chapter"]:
            hi += 1
        for k in range(lo, hi + 1):
            if not paras or key(paras[-1]["first"]) != key(units[k]):
                paras.append({"first": units[k], "units": []})
            paras[-1]["units"].append({"id": units[k]["id"], "text": units[k]["text"], "kind": units[k]["kind"], "here": k == i})
        at = next(n for n, p in enumerate(paras) if any(x["here"] for x in p["units"]))
        show = paras[max(0, at - 2): at + 3]
        return {"book": book_id, "title": book.get("title"), "anchor": bookq.anchor(book, u), "unit": unit_id,
                "paragraphs": [{"anchor": bookq.anchor(book, p["first"]), "units": p["units"]} for p in show],
                "provenance": book.get("provenance") or {}}


class Watches:
    """saved questions asked again on request or every hour while the window is open (Registry #78)"""

    def __init__(self, folder: str | None) -> None:
        self.path = os.path.join(folder or HERE, "shell", "watches.json")
        self.lock = threading.Lock()

    def load(self) -> list:
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    def save(self, rows: list) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    @staticmethod
    def snapshot(r: dict) -> dict:
        facts = modes.facts_of(r.get("sections") or [])
        return {"short": r.get("short") or "", "facts": sorted({"%s|%s|%s" % (f.get("subject"), f.get("predicate"), f.get("object")) for f in facts})[:200]}

    def act(self, body: dict, urls: dict) -> dict:
        with self.lock:
            rows = self.load()
            a = body.get("action")
            if a == "add":
                q = " ".join(str(body.get("q") or "").split())[:300]
                if not q:
                    raise ValueError("Type the question to watch first.")
                if not any(w["q"].lower() == q.lower() for w in rows):
                    rows.append({"q": q, "added": time.time(), "checks": 0, "changes": 0, "last": None, "last_change": None, "snap": None})
            elif a == "remove":
                rows = [w for w in rows if w["q"] != body.get("q")]
            self.save(rows)
        if a in ("add", "run"):
            self.run_all(urls, only=body.get("q") if a == "add" else None)
        return {"watches": [{k: v for k, v in w.items() if k != "snap"} for w in self.load()]}

    def run_all(self, urls: dict, only: object = None) -> None:
        rows = self.load()
        for w in rows:
            if only and w["q"] != only:
                continue
            try:
                r = ask.answer(w["q"], urls)
            except Exception:
                continue
            snap = self.snapshot(r)
            if w.get("snap") is not None and modes.changed(w["snap"], snap):
                w["changes"] += 1
                w["last_change"] = time.time()
                w["was"] = w["snap"].get("short") or ""
            w["snap"], w["checks"], w["last"], w["now"] = snap, w["checks"] + 1, time.time(), snap["short"]
        with self.lock:
            cur = {x["q"]: x for x in self.load()}
            self.save([next((w for w in rows if w["q"] == q), x) for q, x in cur.items()])

    def loop(self, urls_fn) -> None:
        while True:
            time.sleep(3600)
            try:
                self.run_all(urls_fn())
            except Exception:
                pass


LIST_INTENTS = ("since", "still_correct", "values", "modern", "historical", "network", "trace", "first", "characters", "structure", "timeline", "evidence")


def book_ask(shell: "Shell", body: dict) -> dict:
    """Book Query: one book or several. Questions that ask for a list (what changed since the book, a character's network,
    a timeline, evidence in story order) keep bookq's exact lists; every other question is answered by the answer
    engine — search planned, evidence gathered, the answer composed and every citation verified (qbcompose)."""
    q = " ".join(str(body.get("q") or "").split())[:500]
    ids = [str(x) for x in (body.get("books") or []) if x] or [str(body.get("book") or "")]
    ids = list(dict.fromkeys(ids))[:8]
    loaded = [shell.library.get(i) for i in ids]
    use_ai = body.get("ai", True) not in (False, "false", 0)
    keys = qbcompose.load_keys(shell.root or "")
    if len(loaded) == 1:
        book, idx = loaded[0]
        r = bookq.answer(book, idx, q)
        if r["intent"] not in LIST_INTENTS or (r["intent"] in ("network", "trace", "first") and not (r["edges"] or r["chapters"] or r["passages"])):
            r["composed"] = qbcompose.answer(loaded, q, keys, use_ai)
        return r
    return {"multi": True, "query": q, "books": [{"id": b.get("id"), "title": b.get("title")} for b, _ in loaded],
            "composed": qbcompose.answer(loaded, q, keys, use_ai)}


def say(body: dict, urls: dict) -> dict:
    """the answer spoken by Language Builder's voice (and its mouth track, for a face)"""
    base = (urls.get("language") or "").rstrip("/")
    if not base:
        raise ValueError("Language Builder is not running, so there is no voice yet.")
    req = urllib.request.Request(base + "/api/lablang/say", data=json.dumps({"text": str(body.get("text") or "")[:300],
                                 "lang": body.get("lang") or "en", "voice": body.get("voice") or ""}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def make_handler(shell: Shell):
    ui = os.path.join(HERE, "ui")
    types = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
             ".svg": "image/svg+xml", ".json": "application/json; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
             ".wasm": "application/wasm", ".tflite": "application/octet-stream"}
    lang_dir = program_dir("language")
    vendor = os.path.join(lang_dir, "ui", "vendor", "mediapipe") if lang_dir else ""   # the bundled object detector (offline)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:              # quiet console
            pass

        def send(self, code: int, body, ctype: str = "application/json; charset=utf-8") -> None:
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            u = urllib.parse.urlsplit(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            try:
                if u.path == "/api/shell/status":
                    return self.send(200, {"version": VERSION, "data_folder": shell.root,
                                           "programs": [p.to_json() for p in shell.programs.values()]})
                if u.path == "/api/shell/ask":
                    return self.send(200, ask.answer(q.get("q", ""), shell.urls()))
                if u.path == "/api/shell/modes":
                    return self.send(200, {"inputs": modes.INPUTS, "modes": modes.MODES, "formats": modes.FORMATS, "registers": modes.REGISTERS})
                if u.path == "/api/shell/suggest":          # 1.8.6: spelling suggestions for the name in a question — offered, never applied
                    asked = str(q.get("q", ""))[:300]
                    subj = ask.understand(asked).get("subject") or ""
                    base = (shell.urls().get("control") or "").rstrip("/")
                    if not base or len(subj) < 4:
                        return self.send(200, {"typed": subj, "suggestions": []})
                    r = ask._get(base + "/api/bulk/suggest?" + urllib.parse.urlencode({"q": subj, "top": 4}), timeout=8)
                    for x in r.get("suggestions") or []:      # the whole question with the name respelled, ready to use if the person wants it
                        i = asked.lower().find(subj.lower())
                        x["question"] = (asked[:i] + x["name"] + asked[i + len(subj):]) if i >= 0 else x["name"]
                    return self.send(200, r)
                if u.path == "/api/shell/harvest":         # the harvest in one line, for the header (1.6)
                    base = (shell.urls().get("control") or "").rstrip("/")
                    if not base:
                        return self.send(200, {"state": "unknown", "text": "The Control Panel is starting."})
                    try:
                        with urllib.request.urlopen(base + "/api/bulk/health", timeout=8) as r:
                            return self.send(200, json.loads(r.read().decode("utf-8")))
                    except (OSError, ValueError) as e:
                        return self.send(200, {"state": "unknown", "text": "The harvest could not be read just now (%s)." % e})
                if u.path == "/api/shell/caps":
                    return self.send(200, shell.assist.catalogue())
                if u.path == "/api/shell/library":
                    return self.send(200, {"books": shell.library.list()})
                if u.path == "/api/shell/book":
                    book, _ = shell.library.get(q.get("book", ""))
                    return self.send(200, bookq.overview(book))
                if u.path == "/api/shell/book/ai":
                    keys = qbcompose.load_keys(shell.root or "")
                    return self.send(200, {"claude": bool(keys.get("anthropic")), "gemini": bool(keys.get("gemini")),
                                           "model": qbcompose.CLAUDE_MODEL if keys.get("anthropic") else qbcompose.GEMINI_MODEL if keys.get("gemini") else ""})
                if u.path == "/api/shell/book/chapter":
                    return self.send(200, shell.library.chapter(q.get("book", ""), int(q.get("n") or 0)))
                if u.path == "/api/shell/book/passage":
                    return self.send(200, shell.library.passage(q.get("book", ""), q.get("unit", "")))
                if u.path == "/api/shell/watch":
                    return self.send(200, {"watches": [{k: v for k, v in w.items() if k != "snap"} for w in shell.watches.load()]})
                path = "/index.html" if u.path in ("", "/") else u.path
                rel = os.path.normpath(urllib.parse.unquote(path).lstrip("/"))
                base_dir = ui
                if rel.replace("\\", "/").startswith("vendor/mediapipe/") and vendor:
                    base_dir, rel = vendor, os.path.normpath(rel.replace("\\", "/")[len("vendor/mediapipe/"):])
                f = os.path.join(base_dir, rel)
                if rel.startswith("..") or os.path.isabs(rel) or not os.path.isfile(f):
                    return self.send(404, {"error": "not found"})
                with open(f, "rb") as fh:
                    return self.send(200, fh.read(), types.get(os.path.splitext(f)[1], "application/octet-stream"))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as e:
                return self.send(500, {"error": "%s: %s" % (type(e).__name__, e)})

        def do_POST(self) -> None:
            u = urllib.parse.urlsplit(self.path)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                if u.path == "/api/shell/quit":               # a newer QueryBook asks this one to make way
                    self.send(200, {"ok": True, "version": VERSION})
                    threading.Thread(target=lambda: (time.sleep(0.3), shell.stop_all(), os._exit(0)), daemon=True).start()
                    return
                if u.path == "/api/shell/restart":
                    p = shell.programs.get(body.get("id"))
                    if not p:
                        return self.send(404, {"error": "No such application"})
                    p.stop()
                    p.start()
                    return self.send(200, p.to_json())
                if u.path == "/api/shell/ask":
                    return self.send(200, ask_mode(body, shell.urls()))
                if u.path == "/api/shell/grade":
                    return self.send(200, modes.grade(str(body.get("given") or ""), str(body.get("expected") or "")))
                if u.path == "/api/shell/check":
                    return self.send(200, check_text(str(body.get("text") or "")[:20000], shell.urls()))
                if u.path == "/api/shell/seen":
                    rows = modes.seen_summary([d for d in body.get("detections") or [] if isinstance(d, dict)][:20000])
                    return self.send(200, {"seen": rows, "answer": modes.seen_answer(str(body.get("q") or ""), rows) if body.get("q") else ""})
                if u.path == "/api/shell/watch":
                    return self.send(200, shell.watches.act(body, shell.urls()))
                if u.path == "/api/shell/book/ask":
                    return self.send(200, book_ask(shell, body))
                if u.path == "/api/shell/say":
                    return self.send(200, say(body, shell.urls()))
                if u.path == "/api/shell/fill-dates":       # 1.8.1: the Fill Dates button on a fact — the Control Panel's engine does the reading
                    base = (shell.urls().get("control") or "").rstrip("/")
                    if not base:
                        return self.send(200, {"ok": False, "why": "The Control Panel is not running, so the dates cannot be read just now."})
                    return self.send(200, ask._post(base + "/api/bulk/fill-dates", {"qid": str(body.get("qid") or "")}, timeout=90))
                if u.path == "/api/shell/caps/run":
                    return self.send(200, shell.assist.run(body))
                return self.send(404, {"error": "not found"})
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except urllib.error.HTTPError as e:
                try:
                    msg = json.loads(e.read().decode("utf-8")).get("error") or str(e)
                except Exception:
                    msg = str(e)
                return self.send(400, {"error": msg})
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as e:
                return self.send(500, {"error": "%s: %s" % (type(e).__name__, e)})

    return Handler


def free_port(port: int) -> int:
    import socket
    for p in range(port, port + 20):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return port


def _listening_pid(port: int) -> int:
    """the process listening on 127.0.0.1:<port> (Windows: netstat; Mac/Linux: lsof), or 0"""
    try:
        if os.name == "nt":
            out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, timeout=10).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[1].endswith(":%d" % port) and parts[3].upper() == "LISTENING":
                    return int(parts[4])
        else:
            out = subprocess.run(["lsof", "-nP", "-iTCP:%d" % port, "-sTCP:LISTEN", "-t"], capture_output=True, text=True, timeout=10).stdout
            return int(out.split()[0]) if out.split() else 0
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return 0


def _port_free(port: int) -> bool:
    import socket
    with socket.socket() as so:
        try:
            so.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def stop_older_copies() -> None:
    """An older QueryBook still running (its window left open, or hidden) keeps the port and the applications, and the
    browser keeps showing it. Find any QueryBook window program on 8090-8109 and close it — politely when it knows how
    (version 1.3+), otherwise by ending its process tree. Only a program that answers as a QueryBook window is touched."""
    for port in range(PORT, PORT + 20):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/api/shell/status" % port, timeout=1.5) as r:
                st = json.loads(r.read().decode("utf-8"))
        except Exception:
            continue
        if "programs" not in st:
            continue
        print("  Closing an older QueryBook (version %s) that was still running on port %d…" % (st.get("version", "?"), port))
        try:
            req = urllib.request.Request("http://127.0.0.1:%d/api/shell/quit" % port, data=b"{}", headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=3).read()
        except Exception:
            pid = _listening_pid(port)
            if pid and pid != os.getpid():
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=20)
                else:
                    try:
                        os.kill(pid, 15)
                    except OSError:
                        pass
        for _ in range(240):                                # wait (up to a minute) until the port can be taken: it saves and closes its applications first
            time.sleep(0.25)
            if _port_free(port):
                break
        time.sleep(1.0)


def main(argv: list[str]) -> int:
    print("\n  QueryBook %s" % VERSION)
    stop_older_copies()
    shell = Shell()
    shell.prepare_drive()
    shell.start_all()
    threading.Thread(target=shell.watch, daemon=True, name="qb-shell-watch").start()
    threading.Thread(target=shell.watches.loop, args=(shell.urls,), daemon=True, name="qb-watched-questions").start()   # 24 x 7: restart what ends or hangs
    port = free_port(PORT)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(shell))
    httpd.daemon_threads = True
    url = "http://127.0.0.1:%d/" % port
    print("  Open %s" % url)
    print("  Keep this window open while you use QueryBook. Close it to stop everything.\n")
    if "--no-browser" not in argv:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("  Stopping QueryBook…")
        shell.stop_all()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
