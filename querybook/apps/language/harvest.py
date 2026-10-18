"""The Language Builder harvest team (see qbcommons for the four agents).

What it harvests into the Commons: English word meanings from Webster's 1913 dictionary (public
domain), most common words first, and the translations of those words into the 16 other languages
from the bundled bilingual dictionaries. Those dictionaries are MUSE (CC BY-NC 4.0): under the
commercial licence policy the Strategist leaves them out and the translation checks decline.

What it answers for the other applications: whether an English word is in the dictionary (with its
meaning), and whether a translation is in the bilingual dictionary.
"""
import qbcommons as cm
import vocab

SRC_WEBSTER = "Webster's Unabridged Dictionary (1913)"
LIC_WEBSTER = "public domain"
SRC_MUSE = "MUSE bilingual dictionaries (Facebook AI Research)"
LIC_MUSE = "CC BY-NC 4.0 (non-commercial)"
BUDGET = {"definitions": 500, "words_per_language": 250, "forms": 2}


def _meaning(text):
    t = " ".join(str(text or "").split()).rstrip(";,: ")
    return t[:497] + "…" if len(t) > 500 else t


def _subject(word):
    return 'english word "%s"' % word


class LanguageAdapter(cm.Adapter):
    def __init__(self, app=None):
        self.app = app

    # ------------------------------------------------------------------ Strategist
    def survey(self, ctx):
        words = vocab.definitions()
        langs = {}
        for code in vocab.OTHERS:
            n = len(vocab.deck(code))
            langs[code] = {"name": vocab.LANGUAGES[code]["name"], "words": n, "done": min(ctx.cursor("tr_" + code), n)}
        return {"definitions": len(words), "definitions_done": min(ctx.cursor("definitions"), len(words)), "languages": langs,
                "translation_entries": sum(v["words"] for v in langs.values()), "translations_done": sum(v["done"] for v in langs.values())}

    def strategy(self, sv, ctx):
        goals = []
        n_open = ctx.commons.store.scalar("SELECT count(*) FROM requests WHERE to_app = 'language' AND status = 'open'", default=0)
        if n_open:
            goals.append({"goal": "Answer %d checks from the other applications" % n_open, "priority": 1,
                          "why": "they asked whether words are in the dictionary or translations in the bilingual dictionary"})
        if sv["definitions_done"] < sv["definitions"]:
            goals.append({"goal": "Share English meanings", "priority": 2,
                          "why": "%d of %d done; public-domain Webster 1913, most common words first" % (sv["definitions_done"], sv["definitions"])})
        nc_ok = ctx.allowed(LIC_MUSE)
        behind = sorted((v["done"] / max(v["words"], 1), code) for code, v in sv["languages"].items() if v["done"] < v["words"])
        if behind and nc_ok:
            goals.append({"goal": "Share translations", "priority": 3,
                          "why": "%d of %d entries done; the least-covered languages go first (%s). MUSE is CC BY-NC: research and demonstration only"
                                 % (sv["translations_done"], sv["translation_entries"], ", ".join(sv["languages"][c]["name"] for _, c in behind[:3]))})
        elif behind:
            goals.append({"goal": "Hold translations back", "priority": 3,
                          "why": "the licence policy is commercial and the only bundled bilingual source (MUSE) is non-commercial; "
                                 "a commercially usable source is needed first"})
        return {"goals": goals, "budget": BUDGET, "order": [c for _, c in behind],
                "sources": [{"name": SRC_WEBSTER, "licence": LIC_WEBSTER, "use": "English meanings"},
                            {"name": SRC_MUSE, "licence": LIC_MUSE, "use": "translations" if nc_ok else "not used (commercial policy)"}]}

    # ------------------------------------------------------------------ Planner
    def plan(self, st, ctx):
        names = {g["goal"] for g in st["goals"]}
        tasks = []
        if "Share English meanings" in names:
            a = ctx.cursor("definitions")
            b = min(a + BUDGET["definitions"], len(vocab.definitions()))
            tasks.append({"action": "definitions", "title": "Share meanings of words %d–%d" % (a + 1, b), "target": {"from": a, "to": b}})
        if "Share translations" in names:
            for code in st["order"]:
                a = ctx.cursor("tr_" + code)
                b = min(a + BUDGET["words_per_language"], len(vocab.deck(code)))
                tasks.append({"action": "translations", "title": "Share %s translations of words %d–%d" % (vocab.LANGUAGES[code]["name"], a + 1, b),
                              "target": {"lang": code, "from": a, "to": b}})
        return tasks

    # ------------------------------------------------------------------ Harvester
    def execute(self, task, ctx):
        a, t = task["action"], task.get("target") or {}
        if a == "definitions":
            words = list(vocab.definitions().items())[t["from"]:t["to"]]
            items = [{"subject": _subject(w), "predicate": "means", "object": _meaning(d),
                      "evidence": [{"method": "reference", "source": SRC_WEBSTER, "licence": LIC_WEBSTER}],
                      "reasoning": ["Webster 1913 entry for “%s”; frequency rank %d." % (w, t["from"] + i + 1)]}
                     for i, (w, d) in enumerate(words) if _meaning(d)]
            return {"items": items, "cursor": {"definitions": t["to"]}, "detail": "%d meanings" % len(items)}
        if a == "translations":
            code = t["lang"]
            name = vocab.LANGUAGES[code]["name"]
            items = []
            for w in vocab.deck(code)[t["from"]:t["to"]]:
                for f in w["tr"][:BUDGET["forms"]]:
                    items.append({"subject": _subject(w["en"]), "predicate": "in " + name, "object": f,
                                  "evidence": [{"method": "reference", "source": SRC_MUSE, "licence": LIC_MUSE}]})
            return {"items": items, "cursor": {"tr_" + code: t["to"]}, "detail": "%d translations" % len(items)}
        raise ValueError("unknown task %s" % a)

    # ------------------------------------------------------------------ checks for the other applications
    def verifiers(self, ctx):
        def term(p):
            w = " ".join(str(p.get("word") or "").lower().split())
            d = vocab.definitions().get(w)
            if d:
                return {"verdict": "supports", "detail": "Webster 1913: %s" % _meaning(d)[:200],
                        "reasoning": ["“%s” is an entry in Webster's 1913 dictionary." % w]}
            return {"verdict": "cannot_check", "detail": "not among the %d bundled Webster 1913 entries" % len(vocab.definitions()),
                    "reasoning": ["The bundled dictionary is from 1913 and has the most common words only; a newer or rarer word is not evidence against it."]}

        def translation(p):
            if not ctx.allowed(LIC_MUSE):
                return {"verdict": "cannot_check", "detail": "the bilingual dictionary is non-commercial; not used under the commercial policy"}
            code = p.get("lang")
            if code not in vocab.OTHERS:
                return {"verdict": "cannot_check", "detail": "language not covered"}
            forms = vocab.forms(code, str(p.get("en") or "").lower())
            if vocab.check_answer(str(p.get("form") or ""), forms or ["\x00"])["result"] in ("correct", "accent"):
                return {"verdict": "supports", "detail": "listed in MUSE: %s" % ", ".join(forms[:4]),
                        "reasoning": ["The bilingual dictionary pairs “%s” with %s." % (p.get("en"), ", ".join(forms[:4]))]}
            return {"verdict": "cannot_check", "detail": "not listed" + (" (listed: %s)" % ", ".join(forms[:4]) if forms else ""),
                    "reasoning": ["A word missing from one dictionary is not proof that the translation is wrong."]}
        return {"term": term, "translation": translation}
