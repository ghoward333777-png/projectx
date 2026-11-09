"""Language Lab — the application learns English, then the other languages, by itself.

Same logic and order as the last prototype before the full build (v9.50, qb_language.py + the
"lang_pipeline" agent); the learning functions themselves are in lab_core.py, copied unchanged.

  Phase 1  Sub-language (structure): letters, rule-seeded phonics (sounds), syllables, rhythm,
           word stability, co-occurrence, pattern saturation — from raw text, meaning suppressed.
           The one-way TRANSITION GATE opens when all four thresholds are met:
           sounds ≥ 0.80 of 44 · top-word stability ≥ 0.70 · word-pair density ≥ 1.5 · new-pattern rate < 0.20
  Phase 2  Meaning — only after the gate opens: each learned word is grounded to its definition in
           Webster's Unabridged Dictionary (1913, public domain). No AI model (locked out).
  Phase 3  Other languages as a delta: the learned English words get their translations from the
           bundled bilingual dictionary.
  Phase 4  Speech: pronunciation (sounds), syllable count and stress for the learned words.
  Then     each other language is learned the way English was: its starter text (pangrams, numbers,
           weekdays) and dictionary words, with pronunciation.

What changed from the prototype: storage only. The model lives in the application's database
(transactional, checked, backed up) instead of language_model.json, and learned items are rows
in lab_facts instead of the old shared store. "Self-grounding" against other facts is not done
here, because facts now live in the separate History & News application.
"""
import json, time

import lab_core as C
import speech
import vocab

SCHEMA = """
CREATE TABLE lab_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE lab_facts (subject TEXT NOT NULL, predicate TEXT NOT NULL, object TEXT NOT NULL, source TEXT NOT NULL,
  trust REAL NOT NULL, added TEXT NOT NULL, PRIMARY KEY (subject, predicate, object)) WITHOUT ROWID;
CREATE INDEX lab_facts_pred ON lab_facts(predicate)
"""

SRC_LAB = "QueryBook Language Lab (SLPL, deterministic)"
SRC_DICT = "Webster's Unabridged Dictionary (1913, public domain)"
SRC_BILING = "MUSE bilingual dictionary (CC BY-NC 4.0, demonstration data)"
SRC_G2P = "QueryBook rule-seeded G2P / prosody (approximate)"
MAX_PHASE1_CYCLES = 600            # safety stop; the bundled starter text opens the gate in ~36 cycles


class GateClosed(Exception):
    pass


def now():
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%02dZ" % int((t % 1) * 100)


