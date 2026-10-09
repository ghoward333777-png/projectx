#!/usr/bin/env python3
"""Synchronize Prov_Patent_Oct9.docx with the FIG. 1–55 drawing set.
Changes are limited to the drawings and their descriptions:
  1. the Brief Description placeholder is replaced by descriptions of FIG. 1–55;
  2. figure numbers 19–24 cited for the new features are corrected to 50–55;
  3. "See FIG. …" references are appended to Detailed Description paragraphs that discuss a figure's subject;
  4. one paragraph references the figures whose subject has no discussion elsewhere.
All new or changed text is highlighted yellow (clean copy: no new highlight).
Usage: sync.py <in.docx> <final_update.docx> <fu_dir> <out_hl.docx> <out_clean.docx>"""
import copy, json, re, sys, zipfile
from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
q = lambda t: f"{{{W}}}{t}"
XS = "{http://www.w3.org/XML/1998/namespace}space"
src, fu_doc, fu_dir, out_hl, out_clean = sys.argv[1:6]
sys.path.insert(0, fu_dir)

zin = zipfile.ZipFile(src)
MEMBERS = [(i, zin.read(i.filename)) for i in zin.infolist()]
root = etree.fromstring(dict((i.filename, b) for i, b in MEMBERS)["word/document.xml"])
ORIG = etree.tostring(root)
body = root.find(q("body"))
P = body.findall(q("p"))
text = lambda p: "".join(t.text or "" for t in p.iter(q("t")))
NEW_HL = []   # highlight elements added by this script (removed for the clean copy)

RPR_ORDER = ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike", "outline", "shadow",
             "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing", "w", "kern",
             "position", "sz", "szCs", "highlight", "u", "effect", "bdr", "shd", "fitText", "vertAlign", "rtl", "cs",
             "em", "lang", "eastAsianLayout", "specVanish", "oMath"]
def hl_rpr(rpr, bold=None):
    rpr = copy.deepcopy(rpr) if rpr is not None else etree.Element(q("rPr"))
    prior = [copy.deepcopy(e) for e in rpr.findall(q("highlight")) + rpr.findall(q("shd"))]
    for tag in ("highlight", "shd"):
        for e in rpr.findall(q(tag)): rpr.remove(e)
    if bold is not None:
        for e in rpr.findall(q("b")) + rpr.findall(q("bCs")): rpr.remove(e)
        if bold: rpr.append(etree.Element(q("b")))
    h = etree.Element(q("highlight")); h.set(q("val"), "yellow"); rpr.append(h); NEW_HL.append((h, prior))
    kids = sorted(rpr, key=lambda e: RPR_ORDER.index(etree.QName(e).localname) if etree.QName(e).localname in RPR_ORDER else 99)
    for k in list(rpr): rpr.remove(k)
    for k in kids: rpr.append(k)
    return rpr
def run(s, rpr):
    r = etree.Element(q("r")); r.append(rpr); t = etree.SubElement(r, q("t")); t.text = s; t.set(XS, "preserve"); return r
def expect(i, prefix):
    assert text(P[i]).strip().startswith(prefix), (i, text(P[i])[:80])
    return P[i]

# ---------------------------------------------------------------- sources for the descriptions
fu = zipfile.ZipFile(fu_doc); fr = etree.fromstring(fu.read("word/document.xml"))
FT = [text(p) for p in fr.find(q("body")).findall(q("p"))]
INTRO = next(t for t in FT if t.startswith("The accompanying drawings, incorporated in and forming part"))
DESC = {}
for t in FT:
    m = re.match(r"FIG\. (\d+) (is .*)$", t.strip())
    if m and int(m.group(1)) <= 18 and int(m.group(1)) not in DESC: DESC[int(m.group(1))] = m.group(2)
