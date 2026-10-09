import sys
S = sys.argv[1]
s = open(f"{S}/build_v68.py").read()
rep = [
 ('"""Composite Feature Registry v68 = v65', '"""Composite Feature Registry v69 = v65'),
 ("import v68_data as D7", "import v69_data as D7"),
 ('ws.title = "Feature Registry v68"', 'ws.title = "Feature Registry v69"'),
 ("FIGS = {int(k): v[1] for k, v in json.load(open(figs_json)).items()}", "FIGS = {int(k): v[1] for k, v in json.load(open(figs_json)).items()}\nFIGS[56] = D7.FIG56"),
 ("[(t, D7.C, 'v68') for t in D7.NEW]", "[(t, D7.C, 'v69') for t in D7.NEW]"),
 ('wa = wb.create_sheet("Algorithms (v68)")', 'wa = wb.create_sheet("Algorithms (v69)")'),
 ('wd = wb.create_sheet("Drawings FIG 1-55")', 'wd = wb.create_sheet("Drawings FIG 1-56")'),
 ('"Further embodiments" if n <= 49 else "Agent-era extensions")', '"Further embodiments" if n <= 49 else "Agent-era extensions" if n <= 55 else "Support for agent-wrapper services")'),
 ("REG = \"'Feature Registry v68'\"", "REG = \"'Feature Registry v69'\""),
 ("for n in range(1, 56):", "for n in range(1, 57):"),
 ('sm = wb.create_sheet("Summary v68", 0)', 'sm = wb.create_sheet("Summary v69", 0)'),
 ('"QueryBook Composite Feature Registry v68"; sm', '"QueryBook Composite Feature Registry v69"; sm'),
 ('were added in v66 or v68 (column K).', 'were added in v66 or v69 (column K). Verified Agent Transport is supported, not included: see the Supported External Services sheet.'),
 ('("Features added in v68 (support for agent-wrapper services)", f\'=COUNTIF({REG}!K2:K{LAST},"v68")\')',
  '("Features added in v69 (support for agent-wrapper services, FIG. 56)", f\'=COUNTIF({REG}!K2:K{LAST},"v69")\'),\n        ("External services supported (not QueryBook features)", "=COUNT(\'Supported External Services\'!F2:F20)")'),
 ("Drawings (FIG. 1–55)", "Drawings (FIG. 1–56)"),
 ('"New in v68"', '"New in v69"'),
 ('K2:K{LAST},"v68")\').font = BF', 'K2:K{LAST},"v69")\').font = BF'),
]
for a, b in rep:
    assert s.count(a) == 1, (a, s.count(a)); s = s.replace(a, b)
s = s.replace("'Algorithms (v68)'!", "'Algorithms (v69)'!").replace("'Drawings FIG 1-55'!A2:A56", "'Drawings FIG 1-56'!A2:A57").replace("'Drawings FIG 1-55'!D2:D56", "'Drawings FIG 1-56'!D2:D57")
# Supported External Services sheet, inserted before the Summary is built
a = "# ------------------------------------------------ Summary sheet"
assert s.count(a) == 1
s = s.replace(a, '''# ------------------------------------------------ Supported External Services (not QueryBook features)
we = wb.create_sheet("Supported External Services")
eh = [("External service", 30), ("What it is", 60), ("Where it is described", 36), ("Status", 18), ("QueryBook support features used (registry No.)", 40), ("Count", 8)]
for i, (hh, w) in enumerate(eh, 1):
    c = we.cell(1, i, hh); c.font, c.fill, c.alignment, c.border = HF, HFILL, HAL, HB
    we.column_dimensions[get_column_letter(i)].width = w
NO = {str(ws.cell(r, 2).value): ws.cell(r, 1).value for r in range(2, LAST + 1)}
for j, (name, what, where, st, used) in enumerate(D7.EXTERNAL, 2):
    nums = [NO[u] for u in used]
    for i, v in enumerate([name, what, where, st, ", ".join(map(str, nums)), len(nums)], 1):
        c = we.cell(j, i, v); c.font, c.alignment, c.border = BF, BAL, BB
we.cell(len(D7.EXTERNAL) + 3, 1, "External services are listed for reference only. They are not QueryBook features, are not counted in the Feature Registry, and are not claimed in the QueryBook application; QueryBook claims only the support interfaces (claims 355–357).").font = Font(name=BF.name, italic=True, size=10)
we.freeze_panes = "A2"

''' + a)
a0 = s.index('lines += [\n "",\n "QueryBook Composite Feature Registry v68"'); a1 = s.index("]\n", a0) + 2
s = s[:a0] + '''lines += [
 "",
 "QueryBook Composite Feature Registry v69",
 "Assembled October 9, 2026, from Composite Registry v66 and synchronized with the provisional application as updated with support for agent-wrapper services (FIG. 56; claims 355–357). Supersedes v67 (which listed Verified Agent Transport as features) and v68 (same support features without FIG. 56).",
 f"Features: {first_no - 1 + NEW_N + NEW7}. Rows 1–{first_no + NEW_N - 1} carried from v66 unchanged. Rows {first_no + NEW_N}–{first_no + NEW_N + NEW7 - 1} added in v69: QueryBook-side support for external agent-wrapper services, each citing FIG. 56 and its reference numeral (5612–5648).",
 "Verified Agent Transport (VAT) is supported but is not part of QueryBook: it is listed on the Supported External Services sheet with the support features it uses, is not counted as a feature, and is described in its own application and VAT Feature Registry.",
 f"Sheets: Feature Registry v69, Algorithms (v69) — {len(D.ALGOS) + len(D7.ALGOS)} algorithms (ALG-14 to ALG-19 are support algorithms), Drawings FIG 1-56, Supported External Services, Summary v69.",
 "Status of all v69 rows: Specified — not yet built. Additive covenant: no feature removed relative to v66; no v65 cell in columns A–G altered; no v66 row altered. Claims: 357.",
]
''' + s[a1:]
assert "v68" not in s.replace("v68 (same", ""), [l for l in s.splitlines() if "v68" in l]
open(f"{S}/build_v69.py", "w").write(s)
open(f"{S}/restore_v65_text_v69.py", "w").write(open(f"{S}/restore_v65_text.py").read().replace("Feature Registry v66", "Feature Registry v69"))
