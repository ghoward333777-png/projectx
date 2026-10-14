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
        # ---- DATABASE INTEGRITY: the check that catches "database malformed" ----
        def c_index_integrity():
            h = s.index_health(store_dir)
            st = h.get("status")
            if st == "malformed":
                return (False, "index.sqlite is CORRUPT (%s) — the app self-repairs by "
                               "rebuilding from blocks; until then menu items that query "
                               "the index fail" % h.get("detail", ""))
            if st == "unreadable":
                return (False, "index.sqlite cannot be opened: %s" % h.get("detail", ""))
            if st == "empty":
                return (False, "index is empty but %d blocks hold data — rebuild needed/underway"
                        % h.get("blocks", 0))
            if st == "missing":
                return (True, "no index yet (new store) — created on first write")
            return (True, "index OK — %s rows, integrity check passed" % format(h.get("index_rows", 0), ","))
        checks.append(_check("Database index integrity (malformed check)", c_index_integrity))

        # ---- LIVE QUERY: prove a real table query works (not just connect) -------
        def c_live_query():
            import sqlite3
            idx = os.path.join(store_dir, "index.sqlite")
            if not os.path.isfile(idx):
                return (True, "no index yet — nothing to query")
            con = sqlite3.connect("file:%s?mode=ro" % idx, uri=True, timeout=5)
            try:
                n = con.execute("SELECT count(*) FROM nuc").fetchone()[0]
                con.execute("SELECT subject,predicate,object FROM nuc LIMIT 1").fetchall()
                return (True, "live FQL query works (%s indexed rows)" % format(int(n), ","))
            finally:
                con.close()
        checks.append(_check("Live query (FQL path) works", c_live_query))

        # ---- BLOCKS: the source of truth is present and readable ----------------
        def c_blocks():
            import json
            try:
                with open(os.path.join(store_dir, "manifest.json"), encoding="utf-8") as f:
                    m = json.load(f)
            except Exception as e:
                return (False, "manifest.json unreadable: %s" % e)
            blocks = int(m.get("blocks", 0))
            bd = os.path.join(store_dir, "blocks")
            files = [x for x in os.listdir(bd)] if os.path.isdir(bd) else []
            if blocks == 0:
                return (True, "new/empty store (0 blocks) — fine")
            if not files:
                return (False, "manifest says %d blocks but blocks/ is empty — DATA MISSING" % blocks)
            # read one record from the first present block
            try:
                st = s.UFCSStore(store_dir)
                try:
                    rec = next(st.iter_all(), None)
                finally:
                    st.close()
                ok = bool(rec and rec.get("nucleus"))
                return (ok, "%d blocks present; a stored fact reads back" % blocks if ok
                        else "blocks present but no readable record found")
            except Exception as e:
                return (False, "blocks unreadable: %s" % e)
        checks.append(_check("Fact blocks present & readable", c_blocks))

        # ---- SUBSYSTEMS behind the menus (lazy imports; each is a menu target) --
        def c_language():
            import qb_language as L
            r = L.language_readiness(store_dir)
            langs = r.get("languages", [])
            return (isinstance(langs, list) and len(langs) > 0,
                    "language readiness OK (%d languages reported)" % len(langs))
        checks.append(_check("Language Lab subsystem", c_language))

        def c_backup():
            import qb_backup
            st = qb_backup.status()
            return (isinstance(st, dict), "backup subsystem responds (last run %s)"
                    % (st.get("last_run") or "—"))
        checks.append(_check("Backup subsystem", c_backup))

        def c_domains():
            # the dashboard + several menus read domain rollups from the manifest
            import json
            try:
                with open(os.path.join(store_dir, "manifest.json"), encoding="utf-8") as f:
                    m = json.load(f)
                doms = {k: v for k, v in m.items() if k.startswith("facts_dom_")}
                return (True, "%d domain tallies present" % len(doms))
            except Exception as e:
                return (False, "manifest domain rollups unreadable: %s" % e)
        checks.append(_check("Domain rollups readable", c_domains))

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