assert sorted(DESC) == list(range(1, 19))
old = {int(k): re.sub(r",? per Section [IVX]+\.?\s*$", ".", v.strip()) for k, v in json.load(open(f"{fu_dir}/brief_missing.json")).items()}
DESC.update({
 19: "is a diagram of the Fact Unit confidence and evidence model, comprising an evidence pair, a Beta posterior, a score, a credible interval, source diversity, temporal decay, and a confidence trend.",
 20: "is a diagram of the UFCS packet structure, showing the fields of a serialized Fact Unit record and an exemplar packet.",
 21: "is a diagram of UFCS packet framing, in which immutable packets are de-duplicated by fingerprint and appended to content-addressed blocks under a fingerprint index.",
 22: "is a diagram of FQL query anatomy with a worked example, in which match, where, exclude, rank, and return clauses produce a highest-trust answer bound to its evidence by a provenance hash.",
})
for o in range(1, 9): DESC[o + 22] = old[o]
for o in range(31, 50): DESC[o] = old[o]
import content as C
FM = {19: 50, 20: 51, 21: 52, 22: 53, 23: 54, 24: 55}
for n, d in C.BRIEF:
    DESC[FM[n]] = re.sub(r"FIG\. (\d+)", lambda m: f"FIG. {FM.get(int(m.group(1)), int(m.group(1)))}", d)
assert sorted(DESC) == list(range(1, 56))
NOTE = ("[Drafting note: the complete drawing set, FIG. 1–55, is provided in the accompanying drawings PDF, one figure per sheet; "
        "reference numerals used in the drawings are identified in the Detailed Description.]")

# ---------------------------------------------------------------- 1. Brief Description: replace placeholder
expect(119, "BRIEF DESCRIPTION OF THE DRAWINGS")
ph = expect(120, "Insert Descriptions Here")
base_rpr = etree.Element(q("rPr"))
f = etree.SubElement(base_rpr, q("rFonts")); f.set(q("ascii"), "Times New Roman"); f.set(q("hAnsi"), "Times New Roman")
for tag in ("sz", "szCs"):
    e = etree.SubElement(base_rpr, q(tag)); e.set(q("val"), "24")
def para(runs, indent=True, italic=False):
    p = etree.Element(q("p")); ppr = etree.SubElement(p, q("pPr"))
    st = etree.SubElement(ppr, q("pStyle")); st.set(q("val"), "Normal")
    sp = etree.SubElement(ppr, q("spacing")); sp.set(q("before"), "0"); sp.set(q("after"), "120")
    if indent:
        ind = etree.SubElement(ppr, q("ind")); ind.set(q("firstLine"), "432")
    jc = etree.SubElement(ppr, q("jc")); jc.set(q("val"), "both")
    for s, bold in runs:
        r = copy.deepcopy(base_rpr)
        if italic: r.insert(2, etree.Element(q("i")))
        p.append(run(s, hl_rpr(r, bold)))
    return p
brief = [para([(INTRO, False)])] + [para([(f"FIG. {n} ", True), (DESC[n], False)]) for n in range(1, 56)] + [para([(NOTE, False)], indent=False, italic=True)]
for p in reversed(brief): ph.addnext(p)
body.remove(ph)

# ---------------------------------------------------------------- 2. correct FIG. 19–24 citations to FIG. 50–55
FIXED = []
def fix_refs(p):
    changed = False
    for r in list(p.iter(q("r"))):
        t = r.find(q("t"))
        if t is None or not t.text or not re.search(r"FIG\. (19|2[0-4])\b", t.text): continue
        segs, pos = [], 0
        for m in re.finditer(r"(?<=FIG\. )(19|2[0-4])\b|(?<=FIG\. 19–)(24)\b", t.text):
            segs.append((t.text[pos:m.start()], False)); segs.append((str(FM[int(m.group(0))]), True)); pos = m.end()
        segs.append((t.text[pos:], False))
        rpr = r.find(q("rPr"))
        for s, hl in segs:
            if not s: continue
            nr = copy.deepcopy(r); nt = nr.find(q("t")); nt.text = s; nt.set(XS, "preserve")
            if hl:
                o = nr.find(q("rPr"))
                if o is not None: nr.replace(o, hl_rpr(o))
                else: nr.insert(0, hl_rpr(None))
            r.addprevious(nr)
        r.getparent().remove(r); changed = True
    return changed
for i, p in enumerate(P):
    if p is ph: continue
    before = text(p)
    if fix_refs(p): FIXED.append((i, before, text(p)))

