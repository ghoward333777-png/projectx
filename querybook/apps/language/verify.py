"""Proof that the Language Builder learns from scratch — something a third party can run and check.

`python app.py verify` (or Build → Verify from scratch) does this, on any computer:

1. Sealed start. A brand-new, empty database is created in a temporary folder. Its fact count is
   recorded (it must be 0). All network connections are blocked for the whole run, so nothing can be
   looked up online and no AI service can be asked.
2. Order is enforced. Before the sub-language phase, asking for meanings must be refused
   (the one-way Transition Gate is closed).
3. Learning from zero. Phase 1 is run reading by reading; the learning curve (words, sounds,
   word pairs, gate measures after every reading) is recorded from the first reading on.
4. Full build. All 20 steps run exactly as in a normal build.
5. Inputs declared. Every file the builder reads is listed with its SHA-256 hash, and the code is
   checked: it may import only the Python standard library and its own modules (no AI, no network).
6. Fingerprint. Everything learned is reduced to one SHA-256 fingerprint (timestamps excluded). The
   same code and the same inputs always give the same fingerprint, so anyone can rebuild and compare —
   and it must equal the fingerprint of this computer's own build.

Pronunciations made by espeak-ng (optional, version-dependent) are counted but kept out of the
fingerprint, so the fingerprint is the same with or without espeak-ng installed.
"""
import ast, hashlib, json, os, platform, shutil, socket, sys, tempfile, time

import qbcore as core
import lab
import lab_core as C
import speech
import vocab

HERE = os.path.dirname(os.path.abspath(__file__))
CODE_FILES = ["lab_core.py", "lab.py", "vocab.py", "speech.py", "verify.py"]
OWN_MODULES = {"lab_core", "lab", "vocab", "speech", "verify", "qbcore"}
# The standard library modules the builder's code may use (anything else fails the check).
ALLOWED = {"ast", "gzip", "hashlib", "json", "os", "platform", "re", "shutil", "socket", "subprocess", "sys", "tempfile", "time",
           "unicodedata"}
REPORT_VERSION = 1


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inputs_manifest():
    files = []
    for name in CODE_FILES:
        p = os.path.join(HERE, name)
        files.append({"file": name, "kind": "builder code", "bytes": os.path.getsize(p), "sha256": sha256_file(p)})
    data = os.path.join(HERE, "data")
    for name in sorted(os.listdir(data)):
        p = os.path.join(data, name)
        kind = {"english_dictionary.json.gz": "Webster's Unabridged Dictionary 1913 (public domain) + English word order",
                "bilingual.json.gz": "MUSE bilingual word lists (CC BY-NC 4.0)"}.get(name, "data")
        files.append({"file": "data/" + name, "kind": kind, "bytes": os.path.getsize(p), "sha256": sha256_file(p)})
    starter = "\n\n".join(C.STARTER_CORPUS)
    files.append({"file": "lab_core.STARTER_CORPUS", "kind": "starter English text for Phase 1 (%d passages)" % len(C.STARTER_CORPUS),
                  "bytes": len(starter.encode("utf-8")), "sha256": hashlib.sha256(starter.encode("utf-8")).hexdigest()})
    return files


def import_audit():
    """Every module the builder's code imports, and whether it is allowed (standard library or its own)."""
    found = {}
    for name in CODE_FILES:
        tree = ast.parse(open(os.path.join(HERE, name), encoding="utf-8").read())
        for node in ast.walk(tree):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            for m in mods:
                found.setdefault(m.split(".")[0], set()).add(name)
    rows = [{"module": m, "used_in": sorted(v), "allowed": m in ALLOWED or m in OWN_MODULES,
             "kind": "own module" if m in OWN_MODULES else "standard library" if m in ALLOWED else "NOT ALLOWED"} for m, v in sorted(found.items())]
    return {"modules": rows, "ok": all(r["allowed"] for r in rows)}


