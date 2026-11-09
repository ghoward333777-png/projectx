"""Speech Science Protocol (SSP-1): measuring the lips, mouth and face against what is being said.

Every talking head (a person on video, or an avatar recorded from its own canvas) is measured the same way:

  1. FRAMES   the face tracker (MediaPipe Face Landmarker, in the browser) reads EVERY frame of the file by seeking (never
              by playing, so nothing is skipped on a slow computer): the lip gap, 52 face-muscle activations (ARKit
              names) and the head pose.
  2. TIMING   each word gets its start and end: Speech-to-Text word times fitted to the script, or the script fitted to
              the sound (speech stretches and syllable peaks), or the script aligned to the lips (Viterbi), or the words
              read from the lips. Each word is split into its sounds (espeak-ng IPA → 15 visemes), each sound given a
              share of the word by its phonetic weight.
  3. FACTORS  ~20 movement factors (FACTORS below) are computed per frame, then per sound, word and phrase (mean,
              peak, range), plus the dynamics (speed, jerk, blinks, head movement) over the whole delivery.
  4. FORMULA  per sound: z_f = (x_f − μ[v,f]) / σ[v,f] for the factors f that matter for that viseme v (weights
              w[v,f]); D = √(Σ w·z² / Σ w); Articulation Conformance AC = 100·exp(−D²/2). Word AC = duration-weighted
              mean of its sounds; phrase AC = sound-count-weighted mean of its words. A closure (smallest opening) or a
              vowel's opening peak is looked for within ±TAU of its sound (sound boundaries are uncertain by ~50 ms).
              Naturalness N = 100·exp(−Σ severity) over the human-limit checks (HUMAN_LIMITS).
              Delivery Index DI = Σ c_k·S_k / Σ c_k over the components measured: AC (0.45), A/V sync (0.20),
              intelligibility (0.20, chance-corrected agreement of the lips with the script), N (0.15).
  5. VERDICT  pre-registered criteria (CRITERIA) — fixed before any data is seen, never tuned to a result. A criterion
              whose instrument is not yet validated is measured and reported as EXPLORATORY and does not decide the
              verdict. Every failed criterion is reported with the measured value, the limit, and the words and factors.
  6. GROUPS   deliveries labelled by dialect, accent or emotion are compared with clip-level means as the independent
              units (words are nested in clips: no pseudo-replication): n, mean, SD, 95% CI, Hedges' g against the
              baseline group, Welch's t-test, Holm–Bonferroni across factors. A group signature (its g per factor) is
              tested by leave-one-clip-out nearest-centroid classification against chance (exact binomial).

The expectations μ, σ start as PROVISIONAL priors (articulatory phonetics, marked as such in every report). Once 30 or
more reference sounds of a viseme exist for a language (deliveries marked "reference"), they are CALIBRATED from them.
Deterministic: the same inputs give the same numbers and the same report (inputs are fingerprinted with SHA-256).
"""
import hashlib, json, math, os, sqlite3, threading, time

PROTOCOL = "SSP-1.0"
VISEMES = ["sil", "PP", "FF", "TH", "DD", "kk", "CH", "SS", "nn", "RR", "aa", "E", "I", "O", "U"]


def _m(bs, *keys):
    v = [float(bs.get(k) or 0.0) for k in keys]
    return sum(v) / len(v) if v else 0.0


# code: (name, what it measures, how it is computed from one frame)
FACTORS = {
    "A":  ("lip aperture", "lip gap ÷ mouth width (0 closed … ~0.6 wide open)", lambda f, b: float(f.get("gap") or 0.0)),
    "J":  ("jaw opening", "jawOpen activation 0–1", lambda f, b: _m(b, "jawOpen")),
    "W":  ("lip spread", "mean mouthStretch L/R", lambda f, b: _m(b, "mouthStretchLeft", "mouthStretchRight")),
    "S":  ("smile (corners raised)", "mean mouthSmile L/R", lambda f, b: _m(b, "mouthSmileLeft", "mouthSmileRight")),
    "R":  ("lip rounding", "max(mouthPucker, mouthFunnel)", lambda f, b: max(_m(b, "mouthPucker"), _m(b, "mouthFunnel"))),
    "C":  ("lip closure / press", "max(mouthClose, mean mouthPress L/R)", lambda f, b: max(_m(b, "mouthClose"), _m(b, "mouthPressLeft", "mouthPressRight"))),
    "Lu": ("upper-lip raise", "mean mouthUpperUp L/R", lambda f, b: _m(b, "mouthUpperUpLeft", "mouthUpperUpRight")),
    "Ll": ("lower-lip drop", "mean mouthLowerDown L/R", lambda f, b: _m(b, "mouthLowerDownLeft", "mouthLowerDownRight")),
    "Ro": ("lip roll (inward)", "mean mouthRollLower/Upper", lambda f, b: _m(b, "mouthRollLower", "mouthRollUpper")),
    "Bi": ("inner-brow raise", "browInnerUp", lambda f, b: _m(b, "browInnerUp")),
    "Bo": ("outer-brow raise", "mean browOuterUp L/R", lambda f, b: _m(b, "browOuterUpLeft", "browOuterUpRight")),
    "Bd": ("brow lowering", "mean browDown L/R", lambda f, b: _m(b, "browDownLeft", "browDownRight")),
    "Ch": ("cheek raise", "mean cheekSquint L/R", lambda f, b: _m(b, "cheekSquintLeft", "cheekSquintRight")),
    "Es": ("eye squint", "mean eyeSquint L/R", lambda f, b: _m(b, "eyeSquintLeft", "eyeSquintRight")),
    "Ew": ("eye widening", "mean eyeWide L/R", lambda f, b: _m(b, "eyeWideLeft", "eyeWideRight")),
    "Ns": ("nose wrinkle", "mean noseSneer L/R", lambda f, b: _m(b, "noseSneerLeft", "noseSneerRight")),
    "As": ("left–right asymmetry", "mean |L−R| of smile, stretch, upper-lip raise, lower-lip drop",
           lambda f, b: (abs(_m(b, "mouthSmileLeft") - _m(b, "mouthSmileRight")) + abs(_m(b, "mouthStretchLeft") - _m(b, "mouthStretchRight")) +
                         abs(_m(b, "mouthUpperUpLeft") - _m(b, "mouthUpperUpRight")) + abs(_m(b, "mouthLowerDownLeft") - _m(b, "mouthLowerDownRight"))) / 4),
}
DYNAMICS = {
    "Va": ("aperture speed", "90th percentile of |dA/dt| (mouth widths per second)"),
    "Jk": ("aperture jerk", "RMS of the third derivative of A (smoothed), widths/s³ ÷ 1000"),
    "Bl": ("blink rate", "blinks per minute (eyeBlink > 0.5 onsets)"),
    "Hm": ("head movement", "sum over yaw, pitch, roll of the 5–95 percentile range (degrees)"),
    "Mv": ("mouth activity during speech", "SD of A over the spoken frames"),
}

