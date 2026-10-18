"""Phonemes → visemes. A rule table gives the baseline (types.PHONEME_TO_VISEME); the network learns the
context-dependent version (coarticulation, timing shifts, intensity) frame by frame from phoneme, prosody and
emotion streams. Trained on aligned audio + tracked faces (QueryBook's reservoir labels are one source)."""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from vse.common.config import TrainConfig
from vse.common.nn import PositionalEncoding
from vse.common.types import EMOTION_KEYS, PHONEME_TO_VISEME, PHONEMES, VISEMES, VisemeSegment, VisemeSequence

from .framing import emotion_tensor, phoneme_frames, prosody_frames, segments_from_frames


def rule_visemes(tl) -> VisemeSequence:
    return VisemeSequence([VisemeSegment(PHONEME_TO_VISEME.get(p.symbol, "DD"), p.start_time, p.end_time) for p in tl.phonemes])


class PhonemeToVisemeNet(nn.Module):
    def __init__(self, cfg: TrainConfig):
        super().__init__()
        d = cfg.model.dim
        self.ph = nn.Embedding(len(PHONEMES), d)
        self.pr = nn.Linear(4, d)
        self.em = nn.Linear(len(EMOTION_KEYS), d)
        self.pos = PositionalEncoding(d)
        layer = nn.TransformerEncoderLayer(d, cfg.model.heads, d * cfg.model.ff_mult, cfg.model.dropout, batch_first=True)
        self.enc = nn.TransformerEncoder(layer, cfg.model.layers)
        self.vis = nn.Linear(d, len(VISEMES))
        self.intensity = nn.Linear(d, 1)

    def forward(self, ph_ids, prosody, emotion, mask=None):      # [B,T], [B,T,4], [B,8]
        x = self.ph(ph_ids) + self.pr(prosody) + self.em(emotion).unsqueeze(1)
        h = self.enc(self.pos(x), src_key_padding_mask=mask)
        return self.vis(h), torch.sigmoid(self.intensity(h)).squeeze(-1)


def p2v_loss(model, batch, device):
    ph, pros, emo, vis, inten, mask = (b.to(device) for b in batch)
    logits, pi = model(ph, pros, emo, mask)
    keep = ~mask
    ce = F.cross_entropy(logits[keep], vis[keep])
    mse = F.mse_loss(pi[keep], inten[keep])
    acc = (logits.argmax(-1)[keep] == vis[keep]).float().mean()
    return ce + mse, {"accuracy": float(acc)}


class PhonemeToViseme:
    def __init__(self, cfg: TrainConfig, checkpoint=None, device="cpu", fps=100):
        self.fps, self.device = fps, device
        self.model = None
        if checkpoint:
            self.model = PhonemeToVisemeNet(cfg).to(device).eval()
            self.model.load_state_dict(torch.load(checkpoint, map_location=device)["model"])

    @torch.no_grad()
    def generate(self, tl, prosody, emotion, duration) -> VisemeSequence:
        if self.model is None:
            return rule_visemes(tl)
        ph = phoneme_frames(tl, self.fps, duration).unsqueeze(0).to(self.device)
        pr = prosody_frames(prosody, self.fps, duration).unsqueeze(0).to(self.device)
        em = emotion_tensor(emotion).unsqueeze(0).to(self.device)
        logits, inten = self.model(ph, pr, em)
        probs = logits[0].softmax(-1).cpu()
        segs = segments_from_frames(probs.argmax(-1), VISEMES, self.fps, probs)
        return VisemeSequence([VisemeSegment(v, round(a, 3), round(b, 3), round(float(inten[0, int(a * self.fps)]), 3)) for v, a, b, _ in segs])
