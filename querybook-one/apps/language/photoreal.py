"""Photo Real Lab: perfect lip-sync engineered from one perfect sample, and proven on every output.

The method:
  1. REFERENCE — one real recording of the author speaking (real footage is perfect lip-sync by definition).
     It is measured into a signature: how far the lips lead the sound, the mouth shape for every sound
     (viseme), how fast the mouth opens and closes, how long the lips stay shut on p/b/m, how often the mouth
     changes direction, how jaw and lips move together, blinking and head micro-motion, and how well the lips
     agree with the words.
  2. MEASURE — any rendering (the photo-driven face, a HeyGen or D-ID video, a local model's video) is
     tracked by the same face tracker and measured into the same signature.
  3. SCORE AND GATE — each dimension is compared with the reference (0–100); a rendering is released only
     if the overall score and every critical dimension pass. Failures say which dimension failed.
  4. CALIBRATE — for the photo-driven face, the differences are turned into corrected settings and the
     loop repeats until it passes (closed-loop calibration), so it passes every time, not by luck.
  5. GRAPH — every reference, measurement, setting and verdict is a QueryBook fact packet (UFCS 1.0:
     subject–predicate–object, fingerprint, trust, source) in the "photoreal" domain. The graph answers which
     method, which settings and which fixes produce real-looking lip-sync, and exports to the QueryBook store.
"""
import datetime, hashlib, json, math, time

import lipread
import visemes

DOMAIN = "photoreal"

SCHEMA = """
CREATE TABLE IF NOT EXISTS photoreal_graph (
  fingerprint TEXT PRIMARY KEY,           -- UFCS semantic fingerprint: sha256(subject|predicate|object|polarity)
  subject TEXT NOT NULL, predicate TEXT NOT NULL, object TEXT NOT NULL,
  polarity TEXT NOT NULL DEFAULT '+',
  domain TEXT NOT NULL,
  trust REAL NOT NULL,
  source TEXT NOT NULL,                   -- which measurement produced it
  experiment TEXT,                        -- reference / measurement / calibration id
  created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS photoreal_graph_subject ON photoreal_graph(subject);
CREATE INDEX IF NOT EXISTS photoreal_graph_predicate ON photoreal_graph(predicate);
CREATE TABLE IF NOT EXISTS photoreal_runs (
  id INTEGER PRIMARY KEY,
  created TEXT NOT NULL,
  kind TEXT NOT NULL,                     -- reference / measure / calibrate
  persona INTEGER, narration INTEGER, method TEXT,
  signature TEXT, scores TEXT, params TEXT, verdict TEXT
);
"""

# dimension: (label, tolerance, kind, weight, critical) — kind "abs" compares the difference with the reference,
# "excess" is already a difference from the author's model, "floor" counts only falling short.
# Every dimension is independent of WHICH words are spoken: the author's model predicts the ideal mouth for any text.
DIMENSIONS = {
    "lead_error_ms": ("timing against the author's own lip lead (ms)", 40.0, "excess", 3, True),
    "motion_error": ("lip opening, frame by frame, against the author's model", 0.04, "excess", 3, True),
    "width_error": ("mouth width, frame by frame, against the author's model", 0.03, "excess", 2, True),
    "closure_ms": ("lips shut on p / b / m (ms)", 40.0, "abs", 1, False),
    "agreement": ("lips agree with the words", 15.0, "floor", 1, False),
    "jaw_lip_corr": ("jaw and lips move together", 0.25, "abs", 1, False),
    "blink_per_min": ("blinks per minute (clips of 20 s or more)", 8.0, "abs", 1, False),
    "head_sd_deg": ("head micro-motion (degrees)", 1.5, "abs", 1, False),
}
PASS_OVERALL, PASS_CRITICAL = 85, 70
SAMPLE_MIN_EXPLAINED = 0.8                                # a perfect sample's lips follow its words this closely or better
FPS = 50                                                   # model time step (20 ms)

# The reference passage (written for this lab, free to use): about 30 s read aloud, every mouth shape several times.
REFERENCE_PASSAGE = ("Before the autumn rain, my brave father would fish by the shore of a quiet blue lake. "
                     "He thought the thin morning mist was beautiful. Each June the children choose a cheap jar, "
                     "measure sugar for jam, and sing as they walk home. Who knows why a small boat feels so calm? "
                     "Look at the large dark car, the red roof of the old house, and the view we love.")
ALL_VISEMES = ["PP", "FF", "TH", "DD", "kk", "CH", "SS", "nn", "RR", "aa", "E", "I", "O", "U"]

