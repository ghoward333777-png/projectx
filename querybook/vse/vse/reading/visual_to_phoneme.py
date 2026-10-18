"""Visual speech → unit sequence with CTC (units: phonemes, or visemes when the training labels are visemes).
Front-end (video or features) → Conformer → CTC head."""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from vse.common.config import TrainConfig
from vse.common.nn import ConformerEncoder, lengths_to_mask
from vse.common.types import PHONEMES, VISEMES

from .mouth_features import FeatureFrontEnd, VideoFrontEnd

UNITS = {"phoneme": PHONEMES, "viseme": ["<blank>"] + VISEMES}


class LipReader(nn.Module):
    def __init__(self, cfg: TrainConfig, frontend="features", unit="viseme", n_features=13):
        super().__init__()
        d = cfg.model.dim
        self.unit, self.vocab = unit, UNITS[unit]
        self.front = FeatureFrontEnd(n_features, d) if frontend == "features" else VideoFrontEnd(d)
        self.enc = ConformerEncoder(d, d, cfg.model.layers, cfg.model.heads, cfg.model.ff_mult, cfg.model.conv_kernel, cfg.model.dropout)
        self.ctc = nn.Linear(d, len(self.vocab))

    def forward(self, x, lengths=None):
        h = self.front(x)
        mask = lengths_to_mask(lengths, h.size(1)) if lengths is not None else None
        return F.log_softmax(self.ctc(self.enc(h, mask)), -1)


def lipread_loss(model, batch, device):
    x, lens, tgt, tgt_len = (b.to(device) for b in batch)
    lp = model(x, lens)
    loss = F.ctc_loss(lp.transpose(0, 1), tgt, lens, tgt_len, blank=0, zero_infinity=True)
    return loss, {}
