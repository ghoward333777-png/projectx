"""VeriWave's connection to QueryBook.

Tried in this order:
1. attach: a QueryBook one window already running (http://127.0.0.1:8090): VeriWave uses its applications;
2. start: VeriWave starts QueryBook's applications with QueryBook's own Shell (querybook-one/apps/shell), so the data
   folder rule (data-folder.txt), the ports and the Windows job object are exactly QueryBook's;
3. none (--no-querybook): VeriWave runs alone; answers then come from calculations and the registry only.
The Book Intelligence Studio (PHP, this repository) is started with `php -S` when PHP is installed.

Lean:
    inductive Mode where | auto | attach | start | none
    deriving Repr, BEq, DecidableEq
    inductive Linked where | attached | started | alone
    deriving Repr, BEq, DecidableEq
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
SHELL_DIR = os.path.join(REPO, "querybook-one", "apps", "shell")
SHELL_URL = os.environ.get("VERIWAVE_QUERYBOOK_URL", "http://127.0.0.1:8090")
BOOKS_PORT = 8082


def decide_link(mode: str, shell_answers: bool, shell_present: bool, drive_ok: bool) -> str:
    """how VeriWave links to QueryBook: 'attached', 'started' or 'alone'

    Lean:
        def decideLink (m : Mode) (answers present driveOk : Bool) : Linked :=
          if m == .none then .alone
          else if (m == .auto || m == .attach) && answers then .attached
          else if (m == .auto || m == .start) && present && driveOk then .started
          else .alone
        theorem none_is_alone (a p d : Bool) : decideLink .none a p d = .alone := rfl
        theorem attach_never_starts (a p d : Bool) : decideLink .attach a p d ≠ .started := by
          cases a <;> cases p <;> cases d <;> decide
        #guard decideLink .auto true true true == .attached                -- py: decide_link("auto", True, True, True) == "attached"
        #guard decideLink .auto false true true == .started                -- py: decide_link("auto", False, True, True) == "started"
        #guard decideLink .auto false true false == .alone                 -- py: decide_link("auto", False, True, False) == "alone"
    """
    if mode == "none":
        return "alone"
    if mode in ("auto", "attach") and shell_answers:
        return "attached"
    if mode in ("auto", "start") and shell_present and drive_ok:
        return "started"
    return "alone"


def running_urls(programs: list[dict]) -> dict[str, str]:
    """application id -> URL, for the applications that are running

    Lean:
        structure Prog where
          id : String
          url : String
          state : String
        def runningUrls (ps : List Prog) : List (String × String) :=
          (ps.filter (fun p => p.state == "running" && p.url != "")).map (fun p => (p.id, p.url))
        theorem runningUrls_le (ps : List Prog) : (runningUrls ps).length ≤ ps.length := by
          simp only [runningUrls, List.length_map]; exact List.length_filter_le _ _
        #guard runningUrls [⟨"stem", "http://x", "running"⟩, ⟨"video", "", "starting"⟩] == [("stem", "http://x")]   -- py: running_urls([{"id": "stem", "url": "http://x", "state": "running"}, {"id": "video", "url": None, "state": "starting"}]) == {"stem": "http://x"}
    """
    return {str(p["id"]): str(p["url"]) for p in programs if p.get("url") and p.get("state") == "running"}


def import_shell() -> object | None:
    """QueryBook's shell module (and with it ask.py), or None when querybook-one is not beside VeriWave

    Lean:
        def shellAvailable (shellPyExists : Bool) : Bool := shellPyExists
        #guard shellAvailable true                                           -- py: (import_shell() is not None) == os.path.isfile(os.path.join(SHELL_DIR, "shell.py"))
    """
    if not os.path.isfile(os.path.join(SHELL_DIR, "shell.py")):
        return None
    if SHELL_DIR not in sys.path:
        sys.path.insert(0, SHELL_DIR)
    import shell  # noqa: E402  QueryBook's own module, imported from its folder
    return shell


def import_ask() -> object | None:
    """QueryBook's Ask module (querybook-one/apps/shell/ask.py)

    Lean:
        #guard shellAvailable false == false                                 -- py: (import_ask() is not None) == os.path.isfile(os.path.join(SHELL_DIR, "ask.py"))
    """
    if import_shell() is None:
        return None
    import ask  # noqa: E402
    return ask


def get_json(url: str, timeout: float) -> dict | None:
    """a JSON object from a URL, or None on any failure

    Lean:
        -- network I/O; its only outcomes are a parsed object or nothing
        def orNone (ok : Bool) (v : String) : Option String := if ok then some v else none
        #guard orNone false "x" == none                                      -- py: get_json("http://127.0.0.1:9/none", 0.2) is None
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def port_free(port: int) -> bool:
    """whether nothing listens on 127.0.0.1:port

    Lean:
        def validPort (p : Nat) : Bool := 0 < p && p < 65536
        #guard validPort 8095 && !validPort 70000                            -- py: isinstance(port_free(8095), bool)
    """
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


