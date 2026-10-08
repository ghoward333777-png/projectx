"""QueryBook embodiments — one engine, many surfaces  [deterministic manifest]

QueryBook's core (Fact-Unit store + FQL + covenant gate + language/speech engine) is a
library. An *embodiment* wraps that same core in a surface for a particular infrastructure.
This manifest declares the embodiments QueryBook targets and how each maps the core onto
either CONVENTIONAL infrastructure (plain servers, CLIs, apps) or AI-BASED infrastructure
(LLM apps, agent frameworks, tool/function calling, MCP).

The manifest is descriptive + partly live: 'status' marks what the prototype already ships
versus roadmap. It never changes engine semantics; every embodiment speaks to the same core
and inherits the covenant (no LLM asserts facts; refuse rather than invent).
"""

EMBODIMENTS = [
    {"id": "chatbot", "name": "Chatbot", "surface": "Conversational UI",
     "infra": "both",
     "how": "The cited-chat Query pipeline (plan → retrieve → gate → compose → check) behind a "
            "chat window; answers carry provenance or an honest UNKNOWN.",
     "entrypoints": ["GET /  (chat page)", "POST /api/chat"],
     "status": "built"},
    {"id": "engine_api", "name": "AI Engine (HTTP API)", "surface": "REST/JSON service",
     "infra": "conventional",
     "how": "The whole engine exposed as a local HTTP service (ingestion, query, language, "
            "director, editions). Any app or back end calls it.",
     "entrypoints": ["qb_api.py (ThreadingHTTPServer)", "/api/* (~55 routes)"],
     "status": "built"},
    {"id": "cli", "name": "Command-line / batch", "surface": "CLI + stdio",
     "infra": "conventional",
     "how": "ufcs_store CLI verbs (harvest/ingest/stats/get/verify/export/query) and the "
            "manuscript/develop CLIs — scriptable, headless, cron-friendly.",
     "entrypoints": ["python ufcs_store.py <cmd>", "bin/*.py"],
     "status": "built"},
    {"id": "library", "name": "Embeddable library", "surface": "Python import",
     "infra": "conventional",
     "how": "Import qb_language / ufcs_store / qb_gemini / qb_dialect directly; no server. "
            "Dependency-free, stdlib-only, so it drops into any Python host.",
     "entrypoints": ["import ufcs_store, qb_language, qb_gemini"],
     "status": "built"},
    {"id": "mcp_tool", "name": "AI tool / MCP server", "surface": "Tool / function calling",
     "infra": "ai",
     "how": "Expose query + verify + ingest as tools an LLM agent can call. The covenant makes "
            "QueryBook a trustworthy ground-truth tool: it returns cited facts or UNKNOWN, so "
            "a calling model cannot launder a guess through it.",
     "entrypoints": ["qb_mcp.py (stdio JSON-RPC: initialize/tools/list/tools/call)"],
     "status": "built"},
    {"id": "middleware", "name": "Middleware / sidecar", "surface": "In-line verification layer",
     "infra": "ai",
     "how": "Sits between an application and an LLM: every model claim is checked against the "
            "store (VERIFIED / CONTRADICTED / UNKNOWN) before it reaches the user — a "
            "provenance firewall for AI pipelines.",
     "entrypoints": ["qb_middleware.py", "/api/middleware/verify", "/api/middleware/guard"],
     "status": "built"},
    {"id": "sdk", "name": "Client SDKs", "surface": "Language bindings",
     "infra": "both",
     "how": "Thin clients (JS/Python/…) over the HTTP API for conventional apps and AI back "
            "ends alike.",
     "entrypoints": ["qb-client.js (fetch SDK over /api/*)"],
     "status": "built"},
]


def list_embodiments():
    return [dict(e) for e in EMBODIMENTS]

def matrix():
    """Group embodiments by target infrastructure (conventional vs AI-based)."""
    conv = [e for e in EMBODIMENTS if e["infra"] in ("conventional", "both")]
    ai = [e for e in EMBODIMENTS if e["infra"] in ("ai", "both")]
    return {"conventional": conv, "ai": ai,
            "built": [e["id"] for e in EMBODIMENTS if e["status"] == "built"],
            "roadmap": [e["id"] for e in EMBODIMENTS if e["status"] == "roadmap"]}

def info():
    return {"embodiments": list_embodiments(), "matrix": matrix(),
            "principle": "One deterministic core; many surfaces. Every embodiment inherits the "
                         "QueryBook covenant (no LLM asserts facts; cited answer or UNKNOWN)."}


if __name__ == "__main__":
    import json
    print(json.dumps(info(), indent=2))
