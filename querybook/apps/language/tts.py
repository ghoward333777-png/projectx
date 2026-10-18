"""Speech generation — one voice profile, many engines, every request shown before it is sent.

A VOICE PROFILE holds everything a voice can carry: language, accent (dialect), emotion and its
intensity, tone, speaking rate, pitch, volume, pauses, articulation, tremble, hoarseness,
breathiness, whisper and voice age. Each engine receives the profile in its own terms:

    offline   espeak-ng (any OS), the prototype's formant voice (no install at all),
              Windows SAPI, macOS `say`
    cloud     Google Gemini TTS (30 voices, natural-language direction), Google Cloud
              Text-to-Speech (SSML + audio config, custom voices behind the consent gate),
              ElevenLabs (all models, voice settings, v3 audio tags), OpenAI (gpt-4o-mini-tts
              instructions), Microsoft Azure Speech (SSML styles, style degree, age roles),
              Amazon Polly (SSML effects, all engines, signed with AWS Signature V4)

Every engine is asked for uncompressed audio (WAV/PCM), so the controls an engine lacks —
tremble, hoarseness, breath, age, volume, pauses — are added afterwards by QueryBook's own
deterministic post-processing (voicedsp.apply_effects). plan() returns, for each control,
whether it is NATIVE to the engine, ADDED by post-processing, or NOT AVAILABLE, plus the exact
request (keys removed). Keys live only in the data folder (speech_keys.json, owner-only) or the
environment, and are never returned, logged or shown.
"""
import base64, datetime, hashlib, hmac, json, os, platform, re, shutil, subprocess, tempfile, time, urllib.error, urllib.parse, urllib.request
from xml.sax.saxutils import escape as xml_escape

import dialect
import speech
import voicedsp

# ------------------------------------------------------------------ the voice profile
EMOTIONS = ["neutral", "happy", "sad", "angry", "fearful", "calm", "excited", "tender", "serious", "surprised", "disgusted"]
TONES = ["neutral", "warm", "bright", "firm", "soft", "formal", "casual", "authoritative", "playful"]
ARTICULATION = ["relaxed", "normal", "precise"]
PROFILE_DEFAULT = {"lang": "en", "accent": "", "emotion": "neutral", "intensity": 0.5, "tone": "neutral", "rate": 1.0,
                   "pitch_st": 0.0, "volume_db": 0.0, "pause_scale": 1.0, "articulation": "normal", "tremble": 0.0,
                   "hoarse": 0.0, "breath": 0.0, "age": 0.0, "whisper": False, "gender": "any"}
CONTROLS = [  # (key, label, description)
    ("emotion", "Emotion", "the feeling carried by the voice"), ("intensity", "Emotion strength", "0 = hint, 1 = strong"),
    ("tone", "Tone", "overall manner"), ("accent", "Accent", "dialect / regional accent"),
    ("rate", "Speed", "1.0 = normal"), ("pitch_st", "Pitch", "semitones up or down"), ("volume_db", "Volume", "decibels"),
    ("pause_scale", "Pauses", "1.0 = normal, 2.0 = twice as long"), ("articulation", "Articulation", "relaxed / normal / precise"),
    ("tremble", "Tremble", "shaking voice, 0–1"), ("hoarse", "Hoarseness", "rough voice, 0–1"), ("breath", "Breathiness", "airy voice, 0–1"),
    ("whisper", "Whisper", "no voicing"), ("age", "Voice age", "0 = young adult, 1 = elderly"), ("gender", "Voice", "female / male / any"),
]

# per-emotion offsets at full intensity: semitones, rate factor, dB, extra tremble, hoarse, breath
_EMO = {"neutral": (0, 1.0, 0, 0, 0, 0), "happy": (3, 1.10, 2, 0, 0, 0), "sad": (-3, 0.85, -4, 0.1, 0, 0.25),
        "angry": (1, 1.10, 5, 0, 0.25, 0), "fearful": (4, 1.15, 0, 0.45, 0, 0.15), "calm": (-1, 0.90, -2, 0, 0, 0.05),
        "excited": (5, 1.20, 4, 0, 0, 0), "tender": (-1, 0.90, -3, 0, 0, 0.2), "serious": (-2, 0.95, 0, 0, 0, 0),
        "surprised": (5, 1.05, 2, 0, 0, 0), "disgusted": (-2, 0.95, 1, 0, 0.15, 0)}


def profile(p):
    out = dict(PROFILE_DEFAULT)
    for k, v in (p or {}).items():
        if k in out and v is not None and v != "":
            out[k] = v
    for k in ("intensity", "rate", "pitch_st", "volume_db", "pause_scale", "tremble", "hoarse", "breath", "age"):
        out[k] = float(out[k])
    out["whisper"] = out["whisper"] in (True, "true", "1", 1, "on")
    out["intensity"] = min(1.0, max(0.0, out["intensity"]))
    out["rate"] = min(3.0, max(0.3, out["rate"]))
    out["pitch_st"] = min(12.0, max(-12.0, out["pitch_st"]))
    out["volume_db"] = min(12.0, max(-30.0, out["volume_db"]))
    out["pause_scale"] = min(4.0, max(0.25, out["pause_scale"]))
    for k in ("tremble", "hoarse", "breath", "age"):
        out[k] = min(1.0, max(0.0, out[k]))
    if out["emotion"] not in _EMO:
        out["emotion"] = "neutral"
    return out


def effective(p):
    """The profile with the emotion folded into concrete numbers (used by engines without emotion)."""
    st, rf, db, tr, ho, br = _EMO[p["emotion"]]
    k = p["intensity"]
    art = {"relaxed": 1.05, "normal": 1.0, "precise": 0.9}.get(p["articulation"], 1.0)
    return {"pitch_st": p["pitch_st"] + st * k - 2.0 * p["age"], "rate": p["rate"] * (1 + (rf - 1) * k) * art * (1 - 0.15 * p["age"]),
            "volume_db": p["volume_db"] + db * k, "tremble": min(1, p["tremble"] + tr * k), "hoarse": min(1, p["hoarse"] + ho * k),
            "breath": min(1, p["breath"] + br * k), "age": p["age"], "pause_scale": p["pause_scale"] * (1.25 if p["articulation"] == "precise" else 1.0)}


def describe(p, for_engine=""):
    """A natural-language performance direction (Gemini prompt / OpenAI instructions)."""
    parts = []
    if p["emotion"] != "neutral":
        strength = "slightly " if p["intensity"] < 0.35 else "very " if p["intensity"] > 0.75 else ""
        parts.append("sound %s%s" % (strength, p["emotion"]))
    if p["tone"] != "neutral":
        parts.append("use a %s tone" % p["tone"])
    if p["accent"]:
        parts.append("speak " + (dialect.cloud_style(p["accent"]) or ("with a %s accent" % p["accent"])))
    if abs(p["rate"] - 1) > 0.05:
        parts.append("speak %s (about %.0f%% of normal speed)" % ("slowly" if p["rate"] < 1 else "quickly", 100 * p["rate"]))
    if abs(p["pitch_st"]) >= 1:
        parts.append("use a %s pitch" % ("higher" if p["pitch_st"] > 0 else "lower"))
    if abs(p["volume_db"]) >= 2:
        parts.append("speak %s" % ("loudly" if p["volume_db"] > 0 else "quietly"))
    if p["pause_scale"] >= 1.3:
        parts.append("take long, deliberate pauses")
    elif p["pause_scale"] <= 0.75:
        parts.append("keep pauses short")
    if p["articulation"] != "normal":
        parts.append("articulate %s" % ("every consonant crisply" if p["articulation"] == "precise" else "in a relaxed, casual way"))
    if p["tremble"] >= 0.15:
        parts.append("let the voice %s" % ("tremble noticeably" if p["tremble"] > 0.5 else "tremble slightly"))
    if p["hoarse"] >= 0.15:
        parts.append("with a %s voice" % ("very hoarse, rough" if p["hoarse"] > 0.5 else "slightly hoarse"))
    if p["breath"] >= 0.15:
        parts.append("breathy")
    if p["whisper"]:
        parts.append("whisper")
    if p["age"] >= 0.15:
        parts.append("sound like %s" % ("an elderly person" if p["age"] > 0.66 else "a middle-aged person"))
    return ("; ".join(parts)).capitalize() if parts else ""


