#!/usr/bin/env python3
"""The admin's exemplar generator: asks a Google model for examples and files them in the exemplar library.

It runs on its own, started by the admin — never inside the applications or their agents, which stay free of AI models.
The model only produces examples (a talking video, a spoken word, a still, a drill text). Everything after that is
QueryBook's: each take is frozen in the library by its SHA-256 with where it came from, measured by QueryBook's own
checks (`score`), and becomes an exemplar only when the admin approves it.

  python tools/generate_exemplars.py models  --key-file KEY.json
  python tools/generate_exemplars.py plan    --script Pamela-Gemini-test-script.md --skill speech-video:pamela \\
             --model gemini-omni-1.1-flash --image pamela.jpg --subject Pamela --consent "AI-generated portrait supplied by the admin" > plan.json
  python tools/generate_exemplars.py run     --plan plan.json --key-file KEY.json [--takes 3] [--only P01,P02] [--dry-run]
  python tools/generate_exemplars.py import  --plan plan.json --folder clips/   (takes made earlier, e.g. P01.mp4 …)
  python tools/generate_exemplars.py score   --skill speech-video:pamela [--app http://127.0.0.1:8101]
  python tools/generate_exemplars.py status  [--skill …]
  python tools/generate_exemplars.py run-campaign --commons <shared folder>    (started by the Control Panel)

run-campaign follows the switches on the Harvesting page and in the Control Panel: it runs each Google tool the admin switched
on, while the master switch is on and the registry source "google-generative-exemplars" is approved, within each tool's daily
budget, using the plan the admin set for the tool and the Gemini key saved under Harvesting → API keys. It stops when a file
named _runner.stop appears in the exemplar folder (the Control Panel's Stop button) and writes its state to _runner.json.

Kinds and the API each uses: video (Gemini Omni, Interactions API; Veo, predictLongRunning), audio (TTS models,
generateContent), image (image models, generateContent), text (text models, generateContent).
Daily budgets per model (requests per day) are kept in the library folder and never exceeded; a 429 from Google stops
that model for the day. The key is read from the key file and never written anywhere.
"""
import argparse, base64, json, os, re, struct, subprocess, sys, tempfile, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                                    # (the suite ships qbexemplar.py beside this file)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "_core"))
import qbexemplar as X  # noqa: E402

API = "https://generativelanguage.googleapis.com/v1beta"
# requests per day at the account's current tier (Google AI Studio quota page, October 22, 2026); --budget overrides
BUDGET = {"gemini-omni-1.1-flash": 20, "gemini-omni-flash-preview": 20, "veo-3.0-generate-001": 10, "veo-3.0-fast-generate-001": 10,
          "gemini-3.8-flash-tts": 100, "gemini-3.1-flash-tts-preview": 100, "gemini-2.5-pro-preview-tts": 50,
          "gemini-3-pro-image": 250, "gemini-3.1-flash-image": 1000, "gemini-3.1-flash-lite-image": 1000,
          "gemini-3.1-pro-preview": 250, "gemini-3.8-flash": 10000, "gemini-3.5-transcribe": 100}
KIND = lambda model: ("video" if re.search(r"omni|veo", model) else "audio" if "tts" in model else
                      "image" if "image" in model else "text")


# ------------------------------------------------------------------------------------------------ the Google API
def _call(key, url, body=None, timeout=900, raw=False):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), method="GET" if body is None else "POST",
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            return data if raw else json.loads(data)
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(msg)["error"]["message"]
        except Exception:
            pass
        raise ApiError(e.code, X.SECRET.sub("[withheld]", msg[:400]))


class ApiError(RuntimeError):
    def __init__(self, code, msg):
        super().__init__("HTTP %s: %s" % (code, msg)); self.code = code


def _wav(pcm, rate=24000):
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", len(pcm)) + pcm)


