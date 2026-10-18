# Media Sanitizer

A local, dependency-free (Python 3.9+ standard library only) tool that strips metadata from **your own**
audio/video files and re-exports them through named presets. It runs as a small web server on your
machine with a drag-and-drop page, and as a CLI. Every piece of state is JSON: config, presets,
job specs, job records and per-file reports.

## What it removes

- Container tags (title, comment, artist, encoder, creation_time, XMP/user-data items, …)
- Per-stream tags (titles, handler names, encoder strings)
- Chapters
- Data, timecode and attachment streams (only video, audio and optionally subtitles are kept)
- ffmpeg's own version string (`-fflags +bitexact`)

Then it re-probes the output and writes a before/after JSON report with a `clean` / `review` verdict.
ffmpeg always writes a few structural fields (`major_brand`, `handler_name`, `language`, a
versionless `Lavf`/`Lavc` label). These are listed in `technical_tags` and don't affect the verdict.
If ExifTool is installed, the report also lists any descriptive tags it can still see.

## Requirements

- Python 3.9+
- `ffmpeg` and `ffprobe` on PATH (`brew install ffmpeg`, `apt install ffmpeg`, or ffmpeg.org builds on Windows)
- Optional: `exiftool` for a second opinion in the verification step

## Run

```bash
cd media-sanitizer
python3 app.py serve                 # http://127.0.0.1:8090
```

Drop files on the page, or paste a path to a file or folder that is already on the machine. Jobs run
one at a time in the background; each row shows progress, the verdict, a download link and the
full JSON report.

CLI equivalents:

```bash
python3 app.py presets
python3 app.py validate                                  # check config/*.json
python3 app.py probe clip.mp4                            # metadata as JSON
python3 app.py run ~/Videos/exports --preset youtube_ready --out ~/Videos/clean --report run.json
python3 app.py job job.example.json                      # same thing, driven by a JSON spec
```

`run` and `job` exit non-zero if any file failed.

## JSON architecture

| File | Role |
|---|---|
| `config/settings.json` | host/port, workspace, default output dir, suffix, accepted extensions, binary paths, technical-tag allowlist, `allowed_input_roots` |
| `config/presets.json` | the presets; add one by adding an object, nothing else to change |
| `job.example.json` | batch spec for `app.py job` |
| `workspace/jobs/<id>.json` | one record per web job (status, progress, error, report); reloaded on restart |
| report (inside each job, or `--report`) | `before`/`after` probes, `removed`, `remaining`, `verdict`, `notes`, exact ffmpeg `command` |

### Preset schema

```json
"my_preset": {
  "description": "Shown in the UI",
  "container": "mp4 | mov | mkv | source",
  "reencode": true,
  "video": {"codec": "libx264|libx265|ffv1|prores_ks|copy", "crf": 18, "preset": "medium",
            "profile": "high", "pix_fmt": "yuv420p"},
  "audio": {"codec": "aac|libopus|flac|pcm_s16le|pcm_s24le|libmp3lame|copy", "bitrate": "192k",
            "sample_rate": 48000, "loudnorm": {"I": -14, "TP": -1, "LRA": 11}},
  "faststart": true,
  "keep_subtitles": false
}
```

`reencode: false` means stream copy (no quality loss, metadata only). Leave out `video` or `audio`
to drop that stream type. `validate` rejects unknown codecs and codec/container mismatches.

Shipped presets: `youtube_ready`, `mobile`, `archive` (FFV1 + FLAC), `master` (ProRes 422 HQ +
24-bit PCM), `lossless_sanitize` (stream copy).

### HTTP API

| Method | Path | Body / result |
|---|---|---|
| GET | `/api/health` | ffmpeg / ffprobe / exiftool versions |
| GET | `/api/presets` | `{default, presets}` |
| GET | `/api/settings` | public settings |
| POST | `/api/upload?name=clip.mp4` | raw file bytes → `{path}` |
| POST | `/api/jobs` | `{"inputs": [paths], "preset": "...", "output_dir": "...", "recursive": true}` → `{jobs}` |
| GET | `/api/jobs`, `/api/jobs/<id>` | job list (light) / full job with report |
| GET | `/api/download/<id>` | the sanitized file |
| POST | `/api/probe` | `{"path": file-or-folder}` → probes |
| POST | `/api/jobs/clear` | removes finished job records |

## Security note

The server binds to `127.0.0.1` and has no login. It can read any path you give it. If you change
`host` to expose it on your network, set `allowed_input_roots` in `settings.json` so it can only
read inside those folders (plus its own workspace).

## Scope

This tool removes metadata from files and re-encodes them. It does not detect or remove AI
provenance watermarks or content credentials, and it doesn't alter audio to get past AI-content
classifiers. Platforms such as YouTube ask creators to disclose realistic synthetic or altered
media. Removing metadata doesn't change whether that disclosure applies.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Unit tests cover config validation, command building and report diffing. Integration tests
(skipped without ffmpeg) generate a tagged sample, run every preset, and check for a `clean`
verdict. They also run the HTTP upload → job → download flow.
