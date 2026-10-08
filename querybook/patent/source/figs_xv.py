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
s += box(560, 158, 190, 50, ["Archive bounds: depth ·", "members · size · ratio"], "5070", dashed=True)
s += line(530, 183, 560, 183)
s += box(30, 158, 190, 50, ["Executables described,", "never executed"], "5025", dashed=True)
s += line(220, 183, 250, 183)
s += arrow(390, 208, 390, 236)
s += box(240, 236, 300, 50, ["Instruction-like content screen", "(prompt-injection signatures)"], "5040")
s += arrow(390, 286, 390, 314)
s += box(250, 314, 280, 46, ["OPENCLAW INTERPRETER", "segments → knowledge records"], "5050")
s += line(390, 360, 390, 380); s += line(120, 380, 660, 380)
for cx in (120, 300, 480, 660):
    s += arrow(cx, 380, cx, 400)
s += box(40, 400, 160, 56, ["Artifact-description", "records (format, hash,", "title, size …)"], "5051")
s += box(220, 400, 160, 56, ["Structured records", "(cell · JSON path ·", "embedded data)"], "5052")
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
FIGS.append((50, "Open Claw Ingestion — Artifact Segmenter and OpenClaw Interpreter", s))

# ===================== FIG. 51 — On-chain certification =====================
w, h = 780, 560
s = svg_open(w, h)
s += box(30, 30, 220, 56, ["QueryBook object: QBF · Fact", "Unit · seal · response"], "5110")
s += box(30, 120, 220, 46, ["Local provenance seal", "(hash-chained ledger)"], "5100")
s += arrow(140, 86, 140, 120)
s += arrow(250, 143, 300, 143)
s += box(300, 118, 200, 50, ["Content hash +", "on-chain metadata (data URI)"], "5120")
s += arrow(500, 143, 540, 143)
s += box(540, 112, 210, 62, ["In-system transaction", "signer (test-vector", "self-check at start)"], "5140")
s += arrow(645, 174, 645, 206)
s += box(540, 206, 210, 54, ["Network guard: test networks;", "money-bearing networks refused", "unless expressly elected"], "5150", dashed=True)
s += arrow(645, 260, 645, 292)
s += box(300, 292, 450, 104, ["CERTIFICATE CONTRACT (ERC-721)", "one token per content hash · minter-only mint/revoke",
                              "predecessor/successor lineage · revocation with reason",
                              "content hash + metadata recorded on-chain"], "5160")
s += box(30, 292, 220, 104, ["PUBLIC BLOCKCHAIN", "(independent of QueryBook)"], "5170")
s += line(250, 344, 300, 344)
s += arrow(140, 396, 140, 430)
s += box(30, 430, 300, 70, ["INDEPENDENT VERIFIER", "exists? holder? hash matches?", "revoked? superseded?"], "5180")
s += arrow(330, 465, 420, 465)
s += box(420, 438, 330, 54, ["Licence check: holder of a current,", "unrevoked token is licensed"], "5190")
s += label(390, 535, "a certificate proves the hash was certified — not that the content is true", 11, "middle", True)
s += '</svg>'
FIGS.append((51, "On-Chain Certification — Provenance NFTs, Lineage, Revocation and Independent Verification", s))

