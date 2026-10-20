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
import base64, datetime, hashlib, json, math, os, re, threading, time, urllib.error, urllib.parse, urllib.request

import qbcore as core
import lipread
import vse

SCHEMA = ["""
CREATE TABLE samples (
  id INTEGER PRIMARY KEY, created TEXT NOT NULL, kind TEXT NOT NULL, avatar_id INTEGER, avatar_name TEXT, script TEXT,
  words_text INTEGER, words_timed INTEGER, duration REAL, audio_duration REAL, complete INTEGER NOT NULL DEFAULT 0,
  video TEXT, sha256 TEXT, source TEXT, licence TEXT, calibration INTEGER, metrics TEXT, score REAL, scores TEXT,
  verdict TEXT NOT NULL DEFAULT 'pending', note TEXT);
CREATE TABLE calibration (
  version INTEGER PRIMARY KEY, created TEXT NOT NULL, params TEXT NOT NULL, status TEXT NOT NULL, origin TEXT,
  approved_at TEXT, level TEXT, note TEXT);
""", """
ALTER TABLE samples ADD COLUMN transcript TEXT;
ALTER TABLE samples ADD COLUMN frames TEXT;
ALTER TABLE samples ADD COLUMN labels TEXT;
CREATE TABLE human_model (version INTEGER PRIMARY KEY, created TEXT NOT NULL, references_used INTEGER, frames_used INTEGER,
  targets TEXT, style TEXT, visemes TEXT);
""", """
ALTER TABLE samples ADD COLUMN words TEXT;
ALTER TABLE samples ADD COLUMN emotion TEXT;
ALTER TABLE samples ADD COLUMN lang TEXT;
CREATE TABLE motion_graph (src TEXT NOT NULL, rel TEXT NOT NULL, dst TEXT NOT NULL, n INTEGER NOT NULL, stats TEXT,
  PRIMARY KEY (src, rel, dst));
""", """
ALTER TABLE samples ADD COLUMN cues TEXT;
ALTER TABLE samples ADD COLUMN origin TEXT;
"""]

DEFAULTS = {"jaw": 1.0, "spread": 1.0, "round": 1.0, "close": 1.0, "arch": 1.0, "teeth": 1.0, "smooth_ms": 35.0, "lead_ms": 40.0,
            "head": 1.0, "brow": 1.0}
BOUNDS = {"jaw": (0.5, 1.5), "spread": (0.4, 1.6), "round": (0.5, 1.5), "close": (0.6, 1.6), "arch": (0.4, 1.8), "teeth": (0.5, 1.4),
          "smooth_ms": (15.0, 90.0), "lead_ms": (-60.0, 140.0), "head": (0.3, 3.0), "brow": (0.3, 3.0)}

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
    "shape_error": "mouth shape per sound vs the learned human shapes",
    "blink_rate": "blinks per minute",
    "head_motion": "head movement (degrees, typical swing)",
    "brow_activity": "eyebrow movement",
}
# Provisional ranges, used only until the admin adds human reference clips (estimates for conversational speech filmed
# face-on; the references replace them).
PROVISIONAL = {"aperture_mean": (0.08, 0.28), "aperture_p90": (0.2, 0.5), "width_var": (0.015, 0.07), "upper_thick_cv": (0.03, 0.16),
               "lower_thick_cv": (0.04, 0.2), "velocity_p90": (0.8, 3.5), "jerk_rms": (0, 60), "closure_rate": (0.04, 0.25), "av_lag_ms": (-60, 60),
               "shape_error": (0, 0.06), "blink_rate": (8, 30), "head_motion": (1.0, 6.0), "brow_activity": (0.02, 0.12)}
WEIGHTS = {"aperture_mean": 2, "aperture_p90": 1.5, "width_var": 1.5, "upper_thick_cv": 1.5, "lower_thick_cv": 1, "velocity_p90": 1.5,
           "jerk_rms": 1.5, "closure_rate": 1, "av_lag_ms": 2, "shape_error": 3, "blink_rate": 1, "head_motion": 1.5, "brow_activity": 1}
