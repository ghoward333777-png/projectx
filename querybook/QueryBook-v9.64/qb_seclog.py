"""Immutable security log  [append-only · hash-chained · Merkle checkpoints · WORM]

Implements the logging layer of the Agent Protection & Deception spec (L1–L5):

  L1  every agent call, security event and firewall decision is appended here
  L2  each entry's hash covers the previous entry's hash (hash chain); every CHECKPOINT_EVERY
      entries (and on demand) a Merkle root over the new entries is written to a write-once
      checkpoint file (read-only on disk, never overwritten), HMAC-signed, chained to the
      previous checkpoint, optionally mirrored to a second location (QB_SECLOG_MIRROR, e.g. a
      USB drive or network share) and optionally anchored on a blockchain via qb_nft
  L3  entries carry agent, caller, session, UFCS command, parameter hash, decision and flags
  L4  verify(start, end) re-proves a range; proof(seq) returns a Merkle inclusion proof
  L5  this module exposes append only — there is no update or delete; the log file is opened
      in append mode; checkpoints are refused if they already exist

HONEST LIMITS. On one machine, someone with full control of the files and the key can rebuild
a consistent fake log. What stops that is evidence held ELSEWHERE: a mirror on another device,
and blockchain-anchored checkpoint roots (anchor()). verify() reports which protections the
current log actually has.
"""

import hashlib as _h
import hmac as _hmac
import json as _json
import os as _os
import threading as _threading
import time as _time

CHECKPOINT_EVERY = 256
_LOCK = _threading.RLock()


class SecLogError(Exception):
    pass


def _home():
    d = _os.environ.get("QB_SECLOG_DIR") or _os.path.join(_os.path.expanduser("~"), ".querybook", "seclog")
    _os.makedirs(_os.path.join(d, "checkpoints"), exist_ok=True)
    return d


def _paths():
    d = _home()
    return {"log": _os.path.join(d, "security.log.jsonl"), "cp": _os.path.join(d, "checkpoints"),
            "key": _os.path.join(d, "seclog.key"), "dir": d}


def _key():
    p = _paths()["key"]
    try:
        with open(p, "rb") as f:
            return f.read().strip()
    except OSError:
        k = _h.sha256(_os.urandom(64)).hexdigest().encode()
        with open(p, "wb") as f:
            f.write(k)
        try:
            _os.chmod(p, 0o400)
        except OSError:
            pass
        return k


def _canon(obj):
    return _json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _entry_hash(e):
    return _h.sha256(_canon({k: v for k, v in e.items() if k != "hash"}).encode("utf-8")).hexdigest()


def params_hash(params):
    try:
        return _h.sha256(_canon(params).encode("utf-8")).hexdigest()
    except (TypeError, ValueError):
        return _h.sha256(repr(params).encode("utf-8")).hexdigest()


# ---- state (last seq/hash) -------------------------------------------------
_state = {"loaded_for": None, "seq": 0, "hash": "GENESIS", "since_cp": 0, "cp_n": 0, "cp_hash": "GENESIS"}


def _tail():
    p = _paths()
    if _state["loaded_for"] == p["log"]:
        return
    seq, last, torn = 0, "GENESIS", False
    if _os.path.exists(p["log"]):
        with open(p["log"], "rb") as f:
            for line in f:
                if not line.endswith(b"\n"):
                    torn = True
                    break
                try:
                    e = _json.loads(line)
                except ValueError:
                    torn = True
                    continue
                seq, last = e["seq"], e["hash"]
    cps = sorted(n for n in _os.listdir(p["cp"]) if n.startswith("cp-") and n.endswith(".json"))
    cp_n, cp_hash, cp_end = 0, "GENESIS", 0
    if cps:
        with open(_os.path.join(p["cp"], cps[-1]), encoding="utf-8") as f:
            cp = _json.load(f)
        cp_n, cp_hash, cp_end = cp["n"], cp["cp_hash"], cp["end"]
    _state.update(loaded_for=p["log"], seq=seq, hash=last, since_cp=seq - cp_end, cp_n=cp_n, cp_hash=cp_hash)
    if torn:
        # A crash mid-write leaves a partial last line. Never hide it: record that it happened.
        with open(p["log"], "ab") as f:
            f.write(b"\n")
        append("LOG_RECOVERY", decision="note", detail="partial trailing entry found and preserved at load")


