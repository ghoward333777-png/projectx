"""qbfarm — farmed-out harvesting: another PC harvests datasets the main QueryBook server does not, and hands the facts
back sealed.

On the server (Control Panel → Harvesting → Farm out):
  * assign(machine, ip, os, datasets) — those datasets (or Wikidata lanes) go to that machine alone: the main server's
    harvester skips them (qbbulk asks farmed_out()) and no other machine can be given them;
  * package(id) — a zip for Windows (Python inside, when the server has the bundled one) or a Mac (uses python3), with
    the harvesting engine, this module and farm-config.json (machine, IP, datasets, the server's PUBLIC key);
  * import_folder(path) — opens every sealed file on a drive with the server's PRIVATE key (it never leaves the
    server), checks it came from an assignment the server made, and adds the facts (a fact already held is skipped).

On the harvesting PC (`python qbfarm.py agent`):
  * refuses to run on another machine or IP address than the assignment names;
  * runs the same bulk engine on its datasets only, in a hidden working folder;
  * every 2 minutes seals the facts filed since the last time (qbseal: only the server can open them) and deletes them
    from the working folder; keeps a tally of record types and counts — all the person running it sees;
  * a small page (http://127.0.0.1:8099) with the tally and "Back up to drive": the sealed files and the tally are copied
    to an external hard drive or pocket drive, to be carried to the server.
Facts still being read (not yet filed) are in the working folder until they are sealed (minutes): the guarantee is that
everything saved, backed up or carried is sealed.
"""
from __future__ import annotations

import base64
import datetime
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import socket
import sqlite3
import sys
import threading
import time
import zipfile

import qbseal

FARM = "farm"
VERSION = "1.0"
SEAL_EVERY_S = 120
CHUNK_FACTS = 200_000
AGENT_PORT = 8099


# ================================================================== server side
def farm_dir(commons_folder: str) -> str:
    d = os.path.join(commons_folder, FARM)
    os.makedirs(d, exist_ok=True)
    return d


