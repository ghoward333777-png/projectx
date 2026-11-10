"""VeriWave's readiness evaluation: how well it answers from the fact store on D:\\QB.

Two kinds of question:
* sampled: real Fact Units drawn at random from the store (UFCS stores, Commons, bulk shards) and asked about in
  several phrasings; the fact is known to be there, so a refusal is a retrieval failure and a citation that lacks the
  object is a wrong answer;
* curated: the person's own questions, one JSON object per line: {"question": "...", "expect": ["accepted answer", ...]}
  or {"question": "...", "expect_unknown": true} when the right response is "I don't know".

Scores: answer rate, accuracy of the answers given (any citation holds the expected object; and stricter, the
one-line answer does), wrong refusals, correct refusals, and response time (median and 95th percentile).
The evaluation runs only against a connected store: it refuses to run, and says why, when the store is absent or
empty. Every report records the store's path and its fact counts. Read-only, like every VeriWave access to D:\\QB.

Lean:
    inductive Outcome where | correct | wrong | wrongRefusal | correctRefusal | falseAnswer
    deriving Repr, BEq, DecidableEq
"""
from __future__ import annotations

import json
import os
import sqlite3
import time

from . import core, factstore, verdict

PHRASINGS = ["What is the {p} of {s}?", "{s} {p}", "Tell me about {s}"]
DEFAULT_ROOT = "D:\\QB"


def eval_root() -> str:
    """the store the evaluation must run against: D:\\QB, unless VERIWAVE_FACTS names another on purpose (tests, other drives)

    Lean:
        def evalRootOf (env : String) : String := if env == "" then "D:\\QB" else env
        #guard evalRootOf "" == "D:\\QB"                                       -- py: eval_root() == (os.environ.get("VERIWAVE_FACTS") or "D:\\QB")
    """
    return os.environ.get("VERIWAVE_FACTS") or DEFAULT_ROOT


def phrase(template: str, subject: str, predicate: str) -> str:
    """one question about a fact, in a template's words (Wikidata ids removed from the subject)

    Lean:
        def phraseOf (t s p : String) : String := (t.replace "{s}" s).replace "{p}" p
        #guard phraseOf "What is the {p} of {s}?" "Rome" "inception" == "What is the inception of Rome?"   -- py: phrase("What is the {p} of {s}?", "Rome (Q220)", "inception") == "What is the inception of Rome?"
    """
    return template.replace("{s}", verdict.strip_qids(subject)).replace("{p}", predicate)


def holds(text: str, expected: str) -> bool:
    """whether an answer text contains the expected value (case, spacing and Wikidata ids ignored)

    Lean:
        def squash (s : String) : String := ufcsNorm (norm s)
        def holdsIn (text exp : String) : Bool := squash exp != "" && ((squash text).splitOn (squash exp)).length > 1
        #guard holdsIn "printing press — inventor: Johannes Gutenberg" "johannes  GUTENBERG"   -- py: holds("printing press — inventor: Johannes Gutenberg", "johannes  GUTENBERG")
        #guard !holdsIn "anything" ""                                         -- py: not holds("anything", "")
    """
    e = " ".join(verdict.norm(expected).split())
    return bool(e) and e in " ".join(verdict.norm(text).split())


def outcome(res: dict, expect: list[str], expect_unknown: bool) -> str:
    """how one answer scores: correct, wrong, wrong refusal, correct refusal, or false answer (answered when it should not)

    Lean:
        def outcomeOf (unknown expectUnknown cited : Bool) : Outcome :=
          if expectUnknown then (if unknown then .correctRefusal else .falseAnswer)
          else if unknown then .wrongRefusal else if cited then .correct else .wrong
        theorem refusal_never_correct (c : Bool) : outcomeOf true false c = .wrongRefusal := rfl
        #guard outcomeOf false false true == .correct                         -- py: outcome({"verdict": "VERIFIED", "citations": [{"text": "x — p: Gutenberg"}]}, ["gutenberg"], False) == "correct"
        #guard outcomeOf true true false == .correctRefusal                   -- py: outcome({"verdict": "UNKNOWN", "citations": []}, [], True) == "correct refusal"
    """
    unknown = res.get("verdict") == "UNKNOWN"
    if expect_unknown:
        return "correct refusal" if unknown else "false answer"
    if unknown:
        return "wrong refusal"
    texts = [str(c.get("text") or "") for c in (res.get("citations") or [])]
    return "correct" if any(holds(t, e) for t in texts for e in expect) else "wrong"


