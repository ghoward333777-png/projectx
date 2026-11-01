#!/usr/bin/env python3
"""QueryBook Video Studio — a separate application that makes finished videos.

Shots in, one video out. Common human actions come from the clip library (reused and re-timed locally; generated once
by the video model only when no stored clip exists). Speech, pronunciation and lip-synced narrators come from
Language Builder, which must be running for voices and talk shots (START-ALL starts it). Joins get in-between frames
where the ends match, captions come from the measured word timings, and every result is checked before it is kept.

Start:      python app.py            (opens http://127.0.0.1:8104/)
Self-test:  python app.py --selftest
More:       python app.py --help
"""
import base64, json, os, socket, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import qbcore as core
import studio as st
import hybrid_video as hv
import qbframes as qf

APP_ID = "video"
APP_NAME = "QueryBook Video Studio"
VERSION = "1.0.0"
PORT = 8104
program_dir = HERE

SCHEMA = ["""
CREATE TABLE projects (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  body TEXT NOT NULL,              -- the project as JSON (shots, format, voice, frame work, captions)
  updated TEXT NOT NULL
)
"""]

DEFAULTS = {"language_url": "http://127.0.0.1:8101", "gemini_key": ""}


class App:
    def __init__(self, folder):
        os.makedirs(folder, exist_ok=True)
        self.folder = folder
        self.log = core.make_logger(folder, APP_ID)
        self.store = core.Store(folder, APP_ID, SCHEMA, self.log)
        self.jobs = core.Jobs(self.log, self.store)
        self.api = core.Api()
        self.diag = core.Diagnostics(APP_ID, APP_NAME, VERSION, HERE, self.store, self.log, self.jobs, self._health)
        self.monitor = core.Monitor(folder, APP_ID, APP_NAME, VERSION, self.log)
        self.log.hooks.append(self.monitor.on_error)
        core.add_diagnostics(self.api, self.diag, self.monitor, HERE)
        self.settings_path = os.path.join(folder, "studio-settings.json")
        self.studio = st.Studio(folder, self.settings, self.log)
        self._routes()
        try:
            self.store.backup("startup")
        except Exception as e:
            self.log("startup backup failed:", e)

    # ------------------------------------------------------------------ settings
    def _saved(self):
        try:
            with open(self.settings_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def settings(self):
        """language_url and gemini_key: saved here, else QB_GEMINI_KEY, else Language Builder's own Google setup next door"""
        s = dict(DEFAULTS, **self._saved())
        if not s.get("gemini_key"):
            s["gemini_key"] = os.environ.get("QB_GEMINI_KEY", "")
        if not s.get("gemini_key"):
            for sib in ("QueryBook-Language", "language"):
                p = os.path.join(os.path.dirname(HERE), sib, "google-setup.json")
                try:
                    with open(p, encoding="utf-8") as f:
                        k = (json.load(f).get("api_keys") or {}).get("gemini")
                    if k:
                        s["gemini_key"], s["gemini_key_from"] = k, "Language Builder's Google setup"
                        break
                except (OSError, ValueError, AttributeError):
                    pass
        return s

    def save_settings(self, p):
        cur = self._saved()
        if "language_url" in p:
            u = str(p.get("language_url") or "").strip().rstrip("/")
            if u and not u.startswith(("http://127.0.0.1", "http://localhost")):
                raise core.UserError("Language Builder runs on this computer: use an address starting http://127.0.0.1 or http://localhost.")
            cur["language_url"] = u or DEFAULTS["language_url"]
        if p.get("gemini_key") is not None:
            cur["gemini_key"] = str(p["gemini_key"]).strip()
        tmp = self.settings_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cur, f, indent=1)
        os.replace(tmp, self.settings_path)
        return self.public_settings()

    def public_settings(self):
        s = self.settings()
        k = s.get("gemini_key") or ""
        return {"language_url": s["language_url"], "gemini_key_set": bool(k), "gemini_key_hint": ("…" + k[-4:]) if len(k) > 8 else "",
                "gemini_key_from": s.get("gemini_key_from") or ("this studio" if self._saved().get("gemini_key") else
                                                                "QB_GEMINI_KEY" if k else ""),
                "data_folder": self.folder}

    # ------------------------------------------------------------------ projects
    def save_project(self, project):
        name = str((project or {}).get("name") or "").strip()
        if not name:
            raise core.UserError("Give the project a name.")
        try:
            st.Studio._shots(project)
        except ValueError as e:
            raise core.UserError(str(e))
        with self.store.write() as db:
            db.execute("INSERT INTO projects(name, body, updated) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET body=excluded.body, updated=excluded.updated",
                       (name, json.dumps(project, ensure_ascii=False), core.now_iso()))
        return {"saved": name}

    def render(self, project):
        try:
            st.Studio._shots(project)
        except ValueError as e:
            raise core.UserError(str(e))

        def run(progress, stop):
            return self.studio.render(project, lambda d, t=None, m="", **k: progress(d, t, m), stop)
        return self.jobs.start("Make the video: %s" % (project.get("name") or "untitled"), run)

    # ------------------------------------------------------------------ diagnostics
    def _health(self):
        C = core._check
        out = []
        try:
            v = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10).stdout.split("\n")[0]
            out.append(C("ffmpeg", "ffmpeg (video editing) installed", "ok", v[:60]))
        except (OSError, subprocess.SubprocessError):
            out.append(C("ffmpeg", "ffmpeg (video editing) installed", "fail", "install ffmpeg and put it on PATH"))
        lb = self.studio.language().status()
        out.append(C("language", "Language Builder reachable (voices, narrators, lip-sync)", "ok" if lb["ok"] else "warn",
                     ("version %s at %s" % (lb.get("version"), lb["url"])) if lb["ok"] else "not running — action shots still work"))
        b = qf.backends()
        out.append(C("frames", "Frame interpolation and upscaling", "ok", "%s; %s" % (b["interpolation"], b["upscaling"])))
        out.append(C("library", "Clips in the library", "ok", "%d" % len(self.studio.lib.data["clips"]), len(self.studio.lib.data["clips"])))
        return out

    # ------------------------------------------------------------------ routes
    def _routes(self):
        a = self.api

        @a.get("/api/status")
        def status(p):
            return {"app": APP_NAME, "version": VERSION, "store": self.store.status(), "health": (self.diag.last or {}).get("overall"),
                    "clips": len(self.studio.lib.data["clips"]), "outputs": len(self.studio.outputs()), "job": self.jobs.status()["state"]}

        @a.get("/api/studio/info")
        def info(p):
            return {"actions": [{"id": k, "prompt": v} for k, v in hv.PROMPTS.items()], "formats": list(hv.FORMATS), "grades": list(hv.GRADES),
                    "face_methods": st.FACE_METHODS, "engines": st.ENGINES, "language": self.studio.language().status(),
                    "backends": qf.backends(), "generator": bool(self.settings().get("gemini_key")),
                    "stored_actions": sorted({c["action"] for c in self.studio.lib.data["clips"] if not c["action"].startswith("talk-")})}

        @a.post("/api/studio/plan")
        def plan(p):
            try:
                return self.studio.plan(p.get("project") or {})
            except ValueError as e:
                raise core.UserError(str(e))

        @a.post("/api/studio/render")
        def render(p):
            return self.render(p.get("project") or {})

        @a.get("/api/projects")
        def projects(p):
            return {"projects": [dict(name=r["name"], updated=r["updated"], project=json.loads(r["body"]))
                                 for r in self.store.query("SELECT name, body, updated FROM projects ORDER BY updated DESC LIMIT 200")]}

        @a.post("/api/projects/save")
        def project_save(p):
            return self.save_project(p.get("project") or {})

        @a.post("/api/projects/delete")
        def project_delete(p):
            with self.store.write() as db:
                n = db.execute("DELETE FROM projects WHERE name = ?", (str(p.get("name") or ""),)).rowcount
            return {"deleted": n}

        @a.get("/api/outputs")
        def outputs(p):
            return {"outputs": self.studio.outputs(), "folder": self.studio.out_dir}

        @a.get("/api/output")
        def output(p):
            try:
                path = self.studio.output_path(p.get("name"))
            except FileNotFoundError:
                raise core.UserError("No such video.")
            ctype = {".mp4": "video/mp4", ".srt": "text/plain; charset=utf-8", ".json": "application/json; charset=utf-8"}.get(
                os.path.splitext(path)[1], "application/octet-stream")
            with open(path, "rb") as f:
                return f.read(), ctype

        @a.get("/api/library")
        def library(p):
            lib = self.studio.lib
            return {"clips": sorted(lib.data["clips"], key=lambda c: (c["action"], c["added"])),
                    "timings": {k: lib.timing(k) for k in lib.data["timings"]}, "folder": lib.folder}

        @a.get("/api/library/thumb")
        def thumb(p):
            try:
                t = self.studio.thumb(p.get("id"))
            except FileNotFoundError:
                raise core.UserError("No such clip.")
            with open(t, "rb") as f:
                return f.read(), "image/jpeg"

        @a.get("/api/library/clip")
        def clip(p):
            c = next((x for x in self.studio.lib.data["clips"] if x["id"] == p.get("id")), None)
            if not c:
                raise core.UserError("No such clip.")
            with open(os.path.join(self.studio.lib.folder, c["file"]), "rb") as f:
                return f.read(), "video/mp4"

        @a.post("/api/library/add")
        def library_add(p):
            action = core.norm(str(p.get("action") or "")).replace(" ", "-")
            consent = str(p.get("consent") or "").strip()
            if not action or not all(ch.isalnum() or ch == "-" for ch in action):
                raise core.UserError("Name the action in plain words, for example walk-toward.")
            if action.startswith("talk-"):
                raise core.UserError("Narrations are added by Language Builder, not by hand.")
            if not consent:
                raise core.UserError("Say whose footage this is and that the people in it agreed (or that no real person appears).")
            try:
                data = base64.b64decode(str(p.get("data") or "").split(",")[-1], validate=False)
            except ValueError:
                raise core.UserError("The clip could not be read.")
            if len(data) < 1000:
                raise core.UserError("Choose a video file.")
            with tempfile.TemporaryDirectory() as tmp:
                src = os.path.join(tmp, "upload.mp4")
                with open(src, "wb") as f:
                    f.write(data)
                if st._dur(src) < 1.0:
                    raise core.UserError("The clip is shorter than a second, or is not a video ffmpeg can read.")
                c = self.studio.lib.add(action, src, str(p.get("source") or "added by hand").strip()[:200], consent=consent[:300],
                                        look=str(p.get("look") or "").strip()[:80])
            if c.get("motion", 0) < hv.MIN_MOTION:
                return dict(c, warning="This clip shows almost no motion, so it will not be chosen for the action.")
            return c

        @a.post("/api/library/remove")
        def library_remove(p):
            lib = self.studio.lib
            c = next((x for x in lib.data["clips"] if x["id"] == p.get("id")), None)
            if not c:
                raise core.UserError("No such clip.")
            lib.data["clips"] = [x for x in lib.data["clips"] if x["id"] != c["id"]]
            lib.save()
            if not any(x["file"] == c["file"] for x in lib.data["clips"]):
                for f in (c["file"], c["file"][:-4] + ".thumb.jpg", c["file"][:-4] + ".words.json"):
                    try:
                        os.remove(os.path.join(lib.folder, f))
                    except OSError:
                        pass
            return {"removed": c["id"]}

        @a.get("/api/personas")
        def personas(p):
            try:
                return {"personas": [{k: x.get(k) for k in ("id", "name", "face_method", "voice", "engine", "consent")}
                                     for x in self.studio.language().personas()], "language": True}
            except st.LanguageError as e:
                return {"personas": [], "language": False, "why": str(e)}

        @a.get("/api/settings")
        def settings_get(p):
            return self.public_settings()

        @a.post("/api/settings")
        def settings_set(p):
            return self.save_settings(p)

        @a.get("/api/job")
        def job(p):
            return self.jobs.status()

        @a.post("/api/job/stop")
        def job_stop(p):
            self.jobs.stop()
            return {"ok": True}

        @a.post("/api/backup")
        def backup(p):
            return {"backup": os.path.basename(self.store.backup("manual", force=True) or "")}