def generate(key, model, prompt, image=None, voice=None):
    """one request; returns (bytes, extension)"""
    kind = KIND(model)
    if kind == "video" and "omni" in model:
        inp = ([{"type": "image", "data": base64.b64encode(open(image, "rb").read()).decode(), "mime_type": "image/jpeg"}] if image else [])
        body = {"model": model, "store": False, "input": inp + [{"type": "text", "text": prompt}],
                "response_format": {"type": "video", "aspect_ratio": "16:9"},
                "generation_config": {"video_config": {"task": "image_to_video" if image else "text_to_video"}}}
        r = _call(key, API + "/interactions", body)
        vids = [p for s in r.get("steps", []) if s.get("type") == "model_output" for p in s.get("content", []) if p.get("type") == "video"]
        if not vids:
            raise RuntimeError("no video in the answer (status %s)" % r.get("status"))
        return base64.b64decode(vids[0]["data"]), ".mp4"
    if kind == "video":                                            # Veo: a long-running operation
        inst = {"prompt": prompt}
        if image:
            inst["image"] = {"bytesBase64Encoded": base64.b64encode(open(image, "rb").read()).decode(), "mimeType": "image/jpeg"}
        op = _call(key, "%s/models/%s:predictLongRunning" % (API, model), {"instances": [inst], "parameters": {"aspectRatio": "16:9", "personGeneration": "allow_adult"}})
        t0 = time.time()
        while not op.get("done"):
            if time.time() - t0 > 900:
                raise RuntimeError("timed out after 15 minutes")
            time.sleep(10)
            op = _call(key, "%s/%s" % (API, op["name"]))
        if "error" in op:
            raise RuntimeError("generation failed: %s" % op["error"].get("message"))
        resp = op.get("response", {}); g = resp.get("generateVideoResponse") or resp
        s = (g.get("generatedSamples") or g.get("videos") or [None])[0]
        if not s:
            raise RuntimeError("no video in the answer (perhaps filtered)")
        v = s.get("video", s)
        if v.get("bytesBase64Encoded"):
            return base64.b64decode(v["bytesBase64Encoded"]), ".mp4"
        return _call(key, v["uri"] + ("&" if "?" in v["uri"] else "?") + "alt=media", raw=True, timeout=300), ".mp4"
    parts = [{"text": prompt}]
    if image and kind == "image":
        parts.insert(0, {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(open(image, "rb").read()).decode()}})
    body = {"contents": [{"role": "user", "parts": parts}]}
    if kind == "audio":
        body["generationConfig"] = {"responseModalities": ["AUDIO"],
                                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice or "Kore"}}}}
    elif kind == "image":
        body["generationConfig"] = {"responseModalities": ["IMAGE"]}
    r = _call(key, "%s/models/%s:generateContent" % (API, model), body)
    out = [p for c in r.get("candidates", []) for p in c.get("content", {}).get("parts", [])]
    if kind == "text":
        txt = "".join(p.get("text", "") for p in out).strip()
        if not txt:
            raise RuntimeError("no text in the answer")
        return txt.encode("utf-8"), ".txt"
    blobs = [p["inlineData"] for p in out if p.get("inlineData")]
    if not blobs:
        raise RuntimeError("no %s in the answer" % kind)
    data, mime = base64.b64decode(blobs[0]["data"]), blobs[0].get("mimeType", "")
    if kind == "audio":
        m = re.search(r"rate=(\d+)", mime)
        return (data, ".wav") if mime.startswith("audio/wav") else (_wav(data, int(m.group(1)) if m else 24000), ".wav")
    return data, ".png" if "png" in mime else ".jpg"


# ------------------------------------------------------------------------------------------------ budgets
class Budget:
    def __init__(self, lib, overrides=None):
        self.path = os.path.join(lib.folder, "_budget.json"); self.over = overrides or {}

    def _load(self):
        try:
            return json.load(open(self.path))
        except (OSError, ValueError):
            return {}

    def left(self, model):
        d = self._load().get(time.strftime("%Y-%m-%d", time.gmtime()), {})
        if d.get(model + ":stopped"):
            return 0
        return max(0, int(self.over.get(model, BUDGET.get(model, 10))) - int(d.get(model, 0)))

    def spend(self, model, stopped=False):
        b = self._load(); day = time.strftime("%Y-%m-%d", time.gmtime())
        b = {k: v for k, v in b.items() if k >= time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 86400))}
        d = b.setdefault(day, {})
        if stopped:
            d[model + ":stopped"] = True
        else:
            d[model] = d.get(model, 0) + 1
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        json.dump(b, open(self.path, "w"), indent=1, sort_keys=True)