DEFAULT_PARAMS = {"gap_gain": 1.0, "width_gain": 1.0, "lead_ms": 60, "smooth_ms": 60, "blink_per_min": 15, "head_sd_deg": 1.0, "shapes": {}}


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-4]


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _pct(vals, q):
    v = sorted(vals)
    return v[min(len(v) - 1, int(q * len(v)))] if v else 0.0


def _median(vals):
    return _pct(vals, 0.5)


def _corr(a, b):
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    ma, mb = sum(a[:n]) / n, sum(b[:n]) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a[:n])) or 1e-9
    sb = math.sqrt(sum((x - mb) ** 2 for x in b[:n])) or 1e-9
    return sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / (sa * sb)


def _linear(frames, key, fps=FPS, fn=None):
    """A per-frame value as a regular series, linearly interpolated (not held) between frames."""
    ts = [_f(f.get("t")) for f in frames]
    vs = [fn(f) if fn else _f(f.get(key)) for f in frames]
    out, k = [], 0
    for i in range(int((ts[-1] + 0.05) * fps)):
        t = i / fps
        while k + 1 < len(ts) and ts[k + 1] <= t:
            k += 1
        if k + 1 < len(ts) and ts[k + 1] > ts[k] and t >= ts[k]:
            out.append(vs[k] + (t - ts[k]) / (ts[k + 1] - ts[k]) * (vs[k + 1] - vs[k]))
        else:
            out.append(vs[k])
    return out


def _solve(A, b):
    """Gaussian elimination with partial pivoting (small dense systems)."""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        if abs(M[c][c]) < 1e-12:
            continue
        for r in range(n):
            if r != c and M[r][c]:
                k = M[r][c] / M[c][c]
                M[r] = [x - k * y for x, y in zip(M[r], M[c])]
    return [M[i][n] / M[i][i] if abs(M[i][i]) > 1e-12 else 0.0 for i in range(n)]


# ---------------------------------------------------------------------- the author's mouth model
def _responses(vis, n, tau_ms, pad):
    """For each sound v: the indicator 'v is being spoken' passed through the mouth's first-order response,
    over n + 2·pad steps (index pad = time 0), so any lead is just a shift."""
    names = sorted({x["v"] for x in vis} | {"sil"})
    a = 1 - math.exp(-(1.0 / FPS) / max(0.005, tau_ms / 1000.0))
    total = n + 2 * pad
    cur = ["sil"] * total
    for x in vis:
        for k in range(max(0, int(round(x["start"] * FPS)) + pad), min(total, int(round(x["end"] * FPS)) + pad)):
            cur[k] = x["v"]
    out = {}
    for v in names:
        r, y = [], 1.0 if cur[0] == v else 0.0
        for k in range(total):
            y += a * ((1.0 if cur[k] == v else 0.0) - y)
            r.append(y)
        out[v] = r
    return names, out


def _fit_shapes(names, R, s, ys, mask, ridge=1e-4):
    """Least-squares target shapes (one per sound) for each measured series in ys, at shift s."""
    V = len(names)
    idx = [k for k, ok in enumerate(mask) if ok]
    AtA = [[0.0] * V for _ in range(V)]
    for i, v in enumerate(names):
        rv = R[v]
        for j in range(i, V):
            rw = R[names[j]]
            AtA[i][j] = AtA[j][i] = sum(rv[k + s] * rw[k + s] for k in idx)
        AtA[i][i] += ridge * len(idx)
    sols, sse = [], 0.0
    for y in ys:
        Atb = [sum(R[v][k + s] * y[k] for k in idx) for v in names]
        x = _solve(AtA, Atb)
        sols.append(x)
        sse += sum((y[k] - sum(x[i] * R[names[i]][k + s] for i in range(V))) ** 2 for k in idx)
    return sols, sse / max(1, len(idx) * len(ys))


