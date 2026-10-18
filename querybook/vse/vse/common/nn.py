"""Shared building blocks: Conformer encoder, convolutional subsampling, positional encoding, ArcFace head."""
from __future__ import annotations

import math

import torch
import torch.nn as nn
import torch.nn.functional as F


class PositionalEncoding(nn.Module):
    def __init__(self, dim, max_len=10000):
        super().__init__()
        pe = torch.zeros(max_len, dim)
        pos = torch.arange(max_len).unsqueeze(1)
        div = torch.exp(torch.arange(0, dim, 2) * (-math.log(10000.0) / dim))
        pe[:, 0::2] = torch.sin(pos * div)
        pe[:, 1::2] = torch.cos(pos * div)
        self.register_buffer("pe", pe, persistent=False)

    def forward(self, x):                      # x: [B, T, D]
        return x + self.pe[: x.size(1)].unsqueeze(0)


class FeedForward(nn.Module):
    def __init__(self, dim, mult=4, dropout=0.1):
        super().__init__()
        self.net = nn.Sequential(nn.LayerNorm(dim), nn.Linear(dim, dim * mult), nn.SiLU(), nn.Dropout(dropout),
                                 nn.Linear(dim * mult, dim), nn.Dropout(dropout))

    def forward(self, x):
        return self.net(x)


class ConvModule(nn.Module):
    """Conformer convolution module: pointwise → GLU → depthwise → BN → SiLU → pointwise."""

    def __init__(self, dim, kernel=15, dropout=0.1):
        super().__init__()
        self.norm = nn.LayerNorm(dim)
        self.pw1 = nn.Conv1d(dim, 2 * dim, 1)
        self.dw = nn.Conv1d(dim, dim, kernel, padding=kernel // 2, groups=dim)
        self.bn = nn.BatchNorm1d(dim)
        self.pw2 = nn.Conv1d(dim, dim, 1)
        self.drop = nn.Dropout(dropout)

    def forward(self, x, mask=None):           # x: [B, T, D]; mask: [B, T] True = padding
        y = self.norm(x)
        if mask is not None:
            y = y.masked_fill(mask.unsqueeze(-1), 0.0)
        y = F.glu(self.pw1(y.transpose(1, 2)), dim=1)
        y = self.pw2(F.silu(self.bn(self.dw(y))))
        return self.drop(y.transpose(1, 2))


class ConformerBlock(nn.Module):
    def __init__(self, dim, heads, ff_mult=4, kernel=15, dropout=0.1):
        super().__init__()
        self.ff1 = FeedForward(dim, ff_mult, dropout)
        self.attn_norm = nn.LayerNorm(dim)
        self.attn = nn.MultiheadAttention(dim, heads, dropout=dropout, batch_first=True)
        self.conv = ConvModule(dim, kernel, dropout)
        self.ff2 = FeedForward(dim, ff_mult, dropout)
        self.out_norm = nn.LayerNorm(dim)

    def forward(self, x, mask=None):
        x = x + 0.5 * self.ff1(x)
        y = self.attn_norm(x)
        y, _ = self.attn(y, y, y, key_padding_mask=mask, need_weights=False)
        x = x + y
        x = x + self.conv(x, mask)
        x = x + 0.5 * self.ff2(x)
        return self.out_norm(x)


class ConformerEncoder(nn.Module):
    def __init__(self, in_dim, dim, layers, heads, ff_mult=4, kernel=15, dropout=0.1):
        super().__init__()
        self.proj = nn.Linear(in_dim, dim)
        self.pos = PositionalEncoding(dim)
        self.blocks = nn.ModuleList([ConformerBlock(dim, heads, ff_mult, kernel, dropout) for _ in range(layers)])

    def forward(self, x, mask=None):           # x: [B, T, in_dim] → [B, T, dim]
        x = self.pos(self.proj(x))
        for b in self.blocks:
            x = b(x, mask)
        return x


class Subsample2(nn.Module):
    """Two stride-2 convolutions over time and frequency: [B, T, F] → [B, T/4, D]."""

    def __init__(self, n_mels, dim):
        super().__init__()
        self.conv = nn.Sequential(nn.Conv2d(1, dim, 3, 2, 1), nn.SiLU(), nn.Conv2d(dim, dim, 3, 2, 1), nn.SiLU())
        self.out = nn.Linear(dim * ((n_mels + 3) // 4), dim)
        self.factor = 4

    def forward(self, x):
        y = self.conv(x.unsqueeze(1))              # [B, D, T/4, F/4]
        b, d, t, f = y.shape
        return self.out(y.permute(0, 2, 1, 3).reshape(b, t, d * f))

    def lengths(self, n):
        for _ in range(2):
            n = (n + 1) // 2
        return n


class ArcFace(nn.Module):
    """Additive angular margin softmax head (speaker and face identity training)."""

    def __init__(self, dim, classes, s=30.0, m=0.2):
        super().__init__()
        self.W = nn.Parameter(torch.randn(classes, dim) * 0.01)
        self.s, self.m = s, m

    def forward(self, emb, labels):
        cos = F.linear(F.normalize(emb), F.normalize(self.W)).clamp(-1 + 1e-7, 1 - 1e-7)
        theta = torch.acos(cos)
        target = torch.cos(theta + self.m)
        onehot = F.one_hot(labels, cos.size(1)).bool()
        logits = torch.where(onehot, target, cos) * self.s
        return F.cross_entropy(logits, labels)


def lengths_to_mask(lengths, max_len=None):
    max_len = max_len or int(lengths.max())
    return torch.arange(max_len, device=lengths.device).unsqueeze(0) >= lengths.unsqueeze(1)