# ------------------------------------------------------------------------------------------------ plans
def plan_from_script(path, skill, model, image=None, subject=None, consent=None, voice=None):
    """A plan from a test script in the Pamela script format: the fixed instructions + one row per item."""
    text = open(path, encoding="utf-8").read()
    m = re.search(r"## Fixed instructions.*?```\n(.*?)```", text, re.S)
    fixed = m.group(1).strip() if m else ""
    fixed = re.sub(r",\s*[A-Z][a-z]+ —", " —", fixed)           # a first name alone can be mistaken for a real person's
    items = []
    for line in text.splitlines():
        r = re.match(r"\|\s*([A-Z]\d\d)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$", line)
        if not r:
            continue
        code, say, covers = r.groups()
        q = re.search(r"[\"“](.+)[\"”]", say)
        style = (say[:q.start()] if q else say).strip().rstrip(":").strip()
        say_ = q.group(1).strip() if q else ""
        # lists of single words and syllables, said with pauses: speech-to-text hears syllables poorly, so they pass at a lower match
        items.append({"item": code, "script": say_, "style": style, "covers": covers, "min_words": 0.4 if "…" in say_ else None})
    return {"skill": skill, "model": model, "kind": KIND(model), "image": image and os.path.abspath(image), "subject": subject,
            "consent": consent, "voice": voice, "fixed": fixed, "items": items}


def prompt_for(plan, it):
    say = it["script"].replace(" … ", ", ").replace("…", ",")       # spoken pauses as commas (ellipses upset the audio)
    if plan["kind"] in ("audio",):
        return ("Say clearly, at a calm pace%s: %s" % ((", " + it["style"].lower()) if it.get("style") else "", say)) if say else it.get("style", "")
    if plan["kind"] in ("image", "text"):
        return (plan.get("fixed") or "") + "\n\n" + (it.get("prompt") or say or it.get("style", ""))
    fixed = plan.get("fixed") or ""
    if not say:
        return fixed.rsplit("She says exactly:", 1)[0].strip() + "\n\nIn this clip she does not speak: " + it.get("style", "")
    if it.get("style"):
        fixed = fixed.replace("with a relaxed, neutral expression unless the line says otherwise", "in this style: " + it["style"].lower())
    return fixed + ' "' + say + '"'


# ------------------------------------------------------------------------------------------------ commands
def cmd_models(a):
    key = json.load(open(a.key_file))["api_key"]
    for m in _call(key, API + "/models?pageSize=1000").get("models", []):
        n = m["name"].split("/", 1)[1]
        if re.search(r"omni|veo|tts|image|transcribe|pro|flash", n):
            print("%-40s %-6s budget/day %s" % (n, KIND(n), BUDGET.get(n, "-")))


def cmd_plan(a):
    print(json.dumps(plan_from_script(a.script, a.skill, a.model, a.image, a.subject, a.consent, a.voice), indent=1, ensure_ascii=False))


def cmd_run(a):
    plan = json.load(open(a.plan)); lib = X.Library(a.library)
    budget = Budget(lib, dict(kv.split("=") for kv in (a.budget or "").split(",") if "=" in kv))
    key = None if a.dry_run else json.load(open(a.key_file))["api_key"]
    want = [x for x in (a.only or "").split(",") if x]
    made = failed = 0
    for it in plan["items"]:
        if want and it["item"] not in want:
            continue
        have = [t for t in lib.takes(plan["skill"], it["item"]) if t["origin"].get("model") == plan["model"]]
        for take in range(len(have), a.takes):
            prompt = prompt_for(plan, it)
            if a.dry_run:
                print("%s take %d: %s" % (it["item"], take + 1, prompt[-120:].replace("\n", " "))); continue
            if budget.left(plan["model"]) <= 0:
                print("daily budget for %s reached; run again tomorrow (%d made today in this run)" % (plan["model"], made)); return
            t0 = time.time()
            try:
                data, ext = generate(key, plan["model"], prompt, plan.get("image"), plan.get("voice"))
                budget.spend(plan["model"])
            except ApiError as e:
                budget.spend(plan["model"], stopped=e.code == 429)
                print("%s take %d: %s" % (it["item"], take + 1, e)); failed += 1
                if e.code in (401, 403, 429):
                    return
                continue
            except Exception as e:
                budget.spend(plan["model"]); print("%s take %d failed: %s" % (it["item"], take + 1, e)); failed += 1; continue
            with tempfile.TemporaryDirectory() as td:
                f = os.path.join(td, "%s-%d%s" % (it["item"], take + 1, ext)); open(f, "wb").write(data)
                m = lib.add(f, plan["skill"], it["item"], it["script"],
                            {"model": plan["model"], "provider": "Google Gemini API (paid tier)", "prompt": prompt,
                             "created": X._now(), "request_seconds": round(time.time() - t0), "tool": "generate_exemplars.py"},
                            plan.get("subject"), plan.get("consent"), it.get("covers", ""))
            made += 1
            print("%s take %d saved: %s (%d KB, %d s)" % (it["item"], take + 1, m["id"], len(data) // 1024, time.time() - t0), flush=True)
    print("made %d, failed %d" % (made, failed))


def cmd_import(a):
    """file takes made earlier (P01.mp4 …) under the plan's skill, with the origin recorded in the plan"""
    plan = json.load(open(a.plan)); lib = X.Library(a.library); n = 0
    for it in plan["items"]:
        for ext in (".mp4", ".webm", ".wav", ".png", ".jpg", ".txt"):
            f = os.path.join(a.folder, it["item"] + ext)
            if not os.path.exists(f) or (ext == ".txt") != (plan["kind"] == "text"):
                continue
            if True:
                lib.add(f, plan["skill"], it["item"], it["script"],
                        {"model": plan["model"], "provider": "Google Gemini API", "prompt": prompt_for(plan, it), "created": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(f))), "tool": "generate_exemplars.py import"},
                        plan.get("subject"), plan.get("consent"), it.get("covers", ""))
                n += 1; break
    print("imported %d takes into %s" % (n, lib.folder))


