# Data preparation

| Manifest | Built by | Source |
|---|---|---|
| `features_train/test.jsonl` | `vse.bridge.querybook.export_reservoir(db, out)` or `scripts/train_lip_reading.py --reservoir <language.sqlite>` | QueryBook's ingestion reservoir (your own consented recordings, numbers only) |
| `viseme_to_motion_*.jsonl` | `scripts/build_motion_dataset.py <language.sqlite> out.jsonl` | the same reservoir (measured mouth numbers as targets) |
| `asr_phonemes_*.jsonl` | your aligner (e.g. Montreal Forced Aligner) | LibriSpeech (CC BY 4.0), Common Voice (CC0) |
| video lip reading | your crop extractor + `vse.visual.landmarks.mouth_crop` | LRS2/LRS3 (BBC research licences: non-commercial), or your own consented recordings |

Check every dataset's licence before training anything you will ship; record the licence of each manifest next to it.
