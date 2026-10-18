"""Option B — diffusion inpainting of the face region: a small conditional U-Net denoises the masked mouth/lower-face
area, conditioned on the original frame (outside the mask), a rendering of the target mesh, and an embedding
(identity + lighting). DDPM schedule; sampling keeps the known pixels outside the mask at every step."""
from __future__ import annotations

import math

import torch
import torch.nn as nn
import torch.nn.functional as F


def timestep_embedding(t, dim):
    half = dim // 2
    f = torch.exp(-math.log(10000) * torch.arange(half, device=t.device) / half)
    a = t.float().unsqueeze(1) * f.unsqueeze(0)
    return torch.cat([torch.sin(a), torch.cos(a)], 1)


class ResBlock(nn.Module):
    def __init__(self, a, b, emb):
        super().__init__()
        self.n1, self.c1 = nn.GroupNorm(8, a), nn.Conv2d(a, b, 3, 1, 1)
        self.e = nn.Linear(emb, b)
        self.n2, self.c2 = nn.GroupNorm(8, b), nn.Conv2d(b, b, 3, 1, 1)
        self.skip = nn.Conv2d(a, b, 1) if a != b else nn.Identity()

    def forward(self, x, e):
        h = self.c1(F.silu(self.n1(x))) + self.e(e)[:, :, None, None]
        return self.skip(x) + self.c2(F.silu(self.n2(h)))


class ConditionalUNet(nn.Module):
    """Input channels: noisy image (3) + masked original (3) + mask (1) + mesh rendering (3) = 10."""

    def __init__(self, base=32, cond_dim=64):
        super().__init__()
        e = base * 4
        self.temb = nn.Sequential(nn.Linear(base, e), nn.SiLU(), nn.Linear(e, e))
        self.cemb = nn.Linear(cond_dim, e)
        self.base = base
        self.inp = nn.Conv2d(10, base, 3, 1, 1)
        self.d1, self.d2 = ResBlock(base, base, e), ResBlock(base, base * 2, e)
        self.mid = ResBlock(base * 2, base * 2, e)
        self.u2, self.u1 = ResBlock(base * 4, base, e), ResBlock(base * 2, base, e)
        self.out = nn.Conv2d(base, 3, 3, 1, 1)

    def forward(self, x, t, cond_img, cond_vec):
        e = self.temb(timestep_embedding(t, self.base)) + self.cemb(cond_vec)
        h0 = self.inp(torch.cat([x, cond_img], 1))
        h1 = self.d1(h0, e)
        h2 = self.d2(F.avg_pool2d(h1, 2), e)
        m = self.mid(h2, e)
        u = self.u2(torch.cat([m, h2], 1), e)
        u = self.u1(torch.cat([F.interpolate(u, scale_factor=2), h1], 1), e)
        return self.out(u)


class DDPM:
    def __init__(self, steps=1000):
        self.T = steps
        self.betas = torch.linspace(1e-4, 0.02, steps)
        self.alphas = 1 - self.betas
        self.abar = torch.cumprod(self.alphas, 0)

    def noise(self, x0, t, eps):
        a = self.abar.to(x0.device)[t].view(-1, 1, 1, 1)
        return a.sqrt() * x0 + (1 - a).sqrt() * eps

    def loss(self, model, x0, cond_img, cond_vec):
        t = torch.randint(0, self.T, (x0.size(0),), device=x0.device)
        eps = torch.randn_like(x0)
        return F.mse_loss(model(self.noise(x0, t, eps), t, cond_img, cond_vec), eps)

    @torch.no_grad()
    def inpaint(self, model, known, mask, mesh_img, cond_vec, steps=None):
        """known [B,3,H,W] in -1..1, mask [B,1,H,W] 1 = generate. Keeps known pixels outside the mask at every step."""
        x = torch.randn_like(known)
        cond = torch.cat([known * (1 - mask), mask, mesh_img], 1)
        idx = list(range(self.T))[:: max(1, self.T // (steps or self.T))][::-1]
        ab = self.abar.to(known.device)
        for i, t in enumerate(idx):
            tt = torch.full((x.size(0),), t, device=x.device, dtype=torch.long)
            eps = model(x, tt, cond, cond_vec)
            a, a_prev = ab[t], ab[idx[i + 1]] if i + 1 < len(idx) else torch.tensor(1.0, device=x.device)
            x0 = ((x - (1 - a).sqrt() * eps) / a.sqrt()).clamp(-1, 1)
            x = a_prev.sqrt() * x0 + (1 - a_prev).sqrt() * eps                 # deterministic (DDIM-style) step
            x = mask * x + (1 - mask) * (a_prev.sqrt() * known + (1 - a_prev).sqrt() * torch.randn_like(known) * 0)
        return mask * x + (1 - mask) * known


class DiffusionFaceRenderer:
    def __init__(self, model: ConditionalUNet, ddpm: DDPM, steps=50):
        self.m, self.d, self.steps = model.eval(), ddpm, steps

    def render(self, known, mask, mesh_img, cond_vec):
        return self.d.inpaint(self.m, known, mask, mesh_img, cond_vec, self.steps)
