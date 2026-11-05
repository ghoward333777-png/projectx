"""QueryBook Video Studio — the work behind the page: shots in, one finished video out.

A PROJECT is an ordered list of shots and how the result should look:

  action shot   a common human action from the clip library (reused, re-cropped, re-timed, re-coloured locally) or, when no
                stored clip exists, generated once by the video model and stored for reuse. It can carry a VOICE-OVER: the
                text is spoken by Language Builder (its voices, its pronunciation resolver) and the shot is held on its last
                frame if the speech runs longer than the action.
  talk shot     a narrator (an author persona in Language Builder) saying a text, in a video made by a video model:
                Gemini performs it (HeyGen when Gemini cannot), or HeyGen or D-ID animate the photo to the persona's voice.
                Nothing animates a face on this computer. The finished narration is stored in the library, so the same
                narrator saying the same text again is a reuse, not a new request.

The studio then joins the shots (in-between frames where two ends match, else a cut), applies frames-per-second and
upscaling if asked, lays every voice under its shot, writes captions from the word timings Language Builder measures
(an .srt file, burned in on request) and checks the result: every segment's motion kept, sound and picture the same
length, the narrations' timing preserved. Language Builder must be running for voices and narrators; actions alone
need nothing else.
"""
import hashlib, json, os, re, shutil, subprocess, tempfile, time, urllib.error, urllib.parse, urllib.request

import hybrid_video as hv
import qbframes as qf
import reuse_bench as rb

ENGINES = ["espeak", "google_cloud", "google_gemini", "elevenlabs", "openai", "azure", "polly", "sapi", "say", "formant"]
FACE_METHODS = {"gemini": "Gemini (HeyGen when Gemini cannot)", "heygen": "HeyGen (cloud)", "did": "D-ID (cloud)"}


class LanguageError(Exception):
    pass