def append(event, agent_id=None, caller_id=None, session_id=None, ufcs_command=None, params=None,
           decision="allow", flags=None, detail=None, severity="info"):
    """Append one entry (the only write operation). Raises SecLogError if it cannot be made durable."""
    with _LOCK:
        _tail()
        p = _paths()
        e = {"seq": _state["seq"] + 1, "ts": round(_time.time(), 6), "prev": _state["hash"], "event": event,
             "severity": severity, "agent_id": agent_id, "caller_id": caller_id, "session_id": session_id,
             "ufcs_command": ufcs_command, "params_hash": params_hash(params) if params is not None else None,
             "decision": decision, "flags": list(flags or []), "detail": (str(detail)[:500] if detail else None)}
        e["hash"] = _entry_hash(e)
        line = (_canon(e) + "\n").encode("utf-8")
        try:
            with open(p["log"], "ab") as f:
                f.write(line)
                f.flush()
                _os.fsync(f.fileno())
        except OSError as err:
            raise SecLogError("security log unavailable: %s" % err)
        mirror = _os.environ.get("QB_SECLOG_MIRROR")
        if mirror:
            try:
                _os.makedirs(mirror, exist_ok=True)
                with open(_os.path.join(mirror, "security.log.jsonl"), "ab") as f:
                    f.write(line)
            except OSError:
                pass   # the primary is durable; verify() reports a lagging mirror
        _state["seq"], _state["hash"] = e["seq"], e["hash"]
        _state["since_cp"] += 1
        if _state["since_cp"] >= CHECKPOINT_EVERY:
            checkpoint()
        return e


# ---- Merkle ------------------------------------------------------------------
def _merkle_levels(leaves):
    level = [bytes.fromhex(x) for x in leaves]
    levels = [level]
    while len(level) > 1:
        if len(level) % 2:
            level = level + [level[-1]]
        level = [_h.sha256(b"\x01" + level[i] + level[i + 1]).digest() for i in range(0, len(level), 2)]
        levels.append(level)
    return levels


def merkle_root(leaves):
    if not leaves:
        return _h.sha256(b"").hexdigest()
    return _merkle_levels(leaves)[-1][0].hex()


def _merkle_proof(leaves, index):
    proof, levels = [], _merkle_levels(leaves)
    for level in levels[:-1]:
        lv = level + [level[-1]] if len(level) % 2 else level
        sib = index ^ 1
        proof.append({"side": "left" if sib < index else "right", "hash": lv[sib].hex()})
        index //= 2
    return proof


def verify_proof(leaf_hash, proof, root):
    cur = bytes.fromhex(leaf_hash)
    for step in proof:
        sib = bytes.fromhex(step["hash"])
        cur = _h.sha256(b"\x01" + (sib + cur if step["side"] == "left" else cur + sib)).digest()
    return cur.hex() == root


# ---- reading -----------------------------------------------------------------
def entries(start=1, end=None):
    p = _paths()
    out = []
    if not _os.path.exists(p["log"]):
        return out
    with open(p["log"], "rb") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                e = _json.loads(line)
            except ValueError:
                out.append({"seq": None, "corrupt": line[:120].decode("utf-8", "replace")})
                continue
            if e.get("seq", 0) < start:
                continue
            if end is not None and e.get("seq", 0) > end:
                break
            out.append(e)
    return out


def recent(limit=100, event=None):
    rows = entries()
    if event:
        rows = [r for r in rows if r.get("event") == event]
    return rows[-limit:]


def checkpoints():
    p = _paths()
    out = []
    for n in sorted(x for x in _os.listdir(p["cp"]) if x.startswith("cp-") and x.endswith(".json")):
        with open(_os.path.join(p["cp"], n), encoding="utf-8") as f:
            out.append(_json.load(f))
    return out


