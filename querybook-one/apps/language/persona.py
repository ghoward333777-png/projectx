"""Author Persona: an AI narrator that looks and sounds like a QueryBook's author — only with the author's consent.

A persona holds the author's photo (with its face landmarks), a voice sample and a signed consent record
(who, when, for what, and fingerprints of the samples). Its voice can be any of:
  * google_custom — Google Cloud Text-to-Speech custom (cloned) voice, built from the sample;
  * elevenlabs    — ElevenLabs instant voice clone, built from the sample;
  * offline       — the built-in voice tuned (generate → measure → adjust) to the sample's pitch, speed,
                    loudness and breath: free and private, recognisably synthetic.
Its face can be produced by any of:
  * photo   — the author's photo animated in the browser (bundled face tracker, mesh warp; free, offline);
  * heygen  — HeyGen talking-photo video (cloud, needs a key);
  * did     — D-ID talk video (cloud, needs a key);
  * local   — a locally installed open-source model (Wav2Lip, SadTalker or any command) — private, needs a GPU.
Everything a persona produces is labelled "AI narrator". Deleting a persona deletes its local samples and
voice references (copies held by a cloud provider must be deleted there; the page says so).
"""
import base64, datetime, glob, hashlib, json, os, shlex, shutil, subprocess, threading, time, uuid

import tts
import voicedsp

SCHEMA = """
CREATE TABLE IF NOT EXISTS personas (
  id INTEGER PRIMARY KEY,
  created TEXT NOT NULL,
  name TEXT NOT NULL,
  consent TEXT NOT NULL,                 -- JSON: signer, statement, date, purposes, sha256 of photo and sample
  photo TEXT,                            -- file in persona/<id>/
  landmarks TEXT,                        -- JSON [[x, y], …] normalised face landmarks of the photo (from the browser tracker)
  sample TEXT,                           -- the voice sample file
  voice TEXT,                            -- JSON: method, engine, voice, model, profile
  face TEXT,                             -- JSON: method and its settings
  reference TEXT                         -- JSON: the perfect-sample analysis (Photo Real Lab)
);
CREATE TABLE IF NOT EXISTS narrations (
  id INTEGER PRIMARY KEY,
  created TEXT NOT NULL,
  persona INTEGER NOT NULL,
  text TEXT NOT NULL,
  face_method TEXT, voice_method TEXT,
  audio TEXT,                            -- speech audio file name
  video TEXT,                            -- MP4 in persona/<id>/ (cloud and local methods)
  status TEXT NOT NULL,                  -- queued / working / done / failed
  detail TEXT,
  seconds REAL,
  score TEXT                             -- JSON: Photo Real Lab realism measurement, when measured
);
"""

VOICE_METHODS = {"google_custom": "Google custom (cloned) voice", "elevenlabs": "ElevenLabs voice clone", "offline": "Offline approximation (built-in voice tuned to the sample)"}
FACE_METHODS = {"photo": "Photo-driven, in this app (free, offline)", "heygen": "HeyGen talking photo (cloud)", "did": "D-ID talk (cloud)",
                "local": "Local AI model (Wav2Lip / SadTalker / your command)"}
CONSENT_TEXT = ("I, {signer}, am the person whose face and voice are in these samples (or I hold their written permission). "
                "I allow this QueryBook to create an AI narrator that looks and sounds like {name}, to narrate QueryBook content. "
                "Everything it produces will be labelled as AI-generated. I can withdraw this by deleting the persona.")
LOCAL_PRESETS = {
    "wav2lip": "python {repo}/inference.py --checkpoint_path {repo}/checkpoints/wav2lip_gan.pth --face {face} --audio {audio} --outfile {out}",
    "sadtalker": "python {repo}/inference.py --driven_audio {audio} --source_image {face} --result_dir {outdir} --still --preprocess full",
}
LABEL = "AI narrator — generated with consent"


