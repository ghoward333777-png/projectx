#!/usr/bin/env python3
"""Rebalance the provisional QueryBook-first (rev. October 8, 2026 (B)).
Usage: build_rebal.py <in clean.html> <out_review.html> <out_clean.html>"""
import html as H, re, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import rebal_content as C

src, out_rev, out_clean = sys.argv[1:4]
S = open(src, encoding="utf-8").read()

# ------------------------------------------------------------- strip previous-revision highlight markup
S = re.sub(r'<style id="rev-xv">.*?</style>', "", S, flags=re.S)
def _cls(m):
    toks = [t for t in m.group(1).split() if t not in ("add", "addfig")]
    return f' class="{" ".join(toks)}"' if toks else ""
S = re.sub(r' class="([^"]*)"', _cls, S)

# ------------------------------------------------------------- maps
def fig_map(n):
    return n - 8 if 9 <= n <= 30 else (n + 22 if 1 <= n <= 8 else n)

KEEP_XV = [77, 80, 82, 83, 87, 88, 90, 92, 93, 96, 97, 98]
CMAP = {n: n + 20 for n in range(1, 77)}
for i, n in enumerate(KEEP_XV):
    CMAP[n] = 97 + i
DROPPED = sorted(set(range(77, 100)) - set(KEEP_XV))

ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV",
         "XVI", "XVII", "XVIII", "XIX", "XX", "XXI", "XXII", "XXIII", "XXIV"]
SMAP = {ROMAN[i]: ROMAN[i + 8] for i in range(15)}
ROM_RE = r"(?:XV|XIV|XIII|XII|XI|X|IX|VIII|VII|VI|V|IV|III|II|I)"

def runs(nums):
    nums = sorted(set(nums)); out = []
    for n in nums:
        if out and n == out[-1][1] + 1: out[-1][1] = n
        else: out.append([n, n])
    return out

def join_list(parts):
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]

FIG_RE = re.compile(r"(FIGS?\.\s?)(\d+)(?:(\s*(?:–|-|through)\s*)(FIGS?\.\s?)?(\d+))?")
def map_figs(text):
    def rep(m):
        a = int(m.group(2))
        if m.group(5) is None:
            return m.group(1) + str(fig_map(a))
        b = int(m.group(5)); dash = "–" if "through" not in m.group(3) else m.group(3)
        rs = runs(fig_map(k) for k in range(a, b + 1)); pre2 = m.group(4) or ""
        parts = [(f"{x}{dash}{pre2}{y}" if x != y else f"{x}") for x, y in rs]
        return m.group(1) + join_list(parts)
    return FIG_RE.sub(rep, text)

CL_RE = re.compile(r"([Cc]laims?)([  ]+)(\d+(?:[  ]*(?:–|-|,|and|or)[  ]*\d+)*)")
problems = []
def map_claims(text):
    def rep(m):
        toks = re.findall(r"\d+|–|-|,|and|or", m.group(3))
        nums, i = [], 0
        while i < len(toks):
            t = toks[i]
            if t.isdigit():
                if i + 2 < len(toks) and toks[i + 1] in ("–", "-") and toks[i + 2].isdigit():
                    nums += list(range(int(t), int(toks[i + 2]) + 1)); i += 3; continue
                nums.append(int(t))
            i += 1
        mapped = [CMAP.get(n) for n in nums]
        if all(x is None for x in mapped):
            problems.append(("claim ref to dropped claim", m.group(0)))
        mapped = [x for x in mapped if x is not None]
        parts = [(f"{x}–{y}" if x != y else f"{x}") for x, y in runs(mapped)] if mapped else ["?"]
        word = m.group(1)
        if len(mapped) == 1 and word.lower() == "claims": word = word[:-1]
        if len(mapped) > 1 and word.lower() == "claim": word = word + "s"
        return word + m.group(2) + join_list(parts)
    return CL_RE.sub(rep, text)

SEC_RE = re.compile(r"(Sections?\s+)(" + ROM_RE + r")\b((?:\s*(?:–|,|and)\s*" + ROM_RE + r"\b)*)")
def map_sections(text):
    def rep(m):
        tail = re.sub(ROM_RE + r"\b", lambda r: SMAP[r.group(0)], m.group(3))
        return m.group(1) + SMAP[m.group(2)] + tail
    return SEC_RE.sub(rep, text)

