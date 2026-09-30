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
LANG_NAMES = {"en": "English", "es": "Spanish", "fr": "French", "de": "German",
              "pt": "Portuguese", "it": "Italian", "sv": "Swedish", "nl": "Dutch"}
# Languages the bundled OS phonemizer (espeak-ng) can PRONOUNCE deterministically (Phase 4).
# Translation (Phase 3) is a separate capability that needs a licensed bilingual lexicon per
# language: es and fr ship with bundled data; de/pt/it/sv/nl register here and activate their
# translation the moment their lexicon is added (no fabricated dictionaries — covenant C2).
SPEAKABLE = {"en", "es", "fr", "de", "pt", "it", "sv", "nl"}
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


# --------------------------------------------------------------------------
# PHASE 4 — SPEECH (two parts, both honest):
#   4a  DETERMINISTIC ANALYSIS (no dependency): rule-seeded G2P phonemes, syllable
#       split, a heuristic stress pattern, and a punctuation-based prosody contour,
#       stored as provenance-tracked Fact Units. Always runs. No LLM.
#   4b  REAL SPEECH (optional): render text to audio with the OS's BUILT-IN TTS —
#       Windows SAPI (System.Speech), macOS `say`, Linux `espeak-ng`/`espeak` — via
#       subprocess, no pip dependency. If no engine is present it reports that
#       plainly and NEVER fabricates audio.
# --------------------------------------------------------------------------
SPEECH_SOURCE = ("SRC-G2P", "QueryBook rule-seeded G2P / prosody (approximate)", "internal-derived", 0.70)

# Vowel nuclei used to count syllables in an IPA string (approximate, deterministic).
_IPA_VOWELS = set("iyɨʉɯuɪʏʊeøɘɵɤoəɛœɜɞʌɔæɐaɶɑɒ")


def _espeak_exe():
    """Locate espeak-ng/espeak — the deterministic multilingual phonemizer and voice — even
    when it is not on PATH (common on Windows, where the installer uses Program Files)."""
    import shutil, os as _os
    for name in ("espeak-ng", "espeak"):
        p = shutil.which(name)
        if p:
            return p
    for c in (r"C:\Program Files\eSpeak NG\espeak-ng.exe",
              r"C:\Program Files (x86)\eSpeak NG\espeak-ng.exe",
              "/opt/homebrew/bin/espeak-ng", "/usr/local/bin/espeak-ng"):
        if _os.path.exists(c):
            return c
    return None


def _espeak_source(lang):
    """Provenance for a pronunciation derived from the OS phonemizer. espeak-ng is a fixed,
    auditable external tool (same class of source as the English rule-seeded G2P), not an LLM."""
    return ("SRC-ESPEAK-%s" % lang.upper(),
            "espeak-ng grapheme-to-phoneme (%s, deterministic IPA)" % LANG_NAMES.get(lang, lang),
            "external-tool", 0.75)


def _ipa_espeak(word, lang):
    """Deterministic IPA for a word via espeak-ng --ipa. Returns (ipa, stress_syllable,
    syllable_count) or (None, 1, 1) when no engine is present. No LLM; never fabricates."""
    import subprocess
    exe = _espeak_exe()
    if not exe:
        return (None, 1, 1)
    try:
        out = subprocess.run([exe, "-v", lang, "--ipa", "-q", str(word)],
                             timeout=15, check=True, capture_output=True, text=True).stdout
    except Exception:
        return (None, 1, 1)
    ipa = out.strip().replace("\n", " ").strip()
    if not ipa:
        return (None, 1, 1)
    nuclei = [i for i, c in enumerate(ipa) if c in _IPA_VOWELS]
    syl = max(1, len(nuclei))
    stress = 1
    mark = ipa.find("ˈ")                    # espeak marks primary stress with U+02C8
    if mark >= 0 and nuclei:
        stress = min(max(1, 1 + sum(1 for n in nuclei if n < mark)), syl)
    return (ipa, stress, syl)


