"""End-to-end fine-tuning of the face motion synthesizer with a frozen lip reader as a "lip-sync expert": besides
matching the target motion, the generated mouth must be readable as the intended visemes (CTC loss through the
frozen reader). Generated lips that look like the wrong sound are penalized even when their L2 error is small."""
import torch
import torch.nn.functional as F
from _common import args, loaders

from vse.common.data import MotionDataset
from vse.common.train import train
from vse.reading.visual_to_phoneme import LipReader
from vse.sync.motion_synthesizer import FaceMotionSynthesizer, motion_loss

a, cfg = args({"--reader": dict(required=True), "--motion": dict(default=None), "--w-read": dict(type=float, default=0.5),
               "--speaker-dim": dict(type=int, default=256)})
reader = LipReader(cfg, "features", "viseme")
reader.load_state_dict(torch.load(a.reader, map_location="cpu")["model"])
reader.eval()
for p in reader.parameters():
    p.requires_grad_(False)
model = FaceMotionSynthesizer(cfg, a.speaker_dim)
if a.motion:
    model.load_state_dict(torch.load(a.motion, map_location="cpu")["model"])


def loss_fn(m, batch, device):
    base, metrics = motion_loss(m, batch, device)
    vis, pros, emo, spk, target, mask = (b.to(device) for b in batch)
    reader.to(device)
    mouth = m(vis, pros, emo, spk, mask)[..., :13]
    lens = (~mask).sum(1)
    lp = reader(mouth, lens)
    tgts, tlen = [], []
    for row, n in zip(vis, lens):                      # intended viseme sequence (repeats and silence removed), +1 for blank
        seq = [int(v) + 1 for i, v in enumerate(row[:n].tolist()) if v != 0 and (i == 0 or v != int(row[i - 1]))]
        tgts += seq or [1]; tlen.append(len(seq) or 1)
    read = F.ctc_loss(lp.transpose(0, 1), torch.tensor(tgts, device=device), lens, torch.tensor(tlen, device=device), zero_infinity=True)
    return base + a.w_read * read, dict(metrics, readability=float(read))


cfg.name = cfg.name if cfg.name != "model" else "end_to_end"
tl, vl = loaders(MotionDataset(cfg.data.train_manifest), MotionDataset(cfg.data.val_manifest), cfg, MotionDataset.collate)
train(model, loss_fn, tl, vl, cfg, a.steps)