# ------------------------------------------------------------------ keys (never returned)
KEY_FIELDS = {
    "google_gemini": [("api_key", "GEMINI_API_KEY")],
    "google_cloud": [("api_key", "GOOGLE_TTS_API_KEY")],
    "elevenlabs": [("api_key", "ELEVENLABS_API_KEY")],
    "openai": [("api_key", "OPENAI_API_KEY")],
    "azure": [("api_key", "AZURE_SPEECH_KEY"), ("region", "AZURE_SPEECH_REGION")],
    "polly": [("access_key_id", "AWS_ACCESS_KEY_ID"), ("secret_access_key", "AWS_SECRET_ACCESS_KEY"), ("region", "AWS_REGION")],
    "heygen": [("api_key", "HEYGEN_API_KEY")],          # talking-photo video (Author Narrator)
    "did": [("api_key", "DID_API_KEY")],                # D-ID talks (Author Narrator)
}
SECRET_FIELDS = {"api_key", "secret_access_key", "access_key_id"}


class Keys:
    def __init__(self, folder):
        self.path = os.path.join(folder, "speech_keys.json")

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f) or {}
        except (OSError, ValueError):
            return {}

    def get(self, provider):
        cfg = self._load().get(provider) or {}
        out = {}
        for field, env in KEY_FIELDS.get(provider, []):
            out[field] = cfg.get(field) or os.environ.get(env) or ""      # settings saved in the app win over the environment
        if provider in ("google_cloud", "google_gemini") and not out.get("api_key"):
            # one Google key for everything: the key saved under Diagnostics → Google Cloud
            try:
                with open(os.path.join(os.path.dirname(self.path), "google.json"), encoding="utf-8") as f:
                    out["api_key"] = (json.load(f) or {}).get("api_key") or ""
            except (OSError, ValueError):
                pass
            out["api_key"] = out["api_key"] or os.environ.get("GOOGLE_API_KEY") or ""
        out["custom_voices"] = cfg.get("custom_voices") or {}
        return out

    def configured(self, provider):
        k = self.get(provider)
        return all(k.get(f) for f, _ in KEY_FIELDS.get(provider, [])) if provider in KEY_FIELDS else True

    def save(self, provider, values):
        if provider not in KEY_FIELDS:
            raise ValueError("unknown provider")
        cfg = self._load()
        ent = cfg.get(provider) or {}
        for field, _env in KEY_FIELDS[provider]:
            v = (values or {}).get(field)
            if v is not None and str(v).strip():
                ent[field] = str(v).strip()
        cfg[provider] = ent
        self._write(cfg)

    def forget(self, provider):
        cfg = self._load()
        cfg.pop(provider, None)
        self._write(cfg)

    def save_custom_voice(self, name, cloning_key, language):
        cfg = self._load()
        ent = cfg.get("google_cloud") or {}
        cv = ent.get("custom_voices") or {}
        cv[name] = {"cloning_key": cloning_key, "language": language, "created": int(time.time())}
        ent["custom_voices"] = cv
        cfg["google_cloud"] = ent
        self._write(cfg)

    def _write(self, cfg):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)

    # ---- the prototype kept its keys in qb_tts_keys.json next to its program (never committed)
    PROTO_FILE = "qb_tts_keys.json"

    @staticmethod
    def prototype_candidates(extra=None):
        """Where the old QueryBook's key file may be on this computer (searched a few levels deep, quickly)."""
        import glob
        home = os.path.expanduser("~")
        roots = [extra] if extra else []
        roots += [home, os.path.join(home, "Desktop"), os.path.join(home, "Downloads"), os.path.join(home, "Documents"),
                  os.path.join(home, "OneDrive"), os.path.join(home, "OneDrive", "Desktop"), os.path.join(home, "OneDrive", "Documents")]
        if os.name == "nt":
            roots += ["%s:\\" % d for d in "CDEFG"]
        found, seen = [], set()
        for r in roots:
            if not r or not os.path.isdir(r):
                continue
            depth = (1, 2) if (len(r) <= 3 and r.endswith(("\\", "/"))) else (1, 2, 3)      # drive roots: 2 levels; user folders: 3
            pats = [os.path.join(r, Keys.PROTO_FILE)] + [os.path.join(r, *(["*"] * k), Keys.PROTO_FILE) for k in depth]
            for pat in pats:
                for f in glob.glob(pat):
                    a = os.path.abspath(f)
                    if a not in seen and os.path.isfile(a):
                        seen.add(a)
                        found.append(a)
            if len(found) > 20:
                break
        return sorted(found, key=lambda f: -os.path.getmtime(f))

    def import_prototype(self, folder=None):
        """Copy the old QueryBook's Google / ElevenLabs keys (and Google custom voices) into this app. Returns what
        was found — never the keys themselves."""
        if folder and os.path.isfile(folder):
            files = [os.path.abspath(folder)]
        elif folder and os.path.isfile(os.path.join(folder, self.PROTO_FILE)):
            files = [os.path.join(os.path.abspath(folder), self.PROTO_FILE)]
        else:
            files = self.prototype_candidates(folder)
        env = {"google": os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_TTS_API_KEY"), "elevenlabs": os.environ.get("ELEVENLABS_API_KEY")}
        imported, used = [], None
        for f in files:
            try:
                with open(f, encoding="utf-8") as fh:
                    old = json.load(fh) or {}
            except (OSError, ValueError):
                continue
            g, e = old.get("google") or {}, old.get("elevenlabs") or {}
            if not (g.get("key") or e.get("key") or g.get("custom_voices")):
                continue
            used = f
            if g.get("key"):
                # the prototype used one Google key for Gemini TTS and for Cloud Text-to-Speech custom voices
                self.save("google_gemini", {"api_key": g["key"]})
                self.save("google_cloud", {"api_key": g["key"]})
                imported += ["Google Gemini TTS", "Google Cloud Text-to-Speech (same key)"]
            for name, cv in (g.get("custom_voices") or {}).items():
                if cv.get("cloning_key"):
                    self.save_custom_voice(name, cv["cloning_key"], cv.get("language", "en-US"))
                    imported.append("Google custom voice '%s'" % name)
            if e.get("key"):
                self.save("elevenlabs", {"api_key": e["key"]})
                imported.append("ElevenLabs")
            break
        if not used and (env["google"] or env["elevenlabs"]):
            if env["google"]:
                self.save("google_gemini", {"api_key": env["google"]}); self.save("google_cloud", {"api_key": env["google"]})
                imported += ["Google (from the environment)"]
            if env["elevenlabs"]:
                self.save("elevenlabs", {"api_key": env["elevenlabs"]}); imported.append("ElevenLabs (from the environment)")
            used = "environment variables"
        return {"found": used, "searched": len(files), "imported": imported,
                "defaults_noted": ({"google_voice": g.get("voice"), "google_model": g.get("model"), "elevenlabs_voice": e.get("voice"),
                                    "elevenlabs_model": e.get("model")} if used and used != "environment variables" else None)}

    def public(self):
        out = {}
        for prov, fields in KEY_FIELDS.items():
            k = self.get(prov)
            out[prov] = {"configured": all(k.get(f) for f, _ in fields),
                         "fields": [{"field": f, "set": bool(k.get(f)), "from_environment": bool(os.environ.get(env)) and not (self._load().get(prov) or {}).get(f),
                                     "value": (k.get(f) if f not in SECRET_FIELDS else None)} for f, env in fields]}
            if prov == "google_cloud":
                out[prov]["custom_voices"] = sorted(k.get("custom_voices", {}).keys())
        return out

    def secrets(self):
        vals = []
        cfg = self._load()
        for prov, fields in KEY_FIELDS.items():
            k = self.get(prov)
            vals += [k.get(f) for f, _ in fields if f in SECRET_FIELDS and k.get(f)]
            vals += [v.get("cloning_key") for v in (cfg.get(prov) or {}).get("custom_voices", {}).values() if v.get("cloning_key")]
        return [v for v in vals if len(v) >= 6]


def scrub(text, keys):
    t = str(text)
    for s in keys.secrets():
        t = t.replace(s, "<key>")
    t = re.sub(r"(?i)(key=)[A-Za-z0-9_\-]{8,}", r"\1<key>", t)
    return t


# ------------------------------------------------------------------ engines
def _base(provider, default):
    """Endpoint base; QB_TTS_BASE_<PROVIDER> overrides it (used by the self-test's stand-in server)."""
    return os.environ.get("QB_TTS_BASE_" + provider.upper(), default).rstrip("/")


def _http(url, body, headers, method="POST", timeout=60):
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        m = re.search(r"Requests to this API (\S+) .*are blocked", txt)
        if e.code == 403 and m:
            raise RuntimeError("your Google API key is not allowed to use %s (add it under the key's API restrictions)" % m.group(1))
        m = re.search(r"(\S+\.googleapis\.com|[A-Z][\w ]+ API) has not been used in project \d+ before or it is disabled", txt)
        if e.code == 403 and m:
            raise RuntimeError("%s is not switched on in your Google project (APIs & Services → Library → Enable)" % m.group(1))
        raise RuntimeError("HTTP %s: %s" % (e.code, txt[:300]))


SPEECH_LANG = {"en": "en-US", "es": "es-ES", "fr": "fr-FR", "de": "de-DE", "it": "it-IT", "pt": "pt-PT", "nl": "nl-NL", "sv": "sv-SE",
               "da": "da-DK", "no": "nb-NO", "fi": "fi-FI", "pl": "pl-PL", "cs": "cs-CZ", "el": "el-GR", "ro": "ro-RO", "hu": "hu-HU", "ca": "ca-ES"}
DIALECT_LOCALE = {"en-US-south": "en-US", "en-US-aae": "en-US", "en-GB-rp": "en-GB", "en-GB-scot": "en-GB", "en-GB-cockney": "en-GB", "es-AR": "es-US"}


def locale(p):
    return DIALECT_LOCALE.get(p["accent"]) or SPEECH_LANG.get(p["lang"], "en-US")


def _ssml_body(text, pause_scale, break_tag="<break time='%dms'/>"):
    """Text → SSML-safe body with breaks after punctuation, scaled by the pause setting."""
    t = xml_escape(text)
    if abs(pause_scale - 1.0) < 0.05:
        return t
    t = re.sub(r"([,;:])\s+", lambda m: m.group(1) + " " + break_tag % int(250 * pause_scale) + " ", t)
    t = re.sub(r"([.!?])\s+", lambda m: m.group(1) + " " + break_tag % int(500 * pause_scale) + " ", t)
    return t


def P(key, label, kind, default=None, lo=None, hi=None, step=None, options=None, help=""):
    """One advanced, engine-specific control (rendered by the page; blank = use the voice profile's value)."""
    return {"key": key, "label": label, "type": kind, "default": default, "min": lo, "max": hi, "step": step, "options": options or [], "help": help}


class Engine:
    id = ""; name = ""; kind = "offline"; needs_key = False
    params = []           # advanced controls specific to this engine
    native = set()        # profile keys handled by the engine itself
    voices_static = []
    notes = ""
    models = []

    def available(self, keys):
        return True, ""

    def request(self, text, p, voice, model, keys):
        """→ (description of the request with keys removed, callable that performs it and returns WAV bytes)."""
        raise NotImplementedError

    def voices(self, keys, lang="en"):
        return self.voices_static


POST_FX = {"tremble", "hoarse", "breath", "age", "volume_db", "pause_scale", "pitch_st", "rate"}
# engines whose pitch / speed setting is exact (others only describe it, so the match loop corrects them afterwards)
PRECISE_PITCH = {"espeak", "formant", "sapi", "google_cloud", "azure"}
PRECISE_RATE = {"espeak", "formant", "sapi", "say", "google_cloud", "azure", "polly", "elevenlabs"}


def coverage(engine, p):
    """For each control: native / added by post-processing / not available."""
    rows = []
    for key, label, desc in CONTROLS:
        v = p.get(key)
        default = PROFILE_DEFAULT.get(key)
        used = v != default
        if key in engine.native:
            how = "native"
        elif key in POST_FX:
            how = "added by QueryBook post-processing"
        elif key == "emotion" and engine.id in ("espeak", "formant", "sapi", "say", "google_cloud", "polly"):
            how = "approximated: pitch, speed, volume and voice quality are set from the emotion"
        else:
            how = "not available on this engine"
        rows.append({"control": key, "label": label, "value": v, "in_use": used, "how": how})
    return rows


# ---- offline: espeak-ng
class Espeak(Engine):
    id, name, kind = "espeak", "espeak-ng — synthetic voice (default, offline, bundled on Windows)", "offline"
    native = {"lang", "rate", "pitch_st", "volume_db", "pause_scale", "accent", "whisper", "articulation", "gender"}
    notes = "Free, offline, 100+ languages. Accents through dialect voices; variants for whisper, croak (hoarse) and grandpa (age)."
    params = [P("speed_wpm", "Speed (words per minute)", "number", None, 80, 450, 5), P("pitch", "Pitch (0–99)", "number", None, 0, 99, 1),
              P("amplitude", "Amplitude (0–200)", "number", None, 0, 200, 5), P("word_gap", "Gap between words (×10 ms)", "number", None, 0, 50, 1),
              P("voice_name", "espeak voice (e.g. en-gb, en-us+f3)", "text", None, help="overrides language + variant")]

    def available(self, keys):
        return (bool(speech.find_espeak()), "" if speech.find_espeak() else "espeak-ng not found — " + speech.status()["hint"])

    def voices(self, keys, lang="en"):
        return [{"id": "", "name": "Language default"}] + [{"id": v, "name": v} for v in
                ("f1", "f2", "f3", "f4", "f5", "m1", "m2", "m3", "m4", "m5", "m6", "m7", "klatt", "klatt2", "klatt3", "grandpa", "croak", "whisper", "female_whisper")]

    def args(self, p, voice, adv=None):
        adv = adv or {}
        e = effective(p)
        import vocab
        base = vocab.LANGUAGES.get(p["lang"], {}).get("espeak", "en")
        rate_wpm, pitch = 175 * e["rate"], 50 + 4 * e["pitch_st"]
        if p["accent"] and dialect.espeak_opts(p["accent"]):
            o = dialect.espeak_opts(p["accent"])
            base = o.get("voice") or base
            rate_wpm *= (o.get("rate") or 175) / 175.0
            pitch += (o.get("pitch") or 50) - 50
        variant = voice or ""
        if p["whisper"]:
            variant = "female_whisper" if p["gender"] == "female" else "whisper"
        elif not variant and p["gender"] in ("female", "male"):
            variant = "f3" if p["gender"] == "female" else "m3"
        if not voice and e["hoarse"] >= 0.6 and not p["whisper"]:
            variant = "croak"
        if not voice and p["age"] >= 0.66 and not p["whisper"]:
            variant = "grandpa"
        v = base + ("+" + variant if variant else "")
        amp = int(max(0, min(200, 100 * 10 ** (e["volume_db"] / 20.0))))
        gap = max(0, int(round((e["pause_scale"] - 1) * 8)))
        v = adv.get("voice_name") or v
        rate_wpm = adv.get("speed_wpm") if adv.get("speed_wpm") not in (None, "") else rate_wpm
        pitch = adv.get("pitch") if adv.get("pitch") not in (None, "") else pitch
        amp = adv.get("amplitude") if adv.get("amplitude") not in (None, "") else amp
        gap = adv.get("word_gap") if adv.get("word_gap") not in (None, "") else gap
        return ["-v", v, "-s", str(int(max(80, min(450, float(rate_wpm))))), "-p", str(int(max(0, min(99, float(pitch))))), "-a", str(int(float(amp))), "-g", str(int(float(gap)))], e

    def request(self, text, p, voice, model, keys, adv=None):
        a, e = self.args(p, voice, adv)
        desc = {"command": "espeak-ng " + " ".join(a) + " -w <file.wav> <text>", "arguments": a}

        def run():
            return speech.synth(a, text, 60)          # through a file, never stdout (Windows text mode damages audio)
        return desc, run, {"volume_db": 0.0, "pause_scale": 1.0}   # volume and pauses handled natively


# ---- offline: the prototype's formant voice (no install at all)
class Formant(Engine):
    id, name, kind = "formant", "QueryBook formant voice (offline, no install)", "offline"
    native = {"lang", "rate", "pitch_st", "accent", "pause_scale"}
    notes = "The prototype's own source-filter synthesizer, driven by the builder's learned pronunciations. Robotic but needs nothing installed; accents are applied to the IPA by the dialect rules."
    lab = None

    def request(self, text, p, voice, model, keys, adv=None):
        e = effective(p)
        words = re.findall(r"[^\W\d_]+", text, re.UNICODE)[:40]
        ipas, fired = [], []
        for w in words:
            a = self.lab.analyze_pronunciation(w, p["lang"]) if self.lab else {"ipa": "/" + w.lower() + "/"}
            ipa = a.get("ipa") or "/" + w.lower() + "/"
            if p["accent"]:
                ipa, notes = dialect.apply_phonology(ipa, p["accent"])
                fired += notes
            ipas.append(ipa)
        f0 = 118.0 * 2 ** (e["pitch_st"] / 12.0) * (1.6 if p["gender"] == "female" else 1.0)
        desc = {"ipa": ipas, "f0_hz": round(f0, 1), "rate": round(e["rate"], 2), "accent_rules_applied": sorted(set(fired))}
        return desc, (lambda: voicedsp.formant_wav(ipas, f0=f0, rate=e["rate"], gap_s=0.11 * e["pause_scale"])), {"pause_scale": 1.0}


# ---- offline: Windows SAPI and macOS say
class Sapi(Engine):
    id, name, kind = "sapi", "Windows voices (SAPI, offline)", "offline"
    native = {"lang", "rate", "pitch_st", "volume_db", "pause_scale", "gender", "age"}
    notes = "Uses the voices installed in Windows. Voice age and gender pick the closest installed voice (Adult / Senior / Child hints)."

    def available(self, keys):
        return (platform.system() == "Windows", "" if platform.system() == "Windows" else "only on Windows")

    def request(self, text, p, voice, model, keys, adv=None):
        e = effective(p)
        loc = locale(p)
        ssml = ("<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='%s'><prosody rate='%+d%%' pitch='%+dst' volume='%+.1fdB'>%s</prosody></speak>"
                % (loc, int(100 * (e["rate"] - 1)), int(round(e["pitch_st"])), e["volume_db"], _ssml_body(text, e["pause_scale"])))
        age = "Senior" if p["age"] >= 0.66 else "Adult"
        gender = {"female": "Female", "male": "Male"}.get(p["gender"], "NotSet")
        tmp = os.path.join(tempfile.gettempdir(), "qb_sapi_%d.wav" % os.getpid())
        ps = ("Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              "try { $s.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::%s, [System.Speech.Synthesis.VoiceAge]::%s, 0, [System.Globalization.CultureInfo]::new('%s')) } catch {}; "
              "%s$s.SetOutputToWaveFile('%s'); $s.SpeakSsml('%s'); $s.Dispose()"
              % (gender, age, loc, ("$s.SelectVoice('%s'); " % voice.replace("'", "''")) if voice else "", tmp.replace("'", "''"), ssml.replace("'", "''")))
        desc = {"ssml": ssml, "voice_hints": {"gender": gender, "age": age, "culture": loc}, "voice": voice or "(best match)"}

        def run():
            kw = {"creationflags": 0x08000000}
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=60, **kw)
            if r.returncode or not os.path.exists(tmp):
                raise RuntimeError("Windows speech failed: %s" % r.stderr.decode("utf-8", "replace")[:200])
            with open(tmp, "rb") as f:
                data = f.read()
            os.remove(tmp)
            return data
        return desc, run, {"volume_db": 0.0, "pause_scale": 1.0}


