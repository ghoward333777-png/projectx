"""QueryBook Education subsystem  [deterministic]  — Registry 8.6/8.9/8.10 (reader + educator)

Backend for the Learner/Reader experience and the Educator analytics dashboard. Builds on
qb_assess (item generation) and qb_ontology (concept maps). Grades attempts deterministically,
tracks per-learner mastery by competency, detects misconceptions (missed competencies), and
aggregates class/cohort analytics. Local git-ignored store; no LLM. Education manages records
and quizzes facts already in the store — it asserts no new world-facts.
"""

import json as _json, os as _os, time as _time

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_STORE = _os.path.join(_HERE, "qb_edu_store.json")

# Bundled example triples per domain so a lesson is never empty on a fresh store (clearly
# example content; real lessons draw from the live Fact-Unit store).
_SEED = {
    "history": [("year 1776", "recorded_event", "US Declaration of Independence"),
                ("year 1969", "recorded_event", "First Moon landing"),
                ("year 1215", "recorded_event", "Magna Carta sealed"),
                ("year 1945", "recorded_event", "Second World War ends")],
    "art": [("Mona Lisa", "painted_by", "Leonardo da Vinci"),
            ("The Starry Night", "painted_by", "Vincent van Gogh"),
            ("Guernica", "painted_by", "Pablo Picasso"),
            ("The Great Wave", "created_by", "Hokusai")],
    "culture": [("Haiku", "form", "Japanese 5-7-5 verse"),
                ("Flamenco", "origin", "Andalusia, Spain"),
                ("Capoeira", "origin", "Brazil"),
                ("Origami", "is_a", "Japanese paper folding")],
    "mathematics": [("2²", "equals", "4"), ("3²", "equals", "9"),
                    ("5²", "equals", "25"), ("10²", "equals", "100")],
}


def _load():
    try: return _json.load(open(_STORE, encoding="utf-8")) or {}
    except Exception: return {}
def _save(db):
    try:
        _json.dump(db, open(_STORE, "w", encoding="utf-8"))
        try: _os.chmod(_STORE, 0o600)
        except Exception: pass
    except Exception: pass
def _db():
    d = _load()
    d.setdefault("attempts", []); d.setdefault("learners", {}); d.setdefault("classes", {})
    return d


def generate_lesson(domain="history", count=5, store_dir="./mystore"):
    """A lesson = concept list (ontology) + assessment items (qb_assess). Falls back to bundled
    example triples when the live store has none for the domain."""
    import qb_assess, qb_ontology
    items = []
    try:
        items = qb_assess.from_store(store_dir, max_items=count, domain=domain)
    except Exception:
        items = []
    source = "store"
    if not items:
        tris = _SEED.get(domain) or _SEED["history"]
        items = qb_assess.items_from_triples(tris, max_items=count)
        source = "example"
    tris_for_graph = [(it["subject"], it["competency"], it["answer"]) for it in items]
    graph = qb_ontology.public(qb_ontology.build(tris_for_graph))
    comps = sorted({it["competency"] for it in items})
    return {"domain": domain, "source": source, "title": "Lesson — %s" % domain.capitalize(),
            "concepts": comps, "items": items, "concept_graph": graph,
            "note": "Items quiz verified Fact Units; a lesson asserts no new facts." +
                    (" (Example content — the live store has no %s facts yet.)" % domain if source == "example" else "")}


def grade_attempt(learner, domain, answers, class_id=None, store_dir="./mystore"):
    """answers: [{question, answer, competency, correct_answer}]. Grade deterministically, update
    learner mastery + engagement, record the attempt, return score + misconceptions."""
    learner = (learner or "anonymous").strip()
    total = len(answers) or 0
    correct = 0
    per_comp = {}
    misconceptions = []
    for a in answers:
        comp = a.get("competency", "general")
        ok = str(a.get("answer", "")).strip().lower() == str(a.get("correct_answer", "")).strip().lower()
        per_comp.setdefault(comp, {"seen": 0, "correct": 0})
        per_comp[comp]["seen"] += 1
        if ok: correct += 1; per_comp[comp]["correct"] += 1
        else: misconceptions.append({"question": a.get("question"), "competency": comp,
                                     "gave": a.get("answer"), "correct": a.get("correct_answer")})
    score = round(100.0 * correct / total, 1) if total else 0.0
    db = _db()
    ln = db["learners"].setdefault(learner, {"mastery": {}, "attempts": 0, "class": class_id})
    ln["attempts"] += 1
    if class_id: ln["class"] = class_id
    for comp, c in per_comp.items():
        m = ln["mastery"].setdefault(comp, {"seen": 0, "correct": 0})
        m["seen"] += c["seen"]; m["correct"] += c["correct"]
    db["attempts"].append({"learner": learner, "domain": domain, "score": score,
                           "total": total, "correct": correct, "class": class_id,
                           "when": int(_time.time())})
    if class_id:
        db["classes"].setdefault(class_id, {"members": []})
        if learner not in db["classes"][class_id]["members"]:
            db["classes"][class_id]["members"].append(learner)
    _save(db)
    return {"ok": True, "learner": learner, "domain": domain, "score": score,
            "correct": correct, "total": total,
            "mastery": {c: round(100.0 * m["correct"] / m["seen"], 1) if m["seen"] else 0.0
                        for c, m in ln["mastery"].items()},
            "misconceptions": misconceptions,
            "remediation": [m["competency"] for m in misconceptions]}


