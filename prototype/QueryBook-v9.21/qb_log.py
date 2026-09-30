#!/usr/bin/env python3
"""
qb_log.py — QueryBook event log + contingency helpers (stdlib only).

"We can't work in darkness." Every meaningful action, warning, fallback and error
is recorded here in a bounded, thread-safe ring buffer and surfaced live in the UI
(/api/log → the Console Diagnostics panel). Also provides small "trap" helpers so
callers degrade gracefully instead of crashing or silently repeating a failure.
"""
import threading, time, collections

_MAX = 600
_LOG = collections.deque(maxlen=_MAX)
_LK = threading.Lock()
_SEQ = 0

LEVELS = ("info", "ok", "warn", "error", "blocked")


def log(level, source, msg, **extra):
    """Record one event. level ∈ LEVELS; source is a short tag; msg is human text."""
    global _SEQ
    with _LK:
        _SEQ += 1
        e = {"seq": _SEQ, "t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "ts": time.time(), "level": str(level), "source": str(source)[:60],
             "msg": str(msg)[:500]}
        if extra:
            e.update({k: extra[k] for k in list(extra)[:8]})
        _LOG.append(e)
    return e


def entries(limit=200, level=None, since_seq=0):
    with _LK:
        items = list(_LOG)
    if level:
        items = [e for e in items if e["level"] == level]
    if since_seq:
        items = [e for e in items if e["seq"] > since_seq]
    items = items[-int(limit):]
    items.reverse()  # newest first
    return items


def counts():
    with _LK:
        items = list(_LOG)
    c = {k: 0 for k in LEVELS}
    for e in items:
        c[e["level"]] = c.get(e["level"], 0) + 1
    return c


def clear():
    with _LK:
        _LOG.clear()


def guard(source, fn, *args, on_fail=None, **kwargs):
    """Trap: run fn; on exception, log an error and return on_fail instead of raising.
    Lets callers keep going (fallback) rather than crash or repeat an unhandled error."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        log("error", source, "trapped: %s" % e)
        return on_fail
