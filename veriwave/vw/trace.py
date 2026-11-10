"""VeriWave's reasoning trace: for every prompt, each kind of logic, reasoning, decision and analysis the QueryBook Bible
documents, with what VeriWave did under it for that prompt.

A trace is a list of stages in the order they ran. Each stage names its logic types and the Bible chapters that specify
them, says whether it ran, took no part (not applicable to this prompt) or is specified in the Bible but not built in
VeriWave, how long it took (a Processor Slice, Ch. 69), and the data it worked on: the question as understood, every
Fact Unit with its UFCS packet tracking (stored and recomputed semantic fingerprint, block, store), its Ontology Mesh
links, the trust gate, the consistency check, the verdict, the provenance hash. Every Bible logic type appears in every
trace, so nothing is hidden by omission.

Source: QueryBook Bible v2.1 (Pass 120) and the Core Technology Overview it is summarised in (querybook-one
qbselfknow.py). Pure: built from what the model hands over; no I/O.

Lean:
    inductive Status where | ran | notApplicable | specified
    deriving Repr, BEq, DecidableEq
    def Status.name : Status → String
      | .ran => "ran" | .notApplicable => "not applicable" | .specified => "specified, not built"
    structure Stage where
      id : String
      logic : List String
      status : Status
      ms : Nat
    deriving Repr
    def LOGIC_COUNT : Nat := 18
"""
from __future__ import annotations

from . import core, factstore, verdict

