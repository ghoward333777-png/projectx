#!/usr/bin/env python3
"""Composite Feature Registry v71 = v70 (every row and sheet unchanged) + the Digital Synaptic Network and network memory:
features 392-407 (FIG. 58 numerals 5810-5870, FIG. 59 numerals 5910-5990), algorithms ALG-22 to ALG-25, drawings FIG. 58-59,
updated summary and record. Wording from docs/source/dsn_text.py. Usage: build_v71.py <v70.xlsx> <out.xlsx>"""
import copy, os, re, sys
from openpyxl import load_workbook
from openpyxl.styles import Alignment, PatternFill
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "docs", "source"))
import dsn_text as K

src, out = sys.argv[1:3]
wb = load_workbook(src)
ref = load_workbook(src)                      # untouched copy for the additive check
ws = wb["Feature Registry v70"]; ws.title = "Feature Registry v71"
wa = wb["Algorithms (v70)"]; wa.title = "Algorithms (v71)"
wd = wb["Drawings FIG 1-57"]; wd.title = "Drawings FIG 1-59"
sm = wb["Summary v70"]; sm.title = "Summary v71"
REG = "'Feature Registry v71'"
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
    vals = [no, name, dom, cite, f"{surface}{cite}{role} {func}", rule, wexpr, ", ".join(map(str, figs)), status, module, "v71"]
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
for fig, title, area in ((K.FIG_R, K.FIG_R_TITLE, "Answer routing"), (K.FIG_N, K.FIG_N_TITLE, "Network memory")):
    r = wd.max_row + 1
    for i, v in enumerate([fig, title, area], 1):
        style_like(dtpl, wd.cell(r, i, v))
DLAST = wd.max_row
for rr in range(2, DLAST + 1):
    wd.cell(rr, 4).value = f'=SUMPRODUCT(--ISNUMBER(SEARCH(", "&A{rr}&",",", "&{REG}!$H$2:$H${LAST}&",")))'
    wd.cell(rr, 5).value = f"=SUMPRODUCT(--ISNUMBER(SEARCH(\", \"&A{rr}&\",\",\", \"&'Algorithms (v71)'!$D$2:$D${ALAST}&\",\")))"
    if rr > OLD_DLAST:
        for c in (4, 5): style_like(dtpl, wd.cell(rr, c))

# ------------------------------------------------ summary
BF = sm["A5"].font
sm["A1"] = "QueryBook Composite Feature Registry v71"
sm["A2"] = ("Rows highlighted yellow on the Feature Registry sheet were added in v66, v69, v70 or v71 (column K). Verified Agent Transport is "
            "supported, not included: see the Supported External Services sheet. All v65 rows (columns A–G) and all v66, v69 and v70 rows are unchanged.")
for row in sm.iter_rows():
    for c in row:
        if isinstance(c.value, str) and c.value.startswith("="):
            c.value = (c.value.replace("'Feature Registry v70'", REG).replace(f"2:A{OLD_LAST}", f"2:A{LAST}")
                       .replace(f"2:C{OLD_LAST}", f"2:C{LAST}").replace(f"2:G{OLD_LAST}", f"2:G{LAST}").replace(f"2:H{OLD_LAST}", f"2:H{LAST}")
                       .replace(f"2:I{OLD_LAST}", f"2:I{LAST}").replace(f"2:K{OLD_LAST}", f"2:K{LAST}")
                       .replace("'Algorithms (v70)'", "'Algorithms (v71)'").replace(f"A2:A{OLD_ALAST}", f"A2:A{ALAST}")
                       .replace("'Drawings FIG 1-57'", "'Drawings FIG 1-59'").replace(f"A2:A{OLD_DLAST}", f"A2:A{DLAST}")
                       .replace(f"D2:D{OLD_DLAST}", f"D2:D{DLAST}"))
        elif c.value == "Drawings (FIG. 1–57)":
            c.value = "Drawings (FIG. 1–59)"
