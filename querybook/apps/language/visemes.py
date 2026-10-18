"""Mouth shapes (visemes) for speech — what the lips do, when.

A viseme is the visible mouth shape of one or more sounds (p, b and m all close the lips, so they
share one). This module turns words + their audio into a timed viseme track that drives the
talking face and can be exported to animation tools:

    1. pronunciation — each word's sounds (IPA), from espeak-ng when installed, else the builder's rules
    2. timing        — exact word times when Speech-to-Text gave them; otherwise each word is placed
                       inside the measured stretches of speech, and every vowel is pulled to the
                       nearest measured syllable peak (a light forced alignment)
    3. shapes        — every sound mapped to one of 15 standard visemes (the Oculus / Meta set, used by
                       Unity, Unreal and Blender add-ons), plus a jaw-opening curve from the loudness

Exports: JSON (everything), CSV, and Rhubarb Lip Sync's TSV (mouth shapes A–H, X) which many
2D animation tools read. Deterministic: the same text and audio always give the same track.
"""
import re

import speech
import voicedsp

VISEMES = ["sil", "PP", "FF", "TH", "DD", "kk", "CH", "SS", "nn", "RR", "aa", "E", "I", "O", "U"]
DESCRIBE = {"sil": "rest", "PP": "lips pressed (p b m)", "FF": "lower lip to teeth (f v)", "TH": "tongue between teeth (th)",
            "DD": "tongue behind teeth (t d)", "kk": "back of tongue (k g ng)", "CH": "lips forward (ch j sh zh)",
            "SS": "teeth close (s z)", "nn": "tongue up (n l)", "RR": "lips slightly rounded (r)", "aa": "jaw open (a)",
            "E": "mouth spread, half open (e)", "I": "spread, nearly closed (ee)", "O": "rounded open (o)", "U": "small round (oo w)"}
# Rhubarb Lip Sync mouth shapes, for 2D tools: A closed (MBP), B slightly open (most consonants), C open (EH/AE),
# D wide open (AA), E rounded (AO/ER), F puckered (UW/OW/W), G teeth on lip (F/V), H tongue (L), X rest
RHUBARB = {"sil": "X", "PP": "A", "FF": "G", "TH": "H", "DD": "B", "kk": "B", "CH": "B", "SS": "B", "nn": "H", "RR": "E",
           "aa": "D", "E": "C", "I": "B", "O": "E", "U": "F"}

_MAP = [("tʃ", "CH"), ("dʒ", "CH"), ("ts", "SS"), ("dz", "SS")] + [(c, v) for v, cs in {
    "PP": "pbmɸβ", "FF": "fvʋɱ", "TH": "θð", "DD": "tdʈɖ", "kk": "kgŋɡxɣqχʔh", "CH": "ʃʒɕʑçʝ", "SS": "sz",
    "nn": "nlɲɫʎɭ", "RR": "rɹɾʁʀɻ", "aa": "aɑæʌɐɒ", "E": "eɛəɜøœɘɵ", "I": "iɪyʏɨj", "O": "oɔɤ", "U": "uʊwɯʉ"}.items() for c in cs]
_VOWEL_V = {"aa", "E", "I", "O", "U"}
_SKIP = set("ˈˌ.ːˑ‿͡|‖ ()-/123456789")
WEIGHT = {"vowel": 1.0, "long": 1.5, "cons": 0.6}      # tuned on measured word timings (mean error about 60 ms)
WORD_BASE = 1.0          # extra weight per word (time a word takes regardless of its sounds)
DEFAULT_WEIGHT, DEFAULT_WORD_BASE = dict(WEIGHT), WORD_BASE   # the learner (lipcoach.py) may tune WEIGHT and WORD_BASE


def phonemes(ipa):
    """IPA string → [(symbol, viseme, weight)], affricates kept together, stress and length marks absorbed."""
    s = re.sub(r"\((\w+)\)", "", ipa or "")          # espeak language-switch marks like (en)
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch in _SKIP:
            if ch == "ː" and out:
                p, v, w = out[-1]
                out[-1] = (p + "ː", v, WEIGHT["long"] if v in _VOWEL_V else w)
            i += 1
            continue
        hit = None
        for sym, v in _MAP:
            if s.startswith(sym, i):
                hit = (sym, v)
                break
        if hit:
            out.append((hit[0], hit[1], WEIGHT["vowel"] if hit[1] in _VOWEL_V else WEIGHT["cons"]))
            i += len(hit[0])
        else:
            i += 1                                     # diacritic or unknown symbol: no mouth shape of its own
    return out


