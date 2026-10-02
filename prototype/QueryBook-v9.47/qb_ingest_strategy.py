"""QueryBook ingestion strategy — staged, automated, domain-by-domain

The Ingestion system grows the knowledge base along a deliberate STAGE LADDER rather than
ad hoc. The order is a product decision: build competence first on LANGUAGE, then on the
DETERMINISTIC domains, then layer HISTORY, NEWS, CULTURE and ART.

Each stage declares the agents/sources that feed it and a covenant note. This module reports
live progress per stage (from the Fact-Unit store manifest + language readiness), identifies
the ACTIVE stage (the first incomplete, enabled stage), and recommends the exact automated
action to advance it. It is deterministic and edition-aware; it starts nothing by itself —
it hands the UI/API a concrete plan to run.
"""

import os as _os

try:
    import qb_editions
except Exception:
    qb_editions = None

# Ordered stage ladder. 'feature' ties a stage to the edition gate; 'domains' are store
# domains whose fact counts measure progress; 'agents' are the agent kinds that feed it.
STAGES = [
    {"id": "language", "name": "Language", "feature": "ingest.language", "status": "built",
     "order": 1,
     "agents": ["language", "lang_semantic", "lang_multilingual", "lang_speech", "lang_pipeline"],
     "domains": ["language"],
     "source": "Bundled public-domain corpora + dictionaries (no internet, no LLM).",
     "goal": "English Phases 1–4 complete, then each additional language to completion.",
     "covenant": "Fully deterministic; grounded to auditable dictionary/store facts.",
     "measure": "language_readiness"},
    {"id": "deterministic", "name": "Deterministic domains", "feature": "ingest.deterministic",
     "status": "built", "order": 2,
     "agents": ["deterministic"], "domains": ["mathematics", "geometry", "arithmetic"],
     "source": "Rule-based generators (mathematics, geometry, arithmetic).",
     "goal": "Grow verified, reproducible fact domains continuously.",
     "covenant": "Each fact is rule-derived and content-hashed; deterministic.",
     "measure": "domain_facts"},
    {"id": "history", "name": "History", "feature": "ingest.history", "status": "planned",
     "order": 3, "agents": ["web", "deterministic"], "domains": ["history"],
     "source": "Public-domain timelines & reference works; curated event tables.",
     "goal": "Dated, sourced event Fact Units (who/what/when/where), attributed.",
     "covenant": "Events stored as sourced facts; 'recorded by X' ≠ asserted truth.",
     "measure": "domain_facts"},
    {"id": "news", "name": "News", "feature": "ingest.news", "status": "planned",
     "order": 4, "agents": ["web"], "domains": ["news"],
     "source": "Polite web harvest of current-events feeds.",
     "goal": "Current-event Fact Units, each attributed to its outlet and timestamp.",
     "covenant": "Attributed utterances (said ≠ true); provenance + time on every unit.",
     "measure": "domain_facts"},
    {"id": "culture", "name": "Culture", "feature": "ingest.culture", "status": "planned",
     "order": 5, "agents": ["web", "deterministic"], "domains": ["culture"],
     "source": "Reference works on customs, society, traditions.",
     "goal": "Cultural knowledge as sourced Fact Units, with sociolect/safety metadata.",
     "covenant": "Descriptive, sourced; avoids caricature (shares the dialect safety stance).",
     "measure": "domain_facts"},
    {"id": "art", "name": "Art", "feature": "ingest.art", "status": "planned",
     "order": 6, "agents": ["web", "deterministic"], "domains": ["art"],
     "source": "Public-domain catalogs of works, artists, movements.",
     "goal": "Works/artists/movements as linked Fact Units.",
     "covenant": "Catalog facts with provenance; interpretation kept separate from fact.",
     "measure": "domain_facts"},
]

# Progress thresholds (facts) that mark a deterministic/web stage 'in progress' vs 'growing'.
_SEED = 1
_HEALTHY = 1000


