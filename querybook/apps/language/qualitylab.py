"""Quality Lab: every avatar test becomes a recorded, measured sample, compared with real human speech.

The loop, run until the admin approves a quality level:
  1. a test script is spoken by an avatar and recorded as a video (picture + sound, every word of the script);
  2. the video is measured the same way as human reference clips — the face tracker reads the mouth in every frame
     (opening, width, lip thickness, speed, smoothness, closures, lip-to-sound timing);
  3. the measures are compared with the human references (clips the admin adds: their own recordings, or public
     videos they may use — public domain, Creative Commons, government works); until references exist, provisional
     ranges are used and say so;
  4. the comparison proposes the next candidate calibration (jaw, spread, rounding, closure, smoothing, timing,
     upper-lip arch, teeth); the next test uses it;
  5. only the admin (passphrase) approves a calibration; every face outside the lab speaks with the approved one.
Deterministic: the same measures always give the same score and the same proposal.
"""
import base64, datetime, hashlib, json, math, os

import qbcore as core

SCHEMA = ["""
CREATE TABLE samples (
  id INTEGER PRIMARY KEY, created TEXT NOT NULL, kind TEXT NOT NULL, avatar_id INTEGER, avatar_name TEXT, script TEXT,
  words_text INTEGER, words_timed INTEGER, duration REAL, audio_duration REAL, complete INTEGER NOT NULL DEFAULT 0,
  video TEXT, sha256 TEXT, source TEXT, licence TEXT, calibration INTEGER, metrics TEXT, score REAL, scores TEXT,
  verdict TEXT NOT NULL DEFAULT 'pending', note TEXT);
CREATE TABLE calibration (
  version INTEGER PRIMARY KEY, created TEXT NOT NULL, params TEXT NOT NULL, status TEXT NOT NULL, origin TEXT,
  approved_at TEXT, level TEXT, note TEXT);
"""]

DEFAULTS = {"jaw": 1.0, "spread": 1.0, "round": 1.0, "close": 1.0, "arch": 1.0, "teeth": 1.0, "smooth_ms": 35.0, "lead_ms": 40.0}
BOUNDS = {"jaw": (0.5, 1.5), "spread": (0.4, 1.6), "round": (0.5, 1.5), "close": (0.6, 1.6), "arch": (0.4, 1.8), "teeth": (0.5, 1.4),
          "smooth_ms": (15.0, 90.0), "lead_ms": (-60.0, 140.0)}

# What is measured (from the face tracker, per frame; sizes relative to the speaker's own mouth width at rest)
METRICS = {
    "aperture_mean": "average lip opening while speaking",
    "aperture_p90": "wide openings (90th percentile)",
    "width_var": "how much the mouth widens and narrows",
    "upper_thick_cv": "upper-lip thickness change",
    "lower_thick_cv": "lower-lip thickness change",
    "velocity_p90": "speed of the lips (mouth widths per second)",
    "jerk_rms": "jitter (rough, flickering movement)",
    "closure_rate": "lip closures while speaking (p, b, m)",
    "av_lag_ms": "lips behind (+) or ahead of (-) the sound",
}
# Provisional ranges, used only until the admin adds human reference clips (estimates for conversational speech filmed
# face-on; the references replace them).
PROVISIONAL = {"aperture_mean": (0.08, 0.28), "aperture_p90": (0.2, 0.5), "width_var": (0.015, 0.07), "upper_thick_cv": (0.03, 0.16),
               "lower_thick_cv": (0.04, 0.2), "velocity_p90": (0.8, 3.5), "jerk_rms": (0, 60), "closure_rate": (0.04, 0.25), "av_lag_ms": (-60, 60)}
WEIGHTS = {"aperture_mean": 2, "aperture_p90": 1.5, "width_var": 1.5, "upper_thick_cv": 1.5, "lower_thick_cv": 1, "velocity_p90": 1.5,
           "jerk_rms": 1.5, "closure_rate": 1, "av_lag_ms": 2}


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _kind(data):
    if data[:4] == b"\x1aE\xdf\xa3":
        return "webm"
    if data[4:8] == b"ftyp":
        return "mp4"
    return None