class Say(Engine):
    id, name, kind = "say", "macOS voices (say, offline)", "offline"
    native = {"lang", "rate"}
    notes = "Uses the voices installed in macOS (System Settings → Accessibility → Spoken Content)."

    def available(self, keys):
        ok = platform.system() == "Darwin" and bool(shutil.which("say"))
        return ok, "" if ok else "only on macOS"

    def request(self, text, p, voice, model, keys, adv=None):
        e = effective(p)
        a = ["-r", str(int(180 * e["rate"]))] + (["-v", voice] if voice else [])
        desc = {"command": "say " + " ".join(a) + " -o out.aiff <text>; afconvert -f WAVE -d LEI16"}

        def run():
            d = tempfile.mkdtemp(prefix="qb-say-")
            aiff, wav = os.path.join(d, "o.aiff"), os.path.join(d, "o.wav")
            subprocess.run(["say"] + a + ["-o", aiff, text], check=True, capture_output=True, timeout=60)
            subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16", aiff, wav], check=True, capture_output=True, timeout=60)
            with open(wav, "rb") as f:
                data = f.read()
            shutil.rmtree(d, ignore_errors=True)
            return data
        return desc, run, {}


# ---- Google Gemini TTS
GEMINI_VOICES = [("Zephyr", "Bright"), ("Puck", "Upbeat"), ("Charon", "Informative"), ("Kore", "Firm"), ("Fenrir", "Excitable"),
                 ("Leda", "Youthful"), ("Orus", "Firm"), ("Aoede", "Breezy"), ("Callirrhoe", "Easy-going"), ("Autonoe", "Bright"),
                 ("Enceladus", "Breathy"), ("Iapetus", "Clear"), ("Umbriel", "Easy-going"), ("Algieba", "Smooth"), ("Despina", "Smooth"),
                 ("Erinome", "Clear"), ("Algenib", "Gravelly"), ("Rasalgethi", "Informative"), ("Laomedeia", "Upbeat"), ("Achernar", "Soft"),
                 ("Alnilam", "Firm"), ("Schedar", "Even"), ("Gacrux", "Mature"), ("Pulcherrima", "Forward"), ("Achird", "Friendly"),
                 ("Zubenelgenubi", "Casual"), ("Vindemiatrix", "Gentle"), ("Sadachbia", "Lively"), ("Sadaltager", "Knowledgeable"), ("Sulafat", "Warm")]