def fingerprint(store):
    """SHA-256 over everything learned (sorted, timestamps excluded, espeak-ng facts excluded)."""
    h = hashlib.sha256()
    n = skipped = 0
    for r in store.query("SELECT subject, predicate, object, source, trust FROM lab_facts ORDER BY subject, predicate, object, source"):
        if str(r["source"]).startswith("espeak"):
            skipped += 1
            continue
        h.update(("%s\t%s\t%s\t%s\t%s\n" % (r["subject"], r["predicate"], r["object"], r["source"], r["trust"])).encode("utf-8"))
        n += 1
    m = lab.Lab(store, lambda *a: None).load_model()
    core_model = {k: m.get(k) for k in ("total_tokens", "words", "phonemes", "graphemes", "bigrams", "sent_count", "sent_len_sum", "sent_len_sq",
                                        "questions", "exclamations", "ingests", "gate_opened")}
    h.update(json.dumps(core_model, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return {"sha256": h.hexdigest(), "facts_in_fingerprint": n, "espeak_facts_excluded": skipped}


class _NoNetwork:
    """Blocks every network connection while active (proves nothing is fetched or asked online)."""
    def __enter__(self):
        self.attempts = []
        self._orig = (socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo)
        me = self

        def refuse(*a, **k):
            me.attempts.append(repr(a[1:2] if len(a) > 1 else a)[:80])
            raise OSError("network blocked during verification")
        socket.socket.connect = refuse
        socket.socket.connect_ex = refuse
        socket.create_connection = refuse
        socket.getaddrinfo = refuse
        return self

    def __exit__(self, *exc):
        socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo = self._orig
        return False


def run(progress, stop, own_store=None, schema=None, app_id="language"):
    """Rebuild from nothing in a sealed temporary store and return the verification report."""
    t0 = time.time()
    tmp = tempfile.mkdtemp(prefix="qb-verify-")
    rep = {"report": "QueryBook Language Builder — verification from scratch", "report_version": REPORT_VERSION,
           "started": lab.now(), "computer": {"python": platform.python_version(), "os": platform.system() + " " + platform.release(),
                                              "espeak_ng": bool(speech.find_espeak())}, "checks": []}

    def check(name, ok, detail=""):
        rep["checks"].append({"check": name, "pass": bool(ok), "detail": detail})

    try:
        progress(0, 100, "declaring inputs", overall=0.01, stage="Declaring inputs and checking the code")
        rep["inputs"] = inputs_manifest()
        rep["imports"] = import_audit()
        check("The builder's code uses only the Python standard library and its own modules (no AI, no network libraries)",
              rep["imports"]["ok"], ", ".join(r["module"] for r in rep["imports"]["modules"] if not r["allowed"]) or "all imports allowed")
        with _NoNetwork() as net:
            store = core.Store(tmp, app_id, schema, lambda *a: None)
            L = lab.Lab(store, lambda *a: None)
            start = store.scalar("SELECT count(*) FROM lab_facts", default=0)
            m0 = L.load_model()
            check("Starts from nothing: an empty database (0 learned facts, 0 words read)", start == 0 and m0["total_tokens"] == 0,
                  "%d facts, %d words read at the start" % (start, m0["total_tokens"]))
            try:
                L.ground_words(["house"])
                refused = False
            except lab.GateClosed:
                refused = True
            check("Meanings are refused before the sub-language is learned (Transition Gate closed)", refused)
            # Phase 1, reading by reading, with the learning curve recorded
            curve = []
            cycles = 0
            while not L.gate_open() and not stop() and cycles < lab.MAX_PHASE1_CYCLES:
                idx = int(store.scalar("SELECT value FROM lab_state WHERE key = 'chunk'", default=0))
                mx = L.learn(C.corpus_chunk(idx), "Phase 1 · starter corpus #%d" % (idx % len(C.STARTER_CORPUS)))
                with store.write() as db:
                    db.execute("INSERT OR REPLACE INTO lab_state(key, value) VALUES('chunk', ?)", (str(idx + 1),))
                cycles += 1
                g = mx["gate"]["checks"]
                curve.append({"reading": cycles, "words_read": mx["total_tokens"], "different_words": mx["distinct_words"],
                              "sounds": mx["distinct_phonemes"], "word_pairs": mx["distinct_bigrams"],
                              "sounds_found": g["phonemic_completeness"]["value"], "words_settled": g["lexical_stability"]["value"],
                              "pairs_per_word": g["cooccurrence_density"]["value"], "new_patterns": g["pattern_saturation"]["value"],
                              "gate": "open" if mx["gate"]["opened"] else "closed"})
                progress(int(mx["gate"]["progress"]), 100, "reading %d" % cycles, overall=round(0.05 + 0.1 * mx["gate"]["progress"] / 100, 4),
                         stage="Phase 1 from zero — reading %d" % cycles)
            rep["learning_curve"] = curve
            check("Phase 1 learned the sub-language from zero and opened the gate", L.gate_open(),
                  "gate opened after %d readings" % cycles)
            if stop():
                rep["stopped"] = True
                return rep

            def prog(done, total=None, msg="", **x):
                progress(done, total, msg, overall=round(0.15 + 0.8 * x.get("overall", 0), 4),
                         stage="Full build in the sealed store — step %s of %s: %s" % (x.get("stage_no"), x.get("stages"), x.get("stage")))
            ref = lab.Lab(own_store, lambda *a: None).stage_log() if own_store is not None else []
            build = L.run_pipeline(prog, stop, weights={r["key"]: r.get("seconds") for r in ref if r.get("seconds")} or None)
            rep["build"] = {k: v for k, v in build.items()}
            rep["steps"] = L.stage_log()
            check("All 20 steps completed in the sealed store", bool(L.built_at()), build.get("result", ""))
            rep["network_attempts_blocked"] = len(net.attempts)
            check("No network connection was attempted during the whole run", not net.attempts,
                  "%d attempt(s) blocked" % len(net.attempts))
            rep["learned"] = {"facts": store.scalar("SELECT count(*) FROM lab_facts", default=0),
                              "by_kind": store.query("SELECT predicate AS kind, count(*) AS n FROM lab_facts GROUP BY predicate ORDER BY n DESC LIMIT 25"),
                              "by_source": store.query("SELECT source, count(*) AS n FROM lab_facts GROUP BY source ORDER BY n DESC")}
            progress(98, 100, "fingerprint", overall=0.97, stage="Computing the fingerprint")
            rep["fingerprint"] = fingerprint(store)
        if own_store is not None:
            own = fingerprint(own_store)
            rep["this_computer_build"] = own
            check("The sealed rebuild gives exactly the same result as this computer's own build (same fingerprint)",
                  own["sha256"] == rep["fingerprint"]["sha256"],
                  "sealed %s… vs own %s…" % (rep["fingerprint"]["sha256"][:16], own["sha256"][:16]))
    finally:
        try:
            db = getattr(store._local, "db", None)        # close this thread's connection so the folder can be removed
            if db is not None:
                db.close()
        except NameError:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
    rep["seconds"] = round(time.time() - t0, 1)
    rep["finished"] = lab.now()
    rep["verdict"] = "PASS" if all(c["pass"] for c in rep["checks"]) else "FAIL"
    return rep


def text(rep):
    """Plain-text version of the report (command line, and the downloadable .txt)."""
    out = [rep["report"], "=" * len(rep["report"]), "Verdict: %s   (%s s, %s, Python %s, %s)" % (
        rep.get("verdict", "?"), rep.get("seconds"), rep.get("finished", ""), rep["computer"]["python"], rep["computer"]["os"]), ""]
    for c in rep["checks"]:
        out.append("  [%s] %s%s" % ("PASS" if c["pass"] else "FAIL", c["check"], (" — " + c["detail"]) if c["detail"] else ""))
    fp = rep.get("fingerprint")
    if fp:
        out += ["", "Fingerprint of everything learned (SHA-256): " + fp["sha256"],
                "  (%d facts; %d espeak-ng pronunciations not included)" % (fp["facts_in_fingerprint"], fp["espeak_facts_excluded"])]
    out += ["", "Inputs (all the builder reads):"]
    for f in rep.get("inputs", []):
        out.append("  %s  %-30s %10d bytes  %s" % (f["sha256"], f["file"], f["bytes"], f["kind"]))
    out += ["", "Code imports:"]
    for m in rep.get("imports", {}).get("modules", []):
        out.append("  %-14s %-18s %s" % (m["module"], m["kind"], ", ".join(m["used_in"])))
    if rep.get("learning_curve"):
        out += ["", "Phase 1 learning curve from zero (reading: words read / different words / sounds / word pairs / gate):"]
        for r in rep["learning_curve"]:
            out.append("  %3d: %6d / %5d / %2d / %5d / sounds %.2f settled %.2f pairs %.2f new %.2f %s" % (
                r["reading"], r["words_read"], r["different_words"], r["sounds"], r["word_pairs"], r["sounds_found"], r["words_settled"],
                r["pairs_per_word"], r["new_patterns"], r["gate"]))
    out += ["", "How to check this yourself: on any computer with Python 3.8+, unpack the same program and run",
            "  python app.py verify", "The fingerprint must be identical. Any change to the code or the inputs changes it."]
    return "\n".join(out)
