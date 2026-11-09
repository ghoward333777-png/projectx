"""Device gateway: one documented API through which cameras, phones, smart glasses, robots, wearables, motion suits,
eye trackers and microphones send QueryBook what they observe.

  * Every device is registered (by the admin, on this computer) and gets its own key; the key is shown once and only
    its SHA-256 is stored. Devices send events with   Authorization: Bearer qbd_...
  * Consent: a device that captures people, body signals or location is registered only with the subject's consent
    recorded, and events of a kind its consent does not cover are refused.
  * Facts, not recordings: events carry measurements and labels (heart rate, a fixation, an object seen, a sentence
    heard, a contact force) — never pictures or sound. Media files, when a device must send them, go to an inbox that
    the admin reviews; nothing is published anywhere.
  * Raw events are kept for a limited time (default 30 days); per-minute summaries and discrete observations stay.
  * Network listener (off by default): a second server on this computer's network address that answers ONLY the
    device endpoints (never the application pages), so robots and phones on the home network can send events.

Formats imported from files: Apple Health export (export.xml), ARKit face blendshapes CSV (e.g. Live Link Face),
Pupil Labs gaze/fixation CSV, BVH motion capture (Rokoko and others), and generic JSON-lines events.
"""
import base64, csv, datetime, hashlib, hmac, io, json, os, re, secrets, threading, time, urllib.parse
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import qbcore as core

VERSION = "1.0.0"
SCHEMA = ["""
CREATE TABLE devices (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, model TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE, token_hint TEXT NOT NULL,
  consent TEXT NOT NULL, subject TEXT, created TEXT NOT NULL, last_seen TEXT, events INTEGER NOT NULL DEFAULT 0,
  revoked TEXT, note TEXT);
CREATE TABLE events (
  id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL REFERENCES devices(id), t TEXT NOT NULL, received TEXT NOT NULL,
  kind TEXT NOT NULL, data TEXT NOT NULL, subject TEXT);
CREATE INDEX events_dev_t ON events(device_id, t);
CREATE INDEX events_kind_t ON events(kind, t);
CREATE TABLE observations (
  id INTEGER PRIMARY KEY, device_id INTEGER REFERENCES devices(id), t TEXT NOT NULL, kind TEXT NOT NULL, label TEXT NOT NULL,
  value TEXT, unit TEXT, detail TEXT, source TEXT NOT NULL);
CREATE INDEX obs_kind_t ON observations(kind, t);
CREATE INDEX obs_label ON observations(label);
CREATE TABLE minutes (
  device_id INTEGER NOT NULL, minute TEXT NOT NULL, kind TEXT NOT NULL, n INTEGER NOT NULL, sum REAL, min REAL, max REAL,
  PRIMARY KEY(device_id, minute, kind));
CREATE TABLE inbox (
  id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL REFERENCES devices(id), received TEXT NOT NULL, name TEXT NOT NULL,
  kind TEXT NOT NULL, bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, path TEXT NOT NULL, note TEXT);
"""]

# what each kind of event may carry, and which consent it needs (None = no person data)
KINDS = {
    "heart":      ("body",     "heart rate in beats per minute, optional rr_ms list"),
    "ecg":        ("body",     "ECG samples: fs (Hz) and uv (microvolts) — only a summary is kept"),
    "imu":        ("body",     "acceleration acc [x,y,z] m/s² and/or gyro [x,y,z] °/s"),
    "steps":      ("body",     "step count over an interval"),
    "gaze":       ("people",   "gaze point x,y (0–1 or px), optional fixation_ms and target label"),
    "face":       ("people",   "face blendshapes {name: 0–1} (ARKit names)"),
    "pose":       ("people",   "body joints {name: [x,y,z]} or summary values"),
    "transcript": ("people",   "text heard, optional lang and speaker"),
    "location":   ("location", "lat, lon, optional accuracy_m"),
    "detection":  (None,       "an object seen: label, optional confidence and box"),
    "touch":      (None,       "contact: force_n and/or contact_area_mm2, optional sensor and location"),
    "state":      (None,       "device telemetry: battery, temperature, mode …"),
    "note":       (None,       "free text from the operator"),
}
CONSENTS = ("people", "body", "location")

