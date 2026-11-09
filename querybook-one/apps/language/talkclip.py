"""Talking clips: every speaking face is made by a video model, never animated on this computer.

This is the way the October 29 answer videos were made (tools/answer_videos.py make), now inside the Language Builder:

  1. GEMINI FIRST - Gemini Omni (Interactions API) is given the portrait and the fixed performance instructions that made
     those clips, and performs the line itself: face, lips and voice together.
  2. HEYGEN WHEN GEMINI CANNOT - when Google refuses the line (it blocks some names of real people), when the day's Gemini
     videos are used up, when no Gemini key is set or the request fails, the line is spoken by the chosen voice and HeyGen
     (v3 API) animates the same portrait to that sound.
  3. CHECKED - when Speech-to-Text is set up, what the clip says is heard and compared with the line (the share of the
     line's words heard). A clip is never altered afterwards.

Gemini's daily video limit is shared with the admin's exemplar generator: both count in the exemplar library's
_budget.json, so together they never pass Google's limit (20 videos a day on Tier 1, October 30, 2026).
Every request is written to the AI-usage ledger (Control Panel: LLM subscriptions & usage).
"""
import base64, json, os, re, subprocess, tempfile, threading, time, urllib.error, urllib.request, uuid

import tts

MODEL = "gemini-omni-1.1-flash"
DAILY = {"gemini-omni-1.1-flash": 20}             # Google: 20 videos a day on Tier 1, shared with the exemplar generator
API = "https://generativelanguage.googleapis.com/v1beta"
REFUSED = re.compile(r"real people|likeness", re.I)
LABEL = "AI-generated talking clip"
LANGS = {"en": "American English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese",
         "nl": "Dutch", "sv": "Swedish", "da": "Danish", "no": "Norwegian", "fi": "Finnish", "pl": "Polish", "cs": "Czech",
         "el": "Greek", "ro": "Romanian", "hu": "Hungarian", "ca": "Catalan", "ru": "Russian", "uk": "Ukrainian", "tr": "Turkish",
         "ar": "Arabic", "he": "Hebrew", "hi": "Hindi", "bn": "Bengali", "ur": "Urdu", "fa": "Persian", "zh": "Mandarin Chinese",
         "ja": "Japanese", "ko": "Korean", "vi": "Vietnamese", "th": "Thai", "id": "Indonesian", "ms": "Malay", "sw": "Swahili",
         "yo": "Yoruba", "zu": "Zulu", "af": "Afrikaans", "ta": "Tamil", "te": "Telugu", "tl": "Filipino"}


def prompt(line, lang="en"):
    """The fixed instructions of the October 29 answer videos (answers-batch1.script.md), then the line.
    Only the language changes; for English the wording is exactly the one that made those clips."""
    spoken = LANGS.get((lang or "en").split("-")[0], LANGS["en"])
    say = " ".join(str(line or "").split()).replace(" … ", ", ").replace("…", ",")
    return ("Use the attached image: this exact woman — same face, hair, skin, lips and teeth. Do not change her identity.\n\n"
            "Shot: head and shoulders, facing the camera straight on, eyes level with the lens. The camera does not move, zoom or cut. "
            "Soft, even, front lighting with no hard shadows across the mouth. Plain, still background. Her whole mouth and chin stay in "
            "view the entire time; no hands, hair or objects in front of the face.\n\n"
            "Performance: she answers a question, speaking clearly in natural %s at a calm, friendly pace, looking into "
            "the camera, with a warm, neutral expression. Natural blinking and small natural head movements only. She says exactly the "
            "words given — no extra words, no humming, no music, no other sounds. No captions, subtitles or any text on screen.\n\n"
            "Timing: she starts with her lips gently closed for half a second, speaks the line, then closes her lips and holds still "
            "for half a second at the end.\n\nShe says exactly: \"%s\"" % (spoken, say))


