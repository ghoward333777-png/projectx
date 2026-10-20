"""Speech measurement and voice effects — standard-library Python, deterministic.

measure(wav_bytes)  →  what a recording actually contains, with the method behind every number:
    volume (dBFS: mean, peak, range, variation), pauses (where, how long), speaking and
    articulation rate (syllable nuclei per second), pitch (F0 mean / range / contour → tone and
    intonation), jitter and shimmer (cycle-to-cycle instability), harmonics-to-noise ratio
    (hoarseness), tremor (4–12 Hz modulation of pitch and loudness → tremble), breathiness,
    and rule-based emotion / voice-age / voice-condition INDICATORS. Indicators are acoustic
    estimates with their reasons, not diagnoses and not identification.

apply_effects(wav_bytes, fx)  →  the same voice with tremble (vibrato + tremolo), hoarseness
    (aspiration noise + period jitter), breathiness, ageing, volume and added pauses. Seeded,
    so the same input and settings always give the same audio.

Reference ranges (normal adult voice, MDVP-style norms): jitter < 1.04 %, shimmer < 3.81 %,
HNR > 20 dB. Measured here from 20 ms frames (RAP-style 3-point perturbation), so the
values are comparable in kind, not identical to a clinical analyser.
"""
import array, io, math, operator, random, struct, wave

AN_RATE = 8000          # analysis sample rate
FRAME_S = 0.040         # analysis window
HOP_S = 0.020           # analysis step (50 frames per second)
MAX_ANALYSE_S = 30.0
F0_MIN, F0_MAX = 60.0, 400.0


