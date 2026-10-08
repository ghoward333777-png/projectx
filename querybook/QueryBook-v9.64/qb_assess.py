"""Assessment generator  [deterministic]  — Registry features 8.6.x (081–096)

Turns verified Fact Units into assessment items: a question from (subject, predicate), the
correct answer (object), and DISTRACTORS drawn from other objects sharing the same predicate
(so they are plausible and from the same category). Each item carries a difficulty estimate,
a competency tag (the predicate), and provenance. Fully deterministic — same facts, same items
— and non-asserting: it only quizzes facts already in the store.
"""

import re as _re

_Q = {
    "author": "Who is the author of %s?",
    "painted_by": "Who painted %s?",
    "capital_of": "What is the capital of %s?",
    "means": "What does \"%s\" mean?",
    "equals": "What does %s equal?",
    "in_century": "In which century is %s?",
    "days_in_common_year": "How many days are in %s (common year)?",
    "recorded_event": "What event is recorded for %s?",
}

def _question(subject, predicate):
    tmpl = _Q.get(predicate)
    if tmpl:
        return tmpl % subject
    pred = predicate.replace("_", " ")
    return "What is the %s of %s?" % (pred, subject)

def _difficulty(answer, distractors):
    """Heuristic 1–5: more / closer distractors + longer answer => harder."""
    d = min(4, len(distractors))
    if any(abs(len(str(x)) - len(str(answer))) <= 1 for x in distractors):
        d += 1
    return max(1, min(5, d))

def items_from_triples(triples, max_items=50, distractors=3):
    """Build assessment items from (subject, predicate, object[, source]) tuples."""
    by_pred = {}
    rows = []
    for t in triples:
        s, p, o = t[0], t[1], t[2]
        src = t[3] if len(t) > 3 else None
        rows.append((str(s), str(p), str(o), src))
        by_pred.setdefault(str(p), [])
        if str(o) not in by_pred[str(p)]:
            by_pred[str(p)].append(str(o))
    items = []
    for s, p, o, src in rows[:max_items]:
        pool = [x for x in by_pred.get(p, []) if x != o]
        picks = pool[:distractors]                       # deterministic: first N distinct
        opts = sorted([o] + picks)                       # stable order
        items.append({
            "question": _question(s, p), "answer": o, "options": opts,
            "competency": p, "difficulty": _difficulty(o, picks),
            "provenance": src, "subject": s,
        })
    return items

def from_store(store_dir, max_items=50, domain=None):
    try:
        import ufcs_store
        st = ufcs_store.UFCSStore(store_dir)
        tris = []
        for rec in st.iter_all():
            if domain and rec.get("domain") != domain:
                continue
            s, p, o = rec.get("subject"), rec.get("predicate"), rec.get("object")
            if s is not None and p is not None and o is not None:
                src = (rec.get("source") or [None])[0] if isinstance(rec.get("source"), list) else rec.get("source")
                tris.append((s, p, o, src))
            if len(tris) >= max_items * 4:
                break
        st.close()
        return items_from_triples(tris, max_items=max_items)
    except Exception as ex:
        return []

def study_guide(triples, title="Study guide"):
    """A deterministic study guide: group facts by predicate (competency) into sections."""
    sections = {}
    for t in triples:
        s, p, o = str(t[0]), str(t[1]), str(t[2])
        sections.setdefault(p, []).append("%s — %s" % (s, o))
    return {"title": title,
            "sections": [{"competency": p, "points": pts} for p, pts in sorted(sections.items())]}


def qc():
    tris = [("Hamlet", "author", "Shakespeare"), ("Macbeth", "author", "Shakespeare"),
            ("War and Peace", "author", "Tolstoy"), ("The Trial", "author", "Kafka"),
            ("France", "capital_of", "Paris"), ("Japan", "capital_of", "Tokyo")]
    items = items_from_triples(tris)
    checks = []
    checks.append(("items generated", len(items) == 6))
    auth = next(i for i in items if i["subject"] == "Hamlet")
    checks.append(("question phrased", auth["question"].startswith("Who is the author")))
    checks.append(("answer present in options", auth["answer"] in auth["options"]))
    checks.append(("distractors same predicate", "Tolstoy" in auth["options"] or "Kafka" in auth["options"]))
    sg = study_guide(tris)
    checks.append(("study guide sections", len(sg["sections"]) == 2))
    passed = sum(1 for _, c in checks if c)
    return {"passed": passed, "total": len(checks), "ok": passed == len(checks),
            "rows": [{"check": n, "pass": c} for n, c in checks]}


if __name__ == "__main__":
    import json
    print(json.dumps(qc(), indent=2))
