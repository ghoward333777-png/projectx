import json, sys
d = json.load(open("desc.json")); D = {int(k): v for k, v in d["desc"].items()}
B = [{"t": "title", "text": "QueryBook — Drawings and Description of the Drawings"},
     {"t": "center", "text": "FIG. 1–56 · companion to the Provisional Patent Application (synchronized, with support for agent-wrapper services)", "italic": True, "after": 60},
     {"t": "center", "text": "October 9, 2026", "after": 240},
     {"t": "h1", "text": "Brief Description of the Drawings"},
     {"t": "p", "text": d["intro"]}]
GROUPS = [(1, 18, "Platform"), (19, 22, "Confidence, packet, framing and query"), (23, 30, "Language and speech subsystem"),
          (31, 49, "Further subsystems and embodiments"), (50, 55, "Agent-era extensions"), (56, 56, "Support for agent-wrapper services")]
for a, b, g in GROUPS:
    B.append({"t": "h2", "text": f"{g} (FIG. {a}{'' if a == b else '–' + str(b)})"})
    for n in range(a, b + 1):
        B.append({"t": "p", "text": f"**FIG. {n}** {D[n]}"})
B += [{"t": "pagebreak"}, {"t": "h1", "text": "Detailed Description of FIG. 56"},
 {"t": "p", "text": "FIG. 56 shows the interfaces QueryBook provides to external agent-wrapper services — Verified Agent Transport (VAT) and similar relays that sit between an AI agent and the network and check what the agent says and does. The wrapper service itself is outside the system and is described separately; FIG. 56 shows only what QueryBook offers it."},
 {"t": "p", "text": "The wrapper service (5690) receives the traffic of an AI agent (5695) bound for a destination (5697) and calls the support interfaces (5600) under an identity registered with the Agent Gateway. Verification is read-only and records are append-only: a wrapper service never writes Fact Units."},
 {"t": "h2", "text": "Reference numerals"},
 {"t": "table", "header": ["Numeral", "Element", "Rests on"], "widths": [9, 46, 18], "rows": [
  ["5600", "QueryBook support interfaces", ""],
  ["5610", "Verification interfaces", "FIG. 6, 7, 21, 22"],
  ["5612", "Claim verification endpoint (read-only): candidate Fact Units or fingerprints in; verified, contradicted or unknown out, with citation and trust", "FIG. 22"],
  ["5614", "Contradiction query template: same subject and predicate, conflicting value or opposite polarity, trust at or above the minimum", "FIG. 6, 7"],
  ["5616", "Fingerprint-only verification mode: fingerprints and canonical subject/predicate identifiers only", "FIG. 21"],
  ["5618", "Triple extraction and assertion-type labels (fact, opinion, plan, prediction)", "FIG. 2, 6"],
  ["5620", "Transport interfaces", "FIG. 55"],
  ["5622", "Frame message types 16–31 reserved for registered extensions; unregistered types dropped and recorded", "FIG. 55"],
  ["5624", "Extension flag (0x0040) and reserved header field as 16-bit session number and 16-bit hop count", "FIG. 55"],
  ["5626", "Python frame codec; control, normal and bulk lanes as QUIC streams with TLS-on-TCP fallback", "FIG. 55"],
  ["5628", "Have/want fingerprint reconciliation; Bloom filter above 4,096 fingerprints", "FIG. 21, 55"],
  ["5630", "Record and certificate interfaces", "FIG. 51, 53"],
  ["5632", "Signed verdict records and published verifier key", "FIG. 53"],
  ["5634", "Append by a registered service to the security log", "FIG. 53"],
  ["5636", "Session-range Merkle root and inclusion proofs", "FIG. 53"],
  ["5638", "Third-party session certificate type, sealed as a Fact Unit", "FIG. 51"],
  ["5640", "Governance interfaces", "FIG. 52, 54"],
  ["5642", "Wrapper service registration (read-only verification, append-only record rights)", "FIG. 52"],
  ["5644", "Signed, versioned, pull-only policy bundle export", "FIG. 52"],
  ["5646", "Tool-server pre-call and post-call hooks; hash of each tool result record", "FIG. 54"],
  ["5648", "Principal evidence pair (agent reputation); restriction only on a recorded operator decision", "FIG. 19, 52"],
  ["5650", "Fact Unit store and FQL", "FIG. 2, 6, 21, 22"],
  ["5660", "Security log", "FIG. 53"],
  ["5670", "Certificates", "FIG. 51"],
  ["5680", "Agent Gateway and MCP server", "FIG. 52, 54"],
  ["5685", "Framed hybrid transport", "FIG. 55"],
  ["5690", "External agent-wrapper service (e.g., Verified Agent Transport) — outside the system", ""],
  ["5695", "AI agent", ""],
  ["5697", "Destination (agent, tool or data source)", ""]]},
 {"t": "h2", "text": "Status"},
 {"t": "p", "text": "The support interfaces of FIG. 56 are specified and not yet implemented; no performance figures are asserted for them. They correspond to features 364–382 of the QueryBook Composite Feature Registry v68 and to claims 355–357 of the application."}]
json.dump({"title": "QueryBook — Drawings and Description", "font": "Times New Roman", "size": 12, "line": 300, "justify": True,
           "header": "QueryBook — Drawings and Description of the Drawings (FIG. 1–56)", "blocks": B}, open("desc_doc.json", "w"), ensure_ascii=False)
