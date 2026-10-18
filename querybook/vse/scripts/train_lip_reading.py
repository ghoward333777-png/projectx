"""Lip reader (features front-end, viseme units, CTC).

Data sources:
  --reservoir DB      QueryBook's language database (ingestion reservoir: real faces, numbers only, the user's own)
  --synthetic N       N utterances from stage 1's synthetic speakers (analysis-by-synthesis pre-training)
  --config            manifests (features_train.jsonl / features_test.jsonl) e.g. from bridge.export_reservoir"""
import json
import os

from _common import args, loaders

from vse.bridge.querybook import export_reservoir, load_stage1, units_from_labels
from vse.common.data import FeatureCTCDataset
from vse.common.train import train
from vse.reading.visual_to_phoneme import UNITS, LipReader, lipread_loss

HERE = os.path.dirname(os.path.abspath(__file__))
a, cfg = args({"--reservoir": dict(default=None), "--synthetic": dict(type=int, default=0), "--apps": dict(default=os.path.join(HERE, "..", "..", "apps"))})
cfg.name = cfg.name if cfg.name != "model" else "lip_reader"


def synthetic_rows(n, seed):
    s1 = load_stage1(a.apps)
    rnd = s1._rng("vse-stage2-train", seed)
    sents = [s.lower().strip(".?!,") for s in s1.CALIBRATION_SENTENCES]
    rows = []
    for i in range(n):
        spk = s1._speaker(rnd)
        spk["fps"] = 30
        text = " ".join(w.strip(",.?!") for w in sents[i % len(sents)].split())
        frames, truth, tr = s1.synthetic_frames(text, spk, rnd)
        units = []
        for s in tr["visemes"]:
            if s["v"] != "sil" and (not units or units[-1] != s["v"]):
                units.append(s["v"])
        rows.append({"text": text, "features": [[f["t"]] + f["_fv"] for f in frames], "units": units})
    return rows


if a.synthetic:
    train_rows, val_rows = synthetic_rows(a.synthetic, 1), synthetic_rows(max(8, a.synthetic // 10), 2)
elif a.reservoir:
    out = os.path.join(HERE, "..", "data", "manifests")
    print("exported:", export_reservoir(a.reservoir, out))
    train_rows, val_rows = os.path.join(out, "features_train.jsonl"), os.path.join(out, "features_test.jsonl")
else:
    train_rows, val_rows = cfg.data.train_manifest, cfg.data.val_manifest
vocab = UNITS["viseme"]
tl, vl = loaders(FeatureCTCDataset(train_rows, vocab), FeatureCTCDataset(val_rows, vocab), cfg, FeatureCTCDataset.collate)
print(json.dumps(train(LipReader(cfg, "features", "viseme"), lipread_loss, tl, vl, cfg, a.steps)))
