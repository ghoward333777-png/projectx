"""Camera and screen-capture analysis of a speaking face: capture quality against the recommended set-up,
audio/video sync, and lip-reading v1. The browser tracks the face (MediaPipe Face Landmarker, bundled) and
sends one small record per video frame; everything here is plain arithmetic, so the same frames always give
the same answer.

Lip-reading v1 is honest about what lips can show: many sounds look the same on the lips ("homophenes":
pat / bat / mat), and the tongue is mostly hidden. So each frame is read as one of seven mouth classes,
words are matched by their class sequences (dynamic time warping), and every guess comes with the other
words that look identical. Checking a known script against the lips works far better than guessing freely.
"""
import math
import re

import visemes

# Mouth classes that a camera can tell apart.
CLASSES = {"P": "lips closed (p b m)", "F": "lower lip under teeth (f v)", "W": "rounded (o u w r ch)",
           "A": "wide open (a)", "E": "spread (e i)", "T": "tongue behind teeth (t d s n k l th)", "-": "rest"}
FROM_VISEME = {"sil": "-", "PP": "P", "FF": "F", "O": "W", "U": "W", "RR": "W", "CH": "W", "aa": "A", "E": "E", "I": "E",
               "TH": "T", "DD": "T", "kk": "T", "SS": "T", "nn": "T"}
# How alike two classes look (0 identical … 1 unrelated): used by the matcher.
_NEAR = {frozenset("PF"): 0.5, frozenset("TE"): 0.45, frozenset("TA"): 0.6, frozenset("WA"): 0.6, frozenset("EA"): 0.5,
         frozenset("WT"): 0.7, frozenset("-P"): 0.3, frozenset("-T"): 0.7}

# Recommended capture (shown on the capture screen and in Help; checked on every analysis).
GUIDE = {
    "framing": "Whole face, forehead to chin, filling 40–60% of the picture's height. Not just the mouth: the jaw, cheeks and "
               "chin carry speech too, and the tracker needs the whole face to find the lips.",
    "mouth_px": "The mouth at least 150 pixels wide in the picture (about 1080p at arm's length).",
    "resolution": "1080p (1920×1080) is best; 720p works. 4K adds file size, not accuracy — the tracker works on a small copy of the frame.",
    "frame_rate": "60 frames per second is best (lips move in 50–100 ms); 30 is the minimum. Below 25 fast sounds like p and b are missed.",
    "angle": "Face the camera: within about 20° left/right and 15° up/down.",
    "light": "Even light from the front (a window or lamp behind the camera). No strong light behind the head; no hard shadows across the mouth.",
    "clear": "Nothing over the mouth: no hand, microphone, mask or heavy beard shadow over the lips.",
    "screen": "Screen capture: play the video full size (not a small preview) at normal speed, and share the tab with its audio.",
    "sound": "Microphone 20–30 cm away; a quiet room. Clear sound lets the app check sync and time the words.",
}


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def frame_class(fr):
    """One video frame → a mouth class. fr has 'gap' (lip opening ÷ mouth width, from landmarks) and 'bs'
    (MediaPipe blendshape scores 0..1)."""
    bs = fr.get("bs") or {}
    g = lambda k: _f(bs.get(k))
    gap = _f(fr.get("gap"))
    jaw = g("jawOpen")
    press = max(g("mouthClose"), (g("mouthPressLeft") + g("mouthPressRight")) / 2)
    roll_lo = g("mouthRollLower")
    rnd = max(g("mouthFunnel"), g("mouthPucker"))
    spread = max((g("mouthStretchLeft") + g("mouthStretchRight")) / 2, (g("mouthSmileLeft") + g("mouthSmileRight")) / 2)
    if gap < 0.035 and roll_lo > 0.3:
        return "F"
    if gap < 0.04:
        return "P" if press > 0.12 or jaw < 0.08 else "T"
    if rnd > 0.35:
        return "W"
    if jaw > 0.35 or gap > 0.32:
        return "A"
    if spread > 0.25:
        return "E"
    return "T"


