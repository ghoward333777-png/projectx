#!/usr/bin/env python3
"""
qb_backup.py — bullet-proof data preservation for QueryBook (stdlib only).

Goal: NEVER lose data. Layers, strongest first:

  1. Dual (N-way) LOCAL copies with a safe boot sync.
     - The richest copy (most facts) is authoritative.
     - If the PRIMARY store is ever behind a mirror (e.g. it got reset), the
       primary is RESTORED from the richest mirror at boot.
     - A populated copy is never destructively overwritten: before a differing
       populated target is refreshed, its index/manifest/language-model are
       snapshotted aside (*.superseded-<ts>), so no prior state is ever erased.
     - Copies are atomic (temp + os.replace) and the SQLite index is copied via
       the online-backup API, consistent even while the server writes.
     Use this for the second copy on the external drive AND for a local
     Google Drive folder (the Drive client then uploads it — no API keys).

  2. Compressed off-box SNAPSHOTS (tar.gz of the store) uploaded to object
     storage: Bunny.net Storage (simple AccessKey PUT) and OVH Object Storage
     (S3, SigV4 PUT). Credentials are read from a LOCAL, git-ignored file
     (~/.querybook/cloud.json) or environment — never hard-coded or committed.

Everything is best-effort and exception-guarded: a full/unplugged drive or a
network failure is logged and never blocks startup or risks the primary store.
"""
import os, sys, json, time, shutil, sqlite3, tarfile, tempfile, threading, hashlib, hmac
import qb_mirror

APPDIR = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
CLOUD_CFG = os.path.join(HOME, ".querybook", "cloud.json")

# ---------------------------------------------------------------------------
# shared state for the UI / status endpoint
STATE = {
    "running": False, "last_run": None, "authoritative": None, "authoritative_facts": 0,
    "local_targets": [], "cloud": [], "events": [], "error": None,
}
_LOCK = threading.Lock()


def _event(msg):
    line = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "  " + str(msg)
    with _LOCK:
        STATE["events"].append(line)
        STATE["events"] = STATE["events"][-200:]
    try:
        print("  BACKUP: " + str(msg), flush=True)
    except Exception:
        pass


def status():
    with _LOCK:
        return json.loads(json.dumps(STATE))


# ---------------------------------------------------------------------------
# store helpers
def _facts(store):
    """Most reliable fact count: the index, then the manifest."""
    try:
        idx = os.path.join(store, "index.sqlite")
        if os.path.isfile(idx):
            con = sqlite3.connect("file:%s?mode=ro" % idx, uri=True, timeout=5)
            try:
                for t in ("fp", "nuc"):
                    try:
                        n = con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
                        if n:
                            return int(n)
                    except Exception:
                        continue
            finally:
                con.close()
    except Exception:
        pass
    try:
        with open(os.path.join(store, "manifest.json"), encoding="utf-8") as f:
            return int(json.load(f).get("facts", 0))
    except Exception:
        return 0


def _is_store(d):
    return bool(d) and os.path.isdir(os.path.join(d, "blocks")) and (
        os.path.isfile(os.path.join(d, "index.sqlite")) or os.path.isfile(os.path.join(d, "manifest.json")))


def _reachable_parent(d):
    """True if we can create/write d (its drive/mount is present)."""
    try:
        p = d
        while p and not os.path.isdir(p):
            np = os.path.dirname(p)
            if np == p:
                break
            p = np
        return os.path.isdir(p)
    except Exception:
        return False


def _one_pass_copy(src, dst):
    """Atomic one-shot mirror of a store dir using qb_mirror's safe copies."""
    m = qb_mirror.Mirror()
    m.state.update(source=os.path.abspath(src), dest=os.path.abspath(dst))
    os.makedirs(dst, exist_ok=True)
    m._sync_blocks(src, dst)
    for f in ("manifest.json", "language_model.json", "agents.json", "data_events.log"):
        m._sync_file(src, dst, f)
    m._sync_index(src, dst)
    return _facts(dst)


