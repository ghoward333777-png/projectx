"""ffprobe wrapper returning a plain JSON-serialisable summary."""

import json
import shutil
import subprocess


def probe(path, ffprobe="ffprobe"):
    cmd = [ffprobe, "-v", "error", "-show_format", "-show_streams", "-show_chapters",
           "-of", "json", path]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {out.stderr.strip()}")
    data = json.loads(out.stdout or "{}")
    fmt = data.get("format", {})
    return {
        "path": path,
        "format_name": fmt.get("format_name", ""),
        "duration": float(fmt.get("duration") or 0),
        "size": int(fmt.get("size") or 0),
        "format_tags": fmt.get("tags", {}),
        "chapters": len(data.get("chapters", [])),
        "streams": [
            {
                "index": s.get("index"),
                "codec_type": s.get("codec_type", ""),
                "codec_name": s.get("codec_name", ""),
                "width": s.get("width"),
                "height": s.get("height"),
                "tags": s.get("tags", {}),
                "side_data": [d.get("side_data_type", "") for d in s.get("side_data_list", [])],
            }
            for s in data.get("streams", [])
        ],
    }


def exiftool_tags(path, exiftool="exiftool"):
    """Descriptive tags ExifTool still sees, or None when ExifTool is not installed."""
    if not shutil.which(exiftool):
        return None
    out = subprocess.run([exiftool, "-j", "-G1", "-a", "-XMP:all", "-QuickTime:ItemList:all",
                          "-QuickTime:UserData:all", "-ID3:all", "-EXIF:all", path],
                         capture_output=True, text=True)
    try:
        rows = json.loads(out.stdout or "[]")
    except json.JSONDecodeError:
        return None
    return sorted(k for k in (rows[0] if rows else {}) if k != "SourceFile")
