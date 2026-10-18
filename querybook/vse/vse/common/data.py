"""Datasets over JSON-lines manifests (one example per line), with padding collate functions.

  features  {"features": [[t, f1..f13], ...], "units": ["PP", "aa", ...]}       lip reading from tracker numbers
  audio     {"audio": "path.wav", "phonemes": ["HH", "AH", ...]}              phoneme ASR
  motion    {"visemes": [id per frame], "prosody": [[4] per frame], "emotion": [8], "speaker": [S],
             "motion": [[motion_dim] per frame]}                                 lip sync / face motion
  p2v       {"phonemes": [id per frame], "prosody": [[4]...], "emotion": [8], "visemes": [id...], "intensity": [...]}"""
from __future__ import annotations

import json

import torch
from torch.utils.data import Dataset

from .io import load_wav
from .types import PHONEMES


def read_manifest(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def pad(seqs, value=0.0):
    n = max(s.size(0) for s in seqs)
    out = seqs[0].new_full((len(seqs), n, *seqs[0].shape[1:]), value)
    for i, s in enumerate(seqs):
        out[i, :s.size(0)] = s
    return out


class FeatureCTCDataset(Dataset):
    def __init__(self, rows, vocab, fps=30):
        self.rows = rows if isinstance(rows, list) else read_manifest(rows)
        self.idx = {u: i for i, u in enumerate(vocab)}
        self.fps = fps

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        feats = torch.tensor([f[1:14] for f in r["features"]], dtype=torch.float32)
        tgt = torch.tensor([self.idx[u] for u in r["units"] if u in self.idx], dtype=torch.long)
        return feats, tgt

    @staticmethod
    def collate(batch):
        feats, tgts = zip(*batch)
        lens = torch.tensor([f.size(0) for f in feats])
        return pad(list(feats)), lens, torch.cat(tgts), torch.tensor([t.size(0) for t in tgts])


class AudioCTCDataset(Dataset):
    def __init__(self, rows, sample_rate=16000):
        self.rows = rows if isinstance(rows, list) else read_manifest(rows)
        self.sr = sample_rate
        self.idx = {p: i for i, p in enumerate(PHONEMES)}

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        wav = torch.from_numpy(load_wav(r["audio"], self.sr))
        return wav, torch.tensor([self.idx[p] for p in r["phonemes"] if p in self.idx], dtype=torch.long)

    @staticmethod
    def collate(batch):
        wavs, tgts = zip(*batch)
        return pad(list(wavs)), torch.tensor([w.size(0) for w in wavs]), torch.cat(tgts), torch.tensor([t.size(0) for t in tgts])


class MotionDataset(Dataset):
    def __init__(self, rows):
        self.rows = rows if isinstance(rows, list) else read_manifest(rows)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        return (torch.tensor(r["visemes"], dtype=torch.long), torch.tensor(r["prosody"], dtype=torch.float32),
                torch.tensor(r["emotion"], dtype=torch.float32), torch.tensor(r["speaker"], dtype=torch.float32),
                torch.tensor(r["motion"], dtype=torch.float32))

    @staticmethod
    def collate(batch):
        v, p, e, s, m = zip(*batch)
        lens = torch.tensor([x.size(0) for x in v])
        mask = torch.arange(int(lens.max())).unsqueeze(0) >= lens.unsqueeze(1)
        return pad(list(v)), pad(list(p)), torch.stack(e), torch.stack(s), pad(list(m)), mask


class P2VDataset(Dataset):
    def __init__(self, rows):
        self.rows = rows if isinstance(rows, list) else read_manifest(rows)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        return (torch.tensor(r["phonemes"], dtype=torch.long), torch.tensor(r["prosody"], dtype=torch.float32),
                torch.tensor(r["emotion"], dtype=torch.float32), torch.tensor(r["visemes"], dtype=torch.long),
                torch.tensor(r.get("intensity") or [1.0] * len(r["visemes"]), dtype=torch.float32))

    @staticmethod
    def collate(batch):
        ph, pr, em, vi, it = zip(*batch)
        lens = torch.tensor([x.size(0) for x in ph])
        mask = torch.arange(int(lens.max())).unsqueeze(0) >= lens.unsqueeze(1)
        return pad(list(ph)), pad(list(pr)), torch.stack(em), pad(list(vi)), pad(list(it)), mask
