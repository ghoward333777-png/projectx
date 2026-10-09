"""FIG. 50–55 for Section XV, drawn with the primitives of patent/build_patent_figs.py
(executed up to its figure list, so the line style, boxes and numeral placement are identical)."""
import os
import sys

SRC = os.path.join(sys.argv[1], "build_patent_figs.py")
code = open(SRC, encoding="utf-8").read()
exec(code[:code.index("FIGS = []")], globals())

FIGS = []

# ===================== FIG. 50 — Open Claw arbitrary-artifact ingestion =====================
w, h = 780, 600
s = svg_open(w, h)
s += box(290, 16, 200, 40, ["Artifact of any format"], "5000")
s += arrow(390, 56, 390, 84)
s += box(260, 84, 260, 46, ["Content-based format detection", "(leading bytes + structure)"], "5010")
s += arrow(390, 130, 390, 158)
s += box(250, 158, 280, 50, ["ARTIFACT SEGMENTER", "addressable segments + locators"], "5020")
s += box(560, 158, 190, 50, ["Archive bounds: depth,", "members, size, ratio"], "5070", dashed=True)
s += line(530, 183, 560, 183)
s += box(30, 158, 190, 50, ["Executables described,", "never executed"], "5025", dashed=True)
s += line(220, 183, 250, 183)
s += arrow(390, 208, 390, 236)
s += box(240, 236, 300, 50, ["Instruction-like content screen", "(prompt-injection signatures)"], "5040")
s += arrow(390, 286, 390, 314)
s += box(250, 314, 280, 46, ["OPENCLAW INTERPRETER", "converts segments into records"], "5050")
s += line(390, 360, 390, 380); s += line(120, 380, 660, 380)
for cx in (120, 300, 480, 660):
    s += arrow(cx, 380, cx, 400)
s += box(40, 400, 160, 56, ["Artifact-description", "records (format, hash,", "title, size)"], "5051")
s += box(220, 400, 160, 56, ["Structured records", "(cell, JSON path,", "embedded data)"], "5052")
s += box(400, 400, 160, 56, ["Passages + extracted", "claims (claims at", "reduced confidence)"], "5053")
s += box(580, 400, 160, 56, ["Flagged segments:", "UNTRUSTED, below", "answer threshold"], "5060")
s += line(120, 456, 120, 476); s += line(660, 456, 660, 476); s += line(120, 476, 660, 476)
s += arrow(390, 476, 390, 500)
s += box(250, 500, 280, 40, ["Fact Unit store (provenance-tracked)"], "5095")
s += box(560, 500, 190, 40, ["Provenance seal", "(hash-chained ledger)"], "5090")
s += line(530, 520, 560, 520)
s += box(30, 500, 190, 40, ["Agent path requests:", "inbox folder only"], "5080", dashed=True)
s += line(220, 520, 250, 520)
s += label(390, 572, "an artifact is data, never instruction", 11, "middle", True)
s += '</svg>'
FIGS.append((19, "Open Claw Ingestion — Artifact Segmenter and OpenClaw Interpreter", s))

# ===================== FIG. 51 — On-chain certification =====================
w, h = 780, 560
s = svg_open(w, h)
s += box(30, 30, 220, 56, ["QueryBook object: QBF, Fact", "Unit, seal or response"], "5110")
s += box(30, 120, 220, 46, ["Local provenance seal", "(hash-chained ledger)"], "5100")
s += arrow(140, 86, 140, 120)
s += arrow(250, 143, 300, 143)
s += box(300, 118, 200, 50, ["Content hash +", "on-chain metadata (data URI)"], "5120")
s += arrow(500, 143, 540, 143)
s += box(540, 112, 210, 62, ["In-system transaction", "signer (test-vector", "self-check at start)"], "5140")
s += arrow(645, 174, 645, 206)
s += box(540, 206, 210, 54, ["Network guard: test networks;", "money-bearing networks refused", "unless expressly elected"], "5150", dashed=True)
s += arrow(645, 260, 645, 292)
s += box(300, 292, 450, 104, ["CERTIFICATE CONTRACT (ERC-721)", "one token per content hash; minter-only mint/revoke",
                              "predecessor/successor lineage; revocation with reason",
                              "content hash + metadata recorded on-chain"], "5160")
