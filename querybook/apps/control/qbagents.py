"""qbagents — the Agent hub: agents you pick and choose, that take in text, sound, video, live data, touch, body motion
and any other sensor, and that learn from best-in-class examples of people with superior skills. No AI model anywhere.

Pure, non-LLM reasoning (the commitment)
  * Every agent here is a deterministic program: measurements, statistics and stated rules. The same input always
    gives the same result, and every result shows how it was reached (which measures, which examples, which ranges).
  * No agent calls a language model or any other AI service. Network access exists only where an agent needs data
    (a live feed, the Open Claw skill registry), and every request is checked against a block-list of AI-model
    services (LLM_HOSTS): such a request is refused, whatever asks for it.
  * Agents made for language models (Open Claw agents, skills and tools) are imported as DATA, never run: their files
    are read by the Artifact Segmenter, lines that instruct a model ("you are…", "respond with…", prompts, personas)
    are quarantined — kept for inspection, never used — and what remains is knowledge a program can use: checklists,
    commands (listed, never executed), required tools, terms and links. Scripts inside them are described, not run.

Learning by example
  A *skill* is something to get better at, measured by one sense agent (for example "Persuasive speaking" by the
  Listener). Exemplars are recordings or samples of best-in-class performers (with their source and licence, rated
  1–5). From them the Mentor builds a profile: for every measure, the exemplars' median and range and how consistent
  they are (a measure every master shares is a signature of mastery and weighs more). A new sample is scored against
  the profile, told which measures are furthest from the masters and in which direction to move, and which exemplar
  it is closest to. Each new exemplar makes a new candidate profile; the admin adopts one (passphrase).

Senses: text (any file: 40+ formats via qbartifact), audio (WAV; the page converts any recording), video (per-frame
measures computed in the page from a file or the camera), live data (feeds polled on a schedule; the page's live
microphone and camera), touch (pressure, speed, smoothness and rhythm from a touch screen or pen; contact force from
tactile sensors through the Device gateway), body motion (accelerometers, heart rate, gaze through the Device
gateway or the phone's own sensors) and any other sensor (smell, taste, temperature, … — any numeric channels).
Standard library only.
"""
import base64, datetime, hashlib, hmac, io, json, math, os, re, threading, time, urllib.error, urllib.parse, urllib.request, wave, zipfile

import qbcore as core
import qbartifact

VERSION = "1.0.0"
UA = "QueryBook-AgentHub/%s (+https://github.com/ghoward333777-png/projectx)" % VERSION
SCHEMA = ["""
CREATE TABLE skills (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, agent TEXT NOT NULL, description TEXT, playbook_id INTEGER, created TEXT NOT NULL);
CREATE TABLE exemplars (
  id INTEGER PRIMARY KEY, skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE, title TEXT NOT NULL, performer TEXT,
  source TEXT, licence TEXT NOT NULL, rating INTEGER NOT NULL, features TEXT NOT NULL, detail TEXT, sha TEXT NOT NULL, created TEXT NOT NULL,
  UNIQUE(skill_id, sha));
CREATE TABLE samples (
  id INTEGER PRIMARY KEY, skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE, title TEXT, features TEXT NOT NULL,
  result TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE profiles (
  id INTEGER PRIMARY KEY, skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE, version INTEGER NOT NULL,
  profile TEXT NOT NULL, n INTEGER NOT NULL, created TEXT NOT NULL, adopted TEXT, UNIQUE(skill_id, version));
CREATE TABLE playbooks (
  id INTEGER PRIMARY KEY, origin TEXT NOT NULL, ref TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, version TEXT,
  description TEXT, data TEXT NOT NULL, kept INTEGER NOT NULL, quarantined INTEGER NOT NULL, warnings TEXT, sha TEXT NOT NULL UNIQUE,
  enabled INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL);
CREATE TABLE clawhub_index (
  slug TEXT PRIMARY KEY, name TEXT, summary TEXT, version TEXT, updated TEXT, owner TEXT, data TEXT, seen TEXT NOT NULL);
CREATE TABLE feeds (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL, path TEXT, every_s INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
  last TEXT, error TEXT, created TEXT NOT NULL);
CREATE TABLE readings (
  id INTEGER PRIMARY KEY, feed_id INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE, t TEXT NOT NULL, value REAL NOT NULL);
CREATE INDEX readings_feed_t ON readings(feed_id, t);
"""]

# AI-model services: no agent may send anything to these, or fetch from them (the non-LLM commitment)
LLM_HOSTS = ("api.openai.com", "openai.azure.com", "chatgpt.com", "api.anthropic.com", "claude.ai", "generativelanguage.googleapis.com",
             "aiplatform.googleapis.com", "gemini.google.com", "api.cohere.ai", "api.cohere.com", "api.mistral.ai", "api.groq.com",
             "openrouter.ai", "api.together.xyz", "api.fireworks.ai", "api-inference.huggingface.co", "router.huggingface.co",
             "api.deepseek.com", "api.x.ai", "api.perplexity.ai", "bedrock-runtime", "api.replicate.com", "api.ai21.com",
             "inference.ai.azure.com", "models.inference.ai.azure.com", "api.moonshot.cn", "dashscope.aliyuncs.com", "ollama", "localhost:11434")
REFUSED_HOSTS = ("youtube.com", "youtu.be", "googlevideo.com")
CLAWHUB = os.environ.get("QB_CLAWHUB") or os.environ.get("CLAWHUB_REGISTRY") or "https://clawhub.ai"
MAX_FETCH = 20 * 1024 * 1024
MAX_AUDIO_S = 90


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def llm_host(url):
    """True when the URL belongs to an AI-model service (refused by every agent)."""
    u = urllib.parse.urlsplit(str(url or "").strip())
    host = (u.hostname or "").lower() + (":%d" % u.port if u.port else "")
    return any(h in host for h in LLM_HOSTS)