# ---- checkpoints (WORM) ---------------------------------------------------------
def checkpoint(anchor=False):
    """Seal everything since the last checkpoint into a write-once Merkle checkpoint."""
    with _LOCK:
        _tail()
        p = _paths()
        start = _state["seq"] - _state["since_cp"] + 1
        if _state["since_cp"] <= 0:
            return None
        rows = entries(start, _state["seq"])
        leaves = [r["hash"] for r in rows]
        n = _state["cp_n"] + 1
        cp = {"n": n, "start": start, "end": _state["seq"], "count": len(leaves), "root": merkle_root(leaves),
              "last_entry_hash": _state["hash"], "prev_cp": _state["cp_hash"], "ts": round(_time.time(), 3)}
        cp["cp_hash"] = _h.sha256(_canon(cp).encode()).hexdigest()
        cp["hmac"] = _hmac.new(_key(), cp["cp_hash"].encode(), _h.sha256).hexdigest()
        path = _os.path.join(p["cp"], "cp-%06d.json" % n)
        try:
            fd = _os.open(path, _os.O_WRONLY | _os.O_CREAT | _os.O_EXCL, 0o444)   # refuses to overwrite
        except FileExistsError:
            raise SecLogError("checkpoint %d already exists (write-once): refusing to overwrite" % n)
        with _os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(_json.dumps(cp, indent=1))
            f.flush()
            _os.fsync(f.fileno())
        mirror = _os.environ.get("QB_SECLOG_MIRROR")
        if mirror:
            try:
                _os.makedirs(_os.path.join(mirror, "checkpoints"), exist_ok=True)
                mp = _os.path.join(mirror, "checkpoints", "cp-%06d.json" % n)
                if not _os.path.exists(mp):
                    with open(mp, "w", encoding="utf-8") as f:
                        f.write(_json.dumps(cp, indent=1))
                    _os.chmod(mp, 0o444)
            except OSError:
                pass
        _state.update(since_cp=0, cp_n=n, cp_hash=cp["cp_hash"])
    if anchor:
        cp["anchor"] = anchor_checkpoint(n)
    return cp


def anchor_checkpoint(n):
    """Certify a checkpoint's Merkle root on-chain (qb_nft, test network by default).
    The receipt is stored next to the checkpoint (the checkpoint itself stays untouched)."""
    cps = {c["n"]: c for c in checkpoints()}
    cp = cps.get(int(n))
    if not cp:
        return {"ok": False, "error": "no checkpoint %s" % n}
    try:
        import qb_nft
        res = qb_nft.mint("provenance", "seclog-cp-%06d" % cp["n"], content=cp["root"],
                          extra={"log_range": "%d-%d" % (cp["start"], cp["end"]), "cp_hash": cp["cp_hash"]})
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if res.get("ok"):
        rp = _os.path.join(_paths()["cp"], "anchor-%06d.json" % cp["n"])
        if not _os.path.exists(rp):
            with open(rp, "w", encoding="utf-8") as f:
                _json.dump({"n": cp["n"], "root": cp["root"], "token": res["token"]}, f, indent=1)
            _os.chmod(rp, 0o444)
        append("LOG_ANCHORED", decision="note", detail="checkpoint %d root on chain %s token %s" %
               (cp["n"], res["token"]["chain_id"], res["token"]["token_id"]))
    return res


