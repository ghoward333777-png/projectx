"""Integrity: provenance seals (lineage) + UIAS  [deterministic]
Registry features 8.8.x NFT/lineage (109–118) and 20.x UIAS (204–209).

HONEST NAMING: this is a LOCAL, hash-chained provenance ledger and an HMAC-signed proof
package — NOT a blockchain and NOT an on-chain NFT. It gives tamper-evident local provenance:
each seal's id chains the previous seal's hash, so any edit to history is detectable. The HMAC
key is a local secret (git-ignored). Deterministic given the same inputs + key.

UIAS (Universal Integrity Audit Service):
 - seal(text, author): a pre-dispute, timestamped Fact-Unit seal over a submission.
 - similarity(a, b): deterministic k-shingle Jaccard for cross-submission overlap.
 - proof_package(seal_id): the seal + an HMAC signature + issue time.
"""

import hashlib as _h, hmac as _hmac, json as _json, os as _os, time as _time

_LEDGER = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "qb_ledger.json")
_KEYFILE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "qb_integrity_key")

def _key():
    try:
        return open(_KEYFILE, "rb").read()
    except Exception:
        k = _h.sha256(_os.urandom(32)).hexdigest().encode()
        try:
            open(_KEYFILE, "wb").write(k); _os.chmod(_KEYFILE, 0o600)
        except Exception:
            pass
        return k

def _load():
    try: return _json.load(open(_LEDGER, encoding="utf-8")) or []
    except Exception: return []
def _save(chain):
    try:
        _json.dump(chain, open(_LEDGER, "w", encoding="utf-8"))
        try: _os.chmod(_LEDGER, 0o600)
        except Exception: pass
    except Exception: pass

def _sha(*parts):
    h = _h.sha256()
    for p in parts: h.update(str(p).encode("utf-8"))
    return h.hexdigest()


def mint(kind, ref, meta=None, now=None):
    """Append a provenance seal to the local hash chain. Returns the seal record."""
    chain = _load()
    prev = chain[-1]["id"] if chain else "GENESIS"
    ts = int(now if now is not None else _time.time())
    payload_hash = _sha(kind, ref, _json.dumps(meta or {}, sort_keys=True))
    sid = _sha(prev, kind, ref, payload_hash, ts)
    rec = {"id": sid, "prev": prev, "kind": kind, "ref": ref, "payload_hash": payload_hash,
           "ts": ts, "meta": meta or {}}
    chain.append(rec); _save(chain)
    return rec

def lineage(seal_id):
    chain = _load()
    byid = {r["id"]: r for r in chain}
    out, cur = [], byid.get(seal_id)
    while cur:
        out.append(cur)
        cur = byid.get(cur["prev"]) if cur["prev"] != "GENESIS" else None
    return out

def verify_chain():
    """Recompute every seal id from its predecessor; report the first break, if any."""
    chain = _load()
    prev = "GENESIS"
    for i, r in enumerate(chain):
        expect = _sha(prev, r["kind"], r["ref"], r["payload_hash"], r["ts"])
        if r["id"] != expect or r["prev"] != prev:
            return {"ok": False, "broken_at": i, "length": len(chain)}
        prev = r["id"]
    return {"ok": True, "length": len(chain)}


# ---- UIAS ----
def seal(text, author="anonymous", now=None):
    """Pre-dispute, timestamped seal over a submission (stored as a provenance seal)."""
    th = _sha(text)
    rec = mint("uias_seal", th, {"author": author, "word_count": len(text.split())}, now=now)
    return {"seal_id": rec["id"], "text_hash": th, "author": author, "ts": rec["ts"],
            "word_count": len(text.split())}

def _shingles(text, k=3):
    toks = text.lower().split()
    return set(tuple(toks[i:i+k]) for i in range(max(0, len(toks) - k + 1))) if len(toks) >= k \
        else set((tuple(toks),)) if toks else set()

def similarity(a, b, k=3):
    """Deterministic k-shingle Jaccard similarity (0..1) for cross-submission overlap."""
    sa, sb = _shingles(a, k), _shingles(b, k)
    if not sa and not sb: return {"similarity": 0.0, "shared": 0}
    inter = len(sa & sb); union = len(sa | sb) or 1
    return {"similarity": round(inter / union, 4), "shared": inter, "k": k}

def proof_package(seal_id):
    """The seal + an HMAC signature over its canonical form + issue time."""
    chain = _load()
    rec = next((r for r in chain if r["id"] == seal_id), None)
    if not rec: return {"ok": False, "error": "no such seal"}
    canonical = _json.dumps(rec, sort_keys=True)
    sig = _hmac.new(_key(), canonical.encode(), _h.sha256).hexdigest()
    return {"ok": True, "seal": rec, "signature": sig, "algo": "HMAC-SHA256",
            "issued": int(_time.time()), "chain_valid": verify_chain()["ok"],
            "note": "Local tamper-evident proof (HMAC + hash chain). Not a blockchain/NFT."}


def qc():
    global _LEDGER, _KEYFILE
    o1, o2 = _LEDGER, _KEYFILE
    _LEDGER = o1 + ".qc"; _KEYFILE = o2 + ".qc"
    try:
        for f in (_LEDGER, _KEYFILE):
            try: _os.remove(f)
            except OSError: pass
        checks = []
        s1 = seal("the quick brown fox jumps", "alice", now=1000)
        s2 = seal("a totally different submission here", "bob", now=1001)
        checks.append(("two seals chained", lineage(s2["seal_id"])[-1]["prev"] == "GENESIS"))
        checks.append(("chain verifies", verify_chain()["ok"]))
        sim = similarity("the quick brown fox", "the quick brown dog")
        checks.append(("similarity in range", 0 < sim["similarity"] < 1))
        pp = proof_package(s1["seal_id"])
        checks.append(("proof package signed", pp["ok"] and len(pp["signature"]) == 64))
        # tamper detection
        chain = _load(); chain[0]["ref"] = "TAMPERED"; _save(chain)
        checks.append(("tamper detected", not verify_chain()["ok"]))
        passed = sum(1 for _, c in checks if c)
        return {"passed": passed, "total": len(checks), "ok": passed == len(checks),
                "rows": [{"check": n, "pass": c} for n, c in checks]}
    finally:
        for f in (_LEDGER, _KEYFILE):
            try: _os.remove(f)
            except OSError: pass
        _LEDGER, _KEYFILE = o1, o2

if __name__ == "__main__":
    import json; print(json.dumps(qc(), indent=2))
