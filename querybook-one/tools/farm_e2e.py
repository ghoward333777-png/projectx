#!/usr/bin/env python3
"""Farm-out end to end, through the real pages' API: give a dataset to THIS computer, download its harvester, run it,
wait until it has sealed facts, back them up to a "drive" folder, import them on the server, and check every count.

    python tools/farm_e2e.py --panel http://127.0.0.1:8100 --work <empty folder> [--dataset calendar-scaffold] [--os windows]
Exit 0 only if: the harvester ran here, sealed facts it never shows, the backup copied them, and the server imported all
of them as new, and refused nothing. Standard library only.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile


def arg(name: str, default: str) -> str:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def call(url: str, body: dict | None = None, raw: bool = False):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    return data if raw else json.loads(data.decode("utf-8"))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    panel = arg("--panel", "http://127.0.0.1:8100").rstrip("/")
    work = os.path.abspath(arg("--work", "farm-e2e"))
    dataset = arg("--dataset", "calendar-scaffold")
    os_name = arg("--os", "windows" if os.name == "nt" else "mac")
    os.makedirs(work, exist_ok=True)
    host = socket.gethostname()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))
        ip = s.getsockname()[0]
    a = call(panel + "/api/farm/assign", {"machine": host, "ip": ip, "os": os_name, "datasets": [dataset], "note": "end-to-end test"})
    aid = a["assignment"]["id"]
    print("1. assigned:", a["summary"], "(%s, %s)" % (host, ip))
    z = os.path.join(work, "harvester.zip")
    with open(z, "wb") as f:
        f.write(call(panel + "/api/farm/package?id=" + aid, raw=True))
    with zipfile.ZipFile(z) as zf:
        zf.extractall(os.path.join(work, "pc"))
    root = os.path.join(work, "pc", os.listdir(os.path.join(work, "pc"))[0])
    names = sorted(os.listdir(root))
    print("2. harvester unzipped:", names, "| python inside:", os.path.isdir(os.path.join(root, "python")))
    if os_name == "windows":
        cmd = ["cmd", "/c", os.path.join(root, "START-Harvester.bat"), "--no-browser"]
    else:
        cmd = ["bash", os.path.join(root, "START-Harvester.command"), "--no-browser"]
    env = dict(os.environ)
    if os_name == "windows":
        env["PATH"] = r"C:\Windows\System32;C:\Windows"          # only the Python inside the harvester
    log = open(os.path.join(work, "harvester.log"), "w")
    proc = subprocess.Popen(cmd, cwd=root, stdout=log, stderr=subprocess.STDOUT, env=env)
    st, t0 = None, time.time()
    try:
        while time.time() - t0 < 600:
            time.sleep(15)
            try:
                st = call("http://127.0.0.1:8099/api/status")
            except Exception as e:
                print("   harvester page not answering yet:", e)
                if proc.poll() is not None:
                    break
                continue
            print("   %4.0fs running=%s records=%s sealed files=%s reading=%s" % (time.time() - t0, st["running"], st["tally_total"], st["files"], st["reading"]))
            if st["files"] and not st["running"] and st["reading"] == 0:
                break
            if st["files"] and st["reading"] == 0 and time.time() - t0 > 150:
                break
        if not st or not st["files"]:
            log.close()
            print(open(os.path.join(work, "harvester.log"), encoding="utf-8", errors="replace").read()[-3000:])
            print("FAILED: the harvester sealed nothing")
            return 1
        print("3. the harvester shows only the tally:", st["tally_total"], "records,", len(st["tally"]), "record types")
        drive = os.path.join(work, "PocketDrive")
        os.makedirs(drive, exist_ok=True)
        b = call("http://127.0.0.1:8099/api/backup", {"to": drive})
        print("4. backed up:", b)
    finally:
        try:
            call("http://127.0.0.1:8099/api/stop", {})
        except Exception:
            pass
        proc.terminate()
    sealed = os.path.join(root, "sealed")
    leaked = any(b"Easter" in open(os.path.join(sealed, f), "rb").read().split(b"}\n", 1)[-1] for f in os.listdir(sealed) if f.endswith(".qbseal"))
    imp = call(panel + "/api/farm/import", {"folder": os.path.join(drive, "QueryBook-Harvest")})
    print("5. imported on the server:", {k: imp[k] for k in ("files", "facts", "new", "duplicates", "refused")})
    again = call(panel + "/api/farm/import", {"folder": os.path.join(drive, "QueryBook-Harvest")})
    ok = (imp["files"] == b["copied"] and imp["new"] == st["tally_total"] == imp["facts"] and not imp["refused"]
          and again["new"] == 0 and again["skipped_before"] == imp["files"] and not leaked)
    print("VERDICT:", "farm-out works end to end" if ok else "FAILED", "| fact text visible in a sealed file:", leaked)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