def fit_model(gap, width, vis, mask=None):
    """The author's mouth model from one recording: lead (lips before sound), response time, and the target lip
    opening and width for every sound — the least-squares fit over every frame (coarse grid, then refined)."""
    n = min(len(gap), len(width))
    mask = mask or [True] * n
    pad = int(0.35 * FPS)
    best = None

    def tryit(tau, lead):
        nonlocal best
        names, R = _responses(vis, n, tau, pad)
        s = pad + int(round(lead / 1000.0 * FPS))            # lips at time t show the sound at t + lead
        (g, w), mse = _fit_shapes(names, R, s, [gap[:n], width[:n]], mask[:n])
        if best is None or mse < best[0]:
            best = (mse, tau, lead, names, g, w)
    for tau in (15, 30, 50, 80, 120):
        for lead in range(-100, 301, 40):
            tryit(tau, lead)
    _, t0, l0, *_ = best
    for tau in sorted({max(8, t0 + d) for d in (-12, -6, 0, 6, 12)}):
        for lead in range(l0 - 30, l0 + 31, 10):
            tryit(tau, lead)
    mse, tau, lead, names, g, w = best
    pg = predict({"lead_ms": lead, "tau_ms": tau, "gap": dict(zip(names, g)), "width": dict(zip(names, w))}, vis, n)
    k_ok = [k for k in range(n) if mask[k]]
    rg = math.sqrt(sum((gap[k] - pg[0][k]) ** 2 for k in k_ok) / max(1, len(k_ok)))
    rw = math.sqrt(sum((width[k] - pg[1][k]) ** 2 for k in k_ok) / max(1, len(k_ok)))
    mg = sum(gap[k] for k in k_ok) / max(1, len(k_ok))
    var = sum((gap[k] - mg) ** 2 for k in k_ok) / max(1, len(k_ok))
    return {"lead_ms": lead, "tau_ms": tau, "gap": {v: round(max(0.0, x), 4) for v, x in zip(names, g)},
            "width": {v: round(max(0.01, x), 4) for v, x in zip(names, w)}, "rmse_gap": round(rg, 4), "rmse_width": round(rw, 4),
            "explained": round(1 - rg * rg / var, 3) if var > 0 else 0.0}


def predict(model, vis, n):
    """The author's ideal lip opening and mouth width for a viseme track (any text), n steps at FPS."""
    pad = int(0.35 * FPS)
    names, R = _responses(vis, n, model["tau_ms"], pad)
    s = pad + int(round(model["lead_ms"] / 1000.0 * FPS))
    G, Wd = _complete(model)
    g = [sum(G[v] * R[v][k + s] for v in names) for k in range(n)]
    w = [sum(Wd[v] * R[v][k + s] for v in names) for k in range(n)]
    return g, w


def _complete(model):
    """Shapes for every sound: a sound the reference never showed takes the average of the author's sounds that
    look the same on the lips (same mouth class), else the author's overall average."""
    G, Wd = dict(model["gap"]), dict(model["width"])
    mean_g, mean_w = sum(G.values()) / len(G), sum(Wd.values()) / len(Wd)
    for v in ALL_VISEMES + ["sil"]:
        if v in G:
            continue
        same = [x for x in G if lipread.FROM_VISEME.get(x) == lipread.FROM_VISEME.get(v)]
        G[v] = sum(G[x] for x in same) / len(same) if same else mean_g
        Wd[v] = sum(Wd[x] for x in same) / len(same) if same else mean_w
    return G, Wd


