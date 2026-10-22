"""Speech motion library (Language 1.47): a person's own mouth movement, sound by sound, from exemplar clips.

The hand-built motion model shapes the mouth from rules; this one replays the person's real recorded movement. From each
exemplar clip (approved in the exemplar library, e.g. Gemini Omni clips of Pamela) the face tracker's points are read frame
by frame; the head's own movement is removed (a 2D similarity alignment on the face's stable bones: forehead, nose, eye
corners, cheekbones); what remains is how every point of the lower face moved away from the person's own closed-mouth rest,
in units of the eye-to-eye distance. The clip's sounds (phonemes, with their visemes and times) cut that movement into
units: one sound, with the sounds before and after it.

To speak new words, each sound of the new speech chooses the unit that fits best — the same mouth shape, the same
neighbours, a similar length, and a smooth join to the unit before (two units that followed each other in her own clip join
perfectly) — by dynamic programming over all choices (Viterbi). The chosen units are stretched to the new timing and
blended across their joins; pauses ease to her rest. The renderer moves the avatar's lower face by that movement, turned and
scaled to the avatar's own face, and places the teeth by the jaw (the lower teeth ride with the chin; the upper teeth stay
fixed to the skull), not by the lips.

Deterministic (the same clips and the same speech always give the same movement), standard library only, no AI model.
"""
import base64, json, math, os

VERSION = "1.0.0"
STEP = 0.0025                     # quantization of a displacement, in eye-to-eye distances (int8: ±0.32)
# the lower face: every tracked point below the nose base (MediaPipe face mesh indices), lips, chin and the jaw line included
POINTS = [0, 11, 12, 13, 14, 15, 16, 17, 18, 32, 37, 38, 39, 40, 41, 42, 43, 57, 58, 61, 62, 72, 73, 74, 76, 77, 78, 80, 81, 82,
          83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 95, 96, 106, 135, 136, 138, 140, 146, 148, 149, 150, 152, 164, 165, 167, 169,
          170, 171, 172, 175, 176, 178, 179, 180, 181, 182, 183, 184, 185, 186, 191, 192, 194, 199, 200, 201, 202, 204, 207,
          208, 210, 211, 212, 213, 214, 215, 216, 262, 267, 268, 269, 270, 271, 272, 273, 287, 288, 291, 292, 302, 303, 304,
          306, 307, 308, 310, 311, 312, 313, 314, 315, 316, 317, 318, 319, 320, 321, 322, 324, 325, 335, 364, 365, 367, 369,
          375, 377, 378, 379, 391, 393, 394, 395, 396, 397, 400, 402, 403, 404, 405, 406, 407, 408, 409, 410, 415, 416, 418,
          421, 422, 424, 426, 427, 428, 430, 431, 432, 433, 434, 435, 436]
STABLE = [10, 151, 9, 8, 168, 6, 197, 195, 5, 4, 1, 33, 133, 263, 362, 234, 454, 127, 356, 93, 323, 116, 345]
# visemes that look alike stand in for each other when the library has no unit of the exact shape
GROUP = {"PP": "lips", "FF": "lipteeth", "TH": "tongue", "DD": "tongue", "nn": "tongue", "SS": "teeth", "CH": "round_teeth",
         "kk": "back", "RR": "round", "U": "round", "O": "round", "aa": "open", "E": "spread", "I": "spread"}
PAD = 3                           # frames kept on each side of a sound, for the joins


# ------------------------------------------------------------------------------------------------ geometry
def _similarity(P, Q):
    """2D similarity (s·R, t) mapping points P onto Q (least squares, closed form)"""
    n = len(P)
    pcx, pcy = sum(p[0] for p in P) / n, sum(p[1] for p in P) / n
    qcx, qcy = sum(q[0] for q in Q) / n, sum(q[1] for q in Q) / n
    a = b = d = 0.0
    for (px, py), (qx, qy) in zip(P, Q):
        x, y, u, v = px - pcx, py - pcy, qx - qcx, qy - qcy
        a += x * u + y * v; b += x * v - y * u; d += x * x + y * y
    a, b = a / (d or 1), b / (d or 1)
    return a, b, qcx - (a * pcx - b * pcy), qcy - (b * pcx + a * pcy)