def word_phonemes(words, lang="en", lab=None):
    """Pronunciation of every word: espeak-ng when installed (one batched call), else the builder's rules."""
    import vocab
    voice = vocab.LANGUAGES.get(lang, {}).get("espeak", "en-us" if lang == "en" else lang)
    ipas = speech.ipa_many([w.lower() for w in words], voice) if speech.find_espeak() and words else [None] * len(words)
    out = []
    for w, ipa in zip(words, ipas):
        src = "espeak-ng"
        if not ipa and lab is not None:
            ipa, src = (lab.analyze_pronunciation(w.lower(), lang) or {}).get("ipa") or "", "rules"
        ph = phonemes(ipa or "")
        if not ph:                                     # last resort: letters
            ph = phonemes(re.sub(r"[^a-z]", "", w.lower())); src = "letters"
        out.append({"word": w, "ipa": ipa, "source": src, "phonemes": ph})
    return out


def _speech_spans(m):
    hop = m["contour"]["hop_s"]
    spans = [(s["from_s"], s["to_s"]) for s in m["segments"]]
    if not spans:
        return [(0.0, m["duration_s"])]
    # join stretches separated by less than 120 ms (stop closures inside a word, not pauses)
    joined = [list(spans[0])]
    for a, b in spans[1:]:
        if a - joined[-1][1] < 0.12:
            joined[-1][1] = b
        else:
            joined.append([a, b])
    return [(a, b + hop) for a, b in joined]


def _word_bounds_by_syllables(words, peaks, a, b, db, hop):
    """Word boundaries inside one stretch of speech: give each word as many measured syllable peaks as it has
    vowels, and cut at the quietest moment between the last peak of one word and the first of the next."""
    vc = [max(1, sum(1 for p in w["phonemes"] if p[1] in _VOWEL_V)) for w in words]
    V, N = sum(vc), len(peaks)
    if len(words) == 1:
        return [a, b]
    if N < 2 or abs(N - V) > max(1, int(0.25 * V)):
        return None
    # map vowel k (of V) to peak round(k * (N-1)/(V-1))
    pos = [peaks[min(N - 1, int(round(k * (N - 1) / max(1, V - 1))))] for k in range(V)]
    bounds, k = [a], 0
    for w_i in range(len(words) - 1):
        k += vc[w_i]
        left, right = pos[k - 1], pos[k]
        if right <= left:
            cut = (left + right) / 2
        else:
            i0, i1 = int(left / hop) + 1, max(int(left / hop) + 2, int(right / hop))
            seg = db[i0:i1] or [0]
            cut = (i0 + min(range(len(seg)), key=lambda j: seg[j])) * hop + hop / 2
        bounds.append(max(bounds[-1] + 0.02, min(b - 0.02, cut)))
    bounds.append(b)
    return bounds


def _cut_level(bounds, db, hop):
    inner = bounds[1:-1]
    if not inner:
        return 0.0
    return sum(db[min(len(db) - 1, int(c / hop))] for c in inner) / len(inner)


def _snap(bounds, db, hop, reach):
    """Move each inner boundary to the quietest frame within ±reach seconds."""
    out = [bounds[0]]
    for c in bounds[1:-1]:
        i0, i1 = max(0, int((c - reach) / hop)), min(len(db), int((c + reach) / hop) + 1)
        if i1 > i0:
            j = min(range(i0, i1), key=lambda q: db[q])
            c = j * hop + hop / 2
        out.append(max(out[-1] + 0.02, c))
    out.append(max(out[-1] + 0.01, bounds[-1]))
    return out


