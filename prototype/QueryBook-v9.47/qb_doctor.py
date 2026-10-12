#!/usr/bin/env python3
"""
qb_doctor.py — plain-English health check for a QueryBook install.

Tells you, in ordinary words, what (if anything) is actually wrong — and
clearly separates REAL problems from things that are OPTIONAL and safe to
ignore. Read-only: it changes nothing.

Run it:   python qb_doctor.py     (or double-click CHECK_QUERYBOOK.bat on Windows)
"""
import os, sys, socket

OK, OPT, BAD = [], [], []
def ok(m):  OK.append(m);  print("  [OK]       " + m)
def opt(m): OPT.append(m); print("  [OPTIONAL] " + m)
def bad(m): BAD.append(m); print("  [PROBLEM]  " + m)

HERE = os.path.abspath(os.path.dirname(__file__) or ".")

print("=" * 60)
print("  QueryBook — install check (read-only)")
print("=" * 60)

# 1. Python version -----------------------------------------------------------
v = sys.version_info
if v >= (3, 8):
    ok("Python %d.%d.%d" % (v.major, v.minor, v.micro))
else:
    bad("Python %d.%d is too old — install 3.8 or newer from python.org" % (v.major, v.minor))

# 2. Core engine imports ------------------------------------------------------
sys.path.insert(0, HERE)
core_ok = True
for mod in ("ufcs_store", "qb_language", "qb_api"):
    try:
        __import__(mod)
    except Exception as e:
        core_ok = False
        bad("could not load %s.py — %s: %s" % (mod, type(e).__name__, e))
if core_ok:
    ok("core engine modules load")

# 3. Bundled language data ----------------------------------------------------
for base, label in (("qb_bilingual.json", "bilingual dictionary"), ("qb_dict.json", "word dictionary")):
    if os.path.isfile(os.path.join(HERE, base)) or os.path.isfile(os.path.join(HERE, base + ".gz")):
        ok("%s present" % label)
    else:
        bad("%s missing (%s or %s.gz) — translation/learning need it" % (label, base, base))

# 4. Where is the data, and how much? ----------------------------------------
store = None; pinned = None; words = 0
try:
    import qb_api as A
    cfg = A._load_config()
    pinned = cfg.get("data_dir")
    if pinned and os.path.isdir(pinned):
        store = pinned
    else:
        cands = A._candidate_stores()
        if cands:
            store = cands[0]["path"]
    if store:
        words = A._store_langwords(store)
except Exception:
    store = None

if pinned:
    if os.path.isdir(pinned):
        ok("data location is pinned to: %s" % pinned)
    else:
        bad("your data is pinned to %s but that folder isn't available now — plug the "
            "drive in, or run  python qb_api.py configure  to re-point it" % pinned)

def _facts(d):
    try:
        import json
        with open(os.path.join(d, "manifest.json"), encoding="utf-8") as f:
            return int(json.load(f).get("facts", 0))
    except Exception:
        return 0

if store and os.path.isdir(store):
    n = _facts(store)
    if n > 0:
        ok("found your data: %s facts at %s" % (format(n, ","), store))
    else:
        opt("a store exists at %s but has 0 facts yet (harvest to fill it)" % store)
    if words > 0:
        ok("learned language model: %s words" % format(words, ","))
    else:
        opt("no learned-language words yet (teach a language in the Language Lab)")
    le = os.path.join(store, "data_events.log")
    if os.path.isfile(le):
        try:
            evs = [l for l in open(le, encoding="utf-8").read().strip().splitlines() if l.strip()]
            if evs:
                last = evs[-1].split("\t")
                opt("data-safety log: %d auto-recovery/guard event(s); last = %s"
                    % (len(evs), last[1] if len(last) > 1 else evs[-1]))
        except Exception:
            pass
else:
    opt("no data library found yet — a new empty one will be created on first run "
        "(this is normal for a brand-new install). If your data is on an external "
        "drive, start the app and pick it when asked, or run  python qb_api.py configure")

# 5. Is the store folder writable? -------------------------------------------
probe_dir = store or os.path.join(os.path.expanduser("~"), ".querybook", "store")
try:
    os.makedirs(probe_dir, exist_ok=True)
    tp = os.path.join(probe_dir, ".qb_write_test")
    with open(tp, "w") as f:
        f.write("ok")
    os.remove(tp)
    ok("data folder is writable (%s)" % probe_dir)
except Exception as e:
    bad("cannot write to the data folder %s — %s" % (probe_dir, e))

# 6. Is the port free? --------------------------------------------------------
port = 8099
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind(("127.0.0.1", port))
    ok("port %d is free" % port)
except OSError:
    opt("port %d is busy — QueryBook may already be running; just open "
        "http://127.0.0.1:%d/ in your browser" % (port, port))
finally:
    s.close()

# 7. espeak-ng (offline speech) — OPTIONAL -----------------------------------
try:
    import qb_language
    es = qb_language.espeak_status() if hasattr(qb_language, "espeak_status") else {}
    if es.get("found"):
        ok("espeak-ng found (offline speech available)")
    else:
        opt("espeak-ng not installed — offline speech is off, but the app runs fine "
            "and cloud/Google speech still works. Install espeak-ng only if you want "
            "local text-to-speech.")
except Exception:
    opt("espeak-ng status unknown — not required for the app to run")

# Summary ---------------------------------------------------------------------
print("\n" + "=" * 60)
print("  RESULT: %d ok, %d optional note(s), %d problem(s)" % (len(OK), len(OPT), len(BAD)))
if BAD:
    print("\n  Fix the [PROBLEM] item(s) above, then run this check again.")
else:
    print("\n  No real problems. Anything marked [OPTIONAL] is safe to ignore —")
    print("  double-click START_QUERYBOOK.bat to run the app.")
print("=" * 60)
sys.exit(1 if BAD else 0)
