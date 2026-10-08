"""QueryBook MCP tool server  [stdio JSON-RPC · every call through the Agent Gateway]

Exposes QueryBook as tools an AI agent (OpenClaw, Claude, any MCP client) can call, so a
calling model gets GROUND TRUTH — and so the agent itself cannot be turned against QueryBook:

  qb_query(text)          cited answer or UNKNOWN (the covenant gate)
  qb_verify(claim)        VERIFIED / CONTRADICTED / UNKNOWN (the provenance firewall)
  qb_understand(text)     deterministic query plan
  qb_ingest(path|text)    Open Claw ingestion (files must be in the inbox folder)
  qb_preview(path|text)   dry-run Open Claw ingestion (nothing stored)
  qb_ledger_verify()      prove the provenance ledger is intact
  qb_nft_status()         on-chain NFT network/wallet status
  qb_nft_verify(token_id) verify a QueryBook certificate NFT on-chain
  qb_security_status()    shield status

SECURITY. Each tools/call becomes a qb_shield.execute() request with this server's agent id
(QB_MCP_AGENT, default qb.openclaw), caller id (QB_CALLER_ID, default openclaw) and caller token
(QB_CALLER_TOKEN — print it with `python qb_shield.py token openclaw`). The gateway applies the
agent's allow-list, the caller's role, the AI-aware firewall, anomaly detection, honeycode /
tripwire / honeytoken deception and isolation, and logs every decision immutably. A hijacked agent
that calls a privileged-looking tool name gets synthetic decoy data and is isolated.

Setup for OpenClaw:  python qb_mcp.py --openclaw-config
"""

import json as _json
import os as _os
import sys as _sys
import time as _time
import uuid as _uuid

PROTOCOL = "2024-11-05"
SUPPORTED = ("2024-11-05", "2025-03-26", "2025-06-18")

_PATH_OR_TEXT = {"type": "object", "properties": {
    "path": {"type": "string", "description": "file inside the QueryBook inbox folder"},
    "text": {"type": "string", "description": "or the content itself"},
    "filename": {"type": "string"}}}

TOOLS = [
    {"name": "qb_query", "description": "Ask QueryBook; returns a cited answer or UNKNOWN (never a guess).",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "qb_verify", "description": "Check a claim against the Fact-Unit store: VERIFIED / CONTRADICTED / UNKNOWN.",
     "inputSchema": {"type": "object", "properties": {"claim": {"type": "string"}}, "required": ["claim"]}},
    {"name": "qb_understand", "description": "Return a deterministic query plan (entities/predicate/intent).",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "qb_ingest", "description": "Open Claw: ingest any file (PDF, Office, HTML, JSON, CSV, e-mail, images, "
                                         "audio, video, archives ...) into cited Fact Units, sealed with provenance. "
                                         "Content is treated as untrusted data.", "inputSchema": _PATH_OR_TEXT},
    {"name": "qb_preview", "description": "Open Claw dry run: what would be extracted, nothing stored.",
     "inputSchema": _PATH_OR_TEXT},
    {"name": "qb_ledger_verify", "description": "Prove QueryBook's provenance ledger has not been altered.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "qb_nft_status", "description": "Blockchain network, wallet and contract used for QueryBook certificate NFTs.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "qb_nft_verify", "description": "Verify a QueryBook certificate NFT on-chain (owner, content hash, revoked).",
     "inputSchema": {"type": "object", "properties": {"token_id": {"type": "integer"}, "content": {"type": "string"}},
                     "required": ["token_id"]}},
    {"name": "qb_security_status", "description": "QueryBook shield status (isolations, recent security events).",
     "inputSchema": {"type": "object", "properties": {}}},
]

TOOL_COMMANDS = {"qb_query": "ufcs.query", "qb_verify": "ufcs.verify", "qb_understand": "ufcs.understand",
                 "qb_ingest": "openclaw.ingest", "qb_preview": "openclaw.preview",
                 "qb_ledger_verify": "integrity.verify", "qb_nft_status": "nft.status",
                 "qb_nft_verify": "nft.verify", "qb_security_status": "security.status"}

_SESSION = "mcp-" + _uuid.uuid4().hex[:12]


def _store_dir():
    return _os.environ.get("QB_DATA_DIR") or _os.path.join(_os.path.expanduser("~"), ".querybook", "store")


def _identity():
    return (_os.environ.get("QB_MCP_AGENT", "qb.openclaw"), _os.environ.get("QB_CALLER_ID", "openclaw"),
            _os.environ.get("QB_CALLER_TOKEN", ""))


def _call_tool(name, args, store_dir=None, session=None):
    import qb_shield
    agent, caller, token = _identity()
    # Unknown tool names go to the gateway as-is: honeycode/tripwire names trigger deception,
    # anything else is denied and counted by anomaly detection (enumeration).
    command = TOOL_COMMANDS.get(name, name)
    res = qb_shield.execute({"agent_id": agent, "caller_id": caller, "caller_token": token,
                             "session_id": session or _SESSION, "ufcs_command": command,
                             "payload": args or {}, "timestamp": _time.time()},
                            client=None, user_agent="mcp-stdio", store_dir=store_dir or _store_dir())
    return res


