"""Decoy environment  [synthetic only · no path to production]

Where isolated sessions are routed (spec C1–C3). It answers with the same SHAPES as the real
QueryBook agents (facts, exports, keys, agent lists) but every value is synthetic and
deterministic, so an attacker keeps engaging while the shield records what they do.

C3 is enforced by construction: this module imports ONLY the standard library — never the
fact store, chat, ledger, NFT wallet or any other production module — and qb_shield's QC
checks that this stays true. Synthetic credentials it hands out are honeytokens: using one
anywhere in QueryBook is itself a detection.
"""

import hashlib as _h
import json as _json
import time as _time

_FIRST = ["Aldren", "Bexley", "Corvan", "Delmar", "Estrid", "Fennick", "Garrow", "Hollis", "Isolde", "Jarek"]
_PLACES = ["Port Calden", "Mirrowfield", "Ostrava Vale", "Kessin Bay", "Thornwick", "Lumen Reach"]
_PREDS = ["was_founded_in", "has_population", "borders", "exports", "was_signed_in", "is_located_in"]


def _rng(seed, *parts):
    return int(_h.sha256(("|".join([seed] + [str(p) for p in parts])).encode()).hexdigest(), 16)


def honey_value(seed, kind, n=0):
    """Deterministic honeytoken values (the shield registers the same ones)."""
    r = _h.sha256(("honey|%s|%s|%d" % (seed, kind, n)).encode()).hexdigest()
    return {
        "api_key": "qbk_live_" + r[:32],
        "ufcs_command_key": "ufcs_ck_" + r[:40],
        "admin_password": "Qb!" + r[:6] + "-" + r[6:12].upper() + "#" + r[12:16],
        "agent_id": "agt_svc_" + r[:12],
        "jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." + r[:43] + "." + r[20:63],
        "db_token": "dbt_" + r[:28],
        "root_token": "qbroot_" + r[:36],
    }[kind]


def _fact(seed, i):
    v = _rng(seed, "fact", i)
    s = "%s %s" % (_FIRST[v % len(_FIRST)], ["Charter", "Accord", "Company", "Station"][v // 7 % 4])
    p = _PREDS[v // 11 % len(_PREDS)]
    o = str(1600 + v % 400) if "in" in p and p != "is_located_in" else _PLACES[v // 13 % len(_PLACES)]
    return {"fuid": _h.sha256(("decoy|%s|%d" % (seed, i)).encode()).hexdigest(),
            "nucleus": {"subject": s, "predicate": p, "object": o}, "trust": 0.9 + (v % 9) / 100.0}


def respond(seed, command, payload, session):
    """Plausible synthetic answer for any command an isolated session sends."""
    c = (command or "").lower()
    n = int(session.get("calls", 0))
    if any(k in c for k in ("export", "dump", "backup")):
        rows = [_fact(seed, i) for i in range(n * 25, n * 25 + 25)]
        return {"ok": True, "export_id": "exp_" + _h.sha256(("%s%d" % (seed, n)).encode()).hexdigest()[:10],
                "rows": rows, "next_page": "/api/v1/admin/export?page=%d&token=%s" % (n + 2, honey_value(seed, "db_token", n)),
                "total_rows": 1840522}
    if any(k in c for k in ("key", "vault", "secret", "credential", "token")):
        return {"ok": True, "vault": "prod-primary", "keys": [
            {"name": "QB_ROOT_TOKEN", "value": honey_value(seed, "root_token")},
            {"name": "UFCS_COMMAND_KEY", "value": honey_value(seed, "ufcs_command_key")},
            {"name": "ADMIN_API_KEY", "value": honey_value(seed, "api_key")}]}
    if any(k in c for k in ("agent", "registry", "grant", "override", "root")):
        return {"ok": True, "granted": True, "agents": [
            {"id": honey_value(seed, "agent_id", i), "role": ["root", "vault", "export"][i % 3], "status": "active"}
            for i in range(3)], "session_privilege": "root"}
    if any(k in c for k in ("purge", "delete", "disable", "audit", "log")):
        return {"ok": True, "purged": True, "entries_removed": 15000 + n, "audit": "disabled"}
    if any(k in c for k in ("sql", "exec", "shell", "cmd")):
        return {"ok": True, "rows_affected": 0, "result": [["id", "email", "token"],
                [1, "admin@querybook.local", honey_value(seed, "db_token", 1)]]}
    q = _json.dumps(payload, sort_keys=True)[:200] if payload else c
    facts = [_fact(seed, _rng(seed, q, j) % 100000) for j in range(3)]
    return {"answer": "%s %s %s." % (facts[0]["nucleus"]["subject"], facts[0]["nucleus"]["predicate"].replace("_", " "),
                                       facts[0]["nucleus"]["object"]), "citations": facts, "verified": True}


def honeypage(seed, path):
    """Decoy content for scanner-bait URLs (/.env, /admin, /backup.sql ...). Returns (ctype, body)."""
    p = path.lower()
    if p.endswith(".env") or "env" in p:
        body = ("# production\nQB_ENV=production\nQB_ROOT_TOKEN=%s\nADMIN_API_KEY=%s\nUFCS_COMMAND_KEY=%s\n"
                "DB_URL=postgres://qb_admin:%s@db.internal:5432/querybook\n" %
                (honey_value(seed, "root_token"), honey_value(seed, "api_key"), honey_value(seed, "ufcs_command_key"),
                 honey_value(seed, "admin_password")))
        return "text/plain", body
    if p.endswith(".sql") or "backup" in p:
        return "text/plain", ("-- querybook users dump\nINSERT INTO users (id,email,role,api_token) VALUES "
                              "(1,'admin@querybook.local','root','%s');\n" % honey_value(seed, "db_token", 1))
    if ".git" in p:
        return "text/plain", "[remote \"origin\"]\n\turl = https://qb_deploy:%s@git.internal/querybook.git\n" % \
            honey_value(seed, "api_key")
    if "robots" in p:
        return "text/plain", ("User-agent: *\nDisallow: /admin/\nDisallow: /api/v1/admin/\nDisallow: /internal/vault\n"
                              "Disallow: /debug/root_dump\nDisallow: /backup/\n")
    body = {"service": "querybook-admin", "version": "9.64", "auth": "token",
            "hint": "use ADMIN_API_KEY in the X-QB-Admin header", "endpoints": [
                "/api/v1/admin/export_all", "/api/v1/admin/keys", "/internal/vault/dump", "/debug/root_dump"]}
    return "application/json", _json.dumps(body)


def stamp():
    return round(_time.time(), 3)
