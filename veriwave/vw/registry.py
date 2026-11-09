"""The QueryBook Composite Feature Registry v71 (407 features), as VeriWave sees it.

Source: docs/querybook-rebuild/feature-inventory-v71.json (each feature reviewed against QueryBook v9.64 and the
Control Panel 1.36 applications). VeriWave adds, per feature, the interface that serves it and whether VeriWave itself
provides it (`veriwave`), so the registry is also VeriWave's self-knowledge.

Lean:
    structure Feat where
      no : Nat
      name : String
      domain : String
      area : String
      implemented : String
      audience : String
      hay : String
    deriving Repr, BEq
    def contains (s sub : String) : Bool := (s.splitOn sub).length > 1
    def registryTotal : Nat := 407
    theorem registry_partition : 82 + 102 + 223 = registryTotal := by decide
    #guard registryTotal == 407                                       -- py: summary()["total"] == 407
    #guard 82 + 102 + 223 == registryTotal                            -- py: summary()["built"] + summary()["partial"] + summary()["not_built"] == 407
"""
from __future__ import annotations

import json
import os

from . import core, interfaces

HERE = os.path.dirname(os.path.abspath(__file__))
CANDIDATES = (
    os.path.join(HERE, "..", "data", "feature-inventory-v71.json"),
    os.path.join(HERE, "..", "..", "docs", "querybook-rebuild", "feature-inventory-v71.json"),
)

STATUS_NAMES = {
    "built-v964": "Built (prototype v9.64)",
    "built-apps": "Built (applications)",
    "built-both": "Built (prototype and applications)",
    "partial": "Partly built",
    "not-built": "Not built yet",
}

# Features VeriWave itself provides (registry number -> how).
VERIWAVE_PROVIDES: dict[int, str] = {
    1: "Answer mode and Chat: cite-or-refuse over every QueryBook application, trust gate (50%), verdict, provenance hash.",
    2: "Chat keeps the conversation: a follow-up that names no subject reuses the last subject asked about.",
    3: "A contradicted answer shows each competing value side by side with its sources; nothing is picked silently.",
}
SELF_STOP = {"the", "a", "an", "of", "and", "or", "to", "is", "what", "does", "do", "how", "which", "in", "for", "querybook",
             "veriwave", "feature", "features", "can", "it", "you", "your", "me", "about", "tell", "are", "there", "with"}


def source_path() -> str:
    """the inventory file: the bundled copy first, then the repository's

    Lean:
        def firstExisting : List (String × Bool) → Option String
          | [] => none
          | (p, true) :: _ => some p
          | (_, false) :: rest => firstExisting rest
        #guard firstExisting [("a", false), ("b", true)] == some "b"   -- py: source_path().endswith("feature-inventory-v71.json")
    """
    for p in CANDIDATES:
        if os.path.isfile(p):
            return os.path.normpath(p)
    raise FileNotFoundError("feature-inventory-v71.json not found")


def normalise(r: dict) -> dict:
    """one inventory row as VeriWave's feature record

    Lean:
        def statusName (code : String) : String :=
          match code with
          | "built-v964" => "Built (prototype v9.64)" | "built-apps" => "Built (applications)"
          | "built-both" => "Built (prototype and applications)" | "partial" => "Partly built"
          | "not-built" => "Not built yet" | c => c
        #guard statusName "partial" == "Partly built"                  -- py: STATUS_NAMES["partial"] == "Partly built"
    """
    no = int(r["no"])
    impl = str(r.get("implemented") or "")
    return {
        "no": no, "feature": str(r["feature"]), "domain": str(r.get("domain") or ""), "audience": str(r.get("audience") or ""),
        "area": str(r.get("ui_group") or ""), "implemented": impl, "status": STATUS_NAMES.get(impl, impl),
        "where": [str(w) for w in (r.get("implemented_where") or [])], "rule": str(r.get("rule") or ""),
        "formula": str(r.get("formula") or ""), "lean": bool(r.get("lean")), "on_screen": str(r.get("ui_note") or ""),
        "notes": str(r.get("notes") or ""), "function": str(r.get("function") or ""),
        "interface": interfaces.primary_for_group(str(r.get("ui_group") or "")), "veriwave": VERIWAVE_PROVIDES.get(no, ""),
    }


_CACHE: list[dict] = []


