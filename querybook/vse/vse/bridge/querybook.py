"""QueryBook ⇄ stage 2.

  load_stage1(apps_dir)        import QueryBook's stage-1 engine (apps/language/vse.py) for its formats, lexicon and
                               synthetic benchmark speakers.
  export_reservoir(db, out)    the Language Builder's ingestion reservoir (numbers only) → training manifests for the
                               feature lip reader (units = visemes, from the per-frame labels) and the motion model.
  Stage2LipReader              a trained LipReader + lexicon beam search, answering in stage 1's JSON shape.
  benchmark(...)               stage 1's synthetic benchmark with stage 2 as a third column."""
from __future__ import annotations

import json
import os
import sqlite3
import sys

import torch

from vse.common.types import MOUTH_PARAMS, VISEMES
from vse.reading.phoneme_to_text import lexicon_beam_search
from vse.reading.visual_to_phoneme import UNITS, LipReader


def load_stage1(apps_dir):
    """QueryBook's apps/language/vse.py, loaded as module 'qb_vse_stage1' (its own name clashes with this package)."""
    import importlib.util
    if "qb_vse_stage1" in sys.modules:
        return sys.modules["qb_vse_stage1"]
    lang = os.path.join(os.path.abspath(apps_dir), "language")
    path = os.path.join(lang, "vse.py")
    if not os.path.isfile(path):
        raise ImportError("apps/language/vse.py not found under %s" % apps_dir)
    if lang not in sys.path:
        sys.path.append(lang)                             # for its own imports (lipread, visemes, voicedsp, vocab …)
    spec = importlib.util.spec_from_file_location("qb_vse_stage1", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["qb_vse_stage1"] = mod
    spec.loader.exec_module(mod)
    return mod


def frames_to_tensor(frames, fps=30):
    """QueryBook frames (browser dicts with _fv or tracker fields, or reservoir [t, f1..f13] rows) → [T, 13]."""
    rows = []
    for f in frames:
        if isinstance(f, (list, tuple)):
            rows.append((float(f[0]), list(f[1:1 + len(MOUTH_PARAMS)])))
        elif isinstance(f, dict) and f.get("face") and "_fv" in f:
            rows.append((float(f["t"]), f["_fv"]))
    rows.sort(key=lambda r: r[0])
    if not rows:
        return torch.zeros(0, len(MOUTH_PARAMS))
    out, k, t = [], 0, rows[0][0]
    while t <= rows[-1][0] + 1e-9:
        while k + 1 < len(rows) and rows[k + 1][0] <= t:
            k += 1
        out.append(rows[k][1])
        t += 1.0 / fps
    return torch.tensor(out, dtype=torch.float32)


def units_from_labels(labels):
    seq = []
    for lb in labels:
        v = lb[1] if lb and len(lb) > 1 else "sil"
        if v in VISEMES and (not seq or seq[-1] != v) and v != "sil":
            seq.append(v)
    return seq


def export_reservoir(db_path, out_dir):
    """Writes features_train.jsonl / features_test.jsonl (the reservoir's own fixed split). Returns counts."""
    os.makedirs(out_dir, exist_ok=True)
    db = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    counts = {"train": 0, "test": 0}
    files = {k: open(os.path.join(out_dir, "features_%s.jsonl" % k), "w", encoding="utf-8") for k in counts}
    try:
        for text, frames, labels, split in db.execute("SELECT text, frames, labels, split FROM ingest_reservoir ORDER BY id"):
            fr, lb = json.loads(frames), json.loads(labels or "[]")
            units = units_from_labels(lb)
            if len(fr) < 5 or not units:
                continue
            files[split].write(json.dumps({"text": text, "features": fr, "units": units}) + "\n")
            counts[split] += 1
    finally:
        for f in files.values():
            f.close()
        db.close()
    return counts


class Stage2LipReader:
    def __init__(self, cfg, checkpoint, stage1, lang="en", device="cpu", fps=30):
        self.model = LipReader(cfg, "features", "viseme").to(device).eval()
        self.model.load_state_dict(torch.load(checkpoint, map_location=device)["model"])
        self.s1, self.lang, self.device, self.fps = stage1, lang, device, fps

    def _lexicon(self, words=()):
        lx = self.s1.lexicon(self.lang, tuple(w.lower() for w in words), unit="viseme")
        lexicon = {g["words"][0]: g["seq"] for g in lx.values()}
        priors = {g["words"][0]: g["logp"] for g in lx.values()}
        return lexicon, priors, {g["words"][0]: g["words"][1:8] for g in lx.values()}

    @torch.no_grad()
    def lip_read(self, frames, words=(), beam=16):
        x = frames_to_tensor(frames, self.fps).unsqueeze(0).to(self.device)
        if x.size(1) < 5:
            return {"error": "No face was found in enough frames to read the lips."}
        lp = self.model(x)[0].cpu()
        lexicon, priors, same = self._lexicon(words)
        hyps = lexicon_beam_search(lp.tolist(), UNITS["viseme"], lexicon, priors, beam=beam)
        best = list(hyps[0][0]) if hyps else []
        return {"engine": "VSE stage 2 (Conformer-CTC lip reader + lexicon beam search)",
                "lipread": {"text": " ".join(best), "segments": [{"words": [{"word": w, "same_on_lips": same.get(w, [])} for w in best]}]}}


def benchmark(stage2_reader, stage1, speakers=4, sentences=None):
    """Stage 1's synthetic speakers and sentences; stage 2's word error rates next to stage 1's."""
    sents = sentences or stage1.BENCH_SENTENCES
    rnd = stage1._rng("vse-bench", stage1.VERSION)
    vocab = tuple(sorted({w for s in sents for w in s.split()}))
    g = lambda ws: [stage1._group_of(w) for w in ws]
    res = {"stage1": {"wer": [], "lookalike": []}, "stage2": {"wer": [], "lookalike": []}}
    for _ in range(speakers):
        spk = stage1._speaker(rnd)
        for s in sents:
            frames, _, _ = stage1.synthetic_frames(s, spk, rnd)
            ref = s.split()
            h1 = stage1.lip_read(frames, "en", vocab)["lipread"]["text"].split()
            h2 = stage2_reader.lip_read(frames, vocab)["lipread"]["text"].split()
            for k, h in (("stage1", h1), ("stage2", h2)):
                res[k]["wer"].append(stage1._wer(ref, h)); res[k]["lookalike"].append(stage1._wer(g(ref), g(h)))
    return {k: {m: round(sum(v) / len(v), 3) for m, v in d.items()} for k, d in res.items()}
