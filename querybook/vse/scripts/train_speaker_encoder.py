"""Speaker encoder (ECAPA-style + ArcFace). VoxCeleb is the usual source (check its licence and terms of use);
manifest rows: {"audio": "x.wav", "speaker": int}."""
import torch
from _common import args, loaders
from torch.utils.data import Dataset

from vse.audio.features import LogMel
from vse.audio.speaker import SpeakerEncoder, speaker_loss
from vse.common.data import read_manifest
from vse.common.io import load_wav
from vse.common.train import train

a, cfg = args({"--crop-s": dict(type=float, default=3.0)})
mel = LogMel(cfg.data.sample_rate, cfg.data.n_mels)


class SpkDS(Dataset):
    def __init__(self, path):
        self.rows = read_manifest(path)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        w = torch.from_numpy(load_wav(r["audio"], cfg.data.sample_rate))[: int(a.crop_s * cfg.data.sample_rate)]
        w = torch.nn.functional.pad(w, (0, max(0, int(a.crop_s * cfg.data.sample_rate) - w.numel())))
        return mel(w.unsqueeze(0))[0], int(r["speaker"])


def collate(b):
    m, s = zip(*b)
    return torch.stack(m), torch.tensor(s)


train_ds = SpkDS(cfg.data.train_manifest)
cfg.name = cfg.name if cfg.name != "model" else "speaker_encoder"
tl, vl = loaders(train_ds, SpkDS(cfg.data.val_manifest), cfg, collate)
train(SpeakerEncoder(cfg, n_speakers=1 + max(int(r["speaker"]) for r in train_ds.rows)), speaker_loss, tl, vl, cfg, a.steps)
