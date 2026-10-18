"""Silent questions: read a question from the lips alone, for people who cannot speak aloud.

Reading any sentence from lips is unreliable (lips show about a third of speech). A question to QueryBook is
not any sentence: it follows the patterns QueryBook answers ("how do you say ___ in ___", "what does ___ mean",
"translate ___ to ___"), and its gaps are filled by words QueryBook knows and language names. So each pattern
is matched against the lips part by part (fixed words, then each gap from its own list) with a beam search,
and the best readings are offered for the person to confirm with one click. The learned reader (Teach and
improve) is used when it is switched on, so silent questions get better with use.
"""
import math

import lipread
import visemes
import vocab

TEMPLATES = [
    {"id": "say", "parts": ["how do you say", {"slot": "word"}, "in", {"slot": "language"}], "example": "how do you say house in Spanish"},
    {"id": "mean", "parts": ["what does", {"slot": "word"}, "mean"], "example": "what does river mean"},
    {"id": "translate", "parts": ["translate", {"slot": "word"}, "to", {"slot": "language"}], "example": "translate water to French"},
]

_CACHE = {}


def _classes(text, lang="en", lab=None):
    key = ("c", text, lang)
    if key not in _CACHE:
        wp = visemes._cached_phonemes(lipread.re.findall(r"[^\W\d_]+", text), lang, lab)
        s = "".join(lipread.word_classes(w["phonemes"]) for w in wp)
        _CACHE[key] = "".join(c for i, c in enumerate(s) if i == 0 or s[i - 1] != c)
    return _CACHE[key]


def slot_values(size=400, extra=(), lab=None):
    """The words a gap can hold (most common first, plus any given) and the language names, as mouth-class strings."""
    key = ("v", size, tuple(extra))
    if key in _CACHE:
        return _CACHE[key]
    r = vocab.rank()
    words = list(dict.fromkeys([w.lower() for w in extra if w] + [w for w, _ in sorted(r.items(), key=lambda kv: kv[1]) if w.isalpha() and len(w) > 2][:size]))
    out = {"word": [(w, _classes(w, "en", lab)) for w in words],
           "language": [(v["name"], _classes(v["name"], "en", lab)) for k, v in vocab.LANGUAGES.items()]}
    out["word"] = [(w, c) for w, c in out["word"] if c]
    _CACHE[key] = out
    return out


def _sub_dtw(obs, i, ref, max_extra):
    """Align `ref` against obs starting at i; cost (mean step cost) for each possible end j."""
    n, m = len(obs), len(ref)
    hi = min(n, i + m + max_extra)
    INF = 1e9
    D = [[INF] * (hi - i + 1) for _ in range(m + 1)]
    L = [[0] * (hi - i + 1) for _ in range(m + 1)]
    D[0][0] = 0.0
    for a in range(1, m + 1):
        for b in range(1, hi - i + 1):
            c = lipread._cost(obs[i + b - 1], ref[a - 1])
            best, bl = D[a - 1][b - 1] + c, L[a - 1][b - 1]
            v = D[a][b - 1] + (min(c, lipread.PAUSE) if obs[i + b - 1] == "P" else c)
            if v < best:
                best, bl = v, L[a][b - 1]
            if D[a - 1][b] + c < best:
                best, bl = D[a - 1][b] + c, L[a - 1][b]
            D[a][b], L[a][b] = best, bl + 1
    return {i + b: (D[m][b], m) for b in range(1, hi - i + 1) if D[m][b] < INF}   # cost, and the expected sounds it covered