# The library of places that show how talking looks — what each teaches, its licence, and whether "Ingest example videos"
# takes clips from it automatically (only public-domain / openly licensed sources with a machine-readable licence).
SOURCES = [
    {"name": "NASA press briefings and interviews", "url": "https://images.nasa.gov", "licence": "public domain (NASA media)", "auto": True,
     "teaches": "steady, front-facing speakers with caption files (exact words): mouth shape per sound, timing, blinks, brows, head",
     "languages": "English"},
    {"name": "Wikimedia Commons — videos of speeches", "url": "https://commons.wikimedia.org/wiki/Category:Videos_of_speeches",
     "licence": "public domain / CC BY / CC BY-SA (per file)", "auto": True,
     "teaches": "many languages and speakers: face, eye, brow and head movement while talking", "languages": "many"},
    {"name": "Voice of America — Learning English", "url": "https://learningenglish.voanews.com", "licence": "public domain (US government), except third-party footage",
     "auto": False, "teaches": "slow, clear, front-facing presenters with full transcripts; add clips with “Fetch”", "languages": "English"},
    {"name": "Voice of America — language services", "url": "https://www.insidevoa.com/p/5831.html", "licence": "public domain (US government), except third-party footage",
     "auto": False, "teaches": "news presenters in ~40+ languages, stable studio camera", "languages": "40+"},
    {"name": "GRID audio-visual corpus", "url": "https://spandh.dcs.shef.ac.uk/gridcorpus/", "licence": "CC BY 4.0", "auto": False,
     "teaches": "34 speakers, full frontal faces, 1,000 sentences each with word timings — the cleanest mouth-shape data", "languages": "English"},
    {"name": "CREMA-D (emotional actors)", "url": "https://github.com/CheyneyComputerScience/CREMA-D", "licence": "Open Database Licence", "auto": False,
     "teaches": "91 actors saying 12 sentences in six emotions — how emotion changes the whole face while speaking", "languages": "English"},
    {"name": "RAVDESS (emotional speech video)", "url": "https://zenodo.org/records/1188976", "licence": "CC BY-NC-SA 4.0 (non-commercial only)", "auto": False,
     "teaches": "24 actors, frontal, eight emotions at two intensities", "languages": "English"},
    {"name": "Seeing Speech (University of Glasgow)", "url": "https://www.seeingspeech.ac.uk", "licence": "view only (copyrighted)", "auto": False,
     "teaches": "how each speech sound is made — lips, tongue, jaw (articulation videos, MRI and ultrasound); for reading, not ingesting", "languages": "English"},
    {"name": "Your own recordings", "url": "", "licence": "yours", "auto": False,
     "teaches": "the webcam button records you reading the test script — the best match of all", "languages": "any"},
]
UA = "QueryBook-QualityLab/1.0 (https://github.com/ghoward333777-png/projectx; talking-face reference clips, polite, low volume) python-urllib"
COMMONS_OK = re.compile(r"^(public domain|pd|cc0|cc by(-sa)? ?\d|cc-by(-sa)?)", re.I)


def _safe(url):
    u = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((u.scheme, u.netloc, urllib.parse.quote(urllib.parse.unquote(u.path), safe="/~:@!$&'()*+,;="), u.query, u.fragment))


