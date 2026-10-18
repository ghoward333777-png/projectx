"""Speech emotion (VAD regression + categories). Datasets need their own licences (IEMOCAP, MSP-Podcast: research
agreements). Manifest rows: {"mel": [[...]], "prosody": [[4]...], "vad": [3], "categories": [5]} (precomputed)."""
import torch
from _common import args, loaders
from torch.utils.data import Dataset

from vse.audio.emotion import EmotionNet, emotion_loss
from vse.common.data import pad, read_manifest
from vse.common.train import train


class EmoDS(Dataset):
    def __init__(self, path):
        self.rows = read_manifest(path)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        return (torch.tensor(r["mel"]), torch.tensor(r["prosody"]), torch.tensor(r["vad"]), torch.tensor(r["categories"], dtype=torch.float32))


def collate(b):
    m, p, v, c = zip(*b)
    return pad(list(m)), pad(list(p)), torch.stack(v), torch.stack(c)


a, cfg = args()
cfg.name = cfg.name if cfg.name != "model" else "emotion"
tl, vl = loaders(EmoDS(cfg.data.train_manifest), EmoDS(cfg.data.val_manifest), cfg, collate)
train(EmotionNet(cfg), emotion_loss, tl, vl, cfg, a.steps)