class Language:
    """Language Builder over its local web interface: speech, word timings, narrators and their lip-synced narrations"""

    def __init__(self, url="http://127.0.0.1:8101"):
        self.url = (url or "http://127.0.0.1:8101").rstrip("/")

    def _req(self, path, body=None, timeout=600, raw=False):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read()
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error")
            except Exception:
                msg = None
            raise LanguageError("Language Builder: %s" % (msg or "HTTP %d" % e.code))
        except (urllib.error.URLError, OSError) as e:
            raise LanguageError("Language Builder is not reachable at %s — start it (START-ALL starts every program). (%s)"
                                % (self.url, getattr(e, "reason", e)))
        return b if raw else json.loads(b.decode("utf-8"))

    def status(self):
        try:
            s = self._req("/api/status", timeout=4)
            return {"ok": True, "version": s.get("version"), "url": self.url}
        except LanguageError as e:
            return {"ok": False, "url": self.url, "why": str(e)}

    def speak(self, text, engine="espeak", voice="", lang="en", emotion=""):
        prof = {"lang": lang or "en"}
        if emotion:
            prof["emotion"] = emotion
        g = self._req("/api/speech/generate", {"text": text, "engine": engine or "espeak", "voice": voice or "", "profile": prof, "fallback": True})
        wav = self._req("/api/speech/audio?name=" + urllib.parse.quote(g["audio"]), raw=True)
        return g["audio"], wav, (g.get("summary") or {})

    def words(self, audio_name, text, lang="en"):
        try:
            return (self._req("/api/speech/lipsync", {"audio": audio_name, "text": text, "lang": lang or "en"}) or {}).get("words") or []
        except LanguageError:
            return []

    def personas(self):
        return self._req("/api/persona").get("personas") or []

    def narrate(self, pid, text, face_method, emotion="", progress=None, stop=None, timeout=1800):
        r = self._req("/api/persona/narrate", {"id": pid, "text": text, "face_method": face_method, "emotion": emotion or None})
        nid, t0 = r["id"], time.time()
        while True:
            n = self._req("/api/persona/narration?id=%s" % nid)
            if n.get("status") == "done" and n.get("video"):
                mp4 = self._req("/api/persona/video?narration=%s" % nid, raw=True, timeout=600)
                # made by: the narration's own record (a Gemini request that HeyGen finished says "heygen")
                return mp4, {"narration": nid, "track": r.get("track"), "engine_used": r.get("engine_used"), "face_method": n.get("face_method") or r.get("face_method")}
            if n.get("status") == "failed":
                raise LanguageError("the narration failed: %s" % (n.get("detail") or "no detail"))
            if stop and stop():
                raise LanguageError("stopped")
            if time.time() - t0 > timeout:
                raise LanguageError("the narration took longer than %d minutes" % (timeout // 60))
            if progress:
                progress("narrator: %s" % (n.get("detail") or n.get("status") or "working"))
            time.sleep(3)


def _dur(p):
    return rb.duration(p)


def _has_audio(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", p],
                       capture_output=True, text=True)
    return bool(r.stdout.strip())


def _hold(src, dst, seconds):
    """the clip held on its last frame for `seconds` more (a voice-over longer than the action)"""
    rb._ff(["-i", src, "-vf", "tpad=stop_mode=clone:stop_duration=%.3f" % seconds, "-an", "-c:v", "libx264", "-preset", "veryfast",
            "-pix_fmt", "yuv420p", dst])


def _srt_time(t):
    t = max(0.0, t)
    return "%02d:%02d:%02d,%03d" % (int(t // 3600), int(t % 3600 // 60), int(t % 60), int(round((t - int(t)) * 1000)) % 1000)


def captions(words, max_words=7, max_s=3.2):
    """[{word, start, end}] (absolute seconds) → SRT text, lines of a few words"""
    lines, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w["end"] - cur[0]["start"] > max_s or w["start"] - cur[-1]["end"] > 0.6):
            lines.append(cur); cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    out = []
    for i, ln in enumerate(lines, 1):
        out.append("%d\n%s --> %s\n%s\n" % (i, _srt_time(ln[0]["start"]), _srt_time(ln[-1]["end"] + 0.15), " ".join(x["word"] for x in ln)))
    return "\n".join(out)


def _ffmpeg_has(filt):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
    return re.search(r"\s%s\s" % re.escape(filt), r.stdout) is not None


class Studio:
    def __init__(self, folder, settings, log=lambda *a: None):
        self.folder = folder
        self.lib = hv.Library(os.path.join(folder, "library"))
        self.out_dir = os.path.join(folder, "outputs")
        os.makedirs(self.out_dir, exist_ok=True)
        self.settings = settings                      # callable → dict (language_url, gemini_key)
        self.log = log

    def language(self):
        return Language(self.settings().get("language_url"))

    def gemini_generator(self):
        key = self.settings().get("gemini_key")
        if not key:
            return None
        import generate_exemplars as ge
        budget = ge.Budget(type("L", (), {"folder": self.folder})())

        def gen(action, prompt):
            if not budget.reserve(hv.MODEL):
                raise RuntimeError("no %s requests left today; stored clips still work" % hv.MODEL)
            try:
                return ge.generate(key, hv.MODEL, prompt)[0]
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    budget.refund(hv.MODEL)
                raise
        return gen

    # -- planning
    @staticmethod
    def talk_key(shot):
        h = hashlib.sha256(("%s|%s|%s" % (shot.get("persona"), " ".join(str(shot.get("text") or "").split()), shot.get("face_method"))).encode("utf-8")).hexdigest()
        return "talk-%s-%s" % (shot.get("persona"), h[:12])

    def talk_clip(self, key):
        """a stored narration (a talking head moves little, so it is not held to the action clips' motion rule)"""
        return next((c for c in reversed(self.lib.data["clips"]) if c["action"] == key
                     and os.path.exists(os.path.join(self.lib.folder, c["file"]))), None)

    def plan(self, project):
        shots = self._shots(project)
        rows, total = [], 0.0
        for i, s in enumerate(shots, 1):
            if s["type"] == "action":
                p = hv.plan(self.lib, [s["action"]], project.get("format", "horizontal"), float(s.get("speed") or 1.0))
                st = p["steps"][0]
                row = {"shot": i, "type": "action", "what": s["action"], "route": st["route"], "why": st["why"], "estimate_s": st["estimate_s"]}
                if s.get("say"):
                    row["voice_over"] = "spoken by Language Builder (%s)" % ((project.get("voice") or {}).get("engine") or "espeak")
                    row["estimate_s"] = (row["estimate_s"] or 0) + 5
            else:
                c = self.talk_clip(self.talk_key(s))
                row = {"shot": i, "type": "talk", "what": "narrator %s: “%s”" % (s.get("persona"), str(s.get("text"))[:60]),
                       "route": "reuse" if c else "narrate", "why": "this narrator already said this text (stored)" if c else
                       "made by %s through Language Builder, then stored for reuse" % FACE_METHODS.get(s.get("face_method"), s.get("face_method")),
                       "estimate_s": 2.0 if c else (self.lib.timing("narrate") or 120.0)}
            rows.append(row)
            total += row["estimate_s"] or 0
        extras = hv.plan(self.lib, [s.get("action") or "x" for s in shots][:1] * 1, project.get("format", "horizontal"),
                         fps_out=project.get("fps"), height=project.get("height"))["frame_work"]
        total += sum(e["estimate_s"] for e in extras)
        return {"shots": rows, "frame_work": extras, "estimate_s": round(total, 1), "language": self.language().status(),
                "generator": bool(self.settings().get("gemini_key")), "backends": qf.backends()}

    @staticmethod
    def _shots(project):
        shots = [s for s in (project.get("shots") or []) if isinstance(s, dict)]
        if not shots:
            raise ValueError("Add at least one shot.")
        for s in shots:
            if s.get("type") not in ("action", "talk"):
                raise ValueError("A shot is an action or a talk.")
            if s["type"] == "action" and not str(s.get("action") or "").strip():
                raise ValueError("Name the action of every action shot.")
            if s["type"] == "talk" and not (s.get("persona") and str(s.get("text") or "").strip()):
                raise ValueError("A talk shot needs a narrator and what they say.")
            if s["type"] == "talk" and s.get("face_method") not in FACE_METHODS:
                raise ValueError("A talk shot needs a way to make the video: %s." % ", ".join(FACE_METHODS))
        return shots

    # -- rendering
    def render(self, project, progress=lambda *a, **k: None, stop=lambda: False):
        shots = self._shots(project)
        fmt = project.get("format", "horizontal")
        grade = project.get("grade", "none")
        voice = project.get("voice") or {}
        lang = voice.get("lang") or "en"
        lb = self.language()
        tmp = tempfile.mkdtemp(prefix="qb-studio-")
        t_all = time.time()
        rep = {"shots": [], "started": hv._now()}
        try:
            segs = []
            for i, s in enumerate(shots, 1):
                if stop():
                    raise RuntimeError("stopped")
                progress(i - 1, len(shots), "shot %d of %d: %s" % (i, len(shots), s["type"]))
                seg = os.path.join(tmp, "seg%02d.mp4" % i)
                row = {"shot": i, "type": s["type"]}
                audio, words = None, []
                if s["type"] == "action":
                    r = hv.render(self.lib, [s["action"]], seg, fmt, float(s.get("speed") or 1.0), grade, s.get("max_seconds"),
                                  generator=self.gemini_generator(), interp=project.get("interp", "best"), bridges=False)
                    row.update(what=s["action"], route=r["plan"]["steps"][0]["route"], ok=r["ok"], seconds=r["total_s"])
                    if s.get("say"):
                        t0 = time.time()
                        name, wav, summ = lb.speak(s["say"], voice.get("engine"), voice.get("voice"), lang, voice.get("emotion"))
                        audio = os.path.join(tmp, "voice%02d.wav" % i)
                        open(audio, "wb").write(wav)
                        words = lb.words(name, s["say"], lang)
                        row.update(voice_over=summ.get("engine_used"), voice_s=round(time.time() - t0, 2))
                        extra = _dur(audio) - _dur(seg)
                        if extra > 0.05:                  # the speech is longer than the action: hold the last frame
                            held = os.path.join(tmp, "seg%02d-held.mp4" % i)
                            _hold(seg, held, extra + 0.3)
                            seg = held
                            row["held_s"] = round(extra + 0.3, 2)
                else:
                    key = self.talk_key(s)
                    c = self.talk_clip(key)
                    t0 = time.time()
                    if not c:
                        mp4, info = lb.narrate(s["persona"], s["text"], s["face_method"], s.get("emotion"),
                                               lambda m: progress(i - 1, len(shots), "shot %d: %s" % (i, m)), stop)
                        raw = os.path.join(tmp, "talk%02d.mp4" % i)
                        open(raw, "wb").write(mp4)
                        made = info.get("face_method") or s["face_method"]
                        c = self.lib.add(key, raw, "narration video by %s (Language Builder)" % FACE_METHODS.get(made, made),
                                         consent="the narrator's consent is recorded with the persona in Language Builder", prompt=s["text"])
                        # word times for captions: the narration's own speech — except when Gemini spoke with its own voice,
                        # whose timing is not known here (no captions rather than wrong ones)
                        track = (info.get("track") or {}) if made != "gemini" else {}
                        json.dump(track.get("words") or [], open(os.path.join(self.lib.folder, key, c["id"] + ".words.json"), "w"))
                        if made == "gemini":
                            row["captions"] = "none for this shot: Gemini spoke with its own voice, so the word times are not known"
                        self.lib.record("narrate", time.time() - t0)
                        self.lib.save()
                        row["route"] = "narrate"
                    else:
                        row["route"] = "reuse"
                    src = os.path.join(self.lib.folder, c["file"])
                    hv._edit(src, seg, fmt, 1.0, grade, None)
                    if _has_audio(src):
                        audio = os.path.join(tmp, "talk%02d.wav" % i)
                        rb._ff(["-i", src, "-vn", "-ac", "1", "-ar", "24000", audio])
                    wp = os.path.join(self.lib.folder, key, c["id"] + ".words.json")
                    words = json.load(open(wp)) if os.path.exists(wp) else []
                    sync = abs(_dur(seg) - _dur(src))
                    row.update(what="narrator %s" % s["persona"], clip=c["id"], seconds=round(time.time() - t0, 2),
                               lip_sync_kept=sync < 0.1, ok=sync < 0.1 and _dur(seg) > 0.5)
                rep["shots"].append(row)
                segs.append({"video": seg, "audio": audio, "words": words})
            # joins: in-between frames where the ends match, else a cut (sound stays under its own shot)
            progress(len(shots), len(shots), "joining")
            pieces, starts, t, joins = [], [], 0.0, []
            for k, sg in enumerate(segs):
                if k and project.get("bridges", True):
                    br = os.path.join(tmp, "bridge%02d.mp4" % k)
                    backend, diff = qf.bridge(segs[k - 1]["video"], sg["video"], br)
                    if backend:
                        pieces.append(br); t += _dur(br)
                        joins.append({"join": k, "how": "in-between frames", "backend": backend, "difference": diff})
                    else:
                        joins.append({"join": k, "how": "cut", "difference": diff})
                starts.append(t)
                pieces.append(sg["video"]); t += _dur(sg["video"])
            video = os.path.join(tmp, "video.mp4")
            hv._concat(pieces, video) if len(pieces) > 1 else shutil.copyfile(pieces[0], video)
            rep["joins"] = joins
            if project.get("fps"):
                progress(len(shots), len(shots), "frames per second")
                nxt = os.path.join(tmp, "video-fps.mp4")
                rep["fps_backend"] = qf.interpolate(video, nxt, target_fps=float(project["fps"]), mode=project.get("interp", "best"))
                video = nxt
            if project.get("height"):
                progress(len(shots), len(shots), "upscaling")
                nxt = os.path.join(tmp, "video-up.mp4")
                rep["upscale_backend"] = qf.upscale(video, nxt, int(project["height"]))
                rep["upscale_ssim"] = round(qf.ssim(video, nxt), 4)
                video = nxt
            total_v = _dur(video)
            # sound: each voice under its own shot
            progress(len(shots), len(shots), "sound")
            audio = os.path.join(tmp, "audio.wav")
            ins, fl = [], []
            n_a = 0
            for k, sg in enumerate(segs):
                if sg["audio"]:
                    ins += ["-i", sg["audio"]]
                    ms = int(round(starts[k] * 1000))
                    fl.append("[%d:a]aresample=48000,aformat=channel_layouts=stereo,adelay=%d|%d[a%d]" % (n_a, ms, ms, n_a))
                    n_a += 1
            if n_a:
                fl.append("%samix=inputs=%d:normalize=0,apad,atrim=0:%.3f[a]" % ("".join("[a%d]" % j for j in range(n_a)), n_a, total_v))
                rb._ff(ins + ["-filter_complex", ";".join(fl), "-map", "[a]", "-ar", "48000", audio])
            else:
                rb._ff(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "%.3f" % total_v, audio])
            # captions from the measured word timings
            allw = [{"word": w["word"], "start": starts[k] + float(w["start"]), "end": starts[k] + float(w["end"])}
                    for k, sg in enumerate(segs) for w in (sg["words"] or []) if "start" in w]
            stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
            name = re.sub(r"[^A-Za-z0-9_-]+", "-", project.get("name") or "video").strip("-")[:40] or "video"
            base = os.path.join(self.out_dir, "%s-%s" % (name, stamp))
            srt = None
            if allw and project.get("captions", True):
                srt = base + ".srt"
                open(srt, "w", encoding="utf-8").write(captions(allw))
            out = base + ".mp4"
            vin = video
            if srt and project.get("burn_captions") and _ffmpeg_has("subtitles"):
                burned = os.path.join(tmp, "burned.mp4")
                shutil.copyfile(srt, os.path.join(tmp, "captions.srt"))
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", os.path.basename(vin), "-vf", "subtitles=captions.srt",
                                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "burned.mp4"], cwd=tmp, check=True, capture_output=True)
                vin, rep["captions_burned"] = burned, True
            rb._ff(["-i", vin, "-i", audio, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", "%.3f" % total_v, out])
            ad = rb.duration(out)
            w_, h_ = qf.size(out)
            rep.update(output=os.path.basename(out), captions=os.path.basename(srt) if srt else None, duration_s=round(ad, 2),
                       size="%dx%d" % (w_, h_), fps=round(qf.fps(out), 2), total_s=round(time.time() - t_all, 2), finished=hv._now(),
                       sound_matches_picture=abs(ad - total_v) < 0.15, words=len(allw))
            rep["ok"] = all(r.get("ok") for r in rep["shots"]) and rep["sound_matches_picture"] and \
                (not project.get("height") or rep.get("upscale_ssim", 0) >= 0.85)
            json.dump({"project": project, "report": rep}, open(base + ".json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
            self.lib.record("studio_render", time.time() - t_all)
            self.lib.save()
            progress(len(shots), len(shots), "done")
            return rep
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def outputs(self):
        out = []
        for f in sorted(os.listdir(self.out_dir), reverse=True):
            if f.endswith(".json"):
                try:
                    d = json.load(open(os.path.join(self.out_dir, f), encoding="utf-8"))
                    out.append(dict(d["report"], project_name=d["project"].get("name")))
                except (OSError, ValueError, KeyError):
                    pass
        return out[:200]

    def output_path(self, name):
        p = os.path.realpath(os.path.join(self.out_dir, os.path.basename(name or "")))
        if not p.startswith(os.path.realpath(self.out_dir) + os.sep) or not os.path.isfile(p):
            raise FileNotFoundError(name)
        return p

    def thumb(self, cid):
        c = next((x for x in self.lib.data["clips"] if x["id"] == cid), None)
        if not c:
            raise FileNotFoundError(cid)
        src = os.path.join(self.lib.folder, c["file"])
        t = src[:-4] + ".thumb.jpg"
        if not os.path.exists(t):
            rb._ff(["-ss", str(min(1.0, max(0.0, c.get("duration_s", 1) / 3))), "-i", src, "-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "5", t])
        return t