# ---- verification (L4) -----------------------------------------------------------
def verify(start=1, end=None, check_chain=False):
    """Prove a log range is intact. Returns ok, the first problem found, and which protections exist."""
    rows = entries(1, end)
    problems = []
    prev = "GENESIS"
    by_seq = {}
    for i, e in enumerate(rows):
        if e.get("seq") is None:
            problems.append({"at": i + 1, "problem": "unparseable entry"})
            continue
        if e["seq"] != i + 1:
            problems.append({"at": e["seq"], "problem": "sequence gap or reorder (expected %d)" % (i + 1)})
        if e["prev"] != prev:
            problems.append({"at": e["seq"], "problem": "hash chain broken (entry removed, inserted or edited before it)"})
        actual = _entry_hash(e)          # recomputed from content, never trusted from the file
        if actual != e["hash"]:
            problems.append({"at": e["seq"], "problem": "entry content altered"})
        prev = e["hash"]
        by_seq[e["seq"]] = dict(e, hash=actual)
    cps = checkpoints()
    key = _key()
    cp_prev = "GENESIS"
    for cp in cps:
        body = {k: v for k, v in cp.items() if k not in ("cp_hash", "hmac")}
        if _h.sha256(_canon(body).encode()).hexdigest() != cp["cp_hash"]:
            problems.append({"checkpoint": cp["n"], "problem": "checkpoint file altered"})
        if not _hmac.compare_digest(_hmac.new(key, cp["cp_hash"].encode(), _h.sha256).hexdigest(), cp["hmac"]):
            problems.append({"checkpoint": cp["n"], "problem": "checkpoint signature invalid"})
        if cp["prev_cp"] != cp_prev:
            problems.append({"checkpoint": cp["n"], "problem": "checkpoint chain broken"})
        cp_prev = cp["cp_hash"]
        leaves = [by_seq[s]["hash"] for s in range(cp["start"], cp["end"] + 1) if s in by_seq]
        if len(leaves) != cp["count"] or merkle_root(leaves) != cp["root"]:
            problems.append({"checkpoint": cp["n"], "problem": "entries no longer match the sealed Merkle root"})
    mirror = _os.environ.get("QB_SECLOG_MIRROR")
    protections = {"hash_chain": True, "merkle_checkpoints": len(cps), "write_once_checkpoints": True,
                   "mirror": bool(mirror), "anchored_checkpoints": 0}
    anchors = [n for n in _os.listdir(_paths()["cp"]) if n.startswith("anchor-")]
    protections["anchored_checkpoints"] = len(anchors)
    chain_checks = []
    if check_chain and anchors:
        try:
            import qb_nft
            for a in sorted(anchors):
                with open(_os.path.join(_paths()["cp"], a), encoding="utf-8") as f:
                    rec = _json.load(f)
                v = qb_nft.verify(rec["token"]["token_id"], content=rec["root"])
                ok = bool(v.get("content_matches"))
                chain_checks.append({"checkpoint": rec["n"], "on_chain_match": ok})
                if not ok:
                    problems.append({"checkpoint": rec["n"], "problem": "on-chain anchor does not match"})
        except Exception as e:
            chain_checks.append({"error": str(e)})
    if mirror:
        mp = _os.path.join(mirror, "security.log.jsonl")
        try:
            with open(mp, "rb") as f:
                mrows = [_json.loads(x) for x in f if x.strip()]
            mismatch = [m["seq"] for m in mrows if m["seq"] in by_seq and by_seq[m["seq"]]["hash"] != m["hash"]]
            if mismatch:
                problems.append({"at": mismatch[0], "problem": "primary log differs from the mirror"})
            protections["mirror_entries"] = len(mrows)
        except (OSError, ValueError) as e:
            protections["mirror_error"] = str(e)
    in_range = [p for p in problems if "at" not in p or (p["at"] or 0) >= start]
    return {"ok": not in_range, "range": [start, end or (rows[-1]["seq"] if rows else 0)], "entries": len(rows),
            "problems": in_range[:20], "protections": protections, "chain_checks": chain_checks,
            "head": rows[-1]["hash"] if rows else "GENESIS"}


def proof(seq):
    """Merkle inclusion proof of one entry against its sealed checkpoint (L4)."""
    seq = int(seq)
    for cp in checkpoints():
        if cp["start"] <= seq <= cp["end"]:
            rows = entries(cp["start"], cp["end"])
            leaves = [r["hash"] for r in rows]
            idx = seq - cp["start"]
            return {"ok": True, "entry": rows[idx], "checkpoint": cp["n"], "root": cp["root"],
                    "proof": _merkle_proof(leaves, idx),
                    "valid": verify_proof(leaves[idx], _merkle_proof(leaves, idx), cp["root"])}
    return {"ok": False, "error": "entry %d is not sealed in a checkpoint yet (POST /api/security/log/checkpoint)" % seq}


def status():
    with _LOCK:
        _tail()
        return {"dir": _paths()["dir"], "entries": _state["seq"], "head": _state["hash"],
                "checkpoints": _state["cp_n"], "unsealed": _state["since_cp"],
                "mirror": _os.environ.get("QB_SECLOG_MIRROR") or None}