def speakable_languages():
    """Languages Phase 4 can pronounce/voice deterministically via the OS engine."""
    return sorted(SPEAKABLE)


def _stress_pattern(word):
    """Heuristic primary-stress syllable (1-indexed). Approximate, deterministic."""
    w = re.sub(r"[^a-z]", "", word.lower())
    n = _syllables(w)
    if n <= 1:
        return 1, n
    for suf, back in (("tion", 1), ("sion", 1), ("ic", 1), ("ity", 2), ("ical", 2), ("logy", 2)):
        if w.endswith(suf):
            return max(1, n - back), n            # stress falls before the suffix
    if w.endswith(("ate", "ize", "ise")) and n >= 3:
        return max(1, n - 2), n
    return 1, n                                    # default: initial stress


def _prosody(text):
    """Sentence-level intonation contour from punctuation (declarative/interrogative/exclamatory)."""
    t = text.strip()
    if t.endswith("?"):
        return "rising (interrogative)"
    if t.endswith("!"):
        return "emphatic fall (exclamatory)"
    return "falling (declarative)"


# --------------------------------------------------------------------------
# BUNDLED rule-seeded grapheme-to-phoneme for the non-English languages, so
# pronunciation works with NO external engine (exactly like the English G2P).
# espeak-ng, when installed, is preferred for accuracy and provides audio; these
# rule tables are the always-available fallback. Approximate and deterministic —
# the same honesty level as the English rule-seeded G2P. No LLM.
# --------------------------------------------------------------------------
def _R(pairs):
    return [(re.compile(p), ipa) for p, ipa in pairs]

