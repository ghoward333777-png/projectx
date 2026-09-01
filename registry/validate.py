#!/usr/bin/env python3
"""
Validate the QueryBook registry. Run after any change to data/.
Exits non-zero on any failure, so it can gate a commit.
"""
import json, sys, collections, pathlib

D = pathlib.Path(__file__).parent / "data"
F = json.load(open(D / "features.json"))
C = json.load(open(D / "claims.json"))
DOM = json.load(open(D / "domains.json"))
TM = json.load(open(D / "transfer_matrix.json"))

fail = []

def check(cond, msg):
    print(f"  {'PASS' if cond else 'FAIL'}  {msg}")
    if not cond:
        fail.append(msg)

print("=== CLAIMS ===")
ids = [c["id"] for c in C]
check(ids == list(range(1, len(ids) + 1)), f"contiguous 1-{len(ids)}")
check(all(d in ids for c in C for d in c["depends_on"]), "no dangling dependency")
check(all(d < c["id"] for c in C for d in c["depends_on"]), "no forward or self dependency")
check(all(len(c["depends_on"]) <= 1 for c in C), "no multiple dependency")
check(all(len(c["text"]) >= 60 for c in C), "no claim under 60 characters")
indep = [c["id"] for c in C if not c["depends_on"]]
check(len(indep) > 0, f"{len(indep)} independent claims: {indep}")

print("\n=== FEATURES ===")
required = ["name", "category", "citation", "actor", "algorithm", "rule", "domain", "layer"]
for k in required:
    check(all(f.get(k) for f in F), f"no blank '{k}'")
check(len({f["id"] for f in F}) == len(F), "feature ids unique")
check(len({f["name"] for f in F}) == len(F), "feature names unique")
doms = {d["id"] for d in DOM}
check(all((f["domain"] or "").split()[0] in doms for f in F), "every feature in a known domain")

print("\n=== ARCHITECTURE ===")
check(len(DOM) == 15, "15 domains")
layers = {d["layer"] for d in DOM}
check(len(layers) == 5, f"5 layers: {sorted(layers)}")
denied = {(t["from"], t["to"]) for t in TM if t["permission"] == "denied"}
for pair in [("D11", "D0"), ("D7", "D2"), ("D13", "D4"), ("D13", "D7"), ("D9", "D2")]:
    check(pair in denied, f"{pair[0]} -> {pair[1]} denied")

print("\n=== CROSS-REFERENCE ===")
counted = collections.Counter((f["domain"] or "").split()[0] for f in F)
check(all(d["feature_count"] == counted.get(d["id"], 0) for d in DOM),
      "domain feature counts match the feature list")

print(f"\n{'ALL CHECKS PASSED' if not fail else str(len(fail)) + ' FAILURE(S)'}")
sys.exit(1 if fail else 0)
