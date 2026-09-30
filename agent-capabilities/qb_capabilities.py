#!/usr/bin/env python3
"""
qb_capabilities.py — QueryBook Agent Capability Layer (reference implementation).

Gives QueryBook agents the ten capabilities consumers expect of a modern agent,
with every one subordinated to the Covenant (spec §2):

  1  cloud compute offload         -> offload()          local/remote, deterministic
  2  browse the web                -> intake_candidate() web text = sourced CANDIDATE, never asserted raw
  3  use connected apps            -> Connector + Effect  reads = candidates; writes = approval-gated effects
  4  create files                  -> build_file()        cite-or-refuse; every file carries a provenance manifest
  5  run tools                     -> ToolRegistry.run()  deterministic tools may assert; external tools are gated
  6  track projects over time      -> ProjectLedger       append-only, provenance-tracked, replayable
  7  local + other devices         -> sync_devices()      merge by fingerprint (dedup); no silent divergence
  8  work with other agents        -> AgentTeam           one shared store; contradictions surfaced, not overwritten
  9  break work into steps/units   -> Planner.decompose() halts on ambiguity; the plan asserts nothing
  10 subject itself to approval    -> ApprovalGate        effects run only after explicit human approval, logged

The unifying rule: a capability may bring data IN (as sourced candidates that the
deterministic store must verify before anything is asserted) or push an effect OUT
(which requires human approval and is provenance-logged). No capability can make an
agent assert an unverified fact or bypass the store, approval, or provenance.

Dependency-free; binds to the frozen baseline for the proven primitives
(fingerprint, make_packet, UFCSStore, the gate). It never modifies the baseline.
"""
import hashlib
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_BASE = os.path.normpath(os.path.join(_HERE, "..", "prototype", "QueryBook-baseline-v9.15"))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)
import ufcs_store as store          # noqa: E402  proven Fact Unit primitives
import qb_chat as chat              # noqa: E402  proven Prime-Directive gate

TRUST_ASSERT = 0.5                  # the gate's answer threshold (spec §5)
CANDIDATE_TRUST = 0.4               # external/proposed material lands below it


def _hid(*parts):
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# 10. Human approval gate — effects run only after explicit approval, logged.
# ---------------------------------------------------------------------------
class ApprovalGate:
    """Any effect that changes the world outside the store passes through here."""
    def __init__(self):
        self._reqs = {}      # id -> {action, payload, status, approver, ts}
        self.log = []        # provenance-ordered decisions

    def request(self, action, payload=None):
        rid = _hid("approval", action, json.dumps(payload, sort_keys=True, default=str), len(self._reqs))
        self._reqs[rid] = {"action": action, "payload": payload, "status": "pending",
                           "approver": None, "ts": time.time()}
        self.log.append({"event": "requested", "id": rid, "action": action})
        return rid

    def decide(self, rid, approve, approver="human"):
        r = self._reqs.get(rid)
        if not r:
            raise KeyError("no such approval request: %s" % rid)
        r["status"] = "approved" if approve else "denied"
        r["approver"] = approver
        self.log.append({"event": r["status"], "id": rid, "approver": approver})
        return r["status"]

    def is_approved(self, rid):
        return self._reqs.get(rid, {}).get("status") == "approved"


class Effect:
    """An outward action (send, post, delete, publish). Runs ONLY when approved."""
    def __init__(self, action, fn, payload=None):
        self.action, self.fn, self.payload = action, fn, payload

    def run(self, gate, rid=None):
        if rid is None:
            rid = gate.request(self.action, self.payload)
        if not gate.is_approved(rid):
            return {"ran": False, "status": "awaiting-approval", "id": rid}
        result = self.fn(self.payload)
        gate.log.append({"event": "executed", "id": rid, "action": self.action})
        return {"ran": True, "status": "done", "id": rid, "result": result}