# the top devices: how each connects to QueryBook
CATALOG = [
    # id, name, category, captures, how, status
    ("insta360-link-2-pro", "Insta360 Link 2 Pro", "Webcam", [], "USB webcam (UVC): use it in the browser — Devices → Camera controls for pan, tilt and zoom; Language Builder → Face & video for lip reading and Object scan.", "built-in"),
    ("logitech-mx-brio", "Logitech MX Brio", "Webcam", [], "USB webcam (UVC): same as above; zoom control where the browser offers it.", "built-in"),
    ("iphone-17-pro", "Apple iPhone 17 Pro (Face ID camera)", "Selfie camera", ["people"], "ARKit face blendshapes: record with Live Link Face (or any app exporting ARKit CSV) and import the CSV here; live: a phone app posting 'face' events (bridges/iphone_arkit).", "import + bridge"),
    ("pixel-10-pro", "Google Pixel 10 Pro", "Selfie camera", ["people"], "Record video on the phone and import it in Language Builder → Face & video (2D face tracking runs on this computer).", "import"),
    ("ray-ban-meta-gen2", "Ray-Ban Meta (Gen 2)", "Smart glasses", ["people", "location"], "Meta Wearables Device Access Toolkit in a phone app: camera frames are analysed on the phone, and detections, transcripts and notes are posted here (bridges/meta_glasses).", "bridge"),
    ("meta-ray-ban-display", "Meta Ray-Ban Display", "Smart glasses", ["people", "location"], "As Ray-Ban Meta, plus the display API can show QueryBook answers in the lens (bridges/meta_glasses).", "bridge"),
    ("unitree-g1-edu", "Unitree G1 EDU Ultimate D", "Robot", ["people"], "unitree_sdk2 Python or ROS 2: bridges/unitree_bridge.py or bridges/ros2_bridge.py posts detections, touch, pose and state.", "bridge"),
    ("hello-robot-stretch-3", "Hello Robot Stretch 3", "Robot", ["people"], "ROS 2: bridges/ros2_bridge.py.", "bridge"),
    ("gelsight-mini", "GelSight Mini", "Touch sensor", [], "USB camera-based touch sensor: bridges/gelsight_bridge.py turns each touch into contact area and a force estimate.", "bridge"),
    ("unitree-go2-edu", "Unitree Go2 EDU", "Autonomous device", ["people", "location"], "unitree_sdk2 Python or ROS 2: bridges/unitree_bridge.py or bridges/ros2_bridge.py.", "bridge"),
    ("turtlebot-4", "Clearpath TurtleBot 4", "Autonomous device", ["people"], "ROS 2: bridges/ros2_bridge.py (camera detections, bumper touches, state).", "bridge"),
    ("polar-h10", "Polar H10", "Heart / ECG", ["body"], "Bluetooth heart rate straight from the browser (Devices → Connect heart-rate sensor); raw ECG: bridges/polar_bridge.py.", "built-in + bridge"),
    ("polar-verity-sense", "Polar Verity Sense", "Heart / motion", ["body"], "Bluetooth heart rate straight from the browser; motion: bridges/polar_bridge.py.", "built-in + bridge"),
    ("apple-watch-ultra-3", "Apple Watch Ultra 3", "Watch", ["body"], "Export from the Health app (Profile → Export All Health Data) and import export.xml here.", "import"),
    ("rokoko-smartsuit-pro-2", "Rokoko Smartsuit Pro II", "Motion suit", ["people", "body"], "Export BVH from Rokoko Studio and import it here; live: bridges/rokoko_bridge.py (Rokoko Studio Live JSON over UDP).", "import + bridge"),
    ("teslasuit", "Teslasuit", "Motion suit", ["people", "body"], "Use the generic event API from the Teslasuit SDK (pose, heart, touch events).", "API"),
    ("pupil-labs-neon", "Pupil Labs Neon", "Eye tracker", ["people"], "Import gaze.csv / fixations.csv from Pupil Cloud; live: bridges/pupil_neon_bridge.py (Realtime API).", "import + bridge"),
    ("tobii-pro-glasses-3", "Tobii Pro Glasses 3", "Eye tracker", ["people"], "bridges/tobii_bridge.py (Glasses 3 WebSocket API) posts gaze events.", "bridge"),
    ("dji-mic-2", "DJI Mic 2", "Microphone", ["people"], "Recordings (WAV/MP3) → Language Builder speech-to-text for long files; or post 'transcript' events.", "import"),
    ("rode-wireless-pro", "Rode Wireless PRO", "Microphone", ["people"], "As DJI Mic 2.", "import"),
    ("generic", "Any other device", "Other", [], "Post events in the documented format (GET /api/devices/openapi.json).", "API"),
]
CATALOG_BY_ID = {c[0]: c for c in CATALOG}

MAX_EVENTS = 2000            # per request
MAX_UPLOAD = 25 * 1024 * 1024
RETAIN_DAYS = 30


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


