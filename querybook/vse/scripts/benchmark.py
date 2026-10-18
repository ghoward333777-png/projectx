"""Stage 1's synthetic benchmark with a trained stage-2 lip reader as a third column.
   python scripts/benchmark.py --checkpoint checkpoints/lip_reader_cpu.best.pt --config configs/lip_reading_cpu.yaml"""
import json
import os

from _common import args

from vse.bridge.querybook import Stage2LipReader, benchmark, load_stage1

HERE = os.path.dirname(os.path.abspath(__file__))
a, cfg = args({"--checkpoint": dict(required=True), "--apps": dict(default=os.path.join(HERE, "..", "..", "apps")),
               "--speakers": dict(type=int, default=4)})
s1 = load_stage1(a.apps)
print(json.dumps(benchmark(Stage2LipReader(cfg, a.checkpoint, s1), s1, speakers=a.speakers), indent=2))
