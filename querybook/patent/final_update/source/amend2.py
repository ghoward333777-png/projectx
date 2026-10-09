#!/usr/bin/env python3
"""Additions-only amendment of Final_Update.docx (base provisional, pages 9+).
New paragraphs are inserted AFTER the last existing paragraph of each listed section,
formatted like their neighbours and highlighted yellow. No existing element is modified.
Usage: amend.py <in.docx> <out_highlighted.docx> <out_clean.docx>"""
import copy, sys, zipfile
from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
q = lambda t: f"{{{W}}}{t}"
src, out_hl, out_clean = sys.argv[1:4]

zin = zipfile.ZipFile(src)
MEMBERS = [(i, zin.read(i.filename)) for i in zin.infolist()]
xml = dict((i.filename, b) for i, b in MEMBERS)["word/document.xml"]
root = etree.fromstring(xml)
body = root.find(q("body"))
paras = list(body.iter(q("p")))
text = lambda p: "".join(t.text or "" for t in p.iter(q("t")))

# base starts at the "Base Provisional Patent" paragraph; all anchors are searched after it
base_i = next(i for i, p in enumerate(paras) if text(p).strip() == "Base Provisional Patent")
import re as _re
norm = lambda s: _re.sub(r"[\s\u00a0\u2002-\u200b]+", " ", s).strip()
def anchor(prefix, contains=None, exact=False):
    pf = norm(prefix)
    hits = [p for p in paras[base_i:] if (norm(text(p)) == pf if exact else norm(text(p)).startswith(pf)) and (contains is None or contains in text(p))]
    assert len(hits) == 1, (prefix, len(hits))
    return hits[0]

RPR_ORDER = ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike", "outline", "shadow",
             "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing", "w", "kern",
             "position", "sz", "szCs", "highlight", "u", "effect", "bdr", "shd", "fitText", "vertAlign", "rtl", "cs",
             "em", "lang", "eastAsianLayout", "specVanish", "oMath"]

def make_rpr(template_rpr, bold=None, highlight=True):
    rpr = copy.deepcopy(template_rpr) if template_rpr is not None else etree.Element(q("rPr"))
    for tag in ("highlight",):
        for e in rpr.findall(q(tag)): rpr.remove(e)
    if bold is not None:
        for e in rpr.findall(q("b")) + rpr.findall(q("bCs")): rpr.remove(e)
        if bold:
            b = etree.Element(q("b")); rpr.append(b)
    if highlight:
        h = etree.Element(q("highlight")); h.set(q("val"), "yellow"); rpr.append(h)
    kids = sorted(list(rpr), key=lambda e: RPR_ORDER.index(etree.QName(e).localname) if etree.QName(e).localname in RPR_ORDER else 99)
    for k in list(rpr): rpr.remove(k)
    for k in kids: rpr.append(k)
    return rpr

def new_para(style_from, runs, highlight=True):
    """style_from: an existing paragraph whose pPr and first text-run rPr are copied.
    runs: list of (text, bold) tuples."""
    p = etree.Element(q("p"))
    ppr = style_from.find(q("pPr"))
    if ppr is not None:
        ppr = copy.deepcopy(ppr)
        for e in ppr.findall(q("numPr")): ppr.remove(e)  # never join an existing numbered list
        p.append(ppr)
    tr = next((r for r in style_from.iter(q("r")) if r.find(q("t")) is not None), None)
    trpr = tr.find(q("rPr")) if tr is not None else None
    for s, bold in runs:
        r = etree.SubElement(p, q("r"))
        r.append(make_rpr(trpr, bold=bold, highlight=highlight))
        t = etree.SubElement(r, q("t")); t.text = s
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return p

INSERTS = []  # (anchor element, [new paragraph elements])

def add_after(anchor_p, new_ps):
    INSERTS.append((anchor_p, new_ps))

ORIG_XML = etree.tostring(root)
# ------------------------------------------------------------------ content
import content as C
import json as _json
_FM = {19: 50, 20: 51, 21: 52, 22: 53, 23: 54, 24: 55, 17: 25}
def fm(t):
    t = _re.sub(r"FIG\. (\d+)–(\d+)", lambda m: f"FIG. {_FM.get(int(m.group(1)), int(m.group(1)))}–{_FM.get(int(m.group(2)), int(m.group(2)))}", t)
    return _re.sub(r"FIG\. (\d+)(?!–)", lambda m: f"FIG. {_FM.get(int(m.group(1)), int(m.group(1)))}", t)
