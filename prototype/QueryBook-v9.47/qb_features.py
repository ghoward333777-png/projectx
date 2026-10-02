"""QueryBook feature manifest — the single source that ties the running prototype to the
Bible & Registry.

Every subsystem the prototype ships is listed here with: the system it belongs to, its Registry
cross-reference, the module(s) that implement it, the API endpoints that expose it, the UI page
(if any), and a status. `catalog()` LIVE-CHECKS each entry (module importable? page present?) so
the app can report its own feature coverage and drift against the canon. Deterministic; no LLM.

Keep this in sync with docs/QueryBook-Registry-Updated.txt and the Bible amendments — it is the
synchronization backbone used by /api/features and the traceability report.
"""

import os as _os

_HERE = _os.path.dirname(_os.path.abspath(__file__))

# system ∈ {ingestion, query, language, identity, knowledge, integrity, reasoning, platform}
FEATURES = [
    # ---- Ingestion ----
    {"id": "ingest.qa", "title": "Q&A / direct Fact-Unit ingestion", "system": "ingestion",
     "registry": "1 (ingestion)", "module": "ufcs_store,qb_language",
     "endpoints": ["/api/language/ingest", "/api/fact"], "page": None, "status": "built"},
    {"id": "ingest.web", "title": "Web harvester", "system": "ingestion", "registry": "1",
     "module": "qb_web_harvest", "endpoints": ["/api/harvest", "/api/harvest_status"],
     "page": "/ingest", "status": "built"},
    {"id": "ingest.language", "title": "Language ingestion (SLPL/LEL Phases 1–4)", "system": "ingestion",
     "registry": "[178]-[198]", "module": "qb_language,qb_agents",
     "endpoints": ["/api/language/teach", "/api/language/teach_all", "/api/language/run_all"],
     "page": "/language", "status": "built"},
    {"id": "ingest.deterministic", "title": "Deterministic domains (math/geometry/arithmetic)",
     "system": "ingestion", "registry": "domains", "module": "ufcs_store",
     "endpoints": ["/api/harvest", "/api/agents"], "page": "/ingest", "status": "built"},
    {"id": "ingest.history", "title": "History domain", "system": "ingestion", "registry": "23 (ingest ladder)",
     "module": "ufcs_store", "endpoints": ["/api/ingest/strategy"], "page": "/ingest", "status": "built"},
    {"id": "ingest.news", "title": "News domain (sample seed; web-driven)", "system": "ingestion",
     "registry": "23", "module": "ufcs_store", "endpoints": ["/api/ingest/strategy"], "page": "/ingest", "status": "built"},
    {"id": "ingest.culture", "title": "Culture domain", "system": "ingestion", "registry": "23",
     "module": "ufcs_store", "endpoints": ["/api/ingest/strategy"], "page": "/ingest", "status": "built"},
    {"id": "ingest.art", "title": "Art domain", "system": "ingestion", "registry": "23",
     "module": "ufcs_store", "endpoints": ["/api/ingest/strategy"], "page": "/ingest", "status": "built"},
    {"id": "ingest.strategy", "title": "Staged, automated ingestion ladder", "system": "ingestion",
     "registry": "Two-System Arch.", "module": "qb_ingest_strategy",
     "endpoints": ["/api/ingest/strategy"], "page": "/ingest", "status": "built"},
    # ---- Query ----
    {"id": "query.chat", "title": "Cited chat (grounded or UNKNOWN)", "system": "query",
     "registry": "[156]-[165]", "module": "qb_chat", "endpoints": ["/api/chat", "/api/verify"],
     "page": "/chat", "status": "built"},
    {"id": "query.fql", "title": "FQL query + Fact-Unit lookup", "system": "query", "registry": "[062]",
     "module": "ufcs_store", "endpoints": ["/api/fql", "/api/get"], "page": "/chat", "status": "built"},
    {"id": "query.intel", "title": "Query understanding (entities/predicate/intent/expansion)",
     "system": "query", "registry": "[059]-[067]", "module": "qb_query",
     "endpoints": ["/api/query/understand"], "page": None, "status": "built"},
    {"id": "query.language", "title": "Language: translate, detect, pronounce, speak", "system": "query",
     "registry": "[193]-[197]", "module": "qb_language",
     "endpoints": ["/api/language/translate", "/api/language/speak", "/api/language/detect"],
     "page": "/language", "status": "built"},
    {"id": "query.director", "title": "Scene Director (QueryBook→Gemini adapter)", "system": "query",
     "registry": "Scene Director", "module": "qb_gemini",
     "endpoints": ["/api/director/render", "/api/director/prompts"], "page": "/director", "status": "built"},
    {"id": "query.scene", "title": "Scene Reconstructor (prose→director-controlled clip)", "system": "query",
     "registry": "[220]-[226]", "module": "qb_scene",
     "endpoints": ["/api/scene/render", "/api/scene/styles"], "page": "/reconstructor", "status": "built"},
    {"id": "query.voice", "title": "Voice Lab (two-way voice, tone, matching)", "system": "query",
     "registry": "LIL/PIL", "module": "qb_lil,qb_pil", "endpoints": ["/api/pil/analyze"],
     "page": "/voice", "status": "built"},
    # ---- Language tech ----
    {"id": "lang.dialects", "title": "Dialect Parameter Clusters (6 dialects)", "system": "language",
     "registry": "Dialect Support", "module": "qb_dialect",
     "endpoints": ["/api/language/dialects", "/api/language/dialect_detect"], "page": "/language", "status": "built"},
    {"id": "lang.speech_cloud", "title": "Cloud neural voices (Google/ElevenLabs) + cloning", "system": "language",
     "registry": "[195]-[196]", "module": "qb_language",
     "endpoints": ["/api/language/voices", "/api/language/custom_voice", "/api/language/tts_providers"],
     "page": "/language", "status": "built"},
    # ---- Identity & interpretation ----
    {"id": "identity.lil", "title": "LIL voiceprint (enroll/match/authenticate, consent-gated)",
     "system": "identity", "registry": "[199]-[203]", "module": "qb_lil",
     "endpoints": ["/api/lil/enroll", "/api/lil/match", "/api/lil/authenticate"], "page": "/voice", "status": "built"},
    {"id": "identity.pil", "title": "PIL paralinguistics + pragmatic interpretation", "system": "identity",
     "registry": "[210]-[214]", "module": "qb_pil",
     "endpoints": ["/api/pil/analyze", "/api/pil/interpret"], "page": "/voice", "status": "built"},
    # ---- Knowledge ----
    {"id": "knowledge.ontology", "title": "Ontology / concept graph", "system": "knowledge",
     "registry": "[068]-[080]", "module": "qb_ontology", "endpoints": ["/api/ontology"], "page": None, "status": "built"},
    {"id": "knowledge.assess", "title": "Assessment + study-guide generator", "system": "knowledge",
     "registry": "[081]-[096]", "module": "qb_assess", "endpoints": ["/api/assess"], "page": None, "status": "built"},
    # ---- Integrity & rights ----
    {"id": "integrity.rights", "title": "Licensing & rights gate", "system": "integrity",
     "registry": "[097]-[108]", "module": "qb_rights",
     "endpoints": ["/api/rights/grant", "/api/rights/check"], "page": None, "status": "built"},
    {"id": "integrity.ledger", "title": "Provenance ledger + UIAS (seal/similarity/proof)", "system": "integrity",
     "registry": "[109]-[118],[204]-[209]", "module": "qb_integrity",
     "endpoints": ["/api/integrity/seal", "/api/integrity/similarity", "/api/integrity/proof"],
     "page": None, "status": "built"},
    {"id": "integrity.firewall", "title": "Middleware provenance firewall", "system": "integrity",
     "registry": "AI embodiment", "module": "qb_middleware",
     "endpoints": ["/api/middleware/verify", "/api/middleware/guard"], "page": None, "status": "built"},
    {"id": "integrity.webhooks", "title": "Webhook registry (deployment)", "system": "integrity",
     "registry": "[177]", "module": "qb_api", "endpoints": ["/api/webhooks"], "page": None, "status": "built"},
    # ---- Reasoning ----
    {"id": "reasoning.agents", "title": "Reasoning / hypothesis / simulation / planner agents",
     "system": "reasoning", "registry": "[186]-[189]", "module": "qb_agents",
     "endpoints": ["/api/agents", "/api/hypotheses", "/api/plans"], "page": "/dashboard", "status": "built"},
    # ---- Platform ----
    {"id": "platform.editions", "title": "Editions (light/medium/full)", "system": "platform",
     "registry": "Two-System Arch.", "module": "qb_editions", "endpoints": ["/api/edition"], "page": "/", "status": "built"},
    {"id": "platform.embodiments", "title": "Embodiments (chatbot/engine/CLI/library/MCP/middleware/SDK)",
     "system": "platform", "registry": "Two-System Arch.", "module": "qb_embodiment,qb_mcp,qb-client.js",
     "endpoints": ["/api/embodiments"], "page": "/", "status": "built"},
    {"id": "platform.two_system", "title": "Two-system home (Ingestion | Query)", "system": "platform",
     "registry": "Two-System Arch.", "module": "qb_api", "endpoints": ["/api/system"], "page": "/", "status": "built"},
]


