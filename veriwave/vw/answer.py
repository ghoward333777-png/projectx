"""VeriWave's Answer engine: QueryBook's cite-or-refuse Standard Q&A (registry #1) with what VeriWave adds.

Pure: the caller hands over what QueryBook's applications returned (querybook-one/apps/shell/ask.answer, the I/O) and
this module decides what may be said. Sources, in order: calculations (STEM, or VeriWave's exact arithmetic), word
meanings and translations (Language Builder), facts (History & News, shared facts, bulk datasets), and the Feature
Registry for questions about QueryBook or VeriWave themselves. No fact, no answer: the verdict is then UNKNOWN.

Lean:
    structure Cite where
      text : String
      source : String
      link : String
      trust : Nat
    deriving Repr, BEq
"""
from __future__ import annotations

import hashlib

from . import core, registry, verdict

PRONOUNS = ["it", "its", "they", "them", "he", "she", "him", "her", "this", "that"]
REPLACEABLE = ["it", "they", "he", "she", "this", "that"]
SELF_PHRASES = ["querybook", "veriwave", "registry", "feature", "features", "bible", "what can you do", "who are you",
                "what are you", "your capabilities"]
CAPABILITY_PHRASES = ["what can you do", "who are you", "what are you", "your capabilities"]


def resolve_followup(question: str, last_subject: str) -> str:
    """a short follow-up that says 'it', 'they', 'this'… is asked about the last subject (registry #2); '' if not one

    Lean:
        def pronouns : List String := ["it", "its", "they", "them", "he", "she", "him", "her", "this", "that"]
        def replaceable : List String := ["it", "they", "he", "she", "this", "that"]
        def replaceFirst (subj : String) : List String → List String
          | [] => []
          | w :: ws => if replaceable.contains w then subj :: ws else w :: replaceFirst subj ws
        def resolveFollowup (q subj : String) : String :=
          let ws := words q
          if subj == "" || !(ws.any pronouns.contains) || decide (ws.length > 9) then ""
          else if ws.any replaceable.contains then " ".intercalate (replaceFirst subj ws) else ""
        theorem replaceFirst_len (s : String) (ws : List String) : (replaceFirst s ws).length = ws.length := by
          induction ws with
          | nil => rfl
          | cons w ws ih => unfold replaceFirst; split <;> simp [ih]
        #guard resolveFollowup "When was it founded?" "Rome" == "when was Rome founded"   -- py: resolve_followup("When was it founded?", "Rome") == "when was Rome founded"
        #guard resolveFollowup "When was Rome founded?" "Paris" == ""                    -- py: resolve_followup("When was Rome founded?", "Paris") == ""
    """
    ws = core.words(question)
    if not last_subject or not any(w in PRONOUNS for w in ws) or len(ws) > 9:
        return ""
    if not any(w in REPLACEABLE for w in ws):
        return ""
    out: list[str] = []
    done = False
    for w in ws:
        if not done and w in REPLACEABLE:
            out.append(last_subject)
            done = True
        else:
            out.append(w)
    return " ".join(out)


def is_self_question(question: str) -> bool:
    """a question about QueryBook or VeriWave themselves

    Lean:
        def selfPhrases : List String := ["querybook", "veriwave", "registry", "feature", "features", "bible",
          "what can you do", "who are you", "what are you", "your capabilities"]
        def isSelfQuestion (q : String) : Bool := hasAny (words q) selfPhrases
        #guard isSelfQuestion "What can you do?"                        -- py: is_self_question("What can you do?")
        #guard !isSelfQuestion "When was Rome founded?"                 -- py: not is_self_question("When was Rome founded?")
    """
    return core.has_any(core.words(question), SELF_PHRASES)