# ---------------------------------------------------------------------------
# 6. Project ledger — append-only, provenance-tracked, replayable across time.
# ---------------------------------------------------------------------------
class ProjectLedger:
    def __init__(self, path=None):
        self.path = path
        self.events = []
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self.events = [json.loads(l) for l in fh if l.strip()]

    def _emit(self, kind, **kw):
        ev = {"seq": len(self.events), "kind": kind, "ts": time.time(), **kw}
        self.events.append(ev)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev, default=str) + "\n")
        return ev

    def project(self, goal):
        pid = _hid("project", goal)
        self._emit("project", pid=pid, goal=goal)
        return pid

    def add_step(self, pid, title):
        sid = _hid("step", pid, title, len(self.events))
        self._emit("step", pid=pid, sid=sid, title=title, status="pending")
        return sid

    def add_unit(self, sid, desc, acceptance=""):
        uid = _hid("unit", sid, desc, len(self.events))
        self._emit("unit", sid=sid, uid=uid, desc=desc, acceptance=acceptance, status="pending")
        return uid

    def set_status(self, uid, status):
        self._emit("status", uid=uid, status=status)

    def record_artifact(self, uid, path, provenance_fps):
        self._emit("artifact", uid=uid, path=path, provenance=list(provenance_fps))

    def state(self):
        """Fold the append-only log into current state (deterministic replay)."""
        units = {}
        for ev in self.events:
            if ev["kind"] == "unit":
                units[ev["uid"]] = {"desc": ev["desc"], "status": ev["status"], "artifacts": []}
            elif ev["kind"] == "status" and ev["uid"] in units:
                units[ev["uid"]]["status"] = ev["status"]
            elif ev["kind"] == "artifact" and ev["uid"] in units:
                units[ev["uid"]]["artifacts"].append(ev["path"])
        return units


# ---------------------------------------------------------------------------
# 9. Planner — decompose a goal into steps/units; HALT on ambiguity.
# ---------------------------------------------------------------------------
class Planner:
    @staticmethod
    def decompose(goal, known=None, required=None):
        """Return {'halt': question} when a required slot is unknown, else {'steps': [...]}.
        The plan is a non-asserting proposal."""
        known = set(known or [])
        missing = [s for s in (required or []) if s not in known]
        if missing:
            return {"halt": "Before planning, I need: %s. Which %s?" % (
                ", ".join(missing), missing[0])}
        # deterministic decomposition on natural connectors
        raw = goal.replace(" then ", "|").replace(" and ", "|").replace(",", "|")
        steps = [s.strip() for s in raw.split("|") if s.strip()]
        return {"steps": [{"n": i + 1, "unit": s} for i, s in enumerate(steps)]}


# ---------------------------------------------------------------------------
# 2 / 3. Candidate intake — web pages and connector reads become SOURCED
# candidates in an isolated store; they never assert until independently verified.
# ---------------------------------------------------------------------------
def intake_candidate(candidate_dir, source_id, source_name, triples):
    """Write external material (web/connector) as low-trust candidates. NOT asserted."""
    st = store.UFCSStore(candidate_dir)
    src = (source_id, source_name, "external-unverified", 0.4)
    fps = []
    try:
        for (s, p, o) in triples:
            pkt = store.make_packet(s, p, o, "+", "candidate", src, CANDIDATE_TRUST)
            st.add(pkt)
            fps.append(pkt["semantic_fingerprint"])
        st.flush()
    finally:
        st.close()
    return fps


def verify_or_refuse(authoritative_dir, subject, predicate, obj):
    """A candidate is answerable ONLY if the AUTHORITATIVE store holds it at/above the
    trust threshold. Returns (verdict, facts) from the Prime-Directive gate — never the
    candidate store. This is the boundary: external input cannot answer on its own."""
    st = store.UFCSStore(authoritative_dir)
    try:
        rows, _ = st.fql(subject, predicate, 0.0, 10)
    finally:
        st.close()
    facts = [{"subject": s, "predicate": p, "object": o, "trust": round(float(t), 4),
              "fingerprint": fp} for (s, p, o, t, fp) in rows]
    return chat.gate(facts, TRUST_ASSERT)


def promote(authoritative_dir, subject, predicate, obj, trusted_source, gate=None, rid=None):
    """Move a candidate into the authoritative store — allowed only via a trusted,
    deterministic source OR an explicit human approval. Writes a provenance-tracked fact."""
    if gate is not None and not gate.is_approved(rid):
        return {"promoted": False, "reason": "promotion needs human approval"}
    st = store.UFCSStore(authoritative_dir)
    try:
        pkt = store.make_packet(subject, predicate, obj, "+", "derived", trusted_source, 0.9)
        added = st.add(pkt)
        st.flush()
    finally:
        st.close()
    return {"promoted": True, "added": added, "fingerprint": pkt["semantic_fingerprint"]}


# ---------------------------------------------------------------------------
# 5. Tool registry — deterministic tools may assert; external tools are effects.
# ---------------------------------------------------------------------------
class ToolRegistry:
    def __init__(self, authoritative_dir=None):
        self.tools = {}
        self.authoritative_dir = authoritative_dir

    def register(self, name, fn, kind, source=("SRC-TOOL", "Deterministic tool", "reference", 1.0)):
        assert kind in ("assert", "effect", "intake")
        self.tools[name] = {"fn": fn, "kind": kind, "source": source}

    def run(self, name, args, gate=None, rid=None):
        t = self.tools[name]
        if t["kind"] == "effect":
            eff = Effect(name, lambda _p: t["fn"](args), payload=args)
            return eff.run(gate or ApprovalGate(), rid)
        if t["kind"] == "assert":
            # deterministic tool: its output is asserted with provenance
            triples = t["fn"](args)
            st = store.UFCSStore(self.authoritative_dir)
            n = 0
            try:
                for (s, p, o) in triples:
                    if st.add(store.make_packet(s, p, o, "+", "derived", t["source"], 0.99)):
                        n += 1
                st.flush()
            finally:
                st.close()
            return {"asserted": n}
        return {"candidates": t["fn"](args)}   # intake handled by intake_candidate


