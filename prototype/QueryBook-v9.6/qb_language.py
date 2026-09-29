#!/usr/bin/env python3
"""
qb_language.py — QueryBook Language Lab: deterministic Sub-Language Priming Layer
(SLPL) + English-learning-from-scratch harvester (stdlib only).

WHAT THIS IS (honest scope)
---------------------------
This is the *deterministic, prototype* realization of the QueryBook Language
Architecture (Bible Chapter [LX] / LEL): the parts of the Sub-Language Priming
Layer that can be COMPUTED from ingested text today, with no external model and
no API key. It learns the STRUCTURE of English from raw text on its own:
grapheme inventory, a rule-seeded phoneme approximation, syllable segmentation,
lexical stability, word co-occurrence density, prosodic proxies, and the
four one-way Transition Gate thresholds. Everything it learns is written into
the shared UFCS store as provenance-tracked Fact Units (domain "language").

WHAT THIS IS NOT (roadmap — do not overclaim)
---------------------------------------------
It is NOT the full neural Language Expression Layer. Word->referent grounding,
emergent semantics, the trained learned-parameter model, and the neural speech
vocoder are the research program (LEL Research Gates A/B/C) and remain roadmap.
The grapheme->phoneme mapping here is RULE-SEEDED (an initial inventory that
seeds learning, per Bible [L02] audit-fix), not a learned G2P. Metrics are
measured structural statistics, not a claim of language understanding.

The developmental sequence is honored: this module operates in Phase 1
(structural-acoustic) — it extracts structure and suppresses semantics. The
Transition Gate must OPEN before Phase 2 (semantic grounding) would begin, and
Phase 2 requires the roadmap engines, so the gate opening here reports
"structural readiness," not comprehension.

State: <store>/language_model.json holds the cumulative counters (the learned
model). It is the source of truth for status; Fact Units are the provenance
trail written into the store.
"""
import json, os, re, math, time, sys, gzip

import ufcs_store as store

# --------------------------------------------------------------------------
# Rule-seeded English phoneme inventory (initial SLPL scaffold, ~44 phonemes).
# Per Bible [L02] audit-fix: structured resources may SEED the inventory; they
# are the starting parameters, not a retained lookup engine. A learned G2P is
# roadmap. Digraphs are tried before single letters (left-to-right, longest
# match). This is an APPROXIMATION for structural measurement, not correct
# pronunciation.
# --------------------------------------------------------------------------
PHONEME_TARGET = 44                     # standard count of English phonemes (~44)
_DIGRAPH = {
    "th": "θ", "sh": "ʃ", "ch": "tʃ", "ph": "f", "wh": "w", "ng": "ŋ", "ck": "k",
    "qu": "kw", "oo": "uː", "ee": "iː", "ea": "iː", "ou": "aʊ", "ow": "aʊ",
    "ai": "eɪ", "ay": "eɪ", "oa": "oʊ", "oi": "ɔɪ", "oy": "ɔɪ", "au": "ɔː",
    "aw": "ɔː", "ir": "ɜː", "er": "ɜː", "ur": "ɜː", "ar": "ɑː", "or": "ɔː",
}
_SINGLE = {
    "a": "æ", "e": "ɛ", "i": "ɪ", "o": "ɒ", "u": "ʌ", "y": "ɪ",
    "b": "b", "c": "k", "d": "d", "f": "f", "g": "g", "h": "h", "j": "dʒ",
    "k": "k", "l": "l", "m": "m", "n": "n", "p": "p", "r": "r", "s": "s",
    "t": "t", "v": "v", "w": "w", "x": "ks", "z": "z",
}
_VOWELS = set("aeiouy")

# Cumulative-model size caps (bound memory; a prototype, not a corpus warehouse).
_CAP_WORDS = 60000
_CAP_BIGRAMS = 200000
_CAP_TRIGRAMS = 200000
_SATURATION_WINDOW = 4000               # W: trigrams considered "recent"

# One-way Transition Gate thresholds (Bible [L08]). Calibratable; these are the
# prototype defaults, clearly labelled as such.
# Prototype calibration of the Transition Gate (Bible [L08] says thresholds are
# calibrated at "Research Gate B"; these are the prototype values the bundled corpus
# can reach over several Phase-1 agent cycles, so English learning can actually finish).
GATE = {
    "phonemic_completeness": 0.80,      # τ1: distinct phonemes / 44
    "lexical_stability":     0.70,      # τ2: top-word overlap between successive ingests
    "cooccurrence_density":  1.50,      # τ3: distinct bigrams / distinct words
    "pattern_saturation":    0.20,      # ε : recent novel-trigram rate must fall BELOW this
}


