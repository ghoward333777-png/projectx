"""FIG. 58-59 — the Digital Synaptic Network (answer routing) and network memory, drawn with the same primitives as FIG. 1-57
(copied from figs_skl.py so this file stands alone). Usage: figs_dsn.py <out.json>"""
import json, sys
import html
def esc(s): return html.escape(str(s))

def svg_open(w, h):
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:100%;height:auto;'
            f'background:#fff;border:1px solid #000" xmlns="http://www.w3.org/2000/svg">'
            f'<defs><marker id="ah" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" '
            f'markerUnits="strokeWidth"><path d="M0,0 L8,3 L0,6 z" fill="#000"/></marker></defs>'
            f'<rect x="0" y="0" width="{w}" height="{h}" fill="#fff"/>')

def box(x, y, w, h, lines, ref, dashed=False, r=4):
    d = ' stroke-dasharray="6 4"' if dashed else ''
    o = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="#fff" stroke="#000" stroke-width="1.6"{d}/>'
    n = len(lines)
    lh = 15
    ty = y + h/2 - (n-1)*lh/2 + 4
    for i, ln in enumerate(lines):
        weight = 'font-weight="700"' if i == 0 else ''
        o += (f'<text x="{x+w/2}" y="{ty+i*lh}" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" '
              f'font-size="12.5" fill="#000" {weight}>{esc(ln)}</text>')
    if ref is not None:
        # reference numeral OUTSIDE the box (just above the top-right corner) with a short
        # leader tick, so it never overlaps the element label — patent-drawing convention.
        o += f'<line x1="{x+w}" y1="{y}" x2="{x+w+10}" y2="{y-12}" stroke="#000" stroke-width="1"/>'
        o += (f'<text x="{x+w+12}" y="{y-9}" text-anchor="start" font-family="Helvetica,Arial,sans-serif" '
              f'font-size="12" font-weight="700" fill="#000">{esc(ref)}</text>')
    return o

def label(x, y, text, size=12, anchor="start", bold=False):
    b = 'font-weight="700"' if bold else ''
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="Helvetica,Arial,sans-serif" '
            f'font-size="{size}" fill="#000" {b}>{esc(text)}</text>')

def arrow(x1, y1, x2, y2):
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#000" stroke-width="1.6" marker-end="url(#ah)"/>'

def line(x1, y1, x2, y2, dashed=False):
    d = ' stroke-dasharray="5 4"' if dashed else ''
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#000" stroke-width="1.4"{d}/>'



import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "docs", "source"))
import dsn_text as T

# ===================== FIG. 58 — Digital Synaptic Network: answer routing =====================
w, h = 840, 700
s = svg_open(w, h)
s += box(40, 30, 230, 56, ["Lookup", "subject text, limit"], "5800")
s += arrow(155, 86, 155, 120)
s += box(20, 120, 800, 420, [], "5805")
s += label(420, 142, "ANSWER ROUTER  (relationships only, never facts)", 12.5, "middle", True)
s += box(250, 156, 340, 58, ["Routing setting (administrator)", "Central · Shadow · DSN"], "5810")
X = [45, 305, 565]; BW = 225; BH = 86
r1 = [("Learned pathway table", "kind × store: strength,", "facts found, empty answers", "5820"),
      ("Strong pathways asked", "strength ≥ 0.30, strongest first;", "strengthen / weaken", None),
      ("Complete-answer fallback", "every remaining store,", "ordered by spreading activation", "5830")]
r2 = [("Shadow comparison log", "agreed · missed · added ·", "stores asked · time (both)", "5840"),
      ("Health report", "routing, last 24 h,", "verdict (≥ 50 lookups)", "5850"),
      ("Re-check on re-enable", "pathways pulled halfway", "back to neutral", "5860")]
for k, (a, b, c, r) in enumerate(r1):
    s += box(X[k], 250, BW, BH, [a, b, c], r)
for k, (a, b, c, r) in enumerate(r2):
    s += box(X[k], 412, BW, BH, [a, b, c], r)