def _partition(wts, spans):
    """Split the words (in order) into one group per stretch of speech so that each group's expected length
    best matches its stretch's measured length. Dynamic programming; a stretch may get no word (a cough)."""
    n, k = len(wts), len(spans)
    if n == 0:
        return [[] for _ in spans]
    total_t = sum(b - a for a, b in spans)
    rate = total_t / (sum(wts) or 1.0)                     # seconds per unit of sound weight
    pre = [0.0]
    for w in wts:
        pre.append(pre[-1] + w)
    INF = float("inf")
    best = [[INF] * (n + 1) for _ in range(k + 1)]
    back = [[0] * (n + 1) for _ in range(k + 1)]
    best[0][0] = 0.0
    for j in range(1, k + 1):
        dur = spans[j - 1][1] - spans[j - 1][0]
        for i in range(0, n + 1):
            for h in range(0, i + 1):                      # words h..i-1 go into stretch j
                if best[j - 1][h] == INF:
                    continue
                exp = (pre[i] - pre[h]) * rate
                c = best[j - 1][h] + ((exp - dur) ** 2 if i > h else (dur ** 2) * 4)   # an empty stretch costs more
                if c < best[j][i]:
                    best[j][i], back[j][i] = c, h
    groups, i = [], n
    for j in range(k, 0, -1):
        h = back[j][i]
        groups.append(list(range(h, i))); i = h
    return list(reversed(groups))


_CACHE = {}


def _measured(wav):
    """voicedsp.measure, remembered for the last few clips (the learner re-aligns the same clip many times)."""
    import hashlib
    k = ("m", hashlib.sha1(wav).hexdigest())
    if k not in _CACHE:
        if len(_CACHE) > 64:
            _CACHE.clear()
        _CACHE[k] = voicedsp.measure(wav)
    return _CACHE[k]


def _cached_phonemes(words, lang, lab):
    """Pronunciations (remembered), re-weighted with the current WEIGHT so tuned weights take effect."""
    k = ("w", tuple(words), lang)
    if k not in _CACHE:
        _CACHE[k] = word_phonemes(words, lang, lab)
    out = []
    for w in _CACHE[k]:
        ph = [(sym, v, WEIGHT["long"] if (v in _VOWEL_V and sym.endswith("ː")) else WEIGHT["vowel"] if v in _VOWEL_V else WEIGHT["cons"])
              for sym, v, _ in w["phonemes"]]
        out.append(dict(w, phonemes=ph))
    return out