def _ts(v):
    """Event time: ISO 8601 text or Unix seconds (ms and ns accepted) → ISO UTC text."""
    if v in (None, ""):
        return _now()
    if isinstance(v, (int, float)):
        x = float(v)
        while x > 1e11:
            x /= 1000.0                              # ms / µs / ns
        return datetime.datetime.fromtimestamp(x, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-4] + "Z"
    s = str(v).strip()
    try:
        d = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        m = re.match(r"(\d{4}-\d\d-\d\d)[ T](\d\d:\d\d:\d\d)(?:\s*([+-]\d\d)(\d\d))?", s)
        if not m:
            raise ValueError("unreadable time %r" % s[:40])
        d = datetime.datetime.fromisoformat("%sT%s%s" % (m.group(1), m.group(2), (m.group(3) + ":" + m.group(4)) if m.group(3) else "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-4] + "Z"


def _num(v, lo=None, hi=None):
    x = float(v)
    if x != x or (lo is not None and x < lo) or (hi is not None and x > hi):
        raise ValueError("value out of range")
    return x


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Hub:
    def __init__(self, app_folder, app_id, log=None):
        self.app_id = app_id
        self.folder = os.path.join(app_folder, "devices")
        os.makedirs(os.path.join(self.folder, "inbox"), exist_ok=True)
        self.store = core.Store(self.folder, "devices", SCHEMA, log)
        self.log = log or (lambda *a: None)
        self.lan = None
        self._lock = threading.Lock()

    # -------------------------------------------------------------------------------- settings
    def _settings_path(self):
        return os.path.join(self.folder, "settings.json")

    def settings(self):
        try:
            with open(self._settings_path(), encoding="utf-8") as f:
                s = json.load(f)
        except (OSError, ValueError):
            s = {}
        return {"lan": bool(s.get("lan")), "retain_days": int(s.get("retain_days") or RETAIN_DAYS)}

    def save_settings(self, **kw):
        s = dict(self.settings(), **kw)
        tmp = self._settings_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f)
        os.replace(tmp, self._settings_path())
        return s

    # -------------------------------------------------------------------------------- devices
    def register(self, name, model, consent=None, subject=None, consent_confirmed=False, note=None):
        model = model if model in CATALOG_BY_ID else "generic"
        name = " ".join(str(name or "").split())[:80] or CATALOG_BY_ID[model][1]
        consent = sorted({c for c in (consent or []) if c in CONSENTS})
        if consent:
            if not consent_confirmed or not (subject or "").strip():
                raise core.UserError("This device records people, body signals or location: name the person recorded and confirm "
                                     "they agreed (consent) before registering it.")
        token = "qbd_" + secrets.token_urlsafe(24)
        with self.store.write() as db:
            did = db.execute("""INSERT INTO devices(name, model, token_hash, token_hint, consent, subject, created, note)
                                VALUES(?,?,?,?,?,?,?,?)""", (name, model, _hash(token), token[-4:], json.dumps(consent),
                                                            (subject or "").strip()[:120] or None, _now(), (note or "")[:300] or None)).lastrowid
        return {"id": did, "name": name, "model": model, "consent": consent, "token": token,
                "warning": "Copy this key now: it is shown only once. Send it as 'Authorization: Bearer <key>'."}

    def devices(self):
        out = self.store.query("SELECT id, name, model, token_hint, consent, subject, created, last_seen, events, revoked, note FROM devices ORDER BY id")
        for d in out:
            d["consent"] = json.loads(d["consent"])
            d["model_name"] = CATALOG_BY_ID.get(d["model"], CATALOG_BY_ID["generic"])[1]
        return out

    def revoke(self, did):
        with self.store.write() as db:
            n = db.execute("UPDATE devices SET revoked = ? WHERE id = ? AND revoked IS NULL", (_now(), int(did))).rowcount
        if not n:
            raise core.UserError("No such active device.")
        return {"ok": True}

    def authenticate(self, token):
        if not token or not token.startswith("qbd_"):
            return None
        d = self.store.one("SELECT * FROM devices WHERE token_hash = ?", (_hash(token),))
        if not d or d["revoked"] or not hmac.compare_digest(d["token_hash"], _hash(token)):
            return None
        d["consent"] = json.loads(d["consent"])
        return d

    def device(self, did):
        d = self.store.one("SELECT * FROM devices WHERE id = ?", (int(did),))
        if not d or d["revoked"]:
            raise core.UserError("No such active device.")
        d["consent"] = json.loads(d["consent"])
        return d

    # -------------------------------------------------------------------------------- ingest
    def _check(self, dev, ev):
        if not isinstance(ev, dict):
            raise ValueError("each event must be an object")
        kind = ev.get("kind")
        if kind not in KINDS:
            raise ValueError("unknown kind %r (allowed: %s)" % (kind, ", ".join(KINDS)))
        need = KINDS[kind][0]
        if need and need not in dev["consent"]:
            raise PermissionError("'%s' events need '%s' consent for this device" % (kind, need))
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {k: v for k, v in ev.items() if k not in ("kind", "t", "subject")}
        if kind == "heart":
            data = {"bpm": _num(data["bpm"], 20, 260), **({"rr_ms": [_num(x, 200, 3000) for x in data.get("rr_ms", [])][:60]} if data.get("rr_ms") else {})}
        elif kind == "ecg":
            uv = [float(x) for x in data.get("uv", [])][:20000]
            fs = _num(data.get("fs", 130), 1, 10000)
            data = {"fs": fs, "n": len(uv), "seconds": round(len(uv) / fs, 3),
                    "min_uv": min(uv) if uv else None, "max_uv": max(uv) if uv else None}     # summary only, samples discarded
        elif kind == "imu":
            data = {k: [_num(x, -1e4, 1e4) for x in data[k]][:3] for k in ("acc", "gyro") if isinstance(data.get(k), list)}
            if not data:
                raise ValueError("imu needs acc and/or gyro")
        elif kind == "steps":
            data = {"count": int(_num(data["count"], 0, 1e6)), **({"seconds": _num(data["seconds"], 0, 864000)} if data.get("seconds") else {})}
        elif kind == "gaze":
            data = {"x": _num(data["x"], -1e5, 1e5), "y": _num(data["y"], -1e5, 1e5),
                    **({"fixation_ms": _num(data["fixation_ms"], 0, 600000)} if data.get("fixation_ms") is not None else {}),
                    **({"target": str(data["target"])[:80]} if data.get("target") else {})}
        elif kind == "face":
            bs = data.get("blendshapes") or {}
            data = {"blendshapes": {str(k)[:40]: round(_num(v, -1, 2), 4) for k, v in list(bs.items())[:80]}}
            if not data["blendshapes"]:
                raise ValueError("face needs blendshapes")
        elif kind == "pose":
            js = data.get("joints") or {}
            data = {"joints": {str(k)[:40]: [round(_num(x, -1e5, 1e5), 4) for x in v][:3] for k, v in list(js.items())[:120] if isinstance(v, list)}}
        elif kind == "transcript":
            text = " ".join(str(data.get("text") or "").split())[:2000]
            if not text:
                raise ValueError("transcript needs text")
            data = {"text": text, **({"lang": str(data["lang"])[:12]} if data.get("lang") else {}),
                    **({"speaker": str(data["speaker"])[:60]} if data.get("speaker") else {})}
        elif kind == "location":
            data = {"lat": _num(data["lat"], -90, 90), "lon": _num(data["lon"], -180, 180),
                    **({"accuracy_m": _num(data["accuracy_m"], 0, 1e6)} if data.get("accuracy_m") is not None else {})}
        elif kind == "detection":
            label = " ".join(str(data.get("label") or "").split())[:80]
            if not label:
                raise ValueError("detection needs a label")
            data = {"label": label, **({"confidence": _num(data["confidence"], 0, 1)} if data.get("confidence") is not None else {}),
                    **({"box": [_num(x, -1e5, 1e5) for x in data["box"]][:4]} if isinstance(data.get("box"), list) else {})}
        elif kind == "touch":
            data = {**({"force_n": _num(data["force_n"], 0, 1e5)} if data.get("force_n") is not None else {}),
                    **({"contact_area_mm2": _num(data["contact_area_mm2"], 0, 1e6)} if data.get("contact_area_mm2") is not None else {}),
                    **({"sensor": str(data["sensor"])[:40]} if data.get("sensor") else {}),
                    **({"location": str(data["location"])[:60]} if data.get("location") else {})}
            if not data:
                raise ValueError("touch needs force_n or contact_area_mm2")
        elif kind == "state":
            data = {str(k)[:40]: (v if isinstance(v, (int, float, bool)) else str(v)[:80]) for k, v in list(data.items())[:30]}
        elif kind == "note":
            data = {"text": " ".join(str(data.get("text") or "").split())[:2000]}
        return kind, _ts(ev.get("t")), data, (str(ev["subject"])[:80] if ev.get("subject") else None)

    def ingest(self, dev, events, source="api"):
        if not isinstance(events, list) or not events:
            raise core.UserError("Send a non-empty list of events.")
        if len(events) > MAX_EVENTS:
            raise core.UserError("At most %d events per request." % MAX_EVENTS)
        ok, refused = [], []
        for i, ev in enumerate(events):
            try:
                ok.append(self._check(dev, ev))
            except PermissionError as e:
                refused.append({"index": i, "error": str(e)})
            except (KeyError, TypeError, ValueError) as e:
                refused.append({"index": i, "error": "invalid event: %s" % (e if not isinstance(e, KeyError) else "missing %s" % e)})
        now = _now()
        with self.store.write() as db:
            for kind, t, data, subject in ok:
                db.execute("INSERT INTO events(device_id, t, received, kind, data, subject) VALUES(?,?,?,?,?,?)",
                           (dev["id"], t, now, kind, json.dumps(data, ensure_ascii=False), subject))
                self._summarise(db, dev["id"], kind, t, data, subject, source)
            db.execute("UPDATE devices SET last_seen = ?, events = events + ? WHERE id = ?", (now, len(ok), dev["id"]))
        return {"accepted": len(ok), "refused": refused}

    def _minute(self, db, did, t, kind, value):
        db.execute("""INSERT INTO minutes(device_id, minute, kind, n, sum, min, max) VALUES(?,?,?,1,?,?,?)
                      ON CONFLICT(device_id, minute, kind) DO UPDATE SET n = n + 1, sum = sum + excluded.sum,
                      min = min(min, excluded.min), max = max(max, excluded.max)""", (did, t[:16], kind, value, value, value))

    def _obs(self, db, did, t, kind, label, value=None, unit=None, detail=None, source="api"):
        db.execute("INSERT INTO observations(device_id, t, kind, label, value, unit, detail, source) VALUES(?,?,?,?,?,?,?,?)",
                   (did, t, kind, label, None if value is None else str(value), unit, detail, source))

    def _summarise(self, db, did, kind, t, d, subject, source):
        """Keep what lasts: per-minute statistics for streams, an observation for discrete events."""
        if kind == "heart":
            self._minute(db, did, t, "heart_bpm", d["bpm"])
        elif kind == "imu" and "acc" in d:
            self._minute(db, did, t, "movement", sum(x * x for x in d["acc"]) ** 0.5)
        elif kind == "steps":
            self._minute(db, did, t, "steps", d["count"])
        elif kind == "gaze" and d.get("target"):
            self._obs(db, did, t, "gaze", d["target"], d.get("fixation_ms"), "ms", subject, source)
        elif kind == "face" and "jawOpen" in d["blendshapes"]:
            self._minute(db, did, t, "jaw_open", d["blendshapes"]["jawOpen"])
        elif kind in ("detection", "transcript", "note"):
            label = d.get("label") or d.get("text")
            self._obs(db, did, t, kind, label[:300], d.get("confidence"), None, subject, source)
        elif kind == "touch":
            self._obs(db, did, t, "touch", d.get("location") or d.get("sensor") or "contact", d.get("force_n"), "N" if d.get("force_n") is not None else None,
                      json.dumps(d), source)
        elif kind == "ecg":
            self._obs(db, did, t, "ecg", "ECG segment", d["seconds"], "s", "%d samples at %g Hz" % (d["n"], d["fs"]), source)
        elif kind == "location":
            self._obs(db, did, t, "location", "%.5f, %.5f" % (d["lat"], d["lon"]), d.get("accuracy_m"), "m", None, source)

    def upload(self, dev, name, kind, data_b64, note=None):
        if kind not in ("photo", "audio", "video", "file"):
            raise core.UserError("kind must be photo, audio, video or file")
        if kind in ("photo", "video", "audio") and "people" not in dev["consent"]:
            raise core.UserError("Photos, audio and video need 'people' consent for this device.")
        raw = base64.b64decode(data_b64 or "", validate=True)
        if not raw or len(raw) > MAX_UPLOAD:
            raise core.UserError("Upload is empty or larger than 25 MB.")
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(name or "upload"))[:80] or "upload"
        h = hashlib.sha256(raw).hexdigest()
        folder = os.path.join(self.folder, "inbox", str(dev["id"]))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "%s_%s" % (h[:12], safe))
        with open(path, "wb") as f:
            f.write(raw)
        with self.store.write() as db:
            iid = db.execute("INSERT INTO inbox(device_id, received, name, kind, bytes, sha256, path, note) VALUES(?,?,?,?,?,?,?,?)",
                             (dev["id"], _now(), safe, kind, len(raw), h, path, (note or "")[:300] or None)).lastrowid
        return {"id": iid, "sha256": h, "bytes": len(raw)}

    # -------------------------------------------------------------------------------- reading
    def observations(self, kind=None, device=None, label=None, since=None, limit=200):
        w, a = [], []
        for col, val in (("kind", kind), ("device_id", device), ("label", label)):
            if val not in (None, ""):
                w.append("%s = ?" % col); a.append(val)
        if since:
            w.append("t >= ?"); a.append(_ts(since))
        sql = "SELECT * FROM observations" + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY t DESC LIMIT ?"
        return self.store.query(sql, a + [min(int(limit or 200), 5000)])

    def minutes(self, device=None, kind=None, since=None, limit=1440):
        w, a = [], []
        if device:
            w.append("device_id = ?"); a.append(int(device))
        if kind:
            w.append("kind = ?"); a.append(kind)
        if since:
            w.append("minute >= ?"); a.append(_ts(since)[:16])
        rows = self.store.query("SELECT * FROM minutes" + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY minute DESC LIMIT ?",
                                a + [min(int(limit or 1440), 20000)])
        for r in rows:
            r["mean"] = round(r["sum"] / r["n"], 3) if r["n"] else None
        return rows

    def last_seen(self, label):
        r = self.store.one("SELECT * FROM observations WHERE kind IN ('detection', 'gaze') AND lower(label) = lower(?) ORDER BY t DESC LIMIT 1", (label,))
        return r

    def summary(self):
        st = self.store
        return {"version": VERSION, "devices": self.devices(), "settings": self.settings(), "lan": self.lan_status(),
                "counts": st.query("SELECT kind, count(*) AS n, max(t) AS last FROM events GROUP BY kind ORDER BY kind"),
                "inbox": st.query("SELECT id, device_id, received, name, kind, bytes FROM inbox ORDER BY id DESC LIMIT 50"),
                "latest_heart": st.one("SELECT device_id, minute, round(sum / n, 1) AS bpm FROM minutes WHERE kind = 'heart_bpm' ORDER BY minute DESC LIMIT 1")}

    def prune(self):
        days = self.settings()["retain_days"]
        cut = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        with self.store.write() as db:
            n = db.execute("DELETE FROM events WHERE t < ?", (cut,)).rowcount
        return {"pruned": n, "older_than_days": days}

    # -------------------------------------------------------------------------------- file imports
    def import_file(self, dev, fmt, text=None, path=None, data_b64=None):
        if path:
            path = os.path.abspath(os.path.expanduser(path))
            if not os.path.isfile(path):
                raise core.UserError("No such file.")
        elif data_b64:
            text = base64.b64decode(data_b64).decode("utf-8-sig", "replace")
        elif text is None:
            raise core.UserError("Give the file's text or its path on this computer.")
        fn = {"apple-health": self._apple_health, "arkit-csv": self._arkit_csv, "pupil-csv": self._pupil_csv,
              "bvh": self._bvh, "jsonl": self._jsonl}.get(fmt)
        if not fn:
            raise core.UserError("Unknown format. Use apple-health, arkit-csv, pupil-csv, bvh or jsonl.")
        return fn(dev, text, path)

    def _open(self, text, path):
        return open(path, encoding="utf-8-sig", errors="replace") if path else io.StringIO(text)

    def _apple_health(self, dev, text, path):
        if "body" not in dev["consent"]:
            raise core.UserError("Apple Health data needs 'body' consent for this device.")
        types = {"HKQuantityTypeIdentifierHeartRate": ("heart_bpm", 1.0), "HKQuantityTypeIdentifierRestingHeartRate": ("resting_bpm", 1.0),
                 "HKQuantityTypeIdentifierStepCount": ("steps", 1.0), "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": ("hrv_ms", 1.0),
                 "HKQuantityTypeIdentifierActiveEnergyBurned": ("active_kcal", 1.0), "HKQuantityTypeIdentifierOxygenSaturation": ("spo2_pct", 100.0)}
        days, n = {}, 0
        src = open(path, "rb") if path else io.BytesIO(text.encode("utf-8"))
        with src:
            for _, el in ET.iterparse(src, events=("end",)):
                if el.tag == "Record" and el.get("type") in types:
                    key, scale = types[el.get("type")]
                    try:
                        v = float(el.get("value")) * scale
                        day = _ts(el.get("startDate"))[:10]
                    except (TypeError, ValueError):
                        el.clear()
                        continue
                    agg = days.setdefault((day, key), [0, 0.0, None, None])
                    agg[0] += 1; agg[1] += v
                    agg[2] = v if agg[2] is None else min(agg[2], v)
                    agg[3] = v if agg[3] is None else max(agg[3], v)
                    n += 1
                el.clear()
        with self.store.write() as db:
            for (day, key), (c, s, lo, hi) in sorted(days.items()):
                value = round(s, 1) if key in ("steps", "active_kcal") else round(s / c, 1)
                self._obs(db, dev["id"], day + "T00:00:00Z", "daily", key, value, None, "%d readings, min %g, max %g" % (c, lo, hi), "apple-health")
        return {"records": n, "days": len({d for d, _ in days}), "observations": len(days)}

    def _arkit_csv(self, dev, text, path):
        if "people" not in dev["consent"]:
            raise core.UserError("Face data needs 'people' consent for this device.")
        with self._open(text, path) as f:
            rows = list(csv.reader(f))
        if len(rows) < 2:
            raise core.UserError("The CSV has no frames.")
        head = [h.strip() for h in rows[0]]
        canon = {}
        for i, h in enumerate(head):
            k = h[0].lower() + h[1:] if h else h
            if k in ARKIT:
                canon[i] = k
        if "jawOpen" not in canon.values():
            raise core.UserError("No ARKit blendshape columns found (expected names like JawOpen, EyeBlinkLeft).")
        frames, jaw, blinks, closed = 0, [], 0, False
        for r in rows[1:]:
            try:
                vals = {canon[i]: float(r[i]) for i in canon if i < len(r) and r[i] != ""}
            except ValueError:
                continue
            frames += 1
            jaw.append(vals.get("jawOpen", 0.0))
            b = (vals.get("eyeBlinkLeft", 0.0) + vals.get("eyeBlinkRight", 0.0)) / 2
            if b > 0.5 and not closed:
                blinks += 1
            closed = b > 0.5
        t = _now()
        with self.store.write() as db:
            self._obs(db, dev["id"], t, "face", "face recording", frames, "frames",
                      "%d ARKit channels; mean jawOpen %.3f, max %.3f; %d blinks" % (len(canon), sum(jaw) / len(jaw), max(jaw), blinks), "arkit-csv")
        return {"frames": frames, "channels": len(canon), "blinks": blinks, "jaw_open_mean": round(sum(jaw) / len(jaw), 4)}

    def _pupil_csv(self, dev, text, path):
        if "people" not in dev["consent"]:
            raise core.UserError("Gaze data needs 'people' consent for this device.")
        with self._open(text, path) as f:
            rd = csv.DictReader(f)
            cols = [c.strip().lower() for c in (rd.fieldnames or [])]
            rows = list(rd)
        if any("fixation id" in c for c in cols):
            durs = []
            for r in rows:
                rr = {k.strip().lower(): v for k, v in r.items() if k}
                try:
                    durs.append(float(rr.get("duration [ms]") or 0))
                except ValueError:
                    pass
            with self.store.write() as db:
                self._obs(db, dev["id"], _now(), "gaze", "fixations", len(durs), "fixations",
                          "mean %.0f ms, total %.1f s" % (sum(durs) / max(1, len(durs)), sum(durs) / 1000), "pupil-csv")
            return {"fixations": len(durs), "total_s": round(sum(durs) / 1000, 2)}
        if any(c.startswith("gaze x") for c in cols):
            ts = []
            for r in rows:
                rr = {k.strip().lower(): v for k, v in r.items() if k}
                try:
                    ts.append(float(rr.get("timestamp [ns]")))
                except (TypeError, ValueError):
                    pass
            secs = (max(ts) - min(ts)) / 1e9 if len(ts) > 1 else 0
            with self.store.write() as db:
                self._obs(db, dev["id"], _ts(min(ts)) if ts else _now(), "gaze", "gaze recording", round(secs, 1), "s",
                          "%d gaze samples (%.0f Hz)" % (len(ts), len(ts) / secs if secs else 0), "pupil-csv")
            return {"samples": len(ts), "seconds": round(secs, 2)}
        raise core.UserError("Not a Pupil Labs gaze.csv or fixations.csv.")

    def _bvh(self, dev, text, path):
        with self._open(text, path) as f:
            src = f.read()
        if "HIERARCHY" not in src or "MOTION" not in src:
            raise core.UserError("Not a BVH motion-capture file.")
        head, motion = src.split("MOTION", 1)
        joints = re.findall(r"(?:ROOT|JOINT)\s+(\S+)", head)
        chans = [int(x) for x in re.findall(r"CHANNELS\s+(\d+)", head)]
        m_frames = re.search(r"Frames:\s*(\d+)", motion)
        m_time = re.search(r"Frame Time:\s*([\d.eE+-]+)", motion)
        if not (joints and m_frames and m_time):
            raise core.UserError("BVH header incomplete.")
        lines = [l for l in motion.split("Frame Time:", 1)[1].split("\n")[1:] if l.strip()]
        travel, prev = 0.0, None
        for l in lines:
            v = l.split()
            if len(v) >= 3:
                p = [float(x) for x in v[:3]]
                if prev:
                    travel += sum((a - b) ** 2 for a, b in zip(p, prev)) ** 0.5
                prev = p
        frames, ft = int(m_frames.group(1)), float(m_time.group(1))
        with self.store.write() as db:
            self._obs(db, dev["id"], _now(), "pose", "motion capture", round(frames * ft, 2), "s",
                      "%d joints, %d channels, %d frames at %.0f fps, root travel %.1f units" % (len(joints), sum(chans), frames, 1 / ft if ft else 0, travel), "bvh")
        return {"joints": len(joints), "frames": frames, "seconds": round(frames * ft, 3), "root_travel": round(travel, 2)}

    def _jsonl(self, dev, text, path):
        with self._open(text, path) as f:
            events = [json.loads(l) for l in f if l.strip()]
        out = {"accepted": 0, "refused": []}
        for i in range(0, len(events), MAX_EVENTS):
            r = self.ingest(dev, events[i:i + MAX_EVENTS], "jsonl")
            out["accepted"] += r["accepted"]
            out["refused"] += r["refused"]
        return out

    # -------------------------------------------------------------------------------- network listener (devices only)
    def lan_status(self):
        if not self.lan:
            return {"running": False}
        return {"running": True, "port": self.lan.server_address[1], "addresses": _local_addresses()}

    def start_lan(self, port):
        if self.lan:
            return self.lan_status()
        hub = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "QueryBookDevices"

            def log_message(self, *a):
                pass

            def _send(self, code, body):
                b = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                p = urllib.parse.urlsplit(self.path).path
                if p == "/api/devices/ping":
                    dev = hub.authenticate(_bearer(self.headers))
                    return self._send(200 if dev else 401, {"ok": bool(dev), "device": dev and dev["name"]})
                if p == "/api/devices/openapi.json":
                    return self._send(200, openapi())
                self._send(404, {"error": "Only the device API is available on the network."})

            def do_POST(self):
                p = urllib.parse.urlsplit(self.path).path
                if p not in ("/api/devices/ingest", "/api/devices/upload"):
                    return self._send(404, {"error": "Only the device API is available on the network."})
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_UPLOAD * 4 // 3 + 4096:
                    return self._send(413, {"error": "Too large."})
                try:
                    body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                    out = device_call(hub, p, body, _bearer(self.headers), local=False)
                    self._send(200, out)
                except PermissionError as e:
                    self._send(401, {"error": str(e)})
                except core.UserError as e:
                    self._send(400, {"error": str(e)})
                except (ValueError, TypeError) as e:
                    self._send(400, {"error": "Bad request: %s" % e})

        srv = ThreadingHTTPServer(("0.0.0.0", port), H)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.lan = srv
        self.log("device listener on the network, port", port)
        return self.lan_status()

    def stop_lan(self):
        if self.lan:
            self.lan.shutdown()
            self.lan.server_close()
            self.lan = None
        return {"running": False}