def _words(s):
    return re.findall(r"[a-z']+", (s or "").lower().replace("’", "'"))


def word_match(expected, heard):
    a, b = _words(expected), _words(heard)
    if not a:
        return 1.0 if not b else 0.0
    L = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a)):
        for j in range(len(b)):
            L[i + 1][j + 1] = L[i][j] + 1 if a[i] == b[j] else max(L[i][j + 1], L[i + 1][j])
    return round(L[-1][-1] / len(a), 4)


def _app(url, path, body=None):
    req = urllib.request.Request(url + path, data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def cmd_score(a):
    """QueryBook's own checks of each video or audio take: duration, sound, and the words heard (the Language app's
    speech-to-text) against the script. Generators are never asked to judge their own work."""
    lib = X.Library(a.library); n = 0
    plan_items = json.load(open(a.plan))["items"] if a.plan else []
    for m in lib.list(skill=a.skill):
        if m["kind"] not in ("video", "audio") or (m["scores"] and not a.again) or m["status"] == "rejected":
            continue
        path = lib.path(m["id"])
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path], capture_output=True, text=True).stdout or 0)
        wav = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", "-"], capture_output=True).stdout
        peak = max((abs(int.from_bytes(wav[i:i + 2], "little", signed=True)) for i in range(44, len(wav) - 1, 64)), default=0)
        heard = ""
        if m["script"]:
            st = _app(a.app, "/api/speech/transcribe-file", {"audio_b64": "data:audio/wav;base64," + base64.b64encode(wav).decode(), "lang": "en", "mode": "auto"})
            r = {}
            for _ in range(180):
                r = _app(a.app, "/api/speech/transcribe-status?task=" + st["task"])
                if r.get("state") != "running":
                    break
                time.sleep(1)
            if r.get("state") != "done" and not r.get("result"):
                raise SystemExit("speech-to-text failed (%s): %s — nothing was scored for %s" % (r.get("state"), r.get("message"), m["item"]))
            heard = ((r.get("result") or {}).get("transcript") or "").strip()
        wm = word_match(m["script"], heard) if m["script"] else (1.0 if peak < 3000 else 0.0)
        mw = next((it.get("min_words") for it in (plan_items or []) if it["item"] == m["item"] and it.get("min_words")), None) or a.min_words
        checks = [{"name": "words", "ok": wm >= mw, "detail": "heard: " + heard[:200] if m["script"] else "silent clip, peak %d" % peak},
                  {"name": "duration", "ok": dur >= (4 if m["kind"] == "video" else 0.3), "detail": "%.1f s" % dur}]
        lib.score(m["id"], {"words": wm, "has_sound": 1.0 if (peak > 500 or not m["script"]) else 0.0}, checks, "generate_exemplars.py score (speech-to-text)")
        n += 1
        print("%-5s %s  words %.2f  %s" % (m["item"], m["id"], wm, heard[:80]), flush=True)
    print("scored %d takes" % n)


