"""Standalone VAT drawings: FIG. 56-57 of the QueryBook application become FIG. 1-2; numerals 56xx/57xx -> 1xx/2xx."""
import json, re, sys
S = sys.argv[1]
figs = json.load(open(f"{S}/vat/figs_vat.json"))
NUM = {}
out = []
for k, (n, cap, svg) in enumerate(figs, 1):
    def rn(m):
        v = int(m.group(1)); NUM[v] = v - 5500; return f">{v - 5500}<"
    svg = re.sub(r">(5[67]\d\d)<", rn, svg)
    svg = svg.replace("(FIG. 53, FIG. 51)", "(hash chain, signed)")
    assert "FIG." not in svg and not re.search(r">5[67]\d\d<", svg)
    svg = re.sub(r'width="100%" style="[^"]*"', 'style="width:100%;height:auto;max-height:7.9in"', svg, count=1)
    out.append((k, cap, svg))
html = ['<!doctype html><html><head><meta charset="utf-8"><title>Verified Agent Transport Drawings</title><style>'
 '@page{size:Letter;margin:0.75in} body{font-family:Arial,Helvetica,sans-serif;margin:0}'
 'section{page-break-after:always;display:flex;flex-direction:column;align-items:center} section:last-child{page-break-after:auto}'
 '.hd{align-self:stretch;display:flex;justify-content:space-between;align-items:baseline;margin-bottom:12px}'
 '.lab{font-weight:700;font-size:14pt} .sh{font-size:9pt} .cap{font-size:10pt;margin-top:12px;text-align:center}</style></head><body>']
for k, cap, svg in out:
    html.append(f'<section><div class="hd"><span class="lab">FIG. {k}</span><span class="sh">Sheet {k} of {len(out)}</span></div>{svg}<div class="cap">FIG. {k} — {cap}</div></section>')
html.append("</body></html>")
open(f"{S}/vatset/drawings.html", "w").write("".join(html))
json.dump({str(k): v for k, v in sorted(NUM.items())}, open(f"{S}/vatset/numerals.json", "w"))
print(sorted(NUM.items()))