class GoogleGemini(Engine):
    id, name, kind, needs_key = "google_gemini", "Google Gemini TTS (cloud)", "cloud", True
    native = {"lang", "emotion", "intensity", "tone", "accent", "rate", "pitch_st", "volume_db", "pause_scale", "articulation",
              "tremble", "hoarse", "breath", "whisper", "age"}
    models = ["gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts"]
    voices_static = [{"id": n, "name": "%s — %s" % (n, s)} for n, s in GEMINI_VOICES]
    notes = "All 30 prebuilt voices. Every control is passed as a natural-language performance direction; the model decides how to perform it."
    params = [P("direction", "Performance direction (edit freely)", "textarea", None,
                help="Blank = written from the voice profile. Example: 'Say this as a tired old man, slowly, with a trembling, hoarse voice'"),
              P("temperature", "Temperature (variation between takes)", "number", None, 0, 2, 0.05),
              P("language_code", "Language code (BCP-47, e.g. en-GB)", "text", None),
              P("speaker2_voice", "Second speaker voice (dialogue)", "select", None, options=[n for n, _ in GEMINI_VOICES],
                help="With two voices, write the text as 'Speaker1: …' / 'Speaker2: …' lines")]

    def available(self, keys):
        return keys.configured(self.id), "" if keys.configured(self.id) else "add a Gemini API key"

    def request(self, text, p, voice, model, keys, adv=None):
        adv = adv or {}
        model = model or self.models[0]
        voice = voice or "Kore"
        direction = adv.get("direction") or describe(p)
        prompt = (direction + ":\n" + text) if direction else text
        sc = {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}
        if adv.get("speaker2_voice"):
            sc = {"multiSpeakerVoiceConfig": {"speakerVoiceConfigs": [
                {"speaker": "Speaker1", "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
                {"speaker": "Speaker2", "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": adv["speaker2_voice"]}}}]}}
        if adv.get("language_code"):
            sc["languageCode"] = adv["language_code"]
        gc = {"responseModalities": ["AUDIO"], "speechConfig": sc}
        if adv.get("temperature") not in (None, ""):
            gc["temperature"] = float(adv["temperature"])
        body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gc}
        url = _base(self.id, "https://generativelanguage.googleapis.com") + "/v1beta/models/%s:generateContent" % model
        desc = {"POST": url, "headers": {"x-goog-api-key": "<key>", "Content-Type": "application/json"}, "body": body}

        def run():
            raw, _ = _http(url, json.dumps(body).encode("utf-8"), {"x-goog-api-key": keys.get(self.id)["api_key"], "Content-Type": "application/json"})
            data = json.loads(raw)
            part = data["candidates"][0]["content"]["parts"][0]
            inl = part.get("inlineData") or part.get("inline_data")
            mime = inl.get("mimeType") or inl.get("mime_type") or ""
            m = re.search(r"rate=(\d+)", mime)
            return voicedsp.pcm16_to_wav(base64.b64decode(inl["data"]), int(m.group(1)) if m else 24000)
        # the model is asked for every control; nothing extra is post-processed
        return desc, run, {k: 0.0 for k in ("tremble", "hoarse", "breath", "age", "volume_db")} | {"pause_scale": 1.0}


