"""VeriWave's window and API (http://127.0.0.1:8095), standard library only.

GET  /                         the window (ui/)
GET  /api/vw/status            engines, QueryBook link, registry numbers, every interface with its URL
GET  /api/vw/features          the Feature Registry (q, domain, area, implemented, audience, limit)
GET  /api/vw/feature?no=       one feature
GET  /api/vw/items             recent creations
GET  /api/vw/zip?id=           a code project as a zip
GET  /out/<id>/<file>          a creation's file
POST /api/vw/chat              {message, history, subject, engine}
POST /api/vw/answer            {q, min_trust, subject, engine}
POST /api/vw/code              {prompt, kind, engine}
POST /api/vw/create            {kind: text|image|video|audio, prompt, engine}
POST /api/vw/querybook/restart {id}

Lean:
    inductive Handler where
      | page | status | features | feature | items | zip | out | traces | trace | packet | evals | eval | chat | answer | code | create
      | restart | evalRun | notFound
    deriving Repr, BEq, DecidableEq
"""
from __future__ import annotations

import json
import os
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import evaluate, factstore, registry, store, trace
from .backends import Claude
from .factstore import FactStore, default_root
from .model import VERSION, VeriWave
from .querybook import Connection, port_free

HERE = os.path.dirname(os.path.abspath(__file__))
UI = os.path.join(os.path.dirname(HERE), "ui")
PORT = 8095
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".svg": "image/svg+xml", ".json": "application/json; charset=utf-8", ".wav": "audio/wav", ".md": "text/markdown; charset=utf-8",
         ".txt": "text/plain; charset=utf-8", ".py": "text/plain; charset=utf-8", ".zip": "application/zip", ".png": "image/png"}


def dispatch(method: str, path: str) -> str:
    """which handler serves a request

    Lean:
        def dispatch (m p : String) : Handler :=
          if m == "GET" then
            if p == "/" || p == "/index.html" || p == "/veriwave.css" || p == "/veriwave.js" then .page
            else if p == "/api/vw/status" then .status else if p == "/api/vw/features" then .features
            else if p == "/api/vw/feature" then .feature else if p == "/api/vw/items" then .items
            else if p == "/api/vw/zip" then .zip else if p == "/api/vw/traces" then .traces else if p == "/api/vw/trace" then .trace
            else if p == "/api/vw/packet" then .packet else if p == "/api/vw/evals" then .evals else if p == "/api/vw/eval" then .eval
            else if p.startsWith "/out/" then .out else .notFound
          else if m == "POST" then
            if p == "/api/vw/chat" then .chat else if p == "/api/vw/answer" then .answer else if p == "/api/vw/code" then .code
            else if p == "/api/vw/create" then .create else if p == "/api/vw/querybook/restart" then .restart
            else if p == "/api/vw/eval/run" then .evalRun else .notFound
          else .notFound
        theorem post_never_serves_files (p : String) : dispatch "POST" p ≠ .out ∧ dispatch "POST" p ≠ .page := by
          unfold dispatch; constructor <;> simp <;> (repeat' split) <;> simp
        #guard dispatch "GET" "/out/000001-x/image.svg" == .out           -- py: dispatch("GET", "/out/000001-x/image.svg") == "out"
        #guard dispatch "POST" "/api/vw/chat" == .chat                     -- py: dispatch("POST", "/api/vw/chat") == "chat"
        #guard dispatch "DELETE" "/" == .notFound                          -- py: dispatch("DELETE", "/") == "notFound"
    """
    if method == "GET":
        if path in ("/", "/index.html", "/veriwave.css", "/veriwave.js"):
            return "page"
        table = {"/api/vw/status": "status", "/api/vw/features": "features", "/api/vw/feature": "feature",
                 "/api/vw/items": "items", "/api/vw/zip": "zip", "/api/vw/traces": "traces", "/api/vw/trace": "trace",
                 "/api/vw/packet": "packet", "/api/vw/evals": "evals", "/api/vw/eval": "eval"}
        if path in table:
            return table[path]
        return "out" if path.startswith("/out/") else "notFound"
    if method == "POST":
        table = {"/api/vw/chat": "chat", "/api/vw/answer": "answer", "/api/vw/code": "code", "/api/vw/create": "create",
                 "/api/vw/querybook/restart": "restart", "/api/vw/eval/run": "evalRun"}
        return table.get(path, "notFound")
    return "notFound"


