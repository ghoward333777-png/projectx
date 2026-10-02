"""LIL — Language & Identity Linking (voiceprint engine)  [deterministic; consent-gated]

Backend for the Voice Lab's voiceprint feature (previously a browser-only demo). A voiceprint
is a DETERMINISTIC acoustic feature vector (see qb_audio) linked to an identity record
(name + optional email/venue/event). Enrolment is CONSENT-GATED per the covenant; the local
store is git-ignored. Matching is a transparent distance score — NOT a neural speaker model,
and it performs NO anti-spoofing; both are labelled honestly.

Identity linking stays covenant-safe: a match is stored/returned as an ATTRIBUTED claim
("this audio resembles profile X at score S"), never as an asserted identity fact.
"""

import json as _json
import os as _os
import time as _time
import math as _math

import qb_audio

_STORE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "qb_lil_store.json")
MATCH_THRESHOLD = 0.72     # score >= threshold => "resembles"; deterministic


def _load():
    try:
        return _json.load(open(_STORE, encoding="utf-8")) or {}
    except Exception:
        return {}

def _save(db):
    try:
        _json.dump(db, open(_STORE, "w", encoding="utf-8"))
        try: _os.chmod(_STORE, 0o600)
        except Exception: pass
        return True
    except Exception:
        return False


def enroll(name, audio, consent=False, email=None, venue=None, event=None):
    """Create/replace a voiceprint. Requires explicit consent (covenant)."""
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "a profile name is required"}
    if not consent:
        return {"ok": False, "error": "voiceprint enrolment requires explicit consent (covenant gate)"}
    feat = qb_audio.features(audio)
    if not feat.get("ok"):
        return {"ok": False, "error": feat.get("error", "bad audio")}
    vec = qb_audio.vector(feat)
    db = _load()
    db[name] = {"vector": vec, "features": feat, "email": email, "venue": venue,
                "event": event, "enrolled": int(_time.time())}
    _save(db)
    return {"ok": True, "name": name, "features": feat,
            "note": "Voiceprint stored locally (consent recorded). This is a deterministic "
                    "acoustic fingerprint, not a neural speaker model."}


def _distance(a, b):
    if not a or not b or len(a) != len(b):
        return 1e9
    # normalized euclidean (per-dimension scale already applied in qb_audio.vector)
    return _math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

def _score(a, b):
    d = _distance(a, b)
    return round(1.0 / (1.0 + d / 100.0), 4)   # 1.0 = identical; decays with distance


def match(audio, top=3):
    """Rank enrolled profiles by resemblance to `audio`. Returns attributed resemblance scores."""
    feat = qb_audio.features(audio)
    if not feat.get("ok"):
        return {"ok": False, "error": feat.get("error", "bad audio")}
    vec = qb_audio.vector(feat)
    db = _load()
    ranked = []
    for name, p in db.items():
        s = _score(vec, p.get("vector"))
        ranked.append({"name": name, "score": s, "resembles": s >= MATCH_THRESHOLD,
                       "email": p.get("email"), "venue": p.get("venue"), "event": p.get("event")})
    ranked.sort(key=lambda r: -r["score"])
    return {"ok": True, "features": feat, "threshold": MATCH_THRESHOLD, "candidates": ranked[:top],
            "note": "Resemblance scores are attributed claims, not asserted identity. No anti-spoofing is performed."}


def authenticate(name, audio):
    """Verify a CLAIMED identity against its enrolled voiceprint (deterministic score vs threshold)."""
    db = _load()
    p = db.get((name or "").strip())
    if not p:
        return {"ok": False, "error": "no such profile"}
    feat = qb_audio.features(audio)
    if not feat.get("ok"):
        return {"ok": False, "error": feat.get("error", "bad audio")}
    s = _score(qb_audio.vector(feat), p.get("vector"))
    return {"ok": True, "name": name, "score": s, "threshold": MATCH_THRESHOLD,
            "authenticated": s >= MATCH_THRESHOLD, "features": feat,
            "note": "Deterministic acoustic match only; NOT anti-spoof-secure. Treat as a "
                    "convenience signal, never as sole proof of identity."}


def list_profiles():
    db = _load()
    return {"profiles": [{"name": n, "email": p.get("email"), "venue": p.get("venue"),
                          "event": p.get("event"), "enrolled": p.get("enrolled")}
                         for n, p in sorted(db.items())]}

def delete(name):
    db = _load()
    if name in db:
        del db[name]; _save(db)
        return {"ok": True}
    return {"ok": False, "error": "no such profile"}


def qc():
    """Deterministic self-test using two synthetic tones (distinct pitches must not collide)."""
    import struct, io, wave
    def tone(hz, secs=0.5, rate=16000):
        n = int(rate * secs)
        buf = io.BytesIO(); wf = wave.open(buf, "wb")
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(rate)
        frames = b"".join(struct.pack("<h", int(12000 * _math.sin(2 * _math.pi * hz * i / rate)))
                          for i in range(n))
        wf.writeframes(frames); wf.close(); return buf.getvalue()
    # isolate store
    global _STORE
    orig = _STORE; _STORE = orig + ".qc"
    try:
        try: _os.remove(_STORE)
        except OSError: pass
        checks = []
        r1 = enroll("alice", tone(120), consent=True)
        r2 = enroll("bob", tone(240), consent=True)
        gate = enroll("x", tone(120), consent=False)
        checks.append(("consent gate blocks", not gate["ok"]))
        checks.append(("enroll alice", r1["ok"]))
        checks.append(("enroll bob", r2["ok"]))
        a = authenticate("alice", tone(120))
        checks.append(("alice authenticates to her own tone", a["ok"] and a["authenticated"]))
        m = match(tone(240))
        checks.append(("match ranks bob top for 240Hz", m["ok"] and m["candidates"][0]["name"] == "bob"))
        passed = sum(1 for _, c in checks if c)
        return {"passed": passed, "total": len(checks), "ok": passed == len(checks),
                "rows": [{"check": n, "pass": c} for n, c in checks]}
    finally:
        try: _os.remove(_STORE)
        except OSError: pass
        _STORE = orig


if __name__ == "__main__":
    import json
    print(json.dumps(qc(), indent=2))