def features() -> list[dict]:
    """all 407 features, loaded once

    Lean:
        def loadOnce (cache : List Feat) (load : Unit → List Feat) : List Feat := if cache.isEmpty then load () else cache
        theorem loadOnce_cached (c : List Feat) (l : Unit → List Feat) (h : c ≠ []) : loadOnce c l = c := by
          unfold loadOnce; cases c with
          | nil => exact absurd rfl h
          | cons _ _ => simp
    """
    if not _CACHE:
        with open(source_path(), encoding="utf-8") as f:
            raw = json.load(f)
        _CACHE.extend(normalise(r) for r in raw)
    return _CACHE


def hay(f: dict) -> str:
    """the text a search looks through

    Lean:
        def hayOf (name domain rule onScreen notes : String) : String := lower (String.intercalate " " [name, domain, rule, onScreen, notes])
        #guard hayOf "A" "B" "C" "D" "E" == "a b c d e"                  -- py: hay({"feature": "A", "domain": "B", "rule": "C", "on_screen": "D", "notes": "E"}) == "a b c d e"
    """
    return core.lower(" ".join((f["feature"], f["domain"], f["rule"], f["on_screen"], f["notes"])))


def matches(f: dict, ws: list[str], qnum: int, domain: str, area: str, implemented: str, audience: str) -> bool:
    """whether a feature passes every filter; a numeric query also matches the feature number

    Lean:
        def featMatches (f : Feat) (ws : List String) (qnum : Nat) (domain area impl aud : String) : Bool :=
          (domain == "" || f.domain == domain) && (area == "" || f.area == area) &&
          (impl == "" || f.implemented == impl) && (aud == "" || f.audience == aud) &&
          (qnum == f.no || ws.all (fun w => contains f.hay w))
        theorem featMatches_domain (f : Feat) (ws : List String) (q : Nat) (d a i u : String)
            (h : featMatches f ws q d a i u = true) (hd : d ≠ "") : f.domain = d := by
          unfold featMatches at h
          simp only [Bool.and_eq_true, Bool.or_eq_true, beq_iff_eq] at h
          rcases h with ⟨⟨⟨⟨hA, _⟩, _⟩, _⟩, _⟩
          rcases hA with h1 | h1
          · exact absurd h1 hd
          · exact h1
        #guard featMatches ⟨1, "Standard Q&A", "R", "ask", "built-v964", "user", "standard q&a"⟩ ["q&a"] 0 "" "ask" "" ""   -- py: matches(lookup("1"), ["q&a"], 0, "", "ask", "", "")
    """
    if domain and f["domain"] != domain:
        return False
    if area and f["area"] != area:
        return False
    if implemented and f["implemented"] != implemented:
        return False
    if audience and f["audience"] != audience:
        return False
    if qnum and qnum == f["no"]:
        return True
    h = hay(f)
    return all(w in h for w in ws)


def search(q: str, domain: str, area: str, implemented: str, audience: str, limit: int) -> list[dict]:
    """features passing every filter, in registry order, at most `limit`

    Lean:
        def search (fs : List Feat) (ws : List String) (qnum : Nat) (d a i u : String) (limit : Nat) : List Feat :=
          (fs.filter (fun f => featMatches f ws qnum d a i u)).take limit
        theorem search_len (fs : List Feat) (ws : List String) (q : Nat) (d a i u : String) (limit : Nat) :
            (search fs ws q d a i u limit).length ≤ limit := by
          unfold search; exact List.length_take_le _ _
        #guard (search [] [] 0 "" "" "" "" 5).length == 0                 -- py: len(search("ask", "", "", "", "", 5)) <= 5
    """
    ws = core.words(q)
    qs = q.strip().lstrip("#")
    qnum = int(qs) if qs.isdigit() else 0
    out: list[dict] = []
    for f in features():
        if matches(f, [] if qnum else ws, qnum, domain, area, implemented, audience):
            out.append(f)
            if len(out) >= limit:
                break
    return out


def tally(fs: list[dict], key: str) -> dict[str, int]:
    """how many features have each value of key, values in sorted order

    Lean:
        def countEq (xs : List String) (v : String) : Nat := (xs.filter (· == v)).length
        theorem countEq_le (xs : List String) (v : String) : countEq xs v ≤ xs.length := by
          unfold countEq; exact List.length_filter_le _ _
        #guard countEq ["a", "b", "a"] "a" == 2                          -- py: tally([{"k": "a"}, {"k": "b"}, {"k": "a"}], "k") == {"a": 2, "b": 1}
    """
    out: dict[str, int] = {}
    for v in sorted({str(f[key]) for f in fs if f[key]}):
        out[v] = sum(1 for f in fs if f[key] == v)
    return out