def _load(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def server_keys(commons_folder: str) -> tuple[bytes, bytes]:
    """the server's sealing key pair, made once and kept in the data folder (the private half never goes in a package)"""
    p = os.path.join(farm_dir(commons_folder), "server_key.json")
    k = _load(p, None)
    if not k:
        priv, pub = qbseal.keypair()
        k = {"private": base64.b64encode(priv).decode(), "public": base64.b64encode(pub).decode(), "created": _now()}
        _save(p, k)
    return base64.b64decode(k["private"]), base64.b64decode(k["public"])


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def assignments(commons_folder: str) -> list[dict]:
    return _load(os.path.join(farm_dir(commons_folder), "assignments.json"), [])


def _save_assignments(commons_folder: str, rows: list[dict]) -> None:
    _save(os.path.join(farm_dir(commons_folder), "assignments.json"), rows)


def farmed_out(commons_folder: str) -> dict[str, str]:
    """dataset → machine, for every active assignment (the main harvester leaves these alone)"""
    return {k: a["machine"] for a in assignments(commons_folder) if a.get("status") == "active" for k in a["datasets"]}


MACHINE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")


def _valid_ip(ip: str) -> bool:
    try:
        socket.inet_pton(socket.AF_INET6 if ":" in ip else socket.AF_INET, ip)
        return True
    except (OSError, ValueError):
        return False


def assign(commons_folder: str, machine: str, ip: str, os_name: str, datasets: list[str], catalog: list[str],
           note: str = "") -> dict:
    """give datasets to one machine. Refused: a dataset given to another machine already, an unknown dataset, a bad
    machine name or IP address."""
    machine, ip = (machine or "").strip(), (ip or "").strip()
    if not MACHINE_RE.match(machine):
        raise ValueError("The machine name is the computer's name (Windows: Settings → System → About; Mac: System Settings → "
                         "General → About), letters, digits, dots and dashes.")
    if ip and not _valid_ip(ip):
        raise ValueError("%r is not an IP address (for example 192.168.1.42)." % ip)
    if os_name not in ("windows", "mac"):
        raise ValueError("Choose Windows or Mac.")
    ds = [d for d in dict.fromkeys(datasets or [])]
    if not ds:
        raise ValueError("Choose at least one dataset for this machine.")
    unknown = [d for d in ds if d not in catalog]
    if unknown:
        raise ValueError("Unknown dataset(s): %s" % ", ".join(unknown))
    taken = farmed_out(commons_folder)
    clash = ["%s (already given to %s)" % (d, taken[d]) for d in ds if d in taken]
    if clash:
        raise ValueError("Each dataset goes to one machine only: " + "; ".join(clash))
    server_keys(commons_folder)
    rows = assignments(commons_folder)
    a = {"id": "F" + hashlib.sha256(os.urandom(16)).hexdigest()[:8].upper(), "machine": machine, "ip": ip, "os": os_name,
         "datasets": ds, "note": (note or "").strip()[:200], "created": _now(), "status": "active",
         "token": base64.b64encode(os.urandom(18)).decode(), "imported": {"files": 0, "facts": 0, "new": 0, "tally": {}}}
    rows.append(a)
    _save_assignments(commons_folder, rows)
    return a


def revoke(commons_folder: str, aid: str) -> dict:
    rows = assignments(commons_folder)
    for a in rows:
        if a["id"] == aid:
            a["status"], a["revoked"] = "revoked", _now()
            _save_assignments(commons_folder, rows)
            return a
    raise ValueError("No such assignment.")


def public_view(a: dict) -> dict:
    """an assignment without its token (the token goes only into that machine's package)"""
    return {k: v for k, v in a.items() if k != "token"}


def _find_python_for_windows() -> str | None:
    """the bundled embeddable Python of the running QueryBook (QueryBook/python), if there is one"""
    for d in (os.path.dirname(sys.executable), os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python")):
        if os.path.isdir(d) and any(f.endswith("._pth") for f in os.listdir(d)) and os.path.exists(os.path.join(d, "python.exe")):
            return d
    return None


START_BAT = ("@echo off\r\nrem QueryBook Harvester - double-click to start. Keep this window open while it harvests.\r\n"
             "title QueryBook Harvester\r\ncd /d \"%~dp0\"\r\n"
             "if exist \"%~dp0python\\python.exe\" (\"%~dp0python\\python.exe\" -X utf8 \"%~dp0harvester\\qbfarm.py\" agent %*) "
             "else (python -X utf8 \"%~dp0harvester\\qbfarm.py\" agent %*)\r\nif errorlevel 1 pause\r\n")
START_MAC = ("#!/bin/bash\n# QueryBook Harvester - double-click to start (first time: right-click > Open > Open).\n"
             "cd \"$(dirname \"$0\")\"\nexec python3 harvester/qbfarm.py agent \"$@\"\n")
README = """QueryBook Harvester for {machine}
=================================

This copy harvests for the QueryBook server, on this computer only ({machine}{ip}).
Datasets: {datasets}

Start
  {start}
  Your browser opens the harvester's page. Keep the black window open while it harvests.

What you see
  How many records of each kind have been gathered. The records themselves are sealed: only the
  QueryBook server can open them.

Back up / hand over
  On the page, choose your external drive (hard drive or pocket drive) and press "Back up to drive".
  The sealed files and the tally are copied to <drive>/QueryBook-Harvest/{machine}/.
  Take the drive to the QueryBook server: Control Panel → Harvesting → Farm out → Import from drive.

Mac: needs Python 3 (python.org, or "xcode-select --install").
"""


def package(commons_folder: str, aid: str, program_dir: str, out_dir: str) -> str:
    """the harvester zip for one assignment: engine + this module + its config (the server's public key, never the private)"""
    a = next((x for x in assignments(commons_folder) if x["id"] == aid), None)
    if not a or a.get("status") != "active":
        raise ValueError("No active assignment %s." % aid)
    _, pub = server_keys(commons_folder)
    cfg = {"format": "qbfarm/1", "assignment": a["id"], "machine": a["machine"], "ip": a["ip"], "os": a["os"],
           "datasets": a["datasets"], "token": a["token"], "server_public_key": base64.b64encode(pub).decode(),
           "server_key_id": hashlib.sha256(pub).hexdigest()[:16], "created": a["created"], "version": VERSION}
    name = "QueryBook-Harvester-%s-%s" % (a["machine"], "Windows" if a["os"] == "windows" else "Mac")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name + ".zip")
    fixed = (2026, 1, 1, 0, 0, 0)

    def put(z: zipfile.ZipFile, arc: str, data: bytes, mode: int = 0o644) -> None:
        info = zipfile.ZipInfo(name + "/" + arc, fixed)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = mode << 16
        z.writestr(info, data)
    py = _find_python_for_windows() if a["os"] == "windows" else None
    with zipfile.ZipFile(path + ".part", "w") as z:
        put(z, "farm-config.json", json.dumps(cfg, indent=1).encode("utf-8"))
        start = "double-click START-Harvester.bat" if a["os"] == "windows" else "double-click START-Harvester.command"
        put(z, "README.txt", README.format(machine=a["machine"], ip=(", " + a["ip"]) if a["ip"] else "", datasets=", ".join(a["datasets"]),
                                           start=start).replace("\n", "\r\n" if a["os"] == "windows" else "\n").encode("utf-8"))
        if a["os"] == "windows":
            put(z, "START-Harvester.bat", START_BAT.encode("utf-8"), 0o755)
        else:
            put(z, "START-Harvester.command", START_MAC.encode("utf-8"), 0o755)
        for f in sorted(os.listdir(program_dir)):
            if f.endswith(".py") and f not in ("app.py",):
                with open(os.path.join(program_dir, f), "rb") as fh:
                    put(z, "harvester/" + f, fh.read(), 0o755)
        if py:
            for d, dirs, files in os.walk(py):
                dirs[:] = sorted(x for x in dirs if x != "__pycache__")
                for f in sorted(files):
                    if f.endswith(".pyc"):
                        continue
                    with open(os.path.join(d, f), "rb") as fh:
                        put(z, "python/" + os.path.relpath(os.path.join(d, f), py).replace(os.sep, "/"), fh.read())
    os.replace(path + ".part", path)
    return path


def import_folder(commons_folder: str, folder: str, open_shard=None) -> dict:
    """every sealed file under `folder` (a drive's QueryBook-Harvest folder, or a machine's folder in it): opened, checked
    against the assignment it claims, its facts added to that dataset (facts already held are skipped). A file imported
    before is skipped, so importing the same drive twice adds nothing."""
    priv, pub = server_keys(commons_folder)
    rows = assignments(commons_folder)
    by_id = {a["id"]: a for a in rows}
    seen_p = os.path.join(farm_dir(commons_folder), "imported.json")
    seen = set(_load(seen_p, []))
    out = {"files": 0, "skipped_before": 0, "refused": [], "facts": 0, "new": 0, "by_dataset": {}, "tally": {}}
    if not os.path.isdir(folder):
        raise ValueError("Folder not found: %s" % folder)
    files = sorted(os.path.join(d, f) for d, _, fs in os.walk(folder) for f in fs if f.endswith(".qbseal"))
    if open_shard is None:
        import qbbulk
        open_shard = lambda key: qbbulk.Shard(commons_folder, key)
    shards: dict = {}
    try:
        for p in files:
            try:
                with open(p, "rb") as f:
                    blob = f.read()
                hdr, data = qbseal.open_sealed(priv, blob)
            except (OSError, ValueError) as e:
                out["refused"].append({"file": os.path.basename(p), "why": str(e)})
                continue
            fid = hashlib.sha256(blob).hexdigest()
            if fid in seen:
                out["skipped_before"] += 1
                continue
            a = by_id.get(hdr.get("assignment"))
            if not a or hdr.get("token_hash") != hashlib.sha256(a["token"].encode()).hexdigest() or hdr.get("dataset") not in a["datasets"]:
                out["refused"].append({"file": os.path.basename(p), "why": "not from an assignment this server made (or for another dataset)"})
                continue
            key = hdr["dataset"]
            sh = shards.get(key) or shards.setdefault(key, open_shard(key))
            facts = [json.loads(line) for line in gzip.decompress(data).decode("utf-8").splitlines() if line]
            pid = sh.part("farm:%s:%s" % (a["machine"], hdr.get("part") or "?"), "farm:" + a["id"])[0]
            rows_ = [(bytes.fromhex(fp), s, sh.pred(pn), o, pid, r) for fp, s, pn, o, _pt, r in facts]
            for i in range(0, len(rows_), 100_000):
                sh.write(pid, rows_[i:i + 100_000], len(rows_[:i + 100_000]))
            new = sh.merge()
            seen.add(fid)
            out["files"] += 1
            out["facts"] += len(facts)
            out["new"] += new
            out["by_dataset"][key] = out["by_dataset"].get(key, 0) + new
            for t, n in (hdr.get("tally") or {}).items():
                out["tally"][t] = out["tally"].get(t, 0) + n
            im = a.setdefault("imported", {"files": 0, "facts": 0, "new": 0, "tally": {}})
            im["files"] += 1
            im["facts"] += len(facts)
            im["new"] += new
            im["last"] = _now()
            for t, n in (hdr.get("tally") or {}).items():
                im["tally"][t] = im["tally"].get(t, 0) + n
            _save(seen_p, sorted(seen))
            _save_assignments(commons_folder, rows)
    finally:
        for sh in shards.values():
            try:
                sh.db.close()
            except Exception:
                pass
    out["duplicates"] = out["facts"] - out["new"]
    return out


def add_routes(api, commons, program_dir: str) -> None:
    """Control Panel → Harvesting → Farm out: /api/farm, /api/farm/assign, /api/farm/revoke, /api/farm/package, /api/farm/import"""
    import qbbulk
    import qbcore as core

    def user(fn):
        def run(p):
            try:
                return fn(p)
            except ValueError as e:
                raise core.UserError(str(e))
        return run

    @api.get("/api/farm")
    def farm_status(p):
        cat = qbbulk.catalog()
        taken = farmed_out(commons.folder)
        _, pub = server_keys(commons.folder)
        st = qbbulk.status_cached(commons.folder, commons)
        facts = {d["key"]: d.get("facts", 0) for d in st["datasets"]}
        return {"assignments": [public_view(a) for a in reversed(assignments(commons.folder))],
                "datasets": [{"key": k, "title": ds.title, "area": qbbulk.AREA[ds.app], "farmed_to": taken.get(k),
                              "facts_here": facts.get(k, 0), "helper": k == "wikidata-download"}
                             for k, ds in cat.items()],
                "server_key_id": hashlib.sha256(pub).hexdigest()[:16], "windows_python_inside": bool(_find_python_for_windows()),
                "this_server": {"name": socket.gethostname(), "addresses": sorted(local_addresses() - {"127.0.0.1"})},
                "drives": drives()}

    @api.post("/api/farm/assign")
    @user
    def farm_assign(p):
        keys = [k for k in (p.get("datasets") or []) if k != "wikidata-download"]
        a = assign(commons.folder, p.get("machine"), p.get("ip"), p.get("os"), keys, list(qbbulk.catalog()), p.get("note") or "")
        with commons.store.write() as db:
            commons.agent_log(db, "engine", "Farmed out to %s (%s): %s" % (a["machine"], a["ip"] or "any address", ", ".join(a["datasets"])))
        return {"assignment": public_view(a), "summary": "%d dataset(s) given to %s — download its harvester below" % (len(a["datasets"]), a["machine"])}

    @api.post("/api/farm/revoke")
    @user
    def farm_revoke(p):
        a = revoke(commons.folder, p.get("id"))
        with commons.store.write() as db:
            commons.agent_log(db, "engine", "Farm-out ended for %s: its datasets return to this server" % a["machine"])
        return {"assignment": public_view(a), "summary": "%s's datasets are back with this server" % a["machine"]}

    @api.get("/api/farm/package")
    @user
    def farm_package(p):
        path = package(commons.folder, p.get("id"), program_dir, os.path.join(farm_dir(commons.folder), "packages"))
        with open(path, "rb") as f:
            return f.read(), "application/zip"

    @api.post("/api/farm/import")
    @user
    def farm_import(p):
        r = import_folder(commons.folder, str(p.get("folder") or "").strip())
        qbbulk._STATUS.pop(commons.folder, None)
        with commons.store.write() as db:
            commons.agent_log(db, "engine", "Imported farmed-out harvest: %d file(s), %d facts, %d new" % (r["files"], r["facts"], r["new"]))
        return r


# ================================================================== harvesting PC
def local_addresses() -> set[str]:
    """this computer's IP addresses (no packet is sent: a UDP socket only picks the outgoing interface)"""
    ips = {"127.0.0.1"}
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    for target in ("192.0.2.1", "2001:db8::1"):
        try:
            fam = socket.AF_INET6 if ":" in target else socket.AF_INET
            with socket.socket(fam, socket.SOCK_DGRAM) as s:
                s.connect((target, 9))
                ips.add(s.getsockname()[0])
        except OSError:
            pass
    return ips


def identity_ok(cfg: dict, hostname: str | None = None, ips: set[str] | None = None) -> tuple[bool, str]:
    host = (hostname or socket.gethostname()).split(".")[0].lower()
    want = str(cfg.get("machine") or "").split(".")[0].lower()
    if want and host != want:
        return False, "This harvester was made for the computer '%s'; this computer is '%s'. Ask the QueryBook server for a copy made for this one." % (cfg["machine"], host)
    ips = ips if ips is not None else local_addresses()
    if cfg.get("ip") and cfg["ip"] not in ips:
        return False, "This harvester was made for IP address %s; this computer has %s. Ask for a copy with the right address." % (cfg["ip"], ", ".join(sorted(ips)))
    return True, "ok"


class Harvester:
    """the agent on the harvesting PC: the engine in a hidden folder, the sealer, the tally, the backup"""

    def __init__(self, root: str, cfg: dict):
        self.root, self.cfg = root, cfg
        self.work = os.path.join(root, ".harvest-work")
        self.commons = os.path.join(self.work, "commons")
        self.sealed = os.path.join(root, "sealed")
        os.makedirs(self.commons, exist_ok=True)
        os.makedirs(self.sealed, exist_ok=True)
        _hide(self.work)
        self.state_p = os.path.join(self.root, "tally.json")
        self.state = _load(self.state_p, {"tally": {}, "files": 0, "facts": 0, "sealed_bytes": 0, "by_dataset": {}})
        self.pub = base64.b64decode(cfg["server_public_key"])
        self.proc = None
        self.lock = threading.Lock()

    # --- the engine
    def start(self) -> None:
        import subprocess
        if self.proc and self.proc.poll() is None:
            return
        stop = os.path.join(self.commons, "shards", "_runner.stop")
        if os.path.exists(stop):
            os.remove(stop)
        here = os.path.dirname(os.path.abspath(__file__))
        kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
        keys = run_keys(self.cfg["datasets"])
        self.proc = subprocess.Popen([sys.executable, os.path.join(here, "qbbulk.py"), "run", "--commons", self.commons,
                                      "--datasets", ",".join(keys), "--agents", str(max(2, min(len(keys), os.cpu_count() or 2)))],
                                     cwd=here, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)

    def stop(self) -> None:
        os.makedirs(os.path.join(self.commons, "shards"), exist_ok=True)
        open(os.path.join(self.commons, "shards", "_runner.stop"), "w").close()

    def running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    # --- the sealer: filed facts -> sealed files, then gone from the working folder
    def seal_now(self) -> dict:
        made = 0
        with self.lock:
            for key in self.cfg["datasets"]:
                p = os.path.join(self.commons, "shards", key + ".sqlite")
                if not os.path.exists(p):
                    continue
                db = sqlite3.connect(p, timeout=60)
                try:
                    preds = dict(db.execute("SELECT id, name FROM predicates"))
                    parts = dict(db.execute("SELECT id, name FROM parts"))
                    while True:
                        rows = db.execute("SELECT fp, s, p, o, part, row FROM facts LIMIT ?", (CHUNK_FACTS,)).fetchall()
                        if not rows:
                            break
                        tally: dict[str, int] = {}
                        lines = []
                        for fp, s, pid, o, part, row in rows:
                            pn = preds.get(pid, str(pid))
                            tally[pn] = tally.get(pn, 0) + 1
                            lines.append(json.dumps([fp.hex(), s, pn, o, parts.get(part, str(part)), row], ensure_ascii=False))
                        payload = gzip.compress(("\n".join(lines) + "\n").encode("utf-8"), 6)
                        part_name = parts.get(rows[0][4], "") if rows else ""
                        hdr = {"format": "qbfarm/1", "assignment": self.cfg["assignment"], "machine": self.cfg["machine"],
                               "dataset": key, "part": part_name, "facts": len(rows), "tally": tally, "sealed": _now(),
                               "token_hash": hashlib.sha256(self.cfg["token"].encode()).hexdigest(),
                               "server_key_id": self.cfg.get("server_key_id")}
                        blob = qbseal.seal(self.pub, payload, hdr)
                        name = "%s-%s-%s.qbseal" % (key, time.strftime("%Y%m%d-%H%M%S"), hashlib.sha256(blob).hexdigest()[:10])
                        tmp = os.path.join(self.sealed, name + ".tmp")
                        with open(tmp, "wb") as f:
                            f.write(blob)
                            f.flush()
                            os.fsync(f.fileno())
                        os.replace(tmp, os.path.join(self.sealed, name))
                        db.executemany("DELETE FROM facts WHERE fp = ?", [(r[0],) for r in rows])   # only once sealed and on disk
                        db.commit()
                        made += 1
                        st = self.state
                        st["files"] += 1
                        st["facts"] += len(rows)
                        st["sealed_bytes"] += len(blob)
                        st["by_dataset"][key] = st["by_dataset"].get(key, 0) + len(rows)
                        for t, n in tally.items():
                            st["tally"][t] = st["tally"].get(t, 0) + n
                        st["last_sealed"] = _now()
                        _save(self.state_p, st)
                finally:
                    db.close()
        return {"sealed_files": made}

    def reading_now(self) -> int:
        """facts read but not yet filed or sealed (still in the working folder)"""
        n = 0
        for key in self.cfg["datasets"]:
            p = os.path.join(self.commons, "shards", key + ".sqlite")
            if os.path.exists(p):
                try:
                    db = sqlite3.connect("file:%s?mode=ro" % p, uri=True, timeout=5)
                    n += db.execute("SELECT (SELECT count(*) FROM stage) + (SELECT count(*) FROM facts)").fetchone()[0]
                    db.close()
                except sqlite3.Error:
                    pass
        return n

    # --- backup to an external drive
    def backup(self, dest_root: str) -> dict:
        self.seal_now()
        if not os.path.isdir(dest_root):
            raise ValueError("That drive or folder is not available: %s" % dest_root)
        dest = os.path.join(dest_root, "QueryBook-Harvest", self.cfg["machine"])
        os.makedirs(dest, exist_ok=True)
        copied = skipped = 0
        for f in sorted(os.listdir(self.sealed)):
            if not f.endswith(".qbseal"):
                continue
            src, dst = os.path.join(self.sealed, f), os.path.join(dest, f)
            if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
                skipped += 1
                continue
            shutil.copyfile(src, dst + ".part")
            with open(src, "rb") as a, open(dst + ".part", "rb") as b:
                if hashlib.sha256(a.read()).digest() != hashlib.sha256(b.read()).digest():
                    os.remove(dst + ".part")
                    raise ValueError("The copy of %s did not match — try another drive." % f)
            os.replace(dst + ".part", dst)
            copied += 1
        _save(os.path.join(dest, "tally.json"), dict(self.state, machine=self.cfg["machine"], assignment=self.cfg["assignment"], backed_up=_now()))
        return {"copied": copied, "already_there": skipped, "to": dest}


def run_keys(datasets: list[str]) -> list[str]:
    """what the harvester's bulk engine runs: its datasets, plus the one Wikidata dump download when it has Wikidata
    lanes (a lane reads the downloaded dump; the download itself adds no facts, so it is not farmed-out work)"""
    keys = list(datasets)
    if any(k.startswith("wikidata-dump-") for k in keys) and "wikidata-download" not in keys:
        keys.insert(0, "wikidata-download")
    return keys


def _hide(path: str) -> None:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(path, 0x02)     # FILE_ATTRIBUTE_HIDDEN
        except Exception:
            pass


def drives() -> list[dict]:
    """external drives to back up to: Windows drive letters (not C:), Mac /Volumes, Linux /media and /mnt"""
    out = []
    if os.name == "nt":
        import string
        sysdrive = (os.environ.get("SystemDrive") or "C:").upper()
        for L in string.ascii_uppercase:
            p = L + ":\\"
            if p[:2].upper() != sysdrive and os.path.exists(p):
                out.append(p)
    else:
        for base in ("/Volumes", "/media", "/mnt", "/run/media"):
            if os.path.isdir(base):
                for d in sorted(os.listdir(base)):
                    p = os.path.join(base, d)
                    if os.path.isdir(p) and not os.path.islink(p) and d not in ("Macintosh HD",):
                        out.append(p)
    res = []
    for p in out:
        try:
            u = shutil.disk_usage(p)
            res.append({"path": p, "free_gb": round(u.free / 1e9, 1), "total_gb": round(u.total / 1e9, 1)})
        except OSError:
            pass
    return res


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>QueryBook Harvester</title><style>
:root{--bg:#f6f7f9;--panel:#fff;--ink:#1d2330;--muted:#5b6475;--line:#dde1e8;--accent:#2f5fb3;--good:#1f7a4a;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--panel:#1d2128;--ink:#e6e9ef;--muted:#9aa3b2;--line:#2e3440;--accent:#7aa7ff;--good:#5ccf8f;--bad:#ff8a80}}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:900px;margin:0 auto;padding:16px}.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:14px}
h1{font-size:22px;margin:4px 0 12px}h2{font-size:17px;margin:0 0 8px}.muted{color:var(--muted)}.big{font-size:28px;font-weight:700}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}button{font:inherit;padding:8px 14px;border-radius:8px;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer}
button.s{background:transparent;color:var(--accent)}table{border-collapse:collapse;width:100%}td,th{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left}td.n{text-align:right;font-variant-numeric:tabular-nums}
.ok{color:var(--good)}.bad{color:var(--bad)}select,input{font:inherit;padding:6px 8px;border-radius:8px;border:1px solid var(--line);background:var(--panel);color:var(--ink)}
</style></head><body><main>
<h1>QueryBook Harvester — <span id="m"></span></h1>
<div class="card"><div class="row"><div><div class="muted">Records gathered</div><div class="big" id="total">—</div></div>
<div><div class="muted">Sealed files</div><div class="big" id="files">—</div></div><div><div class="muted">Harvesting</div><div class="big" id="state">—</div></div></div>
<p class="muted" id="sub"></p><div class="row"><button id="go">Start</button><button class="s" id="halt">Pause</button></div></div>
<div class="card"><h2>Records by type</h2><p class="muted">The records are sealed: only the QueryBook server can open them. This is the tally.</p><table id="t"></table></div>
<div class="card"><h2>Back up to an external drive</h2><p class="muted">Copies the sealed files and the tally to &lt;drive&gt;/QueryBook-Harvest/<span class="mm"></span>/ — take the drive to the QueryBook server.</p>
<div class="row"><select id="drv"></select><input id="other" placeholder="or another folder" size="28"><button id="bk">Back up to drive</button></div><p id="bkout"></p></div>
</main><script>
const $=s=>document.querySelector(s),f=n=>Number(n||0).toLocaleString();
async function api(p,b){const r=await fetch(p,b?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)}:{});const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);return j}
async function load(){const s=await api("/api/status");$("#m").textContent=s.machine;document.querySelectorAll(".mm").forEach(e=>e.textContent=s.machine);
$("#total").textContent=f(s.tally_total);$("#files").textContent=f(s.files);$("#state").innerHTML=s.running?'<span class="ok">running</span>':'<span class="bad">paused</span>';
$("#sub").textContent="Datasets: "+s.datasets.join(", ")+" · "+f(s.reading)+" being read (sealed within minutes) · last sealed: "+(s.last_sealed||"—");
$("#t").innerHTML="<tr><th>Record type</th><th>Records</th></tr>"+Object.entries(s.tally).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<tr><td>${k.replace(/[<&]/g,"")}</td><td class="n">${f(v)}</td></tr>`).join("")||"<tr><td class=muted>Nothing gathered yet.</td></tr>";
const cur=$("#drv").value;$("#drv").innerHTML=s.drives.length?s.drives.map(d=>`<option value="${d.path}">${d.path} — ${d.free_gb} GB free</option>`).join(""):"<option value=''>No external drive found — plug one in</option>";if(cur)$("#drv").value=cur}
$("#go").onclick=async()=>{await api("/api/start",{});load()};$("#halt").onclick=async()=>{await api("/api/stop",{});load()};
$("#bk").onclick=async()=>{$("#bkout").textContent="Copying…";try{const r=await api("/api/backup",{to:$("#other").value||$("#drv").value});$("#bkout").innerHTML='<span class="ok">✔ '+r.copied+" file(s) copied, "+r.already_there+" already there — "+r.to+"</span>"}catch(e){$("#bkout").innerHTML='<span class="bad">'+e.message+"</span>"}};
load();setInterval(load,5000);
</script></body></html>"""


def agent_main(argv: list[str]) -> int:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    cfg_p = argv[argv.index("--config") + 1] if "--config" in argv else os.path.join(root, "farm-config.json")
    cfg = _load(cfg_p, None)
    if not cfg or cfg.get("format") != "qbfarm/1":
        print("farm-config.json is missing or damaged — ask the QueryBook server for a new copy.")
        return 1
    ok, why = identity_ok(cfg)
    if not ok:
        print(why)
        return 1
    h = Harvester(root, cfg)
    h.start()

    def sealer():
        while True:
            time.sleep(SEAL_EVERY_S)
            try:
                h.seal_now()
            except Exception as e:                           # never stop harvesting over one sealing round
                print("sealing will be tried again:", e)
    threading.Thread(target=sealer, daemon=True).start()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body, ctype: str = "application/json") -> None:
            b = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path == "/":
                return self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            if self.path == "/api/status":
                st = h.state
                return self._send(200, {"machine": cfg["machine"], "datasets": cfg["datasets"], "running": h.running(),
                                        "tally": st["tally"], "tally_total": sum(st["tally"].values()), "files": st["files"],
                                        "last_sealed": st.get("last_sealed"), "reading": h.reading_now(), "drives": drives()})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            try:
                if self.path == "/api/start":
                    h.start()
                    return self._send(200, {"ok": True})
                if self.path == "/api/stop":
                    h.stop()
                    return self._send(200, {"ok": True})
                if self.path == "/api/backup":
                    return self._send(200, h.backup(str(body.get("to") or "")))
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            self._send(404, {"error": "not found"})
    port = AGENT_PORT
    for port in range(AGENT_PORT, AGENT_PORT + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), H)
            break
        except OSError:
            continue
    url = "http://127.0.0.1:%d/" % port
    print("QueryBook Harvester for %s is running at %s" % (cfg["machine"], url))
    print("Keep this window open while it harvests. Close it to stop.")
    if "--no-browser" not in argv:
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        h.stop()
        h.seal_now()
    return 0


# ================================================================== self-test
def self_test() -> list[tuple[str, bool]]:
    import tempfile
    out: list[tuple[str, bool]] = []
    ok = lambda n, c: out.append((n, bool(c)))
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        cf = os.path.join(tmp, "commons")
        os.makedirs(cf)
        cat = ["calendar-scaffold", "mit-ocw", "wikidata-dump-7"]
        a = assign(cf, "LAB-PC-2", "192.168.1.42", "windows", ["calendar-scaffold", "wikidata-dump-7"], cat, "night shift")
        ok("an assignment gives datasets to one machine; the main harvester is told to leave them alone",
           farmed_out(cf) == {"calendar-scaffold": "LAB-PC-2", "wikidata-dump-7": "LAB-PC-2"})
        try:
            assign(cf, "OTHER", "", "mac", ["wikidata-dump-7"], cat)
            twice = True
        except ValueError as e:
            twice = "LAB-PC-2" not in str(e)
        ok("a dataset already given to a machine cannot be given to another (no work done twice)", not twice)
        bad = []
        for args in (("bad name!", "", "mac", ["mit-ocw"]), ("PC", "300.1.1.1", "mac", ["mit-ocw"]), ("PC", "", "ios", ["mit-ocw"]), ("PC", "", "mac", ["nope"])):
            try:
                assign(cf, *args, cat)
                bad.append(False)
            except ValueError:
                bad.append(True)
        ok("refused: a bad machine name, a bad IP address, an OS other than Windows or Mac, an unknown dataset", all(bad))
        ok("the machine's identity is checked: right name and IP pass; another computer or address is refused",
           identity_ok({"machine": "LAB-PC-2", "ip": "192.168.1.42"}, "lab-pc-2", {"192.168.1.42"})[0]
           and not identity_ok({"machine": "LAB-PC-2", "ip": "192.168.1.42"}, "HOME", {"192.168.1.42"})[0]
           and not identity_ok({"machine": "LAB-PC-2", "ip": "192.168.1.42"}, "LAB-PC-2", {"10.0.0.5"})[0])
        # a package, then a harvester on "the other PC": it seals, backs up to a "drive", the server imports
        prog = os.path.dirname(os.path.abspath(__file__))
        z = package(cf, a["id"], prog, os.path.join(tmp, "out"))
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
            cfgz = json.loads(zf.read([n for n in names if n.endswith("farm-config.json")][0]))
        priv, pub = server_keys(cf)
        ok("the package carries the engine, the start file and its config with the server's PUBLIC key only",
           any(n.endswith("harvester/qbbulk.py") for n in names) and any(n.endswith("START-Harvester.bat") for n in names)
           and cfgz["server_public_key"] == base64.b64encode(pub).decode() and base64.b64encode(priv).decode() not in json.dumps(cfgz)
           and not any(n.endswith("/app.py") for n in names))
        root = os.path.join(tmp, "harvest-pc")
        os.makedirs(root)
        h = Harvester(root, cfgz)
        sp = os.path.join(h.commons, "shards")
        os.makedirs(sp, exist_ok=True)
        db = sqlite3.connect(os.path.join(sp, "calendar-scaffold.sqlite"))
        db.executescript("CREATE TABLE facts (fp BLOB PRIMARY KEY, s TEXT, p INTEGER, o TEXT, part INTEGER, row INTEGER);"
                         "CREATE TABLE predicates (id INTEGER PRIMARY KEY, name TEXT); CREATE TABLE parts (id INTEGER PRIMARY KEY, name TEXT);"
                         "CREATE TABLE stage (fp BLOB);")
        db.executemany("INSERT INTO predicates VALUES (?, ?)", [(1, "weekday"), (2, "holiday")])
        db.execute("INSERT INTO parts VALUES (1, 'years')")
        facts = [(hashlib.sha256(b"f%d" % i).digest()[:16], "1776-07-%02d" % (i % 28 + 1), 1 + i % 2, "Thursday" if i % 2 == 0 else "Independence Day", 1, i) for i in range(500)]
        db.executemany("INSERT INTO facts VALUES (?,?,?,?,?,?)", facts)
        db.commit()
        db.close()
        r = h.seal_now()
        left = sqlite3.connect(os.path.join(sp, "calendar-scaffold.sqlite")).execute("SELECT count(*) FROM facts").fetchone()[0]
        sealed_files = [f for f in os.listdir(h.sealed) if f.endswith(".qbseal")]
        raw = open(os.path.join(h.sealed, sealed_files[0]), "rb").read() if sealed_files else b""
        ok("the harvester seals what it filed and removes it from its working folder; it keeps only a tally of record types",
           r["sealed_files"] == 1 and left == 0 and h.state["tally"] == {"weekday": 250, "holiday": 250} and h.state["facts"] == 500)
        ok("the sealed file cannot be read on the harvesting PC (no fact text in it; the harvester holds no key to open it)",
           b"Independence Day" not in raw and b"Thursday" not in raw and "server_public_key" in cfgz and "private" not in json.dumps(cfgz))
        drive = os.path.join(tmp, "PocketDrive")
        os.makedirs(drive)
        b1 = h.backup(drive)
        b2 = h.backup(drive)
        ok("back up to an external drive: sealed files and the tally copied and checked; a second backup copies nothing again",
           b1["copied"] == 1 and b2["copied"] == 0 and b2["already_there"] == 1
           and os.path.exists(os.path.join(drive, "QueryBook-Harvest", "LAB-PC-2", "tally.json")))

        class FakeShard:                                    # the server's dataset (qbbulk.Shard's interface)
            store: dict = {}

            def __init__(self):
                self.db = type("D", (), {"close": lambda s: None})()
                self.parts, self.preds, self.stage = {}, {}, []

            def part(self, name, url):
                return (self.parts.setdefault(name, len(self.parts) + 1), 0, 0, 0)

            def pred(self, name):
                return self.preds.setdefault(name, len(self.preds) + 1)

            def write(self, pid, rows, done):
                self.stage += rows

            def merge(self):
                new = sum(1 for r in self.stage if FakeShard.store.setdefault(r[0], r) is r)
                self.stage = []
                return new
        imp = import_folder(cf, os.path.join(drive, "QueryBook-Harvest"), open_shard=lambda k: FakeShard())
        imp2 = import_folder(cf, os.path.join(drive, "QueryBook-Harvest"), open_shard=lambda k: FakeShard())
        ok("the server opens and imports them: every fact back, by type; importing the same drive again adds nothing",
           imp["files"] == 1 and imp["new"] == 500 and imp["tally"] == {"weekday": 250, "holiday": 250}
           and imp2["files"] == 0 and imp2["skipped_before"] == 1
           and next(x for x in assignments(cf) if x["id"] == a["id"])["imported"]["new"] == 500)
        forged = qbseal.seal(pub, gzip.compress(b'["00","x","weekday","y","p",1]\n'), {"assignment": a["id"], "token_hash": "0" * 64, "dataset": "calendar-scaffold", "tally": {}})
        with open(os.path.join(drive, "QueryBook-Harvest", "forged.qbseal"), "wb") as f:
            f.write(forged)
        imp3 = import_folder(cf, os.path.join(drive, "QueryBook-Harvest"), open_shard=lambda k: FakeShard())
        ok("a file not made by that assignment's harvester is refused on import", imp3["files"] == 0 and len(imp3["refused"]) == 1)
        revoke(cf, a["id"])
        ok("revoking an assignment gives its datasets back to the main harvester", farmed_out(cf) == {})
        ok("drives() lists external drives without failing", isinstance(drives(), list))
        ok("bulk harvesting on the harvester: Wikidata lanes bring the one dump download with them (it adds no facts)",
           run_keys(["wikidata-dump-7", "mit-ocw"]) == ["wikidata-download", "wikidata-dump-7", "mit-ocw"] and run_keys(["mit-ocw"]) == ["mit-ocw"])
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "agent":
        raise SystemExit(agent_main(sys.argv[2:]))
    res = self_test()
    for name, ok_ in res:
        print(("  [OK]   " if ok_ else "  [FAIL] ") + name)
    print("%d of %d checks passed" % (sum(o for _, o in res), len(res)))
    raise SystemExit(0 if all(o for _, o in res) else 1)
