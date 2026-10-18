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
from sanitizer.engine import compare, describe, sanitize  # noqa: E402
from sanitizer.inspect import container_findings, inspect, load_signatures, scan_signatures  # noqa: E402
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


class InspectTests(unittest.TestCase):
    def test_signature_scan_reports_offsets_across_chunk_boundaries(self):
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(b"\0" * 14 + b"x264 - core 1" + b"\0" * 50 + b"<x:xmpmeta")
        try:
            hits = {h["name"]: h for h in scan_signatures(fh.name, load_signatures(), chunk=16)}
            self.assertEqual(hits["x264 encoder settings (H.264 SEI)"]["offsets"], [14])
            self.assertEqual(hits["XMP packet"]["offsets"], [77])
        finally:
            os.remove(fh.name)

    def test_c2pa_uuid_box_and_wav_chunks_are_located(self):
        import struct
        c2pa = bytes.fromhex("d8fec3d61b0e483c92975828877ec481")
        mp4 = struct.pack(">I4s", 16, b"ftyp") + b"isom\0\0\0\0" + struct.pack(">I4s", 28, b"uuid") + c2pa + b"jumb"
        wav = b"RIFF" + struct.pack("<I", 4 + 18) + b"WAVE" + b"bext" + struct.pack("<I", 10) + b"originator"
        for data, expect in ((mp4, ("C2PA content credentials manifest", 16)), (wav, ("bext", 12))):
            with tempfile.NamedTemporaryFile(delete=False) as fh:
                fh.write(data)
            try:
                f = container_findings(fh.name)[0]
                self.assertIn(expect[0], (f["name"], f["box"]))
                self.assertEqual(f["offset"], expect[1])
            finally:
                os.remove(fh.name)


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
        cls.settings["inspection"] = dict(cls.settings["inspection"], visual_overlays=False)
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
            self.assertEqual(report["inspection"]["after"]["findings"], [], name)
        source = {f["name"] for f in report["inspection"]["before"]["findings"]}
        self.assertTrue({"title", "x264 encoder settings (H.264 SEI)"} <= source)

    def test_audio_only_formats_come_out_clean(self):
        for ext, codec in (("mp3", "libmp3lame"), ("wav", "pcm_s16le")):
            src = os.path.join(self.tmp, "in", "tone." + ext)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=duration=1",
                            "-c:a", codec, "-metadata", "title=Studio", src], check=True)
            before = inspect(src, probe(src), self.settings)["findings"]
            self.assertTrue(before, ext)
            report = sanitize(src, os.path.join(self.tmp, "audio"), "lossless_sanitize", self.presets, self.settings)
            self.assertEqual(report["verdict"], "clean", (ext, report["notes"]))

    def test_burned_in_logo_is_located(self):
        src = os.path.join(self.tmp, "in", "logo.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=4",
                        "-vf", "drawbox=x=540:y=20:w=80:h=40:color=white:t=fill,"
                               "drawbox=x=550:y=28:w=60:h=24:color=black:t=4",
                        "-c:v", "libx264", src], check=True)
        settings = dict(self.settings, inspection=dict(self.settings["inspection"], visual_overlays=True))
        result = inspect(src, probe(src), settings)
        boxes = [f["box"] for f in result["findings"] if f["kind"] == "overlay"]
        self.assertTrue(any(b["x"] <= 540 and b["y"] <= 20 and b["x"] + b["w"] >= 620 and b["y"] + b["h"] >= 60
                            for b in boxes), boxes)
        self.assertTrue(any("top-right" in describe(f) for f in result["findings"]))

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