ARKIT = {n for n in """browDownLeft browDownRight browInnerUp browOuterUpLeft browOuterUpRight cheekPuff cheekSquintLeft cheekSquintRight
eyeBlinkLeft eyeBlinkRight eyeLookDownLeft eyeLookDownRight eyeLookInLeft eyeLookInRight eyeLookOutLeft eyeLookOutRight eyeLookUpLeft
eyeLookUpRight eyeSquintLeft eyeSquintRight eyeWideLeft eyeWideRight jawForward jawLeft jawOpen jawRight mouthClose mouthDimpleLeft
mouthDimpleRight mouthFrownLeft mouthFrownRight mouthFunnel mouthLeft mouthLowerDownLeft mouthLowerDownRight mouthPressLeft
mouthPressRight mouthPucker mouthRight mouthRollLower mouthRollUpper mouthShrugLower mouthShrugUpper mouthSmileLeft mouthSmileRight
mouthStretchLeft mouthStretchRight mouthUpperUpLeft mouthUpperUpRight noseSneerLeft noseSneerRight tongueOut""".split()}


def _bearer(headers):
    a = headers.get("Authorization") or ""
    return a[7:].strip() if a.lower().startswith("bearer ") else (headers.get("X-QB-Device-Token") or "").strip()


def _local_addresses():
    import socket
    out = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))                  # no packet is sent; this only picks the outgoing interface
        out.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(out)


