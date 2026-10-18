"""Audio/video loading and saving. WAV via the standard library; other formats and video via ffmpeg (if installed)."""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import wave

import numpy as np


def load_wav(path_or_bytes, target_sr=16000) -> np.ndarray:
    data = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else None
    if data is None and not str(path_or_bytes).lower().endswith(".wav"):
        return load_audio_ffmpeg(path_or_bytes, target_sr)
    with wave.open(io.BytesIO(data) if data is not None else str(path_or_bytes), "rb") as w:
        sr, ch, width, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    dt = {1: np.uint8, 2: np.int16, 4: np.int32}[width]
    x = np.frombuffer(raw, dtype=dt).astype(np.float32)
    if width == 1:
        x = (x - 128.0) / 128.0
    else:
        x /= float(2 ** (8 * width - 1))
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return resample(x, sr, target_sr)


def resample(x: np.ndarray, sr: int, target: int) -> np.ndarray:
    if sr == target:
        return x
    n = int(round(len(x) * target / sr))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def load_audio_ffmpeg(path, target_sr=16000) -> np.ndarray:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is needed to read %s" % path)
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(target_sr), "-f", "f32le", "-"], capture_output=True, check=True)
    return np.frombuffer(out.stdout, dtype=np.float32).copy()


def load_video_frames(path, fps=None, max_frames=None):
    """→ (frames uint8 [N, H, W, 3], fps). Uses ffmpeg (raw RGB pipe)."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is needed to read video")
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate",
                            "-of", "json", str(path)], capture_output=True, check=True)
    st = json.loads(probe.stdout)["streams"][0]
    w, h = int(st["width"]), int(st["height"])
    num, den = (int(x) for x in st["r_frame_rate"].split("/"))
    src_fps = num / den if den else 25.0
    args = ["ffmpeg", "-v", "error", "-i", str(path)] + (["-vf", "fps=%s" % fps] if fps else []) + ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(args, capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, h, w, 3)
    if max_frames:
        frames = frames[:max_frames]
    return frames, float(fps or src_fps)


def save_video(frames: np.ndarray, path, fps: float, audio_path=None):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is needed to write video")
    h, w = frames.shape[1:3]
    args = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (w, h), "-r", str(fps), "-i", "-"]
    if audio_path:
        args += ["-i", str(audio_path), "-shortest", "-c:a", "aac"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(args, input=np.ascontiguousarray(frames).tobytes(), check=True)
    return str(path)
