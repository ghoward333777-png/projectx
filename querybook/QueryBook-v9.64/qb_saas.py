"""QueryBook multi-tenant SaaS subsystem  [deterministic]  — Registry 8.7/8.13/8.14/8.15

Backend for the SaaS Admin console: tenant registry, users + roles, per-tenant edition plan,
usage metering, and a tenant summary that folds in rights (qb_rights) and the edition feature
set (qb_editions). Local git-ignored store; no LLM. Tenancy here is a deterministic registry +
namespacing contract — not a hardened production isolation layer (labelled as such).
"""

import json as _json, os as _os, time as _time, hashlib as _h

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_STORE = _os.path.join(_HERE, "qb_saas_store.json")
ROLES = ("owner", "admin", "educator", "author", "reader", "viewer")
PLAN_EDITION = {"starter": "light", "team": "medium", "enterprise": "full"}

def _load():
    try: return _json.load(open(_STORE, encoding="utf-8")) or {}
    except Exception: return {}
def _save(db):
    try:
        _json.dump(db, open(_STORE, "w", encoding="utf-8"))
        try: _os.chmod(_STORE, 0o600)
        except Exception: pass
    except Exception: pass
def _db():
    d = _load(); d.setdefault("tenants", {}); d.setdefault("usage", []); return d
def _tid(name):
    return "t_" + _h.sha256(name.encode()).hexdigest()[:10]


def create_tenant(name, plan="team", owner_email=None):
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "tenant name required"}
    plan = plan if plan in PLAN_EDITION else "team"
    db = _db(); tid = _tid(name)
    if tid in db["tenants"]:
        return {"ok": False, "error": "tenant already exists", "id": tid}
    db["tenants"][tid] = {"id": tid, "name": name, "plan": plan,
                          "edition": PLAN_EDITION[plan], "users": [], "created": int(_time.time())}
    if owner_email:
        db["tenants"][tid]["users"].append({"email": owner_email, "role": "owner"})
    _save(db)
    return {"ok": True, "id": tid, "plan": plan, "edition": PLAN_EDITION[plan]}

def list_tenants():
    db = _db()
    return {"tenants": [{"id": t["id"], "name": t["name"], "plan": t["plan"],
                         "edition": t["edition"], "users": len(t["users"])}
                        for t in db["tenants"].values()]}

def set_plan(tenant_id, plan):
    db = _db(); t = db["tenants"].get(tenant_id)
    if not t: return {"ok": False, "error": "no such tenant"}
    if plan not in PLAN_EDITION: return {"ok": False, "error": "unknown plan"}
    t["plan"] = plan; t["edition"] = PLAN_EDITION[plan]; _save(db)
    return {"ok": True, "plan": plan, "edition": t["edition"]}

def add_user(tenant_id, email, role="reader"):
    db = _db(); t = db["tenants"].get(tenant_id)
    if not t: return {"ok": False, "error": "no such tenant"}
    if role not in ROLES: return {"ok": False, "error": "unknown role"}
    email = (email or "").strip()
    if not email: return {"ok": False, "error": "email required"}
    t["users"] = [u for u in t["users"] if u["email"] != email]
    t["users"].append({"email": email, "role": role}); _save(db)
    return {"ok": True, "users": len(t["users"])}

def record_usage(tenant_id, metric, n=1):
    db = _db()
    if tenant_id not in db["tenants"]: return {"ok": False, "error": "no such tenant"}
    db["usage"].append({"tenant": tenant_id, "metric": metric, "n": n, "when": int(_time.time())})
    _save(db); return {"ok": True}

def tenant_summary(tenant_id):
    db = _db(); t = db["tenants"].get(tenant_id)
    if not t: return {"ok": False, "error": "no such tenant"}
    usage = {}
    for u in db["usage"]:
        if u["tenant"] == tenant_id:
            usage[u["metric"]] = usage.get(u["metric"], 0) + u["n"]
    feats = []
    try:
        import qb_editions
        feats = sorted(qb_editions.features(t["edition"]))
    except Exception:
        pass
    return {"ok": True, "tenant": t["name"], "id": t["id"], "plan": t["plan"], "edition": t["edition"],
            "users": t["users"], "roles": list(ROLES), "usage": usage,
            "entitled_features": feats,
            "note": "Deterministic tenant registry + namespacing contract; not a hardened "
                    "production isolation layer. Edition is derived from plan."}


def qc():
    global _STORE; orig = _STORE; _STORE = orig + ".qc"
    try:
        try: _os.remove(_STORE)
        except OSError: pass
        checks = []
        c = create_tenant("Acme School", plan="enterprise", owner_email="head@acme.edu")
        ck = lambda n, x: checks.append({"check": n, "pass": bool(x)})
        ck("tenant created (enterprise→full)", c["ok"] and c["edition"] == "full")
        ck("duplicate rejected", not create_tenant("Acme School")["ok"])
        ck("add educator", add_user(c["id"], "teacher@acme.edu", "educator")["ok"])
        ck("bad role rejected", not add_user(c["id"], "x@acme.edu", "wizard")["ok"])
        record_usage(c["id"], "lessons", 3); record_usage(c["id"], "lessons", 2)
        s = tenant_summary(c["id"])
        ck("usage metered", s["usage"].get("lessons") == 5)
        ck("entitled features (full)", len(s["entitled_features"]) >= 20)
        ck("plan change team→medium", set_plan(c["id"], "team")["edition"] == "medium")
        ck("tenant listed", len(list_tenants()["tenants"]) == 1)
        passed = sum(1 for c2 in checks if c2["pass"])
        return {"passed": passed, "total": len(checks), "ok": passed == len(checks), "rows": checks}
    finally:
        try: _os.remove(_STORE)
        except OSError: pass
        _STORE = orig

if __name__ == "__main__":
    import json; print(json.dumps(qc(), indent=2))