def map_old(text):
    """apply figure, claim and section renumbering to legacy content (outside SVG geometry)."""
    pieces = re.split(r"(<svg.*?</svg>)", text, flags=re.S)
    out = []
    for p in pieces:
        if p.startswith("<svg"):
            # remap only FIG references inside drawing text
            p = re.sub(r"(<text[^>]*>)(.*?)(</text>)", lambda m: m.group(1) + map_figs(m.group(2)) + m.group(3), p, flags=re.S)
            out.append(p)
        else:
            out.append(map_sections(map_claims(map_figs(p))))
    return "".join(out)

# platform numerals (+6000) inside the former FIG. 9–30 drawings
NUM_RE = re.compile(r"(?<![\w.#\-])(\d{3,4})([a-d]?)(?![\w.%])")
plat_seen = set()
def shift_platform_svg(svg):
    svg = svg.replace(" (CLAIM 11)", "").replace("(CLAIM 11)", "")
    # FIG. 5 (former 13): remove the screen overlays that hid the waypoint labels; replace undefined "(IQR)"
    svg = re.sub(r'<rect x="\d+" y="140" width="104" height="34" fill="#eef2f8"[^>]*/>', "", svg)
    svg = svg.replace(">(IQR) </text>", ">from Fact Units</text>")
    def tx(m):
        def r(n):
            v = int(n.group(1))
            if v < 100 or v > 2300: return n.group(0)
            new = f"{v + 6000}{n.group(2)}"; plat_seen.add(new); return new
        return m.group(1) + NUM_RE.sub(r, m.group(2)) + m.group(3)
    return re.sub(r"(<text[^>]*>)(.*?)(</text>)", tx, svg, flags=re.S)

# ------------------------------------------------------------- locate legacy parts
def between(a, b, s=S):
    i = s.index(a); j = s.index(b, i); return s[i:j]

head = S[:S.index('<div class="wrap">') + len('<div class="wrap">')]
head = head.replace("</style>", "h4{font-size:15px;margin:20px 0 8px}h3.add,h4.add{padding:0 2px}"
                    ".add{background:#ffff00 !important;-webkit-print-color-adjust:exact;print-color-adjust:exact}</style>", 1)
cover = between('<div class="cover">', '<p style="font-size:12px;color:var(--muted)')
note_old = between('<p style="font-size:12px;color:var(--muted)', '<div style="page-break-before:always"></div>')

# figures
FIGDIV = re.compile(r'<div style="page-break-inside:avoid;margin:18px 0 26px">\s*<div[^>]*>FIG\. (\d+)</div>.*?</svg>\s*<div[^>]*>.*?</div></div>', re.S)
figs = {}
for m in FIGDIV.finditer(S):
    figs[int(m.group(1))] = m.group(0)
assert sorted(figs) == list(range(1, 56)), sorted(figs)

brief_old = between("<h2>Brief Description of the Drawings</h2>", "<h3>Reference Numerals</h3>")
detailed = between("<h2>Detailed Description of the Preferred Embodiments</h2>", "<h2>Claims</h2>")
claims_part = between("<h2>Claims</h2>", "<h2>Abstract</h2>")
after_abs = S[S.index("<h2>Abstract</h2>"):]
flags_old = re.findall(r'<div class="foot" style="border-left:4px solid #b25d00.*?</div>', after_abs, re.S)
assert len(flags_old) == 12, len(flags_old)
table_old = between("<table><thead><tr><th>No.</th>", "</tbody></table>") + "</tbody></table>"

# brief descriptions: legacy entries for FIG. 1–8 (brief section) and 31–55 (misplaced in Section I / Section XV list)
brief_txt = {}
for m in re.finditer(r'<p class="pp"><b>FIG\. (\d+)</b>(.*?)(?=<p|<h3|<h2|$)', brief_old + detailed, re.S):
    n = int(m.group(1))
    if n <= 8 or n >= 31:
        brief_txt[n] = m.group(2).strip().removesuffix("</p>").strip()
