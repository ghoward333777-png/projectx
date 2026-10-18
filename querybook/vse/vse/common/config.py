"""Typed configs loaded from YAML (configs/*.yaml). Every model has a 'tiny' preset for tests and CPU smoke runs."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Optional

import yaml


@dataclass
class OptimConfig:
    lr: float = 3e-4
    weight_decay: float = 0.01
    betas: tuple = (0.9, 0.98)
    warmup_steps: int = 1000
    max_steps: int = 100000
    grad_clip: float = 1.0
    amp: bool = True


@dataclass
class DataConfig:
    train_manifest: str = "data/manifests/train.jsonl"
    val_manifest: str = "data/manifests/val.jsonl"
    batch_size: int = 16
    num_workers: int = 4
    sample_rate: int = 16000
    n_mels: int = 80
    hop_ms: float = 10.0
    win_ms: float = 25.0
    video_fps: int = 25
    mouth_size: int = 88


@dataclass
class ModelConfig:
    dim: int = 256
    layers: int = 6
    heads: int = 4
    ff_mult: int = 4
    dropout: float = 0.1
    conv_kernel: int = 15
    embedding_dim: int = 256
    motion_dim: int = 13 + 3 + 2 + 1 + 2      # mouth params + head pose + gaze + blink + brows


@dataclass
class TrainConfig:
    name: str = "model"
    model: ModelConfig = field(default_factory=ModelConfig)
    data: DataConfig = field(default_factory=DataConfig)
    optim: OptimConfig = field(default_factory=OptimConfig)
    checkpoint_dir: str = "checkpoints"
    log_every: int = 50
    eval_every: int = 1000
    seed: int = 1234
    device: str = "cuda"
    init_from: Optional[str] = None


_NESTED = {"model": ModelConfig, "data": DataConfig, "optim": OptimConfig}


def _build(cls, d):
    names = {f.name for f in dataclasses.fields(cls)}
    unknown = set(d) - names
    if unknown:
        raise ValueError("unknown config keys for %s: %s" % (cls.__name__, ", ".join(sorted(unknown))))
    kw = {}
    for k, v in d.items():
        if k in _NESTED and cls is TrainConfig and isinstance(v, dict):
            v = _build(_NESTED[k], v)
        elif k == "betas" and isinstance(v, list):
            v = tuple(v)
        kw[k] = v
    return cls(**kw)


def load(path: str) -> TrainConfig:
    with open(path, encoding="utf-8") as fh:
        return _build(TrainConfig, yaml.safe_load(fh) or {})


def tiny(name="tiny") -> TrainConfig:
    """A config small enough to train a few steps on a CPU (tests, smoke runs)."""
    return TrainConfig(name=name, model=ModelConfig(dim=32, layers=2, heads=2, embedding_dim=32, conv_kernel=5),
                       data=DataConfig(batch_size=2, num_workers=0, n_mels=40, mouth_size=32), optim=OptimConfig(warmup_steps=5, max_steps=50, amp=False),
                       device="cpu", checkpoint_dir="/tmp/vse-ckpt")