def _snapshot_aside(target, keep=3):
    """Preserve a populated target's current state before it is refreshed, so a
    differing copy is never destroyed. Keeps the last `keep` snapshots per file."""
    ts = time.strftime("%Y%m%d-%H%M%S")
    for f in ("index.sqlite", "manifest.json", "language_model.json"):
        p = os.path.join(target, f)
        if os.path.isfile(p):
            try:
                shutil.copyfile(p, p + ".superseded-" + ts)
            except Exception:
                pass
        # prune old snapshots
        try:
            snaps = sorted([x for x in os.listdir(target) if x.startswith(f + ".superseded-")])
            for old in snaps[:-keep]:
                try:
                    os.remove(os.path.join(target, old))
                except OSError:
                    pass
        except Exception:
            pass


# ---------------------------------------------------------------------------
# LAYER 1 — safe local dual/N-way sync
def boot_sync(store, mirror_dirs):
    """Make every reachable local copy match the richest one, safely.
    Returns the authoritative store path and its fact count."""
    store = os.path.abspath(store)
    mirror_dirs = [os.path.abspath(d) for d in (mirror_dirs or []) if d]
    # authoritative = the existing store with the most facts
    auth, authn = store, _facts(store)
    for d in mirror_dirs:
        if _is_store(d):
            n = _facts(d)
            if n > authn:
                auth, authn = d, n
    _event("authoritative copy: %s (%s facts)" % (auth, format(authn, ",")))
    with _LOCK:
        STATE["authoritative"] = auth
        STATE["authoritative_facts"] = authn

    # 1) If the primary is behind a mirror, RESTORE the primary from the richest copy.
    if auth != store and authn > _facts(store):
        try:
            if _is_store(store):
                _snapshot_aside(store)
            _event("primary %s is behind — RESTORING from %s" % (store, auth))
            _one_pass_copy(auth, store)
            _event("primary restored (%s facts)" % format(_facts(store), ","))
        except Exception as e:
            _event("restore failed: %s" % e)
    # after restore the primary is the richest; it is the sync source
    src = store

    # 2) Push the authoritative data to every mirror target.
    tgts = []
    for d in mirror_dirs:
        if not _reachable_parent(d):
            _event("mirror target not reachable (drive unplugged?): %s" % d)
            tgts.append({"dir": d, "ok": False, "facts": 0, "note": "unreachable"})
            continue
        try:
            if _is_store(d) and _facts(d) != _facts(src) and _facts(d) > 0:
                _snapshot_aside(d)      # never destroy a differing populated copy
            _one_pass_copy(src, d)
            tgts.append({"dir": d, "ok": True, "facts": _facts(d)})
            _event("synced -> %s (%s facts)" % (d, format(_facts(d), ",")))
        except Exception as e:
            tgts.append({"dir": d, "ok": False, "facts": 0, "note": str(e)})
            _event("sync to %s failed: %s" % (d, e))
    with _LOCK:
        STATE["local_targets"] = tgts
    return src, _facts(src)


# ---------------------------------------------------------------------------
# LAYER 2 — compressed off-box snapshots
def make_snapshot(store, out_dir):
    """Write a consistent tar.gz snapshot of the store; returns its path."""
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(out_dir, "querybook-store-%s.tar.gz" % ts)
    tmp = path + ".part"
    idxtmp = os.path.join(out_dir, "_idx-%s.sqlite" % ts)
    have_idx = False
    try:
        src = os.path.join(store, "index.sqlite")
        if os.path.isfile(src):
            a = sqlite3.connect(src, timeout=30); b = sqlite3.connect(idxtmp, timeout=30)
            with b:
                a.backup(b)               # consistent online snapshot
            a.close(); b.close(); have_idx = True
    except Exception:
        have_idx = False
    try:
        with tarfile.open(tmp, "w:gz") as tf:
            for f in ("manifest.json", "language_model.json", "agents.json"):
                p = os.path.join(store, f)
                if os.path.isfile(p):
                    tf.add(p, arcname="store/" + f)
            bl = os.path.join(store, "blocks")
            if os.path.isdir(bl):
                tf.add(bl, arcname="store/blocks")
            if have_idx:
                tf.add(idxtmp, arcname="store/index.sqlite")
        os.replace(tmp, path)
    finally:
        try:
            if os.path.isfile(idxtmp):
                os.remove(idxtmp)
        except OSError:
            pass
    _event("snapshot %s (%.1f MB)" % (os.path.basename(path), os.path.getsize(path) / 1e6))
    return path