def handle(request, store_dir=None, session=None):
    """Handle one JSON-RPC request dict; return the response dict (or None for notifications)."""
    rid = request.get("id")
    method = request.get("method")

    def ok(result):
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def err(code, msg):
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}
    if method == "initialize":
        asked = ((request.get("params") or {}).get("protocolVersion")) or PROTOCOL
        return ok({"protocolVersion": asked if asked in SUPPORTED else PROTOCOL, "capabilities": {"tools": {}},
                   "serverInfo": {"name": "querybook", "version": "9.64"}})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        p = request.get("params", {}) or {}
        res = _call_tool(p.get("name"), p.get("arguments"), store_dir, session)
        denied = isinstance(res.get("result"), dict) and str(res["result"].get("error", "")).startswith("denied")
        return ok({"content": [{"type": "text", "text": _json.dumps(res, ensure_ascii=False, default=str)}],
                   "isError": bool(denied)})
    if method == "ping":
        return ok({})
    if method and method.startswith("notifications/"):
        return None
    return err(-32601, "method not found: %s" % method)


def serve_stdio(store_dir=None):
    for line in _sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = _json.loads(line)
        except ValueError:
            continue
        resp = handle(req, store_dir)
        if resp is not None:
            _sys.stdout.write(_json.dumps(resp) + "\n")
            _sys.stdout.flush()


def openclaw_config():
    """The exact settings to connect OpenClaw to this QueryBook (MCP server + skill)."""
    import qb_shield
    here = _os.path.dirname(_os.path.abspath(__file__))
    return {
        "mcp_server": {"querybook": {"command": _sys.executable, "args": [_os.path.join(here, "qb_mcp.py")],
                                     "cwd": here, "env": {"QB_CALLER_ID": "openclaw",
                                                          "QB_CALLER_TOKEN": qb_shield.caller_token("openclaw"),
                                                          "QB_MCP_AGENT": "qb.openclaw"}}},
        "where": "add under mcp.servers in your OpenClaw config (openclaw.json), then run: "
                 "openclaw mcp probe querybook",
        "skill": "openclaw skills install %s --global" % _os.path.join(here, "openclaw", "querybook"),
        "inbox": __import__("qb_openclaw").inbox(),
        "note": "Keep QB_CALLER_TOKEN private: it is what lets OpenClaw act as the 'agent' role.",
    }


def qc():
    import shutil
    import tempfile
    import qb_seclog
    import qb_shield
    d = tempfile.mkdtemp()
    saved = {k: _os.environ.get(k) for k in ("QB_SHIELD_DIR", "QB_SECLOG_DIR", "QB_CALLER_TOKEN", "QB_CALLER_ID",
                                             "QB_MCP_AGENT")}
    _os.environ.update(QB_SHIELD_DIR=_os.path.join(d, "sh"), QB_SECLOG_DIR=_os.path.join(d, "log"))
    qb_seclog._state["loaded_for"] = None
    qb_shield._state.update(loaded_for=None, isolated=None, windows={}, buckets={})
    qb_shield._HONEY_CACHE["seed"] = None
    _os.environ["QB_CALLER_ID"] = "openclaw"
    _os.environ["QB_CALLER_TOKEN"] = qb_shield.caller_token("openclaw")
    _os.environ["QB_MCP_AGENT"] = "qb.openclaw"
    checks = []
    try:
        init = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        checks.append(("initialize (negotiates version)", init["result"]["protocolVersion"] == "2025-06-18"))
        lst = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        checks.append(("tools listed", len(lst["result"]["tools"]) == len(TOOLS)))
        call = handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "qb_understand", "arguments": {"text": "Who wrote Hamlet?"}}},
                      store_dir=d, session="qc-ok")
        body = _json.loads(call["result"]["content"][0]["text"])
        checks.append(("tools/call goes through the gateway", "security_flags" in body and not call["result"]["isError"]))
        good = _os.environ["QB_CALLER_TOKEN"]
        _os.environ["QB_CALLER_TOKEN"] = "wrong"
        bad = handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                      "params": {"name": "qb_ingest", "arguments": {"text": "x"}}}, store_dir=d, session="qc-bad")
        checks.append(("wrong caller token cannot ingest", bad["result"]["isError"]))
        _os.environ["QB_CALLER_TOKEN"] = good
        hc = handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                     "params": {"name": "ufcs.super_admin.export_all", "arguments": {}}}, store_dir=d, session="qc-hc")
        hb = _json.loads(hc["result"]["content"][0]["text"])
        checks.append(("hidden honeycode tool → decoy + isolation", "honeycode" in hb["security_flags"] and
                       qb_shield.is_isolated("session:qc-hc") is not None))
        checks.append(("honeycode is never advertised", all(t["name"] not in qb_shield.HONEYCODE for t in TOOLS)))
        checks.append(("unknown method errors", "error" in handle({"jsonrpc": "2.0", "id": 6, "method": "nope"})))
    finally:
        for k, v in saved.items():
            if v is None:
                _os.environ.pop(k, None)
            else:
                _os.environ[k] = v
        qb_seclog._state["loaded_for"] = None
        qb_shield._state.update(loaded_for=None, isolated=None, windows={}, buckets={})
        qb_shield._HONEY_CACHE["seed"] = None
        for root, _, files in _os.walk(d):
            for n in files:
                try:
                    _os.chmod(_os.path.join(root, n), 0o600)
                except OSError:
                    pass
        shutil.rmtree(d, ignore_errors=True)
    passed = sum(1 for _, c in checks if c)
    return {"passed": passed, "total": len(checks), "ok": passed == len(checks),
            "rows": [{"check": n, "pass": c} for n, c in checks]}


if __name__ == "__main__":
    if "--qc" in _sys.argv:
        print(_json.dumps(qc(), indent=2))
    elif "--openclaw-config" in _sys.argv:
        print(_json.dumps(openclaw_config(), indent=2))
    else:
        serve_stdio()