def _module_ok(spec):
    for m in (spec.get("module") or "").split(","):
        m = m.strip()
        if not m or m.endswith(".js"):
            continue
        try:
            __import__(m)
        except Exception:
            return False, m
    return True, None

def _page_ok(spec):
    page = spec.get("page")
    if not page:
        return True
    fname = {"/": "home.html", "/chat": "chat.html", "/ingest": "ingest.html",
             "/language": "language.html", "/voice": "voice.html", "/director": "director.html",
             "/reconstructor": "reconstructor.html", "/dashboard": "dashboard.html"}.get(page)
    return bool(fname) and _os.path.exists(_os.path.join(_HERE, fname))

def catalog():
    """The full manifest with a live check per feature (module importable? page present?)."""
    rows = []
    for f in FEATURES:
        ok_mod, bad = _module_ok(f)
        rows.append({**f, "module_ok": ok_mod, "module_missing": bad, "page_ok": _page_ok(f),
                     "live": ok_mod and _page_ok(f)})
    systems = {}
    for r in rows:
        systems.setdefault(r["system"], []).append(r["id"])
    built = sum(1 for r in rows if r["status"] == "built")
    live = sum(1 for r in rows if r["live"])
    return {"count": len(rows), "built": built, "live": live, "systems": systems, "features": rows,
            "note": "Feature manifest synchronized to the Registry/Bible; live-checked against the running prototype."}

def qc():
    c = catalog()
    checks = [{"check": "all modules importable", "pass": all(r["module_ok"] for r in c["features"])},
              {"check": "all pages present", "pass": all(r["page_ok"] for r in c["features"])},
              {"check": "all features live", "pass": c["live"] == c["count"]},
              {"check": ">=28 features cataloged", "pass": c["count"] >= 28}]
    passed = sum(1 for x in checks if x["pass"])
    return {"passed": passed, "total": len(checks), "ok": passed == len(checks),
            "count": c["count"], "live": c["live"], "rows": checks,
            "offenders": [r["id"] for r in c["features"] if not r["live"]]}

if __name__ == "__main__":
    import json; print(json.dumps(qc(), indent=2))
