#!/usr/bin/env python3
"""find_facts — READ-ONLY: list every copy of every bulk dataset (shard) on every drive, with the facts it holds.

Nothing is written, moved or deleted. Run it when a count on the Control Panel looks wrong, to see where the facts are:

    python tools/find_facts.py                      (looks in the usual places)
    python tools/find_facts.py D:\\QB\\commons        (also looks in this shared folder)

For each copy it prints: facts kept, facts staged (written, waiting for the end-of-part pass), state, last error, size, and
whether the file could be opened at all.
"""
import glob, json, os, sqlite3, sys, urllib.request


def ro(path):
    return sqlite3.connect("file:%s?mode=ro" % urllib.request.pathname2url(os.path.abspath(path)), uri=True, timeout=5)


def look(path):
    size = sum(os.path.getsize(path + x) for x in ("", "-wal") if os.path.exists(path + x))
    try:
        db = ro(path)
        try:
            meta = {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM meta")}
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            db.close()
        return {"facts": meta.get("facts") or 0, "staged": meta.get("staged") or 0, "state": meta.get("state"),
                "error": meta.get("error"), "dups_removed": meta.get("duplicates_removed") or 0,
                "has_stage": "stage" in tables, "size_gb": size / 1e9, "open": "ok"}
    except Exception as e:
        return {"facts": None, "size_gb": size / 1e9, "open": "CANNOT OPEN: %s: %s" % (type(e).__name__, e)}


def places(extra):
    home = os.path.expanduser("~")
    out = list(extra)
    out += glob.glob(os.path.join(home, "QueryBook-Work", "*"))                 # working copies (internal drive)
    out += [os.path.join(home, "QueryBook-Data", "commons", "shards")]
    for e in extra:
        out.append(os.path.join(e, "shards"))
    if os.name == "nt":
        for d in "CDEFGHIJ":
            out += glob.glob("%s:\\QB\\commons\\shards" % d) + glob.glob("%s:\\QueryBook*\\commons\\shards" % d)
    seen, res = set(), []
    for p in out:
        p = os.path.normcase(os.path.abspath(p))
        if os.path.isdir(p) and p not in seen:
            seen.add(p)
            res.append(p)
    return res


def main(argv):
    rows = []
    for folder in places(argv[1:]):
        for f in sorted(glob.glob(os.path.join(folder, "*.sqlite"))):
            rows.append((os.path.basename(f)[:-7], f, look(f)))
    if not rows:
        print("No shard files found. Run again with your shared folder, e.g.  python tools/find_facts.py D:\\QB\\commons")
        return 1
    by = {}
    for key, f, r in rows:
        by.setdefault(key, []).append((f, r))
    for key in sorted(by):
        print(key)
        for f, r in by[key]:
            if r["facts"] is None:
                print("   %-70s  %7.1f GB   %s" % (f, r["size_gb"], r["open"]))
            else:
                print("   %-70s  %7.1f GB   facts %15s   staged %12s   state %-8s %s" % (
                    f, r["size_gb"], format(r["facts"], ","), format(r["staged"], ","), r["state"] or "-",
                    ("error: " + str(r["error"])[:80]) if r.get("error") else ""))
    best = sum(max((r["facts"] or 0) + (r.get("staged") or 0) for f, r in v) for v in by.values())
    print("\nLargest copy of each dataset, added up: %s facts" % format(best, ","))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
