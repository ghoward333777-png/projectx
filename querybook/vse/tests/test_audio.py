import numpy as np
import torch

from vse.audio.emotion import EmotionNet, emotion_loss
from vse.audio.features import LogMel
from vse.audio.phonemes import PhonemeASR, ctc_greedy_segments, ctc_loss
from vse.audio.prosody import ProsodyExtractor, yin
from vse.audio.speaker import SpeakerEncoder
from vse.common.config import tiny
from vse.common.types import PHONEMES


def test_logmel_shape():
    m = LogMel(16000, 40)
    x = m(torch.randn(2, 16000))
    assert x.shape == (2, 101, 40)


def test_yin_finds_pitch():
    sr = 16000
    t = np.arange(sr) / sr
    f0, _ = yin(np.sin(2 * np.pi * 180 * t).astype(np.float32), sr)
    voiced = f0[f0 > 0]
    assert len(voiced) > 50 and abs(np.median(voiced) - 180) < 3


def test_prosody_timeline():
    sr = 16000
    t = np.arange(sr) / sr
    tl = ProsodyExtractor(sr).extract((0.5 * np.sin(2 * np.pi * 150 * t)).astype(np.float32))
    assert len(tl.frames) > 90 and all(0 <= f.energy <= 1 for f in tl.frames)


def test_asr_ctc_learns_a_toy_task():
    torch.manual_seed(0)
    cfg = tiny()
    m = PhonemeASR(cfg)
    wav = torch.randn(2, 8000)
    tgt = torch.tensor([5, 6, 7, 5, 6])
    batch = (wav, torch.tensor([8000, 8000]), tgt, torch.tensor([3, 2]))
    opt = torch.optim.Adam(m.parameters(), 3e-3)
    first = None
    for _ in range(30):
        loss, _ = ctc_loss(m, batch, "cpu")
        opt.zero_grad(); loss.backward(); opt.step()
        first = first or float(loss.detach())
    assert float(loss) < first * 0.7


def test_ctc_greedy_segments_times():
    V = len(PHONEMES)
    lp = torch.full((10, V), -10.0)
    seq = [0, 8, 8, 0, 2, 2, 2, 0, 0, 0]          # blank, B, B, blank, AA×3
    for t, k in enumerate(seq):
        lp[t, k] = 0.0
    tl = ctc_greedy_segments(lp, 0.04)
    assert [p.symbol for p in tl.phonemes] == ["B", "AA"] and tl.phonemes[1].start_time == 0.16 and tl.phonemes[0].viseme == "PP"


def test_emotion_and_speaker_shapes():
    cfg = tiny()
    e = EmotionNet(cfg)
    out = e(torch.randn(2, 50, 40), torch.randn(2, 50, 4))
    assert out.shape == (2, 8) and (out[:, :3] >= 0).all() and (out[:, :3] <= 1).all()
    loss, _ = emotion_loss(e, (torch.randn(2, 50, 40), torch.randn(2, 50, 4), torch.rand(2, 3), torch.rand(2, 5).round()), "cpu")
    assert loss.item() > 0
    s = SpeakerEncoder(cfg, n_speakers=3)
    emb = s(torch.randn(2, 80, 40))
    assert emb.shape == (2, 32) and torch.allclose(emb.norm(dim=-1), torch.ones(2), atol=1e-4)
