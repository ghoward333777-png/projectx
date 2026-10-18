"""3D face fitting with a linear morphable model (FLAME-like): vertices = mean + shape·S + expression·E, posed by a
rotation, translation and scale, projected weak-perspectively. Parameters are fitted to 2D landmarks over a clip
with temporal smoothness and regularization (Adam). Bring your own model file (.npz with mean [N,3], shape_basis
[N,3,S], expr_basis [N,3,E], landmark_index [L]) — FLAME itself is licensed for non-commercial research only."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch


@dataclass
class FaceMesh3D:
    vertices: np.ndarray
    shape_params: np.ndarray
    expression_params: np.ndarray
    pose_params: np.ndarray                 # [rx, ry, rz, tx, ty, log_scale]


class MorphableModel:
    def __init__(self, mean, shape_basis, expr_basis, landmark_index):
        self.mean = torch.as_tensor(mean, dtype=torch.float32)
        self.S = torch.as_tensor(shape_basis, dtype=torch.float32)
        self.E = torch.as_tensor(expr_basis, dtype=torch.float32)
        self.lmk = torch.as_tensor(landmark_index, dtype=torch.long)

    @classmethod
    def load(cls, path):
        z = np.load(path)
        return cls(z["mean"], z["shape_basis"], z["expr_basis"], z["landmark_index"])

    @classmethod
    def random(cls, n_vertices=200, n_shape=10, n_expr=8, n_landmarks=68, seed=0):
        """A synthetic model for tests."""
        g = np.random.default_rng(seed)
        return cls(g.normal(size=(n_vertices, 3)), g.normal(size=(n_vertices, 3, n_shape)) * 0.1,
                   g.normal(size=(n_vertices, 3, n_expr)) * 0.1, g.choice(n_vertices, n_landmarks, replace=False))

    def vertices(self, shape, expr):           # shape [S], expr [T, E] → [T, N, 3]
        base = self.mean + torch.einsum("nds,s->nd", self.S, shape)
        return base.unsqueeze(0) + torch.einsum("nde,te->tnd", self.E, expr)


def rotation(r):                               # axis-angle [T, 3] → [T, 3, 3]
    theta = r.norm(dim=-1, keepdim=True).clamp(min=1e-8)
    k = r / theta
    K = torch.zeros(r.shape[0], 3, 3, dtype=r.dtype)
    K[:, 0, 1], K[:, 0, 2], K[:, 1, 0] = -k[:, 2], k[:, 1], k[:, 2]
    K[:, 1, 2], K[:, 2, 0], K[:, 2, 1] = -k[:, 0], -k[:, 1], k[:, 0]
    I = torch.eye(3).expand(r.shape[0], 3, 3)
    s, c = torch.sin(theta).unsqueeze(-1), torch.cos(theta).unsqueeze(-1)
    return I + s * K + (1 - c) * (K @ K)


def project(model, shape, expr, pose):
    v = model.vertices(shape, expr)[:, model.lmk]                 # [T, L, 3]
    R = rotation(pose[:, :3])
    v = torch.einsum("tij,tlj->tli", R, v)
    return v[..., :2] * pose[:, 5].exp().view(-1, 1, 1) + pose[:, 3:5].unsqueeze(1)


class FaceFitter3D:
    def __init__(self, model: MorphableModel, iters=300, lr=0.05, w_shape=1e-3, w_expr=1e-3, w_smooth=1e-1):
        self.m, self.iters, self.lr = model, iters, lr
        self.w = (w_shape, w_expr, w_smooth)

    def fit(self, landmarks_2d: np.ndarray):
        """landmarks_2d: [T, L, 2] (same order as the model's landmark_index) → list of FaceMesh3D, final error."""
        target = torch.as_tensor(landmarks_2d, dtype=torch.float32)
        T = target.shape[0]
        shape = torch.zeros(self.m.S.shape[-1], requires_grad=True)
        expr = torch.zeros(T, self.m.E.shape[-1], requires_grad=True)
        pose = torch.zeros(T, 6)
        pose[:, 3:5] = target.mean(1)
        pose.requires_grad_(True)
        opt = torch.optim.Adam([shape, expr, pose], lr=self.lr)
        with torch.no_grad():
            self.initial_error = float(((project(self.m, shape, expr, pose) - target) ** 2).mean().sqrt())
        for _ in range(self.iters):
            opt.zero_grad()
            pred = project(self.m, shape, expr, pose)
            loss = ((pred - target) ** 2).mean()
            loss = loss + self.w[0] * (shape ** 2).mean() + self.w[1] * (expr ** 2).mean()
            if T > 1:
                loss = loss + self.w[2] * ((expr[1:] - expr[:-1]) ** 2).mean() + self.w[2] * ((pose[1:] - pose[:-1]) ** 2).mean()
            loss.backward()
            opt.step()
        with torch.no_grad():
            err = float(((project(self.m, shape, expr, pose) - target) ** 2).mean().sqrt())
            verts = self.m.vertices(shape, expr).numpy()
        meshes = [FaceMesh3D(verts[t], shape.detach().numpy().copy(), expr[t].detach().numpy().copy(), pose[t].detach().numpy().copy())
                  for t in range(T)]
        return meshes, err
