"""The ingestion reservoir for lip-reading and lip-sync, and the learner that improves both from it.

Every spoken input that comes with a camera and known words — a teaching session, an ingested video with
its script, a confident spoken query — deposits its face frames (numbers only, never the picture) into the
reservoir of the ingestion domain ("speech-visual"). The words and the audio give each frame its true mouth
shape, so the reservoir is labelled training data that grows with use.

Learning is deterministic and proven: about one recording in four is held back for testing (chosen by its
content hash, so it never changes). A learned version is switched on only when it beats the current rules on
those held-back recordings; every version is kept with its scores and can be rolled back. What is learned:
  * the mouth-shape reader (a Gaussian naive Bayes classifier over lip gap and mouth blendshapes),
  * which mouth shapes this camera and this speaker confuse (the look-alike costs used to match words),
  * this computer's own camera/microphone delay (so the sync check stops blaming the video for it),
  * the lip-sync timing weights (from recordings with exact Speech-to-Text word times),
  * the talking face's mouth shapes, averaged from real tracked mouths.
"""
import datetime, hashlib, json, math, threading

import lipread
import visemes

DOMAIN = "speech-visual"

SCHEMA = """
CREATE TABLE IF NOT EXISTS ingest_reservoir (
  id INTEGER PRIMARY KEY,
  created TEXT NOT NULL,                   -- UTC, to 0.01 s
  domain TEXT NOT NULL,                    -- ingestion domain: speech-visual
  source TEXT NOT NULL,                    -- teach / ingest / query / video / import
  lang TEXT,
  text TEXT NOT NULL,                      -- the words spoken (the label source)
  word_times TEXT,                         -- JSON [{word, start_s, end_s}] when exactly known (Speech-to-Text)
  audio TEXT,                              -- file in the speech audio folder (absent for imported rows)
  quality INTEGER,                         -- capture quality 0..100
  sync_ms INTEGER, sync_corr REAL,         -- raw lip/sound offset measured on this recording
  frames TEXT NOT NULL,                    -- JSON [[t, features…]] face frames only (numbers, never pictures)
  labels TEXT,                             -- JSON [[class, viseme] | null per frame] at deposit time
  split TEXT NOT NULL,                     -- train / test, fixed by the content hash
  digest TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS lip_models (
  id INTEGER PRIMARY KEY,
  created TEXT NOT NULL,
  examples INTEGER,
  params TEXT,                             -- JSON: classifier, costs, bias_ms, align, mouth
  metrics TEXT,                            -- JSON: held-out scores, rules vs learned
  active INTEGER NOT NULL DEFAULT 0,
  note TEXT
);
"""

# Sentences that show every mouth shape, for teaching sessions (English; any language can type its own).
TEACH = [
    "Bob may move a big map by the pool.",
    "Five fine wives value very fresh fish.",
    "Who would show you the blue moon?",
    "She sells sea shells on the sea shore.",
    "The thin thief thought through the theory.",
    "Each eager eel eats green leaves.",
    "Father calls a large dark car.",
    "Rory rarely rolls round red rocks.",
    "Do not touch the cold kettle today.",
    "Choose a cheap chair and a jar of jam.",
    "Many people met at the warm mountain lake.",
    "Please open your mouth wide and say ah.",
]

VISEME_MOUTH_KEYS = ("open", "width", "round", "teeth", "press")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-4]


def mouth_from_features(fv):
    """Talking-face mouth parameters from one frame's features (same scale as face.js)."""
    gap, jaw, close, press, roll_lo, roll_up, funnel, pucker, stretch, smile, upper_up, lower_down, shrug = fv
    rnd = max(funnel, pucker)
    return {"open": min(1.0, max(gap * 2.2, jaw * 1.1)), "width": max(0.25, min(0.85, 0.55 + 0.4 * max(stretch, smile) - 0.3 * rnd)),
            "round": rnd, "teeth": min(1.0, 0.3 + upper_up + roll_lo), "press": min(1.0, close * 2 + press)}


def _viseme_at(vs, t, edge=0.025):
    """The viseme at audio time t, or None near a boundary or in silence (unreliable labels are skipped)."""
    for v in vs:
        if v["start"] <= t < v["end"]:
            if v["v"] == "sil" or t - v["start"] < edge or v["end"] - t < edge:
                return None
            return v["v"]
    return None