# ---- QC -----------------------------------------------------------------------------
def qc():
    import shutil
    import tempfile
    d = tempfile.mkdtemp()
    old = _os.environ.get("QB_SECLOG_DIR"), _os.environ.get("QB_SECLOG_MIRROR")
    _os.environ["QB_SECLOG_DIR"] = _os.path.join(d, "log")
    _os.environ["QB_SECLOG_MIRROR"] = _os.path.join(d, "mirror")
    _state["loaded_for"] = None
    checks = []
    try:
        for i in range(300):
            append("AGENT_CALL", agent_id="a1", caller_id="c1", session_id="s1", ufcs_command="ufcs.query",
                   params={"i": i})
        checks.append(("auto-checkpoint after %d entries" % CHECKPOINT_EVERY, status()["checkpoints"] == 1))
        cp = checkpoint()
        checks.append(("manual checkpoint seals the rest", cp and cp["end"] == 300 and status()["unsealed"] == 0))
        checks.append(("intact log verifies", verify()["ok"]))
        pr = proof(42)
        checks.append(("Merkle inclusion proof valid", pr["ok"] and pr["valid"]))
        checks.append(("tampered proof rejected", not verify_proof("00" * 32, pr["proof"], pr["root"])))
        try:
            fd = _os.open(_os.path.join(_paths()["cp"], "cp-000001.json"), _os.O_WRONLY | _os.O_CREAT | _os.O_EXCL)
            _os.close(fd)
            refused = False
        except FileExistsError:
            refused = True
        checks.append(("checkpoint is write-once", refused))
        # Tamper: edit one entry's decision in place
        p = _paths()["log"]
        with open(p, "rb") as f:
            lines = f.readlines()
        e = _json.loads(lines[99])
        e["decision"] = "deny"
        lines[99] = (_canon(e) + "\n").encode()
        with open(p, "wb") as f:
            f.writelines(lines)
        v = verify()
        checks.append(("edited entry detected", not v["ok"] and any(x.get("at") == 100 for x in v["problems"])))
        checks.append(("edit also breaks the sealed Merkle root", any("Merkle" in x["problem"] for x in v["problems"])))
        checks.append(("mirror disagrees with edited primary", any("mirror" in x["problem"] for x in v["problems"])))
        # Tamper: delete an entry and re-hash everything after it (a careful forger)
        del lines[150]
        prev = "GENESIS"
        forged = []
        for i, raw in enumerate(lines):
            x = _json.loads(raw)
            x["seq"], x["prev"] = i + 1, prev
            x["hash"] = _entry_hash(x)
            prev = x["hash"]
            forged.append((_canon(x) + "\n").encode())
        with open(p, "wb") as f:
            f.writelines(forged)
        v2 = verify()
        checks.append(("re-hashed forgery still caught by checkpoints", not v2["ok"]))
        checks.append(("no update/delete API exists", not any(hasattr(_this(), n) for n in ("update", "delete", "remove", "edit"))))
    finally:
        for k, v in zip(("QB_SECLOG_DIR", "QB_SECLOG_MIRROR"), old):
            if v is None:
                _os.environ.pop(k, None)
            else:
                _os.environ[k] = v
        _state["loaded_for"] = None
        for root, dirs, files in _os.walk(d):
            for n in files:
                try:
                    _os.chmod(_os.path.join(root, n), 0o600)
                except OSError:
                    pass
        shutil.rmtree(d, ignore_errors=True)
    passed = sum(1 for _, c in checks if c)
    return {"passed": passed, "total": len(checks), "ok": passed == len(checks),
            "rows": [{"check": n, "pass": c} for n, c in checks]}


def _this():
    import sys
    return sys.modules[__name__]


if __name__ == "__main__":
    import sys
    if "--qc" in sys.argv:
        print(_json.dumps(qc(), indent=2))
    elif "verify" in sys.argv:
        print(_json.dumps(verify(check_chain="--chain" in sys.argv), indent=2))
    elif "checkpoint" in sys.argv:
        print(_json.dumps(checkpoint(anchor="--anchor" in sys.argv), indent=2))
    else:
        print(_json.dumps(status(), indent=2))
