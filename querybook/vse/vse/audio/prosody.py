"""Prosody at 100 frames/s: pitch by YIN (de Cheveigné & Kawahara 2002), RMS energy, voicing, speaking rate
(energy peaks per second over a 2 s window). Signal processing — nothing to train."""
from __future__ import annotations

import numpy as np

from vse.common.types import ProsodyFrame, ProsodyTimeline


def yin(x, sr, fmin=60.0, fmax=500.0, frame_hz=100, threshold=0.12):
    win = int(sr / fmin) * 2
    hop = int(sr / frame_hz)
    tau_min, tau_max = int(sr / fmax), int(sr / fmin)
    n = max(0, 1 + (len(x) - win) // hop)
    f0 = np.zeros(n, dtype=np.float32)
    conf = np.zeros(n, dtype=np.float32)
    for i in range(n):
        fr = x[i * hop: i * hop + win].astype(np.float64)
        w = win // 2
        d = np.array([np.sum((fr[:w] - fr[t:t + w]) ** 2) for t in range(tau_max + 1)])
        cmnd = np.ones_like(d)
        cs = np.cumsum(d[1:])
        cmnd[1:] = d[1:] * np.arange(1, len(d)) / np.maximum(cs, 1e-12)
        cand = np.where(cmnd[tau_min:tau_max] < threshold)[0]
        if len(cand):
            t = cand[0] + tau_min
            while t + 1 < tau_max and cmnd[t + 1] < cmnd[t]:
                t += 1
            if 1 <= t < len(cmnd) - 1:                            # parabolic interpolation
                a, b, c = cmnd[t - 1], cmnd[t], cmnd[t + 1]
                shift = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
            else:
                shift = 0.0
            f0[i] = sr / (t + shift)
            conf[i] = 1.0 - cmnd[t]
    return f0, conf


class ProsodyExtractor:
    def __init__(self, sample_rate=16000, frame_hz=100):
        self.sr, self.hz = sample_rate, frame_hz

    def extract(self, wav: np.ndarray) -> ProsodyTimeline:
        f0, conf = yin(wav, self.sr, frame_hz=self.hz)
        hop = int(self.sr / self.hz)
        n = len(f0)
        rms = np.array([np.sqrt(np.mean(wav[i * hop: i * hop + hop] ** 2) + 1e-12) for i in range(n)])
        db = 20 * np.log10(rms + 1e-9)
        lo, hi = np.percentile(db, 10) if n else -60, db.max() if n else 0
        energy = np.clip((db - lo) / max(6.0, hi - lo), 0, 1)
        # syllable-like peaks: local energy maxima at least 100 ms apart
        peaks = [i for i in range(2, n - 2) if energy[i] > 0.45 and energy[i] == energy[i - 2:i + 3].max()]
        kept = []
        for p in peaks:
            if not kept or p - kept[-1] >= self.hz // 10:
                kept.append(p)
        kept = np.array(kept)
        frames = []
        for i in range(n):
            rate = float(((kept >= i - self.hz) & (kept <= i + self.hz)).sum()) / 2.0 if len(kept) else 0.0
            frames.append(ProsodyFrame(round(i / self.hz, 3), float(f0[i]), float(round(energy[i], 3)), rate, float(conf[i] > 0.5 and f0[i] > 0)))
        return ProsodyTimeline(frames, self.hz)
