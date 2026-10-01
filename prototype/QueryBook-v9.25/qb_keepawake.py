#!/usr/bin/env python3
"""
qb_keepawake.py — keep the computer awake while QueryBook works, AND prove what
the machine actually did (real sleep vs. just a black screen).

Two jobs:

1) KEEP AWAKE (self-defense). While harvesting or an agent is running, tell the
   OS "do not sleep." Released when all work stops so the machine can sleep
   normally when idle. Reference-counted, thread-safe, best-effort (degrades to
   a no-op if the platform hook is missing). The Windows assertion is
   RE-ASSERTED on every heartbeat, so it can't quietly lapse.

2) WATCHDOG / DIAGNOSIS. A heartbeat thread writes a timestamped line to
   <store>/keepawake.log every few seconds. If the process was frozen (the PC
   really slept or hibernated), the wall clock jumps and we detect the GAP:
       *** SLEEP DETECTED: process frozen for 5423s (90.4 min) ***
   If the screen went black with NO gap, the program kept running fine — the
   display just turned off, which is harmless. This is how you tell the two
   apart instead of guessing.

Usage:
    import qb_keepawake
    qb_keepawake.start_monitor("/path/to/store")   # once, at startup
    qb_keepawake.acquire("harvest"); ... ; qb_keepawake.release("harvest")
    qb_keepawake.status()   # dict for the dashboard / /api/health

No third-party dependencies.

Windows : SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED [| ES_AWAYMODE] [| ES_DISPLAY])
macOS   : `caffeinate` subprocess (-i -m -s [-d]), killed on release
Linux   : `systemd-inhibit` subprocess if present, else no-op
"""
import os
import sys
import time
import threading

_lock = threading.Lock()
_holders = set()
_state = {
    "engaged": False, "how": None, "proc": None,
    "display": False,          # also keep the SCREEN on (visible proof it's alive)
    "monitor": False,          # heartbeat thread running?
    "log": None,
    "last_beat": 0.0,          # wall-clock of the last heartbeat
    "started": 0.0,
    "beats": 0,
    "sleep_events": [],        # [{start, end, seconds}] most-recent last (capped)
}

# ---- Windows constants ----
_ES_CONTINUOUS        = 0x80000000
_ES_SYSTEM_REQUIRED   = 0x00000001
_ES_DISPLAY_REQUIRED  = 0x00000002
_ES_AWAYMODE_REQUIRED = 0x00000040

_HEARTBEAT_SEC = 15          # how often we prove we're alive
_SLEEP_SLACK   = 30          # a gap beyond interval+slack means we were frozen


# ---------------- OS keep-awake ----------------
def _win_flags():
    f = _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_AWAYMODE_REQUIRED
    if _state["display"]:
        f |= _ES_DISPLAY_REQUIRED
    return f


def _engage():
    """Turn keep-awake ON. Returns a short 'how' label, or None."""
    plat = sys.platform
    if plat.startswith("win"):
        try:
            import ctypes
            r = ctypes.windll.kernel32.SetThreadExecutionState(_win_flags())
            if r == 0:  # AWAYMODE not permitted here; retry without it
                base = _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED
                if _state["display"]:
                    base |= _ES_DISPLAY_REQUIRED
                r = ctypes.windll.kernel32.SetThreadExecutionState(base)
            return "windows:SetThreadExecutionState" if r != 0 else None
        except Exception:
            return None
    if plat == "darwin":
        try:
            import subprocess
            args = ["caffeinate", "-i", "-m", "-s"] + (["-d"] if _state["display"] else [])
            _state["proc"] = subprocess.Popen(args)
            return "macos:caffeinate"
        except Exception:
            return None
    try:
        import shutil, subprocess
        if shutil.which("systemd-inhibit"):
            what = "sleep:idle" if not _state["display"] else "sleep:idle:handle-lid-switch"
            _state["proc"] = subprocess.Popen([
                "systemd-inhibit", "--what=" + what, "--who=QueryBook",
                "--why=Harvesting facts", "--mode=block", "sleep", "infinity"])
            return "linux:systemd-inhibit"
    except Exception:
        return None
    return None


def _reassert():
    """Re-apply the Windows assertion (per-thread state can lapse otherwise)."""
    if sys.platform.startswith("win") and _state["engaged"]:
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(_win_flags())
        except Exception:
            pass


def _disengage():
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
        except Exception:
            pass
        return
    p = _state.get("proc")
    if p is not None:
        try:
            p.terminate()
        except Exception:
            pass
        _state["proc"] = None


# ---------------- public API ----------------
def acquire(name="job"):
    with _lock:
        _holders.add(name)
        if not _state["engaged"]:
            _state["how"] = _engage()
            _state["engaged"] = True
            _log("KEEP-AWAKE ON via %s (holder: %s)" % (_state["how"], name))
        return _state["how"]


def release(name="job"):
    with _lock:
        _holders.discard(name)
        if not _holders and _state["engaged"]:
            _disengage()
            _state["engaged"] = False
            _log("KEEP-AWAKE OFF (idle; PC may sleep now)")


_MODE_HOLDER = "mode:24x7"


