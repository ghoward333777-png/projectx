#!/usr/bin/env python3
"""Composite Feature Registry v72 = v71 (every row and sheet value unchanged) + the four-state Fact Unit: features 408-422
(FIG. 60 numerals 6010-6080, FIG. 61 numerals 6110-6170), algorithms ALG-26 to ALG-29, drawings FIG. 60-61, updated summary and
record, and a "Fact Unit changes" sheet. Yellow: the v72 rows, and - fill only, no value changed - the earlier Fact Unit design
rows they build on. Wording from docs/source/fsu_text.py. Usage: build_v72.py <v71.xlsx> <out.xlsx>"""
import copy, os, re, sys
from openpyxl import load_workbook
from openpyxl.styles import Alignment, PatternFill
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "docs", "source"))
import fsu_text as K

src, out = sys.argv[1:3]
wb = load_workbook(src)
ref = load_workbook(src)                      # untouched copy for the additive check
ws = wb["Feature Registry v71"]; ws.title = "Feature Registry v72"
wa = wb["Algorithms (v71)"]; wa.title = "Algorithms (v72)"
wd = wb["Drawings FIG 1-59"]; wd.title = "Drawings FIG 1-61"
sm = wb["Summary v71"]; sm.title = "Summary v72"
REG = "'Feature Registry v72'"
NEWFILL = PatternFill("solid", start_color="FFFF00")

def style_like(src_cell, c, fill=None):
    c.font, c.border = copy.copy(src_cell.font), copy.copy(src_cell.border)
    c.alignment = Alignment(wrap_text=True, vertical="top")
    if fill: c.fill = fill

# ------------------------------------------------ new feature rows
OLD_LAST = ws.max_row
tpl = ws.cell(OLD_LAST, 2)
first_no = int(ws.cell(OLD_LAST, 1).value) + 1
for k, ((name, dom, figs, surface, role, func, rule, wexpr, status, module), n) in enumerate(zip(K.NEW, K.NUMERAL)):
    r = OLD_LAST + 1 + k; no = first_no + k
    cite = f"{K.CITE} · FIG. " + ", ".join(map(str, figs))
    func = f"{func[:-1]} ({n})."
    vals = [no, name, dom, cite, f"{surface}{cite}{role} {func}", rule, wexpr, ", ".join(map(str, figs)), status, module, "v72"]
    for col, v in enumerate(vals, 1):
        style_like(tpl, ws.cell(r, col, v), NEWFILL)
LAST = ws.max_row
ws.auto_filter.ref = f"A1:K{LAST}"

# ------------------------------------------------ algorithms
OLD_ALAST = wa.max_row
atpl = wa.cell(wa.max_row, 2)
for aid, name, feats, figs, inp, proc, outp, det, mod in K.ALGOS:
    r = wa.max_row + 1
    for i, v in enumerate([aid, name, feats, ", ".join(map(str, figs)), inp, proc, outp, det, mod], 1):
        style_like(atpl, wa.cell(r, i, v))
wa.auto_filter.ref = f"A1:I{wa.max_row}"
ALAST = wa.max_row

# ------------------------------------------------ drawings: FIG. 58-59, and every formula re-pointed at the renamed sheets
OLD_DLAST = wd.max_row
dtpl = wd.cell(wd.max_row, 2)
for fig, title, area in ((K.FIG_S, K.FIG_S_TITLE, "Fact Unit truth state"), (K.FIG_I, K.FIG_I_TITLE, "Fact Unit identity and context")):
    r = wd.max_row + 1
    for i, v in enumerate([fig, title, area], 1):
        style_like(dtpl, wd.cell(r, i, v))