def learner_state(learner):
    db = _db(); ln = db["learners"].get((learner or "").strip())
    if not ln:
        return {"learner": learner, "known": False, "mastery": {}, "attempts": 0}
    mastery = {c: round(100.0 * m["correct"] / m["seen"], 1) if m["seen"] else 0.0
               for c, m in ln["mastery"].items()}
    overall = round(sum(mastery.values()) / len(mastery), 1) if mastery else 0.0
    return {"learner": learner, "known": True, "attempts": ln["attempts"], "class": ln.get("class"),
            "mastery": mastery, "overall": overall,
            "engagement": "high" if ln["attempts"] >= 5 else "medium" if ln["attempts"] >= 2 else "low"}


def class_analytics(class_id=None):
    """Educator view: class/cohort mastery, misconception clusters, engagement, cohort compare."""
    db = _db()
    classes = db["classes"]
    def agg(members):
        comp_tot, comp_cor, scores, att = {}, {}, [], 0
        for name in members:
            ln = db["learners"].get(name) or {"mastery": {}, "attempts": 0}
            att += ln.get("attempts", 0)
            for c, m in ln.get("mastery", {}).items():
                comp_tot[c] = comp_tot.get(c, 0) + m["seen"]; comp_cor[c] = comp_cor.get(c, 0) + m["correct"]
        for a in db["attempts"]:
            if a["learner"] in members: scores.append(a["score"])
        mastery = {c: round(100.0 * comp_cor[c] / comp_tot[c], 1) if comp_tot[c] else 0.0 for c in comp_tot}
        clusters = sorted(mastery.items(), key=lambda kv: kv[1])[:3]   # weakest competencies
        return {"members": len(members), "avg_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
                "attempts": att, "mastery": mastery,
                "misconception_clusters": [{"competency": c, "mastery": v} for c, v in clusters],
                "engagement": "high" if att >= 3 * max(1, len(members)) else "developing"}
    if class_id:
        members = classes.get(class_id, {}).get("members", [])
        return {"class": class_id, **agg(members)}
    # all classes + cohort comparison
    out = {"classes": [{"class": cid, **agg(c.get("members", []))} for cid, c in classes.items()],
           "total_learners": len(db["learners"]), "total_attempts": len(db["attempts"])}
    out["cohort_comparison"] = sorted([{"class": c["class"], "avg_score": c["avg_score"],
                                        "members": c["members"]} for c in out["classes"]],
                                      key=lambda x: -x["avg_score"])
    return out


def study_guide(domain="history", store_dir="./mystore"):
    les = generate_lesson(domain, count=8, store_dir=store_dir)
    import qb_assess
    tris = [(it["subject"], it["competency"], it["answer"]) for it in les["items"]]
    return qb_assess.study_guide(tris, title="Study guide — %s" % domain.capitalize())


def qc():
    global _STORE; orig = _STORE; _STORE = orig + ".qc"
    try:
        try: _os.remove(_STORE)
        except OSError: pass
        checks = []
        les = generate_lesson("art", 4)
        ck = lambda n, c: checks.append({"check": n, "pass": bool(c)})
        ck("lesson has items", len(les["items"]) >= 3)
        ck("lesson has concept graph", les["concept_graph"]["counts"]["nodes"] >= 3)
        it = les["items"][0]
        # one correct, one wrong
        ans = [{"question": it["question"], "answer": it["answer"], "competency": it["competency"],
                "correct_answer": it["answer"]},
               {"question": les["items"][1]["question"], "answer": "WRONG",
                "competency": les["items"][1]["competency"], "correct_answer": les["items"][1]["answer"]}]
        g = grade_attempt("alice", "art", ans, class_id="class-1")
        ck("graded 50%", g["score"] == 50.0)
        ck("misconception recorded", len(g["misconceptions"]) == 1)
        st = learner_state("alice")
        ck("learner state known", st["known"] and st["attempts"] == 1)
        ca = class_analytics("class-1")
        ck("class analytics", ca["members"] == 1 and "misconception_clusters" in ca)
        ck("cohort compare", "classes" in class_analytics())
        passed = sum(1 for c in checks if c["pass"])
        return {"passed": passed, "total": len(checks), "ok": passed == len(checks), "rows": checks}
    finally:
        try: _os.remove(_STORE)
        except OSError: pass
        _STORE = orig


if __name__ == "__main__":
    import json; print(json.dumps(qc(), indent=2))