class Connection:
    """the live link: which way QueryBook is reached, its applications, and the Book Studio

    Lean:
        structure Conn where
          linked : Linked
          booksUrl : String
    """

    def __init__(self, mode: str, books: bool) -> None:
        """Lean:
            def initial : Conn := ⟨.alone, ""⟩
        """
        self.mode = mode
        self.attached_url = ""
        self.shell: object | None = None
        self.books_proc: subprocess.Popen | None = None
        self.books_url = ""
        self.want_books = books
        self.note = ""
        self.cached: dict = {}

    def start(self) -> None:
        """link to QueryBook following decide_link, then start the Book Studio

        Lean:
            def note (l : Linked) : String := match l with
              | .attached => "Using the QueryBook window already running."
              | .started => "VeriWave started QueryBook's applications."
              | .alone => "Running without QueryBook's applications."
            #guard note .started == "VeriWave started QueryBook's applications."   -- py: decide_link("start", False, True, True) == "started"
        """
        st = get_json(SHELL_URL.rstrip("/") + "/api/shell/status", 2.0) if self.mode in ("auto", "attach") else None
        answers = bool(st and "programs" in st)
        sh = import_shell() if self.mode in ("auto", "start") and not answers else None
        shell_obj = sh.Shell() if sh is not None else None  # type: ignore[attr-defined]
        drive_ok = True
        if shell_obj is not None:
            try:
                shell_obj.prepare_drive()  # type: ignore[attr-defined]
            except SystemExit:
                drive_ok = False
        link = decide_link(self.mode, answers, shell_obj is not None, drive_ok)
        if link == "attached":
            self.attached_url = SHELL_URL.rstrip("/")
            self.cached = st or {}
            self.note = "Using the QueryBook window already running at " + self.attached_url + "."
        elif link == "started" and shell_obj is not None:
            self.shell = shell_obj
            shell_obj.start_all()  # type: ignore[attr-defined]
            self.note = "VeriWave started QueryBook's applications."
        elif self.mode == "none":
            self.note = "Running without QueryBook's applications (--no-querybook)."
        elif shell_obj is not None and not drive_ok:
            self.note = "QueryBook's data folder (data-folder.txt) is not connected, so its applications were not started."
        else:
            self.note = "QueryBook's applications are not available."
        if self.want_books:
            self.start_books()

    def start_books(self) -> None:
        """serve the Book Intelligence Studio with PHP's built-in server on port 8082 (or use one already there)

        Lean:
            def booksUrl (port : Nat) : String := "http://127.0.0.1:" ++ toString port
            #guard booksUrl 8082 == "http://127.0.0.1:8082"                  -- py: "http://127.0.0.1:%d" % BOOKS_PORT == "http://127.0.0.1:8082"
        """
        php = shutil.which("php")
        if not php or not os.path.isfile(os.path.join(REPO, "amazon-book-writer.php")):
            return
        self.books_url = "http://127.0.0.1:%d" % BOOKS_PORT
        if not port_free(BOOKS_PORT):
            return
        flags = 0x08000000 if os.name == "nt" else 0
        self.books_proc = subprocess.Popen([php, "-S", "127.0.0.1:%d" % BOOKS_PORT], cwd=REPO, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)

    def stop(self) -> None:
        """stop what VeriWave started (never a QueryBook window it only attached to)

        Lean:
            def stopsShell (l : Linked) : Bool := l == .started
            theorem attached_not_stopped : stopsShell .attached = false := rfl
        """
        if self.shell is not None:
            self.shell.stop_all()  # type: ignore[attr-defined]
        if self.books_proc is not None and self.books_proc.poll() is None:
            self.books_proc.terminate()

    def programs(self) -> list[dict]:
        """QueryBook's applications and their state

        Lean:
            def programsOf (l : Linked) (fromShell fromSelf : List Prog) : List Prog :=
              match l with | .attached => fromShell | .started => fromSelf | .alone => []
            #guard (programsOf .alone [] []).isEmpty                         -- py: Connection("none", False).programs() == []
        """
        if self.attached_url:
            st = get_json(self.attached_url + "/api/shell/status", 2.0)
            if st:
                self.cached = st
            return list(self.cached.get("programs") or [])
        if self.shell is not None:
            return [p.to_json() for p in self.shell.programs.values()]  # type: ignore[attr-defined]
        return []

    def app_urls(self) -> dict[str, str]:
        """every running application's URL, plus the QueryBook window and the Book Studio when present

        Lean:
            #guard (runningUrls []).isEmpty                                  -- py: Connection("none", False).app_urls() == {}
        """
        urls = running_urls(self.programs())
        if self.attached_url:
            urls["shell"] = self.attached_url + "/"
        if self.books_url:
            urls["books"] = self.books_url
        return urls

    def restart(self, pid: str) -> dict:
        """start one QueryBook application again

        Lean:
            def knownApp (pid : String) : Bool := ["control", "language", "stem", "facts", "video"].contains pid
            #guard knownApp "stem" && !knownApp "x"                          -- py: "stem" in ("control", "language", "stem", "facts", "video")
        """
        if self.attached_url:
            req = urllib.request.Request(self.attached_url + "/api/shell/restart", data=json.dumps({"id": pid}).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode("utf-8"))
        if self.shell is None or pid not in self.shell.programs:  # type: ignore[attr-defined]
            raise KeyError("No such application")
        prog = self.shell.programs[pid]  # type: ignore[attr-defined]
        prog.stop()
        prog.start()
        return prog.to_json()

    def status(self) -> dict:
        """how VeriWave is linked, why, and each application's state

        Lean:
            def linkName (l : Linked) : String := match l with
              | .attached => "attached" | .started => "started" | .alone => "none"
            #guard linkName .alone == "none"                                 -- py: Connection("none", False).status()["mode"] == "none"
        """
        mode = "attached" if self.attached_url else "started" if self.shell is not None else "none"
        return {"mode": mode, "note": self.note, "programs": self.programs(), "books_url": self.books_url,
                "data_folder": self.cached.get("data_folder") if self.attached_url else None}

    def wait_until_running(self, seconds: float) -> None:
        """wait (at most `seconds`) while any application is still starting

        Lean:
            def stillStarting (states : List String) : Bool := states.any (· == "starting")
            #guard !stillStarting ["running", "stopped"]                     -- py: Connection("none", False).wait_until_running(0.0) is None
        """
        end = time.time() + seconds
        while time.time() < end and any(p.get("state") == "starting" for p in self.programs()):
            time.sleep(0.25)
