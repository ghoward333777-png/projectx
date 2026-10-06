# QueryBook/UFCS-FQL-TCP/IP Hybrid Video Compression Lab

A working prototype of a transport engine that speaks **UFCS/FQL** at the semantic
layer, rides on plain **TCP/IP**, and compresses every payload by content type —
video, audio, images and UFCS fact batches — between a producer (Node 1) and a
consumer (Node 2). It also carries **HLS**, **MPEG-DASH** and **RTMP** streams.

This app is separate from the Book Intelligence Studio in the repository root.
Like the Studio, it is plain PHP 8.1+ with no Composer, database or API keys.
ffmpeg and zstd are optional: the lab detects them and reports what is available.

```
Node 1 (producer)                                   Node 2 (consumer)
UFCS/FQL encoder → classifier → compressor          stream reader (resync) → verifier
→ framer → transport manager ══ control  :P   ══▶   → decompressor → UFCS/FQL decoder
     token buckets · window  ══ normal   :P+1 ══▶   → ingestion → QueryBook/UFCS store
                             ══ bulk     :P+2 ══▶     (+ HLS/DASH package rebuild)
                             ◀══ ACK (window, queue depth) on each connection
```

## Install (one step)

Pick one. Each ends with the dashboard at **http://127.0.0.1:8091**.

