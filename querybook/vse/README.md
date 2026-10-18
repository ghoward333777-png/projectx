# Visual Speech Engine — stage 2 (trainable models)

The Visual Speech Engine (VSE) is built in two stages:

| | Stage 1 | Stage 2 (this package) |
|---|---|---|
| Where | inside QueryBook's Language Builder: `apps/language/vse.py` | here: `querybook/vse/`, a separate Python package |
| How | signal processing, geometry, speech science: dominance-model coarticulation, Gaussian mouth models calibrated by analysis-by-synthesis, a hidden-Markov word network | neural networks (PyTorch): Conformer-CTC, Transformers, ECAPA, ResNet, conditional NeRF, diffusion |
| Needs | any computer, standard Python only, no GPU | GPUs for training, licensed data, your own trained checkpoints |
| Status | working, in the app, measured by its benchmark | **complete code, untrained** — every model has tests and a training script; nothing useful comes out until you train it |

Both stages use the same data formats (`vse/common/types.py` mirrors the stage-1 JSON), the same mouth-feature space
(13 numbers per frame from the MediaPipe face tracker), the same API bodies and the same benchmark, so each trained
model can replace its stage-1 counterpart one at a time, and only when the benchmark shows it is better.

## Subsystems → modules

| Spec subsystem | Module | Model | Trains on |
|---|---|---|---|
| APS — phonemes | `vse/audio/phonemes.py` | Conformer + CTC over log-mel (×4 subsampling); greedy CTC gives phoneme times | audio + phoneme sequences |
| APS — prosody | `vse/audio/prosody.py` | YIN pitch, RMS energy, voicing, speaking rate (signal processing) | — |
| APS — emotion | `vse/audio/emotion.py` | Transformer over log-mel + prosody → valence/arousal/dominance + 5 categories | emotion corpora |
| APS — speaker | `vse/audio/speaker.py` | ECAPA-style SE-Res2 + attentive statistics pooling + ArcFace | speaker-labelled speech |
| VPS — landmarks, boxes, mouth crops | `vse/visual/landmarks.py` | MediaPipe Face Landmarker (optional dependency) — same tracker as QueryBook's page | — |
| VPS — 3D face | `vse/visual/mesh.py` | linear morphable model fitted to landmarks over a clip (Adam, temporal smoothness) | — (bring a model file) |
| VPS — lighting | `vse/visual/lighting.py` | 2nd-order spherical harmonics: closed-form fit, or a CNN | renders with known light |
| VPS — camera | `vse/visual/camera.py` | intrinsics from field of view; extrinsics from head pose; background motion by phase correlation | — |
| VPS — identity | `vse/visual/identity.py` | ResNet + ArcFace | consented face crops |
| LSG — phoneme → viseme | `vse/sync/phoneme_to_viseme.py` | rule table baseline + Transformer per frame (phoneme, prosody, emotion streams) | aligned audio + tracked faces |
| LSG/FMS — face motion | `vse/sync/motion_synthesizer.py` | multi-stream Transformer, cross-attention to prosody/emotion/speaker; L2 + velocity + lip-closure losses | tracked or reconstructed face motion |
| LRE — front-ends | `vse/reading/mouth_features.py` | video: 3D conv + ResNet on mouth crops; features: the 13 tracker numbers (+ velocity) | silent video + transcripts, or QueryBook's reservoir |
| LRE — decoder | `vse/reading/visual_to_phoneme.py` | Conformer + CTC over visemes or phonemes | as above |
| LRE — text | `vse/reading/phoneme_to_text.py` | CTC prefix beam search constrained to a pronunciation trie, word priors, insertion bonus | — |
| VRD — option A | `vse/render/nerf_renderer.py` | conditional NeRF (identity/expression/light) with volume rendering | per-person video with cameras |
| VRD — option B | `vse/render/diffusion_renderer.py` | conditional U-Net DDPM inpainting the lower face, known pixels kept | per-person video |
| VRD — compositing | `vse/render/compositor.py` | colour matching + feathered alpha blending | — |
| COL — pipelines | `vse/pipeline/*.py` | lip sync and lip reading; each stage falls back to stage 1 when no checkpoint is configured | — |
| COL — API | `vse/api/server.py` | FastAPI: `/vse/lip_sync`, `/vse/lip_read`, `/vse/job/{id}`, plus QueryBook-compatible `/api/vse/…` | — |
| Bridge | `vse/bridge/querybook.py` | loads stage 1, exports the reservoir, runs stage 1's benchmark with stage 2 as a third column | — |