def capabilities_text() -> str:
    """what VeriWave is, from the registry's own numbers

    Lean:
        def capabilitiesText (total built part notBuilt : Nat) : String :=
          "VeriWave is the QueryBook AI model. It answers questions with cited, verified facts (or says it doesn't know), " ++
          "writes applications from a description, and creates text, images, video and audio from a prompt. It can also open " ++
          "any QueryBook screen on demand: Language Lab, STEM, History & News, Video Studio, the Book Studio and the Control " ++
          "Panel. The QueryBook Feature Registry it is built on lists " ++ toString total ++ " features: " ++ toString built ++
          " built, " ++ toString part ++ " partly built, " ++ toString notBuilt ++ " still to build."
        #guard (capabilitiesText 407 82 102 223).endsWith "223 still to build."   -- py: capabilities_text().endswith("223 still to build.")
    """
    s = registry.summary()
    return ("VeriWave is the QueryBook AI model. It answers questions with cited, verified facts (or says it doesn't know), "
            "writes applications from a description, and creates text, images, video and audio from a prompt. It can also open "
            "any QueryBook screen on demand: Language Lab, STEM, History & News, Video Studio, the Book Studio and the Control "
            "Panel. The QueryBook Feature Registry it is built on lists " + str(s["total"]) + " features: " + str(s["built"]) +
            " built, " + str(s["partial"]) + " partly built, " + str(s["not_built"]) + " still to build.")


def fact_trust(f: dict) -> int:
    """a fact's trust percentage: its own number when it has one, else its status read through the status table

    Lean:
        def factTrust (explicitTrust : Option Nat) (status : String) : Nat :=
          match explicitTrust with
          | some t => min t 100
          | none => statusTrust status
        #guard factTrust (some 140) "" == 100                            -- py: fact_trust({"trust": 140}) == 100
        #guard factTrust none "disputed" == 40                           -- py: fact_trust({"status": "disputed"}) == 40
    """
    t = f.get("trust")
    if isinstance(t, int) and not isinstance(t, bool):
        return core.clamp(0, 100, t)
    return verdict.status_trust(str(f.get("status") or ""))


def fact_text(f: dict) -> str:
    """how a fact is quoted: its own statement, else 'subject — predicate: object', with its date

    Lean:
        def factText (statement subj pred obj date : String) : String :=
          (if statement != "" then statement else stripQids subj ++ " — " ++ pred ++ ": " ++ stripQids obj) ++
          (if date != "" then " (" ++ date ++ ")" else "")
        #guard factText "" "Rome (Q220)" "inception" "753 BC" "" == "Rome — inception: 753 BC"   -- py: fact_text({"subject": "Rome (Q220)", "predicate": "inception", "object": "753 BC"}) == "Rome — inception: 753 BC"
    """
    st = str(f.get("statement") or "")
    base = st if st else (verdict.strip_qids(str(f.get("subject") or "")) + " — " + str(f.get("predicate") or "") + ": "
                          + verdict.strip_qids(str(f.get("object") or "")))
    date = str(f.get("date") or "")
    return base + (" (" + date + ")" if date else "")


def citations_from(qb: dict, min_trust: int) -> tuple[list[dict], int, list[dict]]:
    """(citations, facts withheld below the trust threshold, offered facts the verdict is judged on)

    Lean:
        def offered (trusts : List Nat) (m : Nat) : Nat × Nat :=
          ((trusts.filter (fun t => decide (m ≤ t))).length, (trusts.filter (fun t => decide (t < m))).length)
        theorem offered_partition (ts : List Nat) (m : Nat) : (offered ts m).1 + (offered ts m).2 = ts.length := by
          induction ts with
          | nil => rfl
          | cons t ts ih =>
            simp only [offered] at ih ⊢
            by_cases h : m ≤ t
            · have h' : ¬ t < m := by omega
              simp [List.filter_cons, h, h'] <;> omega
            · have h' : t < m := by omega
              simp [List.filter_cons, h, h'] <;> omega
        #guard offered [95, 40, 65] 50 == (2, 1)                          -- py: citations_from({"sections": [{"kind": "facts", "items": [{"status": "verified", "predicate": "p", "object": "a", "subject": "s"}, {"status": "disputed"}, {"status": ""}]}]}, 50)[1] == 1
    """
    cites: list[dict] = []
    withheld = 0
    offered: list[dict] = []
    hints = [str(h) for h in ((qb.get("understood") or {}).get("hints") or [])]
    for sec in qb.get("sections") or []:
        kind = str(sec.get("kind") or "")
        for it in sec.get("items") or []:
            if kind == "math":
                cites.append({"text": str(it.get("text") or ""), "where": "Math, Science & Engineering", "trust": 99,
                              "kind": "calculation", "how": str(it.get("how") or "")})
            elif kind == "word" and it.get("text"):
                cites.append({"text": core.cut(str(it["text"]), 600), "where": str(it.get("source") or "Language Builder"),
                              "trust": 90, "kind": "word"})
            elif kind == "word" and it.get("translations"):
                tr = it["translations"]
                pairs = "; ".join(k + ": " + str(tr[k]) for k in sorted(tr))
                cites.append({"text": "Translations — " + pairs, "where": "Language Builder", "trust": 85, "kind": "word"})
            elif kind == "facts":
                t = fact_trust(it)
                if t < min_trust:
                    withheld += 1
                    continue
                offered.append(it)
                cites.append({"text": fact_text(it), "where": str(it.get("where") or "QueryBook facts"), "trust": t,
                              "link": str(it.get("link") or ""), "kind": "fact"})
    focus = [f for f in offered if hints and any(h in core.lower(str(f.get("predicate") or "")) for h in hints)]
    return cites, withheld, (focus if focus else offered[:12])


