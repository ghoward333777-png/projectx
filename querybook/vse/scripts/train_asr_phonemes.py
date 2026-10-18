"""Phoneme ASR (Conformer-CTC). Manifest rows: {"audio": "x.wav", "phonemes": [...]} — e.g. LibriSpeech with
Montreal Forced Aligner phonemes, Common Voice (CC0) for more languages."""
from _common import args, loaders

from vse.audio.phonemes import PhonemeASR, ctc_loss
from vse.common.data import AudioCTCDataset
from vse.common.train import train

a, cfg = args()
cfg.name = cfg.name if cfg.name != "model" else "asr_phonemes"
tl, vl = loaders(AudioCTCDataset(cfg.data.train_manifest, cfg.data.sample_rate), AudioCTCDataset(cfg.data.val_manifest, cfg.data.sample_rate), cfg, AudioCTCDataset.collate)
train(PhonemeASR(cfg), ctc_loss, tl, vl, cfg, a.steps)