def align(text, wav, lang="en", lab=None, word_times=None):
    """Timed visemes for `text` spoken in `wav`. word_times: optional [{word, start_s, end_s}] (e.g. Speech-to-Text)."""
    words = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)?", text or "", re.UNICODE)
    m = _measured(wav)
    dur = m["duration_s"]
    wp = _cached_phonemes(words, lang, lab)
    timed, method = [], ""
    if word_times and len(word_times) >= max(1, len(words) // 2):
        method = "word times from speech recognition"
        wt = list(word_times)
        for k, w in enumerate(wp):
            t = wt[min(k, len(wt) - 1)]
            timed.append((w, float(t["start_s"]), float(t["end_s"])))
    else:
        method = "words fitted to the measured stretches of speech (dynamic programming); vowels pulled to measured syllable peaks"
        spans = _speech_spans(m)
        wts = [(sum(p[2] for p in w["phonemes"]) or 0.5) + WORD_BASE for w in wp]
        groups = _partition(wts, spans)
        hop_ = m["contour"]["hop_s"]
        dbs = m["contour"]["db"]
        nuc = [i * hop_ for i in m["contour"]["nuclei"]]
        for (a_, b_), idx in zip(spans, groups):
            if not idx:
                continue
            tot = sum(wts[i] for i in idx)
            t, prop = a_, [a_]
            for i in idx:
                t += (b_ - a_) * wts[i] / tot
                prop.append(t)
            prop = _snap(prop, dbs, hop_, 0.08)
            syl = _word_bounds_by_syllables([wp[i] for i in idx], [x for x in nuc if a_ <= x <= b_], a_, b_, dbs, hop_)
            # keep whichever puts the word boundaries in quieter moments (real word joins are dips in loudness)
            bounds = syl if syl is not None and _cut_level(syl, dbs, hop_) < _cut_level(prop, dbs, hop_) - 1.0 else prop
            for n_, i in enumerate(idx):
                timed.append((wp[i], bounds[n_], bounds[n_ + 1]))
    # phonemes inside each word, proportional to weight
    hop = m["contour"]["hop_s"]
    peaks = [i * hop for i in m["contour"]["nuclei"]]
    ph_rows = []
    for w, a, b in timed:
        tot = sum(p[2] for p in w["phonemes"]) or 1.0
        t = a
        for sym, v, wt in w["phonemes"]:
            d = (b - a) * wt / tot
            ph_rows.append({"p": sym, "v": v, "start": round(t, 3), "end": round(t + d, 3), "word": w["word"]})
            t += d
    if not word_times and peaks:
        # pull each vowel's centre toward the nearest syllable peak inside its word (at most 120 ms), keep order
        for r in ph_rows:
            if r["v"] in _VOWEL_V:
                c = (r["start"] + r["end"]) / 2
                near = min(peaks, key=lambda p: abs(p - c))
                if abs(near - c) <= 0.12:
                    sh = (near - c) * 0.7
                    r["start"] = round(r["start"] + sh, 3); r["end"] = round(r["end"] + sh, 3)
        for k in range(1, len(ph_rows)):                           # repair overlaps
            if ph_rows[k]["start"] < ph_rows[k - 1]["end"]:
                mid = round((ph_rows[k]["start"] + ph_rows[k - 1]["end"]) / 2, 3)
                ph_rows[k - 1]["end"] = ph_rows[k]["start"] = min(mid, ph_rows[k]["end"] - 0.005)
        for k, r in enumerate(ph_rows):                            # keep every sound in order and at least 5 ms long
            if k:
                r["start"] = max(r["start"], ph_rows[k - 1]["end"])
            r["end"] = round(min(dur, max(r["end"], r["start"] + 0.005)), 3)
            r["start"] = min(r["start"], r["end"])
    # viseme track with rests in the gaps
    vis, last = [], 0.0
    for r in ph_rows:
        if r["start"] - last > 0.05:
            vis.append({"v": "sil", "start": round(last, 3), "end": r["start"]})
        if vis and vis[-1]["v"] == r["v"] and abs(vis[-1]["end"] - r["start"]) < 0.02:
            vis[-1]["end"] = r["end"]
        else:
            vis.append({"v": r["v"], "start": r["start"], "end": r["end"]})
        last = r["end"]
    if dur - last > 0.02:
        vis.append({"v": "sil", "start": round(last, 3), "end": round(dur, 3)})
    # jaw opening at 100 per second from loudness (0 closed … 1 wide), smoothed
    db = m["contour"]["db"]
    lo, hi = sorted(db)[len(db) // 10] if db else -60, max(db) if db else 0
    raw = [max(0.0, min(1.0, (d - lo - 6) / max(6.0, hi - lo - 6))) for d in db]
    jaw, k = [], 0.0
    for i in range(int(dur * 100)):
        x = raw[min(len(raw) - 1, int(i / 100.0 / hop))] if raw else 0.0
        k = 0.6 * k + 0.4 * x
        jaw.append(round(k, 3))
    words_out = [{"word": w["word"], "start": round(a, 3), "end": round(b, 3), "ipa": w["ipa"], "pronunciation_from": w["source"]} for w, a, b in timed]
    return {"duration": dur, "method": method, "words": words_out, "phonemes": ph_rows, "visemes": vis, "jaw_fps": 100, "jaw": jaw,
            "viseme_set": "Oculus/Meta 15 (sil PP FF TH DD kk CH SS nn RR aa E I O U)"}


def rhubarb_tsv(track):
    rows, last = [], None
    for v in track["visemes"]:
        s = RHUBARB[v["v"]]
        if s != last:
            rows.append("%.2f\t%s" % (v["start"], s)); last = s
    rows.append("%.2f\tX" % track["duration"])
    return "\n".join(rows) + "\n"


def csv_text(track):
    out = ["start_s,end_s,viseme,description,word,phoneme"]
    for p in track["phonemes"]:
        out.append("%.3f,%.3f,%s,%s,%s,%s" % (p["start"], p["end"], p["v"], DESCRIBE[p["v"]].replace(",", ";"), p["word"].replace(",", ""), p["p"]))
    return "\n".join(out) + "\n"
