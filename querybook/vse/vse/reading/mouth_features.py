"""Visual front-ends for lip reading.

  VideoFrontEnd   mouth crops [B, T, 1, H, W] → [B, T, D]: a 3D convolution over time (lips move across frames)
                  then a ResNet over each frame, the standard design for LRS2/LRS3-class lip readers.
  FeatureFrontEnd the 13 tracker numbers per frame [B, T, 13] → [B, T, D] (plus their velocities). This one trains
                  on QueryBook's ingestion reservoir, which stores numbers only — never pictures."""
from __future__ import annotations

import torch
import torch.nn as nn

from vse.visual.identity import ResNetLite


class VideoFrontEnd(nn.Module):
    def __init__(self, dim=256, width=32):
        super().__init__()
        self.conv3d = nn.Sequential(nn.Conv3d(1, width, (5, 7, 7), (1, 2, 2), (2, 3, 3), bias=False), nn.BatchNorm3d(width), nn.ReLU(),
                                    nn.MaxPool3d((1, 3, 3), (1, 2, 2), (0, 1, 1)))
        self.trunk = ResNetLite(width, in_ch=width)
        self.proj = nn.Linear(self.trunk.out_dim, dim)

    def forward(self, crops):                  # [B, T, 1, H, W] (grey, 0..1)
        b, t = crops.shape[:2]
        x = self.conv3d(crops.transpose(1, 2))                  # [B, C, T, H', W']
        x = x.transpose(1, 2).reshape(b * t, *x.shape[1:2], *x.shape[3:])
        return self.proj(self.trunk(x)).view(b, t, -1)


class FeatureFrontEnd(nn.Module):
    def __init__(self, n_features=13, dim=256):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(2 * n_features, dim), nn.LayerNorm(dim), nn.SiLU(), nn.Linear(dim, dim))

    def forward(self, feats):                  # [B, T, F]
        vel = torch.cat([torch.zeros_like(feats[:, :1]), feats[:, 1:] - feats[:, :-1]], 1)
        return self.net(torch.cat([feats, vel], -1))
