"""Add FIG. 60-61 (the four-state Fact Unit; its identity state and context) to the Drawings and Description document: brief
descriptions, detailed descriptions, reference numerals and status, in the styles of the earlier entries. Mode hl: the new
text is highlighted yellow, and so are the entries of the earlier Fact Unit figures it builds on (FIG. 2, FIG. 19) - highlight only.
Usage: desc_fsu.py <FIG1-59.docx> <FIG1-61.docx> hl|clean"""
import copy, os, sys
from docx import Document
from docx.table import Table, _Row
from docx.text.paragraph import Paragraph
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "docs", "source"))
import fsu_text as T
from docx.enum.text import WD_COLOR_INDEX
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

src, out, mode = sys.argv[1:4]; HL = mode == 'hl'; NEW = []
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

# brief descriptions after FIG. 59
a = find("FIG. 59 is a block diagram")._p
for el in [para(h2, [(f"Four-state Fact Unit (FIG. {T.FIG_S})", None)]), para(brief, [(t, b) for t, b in T.BRIEF_S[0]]),
           para(h2, [(f"Fact Unit identity state and context (FIG. {T.FIG_I})", None)]), para(brief, [(t, b) for t, b in T.BRIEF_I[0]])]:
    a.addnext(el); a = el; NEW.append(el)
# detailed descriptions at the end
sect = body[-1]
for fig, paras, key, status in (
        (T.FIG_S, [T.INTRO[0], T.CORE[0][1][0], T.CORE[1][1][0]], T.FIG_KEY_S,
         f"The rating of FIG. {T.FIG_S} is built and tested in the shared core of the applications (sense.py; engine 1.56). The packed "
         "two-bit form (6070) is built as functions and is not yet used in the store's file format; the multi-level devices of the hardware "
         "mapping (6080) are specified, and no hardware other than an ordinary binary processor is used or required. It corresponds to "
         "features 408–415 of the QueryBook Composite Feature Registry v72, to Chapter 132 of the QueryBook Bible v2.1 (Pass 121) and to "
         "claims 375–381 of the application."),
        (T.FIG_I, [T.SUBSECTIONS[5][1][0], T.CORE[2][1][0]], T.FIG_KEY_I,
         f"The identity state, unresolved zone, mention weigher, context table and fill unit of FIG. {T.FIG_I} are built and tested in the "
         "shared core of the applications (sense.py, qbbulk.py, qbnews.py; engine 1.56); the ambiguous and conflicting identity states are "
         "defined and not yet assigned automatically. It corresponds to features 416–422 of the QueryBook Composite Feature Registry v72, "
         "to Chapter 132 of the QueryBook Bible v2.1 (Pass 121) and to claims 382–386 of the application.")):
    els = [copy.deepcopy(pbr), para(h1, [(f"Detailed Description of FIG. {fig}", None)])]
    els += [para(txt, [(t, None)]) for t in paras]
    els += [para(refh, [("Reference numerals", None)]), numerals(key, fig), para(sth, [("Status", None)]), para(stat, [(status, None)])]
    for el in els: sect.addprevious(el)
    NEW += els[1:]
if HL:
    R = W + "r"
    def hl(el):
        for r in el.iter(R):
            from docx.text.run import Run
            Run(r, None).font.highlight_color = WD_COLOR_INDEX.YELLOW
    for el in NEW: hl(el)
    for p in P:
        if p.text.startswith("FIG. 2 is ") or p.text.startswith("FIG. 19 is "): hl(p._p)
# titles
P[1].runs[0].text = ("FIG. 1–61 · companion to the Provisional Patent Application (synchronized, with support for agent-wrapper services, "
                     "the self-knowledge layer, the digital synaptic network with network memory, and the four-state Fact Unit)")
for r in P[1].runs[1:]: r.text = ""
P[2].runs[0].text = T.DATE
for r in P[2].runs[1:]: r.text = ""
for s in d.sections:
    for p in s.header.paragraphs:
        for r in p.runs: r.text = r.text.replace("FIG. 1–59", "FIG. 1–61")
d.save(out)
print("saved", out)