def photo_check(landmarks):
    """What makes a single photo animate well: mouth closed, facing the camera. Returns the problems found."""
    if not landmarks or len(landmarks) < 400:
        return ["no face landmarks — use a clear, front-facing photo"]
    P = lambda i: landmarks[i]
    d = lambda a, b: ((P(a)[0] - P(b)[0]) ** 2 + (P(a)[1] - P(b)[1]) ** 2) ** 0.5
    out = []
    if d(13, 14) > 0.08 * d(61, 291):
        out.append("the mouth is open in the photo (lips %.0f%% apart) — a closed, neutral mouth animates far more realistically" % (100 * d(13, 14) / d(61, 291)))
    r = (P(1)[0] - P(234)[0]) / ((P(454)[0] - P(234)[0]) or 1e-6)
    if abs(r - 0.5) > 0.12:
        out.append("the face is turned to one side — face the camera")
    return out


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-4]


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _multipart(fields, files):
    """multipart/form-data body: fields {name: value}, files [(field, filename, content_type, bytes)]."""
    bnd = "----qb" + uuid.uuid4().hex
    out = b""
    for k, v in fields.items():
        out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (bnd, k, v)).encode()
    for k, fn, ct, data in files:
        out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n" % (bnd, k, fn, ct)).encode() + data + b"\r\n"
    return out + ("--%s--\r\n" % bnd).encode(), "multipart/form-data; boundary=" + bnd