s += box(30, 292, 220, 104, ["PUBLIC BLOCKCHAIN", "(independent of QueryBook)"], "5170")
s += line(250, 344, 300, 344)
s += arrow(140, 396, 140, 430)
s += box(30, 430, 300, 70, ["INDEPENDENT VERIFIER", "exists? holder? hash matches?", "revoked? superseded?"], "5180")
s += arrow(330, 465, 420, 465)
s += box(420, 438, 330, 54, ["Licence check: holder of a current,", "unrevoked token is licensed"], "5190")
s += label(390, 535, "a certificate proves the hash was certified — not that the content is true", 11, "middle", True)
s += '</svg>'
FIGS.append((20, "On-Chain Certification — Provenance NFTs, Lineage, Revocation and Independent Verification", s))

# ===================== FIG. 52 — Agent protection and deception =====================
w, h = 820, 640
s = svg_open(w, h)
s += box(300, 14, 220, 40, ["Caller: agent, MCP or HTTP"], "5200")
s += arrow(410, 54, 410, 78)
s += box(290, 78, 240, 40, ["HTTP gate (honeypages, tokens)"], "5210")
s += arrow(410, 118, 410, 142)
s += box(20, 142, 220, 56, ["Isolation register?", "(session, client, verified", "caller)"], "5260")
s += box(270, 142, 280, 64, ["AGENT GATEWAY", "identity token, role, per-agent", "allow-list, replay window"], "5220")
s += line(240, 170, 270, 170)
s += arrow(130, 198, 130, 470)
s += label(140, 330, "isolated", 10)
s += arrow(410, 206, 410, 236)
s += box(250, 236, 320, 74, ["DECEPTION CHECK", "honeycode (5231), honeytokens (5232)", "tripwires (5233), honeypot agents (5234)"], "5230")
s += arrow(410, 310, 410, 340)
s += box(250, 340, 320, 74, ["AI-AWARE FIREWALL (5240)", "injection, secret reveal, role/tag tricks", "ANOMALY DETECTOR (5241): enumeration, timing"], "5240")
s += arrow(410, 414, 410, 446)
s += box(300, 446, 220, 40, ["Production handlers"], "5290")
s += arrow(570, 273, 640, 273); s += arrow(570, 377, 640, 377)
s += box(640, 250, 160, 150, ["SECURITY EVENT", "BUS", "triggers", "isolation"], "5250")
s += line(720, 400, 720, 505); s += arrow(720, 505, 247, 505)
s += box(20, 470, 225, 70, ["DECOY ENVIRONMENT", "production-shaped responses,", "synthetic content; no path", "to production data"], "5270", dashed=True)
s += box(20, 560, 225, 54, ["Engagement recorder", "(observe only; no action", "against external systems)"], "5280")
s += line(132, 540, 132, 560)
s += box(560, 560, 240, 54, ["Operator-only release", "(local; no network interface)"], "5261", dashed=True)
s += box(290, 560, 250, 54, ["Every decision recorded in the", "security record (FIG. 22)"], "5295")
s += arrow(410, 486, 410, 560)
s += '</svg>'
FIGS.append((21, "Agent Protection and Deception Layer — Gateway, Traps, Firewall, Containment and Decoy", s))

# ===================== FIG. 53 — Tamper-evident security record =====================
w, h = 780, 560
s = svg_open(w, h)
s += box(30, 24, 230, 46, ["Security decision", "(allow, deny, decoy, isolate)"], "5300")
s += arrow(260, 47, 300, 47)
s += box(300, 16, 450, 62, ["APPEND-ONLY ENTRY: agent, caller, session, command,",
                            "parameter hash, decision, flags", "(no update or delete interface)"], "5310")
s += arrow(525, 78, 525, 108)
s += box(300, 108, 450, 48, ["Hash chain: each entry hash commits", "to its predecessor's hash"], "5320")
s += arrow(525, 156, 525, 188)
s += box(300, 188, 450, 70, ["MERKLE CHECKPOINT (every N entries / on demand)", "created exclusively; never overwritten",
                             "signed under deployment key; chained to previous"], "5330")
