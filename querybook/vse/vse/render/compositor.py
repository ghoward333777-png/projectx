"""Compositing a rendered face region back into the original frame: colour matching (mean/std per channel in the
face region), a feathered mask, alpha blending. Background, hair and everything outside the mask are untouched."""
from __future__ import annotations

import numpy as np


def feather(mask: np.ndarray, radius=8) -> np.ndarray:
    m = mask.astype(np.float32)
    if radius <= 0:
        return m
    k = np.ones(2 * radius + 1, dtype=np.float32) / (2 * radius + 1)
    for axis in (0, 1):
        m = np.apply_along_axis(lambda r: np.convolve(r, k, mode="same"), axis, m)
    return np.clip(m, 0, 1)


def match_colour(src: np.ndarray, ref: np.ndarray, mask: np.ndarray) -> np.ndarray:
    s, r = src.astype(np.float32), ref.astype(np.float32)
    sel = mask > 0.5
    if sel.sum() < 10:
        return s
    out = s.copy()
    for c in range(3):
        sm, ss = s[..., c][sel].mean(), s[..., c][sel].std() + 1e-6
        rm, rs = r[..., c][sel].mean(), r[..., c][sel].std() + 1e-6
        out[..., c] = (s[..., c] - sm) * (rs / ss) + rm
    return out


class FaceCompositor:
    def __init__(self, feather_px=8, colour_match=True):
        self.feather_px, self.colour = feather_px, colour_match

    def compose_one(self, frame, rendered, mask):
        """frame, rendered: uint8 [H, W, 3]; mask: [H, W] 0..1 where the rendered face replaces the frame."""
        m = feather(mask, self.feather_px)[..., None]
        r = match_colour(rendered, frame, mask) if self.colour else rendered.astype(np.float32)
        return np.clip(m * r + (1 - m) * frame.astype(np.float32), 0, 255).astype(np.uint8)

    def compose(self, frames, rendered, masks):
        return [f if r is None else self.compose_one(f, r, m) for f, r, m in zip(frames, rendered, masks)]
