#!/usr/bin/env python3
"""Tests of the shared core's data safety: concurrent writers, crash-safe transactions,
damage detection (the app refuses to write to a damaged database), backups and restore."""
import os, sys, tempfile, threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "_core"))
import qbcore as core

SCHEMA = ["CREATE TABLE t (id INTEGER PRIMARY KEY, k TEXT UNIQUE, v INTEGER)"]


def main():
    c = core.Checks()
    with tempfile.TemporaryDirectory() as tmp:
        st = core.Store(tmp, "t", SCHEMA)
        # 16 threads x 200 writes, each its own transaction
        errors = []

        def worker(n):
            try:
                for i in range(200):
                    with st.write() as db:
                        db.execute("INSERT INTO t(k, v) VALUES(?, ?)", ("%d-%d" % (n, i), i))
            except Exception as e:
                errors.append(repr(e))
        ts = [threading.Thread(target=worker, args=(n,)) for n in range(16)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        c.check("16 concurrent writers, 3,200 writes, no errors", not errors and st.scalar("SELECT count(*) FROM t") == 3200, errors[:3])
        # a failing transaction leaves nothing behind
        try:
            with st.write() as db:
                db.execute("INSERT INTO t(k, v) VALUES('partial', 1)")
                db.execute("INSERT INTO t(k, v) VALUES('0-0', 1)")       # violates UNIQUE -> whole transaction rolls back
        except Exception:
            pass
        c.check("a failed transaction is rolled back completely", st.scalar("SELECT count(*) FROM t WHERE k = 'partial'") == 0)
        b1 = st.backup("test", force=True)
        c.check("backup written and checked", b1 and os.path.exists(b1))
        c.check("unchanged data is not backed up twice", st.backup("again") == b1)
        for i in range(12):
            with st.write() as db:
                db.execute("INSERT INTO t(k, v) VALUES(?, 0)", ("extra-%d" % i,))
            st.backup("n%d" % i, force=True)
        c.check("only the newest %d backups are kept" % core.BACKUPS_KEPT, len(st.backups()) == core.BACKUPS_KEPT)
        good = st.backups()[0]["path"]
        st.conn().close()
        st._local.db = None
        # damage the database file
        with open(st.path, "r+b") as f:
            f.seek(0)
            f.write(b"\x00" * 100)
        for ext in ("-wal", "-shm"):
            if os.path.exists(st.path + ext):
                os.remove(st.path + ext)
        st2 = core.Store(tmp, "t", SCHEMA)
        c.check("damaged database is detected at start-up", st2.read_only and st2.damage)
        try:
            with st2.write() as db:
                db.execute("INSERT INTO t(k, v) VALUES('x', 1)")
            c.check("damaged database refuses writes", False)
        except core.DatabaseDamaged:
            c.check("damaged database refuses writes", True)
        st2.restore(good)
        c.check("damaged file kept aside, not deleted", any(n.startswith("t.sqlite.replaced-") for n in os.listdir(tmp)))
        st3 = core.Store(tmp, "t", SCHEMA)
        c.check("restore from backup gives a working database", not st3.read_only and st3.scalar("SELECT count(*) FROM t") >= 3200)
        with st3.write() as db:
            db.execute("INSERT INTO t(k, v) VALUES('after-restore', 1)")
        c.check("writes work again after restore", st3.scalar("SELECT count(*) FROM t WHERE k = 'after-restore'") == 1)
        c.check("schema version recorded", st3.meta_get("schema_version") == "1")
    for app in ("language", "stem", "facts"):
        c.check("%s carries the current core" % app, core.core_matches_master(os.path.join(ROOT, app)))
    return c.report("Shared core")


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