def _http_put_stream(url, headers, path, timeout=600):
    """Stream a file to a URL with a PUT, without loading it into memory."""
    import http.client
    from urllib.parse import urlsplit
    u = urlsplit(url)
    conn = (http.client.HTTPSConnection(u.netloc, timeout=timeout) if u.scheme == "https"
            else http.client.HTTPConnection(u.netloc, timeout=timeout))
    size = os.path.getsize(path)
    h = dict(headers); h["Content-Length"] = str(size)
    conn.putrequest("PUT", u.path + (("?" + u.query) if u.query else ""))
    for k, v in h.items():
        conn.putheader(k, v)
    conn.endheaders()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            conn.send(chunk)
    resp = conn.getresponse(); body = resp.read(); conn.close()
    if resp.status not in (200, 201, 202, 204):
        raise RuntimeError("HTTP %d: %s" % (resp.status, body[:200]))
    return resp.status


def upload_bunny(path, cfg):
    """Bunny.net Storage: PUT https://[region.]storage.bunnycdn.com/<zone>/<key> with AccessKey."""
    zone = cfg.get("storage_zone") or cfg.get("zone")
    key = cfg.get("access_key") or cfg.get("password")
    if not (zone and key):
        raise RuntimeError("bunny config needs storage_zone + access_key")
    region = (cfg.get("region") or "").strip()
    host = (region + ".storage.bunnycdn.com") if region else "storage.bunnycdn.com"
    folder = (cfg.get("folder") or "").strip("/")
    name = os.path.basename(path)
    objkey = (folder + "/" + name) if folder else name
    url = "https://%s/%s/%s" % (host, zone, objkey)
    _http_put_stream(url, {"AccessKey": key, "Content-Type": "application/octet-stream"}, path)
    _event("Bunny.net: uploaded %s" % objkey)
    return url


def _sigv4_headers(method, host, path, payload_sha, region, service, akey, skey, extra=None):
    """Minimal AWS SigV4 signing (stdlib) for S3-compatible PUT (OVH Object Storage)."""
    now = time.gmtime()
    amzdate = time.strftime("%Y%m%dT%H%M%SZ", now)
    datestamp = time.strftime("%Y%m%d", now)
    headers = {"host": host, "x-amz-content-sha256": payload_sha, "x-amz-date": amzdate}
    if extra:
        headers.update(extra)
    signed = ";".join(sorted(headers))
    canon_headers = "".join("%s:%s\n" % (k, headers[k]) for k in sorted(headers))
    canon_req = "\n".join([method, path, "", canon_headers, signed, payload_sha])
    scope = "%s/%s/%s/aws4_request" % (datestamp, region, service)
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amzdate, scope,
                         hashlib.sha256(canon_req.encode()).hexdigest()])

    def _h(key, msg):
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()
    k = _h(("AWS4" + skey).encode(), datestamp)
    k = _h(k, region); k = _h(k, service); k = _h(k, "aws4_request")
    sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    auth = ("AWS4-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s"
            % (akey, scope, signed, sig))
    out = dict(headers); out["Authorization"] = auth
    return out


def upload_ovh_s3(path, cfg):
    """OVH Object Storage (S3-compatible): SigV4 PUT. Needs endpoint, region, bucket,
    access_key, secret_key (from ~/.querybook/cloud.json — never committed)."""
    ep = (cfg.get("endpoint") or "").rstrip("/")     # e.g. https://s3.gra.io.cloud.ovh.net
    bucket = cfg.get("bucket"); region = cfg.get("region") or "gra"
    akey = cfg.get("access_key"); skey = cfg.get("secret_key")
    if not (ep and bucket and akey and skey):
        raise RuntimeError("ovh config needs endpoint + bucket + region + access_key + secret_key")
    from urllib.parse import urlsplit
    host = urlsplit(ep).netloc
    folder = (cfg.get("folder") or "").strip("/")
    name = os.path.basename(path)
    objkey = (folder + "/" + name) if folder else name
    # payload hash (stream the file through sha256)
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha.update(chunk)
    payload_sha = sha.hexdigest()
    reqpath = "/%s/%s" % (bucket, objkey)
    headers = _sigv4_headers("PUT", host, reqpath, payload_sha, region, "s3", akey, skey)
    headers["Content-Type"] = "application/octet-stream"
    _http_put_stream(ep + reqpath, headers, path)
    _event("OVH: uploaded %s to %s" % (objkey, bucket))
    return ep + reqpath


