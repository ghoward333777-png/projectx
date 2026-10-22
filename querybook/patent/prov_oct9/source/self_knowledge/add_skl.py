#!/usr/bin/env python3
"""Add the Self-Knowledge Layer (FIG. 57, claims 358–362) to the synced provisional with wrapper support.
Additions only: new paragraphs are inserted after existing ones; no existing paragraph is changed.
Usage: add_support.py <in.docx> <out.docx> hl|clean"""
import copy, sys, zipfile, os
from lxml import etree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', 'docs', 'source'))
import skl_text as T
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"; q = lambda t: f"{{{W}}}{t}"
XS = "{http://www.w3.org/XML/1998/namespace}space"
src, out, mode = sys.argv[1:4]; HL = mode == "hl"
zin = zipfile.ZipFile(src); MEMBERS = [(i, zin.read(i.filename)) for i in zin.infolist()]
root = etree.fromstring(dict((i.filename, b) for i, b in MEMBERS)["word/document.xml"])
body = root.find(q("body")); P = body.findall(q("p"))
text = lambda p: "".join(t.text or "" for t in p.iter(q("t")))
RPR_ORDER = ["rStyle","rFonts","b","bCs","i","iCs","caps","smallCaps","strike","dstrike","outline","shadow","emboss","imprint","noProof",
  "snapToGrid","vanish","webHidden","color","spacing","w","kern","position","sz","szCs","highlight","u","effect","bdr","shd","fitText",
  "vertAlign","rtl","cs","em","lang","eastAsianLayout","specVanish","oMath"]
def mk_rpr(rpr, bold):
    rpr = copy.deepcopy(rpr) if rpr is not None else etree.Element(q("rPr"))
    for tag in ("highlight", "shd", "b", "bCs"):
        for e in rpr.findall(q(tag)): rpr.remove(e)
    if bold: rpr.append(etree.Element(q("b")))
    if HL: h = etree.Element(q("highlight")); h.set(q("val"), "yellow"); rpr.append(h)
    kids = sorted(rpr, key=lambda e: RPR_ORDER.index(etree.QName(e).localname) if etree.QName(e).localname in RPR_ORDER else 99)
    for k in list(rpr): rpr.remove(k)
    for k in kids: rpr.append(k)
    return rpr
def clone(tpl, runs):
    p = etree.Element(q("p")); ppr = tpl.find(q("pPr"))
    if ppr is not None: p.append(copy.deepcopy(ppr))
    trs = [r.find(q("rPr")) for r in tpl.findall(q("r")) if r.find(q("t")) is not None]
    plain = next((r for r in trs if r is None or r.find(q("b")) is None), trs[0] if trs else None)
    for s, bold in runs:
        r = etree.SubElement(p, q("r")); r.append(mk_rpr(plain, bold))
        t = etree.SubElement(r, q("t")); t.text = s; t.set(XS, "preserve")
    return p
def expect(i, prefix):
    assert text(P[i]).strip().startswith(prefix), (i, text(P[i])[:80]); return P[i]
def insert_after(anchor, tpl, paras):
    for runs in reversed(paras): anchor.addnext(clone(tpl, runs))

def find(prefix):
    hits = [i for i, p in enumerate(P) if text(p).strip().startswith(prefix)]
    assert len(hits) == 1, (prefix, hits); return P[hits[0]]

# resolve all anchors before editing
aG = find("g. Support for external agent-wrapper services")
a56 = find("FIG. 56 is a block diagram"); aN56 = find("[Drafting note: FIG. 56 is added")
aS7 = find("7. Support for agent-wrapper services.")
a10 = find("10. Support interfaces for agent-wrapper services"); a11 = find("11. Status. The support interfaces of FIG. 56")
aR56 = find("Referring to FIG. 56:")
a357 = find("357.  The method of claim 355"); aCN = find("[Drafting note: claims 355–357 are added")
ORIG = [etree.tostring(p) for p in P]

insert_after(aG, aG, T.SUMMARY_H)              # summary item h follows item g
insert_after(aN56, a56, T.BRIEF)               # FIG. 57 brief description follows FIG. 56 and its note
insert_after(aN56.getnext(), aN56, T.NOTE)
insert_after(aS7, aS7, T.SYSTEM_8)
insert_after(a11, a10, T.CORE)                 # items 12-13 follow item 11, styled as item 10
insert_after(aR56, aR56, T.ARCH)
insert_after(aCN, a357, [[(n, True), (c, False)] for n, c in T.CLAIMS])
last = aCN
for _ in T.CLAIMS: last = last.getnext()
last.addnext(clone(aCN, [(T.CLAIM_NOTE, False)]))

# verify: every original paragraph unchanged and in order
NP = body.findall(q("p")); ser = [etree.tostring(p) for p in NP]
it = iter(ser); assert all(o in it for o in ORIG), "original paragraph changed"
added = len(NP) - len(P); print("added paragraphs:", added)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for i, b in MEMBERS:
        z.writestr(i, etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True) if i.filename == "word/document.xml" else b)