def runs(seq, min_len=2):
    """Class per frame → [[class, frames]] with one-frame flickers merged into a neighbour."""
    out = []
    for c in seq:
        if out and out[-1][0] == c:
            out[-1][1] += 1
        else:
            out.append([c, 1])
    changed = True
    while changed and len(out) > 1:
        changed = False
        for i, (c, n) in enumerate(out):
            if n < min_len:
                j = i - 1 if i > 0 and (i == len(out) - 1 or out[i - 1][1] >= out[i + 1][1]) else i + 1
                out[j][1] += n
                del out[i]
                changed = True
                break
        merged = []
        for c, n in out:
            if merged and merged[-1][0] == c:
                merged[-1][1] += n
            else:
                merged.append([c, n])
        out = merged
    return out


def word_classes(phonemes):
    """A word's phonemes [(sym, viseme, weight)] → collapsed class string, e.g. 'hello' → 'TETW'."""
    s = ""
    for _, v, _ in phonemes:
        c = FROM_VISEME.get(v, "T")
        if not s or s[-1] != c:
            s += c
    return s


PAUSE = 0.15


def _cost(a, b):
    return 0.0 if a == b else _NEAR.get(frozenset((a, b)), 1.0)


def dtw(obs, ref):
    """Mean step cost of the best warping path between two class strings (0 identical … 1 unrelated), and the path."""
    n, m = len(obs), len(ref)
    if not n or not m:
        return 1.0, []
    INF = 1e9
    D = [[INF] * (m + 1) for _ in range(n + 1)]
    L = [[0] * (m + 1) for _ in range(n + 1)]
    D[0][0] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            c = _cost(obs[i - 1], ref[j - 1])
            best, bl = D[i - 1][j - 1] + c, L[i - 1][j - 1]
            # lips closed between words are a pause, not a p/b/m: passing over them is cheap
            v = D[i - 1][j] + (min(c, PAUSE) if obs[i - 1] == "P" else c)
            if v < best:
                best, bl = v, L[i - 1][j]
            if D[i][j - 1] + c < best:
                best, bl = D[i][j - 1] + c, L[i][j - 1]
            D[i][j], L[i][j] = best, bl + 1
    path, i, j = [], n, m
    while i > 0 and j > 0:
        path.append((i - 1, j - 1))
        opts = [(D[i - 1][j - 1], 0, i - 1, j - 1), (D[i - 1][j], 1, i - 1, j), (D[i][j - 1], 2, i, j - 1)]
        _, _, i, j = min(opts)
    return D[n][m] / L[n][m], path[::-1]


# ---------------------------------------------------------------------- vocabulary
_VOCAB = {}
_POS = {}
_ALWAYS = ("the a i you he she it we they is are was were be have has do not no yes and or but to of in on at for with "
           "this that what who where when why how hello hi thank thanks please sorry good bad okay one two three my your").split()


def vocabulary(lang="en", size=1500, extra=(), lab=None):
    """Words grouped by how they look on the lips: {class string: [words, most common first]}."""
    key = (lang, size, tuple(extra))
    if key in _VOCAB:
        return _VOCAB[key]
    import vocab
    if lang == "en":
        r = vocab.rank()
        words = list(_ALWAYS) + [w for w, _ in sorted(r.items(), key=lambda kv: kv[1]) if w.isalpha()][:size]
    else:
        words = [w["tr"][0].lower() for w in vocab.deck(lang)[:size] if w["tr"] and w["tr"][0].isalpha()]
    seen, ordered = set(), []
    for w in list(extra) + words:
        w = w.lower().strip()
        if w and w not in seen:
            seen.add(w); ordered.append(w)
    groups = {}
    for i, w in enumerate(ordered):
        _POS.setdefault(w, i)
    for wp in visemes.word_phonemes(ordered, lang, lab):
        cs = word_classes(wp["phonemes"])
        if cs:
            groups.setdefault(cs, []).append(wp["word"])
    _VOCAB[key] = groups
    return groups


