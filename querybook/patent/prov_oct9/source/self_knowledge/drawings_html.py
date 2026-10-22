"""One sheet per figure (FIG. 1-57), letter size, for printing to PDF with Chromium.
Usage: drawings_html.py <final_figs.json> <figs_sup.json> <figs_skl.json> <out.html>"""
import html, json, sys
a, b, c, out = sys.argv[1:5]
F = {int(k): (v[1], v[0]) for k, v in json.load(open(a)).items()}
for f in (b, c):
    for n, t, sv in json.load(open(f)):
        F[n] = (t, sv)
N = max(F); assert sorted(F) == list(range(1, N + 1))
css = ("@page{size:letter;margin:0.6in}body{margin:0;font-family:Helvetica,Arial,sans-serif;color:#000}"
       ".s{page-break-after:always;height:9.6in;display:flex;flex-direction:column}.s:last-child{page-break-after:auto}"
       ".h{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:14px}.h b{font-size:15pt}.h span{font-size:9.5pt}"
       ".f{flex:1;display:flex;align-items:flex-start;justify-content:center}.f svg{width:100%;max-height:7.6in;border:none!important}"
       ".c{font-size:10.5pt;margin-top:10px}")
pages = []
for n in range(1, N + 1):
    t, sv = F[n]
    pages.append(f'<div class="s"><div class="h"><b>FIG. {n}</b><span>Sheet {n} of {N}</span></div><div class="f">{sv}</div>'
                 f'<div class="c">FIG. {n} — {html.escape(t)}</div></div>')
open(out, "w").write(f'<!doctype html><html><head><meta charset="utf-8"><title>QueryBook Drawings FIG. 1–{N}</title><style>{css}</style></head><body>{"".join(pages)}</body></html>')
print("sheets:", N)