assert set(brief_txt) == set(range(1, 9)) | set(range(31, 56)), sorted(set(range(1, 9)) | set(range(31, 56)) - set(brief_txt))

# ------------------------------------------------------------- build document
out = [head, "\n"]

# cover
cov = map_old(cover)
cov = re.sub(r'(<h1 class="title">).*?(</h1>)', lambda m: m.group(1) + C.TITLE + m.group(2), cov, flags=re.S)
anchor = "<b>Attorney docket"
i = cov.index(anchor); j = cov.rindex(")", 0, i)
cov = cov[:j] + f'<span class="add">{C.REV}</span>' + cov[j:]
out.append(cov)
out.append(C.NOTE + "\n\n  <div style=\"page-break-before:always\"></div>\n")

# drawings
out.append('<h2 id="drawings">Drawings</h2>\n' + C.DRAWINGS_INTRO)
order = list(range(9, 31)) + list(range(1, 9)) + list(range(31, 56))
gstart = {g: h for g, h in C.GROUPS}
for old in order:
    new = fig_map(old)
    if new in gstart:
        out.append(f'<h3 class="add" style="font-family:Helvetica,Arial,sans-serif;font-size:14px">{gstart[new]}</h3>\n')
    d = figs[old]
    if 9 <= old <= 30:
        d = re.sub(r"<svg.*?</svg>", lambda m: shift_platform_svg(m.group(0)), d, flags=re.S)
    out.append(map_old(d) + "\n")

# field / background / summary
out.append(C.FIELD + C.BACKGROUND + C.SUMMARY)

# brief description
out.append("<h2>Brief Description of the Drawings</h2>\n")
for new in range(1, 56):
    if new in gstart:
        out.append(f'<h3 class="add">{gstart[new]}</h3>\n')
    if new <= 22:
        out.append(f'<p class="pp add"><b>FIG. {new}</b> is {C.BRIEF_CORE[new]}.</p>\n')
    else:
        old = new - 22 if 23 <= new <= 30 else new
        out.append(f'<p class="pp"><b>FIG. {new}</b> {map_old(brief_txt[old])}</p>\n')

# reference numerals (merged, sorted, re-split)
rows = re.findall(r"<td>([^<]*)</td><td>(.*?)</td>", table_old)
entries = [(a, b, False) for a, b in rows if a.strip()]
existing = {a for a, _, _ in entries}
for k, v in C.PLATFORM_NUMERALS.items():
    assert str(k) not in existing, k
    entries.append((str(k), H.escape(v, quote=False), True))
def nkey(e):
    m = re.match(r"(\d+)([a-z]?)", e[0]); return (int(m.group(1)), m.group(2))
entries.sort(key=nkey)
half = (len(entries) + 1) // 2
L, R = entries[:half], entries[half:] + [None]
trs = []
for a, b in zip(L, R):
    cells = [a] + ([b] if b else [])
    tds = ""
    for e in cells:
        cls = ' class="add"' if e[2] else ""
        tds += f"<td><span{cls}>{e[0]}</span></td><td><span{cls}>{e[1]}</span></td>"
    if not b: tds += "<td></td><td></td>"
    trs.append(f"<tr>{tds}</tr>")
out.append('<h3>Reference Numerals</h3>\n<table><thead><tr><th>No.</th><th>Element</th><th>No.</th><th>Element</th></tr></thead><tbody>\n'
           + "\n".join(trs) + "\n</tbody></table>\n\n")

# detailed description
det = detailed
# remove the misplaced brief-description paragraphs from legacy Section I
det = re.sub(r'<p class="pp"><b>FIG\. (3[1-9]|4[0-9])</b>.*?</p>\s*', "", det, flags=re.S)
# sections: h3 -> h4, mapped
det = det.replace("<h2>Detailed Description of the Preferred Embodiments</h2>", "")
det = re.sub(r"<h3([^>]*)>(.*?)</h3>", r"<h4\1>\2</h4>", det, flags=re.S)
det = det.replace("Section XIII — Recent Extensions", "Section XIII — Further Embodiments")
det = re.sub(r"\((16(?:0[02468]|10))\)", lambda m: f"({int(m.group(1)) + 6000})", det)  # media numerals (FIG. 16)
det = map_old(det)
# insert part headings before legacy sections
def before(pattern, text, ins):
    i = text.index(pattern); return text[:i] + ins + text[i:]
