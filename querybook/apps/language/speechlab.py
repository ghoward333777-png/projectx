"""Speech Lab — speech in (ingestion, queries) and speech out (generation), welded to the Language Builder.

Every process is recorded in the `speech_log` table with UTC timestamps to the hundredth of a
second, its total time and the time of every stage (to 0.01 s), what it was asked to do, what
it used, what it produced and where the audio is kept. Nothing about API keys is ever recorded.

    ingest(audio, transcript)   measure a recording: volume, pauses, rate, pitch / tone /
                                intonation, jitter, shimmer, HNR, tremor, breathiness, vocal
                                mode (whisper / crying / laughing / shouting / singing / speech),
                                emotion, voice age and condition indicators — and, when words
                                are given, their semantics and pronunciation from what the
                                builder has learned (meaning, translations, IPA, stress, accent cues)
    generate(text, profile)     speak with any engine; uncompressed audio back; the controls the
                                engine lacks are added by post-processing; the result is measured
    match(text, target)         generate → measure → adjust → repeat until the measured output
                                meets the target (pitch, speed, loudness, pauses, tremble, breath)
    query(transcript, audio)    understand a spoken question (words + how it was said) and answer
                                it out loud from the builder's knowledge
"""
import datetime, hashlib, json, math, os, re, shutil, time

import dialect
import function_words
import gcloud
import speech
import tts
import visemes
import vocab
import voicedsp

SCHEMA = """
CREATE TABLE IF NOT EXISTS speech_log (
  id INTEGER PRIMARY KEY,
  started TEXT NOT NULL,            -- UTC, to 0.01 s
  ended TEXT,
  seconds REAL,                     -- total, to 0.01 s
  process TEXT NOT NULL,            -- ingest / generate / match / query / custom-voice …
  description TEXT,
  engine TEXT,
  status TEXT NOT NULL,
  stages TEXT,                      -- JSON [{stage, at_s, seconds}] to 0.01 s
  request TEXT,                     -- JSON, keys removed
  result TEXT,                      -- JSON summary
  audio TEXT,                       -- file name in speech/
  parent INTEGER                    -- a match iteration points to its match
);
CREATE INDEX IF NOT EXISTS speech_log_started ON speech_log(started);
"""


FAILOVER = ["espeak", "sapi", "say", "formant"]       # offline voices, in order; the formant voice needs nothing installed


