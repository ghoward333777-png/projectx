#!/usr/bin/env python3
"""QueryBook Bible v2.1, Pass 119 = Pass 118 (every paragraph unchanged) + Chapter 130, The Self-Knowledge Layer (SKL),
written from the same source as Core Technology Overview §56 and the provisional's FIG. 57.
Usage: build_bible_p119.py <Pass_118.docx> <Pass_119.docx>"""
import copy, os, sys
from docx import Document
from docx.text.paragraph import Paragraph
from lxml import etree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skl_text as T

src, out = sys.argv[1:3]
d = Document(src); P = d.paragraphs
ORIG = [etree.tostring(copy.deepcopy(p._p)) for p in P]
ch = next(p for p in P if p.text == "Chapter 129")
h2 = P[P.index(ch) + 1]; body = P[P.index(ch) + 2]

def clone(tpl, text):
    p = copy.deepcopy(tpl._p); para = Paragraph(p, tpl._parent)
    for r in para.runs[1:]: r._r.getparent().remove(r._r)
    para.runs[0].text = text
    return p

ov = lambda s: s.replace("this Overview", "the Core Technology Overview (v15)").replace("(§1 through §56)", "(Overview §1 through §56)")
els = [clone(ch, "Chapter 130: " + T.TITLE),
       clone(body, "In this chapter § numbers refer to the sections of the Core Technology Overview (v15); chapter numbers refer to this Bible.")]
els += [clone(body, ov(t).replace("Prime Directive (§10)", "Prime Directive (Domain 0; Overview §10)")) for t in T.INTRO]
for head, paras in T.SUBSECTIONS:
    els.append(clone(h2, head.replace("56.", "130.", 1)))
    els += [clone(body, ov(t)) for t in paras]
els.append(clone(h2, "130.10 Correspondence with this specification"))
for t in [
    "The layer's twelve reasoning aspects correspond to chapters of this Bible as follows. Deterministic reasoning: Chapter 5 "
    "(Provenance Ledger) and the determinism guarantee of the context lock. Atomic knowledge: Chapter 3 (Fact Unit Structure). World "
    "model: Chapter 53 (World Aware System Model). Predictive cognition: Chapter 10 (Predictive Inference Engine), Chapter 41 (Predictive "
    "Cognitive Architecture) and Chapter 103 (Temporal Prediction Calibration Layer). Neuromorphic layer: Chapter 7 (Neuromorphic "
    "Cognitive Layer) and Chapter 101 (Verified Neuromorphic Correspondence Methodology). Hypothesis generation: Chapter 97. Simulation: "
    "Chapter 11 (Scenario Graph). Feedback loops: Chapter 66 (Improvement Proposal Pipeline) and Chapter 77 (Validation and "
    "Benchmarking). Supervised self-improvement: Chapter 66 and Chapter 78 (QueryBook AI Evolution). Recursive self-improvement: "
    "excluded under Domain 0 (the Prime Directive) and the approval gates. Self-knowledge: this chapter, with Chapter 40 (Specification "
    "Validation Framework), which validates the specification as this layer validates the system's description of itself.",
    "A chapter of this Bible that specifies a capability not yet built remains specification. The layer reports such a capability as "
    "specified, not yet built, and lists it in its gap agenda; it never reports specification as implementation.",
    f"Registry and claims: Composite Feature Registry v70, features 383–391 (algorithms ALG-20 and ALG-21); provisional application, "
    f"FIG. 57 (reference numerals 5700–5799) and claims 358–362. (Drafting record, Pass 119, {T.DATE}.)"]:
    els.append(clone(body, t))
anchor = P[-1]._p
for el in els:
    anchor.addnext(el); anchor = el
now = [etree.tostring(copy.deepcopy(p._p)) for p in d.paragraphs]
assert now[:len(ORIG)] == ORIG, "a Pass 118 paragraph changed"
d.core_properties.title = "QueryBook Bible v2.1 — Pass 119 (Self-Knowledge Layer)"
d.save(out)
print("added paragraphs:", len(now) - len(ORIG))
