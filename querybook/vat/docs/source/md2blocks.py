"""Minimal Markdown -> builder blocks (headings, paragraphs, bullets, numbered, tables, code)."""
import json, re, sys
def convert(md):
    L = md.splitlines(); i = 0; B = []; para = []
    def flush():
        if para: B.append({"t": "p", "text": " ".join(para)}); para.clear()
    while i < len(L):
        s = L[i]
        if s.startswith("```"):
            flush(); j = i + 1; lines = []
            while not L[j].startswith("```"): lines.append(L[j]); j += 1
            B.append({"t": "code", "lines": lines}); i = j + 1; continue
        if s.startswith("|"):
            flush(); rows = []
            while i < len(L) and L[i].startswith("|"):
                cells = [c.strip() for c in L[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c) for c in cells): rows.append(cells)
                i += 1
            minc = [max(len(x) for r in rows for x in re.split(r"[\s/]+", r[k].replace("`", ""))) + 1 for k in range(len(rows[0]))]
            pref = [min(48, max(len(r[k]) for r in rows)) for k in range(len(rows[0]))]
            B.append({"t": "table", "header": rows[0], "rows": rows[1:], "minc": minc, "pref": pref}); continue
        m = re.match(r"(#{1,4}) (.*)", s)
        if m:
            flush(); lvl = len(m.group(1))
            B.append({"t": "title" if lvl == 1 else ["h1", "h2", "h3"][min(lvl - 2, 2)], "text": m.group(2)}); i += 1; continue
        if re.match(r"\s*([-*]|\d+\.) ", s):
            flush(); kind = "numbered" if re.match(r"\s*\d+\.", s) else "bullets"; items = []
            while i < len(L) and (re.match(r"\s*([-*]|\d+\.) ", L[i]) or (L[i].startswith("  ") and L[i].strip() and items)):
                t = L[i]
                if re.match(r"\s{2,}([-*]|\d+\.) ", t) and items: items[-1] += " — " + re.sub(r"^\s*([-*]|\d+\.) ", "", t).strip()
                elif re.match(r"\s*([-*]|\d+\.) ", t): items.append(re.sub(r"^\s*([-*]|\d+\.) ", "", t).strip())
                else: items[-1] += " " + t.strip()
                i += 1
            B.append({"t": kind, "items": items}); continue
        if s.strip() in ("---", ""):
            flush(); i += 1; continue
        para.append(s.strip()); i += 1
    flush(); return B
if __name__ == "__main__":
    print(json.dumps(convert(open(sys.argv[1]).read()), ensure_ascii=False, indent=0)[:3000])