def _get(url, timeout=40, limit=None, tries=3):
    """Polite GET: one request at a time, and when a site says “too many requests” we wait as long as it asks (≤ 60 s)."""
    import time
    for k in range(tries):
        try:
            req = urllib.request.Request(_safe(url), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(limit) if limit else r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and k + 1 < tries:
                time.sleep(min(60, int(e.headers.get("Retry-After") or 0) or 10 * (k + 1)))
                continue
            raise


def _size(url):
    try:
        req = urllib.request.Request(_safe(url), method="HEAD", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            return int(r.headers.get("Content-Length") or 0)
    except Exception:
        return 0


def srt_cues(text):
    """SRT/VTT captions → [{start, end, text}]."""
    cues, t = [], lambda h, m, s_, ms: int(h) * 3600 + int(m) * 60 + int(s_) + int(ms) / 1000
    for blk in re.split(r"\n\s*\n", (text or "").replace("\r", "")):
        m = re.search(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})", blk)
        if not m:
            continue
        words = " ".join(l.strip() for l in blk.split("\n")[blk.split("\n").index(next(l for l in blk.split("\n") if "-->" in l)) + 1:] if l.strip())
        words = re.sub(r"<[^>]+>|\[[^\]]*\]|\([^)]*\)", " ", words)
        if words.strip():
            cues.append({"start": t(*m.group(1, 2, 3, 4)), "end": t(*m.group(5, 6, 7, 8)), "text": " ".join(words.split())})
    return cues


# Where reference video may be fetched from automatically: public-domain and openly licensed archives, and US government
# works. YouTube and broadcasters are not: their terms forbid downloading, and TV/film footage is copyrighted.
# Voice of America: news in ~40+ languages, public domain as a US government work (except third-party footage it licenses).
VOA_HOST = __import__("re").compile(r"(^|\.)(voa[a-z]*|insidevoa|golosameriki|radiosvoboda|martinoticias)\.(com|gov|org)$|(^|\.)voa-video[a-z0-9.-]*$")
ALLOWED_HOSTS = ("upload.wikimedia.org", "commons.wikimedia.org", "archive.org", "ia800", "ia900", "spandh.dcs.shef.ac.uk", "zenodo.org")
REFUSED_HOSTS = ("youtube.com", "youtu.be", "googlevideo.com", "vimeo.com", "tiktok.com", "netflix.com", "facebook.com", "instagram.com")


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
        elif k == "head_motion":
            nudge("head", step, METRICS[k])
        elif k == "brow_activity":
            nudge("brow", step, METRICS[k])
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
            db.execute("UPDATE samples SET video = ?, transcript = ? WHERE id = ?", (fn, str(meta.get("transcript") or "")[:4000], sid))
        return self.get(sid)

    def get(self, sid):
        r = self.store.one("SELECT * FROM samples WHERE id = ?", (int(sid),))
        if not r:
            raise core.UserError("No such sample.")
        r = dict(r)
        for k in ("metrics", "scores"):
            r[k] = json.loads(r[k]) if r[k] else None
        r["learned"] = bool(r.pop("frames", None))
        r.pop("labels", None)
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
        was_ref = self.get(sid)["kind"] == "reference"
        with self.store.write() as db:
            db.execute("DELETE FROM samples WHERE id = ?", (int(sid),))
        try:
            os.remove(p)
        except OSError:
            pass
        if was_ref:
            self.rebuild()                    # what was learned from it goes too
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

    # ------------------------------------------------------------------ learning from human speech
    def fetch_reference(self, url, source="", licence="", transcript=""):
        """Download a reference clip from an allowed archive (public domain / open licence / US government works)."""
        u = urllib.parse.urlsplit(str(url or "").strip())
        host = (u.hostname or "").lower()
        if u.scheme not in ("http", "https") or not host:
            raise core.UserError("Give the full address of the video file.")
        if any(host == h or host.endswith("." + h) for h in REFUSED_HOSTS):
            raise core.UserError("Not from %s: its terms forbid downloading, and TV, film and news footage there is copyrighted. "
                                 "Use public-domain sources (US government briefings, NASA, Wikimedia Commons, Internet Archive "
                                 "public-domain items), openly licensed corpora, or record yourself." % host)
        if not (host.endswith(".gov") or host.endswith(".mil") or VOA_HOST.search(host) or any(h in host for h in ALLOWED_HOSTS)):
            raise core.UserError("That site is not on the allowed list (Voice of America sites, US government .gov/.mil, Wikimedia Commons, "
                                 "Internet Archive, Zenodo, the GRID corpus). Download it yourself if you may, and add it as a file.")
        req = urllib.request.Request(u.geturl(), headers={"User-Agent": "QueryBook-QualityLab/1.0 (reference clips; polite)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read(300 * 1024 * 1024 + 1)
        return self.add("reference", data, {"source": source or u.geturl(), "licence": licence or "public domain / open licence (from %s)" % host,
                                            "transcript": transcript})

    def learn(self, sid, frames, segments, transcript="", words=None, emotion=None, lang=""):
        """Keep a reference clip's measured frames, each labelled with the sound being made (from aligning its audio with its
        words), then rebuild the human motion model."""
        r = self.get(sid)
        if r["kind"] != "reference":
            raise core.UserError("Only human reference clips teach the model.")
        segs = sorted([(str(x["v"]), float(x["start"]), float(x["end"])) for x in segments or [] if x.get("v")], key=lambda x: x[1])
        rows, labels, j = [], [], 0
        for fr in frames or []:
            t = float(fr.get("t") or 0)
            while j < len(segs) and segs[j][2] <= t:
                j += 1
            v = segs[j][0] if j < len(segs) and segs[j][1] <= t < segs[j][2] else None
            bs = fr.get("bs") or {}
            upper = {k: round(float(bs.get(n, 0) or 0), 3) for k, n in (("sq", "eyeSquintLeft"), ("ch", "cheekSquintLeft"), ("wd", "eyeWideLeft"),
                                                                       ("bd", "browDownLeft"), ("ns", "noseSneerLeft"), ("bo", "browOuterUpLeft"))}
            rows.append([t] + lipread.features(fr) + [fr.get("pose") or [], bs.get("eyeBlinkLeft", 0), bs.get("browInnerUp", 0), upper])
            labels.append(["", v] if (v and fr.get("face")) else None)
        with self.store.write() as db:
            db.execute("UPDATE samples SET frames = ?, labels = ?, transcript = ?, words = ?, emotion = ?, lang = ? WHERE id = ?",
                       (json.dumps(rows), json.dumps(labels), str(transcript)[:4000],
                        json.dumps([{"word": str(w.get("word", ""))[:60], "start": float(w.get("start", 0)), "end": float(w.get("end", 0))} for w in (words or [])]),
                        json.dumps({k: round(float(v), 3) for k, v in (emotion or {}).items() if isinstance(v, (int, float))}), str(lang or "")[:12], int(sid)))
        return self.rebuild()

    def rebuild(self):
        refs = [dict(r) for r in self.store.query("SELECT id, frames, labels, words, emotion, lang FROM samples WHERE kind = 'reference' AND frames IS NOT NULL")]
        self._graph(refs)
        data, nf, blinks, mins, yaw, pitch, roll, brow, upper = [], 0, 0, 0.0, [], [], [], [], {}
        for r in refs:
            fr, lb = json.loads(r["frames"]), json.loads(r["labels"] or "[]")
            data.append(([f[:1 + len(lipread.FEATURES)] for f in fr], lb))
            nf += len(fr)
            if len(fr) > 2:
                mins += (fr[-1][0] - fr[0][0]) / 60
                prev = 0
                P = 1 + len(lipread.FEATURES)
                for f in fr:
                    b = f[P + 1] or 0
                    if b > 0.5 and prev <= 0.5:
                        blinks += 1
                    prev = b
                    if f[P] and len(f[P]) >= 3:
                        yaw.append(f[P][0]); pitch.append(f[P][1]); roll.append(f[P][2])   # measureFrame: [yaw, pitch, roll, …]
                    brow.append(f[P + 2] or 0)
                    up = f[P + 3] if len(f) > P + 3 and isinstance(f[P + 3], dict) else None
                    if up:
                        for k in ("sq", "ch", "wd", "bd", "ns"):
                            upper.setdefault(k, []).append(up.get(k, 0))
        targets = vse.learn_targets(data)
        sd = lambda a: (sum((x - sum(a) / len(a)) ** 2 for x in a) / len(a)) ** 0.5 if len(a) > 2 else None
        style = {"blink_per_min": round(blinks / mins, 1) if mins > 0.05 else None, "yaw_sd": sd(yaw), "pitch_sd": sd(pitch), "roll_sd": sd(roll),
                 "brow_sd": sd(brow)}
        for k, name in (("sq", "squint_sd"), ("ch", "cheek_sd"), ("wd", "wide_sd"), ("bd", "browdown_sd"), ("ns", "sneer_sd")):
            style[name] = sd(upper.get(k, []))
        style = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in style.items()}
        with self.store.write() as db:
            v = db.execute("INSERT INTO human_model(created, references_used, frames_used, targets, style, visemes) VALUES(?,?,?,?,?,?)",
                           (_now(), len(refs), nf, json.dumps(targets), json.dumps(style), json.dumps(sorted(targets)))).lastrowid
        return self.human_model()

    def human_model(self):
        r = self.store.one("SELECT * FROM human_model ORDER BY version DESC LIMIT 1")
        if not r:
            return {"version": 0, "targets": {}, "style": {}, "visemes": [], "references_used": 0, "frames_used": 0}
        r = dict(r)
        for k in ("targets", "style", "visemes"):
            r[k] = json.loads(r[k] or "{}")
        return r

    def shape_error(self, frames, segments):
        """How far the avatar's measured mouth shape per sound is from the learned human shape (mean abs difference)."""
        hm = self.human_model()["targets"]
        if not hm:
            return None
        segs = sorted([(str(x["v"]), float(x["start"]), float(x["end"])) for x in segments or []], key=lambda x: x[1])
        acc = {}
        for fr in frames or []:
            t = float(fr.get("t") or 0)
            v = next((a for a, b0, b1 in segs if b0 <= t < b1), None)
            if v in hm and fr.get("face"):
                acc.setdefault(v, []).append(lipread.features(fr))
        diffs = []
        for v, rows in acc.items():
            mean = [sum(r[i] for r in rows) / len(rows) for i in range(len(lipread.FEATURES))]
            diffs.append(sum(abs(a - b) for a, b in zip(mean, hm[v])) / len(mean))
        return round(sum(diffs) / len(diffs), 4) if diffs else None

    # ------------------------------------------------------------------ the motion graph
    def _graph(self, refs):
        """Rebuild the graph library of movement from every learned clip (deterministic):
             lang:<l>        —uses_word→        word:<l>:<w>      (how often)
             word:<l>:<w>    —articulated_as→   viseme:<v>        (how often)
             word:<l>:<w>    —moves_mouth→      motion:mouth      (mean of the 13 mouth measures, duration)
             word:<l>:<w>    —moves_head→       motion:head       (mean yaw/pitch/roll swing, brow lift)
             viseme:<v>      —shaped_under→     emotion:<e>       (mean mouth measures while that emotion leads)
             emotion:<e>     —moves_head→       motion:head       (head swing, brow movement, blinks)"""
        acc = {}

        def add(src, rel, dst, vec=None, extra=None):
            k = (src, rel, dst)
            a = acc.setdefault(k, {"n": 0, "sum": None, "extra": {}})
            a["n"] += 1
            if vec is not None:
                a["sum"] = list(vec) if a["sum"] is None else [x + y for x, y in zip(a["sum"], vec)]
            for ek, ev in (extra or {}).items():
                a["extra"][ek] = a["extra"].get(ek, 0.0) + ev

        nf = len(lipread.FEATURES)
        for r in refs:
            fr = json.loads(r["frames"] or "[]")
            lb = json.loads(r["labels"] or "[]")
            words = json.loads(r.get("words") or "[]")
            emo = json.loads(r.get("emotion") or "{}")
            lang = (r.get("lang") or "en").split("-")[0].lower()
            lead = max(emo, key=emo.get) if emo else "neutral"
            for w in words:
                ww = "".join(ch for ch in str(w["word"]).lower() if ch.isalnum() or ch == "'")
                if not ww:
                    continue
                inside = [f for f in fr if w["start"] <= f[0] < w["end"]]
                node = "word:%s:%s" % (lang, ww)
                add("lang:" + lang, "uses_word", node)
                if inside:
                    mean = [sum(f[1 + i] for f in inside) / len(inside) for i in range(nf)]
                    add(node, "moves_mouth", "motion:mouth", mean, {"seconds": w["end"] - w["start"]})
                    poses = [f[1 + nf] for f in inside if f[1 + nf] and len(f[1 + nf]) >= 3]
                    if poses:
                        sw = lambda i: max(p[i] for p in poses) - min(p[i] for p in poses)
                        add(node, "moves_head", "motion:head", None, {"yaw": sw(0), "pitch": sw(1), "roll": sw(2),
                                                                      "brow": max(f[3 + nf] or 0 for f in inside)})
            for f, l in zip(fr, lb):
                if l and l[1]:
                    add("viseme:" + l[1], "shaped_under", "emotion:" + lead, f[1:1 + nf])
                    for w in words:
                        if w["start"] <= f[0] < w["end"]:
                            ww = "".join(ch for ch in str(w["word"]).lower() if ch.isalnum() or ch == "'")
                            if ww:
                                add("word:%s:%s" % (lang, ww), "articulated_as", "viseme:" + l[1])
                            break
            poses = [f[1 + nf] for f in fr if f[1 + nf] and len(f[1 + nf]) >= 3]
            if poses:
                sd = lambda i: (sum((p[i] - sum(q[i] for q in poses) / len(poses)) ** 2 for p in poses) / len(poses)) ** 0.5
                add("emotion:" + lead, "moves_head", "motion:head", None, {"yaw_sd": sd(0), "pitch_sd": sd(1), "roll_sd": sd(2)})
        with self.store.write() as db:
            db.execute("DELETE FROM motion_graph")
            for (src, rel, dst), a in sorted(acc.items()):
                st = {}
                if a["sum"] is not None:
                    st["mouth"] = dict(zip(lipread.FEATURES, [round(x / a["n"], 4) for x in a["sum"]]))
                st.update({k: round(v / a["n"], 3) for k, v in a["extra"].items()})
                db.execute("INSERT INTO motion_graph(src, rel, dst, n, stats) VALUES(?,?,?,?,?)", (src, rel, dst, a["n"], json.dumps(st)))

    def graph(self, node=None, limit=200):
        if node:
            rows = self.store.query("SELECT * FROM motion_graph WHERE src = ? OR dst = ? ORDER BY n DESC LIMIT ?", (node, node, int(limit)))
        else:
            rows = self.store.query("SELECT * FROM motion_graph ORDER BY n DESC LIMIT ?", (int(limit),))
        counts = {r["k"]: r["c"] for r in self.store.query("SELECT substr(src, 1, instr(src, ':') - 1) AS k, COUNT(DISTINCT src) AS c FROM motion_graph GROUP BY k")}
        langs = [r["src"][5:] for r in self.store.query("SELECT DISTINCT src FROM motion_graph WHERE src LIKE 'lang:%' ORDER BY src")]
        return {"nodes": counts, "languages": langs, "edges": [dict(r, stats=json.loads(r["stats"] or "{}")) for r in rows]}

    # ------------------------------------------------------------------ "Ingest example videos"
    def sources(self):
        return {"sources": SOURCES}

    def _have(self, origin):
        return bool(self.store.one("SELECT id FROM samples WHERE origin = ?", (origin,)))

    def _keep(self, data, origin, source, licence, cues=None, lang="en"):
        smp = self.add("reference", data, {"source": source, "licence": licence,
                                           "transcript": " ".join(c["text"] for c in cues or [])})
        with self.store.write() as db:
            db.execute("UPDATE samples SET origin = ?, cues = ?, lang = ? WHERE id = ?", (origin, json.dumps(cues or []), lang, smp["id"]))
        return smp["id"]

    def _nasa(self, want, log, max_mb):
        got = []
        for q in ("interview", "astronaut interview", "press conference", "briefing", "explains"):
            if len(got) >= want:
                break
            d = json.loads(_get("https://images-api.nasa.gov/search?media_type=video&page_size=40&q=" + urllib.parse.quote(q)))
            for it in d.get("collection", {}).get("items", []):
                if len(got) >= want:
                    break
                meta = (it.get("data") or [{}])[0]
                nid = meta.get("nasa_id")
                origin = "nasa:" + str(nid)
                if not nid or self._have(origin):
                    continue
                try:
                    files = json.loads(_get(it["href"]))
                    mp4 = next((f for f in files if f.endswith("~mobile.mp4")), None) or next((f for f in files if f.endswith("~small.mp4")), None)
                    srt = next((f for f in files if f.endswith(".srt") or f.endswith(".vtt")), None)
                    if not mp4 or not srt:
                        continue                                  # learning needs the words: only clips with captions
                    mp4, srt = mp4.replace("http://", "https://"), srt.replace("http://", "https://")
                    size = _size(mp4)
                    if not size or size > max_mb * 1024 * 1024:
                        continue
                    cues = srt_cues(_get(srt).decode("utf-8", "replace"))
                    if len(cues) < 3:
                        continue
                    log("NASA: downloading “%s” (%.0f MB, %d caption lines)" % (meta.get("title", nid)[:70], size / 1048576, len(cues)))
                    got.append(self._keep(_get(mp4, timeout=300), origin, "https://images.nasa.gov/details/" + nid + " — " + meta.get("title", ""),
                                          "public domain (NASA media)", cues))
                except Exception as e:
                    log("NASA: skipped %s (%s)" % (nid, e))
        return got

    def _commons(self, want, log, max_mb):
        got, cont = [], ""
        for _ in range(6):
            if len(got) >= want:
                break
            url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&generator=categorymembers&gcmtitle=Category:Videos_of_speeches"
                   "&gcmtype=file&gcmlimit=40&prop=videoinfo&viprop=url%7Csize%7Cmime%7Cderivatives%7Cextmetadata"
                   "&viextmetadatafilter=LicenseShortName%7CArtist" + ("&gcmcontinue=" + urllib.parse.quote(cont) if cont else ""))
            try:
                d = json.loads(_get(url))
            except urllib.error.HTTPError as e:
                log("Wikimedia Commons is busy (%s) — try again later; the other sources carry on." % e.code)
                break
            cont = (d.get("continue") or {}).get("gcmcontinue", "")
            for p in (d.get("query") or {}).get("pages", {}).values():
                if len(got) >= want:
                    break
                vi = (p.get("videoinfo") or [{}])[0]
                lic = ((vi.get("extmetadata") or {}).get("LicenseShortName") or {}).get("value", "")
                origin = "commons:" + p["title"]
                if not COMMONS_OK.search(lic.strip()) or self._have(origin):
                    continue
                der = next((x for x in vi.get("derivatives", []) if (x.get("transcodekey") or "") in ("360p.vp9.webm", "240p.vp9.webm")), None)
                if not der:
                    continue
                time.sleep(1.0)                                   # Wikimedia asks bots to go gently
                size = _size(der["src"])
                if not size or size > max_mb * 1024 * 1024:
                    continue
                try:
                    cues = []
                    for code in ("en", "de", "fr", "es", "it", "cs", "el"):
                        t = json.loads(_get("https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=revisions&rvprop=content&rvslots=main&titles="
                                            + urllib.parse.quote("TimedText:" + p["title"][5:] + "." + code + ".srt")))
                        pg = next(iter(t["query"]["pages"].values()))
                        if "revisions" in pg:
                            cues = srt_cues(pg["revisions"][0]["slots"]["main"]["*"]); lang = code
                            break
                    log("Commons: downloading “%s” (%s, %.0f MB%s)" % (p["title"][5:70], lic, size / 1048576, ", with captions" if cues else ", no captions: face movement only"))
                    got.append(self._keep(_get(der["src"], timeout=300), origin, vi.get("descriptionurl") or ("https://commons.wikimedia.org/wiki/" + p["title"]),
                                          lic + " (Wikimedia Commons)", cues, lang if cues else ""))
                except Exception as e:
                    log("Commons: skipped %s (%s)" % (p["title"][:60], e))
                    if "429" in str(e):
                        log("Wikimedia Commons asks us to slow down — leaving it for now.")
                        return got
            if not cont:
                break
        return got

    def ingest(self, n=6, max_mb=60):
        """Fetch example talking videos from the automatic sources in the background; the page then measures and learns."""
        job = {"id": hashlib.sha1(_now().encode()).hexdigest()[:10], "status": "running", "log": [], "ids": []}
        self.jobs = getattr(self, "jobs", {})
        self.jobs[job["id"]] = job
        log = lambda m: job["log"].append(m)

        def run():
            try:
                half = max(1, n // 2)
                job["ids"] += self._nasa(half, log, max_mb)
                job["ids"] += self._commons(n - len(job["ids"]), log, max_mb)
                log("Downloaded %d clip(s)." % len(job["ids"]))
                job["status"] = "done"
            except Exception as e:
                log("Stopped: %s" % e)
                job["status"] = "failed"
        threading.Thread(target=run, daemon=True).start()
        return {"job": job["id"]}

    def ingest_status(self, jid):
        j = getattr(self, "jobs", {}).get(jid)
        if not j:
            raise core.UserError("No such ingest job.")
        return j

    def pending(self):
        """Reference clips not yet measured (the page measures and learns them)."""
        rows = self.store.query("SELECT id FROM samples WHERE kind = 'reference' AND metrics IS NULL ORDER BY id")
        out = []
        for r in rows:
            x = self.get(r["id"])
            c = self.store.one("SELECT cues, lang FROM samples WHERE id = ?", (r["id"],))
            x["cues"] = json.loads(c["cues"] or "[]") if c else []
            x["lang"] = (c["lang"] if c else "") or "en"
            out.append(x)
        return out