def device_call(hub, path, body, token, local=True):
    """The device endpoints, shared by the application server (this computer) and the network listener."""
    dev = hub.authenticate(token) if token else None
    if dev is None:
        if local and body.get("device_id"):
            dev = hub.device(body["device_id"])       # the application's own page on this computer
        else:
            raise PermissionError("Missing or revoked device key.")
    if path.endswith("/ingest"):
        return hub.ingest(dev, body.get("events"))
    if path.endswith("/upload"):
        return hub.upload(dev, body.get("name"), body.get("kind"), body.get("data_b64"), body.get("note"))
    raise core.UserError("No such device action.")


def openapi():
    ev_kinds = {k: v[1] + (" (needs '%s' consent)" % v[0] if v[0] else "") for k, v in KINDS.items()}
    return {
        "openapi": "3.0.3",
        "info": {"title": "QueryBook device API", "version": VERSION,
                 "description": "Send observations from cameras, glasses, robots, wearables and other devices to QueryBook. "
                                "Register the device in QueryBook (Devices tab) to get its key. Event kinds: " +
                                "; ".join("%s — %s" % kv for kv in ev_kinds.items())},
        "components": {"securitySchemes": {"deviceKey": {"type": "http", "scheme": "bearer", "description": "qbd_… device key"}},
                       "schemas": {"Event": {"type": "object", "required": ["kind"], "properties": {
                           "kind": {"type": "string", "enum": list(KINDS)},
                           "t": {"description": "ISO 8601 time or Unix seconds/ms/ns; default: now", "oneOf": [{"type": "string"}, {"type": "number"}]},
                           "subject": {"type": "string", "description": "who or what the event is about (optional)"},
                           "data": {"type": "object", "description": "fields for the kind, e.g. {\"bpm\": 72} or {\"label\": \"cup\", \"confidence\": 0.9}"}}}}},
        "security": [{"deviceKey": []}],
        "paths": {
            "/api/devices/ingest": {"post": {"summary": "Send events (at most %d per request)" % MAX_EVENTS,
                "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "required": ["events"],
                    "properties": {"events": {"type": "array", "items": {"$ref": "#/components/schemas/Event"}}}}}}},
                "responses": {"200": {"description": "accepted count and refused events with reasons"}, "401": {"description": "bad key"}}}},
            "/api/devices/upload": {"post": {"summary": "Send one media file (≤ 25 MB) to the admin's inbox",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "required": ["name", "kind", "data_b64"],
                    "properties": {"name": {"type": "string"}, "kind": {"type": "string", "enum": ["photo", "audio", "video", "file"]},
                                   "data_b64": {"type": "string", "format": "byte"}, "note": {"type": "string"}}}}}},
                "responses": {"200": {"description": "stored, with SHA-256"}}}},
            "/api/devices/ping": {"get": {"summary": "Check the key", "responses": {"200": {"description": "key valid"}, "401": {"description": "bad key"}}}},
        },
    }