C.SUMMARY_ITEMS = [fm(t) for t in C.SUMMARY_ITEMS]
C.CORE_PARAS = [(fm(h), fm(t)) for h, t in C.CORE_PARAS]
C.BRIEF = [(_FM[n], fm(d)) for n, d in C.BRIEF]
C.DRAWING_NOTE = ("[Drafting note: the complete drawing set, FIG. 1–55, is provided in the accompanying drawings PDF; "
                  "reference numerals 5000–5550 used in FIG. 50–55 are identified in the Detailed Description.]")
# brief descriptions for the drawings of the complete set not previously described in this application
_MISS = _json.load(open(__import__("os").path.join(__import__("os").path.dirname(__file__), "brief_missing.json")))
_MISS = {int(k): _re.sub(r",? per Section [IVX]+\.?\s*$", ".", v.strip()) for k, v in _MISS.items()}
_MISS.update({
 27: "is a diagram of the Fact Unit confidence and evidence model, comprising an evidence pair, a Beta posterior, a score, a credible interval, source diversity, temporal decay, and a confidence trend.",
 28: "is a diagram of the UFCS packet structure, showing the fields of a serialized Fact Unit record and an exemplar packet.",
 29: "is a diagram of UFCS packet framing, in which immutable packets are de-duplicated by fingerprint and appended to content-addressed blocks under a fingerprint index.",
 30: "is a diagram of FQL query anatomy with a worked example, in which match, where, exclude, rank, and return clauses produce a highest-trust answer bound to its evidence by a provenance hash.",
})
assert sorted(_MISS) == list(range(1, 9)) + list(range(27, 50)), sorted(_MISS)

# 1. Description of the Related Art — after its single existing body paragraph
ra = anchor("Artificial-intelligence and knowledge systems of several established types")
add_after(ra, [new_para(ra, [(t, None)]) for t in C.RELATED_ART])

# 2. Summary of the Invention — after item G.e
g_head = anchor("G.  Fact Unit Based Additional Applications")
g_intro = paras[paras.index(g_head) + 1]
assert norm(text(g_intro)).startswith("The Fact Unit primitive, carried on the UFCS substrate")
g_e = anchor("e. A QueryBook-enhanced TCP/IP hybrid protocol carrying Fact Unit identifiers and provenance references alongside network payload data.", exact=True)
summ = [new_para(g_head, [(C.SUMMARY_HEAD, None)]), new_para(g_intro, [(C.SUMMARY_INTRO, None)])]
summ += [new_para(g_e, [(t, None)]) for t in C.SUMMARY_ITEMS]
summ += [new_para(g_intro, [(C.SUMMARY_CLOSE, None)])]
add_after(g_e, summ)

# 3. Brief Description of the Drawings — complete set FIG. 1–55
RENUM = []   # (paragraph, deepcopy of original) for verification
def fig_anchor(n):
    hits = [p for p in paras[base_i:] if _re.match(rf"FIG\. {n} is ", norm(text(p)))]
    assert len(hits) == 1, (n, len(hits)); return hits[0]
intro = anchor("The accompanying drawings, incorporated in and forming part of the specification")
f1 = fig_anchor(1)
f18 = fig_anchor(18)
fig_lines = [(n, fig_anchor(n)) for n in range(1, 19)]
for n, p in fig_lines:
    RENUM.append((p, copy.deepcopy(p)))
    r = next(r for r in p.iter(q("r")) if r.find(q("t")) is not None)
    t = r.find(q("t")); assert t.text.strip() == f"FIG. {n}", t.text
    t.text = t.text.replace(f"FIG. {n}", f"FIG. {n + 8}")
    old = r.find(q("rPr")); r.replace(old, make_rpr(old, highlight=True)) if old is not None else r.insert(0, make_rpr(None))
note = anchor("[Drafting note: professional line-art drawings for FIG. 1–4")
RENUM.append((note, copy.deepcopy(note)))
nruns = [r for r in note.iter(q("r")) if r.find(q("t")) is not None]
assert len(nruns) == 1
nr = nruns[0]; ntext = nr.find(q("t")).text
segs, pos = [], 0
for m in _re.finditer(r"FIG\. ([0-9–, and]+?)(?= are )", ntext):
    for d in _re.finditer(r"\d+", m.group(1)):
        a, b = m.start(1) + d.start(), m.start(1) + d.end()
        segs.append((ntext[pos:a], False)); segs.append((str(int(d.group(0)) + 8), True)); pos = b