def percentile(values: list[float], pct: int) -> float:
    """the pct-th percentile by the nearest-rank method (0 for no values)

    Lean:
        def rankIndex (n pct : Nat) : Nat := if n = 0 then 0 else (pct * n + 99) / 100 - 1
        #guard rankIndex 20 95 == 18                                          -- py: percentile([float(i) for i in range(1, 21)], 95) == 19.0
        #guard rankIndex 0 50 == 0                                            -- py: percentile([], 50) == 0.0
    """
    if not values:
        return 0.0
    v = sorted(values)
    k = max(0, (pct * len(v) + 99) // 100 - 1)
    return v[min(k, len(v) - 1)]


def summary(rows: list[dict]) -> dict:
    """the scores over all questions

    Lean:
        def answerRate (answered total : Nat) : Nat := if total = 0 then 0 else answered * 1000 / total
        theorem answerRate_none (a : Nat) : answerRate a 0 = 0 := by simp [answerRate]
        #guard answerRate 3 4 == 750                                          -- py: summary([{"outcome": "correct", "top": True, "ms": 1.0}, {"outcome": "correct", "top": False, "ms": 1.0}, {"outcome": "wrong", "top": False, "ms": 1.0}, {"outcome": "wrong refusal", "top": False, "ms": 1.0}])["answer_rate"] == 75.0
    """
    n = len(rows)
    count = lambda o: sum(1 for r in rows if r["outcome"] == o)
    correct, wrong, refused = count("correct"), count("wrong"), count("wrong refusal")
    answered = correct + wrong
    should_answer = correct + wrong + refused
    pct = lambda a, b: round(100.0 * a / b, 1) if b else 0.0
    ms = [float(r["ms"]) for r in rows]
    return {"questions": n, "answered": answered, "correct": correct, "wrong": wrong, "wrong_refusals": refused,
            "correct_refusals": count("correct refusal"), "false_answers": count("false answer"),
            "answer_rate": pct(answered, should_answer), "accuracy": pct(correct, answered),
            "top_answer_accuracy": pct(sum(1 for r in rows if r["outcome"] == "correct" and r.get("top")), answered),
            "wrong_refusal_rate": pct(refused, should_answer), "median_ms": round(percentile(ms, 50), 1), "p95_ms": round(percentile(ms, 95), 1)}


def sample_facts(fs: factstore.FactStore, n: int, seed: int) -> list[dict]:
    """n Fact Units drawn from the store, spread across its UFCS stores, Commons and bulk shards, deterministically for a seed

    Lean:
        def share (n stores i : Nat) : Nat := n / stores + (if i < n % stores then 1 else 0)
        theorem shares_sum2 (n : Nat) : share n 2 0 + share n 2 1 = n := by
          unfold share; split <;> split <;> omega
        #guard share 10 3 0 + share 10 3 1 + share 10 3 2 == 10               -- py: sample_facts(factstore.FactStore("/no/such/root"), 10, 1) == []
    """
    st = fs.status()
    sources: list[tuple[str, str, int]] = [("ufcs", u["path"], int(u["facts"])) for u in st["ufcs"] if u["facts"]]
    if st["commons"] and st["commons"]["facts"]:
        sources.append(("commons", fs.commons, int(st["commons"]["facts"])))
    sources += [("shard", s["path"], int(s["facts"])) for s in fs.shards if s["facts"]]
    if not sources:
        return []
    rng = core.Rng(seed)
    out: list[dict] = []
    for i, (kind, path, count) in enumerate(sources):
        want = n // len(sources) + (1 if i < n % len(sources) else 0)
        tries = 0
        while want > 0 and tries < want * 6:
            tries += 1
            f = draw(kind, path, count, rng, fs)
            if f is not None and f["object"] and f not in out:
                out.append(f)
                want -= 1
    return out


def draw(kind: str, path: str, count: int, rng: core.Rng, fs: factstore.FactStore) -> dict | None:
    """one random Fact Unit from one store: by rowid (UFCS), by id (Commons), or from a random fingerprint onward (shard)

    Lean:
        def pickRow (r : Rng) (count : Nat) : Nat := (r.below (max count 1)).1 + 1
        theorem pickRow_pos (r : Rng) (c : Nat) : 1 ≤ pickRow r c := by unfold pickRow; omega
    """
    try:
        if kind == "ufcs":
            conn = factstore.ro(os.path.join(path, "index.sqlite"))
            try:
                row = conn.execute("SELECT subject, predicate, object FROM nuc WHERE rowid >= ? LIMIT 1",
                                   (rng.below(max(count, 1)) + 1,)).fetchone()
            finally:
                conn.close()
            return None if row is None else {"subject": str(row[0]), "predicate": str(row[1]), "object": str(row[2]), "store": "UFCS " + path}
        if kind == "commons":
            conn = factstore.ro(path)
            try:
                row = conn.execute("SELECT subject, predicate, object FROM facts WHERE id >= ? LIMIT 1", (rng.below(max(count, 1)) + 1,)).fetchone()
            finally:
                conn.close()
            return None if row is None else {"subject": str(row[0]), "predicate": str(row[1]), "object": str(row[2]), "store": "Commons " + path}
        conn = factstore.ro(path)
        try:
            start = bytes(rng.below(256) for _ in range(16))
            row = conn.execute("SELECT s, p, o FROM facts WHERE fp >= ? LIMIT 1", (start,)).fetchone()
            name = ""
            if row is not None:
                pr = conn.execute("SELECT name FROM predicates WHERE id = ?", (int(row[1]),)).fetchone()
                name = str(pr[0]) if pr is not None else str(row[1])
        finally:
            conn.close()
        return None if row is None else {"subject": str(row[0]), "predicate": name, "object": str(row[2]), "store": "Shard " + path}
    except (sqlite3.Error, ValueError):
        return None


def load_curated(path: str) -> list[dict]:
    """the person's own questions (JSON lines); lines that are not a question object are skipped

    Lean:
        def isQuestion (hasQ : Bool) (q : String) : Bool := hasQ && q.trim != ""
        #guard !isQuestion true "  "                                          -- py: load_curated("/no/such/file.jsonl") == []
    """
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().split("\n")
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and str(obj.get("question") or "").strip():
            exp = obj.get("expect") or []
            out.append({"question": str(obj["question"]), "expect": [str(e) for e in (exp if isinstance(exp, list) else [exp])],
                        "expect_unknown": bool(obj.get("expect_unknown")), "kind": "curated"})
    return out


def plan(fs: factstore.FactStore, sample: int, seed: int, curated: list[dict]) -> list[dict]:
    """the questions to ask: every sampled fact in each phrasing, then the curated questions

    Lean:
        def planSize (facts phrasings curated : Nat) : Nat := facts * phrasings + curated
        #guard planSize 100 3 20 == 320                                       -- py: len(PHRASINGS) == 3
    """
    qs: list[dict] = []
    for f in sample_facts(fs, sample, seed):
        for t in PHRASINGS:
            qs.append({"question": phrase(t, f["subject"], f["predicate"]), "expect": [verdict.strip_qids(f["object"])],
                       "expect_unknown": False, "kind": "sampled", "phrasing": t, "fact": f})
    return qs + curated


def readiness_check(st: dict, root: str) -> str:
    """'' when the evaluation may run; otherwise why not (the store must be the one asked for, present and non-empty)

    Lean:
        def refuseReason (rootExists connected : Bool) (facts : Nat) : String :=
          if !rootExists then "missing" else if !connected then "no store" else if facts = 0 then "empty" else ""
        #guard refuseReason false false 0 == "missing"                        -- py: readiness_check({"root_exists": False, "connected": False, "facts": 0, "root": "D:\\QB"}, "D:\\QB").startswith("D:\\QB is not connected")
        #guard refuseReason true true 5 == ""                                 -- py: readiness_check({"root_exists": True, "connected": True, "facts": 5, "root": "D:\\QB"}, "D:\\QB") == ""
    """
    if not st.get("root_exists"):
        return root + " is not connected (the folder does not exist). Connect the drive and run the evaluation again."
    if not st.get("connected"):
        return "No fact store was found in " + root + " (no UFCS index.sqlite, commons\\commons.sqlite or commons\\shards)."
    if not st.get("facts"):
        return "The fact store in " + root + " is empty."
    if str(st.get("root") or "") != root:
        return "VeriWave is connected to " + str(st.get("root")) + ", not " + root + "."
    return ""


def report_name(at: int) -> str:
    """the file a report is saved under: eval-<unix time>.json

    Lean:
        def reportName (t : Nat) : String := "eval-" ++ toString t ++ ".json"
        #guard reportName 1794332709 == "eval-1794332709.json"               -- py: report_name(1794332709) == "eval-1794332709.json"
    """
    return "eval-" + str(at) + ".json"


def run(model: object, root: str, sample: int, seed: int, curated: list[dict], progress: object) -> dict:
    """ask every planned question through the full VeriWave pipeline and score it; refuses unless the store at root is connected

    Lean:
        #guard refuseReason true false 0 == "no store"                        -- py: readiness_check({"root_exists": True, "connected": False, "facts": 0, "root": "D:\\QB"}, "D:\\QB").startswith("No fact store")
    """
    fs = model.facts  # type: ignore[attr-defined]
    st = fs.status()
    why = readiness_check(st, root)
    started = int(time.time())
    base = {"at": started, "root": root, "store": {"facts": st.get("facts", 0), "ufcs": st.get("ufcs", []), "commons": st.get("commons"),
                                                    "shards": len(st.get("shards") or [])}, "seed": seed, "sample": sample}
    if why:
        return dict(base, ok=False, error=why, rows=[], summary=summary([]))
    qs = plan(fs, sample, seed, curated)
    rows: list[dict] = []
    for i, q in enumerate(qs):
        t0 = time.perf_counter()
        res = model.ask(q["question"], verdict.MIN_TRUST, "", "local", "Readiness evaluation.")  # type: ignore[attr-defined]
        ms = (time.perf_counter() - t0) * 1000
        oc = outcome(res, q["expect"], q["expect_unknown"])
        rows.append({"question": q["question"], "kind": q["kind"], "phrasing": q.get("phrasing", ""), "expect": q["expect"],
                     "outcome": oc, "top": any(holds(str(res.get("short") or ""), e) for e in q["expect"]),
                     "verdict": res.get("verdict"), "short": str(res.get("short") or "")[:200], "ms": round(ms, 1),
                     "trace_id": res.get("trace_id", ""), "store": (q.get("fact") or {}).get("store", "")})
        if progress is not None:
            progress(i + 1, len(qs))  # type: ignore[operator]
    by_phrasing = {t: summary([r for r in rows if r["phrasing"] == t]) for t in PHRASINGS}
    return dict(base, ok=True, error="", rows=rows, summary=summary(rows), by_phrasing=by_phrasing,
                curated=summary([r for r in rows if r["kind"] == "curated"]), seconds=int(time.time()) - started)