def for_person(text, kind):
    """the instructions for a man or for a person of unstated gender (the same words, other pronouns)"""
    if kind == "man":
        swaps = [("woman", "man"), ("Her whole", "His whole"), ("her identity", "his identity"), ("she ", "he "), ("She ", "He "), ("her lips", "his lips")]
    elif kind == "person":
        swaps = [("this exact woman", "this exact person"), ("Her whole", "The whole"), ("her identity", "their identity"),
                 ("she answers", "they answer"), ("She says exactly the", "They say exactly the"), ("she starts with her lips", "they start with their lips"),
                 ("then closes her lips and holds", "then close their lips and hold"), ("She says exactly:", "They say exactly:")]
    else:
        return text
    for a, b in swaps:
        text = text.replace(a, b)
    return text


# ------------------------------------------------------------------------------------------------ hearing the clip
def _words(s):
    import unicodedata
    t = unicodedata.normalize("NFKD", (s or "").lower().replace("’", "'"))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"(?<=\d),(?=\d)", "", t)
    return [w.strip(".'") for w in re.findall(r"[\w.']+", t) if w.strip(".'")]


def heard_share(line, heard):
    """the share of the line's words heard, in order (longest common subsequence)"""
    a, b = _words(line), _words(heard)
    if not a:
        return 1.0
    L = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a)):
        for j in range(len(b)):
            L[i + 1][j + 1] = L[i][j] + 1 if a[i] == b[j] else max(L[i][j + 1], L[i + 1][j])
    return round(L[-1][-1] / len(a), 3)


