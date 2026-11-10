"""VeriWave engine and server: answers, code, text, images, video, audio, the registry, the window's API."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from vw import answer, audiogen, codegen, imagegen, interfaces, registry, router, store, textgen, verdict, videogen  # noqa: E402
from vw.backends import BackendError, Claude, extract_text, parse_json_reply  # noqa: E402
from vw.model import VeriWave  # noqa: E402
from vw.factstore import FactStore  # noqa: E402
from vw.querybook import Connection  # noqa: E402
from vw.server import App  # noqa: E402

FACTS = {"understood": {"subject": "rome", "hints": ["inception", "date"]}, "asked": ["commons"], "unavailable": [],
         "sections": [{"kind": "facts", "items": [
             {"subject": "Rome (Q220)", "predicate": "inception", "object": "753 BC", "status": "verified", "where": "Wikidata"},
             {"subject": "Rome", "predicate": "inception", "object": "752 BC", "status": "accepted", "where": "History & News"},
             {"subject": "Rome", "predicate": "nickname", "object": "Eternal City", "status": "disputed", "where": "Forum"}]}]}


class AnswerTest(unittest.TestCase):
    def test_refuses_without_facts(self):
        r = answer.compose("When was the printing press invented?", {}, 50, "", False)
        self.assertEqual(r["verdict"], "UNKNOWN")
        self.assertIn("I don't know", r["short"])
        self.assertIn("not running", r["short"])
        self.assertEqual(r["citations"], [])

    def test_trust_gate_and_contradiction(self):
        r = answer.compose("When was Rome founded?", FACTS, 50, "", True)
        self.assertEqual(r["verdict"], "CONTRADICTED")
        self.assertEqual(r["withheld"], 1)                       # the disputed (40%) fact is held back
        self.assertEqual(len(r["citations"]), 2)
        self.assertEqual([c["n"] for c in r["citations"]], [1, 2])
        self.assertEqual({v["value"] for v in r["conflicts"][0]["values"]}, {"753 BC", "752 BC"})
        self.assertEqual(len(r["provenance"]), 64)
        strict = answer.compose("When was Rome founded?", FACTS, 90, "", True)
        self.assertEqual(strict["verdict"], "VERIFIED")
        self.assertEqual(strict["withheld"], 2)

    def test_provenance_changes_with_citations(self):
        a = answer.compose("When was Rome founded?", FACTS, 50, "", True)["provenance"]
        b = answer.compose("When was Rome founded?", FACTS, 90, "", True)["provenance"]
        self.assertNotEqual(a, b)

    def test_arithmetic_and_self_knowledge(self):
        self.assertEqual(answer.compose("What is 15% of 80?", {}, 50, "", False)["short"], "12")
        r = answer.compose("What does the QueryBook feature voice cloning do?", {}, 50, "", False)
        self.assertEqual(r["verdict"], "VERIFIED")
        self.assertTrue(all(c["where"] == "QueryBook Feature Registry v71" for c in r["citations"]))

    def test_followup(self):
        self.assertEqual(answer.resolve_followup("when was it founded", "Rome"), "when was Rome founded")


class GeneratorsTest(unittest.TestCase):
    def test_every_code_kind(self):
        for kind in list(codegen.KINDS) + ["records"]:
            r = codegen.generate_local("a thing called Test Thing with name, price and notes", kind)
            self.assertEqual(r["kind"], kind)
            self.assertIn("README.md", r["files"])
            body = r["files"][r["entry"]]
            if kind == "python":
                compile(body, r["entry"], "exec")
            else:
                self.assertTrue(body.startswith("<!doctype html>"))
                self.assertIn("<h1>Test Thing</h1>", body)

    def test_generated_apps_run(self):
        """each generated page loads in a real browser without a script error"""
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        d = tempfile.mkdtemp()
        try:
            pages = []
            for kind in [k for k in codegen.KINDS if k != "python"] + ["records"]:
                path = os.path.join(d, kind + ".html")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(codegen.generate_local("a test app with name and notes", kind)["files"]["index.html"])
                pages.append(path)
            script = ("const { chromium } = require('playwright'); (async () => { const b = await chromium.launch(); const bad = [];"
                      "for (const f of %s) { const p = await b.newPage(); p.on('pageerror', e => bad.push(f + ': ' + e.message));"
                      "await p.goto('file://' + f); await p.waitForTimeout(150); await p.close(); }"
                      "console.log(JSON.stringify(bad)); await b.close(); })();") % json.dumps(pages)
            out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=120)
            if out.returncode != 0 and "Cannot find module" in out.stderr:
                self.skipTest("playwright is not available to node")
            self.assertEqual(json.loads(out.stdout.strip().splitlines()[-1]), [])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_text_forms(self):
        self.assertEqual(len(textgen.generate_local("write a haiku about rain", [], [])["lines"]), 3)
        art = textgen.generate_local("an article about honey bees", ["Bees make honey"], ["Facts"])
        self.assertIn("## The takeaway", art["text"])
        self.assertIn("Bees make honey. [1] — Facts", art["text"])
        self.assertEqual(textgen.generate_local("x poem about y", [], [])["text"], textgen.generate_local("x poem about y", [], [])["text"])

    def test_images(self):
        a = imagegen.paint("a lighthouse by the sea at sunset")
        self.assertEqual(a["svg"], imagegen.paint("a lighthouse by the sea at sunset")["svg"])
        self.assertEqual(imagegen.safe_svg(a["svg"]), a["svg"])
        self.assertIn("lighthouse", a["elements"])
        self.assertEqual(imagegen.safe_svg('<svg><script>alert(1)</script></svg>'), "")

    def test_video(self):
        v = videogen.generate_local("a 30 second video about a mountain forest")
        self.assertEqual(len(v["scenes"]), 6)
        self.assertEqual(v["svg"].count("<animate attributeName=\"opacity\""), 6)
        self.assertTrue(imagegen.safe_svg(v["svg"]))

    def test_audio(self):
        for p in ("a calm melody", "an upbeat jingle", "5 seconds of rain", "ocean waves for 3 seconds", "a beep", "an alarm"):
            r = audiogen.render(p)
            w = wave.open(io.BytesIO(r["wav"]))
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 22050))
            self.assertGreater(w.getnframes(), 10000)
        self.assertEqual(audiogen.plan('say "hello there"'), {"kind": "speech", "text": "hello there"})


class BackendTest(unittest.TestCase):
    def test_reply_handling(self):
        with self.assertRaises(BackendError):
            extract_text({"stop_reason": "refusal", "content": []})
        self.assertTrue(extract_text({"stop_reason": "max_tokens", "content": [{"type": "text", "text": "x"}]}).endswith("limit]"))
        self.assertEqual(parse_json_reply('Sure:\n```json\n{"a": [1]}\n```'), {"a": [1]})
        body = Claude("k", "claude-opus-5-5").request_body("s", [], 100, "low")
        self.assertEqual((body["model"], body["fallbacks"], body["output_config"]), ("claude-opus-5-5", "default", {"effort": "low"}))
        self.assertFalse(Claude("", None).available)


class RegistryTest(unittest.TestCase):
    def test_registry(self):
        s = registry.summary()
        self.assertEqual((s["total"], s["built"], s["partial"], s["not_built"]), (407, 82, 102, 223))
        self.assertEqual(registry.lookup("#1")["feature"], "Standard Q&A")
        self.assertEqual([f["no"] for f in registry.search("7", "", "", "", "", 5)], [7])
        for f in registry.features():
            self.assertIsNotNone(interfaces.by_id(f["interface"]), f["no"])

    def test_every_registry_screen_is_an_interface(self):
        groups = {f["area"] for f in registry.features()}
        served = {g for i in interfaces.catalog() for g in i["serves"]}
        self.assertEqual(groups - served, set())


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        conn = Connection("none", False)
        conn.start()
        self.app = App(conn, VeriWave(conn, store.Store(self.dir), Claude("", None), FactStore("")))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_status_and_page(self):
        code, body, _ = self.app.get("/api/vw/status", {})
        self.assertEqual(code, 200)
        self.assertEqual(len(body["interfaces"]), len(interfaces.catalog()))
        self.assertEqual(body["registry"]["total"], 407)
        code, page, ctype = self.app.get("/", {})
        self.assertIn(b"veriwave.js", page)
        self.assertTrue(ctype.startswith("text/html"))

    def test_chat_routes_and_files(self):
        for msg, rt in (("Build me a calculator app", "code"), ("draw a snowy mountain at night", "image"),
                        ("compose a sad melody", "audio"), ("make a video about bees", "video"), ("write a poem about rain", "text"),
                        ("What is 2^10?", "answer"), ("open the timeline", "open"), ("hello", "chat")):
            code, r, _ = self.app.post("/api/vw/chat", {"message": msg})
            self.assertEqual((code, r["route"]), (200, rt), msg)
        code, items, _ = self.app.get("/api/vw/items", {})
        self.assertEqual(len(items["items"]), 5)
        img = [i for i in items["items"] if i["kind"] == "image"][0]
        code, svg, ctype = self.app.get("/out/" + img["id"] + "/image.svg", {})
        self.assertEqual((code, ctype), (200, "image/svg+xml"))
        app = [i for i in items["items"] if i["kind"] == "code"][0]
        code, z, ctype = self.app.get("/api/vw/zip", {"id": app["id"]})
        self.assertEqual(sorted(zipfile.ZipFile(io.BytesIO(z)).namelist()), ["README.md", "index.html"])

    def test_paths_cannot_escape(self):
        for p in ("/out/../../etc/passwd", "/out/x/../../vw/core.py", "/out/%2e%2e/x"):
            self.assertEqual(self.app.get(p, {})[0], 404, p)
        self.assertEqual(self.app.get("/api/vw/zip", {"id": ".."})[0], 404)

    def test_bad_requests(self):
        self.assertEqual(self.app.post("/api/vw/chat", {"message": " "})[0], 400)
        self.assertEqual(self.app.post("/api/vw/create", {"kind": "smell", "prompt": "x"})[0], 400)
        self.assertEqual(self.app.post("/api/vw/nope", {})[0], 404)


class VectorsTest(unittest.TestCase):
    def test_golden_vectors_up_to_date(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "gen_vectors.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main()


class FactStoreTest(unittest.TestCase):
    """VeriWave reads QueryBook's facts on the data drive directly and read-only (UFCS, Commons, bulk shards)."""

    def setUp(self):
        import sqlite3
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "store"))
        db = sqlite3.connect(os.path.join(self.root, "store", "index.sqlite"))       # ufcs_store.py's schema
        db.execute("CREATE TABLE fp (fingerprint TEXT PRIMARY KEY, block INTEGER)")
        db.execute("CREATE TABLE nuc (fp TEXT PRIMARY KEY, subject TEXT, predicate TEXT, object TEXT, trust REAL, block INTEGER)")
        db.execute("CREATE INDEX nuc_sp ON nuc(subject, predicate)")
        rows = [("f%d" % i, "%d²" % i, "equals", str(i * i), 0.99, 0) for i in range(1, 3001)]
        rows += [("pp1", "printing press", "inventor", "Johannes Gutenberg", 0.93, 0),
                 ("pp2", "printing press", "time of discovery or invention", "c. 1440", 0.9, 0),
                 ("r1", "rome", "inception", "753 BC", 0.9, 0), ("r2", "rome", "inception", "752 BC", 0.6, 0)]
        db.executemany("INSERT INTO nuc VALUES (?,?,?,?,?,?)", rows)
        db.commit()
        db.close()
        os.makedirs(os.path.join(self.root, "commons", "shards"))
        db = sqlite3.connect(os.path.join(self.root, "commons", "commons.sqlite"))   # qbcommons.py's schema (facts columns used)
        db.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY, fingerprint TEXT, domain TEXT, subject TEXT, predicate TEXT, object TEXT, "
                   "statement TEXT, origin_app TEXT, status TEXT, confidence REAL, created TEXT, updated TEXT)")
        db.execute("INSERT INTO facts VALUES (1,'x','history','Marie Curie','award received','Nobel Prize in Physics',NULL,'facts','verified',0.9,'','')")
        db.commit()
        db.close()
        db = sqlite3.connect(os.path.join(self.root, "commons", "shards", "wikidata-lattice.sqlite"))   # qbbulk.py's shard schema
        db.executescript("CREATE TABLE facts (fp BLOB PRIMARY KEY, s TEXT NOT NULL, p INTEGER NOT NULL, o TEXT NOT NULL, part INTEGER NOT NULL,"
                         " row INTEGER NOT NULL) WITHOUT ROWID; CREATE INDEX facts_s ON facts(s);"
                         "CREATE TABLE predicates (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, rule TEXT);"
                         "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);")
        db.execute("INSERT INTO predicates VALUES (1, 'country', NULL)")
        db.execute("INSERT INTO facts VALUES (x'01', 'Paris (Q90)', 1, 'France (Q142)', 0, 0)")
        db.execute("INSERT INTO meta VALUES ('facts', '1')")
        db.commit()
        db.close()
        self.before = {os.path.join(d, f): os.path.getmtime(os.path.join(d, f)) for d, _, fs in os.walk(self.root) for f in fs}

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_status_counts_every_store(self):
        st = FactStore(self.root).status()
        self.assertTrue(st["connected"])
        self.assertEqual(st["facts"], 3004 + 1 + 1)
        self.assertEqual([os.path.basename(u["path"]) for u in st["ufcs"]], ["store"])

    def test_lookup_every_store(self):
        fs = FactStore(self.root)
        self.assertEqual([(f["predicate"], f["object"], f["trust"]) for f in fs.lookup("Printing Press", 5)],
                         [("inventor", "Johannes Gutenberg", 93), ("time of discovery or invention", "c. 1440", 90)])
        self.assertEqual(fs.lookup("Marie Curie", 5)[0]["object"], "Nobel Prize in Physics")
        self.assertEqual(fs.lookup("Paris", 5)[0]["object"], "France (Q142)")       # 'Name (Q…)' labels by prefix
        self.assertEqual(fs.lookup("Nobody", 5), [])

    def test_answers_from_the_drive_without_apps(self):
        d = tempfile.mkdtemp()
        try:
            conn = Connection("none", False)
            conn.start()
            app = App(conn, VeriWave(conn, store.Store(d), Claude("", None), FactStore(self.root)))
            code, r, _ = app.post("/api/vw/answer", {"q": "When was the printing press invented?"})
            self.assertEqual((code, r["verdict"]), (200, "VERIFIED"))
            self.assertEqual(r["short"], "printing press — time of discovery or invention: c. 1440")
            self.assertIn("ufcs", r["asked"])
            r = app.post("/api/vw/answer", {"q": "When was Rome founded?"})[1]
            self.assertEqual(r["verdict"], "CONTRADICTED")
            self.assertEqual(app.get("/api/vw/status", {})[1]["facts"]["facts"], 3006)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_never_writes(self):
        fs = FactStore(self.root)
        fs.status()
        fs.lookup("rome", 10)
        after = {os.path.join(d, f): os.path.getmtime(os.path.join(d, f)) for d, _, fs_ in os.walk(self.root) for f in fs_}
        self.assertEqual(after, self.before)