def open_app(folder=None):
    return App(folder or core.data_folder(APP_ID, HERE))


# ---------------------------------------------------------------------- self-test
def _ff(args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error"] + args, check=True, capture_output=True)


class _FakeLanguage:
    """a stand-in Language Builder on a spare port: speech is a tone as long as the words, narrations are test video with sound"""

    def __init__(self, tmp):
        self.tmp, self.calls, self.narrations = tmp, [], {}
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _out(self, body, ctype="application/json"):
                if isinstance(body, dict):
                    body = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path, _, q = self.path.partition("?")
                arg = q.split("=", 1)[-1]
                fake.calls.append(path)
                if path == "/api/status":
                    return self._out({"version": "test"})
                if path == "/api/speech/audio":
                    return self._out(open(os.path.join(fake.tmp, arg), "rb").read(), "audio/wav")
                if path == "/api/persona":
                    return self._out({"personas": [{"id": "p1", "name": "Ann", "face_method": "heygen", "consent": True}]})
                if path == "/api/persona/narration":
                    return self._out({"id": arg, "status": "done", "video": True})
                if path == "/api/persona/video":
                    return self._out(open(fake.narrations[arg], "rb").read(), "video/mp4")
                self.send_response(404); self.end_headers()

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                fake.calls.append(self.path)
                n = len(str(body.get("text", "")).split())
                if self.path == "/api/speech/generate":
                    name = "say%d.wav" % len(fake.calls)
                    _ff(["-f", "lavfi", "-i", "sine=frequency=300:duration=%.2f" % (0.45 * n), "-ar", "24000", os.path.join(fake.tmp, name)])
                    return self._out({"audio": name, "summary": {"engine_used": "espeak"}})
                if self.path == "/api/speech/lipsync":
                    words = str(body.get("text", "")).split()
                    return self._out({"words": [{"word": w, "start": 0.45 * i, "end": 0.45 * i + 0.4} for i, w in enumerate(words)]})
                if self.path == "/api/persona/narrate":
                    nid = "n%d" % (len(fake.narrations) + 1)
                    dst = os.path.join(fake.tmp, nid + ".mp4")
                    d = max(2.0, 0.45 * n)
                    _ff(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=%.2f" % d, "-f", "lavfi", "-i",
                         "sine=frequency=500:duration=%.2f" % d, "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", dst])
                    fake.narrations[nid] = dst
                    words = str(body.get("text", "")).split()
                    return self._out({"id": nid, "face_method": body.get("face_method"), "engine_used": "espeak",
                                      "track": {"words": [{"word": w, "start": 0.45 * i, "end": 0.45 * i + 0.4} for i, w in enumerate(words)]}})
                self.send_response(404); self.end_headers()

        s = socket.socket(); s.bind(("127.0.0.1", 0)); self.port = s.getsockname()[1]; s.close()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.port


