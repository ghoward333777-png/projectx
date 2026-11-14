#!/usr/bin/env python3
"""QueryBook Bible v2.1, Pass 121 = Pass 120 (every paragraph's text unchanged) + Chapter 132, The Four-State Fact Unit, written
from the same source as the provisional's FIG. 60-61 and Registry v72 (docs/source/fsu_text.py).
Mode hl: the new chapter is highlighted yellow, and so are the earlier Fact Unit design passages it builds on (the Chapter 3
master definition and evidence pair, and the Beta-posterior confidence of section 41.6.2) - highlight only, no text changed.
Usage: build_bible_p121.py <Pass_120.docx> <Pass_121.docx> hl|clean"""
import copy, os, re, sys
from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.text.paragraph import Paragraph
from lxml import etree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fsu_text as T

src, out, mode = sys.argv[1:4]; HL = mode == "hl"
d = Document(src); P = d.paragraphs
ORIG = [etree.tostring(copy.deepcopy(p._p)) for p in P]; ORIG_TEXT = [p.text for p in P]
ch = next(p for p in P if p.text == "Chapter 129")
h2 = P[P.index(ch) + 1]; body = P[P.index(ch) + 2]

def clone(tpl, text):
    p = copy.deepcopy(tpl._p); para = Paragraph(p, tpl._parent)
    for r in para.runs[1:]: r._r.getparent().remove(r._r)
    para.runs[0].text = text
    if HL: para.runs[0].font.highlight_color = WD_COLOR_INDEX.YELLOW
    return p

els = [clone(ch, "Chapter 132: " + T.TITLE),
       clone(body, "In this chapter chapter numbers refer to this Bible; § numbers refer to the Core Technology Overview (v15).")]
els += [clone(body, t) for t in T.INTRO]
els.append(clone(h2, "The four states at a glance"))
els += [clone(body, f"{s} — code {c} — {m} — in hardware terms: {hw}.") for s, c, m, hw in T.STATES]
els.append(clone(h2, "The eight backings and their weights"))
els += [clone(body, f"{b} — state {s} — weight {w} — {why}.") for b, s, w, why in T.BACKINGS]
for head, paras in T.SUBSECTIONS:
    els.append(clone(h2, head))
    els += [clone(body, t) for t in paras]
els.append(clone(h2, "132.11 Correspondence with this specification"))
els += [clone(body, t) for t in T.BIBLE_CORR]
anchor = P[-1]._p
for el in els:
    anchor.addnext(el); anchor = el

EARLIER = 0
if HL:   # the earlier Fact Unit design passages: highlight only
    c3 = [i for i, t in enumerate(ORIG_TEXT) if t.startswith("Chapter 3: Fact Unit Structure")][-1]
    c4 = next(i for i in range(c3, len(ORIG_TEXT)) if ORIG_TEXT[i].startswith("Chapter 4:"))
    pick = [i for i in range(c3, c4) if ORIG_TEXT[i].startswith("Chapter 3:") or ORIG_TEXT[i].startswith("Master definition")
            or re.search(r"evidence pair", ORIG_TEXT[i])]
    pick += [i for i, t in enumerate(ORIG_TEXT) if "ceases to be a scalar and becomes the mean of a Beta distribution" in t
             or t.startswith("§41.6.2 — Fully Bayesian ConfidenceScore")]
    for i in pick:
        for r in P[i].runs: r.font.highlight_color = WD_COLOR_INDEX.YELLOW
    EARLIER = len(pick)
now = d.paragraphs
assert [p.text for p in now[:len(ORIG)]] == ORIG_TEXT, "a Pass 120 paragraph's text changed"
if not HL:
    assert [etree.tostring(copy.deepcopy(p._p)) for p in now[:len(ORIG)]] == ORIG, "a Pass 120 paragraph changed"
d.core_properties.title = "QueryBook Bible v2.1 — Pass 121 (The Four-State Fact Unit)"
d.save(out)
print("added paragraphs:", len(now) - len(ORIG), "earlier Fact Unit passages highlighted:", EARLIER)
