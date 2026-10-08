"""QueryBook middleware — provenance firewall for AI pipelines  [deterministic]

Sits between an application and an LLM. Every CLAIM a model makes is checked against the
Fact-Unit store before it reaches the user: VERIFIED (a stored fact corroborates it),
CONTRADICTED (a stored fact for the same subject+predicate disagrees), or UNKNOWN (no fact on
record). This is the covenant as a guardrail — a model cannot launder a guess through
QueryBook. Deterministic given the store.
"""

import re as _re

def _triple(text):
    """Very light claim parse: 'X <pred> Y' using qb_query predicate cues + first/last entity."""
    import qb_query
    ents = qb_query.entities(text)
    pred = qb_query.predicate(text)
    subj = ents[0] if ents else None
    # object = the next distinct entity after the subject (capitalized/quoted spans rank first)
    obj = ents[1] if len(ents) >= 2 else None
    return subj, pred, obj

def _store_lookup(store_dir):
    import ufcs_store
    def lookup(subject, predicate):
        try:
            st = ufcs_store.UFCSStore(store_dir)
            objs = set()
            for rec in st.iter_all():
                if str(rec.get("subject", "")).lower() == str(subject).lower() and \
                   str(rec.get("predicate", "")).lower() == str(predicate).lower():
                    objs.add(str(rec.get("object")))
            st.close()
            return objs
        except Exception:
            return set()
    return lookup

def verify_claim(text, lookup=None, store_dir=None):
    """Classify a single claim VERIFIED / CONTRADICTED / UNKNOWN against the store."""
    if lookup is None:
        lookup = _store_lookup(store_dir or "./mystore")
    subj, pred, obj = _triple(text)
    if not subj or obj is None:
        return {"claim": text, "verdict": "UNKNOWN", "reason": "could not parse a checkable triple"}
    objs = lookup(subj, pred)
    if not objs:
        return {"claim": text, "verdict": "UNKNOWN", "subject": subj, "predicate": pred,
                "reason": "no fact on record for this subject+predicate"}
    norm = {o.lower() for o in objs}
    if obj.lower() in norm:
        return {"claim": text, "verdict": "VERIFIED", "subject": subj, "predicate": pred,
                "object": obj, "supported_by": sorted(objs)}
    return {"claim": text, "verdict": "CONTRADICTED", "subject": subj, "predicate": pred,
            "claimed": obj, "on_record": sorted(objs)}

def guard(model_output, lookup=None, store_dir=None):
    """Split model text into sentence-claims and verify each; summarize the gate decision."""
    claims = [s.strip() for s in _re.split(r"(?<=[.!?])\s+", model_output or "") if s.strip()]
    results = [verify_claim(c, lookup=lookup, store_dir=store_dir) for c in claims]
    counts = {"VERIFIED": 0, "CONTRADICTED": 0, "UNKNOWN": 0}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    decision = ("block" if counts["CONTRADICTED"] else ("flag" if counts["UNKNOWN"] else "pass"))
    return {"decision": decision, "counts": counts, "claims": results,
            "note": "block = a claim contradicts the store; flag = unverifiable; pass = all corroborated."}

def qc():
    facts = {("France", "capital_of"): {"Paris"}, ("Hamlet", "author"): {"Shakespeare"}}
    lookup = lambda s, p: facts.get((s, p), set())
    checks = []
    v = verify_claim("France capital_of Paris", lookup=lookup)
    checks.append(("verified", v["verdict"] == "VERIFIED"))
    c = verify_claim("France capital_of Berlin", lookup=lookup)
    checks.append(("contradicted", c["verdict"] == "CONTRADICTED"))
    u = verify_claim("Spain capital_of Madrid", lookup=lookup)
    checks.append(("unknown", u["verdict"] == "UNKNOWN"))
    g = guard("France capital_of Paris. France capital_of Berlin.", lookup=lookup)
    checks.append(("guard blocks on contradiction", g["decision"] == "block"))
    passed = sum(1 for _, c2 in checks if c2)
    return {"passed": passed, "total": len(checks), "ok": passed == len(checks),
            "rows": [{"check": n, "pass": c2} for n, c2 in checks]}

if __name__ == "__main__":
    import json; print(json.dumps(qc(), indent=2))
