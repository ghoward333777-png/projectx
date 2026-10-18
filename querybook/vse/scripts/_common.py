"""Shared command line for the training scripts: --config, --tiny (CPU smoke run), --steps, --device."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from torch.utils.data import DataLoader  # noqa: E402

from vse.common import config as C  # noqa: E402


def args(extra=None):
    p = argparse.ArgumentParser()
    p.add_argument("--config", help="configs/<name>.yaml")
    p.add_argument("--tiny", action="store_true", help="a tiny model for a CPU smoke run")
    p.add_argument("--steps", type=int, default=None)
    p.add_argument("--device", default=None)
    for a, kw in (extra or {}).items():
        p.add_argument(a, **kw)
    a = p.parse_args()
    cfg = C.tiny() if a.tiny or not a.config else C.load(a.config)
    if a.device:
        cfg.device = a.device
    return a, cfg


def loaders(train_ds, val_ds, cfg, collate):
    tl = DataLoader(train_ds, batch_size=cfg.data.batch_size, shuffle=True, num_workers=cfg.data.num_workers, collate_fn=collate)
    vl = DataLoader(val_ds, batch_size=cfg.data.batch_size, num_workers=cfg.data.num_workers, collate_fn=collate) if val_ds is not None else None
    return tl, vl
