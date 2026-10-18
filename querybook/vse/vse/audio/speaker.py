"""Speaker encoder (ECAPA-TDNN style): SE-Res2 blocks, attentive statistics pooling, unit-length embedding.
Trained with an additive-margin (ArcFace) head over speaker identities."""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from vse.common.config import TrainConfig
from vse.common.nn import ArcFace


class SEBlock(nn.Module):
    def __init__(self, ch, r=8):
        super().__init__()
        self.fc = nn.Sequential(nn.Linear(ch, ch // r), nn.ReLU(), nn.Linear(ch // r, ch), nn.Sigmoid())

    def forward(self, x):                                  # [B, C, T]
        return x * self.fc(x.mean(-1)).unsqueeze(-1)


class SERes2Block(nn.Module):
    def __init__(self, ch, kernel, dilation, scale=4):
        super().__init__()
        self.scale = scale
        w = ch // scale
        self.convs = nn.ModuleList([nn.Sequential(nn.Conv1d(w, w, kernel, dilation=dilation, padding=dilation * (kernel // 2)),
                                                  nn.BatchNorm1d(w), nn.ReLU()) for _ in range(scale - 1)])
        self.inp = nn.Sequential(nn.Conv1d(ch, ch, 1), nn.BatchNorm1d(ch), nn.ReLU())
        self.out = nn.Sequential(nn.Conv1d(ch, ch, 1), nn.BatchNorm1d(ch), nn.ReLU())
        self.se = SEBlock(ch)

    def forward(self, x):
        y = self.inp(x)
        parts = torch.chunk(y, self.scale, dim=1)
        outs, prev = [parts[0]], None
        for i, conv in enumerate(self.convs):
            z = parts[i + 1] if prev is None else parts[i + 1] + prev
            prev = conv(z)
            outs.append(prev)
        return x + self.se(self.out(torch.cat(outs, 1)))


class AttentiveStatsPool(nn.Module):
    def __init__(self, ch, hidden=128):
        super().__init__()
        self.att = nn.Sequential(nn.Conv1d(ch, hidden, 1), nn.Tanh(), nn.Conv1d(hidden, ch, 1))

    def forward(self, x):
        w = torch.softmax(self.att(x), dim=-1)
        mean = (x * w).sum(-1)
        std = torch.sqrt(((x ** 2) * w).sum(-1) - mean ** 2 + 1e-6)
        return torch.cat([mean, std], 1)


class SpeakerEncoder(nn.Module):
    def __init__(self, cfg: TrainConfig, n_speakers=0):
        super().__init__()
        ch = max(64, cfg.model.dim * 2)
        ch -= ch % 4
        self.front = nn.Sequential(nn.Conv1d(cfg.data.n_mels, ch, 5, padding=2), nn.BatchNorm1d(ch), nn.ReLU())
        self.blocks = nn.ModuleList([SERes2Block(ch, 3, d) for d in (2, 3, 4)])
        self.mfa = nn.Sequential(nn.Conv1d(ch * 3, ch * 3, 1), nn.ReLU())
        self.pool = AttentiveStatsPool(ch * 3)
        self.fc = nn.Linear(ch * 6, cfg.model.embedding_dim)
        self.arc = ArcFace(cfg.model.embedding_dim, n_speakers) if n_speakers else None

    def forward(self, mel):                                # [B, T, n_mels] → [B, E] unit length
        x = self.front(mel.transpose(1, 2))
        outs = []
        for b in self.blocks:
            x = b(x)
            outs.append(x)
        x = self.mfa(torch.cat(outs, 1))
        return F.normalize(self.fc(self.pool(x)), dim=-1)


def speaker_loss(model, batch, device):
    mel, labels = (b.to(device) for b in batch)
    return model.arc(model(mel), labels), {}