# ---------------------------------------------------------------------- 1 + 2: the signature of a speaking face
def signature(frames, wav, text, lang="en", info=None, lab=None, word_times=None, fit=False):
    """Measure a speaking face (real or rendered) into the lab's signature. frames come from the browser tracker
    (t, gap, mouth_px, face_h, yaw, pitch, bs); wav is the soundtrack; text the words spoken. fit=True also
    fits the author's mouth model (for the reference)."""
    info = info or {}
    seen = sorted((f for f in frames or [] if isinstance(f, dict) and f.get("face")), key=lambda f: _f(f.get("t")))
    if len(seen) < 10:
        raise ValueError("A face was found in only %d frames — the lab needs a clear, front-facing face." % len(seen))
    H = _f(info.get("height"), 720) or 720
    cls = lipread.classes_of(seen)[0]
    gap = _linear(seen, "gap")
    width = _linear(seen, None, fn=lambda f: _f(f.get("mouth_px")) / ((_f(f.get("face_h")) * H) or 1.0))
    track = visemes.align(text, wav, lang, lab, word_times)
    vis = [{"v": x["v"], "start": x["start"], "end": x["end"]} for x in track["visemes"]]
    m = visemes._measured(wav)
    # how long the lips stay shut on p / b / m: closed runs that sit inside speech (not pauses)
    import speechlab
    env = speechlab._envelope(m)
    g100 = _linear(seen, "gap", 100)
    speech_on = [e > 0.35 for e in env] if env else [True] * len(g100)
    runs, k = [], 0
    while k < len(g100):
        if g100[k] < 0.04:
            j = k
            while j < len(g100) and g100[j] < 0.04:
                j += 1
            if 3 <= j - k <= 40 and any(speech_on[max(0, k - 15):k]) and any(speech_on[j:j + 15]):
                runs.append((j - k) * 10)
            k = j
        else:
            k += 1
    jaw = [_f((f.get("bs") or {}).get("jawOpen")) for f in seen]
    gp = [_f(f.get("gap")) for f in seen]
    dur = (_f(seen[-1].get("t")) - _f(seen[0].get("t"))) or 1.0
    blink = [((_f((f.get("bs") or {}).get("eyeBlinkLeft")) + _f((f.get("bs") or {}).get("eyeBlinkRight"))) / 2) for f in seen]
    blinks = sum(1 for i in range(1, len(blink)) if blink[i] >= 0.5 > blink[i - 1])
    yaw, pitch = [_f(f.get("yaw")) for f in seen], [_f(f.get("pitch")) for f in seen]
    sd = lambda xs: math.sqrt(sum((x - sum(xs) / len(xs)) ** 2 for x in xs) / len(xs)) if xs else 0.0
    out = {"closure_ms": round(_median(runs), 1) if runs else None, "closures": len(runs),
           "jaw_lip_corr": round(_corr(jaw, gp), 3),
           "blink_per_min": round(60.0 * blinks / dur, 1) if dur >= 20 else None,   # too few blinks in a short clip to judge a rate
           "blinks": blinks, "head_sd_deg": round((sd(yaw) + sd(pitch)) / 2, 2),
           "agreement": lipread.script_agreement(cls, text, lang, lab)["agreement"] if text else None,
           "frames": len(seen), "seconds": round(dur, 2), "fps": round((len(seen) - 1) / dur, 1), "words": len(track["words"]),
           "series": {"fps": FPS, "gap": [round(x, 4) for x in gap], "width": [round(x, 4) for x in width]}, "visemes": vis}
    if fit:
        out["model"] = fit_model(gap, width, vis)
        out["lead_ms"] = out["model"]["lead_ms"]
    return out


def keyframes(frames, vis, model, info=None):
    """The real frames of the perfect sample to keep as the author's mouth library: for each sound, the frame in
    the steady middle of that sound whose lip opening and width are closest to the author's model; a neutral
    rest frame (mouth closed, facing the camera, outside speech); and a blink frame."""
    info = info or {}
    H = _f(info.get("height"), 720) or 720
    seen = [f for f in frames or [] if isinstance(f, dict) and f.get("face")]
    lead = model["lead_ms"] / 1000.0
    width = lambda f: _f(f.get("mouth_px")) / ((_f(f.get("face_h")) * H) or 1.0)
    out = {}
    for v in model["gap"]:
        if v == "sil":
            continue
        best = None
        for f in seen:
            t = _f(f.get("t")) + lead
            seg = next((x for x in vis if x["v"] == v and x["end"] - x["start"] >= 0.06 and
                        x["start"] + 0.3 * (x["end"] - x["start"]) <= t <= x["end"] - 0.3 * (x["end"] - x["start"])), None)
            if not seg:
                continue
            d = abs(_f(f.get("gap")) - model["gap"][v]) + 0.5 * abs(width(f) - model["width"][v]) + 0.002 * abs(_f(f.get("yaw")))
            if best is None or d < best[0]:
                best = (d, _f(f.get("t")), _f(f.get("gap")))
        # keep a frame only if it really shows that sound: close to the model, and closed lips for p / b / m
        if best and best[0] < 0.08 and not (v == "PP" and best[2] > 0.05):
            out[v] = round(best[1], 3)
    speech_from = min((x["start"] for x in vis if x["v"] != "sil"), default=0.0)
    speech_to = max((x["end"] for x in vis if x["v"] != "sil"), default=0.0)
    rest = [f for f in seen if _f(f.get("t")) + lead < speech_from - 0.1 or _f(f.get("t")) + lead > speech_to + 0.2] or seen
    blink = lambda f: (_f((f.get("bs") or {}).get("eyeBlinkLeft")) + _f((f.get("bs") or {}).get("eyeBlinkRight"))) / 2
    r = min(rest, key=lambda f: _f(f.get("gap")) + 0.01 * abs(_f(f.get("yaw"))) + 0.01 * abs(_f(f.get("pitch"))) + blink(f))
    out["rest"] = round(_f(r.get("t")), 3)
    b = max(seen, key=blink)
    if blink(b) >= 0.5:
        out["blink"] = round(_f(b.get("t")), 3)
    return out