# ---------------------------------------------------------------------- analysis
def _resample(times, vals, fps, dur):
    """Irregular (t, v) samples → a regular series at `fps` (sample-and-hold)."""
    out, k = [], 0
    for i in range(int(dur * fps)):
        t = i / fps
        while k + 1 < len(times) and times[k + 1] <= t:
            k += 1
        out.append(vals[k] if vals else 0.0)
    return out


def _z(x):
    if not x:
        return []
    m = sum(x) / len(x)
    s = math.sqrt(sum((v - m) ** 2 for v in x) / len(x)) or 1.0
    return [(v - m) / s for v in x]


def av_sync(mouth, env, fps=100, max_lag_s=0.5):
    """Offset between lips and sound by cross-correlating mouth opening with loudness.
    Positive = the sound comes after the lips (audio late)."""
    n = min(len(mouth), len(env))
    if n < fps:
        return {"ok": False, "reason": "less than a second of face and sound together"}
    a, b = _z(mouth[:n]), _z(env[:n])
    best, best_lag, curve = -2.0, 0, []
    L = int(max_lag_s * fps)
    for lag in range(-L, L + 1):
        s, c = 0.0, 0
        for i in range(max(0, -lag), min(n, n - lag)):
            s += a[i] * b[i + lag]; c += 1
        r = s / c if c else 0.0
        curve.append(r)
        if r > best:
            best, best_lag = r, lag
    ms = round(1000.0 * best_lag / fps)
    # ITU-R BT.1359: sound more than 45 ms early or 125 ms late is noticeable
    if best < 0.2:
        verdict = "not measurable (lips and sound move too little together)"
    elif -45 <= ms <= 45:
        verdict = "in sync"
    elif ms < -45:
        verdict = "sound is %d ms EARLY — noticeable (more than 45 ms)" % -ms
    elif ms > 125:
        verdict = "sound is %d ms LATE — noticeable (more than 125 ms)" % ms
    else:
        verdict = "sound is %d ms late — within what viewers accept" % ms
    return {"ok": best >= 0.2, "offset_ms": ms, "correlation": round(best, 3), "verdict": verdict,
            "searched_ms": [-int(max_lag_s * 1000), int(max_lag_s * 1000)]}