G2P_RULES = {
    "es": _R([(r"ch","tʃ"),(r"ll","ʝ"),(r"rr","r"),(r"qu(?=[eiéí])","k"),(r"gu(?=[eiéí])","ɡ"),
              (r"gü","ɡw"),(r"c(?=[eiéí])","θ"),(r"g(?=[eiéí])","x"),(r"á","a"),(r"é","e"),(r"í","i"),
              (r"ó","o"),(r"ú","u"),(r"ü","u"),(r"ñ","ɲ"),(r"a","a"),(r"e","e"),(r"i","i"),(r"o","o"),
              (r"u","u"),(r"b","b"),(r"c","k"),(r"d","d"),(r"f","f"),(r"g","ɡ"),(r"h",""),(r"j","x"),
              (r"k","k"),(r"l","l"),(r"m","m"),(r"n","n"),(r"p","p"),(r"q","k"),(r"r","ɾ"),(r"s","s"),
              (r"t","t"),(r"v","b"),(r"w","w"),(r"x","ks"),(r"y","ʝ"),(r"z","θ")]),
    "it": _R([(r"ch","k"),(r"gh","ɡ"),(r"gl(?=i)","ʎ"),(r"gn","ɲ"),(r"sc(?=[ie])","ʃ"),
              (r"c(?=[ie])","tʃ"),(r"g(?=[ie])","dʒ"),(r"à","a"),(r"è","ɛ"),(r"é","e"),(r"ì","i"),
              (r"ò","ɔ"),(r"ù","u"),(r"a","a"),(r"e","e"),(r"i","i"),(r"o","o"),(r"u","u"),(r"b","b"),
              (r"c","k"),(r"d","d"),(r"f","f"),(r"g","ɡ"),(r"h",""),(r"j","j"),(r"k","k"),(r"l","l"),
              (r"m","m"),(r"n","n"),(r"p","p"),(r"q","k"),(r"r","r"),(r"s","s"),(r"t","t"),(r"v","v"),
              (r"w","v"),(r"x","ks"),(r"y","i"),(r"z","ts")]),
    "de": _R([(r"sch","ʃ"),(r"tsch","tʃ"),(r"ch","x"),(r"ck","k"),(r"ph","f"),(r"th","t"),(r"qu","kv"),
              (r"ng","ŋ"),(r"ei","aɪ"),(r"ai","aɪ"),(r"ie","iː"),(r"eu","ɔʏ"),(r"äu","ɔʏ"),(r"au","aʊ"),
              (r"^sp","ʃp"),(r"^st","ʃt"),(r"ß","s"),(r"ö","ø"),(r"ü","y"),(r"ä","ɛ"),(r"a","a"),(r"e","e"),
              (r"i","i"),(r"o","o"),(r"u","u"),(r"y","y"),(r"b","b"),(r"c","k"),(r"d","d"),(r"f","f"),
              (r"g","ɡ"),(r"h","h"),(r"j","j"),(r"k","k"),(r"l","l"),(r"m","m"),(r"n","n"),(r"p","p"),
              (r"r","ʁ"),(r"s","z"),(r"t","t"),(r"v","f"),(r"w","v"),(r"x","ks"),(r"z","ts")]),
    "nl": _R([(r"sch","sx"),(r"ch","x"),(r"ij","ɛi"),(r"ui","œy"),(r"eu","ø"),(r"oe","u"),(r"aa","aː"),
              (r"ee","eː"),(r"oo","oː"),(r"uu","y"),(r"ie","i"),(r"ou","ʌu"),(r"au","ʌu"),(r"ng","ŋ"),
              (r"a","ɑ"),(r"e","ɛ"),(r"i","ɪ"),(r"o","ɔ"),(r"u","ʏ"),(r"y","i"),(r"b","b"),(r"c","k"),
              (r"d","d"),(r"f","f"),(r"g","x"),(r"h","h"),(r"j","j"),(r"k","k"),(r"l","l"),(r"m","m"),
              (r"n","n"),(r"p","p"),(r"q","k"),(r"r","r"),(r"s","s"),(r"t","t"),(r"v","v"),(r"w","ʋ"),
              (r"x","ks"),(r"z","z")]),
    "sv": _R([(r"skj","ɧ"),(r"stj","ɧ"),(r"sj","ɧ"),(r"tj","ɕ"),(r"kj","ɕ"),(r"sk(?=[eiyäö])","ɧ"),
              (r"k(?=[eiyäö])","ɕ"),(r"g(?=[eiyäö])","j"),(r"å","oː"),(r"ä","ɛ"),(r"ö","ø"),(r"a","a"),
              (r"e","e"),(r"i","i"),(r"o","u"),(r"u","ʉ"),(r"y","y"),(r"b","b"),(r"c","k"),(r"d","d"),
              (r"f","f"),(r"g","ɡ"),(r"h","h"),(r"j","j"),(r"k","k"),(r"l","l"),(r"m","m"),(r"n","n"),
              (r"p","p"),(r"q","k"),(r"r","r"),(r"s","s"),(r"t","t"),(r"v","v"),(r"w","v"),(r"x","ks"),
              (r"z","s")]),
    "pt": _R([(r"lh","ʎ"),(r"nh","ɲ"),(r"ch","ʃ"),(r"rr","ʁ"),(r"ss","s"),(r"qu(?=[ei])","k"),
              (r"gu(?=[ei])","ɡ"),(r"ão","ɐ̃w"),(r"ç","s"),(r"c(?=[ei])","s"),(r"g(?=[ei])","ʒ"),
              (r"ã","ɐ̃"),(r"õ","õ"),(r"á","a"),(r"â","ɐ"),(r"é","ɛ"),(r"ê","e"),(r"í","i"),(r"ó","ɔ"),
              (r"ô","o"),(r"ú","u"),(r"a","a"),(r"e","e"),(r"i","i"),(r"o","o"),(r"u","u"),(r"y","i"),
              (r"b","b"),(r"c","k"),(r"d","d"),(r"f","f"),(r"g","ɡ"),(r"h",""),(r"j","ʒ"),(r"k","k"),
              (r"l","l"),(r"m","m"),(r"n","n"),(r"p","p"),(r"q","k"),(r"r","ʁ"),(r"s","s"),(r"t","t"),
              (r"v","v"),(r"w","v"),(r"x","ʃ"),(r"z","z")]),
    "fr": _R([(r"ph","f"),(r"ch","ʃ"),(r"gn","ɲ"),(r"qu","k"),(r"ç","s"),
              (r"ain(?![aeiouy])","ɛ̃"),(r"ein(?![aeiouy])","ɛ̃"),(r"an(?![aeiouy])","ɑ̃"),
              (r"am(?![aeiouy])","ɑ̃"),(r"en(?![aeiouy])","ɑ̃"),(r"em(?![aeiouy])","ɑ̃"),
              (r"on(?![aeiouy])","ɔ̃"),(r"om(?![aeiouy])","ɔ̃"),(r"un(?![aeiouy])","œ̃"),
              (r"in(?![aeiouy])","ɛ̃"),(r"im(?![aeiouy])","ɛ̃"),(r"eau","o"),(r"au","o"),(r"ou","u"),
              (r"oi","wa"),(r"ai","ɛ"),(r"ei","ɛ"),(r"eu","ø"),(r"c(?=[eiy])","s"),(r"g(?=[eiy])","ʒ"),
              (r"é","e"),(r"è","ɛ"),(r"ê","ɛ"),(r"ë","ɛ"),(r"à","a"),(r"â","a"),(r"ô","o"),(r"û","y"),
              (r"î","i"),(r"ï","i"),(r"ù","y"),(r"a","a"),(r"e","ə"),(r"i","i"),(r"o","o"),(r"u","y"),
              (r"y","i"),(r"b","b"),(r"c","k"),(r"d","d"),(r"f","f"),(r"g","ɡ"),(r"h",""),(r"j","ʒ"),
              (r"k","k"),(r"l","l"),(r"m","m"),(r"n","n"),(r"p","p"),(r"q","k"),(r"r","ʁ"),(r"s","s"),
              (r"t","t"),(r"v","v"),(r"w","v"),(r"x","ks"),(r"z","z")]),
}
_STRESS_RULE = {"es": "penult", "it": "penult", "pt": "penult", "fr": "final",
                "de": "first", "nl": "first", "sv": "first"}


