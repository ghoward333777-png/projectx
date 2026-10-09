"""FIG. 50–55 for Section XV, drawn with the primitives of patent/build_patent_figs.py
(executed up to its figure list, so the line style, boxes and numeral placement are identical)."""
import os
import sys

SRC = os.path.join(sys.argv[1], "build_patent_figs.py")
code = open(SRC, encoding="utf-8").read()
exec(code[:code.index("FIGS = []")], globals())

FIGS = []

def cell(x, y, w, h, lines, size=11, dashed=False, bold_first=True):
    d = ' stroke-dasharray="5 3"' if dashed else ''
    o = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#fff" stroke="#000" stroke-width="1"{d}/>'
    lh = size + 3; ty = y + h / 2 - (len(lines) - 1) * lh / 2 + 4
    for i, ln in enumerate(lines):
        o += label(x + w / 2, ty + i * lh, ln, size, "middle", bold_first and i == 0 and len(lines) > 1)
    return o


# ===================== FIG. 56 — Verified Agent Transport: deployment =====================
w, h = 840, 640
s = svg_open(w, h)
s += box(20, 20, 800, 260, [], "5605", dashed=True)
s += label(420, 40, "EGRESS LOCK: the agent can reach only its sidecar", 11.5, "middle", True)
s += box(40, 60, 190, 78, ["AI agent (unmodified)", "speaks MCP, A2A", "or HTTP"], "5600")
s += arrow(230, 99, 280, 99)
s += box(280, 56, 500, 210, [], "5610")
s += label(530, 76, "VAT SIDECAR (co-located with the agent)", 12.5, "middle", True)
cells = [("Protocol adapters", "MCP, A2A, HTTP", "5612"), ("Claim extraction", "fact / opinion / plan", "5614"),
         ("Intent binding", "plan, allow-list, result", "5616"), ("Frame codec + signing", "UFCS-FQL frames", "5618")]
for i, (a, b, ref) in enumerate(cells):
    x = 296 + (i % 2) * 244; y = 92 + (i // 2) * 84
    s += cell(x, y, 226, 62, [a, b], 11.5)
    s += label(x + 226 - 4, y + 58, ref, 10.5, "end", True)
s += arrow(530, 266, 530, 318)
s += box(170, 318, 530, 120, [], "5620")
s += label(435, 338, "ENCRYPTED CONNECTION: QUIC streams, or TLS over TCP", 12.5, "middle", True)
for i, (a, b, ref) in enumerate([("Control lane", "verdicts, intent, certificates", "5622"), ("Normal lane", "claims, queries, answers", "5624"), ("Bulk lane", "Fact Unit data, media", "5626")]):
    x = 186 + i * 170
    s += cell(x, 352, 158, 54, [a, b], 11)
    s += label(x + 79, 424, ref, 10.5, "middle", True)
s += arrow(700, 378, 730, 378)
s += box(730, 330, 100, 96, ["Peer VAT", "sidecar"], "5630")
s += arrow(780, 426, 780, 470)
s += box(700, 470, 130, 60, ["Destination", "agent or tool"], "5640")
s += box(40, 480, 250, 80, ["UFCS verification service", "fingerprint lookup + FQL", "contradiction query"], "5650")
s += box(320, 480, 220, 80, ["Tamper-evident ledger", "and session certificates", "(FIG. 53, FIG. 51)"], "5660")
s += box(30, 330, 80, 96, ["Control", "plane", "(policy,", "keys)"], "5670", dashed=True)
s += line(200, 438, 200, 480, dashed=True); s += line(430, 438, 430, 480, dashed=True)
s += line(110, 378, 170, 378, dashed=True)
s += label(420, 600, "only traffic that passes through the sidecar is verified, recorded and certified", 11, "middle", True)
s += '</svg>'
FIGS.append((56, "Verified Agent Transport — Sidecar, Egress Lock and Lanes over an Encrypted Connection", s))

# ===================== FIG. 57 — VAT verification, binding and certification =====================
w, h = 840, 760
s = svg_open(w, h)
s += box(250, 16, 300, 46, ["Outbound agent message", "(text, claim, action)"], "5700")
s += arrow(400, 62, 400, 92)
s += box(220, 92, 360, 56, ["Classify each sentence", "fact / opinion / plan / prediction"], "5705")
s += arrow(580, 120, 640, 120)
s += box(640, 96, 180, 50, ["Non-fact: labelled,", "never verified"], "5706", dashed=True)
s += arrow(400, 148, 400, 178)
s += box(220, 178, 360, 56, ["Extract triple + semantic fingerprint", "(coverage measured; misses = unchecked)"], "5710")
s += arrow(400, 234, 400, 264)
s += box(250, 264, 300, 50, ["Fingerprint in UFCS store", "at or above minimum trust?"], "5720")
s += arrow(550, 289, 640, 289); s += label(560, 282, "yes", 10.5)
s += box(640, 266, 180, 46, ["VERIFIED", "with citation"], "5731")
s += arrow(400, 314, 400, 344); s += label(408, 334, "no", 10.5)
s += box(220, 344, 360, 56, ["FQL: same subject and predicate,", "different object, higher trust?"], "5725")
s += arrow(580, 372, 640, 372); s += label(590, 365, "yes", 10.5)
s += box(640, 348, 180, 46, ["CONTRADICTED", "cite stronger record"], "5732")
s += arrow(400, 400, 400, 430); s += label(408, 420, "no", 10.5)
s += box(300, 430, 200, 40, ["UNKNOWN (labelled)"], "5733")
s += line(820, 289, 836, 289); s += line(820, 371, 836, 371); s += line(836, 289, 836, 490); s += line(400, 470, 400, 490); s += line(400, 490, 836, 490)
s += arrow(560, 490, 560, 516)
s += box(330, 516, 460, 56, ["Signed VERDICT frame on the control lane", "delivery policy: deliver, annotate or block"], "5740")
s += box(20, 516, 280, 56, ["ACTION checked against INTENT and", "allow-list; RESULT vs tool record"], "5745")
s += line(160, 572, 160, 600); s += line(560, 572, 560, 600); s += line(160, 600, 560, 600)
s += arrow(360, 600, 360, 620)
s += box(200, 620, 320, 46, ["Ledger append: hash chain,", "write-once Merkle checkpoints"], "5750")
s += arrow(520, 643, 560, 643)
s += box(560, 614, 260, 60, ["Agent Session Certificate:", "counts, coverage, Merkle root"], "5770")
s += arrow(690, 674, 690, 700)
s += box(560, 700, 260, 46, ["Agent reputation", "evidence pair (alpha, beta)"], "5780")
s += box(20, 92, 180, 140, ["Have / want exchange", "HAVE: fingerprints", "WANT: missing ones", "DATA: only missing", "records are sent"], "5790", dashed=True)
s += box(20, 264, 180, 96, ["Privacy mode", "verify by fingerprint;", "text never leaves", "the sidecar"], "5795", dashed=True)
s += label(360, 700, "the certificate records what was checked and what the checks found;", 10.5, "middle", True)
s += label(360, 716, "it does not assert that the agent is honest or that content is true", 10.5, "middle", True)
s += '</svg>'
FIGS.append((57, "Verified Agent Transport — Claim Verification, Intent Binding and Session Certification", s))

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
