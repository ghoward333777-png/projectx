"""Deterministic acoustic feature extraction (stdlib only).

Shared by LIL (voiceprint) and PIL (paralinguistics). Parses a WAV (base64 or bytes) with the
stdlib `wave` module and computes a small, DETERMINISTIC feature vector with pure Python/math:
duration, RMS/peak energy, zero-crossing rate, a crude autocorrelation pitch estimate, a
low/high energy-band ratio (brightness proxy), and an energy-envelope tempo proxy.

Honesty: these are simple, reproducible signal measurements — NOT a neural speaker model or a
neural emotion classifier. The same audio always yields the same vector. No LLM, no cloud.
"""

import base64 as _b64
import io as _io
import math as _math
import wave as _wave
from array import array as _array

MAX_SAMPLES = 480000   # cap (~30 s at 16 kHz) so analysis is bounded


def _load_wav(data):
    """bytes|base64 -> (samples:list[int], rate). Mono-mixed, 16-bit assumed; tolerant."""
    if isinstance(data, str):
        data = _b64.b64decode(data)
    wf = _wave.open(_io.BytesIO(data), "rb")
    rate = wf.getframerate() or 16000
    ch = wf.getnchannels() or 1
    width = wf.getsampwidth() or 2
    n = min(wf.getnframes(), MAX_SAMPLES)
    raw = wf.readframes(n)
    wf.close()
    if width != 2:
        # Only 16-bit PCM is handled precisely; approximate others as silence-safe empty.
        return [], rate
    a = _array("h")
    a.frombytes(raw[: (len(raw) // 2) * 2])
    if ch > 1:
        # downmix to mono by averaging channels
        mono = [sum(a[i:i+ch]) // ch for i in range(0, len(a) - ch + 1, ch)]
        return mono, rate
    return list(a), rate


def _rms(s):
    if not s:
        return 0.0
    return _math.sqrt(sum(x * x for x in s) / len(s))


def _zcr(s):
    if len(s) < 2:
        return 0.0
    z = sum(1 for i in range(1, len(s)) if (s[i - 1] >= 0) != (s[i] >= 0))
    return z / (len(s) - 1)


def _pitch_hz(s, rate):
    """Crude autocorrelation pitch on a central 50 ms window; 0 if unvoiced/none."""
    if len(s) < rate // 10:
        return 0.0
    win = int(rate * 0.05) or 1
    mid = len(s) // 2
    seg = s[max(0, mid - win): mid + win]
    if len(seg) < 64:
        return 0.0
    lo = int(rate / 400)   # 400 Hz
    hi = int(rate / 70)    # 70 Hz
    best_lag, best = 0, 0.0
    for lag in range(max(1, lo), min(hi, len(seg) - 1)):
        acc = 0.0
        for i in range(0, len(seg) - lag, 2):   # stride 2 for speed, deterministic
            acc += seg[i] * seg[i + lag]
        if acc > best:
            best, best_lag = acc, lag
    return round(rate / best_lag, 1) if best_lag else 0.0


def _band_ratio(s):
    """Low vs high energy proxy via a 1st-difference (high-pass) energy ratio (brightness)."""
    if len(s) < 2:
        return 0.0
    hi = sum((s[i] - s[i - 1]) ** 2 for i in range(1, len(s)))
    lo = sum(x * x for x in s) or 1
    return round(hi / lo, 4)


def _envelope_tempo(s, rate):
    """Energy-envelope peak rate (syllable/beat proxy) in events/sec."""
    if len(s) < rate // 5:
        return 0.0
    frame = max(1, rate // 50)   # 20 ms frames
    env = []
    for i in range(0, len(s) - frame, frame):
        seg = s[i:i + frame]
        env.append(sum(abs(x) for x in seg) / frame)
    if len(env) < 3:
        return 0.0
    thr = (sum(env) / len(env)) * 1.3
    peaks = sum(1 for i in range(1, len(env) - 1)
                if env[i] > thr and env[i] >= env[i - 1] and env[i] > env[i + 1])
    secs = len(s) / rate
    return round(peaks / secs, 2) if secs else 0.0


def features(data):
    """Return a deterministic feature dict for a WAV (bytes or base64)."""
    s, rate = _load_wav(data)
    if not s:
        return {"ok": False, "error": "could not read 16-bit PCM WAV audio"}
    dur = round(len(s) / rate, 3)
    peak = max((abs(x) for x in s), default=0)
    rms = _rms(s)
    return {
        "ok": True, "rate": rate, "samples": len(s), "duration_s": dur,
        "rms": round(rms, 2), "peak": peak,
        "loudness_dbfs": round(20 * _math.log10((rms / 32768.0) + 1e-9), 1),
        "zcr": round(_zcr(s), 4),
        "pitch_hz": _pitch_hz(s, rate),
        "brightness": _band_ratio(s),
        "tempo_eps": _envelope_tempo(s, rate),   # envelope events / second
    }


def vector(feat):
    """A compact, comparable numeric vector from a features dict (for voiceprint matching)."""
    if not feat.get("ok"):
        return []
    return [feat["pitch_hz"], feat["zcr"] * 1000, feat["brightness"] * 1000,
            feat["tempo_eps"] * 10, min(feat["rms"], 32768) / 100.0]
