import sys
S = sys.argv[1]
s = open(f"{S}/build_v67.py").read()
rep = [
 ('"""Composite Feature Registry v67 = v65', '"""Composite Feature Registry v68 = v65'),
 ("import v67_data as D7", "import v68_data as D7"),
 ("FIGS.update(D7.FIGS)\n", ""),
 ('ws.title = "Feature Registry v67"', 'ws.title = "Feature Registry v68"'),
 ("[(t, D7.C, 'v67') for t in D7.NEW]", "[(t, D7.C, 'v68') for t in D7.NEW]"),
 ('wa = wb.create_sheet("Algorithms (v67)")', 'wa = wb.create_sheet("Algorithms (v68)")'),
 ('wd = wb.create_sheet("Drawings FIG 1-57")', 'wd = wb.create_sheet("Drawings FIG 1-55")'),
 (' if n <= 55 else "Verified Agent Transport")', ')'),
 ("REG = \"'Feature Registry v67'\"", "REG = \"'Feature Registry v68'\""),
 ("for n in range(1, 58):", "for n in range(1, 56):"),
 ('sm = wb.create_sheet("Summary v67", 0)', 'sm = wb.create_sheet("Summary v68", 0)'),
 ('"QueryBook Composite Feature Registry v67"; sm', '"QueryBook Composite Feature Registry v68"; sm'),
 ('were added in v66 or v67 (column K).', 'were added in v66 or v68 (column K).'),
 ('("Features added in v67 (Verified Agent Transport)", f\'=COUNTIF({REG}!K2:K{LAST},"v67")\')',
  '("Features added in v68 (support for agent-wrapper services)", f\'=COUNTIF({REG}!K2:K{LAST},"v68")\')'),
 ("Drawings (FIG. 1–57)", "Drawings (FIG. 1–55)"),
 ('"New in v67"', '"New in v68"'),
 ('K2:K{LAST},"v67")\').font = BF', 'K2:K{LAST},"v68")\').font = BF'),
]
for a, b in rep:
    assert s.count(a) == 1, (a, s.count(a)); s = s.replace(a, b)
s = s.replace("'Algorithms (v67)'!", "'Algorithms (v68)'!").replace("'Drawings FIG 1-57'!A2:A58", "'Drawings FIG 1-55'!A2:A56").replace("'Drawings FIG 1-57'!D2:D58", "'Drawings FIG 1-55'!D2:D56")
a0 = s.index('lines += [\n "",\n "QueryBook Composite Feature Registry v67"'); a1 = s.index("]\n", a0) + 2
s = s[:a0] + '''lines += [
 "",
 "QueryBook Composite Feature Registry v68",
 "Assembled October 9, 2026, from Composite Registry v66. Verified Agent Transport (VAT), the AI agent wrapper service, is registered separately in the VAT Feature Registry and is not listed here; registry v67, which listed VAT features, is superseded by this edition.",
 f"Features: {first_no - 1 + NEW_N + NEW7}. Rows 1–{first_no + NEW_N - 1} carried from v66 unchanged. Rows {first_no + NEW_N}–{first_no + NEW_N + NEW7 - 1} added in v68: QueryBook-side support for external agent-wrapper services — claim verification endpoint; contradiction query template; fingerprint-only verification; external triple extraction; assertion-type labels; signed verdicts and published verifier key; frame message-type extension range; extension flag and reserved-field profile; Python frame codec; QUIC stream binding; fingerprint set reconciliation; external append to the security log; session-range Merkle root; third-party session certificate type; principal evidence pair; signed policy bundle export; MCP pre-/post-call hooks; tool result record hash; wrapper service registration.",
 "Status of all v68 rows: Specified — not yet built; modules are the existing prototype modules to be extended (marked planned) or a new codec (qb_frames).",
 f"Sheets: Feature Registry v68, Algorithms (v68) — {len(D.ALGOS) + len(D7.ALGOS)} algorithms (ALG-14 to ALG-19 are support algorithms), Drawings FIG 1-55, Summary v68. Drawing references cite FIG. 1–55 only.",
 "Additive covenant: no feature removed relative to v66; no v65 cell in columns A–G altered; no v66 row altered.",
]
''' + s[a1:]
assert "v67" not in s.replace("v67_data", "").replace("registry v67, which", ""), [l for l in s.splitlines() if "v67" in l]
open(f"{S}/build_v68.py", "w").write(s)
open(f"{S}/restore_v65_text_v68.py", "w").write(open(f"{S}/restore_v65_text.py").read().replace("Feature Registry v66", "Feature Registry v68"))
