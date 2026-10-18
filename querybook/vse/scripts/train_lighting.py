"""Lighting estimator CNN on renders with known spherical-harmonics light. Manifest rows: {"crop": "x.npy", "sh": [27]}."""
import numpy as np
import torch
from _common import args, loaders
from torch.utils.data import Dataset

from vse.common.data import read_manifest
from vse.common.train import train
from vse.visual.lighting import LightingEstimator


class DS(Dataset):
    def __init__(self, path):
        self.rows = read_manifest(path)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        return torch.from_numpy(np.load(r["crop"])).permute(2, 0, 1).float() / 255.0, torch.tensor(r["sh"], dtype=torch.float32)


def collate(b):
    return tuple(torch.stack(x) for x in zip(*b))


def loss_fn(model, batch, device):
    x, y = (t.to(device) for t in batch)
    return torch.nn.functional.mse_loss(model(x), y), {}


a, cfg = args()
cfg.name = cfg.name if cfg.name != "model" else "lighting"
tl, vl = loaders(DS(cfg.data.train_manifest), DS(cfg.data.val_manifest), cfg, collate)
train(LightingEstimator(), loss_fn, tl, vl, cfg, a.steps)
