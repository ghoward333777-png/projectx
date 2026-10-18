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


# What the learner (lipcoach.py) has proven better than the rules on held-out recordings; empty = rules only.
ACTIVE = {"model": None, "costs": None, "bias_ms": 0, "version": None}

FEATURES = ["gap", "jawOpen", "mouthClose", "press", "mouthRollLower", "mouthRollUpper", "mouthFunnel", "mouthPucker",
            "stretch", "smile", "upperUp", "lowerDown", "mouthShrugLower"]


def features(fr):
    """A frame as numbers the learner uses (lip gap plus the mouth blendshapes, left/right averaged)."""
    bs = fr.get("bs") or {}
    g = lambda k: _f(bs.get(k))
    avg = lambda a: (g(a + "Left") + g(a + "Right")) / 2
    return [round(v, 4) for v in (_f(fr.get("gap")), g("jawOpen"), g("mouthClose"), avg("mouthPress"), g("mouthRollLower"),
                                  g("mouthRollUpper"), g("mouthFunnel"), g("mouthPucker"), avg("mouthStretch"), avg("mouthSmile"),
                                  avg("mouthUpperUp"), avg("mouthLowerDown"), g("mouthShrugLower"))]


def predict(model, fv):
    """Gaussian naive Bayes: the most likely mouth class for a feature vector (deterministic)."""
    best, bc = -1e18, "T"
    for c in sorted(model["classes"]):
        p = model["classes"][c]
        ll = p["log_prior"]
        for x, m, v in zip(fv, p["mean"], p["var"]):
            ll -= 0.5 * ((x - m) ** 2 / v + math.log(v))
        if ll > best:
            best, bc = ll, c
    return bc


def frame_class(fr, model=None):
    """One video frame → a mouth class. fr has 'gap' (lip opening ÷ mouth width, from landmarks) and 'bs'
    (MediaPipe blendshape scores 0..1). Uses the learned model when one is active, else the rules;
    model="rules" forces the rules."""
    model = ACTIVE["model"] if model is None else model
    if model and model != "rules":
        return predict(model, fr["_fv"] if "_fv" in fr else features(fr))
    if "_fv" in fr and not fr.get("bs"):                  # a stored feature vector (the reservoir)
        fv = fr["_fv"]
        fr = {"gap": fv[0], "bs": {"jawOpen": fv[1], "mouthClose": fv[2], "mouthPressLeft": fv[3], "mouthPressRight": fv[3],
                                   "mouthRollLower": fv[4], "mouthFunnel": fv[6], "mouthPucker": fv[7], "mouthStretchLeft": fv[8],
                                   "mouthStretchRight": fv[8], "mouthSmileLeft": fv[9], "mouthSmileRight": fv[9]}}
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


def _cost(a, b, costs=None):
    if a == b:
        return 0.0
    learned = ACTIVE["costs"] if costs is None else costs
    if learned:
        return learned.get(a + b, learned.get(b + a, _NEAR.get(frozenset((a, b)), 1.0)))
    return _NEAR.get(frozenset((a, b)), 1.0)