def _g2p(word):
    """Rule-seeded grapheme->phoneme approximation. Returns a list of phoneme symbols."""
    w = re.sub(r"[^a-z]", "", word.lower())
    out, i, n = [], 0, len(w)
    while i < n:
        pair = w[i:i + 2]
        if len(pair) == 2 and pair in _DIGRAPH:
            out.append(_DIGRAPH[pair]); i += 2; continue
        ch = w[i]
        if ch in _SINGLE:
            out.append(_SINGLE[ch])
        i += 1
    return out


def _syllables(word):
    """Vowel-group heuristic syllable count (deterministic, approximate)."""
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    groups = re.findall(r"[aeiouy]+", w)
    c = len(groups)
    if w.endswith("e") and c > 1:       # silent final 'e'
        c -= 1
    return max(1, c)


def _blank_model():
    return {
        "version": 1, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": [], "ingests": 0,
        "total_tokens": 0, "total_chars": 0,
        "graphemes": {}, "phonemes": {},
        "words": {}, "prev_top": [],   # rolling top-word snapshot for lexical stability
        "bigrams": {},
        "trigram_recent": [], "novel_recent": [],  # rolling window of (was_novel) flags
        "trigrams_seen_count": 0,
        "trigram_keys": {},                     # bounded set: key -> 1
        "sent_count": 0, "sent_len_sum": 0, "sent_len_sq": 0,
        "questions": 0, "exclamations": 0,
        "gate_opened": False, "gate_opened_at": None,
        "history": [],          # gate-metric snapshots over time (capped)
    }