def score(metrics, ranges):
    """Each measure scores 100 inside the human range and falls off with distance outside it (in range widths)."""
    out, tot, wsum = {}, 0.0, 0.0
    for k, (lo, hi) in ranges.items():
        v = metrics.get(k)
        if v is None:
            continue
        span = max(1e-6, hi - lo)
        d = (lo - v) / span if v < lo else (v - hi) / span if v > hi else 0.0
        s = round(100.0 * math.exp(-1.6 * d * d) if d else 100.0, 1)
        out[k] = {"value": round(float(v), 4), "human": [round(lo, 4), round(hi, 4)], "score": s,
                  "verdict": "within human range" if not d else ("too low" if v < lo else "too high")}
        tot += WEIGHTS.get(k, 1) * s
        wsum += WEIGHTS.get(k, 1)
    return (round(tot / wsum, 1) if wsum else 0.0), out


def propose(params, scores):
    """The next candidate calibration: each measure outside the human range moves the setting that drives it."""
    p = dict(params)
    notes = []

    def nudge(key, factor, why):
        lo, hi = BOUNDS[key]
        old = p[key]
        p[key] = round(max(lo, min(hi, old * factor)), 3)
        if p[key] != old:
            notes.append("%s %s → %s (%s)" % (key, old, p[key], why))

    def mid(k):
        lo, hi = scores[k]["human"]
        return (lo + hi) / 2

    for k, s in scores.items():
        if s["score"] >= 99.9:
            continue
        v, m = s["value"], mid(k)
        ratio = (m / v) if v else 1.25
        step = max(0.8, min(1.25, ratio ** 0.6))
        if k in ("aperture_mean", "aperture_p90"):
            nudge("jaw", step, METRICS[k])
        elif k == "width_var":
            nudge("spread", step, METRICS[k])
        elif k == "upper_thick_cv":
            nudge("arch", step, METRICS[k])
        elif k == "closure_rate":
            nudge("close", step, METRICS[k])
        elif k in ("velocity_p90", "jerk_rms"):
            if v > m:
                nudge("smooth_ms", 1.2, METRICS[k] + " — smoother")
            else:
                nudge("smooth_ms", 0.85, METRICS[k] + " — livelier")
        elif k == "av_lag_ms":
            lo, hi = BOUNDS["lead_ms"]
            old = p["lead_ms"]
            p["lead_ms"] = round(max(lo, min(hi, old + 0.7 * (v - m))), 1)   # lips late (+): show the motion earlier
            if p["lead_ms"] != old:
                notes.append("lead_ms %s → %s (%s)" % (old, p["lead_ms"], METRICS[k]))
    return p, notes