def selftest():
    c = core.Checks()
    c.check("shared core matches the master copy", core.core_matches_master(HERE))
    c.check("captions: words grouped into timed lines", st.captions([{"word": "a", "start": 0, "end": 0.4}, {"word": "b", "start": 0.5, "end": 0.9},
                                                                      {"word": "c", "start": 3.0, "end": 3.4}]).count("-->") == 2)
    with tempfile.TemporaryDirectory() as tmp:
        fake = _FakeLanguage(os.path.join(tmp, "lb"))
        os.makedirs(fake.tmp)
        app = App(os.path.join(tmp, "data"))
        app.save_settings({"language_url": fake.url, "gemini_key": ""})
        try:
            app.save_settings({"language_url": "http://example.com"})
            c.check("settings refuse a Language Builder address on another computer", False)
        except core.UserError:
            c.check("settings refuse a Language Builder address on another computer", True)
        c.check("Language Builder is found at the saved address", app.studio.language().status()["ok"])
        src = os.path.join(tmp, "walk.mp4")
        _ff(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24:duration=3", "-pix_fmt", "yuv420p", src])
        app.studio.lib.add("walk-toward", src, "filmed", consent="test footage")
        proj = {"name": "Self test", "format": "horizontal", "voice": {"engine": "espeak"}, "captions": True, "bridges": True,
                "shots": [{"type": "action", "action": "walk-toward", "say": "She walks to the door and opens it slowly today"},
                          {"type": "talk", "persona": "p1", "face_method": "heygen", "text": "Hello there, this is the narrator speaking"}]}
        pl = app.studio.plan(proj)
        c.check("plan: stored action reused, the narrator narrates, with an estimate",
                [r["route"] for r in pl["shots"]] == ["reuse", "narrate"] and pl["estimate_s"] > 0 and pl["language"]["ok"], pl["shots"])
        try:
            app.studio.plan({"shots": [{"type": "talk", "persona": "p1", "text": "hi", "face_method": "photo"}]})
            c.check("a talk shot needs a video lip-sync method", False)
        except ValueError:
            c.check("a talk shot needs a video lip-sync method", True)
        r = app.studio.render(proj)
        out = os.path.join(app.studio.out_dir, r["output"])
        c.check("render: one checked video with sound under both shots", r["ok"] and os.path.exists(out) and st._has_audio(out), r)
        c.check("the voice-over is longer than the action, so the action is held on its last frame", r["shots"][0].get("held_s", 0) > 1.0, r["shots"][0])
        c.check("the narration keeps its lip-sync (its length unchanged)", r["shots"][1].get("lip_sync_kept"), r["shots"][1])
        c.check("sound and picture are the same length", r["sound_matches_picture"], r.get("duration_s"))
        srt = os.path.join(app.studio.out_dir, r["captions"] or "-")
        txt = open(srt, encoding="utf-8").read() if os.path.exists(srt) else ""
        c.check("captions from the measured word timings, both shots", "walks" in txt and "narrator" in txt and r["words"] == 17, r.get("words"))
        n_before = sum(1 for x in fake.calls if x == "/api/persona/narrate")
        pl2 = app.studio.plan(proj)
        r2 = app.studio.render(dict(proj, height=480))
        c.check("the same narrator saying the same text is reused from the library, not narrated again",
                pl2["shots"][1]["route"] == "reuse" and r2["shots"][1]["route"] == "reuse"
                and sum(1 for x in fake.calls if x == "/api/persona/narrate") == n_before, r2["shots"][1])
        c.check("upscaled output keeps its source (structural similarity)", r2["ok"] and r2["size"].endswith("x480") and r2["upscale_ssim"] >= 0.85,
                (r2.get("size"), r2.get("upscale_ssim")))
        c.check("outputs listed with their reports", len(app.studio.outputs()) == 2)
        try:
            app.studio.output_path("../studio-settings.json")
            c.check("outputs cannot reach outside their folder", False)
        except FileNotFoundError:
            c.check("outputs cannot reach outside their folder", True)
        try:
            app.studio.render({"shots": [{"type": "action", "action": next(a for a in hv.PROMPTS if a != "walk-toward")}]})
            c.check("a missing action with no generator is refused with a reason", False)
        except ValueError as e:
            c.check("a missing action with no generator is refused with a reason", "generator" in str(e), str(e))
        app.save_project(proj)
        c.check("projects saved and listed", app.store.scalar("SELECT count(*) FROM projects") == 1)
        h = core.make_handler(app.api, os.path.join(HERE, "ui"), app.log, APP_NAME)
        c.check("web routes registered", all(("POST" if k.endswith(("render", "plan", "add")) else "GET", k) in app.api.routes for k in
                                             ("/api/studio/info", "/api/studio/plan", "/api/studio/render", "/api/outputs", "/api/output",
                                              "/api/library", "/api/library/add", "/api/personas")) and h is not None)
        c.check("personas come from Language Builder", app.api.routes[("GET", "/api/personas")]({})["personas"][0]["id"] == "p1")
        c.check("user interface present", all(os.path.exists(os.path.join(HERE, "ui", f)) for f in ("index.html", "app.js", "qb.js", "qb.css")))
        c.check("the Gemini key is never shown in full", "gemini_key" not in app.public_settings())
        fake.server.shutdown()
    return c.report(APP_NAME)


if __name__ == "__main__":
    sys.exit(core.run_cli(sys.modules[__name__]))
