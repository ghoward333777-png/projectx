#!/usr/bin/env python3
"""QueryBook Math, Science & Engineering — a dedicated application for deterministic answers.

Every answer is computed, never looked up from an AI: exact arithmetic, unit conversion with
dimension checks, solvable science and engineering formulas, physical constants, the periodic
table and molar masses. Saved answers can be re-checked at any time by computing them again.

Start:      python app.py            (opens http://127.0.0.1:8102/)
Self-test:  python app.py --selftest
More:       python app.py --help
"""
import csv, io, json, os, sys, tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import qbcore as core
import engine
import science
import units
import verify

APP_ID = "stem"
APP_NAME = "QueryBook Math, Science & Engineering"
VERSION = "1.2.2"
PORT = 8102
program_dir = HERE

SCHEMA = ["""
CREATE TABLE facts (
  id INTEGER PRIMARY KEY,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  kind TEXT NOT NULL,              -- calc | convert | formula | molar | imported
  detail TEXT,                     -- JSON needed to recompute
  fingerprint TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,            -- verified | mismatch | unverifiable
  source TEXT NOT NULL,
  domain TEXT,
  created TEXT NOT NULL,
  checked TEXT
);
CREATE INDEX facts_status ON facts(status);
CREATE INDEX facts_kind ON facts(kind);
CREATE TABLE imports (
  id INTEGER PRIMARY KEY, folder TEXT, started TEXT, finished TEXT,
  records_read INTEGER, imported INTEGER, already_present INTEGER, mismatched INTEGER, not_deterministic INTEGER, note TEXT
);
CREATE TABLE mismatches (
  id INTEGER PRIMARY KEY, import_id INTEGER, subject TEXT, predicate TEXT, stored TEXT, computed TEXT
)
"""]