# id, name, Bible chapters, what the Bible says, how VeriWave carries it, and whether VeriWave has it at all
LOGIC_TYPES: list[dict] = [
    {"id": "deterministic", "name": "Deterministic logic", "chapters": "Ch. 5 Provenance Ledger · §6 Deterministic Provenance · Ch. 124 Context Lock",
     "bible": "The same inputs give the same result; identity is computed from content, and determinism is asserted on enumerated dimensions.",
     "veriwave": "Rule-based routing and look-up; seeded generators; a SHA-256 provenance hash over the question and every citation.", "built": True},
    {"id": "atomic", "name": "Atomic logic (the Fact Unit)", "chapters": "Ch. 3 Fact Unit Structure · Ch. 57 Below-Language Meaning Storage",
     "bible": "The Fact Unit is the atomic, indivisible assertion record: nucleus, polarity, FUID, semantic fingerprint, sources, trust, temporal and safety fields.",
     "veriwave": "Every cited fact is a Fact Unit; UFCS packets are tracked by semantic fingerprint and block.", "built": True},
    {"id": "interpretive", "name": "Interpretive logic", "chapters": "Ch. 50 NLIL · Ch. 109 The Interpretive Layer · Ch. 37 Conversational Intelligence",
     "bible": "Natural language is interpreted into a structured request; context and perspective modulate an already-admissible result.",
     "veriwave": "The router chooses the capability; QueryBook's ask.understand extracts kind, subject, spellings and the predicate hints.", "built": True},
    {"id": "transport", "name": "UFCS/FQL retrieval", "chapters": "Ch. 81 UFCS/FQL · Ch. 9 Semantic Transport Layer · Ch. 18 QB-Query Language",
     "bible": "Fact Units travel as UFCS packets and are queried by structure (FQL); a result carries a response provenance hash.",
     "veriwave": "Index look-ups on every UFCS store, the Commons and the bulk shards (read-only), with the RPH over the fingerprints returned.", "built": True},
    {"id": "relational", "name": "Relational logic (Ontology Mesh linkage)", "chapters": "Ch. 6 Ontology Mesh · §54.6 Inheritance and Inverse Traversal",
     "bible": "Fact Units are joined by typed, weighted adjacency; traversal follows the mesh.",
     "veriwave": "For each cited Fact Unit: its siblings (same subject) and onward links (facts about its object), one hop.", "built": True},
    {"id": "confidence", "name": "Confidence calibration", "chapters": "Ch. 41 Confidence Scoring · §41.6.2 Bayesian ConfidenceScore · §41.6.5 Observation Diversity",
     "bible": "Confidence is a Beta posterior over supporting and contradicting evidence; concentrated corroboration is discounted.",
     "veriwave": "A single trust score per fact and a trust gate (default 50%); observation diversity counted as distinct sources. The Beta pair is not built yet.", "built": True},
    {"id": "consistency", "name": "Cross-domain consistency", "chapters": "Ch. 17 Cross-Domain Rule Engine · §4 Cross-Domain Consistency",
     "bible": "Contradictions between Fact Units are detected and surfaced, never silently resolved.",
     "veriwave": "A functional predicate with two different values for one subject makes the answer CONTRADICTED, with every value shown.", "built": True},
    {"id": "deductive", "name": "Deductive reasoning", "chapters": "Ch. 108 Reasoning Mode Formalization",
     "bible": "Deduction from verified premises may write: derived facts carry their premises.",
     "veriwave": "The verdict follows from the offered premises by fixed rules; exact arithmetic is derived step by step (tokens, reverse Polish order, rationals).", "built": True},
    {"id": "inductive", "name": "Inductive reasoning", "chapters": "Ch. 108 Reasoning Mode Formalization · Ch. 110 Outcome Feedback",
     "bible": "Induction generalises from observations and may not write; feedback is evidence, not correction.",
     "veriwave": "Not used to answer: an answer never generalises beyond its cited facts.", "built": False},
    {"id": "abductive", "name": "Abductive reasoning (hypothesis)", "chapters": "Ch. 108 Reasoning Mode Formalization · Ch. 97 Hypothesis Generation",
     "bible": "Abduction proposes the best explanation; hypotheses are isolated at low trust and never asserted.",
     "veriwave": "Not built in VeriWave (QueryBook 9.64's hypothesis agent proposes; it never asserts).", "built": False},
    {"id": "neuromorphic", "name": "Neuromorphic logic (NCL)", "chapters": "Ch. 7 Neuromorphic Cognitive Layer · Ch. 116 Attractor Stabilization · Ch. 95 Complementary Learning Systems · Ch. 101",
     "bible": "STDP and Hebbian strengthening, attractor dynamics and HTM stabilise retrieval, learning from each query without forgetting.",
     "veriwave": "Specified, not built: retrieval is deterministic index look-up; no attractor or plasticity runs.", "built": False},
    {"id": "predictive", "name": "Predictive inference", "chapters": "Ch. 10 Predictive Inference Engine · Ch. 41 PCA · Ch. 103 Temporal Prediction Calibration · Ch. 122",
     "bible": "Predictions are made, scored against what happens and calibrated over time, with precision-weighted error.",
     "veriwave": "Specified, not built: VeriWave makes no predictions.", "built": False},
    {"id": "scenario", "name": "Scenario and simulation", "chapters": "Ch. 11 Scenario Graph · Ch. 117 Systematic Trial Architecture",
     "bible": "Scenarios are explored and trials run over a metered budget; trials discover and never apply.",
     "veriwave": "Specified, not built in VeriWave.", "built": False},
    {"id": "temporal", "name": "Temporal scope", "chapters": "Ch. 123 Differentiated Propagation and Tri-Temporal Scope",
     "bible": "Attested past, live present and projected future are distinct postures.",
     "veriwave": "Answers take the attested-past posture: facts as stored; nothing is projected.", "built": True},
    {"id": "safety", "name": "Safety and the Prime Directive", "chapters": "Ch. 8 Safety Substrate · §10 The Prime Directive · §96.10 Analysis Quarantine",
     "bible": "Nothing ungrounded is asserted; the system refuses rather than guesses.",
     "veriwave": "Cite-or-refuse: no fact at or above the trust threshold, no answer (UNKNOWN); unsafe files and SVG are rejected.", "built": True},
    {"id": "expressive", "name": "Expressive register and surface realization", "chapters": "Ch. 111 Expressive Register · Ch. 112 Surface Realization",
     "bible": "A grounded result is realised in words under a governed register, without changing what it asserts.",
     "veriwave": "The one-line answer is the fact whose predicate answers the question; Claude may reword cited facts only.", "built": True},
    {"id": "generative", "name": "Generative regeneration", "chapters": "Ch. 16 Multilingual Regeneration Engine · Ch. 39 Application Library and Generator",
     "bible": "Output is regenerated from grounded knowledge; applications are instantiated from narrow-scope templates.",
     "veriwave": "Code, text, images, video and audio from deterministic generators (seeded by the prompt) or Claude, under file and SVG safety checks.", "built": True},
    {"id": "metering", "name": "Processor Slice measurement", "chapters": "Ch. 69 Processor Slice Measurement Model",
     "bible": "Every unit of work is a bounded, atomic, measured event in a defined category (Ingestion, Reasoning, Response Generation, Safety Gate …).",
     "veriwave": "Each stage of every prompt is timed and filed under its category.", "built": True},
]
LOGIC_IDS = [t["id"] for t in LOGIC_TYPES]


