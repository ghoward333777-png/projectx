"""vse — the Visual Speech Engine, stage 1: lip sync and lip reading inside the Language Builder.

The design follows the Visual Speech Engine specification (subsystems APS, VPS, LSG, LRE, FMS, COL) but every
part is built from signal processing, geometry and established speech science instead of trained networks, so
it runs on any computer, needs no GPU, uses only the Python standard library and gives the same answer for the
same input. Stage 2 (a separate PyTorch package, outside this application) keeps the same data formats and
API, so trained models can replace these parts one at a time and be measured with the same benchmark.

  APS  Audio Processing Subsystem   phoneme timeline (espeak-ng / rules + forced alignment or Speech-to-Text
                                    word times), prosody at 100 frames/s (pitch, energy, voicing, local speaking
                                    rate), an 8-dimension emotion vector, and a speaker fingerprint (log-mel
                                    statistics + pitch) for "same voice?" checks.
  VPS  Visual Processing Subsystem  per recording, from the browser's MediaPipe face mesh: head pose from the
                                    face transformation matrix, camera/framing motion, an approximate
                                    first-order spherical-harmonics lighting estimate, and a geometric identity
                                    fingerprint (landmark distance ratios) — numbers only, never pictures.
  LSG  Lip Sync Generator           phonemes → visemes with coarticulation (Cohen–Massaro dominance functions:
                                    each sound pulls the mouth toward its target with a strength that decays in
                                    time, so neighbours blend, rounding is anticipated, and p/b/m must close),
                                    then visemes → full-face motion: 12 mouth blendshapes in MediaPipe / ARKit
                                    names, jaw rotation, brows and head nods on pitch accents, blinks and gaze
                                    shifts at phrase boundaries, all scaled by the emotion vector.
  LRE  Lip Reading Engine           mouth features → soft class likelihoods (Gaussian models: built from the
                                    LSG targets, or the camera/speaker model the reservoir learned) → word
                                    decoding with a hidden-Markov word network over the vocabulary (Viterbi,
                                    beam-pruned), word-frequency priors and an insertion penalty. With a script
                                    it force-aligns instead (per-word timing and agreement). Every word still
                                    comes with the words that look the same on the lips.
  COL  Control & Orchestration      background jobs (lip_sync, lip_read, benchmark) with status polling.

Accuracy is measured, never claimed: benchmark() runs a synthetic round trip (deterministic speakers with
their own mouth shapes, timing and noise) and, when the ingestion reservoir has held-out recordings, the same
measures on real faces — each against lip-reading v1. Synthetic numbers are a regression check, not a
real-world accuracy figure.
"""
import hashlib, json, math, random, re, threading, time, uuid

import lipread
import visemes
import voicedsp

VERSION = "1.0"
FPS_READ = 30                      # lip reading works at 30 frames per second (lips move in 50–100 ms)
# The mouth parameters: the same 13 numbers the tracker measures (lipread.FEATURES), so synthesis and
# measurement can be compared directly and synthesized frames can be read back.
PARAMS = list(lipread.FEATURES)    # gap, jawOpen, mouthClose, press, mouthRollLower, mouthRollUpper, mouthFunnel,
                                   # mouthPucker, stretch, smile, upperUp, lowerDown, mouthShrugLower
_I = {k: i for i, k in enumerate(PARAMS)}
CLASSES = ["P", "F", "W", "A", "E", "T", "-"]
UNIT = "viseme"                    # decode over the 15 visemes with soft scores ("class" = the 7 look-alike classes)
REST_UNITS = {"viseme": ("sil", "PP"), "class": ("-", "P")}


def _now():
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%02dZ" % int((t % 1) * 100)


def _vec(**kw):
    v = [0.0] * len(PARAMS)
    for k, x in kw.items():
        v[_I[k]] = x
    return v


# ============================================================================ APS — audio
def phoneme_timeline(track):
    """visemes.align() output → PhonemeTimeline {phonemes: [{symbol, viseme, word, start_time, end_time, confidence}]}."""
    conf = 0.9 if str(track.get("method", "")).startswith("word times") else 0.6
    return {"phonemes": [{"symbol": r["p"], "viseme": r["v"], "word": r.get("word"), "start_time": r["start"], "end_time": r["end"],
                          "confidence": conf} for r in track.get("phonemes", [])], "method": track.get("method")}