# ===================== FIG. 52 — Agent protection and deception =====================
w, h = 820, 640
s = svg_open(w, h)
s += box(300, 14, 220, 40, ["Caller: agent · MCP · HTTP"], "5200")
s += arrow(410, 54, 410, 78)
s += box(290, 78, 240, 40, ["HTTP gate (honeypages, tokens)"], "5210")
s += arrow(410, 118, 410, 142)
s += box(20, 142, 220, 56, ["Isolation register?", "(session · client · verified", "caller)"], "5260")
s += box(270, 142, 280, 64, ["AGENT GATEWAY", "identity token · role · per-agent", "allow-list · replay window"], "5220")
s += line(240, 170, 270, 170)
s += arrow(130, 198, 130, 470)
s += label(140, 330, "isolated →", 10)
s += arrow(410, 206, 410, 236)
s += box(250, 236, 320, 74, ["DECEPTION CHECK", "honeycode (5231) · honeytokens (5232)", "tripwires (5233) · honeypot agents (5234)"], "5230")
s += arrow(410, 310, 410, 340)
s += box(250, 340, 320, 74, ["AI-AWARE FIREWALL (5240)", "injection · secret reveal · role / tag tricks", "ANOMALY DETECTOR (5241): enumeration, timing"], "5240")
s += arrow(410, 414, 410, 446)
s += box(300, 446, 220, 40, ["Production handlers"], "5290")
s += arrow(570, 273, 640, 273); s += arrow(570, 377, 640, 377)
s += box(640, 250, 160, 150, ["SECURITY EVENT", "BUS", "trigger →", "isolate"], "5250")
s += line(720, 400, 720, 505); s += arrow(720, 505, 247, 505)
s += box(20, 470, 225, 70, ["DECOY ENVIRONMENT", "production-shaped responses,", "synthetic content; no path", "to production data"], "5270", dashed=True)
s += box(20, 560, 225, 54, ["Engagement recorder", "(observe only; no action", "against external systems)"], "5280")
s += line(132, 540, 132, 560)
s += box(560, 560, 240, 54, ["Operator-only release", "(local; no network interface)"], "5261", dashed=True)
s += box(290, 560, 250, 54, ["Every decision → tamper-evident", "security record (FIG. 53)"], "5295")
s += arrow(410, 486, 410, 560)
s += '</svg>'
FIGS.append((52, "Agent Protection and Deception Layer — Gateway, Traps, Firewall, Containment and Decoy", s))

# ===================== FIG. 53 — Tamper-evident security record =====================
w, h = 780, 560
s = svg_open(w, h)
s += box(30, 24, 230, 46, ["Security decision", "(allow · deny · decoy · isolate)"], "5300")
s += arrow(260, 47, 300, 47)
s += box(300, 16, 450, 62, ["APPEND-ONLY ENTRY: agent · caller · session · command ·",
                            "parameter hash · decision · flags", "(no update or delete interface)"], "5310")
s += arrow(525, 78, 525, 108)
s += box(300, 108, 450, 48, ["Hash chain: each entry hash commits", "to its predecessor's hash"], "5320")
s += arrow(525, 156, 525, 188)
s += box(300, 188, 450, 70, ["MERKLE CHECKPOINT (every N entries / on demand)", "created exclusively · never overwritten",
                             "signed under deployment key · chained to previous"], "5330")
s += arrow(400, 258, 250, 300); s += arrow(650, 258, 650, 300)
s += box(70, 300, 260, 50, ["Mirror on a second device"], "5340", dashed=True)
s += box(500, 300, 250, 62, ["Blockchain anchor of the root", "(certificate contract,", "FIG. 51)"], "5350", dashed=True)
s += line(200, 350, 200, 400); s += line(625, 362, 625, 400); s += line(200, 400, 625, 400)
s += arrow(410, 400, 410, 424)
s += box(200, 424, 420, 62, ["VERIFIER: recompute every entry and root from", "content (never trust stored hashes);",
                             "Merkle inclusion proof per entry"], "5360")
s += arrow(410, 486, 410, 508)
s += box(200, 508, 420, 40, ["Assurance report: which protections exist"], "5370")
s += '</svg>'
FIGS.append((53, "Tamper-Evident Security Record — Hash Chain, Write-Once Merkle Checkpoints, Mirror and Anchor", s))

# ===================== FIG. 54 — Agent interoperability (MCP / OpenClaw) =====================
w, h = 780, 520
s = svg_open(w, h)
s += box(40, 30, 220, 50, ["External AI agent", "(e.g. OpenClaw)"], "5400")
s += box(40, 120, 220, 76, ["Skill definition: cite, report", "UNKNOWN, treat ingested", "content as data, stop on", "isolation"], "5410", dashed=True)
s += line(150, 80, 150, 120)
s += arrow(260, 55, 330, 55)
s += box(330, 24, 410, 62, ["MCP TOOL SERVER — fixed tools: query · verify ·", "understand · ingest · preview · ledger · NFT · status",
                            "(reserved honeycode NEVER listed)"], "5420")
