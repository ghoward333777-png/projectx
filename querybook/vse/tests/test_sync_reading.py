import math

import torch

from vse.common.config import tiny
from vse.common.types import PHONEMES, VISEMES, PhonemeSegment, PhonemeTimeline
from vse.reading.phoneme_to_text import lexicon_beam_search
from vse.reading.visual_to_phoneme import UNITS, LipReader, lipread_loss
from vse.sync.motion_synthesizer import FaceMotionSynthesizer, motion_loss
from vse.sync.phoneme_to_viseme import PhonemeToVisemeNet, p2v_loss, rule_visemes


def test_rule_visemes():
    tl = PhonemeTimeline([PhonemeSegment("B", 0.0, 0.1), PhonemeSegment("UW", 0.1, 0.3)])
    assert [v.id for v in rule_visemes(tl).visemes] == ["PP", "U"]


def test_p2v_and_motion_train_steps():
    torch.manual_seed(0)
    cfg = tiny()
    T = 40
    mask = torch.zeros(2, T, dtype=torch.bool)
    net = PhonemeToVisemeNet(cfg)
    batch = (torch.randint(1, len(PHONEMES), (2, T)), torch.rand(2, T, 4), torch.rand(2, 8), torch.randint(0, len(VISEMES), (2, T)), torch.rand(2, T), mask)
    loss, m = p2v_loss(net, batch, "cpu")
    assert loss.item() > 0 and 0 <= m["accuracy"] <= 1
    fms = FaceMotionSynthesizer(cfg, speaker_dim=16)
    vis = torch.randint(0, len(VISEMES), (2, T))
    target = torch.rand(2, T, cfg.model.motion_dim)
    batch = (vis, torch.rand(2, T, 4), torch.rand(2, 8), torch.rand(2, 16), target, mask)
    opt = torch.optim.Adam(fms.parameters(), 3e-3)
    first = None
    for _ in range(40):
        loss, _ = motion_loss(fms, batch, "cpu")
        opt.zero_grad(); loss.backward(); opt.step()
        first = first or float(loss.detach())
    assert float(loss) < first * 0.6


def test_lip_reader_forward_and_loss():
    cfg = tiny()
    m = LipReader(cfg, "features", "viseme")
    x = torch.rand(2, 50, 13)
    lp = m(x, torch.tensor([50, 40]))
    assert lp.shape == (2, 50, len(UNITS["viseme"]))
    loss, _ = lipread_loss(m, (x, torch.tensor([50, 40]), torch.tensor([2, 11, 3, 4]), torch.tensor([2, 2])), "cpu")
    assert math.isfinite(loss.item())
    mv = LipReader(cfg, "video", "phoneme")
    assert mv(torch.rand(1, 6, 1, 32, 32)).shape == (1, 6, len(PHONEMES))


def test_lexicon_beam_search_reads_words():
    vocab = UNITS["viseme"]
    idx = {u: i for i, u in enumerate(vocab)}
    lex = {"bob": ["PP", "O", "PP"], "pa": ["PP", "aa"], "you": ["I", "U"]}
    seq = ["PP", "PP", "O", "O", "<blank>", "PP", "<blank>", "I", "U", "U"]
    lp = [[math.log(0.9) if vocab[k] == u else math.log(0.1 / (len(vocab) - 1)) for k in range(len(vocab))] for u in seq]
    hyps = lexicon_beam_search(lp, vocab, lex, {w: math.log(1 / 3) for w in lex})
    assert hyps and list(hyps[0][0]) == ["bob", "you"]
