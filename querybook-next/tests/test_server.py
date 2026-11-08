import json
import threading
import time
import unittest
import urllib.request

from querybook.apps import build_apps
from querybook.server import QueryBookServer
from tests.helpers import RuntimeCase


class ServerTest(RuntimeCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.srv = QueryBookServer(cls.rt.store, build_apps(), cls.rt.pipeline, renders_dir=cls.rt.paths.renders,
                                  port=0).start_background()
        cls.single = QueryBookServer(cls.rt.store, build_apps(["history"]), cls.rt.pipeline,
                                     renders_dir=cls.rt.paths.renders, port=0, mode="history").start_background()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.single.shutdown()
        super().tearDownClass()

    def get(self, path, srv=None):
        with urllib.request.urlopen((srv or self.srv).url + path.lstrip("/"), timeout=10) as r:
            return r.status, r.headers.get("Content-Type"), r.read()

    def post(self, path, body):
        req = urllib.request.Request(self.srv.url + path.lstrip("/"), data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_every_ui_page_is_served(self):
        for path in ("/", "/language", "/stem", "/history", "/video"):
            status, ctype, body = self.get(path)
            self.assertEqual(status, 200)
            self.assertIn("text/html", ctype)
            self.assertIn(b"/static/common.js", body)
        self.assertEqual(self.get("/static/common.css")[0], 200)

    def test_domain_query_endpoints(self):
        for domain, kind in (("language", "lexicon"), ("stem", "solution"), ("history", "timeline")):
            _, _, body = self.get(f"/api/{domain}/query?q=lexicon")
            self.assertEqual(json.loads(body)["kind"], kind)

    def test_fql_endpoint_readonly_by_default(self):
        status, res = self.post("/api/fql", {"query": "Collection.all()"})
        self.assertEqual(status, 200)
        self.assertTrue(res["ok"])
        status, res = self.post("/api/fql", {"query": 'Stem.create({ title: "x" })'})
        self.assertEqual((status, res["error"]["code"]), (400, "readonly"))

    def test_single_app_mode_hosts_only_its_app(self):
        _, _, body = self.get("/api/apps", self.single)
        info = json.loads(body)
        self.assertEqual((info["mode"], [a["key"] for a in info["apps"]]), ("history", ["history"]))
        with self.assertRaises(urllib.error.HTTPError):
            self.get("/api/stem/query?q=1", self.single)

    def test_push_ingest_reaches_stream_of_another_server(self):
        """Real-time: a push to the hub shows up on the standalone app's SSE feed."""
        received = []

        def listen():
            with urllib.request.urlopen(self.single.url + "api/stream?coll=History", timeout=10) as r:
                for raw in r:
                    line = raw.decode().strip()
                    if line.startswith("data:") and '"title"' in line:
                        received.append(json.loads(line[5:]))
                        return

        t = threading.Thread(target=listen, daemon=True)
        t.start()
        time.sleep(0.6)
        status, res = self.post("/api/ingest", {"title": "Treaty of Westphalia",
                                                "body": "The Peace of Westphalia was signed in 1648.", "domain": "history"})
        self.assertEqual(res["results"][0]["status"], "added")
        t.join(timeout=8)
        self.assertTrue(received, "no change event arrived")
        self.assertEqual(received[0]["title"], "Treaty of Westphalia")

    def test_path_traversal_is_refused(self):
        for path in ("/static/../server/http.py", "/renders/../querybook.fqldb"):
            with self.assertRaises(urllib.error.HTTPError):
                self.get(path)


if __name__ == "__main__":
    unittest.main()


class UiScriptSyntaxTest(unittest.TestCase):
    """Every page's JavaScript must parse (checked with node when it is installed)."""

    @unittest.skipUnless(__import__("shutil").which("node"), "node not installed")
    def test_all_ui_scripts_parse(self):
        import re
        import subprocess
        import tempfile
        from pathlib import Path

        ui = Path(__file__).resolve().parents[1] / "querybook" / "ui"
        sources = {"common.js": (ui / "common.js").read_text(encoding="utf-8")}
        for page in ui.glob("*.html"):
            for i, block in enumerate(re.findall(r"<script>(.*?)</script>", page.read_text(encoding="utf-8"), re.S)):
                sources[f"{page.name}#{i}"] = block
        with tempfile.TemporaryDirectory() as d:
            for name, code in sources.items():
                f = Path(d) / (name.replace("#", "_") + ".js")
                f.write_text(code, encoding="utf-8")
                proc = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, f"{name}: {proc.stderr}")
