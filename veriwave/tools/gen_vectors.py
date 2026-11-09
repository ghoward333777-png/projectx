"""Golden vectors: the Python engine's answers for a fixed set of inputs, which the Rust port must reproduce exactly.

    python tools/gen_vectors.py           write contracts/vectors.tsv
    python tools/gen_vectors.py --check   fail if it is out of date

Format: one vector per line, `function<TAB>input<TAB>expected`, with backslash, tab and newline escaped as \\\\ \\t \\n.
Lists are joined with '|'; facts as subject;predicate;object joined by '|'; no value is written as ∅.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from vw import core, router, verdict  # noqa: E402

OUT = os.path.join(ROOT, "contracts", "vectors.tsv")
TEXTS = ["", "a", "VeriWave", "Hello, World!", "  To-Do List 2  ", "Ünïcödé café", "Build me a to-do app!", "it's 5 o'clock",
         "***", "draw a lighthouse at sunset", "What is 15% of 80?", "Paris (Q90) is in France (Q142)"]
MESSAGES = ["Build me a to-do app", "Draw a lighthouse at sunset", "make a short video about bees", "compose a calm melody",
            "write a poem about the sea", "When was the printing press invented?", "open the language lab", "hello",
            "/code a timer", "/image a red fox", "write a python script that counts words", "say good morning",
            "what can you do", "make me a song about rain", "create a logo for a bakery", "60 mph to km/h", "", "thanks!",
            "show me the feature registry", "animate a bouncing ball", "please narrate this paragraph", "write an email to my landlord"]
EXPRS = ["What is 15% of 80?", "2^10 / 3", "(1.5 + 2.25) * -4", "1/0", "60 mph to km/h", "hello", "-2^2", "2^-1", "3*(4+5)/2",
         "1+", "((2))", "0.1+0.2", "2^61", "2^62", "99999999999999999999", "1,000 × 3 =", "7 ÷ 8", "1/3 + 1/6", "-(3-5)^3",
         "2^2^3", "10 % of 50", "5 -- 3", "3 +", "()", "1 2", "0^-1", "12.500 * 4", "calculate 22/7"]
STATUSES = ["Verified", "", "disputed", " HARVESTED ", "unknown-thing", "rejected"]
FACTSETS = [[], [("Rome", "inception", "753 BC")], [("Rome", "inception", "753 BC"), ("Rome (Q220)", "Inception", "752 BC")],
            [("Curie", "award received", "Nobel Physics"), ("Curie", "award received", "Nobel Chemistry")],
            [("A", "date of birth", "1900"), ("B", "date of birth", "1901")], [("A", "p", "x"), ("a", "P", " X ")]]


def esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")


def rows() -> list[str]:
    out: list[str] = []
    add = lambda fn, inp, exp: out.append(fn + "\t" + esc(inp) + "\t" + esc(exp))
    for t in TEXTS:
        add("fnv1a32", t, str(core.fnv1a32(t)))
        add("slug", t, core.slug(t))
        add("words", t, "|".join(core.words(t)))
        add("strip_qids", t, verdict.strip_qids(t))
    for x in (1, 2, 270369, 2463534242, 4294967295):
        add("xorshift32", str(x), str(core.xorshift32(x)))
    for m in MESSAGES:
        add("route", m, router.route(m))
        add("screen_for", m, router.screen_for(m))
    for e in EXPRS:
        r = verdict.calculate(e)
        add("calculate", e, "∅" if r is None else r)
    for s in STATUSES:
        add("status_trust", s, str(verdict.status_trust(s)))
    for p in ("award received", "date of birth", "Occupation", "inception"):
        add("multi_valued", p, "true" if verdict.multi_valued(p) else "false")
    for fs in FACTSETS:
        enc = "|".join(";".join(f) for f in fs)
        add("verdict", enc, verdict.verdict([{"subject": a, "predicate": b, "object": c} for a, b, c in fs]))
    return out


def main(argv: list[str]) -> int:
    text = "".join(r + "\n" for r in rows())
    if "--check" in argv:
        try:
            cur = open(OUT, encoding="utf-8").read()
        except OSError:
            cur = ""
        if cur != text:
            print("contracts/vectors.tsv is out of date: run python tools/gen_vectors.py")
            return 1
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("wrote %d vectors" % len(rows()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
