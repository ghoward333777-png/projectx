"""Query understanding + response shaping  [deterministic]

Wave-1 upgrades to the Query system's partials:
 - understand(text): deterministic entity / predicate / intent / scope extraction + query
   expansion, folding in PIL pragmatic framing. It produces a QUERY PLAN; it does not answer.
 - rank_evidence(rows, query): deterministic lexical-overlap ranking + a coherence note.
These are front-stage aids; the grounded answer and the refuse-not-invent gate are unchanged.
"""

import re as _re

_STOP = set("the a an of to in on at for and or but is are was were be been being this that "
            "these those it its as by with from into about over under not no do does did can "
            "could should would will shall may might i you he she we they me him her us them".split())
# Specific predicate cues are checked BEFORE generic wh-words, so "who wrote X" -> author.
_PREDICATE_HINTS = {
    "wrote": "author", "author": "author", "written by": "author", "capital": "capital_of",
    "mean": "means", "means": "means", "define": "means", "definition": "means",
    "date": "time", "located": "location", "how many": "count", "population": "population",
    "when": "time", "where": "location", "who": "agent", "is": "is_a", "are": "is_a",
}
_WH = ("who", "what", "when", "where", "why", "how", "which", "whose", "whom")


def _tokens(text):
    return [w for w in _re.findall(r"[a-z0-9']+", (text or "").lower())]

def entities(text):
    """Candidate entities = capitalized spans + quoted spans + content tokens (dedup, order-stable)."""
    out = []
    for m in _re.finditer(r'"([^"]+)"', text or ""):
        out.append(m.group(1).strip())
    for m in _re.finditer(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\b", text or ""):
        out.append(m.group(1).strip())
    content = [w for w in _tokens(text) if w not in _STOP and len(w) > 2]
    seen, res = set(), []
    for e in out + content:
        k = e.lower()
        if k not in seen:
            seen.add(k); res.append(e)
    return res[:12]

def predicate(text):
    low = (text or "").lower()
    for k, p in _PREDICATE_HINTS.items():
        if k in low:
            return p
    return "related_to"

def intent(text):
    low = (text or "").strip().lower()
    if low.startswith(_WH) or low.endswith("?"):
        return "question"
    if _re.match(r"^(list|show|find|give|tell|explain|compare|translate|speak|define)\b", low):
        return "command"
    return "statement"

def expand(text):
    """Query expansion: add light morphological / synonym-free variants of content tokens."""
    toks = [w for w in _tokens(text) if w not in _STOP and len(w) > 2]
    variants = set()
    for w in toks:
        variants.add(w)
        if w.endswith("s"): variants.add(w[:-1])
        else: variants.add(w + "s")
        if w.endswith("ed"): variants.add(w[:-2])
        if w.endswith("ing"): variants.add(w[:-3])
    return sorted(variants)

def understand(text):
    """Full deterministic query plan: entities, predicate, intent, scope, expansion, pragmatics."""
    ents = entities(text)
    plan = {"ok": True, "text": text, "intent": intent(text), "predicate": predicate(text),
            "entities": ents, "scope": "store", "expansion": expand(text)}
    try:
        import qb_pil
        plan["pragmatics"] = qb_pil.pragmatics(text)
    except Exception:
        pass
    plan["covenant"] = ("A query plan only; it selects HOW to search. The answer still comes "
                        "from verified Fact Units or returns UNKNOWN.")
    return plan


def rank_evidence(rows, query):
    """Rank candidate evidence strings by lexical overlap with the query (deterministic)."""
    q = set(w for w in _tokens(query) if w not in _STOP)
    scored = []
    for r in rows or []:
        text = r if isinstance(r, str) else (r.get("text") or str(r))
        toks = set(_tokens(text))
        overlap = len(q & toks)
        scored.append({"text": text, "score": overlap,
                       "coverage": round(overlap / (len(q) or 1), 3)})
    scored.sort(key=lambda x: -x["score"])
    coherent = bool(scored) and scored[0]["score"] > 0
    return {"ranked": scored, "coherent": coherent,
            "note": "Lexical-overlap ranking; a 0 top score means no evidence covers the query."}


def qc():
    checks = []
    u = understand('Who wrote "Hamlet"?')
    checks.append(("intent question", u["intent"] == "question"))
    checks.append(("predicate author", u["predicate"] == "author"))
    checks.append(("entity Hamlet", "Hamlet" in u["entities"]))
    checks.append(("expansion nonempty", len(u["expansion"]) > 0))
    r = rank_evidence(["Shakespeare wrote Hamlet", "Paris is in France"], "who wrote Hamlet")
    checks.append(("ranks Hamlet evidence top", r["ranked"][0]["text"].startswith("Shakespeare")))
    passed = sum(1 for _, c in checks if c)
    return {"passed": passed, "total": len(checks), "ok": passed == len(checks),
            "rows": [{"check": n, "pass": c} for n, c in checks]}


if __name__ == "__main__":
    import json
    print(json.dumps(qc(), indent=2))