# Provisional expectations per viseme: (μ, σ) on the factor's own scale, and the factor's weight for that sound.
_P = lambda a, j, r=(0.08, 0.08), w=(0.10, 0.10), c=None, wt=None: {"A": a, "J": j, "R": r, "W": w, **({"C": c} if c else {}), "_w": wt or {"A": 2, "J": 1}}
PRIORS = {
    "sil": _P((0.03, 0.04), (0.04, 0.04), wt={"A": 1}),
    "PP":  _P((0.02, 0.03), (0.04, 0.04), c=(0.30, 0.20), wt={"A": 2, "C": 1}),
    "FF":  _P((0.06, 0.05), (0.06, 0.05), wt={"A": 2, "J": 0.5}),
    "TH":  _P((0.12, 0.06), (0.10, 0.06), wt={"A": 1, "J": 0.5}),
    "DD":  _P((0.14, 0.07), (0.10, 0.06), wt={"A": 1, "J": 0.5}),
    "kk":  _P((0.16, 0.08), (0.12, 0.07), wt={"A": 1, "J": 0.5}),
    "CH":  _P((0.12, 0.06), (0.08, 0.06), r=(0.30, 0.15), wt={"A": 1, "R": 1}),
    "SS":  _P((0.08, 0.05), (0.06, 0.05), w=(0.20, 0.12), wt={"A": 1.5, "W": 0.5}),
    "nn":  _P((0.12, 0.07), (0.09, 0.06), wt={"A": 1, "J": 0.5}),
    "RR":  _P((0.14, 0.07), (0.10, 0.06), r=(0.25, 0.15), wt={"A": 1, "R": 1}),
    "aa":  _P((0.38, 0.12), (0.30, 0.12), wt={"A": 2, "J": 1.5}),
    "E":   _P((0.26, 0.10), (0.20, 0.10), w=(0.22, 0.12), wt={"A": 2, "J": 1, "W": 0.5}),
    "I":   _P((0.16, 0.08), (0.12, 0.07), w=(0.30, 0.15), wt={"A": 1, "W": 1.5}),
    "O":   _P((0.30, 0.10), (0.22, 0.10), r=(0.35, 0.15), w=(0.05, 0.05), wt={"A": 1.5, "R": 2, "J": 0.5}),
    "U":   _P((0.18, 0.08), (0.12, 0.07), r=(0.45, 0.15), w=(0.05, 0.05), wt={"A": 1, "R": 2}),
}
CALIBRATE_MIN = 30
TAU = 0.06                      # timing tolerance (s): a closure or an opening peak is looked for within ±TAU of its sound

# Human limits: what a human face cannot (or practically does not) do while speaking. severity grows with the excess.
HUMAN_LIMITS = [
    ("over_open", "lips opened wider than a human mouth (A > 0.75)", lambda d: max(0.0, d["dyn"]["A_p99"] - 0.75) * 10),
    ("too_fast", "lips moved faster than human lips (aperture speed p99 > 6 widths/s)", lambda d: max(0.0, d["dyn"]["Va_p99"] - 6.0) / 2),
    ("contradiction", "lips pressed shut and wide open at once (closure > 0.5 with A > 0.25) in > 5% of frames",
     lambda d: max(0.0, d["dyn"]["contradiction_share"] - 0.05) * 20),
    ("lopsided", "one side of the mouth moves far more than the other (mean asymmetry > 0.25)", lambda d: max(0.0, d["fac_mean"].get("As", 0) - 0.25) * 8),
    ("frozen", "lips barely move while speaking (SD of A < 0.02 over the spoken frames)", lambda d: (0.02 - d["dyn"]["Mv"]) * 60 if d["dyn"]["Mv"] < 0.02 else 0.0),
    ("shut_vowels", "lips stay nearly closed on open vowels (A < 0.08 on more than half of aa, E, O)",
     lambda d: max(0.0, d["dyn"]["shut_open_vowels"] - 0.5) * 4 if d["dyn"]["open_vowel_sounds"] >= 3 else 0.0),
    ("blinks", "blink rate outside 4–40 per minute (over ≥ 10 s)",
     lambda d: (0.5 if (d["dyn"]["Bl"] < 4 or d["dyn"]["Bl"] > 40) else 0.0) if d["dyn"]["spoken_s"] >= 10 else 0.0),
]

COMPONENTS = {"AC": 0.45, "sync": 0.20, "intelligibility": 0.20, "naturalness": 0.15}
CRITERIA = [
    ("tracking", "face found in ≥ 90% of frames", lambda d: d["tracking"]["face_share"], 0.90, ">="),
    ("capture", "capture quality ≥ 60/100", lambda d: d["inputs"].get("capture_quality"), 60, ">="),
    ("sync", "|audio–lip offset| ≤ 120 ms", lambda d: abs(d["inputs"]["sync_ms"]) if d["inputs"].get("sync_ms") is not None else None, 120, "<="),
    ("conformance", "Articulation Conformance ≥ 70", lambda d: d["scores"]["AC"], 70, ">="),
    ("intelligibility", "lips agree with the script ≥ 40% (chance-corrected)", lambda d: d["scores"].get("intelligibility"), 40, ">="),
    ("naturalness", "Naturalness ≥ 70 (no movement beyond human limits)", lambda d: d["scores"]["naturalness"], 70, ">="),
]


# ------------------------------------------------------------------------------------------------ small statistics
def _pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return 0.0
    k = (len(xs) - 1) * q
    i = int(k)
    return xs[i] + (xs[min(i + 1, len(xs) - 1)] - xs[i]) * (k - i)


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _sd(xs):
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _betacf(a, b, x):
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > 1e-30 else 1e-30)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d; d = 1 / (d if abs(d) > 1e-30 else 1e-30)
        c = 1 + aa / c if abs(c) > 1e-30 else 1e30
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d; d = 1 / (d if abs(d) > 1e-30 else 1e-30)
        c = 1 + aa / c if abs(c) > 1e-30 else 1e30
        de = d * c
        h *= de
        if abs(de - 1) < 3e-12:
            break
    return h


def _ibeta(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lb = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lb) * _betacf(a, b, x) / a
    return 1 - math.exp(lb) * _betacf(b, a, 1 - x) / b


def t_sf2(t, df):
    """two-sided p-value of Student's t"""
    if df <= 0 or t != t:
        return 1.0
    return _ibeta(df / 2, 0.5, df / (df + t * t))


def t_crit(df, alpha=0.05):
    lo, hi = 0.0, 100.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if t_sf2(mid, df) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