# ---------------------------------------------------------------- 3. "See FIG." references appended to discussing paragraphs
REFS = {
 128: ("At its foundation, QueryBook uses Fact Units", [2, 19]),
 130: ("QueryBook’s intelligence emerges from a neuromorphic", [18]),
 134: ("QueryBook’s range of applications begins", [48, 49]),
 138: ("Search Engine:", [49]),
 146: ("In addition QueryBook can provide controlled", [14]),
 148: ("Cybersecurity and Defense", [10, 11, 52]),
 150: ("The Prime Directive is the governing", [1]),
 154: ("QueryBook is highly flexible in deployment", [12, 49]),
 190: ("a. Deterministic multi-language regeneration", [15]),
 192: ("b. Semantic compression and expansion", [16]),
 194: ("c. Deterministic video colorization", [16]),
 196: ("d. Three-dimensional and VR presentation", [5]),
 198: ("e. A QueryBook-enhanced TCP/IP hybrid protocol", [17, 55]),
 204: ("1. Any-format ingestion", [50]), 205: ("2. Certificates anyone can check", [51]),
 206: ("3. Protection for QueryBook’s agents", [52]), 207: ("4. A security log", [53]),
 208: ("5. Connection to outside AI agents", [54]), 209: ("6. Faster, provenance-carrying transport", [55]),
 215: ("At the core of QueryBook is the Fact Unit", [2, 19]),
 216: ("The Fact Unit does not stand alone", [3, 4, 6, 20, 21, 22]),
 217: ("Because meaning is stored below language", [15, 16, 17]),
 220: ("Unlike transformer models that grow unstable", [18]),
 223: ("QueryBook is structurally constrained against causing harm", [1]),
 226: ("QueryBook binds every answer", [22]),
 227: ("Ungrounded output is structurally impossible", [7, 12, 13]),
 231: ("Fact Units contain atomic meaning", [19]),
 241: ("QueryBook advances beyond conceptual intelligence", [18]),
 257: ("Encryption in QueryBook is architectural", [9]),
 258: ("Beyond encryption, QueryBook incorporates", [10, 11]),
 260: ("QueryBook’s Brain-Grade Knowledge Engine", [13, 48]),
 263: ("QueryBook supports a wide range of applications", [48, 49]),
 264: ("Eight: It can be used for LLM Integration", [7, 49]),
 266: ("QueryBook enables deterministic language translation", [15]),
 267: ("QueryBook enables audio and video compression", [16]),
 272: ("Four media transformations are specified", [16]),
 274: ("Records carrying spatial anchors support presentation", [5]),
 278: ("Every connection to a system outside the boundary", [44, 54]),
 283: ("QueryBook’s defined agents differ fundamentally", [14]),
 317: ("The Prime Directive is Domain 0", [1]),
 319: ("Referring generally to the drawings", [1]),
 322: ("The fundamental unit of knowledge is a Fact Unit", [2, 19]),
 326: ("Fact Units are held in a knowledge substrate", [4, 20, 21]),
 330: ("The horizontal domains are grouped as follows", [1]),
 337: ("Retrieved candidate Fact Units are stabilized", [18]),
 340: ("The same logical services execute in each deployment mode", [12, 46, 49]),
 344: ("1.Integrity auditing and external mediation", [35, 36, 44]),
 345: ("2. Lecture Query, PIL, and LIL", [33, 34, 37, 38, 39, 40]),
 346: ("3. The Scene Director and Scene Reconstructor", [43, 45]),
 347: ("4. Two cross-cutting additions", [46, 47]),
 348: ("5. Open Claw ingestion", [50]),
 349: ("6. The Agent Gateway, deception check", [52, 53]),
 350: ("8. External agents connected through", [54]),
}
def figlist(ns):
    rs = []
    for n in sorted(set(ns)):
        if rs and n == rs[-1][1] + 1: rs[-1][1] = n
        else: rs.append([n, n])
    parts = [f"FIG. {a}" if a == b else (f"FIG. {a} and FIG. {b}" if b == a + 1 else f"FIG. {a}–FIG. {b}") for a, b in rs]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
