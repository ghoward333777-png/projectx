#!/usr/bin/env python3
"""Composite Feature Registry v68 = v65 (all 293 rows, columns A–G untouched) + new features 294+,
drawing references (FIG. 1–55), status, prototype module, an Algorithms sheet, a Drawings sheet and a Summary.
Usage: build_v66.py <v65.xlsx> <final_figs.json> <out.xlsx>"""
import copy, json, re, sys
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
sys.path.insert(0, __import__("os").path.dirname(__file__))
import v66_data as D
import v68_data as D7

v65, figs_json, out = sys.argv[1:4]
wb = load_workbook(v65)
ws = wb["Feature Registry v65"]
ws.title = "Feature Registry v68"
FIGS = {int(k): v[1] for k, v in json.load(open(figs_json)).items()}

hdr = ws["A1"]; body = ws["B2"]
HF = copy.copy(hdr.font); HFILL = copy.copy(hdr.fill); HAL = copy.copy(hdr.alignment); HB = copy.copy(hdr.border)
BF = copy.copy(body.font); BAL = Alignment(wrap_text=True, vertical="top"); BB = copy.copy(body.border)
NEWFILL = PatternFill("solid", start_color="FFFF00")

def set_hdr(col, text, width):
    c = ws.cell(1, col, text); c.font, c.fill, c.alignment, c.border = HF, HFILL, HAL, HB
    ws.column_dimensions[get_column_letter(col)].width = width
set_hdr(8, "Drawing reference (FIG.)", 16)
set_hdr(9, "Status", 22)
set_hdr(10, "Prototype module", 20)
set_hdr(11, "Registry version added", 12)

# ------------------------------------------------ drawing references for v65 rows (by subject)
RULES = [
 (r"Prime Directive|Domain 0|Safety Substrate|Without-Information", 1),
 (r"FUID|semantic fingerprint|Polarity|N-ary|Fact Unit Language|Applicability Scope|Epistemic|Adjustment History|Integrity Chain", 2),
 (r"authority class|certifying authorit|trust ceiling|fact-certification|Certified Fact|Source Reliability", 3),
 (r"hypergraph|hyperedge|ontology mesh|Provenance Ledger|Fact Universe|Live Fact Graph", 4),
 (r"Tour and Exhibition|Instructor-Created Tours|Immersive 3D|waypoint", 5),
 (r"QBQL|Structured Query|FQL|Internal Fact Query", 6),
 (r"Contradiction|Forensic Analysis of External", 7),
 (r"federat", 8),
 (r"Erasure|key destruction|Key Custody|zero-knowledge", 9),
 (r"Deployment|Topolog|Offline Synchronization|Hybrid and Edge|Edge Deployment", 12),
 (r"Adaptive Response|Generation Directive|Expressive Register|Surface Realization|Vocabulary", 13),
 (r"Agent Definition|Agent Capability|Agent Lifecycle|Agent Decision|Advisory Distinguished|Autonomous Agent Connector", 14),
 (r"Multilingual|Translation|Parallel Multilingual", 15),
 (r"Coloriz|VCUM|Upscal|Restoration|Compression", 16),
 (r"Semantic Transport", 17),
 (r"Attractor|Convergence|Hopfield|Neuromorphic|Capacity", 18),
 (r"Confidence|Evidence Pair|Calibration|Temporal Decay|Diversity", 19),
 (r"Compact Encoding|Record-Fused|Canonical Encoding", 20),
 (r"Opaque-Blob|Deduplicat|Content-Addressed", 21),
 (r"Developmental", 25),
 (r"Voice Signal|Affective", 37),
 (r"Standard Q&A|Natural Language Interaction", 48),
 (r"Public API Layer", 49),
]
for r in range(2, ws.max_row + 1):
    name = str(ws.cell(r, 2).value or ""); func = str(ws.cell(r, 5).value or "")
    hits = []
    for pat, f in RULES:
        bp = r"\b(?:" + pat + r")"
        if re.search(bp, name, re.I) or (len(hits) < 1 and re.search(bp, func[:160], re.I)):
            if f not in hits: hits.append(f)
    hits = sorted(hits)[:3]
    for col, val in ((8, ", ".join(map(str, hits)) if hits else None), (9, None), (10, None), (11, "v65 or earlier")):
        c = ws.cell(r, col, val); c.font, c.alignment, c.border = BF, BAL, BB

# ------------------------------------------------ new rows
start = ws.max_row + 1
first_no = int(ws.cell(ws.max_row, 1).value) + 1
ROWS = [(t, D.C, 'v66') for t in D.NEW] + [(t, D7.C, 'v68') for t in D7.NEW]
for k, ((name, dom, figs, surface, role, func, rule, wexpr, status, module), CIT, VER) in enumerate(ROWS):
    r = start + k; no = first_no + k
    cite = f"{CIT} · FIG. " + ", ".join(map(str, figs))
    vals = [no, name, dom, cite, f"{surface}{cite}{role} {func}", rule, wexpr,
            ", ".join(map(str, figs)), status, module or None, VER]
    for col, v in enumerate(vals, 1):
        c = ws.cell(r, col, v); c.font, c.alignment, c.border = BF, BAL, BB
        c.fill = NEWFILL