s += arrow(420, 214, 420, 250)
s += arrow(X[0] + BW, 293, X[1], 293); s += arrow(X[1] + BW, 293, X[2], 293)
s += label(X[2] - 17, 244, "nothing found", 10, "middle")
s += arrow(X[0] + BW / 2, 336, X[0] + BW / 2, 412)
s += label(X[0] + BW / 2 + 6, 380, "Shadow: DSN beside Central", 10, "start")
s += arrow(X[0] + BW, 455, X[1], 455)
s += line(X[2] + BW / 2, 412, X[2] + BW / 2, 380, True); s += arrow(X[2] + BW / 2, 380, X[0] + BW / 2 + 40, 336)
s += label(X[2] + BW / 2 + 6, 400, "Central → DSN", 10, "start")
s += box(40, 585, 240, 60, ["Dataset stores (agents)", "asked as the setting says"], "5895")
s += arrow(160, 540, 160, 585)
s += box(310, 585, 240, 60, ["Stress-test harness", "six engines · learning over time"], "5870", dashed=True)
s += box(580, 585, 220, 60, ["Answer", "Central's, in Shadow"], "5899")
s += arrow(690, 540, 690, 585)
s += label(420, 672, "routing never hides a fact: when strong pathways find nothing, every store is asked", 10.5, "middle", True)
s += label(420, 688, "Central is the default and the reference against which the DSN is measured", 10.5, "middle", True)
s += '</svg>'
FIG58 = s

# ===================== FIG. 59 — Network memory =====================
w, h = 840, 700
s = svg_open(w, h)
src = [("Answers", "cited specialists"), ("Agent cycles", "harvesting agents"), ("Store lookups", "stores that answered"), ("Checks", "team → team")]
for k, (a, b) in enumerate(src):
    s += box(40 + k * 190, 28, 170, 50, [a, b], "5900" if k == 3 else None)
s += label(420, 98, "activity sources: agents active together (episode, time window, or directed use)", 10.5, "middle")
s += arrow(420, 104, 420, 130)
s += box(20, 130, 800, 430, [], "5905")
s += label(420, 152, "SYNAPSE STORE  (one network file per application)", 12.5, "middle", True)
s += box(45, 166, 750, 62, ["Digital synapse record", "type · strength · threshold (0.30 + 0.40 × bad share) · contexts · good / bad",
                            "evidence (last 5) · history (last 12) · formed · last used · consolidated"], "5910")
X = [45, 305, 565]; BW = 225; BH = 80
r1 = [("Plasticity", "form weak (0.20) on success;", "potentiate / depress", "5920"),
      ("Turnover", "fade by idle time; consolidate;", "prune faded, idle synapses", "5930"),
      ("Co-activation", "episodes · window (600 s) ·", "directed links", "5940")]
r2 = [("Engram store", "per context: agents active", "when it was solved", "5950"),
      ("Assembly detector", "synapses ≥ 0.50 →", "functional assemblies", "5960"),
      ("Assembly links", "synapses above threshold", "between assemblies", "5970")]
for k, (a, b, c, r) in enumerate(r1):
    s += box(X[k], 262, BW, BH, [a, b, c], r)
for k, (a, b, c, r) in enumerate(r2):
    s += box(X[k], 380, BW, BH, [a, b, c], r)
for k in range(3):
    s += arrow(X[k] + BW / 2, 228, X[k] + BW / 2, 262)
s += arrow(X[1] + BW / 2, 342, X[1] + BW / 2, 380); s += arrow(X[1] + BW, 420, X[2], 420)
s += arrow(X[2] + BW / 2, 342, X[0] + BW - 40, 380)
s += box(45, 482, 750, 58, ["Spreading activation", "from active agents along synapses above threshold: activation × strength × 0.5 per step, two steps"], "5980")
# a small network-of-networks sketch inside the assembly boxes is omitted: patent drawings stay block diagrams
s += box(40, 595, 380, 56, ["Interfaces", "/api/network · Network page · Control Panel · health lines"], "5990")
s += arrow(230, 540, 230, 595)
s += box(460, 595, 340, 56, ["Uses", "orders fallback stores (FIG. 58) · reports related agents"], None)
s += arrow(630, 540, 630, 595)
s += label(420, 678, "relationships are memory: never a fact, never a change to an answer — every synapse explains itself", 10.5, "middle", True)
s += '</svg>'
FIG59 = s
FIGS = [(T.FIG_R, T.FIG_R_TITLE, FIG58), (T.FIG_N, T.FIG_N_TITLE, FIG59)]

import re as _re


def _margin(svg):
    m = _re.search(r'viewBox="0 0 (\d+) (\d+)"', svg)
    w0, h0 = int(m.group(1)), int(m.group(2))
    svg = svg.replace(m.group(0), 'viewBox="0 -18 %d %d"' % (w0 + 60, h0 + 18), 1)
    return svg.replace('<rect x="0" y="0" width="%d" height="%d" fill="#fff"/>' % (w0, h0),
                       '<rect x="0" y="-18" width="%d" height="%d" fill="#fff"/>' % (w0 + 60, h0 + 18), 1)


FIGS = [(n, t, _margin(sv)) for n, t, sv in FIGS]

if __name__ == "__main__":
    json.dump(FIGS, open(sys.argv[1], "w"))
    print("figures:", [f[0] for f in FIGS])
