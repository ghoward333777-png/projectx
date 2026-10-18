"""Visual identity encoder (ResNet + ArcFace) on aligned face crops. Use consented data only — MS-Celeb-1M and
VGGFace2 were withdrawn by their creators. Manifest rows: {"crop": "x.png" or "x.npy", "id": int}."""
import numpy as np
import torch
from _common import args, loaders
from torch.utils.data import Dataset

from vse.common.data import read_manifest
from vse.common.train import train
from vse.visual.identity import IdentityEncoder, identity_loss


class IdDS(Dataset):
    def __init__(self, path):
        self.rows = read_manifest(path)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        img = np.load(r["crop"]) if r["crop"].endswith(".npy") else None
        if img is None:
            raise ValueError("store crops as .npy uint8 [H, W, 3] (no image library dependency)")
        return torch.from_numpy(img).permute(2, 0, 1).float() / 255.0, int(r["id"])


def collate(b):
    x, y = zip(*b)
    return torch.stack(x), torch.tensor(y)


a, cfg = args()
cfg.name = cfg.name if cfg.name != "model" else "identity_encoder"
ds = IdDS(cfg.data.train_manifest)
tl, vl = loaders(ds, IdDS(cfg.data.val_manifest), cfg, collate)
train(IdentityEncoder(cfg.model.embedding_dim, n_ids=1 + max(int(r["id"]) for r in ds.rows)), identity_loss, tl, vl, cfg, a.steps)
