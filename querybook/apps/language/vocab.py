"""Vocabulary, dictionary and answer checking for the language application.

Data (bundled, read-only):
  data/bilingual.json.gz          English -> translations for 16 European languages (built by tools/build_wordlists.py).
                                  MUSE bilingual dictionaries (Facebook AI Research), CC BY-NC 4.0 —
                                  demonstration data for non-commercial use; replace before selling.
  data/english_dictionary.json.gz English definitions from Webster's Unabridged Dictionary (1913),
                                  public domain. Ordered by how often English words occur, which
                                  sets the order new words are taught.
Known limits of the data: translations are lower-case (German nouns are normally capitalized),
some entries are inflected forms, and the 1913 definitions use old-fashioned wording.
"""
import gzip, json, os, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

LANGUAGES = {        # English first; every other language is paired with English in the bundled dictionaries
    "en": {"name": "English", "native": "English", "speech": "en-US", "espeak": "en-us"},
    "es": {"name": "Spanish", "native": "Español", "speech": "es-ES", "espeak": "es"},
    "fr": {"name": "French", "native": "Français", "speech": "fr-FR", "espeak": "fr"},
    "de": {"name": "German", "native": "Deutsch", "speech": "de-DE", "espeak": "de"},
    "it": {"name": "Italian", "native": "Italiano", "speech": "it-IT", "espeak": "it"},
    "pt": {"name": "Portuguese", "native": "Português", "speech": "pt-PT", "espeak": "pt"},
    "nl": {"name": "Dutch", "native": "Nederlands", "speech": "nl-NL", "espeak": "nl"},
    "sv": {"name": "Swedish", "native": "Svenska", "speech": "sv-SE", "espeak": "sv"},
    "da": {"name": "Danish", "native": "Dansk", "speech": "da-DK", "espeak": "da"},
    "no": {"name": "Norwegian", "native": "Norsk", "speech": "nb-NO", "espeak": "nb"},
    "fi": {"name": "Finnish", "native": "Suomi", "speech": "fi-FI", "espeak": "fi"},
    "pl": {"name": "Polish", "native": "Polski", "speech": "pl-PL", "espeak": "pl"},
    "cs": {"name": "Czech", "native": "Čeština", "speech": "cs-CZ", "espeak": "cs"},
    "el": {"name": "Greek", "native": "Ελληνικά", "speech": "el-GR", "espeak": "el"},
    "ro": {"name": "Romanian", "native": "Română", "speech": "ro-RO", "espeak": "ro"},
    "hu": {"name": "Hungarian", "native": "Magyar", "speech": "hu-HU", "espeak": "hu"},
    "ca": {"name": "Catalan", "native": "Català", "speech": "ca-ES", "espeak": "ca"},
}
OTHERS = [c for c in LANGUAGES if c != "en"]
ENGLISH = LANGUAGES["en"]
SOURCES = {
    "bilingual": "MUSE bilingual dictionaries (Facebook AI Research), CC BY-NC 4.0 — demonstration data, non-commercial use",
    "dictionary": "Webster's Unabridged Dictionary (1913), public domain",
}

_cache = {}


def _load(name):
    if name not in _cache:
        with gzip.open(os.path.join(DATA, name), "rb") as f:
            _cache[name] = json.loads(f.read().decode("utf-8"))
    return _cache[name]


def definitions():
    return _load("english_dictionary.json.gz")


def rank():
    if "rank" not in _cache:
        _cache["rank"] = {w: i for i, w in enumerate(definitions())}
    return _cache["rank"]


def deck(lang):
    """The ordered word list for a language: [{"en", "tr": [...], "rank"}], most common English words first."""
    key = "deck:" + lang
    if key in _cache:
        return _cache[key]
    if lang not in OTHERS:
        raise KeyError(lang)
    raw = _load("bilingual.json.gz").get(lang, {})
    r = rank()
    out = []
    for en, forms in raw.items():
        if not en.isalpha() or (len(en) < 2 and en not in ("a", "i")):
            continue
        tr = []
        for f in forms if isinstance(forms, list) else [forms]:
            f = str(f).strip()
            if f and f.lower() != en.lower() and f not in tr and all(ch.isalpha() or ch in " -'’" for ch in f):
                tr.append(f)
        if tr:
            out.append({"en": en, "tr": tr, "rank": r.get(en, 100000 + len(out))})
    out.sort(key=lambda w: (w["rank"], w["en"]))
    _cache[key] = out
    _cache["index:" + lang] = {w["en"]: w for w in out}
    return out


