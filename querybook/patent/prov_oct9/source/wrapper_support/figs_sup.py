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


# ===================== FIG. 56 — Support interfaces for external agent-wrapper services =====================
w, h = 840, 700
s = svg_open(w, h)
s += box(40, 40, 170, 60, ["AI agent", "MCP, A2A, HTTP"], "5695")
s += arrow(210, 70, 280, 70)
s += box(280, 30, 320, 80, ["External agent-wrapper service", "Verified Agent Transport (VAT)", "or a similar relay"], "5690", dashed=True)
s += arrow(600, 70, 660, 70)
s += box(660, 40, 160, 60, ["Destination", "agent, tool, data"], "5697")
s += arrow(440, 110, 440, 140)
s += label(448, 130, "calls (registered identity)", 10.5, "start")
s += box(20, 140, 800, 375, [], "5600")
s += label(420, 160, "QUERYBOOK SUPPORT INTERFACES", 12.5, "middle", True)
cols = [("VERIFICATION", "5610", [("Claim verification", "endpoint (read-only)", "5612"), ("Contradiction query", "template (FQL)", "5614"),
                                  ("Fingerprint-only", "verification mode", "5616"), ("Triple extraction +", "assertion-type labels", "5618")]),
        ("TRANSPORT", "5620", [("Message types 16-31", "reserved for extensions", "5622"), ("Extension flag +", "session / hop field", "5624"),
                               ("Python frame codec,", "QUIC lanes, TLS fallback", "5626"), ("Have / want fingerprint", "reconciliation", "5628")]),
        ("RECORD + CERTIFICATE", "5630", [("Signed verdicts,", "published verifier key", "5632"), ("External append to", "the security log", "5634"),
                                         ("Session-range", "Merkle root + proofs", "5636"), ("Third-party session", "certificate type", "5638")]),
        ("GOVERNANCE", "5640", [("Wrapper service", "registration", "5642"), ("Signed policy", "bundle export", "5644"),
                                ("MCP pre-/post-call", "hooks, tool result hash", "5646"), ("Principal evidence", "pair (reputation)", "5648")])]
for k, (title, ref, cells_) in enumerate(cols):
    x = 32 + k * 192
    s += box(x, 185, 182, 315, [], ref)
    s += label(x + 91, 205, title, 11, "middle", True)
    for j, (a, b, r) in enumerate(cells_):
        y = 218 + j * 70
        s += cell(x + 8, y, 166, 62, [a, b], 10.5)
        s += label(x + 170, y + 58, r, 10, "end", True)
    s += line(x + 91, 515, x + 91, 540)
s += line(94, 540, 746, 540)
core = [("Fact Unit store", "and FQL", "FIG. 2, 6, 21, 22", "5650"), ("Security log", "FIG. 53", None, "5660"), ("Certificates", "FIG. 51", None, "5670"),
        ("Agent Gateway", "and MCP server", "FIG. 52, 54", "5680"), ("Framed hybrid", "transport", "FIG. 55", "5685")]
for k, (a, b, c, r) in enumerate(core):
    x = 20 + k * 163
    s += arrow(x + 74, 540, x + 74, 565)
    s += box(x, 565, 148, 70, [t for t in (a, b, c) if t], r)
s += label(420, 665, "verification is read-only and records are append-only: a wrapper service never writes Fact Units", 10.5, "middle", True)
s += label(420, 681, "the wrapper service itself is outside the system and is described separately", 10.5, "middle", True)
s += '</svg>'
FIGS.append((56, "Support Interfaces for External Agent-Wrapper Services (Verified Agent Transport and Similar Relays)", s))

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