# rows for v71 after the v70 row, by shifting the rows below them
vrow = next(r for r in range(1, sm.max_row + 1) if str(sm.cell(r, 1).value).startswith("Features added in v70"))
sm.insert_rows(vrow + 1, 2)
sm.cell(vrow + 1, 1, "Features added in v71 (Digital Synaptic Network and network memory, FIG. 58–59)").font = copy.copy(BF)
sm.cell(vrow + 1, 2, f'=COUNTIF({REG}!K2:K{LAST},"v71")').font = copy.copy(BF)
sm.cell(vrow + 2, 1, "v71 features built (prototype v9.64, the applications, or the test tool)").font = copy.copy(BF)
sm.cell(vrow + 2, 2, f'=COUNTIFS({REG}!K2:K{LAST},"v71",{REG}!I2:I{LAST},"Built*")').font = copy.copy(BF)
hdr = next(r for r in range(1, sm.max_row + 1) if sm.cell(r, 1).value == "Features by domain")
sm.cell(hdr, 6, "New in v71").font = copy.copy(sm.cell(hdr, 5).font)
r = hdr + 1
while sm.cell(r, 1).value:
    for c in (2, 3, 4, 5):                                # insert_rows does not move formula references: re-point A{r}
        v = sm.cell(r, c).value
        if isinstance(v, str):
            sm.cell(r, c).value = re.sub(r"\bA\d+\b", f"A{r}", v)
    sm.cell(r, 6, f'=COUNTIFS({REG}!C2:C{LAST},A{r},{REG}!K2:K{LAST},"v71")').font = copy.copy(BF)
    r += 1
sm.column_dimensions["F"].width = 12

# ------------------------------------------------ registry record
rec = wb["Registry Record"]
for l in ["",
          "QueryBook Composite Feature Registry v71",
          f"Assembled {K.DATE} from Composite Registry v70 and synchronized with the provisional application as updated with the "
          f"Digital Synaptic Network and network memory (FIG. 58–59; claims 363–374) and with QueryBook Bible v2.1 Pass 120, Chapter 131.",
          f"Features: {LAST - 1}. Rows 1–{OLD_LAST - 1} carried from v70 unchanged. Rows {first_no}–{LAST - 1} added in v71: answer routing "
          f"(FIG. 58, numerals 5810–5870) and network memory (FIG. 59, numerals 5910–5990), each citing its figure and reference numeral.",
          f"Sheets: Feature Registry v71, Algorithms (v71) — {ALAST - 1} algorithms (ALG-22 to ALG-25 are DSN and network-memory algorithms), "
          "Drawings FIG 1-59, Supported External Services, Summary v71.",
          "Status of the v71 rows: answer routing built in the applications' shared core (qbdsn.py, Control Panel 1.34); network memory built "
          "in prototype v9.64 (qb_synapse.py) and the applications' shared core (qbsynapse.py, Control Panel 1.35); the stress-test harness "
          "built as a test tool (querybook/sim/dsn_stress.py 1.1.0). Additive covenant: no feature removed; no v65 cell in columns A–G "
          "altered; no v66, v69 or v70 row altered. Claims: 374."]:
    rec.append([l])
for row in rec.iter_rows():
    for c in row: c.alignment = Alignment(wrap_text=True, vertical="top")

# ------------------------------------------------ additive check: every v70 feature and algorithm cell unchanged
a = ref["Feature Registry v70"]
diff = [(r, c) for r in range(1, OLD_LAST + 1) for c in range(1, 12) if a.cell(r, c).value != ws.cell(r, c).value]
assert not diff, diff[:5]
b = ref["Algorithms (v70)"]
diff = [(r, c) for r in range(1, OLD_ALAST + 1) for c in range(1, 10) if b.cell(r, c).value != wa.cell(r, c).value]
assert not diff, diff[:5]
wb.active = 0
wb.save(out)
print("features:", LAST - 1, "new:", LAST - OLD_LAST, f"({first_no}-{LAST - 1})", "algorithms:", ALAST - 1, "drawings:", DLAST - 1)
