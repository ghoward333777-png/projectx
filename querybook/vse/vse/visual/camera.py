"""Camera parameters. Intrinsics from the field of view (a phone's main camera is about 70° horizontally); per-frame
extrinsics are the inverse of the head pose (head moves ⇄ camera moves are indistinguishable from one face alone);
camera motion is separated from head motion by tracking the background (optional, needs OpenCV)."""
from __future__ import annotations

import math

import numpy as np

from vse.common.types import CameraParams


def intrinsics(width, height, hfov_deg=70.0) -> CameraParams:
    f = (width / 2) / math.tan(math.radians(hfov_deg) / 2)
    return CameraParams(f, f, width / 2, height / 2)


def extrinsics_from_head(transform_4x4: np.ndarray) -> CameraParams:
    inv = np.linalg.inv(transform_4x4)
    return CameraParams(1.0, 1.0, 0.0, 0.0, inv[:3, :3].tolist(), inv[:3, 3].tolist())


def background_motion(prev_gray: np.ndarray, gray: np.ndarray, face_box=None):
    """Global image shift between frames outside the face (pixels), by phase correlation (numpy only)."""
    a, b = prev_gray.astype(np.float32), gray.astype(np.float32)
    if face_box is not None:
        x0, y0, x1, y1 = (int(v) for v in face_box)
        a, b = a.copy(), b.copy()
        a[y0:y1, x0:x1] = a.mean(); b[y0:y1, x0:x1] = b.mean()
    F1, F2 = np.fft.fft2(a), np.fft.fft2(b)
    R = F1 * np.conj(F2)
    r = np.fft.ifft2(R / (np.abs(R) + 1e-9)).real
    dy, dx = np.unravel_index(np.argmax(r), r.shape)
    h, w = r.shape
    return (dx if dx <= w // 2 else dx - w), (dy if dy <= h // 2 else dy - h)