def dtw(obs, ref, costs=None):
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
            c = _cost(obs[i - 1], ref[j - 1], costs)
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
    raw = round(1000.0 * best_lag / fps)
    bias = int(ACTIVE.get("bias_ms") or 0)              # this computer's own camera/microphone delay, learned
    ms = raw - bias
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
    return {"ok": best >= 0.2, "offset_ms": ms, "raw_offset_ms": raw, "device_bias_ms": bias, "correlation": round(best, 3), "verdict": verdict,
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
        out["script"] = script_agreement(cls, script, lang, lab)
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


def script_agreement(cls, script, lang="en", lab=None, costs=None):
    """How well the mouth classes seen (100 per second) agree with a script, scored against chance
    (the same classes in scrambled orders): 0 = no better than chance, 100 = perfect."""
    wp = visemes.word_phonemes(re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", script), lang, lab)
    ref = "".join(word_classes(w["phonemes"]) for w in wp)
    ref_c = "".join(c for i, c in enumerate(ref) if i == 0 or ref[i - 1] != c)
    obs = "".join(c for c, _ in runs([c for c in cls if c != "-"], 3))
    if not ref_c or not obs:
        return {"agreement": 0, "raw_match": 0, "chance_match": 0, "words": [], "expected": ref_c, "seen": obs,
                "verdict": "nothing to compare (no words or no lip movement)"}
    cost, path = dtw(obs, ref_c, costs)
    per, pos = [], 0
    for w in wp:                                        # per word: the share of its classes that matched what was seen
        k = word_classes(w["phonemes"])
        idx = set(range(pos, pos + len(k))); pos += len(k)
        hits = [_cost(obs[i], ref_c[j], costs) for i, j in path if j in idx]
        per.append({"word": w["word"], "looks_like": k, "agreement": round(1 - sum(hits) / len(hits), 2) if hits else 0.0})
    raw = 1 - cost
    n_ = len(ref_c)
    scr = [ref_c[::-1]] + [ref_c[k:] + ref_c[:k] for k in (n_ // 3, 2 * n_ // 3) if 0 < k < n_]
    chance = sum(1 - dtw(obs, x, costs)[0] for x in scr) / len(scr) if scr else raw
    agree = round(100 * max(0.0, (raw - chance) / (1 - chance))) if chance < 1 else 0
    return {"agreement": agree, "raw_match": round(100 * raw), "chance_match": round(100 * chance),
            "words": per, "expected": ref_c, "seen": obs,
            "verdict": ("the lips agree with the script" if agree >= 40 else
                        "partly agrees — check the words marked low" if agree >= 20 else
                        "the lips do NOT match this script (different words, dubbing, or a poor view)")}


# ---------------------------------------------------------------------- audio + face together (ingestion and queries)
def classes_of(frames, fps=100, model=None):
    """Frames → (mouth class per 1/100 s, lip-gap series per 1/100 s), or ([], []) when no face was seen."""
    seen = sorted((f for f in frames or [] if isinstance(f, dict) and f.get("face")), key=lambda f: _f(f.get("t")))
    if len(seen) < 5:
        return [], []
    times = [_f(f.get("t")) for f in seen]                  # seconds from the start of the recording, same clock as the sound
    dur = times[-1] + 0.05
    return (_resample(times, [frame_class(f, model) for f in seen], fps, dur),
            _resample(times, [_f(f.get("gap")) for f in seen], fps, dur))


def _p(vals, q):
    v = sorted(vals)
    return v[min(len(v) - 1, int(q * len(v)))] if v else 0.0


def expression(frames):
    """What the face shows while speaking, from MediaPipe blendshapes: smiling, sad (inner brows up, mouth
    corners down), angry (brows down, nose wrinkled), surprised (brows up, eyes wide). The upper 75th
    percentile of each cue is used, so a brief expression counts but a single odd frame does not."""
    seen = [f for f in frames or [] if isinstance(f, dict) and f.get("face") and f.get("bs")]
    if len(seen) < 5:
        return {"label": "not seen", "cues": {}, "reasons": ["no face in enough frames"]}
    def cue(*keys):
        return round(_p([sum(_f((f.get("bs") or {}).get(k)) for k in keys) / len(keys) for f in seen], 0.75), 3)
    c = {"smile": cue("mouthSmileLeft", "mouthSmileRight"), "frown": cue("mouthFrownLeft", "mouthFrownRight"),
         "brow_inner_up": cue("browInnerUp"), "brow_down": cue("browDownLeft", "browDownRight"),
         "brow_outer_up": cue("browOuterUpLeft", "browOuterUpRight"), "squint": cue("eyeSquintLeft", "eyeSquintRight"),
         "cheek": cue("cheekSquintLeft", "cheekSquintRight"), "sneer": cue("noseSneerLeft", "noseSneerRight"),
         "eyes_wide": cue("eyeWideLeft", "eyeWideRight"), "jaw": cue("jawOpen")}
    sc = {"smiling / laughing": 1.6 * c["smile"] + 0.6 * c["cheek"] + 0.3 * c["squint"],
          "sad / tearful": 1.2 * c["brow_inner_up"] + 1.0 * c["frown"] + 0.3 * c["squint"] - 0.8 * c["smile"],
          "angry / tense": 1.2 * c["brow_down"] + 0.8 * c["sneer"] - 0.5 * c["smile"],
          "surprised": 0.9 * c["brow_outer_up"] + 0.7 * c["eyes_wide"] + 0.3 * c["jaw"] - 0.5 * c["frown"]}
    top = max(sc, key=sc.get)
    label = top if sc[top] >= 0.35 else "neutral"
    why = {"smiling / laughing": "mouth corners up %.2f, cheeks raised %.2f" % (c["smile"], c["cheek"]),
           "sad / tearful": "inner brows up %.2f, mouth corners down %.2f" % (c["brow_inner_up"], c["frown"]),
           "angry / tense": "brows down %.2f, nose wrinkled %.2f" % (c["brow_down"], c["sneer"]),
           "surprised": "brows up %.2f, eyes wide %.2f" % (c["brow_outer_up"], c["eyes_wide"])}
    return {"label": label, "strength": round(max(0.0, sc[top]), 2), "cues": c, "scores": {k: round(v, 2) for k, v in sc.items()},
            "reasons": [why[top]] if label != "neutral" else ["no expression cue above 0.35"]}


def lips_moving(gap_series, fps=100):
    """Whether the mouth moves like speech: lip opening varies and changes direction several times a second."""
    if len(gap_series) < fps // 2:
        return {"moving": False, "variation": 0.0, "changes_per_s": 0.0}
    sd = math.sqrt(sum((g - sum(gap_series) / len(gap_series)) ** 2 for g in gap_series) / len(gap_series))
    sm = [sum(gap_series[max(0, i - 3):i + 4]) / len(gap_series[max(0, i - 3):i + 4]) for i in range(len(gap_series))]
    turns = sum(1 for i in range(1, len(sm) - 1) if (sm[i] - sm[i - 1]) * (sm[i + 1] - sm[i]) < 0 and abs(sm[i] - sm[i - 1]) > 1e-4)
    rate = turns / (len(sm) / fps)
    return {"moving": sd > 0.03 and rate >= 1.0, "variation": round(sd, 3), "changes_per_s": round(rate, 1)}


# what each sound-based vocal mode should look like on the face
_EXPECT = {"crying": "sad / tearful", "laughing": "smiling / laughing", "shouting": "angry / tense"}


def fuse_mode(vocal, expr, moving=None):
    """Combine the vocal mode heard with the face seen. Crying and laughing sound alike (breathy bursts,
    shaky pitch) but look opposite, so the face settles close calls; a whisper with still lips is not this
    person speaking. Returns the final label, how sure, and why."""
    a = (vocal or {}).get("label") or "speaking"
    conf = (vocal or {}).get("confidence") or "uncertain"
    f = (expr or {}).get("label") or "not seen"
    out = {"heard": a, "heard_confidence": conf, "seen": f, "label": a, "confidence": conf, "reasons": []}
    scores = {s["mode"]: s["score"] for s in (vocal or {}).get("scores") or []}
    if f == "not seen":
        out["reasons"].append("no face: the sound alone decides")
        return out
    if moving is not None and not moving.get("moving") and a not in ("silence / no voice",):
        out["reasons"].append("the lips are not moving like speech — the voice may be someone else's (off camera or dubbed)")
        out["voice_matches_face"] = False
    if a in _EXPECT and f == _EXPECT[a]:
        out["confidence"] = "confirmed by the face"
        out["reasons"].append("the face shows %s, as %s does" % (f, a))
    elif a in ("crying", "laughing") and f in ("smiling / laughing", "sad / tearful"):
        other = "laughing" if f == "smiling / laughing" else "crying"
        if other != a and (conf == "uncertain" or scores.get(other, 0) >= scores.get(a, 0) - 25 or expr.get("strength", 0) >= 0.6):
            out["label"], out["confidence"] = other, "corrected by the face"
            out["reasons"].append("sounded like %s, but the face shows %s — %s and %s sound alike, the face tells them apart" % (a, f, a, other))
        else:
            out["reasons"].append("the sound says %s but the face shows %s: marked uncertain" % (a, f))
            out["confidence"] = "uncertain (sound and face disagree)"
    elif a in ("speaking", "whispering") and f != "neutral":
        out["label"] = "%s, %s" % (a, {"smiling / laughing": "smiling", "sad / tearful": "upset", "angry / tense": "tense",
                                       "surprised": "surprised"}.get(f, f))
        out["reasons"].append("an ordinary voice with a %s face" % f)
    elif a in _EXPECT and f == "neutral":
        out["reasons"].append("the face looks neutral; the sound alone says %s" % a)
        if conf == "uncertain":
            out["confidence"] = "uncertain (the face does not confirm it)"
    else:
        out["reasons"].append("sound and face agree" if f == "neutral" else "the face shows %s" % f)
    return out


def rank_candidates(cls, candidates, quality_score=100, lang="en", lab=None):
    """Choose between possible transcripts (recognizer alternatives, typed text) using the lips: each gets the
    recognizer's confidence and the lips' agreement; the lips count for more when the picture is good."""
    w_lips = 0.5 * max(0.0, min(1.0, (quality_score - 30) / 50.0))     # 0 for a poor picture … 0.5 for a good one
    rows = []
    for c in candidates:
        text = " ".join(str(c.get("text") or "").split())
        if not text or any(r["text"].lower() == text.lower() for r in rows):
            continue
        ac = c.get("confidence")
        ac = 0.5 if ac is None else max(0.0, min(1.0, float(ac)))
        lip = script_agreement(cls, text, lang, lab)["agreement"] / 100.0 if cls else 0.0
        rows.append({"text": text, "source": c.get("source") or "", "audio_confidence": round(ac, 2), "lip_agreement": round(lip, 2),
                     "score": round((1 - w_lips) * ac + w_lips * lip, 3)})
    rows.sort(key=lambda r: -r["score"])
    for i, r in enumerate(rows):
        r["chosen"] = i == 0
    changed = bool(rows) and rows[0]["source"] != (candidates[0].get("source") if candidates else None)
    return {"chosen": rows[0]["text"] if rows else "", "candidates": rows, "lip_weight": round(w_lips, 2),
            "changed_by_lips": changed and rows[0]["text"].lower() != str(candidates[0].get("text") or "").strip().lower()}


def authenticity(script_check, sync, moving, quality):
    """Does this voice belong to this face? Lips against the words, sync, and whether the lips move at all."""
    flags, ok = [], []
    q = (quality or {}).get("score", 0)
    if q < 45:
        return {"verdict": "cannot tell — the picture is too poor to judge (capture quality %d/100)" % q, "flags": [], "ok": [], "trust": "unknown"}
    if moving is not None:
        (ok if moving.get("moving") else flags).append("lips move like speech" if moving.get("moving") else "lips hardly move while the voice speaks")
    if script_check:
        a = script_check.get("agreement", 0)
        (ok if a >= 40 else flags if a < 20 else ok).append("lips agree with the words (%d%%)" % a if a >= 20 else "lips do not match the words (%d%%)" % a)
    if sync and sync.get("ok"):
        ms = sync["offset_ms"]
        (ok if -45 <= ms <= 125 else flags).append("sound and lips %d ms apart" % ms)
    mismatch = bool(script_check) and script_check.get("agreement", 0) < 20 and q >= 70   # a clear view and the wrong words
    trust = "low" if len(flags) >= 2 or mismatch else "high" if not flags and len(ok) >= 2 else "medium"
    verdict = {"high": "the voice matches this face", "medium": "probably the same speaker — check the flags",
               "low": "the voice probably does NOT belong to this face (dubbed, edited or another speaker)"}[trust]
    return {"verdict": verdict, "trust": trust, "flags": flags, "ok": ok}


def fuse(frames, vocal=None, env=None, candidates=None, info=None, lang="en", lab=None):
    """Everything the camera adds to a spoken input: transcript choice, expression, fused vocal mode, sync and a
    speaker check. Used by ingestion and by spoken queries."""
    cls, gaps = classes_of(frames)
    q = quality(info or {}, frames or [])
    out = {"quality": q, "face_seen": bool(cls)}
    if not cls:
        out["note"] = "no face in enough frames — the sound alone was used"
        if candidates:
            out["transcript"] = rank_candidates([], candidates, 0, lang, lab)
        out["mode"] = fuse_mode(vocal, None)
        return out
    mv = lips_moving(gaps)
    ex = expression(frames)
    out.update({"expression": ex, "lips": mv, "mode": fuse_mode(vocal, ex, mv)})
    if env:
        out["sync"] = av_sync(gaps, [_f(v) for v in env])
    if candidates:
        out["transcript"] = rank_candidates(cls, candidates, q["score"], lang, lab)
        chosen = out["transcript"]["chosen"]
        out["script"] = script_agreement(cls, chosen, lang, lab) if chosen else None
    out["speaker_check"] = authenticity(out.get("script"), out.get("sync"), mv, q)
    return out