ws.auto_filter.ref = f"A1:K{ws.max_row}"
LAST = ws.max_row
NEW_N = len(D.NEW); NEW7 = len(D7.NEW)

# ------------------------------------------------ Algorithms sheet
wa = wb.create_sheet("Algorithms (v68)")
heads = [("ID", 9), ("Algorithm", 30), ("Features (registry)", 34), ("Drawing (FIG.)", 11), ("Inputs", 26),
         ("Procedure", 90), ("Output", 24), ("Deterministic", 12), ("Prototype module", 20)]
for i, (h, w) in enumerate(heads, 1):
    c = wa.cell(1, i, h); c.font, c.fill, c.alignment, c.border = HF, HFILL, HAL, HB
    wa.column_dimensions[get_column_letter(i)].width = w
for j, (aid, name, feats, figs, inp, proc, outp, det, mod) in enumerate(D.ALGOS + D7.ALGOS, 2):
    for i, v in enumerate([aid, name, feats, ", ".join(map(str, figs)), inp, proc, outp, det, mod], 1):
        c = wa.cell(j, i, v); c.font, c.alignment, c.border = BF, BAL, BB
wa.freeze_panes = "A2"; wa.auto_filter.ref = f"A1:I{wa.max_row}"

# ------------------------------------------------ Drawings sheet (FIG. 1–55)
wd = wb.create_sheet("Drawings FIG 1-55")
dh = [("FIG.", 7), ("Title", 62), ("Group", 34), ("Features referencing (count)", 14), ("Algorithms referencing (count)", 14)]
for i, (h, w) in enumerate(dh, 1):
    c = wd.cell(1, i, h); c.font, c.fill, c.alignment, c.border = HF, HFILL, HAL, HB
    wd.column_dimensions[get_column_letter(i)].width = w
def group(n):
    return ("Core platform" if n <= 22 else "Language & speech subsystem" if n <= 32 else
            "Identity, audit, interpretation, lecture" if n <= 40 else "Further embodiments" if n <= 49 else "Agent-era extensions")
REG = "'Feature Registry v68'"
for n in range(1, 56):
    r = n + 1
    vals = [n, FIGS[n], group(n),
            f'=SUMPRODUCT(--ISNUMBER(SEARCH(", "&A{r}&",",", "&{REG}!$H$2:$H${LAST}&",")))',
            f"=SUMPRODUCT(--ISNUMBER(SEARCH(\", \"&A{r}&\",\",\", \"&'Algorithms (v68)'!$D$2:$D${wa.max_row}&\",\")))"]
    for i, v in enumerate(vals, 1):
        c = wd.cell(r, i, v); c.font, c.alignment, c.border = BF, BAL, BB
wd.freeze_panes = "A2"

# ------------------------------------------------ Summary sheet
sm = wb.create_sheet("Summary v68", 0)
sm["A1"] = "QueryBook Composite Feature Registry v68"; sm["A1"].font = Font(name=BF.name, bold=True, size=14)
sm["A2"] = "Rows highlighted yellow on the Feature Registry sheet were added in v66 or v68 (column K). All v65 rows (columns A–G) and all v66 rows are unchanged."
sm["A2"].font = Font(name=BF.name, italic=True, size=10, color="595959")
rows = [("Total features", f"=COUNTA({REG}!A2:A{LAST})"),
        ("Features carried from v65", f'=COUNTIF({REG}!K2:K{LAST},"v65 or earlier")'),
        ("Features added in v66", f'=COUNTIF({REG}!K2:K{LAST},"v66")'),
        ("Features added in v68 (support for agent-wrapper services)", f'=COUNTIF({REG}!K2:K{LAST},"v68")'),
        ("Features with a drawing reference", f'=COUNTIF({REG}!H2:H{LAST},"?*")'),
        ("Features with a worked expression", f'=SUMPRODUCT(--({REG}!G2:G{LAST}<>""))'),
        ("New features built in prototype v9.64", f'=COUNTIF({REG}!I2:I{LAST},"Built — prototype v9.64")'),
        ("New features built in laboratory prototype", f'=COUNTIF({REG}!I2:I{LAST},"Built — laboratory prototype")'),
        ("New features specified (not yet built)", f'=COUNTIF({REG}!I2:I{LAST},"Specified")'),
        ("Algorithms documented", f"=COUNTA('Algorithms (v68)'!A2:A{wa.max_row})"),
        ("Drawings (FIG. 1–55)", "=COUNTA('Drawings FIG 1-55'!A2:A56)"),
        ("Drawings referenced by at least one feature", "=COUNTIF('Drawings FIG 1-55'!D2:D56,\">0\")")]
