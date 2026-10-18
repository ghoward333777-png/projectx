"""Lip-sync motion for a recording: stage-2 models where trained checkpoints exist, stage 1 otherwise.
   python examples/run_lip_sync.py speech.wav "the words spoken" [motion_checkpoint]"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from vse.bridge.querybook import load_stage1  # noqa: E402
from vse.common import config as C  # noqa: E402
from vse.pipeline.lip_sync_pipeline import LipSyncConfig, LipSyncPipeline  # noqa: E402

s1 = load_stage1(os.path.join(HERE, "..", "..", "apps"))
motion = None
if len(sys.argv) > 3:
    from vse.sync.motion_synthesizer import MotionGenerator
    motion = MotionGenerator(C.load(os.path.join(HERE, "..", "configs", "viseme_to_motion.yaml")), sys.argv[3], fps=30, speaker_dim=50)
r = LipSyncPipeline(LipSyncConfig(), s1, motion).run(sys.argv[1], sys.argv[2])
print(json.dumps({"engine": r["engine"], "frames": len(r["motion"]["frames"]), "visemes": len(r["visemes"]["visemes"])}, indent=2))
