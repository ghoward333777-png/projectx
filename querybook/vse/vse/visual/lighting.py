"""Lighting as second-order spherical harmonics (9 coefficients per colour channel = 27). Two estimators: a closed-
form least-squares fit from surface normals and observed colours (needs the fitted mesh), and a CNN that predicts
the 27 numbers straight from a face crop (trained on renders with known light)."""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn


def sh_basis(normals: np.ndarray) -> np.ndarray:
    """Real SH basis up to band 2 for unit normals [N, 3] → [N, 9]."""
    x, y, z = normals[:, 0], normals[:, 1], normals[:, 2]
    c0, c1, c2, c3, c4 = 0.282095, 0.488603, 1.092548, 0.315392, 0.546274
    return np.stack([np.full_like(x, c0), c1 * y, c1 * z, c1 * x, c2 * x * y, c2 * y * z, c3 * (3 * z * z - 1), c2 * x * z,
                     c4 * (x * x - y * y)], 1)


def fit_sh(normals: np.ndarray, colors: np.ndarray, ridge=1e-3) -> np.ndarray:
    """Least squares: colors [N, 3] ≈ basis(normals) @ coeffs → coeffs [9, 3] (flatten to 27)."""
    B = sh_basis(normals)
    A = B.T @ B + ridge * np.eye(9)
    return np.linalg.solve(A, B.T @ colors)


def shade(normals, coeffs):
    return sh_basis(normals) @ coeffs


class LightingEstimator(nn.Module):
    def __init__(self, width=32):
        super().__init__()
        ch = [3, width, width * 2, width * 4, width * 8]
        layers = []
        for a, b in zip(ch, ch[1:]):
            layers += [nn.Conv2d(a, b, 3, 2, 1), nn.BatchNorm2d(b), nn.ReLU()]
        self.cnn = nn.Sequential(*layers, nn.AdaptiveAvgPool2d(1), nn.Flatten())
        self.fc = nn.Linear(ch[-1], 27)

    def forward(self, crop):                       # [B, 3, H, W] in 0..1 → [B, 27]
        return self.fc(self.cnn(crop))
