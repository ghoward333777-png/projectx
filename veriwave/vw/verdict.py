"""Truth rules for VeriWave answers (QueryBook registry #1, Standard Q&A) and exact arithmetic.

* Trust is a whole percentage 0..100 (exact in Python, Rust and Lean). A fact is offered only if trust >= 50.
* Verdict: UNKNOWN with no usable fact; CONTRADICTED when one subject has two different values for a functional
  (single-valued) predicate; VERIFIED otherwise.
* Arithmetic is exact: rationals (numerator, denominator), never floating point. Tokenizer -> shunting-yard -> RPN.

Lean:
    structure Fact where
      subj : String
      pred : String
      obj : String
      trust : Nat
    deriving Repr, BEq
    def MIN_TRUST : Nat := 50
"""
from __future__ import annotations

from . import core

MIN_TRUST = 50
DEFAULT_TRUST = 65
BOUND = 2 ** 62          # every rational keeps |numerator| and denominator below this (Rust: i128 never overflows)
STATUS_TRUST: dict[str, int] = {
    "proved": 99, "verified": 95, "confirmed": 95, "accepted": 85, "sourced": 80, "active": 75, "harvested": 70,
    "imported": 70, "unverified": 60, "pending": 55, "stale": 45, "disputed": 40, "contested": 40, "retracted": 5,
    "rejected": 5, "deleted": 0,
}
MULTI_VALUED = ("instance of", "subclass of", "occupation", "award", "child", "sibling", "spouse", "member", "genre",
                "language", "field", "part of", "has part", "notable work", "educated", "employer", "position", "nominated",
                "citizenship", "alias", "also known", "category", "translation", "named after", "influenced", "described by",
                "different from", "contains", "shares border", "religion", "ethnic", "participant", "cast member", "product",
                "industry", "topic", "subject", "use")


# --------------------------------------------------------------------------- trust
def status_trust(status: str) -> int:
    """QueryBook's per-fact status read as a trust percentage

    Lean:
        def statusTrust (s : String) : Nat :=
          match lower s.trim with
          | "proved" => 99 | "verified" => 95 | "confirmed" => 95 | "accepted" => 85 | "sourced" => 80 | "active" => 75
          | "harvested" => 70 | "imported" => 70 | "unverified" => 60 | "pending" => 55 | "stale" => 45
          | "disputed" => 40 | "contested" => 40 | "retracted" => 5 | "rejected" => 5 | "deleted" => 0 | _ => 65
        theorem statusTrust_le (s : String) : statusTrust s ≤ 100 := by
          unfold statusTrust; split <;> decide
        #guard statusTrust "Verified" == 95                              -- py: status_trust("Verified") == 95
        #guard statusTrust "" == 65                                      -- py: status_trust("") == 65
    """
    return STATUS_TRUST.get(core.lower(status.strip()), DEFAULT_TRUST)


def gate(trusts: list[int], minimum: int) -> list[int]:
    """the positions of the facts that may be offered (trust >= minimum), in order

    Lean:
        def gate (fs : List Fact) (minimum : Nat) : List Fact := fs.filter (fun f => decide (minimum ≤ f.trust))
        theorem gate_sound (fs : List Fact) (m : Nat) (f : Fact) (h : f ∈ gate fs m) : m ≤ f.trust := by
          simp [gate, List.mem_filter] at h
          exact h.2
        theorem gate_sub (fs : List Fact) (m : Nat) : (gate fs m).length ≤ fs.length := List.length_filter_le _ _
        #guard (gate [⟨"a", "p", "x", 40⟩, ⟨"a", "p", "x", 50⟩] 50).length == 1   -- py: gate([40, 50], 50) == [1]
    """
    return [i for i, t in enumerate(trusts) if minimum <= t]


