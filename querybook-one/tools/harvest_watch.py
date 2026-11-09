#!/usr/bin/env python3
"""Watch QueryBook's harvesting and say plainly whether it keeps going, and if not, why it stopped.

    python tools/harvest_watch.py [--start] [--minutes 6] [--every 20] [--panel http://127.0.0.1:8100] [--data D:\\QB]

--start   presses Start harvesting first (the Control Panel's own Start: /api/panel/harvest)
Every sample: the runner's heartbeat age, its note, how many agents run, facts so far, and each agent that ended
(with its reason). At the end: a verdict, the last trace lines of the runner, and exit code 1 if harvesting died.
Standard library only; works on Windows, macOS and Linux.
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time
import urllib.request


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def post(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def arg(name: str, default: str) -> str:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main() -> int:
    try:                                            # the screen's text has ⚡ and accents; a Windows console may not
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    panel = arg("--panel", "http://127.0.0.1:8100").rstrip("/")
    minutes, every = float(arg("--minutes", "6")), float(arg("--every", "20"))
    data = arg("--data", "")
    if "--start" in sys.argv:
        r = post(panel + "/api/panel/harvest", {"action": "start"})
        print("Start pressed:", r.get("summary"))
    t0, seen, last, facts0 = time.time(), set(), {}, None
    alive_samples, agent_samples = 0, 0
    top, top_at, falls, longest_still, filed0, filed_last = None, time.time(), [], 0.0, None, None
    max_still = float(arg("--max-still", "10")) * 60
    while time.time() - t0 < minutes * 60:
        try:
            b = get(panel + "/api/bulk")
        except Exception as e:                      # the Control Panel itself not answering is a finding too
            print("%5.0fs  Control Panel not answering: %r" % (time.time() - t0, e))
            time.sleep(every)
            continue
        rs = b.get("runner") or {}
        age = time.time() - float(rs.get("heartbeat") or 0) if rs.get("heartbeat") else None
        running = rs.get("running") or []
        facts = b.get("total_gathered", b.get("total"))            # gathered = filed + new staged (what the screen counts)
        facts0 = facts if facts0 is None else facts0
        filed0 = b.get("total") if filed0 is None else filed0
        filed_last = b.get("total")
        if facts is not None:                       # care of records: the count must never fall; stalls: how long it stood still
            if top is not None and facts < top:
                falls.append((round(time.time() - t0), top, facts))
                print("         !! THE TOTAL FELL: %s -> %s" % (top, facts))
            if top is None or facts > top:
                top, top_at = facts, time.time()
            longest_still = max(longest_still, time.time() - top_at)
        for x in b.get("drops") or []:
            k_ = ("drop", x.get("at"), x.get("dataset"))
            if k_ not in seen:
                seen.add(k_)
                print("         count went down: %s %s -> %s: %s" % (x.get("dataset"), x.get("from"), x.get("to"), x.get("cause")))
        alive = age is not None and age < 60
        alive_samples += alive
        agent_samples += bool(running)
        print("%5.0fs  runner %s (beat %s s ago, pid %s)  agents running: %d  facts: %s  note: %s" % (
            time.time() - t0, "ALIVE" if alive else "NOT BEATING", "—" if age is None else "%.0f" % age, rs.get("pid"),
            len(running), facts, str(rs.get("note") or "")[:90]))
        hl = b.get("headline") or {}
        print("         screen: %s  [facts/min %s, last minute %s]" % (hl.get("text"), b.get("facts_per_min"), b.get("last_minute")))
        for d in b.get("datasets") or []:
            if d.get("key") in running or d.get("staged") or d.get("last_10min"):
                pg = d.get("progress") or {}
                print("         %-20s %-9s filed %-10s staged %-10s new~ %-10s +10min %-9s part %s %s%% %s %s" % (
                    d["key"], d.get("state"), d.get("facts"), d.get("staged"), d.get("staged_new"), d.get("last_10min"), str(pg.get("part") or "")[-18:],
                    "—" if pg.get("fraction") is None else round(100 * pg["fraction"], 1),
                    "" if not pg.get("rate") else "%.1f %s/s" % (pg["rate"] / (1e6 if pg.get("unit") == "bytes" else 1), "MB" if pg.get("unit") == "bytes" else pg.get("unit") or ""),
                    ("[" + d["doing"] + "]") if d.get("doing") else ""))
        for e in rs.get("events") or []:
            k = (e.get("at"), e.get("dataset"), e.get("what"))
            if k in seen:
                continue
            seen.add(k)
            if e.get("what") == "ended":
                print("         ended %-22s %-8s ran %ss, next try in %ss: %s" % (e.get("dataset"), e.get("state"), e.get("ran_s"),
                                                                              e.get("next_in_s"), str(e.get("why"))[:140]))
            elif e.get("what") not in ("started",):
                print("         %s %s %s" % (e.get("what"), e.get("dataset"), {k_: v for k_, v in e.items() if k_ not in ("what", "dataset", "at")}))
        last = {"alive": alive, "running": running, "facts": facts, "note": rs.get("note")}
        time.sleep(every)
    print()
    if data:                                        # the runner's own trace: the last things it did
        for f in sorted(glob.glob(os.path.join(data, "**", "runner-*.jsonl"), recursive=True))[-2:]:
            print("--- trace", f)
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    for line in fh.readlines()[-25:]:
                        print("   ", line.rstrip()[:300])
            except OSError:
                pass
    grew = (last.get("facts") or 0) > (facts0 or 0)
    still_ok = longest_still <= max_still
    ok = bool(last.get("alive")) and grew and not falls and still_ok
    print("Longest stretch with no new facts: %.1f min (limit %.0f) · times the total fell: %d · filed %s -> %s" % (
        longest_still / 60, max_still / 60, len(falls), filed0, filed_last))
    print("VERDICT: harvesting %s after %.0f min — runner beating in %d samples, agents running in %d; facts gathered %s -> %s" % (
        "is still RUNNING and gathering" if ok else "has STOPPED" if not last.get("alive") else "is running but GATHERED NOTHING" if not grew
        else "LOST COUNT (the total fell)" if falls else "STALLED for %.0f min" % (longest_still / 60),
        minutes, alive_samples, agent_samples, facts0, last.get("facts")))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
