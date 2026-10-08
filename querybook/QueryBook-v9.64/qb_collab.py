"""QueryBook Collaboration subsystem  [deterministic]  — Registry 8.11 (146–155)

Backend for the Collaboration workspace: annotations, threaded discussions, shared resources,
and an activity feed. Every record is provenance-stamped (and sealed via qb_integrity when
present). Local git-ignored store; no LLM. Collaboration records are attributed user content,
never promoted to world-facts.
"""

import json as _json, os as _os, time as _time, hashlib as _h

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_STORE = _os.path.join(_HERE, "qb_collab_store.json")

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
    d = _load()
    for k in ("annotations", "threads", "resources", "activity"):
        d.setdefault(k, [] if k != "threads" else {})
    return d
def _id(*p):
    return _h.sha256(("|".join(str(x) for x in p) + str(_time.time())).encode()).hexdigest()[:12]
def _seal(kind, ref):
    try:
        import qb_integrity
        return qb_integrity.mint(kind, ref)["id"]
    except Exception:
        return None
def _activity(db, who, what):
    db["activity"].insert(0, {"who": who, "what": what, "when": int(_time.time())})
    db["activity"] = db["activity"][:100]


def add_resource(title, owner, body="", tenant=None):
    db = _db(); rid = _id("res", title)
    db["resources"].append({"id": rid, "title": title, "owner": owner, "body": body,
                            "tenant": tenant, "seal": _seal("resource", title), "when": int(_time.time())})
    _activity(db, owner, "shared resource '%s'" % title); _save(db)
    return {"ok": True, "id": rid}

def list_resources(tenant=None):
    db = _db()
    rs = [r for r in db["resources"] if (not tenant or r.get("tenant") == tenant)]
    return {"resources": rs}

def add_annotation(resource_id, author, text, anchor=None):
    db = _db(); aid = _id("ann", resource_id, author)
    db["annotations"].append({"id": aid, "resource": resource_id, "author": author, "text": text,
                              "anchor": anchor, "seal": _seal("annotation", text), "when": int(_time.time())})
    _activity(db, author, "annotated a resource"); _save(db)
    return {"ok": True, "id": aid}

def list_annotations(resource_id):
    db = _db()
    return {"annotations": [a for a in db["annotations"] if a["resource"] == resource_id]}

def post_thread(resource_id, author, text, parent=None):
    db = _db(); tid = _id("msg", resource_id, author)
    root = parent or resource_id
    db["threads"].setdefault(root, [])
    db["threads"][root].append({"id": tid, "author": author, "text": text, "parent": parent,
                                "seal": _seal("message", text), "when": int(_time.time())})
    _activity(db, author, "posted in a discussion"); _save(db)
    return {"ok": True, "id": tid, "root": root}

def get_thread(root):
    db = _db()
    return {"root": root, "messages": db["threads"].get(root, [])}

def activity(limit=30):
    db = _db()
    return {"activity": db["activity"][:limit]}

def qc():
    global _STORE; orig = _STORE; _STORE = orig + ".qc"
    try:
        for f in (_STORE,):
            try: _os.remove(f)
            except OSError: pass
        checks = []
        r = add_resource("Chapter 1", "alice", "The quick brown fox...")
        ck = lambda n, c: checks.append({"check": n, "pass": bool(c)})
        ck("resource created", r["ok"])
        a = add_annotation(r["id"], "bob", "Great opening line", anchor="p1")
        ck("annotation created", a["ok"])
        ck("annotation listed", len(list_annotations(r["id"])["annotations"]) == 1)
        t = post_thread(r["id"], "alice", "What did you think?")
        post_thread(r["id"], "bob", "I liked it.", parent=r["id"])
        ck("thread has 2 messages", len(get_thread(r["id"])["messages"]) == 2)
        ck("activity feed populated", len(activity()["activity"]) >= 3)
        passed = sum(1 for c in checks if c["pass"])
        return {"passed": passed, "total": len(checks), "ok": passed == len(checks), "rows": checks}
    finally:
        try: _os.remove(_STORE)
        except OSError: pass
        _STORE = orig

if __name__ == "__main__":
    import json; print(json.dumps(qc(), indent=2))
