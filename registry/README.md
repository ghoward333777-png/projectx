# QueryBook Technical Registry

Machine-readable registry of every specified feature, function and claim.
Import target: a Claude Code project. Everything here is derived from the
specification rather than hand-maintained, and `validate.py` re-derives the
integrity checks so the data can gate a commit.

## Counts

| | |
|---|---|
| Features | **279** |
| Claims | **341** (7 independent) |
| Worked expressions | **229** |
| Domains | 15 (D0 vertical + D1-D14) |
| Layers | 5 |

Provisional 63/975,036 filed 2026-02-03, expires **2027-02-03**.
Assignee Mediagration, LLC.

## Layout

```
registry/
  validate.py            run after any change; exits non-zero on failure
  SCHEMA.md              field-by-field description
  data/
    features.json        279 features, full detail
    features.csv         same, flat
    claims.json          341 claims with dependency structure
    claims.csv           same, flat
    domains.json         15 domains with mandate and feature count
    transfer_matrix.json permitted, denied and conversion-required transfers
    paths.json           execution paths and the path-separation invariants
    excluded_set.json    subsystems no internal proposal may modify
    manifest.json        computed counts and integrity results
```

## Quick start

```bash
python3 validate.py                      # gate: all checks must pass
python3 -c "import json;print(len(json.load(open('data/features.json'))))"
```

```python
import json
F = json.load(open("data/features.json"))
C = json.load(open("data/claims.json"))

# features in one domain
[f["name"] for f in F if f["domain"].startswith("D4")]

# a feature's claims are found by citation, not by a stored link:
# claims cite mechanisms, features cite chapters. Join on citation text
# where you need the mapping, and expect it to be approximate.

# claim dependency chain
def chain(cid):
    c = next(x for x in C if x["id"] == cid)
    return [cid] + (chain(c["depends_on"][0]) if c["depends_on"] else [])
```

## Rules this data encodes

Five constraints are structural rather than advisory, and code built on this
registry should treat them as invariants:

1. **Exactly one domain owns each decision.** No consensus mechanism among
   domains exists or should be added.
2. **A denied transfer has no route.** `transfer_matrix.json` denials are
   enforced by absence, not by a check that could be omitted.
3. **Generation cannot write.** D7 to D2 is denied. No cache or memoisation
   inside D7 may persist to the store.
4. **Scope precedes traversal.** D8 executes before D4 in every path.
5. **The excluded set cannot be modified from within**, including itself.

## Provenance and caveats

Feature `algorithm` and `rule` text is the specification's own wording.
`worked_expression` is spreadsheet notation that evaluates; 50
features are qualitative and carry none.

`module` is derived by clustering features on citation chapter within a domain,
so it reflects what was specified together rather than a declared package
boundary. Treat it as a hint.

`lean_statement` fields are marked reference-only and are **unverified** —
never executed against Mathlib. Nothing depends on them.

Six features are disclosed but not claimed; they carry a written reason in the
source specification and are not flagged in this data.