def summary() -> dict:
    """the registry in numbers

    Lean:
        def builtCount (built964 builtApps builtBoth : Nat) : Nat := built964 + builtApps + builtBoth
        #guard builtCount 41 8 33 == 82                                   -- py: summary()["built"] == 82
    """
    fs = features()
    impl = tally(fs, "implemented")
    built = sum(n for k, n in impl.items() if k.startswith("built"))
    return {"total": len(fs), "built": built, "partial": impl.get("partial", 0), "not_built": impl.get("not-built", 0),
            "veriwave": len(VERIWAVE_PROVIDES), "domains": tally(fs, "domain"), "areas": tally(fs, "area"),
            "implemented": impl, "audiences": tally(fs, "audience"), "status_names": STATUS_NAMES}


def lookup(name_or_no: str) -> dict | None:
    """a feature by number ('1', '#1') or exact name, case-insensitive

    Lean:
        def lookupNo (fs : List Feat) (n : Nat) : Option Feat := fs.find? (·.no == n)
        #guard (lookupNo [] 1).isNone                                      -- py: lookup("#1")["feature"] == "Standard Q&A"
    """
    s = core.lower(name_or_no.strip().lstrip("#"))
    for f in features():
        if s == str(f["no"]) or s == core.lower(f["feature"]):
            return f
    return None


def score(f: dict, ws: list[str]) -> int:
    """how well a feature matches the question's words: 3 per word in its name, 1 per word in its rule or screen

    Lean:
        def score (name rest : String) (ws : List String) : Nat :=
          (ws.filter (fun w => contains name w)).length * 3 + (ws.filter (fun w => contains rest w)).length
        theorem score_zero (name rest : String) : score name rest [] = 0 := rfl
        #guard score "voice cloning" "consent" ["voice", "consent"] == 4   -- py: score({"feature": "Voice Cloning", "rule": "consent", "on_screen": "", "domain": ""}, ["voice", "consent"]) == 4
    """
    name = core.lower(f["feature"])
    rest = core.lower(" ".join((f["rule"], f["on_screen"], f["domain"])))
    return sum(3 for w in ws if w in name) + sum(1 for w in ws if w in rest)


def best_matches(question: str, limit: int) -> list[dict]:
    """features most relevant to a question about QueryBook or VeriWave: highest score first, then registry order

    Lean:
        def before (a b : Nat × Nat) : Bool := a.1 > b.1 || (a.1 == b.1 && a.2 < b.2)
        def insertBy (x : Nat × Nat) : List (Nat × Nat) → List (Nat × Nat)
          | [] => [x]
          | y :: ys => if before x y then x :: y :: ys else y :: insertBy x ys
        def sortScored (xs : List (Nat × Nat)) : List (Nat × Nat) := xs.foldr insertBy []
        theorem insertBy_len (x : Nat × Nat) (ys : List (Nat × Nat)) : (insertBy x ys).length = ys.length + 1 := by
          induction ys with
          | nil => rfl
          | cons y ys ih => unfold insertBy; split <;> simp [ih]
        theorem sortScored_len : ∀ xs : List (Nat × Nat), (sortScored xs).length = xs.length
          | [] => rfl
          | x :: xs => by
            show (insertBy x (sortScored xs)).length = xs.length + 1
            rw [insertBy_len, sortScored_len xs]
        -- (score, feature number): best score first, ties in registry order
        #guard sortScored [(1, 5), (3, 9), (3, 2)] == [(3, 2), (3, 9), (1, 5)]   -- py: [(s, n) for s, n in sorted([(1, 5), (3, 9), (3, 2)], key=lambda t: (-t[0], t[1]))] == [(3, 2), (3, 9), (1, 5)]
    """
    ws = [w for w in core.words(question) if w not in SELF_STOP and len(w) > 2]
    if not ws:
        return []
    scored = [(score(f, ws), f["no"], f) for f in features()]
    ranked = sorted([t for t in scored if t[0] > 0], key=lambda t: (-t[0], t[1]))
    return [t[2] for t in ranked[:limit]]