class QualityLab:
    def __init__(self, app_folder, approvals_fn=None, program_dir=None, log=None):
        self.folder = os.path.join(app_folder, "qualitylab")
        os.makedirs(self.folder, exist_ok=True)
        self.store = core.Store(self.folder, "qualitylab", SCHEMA, log)
        self.approvals_fn, self.program_dir = approvals_fn, program_dir

    # ------------------------------------------------------------------ calibration
    def _cal_rows(self):
        return [dict(r) for r in self.store.query("SELECT * FROM calibration ORDER BY version")]

    def _shipped(self):
        """A calibration the admin approved earlier and shipped with the program (calibration.json next to it)."""
        p = os.path.join(self.program_dir or "", "calibration.json")
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            return {k: float(d["params"][k]) for k in DEFAULTS if k in d.get("params", {})}
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def calibration(self):
        rows = self._cal_rows()
        for r in rows:
            r["params"] = json.loads(r["params"])
        approved = next((r for r in reversed(rows) if r["status"] == "approved"), None)
        candidate = rows[-1] if rows else None
        shipped = self._shipped()
        return {"approved": approved, "candidate": candidate, "history": rows[-20:], "defaults": DEFAULTS, "bounds": BOUNDS,
                "shipped": shipped, "metrics": METRICS}

    def active(self, lab=False):
        """The calibration the faces speak with: the lab tests the candidate; everywhere else uses the approved one."""
        c = self.calibration()
        if lab and c["candidate"]:
            r = c["candidate"]
            return {"version": r["version"], "status": r["status"], "params": dict(DEFAULTS, **r["params"])}
        if c["approved"]:
            r = c["approved"]
            return {"version": r["version"], "status": "approved", "params": dict(DEFAULTS, **r["params"])}
        if c["shipped"]:
            return {"version": 0, "status": "shipped", "params": dict(DEFAULTS, **c["shipped"])}
        return {"version": 0, "status": "default — not yet approved", "params": dict(DEFAULTS)}

    def save_candidate(self, params, origin="admin", note=""):
        cur = self.active(lab=True)["params"]
        p = {k: round(max(BOUNDS[k][0], min(BOUNDS[k][1], float(params.get(k, cur[k])))), 3) for k in DEFAULTS}
        with self.store.write() as db:
            db.execute("UPDATE calibration SET status = 'superseded' WHERE status = 'candidate'")
            v = db.execute("INSERT INTO calibration(created, params, status, origin, note) VALUES(?,?,?,?,?)",
                           (_now(), json.dumps(p), "candidate", origin, str(note)[:500])).lastrowid
        return {"version": v, "params": p}

    def approve(self, version, passphrase, level="production", note=""):
        ap = self.approvals_fn() if self.approvals_fn else None
        if ap is None:
            raise core.UserError("The admin passphrase is not available here.")
        ap._require(passphrase)
        r = self.store.one("SELECT * FROM calibration WHERE version = ?", (int(version),))
        if not r:
            raise core.UserError("No such calibration.")
        with self.store.write() as db:
            db.execute("UPDATE calibration SET status = 'superseded' WHERE status = 'approved'")
            db.execute("UPDATE calibration SET status = 'approved', approved_at = ?, level = ?, note = ? WHERE version = ?",
                       (_now(), str(level)[:60], str(note)[:500], int(version)))
        return self.calibration()["approved"]

    def export(self):
        a = self.calibration()["approved"]
        if not a:
            raise core.UserError("No calibration has been approved yet.")
        return {"version": a["version"], "approved_at": a["approved_at"], "level": a["level"], "params": a["params"]}

    def ship(self, passphrase):
        """Write the approved calibration next to the program, so a packaged installer speaks with it from the start."""
        ap = self.approvals_fn() if self.approvals_fn else None
        if ap is None:
            raise core.UserError("The admin passphrase is not available here.")
        ap._require(passphrase)
        d = self.export()
        p = os.path.join(self.program_dir, "calibration.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
        return {"written": p, **d}

    # ------------------------------------------------------------------ samples and references
    def add(self, kind, data, meta):
        if kind not in ("avatar", "reference"):
            raise core.UserError("A sample is an avatar test or a human reference.")
        if not data or len(data) > 300 * 1024 * 1024:
            raise core.UserError("The video is empty or larger than 300 MB.")
        ext = _kind(data)
        if not ext:
            raise core.UserError("Use a WebM or MP4 video.")
        sha = hashlib.sha256(data).hexdigest()
        words_text, words_timed = int(meta.get("words_text") or 0), int(meta.get("words_timed") or 0)
        dur, adur = float(meta.get("duration") or 0), float(meta.get("audio_duration") or 0)
        complete = 1 if kind == "reference" else int(words_text > 0 and words_timed >= words_text and dur + 0.05 >= adur > 0)
        if kind == "reference" and not (meta.get("source") or "").strip():
            raise core.UserError("Say where the reference comes from (your own recording, or the public video's address).")
        cal = self.active(lab=True)["version"] if kind == "avatar" else None
        with self.store.write() as db:
            sid = db.execute("""INSERT INTO samples(created, kind, avatar_id, avatar_name, script, words_text, words_timed, duration,
                                audio_duration, complete, sha256, source, licence, calibration) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                             (_now(), kind, meta.get("avatar_id"), str(meta.get("avatar_name") or "")[:80], str(meta.get("script") or "")[:4000],
                              words_text, words_timed, dur, adur, complete, sha, str(meta.get("source") or "")[:500],
                              str(meta.get("licence") or "")[:200], cal)).lastrowid
            fn = "%s-%d.%s" % (kind, sid, ext)
            with open(os.path.join(self.folder, fn), "wb") as f:
                f.write(data)
            db.execute("UPDATE samples SET video = ? WHERE id = ?", (fn, sid))
        return self.get(sid)

    def get(self, sid):
        r = self.store.one("SELECT * FROM samples WHERE id = ?", (int(sid),))
        if not r:
            raise core.UserError("No such sample.")
        r = dict(r)
        for k in ("metrics", "scores"):
            r[k] = json.loads(r[k]) if r[k] else None
        r["complete"] = bool(r["complete"])
        return r

    def video_path(self, sid):
        r = self.get(sid)
        return os.path.join(self.folder, os.path.basename(r["video"] or ""))

    def list(self, kind=None, limit=200):
        q = "SELECT id FROM samples" + (" WHERE kind = ?" if kind else "") + " ORDER BY id DESC LIMIT ?"
        return [self.get(r["id"]) for r in self.store.query(q, ((kind,) if kind else ()) + (int(limit),))]

    def delete(self, sid):
        p = self.video_path(sid)
        with self.store.write() as db:
            db.execute("DELETE FROM samples WHERE id = ?", (int(sid),))
        try:
            os.remove(p)
        except OSError:
            pass
        return {"deleted": True}

    def human_ranges(self):
        """The human range of each measure: from the reference clips (mean ± 1.5 sd, at least ±15% of the mean), else provisional."""
        refs = [r["metrics"] for r in self.list("reference") if r["metrics"]]
        if not refs:
            return dict(PROVISIONAL), "provisional ranges — add human reference clips to replace them"
        out = {}
        for k in METRICS:
            vals = [float(m[k]) for m in refs if m.get(k) is not None]
            if not vals:
                out[k] = PROVISIONAL[k]
                continue
            mu = sum(vals) / len(vals)
            sd = (sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5
            half = max(1.5 * sd, 0.15 * abs(mu), 1e-3 if k != "av_lag_ms" else 25.0)
            out[k] = (mu - half, mu + half)
        return out, "from %d human reference clip(s)" % len(refs)

    def set_metrics(self, sid, metrics):
        m = {k: float(metrics[k]) for k in METRICS if metrics.get(k) is not None and math.isfinite(float(metrics[k]))}
        m["frames"] = int(metrics.get("frames") or 0)
        m["tracked"] = float(metrics.get("tracked") or 0)
        r = self.get(sid)
        result = {"metrics": m}
        if r["kind"] == "avatar":
            ranges, basis = self.human_ranges()
            total, per = score(m, ranges)
            cal = self.active(lab=True)
            proposal, notes = propose(cal["params"], per)
            result.update(score=total, scores=per, basis=basis, proposal=proposal, proposal_notes=notes, calibration=cal["version"])
            with self.store.write() as db:
                db.execute("UPDATE samples SET metrics = ?, score = ?, scores = ? WHERE id = ?", (json.dumps(m), total, json.dumps(per), int(sid)))
        else:
            with self.store.write() as db:
                db.execute("UPDATE samples SET metrics = ? WHERE id = ?", (json.dumps(m), int(sid)))
        return result

    def verdict(self, sid, verdict, note=""):
        if verdict not in ("approved", "rejected", "pending"):
            raise core.UserError("A verdict is approved, rejected or pending.")
        self.get(sid)
        with self.store.write() as db:
            db.execute("UPDATE samples SET verdict = ?, note = ? WHERE id = ?", (verdict, str(note)[:1000], int(sid)))
        return self.get(sid)

    def status(self):
        c = self.calibration()
        avatar = [r for r in self.list("avatar") if r["score"] is not None]
        recent = avatar[:10]
        return {"calibration": self.active(), "candidate": c["candidate"], "approved": c["approved"],
                "references": len(self.list("reference")), "samples": len(avatar),
                "recent_mean_score": round(sum(r["score"] for r in recent) / len(recent), 1) if recent else None,
                "basis": self.human_ranges()[1]}
