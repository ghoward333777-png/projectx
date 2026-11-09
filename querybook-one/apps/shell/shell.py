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

import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ask

VERSION = "1.0.0"
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
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def to_json(self) -> dict:
        return {"id": self.pid, "name": self.name, "url": self.url, "state": self.state,
                "output": self.lines[-12:] if self.state not in ("running",) else []}


class Shell:
    def __init__(self) -> None:
        self.root = data_folder()
        self.job = WindowsJob()
        self.programs = {pid: Program(pid, self.root, self.job) for pid in PROGRAMS}

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

    def urls(self) -> dict[str, str]:
        return {pid: p.url for pid, p in self.programs.items() if p.url}


def make_handler(shell: Shell):
    ui = os.path.join(HERE, "ui")
    types = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
             ".svg": "image/svg+xml", ".json": "application/json; charset=utf-8"}

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
                path = "/index.html" if u.path in ("", "/") else u.path
                rel = os.path.normpath(urllib.parse.unquote(path).lstrip("/"))
                f = os.path.join(ui, rel)
                if rel.startswith("..") or os.path.isabs(rel) or not os.path.isfile(f):
                    return self.send(404, {"error": "not found"})
                with open(f, "rb") as fh:
                    return self.send(200, fh.read(), types.get(os.path.splitext(f)[1], "application/octet-stream"))
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
                return self.send(404, {"error": "not found"})
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