| You have | Run this in the `ufcs-transport-lab` folder | Then |
|---|---|---|
| Docker (any OS) | `docker compose up` | open http://127.0.0.1:8091 |
| Linux or macOS | `./install.sh` | `./start.sh` (opens the browser) |
| Windows | install [PHP 8.3](https://windows.php.net/download) and, for video, `winget install Gyan.FFmpeg` | double-click `start.bat` |

- `./install.sh` finds your package manager (apt, dnf, yum, apk, pacman, zypper or
  Homebrew), installs PHP, ffmpeg and zstd, checks the result and runs the self-tests.
  Use `--minimal` for PHP only, or `--dry-run` to see the commands first.
- The Docker image includes PHP, ffmpeg and zstd. Reports, received files and colorized
  output are saved in the `reports/`, `received/` and `colorized/` folders.
- Something not working? Run `php bin/doctor.php`. It lists what is present and what is
  missing, with the exact install command for your system. Only PHP 8.1+ is required.
  ffmpeg, zstd, Go and Rust are optional extras that add video, Zstd and the reference
  sender/receiver pairs.

## Run it

```bash
# Dashboard: overview, frame inspector, compression lab, live transfer,
# HLS · DASH · RTMP, benchmark (./start.sh runs this for you)
php -d upload_max_filesize=256M -d post_max_size=256M -S 127.0.0.1:8091 -t ufcs-transport-lab/web

# Two nodes from the command line
php ufcs-transport-lab/bin/receiver.php --port=9100 --out=received --repackage   # Node 2
php ufcs-transport-lab/bin/sender.php facts --port=9100 --count=20000 --sign     # Node 1
php ufcs-transport-lab/bin/sender.php query --port=9100 --fql='FIND fact WHERE entity = "France" RANK BY trust LIMIT 5'
php ufcs-transport-lab/bin/sender.php file  --port=9100 --file=clip.mp4 --kbps=1500
php ufcs-transport-lab/bin/sender.php ping|stats|shutdown --port=9100

# RTMP edge: OBS / ffmpeg publish to rtmp://host:1935/live/<key>
php ufcs-transport-lab/bin/rtmp-ingest.php --port=9100 --rtmp-port=1935 --key=YOUR_KEY

# Benchmark (local Node 2 over loopback, or --remote=host:9100 for two machines)
php ufcs-transport-lab/bin/bench.php --preset=quick        # smoke | quick | full
php ufcs-transport-lab/bin/inspect.php --demo              # decode captured frames

# Tests
php ufcs-transport-lab/tests/run.php
```

For two machines, start the receiver with `--host=0.0.0.0` and open ports P, P+1 and P+2.

## Video transit reports

`bin/video-report.php` runs video-on-demand and live video feeds from Node 1 to
Node 2 through emulated network paths (`bin/netem-proxy.php`: one-way delay and a
capacity cap in both directions). It measures each transfer at three points:

- **Before:** lossless FFV1 masters (studio graphics, and a high-motion Mandelbrot
  zoom), with their raw rate and ITU-T P.910 SI/TI, then each encode (H.264,
  H.265, AV1, HLS/DASH ladders, live x264 zerolatency).
- **During:** a per-frame trace on both nodes. Each frame's time is split into
  queue, serialisation, path and ACK return. The report also covers framing and
  modelled TCP/IP overhead, goodput, utilisation, jitter, and the live feeds'
  edge → Node 2 time and lag.
- **After:** whether Node 2's copy is bit-exact, Node 2's per-frame parse and
  verify cost, single-core media decode cost, PSNR/SSIM against the master, and
  RTMP repackaging time.

```bash
php ufcs-transport-lab/bin/video-report.php --preset=standard   # ~5 min; quick ≈ 45 s
# → reports/video-report.html (compression, transport efficiency,
#   decompression overhead, propagation) and reports/video-report.json
```

## Colorization: black and white to 1K, 4K and 16K

`bin/colorize.php` and the dashboard's **Colorization** tab implement the QueryBook
Semantic Colorization Engine (VCUM, Registry F22/F75). It needs no transport.

```bash
php ufcs-transport-lab/bin/colorize.php --demo --targets=1k,4k,16k
php ufcs-transport-lab/bin/colorize.php --in=old-photo.png --targets=1k,4k,16k \
    --scene="setting=harbour;era=1940s;time=overcast" \
    --fact="Old Mill|has_color|#B03A2E" --region="0.66,0.28,0.82,0.55=Old Mill"
```

What QueryBook/UFCS-FQL brings to it:

- **Colour comes from knowledge.** Every colour is a UFCS Fact Unit resolved by FQL:
  the material palette (`data/color_knowledge.jsonl`), scene priors, period film
  grading, lighting, and any facts supplied with the job, such as a landmark's
  known colour. The provenance manifest names the fact (fuid), source and trust
  behind each painted region.
- **Bounded confidence (F224).** A region's colour confidence is the lesser of the
  material classification and the fact's trust.
- **Withhold, don't fabricate (F182).** Below 0.35 confidence a region keeps its gray.
  Skin is deliberately low-trust: grayscale carries no evidence of a person's skin
  tone, so it stays gray unless the job supplies a fact.
- **Marking (F225).** Luminance is observed and preserved; colour is marked as
  reconstructed in file metadata and in `<name>.colorization.json`.
- **Determinism (F22).** Identical inputs and facts give byte-identical outputs.
- **Declared agents (F76).** The stages are ingest → knowledge → lighting →
  historical prior → material → colorist → upscale → marking, and each is logged.

Output sizes:

| Target | Size (16:9) | Stills | Video |
|---|---|---|---|
| 1K | 1024 × 576 | PNG | H.264 MP4 |
| 4K | 3840 × 2160 | PNG | H.265 MP4 |
| 16K | 15360 × 8640 | JPEG (PNG optional, about 170 MB) | JPEG frame sequence, capped by `--max-16k-frames` |

AV1 is the only common codec that allows 16K video, and SVT-AV1 marks 8K and above
as experimental, so 16K video is a frame sequence.

Upscaling resamples observed luminance (Lanczos plus mild sharpening). It does not
invent detail. Each output is checked for consistency with the source: brought back to
the source size, its luminance must match the source's (≥ 40 dB PSNR at a 1-pixel
blur). On the synthetic demo landscape the engine is about 74% closer to the true
colours than the gray input (CIE76 ΔE 8.7 vs 33.5).

Limits: material recognition uses local brightness, texture, position and how far a
brightness band runs across the frame. It is not a trained model, so ambiguous
regions (a flat wall that matches the sky) need a region fact. The demo scenes are
synthetic, built from the same materials the engine knows, so their score measures
the pipeline, not real-world accuracy.

## The UFCS-FQL/1 frame

All integers are big-endian. The header is exactly 32 bytes.