def stamp(t=None):
    d = datetime.datetime.fromtimestamp(t if t is not None else time.time(), datetime.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%02dZ" % (d.microsecond // 10000)


class Clock:
    """Times a process and each of its stages to the hundredth of a second."""

    def __init__(self):
        self.t0 = time.time()
        self.stages = []
        self._cur = None

    def __call__(self, name):
        now = time.time()
        if self._cur:
            self._cur["seconds"] = round(now - self._cur["_t"], 2)
        self._cur = {"stage": name, "at_s": round(now - self.t0, 2), "_t": now}
        self.stages.append(self._cur)

    def done(self):
        now = time.time()
        if self._cur and "seconds" not in self._cur:
            self._cur["seconds"] = round(now - self._cur["_t"], 2)
        return [{k: v for k, v in s.items() if not k.startswith("_")} for s in self.stages], round(now - self.t0, 2)


class SpeechLab:
    def __init__(self, store, lab, log, folder):
        self.store, self.lab, self.log = store, lab, log
        self.keys = tts.Keys(folder)
        self.audio_dir = os.path.join(folder, "speech")
        os.makedirs(self.audio_dir, exist_ok=True)
        tts.Formant.lab = lab
        tts.BY_ID["formant"].lab = lab
        self.google = gcloud.Google(gcloud.Settings(folder), log)

    # ---------------------------------------------------------------- Google Speech-to-Text (optional recognizer)
    def stt_ready(self):
        pub = self.google.s.public()
        return pub["api_key_set"] and pub["stt_on"] is not False

    def transcribe(self, audio, lang="en", parent=None):
        """Google Speech-to-Text with word timings; logged as its own process. Returns None when not available or failed."""
        if not self.stt_ready():
            return None
        clk = Clock()
        clk("Google Speech-to-Text")
        code = tts.SPEECH_LANG.get(lang, lang if "-" in str(lang) else "en-US")
        try:
            r = self.google.recognize(audio, code)
            self._record("transcribe", "Google Speech-to-Text: %d words, confidence %s" % (len(r["words"]), r["confidence"]), "google_stt", "ok", clk,
                         {"language": code}, {"transcript": r["transcript"][:500], "confidence": r["confidence"], "words": len(r["words"])}, None, parent)
            return r
        except Exception as e:
            self._record("transcribe", "Google Speech-to-Text failed: %s" % self.google.s.scrub(e), "google_stt", "failed", clk, {"language": code}, None, None, parent)
            return {"error": self.google.s.scrub(e)}

    # ---------------------------------------------------------------- logging
    def _record(self, process, description, engine, status, clock, request=None, result=None, audio=None, parent=None, started=None):
        stages, secs = clock.done()
        row = (stamp(started or clock.t0), stamp(), secs, process, description[:500], engine or "", status,
               json.dumps(stages), json.dumps(request, ensure_ascii=False)[:20000] if request is not None else None,
               json.dumps(result, ensure_ascii=False)[:20000] if result is not None else None, audio, parent)
        if self.store.read_only:
            return None
        with self.store.write() as db:
            cur = db.execute("INSERT INTO speech_log(started, ended, seconds, process, description, engine, status, stages, request, result, audio, parent) "
                             "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", row)
            rid = cur.lastrowid
        self.store.activity("Speech: " + process, status, "%s (%.2f s)" % (description[:160], secs), int(secs * 1000))
        return rid

    def history(self, limit=100, process=None):
        q = "SELECT * FROM speech_log" + (" WHERE process = ?" if process else "") + " ORDER BY id DESC LIMIT ?"
        rows = self.store.query(q, ((process, limit) if process else (limit,)))
        for r in rows:
            for k in ("stages", "request", "result"):
                try:
                    r[k] = json.loads(r[k]) if r[k] else None
                except ValueError:
                    pass
        return rows

    def stats(self):
        return self.store.query("SELECT process, engine, count(*) AS runs, round(avg(seconds), 2) AS mean_s, round(min(seconds), 2) AS min_s, "
                                "round(max(seconds), 2) AS max_s, round(sum(seconds), 2) AS total_s, "
                                "sum(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) AS ok FROM speech_log GROUP BY process, engine ORDER BY runs DESC")

    def _save_audio(self, data, kind):
        h = hashlib.sha256(data).hexdigest()[:16]
        day = time.strftime("%Y%m%d", time.gmtime())
        name = "%s/%s-%s.wav" % (day, kind, h)
        path = os.path.join(self.audio_dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(data)
        return name

    def audio_path(self, name):
        p = os.path.normpath(os.path.join(self.audio_dir, name))
        if not p.startswith(os.path.normpath(self.audio_dir) + os.sep) or not os.path.isfile(p):
            raise FileNotFoundError(name)
        return p

    # ---------------------------------------------------------------- semantics of words
    def semantics(self, text, lang_hint=None, accent=""):
        """What the builder knows about each word: language, meaning, translations, IPA, stress; plus accent cues."""
        words = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)?", text or "", re.UNICODE)[:60]
        out, langs = [], {}
        defs = vocab.definitions()
        seen = self.lab.load_model()["words"] if self.lab else {}
        rank = vocab.rank()

        def langs_of(lw):
            """Every language this word belongs to, from what the builder has learned."""
            out = set(function_words.INDEX.get(lw, ()))
            if lw in seen or lw in rank or lw in defs or vocab.word("es", lw):
                out.add("en")
            for l in vocab.OTHERS:
                if vocab.reverse_index(l).get(vocab.fold(lw)):
                    out.add(l)
            return out
        cand = [langs_of(w.lower()) for w in words]
        votes = {}
        for w, c in zip(words, cand):
            fw = function_words.INDEX.get(w.lower(), ())
            for l in c:
                # a closed-class word is strong evidence; an ambiguous content word counts a little for each language
                votes[l] = votes.get(l, 0) + (2.0 / len(fw) if l in fw else 1.0 / len(c))
        sentence_lang = lang_hint or (max(votes, key=lambda l: (votes[l], l == "en")) if votes else "en")
        for w, c in zip(words, cand):
            lw = w.lower()
            info = {"word": w, "lang": None, "meaning": None, "translations": {}, "known_to_builder": False}
            dominant = sum(1 for cc in cand if sentence_lang in cc) >= 0.6 * max(1, sum(1 for cc in cand if cc))
            lang = sentence_lang if (sentence_lang in c or not c or dominant) else sorted(c, key=lambda l: -votes.get(l, 0))[0]
            info["lang"] = lang
            if lang == "en":
                info["meaning"] = (defs.get(lw) or "")[:240] or None
                info["translations"] = {l: vocab.forms(l, lw)[:2] for l in ("es", "fr", "de") if vocab.forms(l, lw)}
            else:
                hits = vocab.reverse_index(lang).get(vocab.fold(lw))
                if hits:
                    info["meaning"] = "English: " + ", ".join(hits[:4])
            info["lang"] = info["lang"] or lang_hint or "en"
            langs[info["lang"]] = langs.get(info["lang"], 0) + 1
            info["known_to_builder"] = bool(seen.get(lw)) or bool(info["meaning"]) or lang in function_words.INDEX.get(lw, ())
            if not info["meaning"] and lang in function_words.INDEX.get(lw, ()):
                info["meaning"] = "function word (grammar)"
            pr = self.lab.analyze_pronunciation(lw, info["lang"]) if self.lab else {}
            info["ipa"], info["syllables"], info["stress_syllable"] = pr.get("ipa"), pr.get("syllables"), pr.get("stress_syllable")
            info["ipa_source"] = pr.get("source")
            if info["lang"] == "en" and speech.find_espeak():
                # the builder's English phonics rules are approximate; espeak-ng's dictionary is shown when installed
                e = speech.ipa(lw, "en-us")
                if e:
                    info["ipa_rules"], info["ipa"], info["ipa_source"] = info["ipa"], "/" + e.strip() + "/", "espeak-ng (rules: %s)" % info["ipa"]
            if accent and pr.get("ipa"):
                info["ipa_in_accent"], info["accent_rules"] = dialect.apply_phonology(pr["ipa"], accent)
            out.append(info)
        main = max(langs, key=langs.get) if langs else (lang_hint or "en")
        return {"words": out, "language": main, "language_name": vocab.LANGUAGES.get(main, {}).get("name", main),
                "syllables_expected": sum(w.get("syllables") or 0 for w in out),
                "accent_cues": dialect.detect_dialect(text or "", None)[:3] if text else []}

    # ---------------------------------------------------------------- ingestion
    def ingest(self, audio, transcript="", expected="", label="", recognizer="auto", lang="en"):
        clk = Clock()
        clk("receive")
        if not voicedsp.is_wav(audio):
            raise ValueError("Please send WAV audio (the page records WAV).")
        name = self._save_audio(audio, "in")
        try:
            stt, heard_by = None, ("browser / typed" if transcript else "none")
            if recognizer == "google" or (recognizer == "auto" and not transcript):
                clk("transcribe (Google Speech-to-Text)")
                stt = self.transcribe(audio, lang)
                if stt and stt.get("transcript"):
                    transcript, heard_by = stt["transcript"], "Google Speech-to-Text"
                elif stt and stt.get("error"):
                    heard_by = ("browser / typed" if transcript else "none") + " (Google Speech-to-Text failed: %s)" % stt["error"][:120]
            m = voicedsp.measure(audio, clk)
            clk("semantics")
            sem = self.semantics(transcript or expected) if (transcript or expected) else None
            if sem and m["rate"]["syllables"]:
                sem["syllables_heard"] = m["rate"]["syllables"]
            if expected and transcript:
                sem["match_to_expected"] = vocab.similarity(transcript, expected)
            if sem and stt and stt.get("words"):
                # attach Google's timing and confidence to each word, in order
                pool = [dict(w) for w in stt["words"]]
                for w in sem["words"]:
                    for k, g in enumerate(pool):
                        if vocab.fold(g["word"].strip(".,!?;:").lower()) == vocab.fold(w["word"].lower()):
                            w.update({"start_s": g["start_s"], "end_s": g["end_s"], "stt_confidence": g["confidence"]})
                            pool = pool[k + 1:]
                            break
            res = {"measure": _slim(m), "semantics": sem, "transcript": transcript, "expected": expected, "heard_by": heard_by,
                   "stt": {k: stt[k] for k in ("confidence", "language", "seconds") if k in stt} if stt and not stt.get("error") else None}
            rid = self._record("ingest", "%s%.2f s of audio — %s, %s" % ((label + ": ") if label else "", m["duration_s"], m["vocal_mode"]["label"],
                               m["indicators"]["emotion"]["label"]), "voicedsp", "ok", clk, {"transcript": transcript, "expected": expected, "label": label},
                               {"vocal_mode": m["vocal_mode"]["label"], "emotion": m["indicators"]["emotion"]["label"]}, name)
            res.update({"log_id": rid, "audio": name, "contour": m["contour"], "segments": m["segments"]})
            return res
        except Exception as e:
            self._record("ingest", "failed: %s" % e, "voicedsp", "failed", clk, None, None, name)
            raise

    # ---------------------------------------------------------------- generation
    def generate(self, text, prof, engine="espeak", voice="", model="", adv=None, measure=True, fallback=True, parent=None, quiet_label="", extra_fx=None):
        text = " ".join(str(text or "").split())[:2000]
        if not text:
            raise ValueError("Type something to say.")
        if engine not in tts.BY_ID:
            raise ValueError("Unknown voice engine.")
        clk = Clock()
        clk("plan")
        pl, run, fx = tts.plan(text, prof, engine, voice, model, self.keys, adv)
        # redundancy: the chosen engine first, then every offline voice in turn, ending with the pure-Python voice
        chain = [engine] + ([e for e in FAILOVER if e != engine] if fallback else [])
        if engine == "google_gemini":
            # the same 30 Google AI voices are offered by Cloud Text-to-Speech as "Chirp 3 HD" voices: use those first
            chain.insert(1, "google_cloud")
        attempts, data, used, err, fx_used = [], None, None, None, fx
        for eid in chain:
            ok, why = tts.BY_ID[eid].available(self.keys)
            if not ok:
                attempts.append({"engine": eid, "result": "skipped", "reason": why})
                continue
            t_try = time.time()
            clk("synthesize (%s)" % eid)
            try:
                if eid == engine:
                    data, fx_used = run(), fx
                else:
                    alt_voice = ""
                    if engine == "google_gemini" and eid == "google_cloud":
                        alt_voice = "%s-Chirp3-HD-%s" % (tts.locale(tts.profile(prof)), voice or "Kore")
                    pl2, run2, fx_used = tts.plan(text, prof, eid, alt_voice, "", self.keys, None)
                    data = run2()
                    pl.setdefault("fallback", {"engine": eid, "voice": alt_voice, "request": pl2["request"]})
                if not voicedsp.is_wav(data):
                    raise RuntimeError("the engine returned audio that is not WAV")
                attempts.append({"engine": eid, "result": "ok", "seconds": round(time.time() - t_try, 2)})
                used = eid
                break
            except Exception as e:
                reason = tts.scrub(e, self.keys)
                attempts.append({"engine": eid, "result": "failed", "reason": reason, "seconds": round(time.time() - t_try, 2)})
                data = None
        fx = fx_used
        if used != engine:
            err = next((a.get("reason") for a in attempts if a["engine"] == engine), None) or "not available"
        pl["attempts"] = attempts
        if not used:
            self._record("generate", "every voice failed: %s" % "; ".join("%s: %s" % (a["engine"], a.get("reason", "")) for a in attempts),
                         engine, "failed", clk, {"plan": pl["request"], "attempts": attempts}, None, None, parent)
            raise RuntimeError("No voice could speak: " + "; ".join("%s — %s" % (a["engine"], a.get("reason", a["result"])) for a in attempts))
        if used != engine and not fallback:
            raise RuntimeError(err)
        if not voicedsp.is_wav(data):
            raise RuntimeError("the engine returned audio that is not WAV")
        if extra_fx:                                        # corrections from the match loop
            fx = dict(fx)
            fx["pitch_st"] = fx.get("pitch_st", 0.0) + extra_fx.get("pitch_st", 0.0)
            fx["tempo"] = fx.get("tempo", 1.0) * extra_fx.get("tempo", 1.0)
        data, fxrep = voicedsp.apply_effects(data, fx, clk)
        meas = None
        if measure:
            meas = voicedsp.measure(data, lambda s: clk("measure: " + s))
        clk("save")
        name = self._save_audio(data, "out")
        summary = {"engine_used": used, "fallback_reason": err, "effects": fxrep.get("applied"), "bytes": len(data), "attempts": attempts}
        p_ = tts.profile(prof)
        if meas and not p_["whisper"] and meas["vocal"]["voiced_ratio"] < 0.25 and meas["duration_s"] > 0.5:
            summary["warning"] = ("The result does not sound like speech (only %.0f%% voiced). If you hear noise, run Diagnostics."
                                  % (100 * meas["vocal"]["voiced_ratio"]))
        if meas:
            summary.update({"duration_s": meas["duration_s"], "pitch_hz": meas["pitch"].get("mean_hz"), "rate_syl_s": meas["rate"]["articulation_rate_syl_s"],
                            "volume_dbfs": meas["volume"]["mean_dbfs"], "vocal_mode": meas["vocal_mode"]["label"]})
        rid = self._record("generate", (quiet_label or "") + "“%s” — %s" % (text[:80], tts.BY_ID[used].name), used, "ok" if not err else "fallback",
                           clk, {"plan": pl["request"], "profile": pl["profile"], "advanced": pl["advanced"], "post_processing": fx, "text": text}, summary, name, parent)
        return {"log_id": rid, "audio": name, "plan": pl, "effects": fxrep, "measure": _slim(meas) if meas else None,
                "summary": summary, "stages": self.store.query("SELECT stages, seconds FROM speech_log WHERE id = ?", (rid,))[0] if rid else None}

    # ---------------------------------------------------------------- lip-sync: timed mouth shapes for a spoken clip
    def lipsync(self, audio_name, text, lang="en", exact=False):
        """Viseme track for a clip this app produced or received. exact=True asks Google Speech-to-Text for word
        times first (needs the API key); otherwise the words are fitted to the measured speech."""
        clk = Clock()
        clk("read audio")
        with open(self.audio_path(audio_name), "rb") as f:
            wav = f.read()
        wt = None
        if exact and self.stt_ready():
            clk("word times (Google Speech-to-Text)")
            r = self.transcribe(wav, lang)
            if r and r.get("words"):
                wt = r["words"]
        clk("align mouth shapes")
        tr = visemes.align(text, wav, lang, self.lab, wt)
        self._record("lipsync", "%d mouth shapes for “%s” (%s)" % (len(tr["visemes"]), (text or "")[:60], tr["method"][:60]), "visemes", "ok", clk,
                     {"audio": audio_name, "lang": lang, "exact": bool(wt)}, {"visemes": len(tr["visemes"]), "duration": tr["duration"]}, audio_name)
        tr["audio"] = audio_name
        return tr

    # ---------------------------------------------------------------- overdub: new words in the timing of the old ones
    def overdub(self, original_wav, text, prof=None, engine="espeak", voice="", model="", adv=None, consent=False, lang=None):
        """Speak `text` with the chosen voice and fit it into the speaking time of `original_wav` (the soundtrack
        of a video): phrase by phrase when both have the same number of phrases, otherwise as one block.
        Stretching keeps the pitch (WSOLA). The result is labelled synthetic."""
        if not consent:
            raise ValueError("Overdubbing replaces a person's voice. Tick the box to confirm you are that person or have their permission, "
                             "and that the result will be labelled as altered.")
        if not voicedsp.is_wav(original_wav):
            raise ValueError("The original soundtrack must be WAV audio.")
        clk = Clock()
        clk("measure the original")
        orig_name = self._save_audio(original_wav, "orig")
        mo = voicedsp.measure(original_wav)
        o_spans = visemes._speech_spans(mo)
        clk("speak the new words")
        g = self.generate(text, prof or {}, engine, voice, model, adv, measure=False, parent=None, quiet_label="overdub: ")
        with open(self.audio_path(g["audio"]), "rb") as f:
            new_wav = f.read()
        x, sr = voicedsp.read_wav(new_wav)
        mn = voicedsp.measure(new_wav)
        n_spans = visemes._speech_spans(mn)
        clk("fit phrase by phrase")

        def phrases(spans, gap=0.25):
            out = [list(spans[0])]
            for a, b in spans[1:]:
                if a - out[-1][1] >= gap:
                    out.append([a, b])
                else:
                    out[-1][1] = b
            return out
        po, pn = phrases(o_spans), phrases(n_spans)
        if len(po) != len(pn):
            po, pn, mode = [[po[0][0], po[-1][1]]], [[pn[0][0], pn[-1][1]]], "one block (%d phrases in the original, %d in the new words)" % (len(po), len(pn))
        else:
            mode = "phrase by phrase (%d phrases)" % len(po)
        total = max(mo["duration_s"], po[-1][1])
        y = [0.0] * int(total * sr + sr * 0.05)
        fits, warnings = [], []
        for (oa, ob), (na, nb) in zip(po, pn):
            seg = x[int(na * sr):int(nb * sr)]
            want = max(0.05, ob - oa)
            k = want / max(0.05, nb - na)
            kk = max(0.6, min(1.6, k))
            if kk != k:
                warnings.append("The phrase at %.2f s needed %.2f× time; limited to %.2f× so it stays natural — reword it %s." %
                                (oa, k, kk, "longer" if k > 1 else "shorter"))
            elif k < 0.8 or k > 1.25:
                warnings.append("The phrase at %.2f s was stretched %.2f× (noticeable). Rewording it to fit will sound better." % (oa, k))
            st = voicedsp.wsola(seg, sr, kk)
            p0 = int(oa * sr)
            for i, v in enumerate(st):
                if p0 + i < len(y):
                    y[p0 + i] += v
            fits.append({"original_from_s": round(oa, 2), "original_to_s": round(ob, 2), "new_seconds": round(nb - na, 2), "stretch": round(kk, 3)})
        peak = max((abs(v) for v in y), default=0.0)
        if peak > 0.99:
            y = [v * 0.99 / peak for v in y]
        data = voicedsp.write_wav(y, sr)
        clk("save")
        name = self._save_audio(data, "dub")
        clk("mouth shapes for the new words")
        track = visemes.align(text, data, lang or (prof or {}).get("lang") or "en", self.lab)
        res = {"audio": name, "original_audio": orig_name, "voice_audio": g["audio"], "engine_used": g["summary"]["engine_used"],
               "mode": mode, "phrases": fits, "warnings": warnings, "duration_s": round(len(y) / sr, 2), "track": track,
               "label": "SYNTHETIC VOICE — overdubbed with QueryBook"}
        rid = self._record("overdub", "“%s” fitted %s over %.2f s" % (text[:60], mode, total), g["summary"]["engine_used"], "ok", clk,
                           {"text": text, "engine": engine, "voice": voice, "consent": True, "original": orig_name},
                           {k: res[k] for k in ("mode", "phrases", "warnings", "duration_s")}, name)
        res["log_id"] = rid
        res["stages"] = self.store.query("SELECT stages, seconds FROM speech_log WHERE id = ?", (rid,))[0] if rid else None
        return res

    def video_analysis(self, p):
        """Log and return lipread.analyse() for frames sent by the browser tracker."""
        import lipread
        clk = Clock()
        clk("analyse %d frames" % len(p.get("frames") or []))
        r = lipread.analyse(p.get("frames") or [], p.get("info") or {}, p.get("env") or None, int(p.get("env_fps") or 100),
                            p.get("script") or "", p.get("lang") or "en", [w for w in re.split(r"[\s,;]+", p.get("words") or "") if w],
                            self.lab, p.get("read_lips", True) not in (False, "false"))
        bits = ["capture quality %d/100" % r["quality"]["score"]]
        if r.get("sync"):
            bits.append("sync: " + r["sync"].get("verdict", r["sync"].get("reason", "")))
        if r.get("script"):
            bits.append("script agreement %d%%" % r["script"]["agreement"])
        if r.get("lipread"):
            bits.append("read: “%s”" % r["lipread"]["text"][:60])
        rid = self._record("video", "; ".join(bits), (p.get("info") or {}).get("source", "camera"), "ok" if not r.get("error") else "failed", clk,
                           {"info": p.get("info"), "frames": len(p.get("frames") or []), "script": p.get("script") or ""},
                           {k: r.get(k) for k in ("quality", "sync", "script")})
        r["log_id"] = rid
        r["stages"] = self.store.query("SELECT stages, seconds FROM speech_log WHERE id = ?", (rid,))[0] if rid else None
        return r

    # ---------------------------------------------------------------- match a target specification
    TARGET_KEYS = {"pitch_hz": "mean pitch (Hz)", "rate_syl_s": "articulation rate (syllables/s)", "volume_dbfs": "loudness (dBFS)",
                   "pause_ratio": "share of time in pauses", "tremble": "tremble level (0–100)", "breathiness": "breathiness (0–1)"}

    def _measured(self, m):
        return {"pitch_hz": m["pitch"].get("mean_hz"), "rate_syl_s": m["rate"]["articulation_rate_syl_s"], "volume_dbfs": m["volume"]["mean_dbfs"],
                "pause_ratio": m["pauses"]["pause_ratio"], "tremble": (m["quality"]["tremor_pitch"].get("depth_pct") or 0) * 40,
                "breathiness": m["quality"]["breathiness"]}

    def match(self, text, target, prof, engine="espeak", voice="", model="", adv=None, max_rounds=5, progress=None, stop=None):
        """Generate, measure, adjust, repeat — until every target is within tolerance or the rounds run out."""
        tol = {"pitch_hz": 0.05, "rate_syl_s": 0.10, "volume_dbfs": 1.5, "pause_ratio": 0.05, "tremble": 10, "breathiness": 0.1}
        tgt = {k: float(v) for k, v in (target or {}).items() if k in self.TARGET_KEYS and v not in (None, "")}
        if not tgt:
            raise ValueError("Set at least one target.")
        clk = Clock()
        clk("match")
        parent = self._record("match", "matching %s with %s" % (", ".join("%s=%s" % kv for kv in tgt.items()), engine), engine, "running", Clock(), {"target": tgt})
        p = tts.profile(prof)
        corr = {"pitch_st": 0.0, "tempo": 1.0}          # applied after the engine when its own setting is only descriptive
        exact_pitch, exact_rate = engine in tts.PRECISE_PITCH, engine in tts.PRECISE_RATE
        rounds = []
        best = None
        for k in range(int(max_rounds)):
            if stop and stop():
                break
            if progress:
                progress(k, max_rounds, "round %d of %d" % (k + 1, max_rounds))
            g = self.generate(text, p, engine, voice, model, adv, True, False, parent, "match round %d: " % (k + 1), dict(corr))
            got = self._measured(g["measure"])
            err, okk = {}, True
            for key, want in tgt.items():
                have = got.get(key)
                if have is None:
                    err[key] = None; okk = False; continue
                d = have - want
                lim = tol[key] * (abs(want) if key in ("pitch_hz", "rate_syl_s") else 1)
                err[key] = round(d, 2)
                okk = okk and abs(d) <= lim
            score = sum(abs(v) / (tol[k2] * (abs(tgt[k2]) if k2 in ("pitch_hz", "rate_syl_s") else 1)) for k2, v in err.items() if v is not None)
            rounds.append({"round": k + 1, "profile": {x: p[x] for x in ("pitch_st", "rate", "volume_db", "pause_scale", "tremble", "breath")},
                           "post_correction": dict(corr),
                           "measured": got, "error": err, "within_tolerance": okk, "audio": g["audio"], "log_id": g["log_id"],
                           "seconds": g["stages"]["seconds"] if g.get("stages") else None})
            if best is None or score < best[0]:
                best = (score, k)
            if okk:
                break
            # adjust (damped) toward the target
            if got.get("pitch_hz") and "pitch_hz" in tgt:
                step = 0.85 * 12 * math.log2(tgt["pitch_hz"] / got["pitch_hz"])
                if exact_pitch:
                    p["pitch_st"] = max(-12, min(12, p["pitch_st"] + step))
                else:
                    corr["pitch_st"] = max(-12, min(12, corr["pitch_st"] + step))
            if got.get("rate_syl_s") and "rate_syl_s" in tgt:
                f = (tgt["rate_syl_s"] / got["rate_syl_s"]) ** 0.85
                if exact_rate:
                    p["rate"] = max(0.3, min(3.0, p["rate"] * f))
                else:
                    corr["tempo"] = max(0.4, min(2.5, corr["tempo"] * f))
            if got.get("volume_dbfs") is not None and "volume_dbfs" in tgt:
                p["volume_db"] = max(-30, min(12, p["volume_db"] + 0.9 * (tgt["volume_dbfs"] - got["volume_dbfs"])))
            if "pause_ratio" in tgt and got.get("pause_ratio") is not None:
                have = max(0.02, got["pause_ratio"])
                p["pause_scale"] = max(0.25, min(4.0, p["pause_scale"] * (max(0.02, tgt["pause_ratio"]) / have) ** 0.7))
            if "tremble" in tgt:
                p["tremble"] = max(0.0, min(1.0, p["tremble"] + 0.006 * (tgt["tremble"] - got["tremble"])))
            if "breathiness" in tgt and got.get("breathiness") is not None:
                p["breath"] = max(0.0, min(1.0, p["breath"] + 0.8 * (tgt["breathiness"] - got["breathiness"])))
        b = rounds[best[1]] if best else None
        res = {"target": tgt, "tolerance": tol, "rounds": rounds, "best_round": b["round"] if b else None,
               "post_correction": b["post_correction"] if b else None,
               "matched": bool(b and b["within_tolerance"]), "final_profile": b["profile"] if b else None, "audio": b["audio"] if b else None}
        stages, secs = clk.done()
        with self.store.write() as db:
            db.execute("UPDATE speech_log SET ended = ?, seconds = ?, status = ?, stages = ?, result = ?, audio = ? WHERE id = ?",
                       (stamp(), secs, "ok" if res["matched"] else "closest", json.dumps([{"stage": "round %d" % r["round"], "seconds": r["seconds"]} for r in rounds]),
                        json.dumps({"matched": res["matched"], "best_round": res["best_round"], "rounds": len(rounds)}), res["audio"], parent))
        self.store.activity("Speech: match", "ok" if res["matched"] else "closest", "%d round(s), %s" % (len(rounds), "matched" if res["matched"] else "closest kept"), int(secs * 1000))
        res["log_id"] = parent
        return res

    # ---------------------------------------------------------------- spoken queries
    def query(self, transcript, audio=None, prof=None, engine="espeak", voice="", model="", adv=None, respond_to_mood=True):
        clk = Clock()
        clk("understand words")
        text = " ".join(str(transcript or "").split())
        if not text and audio:
            clk("transcribe (Google Speech-to-Text)")
            r = self.transcribe(audio, (prof or {}).get("lang") or "en")
            text = (r or {}).get("transcript") or ""
        if not text:
            raise ValueError("No words were heard. Speak again or type the question.")
        sem = self.semantics(text)
        how = None
        if audio:
            clk("how it was said")
            m = voicedsp.measure(audio)
            how = {"vocal_mode": m["vocal_mode"]["label"], "confidence": m["vocal_mode"].get("confidence"),
                   "emotion": m["indicators"]["emotion"]["label"], "volume": m["indicators"]["volume"]["label"], "tone": m["indicators"]["tone"]["label"]}
        clk("answer")
        answer = self._answer(text, sem)
        p = tts.profile(prof)
        if respond_to_mood and how:
            if how["vocal_mode"] == "whispering":
                p["whisper"], p["volume_db"] = True, min(p["volume_db"], -6.0)
            elif how["vocal_mode"] == "crying" or how["emotion"].startswith("sad"):
                p["emotion"], p["intensity"], p["rate"] = "tender", 0.7, min(p["rate"], 0.9)
            elif how["vocal_mode"] == "shouting" or how["emotion"].startswith("angry"):
                p["emotion"], p["intensity"] = "calm", 0.8
        clk("speak the answer")
        g = self.generate(answer, p, engine, voice, model, adv, measure=False, quiet_label="answer: ")
        rid = self._record("query", "“%s” → “%s”" % (text[:80], answer[:80]), g["summary"]["engine_used"], "ok", clk,
                           {"transcript": text, "respond_to_mood": respond_to_mood}, {"answer": answer, "how_said": how}, g["audio"])
        return {"log_id": rid, "answer": answer, "semantics": sem, "how_said": how, "voice_used": {k: p[k] for k in ("emotion", "whisper", "rate", "volume_db")},
                "audio": g["audio"]}

    def _answer(self, text, sem):
        """Deterministic answers from the builder's knowledge (no AI)."""
        t = text.lower().strip(" ?!.")
        names = {v["name"].lower(): k for k, v in vocab.LANGUAGES.items()}
        m = re.search(r"how (?:do you|do i|to) say (.+?) in (\w+)", t)
        if m and m.group(2) in names:
            w, l = m.group(1).strip(" '\""), names[m.group(2)]
            f = vocab.forms(l, w)
            return ("In %s, “%s” is %s." % (m.group(2).capitalize(), w, " or ".join(f[:2]))) if f else "I have not learned “%s” in %s yet." % (w, m.group(2).capitalize())
        m = re.search(r"(?:what does|what is the meaning of|define|meaning of) (.+?)(?: mean)?$", t)
        if m:
            w = m.group(1).strip(" '\"").split()[-1]
            r = vocab.lookup(w)
            if r["english"] and r["english"].get("definition"):
                return "“%s”: %s" % (w, r["english"]["definition"].split(";")[0][:220])
            if r["foreign"]:
                f = r["foreign"][0]
                return "“%s” is %s for %s." % (w, f["language"], ", ".join(f["english"][:3]))
            return "I have not learned the word “%s” yet." % w
        m = re.search(r"translate (.+?)(?: into| to) (\w+)", t)
        if m and m.group(2) in names:
            l = names[m.group(2)]
            out = []
            for w in m.group(1).split():
                f = vocab.forms(l, w)
                out.append(f[0] if f else "[%s]" % w)
            return "In %s: %s." % (m.group(2).capitalize(), " ".join(out))
        known = sum(1 for w in sem["words"] if w["known_to_builder"])
        return "I heard %d words in %s; I know %d of them. Ask me what a word means, or how to say a word in another language." % (
            len(sem["words"]), sem["language_name"], known)


def _slim(m):
    """The measurement without the long per-frame contour (kept separately for charts)."""
    if not m:
        return m
    return {k: v for k, v in m.items() if k not in ("contour", "segments")}


def diagnostics(sl, C):
    """Speech checks for the Diagnostics page: every voice path, the measurement chain, audio I/O, keys, providers, log."""
    out = []
    t = time.time()
    st = speech.status()
    if st["espeak"]:
        w = speech.speak_wav("This is a diagnostic test of the default voice.", "en-us")
        ok = bool(w) and voicedsp.is_wav(w) and len(w) > 2000
        heard = voicedsp.measure(w) if ok else None
        clear = bool(heard) and heard["vocal_mode"]["label"] == "speaking" and heard["vocal"]["voiced_ratio"] > 0.5
        out.append(C("sp_default", "Default voice speaks clearly (espeak-ng, %s)" % ("bundled" if st["bundled"] else "system"), "ok" if clear else "fail",
                     ("%.2f s; listened back: %s, %.0f%% voiced, %s Hz" % (time.time() - t, heard["vocal_mode"]["label"], 100 * heard["vocal"]["voiced_ratio"], heard["pitch"].get("mean_hz")))
                     if heard else "no audio came back"))
        t = time.time()
        bad = [c for c, v in vocab.LANGUAGES.items() if not speech.ipa("test", v["espeak"])]
        out.append(C("sp_langs", "Default voice: all 17 languages", "fail" if bad else "ok",
                     ("no voice for: " + ", ".join(bad)) if bad else "17 of 17 in %.2f s" % (time.time() - t)))
    else:
        out.append(C("sp_default", "Default voice speaks (espeak-ng)", "warn", st["hint"]))
    t = time.time()
    try:
        fw = voicedsp.formant_wav(["/tɛst/"])
        out.append(C("sp_failover", "Last-resort voice (built-in, no install)", "ok" if voicedsp.is_wav(fw) else "fail", "%.2f s" % (time.time() - t)))
    except Exception as e:
        out.append(C("sp_failover", "Last-resort voice (built-in, no install)", "fail", repr(e)[:200]))
    t = time.time()
    try:
        m = voicedsp.measure(voicedsp.tone_wav(f0=150, seconds=1.5))
        tr = voicedsp.measure(voicedsp.apply_effects(voicedsp.tone_wav(f0=150, seconds=2.5), {"tremble": 0.8})[0])
        okm = abs((m["pitch"].get("mean_hz") or 0) - 150) < 2
        out.append(C("sp_measure", "Speech measurement (known 150 Hz test voice)", "ok" if okm else "fail",
                     "measured %s Hz; effects → tremble %s; %.2f s" % (m["pitch"].get("mean_hz"), "found" if tr["quality"]["tremor_pitch"].get("detected") else "NOT found", time.time() - t)))
    except Exception as e:
        out.append(C("sp_measure", "Speech measurement", "fail", repr(e)[:200]))
    t = time.time()
    try:
        probe = os.path.join(sl.audio_dir, ".io-probe.wav")
        data = voicedsp.tone_wav(seconds=0.2)
        with open(probe, "wb") as f:
            f.write(data)
        with open(probe, "rb") as f:
            back = f.read()
        os.remove(probe)
        free = shutil.disk_usage(sl.audio_dir).free
        n = sum(len(fs) for _, _, fs in os.walk(sl.audio_dir))
        out.append(C("sp_audio", "Speech audio folder (write, read back, compare)", "ok" if back == data else "fail",
                     "%d files kept; %.1f GB free; %.2f s" % (n, free / 2**30, time.time() - t)))
    except Exception as e:
        out.append(C("sp_audio", "Speech audio folder", "fail", repr(e)[:200]))
    kp = sl.keys.path
    if os.path.exists(kp) and os.name != "nt":
        mode = os.stat(kp).st_mode & 0o077
        out.append(C("sp_keys", "Provider keys file is private", "ok" if not mode else "warn", "owner-only" if not mode else "readable by others — run: chmod 600 speech_keys.json"))
    pub = sl.keys.public()
    for prov in tts.KEY_FIELDS:
        name = tts.BY_ID[prov].name
        if not pub[prov]["configured"]:
            out.append(C("sp_" + prov, name, "ok", "not set up (optional)"))
            continue
        last = sl.store.query("SELECT status, started, description FROM speech_log WHERE engine = ? AND process IN ('generate', 'query') ORDER BY id DESC LIMIT 1", (prov,))
        fails = sl.store.scalar("SELECT count(*) FROM speech_log WHERE engine = ? AND status = 'failed' AND started > ?", (prov, stamp(time.time() - 86400)), 0)
        if not last:
            out.append(C("sp_" + prov, name, "ok", "key set; not used yet — press Test on Voice providers"))
        else:
            out.append(C("sp_" + prov, name, "warn" if last[0]["status"] == "failed" else "ok",
                         "last use %s: %s; failures in 24 h: %d" % (last[0]["started"], last[0]["status"], fails)))
    if sl.stt_ready():
        last = sl.store.query("SELECT status, started FROM speech_log WHERE process = 'transcribe' ORDER BY id DESC LIMIT 1")
        out.append(C("sp_stt", "Google Speech-to-Text", "warn" if last and last[0]["status"] == "failed" else "ok",
                     ("last use %s: %s" % (last[0]["started"], last[0]["status"])) if last else "key set; not used yet"))
    else:
        out.append(C("sp_stt", "Google Speech-to-Text", "ok", "not set up (optional) — the browser's recognizer is used"))
    n = sl.store.scalar("SELECT count(*) FROM speech_log", default=0)
    lastlog = sl.store.scalar("SELECT max(started) FROM speech_log", default=None)
    out.append(C("sp_log", "Speech log", "ok", "%d processes logged; newest %s" % (n, lastlog or "—")))
    return out
