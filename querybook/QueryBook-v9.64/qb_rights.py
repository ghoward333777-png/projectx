"""Licensing & rights  [deterministic]  — Registry features 8.7.x (097–108)

A local license registry + a rights-aware access gate. Each resource maps to terms
(territories, editions, expiry, holder). check() decides allow/deny deterministically with
reasons; redact() blanks disallowed content. Local git-ignored store. No LLM.
"""

import json as _json, os as _os, time as _time

_STORE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "qb_rights_store.json")

def _load():
    try: return _json.load(open(_STORE, encoding="utf-8")) or {}
    except Exception: return {}
def _save(db):
    try:
        _json.dump(db, open(_STORE, "w", encoding="utf-8"))
        try: _os.chmod(_STORE, 0o600)
        except Exception: pass
    except Exception: pass

def grant(resource, territories=None, editions=None, expires=None, holder=None):
    db = _load()
    db[resource] = {"territories": territories or ["*"], "editions": editions or ["*"],
                    "expires": expires, "holder": holder, "granted": int(_time.time())}
    _save(db); return {"ok": True, "resource": resource, "terms": db[resource]}

def revoke(resource):
    db = _load()
    if resource in db: del db[resource]; _save(db); return {"ok": True}
    return {"ok": False, "error": "no such resource"}

def check(resource, territory="*", edition="*", now=None):
    db = _load(); t = db.get(resource)
    if not t:
        return {"allowed": True, "reasons": ["no license on record (open by default)"]}
    now = now or int(_time.time())
    reasons, allowed = [], True
    if t.get("expires") and now > t["expires"]:
        allowed = False; reasons.append("license expired")
    if "*" not in t["territories"] and territory not in t["territories"]:
        allowed = False; reasons.append("territory '%s' not licensed" % territory)
    if "*" not in t["editions"] and edition not in t["editions"]:
        allowed = False; reasons.append("edition '%s' not licensed" % edition)
    if allowed: reasons.append("within licensed scope")
    return {"allowed": allowed, "reasons": reasons, "holder": t.get("holder")}

def redact(text, allowed):
    return text if allowed else "█ [redacted — not licensed in this scope] █"

def registry():
    return {"licenses": _load()}

def qc():
    global _STORE; orig = _STORE; _STORE = orig + ".qc"
    try:
        try: _os.remove(_STORE)
        except OSError: pass
        checks = []
        grant("bookA", territories=["US", "CA"], editions=["full"], expires=None, holder="Pub")
        checks.append(("open resource allowed", check("open")["allowed"]))
        checks.append(("US/full allowed", check("bookA", "US", "full")["allowed"]))
        checks.append(("UK denied", not check("bookA", "UK", "full")["allowed"]))
        checks.append(("light edition denied", not check("bookA", "US", "light")["allowed"]))
        expd = check("bookA", "US", "full", now=0)  # pre-grant epoch is fine; test expiry path:
        grant("bookB", expires=1)
        checks.append(("expired denied", not check("bookB", now=2)["allowed"]))
        checks.append(("redaction", redact("secret", False).startswith("█")))
        passed = sum(1 for _, c in checks if c)
        return {"passed": passed, "total": len(checks), "ok": passed == len(checks),
                "rows": [{"check": n, "pass": c} for n, c in checks]}
    finally:
        try: _os.remove(_STORE)
        except OSError: pass
        _STORE = orig

if __name__ == "__main__":
    import json; print(json.dumps(qc(), indent=2))