DLAST = wd.max_row
for rr in range(2, DLAST + 1):
    wd.cell(rr, 4).value = f'=SUMPRODUCT(--ISNUMBER(SEARCH(", "&A{rr}&",",", "&{REG}!$H$2:$H${LAST}&",")))'
    wd.cell(rr, 5).value = f"=SUMPRODUCT(--ISNUMBER(SEARCH(\", \"&A{rr}&\",\",\", \"&'Algorithms (v72)'!$D$2:$D${ALAST}&\",\")))"
    if rr > OLD_DLAST:
        for c in (4, 5): style_like(dtpl, wd.cell(rr, c))

# ------------------------------------------------ summary
BF = sm["A5"].font
sm["A1"] = "QueryBook Composite Feature Registry v72"
sm["A2"] = ("Rows highlighted yellow on the Feature Registry sheet were added in v66, v69, v70, v71 or v72 (column K), or are earlier Fact Unit "
            "design features that the four-state Fact Unit of v72 builds on (listed on the Fact Unit changes sheet; fill only, no value changed). "
            "Verified Agent Transport is supported, not included: see the Supported External Services sheet. All v65 rows (columns A–G) and all "
            "v66, v69, v70 and v71 rows are unchanged.")
for row in sm.iter_rows():
    for c in row:
        if isinstance(c.value, str) and c.value.startswith("="):
            c.value = (c.value.replace("'Feature Registry v71'", REG).replace(f"2:A{OLD_LAST}", f"2:A{LAST}")
                       .replace(f"2:C{OLD_LAST}", f"2:C{LAST}").replace(f"2:G{OLD_LAST}", f"2:G{LAST}").replace(f"2:H{OLD_LAST}", f"2:H{LAST}")
                       .replace(f"2:I{OLD_LAST}", f"2:I{LAST}").replace(f"2:K{OLD_LAST}", f"2:K{LAST}")
                       .replace("'Algorithms (v71)'", "'Algorithms (v72)'").replace(f"A2:A{OLD_ALAST}", f"A2:A{ALAST}")
                       .replace("'Drawings FIG 1-59'", "'Drawings FIG 1-61'").replace(f"A2:A{OLD_DLAST}", f"A2:A{DLAST}")
                       .replace(f"D2:D{OLD_DLAST}", f"D2:D{DLAST}"))
        elif c.value == "Drawings (FIG. 1–59)":
            c.value = "Drawings (FIG. 1–61)"
# rows for v71 after the v70 row, by shifting the rows below them
vrow = next(r for r in range(1, sm.max_row + 1) if str(sm.cell(r, 1).value).startswith("v71 features built"))
sm.insert_rows(vrow + 1, 2)
sm.cell(vrow + 1, 1, "Features added in v72 (four-state Fact Unit, FIG. 60–61)").font = copy.copy(BF)
sm.cell(vrow + 1, 2, f'=COUNTIF({REG}!K2:K{LAST},"v72")').font = copy.copy(BF)
sm.cell(vrow + 2, 1, "v72 features built (the applications, engine 1.56)").font = copy.copy(BF)
sm.cell(vrow + 2, 2, f'=COUNTIFS({REG}!K2:K{LAST},"v72",{REG}!I2:I{LAST},"Built*")').font = copy.copy(BF)
hdr = next(r for r in range(1, sm.max_row + 1) if sm.cell(r, 1).value == "Features by domain")
sm.cell(hdr, 7, "New in v72").font = copy.copy(sm.cell(hdr, 6).font)
r = hdr + 1
while sm.cell(r, 1).value:
    for c in (2, 3, 4, 5, 6):                                # insert_rows does not move formula references: re-point A{r}
        v = sm.cell(r, c).value
        if isinstance(v, str):
            sm.cell(r, c).value = re.sub(r"\bA\d+\b", f"A{r}", v)
    sm.cell(r, 7, f'=COUNTIFS({REG}!C2:C{LAST},A{r},{REG}!K2:K{LAST},"v72")').font = copy.copy(BF)
    r += 1
sm.column_dimensions["G"].width = 12

