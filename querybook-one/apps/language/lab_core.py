"""Language Lab learning logic, ported VERBATIM from the last prototype before the full build:
prototype/QueryBook-v9.47/qb_language.py at commit b9f5b48 (Prototype v9.50, 2 October 2026).

Only these pure functions and tables are copied; nothing in them was changed. Storage, the phase
driver and the user interface are in lab.py (the old JSON model file is replaced by the app database).
"""
import re, time

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


LANG_NAMES = {"en": "English", "es": "Spanish", "fr": "French", "de": "German",
              "pt": "Portuguese", "it": "Italian", "sv": "Swedish", "nl": "Dutch"}


# Vowel nuclei used to count syllables in an IPA string (approximate, deterministic).
_IPA_VOWELS = set("iyɨʉɯuɪʏʊeøɘɵɤoəɛœɜɞʌɔæɐaɶɑɒ")


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


def _ipa_meta(ipa):
    """syllable count + 1-indexed primary-stress syllable from an IPA string."""
    nuclei = [i for i, c in enumerate(ipa) if c in _IPA_VOWELS]
    syl = max(1, len(nuclei))
    stress = 1
    mark = ipa.find("ˈ")
    if mark >= 0 and nuclei:
        stress = min(max(1, 1 + sum(1 for n in nuclei if n < mark)), syl)
    return syl, stress


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