sm["A4"], sm["B4"] = "Measure", "Value"
for c in (sm["A4"], sm["B4"]): c.font, c.fill, c.border = HF, HFILL, HB
for i, (a, f) in enumerate(rows, 5):
    sm.cell(i, 1, a).font = BF; sm.cell(i, 2, f).font = BF
r0 = 5 + len(rows) + 1
sm.cell(r0, 1, "Features by domain").font = Font(name=BF.name, bold=True)
sm.cell(r0, 2, "All").font = Font(name=BF.name, bold=True); sm.cell(r0, 3, "New in v66").font = Font(name=BF.name, bold=True); sm.cell(r0, 4, "New in v68").font = Font(name=BF.name, bold=True)
doms = sorted({str(ws.cell(r, 3).value) for r in range(2, LAST + 1)})
for i, d in enumerate(doms, r0 + 1):
    sm.cell(i, 1, d).font = BF
    sm.cell(i, 2, f'=COUNTIF({REG}!C2:C{LAST},A{i})').font = BF
    sm.cell(i, 3, f'=COUNTIFS({REG}!C2:C{LAST},A{i},{REG}!K2:K{LAST},"v66")').font = BF
    sm.cell(i, 4, f'=COUNTIFS({REG}!C2:C{LAST},A{i},{REG}!K2:K{LAST},"v68")').font = BF
sm.column_dimensions["A"].width = 48; sm.column_dimensions["B"].width = 12; sm.column_dimensions["C"].width = 12

# ------------------------------------------------ Registry Record (append)
rec = wb["Registry Record"]
rec["A1"] = rec["A1"].value  # unchanged title line kept; v66 lines appended below
lines = [
 "",
 "QueryBook Composite Feature Registry v66",
 f"Assembled October 9, 2026, from Composite Registry v65 plus the features disclosed in Provisional Patent Application of October 9, 2026 and built in QueryBook prototype v9.64.",
 f"Features: {first_no - 1 + NEW_N}. Rows 1–{first_no - 1} carried from v65 unchanged (columns A–G). Rows {first_no}–{first_no + NEW_N - 1} added in v66: Open Claw ingestion; on-chain certification; agent protection and deception; tamper-evident security record; agent interoperability (MCP / OpenClaw); framed hybrid transport; record-grounded colorization; the security architecture, honeypot saturation, worm defense, agent passport, post-quantum signatures and default-on-deny approval described in the application; and the October embodiments (pronunciation, speech QC, LIL, UIAS, PIL, Lecture Query, multilingual acquisition, dialects, scene director and reconstructor, key-safe mediation, editions, version-independent store, cited Q&A, deployment surfaces).",
 "New columns: H Drawing reference (FIG. 1–55 of the synchronized drawing set); I Status and J Prototype module (new rows); K Registry version added. Drawing references for v65 rows are assigned by subject and should be confirmed by counsel.",
 "New sheets: Algorithms (v66) — 13 documented algorithms with inputs, procedure, output and module; Drawings FIG 1-55 — each figure with the count of features and algorithms referencing it; Summary v66.",
 "Additive covenant: no feature removed; no v65 cell in columns A–G altered. Claims: 354 — unchanged.",
]
lines += [
 "",
 "QueryBook Composite Feature Registry v68",
 "Assembled October 9, 2026, from Composite Registry v66. Verified Agent Transport (VAT), the AI agent wrapper service, is registered separately in the VAT Feature Registry and is not listed here; registry v67, which listed VAT features, is superseded by this edition.",
 f"Features: {first_no - 1 + NEW_N + NEW7}. Rows 1–{first_no + NEW_N - 1} carried from v66 unchanged. Rows {first_no + NEW_N}–{first_no + NEW_N + NEW7 - 1} added in v68: QueryBook-side support for external agent-wrapper services — claim verification endpoint; contradiction query template; fingerprint-only verification; external triple extraction; assertion-type labels; signed verdicts and published verifier key; frame message-type extension range; extension flag and reserved-field profile; Python frame codec; QUIC stream binding; fingerprint set reconciliation; external append to the security log; session-range Merkle root; third-party session certificate type; principal evidence pair; signed policy bundle export; MCP pre-/post-call hooks; tool result record hash; wrapper service registration.",
 "Status of all v68 rows: Specified — not yet built; modules are the existing prototype modules to be extended (marked planned) or a new codec (qb_frames).",
 f"Sheets: Feature Registry v68, Algorithms (v68) — {len(D.ALGOS) + len(D7.ALGOS)} algorithms (ALG-14 to ALG-19 are support algorithms), Drawings FIG 1-55, Summary v68. Drawing references cite FIG. 1–55 only.",
 "Additive covenant: no feature removed relative to v66; no v65 cell in columns A–G altered; no v66 row altered.",
]
for l in lines:
    rec.append([l])
rec.column_dimensions["A"].width = 160
for row in rec.iter_rows():
    for c in row: c.alignment = Alignment(wrap_text=True, vertical="top")

wb.active = 0
wb.save(out)
print("rows:", LAST - 1, "new66:", NEW_N, "new67:", NEW7, "first new no.:", first_no)