# ------------------------------------------------------------------------------------------------ the two makers
def image_type(image):
    """(mime type, file extension) of a portrait from its first bytes"""
    if image[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", "png"
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "image/webp", "webp"
    return "image/jpeg", "jpg"


class GeminiError(RuntimeError):
    def __init__(self, code, msg):
        super().__init__("Gemini HTTP %s: %s" % (code, msg)); self.code = code


def gemini_video(key, image, line, lang="en", person="woman", model=MODEL, timeout=900):
    """one Gemini Omni request: the portrait + the fixed instructions; returns the MP4 bytes"""
    body = {"model": model, "store": False,
            "input": [{"type": "image", "data": base64.b64encode(image).decode(), "mime_type": image_type(image)[0]},
                      {"type": "text", "text": for_person(prompt(line, lang), person)}],
            "response_format": {"type": "video", "aspect_ratio": "16:9"},
            "generation_config": {"video_config": {"task": "image_to_video"}}}
    base = os.environ.get("QB_GEMINI_BASE", API).rstrip("/")
    req = urllib.request.Request(base + "/interactions", data=json.dumps(body).encode(), method="POST",
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ans = json.loads(r.read())
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(msg)["error"]["message"]
        except Exception:
            pass
        raise GeminiError(e.code, msg.replace(key, "<key>")[:400])
    vids = [p for s in ans.get("steps", []) if s.get("type") == "model_output" for p in s.get("content", []) if p.get("type") == "video"]
    if not vids:
        raise GeminiError(0, "no video in the answer (status %s)" % ans.get("status"))
    return base64.b64decode(vids[0]["data"])


def _multipart(fields, files):
    b = uuid.uuid4().hex
    out = b""
    for k, v in fields.items():
        out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (b, k, v)).encode()
    for field, name, ctype, blob in files:
        out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n" % (b, field, name, ctype)).encode() + blob + b"\r\n"
    return out + ("--%s--\r\n" % b).encode(), "multipart/form-data; boundary=" + b


def heygen_video(api_key, image, wav, note=lambda s: None, poll_s=None, limit_s=900):
    """HeyGen v3: the portrait and the speech are uploaded as assets, then an "image" video animates the portrait to the
    sound (no photo-avatar slot is used, so a plan's avatar limit does not apply). Returns the MP4 bytes."""
    k = {"X-Api-Key": api_key}
    api = tts._base("heygen", "https://api.heygen.com")

    def upload(name, ctype, blob):
        body, ct = _multipart({}, [("file", name, ctype, blob)])
        return json.loads(tts._http(api + "/v3/assets", body, dict(k, **{"Content-Type": ct}), timeout=120)[0])["data"]["asset_id"]
    note("uploading the portrait to HeyGen")
    mime, ext = image_type(image)
    img = upload("portrait." + ext, mime, image)
    note("uploading the speech to HeyGen")
    aud = upload("speech.wav", "audio/wav", wav)
    note("HeyGen is making the video")
    raw, _ = tts._http(api + "/v3/videos", json.dumps({"type": "image", "image": {"type": "asset_id", "asset_id": img}, "audio_asset_id": aud,
                                                      "resolution": "720p", "aspect_ratio": "auto", "title": "QueryBook talking clip"}).encode(),
                       dict(k, **{"Content-Type": "application/json"}))
    vid = json.loads(raw)["data"]["video_id"]
    t0, wait = time.time(), float(poll_s if poll_s is not None else os.environ.get("QB_POLL_S", "4"))
    while time.time() - t0 < limit_s:
        d = json.loads(tts._http(api + "/v3/videos/" + vid, None, k, method="GET")[0])["data"]
        if d.get("status") == "completed":
            note("downloading the video")
            return tts._http(d["video_url"], None, {}, method="GET", timeout=300)[0]
        if d.get("status") == "failed":
            raise RuntimeError("HeyGen could not make the video: %s" % (d.get("failure_message") or d.get("error") or "no reason given"))
        note("HeyGen is making the video (%.0f s)" % (time.time() - t0))
        time.sleep(wait)
    raise RuntimeError("HeyGen did not finish within %d s" % limit_s)


# ------------------------------------------------------------------------------------------------ the shared daily budget
class Budget:
    """Gemini videos per day, in the exemplar library's _budget.json (the exemplar generator's own file and format)."""
    _lock = threading.Lock()

    def __init__(self, folder):
        self.path = os.path.join(folder, "_budget.json")

    def _load(self):
        try:
            return json.load(open(self.path, encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, b):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        json.dump(b, open(tmp, "w", encoding="utf-8"), indent=1, sort_keys=True)
        os.replace(tmp, self.path)

    def left(self, model=MODEL):
        d = self._load().get(time.strftime("%Y-%m-%d", time.gmtime()), {})
        if d.get(model + ":stopped"):
            return 0
        return max(0, DAILY.get(model, 20) - int(d.get(model, 0)))

    def reserve(self, model=MODEL):
        with self._lock:
            if self.left(model) <= 0:
                return False
            b = self._load(); day = time.strftime("%Y-%m-%d", time.gmtime())
            d = b.setdefault(day, {}); d[model] = int(d.get(model, 0)) + 1
            self._save(b)
            return True

    def refund(self, model=MODEL):
        with self._lock:
            b = self._load(); d = b.get(time.strftime("%Y-%m-%d", time.gmtime()), {})
            if int(d.get(model, 0)) > 0:
                d[model] = int(d[model]) - 1
                self._save(b)

    def stop_today(self, model=MODEL):
        with self._lock:
            b = self._load(); b.setdefault(time.strftime("%Y-%m-%d", time.gmtime()), {})[model + ":stopped"] = True
            self._save(b)


# ------------------------------------------------------------------------------------------------ the clip library
class TalkClips:
    """make(line, portrait) → a background job; clips are kept in <app folder>/talkclips/ with index.json."""

    def __init__(self, app_folder, keys, budget_folder, speak=None, hear=None, log=None, usage=None, hear_ready=None):
        self.folder = os.path.join(app_folder, "talkclips")
        os.makedirs(self.folder, exist_ok=True)
        self.path = os.path.join(self.folder, "index.json")
        self.keys = keys                          # tts.Keys: google_gemini, heygen
        self.budget = Budget(budget_folder)
        self.speak = speak                        # (line, lang, voice) → wav bytes, for the HeyGen route
        self.hear = hear                          # (wav bytes, lang) → transcript or None
        self.hear_ready = hear_ready or (lambda: bool(self.hear))   # whether Speech-to-Text is set up now
        self.log = log or (lambda *a: None)
        self.usage = usage or (lambda *a, **k: None)
        self._lock = threading.Lock()
        self.makers = {"gemini": gemini_video, "heygen": heygen_video}   # replaced in the self-test

    # ---------------------------------------------------------------- index
    def _load(self):
        try:
            return json.load(open(self.path, encoding="utf-8"))
        except (OSError, ValueError):
            return {"clips": []}

    def _save(self, d):
        tmp = self.path + ".tmp"
        json.dump(d, open(tmp, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        os.replace(tmp, self.path)

    def _update(self, cid, **kw):
        with self._lock:
            d = self._load()
            for c in d["clips"]:
                if c["id"] == cid:
                    c.update(kw)
            self._save(d)

    def list(self, limit=50):
        return list(reversed(self._load()["clips"]))[:limit]

    def get(self, cid):
        c = next((x for x in self._load()["clips"] if x["id"] == str(cid)), None)
        if not c:
            raise ValueError("No such talking clip.")
        return c

    def video_path(self, cid):
        c = self.get(cid)
        if not c.get("video"):
            raise ValueError("This clip has no video yet.")
        return os.path.join(self.folder, c["video"])

    def delete(self, cid):
        c = self.get(cid)
        with self._lock:
            d = self._load(); d["clips"] = [x for x in d["clips"] if x["id"] != c["id"]]; self._save(d)
        if c.get("video"):
            try:
                os.remove(os.path.join(self.folder, c["video"]))
            except OSError:
                pass
        return {"deleted": c["id"]}

    def status(self):
        return {"gemini_key": self.keys.configured("google_gemini"), "heygen_key": self.keys.configured("heygen"),
                "gemini_left_today": self.budget.left(), "gemini_daily": DAILY.get(MODEL, 20), "model": MODEL, "label": LABEL,
                "speech_to_text": bool(self.hear and self.hear_ready())}

    # ---------------------------------------------------------------- making
    def make(self, line, image, face_name="", lang="en", person="woman", route="auto", voice=None, wait=False):
        line = " ".join(str(line or "").split())
        if not line:
            raise ValueError("Type what the face should say.")
        if not image or len(image) < 1000:
            raise ValueError("Choose a face (a portrait) first.")
        if route not in ("auto", "gemini", "heygen"):
            raise ValueError("Unknown way to make the clip.")
        if not self.keys.configured("google_gemini") and not self.keys.configured("heygen"):
            raise ValueError("Add a Gemini API key (Speech → Voice providers → Google Gemini) or a HeyGen key first.")
        c = {"id": uuid.uuid4().hex[:12], "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "line": line, "lang": lang, "face": face_name,
             "person": person, "asked": route, "status": "queued", "detail": "waiting to start", "route": None, "why": "", "video": None,
             "seconds": None, "heard": None, "heard_share": None, "label": LABEL}
        with self._lock:
            d = self._load(); d["clips"].append(c); self._save(d)
        t = threading.Thread(target=self._job, args=(c["id"], line, image, lang, person, route, voice or {}), daemon=True, name="talkclip-" + c["id"])
        t.start()
        if wait:
            t.join()
            return self.get(c["id"])
        return c

    def _job(self, cid, line, image, lang, person, route, voice):
        t0 = time.time()
        note = lambda s: self._update(cid, detail=s)
        self._update(cid, status="working")
        data, used, why = None, None, ""
        try:
            if route in ("auto", "gemini"):
                data, why = self._try_gemini(line, image, lang, person, note)
                used = "gemini" if data else None
                if not data and route == "gemini":
                    raise RuntimeError(why)
            if not data:
                if not self.keys.configured("heygen"):
                    raise RuntimeError((why + " — and " if why else "") + "no HeyGen key is set, so the clip could not be made the other way")
                if not self.speak:
                    raise RuntimeError("no voice is available for the HeyGen route")
                note("speaking the line for HeyGen")
                wav = self.speak(line, lang, voice)
                h0 = time.time()
                try:
                    data = self.makers["heygen"](self.keys.get("heygen")["api_key"], image, wav, note)
                    self.usage("heygen", "image video v3", "talking clip", seconds=time.time() - h0)
                except Exception as e:
                    self.usage("heygen", "image video v3", "talking clip", seconds=time.time() - h0, ok=False, error=str(e)[:80])
                    raise
                used = "heygen"
            if not data or len(data) < 1000:
                raise RuntimeError("the %s result was empty" % used)
            name = "clip-%s.mp4" % cid
            with open(os.path.join(self.folder, name), "wb") as f:
                f.write(data)
            heard = share = None
            if self.hear:
                note("checking what the clip says")
                try:
                    heard = self.hear(self._audio(os.path.join(self.folder, name)), lang)
                    share = heard_share(line, heard) if heard is not None else None
                except Exception as e:
                    heard = None
                    self.log("talking clip: could not check the words (%s)" % e)
            self._update(cid, status="done", route=used, why=why, video=name, seconds=round(time.time() - t0, 2), heard=heard, heard_share=share,
                         detail="made by %s%s" % ("Gemini" if used == "gemini" else "HeyGen", (" — " + why) if why and used == "heygen" else ""))
            self.log("talking clip made by %s in %.1f s: %s" % (used, time.time() - t0, line[:60]))
        except Exception as e:
            msg = tts.scrub(e, self.keys)[:400]
            self._update(cid, status="failed", route=used, why=why, detail=msg, seconds=round(time.time() - t0, 2))
            self.log("talking clip failed: %s" % msg)

    def _try_gemini(self, line, image, lang, person, note):
        """(MP4 bytes, "") or (None, why Gemini was not used)"""
        if not self.keys.configured("google_gemini"):
            return None, "no Gemini key is set"
        if not self.budget.reserve():
            return None, "today's %d Gemini videos are used up" % DAILY.get(MODEL, 20)
        note("Gemini is making the video (about 1 to 3 minutes)")
        g0 = time.time()
        try:
            data = self.makers["gemini"](self.keys.get("google_gemini")["api_key"], image, line, lang, person)
            self.usage("veo", MODEL, "talking clip", seconds=time.time() - g0)
            return data, ""
        except GeminiError as e:
            self.usage("veo", MODEL, "talking clip", seconds=time.time() - g0, ok=False, error="HTTP %s" % e.code)
            if e.code == 400 and REFUSED.search(str(e)):
                self.budget.refund()
                return None, "Google refused the line (it names a real person)"
            if e.code == 429 and "quota" in str(e).lower():
                self.budget.stop_today()
                return None, "Google says today's Gemini video quota is used up"
            if e.code in (429, 500, 502, 503, 504):
                self.budget.refund()
            return None, "Gemini could not make it (%s)" % str(e)[:160]
        except Exception as e:
            self.budget.refund()
            self.usage("veo", MODEL, "talking clip", seconds=time.time() - g0, ok=False, error=str(e)[:80])
            return None, "Gemini could not make it (%s)" % str(e)[:160]

    @staticmethod
    def _audio(mp4):
        with tempfile.TemporaryDirectory() as td:
            wav = os.path.join(td, "a.wav")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", mp4, "-vn", "-ac", "1", "-ar", "16000", wav], check=True, timeout=120)
            with open(wav, "rb") as f:
                return f.read()


# ------------------------------------------------------------------------------------------------ self-test
def self_test():
    """the Gemini-first rule, the HeyGen fallback, the shared budget and the October 29 wording (stand-in makers)"""
    import shutil
    checks, td = [], tempfile.mkdtemp()

    def ok(name, cond, detail=""):
        checks.append({"name": name, "ok": bool(cond), "detail": str(detail)[:200]})

    class Keys:
        def __init__(self, have):
            self.have = have

        def configured(self, p):
            return p in self.have

        def get(self, p):
            return {"api_key": "TEST-" + p}

        def secrets(self):
            return ["TEST-google_gemini", "TEST-heygen"]
    try:
        p = prompt("The capital of France is Paris.")
        ok("the instructions are the October 29 wording", p.startswith("Use the attached image: this exact woman") and "natural American English" in p
           and p.endswith('She says exactly: "The capital of France is Paris."'), p[-80:])
        ok("another language changes only the language", "natural French" in prompt("Bonjour.", "fr") and prompt("x", "fr").replace("French", "American English") == prompt("x"))
        ok("instructions for a man / a person", "this exact man" in for_person(p, "man") and "He says exactly:" in for_person(p, "man")
           and "this exact person" in for_person(p, "person") and "They say exactly:" in for_person(p, "person"))
        ok("the portrait's type is read from its bytes", image_type(b"\x89PNG\r\n\x1a\n....")[0] == "image/png" and image_type(b"\xff\xd8\xff")[0] == "image/jpeg")
        ok("words heard: share of the line", heard_share("The capital of France is Paris.", "the capital of france is paris") == 1.0
           and heard_share("one two three four", "one three") == 0.5)
        mp4 = b"\x00" * 5000
        calls = []
        tc = TalkClips(td, Keys({"google_gemini", "heygen"}), os.path.join(td, "budget"), speak=lambda line, lang, v: b"RIFF" + b"\x00" * 2000)
        tc._audio = lambda path: b""
        tc.makers = {"gemini": lambda k, img, line, lang, person: calls.append("gemini") or mp4,
                     "heygen": lambda k, img, wav, note: calls.append("heygen") or mp4}
        c = tc.make("Hello there.", b"\xff" * 2000, "Pamela", wait=True)
        ok("Gemini makes the clip first", c["status"] == "done" and c["route"] == "gemini" and calls == ["gemini"], c)
        ok("the clip is kept", os.path.getsize(tc.video_path(c["id"])) == len(mp4))
        ok("one Gemini video counted today", tc.budget.left() == DAILY[MODEL] - 1, tc.budget.left())

        def refuse(*a):
            calls.append("gemini"); raise GeminiError(400, "Input blocked: real people's names or likenesses")
        tc.makers["gemini"] = refuse; calls.clear()
        c = tc.make("Nelson Mandela was born in 1918.", b"\xff" * 2000, wait=True)
        ok("a refused line is made by HeyGen, and the Gemini request is given back", c["route"] == "heygen" and calls == ["gemini", "heygen"]
           and "refused" in c["why"] and tc.budget.left() == DAILY[MODEL] - 1, c)
        b = tc.budget._load(); b[time.strftime("%Y-%m-%d", time.gmtime())][MODEL] = DAILY[MODEL]; tc.budget._save(b)
        tc.makers["gemini"] = lambda *a: calls.append("gemini") or mp4; calls.clear()
        c = tc.make("Kenya is in Africa.", b"\xff" * 2000, wait=True)
        ok("Gemini's day used up: HeyGen makes it without a Gemini request", c["route"] == "heygen" and calls == ["heygen"] and "used up" in c["why"], c)
        tc.keys = Keys({"google_gemini"}); calls.clear()
        c = tc.make("Kenya is in Africa.", b"\xff" * 2000, wait=True)
        ok("no HeyGen key and no Gemini left: the clip fails and says why", c["status"] == "failed" and "HeyGen" in c["detail"], c)
        tc.keys = Keys({"heygen"}); calls.clear()
        c = tc.make("Kenya is in Africa.", b"\xff" * 2000, route="heygen", wait=True)
        ok("HeyGen on request", c["route"] == "heygen" and calls == ["heygen"], c)
        tc.hear = lambda wav, lang: "kenya is in africa"; calls.clear()
        c = tc.make("Kenya is in Africa.", b"\xff" * 2000, wait=True)
        ok("what the clip says is heard and compared", c["heard_share"] == 1.0, c)
        try:
            tc.make("", b"\xff" * 2000); bad = False
        except ValueError:
            bad = True
        ok("an empty line is refused", bad)
        n = len(tc.list()); tc.delete(tc.list()[0]["id"])
        ok("a clip can be deleted", len(tc.list()) == n - 1)
    finally:
        shutil.rmtree(td, ignore_errors=True)
    return checks


if __name__ == "__main__":
    res = self_test()
    for r in res:
        print("ok  " if r["ok"] else "FAIL", r["name"], "" if r["ok"] else r["detail"])
    print("%d of %d checks passed" % (sum(r["ok"] for r in res), len(res)))