def stage(sid: str, name: str, logic: list[str], status: str, ms: float, category: str, summary: str, data: dict) -> dict:
    """one stage of a trace

    Lean:
        def mkStage (id : String) (logic : List String) (st : Status) (ms : Nat) : Stage := ⟨id, logic, st, ms⟩
        #guard (mkStage "retrieve" ["transport"] .ran 3).ms == 3            -- py: stage("retrieve", "R", ["transport"], "ran", 3.0, "Ingestion", "", {})["ms"] == 3.0
    """
    return {"id": sid, "name": name, "logic": logic, "status": status, "ms": round(ms, 2), "category": category,
            "summary": summary, "data": data}


def logic_summary(stages: list[dict]) -> list[dict]:
    """every Bible logic type with its status in this trace: ran (and in which stages), not applicable, or specified

    Lean:
        def statusOf (built : Bool) (ranIn : List String) : Status :=
          if !ranIn.isEmpty then .ran else if built then .notApplicable else .specified
        theorem ran_wins (b : Bool) (x : String) (xs : List String) : statusOf b (x :: xs) = .ran := rfl
        #guard statusOf false [] == .specified                                 -- py: [x["status"] for x in logic_summary([]) if x["id"] == "neuromorphic"] == ["specified, not built"]
        #guard statusOf true [] == .notApplicable                              -- py: [x["status"] for x in logic_summary([]) if x["id"] == "atomic"] == ["not applicable"]
    """
    out: list[dict] = []
    for t in LOGIC_TYPES:
        ran_in = [s["name"] for s in stages if s["status"] == "ran" and t["id"] in s["logic"]]
        status = "ran" if ran_in else "not applicable" if t["built"] else "specified, not built"
        out.append({"id": t["id"], "name": t["name"], "chapters": t["chapters"], "bible": t["bible"], "veriwave": t["veriwave"],
                    "status": status, "stages": ran_in})
    return out


def slices(stages: list[dict]) -> list[dict]:
    """Processor Slices: total time per category, in the order the categories first appear

    Lean:
        def sliceTotal (ms : List Nat) : Nat := ms.foldl (· + ·) 0
        #guard sliceTotal [2, 3, 5] == 10                                      -- py: slices([stage("a", "A", [], "ran", 2.0, "Reasoning", "", {}), stage("b", "B", [], "ran", 3.0, "Reasoning", "", {})]) == [{"category": "Reasoning", "ms": 5.0, "stages": 2}]
    """
    order: list[str] = []
    total: dict[str, float] = {}
    count: dict[str, int] = {}
    for s in stages:
        if s["status"] != "ran":
            continue
        c = str(s["category"])
        if c not in total:
            order.append(c)
            total[c] = 0.0
            count[c] = 0
        total[c] += float(s["ms"])
        count[c] += 1
    return [{"category": c, "ms": round(total[c], 2), "stages": count[c]} for c in order]


def sources_count(citations: list[dict]) -> int:
    """observation diversity (§41.6.5) as VeriWave can measure it: the number of distinct sources among the citations

    Lean:
        def distinctCount : List String → Nat
          | [] => 0
          | x :: xs => (if xs.contains x then 0 else 1) + distinctCount xs
        #guard distinctCount ["a", "b", "a"] == 2                              -- py: sources_count([{"where": "a"}, {"where": "b"}, {"where": "a"}]) == 2
    """
    seen: list[str] = []
    for c in citations:
        w = str(c.get("where") or "")
        if w not in seen:
            seen.append(w)
    return len(seen)


def calc_steps(question: str) -> dict:
    """the deductive derivation of an arithmetic answer: the expression, its tokens, reverse Polish order and the exact value

    Lean:
        #guard calculate "2+3*4" == some "14"                                  -- py: calc_steps("2+3*4")["rpn"] == "2 3 4 * +"
    """
    expr = verdict.prepare(question)
    toks = verdict.tokenize(expr)
    if not toks:
        return {}
    rpn = verdict.to_rpn(toks)
    show = lambda t: (str(t[1]) if t[2] == 1 else str(t[1]) + "/" + str(t[2])) if t[0] == "n" else ("neg" if t[0] == "~" else t[0])
    value = verdict.eval_rpn(rpn) if rpn is not None else None
    return {"expression": expr, "tokens": " ".join(show(t) for t in toks), "rpn": " ".join(show(t) for t in rpn) if rpn is not None else "",
            "exact": (str(value[0]) + "/" + str(value[1])) if value is not None else "", "value": verdict.fmt_q(value) if value is not None else ""}