def _rule_stress(lang, syl):
    if syl <= 1:
        return 1
    r = _STRESS_RULE.get(lang, "first")
    if r == "penult":
        return max(1, syl - 1)
    if r == "final":
        return syl
    return 1


def _rule_source(lang):
    return ("SRC-G2P-%s" % lang.upper(),
            "QueryBook rule-seeded G2P (%s, approximate)" % LANG_NAMES.get(lang, lang),
            "internal-derived", 0.65)


def _g2p_rules(word, lang):
    """Bundled rule-seeded IPA for `lang` — pure Python, no engine. Returns
    (ipa, stress_syllable, syllable_count) or None if the language has no table."""
    rules = G2P_RULES.get((lang or "").lower())
    if not rules:
        return None
    w = str(word).lower()
    out, i, n = [], 0, len(w)
    while i < n:
        hit = False
        for rx, ipa in rules:
            m = rx.match(w, i)
            if m and m.end() > i:
                if ipa:
                    out.append(ipa)
                i = m.end(); hit = True; break
        if not hit:
            i += 1
    ipa = "".join(out)
    if not ipa:
        return None
    syl = max(1, sum(1 for c in ipa if c in _IPA_VOWELS))
    return ipa, _rule_stress(lang, syl), syl


def analyze_pronunciation(word, lang="en"):
    """Deterministic pronunciation breakdown for one word (no store write). English uses the
    rule-seeded G2P; other languages prefer espeak-ng when installed (most accurate) and
    otherwise use the BUNDLED rule-seeded G2P, so pronunciation always works. No LLM, never
    fabricates beyond the approximate rule model."""
    lang = (lang or "en").lower()
    if lang == "en":
        phon = _g2p(word)
        stress, syl = _stress_pattern(word)
        return {"word": word.lower(), "lang": "en", "phonemes": phon,
                "ipa": "/" + "".join(phon) + "/", "syllables": syl, "stress_syllable": stress,
                "source": "rule-seeded G2P", "via": "rules"}
    if _espeak_exe():
        ipa, stress, syl = _ipa_espeak(word, lang)
        if ipa is not None:
            return {"word": str(word).lower(), "lang": lang, "phonemes": list(ipa),
                    "ipa": "/" + ipa + "/", "syllables": syl, "stress_syllable": stress,
                    "source": "espeak-ng %s" % lang, "via": "espeak"}
    r = _g2p_rules(word, lang)
    if r is not None:
        ipa, stress, syl = r
        return {"word": str(word).lower(), "lang": lang, "phonemes": list(ipa),
                "ipa": "/" + ipa + "/", "syllables": syl, "stress_syllable": stress,
                "source": "rule-seeded G2P (%s)" % lang, "via": "rules"}
    return {"word": str(word).lower(), "lang": lang, "phonemes": [], "ipa": None,
            "syllables": 1, "stress_syllable": 1, "source": "no phonemizer", "via": None}