class TraceTest(unittest.TestCase):
    """Every prompt leaves a reasoning trace naming each Bible logic type, with UFCS packet tracking and linkage."""

    def setUp(self):
        import sqlite3
        from vw import factstore
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "store"))
        db = sqlite3.connect(os.path.join(self.root, "store", "index.sqlite"))
        db.execute("CREATE TABLE fp (fingerprint TEXT PRIMARY KEY, block INTEGER)")
        db.execute("CREATE TABLE nuc (fp TEXT PRIMARY KEY, subject TEXT, predicate TEXT, object TEXT, trust REAL, block INTEGER)")
        db.execute("CREATE INDEX nuc_sp ON nuc(subject, predicate)")
        for s, p, o, t in (("printing press", "inventor", "Johannes Gutenberg", 0.93), ("printing press", "time of discovery or invention", "c. 1440", 0.9),
                           ("johannes gutenberg", "occupation", "goldsmith", 0.8)):
            db.execute("INSERT INTO nuc VALUES (?,?,?,?,?,0)", (factstore.ufcs_fingerprint(s, p, o, "+"), s, p, o, t))
        db.commit()
        db.close()
        self.data = tempfile.mkdtemp()
        conn = Connection("none", False)
        conn.start()
        self.app = App(conn, VeriWave(conn, store.Store(self.data), Claude("", None), FactStore(self.root)))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.data, ignore_errors=True)

    def test_answer_trace(self):
        from vw import trace
        r = self.app.post("/api/vw/chat", {"message": "Who invented the printing press?"})[1]
        code, t, _ = self.app.get("/api/vw/trace", {"id": r["trace_id"]})
        self.assertEqual(code, 200)
        self.assertEqual([l["id"] for l in t["logic"]], trace.LOGIC_IDS)
        status = {l["id"]: l["status"] for l in t["logic"]}
        for ran in ("deterministic", "atomic", "interpretive", "transport", "relational", "confidence", "deductive", "safety", "metering"):
            self.assertEqual(status[ran], "ran", ran)
        for spec in ("neuromorphic", "predictive", "scenario", "abductive"):
            self.assertEqual(status[spec], "specified, not built", spec)
        self.assertEqual(len(t["packets"]), 2)
        self.assertTrue(all(p["verified"] and p["polarity"] == "+" for p in t["packets"]))
        retrieve = [s for s in t["stages"] if s["id"] == "retrieve"][0]
        self.assertEqual(len(retrieve["data"]["rph"]), 64)
        links = [s for s in t["stages"] if s["id"] == "linkage"][0]["data"]["links"]
        onward = [l for l in links if l["fact"].endswith("Johannes Gutenberg")][0]["onward"]
        self.assertEqual(onward[0]["object"], "goldsmith")                     # Ontology Mesh: one hop to the inventor

    def test_creation_and_screen_traces(self):
        r = self.app.post("/api/vw/create", {"kind": "image", "prompt": "a lighthouse at sunset"})[1]
        t = self.app.get("/api/vw/trace", {"id": r["trace_id"]})[1]
        self.assertEqual({l["id"]: l["status"] for l in t["logic"]}["generative"], "ran")
        self.assertEqual(self.app.get("/api/vw/traces", {})[1]["traces"][0]["route"], "image")
        self.assertEqual(self.app.get("/api/vw/trace", {"id": "../../x"})[0], 404)

    def test_packet_endpoint_only_for_connected_stores(self):
        self.assertEqual(self.app.get("/api/vw/packet", {"store": "/etc", "block": "0", "fp": "x" * 64})[0], 404)
