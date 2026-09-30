#!/usr/bin/env python3
"""Export a parity vector set from the Python prototype (the oracle).

For each nucleus tuple we record the prototype's own fingerprint() and fuid(),
so the Rust qb-core can be proven to reproduce them byte-for-byte. Input fields
are hex-encoded UTF-8 (delimiter/escaping-proof); the two hashes are plain hex.

Run:  python gen_vectors.py            # writes vectors.tsv next to this file
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE = os.path.normpath(os.path.join(HERE, "..", "..", "prototype", "QueryBook-baseline-v9.15"))
sys.path.insert(0, BASELINE)
import ufcs_store as store   # the oracle

# (subject, predicate, object, polarity, source_id, ingested)
VECTORS = [
    ("France", "has_capital", "Paris", "+", "SRC-GEN", "2026-09-30T00:00:00Z"),
    ("  FRANCE  ", "HAS_CAPITAL", "paris", "+", "SRC-GEN", "2026-09-30T00:00:00Z"),   # case/space normalize
    ("France", "has_capital", "Lyon", "+", "SRC-GEN", "2026-09-30T00:00:00Z"),        # distinct object
    ("x    y", "spans", "o", "+", "SRC-A", "2026-01-02T03:04:05Z"),                    # multi-space collapse
    ("a\tb\nc", "p", "o", "+", "SRC-A", "2026-01-02T03:04:05Z"),                       # tab/newline whitespace
    ("water", "boils_at", "100 °C", "+", "SRC-SCI", "2026-05-05T05:05:05Z"),      # non-ASCII (ensure_ascii)
    ("café", "significa", "coffee", "+", "SRC-DICT", "2026-06-06T06:06:06Z"),     # accented lowercase
    ("CAFÉ", "SIGNIFICA", "Coffee", "+", "SRC-DICT", "2026-06-06T06:06:06Z"),     # accented uppercase -> same norm
    ("日本語", "means", "Japanese", "+", "SRC-DICT", "2026-06-06T06:06:06Z"),  # CJK
    ("Mars", "may_have", "life", "-", "SRC-HYP", "2026-07-07T07:07:07Z"),              # negative polarity
    ("quote\"and\\slash", "p", "o", "+", "SRC-X", "2026-08-08T08:08:08Z"),             # JSON-escaping chars
    ("sparrow", "is_a", "bird", "+", "SRC-GEN", "2026-09-09T09:09:09Z"),
    ("H2O", "same_as", "water", "+", "SRC-GEN", "2026-09-09T09:09:09Z"),
    ("emoji \U0001F600 face", "p", "o", "+", "SRC-X", "2026-08-08T08:08:08Z"),         # astral plane (surrogate pair)
]


def hx(s):
    return s.encode("utf-8").hex()


def main():
    out = os.path.join(HERE, "vectors.tsv")
    n = 0
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("# QueryBook parity vectors — exported from ufcs_store (the oracle)\n")
        fh.write("# hex(subject) hex(predicate) hex(object) hex(polarity) hex(source_id) hex(ingested) fingerprint fuid\n")
        for (s, p, o, pol, sid, ing) in VECTORS:
            fp = store.fingerprint(s, p, o, pol)
            fu = store.fuid(s, p, o, pol, sid, ing)
            fh.write("\t".join([hx(s), hx(p), hx(o), hx(pol), hx(sid), hx(ing), fp, fu]) + "\n")
            n += 1
    print("wrote %d vectors to %s" % (n, out))


if __name__ == "__main__":
    main()