def prosody(meas):
    """voicedsp.measure() → ProsodyTimeline at 100 frames/s: pitch (Hz, 0 unvoiced), energy 0..1, voicing, speaking rate."""
    c = meas["contour"]
    hop, f0, db, nuc = c["hop_s"], c["f0_hz"], c["db"], c["nuclei"]
    if not db:
        return {"fps": 100, "frames": []}
    lo, hi = sorted(db)[len(db) // 10], max(db)
    n = int(meas["analysed_s"] * 100)
    nuc_t = [i * hop for i in nuc]
    out, k = [], 0
    for i in range(n):
        t = i / 100.0
        j = min(len(db) - 1, int(t / hop))
        while k < len(nuc_t) and nuc_t[k] < t - 1.0:
            k += 1
        cnt, m = 0, k
        while m < len(nuc_t) and nuc_t[m] <= t + 1.0:
            cnt += 1; m += 1
        out.append({"time": round(t, 2), "pitch": f0[j], "energy": round(max(0.0, min(1.0, (db[j] - lo) / max(6.0, hi - lo))), 3),
                    "voicing": 1.0 if f0[j] > 0 else 0.0, "speaking_rate": round(cnt / 2.0, 2)})
    return {"fps": 100, "frames": out}


EMOTION_KEYS = ["valence", "arousal", "dominance", "anger", "joy", "sadness", "fear", "surprise"]
_EMO_LABEL = {"excited / animated": dict(valence=0.6, arousal=0.85, dominance=0.6, joy=0.6, surprise=0.3),
              "engaged": dict(valence=0.6, arousal=0.6, dominance=0.55, joy=0.3),
              "angry / forceful": dict(valence=0.2, arousal=0.9, dominance=0.85, anger=0.8),
              "tense / fearful": dict(valence=0.25, arousal=0.85, dominance=0.25, fear=0.7),
              "sad / subdued": dict(valence=0.2, arousal=0.2, dominance=0.3, sadness=0.7),
              "calm": dict(valence=0.6, arousal=0.25, dominance=0.5),
              "neutral": dict(valence=0.5, arousal=0.45, dominance=0.5)}


def emotion(meas):
    """An 8-dimension emotion vector from the acoustic indicators (arousal-led; an estimate, not mind-reading)."""
    label = ((meas.get("indicators") or {}).get("emotion") or {}).get("label", "neutral")
    base = {k: 0.0 for k in EMOTION_KEYS}
    base.update(_EMO_LABEL.get(label, _EMO_LABEL["neutral"]))
    p, v = meas.get("pitch") or {}, meas.get("volume") or {}
    if p.get("variation_semitones") is not None:           # nudge arousal continuously, not only by label
        base["arousal"] = round(max(0.0, min(1.0, 0.7 * base["arousal"] + 0.3 * min(1.0, p["variation_semitones"] / 6.0))), 3)
    base["label"] = label
    return base


def _fft(re_, im_):
    n = len(re_)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit; bit >>= 1
        j |= bit
        if i < j:
            re_[i], re_[j] = re_[j], re_[i]; im_[i], im_[j] = im_[j], im_[i]
    size = 2
    while size <= n:
        ang = -2 * math.pi / size
        wr, wi = math.cos(ang), math.sin(ang)
        for s in range(0, n, size):
            cr, ci = 1.0, 0.0
            for k in range(size // 2):
                a, b = s + k, s + k + size // 2
                tr = cr * re_[b] - ci * im_[b]; ti = cr * im_[b] + ci * re_[b]
                re_[b], im_[b] = re_[a] - tr, im_[a] - ti
                re_[a] += tr; im_[a] += ti
                cr, ci = cr * wr - ci * wi, cr * wi + ci * wr
        size *= 2


def _mel_bank(n_fft, sr, bands=24, fmin=80.0, fmax=7600.0):
    mel = lambda f: 2595 * math.log10(1 + f / 700.0)
    inv = lambda m: 700 * (10 ** (m / 2595.0) - 1)
    pts = [inv(mel(fmin) + (mel(fmax) - mel(fmin)) * i / (bands + 1)) for i in range(bands + 2)]
    bins = [int(f * n_fft / sr) for f in pts]
    bank = []
    for b in range(bands):
        a, c, e = bins[b], bins[b + 1], bins[b + 2]
        w = {}
        for k in range(a, e + 1):
            if k < c and c > a:
                w[k] = (k - a) / (c - a)
            elif k >= c and e > c:
                w[k] = (e - k) / (e - c)
        bank.append(w)
    return bank


def speaker_embedding(wav_bytes, meas=None, step_s=0.04):
    """A 50-number voice fingerprint: mean and spread of 24 log-mel bands over voiced frames, plus pitch level and
    range. Unit length, so two voices compare by cosine similarity (1 = identical)."""
    x, sr = voicedsp.read_wav(wav_bytes)
    if sr > 16000:
        x, sr = voicedsp._downsample(x, sr, 16000)
    n_fft, bank = 512, _mel_bank(512, sr, fmax=min(7600.0, 0.475 * sr))
    win = [0.5 - 0.5 * math.cos(2 * math.pi * i / (n_fft - 1)) for i in range(n_fft)]
    feats = []
    f0 = (meas or {}).get("contour", {}).get("f0_hz") or []
    hop = (meas or {}).get("contour", {}).get("hop_s") or 0.01
    for s in range(0, max(0, len(x) - n_fft), int(step_s * sr)):
        if f0 and f0[min(len(f0) - 1, int(s / sr / hop))] <= 0:
            continue                                         # voiced frames only: the voice, not the room
        re_ = [x[s + i] * win[i] for i in range(n_fft)]
        im_ = [0.0] * n_fft
        _fft(re_, im_)
        pw = [re_[k] * re_[k] + im_[k] * im_[k] for k in range(n_fft // 2 + 1)]
        e = sum(pw)
        if e < 1e-6:
            continue
        feats.append([math.log(1e-9 + sum(w * pw[k] for k, w in b.items()) / e) for b in bank])
        if len(feats) >= 600:
            break
    if not feats:
        return None
    m = [sum(f[i] for f in feats) / len(feats) for i in range(24)]
    sd = [math.sqrt(sum((f[i] - m[i]) ** 2 for f in feats) / len(feats)) for i in range(24)]
    mm = sum(m) / 24
    vf = [v for v in f0 if v > 0]
    pitch = [math.log(sum(vf) / len(vf)) - 4.8 if vf else 0.0, (math.log(max(vf)) - math.log(min(vf))) if len(vf) > 2 else 0.0]
    v = [a - mm for a in m] + [0.5 * s for s in sd] + pitch
    nrm = math.sqrt(sum(a * a for a in v)) or 1.0
    return [round(a / nrm, 5) for a in v]


def cosine(a, b):
    if not a or not b or len(a) != len(b):
        return None
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return round(sum(x * y for x, y in zip(a, b)) / ((na * nb) or 1.0), 4)


def aps(wav_bytes, text, lang="en", lab=None, word_times=None):
    """The whole audio subsystem for one recording."""
    meas = voicedsp.measure(wav_bytes)
    track = visemes.align(text, wav_bytes, lang, lab, word_times)
    return {"track": track, "phonemes": phoneme_timeline(track), "prosody": prosody(meas), "emotion": emotion(meas),
            "speaker_embedding": speaker_embedding(wav_bytes, meas), "duration": track["duration"], "measure": meas}


def timing_from_text(text, lang="en", lab=None, syl_per_s=4.5):
    """A visemes.align()-shaped track without audio: words timed from their sounds at a steady speaking rate
    (used for previews and the synthetic benchmark)."""
    words = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)?", text or "", re.UNICODE)
    wp = visemes.word_phonemes(words, lang, lab)
    t, rows, wout = 0.15, [], []
    per = 1.0 / (syl_per_s * 1.0)
    for w in wp:
        ph = w["phonemes"] or [("ə", "E", 1.0)]
        a = t
        for sym, v, wt in ph:
            d = per * (0.55 if wt >= 1.0 else 0.32) * (1.4 if "ː" in sym else 1.0)
            rows.append({"p": sym, "v": v, "start": round(t, 3), "end": round(t + d, 3), "word": w["word"]})
            t += d
        wout.append({"word": w["word"], "start": round(a, 3), "end": round(t, 3)})
        t += 0.06
    dur = round(t + 0.2, 3)
    vis, last = [], 0.0
    for r in rows:
        if r["start"] - last > 0.05:
            vis.append({"v": "sil", "start": round(last, 3), "end": r["start"]})
        vis.append(visemes.shaped(r))
        last = r["end"]
    vis.append({"v": "sil", "start": round(last, 3), "end": dur})
    return {"duration": dur, "method": "timed from the text at %.1f syllables/s (no audio)" % syl_per_s, "words": wout,
            "phonemes": rows, "visemes": vis, "jaw_fps": 100, "jaw": []}


# ============================================================================ VPS — face, head, light, identity
def vps(frames):
    """Summary of the face analysis the browser sends per frame (numbers only): head pose, camera/framing
    motion, lighting and a geometric identity fingerprint."""
    seen = [f for f in frames or [] if isinstance(f, dict) and f.get("face")]
    out = {"frames": len(frames or []), "frames_with_face": len(seen)}
    if not seen:
        return out
    poses = [f["pose"] for f in seen if isinstance(f.get("pose"), list) and len(f["pose"]) >= 6]
    if poses:
        def st(i):
            v = [p[i] for p in poses]
            m = sum(v) / len(v)
            return {"mean": round(m, 1), "spread": round(math.sqrt(sum((x - m) ** 2 for x in v) / len(v)), 1)}
        out["head_pose_deg"] = {"yaw": st(0), "pitch": st(1), "roll": st(2)}
        out["head_translation"] = {"x": st(3), "y": st(4), "z": st(5)}
    boxes = [f["box"] for f in seen if isinstance(f.get("box"), list) and len(f["box"]) == 3]
    if len(boxes) > 2:
        dx = [abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(boxes, boxes[1:])]
        dz = [abs(b[2] - a[2]) for a, b in zip(boxes, boxes[1:])]
        out["camera_motion"] = {"mean_shift_per_frame": round(sum(dx) / len(dx), 4), "mean_zoom_per_frame": round(sum(dz) / len(dz), 4),
                                "verdict": "steady" if sum(dx) / len(dx) < 0.004 else "some movement" if sum(dx) / len(dx) < 0.012 else "shaky — steady the camera"}
    sh = [f["sh"] for f in seen if isinstance(f.get("sh"), list) and len(f["sh"]) == 4]
    if sh:
        m = [round(sum(s[i] for s in sh) / len(sh), 3) for i in range(4)]
        d = math.sqrt(m[1] ** 2 + m[2] ** 2 + m[3] ** 2)
        out["lighting_sh1"] = {"coeffs": m, "ambient": m[0], "directional": round(d, 3),
                               "from": "front" if abs(m[3]) >= max(abs(m[1]), abs(m[2])) else ("the side" if abs(m[1]) >= abs(m[2]) else "above/below"),
                               "evenness": "even" if d < 0.25 * max(0.05, m[0]) else "uneven — shadows across the face",
                               "model": "first-order spherical harmonics on face-mesh normals (approximate)"}
    geo = [f["geo"] for f in seen if isinstance(f.get("geo"), list) and f["geo"]]
    if geo:
        n = len(geo[0])
        geo = [g for g in geo if len(g) == n]
        m = [sum(g[i] for g in geo) / len(geo) for i in range(n)]
        half = len(geo) // 2
        cons = None
        if half >= 2:
            a = [sum(g[i] for g in geo[:half]) / half for i in range(n)]
            b = [sum(g[i] for g in geo[half:]) / (len(geo) - half) for i in range(n)]
            cons = round(math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)) / n), 4)
        out["identity"] = {"fingerprint": [round(v, 4) for v in m], "samples": len(geo), "drift_between_halves": cons,
                           "same_face_throughout": None if cons is None else cons < 0.02,
                           "model": "landmark distance ratios on near-neutral frames (geometric, not face recognition)"}
    return out


# ============================================================================ LSG / FMS — lip sync and face motion
# Viseme targets in the tracker's own units (blendshape scores 0..1 and lip gap ÷ mouth width).
# The upper lip is not still in speech: measured word by word on the original creator's clips of a speaker (Pamela,
# Gemini), it lifts on nearly every open sound — most on open and rounded vowels (our, whole, push), clearly on ee and s,
# hardly on m / b / p — and makes about a third of each opening; it lifts most with the spread, smiling sounds (ee, i, eh,
# s: the upper teeth show), less on wide-open and round ones. Each sound's upperUp is set from that.
# (1.45: measured against her Gemini clip with the calibration bench: open vowels and r opened 2–3× hers and rounded
# sounds were not round — less opening, more pucker and funnel on oh, oo, r; s/z keep a small teeth gap)
TARGETS = {
    "sil": _vec(gap=0.02, jawOpen=0.03, mouthClose=0.05),
    "PP": _vec(gap=0.004, jawOpen=0.05, mouthClose=0.6, press=0.6, mouthRollLower=0.15, mouthRollUpper=0.1),
    "FF": _vec(gap=0.025, jawOpen=0.08, mouthRollLower=0.55, upperUp=0.2, press=0.05),
    "TH": _vec(gap=0.10, jawOpen=0.15, lowerDown=0.1, stretch=0.1, upperUp=0.3),
    "DD": _vec(gap=0.10, jawOpen=0.14, stretch=0.12, upperUp=0.3),
    "kk": _vec(gap=0.12, jawOpen=0.18, upperUp=0.3),
    "CH": _vec(gap=0.14, jawOpen=0.14, mouthFunnel=0.45, mouthPucker=0.5, upperUp=0.4),
    "SS": _vec(gap=0.09, jawOpen=0.1, stretch=0.18, smile=0.05, upperUp=0.45),
    "nn": _vec(gap=0.06, jawOpen=0.09, stretch=0.08, upperUp=0.25),
    "RR": _vec(gap=0.07, jawOpen=0.08, mouthFunnel=0.45, mouthPucker=0.7, upperUp=0.4),
    "aa": _vec(gap=0.36, jawOpen=0.42, lowerDown=0.28, upperUp=0.35),
    "E": _vec(gap=0.17, jawOpen=0.2, stretch=0.4, smile=0.15, lowerDown=0.1, upperUp=0.5),
    "I": _vec(gap=0.1, jawOpen=0.1, stretch=0.6, smile=0.4, upperUp=0.6),
    "O": _vec(gap=0.22, jawOpen=0.24, mouthFunnel=0.6, mouthPucker=0.7, upperUp=0.45),
    "U": _vec(gap=0.12, jawOpen=0.12, mouthFunnel=0.45, mouthPucker=0.9, upperUp=0.4),
}
NEUTRAL = TARGETS["sil"]
LIP_CLOSURE = ("gap", "mouthClose", "press", "mouthRollLower", "mouthRollUpper", "jawOpen")
ROUNDING = ("mouthFunnel", "mouthPucker")
# Dominance (Cohen & Massaro 1993): strength alpha on the parameters a sound depends on, a weaker pull on the
# rest; decay rates (1/s) before (left) and after (right) the sound. Rounding is anticipated early.
_CRIT = {"PP": LIP_CLOSURE, "FF": ("gap", "mouthRollLower", "upperUp", "jawOpen"), "CH": ROUNDING + ("gap",), "RR": ROUNDING,
         "O": ROUNDING + ("gap", "jawOpen"), "U": ROUNDING + ("gap",), "aa": ("gap", "jawOpen", "lowerDown"),
         "E": ("stretch", "gap", "jawOpen"), "I": ("stretch", "smile", "gap"), "SS": ("stretch", "gap"), "TH": ("gap", "lowerDown")}


