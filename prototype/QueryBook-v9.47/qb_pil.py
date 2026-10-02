"""PIL — Paralinguistic & Pragmatic Interpretation Layer  [deterministic; measured estimates]

Backend for the Voice Lab's tone/emotion/pacing feature and for interpreting QueryBook queries.
From a WAV it reports MEASURED acoustic estimates (pacing, loudness, pitch register, a labelled
arousal estimate). From query text it reports pragmatic cues (intent, politeness, urgency,
certainty). Everything is deterministic and labelled as an estimate — NOT a neural emotion
classifier, and never asserted as a fact about the speaker's true state.
"""

import re as _re
import qb_audio


def _bucket(v, cuts, labels):
    for c, lab in zip(cuts, labels):
        if v <= c:
            return lab
    return labels[-1]


def analyze(audio, text=None):
    """Paralinguistic estimate from audio (+ optional transcript for combined cues)."""
    feat = qb_audio.features(audio)
    if not feat.get("ok"):
        return {"ok": False, "error": feat.get("error", "bad audio")}
    pacing = _bucket(feat["tempo_eps"], [2.0, 3.5, 5.5], ["slow", "measured", "natural", "fast"])
    loud = _bucket(feat["loudness_dbfs"], [-28, -18, -10], ["soft", "normal", "raised", "loud"])
    pitch = feat["pitch_hz"]
    register = ("unvoiced" if pitch <= 0 else
                _bucket(pitch, [140, 200, 300], ["low", "mid", "high", "very high"]))
    # Arousal estimate: combine loudness, tempo, brightness into a 0..1 index (labelled estimate).
    import math
    loud_n = min(1.0, max(0.0, (feat["loudness_dbfs"] + 40) / 40.0))
    tempo_n = min(1.0, feat["tempo_eps"] / 6.0)
    bright_n = min(1.0, feat["brightness"] * 2.0)
    arousal = round((0.45 * loud_n + 0.35 * tempo_n + 0.20 * bright_n), 3)
    arousal_lab = _bucket(arousal, [0.33, 0.66], ["low", "medium", "high"])
    out = {"ok": True, "features": feat,
           "paralinguistics": {"pacing": pacing, "loudness": loud, "pitch_register": register,
                               "arousal_estimate": {"value": arousal, "label": arousal_lab}},
           "note": "Measured acoustic estimates, deterministic. NOT a neural emotion classifier; "
                   "never asserted as the speaker's true emotional state."}
    if text:
        out["pragmatics"] = pragmatics(text)
    return out


POLITE = ("please", "thank", "thanks", "would you", "could you", "kindly", "appreciate")
URGENT = ("now", "immediately", "asap", "urgent", "right away", "hurry", "emergency")
HEDGE = ("maybe", "perhaps", "i think", "possibly", "might", "not sure", "i guess")

def pragmatics(text):
    """Deterministic pragmatic cues from query/utterance text (framing for interpretation)."""
    t = (text or "").strip()
    low = t.lower()
    is_q = t.endswith("?") or bool(_re.match(r"^(who|what|when|where|why|how|which|is|are|do|does|can|could|should)\b", low))
    return {"intent": "question" if is_q else ("command" if _re.match(r"^(please\s+)?[a-z]+\b", low) and not is_q else "statement"),
            "polite": any(p in low for p in POLITE),
            "urgent": any(u in low for u in URGENT),
            "uncertain": any(h in low for h in HEDGE),
            "exclamatory": t.endswith("!"),
            "length_words": len(_re.findall(r"\w+", t))}


def interpret_query(text):
    """Pragmatic framing for a QueryBook query: how to READ it (not what the answer is)."""
    pr = pragmatics(text)
    reading = []
    if pr["intent"] == "question": reading.append("treat as an information request")
    if pr["polite"]: reading.append("polite register")
    if pr["urgent"]: reading.append("prioritize a direct, concise answer")
    if pr["uncertain"]: reading.append("the asker signals low certainty; offer evidence, not just a verdict")
    return {"ok": True, "text": text, "pragmatics": pr, "reading": reading,
            "covenant": "Interpretation frames HOW the query is read; it never changes the "
                        "grounded answer or lets the engine invent one."}


def qc():
    checks = []
    p = pragmatics("Could you please tell me who wrote this?")
    checks.append(("question detected", p["intent"] == "question"))
    checks.append(("polite detected", p["polite"]))
    u = pragmatics("Stop now, immediately!")
    checks.append(("urgent detected", u["urgent"]))
    checks.append(("exclamatory detected", u["exclamatory"]))
    iq = interpret_query("maybe what is the capital?")
    checks.append(("uncertain reading", any("certainty" in r for r in iq["reading"])))
    passed = sum(1 for _, c in checks if c)
    return {"passed": passed, "total": len(checks), "ok": passed == len(checks),
            "rows": [{"check": n, "pass": c} for n, c in checks]}


if __name__ == "__main__":
    import json
    print(json.dumps(qc(), indent=2))
