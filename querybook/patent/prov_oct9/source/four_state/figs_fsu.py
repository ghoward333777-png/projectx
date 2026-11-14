"""FIG. 60-61 — the four-state Fact Unit and its identity state and context, drawn with the same primitives as FIG. 1-59
(copied from figs_dsn.py so this file stands alone). Usage: figs_fsu.py <out.json>"""
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
import fsu_text as T

# ===================== FIG. 60 — the four-state Fact Unit =====================
w, h = 840, 720
s = svg_open(w, h)
s += box(40, 28, 300, 56, ["Stored fact", "status · sources in its record · contradiction mark"], "6000")
s += arrow(190, 84, 190, 118)
s += box(20, 118, 800, 300, [], "6005")
s += label(420, 138, "RATING UNIT  (reads the record; never alters it or its identifier)", 12.5, "middle", True)
X = [45, 305, 565]; BW = 225; BH = 80
s += box(X[0], 172, BW, BH, ["Backing selector", "verified · computed · corroborated", "sourced · reported · unsourced", "disputed · rejected"], "6020")
s += box(X[1], 172, BW, BH, ["Corroboration rule", "two different sources named", "in the fact's own record", "one source: not confirmed"], "6040")
s += box(X[2], 172, BW, BH, ["Weight table", "1.0 · 1.0 · 0.9", "0.75 · 0.4 · 0.2", "0.3 · 0.0"], "6030")
s += arrow(X[1], 212, X[0] + BW, 212)
s += arrow(X[0] + BW / 2, 252, X[0] + BW / 2, 304)
s += box(X[0], 304, 485, 96, ["State table — exactly one of four", "TRUE: confirmed, nothing against   ·   FALSE: found wrong",
                                 "UNDETERMINED: no confirming evidence either way", "CONFLICTING: evidence for and evidence against"], "6010")
s += box(X[2], 304, BW, 96, ["Rated fact", "state · backing · weight", "reason · code"], "6050")
s += arrow(X[0] + 485, 352, X[2], 352)
s += arrow(X[2] + BW / 2, 252, X[2] + BW / 2, 304)
s += arrow(X[2] + BW / 2, 418, X[2] + BW / 2, 452)
s += box(X[2], 452, BW, 62, ["Answer", "with tally of the four states"], "6099")
s += box(45, 452, 225, 100, ["Two-bit evidence encoder", "bit 1: confirming evidence", "bit 2: found wrong",
                             "00 undetermined · 01 false", "10 true · 11 conflicting"], "6060")
s += arrow(157, 418, 157, 452)
s += box(305, 452, 225, 100, ["Join unit", "bitwise OR of codes", "true + false = conflicting", "32 states per 64-bit word"], "6070")
s += arrow(270, 502, 305, 502)
s += box(45, 592, 750, 70, ["Hardware mapping (same states, same answers)",
                            "binary processor: two bits per state  ·  four-level element: one digit per state  ·  eight or more levels: one digit holds backing and state",
                            "corresponds in meaning to hardware logic values 1, 0, Z (undriven) and X (driven in conflict); no such circuit is required"], "6080")
s += arrow(417, 552, 417, 592)
s += label(420, 690, "a fact with nothing recorded about its evidence is undetermined — never assumed true", 10.5, "middle", True)
s += label(420, 706, "one source leaves a fact undetermined; popularity and demand never change a state or a weight", 10.5, "middle", True)
s += '</svg>'
FIG60 = s

# ===================== FIG. 61 — identity state, context beside the fact, mention weighing =====================
w, h = 840, 700
s = svg_open(w, h)
s += box(40, 28, 240, 54, ["Subject of a fact", "an identifier, or only a name"], "6100")
s += box(480, 28, 320, 54, ["As-printed fact", "name · date · publication · page · reason · words"], "6160")
s += arrow(160, 82, 160, 118); s += arrow(640, 82, 640, 118)
s += box(20, 118, 800, 400, [], "6105")
s += label(420, 138, "IDENTITY AND CONTEXT  (kept apart from the truth state; the fact is never altered)", 12.5, "middle", True)
X = [45, 305, 565]; BW = 225; BH = 80
s += box(X[0], 172, BW, BH, ["Identity unit", "resolved · unresolved", "ambiguous · conflicting", "resolved only by identifier"], "6110")
s += box(X[1], 172, BW, BH, ["Mention weigher", "against the entity's own facts:", "dates · offices · places", "likely · possible · impossible"], "6130")
s += box(X[2], 172, BW, BH, ["Unresolved zone", "true as printed,", "unresolved as to who;", "never merged by name"], "6120")
s += arrow(X[0] + BW, 212, X[1], 212); s += arrow(X[2], 212, X[1] + BW, 212)
s += box(X[0], 300, 485, 88, ["Context table — beside the facts", "keyed by item, predicate and stored value",
                               "start · end · point in time · qualifiers · rank · sources", "a missing date is never supplied"], "6140")
s += box(X[2], 300, BW, 88, ["Fill unit", "reads the cited source;", "adds context only,", "never a fact"], "6150")
s += arrow(X[2], 344, X[0] + 485, 344)
s += arrow(X[1] + BW / 2, 300, X[1] + BW / 2, 252)
s += label(X[1] + BW / 2 - 8, 280, "the entity's dates, for weighing", 10, "end")
s += label(X[0] + 4, 404, "its sources are what the corroboration rule of FIG. 60 counts", 10, "start")
s += box(X[0], 424, 750, 76, ["Separation", "observed measurements (by period) · observed navigation · inferred intent (labelled) — stored apart from facts",
                               "demand orders harvesting; it never changes a fact's state, weight or confidence"], "6170")
s += box(160, 566, 520, 62, ["Answer", "known entity and its facts · analysis of mentions · unresolved zone shown apart"], "6199")
s += arrow(420, 518, 420, 566)
s += label(420, 664, "whether a statement is true and whom it is about are separate questions, each with its own states", 10.5, "middle", True)
s += label(420, 680, "a name alone never makes a match", 10.5, "middle", True)
s += '</svg>'
FIG61 = s
FIGS = [(T.FIG_S, T.FIG_S_TITLE, FIG60), (T.FIG_I, T.FIG_I_TITLE, FIG61)]

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
