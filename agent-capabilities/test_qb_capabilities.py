#!/usr/bin/env python3
"""Tests for the QueryBook Agent Capability Layer. One test per capability, each
proving the COVENANT GUARD holds (not just that the feature runs). Flake-free,
dependency-free. Run: python test_qb_capabilities.py"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qb_capabilities as cap
import ufcs_store as store

RESULTS = []


def check(name, fn):
    d = tempfile.mkdtemp(prefix="qbcap_")
    try:
        ok, detail = fn(d)
        RESULTS.append((name, bool(ok), str(detail)))
    except Exception as e:
        import traceback
        RESULTS.append((name, False, "exception: %s | %s" % (e, traceback.format_exc().splitlines()[-1])))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _mk(d, name):
    p = os.path.join(d, name)
    os.makedirs(p, exist_ok=True)
    return p


# 1. cloud offload — deterministic local vs remote
def t_offload(d):
    job = lambda x: store.fingerprint(x, "n", "v")
    local = cap.offload(job, "Payload")
    remote = cap.offload(job, "Payload", adapter=lambda f, *a: f(*a))
    return (local == remote and len(local) == 64), "local == remote fingerprint (deterministic offload)"


# 2. browse web — web candidate never answers until independently verified
def t_web_intake(d):
    cand, auth = _mk(d, "cand"), _mk(d, "auth")
    cap.intake_candidate(cand, "web", "example.com", [("France", "has_capital", "Paris")])
    v1, _ = cap.verify_or_refuse(auth, "France", "has_capital", "Paris")   # auth empty
    cap.promote(auth, "France", "has_capital", "Paris", ("SRC-REF", "Reference", "reference", 1.0))
    v2, _ = cap.verify_or_refuse(auth, "France", "has_capital", "Paris")
    return (v1 == "UNKNOWN" and v2 == "VERIFIED"), "web candidate=UNKNOWN until verified, then VERIFIED"


# 3. connected app WRITE is an approval-gated effect that truly does not run early
def t_connector_effect(d):
    gate = cap.ApprovalGate()
    fired = {"v": False}
    eff = cap.Effect("gmail.send", lambda p: fired.__setitem__("v", True) or "sent", {"to": "x@y"})
    r1 = eff.run(gate)                       # no approval yet
    ran_early = fired["v"]
    gate.decide(r1["id"], True)
    r2 = eff.run(gate, r1["id"])             # now approved
    executed = any(e["event"] == "executed" for e in gate.log)
    return (not ran_early and not r1["ran"] and r2["ran"] and executed), \
        "effect blocked pre-approval (fn never ran), executed + logged after approval"


# 4. create files — cite-or-refuse; unverified claim omitted
def t_build_file(d):
    auth = _mk(d, "auth")
    cap.promote(auth, "France", "has_capital", "Paris", ("SRC-REF", "Reference", "reference", 1.0))
    out = os.path.join(d, "brief.md")
    r = cap.build_file(auth, out, [("France", "has_capital", "Paris"),
                                   ("France", "has_capital", "Berlin")])
    body = open(out, encoding="utf-8").read()
    manifest = os.path.exists(out + ".provenance.json")
    return (r["included"] == 1 and r["omitted"] == 1 and "Paris" in body
            and "Berlin" not in body and manifest), \
        "verified claim written (Paris), unverified omitted (Berlin); provenance manifest present"


# 5. run tools — deterministic tool asserts; external tool is an approval-gated effect
def t_tools(d):
    auth = _mk(d, "auth")
    reg = cap.ToolRegistry(auth)
    reg.register("triples", lambda a: [("2", "plus", "2 = 4")], "assert")
    reg.register("poster", lambda a: "posted", "effect")
    asserted = reg.run("triples", None)["asserted"]
    gate = cap.ApprovalGate()
    rid = gate.request("poster", None)
    before = reg.run("poster", None, gate, rid)          # not approved
    gate.decide(rid, True)
    after = reg.run("poster", None, gate, rid)
    return (asserted == 1 and not before["ran"] and after["ran"]), \
        "deterministic tool asserted 1 fact; effect tool ran only after approval"


# 6. project ledger — append-only, replayable, survives reload (over time)
def t_ledger(d):
    path = os.path.join(d, "ledger.jsonl")
    lg = cap.ProjectLedger(path)
    pid = lg.project("Ship the report")
    sid = lg.add_step(pid, "Draft")
    uid = lg.add_unit(sid, "Write section 1", "cited")
    lg.set_status(uid, "done")
    reloaded = cap.ProjectLedger(path)                   # new process view
    return (lg.state()[uid]["status"] == "done"
            and reloaded.state()[uid]["status"] == "done"), \
        "unit status persisted and replays identically from the append-only log"


# 7. device sync — merge by fingerprint, dedup, no divergence
def t_sync(d):
    a, b = _mk(d, "devA"), _mk(d, "devB")
    for (dr, facts) in [(a, [("X", "is", "1")]), (b, [("X", "is", "1"), ("Y", "is", "2")])]:
        st = store.UFCSStore(dr)
        for (s, p, o) in facts:
            st.add(store.make_packet(s, p, o))
        st.close()
    r = cap.sync_devices(a, b)
    return (r["added"] == 1 and r["duplicates"] == 1), \
        "shared fact deduped by fingerprint, unique fact merged (added=1, dup=1)"


# 8. multi-agent — disagreement on a functional relation is surfaced, not overwritten
def t_team(d):
    auth = _mk(d, "auth")
    team = cap.AgentTeam(auth)
    team.contribute("agent-1", "France", "has_capital", "Paris", ("SRC-A", "A", "reference", 1.0))
    team.contribute("agent-2", "France", "has_capital", "Lyon", ("SRC-B", "B", "reference", 1.0))
    verdict, facts = team.consensus("France", "has_capital")
    return (verdict == "CONTRADICTED" and len(facts) == 2), \
        "two agents disagree → gate returns CONTRADICTED (both values kept, no winner)"


# 9. planner — halts on ambiguity; decomposes when the slot is known
def t_planner(d):
    halt = cap.Planner.decompose("write report", known=set(), required={"audience"})
    plan = cap.Planner.decompose("research then draft then review", known={"audience"})
    return ("halt" in halt and "audience" in halt["halt"] and len(plan["steps"]) == 3), \
        "ambiguous goal halts with a question; clear goal decomposes into 3 units"


# 10. approval — an unapproved effect never changes the world
def t_approval(d):
    gate = cap.ApprovalGate()
    world = {"emails": 0}
    eff = cap.Effect("send", lambda p: world.__setitem__("emails", world["emails"] + 1), {})
    eff.run(gate)                    # requested, not approved
    denied = world["emails"]
    rid = gate._reqs and list(gate._reqs)[0]
    gate.decide(rid, False)          # explicitly denied
    eff.run(gate, rid)
    return (denied == 0 and world["emails"] == 0), \
        "effect never executed while unapproved or denied (world unchanged)"


if __name__ == "__main__":
    for name, fn in [
        ("1  cloud offload (deterministic)", t_offload),
        ("2  browse web (candidate → verify)", t_web_intake),
        ("3  connected-app write (approval-gated)", t_connector_effect),
        ("4  create files (cite-or-refuse)", t_build_file),
        ("5  run tools (assert vs effect)", t_tools),
        ("6  project ledger (over time)", t_ledger),
        ("7  device sync (dedup merge)", t_sync),
        ("8  multi-agent (contradiction surfaced)", t_team),
        ("9  planner (halt on ambiguity)", t_planner),
        ("10 human approval (effects gated)", t_approval),
    ]:
        check(name, fn)

    print("=" * 74)
    print("QueryBook Agent Capability Layer — covenant-guard tests")
    print("=" * 74)
    passed = 0
    for name, ok, detail in RESULTS:
        print(("  PASS " if ok else "  FAIL ") + name)
        print("        " + detail)
        passed += ok
    print("-" * 74)
    print("%d/%d capabilities proven covenant-bound" % (passed, len(RESULTS)))
    sys.exit(0 if passed == len(RESULTS) else 1)
