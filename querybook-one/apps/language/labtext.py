"""labtext — the Language Lab screen's word-list translation and voice choice, as plain functions.

The phrase translator (ui/translate, offline dictionaries) handles whole phrases first; the words it does not
know are sent here and filled from the Language Builder's word lists (about 4,500 words per language), always
marked as coming from the word list and with the other possible words, never guessed beyond that.
"""
from __future__ import annotations

import unicodedata

import vocab

VOICE_OPTIONS: dict[str, str] = {"": "", "female": "f3", "male": "m3", "whisper": "whisper", "whisper-female": "whisperf",
                                 "slow-old": "grandpa", "hoarse": "croak"}
_REVERSE: dict[str, dict[str, list[str]]] = {}


def voice_name(base: str, option: str) -> str:
    """espeak-ng voice for a language's base voice and a Lab voice option (variants are espeak-ng's FILE names)."""
    v = VOICE_OPTIONS.get(option, "")
    return base + "+" + v if v else base


def _plain(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", word) if not unicodedata.combining(c))


def best(forms: list[str]) -> str:
    """The form shown first: the shortest (usually the base form: casa, not casita); between spellings that differ
    only by accents, the accented one (estación, not estacion — the word lists hold both); else the earliest."""
    if not forms:
        return ""
    return min(forms, key=lambda f: (len(_plain(f)), _plain(f) == f and any(_plain(g) == f and g != f for g in forms)))


def to_english(lang: str, word: str) -> list[str]:
    """English words whose translation in `lang` is `word` (case-insensitive), most common English word first."""
    if lang == "en":
        return [word.lower()] if word.lower() in vocab.rank() else []
    if lang not in _REVERSE:
        idx: dict[str, list[str]] = {}
        for w in vocab.deck(lang):
            for t in w["tr"]:
                idx.setdefault(t.lower(), []).append(w["en"])
        _REVERSE[lang] = idx
    return list(_REVERSE[lang].get(word.lower(), []))


# The word lists leave out grammar words. Their basic equivalents, only where one is clear-cut (no articles: their
# form depends on the noun's gender; no languages that express these by case endings, such as Finnish or Hungarian).
# Order: of, to, in, on, with, for, from, and, or, but, not, very, also
GRAMMAR_EN: list[str] = "of to in on with for from and or but not very also".split()
GRAMMAR: dict[str, list[str]] = {
    "es": "de a en en con para de y o pero no muy también".split(),
    "fr": "de à dans sur avec pour de et ou mais pas très aussi".split(),
    "de": "von zu in auf mit für aus und oder aber nicht sehr auch".split(),
    "it": "di a in su con per da e o ma non molto anche".split(),
    "pt": "de a em em com para de e ou mas não muito também".split(),
    "nl": "van naar in op met voor uit en of maar niet zeer ook".split(),
    "sv": "av till i på med för från och eller men inte mycket också".split(),
    "da": "af til i på med for fra og eller men ikke meget også".split(),
    "no": "av til i på med for fra og eller men ikke veldig også".split(),
    "ca": "de a en en amb per de i o però no molt també".split(),
    "ro": "de la în pe cu pentru din și sau dar nu foarte și".split(),
}


def grammar_word(src: str, tgt: str, word: str) -> str:
    """The basic equivalent of a grammar word, from English (src "en") or back to English (tgt "en"); "" if none."""
    w = word.lower()
    if src == "en" and tgt in GRAMMAR and w in GRAMMAR_EN:
        return GRAMMAR[tgt][GRAMMAR_EN.index(w)]
    if tgt == "en" and src in GRAMMAR and w in GRAMMAR[src]:
        return GRAMMAR_EN[GRAMMAR[src].index(w)]
    return ""


def from_english(lang: str, en: str) -> list[str]:
    return vocab.forms(lang, en.lower()) if lang != "en" else ([en.lower()] if en.lower() in vocab.rank() else [])


def fill_one(src: str, tgt: str, word: str) -> dict:
    """One word through the word lists, via English when neither side is English."""
    ens = [word.lower()] if src == "en" else to_english(src, word)
    for en in ens:
        forms = [en] if tgt == "en" else from_english(tgt, en)
        if forms:
            return {"word": word, "text": best(forms), "others": [f for f in forms if f != best(forms)][:6],
                    "via": "word list" + ("" if src == "en" or tgt == "en" else " (through English: %s)" % en)}
    g = grammar_word(src, tgt, word) if "en" in (src, tgt) else grammar_word("en", tgt, grammar_word(src, "en", word))
    if g:
        return {"word": word, "text": g, "others": [], "via": "grammar word (basic meaning — it can change with the sentence)"}
    return {"word": word, "text": word, "others": [], "via": None}


def fill(src: str, tgt: str, words: list[str]) -> dict:
    """Fill each word the phrase translator did not know. Unknown languages or words are returned unchanged."""
    langs = set(vocab.LANGUAGES)
    if src not in langs or tgt not in langs:
        return {"words": {w: {"word": w, "text": w, "others": [], "via": None} for w in words[:200]}}
    return {"words": {w: fill_one(src, tgt, w) for w in [str(x) for x in words][:200] if w.strip()}}


def self_test() -> list[tuple[str, bool]]:
    es = fill("en", "es", ["house", "water", "zzqx"])["words"]
    back = fill("es", "en", ["casa"])["words"]
    via = fill("fr", "es", ["maison"])["words"]
    return [
        ("voice options use espeak-ng's file names", voice_name("en-us", "whisper-female") == "en-us+whisperf" and voice_name("es", "") == "es"),
        ("an English word is filled from the word list", es["house"]["text"] == "casa" and es["water"]["text"] == "agua"),
        ("grammar words the word lists leave out: of → de / von, and back", fill("en", "es", ["of"])["words"]["of"]["text"] == "de"
         and fill("en", "de", ["of"])["words"]["of"]["text"] == "von" and fill("de", "en", ["und"])["words"]["und"]["text"] == "and"
         and all(len(v) == len(GRAMMAR_EN) for v in GRAMMAR.values())),
        ("the accented spelling wins over the same word without accents", best(["estacion", "estación"]) == "estación" and best(["casita", "casa"]) == "casa"),
        ("an unknown word is returned unchanged and unmarked", es["zzqx"]["text"] == "zzqx" and es["zzqx"]["via"] is None),
        ("Spanish back to English", back["casa"]["text"] == "house"),
        ("French to Spanish goes through English and says so", via["maison"]["text"] == "casa" and "through English" in via["maison"]["via"]),
    ]


if __name__ == "__main__":
    res = self_test()
    for name, ok in res:
        print(("  [OK]   " if ok else "  [FAIL] ") + name)
    print("%d of %d checks passed" % (sum(ok for _, ok in res), len(res)))
    raise SystemExit(0 if all(ok for _, ok in res) else 1)
