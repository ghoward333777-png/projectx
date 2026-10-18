"""Option A — conditional NeRF for the face region: an MLP maps a 3D point (positional-encoded) plus a condition
(identity, expression, lighting) to colour and density; pixels are rendered by volume integration along camera
rays. Train per identity on multi-view or monocular video with known camera and expression parameters."""
from __future__ import annotations

import math

import torch
import torch.nn as nn


def posenc(x, n_freq=6):
    out = [x]
    for k in range(n_freq):
        out += [torch.sin((2 ** k) * math.pi * x), torch.cos((2 ** k) * math.pi * x)]
    return torch.cat(out, -1)


class ConditionalFaceNeRF(nn.Module):
    def __init__(self, cond_dim, width=128, depth=6, n_freq=6):
        super().__init__()
        self.n_freq = n_freq
        in_dim = 3 * (1 + 2 * n_freq) + cond_dim
        layers, d = [], in_dim
        for _ in range(depth):
            layers += [nn.Linear(d, width), nn.ReLU()]
            d = width
        self.mlp = nn.Sequential(*layers)
        self.sigma = nn.Linear(width, 1)
        self.rgb = nn.Sequential(nn.Linear(width + 3 * (1 + 2 * 4), width // 2), nn.ReLU(), nn.Linear(width // 2, 3), nn.Sigmoid())

    def forward(self, pts, dirs, cond):            # pts, dirs [N, S, 3]; cond [C] or [N, C]
        n, s, _ = pts.shape
        c = cond.view(1, 1, -1).expand(n, s, -1) if cond.dim() == 1 else cond.unsqueeze(1).expand(n, s, -1)
        h = self.mlp(torch.cat([posenc(pts, self.n_freq), c], -1))
        return self.rgb(torch.cat([h, posenc(dirs, 4)], -1)), torch.relu(self.sigma(h)).squeeze(-1)


def render_rays(model, origins, dirs, cond, near=0.5, far=2.0, samples=48, perturb=False):
    """Volume rendering: origins, dirs [N, 3] → rgb [N, 3], depth [N], opacity [N]."""
    t = torch.linspace(near, far, samples, device=origins.device).expand(origins.size(0), samples)
    if perturb:
        t = t + (torch.rand_like(t) - 0.5) * (far - near) / samples
    pts = origins.unsqueeze(1) + dirs.unsqueeze(1) * t.unsqueeze(-1)
    rgb, sigma = model(pts, dirs.unsqueeze(1).expand_as(pts), cond)
    delta = torch.cat([t[:, 1:] - t[:, :-1], torch.full_like(t[:, :1], 1e10)], -1)
    alpha = 1 - torch.exp(-sigma * delta)
    trans = torch.cumprod(torch.cat([torch.ones_like(alpha[:, :1]), 1 - alpha + 1e-10], -1), -1)[:, :-1]
    w = alpha * trans
    return (w.unsqueeze(-1) * rgb).sum(1), (w * t).sum(1), w.sum(1)


def camera_rays(h, w, focal, c2w):
    """Pinhole rays for an H×W image; c2w [3, 4] camera-to-world."""
    j, i = torch.meshgrid(torch.arange(h, dtype=torch.float32), torch.arange(w, dtype=torch.float32), indexing="ij")
    d = torch.stack([(i - w / 2) / focal, -(j - h / 2) / focal, -torch.ones_like(i)], -1)
    dirs = (d.view(-1, 1, 3) * c2w[:3, :3]).sum(-1)
    dirs = dirs / dirs.norm(dim=-1, keepdim=True)
    return c2w[:3, 3].expand_as(dirs), dirs


class NeRFFaceRenderer:
    def __init__(self, model: ConditionalFaceNeRF, focal, size=128, chunk=4096):
        self.m, self.focal, self.size, self.chunk = model.eval(), focal, size, chunk

    @torch.no_grad()
    def render(self, c2w, cond):
        o, d = camera_rays(self.size, self.size, self.focal, c2w)
        rgb, _, acc = [], [], []
        for k in range(0, o.size(0), self.chunk):
            r, _, a = render_rays(self.m, o[k:k + self.chunk], d[k:k + self.chunk], cond)
            rgb.append(r); acc.append(a)
        img = torch.cat(rgb).view(self.size, self.size, 3)
        return (img.clamp(0, 1) * 255).byte().numpy(), torch.cat(acc).view(self.size, self.size).numpy()