def _mode_file():
    log = _state.get("log")
    return os.path.join(os.path.dirname(log), "keepawake_mode.json") if log else None


def _save_mode():
    path = _mode_file()
    if not path:
        return
    try:
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"always_on": is_always_on(), "display": _state["display"]}, f)
    except Exception:
        pass


def enable_always_on():
    """Master 24x7 switch ON: hold the machine awake in ALL modes — harvesting,
    paused, or idle — until explicitly turned off. Persists across restarts."""
    acquire(_MODE_HOLDER)
    _log("24x7 MODE ENABLED — machine stays awake until turned off")
    _save_mode()
    return status()


def disable_always_on():
    """Master 24x7 switch OFF: revert to automatic (awake only while working)."""
    release(_MODE_HOLDER)
    _log("24x7 MODE DISABLED — automatic keep-awake only while working")
    _save_mode()
    return status()


def is_always_on():
    with _lock:
        return _MODE_HOLDER in _holders


def set_display(on):
    """Also keep the screen on (visible proof). Re-engages if already active."""
    with _lock:
        _state["display"] = bool(on)
        if _state["engaged"]:
            _disengage(); _state["how"] = _engage()
        _log("display-stay-on set to %s" % _state["display"])
    _save_mode()


def status():
    with _lock:
        now = time.time()
        return {
            "engaged": _state["engaged"], "how": _state["how"],
            "display_on": _state["display"], "monitor": _state["monitor"],
            "holders": sorted(_holders), "beats": _state["beats"],
            "last_beat_age_sec": round(now - _state["last_beat"], 1) if _state["last_beat"] else None,
            "uptime_sec": round(now - _state["started"], 1) if _state["started"] else None,
            "sleep_events": list(_state["sleep_events"]),
            "sleep_count": len(_state["sleep_events"]),
            "log": _state["log"],
        }


# ---------------- watchdog / heartbeat ----------------
def _log(msg):
    path = _state.get("log")
    if not path:
        return
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        with open(path, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (ts, msg))
    except Exception:
        pass


def _monitor_loop():
    _state["started"] = _state["last_beat"] = time.time()
    _log("WATCHDOG START (heartbeat every %ss)" % _HEARTBEAT_SEC)
    while _state["monitor"]:
        # sleep in 1s steps so shutdown is responsive
        for _ in range(_HEARTBEAT_SEC):
            if not _state["monitor"]:
                break
            time.sleep(1)
        now = time.time()
        gap = now - _state["last_beat"]
        _state["last_beat"] = now
        _state["beats"] += 1
        # If far more wall-clock passed than we slept for, the process was FROZEN
        # (real sleep / hibernate / suspend) for that whole gap.
        if gap > _HEARTBEAT_SEC + _SLEEP_SLACK:
            ev = {"start": now - gap, "end": now, "seconds": round(gap, 1)}
            _state["sleep_events"].append(ev)
            _state["sleep_events"] = _state["sleep_events"][-50:]
            _log("*** SLEEP DETECTED: process frozen for %.0fs (%.1f min) — "
                 "the PC slept/hibernated. Set Sleep=Never (see fix #1)."
                 % (gap, gap / 60.0))
        else:
            _reassert()  # keep the Windows assertion fresh; also a normal heartbeat
            hold = "+".join(sorted(_holders)) or "idle"
            _log("alive (holders: %s, keep-awake: %s)"
                 % (hold, "ON" if _state["engaged"] else "off"))


def start_monitor(store_dir, heartbeat_sec=15, display=False):
    """Start the heartbeat/sleep-detection thread. Safe to call once at startup."""
    global _HEARTBEAT_SEC
    with _lock:
        if _state["monitor"]:
            return
        _HEARTBEAT_SEC = max(5, int(heartbeat_sec))
        _state["display"] = bool(display)
        try:
            os.makedirs(store_dir, exist_ok=True)
        except Exception:
            pass
        _state["log"] = os.path.join(store_dir, "keepawake.log")
        _state["monitor"] = True
    # Restore a persisted 24x7 master switch so it survives restarts.
    try:
        import json
        mf = _mode_file()
        if mf and os.path.exists(mf):
            with open(mf, encoding="utf-8") as f:
                saved = json.load(f)
            if saved.get("display"):
                _state["display"] = True
            if saved.get("always_on"):
                acquire(_MODE_HOLDER)
                _log("restored 24x7 MODE from previous session")
    except Exception:
        pass
    t = threading.Thread(target=_monitor_loop, daemon=True)
    t.start()
    return _state["log"]


def stop_monitor():
    _state["monitor"] = False


if __name__ == "__main__":
    # Manual check: run the watchdog + hold awake for ~40s, print status, and
    # tail the log. On Windows this exercises the real SetThreadExecutionState path.
    import tempfile, json
    d = tempfile.mkdtemp(prefix="qb_ka_")
    log = start_monitor(d, heartbeat_sec=5)
    print("watchdog log:", log)
    print("engage:", acquire("selftest"))
    time.sleep(12)
    release("selftest")
    time.sleep(2)
    print("status:", json.dumps(status(), indent=2))
    stop_monitor()
    print("\n--- log ---")
    print(open(log).read())
