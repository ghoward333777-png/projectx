#!/usr/bin/env python3
"""Build apps/_core/hot_seed.json — the icons list that ships inside QueryBook, so the hot list is read at once.

For every icons set of the harvest engine (qbbulk.ICONS: teams, athletes, music, screen, leaders and writers, places and
landmarks, culture and events) Wikidata's query service is asked for the set's ranked list, exactly as the engine does on
the user's computer (qbbulk.domain_discover: fame = Wikipedias with an article, weighted for the culture, each code's
label checked). The sets are then taken in turn, 50 at a time, so the top of every set comes first.

Run from querybook-one/:  python tools/build_hot_seed.py        (about half an hour; resumes where it stopped)
Then: python apps/tools/sync_core.py
"""
import datetime
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "apps", "_core"))
import qbbulk  # noqa: E402

OUT = os.path.join(ROOT, "apps", "_core", "hot_seed.json")
PART = OUT + ".part"


def main():
    try:
        with open(PART, encoding="utf-8") as f:
            done = json.load(f)
    except (OSError, ValueError):
        done = {}
    earlier = None                          # a shipped list made before its sets were kept one by one: kept whole
    try:
        with open(OUT, encoding="utf-8") as f:
            old = json.load(f)
        if old.get("lists"):
            for n, ids in old["lists"].items():
                done.setdefault(n, {"ids": ids, "roots": (old.get("roots") or {}).get(n, [])})
        else:
            earlier = old
            for n in old.get("sets") or {}:
                done.setdefault(n, {"ids": [], "roots": (old.get("roots") or {}).get(n, []), "count": old["sets"][n]})
    except (OSError, ValueError):
        pass
    for name in qbbulk.ICONS:
        if name in done:
            print("have", name, len(done[name]["ids"]))
            continue
        t0 = time.time()
        d = qbbulk.domain_discover(name, table=qbbulk.ICONS)
        done[name] = {"ids": d["ids"], "roots": d["roots"]}
        with open(PART, "w", encoding="utf-8") as f:
            json.dump(done, f)
        print("%-18s %6d in %4d s  left out: %s" % (name, len(d["ids"]), time.time() - t0,
              [r["expected"] for r in d["roots"] if not r["used"] or r.get("why")]), flush=True)
    if earlier:                             # the earlier list takes its sets' share of every round, each new set its own 50
        share = qbbulk.ICON_BLOCK * len(earlier.get("sets") or {})
        fresh = [done[n]["ids"] for n in qbbulk.ICONS if done[n]["ids"]]
        ids, seen, k = [], set(), 0
        while k * share < len(earlier["ids"]) or any(k * qbbulk.ICON_BLOCK < len(x) for x in fresh):
            for q in earlier["ids"][k * share:(k + 1) * share] + [q for x in fresh for q in x[k * qbbulk.ICON_BLOCK:(k + 1) * qbbulk.ICON_BLOCK]]:
                if q not in seen:
                    seen.add(q)
                    ids.append(q)
            k += 1
        lists = {}
    else:
        ids = qbbulk.interleave([done[n]["ids"] for n in qbbulk.ICONS])
        lists = {n: done[n]["ids"] for n in qbbulk.ICONS}
    seed = {"made": datetime.date.today().isoformat(), "culture": qbbulk.CULTURE[0],
            "sets": {n: done[n].get("count") or len(done[n]["ids"]) for n in qbbulk.ICONS},
            "roots": {n: done[n]["roots"] for n in qbbulk.ICONS}, "lists": lists, "ids": ids}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(seed, f, separators=(",", ":"))
    if os.path.exists(PART):
        os.remove(PART)
    print("wrote", OUT, len(ids), "subjects")


if __name__ == "__main__":
    main()
