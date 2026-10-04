#!/usr/bin/env python3
"""
qb_find_store.py — SAFE, READ-ONLY recovery helper.

If QueryBook ever starts up showing 0 facts / no languages, your data is NOT
gone: it lives in a `mystore` folder (its `blocks/`, `index.sqlite`, and
`language_model.json`). This tool searches your computer for every QueryBook
store it can find, counts the facts actually on disk, and prints the exact
command to start the app against the richest one.

It NEVER writes, moves, or deletes anything. Run it from the QueryBook folder:

    python3 qb_find_store.py            # scan sensible default locations
    python3 qb_find_store.py /some/dir  # also scan the directories you name

Then copy-paste the command it prints.
"""
import os, sys, json, sqlite3

def _true_facts(store):
    """Count facts actually indexed on disk, independent of the (cacheable) manifest."""
    idx = os.path.join(store, "index.sqlite")
    if not os.path.isfile(idx):
        return None
    try:
        con = sqlite3.connect("file:%s?mode=ro" % idx, uri=True, timeout=5)
        try:
            for tbl in ("fp", "nuc"):
                try:
                    n = con.execute("SELECT COUNT(*) FROM %s" % tbl).fetchone()[0]
                    if n:
                        return int(n)
                except sqlite3.Error:
                    continue
            return 0
        finally:
            con.close()
    except sqlite3.Error:
        return None

def _manifest_facts(store):
    p = os.path.join(store, "manifest.json")
    try:
        with open(p, encoding="utf-8") as f:
            return int(json.load(f).get("facts", 0))
    except Exception:
        return None

