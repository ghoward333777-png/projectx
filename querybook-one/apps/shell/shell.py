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
import bookq
import modes

VERSION = "1.2.0"
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
        self.library = Library(os.path.join(HERE, "library"))

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
    r = ask.answer(asked, urls)
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
    """the books in library/<id>/book.json.gz, loaded when first asked about (the last six are kept in memory)"""

    def __init__(self, folder: str) -> None:
        self.folder = folder
        self.lock = threading.Lock()
        self.cache: dict = {}
        self.order: list = []
        self.cards: list | None = None

    def ids(self) -> list:
        try:
            return sorted(d for d in os.listdir(self.folder) if os.path.isfile(os.path.join(self.folder, d, "book.json.gz")))
        except OSError:
            return []

    def get(self, book_id: str) -> tuple:
        if book_id not in self.ids():
            raise ValueError("There is no book %r in the library." % book_id)
        with self.lock:
            if book_id in self.cache:
                self.order.remove(book_id)
                self.order.append(book_id)
                return self.cache[book_id]
            with gzip.open(os.path.join(self.folder, book_id, "book.json.gz"), "rb") as f:
                book = json.loads(f.read().decode("utf-8"))
            entry = (book, bookq.index(book))
            self.cache[book_id] = entry
            self.order.append(book_id)
            while len(self.order) > 6:
                self.cache.pop(self.order.pop(0), None)
            return entry

    def list(self) -> list:
        """one card per book, from library/catalog.json (written by tools/build_library.py)"""
        if self.cards is None:
            try:
                with open(os.path.join(self.folder, "catalog.json"), encoding="utf-8") as f:
                    self.cards = json.load(f)["books"]
            except (OSError, ValueError, KeyError):
                self.cards = []
        return self.cards

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
                if u.path == "/api/shell/library":
                    return self.send(200, {"books": shell.library.list()})
                if u.path == "/api/shell/book":
                    book, _ = shell.library.get(q.get("book", ""))
                    return self.send(200, bookq.overview(book))
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
                    book, idx = shell.library.get(str(body.get("book") or ""))
                    return self.send(200, bookq.answer(book, idx, str(body.get("q") or "")[:500]))
                if u.path == "/api/shell/say":
                    return self.send(200, say(body, shell.urls()))
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


def main(argv: list[str]) -> int:
    print("\n  QueryBook %s" % VERSION)
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