def welch(a, b):
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return None
    va, vb = _sd(a) ** 2 / na, _sd(b) ** 2 / nb
    if va + vb == 0:
        return {"t": 0.0, "df": na + nb - 2, "p": 1.0}
    t = (_mean(a) - _mean(b)) / math.sqrt(va + vb)
    df = (va + vb) ** 2 / ((va ** 2 / (na - 1)) + (vb ** 2 / (nb - 1)) or 1e-12)
    return {"t": t, "df": df, "p": t_sf2(abs(t), df)}


def hedges_g(a, b):
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return None
    sp = math.sqrt(((na - 1) * _sd(a) ** 2 + (nb - 1) * _sd(b) ** 2) / (na + nb - 2))
    if sp == 0:
        return 0.0
    return (_mean(a) - _mean(b)) / sp * (1 - 3 / (4 * (na + nb) - 9))


def holm(ps):
    idx = sorted(range(len(ps)), key=lambda i: ps[i])
    out, run = [1.0] * len(ps), 0.0
    for r, i in enumerate(idx):
        run = max(run, min(1.0, (len(ps) - r) * ps[i]))
        out[i] = run
    return out


def binom_sf(k, n, p):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def ci95(xs):
    n = len(xs)
    if n < 2:
        return None
    h = t_crit(n - 1) * _sd(xs) / math.sqrt(n)
    return [_mean(xs) - h, _mean(xs) + h]


# ------------------------------------------------------------------------------------------------ timing
def segments(words_timed, lang="en", lab=None):
    """[{word, start, end}] → words, each with its sounds [{viseme, symbol, start, end}] (time shared by phonetic weight)"""
    import visemes
    names = [w["word"] for w in words_timed]
    wp = visemes.word_phonemes(names, lang, lab) if names else []
    out = []
    for w, p in zip(words_timed, wp):
        a, b = float(w["start"]), float(w["end"])
        ph = p.get("phonemes") or []
        tot = sum(max(0.01, float(x[2])) for x in ph) or 1.0
        t, sounds = a, []
        for sym, v, wt in ph:
            d = (b - a) * max(0.01, float(wt)) / tot
            sounds.append({"symbol": sym, "viseme": v if v in PRIORS else "DD", "start": round(t, 3), "end": round(t + d, 3)})
            t += d
        out.append({"word": w["word"], "start": a, "end": b, "ipa": p.get("ipa") or "", "sounds": sounds, "source": w.get("source")})
    return out


# ------------------------------------------------------------------------------------------------ the measurement
def _series(frames):
    rows = []
    for f in frames:
        if not f.get("face"):
            continue
        b = f.get("bs") or {}
        v = {k: fn(f, b) for k, (_, _, fn) in FACTORS.items()}
        pose = f.get("pose") or [f.get("pitch") or 0, f.get("yaw") or 0, 0]
        rows.append((float(f.get("t") or 0.0), v, [float(x or 0) for x in pose[:3]], _m(b, "eyeBlinkLeft", "eyeBlinkRight")))
    return rows


def _window(rows, a, b):
    sel = [r for r in rows if a <= r[0] < b]
    if not sel and rows:
        mid = (a + b) / 2
        sel = [min(rows, key=lambda r: abs(r[0] - mid))]
    return sel


def _stats(sel):
    out = {}
    for k in FACTORS:
        xs = [r[1][k] for r in sel]
        out[k] = {"mean": round(_mean(xs), 4), "peak": round(max(xs) if xs else 0.0, 4), "range": round((max(xs) - min(xs)) if xs else 0.0, 4)}
    return out


def expectations(calibration=None, lang="en"):
    out = {}
    cal = (calibration or {}).get(lang) or {}
    for v, pr in PRIORS.items():
        e = {}
        for f, w in pr["_w"].items():
            mu, sd = pr[f]
            basis = "provisional"
            c = (cal.get(v) or {}).get(f)
            if c and c["n"] >= CALIBRATE_MIN and c["sd"] > 0:
                mu, sd, basis = c["mean"], max(c["sd"], 0.02), "calibrated (n=%d)" % c["n"]
            e[f] = {"mu": mu, "sd": sd, "w": w, "basis": basis}
        out[v] = e
    return out


def _plain_fix(f, z):
    return ("%s too small" if z < 0 else "%s too large") % FACTORS[f][0]