## Training (scripts/)

Every script takes `--config configs/<name>.yaml` (GPU defaults), `--tiny` (CPU smoke run), `--steps N`, `--device`.
They share one loop (`vse/common/train.py`): AdamW, warm-up + cosine schedule, mixed precision on GPU, gradient
clipping, validation, best/last checkpoints in `checkpoints/`.

```
python scripts/train_asr_phonemes.py   --config configs/asr_phonemes.yaml
python scripts/train_emotion.py        --config configs/emotion.yaml
python scripts/train_speaker_encoder.py --config configs/speaker_encoder.yaml
python scripts/train_identity_encoder.py --config configs/identity_encoder.yaml
python scripts/train_lighting.py       --config configs/lighting.yaml
python scripts/train_phoneme_to_viseme.py --config configs/phoneme_to_viseme.yaml
python scripts/build_motion_dataset.py <language.sqlite> data/manifests/viseme_to_motion_train.jsonl
python scripts/train_viseme_to_motion.py --config configs/viseme_to_motion.yaml
python scripts/train_lip_reading.py    --reservoir <QueryBook-Data/language/language.sqlite>   # your own recordings
python scripts/train_lip_reading.py    --config configs/lip_reading_cpu.yaml --synthetic 1200  # synthetic pre-training
python scripts/train_renderer_nerf.py  --config configs/renderer_nerf.yaml
python scripts/train_renderer_diffusion.py --config configs/renderer_diffusion.yaml
python scripts/train_end_to_end.py     --config configs/end_to_end.yaml --reader checkpoints/lip_reading.best.pt
python scripts/benchmark.py            --config configs/lip_reading_cpu.yaml --checkpoint checkpoints/lip_reader_cpu.best.pt
```

`train_end_to_end.py` fine-tunes the motion synthesizer with the frozen lip reader as a lip-sync expert: the
generated mouth must be readable as the intended visemes, not only close in L2.

Order (spec §10.2): APS and VPS encoders → 3D motion data → phoneme→viseme → motion → lip reader → renderer →
end-to-end. Train the lip reader first on the reservoir if you have recordings: it needs no pictures.

## Data and licences — read before training anything you will ship

* **LRS2 / LRS3** (BBC): research licences, non-commercial. **VoxCeleb**: check its terms of use for your purpose.
  **IEMOCAP / MSP-Podcast**: research agreements. **LibriSpeech**: CC BY 4.0. **Common Voice**: CC0.
* **MS-Celeb-1M** and **VGGFace2** were withdrawn by their creators; do not use them.
* **FLAME** (3D face model): non-commercial research licence. `mesh.py` takes any linear model file.
* Faces and voices are personal data. Train identity, rendering and voice models only on people who agreed.
  The pipeline refuses to render a real person's face without `consent=True`, and rendered results are synthetic
  media: label them as such wherever they are shown.

## Tests

```
pip install -r requirements.txt pytest httpx
pytest -q          # 18 tests: shapes, a CTC model learning a toy task, YIN pitch, SH recovery, 3D fitting,
                   # beam search, NeRF/diffusion, compositing, and the API answering through stage 1
```

## Demonstration run (CPU, synthetic data)

`scripts/train_lip_reading.py --config configs/lip_reading_cpu.yaml --synthetic 1200` trains a small lip reader
(96-dim, 3 Conformer layers) on 1,200 utterances spoken by stage 1's synthetic speakers using the 18 calibration
sentences, then `scripts/benchmark.py` reads the 16 benchmark sentences (never seen in training) with both engines.
See RESULTS below — a demonstration that the loop works end to end, not a claim about real faces: the synthetic
speakers come from stage 1's own lip-sync model.

### RESULTS (18 October 2026, CPU, about 9 minutes of training)

| Lip reading, 64 synthetic utterances of unseen sentences | Exact word error rate | Look-alike word error rate |
|---|---|---|
| Stage 1 (in QueryBook) | 71% | 61% |
| Stage 2, small CPU model, 1,200 synthetic utterances of 18 sentences | 85% | 77% |

Stage 2 is **worse** here, and that is the expected result: a network trained on 18 sentences learns those
sentences, not lip reading. It shows the loop working end to end (generate data → train → load → benchmark with the
same measures as stage 1) and why the rule holds: **a stage-2 model replaces its stage-1 counterpart only when the
shared benchmark says it is better.** Real gains need real data at scale — the reservoir's recordings of real faces,
licensed audio-visual corpora — and GPU training with the full configs.
