"""Read the lips in QueryBook frames JSON (as the Language Builder's page sends them) or a video file (needs mediapipe).
   python examples/run_lip_reading.py frames.json [--script "expected words"]"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from vse.bridge.querybook import load_stage1  # noqa: E402
from vse.pipeline.lip_read_pipeline import LipReadConfig, LipReadPipeline  # noqa: E402

s1 = load_stage1(os.path.join(HERE, "..", "..", "apps"))
src = sys.argv[1]
script = sys.argv[sys.argv.index("--script") + 1] if "--script" in sys.argv else ""
pipe = LipReadPipeline(LipReadConfig(), s1)
r = pipe.run(frames=json.load(open(src)), script=script) if src.endswith(".json") else pipe.run(video_path=src, script=script)
print(json.dumps({k: r[k] for k in ("lipread", "script") if k in r}, indent=2)[:4000])
