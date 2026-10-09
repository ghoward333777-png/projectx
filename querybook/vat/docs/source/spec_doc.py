import json, sys, re
sys.path.insert(0, sys.argv[1]); from md2blocks import convert
md = open(sys.argv[2]).read().replace("**`opinion`, `plan`, `prediction`**", "`opinion`, `plan` and `prediction` claims")
# repo-relative references stay; the "Status/Audience/Builds on" preface becomes a key-value table
B = convert(md)
for b in B:
    if b["t"] == "code" and any("Agent A" in l for l in b["lines"]):
        b["lines"] = ["Agent A --MCP/A2A/HTTP--> [VAT Sidecar A]",
                      "                              ||  VAT frames over QUIC (or TLS/TCP)",
                      "                              \\=====================> [VAT Sidecar B] --> Agent B / tool",
                      "   Sidecar A: verify, bind, sign, log, certify      Sidecar B: verify, log",
                      "   Both sidecars --> UFCS Verification Service",
                      "   Shared: Ledger + Certificates; Control Plane (policy)",
                      "   (see drawings, FIG. 1)"]
assert B[0]["t"] == "title"
B[0]["text"] = "Verified Agent Transport (VAT)"
B.insert(1, {"t": "center", "text": "Technical Specification — v1.0 — October 9, 2026", "bold": True, "after": 60})
B.insert(2, {"t": "center", "text": "AI Agent Wrapper Service on the QueryBook + TCP/IP Hybrid Transport (UFCS-FQL/1)", "italic": True, "after": 240})
json.dump({"title": "Verified Agent Transport — Technical Specification", "font": "Calibri", "size": 11, "line": 264,
           "header": "Verified Agent Transport — Technical Specification v1.0", "blocks": B},
          open(sys.argv[3], "w"), ensure_ascii=False)
