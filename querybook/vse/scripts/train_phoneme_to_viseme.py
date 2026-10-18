"""Context-dependent phoneme → viseme network (per frame). Manifest rows as in vse.common.data.P2VDataset."""
from _common import args, loaders

from vse.common.data import P2VDataset
from vse.common.train import train
from vse.sync.phoneme_to_viseme import PhonemeToVisemeNet, p2v_loss

a, cfg = args()
cfg.name = cfg.name if cfg.name != "model" else "phoneme_to_viseme"
tl, vl = loaders(P2VDataset(cfg.data.train_manifest), P2VDataset(cfg.data.val_manifest), cfg, P2VDataset.collate)
train(PhonemeToVisemeNet(cfg), p2v_loss, tl, vl, cfg, a.steps)