# ---- Google Cloud Text-to-Speech
class GoogleCloud(Engine):
    id, name, kind, needs_key = "google_cloud", "Google Cloud Text-to-Speech (cloud)", "cloud", True
    native = {"lang", "rate", "pitch_st", "volume_db", "pause_scale", "accent", "gender"}
    models = ["(voice decides: Standard, WaveNet, Neural2, Studio, Chirp 3 HD, Journey)"]
    notes = ("SSML with prosody and breaks; audio config with speaking rate, pitch, volume gain, sample rate and device effects profile. "
             "Chirp 3 HD and Journey voices ignore SSML pitch. Custom (cloned) voices need the speaker's consent.")
    EFFECTS = ["", "wearable-class-device", "handset-class-device", "headphone-class-device", "small-bluetooth-speaker-class-device",
               "medium-bluetooth-speaker-class-device", "large-home-entertainment-class-device", "large-automotive-class-device", "telephony-class-application"]

    def available(self, keys):
        return keys.configured(self.id), "" if keys.configured(self.id) else "add a Google Cloud API key (Text-to-Speech API enabled)"

    def voices(self, keys, lang="en"):
        out = [{"id": "", "name": "Default for the language"}]
        out += [{"id": "custom:" + n, "name": "Custom voice: " + n} for n in sorted(keys.get(self.id).get("custom_voices", {}))]
        if not keys.configured(self.id):
            return out
        try:
            raw, _ = _http(_base(self.id, "https://texttospeech.googleapis.com") + "/v1/voices?languageCode=" + urllib.parse.quote(SPEECH_LANG.get(lang, "en-US")),
                           None, {"X-Goog-Api-Key": keys.get(self.id)["api_key"]}, method="GET", timeout=20)
            for v in json.loads(raw).get("voices", []):
                out.append({"id": v["name"], "name": "%s (%s, %s)" % (v["name"], v.get("ssmlGender", "").lower(), ",".join(v.get("languageCodes", [])))})
        except Exception as e:
            out.append({"id": "", "name": "voice list unavailable: %s" % scrub(e, keys)})
        return out

    params = [P("speaking_rate", "Speaking rate (0.25–4.0)", "number", None, 0.25, 4.0, 0.05, help="audioConfig.speakingRate"),
              P("pitch", "Pitch (−20 to +20 semitones)", "number", None, -20, 20, 0.5, help="audioConfig.pitch (not on Chirp 3 HD / Journey)"),
              P("volume_gain_db", "Volume gain (−96 to +16 dB)", "number", None, -96, 16, 0.5),
              P("sample_rate", "Sample rate (Hz)", "select", None, options=["8000", "16000", "22050", "24000", "44100", "48000"]),
              P("effects_profile", "Device effects profile", "select", None, options=EFFECTS[1:]),
              P("language_code", "Language code (e.g. en-GB, en-IN)", "text", None),
              P("ssml", "SSML (edit freely)", "textarea", None, help="Blank = written from the voice profile")]

    def request(self, text, p, voice, model, keys, adv=None):
        adv = adv or {}
        effects_profile = adv.get("effects_profile") or ""
        e = effective(p)
        loc = adv.get("language_code") or locale(p)
        if voice and voice.startswith("custom:"):
            cv = keys.get(self.id)["custom_voices"].get(voice[7:]) or {}
            vsel = {"languageCode": cv.get("language", loc), "voiceClone": {"voiceCloningKey": "<custom voice key>"}}
            path = "/v1beta1/text:synthesize"
        else:
            vsel = {"languageCode": loc}
            if voice:
                vsel["name"] = voice
            elif p["gender"] in ("female", "male"):
                vsel["ssmlGender"] = p["gender"].upper()
            path = "/v1/text:synthesize"
        ssml = adv.get("ssml") or "<speak><prosody rate='%d%%' pitch='%+.1fst'>%s</prosody></speak>" % (int(100 * e["rate"]), e["pitch_st"], _ssml_body(text, e["pause_scale"]))
        audio = {"audioEncoding": "LINEAR16", "sampleRateHertz": int(adv.get("sample_rate") or 24000),
                 "volumeGainDb": round(max(-96, min(16, float(adv["volume_gain_db"]) if adv.get("volume_gain_db") not in (None, "") else e["volume_db"])), 1)}
        if adv.get("speaking_rate") not in (None, ""):
            audio["speakingRate"] = float(adv["speaking_rate"])
        if adv.get("pitch") not in (None, ""):
            audio["pitch"] = float(adv["pitch"])
        if effects_profile:
            audio["effectsProfileId"] = [effects_profile]
        body = {"input": {"ssml": ssml}, "voice": vsel, "audioConfig": audio}
        url = _base(self.id, "https://texttospeech.googleapis.com") + path
        desc = {"POST": url, "headers": {"X-Goog-Api-Key": "<key>"}, "body": body}

        def run():
            real = json.loads(json.dumps(body))
            if "voiceClone" in real["voice"]:
                real["voice"]["voiceClone"]["voiceCloningKey"] = cv["cloning_key"]
            raw, _ = _http(url, json.dumps(real).encode("utf-8"), {"X-Goog-Api-Key": keys.get(self.id)["api_key"], "Content-Type": "application/json"})
            return base64.b64decode(json.loads(raw)["audioContent"])
        return desc, run, {"volume_db": 0.0, "pause_scale": 1.0}

    def build_custom_voice(self, keys, name, audio, consent, language="en-US"):
        """The prototype's Instant Custom Voice: a consented voice sample → a cloned voice (key stored locally only)."""
        if not consent:
            raise ValueError("Voice cloning needs the speaker's explicit consent.")
        if not name or not audio:
            raise ValueError("A name and a voice sample are required.")
        script = "I am the owner of this voice and I consent to Google using this sample to create a synthetic version of my voice."
        enc = {"audioEncoding": "LINEAR16", "sampleRateHertz": 24000}
        body = {"reference_audio": {"audio_config": enc, "content": base64.b64encode(audio).decode()},
                "voice_talent_consent": {"audio_config": enc, "content": base64.b64encode(audio).decode()},
                "consent_script": script, "language_code": language}
        raw, _ = _http(_base(self.id, "https://texttospeech.googleapis.com") + "/v1beta1/voices:generateVoiceCloningKey",
                       json.dumps(body).encode(), {"X-Goog-Api-Key": keys.get(self.id)["api_key"], "Content-Type": "application/json"})
        ck = json.loads(raw).get("voiceCloningKey")
        if not ck:
            raise RuntimeError("Google returned no cloning key")
        keys.save_custom_voice(name, ck, language)
        return {"name": name}