def decode_word(cls, lab=None, words=(), top=8):
    """Guided mode: the person chose the question and the language by tapping, and mouths only the word."""
    full = "".join(c for c, _ in lipread.runs([c for c in cls if c != "-"], 3))
    obs = full.strip("P")                                # a closed mouth at the edges is rest — or the word's own m / b / p
    if len(obs) < 1:
        return {"seen": obs, "readings": [], "note": "the lips hardly moved"}
    vals = slot_values(extra=tuple(words), lab=lab)["word"]
    groups = {}
    for w, ref in vals:
        groups.setdefault(ref, []).append(w)
    scored = []
    for ref, ws in groups.items():
        if abs(len(ref) - len(obs)) > max(2, len(obs) // 2):
            continue
        variants = {obs, full.lstrip("P") if not ref.startswith("P") else "P" + obs, obs + "P" if ref.endswith("P") else obs}
        c = min(lipread.dtw(v, ref)[0] for v in variants if v)
        scored.append((c, ref, ws))
    scored.sort(key=lambda x: (x[0], x[1]))
    out = [{"word": ws[0], "same_on_lips": ws[1:6], "looks_like": ref, "match": round(1 - c, 3)} for c, ref, ws in scored[:top]]
    return {"seen": obs, "readings": out, "note": "Words that look the same on the lips are listed together — tap the right one."}


def decode(cls, lab=None, words=(), beam=120, top=5, rerank=80):
    """Best readings of a silent question. cls: mouth class per 1/100 s (from lipread.classes_of)."""
    full = "".join(c for c, _ in lipread.runs([c for c in cls if c != "-"], 3))
    if len(full.strip("P")) < 3:
        return {"seen": full, "readings": [], "note": "the lips hardly moved"}
    vals = slot_values(extra=tuple(words), lab=lab)
    finals = []
    # the closed mouth at the start and end is rest, unless the question itself starts or ends with m / b / p
    for obs, tpl in [(full.strip("P") if not _classes(" ".join(p for p in t["parts"] if isinstance(p, str)).split()[0], "en", lab).startswith("P") else "P" + full.strip("P"), t)
                     for t in TEMPLATES]:
        states = [(0.0, 0, 0, [])]                        # (cost, steps, position, chosen slot values)
        for part in tpl["parts"]:
            nxt = []
            for cost, steps, pos, chosen in states:
                if isinstance(part, str):
                    ref = _classes(part, "en", lab)
                    for j, (c, l) in _sub_dtw(obs, pos, ref, 3).items():
                        nxt.append((cost + c, steps + l, j, chosen))
                else:
                    for value, ref in vals[part["slot"]]:
                        if pos + max(1, len(ref) - 2) > len(obs):
                            continue
                        for j, (c, l) in _sub_dtw(obs, pos, ref, 2).items():
                            if abs((j - pos) - len(ref)) <= 2:
                                nxt.append((cost + c, steps + l, j, chosen + [value]))
            nxt.sort(key=lambda s: (s[0] + 0.5 * max(0, s[2] - s[1] * 1.6)) / max(1, s[1]))
            states = nxt[:beam]
        for cost, steps, pos, chosen in states:
            tail = len(obs) - pos                            # unread lips at the end count against the reading
            score = (cost + tail * 0.8) / max(1, steps)      # per expected sound, so pauses between words do not dilute it
            text, k = [], 0
            for part in tpl["parts"]:
                if isinstance(part, str):
                    text.append(part)
                else:
                    text.append(chosen[k]); k += 1
            finals.append((score, " ".join(text), tpl["id"], tuple(chosen)))
    # the pattern search proposes; the whole-utterance agreement (scored against chance) decides
    seen, cands = set(), []
    for score, text, tid, chosen in sorted(finals):
        if text not in seen:
            seen.add(text)
            cands.append((score, text, tid, chosen))
    mates = {}
    for w, ref in vals["word"]:
        mates.setdefault(ref, []).append(w)
    out = []
    core_obs = full.strip("P")
    for score, text, tid, chosen in cands[:rerank]:
        ref = _classes(text, "en", lab)
        whole = min(lipread.dtw(core_obs, ref)[0], lipread.dtw("P" + core_obs, ref)[0] if ref.startswith("P") else 9)
        alts = {w: [m for m in mates.get(_classes(w, "en", lab), []) if m != w][:5] for w in chosen if w not in [l for l, _ in vals["language"]]}
        out.append({"question": text, "pattern": tid, "slots": list(chosen), "same_on_lips": alts, "match": round(1 - (0.7 * whole + 0.3 * score), 3)})
    out.sort(key=lambda r: -r["match"])
    out = out[:top]
    # how sure: the gap between the best reading and the next one that reads differently
    conf = 0.0
    if out:
        second = out[1]["match"] if len(out) > 1 else 0.0
        conf = round(max(0.0, min(1.0, (out[0]["match"] - 0.5) * 2)) * min(1.0, 0.3 + 6 * (out[0]["match"] - second)), 2)
    return {"seen": obs, "readings": out, "confidence": conf,
            "note": "Read from the lips alone, matched to the questions QueryBook answers. Confirm the right one."}
