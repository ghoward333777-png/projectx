"""QueryBook MCP tool server  [minimal, stdio JSON-RPC]

Exposes QueryBook as tools an AI agent can call, so a calling model gets GROUND TRUTH:
  - qb_query(text)      → cited answer or UNKNOWN (the covenant gate)
  - qb_verify(claim)    → VERIFIED / CONTRADICTED / UNKNOWN (the provenance firewall)
  - qb_understand(text) → a deterministic query plan

It speaks a minimal subset of MCP over stdio: `initialize`, `tools/list`, `tools/call`.
`handle(request)` is pure (unit-testable); `serve_stdio()` runs the loop. No external deps.
"""

import json as _json
import sys as _sys

PROTOCOL = "2024-11-05"

TOOLS = [
    {"name": "qb_query", "description": "Ask QueryBook; returns a cited answer or UNKNOWN (never a guess).",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "qb_verify", "description": "Check a claim against the Fact-Unit store: VERIFIED / CONTRADICTED / UNKNOWN.",
     "inputSchema": {"type": "object", "properties": {"claim": {"type": "string"}}, "required": ["claim"]}},
    {"name": "qb_understand", "description": "Return a deterministic query plan (entities/predicate/intent).",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
]


def _call_tool(name, args, store_dir="./mystore"):
    args = args or {}
    if name == "qb_understand":
        import qb_query
        return qb_query.understand(args.get("text", ""))
    if name == "qb_verify":
        import qb_middleware
        return qb_middleware.verify_claim(args.get("claim", ""), store_dir=store_dir)
    if name == "qb_query":
        # Prefer the grounded chat pipeline; fall back to verify if chat is unavailable.
        try:
            import qb_chat
            return qb_chat.answer(args.get("text", ""), store_dir)
        except Exception:
            import qb_middleware
            return qb_middleware.verify_claim(args.get("text", ""), store_dir=store_dir)
    return {"error": "unknown tool: %s" % name}


def handle(request, store_dir="./mystore"):
    """Handle one JSON-RPC request dict; return the response dict (or None for notifications)."""
    rid = request.get("id")
    method = request.get("method")
    def ok(result): return {"jsonrpc": "2.0", "id": rid, "result": result}
    def err(code, msg): return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}
    if method == "initialize":
        return ok({"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                   "serverInfo": {"name": "querybook", "version": "1.0"}})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        p = request.get("params", {}) or {}
        res = _call_tool(p.get("name"), p.get("arguments"), store_dir)
        return ok({"content": [{"type": "text", "text": _json.dumps(res, ensure_ascii=False)}]})
    if method in ("notifications/initialized",):
        return None
    return err(-32601, "method not found: %s" % method)


def serve_stdio(store_dir="./mystore"):
    for line in _sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = _json.loads(line)
        except Exception:
            continue
        resp = handle(req, store_dir)
        if resp is not None:
            _sys.stdout.write(_json.dumps(resp) + "\n"); _sys.stdout.flush()


def qc():
    checks = []
    init = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    checks.append(("initialize", init["result"]["protocolVersion"] == PROTOCOL))
    lst = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    checks.append(("tools listed", len(lst["result"]["tools"]) == 3))
    call = handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                   "params": {"name": "qb_understand", "arguments": {"text": "Who wrote Hamlet?"}}})
    checks.append(("tools/call understand", "content" in call["result"]))
    bad = handle({"jsonrpc": "2.0", "id": 4, "method": "nope"})
    checks.append(("unknown method errors", "error" in bad))
    passed = sum(1 for _, c in checks if c)
    return {"passed": passed, "total": len(checks), "ok": passed == len(checks),
            "rows": [{"check": n, "pass": c} for n, c in checks]}


if __name__ == "__main__":
    if "--qc" in _sys.argv:
        print(_json.dumps(qc(), indent=2))
    else:
        serve_stdio()
