"""Add FIG. 58-59 (Digital Synaptic Network answer routing; network memory) to the Drawings and Description document: brief
descriptions, detailed descriptions, reference numerals and status, in the styles of the FIG. 57 entries.
Usage: desc_dsn.py <FIG1-57.docx> <FIG1-59.docx>"""
import copy, os, sys
from docx import Document
from docx.table import Table, _Row
from docx.text.paragraph import Paragraph
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "docs", "source"))
import dsn_text as T
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

src, out = sys.argv[1:3]
d = Document(src); P = d.paragraphs; body = d.element.body
find = lambda s: next(p for p in P if p.text.startswith(s))
h2, brief = find("Self-knowledge (FIG. 57)"), find("FIG. 57 is a block diagram")
h1 = find("Detailed Description of FIG. 57"); pbr = h1._p.getprevious()
txt = find("A self-question (5700)"); stat = find("The self-knowledge layer of FIG. 57 is built")
refh = [p for p in P if p.text == "Reference numerals"][-1]; sth = [p for p in P if p.text == "Status"][-1]
tbl = d.tables[-1]

def para(tpl, runs):
    p = copy.deepcopy(tpl._p)
    rs = p.findall(".//" + W + "r")
    for r in rs[1:]: r.getparent().remove(r)
    para_ = Paragraph(p, tpl._parent)
    para_.runs[0].text = runs[0][0]
    para_.runs[0].bold = runs[0][1]
    for s, bold in runs[1:]:
        r = copy.deepcopy(rs[0]); p.append(r)
        Paragraph(p, tpl._parent).runs[-1].text = s
        Paragraph(p, tpl._parent).runs[-1].bold = bold
    return p

def numerals(key, fig):
    nt = copy.deepcopy(tbl._tbl)
    rows = nt.findall(W + "tr")
    for r in rows[2:]: nt.remove(r)
    t = Table(nt, d._body); tpl_row = t.rows[1]._tr
    for n, (num, what) in enumerate(key):
        tr = tpl_row if n == 0 else copy.deepcopy(tpl_row)
        if n: nt.append(tr)
        row = _Row(tr, t)
        for c, v in zip(row.cells, [num, what, f"FIG. {fig}"]):
            q = c.paragraphs[0]
            q.runs[0].text = v
            for r in q.runs[1:]: r.text = ""
    return nt

# brief descriptions after FIG. 57
a = brief._p
for el in [para(h2, [(f"Digital Synaptic Network — answer routing (FIG. {T.FIG_R})", None)]), para(brief, [(t, b) for t, b in T.BRIEF_R[0]]),
           para(h2, [(f"Network memory (FIG. {T.FIG_N})", None)]), para(brief, [(t, b) for t, b in T.BRIEF_N[0]])]:
    a.addnext(el); a = el
# detailed descriptions at the end
sect = body[-1]
for fig, intro, core, key, status in (
        (T.FIG_R, T.INTRO[0], T.CORE[0][1][0], T.FIG_KEY_R,
         f"The answer routing of FIG. {T.FIG_R} is built and tested in the shared core of the applications (qbdsn.py, Control Panel 1.34). "
         "It corresponds to features 392–398 of the QueryBook Composite Feature Registry v71, to Chapter 131 of the QueryBook Bible v2.1 "
         "(Pass 120) and to claims 363–366 and 371 of the application. The stress-test harness (5870) is a test tool, not part of the product."),
        (T.FIG_N, T.INTRO[1], T.CORE[1][1][0] + " " + T.CORE[2][1][0], T.FIG_KEY_N,
         f"The network memory of FIG. {T.FIG_N} is built and tested in prototype v9.64 (qb_synapse.py) and in the shared core of the "
         "applications (qbsynapse.py, Control Panel 1.35). It corresponds to features 399–407 of the QueryBook Composite Feature Registry "
         "v71, to Chapter 131 of the QueryBook Bible v2.1 (Pass 120) and to claims 367–374 of the application.")):
    els = [copy.deepcopy(pbr), para(h1, [(f"Detailed Description of FIG. {fig}", None)])]
    els += [para(txt, [(t, None)]) for t in (intro, core)]
    els += [para(refh, [("Reference numerals", None)]), numerals(key, fig), para(sth, [("Status", None)]), para(stat, [(status, None)])]
    for el in els: sect.addprevious(el)
# titles
P[1].runs[0].text = ("FIG. 1–59 · companion to the Provisional Patent Application (synchronized, with support for agent-wrapper services, "
                     "the self-knowledge layer, and the digital synaptic network with network memory)")
for r in P[1].runs[1:]: r.text = ""
P[2].runs[0].text = T.DATE
for r in P[2].runs[1:]: r.text = ""
for s in d.sections:
    for p in s.header.paragraphs:
        for r in p.runs: r.text = r.text.replace("FIG. 1–57", "FIG. 1–59")
d.save(out)
print("saved", out)