def answer_trace(tid: str, at: int, prompt: str, route: dict, intent: dict, qb: dict, drive: list[dict], res: dict,
                 links: list[dict], timings: dict[str, float], engine: str) -> dict:
    """the full trace of an answered (or refused) question

    Lean:
        def answerStages : Nat := 15
        #guard answerStages == 15                                              -- py: len(answer_trace("t", 0, "q", {"route": "answer", "reason": ""}, {}, {}, [], {"citations": [], "verdict": "UNKNOWN", "conflicts": []}, [], {}, "local")["stages"]) == 15
    """
    cites = list(res.get("citations") or [])
    t = lambda k: float(timings.get(k, 0.0))
    stages: list[dict] = []
    stages.append(stage("route", "Route the prompt", ["interpretive", "deterministic"], "ran", t("route"), "Reasoning",
                        "Chosen: " + str(route.get("route")) + ". " + str(route.get("reason") or ""), route))
    stages.append(stage("understand", "Understand the question", ["interpretive"], "ran", t("understand"), "Reasoning",
                        "A " + str(intent.get("kind") or "?") + " question about “" + str(intent.get("subject") or "") + "”"
                        + (" (follow-up resolved to: " + str(res.get("resolved")) + ")" if res.get("resolved") else ""),
                        {"kind": intent.get("kind"), "subject": intent.get("subject"), "spellings": intent.get("variants") or [],
                         "predicate_hints": intent.get("hints") or [], "resolved_follow_up": res.get("resolved") or ""}))
    asked_apps = [a for a in (qb.get("asked") or []) if a != "ufcs"]
    fps = [str((f.get("packet") or {}).get("fp") or "") for f in drive if (f.get("packet") or {}).get("kind") == "ufcs"]
    stores = sorted({str((f.get("packet") or {}).get("store") or "") for f in drive})
    fql = ["FQL Facts WHERE subject = “" + str(v) + "” ORDER BY trust DESC" for v in (intent.get("variants") or [intent.get("subject") or ""])[:3]]
    stages.append(stage("retrieve", "Retrieve Fact Units (UFCS/FQL)", ["transport", "atomic"],
                        "ran" if drive or asked_apps else "not applicable", t("retrieve"), "Ingestion",
                        str(len(drive)) + " Fact Unit(s) from the data drive" + ((", plus QueryBook's applications: " + ", ".join(asked_apps)) if asked_apps else ""),
                        {"fql": fql, "stores": stores, "applications_asked": asked_apps,
                         "applications_not_answering": [u.get("source") for u in (qb.get("unavailable") or [])],
                         "rph": factstore.rph(fps) if fps else "", "rph_input": factstore.rph_input(fps) if fps else ""}))
    packets = [dict(factstore.verify_packet(f), trust=int(f.get("trust") or 0), where=str(f.get("where") or "")) for f in drive]
    verified = sum(1 for p in packets if p["verified"])
    stages.append(stage("packets", "Track UFCS packets", ["atomic", "deterministic"], "ran" if packets else "not applicable", t("packets"),
                        "Reasoning", str(len(packets)) + " packet(s); " + str(verified) + " semantic fingerprint(s) recomputed and verified", {"packets": packets}))
    nlinks = sum(len(l.get("siblings") or []) + len(l.get("onward") or []) for l in links)
    stages.append(stage("linkage", "Link Fact Units (Ontology Mesh)", ["relational"], "ran" if links else "not applicable", t("linkage"),
                        "Reasoning", str(nlinks) + " linked Fact Unit(s) one hop from the cited ones", {"links": links}))
    trusts = [{"n": c.get("n"), "text": c.get("text"), "trust": c.get("trust"), "where": c.get("where")} for c in cites]
    stages.append(stage("gate", "Trust gate and observation diversity", ["confidence", "safety"], "ran" if cites or res.get("withheld") else "not applicable",
                        t("compose") / 3, "Safety Gate",
                        str(len(cites)) + " offered at or above " + str(res.get("min_trust", verdict.MIN_TRUST)) + "%, " + str(res.get("withheld") or 0)
                        + " held back; " + str(sources_count(cites)) + " distinct source(s)",
                        {"threshold": res.get("min_trust", verdict.MIN_TRUST), "offered": trusts, "withheld": res.get("withheld") or 0,
                         "distinct_sources": sources_count(cites)}))
    stages.append(stage("consistency", "Check consistency", ["consistency"], "ran" if cites else "not applicable", t("compose") / 3, "Reasoning",
                        (str(len(res.get("conflicts") or [])) + " contradiction(s)") if cites else "Nothing to check",
                        {"conflicts": res.get("conflicts") or [], "rule": "a functional predicate with two different values for one subject"}))
    calc = calc_steps(str(res.get("resolved") or prompt)) if any(c.get("kind") == "calculation" for c in cites) else {}
    stages.append(stage("deduce", "Deduce the verdict", ["deductive", "deterministic"], "ran", t("compose") / 3, "Reasoning",
                        "Verdict " + str(res.get("verdict")) + " from " + str(len(cites)) + " premise(s)",
                        {"verdict": res.get("verdict"), "premises": [c.get("n") for c in cites],
                         "rule": "UNKNOWN with no premise; CONTRADICTED when the consistency check finds one; VERIFIED otherwise",
                         "derivation": calc}))
    stages.append(stage("induce", "Induction and abduction", ["inductive", "abductive"], "not applicable", 0.0, "Reasoning",
                        "Not used: Ch. 108 lets deduction write; induction and abduction may only propose, never answer", {}))
    stages.append(stage("neuromorphic", "Neuromorphic stabilization (NCL)", ["neuromorphic"], "specified, not built", 0.0, "Reasoning",
                        "Specified in Ch. 7 and Ch. 116; retrieval here was a deterministic index look-up instead", {}))
    stages.append(stage("predict", "Prediction and scenarios", ["predictive", "scenario"], "specified, not built", 0.0, "Reasoning",
                        "Specified in Ch. 10, 11, 41, 103, 117 and 122; no prediction or simulation is made", {}))
    stages.append(stage("temporal", "Temporal scope", ["temporal"], "ran" if cites else "not applicable", 0.0, "Reasoning",
                        "Attested past: every premise is a stored fact; nothing projected", {"posture": "attested past"}))
    refused = res.get("verdict") == "UNKNOWN"
    stages.append(stage("directive", "Cite or refuse (Prime Directive)", ["safety"], "ran", 0.0, "Safety Gate",
                        "Refused: no fact at or above the threshold" if refused else "Answered: every line is cited",
                        {"decision": "refuse" if refused else "answer", "short": res.get("short")}))
    stages.append(stage("express", "Realize the answer", ["expressive"], "ran", t("express"), "Response Generation",
                        "Reworded by Claude from the cited facts only" if engine == "local+claude" else "Stated from the fact whose predicate answers the question",
                        {"short": res.get("short"), "prose": res.get("prose") or "", "engine": engine}))
    stages.append(stage("provenance", "Provenance and the Context Lock", ["deterministic"], "ran", 0.0, "Reasoning",
                        "The same question over the same facts gives the same hash",
                        {"provenance": res.get("provenance"), "covers": "the question, then each citation's text, source and link"}))
    return finish({"id": tid, "at": at, "prompt": prompt, "route": route.get("route"), "kind": "answer", "verdict": res.get("verdict"),
                   "short": res.get("short"), "stages": stages, "packets": packets})


