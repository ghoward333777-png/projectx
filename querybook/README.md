# QueryBook documents — the four-state Fact Unit (2026-11-14)

Amendments to the project documents for the four-state Fact Unit. The earlier documents and their builders live on branch
`claude/lucid-brahmagupta-ak4f6m` under `querybook/`; each file here is that branch's latest document plus additions only.
One wording source feeds all of them: `docs/source/fsu_text.py`.

| Document | File | Adds |
|---|---|---|
| QueryBook Bible v2.1, Pass 121 | `docs/QueryBook_Bible_v2.1_Pass_121_FourStateFactUnit_{clean,changes-highlighted}.docx/.pdf` | Chapter 132 |
| Composite Feature Registry v72 | `patent/registry/QueryBook_Composite_Feature_Registry_v72.xlsx` | features 408–422, ALG-26–29, FIG. 60–61, sheet "Fact Unit changes" |
| Provisional (synced) | `patent/prov_oct9/Prov_Patent_Oct9_SYNCED_FourStateFactUnit_{clean,changes-highlighted}.docx/.pdf` | summary item j, system item 10, items 18–21, claims 375–386 |
| Drawings | `patent/prov_oct9/QueryBook_Drawings_FIG1-61_FourStateFactUnit.pdf` | FIG. 60, FIG. 61 |
| Drawings description | `patent/prov_oct9/QueryBook_Drawings_Description_FIG1-61{,_changes-highlighted}.docx/.pdf` | FIG. 60–61 descriptions and numerals |

Yellow in the highlighted versions: the new four-state text, and — highlight only, no wording changed — the earlier Fact Unit
design passages it builds on (the Fact Unit definition and its supporting/contradicting evidence model; FIG. 2 and FIG. 19;
Bible Chapter 3 and §41.6.2; seven earlier Registry rows).

Every builder asserts that no earlier paragraph, row or cell value changed. The claims are a draft for the patent attorney.
To rebuild, take the inputs from the suite branch (`git archive origin/claude/lucid-brahmagupta-ak4f6m querybook/docs querybook/patent`)
and run `docs/source/build_bible_p121.py`, `patent/registry/source/build_v72.py`, `patent/prov_oct9/source/four_state/{add_fsu,figs_fsu,drawings_html,desc_fsu}.py`.
