import os
import shutil
import unittest
from pathlib import Path

from querybook.apps.base import QueryContext
from querybook.apps.history import parse_range
from querybook.apps.stem import MathError, evaluate
from tests.helpers import RuntimeCase


class AppsTest(RuntimeCase):
    def ask(self, domain, q):
        return self.rt.all_apps[domain].answer(q, QueryContext(self.rt.store, self.rt.paths.renders))

    def test_envelope_is_uniform(self):
        for domain, q in (("language", "lexicon"), ("stem", "kinetic energy"), ("history", "Magna Carta"), ("video", "Magna Carta")):
            res = self.ask(domain, q)
            for key in ("domain", "query", "kind", "summary", "fql", "sources", "took_ms"):
                self.assertIn(key, res, f"{domain} missing {key}")
            self.assertTrue(res["fql"], f"{domain} should show the FQL it ran")

    def test_language_entry(self):
        res = self.ask("language", "what does serendipity mean?")
        self.assertEqual(res["kind"], "lexicon")
        self.assertEqual(res["headword"], "serendipity")
        self.assertEqual(res["senses"][0]["pos"], "noun")
        self.assertIn("fortunate discoveries", res["senses"][0]["definition"])
        self.assertTrue(any("Walpole" in e["text"] for e in res["examples"]))
        self.assertTrue(self.ask("language", "zzzqqq")["summary"].startswith("No entry"))

    def test_stem_solution_with_steps_and_variables(self):
        res = self.ask("stem", "calculate (3 + 4) * 2^3")
        self.assertEqual(res["solution"]["value"], 56)
        self.assertEqual(res["solution"]["steps"], ["3 + 4 = 7", "2 ^ 3 = 8", "7 × 8 = 56"])
        res = self.ask("stem", "F = m * a where m = 70, a = 9.81")
        self.assertEqual(res["solution"]["target"], "F")
        self.assertAlmostEqual(res["solution"]["value"], 686.7)
        res = self.ask("stem", "kinetic energy")
        self.assertIsNone(res["solution"])
        self.assertIn("E = 0.5 * m * v^2", [f["expr"] for f in res["formulas"]])

    def test_stem_evaluator_is_safe(self):
        for bad in ("__import__('os')", "2 ** 99999", "open('x')", "1/0", "[1,2]"):
            with self.subTest(bad=bad), self.assertRaises(MathError):
                evaluate(bad)

    def test_history_timeline_range_and_bce(self):
        res = self.ask("history", "1750 to 1850")
        years = [e["year"] for e in res["events"]]
        self.assertEqual(years, sorted(years))
        self.assertTrue(all(1750 <= y <= 1850 for y in years))
        self.assertIn(1769, years)
        rome = self.ask("history", "Roman Republic")
        self.assertEqual([e["label"] for e in rome["events"]][:2], ["509 BCE", "44 BCE"])
        self.assertEqual(rome["eras"][0]["era"], "Ancient")
        self.assertEqual(parse_range("20th century")[:2], (1901, 2000))
        self.assertEqual(parse_range("the 1960s")[:2], (1960, 1969))

    def test_video_storyboard_job_is_deterministic(self):
        a = self.ask("video", "the printing press")
        b = self.ask("video", "the printing press")
        self.assertEqual(a["kind"], "storyboard")
        self.assertEqual(a["job"]["id"], b["job"]["id"])
        self.assertTrue(a["job"]["created"])
        self.assertFalse(b["job"]["created"])
        scenes = a["scenes"]
        self.assertEqual(scenes[0]["kind"], "title")
        self.assertEqual(scenes[-1]["kind"], "outro")
        self.assertTrue(all(s2["start"] == s1["end"] for s1, s2 in zip(scenes, scenes[1:])))
        self.assertIn("00:00:00,000 --> ", a["srt"])
        self.assertIn("history", [s["kind"] for s in scenes])

    @unittest.skipUnless(shutil.which("ffmpeg") and os.environ.get("QUERYBOOK_TEST_RENDER"),
                         "set QUERYBOOK_TEST_RENDER=1 (needs ffmpeg) to test MP4 rendering")
    def test_video_render(self):
        job = self.ask("video", "Magna Carta")["job"]["id"]
        video = self.rt.all_apps["video"]
        self.assertTrue(video.start_render(self.rt.store, job, self.rt.paths.renders, wait=True)["ok"])
        doc = self.rt.store.get("Video", job)
        self.assertEqual(doc.data["status"], "rendered", doc.data.get("error"))
        self.assertTrue((Path(self.rt.paths.renders) / doc.data["video_file"]).stat().st_size > 1000)


if __name__ == "__main__":
    unittest.main()
