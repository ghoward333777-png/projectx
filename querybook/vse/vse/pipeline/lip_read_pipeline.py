"""Lip reading pipeline: video file (MediaPipe landmarks → the 13 tracker numbers per frame) or QueryBook frames JSON
→ transcript, with the stage-2 reader when a checkpoint is configured, else stage 1."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from vse.common.io import load_video_frames


@dataclass
class LipReadConfig:
    language: str = "en"
    fps: int = 30
    landmark_model: Optional[str] = None


class LipReadPipeline:
    def __init__(self, cfg: LipReadConfig, stage1=None, stage2_reader=None):
        self.cfg, self.s1, self.s2 = cfg, stage1, stage2_reader

    def frames_from_video(self, path):
        from vse.visual.landmarks import LandmarkDetector, mouth_features
        frames, fps = load_video_frames(path, fps=self.cfg.fps)
        det = LandmarkDetector("mediapipe", self.cfg.landmark_model)
        out = []
        for i, fr in enumerate(frames):
            lms, bs, _ = det.detect(fr, i, int(1000 * i / fps))
            if lms is not None:
                out.append({"t": round(i / fps, 4), "face": True, "_fv": mouth_features(lms, bs, fr.shape[1], fr.shape[0])})
        return out

    def run(self, frames=None, video_path=None, words=(), script=""):
        if frames is None:
            frames = self.frames_from_video(video_path)
        if self.s2 is not None and not script:
            r = self.s2.lip_read(frames, words)
        else:
            r = self.s1.lip_read(frames, self.cfg.language, tuple(words), script)
        r["frames"] = len(frames)
        return r