det = before("<h4>Section IX — The Sub-Language", det, C.PART_B_HEAD)
det = before("<h4>Section XVII — Voiceprint", det, C.PART_C_HEAD)
det = before('<h4 id="sec-xiii">Section XXI', det, C.PART_D_HEAD)
out.append("<h2>Detailed Description of the Preferred Embodiments</h2>\n" + C.PART_A + det)

# claims
claim_ps = re.findall(r'<p class="claim"><span class="cn">(\d+)\.</span>(.*?)</p>', claims_part, re.S)
assert [int(n) for n, _ in claim_ps] == list(range(1, 100))
intro = claims_part[:claims_part.index('<p class="claim">')]
cl_html = [intro]
for i, body in enumerate(C.CORE_CLAIMS, 1):
    cl_html.append(f'<p class="claim add"><span class="cn">{i}.</span> {body}</p>')
for n, body in claim_ps:
    n = int(n)
    if CMAP.get(n) is None: continue
    cl_html.append(f'<p class="claim"><span class="cn">{CMAP[n]}.</span>{map_old(body)}</p>')
out.append("".join(cl_html) + "\n\n  ")

# abstract + flags + final foot
out.append(C.ABSTRACT + "\n")
for f in C.NEW_FLAGS:
    out.append(re.sub(r"\{(A\d\d)\}", r"[\1]", f))
for f in flags_old:
    out.append("  " + map_old(f) + "\n")
out.append(C.FINAL_FOOT + "</div>\n\n</body></html>\n")
doc = "".join(out)
doc = re.sub(r"<title>.*?</title>", "<title>QueryBook Provisional Patent Application — rev. October 8, 2026 (B)</title>", doc, count=1, flags=re.S)

# ------------------------------------------------------------- paragraph renumbering
labels = re.findall(r'<span class="n">\[([^\]]+)\]</span>', doc)
assert len(labels) == len(set(labels)), "duplicate paragraph labels"
PMAP = {l: f"{i:04d}" for i, l in enumerate(labels, 1)}
doc = re.sub(r"\[(\d{4}|[AB]\d\d)\]", lambda m: f"[{PMAP[m.group(1)]}]" if m.group(1) in PMAP else m.group(0), doc)

# ------------------------------------------------------------- checks
text = re.sub(r"<[^>]+>", " ", re.sub(r"<svg.*?</svg>", " ", doc, flags=re.S))
text = H.unescape(text)
bad_figs = [x for x in re.findall(r"FIGS?\.\s?(\d+)", text) if not 1 <= int(x) <= 55]
assert not bad_figs, bad_figs
cl_nums = [int(x) for x in re.findall(r'<span class="cn">(\d+)\.</span>', doc)]
assert cl_nums == list(range(1, len(cl_nums) + 1)), cl_nums
for m in re.finditer(r"[Cc]laims? (\d+)", text):
    assert int(m.group(1)) <= len(cl_nums), m.group(0)
# every cited numeral in text exists in the table
tab = set(re.findall(r"<td><span[^>]*>(\d+[a-d]?)</span></td>", doc))
cited = set(re.findall(r"\((\d{3,4}[a-d]?)\)", text))
missing = sorted(c for c in cited if c not in tab)
expected_plat = {str(k) for k in C.PLATFORM_NUMERALS}
print("platform numerals in drawings vs key — missing in key:", sorted(plat_seen - expected_plat),
      "unused key entries:", sorted(expected_plat - plat_seen))
print("cited numerals absent from key:", missing)
print("problems:", problems)
print("paragraphs:", len(labels), "claims:", len(cl_nums), "dropped XV claims:", DROPPED)

open(out_rev, "w", encoding="utf-8").write(doc)
clean = doc.replace(".add{background:#ffff00 !important", ".add{background:transparent !important")
open(out_clean, "w", encoding="utf-8").write(clean)
print("written", len(doc))
