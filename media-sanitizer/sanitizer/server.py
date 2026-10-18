"""Local HTTP server: JSON API plus the drag-and-drop web UI."""

import json
import os
import shutil
import subprocess
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .config import APP_ROOT
from .files import collect_media, safe_filename
from .jobs import JobStore
from .engine import describe
from .inspect import inspect
from .probe import probe

WEB_DIR = os.path.join(APP_ROOT, "web")


def tool_version(binary):
    if not shutil.which(binary):
        return None
    flag = "-ver" if os.path.basename(binary).startswith("exiftool") else "-version"
    out = subprocess.run([binary, flag], capture_output=True, text=True)
    return (out.stdout.splitlines() or [""])[0].strip()


def make_handler(settings, presets, store):
    upload_dir = os.path.join(settings["workspace"], "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        server_version = f"MediaSanitizer/{__version__}"

        def log_message(self, fmt, *args):
            pass

        # --- helpers -----------------------------------------------------
        def send_json(self, payload, status=200):
            body = json.dumps(payload, indent=2).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_error_json(self, status, message):
            self.send_json({"error": message}, status)

        def read_json(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > 1_000_000:
                raise ValueError("JSON body too large")
            return json.loads(self.rfile.read(length) or b"{}")

        def send_file(self, path, content_type, download_name=None):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(os.path.getsize(path)))
            if download_name:
                self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
            self.end_headers()
            with open(path, "rb") as fh:
                shutil.copyfileobj(fh, self.wfile)

        # --- routes ------------------------------------------------------
        def do_GET(self):
            url = urlparse(self.path)
            parts = [unquote(p) for p in url.path.strip("/").split("/") if p]
            try:
                if not parts or parts == ["index.html"]:
                    return self.send_file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")
                if parts == ["api", "health"]:
                    return self.send_json({
                        "version": __version__,
                        "ffmpeg": tool_version(settings["ffmpeg"]),
                        "ffprobe": tool_version(settings["ffprobe"]),
                        "exiftool": tool_version(settings["exiftool"]),
                    })
                if parts == ["api", "presets"]:
                    return self.send_json({"default": settings["default_preset"], "presets": presets})
                if parts == ["api", "settings"]:
                    return self.send_json({k: settings[k] for k in (
                        "default_output_dir", "output_suffix", "default_preset", "media_extensions")})
                if parts == ["api", "jobs"]:
                    jobs = store.list()
                    for j in jobs:  # list view stays light; full report via /api/jobs/<id>
                        if j["report"]:
                            found = j["report"].get("inspection", {}).get("before", {}).get("findings", [])
                            j["report"] = {k: j["report"][k] for k in ("output", "verdict", "notes", "removed")}
                            j["report"]["found_in_source"] = [describe(f) for f in found]
                    return self.send_json({"jobs": jobs})
                if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
                    job = store.get(parts[2])
                    return self.send_json(job) if job else self.send_error_json(404, "No such job")
                if len(parts) == 3 and parts[:2] == ["api", "download"]:
                    job = store.get(parts[2])
                    if not job or job["status"] != "done":
                        return self.send_error_json(404, "No finished job with that id")
                    out = job["report"]["output"]
                    return self.send_file(out, "application/octet-stream", os.path.basename(out))
                return self.send_error_json(404, "Not found")
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            url = urlparse(self.path)
            try:
                if url.path == "/api/upload":
                    return self.handle_upload(parse_qs(url.query))
                body = self.read_json()
                if url.path == "/api/jobs":
                    return self.handle_jobs(body)
                if url.path == "/api/probe":
                    paths = collect_media([body["path"]], settings)
                    return self.send_json({"probes": [probe(p, settings["ffprobe"]) for p in paths]})
                if url.path == "/api/inspect":
                    results = []
                    for p in collect_media([body["path"]], settings):
                        info = probe(p, settings["ffprobe"])
                        result = inspect(p, info, settings)
                        result["summary"] = [describe(f) for f in result["findings"]]
                        results.append(dict(result, path=p))
                    return self.send_json({"inspections": results})
                if url.path == "/api/jobs/clear":
                    return self.send_json({"cleared": store.clear_finished()})
                return self.send_error_json(404, "Not found")
            except (ValueError, KeyError, FileNotFoundError, PermissionError, RuntimeError) as exc:
                return self.send_error_json(400, f"{type(exc).__name__}: {exc}")

        def handle_upload(self, query):
            name = safe_filename((query.get("name") or ["upload"])[0])
            if not name.lower().endswith(tuple(settings["media_extensions"])):
                raise ValueError(f"Unsupported file type: {name}")
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > settings["max_upload_mb"] * 1024 * 1024:
                raise ValueError("Upload is empty or larger than max_upload_mb")
            folder = os.path.join(upload_dir, time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6])
            os.makedirs(folder, exist_ok=True)
            dest = os.path.join(folder, name)
            remaining = length
            with open(dest, "wb") as fh:
                while remaining:
                    chunk = self.rfile.read(min(1 << 20, remaining))
                    if not chunk:
                        raise ValueError("Upload interrupted")
                    fh.write(chunk)
                    remaining -= len(chunk)
            return self.send_json({"path": dest, "bytes": length})

        def handle_jobs(self, body):
            """Body: {"inputs": [file-or-folder, ...], "preset": "...", "output_dir": "...", "recursive": true}"""
            inputs = body.get("inputs") or ([body["input"]] if body.get("input") else [])
            if not inputs:
                raise ValueError("Provide 'inputs': a list of files or folders")
            preset = body.get("preset") or settings["default_preset"]
            output_dir = body.get("output_dir") or settings["default_output_dir"]
            files = collect_media(inputs, settings, body.get("recursive", True))
            if not files:
                raise ValueError("No media files found in the given inputs")
            jobs = [store.submit(f, preset, os.path.expanduser(output_dir)) for f in files]
            return self.send_json({"jobs": jobs}, 201)

    return Handler


def serve(settings, presets, host=None, port=None):
    store = JobStore(settings, presets)
    host = host or settings["host"]
    port = settings["port"] if port is None else port
    httpd = ThreadingHTTPServer((host, port), make_handler(settings, presets, store))
    return httpd, store
