#!/usr/bin/env python3
"""Add the four-state Fact Unit (FIG. 60-61, claims 375-386) to the synced provisional with the Digital Synaptic Network.
Additions only: new paragraphs are inserted after existing ones; no existing paragraph's text is changed.
Mode hl: run on the changes-highlighted document; the new text is highlighted yellow and so are the earlier Fact Unit design
passages it builds on (the Fact Unit definition and its supporting/contradicting evidence model, FIG. 2 and FIG. 19) -
highlight only. Mode clean: run on the clean document; nothing highlighted.
Usage: add_fsu.py <Prov_Patent_Oct9_SYNCED_DSN_SynapticNetwork_{clean|changes-highlighted}.docx> <out.docx> hl|clean"""
import copy, sys, zipfile, os
from lxml import etree
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', 'docs', 'source'))
import fsu_text as T
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
def order(rpr):
    kids = sorted(rpr, key=lambda e: RPR_ORDER.index(etree.QName(e).localname) if etree.QName(e).localname in RPR_ORDER else 99)
    for k in list(rpr): rpr.remove(k)
    for k in kids: rpr.append(k)
    return rpr
def mk_rpr(rpr, bold):
    rpr = copy.deepcopy(rpr) if rpr is not None else etree.Element(q("rPr"))
    for tag in ("highlight", "shd", "b", "bCs"):
        for e in rpr.findall(q(tag)): rpr.remove(e)
    if bold: rpr.append(etree.Element(q("b")))
    if HL: h = etree.Element(q("highlight")); h.set(q("val"), "yellow"); rpr.append(h)
    return order(rpr)
def clone(tpl, runs):
    p = etree.Element(q("p")); ppr = tpl.find(q("pPr"))
    if ppr is not None: p.append(copy.deepcopy(ppr))
    trs = [r.find(q("rPr")) for r in tpl.findall(q("r")) if r.find(q("t")) is not None]
    plain = next((r for r in trs if r is None or r.find(q("b")) is None), trs[0] if trs else None)
    for s, bold in runs:
        r = etree.SubElement(p, q("r")); r.append(mk_rpr(plain, bold))
        t = etree.SubElement(r, q("t")); t.text = s; t.set(XS, "preserve")
    return p
def insert_after(anchor, tpl, paras):
    for runs in reversed(paras): anchor.addnext(clone(tpl, runs))
def find(prefix):
    hits = [i for i, p in enumerate(P) if text(p).strip().startswith(prefix)]
    assert len(hits) == 1, (prefix, hits); return P[hits[0]]
def highlight(p):
    for r in p.findall(q("r")):
        rpr = r.find(q("rPr"))
        if rpr is None: rpr = etree.Element(q("rPr")); r.insert(0, rpr)
        for e in rpr.findall(q("highlight")): rpr.remove(e)
        h = etree.Element(q("highlight")); h.set(q("val"), "yellow"); rpr.append(h); order(rpr)

# resolve all anchors before editing
aI = find("i. A digital synaptic network by which")
a59 = find("FIG. 59 is a block diagram"); aN59 = find("[Drafting note: FIG. 58 and FIG. 59 are added")
aS9 = find("9. Learning connections between agents.")
a14 = find("14. Digital Synaptic Network"); a17 = find("17. Status. The answer routing of FIG. 58")
aR59 = find("Referring to FIG. 58 and FIG. 59:")
a374 = find("374.  The method of claim 367"); aCN = find("[Drafting note: claims 363–374 are added")
EARLIER = [find(s) for s in (
    "FIG. 2 is ", "FIG. 19 is a diagram of the Fact Unit confidence and evidence model",
    "At its foundation, QueryBook uses Fact Units", "At the core of QueryBook is the Fact Unit, a cognitive atom",
    "The Fact Unit does not stand alone", "Fact Units contain atomic meaning, semantic lineage",
    "The fundamental unit of knowledge is a Fact Unit")]
ORIG = [text(p) for p in P]; ORIG_XML = [etree.tostring(p) for p in P]

insert_after(aI, aI, T.SUMMARY_J)               # summary item j follows item i
insert_after(aN59, a59, T.BRIEF_S + T.BRIEF_I)  # FIG. 60 and 61 brief descriptions follow FIG. 59 and its note
insert_after(aN59.getnext().getnext(), aN59, T.NOTE)
insert_after(aS9, aS9, T.SYSTEM_10)
insert_after(a17, a14, T.CORE)                  # items 18-21 follow item 17, styled as item 14
insert_after(aR59, aR59, T.ARCH)
insert_after(aCN, a374, [[(n, True), (c, False)] for n, c in T.CLAIMS])
last = aCN
for _ in T.CLAIMS: last = last.getnext()
last.addnext(clone(aCN, [(T.CLAIM_NOTE, False)]))
if HL:
    for p in EARLIER: highlight(p)

# verify: every original paragraph's text unchanged and in order (clean mode: byte for byte)
NP = body.findall(q("p"))
it = iter(text(p) for p in NP); assert all(o in it for o in ORIG), "original paragraph text changed"
if not HL:
    it = iter(etree.tostring(p) for p in NP); assert all(o in it for o in ORIG_XML), "original paragraph changed"
print("added paragraphs:", len(NP) - len(P), "earlier Fact Unit passages highlighted:", len(EARLIER) if HL else 0)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for i, b in MEMBERS:
        z.writestr(i, etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True) if i.filename == "word/document.xml" else b)