def load_model(store_dir):
    p = os.path.join(store_dir, "language_model.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return _blank_model()


def save_model(store_dir, m):
    os.makedirs(store_dir, exist_ok=True)
    p = os.path.join(store_dir, "language_model.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f)
    os.replace(tmp, p)


def _trim(d, cap):
    """Keep the `cap` highest-count keys (deterministic tie-break by key)."""
    if len(d) <= cap:
        return d
    keep = sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:cap]
    return dict(keep)


def _tokenize(text):
    # sentences by terminal punctuation; words as alphabetic runs (apostrophes kept)
    sents = re.split(r"[.!?]+", text)
    words = re.findall(r"[A-Za-z][A-Za-z']*", text)
    return sents, [w.lower() for w in words]


def analyze_only(text):
    """Compute SLPL metrics for a single text WITHOUT persisting (preview)."""
    m = _blank_model()
    _ingest_into_model(m, text, persist_source=None)
    return metrics(m)


def _ingest_into_model(m, text, persist_source):
    sents, words = _tokenize(text)
    # graphemes + phonemes
    for w in words:
        for ch in re.sub(r"[^a-z]", "", w):
            m["graphemes"][ch] = m["graphemes"].get(ch, 0) + 1
        for ph in _g2p(w):
            m["phonemes"][ph] = m["phonemes"].get(ph, 0) + 1
    # words
    half = m["total_tokens"] < 1  # remember if this is the very first ingest (for stability split)
    for w in words:
        m["words"][w] = m["words"].get(w, 0) + 1
    m["total_tokens"] += len(words)
    m["total_chars"] += sum(len(w) for w in words)
    # bigrams
    for a, b in zip(words, words[1:]):
        m["bigrams"][a + " " + b] = m["bigrams"].get(a + " " + b, 0) + 1
    # trigram novelty (pattern saturation)
    for a, b, c in zip(words, words[1:], words[2:]):
        key = a + " " + b + " " + c
        was_novel = 0 if key in m["trigram_keys"] else 1
        if was_novel and len(m["trigram_keys"]) < _CAP_TRIGRAMS:
            m["trigram_keys"][key] = 1
        m["trigrams_seen_count"] += 1
        m["novel_recent"].append(was_novel)
    # keep the novelty window bounded
    if len(m["novel_recent"]) > _SATURATION_WINDOW:
        m["novel_recent"] = m["novel_recent"][-_SATURATION_WINDOW:]
    # prosody proxies (pre-semantic: structure only)
    for s in sents:
        toks = re.findall(r"[A-Za-z][A-Za-z']*", s)
        if not toks:
            continue
        m["sent_count"] += 1
        m["sent_len_sum"] += len(toks)
        m["sent_len_sq"] += len(toks) * len(toks)
    m["questions"] += text.count("?")
    m["exclamations"] += text.count("!")
    # trim caps
    m["words"] = _trim(m["words"], _CAP_WORDS)
    m["bigrams"] = _trim(m["bigrams"], _CAP_BIGRAMS)
    if persist_source:
        m["ingests"] += 1
        if persist_source not in m["sources"]:
            m["sources"].append(persist_source)


def metrics(m):
    """Derive the measurable SLPL representations + gate verdict from the model."""
    distinct_phon = len(m["phonemes"])
    phon_complete = min(1.0, distinct_phon / PHONEME_TARGET)
    distinct_words = len(m["words"]) or 1
    distinct_bigrams = len(m["bigrams"])
    density = distinct_bigrams / distinct_words
    # lexical stability: overlap of the top words between successive ingests. As more
    # same-language text arrives, the high-frequency words settle and overlap → 1.0.
    prev = set(m.get("prev_top") or [])
    cur_top = [k for k, _ in sorted(m["words"].items(), key=lambda kv: -kv[1])[:40]]
    stability = (len(prev & set(cur_top)) / len(prev)) if prev else 0.0
    novelty = (sum(m["novel_recent"]) / len(m["novel_recent"])) if m["novel_recent"] else 1.0
    # syllable stats over top words (bounded work)
    top_words = [w for w, _ in sorted(m["words"].items(), key=lambda kv: -kv[1])[:500]]
    syl = [_syllables(w) for w in top_words] or [0]
    avg_syl = sum(syl) / len(syl)
    mean_len = (m["sent_len_sum"] / m["sent_count"]) if m["sent_count"] else 0.0
    var = ((m["sent_len_sq"] / m["sent_count"]) - mean_len * mean_len) if m["sent_count"] else 0.0
    checks = {
        "phonemic_completeness": (round(phon_complete, 4), GATE["phonemic_completeness"], phon_complete >= GATE["phonemic_completeness"]),
        "lexical_stability":     (round(stability, 4),     GATE["lexical_stability"],     stability >= GATE["lexical_stability"]),
        "cooccurrence_density":  (round(density, 4),        GATE["cooccurrence_density"],  density >= GATE["cooccurrence_density"]),
        "pattern_saturation":    (round(novelty, 4),        GATE["pattern_saturation"],    novelty < GATE["pattern_saturation"]),
    }
    gate_ready = all(c[2] for c in checks.values())
    # a single 0..100 "% toward Phase 1 complete" (mean of the four normalized metrics)
    def _frac(k, v, thr):
        if k == "pattern_saturation":
            return min(1.0, thr / v) if v > 0 else 1.0   # lower novelty is better
        return min(1.0, v / thr) if thr else 1.0
    gate_progress = round(100.0 * sum(_frac(k, checks[k][0], checks[k][1]) for k in checks) / len(checks), 1)
    return {
        "total_tokens": m["total_tokens"], "distinct_words": len(m["words"]),
        "distinct_phonemes": distinct_phon, "phoneme_target": PHONEME_TARGET,
        "distinct_bigrams": distinct_bigrams, "distinct_graphemes": len(m["graphemes"]),
        "avg_syllables_per_word": round(avg_syl, 3),
        "mean_sentence_len": round(mean_len, 2), "sentence_len_var": round(var, 2),
        "questions": m["questions"], "exclamations": m["exclamations"],
        "sources": list(m["sources"]), "ingests": m["ingests"],
        "gate": {
            "checks": {k: {"value": v[0], "threshold": v[1], "pass": v[2]} for k, v in checks.items()},
            "ready": gate_ready,
            "progress": gate_progress,
            "opened": m.get("gate_opened", False),
            "opened_at": m.get("gate_opened_at"),
            "phase": ("Phase 2 eligible (structural readiness met)" if (gate_ready or m.get("gate_opened"))
                      else "Phase 1 (structural-acoustic) — semantics suppressed"),
        },
        "top_letters": sorted(m["graphemes"].items(), key=lambda kv: -kv[1])[:12],
        "top_phonemes": sorted(m["phonemes"].items(), key=lambda kv: -kv[1])[:12],
        "top_words": sorted(m["words"].items(), key=lambda kv: -kv[1])[:20],
    }


_SRC = ("SRC-LANG", "QueryBook Language Lab (SLPL, deterministic)", "internal-derived", 0.85)


def _store_facts(store_dir, mx):
    """Write the learned structure into the shared UFCS store as Fact Units.
    Aggregate metrics + top inventory. Rule-seeded phonemes carry lower trust."""
    st = store.UFCSStore(store_dir)
    added = 0
    try:
        def put(subj, pred, obj, trust=0.85, src=_SRC):
            nonlocal added
            pkt = store.make_packet(str(subj), str(pred), str(obj), "+", "language", src, trust)
            if st.add(pkt):
                added += 1
        g = mx["gate"]
        put("english", "phoneme_inventory_completeness", g["checks"]["phonemic_completeness"]["value"])
        put("english", "lexical_stability", g["checks"]["lexical_stability"]["value"])
        put("english", "cooccurrence_density", g["checks"]["cooccurrence_density"]["value"])
        put("english", "pattern_saturation_novelty", g["checks"]["pattern_saturation"]["value"])
        put("english", "distinct_words_learned", mx["distinct_words"])
        put("english", "distinct_phonemes_observed", mx["distinct_phonemes"])
        put("english", "avg_syllables_per_word", mx["avg_syllables_per_word"])
        put("english", "mean_sentence_length", mx["mean_sentence_len"])
        if g["opened"]:
            put("english", "transition_gate", "OPEN")
        # top letters (grapheme frequency facts)
        tot = sum(c for _, c in mx["top_letters"]) or 1
        for ch, c in mx["top_letters"]:
            put("english letter %s" % ch, "grapheme_frequency", round(c / tot, 4))
        # rule-seeded phoneme facts (lower trust — labelled rule-seeded, learned G2P is roadmap)
        for ph, c in mx["top_phonemes"]:
            put("english phoneme %s" % ph, "phoneme_rule_seeded", "observed", trust=0.70)
        st.flush()
    finally:
        st.close()
    return added


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def strip_html(html):
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = _TAG.sub(" ", html)
    text = (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"'))
    return _WS.sub(" ", text).strip()


def fetch_text(url, max_bytes=800000, timeout=12):
    """Politely fetch ONE user-chosen page and return extracted text (stdlib)."""
    import urllib.request
    req = urllib.request.Request(url, headers={
        "User-Agent": "QueryBook-LanguageLab/1.0 (+structural language learning; single manual fetch)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(max_bytes)
    enc = "utf-8"
    try:
        ctype = r.headers.get("Content-Type", "")
        m = re.search(r"charset=([\w-]+)", ctype)
        if m:
            enc = m.group(1)
    except Exception:
        pass
    return strip_html(raw.decode(enc, "replace"))


def learn(store_dir, text=None, url=None, source=None):
    """Ingest text (or a fetched URL), update the cumulative model, store Fact Units.
    Returns metrics + how many new facts were written. Deterministic."""
    if url and not text:
        text = fetch_text(url)
        source = source or url
    text = (text or "").strip()
    if not text:
        return {"error": "no text to learn from"}
    source = (source or "pasted text").strip()
    m = load_model(store_dir)
    _ingest_into_model(m, text, persist_source=source)
    mx = metrics(m)
    # one-way gate: latch OPEN the first time structural readiness is met
    if mx["gate"]["ready"] and not m.get("gate_opened"):
        m["gate_opened"] = True
        m["gate_opened_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        mx = metrics(m)
    # append a gate-metric snapshot for the progress view (cap the history)
    g = mx["gate"]["checks"]
    m.setdefault("history", []).append({
        "t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tokens": m["total_tokens"], "words": len(m["words"]),
        "phon": g["phonemic_completeness"]["value"],
        "stab": g["lexical_stability"]["value"],
        "dens": g["cooccurrence_density"]["value"],
        "novel": g["pattern_saturation"]["value"],
        "ready": mx["gate"]["ready"], "opened": m.get("gate_opened", False),
    })
    m["history"] = m["history"][-200:]
    # roll the top-word snapshot forward for the NEXT ingest's stability comparison
    m["prev_top"] = [k for k, _ in sorted(m["words"].items(), key=lambda kv: -kv[1])[:40]]
    save_model(store_dir, m)
    mx["history"] = m["history"]
    added = _store_facts(store_dir, mx)
    mx["chars_ingested"] = len(text)
    mx["facts_written"] = added
    mx["source"] = source
    return mx


def status(store_dir):
    m = load_model(store_dir)
    mx = metrics(m)
    mx["thresholds"] = GATE
    mx["history"] = m.get("history", [])
    return mx


def learned_words(store_dir, n=400):
    """Most-frequent words Phase 1 has actually seen, highest first (for grounding)."""
    m = load_model(store_dir)
    return [w for w, _ in sorted(m["words"].items(), key=lambda kv: -kv[1])[:n]]


# --------------------------------------------------------------------------
# PHASE 2 — DETERMINISTIC SEMANTIC GROUNDING (dictionary + store). NO LLM.
#
# Meaning is attached only from sources QueryBook can point to and audit:
#   (a) a bundled PUBLIC-DOMAIN dictionary (Webster's 1913 / GCIDE), and
#   (b) SELF-GROUNDING — the verified Fact Units a word already appears in.
# An LLM is deliberately LOCKED OUT of this phase: a live "green" API check
# proves the connection works, never that a returned meaning is TRUE, so an
# LLM meaning cannot satisfy the provenance mandate. (A future "suggestor"
# mode may propose meanings that are ACCEPTED only when they agree with the
# dictionary — the dictionary staying the authority. Hook: ground_words(...,
# suggestor=None).)
# --------------------------------------------------------------------------
_DICT = None
# COVENANT: no large language model grounds meaning or asserts a fact in QueryBook
# language understanding (Phases 1-2). This flag ENFORCES that lockout at runtime —
# even a future grounding "suggestor" callable is dropped while it is True. It scopes
# ONLY the grounding path here; LLMs remain permitted elsewhere in non-asserting roles
# (phrasing answers over verified facts; building hypotheses and simulations), where
# nothing an LLM proposes becomes a fact without independent verification. Flip this
# only by an explicit, recorded decision.
LLM_LOCKOUT = True
# Webster's Unabridged Dictionary (1913) is out of copyright / public domain.
DICT_SOURCE = ("SRC-DICT-WEB1913", "Webster's Unabridged Dictionary (1913, public domain)",
               "reference-public-domain", 0.9)
LINK_SOURCE = ("SRC-STORE-LINK", "QueryBook UFCS store (self-grounding)", "internal-derived", 0.85)


def _dict_path():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    for name in ("qb_dict.json.gz", "qb_dict.json"):
        p = os.path.join(base, name)
        if os.path.exists(p):
            return p
    # explicit override
    p = os.environ.get("QB_DICT")
    return p if (p and os.path.exists(p)) else None


def load_dictionary():
    """Load the bundled public-domain dictionary (word -> definition). Cached; stdlib only."""
    global _DICT
    if _DICT is not None:
        return _DICT
    d = {}
    p = _dict_path()
    if p:
        try:
            raw = (gzip.open(p, "rb").read() if p.endswith(".gz") else open(p, "rb").read())
            d = json.loads(raw.decode("utf-8", "ignore"))
        except Exception:
            d = {}
    _DICT = {str(k).lower(): str(v) for k, v in d.items()}
    return _DICT


def dictionary_size():
    return len(load_dictionary())


def ground_words(store_dir, words, use_dictionary=True, use_store=True, max_links=4, suggestor=None):
    """Deterministically ground each word and write the meanings as Fact Units (domain
    'language'). Returns a summary with per-word results. No network, no LLM.

    - dictionary: `english word "<w>" · means · <definition>`  (trust 0.9, source = Webster 1913)
    - store-link: `english word "<w>" · grounded_by_fact · <s p o>`  (from facts the word appears in)

    `suggestor` is an optional callable(word)->str for a FUTURE validated mode; a suggestion is
    accepted ONLY if it agrees with the dictionary. It is None here (LLMs locked out of Phase 2).
    """
    # COVENANT ENFORCED: while the lockout holds, refuse any LLM-backed suggestor outright.
    if LLM_LOCKOUT and suggestor is not None:
        suggestor = None
    D = load_dictionary() if use_dictionary else {}
    st = store.UFCSStore(store_dir)
    grounded, added = [], 0
    try:
        def put(subj, pred, obj, trust, src):
            nonlocal added
            pkt = store.make_packet(str(subj), str(pred), str(obj)[:300], "+", "language", src, trust)
            if st.add(pkt):
                added += 1

        for w in words:
            wl = str(w).lower().strip()
            if not wl or not wl.isalpha() or len(wl) < 2:
                continue
            subj = 'english word "%s"' % wl
            rec = {"word": wl, "definition": None, "source": None, "links": []}

            if use_dictionary and wl in D:
                defn = D[wl].strip()
                if defn:
                    put(subj, "means", defn, 0.9, DICT_SOURCE)
                    rec["definition"] = defn
                    rec["source"] = "Webster's 1913 (public domain)"

            if use_store:
                try:
                    rows, _ = st.search(wl, 0.0, 12)
                except Exception:
                    rows = []
                for s, p, o, t, fp in rows:
                    # link only to REAL-WORLD knowledge facts, never to language bookkeeping
                    if str(s).startswith("english") or p in ("means", "grounded_by_fact",
                                                              "grapheme_frequency", "phoneme_rule_seeded"):
                        continue
                    triple = "%s %s %s" % (s, p, o)
                    put(subj, "grounded_by_fact", triple, min(0.85, float(t or 0.0)), LINK_SOURCE)
                    rec["links"].append({"triple": triple, "trust": round(float(t or 0.0), 3)})
                    if len(rec["links"]) >= max_links:
                        break

            # future validated-suggestor hook: accept ONLY if it matches the dictionary
            if suggestor and rec["definition"]:
                try:
                    sug = (suggestor(wl) or "").strip()
                    if sug and _agrees(sug, rec["definition"]):
                        put(subj, "means_confirmed", sug, 0.9, LINK_SOURCE)
                except Exception:
                    pass

            if rec["definition"] or rec["links"]:
                grounded.append(rec)
        st.flush()
    finally:
        st.close()
    return {"words_in": len(words), "words_grounded": len(grounded),
            "facts_added": added, "dict_entries": len(D), "grounded": grounded}


def _agrees(a, b):
    """Cheap agreement test for the future suggestor gate: meaningful word overlap."""
    stop = {"a", "an", "the", "of", "to", "or", "and", "is", "that", "which", "with", "as"}
    wa = {w for w in re.findall(r"[a-z]+", a.lower()) if w not in stop and len(w) > 2}
    wb = {w for w in re.findall(r"[a-z]+", b.lower()) if w not in stop and len(w) > 2}
    return bool(wa & wb)


# --------------------------------------------------------------------------
# PHASE 3 — DETERMINISTIC MULTILINGUAL DELTA (dictionary-based). NO LLM.
#
# Approximates the Delta Acquisition Model: reuse the English foundation learned
# in Phase 1 and learn ONLY the delta to a second language — the word-to-word
# mapping — from a bundled bilingual dictionary. Deterministic, auditable source,
# no LLM. (The full neural cross-lingual alignment remains the roadmap embodiment.)
# --------------------------------------------------------------------------
_BILING = None
LANG_NAMES = {"es": "Spanish", "fr": "French"}
# NOTE: the bundled bilingual data is a DEMONSTRATION set (MUSE, CC BY-NC 4.0) and is
# to be replaced with a public-domain/permissive bilingual source before commercial use.
BILINGUAL_SOURCE = ("SRC-BILINGUAL-DEMO",
                    "MUSE bilingual dictionary (CC BY-NC 4.0; demo — replace with a "
                    "public-domain/permissive source before commercial use)",
                    "reference-demo", 0.85)


def _biling_path():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    for name in ("qb_bilingual.json.gz", "qb_bilingual.json"):
        p = os.path.join(base, name)
        if os.path.exists(p):
            return p
    p = os.environ.get("QB_BILINGUAL")
    return p if (p and os.path.exists(p)) else None


def load_bilingual():
    """Load the bundled bilingual dictionary {lang: {english: [translations]}}. Cached; stdlib only."""
    global _BILING
    if _BILING is not None:
        return _BILING
    d = {}
    p = _biling_path()
    if p:
        try:
            raw = (gzip.open(p, "rb").read() if p.endswith(".gz") else open(p, "rb").read())
            d = json.loads(raw.decode("utf-8", "ignore"))
        except Exception:
            d = {}
    _BILING = d
    return _BILING


def available_languages():
    return [k for k in load_bilingual().keys() if not k.startswith("_")]


def acquire_language(store_dir, lang="es", words=None, max_words=None):
    """Phase-3 delta: for English words already learned in Phase 1, attach their L2 translation
    from the bundled bilingual dictionary. Reuses the English foundation; learns only the delta.
    Deterministic, NO LLM. Writes english word "w" · translation_<lang> · <tr> Fact Units."""
    B = load_bilingual().get(lang) or {}
    if not B:
        return {"error": "no bilingual data for '%s' (available: %s)" % (lang, ", ".join(available_languages()))}
    if words is None:
        words = learned_words(store_dir, 400)
    if max_words:
        words = words[:max_words]
    st = store.UFCSStore(store_dir)
    added = 0; mapped = []
    pred = "translation_" + lang
    try:
        for w in words:
            wl = str(w).lower().strip()
            trs = B.get(wl)
            if not trs:
                continue
            for tr in trs[:2]:
                if st.add(store.make_packet('english word "%s"' % wl, pred, tr, "+",
                                            "language", BILINGUAL_SOURCE, 0.85)):
                    added += 1
            mapped.append({"word": wl, "translations": trs[:2]})
        st.flush()
    finally:
        st.close()
    return {"lang": lang, "language": LANG_NAMES.get(lang, lang), "words_in": len(words),
            "mapped": len(mapped), "facts_added": added, "sample": mapped[:8]}


def multilingual_status(store_dir):
    """Phase-3 coverage: per-language translation counts against the learned vocabulary."""
    vocab = len(learned_words(store_dir, 400))
    st = store.UFCSStore(store_dir)
    langs = {}
    try:
        if not st.no_fql:
            for lg in available_languages():
                n = st.db.execute("SELECT COUNT(*) FROM nuc WHERE predicate=?",
                                  ("translation_" + lg,)).fetchone()[0]
                langs[lg] = {"language": LANG_NAMES.get(lg, lg), "translations": n}
    except Exception:
        pass
    finally:
        st.close()
    meta = load_bilingual().get("_meta", {})
    return {"vocabulary": vocab, "languages": langs, "available": available_languages(),
            "source": meta.get("source"), "license": meta.get("license"), "note": meta.get("note")}


def grounding_status(store_dir):
    """How much of the Phase-1 vocabulary has been grounded (for the Phase 2 UI)."""
    words = learned_words(store_dir, 400)
    st = store.UFCSStore(store_dir)
    means = links = 0
    samples = []
    try:
        if not st.no_fql:
            means = st.db.execute("SELECT COUNT(*) FROM nuc WHERE predicate='means'").fetchone()[0]
            links = st.db.execute("SELECT COUNT(*) FROM nuc WHERE predicate='grounded_by_fact'").fetchone()[0]
            rows = st.db.execute(
                "SELECT subject, object FROM nuc WHERE predicate='means' ORDER BY rowid DESC LIMIT 8").fetchall()
            samples = [{"word": r[0].replace('english word "', "").rstrip('"'),
                        "definition": r[1]} for r in rows]
    except Exception:
        pass
    finally:
        st.close()
    return {"vocabulary": len(words), "defined": means, "store_links": links,
            "coverage_pct": (round(100.0 * means / len(words), 1) if words else 0.0),
            "dict_entries": dictionary_size(), "samples": samples}


# --------------------------------------------------------------------------
# Bundled public-domain English starter corpus. Lets a Phase-1 Language agent
# drive learning to the Transition Gate with ONE click and NO internet — pangrams
# (broad letter/phoneme coverage), classic public-domain nursery rhymes, and
# common-word sentences. Split into chunks so an agent shows steady progress.
# --------------------------------------------------------------------------
STARTER_CORPUS = [
    # Pangrams — maximize grapheme/phoneme coverage (τ1)
    "The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs. "
    "Sphinx of black quartz, judge my vow. How vexingly quick daft zebras jump! "
    "The five boxing wizards jump quickly. Bright vixens jump; dozy fowl quack.",
    # Phoneme-targeted words: digraphs and vowel teams (th, sh, ch, ph, wh, ng, oo, ee, ea, ou, ow, ai, oa, oi, aw, ir, ar, or)
    "The ship sails on the shore while children chat. The phone rang; the whale sang a long song. "
    "The moon and the trees stand near the sea. A house on the cow path saw rain in the day. "
    "The boat found a coin; the boy heard a saw. A bird with fur sat in a car by the door.",
    # Nursery rhymes (public domain) — rhythm, prosody, repetition
    "Twinkle, twinkle, little star, how I wonder what you are. Up above the world so high, "
    "like a diamond in the sky. Jack and Jill went up the hill to fetch a pail of water. "
    "Jack fell down and broke his crown, and Jill came tumbling after.",
    "Mary had a little lamb, its fleece was white as snow. And everywhere that Mary went, "
    "the lamb was sure to go. Humpty Dumpty sat on a wall. Humpty Dumpty had a great fall. "
    "The itsy bitsy spider climbed up the water spout.",
    # Common-word sentences — high-frequency function words for lexical stability (τ2) and density (τ3)
    "The cat sat on the mat and the dog ran to the park. She sells sea shells by the sea shore. "
    "We can go to the shop when the sun comes up. They will read a book and write a note. "
    "I like to run and jump and play. He said that this is the way we do it.",
    "People use words to share what they think and feel. A child learns to hear sounds, then say "
    "words, then read and write them. Water flows to the river and the rain falls on the plain. "
    "Time and light and sound move through the air around us every day.",
    "Phonics teaches the sounds that letters make in words. Every language has its own set of "
    "sounds and rules. When we speak, we join sounds into words and words into sentences. "
    "Grammar is the pattern that holds the words of a sentence together in order.",
]


def corpus_chunk(i):
    """Return the i-th starter-corpus chunk (cycling)."""
    return STARTER_CORPUS[i % len(STARTER_CORPUS)]


# The documented developmental phases (Bible LEL chapter). "built" phases run in
# this prototype; "roadmap" phases require engines that are spec-only, so their
# agents refuse rather than fabricate.
LANGUAGE_PHASES = [
    {"n": 1, "key": "structural", "agent_kind": "language", "status": "built",
     "name": "Structural priming (SLPL + Phase 1)",
     "desc": "Learn the STRUCTURE of English from raw text — grapheme inventory, rule-seeded "
             "phonemes, syllables, lexical stability, co-occurrence, prosody. Semantics are "
             "suppressed. Advances the four Transition Gate thresholds."},
    {"n": 2, "key": "semantic", "agent_kind": "lang_semantic", "status": "built",
     "name": "Semantic grounding (Phase 2) — dictionary + store",
     "desc": "Grounds Phase-1 words to meanings QueryBook can point to: a bundled PUBLIC-DOMAIN "
             "dictionary (Webster's 1913) writes `means` facts, and self-grounding links each word to "
             "the verified Fact Units it already appears in. Fully deterministic, no internet, NO LLM "
             "— every meaning carries an auditable source. (LLMs are locked out of this phase; a future "
             "'suggestor' mode may propose meanings that are accepted only when they match the "
             "dictionary.)"},
    {"n": 3, "key": "multilingual", "agent_kind": "lang_multilingual", "status": "built",
     "name": "Multilingual delta (Phase 3) — dictionary delta",
     "desc": "Deterministic approximation of the Delta Acquisition Model: reuse the English "
             "foundation from Phase 1 and learn only the DELTA to a second language (the word "
             "mapping) from a bundled bilingual dictionary, stored as translation Fact Units. "
             "No LLM, no internet. Set the agent target to a language code (es, fr). The full "
             "neural cross-lingual alignment remains the roadmap embodiment; the bundled "
             "bilingual data is a demo set to be replaced with a public-domain source."},
    {"n": 4, "key": "speech", "agent_kind": "lang_speech", "status": "roadmap",
     "name": "Speech output (Phase 4)",
     "desc": "Render meaning to speech through the seven-stage pipeline (G2P → coarticulation → "
             "prosody → vocoder). Requires the neural speech engine (spec-only)."},
]


def phases(store_dir):
    """Phase catalog + the current structural status/gate, for the Language Lab page."""
    return {"phases": LANGUAGE_PHASES, "status": status(store_dir)}


# Curated seed sources for the Language Lab (structural / sub-language material).
# These are SUGGESTIONS the user can fetch; QueryBook does not auto-crawl them.
SEED_SOURCES = [
    {"name": "English phonology (overview)", "url": "https://en.wikipedia.org/wiki/English_phonology",
     "kind": "phonology", "note": "Phoneme inventory, syllable structure — seeds τ1."},
    {"name": "English phonemic chart / IPA", "url": "https://en.wikipedia.org/wiki/Help:IPA/English",
     "kind": "phonetics", "note": "Grapheme→phoneme correspondences."},
    {"name": "Phonics (letter–sound rules)", "url": "https://en.wikipedia.org/wiki/Phonics",
     "kind": "phonics", "note": "Sub-language sound structure."},
    {"name": "Most common English words", "url": "https://en.wikipedia.org/wiki/Most_common_words_in_English",
     "kind": "lexicon", "note": "Seeds lexical stability (τ2)."},
    {"name": "English grammar", "url": "https://en.wikipedia.org/wiki/English_grammar",
     "kind": "grammar", "note": "Co-occurrence & structure (τ3)."},
    {"name": "Syllable", "url": "https://en.wikipedia.org/wiki/Syllable",
     "kind": "prosody", "note": "Syllable segmentation reference."},
    {"name": "Prosody (linguistics)", "url": "https://en.wikipedia.org/wiki/Prosody_(linguistics)",
     "kind": "prosody", "note": "Rhythm/intonation — pre-semantic contours."},
    {"name": "International Phonetic Alphabet", "url": "https://en.wikipedia.org/wiki/International_Phonetic_Alphabet",
     "kind": "phonetics", "note": "Phonetic symbol inventory."},
    {"name": "English orthography", "url": "https://en.wikipedia.org/wiki/English_orthography",
     "kind": "phonics", "note": "Spelling→sound correspondences (seeds G2P)."},
    {"name": "Morphology (linguistics)", "url": "https://en.wikipedia.org/wiki/Morphology_(linguistics)",
     "kind": "grammar", "note": "Word-formation structure."},
    {"name": "Function word", "url": "https://en.wikipedia.org/wiki/Function_word",
     "kind": "lexicon", "note": "High-frequency closed-class words (lexical stability)."},
    {"name": "English verbs", "url": "https://en.wikipedia.org/wiki/English_verbs",
     "kind": "grammar", "note": "Inflection and conjugation patterns."},
    {"name": "Vowel", "url": "https://en.wikipedia.org/wiki/Vowel",
     "kind": "phonetics", "note": "Vowel space — completes the phoneme inventory (τ1)."},
    {"name": "Consonant", "url": "https://en.wikipedia.org/wiki/Consonant",
     "kind": "phonetics", "note": "Consonant inventory — completes τ1."},
    {"name": "Stress (linguistics)", "url": "https://en.wikipedia.org/wiki/Stress_(linguistics)",
     "kind": "prosody", "note": "Lexical/sentence stress patterns."},
]


def main():
    import sys
    if len(sys.argv) < 2:
        print("usage: python qb_language.py <store> [--url URL | --file PATH | \"text\"]"); return
    sd = sys.argv[1]
    if "--url" in sys.argv:
        res = learn(sd, url=sys.argv[sys.argv.index("--url") + 1])
    elif "--file" in sys.argv:
        p = sys.argv[sys.argv.index("--file") + 1]
        res = learn(sd, text=open(p, encoding="utf-8", errors="replace").read(), source=os.path.basename(p))
    elif len(sys.argv) >= 3:
        res = learn(sd, text=sys.argv[2], source="cli text")
    else:
        res = status(sd)
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