def speech_analyze(store_dir, words=None, max_words=None, lang="en"):
    """Phase 4a: write deterministic pronunciation Fact Units for words. No LLM. English uses
    the rule-seeded G2P; other languages use the OS phonemizer, each fact sourced accordingly.
    A word whose phonemizer is unavailable is skipped, never fabricated."""
    lang = (lang or "en").lower()
    if words is None:
        words = learned_words(store_dir, 400)
    if max_words:
        words = words[:max_words]
    src = SPEECH_SOURCE if lang == "en" else (_espeak_source(lang) if _espeak_exe() else _rule_source(lang))
    st = store.UFCSStore(store_dir)
    added = 0; sample = []
    try:
        for w in words:
            wl = str(w).lower().strip()
            if not wl or not wl.isalpha() or len(wl) < 2:
                continue
            a = analyze_pronunciation(wl, lang)
            if a["ipa"] is None:                       # unsupported language -> skip, do not fabricate
                continue
            label = ('english word "%s"' % wl) if lang == "en" \
                else ('%s word "%s"' % (LANG_NAMES.get(lang, lang).lower(), wl))
            if st.add(store.make_packet(label, "pronunciation", a["ipa"], "+", "language", src, 0.70)):
                added += 1
            st.add(store.make_packet(label, "syllable_count", str(a["syllables"]), "+", "language", src, 0.70))
            st.add(store.make_packet(label, "stress_syllable", str(a["stress_syllable"]), "+", "language", src, 0.70))
            if len(sample) < 8:
                sample.append(a)
        st.flush()
    finally:
        st.close()
    return {"words_in": len(words), "analyzed": added, "lang": lang, "sample": sample}


def _tts_engine():
    """Detect an available OS text-to-speech engine without synthesizing. Returns (kind, exe) or (None, None)."""
    import platform, shutil
    sysname = platform.system()
    if sysname == "Windows":
        return ("sapi", "powershell")          # System.Speech ships with Windows
    if sysname == "Darwin":
        return ("say", "say") if shutil.which("say") else (None, None)
    for exe in ("espeak-ng", "espeak"):
        if shutil.which(exe):
            return ("espeak", exe)
    return (None, None)


def tts_status():
    kind, exe = _tts_engine()
    hints = {"Linux": "install espeak-ng (e.g. `sudo apt install espeak-ng`)",
             "Windows": "built in (System.Speech)", "Darwin": "built in (`say`)"}
    import platform
    return {"available": bool(kind), "engine": kind, "platform": platform.system(),
            "hint": None if kind else hints.get(platform.system(), "install a local TTS engine")}