# ---- ElevenLabs
class ElevenLabs(Engine):
    id, name, kind, needs_key = "elevenlabs", "ElevenLabs (cloud)", "cloud", True
    native = {"lang", "emotion", "intensity", "rate", "whisper"}
    models = ["eleven_v3", "eleven_multilingual_v2", "eleven_flash_v2_5", "eleven_turbo_v2_5"]
    voices_static = [{"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel (premade)"}]
    notes = ("Voice settings: stability (lower = more expressive), similarity boost, style exaggeration, speaker boost and speed. "
             "With eleven_v3 the emotion and whisper are also given as audio tags such as [sad] or [whispers].")

    def available(self, keys):
        return keys.configured(self.id), "" if keys.configured(self.id) else "add an ElevenLabs API key"

    def voices(self, keys, lang="en"):
        if not keys.configured(self.id):
            return self.voices_static
        try:
            raw, _ = _http(_base(self.id, "https://api.elevenlabs.io") + "/v1/voices", None, {"xi-api-key": keys.get(self.id)["api_key"]}, method="GET", timeout=20)
            return [{"id": v["voice_id"], "name": "%s (%s)" % (v.get("name"), v.get("category", ""))} for v in json.loads(raw).get("voices", [])]
        except Exception as e:
            return self.voices_static + [{"id": "", "name": "voice list unavailable: %s" % scrub(e, keys)}]

    params = [P("stability", "Stability (0–1)", "number", None, 0, 1, 0.01, help="lower = more expressive and variable; v3 uses 0.0 creative, 0.5 natural, 1.0 robust"),
              P("similarity_boost", "Similarity boost (0–1)", "number", None, 0, 1, 0.01, help="how closely to keep the original voice"),
              P("style", "Style exaggeration (0–1)", "number", None, 0, 1, 0.01, help="amplifies the voice's style; slower to generate"),
              P("use_speaker_boost", "Speaker boost", "select", None, options=["true", "false"]),
              P("speed", "Speed (0.7–1.2)", "number", None, 0.7, 1.2, 0.01),
              P("output_format", "Output format", "select", None, options=["pcm_16000", "pcm_22050", "pcm_24000", "pcm_44100"]),
              P("language_code", "Language code (ISO 639-1)", "text", None),
              P("seed", "Seed (repeatable takes)", "number", None, 0, 4294967295, 1),
              P("apply_text_normalization", "Text normalization", "select", None, options=["auto", "on", "off"]),
              P("previous_text", "Text before (for continuity)", "text", None), P("next_text", "Text after (for continuity)", "text", None),
              P("audio_tags", "eleven_v3 audio tags (e.g. [crying] [sighs] [whispers])", "text", None,
                help="Blank = from the voice profile. Tags shape delivery: [laughs] [sighs] [crying] [whispers] [shouting] [nervous] [sarcastic] …")]

    def request(self, text, p, voice, model, keys, adv=None):
        adv = adv or {}
        model = model or self.models[1]
        voice = voice or self.voices_static[0]["id"]
        e = effective(p)
        k = p["intensity"] if p["emotion"] != "neutral" else 0.0
        settings = {"stability": round(0.75 - 0.5 * k, 2), "similarity_boost": 0.75, "style": round(0.6 * k, 2),
                    "use_speaker_boost": True, "speed": round(max(0.7, min(1.2, e["rate"])), 2)}
        for key in ("stability", "similarity_boost", "style", "speed"):
            if adv.get(key) not in (None, ""):
                settings[key] = float(adv[key])
        if adv.get("use_speaker_boost") not in (None, ""):
            settings["use_speaker_boost"] = str(adv["use_speaker_boost"]).lower() == "true"
        say = text
        if model == "eleven_v3" and adv.get("audio_tags"):
            say = adv["audio_tags"].strip() + " " + text
        elif model == "eleven_v3":
            tags = []
            if p["emotion"] != "neutral":
                tags.append({"happy": "happy", "sad": "sad", "angry": "angry", "fearful": "nervous", "calm": "calm", "excited": "excited",
                             "tender": "softly", "serious": "serious", "surprised": "surprised", "disgusted": "disgusted"}[p["emotion"]])
            if p["whisper"]:
                tags.append("whispers")
            say = "".join("[%s] " % t for t in tags) + text
        body = {"text": say, "model_id": model, "voice_settings": settings}
        if adv.get("language_code") or model in ("eleven_flash_v2_5", "eleven_turbo_v2_5", "eleven_v3"):
            body["language_code"] = adv.get("language_code") or p["lang"]
        for key in ("previous_text", "next_text", "apply_text_normalization"):
            if adv.get(key):
                body[key] = adv[key]
        if adv.get("seed") not in (None, ""):
            body["seed"] = int(float(adv["seed"]))
        fmt = adv.get("output_format") or "pcm_24000"
        url = _base(self.id, "https://api.elevenlabs.io") + "/v1/text-to-speech/%s?output_format=%s" % (voice, fmt)
        desc = {"POST": url, "headers": {"xi-api-key": "<key>"}, "body": body}

        def run():
            raw, _ = _http(url, json.dumps(body).encode("utf-8"), {"xi-api-key": keys.get(self.id)["api_key"], "Content-Type": "application/json"})
            return voicedsp.pcm16_to_wav(raw, int(fmt.split("_")[1]))
        return desc, run, {}


