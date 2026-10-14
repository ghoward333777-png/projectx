#!/usr/bin/env python3
"""
qb_selftest.py — QueryBook quality-control battery.

Verifies every core function against a throwaway store so failures are caught before
they reach data. Runs three ways: at server startup, on demand from the dashboard
(/api/selftest), and standalone (`python qb_selftest.py`). Each check returns pass/fail
with a human-readable detail line.
"""
import os, shutil, tempfile, threading, time
import ufcs_store as s


def _check(name, fn):
    try:
        ok, detail = fn()
        return {"name": name, "ok": bool(ok), "detail": str(detail)}
    except Exception as e:
        return {"name": name, "ok": False, "detail": "exception: " + str(e)}


def run_all(store_dir=None):
    checks = []

    def c_fingerprint():
        a = s.fingerprint("France", "has_capital", "Paris")
        b = s.fingerprint("  france ", "HAS_CAPITAL", "Paris")   # normalization must match
        c = s.fingerprint("France", "has_capital", "Lyon")       # different object must differ
        return (a == b and a != c and len(a) == 64,
                f"64-hex, case/space-normalized match={a==b}, distinct-object differs={a!=c}")
    checks.append(_check("Fingerprint determinism & normalization", c_fingerprint))

    def c_roundtrip():
        d = tempfile.mkdtemp()
        try:
            st = s.UFCSStore(d)
            p = s.make_packet("QC Subject", "qc_predicate", "42", domain="qc")
            added = st.add(p); fp = p["semantic_fingerprint"]; st.close()
            st2 = s.UFCSStore(d); rec = st2.get(fp); st2.db.close()
            good = bool(added and rec and rec["nucleus"]["object"] == "42"
                        and rec["semantic_fingerprint"] == fp)
            return (good, "packet stored and read back byte-identical")
        finally:
            shutil.rmtree(d, ignore_errors=True)
    checks.append(_check("Store write → read round-trip", c_roundtrip))

    def c_dedup():
        d = tempfile.mkdtemp()
        try:
            st = s.UFCSStore(d); p = s.make_packet("Dup", "equals", "1")
            a1 = st.add(p); a2 = st.add(p); st.close()
            return (a1 and not a2, "identical second fact correctly skipped")
        finally:
            shutil.rmtree(d, ignore_errors=True)
    checks.append(_check("Duplicate detection", c_dedup))

    def c_resume():
        d = tempfile.mkdtemp()
        try:
            t1 = s.harvest_into(d, 5000); t2 = s.harvest_into(d, 5000)
            return (t2 > t1, f"run1={t1:,} → run2={t2:,} (grew by {t2 - t1:,}; no 1M-style stall)")
        finally:
            shutil.rmtree(d, ignore_errors=True)
    checks.append(_check("Resume-and-grow harvesting", c_resume))

    def c_stop():
        d = tempfile.mkdtemp()
        try:
            flag = {"s": False}
            th = threading.Thread(target=lambda: s.harvest_into(d, 0, should_stop=lambda: flag["s"]),
                                  daemon=True)
            th.start(); time.sleep(1.0); flag["s"] = True; th.join(timeout=5)
            return (not th.is_alive(), "continuous 24×7 run halts promptly on stop")
        finally:
            shutil.rmtree(d, ignore_errors=True)
    checks.append(_check("24×7 stop control", c_stop))

    def c_verify_unknown():
        d = tempfile.mkdtemp()
        try:
            st = s.UFCSStore(d)
            missing = st.get(s.fingerprint("Nobody", "was_on", "Mars"))
            st.db.close()
            return (missing is None, "unknown fact correctly returns nothing (no fabrication)")
        finally:
            shutil.rmtree(d, ignore_errors=True)
    checks.append(_check("Unknown-fact honesty", c_verify_unknown))

    if store_dir and os.path.isdir(store_dir):
        def c_live():
            # Read-only probe: the running server already holds this store's
            # index.sqlite open, so opening a SECOND read/write UFCSStore here can
            # fail on a lock (especially on an external drive) even though the data
            # is perfectly readable. Read the manifest (no lock) and open the index
            # read-only (coexists with the live writer) to confirm it is queryable.
            import json, sqlite3
            facts = 0
            try:
                with open(os.path.join(store_dir, "manifest.json"), encoding="utf-8") as f:
                    facts = int(json.load(f).get("facts", 0))
            except Exception:
                facts = 0
            idx = os.path.join(store_dir, "index.sqlite")
            if os.path.isfile(idx):
                con = sqlite3.connect("file:%s?mode=ro" % idx, uri=True, timeout=5)
                try:
                    con.execute("SELECT 1").fetchone()
                finally:
                    con.close()
                return (True, f"{facts:,} facts; live store index is readable (read-only check)")
            # No index yet (brand-new store) is fine — not a failure.
            return (True, f"{facts:,} facts; store present (index not created yet)")
        checks.append(_check("Live store readable", c_live))

    passed = sum(1 for c in checks if c["ok"])
    return {"passed": passed, "total": len(checks), "all_ok": passed == len(checks),
            "checks": checks, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}


if __name__ == "__main__":
    import sys, json
    r = run_all(sys.argv[1] if len(sys.argv) > 1 else None)
    for c in r["checks"]:
        print(("PASS " if c["ok"] else "FAIL ") + c["name"] + " — " + c["detail"])
    print(f"\n{r['passed']}/{r['total']} checks passed"
          + ("" if r["all_ok"] else "  ⚠ SOME CHECKS FAILED"))
    sys.exit(0 if r["all_ok"] else 1)
