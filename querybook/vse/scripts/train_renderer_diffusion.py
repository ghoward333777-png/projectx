"""Diffusion face inpainting renderer. Manifest rows: {"frame": "x.npy", "mask": "m.npy", "mesh": "r.npy", "cond": [64]}
(frame/mesh uint8 [H, W, 3], mask uint8 [H, W]). Train per person, with that person's consent."""
import numpy as np
import torch
from _common import args, loaders
from torch.utils.data import Dataset

from vse.common.data import read_manifest
from vse.common.train import train
from vse.render.diffusion_renderer import DDPM, ConditionalUNet

a, cfg = args()
ddpm = DDPM()


class DS(Dataset):
    def __init__(self, path):
        self.rows = read_manifest(path)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        img = torch.from_numpy(np.load(r["frame"])).permute(2, 0, 1).float() / 127.5 - 1
        mask = torch.from_numpy(np.load(r["mask"])).float().unsqueeze(0) / 255.0
        mesh = torch.from_numpy(np.load(r["mesh"])).permute(2, 0, 1).float() / 127.5 - 1
        return img, torch.cat([img * (1 - mask), mask, mesh], 0), torch.tensor(r["cond"], dtype=torch.float32)


def collate(b):
    return tuple(torch.stack(x) for x in zip(*b))


def loss_fn(model, batch, device):
    x0, cimg, cvec = (t.to(device) for t in batch)
    return ddpm.loss(model, x0, cimg, cvec), {}


cfg.name = cfg.name if cfg.name != "model" else "renderer_diffusion"
tl, vl = loaders(DS(cfg.data.train_manifest), DS(cfg.data.val_manifest), cfg, collate)
train(ConditionalUNet(base=max(8, cfg.model.dim // 4), cond_dim=64), loss_fn, tl, vl, cfg, a.steps)
