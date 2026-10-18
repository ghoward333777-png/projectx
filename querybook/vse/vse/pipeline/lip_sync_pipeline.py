"""Lip sync pipeline (audio → face motion → optional rendered video).

Each stage uses a trained stage-2 model when its checkpoint is configured, else falls back to the stage-1 engine
(QueryBook's apps/language/vse.py), so the pipeline always runs end to end and every result says which engine
produced each part. Rendering a real person's face needs `consent=True`; rendered videos are tagged synthetic."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from vse.common.io import load_wav
from vse.common.types import EmotionVector, PhonemeSegment, PhonemeTimeline, ProsodyFrame, ProsodyTimeline


@dataclass
class LipSyncConfig:
    fps: int = 30
    language: str = "en"
    stage1_apps_dir: Optional[str] = None
    checkpoints: dict = field(default_factory=dict)       # e.g. {"motion": "ckpt/motion.best.pt", "asr": ...}
    device: str = "cpu"


class LipSyncPipeline:
    def __init__(self, cfg: LipSyncConfig, stage1=None, motion_model=None, asr=None, p2v=None):
        self.cfg, self.s1 = cfg, stage1
        self.motion_model, self.asr, self.p2v = motion_model, asr, p2v

    def run(self, audio, text, word_times=None):
        """audio: path or WAV bytes; text: the words spoken. → {"engine": {...}, "phonemes", "visemes", "motion", ...}."""
        wav_bytes = audio if isinstance(audio, (bytes, bytearray)) else open(audio, "rb").read()
        engines = {}
        if self.s1 is None:
            raise RuntimeError("stage 1 (QueryBook apps directory) is needed for alignment and fallbacks")
        a = self.s1.aps(wav_bytes, text, self.cfg.language, None, word_times)
        engines["audio"] = "stage 1"
        if self.asr is not None:
            tl = self.asr.extract(load_wav(wav_bytes))
            engines["phonemes"] = "stage 2 ASR"
        else:
            tl = PhonemeTimeline([PhonemeSegment(p["symbol"], p["start_time"], p["end_time"], p["confidence"], p["viseme"]) for p in a["phonemes"]["phonemes"]])
            engines["phonemes"] = "stage 1 (pronunciation + forced alignment)"
        pros = ProsodyTimeline([ProsodyFrame(f["time"], f["pitch"], f["energy"], f["speaking_rate"], f["voicing"]) for f in a["prosody"]["frames"]])
        emo = EmotionVector(**{k: a["emotion"][k] for k in EmotionVector().__dict__})
        if self.motion_model is not None:
            from vse.sync.phoneme_to_viseme import rule_visemes
            vis = self.p2v.generate(tl, pros, emo, a["duration"]) if self.p2v is not None else rule_visemes(tl)
            motion = self.motion_model.generate(vis, pros, emo, a["speaker_embedding"], a["duration"]).to_json()
            engines["motion"] = "stage 2 FaceMotionSynthesizer"
            visemes = vis.to_json()
        else:
            ls = self.s1.lip_sync(a["track"], a["prosody"], a["emotion"], fps=self.cfg.fps, seed=text)
            motion, visemes = ls["motion"], ls["viseme_sequence"]
            engines["motion"] = "stage 1 (dominance-model coarticulation)"
        return {"engine": engines, "phonemes": tl.to_json(), "visemes": visemes, "motion": motion, "emotion": a["emotion"],
                "speaker_embedding": a["speaker_embedding"], "duration": a["duration"]}

    def render(self, frames, motion, renderer, compositor, masks, consent=False):
        """Render the face region per frame and composite it. Refuses without consent."""
        if not consent:
            raise PermissionError("Rendering a real person's face needs their consent (consent=True).")
        rendered = [renderer(f, m) for f, m in zip(frames, motion["frames"])]
        return compositor.compose(frames, rendered, masks)