def _languages(store):
    """Return a short description of the learned-language model, if present."""
    p = os.path.join(store, "language_model.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            m = json.load(f)
        langs = m.get("languages") or m.get("langs") or list((m.get("by_lang") or {}).keys())
        if isinstance(langs, dict):
            langs = list(langs.keys())
        size = os.path.getsize(p)
        if langs:
            return "%d language(s): %s" % (len(langs), ", ".join(map(str, langs))[:120])
        return "present (%d bytes)" % size
    except Exception:
        return "present"

def _is_store(d):
    """A store = a directory that has blocks/ AND an index.sqlite or manifest.json."""
    return (os.path.isdir(os.path.join(d, "blocks"))
            and (os.path.isfile(os.path.join(d, "index.sqlite"))
                 or os.path.isfile(os.path.join(d, "manifest.json"))))

def _dir_size(d):
    """Cheap size estimate: files directly in the store dir + its blocks/ dir.
    The blocks hold essentially all the bytes, so this avoids a slow deep walk."""
    total = 0
    for sub in (d, os.path.join(d, "blocks")):
        try:
            for fn in os.listdir(sub):
                try:
                    total += os.path.getsize(os.path.join(sub, fn))
                except OSError:
                    pass
        except OSError:
            pass
    return total

def _human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return "%.1f %s" % (n, unit)
        n /= 1024.0

def _roots():
    """Sensible places a QueryBook store might live, cross-platform."""
    here = os.path.abspath(os.path.dirname(__file__) or ".")
    roots = [here, os.path.dirname(here)]            # this folder + its parent (sibling versions)
    home = os.path.expanduser("~")
    roots += [home]
    for sub in ("Desktop", "Documents", "Downloads", "QueryBook"):
        roots.append(os.path.join(home, sub))
    # Windows drive letters + common external-drive mount points
    if os.name == "nt":
        import string
        for L in string.ascii_uppercase:
            dp = "%s:\\" % L
            if os.path.exists(dp):
                roots.append(dp)
    else:
        for mp in ("/Volumes", "/media", "/mnt"):
            if os.path.isdir(mp):
                for e in os.listdir(mp):
                    roots.append(os.path.join(mp, e))
    roots += [os.path.abspath(a) for a in sys.argv[1:]]
    # de-dup, keep existing
    seen, out = set(), []
    for r in roots:
        r = os.path.abspath(r)
        if r not in seen and os.path.isdir(r):
            seen.add(r); out.append(r)
    return out

def scan(roots, max_depth=4):
    found = {}
    for root in roots:
        base_depth = root.rstrip(os.sep).count(os.sep)
        for cur, dirs, _files in os.walk(root):
            # prune noise and limit depth
            depth = cur.count(os.sep) - base_depth
            if depth >= max_depth:
                dirs[:] = []
            dirs[:] = [d for d in dirs
                       if d not in (".git", "__pycache__", "node_modules", ".cache")]
            if _is_store(cur):
                real = os.path.realpath(cur)
                if real not in found:
                    found[real] = True
                    yield cur

def _best_only(extra_roots):
    """Machine mode for launchers: print ONLY the richest store's absolute path
    (or nothing). Used by START_QUERYBOOK.bat to auto-locate the data folder.
    Fast and targeted — scans a small candidate set, not the whole disk."""
    here = os.path.abspath(os.path.dirname(__file__) or ".")
    roots = [here, os.path.dirname(here)] + [os.path.abspath(r) for r in extra_roots]
    cands = [os.path.join(os.path.expanduser("~"), ".querybook", "store"),
             os.path.abspath("./mystore")]
    for base in roots:
        if not os.path.isdir(base):
            continue
        cands += [os.path.join(base, "mystore"), os.path.join(base, "store"), base]
        try:
            for name in os.listdir(base):
                p = os.path.join(base, name)
                if os.path.isdir(p):
                    cands += [os.path.join(p, "mystore"), os.path.join(p, "store"), p]
        except OSError:
            pass
    best, best_n, seen = None, 0, set()
    for c in cands:
        c = os.path.abspath(c)
        if c in seen:
            continue
        seen.add(c)
        if not os.path.isdir(os.path.join(c, "blocks")):
            continue
        # Manifest first (instant). Only fall back to an index COUNT when the manifest
        # is absent/zero, so a launcher never stalls on a huge index.
        mf = _manifest_facts(c)
        n = mf if mf else (_true_facts(c) or 0)
        if n > best_n:
            best_n, best = n, c
    if best:
        print(best)
        return 0
    return 1

def main():
    # --best <roots...> : quiet mode for the launcher (prints only the best path).
    if "--best" in sys.argv:
        i = sys.argv.index("--best")
        return _best_only(sys.argv[i+1:])
    print("QueryBook store finder — READ-ONLY, nothing is changed.\n")
    roots = _roots()
    print("Searching:")
    for r in roots:
        print("   " + r)
    print()
    results = []
    for store in scan(roots):
        tf = _true_facts(store)
        mf = _manifest_facts(store)
        facts = tf if tf is not None else (mf or 0)
        results.append({
            "path": os.path.abspath(store),
            "facts_on_disk": tf, "facts_manifest": mf, "facts": facts,
            "languages": _languages(store), "size": _dir_size(store),
        })
    if not results:
        print("No QueryBook stores found in the locations above.")
        print("If your data is on an external/USB drive, re-run and pass its path, e.g.:")
        print("   python3 qb_find_store.py E:\\   (Windows)   or   python3 qb_find_store.py /Volumes/MyDrive")
        return 1
    results.sort(key=lambda r: r["facts"], reverse=True)
    print("Found %d store(s), richest first:\n" % len(results))
    for i, r in enumerate(results, 1):
        disk = "unknown" if r["facts_on_disk"] is None else format(r["facts_on_disk"], ",")
        man = "n/a" if r["facts_manifest"] is None else format(r["facts_manifest"], ",")
        print("  [%d] %s" % (i, r["path"]))
        print("      facts on disk: %s   (manifest says: %s)   size: %s"
              % (disk, man, _human(r["size"])))
        if r["languages"]:
            print("      languages: %s" % r["languages"])
        if r["facts_manifest"] is not None and r["facts_on_disk"] not in (None, r["facts_manifest"]):
            print("      NOTE: manifest counter is stale; the app repairs it automatically at boot.")
        print()
    best = results[0]
    print("=" * 64)
    print("To start QueryBook against your real data (%s facts):\n"
          % format(best["facts"], ","))
    if os.name == "nt":
        print('   set QB_DATA_DIR=%s' % best["path"])
        print('   python qb_api.py')
    else:
        print("   QB_DATA_DIR='%s' python3 qb_api.py" % best["path"])
    print()
    print("Nothing was moved or changed. This just tells the app where to look.")
    print("=" * 64)
    return 0

if __name__ == "__main__":
    sys.exit(main())