s += arrow(535, 86, 535, 120)
s += box(370, 120, 330, 46, ["Tool → command mapping under agent's", "registered identity + caller credential"], "5430")
s += arrow(535, 166, 535, 200)
s += box(370, 200, 330, 50, ["AGENT GATEWAY (5220) with the", "agent's allow-list (5450)"], "5440")
s += arrow(450, 250, 300, 300); s += arrow(620, 250, 620, 300)
s += box(140, 300, 300, 70, ["Grounded handlers: cited answer or", "UNKNOWN · verify · inbox-only", "ingestion · ledger / NFT verify"], "5460")
s += box(470, 300, 270, 70, ["Reserved command invoked →", "agent presumed subverted →", "isolated; decoy answers"], "5470", dashed=True)
s += label(390, 420, "connecting an agent confers no capability beyond its allow-list;", 11, "middle", True)
s += label(390, 440, "no write path into the record store except through ingestion conversion", 11, "middle", True)
s += '</svg>'
FIGS.append((54, "Agent Interoperability — MCP Tool Server and OpenClaw Skill Through the Agent Gateway", s))

# ===================== FIG. 55 — Hybrid transport =====================
w, h = 800, 600
s = svg_open(w, h)
s += box(30, 20, 200, 46, ["Producer node", "(knowledge records · media)"], "5500")
s += arrow(230, 43, 270, 43)
s += box(270, 14, 500, 58, ["Per-type compression: record batches by a dictionary primed",
                            "with record field names; media by a standard codec, unaltered"], "5510")
s += arrow(520, 72, 520, 104)
s += box(80, 104, 660, 92, [], "5520")
s += label(410, 124, "FRAME", 12, "middle", True)
xs = [96, 256, 376, 586, 676]
labs = [("32-byte header", "5521", 150), ("Metadata", "5522", 110), ("Payload", "5523", 200), ("CRC32", "5524", 80), ("Sig. (opt.)", "5525", 54)]
for x, (lab, ref, wd) in zip(xs, labs):
    s += f'<rect x="{x}" y="132" width="{wd}" height="40" fill="#fff" stroke="#000" stroke-width="1.4"/>'
    s += label(x + wd / 2, 157, lab, 11.5, "middle")
    s += label(x + wd / 2, 188, ref, 11, "middle", True)
s += arrow(410, 196, 410, 226)
s += line(150, 226, 670, 226)
for cx, lab, ref in ((150, "CONTROL lane", "5530"), (410, "NORMAL lane", "5531"), (670, "BULK lane", "5532")):
    s += arrow(cx, 226, cx, 250)
    s += box(cx - 100, 250, 200, 56, [lab, "own connection · rate limit", "· receipt window"], ref)
s += line(150, 306, 150, 336); s += line(410, 306, 410, 336); s += line(670, 306, 670, 336); s += line(150, 336, 670, 336)
s += arrow(410, 336, 410, 360)
s += box(170, 360, 480, 62, ["RECEIVER: frame reader drops a frame failing plausibility,",
                             "checksum or signature and resynchronizes at the next marker"], "5541")
s += line(410, 422, 410, 438); s += line(230, 438, 590, 438)
s += arrow(230, 438, 230, 466); s += arrow(590, 438, 590, 466)
s += box(80, 466, 300, 56, ["Package rebuild + manifest check", "(HLS · MPEG-DASH · RTMP ingest)"], "5543")
s += box(440, 466, 300, 56, ["Record verification → Fact Unit", "store (provenance travels with bits)"], "5550")
s += label(400, 556, "a bulk transfer cannot hold a control message or a live stream behind it;", 11, "middle", True)
s += label(400, 576, "the transport neither enlarges nor alters a compressed asset", 11, "middle", True)
s += '</svg>'
FIGS.append((55, "Hybrid Transport — Framed UFCS-FQL Messages on Priority Lanes over TCP/IP (extends FIG. 25)", s))

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