def hinted_short(focus: list[dict], hints: list[str]) -> str:
    """the one-line answer: the first offered fact whose predicate is what the question asks for ('when' -> a date…)

    Lean:
        def hinted (hints : List String) (pred : String) : Bool := hints.any (fun h => (lower pred |>.splitOn h).length > 1)
        #guard hinted ["date", "time", "invention"] "time of discovery or invention"   -- py: hinted_short([{"subject": "printing press", "predicate": "time of discovery or invention", "object": "c. 1440"}], ["time"]) == "printing press — time of discovery or invention: c. 1440"
        #guard !hinted [] "inventor"                                        -- py: hinted_short([{"subject": "a", "predicate": "inventor", "object": "b"}], []) == ""
    """
    for f in focus:
        if hints and any(h in core.lower(str(f.get("predicate") or "")) for h in hints):
            return fact_text(f)
    return ""


def subject_candidates(subject: str) -> list[tuple[str, list[str]]]:
    """shorter subjects inside a question's subject, each with the words left over (they should name the predicate):
    the part after the last ' of ' first ('inception of Rome' -> 'Rome', ['inception']), then shorter word runs from
    the end and from the start, longest first; at most eight

    Lean:
        def ofSplit (ws : List String) : Option (List String × List String) :=
          match (ws.reverse.findIdx? (· == "of")) with
          | some i => let k := ws.length - 1 - i; some (ws.drop (k + 1), ws.take k)
          | none => none
        def candidateCount (n : Nat) : Nat := min 8 (2 * (n - 1))
        theorem candidateCount_le (n : Nat) : candidateCount n ≤ 8 := Nat.min_le_left _ _
        def dropMarks (s : String) : String := s.trim.dropRightWhile (fun c => c == '?' || c == '!' || c == '.')
        #guard dropMarks "inception of Rome?" == "inception of Rome"          -- py: subject_candidates("inception of Rome?")[0] == ("Rome", ["inception"])
        #guard ofSplit ["inception", "of", "rome"] == some (["rome"], ["inception"])   -- py: subject_candidates("inception of Rome")[0] == ("Rome", ["inception"])
        #guard ofSplit ["rome", "inception"] == none                          -- py: ("Rome", ["inception"]) in subject_candidates("Rome inception")
    """
    raw = subject.strip().rstrip("?!.").split()
    low = [core.lower(w) for w in raw]
    out: list[tuple[str, list[str]]] = []
    stop = ["the", "a", "an", "of", "is", "was", "what", "who", "when", "where", "tell", "me", "about"]

    def add(words: list[str], rest: list[str]) -> None:
        """one candidate, unless empty, only filler words, or already listed

        Lean:
            def fillerOnly (stop ws : List String) : Bool := ws.all stop.contains
            def trimFiller (stop ws : List String) : List String := ((ws.dropWhile stop.contains).reverse.dropWhile stop.contains).reverse
            #guard fillerOnly ["the", "of"] ["the"] && !fillerOnly ["the"] ["rome"]   -- py: subject_candidates("the") == []
            #guard trimFiller ["of", "me", "about"] ["me", "about", "x"] == ["x"]     -- py: subject_candidates("Tell me about 67550+67550")[0][0] == "67550+67550"
        """
        while words and core.lower(words[0]) in stop:
            words = words[1:]
        while words and core.lower(words[-1]) in stop:
            words = words[:-1]
        cand = " ".join(words).strip()
        left = [w for w in rest if w not in stop]
        if cand and not all(core.lower(w) in stop for w in words) and all(c[0] != cand for c in out):
            out.append((cand, left))
    if "of" in low:
        k = len(low) - 1 - low[::-1].index("of")
        add(raw[k + 1:], low[:k])
    for n in range(len(raw) - 1, 0, -1):
        add(raw[len(raw) - n:], low[:len(raw) - n])
        add(raw[:n], low[n:])
    return out[:8]


