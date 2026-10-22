"""FIG. 57 — the Self-Knowledge Layer, drawn with the same primitives as FIG. 1-56 (copied from build_patent_figs.py so
this file stands alone). Usage: figs_skl.py <out.json>"""
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


# ===================== FIG. 57 — Self-Knowledge Layer =====================
w, h = 840, 700
s = svg_open(w, h)
s += box(40, 40, 220, 60, ["Self-question", "user, assistant or application"], "5700")
s += arrow(150, 100, 150, 140)
s += label(158, 126, "\"Are you neuromorphic?\"  \"What is §21?\"", 10.5, "start")
s += box(20, 140, 800, 400, [], "5705")
s += label(420, 162, "SELF-KNOWLEDGE LAYER  (rule-based, read-only, no language model)", 12.5, "middle", True)
rows = [
    [("Specification index", "Overview §1–§56", "by number and title", "5710"),
     ("Implementation map", "(file, symbol) evidence,", "checked when asked", "5720"),
     ("Status labeller", "built · partly built · specified", "not planned · not present", "5730")],
    [("Aspect describer", "12 reasoning aspects,", "brief · user · engineer", "5740"),
     ("Consistency checker", "missing evidence →", "contradiction, withheld", "5750"),
     ("Gap agenda", "specified and partly built", "sections, nearest component", "5760")],
    [("Rule-based answerer", "label, section numbers,", "file:symbol sources", "5770"),
     ("Disclosure filter", "keys and credentials", "removed", "5780"),
     ("Interfaces", "/api/self · /api/self/ask", "page · panel · assistant", "5790")],
]
X = [45, 305, 565]; BW = 225; BH = 78
for j, row in enumerate(rows):
    y = 190 + j * 118
    for k, (a, b, c, r) in enumerate(row):
        s += box(X[k], y, BW, BH, [a, b, c], r)
    s += arrow(X[0] + BW, y + BH / 2, X[1], y + BH / 2)
    s += arrow(X[1] + BW, y + BH / 2, X[2], y + BH / 2)
for k in range(3):
    s += arrow(X[k] + BW / 2, 190 + BH, X[k] + BW / 2, 308)
s += arrow(X[0] + BW / 2, 308 + BH, X[0] + BW / 2, 426)
s += arrow(X[1] + BW / 2, 308 + BH, X[0] + BW - 60, 426)
s += box(40, 585, 225, 60, ["Program source files", "read as text, never executed"], "5795")
s += box(300, 585, 225, 60, ["Self-tests, measurements", "of the host application"], "5797")
s += arrow(152, 585, 152, 540); s += arrow(412, 585, 412, 540)
s += label(160, 565, "evidence", 10.5, "start"); s += label(420, 565, "evidence", 10.5, "start")
s += box(580, 585, 220, 60, ["Answer", "status label + sources"], "5799")
s += arrow(690, 504, 690, 585)
s += label(420, 672, "every statement carries one status label and its sources; a specified capability is never described as built", 10.5, "middle", True)
s += label(420, 688, "the layer reads and never writes: improvements it identifies pass through the existing approval gates", 10.5, "middle", True)
s += '</svg>'
FIGS = [(57, "Self-Knowledge Layer: Accurate Self-Description with Sources", s)]

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