def _best_shift(meas, pred, max_ms=300):
    """The shift (ms) that best lines a measured series up with the predicted one, and the error there.
    Positive = the measured lips are later than the author's would be."""
    n = min(len(meas), len(pred))
    best = None
    for s in range(-int(max_ms / 1000 * FPS), int(max_ms / 1000 * FPS) + 1):
        idx = range(max(0, s), min(n, n + s))
        if len(idx) < FPS:
            continue
        e = sum((meas[k] - pred[k - s]) ** 2 for k in idx) / len(idx)
        if best is None or e < best[1]:
            best = (s, e)
    return round(1000.0 * best[0] / FPS), math.sqrt(best[1])


# ---------------------------------------------------------------------- 3: score and gate
def compare(ref, cand):
    """Score a candidate against the reference: its lips are compared, frame by frame, with what the author's own
    mouth model predicts for the SAME words (any text), plus the slower signs of life. 0–100 per dimension."""
    model = ref["model"]
    n = min(len(cand["series"]["gap"]), len(cand["series"]["width"]))
    pg, pw = predict(model, cand["visemes"], n)
    shift, eg = _best_shift(cand["series"]["gap"][:n], pg)
    s = int(round(shift / 1000.0 * FPS))
    idx = range(max(0, s), min(n, n + s))
    ew = math.sqrt(sum((cand["series"]["width"][k] - pw[k - s]) ** 2 for k in idx) / max(1, len(idx)))
    diffs = {"lead_error_ms": abs(shift), "motion_error": max(0.0, eg - model["rmse_gap"]), "width_error": max(0.0, ew - model["rmse_width"])}
    out, tot, wsum, failed = {}, 0.0, 0.0, []
    for k, (label, tol, kind, w, critical) in DIMENSIONS.items():
        if kind == "excess":
            rv, cv, d = 0, round(diffs[k], 4), diffs[k]
        else:
            rv, cv = ref.get(k), cand.get(k)
            if rv is None or cv is None:
                continue
            d = min(0.0, cv - rv) if kind == "floor" else cv - rv
        sc = 100.0 * math.exp(-0.693 * (d / tol) ** 2)      # 100 when equal, 50 at one tolerance away
        out[k] = {"label": label, "reference": rv, "candidate": cv, "score": round(sc, 1), "critical": critical}
        tot += w * sc; wsum += w
        if critical and sc < PASS_CRITICAL:
            failed.append(label)
    overall = round(tot / wsum, 1) if wsum else 0.0
    passed = overall >= PASS_OVERALL and not failed
    return {"overall": overall, "passed": passed, "dimensions": out, "failed": failed, "lead_shift_ms": shift,
            "verdict": ("PASS — moves like the author's own mouth would for these words" if passed else
                        "FAIL — " + (", ".join(failed) if failed else "overall %.0f below %d" % (overall, PASS_OVERALL)))}


# ---------------------------------------------------------------------- 4: closed-loop calibration (photo-driven face)
def initial_params(ref):
    """Renderer settings taken straight from the author's fitted model: shapes, lead, response, blinking, head motion."""
    m = ref["model"]
    p = json.loads(json.dumps(DEFAULT_PARAMS))
    G, Wd = _complete(m)
    p.update({"lead_ms": m["lead_ms"], "smooth_ms": m["tau_ms"], "head_sd_deg": ref.get("head_sd_deg") or 1.0,
              "blink_per_min": ref.get("blink_per_min") or (round(60.0 * ref.get("blinks", 0) / ref["seconds"], 1) if ref.get("seconds") and ref.get("blinks") else 15),
              "shapes": {v: {"gap": round(G[v], 4), "width": round(Wd[v], 4)} for v in G}})
    return p


def correct(params, ref, cand):
    """New renderer settings: fit the same model to the rendering and correct each part by what differs."""
    rm = ref["model"]
    n = min(len(cand["series"]["gap"]), len(cand["series"]["width"]))
    cm = fit_model(cand["series"]["gap"][:n], cand["series"]["width"][:n], cand["visemes"])
    p = json.loads(json.dumps(params))
    p["lead_ms"] = int(round(p["lead_ms"] + (rm["lead_ms"] - cm["lead_ms"])))
    p["smooth_ms"] = int(max(8, min(200, p["smooth_ms"] * rm["tau_ms"] / max(5, cm["tau_ms"]))))
    ps = p.setdefault("shapes", {})
    for v in rm["gap"]:
        if v not in cm["gap"]:
            continue
        cur = ps.get(v) or {"gap": rm["gap"][v], "width": rm["width"][v]}
        ps[v] = {"gap": round(max(0.0, cur["gap"] + 0.9 * (rm["gap"][v] - cm["gap"][v]) / max(0.3, p["gap_gain"])), 4),
                 "width": round(max(0.01, cur["width"] + 0.9 * (rm["width"][v] - cm["width"][v]) / max(0.6, p["width_gain"])), 4)}
    p["blink_per_min"] = params.get("blink_per_min")
    p["head_sd_deg"] = ref.get("head_sd_deg") or params.get("head_sd_deg")
    return p