def _apply(T, p):
    a, b, tx, ty = T
    return (a * p[0] - b * p[1] + tx, b * p[0] + a * p[1] + ty)


def canonical(frames):
    """frames: [[(x, y)…478]] in pixels → the same frames with the head's movement removed: aligned on the stable points
    to the clip's mean face, eyes level, origin at the stable points' centre, 1 = eye-to-eye distance (33 ↔ 263)"""
    ok = [f for f in frames if f]
    if not ok:
        return [None] * len(frames)
    tmpl = [ok[len(ok) // 2][i] for i in range(len(ok[0]))]
    for _ in range(3):
        acc = [[0.0, 0.0] for _ in tmpl]
        for f in ok:
            T = _similarity([f[i] for i in STABLE], [tmpl[i] for i in STABLE])
            for i, p in enumerate(f):
                q = _apply(T, p); acc[i][0] += q[0]; acc[i][1] += q[1]
        tmpl = [(x / len(ok), y / len(ok)) for x, y in acc]
    e1, e2 = tmpl[33], tmpl[263]
    iod = math.hypot(e2[0] - e1[0], e2[1] - e1[1]) or 1.0
    ang = math.atan2(e2[1] - e1[1], e2[0] - e1[0])
    cx = sum(tmpl[i][0] for i in STABLE) / len(STABLE); cy = sum(tmpl[i][1] for i in STABLE) / len(STABLE)
    c, s = math.cos(-ang), math.sin(-ang)
    level = lambda p: (((p[0] - cx) * c - (p[1] - cy) * s) / iod, ((p[0] - cx) * s + (p[1] - cy) * c) / iod)
    out = []
    for f in frames:
        if not f:
            out.append(None); continue
        T = _similarity([f[i] for i in STABLE], [tmpl[i] for i in STABLE])
        out.append([level(_apply(T, f[i])) for i in range(len(f))])
    return out


# ------------------------------------------------------------------------------------------------ one clip
def analyse_clip(frames, fps, phonemes, exemplar=None, script=""):
    """frames: per video frame the tracker's 478 points in pixels (None where no face); phonemes: [{viseme, start_time,
    end_time}] from the clip's own sound. Returns the clip's movement (quantized) and its sound units."""
    can = canonical(frames)
    # missing frames take the nearest tracked one (a blink of the tracker must not jump the mouth to rest)
    last = next((c for c in can if c), None)
    for i, c in enumerate(can):
        if c:
            last = c
        else:
            can[i] = last
    if not last:
        raise ValueError("no face was found in the clip")
    gap = [c[14][1] - c[13][1] for c in can]
    order = sorted(range(len(can)), key=lambda i: (gap[i], i))[:max(3, len(can) // 10)]
    rest = [(sum(can[i][p][0] for i in order) / len(order), sum(can[i][p][1] for i in order) / len(order)) for p in POINTS]
    q = bytearray()
    for c in can:
        for k, p in enumerate(POINTS):
            for d in (c[p][0] - rest[k][0], c[p][1] - rest[k][1]):
                q.append(max(-127, min(127, int(round(d / STEP)))) & 0xFF)
    n = len(can)
    units = []
    ph = [x for x in phonemes if x.get("viseme") and x["viseme"] != "sil" and float(x["end_time"]) > float(x["start_time"])]
    for j, x in enumerate(ph):
        c0 = max(0, min(n - 1, int(round(float(x["start_time"]) * fps))))
        c1 = max(c0, min(n - 1, int(round(float(x["end_time"]) * fps)) - 1))
        units.append({"v": x["viseme"], "prev": ph[j - 1]["viseme"] if j else "sil", "next": ph[j + 1]["viseme"] if j + 1 < len(ph) else "sil",
                      "dur": round(float(x["end_time"]) - float(x["start_time"]), 3), "c0": c0, "c1": c1,
                      "p0": max(0, c0 - PAD), "p1": min(n - 1, c1 + PAD), "sym": x.get("symbol", "")})
    return {"exemplar": exemplar, "script": script, "fps": fps, "frames": n, "data": base64.b64encode(bytes(q)).decode(), "units": units}


# ------------------------------------------------------------------------------------------------ visual re-alignment
FEAT = (13, 14, 61, 291, 0, 17, 152)          # upper lip, lower lip, corners, outer lip middles, chin


def _features(clip):
    """per frame: lip opening, mouth width, upper-lip lift, lower-lip drop, chin drop, corner height (eye-to-eye units)"""
    k = {p: POINTS.index(p) for p in FEAT}
    d, W = base64.b64decode(clip["data"]), 2 * len(POINTS)
    s = lambda b: b - 256 if b > 127 else b
    out = []
    for f in range(clip["frames"]):
        g = lambda p, c: s(d[f * W + 2 * k[p] + c]) * STEP
        out.append((g(14, 1) - g(13, 1), g(291, 0) - g(61, 0), -g(13, 1), g(14, 1), g(152, 1), (g(61, 1) + g(291, 1)) / 2))
    return out


def realign(clips, iters=3, tol_s=0.12, weight=4.0):
    """Re-time each clip's sounds on her own mouth (embedded re-estimation): every viseme's typical mouth measures are
    estimated from the current timing over all clips, then each clip's known sequence of sounds is aligned to its mouth
    track by dynamic programming (left to right, each sound at least one frame), kept near the sound's timing from the audio
    (a penalty beyond tol_s). Repeated a few times. Deterministic. Returns the clips with re-timed units (originals kept
    as audio_c0/audio_c1)."""
    feats = [_features(c) for c in clips]
    for c in clips:
        for u in c["units"]:
            u.setdefault("audio_c0", u["c0"]); u.setdefault("audio_c1", u["c1"])
    nf = 6
    for _ in range(iters):
        acc = {}
        for c, F in zip(clips, feats):
            for u in c["units"]:
                for f in range(u["c0"], u["c1"] + 1):
                    acc.setdefault(u["v"], []).append(F[f])
        allv = [x for v in acc.values() for x in v]
        gvar = [max(1e-6, sum((x[i] - sum(y[i] for y in allv) / len(allv)) ** 2 for x in allv) / len(allv)) for i in range(nf)]
        mu = {v: [sum(x[i] for x in xs) / len(xs) for i in range(nf)] for v, xs in acc.items()}
        var = {v: [max(0.25 * gvar[i], sum((x[i] - mu[v][i]) ** 2 for x in xs) / len(xs)) for i in range(nf)] for v, xs in acc.items()}
        for c, F in zip(clips, feats):
            fps = c["fps"]; tol = tol_s * fps
            groups, cur = [], []
            for u in c["units"]:                                  # stretches of speech: sounds closer than 4 frames
                if cur and u["audio_c0"] - cur[-1]["audio_c1"] > 4:
                    groups.append(cur); cur = []
                cur.append(u)
            if cur:
                groups.append(cur)
            for g in groups:
                a = max(0, g[0]["audio_c0"] - int(tol)); b = min(c["frames"] - 1, g[-1]["audio_c1"] + int(tol))
                T, S = b - a + 1, len(g)
                if T < S:
                    continue
                def cost(sidx, f):
                    u = g[sidx]; m, vv = mu[u["v"]], var[u["v"]]
                    e = sum((F[f][i] - m[i]) ** 2 / vv[i] for i in range(nf))
                    lo, hi = u["audio_c0"] - tol, u["audio_c1"] + tol
                    out = (lo - f) if f < lo else (f - hi) if f > hi else 0
                    return e + weight * (out / max(1.0, tol)) ** 2
                INF = float("inf")
                D = [[INF] * S for _ in range(T)]; B = [[0] * S for _ in range(T)]
                D[0][0] = cost(0, a)
                for t in range(1, T):
                    for k in range(min(S, t + 1)):
                        stay, adv = D[t - 1][k], D[t - 1][k - 1] if k else INF
                        if stay <= adv:
                            D[t][k], B[t][k] = stay, k
                        else:
                            D[t][k], B[t][k] = adv, k - 1
                        D[t][k] += cost(k, a + t)
                k, bounds = S - 1, [[None, None] for _ in range(S)]
                for t in range(T - 1, -1, -1):
                    bounds[k][0] = a + t
                    if bounds[k][1] is None:
                        bounds[k][1] = a + t
                    k = B[t][k] if t else k
                for u, (c0, c1) in zip(g, bounds):
                    if c0 is not None:
                        u["c0"], u["c1"] = c0, c1
                        u["p0"], u["p1"] = max(0, c0 - PAD), min(c["frames"] - 1, c1 + PAD)
    return clips


# ------------------------------------------------------------------------------------------------ the library
def build(clips, person, note=""):
    """the library from analysed clips (deterministic: clips are taken in exemplar order)"""
    clips = realign(json.loads(json.dumps(sorted(clips, key=lambda c: (str(c.get("exemplar")), c["frames"])))))
    fps = clips[0]["fps"] if clips else 24
    for c in clips:
        if c["fps"] != fps:
            raise ValueError("all clips of a library must have the same frame rate")
    units = [dict(u, clip=k) for k, c in enumerate(clips) for u in c["units"]]
    counts = {}
    for u in units:
        counts[u["v"]] = counts.get(u["v"], 0) + 1
    return {"kind": "speech-motion", "version": VERSION, "person": person, "note": note, "fps": fps, "step": STEP,
            "points": POINTS, "clips": [{k: c[k] for k in ("exemplar", "script", "frames", "data")} for c in clips], "units": units,
            "coverage": dict(sorted(counts.items())), "method": "her tracked lower-face movement per sound in context (sounds re-timed on her own mouth), joined by Viterbi"}


class Motion:
    """a loaded library, ready to synthesize"""

    def __init__(self, lib):
        self.lib, self.fps, self.K = lib, lib["fps"], len(lib["points"])
        self.data = [base64.b64decode(c["data"]) for c in lib["clips"]]
        self.units = lib["units"]
        self.by_v, self.by_g = {}, {}
        for i, u in enumerate(self.units):
            self.by_v.setdefault(u["v"], []).append(i)
            self.by_g.setdefault(GROUP.get(u["v"], u["v"]), []).append(i)
        self._edge = {}

    def frame(self, clip, f):
        """one frame of a clip: [dx0, dy0, dx1, dy1, …] in quantization steps"""
        d, w = self.data[clip], 2 * self.K
        f = max(0, min(len(d) // w - 1, f))
        return [b - 256 if b > 127 else b for b in d[f * w:(f + 1) * w]]

    def at(self, ui, pos):
        """unit ui at a fractional frame position (clamped to the unit's padded span), linear between frames"""
        u = self.units[ui]
        pos = max(u["p0"], min(u["p1"], pos))
        f0 = int(math.floor(pos)); w = pos - f0
        a = self.frame(u["clip"], f0)
        if w < 1e-6 or f0 + 1 > u["p1"]:
            return [float(x) for x in a]
        b = self.frame(u["clip"], f0 + 1)
        return [x + (y - x) * w for x, y in zip(a, b)]

    def _edges(self, ui):
        e = self._edge.get(ui)
        if e is None:
            u = self.units[ui]
            e = self._edge[ui] = (self.frame(u["clip"], u["c0"]), self.frame(u["clip"], u["c1"]))
        return e

    def choose(self, segs, beam=14):
        """segs: [(viseme, start, end, prev, next)] → the unit chosen for each (None where the library has none)"""
        cands = []
        for v, s, e, pv, nv in segs:
            pool = self.by_v.get(v) or self.by_g.get(GROUP.get(v, v)) or []
            exact = v in self.by_v
            dur = max(0.02, e - s)
            scored = []
            for ui in pool:
                u = self.units[ui]
                tc = (0 if exact else 2.0) + 0.5 * (u["prev"] != pv) + 0.5 * (u["next"] != nv) + 0.6 * abs(math.log(max(0.02, u["dur"]) / dur))
                scored.append((tc, ui))
            scored.sort()
            cands.append(scored[:beam])
        best, back = [], []
        for k, cs in enumerate(cands):
            if not cs:
                best.append([]); back.append([]); continue
            prev = next((j for j in range(k - 1, -1, -1) if best[j]), None)
            row, brow = [], []
            for tc, ui in cs:
                if prev is None or prev != k - 1:
                    row.append(tc); brow.append(None); continue
                u = self.units[ui]
                bc, bj = None, None
                for j, (pc, pui) in enumerate(zip(best[prev], (x[1] for x in cands[prev]))):
                    pu = self.units[pui]
                    if pu["clip"] == u["clip"] and 0 <= u["c0"] - pu["c1"] <= 2:
                        jc = 0.0                                         # they followed each other in her own clip
                    else:
                        a, b = self._edges(pui)[1], self._edges(ui)[0]
                        jc = 0.25 + 0.5 * sum(abs(x - y) for x, y in zip(a, b)) * STEP / len(a) / 0.004
                    if bc is None or pc + jc < bc:
                        bc, bj = pc + jc, j
                row.append(tc + bc); brow.append(bj)
            best.append(row); back.append(brow)
        out = [None] * len(cands)
        k = len(cands) - 1
        j = None
        while k >= 0:
            if not cands[k]:
                k -= 1; j = None; continue
            if j is None:
                j = min(range(len(best[k])), key=lambda i: (best[k][i], i))
            out[k] = cands[k][j][1]
            nj = back[k][j]
            k -= 1
            j = nj if (k >= 0 and nj is not None and cands[k]) else None
        return out

    def synthesize(self, phonemes, duration, fps=30, h=0.04, rest_ramp=0.1):
        """the lower face's movement for new speech: {fps, points, step, n, data (base64 int8 frames), units}"""
        ph = sorted([(x["viseme"], float(x["start_time"]), float(x["end_time"])) for x in phonemes
                     if x.get("viseme") and x["viseme"] != "sil" and float(x["end_time"]) > float(x["start_time"])], key=lambda p: (p[1], p[2]))
        # short gaps inside words and phrases close (no flash of rest between two sounds)
        segs = [list(p) for p in ph]
        for i in range(len(segs) - 1):
            g = segs[i + 1][1] - segs[i][2]
            if 0 < g < 0.15:
                m = (segs[i][2] + segs[i + 1][1]) / 2; segs[i][2] = m; segs[i + 1][1] = m
        vs = [s[0] for s in segs]
        ctx = [(v, s, e, vs[i - 1] if i and segs[i][1] - segs[i - 1][2] < 0.15 else "sil",
                vs[i + 1] if i + 1 < len(vs) and segs[i + 1][1] - e < 0.15 else "sil") for i, (v, s, e) in enumerate(segs)]
        choice = self.choose(ctx)
        n = max(1, int(math.ceil(duration * fps)))
        W = 2 * self.K
        out = bytearray()
        ss = lambda x: 0.0 if x <= 0 else 1.0 if x >= 1 else x * x * (3 - 2 * x)
        for fi in range(n):
            t = fi / fps
            acc, wsum = [0.0] * W, 0.0
            for k, (v, s, e) in enumerate(segs):
                if choice[k] is None:
                    continue
                lead = rest_ramp if ctx[k][3] == "sil" else h
                tail = rest_ramp if ctx[k][4] == "sil" else h
                if t < s - lead or t > e + tail:
                    continue
                w = ss((t - (s - lead)) / (2 * lead) if t < s + lead else 1.0) * ss(((e + tail) - t) / (2 * tail) if t > e - tail else 1.0)
                if ctx[k][3] == "sil" and t < s:
                    w = ss((t - (s - lead)) / lead)
                if ctx[k][4] == "sil" and t > e:
                    w = ss(((e + tail) - t) / tail)
                if w <= 0:
                    continue
                u = self.units[choice[k]]
                pos = u["c0"] + (t - s) * (u["c1"] + 1 - u["c0"]) / max(1e-3, e - s)
                val = self.at(choice[k], pos)
                for q in range(W):
                    acc[q] += w * val[q]
                wsum += w
            if wsum > 1:
                acc = [x / wsum for x in acc]
            # (wsum < 1 only at the edges of pauses: the rest of the weight is her rest, i.e. no movement)
            for x in acc:
                out.append(max(-127, min(127, int(round(x)))) & 0xFF)
        used = sorted({c for c in choice if c is not None})
        follow = sum(1 for k in range(1, len(choice)) if choice[k] is not None and choice[k - 1] is not None
                     and self.units[choice[k]]["clip"] == self.units[choice[k - 1]]["clip"] and 0 <= self.units[choice[k]]["c0"] - self.units[choice[k - 1]]["c1"] <= 2)
        return {"kind": "speech-motion", "person": self.lib.get("person"), "fps": fps, "step": STEP, "points": self.lib["points"],
                "n": n, "data": base64.b64encode(bytes(out)).decode(),
                "units": {"sounds": len(segs), "covered": sum(c is not None for c in choice), "distinct": len(used), "joined_as_recorded": follow}}


# ------------------------------------------------------------------------------------------------ files
def save(lib, path):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lib, f, separators=(",", ":"), sort_keys=True)
    os.replace(tmp, path)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Libraries:
    """the speech motion libraries on this computer (avatars/speech-motion/): each person's analysed clips, the library
    built from them, and which avatars speak with which person's movement"""

    def __init__(self, avatars_folder):
        self.folder = os.path.join(avatars_folder, "speech-motion")
        os.makedirs(self.folder, exist_ok=True)
        self._cache = {}

    @staticmethod
    def slug(person):
        s = "".join(ch if ch.isalnum() else "-" for ch in str(person or "").strip().lower()).strip("-")
        while "--" in s:
            s = s.replace("--", "-")
        if not s:
            raise ValueError("Name the person whose movement this is.")
        return s[:60]

    def _assign_path(self):
        return os.path.join(self.folder, "assign.json")

    def assignments(self):
        try:
            return load(self._assign_path())
        except (OSError, ValueError):
            return {}

    def assign(self, avatar_id, person):
        a = self.assignments()
        if person:
            if not os.path.isfile(self.path(person)):
                raise ValueError("There is no speech motion library for %s yet." % person)
            a[str(int(avatar_id))] = self.slug(person)
        else:
            a.pop(str(int(avatar_id)), None)
        save(a, self._assign_path())
        return {"avatar": int(avatar_id), "person": a.get(str(int(avatar_id)))}

    def path(self, person):
        return os.path.join(self.folder, self.slug(person) + ".json")

    def add_clip(self, person, clip):
        d = os.path.join(self.folder, self.slug(person), "clips")
        os.makedirs(d, exist_ok=True)
        name = "".join(ch for ch in str(clip.get("exemplar") or "clip") if ch.isalnum() or ch in "-_")[:40] or "clip"
        save(clip, os.path.join(d, name + ".json"))
        return {"person": self.slug(person), "clip": name, "units": len(clip["units"]), "frames": clip["frames"]}

    def build(self, person, note=""):
        d = os.path.join(self.folder, self.slug(person), "clips")
        clips = [load(os.path.join(d, f)) for f in sorted(os.listdir(d)) if f.endswith(".json")] if os.path.isdir(d) else []
        if not clips:
            raise ValueError("No analysed clips for %s yet." % person)
        lib = build(clips, str(person), note)
        save(lib, self.path(person))
        self._cache.pop(self.slug(person), None)
        return self.info(person)

    def install(self, src, person):
        """a ready-made library (e.g. the one bundled with the starter avatars)"""
        lib = load(src)
        if lib.get("kind") != "speech-motion":
            raise ValueError("not a speech motion library")
        save(lib, self.path(person))
        self._cache.pop(self.slug(person), None)

    def info(self, person):
        p = self.path(person)
        if not os.path.isfile(p):
            return None
        lib = load(p)
        return {"person": lib.get("person"), "slug": self.slug(person), "clips": len(lib["clips"]), "units": len(lib["units"]),
                "coverage": lib.get("coverage"), "fps": lib["fps"], "version": lib.get("version"), "bytes": os.path.getsize(p),
                "exemplars": [c.get("exemplar") for c in lib["clips"]]}

    def list(self):
        out = []
        for f in sorted(os.listdir(self.folder)):
            if f.endswith(".json") and f != "assign.json":
                i = self.info(f[:-5])
                if i:
                    out.append(i)
        return {"libraries": out, "assignments": self.assignments()}

    def motion_for(self, avatar_id):
        person = self.assignments().get(str(int(avatar_id))) if avatar_id not in (None, "") else None
        if not person or not os.path.isfile(self.path(person)):
            return None
        mt = os.path.getmtime(self.path(person))
        c = self._cache.get(person)
        if not c or c[0] != mt:
            c = self._cache[person] = (mt, Motion(load(self.path(person))))
        return c[1]


# ------------------------------------------------------------------------------------------------ self-test
def _synthetic_clip(seed, vis, fps=24):
    """a made-up face whose jaw opens on 'aa' and closes on 'PP' (for the self-test only)"""
    import random
    rnd = random.Random(seed)
    base = [(300 + 80 * math.cos(i * 0.7) + (i % 7), 300 + 90 * math.sin(i * 1.3) + (i % 5)) for i in range(478)]
    base[33], base[263] = (250.0, 250.0), (350.0, 250.0)
    base[13], base[14] = (300.0, 380.0), (300.0, 381.0)
    frames, phon, t = [], [], 0.2
    for v in vis:
        d = 0.12
        phon.append({"viseme": v, "start_time": t, "end_time": t + d, "symbol": v}); t += d
    n = int((t + 0.3) * fps)
    for f in range(n):
        tt = f / fps
        open_ = next((0.25 if p["viseme"] == "aa" else 0.0 for p in phon if p["start_time"] <= tt < p["end_time"]), 0.0)
        roll = 0.02 * math.sin(f * 0.3)
        fr = []
        for i, (x, y) in enumerate(base):
            if i in (14, 152, 17, 18):
                y += open_ * 100
            x, y = 300 + (x - 300) * math.cos(roll) - (y - 300) * math.sin(roll) + rnd.uniform(-0.05, 0.05), 300 + (x - 300) * math.sin(roll) + (y - 300) * math.cos(roll)
            fr.append((x, y))
        frames.append(fr)
    return frames, phon, fps


def self_test():
    out = []
    ok = lambda n, c: out.append((n, bool(c)))
    clips = []
    for k, vis in enumerate([["PP", "aa", "PP", "aa"], ["aa", "PP", "E"], ["PP", "aa"]]):
        fr, ph, fps = _synthetic_clip(k, vis)
        clips.append(analyse_clip(fr, fps, ph, "ex%d" % k, " ".join(vis)))
    c0 = clips[0]
    ok("a clip becomes sound units with their neighbours", [u["v"] for u in c0["units"]] == ["PP", "aa", "PP", "aa"] and c0["units"][1]["prev"] == "PP")
    lib = build(clips, "Test")
    ok("the library is deterministic", json.dumps(build(list(reversed(clips)), "Test"), sort_keys=True) == json.dumps(lib, sort_keys=True))
    M = Motion(json.loads(json.dumps(lib)))
    k152 = POINTS.index(152)
    u_aa = next(i for i, u in enumerate(M.units) if u["v"] == "aa")
    mid = M.at(u_aa, (M.units[u_aa]["c0"] + M.units[u_aa]["c1"]) / 2)
    ok("the head's own movement is removed (the jaw drop survives the roll)", mid[2 * k152 + 1] * STEP > 0.1 and abs(mid[2 * k152]) * STEP < 0.05)
    phon = [{"viseme": v, "start_time": 0.3 + 0.15 * i, "end_time": 0.45 + 0.15 * i} for i, v in enumerate(["PP", "aa", "PP", "aa"])]
    s1 = M.synthesize(phon, 1.2)
    ok("synthesis is deterministic", s1 == M.synthesize(phon, 1.2))
    d = base64.b64decode(s1["data"]); W = 2 * len(POINTS)
    jaw = lambda t: (lambda b: b - 256 if b > 127 else b)(d[int(t * 30) * W + 2 * k152 + 1]) * STEP
    ok("the new speech opens on aa and closes on PP", jaw(0.525) > 0.15 and jaw(0.375) < 0.05 and jaw(0.675) < 0.08)
    ok("pauses rest", jaw(0.05) == 0 and jaw(1.15) == 0)
    ok("units that followed each other in a clip are kept together", s1["units"]["joined_as_recorded"] >= 2)
    s2 = M.synthesize([{"viseme": "FF", "start_time": 0.2, "end_time": 0.35}], 0.6)
    ok("a sound the library lacks is left to rest, not guessed", s2["units"]["covered"] == 0)
    return out


def qc():
    r = self_test()
    for n, g in r:
        print("  [%s] %s" % ("OK" if g else "FAIL", n))
    print("  %d of %d checks passed" % (sum(g for _, g in r), len(r)))
    return all(g for _, g in r)


if __name__ == "__main__":
    import sys
    sys.exit(0 if qc() else 1)