# ---- OpenAI
class OpenAI(Engine):
    id, name, kind, needs_key = "openai", "OpenAI speech (cloud)", "cloud", True
    native = {"lang", "emotion", "intensity", "tone", "accent", "rate", "pitch_st", "volume_db", "pause_scale", "articulation",
              "tremble", "hoarse", "breath", "whisper", "age"}
    models = ["gpt-4o-mini-tts", "tts-1-hd", "tts-1"]
    voices_static = [{"id": v, "name": v} for v in ("alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse", "marin", "cedar")]
    notes = "gpt-4o-mini-tts takes every control as spoken instructions; tts-1 / tts-1-hd take speed only (the rest is post-processed)."

    def available(self, keys):
        return keys.configured(self.id), "" if keys.configured(self.id) else "add an OpenAI API key"

    params = [P("instructions", "Instructions (edit freely)", "textarea", None, help="Blank = written from the voice profile (gpt-4o-mini-tts)"),
              P("speed", "Speed (0.25–4.0)", "number", None, 0.25, 4.0, 0.05)]

    def request(self, text, p, voice, model, keys, adv=None):
        adv = adv or {}
        model = model or self.models[0]
        e = effective(p)
        body = {"model": model, "input": text, "voice": voice or "coral", "response_format": "wav",
                "speed": float(adv["speed"]) if adv.get("speed") not in (None, "") else round(max(0.25, min(4.0, e["rate"])), 2)}
        if model == "gpt-4o-mini-tts":
            ins = adv.get("instructions") or describe(p)
            if ins:
                body["instructions"] = ins
            body.pop("speed", None) if ins else None
        url = _base(self.id, "https://api.openai.com") + "/v1/audio/speech"
        desc = {"POST": url, "headers": {"Authorization": "Bearer <key>"}, "body": body}

        def run():
            raw, _ = _http(url, json.dumps(body).encode("utf-8"), {"Authorization": "Bearer " + keys.get(self.id)["api_key"], "Content-Type": "application/json"})
            return raw
        if model == "gpt-4o-mini-tts":
            return desc, run, {k: 0.0 for k in ("tremble", "hoarse", "breath", "age", "volume_db")} | {"pause_scale": 1.0}
        return desc, run, {}


# ---- Microsoft Azure Speech
AZURE_STYLE = {"happy": "cheerful", "sad": "sad", "angry": "angry", "fearful": "fearful", "calm": "calm", "excited": "excited",
               "tender": "gentle", "serious": "serious", "surprised": "excited", "disgusted": "disgruntled"}


class Azure(Engine):
    id, name, kind, needs_key = "azure", "Microsoft Azure Speech (cloud)", "cloud", True
    native = {"lang", "emotion", "intensity", "rate", "pitch_st", "volume_db", "pause_scale", "whisper", "age", "gender", "accent"}
    voices_static = [{"id": "", "name": "Default for the language"}, {"id": "en-US-JennyNeural", "name": "en-US-JennyNeural"},
                     {"id": "en-US-GuyNeural", "name": "en-US-GuyNeural"}, {"id": "en-US-AriaNeural", "name": "en-US-AriaNeural"}]
    notes = ("SSML: speaking style (cheerful, sad, angry, fearful, whispering …) with style degree 0.01–2, age roles "
             "(YoungAdult, OlderAdult, Senior), prosody rate / pitch / volume and timed breaks. Styles and roles depend on the voice.")

    def available(self, keys):
        return keys.configured(self.id), "" if keys.configured(self.id) else "add an Azure Speech key and region"

    def voices(self, keys, lang="en"):
        if not keys.configured(self.id):
            return self.voices_static
        k = keys.get(self.id)
        try:
            raw, _ = _http(_base(self.id, "https://%s.tts.speech.microsoft.com" % k["region"]) + "/cognitiveservices/voices/list", None,
                           {"Ocp-Apim-Subscription-Key": k["api_key"]}, method="GET", timeout=20)
            loc = SPEECH_LANG.get(lang, "en-US")
            return [{"id": v["ShortName"], "name": "%s (%s; styles: %s)" % (v["ShortName"], v.get("Gender", ""), ", ".join(v.get("StyleList", [])[:6]) or "none")}
                    for v in json.loads(raw) if v.get("Locale") == loc]
        except Exception as e:
            return self.voices_static + [{"id": "", "name": "voice list unavailable: %s" % scrub(e, keys)}]

    params = [P("style", "Speaking style", "select", None, options=["advertisement_upbeat", "affectionate", "angry", "assistant", "calm", "chat", "cheerful",
                "customerservice", "depressed", "disgruntled", "documentary-narration", "embarrassed", "empathetic", "envious", "excited", "fearful",
                "friendly", "gentle", "hopeful", "lyrical", "narration-professional", "narration-relaxed", "newscast", "newscast-casual",
                "newscast-formal", "poetry-reading", "sad", "serious", "shouting", "sports_commentary", "sports_commentary_excited",
                "terrified", "unfriendly", "whispering"]),
              P("styledegree", "Style degree (0.01–2)", "number", None, 0.01, 2, 0.01),
              P("role", "Role (age / gender played)", "select", None, options=["Girl", "Boy", "YoungAdultFemale", "YoungAdultMale",
                "OlderAdultFemale", "OlderAdultMale", "SeniorFemale", "SeniorMale"]),
              P("ssml", "SSML (edit freely)", "textarea", None, help="Blank = written from the voice profile")]

    def request(self, text, p, voice, model, keys, adv=None):
        adv = adv or {}
        e = effective(p)
        loc = locale(p)
        voice = voice or {"en-US": "en-US-JennyNeural", "en-GB": "en-GB-SoniaNeural"}.get(loc, loc + "-Neural")
        style = adv.get("style") or ("whispering" if p["whisper"] else AZURE_STYLE.get(p["emotion"]) if p["emotion"] != "neutral" else None)
        role = None
        if p["age"] >= 0.85:
            role = "SeniorFemale" if p["gender"] == "female" else "SeniorMale"
        elif p["age"] >= 0.5:
            role = "OlderAdultFemale" if p["gender"] == "female" else "OlderAdultMale"
        role = adv.get("role") or role
        inner = "<prosody rate='%+d%%' pitch='%+dst' volume='%+.1fdB'>%s</prosody>" % (
            int(100 * (e["rate"] - 1)), int(round(e["pitch_st"])), e["volume_db"], _ssml_body(text, e["pause_scale"]))
        if style or role:
            deg = float(adv["styledegree"]) if adv.get("styledegree") not in (None, "") else max(0.01, 2 * p["intensity"])
            attrs = (" style='%s' styledegree='%.2f'" % (style, deg)) if style else ""
            attrs += (" role='%s'" % role) if role else ""
            inner = "<mstts:express-as%s>%s</mstts:express-as>" % (attrs, inner)
        ssml = ("<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xmlns:mstts='https://www.w3.org/2001/mstts' xml:lang='%s'>"
                "<voice name='%s'>%s</voice></speak>" % (loc, voice, inner))
        ssml = adv.get("ssml") or ssml
        k = keys.get(self.id)
        url = _base(self.id, "https://%s.tts.speech.microsoft.com" % (k.get("region") or "<region>")) + "/cognitiveservices/v1"
        hdr = {"Content-Type": "application/ssml+xml", "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm", "User-Agent": "QueryBook"}
        desc = {"POST": url, "headers": dict(hdr, **{"Ocp-Apim-Subscription-Key": "<key>"}), "body_ssml": ssml}

        def run():
            raw, _ = _http(url, ssml.encode("utf-8"), dict(hdr, **{"Ocp-Apim-Subscription-Key": k["api_key"]}))
            return raw
        post = {"volume_db": 0.0, "pause_scale": 1.0}
        if role:
            post["age"] = 0.0
        return desc, run, post