def content_type(name: str) -> str:
    """the media type served for a file name

    Lean:
        def extOf (name : String) : String := match name.splitOn "." with
          | [] => "" | [_] => "" | parts => "." ++ parts.getLast!
        #guard extOf "a/b.svg" == ".svg"                                    -- py: content_type("a/b.svg") == "image/svg+xml"
        #guard extOf "README" == ""                                         -- py: content_type("README") == "application/octet-stream"
    """
    dot = name.rfind(".")
    return TYPES.get(name[dot:] if dot >= 0 else "", "application/octet-stream")


def int_param(value: object, default: int, lo: int, hi: int) -> int:
    """a whole-number request parameter, limited to [lo, hi]; the default when missing or not a number

    Lean:
        def intParam (v : Option Int) (dflt lo hi : Int) : Int := clamp lo hi (v.getD dflt)
        theorem intParam_in (v : Option Int) (d lo hi : Int) (h : lo ≤ hi) : lo ≤ intParam v d lo hi ∧ intParam v d lo hi ≤ hi :=
          clamp_in lo hi _ h
        #guard intParam (some 900) 50 0 100 == 100                           -- py: int_param("900", 50, 0, 100) == 100
        #guard intParam none 50 0 100 == 50                                  -- py: int_param("x", 50, 0, 100) == 50
    """
    s = str(value).strip() if value is not None else ""
    neg = s.startswith("-")
    digits = s[1:] if neg else s
    if not digits.isdigit() or not digits.isascii():
        return core_clamp(lo, hi, default)
    return core_clamp(lo, hi, -int(digits) if neg else int(digits))


def core_clamp(lo: int, hi: int, x: int) -> int:
    """vw.core.clamp (kept local so the server reads on its own)

    Lean:
        #guard clamp 0 10 (-3) == 0                                          -- py: core_clamp(0, 10, -3) == 0
    """
    return lo if x < lo else hi if x > hi else x


def engine_param(value: object) -> str:
    """the engine a request asks for: 'local' or '' (automatic)

    Lean:
        def engineParam (v : String) : String := if v == "local" then "local" else ""
        #guard engineParam "claude" == ""                                    -- py: engine_param("claude") == ""
    """
    return "local" if value == "local" else ""


