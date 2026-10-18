"""Emotion classifier: Transformer over log-mel + prosody → 8 numbers (valence, arousal, dominance as regression;
anger, joy, sadness, fear, surprise as multi-label probabilities)."""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from vse.common.config import TrainConfig
from vse.common.nn import PositionalEncoding
from vse.common.types import EmotionVector


class EmotionNet(nn.Module):
    def __init__(self, cfg: TrainConfig, prosody_dim=4):
        super().__init__()
        m = cfg.model
        self.inp = nn.Linear(cfg.data.n_mels + prosody_dim, m.dim)
        self.pos = PositionalEncoding(m.dim)
        layer = nn.TransformerEncoderLayer(m.dim, m.heads, m.dim * m.ff_mult, m.dropout, batch_first=True)
        self.encoder = nn.TransformerEncoder(layer, m.layers)
        self.head = nn.Linear(m.dim, 8)

    def forward(self, mel, prosody, mask=None):            # [B, T, n_mels], [B, T, 4] → [B, 8]
        h = self.encoder(self.pos(self.inp(torch.cat([mel, prosody], -1))), src_key_padding_mask=mask)
        if mask is not None:
            h = h.masked_fill(mask.unsqueeze(-1), 0.0)
            pooled = h.sum(1) / (~mask).sum(1, keepdim=True).clamp(min=1)
        else:
            pooled = h.mean(1)
        out = self.head(pooled)
        return torch.cat([torch.sigmoid(out[:, :3]), out[:, 3:]], -1)     # VAD in 0..1, logits for categories


def emotion_loss(model, batch, device):
    mel, pros, vad, cats = (b.to(device) for b in batch)
    out = model(mel, pros)
    l_vad = F.mse_loss(out[:, :3], vad)
    l_cat = F.binary_cross_entropy_with_logits(out[:, 3:], cats)
    return l_vad + l_cat, {"vad_mse": float(l_vad), "cat_bce": float(l_cat)}


def to_vector(out) -> EmotionVector:
    v = out.detach().cpu().tolist()
    return EmotionVector.from_list(v[:3] + [float(torch.sigmoid(torch.tensor(x))) for x in v[3:]])
