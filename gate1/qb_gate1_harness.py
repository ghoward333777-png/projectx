#!/usr/bin/env python3
"""
qb_gate1_harness.py — QueryBook Gate 1 automated test harness.

Gate 1 of the foolproof phased development plan: a single-command, flake-free
suite that proves the Canonical Engine Spec's covenant invariants (C1-C6) plus
core behaviour — fingerprint/round-trip/dedup, the Prime-Directive gate, each of
the four language phases, and the agent family — against the FROZEN baseline
`QueryBook-baseline-v9.15`. It never modifies the baseline; it imports it.

Run:
    python qb_gate1_harness.py            # 3 consecutive runs (default), prove flake-free
    python qb_gate1_harness.py -n 5       # N consecutive runs
    python qb_gate1_harness.py --once     # a single run

Exit code 0 iff every check passes on every run AND the deterministic signature
is byte-identical across all runs. Any failure or drift exits non-zero.

This harness covers the engine (Python). The optional UI-render check (zero JS
console errors) lives in qb_gate1_ui.py and is invoked with --ui.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

# --- locate and import the frozen baseline WITHOUT modifying it ---------------
HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE = os.path.normpath(os.path.join(HERE, "..", "prototype", "QueryBook-baseline-v9.15"))
if not os.path.isdir(BASELINE):
    print("FATAL: frozen baseline not found at %s" % BASELINE)
    sys.exit(2)
sys.path.insert(0, BASELINE)
# data files (qb_dict.json.gz, qb_bilingual.json.gz) resolve relative to the
# baseline module dir via each module's _path() helper, so no chdir is required.

import ufcs_store as store          # noqa: E402
import qb_chat as chat              # noqa: E402
import qb_language as lang          # noqa: E402
import qb_agents as agents          # noqa: E402


# --- tiny check framework -----------------------------------------------------
class Ctx:
    """Per-run scratch: a throwaway store dir, auto-cleaned."""
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="qb_gate1_")
        self.sig = {}     # deterministic signature accumulator

    def store_dir(self, name):
        d = os.path.join(self.dir, name)
        os.makedirs(d, exist_ok=True)
        return d

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def _fact(subject, predicate, obj, trust=0.99):
    """A retrieval-shaped fact dict as qb_chat.gate/compose expect."""
    return {"subject": subject, "predicate": predicate, "object": obj,
            "trust": trust, "fingerprint": store.fingerprint(subject, predicate, obj)}


# Each check is a function(ctx) -> (ok: bool, detail: str). It may write into
# ctx.sig[...] the deterministic values that must match across runs.
CHECKS = []


def check(name, invariant=""):
    def deco(fn):
        CHECKS.append((name, invariant, fn))
        return fn
    return deco


# ---------------------------------------------------------------- C3 determinism
@check("Fingerprint: pure, normalized, collision-free", "C3")
def c_fingerprint(ctx):
    a = store.fingerprint("France", "has_capital", "Paris")
    b = store.fingerprint("  france ", "HAS_CAPITAL", "Paris")   # normalize → same
    c = store.fingerprint("France", "has_capital", "Lyon")       # differ → differ
    ctx.sig["fp_france"] = a
    ok = (a == b) and (a != c) and len(a) == 64 and all(ch in "0123456789abcdef" for ch in a)
    return ok, "64-hex; case/space match=%s; distinct-object differs=%s" % (a == b, a != c)


@check("Determinism: identical packets → identical fingerprints", "C3")
def c_determinism_packets(ctx):
    p1 = store.make_packet("Water", "boils_at", "100C", domain="qc")
    p2 = store.make_packet("water", "boils_at", "100C", domain="qc")   # different metadata, same nucleus
    same = p1["semantic_fingerprint"] == p2["semantic_fingerprint"]
    ctx.sig["fp_water"] = p1["semantic_fingerprint"]
    return same, "normalized nucleus yields one identity regardless of ingest metadata"


# ---------------------------------------------------------------- C2 provenance
@check("Provenance: every asserted fact carries source + certification", "C2")
def c_provenance(ctx):
    d = ctx.store_dir("prov")
    st = store.UFCSStore(d)
    p = store.make_packet("Proof", "needs", "source", domain="qc")
    st.add(p); fp = p["semantic_fingerprint"]; st.close()
    st2 = store.UFCSStore(d); rec = st2.get(fp); st2.db.close()
    srcs = (rec or {}).get("sources") or []
    cert = (rec or {}).get("certification") or {}
    ok = bool(rec) and len(srcs) >= 1 and bool(srcs[0].get("id")) \
        and cert.get("authority_class") and "trust_score" in cert
    return ok, "stored fact retains sources[%d] + certification(%s)" % (len(srcs), cert.get("authority_class"))


# ---------------------------------------------------------------- round-trip
@check("Store write → read round-trip is byte-identical", "C3")
def c_roundtrip(ctx):
    d = ctx.store_dir("rt")
    st = store.UFCSStore(d)
    p = store.make_packet("QC Subject", "qc_predicate", "42", domain="qc")
    added = st.add(p); fp = p["semantic_fingerprint"]; st.close()
    st2 = store.UFCSStore(d); rec = st2.get(fp); st2.db.close()
    ok = bool(added and rec and rec["nucleus"]["object"] == "42"
              and rec["semantic_fingerprint"] == fp)
    return ok, "packet stored and read back identical"


# ---------------------------------------------------------------- C5 dedup
@check("Dedup: identical meaning stored once", "C5")
def c_dedup(ctx):
    d = ctx.store_dir("dd")
    st = store.UFCSStore(d)
    p = store.make_packet("Dup", "equals", "1")
    a1 = st.add(p); a2 = st.add(p)
    facts = st.manifest.get("facts", 0); st.close()
    return (a1 and not a2 and facts == 1), "second identical fact skipped; store holds 1"


# ---------------------------------------------------------------- C4 gate: verdicts
@check("Gate: VERIFIED on clean single-valued facts", "C4")
def c_gate_verified(ctx):
    verdict, usable = chat.gate([_fact("France", "has_capital", "Paris")], 0.5)
    return (verdict == "VERIFIED" and len(usable) == 1), "verdict=%s" % verdict


@check("Gate: UNKNOWN → refuse (no invention)", "C4")
def c_gate_unknown(ctx):
    v_empty, _ = chat.gate([], 0.5)
    v_lowtrust, _ = chat.gate([_fact("X", "y", "z", trust=0.2)], 0.5)   # below threshold
    draft = chat.compose("anything", "UNKNOWN", [], use_llm=False)
    refuses = "Without-Information Rule" in draft and "declin" in draft.lower()
    ok = v_empty == "UNKNOWN" and v_lowtrust == "UNKNOWN" and refuses
    return ok, "empty=%s low-trust=%s; composer emits the Without-Information Rule" % (v_empty, v_lowtrust)


@check("Gate: CONTRADICTED on a functional predicate with two values", "C4")
def c_gate_contradicted(ctx):
    facts = [_fact("France", "has_capital", "Paris"), _fact("France", "has_capital", "Lyon")]
    verdict, _ = chat.gate(facts, 0.5)
    return verdict == "CONTRADICTED", "two has_capital values → verdict=%s" % verdict


@check("Gate: multi-valued predicate is NOT a contradiction", "C4")
def c_gate_multivalued(ctx):
    facts = [_fact("sparrow", "is_a", "bird"), _fact("sparrow", "is_a", "animal")]
    verdict, _ = chat.gate(facts, 0.5)
    return verdict == "VERIFIED", "two is_a facets coexist → verdict=%s" % verdict


# ---------------------------------------------------------------- C6 non-assertion
@check("Non-assertion: low-trust hypothesis never reaches an answer", "C6")
def c_hypothesis_isolation(ctx):
    # hypothesis/simulation facts live in isolated domains at trust < 0.5, so the
    # gate at the default 0.5 threshold excludes them: an LLM proposal cannot be asserted.
    hyp = _fact("Mars", "may_have", "life", trust=0.4)           # a proposal
    hyp["object"] = "life"
    verdict, usable = chat.gate([hyp], 0.5)
    return (verdict == "UNKNOWN" and not usable), \
        "a trust-0.4 hypothesis is gated out (verdict=%s), never asserted" % verdict


# ---------------------------------------------------------------- C1 LLM lockout
@check("LLM lockout: Phase-2 grounder drops any suggestor (never calls an LLM)", "C1")
def c_llm_lockout(ctx):
    assert lang.LLM_LOCKOUT is True, "LLM_LOCKOUT must be True in the baseline"
    d = ctx.store_dir("lock")
    called = {"n": 0}

    def suggestor(word):          # a stand-in LLM that WOULD inject meaning
        called["n"] += 1
        return "an injected meaning that must never be used"

    lang.ground_words(d, ["book"], suggestor=suggestor)
    # prove the injected suggestion produced no 'means_confirmed' fact either
    st = store.UFCSStore(d)
    injected = 0
    try:
        if not st.no_fql:
            injected = st.db.execute(
                "SELECT COUNT(*) FROM nuc WHERE predicate='means_confirmed'").fetchone()[0]
    finally:
        st.close()
    ok = (called["n"] == 0) and (injected == 0)
    return ok, "suggestor invoked %d times; means_confirmed facts=%d (lockout enforced)" % (called["n"], injected)


# ---------------------------------------------------------------- Phase 1
@check("Phase 1 (SLPL): structural learning writes metric facts", "phase")
def c_phase1(ctx):
    d = ctx.store_dir("p1")
    text = lang.corpus_chunk(0) + " " + lang.corpus_chunk(1)
    mx = lang.learn(d, text=text)
    words = lang.learned_words(d, 400)
    ctx.sig["p1_vocab"] = len(words)
    ok = ("error" not in mx) and mx.get("facts_written", 0) > 0 and len(words) > 0 \
        and "gate" in mx and "checks" in mx["gate"]
    return ok, "vocab=%d, facts_written=%d, gate keys present" % (len(words), mx.get("facts_written", 0))


# ---------------------------------------------------------------- Phase 2
@check("Phase 2 (semantic): deterministic dictionary grounding", "phase")
def c_phase2(ctx):
    assert lang.dictionary_size() > 0, "Webster's 1913 dictionary must be bundled"
    d1 = ctx.store_dir("p2a"); d2 = ctx.store_dir("p2b")
    words = ["book", "water", "fox"]
    r1 = lang.ground_words(d1, words)
    r2 = lang.ground_words(d2, words)
    ctx.sig["p2_facts"] = r1["facts_added"]
    ctx.sig["p2_defs"] = tuple(sorted(g["word"] + "::" + (g.get("definition") or "")[:40]
                                      for g in r1["grounded"]))
    deterministic = (r1["facts_added"] == r2["facts_added"]) and \
        ([g["word"] for g in r1["grounded"]] == [g["word"] for g in r2["grounded"]])
    webster = any(g.get("source", "").startswith("Webster") for g in r1["grounded"])
    ok = r1["facts_added"] > 0 and deterministic and webster
    return ok, "dict=%d, facts_added=%d, deterministic=%s, Webster-sourced=%s" % (
        lang.dictionary_size(), r1["facts_added"], deterministic, webster)


# ---------------------------------------------------------------- Phase 3
@check("Phase 3 (multilingual): deterministic delta translation", "phase")
def c_phase3(ctx):
    avail = lang.available_languages()
    assert "es" in avail and "fr" in avail, "es+fr bilingual data must be bundled"
    # draw real keys from the bundled es set so mapping is guaranteed
    es = lang.load_bilingual().get("es") or {}
    words = [w for w in list(es.keys()) if isinstance(w, str) and w.isalpha()][:6]
    d1 = ctx.store_dir("p3a"); d2 = ctx.store_dir("p3b")
    r1 = lang.acquire_language(d1, "es", words=words)
    r2 = lang.acquire_language(d2, "es", words=words)
    ctx.sig["p3_facts"] = r1.get("facts_added")
    ok = ("error" not in r1) and r1.get("facts_added", 0) > 0 \
        and r1.get("facts_added") == r2.get("facts_added")
    return ok, "available=%s, es facts_added=%s (deterministic=%s)" % (
        avail, r1.get("facts_added"), r1.get("facts_added") == r2.get("facts_added"))


# ---------------------------------------------------------------- Phase 4a
@check("Phase 4a (speech): deterministic pronunciation analysis", "phase")
def c_phase4_analysis(ctx):
    a1 = lang.analyze_pronunciation("book")
    a2 = lang.analyze_pronunciation("book")
    ctx.sig["p4_book_ipa"] = a1["ipa"]
    ctx.sig["p4_book_syl"] = a1["syllables"]
    d = ctx.store_dir("p4")
    r = lang.speech_analyze(d, words=["book", "water", "language"])
    ok = a1 == a2 and a1["ipa"].startswith("/") and a1["syllables"] >= 1 \
        and 1 <= a1["stress_syllable"] <= a1["syllables"] and r["analyzed"] > 0
    return ok, "book=%s syl=%d stress=%d; analyzed=%d Fact Units" % (
        a1["ipa"], a1["syllables"], a1["stress_syllable"], r["analyzed"])


# ---------------------------------------------------------------- Phase 4b
@check("Phase 4b (speech): OS-TTS status honest, speak() never fabricates", "phase")
def c_phase4_tts(ctx):
    ts = lang.tts_status()
    res = lang.speak("hello world")               # must not raise on any platform
    shape_ok = isinstance(ts, dict) and "available" in ts and isinstance(res, dict) \
        and "available" in res and "wav_bytes" in res
    # if no engine present, audio must be None with a hint (never fabricated)
    honest = True
    if not ts.get("available"):
        honest = (res.get("wav_bytes") is None) and bool(res.get("error"))
    return (shape_ok and honest), "tts available=%s engine=%s; speak honest=%s" % (
        ts.get("available"), ts.get("engine"), honest)


# ---------------------------------------------------------------- agent family
@check("Agent family: 12 roles all 'built', roadmap engine empty", "C6")
def c_agent_family(ctx):
    roles = agents.ROLES
    expected = {"deterministic", "web", "grounded_qa", "watch", "reasoning", "hypothesis",
                "simulation", "planner", "language", "lang_semantic",
                "lang_multilingual", "lang_speech"}
    have = set(roles.keys())
    all_built = all(r.get("status") == "built" for r in roles.values())
    roadmap_empty = (agents._ROADMAP_ENGINE == {})
    ctx.sig["roles"] = tuple(sorted(have))
    ok = expected.issubset(have) and all_built and roadmap_empty
    return ok, "%d roles, all built=%s, roadmap engines=%d" % (
        len(roles), all_built, len(agents._ROADMAP_ENGINE))


# --- run mechanics ------------------------------------------------------------
def run_once():
    ctx = Ctx()
    results = []
    try:
        for name, inv, fn in CHECKS:
            try:
                ok, detail = fn(ctx)
                results.append({"name": name, "inv": inv, "ok": bool(ok), "detail": str(detail)})
            except Exception as e:
                import traceback
                results.append({"name": name, "inv": inv, "ok": False,
                                "detail": "exception: %s | %s" % (e, traceback.format_exc().splitlines()[-1])})
        sig = json.dumps(ctx.sig, sort_keys=True, default=str)
        sig_hash = hashlib.sha256(sig.encode()).hexdigest()[:16]
    finally:
        ctx.cleanup()
    passed = sum(1 for r in results if r["ok"])
    return {"results": results, "passed": passed, "total": len(results),
            "all_ok": passed == len(results), "sig": sig_hash}


def main():
    ap = argparse.ArgumentParser(description="QueryBook Gate 1 test harness")
    ap.add_argument("-n", "--runs", type=int, default=3, help="consecutive runs (flake-free proof)")
    ap.add_argument("--once", action="store_true", help="a single run")
    args = ap.parse_args()
    n = 1 if args.once else max(1, args.runs)

    print("=" * 74)
    print("QueryBook Gate 1 harness — baseline: QueryBook-baseline-v9.15")
    print("checks: %d   runs: %d   started: %s" % (len(CHECKS), n, time.strftime("%Y-%m-%d %H:%M:%S")))
    print("=" * 74)

    sigs, all_runs_ok = set(), True
    last = None
    for i in range(n):
        r = run_once()
        last = r
        sigs.add(r["sig"])
        if i == 0:
            for res in r["results"]:
                mark = "PASS" if res["ok"] else "FAIL"
                tag = ("[%s] " % res["inv"]) if res["inv"] else ""
                print("  %s %s%s" % (mark, tag, res["name"]))
                print("        %s" % res["detail"])
        print("-" * 74)
        print("  run %d/%d: %d/%d passed   signature=%s   %s"
              % (i + 1, n, r["passed"], r["total"], r["sig"],
                 "ALL OK" if r["all_ok"] else "*** FAILURES ***"))
        if not r["all_ok"]:
            all_runs_ok = False

    deterministic = (len(sigs) == 1)
    print("=" * 74)
    print("SUMMARY: %d run(s); every-run-green=%s; deterministic-across-runs=%s (signatures=%s)"
          % (n, all_runs_ok, deterministic, ",".join(sorted(sigs))))
    ok = all_runs_ok and deterministic
    print("GATE 1 RESULT: %s" % ("GREEN ✓" if ok else "RED ✗"))
    print("=" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