# ------------------------------------------------ registry record
rec = wb["Registry Record"]
for l in ["",
          "QueryBook Composite Feature Registry v72",
          f"Assembled {K.DATE} from Composite Registry v71 and synchronized with the provisional application as updated with the "
          f"four-state Fact Unit (FIG. 60–61; claims 375–386) and with QueryBook Bible v2.1 Pass 121, Chapter 132.",
          f"Features: {LAST - 1}. Rows 1–{OLD_LAST - 1} carried from v71 unchanged. Rows {first_no}–{LAST - 1} added in v72: the truth state, "
          f"backing, weight and two-bit evidence code (FIG. 60, numerals 6010–6080) and the identity state, context beside the fact and mention "
          f"weighing (FIG. 61, numerals 6110–6170), each citing its figure and reference numeral.",
          f"Sheets: Feature Registry v72, Algorithms (v72) — {ALAST - 1} algorithms (ALG-26 to ALG-29 are Fact Unit algorithms), "
          "Drawings FIG 1-61, Supported External Services, Summary v72, Fact Unit changes.",
          "Status of the v72 rows: built and tested in the shared core of the applications (sense.py, qbbulk.py; engine 1.56), except the "
          "hardware-independent state mapping, which is specified: no hardware other than an ordinary binary processor is used or required. "
          "The packed two-bit form is built as functions and is not yet used in the store's file format. Additive covenant: no feature "
          "removed; no v65 cell in columns A–G altered; no v66, v69, v70 or v71 row altered. Claims: 386 (draft for the patent attorney)."]:
    rec.append([l])
for row in rec.iter_rows():
    for c in row: c.alignment = Alignment(wrap_text=True, vertical="top")

# ------------------------------------------------ Fact Unit changes: earlier design rows (fill only) and the v72 rows, on one sheet
EARLIER = ["Fact Unit Schema", "Bayesian ConfidenceScore Posterior Update", "Confidence Band Calibration Gap", "Self-Corroboration Bar",
           "Fact Unit Language", "Contradiction Query Template", "Principal Evidence Pair (Agent Reputation Store)"]
fu = wb.create_sheet("Fact Unit changes")
fu.append(["No.", "Feature", "Registry version added", "Drawing reference (FIG.)", "Status", "Relation to the four-state Fact Unit"])
for c in fu[1]: style_like(ws.cell(1, 2), c)
found = []
for r in range(2, LAST + 1):
    name, ver = ws.cell(r, 2).value, ws.cell(r, 11).value
    if name in EARLIER or ver == "v72":
        if ver != "v72":
            found.append(name)
            for c in range(1, 12): ws.cell(r, c).fill = NEWFILL          # fill only
        fu.append([ws.cell(r, 1).value, name, ver, ws.cell(r, 8).value, ws.cell(r, 9).value,
                   "new in v72" if ver == "v72" else "earlier Fact Unit design feature the four states build on"])
        for c in fu[fu.max_row]: style_like(tpl, c, NEWFILL)
assert sorted(found) == sorted(EARLIER), set(EARLIER) - set(found)
for col, wdt in zip("ABCDEF", (8, 52, 16, 14, 44, 50)): fu.column_dimensions[col].width = wdt

# ------------------------------------------------ additive check: every v70 feature and algorithm cell unchanged
a = ref["Feature Registry v71"]
diff = [(r, c) for r in range(1, OLD_LAST + 1) for c in range(1, 12) if a.cell(r, c).value != ws.cell(r, c).value]
assert not diff, diff[:5]
b = ref["Algorithms (v71)"]
diff = [(r, c) for r in range(1, OLD_ALAST + 1) for c in range(1, 10) if b.cell(r, c).value != wa.cell(r, c).value]
assert not diff, diff[:5]
wb.active = 0
wb.save(out)
print("features:", LAST - 1, "new:", LAST - OLD_LAST, f"({first_no}-{LAST - 1})", "algorithms:", ALAST - 1, "drawings:", DLAST - 1)
