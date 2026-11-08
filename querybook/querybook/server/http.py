"""Local HTTP server (stdlib only). One server can host the hub with all four
apps, or a single app on its own port; either way every page talks to the same
FQL store and the same /api/stream change feed.

    GET  /                       hub (or the single app's page)
    GET  /<domain>               domain UI: language | stem | history | video
    GET  /api/apps               which apps this server hosts
    GET  /api/<domain>/query?q=  domain-shaped answer (contracts/domain-response)
    POST /api/fql                {"query": "...", "write": false}
    POST /api/ingest             one item or a list of items (real-time push)
    POST /api/video/render       {"id": "<job id>"}
    GET  /api/stream?since=&coll=   Server-Sent Events change feed
    GET  /api/stats              collection counts + harvester status
    GET  /renders/<file>         rendered videos
"""

from __future__ import annotations

import json
import mimetypes
import re
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from querybook import __version__
from querybook.apps.base import QueryContext
from querybook.core.fql import run_fql
from querybook.core.model import RawItem
from querybook.core.store import StoreError

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
MAX_BODY = 5_000_000


class QueryBookServer:
    def __init__(self, store: Any, apps: dict[str, Any], pipeline: Any, *, renders_dir: Path,
                 harvester: Any = None, host: str = "127.0.0.1", port: int = 8090, mode: str = "hub"):
        self.store, self.apps, self.pipeline, self.harvester = store, apps, pipeline, harvester
        self.renders_dir = Path(renders_dir)
        self.mode = mode
        self.stopping = threading.Event()
        self.httpd = ThreadingHTTPServer((host, port), self._handler())
        self.httpd.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    @property
    def url(self) -> str:
        return f"http://{self.httpd.server_address[0]}:{self.port}/"

    def serve_forever(self) -> None:
        try:
            self.httpd.serve_forever(poll_interval=0.25)
        finally:
            self.stopping.set()

    def start_background(self) -> "QueryBookServer":
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()
        return self

    def shutdown(self) -> None:
        self.stopping.set()
        self.httpd.shutdown()
        self.httpd.server_close()

    # ------------------------------------------------------------------
    def _handler(self):
        app_server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = f"QueryBook/{__version__}"
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt: str, *args: Any) -> None:  # keep the console quiet
                pass

            # -- responses ------------------------------------------------
            def send_bytes(self, body: bytes, ctype: str, status: int = 200, cache: bool = False) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "max-age=300" if cache else "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def send_json(self, data: Any, status: int = 200) -> None:
                self.send_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"),
                                "application/json; charset=utf-8", status)

            def send_error_json(self, status: int, code: str, message: str) -> None:
                self.send_json({"ok": False, "error": {"code": code, "message": message}}, status)

            def read_json(self) -> Any:
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    raise ValueError("Request body too large")
                raw = self.rfile.read(length) if length else b"{}"
                return json.loads(raw.decode("utf-8") or "{}")

            def page(self, name: str) -> None:
                path = UI_DIR / f"{name}.html"
                self.send_bytes(path.read_bytes(), "text/html; charset=utf-8")

            # -- routing --------------------------------------------------
            def do_HEAD(self) -> None:
                self.do_GET()

            def do_GET(self) -> None:
                url = urlparse(self.path)
                qs = parse_qs(url.query)
                path = url.path.rstrip("/") or "/"
                try:
                    if path == "/":
                        return self.page("hub" if app_server.mode == "hub" else app_server.mode)
                    if path.lstrip("/") in app_server.apps:
                        return self.page(path.lstrip("/"))
                    if path.startswith("/static/"):
                        f = (UI_DIR / path[len("/static/"):]).resolve()
                        if f.parent != UI_DIR or not f.is_file():
                            return self.send_error_json(404, "not_found", "No such file")
                        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                        return self.send_bytes(f.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text") or ctype.endswith("javascript") else ""))
                    if path.startswith("/renders/"):
                        name = path[len("/renders/"):]
                        f = (app_server.renders_dir / name).resolve()
                        if not re.fullmatch(r"[\w.-]+\.(mp4|srt)", name) or f.parent != app_server.renders_dir.resolve() or not f.is_file():
                            return self.send_error_json(404, "not_found", "No such render")
                        return self.send_bytes(f.read_bytes(), "video/mp4" if name.endswith(".mp4") else "text/plain; charset=utf-8")
                    if path == "/api/apps":
                        return self.send_json({"mode": app_server.mode, "version": __version__,
                                               "apps": [a.describe() for a in app_server.apps.values()]})
                    if path == "/api/stats":
                        return self.send_json({"collections": app_server.store.collections(),
                                               "latest_seq": app_server.store.latest_seq(),
                                               "harvester": app_server.harvester.status() if app_server.harvester else None,
                                               "ingest": dict(app_server.pipeline.stats)})
                    if path == "/api/stream":
                        return self.stream(qs)
                    m = re.fullmatch(r"/api/(\w+)/query", path)
                    if m:
                        app = app_server.apps.get(m.group(1))
                        if app is None:
                            return self.send_error_json(404, "unknown_app", f"This server does not host '{m.group(1)}'")
                        ctx = QueryContext(app_server.store, app_server.renders_dir)
                        return self.send_json(app.answer(qs.get("q", [""])[0], ctx))
                    m = re.fullmatch(r"/api/doc/([A-Z]\w*)/(\w+)", path)
                    if m:
                        doc = app_server.store.get(m.group(1), m.group(2))
                        return self.send_json(doc.to_json() if doc else None, 200 if doc else 404)
                    return self.send_error_json(404, "not_found", "No such page")
                except (BrokenPipeError, ConnectionResetError):
                    return
                except Exception as exc:  # surface errors to the UI instead of dropping the connection
                    return self.send_error_json(500, "internal_error", f"{type(exc).__name__}: {exc}")

            def do_POST(self) -> None:
                path = urlparse(self.path).path.rstrip("/")
                try:
                    body = self.read_json()
                    if path == "/api/fql":
                        query = body.get("query", "") if isinstance(body, dict) else ""
                        res = run_fql(app_server.store, query, readonly=not bool(body.get("write")))
                        return self.send_json(res, 200 if res["ok"] else 400)
                    if path == "/api/ingest":
                        objs = body if isinstance(body, list) else [body]
                        results = []
                        for o in objs[:1000]:
                            if not isinstance(o, dict):
                                continue
                            item = RawItem(body=str(o.get("body") or o.get("text") or ""), title=str(o.get("title") or ""),
                                           source=str(o.get("source") or "push"), url=str(o.get("url") or ""),
                                           domain=o.get("domain"), fields=o.get("fields") or {})
                            results.append(app_server.pipeline.ingest(item).to_json())
                        return self.send_json({"ok": True, "results": results})
                    if path == "/api/video/render":
                        video = app_server.apps.get("video")
                        if video is None:
                            return self.send_error_json(404, "unknown_app", "This server does not host the video app")
                        res = video.start_render(app_server.store, str(body.get("id", "")), app_server.renders_dir)
                        return self.send_json(res, 200 if res.get("ok") else 400)
                    return self.send_error_json(404, "not_found", "No such endpoint")
                except (json.JSONDecodeError, ValueError, StoreError) as exc:
                    return self.send_error_json(400, "bad_request", str(exc))
                except (BrokenPipeError, ConnectionResetError):
                    return
                except Exception as exc:
                    return self.send_error_json(500, "internal_error", f"{type(exc).__name__}: {exc}")

            def stream(self, qs: dict[str, list[str]]) -> None:
                """Server-Sent Events: tails the store's change journal (works across processes)."""
                store = app_server.store
                coll = qs.get("coll", [None])[0]
                since_raw = qs.get("since", [""])[0] or self.headers.get("Last-Event-ID", "")
                since = int(since_raw) if since_raw.lstrip("-").isdigit() and int(since_raw) >= 0 else store.latest_seq()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                last_ping = time.monotonic()
                try:
                    self.wfile.write(f"event: hello\ndata: {json.dumps({'seq': since})}\n\n".encode())
                    self.wfile.flush()
                    while not app_server.stopping.is_set():
                        events = store.changes_since(since, 100, coll)
                        for ev in events:
                            self.wfile.write(f"id: {ev.seq}\nevent: change\ndata: {json.dumps(ev.to_json(), ensure_ascii=False)}\n\n".encode())
                            since = ev.seq
                        if events:
                            self.wfile.flush()
                        elif time.monotonic() - last_ping > 15:
                            self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                            last_ping = time.monotonic()
                        app_server.stopping.wait(0.4)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    return

        return Handler