s += arrow(400, 258, 250, 300); s += arrow(650, 258, 650, 300)
s += box(70, 300, 260, 50, ["Mirror on a second device"], "5340", dashed=True)
s += box(500, 300, 250, 62, ["Blockchain anchor of the root", "(certificate contract,", "FIG. 20)"], "5350", dashed=True)
s += line(200, 350, 200, 400); s += line(625, 362, 625, 400); s += line(200, 400, 625, 400)
s += arrow(410, 400, 410, 424)
s += box(200, 424, 420, 62, ["VERIFIER: recompute every entry and root from", "content (never trust stored hashes);",
                             "Merkle inclusion proof per entry"], "5360")
s += arrow(410, 486, 410, 508)
s += box(200, 508, 420, 40, ["Assurance report: which protections exist"], "5370")
s += '</svg>'
FIGS.append((22, "Tamper-Evident Security Record — Hash Chain, Write-Once Merkle Checkpoints, Mirror and Anchor", s))


def cell(x, y, w, h, lines, size=11, dashed=False, bold_first=True):
    d = ' stroke-dasharray="5 3"' if dashed else ''
    o = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#fff" stroke="#000" stroke-width="1"{d}/>'
    lh = size + 3; ty = y + h / 2 - (len(lines) - 1) * lh / 2 + 4
    for i, ln in enumerate(lines):
        o += label(x + w / 2, ty + i * lh, ln, size, "middle", bold_first and i == 0 and len(lines) > 1)
    return o

