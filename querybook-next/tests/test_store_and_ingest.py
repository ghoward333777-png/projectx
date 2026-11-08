import json
import time
import unittest

from querybook.core.model import RawItem
from querybook.core.store import FQLStore, StoreError
from querybook.ingest import FolderSource, Harvester
from querybook.ingest.sources import FeedSource
from tests.helpers import RuntimeCase

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>The Battle of Hastings</title><link>https://example.org/1066</link><guid>a1</guid>
<description>&lt;p&gt;In 1066 William of Normandy defeated King Harold.&lt;/p&gt;</description></item>
<item><title>Second</title><guid>a2</guid><description>The treaty was signed in 1648.</description></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>t</title>
<entry><id>urn:1</id><title>Photon energy</title><link href="https://example.org/p"/>
<summary>The energy of a photon is E = h * f, where f is the frequency.</summary></entry></feed>"""


class StoreTest(RuntimeCase):
    seed = False

    def test_dedupe_and_change_journal(self):
        store = self.rt.store
        start = store.latest_seq()
        a, created_a = store.create("Language", {"term": "x"})
        b, created_b = store.create("Language", {"term": "x"})
        self.assertTrue(created_a)
        self.assertFalse(created_b)
        self.assertEqual(a.id, b.id)
        store.update("Language", a.id, {"pos": "noun"})
        store.delete("Language", a.id)
        self.assertEqual([e.type for e in store.changes_since(start)], ["add", "update", "remove"])

    def test_second_connection_sees_writes(self):
        """Two FQLStore objects on one file stand in for two app processes."""
        other = FQLStore(self.rt.paths.db)
        seq = other.latest_seq()
        self.rt.store.create("Stem", {"title": "cross-process"})
        events = other.changes_since(seq)
        self.assertEqual(events[-1].title, "cross-process")
        other.close()

    def test_collection_names_are_validated(self):
        with self.assertRaises(StoreError):
            self.rt.store.create("bad name", {})


class IngestTest(RuntimeCase):
    seed = False

    def test_pipeline_classifies_enriches_and_dedupes(self):
        p = self.rt.pipeline
        r1 = p.ingest(RawItem(title="Ohm", body="Ohm's law for a circuit: V = I * R, where voltage and current relate."))
        r2 = p.ingest(RawItem(title="ohm", body="Ohm's law for a  circuit: V = I * R, where voltage and current relate."))
        self.assertEqual((r1.status, r1.coll), ("added", "Stem"))
        self.assertEqual(r2.status, "duplicate")
        doc = self.rt.store.get("Stem", r1.id)
        self.assertEqual(doc.data["formulas"][0]["expr"], "V = I * R")
        self.assertEqual(p.ingest(RawItem(body="  ")).status, "rejected")

    def test_domain_hint_overrides_classifier(self):
        r = self.rt.pipeline.ingest(RawItem(title="Note", body="equation formula theorem", domain="history"))
        self.assertEqual(r.coll, "History")

    def test_folder_source_formats_and_subfolder_domains(self):
        inbox = self.rt.paths.inbox
        (inbox / "history" / "a.txt").write_text("Magna Carta\nSealed in 1215 at Runnymede.", encoding="utf-8")
        (inbox / "b.json").write_text(json.dumps([{"title": "Derivative", "body": "A derivative measures change.", "domain": "stem"}]))
        (inbox / "language" / "c.csv").write_text("title,body,pos\nlucid,clear and easy to understand,adjective\n")
        (inbox / "d.jsonl").write_text('{"title": "Clip", "body": "A short video clip with a slow zoom."}\n')
        src = FolderSource(inbox, settle_seconds=0)
        items = src.poll()
        by_title = {i.title: i for i in items}
        self.assertEqual(by_title["Magna Carta"].domain, "history")
        self.assertEqual(by_title["Derivative"].domain, "stem")
        self.assertEqual(by_title["lucid"].domain, "language")
        self.assertEqual(by_title["lucid"].fields, {"pos": "adjective"})
        self.assertIsNone(by_title["Clip"].domain)
        self.assertEqual(src.poll(), [])  # unchanged files are not re-read

    def test_feed_parsing_rss_and_atom(self):
        f = FeedSource("https://example.org/feed", domain="history")
        items = f.parse(RSS)
        self.assertEqual([i.title for i in items], ["The Battle of Hastings", "Second"])
        self.assertEqual(items[0].body, "In 1066 William of Normandy defeated King Harold.")
        self.assertEqual(items[0].url, "https://example.org/1066")
        self.assertEqual(f.parse(RSS), [])  # seen guids are skipped
        atom = FeedSource("https://example.org/atom").parse(ATOM)
        self.assertEqual((atom[0].title, atom[0].url), ("Photon energy", "https://example.org/p"))

    def test_harvester_runs_sources_and_db_declared_feeds(self):
        (self.rt.paths.inbox / "stem").mkdir(exist_ok=True)
        (self.rt.paths.inbox / "stem" / "h.md").write_text("# Gravity\nGravity accelerates objects at about 9.8 m/s².")
        h = Harvester(self.rt.pipeline, [(FolderSource(self.rt.paths.inbox, settle_seconds=0), 1.0)])
        self.rt.store.create("Source", {"kind": "feed", "url": "http://127.0.0.1:9/never", "domain": "history", "interval": 60})
        status = h.run_once()
        kinds = {s["kind"]: s for s in status["sources"]}
        self.assertGreaterEqual(kinds["folder"]["added"], 1)
        self.assertIn("feed", kinds)
        self.assertTrue(kinds["feed"]["last_error"])  # unreachable feed is reported, not fatal
        self.assertGreaterEqual(self.rt.store.count("IngestLog"), 1)

    def test_background_harvester_picks_up_new_files(self):
        h = Harvester(self.rt.pipeline, [(FolderSource(self.rt.paths.inbox, settle_seconds=0), 0.25)]).start()
        try:
            seq = self.rt.store.latest_seq()
            (self.rt.paths.inbox / "history" / "live.txt").write_text("Telegraph\nMorse sent a message in 1844.")
            deadline = time.time() + 5
            while time.time() < deadline and not any(e.title == "Telegraph" for e in self.rt.store.changes_since(seq)):
                time.sleep(0.1)
            self.assertTrue(any(e.title == "Telegraph" for e in self.rt.store.changes_since(seq)))
        finally:
            h.stop()


if __name__ == "__main__":
    unittest.main()