def _dominance(v, p):
    crit = p in _CRIT.get(v, ())
    vowel = v in ("aa", "E", "I", "O", "U")
    alpha = 1.0 if crit else (0.55 if vowel else 0.18 if v != "sil" else 0.35)
    th_l = 9.0 if (crit and p in ROUNDING) else (16.0 if vowel else 26.0)
    th_r = 14.0 if vowel else 30.0
    return alpha, th_l, th_r


def _rng(*parts):
    return random.Random(int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:12], 16))


def lip_sync(track, pros=None, emo=None, fps=100, targets=None, seed="", style=None):
    """Visemes → coarticulated full-face motion. Returns {viseme_sequence, motion}.

    track: visemes.align() / timing_from_text() output; pros: prosody(); emo: emotion();
    targets: personal viseme targets learned from this speaker's own mouth (else the defaults)."""
    T = dict(TARGETS)
    T.update(targets or {})
    dur = float(track["duration"])
    segs = [(s["v"], float(s["start"]), float(s["end"])) for s in track["visemes"] if s["end"] > s["start"]]
    # lighter lip rounding where the sound is a lax vowel (the short oo of book): its target is pulled toward rest
    lax = [float(s.get("s", 1.0)) for s in track["visemes"] if s["end"] > s["start"]]
    RI = {_I[p] for p in ROUNDING}
    n = max(1, int(dur * fps))
    dom = {p: {v: _dominance(v, p) for v in T} for p in PARAMS}
    frames_mouth = []
    j0 = 0
    for i in range(n):
        t = i / fps
        while j0 < len(segs) and segs[j0][2] < t - 0.5:
            j0 += 1
        row = []
        for p in PARAMS:
            pi = _I[p]
            num = den = 0.0
            for q, (v, a, b) in enumerate(segs[j0:], j0):
                if a > t + 0.5:
                    break
                al, tl, tr = dom[p][v]
                if t < a:
                    d = al * math.exp(-tl * (a - t))
                elif t > b:
                    d = al * math.exp(-tr * (t - b))
                else:
                    d = al
                tv = T[v][pi] if lax[q] == 1.0 or pi not in RI else NEUTRAL[pi] + (T[v][pi] - NEUTRAL[pi]) * lax[q]
                num += d * tv; den += d
            row.append(num / den if den > 1e-6 else NEUTRAL[pi])
        frames_mouth.append(row)
    # loudness shapes the jaw (when the track came from audio)
    jaw = track.get("jaw") or []
    if jaw:
        for i in range(n):
            lj = jaw[min(len(jaw) - 1, int(i * 100 / fps))]
            frames_mouth[i][_I["jawOpen"]] = 0.8 * frames_mouth[i][_I["jawOpen"]] + 0.2 * 0.55 * lj
    # emotion: arousal scales the movement, joy adds a smile, sadness drops the corners
    e = emo or _EMO_LABEL["neutral"]
    scale = 0.85 + 0.3 * float(e.get("arousal", 0.45))
    joy, sad = float(e.get("joy", 0.0)), float(e.get("sadness", 0.0))
    for r in frames_mouth:
        for k in range(len(PARAMS)):
            r[k] = max(0.0, min(1.0, NEUTRAL[k] + (r[k] - NEUTRAL[k]) * scale))
        r[_I["smile"]] = min(1.0, r[_I["smile"]] + 0.18 * joy)
        r[_I["mouthShrugLower"]] = min(1.0, r[_I["mouthShrugLower"]] + 0.15 * sad)
    # p, b, m must close: enforce closure at the middle of every bilabial
    for v, a, b in segs:
        if v != "PP":
            continue
        c, h = (a + b) / 2, max(0.012, min(0.03, (b - a) / 2))
        for i in range(max(0, int((c - h) * fps)), min(n, int((c + h) * fps) + 1)):
            for p in LIP_CLOSURE:
                w = 1.0 if abs(i / fps - c) <= h / 2 else 0.85
                frames_mouth[i][_I[p]] = (1 - w) * frames_mouth[i][_I[p]] + w * T["PP"][_I[p]]
    # prosody: pitch accents raise the brows and nod the head; phrase breaks bring blinks and gaze shifts
    accents, pauses = [], []
    pf = (pros or {}).get("frames") or []
    if pf:
        voiced = sorted(f["pitch"] for f in pf if f["pitch"] > 0)
        if voiced:
            med = voiced[len(voiced) // 2]
            for i in range(3, len(pf) - 3):
                p0 = pf[i]["pitch"]
                if p0 > 0 and p0 > med * 1.12 and p0 >= max(f["pitch"] for f in pf[i - 3:i + 4]) and pf[i]["energy"] > 0.5:
                    if not accents or pf[i]["time"] - accents[-1] > 0.35:
                        accents.append(pf[i]["time"])
    for v, a, b in segs:
        if v == "sil" and b - a >= 0.3 and a > 0.1:
            pauses.append((a, b))
    rnd = _rng("vse-motion", seed, round(dur, 2), len(segs))
    # style learned from real speakers (Quality lab): blink rate, head and brow movement; defaults otherwise
    st = style or {}
    clamp = lambda x: max(0.3, min(3.0, x))
    blink_mean = 60.0 / st["blink_per_min"] if st.get("blink_per_min") else 3.2
    hy = clamp(st["yaw_sd"] / 1.06) if st.get("yaw_sd") else 1.0
    hp = clamp(st["pitch_sd"] / 0.9) if st.get("pitch_sd") else 1.0
    hr = clamp(st["roll_sd"] / 0.42) if st.get("roll_sd") else 1.0
    bw = clamp(st["brow_sd"] / 0.06) if st.get("brow_sd") else 1.0
    # the upper face in speech (learned from real speakers when clips have been ingested)
    upper = {k: clamp(st[k] / ref) if st.get(k) else 1.0 for k, ref in (("squint_sd", 0.05), ("cheek_sd", 0.05), ("wide_sd", 0.04),
                                                                          ("browdown_sd", 0.04), ("sneer_sd", 0.03))}
    blinks, t = [], 0.6 + rnd.random() * 1.5
    while t < dur:
        blinks.append(t)
        t += max(1.4, rnd.expovariate(1 / blink_mean))
    for a, b in pauses:
        if rnd.random() < 0.6:
            blinks.append(a + 0.05)
    blinks.sort()
    gaze_shifts = [(a, (rnd.uniform(-0.25, 0.25), rnd.uniform(-0.12, 0.08))) for a, _ in pauses]
    phase = rnd.random() * 6.28
    # brows live with the voice: measured on the original creator's clips of a speaker, the brows move all through
    # speech (not only on stressed words) — a small, continuous rise with the pitch above the speaker's middle and with
    # the loudness, smoothed over ~0.15 s (text-only timing has no voice: brows then move on accents only)
    live = [0.0] * n
    if pf:
        voiced = sorted(f["pitch"] for f in pf if f["pitch"] > 0)
        med = voiced[len(voiced) // 2] if voiced else 0
        raw = []
        for i in range(n):
            q = pf[min(len(pf) - 1, int(i / fps * 100))]
            up = max(0.0, min(1.0, (q["pitch"] / med - 1.0) / 0.25)) if med and q["pitch"] > 0 else 0.0
            raw.append(0.6 * up + 0.4 * q["energy"])
        k = max(1, int(0.15 * fps))
        for i in range(n):
            seg = raw[max(0, i - k):i + k + 1]
            live[i] = sum(seg) / len(seg)
    motion = []
    gaze = (0.0, 0.0)
    gi = 0
    for i in range(n):
        t = i / fps
        while gi < len(gaze_shifts) and gaze_shifts[gi][0] <= t:
            gaze = gaze_shifts[gi][1]; gi += 1
        blink = 0.0
        for bt in blinks:
            if bt - 0.07 <= t <= bt + 0.11:
                blink = (t - bt + 0.07) / 0.07 if t < bt else 1 - (t - bt) / 0.11
                break
        brow = bw * (sum(0.8 * math.exp(-((t - (a - 0.08)) / 0.12) ** 2) for a in accents if abs(t - a) < 0.5) + 0.35 * live[i])
        nod = hp * sum(-4.5 * math.exp(-((t - (a + 0.1)) / 0.15) ** 2) for a in accents if abs(t - a) < 0.6)
        m = frames_mouth[i]
        motion.append({"time": round(t, 3), "mouth": [round(x, 4) for x in m],
                       "jaw_rotation_deg": round(24.0 * m[_I["jawOpen"]], 2),
                       "head_pose_deg": [round(hy * 0.8 * math.sin(0.9 * t + phase), 2), round(nod, 2), round(hr * 0.5 * math.sin(0.5 * t + phase / 2), 2)],
                       "eye_gaze": [round(gaze[0], 3), round(gaze[1], 3)], "blink": round(max(0.0, min(1.0, blink)), 3),
                       "brows": [round(min(1.0, brow + 0.1 * sad), 3), round(min(1.0, 0.7 * brow), 3)]})
    # the full 52-channel ARKit face for every frame (mouth, jaw, cheeks, nose, eyes, brows, tongue)
    tongue = [0.0] * n
    for v, a, b in segs:
        if v in ("TH", "DD", "nn", "SS"):
            peak = 0.55 if v == "TH" else 0.12
            c, h = (a + b) / 2, max(0.03, (b - a) / 2)
            for i in range(max(0, int((c - 2 * h) * fps)), min(n, int((c + 2 * h) * fps) + 1)):
                tongue[i] = max(tongue[i], peak * math.exp(-((i / fps - c) / h) ** 2))
    asym = 0.06 * (rnd.random() - 0.5)                    # this speaker's slight left/right difference
    for i, f in enumerate(motion):
        f["bs"] = arkit52(f, e, tongue[i], asym, i / fps, phase, upper)
    # the viseme sequence, with how far each sound was reached and how much its neighbours took over
    vseq = []
    for k, (v, a, b) in enumerate(segs):
        i = min(n - 1, int((a + b) / 2 * fps))
        crit = _CRIT.get(v) or ("gap", "jawOpen")
        tgt = T[v]
        got = frames_mouth[i]
        span = [abs(tgt[_I[p]] - NEUTRAL[_I[p]]) for p in crit]
        miss = [abs(got[_I[p]] - tgt[_I[p]]) for p in crit]
        inten = 1.0 if v == "sil" else 1.0 - (sum(miss) / max(1e-6, sum(span) + 0.05))
        left = segs[k - 1][0] if k else None
        right = segs[k + 1][0] if k + 1 < len(segs) else None
        vseq.append({"id": v, "start_time": round(a, 3), "end_time": round(b, 3), "intensity": round(max(0.0, min(1.0, inten)), 3),
                     "coarticulation_left": round(_dominance(left, crit[0])[0] / 1.0, 2) if left else 0.0,
                     "coarticulation_right": round(_dominance(right, crit[0])[0] / 1.0, 2) if right else 0.0})
    return {"viseme_sequence": {"visemes": vseq}, "motion": {"fps": fps, "params": PARAMS, "bs_names": ARKIT52, "frames": motion, "accents_s": accents,
                                                             "blinks_s": [round(b, 2) for b in blinks]}}


# The 52 ARKit blendshapes, in Apple's order (ARFaceAnchor.BlendShapeLocation).
ARKIT52 = ["eyeBlinkLeft", "eyeLookDownLeft", "eyeLookInLeft", "eyeLookOutLeft", "eyeLookUpLeft", "eyeSquintLeft", "eyeWideLeft",
           "eyeBlinkRight", "eyeLookDownRight", "eyeLookInRight", "eyeLookOutRight", "eyeLookUpRight", "eyeSquintRight", "eyeWideRight",
           "jawForward", "jawLeft", "jawRight", "jawOpen", "mouthClose", "mouthFunnel", "mouthPucker", "mouthLeft", "mouthRight",
           "mouthSmileLeft", "mouthSmileRight", "mouthFrownLeft", "mouthFrownRight", "mouthDimpleLeft", "mouthDimpleRight",
           "mouthStretchLeft", "mouthStretchRight", "mouthRollLower", "mouthRollUpper", "mouthShrugLower", "mouthShrugUpper",
           "mouthPressLeft", "mouthPressRight", "mouthLowerDownLeft", "mouthLowerDownRight", "mouthUpperUpLeft", "mouthUpperUpRight",
           "browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight", "cheekPuff", "cheekSquintLeft",
           "cheekSquintRight", "noseSneerLeft", "noseSneerRight", "tongueOut"]


def arkit52(f, emo, tongue=0.0, asym=0.0, t=0.0, phase=0.0, upper=None):
    """One motion frame → all 52 ARKit blendshapes. The 13 measured mouth parameters drive their own channels; the rest
    follow how faces move together in speech: a smile narrows the eyes and lifts the cheeks, lip presses build cheek
    pressure, upper-lip raises wrinkle the nose, sadness pulls the corners down, the eyes follow the gaze, and the two
    sides of the face differ slightly (no real face is symmetric)."""
    m = {k: f["mouth"][_I[k]] for k in PARAMS}
    gx, gy = f["eye_gaze"]
    blink, (brow_in, brow_out) = f["blink"], f["brows"]
    joy, sad, ang = float(emo.get("joy", 0.0)), float(emo.get("sadness", 0.0)), float(emo.get("anger", 0.0))
    L, R = 1.0 + asym, 1.0 - asym
    c = lambda x: round(max(0.0, min(1.0, x)), 4)
    smile, stretch, press, jaw = m["smile"], m["stretch"], m["press"], m["jawOpen"]
    rel = 1.0 - 0.85 * min(1.0, max(m["mouthPucker"], m["mouthFunnel"]))
    u = upper or {}
    gsq, gch, gwd, gbd, gns = (u.get(k, 1.0) for k in ("squint_sd", "cheek_sd", "wide_sd", "browdown_sd", "sneer_sd"))
    # a speaking face is never still above the mouth: the cheeks lift with spread and open vowels, the lower lids narrow a
    # little with them and with emphasis, the eyes widen on raised brows, the nose wrinkles on f/v and raised upper lip
    sq = (0.55 * smile + 0.25 * ang + 0.3 * stretch + 0.2 * jaw + 0.3 * brow_in) * gsq
    ch = (0.6 * smile + 0.3 * stretch + 0.14 * jaw) * gch
    v = {
        "eyeBlinkLeft": blink, "eyeBlinkRight": blink,
        "eyeLookOutLeft": max(0.0, -gx) * 2.4, "eyeLookInRight": max(0.0, -gx) * 2.4,
        "eyeLookInLeft": max(0.0, gx) * 2.4, "eyeLookOutRight": max(0.0, gx) * 2.4,
        "eyeLookUpLeft": max(0.0, -gy) * 3.0, "eyeLookUpRight": max(0.0, -gy) * 3.0,
        "eyeLookDownLeft": max(0.0, gy) * 3.0, "eyeLookDownRight": max(0.0, gy) * 3.0,
        "eyeSquintLeft": sq * L, "eyeSquintRight": sq * R,
        "eyeWideLeft": (0.35 * brow_out + 0.2 * brow_in) * gwd, "eyeWideRight": (0.35 * brow_out + 0.2 * brow_in) * gwd,
        "jawForward": 0.25 * m["mouthRollLower"] + 0.08 * stretch,
        "jawLeft": max(0.0, 0.03 * math.sin(0.7 * t + phase)), "jawRight": max(0.0, -0.03 * math.sin(0.7 * t + phase)),
        "jawOpen": m["jawOpen"], "mouthClose": m["mouthClose"], "mouthFunnel": m["mouthFunnel"], "mouthPucker": m["mouthPucker"],
        "mouthLeft": max(0.0, asym) * 0.5 * m["jawOpen"], "mouthRight": max(0.0, -asym) * 0.5 * m["jawOpen"],
        # a speaking face carries a little warmth: a slight smile while talking, more with joy — relaxed while the lips
        # round (the muscles that smile and the ones that pucker pull against each other)
        "mouthSmileLeft": (smile + 0.08 + 0.3 * joy) * rel * L, "mouthSmileRight": (smile + 0.08 + 0.3 * joy) * rel * R,
        "mouthFrownLeft": (0.5 * m["mouthShrugLower"] + 0.35 * sad) * L, "mouthFrownRight": (0.5 * m["mouthShrugLower"] + 0.35 * sad) * R,
        "mouthDimpleLeft": (0.3 * smile + 0.25 * press) * L, "mouthDimpleRight": (0.3 * smile + 0.25 * press) * R,
        "mouthStretchLeft": stretch * rel * L, "mouthStretchRight": stretch * rel * R,
        "mouthRollLower": m["mouthRollLower"], "mouthRollUpper": m["mouthRollUpper"],
        "mouthShrugLower": m["mouthShrugLower"], "mouthShrugUpper": 0.35 * m["mouthShrugLower"] + 0.2 * m["mouthRollLower"],
        "mouthPressLeft": press * L, "mouthPressRight": press * R,
        "mouthLowerDownLeft": m["lowerDown"] * L, "mouthLowerDownRight": m["lowerDown"] * R,
        "mouthUpperUpLeft": m["upperUp"] * L, "mouthUpperUpRight": m["upperUp"] * R,
        "browDownLeft": (0.4 * ang + 0.12 * press) * gbd, "browDownRight": (0.4 * ang + 0.12 * press) * gbd,
        "browInnerUp": 1.3 * brow_in + 0.25 * sad + 0.15 * jaw, "browOuterUpLeft": (1.3 * brow_out + 0.1 * jaw) * L, "browOuterUpRight": (1.3 * brow_out + 0.1 * jaw) * R,
        "cheekPuff": 0.3 * press * (1.0 - m["jawOpen"]), "cheekSquintLeft": ch * L, "cheekSquintRight": ch * R,
        "noseSneerLeft": (0.35 * m["upperUp"] + 0.1 * smile + 0.2 * m["mouthRollLower"]) * gns,
        "noseSneerRight": (0.35 * m["upperUp"] + 0.1 * smile + 0.2 * m["mouthRollLower"]) * gns,
        "tongueOut": tongue,
    }
    return [c(v.get(k, 0.0)) for k in ARKIT52]


def arkit52_csv(motion):
    """All 52 ARKit channels per frame plus head pose (Live Link Face column order)."""
    lines = [",".join(["time_s"] + ARKIT52 + ["headYaw", "headPitch", "headRoll"])]
    for f in motion["frames"]:
        lines.append(",".join(str(x) for x in [f["time"]] + f["bs"] + f["head_pose_deg"]))
    return "\n".join(lines) + "\n"


ARKIT = [("jawOpen", "jawOpen", 1), ("mouthClose", "mouthClose", 1), ("mouthFunnel", "mouthFunnel", 1), ("mouthPucker", "mouthPucker", 1),
         ("mouthStretchLeft", "stretch", 1), ("mouthStretchRight", "stretch", 1), ("mouthSmileLeft", "smile", 1), ("mouthSmileRight", "smile", 1),
         ("mouthRollLower", "mouthRollLower", 1), ("mouthRollUpper", "mouthRollUpper", 1), ("mouthUpperUpLeft", "upperUp", 1),
         ("mouthUpperUpRight", "upperUp", 1), ("mouthLowerDownLeft", "lowerDown", 1), ("mouthLowerDownRight", "lowerDown", 1),
         ("mouthPressLeft", "press", 1), ("mouthPressRight", "press", 1), ("mouthShrugLower", "mouthShrugLower", 1)]


def arkit_csv(motion):
    """The motion as ARKit-named blendshape curves (Live Link Face / Blender / Unreal friendly), one row per frame."""
    head = ["time_s"] + [a for a, _, _ in ARKIT] + ["eyeBlinkLeft", "eyeBlinkRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight",
                                                    "eyeLookX", "eyeLookY", "headYaw", "headPitch", "headRoll"]
    lines = [",".join(head)]
    for f in motion["frames"]:
        m = f["mouth"]
        row = [f["time"]] + [m[_I[k]] for _, k, _ in ARKIT] + [f["blink"], f["blink"], f["brows"][0], f["brows"][1], f["brows"][1],
                                                               f["eye_gaze"][0], f["eye_gaze"][1]] + f["head_pose_deg"]
        lines.append(",".join(str(round(x, 4)) for x in row))
    return "\n".join(lines) + "\n"


# ============================================================================ LRE — lip reading
CALIBRATION_SENTENCES = [
    "Peter picked a pepper from the big brown box.", "We were away in a warm wet week.", "Five fine violins filled the evening.",
    "The thin thief thought about three things.", "Sally sells sea shells by the sea shore.", "Choose a cheap chair from the shop.",
    "Please open your mouth wide and say ah.", "Look at the moon, it is so blue tonight.", "Red roses and yellow lilies grow here.",
    "Cool blue pools of water rule the zoo.", "Nine new nannies need ninety minutes.", "The dog dug a deep hole in the garden.",
    "My mother made a muffin for me.", "Go and get the green kettle for Kate.", "I see three bees in the tree.",
    "She told her children a long story.", "Hello, how are you doing this evening?", "Thank you very much for your help.",
]
_CAL = {}


def class_models(targets=None, learned=None, fps=FPS_READ, unit=None):
    """Gaussian models of the seven mouth classes over the 13 features. With a learned model (this camera, this
    speaker, from the reservoir) that model is used. Otherwise the models are calibrated by analysis-by-synthesis:
    the lip-sync model speaks a set of calibration sentences (never the benchmark's), and each class is modelled
    on the mouth shapes it actually produces once neighbours have blended in — coarticulation included."""
    unit = unit or UNIT
    if learned and learned.get("visemes") and unit == "viseme":         # (1.48) viseme models measured on real faces
        return {v: {"mean": list(m["mean"]), "var": [max(1e-4, x) for x in m["var"]]} for v, m in learned["visemes"].items()}
    if learned and learned.get("classes") and unit == "class":
        return {c: {"mean": list(m["mean"]), "var": [max(1e-4, x) for x in m["var"]]} for c, m in learned["classes"].items()}
    key = (json.dumps(targets or {}, sort_keys=True), fps, unit)
    if key in _CAL:
        return _CAL[key]
    acc = {}
    for text in CALIBRATION_SENTENCES:
        tr = timing_from_text(text)
        mo = lip_sync(tr, None, None, fps=fps, targets=targets, seed="cal")["motion"]["frames"]
        vis, k = tr["visemes"], 0
        for f in mo:
            while k + 1 < len(vis) and vis[k]["end"] <= f["time"]:
                k += 1
            v = vis[k]["v"]
            acc.setdefault(v if unit == "viseme" else lipread.FROM_VISEME.get(v, "T"), []).append(f["mouth"])
    out = {}
    for c, vs in acc.items():
        mean = [sum(v[i] for v in vs) / len(vs) for i in range(len(PARAMS))]
        var = [sum((v[i] - mean[i]) ** 2 for v in vs) / len(vs) for i in range(len(PARAMS))]
        # widen for real faces: tracker noise and how differently people shape the same sound
        out[c] = {"mean": mean, "var": [x + 0.0016 + 0.04 * m * m for x, m in zip(var, mean)], "frames": len(vs)}
    _CAL[key] = out
    return out


def _loglik(models, fv):
    out = {}
    for c, m in models.items():
        ll = 0.0
        for x, mu, var in zip(fv, m["mean"], m["var"]):
            ll -= 0.5 * ((x - mu) ** 2 / var + math.log(var))
        out[c] = ll
    top = max(out.values())
    z = top + math.log(sum(math.exp(v - top) for v in out.values()))
    return {c: v - z for c, v in out.items()}                     # log posteriors (flat prior)


def best_class(post):
    """The most likely look-alike class for one frame (viseme probabilities added up per class)."""
    if UNIT != "viseme":
        return max(post, key=post.get)
    acc = {}
    for u, v in post.items():
        c = lipread.FROM_VISEME.get(u, "T")
        acc[c] = acc.get(c, 0.0) + math.exp(v)
    return max(acc, key=acc.get)


def frame_series(frames, fps=FPS_READ):
    """Browser frames (or reservoir rows) → (times, feature vectors) resampled to `fps`, face frames only."""
    rows = []
    for f in frames or []:
        if isinstance(f, (list, tuple)):
            rows.append((float(f[0]), list(f[1:1 + len(PARAMS)])))
        elif isinstance(f, dict) and f.get("face"):
            rows.append((float(f.get("t") or 0.0), f["_fv"] if "_fv" in f else lipread.features(f)))
    rows.sort(key=lambda r: r[0])
    if len(rows) < 3:
        return [], []
    t0, t1 = rows[0][0], rows[-1][0]
    ts, vs, k = [], [], 0
    t = t0
    while t <= t1 + 1e-9:
        while k + 1 < len(rows) and rows[k + 1][0] <= t:
            k += 1
        ts.append(round(t, 4)); vs.append(rows[k][1])
        t += 1.0 / fps
    return ts, vs


_LEX = {}


def word_units(phonemes, unit=None):
    """A word's phonemes → its sequence of units (visemes or look-alike classes), repeats collapsed."""
    unit = unit or UNIT
    seq = []
    for _, v, _ in phonemes:
        u = v if unit == "viseme" else lipread.FROM_VISEME.get(v, "T")
        if not seq or seq[-1] != u:
            seq.append(u)
    return seq


def lexicon(lang="en", extra=(), lab=None, size=1500, unit=None):
    """Word models {key: {"seq": units, "words": [...], "logp": prior}}: words that look identical share one model."""
    unit = unit or UNIT
    key = (lang, tuple(extra), size, unit)
    if key in _LEX:
        return _LEX[key]
    lipread.vocabulary(lang, size=size, extra=tuple(extra), lab=lab)           # fills the word-frequency positions
    pos = lipread._POS
    import vocab as _vocab
    if size == 0 and extra:
        words = []                                                 # a closed set: only the expected words
    elif lang == "en":
        words = list(lipread._ALWAYS) + [w for w, _ in sorted(_vocab.rank().items(), key=lambda kv: kv[1]) if w.isalpha()][:size]
    else:
        words = [w["tr"][0].lower() for w in _vocab.deck(lang)[:size] if w["tr"] and w["tr"][0].isalpha()]
    seen, ordered = set(), []
    for w in list(extra) + words:
        w = w.lower().strip()
        if w and w not in seen:
            seen.add(w); ordered.append(w)
    groups = {}
    for wp in visemes.word_phonemes(ordered, lang, lab):
        seq = word_units(wp["phonemes"], unit)
        if seq and seq != ["sil"]:
            groups.setdefault("|".join(seq), {"seq": seq, "words": []})["words"].append(wp["word"])
    tot = 0.0
    for k, g in groups.items():
        g["p"] = sum(1.0 / (10.0 + pos.get(w, 5000)) for w in g["words"])
        g["expected"] = [w for w in g["words"] if w in extra]
        tot += g["p"]
    n_exp = sum(1 for g in groups.values() if g["expected"])
    for g in groups.values():
        share = g["p"] / tot
        if n_exp:                                                  # expected words get 80% of the probability between them
            share = 0.2 * share + (0.8 / n_exp if g["expected"] else 0.0)
        g["logp"] = math.log(share)
        if g["expected"]:
            g["words"] = g["expected"] + [w for w in g["words"] if w not in g["expected"]]
    _LEX[key] = groups
    return groups


STAY, MOVE = math.log(0.75), math.log(0.25)
# Decoder settings, tuned on the calibration sentences only (never the benchmark's): look-alike word error rate
# 0.76–0.78 against 0.975 for lip-reading v1 on the same synthetic speakers.
WORD_PENALTY = 4.0
LM_WEIGHT = 0.6
ACOUSTIC_SCALE = 0.6               # how much the mouth evidence counts against the word priors


def decode(post, lex, beam=30.0):
    """Hidden-Markov word network over the observed class posteriors (Viterbi, beam-pruned). Each word is a
    left-to-right chain of its mouth classes with self-loops; between words the mouth may rest."""
    keys = list(lex)
    ref = sum(lex[k]["logp"] for k in keys) / max(1, len(keys))      # priors count relative to an average word
    entry = [LM_WEIGHT * (lex[k]["logp"] - ref) - WORD_PENALTY for k in keys]
    NEG = -1e18
    seqs = [lex[k]["seq"] for k in keys]
    r1, r2 = REST_UNITS[UNIT]
    score = [[NEG] * len(q) for q in seqs]
    hist = [[None] * len(q) for q in seqs]
    rest_s, rest_h = 0.0, None                                     # the rest/pause state
    if ACOUSTIC_SCALE != 1.0:
        post = [{c: v * ACOUSTIC_SCALE for c, v in lp.items()} for lp in post]
    for t, lp in enumerate(post):
        rest_obs = max(lp.get(r1, -9.0), lp.get(r2, -9.0))
        # best word end at the previous frame
        best_end, best_h = rest_s, rest_h
        for gi, k in enumerate(keys):
            s = score[gi][-1]
            if s > NEG / 2:
                v = s + MOVE
                if v > best_end:
                    best_end, best_h = v, (hist[gi][-1], k)
        top = NEG
        for gi, k in enumerate(keys):
            row, hr = score[gi], hist[gi]
            q = seqs[gi]
            new, newh = [NEG] * len(q), [None] * len(q)
            st = best_end + entry[gi]
            for j, c in enumerate(q):
                a = row[j] + STAY if row[j] > NEG / 2 else NEG
                ha = hr[j]
                if j == 0:
                    b, hb = st, (best_h, t)                       # a word starts at frame t
                else:
                    b = row[j - 1] + MOVE if row[j - 1] > NEG / 2 else NEG
                    hb = hr[j - 1]
                if b > a:
                    a, ha = b, hb
                if a > NEG / 2:
                    new[j], newh[j] = a + lp.get(c, -9.0), ha
                    if new[j] > top:
                        top = new[j]
            score[gi], hist[gi] = new, newh
        rest_s, rest_h = max(rest_s + STAY, best_end + MOVE) + rest_obs, (best_h if best_end + MOVE > rest_s + STAY else rest_h)
        top = max(top, rest_s)
        for gi in range(len(keys)):                                # beam pruning
            row = score[gi]
            for j in range(len(row)):
                if row[j] < top - beam:
                    row[j] = NEG
    # finish: best of rest or any word end
    best, bh = rest_s, rest_h
    for gi, k in enumerate(keys):
        if score[gi][-1] > best:
            best, bh = score[gi][-1], (hist[gi][-1], k)
    words = []
    h = bh
    while h:
        inner, k = h
        if inner is None:
            break
        prev, start = inner
        words.append((k, start))
        h = prev
    return words[::-1], best


def lip_read(frames, lang="en", words=(), script="", lab=None, learned=None, targets=None, fps=FPS_READ, vocab_size=1500, real=None):
    """Read the lips. With a script: force-align it and score each word; without: decode freely."""
    ts, vs = frame_series(frames, fps)
    if len(vs) < 5:
        return {"error": "No face was found in enough frames to read the lips."}
    use = learned if (learned and learned.get("visemes")) else real if real else learned   # this camera's own model wins; else real faces
    models = class_models(targets, use)
    post = [_loglik(models, fv) for fv in vs]
    best_cls = [best_class(p) for p in post]
    out = {"engine": "VSE %s (HMM word network over Gaussian %s models)" % (VERSION, "viseme" if UNIT == "viseme" else "mouth-class"), "fps": fps,
           "class_models": "learned from your recordings" if (learned and use is learned) else (real.get("about") or "measured on real faces") if (real and use is real)
                            else "built from the lip-sync targets",
           "timeline": [{"class": c, "start": round(ts[i], 2)} for i, c in enumerate(best_cls) if i == 0 or c != best_cls[i - 1]]}
    if script.strip():
        out["script"] = align_script(post, ts, script, lang, lab)
    lex = lexicon(lang, tuple(w.lower() for w in words), lab, size=vocab_size)      # vocab_size=0: only the expected words (a closed set)
    segs = speech_segments(best_cls, fps)
    read = []
    for a, b in segs[:20]:
        ws, sc = decode(post[a:b], lex)
        items = []
        for idx, (k, st) in enumerate(ws):
            en = ws[idx + 1][1] if idx + 1 < len(ws) else b - a
            conf = sum(math.exp(post[a + i].get(c, -9)) for i, c in _spread(lex[k]["seq"], st, en)) / max(1, en - st)
            items.append({"word": lex[k]["words"][0], "same_on_lips": lex[k]["words"][1:8], "looks_like": " ".join(lex[k]["seq"]),
                          "from_s": round(ts[a + st], 2), "to_s": round(ts[min(len(ts) - 1, a + en - 1)], 2), "confidence": round(conf, 2)})
        read.append({"from_s": round(ts[a], 2), "to_s": round(ts[b - 1], 2), "words": items,
                     "confidence": round(sum(i["confidence"] for i in items) / len(items), 2) if items else 0.0})
    out["lipread"] = {"segments": read, "text": " ".join(w["word"] for s in read for w in s["words"]),
                      "vocabulary_groups": len(lex),
                      "note": "Each word is shown with the words that look the same on the lips; give a script or expected words for a reliable check."}
    return out


def speech_segments(cls, fps, rest_s=0.3, closed_s=0.45):
    """Stretches of speech: split where the mouth rests for rest_s, or stays closed for closed_s (a p, b or m
    lasts well under that, so it stays inside its word)."""
    n, out, i, start = len(cls), [], 0, None
    while i < n:
        c = cls[i]
        if c in "-P":
            j = i
            while j < n and cls[j] in "-P":
                j += 1
            run = cls[i:j]
            long_rest = run.count("-") >= rest_s * fps or (j - i) >= closed_s * fps
            if long_rest or start is None and all(x == "-" for x in run) or j == n and all(x == "-" for x in run):
                if start is not None:
                    out.append((start, i)); start = None
                # keep closed lips that lead straight into speech (a word-initial p, b or m)
                k = j
                while k > i and cls[k - 1] == "P" and (j - k) < 0.2 * fps:
                    k -= 1
                if k < j and j < n:
                    start = k
                i = j
                continue
            if start is None:
                start = i
            i = j
            continue
        if start is None:
            start = i
        i += 1
    if start is not None:
        out.append((start, n))
    return [(a, b) for a, b in out if b - a >= max(3, int(0.1 * fps))]


def _spread(k, st, en):
    """Frames st..en spread evenly over the classes of word k (for a confidence figure)."""
    n = max(1, en - st)
    return [(st + i, k[min(len(k) - 1, int(i * len(k) / n))]) for i in range(n)]


def align_script(post, ts, script, lang="en", lab=None):
    """Force-align a script's mouth classes to the frames (Viterbi on a left-to-right chain with optional rests)."""
    wp = visemes.word_phonemes(re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", script), lang, lab)
    chain, owner = [], []
    for wi, w in enumerate(wp):
        for c in word_units(w["phonemes"]) or ["DD" if UNIT == "viseme" else "T"]:
            chain.append(c); owner.append(wi)
    if not chain:
        return {"agreement": 0, "words": []}
    NEG = -1e18
    n, m = len(post), len(chain)
    S = [[NEG] * m for _ in range(n)]
    B = [[0] * m for _ in range(n)]
    S[0][0] = post[0].get(chain[0], -9)
    for t in range(1, n):
        for j in range(m):
            a = S[t - 1][j] + STAY
            b = S[t - 1][j - 1] + MOVE if j else NEG
            # a rest inside or between words costs little when the mouth is resting
            obs = post[t].get(chain[j], -9)
            rest = max(post[t].get(REST_UNITS[UNIT][0], -9), post[t].get(REST_UNITS[UNIT][1], -9)) - 1.0
            S[t][j] = max(a, b) + max(obs, rest)
            B[t][j] = j if a >= b else j - 1
    path, j = [], m - 1
    for t in range(n - 1, -1, -1):
        path.append(j)
        j = B[t][j]
    path.reverse()
    # agreement = how much of each frame's probability falls on the expected sound's look-alike class
    # (the lips cannot show t from n from k, so that difference is not held against the script)
    cls_of = (lambda u: lipread.FROM_VISEME.get(u, "T")) if UNIT == "viseme" else (lambda u: u)
    per = {}
    for t, j in enumerate(path):
        want = cls_of(chain[j])
        per.setdefault(owner[j], []).append(sum(math.exp(v) for u, v in post[t].items() if cls_of(u) == want))
    words = []
    for wi, w in enumerate(wp):
        v = per.get(wi, [])
        fr = [t for t, j in enumerate(path) if owner[j] == wi]
        words.append({"word": w["word"], "agreement": round(sum(v) / len(v), 2) if v else 0.0,
                      "from_s": round(ts[fr[0]], 2) if fr else None, "to_s": round(ts[fr[-1]], 2) if fr else None,
                      "looks_like": lipread.word_classes(w["phonemes"])})
    chance = 1.0 / len(CLASSES)
    raw = sum(x["agreement"] for x in words) / len(words)
    return {"agreement": int(round(100 * max(0.0, (raw - chance) / (1 - chance)))), "raw_match": int(round(100 * raw)),
            "chance_match": int(round(100 * chance)), "words": words,
            "verdict": "the lips agree with the script" if raw >= 0.45 else "weak agreement — a different speaker, dubbing, or a poor view of the mouth"}


# ============================================================================ personal targets from the reservoir
def learn_targets(rows):
    """Mean mouth features per viseme over labelled reservoir frames (centres of each viseme run) → targets."""
    acc = {}
    for frames, labels in rows:
        for fr, lb in zip(frames, labels):
            if not lb or not isinstance(lb, (list, tuple)) or len(lb) < 2:
                continue
            v = lb[1]
            if v in TARGETS:
                acc.setdefault(v, []).append(fr[1:1 + len(PARAMS)])
    out = {}
    for v, vs in acc.items():
        if len(vs) >= 15:
            out[v] = [round(sum(x[i] for x in vs) / len(vs), 4) for i in range(len(PARAMS))]
    return out


# ============================================================================ benchmark
BENCH_SENTENCES = ["please open the window", "the boy is very happy today", "my father is at home", "we can see the moon",
                   "thank you for the food", "where is the big blue book", "she will be back in five minutes",
                   "do you want some more water", "i like to walk in the park", "they made a good choice",
                   "bring me the black cup", "how are you this morning", "the fish swam away fast", "open your mouth wide",
                   "we love music and books", "put the map on the table"]


def _speaker(rnd):
    """A synthetic speaker: their own mouth-shape scale, offsets, speed and tracker noise."""
    return {"scale": rnd.uniform(0.75, 1.25), "offset": [rnd.gauss(0, 0.02) for _ in PARAMS], "rate": rnd.uniform(3.8, 5.2),
            "noise": rnd.uniform(0.02, 0.05), "jitter": rnd.uniform(0.0, 0.015), "fps": rnd.choice([25, 30, 60])}


def synthetic_frames(text, spk, rnd, lab=None):
    """Frames as a tracker would send them for a synthetic speaker saying `text`, plus the true viseme per frame."""
    tr = timing_from_text(text, "en", lab, spk["rate"])
    mo = lip_sync(tr, None, None, fps=spk["fps"], seed=text)["motion"]
    frames, truth = [], []
    vis = tr["visemes"]
    k = 0
    for f in mo["frames"]:
        t = f["time"]
        while k + 1 < len(vis) and vis[k]["end"] <= t:
            k += 1
        fv = [max(0.0, NEUTRAL[i] + (x - NEUTRAL[i]) * spk["scale"] + spk["offset"][i] + rnd.gauss(0, spk["noise"]))
              for i, x in enumerate(f["mouth"])]
        frames.append({"t": round(t + rnd.gauss(0, spk["jitter"]), 4), "face": True, "_fv": [round(x, 4) for x in fv]})
        truth.append(lipread.FROM_VISEME.get(vis[k]["v"], "T"))
    return frames, truth, tr


def _group_of(word, lang="en", lab=None):
    wp = visemes.word_phonemes([word], lang, lab)[0]
    return lipread.word_classes(wp["phonemes"])


def _wer(ref, hyp):
    n, m = len(ref), len(hyp)
    D = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        D[i][0] = i
    for j in range(m + 1):
        D[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D[i][j] = min(D[i - 1][j] + 1, D[i][j - 1] + 1, D[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]))
    return D[n][m] / max(1, n)


def benchmark(lab=None, reservoir_rows=None, speakers=4, sentences=None, progress=None, learned=None):
    """Measure lip reading (VSE against v1) and lip sync, on synthetic speakers and, when given, on real
    held-out recordings from the ingestion reservoir. Deterministic."""
    t0 = time.time()
    sents = sentences or BENCH_SENTENCES
    rnd = _rng("vse-bench", VERSION)
    res = {"version": VERSION, "synthetic": {}, "real": None}
    acc = {"v1_frames": [0, 0], "vse_frames": [0, 0], "v1_wer": [], "vse_wer": [], "v1_vwer": [], "vse_vwer": [],
           "v1_script": [], "vse_script": []}
    total = speakers * len(sents)
    done = 0
    vocab_words = tuple(sorted({w for s in sents for w in s.split()}))
    for si in range(speakers):
        spk = _speaker(rnd)
        for s in sents:
            frames, truth, tr = synthetic_frames(s, spk, rnd, lab)
            ref = s.split()
            # frame classes: v1 rules against VSE models
            ts, vs = frame_series(frames, spk["fps"])
            models = class_models()
            truth_at = lambda t: truth[min(len(truth) - 1, int(t * spk["fps"]))]
            for t, fv in zip(ts, vs):
                tru = truth_at(t)
                if tru == "-":
                    continue
                d = {"_fv": fv}
                acc["v1_frames"][0] += lipread.frame_class(d, "rules") == tru; acc["v1_frames"][1] += 1
                acc["vse_frames"][0] += best_class(_loglik(models, fv)) == tru; acc["vse_frames"][1] += 1
            # free lip reading with the sentence words expected (both engines get the same help)
            v1 = lipread.analyse([{"t": f["t"], "face": True, **_as_tracker(f["_fv"])} for f in frames], {}, None, 100, "", "en",
                                 list(vocab_words), lab, True)
            v1_words = (v1.get("lipread") or {}).get("text", "").split()
            ve = lip_read(frames, "en", vocab_words, "", lab, learned)
            ve_words = (ve.get("lipread") or {}).get("text", "").split()
            acc["v1_wer"].append(_wer(ref, v1_words)); acc["vse_wer"].append(_wer(ref, ve_words))
            g = lambda ws: [_group_of(w, "en", lab) for w in ws]
            acc["v1_vwer"].append(_wer(g(ref), g(v1_words))); acc["vse_vwer"].append(_wer(g(ref), g(ve_words)))
            # script check: right script vs a wrong one (does the score separate them?)
            wrong = sents[(sents.index(s) + 5) % len(sents)]
            cls100 = lipread.classes_of([{"t": f["t"], "face": True, **_as_tracker(f["_fv"])} for f in frames], 100, "rules")[0]
            s1r = lipread.script_agreement(cls100, s, "en", lab)["agreement"]
            s1w = lipread.script_agreement(cls100, wrong, "en", lab)["agreement"]
            vr = lip_read(frames, "en", (), s, lab, learned)["script"]["agreement"]
            vw = lip_read(frames, "en", (), wrong, lab, learned)["script"]["agreement"]
            acc["v1_script"].append(s1r > s1w); acc["vse_script"].append(vr > vw)
            done += 1
            if progress:
                progress(done, total, "synthetic speaker %d: %s" % (si + 1, s))
    mean = lambda v: round(sum(v) / len(v), 3) if v else None
    res["synthetic"] = {
        "speakers": speakers, "sentences": len(sents), "utterances": total,
        "frame_class_accuracy": {"v1": round(acc["v1_frames"][0] / max(1, acc["v1_frames"][1]), 3),
                                 "vse": round(acc["vse_frames"][0] / max(1, acc["vse_frames"][1]), 3)},
        "word_error_rate": {"v1": mean(acc["v1_wer"]), "vse": mean(acc["vse_wer"])},
        "lookalike_group_error_rate": {"v1": mean(acc["v1_vwer"]), "vse": mean(acc["vse_vwer"])},
        "script_check_separates_right_from_wrong": {"v1": mean([1.0 if x else 0.0 for x in acc["v1_script"]]),
                                                    "vse": mean([1.0 if x else 0.0 for x in acc["vse_script"]])},
        "note": "Synthetic speakers made by this engine's own lip-sync model: a regression check, not a real-world accuracy figure."}
    if reservoir_rows:
        res["real"] = _bench_real(reservoir_rows, lab, learned)
    res["seconds"] = round(time.time() - t0, 2)
    return res


def _as_tracker(fv):
    """A 13-number feature vector back into the tracker's frame fields (so lip-reading v1 can read it)."""
    g = lambda k: fv[_I[k]]
    return {"gap": g("gap"), "bs": {"jawOpen": g("jawOpen"), "mouthClose": g("mouthClose"), "mouthPressLeft": g("press"),
                                    "mouthPressRight": g("press"), "mouthRollLower": g("mouthRollLower"), "mouthRollUpper": g("mouthRollUpper"),
                                    "mouthFunnel": g("mouthFunnel"), "mouthPucker": g("mouthPucker"), "mouthStretchLeft": g("stretch"),
                                    "mouthStretchRight": g("stretch"), "mouthSmileLeft": g("smile"), "mouthSmileRight": g("smile"),
                                    "mouthUpperUpLeft": g("upperUp"), "mouthUpperUpRight": g("upperUp"), "mouthLowerDownLeft": g("lowerDown"),
                                    "mouthLowerDownRight": g("lowerDown"), "mouthShrugLower": g("mouthShrugLower")}}


def _bench_real(rows, lab=None, learned=None):
    """Held-out reservoir recordings: frame-class accuracy (v1 rules vs VSE) and lip-sync fit (synthesized
    mouth against the measured mouth, from the same words and timing)."""
    fc = {"v1": [0, 0], "vse": [0, 0]}
    corr_gap, mae = [], []
    targets = learn_targets([(r["frames"], r["labels"]) for r in rows if r.get("split") == "train"])
    models = class_models(targets, learned)
    tests = [r for r in rows if r.get("split") == "test"]
    for r in tests:
        for fr, lb in zip(r["frames"], r["labels"]):
            if not lb:
                continue
            fv = fr[1:1 + len(PARAMS)]
            tru = lb[0]
            if tru == "-":
                continue
            fc["v1"][0] += lipread.frame_class({"_fv": fv}, "rules") == tru; fc["v1"][1] += 1
            fc["vse"][0] += best_class(_loglik(models, fv)) == tru; fc["vse"][1] += 1
        if r.get("word_times") and r["frames"]:
            wt = r["word_times"]
            tr = timing_from_text(r["text"], r.get("lang") or "en", lab)
            # re-time the synthetic track onto the measured word times (same words, real timing)
            words = tr["words"]
            if len(words) == len(wt):
                mp = []
                for w, x in zip(words, wt):
                    mp.append((w["start"], w["end"], float(x["start_s"]), float(x["end_s"])))
                def remap(t):
                    for a, b, c, d in mp:
                        if a <= t <= b:
                            return c + (t - a) * (d - c) / max(1e-6, b - a)
                    return t
                tr["visemes"] = [dict(s, start=round(remap(s["start"]), 3), end=round(remap(s["end"]), 3)) for s in tr["visemes"]]
                tr["duration"] = max(tr["duration"], max(float(x["end_s"]) for x in wt) + 0.2)
            mo = lip_sync(tr, None, None, fps=100, targets=targets)["motion"]["frames"]
            meas = [(fr[0], fr[1]) for fr in r["frames"]]
            synth = [mo[min(len(mo) - 1, int(t * 100))]["mouth"][0] for t, _ in meas]
            real = [g for _, g in meas]
            if len(real) > 5:
                corr_gap.append(_corr(real, synth))
                mae.append(sum(abs(a - b) for a, b in zip(real, synth)) / len(real))
    return {"held_out_recordings": len(tests),
            "frame_class_accuracy": {k: round(v[0] / v[1], 3) if v[1] else None for k, v in fc.items()},
            "lip_sync_mouth_opening_correlation": round(sum(corr_gap) / len(corr_gap), 3) if corr_gap else None,
            "lip_sync_mouth_opening_mean_error": round(sum(mae) / len(mae), 4) if mae else None,
            "personal_targets_learned": sorted(targets)}


def _corr(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a)); sb = math.sqrt(sum((x - mb) ** 2 for x in b))
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / ((sa * sb) or 1.0)


# ============================================================================ COL — jobs
class Engine:
    """Background jobs for the API: lip_sync, lip_read and benchmark, each polled by id."""

    def __init__(self, speech_lab=None, lab=None, coach=None):
        self.sl, self.lab, self.coach = speech_lab, lab, coach
        self.jobs = {}
        self._lock = threading.Lock()
        self.human = None                     # the human motion model (Quality lab), set by the app
        self.real = None                      # (1.48) viseme models measured on real faces, set by the app
        self.stt_timing = True                # (1.48) time speech by Speech-to-Text word times when Google is set up

    def _learned(self):
        return lipread.ACTIVE.get("model") if isinstance(lipread.ACTIVE.get("model"), dict) else None

    def _targets(self):
        try:
            rows = self.coach.store.query("SELECT frames, labels FROM ingest_reservoir WHERE split = 'train' ORDER BY id DESC LIMIT 400") if self.coach else []
            return learn_targets([(json.loads(r["frames"]), json.loads(r["labels"] or "[]")) for r in rows])
        except Exception:
            return {}

    def submit(self, kind, fn):
        jid = uuid.uuid4().hex[:12]
        job = {"job_id": jid, "kind": kind, "status": "queued", "created": _now(), "progress": None, "result": None, "error": None}
        with self._lock:
            self.jobs[jid] = job
            for old in sorted(self.jobs.values(), key=lambda j: j["created"])[:-50]:
                self.jobs.pop(old["job_id"], None)

        def run():
            job["status"] = "running"
            t0 = time.time()
            try:
                job["result"] = fn(lambda d, t=None, m="": job.update(progress={"done": d, "total": t, "message": m}))
                job["status"] = "completed"
            except Exception as e:
                job["status"], job["error"] = "failed", str(e)
            job["seconds"] = round(time.time() - t0, 2)
        threading.Thread(target=run, daemon=True).start()
        return {"job_id": jid, "status": "queued"}

    def status(self, jid):
        j = self.jobs.get(jid)
        if not j:
            raise KeyError("no such job")
        return j

    # -- pipelines
    def lip_sync_job(self, wav, text, lang="en", word_times=None, fps=30, emotion_override=None, personal=True):
        def fn(progress):
            progress(1, 4, "audio: phonemes, prosody, emotion, voice")
            wt, timing = word_times, "word times given" if word_times else "fitted to the sound"
            if not wt and self.sl is not None and self.stt_timing:
                try:                                      # (1.48) Speech-to-Text word times, fitted to the script's words
                    if self.sl.stt_ready():
                        r = self.sl.transcribe(wav, lang)
                        wt = visemes.fit_word_times(text, (r or {}).get("words") or []) if r and not r.get("error") else None
                        timing = "Speech-to-Text word times" if wt else "fitted to the sound (Speech-to-Text did not match the words)"
                except Exception:
                    wt = None
            a = aps(wav, text, lang, self.lab, wt)
            emo = dict(a["emotion"])
            if emotion_override:
                emo.update({k: float(v) for k, v in emotion_override.items() if k in EMOTION_KEYS})
            progress(2, 4, "lip sync and face motion")
            hm = self.human() if self.human else {}
            tg = dict(hm.get("targets") or {})                              # mouth shapes learned from real speakers
            if personal:
                tg.update(self._targets())                                   # this speaker's own shapes win
            ls = lip_sync(a["track"], a["prosody"], emo, fps=int(fps), targets=tg, seed=text, style=hm.get("style"))
            progress(4, 4, "done")
            return {"phonemes": a["phonemes"], "emotion": emo, "speaker_embedding": a["speaker_embedding"],
                    "prosody_summary": {"pitch_hz": a["measure"]["pitch"].get("mean_hz"), "rate_syl_s": a["measure"]["rate"]["articulation_rate_syl_s"]},
                    "visemes": ls["viseme_sequence"], "motion": ls["motion"], "arkit_csv": arkit_csv(ls["motion"]), "arkit52_csv": arkit52_csv(ls["motion"]),
                    "personal_targets": sorted(tg), "duration": a["duration"], "human_model": hm.get("version", 0),
                    "words": [{"word": w["word"], "start": w["start"], "end": w["end"]} for w in a["track"].get("words", [])], "timing": timing}
        return fn

    def lip_read_job(self, frames, lang="en", words=(), script=""):
        def fn(progress):
            progress(1, 2, "face analysis")
            v = vps(frames)
            progress(1, 2, "reading the lips")
            r = lip_read(frames, lang, tuple(words), script, self.lab, self._learned(), self._targets(), real=self.real)
            r["vps"] = v
            return r
        return fn

    def benchmark_job(self):
        def fn(progress):
            rows = []
            if self.coach:
                for r in self.coach.store.query("SELECT text, lang, word_times, frames, labels, split FROM ingest_reservoir ORDER BY id"):
                    rows.append({"text": r["text"], "lang": r["lang"], "word_times": json.loads(r["word_times"]) if r["word_times"] else None,
                                 "frames": json.loads(r["frames"]), "labels": json.loads(r["labels"] or "[]"), "split": r["split"]})
            return benchmark(self.lab, rows or None, progress=progress, learned=self._learned())
        return fn