APPENDED = []
for i, (prefix, figs) in REFS.items():
    p = expect(i, prefix)
    last = [r for r in p.iter(q("r")) if r.find(q("t")) is not None][-1]
    t = text(p).rstrip()
    s = f" See {figlist(figs)}." if t.endswith((".", ":", ";")) else f" (see {figlist(figs)})."
    if t.endswith((":", ";")): s = f" (See {figlist(figs)}.)"
    last.addnext(run(s, hl_rpr(last.find(q("rPr")))))
    APPENDED.append(i)

# ---------------------------------------------------------------- 4. remaining figures (no discussion elsewhere)
covered = {n for _, fs in REFS.values() for n in fs}
remaining = sorted(set(range(1, 56)) - covered)
REM = ("Referring to the remaining drawings: FIG. 8 shows federation, in which a certified envelope crossing a domain boundary is "
       "re-validated on the receiving side before admission. FIG. 23–FIG. 32 show the language and speech subsystem: the overall "
       "Language Expression Layer architecture (FIG. 23), the Sub-Language Priming Layer (FIG. 24), the developmental learning "
       "sequence and one-way Transition Gate (FIG. 25), multilingual delta acquisition (FIG. 26), the speech output pipeline "
       "(FIG. 27), co-grounded integration with FQL and UFCS (FIG. 28), a reduced-to-practice Language Lab embodiment and its "
       "deterministic semantic grounding (FIG. 29 and FIG. 30), and advanced multilingual pronunciation with its quality-control "
       "battery (FIG. 31 and FIG. 32). FIG. 41 shows deterministic multilingual acquisition without a generative model, and "
       "FIG. 42 shows Dialect Parameter Clusters, which modulate expression only.")
in_rem = {int(x) for x in re.findall(r"FIG\. (\d+)", REM)} | set(range(23, 33))
assert set(remaining) <= in_rem, sorted(set(remaining) - in_rem)
anchor = expect(350, "8. External agents connected through")
rp = etree.Element(q("p")); rp.append(copy.deepcopy(expect(340, "The same logical services").find(q("pPr"))))
rp.append(run(REM, hl_rpr(None)))
anchor.addnext(rp)

# ---------------------------------------------------------------- verification
new_xml = etree.tostring(root)
o_body = etree.fromstring(ORIG).find(q("body")).findall(q("p"))
n_body = body.findall(q("p"))
o_bytes = [etree.tostring(p) for p in o_body]
changed_idx = {120} | {i for i, _, _ in FIXED} | set(APPENDED)
n_set = {}
for p in n_body: n_set.setdefault(etree.tostring(p), 0); n_set[etree.tostring(p)] += 1
unchanged_ok = all(o_bytes[i] in n_set for i in range(len(o_bytes)) if i not in changed_idx)
nt = [text(p) for p in n_body]
for i, b, a in FIXED:
    assert a == re.sub(r"(?<=FIG\. )(19|2[0-4])\b|(?<=FIG\. 19–)(24)\b", lambda m: str(FM[int(m.group(0))]), b), i
for i in APPENDED:
    ot = text(o_body[i]); assert any(t.startswith(ot) and len(t) > len(ot) for t in nt), i
print("unchanged paragraphs byte-identical:", unchanged_ok, "| changed:", len(changed_idx),
      "(placeholder 1, corrected", len(FIXED), ", references appended", len(APPENDED), ")")
refs_all = sorted({int(x) for t in nt for x in re.findall(r"FIG\. (\d+)", t)})
print("figure numbers cited:", refs_all[0], "…", refs_all[-1], "| missing:", sorted(set(range(1, 56)) - set(refs_all)))

def write(path):
    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for item, b in MEMBERS:
            z.writestr(item, data if item.filename == "word/document.xml" else b)
write(out_hl)
for h, prior in NEW_HL:
    par = h.getparent()
    if par is None: continue
    par.remove(h)
    for e in prior: par.append(e)          # restore the author's own highlight/shading where the run had one
    kids = sorted(par, key=lambda e: RPR_ORDER.index(etree.QName(e).localname) if etree.QName(e).localname in RPR_ORDER else 99)
    for k in list(par): par.remove(k)
    for k in kids: par.append(k)
write(out_clean)