def predicate_matches(predicate: str, words: list[str]) -> bool:
    """whether a fact's predicate shares a word (or a word stem of four letters or more) with the question's other words

    Lean:
        def stemHit (pred w : String) : Bool := w.length ≥ 4 && ((lower pred).splitOn (String.mk (w.toList.take 5))).length > 1
        #guard stemHit "time of discovery or invention" "invented"           -- py: predicate_matches("time of discovery or invention", ["invented"])
        #guard !stemHit "inception" "of"                                     -- py: not predicate_matches("inception", ["of"])
    """
    p = core.lower(predicate)
    pw = core.words(p)
    for w in words:
        if w in pw or (len(w) >= 4 and w[:5] in p):
            return True
    return False


def provenance_input(question: str, cites: list[dict]) -> str:
    """the canonical text the provenance hash covers: the question, then one line per citation

    Lean:
        def provenanceInput (q : String) (cs : List Cite) : String :=
          q ++ String.join (cs.map (fun c => "\n" ++ c.text ++ "|" ++ c.source ++ "|" ++ c.link))
        #guard provenanceInput "q" [⟨"t", "s", "", 90⟩] == "q\nt|s|"    -- py: provenance_input("q", [{"text": "t", "where": "s"}]) == "q\nt|s|"
    """
    return question + "".join("\n" + str(c.get("text") or "") + "|" + str(c.get("where") or "") + "|" + str(c.get("link") or "")
                              for c in cites)


def provenance_hash(question: str, cites: list[dict]) -> str:
    """SHA-256 (FIPS 180-4) of the provenance input, hex: anyone can recompute it from the answer shown

    Lean:
        -- SHA-256 is an external primitive (Rust: sha2, Python: hashlib); Lean fixes what it is applied to.
        def provenanceHashInput (q : String) (cs : List Cite) : String := provenanceInput q cs
        #guard (provenanceHashInput "" []).length == 0                    -- py: provenance_hash("", []) == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    """
    return hashlib.sha256(provenance_input(question, cites).encode("utf-8")).hexdigest()


def registry_cites(question: str) -> list[dict]:
    """citations from the Feature Registry for a question about QueryBook or VeriWave

    Lean:
        def registryCite (no : Nat) (name status rule screen : String) : Cite :=
          ⟨"#" ++ toString no ++ " " ++ name ++ " (" ++ status ++ ") — " ++ rule ++ " " ++ screen, "QueryBook Feature Registry v71", "", 99⟩
        #guard (registryCite 1 "Standard Q&A" "Built" "R." "S").trust == 99   -- py: all(c["trust"] == 99 for c in registry_cites("feature 1"))
    """
    hits: list[dict] = []
    ws = core.words(question)
    for w in ws:
        if w.isdigit() and core.has_any(ws, ["feature", "number", "no"]):
            f = registry.lookup(w)
            if f is not None:
                hits.append(f)
    for f in registry.best_matches(question, 5):
        if f not in hits:
            hits.append(f)
    out: list[dict] = []
    for f in hits[:5]:
        rule = f["rule"][:-1] if f["rule"].endswith(".") else f["rule"]
        out.append({"text": ("#" + str(f["no"]) + " " + f["feature"] + " (" + f["status"] + ") — " + rule + ". " + f["on_screen"]).strip(),
                    "where": "QueryBook Feature Registry v71", "trust": 99, "kind": "registry", "feature": f["no"],
                    "interface": f["interface"]})
    return out