def _edition_enabled(feature):
    if not qb_editions:
        return True
    try:
        return qb_editions.is_enabled(feature)
    except Exception:
        return True

def _lang_pct(store_dir):
    try:
        import qb_language
        r = qb_language.language_readiness(store_dir)
        # readiness may expose an overall percent or per-phase; be tolerant.
        if isinstance(r, dict):
            for k in ("overall_pct", "percent", "readiness_pct", "pct"):
                if isinstance(r.get(k), (int, float)):
                    return float(r[k])
            phs = r.get("phases") or r.get("phase_pct")
            if isinstance(phs, list) and phs:
                vals = [p.get("pct", p.get("percent", 0)) for p in phs if isinstance(p, dict)]
                if vals:
                    return round(sum(vals) / len(vals), 1)
        return 0.0
    except Exception:
        return 0.0

def _domain_facts(store_dir, domains):
    try:
        import ufcs_store
        counts = ufcs_store.domain_counts(store_dir) or {}
        return int(sum(counts.get(d, 0) for d in domains))
    except Exception:
        return 0

def _stage_progress(stage, store_dir):
    if stage["measure"] == "language_readiness":
        pct = _lang_pct(store_dir)
        return {"metric": "readiness", "value": pct, "unit": "%",
                "state": ("complete" if pct >= 99 else "in_progress" if pct > 0 else "not_started")}
    facts = _domain_facts(store_dir, stage["domains"])
    state = ("growing" if facts >= _HEALTHY else "in_progress" if facts >= _SEED else "not_started")
    return {"metric": "facts", "value": facts, "unit": "facts", "state": state}


def status(store_dir, edition=None):
    """Full strategy status: each stage with edition-gating, built/planned, live progress, and
    the single recommended next automated action. Deterministic."""
    stages = []
    active = None
    for st in STAGES:
        enabled = _edition_enabled(st["feature"])
        prog = _stage_progress(st, store_dir)
        row = {"id": st["id"], "name": st["name"], "order": st["order"], "status": st["status"],
               "enabled_in_edition": enabled, "feature": st["feature"],
               "agents": st["agents"], "domains": st["domains"], "source": st["source"],
               "goal": st["goal"], "covenant": st["covenant"], "progress": prog}
        # The active stage = first BUILT + edition-enabled stage that is not yet complete/growing.
        if (active is None and enabled and st["status"] == "built"
                and prog["state"] in ("not_started", "in_progress")):
            active = st["id"]
        stages.append(row)
    if active is None:
        # all built stages healthy → active becomes the first planned+enabled stage (next to build)
        active = next((s["id"] for s in stages
                       if s["enabled_in_edition"] and s["status"] == "planned"), None)
    rec = None
    act = next((s for s in stages if s["id"] == active), None)
    if act:
        if act["status"] == "built":
            rec = {"stage": act["id"], "action": "run_agents", "agents": act["agents"],
                   "note": "Start these agent(s) to advance the active stage."}
        else:
            rec = {"stage": act["id"], "action": "build",
                   "note": "This stage is on the roadmap; building it is the next engineering step."}
    return {"ladder": [s["id"] for s in STAGES], "active_stage": active,
            "edition": (qb_editions.current_edition() if qb_editions else "full"),
            "stages": stages, "recommended": rec,
            "principle": "Automated, staged ingestion: language first, then deterministic, "
                         "then history, news, culture, art."}


def plan():
    """The static strategy plan (order + intent), independent of any store."""
    return {"ladder": [{"id": s["id"], "name": s["name"], "order": s["order"],
                        "status": s["status"], "goal": s["goal"], "source": s["source"],
                        "agents": s["agents"], "covenant": s["covenant"]} for s in STAGES]}


if __name__ == "__main__":
    import json
    print(json.dumps(status(_os.environ.get("QB_DATA_DIR", "./mystore")), indent=2))
