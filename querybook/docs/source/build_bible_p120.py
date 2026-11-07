#!/usr/bin/env python3
"""QueryBook Bible v2.1, Pass 120 = Pass 119 (every paragraph unchanged) + Chapter 131, The Digital Synaptic Network (DSN) and
Network Memory, written from the same source as the provisional's FIG. 58-59 and Registry v71 (docs/source/dsn_text.py).
Usage: build_bible_p120.py <Pass_119.docx> <Pass_120.docx>"""
import copy, os, sys
from docx import Document
from docx.text.paragraph import Paragraph
from lxml import etree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsn_text as T

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

els = [clone(ch, "Chapter 131: " + T.TITLE),
       clone(body, "In this chapter chapter numbers refer to this Bible; § numbers refer to the Core Technology Overview (v15).")]
els += [clone(body, t) for t in T.INTRO]
for head, paras in T.SUBSECTIONS:
    els.append(clone(h2, head))
    els += [clone(body, t) for t in paras]
els.append(clone(h2, "131.15 Correspondence with this specification"))
for t in [
    "The DSN is the implemented, measured part of the neuromorphic direction specified in Chapter 7 (Neuromorphic Cognitive Layer). It "
    "follows the method of Chapter 101 (Verified Neuromorphic Correspondence Methodology): it names a correspondence with biology — "
    "synaptic strength, thresholds, inhibition, plasticity, engrams, neuronal ensembles — and states what is built, what was measured, "
    "and where the correspondence stops. Chapter 7 as a whole remains specification; the Self-Knowledge Layer (Chapter 130) continues to "
    "report the Neuromorphic Cognitive Layer as specified, not yet built.",
    "Network memory corresponds to Chapter 95 (Complementary Learning Systems Formalization): engrams and consolidation record which "
    "agents solved which kinds of problem, beside the fact store that records what is true. Assemblies and links between assemblies "
    "extend Chapter 98 (Cognitive Map Formalization) from concepts to the agents that process them. The agents themselves are those of "
    "Chapter 56 (Robot Memory Domain — Autonomous Agent Integration with the Fact Universe) and the harvesting teams of the Commons; the cross-application "
    "checks they exchange are the cooperation those chapters specify, now remembered as directed synapses.",
    "Governance is unchanged. Under Domain 0 (the Prime Directive) a synapse or pathway never asserts a fact and never alters an answer; "
    "every one keeps its provenance as a Fact Unit does (Chapter 3, Chapter 5); the routing setting is an administrator's decision; and "
    "the stress test belongs with Chapter 77 (Validation and Benchmarking), whose rule it keeps: results are reported as measured, "
    "including where the new design loses to the old.",
    f"Registry and claims: Composite Feature Registry v71, features 392–407 (algorithms ALG-22 to ALG-25); provisional application, "
    f"FIG. 58 (reference numerals 5800–5899), FIG. 59 (5900–5999) and claims 363–374. (Drafting record, Pass 120, {T.DATE}.)"]:
    els.append(clone(body, t))
anchor = P[-1]._p
for el in els:
    anchor.addnext(el); anchor = el
now = [etree.tostring(copy.deepcopy(p._p)) for p in d.paragraphs]
assert now[:len(ORIG)] == ORIG, "a Pass 119 paragraph changed"
d.core_properties.title = "QueryBook Bible v2.1 — Pass 120 (Digital Synaptic Network and Network Memory)"
d.save(out)
print("added paragraphs:", len(now) - len(ORIG))
