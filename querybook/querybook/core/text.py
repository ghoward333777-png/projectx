"""Deterministic text kernel, mirrored line-for-line in rust/querybook-core.

Parity contract (checked by both test suites against contracts/golden_text.tsv):
normalize_ws, tokenize, fnv1a64, content_hash and classify must return the
same values in Python and Rust. Python additionally applies NFC (stdlib
unicodedata); the Rust port adds it via the unicode-normalization crate.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from querybook.core.model import DOMAINS

INVISIBLE = frozenset("​‌‍⁠﻿­")

STOPWORDS = frozenset(
    "a an and are as at be been but by can could did do does for from had has have he her his i if in "
    "into is it its may might more most no not of on or our she should so such than that the their them "
    "then there these they this those to too was we were what when where which while who why will with "
    "would you your also about after before between over under all any each other some only very just".split()
)


def normalize_ws(text: str) -> str:
    """Drop invisible characters, collapse every whitespace run to one space, trim."""
    return " ".join("".join(ch for ch in text if ch not in INVISIBLE).split())


def normalize(text: str) -> str:
    return normalize_ws(unicodedata.normalize("NFC", text))


def normalize_paragraphs(text: str) -> str:
    """normalize() each paragraph but keep paragraph breaks (one blank line)."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    paras = [normalize_ws(p) for p in re.split(r"\n\s*\n", text)]
    return "\n\n".join(p for p in paras if p)


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    for ch in text.lower():
        if ch.isalnum():
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def fnv1a64(data: bytes) -> str:
    h = 0xCBF29CE484222325
    for b in data:
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


def content_hash(text: str) -> str:
    return fnv1a64(normalize(text).lower().encode("utf-8"))


def load_lexicons(path: Path | None = None) -> dict[str, frozenset[str]]:
    path = path or Path(__file__).with_name("lexicons.txt")
    lex: dict[str, frozenset[str]] = {d: frozenset() for d in DOMAINS}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        name, words = line.split(":", 1)
        if name.strip() in lex:
            lex[name.strip()] = frozenset(words.split())
    return lex


LEXICONS = load_lexicons()


def classify(text: str, lexicons: dict[str, frozenset[str]] | None = None) -> tuple[str, dict[str, int]]:
    """Score text against each domain lexicon; ties go to the earlier domain.

    Four-digit tokens between 1000 and 2100 count once toward history.
    Text that matches nothing is filed under language (it is still text).
    """
    lex = lexicons or LEXICONS
    scores = {d: 0 for d in DOMAINS}
    for tok in tokenize(text):
        for d in DOMAINS:
            if tok in lex[d]:
                scores[d] += 1
        if len(tok) == 4 and tok.isascii() and tok.isdigit() and 1000 <= int(tok) <= 2100:
            scores["history"] += 1
    best = DOMAINS[0]
    for d in DOMAINS:
        if scores[d] > scores[best]:
            best = d
    return best, scores


def keywords(text: str, limit: int = 10) -> list[str]:
    counts: dict[str, int] = {}
    for tok in tokenize(text):
        if len(tok) >= 4 and tok not in STOPWORDS and not tok.isdigit():
            counts[tok] = counts.get(tok, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[\"'“(A-Z0-9])")


def sentences(text: str) -> list[str]:
    out: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        out.extend(s.strip() for s in _SENTENCE.split(normalize_ws(para)) if s.strip())
    return out
