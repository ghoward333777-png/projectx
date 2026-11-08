import os
import shutil
import tempfile
import unittest
from pathlib import Path

from querybook.apps import build_apps
from querybook.apps.base import QueryContext
from querybook.cli import Runtime
from querybook.core.fql import run_fql
from querybook.core.legacy import LegacyStore, fingerprint, shard_fp, work_dir
from tests.suite_fixture import build_suite_folder, snapshot
from tests.test_text import unescape

GOLDEN = Path(__file__).resolve().parents[1] / "contracts" / "golden_fingerprints.tsv"


class FingerprintTest(unittest.TestCase):
    def test_matches_the_suites_own_fingerprints(self):
        rows = [l.split("\t") for l in GOLDEN.read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
        self.assertGreaterEqual(len(rows), 10)
        for area, s, p, o, full, key in rows:
            parts = [unescape(x) for x in (area, s, p, o)]
            with self.subTest(parts=parts):
                self.assertEqual(fingerprint(parts), full)
                self.assertEqual(shard_fp(*parts).hex(), key)

    def test_work_dir_matches_the_suite(self):
        self.assertIsNone(work_dir(Path("D:/QB/commons"), env={"QB_WORK_FOLDER": "off"}))
        wd = work_dir(Path("/x/commons"), env={"QB_WORK_FOLDER": "/w"})
        self.assertEqual(wd.parent, Path("/w"))
        self.assertEqual(len(wd.name), 10)


class SuiteStoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = build_suite_folder(Path(tempfile.mkdtemp(prefix="dqb-")), extra_bulk=2000)
        cls.before = snapshot(cls.folder)
        cls.rt = Runtime(str(cls.folder))

    @classmethod
    def tearDownClass(cls):
        cls.rt.store.close()
        shutil.rmtree(cls.folder, ignore_errors=True)

    def fql(self, src, write=False):
        return run_fql(self.rt.store, src, readonly=not write, legacy=self.rt.legacy)

    def test_discovers_commons_and_shards(self):
        lg = self.rt.legacy
        self.assertTrue(lg.available)
        keys = {s.key: s for s in lg.shards()}
        self.assertEqual(set(keys), {"wikidata-dump-1", "pubchem-computed", "tatoeba-cc0"})
        self.assertEqual(keys["wikidata-dump-1"].facts, 2004)
        self.assertEqual((keys["pubchem-computed"].area, keys["tatoeba-cc0"].area), ("stem", "language"))
        self.assertEqual(lg.commons_count(), 1)

    def test_fql_facts_and_commons(self):
        res = self.fql('Facts.bySubject("marie curie")')
        self.assertTrue(res["ok"], res)
        self.assertEqual({f["predicate"] for f in res["data"]}, {"date of birth", "award received"})
        self.assertEqual(self.fql('Facts.exists("history", "Paris", "country", "France")')["data"], ["wikidata-dump-1"])
        self.assertEqual(self.fql('Facts.exists("history", "Paris", "country", "Spain")')["data"], [])
        c = self.fql('Commons.bySubject("Marie Curie").first()')["data"]
        self.assertEqual((c["object"], c["status"]), ("Warsaw", "corroborated"))
        self.assertEqual(self.fql('Commons.byId("1").evidence[0].source')["data"], "Britannica 1911")
        self.assertEqual(sorted(self.fql('Facts.inDataset("pubchem-computed").take(5).map(.object).toArray()')["data"]), ["18.015", "H2O"])
        names = {c["name"] for c in self.fql("Collection.all()")["data"]}
        self.assertTrue({"Facts", "Commons"} <= names)

    def test_billion_row_guard(self):
        for src in ("Facts.all().count()", "Facts.all().order(.subject)", 'Facts.where(.object == "x").toArray()'):
            res = self.fql(src)
            with self.subTest(src=src):
                self.assertEqual(res["error"]["code"], "unbounded_set")
        ok = self.fql('Facts.where(.predicate == "instance of").take(3).count()')
        self.assertEqual(ok["data"], 3)
        self.assertEqual(len(self.fql("Facts.all()")["data"]["data"]), 100)  # output capped
        self.assertEqual(self.fql("Facts.count()")["data"], 2007)  # from each shard's meta, no scan

    def test_suite_store_is_never_written(self):
        res = self.fql('Commons.create({ subject: "x" })', write=True)
        self.assertEqual(res["error"]["code"], "readonly")
        self.fql('Facts.bySubject("Water")')
        ctx = QueryContext(self.rt.store, self.rt.paths.renders, self.rt.legacy)
        for key, app in build_apps().items():
            app.answer("Marie Curie", ctx)
        self.rt.pipeline.ingest(__import__("querybook.core.model", fromlist=["RawItem"]).RawItem(title="t", body="new note"))
        self.assertEqual(snapshot(self.folder), self.before)
        self.assertTrue((self.folder / "querybook-next" / "querybook.fqldb").is_file())

    def test_domain_answers_include_store_facts(self):
        ctx = QueryContext(self.rt.store, self.rt.paths.renders, self.rt.legacy)
        res = build_apps(["history"])["history"].answer("Marie Curie", ctx)
        objs = {f["object"] for f in res["store_facts"]}
        self.assertIn("Warsaw", objs)          # Commons
        self.assertIn("1867-11-07", objs)      # bulk shard
        self.assertIn(1867, [e["year"] for e in res["events"]])  # dated store fact on the timeline
        stem = build_apps(["stem"])["stem"].answer("water", ctx)
        self.assertIn("H2O", {f["object"] for f in stem["store_facts"]})

    def test_prefers_newer_working_copy(self):
        wdir = Path(tempfile.mkdtemp())
        lg = LegacyStore(self.folder / "commons", env={"QB_WORK_FOLDER": str(wdir)})
        wd = work_dir(self.folder / "commons", env={"QB_WORK_FOLDER": str(wdir)})
        wd.mkdir(parents=True)
        shutil.copy(self.folder / "commons" / "shards" / "pubchem-computed.sqlite", wd / "pubchem-computed.sqlite")
        info = {s.key: s for s in lg.shards()}["pubchem-computed"]
        self.assertTrue(info.working_copy)
        self.assertEqual(info.path, wd / "pubchem-computed.sqlite")
        shutil.rmtree(wdir)


if __name__ == "__main__":
    unittest.main()
