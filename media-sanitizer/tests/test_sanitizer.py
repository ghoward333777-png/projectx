"""Run with:  python3 -m unittest discover -s tests   (from the media-sanitizer folder)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sanitizer.commands import build_command, output_path_for  # noqa: E402
from sanitizer.config import load_presets, load_settings, validate_preset  # noqa: E402
from sanitizer.engine import compare, sanitize  # noqa: E402
from sanitizer.probe import probe  # noqa: E402

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


class ConfigTests(unittest.TestCase):
    def test_shipped_presets_are_valid(self):
        self.assertIn("youtube_ready", load_presets())

    def test_validation_catches_bad_presets(self):
        self.assertTrue(validate_preset("x", {"description": "d", "container": "avi"}))
        self.assertTrue(validate_preset("x", {"description": "d", "container": "mp4", "reencode": True}))
        bad_codec = {"description": "d", "container": "mp4", "reencode": True, "video": {"codec": "prores_ks"}}
        self.assertTrue(validate_preset("x", bad_codec))
        ok = {"description": "d", "container": "mp4", "reencode": True, "audio": {"codec": "aac"}}
        self.assertEqual(validate_preset("x", ok), [])


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.presets = load_presets()

    def test_every_command_strips_metadata(self):
        for name, preset in self.presets.items():
            cmd = build_command("in.mov", "out.x", preset)
            for flag in ("-map_metadata", "-map_chapters"):
                self.assertEqual(cmd[cmd.index(flag) + 1], "-1", name)
            self.assertIn("+bitexact", cmd, name)
            self.assertEqual(cmd[-1], "out.x")

    def test_stream_copy_and_reencode(self):
        copy = build_command("a.mp4", "b.mp4", self.presets["lossless_sanitize"])
        self.assertIn("copy", copy)
        self.assertIn("+faststart", copy)
        yt = build_command("a.mov", "b.mp4", self.presets["youtube_ready"])
        self.assertEqual(yt[yt.index("-c:v") + 1], "libx264")
        self.assertIn("loudnorm=I=-14:TP=-1:LRA=11", yt)

    def test_output_naming(self):
        self.assertEqual(output_path_for("/x/clip.mov", "/o", self.presets["youtube_ready"]), "/o/clip_clean.mp4")
        self.assertEqual(output_path_for("/x/clip.mov", "/o", self.presets["lossless_sanitize"]), "/o/clip_clean.mov")


class CompareTests(unittest.TestCase):
    def test_technical_and_generic_encoder_tags_do_not_fail(self):
        before = {"format_tags": {"title": "t", "encoder": "Studio 3"}, "chapters": 2,
                  "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264", "tags": {"title": "v"}},
                              {"index": 1, "codec_type": "data", "codec_name": "bin_data", "tags": {}}]}
        after = {"format_tags": {"major_brand": "isom", "encoder": "Lavf"}, "chapters": 0,
                 "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264",
                              "tags": {"handler_name": "VideoHandler", "encoder": "Lavc libx264"}}]}
        diff = compare(before, after, ["handler_name", "major_brand"])
        self.assertEqual(diff["verdict"], "clean")
        self.assertEqual(diff["removed"]["format_tags"], ["title"])
        self.assertEqual(diff["removed"]["chapters"], 2)
        self.assertEqual(diff["removed"]["dropped_streams"], ["1:data/bin_data"])

    def test_descriptive_leftovers_need_review(self):
        same = {"format_tags": {"comment": "made with X"}, "chapters": 0, "streams": []}
        self.assertEqual(compare(same, same, [])["verdict"], "review")


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not installed")
class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.sample = os.path.join(cls.tmp, "in", "sample.mp4")
        os.makedirs(os.path.dirname(cls.sample))
        subprocess.run(["ffmpeg", "-v", "error", "-y",
                        "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=1",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                        "-c:v", "libx264", "-c:a", "aac",
                        "-metadata", "title=Studio render", "-metadata", "comment=made by StudioX",
                        "-metadata:s:a:0", "title=studio audio", cls.sample], check=True)
        cls.settings = load_settings()
        cls.settings["workspace"] = os.path.join(cls.tmp, "ws")
        cls.settings["default_output_dir"] = os.path.join(cls.tmp, "ws", "out")
        cls.presets = load_presets()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_all_presets_produce_clean_files(self):
        for name in self.presets:
            report = sanitize(self.sample, os.path.join(self.tmp, name), name, self.presets, self.settings)
            self.assertEqual(report["verdict"], "clean", (name, report["remaining"], report["notes"]))
            self.assertIn("title", report["removed"]["format_tags"])
            after = probe(report["output"])
            self.assertNotIn("title", after["format_tags"])
            self.assertTrue(any(s["codec_type"] == "video" for s in after["streams"]), name)

    def test_server_round_trip(self):
        from sanitizer.server import serve
        httpd, _ = serve(self.settings, self.presets, "127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        url = "http://127.0.0.1:%d" % httpd.server_address[1]
        try:
            def call(path, body=None, raw=None):
                data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
                with urllib.request.urlopen(urllib.request.Request(url + path, data=data)) as res:
                    return json.loads(res.read())

            self.assertIn("lossless_sanitize", call("/api/presets")["presets"])
            with open(self.sample, "rb") as fh:
                uploaded = call("/api/upload?name=../evil%20name.mp4", raw=fh.read())
            self.assertTrue(uploaded["path"].startswith(self.settings["workspace"]))
            job = call("/api/jobs", {"inputs": [uploaded["path"]], "preset": "lossless_sanitize"})["jobs"][0]
            for _ in range(100):
                state = call("/api/jobs/" + job["id"])
                if state["status"] in ("done", "failed"):
                    break
                time.sleep(0.1)
            self.assertEqual(state["status"], "done", state.get("error"))
            self.assertEqual(state["report"]["verdict"], "clean")
            with urllib.request.urlopen(url + "/api/download/" + job["id"]) as res:
                self.assertGreater(len(res.read()), 1000)
            with urllib.request.urlopen(url + "/") as res:
                self.assertIn(b"Media Sanitizer", res.read())
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
