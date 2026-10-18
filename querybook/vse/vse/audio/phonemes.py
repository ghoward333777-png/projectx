"""ASR & phoneme extractor: Conformer encoder over log-mel frames with a CTC phoneme head. Greedy CTC decoding
gives each phoneme its frames, hence its start and end time and a confidence."""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from vse.common.config import TrainConfig
from vse.common.nn import ConformerEncoder, Subsample2, lengths_to_mask
from vse.common.types import PHONEMES, PHONEME_TO_VISEME, PhonemeSegment, PhonemeTimeline

from .features import LogMel


class PhonemeASR(nn.Module):
    def __init__(self, cfg: TrainConfig, vocab=PHONEMES):
        super().__init__()
        m, d = cfg.model, cfg.data
        self.vocab = list(vocab)
        self.mel = LogMel(d.sample_rate, d.n_mels, d.win_ms, d.hop_ms)
        self.sub = Subsample2(d.n_mels, m.dim)
        self.encoder = ConformerEncoder(m.dim, m.dim, m.layers, m.heads, m.ff_mult, m.conv_kernel, m.dropout)
        self.ctc = nn.Linear(m.dim, len(self.vocab))
        self.frame_s = self.mel.hop_s * self.sub.factor

    def forward(self, wav, wav_lengths=None):
        """wav [B, N] → (log-probs [B, T', V], output lengths [B])."""
        x = self.sub(self.mel(wav))
        if wav_lengths is None:
            lens = torch.full((x.size(0),), x.size(1), dtype=torch.long, device=x.device)
        else:
            lens = self.sub.lengths(wav_lengths // self.mel.hop + 1).clamp(max=x.size(1))
        h = self.encoder(x, lengths_to_mask(lens, x.size(1)))
        return F.log_softmax(self.ctc(h), dim=-1), lens


def ctc_loss(model, batch, device):
    wav, wav_len, tgt, tgt_len = (b.to(device) for b in batch)
    lp, lens = model(wav, wav_len)
    loss = F.ctc_loss(lp.transpose(0, 1), tgt, lens, tgt_len, blank=0, zero_infinity=True)
    return loss, {}


def ctc_greedy_segments(log_probs, frame_s, vocab=PHONEMES, min_conf=0.0):
    """One utterance's log-probs [T, V] → PhonemeTimeline (blank = index 0)."""
    probs = log_probs.exp()
    best = probs.argmax(-1).tolist()
    segs, cur, start, conf = [], None, 0, []
    for t, k in enumerate(best + [0]):
        if k != cur:
            if cur not in (None, 0):
                c = sum(conf) / len(conf)
                if c >= min_conf:
                    sym = vocab[cur]
                    segs.append(PhonemeSegment(sym, round(start * frame_s, 3), round(t * frame_s, 3), round(c, 3), PHONEME_TO_VISEME.get(sym)))
            cur, start, conf = k, t, []
        if t < len(best):
            conf.append(float(probs[t, k]))
    return PhonemeTimeline(segs)


class PhonemeExtractor:
    """Inference wrapper: a checkpoint in, a timed phoneme timeline out."""

    def __init__(self, cfg: TrainConfig, checkpoint: str, device="cpu"):
        self.model = PhonemeASR(cfg).to(device).eval()
        self.model.load_state_dict(torch.load(checkpoint, map_location=device)["model"])
        self.device = device

    @torch.no_grad()
    def extract(self, wav) -> PhonemeTimeline:
        wav = torch.as_tensor(wav, dtype=torch.float32, device=self.device).unsqueeze(0)
        lp, _ = self.model(wav)
        return ctc_greedy_segments(lp[0].cpu(), self.model.frame_s, self.model.vocab)