def creation_trace(tid: str, at: int, prompt: str, route: dict, engine: str, result: dict, timings: dict[str, float]) -> dict:
    """the trace of a creation (code, text, image, video, audio), an 'open screen' request or small talk

    Lean:
        def creationStages : Nat := 7
        #guard creationStages == 7                                             -- py: len(creation_trace("t", 0, "hi", {"route": "chat", "reason": ""}, "local", {}, {})["stages"]) == 7
    """
    t = lambda k: float(timings.get(k, 0.0))
    rt = str(route.get("route"))
    making = rt in ("code", "text", "image", "video", "audio")
    stages: list[dict] = []
    stages.append(stage("route", "Route the prompt", ["interpretive", "deterministic"], "ran", t("route"), "Reasoning",
                        "Chosen: " + rt + ". " + str(route.get("reason") or ""), route))
    seed = core.seed_of(prompt)
    stages.append(stage("engine", "Choose the engine", ["deterministic"], "ran", 0.0, "Reasoning",
                        "Engine: " + engine + ("" if engine != "local" else "; deterministic, seed " + str(seed)),
                        {"engine": engine, "seed": seed, "seed_rule": "FNV-1a 32-bit of the prompt, then xorshift32"}))
    facts = list(result.get("sources") or [])
    stages.append(stage("ground", "Ground in Fact Units", ["atomic", "transport"], "ran" if facts else "not applicable", t("ground"), "Ingestion",
                        (str(len(facts)) + " QueryBook fact(s) used") if facts else "No facts needed for this creation",
                        {"sources": facts, "grounded": result.get("grounded", 0)}))
    detail = {k: v for k, v in result.items() if k in ("kind", "title", "form", "subject", "elements", "light", "scale", "tempo", "key",
                                                         "notes", "seconds", "effect", "entry", "layout", "interface", "name")}
    stages.append(stage("generate", "Generate", ["generative", "deterministic"], "ran" if making else "not applicable", t("generate"),
                        "Response Generation", ("Made by " + ("Claude" if result.get("engine") == "claude" else "the local generator")) if making else "Nothing generated",
                        detail))
    stages.append(stage("safety", "Safety checks", ["safety"], "ran" if making else "not applicable", 0.0, "Safety Gate",
                        "Files kept inside their folder; pictures and films carry no scripts or links" if making else "Nothing to check",
                        {"note": result.get("engine_note") or ""}))
    stages.append(stage("store", "Record the creation", ["deterministic", "atomic"], "ran" if result.get("id") else "not applicable", 0.0,
                        "Response Generation", ("Saved as " + str(result.get("id"))) if result.get("id") else "Nothing saved",
                        {"id": result.get("id") or "", "files": sorted((result.get("urls") or {}).keys()) if isinstance(result.get("urls"), dict) else []}))
    stages.append(stage("neuromorphic", "Neuromorphic and predictive layers", ["neuromorphic", "predictive", "scenario", "inductive", "abductive"],
                        "specified, not built", 0.0, "Reasoning", "Specified in the Bible; not built in VeriWave", {}))
    return finish({"id": tid, "at": at, "prompt": prompt, "route": rt, "kind": "creation", "verdict": "", "short": str(result.get("title") or result.get("name") or ""),
                   "stages": stages, "packets": []})


