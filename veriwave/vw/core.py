"""VeriWave core: small pure functions every other module uses.

Rust-ready: integers and strings only, ASCII rules spelled out (Rust and Lean see the same characters Python does),
32-bit arithmetic written as explicit `% 2**32`.

Lean:
    def M32 : Nat := 4294967296
    theorem M32_pos : M32 > 0 := by decide
"""
from __future__ import annotations

M32 = 4294967296
FNV_OFFSET = 2166136261
FNV_PRIME = 16777619
XS_DEFAULT = 2463534242


def fnv1a32(text: str) -> int:
    """FNV-1a, 32 bits, over the UTF-8 bytes of text. Seeds every deterministic generator.

    Lean:
        def fnvStep (h : Nat) (b : UInt8) : Nat := ((Nat.xor h b.toNat) * 16777619) % M32
        def fnv1a32 (s : String) : Nat := s.toUTF8.toList.foldl fnvStep 2166136261
        theorem foldl_fnvStep_lt (l : List UInt8) (h : Nat) (h0 : h < M32) : l.foldl fnvStep h < M32 := by
          induction l generalizing h with
          | nil => simpa using h0
          | cons b bs ih => exact ih _ (Nat.mod_lt _ M32_pos)
        theorem fnv1a32_lt (s : String) : fnv1a32 s < M32 := foldl_fnvStep_lt _ _ (by decide)
        #guard fnv1a32 "" == 2166136261                     -- py: fnv1a32("") == 2166136261
        #guard fnv1a32 "a" == 3826002220                    -- py: fnv1a32("a") == 3826002220
        #guard fnv1a32 "VeriWave" == 3739194040             -- py: fnv1a32("VeriWave") == 3739194040
    """
    h = FNV_OFFSET
    for b in text.encode("utf-8"):
        h = ((h ^ b) * FNV_PRIME) % M32
    return h


def xorshift32(state: int) -> int:
    """One step of Marsaglia's xorshift32. The state is never 0 when the seed isn't 0.

    Lean:
        def xorshift32 (x : Nat) : Nat :=
          let a := Nat.xor x ((x <<< 13) % M32)
          let b := Nat.xor a (a >>> 17)
          Nat.xor b ((b <<< 5) % M32) % M32
        theorem xorshift32_lt (x : Nat) : xorshift32 x < M32 := Nat.mod_lt _ M32_pos
        #guard xorshift32 1 == 270369                       -- py: xorshift32(1) == 270369
        #guard xorshift32 2463534242 == 723471715           -- py: xorshift32(2463534242) == 723471715
    """
    x = state ^ ((state << 13) % M32)
    x = x ^ (x >> 17)
    return (x ^ ((x << 5) % M32)) % M32


def seed_of(text: str) -> int:
    """The generator seed for a prompt: its FNV-1a hash, or a fixed non-zero seed when that hash is 0.

    Lean:
        def seedOf (s : String) : Nat := if fnv1a32 s = 0 then 2463534242 else fnv1a32 s
        theorem seedOf_ne_zero (s : String) : seedOf s ≠ 0 := by
          unfold seedOf; split <;> omega
    """
    h = fnv1a32(text)
    return XS_DEFAULT if h == 0 else h


class Rng:
    """A deterministic random stream (xorshift32). Same prompt, same stream, in Python, Rust and Lean.

    Lean:
        structure Rng where
          state : Nat
    """

    def __init__(self, seed: int) -> None:
        """Lean:
            def Rng.new (seed : Nat) : Rng := ⟨if seed % M32 = 0 then 2463534242 else seed % M32⟩
        """
        self.state = (seed % M32) or XS_DEFAULT

    def next(self) -> int:
        """the next 32-bit value

        Lean:
            def Rng.next (r : Rng) : Nat × Rng := (xorshift32 r.state, ⟨xorshift32 r.state⟩)
        """
        self.state = xorshift32(self.state)
        return self.state

    def below(self, n: int) -> int:
        """a value in [0, n) (n > 0)

        Lean:
            def Rng.below (r : Rng) (n : Nat) : Nat × Rng := (r.next.1 % n, r.next.2)
            theorem Rng.below_lt (r : Rng) (n : Nat) (h : 0 < n) : (r.below n).1 < n := Nat.mod_lt _ h
        """
        return self.next() % n

    def between(self, lo: int, hi: int) -> int:
        """a value in [lo, hi] (lo <= hi)

        Lean:
            def Rng.between (r : Rng) (lo hi : Int) : Int × Rng :=
              (lo + ((r.below ((hi - lo).toNat + 1)).1 : Int), (r.below ((hi - lo).toNat + 1)).2)
            theorem Rng.between_ge (r : Rng) (lo hi : Int) : lo ≤ (r.between lo hi).1 := by
              unfold Rng.between; omega
        """
        return lo + self.below(hi - lo + 1)

    def pick(self, items: list[str]) -> str:
        """one item of a non-empty list

        Lean:
            def Rng.pick (r : Rng) (items : List String) : String × Rng :=
              (items.getD (r.below items.length).1 "", (r.below items.length).2)
        """
        return items[self.below(len(items))]


def ascii_lower(c: str) -> str:
    """one character in lower case, ASCII letters only (Lean's Char.toLower and Rust's to_ascii_lowercase agree)

    Lean:
        def asciiLower (c : Char) : Char := c.toLower
        #guard asciiLower 'Q' == 'q'                         -- py: ascii_lower("Q") == "q"
        #guard asciiLower 'é' == 'é'                         -- py: ascii_lower("é") == "é"
    """
    return chr(ord(c) + 32) if "A" <= c <= "Z" else c


