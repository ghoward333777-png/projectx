# Registry v69: the v68 support features, synchronized with the provisional (FIG. 56, claims 355-357).
# Verified Agent Transport (VAT) is an external service supported by these features; it is not a QueryBook feature.
import v68_data as B
C = "Prov. 2026-10-09"
NUMERAL = [5612, 5614, 5616, 5618, 5618, 5632, 5622, 5624, 5626, 5626, 5628, 5634, 5636, 5638, 5648, 5644, 5646, 5646, 5642]
assert len(NUMERAL) == len(B.NEW)
NEW = [(name, dom, [56] + figs, surface, role, f"{func[:-1]} ({n}).", rule, wexpr, status, module)
       for (name, dom, figs, surface, role, func, rule, wexpr, status, module), n in zip(B.NEW, NUMERAL)]
ALGOS = [(aid, name, feats, [56] + figs, inp, proc, outp, det, mod) for (aid, name, feats, figs, inp, proc, outp, det, mod) in B.ALGOS]
FIG56 = "Support Interfaces for External Agent-Wrapper Services (Verified Agent Transport and Similar Relays)"
# External services that use the support features (listed for reference; not counted as QueryBook features)
EXTERNAL = [
 ("Verified Agent Transport (VAT)", "External agent-wrapper service: a sidecar relay beside an AI agent that verifies the agent's factual claims in transit, binds actions to declared intent, records every frame and verdict, and certifies each session.",
  "Separate provisional application and VAT Feature Registry (querybook/vat/docs)", "Specified — not yet built",
  ["Claim Verification Endpoint", "Contradiction Query Template", "Fingerprint-Only Verification Mode", "External Triple Extraction Interface",
   "Assertion-Type Label (Fact / Opinion / Plan / Prediction)", "Signed Verdict Record and Published Verifier Key", "Frame Message-Type Extension Range",
   "Frame Extension Flag and Reserved-Field Profile", "Python UFCS-FQL/1 Frame Codec", "QUIC Stream Binding for Priority Lanes",
   "Fingerprint Set Reconciliation (Have / Want)", "External Service Append to Security Log", "Session-Range Merkle Root",
   "Third-Party Session Certificate Type", "Principal Evidence Pair (Agent Reputation Store)", "Signed Policy Bundle Export",
   "MCP Pre-Call and Post-Call Hooks", "Tool Result Record Hash", "Wrapper Service Registration"]),
 ("Similar agent-wrapper relays (generic)", "Any external gateway, proxy or sidecar that checks an AI agent's statements or actions and needs certified facts, a tamper-evident record or session certificates.",
  "Not described in detail; supported through the same registered-caller interfaces", "—",
  ["Wrapper Service Registration", "Claim Verification Endpoint", "Contradiction Query Template", "Signed Verdict Record and Published Verifier Key",
   "External Service Append to Security Log", "Session-Range Merkle Root", "Third-Party Session Certificate Type", "MCP Pre-Call and Post-Call Hooks", "Tool Result Record Hash"]),
]