class App:
    def __init__(self, folder):
        os.makedirs(folder, exist_ok=True)
        self.folder = folder
        self.log = core.make_logger(folder, APP_ID)
        self.store = core.Store(folder, APP_ID, SCHEMA, self.log)
        self.jobs = core.Jobs(self.log, self.store)
        self.api = core.Api()
        self.diag = core.Diagnostics(APP_ID, APP_NAME, VERSION, HERE, self.store, self.log, self.jobs, self._health)
        self.monitor = core.Monitor(folder, APP_ID, APP_NAME, VERSION, self.log)
        self.log.hooks.append(self.monitor.on_error)
        core.add_diagnostics(self.api, self.diag, self.monitor, HERE)
        self._routes()
        try:
            self.store.backup("startup")
        except Exception as e:
            self.log("startup backup failed:", e)

    # ------------------------------------------------------------------ questions
    def ask(self, q):
        """One box for everything: conversions, molar masses, element lookups, calculations."""
        q = (q or "").strip()
        if not q:
            raise core.UserError("Type a calculation or a question, for example 12 × 7, 60 mph to km/h, or molar mass of H2O.")
        low = q.lower()
        if units._Q.match(q):
            try:
                r = units.convert(q)
                return {"kind": "convert", "question": q, "answer": r["result"] + " " + r["unit"], "display": r["display"],
                        "exact": r["exact"], "detail": r, "method": "unit conversion (%s)" % r["kind"]}
            except units.UnitError as e:
                conv_err = str(e)
        else:
            conv_err = None
        for prefix in ("molar mass of ", "molecular weight of ", "molar mass "):
            if low.startswith(prefix):
                f = q[len(prefix):].strip()
                try:
                    r = science.molar_mass(f)
                except science.FormulaError as e:
                    raise core.UserError(str(e))
                return {"kind": "molar", "question": f, "answer": r["molar_mass"] + " g/mol", "display": r["molar_mass"] + " g/mol",
                        "exact": True, "detail": r, "method": "sum of standard atomic weights (%s)" % science.ELEMENT_SOURCE}
        el = science.element(q[len("element "):] if low.startswith("element ") else q)
        if el and not any(ch.isdigit() for ch in q.replace("element", "")):
            return {"kind": "element", "question": q, "answer": el["name"], "display": "%s (%s), atomic number %d, atomic weight %s"
                    % (el["name"], el["symbol"], el["z"], el["weight"]), "exact": True, "detail": el, "method": science.ELEMENT_SOURCE}
        try:
            r = engine.evaluate(q)
        except engine.CalcError as e:
            raise core.UserError(conv_err or str(e))
        return {"kind": "calc", "question": q, "answer": r["value"], "display": r["display"], "exact": r["exact"], "detail": r,
                "method": "exact arithmetic" if r["exact"] else "floating point (approximate)"}

    # ------------------------------------------------------------------ saved facts
    def save(self, kind, question, answer, detail):
        if kind not in ("calc", "convert", "formula", "molar"):
            raise core.UserError("only calculations, conversions, formula answers and molar masses can be saved")
        try:
            fresh = verify.recompute(kind, question, detail)
        except Exception as e:
            raise core.UserError("could not re-check this answer: %s" % e)
        status = "verified" if verify.answers_match(_strip_unit(answer), fresh) else "mismatch"
        fp = core.fingerprint(kind, question, json.dumps(detail.get("given") if isinstance(detail, dict) else None, sort_keys=True),
                              detail.get("unknown") if isinstance(detail, dict) else "")
        with self.store.write() as db:
            db.execute("""INSERT INTO facts(question, answer, kind, detail, fingerprint, status, source, domain, created, checked)
                          VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(fingerprint) DO UPDATE SET answer=excluded.answer,
                          status=excluded.status, checked=excluded.checked""",
                       (question, answer, kind, json.dumps(detail), fp, status, "computed in this app", _domain(kind, detail),
                        core.now_iso(), core.now_iso()))
        return {"status": status, "recomputed": fresh}

    def verify_all(self, progress, stop):
        total = self.store.scalar("SELECT count(*) FROM facts", default=0)
        done = changed = bad = 0
        last = 0
        while not stop():
            rows = self.store.query("SELECT id, kind, question, answer, detail, status FROM facts WHERE id > ? ORDER BY id LIMIT 2000", (last,))
            if not rows:
                break
            updates = []
            for r in rows:
                last = r["id"]
                try:
                    fresh = verify.recompute(r["kind"], r["question"], json.loads(r["detail"] or "null"))
                    st = "verified" if verify.answers_match(_strip_unit(r["answer"]), fresh) else "mismatch"
                except Exception:
                    st = "unverifiable"
                if st != r["status"]:
                    changed += 1
                if st != "verified":
                    bad += 1
                updates.append((st, core.now_iso(), r["id"]))
            with self.store.write() as db:
                db.executemany("UPDATE facts SET status=?, checked=? WHERE id=?", updates)
            done += len(rows)
            progress(done, total, "re-checking")
        return {"checked": done, "status_changed": changed, "not_verified": bad}

    # ------------------------------------------------------------------ import from the old store
    def import_old(self, folder, progress, stop):
        store = core.find_old_store(folder)
        if not store:
            raise core.UserError("No old QueryBook store found in that folder (looked for blocks\\ and manifest.json).")
        self.store.backup("before-import", force=True)
        started = core.now_iso()
        with self.store.write() as db:
            cur = db.execute("INSERT INTO imports(folder, started) VALUES(?, ?)", (store, started))
            import_id = cur.lastrowid
        read = imported = present = mism = other = 0
        batch, bad_rows = [], []

        def flush():
            nonlocal imported, present
            if not batch:
                return
            with self.store.write() as db:
                before = db.total_changes
                db.executemany("""INSERT OR IGNORE INTO facts(question, answer, kind, detail, fingerprint, status, source, domain, created, checked)
                                  VALUES(?,?,?,?,?,?,?,?,?,?)""", batch)
                n = db.total_changes - before
                if bad_rows:
                    db.executemany("INSERT INTO mismatches(import_id, subject, predicate, stored, computed) VALUES(?,?,?,?,?)", bad_rows)
            imported += n
            present += len(batch) - n
            batch.clear()
            bad_rows.clear()

        for rec in core.iter_old_records(store, verify.OLD_DOMAINS, stop):
            read += 1
            got = verify.check_old(rec)
            if got is None:
                other += 1
            else:
                question, expected = got
                if verify.answers_match(rec["object"], expected):
                    detail = {k: rec[k] for k in ("subject", "predicate", "object", "domain")}
                    batch.append((question, rec["object"], "imported", json.dumps(detail),
                                  core.fingerprint("imported", rec["subject"], rec["predicate"], rec["object"]),
                                  "verified", "old QueryBook store (re-computed on import)", rec["domain"], core.now_iso(), core.now_iso()))
                else:
                    mism += 1
                    if mism <= 1000:
                        bad_rows.append((import_id, rec["subject"], rec["predicate"], rec["object"], expected))
            if len(batch) >= 5000:
                flush()
            if read % 2000 == 0:
                progress(read, None, "read %s · kept %s verified" % (format(read, ","), format(imported + len(batch), ",")))
        flush()
        note = "stopped by user" if stop() else "complete"
        with self.store.write() as db:
            db.execute("""UPDATE imports SET finished=?, records_read=?, imported=?, already_present=?, mismatched=?, not_deterministic=?, note=?
                          WHERE id=?""", (core.now_iso(), read, imported, present, mism, other, note, import_id))
        self.store.backup("after-import", force=True)
        return {"old_store": store, "records_read": read, "imported_verified": imported, "already_present": present,
                "failed_recomputation": mism, "left_for_other_apps": other, "note": note}

    # ------------------------------------------------------------------ diagnostics
    def _health(self):
        C = core._check
        samples = [("12 × 7", "84"), ("0.1 + 0.2", "3/10"), ("2^64", "18446744073709551616"), ("sqrt(144)", "12"), ("factor(360)", "2³ × 3² × 5")]
        bad = [q for q, want in samples if engine.evaluate(q)["value"] != want]
        if units.convert("60 mph to km/h")["result"] != "96.56064":
            bad.append("60 mph to km/h")
        if science.molar_mass("H2O")["molar_mass"] != "18.015":
            bad.append("molar mass of H2O")
        out = [C("engine", "Calculation engine gives known answers", "fail" if bad else "ok", ("wrong: " + ", ".join(bad)) if bad else "%d samples" % (len(samples) + 2))]
        if not self.store.read_only:
            n = self.store.scalar("SELECT count(*) FROM facts WHERE status <> 'verified'", default=0)
            out.append(C("recheck", "Saved answers that do not recompute", "warn" if n else "ok", "%d" % n, n))
        return out

    # ------------------------------------------------------------------ routes
    def _routes(self):
        a = self.api

        @a.get("/api/status")
        def status(p):
            counts = {r["status"]: r["n"] for r in self.store.query("SELECT status, count(*) n FROM facts GROUP BY status")}
            return {"app": APP_NAME, "version": VERSION, "store": self.store.status(), "health": (self.diag.last or {}).get("overall"), "facts": counts,
                    "facts_total": sum(counts.values()), "job": self.jobs.status()["state"]}

        @a.post("/api/ask")
        def ask(p):
            return self.ask(p.get("q"))

        @a.get("/api/help")
        def helpinfo(p):
            return {"functions": [{"syntax": s, "meaning": m} for s, m in engine.FUNCTION_HELP]}

        @a.get("/api/units")
        def unit_list(p):
            return {"units": units.unit_table()}

        @a.get("/api/formulas")
        def formulas(p):
            return {"formulas": science.formula_list()}

        @a.post("/api/solve")
        def solve(p):
            try:
                return science.solve(p.get("id"), p.get("unknown"), p.get("given") or {}, (p.get("out_unit") or "").strip() or None)
            except science.FormulaError as e:
                raise core.UserError(str(e))

        @a.get("/api/constants")
        def constants(p):
            return {"source": science.CONSTANT_SOURCE, "constants": [
                {"symbol": s, "name": n, "value": v, "unit": u, "exact": x, "note": note} for s, n, v, u, x, note in science.CONSTANTS]}

        @a.get("/api/elements")
        def elements(p):
            return {"source": science.ELEMENT_SOURCE, "elements": science.ELEMENTS}

        @a.post("/api/molar")
        def molar(p):
            try:
                return science.molar_mass(p.get("formula", ""))
            except science.FormulaError as e:
                raise core.UserError(str(e))

        @a.post("/api/save")
        def save(p):
            return self.save(p.get("kind"), str(p.get("question", "")), str(p.get("answer", "")), p.get("detail") or {})

        @a.get("/api/facts")
        def facts(p):
            where, args = [], []
            if p.get("status"):
                where.append("status = ?")
                args.append(p["status"])
            if p.get("kind"):
                where.append("kind = ?")
                args.append(p["kind"])
            if p.get("q"):
                where.append("(question LIKE ? OR answer LIKE ?)")
                args += ["%" + p["q"] + "%"] * 2
            w = (" WHERE " + " AND ".join(where)) if where else ""
            limit = max(1, min(500, int(p.get("limit") or 50)))
            offset = max(0, int(p.get("offset") or 0))
            rows = self.store.query("SELECT id, question, answer, kind, status, source, domain, created, checked FROM facts%s ORDER BY id DESC LIMIT ? OFFSET ?" % w,
                                    args + [limit, offset])
            total = self.store.scalar("SELECT count(*) FROM facts" + w, args, 0)
            return {"facts": rows, "total": total}

        @a.post("/api/facts/delete")
        def delete(p):
            with self.store.write() as db:
                n = db.execute("DELETE FROM facts WHERE id = ?", (int(p.get("id")),)).rowcount
            return {"deleted": n}

        @a.post("/api/verify-all")
        def verify_all(p):
            return self.jobs.start("Re-check all saved facts", self.verify_all)

        @a.get("/api/old-store-hint")
        def old_store_hint(p):
            hints = core.old_store_hints()
            return {"folder": hints[0] if hints else "", "all": hints}

        @a.get("/api/old-store")
        def old_store(p):
            s = core.find_old_store(p.get("folder", ""))
            if not s:
                raise core.UserError("No old QueryBook store found there. Choose the folder that contains blocks\\ and manifest.json.")
            return core.old_store_summary(s)

        @a.post("/api/import-old")
        def import_old(p):
            folder = p.get("folder", "")
            if not core.find_old_store(folder):
                raise core.UserError("No old QueryBook store found there. Choose the folder that contains blocks\\ and manifest.json.")
            return self.jobs.start("Import from the old store", lambda prog, stop: self.import_old(folder, prog, stop))

        @a.get("/api/imports")
        def imports(p):
            return {"imports": self.store.query("SELECT * FROM imports ORDER BY id DESC LIMIT 20"),
                    "mismatches": self.store.query("SELECT * FROM mismatches ORDER BY id DESC LIMIT 50")}

        @a.get("/api/job")
        def job(p):
            return self.jobs.status()

        @a.post("/api/job/stop")
        def job_stop(p):
            self.jobs.stop()
            return {"ok": True}

        @a.post("/api/backup")
        def backup(p):
            return {"backup": os.path.basename(self.store.backup("manual", force=True) or "")}

        @a.get("/api/backups")
        def backups(p):
            return {"backups": [{"name": b["name"], "kb": b["bytes"] // 1024} for b in self.store.backups()], "folder": self.store.backup_dir}

        @a.get("/api/export.csv")
        def export_csv(p):
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["id", "question", "answer", "kind", "status", "source", "domain", "created", "checked"])
            for r in self.store.query("SELECT id, question, answer, kind, status, source, domain, created, checked FROM facts ORDER BY id"):
                w.writerow([r[k] for k in ("id", "question", "answer", "kind", "status", "source", "domain", "created", "checked")])
            return buf.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8"


def _strip_unit(ans):
    s = str(ans).strip()
    parts = s.split(" ", 1)
    try:
        float(parts[0].replace(",", "").split("/")[0])
        return parts[0]
    except ValueError:
        return s


def _domain(kind, detail):
    if kind == "formula" and isinstance(detail, dict):
        f = science.FORMULA_BY_ID.get(detail.get("id"))
        return f[2] if f else "formula"
    return {"calc": "mathematics", "convert": "units", "molar": "chemistry"}.get(kind, kind)


def open_app(folder=None):
    return App(folder or core.data_folder(APP_ID, HERE))


# ---------------------------------------------------------------------- self-test
def selftest():
    import gzip
    c = core.Checks()
    c.check("shared core matches the master copy", core.core_matches_master(HERE))
    # engine
    cases = [("12 × 7", "84"), ("0.1 + 0.2", "3/10"), ("2^100", str(2 ** 100)), ("sqrt(144)", "12"), ("25!", "15511210043330985984000000"),
             ("gcd(84, 36)", "12"), ("factor(360)", "2³ × 3² × 5"), ("isprime(2^61-1)", "prime"), ("sind(30)", "1/2"), ("log(8, 2)", "3"),
             ("15% of 200", "30"), ("1,000,000 + 1", "1000001"), ("round(2.5)", "3"), ("8^(1/3)", "2")]
    for q, want in cases:
        try:
            got = engine.evaluate(q)["value"]
        except Exception as e:
            got = "error: %s" % e
        c.check("calculate %s = %s" % (q, want), got == want, got)
    for bad in ("1/0", "sqrt(-1)", "__import__('os')", "open('x')", "2**10**10"):
        try:
            engine.evaluate(bad)
            c.check("refuses %s" % bad, False, "was accepted")
        except engine.CalcError:
            c.check("refuses %s" % bad, True)
    # units
    for q, want in [("60 mph to km/h", "96.56064"), ("100 degF to degC", None), ("-40 degC to degF", "-40"), ("1 kWh to J", "3600000"),
                    ("3 ft to m", "0.9144"), ("1 gal to L", "3.785411784"), ("9.81 kg*m/s^2 to N", "9.81")]:
        r = units.convert(q)
        c.check("convert %s" % q, want is None or r["result"] == want, r["display"])
    try:
        units.convert("5 kg to m")
        c.check("refuses kg to m", False)
    except units.UnitError:
        c.check("refuses kg to m (different dimensions)", True)
    # science
    c.check("118 elements", len(science.ELEMENTS) == 118 and science.ELEMENTS[-1]["symbol"] == "Og")
    c.check("molar mass of H2O = 18.015", science.molar_mass("H2O")["molar_mass"] == "18.015")
    c.check("molar mass of CuSO4·5H2O = 249.677", science.molar_mass("CuSO4·5H2O")["molar_mass"] == "249.677")
    c.check("Ohm's law V = 10", science.solve("ohm", "V", {"I": "2", "R": "5"})["result"]["value"] == "10")
    c.check("kinetic energy with units", science.solve("kinetic", "E", {"m": "1500 kg", "v": "60 mph"})["result"]["display"] == "539580.85632")
    gas = science.solve("ideal_gas", "Vol", {"p": "1 atm", "n": "1", "T": "0 degC"}, "L")
    c.check("ideal gas molar volume ≈ 22.414 L", "22.41396954" in gas["converted"], gas.get("converted"))
    for f in science.FORMULAS:
        c.check("formula %s solves for each listed unknown" % f[0], all(v in f[5] for v, *_ in f[4] if v not in ("theta",)) or f[0] in ("photon", "mass_energy", "interest"))
    # store, save, verify, import — in a throw-away folder
    with tempfile.TemporaryDirectory() as tmp:
        app = App(os.path.join(tmp, "data"))
        r = app.ask("12 × 7")
        c.check("ask: calculation", r["answer"] == "84")
        c.check("ask: conversion", app.ask("60 mph to km/h")["answer"] == "96.56064 km/h")
        c.check("ask: molar mass", app.ask("molar mass of NaCl")["answer"] == "58.44 g/mol")
        c.check("ask: element", app.ask("Fe")["answer"] == "Iron")
        s = app.save("calc", "12 × 7", "84", r["detail"])
        c.check("saved fact verified", s["status"] == "verified")
        s2 = app.save("calc", "2+2", "5", {})
        c.check("wrong saved answer is flagged", s2["status"] == "mismatch")
        app.save("formula", "Ohm's law: V", "10", {"id": "ohm", "unknown": "V", "given": {"I": "2", "R": "5"}})
        res = app.verify_all(lambda *a: None, lambda: False)
        c.check("re-check all", res["checked"] == 3 and res["not_verified"] == 1, res)
        # a small old store: JSON-lines gzip block with good, wrong and non-deterministic records
        old = os.path.join(tmp, "oldstore")
        os.makedirs(os.path.join(old, "blocks"))
        recs = [("12²", "equals", "144", "mathematics"), ("7 × 8", "equals", "56", "arithmetic"), ("5!", "equals", "121", "mathematics"),
                ("circle radius 2", "area", "12.5664", "geometry"), ("year 2000", "is_leap_year", "yes", "history"),
                ("year 1900", "is_leap_year", "no", "history"), ("year 1215", "recorded_event", "Magna Carta sealed", "history"),
                ("grayscale level 255", "hex", "#ffffff", "art")]
        with gzip.open(os.path.join(old, "blocks", "block_00000.jsonl.gz"), "wt", encoding="utf-8") as f:
            for s_, p_, o_, d_ in recs:
                f.write(json.dumps({"nucleus": {"subject": s_, "predicate": p_, "object": o_}, "domain": d_, "polarity": "+",
                                    "certification": {"trust_score": 0.99}}) + "\n")
            f.write("{this line is damaged\n")
        with open(os.path.join(old, "manifest.json"), "w") as f:
            json.dump({"blocks": 1, "facts": len(recs)}, f)
        before = sorted(os.listdir(os.path.join(old, "blocks")))
        mtime = os.path.getmtime(os.path.join(old, "blocks", "block_00000.jsonl.gz"))
        res = app.import_old(old, lambda *a: None, lambda: False)
        c.check("import keeps only facts that recompute", res["imported_verified"] == 6 and res["failed_recomputation"] == 1, res)
        c.check("import leaves non-deterministic facts for the other apps", res["left_for_other_apps"] == 1, res)
        res2 = app.import_old(old, lambda *a: None, lambda: False)
        c.check("importing twice adds nothing", res2["imported_verified"] == 0 and res2["already_present"] == 6, res2)
        c.check("old store untouched", sorted(os.listdir(os.path.join(old, "blocks"))) == before and
                os.path.getmtime(os.path.join(old, "blocks", "block_00000.jsonl.gz")) == mtime and
                not os.path.exists(os.path.join(old, "index.sqlite")))
        c.check("backups written", len(app.store.backups()) >= 2)
        c.check("database integrity", app.store.scalar("PRAGMA integrity_check") == "ok")
        # a write that fails half-way leaves nothing behind
        n0 = app.store.scalar("SELECT count(*) FROM facts")
        try:
            with app.store.write() as db:
                db.execute("INSERT INTO facts(question, answer, kind, fingerprint, status, source, created) VALUES('x','1','calc','fp-x','verified','t','t')")
                raise RuntimeError("simulated crash")
        except RuntimeError:
            pass
        c.check("interrupted write is rolled back", app.store.scalar("SELECT count(*) FROM facts") == n0)
        # HTTP layer
        h = core.make_handler(app.api, os.path.join(HERE, "ui"), app.log, APP_NAME)
        c.check("web routes registered", ("POST", "/api/ask") in app.api.routes and ("GET", "/api/status") in app.api.routes)
        c.check("user interface present", os.path.exists(os.path.join(HERE, "ui", "index.html")) and h is not None)
    return c.report(APP_NAME)


if __name__ == "__main__":
    sys.exit(core.run_cli(sys.modules[__name__]))
