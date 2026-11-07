#!/usr/bin/env python3
"""Add the Digital Synaptic Network and network memory (FIG. 58-59, claims 363-374) to the synced provisional with the
self-knowledge layer. Additions only: new paragraphs are inserted after existing ones; no existing paragraph is changed.
Usage: add_dsn.py <Prov_Patent_Oct9_SYNCED_SelfKnowledge_clean.docx> <out.docx> hl|clean"""
import copy, sys, zipfile, os
from lxml import etree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', 'docs', 'source'))
import dsn_text as T
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
aH = find("h. A self-knowledge layer by which the system")
a57 = find("FIG. 57 is a block diagram"); aN57 = find("[Drafting note: FIG. 57 is added")
aS8 = find("8. Accurate self-knowledge.")
a12 = find("12. Self-Knowledge Layer (FIG. 57)."); a13 = find("13. Status. The self-knowledge layer of FIG. 57")
aR57 = find("Referring to FIG. 57:")
a362 = find("362.  The method of claim 358"); aCN = find("[Drafting note: claims 358–362 are added")
ORIG = [etree.tostring(p) for p in P]

insert_after(aH, aH, T.SUMMARY_I)              # summary item i follows item h
insert_after(aN57, a57, T.BRIEF_R + T.BRIEF_N) # FIG. 58 and 59 brief descriptions follow FIG. 57 and its note
insert_after(aN57.getnext().getnext(), aN57, T.NOTE)
insert_after(aS8, aS8, T.SYSTEM_9)
insert_after(a13, a12, T.CORE)                 # items 14-17 follow item 13, styled as item 12
insert_after(aR57, aR57, T.ARCH)
insert_after(aCN, a362, [[(n, True), (c, False)] for n, c in T.CLAIMS])
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