def add_routes(api, hub):
    @api.get("/api/devices/catalog")
    def catalog(p):
        return {"devices": [{"id": c[0], "name": c[1], "category": c[2], "captures": c[3], "how": c[4], "status": c[5]} for c in CATALOG],
                "kinds": {k: {"consent": v[0], "fields": v[1]} for k, v in KINDS.items()}}

    @api.get("/api/devices/status")
    def status(p):
        return hub.summary()

    @api.get("/api/devices/openapi.json")
    def spec(p):
        return openapi()

    @api.post("/api/devices/register")
    def register(p):
        _admin(hub, p)
        return hub.register(p.get("name"), p.get("model"), p.get("consent"), p.get("subject"), bool(p.get("consent_confirmed")), p.get("note"))

    @api.post("/api/devices/revoke")
    def revoke(p):
        _admin(hub, p)
        return hub.revoke(p.get("id"))

    @api.post("/api/devices/ingest")
    def ingest(p):
        return _call(hub, "/api/devices/ingest", p)

    @api.post("/api/devices/upload")
    def upload(p):
        return _call(hub, "/api/devices/upload", p)

    @api.get("/api/devices/ping")
    def ping(p):
        return {"ok": True, "version": VERSION}

    @api.post("/api/devices/import")
    def imp(p):
        return hub.import_file(hub.device(p.get("device_id")), p.get("format"), p.get("text"), p.get("path"), p.get("data_b64"))

    @api.post("/api/devices/observations")
    def obs(p):
        return {"observations": hub.observations(p.get("kind"), p.get("device"), p.get("label"), p.get("since"), p.get("limit"))}

    @api.post("/api/devices/minutes")
    def mins(p):
        return {"minutes": hub.minutes(p.get("device"), p.get("kind"), p.get("since"), p.get("limit"))}

    @api.post("/api/devices/last_seen")
    def last(p):
        return {"observation": hub.last_seen(p.get("label") or "")}

    @api.post("/api/devices/settings")
    def settings(p):
        if p.get("lan") in (True, False):
            _admin(hub, p)
            hub.save_settings(lan=p["lan"])
            if p["lan"]:
                hub.start_lan(hub.lan_port)
            else:
                hub.stop_lan()
        if p.get("retain_days"):
            hub.save_settings(retain_days=max(1, min(3650, int(p["retain_days"]))))
        return hub.summary()

    @api.post("/api/devices/prune")
    def prune(p):
        return hub.prune()


def _call(hub, path, p):
    try:
        return device_call(hub, path, p, p.pop("_token", None) or p.get("token"), local=True)
    except PermissionError as e:
        raise core.UserError(str(e))


def _admin(hub, p):
    ap = getattr(hub, "approvals", None)
    if ap is not None and ap.admin_set():
        ap._require(p.get("passphrase") or "")


def attach(app, app_id, port):
    """Give an application the device gateway. Never stops the application if it cannot be opened."""
    try:
        app.devices = Hub(app.folder, app_id, app.log)
        app.devices.lan_port = port + 1000
        app.devices.approvals = getattr(getattr(app, "commons", None), "approvals", None)
        add_routes(app.api, app.devices)
    except Exception as e:
        app.log("device gateway unavailable:", repr(e))
        app.devices = None
    return app.devices


def start(app):
    """At application start: open the network listener if the admin turned it on, and prune old raw events."""
    hub = getattr(app, "devices", None)
    if not hub:
        return
    try:
        hub.prune()
        if hub.settings()["lan"]:
            hub.start_lan(hub.lan_port)
    except Exception as e:
        app.log("device listener:", repr(e))