def speak(text, out_path=None, lang="en"):
    """Phase 4b: synthesize `text` to a WAV using the OS's built-in TTS, in the given
    language's voice where the engine supports it. Returns {available, engine, lang,
    wav_bytes|None, error?}. Never fabricates audio."""
    import platform, subprocess, tempfile, os as _os
    lang = (lang or "en").lower()
    text = (text or "").strip()[:400]
    if not text:
        return {"available": True, "engine": None, "lang": lang, "wav_bytes": None, "error": "no text"}
    tmp = out_path or _os.path.join(tempfile.gettempdir(), "qb_speech.wav")

    # --- Non-English: espeak-ng is the reliable multilingual voice on every OS. ---
    esp = _espeak_exe()
    if lang != "en" and esp:
        try:
            subprocess.run([esp, "-v", lang, "-w", tmp, text], timeout=30, check=True, capture_output=True)
            with open(tmp, "rb") as fh:
                data = fh.read()
            return {"available": True, "engine": "espeak", "lang": lang, "wav_bytes": data, "mime": "audio/wav"}
        except Exception as e:
            return {"available": True, "engine": "espeak", "lang": lang, "wav_bytes": None,
                    "error": "espeak-ng failed for '%s': %s" % (lang, e)}

    kind, exe = _tts_engine()
    if not kind:
        return {"available": False, "engine": None, "lang": lang, "wav_bytes": None,
                "error": tts_status()["hint"]}

    # --- Non-English but no espeak-ng: try a matching Windows SAPI voice; refuse if none. ---
    if lang != "en" and kind == "sapi":
        safe = text.replace("'", "''")
        ps = ("Add-Type -AssemblyName System.Speech; "
              "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              "$v=$s.GetInstalledVoices()|?{$_.Enabled -and $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq '%s'}|select -First 1; "
              "if($v){$s.SelectVoice($v.VoiceInfo.Name);$s.SetOutputToWaveFile('%s');$s.Speak('%s');$s.Dispose();exit 0}else{exit 3}"
              % (lang, tmp.replace("'", "''"), safe))
        rc = subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=30, capture_output=True)
        if rc.returncode == 0 and _os.path.exists(tmp):
            with open(tmp, "rb") as fh:
                data = fh.read()
            return {"available": True, "engine": "sapi", "lang": lang, "wav_bytes": data, "mime": "audio/wav"}
        return {"available": False, "engine": "sapi", "lang": lang, "wav_bytes": None,
                "error": ("No %s voice on this computer. Install espeak-ng (free, works for all languages) "
                          "or add a Windows %s voice in Settings. (Not speaking English for a %s request.)"
                          % (LANG_NAMES.get(lang, lang), LANG_NAMES.get(lang, lang), LANG_NAMES.get(lang, lang)))}

    # --- English (or a non-English 'say'/espeak default handled above). ---
    try:
        if kind == "sapi":
            safe = text.replace("'", "''")
            ps = ("Add-Type -AssemblyName System.Speech; "
                  "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  "$s.SetOutputToWaveFile('%s'); $s.Speak('%s'); $s.Dispose()" % (tmp.replace("'", "''"), safe))
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=30,
                           check=True, capture_output=True)
        elif kind == "say":
            aiff = tmp[:-4] + ".aiff"
            subprocess.run(["say", "-o", aiff, text], timeout=30, check=True, capture_output=True)
            # convert to wav if afconvert exists, else return aiff bytes
            import shutil as _sh
            if _sh.which("afconvert"):
                subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16", aiff, tmp], timeout=30, check=True)
            else:
                tmp = aiff
        else:  # espeak / espeak-ng — select the language voice when not English
            cmd = [exe] + (["-v", lang] if lang and lang != "en" else []) + ["-w", tmp, text]
            subprocess.run(cmd, timeout=30, check=True, capture_output=True)
        with open(tmp, "rb") as fh:
            data = fh.read()
        return {"available": True, "engine": kind, "lang": lang, "wav_bytes": data,
                "mime": "audio/aiff" if tmp.endswith(".aiff") else "audio/wav"}
    except Exception as e:
        return {"available": True, "engine": kind, "wav_bytes": None, "error": "TTS call failed: %s" % e}


