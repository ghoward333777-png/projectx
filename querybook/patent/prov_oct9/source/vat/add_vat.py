#!/usr/bin/env python3
"""Add Verified Agent Transport (FIG. 56–57, claims 355–365) to the synced provisional.
Additions only: new paragraphs are inserted after existing ones; no existing paragraph is changed.
Usage: add_vat.py <in.docx> <out.docx> hl|clean"""
import copy, sys, zipfile, os
from lxml import etree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vat_text as T
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

# resolve all anchors before editing
a116 = expect(116, "f. A framed hybrid transport"); a117 = expect(117, "These additions are implemented")
a175 = expect(175, "FIG. 55 is a block diagram"); a176 = expect(176, "[Drafting note: the complete drawing set")
a265 = expect(265, "6. Faster, provenance-carrying transport")
a365 = expect(365, "8.Framed hybrid transport"); a366 = expect(366, "9. Implementation status")
a407 = expect(407, "Referring to the remaining drawings")
a768 = expect(768, "354.  The method of claim 351"); expect(772, "ABSTRACT")
ORIG = [etree.tostring(p) for p in P]

insert_after(a116, a116, T.SUMMARY_G)          # summary item g follows item f
insert_after(a175, a175, T.BRIEF)              # FIG. 56–57 brief descriptions follow FIG. 55
insert_after(a176, a176, T.NOTE)
insert_after(a265, a265, T.SYSTEM_7)
insert_after(a366, a365, T.CORE)               # items 10–16 follow item 9, styled as item 8
insert_after(a407, a407, T.ARCH)
claims = [[(n, True), (c, False)] for n, c in T.CLAIMS]
note_tpl = a176
insert_after(a768, a768, claims)
last = a768
for _ in T.CLAIMS: last = last.getnext()
last.addnext(clone(note_tpl, [(T.CLAIM_NOTE, False)]))

# verify: every original paragraph unchanged and in order
NP = body.findall(q("p")); ser = [etree.tostring(p) for p in NP]
it = iter(ser); assert all(o in it for o in ORIG), "original paragraph changed"
added = len(NP) - len(P); print("added paragraphs:", added)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for i, b in MEMBERS:
        z.writestr(i, etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True) if i.filename == "word/document.xml" else b)