class App:
    """the running VeriWave: model, store and QueryBook connection

    Lean:
        structure AppState where
          port : Nat
    """

    def __init__(self, conn: Connection, model: VeriWave) -> None:
        """Lean:
            def AppState.default : AppState := ⟨8095⟩
        """
        self.conn = conn
        self.model = model
        self.eval_state: dict = {"running": False, "done": 0, "total": 0, "last": "", "error": ""}
        self.eval_lock = threading.Lock()

    def get(self, path: str, q: dict[str, str]) -> tuple[int, object, str]:
        """a GET request: (status, body, content type)

        Lean:
            def statusOf (h : Handler) : Nat := if h == .notFound then 404 else 200
            #guard statusOf .notFound == 404                                  -- py: dispatch("GET", "/nope") == "notFound"
        """
        h = dispatch("GET", path)
        if h == "page":
            name = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
            with open(os.path.join(UI, name), "rb") as f:
                return 200, f.read(), content_type(name)
        if h == "status":
            return 200, self.model.status(), ""
        if h == "features":
            return 200, {"features": registry.search(q.get("q", ""), q.get("domain", ""), q.get("area", ""), q.get("implemented", ""),
                                                     q.get("audience", ""), int_param(q.get("limit"), 500, 1, 500)),
                         "summary": registry.summary()}, ""
        if h == "feature":
            f = registry.lookup(q.get("no", ""))
            return (200, f, "") if f is not None else (404, {"error": "No such feature"}, "")
        if h == "items":
            return 200, {"items": self.model.store.list_items(int_param(q.get("limit"), 30, 1, 200))}, ""
        if h == "zip":
            iid = q.get("id", "")
            folder = os.path.join(self.model.store.items, iid)
            if not store.okrel_check([iid]) or not os.path.isdir(folder):
                return 404, {"error": "No such project"}, ""
            files: dict[str, str] = {}
            for dirpath, _, names in os.walk(folder):
                for n in names:
                    full = os.path.join(dirpath, n)
                    rel = os.path.relpath(full, folder).replace(os.sep, "/")
                    if rel != "meta.json":
                        with open(full, encoding="utf-8", errors="replace") as fh:
                            files[rel] = fh.read()
            return 200, store.zip_files(files), "application/zip"
        if h == "evals":
            return 200, self.evals(), ""
        if h == "eval":
            rep = self.eval_report(q.get("name", ""))
            return (200, rep, "") if rep is not None else (404, {"error": "No such report"}, "")
        if h == "traces":
            return 200, {"traces": self.model.trace_list(int_param(q.get("limit"), 100, 1, 200)), "logic_types": trace.LOGIC_TYPES}, ""
        if h == "trace":
            tr = self.model.trace_get(q.get("id", ""))
            return (200, tr, "") if tr is not None else (404, {"error": "No such trace"}, "")
        if h == "packet":
            known = [u["path"] for u in self.model.facts.status()["ufcs"]]
            st = q.get("store", "")
            if st not in known:
                return 404, {"error": "Not a UFCS store VeriWave is connected to"}, ""
            pk = factstore.find_packet(st, int_param(q.get("block"), 0, 0, 100000), q.get("fp", ""), 25.0)
            if pk is None:
                return 404, {"error": "Packet not found in its block"}, ""
            if pk.get("_timeout"):
                return 504, {"error": "The block is large; the packet was not reached within 25 seconds"}, ""
            return 200, pk, ""
        if h == "out":
            parts = path[len("/out/"):].split("/", 1)
            if len(parts) == 2:
                p = self.model.store.file_path(urllib.parse.unquote(parts[0]), urllib.parse.unquote(parts[1]))
                if p is not None:
                    with open(p, "rb") as f:
                        return 200, f.read(), content_type(p)
            return 404, {"error": "not found"}, ""
        return 404, {"error": "not found"}, ""

    def post(self, path: str, body: dict) -> tuple[int, object, str]:
        """a POST request: (status, body, content type)

        Lean:
            def createKind (k : String) : Bool := ["text", "image", "video", "audio"].contains k
            #guard createKind "video" && !createKind "smell"                  -- py: dispatch("POST", "/api/vw/create") == "create"
        """
        h = dispatch("POST", path)
        engine = engine_param(body.get("engine"))
        if h == "chat":
            msg = str(body.get("message") or "").strip()
            if not msg:
                return 400, {"error": "Type a message first."}, ""
            history = [x for x in (body.get("history") or []) if isinstance(x, dict)]
            return 200, self.model.chat(msg, history, str(body.get("subject") or ""), engine), ""
        if h == "answer":
            return 200, self.model.ask(str(body.get("q") or ""), int_param(body.get("min_trust"), 50, 0, 100),
                                       str(body.get("subject") or ""), engine, "Asked on the Answer screen."), ""
        if h == "code":
            prompt = str(body.get("prompt") or "").strip()
            if not prompt:
                return 400, {"error": "Describe the application first."}, ""
            return 200, self.model.make("code", prompt, engine, "Asked on the Code screen.", str(body.get("kind") or "")), ""
        if h == "create":
            kind = str(body.get("kind") or "")
            prompt = str(body.get("prompt") or "").strip()
            if not prompt:
                return 400, {"error": "Write a prompt first."}, ""
            if kind in ("text", "image", "video", "audio"):
                return 200, self.model.make(kind, prompt, engine, "Asked on the Create: " + kind + " screen.", ""), ""
            return 400, {"error": "kind must be text, image, video or audio"}, ""
        if h == "evalRun":
            return self.eval_start(int_param(body.get("sample"), 100, 10, 2000), int_param(body.get("seed"), 1, 0, 1000000))
        if h == "restart":
            try:
                return 200, self.conn.restart(str(body.get("id") or "")), ""
            except (KeyError, OSError) as e:
                return 404, {"error": str(e)}, ""
        return 404, {"error": "not found"}, ""

    def eval_dir(self) -> str:
        """where readiness reports are kept: the creations folder's evals/ (D:\\QB\\veriwave\\evals on the test server)

        Lean:
            def evalDir (root : String) : String := root ++ "/evals"
            #guard evalDir "D:/QB/veriwave" == "D:/QB/veriwave/evals"         -- py: evaluate.report_name(1).startswith("eval-")
        """
        return os.path.join(self.model.store.root, "evals")

    def evals(self) -> dict:
        """the evaluation's store, whether it may run, its progress, and every saved report's scores (newest first)

        Lean:
            #guard reportName 1 == "eval-1.json"                                -- py: evaluate.report_name(1) == "eval-1.json"
        """
        root = evaluate.eval_root()
        st = self.model.facts.status()
        reports: list[dict] = []
        try:
            names = sorted((n for n in os.listdir(self.eval_dir()) if n.startswith("eval-") and n.endswith(".json")), reverse=True)
        except OSError:
            names = []
        for n in names[:50]:
            rep = self.eval_report(n)
            if rep is not None:
                reports.append({"name": n, "at": rep.get("at"), "ok": rep.get("ok"), "error": rep.get("error", ""), "root": rep.get("root"),
                                "facts": (rep.get("store") or {}).get("facts", 0), "summary": rep.get("summary"), "sample": rep.get("sample")})
        return {"root": root, "store": {"root": st.get("root"), "facts": st.get("facts"), "connected": st.get("connected")},
                "blocked": evaluate.readiness_check(st, root), "state": dict(self.eval_state), "reports": reports,
                "phrasings": evaluate.PHRASINGS,
                "questions_file": os.path.join(self.model.store.root, "eval-questions.jsonl")}

    def eval_report(self, name: str) -> dict | None:
        """one saved report by file name

        Lean:
            #guard okRel ["eval-1.json"] && !okRel [".."]                     -- py: store.okrel_check(["eval-1.json"]) and not store.okrel_check([".."])
        """
        if not store.okrel_check([name]) or not name.endswith(".json"):
            return None
        try:
            with open(os.path.join(self.eval_dir(), name), encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def eval_start(self, sample: int, seed: int) -> tuple[int, object, str]:
        """start an evaluation in the background (one at a time); it runs only against the D:\\QB store

        Lean:
            def canStart (running : Bool) (blocked : String) : Bool := !running && blocked == ""
            #guard !canStart true "" && !canStart false "missing" && canStart false ""   -- py: evaluate.readiness_check({"root_exists": False}, "D:\\QB") != ""
        """
        root = evaluate.eval_root()
        why = evaluate.readiness_check(self.model.facts.status(), root)
        with self.eval_lock:
            if self.eval_state["running"]:
                return 409, {"error": "An evaluation is already running."}, ""
            if why:
                return 409, {"error": why}, ""
            self.eval_state = {"running": True, "done": 0, "total": 0, "last": "", "error": ""}
        threading.Thread(target=self.eval_worker, args=(root, sample, seed), daemon=True, name="vw-eval").start()
        return 202, {"started": True, "root": root, "sample": sample, "seed": seed}, ""

    def eval_worker(self, root: str, sample: int, seed: int) -> None:
        """the background evaluation: sampled questions plus the person's own (eval-questions.jsonl), saved as a report

        Lean:
            #guard planSize 1 3 0 == 3                                          -- py: len(evaluate.PHRASINGS) == 3
        """
        def progress(done: int, total: int) -> None:
            """record how far the evaluation has got

            Lean:
                def progressPct (done total : Nat) : Nat := if total = 0 then 0 else done * 100 / total
                #guard progressPct 5 20 == 25                                   -- py: evaluate.percentile([25.0], 50) == 25.0
            """
            self.eval_state["done"] = done
            self.eval_state["total"] = total
        try:
            curated = evaluate.load_curated(os.path.join(self.model.store.root, "eval-questions.jsonl"))
            rep = evaluate.run(self.model, root, sample, seed, curated, progress)
            os.makedirs(self.eval_dir(), exist_ok=True)
            name = evaluate.report_name(int(rep["at"]))
            with open(os.path.join(self.eval_dir(), name), "w", encoding="utf-8") as f:
                json.dump(rep, f, ensure_ascii=False)
            self.eval_state["last"] = name
            self.eval_state["error"] = str(rep.get("error") or "")
        except Exception as e:  # reported on the screen, never swallowed
            self.eval_state["error"] = "Evaluation failed: " + str(e)
        finally:
            self.eval_state["running"] = False


def make_handler(app: App) -> type:
    """the HTTP handler class bound to the running app

    Lean:
        def jsonType : String := "application/json; charset=utf-8"
        #guard jsonType.startsWith "application/json"                         -- py: content_type("x.json").startswith("application/json")
    """

    class Handler(BaseHTTPRequestHandler):
        """Lean:
            def noStore : String := "no-store"
        """

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002  (the standard library's signature)
            """quiet console

            Lean:
                def quiet : Bool := true
            """
            return None

        def reply(self, code: int, body: object, ctype: str) -> None:
            """send one response (JSON unless a content type is given)

            Lean:
                def isJson (ctype : String) : Bool := ctype == ""
                #guard isJson ""                                              -- py: content_type("x.json") == TYPES[".json"]
            """
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype or "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            """Lean:
                #guard dispatch "GET" "/api/vw/status" == .status             -- py: dispatch("GET", "/api/vw/status") == "status"
            """
            u = urllib.parse.urlsplit(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            try:
                code, body, ctype = app.get(u.path, q)
                self.reply(code, body, ctype)
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as e:
                self.reply(500, {"error": "Internal error: " + str(e)}, "")

        def do_POST(self) -> None:
            """Lean:
                #guard dispatch "POST" "/api/vw/code" == .code                -- py: dispatch("POST", "/api/vw/code") == "code"
            """
            u = urllib.parse.urlsplit(self.path)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > 2_000_000:
                    self.reply(413, {"error": "Request too large"}, "")
                    return
                raw = self.rfile.read(n) if n else b"{}"
                body = json.loads(raw or b"{}")
                if not isinstance(body, dict):
                    body = {}
                code, out, ctype = app.post(u.path, body)
                self.reply(code, out, ctype)
            except (BrokenPipeError, ConnectionResetError):
                return
            except json.JSONDecodeError:
                self.reply(400, {"error": "The request was not valid JSON."}, "")
            except Exception as e:
                self.reply(500, {"error": "Internal error: " + str(e)}, "")

    return Handler


def free_port(port: int) -> int:
    """the first free port from `port` upward (20 tries)

    Lean:
        def candidates (p : Nat) : List Nat := (List.range 20).map (p + ·)
        theorem candidates_len (p : Nat) : (candidates p).length = 20 := by simp [candidates]
        #guard (candidates 8095).head? == some 8095                           -- py: free_port(8095) >= 8095
    """
    for p in range(port, port + 20):
        if port_free(p):
            return p
    return port


def parse_args(argv: list[str]) -> dict:
    """--no-querybook, --attach, --start, --no-books, --no-browser, --port N

    Lean:
        def modeOfArgs (args : List String) : String :=
          if args.contains "--no-querybook" then "none" else if args.contains "--attach" then "attach"
          else if args.contains "--start" then "start" else "auto"
        #guard modeOfArgs ["--no-querybook"] == "none"                        -- py: parse_args(["--no-querybook"])["mode"] == "none"
        #guard modeOfArgs [] == "auto"                                         -- py: parse_args([])["mode"] == "auto"
    """
    mode = "none" if "--no-querybook" in argv else "attach" if "--attach" in argv else "start" if "--start" in argv else "auto"
    port = PORT
    if "--port" in argv:
        i = argv.index("--port")
        if i + 1 < len(argv):
            port = int_param(argv[i + 1], PORT, 1024, 65535)
    return {"mode": mode, "books": "--no-books" not in argv, "browser": "--no-browser" not in argv, "port": port}


def main(argv: list[str]) -> int:
    """start VeriWave: link to QueryBook, open the store, serve the window until Ctrl+C or the window's program closes

    Lean:
        def exitCode (ok : Bool) : Nat := if ok then 0 else 1
        #guard exitCode true == 0                                              -- py: parse_args(["--port", "9000"])["port"] == 9000
    """
    args = parse_args(argv)
    print("\n  VeriWave " + VERSION + " — the QueryBook AI model")
    conn = Connection(str(args["mode"]), bool(args["books"]))
    conn.start()
    print("  " + conn.note)
    st = store.Store(store.data_root())
    claude = Claude(None, None)
    print("  Engine: " + ("local + Claude (" + claude.model + ")" if claude.available else "local (set ANTHROPIC_API_KEY to add Claude)"))
    facts = FactStore(default_root())
    fs = facts.status()
    print("  Facts: " + (("%s facts read directly from %s" % (format(fs["facts"], ","), fs["root"])) if fs["connected"]
                         else ("no fact store found in " + (fs["root"] or "(no data folder)"))))
    app = App(conn, VeriWave(conn, st, claude, facts))
    port = free_port(int(args["port"]))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    httpd.daemon_threads = True
    url = "http://127.0.0.1:%d/" % port
    print("  Open " + url + "\n  Keep this window open while you use VeriWave. Close it (or press Ctrl+C) to stop.\n")
    if args["browser"]:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("  Stopping VeriWave…")
        conn.stop()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