def fetch(url, accept="*/*", limit=MAX_FETCH, timeout=30):
    """The one way an agent reaches the network: https/http only, never an AI-model service, size-capped, polite."""
    u = urllib.parse.urlsplit(str(url or "").strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise core.UserError("Give a web address starting with https://")
    if llm_host(url):
        raise core.UserError("Refused: %s is an AI-model service — agents here reason without language models." % u.hostname)
    if any(u.hostname.lower().endswith(h) for h in REFUSED_HOSTS):
        raise core.UserError("Refused: %s does not allow its videos to be downloaded." % u.hostname)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                final = r.geturl()
                if llm_host(final):
                    raise core.UserError("Refused: the address redirected to an AI-model service.")
                data = r.read(limit + 1)
                if len(data) > limit:
                    raise core.UserError("More than %d MB — too large." % (limit // 1048576))
                return data, r.headers.get("Content-Type", ""), final
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                time.sleep(min(10, int(e.headers.get("Retry-After") or 2)))
                continue
            raise core.UserError("%s answered %s: %s" % (u.hostname, e.code, (e.read(300) or b"").decode("utf-8", "replace").strip()[:200]))
        except urllib.error.URLError as e:
            raise core.UserError("Could not reach %s (%s)." % (u.hostname, e.reason))
    raise core.UserError("%s is busy — try again in a minute." % u.hostname)


# ============================================================================ statistics
def _mean(v):
    return sum(v) / len(v) if v else 0.0


def _sd(v):
    if len(v) < 2:
        return 0.0
    m = _mean(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def _pct(v, q):
    if not v:
        return 0.0
    s = sorted(v)
    k = (len(s) - 1) * q
    i = int(k)
    return s[i] + (s[min(i + 1, len(s) - 1)] - s[i]) * (k - i)


def _period(v, dt, lo_s, hi_s):
    """Dominant period (s) of a series by autocorrelation between lo_s and hi_s; 0 when there is no clear rhythm."""
    n = len(v)
    if n < 8 or dt <= 0:
        return 0.0
    m = _mean(v)
    x = [a - m for a in v]
    den = sum(a * a for a in x) or 1e-12
    best, lag_best = 0.3, 0
    for lag in range(max(1, int(lo_s / dt)), min(n // 2, int(hi_s / dt) + 1)):
        r = sum(x[i] * x[i + lag] for i in range(n - lag)) / den
        if r > best:
            best, lag_best = r, lag
    return round(lag_best * dt, 3)


def _slope(v, dt):
    n = len(v)
    if n < 2:
        return 0.0
    tm = (n - 1) / 2
    num = sum((i - tm) * (y - _mean(v)) for i, y in enumerate(v))
    den = sum((i - tm) ** 2 for i in range(n)) or 1
    return num / den / (dt or 1)


def _r(x, d=3):
    return round(float(x), d)


# ============================================================================ the sense agents (pure functions)
# feature definitions: key -> (label, unit, advice when higher is needed, advice when lower is needed, scored)
TEXT_F = {
    "words": ("words", "", "", "", False), "sentences": ("sentences", "", "", "", False),
    "sent_len_mean": ("average sentence length", "words", "write longer, fuller sentences", "write shorter sentences", True),
    "sent_len_sd": ("sentence-length variety", "words", "vary sentence length more (mix short and long)", "keep sentence lengths steadier", True),
    "word_len_mean": ("average word length", "letters", "use more precise, longer words", "use plainer, shorter words", True),
    "long_word_pct": ("long words", "%", "use more specific vocabulary", "cut long words for short ones", True),
    "variety": ("vocabulary variety", "", "repeat words less; vary vocabulary", "repeat key words more consistently", True),
    "question_pct": ("questions", "% of sentences", "ask the reader more questions", "ask fewer questions", True),
    "comma_per_sent": ("commas per sentence", "", "add more clauses and asides", "simplify clauses", True),
    "filler_per_100": ("filler words", "per 100 words", "", "cut fillers (very, really, just, basically…)", True),
    "hedge_per_100": ("hedging", "per 100 words", "qualify claims more carefully", "commit: fewer maybes and perhapses", True),
    "number_per_100": ("numbers and figures", "per 100 words", "give more concrete figures", "use fewer figures", True),
    "you_per_100": ("addressing the reader (you)", "per 100 words", "speak to the reader more directly", "address the reader less", True),
    "i_per_100": ("first person (I, we)", "per 100 words", "bring in your own voice more", "talk about yourself less", True),
    "passive_pct": ("passive voice", "% of sentences", "", "use active voice: say who does what", True),
    "para_sent_mean": ("sentences per paragraph", "", "develop paragraphs further", "break up long paragraphs", True),
    "reading_ease": ("reading ease (Flesch)", "", "write more simply", "write with more density", True),
    "playbook_terms_pct": ("playbook terms covered", "%", "cover more of the attached playbook's key terms", "", True),
}
AUDIO_F = {
    "duration_s": ("duration", "s", "", "", False),
    "speech_level_db": ("speaking level", "dBFS", "speak up / record closer", "speak more softly / record further away", False),
    "dynamics_db": ("vocal dynamics (loud–soft range)", "dB", "vary loudness more for emphasis", "keep loudness steadier", True),
    "pause_pct": ("time in pauses", "%", "pause more; let points land", "pause less; keep momentum", True),
    "pauses_per_min": ("pauses per minute", "", "use more short pauses", "use fewer pauses", True),
    "pause_mean_s": ("average pause", "s", "hold pauses a little longer", "shorten pauses", True),
    "phrase_mean_s": ("average phrase between pauses", "s", "speak in longer phrases", "speak in shorter phrases", True),
    "syllables_per_s": ("speaking rate", "syllables/s", "speak a little faster", "slow down", True),
    "pitch_median_hz": ("voice pitch (median)", "Hz", "", "", False),
    "pitch_range_st": ("pitch range (melody)", "semitones", "use more melody: lift and drop the voice", "flatten the melody a little", True),
    "pitch_sd_st": ("pitch variation", "semitones", "vary pitch more", "vary pitch less", True),
}
VIDEO_F = {
    "duration_s": ("duration", "s", "", "", False),
    "motion_mean": ("movement (average)", "", "move more", "move less", True),
    "motion_sd": ("movement variety", "", "vary movement more", "move more evenly", True),
    "motion_p90": ("biggest movements", "", "make bolder movements", "make smaller movements", True),
    "still_pct": ("time still", "%", "hold still more often", "hold still less", True),
    "cuts_per_min": ("cuts / scene changes per minute", "", "change shot more often", "hold shots longer", True),
    "bright_mean": ("brightness", "", "light the scene more", "darken the scene", True),
    "contrast_mean": ("contrast", "", "add contrast", "soften contrast", True),
    "sat_mean": ("colour saturation", "", "use richer colour", "use calmer colour", True),
    "motion_period_s": ("movement rhythm", "s", "slow the rhythm of movement", "quicken the rhythm of movement", True),
}
TOUCH_F = {
    "pressure_mean": ("pressure (average)", "0–1", "press more firmly", "press more lightly", True),
    "pressure_sd": ("pressure control (variation)", "", "vary pressure more", "keep pressure steadier", True),
    "pressure_peak": ("peak pressure", "0–1", "press harder at the peaks", "ease off at the peaks", True),
    "speed_mean": ("stroke speed", "screen-widths/s", "move faster", "move slower", True),
    "speed_sd": ("speed variation", "", "vary speed more", "keep speed steadier", True),
    "smoothness": ("smoothness (jerk, log10)", "", "", "move more smoothly (less jerk)", True),
    "contact_ms_mean": ("contact time per stroke", "ms", "stay in contact longer", "lift off sooner", True),
    "strokes_per_min": ("strokes per minute", "", "work faster", "work slower", True),
    "rhythm_cv": ("rhythm irregularity", "", "", "keep a steadier rhythm", True),
    "force_mean_n": ("contact force (average)", "N", "apply more force", "apply less force", True),
    "force_sd_n": ("force variation", "N", "vary force more", "keep force steadier", True),
    "force_peak_n": ("peak force", "N", "push harder at the peaks", "ease off at the peaks", True),
    "force_rise_n_s": ("force build-up speed", "N/s", "build force faster", "build force more gradually", True),
}
MOTION_F = {
    "acc_mean": ("movement intensity", "m/s²", "move more vigorously", "move more gently", True),
    "acc_sd": ("movement variation", "m/s²", "vary movement more", "move more steadily", True),
    "jerk_mean": ("jerkiness", "m/s³", "", "move more smoothly", True),
    "cadence_hz": ("cadence", "Hz", "quicken the cadence", "slow the cadence", True),
    "heart_mean": ("heart rate", "bpm", "", "", True),
    "heart_sd": ("heart-rate variation", "bpm", "", "", True),
    "fixation_ms_mean": ("gaze fixation length", "ms", "look longer at each point", "move the eyes on sooner", True),
}
SENSOR_F = {}              # channel features are named "<channel>.<stat>" and built on the fly

FEATURES = {"text": TEXT_F, "audio": AUDIO_F, "video": VIDEO_F, "touch": TOUCH_F, "motion": MOTION_F, "sensor": SENSOR_F, "live": SENSOR_F}

AGENTS = [
    {"id": "text", "name": "Reader", "sense": "text", "icon": "📖",
     "takes": "typed or pasted text, any document (Word, PDF, web page, e-book, e-mail, spreadsheet … 40+ formats), a web page by address",
     "measures": "sentence rhythm and variety, vocabulary, questions, fillers, hedges, figures, voice (active/passive), reading ease, playbook coverage"},
    {"id": "audio", "name": "Listener", "sense": "audio", "icon": "👂",
     "takes": "any recording (the page converts it to WAV) or the live microphone",
     "measures": "pauses and phrasing, speaking rate, loudness dynamics, pitch range and melody"},
    {"id": "video", "name": "Watcher", "sense": "video", "icon": "👁",
     "takes": "any video file the browser can play, or the live camera (measured frame by frame in the page)",
     "measures": "amount, variety, size and rhythm of movement, stillness, cuts, light, contrast, colour"},
    {"id": "live", "name": "Live feed", "sense": "live data", "icon": "📡",
     "takes": "a data address (JSON or CSV) polled on a schedule; the page's live microphone and camera",
     "measures": "level, spread, trend and rhythm of each live reading"},
    {"id": "touch", "name": "Toucher", "sense": "touch", "icon": "✋",
     "takes": "strokes on a touch screen or pen (pressure, contact size, speed); contact force from tactile sensors (Device gateway)",
     "measures": "pressure and its control, speed, smoothness, contact time, rhythm, force build-up"},
    {"id": "motion", "name": "Mover", "sense": "body", "icon": "🏃",
     "takes": "accelerometers (phone, watch, motion suit), heart rate and gaze (Device gateway or the phone's own sensors)",
     "measures": "intensity, steadiness, smoothness, cadence, heart rate, gaze fixations"},
    {"id": "sensor", "name": "Any sensor", "sense": "all senses", "icon": "🧪",
     "takes": "any numeric channels — smell (e-nose), taste (e-tongue), temperature, light, sound level, pressure … as CSV or JSON",
     "measures": "per channel: level, spread, range, trend and rhythm"},
    {"id": "mentor", "name": "Mentor", "sense": "learning", "icon": "🎓",
     "takes": "exemplars of best-in-class performers for a skill", "measures": "builds the mastery profile, scores samples, coaches"},
    {"id": "engineer", "name": "Engineer", "sense": "its own program", "icon": "🛠",
     "takes": "QueryBook's own source code, its log and its activity record",
     "measures": "finds improvements (unused code, risky patterns, errors in use, slow work), proposes exact fixes; the admin approves, every fix is tested before it is applied"},
    {"id": "claw", "name": "Open Claw importer", "sense": "agents, skills, tools", "icon": "🦞",
     "takes": "Open Claw skills from ClawHub, the agents, skills and tools of an Open Claw installation on this computer, uploaded skill folders",
     "measures": "turns them into playbooks: checklists, commands (never run), required tools, terms; quarantines model instructions"},
]
AGENT_IDS = [a["id"] for a in AGENTS]
SENSE_AGENTS = ("text", "audio", "video", "live", "touch", "motion", "sensor")

_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.U)
FILLERS = {"very", "really", "just", "basically", "actually", "literally", "quite", "totally", "simply", "honestly", "definitely", "pretty"}
HEDGES = {"maybe", "perhaps", "might", "possibly", "somewhat", "seems", "seem", "apparently", "probably", "arguably", "fairly", "rather"}
STOP = set("""a an and are as at be been but by for from has have he her his i if in into is it its me my of on or our she so than that the
their them then there these they this to was we were what when which who will with you your not no do does did can could would should
about after all also any because before being both each few more most other over same some such through too under up very just only own""".split())


def _syllables(w):
    w = w.lower()
    n = len(re.findall(r"[aeiouyàâäéèêëîïôöùûüáíóú]+", w))
    if w.endswith("e") and n > 1 and not w.endswith(("le", "ee")):
        n -= 1
    return max(1, n)


def text_features(text, terms=None):
    text = str(text or "")
    words = _WORD.findall(text)
    lw = [w.lower() for w in words]
    nw = len(words)
    if nw < 5:
        raise core.UserError("Give at least a few sentences of text.")
    sents = [s for s in re.split(r"(?<=[.!?…])[\"'”’)\]]*\s+|\n{2,}", text.strip()) if _WORD.search(s)]
    slen = [len(_WORD.findall(s)) for s in sents] or [nw]
    paras = [p for p in re.split(r"\n\s*\n", text.strip()) if _WORD.search(p)]
    per100 = lambda c: 100.0 * c / nw
    win = 50                                                     # moving-average type/token ratio (length-independent)
    if nw >= win:
        variety = _mean([len(set(lw[i:i + win])) / win for i in range(0, nw - win + 1, max(1, (nw - win) // 40 or 1))])
    else:
        variety = len(set(lw)) / nw
    passive = sum(1 for s in sents if re.search(r"\b(?:is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?\w+(?:ed|en)\b", s, re.I))
    syl = sum(_syllables(w) for w in words)
    f = {"words": nw, "sentences": len(sents),
         "sent_len_mean": _r(_mean(slen), 2), "sent_len_sd": _r(_sd(slen), 2), "word_len_mean": _r(_mean([len(w) for w in words]), 2),
         "long_word_pct": _r(100.0 * sum(1 for w in words if len(w) >= 7) / nw, 2), "variety": _r(variety, 3),
         "question_pct": _r(100.0 * sum(1 for s in sents if s.rstrip("\"'”’) ").endswith("?")) / len(sents), 2) if sents else 0.0,
         "comma_per_sent": _r(text.count(",") / max(1, len(sents)), 2),
         "filler_per_100": _r(per100(sum(1 for w in lw if w in FILLERS)), 2), "hedge_per_100": _r(per100(sum(1 for w in lw if w in HEDGES)), 2),
         "number_per_100": _r(per100(len(re.findall(r"\b\d[\d.,%]*\b", text))), 2),
         "you_per_100": _r(per100(sum(1 for w in lw if w in ("you", "your", "yours", "yourself"))), 2),
         "i_per_100": _r(per100(sum(1 for w in lw if w in ("i", "me", "my", "we", "us", "our"))), 2),
         "passive_pct": _r(100.0 * passive / max(1, len(sents)), 2), "para_sent_mean": _r(len(sents) / max(1, len(paras)), 2),
         "reading_ease": _r(206.835 - 1.015 * (nw / max(1, len(sents))) - 84.6 * (syl / nw), 1)}
    if terms:
        have = set(lw)
        f["playbook_terms_pct"] = _r(100.0 * sum(1 for t in terms if t in have) / len(terms), 1)
    return f


def text_from_file(data, name):
    """Any document → its text, through the Artifact Segmenter (nothing in the file is executed)."""
    fmt, segs, meta = qbartifact.segment(data, name or "file")
    parts = [s["text"] for s in segs if s.get("text") and s.get("kind") in ("paragraph", "heading", "passage", "page", "cell", "slide", "text", "line", "part")]
    if not parts:
        parts = [s["text"] for s in segs if isinstance(s.get("text"), str) and len(s["text"]) > 20]
    return "\n\n".join(parts), {"format": meta.get("format_name"), "segments": len(segs), "sha256": meta.get("sha256")}


def _pcm(wav_bytes):
    try:
        w = wave.open(io.BytesIO(wav_bytes))
    except (wave.Error, EOFError) as e:
        raise core.UserError("Send the sound as a WAV file (the page converts any recording): %s" % e)
    sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
    n = min(n, int(sr * MAX_AUDIO_S))
    raw = w.readframes(n)
    if sw != 2:
        raise core.UserError("Use 16-bit WAV.")
    import array
    a = array.array("h"); a.frombytes(raw[: len(raw) // 2 * 2])
    if ch > 1:
        a = [sum(a[i:i + ch]) / ch for i in range(0, len(a) - ch + 1, ch)]
    k = max(1, int(round(sr / 8000)))                           # to ~8 kHz (block average: enough for voice measures)
    x = [sum(a[i:i + k]) / k / 32768.0 for i in range(0, len(a) - k + 1, k)]
    return x, sr / k, n / sr


def audio_features(wav_bytes):
    x, sr, dur = _pcm(wav_bytes)
    if dur < 1.0:
        raise core.UserError("Give at least a second of sound.")
    hop = int(sr * 0.02)
    db = []
    for i in range(0, len(x) - hop + 1, hop):
        e = sum(v * v for v in x[i:i + hop]) / hop
        db.append(10 * math.log10(e + 1e-10))
    floor, top = _pct(db, 0.1), _pct(db, 0.95)
    thr = max(floor + 10, top - 35)
    sp = [d > thr for d in db]
    # pauses: silent runs of 0.2 s or more between speech
    pauses, phrases, run, cur = [], [], 0, None
    for s in sp + [not sp[-1]]:
        if cur is None or s == cur:
            run += 1
        else:
            (phrases if cur else pauses).append(run * 0.02)
            run = 1
        cur = s
    first = next((i for i, s in enumerate(sp) if s), 0)
    last = len(sp) - 1 - next((i for i, s in enumerate(reversed(sp)) if s), 0)
    inner = [p for p in pauses if p >= 0.2]
    if sp and not sp[0] and pauses:
        inner = [p for p in pauses[1:] if p >= 0.2]
    if sp and not sp[-1] and inner:
        inner = inner[:-1]
    span = max(0.02, (last - first + 1) * 0.02)
    speech_s = sum(1 for s in sp[first:last + 1] if s) * 0.02 or 0.02
    # syllable nuclei: peaks of the smoothed energy inside speech, at least 80 ms apart
    sm = [(db[max(0, i - 1)] + db[i] + db[min(len(db) - 1, i + 1)]) / 3 for i in range(len(db))]
    peaks, lastp = 0, -10
    for i in range(1, len(sm) - 1):
        if sp[i] and sm[i] >= sm[i - 1] and sm[i] > sm[i + 1] and sm[i] > thr + 3 and i - lastp >= 4:
            lo = min(sm[max(0, i - 6):i] or [sm[i]])
            if sm[i] - lo >= 2.0:
                peaks += 1; lastp = i
    # pitch: normalised autocorrelation on voiced frames, 10 per second, 50–400 Hz
    win, pitches = int(sr * 0.032), []
    lag_lo, lag_hi = int(sr / 400), int(sr / 50)
    voiced = [fi for fi in range(0, len(db), 5) if sp[fi]]
    if len(voiced) > 300:                                        # evenly spread, enough for a stable median and range
        voiced = [voiced[int(k * len(voiced) / 300)] for k in range(300)]
    for fi in voiced:
        i = fi * hop
        seg = x[i:i + win + lag_hi]
        if len(seg) < win + lag_hi:
            break
        a0 = seg[:win:2]
        e0 = sum(v * v for v in a0)
        best, bl = 0.0, 0
        for lag in range(lag_lo, lag_hi):
            b = seg[lag:lag + win:2]
            num = sum(u * v for u, v in zip(a0, b))
            r = 2 * num / ((e0 + sum(v * v for v in b)) or 1e-12)
            if r > best:
                best, bl = r, lag
        if best > 0.45 and bl:
            pitches.append(sr / bl)
    st = [12 * math.log2(p / 100.0) for p in pitches]
    spdb = [d for d, s in zip(db, sp) if s]
    return {"duration_s": _r(dur, 2), "speech_level_db": _r(_mean(spdb), 1), "dynamics_db": _r(_sd(spdb), 2),
            "pause_pct": _r(100.0 * sum(inner) / span, 2), "pauses_per_min": _r(60.0 * len(inner) / span, 2),
            "pause_mean_s": _r(_mean(inner), 3), "phrase_mean_s": _r(_mean([p for p in phrases if p >= 0.1]), 3),
            "syllables_per_s": _r(peaks / speech_s, 2),
            "pitch_median_hz": _r(_pct(pitches, 0.5), 1), "pitch_range_st": _r(_pct(st, 0.9) - _pct(st, 0.1), 2) if st else 0.0,
            "pitch_sd_st": _r(_sd(st), 2)}


def video_features(frames, fps):
    fps = float(fps or 0)
    if not isinstance(frames, list) or len(frames) < 4 or fps <= 0:
        raise core.UserError("The video needs at least a few measured frames (the page measures them).")
    col = lambda k: [float(f[k]) for f in frames if isinstance(f, dict) and isinstance(f.get(k), (int, float))]
    mo = col("motion")
    m, s = _mean(mo), _sd(mo)
    cuts = sum(1 for v in mo if v > max(25.0, m + 4 * s))
    dur = len(frames) / fps
    f = {"duration_s": _r(dur, 2), "motion_mean": _r(m, 3), "motion_sd": _r(s, 3), "motion_p90": _r(_pct(mo, 0.9), 3),
         "still_pct": _r(100.0 * sum(1 for v in mo if v < 1.0) / max(1, len(mo)), 2), "cuts_per_min": _r(60.0 * cuts / dur, 2),
         "bright_mean": _r(_mean(col("bright")), 2), "contrast_mean": _r(_mean(col("contrast")), 2), "sat_mean": _r(_mean(col("sat")), 2),
         "motion_period_s": _period([min(v, _pct(mo, 0.95)) for v in mo[:3000]], 1.0 / fps, 0.3, 5.0)}   # cuts clipped: rhythm of the movement itself
    extra = sorted({k for fr in frames[:50] if isinstance(fr, dict) for k, v in fr.items()
                    if isinstance(v, (int, float)) and k not in ("motion", "bright", "contrast", "sat", "t")})[:24]
    for k in extra:                                              # any extra per-frame channel (e.g. face or pose measures)
        v = col(k)
        f[k + ".mean"], f[k + ".sd"] = _r(_mean(v), 4), _r(_sd(v), 4)
    return f


def touch_features(inp):
    f = {}
    pts = inp.get("points") or []
    if pts:
        strokes = {}
        for p in pts[:200000]:
            strokes.setdefault(p.get("stroke", 0), []).append(p)
        pr, sp, jerks, contact, starts = [], [], [], [], []
        for st in strokes.values():
            st.sort(key=lambda p: p.get("t", 0))
            starts.append(st[0].get("t", 0)); contact.append(st[-1].get("t", 0) - st[0].get("t", 0))
            pr += [float(p.get("p") or 0) for p in st if p.get("p") is not None]
            v = []
            for a, b in zip(st, st[1:]):
                dt = (b.get("t", 0) - a.get("t", 0)) / 1000.0
                if dt > 0:
                    v.append(math.hypot(b.get("x", 0) - a.get("x", 0), b.get("y", 0) - a.get("y", 0)) / dt)
            sp += v
            acc = [(v2 - v1) for v1, v2 in zip(v, v[1:])]
            jerks += [abs(a2 - a1) for a1, a2 in zip(acc, acc[1:])]
        starts.sort()
        gaps = [b - a for a, b in zip(starts, starts[1:]) if b > a]
        span_min = max(1e-6, (max(p.get("t", 0) for p in pts) - min(p.get("t", 0) for p in pts)) / 60000.0)
        f.update({"pressure_mean": _r(_mean(pr), 3), "pressure_sd": _r(_sd(pr), 3), "pressure_peak": _r(_pct(pr, 0.95), 3),
                  "speed_mean": _r(_mean(sp), 3), "speed_sd": _r(_sd(sp), 3), "smoothness": _r(math.log10(_mean(jerks) + 1e-6), 3),
                  "contact_ms_mean": _r(_mean(contact), 1), "strokes_per_min": _r(len(strokes) / span_min, 2),
                  "rhythm_cv": _r(_sd(gaps) / _mean(gaps), 3) if len(gaps) >= 2 and _mean(gaps) else 0.0})
    force = [float(x) for x in (inp.get("force") or [])][:200000]
    if force:
        rate = float(inp.get("rate_hz") or 10)
        rise = [(b - a) * rate for a, b in zip(force, force[1:]) if b > a]
        f.update({"force_mean_n": _r(_mean(force), 3), "force_sd_n": _r(_sd(force), 3), "force_peak_n": _r(_pct(force, 0.95), 3),
                  "force_rise_n_s": _r(_pct(rise, 0.9), 3) if rise else 0.0})
    if not f:
        raise core.UserError("Give touch strokes (points) or contact forces.")
    return f


def motion_features(inp):
    f = {}
    rate = float(inp.get("rate_hz") or 50)
    acc = inp.get("acc")
    if not acc and inp.get("samples"):
        acc = [math.sqrt(sum(float(s.get(k) or 0) ** 2 for k in ("ax", "ay", "az"))) for s in inp["samples"][:200000]]
    if acc:
        acc = [float(a) if not isinstance(a, list) else math.sqrt(sum(float(c) ** 2 for c in a)) for a in acc][:200000]
        jerk = [abs(b - a) * rate for a, b in zip(acc, acc[1:])]
        f.update({"acc_mean": _r(_mean(acc), 3), "acc_sd": _r(_sd(acc), 3), "jerk_mean": _r(_mean(jerk), 3),
                  "cadence_hz": _r(1.0 / p, 3) if (p := _period(acc[:4000], 1.0 / rate, 0.25, 2.0)) else 0.0})
    if inp.get("heart"):
        h = [float(x) for x in inp["heart"]]
        f.update({"heart_mean": _r(_mean(h), 1), "heart_sd": _r(_sd(h), 2)})
    if inp.get("fixations_ms"):
        f["fixation_ms_mean"] = _r(_mean([float(x) for x in inp["fixations_ms"]]), 1)
    if not f:
        raise core.UserError("Give acceleration samples, heart rates or gaze fixations.")
    return f


def sensor_features(inp):
    chans = inp.get("channels")
    if not chans and inp.get("csv"):
        rows = [r for r in __import__("csv").reader(io.StringIO(str(inp["csv"])))]
        head = rows[0] if rows else []
        chans = {}
        for j, name in enumerate(head):
            vals = []
            for r in rows[1:]:
                try:
                    vals.append(float(r[j]))
                except (ValueError, IndexError):
                    pass
            if len(vals) >= 2 and name.strip().lower() not in ("t", "time", "timestamp", "date"):
                chans[name.strip()[:40]] = vals
    if not chans:
        raise core.UserError("Give numeric channels (CSV with a header row, or JSON {channel: [values]}).")
    rate = float(inp.get("rate_hz") or 1)
    f = {}
    for name, vals in list(chans.items())[:32]:
        v = [float(x) for x in vals][:100000]
        if len(v) < 2:
            continue
        k = re.sub(r"[^\w.-]+", "_", str(name))[:40]
        f.update({k + ".mean": _r(_mean(v), 4), k + ".sd": _r(_sd(v), 4), k + ".min": _r(min(v), 4), k + ".max": _r(max(v), 4),
                  k + ".trend_per_s": _r(_slope(v, 1.0 / rate), 5), k + ".period_s": _period(v[:4000], 1.0 / rate, 2.0 / rate, len(v) / rate / 2)})
    return f


def analyse(agent, inp, terms=None):
    """Run one sense agent on its input. Returns (features, detail). Pure: nothing is stored."""
    inp = inp or {}
    if agent == "text":
        detail = {}
        text = inp.get("text") or ""
        if inp.get("file_b64"):
            text, detail = text_from_file(base64.b64decode(str(inp["file_b64"]).split(",", 1)[-1]), inp.get("name") or "file")
        elif inp.get("url"):
            data, ctype, final = fetch(inp["url"], "text/html,text/plain,application/pdf,*/*")
            text, detail = text_from_file(data, urllib.parse.urlsplit(final).path.rsplit("/", 1)[-1] or ("page.html" if "html" in ctype else "file"))
            detail["url"] = final
        return text_features(text, terms), detail
    if agent == "audio":
        data = base64.b64decode(str(inp.get("wav_b64") or "").split(",", 1)[-1])
        return audio_features(data), {"bytes": len(data)}
    if agent == "video":
        return video_features(inp.get("frames"), inp.get("fps")), {"frames": len(inp.get("frames") or [])}
    if agent == "touch":
        return touch_features(inp), {}
    if agent == "motion":
        return motion_features(inp), {}
    if agent in ("sensor", "live"):
        return sensor_features(inp), {}
    raise core.UserError("Unknown agent %r." % agent)


def feature_defs(agent, keys=()):
    base = FEATURES.get(agent, {})
    out = dict(base)
    for k in keys:
        if k not in out:
            ch, _, stat = k.rpartition(".")
            out[k] = ("%s (%s)" % (ch, stat), "", "raise %s's %s" % (ch, stat), "lower %s's %s" % (ch, stat), True)
    return out


# ============================================================================ the Mentor: learning from exemplars
def build_profile(agent, exemplars):
    """Mastery profile from best-in-class exemplars: per measure the (rating-weighted) median, p10–p90 range, a robust
    spread, and an importance that grows with how consistently the masters share it."""
    feats = [(json.loads(e["features"]) if isinstance(e["features"], str) else e["features"], max(1, min(5, int(e.get("rating") or 3)))) for e in exemplars]
    keys = sorted({k for f, _ in feats for k in f})
    defs = feature_defs(agent, keys)
    prof = {}
    for k in keys:
        if not defs.get(k, (0, 0, 0, 0, True))[4]:
            continue
        vals = [(float(f[k]), w) for f, w in feats if isinstance(f.get(k), (int, float))]
        if not vals:
            continue
        xs = [v for v, _ in vals]
        srt = sorted(vals)
        half, acc, med = sum(w for _, w in srt) / 2.0, 0.0, srt[-1][0]
        for v, w in srt:
            acc += w
            if acc >= half:
                med = v
                break
        mad = _pct([abs(x - med) for x in xs], 0.5)
        # few exemplars say less about the true range: the spread is widened until there are enough of them
        spread = max(1.4826 * mad, 0.15 * abs(med), 1e-3) * (1 + 1.0 / len(xs))
        cv = spread / (abs(med) + spread)
        prof[k] = {"median": _r(med, 4), "p10": _r(min(med, _pct(xs, 0.1)), 4), "p90": _r(max(med, _pct(xs, 0.9)), 4), "spread": _r(spread, 5), "n": len(xs),
                   "importance": _r((1.0 - cv) * min(1.0, len(xs) / 3.0), 3)}
    tot = sum(p["importance"] for p in prof.values()) or 1
    for p in prof.values():
        p["importance"] = _r(p["importance"] / tot, 4)
    return {"agent": agent, "features": prof, "exemplars": len(exemplars), "method": "rating-weighted median, robust spread (1.4826·MAD), "
            "importance = consistency across exemplars × coverage; deterministic"}


def score(agent, features, profile, exemplars=()):
    """How close a sample is to the masters, measure by measure, with the advice that would close the gap."""
    defs = feature_defs(agent, features.keys())
    per, tot, wsum = {}, 0.0, 0.0
    for k, p in profile["features"].items():
        if k not in features:
            continue
        x = float(features[k])
        z = (x - p["median"]) / (p["spread"] or 1e-6)
        s = 100.0 * math.exp(-0.5 * max(0.0, abs(z) - 1.0) ** 2)       # within one spread of the masters = full marks
        per[k] = {"value": x, "median": p["median"], "range": [p["p10"], p["p90"]], "z": _r(z, 2), "score": _r(s, 1), "importance": p["importance"]}
        tot += p["importance"] * s; wsum += p["importance"]
    overall = _r(tot / wsum, 1) if wsum else None
    advice = []
    for k, v in sorted(per.items(), key=lambda kv: -kv[1]["importance"] * (100 - kv[1]["score"])):
        if v["score"] >= 90 or len(advice) >= 5:
            continue
        lab, unit, more, less, _ = defs.get(k, (k, "", "", "", True))
        hint = more if v["z"] < 0 else less
        advice.append({"measure": k, "label": lab, "text": "%s: yours %s%s, the best-in-class median %s (range %s–%s)%s" % (
            lab, _fmt(v["value"]), " " + unit if unit else "", _fmt(v["median"]), _fmt(v["range"][0]), _fmt(v["range"][1]), " → " + hint if hint else ""),
            "direction": "more" if v["z"] < 0 else "less"})
    near = None
    for e in exemplars:
        ef = json.loads(e["features"]) if isinstance(e["features"], str) else e["features"]
        ks = [k for k in per if k in ef]
        if not ks:
            continue
        d = math.sqrt(sum(((float(features[k]) - float(ef[k])) / (profile["features"][k]["spread"] or 1e-6)) ** 2 for k in ks) / len(ks))
        if near is None or d < near["distance"]:
            near = {"id": e["id"], "title": e["title"], "performer": e.get("performer"), "distance": _r(d, 3)}
    return {"overall": overall, "measures": per, "advice": advice, "closest_exemplar": near,
            "verdict": None if overall is None else ("best-in-class range" if overall >= 85 else "close" if overall >= 70 else "developing" if overall >= 50 else "far from the exemplars")}


def _fmt(x):
    x = float(x)
    return ("%d" % x) if x == int(x) and abs(x) < 1e6 else ("%.3g" % x if abs(x) < 10 else "%.1f" % x)


# ============================================================================ non-LLM purification of imported agents
LLM_LINE = [
    (r"\b(?:you are|you're|act as|pretend to be|role-?play)\b", "addresses a model as a persona"),
    (r"\b(?:language model|llm|gpt-?\d*|chatgpt|claude|gemini|openai|anthropic|mistral|llama|copilot)\b", "names an AI model"),
    (r"\b(?:system prompt|prompt(?:s|ing)?|few-?shot|chain[- ]of[- ]thought|think step[- ]by[- ]step|context window|tokens?\b)", "prompting instructions"),
    (r"\b(?:respond|reply|answer|output)\s+(?:with|in|only|as|using)\b", "tells a model how to answer"),
    (r"\byour (?:response|answer|reply|output|persona|personality|tone|vibe)\b", "tells a model how to answer"),
    (r"\b(?:the|this) (?:agent|assistant|model|bot|ai)\s+(?:should|must|will|can|may|never|always)\b", "instructions to an agent"),
    (r"\b(?:always|never) (?:mention|reveal|disclose|say|tell|apologi[sz]e|refuse)\b", "behaviour rules for a model"),
    (r"\b(?:hallucinat\w*|jailbreak\w*|ignore (?:all |any )?(?:previous|prior) instructions)\b", "model-specific behaviour"),
    (r"\b(?:soul|vibe|emoji|be (?:genuinely )?helpful|have opinions|be resourceful)\b", "persona and tone for a model"),
    (r"\b(?:ask the user|tell the user|the user (?:asks|wants|says))\b", "conversation rules for a model"),
    (r"\b(?:ask|tell|instruct|prompt|let) (?:the|a|your) (?:model|llm|assistant|ai|bot)\b", "instructions to a model"),
]
_LLM_RX = [(re.compile(p, re.I), why) for p, why in LLM_LINE]
_CMD = re.compile(r"^\s*(?:\$\s+|>\s+)?(?:sudo\s+)?(?:openclaw|clawhub|npm|npx|pnpm|yarn|pip3?|uv|uvx|python3?|node|bun|deno|brew|apt(?:-get)?|curl|wget|git|gh|docker|ffmpeg|jq|go|cargo|make|bash|sh|zsh|pwsh|powershell)\b", re.I)


def classify_line(line):
    for rx, why in _LLM_RX:
        if rx.search(line):
            return "llm", why
    return "keep", ""


def _frontmatter(text):
    """The --- block at the top of a SKILL.md: simple key: value lines, nested blocks, and JSON values (as Open Claw writes them)."""
    m = re.match(r"\A\s*---\s*\n(.*?)\n---\s*(?:\n|\Z)", text, re.S)
    if not m:
        return {}, text
    out, cur, buf = {}, None, []

    def flush():
        if cur is not None and buf:
            raw = "\n".join(buf).strip()
            try:
                out[cur] = json.loads(raw)
            except ValueError:
                out[cur] = _yaml_block(buf)
    for line in m.group(1).splitlines():
        km = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if km:
            flush(); buf = []
            cur, val = km.group(1), km.group(2).strip()
            if val:
                if val[:1] in "{[":
                    buf = [val]
                    continue
                out[cur] = val.strip("\"'")
                cur = None
        elif cur is not None:
            buf.append(line)
    flush()
    return out, text[m.end():]


def _yaml_block(lines):
    """A small nested YAML subset (indented keys, lists of scalars) — enough for skill metadata."""
    root = {}
    stack = [(-1, root, None, None)]                             # (indent, container, its parent, its key)
    for line in lines:
        if not line.strip() or line.strip().startswith("#"):
            continue
        ind = len(line) - len(line.lstrip())
        s = line.strip()
        while len(stack) > 1 and (ind < stack[-1][0] or (ind == stack[-1][0] and not s.startswith("- "))):
            stack.pop()
        _, parent, gp, key = stack[-1]
        if s.startswith("- "):
            if isinstance(parent, dict) and not parent and gp is not None:
                parent = gp[key] = []
                stack[-1] = (stack[-1][0], parent, gp, key)
            if isinstance(parent, list):
                parent.append(s[2:].strip().strip("\"'"))
            continue
        km = re.match(r"^([\w.-]+):\s*(.*)$", s)
        if not km or not isinstance(parent, dict):
            continue
        k, v = km.group(1), km.group(2).strip()
        if v:
            try:
                parent[k] = json.loads(v)
            except ValueError:
                parent[k] = [x.strip().strip("\"'") for x in v.strip("[]").split(",") if x.strip()] if v.startswith("[") else v.strip("\"'")
        else:
            nxt = {}
            parent[k] = nxt
            stack.append((ind + 1, nxt, parent, k))
    return root


def purify(text):
    """Split an agent's text into what a program can use (kept) and what only instructs a model (quarantined)."""
    kept = {"steps": [], "commands": [], "facts": [], "headings": [], "links": []}
    quarantined = []
    in_code = False
    for raw in str(text or "").splitlines():
        line = raw.rstrip()
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        s = line.strip()
        if not s:
            continue
        if in_code or _CMD.match(s):
            if llm_host(s) or re.search(r"\b(?:openai|anthropic)\b", s, re.I):
                quarantined.append({"line": s[:300], "why": "calls an AI-model service"})
            elif not s.startswith("#"):
                kept["commands"].append(s[:300])
            continue
        kind, why = classify_line(s)
        if kind == "llm":
            quarantined.append({"line": s[:300], "why": why})
            continue
        kept["links"] += [u for u in re.findall(r"https?://[^\s)>\]\"']+", s) if not llm_host(u)][:5]
        hm = re.match(r"^#{1,6}\s+(.*)", s)
        if hm:
            kept["headings"].append(hm.group(1).strip()[:120])
        elif re.match(r"^(?:[-*+]|\d+[.)])\s+", s):
            kept["steps"].append(re.sub(r"^(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s*)?", "", s)[:300])
        else:
            kept["facts"].append(s[:400])
    words = [w.lower() for w in _WORD.findall(" ".join(kept["steps"] + kept["facts"] + kept["headings"]))]
    freq = {}
    for w in words:
        if len(w) > 3 and w not in STOP:
            freq[w] = freq.get(w, 0) + 1
    kept["terms"] = [w for w, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:30]]
    for k in ("links", "commands"):
        kept[k] = list(dict.fromkeys(kept[k]))[:200]
    return kept, quarantined


def _count_kept(k):
    return sum(len(k.get(x) or []) for x in ("steps", "commands", "facts", "headings"))


def parse_skill(files, origin, ref):
    """An Open Claw / Agent Skills folder ({path: bytes}) → a playbook. Scripts are described, never run."""
    paths = sorted(files)
    main = min((p for p in paths if p.rsplit("/", 1)[-1].lower() == "skill.md"), key=lambda p: p.count("/"), default=None)
    if not main:
        raise core.UserError("No SKILL.md in this skill.")
    root = main.rsplit("/", 1)[0] + "/" if "/" in main else ""
    text = files[main].decode("utf-8", "replace")
    fm, body = _frontmatter(text)
    kept, quar = purify(body)
    meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
    oc = meta.get("openclaw") or meta.get("clawdbot") or meta.get("clawdis") or {}
    req = oc.get("requires") or {} if isinstance(oc, dict) else {}
    resources, warnings = [], []
    for p in paths:
        if p == main or not p.startswith(root):
            continue
        data = files[p]
        fmt, segs, m = qbartifact.segment(data, p)
        r = {"path": p[len(root):], "format": m.get("format_name"), "bytes": len(data), "sha256": m.get("sha256")}
        if fmt in ("code", "exe", "elf", "macho") or p.lower().endswith((".sh", ".py", ".js", ".ts", ".ps1", ".bat", ".rb", ".mjs", ".cjs")):
            r["note"] = "script — described, never run"
            warnings.append("contains a script (%s): listed only, never executed" % r["path"])
        elif fmt in ("markdown", "text"):
            k2, q2 = purify(data.decode("utf-8", "replace"))
            for key in ("steps", "commands", "facts", "headings", "links"):
                kept[key] += k2[key]
            quar += [dict(q, file=r["path"]) for q in q2]
        resources.append(r)
    tools = sorted(set((req.get("bins") or []) + (req.get("anyBins") or []))) if isinstance(req, dict) else []
    tools += sorted({c.split()[0].lstrip("$>").strip() for c in kept["commands"] if c.split()} - set(tools))
    data = {"frontmatter": {k: v for k, v in fm.items() if k != "metadata"}, "openclaw": oc if isinstance(oc, dict) else {},
            "requires": {"bins": req.get("bins") or [], "anyBins": req.get("anyBins") or [], "env": req.get("env") or [],
                         "config": req.get("config") or []} if isinstance(req, dict) else {},
            "tools": tools[:60], "kept": kept, "quarantined": quar[:500], "resources": resources[:300],
            "how_used": "knowledge only: checklist steps, terms and facts feed the deterministic agents; commands and scripts are listed, never run; "
                        "lines that instruct a language model are quarantined"}
    name = str(fm.get("name") or ref.rsplit("/", 1)[-1] or "skill")[:80]
    return {"origin": origin, "ref": ref, "kind": "skill", "name": name, "version": str(fm.get("version") or "")[:40],
            "description": " ".join(str(fm.get("description") or "").split())[:500], "data": data, "warnings": warnings}


def unzip_skill(blob):
    """Files of a skill zip, with the same limits as the Artifact Segmenter (no bombs, no absolute paths)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise core.UserError("Not a zip file.")
    files, total = {}, 0
    for info in z.infolist()[:2000]:
        n = info.filename.replace("\\", "/")
        if info.is_dir() or n.startswith(("/", "../")) or "/../" in n or "__MACOSX" in n or n.rsplit("/", 1)[-1].startswith("."):
            continue
        total += info.file_size
        if info.file_size > 10 * 1048576 or total > 60 * 1048576 or (info.compress_size and info.file_size / info.compress_size > 200):
            raise core.UserError("The skill archive is too large or suspiciously compressed.")
        files[n] = z.read(info)
    return files


# ---- an Open Claw installation on this computer: its agents, skills and tools (read-only; secrets never read)
OC_AGENT_FILES = ("AGENTS.md", "SOUL.md", "IDENTITY.md", "TOOLS.md", "HEARTBEAT.md", "BOOT.md")
OC_PERSONAL_FILES = ("USER.md", "MEMORY.md")
OC_SECRET = re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key|apikey|auth|credential|cookie|session|private)")


def _json5(text):
    t = re.sub(r"(?m)^\s*//.*$", "", text)
    t = re.sub(r"/\*.*?\*/", "", t, flags=re.S)
    t = re.sub(r",\s*([}\]])", r"\1", t)
    t = re.sub(r"(?m)([{,]\s*)([A-Za-z_][\w-]*)\s*:", r'\1"\2":', t)
    t = re.sub(r"'([^'\\\n]*)'", r'"\1"', t)
    return json.loads(t)


def _redact(o):
    if isinstance(o, dict):
        return {k: ("•••" if OC_SECRET.search(str(k)) else _redact(v)) for k, v in o.items()}
    if isinstance(o, list):
        return [_redact(v) for v in o]
    return o


def openclaw_home(path=None):
    return os.path.abspath(os.path.expanduser(path or os.environ.get("OPENCLAW_HOME") or os.path.join("~", ".openclaw")))


def scan_openclaw(home=None, include_personal=False):
    """Read an Open Claw installation: openclaw.json (secrets redacted), each agent's workspace files, every skill
    folder, and the tools the configuration allows or denies. Only these known files are read; credentials, sessions
    and keys never are."""
    home = openclaw_home(home)
    if not os.path.isdir(home):
        return {"home": home, "found": False, "agents": [], "skills": [], "tools": {}}
    cfg, cfg_err = {}, None
    cp = os.path.join(home, "openclaw.json")
    if os.path.isfile(cp):
        try:
            with open(cp, encoding="utf-8") as f:
                cfg = _redact(_json5(f.read()))
        except (OSError, ValueError) as e:
            cfg_err = "openclaw.json could not be read: %s" % e
    ag = cfg.get("agents") or {}
    default_ws = os.environ.get("OPENCLAW_WORKSPACE_DIR") or (ag.get("defaults") or {}).get("workspace") or os.path.join(home, "workspace")
    entries = ag.get("entries") or {}
    if isinstance(ag.get("list"), list):
        entries = dict(entries, **{str(a.get("id") or a.get("name") or i): a for i, a in enumerate(ag["list"]) if isinstance(a, dict)})
    workspaces = {"main": default_ws}
    for aid, a in entries.items():
        if isinstance(a, dict):
            workspaces[str(aid)] = a.get("workspace") or default_ws
    agents, seen = [], set()
    for aid, ws in workspaces.items():
        ws = os.path.abspath(os.path.expanduser(ws))
        files = {}
        for fn in OC_AGENT_FILES + (OC_PERSONAL_FILES if include_personal else ()):
            p = os.path.join(ws, fn)
            if os.path.isfile(p) and os.path.getsize(p) < 2 * 1048576:
                with open(p, "rb") as f:
                    files[fn] = f.read()
        if include_personal and os.path.isdir(os.path.join(ws, "memory")):
            for fn in sorted(os.listdir(os.path.join(ws, "memory")))[-60:]:
                if fn.endswith(".md"):
                    with open(os.path.join(ws, "memory", fn), "rb") as f:
                        files["memory/" + fn] = f.read(1048576)
        if files and (aid, ws) not in seen:
            seen.add((aid, ws))
            agents.append({"id": aid, "workspace": ws, "files": files, "config": entries.get(aid) if isinstance(entries.get(aid), dict) else {}})
    skill_dirs = [os.path.join(w, "skills") for w in sorted(set(os.path.abspath(os.path.expanduser(x)) for x in workspaces.values()))]
    skill_dirs += [os.path.join(home, "skills")] + [os.path.expanduser(d) for d in ((cfg.get("skills") or {}).get("load") or {}).get("extraDirs") or [] if isinstance(d, str)]
    skills = []
    for d in skill_dirs:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            sd = os.path.join(d, name)
            if not os.path.isfile(os.path.join(sd, "SKILL.md")):
                continue
            files, total = {}, 0
            for r, dirs, fns in os.walk(sd):
                dirs[:] = [x for x in dirs if not x.startswith(".") and x != "node_modules"]
                for fn in fns:
                    p = os.path.join(r, fn)
                    if fn.startswith(".") or os.path.islink(p) or OC_SECRET.search(fn) and not fn.lower().endswith(".md"):
                        continue
                    total += os.path.getsize(p)
                    if total > 30 * 1048576 or len(files) > 400:
                        break
                    with open(p, "rb") as f:
                        files[os.path.relpath(p, d).replace(os.sep, "/")] = f.read(10 * 1048576)
            skills.append({"dir": sd, "files": files})
    tools = {k: cfg.get("tools", {}).get(k) for k in ("profile", "allow", "deny", "alsoAllow", "byProvider") if isinstance(cfg.get("tools"), dict) and k in cfg["tools"]}
    for aid, a in entries.items():
        if isinstance(a, dict) and isinstance(a.get("tools"), dict):
            tools["agent:" + str(aid)] = a["tools"]
    plugins = cfg.get("plugins") or {}
    mcp = cfg.get("mcp") or cfg.get("mcpServers") or {}
    return {"home": home, "found": True, "config_error": cfg_err, "agents": agents, "skills": skills, "tools": tools,
            "plugins": sorted((plugins.get("entries") or plugins).keys()) if isinstance(plugins, dict) else [],
            "mcp_servers": sorted((mcp.get("servers") or mcp).keys()) if isinstance(mcp, dict) else []}


def parse_agent(a):
    kept_all = {"steps": [], "commands": [], "facts": [], "headings": [], "links": []}
    quar, by_file = [], {}
    ident = {}
    for fn, data in a["files"].items():
        t = data.decode("utf-8", "replace")
        if fn == "IDENTITY.md":
            for line in t.splitlines():
                m = re.match(r"^\s*[-*]?\s*\**(name|emoji|creature|vibe)\**\s*[:：]\s*(.+)$", line, re.I)
                if m:
                    ident[m.group(1).lower()] = m.group(2).strip()[:80]
        k, q = purify(t)
        for key in kept_all:
            kept_all[key] += k[key]
        quar += [dict(x, file=fn) for x in q]
        by_file[fn] = {"kept": _count_kept(k), "quarantined": len(q)}
    words = [w.lower() for w in _WORD.findall(" ".join(kept_all["steps"] + kept_all["facts"]))]
    freq = {}
    for w in words:
        if len(w) > 3 and w not in STOP:
            freq[w] = freq.get(w, 0) + 1
    kept_all["terms"] = [w for w, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:30]]
    name = ident.get("name") or ("Open Claw agent " + a["id"])
    return {"origin": "openclaw-local", "ref": a["workspace"] + "#" + a["id"], "kind": "agent", "name": name[:80], "version": "",
            "description": "Open Claw agent '%s' (workspace %s)" % (a["id"], a["workspace"]),
            "data": {"identity": {k: v for k, v in ident.items() if k == "name"}, "files": by_file, "config": a.get("config") or {}, "kept": kept_all,
                     "quarantined": quar[:800], "how_used": "knowledge only: its procedures, checklists and tool conventions are kept; its persona and "
                     "instructions to the model are quarantined; the agent itself is never run"},
            "warnings": []}


# ============================================================================ the hub
class Hub:
    def __init__(self, app_folder, app_id, log=None):
        self.folder = os.path.join(app_folder, "agents")
        os.makedirs(self.folder, exist_ok=True)
        self.store = core.Store(self.folder, "agents", SCHEMA, log)
        self.app_id, self.log = app_id, (log or (lambda *a: None))
        self.approvals = None
        self.devices = None
        self._stop = threading.Event()
        self._thread = None

    # ---- pick and choose
    def _settings_path(self):
        return os.path.join(self.folder, "settings.json")

    def settings(self):
        s = {"enabled": {a: True for a in AGENT_IDS}}
        try:
            with open(self._settings_path(), encoding="utf-8") as f:
                s["enabled"].update(json.load(f).get("enabled", {}))
        except (OSError, ValueError):
            pass
        return s

    def _admin(self, passphrase):
        ap = self.approvals
        if ap is not None and ap.admin_set():
            ap._require(passphrase or "")

    def pick(self, agent, enabled, passphrase=None):
        if agent not in AGENT_IDS:
            raise core.UserError("Unknown agent.")
        self._admin(passphrase)
        s = self.settings()
        s["enabled"][agent] = bool(enabled)
        with open(self._settings_path(), "w", encoding="utf-8") as f:
            json.dump(s, f)
        return s

    def _need(self, agent):
        if not self.settings()["enabled"].get(agent, True):
            raise core.UserError("The %s agent is switched off — turn it on under Agents → Pick your agents." % next(a["name"] for a in AGENTS if a["id"] == agent))

    def status(self):
        en = self.settings()["enabled"]
        n = lambda t: self.store.scalar("SELECT COUNT(*) FROM %s" % t, default=0)
        return {"version": VERSION, "agents": [dict(a, enabled=en.get(a["id"], True), llm=False, deterministic=True,
                                                    network=("only the feed addresses you add" if a["id"] == "live" else "ClawHub registry (read-only)" if a["id"] == "claw"
                                                             else "a web page you give it" if a["id"] == "text" else "none")) for a in AGENTS],
                "counts": {"skills": n("skills"), "exemplars": n("exemplars"), "samples": n("samples"), "playbooks": n("playbooks"),
                           "clawhub_index": n("clawhub_index"), "feeds": n("feeds"), "readings": n("readings")},
                "purity": self.purity(), "openclaw_home": openclaw_home(), "clawhub": CLAWHUB}

    def purity(self):
        """The non-LLM commitment, checked: no agent is a model, no model service is reachable, model instructions in
        imported agents are quarantined."""
        src = open(os.path.abspath(__file__), encoding="utf-8").read()
        imports = re.findall(r"^\s*(?:import|from)\s+([\w.]+)", src, re.M)
        bad = [m for m in imports if m.split(".")[0] in ("openai", "anthropic", "google", "transformers", "torch", "llama_cpp", "ollama", "langchain", "cohere", "mistralai")]
        q = self.store.scalar("SELECT SUM(quarantined) FROM playbooks", default=0)
        k = self.store.scalar("SELECT SUM(kept) FROM playbooks", default=0)
        return {"ok": not bad, "model_imports": bad, "llm_hosts_blocked": len(LLM_HOSTS), "agents_using_models": 0,
                "imported_lines_kept": k, "imported_lines_quarantined": q,
                "statement": "Every agent is a deterministic program (measurements, statistics, stated rules); none calls or imitates an AI model. "
                             "Requests to AI-model services are refused. Model instructions inside imported agents are quarantined — kept for inspection, never used."}

    # ---- skills, exemplars, samples
    def skills(self):
        rows = self.store.query("""SELECT s.*, (SELECT COUNT(*) FROM exemplars e WHERE e.skill_id = s.id) AS exemplars,
                                   (SELECT COUNT(*) FROM samples x WHERE x.skill_id = s.id) AS samples,
                                   (SELECT MAX(version) FROM profiles p WHERE p.skill_id = s.id) AS profile_version,
                                   (SELECT MAX(version) FROM profiles p WHERE p.skill_id = s.id AND adopted IS NOT NULL) AS adopted_version
                                   FROM skills s ORDER BY name""")
        return rows

    def skill(self, sid):
        r = self.store.one("SELECT * FROM skills WHERE id = ?", (int(sid),))
        if not r:
            raise core.UserError("No such skill.")
        return r

    def add_skill(self, name, agent, description=None):
        name = " ".join(str(name or "").split())[:80]
        if not name:
            raise core.UserError("Name the skill (for example: Persuasive speaking).")
        if agent not in SENSE_AGENTS:
            raise core.UserError("Choose the agent that measures it: " + ", ".join(SENSE_AGENTS))
        if self.store.one("SELECT id FROM skills WHERE name = ?", (name,)):
            raise core.UserError("A skill with that name exists.")
        with self.store.write() as db:
            sid = db.execute("INSERT INTO skills(name, agent, description, created) VALUES(?,?,?,?)", (name, agent, str(description or "")[:500], _now())).lastrowid
        return self.skill(sid)

    def delete_skill(self, sid):
        self.skill(sid)
        with self.store.write() as db:
            db.execute("DELETE FROM skills WHERE id = ?", (int(sid),))
        return {"deleted": True}

    def attach_playbook(self, sid, pid):
        self.skill(sid)
        if pid:
            self.playbook(pid)
        with self.store.write() as db:
            db.execute("UPDATE skills SET playbook_id = ? WHERE id = ?", (int(pid) if pid else None, int(sid)))
        return self.skill(sid)

    def _terms(self, sk):
        if not sk.get("playbook_id"):
            return None
        pb = self.store.one("SELECT data, enabled FROM playbooks WHERE id = ?", (sk["playbook_id"],))
        if not pb or not pb["enabled"]:
            return None
        return (json.loads(pb["data"]).get("kept") or {}).get("terms") or None

    def _run(self, sk, inp):
        self._need(sk["agent"])
        if inp.get("feed_id"):
            vals = [r["value"] for r in self.store.query("SELECT value FROM readings WHERE feed_id = ? ORDER BY t", (int(inp["feed_id"]),))]
            fd = self.store.one("SELECT name, every_s FROM feeds WHERE id = ?", (int(inp["feed_id"]),)) or {"name": "feed", "every_s": 60}
            inp = {"channels": {fd["name"]: vals}, "rate_hz": 1.0 / fd["every_s"]}
        return analyse(sk["agent"], inp, self._terms(sk))

    def add_exemplar(self, sid, title, inp, licence, performer=None, source=None, rating=4):
        sk = self.skill(sid)
        lic = str(licence or "").strip()
        if not lic:
            raise core.UserError("Say what lets you use this example: your own, public domain, Creative Commons, government work, or permission.")
        feats, detail = self._run(sk, inp or {})
        sha = hashlib.sha256(json.dumps(feats, sort_keys=True).encode()).hexdigest()
        with self.store.write() as db:
            cur = db.execute("""INSERT OR IGNORE INTO exemplars(skill_id, title, performer, source, licence, rating, features, detail, sha, created)
                                VALUES(?,?,?,?,?,?,?,?,?,?)""", (sk["id"], str(title or "exemplar")[:120], str(performer or "")[:120] or None,
                                                                str(source or detail.get("url") or "")[:500] or None, lic[:120],
                                                                max(1, min(5, int(rating or 4))), json.dumps(feats), json.dumps(detail), sha, _now()))
            dup = not cur.rowcount
        prof = None if dup else self.rebuild(sk["id"])
        return {"duplicate": dup, "features": feats, "detail": detail, "profile": prof}

    def delete_exemplar(self, eid):
        r = self.store.one("SELECT skill_id FROM exemplars WHERE id = ?", (int(eid),))
        if not r:
            raise core.UserError("No such exemplar.")
        with self.store.write() as db:
            db.execute("DELETE FROM exemplars WHERE id = ?", (int(eid),))
        return {"deleted": True, "profile": self.rebuild(r["skill_id"])}

    def exemplars(self, sid):
        rows = self.store.query("SELECT * FROM exemplars WHERE skill_id = ? ORDER BY id", (int(sid),))
        for r in rows:
            r["features"] = json.loads(r["features"]); r["detail"] = json.loads(r["detail"] or "{}")
        return rows

    def rebuild(self, sid):
        sk = self.skill(sid)
        ex = self.store.query("SELECT * FROM exemplars WHERE skill_id = ? ORDER BY id", (sk["id"],))
        if not ex:
            return None
        prof = build_profile(sk["agent"], ex)
        prof["exemplar_ids"] = [e["id"] for e in ex]
        with self.store.write() as db:
            v = (db.execute("SELECT MAX(version) FROM profiles WHERE skill_id = ?", (sk["id"],)).fetchone()[0] or 0) + 1
            db.execute("INSERT INTO profiles(skill_id, version, profile, n, created) VALUES(?,?,?,?,?)", (sk["id"], v, json.dumps(prof), len(ex), _now()))
        return {"version": v, "exemplars": len(ex), "measures": len(prof["features"])}

    def profile(self, sid, version=None):
        self.skill(sid)
        if version:
            r = self.store.one("SELECT * FROM profiles WHERE skill_id = ? AND version = ?", (int(sid), int(version)))
        else:
            r = (self.store.one("SELECT * FROM profiles WHERE skill_id = ? AND adopted IS NOT NULL ORDER BY version DESC LIMIT 1", (int(sid),))
                 or self.store.one("SELECT * FROM profiles WHERE skill_id = ? ORDER BY version DESC LIMIT 1", (int(sid),)))
        if not r:
            return None
        r["profile"] = json.loads(r["profile"])
        r["status"] = "adopted" if r["adopted"] else "candidate (not adopted yet)"
        return r

    def adopt(self, sid, version, passphrase=None):
        self._admin(passphrase)
        r = self.store.one("SELECT id FROM profiles WHERE skill_id = ? AND version = ?", (int(sid), int(version)))
        if not r:
            raise core.UserError("No such profile version.")
        with self.store.write() as db:
            db.execute("UPDATE profiles SET adopted = ? WHERE id = ?", (_now(), r["id"]))
        return self.profile(sid, version)

    def sample(self, sid, inp, title=None, keep=True):
        sk = self.skill(sid)
        feats, detail = self._run(sk, inp or {})
        pr = self.profile(sk["id"])
        if not pr:
            res = {"overall": None, "advice": [], "measures": {}, "note": "Add best-in-class exemplars first — then every sample is scored against them."}
        else:
            ex = self.store.query("SELECT id, title, performer, features FROM exemplars WHERE skill_id = ?", (sk["id"],))
            res = score(sk["agent"], feats, pr["profile"], ex)
            res["profile_version"], res["profile_status"] = pr["version"], pr["status"]
        if keep:
            with self.store.write() as db:
                res["id"] = db.execute("INSERT INTO samples(skill_id, title, features, result, created) VALUES(?,?,?,?,?)",
                                       (sk["id"], str(title or "sample")[:120], json.dumps(feats), json.dumps(res), _now())).lastrowid
        res["features"], res["detail"] = feats, detail
        return res

    def samples(self, sid, limit=100):
        rows = self.store.query("SELECT id, title, result, created FROM samples WHERE skill_id = ? ORDER BY id DESC LIMIT ?", (int(sid), int(limit)))
        out = []
        for r in rows:
            res = json.loads(r["result"])
            out.append({"id": r["id"], "title": r["title"], "created": r["created"], "overall": res.get("overall"), "verdict": res.get("verdict"),
                        "advice": [a["text"] for a in res.get("advice", [])][:3]})
        return out

    # ---- playbooks (imported agents, skills and tools)
    def _save_playbook(self, pb):
        data = json.dumps(pb["data"], sort_keys=True, default=str)
        sha = hashlib.sha256((pb["origin"] + "|" + pb["ref"] + "|" + data).encode()).hexdigest()
        kept, quar = _count_kept(pb["data"].get("kept") or {}), len(pb["data"].get("quarantined") or [])
        with self.store.write() as db:
            old = db.execute("SELECT id FROM playbooks WHERE sha = ?", (sha,)).fetchone()
            if old:
                return {"id": old[0], "duplicate": True, "name": pb["name"]}
            db.execute("DELETE FROM playbooks WHERE origin = ? AND ref = ?", (pb["origin"], pb["ref"]))    # a newer copy replaces the old
            pid = db.execute("""INSERT INTO playbooks(origin, ref, kind, name, version, description, data, kept, quarantined, warnings, sha, created)
                                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (pb["origin"], pb["ref"], pb["kind"], pb["name"], pb.get("version") or "",
                                                                     pb.get("description") or "", data, kept, quar, json.dumps(pb.get("warnings") or []), sha, _now())).lastrowid
        return {"id": pid, "duplicate": False, "name": pb["name"], "kept": kept, "quarantined": quar}

    def playbooks(self, kind=None):
        rows = self.store.query("SELECT id, origin, ref, kind, name, version, description, kept, quarantined, warnings, enabled, created FROM playbooks"
                                + (" WHERE kind = ?" if kind else "") + " ORDER BY kind, name", (kind,) if kind else ())
        for r in rows:
            r["warnings"] = json.loads(r["warnings"] or "[]")
        return rows

    def playbook(self, pid):
        r = self.store.one("SELECT * FROM playbooks WHERE id = ?", (int(pid),))
        if not r:
            raise core.UserError("No such playbook.")
        r["data"] = json.loads(r["data"]); r["warnings"] = json.loads(r["warnings"] or "[]")
        return r

    def pick_playbook(self, pid, enabled):
        self.playbook(pid)
        with self.store.write() as db:
            db.execute("UPDATE playbooks SET enabled = ? WHERE id = ?", (1 if enabled else 0, int(pid)))
        return {"id": int(pid), "enabled": bool(enabled)}

    def delete_playbook(self, pid):
        self.playbook(pid)
        with self.store.write() as db:
            db.execute("UPDATE skills SET playbook_id = NULL WHERE playbook_id = ?", (int(pid),))
            db.execute("DELETE FROM playbooks WHERE id = ?", (int(pid),))
        return {"deleted": True}

    def import_upload(self, name, data_b64):
        self._need("claw")
        blob = base64.b64decode(str(data_b64 or "").split(",", 1)[-1])
        if blob[:2] == b"PK":
            files = unzip_skill(blob)
        else:
            files = {"SKILL.md": blob}
        return self._save_playbook(parse_skill(files, "upload", str(name or "skill")[:120]))

    # ---- Open Claw: ClawHub registry
    def claw_search(self, q, limit=30, safe=True):
        self._need("claw")
        qs = urllib.parse.urlencode({"q": str(q or "")[:120], "limit": max(1, min(100, int(limit or 30))), **({"nonSuspiciousOnly": "true"} if safe else {})})
        data, _, _ = fetch(CLAWHUB.rstrip("/") + "/api/v1/search?" + qs, "application/json")
        res = json.loads(data.decode("utf-8")).get("results") or []
        return {"results": [{"slug": r.get("slug"), "name": r.get("displayName") or r.get("slug"), "summary": r.get("summary"), "version": r.get("version"),
                             "owner": r.get("ownerHandle") or (r.get("owner") or {}).get("handle"), "updated": r.get("updatedAt")} for r in res]}

    def claw_sync_index(self, max_pages=500, safe=True, sort="updated"):
        """Every skill in ClawHub, page by page (metadata only), into a local index you can browse and pick from."""
        self._need("claw")
        cursor, pages, n = None, 0, 0
        while pages < max_pages:
            qs = {"limit": 200, "sort": sort, **({"nonSuspiciousOnly": "true"} if safe else {}), **({"cursor": cursor} if cursor else {})}
            data, _, _ = fetch(CLAWHUB.rstrip("/") + "/api/v1/skills?" + urllib.parse.urlencode(qs), "application/json")
            d = json.loads(data.decode("utf-8"))
            items = d.get("items") or []
            now = _now()
            with self.store.write() as db:
                for it in items:
                    lv = it.get("latestVersion")
                    db.execute("""INSERT INTO clawhub_index(slug, name, summary, version, updated, owner, data, seen) VALUES(?,?,?,?,?,?,?,?)
                                  ON CONFLICT(slug) DO UPDATE SET name=excluded.name, summary=excluded.summary, version=excluded.version,
                                  updated=excluded.updated, owner=excluded.owner, data=excluded.data, seen=excluded.seen""",
                               (it.get("slug"), it.get("displayName") or it.get("slug"), (it.get("summary") or "")[:500],
                                (lv.get("version") if isinstance(lv, dict) else lv) or "", str(it.get("updatedAt") or ""), it.get("ownerHandle") or "",
                                json.dumps({k: it.get(k) for k in ("topics", "tags", "stats")}, default=str), now))
            n += len(items); pages += 1
            cursor = d.get("nextCursor")
            if not cursor:
                break
        return {"indexed": n, "pages": pages, "complete": not cursor, "total": self.store.scalar("SELECT COUNT(*) FROM clawhub_index", default=0)}

    def claw_index(self, q=None, limit=100, offset=0):
        w, a = "", []
        if q:
            w = " WHERE slug LIKE ? OR name LIKE ? OR summary LIKE ?"; a = ["%" + q + "%"] * 3
        rows = self.store.query("SELECT slug, name, summary, version, updated, owner FROM clawhub_index" + w + " ORDER BY name LIMIT ? OFFSET ?", a + [int(limit), int(offset)])
        return {"items": rows, "total": self.store.scalar("SELECT COUNT(*) FROM clawhub_index" + w, a, 0)}

    def claw_import(self, slug, version=None):
        """Download one ClawHub skill (zip) and turn it into a playbook. Flagged skills are refused."""
        self._need("claw")
        slug = str(slug or "").strip()
        if not re.match(r"^[\w.-]{1,128}(?:/[\w.-]{1,128})?$", slug):
            raise core.UserError("Give the skill's slug (as ClawHub shows it).")
        base = CLAWHUB.rstrip("/") + "/api/v1"
        info = {}
        try:
            info = json.loads(fetch(base + "/skills/" + urllib.parse.quote(slug), "application/json")[0].decode("utf-8"))
        except core.UserError:
            pass
        mod = info.get("moderation") or {}
        if mod and (mod.get("status") in ("flagged", "hidden", "blocked", "malicious") or mod.get("isSuspicious") or mod.get("flagged")):
            raise core.UserError("ClawHub has flagged '%s' — not imported." % slug)
        qs = {"slug": slug, **({"version": version} if version else {"tag": "latest"})}
        blob, ctype, _ = fetch(base + "/download?" + urllib.parse.urlencode(qs), "application/zip")
        if "json" in ctype or blob[:1] == b"{":
            ref = json.loads(blob.decode("utf-8"))
            if not ref.get("archiveUrl"):
                raise core.UserError("ClawHub gave no archive for '%s'." % slug)
            blob, _, _ = fetch(ref["archiveUrl"], "application/zip")
        files = unzip_skill(blob)
        pb = parse_skill(files, "clawhub", slug)
        pb["data"]["clawhub"] = {"slug": slug, "version": version or (info.get("latestVersion") or {}).get("version") if isinstance(info.get("latestVersion"), dict) else version,
                                 "owner": (info.get("owner") or {}).get("handle") if isinstance(info.get("owner"), dict) else None}
        return self._save_playbook(pb)

    # ---- Open Claw: an installation on this computer
    def claw_local(self, home=None, include_personal=False, passphrase=None, preview=False):
        self._need("claw")
        if home:
            self._admin(passphrase)                              # reading another folder is the admin's call
        sc = scan_openclaw(home, include_personal)
        if not sc["found"]:
            return {"home": sc["home"], "found": False, "imported": []}
        out = []
        for a in sc["agents"]:
            pb = parse_agent(a)
            out.append(pb if preview else self._save_playbook(pb))
        for s in sc["skills"]:
            try:
                pb = parse_skill(s["files"], "openclaw-local", s["dir"])
                out.append(pb if preview else self._save_playbook(pb))
            except core.UserError as e:
                out.append({"name": s["dir"], "error": str(e)})
        tools = {"tools_config": sc["tools"], "plugins": sc["plugins"], "mcp_servers": sc["mcp_servers"],
                 "skill_tools": sorted({t for s in out if isinstance(s, dict) and s.get("data") for t in (s["data"].get("tools") or [])})}
        tpb = {"origin": "openclaw-local", "ref": sc["home"] + "#tools", "kind": "tools", "name": "Open Claw tools (%s)" % os.path.basename(sc["home"]),
               "description": "Tools the Open Claw configuration allows or denies, its plugins and MCP servers, and the command-line tools its skills need — "
                              "a catalogue; nothing is run.", "data": dict(tools, kept={"steps": [], "commands": [], "facts": [], "headings": [], "links": [], "terms": []},
                                                                           quarantined=[], how_used="catalogue only"), "warnings": []}
        if not preview:
            out.append(self._save_playbook(tpb))
            for o in out:                                        # stored rows only carry ids; drop parsed bodies from the answer
                if isinstance(o, dict):
                    o.pop("data", None)
        return {"home": sc["home"], "found": True, "config_error": sc.get("config_error"), "agents": len(sc["agents"]), "skills": len(sc["skills"]),
                "imported": out if not preview else [{"name": o.get("name"), "kind": o.get("kind"), "kept": _count_kept((o.get("data") or {}).get("kept") or {}),
                                                     "quarantined": len((o.get("data") or {}).get("quarantined") or [])} for o in out]}

    # ---- live data
    def add_feed(self, name, url, path=None, every_s=300):
        self._need("live")
        if llm_host(url):
            raise core.UserError("Refused: that address is an AI-model service.")
        fetch_ok = urllib.parse.urlsplit(str(url)).scheme in ("http", "https")
        if not fetch_ok:
            raise core.UserError("Give a web address starting with https://")
        with self.store.write() as db:
            fid = db.execute("INSERT INTO feeds(name, url, path, every_s, created) VALUES(?,?,?,?,?)",
                             (" ".join(str(name or "feed").split())[:60], str(url)[:800], str(path or "")[:200], max(30, int(every_s or 300)), _now())).lastrowid
        return self.poll(fid)

    def feeds(self):
        rows = self.store.query("SELECT f.*, (SELECT COUNT(*) FROM readings r WHERE r.feed_id = f.id) AS n, "
                                "(SELECT value FROM readings r WHERE r.feed_id = f.id ORDER BY t DESC LIMIT 1) AS latest FROM feeds f ORDER BY id")
        return rows

    def delete_feed(self, fid):
        with self.store.write() as db:
            db.execute("DELETE FROM feeds WHERE id = ?", (int(fid),))
        return {"deleted": True}

    @staticmethod
    def _extract(data, ctype, path):
        t = data.decode("utf-8", "replace").strip()
        if t[:1] in "{[":
            o = json.loads(t)
            for part in [p for p in re.split(r"[./]", path or "") if p]:
                o = o[int(part)] if isinstance(o, list) else o[part]
            if isinstance(o, list):
                o = o[-1]
            return float(o)
        rows = list(__import__("csv").reader(io.StringIO(t)))
        if not rows:
            raise ValueError("empty")
        head = rows[0]
        j = head.index(path) if path in head else len(head) - 1
        return float(rows[-1][j])

    def poll(self, fid):
        f = self.store.one("SELECT * FROM feeds WHERE id = ?", (int(fid),))
        if not f:
            raise core.UserError("No such feed.")
        try:
            data, ctype, _ = fetch(f["url"], "application/json,text/csv,text/plain", limit=5 * 1048576)
            v = self._extract(data, ctype, f["path"])
            with self.store.write() as db:
                db.execute("INSERT INTO readings(feed_id, t, value) VALUES(?,?,?)", (f["id"], _now(), v))
                db.execute("UPDATE feeds SET last = ?, error = NULL WHERE id = ?", (_now(), f["id"]))
            return {"id": f["id"], "value": v}
        except (core.UserError, ValueError, KeyError, IndexError, TypeError) as e:
            with self.store.write() as db:
                db.execute("UPDATE feeds SET last = ?, error = ? WHERE id = ?", (_now(), str(e)[:300], f["id"]))
            return {"id": f["id"], "error": str(e)}

    def _loop(self):
        while not self._stop.wait(15):
            if not self.settings()["enabled"].get("live", True):
                continue
            now = time.time()
            for f in self.store.query("SELECT id, every_s, last FROM feeds WHERE enabled = 1"):
                last = 0
                if f["last"]:
                    try:
                        last = datetime.datetime.strptime(f["last"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc).timestamp()
                    except ValueError:
                        pass
                if now - last >= f["every_s"]:
                    try:
                        self.poll(f["id"])
                    except Exception as e:
                        self.log("live feed %s: %r" % (f["id"], e))

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="agent-feeds", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()

    # ---- from the Device gateway: tactile sensors, accelerometers, heart rate, gaze
    def from_devices(self, kind, since=None):
        dv = self.devices
        if dv is None:
            raise core.UserError("The Device gateway is not available.")
        if kind == "touch":
            obs = dv.observations(kind="touch", since=since, limit=5000)
            force = [float(o["value"]) for o in reversed(obs) if o.get("value") not in (None, "")]
            return {"force": force, "rate_hz": 10, "count": len(force)}
        if kind == "motion":
            mv = dv.minutes(kind="movement", since=since, limit=5000)
            hr = dv.minutes(kind="heart_bpm", since=since, limit=5000)
            gz = dv.observations(kind="gaze", since=since, limit=5000)
            return {"acc": [m["mean"] for m in reversed(mv)], "rate_hz": 1 / 60.0, "heart": [m["mean"] for m in reversed(hr)],
                    "fixations_ms": [float(o["value"]) for o in gz if o.get("value") not in (None, "")], "count": len(mv) + len(hr) + len(gz)}
        raise core.UserError("Devices give touch or motion.")


# ============================================================================ routes
def add_routes(api, hub):
    g, p = api.get, api.post
    g("/api/agents/status")(lambda q: hub.status())
    p("/api/agents/pick")(lambda q: hub.pick(q.get("agent"), q.get("enabled"), q.get("passphrase")))
    g("/api/agents/features")(lambda q: {k: {f: list(v) for f, v in d.items()} for k, d in FEATURES.items()})
    @p("/api/agents/analyse")
    def _analyse(q):
        hub._need(q.get("agent"))
        f, d = analyse(q.get("agent"), q.get("input") or {})
        return {"features": f, "detail": d}
    g("/api/agents/skills")(lambda q: {"skills": hub.skills()})
    p("/api/agents/skill_add")(lambda q: hub.add_skill(q.get("name"), q.get("agent"), q.get("description")))
    p("/api/agents/skill_delete")(lambda q: hub.delete_skill(q.get("id")))
    p("/api/agents/skill_attach")(lambda q: hub.attach_playbook(q.get("id"), q.get("playbook_id")))
    g("/api/agents/exemplars")(lambda q: {"exemplars": hub.exemplars(q.get("skill_id"))})
    p("/api/agents/exemplar_add")(lambda q: hub.add_exemplar(q.get("skill_id"), q.get("title"), q.get("input"), q.get("licence"), q.get("performer"),
                                                             q.get("source"), q.get("rating") or 4))
    p("/api/agents/exemplar_delete")(lambda q: hub.delete_exemplar(q.get("id")))
    g("/api/agents/profile")(lambda q: {"profile": hub.profile(q.get("skill_id"), q.get("version"))})
    p("/api/agents/adopt")(lambda q: hub.adopt(q.get("skill_id"), q.get("version"), q.get("passphrase")))
    p("/api/agents/sample")(lambda q: hub.sample(q.get("skill_id"), q.get("input"), q.get("title"), q.get("keep", True)))
    g("/api/agents/samples")(lambda q: {"samples": hub.samples(q.get("skill_id"))})
    g("/api/agents/playbooks")(lambda q: {"playbooks": hub.playbooks(q.get("kind"))})
    g("/api/agents/playbook")(lambda q: hub.playbook(q.get("id")))
    p("/api/agents/playbook_pick")(lambda q: hub.pick_playbook(q.get("id"), q.get("enabled")))
    p("/api/agents/playbook_delete")(lambda q: hub.delete_playbook(q.get("id")))
    p("/api/agents/claw/upload")(lambda q: hub.import_upload(q.get("name"), q.get("data_b64")))
    p("/api/agents/claw/search")(lambda q: hub.claw_search(q.get("q"), q.get("limit") or 30, q.get("safe", True)))
    p("/api/agents/claw/sync_index")(lambda q: hub.claw_sync_index(int(q.get("max_pages") or 500), q.get("safe", True)))
    g("/api/agents/claw/index")(lambda q: hub.claw_index(q.get("q"), int(q.get("limit") or 100), int(q.get("offset") or 0)))
    p("/api/agents/claw/import")(lambda q: hub.claw_import(q.get("slug"), q.get("version")))
    p("/api/agents/claw/local")(lambda q: hub.claw_local(q.get("home"), bool(q.get("include_personal")), q.get("passphrase"), bool(q.get("preview"))))
    g("/api/agents/feeds")(lambda q: {"feeds": hub.feeds()})
    p("/api/agents/feed_add")(lambda q: hub.add_feed(q.get("name"), q.get("url"), q.get("path"), q.get("every_s") or 300))
    p("/api/agents/feed_poll")(lambda q: hub.poll(q.get("id")))
    p("/api/agents/feed_delete")(lambda q: hub.delete_feed(q.get("id")))
    p("/api/agents/from_devices")(lambda q: hub.from_devices(q.get("kind"), q.get("since")))
    g("/api/agents/purity")(lambda q: hub.purity())


def attach(app, app_id):
    """Give an application the Agent hub. Never stops the application if it cannot be opened."""
    try:
        app.agents = Hub(app.folder, app_id, app.log)
        app.agents.approvals = getattr(getattr(app, "commons", None), "approvals", None)
        app.agents.devices = getattr(app, "devices", None)
        add_routes(app.api, app.agents)
    except Exception as e:
        app.log("agent hub unavailable:", repr(e))
        app.agents = None
    return app.agents


def start(app):
    hub = getattr(app, "agents", None)
    if hub:
        hub.start()