class Lab:
    def __init__(self, store, log=lambda *a: None):
        self.store = store
        self.log = log

    # ------------------------------------------------------------------ model storage (replaces language_model.json)
    def load_model(self):
        raw = self.store.scalar("SELECT value FROM lab_state WHERE key = 'model_en'")
        if raw:
            m = json.loads(raw)
            if isinstance(m, dict) and "words" in m:
                base = C._blank_model()
                base.update(m)
                return base
        return C._blank_model()

    def _save_model(self, db, m):
        db.execute("INSERT OR REPLACE INTO lab_state(key, value) VALUES('model_en', ?)", (json.dumps(m, separators=(",", ":")),))

    def _put(self, db, subj, pred, obj, trust, src):
        cur = db.execute("INSERT OR IGNORE INTO lab_facts(subject, predicate, object, source, trust, added) VALUES(?,?,?,?,?,?)",
                         (str(subj), str(pred), str(obj)[:300], src, trust, now()))
        return cur.rowcount

    def gate_open(self):
        return bool(self.load_model().get("gate_opened"))

    # ------------------------------------------------------------------ Phase 1 (same as prototype learn())
    def learn(self, text, source="pasted text"):
        text = (text or "").strip()
        if not text:
            raise ValueError("no text to learn from")
        m = self.load_model()
        C._ingest_into_model(m, text, persist_source=source)
        mx = C.metrics(m)
        if mx["gate"]["ready"] and not m.get("gate_opened"):              # one-way gate latches OPEN
            m["gate_opened"] = True
            m["gate_opened_at"] = now()
            mx = C.metrics(m)
        g = mx["gate"]["checks"]
        m.setdefault("history", []).append({
            "t": now(), "tokens": m["total_tokens"], "words": len(m["words"]),
            "phon": g["phonemic_completeness"]["value"], "stab": g["lexical_stability"]["value"],
            "dens": g["cooccurrence_density"]["value"], "novel": g["pattern_saturation"]["value"],
            "ready": mx["gate"]["ready"], "opened": m.get("gate_opened", False)})
        m["history"] = m["history"][-200:]
        m["prev_top"] = [k for k, _ in sorted(m["words"].items(), key=lambda kv: -kv[1])[:40]]
        with self.store.write() as db:
            self._save_model(db, m)
            added = self._store_structure(db, mx)
        mx["history"] = m["history"]
        mx["chars_ingested"] = len(text)
        mx["facts_written"] = added
        mx["source"] = source
        return mx

    def _store_structure(self, db, mx):
        """The prototype's _store_facts: aggregate metrics, letter frequencies, observed sounds."""
        added = 0
        g = mx["gate"]
        for pred, val in (("phoneme_inventory_completeness", g["checks"]["phonemic_completeness"]["value"]),
                          ("lexical_stability", g["checks"]["lexical_stability"]["value"]),
                          ("cooccurrence_density", g["checks"]["cooccurrence_density"]["value"]),
                          ("pattern_saturation_novelty", g["checks"]["pattern_saturation"]["value"]),
                          ("distinct_words_learned", mx["distinct_words"]), ("distinct_phonemes_observed", mx["distinct_phonemes"]),
                          ("avg_syllables_per_word", mx["avg_syllables_per_word"]), ("mean_sentence_length", mx["mean_sentence_len"])):
            db.execute("DELETE FROM lab_facts WHERE subject = 'english' AND predicate = ?", (pred,))      # metrics: latest value
            added += self._put(db, "english", pred, val, 0.85, SRC_LAB)
        if g["opened"]:
            added += self._put(db, "english", "transition_gate", "OPEN", 0.85, SRC_LAB)
        tot = sum(c for _, c in mx["top_letters"]) or 1
        for ch, c in mx["top_letters"]:
            db.execute("DELETE FROM lab_facts WHERE subject = ? AND predicate = 'grapheme_frequency'", ("english letter %s" % ch,))
            added += self._put(db, "english letter %s" % ch, "grapheme_frequency", round(c / tot, 4), 0.85, SRC_LAB)
        for ph, c in mx["top_phonemes"]:
            added += self._put(db, "english phoneme %s" % ph, "phoneme_rule_seeded", "observed", 0.70, SRC_LAB)
        return added

    def status(self):
        m = self.load_model()
        mx = C.metrics(m)
        mx["thresholds"] = C.GATE
        mx["history"] = m.get("history", [])
        return mx

    def learned_words(self, n=400):
        m = self.load_model()
        return [w for w, _ in sorted(m["words"].items(), key=lambda kv: -kv[1])[:n]]

    def _require_gate(self):
        if not self.gate_open():
            raise GateClosed("Sub-language comes first: Phase 1 must open the Transition Gate before meaning, "
                             "translation or speech can be learned.")

    # ------------------------------------------------------------------ Phase 2 (ground_words: dictionary)
    def ground_words(self, words):
        self._require_gate()
        D = vocab.definitions()
        grounded, added = [], 0
        with self.store.write() as db:
            for w in words:
                wl = str(w).lower().strip()
                if not wl or not wl.isalpha() or len(wl) < 2:
                    continue
                defn = (D.get(wl) or "").strip()
                if defn:
                    added += self._put(db, 'english word "%s"' % wl, "means", defn, 0.9, SRC_DICT)
                    grounded.append({"word": wl, "definition": defn})
        return {"words_in": len(words), "words_grounded": len(grounded), "facts_added": added, "dict_entries": len(D), "grounded": grounded}

    # ------------------------------------------------------------------ Phase 3 (acquire_language: dictionary delta)
    def acquire_language(self, lang, words):
        self._require_gate()
        added, mapped = 0, []
        with self.store.write() as db:
            for w in words:
                wl = str(w).lower().strip()
                tw = vocab.word(lang, wl)
                if not tw:
                    continue
                for tr in tw["tr"][:2]:
                    added += self._put(db, 'english word "%s"' % wl, "translation_" + lang, tr, 0.85, SRC_BILING)
                mapped.append({"word": wl, "translations": tw["tr"][:2]})
        return {"lang": lang, "language": vocab.LANGUAGES[lang]["name"], "words_in": len(words), "mapped": len(mapped),
                "facts_added": added, "sample": mapped[:8]}

    # ------------------------------------------------------------------ Phase 4 (speech_analyze) and pronunciation
    def prefetch_ipa(self, words, lang):
        """Fill the pronunciation cache for many words at once (one espeak-ng call per 400 words)."""
        if lang == "en" or lang not in vocab.LANGUAGES or not speech.find_espeak():
            return
        cache = self.__dict__.setdefault("_ipa", {})
        todo = [w for w in words if (lang, w) not in cache]
        for w, r in zip(todo, speech.ipa_many(todo, vocab.LANGUAGES[lang]["espeak"])):
            cache[(lang, w)] = r

    def analyze_pronunciation(self, word, lang="en"):
        """English: the prototype's rule-seeded G2P. Other languages: espeak-ng when installed, else the bundled rules."""
        if lang == "en":
            phon = C._g2p(word)
            stress, syl = C._stress_pattern(word)
            return {"word": word.lower(), "lang": "en", "ipa": "/" + "".join(phon) + "/", "syllables": syl,
                    "stress_syllable": stress, "source": SRC_G2P}
        cache = self.__dict__.setdefault("_ipa", {})
        if (lang, word.lower()) in cache:
            ipa = cache[(lang, word.lower())]
        else:
            ipa = speech.ipa(word, vocab.LANGUAGES[lang]["espeak"]) if lang in vocab.LANGUAGES and speech.find_espeak() else None
        if ipa:
            ipa = ipa.strip()
            nuclei = [i for i, ch in enumerate(ipa) if ch in C._IPA_VOWELS]
            syl = max(1, len(nuclei))
            mark = ipa.find("ˈ")
            stress = min(max(1, 1 + sum(1 for n in nuclei if n < mark)), syl) if mark >= 0 and nuclei else 1
            return {"word": word.lower(), "lang": lang, "ipa": "/" + ipa + "/", "syllables": syl, "stress_syllable": stress,
                    "source": "espeak-ng %s" % lang}
        r = C._g2p_rules(word, lang)
        if r:
            ipa, stress, syl = r
            return {"word": word.lower(), "lang": lang, "ipa": "/" + ipa + "/", "syllables": syl, "stress_syllable": stress,
                    "source": "rule-seeded G2P (%s)" % lang}
        return {"word": word.lower(), "lang": lang, "ipa": None, "syllables": 1, "stress_syllable": 1, "source": "no phonemizer"}

    def speech_analyze(self, words, lang="en"):
        self._require_gate()
        added, sample = 0, []
        with self.store.write() as db:
            for w in words:
                wl = str(w).lower().strip()
                if not wl or not wl.isalpha() or len(wl) < 2:
                    continue
                a = self.analyze_pronunciation(wl, lang)
                if a["ipa"] is None:
                    continue                                # never fabricated
                label = ('english word "%s"' % wl) if lang == "en" else ('%s word "%s"' % (vocab.LANGUAGES[lang]["name"].lower(), wl))
                added += self._put(db, label, "pronunciation", a["ipa"], 0.70, a["source"])
                self._put(db, label, "syllable_count", a["syllables"], 0.70, a["source"])
                self._put(db, label, "stress_syllable", a["stress_syllable"], 0.70, a["source"])
                if len(sample) < 8:
                    sample.append(a)
        return {"words_in": len(words), "analyzed": added, "lang": lang, "sample": sample}

    # ------------------------------------------------------------------ learn another language (learn_language)
    def corpus_words(self, lang):
        """The prototype's _corpus_words: starter-text words first, then the dictionary's words, in a fixed order."""
        import re
        text = " ".join(C.STARTER_CORPUS_L10N.get(lang, [])).lower()
        seen, order = set(), []
        for tok in re.findall(r"[^\W\d_]+", text, re.UNICODE):
            if tok not in seen:
                seen.add(tok)
                order.append(tok)
        inv = self._foreign_map(lang)
        for w in sorted(inv):
            if w not in seen:
                seen.add(w)
                order.append(w)
        return order

    def _foreign_map(self, lang):
        inv = {}
        for w in vocab.deck(lang):
            for f in w["tr"]:
                fl = f.lower().strip()
                if fl and " " not in fl and fl.isalpha():
                    inv.setdefault(fl, set()).add(w["en"])
        return {k: sorted(v) for k, v in inv.items()}

    def learn_language(self, lang, words):
        self._require_gate()
        tmap = self._foreign_map(lang)
        name = vocab.LANGUAGES[lang]["name"]
        self.prefetch_ipa([str(w).lower().strip() for w in words], lang)
        vocab_added = pron_added = trans_added = 0
        with self.store.write() as db:
            for w in words:
                wl = str(w).lower().strip()
                if not wl or not wl.isalpha():
                    continue
                label = '%s word "%s"' % (name.lower(), wl)
                senses = tmap.get(wl)
                attest = "bundled bilingual dictionary" if senses else "bundled starter corpus"
                vocab_added += self._put(db, label, "attested_in", attest, 0.8, SRC_BILING if senses else "Bundled public-domain starter corpus (%s)" % name)
                for en in (senses or [])[:3]:
                    trans_added += self._put(db, label, "means", en, 0.70, SRC_BILING)
                a = self.analyze_pronunciation(wl, lang)
                if a["ipa"]:
                    pron_added += self._put(db, label, "pronunciation", a["ipa"], 0.70, a["source"])
                    self._put(db, label, "syllable_count", a["syllables"], 0.70, a["source"])
                    self._put(db, label, "stress_syllable", a["stress_syllable"], 0.70, a["source"])
        return {"lang": lang, "language": name, "vocab_added": vocab_added, "pron_added": pron_added, "trans_added": trans_added}

    # ------------------------------------------------------------------ progress
    def phase_status(self):
        q = self.store.scalar
        words = self.learned_words(400)
        defined = q("SELECT count(*) FROM lab_facts WHERE predicate = 'means' AND subject LIKE 'english word %'", default=0)
        langs = []
        for code in vocab.OTHERS:
            name = vocab.LANGUAGES[code]["name"]
            langs.append({"code": code, "name": name,
                          "translations": q("SELECT count(*) FROM lab_facts WHERE predicate = ?", ("translation_" + code,), 0),
                          "vocabulary": q("SELECT count(*) FROM lab_facts WHERE predicate = 'attested_in' AND subject LIKE ?", (name.lower() + ' word %',), 0),
                          "pronounced": q("SELECT count(*) FROM lab_facts WHERE predicate = 'pronunciation' AND subject LIKE ?", (name.lower() + ' word %',), 0),
                          "corpus": len(self.corpus_words(code))})
        return {"gate_open": self.gate_open(), "vocabulary": len(words), "defined": defined,
                "pronounced_en": q("SELECT count(*) FROM lab_facts WHERE predicate = 'pronunciation' AND subject LIKE 'english word %'", default=0),
                "facts": q("SELECT count(*) FROM lab_facts", default=0), "languages": langs, "phases": C.LANGUAGE_PHASES}

    def word_card(self, word):
        """Everything the lab has learned about one word (any language), with sources."""
        w = str(word or "").lower().strip()
        rows = self.store.query("SELECT subject, predicate, object, source, trust FROM lab_facts WHERE subject LIKE ? ORDER BY subject, predicate",
                                ('% word "' + w + '"',))
        m = self.load_model()
        return {"word": w, "seen_in_phase1": m["words"].get(w, 0), "facts": rows,
                "pronunciation_now": self.analyze_pronunciation(w, "en") if w.isalpha() else None}

    def recent_facts(self, n=40):
        return self.store.query("SELECT subject, predicate, object, source FROM lab_facts WHERE subject LIKE '% word %' ORDER BY added DESC, subject LIMIT ?", (n,))

    # ------------------------------------------------------------------ the one-button run (the prototype's lang_pipeline agent)
    def build_stages(self):
        """The whole build, in order: English phases 1-4, then each other language."""
        st = [("en1", "English — sub-language (Phase 1, up to the Transition Gate)"), ("en2", "English — meanings (Phase 2)"),
              ("en3", "English — links to the other %d languages (Phase 3)" % len(vocab.OTHERS)), ("en4", "English — pronunciation (Phase 4)")]
        return st + [("lang_" + c, vocab.LANGUAGES[c]["name"]) for c in vocab.OTHERS]

    def _save_stage_log(self, log, started=None):
        rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in log]
        with self.store.write() as db:
            db.execute("INSERT OR REPLACE INTO lab_state(key, value) VALUES('stage_log', ?)", (json.dumps(rows),))
            if started:
                db.execute("INSERT OR REPLACE INTO lab_state(key, value) VALUES('build_started', ?)", (started,))

    def stage_log(self):
        try:
            return json.loads(self.store.scalar("SELECT value FROM lab_state WHERE key = 'stage_log'", default="[]"))
        except ValueError:
            return []

    def built_at(self):
        return self.store.scalar("SELECT value FROM lab_state WHERE key = 'built_at'", default=None)

    def run_pipeline(self, progress, stop, extra_text=None, weights=None):
        report = {}
        stages = self.build_stages()
        N = len(stages)
        # How much of the whole build each step is: its time in the previous build (equal shares when unknown),
        # so "% done" and "time left" track real time instead of step counts.
        prev = weights or {r["key"]: r.get("seconds") for r in self.stage_log() if r.get("seconds")}
        w = [max(0.2, float(prev.get(k) or 0)) if len(prev) >= N // 2 else 1.0 for k, _ in stages]
        before = [sum(w[:i]) for i in range(N)]
        W = sum(w)

        log = []                                   # one row per step: when it started and finished, how long, what it did
        self._save_stage_log(log, now())

        def step(no, done, total, msg):
            frac = (done / total) if total else 0
            if not log or log[-1]["no"] != no:
                t = time.time()
                if log:
                    log[-1].update(finished=now(), seconds=round(t - log[-1]["_t"], 2), state="done")
                log.append({"no": no, "key": stages[no - 1][0], "name": stages[no - 1][1], "started": now(), "_t": t, "state": "running", "detail": ""})
                self._save_stage_log(log)
            log[-1]["detail"] = msg
            progress(done, total, msg, overall=round((before[no - 1] + w[no - 1] * min(1.0, frac)) / W, 4), stage_no=no, stages=N, stage=stages[no - 1][1])
        # Phase 1 — cycle through the starter text (plus anything fed to it) until the gate opens
        cycles = 0
        if extra_text:
            self.learn(extra_text, "your text")
        step(1, int(self.status()["gate"]["progress"]), 100, "reading for structure")
        while not self.gate_open() and not stop():
            if cycles >= MAX_PHASE1_CYCLES:
                report["phase1"] = "stopped after %d cycles without opening the gate — feed more English text" % cycles
                return report
            idx = int(self.store.scalar("SELECT value FROM lab_state WHERE key = 'chunk'", default=0))
            mx = self.learn(C.corpus_chunk(idx), "Phase 1 · starter corpus #%d" % (idx % len(C.STARTER_CORPUS)))
            with self.store.write() as db:
                db.execute("INSERT OR REPLACE INTO lab_state(key, value) VALUES('chunk', ?)", (str(idx + 1),))
            cycles += 1
            step(1, int(mx["gate"]["progress"]), 100, "reading %d — %.0f%% of the way to the Transition Gate" % (cycles, mx["gate"]["progress"]))
        if stop():
            return report
        report["phase1"] = "Transition Gate open (%d readings this run)" % cycles
        words = self.learned_words(400)
        # Phase 2 — meaning, 40 words at a time
        for i in range(0, len(words), 40):
            if stop():
                return report
            self.ground_words(words[i:i + 40])
            step(2, min(i + 40, len(words)), len(words), "%d of %d words looked up" % (min(i + 40, len(words)), len(words)))
        report["phase2"] = "%d words defined" % self.store.scalar("SELECT count(*) FROM lab_facts WHERE predicate = 'means' AND subject LIKE 'english word %'", default=0)
        # Phase 3 — translations of the learned English words into every other language
        for k, code in enumerate(vocab.OTHERS):
            if stop():
                return report
            self.acquire_language(code, words)
            step(3, k + 1, len(vocab.OTHERS), "%s linked" % vocab.LANGUAGES[code]["name"])
        report["phase3"] = "%d languages linked" % len(vocab.OTHERS)
        # Phase 4 — speech analysis of the learned English words
        for i in range(0, len(words), 40):
            if stop():
                return report
            self.speech_analyze(words[i:i + 40], "en")
            step(4, min(i + 40, len(words)), len(words), "%d of %d words" % (min(i + 40, len(words)), len(words)))
        report["phase4"] = "pronunciation for %d English words" % len(words)
        # Then each other language, learned the way English was
        learned = {l["code"]: l["vocabulary"] for l in self.phase_status()["languages"]}
        for k, code in enumerate(vocab.OTHERS):
            allw = self.corpus_words(code)
            done = 0
            if allw and learned.get(code, 0) >= len(allw):         # already finished in an earlier run: keep it
                step(5 + k, len(allw), len(allw), "already built — %d words kept" % len(allw))
                report["learn_" + code] = "%d words (kept)" % len(allw)
                continue
            for i in range(0, len(allw), 400):
                if stop():
                    return report
                self.learn_language(code, allw[i:i + 400])
                done = min(i + 400, len(allw))
                step(5 + k, done, len(allw), "%d of %d words" % (done, len(allw)))
            report["learn_" + code] = "%d words" % done
        if log:
            log[-1].update(finished=now(), seconds=round(time.time() - log[-1]["_t"], 2), state="done")
        self._save_stage_log(log)
        with self.store.write() as db:
            db.execute("INSERT OR REPLACE INTO lab_state(key, value) VALUES('built_at', ?)", (now(),))
        report["result"] = "All %d languages built." % (len(vocab.OTHERS) + 1)
        return report

    def adopt_old_model(self, model, name):
        """Continue from an old prototype's English model (same format) when the lab has not learned anything yet."""
        if not isinstance(model, dict) or not isinstance(model.get("words"), dict):
            return {"adopted": False, "reason": "%s is not a language model" % name}
        if self.load_model()["total_tokens"] > 0:
            return {"adopted": False, "reason": "the lab has already learned on its own; the old model was not merged into it"}
        m = C._blank_model()
        for k in m:
            if k in model and type(model[k]) is type(m[k]):
                m[k] = model[k]
        with self.store.write() as db:
            self._save_model(db, m)
        mx = C.metrics(m)
        return {"adopted": True, "tokens": m["total_tokens"], "words": len(m["words"]), "gate_open": bool(m.get("gate_opened")),
                "gate_progress": mx["gate"]["progress"]}

    def forget(self):
        with self.store.write() as db:
            db.execute("DELETE FROM lab_state")
            db.execute("DELETE FROM lab_facts")