def word(lang, en):
    deck(lang)
    return _cache["index:" + lang].get(en)


def forms(lang, en):
    """How the English word `en` is said in `lang` (English: the word itself)."""
    if lang == "en":
        return [en] if en in rank() else []
    w = word(lang, en)
    return list(w["tr"]) if w else []


def pair_deck(target, native):
    """Words to learn in `target` for someone who speaks `native`, most common first:
    [{"en", "target": [...], "native": [...], "rank"}]. Languages other than English are linked through English."""
    key = "pair:%s:%s" % (target, native)
    if key in _cache:
        return _cache[key]
    if target == native or target not in LANGUAGES or native not in LANGUAGES:
        raise KeyError((target, native))
    base = deck(native) if target == "en" else deck(target)
    out = []
    for w in base:
        t, n = forms(target, w["en"]), forms(native, w["en"])
        if t and n:
            out.append({"en": w["en"], "target": t, "native": n, "rank": w["rank"]})
    _cache[key] = out
    _cache["pairindex:%s:%s" % (target, native)] = {w["en"]: w for w in out}
    return out


def pair_word(target, native, en):
    pair_deck(target, native)
    return _cache["pairindex:%s:%s" % (target, native)].get(en)


def reverse_index(lang):
    key = "rev:" + lang
    if key not in _cache:
        rev = {}
        for w in deck(lang):
            for t in w["tr"]:
                rev.setdefault(fold(t), set()).add(w["en"])
        _cache[key] = {k: sorted(v) for k, v in rev.items()}
    return _cache[key]


def fold(s):
    """Lower-case and remove accents: 'Être' -> 'etre'. Used to forgive missing accents (with a note)."""
    s = unicodedata.normalize("NFKD", str(s).strip().lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch)).replace("ß", "ss")


def clean(s):
    return " ".join(unicodedata.normalize("NFC", str(s or "")).strip().lower().split()).strip(".!?¡¿,;:")


def check_answer(given, accepted):
    """Compare a typed answer with the accepted answers.

    Returns {"result": "correct" | "accent" | "close" | "wrong", "expected": best match, "distance": n}
      correct — exact (case and spacing ignored)
      accent  — right letters, accents missing or wrong (counted correct, with a reminder)
      close   — one letter off in a word of 5+ letters (counted wrong, shown as nearly right)
    """
    g = clean(given)
    best, best_d = accepted[0] if accepted else "", 99
    for a in accepted:
        ca = clean(a)
        if g == ca:
            return {"result": "correct", "expected": a, "distance": 0}
        if fold(g) == fold(ca):
            return {"result": "accent", "expected": a, "distance": 0}
        d = edit_distance(fold(g), fold(ca))
        if d < best_d:
            best, best_d = a, d
    if best_d == 1 and len(fold(best)) >= 5:
        return {"result": "close", "expected": best, "distance": 1}
    return {"result": "wrong", "expected": best, "distance": best_d}


def edit_distance(a, b):
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def similarity(a, b):
    """0–100: how close two phrases are (used to score speaking practice)."""
    fa, fb = fold(clean(a)), fold(clean(b))
    if not fa and not fb:
        return 100
    d = edit_distance(fa, fb)
    return max(0, round(100 * (1 - d / max(len(fa), len(fb)))))


def lookup(text, langs=None):
    """Look a word up in both directions: English definition + translations, or foreign word -> English."""
    q = clean(text)
    if not q:
        return {"query": text, "english": None, "foreign": []}
    langs = langs or list(OTHERS)
    out = {"query": text, "english": None, "foreign": []}
    defs = definitions()
    if q in defs or any(word(l, q) for l in langs):
        out["english"] = {"word": q, "definition": defs.get(q), "frequency_rank": rank().get(q),
                          "translations": {l: (word(l, q) or {}).get("tr", []) for l in langs}}
    for l in langs:
        hits = reverse_index(l).get(fold(q))
        if hits:
            out["foreign"].append({"lang": l, "language": LANGUAGES[l]["name"], "word": q, "english": hits[:12]})
    return out