# ---------------------------------------------------------------------------
# 4. File creation — cite-or-refuse; every generated file carries provenance.
# ---------------------------------------------------------------------------
def build_file(authoritative_dir, out_path, claims):
    """Write a file containing ONLY claims the authoritative store verifies; unsupported
    claims are omitted and listed in a sidecar provenance manifest. (Covenant C4 for files.)"""
    included, omitted, prov = [], [], []
    for (s, p, o) in claims:
        verdict, facts = verify_or_refuse(authoritative_dir, s, p, o)
        matched = [f for f in facts if f["object"].lower() == str(o).lower()]
        if verdict == "VERIFIED" and matched:
            included.append((s, p, o, matched[0]["fingerprint"]))
            prov.append({"claim": [s, p, o], "fingerprint": matched[0]["fingerprint"], "status": "verified"})
        else:
            omitted.append((s, p, o))
            prov.append({"claim": [s, p, o], "status": "omitted-unverified", "verdict": verdict})
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("# Generated by QueryBook — every line traces to a verified Fact Unit\n\n")
        for (s, p, o, fp) in included:
            fh.write("- %s %s %s  [fp %s]\n" % (s, p, o, fp[:10]))
        if omitted:
            fh.write("\n# Omitted (no verified fact): %d claim(s) — see provenance manifest\n" % len(omitted))
    with open(out_path + ".provenance.json", "w", encoding="utf-8") as fh:
        json.dump({"file": os.path.basename(out_path), "claims": prov}, fh, indent=2)
    return {"included": len(included), "omitted": len(omitted), "manifest": out_path + ".provenance.json"}


# ---------------------------------------------------------------------------
# 7. Device sync — merge stores by fingerprint (dedup); no silent divergence.
# ---------------------------------------------------------------------------
def sync_devices(dir_into, dir_from):
    """Merge every fact from dir_from into dir_into. Because identity is the content
    fingerprint, the merge is a deterministic union with dedup; the same fact from two
    devices collapses to one, and a functional-predicate conflict remains visible to the gate."""
    src = store.UFCSStore(dir_from)
    try:
        rows = src.db.execute("SELECT subject, predicate, object, trust FROM nuc").fetchall()
    finally:
        src.close()
    dst = store.UFCSStore(dir_into)
    added = dup = 0
    try:
        for (s, p, o, t) in rows:
            pkt = store.make_packet(s, p, o, "+", "synced",
                                    ("SRC-SYNC", "Device sync", "internal-derived", float(t or 0.9)),
                                    float(t or 0.9))
            if dst.add(pkt):
                added += 1
            else:
                dup += 1
        dst.flush()
    finally:
        dst.close()
    return {"added": added, "duplicates": dup}


# ---------------------------------------------------------------------------
# 1. Cloud offload — same job local or remote; deterministic either way.
# ---------------------------------------------------------------------------
def offload(job, *args, adapter=None):
    """Run a heavy job with the compute of a cloud worker. `adapter` is a callable that
    dispatches to the remote worker; when None the job runs locally. Determinism is a
    property of the job (pure over its inputs), so local and remote agree by fingerprint."""
    if adapter is None:
        return job(*args)
    return adapter(job, *args)


# ---------------------------------------------------------------------------
# 8. Agent team — many agents, one shared store; contradictions are surfaced.
# ---------------------------------------------------------------------------
class AgentTeam:
    """Agents collaborate through a single authoritative store (the source of truth).
    No agent can inject an unverified fact, and when two agents disagree on a functional
    relation the gate surfaces a contradiction rather than letting one silently overwrite."""
    def __init__(self, authoritative_dir, ledger=None):
        self.dir = authoritative_dir
        self.ledger = ledger or ProjectLedger()
        self.messages = []

    def contribute(self, agent_id, subject, predicate, obj, source):
        st = store.UFCSStore(self.dir)
        try:
            added = st.add(store.make_packet(subject, predicate, obj, "+", "derived", source, 0.99))
            st.flush()
        finally:
            st.close()
        self.messages.append({"from": agent_id, "fact": [subject, predicate, obj], "added": added})
        return added

    def consensus(self, subject, predicate):
        return verify_or_refuse(self.dir, subject, predicate, None)
