"""QueryBook editions — light / medium / full  [deterministic feature gating]

QueryBook is modularized into three editions, split BY SUBSYSTEM. An edition is a named set
of feature flags; the API and UI consult it to show/hide and enable/disable subsystems. The
edition is chosen with the QB_EDITION environment variable (default: 'full'). This is a
packaging/registry concern only — it never changes engine semantics or the covenant.

Feature keys are subsystem-level (dotted): the two top-level SYSTEMS are 'query.*' and
'ingest.*', plus cross-cutting capability flags (agents.*, speech.*, dialects, lil, pil,
uias, director, saas).
"""

import os as _os

# Canonical feature catalog (key -> human label), grouped by the two systems + capabilities.
FEATURES = {
    # ---- QUERY system ----
    "query.chat":          "Query · Cited chat (grounded answers / UNKNOWN)",
    "query.language":      "Query · Language (translate, detect, pronounce, speak)",
    "query.voice":         "Query · Voice Lab (two-way voice, tone, matching)",
    "query.director":      "Query · Scene Director (Gemini Omni adapter)",
    "query.scene":         "Query · Scene Reconstructor (prose → video clip)",
    "query.intel":         "Query · Query understanding (entities/intent/expansion)",
    # ---- INGESTION system (staged domains) ----
    "ingest.language":     "Ingest · Language (structural → semantic → multilingual → speech)",
    "ingest.deterministic":"Ingest · Deterministic domains (mathematics, geometry, arithmetic)",
    "ingest.history":      "Ingest · History (timelines, events)",
    "ingest.news":         "Ingest · News (current events, attributed)",
    "ingest.culture":      "Ingest · Culture (customs, society)",
    "ingest.art":          "Ingest · Art (works, movements)",
    "ingest.web":          "Ingest · Web harvester",
    "ingest.qa":           "Ingest · Q&A / direct Fact-Unit injection",
    # ---- Cross-cutting capabilities ----
    "agents.reasoning":    "Agents · Gated reasoning (deductive closure)",
    "agents.creativity":   "Agents · Hypothesis + simulation (store-verified)",
    "agents.planner":      "Agents · NLPL planner",
    "speech.cloud":        "Speech · Cloud neural voices (Google / ElevenLabs)",
    "dialects":            "Language · Dialect Parameter Clusters",
    "lil":                 "Identity · LIL voiceprint (consent-gated)",
    "pil":                 "Interpretation · PIL paralinguistics",
    "knowledge.ontology":  "Knowledge · Ontology / concept graph",
    "knowledge.assess":    "Knowledge · Assessment + study-guide generator",
    "integrity.rights":    "Integrity · Licensing & rights gate",
    "integrity.ledger":    "Integrity · Provenance ledger + proof",
    "uias":                "Integrity · UIAS audit service",
    "saas":                "Platform · Multi-tenant / rights / analytics (enterprise)",
}

# Edition membership — split BY SUBSYSTEM (per product decision).
#   light  = the Query system + Language ingestion (the smallest useful knowledge engine)
#   medium = + deterministic/history/news ingestion, web, agents, speech, voice
#   full   = everything (dialects, LIL, PIL, UIAS, Director, culture/art, SaaS)
_LIGHT = {
    "query.chat", "query.language", "ingest.language", "ingest.qa",
}
_MEDIUM = _LIGHT | {
    "query.voice", "query.intel", "ingest.deterministic", "ingest.history", "ingest.news", "ingest.web",
    "agents.reasoning", "agents.creativity", "agents.planner", "speech.cloud",
    "knowledge.ontology", "knowledge.assess",
}
_FULL = set(FEATURES.keys())   # everything

EDITIONS = {
    "light":  {"name": "QueryBook Light",  "features": _LIGHT,
               "tagline": "Query + Language ingestion. The smallest useful, fully-offline knowledge engine.",
               "footprint": "Minimal RAM/disk; no cloud required."},
    "medium": {"name": "QueryBook Medium", "features": _MEDIUM,
               "tagline": "Adds deterministic / history / news ingestion, web harvest, agents, speech and voice.",
               "footprint": "Moderate; optional cloud (TTS/LLM)."},
    "full":   {"name": "QueryBook Full",   "features": _FULL,
               "tagline": "Everything: dialects, LIL, PIL, UIAS, Scene Director, culture & art, enterprise.",
               "footprint": "Server-grade; all subsystems."},
}

ORDER = ["light", "medium", "full"]


def current_edition():
    e = (_os.environ.get("QB_EDITION") or "full").strip().lower()
    return e if e in EDITIONS else "full"

def features(edition=None):
    return set(EDITIONS[edition or current_edition()]["features"])

def is_enabled(feature, edition=None):
    return feature in features(edition)

def info(edition=None):
    ed = edition or current_edition()
    out = {"edition": ed, "name": EDITIONS[ed]["name"], "tagline": EDITIONS[ed]["tagline"],
           "footprint": EDITIONS[ed]["footprint"], "order": ORDER,
           "enabled": sorted(features(ed)),
           "features": [{"key": k, "label": FEATURES[k], "enabled": k in features(ed)}
                        for k in FEATURES],
           "editions": []}
    for name in ORDER:
        fset = EDITIONS[name]["features"]
        out["editions"].append({"edition": name, "name": EDITIONS[name]["name"],
                                "tagline": EDITIONS[name]["tagline"],
                                "footprint": EDITIONS[name]["footprint"],
                                "feature_count": len(fset),
                                "features": sorted(fset)})
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(info(), indent=2))