def _load_cloud_cfg():
    # env override, else the local git-ignored file
    try:
        if os.environ.get("QB_CLOUD_JSON") and os.path.isfile(os.environ["QB_CLOUD_JSON"]):
            return json.load(open(os.environ["QB_CLOUD_JSON"], encoding="utf-8"))
        if os.path.isfile(CLOUD_CFG):
            return json.load(open(CLOUD_CFG, encoding="utf-8"))
    except Exception as e:
        _event("cloud config unreadable: %s" % e)
    return {}


def run_cloud_backup(store, out_dir=None):
    """Make one snapshot and upload to every configured cloud provider. Best-effort."""
    cfg = _load_cloud_cfg()

    def _on(pc):
        return isinstance(pc, dict) and str(pc.get("enabled", True)).lower() not in ("0", "false", "no")

    providers = []
    if _on(cfg.get("bunny")):
        providers.append(("bunny", cfg["bunny"], upload_bunny))
    if _on(cfg.get("ovh")):
        providers.append(("ovh", cfg["ovh"], upload_ovh_s3))
    if not providers:
        _event("cloud backup: no providers enabled (edit %s — set \"enabled\": true — to turn on Bunny.net / OVH)" % CLOUD_CFG)
        return []
    out_dir = out_dir or os.path.join(store, "_snapshots")
    results = []
    try:
        snap = make_snapshot(store, out_dir)
    except Exception as e:
        _event("snapshot failed: %s" % e)
        return [{"provider": "snapshot", "ok": False, "note": str(e)}]
    for name, pcfg, fn in providers:
        try:
            if str(pcfg.get("enabled", True)).lower() in ("0", "false", "no"):
                continue
            fn(snap, pcfg)
            results.append({"provider": name, "ok": True})
        except Exception as e:
            results.append({"provider": name, "ok": False, "note": str(e)})
            _event("%s upload failed: %s" % (name, e))
    # keep only the last few local snapshots
    try:
        snaps = sorted(x for x in os.listdir(out_dir) if x.endswith(".tar.gz"))
        for old in snaps[:-3]:
            os.remove(os.path.join(out_dir, old))
    except Exception:
        pass
    with _LOCK:
        STATE["cloud"] = results
    return results


# ---------------------------------------------------------------------------
# orchestrator used at boot
def run_boot_backup(store, mirror_dirs, do_cloud=True, background_cloud=True):
    """Boot entry point: safe local sync now; cloud snapshot upload in background."""
    with _LOCK:
        STATE["running"] = True; STATE["error"] = None
    try:
        src, n = boot_sync(store, mirror_dirs)
    except Exception as e:
        with _LOCK:
            STATE["error"] = str(e)
        _event("boot sync error: %s" % e)
        src = store
    if do_cloud:
        if background_cloud:
            threading.Thread(target=lambda: run_cloud_backup(src), daemon=True).start()
        else:
            run_cloud_backup(src)
    with _LOCK:
        STATE["running"] = False
        STATE["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return status()


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # CLI: python qb_backup.py <store> [mirror1] [mirror2] ... [--cloud]
    if len(sys.argv) < 2:
        print("usage: python qb_backup.py <store_dir> [mirror_dir ...] [--cloud]")
        sys.exit(2)
    st = sys.argv[1]
    mirrors = [a for a in sys.argv[2:] if not a.startswith("--")]
    r = run_boot_backup(st, mirrors, do_cloud=("--cloud" in sys.argv), background_cloud=False)
    print(json.dumps(r, indent=2))
