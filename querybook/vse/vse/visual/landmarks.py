"""Face landmarks and boxes. Backends: MediaPipe Face Landmarker (optional dependency, 478 points + blendshapes +
transformation matrix — the same tracker QueryBook's browser uses) or landmarks supplied as JSON."""
from __future__ import annotations

import numpy as np

from vse.common.types import FaceBox, LandmarkSet

# MediaPipe indices used across the package
MOUTH_L, MOUTH_R, LIP_TOP, LIP_BOT = 61, 291, 13, 14
EYE_OUTER_L, EYE_OUTER_R = 33, 263
MOUTH_RING = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]


class LandmarkDetector:
    def __init__(self, backend="mediapipe", model_path=None):
        self.backend = backend
        self._lm = None
        if backend == "mediapipe":
            try:
                import mediapipe as mp                     # optional
                from mediapipe.tasks.python import vision
                from mediapipe.tasks.python.core.base_options import BaseOptions
            except ImportError as e:
                raise RuntimeError("pip install mediapipe (or use backend='json')") from e
            opts = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=model_path or "face_landmarker.task"),
                                                output_face_blendshapes=True, output_facial_transformation_matrixes=True,
                                                running_mode=vision.RunningMode.VIDEO, num_faces=1)
            self._mp, self._lm = mp, vision.FaceLandmarker.create_from_options(opts)

    def detect(self, frame: np.ndarray, frame_index: int, timestamp_ms: int):
        """RGB frame → (LandmarkSet | None, blendshapes {name: score}, 4x4 transform | None)."""
        img = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=frame)
        res = self._lm.detect_for_video(img, timestamp_ms)
        if not res.face_landmarks:
            return None, {}, None
        lms = [(p.x, p.y, p.z) for p in res.face_landmarks[0]]
        bs = {c.category_name: c.score for c in res.face_blendshapes[0]} if res.face_blendshapes else {}
        mat = np.array(res.facial_transformation_matrixes[0]).reshape(4, 4) if res.facial_transformation_matrixes else None
        return LandmarkSet("face_0", frame_index, lms), bs, mat


def box_from_landmarks(lms: LandmarkSet, w: int, h: int, margin=0.1) -> FaceBox:
    a = np.array(lms.landmarks)[:, :2]
    x0, y0 = a.min(0); x1, y1 = a.max(0)
    mx, my = (x1 - x0) * margin, (y1 - y0) * margin
    return FaceBox(lms.frame_index, lms.face_id, ((x0 - mx) * w, (y0 - my) * h, (x1 + mx) * w, (y1 + my) * h))


def mouth_crop(frame: np.ndarray, lms: LandmarkSet, size=88, scale=1.8):
    """A square crop centred on the mouth, sized to the mouth width (the input of the visual front-end)."""
    h, w = frame.shape[:2]
    p = np.array(lms.landmarks)[:, :2] * [w, h]
    c = p[MOUTH_RING].mean(0)
    half = max(8.0, np.linalg.norm(p[MOUTH_L] - p[MOUTH_R]) * scale / 2)
    ys = np.clip(np.linspace(c[1] - half, c[1] + half, size).astype(int), 0, h - 1)
    xs = np.clip(np.linspace(c[0] - half, c[0] + half, size).astype(int), 0, w - 1)
    return frame[ys][:, xs]


def mouth_features(lms: LandmarkSet, blendshapes: dict, w: int, h: int):
    """The 13 numbers QueryBook's tracker sends per frame (types.MOUTH_PARAMS order)."""
    p = np.array(lms.landmarks)[:, :2] * [w, h]
    mw = np.linalg.norm(p[MOUTH_L] - p[MOUTH_R]) or 1.0
    g = lambda k: float(blendshapes.get(k, 0.0))
    avg = lambda k: (g(k + "Left") + g(k + "Right")) / 2
    return [float(np.linalg.norm(p[LIP_TOP] - p[LIP_BOT]) / mw), g("jawOpen"), g("mouthClose"), avg("mouthPress"), g("mouthRollLower"),
            g("mouthRollUpper"), g("mouthFunnel"), g("mouthPucker"), avg("mouthStretch"), avg("mouthSmile"), avg("mouthUpperUp"),
            avg("mouthLowerDown"), g("mouthShrugLower")]