# ------------------------------------------------------------------------------------------------ campaign runner
TOOL_MODELS = {"omni-speech-video": "gemini-omni-1.1-flash", "veo-speech-video": "veo-3.0-fast-generate-001", "tts-pronunciation": "gemini-3.8-flash-tts",
               "image-mouth-shapes": "gemini-3.1-flash-image", "image-pro-poses": "gemini-3-pro-image", "text-drills": "gemini-3.8-flash",
               "transcribe-check": "gemini-3.5-transcribe"}           # (the same catalogue as _core/qbcampaign.py GOOGLE_TOOLS)
SOURCE_KEY = "google-generative-exemplars"


def _switches(commons):
    """the switches, read-only from the shared database (the applications write them)"""
    import sqlite3
    db = sqlite3.connect("file:%s?mode=ro" % os.path.join(commons, "commons.sqlite"), uri=True, timeout=10)
    try:
        st = dict(db.execute("SELECT key, value FROM settings WHERE key LIKE 'gtool%' OR key = 'harvest:master'").fetchall())
        row = db.execute("SELECT status FROM policy_sources WHERE key = ?", (SOURCE_KEY,)).fetchone()
    finally:
        db.close()
    return st, bool(row and row[0] == "approved")


def _switches_file(path):
    """QueryBook 9.64 keeps its switches in campaigns.json (no shared database)"""
    s = json.load(open(path))
    st = {"harvest:master": "running" if s.get("master") == "on" else "stopped"}
    for t, v in (s.get("tools") or {}).items():
        st["gtool:%s" % t] = "on" if v.get("on") else "off"
        if v.get("plan"):
            st["gtool-plan:%s" % t] = v["plan"]
    return st, bool(s.get("google_terms_accepted"))


def _gemini_key(commons):
    try:
        return json.load(open(os.path.join(commons, "api-keys.json"))).get("gemini")
    except (OSError, ValueError):
        return None