| Offset | Size | Field | Values |
|---|---|---|---|
| 0 | 2 | Magic | `0xF051` (the spec's "0xFQ10" is not hex: 0xF0 can never start UTF-8 text, then ASCII `Q`) |
| 2 | 1 | Version | 1 |
| 3 | 1 | MsgType | 0 FACT_BATCH · 1 STREAM_CHUNK · 2 CONTROL |
| 4 | 1 | ContentType | 0 TEXT · 1 IMAGE · 2 VIDEO · 3 AUDIO · 4 MIXED |
| 5 | 1 | CompressionType | 0 NONE · 1 ZSTD · 2 GZIP · 3 H264 · 4 OPUS · 5 WEBP · 6 H265 · 7 AV1 · 8 AAC · 9 UFCS_DICT |
| 6 | 2 | Flags | 0x01 control · 0x02 normal · 0x04 bulk · 0x08 SIGNED · 0x10 END_OF_STREAM · 0x20 ACK_REQUESTED |
| 8 | 4 | PayloadLen | cap 64 MiB |
| 12 | 4 | MetaLen | cap 1 MiB |
| 16 | 8 | MessageID | echoed in ACKs |
| 24 | 4 | Sequence | chunk number in a stream |
| 28 | 4 | Reserved | 0 |

After the header come the meta (UTF-8 JSON) and the payload (already compressed).
The footer is a CRC32 (IEEE) over header + meta + payload. When the frame is
SIGNED, a 64-byte Ed25519 signature over everything before it follows the CRC.
The meta carries `query_id`, `entity_ids`, `relation_ids`, `source_region`,
`source_node_id`, `priority`, `latency_target_ms` and `reliability`, plus
stream and package fields.

The stream reader (`FrameReader`) recovers from corruption. A frame that fails
its plausibility, CRC or signature check is dropped, and the reader rescans for
the next `F0 51 01` anchor. So a corrupt frame costs one frame, not the stream
(Registry F61). Golden bytes in `tests/frame-contract.php` are cross-checked
against Python's `struct` and `zlib`.

## What maps to what in the spec

| Spec | Where |
|---|---|
| UFCS/FQL semantic layer | `src/Ufcs.php`: records re-validate on arrival with SHA-256(norm(s)\|norm(p)\|norm(o)\|polarity), the Prototype Test Kit rule, including Python float formatting. Restated facts merge as corroboration. `src/Fql.php`: `FIND fact WHERE … RANK BY … LIMIT n` travels as CONTROL; answers come back as compressed FACT_BATCH. |
| Content-aware compression | `src/Codec.php`: ZSTD, GZIP, and UFCS_DICT (DEFLATE primed with the UFCS field dictionary). `src/MediaCodec.php`: H.264/H.265/AV1 with bitrate from link capacity and ladder downscaling, Opus/AAC (speech goes to 24 kHz mono), WebP with optional downscale. MIXED multipart payloads. |
| Batching | 1,000 facts per FACT_BATCH by default. Frame overhead is under 0.3%. |
| Priority classes and connections | `src/Transport.php`: one TCP connection per class (P, P+1, P+2), strict priority on a shared link. Each connection has a token bucket, and there is an optional link bucket. The receiver's ACK window limits frames in flight. |
| Streaming vs bulk | STREAM_CHUNK with sequence numbers and END_OF_STREAM + SHA-256, vs single-frame FACT_BATCH. Node 2 reassembles and checks for gaps. |
| HLS / MPEG-DASH | `src/Streaming.php`: multi-rendition packaging, then `Sender::sendPackage()` (segments on bulk, manifests last). Node 2 rebuilds the tree, refuses unsafe paths and hash mismatches, and verifies the package against its manifest. `web/media.php` serves it to hls.js and dash.js. |
| RTMP | `src/Rtmp.php`: a native RTMP ingest server (handshake, chunk stream, AMF0, publish flow, stream-key check) and a live bridge to STREAM_CHUNK (FLV). Node 2 repackages finished streams to HLS + DASH with `--repackage`. `RtmpPublisher` handles egress to any `rtmp://` endpoint. |
| Benchmark plan | `src/Benchmark.php` + `bin/bench.php`: text, images, video, audio, the mixed workload (3 connections vs 1 shared), and streaming. Reports compression ratio, MB/s, p50/p95 latency and CPU on both nodes, and checks the success criteria. Output: `reports/latest.html`. |
| Go / Rust prototypes | `ref/go` and `ref/rust` are standard-library-only sender/receiver pairs. `tests/interop-contract.php` checks they are wire-compatible with the PHP nodes in both directions. |

## Limits of the prototype

- The datasets are synthetic and deterministic: UFCS facts derived from the
  242-record sample, photo-like images, `testsrc2` video and tonal audio.
  Their ratios will differ from real archives. Point `bench.php` at a remote
  Node 2 and real media for production numbers.
- The link-capacity bucket simulates a 40–100 Mbps network on loopback. It does
  not model packet loss or retransmits. Use `tc netem` on Linux for that.
- RTMP covers ingest (publish) and egress (push). The lab does not serve RTMP
  *playback*; viewers use the HLS/DASH output. Repackaging runs once a stream
  ends, so the HLS/DASH output is not live yet.
- Lab node keys are derived from the node id so runs are reproducible. Replace
  `NodeKeys` with a real key store before using signatures for trust.
