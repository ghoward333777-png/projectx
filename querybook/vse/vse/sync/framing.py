"""Turning timed segments into per-frame inputs (every model here works frame by frame at the output frame rate)."""
from __future__ import annotations

import torch

from vse.common.types import EMOTION_KEYS, PHONEMES, VISEMES, EmotionVector, PhonemeTimeline, ProsodyTimeline, VisemeSequence


def frames_of(segments, attr, vocab, fps, duration):
    n = max(1, int(round(duration * fps)))
    ids = torch.zeros(n, dtype=torch.long)
    idx = {s: i for i, s in enumerate(vocab)}
    sil = idx.get("sil", 0)
    ids[:] = sil
    for s in segments:
        a, b = int(s.start_time * fps), max(int(s.start_time * fps) + 1, int(round(s.end_time * fps)))
        ids[a:min(n, b)] = idx.get(getattr(s, attr), sil)
    return ids


def phoneme_frames(tl: PhonemeTimeline, fps, duration):
    return frames_of(tl.phonemes, "symbol", PHONEMES, fps, duration)


def viseme_frames(vs: VisemeSequence, fps, duration):
    return frames_of(vs.visemes, "id", VISEMES, fps, duration)


def prosody_frames(p: ProsodyTimeline, fps, duration):
    n = max(1, int(round(duration * fps)))
    out = torch.zeros(n, 4)
    if not p.frames:
        return out
    for i in range(n):
        f = p.frames[min(len(p.frames) - 1, int(i / fps * p.fps))]
        out[i] = torch.tensor([f.pitch / 300.0, f.energy, f.speaking_rate / 8.0, f.voicing])
    return out


def emotion_tensor(e: EmotionVector | None):
    return torch.tensor((e or EmotionVector()).as_list(), dtype=torch.float32)


def segments_from_frames(ids, vocab, fps, probs=None):
    """Per-frame ids → timed segments (consecutive equal ids merged)."""
    out, start = [], 0
    ids = ids.tolist()
    for i in range(1, len(ids) + 1):
        if i == len(ids) or ids[i] != ids[start]:
            conf = float(probs[start:i].max(-1).values.mean()) if probs is not None else 1.0
            out.append((vocab[ids[start]], start / fps, i / fps, conf))
            start = i
    return out