class LipCoach:
    def __init__(self, store, speech):
        self.store, self.speech = store, speech
        self.lock = threading.Lock()
        self.training = False
        self.last = None
        self.apply_active()

    # ---------------------------------------------------------------- settings
    def auto(self):
        return (self.store.meta_get("lipcoach_auto") or "on") == "on"

    def set_auto(self, on):
        if not self.store.read_only:
            self.store.meta_set("lipcoach_auto", "on" if on else "off")
        return self.auto()

    # ---------------------------------------------------------------- deposits
    def _labels(self, rows, text, lang, wav, word_times, bias_ms):
        track = visemes.align(text, wav, lang, self.speech.lab, word_times)
        out = []
        for r in rows:
            v = _viseme_at(track["visemes"], r[0] + bias_ms / 1000.0)
            out.append([lipread.FROM_VISEME[v], v] if v else None)
        return out

    def deposit(self, frames, text, lang="en", source="teach", wav=None, audio_name=None, word_times=None, info=None, sync=None):
        """Add one recording to the reservoir. Returns what it holds and how the current reader did on it."""
        text = " ".join(str(text or "").split())
        face = sorted((f for f in frames or [] if isinstance(f, dict) and f.get("face")), key=lambda f: lipread._f(f.get("t")))
        if not text:
            return {"stored": False, "reason": "no words to learn from"}
        if len(face) < 10:
            return {"stored": False, "reason": "the camera saw a face in only %d frames (10 needed) — face the camera and record again" % len(face)}
        if wav is None and audio_name:
            with open(self.speech.audio_path(audio_name), "rb") as fh:
                wav = fh.read()
        if wav is None:
            return {"stored": False, "reason": "needs the sound to label the frames"}
        # guard the reservoir: the recording must plausibly be this sentence (syllables heard vs syllables written)
        heard = visemes._measured(wav)["rate"]["syllables"]
        want = sum(1 for w in visemes._cached_phonemes(lipread.re.findall(r"[^\W\d_]+", text), lang, self.speech.lab)
                   for _, v, _ in w["phonemes"] if v in visemes._VOWEL_V)
        if want and not (0.45 <= heard / want <= 2.2):
            return {"stored": False, "reason": "the recording does not seem to be this sentence (%d syllables heard, about %d written) — read it again" % (heard, want)}
        if not audio_name:
            audio_name = self.speech._save_audio(wav, "teach")
        rows = [[round(lipread._f(f.get("t")), 3)] + lipread.features(f) for f in face]
        digest = hashlib.sha256((text + "|" + json.dumps(rows)).encode()).hexdigest()
        split = "test" if int(digest[:8], 16) % 4 == 0 else "train"
        bias = int(lipread.ACTIVE.get("bias_ms") or 0)
        labels = self._labels(rows, text, lang, wav, word_times, bias)
        q = lipread.quality(info or {}, frames)["score"]
        if sync is None:
            env = _env(wav)
            cls_gap = lipread.classes_of(face)[1]
            sync = lipread.av_sync(cls_gap, env) if env and cls_gap else {}
        known = [(r, l) for r, l in zip(rows, labels) if l]
        rules = sum(1 for r, l in known if _rules_fv(r[1:]) == l[0]) / len(known) if known else 0.0
        cur = lipread.ACTIVE["model"]
        learned = sum(1 for r, l in known if lipread.predict(cur, r[1:]) == l[0]) / len(known) if (known and cur) else None
        if self.store.read_only:
            return {"stored": False, "reason": "the database is read-only"}
        with self.store.write() as db:
            if db.execute("SELECT 1 FROM ingest_reservoir WHERE digest = ?", (digest,)).fetchone():
                return {"stored": False, "reason": "already in the reservoir"}
            cur_ = db.execute("INSERT INTO ingest_reservoir(created, domain, source, lang, text, word_times, audio, quality, sync_ms, sync_corr, frames, labels, split, digest) "
                              "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (_now(), DOMAIN, source, lang, text, json.dumps(word_times) if word_times else None, audio_name, q,
                               (sync or {}).get("raw_offset_ms"), (sync or {}).get("correlation"), json.dumps(rows), json.dumps(labels), split, digest))
            rid = cur_.lastrowid
        res = {"stored": True, "id": rid, "split": split, "frames": len(rows), "labelled_frames": len(known), "quality": q,
               "rules_accuracy": round(rules, 3), "current_accuracy": round(learned, 3) if learned is not None else None,
               "exact_word_times": bool(word_times), "domain": DOMAIN}
        self.store.activity("Ingestion reservoir: deposit", "ok", "%s · “%s” · %d frames (%d labelled, %s)" % (source, text[:60], len(rows), len(known), split))
        if self.new_since_model() >= 3:
            self.train_async()
        return res

    def new_since_model(self):
        last = self.store.scalar("SELECT max(id) FROM lip_models", default=None)
        upto = (json.loads(self.store.query("SELECT metrics FROM lip_models WHERE id = ?", (last,))[0]["metrics"]) or {}).get("reservoir_max_id", 0) if last else 0
        return self.store.scalar("SELECT count(*) FROM ingest_reservoir WHERE id > ?", (upto,), default=0)

    # ---------------------------------------------------------------- training
    def train_async(self):
        if self.training:
            return False
        threading.Thread(target=self.train, name="lipcoach-train", daemon=True).start()
        return True

    def _examples(self, bias_ms):
        out = []
        for r in self.store.query("SELECT * FROM ingest_reservoir ORDER BY id"):
            rows = json.loads(r["frames"])
            labels = json.loads(r["labels"] or "[]")
            if r["audio"]:
                try:
                    with open(self.speech.audio_path(r["audio"]), "rb") as fh:
                        wav = fh.read()
                    labels = self._labels(rows, r["text"], r["lang"] or "en", wav, json.loads(r["word_times"]) if r["word_times"] else None, bias_ms)
                except (FileNotFoundError, OSError, ValueError):
                    pass
            out.append(dict(r, rows=rows, lab=labels))
        tests = [e for e in out if e["split"] == "test"]
        if not tests and len(out) >= 3:                       # always keep at least one recording back for testing
            e = min(out, key=lambda e: e["digest"])
            e["split"] = "test"
        return out

    def train(self):
        """Learn from the whole reservoir, test on the held-back recordings, keep the result only if it is better."""
        with self.lock:
            self.training = True
            t0 = datetime.datetime.now()
            try:
                return self._train()
            finally:
                self.training = False
                self.last = {"seconds": round((datetime.datetime.now() - t0).total_seconds(), 2)}

    def _train(self):
        n_res = self.store.scalar("SELECT count(*) FROM ingest_reservoir", default=0)
        max_id = self.store.scalar("SELECT max(id) FROM ingest_reservoir", default=0) or 0
        # 1. this computer's camera/microphone delay
        offs = sorted(r["sync_ms"] for r in self.store.query("SELECT sync_ms, sync_corr FROM ingest_reservoir WHERE sync_ms IS NOT NULL")
                      if (r["sync_corr"] or 0) >= 0.4 and abs(r["sync_ms"]) <= 300)
        bias = offs[len(offs) // 2] if len(offs) >= 3 else 0
        ex = self._examples(bias)
        tr = [(r[1:], l[0], l[1]) for e in ex if e["split"] == "train" for r, l in zip(e["rows"], e["lab"]) if l]
        te = [(r[1:], l[0], l[1]) for e in ex if e["split"] == "test" for r, l in zip(e["rows"], e["lab"]) if l]
        metrics = {"reservoir": n_res, "reservoir_max_id": max_id, "train_frames": len(tr), "test_frames": len(te),
                   "train_recordings": sum(1 for e in ex if e["split"] == "train"), "test_recordings": sum(1 for e in ex if e["split"] == "test"),
                   "bias_ms": bias, "bias_from": len(offs)}
        params = {"bias_ms": bias}
        note = []
        if len(tr) < 60 or len(te) < 30:
            note.append("not enough labelled frames yet (%d to learn from, %d to test; need 60 and 30)" % (len(tr), len(te)))
            model = None
        else:
            model = fit(tr)
        # 2. held-out scores: rules vs learned, frame by frame
        classes = sorted({c for _, c, _ in tr + te})
        rule_hits = [(_rules_fv(fv) == c, c) for fv, c, _ in te]
        metrics["rules_accuracy"] = round(sum(h for h, _ in rule_hits) / len(te), 3) if te else None
        metrics["rules_per_class"] = {k: _rate([h for h, c in rule_hits if c == k]) for k in classes}
        if model:
            pred = [(lipread.predict(model, fv), c) for fv, c, _ in te]
            metrics["learned_accuracy"] = round(sum(p == c for p, c in pred) / len(te), 3)
            metrics["learned_per_class"] = {k: _rate([p == c for p, c in pred if c == k]) for k in classes}
            metrics["confusion"] = {a: {b: sum(1 for p, c in pred if c == a and p == b) for b in classes} for a in classes}
            costs = learn_costs(model, tr)
            params.update({"classifier": model, "costs": costs})
            # 3. the end result that matters: how well lips agree with the true words, per held-out recording
            ag_rules, ag_learned = [], []
            for e in ex:
                if e["split"] != "test":
                    continue
                fr = [{"t": r[0], "face": True, "gap": r[1], "_fv": r[1:]} for r in e["rows"]]
                ag_rules.append(lipread.script_agreement(lipread.classes_of(fr, model="rules")[0], e["text"], e["lang"] or "en", self.speech.lab, costs={})["agreement"])
                ag_learned.append(lipread.script_agreement(lipread.classes_of(fr, model=model)[0], e["text"], e["lang"] or "en", self.speech.lab, costs=costs)["agreement"])
            metrics["agreement_rules"] = round(sum(ag_rules) / len(ag_rules), 1) if ag_rules else None
            metrics["agreement_learned"] = round(sum(ag_learned) / len(ag_learned), 1) if ag_learned else None
        # 4. lip-sync timing weights, from recordings with exact word times
        al = [e for e in ex if e["word_times"] and e["audio"]]
        if len(al) >= 2:
            params["align"], metrics["align"] = self._tune_align(al)
        # 5. the talking face's mouth shapes from real mouths
        by_v = {}
        for e in ex:
            for r, l in zip(e["rows"], e["lab"]):
                if l:
                    by_v.setdefault(l[1], []).append(mouth_from_features(r[1:]))
        params["mouth"] = {v: {k: round(sum(m[k] for m in ms) / len(ms), 3) for k in VISEME_MOUTH_KEYS} for v, ms in sorted(by_v.items()) if len(ms) >= 15}
        metrics["mouth_shapes_learned"] = len(params["mouth"])
        # decide
        better = bool(model) and metrics["learned_accuracy"] >= (metrics["rules_accuracy"] or 0) + 0.02 and \
            (metrics.get("agreement_learned") or 0) >= (metrics.get("agreement_rules") or 0) - 2
        metrics["reader_switched_on"] = better
        if model and not better:
            note.append("the learned reader is not yet better than the rules on held-back recordings (%.0f%% vs %.0f%%) — rules kept" %
                        (100 * metrics["learned_accuracy"], 100 * (metrics["rules_accuracy"] or 0)))
        if better:
            note.append("learned reader switched on: %.0f%% vs %.0f%% of held-back frames read right" % (100 * metrics["learned_accuracy"], 100 * metrics["rules_accuracy"]))
        if not better:
            params.pop("classifier", None); params.pop("costs", None)
        if metrics.get("align", {}).get("improved"):
            note.append("lip-sync timing improved: %(before_ms).0f ms → %(after_ms).0f ms average word-edge error" % metrics["align"])
        else:
            params.pop("align", None)
        if bias:
            note.append("this computer's camera/microphone delay: %d ms (from %d recordings)" % (bias, len(offs)))
        if self.store.read_only:
            return {"metrics": metrics, "note": note}
        learned_any = better or "align" in params or bias or len(params.get("mouth") or {}) >= 3
        metrics["switched_on"] = bool(learned_any)
        if not learned_any:
            note.append("nothing better yet — the version in use is unchanged")
        with self.store.write() as db:
            if learned_any:
                db.execute("UPDATE lip_models SET active = 0")
            cur = db.execute("INSERT INTO lip_models(created, examples, params, metrics, active, note) VALUES(?,?,?,?,?,?)",
                             (_now(), n_res, json.dumps(params), json.dumps(metrics), 1 if learned_any else 0, "; ".join(note)))
            mid = cur.lastrowid
        self.apply_active()
        self.store.activity("Ingestion reservoir: learning", "ok", "version %d — %s" % (mid, "; ".join(note)[:300]))
        return {"version": mid, "metrics": metrics, "note": note}

    def _tune_align(self, al):
        """Coordinate search over the timing weights, scored by average word-edge error against exact word times."""
        wavs = {}
        for e in al:
            with open(self.speech.audio_path(e["audio"]), "rb") as fh:
                wavs[e["id"]] = fh.read()

        def err(w, base):
            saved = (dict(visemes.WEIGHT), visemes.WORD_BASE)
            visemes.WEIGHT.update(w); visemes.WORD_BASE = base
            try:
                tot, n = 0.0, 0
                for e in al:
                    exact = json.loads(e["word_times"])
                    est = visemes.align(e["text"], wavs[e["id"]], e["lang"] or "en", self.speech.lab)["words"]
                    for a, b in zip(est, exact):
                        tot += abs(a["start"] - float(b["start_s"])) + abs(a["end"] - float(b["end_s"])); n += 2
                return 1000 * tot / n if n else 0.0
            finally:
                visemes.WEIGHT.clear(); visemes.WEIGHT.update(saved[0]); visemes.WORD_BASE = saved[1]
        w, base = dict(visemes.DEFAULT_WEIGHT), visemes.DEFAULT_WORD_BASE
        before = best = err(w, base)
        for _ in range(2):
            for k in ("vowel", "long", "cons", "base"):
                for f in (0.6, 0.8, 1.25, 1.6):
                    w2, b2 = dict(w), base
                    if k == "base":
                        b2 = round(base * f, 3)
                    else:
                        w2[k] = round(w[k] * f, 3)
                    e_ = err(w2, b2)
                    if e_ < best - 0.5:
                        best, w, base = e_, w2, b2
        return {"weight": w, "word_base": base}, {"before_ms": round(before, 1), "after_ms": round(best, 1), "recordings": len(al),
                                                  "improved": best <= before * 0.95}

    # ---------------------------------------------------------------- using a version
    def apply_active(self):
        rows = self.store.query("SELECT id, params FROM lip_models WHERE active = 1 ORDER BY id DESC LIMIT 1") if self.store else []
        p = json.loads(rows[0]["params"]) if rows else {}
        lipread.ACTIVE.update({"model": p.get("classifier"), "costs": p.get("costs"), "bias_ms": p.get("bias_ms", 0),
                               "version": rows[0]["id"] if rows else None})
        a = p.get("align")
        visemes.WEIGHT.clear(); visemes.WEIGHT.update(a["weight"] if a else visemes.DEFAULT_WEIGHT)
        visemes.WORD_BASE = a["word_base"] if a else visemes.DEFAULT_WORD_BASE
        self.mouth = p.get("mouth") or {}
        return lipread.ACTIVE["version"]

    def use(self, version):
        """Switch to an earlier version, or 'rules' to switch every learned part off."""
        if self.store.read_only:
            raise ValueError("The database is read-only.")
        with self.store.write() as db:
            db.execute("UPDATE lip_models SET active = 0")
            if version != "rules":
                if not db.execute("SELECT 1 FROM lip_models WHERE id = ?", (int(version),)).fetchone():
                    raise ValueError("No such version.")
                db.execute("UPDATE lip_models SET active = 1 WHERE id = ?", (int(version),))
        self.store.activity("Ingestion reservoir: version chosen", "ok", "using %s" % ("the rules only" if version == "rules" else "version %s" % version))
        return self.apply_active()

    # ---------------------------------------------------------------- reporting, sharing
    def status(self):
        q = self.store.query
        models = q("SELECT id, created, examples, metrics, active, note FROM lip_models ORDER BY id")
        for m in models:
            m["metrics"] = json.loads(m["metrics"] or "{}")
        return {"domain": DOMAIN, "auto": self.auto(), "training": self.training, "active_version": lipread.ACTIVE["version"],
                "reservoir": q("SELECT source, split, count(*) AS recordings, sum(json_array_length(frames)) AS frames FROM ingest_reservoir GROUP BY source, split ORDER BY source, split"),
                "total": self.store.scalar("SELECT count(*) FROM ingest_reservoir", default=0),
                "exact_timing": self.store.scalar("SELECT count(*) FROM ingest_reservoir WHERE word_times IS NOT NULL", default=0),
                "recent": q("SELECT id, created, source, text, quality, split, json_array_length(frames) AS frames FROM ingest_reservoir ORDER BY id DESC LIMIT 12"),
                "versions": models, "teach": TEACH, "new_since_last": self.new_since_model(), "mouth": self.mouth,
                "weights": {"weight": dict(visemes.WEIGHT), "word_base": visemes.WORD_BASE}, "bias_ms": lipread.ACTIVE.get("bias_ms", 0)}

    def export(self):
        """The reservoir as portable JSON: features, words and labels (no pictures, no audio)."""
        rows = []
        for r in self.store.query("SELECT created, source, lang, text, word_times, quality, sync_ms, sync_corr, frames, labels, digest FROM ingest_reservoir ORDER BY id"):
            rows.append({k: (json.loads(r[k]) if k in ("frames", "labels", "word_times") and r[k] else r[k]) for k in r})
        return {"format": "querybook-ingest-reservoir", "domain": DOMAIN, "version": 1, "features": lipread.FEATURES, "rows": rows}

    def import_(self, data):
        if not isinstance(data, dict) or data.get("format") != "querybook-ingest-reservoir":
            raise ValueError("This is not an exported ingestion reservoir.")
        if data.get("features") != lipread.FEATURES:
            raise ValueError("The file was made with different frame features.")
        added = 0
        with self.store.write() as db:
            for r in data.get("rows") or []:
                if not r.get("frames") or not r.get("text") or not r.get("labels"):
                    continue
                d = r.get("digest") or hashlib.sha256((r["text"] + "|" + json.dumps(r["frames"])).encode()).hexdigest()
                if db.execute("SELECT 1 FROM ingest_reservoir WHERE digest = ?", (d,)).fetchone():
                    continue
                split = "test" if int(d[:8], 16) % 4 == 0 else "train"
                db.execute("INSERT INTO ingest_reservoir(created, domain, source, lang, text, word_times, audio, quality, sync_ms, sync_corr, frames, labels, split, digest) "
                           "VALUES(?,?,?,?,?,?,NULL,?,?,?,?,?,?,?)",
                           (_now(), DOMAIN, "import:" + str(r.get("source") or "")[:20], r.get("lang"), r["text"],
                            json.dumps(r["word_times"]) if r.get("word_times") else None, r.get("quality"), r.get("sync_ms"), r.get("sync_corr"),
                            json.dumps(r["frames"]), json.dumps(r["labels"]), split, d))
                added += 1
        self.store.activity("Ingestion reservoir: import", "ok", "%d recordings added" % added)
        return {"added": added}


def _rules_fv(fv):
    """The rule reader on a stored feature vector."""
    return lipread.frame_class({"_fv": fv}, "rules")


def _rate(hits):
    return round(sum(hits) / len(hits), 3) if hits else None


def fit(samples):
    """Gaussian naive Bayes on [(features, class, viseme)] — means, variances (with a floor), priors."""
    n, d = len(samples), len(samples[0][0])
    gm = [sum(s[0][j] for s in samples) / n for j in range(d)]
    gv = [sum((s[0][j] - gm[j]) ** 2 for s in samples) / n for j in range(d)]
    out = {}
    for c in sorted({s[1] for s in samples}):
        xs = [s[0] for s in samples if s[1] == c]
        if len(xs) < 8:
            continue
        mean = [sum(x[j] for x in xs) / len(xs) for j in range(d)]
        var = [max(sum((x[j] - mean[j]) ** 2 for x in xs) / len(xs), 0.0004 + 0.05 * gv[j]) for j in range(d)]
        out[c] = {"mean": [round(v, 5) for v in mean], "var": [round(v, 6) for v in var], "log_prior": round(math.log(len(xs) / n), 5), "n": len(xs)}
    return {"kind": "gaussian-naive-bayes", "features": lipread.FEATURES, "classes": out}


def learn_costs(model, samples, prior_weight=20.0):
    """How alike two mouth classes look to this reader: from its confusions, blended with the built-in costs."""
    cls = sorted(model["classes"])
    C = {a: {b: 0 for b in cls} for a in cls}
    for fv, c, _ in samples:
        if c in C:
            C[c][lipread.predict(model, fv)] += 1
    out = {}
    for i, a in enumerate(cls):
        for b in cls[i + 1:]:
            n = C[a][a] + C[b][b] + C[a][b] + C[b][a]
            s = (C[a][b] + C[b][a]) / n if n else 0.0
            data = 1 - min(0.8, 2 * s)
            prior = lipread._NEAR.get(frozenset((a, b)), 1.0)
            out[a + b] = round((n * data + prior_weight * prior) / (n + prior_weight), 3)
    return out


def _env(wav):
    """Loudness at 100 per second, 0..1 (as the page computes it)."""
    import speechlab
    return speechlab._envelope(visemes._measured(wav))
