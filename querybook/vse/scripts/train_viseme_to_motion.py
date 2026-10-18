"""Face motion synthesizer (visemes + prosody + emotion + speaker → face motion). Manifests from
build_motion_dataset.py (QueryBook reservoir) or from 3D reconstructions of real performances."""
from _common import args, loaders

from vse.common.data import MotionDataset
from vse.common.train import train
from vse.sync.motion_synthesizer import FaceMotionSynthesizer, motion_loss

a, cfg = args({"--speaker-dim": dict(type=int, default=256)})
cfg.name = cfg.name if cfg.name != "model" else "motion"
tl, vl = loaders(MotionDataset(cfg.data.train_manifest), MotionDataset(cfg.data.val_manifest), cfg, MotionDataset.collate)
train(FaceMotionSynthesizer(cfg, a.speaker_dim), motion_loss, tl, vl, cfg, a.steps)