def metering_stage(sl: list[dict]) -> list[dict]:
    """Processor Slice measurement ran whenever any stage was timed: one summary stage naming the categories

    Lean:
        def meteringRan (categories : List String) : Bool := !categories.isEmpty
        #guard meteringRan ["Reasoning"] && !meteringRan []                  -- py: len(metering_stage([{"category": "Reasoning", "ms": 1.0, "stages": 1}])) == 1 and metering_stage([]) == []
    """
    if not sl:
        return []
    return [stage("slices", "Measure Processor Slices", ["metering"], "ran", 0.0, "Reasoning",
                  ", ".join(str(x["category"]) for x in sl), {})]


def finish(tr: dict) -> dict:
    """add the per-type summary and the Processor Slices to a trace

    Lean:
        #guard LOGIC_COUNT == 18                                               -- py: len(finish({"stages": []})["logic"]) == 18
    """
    tr["slices"] = slices(list(tr["stages"]))
    tr["logic"] = logic_summary(list(tr["stages"]) + metering_stage(tr["slices"]))
    tr["total_ms"] = round(sum(float(s["ms"]) for s in tr["stages"]), 2)
    return tr


def route_reason(message: str, route: str) -> str:
    """why the router chose what it did, in words

    Lean:
        def reasonFor (r : String) : String := match r with
          | "answer" => "No creation or screen was asked for, so it is a question for the Answer engine."
          | "code" => "A making word with an application word."
          | "chat" => "A greeting or a request for help."
          | "open" => "An opening word with the name of a screen."
          | "image" => "A drawing word, or a making word with a picture word."
          | "video" => "An animating word, or a making word with a video word."
          | "audio" => "A speaking word, or a making word with a sound word."
          | "text" => "A making word with a kind of writing."
          | _ => "Matched the router's words for this capability."
        #guard reasonFor "code" == "A making word with an application word."   -- py: route_reason("build an app", "code") == "A making word with an application word."
    """
    if message.lstrip().startswith("/"):
        return "Chosen explicitly with /" + route + "."
    return {"answer": "No creation or screen was asked for, so it is a question for the Answer engine.",
            "code": "A making word with an application word.", "chat": "A greeting or a request for help.",
            "open": "An opening word with the name of a screen.", "image": "A drawing word, or a making word with a picture word.",
            "video": "An animating word, or a making word with a video word.", "audio": "A speaking word, or a making word with a sound word.",
            "text": "A making word with a kind of writing."}.get(route, "Matched the router's words for this capability.")