# ---------------------------------------------------------------------- WAV in / out
def read_wav(data):
    """→ (samples as floats -1..1, mono, sample_rate). PCM 8/16/24/32-bit WAV only."""
    with wave.open(io.BytesIO(data), "rb") as w:
        ch, width, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width == 2:
        a = array.array("h"); a.frombytes(raw[:len(raw) // 2 * 2]); scale = 32768.0
    elif width == 1:
        a = array.array("h", [(b - 128) << 8 for b in raw]); scale = 32768.0
    elif width == 4:
        a = array.array("i"); a.frombytes(raw[:len(raw) // 4 * 4]); scale = 2147483648.0
    elif width == 3:
        a = array.array("i", [int.from_bytes(raw[i:i + 3], "little", signed=True) for i in range(0, len(raw) - 2, 3)]); scale = 8388608.0
    else:
        raise ValueError("unsupported WAV sample width %d" % width)
    if ch > 1:
        x = [sum(a[i:i + ch]) / (ch * scale) for i in range(0, len(a) - ch + 1, ch)]
    else:
        x = [v / scale for v in a]
    return x, sr


def write_wav(x, sr):
    out = array.array("h", [int(max(-32767, min(32767, v * 32767))) for v in x])
    if out.itemsize != 2:
        raise RuntimeError("unexpected array item size")
    import sys
    if sys.byteorder == "big":
        out.byteswap()
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(out.tobytes())
    return bio.getvalue()


def pcm16_to_wav(pcm, sr=24000):
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm[:len(pcm) // 2 * 2])
    return bio.getvalue()


def is_wav(data):
    return isinstance(data, (bytes, bytearray)) and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def _downsample(x, sr, target=AN_RATE):
    """Windowed-sinc low-pass (31 taps, cut-off just under the new Nyquist), then decimate."""
    k = max(1, int(round(sr / target)))
    if k == 1:
        return x, sr
    M = 31
    fc = 0.45 / k
    h = []
    for i in range(M):
        m = i - (M - 1) / 2.0
        v = 2 * fc if m == 0 else math.sin(2 * math.pi * fc * m) / (math.pi * m)
        h.append(v * (0.54 - 0.46 * math.cos(2 * math.pi * i / (M - 1))))
    g = sum(h)
    h = [v / g for v in h]
    pad = [0.0] * (M // 2)
    xp = pad + list(x) + pad
    out = [sum(map(operator.mul, h, xp[i:i + M])) for i in range(0, len(x), k)]
    return out, sr / k


def _db(v):
    return 20 * math.log10(v) if v > 1e-9 else -120.0


def _pct(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    i = min(len(s) - 1, max(0, int(round(p / 100.0 * (len(s) - 1)))))
    return s[i]


def _mean(v):
    return sum(v) / len(v) if v else 0.0


def _std(v):
    if len(v) < 2:
        return 0.0
    m = _mean(v)
    return math.sqrt(sum((a - m) ** 2 for a in v) / (len(v) - 1))


def _semitones(a, b):
    return 12 * math.log2(a / b) if a > 0 and b > 0 else 0.0


# ---------------------------------------------------------------------- measurement
def measure(data, timer=None, max_s=None):
    """Measure a WAV recording. `timer(stage)` is called at each stage so the caller can time it.
    max_s: how much of the recording to analyse (default MAX_ANALYSE_S; lip sync passes the whole length)."""
    t = timer or (lambda s: None)
    t("decode")
    x, sr = read_wav(data)
    dur_total = len(x) / float(sr) if sr else 0.0
    x = x[:int((max_s or MAX_ANALYSE_S) * sr)]
    t("resample")
    y, fs = _downsample(x, sr)
    fs = float(fs)
    # remove DC
    m = _mean(y)
    y = [v - m for v in y]
    N, H = int(FRAME_S * fs), int(HOP_S * fs)
    nfr = max(0, (len(y) - N) // H + 1)
    t("volume")
    rms, peak, zcr = [], [], []
    for i in range(nfr):
        f = y[i * H:i * H + N]
        e = sum(map(operator.mul, f, f)) / N
        rms.append(math.sqrt(e))
        peak.append(max(abs(min(f)), abs(max(f))))
        zcr.append(sum(1 for j in range(1, N) if (f[j - 1] >= 0) != (f[j] >= 0)) / float(N))
    db = [_db(r) for r in rms]
    floor = _pct(db, 10)
    thr = max(-55.0, min(floor + 9.0, _pct(db, 90) - 12.0))   # adapts to steady sound as well as to quiet rooms
    speech = [d > thr for d in db]
    # close tiny gaps (< 60 ms) and drop blips (< 40 ms)
    speech = _smooth_mask(speech, 3, 2)
    t("pitch")
    lag_min, lag_max = int(fs / F0_MAX), int(fs / F0_MIN)
    f0 = [0.0] * nfr
    rmax = [0.0] * nfr
    for i in range(nfr):
        if not speech[i]:
            continue
        f = y[i * H:i * H + N]
        e0 = sum(map(operator.mul, f, f))
        if e0 <= 1e-12:
            continue
        n = len(f)
        rs = {}
        for lag in range(lag_min, min(lag_max, n - 1) + 1):
            a, b = f[:n - lag], f[lag:]
            den = math.sqrt(sum(map(operator.mul, a, a)) * sum(map(operator.mul, b, b))) or 1e-12
            rs[lag] = sum(map(operator.mul, a, b)) / den
        best = max(rs.values()) if rs else 0.0
        bl = 0
        # the shortest lag that is a local peak within 10 % of the best (avoids octave-low errors)
        for lag in sorted(rs):
            if rs[lag] >= 0.9 * best and rs[lag] >= rs.get(lag - 1, -1) and rs[lag] >= rs.get(lag + 1, -1):
                bl, best = lag, rs[lag]
                break
        if best > 0.45 and bl:
            # parabolic refinement
            def rr(L):
                a, b = f[:n - L], f[L:]
                return sum(map(operator.mul, a, b)) / (math.sqrt(sum(map(operator.mul, a, a)) * sum(map(operator.mul, b, b))) or 1e-12)
            if lag_min < bl < lag_max:
                r1, r2, r3 = rr(bl - 1), best, rr(bl + 1)
                d = (r1 - r3) / (2 * (r1 - 2 * r2 + r3)) if (r1 - 2 * r2 + r3) else 0.0
                lag_f = bl + max(-0.5, min(0.5, d))
            else:
                lag_f = bl
            f0[i] = fs / lag_f
            rmax[i] = min(0.999, best)
    # octave-jump cleanup against the running median
    voiced = [i for i in range(nfr) if f0[i] > 0]
    if voiced:
        med = _pct([f0[i] for i in voiced], 50)
        for i in voiced:
            if f0[i] > 1.8 * med:
                f0[i] /= 2.0
            elif f0[i] < 0.55 * med:
                f0[i] *= 2.0
    t("pauses")
    hop = HOP_S
    pauses, segs = [], []
    first = next((i for i, s in enumerate(speech) if s), None)
    last = (nfr - 1 - next((i for i, s in enumerate(reversed(speech)) if s), 0)) if first is not None else None
    if first is not None:
        i = first
        while i <= last:
            if speech[i]:
                j = i
                while j <= last and speech[j]:
                    j += 1
                segs.append((i, j))
                i = j
            else:
                j = i
                while j <= last and not speech[j]:
                    j += 1
                if (j - i) * hop >= 0.20:
                    pauses.append({"at_s": round(i * hop, 2), "seconds": round((j - i) * hop, 2)})
                i = j
    speak_s = sum(e - s for s, e in segs) * hop
    span_s = ((last - first + 1) * hop) if first is not None else 0.0
    pause_s = sum(p["seconds"] for p in pauses)
    t("rate")
    # syllable nuclei: intensity peaks inside speech, ≥ 2 dB above both neighbouring dips, ≥ 100 ms apart
    sm = _movavg(db, 3)
    nuclei = []
    for i in range(1, nfr - 1):
        if speech[i] and sm[i] >= sm[i - 1] and sm[i] > sm[i + 1] and sm[i] > thr + 4:
            lo_l = min(sm[max(0, i - 8):i] or [sm[i]])
            lo_r = min(sm[i + 1:i + 9] or [sm[i]])
            if sm[i] - lo_l >= 2.0 and sm[i] - lo_r >= 2.0 and (not nuclei or (i - nuclei[-1]) * hop >= 0.10):
                nuclei.append(i)
    t("voice quality")
    vf = [f0[i] for i in voiced]
    cyc = _cycles(y, fs, f0, H, N, voiced)
    jitter, shimmer, ncyc = cyc["jitter"], cyc["shimmer"], cyc["cycles"]
    hnr = []
    for i in voiced:                              # pitch-synchronous: 3 periods compared with the next 3
        T = int(round(fs / f0[i]))
        c = i * H + N // 2
        a, b = y[c - int(1.5 * T):c + int(1.5 * T)], y[c - int(1.5 * T) + T:c + int(1.5 * T) + T]
        if c - int(1.5 * T) < 0 or len(b) < len(a) or not a:
            continue
        den = math.sqrt(sum(map(operator.mul, a, a)) * sum(map(operator.mul, b, b))) or 1e-12
        r = sum(map(operator.mul, a, b)) / den
        if 0 < r < 1:
            hnr.append(10 * math.log10(r / (1 - r)))
    hnr_db = _pct(hnr, 50) if hnr else 0.0
    t("tremor")
    trem_f0 = _tremor([f0[i] for i in range(nfr)], voiced, fs_c=1 / hop, rel=True)
    trem_amp = _tremor(rms, voiced, fs_c=1 / hop, rel=True)
    t("indicators")
    sp_db = [db[i] for i in range(nfr) if speech[i]]
    vol = {"mean_dbfs": round(_mean(sp_db), 1), "peak_dbfs": round(_db(max(peak) if peak else 0), 1),
           "range_db": round(_pct(sp_db, 95) - _pct(sp_db, 10), 1), "variation_db": round(_std(sp_db), 1),
           "noise_floor_dbfs": round(floor, 1)}
    pitch = {}
    if vf:
        mean_f0 = _mean(vf)
        lo, hi = _pct(vf, 5), _pct(vf, 95)
        tail = [f0[i] for i in voiced if i >= voiced[0] + 0.7 * (voiced[-1] - voiced[0])]
        head = [f0[i] for i in voiced if i <= voiced[0] + 0.5 * (voiced[-1] - voiced[0])]
        slope = _semitones(_mean(tail), _mean(head)) if tail and head else 0.0
        pitch = {"mean_hz": round(mean_f0, 1), "median_hz": round(_pct(vf, 50), 1), "low_hz": round(lo, 1), "high_hz": round(hi, 1),
                 "range_semitones": round(_semitones(hi, lo), 1), "variation_semitones": round(_std([_semitones(v, mean_f0) for v in vf]), 2),
                 "end_slope_semitones": round(slope, 1),
                 "intonation": "rising (question-like)" if slope > 1.5 else "falling (statement-like)" if slope < -1.5 else "level",
                 "register": "low" if mean_f0 < 120 else "middle" if mean_f0 < 200 else "high",
                 "expressiveness": "monotone" if _semitones(hi, lo) < 4 else "expressive" if _semitones(hi, lo) > 10 else "normal"}
    voiced_ratio = len(voiced) / float(max(1, sum(speech)))
    zc_v = _mean([zcr[i] for i in voiced])
    breath = max(0.0, min(1.0, (15.0 - hnr_db) / 15.0 * 0.6 + max(0.0, zc_v - 0.08) * 4)) if voiced else 0.0
    rate = {"syllables": len(nuclei), "speaking_rate_syl_s": round(len(nuclei) / span_s, 2) if span_s else 0.0,
            "articulation_rate_syl_s": round(len(nuclei) / speak_s, 2) if speak_s else 0.0}
    runs = _runs(voiced)
    longest = max((b - a for a, b in runs), default=0) * hop
    quality = {"jitter_pct": round(100 * jitter, 2), "shimmer_pct": round(100 * shimmer, 2), "hnr_db": round(hnr_db, 1),
               "cycles_measured": ncyc, "longest_voiced_s": round(longest, 2),
               "reliability": "good (sustained voicing)" if longest >= 1.0 else "approximate (connected speech — record a sustained vowel for a voice-condition test)",
               "voiced_ratio": round(voiced_ratio, 2), "breathiness": round(breath, 2),
               "tremor_pitch": trem_f0, "tremor_loudness": trem_amp}
    res = {"duration_s": round(dur_total, 2), "analysed_s": round(len(x) / float(sr), 2), "sample_rate": sr,
           "speech_s": round(speak_s, 2), "span_s": round(span_s, 2),
           "volume": vol, "pauses": {"count": len(pauses), "total_s": round(pause_s, 2),
                                     "mean_s": round(pause_s / len(pauses), 2) if pauses else 0.0,
                                     "pause_ratio": round(pause_s / span_s, 2) if span_s else 0.0, "list": pauses[:60]},
           "rate": rate, "pitch": pitch, "quality": quality,
           "contour": {"hop_s": hop, "f0_hz": [round(v, 1) for v in f0], "db": [round(v, 1) for v in db], "nuclei": nuclei},
           "segments": [{"from_s": round(s * hop, 2), "to_s": round(e * hop, 2)} for s, e in segs][:200]}
    t("vocal mode")
    # bursts = voiced stretches; their rhythm separates sobbing, laughing, singing and speech
    vruns = _runs(voiced)
    onsets = [a * hop for a, b in vruns]
    lens = [(b - a) * hop for a, b in vruns]
    gaps_ = [o2 - o1 for o1, o2 in zip(onsets, onsets[1:])]
    sp_idx = [i for i in range(nfr) if speech[i]]
    unv = [i for i in sp_idx if f0[i] == 0]
    res["vocal"] = {"voiced_ratio": round(voiced_ratio, 2), "zcr_speech": round(_mean([zcr[i] for i in sp_idx]), 3),
                    "zcr_unvoiced": round(_mean([zcr[i] for i in unv]), 3), "zcr_voiced": round(zc_v, 3),
                    "bursts": len(vruns), "burst_rate_hz": round(len(vruns) / span_s, 2) if span_s else 0.0,
                    "burst_mean_s": round(_mean(lens), 2), "burst_regularity_cv": round(_std(gaps_) / _mean(gaps_), 2) if len(gaps_) > 2 and _mean(gaps_) else None,
                    "pitch_within_burst_st": round(_mean([_std([_semitones(f0[i], _mean([f0[j] for j in range(a, b)])) for i in range(a, b)]) for a, b in vruns if b - a >= 5]), 2) if vruns else 0.0,
                    "level_above_floor_db": round(_mean(sp_db) - floor, 1) if sp_db else 0.0}
    res["indicators"] = indicators(res)
    res["vocal_mode"] = vocal_mode(res)
    return res


def vocal_mode(r):
    """Which way of using the voice this is — whispering, crying, laughing, shouting, singing or speaking —
    scored 0–100 from acoustic patterns, with the reasons. Patterns, not certainty: crying and laughing can
    resemble each other, and context decides close calls."""
    v, q, p, vol, ps = r["vocal"], r["quality"], r["pitch"], r["volume"], r["pauses"]
    if r["speech_s"] < 0.3:
        return {"label": "silence / no voice", "scores": [], "note": "less than 0.3 s of sound above the room noise"}
    sc = {}

    def add(mode, pts, why):
        s_, w_ = sc.setdefault(mode, [0, []])
        sc[mode][0] = s_ + pts
        w_.append(why)
    # whispering: sound without voicing — noise-like (many zero crossings), almost no pitch
    if v["voiced_ratio"] < 0.35:
        add("whispering", 45, "only %.0f%% of the sound is voiced (speech is normally > 60%%)" % (100 * v["voiced_ratio"]))
    if v["zcr_speech"] > 0.26:
        add("whispering", 25, "noise-like sound (zero-crossing rate %.2f)" % v["zcr_speech"])
    if vol["mean_dbfs"] < -28 and v["voiced_ratio"] < 0.5:
        add("whispering", 15, "quiet (%.0f dBFS)" % vol["mean_dbfs"])
    if p:
        # crying: high, unstable pitch; rough voice; voicing broken into sobs with breathy gaps
        if p["mean_hz"] > 300:
            add("crying", 15, "raised pitch (%.0f Hz)" % p["mean_hz"])
        if q["jitter_pct"] > 2.0 and q["hnr_db"] < 10:
            add("crying", 15, "irregular, rough voicing (jitter %.1f %%, HNR %.0f dB)" % (q["jitter_pct"], q["hnr_db"]))
        if q["tremor_pitch"].get("detected") or (0.5 <= v["pitch_within_burst_st"] and p["mean_hz"] > 300 and v["burst_mean_s"] >= 0.3):
            add("crying", 20, "quavering pitch inside long voiced bursts (%.1f st)" % v["pitch_within_burst_st"])
        sob = 0.4 <= v["burst_rate_hz"] <= 2.0 and v["burst_mean_s"] >= 0.3 and v["burst_mean_s"] < 0.9 and (v["burst_regularity_cv"] or 1) < 0.5
        if sob:
            add("crying", 25, "voicing comes in sobs (%.1f per second, %.2f s each)" % (v["burst_rate_hz"], v["burst_mean_s"]))
        if sob and v["zcr_unvoiced"] > 0.15:
            add("crying", 15, "breathy inhalations between sobs")
        if ps["count"] >= 2 and ps["pause_ratio"] > 0.2:
            add("crying", 10, "frequent catches / pauses (%.0f%% of the time)" % (100 * ps["pause_ratio"]))
        # laughing: short, regular voiced bursts at 3–7 per second, aspirated in between
        regular = v["burst_regularity_cv"] is not None and v["burst_regularity_cv"] < 0.3 and v["bursts"] >= 4
        if 3.0 <= v["burst_rate_hz"] <= 8 and v["burst_mean_s"] < 0.2:
            add("laughing", 20 + (35 if regular else 0), "short voiced bursts at %.1f per second%s" % (v["burst_rate_hz"], ", evenly spaced (variation %.2f)" % v["burst_regularity_cv"] if regular else ""))
        if regular and v["pitch_within_burst_st"] < 0.8 and v["burst_mean_s"] < 0.2:
            add("laughing", 15, "every burst has the same steady pitch ('ha-ha-ha')")
        if regular and v["zcr_unvoiced"] > 0.2 and v["burst_mean_s"] < 0.2:
            add("laughing", 10, "aspirated 'h' between bursts")
        # shouting: loud, high, strained
        loud = vol["mean_dbfs"] > -14
        strained = p["mean_hz"] > 260 or (v["zcr_voiced"] > 0.12 and vol["mean_dbfs"] > -14)
        if loud and strained:
            add("shouting", 45, "loud (%.0f dBFS) with a raised, strained voice (%.0f Hz)" % (vol["mean_dbfs"], p["mean_hz"]))
        elif loud:
            add("shouting", 15, "loud (%.0f dBFS) — loudness alone also depends on the microphone" % vol["mean_dbfs"])
        if loud and v["level_above_floor_db"] > 45:
            add("shouting", 15, "%.0f dB above the room noise" % v["level_above_floor_db"])
        # singing: long, steady notes
        if v["burst_mean_s"] > 0.6 and v["voiced_ratio"] > 0.75:
            add("singing", 35, "long voiced stretches (%.1f s on average)" % v["burst_mean_s"])
        if v["pitch_within_burst_st"] < 0.6 and v["burst_mean_s"] > 0.4:
            add("singing", 30, "steady pitch within each stretch (%.2f st)" % v["pitch_within_burst_st"])
        # speaking: the ordinary pattern
        if 0.55 <= v["voiced_ratio"] <= 0.95:
            add("speaking", 30, "normal share of voiced sound (%.0f%%)" % (100 * v["voiced_ratio"]))
        if 3.0 <= r["rate"]["articulation_rate_syl_s"] <= 7.0:
            add("speaking", 30, "normal syllable rate (%.1f per second)" % r["rate"]["articulation_rate_syl_s"])
        if 0.15 <= v["burst_mean_s"] <= 0.6:
            add("speaking", 15, "word-length voiced stretches (%.2f s)" % v["burst_mean_s"])
    ranked = sorted(([m, min(100, s_), w] for m, (s_, w) in sc.items()), key=lambda x: -x[1])
    top = ranked[0] if ranked else ["speaking", 0, []]
    second = ranked[1][1] if len(ranked) > 1 else 0
    conf = "clear" if top[1] - second >= 25 else "likely" if top[1] - second >= 10 else "uncertain"
    return {"label": top[0], "confidence": conf, "scores": [{"mode": m, "score": s_, "reasons": w} for m, s_, w in ranked],
            "note": "acoustic patterns only; crying, laughing and shouting can overlap, so close calls are marked uncertain"}


def _smooth_mask(m, close, drop):
    m = list(m)
    n = len(m)
    i = 0
    while i < n:                                  # close short gaps
        if not m[i]:
            j = i
            while j < n and not m[j]:
                j += 1
            if 0 < i and j < n and (j - i) < close:
                for k in range(i, j):
                    m[k] = True
            i = j
        else:
            i += 1
    i = 0
    while i < n:                                  # drop short blips
        if m[i]:
            j = i
            while j < n and m[j]:
                j += 1
            if (j - i) < drop:
                for k in range(i, j):
                    m[k] = False
            i = j
        else:
            i += 1
    return m


def _movavg(v, k):
    out, h = [], k // 2
    for i in range(len(v)):
        s = v[max(0, i - h):i + h + 1]
        out.append(sum(s) / len(s))
    return out


def _runs(idx):
    out, start = [], None
    for k, i in enumerate(idx):
        if start is None:
            start = i
        if k + 1 == len(idx) or idx[k + 1] != i + 1:
            out.append((start, i + 1)); start = None
    return out


def _cycles(y, fs, f0, H, N, voiced):
    """Cycle-to-cycle (local) jitter and shimmer: glottal peaks are picked one period apart inside
    every voiced stretch; consecutive periods and peak heights are compared (as Praat/MDVP do)."""
    dj, ds, tp, ta = [], [], [], []
    for a, b in _runs(voiced):
        if b - a < 3:
            continue
        start, end = a * H, (b - 1) * H + N
        T0 = fs / f0[a]
        seg = y[start:end]
        if len(seg) < 3 * T0:
            continue
        # first peak: the largest sample in the first period
        p = max(range(0, int(T0)), key=lambda j: seg[j])
        marks = [p]
        while True:
            i = min(b - 1, a + int((start + marks[-1]) / H) - a)
            T = fs / f0[i] if f0[i] > 0 else T0
            lo, hi = marks[-1] + int(0.8 * T), marks[-1] + int(1.2 * T) + 1
            if hi >= len(seg) - 1:
                break
            q = max(range(lo, hi), key=lambda j: seg[j])
            marks.append(q)
        # parabolic refinement of each mark
        times, amps = [], []
        for m in marks:
            if 0 < m < len(seg) - 1:
                y1, y2, y3 = seg[m - 1], seg[m], seg[m + 1]
                den = (y1 - 2 * y2 + y3)
                d = 0.5 * (y1 - y3) / den if den else 0.0
                times.append((m + max(-0.5, min(0.5, d))) / fs)
                amps.append(y2 - 0.25 * (y1 - y3) * d)
        per = [t2 - t1 for t1, t2 in zip(times, times[1:])]
        # skip implausible periods (octave slips)
        good = [k for k in range(1, len(per)) if 0.7 < per[k] / per[k - 1] < 1.43]
        for k in good:
            dj.append(abs(per[k] - per[k - 1])); tp.append(per[k])
            if amps[k] > 0 and amps[k + 1] > 0:
                ds.append(abs(amps[k + 1] - amps[k])); ta.append(amps[k + 1])
    jit = (_mean(dj) / _mean(tp)) if dj and tp else 0.0
    shim = (_mean(ds) / _mean(ta)) if ds and ta else 0.0
    return {"jitter": jit, "shimmer": shim, "cycles": len(dj)}


def _rap(vals, idx):
    """Relative average perturbation over consecutive voiced frames (removes slow intonation trends)."""
    num, cnt, tot = 0.0, 0, 0.0
    for k in range(1, len(vals) - 1):
        if idx[k] - idx[k - 1] == 1 and idx[k + 1] - idx[k] == 1:
            num += abs(vals[k] - (vals[k - 1] + vals[k] + vals[k + 1]) / 3.0)
            tot += vals[k]
            cnt += 1
    return (num / cnt) / (tot / cnt) if cnt and tot else 0.0


def _tremor(series, voiced, fs_c, rel=True):
    """Strength of 3–12 Hz modulation in a contour over voiced runs ≥ 0.6 s."""
    runs, cur = [], []
    vs = set(voiced)
    for i in range(len(series)):
        if i in vs:
            cur.append(series[i])
        else:
            if len(cur) * (1 / fs_c) >= 0.6:
                runs.append(cur)
            cur = []
    if len(cur) * (1 / fs_c) >= 0.6:
        runs.append(cur)
    if not runs:
        return {"detected": False, "index": 0.0, "freq_hz": None, "depth_pct": 0.0, "note": "no voiced stretch ≥ 0.6 s"}
    band_e = tot_e = 0.0
    best_f, best_m, depth = None, 0.0, []
    for r in runs:
        m = _mean(r) or 1.0
        trend = _movavg(r, max(3, int(0.3 * fs_c) | 1))
        d = [(a - b) / m if rel else a - b for a, b in zip(r, trend)]
        n = len(d)
        depth.append(_std(d))
        for kf in range(1, n // 2):
            f = kf * fs_c / n
            re_ = sum(d[j] * math.cos(2 * math.pi * kf * j / n) for j in range(n))
            im = sum(d[j] * math.sin(2 * math.pi * kf * j / n) for j in range(n))
            p = re_ * re_ + im * im
            if f >= 1.0:
                tot_e += p
            if 3.0 <= f <= 12.0:
                band_e += p
                if p > best_m:
                    best_m, best_f = p, f
    idx = band_e / tot_e if tot_e else 0.0
    dp = 100 * _mean(depth) * math.sqrt(2)
    longest = max(len(r) for r in runs) / fs_c
    # a tremor is a regular, sustained oscillation: most of the energy in one 3–12 Hz band, over ≥ 1 s
    return {"detected": idx > 0.6 and dp > 0.8 and longest >= 1.0, "index": round(idx, 2), "freq_hz": round(best_f, 1) if best_f else None,
            "depth_pct": round(dp, 2), "longest_run_s": round(longest, 2)}


def indicators(r):
    """Rule-based readings of the measurements, each with the reasons behind it. Voice-condition
    readings (hoarseness, tremble, voice age) use sustained-vowel norms, so they are only given for
    a sustained vowel (≥ 1 s of continuous voicing); for connected speech the raw numbers are kept
    and the reading says why it is not assessed."""
    q, p, v, rt = r["quality"], r["pitch"], r["volume"], r["rate"]
    out = {}
    sustained = q.get("longest_voiced_s", 0) >= 1.0
    # voice condition (hoarseness)
    reasons, score = [], 0
    if q["hnr_db"] and q["hnr_db"] < 20:
        score += min(40, (20 - q["hnr_db"]) * 4); reasons.append("harmonics-to-noise %.1f dB (normal > 20)" % q["hnr_db"])
    if q["jitter_pct"] > 1.04:
        score += min(30, (q["jitter_pct"] - 1.04) * 15); reasons.append("jitter %.2f %% (normal < 1.04)" % q["jitter_pct"])
    if q["shimmer_pct"] > 3.81:
        score += min(30, (q["shimmer_pct"] - 3.81) * 5); reasons.append("shimmer %.2f %% (normal < 3.81)" % q["shimmer_pct"])
    score = int(min(100, score))
    out["hoarseness"] = {"level": score, "label": "clear" if score < 20 else "slightly hoarse" if score < 50 else "hoarse",
                         "reasons": reasons or ["jitter, shimmer and harmonics-to-noise within normal ranges"]}
    # tremble
    tf, ta = q["tremor_pitch"], q["tremor_loudness"]
    lvl = int(min(100, max(tf.get("depth_pct", 0) * 40 if tf.get("detected") else 0, ta.get("depth_pct", 0) * 4 if ta.get("detected") else 0)))
    out["tremble"] = {"level": lvl, "label": "none" if lvl < 15 else "slight" if lvl < 45 else "marked",
                      "reasons": ["pitch modulation %s Hz, depth %.2f %%, band share %.2f" % (tf.get("freq_hz"), tf.get("depth_pct", 0), tf.get("index", 0)),
                                  "loudness modulation %s Hz, depth %.2f %%" % (ta.get("freq_hz"), ta.get("depth_pct", 0))]}
    # emotion (arousal-led estimate)
    em, why = "neutral", []
    if p:
        hi_ar = (v["mean_dbfs"] > -20) + (p["variation_semitones"] > 3.5) + (rt["articulation_rate_syl_s"] > 5.5) + (p["mean_hz"] > 220)
        lo_ar = (v["mean_dbfs"] < -32) + (p["variation_semitones"] < 1.5) + (0 < rt["articulation_rate_syl_s"] < 3.0)
        why = ["loudness %.1f dBFS" % v["mean_dbfs"], "pitch variation %.1f semitones" % p["variation_semitones"],
               "articulation %.1f syllables/s" % rt["articulation_rate_syl_s"], "mean pitch %.0f Hz" % p["mean_hz"]]
        if hi_ar >= 3 and (out["tremble"]["level"] or 0) >= 45:
            em = "tense / fearful"
        elif hi_ar >= 3 and (out["hoarseness"]["level"] or 0) >= 30:
            em = "angry / forceful"
        elif hi_ar >= 3:
            em = "excited / animated"
        elif hi_ar == 2:
            em = "engaged"
        elif lo_ar >= 2 and r["pauses"]["pause_ratio"] > 0.25:
            em = "sad / subdued"
        elif lo_ar >= 2:
            em = "calm"
    out["emotion"] = {"label": em, "basis": "arousal from loudness, pitch movement and tempo (an estimate, not mind-reading)", "reasons": why}
    if not sustained:
        na = {"level": None, "label": "not assessed (connected speech)",
              "reasons": ["voice-condition norms apply to a sustained vowel — record 'aaah' for 3 seconds",
                          "measured: jitter %.2f %%, shimmer %.2f %%, harmonics-to-noise %.1f dB" % (q["jitter_pct"], q["shimmer_pct"], q["hnr_db"])]}
        out["hoarseness"] = dict(na)
        out["tremble"] = dict(na)
    # voice-age indicators
    reasons, a = [], 0
    if (out["tremble"]["level"] or 0) >= 15:
        a += 30; reasons.append("tremor present")
    if q["hnr_db"] and q["hnr_db"] < 15:
        a += 20; reasons.append("reduced harmonics-to-noise")
    if q["jitter_pct"] > 1.5:
        a += 20; reasons.append("raised jitter")
    if 0 < rt["articulation_rate_syl_s"] < 3.5:
        a += 15; reasons.append("slower articulation")
    if q["breathiness"] > 0.4:
        a += 15; reasons.append("breathy voice")
    a = min(100, a)
    if not sustained:
        out["voice_age"] = {"level": None, "label": "not assessed (connected speech)", "reasons": out["hoarseness"]["reasons"][:1],
                            "basis": "acoustic ageing features, not a person's age"}
    else:
        out["voice_age"] = {"level": a, "label": "youthful / typical adult" if a < 20 else "some ageing features" if a < 55 else "marked ageing features",
                        "reasons": reasons or ["no ageing features measured"], "basis": "acoustic ageing features, not a person's age"}
    out["articulation"] = {"rate_syl_s": rt["articulation_rate_syl_s"],
                           "label": "slow / deliberate" if 0 < rt["articulation_rate_syl_s"] < 3.5 else "fast" if rt["articulation_rate_syl_s"] > 6 else "normal",
                           "pause_ratio": r["pauses"]["pause_ratio"]}
    out["tone"] = {"label": (p.get("register", "") + " register, " + p.get("expressiveness", "") + ", " + p.get("intonation", "")) if p else "no voiced speech found"}
    out["volume"] = {"label": "quiet" if v["mean_dbfs"] < -35 else "loud" if v["mean_dbfs"] > -15 else "normal", "mean_dbfs": v["mean_dbfs"]}
    return out


# ---------------------------------------------------------------------- effects for generated speech
FX_DEFAULT = {"volume_db": 0.0, "tremble": 0.0, "tremble_hz": 5.5, "hoarse": 0.0, "breath": 0.0, "age": 0.0, "pause_scale": 1.0,
              "pitch_st": 0.0, "tempo": 1.0}


def wsola(x, sr, stretch):
    """Change duration by `stretch` (2.0 = twice as long) without changing pitch: waveform-similarity
    overlap-add — each 30 ms frame is placed where it best continues the previous one."""
    if abs(stretch - 1.0) < 0.005 or len(x) < sr // 10:
        return list(x)
    N = int(0.030 * sr); Ho = N // 2; Hi = Ho / stretch; tol = int(0.010 * sr)
    win = [0.5 - 0.5 * math.cos(2 * math.pi * i / N) for i in range(N)]
    n_out = int(len(x) * stretch)
    y = [0.0] * (n_out + N)
    prev = 0
    k = 0
    while True:
        o = k * Ho
        nominal = int(k * Hi)
        if o >= n_out or nominal + N + tol >= len(x):
            break
        if k == 0:
            best = 0
        else:
            ref = x[prev + Ho:prev + Ho + N:4]            # the natural continuation of the last frame
            best, bv = nominal, -1e18
            lo, hi = max(0, nominal - tol), min(len(x) - N - 1, nominal + tol)
            for cand in range(lo, hi + 1, 2):
                v = sum(map(operator.mul, ref, x[cand:cand + N:4]))
                if v > bv:
                    bv, best = v, cand
        seg = x[best:best + N]
        for i in range(len(seg)):
            y[o + i] += seg[i] * win[i]
        prev = best
        k += 1
    return y[:n_out]


def resample(x, factor):
    """Linear-interpolation resampling: output length = len(x) / factor."""
    n = int(len(x) / factor)
    out = []
    for i in range(n):
        pos = i * factor
        j = int(pos); f = pos - j
        a = x[j] if j < len(x) else 0.0
        b = x[j + 1] if j + 1 < len(x) else a
        out.append(a + (b - a) * f)
    return out


def pitch_tempo(x, sr, semitones=0.0, tempo=1.0):
    """Shift pitch by `semitones` and change speed by `tempo` (1.2 = 20 % faster), independently."""
    k = 2 ** (semitones / 12.0)
    y = wsola(x, sr, k / tempo)          # length × k/tempo, same pitch
    return resample(y, k) if abs(k - 1) > 1e-3 else y


def apply_effects(data, fx, timer=None):
    """Apply voice-condition effects to WAV bytes; returns (wav_bytes, report). 0 = off, 1 = strongest."""
    t = timer or (lambda s: None)
    f = dict(FX_DEFAULT); f.update({k: float(v) for k, v in (fx or {}).items() if k in FX_DEFAULT and v is not None})
    if all(f[k] == FX_DEFAULT[k] for k in FX_DEFAULT):
        return data, {"applied": []}
    t("decode for effects")
    x, sr = read_wav(data)
    rnd = random.Random(1913)
    applied = []
    if abs(f["pitch_st"]) >= 0.05 or abs(f["tempo"] - 1.0) >= 0.005:
        t("pitch / speed")
        x = pitch_tempo(x, sr, max(-12, min(12, f["pitch_st"])), max(0.4, min(2.5, f["tempo"])))
        if abs(f["pitch_st"]) >= 0.05:
            applied.append("pitch %+.1f semitones" % f["pitch_st"])
        if abs(f["tempo"] - 1.0) >= 0.005:
            applied.append("speed ×%.2f" % f["tempo"])
    age = max(0.0, min(1.0, f["age"]))
    trem = max(0.0, min(1.0, f["tremble"] + 0.6 * age))
    hoarse = max(0.0, min(1.0, f["hoarse"] + 0.4 * age))
    breath = max(0.0, min(1.0, f["breath"] + 0.3 * age))
    if f["pause_scale"] != 1.0:
        t("pauses")
        x = _scale_pauses(x, sr, max(0.25, min(4.0, f["pause_scale"])))
        applied.append("pauses ×%.2f" % f["pause_scale"])
    env = _envelope(x, sr)
    if trem > 0:
        t("tremble")
        hz = max(2.0, min(12.0, f["tremble_hz"] - 1.0 * age))
        depth_s = trem * 0.0009                      # vibrato: up to ~±0.9 ms delay swing ≈ ±1 semitone at 5 Hz
        am = trem * 0.35                             # tremolo depth
        y, D0 = [], 0.002
        for n in range(len(x)):
            ph = 2 * math.pi * hz * n / sr
            d = (D0 + depth_s * math.sin(ph)) * sr
            pos = n - d
            i0 = int(math.floor(pos)); fr = pos - i0
            a = x[i0] if 0 <= i0 < len(x) else 0.0
            b = x[i0 + 1] if 0 <= i0 + 1 < len(x) else 0.0
            y.append((a + (b - a) * fr) * (1 - am * (0.5 + 0.5 * math.sin(ph + 0.7))))
        x = y
        applied.append("tremble %.0f%% at %.1f Hz" % (100 * trem, hz))
    if hoarse > 0:
        t("hoarseness")
        # period jitter (random-walk micro-delays) + rough noise following the voice envelope
        y, walk = [], 0.0
        for n in range(len(x)):
            walk = 0.995 * walk + rnd.uniform(-1, 1) * 0.02
            pos = n - (0.0015 + hoarse * 0.0004 * walk) * sr
            i0 = int(math.floor(pos)); fr = pos - i0
            a = x[i0] if 0 <= i0 < len(x) else 0.0
            b = x[i0 + 1] if 0 <= i0 + 1 < len(x) else 0.0
            y.append(a + (b - a) * fr + hoarse * 0.35 * env[n] * rnd.uniform(-1, 1))
        x = y
        applied.append("hoarseness %.0f%%" % (100 * hoarse))
    if breath > 0:
        t("breathiness")
        lp = 0.0
        y = []
        for n in range(len(x)):
            lp = 0.6 * lp + 0.4 * rnd.uniform(-1, 1)          # softer aspiration noise
            y.append(x[n] * (1 - 0.3 * breath) + breath * 0.45 * env[n] * lp)
        x = y
        applied.append("breathiness %.0f%%" % (100 * breath))
    if age > 0:
        applied.append("ageing %.0f%% (adds tremble, hoarseness and breath; slower, lower voice on the engine side)" % (100 * age))
    t("volume")
    peak = max((abs(v) for v in x), default=1.0) or 1.0
    gain = 10 ** (f["volume_db"] / 20.0)
    k = min(gain * 0.89 / peak if peak > 0.89 else gain, 0.99 / peak)
    x = [v * k for v in x]
    if f["volume_db"]:
        applied.append("volume %+.1f dB" % f["volume_db"])
    t("encode")
    return write_wav(x, sr), {"applied": applied, "settings": f}


def _envelope(x, sr):
    a = math.exp(-1.0 / (0.01 * sr))
    e, out = 0.0, []
    for v in x:
        e = max(abs(v), a * e)
        out.append(e)
    return out


def _scale_pauses(x, sr, k):
    """Lengthen or shorten silent stretches (≥ 120 ms) by factor k."""
    w = int(0.01 * sr)
    if w <= 0:
        return x
    loud = [max(abs(v) for v in x[i:i + w]) > 0.01 for i in range(0, len(x), w)]
    out, i = [], 0
    while i < len(loud):
        if not loud[i]:
            j = i
            while j < len(loud) and not loud[j]:
                j += 1
            seg = x[i * w:j * w]
            if (j - i) * 0.01 >= 0.12:
                n = int(len(seg) * k)
                seg = seg[:n] if k < 1 else seg + [0.0] * (n - len(seg))
            out += seg
            i = j
        else:
            out += x[i * w:(i + 1) * w]
            i += 1
    return out


# ---------------------------------------------------------------------- the prototype's formant voice (offline, any language)
_VOWEL_FORMANTS = {
    'i': (300, 2300, 3000), 'ɪ': (390, 1990, 2550), 'e': (440, 2100, 2800), 'ɛ': (550, 1900, 2550),
    'æ': (660, 1720, 2410), 'a': (750, 1200, 2600), 'ɑ': (750, 1050, 2600), 'ʌ': (640, 1200, 2600),
    'ɔ': (600, 1000, 2600), 'o': (480, 900, 2500), 'ʊ': (420, 1020, 2300), 'u': (320, 800, 2400),
    'ə': (500, 1500, 2500), 'ɐ': (650, 1300, 2500), 'y': (300, 1800, 2400), 'ø': (450, 1600, 2400),
    'œ': (550, 1550, 2400), 'ɨ': (350, 1600, 2600), 'ɯ': (350, 900, 2400), 'ɜ': (580, 1400, 2500),
    'ɒ': (680, 1000, 2500),
}
_NASALS = {'m': (250, 1000, 2200), 'n': (250, 1700, 2600), 'ɲ': (250, 2000, 2800), 'ŋ': (250, 1200, 2400)}
_FRIC_VL = set('sʃfθxçh')
_FRIC_VD = set('zʒvðɣβʝ')
_STOPS = set('ptkbdgʔ')
_APPROX = {'l': (360, 1300, 2600), 'ɾ': (400, 1300, 2600), 'r': (400, 1300, 2600),
           'ʎ': (300, 2000, 2800), 'j': (300, 2200, 3000), 'w': (320, 800, 2300), 'ʋ': (400, 1400, 2400)}


def formant_wav(ipa_words, f0=118.0, rate=1.0, gap_s=0.11):
    """The prototype's source-filter formant synthesizer, driven by IPA (one string per word).
    Returns WAV bytes at 16 kHz. Robotic but intelligible; deterministic."""
    SR = 16000
    rnd = random.Random(20251001)

    class Res:
        def __init__(self): self.y1 = self.y2 = 0.0; self.a1 = self.a2 = self.g = 0.0
        def set(self, f, bw):
            r = math.exp(-math.pi * bw / SR); th = 2 * math.pi * f / SR
            self.a1 = 2 * r * math.cos(th); self.a2 = -(r * r)
            self.g = (1 - r) * math.sqrt(1 - 2 * r * math.cos(2 * th) + r * r)
        def step(self, x):
            y = self.g * x + self.a1 * self.y1 + self.a2 * self.y2
            self.y2 = self.y1; self.y1 = y; return y
    R1, R2, R3 = Res(), Res(), Res()
    out, st = [], {"phase": 0.0}
    cur = [500.0, 1500.0, 2500.0]

    def seg(target, dur, voiced, amp, noise_amt=0.0):
        n = max(1, int(SR * dur / rate))
        glide = int(0.03 * SR)
        for i in range(n):
            for k in range(3):
                cur[k] = cur[k] + (target[k] - cur[k]) * (1.0 / max(1, glide - i)) if i < glide else target[k]
            R1.set(cur[0], 80); R2.set(cur[1], 110); R3.set(cur[2], 160)
            env = min(1.0, i / (0.008 * SR)) * min(1.0, (n - i) / (0.008 * SR))
            if voiced:
                st["phase"] += f0 / SR
                src = 0.0
                if st["phase"] >= 1.0:
                    st["phase"] -= 1.0; src = 1.0
                src -= 0.5 * (1.0 if st["phase"] < f0 / SR else 0.0)
                if noise_amt:
                    src += noise_amt * rnd.uniform(-1, 1)
            else:
                src = rnd.uniform(-1, 1)
            out.append(amp * env * (R1.step(src) + 0.6 * R2.step(src) + 0.3 * R3.step(src)))

    def gap(d):
        out.extend([0.0] * int(SR * d))
    for ipa in ipa_words[:40]:
        chars = [c for c in (ipa or "").strip("/") if c not in " ˈˌ.|‖"]
        j = 0
        while j < len(chars):
            c = chars[j]; nxt = chars[j + 1] if j + 1 < len(chars) else ''
            longv = nxt == 'ː'
            if c in _VOWEL_FORMANTS:
                seg(list(_VOWEL_FORMANTS[c]), 0.18 if longv else 0.13, True, 0.9)
                if longv:
                    j += 1
            elif c in _NASALS:
                seg(list(_NASALS[c]), 0.10, True, 0.7)
            elif c in _APPROX:
                seg(list(_APPROX[c]), 0.08, True, 0.8)
            elif c in _STOPS:
                gap(0.04); seg([1800, 2200, 2800], 0.02, False, 0.5)
            elif c in _FRIC_VL:
                seg([2600, 4000, 6000], 0.11, False, 0.45)
            elif c in _FRIC_VD:
                seg([400, 1600, 2600], 0.09, True, 0.55, noise_amt=0.6)
            else:
                seg([500, 1500, 2500], 0.06, True, 0.5)
            j += 1
        gap(gap_s)
    if not out:
        gap(0.2)
    peak = max((abs(s) for s in out), default=1.0) or 1.0
    return write_wav([0.3 * s / peak for s in out], SR)


def tone_wav(f0=150.0, seconds=1.5, sr=16000, vibrato_hz=0.0, vibrato_st=0.0, noise=0.0, gaps=()):
    """A synthetic voiced test signal (pulse train through a vowel filter) — used by the self-test
    to check that the measurements find what was put in."""
    rnd = random.Random(7)
    x, ph = [], 0.0
    for n in range(int(seconds * sr)):
        tt = n / float(sr)
        if any(a <= tt < b for a, b in gaps):
            x.append(0.0); continue
        f = f0 * 2 ** ((vibrato_st * math.sin(2 * math.pi * vibrato_hz * tt)) / 12.0) if vibrato_hz else f0
        ph += f / sr
        s = 0.0
        if ph >= 1.0:
            ph -= 1.0
        s = sum(math.sin(2 * math.pi * k * ph) / k for k in range(1, 8))
        x.append(0.25 * s + noise * rnd.uniform(-1, 1))
    return write_wav(x, sr)
