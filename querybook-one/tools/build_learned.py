#!/usr/bin/env python3
"""Merge what was learned from sources into apps/shell/genres_learned.json — the rules QueryBook ships with.

    python tools/build_learned.py <folder>      <folder>/out/<source>.json and <folder>/pages/<source>-<n>.txt

Each out file is one source read by a model in a build session (the brief is docs/querybook-rebuild/writing-skills-plan.md,
"Source learning"): pages, and for each page rule units in the reader's own words. This tool is the gate:
  - a unit must name a known genre (or "any") and a known skill layer;
  - a unit that repeats seven consecutive words of its page is dropped (apps/shell/writing.py: keep_units);
  - the page's text is hashed and then NOT kept: only the address, the date, the hash and the rules are.
The result is sorted and written deterministically. A source with no page read is recorded as not read, with the reason.
"""
import glob
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "apps", "shell"))
import writing  # noqa: E402

OUT = os.path.join(ROOT, "apps", "shell", "genres_learned.json")


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    folder = argv[0]
    with open(os.path.join(ROOT, "apps", "shell", "genres.json"), encoding="utf-8") as f:
        lib = writing.load_genres(f.read())
    ids = sorted(lib["genres"])
    pages, not_read, dropped_all = [], [], {}
    for path in sorted(glob.glob(os.path.join(folder, "out", "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError) as e:
            not_read.append({"source": os.path.basename(path)[:-5], "why": "its file could not be read: %s" % e})
            continue
        sid = str(d.get("source") or os.path.basename(path)[:-5])
        if sid not in lib["sources"]:
            not_read.append({"source": sid, "why": "not in the register of sources"})
            continue
        got = 0
        for pg in d.get("pages") or []:
            tf = os.path.join(folder, str(pg.get("text_file") or ""))
            try:
                with open(tf, encoding="utf-8", errors="replace") as f:
                    text = " ".join(f.read().split())
            except OSError:
                dropped_all[sid] = dropped_all.get(sid, 0) + len(pg.get("units") or [])
                continue                                     # no page text: the copy check cannot be made, so nothing is kept
            if len(text.split()) < 80:
                continue
            res = writing.keep_units([u for u in pg.get("units") or [] if isinstance(u, dict)], text, ids)
            kept = [u for u in res["kept"] if u["layer"]]
            dropped_all[sid] = dropped_all.get(sid, 0) + len(pg.get("units") or []) - len(kept)
            if not kept:
                continue
            got += len(kept)
            pages.append({"source": sid, "url": str(pg.get("url") or ""), "title": " ".join(str(pg.get("title") or "").split())[:120],
                          "retrieved": str(pg.get("retrieved") or ""), "page_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                          "by": "a model in a QueryBook build session", "units": kept})
        if not got:
            not_read.append({"source": sid, "why": " ".join(str(d.get("why_not") or "no usable rule came from its pages").split())[:300]})
    pages.sort(key=lambda p: (p["source"], p["url"]))
    not_read.sort(key=lambda r: r["source"])
    doc = {"version": "learned-1", "pages": pages, "not_read": not_read}
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    srcs = sorted({p["source"] for p in pages})
    print("wrote %s: %d rules from %d pages of %d sources; %d sources not read; %d units dropped by the gate" % (
        OUT, sum(len(p["units"]) for p in pages), len(pages), len(srcs), len(not_read), sum(dropped_all.values())))
    for r in not_read:
        print("  not read: %-24s %s" % (r["source"], r["why"][:110]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