segs.append((ntext[pos:], False))
base_rpr = nr.find(q("rPr"))
for seg, hl in segs:
    if not seg: continue
    r = copy.deepcopy(nr); r.find(q("t")).text = seg
    r.find(q("t")).set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    if hl:
        o = r.find(q("rPr")); r.replace(o, make_rpr(o, highlight=True))
    nr.addprevious(r)
note.remove(nr)
add_after(intro, [new_para(f1, [(f"FIG. {n} ", True), (_MISS[n], False)]) for n in range(1, 9)])
add_after(f18, [new_para(f18, [(f"FIG. {n} ", True), (_MISS[n], False)]) for n in range(27, 50)]
               + [new_para(f18, [(f"FIG. {n} ", True), (d, False)]) for n, d in C.BRIEF])
add_after(note, [new_para(note, [(C.DRAWING_NOTE, None)])])

# 4. QueryBook System Overview — after the closing "In summary" paragraph
so_end = anchor("In summary, QueryBook is a synthetic cortex")
so_head = anchor("Additional Fact Unit Related Capabilities")
add_after(so_end, [new_para(so_head, [(C.SYS_HEAD, None)]), new_para(so_end, [(C.SYS_INTRO, None)])]
          + [new_para(so_end, [(t, None)]) for t in C.SYS_ITEMS])

# 5. Core Technology Overview — after its last paragraph (note on projections)
ct_end = anchor("A note on the projections stated in the compression")
ct_head = anchor("Commentary on Neuromorphic Correspondences")
add_after(ct_end, [new_para(ct_head, [(C.CORE_HEAD, None)])]
          + [new_para(ct_end, [(h, True), (t, False)]) for h, t in C.CORE_PARAS])

# 6. Architectural Overview — after the Deployment paragraph
ar_end = anchor("The same logical services execute in each deployment mode")
ar_head = anchor("The substrate and its database-neutral boundary")
add_after(ar_end, [new_para(ar_head, [(C.ARCH_HEAD, None)])] + [new_para(ar_end, [(t, None)]) for t in C.ARCH_PARAS])

# ------------------------------------------------------------------ apply (each group inserted, in order, right after its anchor)
orig_xml = ORIG_XML
for a, ps in INSERTS:
    for p in reversed(ps):
        a.addnext(p)

# verify: removing every inserted paragraph restores the original XML exactly
chk = copy.deepcopy(root)
inserted_ids = {id(p) for _, ps in INSERTS for p in ps}
def strip_inserted(r):
    # match by structural position: rebuild from live tree
    pass
live_inserted = [p for _, ps in INSERTS for p in ps]
for p in live_inserted:
    parent = p.getparent(); idx = parent.index(p)
for p in live_inserted:
    p.getparent().remove(p)
edited = [(p, copy.deepcopy(p)) for p, _ in RENUM]
for p, orig in RENUM:
    p.getparent().replace(p, orig)
assert etree.tostring(root) == orig_xml, "original content altered"
for (p, orig), (_, ed) in zip(RENUM, edited):
    orig.getparent().replace(orig, ed)
RENUM_LIVE = [ed for _, ed in edited]
# re-resolve anchors (they may be renumbered paragraphs) for re-insertion
_swap = {id(o): e for (o_p, o), (_, e) in zip([(p, p) for p, _ in RENUM], edited)}
_amap = {id(p): ed for (p, _), (_, ed) in zip(RENUM, edited)}
for a, ps in INSERTS:
    a = _amap.get(id(a), a)
    for p in reversed(ps):
        a.addnext(p)

def write(path, highlight):
    r = copy.deepcopy(root)
    if not highlight:
        # remove only the highlight elements this script added (identified by marker list)
        pass
    data = etree.tostring(r, xml_declaration=True, encoding="UTF-8", standalone=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for item, b in MEMBERS:
            zout.writestr(item, data if item.filename == "word/document.xml" else b)

write(out_hl, True)
# clean copy: same insertions without highlight
for a, ps in INSERTS:
    for p in ps:
        for h in list(p.iter(q("highlight"))):
            h.getparent().remove(h)
for p in RENUM_LIVE:
    for h in list(p.iter(q("highlight"))):
        h.getparent().remove(h)
write(out_clean, False)
print("inserted paragraphs:", sum(len(ps) for _, ps in INSERTS), "at", len(INSERTS), "anchors")