def speech_status(store_dir):
    """Phase 4 status: analysis coverage + whether a real TTS engine is available."""
    vocab = len(learned_words(store_dir, 400))
    st = store.UFCSStore(store_dir)
    analyzed = 0
    try:
        if not st.no_fql:
            analyzed = st.db.execute("SELECT COUNT(*) FROM nuc WHERE predicate='pronunciation'").fetchone()[0]
    except Exception:
        pass
    finally:
        st.close()
    return {"vocabulary": vocab, "analyzed": analyzed, "tts": tts_status()}


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


# --------------------------------------------------------------------------
# PER-LANGUAGE LEARNING (structural + pronunciation), the same shape as the
# English Phase-1 path: ingest a bundled PUBLIC-DOMAIN starter corpus (standard
# pangrams + numbers + weekdays), build the language's vocabulary, and write a
# pronunciation Fact Unit for each word via the deterministic OS phonemizer.
# No LLM. Meaning-grounding (definitions) still needs a per-language dictionary
# and stays gated — this is vocabulary + pronunciation acquisition.
# --------------------------------------------------------------------------
STARTER_CORPUS_L10N = {
    "de": ["Zwölf Boxkämpfer jagen Viktor quer über den großen Sylter Deich.",
           "Franz jagt im komplett verwahrlosten Taxi quer durch Bayern.",
           "null eins zwei drei vier fünf sechs sieben acht neun zehn",
           "Montag Dienstag Mittwoch Donnerstag Freitag Samstag Sonntag"],
    "fr": ["Portez ce vieux whisky au juge blond qui fume.",
           "Voix ambiguë d'un cœur qui au zéphyr préfère les jattes de kiwis.",
           "zéro un deux trois quatre cinq six sept huit neuf dix",
           "lundi mardi mercredi jeudi vendredi samedi dimanche"],
    "es": ["El veloz murciélago hindú comía feliz cardillo y kiwi.",
           "La cigüeña tocaba cada vez mejor el saxofón y el búho pedía queso.",
           "cero uno dos tres cuatro cinco seis siete ocho nueve diez",
           "lunes martes miércoles jueves viernes sábado domingo"],
    "pt": ["Um pequeno jabuti xereta viu dez cegonhas felizes.",
           "Luís argüía à Júlia que fé, chá, óxido, pôr e zângão eram palavras.",
           "zero um dois três quatro cinco seis sete oito nove dez",
           "segunda terça quarta quinta sexta sábado domingo"],
    "it": ["Ma la volpe, col suo balzo, ha raggiunto il quieto Fido.",
           "Quel fez sghembo copre davanti al pianoforte.",
           "zero uno due tre quattro cinque sei sette otto nove dieci",
           "lunedì martedì mercoledì giovedì venerdì sabato domenica"],
    "sv": ["Flygande bäckasiner söka hwila på mjuka tuvor.",
           "Yxskaftbud, ge vår WC-zonmö iq-hjälp.",
           "noll ett två tre fyra fem sex sju åtta nio tio",
           "måndag tisdag onsdag torsdag fredag lördag söndag"],
    "nl": ["Pa's wijze lynx bezag vroom het fikse aquaduct.",
           "Sexy qua lijf, doch bang voor het zwempak.",
           "nul een twee drie vier vijf zes zeven acht negen tien",
           "maandag dinsdag woensdag donderdag vrijdag zaterdag zondag"],
}


def _corpus_words(lang):
    """Ordered unique word forms from the bundled starter corpus for `lang`
    (English reuses STARTER_CORPUS). Letter-only tokens; accents preserved."""
    lang = (lang or "en").lower()
    chunks = STARTER_CORPUS if lang == "en" else STARTER_CORPUS_L10N.get(lang, [])
    text = " ".join(chunks).lower()
    seen, order = set(), []
    for tok in re.findall(r"[^\W\d_]+", text, re.UNICODE):
        if len(tok) >= 1 and tok not in seen:
            seen.add(tok); order.append(tok)
    return order