# ---- Amazon Polly (AWS Signature V4, standard library only)
class Polly(Engine):
    id, name, kind, needs_key = "polly", "Amazon Polly (cloud)", "cloud", True
    native = {"lang", "rate", "pitch_st", "volume_db", "pause_scale", "whisper", "age", "breath", "gender"}
    models = ["neural", "standard", "generative", "long-form"]
    voices_static = [{"id": v, "name": v} for v in ("Joanna", "Matthew", "Ruth", "Stephen", "Amy", "Brian", "Lucia", "Lea", "Vicki", "Bianca")]
    notes = ("SSML prosody (rate, volume; pitch on the standard engine), breaks; on the standard engine also whispering, "
             "soft phonation (breathy) and vocal-tract length (older / younger sounding).")

    def available(self, keys):
        return keys.configured(self.id), "" if keys.configured(self.id) else "add AWS access key, secret and region"

    params = [P("sample_rate", "Sample rate", "select", None, options=["8000", "16000"]),
              P("ssml", "SSML (edit freely)", "textarea", None, help="Blank = written from the voice profile")]

    def request(self, text, p, voice, model, keys, adv=None):
        adv = adv or {}
        engine = model or "neural"
        e = effective(p)
        std = engine == "standard"
        body_txt = _ssml_body(text, e["pause_scale"])
        pros = "rate='%d%%' volume='%+.1fdB'" % (int(100 * e["rate"]), e["volume_db"])
        if std:
            pros += " pitch='%+d%%'" % int(round(100 * (2 ** (e["pitch_st"] / 12.0) - 1)))
        s = "<prosody %s>%s</prosody>" % (pros, body_txt)
        if std and p["age"] >= 0.15:
            s = "<amazon:effect vocal-tract-length='%+d%%'>%s</amazon:effect>" % (int(10 * p["age"]), s)
        if std and e["breath"] >= 0.15:
            s = "<amazon:effect phonation='soft'>%s</amazon:effect>" % s
        if std and p["whisper"]:
            s = "<amazon:effect name='whispered'>%s</amazon:effect>" % s
        ssml = adv.get("ssml") or "<speak>%s</speak>" % s
        k = keys.get(self.id)
        region = k.get("region") or "us-east-1"
        body = {"Text": ssml, "TextType": "ssml", "VoiceId": voice or ("Joanna" if p["gender"] != "male" else "Matthew"), "Engine": engine,
                "OutputFormat": "pcm", "SampleRate": adv.get("sample_rate") or "16000", "LanguageCode": locale(p)}
        url = _base(self.id, "https://polly.%s.amazonaws.com" % region) + "/v1/speech"
        desc = {"POST": url, "headers": {"Authorization": "AWS4-HMAC-SHA256 Credential=<key>/…, Signature=…"}, "body": body}

        def run():
            payload = json.dumps(body).encode("utf-8")
            hdr = _sigv4("POST", url, payload, region, "polly", k["access_key_id"], k["secret_access_key"])
            raw, _ = _http(url, payload, hdr)
            return voicedsp.pcm16_to_wav(raw, int(body["SampleRate"]))
        post = {"volume_db": 0.0, "pause_scale": 1.0}
        if std:
            post.update({"age": 0.0, "breath": 0.0})
        return desc, run, post


def _sigv4(method, url, payload, region, service, akid, secret, now=None):
    u = urllib.parse.urlparse(url)
    t = now or datetime.datetime.now(datetime.timezone.utc)
    amz, day = t.strftime("%Y%m%dT%H%M%SZ"), t.strftime("%Y%m%d")
    ph = hashlib.sha256(payload).hexdigest()
    host = u.netloc
    canon = "\n".join([method, u.path or "/", u.query, "content-type:application/json\nhost:%s\nx-amz-date:%s\n" % (host, amz),
                       "content-type;host;x-amz-date", ph])
    scope = "%s/%s/%s/aws4_request" % (day, region, service)
    sts = "\n".join(["AWS4-HMAC-SHA256", amz, scope, hashlib.sha256(canon.encode()).hexdigest()])

    def h(k, m):
        return hmac.new(k, m.encode(), hashlib.sha256).digest()
    sig = hmac.new(h(h(h(h(("AWS4" + secret).encode(), day), region), service), "aws4_request"), sts.encode(), hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "X-Amz-Date": amz,
            "Authorization": "AWS4-HMAC-SHA256 Credential=%s/%s, SignedHeaders=content-type;host;x-amz-date, Signature=%s" % (akid, scope, sig)}


ENGINES = [Espeak(), Formant(), Sapi(), Say(), GoogleGemini(), GoogleCloud(), ElevenLabs(), OpenAI(), Azure(), Polly()]
BY_ID = {e.id: e for e in ENGINES}


def engines_public(keys):
    out = []
    for e in ENGINES:
        ok, why = e.available(keys)
        out.append({"id": e.id, "name": e.name, "kind": e.kind, "available": ok, "why_not": why, "needs_key": e.needs_key,
                    "models": e.models, "notes": e.notes, "native": sorted(e.native), "params": e.params})
    return out


def plan(text, prof, engine_id, voice="", model="", keys=None, adv=None):
    """Everything about a generation before it happens: the request (keys removed) and control coverage."""
    p = profile(prof)
    eng = BY_ID[engine_id]
    adv = {k: v for k, v in (adv or {}).items() if v not in (None, "")}
    desc, run, post_override = eng.request(text, p, voice, model, keys, adv)
    e = effective(p)
    fx = {"tremble": e["tremble"], "hoarse": e["hoarse"], "breath": e["breath"], "age": p["age"], "volume_db": e["volume_db"], "pause_scale": e["pause_scale"],
          "pitch_st": 0.0 if "pitch_st" in eng.native else e["pitch_st"], "tempo": 1.0 if "rate" in eng.native else e["rate"]}
    fx.update(post_override)
    cov = coverage(eng, p)
    for row in cov:
        k = row["control"]
        fk = "tempo" if k == "rate" else k
        if row["how"].startswith("added") and fk in fx and (fx[fk] in (0.0,) or (fk in ("pause_scale", "tempo") and fx[fk] == 1.0)):
            row["how"] = "native" if k in eng.native else ("not needed" if not row["in_use"] else "handled by the engine")
    return {"engine": engine_id, "profile": p, "effective": e, "request": desc, "post_processing": fx, "coverage": cov,
            "direction": describe(p), "advanced": adv}, run, fx