class Personas:
    def __init__(self, store, speech, folder):
        self.store, self.speech = store, speech
        self.dir = os.path.join(folder, "persona")
        os.makedirs(self.dir, exist_ok=True)
        self.keys = speech.keys
        self.lock = threading.Lock()

    # ---------------------------------------------------------------- files
    def _pdir(self, pid):
        d = os.path.join(self.dir, str(int(pid)))
        os.makedirs(d, exist_ok=True)
        return d

    def file_path(self, pid, name):
        p = os.path.normpath(os.path.join(self._pdir(pid), os.path.basename(name or "")))
        if not os.path.isfile(p):
            raise FileNotFoundError(name)
        return p

    # ---------------------------------------------------------------- create / read / delete
    def create(self, name, signer, consent, photo, sample, lang="en", landmarks=None, on_behalf=False):
        name, signer = " ".join(str(name or "").split()), " ".join(str(signer or "").split())
        if not name:
            raise ValueError("Give the author's name.")
        if not consent or not signer:
            raise ValueError("The author must agree to the consent statement and type their full name.")
        if signer.lower() != name.lower() and not on_behalf:
            raise ValueError("The signer must be the author (%s), or tick 'I hold the author's written permission'." % name)
        if not photo or not sample:
            raise ValueError("A photo of the author and a voice sample are both needed.")
        if not voicedsp.is_wav(sample):
            raise ValueError("The voice sample must be WAV (the page records WAV).")
        dur = voicedsp.measure(sample)["duration_s"]
        if dur < 10:
            raise ValueError("The voice sample is %.1f s; at least 10 s (30–120 s is best) of the author reading aloud is needed." % dur)
        rec = {"signer": signer, "on_behalf": bool(on_behalf), "statement": CONSENT_TEXT.format(signer=signer, name=name), "date_utc": _now(),
               "purposes": ["narration of QueryBook content"], "label": LABEL, "photo_sha256": _sha(photo), "sample_sha256": _sha(sample)}
        with self.store.write() as db:
            pid = db.execute("INSERT INTO personas(created, name, consent, voice, face) VALUES(?,?,?,?,?)",
                             (_now(), name, json.dumps(rec), json.dumps({"method": "offline", "lang": lang}), json.dumps({"method": "photo"}))).lastrowid
        d = self._pdir(pid)
        with open(os.path.join(d, "photo.jpg"), "wb") as f:
            f.write(photo)
        with open(os.path.join(d, "sample.wav"), "wb") as f:
            f.write(sample)
        with self.store.write() as db:
            db.execute("UPDATE personas SET photo = 'photo.jpg', sample = 'sample.wav', landmarks = ? WHERE id = ?",
                       (json.dumps(landmarks) if landmarks else None, pid))
        self.store.activity("Author narrator: persona created", "ok", "%s (consent signed by %s)" % (name, signer))
        return self.get(pid)

    def get(self, pid):
        rows = self.store.query("SELECT * FROM personas WHERE id = ?", (int(pid),))
        if not rows:
            raise ValueError("No such persona.")
        r = rows[0]
        for k in ("consent", "voice", "face", "landmarks", "reference"):
            r[k] = json.loads(r[k]) if r.get(k) else None
        r["label"] = LABEL
        r["photo_check"] = photo_check(r.get("landmarks"))
        return r

    def list(self):
        out = []
        for r in self.store.query("SELECT id FROM personas ORDER BY id"):
            p = self.get(r["id"])
            p.pop("landmarks", None)
            out.append(p)
        return out

    def set_landmarks(self, pid, landmarks):
        if not isinstance(landmarks, list) or len(landmarks) < 400:
            raise ValueError("Face landmarks were not found in the photo — use a clear, front-facing photo.")
        with self.store.write() as db:
            db.execute("UPDATE personas SET landmarks = ? WHERE id = ?", (json.dumps([[round(float(x), 5), round(float(y), 5)] for x, y, *_ in landmarks]), int(pid)))
        return {"ok": True}

    def delete(self, pid):
        p = self.get(pid)
        if p["voice"] and p["voice"].get("method") == "google_custom" and p["voice"].get("voice", "").startswith("custom:"):
            cfg = self.keys._load()
            (cfg.get("google_cloud") or {}).get("custom_voices", {}).pop(p["voice"]["voice"][7:], None)
            self.keys._write(cfg)
        shutil.rmtree(self._pdir(pid), ignore_errors=True)
        with self.store.write() as db:
            db.execute("DELETE FROM personas WHERE id = ?", (int(pid),))
            db.execute("DELETE FROM narrations WHERE persona = ?", (int(pid),))
        self.store.activity("Author narrator: persona deleted", "ok", p["name"])
        note = {"elevenlabs": "Also delete the voice “%s” in your ElevenLabs account." % p["voice"].get("voice"),
                "google_custom": "The Google cloning key was removed from this computer."}.get((p["voice"] or {}).get("method"), "")
        return {"deleted": True, "note": note}

    # ---------------------------------------------------------------- the real-mouth library (from the perfect sample)
    def set_library(self, pid, items):
        """Store the author's own frames for each sound (chosen by the Photo Real Lab from the perfect sample)."""
        p = self.get(pid)
        ref = p.get("reference")
        if not ref:
            raise ValueError("Record the perfect sample first.")
        lib = {}
        for it in items or []:
            v = str(it.get("v") or "")
            if v not in (ref.get("keyframes") or {}) or not it.get("image_b64") or not isinstance(it.get("landmarks"), list) or len(it["landmarks"]) < 400:
                continue
            img = base64.b64decode(str(it["image_b64"]).split(",", 1)[-1])
            if img[:2] != b"\xff\xd8":
                continue
            fn = "lib-%s.jpg" % v
            with open(os.path.join(self._pdir(pid), fn), "wb") as f:
                f.write(img)
            lib[v] = {"file": fn, "landmarks": [[round(float(x), 5), round(float(y), 5)] for x, y, *_ in it["landmarks"]]}
        if "rest" not in lib:
            raise ValueError("The rest frame (mouth closed) could not be taken from the sample.")
        ref["library"] = lib
        with self.store.write() as db:
            db.execute("UPDATE personas SET reference = ? WHERE id = ?", (json.dumps(ref), int(pid)))
        self.store.activity("Author narrator: real-mouth library", "ok", "%s · %d frames of the author's own mouth" % (p["name"], len(lib)))
        return {"frames": sorted(lib), "count": len(lib)}

    # ---------------------------------------------------------------- voice
    def set_voice(self, pid, method, lang="en"):
        p = self.get(pid)
        if method not in VOICE_METHODS:
            raise ValueError("Unknown voice method.")
        with open(self.file_path(pid, p["sample"]), "rb") as f:
            sample = f.read()
        v = {"method": method, "lang": lang}
        if method == "google_custom":
            nm = "author-%d" % int(pid)
            tts.BY_ID["google_cloud"].build_custom_voice(self.keys, nm, sample, True, tts.SPEECH_LANG.get(lang, "en-US"))
            v.update({"engine": "google_cloud", "voice": "custom:" + nm, "model": ""})
        elif method == "elevenlabs":
            if not self.keys.configured("elevenlabs"):
                raise ValueError("Add an ElevenLabs API key (Speech → Voice providers) first.")
            body, ct = _multipart({"name": "QueryBook author: %s" % p["name"], "description": "AI narrator voice, created with the author's consent"},
                                  [("files", "sample.wav", "audio/wav", sample)])
            raw, _ = tts._http(tts._base("elevenlabs", "https://api.elevenlabs.io") + "/v1/voices/add", body,
                               {"xi-api-key": self.keys.get("elevenlabs")["api_key"], "Content-Type": ct}, timeout=120)
            vid = json.loads(raw).get("voice_id")
            if not vid:
                raise RuntimeError("ElevenLabs returned no voice id")
            v.update({"engine": "elevenlabs", "voice": vid, "model": "eleven_multilingual_v2"})
        else:
            m = voicedsp.measure(sample)
            target = {"pitch_hz": m["pitch"].get("mean_hz") or 140, "rate_syl_s": m["rate"]["articulation_rate_syl_s"] or 4.5,
                      "volume_dbfs": m["volume"]["mean_dbfs"]}
            gender = "female" if (m["pitch"].get("mean_hz") or 140) >= 165 else "male"
            res = self.speech.match("The quick brown fox jumps over the lazy dog, and then rests in the warm sun.", target,
                                    {"lang": lang, "gender": gender}, "espeak", max_rounds=5)
            prof = dict(res.get("final_profile") or {}, lang=lang, gender=gender)
            v.update({"engine": "espeak", "voice": "", "model": "", "profile": prof, "target": target, "matched": res.get("matched")})
        with self.store.write() as db:
            db.execute("UPDATE personas SET voice = ? WHERE id = ?", (json.dumps(v), int(pid)))
        self.store.activity("Author narrator: voice", "ok", "%s — %s" % (p["name"], VOICE_METHODS[method]))
        return v

    def speak(self, pid, text, emotion=None):
        """The narration audio in the persona's voice (falls back to the offline voice if the clone fails, and says so)."""
        p = self.get(pid)
        v = p["voice"] or {"method": "offline"}
        prof = dict(v.get("profile") or {}, lang=v.get("lang", "en"))
        if emotion:
            prof["emotion"] = emotion
        g = self.speech.generate(text, prof, v.get("engine") or "espeak", v.get("voice") or "", v.get("model") or "", None, measure=False,
                                 quiet_label="narrator %s: " % p["name"])
        return g

    # ---------------------------------------------------------------- face
    def set_face(self, pid, method, settings=None):
        if method not in FACE_METHODS:
            raise ValueError("Unknown face method.")
        f = {"method": method}
        f.update({k: v for k, v in (settings or {}).items() if k in ("command", "repo", "preset")})
        if method == "local":
            if f.get("preset") in LOCAL_PRESETS and not f.get("command"):
                f["command"] = LOCAL_PRESETS[f["preset"]]
            if not f.get("command"):
                raise ValueError("Give the command that runs your local model (or choose a preset).")
        if method in ("heygen", "did") and not self.keys.configured(method):
            raise ValueError("Add your %s API key first." % ("HeyGen" if method == "heygen" else "D-ID"))
        with self.store.write() as db:
            db.execute("UPDATE personas SET face = ? WHERE id = ?", (json.dumps(f), int(pid)))
        return f

    # ---------------------------------------------------------------- narration
    def narrate(self, pid, text, face_method=None, emotion=None, lang=None):
        """Speak `text` as the author. photo: returns at once (the page animates the photo); cloud / local: a
        background job makes an MP4 — poll narration(id)."""
        import visemes
        p = self.get(pid)
        text = " ".join(str(text or "").split())
        if not text:
            raise ValueError("Type what the narrator should say.")
        fm = face_method or (p["face"] or {}).get("method") or "photo"
        t0 = time.time()
        g = self.speak(pid, text, emotion)
        with open(self.speech.audio_path(g["audio"]), "rb") as fh:
            wav = fh.read()
        track = visemes.align(text, wav, lang or (p["voice"] or {}).get("lang") or "en", self.speech.lab)
        with self.store.write() as db:
            nid = db.execute("INSERT INTO narrations(created, persona, text, face_method, voice_method, audio, status, seconds) VALUES(?,?,?,?,?,?,?,?)",
                             (_now(), int(pid), text, fm, (p["voice"] or {}).get("method"), g["audio"], "done" if fm == "photo" else "queued",
                              round(time.time() - t0, 2))).lastrowid
        if fm != "photo":
            threading.Thread(target=self._video_job, args=(nid, p, fm, wav), daemon=True, name="narration-%d" % nid).start()
        self.store.activity("Author narrator: narration", "ok", "%s · %s · “%s”" % (p["name"], FACE_METHODS[fm], text[:60]))
        return {"id": nid, "persona": pid, "audio": g["audio"], "track": track, "face_method": fm, "label": LABEL,
                "engine_used": g["summary"]["engine_used"], "voice_fallback": g["summary"].get("fallback_reason"), "status": "done" if fm == "photo" else "queued"}

    def narration(self, nid):
        rows = self.store.query("SELECT * FROM narrations WHERE id = ?", (int(nid),))
        if not rows:
            raise ValueError("No such narration.")
        r = rows[0]
        r["score"] = json.loads(r["score"]) if r.get("score") else None
        return r

    def _set(self, nid, **kw):
        with self.store.write() as db:
            db.execute("UPDATE narrations SET %s WHERE id = ?" % ", ".join("%s = ?" % k for k in kw), list(kw.values()) + [int(nid)])

    def _video_job(self, nid, p, method, wav):
        t0 = time.time()
        self._set(nid, status="working", detail="starting %s" % FACE_METHODS[method])
        try:
            with open(self.file_path(p["id"], p["photo"]), "rb") as f:
                photo = f.read()
            out = os.path.join(self._pdir(p["id"]), "narration-%d.mp4" % int(nid))
            if method == "heygen":
                data = self._heygen(photo, wav, lambda s: self._set(nid, detail=s))
            elif method == "did":
                data = self._did(photo, wav, lambda s: self._set(nid, detail=s))
            else:
                data = self._local(p, photo, wav, out, lambda s: self._set(nid, detail=s))
            if not data or len(data) < 1000:
                raise RuntimeError("the %s result was empty" % method)
            with open(out, "wb") as f:
                f.write(data)
            self._set(nid, status="done", video=os.path.basename(out), detail="video ready (%d KB)" % (len(data) // 1024), seconds=round(time.time() - t0, 2))
            self.store.activity("Author narrator: video", "ok", "%s · %s · %.2f s" % (p["name"], method, time.time() - t0))
        except Exception as e:
            msg = tts.scrub(e, self.keys)[:400]
            self._set(nid, status="failed", detail=msg, seconds=round(time.time() - t0, 2))
            self.store.activity("Author narrator: video", "failed", "%s · %s · %s" % (p["name"], method, msg))

    def _poll(self, get, done, fail, note, limit=900):
        t0 = time.time()
        while time.time() - t0 < limit:
            r = get()
            if done(r):
                return r
            if fail(r):
                raise RuntimeError("the service reported a failure: %s" % json.dumps(r)[:300])
            note("waiting for the service (%.0f s)" % (time.time() - t0))
            time.sleep(float(os.environ.get("QB_POLL_S", "4")))
        raise RuntimeError("the service did not finish within %d s" % limit)

    def _heygen(self, photo, wav, note):
        """HeyGen's v3 API (the v1 upload and talking-photo endpoints were retired on 31 October 2026): the photo and the
        narration are uploaded as assets, then an "image" video animates the photo to the audio. No photo-avatar slot is
        used, so a plan's avatar limit does not apply."""
        k = {"X-Api-Key": self.keys.get("heygen")["api_key"]}
        api = tts._base("heygen", "https://api.heygen.com")

        def upload(field_name, ctype, blob):
            body, ct = _multipart({}, [("file", field_name, ctype, blob)])
            return json.loads(tts._http(api + "/v3/assets", body, dict(k, **{"Content-Type": ct}), timeout=120)[0])["data"]["asset_id"]
        note("uploading the photo")
        img = upload("author.jpg", "image/jpeg", photo)
        note("uploading the narration audio")
        aud = upload("narration.wav", "audio/wav", wav)
        note("asking HeyGen to make the video")
        body = {"type": "image", "image": {"type": "asset_id", "asset_id": img}, "audio_asset_id": aud,
                "resolution": "720p", "aspect_ratio": "auto", "title": "QueryBook AI narrator"}
        raw, _ = tts._http(api + "/v3/videos", json.dumps(body).encode(), dict(k, **{"Content-Type": "application/json"}))
        vid = json.loads(raw)["data"]["video_id"]
        r = self._poll(lambda: json.loads(tts._http(api + "/v3/videos/" + vid, None, k, method="GET")[0])["data"],
                       lambda d: d.get("status") == "completed", lambda d: d.get("status") == "failed", note)
        note("downloading the video")
        return tts._http(r["video_url"], None, {}, method="GET", timeout=300)[0]

    def _did(self, photo, wav, note):
        k = {"Authorization": "Basic " + self.keys.get("did")["api_key"], "Accept": "application/json"}
        api = tts._base("did", "https://api.d-id.com")
        note("uploading the photo")
        body, ct = _multipart({}, [("image", "author.jpg", "image/jpeg", photo)])
        img = json.loads(tts._http(api + "/images", body, dict(k, **{"Content-Type": ct}), timeout=120)[0])["url"]
        note("uploading the narration audio")
        body, ct = _multipart({}, [("audio", "narration.wav", "audio/wav", wav)])
        aud = json.loads(tts._http(api + "/audios", body, dict(k, **{"Content-Type": ct}), timeout=120)[0])["url"]
        note("asking D-ID to make the video")
        raw, _ = tts._http(api + "/talks", json.dumps({"source_url": img, "script": {"type": "audio", "audio_url": aud}, "config": {"stitch": True}}).encode(),
                           dict(k, **{"Content-Type": "application/json"}))
        tid = json.loads(raw)["id"]
        r = self._poll(lambda: json.loads(tts._http(api + "/talks/" + tid, None, k, method="GET")[0]),
                       lambda d: d.get("status") == "done", lambda d: d.get("status") in ("error", "rejected"), note)
        note("downloading the video")
        return tts._http(r["result_url"], None, {}, method="GET", timeout=300)[0]

    def _local(self, p, photo, wav, out, note):
        f = p["face"] or {}
        cmd = f.get("command") or ""
        work = os.path.join(self._pdir(p["id"]), "work-%s" % uuid.uuid4().hex[:8])
        os.makedirs(work)
        try:
            face, audio = os.path.join(work, "face.jpg"), os.path.join(work, "audio.wav")
            with open(face, "wb") as fh:
                fh.write(photo)
            with open(audio, "wb") as fh:
                fh.write(wav)
            vals = {"face": face, "audio": audio, "out": out, "outdir": work, "repo": f.get("repo") or ""}
            # split the template first, then fill each piece: paths with spaces stay one argument on every system
            args = [a.format(**vals) for a in shlex.split(cmd, posix=os.name != "nt")]
            note("running: %s" % " ".join(os.path.basename(a) if os.sep in a else a for a in args)[:200])
            pr = subprocess.run(args, capture_output=True, text=True, timeout=7200, cwd=f.get("repo") or work)
            if pr.returncode != 0:
                raise RuntimeError("the local model stopped (exit %d): %s" % (pr.returncode, (pr.stderr or pr.stdout)[-300:]))
            if not os.path.isfile(out):                     # models that write into a folder (SadTalker): newest MP4 there
                vids = sorted(glob.glob(os.path.join(work, "**", "*.mp4"), recursive=True), key=os.path.getmtime)
                if not vids:
                    raise RuntimeError("the local model made no MP4")
                shutil.copy(vids[-1], out)
            with open(out, "rb") as fh:
                return fh.read()
        finally:
            shutil.rmtree(work, ignore_errors=True)