def quality(info, frames):
    """How well the capture matches the recommended set-up, item by item."""
    W, H = int(_f(info.get("width"))), int(_f(info.get("height")))
    fps = _f(info.get("fps"))
    seen = [f for f in frames if f.get("face")]
    face_rate = len(seen) / len(frames) if frames else 0.0
    med = lambda k: sorted(_f(f.get(k)) for f in seen)[len(seen) // 2] if seen else 0.0
    face_h, mouth_px, yaw, pitch, light = med("face_h"), med("mouth_px"), med("yaw"), med("pitch"), med("light")
    items = []

    def add(key, ok, warn, value, advice):
        items.append({"item": key, "status": "ok" if ok else ("warn" if warn else "bad"), "value": value, "advice": advice})
    add("face found", face_rate >= 0.9, face_rate >= 0.6, "%d%% of frames" % round(100 * face_rate), GUIDE["clear"])
    add("framing", 0.4 <= face_h <= 0.6, 0.28 <= face_h <= 0.75, "face fills %d%% of the height" % round(100 * face_h), GUIDE["framing"])
    add("mouth size", mouth_px >= 150, mouth_px >= 90, "mouth %d px wide" % round(mouth_px), GUIDE["mouth_px"])
    add("resolution", H >= 1080 or W >= 1920, H >= 720, "%d×%d" % (W, H), GUIDE["resolution"])
    add("frame rate", fps >= 50, fps >= 29, "%.1f frames/s" % fps, GUIDE["frame_rate"])
    add("angle", abs(yaw) <= 20 and abs(pitch) <= 15, abs(yaw) <= 30 and abs(pitch) <= 25, "turned %d°, tilted %d°" % (round(yaw), round(pitch)), GUIDE["angle"])
    add("light", 0.3 <= light <= 0.8, 0.18 <= light <= 0.9, "face brightness %d%%" % round(100 * light), GUIDE["light"])
    score = round(100 * sum({"ok": 1, "warn": 0.5, "bad": 0}[i["status"]] for i in items) / len(items))
    return {"score": score, "items": items, "frames": len(frames), "frames_with_face": len(seen)}


def segments(cls, fps, quiet=None, min_pause_s=0.25):
    """Split the frame classes into stretches of speech at pauses: the mouth at rest/closed for at least
    `min_pause_s` (and, when sound is given, quiet)."""
    pause = [(c in "P-") and (quiet is None or quiet[i]) for i, c in enumerate(cls)]
    out, start, i, n, k = [], None, 0, len(cls), int(min_pause_s * fps)
    while i < n:
        if pause[i]:
            j = i
            while j < n and pause[j]:
                j += 1
            if j - i >= k or i == 0 or j == n:
                if start is not None:
                    out.append((start, i)); start = None
                i = j
                continue
            i = j
            continue
        if start is None:
            start = i
        i += 1
    if start is not None:
        out.append((start, n))
    return [(a, b) for a, b in out if b - a >= max(3, int(0.1 * fps))]


def decode(obs, groups, max_words=12):
    """Best sequence of vocabulary words for one stretch of observed classes (word-level dynamic programming)."""
    keys = list(groups)
    n = len(obs)
    INF = 1e9
    best = [(INF, None)] * (n + 1)
    best[0] = (0.0, None)
    order = {k: groups[k][0] for k in keys}
    rank = {k: i for i, k in enumerate(sorted(keys, key=lambda k: _POS.get(order[k], 1e6)))}
    for j in range(1, n + 1):
        if obs[j - 1] == "P" and best[j - 1][0] + PAUSE < best[j][0]:      # a pause between words
            best[j] = (best[j - 1][0] + PAUSE, (j - 1, None, 0.0))
        for i in range(max(0, j - 8), j):
            if best[i][0] >= INF:
                continue
            piece = obs[i:j]
            for k in keys:
                if abs(len(k) - len(piece)) > 2:
                    continue
                c, _ = dtw(piece, k)
                # a small cost per word keeps words whole; common words are a little more likely
                tot = best[i][0] + c * len(piece) + 0.6 + 0.08 * math.log10(2 + rank[k])
                if tot < best[j][0]:
                    best[j] = (tot, (i, k, c))
    words, j = [], n
    while j > 0 and best[j][1]:
        i, k, c = best[j][1]
        if k is None:
            j = i
            continue
        words.append({"looks_like": k, "word": groups[k][0], "same_on_lips": groups[k][1:8], "match": round(1 - c, 2)})
        j = i
    words = words[::-1][:max_words]
    return words, (1 - best[n][0] / max(1, n + 0.6 * len(words))) if best[n][1] or n == 0 else 0.0


def analyse(frames, info=None, env=None, env_fps=100, script="", lang="en", vocab_extra=(), lab=None, read_lips=True):
    """frames: [{t, face, gap, mouth_px, face_h, yaw, pitch, light, bs:{…}}] from the browser tracker.
    env: loudness envelope of the soundtrack (0..1) at env_fps. Returns quality, sync, lip-reading and,
    with a script, how well the lips agree with it."""
    info = info or {}
    frames = sorted((f for f in frames or [] if isinstance(f, dict)), key=lambda f: _f(f.get("t")))
    out = {"quality": quality(info, frames), "classes": CLASSES}
    seen = [f for f in frames if f.get("face")]
    if len(seen) < 5:
        out["error"] = "No face was found in enough frames to read the lips."
        return out
    fps = 100
    dur = _f(seen[-1].get("t")) + 0.05
    times = [_f(f.get("t")) for f in seen]
    gap_series = _resample(times, [_f(f.get("gap")) for f in seen], fps, dur)
    if env:
        if env_fps != fps:                                       # bring the loudness to the same 100 per second
            env = _resample([i / env_fps for i in range(len(env))], [_f(v) for v in env], fps, len(env) / env_fps)
        out["sync"] = av_sync(gap_series, [_f(v) for v in env], fps)
    cls = _resample(times, [frame_class(f) for f in seen], fps, dur)
    quiet = None
    if env:
        e = [_f(v) for v in env][:len(cls)] + [0.0] * max(0, len(cls) - len(env))
        thr = sorted(e)[len(e) // 5] + 0.08 if e else 0.0
        quiet = [v <= thr for v in e]
    out["timeline"] = [{"class": c, "frames": n, "start": None} for c, n in runs(cls, 3)]
    t = 0
    for r in out["timeline"]:
        r["start"] = round(t / fps, 2); t += r["frames"]; r["seconds"] = round(r["frames"] / fps, 2); del r["frames"]
    if script.strip():
        wp = visemes.word_phonemes([w for w in re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", script)], lang, lab)
        ref = "".join(word_classes(w["phonemes"]) for w in wp)
        ref_c = "".join(c for i, c in enumerate(ref) if i == 0 or ref[i - 1] != c)
        obs = "".join(c for c, _ in runs([c for c in cls if c != "-"], 3))
        cost, path = dtw(obs, ref_c)
        # per word: the share of its classes that matched what was seen
        per, pos = [], 0
        for w in wp:
            k = word_classes(w["phonemes"])
            idx = set(range(pos, pos + len(k))); pos += len(k)
            hits = [_cost(obs[i], ref_c[j]) for i, j in path if j in idx]
            per.append({"word": w["word"], "looks_like": k, "agreement": round(1 - sum(hits) / len(hits), 2) if hits else 0.0})
        raw = 1 - cost
        # chance level: the same classes in scrambled orders (reversed, rotated) — any script matches this well
        n_ = len(ref_c)
        scr = [ref_c[::-1]] + [ref_c[k:] + ref_c[:k] for k in (n_ // 3, 2 * n_ // 3) if 0 < k < n_]
        chance = sum(1 - dtw(obs, x)[0] for x in scr) / len(scr) if scr else raw
        agree = round(100 * max(0.0, (raw - chance) / (1 - chance))) if chance < 1 else 0
        out["script"] = {"agreement": agree, "raw_match": round(100 * raw), "chance_match": round(100 * chance),
                         "words": per, "expected": ref_c, "seen": obs,
                         "verdict": ("the lips agree with the script" if agree >= 40 else
                                     "partly agrees — check the words marked low" if agree >= 20 else
                                     "the lips do NOT match this script (different words, dubbing, or a poor view)")}
    if read_lips:
        groups = vocabulary(lang, extra=tuple(vocab_extra), lab=lab)
        segs = segments(cls, fps, quiet)
        read = []
        for a, b in segs[:20]:
            obs = "".join(c for c, _ in runs([c for c in cls[a:b] if c != "-"], 3))
            words, conf = decode(obs, groups)
            read.append({"from_s": round(a / fps, 2), "to_s": round(b / fps, 2), "seen": obs, "words": words, "confidence": round(max(0.0, conf), 2)})
        out["lipread"] = {"segments": read, "text": " ".join(w["word"] for s in read for w in s["words"]),
                          "vocabulary_size": sum(len(v) for v in groups.values()), "look_alike_groups": len(groups),
                          "note": "Lips show about a third of speech: each word is shown with the words that look the same. "
                                  "Give a script (or a short list of expected words) for a reliable check."}
    return out