# --------------------------------------------------------------------------- verdict
def strip_qids(text: str) -> str:
    """text without Wikidata ids written as ' (Q123)'

    Lean:
        def isQid : List Char → Option (List Char)
          | ' ' :: '(' :: 'Q' :: rest =>
            let ds := rest.takeWhile Char.isDigit
            match rest.dropWhile Char.isDigit with
            | ')' :: more => if ds.isEmpty then none else some more
            | _ => none
          | _ => none
        def stripAux : Nat → List Char → List Char
          | 0, cs => cs
          | _ + 1, [] => []
          | n + 1, c :: cs =>
            match isQid (c :: cs) with
            | some more => stripAux n more
            | none => c :: stripAux n cs
        def stripQids (s : String) : String := (String.mk (stripAux s.length s.toList)).trim
        #guard stripQids "Paris (Q90) is in France (Q142)" == "Paris is in France"   -- py: strip_qids("Paris (Q90) is in France (Q142)") == "Paris is in France"
        #guard stripQids "a (Qx)" == "a (Qx)"                                      -- py: strip_qids("a (Qx)") == "a (Qx)"
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text.startswith(" (Q", i):
            j = i + 3
            while j < n and "0" <= text[j] <= "9":
                j += 1
            if j > i + 3 and j < n and text[j] == ")":
                i = j + 1
                continue
        out.append(text[i])
        i += 1
    return "".join(out).strip()


def norm(text: str) -> str:
    """how values are compared: ids removed, ASCII lower case, outer spaces trimmed

    Lean:
        def norm (s : String) : String := lower (stripQids s).trim
        #guard norm " Rome (Q220) " == "rome"                           -- py: norm(" Rome (Q220) ") == "rome"
    """
    return core.lower(strip_qids(text).strip())


def multi_valued(predicate: str) -> bool:
    """predicates that legitimately have several values (occupation, award, child…) never contradict

    Lean:
        def multiWords : List String := ["instance of", "subclass of", "occupation", "award", "child", "sibling", "spouse",
          "member", "genre", "language", "field", "part of", "has part", "notable work", "educated", "employer", "position",
          "nominated", "citizenship", "alias", "also known", "category", "translation", "named after", "influenced",
          "described by", "different from", "contains", "shares border", "religion", "ethnic", "participant", "cast member",
          "product", "industry", "topic", "subject", "use"]
        def multiValued (p : String) : Bool := multiWords.any (fun m => (lower p |>.splitOn m).length > 1)
        #guard multiValued "award received"                              -- py: multi_valued("award received")
        #guard !multiValued "date of birth"                              -- py: not multi_valued("date of birth")
    """
    p = core.lower(predicate)
    return any(m in p for m in MULTI_VALUED)


def clash(a: dict, b: dict) -> bool:
    """two facts give different values for one subject's functional predicate

    Lean:
        def clash (a b : Fact) : Bool :=
          !multiValued a.pred && a.obj != "" && b.obj != "" && norm a.subj == norm b.subj &&
          lower a.pred == lower b.pred && norm a.obj != norm b.obj
        theorem clash_irrefl (a : Fact) : clash a a = false := by simp [clash]
        #guard clash ⟨"Rome", "inception", "753 BC", 90⟩ ⟨"Rome (Q220)", "Inception", "752 BC", 90⟩   -- py: clash({"subject": "Rome", "predicate": "inception", "object": "753 BC"}, {"subject": "Rome (Q220)", "predicate": "Inception", "object": "752 BC"})
    """
    pa, oa, ob = str(a.get("predicate") or ""), str(a.get("object") or ""), str(b.get("object") or "")
    return (not multi_valued(pa) and oa != "" and ob != "" and norm(str(a.get("subject") or "")) == norm(str(b.get("subject") or ""))
            and core.lower(pa) == core.lower(str(b.get("predicate") or "")) and norm(oa) != norm(ob))


def verdict(facts: list[dict]) -> str:
    """UNKNOWN, CONTRADICTED or VERIFIED for the facts offered

    Lean:
        inductive Verdict where | unknown | contradicted | verified
        deriving Repr, BEq, DecidableEq
        def verdict (fs : List Fact) : Verdict :=
          if fs.isEmpty then .unknown
          else if fs.any (fun a => fs.any (fun b => clash a b)) then .contradicted
          else .verified
        theorem verdict_nil : verdict [] = .unknown := rfl
        theorem verdict_single (f : Fact) : verdict [f] = .verified := by simp [verdict, clash_irrefl]
        theorem verdict_nonempty (f : Fact) (fs : List Fact) : verdict (f :: fs) ≠ .unknown := by
          unfold verdict
          cases h : (f :: fs).any (fun a => (f :: fs).any (fun b => clash a b)) <;> simp [h]
        #guard verdict [] == .unknown                                     -- py: verdict([]) == "UNKNOWN"
        #guard verdict [⟨"Rome", "inception", "753 BC", 90⟩] == .verified  -- py: verdict([{"subject": "Rome", "predicate": "inception", "object": "753 BC"}]) == "VERIFIED"
        #guard verdict [⟨"Rome", "inception", "753 BC", 90⟩, ⟨"Rome", "inception", "752 BC", 90⟩] == .contradicted   -- py: verdict([{"subject": "Rome", "predicate": "inception", "object": "753 BC"}, {"subject": "Rome", "predicate": "inception", "object": "752 BC"}]) == "CONTRADICTED"
        #guard verdict [⟨"Curie", "award received", "Nobel Physics", 90⟩, ⟨"Curie", "award received", "Nobel Chemistry", 90⟩] == .verified   -- py: verdict([{"subject": "Curie", "predicate": "award received", "object": "Nobel Physics"}, {"subject": "Curie", "predicate": "award received", "object": "Nobel Chemistry"}]) == "VERIFIED"
    """
    if not facts:
        return "UNKNOWN"
    for a in facts:
        for b in facts:
            if clash(a, b):
                return "CONTRADICTED"
    return "VERIFIED"


def conflicts(facts: list[dict]) -> list[dict]:
    """each contradiction, for display: the subject, the predicate and every competing value with its sources

    Lean:
        def conflictKeys (fs : List Fact) : List (String × String) :=
          (fs.filter (fun a => fs.any (fun b => clash a b))).map (fun a => (norm a.subj, lower a.pred)) |>.eraseDups
        theorem conflictKeys_nil : conflictKeys [] = [] := rfl
        #guard (conflictKeys [⟨"Rome", "inception", "753 BC", 90⟩, ⟨"Rome", "inception", "752 BC", 90⟩]).length == 1   -- py: len(conflicts([{"subject": "Rome", "predicate": "inception", "object": "753 BC"}, {"subject": "Rome", "predicate": "inception", "object": "752 BC"}])) == 1
    """
    keys: list[tuple[str, str]] = []
    for a in facts:
        if any(clash(a, b) for b in facts):
            k = (norm(str(a.get("subject") or "")), core.lower(str(a.get("predicate") or "")))
            if k not in keys:
                keys.append(k)
    out: list[dict] = []
    for subj, pred in keys:
        group = [f for f in facts if norm(str(f.get("subject") or "")) == subj and core.lower(str(f.get("predicate") or "")) == pred]
        values: list[dict] = []
        for f in group:
            v = strip_qids(str(f.get("object") or ""))
            where = str(f.get("where") or "")
            hit = [x for x in values if norm(x["value"]) == norm(v)]
            if hit:
                if where and where not in hit[0]["sources"]:
                    hit[0]["sources"].append(where)
            else:
                values.append({"value": v, "sources": [where] if where else []})
        out.append({"subject": strip_qids(str(group[0].get("subject") or "")), "predicate": str(group[0].get("predicate") or ""),
                    "values": values})
    return out


# --------------------------------------------------------------------------- exact arithmetic
def gcd(a: int, b: int) -> int:
    """greatest common divisor of two naturals (Euclid)

    Lean:
        -- Nat.gcd from core Lean
        #guard Nat.gcd 12 18 == 6                                         -- py: gcd(12, 18) == 6
    """
    while b:
        a, b = b, a % b
    return a


def q_norm(n: int, d: int) -> tuple[int, int]:
    """the rational n/d (d > 0) in lowest terms

    Lean:
        structure Q where
          num : Int
          den : Nat
        deriving Repr, BEq, DecidableEq
        def Q.norm (n : Int) (d : Nat) : Q :=
          let g := Nat.gcd n.natAbs d
          if g = 0 then ⟨0, 1⟩ else ⟨n / (g : Int), d / g⟩
        #guard Q.norm 6 8 == ⟨3, 4⟩                                       -- py: q_norm(6, 8) == (3, 4)
        #guard Q.norm (-6) 8 == ⟨-3, 4⟩                                   -- py: q_norm(-6, 8) == (-3, 4)
        #guard Q.norm 0 5 == ⟨0, 1⟩                                       -- py: q_norm(0, 5) == (0, 1)
    """
    g = gcd(abs(n), d)
    if g == 0:
        return (0, 1)
    return (n // g if n >= 0 else -((-n) // g), d // g)


def in_bound(q: tuple[int, int]) -> bool:
    """whether a rational stays inside the exact range every port shares (|numerator|, denominator < 2^62)

    Lean:
        def BOUND : Nat := 2 ^ 62
        def inBound (q : Q) : Bool := decide (q.num.natAbs < BOUND) && decide (q.den < BOUND)
        #guard inBound ⟨-5, 2⟩ && !inBound ⟨2 ^ 62, 1⟩                    -- py: in_bound((-5, 2)) and not in_bound((2 ** 62, 1))
    """
    return abs(q[0]) < BOUND and q[1] < BOUND


def bounded(q: tuple[int, int] | None) -> tuple[int, int] | None:
    """the value if it is in range, else None

    Lean:
        def bounded (q : Option Q) : Option Q := q.bind (fun v => if inBound v then some v else none)
        theorem bounded_none : bounded none = none := rfl
        #guard bounded (some ⟨1, 1⟩) == some ⟨1, 1⟩                        -- py: bounded((1, 1)) == (1, 1)
    """
    return q if q is not None and in_bound(q) else None


def q_apply(op: str, a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int] | None:
    """a op b for + - * / ^ ; None for division by zero or an exponent that isn't a small whole number

    Lean:
        def qpow (a : Q) : Nat → Q
          | 0 => ⟨1, 1⟩
          | k + 1 => let r := qpow a k; Q.norm (r.num * a.num) (r.den * a.den)
        def qApply (op : Char) (a b : Q) : Option Q := bounded <|
          match op with
          | '+' => some (Q.norm (a.num * b.den + b.num * a.den) (a.den * b.den))
          | '-' => some (Q.norm (a.num * b.den - b.num * a.den) (a.den * b.den))
          | '*' => some (Q.norm (a.num * b.num) (a.den * b.den))
          | '/' => if b.num = 0 then none
                   else some (Q.norm (a.num * b.den * (if b.num < 0 then -1 else 1)) (a.den * b.num.natAbs))
          | '^' => if b.den ≠ 1 ∨ b.num.natAbs > 64 then none
                   else if 0 ≤ b.num then some (qpow a b.num.natAbs)
                   else if a.num = 0 then none
                   else let p := qpow a b.num.natAbs
                        some (Q.norm (p.den * (if p.num < 0 then -1 else 1)) p.num.natAbs)
          | _ => none
        theorem qApply_div_zero (a : Q) (d : Nat) : qApply '/' a ⟨0, d⟩ = none := by simp [qApply]
        #guard qApply '+' ⟨1, 2⟩ ⟨1, 3⟩ == some ⟨5, 6⟩                   -- py: q_apply("+", (1, 2), (1, 3)) == (5, 6)
        #guard qApply '/' ⟨1, 1⟩ ⟨-2, 1⟩ == some ⟨-1, 2⟩                 -- py: q_apply("/", (1, 1), (-2, 1)) == (-1, 2)
        #guard qApply '^' ⟨2, 1⟩ ⟨-2, 1⟩ == some ⟨1, 4⟩                  -- py: q_apply("^", (2, 1), (-2, 1)) == (1, 4)
        #guard qApply '/' ⟨1, 1⟩ ⟨0, 1⟩ == none                          -- py: q_apply("/", (1, 1), (0, 1)) is None
        #guard qApply '^' ⟨2, 1⟩ ⟨62, 1⟩ == none                         -- py: q_apply("^", (2, 1), (62, 1)) is None
        #guard qApply '^' ⟨2, 1⟩ ⟨61, 1⟩ == some ⟨2 ^ 61, 1⟩             -- py: q_apply("^", (2, 1), (61, 1)) == (2 ** 61, 1)
    """
    return bounded(q_raw(op, a, b))


def q_raw(op: str, a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int] | None:
    """a op b before the range check

    Lean:
        -- qApply above is `bounded` applied to this same arithmetic
        #guard qApply '*' ⟨3, 1⟩ ⟨4, 1⟩ == some ⟨12, 1⟩                    -- py: q_raw("*", (3, 1), (4, 1)) == (12, 1)
    """
    an, ad = a
    bn, bd = b
    if op == "+":
        return q_norm(an * bd + bn * ad, ad * bd)
    if op == "-":
        return q_norm(an * bd - bn * ad, ad * bd)
    if op == "*":
        return q_norm(an * bn, ad * bd)
    if op == "/":
        if bn == 0:
            return None
        return q_norm(an * bd * (-1 if bn < 0 else 1), ad * abs(bn))
    if op == "^":
        if bd != 1 or abs(bn) > 64:
            return None
        pn, pd = 1, 1
        for _ in range(abs(bn)):
            pn, pd = q_norm(pn * an, pd * ad)
        if bn >= 0:
            return (pn, pd)
        if an == 0:
            return None
        return q_norm(pd * (-1 if pn < 0 else 1), abs(pn))
    return None


def tokenize(text: str) -> list[tuple[str, int, int]] | None:
    """numbers and operators; ('n', num, den) for a number, (op, 0, 0) for + - * / ^ ( ) ; None on anything else

    Lean:
        inductive Tok where | num (q : Q) | op (c : Char)
        deriving Repr, BEq
        def isOpChar (c : Char) : Bool := c == '+' || c == '-' || c == '*' || c == '/' || c == '^' || c == '(' || c == ')'
        def flush (num : Option Nat) (sc : Nat) (acc : List Tok) : List Tok :=
          match num with
          | some n => Tok.num (Q.norm n (10 ^ sc)) :: acc
          | none => acc
        def allInBound : List Tok → Bool
          | [] => true
          | Tok.num q :: ts => inBound q && allInBound ts
          | Tok.op _ :: ts => allInBound ts
        def tokAux : List Char → Option Nat → Nat → Bool → List Tok → Option (List Tok)
          | [], num, sc, _, acc => some (flush num sc acc).reverse
          | c :: cs, num, sc, dot, acc =>
            if c.isDigit then tokAux cs (some (num.getD 0 * 10 + (c.toNat - 48))) (if dot then sc + 1 else sc) dot acc
            else if c == '.' then (if dot then none else tokAux cs (some (num.getD 0)) sc true acc)
            else if c == ' ' then tokAux cs none 0 false (flush num sc acc)
            else if isOpChar c then tokAux cs none 0 false (Tok.op c :: flush num sc acc)
            else none
        def tokenize (s : String) : Option (List Tok) :=
          match tokAux s.toList none 0 false [] with
          | some ts => if allInBound ts then some ts else none
          | none => none
        #guard tokenize "2.5*(3)" == some [.num ⟨5, 2⟩, .op '*', .op '(', .num ⟨3, 1⟩, .op ')']   -- py: tokenize("2.5*(3)") == [("n", 5, 2), ("*", 0, 0), ("(", 0, 0), ("n", 3, 1), (")", 0, 0)]
        #guard tokenize "2..5" == none                                    -- py: tokenize("2..5") is None
        #guard tokenize "2x" == none                                      -- py: tokenize("2x") is None
        #guard tokenize "99999999999999999999" == none                    -- py: tokenize("99999999999999999999") is None
    """
    toks: list[tuple[str, int, int]] = []
    num: int | None = None
    sc = 0
    dot = False
    for c in text:
        if "0" <= c <= "9":
            num = (num or 0) * 10 + (ord(c) - 48)
            if dot:
                sc += 1
            continue
        if c == ".":
            if dot:
                return None
            num = num or 0
            dot = True
            continue
        if num is not None:
            n, d = q_norm(num, 10 ** sc)
            toks.append(("n", n, d))
        num, sc, dot = None, 0, False
        if c == " ":
            continue
        if c in "+-*/^()":
            toks.append((c, 0, 0))
            continue
        return None
    if num is not None:
        n, d = q_norm(num, 10 ** sc)
        toks.append(("n", n, d))
    for t in toks:
        if t[0] == "n" and not in_bound((t[1], t[2])):
            return None
    return toks


def prec(op: str) -> int:
    """binding strength: + - 1, * / 2, unary minus (~) 3, ^ 4

    Lean:
        def prec (c : Char) : Nat := if c == '+' || c == '-' then 1 else if c == '*' || c == '/' then 2
          else if c == '~' then 3 else if c == '^' then 4 else 0
        #guard prec '^' == 4                                              -- py: prec("^") == 4
    """
    return {"+": 1, "-": 1, "*": 2, "/": 2, "~": 3, "^": 4}.get(op, 0)


def to_rpn(toks: list[tuple[str, int, int]]) -> list[tuple[str, int, int]] | None:
    """shunting-yard: infix tokens to reverse Polish order; None when the expression is malformed

    Lean:
        def shouldPop (top incoming : Char) : Bool :=
          top != '(' && (prec top > prec incoming || (prec top == prec incoming && incoming != '^'))
        def popWhile (o : Char) : List Char → List Tok → List Char × List Tok
          | [], out => ([], out)
          | t :: st, out => if shouldPop t o then popWhile o st (Tok.op t :: out) else (t :: st, out)
        def popParen : List Char → List Tok → Option (List Char × List Tok)
          | [], _ => none
          | '(' :: st, out => some (st, out)
          | t :: st, out => popParen st (Tok.op t :: out)
        def flushAll : List Char → List Tok → Option (List Tok)
          | [], out => some out.reverse
          | '(' :: _, _ => none
          | t :: st, out => flushAll st (Tok.op t :: out)
        -- expect = true when an operand (number, '(' or unary sign) must come next
        def rpnAux : List Tok → Bool → List Char → List Tok → Option (List Tok)
          | [], expect, st, out => if expect then none else flushAll st out
          | Tok.num q :: ts, expect, st, out => if expect then rpnAux ts false st (Tok.num q :: out) else none
          | Tok.op c :: ts, expect, st, out =>
            if c == '(' then (if expect then rpnAux ts true ('(' :: st) out else none)
            else if c == ')' then
              (if expect then none else match popParen st out with
                | some (st', out') => rpnAux ts false st' out'
                | none => none)
            else if expect then
              (if c == '-' then rpnAux ts true ('~' :: st) out else if c == '+' then rpnAux ts true st out else none)
            else
              let (st', out') := popWhile c st out
              rpnAux ts true (c :: st') out'
        def toRpn (ts : List Tok) : Option (List Tok) := rpnAux ts true [] []
        #guard toRpn [.num ⟨1, 1⟩, .op '+', .num ⟨2, 1⟩, .op '*', .num ⟨3, 1⟩] == some [.num ⟨1, 1⟩, .num ⟨2, 1⟩, .num ⟨3, 1⟩, .op '*', .op '+']   -- py: to_rpn(tokenize("1+2*3")) == [("n", 1, 1), ("n", 2, 1), ("n", 3, 1), ("*", 0, 0), ("+", 0, 0)]
        #guard toRpn [.op '(', .num ⟨1, 1⟩] == none                      -- py: to_rpn(tokenize("(1")) is None
    """
    out: list[tuple[str, int, int]] = []
    st: list[str] = []
    expect = True
    for t in toks:
        kind = t[0]
        if kind == "n":
            if not expect:
                return None
            out.append(t)
            expect = False
        elif kind == "(":
            if not expect:
                return None
            st.append("(")
        elif kind == ")":
            if expect:
                return None
            while st and st[-1] != "(":
                out.append((st.pop(), 0, 0))
            if not st:
                return None
            st.pop()
        elif expect:
            if kind == "-":
                st.append("~")
            elif kind != "+":
                return None
        else:
            while st and st[-1] != "(" and (prec(st[-1]) > prec(kind) or (prec(st[-1]) == prec(kind) and kind != "^")):
                out.append((st.pop(), 0, 0))
            st.append(kind)
            expect = True
    if expect:
        return None
    while st:
        top = st.pop()
        if top == "(":
            return None
        out.append((top, 0, 0))
    return out


def eval_rpn(rpn: list[tuple[str, int, int]]) -> tuple[int, int] | None:
    """the value of an RPN token list, exactly

    Lean:
        def evalRpn : List Tok → List Q → Option Q
          | [], [q] => some q
          | [], _ => none
          | Tok.num q :: ts, st => evalRpn ts (q :: st)
          | Tok.op '~' :: ts, a :: st => evalRpn ts (⟨-a.num, a.den⟩ :: st)
          | Tok.op c :: ts, b :: a :: st =>
            match qApply c a b with
            | some r => evalRpn ts (r :: st)
            | none => none
          | _, _ => none
        #guard evalRpn [.num ⟨2, 1⟩, .num ⟨2, 1⟩, .op '^', .op '~'] [] == some ⟨-4, 1⟩   -- py: eval_rpn(to_rpn(tokenize("-2^2"))) == (-4, 1)
    """
    st: list[tuple[int, int]] = []
    for t in rpn:
        if t[0] == "n":
            st.append((t[1], t[2]))
        elif t[0] == "~":
            if not st:
                return None
            a = st.pop()
            st.append((-a[0], a[1]))
        else:
            if len(st) < 2:
                return None
            b = st.pop()
            a = st.pop()
            r = q_apply(t[0], a, b)
            if r is None:
                return None
            st.append(r)
    return st[0] if len(st) == 1 else None


def prepare(text: str) -> str:
    """a question turned into a bare expression: lead-in words and trailing marks removed, × ÷ % and commas rewritten

    Lean:
        def leads : List String := ["what is ", "what's ", "calculate ", "compute ", "evaluate ", "how much is "]
        def dropLead (s : String) : String :=
          match leads.find? (fun l => s.startsWith l) with
          | some l => s.drop l.length
          | none => s
        def prepare (s : String) : String :=
          let t := (dropLead (lower s.trim)).dropRightWhile (fun c => c == '?' || c == '=' || c == '.' || c == ' ')
          ((((t.replace "×" "*").replace "÷" "/").replace "% of " "/100*").replace "%" "/100").replace "," ""
        #guard prepare "What is 15% of 80?" == "15/100*80"               -- py: prepare("What is 15% of 80?") == "15/100*80"
        #guard prepare "1,000 × 3 =" == "1000 * 3"                       -- py: prepare("1,000 × 3 =") == "1000 * 3"
    """
    t = core.lower(text.strip())
    for lead in ("what is ", "what's ", "calculate ", "compute ", "evaluate ", "how much is "):
        if t.startswith(lead):
            t = t[len(lead):]
            break
    t = t.rstrip("?=. ")
    return t.replace("×", "*").replace("÷", "/").replace("% of ", "/100*").replace("%", "/100").replace(",", "")


def decimal_digits(n: int, d: int, places: int) -> str:
    """n/d (d > 0) written with exactly `places` decimals, truncated toward zero

    Lean:
        def padLeft (s : String) (k : Nat) : String := String.mk (List.replicate (k - s.length) '0') ++ s
        def decimalDigits (n : Int) (d places : Nat) : String :=
          let a := n.natAbs
          let whole := a / d
          let frac := (a % d) * 10 ^ places / d
          (if n < 0 then "-" else "") ++ toString whole ++ (if places = 0 then "" else "." ++ padLeft (toString frac) places)
        #guard decimalDigits 1 3 4 == "0.3333"                            -- py: decimal_digits(1, 3, 4) == "0.3333"
        #guard decimalDigits (-7) 2 1 == "-3.5"                           -- py: decimal_digits(-7, 2, 1) == "-3.5"
    """
    a = abs(n)
    whole = a // d
    frac = (a % d) * 10 ** places // d
    sign = "-" if n < 0 else ""
    return sign + str(whole) + ("" if places == 0 else "." + str(frac).rjust(places, "0"))


def terminating_places(d: int) -> int:
    """how many decimals n/d needs when d has no prime factor but 2 and 5; -1 otherwise

    Lean:
        def strip25 : Nat → Nat → Nat × Nat × Nat
          | 0, d => (d, 0, 0)
          | k + 1, d =>
            if d % 2 = 0 ∧ d > 0 then let (r, a, b) := strip25 k (d / 2); (r, a + 1, b)
            else if d % 5 = 0 ∧ d > 0 then let (r, a, b) := strip25 k (d / 5); (r, a, b + 1)
            else (d, 0, 0)
        def terminatingPlaces (d : Nat) : Int :=
          let (r, a, b) := strip25 64 d
          if r = 1 then ((max a b : Nat) : Int) else -1
        #guard terminatingPlaces 8 == 3                                   -- py: terminating_places(8) == 3
        #guard terminatingPlaces 3 == -1                                  -- py: terminating_places(3) == -1
        #guard terminatingPlaces 20 == 2                                  -- py: terminating_places(20) == 2
    """
    r, a, b = d, 0, 0
    for _ in range(64):
        if r % 2 == 0 and r > 0:
            r //= 2
            a += 1
        elif r % 5 == 0 and r > 0:
            r //= 5
            b += 1
        else:
            break
    return max(a, b) if r == 1 else -1


def fmt_q(q: tuple[int, int]) -> str:
    """an exact value for people: whole numbers as is, terminating decimals in full, others as a fraction and ≈ decimal

    Lean:
        def fmtQ (q : Q) : String :=
          if q.den = 1 then toString q.num
          else
            let p := terminatingPlaces q.den
            if 0 ≤ p ∧ p ≤ 12 then decimalDigits q.num q.den p.toNat
            else toString q.num ++ "/" ++ toString q.den ++ " ≈ " ++ decimalDigits q.num q.den 10
        #guard fmtQ ⟨12, 1⟩ == "12"                                       -- py: fmt_q((12, 1)) == "12"
        #guard fmtQ ⟨5, 2⟩ == "2.5"                                       -- py: fmt_q((5, 2)) == "2.5"
        #guard fmtQ ⟨1, 3⟩ == "1/3 ≈ 0.3333333333"                        -- py: fmt_q((1, 3)) == "1/3 ≈ 0.3333333333"
    """
    n, d = q
    if d == 1:
        return str(n)
    p = terminating_places(d)
    if 0 <= p <= 12:
        return decimal_digits(n, d, p)
    return "%d/%d ≈ %s" % (n, d, decimal_digits(n, d, 10))


def calculate(text: str) -> str | None:
    """the exact value of an arithmetic question, or None when it isn't plain arithmetic

    Lean:
        def calculate (s : String) : Option String :=
          match tokenize (prepare s) with
          | none => none
          | some [] => none
          | some ts => match toRpn ts with
            | none => none
            | some r => (evalRpn r []).map fmtQ
        #guard calculate "What is 15% of 80?" == some "12"               -- py: calculate("What is 15% of 80?") == "12"
        #guard calculate "2^10 / 3" == some "1024/3 ≈ 341.3333333333"     -- py: calculate("2^10 / 3") == "1024/3 ≈ 341.3333333333"
        #guard calculate "(1.5 + 2.25) * -4" == some "-15"               -- py: calculate("(1.5 + 2.25) * -4") == "-15"
        #guard calculate "1/0" == none                                    -- py: calculate("1/0") is None
        #guard calculate "60 mph to km/h" == none                         -- py: calculate("60 mph to km/h") is None
        #guard calculate "hello" == none                                  -- py: calculate("hello") is None
    """
    toks = tokenize(prepare(text))
    if not toks:
        return None
    rpn = to_rpn(toks)
    if rpn is None:
        return None
    v = eval_rpn(rpn)
    return None if v is None else fmt_q(v)