# ---------------------------------------------------------------------- 5: the graph
def packet(subject, predicate, obj, trust=0.95, source="photoreal-lab", polarity="+"):
    """A UFCS 1.0 fact packet (same content addressing as the QueryBook store)."""
    norm = lambda s: " ".join(str(s).strip().lower().split())
    fp = hashlib.sha256("|".join([norm(subject), norm(predicate), norm(obj), polarity]).encode()).hexdigest()
    ing = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return {"ufcs_version": "1.0", "fact_type": "assertion", "domain": DOMAIN,
            "nucleus": {"subject": str(subject), "predicate": str(predicate), "object": str(obj)}, "polarity": polarity,
            "semantic_fingerprint": fp, "confidence": {"trust_score": trust},
            "sources": [{"id": source, "name": "QueryBook Photo Real Lab", "class": "measurement", "reputation": 1.0}],
            "certification": {"authority_class": "measurement", "trust_score": trust}, "temporal": {"ingested": ing},
            "safety": {"classification": "PRIVATE", "acl": ["owner"]}}


def _lean(sig):
    """The signature without the long per-frame series (what is stored and shown)."""
    return {k: v for k, v in sig.items() if k not in ("series", "visemes")}


class Lab:
    def __init__(self, store, personas, lab=None):
        self.store, self.personas, self.lab = store, personas, lab

    def _facts(self, facts, experiment, source):
        if self.store.read_only:
            return 0
        n = 0
        with self.store.write() as db:
            for s, p_, o, trust in facts:
                pk = packet(s, p_, o, trust, source)
                cur = db.execute("INSERT OR IGNORE INTO photoreal_graph(fingerprint, subject, predicate, object, polarity, domain, trust, source, experiment, created) "
                                 "VALUES(?,?,?,?,?,?,?,?,?,?)", (pk["semantic_fingerprint"], s, p_, str(o), "+", DOMAIN, trust, source, experiment, _now()))
                n += cur.rowcount
        return n

    def _run(self, kind, persona=None, narration=None, method=None, sig=None, scores=None, params=None, verdict=None):
        with self.store.write() as db:
            return db.execute("INSERT INTO photoreal_runs(created, kind, persona, narration, method, signature, scores, params, verdict) VALUES(?,?,?,?,?,?,?,?,?)",
                              (_now(), kind, persona, narration, method, json.dumps(sig) if sig else None, json.dumps(scores) if scores else None,
                               json.dumps(params) if params else None, verdict)).lastrowid

    # 1. the perfect sample
    def set_reference(self, pid, frames, wav, text, lang="en", info=None, word_times=None):
        p = self.personas.get(pid)
        sig = signature(frames, wav, text, lang, info, self.lab, word_times, fit=True)
        if sig["model"]["explained"] < 0.3:
            raise ValueError("The lips in this recording follow the words too loosely to learn from (model explains %d%%) — record again: "
                             "face the camera, good light, speak clearly." % round(100 * sig["model"]["explained"]))
        rid = self._run("reference", pid, None, "real footage", _lean(sig), verdict="reference")
        params = initial_params(sig)
        kf = keyframes(frames, sig["visemes"], sig["model"], info)
        ref = {"run": rid, "signature": _lean(sig), "params": params, "text": text, "created": _now(), "keyframes": kf, "library": {}}
        with self.store.write() as db:
            db.execute("UPDATE personas SET reference = ? WHERE id = ?", (json.dumps(ref), int(pid)))
        subj = "author %s reference #%d" % (p["name"], rid)
        mdl = sig["model"]
        missing = [v for v in ALL_VISEMES if v not in mdl["gap"]]
        mdl["missing"] = missing
        warn = []
        if mdl["explained"] < SAMPLE_MIN_EXPLAINED:
            warn.append("the lips follow the words only %d%% (%d%% needed for a perfect narrator) — re-record: whole face, steady, good front light, 60 fps, read clearly"
                        % (round(100 * mdl["explained"]), round(100 * SAMPLE_MIN_EXPLAINED)))
        if mdl["gap"].get("PP", 0) > min([mdl["gap"][v] for v in ("aa", "O", "E") if v in mdl["gap"]] or [1]):
            warn.append("closed-lip sounds (p, b, m) do not look closed in this sample")
        lost = [v for v in ALL_VISEMES if v in mdl["gap"] and v not in kf]
        if lost:
            warn.append("no clear frame for: %s (those sounds use the nearest look-alike)" % ", ".join(lost))
        ref["warnings"] = warn
        with self.store.write() as db:
            db.execute("UPDATE personas SET reference = ? WHERE id = ?", (json.dumps(ref), int(pid)))
        facts = [(subj, "mouth shapes not shown (estimated from look-alikes)", ", ".join(missing) or "none", 0.97)] + \
                [(subj, "sample problem", w_, 0.97) for w_ in warn] + [(subj, "is", "real footage of the author speaking (perfect lip-sync by definition)", 1.0),
                 (subj, "lips lead the sound by (ms)", mdl["lead_ms"], 0.97), (subj, "mouth response time (ms)", mdl["tau_ms"], 0.97),
                 (subj, "model explains lip motion (share)", mdl["explained"], 0.97), (subj, "model lip error (rmse)", mdl["rmse_gap"], 0.97)]
        for k in ("closure_ms", "jaw_lip_corr", "blink_per_min", "head_sd_deg", "agreement"):
            if sig.get(k) is not None:
                facts.append((subj, DIMENSIONS[k][0], sig[k], 0.97))
        for v in mdl["gap"]:
            facts.append(("author %s viseme %s" % (p["name"], v), "lip opening (share of mouth width)", mdl["gap"][v], 0.95))
            facts.append(("author %s viseme %s" % (p["name"], v), "mouth width (share of face height)", mdl["width"][v], 0.95))
        facts.append(("photo-driven renderer for %s" % p["name"], "starts from settings", json.dumps(params, sort_keys=True), 0.9))
        self._facts(facts, "reference-%d" % rid, "reference")
        self.store.activity("Photo Real Lab: reference", "ok", "%s · %d frames · lead %s ms · response %s ms · explains %d%%" %
                            (p["name"], sig["frames"], mdl["lead_ms"], mdl["tau_ms"], round(100 * mdl["explained"])))
        return {"run": rid, "signature": _lean(sig), "model": mdl, "params": params, "keyframes": kf, "warnings": warn, "dimensions": {k: v[0] for k, v in DIMENSIONS.items()}}

    def reference(self, pid):
        r = self.personas.get(pid).get("reference")
        if not r:
            raise ValueError("Record the perfect reference sample first (one clear recording of the author speaking).")
        return r

    # 2 + 3. measure a rendering and gate it
    def measure(self, pid, frames, wav, text, method, lang="en", info=None, narration=None, params=None):
        p = self.personas.get(pid)
        ref = self.reference(pid)
        sig = signature(frames, wav, text, lang, info, self.lab)
        sc = compare(ref["signature"], sig)
        rid = self._run("measure", pid, narration, method, _lean(sig), sc, params, sc["verdict"])
        subj = "rendering #%d (%s, %s)" % (rid, method, p["name"])
        facts = [(subj, "method", method, 1.0), (subj, "realism score", sc["overall"], 0.95),
                 (subj, "passes the gate", "yes" if sc["passed"] else "no", 0.95)]
        for k, d in sc["dimensions"].items():
            facts.append((subj, "score: " + d["label"], d["score"], 0.95))
        for lbl in sc["failed"]:
            facts.append((subj, "fails on", lbl, 0.95))
            facts.append(("method " + method, "has failed on", lbl, 0.8))
        if params:
            facts.append((subj, "renderer settings", json.dumps(params, sort_keys=True), 0.95))
        self._facts(facts, "measure-%d" % rid, "measurement")
        if narration:
            with self.store.write() as db:
                db.execute("UPDATE narrations SET score = ? WHERE id = ?", (json.dumps({"run": rid, "overall": sc["overall"], "passed": sc["passed"], "verdict": sc["verdict"]}), int(narration)))
        self.store.activity("Photo Real Lab: measure", "ok" if sc["passed"] else "failed", "%s · %s · %.0f/100 · %s" % (p["name"], method, sc["overall"], sc["verdict"][:120]))
        return {"run": rid, "signature": sig, "score": sc}  # full signature: calibration fits the rendering's own model

    # 4. closed loop for the photo-driven face
    def calibrate(self, pid, frames, wav, text, params, lang="en", info=None, round_no=1):
        """Measure one rendering made with `params`; return the verdict and the corrected settings for the next round.
        When it passes, the settings are stored as the persona's proven settings."""
        ref = self.reference(pid)
        m = self.measure(pid, frames, wav, text, "photo", lang, info, None, params)
        sc = m["score"]
        nxt = params if sc["passed"] else correct(params, ref["signature"], m["signature"])
        if sc["passed"]:
            ref["params"], ref["proven"] = params, {"run": m["run"], "score": sc["overall"], "at": _now()}
            with self.store.write() as db:
                db.execute("UPDATE personas SET reference = ? WHERE id = ?", (json.dumps(ref), int(pid)))
            self._facts([("photo-driven renderer for %s" % self.personas.get(pid)["name"], "proven settings", json.dumps(params, sort_keys=True), 0.97),
                         ("photo-driven renderer for %s" % self.personas.get(pid)["name"], "passes the gate after rounds", round_no, 0.97)],
                        "calibrate-%d" % m["run"], "calibration")
        else:
            changes = {k: (params.get(k), nxt.get(k)) for k in nxt if k != "shapes" and nxt.get(k) != params.get(k)}
            self._facts([("calibration round %d (run #%d)" % (round_no, m["run"]), "changed " + k, "%s → %s" % (a, b), 0.9) for k, (a, b) in changes.items()],
                        "calibrate-%d" % m["run"], "calibration")
        self._run("calibrate", pid, None, "photo", None, {"round": round_no, "overall": sc["overall"], "passed": sc["passed"]}, nxt, sc["verdict"])
        return {"run": m["run"], "score": sc, "next_params": nxt, "passed": sc["passed"], "round": round_no}

    # 5. what the graph knows
    def findings(self, pid=None):
        q = self.store.query
        runs = q("SELECT id, created, kind, persona, method, scores, verdict FROM photoreal_runs WHERE kind = 'measure'" +
                 (" AND persona = ?" if pid else "") + " ORDER BY id", (int(pid),) if pid else ())
        by = {}
        for r in runs:
            s = json.loads(r["scores"] or "{}")
            b = by.setdefault(r["method"], {"method": r["method"], "measured": 0, "passed": 0, "scores": [], "fails": {}})
            b["measured"] += 1; b["passed"] += 1 if s.get("passed") else 0; b["scores"].append(s.get("overall", 0))
            for f in s.get("failed", []):
                b["fails"][f] = b["fails"].get(f, 0) + 1
        methods = []
        for b in by.values():
            methods.append({"method": b["method"], "measured": b["measured"], "pass_rate": round(b["passed"] / b["measured"], 3),
                            "mean_score": round(sum(b["scores"]) / len(b["scores"]), 1), "best_score": max(b["scores"]),
                            "most_common_failures": sorted(b["fails"].items(), key=lambda x: -x[1])[:3]})
        methods.sort(key=lambda m: (-m["pass_rate"], -m["mean_score"]))
        return {"methods": methods, "best": methods[0]["method"] if methods else None,
                "facts": self.store.scalar("SELECT count(*) FROM photoreal_graph", default=0),
                "recent": q("SELECT subject, predicate, object, trust, source, created FROM photoreal_graph ORDER BY created DESC, rowid DESC LIMIT 40")}

    def graph(self, subject=None, predicate=None, limit=500):
        sql, args = "SELECT * FROM photoreal_graph WHERE 1 = 1", []
        if subject:
            sql += " AND subject LIKE ?"; args.append("%" + subject + "%")
        if predicate:
            sql += " AND predicate LIKE ?"; args.append("%" + predicate + "%")
        return self.store.query(sql + " ORDER BY created, rowid LIMIT ?", tuple(args) + (int(limit),))

    def export_ufcs(self):
        """The lab's graph as UFCS 1.0 packets, one JSON object per line (for the QueryBook store)."""
        out = []
        for r in self.store.query("SELECT * FROM photoreal_graph ORDER BY created, rowid"):
            pk = packet(r["subject"], r["predicate"], r["object"], r["trust"], r["source"])
            pk["temporal"]["ingested"] = r["created"].replace(" ", "T")[:19] + "Z"
            out.append(json.dumps(pk, sort_keys=True))
        return "\n".join(out) + ("\n" if out else "")