def _transcribe(key, model, path):
    wav = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", "-"], capture_output=True).stdout
    body = {"contents": [{"role": "user", "parts": [{"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(wav).decode()}},
                                                    {"text": "Transcribe exactly the words spoken. Reply with the words only."}]}]}
    r = _call(key, "%s/models/%s:generateContent" % (API, model), body, timeout=300)
    return "".join(p.get("text", "") for c in r.get("candidates", []) for p in c.get("content", {}).get("parts", [])).strip()


def _one_step(lib, budget, key, tid, model, plan_path, takes):
    """one request for one switched-on tool; returns what it did (or None when it has nothing to do)"""
    if budget.left(model) <= 0:
        return None
    if tid == "transcribe-check":
        for m in lib.list():
            if m["kind"] in ("video", "audio") and m["script"] and m["status"] != "rejected" and "second_transcript" not in (m.get("advisory") or {}):
                try:
                    heard = _transcribe(key, model, lib.path(m["id"]))
                    budget.spend(model)
                except ApiError as e:
                    budget.spend(model, stopped=e.code == 429); return "transcribe %s: %s" % (m["item"], e)
                lib.advise(m["id"], {"second_transcript": heard[:400], "second_transcript_match": word_match(m["script"], heard)}, model)
                return "transcribed %s %s" % (m["skill"], m["item"])
        return None
    if not plan_path or not os.path.isfile(plan_path):
        return None
    plan = json.load(open(plan_path))
    if plan.get("kind") in ("image", "video") and not (plan.get("image") and os.path.isfile(plan["image"])):
        return None                                    # an avatar's examples need the avatar's own image: set "image" in the plan
    if plan.get("model") != model:
        plan = dict(plan, model=model, kind=KIND(model))
    for it in plan["items"]:
        have = [t for t in lib.takes(plan["skill"], it["item"]) if t["origin"].get("model") == model]
        if len(have) >= takes:
            continue
        prompt = prompt_for(plan, it)
        t0 = time.time()
        try:
            data, ext = generate(key, model, prompt, plan.get("image"), plan.get("voice"))
            budget.spend(model)
        except ApiError as e:
            budget.spend(model, stopped=e.code == 429)
            return "%s %s: %s" % (tid, it["item"], e)
        except Exception as e:
            budget.spend(model); return "%s %s failed: %s" % (tid, it["item"], e)
        with tempfile.TemporaryDirectory() as td:
            f = os.path.join(td, "%s%s" % (it["item"], ext)); open(f, "wb").write(data)
            lib.add(f, plan["skill"], it["item"], it.get("script", ""), {"model": model, "provider": "Google Gemini API (paid tier)", "prompt": prompt,
                    "created": X._now(), "request_seconds": round(time.time() - t0), "tool": "generate_exemplars.py run-campaign (%s)" % tid},
                    plan.get("subject"), plan.get("consent"), it.get("covers", ""))
        return "%s made %s %s" % (tid, plan["skill"], it["item"])
    return None


def cmd_run_campaign(a):
    lib = X.Library(a.library or os.path.join(a.commons, "exemplars"))
    os.makedirs(lib.folder, exist_ok=True)
    budget, stop, state = Budget(lib), os.path.join(lib.folder, "_runner.stop"), os.path.join(lib.folder, "_runner.json")
    if os.path.exists(stop):
        os.remove(stop)
    last = []
    while not os.path.exists(stop):
        note = "idle"
        try:
            st, approved = _switches_file(a.switches) if a.switches else _switches(a.commons)
            key = _gemini_key(a.commons)
            on = [t for t in TOOL_MODELS if st.get("gtool:%s" % t) == "on"]
            if st.get("harvest:master", "running") == "stopped":
                note = "waiting: harvesting is stopped (master switch)"
            elif not on:
                note = "waiting: no Google tool is switched on"
            elif not approved:
                note = "waiting: the Google source is not approved in the policy registry"
            elif not key:
                note = "waiting: save the Gemini key under Harvesting → API keys"
            else:
                did = [d for d in (_one_step(lib, budget, key, t, TOOL_MODELS[t], st.get("gtool-plan:%s" % t), a.takes) for t in on) if d]
                note = "; ".join(did) if did else "all switched-on tools are up to date or at their daily budget"
                last = (did + last)[:20]
        except Exception as e:
            note = "error: %s" % X.SECRET.sub("[withheld]", str(e))[:300]
        today = Budget(lib)._load().get(time.strftime("%Y-%m-%d", time.gmtime()), {})
        with open(state + ".tmp", "w") as f:
            json.dump({"heartbeat": time.time(), "pid": os.getpid(), "note": note, "recent": last, "today": {k: v for k, v in today.items() if ":" not in k}}, f)
        os.replace(state + ".tmp", state)
        time.sleep(a.pause if note.startswith(("made", "transcribed")) or " made " in note else a.idle)
    os.remove(stop)
    print("stopped")


def cmd_status(a):
    lib = X.Library(a.library)
    print(json.dumps(lib.summary(), indent=1))
    for p in lib.proposals(a.skill):
        print("proposal: %(skill)s %(item)s -> %(proposed)s (overall %(overall)s)" % p)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--library", default=None, help="exemplar library folder (default: the shared folder)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("models"); s.add_argument("--key-file", required=True)
    s = sp.add_parser("plan"); s.add_argument("--script", required=True); s.add_argument("--skill", required=True); s.add_argument("--model", required=True)
    s.add_argument("--image"); s.add_argument("--subject"); s.add_argument("--consent"); s.add_argument("--voice")
    s = sp.add_parser("run"); s.add_argument("--plan", required=True); s.add_argument("--key-file"); s.add_argument("--takes", type=int, default=1)
    s.add_argument("--only"); s.add_argument("--dry-run", action="store_true"); s.add_argument("--budget", help="model=requests per day,…")
    s = sp.add_parser("import"); s.add_argument("--plan", required=True); s.add_argument("--folder", required=True)
    s = sp.add_parser("score"); s.add_argument("--skill"); s.add_argument("--app", default="http://127.0.0.1:8101"); s.add_argument("--plan", help="the plan, for per-item thresholds")
    s.add_argument("--min-words", type=float, default=0.8); s.add_argument("--again", action="store_true")
    s = sp.add_parser("status"); s.add_argument("--skill")
    s = sp.add_parser("run-campaign"); s.add_argument("--commons", required=True); s.add_argument("--takes", type=int, default=1)
    s.add_argument("--switches", help="a campaigns.json to read the switches from (QueryBook 9.64) instead of the shared database")
    s.add_argument("--pause", type=float, default=5.0); s.add_argument("--idle", type=float, default=30.0)
    a = ap.parse_args(argv)
    if a.cmd == "run" and not a.dry_run and not a.key_file:
        ap.error("run needs --key-file (or --dry-run)")
    {"models": cmd_models, "plan": cmd_plan, "run": cmd_run, "import": cmd_import, "score": cmd_score, "status": cmd_status,
     "run-campaign": cmd_run_campaign}[a.cmd](a)


if __name__ == "__main__":
    main()
