"""Shared data structures. Field names and JSON shapes match QueryBook's stage-1 engine (apps/language/vse.py)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

# The 13 mouth features measured by QueryBook's browser tracker (lip gap ÷ mouth width + 12 MediaPipe/ARKit
# blendshapes, left/right averaged). Synthesis and measurement share this space.
MOUTH_PARAMS = ["gap", "jawOpen", "mouthClose", "press", "mouthRollLower", "mouthRollUpper", "mouthFunnel", "mouthPucker",
                "stretch", "smile", "upperUp", "lowerDown", "mouthShrugLower"]
VISEMES = ["sil", "PP", "FF", "TH", "DD", "kk", "CH", "SS", "nn", "RR", "aa", "E", "I", "O", "U"]
EMOTION_KEYS = ["valence", "arousal", "dominance", "anger", "joy", "sadness", "fear", "surprise"]
# ARPAbet-style phoneme set (+ blank for CTC at index 0). Used by the trainable ASR/lip-reading heads.
PHONEMES = ["<blank>", "sil", "AA", "AE", "AH", "AO", "AW", "AY", "B", "CH", "D", "DH", "EH", "ER", "EY", "F", "G", "HH", "IH", "IY",
            "JH", "K", "L", "M", "N", "NG", "OW", "OY", "P", "R", "S", "SH", "T", "TH", "UH", "UW", "V", "W", "Y", "Z", "ZH"]
PHONEME_TO_VISEME = {"sil": "sil", "AA": "aa", "AE": "aa", "AH": "aa", "AO": "O", "AW": "aa", "AY": "aa", "B": "PP", "CH": "CH",
                     "D": "DD", "DH": "TH", "EH": "E", "ER": "RR", "EY": "E", "F": "FF", "G": "kk", "HH": "kk", "IH": "I", "IY": "I",
                     "JH": "CH", "K": "kk", "L": "nn", "M": "PP", "N": "nn", "NG": "kk", "OW": "O", "OY": "O", "P": "PP", "R": "RR",
                     "S": "SS", "SH": "CH", "T": "DD", "TH": "TH", "UH": "U", "UW": "U", "V": "FF", "W": "U", "Y": "I", "Z": "SS", "ZH": "CH"}


@dataclass
class PhonemeSegment:
    symbol: str
    start_time: float
    end_time: float
    confidence: float = 1.0
    viseme: Optional[str] = None


@dataclass
class PhonemeTimeline:
    phonemes: list[PhonemeSegment] = field(default_factory=list)

    def to_json(self):
        return {"phonemes": [asdict(p) for p in self.phonemes]}


@dataclass
class ProsodyFrame:
    time: float
    pitch: float
    energy: float
    speaking_rate: float
    voicing: float


@dataclass
class ProsodyTimeline:
    frames: list[ProsodyFrame] = field(default_factory=list)
    fps: int = 100

    def as_matrix(self):
        return [[f.pitch, f.energy, f.speaking_rate, f.voicing] for f in self.frames]


@dataclass
class EmotionVector:
    valence: float = 0.5
    arousal: float = 0.45
    dominance: float = 0.5
    anger: float = 0.0
    joy: float = 0.0
    sadness: float = 0.0
    fear: float = 0.0
    surprise: float = 0.0

    def as_list(self):
        return [getattr(self, k) for k in EMOTION_KEYS]

    @classmethod
    def from_list(cls, v):
        return cls(**{k: float(x) for k, x in zip(EMOTION_KEYS, v)})


@dataclass
class VisemeSegment:
    id: str
    start_time: float
    end_time: float
    intensity: float = 1.0
    coarticulation_left: float = 0.0
    coarticulation_right: float = 0.0


@dataclass
class VisemeSequence:
    visemes: list[VisemeSegment] = field(default_factory=list)

    def to_json(self):
        return {"visemes": [asdict(v) for v in self.visemes]}


@dataclass
class FaceMotionFrame:
    time: float
    mouth: list[float]                 # MOUTH_PARAMS order
    jaw_rotation_deg: float = 0.0
    head_pose_deg: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    eye_gaze: list[float] = field(default_factory=lambda: [0.0, 0.0])
    blink: float = 0.0
    brows: list[float] = field(default_factory=lambda: [0.0, 0.0])


@dataclass
class FaceMotionTimeline:
    fps: int
    frames: list[FaceMotionFrame] = field(default_factory=list)
    params: list[str] = field(default_factory=lambda: list(MOUTH_PARAMS))

    def to_json(self):
        return {"fps": self.fps, "params": self.params, "frames": [asdict(f) for f in self.frames]}


@dataclass
class FaceBox:
    frame_index: int
    id: str
    bbox: tuple[float, float, float, float]
    confidence: float = 1.0


@dataclass
class LandmarkSet:
    face_id: str
    frame_index: int
    landmarks: list[tuple[float, float, float]]     # normalized x, y and relative depth z (MediaPipe convention)


@dataclass
class CameraParams:
    fx: float
    fy: float
    cx: float
    cy: float
    R: list[list[float]] = field(default_factory=lambda: [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    t: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
