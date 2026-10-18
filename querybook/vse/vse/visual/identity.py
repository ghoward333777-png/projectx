"""Visual identity encoder: a small ResNet over aligned face crops → unit-length embedding, trained with ArcFace.
Use only with consent (see README: datasets such as MS-Celeb-1M and VGGFace2 were withdrawn by their creators)."""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from vse.common.nn import ArcFace


class BasicBlock(nn.Module):
    def __init__(self, a, b, stride):
        super().__init__()
        self.c1, self.b1 = nn.Conv2d(a, b, 3, stride, 1, bias=False), nn.BatchNorm2d(b)
        self.c2, self.b2 = nn.Conv2d(b, b, 3, 1, 1, bias=False), nn.BatchNorm2d(b)
        self.skip = nn.Sequential() if stride == 1 and a == b else nn.Sequential(nn.Conv2d(a, b, 1, stride, bias=False), nn.BatchNorm2d(b))

    def forward(self, x):
        return F.relu(self.b2(self.c2(F.relu(self.b1(self.c1(x))))) + self.skip(x))


class ResNetLite(nn.Module):
    def __init__(self, width=32, in_ch=3):
        super().__init__()
        self.stem = nn.Sequential(nn.Conv2d(in_ch, width, 3, 1, 1, bias=False), nn.BatchNorm2d(width), nn.ReLU())
        chans = [width, width * 2, width * 4, width * 8]
        layers, prev = [], width
        for i, c in enumerate(chans):
            layers += [BasicBlock(prev, c, 1 if i == 0 else 2), BasicBlock(c, c, 1)]
            prev = c
        self.layers = nn.Sequential(*layers)
        self.out_dim = prev

    def forward(self, x):
        return F.adaptive_avg_pool2d(self.layers(self.stem(x)), 1).flatten(1)


class IdentityEncoder(nn.Module):
    def __init__(self, embedding_dim=512, width=32, n_ids=0):
        super().__init__()
        self.backbone = ResNetLite(width)
        self.fc = nn.Linear(self.backbone.out_dim, embedding_dim)
        self.arc = ArcFace(embedding_dim, n_ids) if n_ids else None

    def forward(self, crop):                       # [B, 3, H, W] → [B, E]
        return F.normalize(self.fc(self.backbone(crop)), dim=-1)


def identity_loss(model, batch, device):
    crops, labels = (b.to(device) for b in batch)
    return model.arc(model(crops), labels), {}