def compose(question: str, qb: dict, min_trust: int, last_subject: str, apps_running: bool) -> dict:
    """the whole answer: verdict, short answer, numbered citations, conflicts, provenance

    Lean:
        def composeVerdict (cites : List Cite) (contradicted : Bool) : Verdict :=
          if cites.isEmpty then .unknown else if contradicted then .contradicted else .verified
        theorem compose_refuses (c : Bool) : composeVerdict [] c = .unknown := rfl
        theorem compose_cited (x : Cite) (xs : List Cite) (c : Bool) : composeVerdict (x :: xs) c ≠ .unknown := by
          unfold composeVerdict; cases c <;> simp
        #guard composeVerdict [] true == .unknown                         -- py: compose("", {}, 50, "", False)["verdict"] == "UNKNOWN"
    """
    q = " ".join(question.split())
    out: dict = {"question": q, "verdict": "UNKNOWN", "short": "", "citations": [], "conflicts": [], "sections": [],
                 "asked": [], "unavailable": [], "min_trust": min_trust, "withheld": 0, "subject": "", "provenance": "",
                 "resolved": ""}
    if not q:
        out["provenance"] = provenance_hash(q, [])
        return out
    resolved = resolve_followup(q, last_subject)
    out["resolved"] = resolved
    cites, withheld, focus = citations_from(qb, min_trust)
    out["withheld"] = withheld
    out["asked"] = list(qb.get("asked") or [])
    out["unavailable"] = list(qb.get("unavailable") or [])
    out["subject"] = str((qb.get("understood") or {}).get("subject") or "")
    out["sections"] = list(qb.get("sections") or [])
    out["short"] = str(qb.get("short") or "") or hinted_short(focus, [str(h) for h in ((qb.get("understood") or {}).get("hints") or [])])
    out["conflicts"] = verdict.conflicts(focus)
    if not any(c["kind"] == "calculation" for c in cites):
        calc = verdict.calculate(resolved or q)
        if calc is not None:
            cites.insert(0, {"text": (resolved or q).rstrip("?= ") + " = " + calc, "where": "VeriWave exact arithmetic",
                             "trust": 99, "kind": "calculation"})
            out["short"] = out["short"] or calc
    if is_self_question(q):
        if core.has_any(core.words(q), CAPABILITY_PHRASES):
            cites.append({"text": capabilities_text(), "where": "VeriWave", "trust": 99, "kind": "self"})
            out["short"] = out["short"] or capabilities_text()
        reg = registry_cites(q)
        cites += reg
        if not out["short"] and reg:
            f0 = registry.lookup(str(reg[0]["feature"]))
            out["short"] = (f0["feature"] + ": " + f0["rule"]) if f0 is not None else ""
    for i, c in enumerate(cites):
        c["n"] = i + 1
    out["citations"] = cites
    if not cites:
        reasons: list[str] = []
        if not apps_running:
            reasons.append("QueryBook's applications are not running")
        if withheld:
            reasons.append(str(withheld) + " fact(s) were below the " + str(min_trust) + "% trust threshold")
        out["short"] = "I don't know — QueryBook holds no fact that answers this" + (" (" + "; ".join(reasons) + ")." if reasons else ".")
        out["verdict"] = "UNKNOWN"
    else:
        out["verdict"] = "CONTRADICTED" if out["conflicts"] else "VERIFIED"
        out["short"] = out["short"] or "Here is what QueryBook holds about this:"
    out["provenance"] = provenance_hash(q, cites)
    return out


GROUNDED_SYSTEM = ("You are VeriWave, the QueryBook AI model. Answer the user's question using ONLY the numbered facts "
                   "provided. Cite every claim with its number in square brackets, like [2]. If the facts do not answer the "
                   "question, say exactly what is missing instead of guessing. If the facts disagree, present each value with "
                   "its citation and do not pick one. Be concise: two to six sentences of plain prose, no headings.")


def grounded_prompt(result: dict) -> str:
    """what Claude is given when it rewords an answer: the question and the numbered facts, nothing else

    Lean:
        def factLine (n : Nat) (c : Cite) : String :=
          "[" ++ toString n ++ "] " ++ c.text ++ " (source: " ++ c.source ++ ", trust " ++ toString c.trust ++ "%)"
        #guard factLine 1 ⟨"t", "s", "", 90⟩ == "[1] t (source: s, trust 90%)"   -- py: grounded_prompt({"question": "q", "citations": [{"n": 1, "text": "t", "where": "s", "trust": 90}]}).endswith("[1] t (source: s, trust 90%)")
    """
    lines = ["[" + str(c["n"]) + "] " + str(c["text"]) + " (source: " + str(c["where"]) + ", trust " + str(c["trust"]) + "%)"
             for c in result["citations"][:40]]
    return "Question: " + str(result.get("resolved") or result["question"]) + "\n\nFacts:\n" + "\n".join(lines)