def learn_language(store_dir, lang, words=None, max_words=None):
    """Learn a language the way English Phase 1 learned: for each word in the bundled
    starter corpus, write a vocabulary Fact Unit (attested in the corpus) and, when the
    OS phonemizer is present, its pronunciation. Deterministic, no LLM. Returns counts."""
    lang = (lang or "en").lower()
    allw = _corpus_words(lang)
    if words is None:
        words = allw
    if max_words:
        words = words[:max_words]
    csrc = ("SRC-CORPUS-%s" % lang.upper(),
            "Bundled public-domain starter corpus (pangrams, %s)" % LANG_NAMES.get(lang, lang),
            "reference", 0.8)
    psrc = SPEECH_SOURCE if lang == "en" else (_espeak_source(lang) if _espeak_exe() else _rule_source(lang))
    st = store.UFCSStore(store_dir)
    vocab_added = pron_added = 0
    sample = []
    try:
        for w in words:
            wl = str(w).lower().strip()
            if not wl or not wl.isalpha():
                continue
            label = '%s word "%s"' % (LANG_NAMES.get(lang, lang).lower(), wl)
            if st.add(store.make_packet(label, "attested_in", "bundled starter corpus", "+", "language", csrc, 0.8)):
                vocab_added += 1
            a = analyze_pronunciation(wl, lang)
            if a["ipa"]:
                if st.add(store.make_packet(label, "pronunciation", a["ipa"], "+", "language", psrc, 0.70)):
                    pron_added += 1
                st.add(store.make_packet(label, "syllable_count", str(a["syllables"]), "+", "language", psrc, 0.70))
                st.add(store.make_packet(label, "stress_syllable", str(a["stress_syllable"]), "+", "language", psrc, 0.70))
            if len(sample) < 10:
                sample.append({"word": wl, "ipa": a["ipa"]})
        st.flush()
    finally:
        st.close()
    return {"lang": lang, "language": LANG_NAMES.get(lang, lang), "vocab_total": len(allw),
            "vocab_added": vocab_added, "pron_added": pron_added,
            "phonemizer": bool(_espeak_exe()) or lang == "en", "sample": sample}


def language_learning_status(store_dir, lang):
    """How much of a language has been learned (vocabulary + pronunciation)."""
    lang = (lang or "en").lower()
    total = len(_corpus_words(lang))
    prefix = ('english word "' if lang == "en" else '%s word "' % LANG_NAMES.get(lang, lang).lower())
    st = store.UFCSStore(store_dir)
    vocab = pron = 0
    try:
        if not st.no_fql:
            vocab = st.db.execute("SELECT COUNT(DISTINCT subject) FROM nuc WHERE predicate='attested_in' AND subject LIKE ?",
                                  (prefix + "%",)).fetchone()[0]
            pron = st.db.execute("SELECT COUNT(*) FROM nuc WHERE predicate='pronunciation' AND subject LIKE ?",
                                 (prefix + "%",)).fetchone()[0]
    except Exception:
        pass
    finally:
        st.close()
    return {"lang": lang, "language": LANG_NAMES.get(lang, lang), "vocab_total": total,
            "vocab_learned": vocab, "pronounced": pron, "phonemizer": bool(_espeak_exe()) or lang == "en"}


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
    {"n": 4, "key": "speech", "agent_kind": "lang_speech", "status": "built",
     "name": "Speech output (Phase 4) — analysis + OS voice",
     "desc": "Two honest parts. (4a) Deterministic pronunciation analysis of the learned vocabulary — "
             "rule-seeded G2P phonemes, syllable split, stress, prosody — stored as Fact Units, no LLM. "
             "(4b) Real speech via the computer's BUILT-IN text-to-speech (Windows SAPI, macOS say, Linux "
             "espeak-ng); if no engine is present it says so and never fabricates audio. The full neural "
             "vocoder pipeline remains the roadmap embodiment."},
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