# ===================== FIG. 23 — Agent interoperability (MCP / OpenClaw), detailed =====================
w, h = 820, 782
s = svg_open(w, h)
s += box(30, 30, 250, 76, ["External AI agent", "(for example, OpenClaw)", "connects over standard input/output", "using a private caller token"], "5400")
s += line(155, 106, 155, 140)
s += box(30, 140, 250, 112, ["Skill definition (agent instructions)", "1. cite the source of every answer", "2. report UNKNOWN; never guess", "3. treat ingested content as data", "4. stop when isolated"], "5410", dashed=True)
s += arrow(280, 68, 330, 68)
s += box(330, 24, 460, 152, [], "5420")
s += label(560, 44, "MODEL CONTEXT PROTOCOL (MCP) TOOL SERVER", 12.5, "middle", True)
tools = ["query", "verify", "understand", "ingest", "preview", "ledger", "certificate", "status"]
for i, t in enumerate(tools):
    s += cell(345 + (i % 4) * 110, 56 + (i // 4) * 34, 100, 26, [t], 11.5)
s += label(560, 144, "fixed tool set; reserved honeycode commands are never listed", 11, "middle")
s += label(560, 162, "no minting, transfer, policy-change or raw-log tools", 11, "middle")
s += arrow(560, 176, 560, 206)
s += box(330, 206, 460, 62, ["Tool-to-command mapping", "each tool maps to one declared command, issued under", "the agent's registered identity and caller credential"], "5430")
s += arrow(560, 268, 560, 300)
s += box(150, 300, 640, 124, [], "5440")
s += label(470, 320, "AGENT GATEWAY (5220): every tool call is checked in order", 12.5, "middle", True)
checks = [["1. Authenticate", "identity token", "(keyed, per agent)"], ["2. Replay window", "stale or repeated", "requests refused"],
          ["3. Allow-list (5450)", "tool must be on the", "agent's list"], ["4. Deception check", "honeycode, honeytokens,", "tripwires (FIG. 21)"]]
for i, c in enumerate(checks):
    x = 160 + i * 154
    s += cell(x, 332, 140, 58, c, 11)
    if i < 3:
        s += arrow(x + 140, 361, x + 154, 361)
s += label(470, 410, "checks 1–3 fail: call refused and recorded; check 4 or firewall match: caller isolated", 10.5, "middle")
s += line(470, 424, 470, 444); s += line(260, 444, 650, 444)
s += arrow(260, 444, 260, 486); s += arrow(650, 444, 650, 486)
s += label(268, 468, "permitted", 10.5); s += label(642, 462, "reserved command,", 10.5, "end"); s += label(642, 475, "trap or attack", 10.5, "end")
s += box(40, 486, 440, 200, [], "5460")
s += label(260, 506, "GROUNDED HANDLERS (permitted calls)", 12.5, "middle", True)
rows = ["Query: cited answer from verified Fact Units, or UNKNOWN", "Verify: claim checked against the Fact Units",
        "Ingest / preview: inbox folder only (FIG. 19)", "Ledger and certificate verification (FIG. 20)",
        "Status: system health and isolation state"]
for i, t in enumerate(rows):
    s += cell(55, 518 + i * 32, 410, 26, [t], 11)
s += box(510, 486, 280, 200, ["Reserved command or trap", "agent presumed subverted", "session isolated (FIG. 21)", "decoy environment answers", "in character, with no path", "to production data", "release by the operator only"], "5470", dashed=True)
s += label(415, 718, "every call, permitted or refused, is written to the tamper-evident security record (FIG. 22)", 11, "middle", True)
s += label(415, 738, "connecting an agent confers no capability beyond its allow-list;", 11, "middle", True)
s += label(415, 758, "no write path into the record store except through ingestion", 11, "middle", True)
s += '</svg>'
FIGS.append((23, "Agent Interoperability — MCP Tool Server and OpenClaw Skill Through the Agent Gateway", s))

# ===================== FIG. 24 — Hybrid transport =====================
w, h = 800, 610
s = svg_open(w, h)
s += box(30, 20, 200, 46, ["Producer node", "(knowledge records and media)"], "5500")
s += arrow(230, 43, 270, 43)
s += box(270, 14, 500, 58, ["Per-type compression: record batches by a dictionary primed",
                            "with record field names; media by a standard codec, unaltered"], "5510")
s += arrow(520, 72, 520, 104)
s += box(80, 104, 660, 100, [], "5520")
s += label(410, 124, "FRAME", 12, "middle", True)
fields = [(96, 130, ["32-byte header"], "5521"), (238, 100, ["Metadata"], "5522"), (350, 180, ["Payload"], "5523"),
          (542, 80, ["CRC32"], "5524"), (634, 96, ["Signature", "(optional)"], "5525")]
for x, wd, lab, ref in fields:
    s += cell(x, 134, wd, 42, lab, 11.5, bold_first=False)
    s += label(x + wd / 2, 194, ref, 11, "middle", True)
s += arrow(410, 204, 410, 230)
s += line(150, 230, 670, 230)
for cx, lab, ref in ((150, "CONTROL lane", "5530"), (410, "NORMAL lane", "5531"), (670, "BULK lane", "5532")):
    s += arrow(cx, 230, cx, 254)
    s += box(cx - 100, 254, 200, 60, [lab, "own connection,", "rate limit, receipt window"], ref)
s += line(150, 314, 150, 340); s += line(410, 314, 410, 340); s += line(670, 314, 670, 340); s += line(150, 340, 670, 340)
s += arrow(410, 340, 410, 366)
s += box(170, 366, 480, 62, ["RECEIVER: frame reader drops a frame failing plausibility,",
                             "checksum or signature and resynchronizes at the next marker"], "5541")
s += line(410, 428, 410, 446); s += line(230, 446, 590, 446)
s += arrow(230, 446, 230, 474); s += arrow(590, 446, 590, 474)
s += box(80, 474, 300, 62, ["Package rebuild and manifest check", "(HLS, MPEG-DASH or RTMP ingest)"], "5543")
s += box(440, 474, 300, 62, ["Record verification into the", "Fact Unit store (provenance", "travels with the data)"], "5550")
s += label(410, 570, "a bulk transfer cannot hold a control message or a live stream behind it;", 11, "middle", True)
s += label(410, 590, "the transport neither enlarges nor alters a compressed asset", 11, "middle", True)
s += '</svg>'
FIGS.append((24, "Hybrid Transport — Framed Messages on Priority Lanes over TCP/IP (extends FIG. 17)", s))

import re as _re


def _margin(svg):
    m = _re.search(r'viewBox="0 0 (\d+) (\d+)"', svg)
    w0, h0 = int(m.group(1)), int(m.group(2))
    svg = svg.replace(m.group(0), 'viewBox="0 -18 %d %d"' % (w0 + 60, h0 + 18), 1)
    return svg.replace('<rect x="0" y="0" width="%d" height="%d" fill="#fff"/>' % (w0, h0),
                       '<rect x="0" y="-18" width="%d" height="%d" fill="#fff"/>' % (w0 + 60, h0 + 18), 1)


FIGS = [(n, t, _margin(sv)) for n, t, sv in FIGS]

if __name__ == "__main__":
    import json
    json.dump(FIGS, open(sys.argv[2], "w"))
    print("figures:", [f[0] for f in FIGS])