def measure(frames, words_timed, lang="en", lab=None, labels=None, text="", inputs=None, calibration=None, info=None):
    """one delivery measured by the protocol. words_timed: [{word, start, end}] in the video's own time."""
    labels = dict(labels or {})
    inputs = dict(inputs or {})
    rows = _series(frames)
    words = segments(words_timed, lang, lab)
    exp = expectations(calibration, lang)
    w_out, sounds_all = [], []
    for w in words:
        s_out = []
        for s in w["sounds"]:
            sel = _window(rows, s["start"], s["end"])
            wide = _window(rows, s["start"] - TAU, s["end"] + TAU)
            st, sw = _stats(sel), _stats(wide)
            e = exp.get(s["viseme"]) or exp["DD"]
            z, num, den = {}, 0.0, 0.0
            for f, q in e.items():
                if s["viseme"] == "PP" and f == "A":
                    x = min(r[1]["A"] for r in wide)
                elif s["viseme"] == "PP" and f == "C":
                    x = sw[f]["peak"]
                elif f in ("A", "J", "R", "W") and s["viseme"] in ("aa", "E", "O", "U", "I"):
                    x = sw[f]["peak"]
                else:
                    x = st[f]["mean"]
                zz = (x - q["mu"]) / q["sd"]
                z[f] = {"x": round(x, 4), "mu": q["mu"], "sd": q["sd"], "z": round(zz, 2), "w": q["w"], "basis": q["basis"]}
                num += q["w"] * zz * zz; den += q["w"]
            D = math.sqrt(num / den) if den else 0.0
            ac = 100 * math.exp(-D * D / 2)
            worst = max(z.items(), key=lambda kv: kv[1]["w"] * kv[1]["z"] ** 2) if z else None
            s_out.append(dict(s, frames=len(sel), D=round(D, 3), AC=round(ac, 1), z=z, factors=st,
                              note=(_plain_fix(worst[0], worst[1]["z"]) if worst and abs(worst[1]["z"]) > 1.5 else "")))
        dur = [max(0.001, x["end"] - x["start"]) for x in s_out]
        wac = sum(d * x["AC"] for d, x in zip(dur, s_out)) / sum(dur) if s_out else 0.0
        wsel = _window(rows, w["start"], w["end"])
        w_out.append({"word": w["word"], "ipa": w["ipa"], "start": round(w["start"], 3), "end": round(w["end"], 3), "AC": round(wac, 1),
                      "sounds": s_out, "factors": _stats(wsel), "source": w.get("source")})
        sounds_all += s_out
    a0 = min((w["start"] for w in w_out), default=0.0)
    b0 = max((w["end"] for w in w_out), default=0.0)
    sp = [r for r in rows if a0 <= r[0] <= b0] or rows
    A = [r[1]["A"] for r in sp]
    ts = [r[0] for r in sp]
    vel = [abs(A[i + 1] - A[i]) / max(1e-3, ts[i + 1] - ts[i]) for i in range(len(A) - 1)]
    sm = [_mean(A[max(0, i - 1): i + 2]) for i in range(len(A))]
    dt = _mean([ts[i + 1] - ts[i] for i in range(len(ts) - 1)]) if len(ts) > 1 else 1 / 30
    jerk = [(sm[i + 3] - 3 * sm[i + 2] + 3 * sm[i + 1] - sm[i]) / (dt ** 3) for i in range(len(sm) - 3)]
    blinks, was = 0, False
    for r in rows:
        on = r[3] > 0.5
        blinks += on and not was
        was = on
    secs = (rows[-1][0] - rows[0][0]) if len(rows) > 1 else 0.0
    pose = list(zip(*[r[2] for r in sp])) if sp else [[], [], []]
    contra = sum(1 for r in sp if r[1]["C"] > 0.5 and r[1]["A"] > 0.25) / max(1, len(sp))
    open_v = [s for s in sounds_all if s["viseme"] in ("aa", "E", "O")]
    dyn = {"Va": round(_pct(vel, 0.9), 3), "Va_p99": round(_pct(vel, 0.99), 3), "Jk": round(math.sqrt(_mean([j * j for j in jerk])) / 1000, 3) if jerk else 0.0,
           "Bl": round(60 * blinks / secs, 1) if secs > 0 else 0.0, "Hm": round(sum(_pct(p, 0.95) - _pct(p, 0.05) for p in pose if p), 2),
           "Mv": round(_sd(A), 4), "A_p99": round(_pct(A, 0.99), 3), "contradiction_share": round(contra, 4),
           "open_vowel_sounds": len(open_v), "shut_open_vowels": round(sum(1 for s in open_v if s["z"].get("A", {}).get("x", 1) < 0.08) / max(1, len(open_v)), 3),
           "spoken_s": round(b0 - a0, 2)}
    fac_mean = {k: round(_mean([r[1][k] for r in sp]), 4) for k in FACTORS}
    d = {"dyn": dyn, "fac_mean": fac_mean}
    checks = []
    for code, text_, fn in HUMAN_LIMITS:
        sev = round(float(fn(d)), 3)
        checks.append({"check": code, "rule": text_, "severity": sev, "passed": sev <= 0})
    naturalness = round(100 * math.exp(-sum(c["severity"] for c in checks)), 1)
    tot_w = sum(len(w["sounds"]) for w in w_out)
    AC = round(sum(len(w["sounds"]) * w["AC"] for w in w_out) / tot_w, 1) if tot_w else 0.0
    scores = {"AC": AC, "naturalness": naturalness}
    if inputs.get("sync_ms") is not None:
        scores["sync"] = round(100 * math.exp(-(float(inputs["sync_ms"]) / 120.0) ** 2), 1)
    if inputs.get("intelligibility") is not None:
        scores["intelligibility"] = round(float(inputs["intelligibility"]), 1)
    used = {k: c for k, c in COMPONENTS.items() if scores.get(k) is not None}
    scores["DI"] = round(sum(c * scores[k] for k, c in used.items()) / sum(used.values()), 1) if used else 0.0
    scores["DI_components"] = {k: round(c / sum(used.values()), 3) for k, c in used.items()}
    out = {"protocol": PROTOCOL, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "lang": lang, "labels": labels, "text": text,
           "info": info or {}, "inputs": inputs, "tracking": {"frames": len(frames), "face_frames": len(rows), "face_share": round(len(rows) / max(1, len(frames)), 3)},
           "words": w_out, "dynamics": dyn, "factor_means": fac_mean, "human_limits": checks, "scores": scores,
           "expectation_basis": sorted({q["basis"].split(" (")[0] for e in exp.values() for q in e.values()})}
    out["fingerprint"] = hashlib.sha256(json.dumps({"frames": frames, "words": words_timed, "lang": lang, "inputs": inputs, "cal": calibration or {}},
                                                   sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    out["verdict"] = verdict(out)
    return out


def _exploratory(code, d):
    """a criterion whose instrument is not validated yet is measured and reported, but does not decide the verdict"""
    if code == "conformance" and any(b != "calibrated" for b in d.get("expectation_basis") or []):
        return "expectations are provisional (not yet calibrated from reference deliveries of this language)"
    if code == "intelligibility":
        return "the lip reader's agreement score is not yet validated against known speech (lip-reading curriculum)"
    return None


def verdict(d):
    rows, failed, flagged = [], [], []
    for code, rule, fn, limit, op in CRITERIA:
        v = fn(d)
        if v is None:
            rows.append({"criterion": code, "rule": rule, "value": None, "passed": None, "status": "not measured"})
            continue
        ok = v >= limit if op == ">=" else v <= limit
        ex = _exploratory(code, d)
        rows.append({"criterion": code, "rule": rule, "value": round(v, 3) if isinstance(v, float) else v, "passed": ok,
                     "status": ("exploratory: " + ex) if ex else "judged"})
        if not ok:
            (flagged if ex else failed).append(code)
    why = []
    if "conformance" in failed or "conformance" in flagged:
        bad = sorted((s for w in d["words"] for s in w["sounds"]), key=lambda s: s["AC"])[:5]
        for s in bad:
            w = next(x["word"] for x in d["words"] if s in x["sounds"])
            top = max(s["z"].items(), key=lambda kv: kv[1]["w"] * kv[1]["z"] ** 2)
            why.append("“%s” /%s/ (%s): %s — %s %.3f, expected %.3f ± %.3f (z = %+.1f)" % (
                w, s["symbol"], s["viseme"], s["note"] or "off target", FACTORS[top[0]][0], top[1]["x"], top[1]["mu"], top[1]["sd"], top[1]["z"]))
    for c in d["human_limits"]:
        if not c["passed"]:
            why.append("beyond human limits: %s (severity %.2f)" % (c["rule"], c["severity"]))
    if "sync" in failed:
        why.append("the lips are %d ms %s the sound" % (abs(d["inputs"]["sync_ms"]), "behind" if d["inputs"]["sync_ms"] > 0 else "ahead of"))
    if "tracking" in failed or "capture" in failed:
        why.append("the face was not seen well enough to judge (tracking %.0f%%, capture %s/100) — not a failure of the speaker" % (
            100 * d["tracking"]["face_share"], d["inputs"].get("capture_quality")))
    if flagged:
        why.append("exploratory (measured, not judged): " + ", ".join(flagged) + " — see the criteria table for why")
    measurable = not ({"tracking", "capture"} & set(failed))
    return {"result": "PASS" if not failed else ("NOT MEASURABLE" if not measurable else "FAIL"), "failed": failed, "exploratory_flags": flagged,
            "criteria": rows, "why": why}


# ------------------------------------------------------------------------------------------------ group comparison
FACTOR_KEYS = list(FACTORS) + ["Va", "Jk", "Bl", "Hm", "Mv"]
MIN_CLIPS = 5


def clip_vector(d):
    v = dict(d["factor_means"])
    for k in ("Va", "Jk", "Bl", "Hm", "Mv"):
        v[k] = d["dynamics"].get(k, 0.0)
    v["AC"] = d["scores"]["AC"]
    return v


def compare(deliveries, by="emotion", baseline=None, word=None):
    """deliveries grouped by a label; clip-level means are the units. word: one word's movement only (matched-word contrast)"""
    groups = {}
    for d in deliveries:
        g = (d.get("labels") or {}).get(by) or (d.get("lang") if by == "language" else None)
        if not g:
            continue
        if word:
            ws = [w for w in d["words"] if w["word"].lower() == word.lower()]
            if not ws:
                continue
            v = {k: _mean([w["factors"][k]["mean"] for w in ws]) for k in FACTORS}
            v["AC"] = _mean([w["AC"] for w in ws])
        else:
            v = clip_vector(d)
        groups.setdefault(g, []).append(v)
    keys = (list(FACTORS) + ["AC"]) if word else (FACTOR_KEYS + ["AC"])
    names = sorted(groups, key=lambda g: (-len(groups[g]), g))
    base = baseline if baseline in groups else (names[0] if names else None)
    table = []
    for g in names:
        row = {"group": g, "n": len(groups[g]), "factors": {}}
        for k in keys:
            xs = [v[k] for v in groups[g]]
            c = ci95(xs)
            row["factors"][k] = {"mean": round(_mean(xs), 4), "sd": round(_sd(xs), 4), "ci95": [round(x, 4) for x in c] if c else None}
        table.append(row)
    contrasts = []
    for g in names:
        if g == base:
            continue
        rows = []
        for k in keys:
            a, b = [v[k] for v in groups[g]], [v[k] for v in groups[base]]
            wt, hg = welch(a, b), hedges_g(a, b)
            rows.append({"factor": k, "diff": round(_mean(a) - _mean(b), 4), "g": round(hg, 3) if hg is not None else None,
                         "t": round(wt["t"], 3) if wt else None, "df": round(wt["df"], 1) if wt else None, "p": wt["p"] if wt else None})
        ps = [r["p"] if r["p"] is not None else 1.0 for r in rows]
        for r, ph in zip(rows, holm(ps)):
            r["significant"] = bool(r["p"] is not None and ph < 0.05)
            if r["p"] is not None:
                r["p"] = round(r["p"], 5)
            r["p_holm"] = round(ph, 5)
        enough = len(groups[g]) >= MIN_CLIPS and len(groups[base]) >= MIN_CLIPS
        sig = sorted([r for r in rows if r["g"] is not None], key=lambda r: -abs(r["g"]))
        contrasts.append({"group": g, "baseline": base, "n": len(groups[g]), "n_baseline": len(groups[base]), "enough_data": enough,
                          "factors": rows, "signature": {r["factor"]: r["g"] for r in sig[:8]},
                          "signature_size": round(math.sqrt(sum((r["g"] or 0) ** 2 for r in rows)), 3)})
    return {"by": by, "baseline": base, "word": word, "groups": table, "contrasts": contrasts, "validation": loo_classify(groups, keys),
            "units": "clip-level means (words nested in clips are not treated as independent)", "min_clips": MIN_CLIPS}


def loo_classify(groups, keys):
    pts = [(g, v) for g, vs in groups.items() for v in vs]
    k = len(groups)
    if k < 2 or len(pts) < 2 * k or any(len(v) < 2 for v in groups.values()):
        return {"done": False, "reason": "needs at least 2 groups with 2+ clips each"}
    mu = {f: _mean([v[f] for _, v in pts]) for f in keys}
    sd = {f: (_sd([v[f] for _, v in pts]) or 1.0) for f in keys}
    zp = [(g, {f: (v[f] - mu[f]) / sd[f] for f in keys}) for g, v in pts]
    hits = 0
    for i, (g, v) in enumerate(zp):
        cents = {}
        for h in groups:
            m = [w for j, (gg, w) in enumerate(zp) if gg == h and j != i]
            if m:
                cents[h] = {f: _mean([w[f] for w in m]) for f in keys}
        pred = min(cents, key=lambda h: sum((v[f] - cents[h][f]) ** 2 for f in keys))
        hits += pred == g
    n = len(zp)
    chance = 1.0 / k
    p = binom_sf(hits, n, chance)
    return {"done": True, "clips": n, "correct": hits, "accuracy": round(hits / n, 3), "chance": round(chance, 3), "p_binomial": round(p, 5),
            "conclusion": ("the groups move measurably differently (p < 0.05)" if p < 0.05 else
                           "no reliable difference in movement between the groups yet (not better than chance)")}


def calibrate(deliveries):
    acc = {}
    for d in deliveries:
        if (d.get("labels") or {}).get("role") != "reference" or d["verdict"]["result"] == "NOT MEASURABLE":
            continue
        for w in d["words"]:
            for s in w["sounds"]:
                for f, z in s["z"].items():
                    acc.setdefault(d["lang"], {}).setdefault(s["viseme"], {}).setdefault(f, []).append(z["x"])
    return {lang: {v: {f: {"mean": round(_mean(xs), 4), "sd": round(_sd(xs), 4), "n": len(xs)} for f, xs in fs.items()} for v, fs in vs.items()}
            for lang, vs in acc.items()}


# ------------------------------------------------------------------------------------------------ reports
def _fmt(x, nd=3):
    return "—" if x is None else (("%." + str(nd) + "f") % x if isinstance(x, float) else str(x))


def methods_text():
    L = ["## Methods (%s)" % PROTOCOL, "",
         "**Instrument.** MediaPipe Face Landmarker (bundled, in the browser): 478 landmarks, 52 face-muscle activations and the head pose for every "
         "frame of the file, read by seeking frame by frame. Lip aperture A = lip gap ÷ mouth width, measured on the landmarks.", "",
         "**Timing.** Words are timed by Speech-to-Text (fitted to the script), by fitting the script to the sound (speech stretches and syllable "
         "peaks), by aligning the script to the lips (Viterbi), or by reading the lips — the report names which. Each word is split into its "
         "sounds (espeak-ng IPA → 15 visemes); a sound's share of the word follows its phonetic weight.", "",
         "**Factors.**", "", "| code | factor | definition |", "|---|---|---|"]
    L += ["| %s | %s | %s |" % (k, v[0], v[1]) for k, v in FACTORS.items()]
    L += ["| %s | %s | %s |" % (k, v[0], v[1]) for k, v in DYNAMICS.items()]
    L += ["", "**Formula.**", "",
          "- per sound s with viseme v: z_f = (x_f − μ[v,f]) / σ[v,f] over the factors that matter for v (weights w[v,f]); for a closure (p, b, m) "
          "x is the smallest opening and for open, rounded and spread vowels the peak, each within ±%d ms of the sound; otherwise the mean over the sound" % int(TAU * 1000),
          "- D_s = √(Σ_f w·z² / Σ_f w);  Articulation Conformance AC_s = 100 · exp(−D_s² / 2)  (AC = 100: exactly as expected; D = 1 σ → 61; 2 σ → 14)",
          "- word AC = duration-weighted mean of its sounds; delivery AC = sound-count-weighted mean of its words",
          "- Naturalness N = 100 · exp(−Σ severity) over the human-limit checks",
          "- Sync S = 100 · exp(−(offset_ms / 120)²);  Intelligibility I = chance-corrected agreement of the lips with the script",
          "- Delivery Index DI = Σ c_k·score_k / Σ c_k over the measured components (c: AC 0.45, sync 0.20, intelligibility 0.20, naturalness 0.15)",
          "", "**Pre-registered criteria** (fixed in the protocol, never tuned to a result). A criterion whose instrument is not yet validated is "
          "measured and reported as *exploratory* and does not decide the verdict: conformance until the expectations are calibrated for the "
          "language; intelligibility until the lip reader is validated on known speech.", ""]
    L += ["- %s: %s" % (c[0], c[1]) for c in CRITERIA]
    L += ["", "**Human limits** (movement a human face does not make while speaking):", ""]
    L += ["- %s: %s" % (c[0], c[1]) for c in HUMAN_LIMITS]
    L += ["", "**Expectations.** μ, σ per viseme start as provisional priors from articulatory phonetics; they are calibrated per language from "
          "reference deliveries once %d or more sounds of a viseme exist. Every result says which basis it used." % CALIBRATE_MIN,
          "", "**Group comparisons.** Units are clip-level means (words are nested in clips: no pseudo-replication). Per group: n, mean, SD, 95%% CI (t). "
          "Contrast with the baseline: Hedges' g, Welch's t-test, Holm–Bonferroni across factors. A group needs ≥ %d clips before its contrast is "
          "interpreted. Validation: leave-one-clip-out nearest-centroid classification against chance (exact binomial test)." % MIN_CLIPS]
    return "\n".join(L)


def report_delivery(d):
    v = d["verdict"]
    L = ["# Delivery report — %s" % v["result"], "",
         "Protocol %s · measured %s · language %s · fingerprint `%s`" % (d["protocol"], d["at"], d["lang"], d["fingerprint"][:16]), "",
         "Labels: " + (", ".join("%s = %s" % kv for kv in sorted(d["labels"].items())) or "none"), "",
         "Text: “%s”" % (d["text"] or " ".join(w["word"] for w in d["words"])), "",
         "## Result", "", "| score | value |", "|---|---|"]
    names = {"DI": "Delivery Index", "AC": "Articulation Conformance", "naturalness": "Naturalness", "sync": "A/V sync", "intelligibility": "Intelligibility"}
    for k in ("DI", "AC", "naturalness", "sync", "intelligibility"):
        if d["scores"].get(k) is not None:
            L.append("| %s | %s |" % (names[k], _fmt(d["scores"][k], 1)))
    L += ["", "Components used for DI (re-weighted): " + ", ".join("%s %.2f" % kv for kv in d["scores"]["DI_components"].items()), "",
          "| criterion | rule | measured | result | status |", "|---|---|---|---|---|"]
    for c in v["criteria"]:
        L.append("| %s | %s | %s | %s | %s |" % (c["criterion"], c["rule"], _fmt(c["value"]), "pass" if c["passed"] else ("not measured" if c["passed"] is None else "**FAIL**"),
                                                c.get("status", "")))
    if v["why"]:
        L += ["", "### Why it %s" % ("failed" if v["result"] != "PASS" else "was flagged")] + ["- " + x for x in v["why"]]
    L += ["", "## Words", "", "| word | IPA | start–end (s) | AC | weakest sound |", "|---|---|---|---|---|"]
    for w in d["words"]:
        ws = min(w["sounds"], key=lambda s: s["AC"]) if w["sounds"] else None
        L.append("| %s | /%s/ | %.2f–%.2f | %.0f | %s |" % (w["word"], w["ipa"], w["start"], w["end"], w["AC"],
                                                            ("%s (%s) %.0f — %s" % (ws["symbol"], ws["viseme"], ws["AC"], ws["note"] or "ok")) if ws else "—"))
    L += ["", "## Movement over the delivery", "", "| factor | mean |", "|---|---|"]
    L += ["| %s %s | %.3f |" % (k, FACTORS[k][0], x) for k, x in d["factor_means"].items()]
    L += ["| %s %s | %s |" % (k, DYNAMICS[k][0], _fmt(d["dynamics"].get(k))) for k in DYNAMICS]
    L += ["", "## Human-limit checks", "", "| check | rule | severity | result |", "|---|---|---|---|"]
    L += ["| %s | %s | %.2f | %s |" % (c["check"], c["rule"], c["severity"], "pass" if c["passed"] else "**FAIL**") for c in d["human_limits"]]
    L += ["", "## Data and exclusions", "",
          "- frames: %d, face found in %d (%.0f%%)" % (d["tracking"]["frames"], d["tracking"]["face_frames"], 100 * d["tracking"]["face_share"]),
          "- word timing: %s" % (", ".join(sorted({w.get("source") or "?" for w in d["words"]})) or "—"),
          "- expectations: %s" % ", ".join(d["expectation_basis"]),
          "- inputs: %s" % ", ".join("%s = %s" % (k, _fmt(x) if not isinstance(x, (dict, list)) else "…") for k, x in sorted(d["inputs"].items())),
          "", methods_text(), "",
          "## Limitations", "",
          "- Provisional expectations are literature-informed, not yet calibrated on this speaker or language; calibrated values replace them once reference deliveries exist.",
          "- One camera view: movement towards or away from the camera (lip protrusion) is seen only through the rounding activations.",
          "- Word timing from the sound or the lips is less exact than Speech-to-Text; the source of the timing is stated above.", "",
          "Reproducibility: the same frames, words, language, inputs and calibration give the same numbers (fingerprint above)."]
    return "\n".join(L)


def report_compare(c):
    L = ["# Group comparison by %s%s" % (c["by"], (" — word “%s”" % c["word"]) if c["word"] else ""), "",
         "Protocol %s · baseline group: %s · units: %s" % (PROTOCOL, c["baseline"], c["units"]), "", "## Groups", "",
         "| group | clips | AC mean (95% CI) | aperture A | rounding R | spread W | inner brow Bi | head Hm |", "|---|---|---|---|---|---|---|---|"]
    for g in c["groups"]:
        f = g["factors"]
        ci = f["AC"]["ci95"]
        L.append("| %s | %d | %.1f (%s) | %.3f | %.3f | %.3f | %.3f | %s |" % (
            g["group"], g["n"], f["AC"]["mean"], ("%.1f–%.1f" % tuple(ci)) if ci else "—", f["A"]["mean"], f["R"]["mean"], f["W"]["mean"], f["Bi"]["mean"],
            _fmt(f.get("Hm", {}).get("mean"), 2)))
    for k in c["contrasts"]:
        L += ["", "## %s vs %s (n = %d vs %d)%s" % (k["group"], k["baseline"], k["n"], k["n_baseline"],
                                                    "" if k["enough_data"] else " — **insufficient data: fewer than %d clips; not interpreted**" % c["min_clips"]), "",
              "| factor | difference | Hedges' g | Welch t (df) | p | p (Holm) | |", "|---|---|---|---|---|---|---|"]
        for r in sorted(k["factors"], key=lambda r: -(abs(r["g"]) if r["g"] is not None else 0)):
            name = FACTORS.get(r["factor"], DYNAMICS.get(r["factor"], ("Articulation Conformance",)))[0]
            L.append("| %s %s | %+.4f | %s | %s | %s | %s | %s |" % (r["factor"], name, r["diff"], _fmt(r["g"]), (
                "%.2f (%.1f)" % (r["t"], r["df"])) if r["t"] is not None else "—", _fmt(r["p"], 4), _fmt(r["p_holm"], 4),
                "significant" if r["significant"] and k["enough_data"] else ""))
        L += ["", "Movement signature (largest effects): " + ", ".join("%s g=%+.2f" % kv for kv in k["signature"].items()) + " · size ‖g‖ = %.2f" % k["signature_size"]]
    v = c["validation"]
    L += ["", "## Is the difference real? (validation)", ""]
    L.append(("Leave-one-clip-out nearest-centroid classification: %d of %d clips correct (%.0f%%; chance %.0f%%), exact binomial p = %s. Conclusion: %s." % (
        v["correct"], v["clips"], 100 * v["accuracy"], 100 * v["chance"], _fmt(v["p_binomial"], 4), v["conclusion"])) if v.get("done") else
             "Not done: " + v["reason"] + ".")
    L += ["", methods_text(), "", "## Limitations", "",
          "- Groups recorded under different conditions (camera, light, distance) differ for those reasons too; record them alike.",
          "- Labels (dialect, accent, emotion) are as given by the person who added the recording; they are not inferred.",
          "- With few clips a large effect can be chance; contrasts with fewer than %d clips per group are listed but not interpreted." % MIN_CLIPS]
    return "\n".join(L)


# ------------------------------------------------------------------------------------------------ the corpus
class Corpus:
    """every measured delivery (SQLite in the app's folder) and the reports written from them"""

    def __init__(self, folder):
        self.folder = os.path.join(folder, "science")
        os.makedirs(os.path.join(self.folder, "reports"), exist_ok=True)
        self.path = os.path.join(self.folder, "deliveries.sqlite")
        self._lock = threading.Lock()
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS deliveries (id INTEGER PRIMARY KEY, at TEXT, fingerprint TEXT UNIQUE, lang TEXT, labels TEXT, "
                       "text TEXT, result TEXT, di REAL, ac REAL, data TEXT)")

    def _db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def add(self, d):
        with self._lock, self._db() as db:
            cur = db.execute("INSERT OR IGNORE INTO deliveries(at, fingerprint, lang, labels, text, result, di, ac, data) VALUES(?,?,?,?,?,?,?,?,?)",
                             (d["at"], d["fingerprint"], d["lang"], json.dumps(d["labels"], sort_keys=True), d["text"], d["verdict"]["result"],
                              d["scores"]["DI"], d["scores"]["AC"], json.dumps(d)))
            if cur.rowcount == 0:
                return db.execute("SELECT id FROM deliveries WHERE fingerprint = ?", (d["fingerprint"],)).fetchone()[0]
            return cur.lastrowid

    def list(self, limit=200):
        with self._db() as db:
            rows = db.execute("SELECT id, at, lang, labels, text, result, di, ac FROM deliveries ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [{"id": r[0], "at": r[1], "lang": r[2], "labels": json.loads(r[3] or "{}"), "text": r[4], "result": r[5], "DI": r[6], "AC": r[7]} for r in rows]

    def get(self, i):
        with self._db() as db:
            r = db.execute("SELECT data FROM deliveries WHERE id = ?", (int(i),)).fetchone()
        return json.loads(r[0]) if r else None

    def all(self, ids=None):
        with self._db() as db:
            rows = db.execute("SELECT id, data FROM deliveries ORDER BY id").fetchall()
        out = []
        for i, data in rows:
            if ids and i not in ids:
                continue
            d = json.loads(data)
            d["id"] = i
            out.append(d)
        return out

    def label(self, i, labels):
        d = self.get(i)
        if not d:
            raise ValueError("no such delivery")
        d["labels"] = {k: str(v)[:60] for k, v in (labels or {}).items() if v not in (None, "")}
        with self._lock, self._db() as db:
            db.execute("UPDATE deliveries SET labels = ?, data = ? WHERE id = ?", (json.dumps(d["labels"], sort_keys=True), json.dumps(d), int(i)))
        return d

    def delete(self, i):
        with self._lock, self._db() as db:
            db.execute("DELETE FROM deliveries WHERE id = ?", (int(i),))

    def calibration(self):
        return calibrate(self.all())

    def save_report(self, kind, text, data):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = os.path.join(self.folder, "reports", "%s-%s-%s" % (stamp, kind, hashlib.sha256(text.encode()).hexdigest()[:8]))
        with open(base + ".md", "w", encoding="utf-8") as f:
            f.write(text)
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, default=str)
        return os.path.basename(base)

    def reports(self):
        d = os.path.join(self.folder, "reports")
        return sorted((f[:-3] for f in os.listdir(d) if f.endswith(".md")), reverse=True)

    def report(self, name, ext="md"):
        name = os.path.basename(str(name))
        p = os.path.join(self.folder, "reports", name + "." + ("json" if ext == "json" else "md"))
        with open(p, encoding="utf-8") as f:
            return f.read()


# ------------------------------------------------------------------------------------------------ self-test
def synthetic_frames(script_visemes, fps=30, shut=False, seed=1):
    """a made-up talking face: aperture and jaw follow the visemes (shut=True: the lips barely move — the 1.49 failure)"""
    import random
    rnd = random.Random(seed)
    frames, t = [], 0.0
    for v, dur in script_visemes:
        pr = PRIORS[v]
        for _ in range(max(1, int(dur * fps))):
            a = 0.03 if shut else max(0.0, rnd.gauss(pr["A"][0], pr["A"][1] * 0.15))
            r = 0.05 if shut else max(0.0, rnd.gauss(pr["R"][0], pr["R"][1] * 0.15))
            j = 0.03 if shut else max(0.0, rnd.gauss(pr["J"][0], pr["J"][1] * 0.15))
            w = max(0.0, rnd.gauss(pr["W"][0], pr["W"][1] * 0.15))
            frames.append({"t": round(t, 4), "face": True, "gap": round(a, 4), "pose": [rnd.gauss(0, 2), rnd.gauss(0, 2), rnd.gauss(0, 1)],
                           "bs": {"jawOpen": j, "mouthPucker": r, "mouthFunnel": r * 0.8, "mouthStretchLeft": w, "mouthStretchRight": w,
                                  "mouthClose": 0.4 if v == "PP" else 0.02, "browInnerUp": 0.1, "eyeBlinkLeft": 0.9 if rnd.random() < 0.01 else 0.05,
                                  "eyeBlinkRight": 0.9 if rnd.random() < 0.01 else 0.05}})
            t += 1.0 / fps
    k = math.exp(-1.0 / (fps * 0.05))             # lips are muscles: a first-order lag (~50 ms), as a real mouth moves
    prev = None
    for f in frames:
        if prev is not None:
            f["gap"] = round(prev["gap"] * k + f["gap"] * (1 - k), 4)
            for c in ("jawOpen", "mouthPucker", "mouthFunnel", "mouthStretchLeft", "mouthStretchRight", "mouthClose"):
                f["bs"][c] = prev["bs"][c] * k + f["bs"][c] * (1 - k)
        prev = f
    return frames


def self_test():
    out = []
    ok = lambda n, c, d="": out.append((n, bool(c), d))
    import visemes as _vz
    real_wp = _vz.word_phonemes
    plan = [("PP", 0.10), ("aa", 0.25), ("PP", 0.10), ("aa", 0.25), ("sil", 0.2)]
    papa = lambda words, lang="en", lab=None: [{"ipa": "papa", "phonemes": [("p", "PP", 1), ("a", "aa", 2.5), ("p", "PP", 1), ("a", "aa", 2.5)]} for _ in words]
    W = [{"word": "papa", "start": 0.0, "end": 0.7, "source": "test"}]
    I = {"sync_ms": 20, "capture_quality": 90}
    cal = {"en": {v: {f: {"mean": PRIORS[v][f][0], "sd": PRIORS[v][f][1], "n": 40} for f in PRIORS[v]["_w"]} for v in PRIORS}}
    _vz.word_phonemes = papa
    try:
        good = measure(synthetic_frames(plan), W, inputs=I)
        bad = measure(synthetic_frames(plan, shut=True), W, inputs=I)
        again = measure(synthetic_frames(plan), W, inputs=I)
        bad_c = measure(synthetic_frames(plan, shut=True), W, inputs=I, calibration=cal)
    finally:
        _vz.word_phonemes = real_wp
    ok("a face that moves as expected conforms (AC ≥ 70) and passes", good["scores"]["AC"] >= 70 and good["verdict"]["result"] == "PASS", good["scores"])
    ok("lips that stay shut on open vowels fail, and the report says why (the 1.49 avatar failure)",
       bad["verdict"]["result"] == "FAIL" and "naturalness" in bad["verdict"]["failed"] and "conformance" in bad["verdict"]["exploratory_flags"]
       and any("aperture too small" in w for w in bad["verdict"]["why"]) and any("beyond human limits" in w for w in bad["verdict"]["why"]), bad["verdict"])
    ok("with calibrated expectations, conformance is judged (and fails here)", "conformance" in bad_c["verdict"]["failed"] and bad_c["expectation_basis"] == ["calibrated"],
       (bad_c["verdict"]["failed"], bad_c["expectation_basis"]))
    ok("the human-limit check names frozen / shut lips", any(c["check"] in ("frozen", "shut_vowels") and not c["passed"] for c in bad["human_limits"]))
    strip = lambda d: {k: v for k, v in d.items() if k != "at"}
    ok("deterministic: the same inputs give the same numbers and fingerprint", strip(again) == strip(good))
    rep = report_delivery(bad)
    ok("the delivery report has the result, criteria, words, methods and limitations",
       all(s in rep for s in ("# Delivery report — FAIL", "| criterion |", "## Words", "## Methods", "## Limitations")))
    ok("Welch t-test matches a known value (t = −2, df = 8, p = 0.0805)", abs(welch([1, 2, 3, 4, 5], [3, 4, 5, 6, 7])["p"] - 0.0805) < 0.001)
    ok("t critical value for df = 10 is 2.228", abs(t_crit(10) - 2.228) < 0.002, t_crit(10))
    ok("Holm–Bonferroni adjusts in order", holm([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06], holm([0.01, 0.04, 0.03]))
    ok("exact binomial tail", abs(binom_sf(8, 10, 0.5) - 0.0546875) < 1e-9)
    import random
    rnd = random.Random(7)

    def fake(em, a):
        fm = {k: 0.1 for k in FACTORS}
        fm["A"] = rnd.gauss(a, 0.02)
        return {"labels": {"emotion": em}, "lang": "en", "factor_means": fm, "dynamics": {"Va": 1, "Jk": 1, "Bl": 15, "Hm": 5, "Mv": 0.1},
                "scores": {"AC": 80}, "words": [], "verdict": {"result": "PASS"}}
    ds = [fake("neutral", 0.20) for _ in range(8)] + [fake("joy", 0.30) for _ in range(8)] + [fake("anger", 0.21) for _ in range(3)]
    c = compare(ds, "emotion", "neutral")
    joy = next(k for k in c["contrasts"] if k["group"] == "joy")
    ang = next(k for k in c["contrasts"] if k["group"] == "anger")
    a_row = next(r for r in joy["factors"] if r["factor"] == "A")
    ok("a real difference between groups is found (aperture, Holm-corrected) with a large effect", a_row["significant"] and a_row["g"] > 2, a_row)
    ok("a group with too few clips is reported but not interpreted", not ang["enough_data"])
    ok("the leave-one-clip-out check says whether the groups differ at all", c["validation"]["done"] and c["validation"]["accuracy"] > c["validation"]["chance"], c["validation"])
    ok("the comparison report states units, contrasts and the validation", all(s in report_compare(c) for s in ("clip-level means", "Hedges' g", "Is the difference real?")))
    return out


if __name__ == "__main__":
    res = self_test()
    for n, g, d in res:
        print(("  [OK]   " if g else "  [FAIL] ") + n + ("" if g else "  — %s" % (d,)))
    print("\n  %d of %d checks passed" % (sum(1 for x in res if x[1]), len(res)))
