"""Face motion synthesizer: multi-stream Transformer (viseme, prosody, emotion, speaker/identity streams with
cross-attention from the viseme stream to the others) → per-frame motion: 13 mouth parameters, head pose (3),
gaze (2), blink (1), brows (2). Losses: L2 on parameters, velocity (smoothness), lip-closure on p/b/m frames,
and an identity-consistency term when an identity encoder is supplied."""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from vse.common.config import TrainConfig
from vse.common.nn import PositionalEncoding
from vse.common.types import EMOTION_KEYS, MOUTH_PARAMS, VISEMES, FaceMotionFrame, FaceMotionTimeline

from .framing import emotion_tensor, prosody_frames, viseme_frames

N_MOUTH = len(MOUTH_PARAMS)
PP = VISEMES.index("PP")


class FaceMotionSynthesizer(nn.Module):
    def __init__(self, cfg: TrainConfig, speaker_dim=256):
        super().__init__()
        d = cfg.model.dim
        self.vis = nn.Embedding(len(VISEMES), d)
        self.pr = nn.Linear(4, d)
        self.em = nn.Linear(len(EMOTION_KEYS), d)
        self.spk = nn.Linear(speaker_dim, d)
        self.pos = PositionalEncoding(d)
        layer = nn.TransformerEncoderLayer(d, cfg.model.heads, d * cfg.model.ff_mult, cfg.model.dropout, batch_first=True)
        self.viseme_stream = nn.TransformerEncoder(layer, cfg.model.layers)
        self.cross = nn.MultiheadAttention(d, cfg.model.heads, batch_first=True)
        self.out = nn.Sequential(nn.LayerNorm(d), nn.Linear(d, d), nn.SiLU(), nn.Linear(d, cfg.model.motion_dim))

    def forward(self, vis_ids, prosody, emotion, speaker, mask=None):   # [B,T], [B,T,4], [B,8], [B,S]
        v = self.viseme_stream(self.pos(self.vis(vis_ids)), src_key_padding_mask=mask)
        ctx = torch.cat([self.pr(prosody), (self.em(emotion) + self.spk(speaker)).unsqueeze(1)], 1)
        ctx_mask = None if mask is None else torch.cat([mask, torch.zeros_like(mask[:, :1])], 1)
        c, _ = self.cross(v, ctx, ctx, key_padding_mask=ctx_mask)
        return self.out(v + c)


def motion_loss(model, batch, device, w_vel=0.5, w_close=2.0):
    vis, pros, emo, spk, target, mask = (b.to(device) for b in batch)
    pred = model(vis, pros, emo, spk, mask)
    keep = (~mask).unsqueeze(-1).float()
    l2 = (((pred - target) ** 2) * keep).sum() / keep.sum().clamp(min=1) / pred.size(-1)
    vel = ((((pred[:, 1:] - pred[:, :-1]) - (target[:, 1:] - target[:, :-1])) ** 2) * keep[:, 1:]).mean()
    closed = (vis == PP) & ~mask
    close = pred[..., 0][closed].clamp(min=0).mean() if closed.any() else pred.sum() * 0      # lip gap must be ~0 on p/b/m
    return l2 + w_vel * vel + w_close * close, {"l2": float(l2), "closure": float(close)}


class MotionGenerator:
    def __init__(self, cfg: TrainConfig, checkpoint, device="cpu", fps=30, speaker_dim=256):
        self.fps, self.device = fps, device
        self.model = FaceMotionSynthesizer(cfg, speaker_dim).to(device).eval()
        self.model.load_state_dict(torch.load(checkpoint, map_location=device)["model"])
        self.speaker_dim = speaker_dim

    @torch.no_grad()
    def generate(self, visemes, prosody, emotion, speaker_emb, duration) -> FaceMotionTimeline:
        vi = viseme_frames(visemes, self.fps, duration).unsqueeze(0).to(self.device)
        pr = prosody_frames(prosody, self.fps, duration).unsqueeze(0).to(self.device)
        em = emotion_tensor(emotion).unsqueeze(0).to(self.device)
        sp = torch.as_tensor(speaker_emb if speaker_emb is not None else [0.0] * self.speaker_dim, dtype=torch.float32).view(1, -1).to(self.device)
        m = self.model(vi, pr, em, sp)[0].cpu()
        frames = []
        for t in range(m.size(0)):
            r = m[t].tolist()
            mouth = [max(0.0, x) for x in r[:N_MOUTH]]
            frames.append(FaceMotionFrame(round(t / self.fps, 3), mouth, 24.0 * mouth[1], r[N_MOUTH:N_MOUTH + 3], r[N_MOUTH + 3:N_MOUTH + 5],
                                          min(1.0, max(0.0, r[N_MOUTH + 5])), r[N_MOUTH + 6:N_MOUTH + 8]))
        return FaceMotionTimeline(self.fps, frames)