def is_ascii_alnum(c: str) -> bool:
    """Lean:
        def isAsciiAlnum (c : Char) : Bool := c.isAlphanum
        #guard isAsciiAlnum '7' && !isAsciiAlnum '-'          -- py: is_ascii_alnum("7") and not is_ascii_alnum("-")
    """
    return "a" <= c <= "z" or "A" <= c <= "Z" or "0" <= c <= "9"


def lower(text: str) -> str:
    """ASCII lower case of a whole string

    Lean:
        def lower (s : String) : String := s.map asciiLower
        #guard lower "VeriWave AI" == "veriwave ai"          -- py: lower("VeriWave AI") == "veriwave ai"
    """
    return "".join(ascii_lower(c) for c in text)


def slug(text: str) -> str:
    """lower-case ASCII letters and digits joined by single hyphens

    Lean:
        def slugAux : List Char → Bool → List Char → List Char
          | [], _, acc => acc.reverse
          | c :: cs, pendingDash, acc =>
            if isAsciiAlnum c then
              slugAux cs false (asciiLower c :: (if pendingDash && !acc.isEmpty then '-' :: acc else acc))
            else slugAux cs true acc
        def slug (s : String) : String := String.mk (slugAux s.toList false [])
        #guard slug "  Hello, World!  " == "hello-world"     -- py: slug("  Hello, World!  ") == "hello-world"
        #guard slug "To-Do List 2" == "to-do-list-2"         -- py: slug("To-Do List 2") == "to-do-list-2"
        #guard slug "***" == ""                               -- py: slug("***") == ""
    """
    out: list[str] = []
    pending = False
    for c in text:
        if is_ascii_alnum(c):
            if pending and out:
                out.append("-")
            out.append(ascii_lower(c))
            pending = False
        else:
            pending = True
    return "".join(out)


def clamp(lo: int, hi: int, x: int) -> int:
    """x limited to [lo, hi]

    Lean:
        def clamp (lo hi x : Int) : Int := if x < lo then lo else if hi < x then hi else x
        theorem clamp_in (lo hi x : Int) (h : lo ≤ hi) : lo ≤ clamp lo hi x ∧ clamp lo hi x ≤ hi := by
          unfold clamp; split <;> (try split) <;> omega
        #guard clamp 0 100 140 == 100                         -- py: clamp(0, 100, 140) == 100
    """
    if x < lo:
        return lo
    if hi < x:
        return hi
    return x


def words(text: str) -> list[str]:
    """the ASCII words of text, lower case (letters, digits and apostrophes)

    Lean:
        def isWordChar (c : Char) : Bool := isAsciiAlnum c || c == '\''
        def wordsAux : List Char → List Char → List String → List String
          | [], cur, acc => (if cur.isEmpty then acc else String.mk cur.reverse :: acc).reverse
          | c :: cs, cur, acc =>
            if isWordChar c then wordsAux cs (asciiLower c :: cur) acc
            else wordsAux cs [] (if cur.isEmpty then acc else String.mk cur.reverse :: acc)
        def words (s : String) : List String := wordsAux s.toList [] []
        #guard words "Build me a To-Do app!" == ["build", "me", "a", "to", "do", "app"]   -- py: words("Build me a To-Do app!") == ["build", "me", "a", "to", "do", "app"]
    """
    out: list[str] = []
    cur: list[str] = []
    for c in text:
        if is_ascii_alnum(c) or c == "'":
            cur.append(ascii_lower(c))
        else:
            if cur:
                out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def has_phrase(ws: list[str], phrase: list[str]) -> bool:
    """whether the word list contains the phrase as consecutive words

    Lean:
        def hasPhrase : List String → List String → Bool
          | _, [] => true
          | [], _ :: _ => false
          | w :: ws, p => (p.isPrefixOf (w :: ws)) || hasPhrase ws p
        theorem hasPhrase_nil (ws : List String) : hasPhrase ws [] = true := by cases ws <;> rfl
        #guard hasPhrase ["a", "to", "do", "list"] ["to", "do"]   -- py: has_phrase(["a", "to", "do", "list"], ["to", "do"])
        #guard !hasPhrase ["to"] ["to", "do"]                      -- py: not has_phrase(["to"], ["to", "do"])
    """
    if not phrase:
        return True
    n = len(phrase)
    for i in range(len(ws) - n + 1):
        if ws[i:i + n] == phrase:
            return True
    return False


def has_any(ws: list[str], phrases: list[str]) -> bool:
    """whether any of the phrases (each given as text) occurs in the word list

    Lean:
        def hasAny (ws : List String) (phrases : List String) : Bool := phrases.any (fun p => hasPhrase ws (words p))
        #guard hasAny (words "please draw a cat") ["picture", "draw"]   -- py: has_any(words("please draw a cat"), ["picture", "draw"])
    """
    for p in phrases:
        if has_phrase(ws, words(p)):
            return True
    return False


def cut(text: str, limit: int) -> str:
    """text shortened to at most `limit` characters at a word boundary, without trailing punctuation

    Lean:
        def cut (s : String) (limit : Nat) : String :=
          if s.length ≤ limit then s else
            let head := String.mk (s.toList.take limit)
            let sp := (head.toList.reverse.dropWhile (· != ' ')).reverse
            let base := if sp.isEmpty then head.toList else sp
            String.mk (base.reverse.dropWhile (fun c => c == ' ' || c == ',' || c == ';' || c == ':' || c == '-')).reverse
        #guard cut "short" 10 == "short"                                  -- py: cut("short", 10) == "short"
        #guard cut "the quick brown fox" 12 == "the quick"                -- py: cut("the quick brown fox", 12) == "the quick"
    """
    if len(text) <= limit:
        return text
    head = text[:limit]
    sp = head[:head.rfind(" ") + 1] if " " in head else ""
    base = sp if sp else head
    return base.rstrip(" ,;:-")
