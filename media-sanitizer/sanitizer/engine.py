"""Run one sanitize job: probe, ffmpeg, re-probe, diff into a JSON report."""

import os
import re
import subprocess
import tempfile
import time

from .commands import build_command, output_path_for
from .probe import exiftool_tags, probe


# ffmpeg's own versionless muxer/encoder labels (bitexact mode); they cannot be
# suppressed and carry nothing about the source, so they count as technical.
GENERIC_ENCODER = re.compile(r"^Lav[fc]( [\w-]+)?$")


def _descriptive(tags, technical):
    return {k: v for k, v in tags.items()
            if k.lower() not in technical
            and not (k.lower() == "encoder" and GENERIC_ENCODER.match(str(v)))}


def compare(before, after, technical_tags):
    """Diff two probe summaries into removed/remaining tag lists and a verdict."""
    technical = set(technical_tags)
    after_streams = {s["index"]: s for s in after["streams"]}
    removed_stream_tags, remaining_stream_tags = {}, {}
    for s in before["streams"]:
        kept = after_streams.get(s["index"], {}).get("tags", {})
        gone = [k for k in s["tags"] if k not in kept]
        if gone:
            removed_stream_tags[str(s["index"])] = sorted(gone)
    for s in after["streams"]:
        descriptive = _descriptive(s["tags"], technical)
        if descriptive:
            remaining_stream_tags[str(s["index"])] = descriptive

    remaining_format = _descriptive(after["format_tags"], technical)
    kept_types = {"video", "audio", "subtitle"}
    dropped = [f"{s['index']}:{s['codec_type']}/{s['codec_name']}"
               for s in before["streams"] if s["codec_type"] not in kept_types]
    notes = []
    if remaining_format or remaining_stream_tags:
        notes.append("Descriptive tags remain - review them before publishing.")
    if after["chapters"]:
        notes.append("Chapters remain in the output.")
    return {
        "removed": {
            "format_tags": sorted(k for k in before["format_tags"] if k not in after["format_tags"]),
            "stream_tags": removed_stream_tags,
            "chapters": before["chapters"] - after["chapters"],
            "dropped_streams": dropped,
        },
        "remaining": {"format_tags": remaining_format, "stream_tags": remaining_stream_tags,
                      "chapters": after["chapters"]},
        "verdict": "clean" if not notes else "review",
        "notes": notes,
    }


def sanitize(input_path, output_dir, preset_name, presets, settings, on_progress=None):
    """Process one file; returns the JSON report dict. Raises on failure."""
    preset = presets[preset_name]
    started = time.time()
    os.makedirs(output_dir, exist_ok=True)
    output_path = output_path_for(input_path, output_dir, preset, settings.get("output_suffix", "_clean"))
    if os.path.abspath(output_path) == os.path.abspath(input_path):
        raise ValueError("Output would overwrite the input; choose another folder or suffix.")

    before = probe(input_path, settings["ffprobe"])
    cmd = build_command(input_path, output_path, preset, settings["ffmpeg"])
    duration_us = before["duration"] * 1_000_000

    with tempfile.TemporaryFile(mode="w+") as errlog:
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errlog, text=True) as proc:
            for line in proc.stdout:
                key, _, value = line.strip().partition("=")
                if key == "out_time_us" and value.isdigit() and duration_us and on_progress:
                    on_progress(min(99, int(int(value) * 100 / duration_us)))
        code = proc.returncode
        if code != 0:
            errlog.seek(0)
            tail = errlog.read()[-2000:]
            raise RuntimeError(f"ffmpeg exited with {code}: {tail.strip()}")

    after = probe(output_path, settings["ffprobe"])
    report = {
        "input": input_path,
        "output": output_path,
        "preset": preset_name,
        "command": cmd,
        "seconds": round(time.time() - started, 2),
        "size_before": before["size"],
        "size_after": after["size"],
        "before": before,
        "after": after,
    }
    report.update(compare(before, after, settings["technical_tags"]))
    exif = exiftool_tags(output_path, settings.get("exiftool", "exiftool"))
    report["exiftool_remaining"] = exif
    if exif:
        report["verdict"] = "review"
        report["notes"].append("ExifTool still reports descriptive tags: " + ", ".join(exif))
    if on_progress:
        on_progress(100)
    return report
