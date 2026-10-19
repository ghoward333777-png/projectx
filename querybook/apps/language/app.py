#!/usr/bin/env python3
"""QueryBook Language Builder — a dedicated application for learning vocabulary, listening and speaking.

17 languages — English, Spanish, French, German, Italian, Portuguese, Dutch, Swedish, Danish, Norwegian, Finnish, Polish, Czech, Greek, Romanian, Hungarian and Catalan. Choose the language you speak and the one to learn;
English can be learned from any of the others, and any two are linked through English.
New words arrive a few at a time, most common first, and come back for review on a fixed
spaced-repetition schedule (1, 2, 4, 8, 16, 32, 64 days). Practise with flashcards, multiple
choice, typing, listening and speaking. Answers are checked by rule, never by an AI model.

Start:      python app.py            (opens http://127.0.0.1:8101/)
Self-test:  python app.py --selftest
More:       python app.py --help
"""
import datetime, hashlib, json, os, re, sys, tempfile, threading, time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import qbcore as core
import qbcommons as cm
import harvest
import lab
import speech
import speechlab
import lipcoach
import persona
import photoreal
import silent
import lipread
import objscan
import vse
import tts
import visemes
import verify
import vocab

APP_ID = "language"
APP_NAME = "QueryBook Language Builder"
VERSION = "1.18.0"
PORT = 8101
program_dir = HERE

INTERVALS = [0, 1, 2, 4, 8, 16, 32, 64]      # days until the next review for each box
MASTERED_BOX = 6                              # a word reviewed correctly at 16+ days is "mastered"
MODES = ("cards", "choice", "type", "listen", "speak")
SPEAK_PASS = 80                               # similarity needed for a spoken answer to count

SCHEMA = ["""
CREATE TABLE cards (
  lang TEXT NOT NULL, word TEXT NOT NULL, box INTEGER NOT NULL DEFAULT 0, due TEXT NOT NULL,
  reps INTEGER NOT NULL DEFAULT 0, correct INTEGER NOT NULL DEFAULT 0, wrong INTEGER NOT NULL DEFAULT 0, lapses INTEGER NOT NULL DEFAULT 0,
  introduced TEXT NOT NULL, last_review TEXT, PRIMARY KEY (lang, word)
);
CREATE INDEX cards_due ON cards(lang, due);
CREATE TABLE reviews (
  id INTEGER PRIMARY KEY, lang TEXT NOT NULL, word TEXT NOT NULL, mode TEXT NOT NULL, direction TEXT, correct INTEGER NOT NULL,
  result TEXT, given TEXT, at TEXT NOT NULL, day TEXT NOT NULL
);
CREATE INDEX reviews_day ON reviews(lang, day);
CREATE TABLE custom_words (
  id INTEGER PRIMARY KEY, lang TEXT NOT NULL, english TEXT NOT NULL, foreign_word TEXT NOT NULL, note TEXT, created TEXT NOT NULL,
  UNIQUE (lang, english, foreign_word)
);
CREATE TABLE settings (lang TEXT PRIMARY KEY, new_per_day INTEGER NOT NULL DEFAULT 10, direction TEXT NOT NULL DEFAULT 'from_english');
CREATE TABLE old_words (lang TEXT NOT NULL, word TEXT NOT NULL, seen INTEGER NOT NULL, origin TEXT, PRIMARY KEY (lang, word))
""", """
CREATE TABLE custom_pairs (
  id INTEGER PRIMARY KEY, lang TEXT NOT NULL, native TEXT NOT NULL, target_word TEXT NOT NULL, native_word TEXT NOT NULL,
  note TEXT, created TEXT NOT NULL, UNIQUE (lang, native, target_word, native_word)
);
INSERT INTO custom_pairs(lang, native, target_word, native_word, note, created)
  SELECT lang, 'en', foreign_word, english, note, created FROM custom_words
""", lab.SCHEMA, speechlab.SCHEMA, lipcoach.SCHEMA, persona.SCHEMA, photoreal.SCHEMA, objscan.SCHEMA]


def today():
    return datetime.date.today().isoformat()


def _direction(d):
    """Directions are relative to the language you speak (older settings said 'english')."""
    return {"from_native": "from_native", "to_english": "to_native"}.get(d, d)


def add_days(day, n):
    return (datetime.date.fromisoformat(day) + datetime.timedelta(days=n)).isoformat()


class App:
    def __init__(self, folder, clock=today):
        os.makedirs(folder, exist_ok=True)
        self.folder = folder
        self.today = clock
        self.log = core.make_logger(folder, APP_ID)
        self.store = core.Store(folder, APP_ID, SCHEMA, self.log)
        self.jobs = core.Jobs(self.log, self.store)
        self.lab = lab.Lab(self.store, self.log)
        self.CLI_COMMANDS = {"build": self._cli_build, "verify": self._cli_verify, "import-keys": self._cli_import_keys, "vse-bench": self._cli_vse_bench}
        self.speech = speechlab.SpeechLab(self.store, self.lab, self.log, self.store.folder)
        self.coach = self.speech.coach = lipcoach.LipCoach(self.store, self.speech)   # the ingestion reservoir and its learner
        self.personas = persona.Personas(self.store, self.speech, self.store.folder)    # Author Narrator (consent-gated)
        self.prlab = photoreal.Lab(self.store, self.personas, self.lab)                 # Photo Real Lab
        self.scan = self.speech.scan = objscan.Scan(self.store, self.log)                # object scan: what the camera saw
        self.vse = vse.Engine(self.speech, self.lab, self.coach)                          # Visual Speech Engine (lip sync, lip reading)
        self.api = core.Api()
        self.diag = core.Diagnostics(APP_ID, APP_NAME, VERSION, HERE, self.store, self.log, self.jobs, self._health)
        self.monitor = core.Monitor(folder, APP_ID, APP_NAME, VERSION, self.log)
        self.log.hooks.append(self.monitor.on_error)
        core.add_diagnostics(self.api, self.diag, self.monitor, HERE)
        self._routes()
        cm.attach(self, APP_ID, harvest.LanguageAdapter(self))
        try:
            self.store.backup("startup")
        except Exception as e:
            self.log("startup backup failed:", e)
        threading.Thread(target=self._warm, daemon=True).start()

    def _cli_vse_bench(self, args):
        """python app.py vse-bench — measure the Visual Speech Engine against lip-reading v1 and print the report."""
        r = self.vse.benchmark_job()(lambda d, t=None, m="": print("\r  %s/%s %s" % (d, t, m[:60]), end="", flush=True))
        print("\n" + json.dumps(r, indent=2))
        return 0

    # ------------------------------------------------------------------ building the languages (admin, automatic)
    BUILD_JOB = "Build all languages"

    def start_build(self, weights=None):
        return self.jobs.start(self.BUILD_JOB, lambda prog, stop: self.lab.run_pipeline(prog, stop, weights=weights))

    def autostart(self):
        """When the application is served and the languages are not built yet, build them without being asked."""
        if not self.store.read_only and not self.lab.built_at():
            try:
                self.start_build()
                self.store.activity(self.BUILD_JOB, "auto", "started automatically at launch (languages not built yet)")
            except core.UserError:
                pass

    def _cli_build(self, args):
        """python app.py build [--again]: build every language in this window, with progress."""
        if self.lab.built_at() and "--again" not in args:
            print("Languages already built at %s. Use: python app.py build --again" % self.lab.built_at())
            return 0
        t0 = time.time()
        self.store.activity(self.BUILD_JOB, "started", "command line")
        def prog(done, total=None, msg="", **x):
            print("\r  step %s/%s %-52s %3d%%  %s" % (x.get("stage_no", "?"), x.get("stages", "?"), (x.get("stage") or "")[:52],
                                                   int(100 * x.get("overall", 0)), msg[:40]), end="", flush=True)
        r = self.lab.run_pipeline(prog, lambda: False)
        ms = int((time.time() - t0) * 1000)
        self.store.activity(self.BUILD_JOB, "finished", core._summary(r), ms)
        print("\n  %s  (%.1f s)" % (r.get("result", r), ms / 1000))
        return 0

    # ------------------------------------------------------------------ verification from scratch (for third parties)
    VERIFY_JOB = "Verify from scratch"

    def _verify_dir(self):
        d = os.path.join(self.store.folder, "verification")
        os.makedirs(d, exist_ok=True)
        return d

    def _save_verification(self, rep):
        stamp = rep["finished"].replace(":", "").replace("-", "")
        base = os.path.join(self._verify_dir(), "verify-" + stamp)
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1, ensure_ascii=False)
        with open(base + ".txt", "w", encoding="utf-8") as f:
            f.write(verify.text(rep))
        self.store.activity(self.VERIFY_JOB, "ok" if rep["verdict"] == "PASS" else "failed",
                            "%s · fingerprint %s" % (rep["verdict"], rep.get("fingerprint", {}).get("sha256", "")[:16]), int(rep["seconds"] * 1000))
        return base

    def run_verification(self, progress, stop):
        own = self.store if self.lab.built_at() else None
        rep = verify.run(progress, stop, own_store=own, schema=SCHEMA, app_id=APP_ID)
        if rep.get("stopped"):
            return {"result": "stopped"}
        self._save_verification(rep)
        return {"verdict": rep["verdict"], "fingerprint": rep["fingerprint"]["sha256"], "seconds": rep["seconds"]}

    def last_verification(self):
        d = self._verify_dir()
        names = sorted(n for n in os.listdir(d) if n.endswith(".json"))
        if not names:
            return None
        with open(os.path.join(d, names[-1]), encoding="utf-8") as f:
            rep = json.load(f)
        rep["file"] = names[-1]
        rep["all_reports"] = len(names)
        return rep

    def _cli_import_keys(self, args):
        """python app.py import-keys [FOLDER]: copy the old QueryBook's voice keys (never printed)."""
        r = self.speech.keys.import_prototype(args[0] if args else None)
        if r["imported"]:
            print("Imported from %s:\n  %s" % (core.redact(r["found"]), "\n  ".join(r["imported"])))
        else:
            print("No old QueryBook key file (qb_tts_keys.json) found in %d places. Give the old QueryBook folder: python app.py import-keys \"C:\\path\\to\\QueryBook\"" % r["searched"])
        self.store.activity("Speech: import old QueryBook keys", "ok" if r["imported"] else "not found", ", ".join(r["imported"]))
        return 0 if r["imported"] else 1

    def _cli_verify(self, args):
        print("Verifying from scratch: sealed empty store, network blocked, full build, fingerprint…")
        def prog(done, total=None, msg="", **x):
            print("\r  %3d%%  %-70s" % (int(100 * x.get("overall", 0)), (x.get("stage") or "")[:70]), end="", flush=True)
        rep = verify.run(prog, lambda: False, own_store=self.store if self.lab.built_at() else None, schema=SCHEMA, app_id=APP_ID)
        base = self._save_verification(rep)
        print("\n\n" + verify.text(rep))
        print("\nSaved: %s.txt and .json" % base)
        return 0 if rep["verdict"] == "PASS" else 1

    def build_status(self):
        ps = self.lab.phase_status()
        st = self.lab.status()
        stages = self.lab.build_stages()
        done = {"en1": st["gate"]["opened"], "en2": ps["defined"] > 0,
                "en3": all(l["translations"] > 0 for l in ps["languages"]), "en4": ps["pronounced_en"] > 0}
        for l in ps["languages"]:
            done["lang_" + l["code"]] = l["corpus"] > 0 and l["vocabulary"] >= l["corpus"]
        langs = [{"code": "en", "name": "English", "words": ps["vocabulary"], "of": None, "meanings": ps["defined"],
                  "sounds": ps["pronounced_en"], "links": sum(l["translations"] for l in ps["languages"]),
                  "built": all(done[k] for k in ("en1", "en2", "en3", "en4"))}]
        langs += [{"code": l["code"], "name": l["name"], "words": l["vocabulary"], "of": l["corpus"], "meanings": None,
                   "sounds": l["pronounced"], "links": l["translations"], "built": done["lang_" + l["code"]]} for l in ps["languages"]]
        return {"built_at": self.lab.built_at(), "stages": [{"key": k, "name": n, "done": bool(done.get(k))} for k, n in stages],
                "languages": langs, "facts": ps["facts"], "gate": st["gate"], "metrics": {k: st[k] for k in (
                    "total_tokens", "distinct_words", "distinct_phonemes", "phoneme_target", "distinct_bigrams", "avg_syllables_per_word", "ingests")},
                "history": st.get("history", [])[-60:], "phases": ps["phases"], "stage_log": self.lab.stage_log(),
                "build_started": self.store.scalar("SELECT value FROM lab_state WHERE key = 'build_started'", default=None)}

    def _warm(self):
        """Prepare the word lists in the background so the first page opens at once."""
        try:
            nat = self.native()
            for code in vocab.LANGUAGES:
                if code != nat:
                    vocab.pair_deck(code, nat)
            for code in vocab.OTHERS:
                vocab.reverse_index(code)
        except Exception as e:
            self.log("ERROR", "preparing word lists:", repr(e))

    # ------------------------------------------------------------------ words
    def native(self):
        n = self.store.meta_get("native", "en")
        return n if n in vocab.LANGUAGES else "en"

    def set_native(self, code):
        if code not in vocab.LANGUAGES:
            raise core.UserError("Unknown language.")
        self.store.meta_set("native", code)
        return {"native": code}

    def _lang(self, lang):
        if lang not in vocab.LANGUAGES:
            raise core.UserError("Choose one of: " + ", ".join(v["name"] for v in vocab.LANGUAGES.values()))
        if lang == self.native():
            raise core.UserError("You speak %s already — choose another language to learn, or change “I speak”." % vocab.LANGUAGES[lang]["name"])
        return lang

    def custom(self, lang):
        """Your own words for this language, for the language you speak: {"custom:<id>": {...}}."""
        out = {}
        for r in self.store.query("SELECT id, target_word, native_word FROM custom_pairs WHERE lang = ? AND native = ? ORDER BY id",
                                  (lang, self.native())):
            out["custom:%d" % r["id"]] = {"tr": [r["target_word"]], "nat": [r["native_word"]]}
        return out

    def get_word(self, lang, key, custom=None):
        """A word to learn: {"en": key, "tr": forms in the language learned, "nat": forms in the language spoken}."""
        if str(key).startswith("custom:"):
            custom = self.custom(lang) if custom is None else custom
            c = custom.get(key)
            return {"en": key, "tr": c["tr"], "nat": c["nat"], "rank": None, "custom": True} if c else None
        w = vocab.pair_word(lang, self.native(), key)
        if not w:
            return None
        return {"en": key, "tr": w["target"], "nat": w["native"], "rank": w["rank"], "custom": False}

    def settings(self, lang):
        r = self.store.one("SELECT new_per_day, direction FROM settings WHERE lang = ?", (lang,))
        r = r or {"new_per_day": 10, "direction": "from_native"}
        r["direction"] = _direction(r["direction"])
        return r

    def set_settings(self, lang, new_per_day=None, direction=None):
        s = self.settings(lang)
        n = s["new_per_day"] if new_per_day in (None, "") else int(new_per_day)
        d = _direction(direction or s["direction"])
        if not 0 <= n <= 100:
            raise core.UserError("New words per day must be between 0 and 100.")
        if d not in ("from_native", "to_native"):
            raise core.UserError("Unknown direction.")
        with self.store.write() as db:
            db.execute("INSERT OR REPLACE INTO settings(lang, new_per_day, direction) VALUES(?,?,?)", (lang, n, d))
        return {"new_per_day": n, "direction": d}

    def new_words(self, lang, n):
        """The next n words not yet introduced: your own words first, then the most common words."""
        if n <= 0:
            return []
        known = {r["word"] for r in self.store.query("SELECT word FROM cards WHERE lang = ?", (lang,))}
        out = [k for k in self.custom(lang) if k not in known][:n]
        for w in vocab.pair_deck(lang, self.native()):
            if len(out) >= n:
                break
            if w["en"] not in known:
                out.append(w["en"])
        return out

    # ------------------------------------------------------------------ sessions
    def session(self, lang, mode="cards", direction=None, size=20):
        lang = self._lang(lang)
        if mode not in MODES:
            raise core.UserError("Unknown practice mode.")
        st = self.settings(lang)
        direction = _direction(direction or st["direction"])
        day = self.today()
        due = [r["word"] for r in self.store.query("SELECT word FROM cards WHERE lang = ? AND due <= ? ORDER BY due, box, word LIMIT ?",
                                                     (lang, day, size))]
        introduced_today = self.store.scalar("SELECT count(*) FROM cards WHERE lang = ? AND introduced = ?", (lang, day), 0)
        allowance = max(0, st["new_per_day"] - introduced_today)
        new = self.new_words(lang, min(allowance, max(0, size - len(due))))
        custom = self.custom(lang)
        items = []
        for key, is_new in [(w, False) for w in due] + [(w, True) for w in new]:
            w = self.get_word(lang, key, custom)
            if w:
                items.append(self._item(lang, w, mode, direction, is_new, day))
        nat = self.native()
        return {"lang": lang, "language": vocab.LANGUAGES[lang]["name"], "speech": vocab.LANGUAGES[lang]["speech"],
                "native": nat, "native_name": vocab.LANGUAGES[nat]["name"], "native_speech": vocab.LANGUAGES[nat]["speech"],
                "mode": mode, "direction": direction, "items": items, "due": len(due), "new": len(new),
                "new_left_today": max(0, allowance - len(new)), "settings": st}

    def _item(self, lang, w, mode, direction, is_new, day):
        nat = self.native()
        foreign = w["tr"][0]
        direction = _direction(direction)
        if mode in ("listen", "speak"):
            direction = "from_native"
        if direction == "to_native":
            extra = vocab.reverse_index(lang).get(vocab.fold(foreign), []) if nat == "en" and not w["custom"] and lang != "en" else []
            prompt, accepted = foreign, list(dict.fromkeys(w["nat"] + extra))
        else:
            prompt, accepted = w["nat"][0], w["tr"]
        definition = ""
        if not w["custom"] and "en" in (lang, nat):
            definition = (vocab.definitions().get(w["en"]) or "")[:300]
        item = {"en": w["en"], "foreign": foreign, "all_foreign": w["tr"], "meaning": w["nat"][0], "prompt": prompt, "accepted": accepted,
                "new": is_new, "definition": definition, "custom": w["custom"], "direction": direction}
        if mode == "choice":
            item["choices"] = self._choices(lang, w, direction, day)
        if mode == "listen":
            item["prompt"] = None              # the page plays the word; the learner writes what they hear
            item["accepted"] = w["tr"]
        return item

    def _choices(self, lang, w, direction, day):
        """Four options: the answer plus three nearby words, chosen the same way every time for this word and day."""
        d = vocab.pair_deck(lang, self.native())
        pos = next((i for i, x in enumerate(d) if x["en"] == w["en"]), 0)
        seed = int(hashlib.sha256((lang + w["en"] + day).encode()).hexdigest(), 16)
        pool = [x for x in d[max(0, pos - 60): pos + 60] if x["en"] != w["en"]]
        side = "native" if direction == "to_native" else "target"
        right = w["nat"][0] if direction == "to_native" else w["tr"][0]
        picks = []
        while pool and len(picks) < 3:
            x = pool.pop(seed % len(pool))
            seed //= 7
            opt = x[side][0]
            if vocab.fold(opt) not in {vocab.fold(p) for p in picks} and vocab.fold(opt) != vocab.fold(right):
                picks.append(opt)
        opts = picks + [right]
        k = int(hashlib.sha256((w["en"] + day + "order").encode()).hexdigest(), 16) % len(opts)
        opts.insert(k, opts.pop())
        return opts

    def answer(self, lang, en, mode, direction, given=None, knew=None, score=None):
        """Grade an answer, move the card to its next box and schedule it. Returns the verdict."""
        lang = self._lang(lang)
        if mode not in MODES:
            raise core.UserError("Unknown practice mode.")
        w = self.get_word(lang, en)
        if not w:
            raise core.UserError("That word is not in the %s word list." % vocab.LANGUAGES[lang]["name"])
        item = self._item(lang, w, mode, direction or self.settings(lang)["direction"], False, self.today())
        if mode == "cards":
            if knew is None:
                raise core.UserError("Say whether you knew it.")
            verdict = {"result": "correct" if knew else "wrong", "expected": item["accepted"][0]}
        elif mode == "speak":
            heard = str(given or "")
            sim = max((vocab.similarity(heard, a) for a in item["accepted"]), default=0)
            verdict = {"result": "correct" if sim >= SPEAK_PASS else "wrong", "expected": item["accepted"][0], "similarity": sim, "heard": heard}
        else:
            verdict = vocab.check_answer(str(given or ""), item["accepted"])
        ok = verdict["result"] in ("correct", "accent")
        day = self.today()
        with self.store.write() as db:
            row = db.execute("SELECT box, reps, correct, wrong, lapses FROM cards WHERE lang = ? AND word = ?", (lang, en)).fetchone()
            box = row[0] if row else 0
            if ok:
                box = min(box + 1, len(INTERVALS) - 1)
                due = add_days(day, INTERVALS[box])
            else:
                box = 1 if box > 1 else 0
                due = day
            if row:
                db.execute("""UPDATE cards SET box = ?, due = ?, reps = reps + 1, correct = correct + ?, wrong = wrong + ?, lapses = lapses + ?,
                              last_review = ? WHERE lang = ? AND word = ?""",
                           (box, due, int(ok), int(not ok), int(not ok and row[0] > 1), core.now_iso(), lang, en))
            else:
                db.execute("""INSERT INTO cards(lang, word, box, due, reps, correct, wrong, lapses, introduced, last_review)
                              VALUES(?,?,?,?,1,?,?,0,?,?)""", (lang, en, box, due, int(ok), int(not ok), day, core.now_iso()))
            db.execute("INSERT INTO reviews(lang, word, mode, direction, correct, result, given, at, day) VALUES(?,?,?,?,?,?,?,?,?)",
                       (lang, en, mode, item["direction"], int(ok), verdict["result"], (str(given) if given is not None else None), core.now_iso(), day))
        verdict.update({"correct": ok, "box": box, "next_review": due, "all_answers": item["accepted"]})
        return verdict

    # ------------------------------------------------------------------ progress
    def language_summary(self):
        day = self.today()
        rows = {r["lang"]: r for r in self.store.query("""SELECT lang, count(*) AS learning, sum(box >= ?) AS mastered, sum(due <= ?) AS due
                                                           FROM cards GROUP BY lang""", (MASTERED_BOX, day))}
        out = []
        nat = self.native()
        for code, info in vocab.LANGUAGES.items():
            r = rows.get(code, {})
            out.append({"code": code, "name": info["name"], "native": info["native"], "is_native": code == nat,
                        "words_available": 0 if code == nat else len(vocab.pair_deck(code, nat)),
                        "learning": r.get("learning") or 0, "mastered": r.get("mastered") or 0, "due": r.get("due") or 0})
        return out

    def progress(self, lang):
        lang = self._lang(lang)
        day = self.today()
        start = add_days(day, -29)
        daily = {r["day"]: r for r in self.store.query("""SELECT day, count(*) AS reviews, sum(correct) AS correct FROM reviews
                                                           WHERE lang = ? AND day >= ? GROUP BY day""", (lang, start))}
        series = []
        for i in range(30):
            d = add_days(start, i)
            r = daily.get(d, {})
            series.append({"day": d, "reviews": r.get("reviews") or 0, "correct": r.get("correct") or 0})
        streak, d = 0, day
        days_with = {r["day"] for r in self.store.query("SELECT DISTINCT day FROM reviews WHERE lang = ?", (lang,))}
        if day not in days_with:
            d = add_days(day, -1)
        while d in days_with:
            streak += 1
            d = add_days(d, -1)
        boxes = {r["box"]: r["n"] for r in self.store.query("SELECT box, count(*) n FROM cards WHERE lang = ? GROUP BY box", (lang,))}
        week = self.store.one("SELECT count(*) AS n, sum(correct) AS c FROM reviews WHERE lang = ? AND day >= ?", (lang, add_days(day, -6)))
        hard = self.store.query("""SELECT word, wrong, correct, box FROM cards WHERE lang = ? AND wrong > 0
                                   ORDER BY wrong * 1.0 / (correct + wrong) DESC, wrong DESC LIMIT 12""", (lang,))
        for h in hard:
            w = self.get_word(lang, h["word"])
            h["foreign"] = w["tr"][0] if w else ""
            h["meaning"] = w["nat"][0] if w else ""
        upcoming = self.store.query("SELECT due, count(*) n FROM cards WHERE lang = ? AND due > ? GROUP BY due ORDER BY due LIMIT 14", (lang, day))
        return {"lang": lang, "series": series, "streak": streak, "boxes": [boxes.get(b, 0) for b in range(len(INTERVALS))],
                "intervals": INTERVALS, "week_reviews": week["n"] or 0, "week_accuracy": round(100 * (week["c"] or 0) / week["n"]) if week["n"] else None,
                "hardest": hard, "upcoming": upcoming}

    def words(self, lang, which="learning", q="", limit=100, offset=0):
        lang = self._lang(lang)
        day = self.today()
        q = vocab.clean(q)
        if which == "new":
            known = {r["word"] for r in self.store.query("SELECT word FROM cards WHERE lang = ?", (lang,))}
            rows = [w for w in vocab.pair_deck(lang, self.native()) if w["en"] not in known and
                    (not q or any(q in vocab.fold(t) for t in w["target"] + w["native"]))]
            return {"total": len(rows), "words": [{"word": w["en"], "foreign": ", ".join(w["target"]), "meaning": ", ".join(w["native"]),
                                                   "box": None, "due": None} for w in rows[offset:offset + limit]]}
        where = {"learning": "", "mastered": " AND box >= %d" % MASTERED_BOX, "due": " AND due <= '%s'" % day}.get(which, "")
        rows = self.store.query("SELECT word, box, due, correct, wrong FROM cards WHERE lang = ?%s ORDER BY word" % where, (lang,))
        custom = self.custom(lang)
        out = []
        for r in rows:
            w = self.get_word(lang, r["word"], custom)
            if not w:
                continue                         # e.g. your own word made for another "I speak" language
            r["foreign"], r["meaning"] = ", ".join(w["tr"]), ", ".join(w["nat"])
            if not q or q in vocab.fold(r["foreign"]) or q in vocab.fold(r["meaning"]):
                out.append(r)
        return {"total": len(out), "words": out[offset:offset + limit]}

    # ------------------------------------------------------------------ old QueryBook
    def import_old(self, folder, progress, stop):
        store = core.find_old_store(folder)
        if not store:
            raise core.UserError("No old QueryBook store found in that folder.")
        self.store.backup("before-import", force=True)
        files = added = 0
        for name, model in core.iter_old_language_models(store):
            if stop():
                break
            files += 1
            lang = "en"
            for code in list(vocab.LANGUAGES) + ["en"]:
                if name.startswith("language_model_%s" % code) or name.startswith("language_model-%s" % code):
                    lang = code
            if lang == "en" and name == "language_model.json":
                adopted = self.lab.adopt_old_model(model, name)
                self.store.activity("Language Lab: continue from old English model", "ok" if adopted.get("adopted") else "skipped",
                                    json.dumps(adopted)[:300])
            words = model.get("words") or {}
            if isinstance(words, list):
                words = {w: 1 for w in words}
            rows = [(lang, str(w).lower()[:80], int(c) if isinstance(c, (int, float)) else 1, name)
                    for w, c in words.items() if str(w).isalpha()]
            with self.store.write() as db:
                for r in rows:
                    db.execute("""INSERT INTO old_words(lang, word, seen, origin) VALUES(?,?,?,?)
                                  ON CONFLICT(lang, word) DO UPDATE SET seen = max(seen, excluded.seen)""", r)
            added += len(rows)
            progress(files, None, "%s: %s words" % (name, format(len(rows), ",")))
        self.store.backup("after-import", force=True)
        return {"old_store": store, "language_model_files": files, "words_recorded": added,
                "note": "The old QueryBook counted words it read; those counts are kept so you can add the words it saw most into your lessons."}

    def add_old_words(self, lang, limit):
        """Put the old store's most-seen English words that have a translation into lessons, due today."""
        lang = self._lang(lang)
        day = self.today()
        rows = self.store.query("SELECT word FROM old_words WHERE lang = 'en' ORDER BY seen DESC LIMIT 5000")
        known = {r["word"] for r in self.store.query("SELECT word FROM cards WHERE lang = ?", (lang,))}
        picked = [r["word"] for r in rows if r["word"] not in known and vocab.pair_word(lang, self.native(), r["word"])][:limit]
        with self.store.write() as db:
            db.executemany("INSERT OR IGNORE INTO cards(lang, word, box, due, introduced) VALUES(?,?,0,?,?)", [(lang, w, day, day) for w in picked])
        return {"added": len(picked), "words": picked}

    # ------------------------------------------------------------------ diagnostics
    def _health(self):
        C = core._check
        sizes = {code: len(vocab.deck(code)) for code in vocab.OTHERS}
        small = [vocab.LANGUAGES[c]["name"] for c, n in sizes.items() if n < 1500]
        out = [C("wordlists", "Word lists", "fail" if small else "ok", ("too few words: " + ", ".join(small)) if small else "%d languages, %d–%d words each" % (len(sizes), min(sizes.values()), max(sizes.values())))]
        okd = len(vocab.definitions()) > 5000
        out.append(C("dictionary", "English dictionary", "ok" if okd else "fail", "%d entries" % len(vocab.definitions())))
        okc = vocab.check_answer("etre", ["être"])["result"] == "accent" and vocab.check_answer("gato", ["perro"])["result"] == "wrong"
        out.append(C("checker", "Answer checking", "ok" if okc else "fail"))
        sp = speech.status()
        miss = bundle_missing()
        if sp["espeak"]:
            out.append(C("voice", "Default voice (espeak-ng)", "ok", "%s — %s" % ("bundled" if sp["bundled"] else "system", sp["version"] or sp["path"])))
        else:
            out.append(C("voice", "Default voice (espeak-ng)", "warn", sp["hint"]))
        out += speechlab.diagnostics(self.speech, C) if hasattr(self, "speech") else []
        b = self.lab.built_at()
        sl = self.lab.stage_log()
        out.append(C("build", "Language build", "ok" if b else "warn", ("all 20 steps done %s" % b) if b else "not built yet — it starts automatically"))
        vr = self.last_verification()
        out.append(C("proof", "Proof of learning from scratch", "ok" if vr and vr["verdict"] == "PASS" else "fail" if vr else "warn",
                     ("%s %s, fingerprint %s…" % (vr["verdict"], vr["finished"], vr.get("fingerprint", {}).get("sha256", "")[:16])) if vr else "not run yet (Verify tab)"))
        if hasattr(self, "coach"):
            st = self.coach.status()
            out.append(C("reservoir", "Ingestion reservoir (lip-reading / lip-sync learning)", "ok",
                         "%d recordings; %s" % (st["total"], ("version %s in use" % st["active_version"]) if st["active_version"] else "built-in rules in use")))
        vm = vendor_missing()
        out.append(C("face_video", "Face & video (3D/VR face, face tracker)", "fail" if vm else "ok",
                     ("missing: " + ", ".join(vm)) if vm else "three.js r160 and MediaPipe Face Landmarker 0.10.14 present (%d files)" % len(VENDOR)))
        out.append(C("voice_bundle", "Bundled espeak-ng files", "fail" if miss else "ok", ("missing: " + ", ".join(miss[:6])) if miss else "program, runtime and 17 languages present"))
        return out

    # ------------------------------------------------------------------ routes
    def _routes(self):
        a = self.api

        @a.get("/api/status")
        def status(p):
            return {"app": APP_NAME, "version": VERSION, "store": self.store.status(), "health": (self.diag.last or {}).get("overall"), "speech": speech.status(),
                    "reviews": self.store.scalar("SELECT count(*) FROM reviews", default=0),
                    "cards": self.store.scalar("SELECT count(*) FROM cards", default=0), "sources": vocab.SOURCES, "job": self.jobs.status()["state"]}

        @a.get("/api/languages")
        def languages(p):
            return {"languages": self.language_summary(), "native": self.native(), "modes": MODES, "intervals": INTERVALS}

        @a.get("/api/settings")
        def get_settings(p):
            return self.settings(self._lang(p.get("lang")))

        @a.post("/api/settings")
        def post_settings(p):
            return self.set_settings(self._lang(p.get("lang")), p.get("new_per_day"), p.get("direction"))

        @a.get("/api/session")
        def session(p):
            return self.session(p.get("lang"), p.get("mode") or "cards", p.get("direction") or None, int(p.get("size") or 20))

        @a.post("/api/answer")
        def answer(p):
            return self.answer(p.get("lang"), p.get("en"), p.get("mode"), p.get("direction"), p.get("given"), p.get("knew"), p.get("score"))

        @a.get("/api/progress")
        def progress(p):
            return self.progress(p.get("lang"))

        @a.get("/api/words")
        def words(p):
            return self.words(p.get("lang"), p.get("which") or "learning", p.get("q") or "", int(p.get("limit") or 100), int(p.get("offset") or 0))

        @a.post("/api/words/reset")
        def reset(p):
            with self.store.write() as db:
                db.execute("DELETE FROM cards WHERE lang = ? AND word = ?", (self._lang(p.get("lang")), p.get("word")))
            return {"ok": True}

        @a.get("/api/custom")
        def custom_list(p):
            return {"words": self.store.query("SELECT * FROM custom_pairs WHERE lang = ? AND native = ? ORDER BY id DESC",
                                              (self._lang(p.get("lang")), self.native()))}

        @a.post("/api/custom/add")
        def custom_add(p):
            lang = self._lang(p.get("lang"))
            tw = " ".join(str(p.get("target_word") or "").split())
            nw = " ".join(str(p.get("native_word") or "").split())
            if not tw or not nw:
                raise core.UserError("Enter the word in both languages.")
            if len(tw) > 80 or len(nw) > 80:
                raise core.UserError("Keep each word or phrase under 80 characters.")
            with self.store.write() as db:
                db.execute("INSERT OR IGNORE INTO custom_pairs(lang, native, target_word, native_word, note, created) VALUES(?,?,?,?,?,?)",
                           (lang, self.native(), tw, nw, (p.get("note") or "").strip() or None, core.now_iso()))
            return {"ok": True}

        @a.post("/api/custom/delete")
        def custom_delete(p):
            with self.store.write() as db:
                db.execute("DELETE FROM custom_pairs WHERE id = ?", (int(p.get("id")),))
                db.execute("DELETE FROM cards WHERE word = ?", ("custom:%d" % int(p.get("id")),))
            return {"ok": True}

        @a.get("/api/native")
        def get_native(p):
            return {"native": self.native()}

        @a.post("/api/native")
        def post_native(p):
            return self.set_native(p.get("native"))

        @a.get("/api/lookup")
        def lookup(p):
            return vocab.lookup(p.get("q", ""))

        @a.get("/api/speak")
        def speak(p):
            lang = p.get("lang") or "en"
            voice = vocab.LANGUAGES[lang]["espeak"] if lang in vocab.LANGUAGES else vocab.ENGLISH["espeak"]
            wav = speech.speak_wav(p.get("text", ""), voice, int(p.get("rate") or 140))
            if not wav:
                raise core.UserError("No voice is available for this language. Install a voice in your system's speech settings, or install espeak-ng.")
            return wav, "audio/wav"

        @a.get("/api/ipa")
        def ipa(p):
            lang = p.get("lang") or "en"
            voice = vocab.LANGUAGES[lang]["espeak"] if lang in vocab.LANGUAGES else vocab.ENGLISH["espeak"]
            return {"ipa": speech.ipa(p.get("text", ""), voice)}

        # ---- Language Lab (learns English, then the other languages, by itself)
        @a.get("/api/lab/status")
        def lab_status(p):
            st = self.lab.status()
            st["phase_status"] = self.lab.phase_status()
            return st

        @a.post("/api/lab/run")
        def lab_run(p):
            if p.get("fresh"):                     # rebuild everything from nothing (backup first)
                if self.jobs.status().get("state") == "running":
                    raise core.UserError("Something is still running. Wait for it or stop it first.")
                self.store.backup("before-rebuild", force=True)
                times = {r["key"]: r.get("seconds") for r in self.lab.stage_log() if r.get("seconds")}
                self.lab.forget()
                self.store.activity("Rebuild from scratch", "ok", "previous build forgotten after a backup")
                return self.start_build(times or None)
            return self.start_build()

        # ---- Speech Lab: ingestion, generation, matching, spoken queries, providers, log
        import base64 as _b64

        def _audio(p, key="audio_b64"):
            v = p.get(key)
            if not v:
                return None
            if "," in v[:80]:
                v = v.split(",", 1)[1]
            try:
                return _b64.b64decode(v)
            except ValueError:
                raise core.UserError("The audio could not be read.")

        def _gen_args(p):
            return dict(prof=p.get("profile") or {}, engine=p.get("engine") or "espeak", voice=p.get("voice") or "",
                        model=p.get("model") or "", adv=p.get("advanced") or {})

        @a.get("/api/speech/engines")
        def sp_engines(p):
            return {"engines": tts.engines_public(self.speech.keys), "keys": self.speech.keys.public(), "controls": tts.CONTROLS,
                    "profile_default": tts.PROFILE_DEFAULT, "emotions": tts.EMOTIONS, "tones": tts.TONES, "articulation": tts.ARTICULATION,
                    "dialects": speechlab.dialect.list_dialects(), "languages": [{"code": c, "name": v["name"]} for c, v in vocab.LANGUAGES.items()],
                    "targets": self.speech.TARGET_KEYS}

        @a.get("/api/speech/voices")
        def sp_voices(p):
            e = tts.BY_ID.get(p.get("engine") or "espeak")
            if not e:
                raise core.UserError("Unknown engine.")
            return {"voices": e.voices(self.speech.keys, p.get("lang") or "en"), "models": e.models}

        @a.post("/api/speech/plan")
        def sp_plan(p):
            g = _gen_args(p)
            pl, _run, _fx = tts.plan(p.get("text") or "", g["prof"], g["engine"], g["voice"], g["model"], self.speech.keys, g["adv"])
            return pl

        @a.post("/api/speech/generate")
        def sp_generate(p):
            try:
                return self.speech.generate(p.get("text"), fallback=p.get("fallback", True) not in (False, "false"), **_gen_args(p))
            except (ValueError, RuntimeError) as e:
                raise core.UserError(str(e))

        @a.post("/api/speech/match")
        def sp_match(p):
            g = _gen_args(p)
            text, target, rounds = p.get("text"), p.get("target") or {}, int(p.get("rounds") or 5)
            return self.jobs.start("Speech: match the target", lambda prog, stop: self.speech.match(text, target, g["prof"], g["engine"], g["voice"],
                                                                                                  g["model"], g["adv"], rounds, prog, stop))

        @a.post("/api/speech/ingest")
        def sp_ingest(p):
            try:
                return self.speech.ingest(_audio(p), p.get("transcript") or "", p.get("expected") or "", p.get("label") or "",
                                          p.get("recognizer") or "auto", p.get("lang") or "en", p.get("video") or None)
            except ValueError as e:
                raise core.UserError(str(e))

        @a.post("/api/speech/transcribe-file")
        def sp_transcribe_file(p):
            wav = _audio(p)
            if not wav or not voicedsp_is_wav(wav):
                raise core.UserError("Send the recording as WAV (the page converts MP3 and other formats).")
            if not self.speech.stt_ready():
                raise core.UserError("Transcription needs Google Speech-to-Text: add the Google key under Diagnostics → Google Cloud.")
            return self.speech.start_transcription(wav, p.get("lang") or "en", p.get("mode") or "auto")

        @a.get("/api/speech/transcribe-status")
        def sp_transcribe_status(p):
            try:
                return self.speech.transcription(p.get("task") or "")
            except ValueError as e:
                raise core.UserError(str(e))

        @a.post("/api/speech/caption/start")
        def sp_caption_start(p):
            if not self.speech.stt_ready():
                raise core.UserError("Live captions need Google Speech-to-Text: add the Google key under Diagnostics → Google Cloud.")
            return self.speech.caption_session(p.get("name") or "audio", p.get("duration_s") or 0, p.get("lang") or "en")

        @a.post("/api/speech/caption/piece")
        def sp_caption_piece(p):
            try:
                return self.speech.caption_piece(_audio(p), p.get("lang") or "en", float(p.get("offset_s") or 0), p.get("session"))
            except (ValueError, RuntimeError) as e:
                raise core.UserError(str(e))

        @a.post("/api/speech/query")
        def sp_query(p):
            try:
                return self.speech.query(p.get("transcript"), _audio(p), respond_to_mood=p.get("respond_to_mood", True) not in (False, "false"),
                                         video=p.get("video") or None, **_gen_args(p))
            except (ValueError, RuntimeError) as e:
                raise core.UserError(str(e))

        @a.post("/api/speech/keys")
        def sp_keys(p):
            try:
                self.speech.keys.save(p.get("provider"), p.get("values") or {})
            except ValueError as e:
                raise core.UserError(str(e))
            self.store.activity("Speech: provider settings saved", "ok", p.get("provider"))
            return self.speech.keys.public()

        @a.post("/api/speech/keys/import-prototype")
        def sp_keys_import(p):
            clk = speechlab.Clock(); clk("search and import")
            r = self.speech.keys.import_prototype((p.get("folder") or "").strip() or None)
            where = core.redact(r["found"]) if r["found"] else None
            self.speech._record("keys-import", "old QueryBook keys: %s" % (", ".join(r["imported"]) if r["imported"] else "none found (%d places searched)" % r["searched"]),
                                "", "ok" if r["imported"] else "not found", clk, {"folder": core.redact(p.get("folder") or "")}, {"found": where, "imported": r["imported"]})
            return {"found": where, "searched": r["searched"], "imported": r["imported"], "defaults": r["defaults_noted"], "keys": self.speech.keys.public()}

        @a.post("/api/speech/keys/forget")
        def sp_keys_forget(p):
            self.speech.keys.forget(p.get("provider"))
            self.store.activity("Speech: provider settings removed", "ok", p.get("provider"))
            return self.speech.keys.public()

        @a.post("/api/speech/custom-voice")
        def sp_custom(p):
            clk = speechlab.Clock(); clk("build custom voice")
            try:
                r = tts.BY_ID["google_cloud"].build_custom_voice(self.speech.keys, (p.get("name") or "").strip(), _audio(p),
                                                                p.get("consent") in (True, "true"), p.get("language") or "en-US")
            except Exception as e:
                self.speech._record("custom-voice", "failed: %s" % tts.scrub(e, self.speech.keys), "google_cloud", "failed", clk)
                raise core.UserError(tts.scrub(e, self.speech.keys))
            self.speech._record("custom-voice", "custom voice '%s' built (with consent)" % r["name"], "google_cloud", "ok", clk)
            return r

        @a.post("/api/speech/lipsync")
        def sp_lipsync(p):
            try:
                return self.speech.lipsync(p.get("audio") or "", p.get("text") or "", p.get("lang") or "en", p.get("exact") in (True, "true"))
            except FileNotFoundError:
                raise core.UserError("That audio is not kept here.")

        @a.get("/api/speech/lipsync.export")
        def sp_lipsync_export(p):
            tr = self.speech.lipsync(p.get("audio") or "", p.get("text") or "", p.get("lang") or "en", False)
            fmt = p.get("format") or "json"
            if fmt == "csv":
                return visemes.csv_text(tr).encode("utf-8"), "text/csv; charset=utf-8"
            if fmt == "tsv":
                return visemes.rhubarb_tsv(tr).encode("utf-8"), "text/tab-separated-values; charset=utf-8"
            return json.dumps(tr, indent=1, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"

        @a.post("/api/scan/save")
        def scan_save(p):
            try:
                return self.scan.save(p)
            except ValueError as e:
                raise core.UserError(str(e))

        @a.get("/api/scan/sessions")
        def scan_sessions(p):
            return {"sessions": self.scan.sessions(), "stats": self.scan.stats()}

        @a.post("/api/scan/delete")
        def scan_delete(p):
            return self.scan.delete(int(p.get("id")))

        @a.post("/api/scan/query")
        def scan_query(p):
            r = self.scan.answer(p.get("q"), int(p.get("tz_min") or 0), p.get("live"))
            return r or {"kind": "none", "answer": "Ask about what the camera saw — for example: when did I last see a cup? what did I see today? what is this in Spanish?"}

        @a.post("/api/scan/what")
        def scan_what(p):
            return self.scan.what_is(p.get("label"), p.get("score"), p.get("lang"))

        @a.get("/api/vse/info")
        def vse_info(p):
            return {"version": vse.VERSION, "params": vse.PARAMS, "visemes": list(vse.TARGETS), "unit": vse.UNIT,
                    "subsystems": {"APS": "phonemes, prosody, emotion, voice fingerprint", "VPS": "head pose, camera motion, lighting (SH1), face geometry",
                                   "LSG/FMS": "coarticulated full-face motion (dominance model)", "LRE": "HMM word decoding / script alignment",
                                   "COL": "jobs: lip_sync, lip_read, benchmark"},
                    "learned_model_active": isinstance(lipread.ACTIVE.get("model"), dict)}

        @a.post("/api/vse/lip_sync")
        def vse_lip_sync(p):
            text = (p.get("text") or "").strip()
            wav = None
            if p.get("audio_b64"):
                wav = _audio(p)
            elif p.get("log_id"):
                row = self.store.one("SELECT request, result, audio FROM speech_log WHERE id = ?", (int(p["log_id"]),))
                if not row or not row["audio"]:
                    raise core.UserError("That speech log entry has no recording.")
                with open(self.speech.audio_path(row["audio"]), "rb") as f:
                    wav = f.read()
                if not text:
                    req = json.loads(row["request"] or "{}"); res = json.loads(row["result"] or "{}")
                    text = req.get("text") or res.get("transcript") or ""
            if not text:
                raise core.UserError("Give the words that are spoken.")
            if wav is not None and not voicedsp_is_wav(wav):
                raise core.UserError("Send the audio as WAV (the page converts MP3 and other formats before sending).")
            if wav is None:
                tr = vse.timing_from_text(text, p.get("lang") or "en", self.lab)
                return self.vse.submit("lip_sync", lambda prog: dict(vse.lip_sync(tr, None, p.get("emotion"), int(p.get("fps") or 30), seed=text),
                                                                      note="timed from the text (no audio)"))
            return self.vse.submit("lip_sync", self.vse.lip_sync_job(wav, text, p.get("lang") or "en", p.get("word_times"), int(p.get("fps") or 30),
                                                                     p.get("emotion"), p.get("personal", True) not in (False, "false")))

        @a.post("/api/vse/lip_read")
        def vse_lip_read(p):
            words = [w for w in re.split(r"[\s,;]+", p.get("words") or "") if w] if isinstance(p.get("words"), str) else list(p.get("words") or [])
            return self.vse.submit("lip_read", self.vse.lip_read_job(p.get("frames") or [], p.get("lang") or "en", words, p.get("script") or ""))

        @a.post("/api/vse/benchmark")
        def vse_benchmark(p):
            return self.vse.submit("benchmark", self.vse.benchmark_job())

        @a.get("/api/vse/job")
        def vse_job(p):
            try:
                return self.vse.status(p.get("id") or "")
            except KeyError:
                raise core.UserError("No such job (jobs are kept while the application runs).")

        @a.post("/api/video/analyse")
        def video_analyse(p):
            return self.speech.video_analysis(p)

        @a.post("/api/video/event")
        def video_event(p):
            # capture steps that happen in the browser (camera on, recording, export) go into the same speech log
            clk = speechlab.Clock()
            clk.t0 -= max(0.0, min(86400.0, float(p.get("seconds") or 0)))
            clk(str(p.get("what") or "event")[:80])
            clk._cur["_t"], clk._cur["at_s"] = clk.t0, 0.0
            self.speech._record("capture", "%s — %s" % (str(p.get("what") or "")[:80], str(p.get("detail") or "")[:200]), "browser",
                                "failed" if p.get("status") == "failed" else "ok", clk)
            return {"ok": True}

        # ---- Author Narrator (persona) and the Photo Real Lab
        def _logged(process, desc, fn, engine="persona"):
            clk = speechlab.Clock()
            clk(process)
            try:
                r = fn()
            except (ValueError, RuntimeError, FileNotFoundError) as e:
                self.speech._record(process, "failed: %s" % tts.scrub(e, self.speech.keys)[:300], engine, "failed", clk)
                raise core.UserError(tts.scrub(e, self.speech.keys))
            self.speech._record(process, desc(r) if callable(desc) else desc, engine, "ok", clk)
            return r

        @a.get("/api/persona")
        def pe_list(p):
            k = self.speech.keys
            return {"personas": self.personas.list(), "voice_methods": persona.VOICE_METHODS, "face_methods": persona.FACE_METHODS,
                    "consent_text": persona.CONSENT_TEXT, "local_presets": persona.LOCAL_PRESETS, "label": persona.LABEL,
                    "keys": {x: k.configured(x) for x in ("heygen", "did", "elevenlabs", "google_cloud")}, "dimensions": {d: v[0] for d, v in photoreal.DIMENSIONS.items()},
                    "gate": {"overall": photoreal.PASS_OVERALL, "critical": photoreal.PASS_CRITICAL}, "passage": photoreal.REFERENCE_PASSAGE}

        @a.get("/api/persona/get")
        def pe_get(p):
            try:
                return self.personas.get(p.get("id"))
            except ValueError as e:
                raise core.UserError(str(e))

        @a.get("/api/persona/photo")
        def pe_photo(p):
            try:
                pe = self.personas.get(p.get("id"))
                with open(self.personas.file_path(pe["id"], pe["photo"]), "rb") as f:
                    return f.read(), "image/jpeg"
            except (ValueError, FileNotFoundError):
                raise core.UserError("No photo.")

        @a.get("/api/persona/video")
        def pe_video(p):
            try:
                n = self.personas.narration(p.get("narration"))
                with open(self.personas.file_path(n["persona"], n["video"]), "rb") as f:
                    return f.read(), "video/mp4"
            except (ValueError, FileNotFoundError, TypeError):
                raise core.UserError("That video is not here.")

        @a.post("/api/persona/create")
        def pe_create(p):
            photo = _b64.b64decode((p.get("photo_b64") or "").split(",", 1)[-1] or "")
            return _logged("persona", lambda r: "persona “%s” created (consent signed by %s)" % (r["name"], r["consent"]["signer"]),
                           lambda: self.personas.create(p.get("name"), p.get("signer"), p.get("consent") in (True, "true"), photo, _audio(p, "sample_b64"),
                                                        p.get("lang") or "en", p.get("landmarks"), p.get("on_behalf") in (True, "true")))

        @a.post("/api/persona/library")
        def pe_library(p):
            return _logged("persona", lambda r: "real-mouth library: %d frames of the author's own mouth" % r["count"],
                           lambda: self.personas.set_library(p.get("id"), p.get("items") or []))

        @a.get("/api/persona/lib")
        def pe_lib(p):
            try:
                pe = self.personas.get(p.get("id"))
                ent = ((pe.get("reference") or {}).get("library") or {}).get(p.get("v") or "")
                with open(self.personas.file_path(pe["id"], ent["file"]), "rb") as f:
                    return f.read(), "image/jpeg"
            except (ValueError, FileNotFoundError, TypeError, KeyError):
                raise core.UserError("No such frame.")

        @a.post("/api/persona/landmarks")
        def pe_landmarks(p):
            return _logged("persona", "face landmarks of the photo saved", lambda: self.personas.set_landmarks(p.get("id"), p.get("landmarks")))

        @a.post("/api/persona/voice")
        def pe_voice(p):
            return _logged("persona-voice", lambda r: "voice: %s" % persona.VOICE_METHODS[r["method"]],
                           lambda: self.personas.set_voice(p.get("id"), p.get("method"), p.get("lang") or "en"))

        @a.post("/api/persona/face")
        def pe_face(p):
            return _logged("persona-face", lambda r: "face: %s" % persona.FACE_METHODS[r["method"]],
                           lambda: self.personas.set_face(p.get("id"), p.get("method"), p.get("settings") or {}))

        @a.post("/api/persona/delete")
        def pe_delete(p):
            return _logged("persona", "persona deleted with its samples", lambda: self.personas.delete(p.get("id")))

        @a.post("/api/persona/narrate")
        def pe_narrate(p):
            return _logged("narrate", lambda r: "narration #%d (%s) “%s”" % (r["id"], r["face_method"], (p.get("text") or "")[:60]),
                           lambda: self.personas.narrate(p.get("id"), p.get("text"), p.get("face_method") or None, p.get("emotion") or None))

        @a.get("/api/persona/narration")
        def pe_narration(p):
            try:
                return self.personas.narration(p.get("id"))
            except ValueError as e:
                raise core.UserError(str(e))

        def _wav_of(p):
            if p.get("audio"):
                with open(self.speech.audio_path(p["audio"]), "rb") as f:
                    return f.read()
            w = _audio(p)
            if not w:
                raise core.UserError("No sound was sent.")
            return w

        @a.post("/api/photoreal/reference")
        def pr_reference(p):
            wav = _wav_of(p)
            return _logged("photoreal", lambda r: "perfect reference analysed: %d frames, lead %s ms, response %s ms, explains %d%%" % (r["signature"]["frames"], r["model"]["lead_ms"], r["model"]["tau_ms"], round(100 * r["model"]["explained"])),
                           lambda: self.prlab.set_reference(p.get("persona"), p.get("frames") or [], wav, p.get("text") or "", p.get("lang") or "en", p.get("info") or {}), "photoreal")

        @a.post("/api/photoreal/measure")
        def pr_measure(p):
            wav = _wav_of(p)
            return _logged("photoreal", lambda r: "%s measured: %.0f/100 — %s" % (p.get("method"), r["score"]["overall"], r["score"]["verdict"]),
                           lambda: self.prlab.measure(p.get("persona"), p.get("frames") or [], wav, p.get("text") or "", p.get("method") or "photo",
                                                      p.get("lang") or "en", p.get("info") or {}, p.get("narration"), p.get("params")), "photoreal")

        @a.post("/api/photoreal/calibrate")
        def pr_calibrate(p):
            wav = _wav_of(p)
            return _logged("photoreal", lambda r: "calibration round %d: %.0f/100 %s" % (r["round"], r["score"]["overall"], "PASS" if r["passed"] else "→ corrected"),
                           lambda: self.prlab.calibrate(p.get("persona"), p.get("frames") or [], wav, p.get("text") or "", p.get("params") or photoreal.DEFAULT_PARAMS,
                                                        p.get("lang") or "en", p.get("info") or {}, int(p.get("round") or 1)), "photoreal")

        @a.get("/api/photoreal/findings")
        def pr_findings(p):
            return self.prlab.findings(p.get("persona") or None)

        @a.get("/api/photoreal/graph")
        def pr_graph(p):
            return {"facts": self.prlab.graph(p.get("subject") or None, p.get("predicate") or None)}

        @a.get("/api/photoreal/export.ufcs")
        def pr_export(p):
            return self.prlab.export_ufcs().encode("utf-8"), "application/x-ndjson; charset=utf-8"

        # ---- silent questions: lips only (for people who cannot speak aloud)
        @a.get("/api/silent/patterns")
        def si_patterns(p):
            return {"patterns": [{"id": t["id"], "parts": t["parts"], "example": t["example"]} for t in silent.TEMPLATES],
                    "languages": [v["name"] for v in vocab.LANGUAGES.values()]}

        @a.post("/api/silent/read")
        def si_read(p):
            clk = speechlab.Clock()
            clk("read the lips")
            frames = p.get("frames") or []
            cls = lipread.classes_of(frames)[0]
            if not cls:
                raise core.UserError("No face was seen — face the camera and mouth the question again.")
            words = [w for w in re.split(r"[\s,;]+", p.get("words") or "") if w]
            r = silent.decode_word(cls, self.lab, words) if p.get("mode") == "word" else silent.decode(cls, self.lab, words)
            best = (r["readings"] or [{}])[0]
            self.speech._record("silent", "%s: %s" % ("word" if p.get("mode") == "word" else "question", best.get("question") or best.get("word") or "nothing read"),
                                "lips", "ok" if r["readings"] else "failed", clk, {"frames": len(frames), "mode": p.get("mode") or "question"},
                                {"seen": r["seen"], "readings": r["readings"][:5]})
            return r

        # ---- the ingestion reservoir (speech-visual) and its learner
        @a.get("/api/lipcoach")
        def lc_status(p):
            return self.coach.status()

        @a.get("/api/lipcoach/mouth")
        def lc_mouth(p):
            return {"mouth": self.coach.mouth, "version": lipread_active_version()}

        @a.post("/api/lipcoach/teach")
        def lc_teach(p):
            clk = speechlab.Clock()
            clk("receive")
            wav, text, lang = _audio(p), " ".join(str(p.get("text") or "").split()), p.get("lang") or "en"
            if not wav or not text:
                raise core.UserError("Record the sentence with the camera on first.")
            wt = None
            if self.speech.stt_ready():
                clk("exact word times (Google Speech-to-Text)")
                st = self.speech.transcribe(wav, lang)
                if st and st.get("words") and vocab.similarity(st.get("transcript", ""), text) >= 80:
                    wt = st["words"]                       # only when Google heard the same sentence
            clk("label the frames and deposit")
            try:
                r = self.coach.deposit(p.get("frames") or [], text, lang, "teach", wav, None, wt, p.get("info") or {})
            except ValueError as e:
                raise core.UserError(str(e))
            self.speech._record("teach", "“%s” — %s" % (text[:60], ("%d frames labelled, %s set" % (r["labelled_frames"], r["split"])) if r.get("stored") else r.get("reason")),
                                "lipcoach", "ok" if r.get("stored") else "skipped", clk, {"text": text, "frames": len(p.get("frames") or [])}, r)
            return r

        @a.post("/api/lipcoach/train")
        def lc_train(p):
            clk = speechlab.Clock()
            clk("learn from the reservoir and test on held-back recordings")
            if self.coach.training:
                raise core.UserError("Learning is already running — try again in a moment.")
            r = self.coach.train()
            self.speech._record("learn", "; ".join(r.get("note") or [])[:400] or "learned", "lipcoach", "ok", clk, None, r.get("metrics"))
            return r

        @a.post("/api/lipcoach/use")
        def lc_use(p):
            try:
                return {"active_version": self.coach.use(p.get("version") or "rules")}
            except ValueError as e:
                raise core.UserError(str(e))

        @a.post("/api/lipcoach/auto")
        def lc_auto(p):
            return {"auto": self.coach.set_auto(p.get("on") in (True, "true"))}

        @a.get("/api/lipcoach/export")
        def lc_export(p):
            return json.dumps(self.coach.export(), ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"

        @a.post("/api/lipcoach/import")
        def lc_import(p):
            try:
                return self.coach.import_(p.get("data"))
            except ValueError as e:
                raise core.UserError(str(e))

        @a.get("/api/video/guide")
        def video_guide(p):
            import lipread
            return {"guide": lipread.GUIDE, "classes": lipread.CLASSES}

        @a.post("/api/video/overdub")
        def video_overdub(p):
            try:
                wav = _audio(p) or b""
                return self.speech.overdub(wav, p.get("text") or "", consent=p.get("consent") in (True, "true"), lang=(p.get("profile") or {}).get("lang"), **_gen_args(p))
            except (ValueError, RuntimeError) as e:
                raise core.UserError(str(e))

        @a.get("/api/speech/log")
        def sp_log(p):
            return {"log": self.speech.history(min(1000, int(p.get("limit") or 100)), p.get("process") or None), "stats": self.speech.stats()}

        @a.get("/api/speech/log.csv")
        def sp_log_csv(p):
            import csv, io as _io
            buf = _io.StringIO()
            w = csv.writer(buf)
            w.writerow(["id", "started_utc", "ended_utc", "seconds", "process", "engine", "status", "description", "stages (stage@start s: seconds)", "audio"])
            for r in self.speech.history(100000):
                w.writerow([r["id"], r["started"], r["ended"], "%.2f" % (r["seconds"] or 0), r["process"], r["engine"], r["status"], r["description"],
                            "; ".join("%s@%.2f: %.2f" % (x["stage"], x.get("at_s") or 0, x.get("seconds") or 0) for x in (r["stages"] or [])), r["audio"] or ""])
            return buf.getvalue().encode("utf-8"), "text/csv; charset=utf-8"

        @a.get("/api/speech/audio")
        def sp_audio(p):
            try:
                with open(self.speech.audio_path(p.get("name") or ""), "rb") as f:
                    return f.read(), "audio/wav"
            except FileNotFoundError:
                raise core.UserError("That audio file is not kept here.")

        @a.post("/api/verify")
        def verify_run(p):
            return self.jobs.start(self.VERIFY_JOB, self.run_verification)

        @a.get("/api/verify/last")
        def verify_last(p):
            return {"report": self.last_verification()}

        @a.get("/api/verify/report.txt")
        def verify_txt(p):
            rep = self.last_verification()
            if not rep:
                raise core.UserError("No verification has been run yet.")
            return verify.text(rep).encode("utf-8"), "text/plain; charset=utf-8"

        @a.get("/api/verify/report.json")
        def verify_json(p):
            rep = self.last_verification()
            if not rep:
                raise core.UserError("No verification has been run yet.")
            return json.dumps(rep, indent=1, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"

        @a.get("/api/build")
        def build(p):
            return self.build_status()

        @a.post("/api/lab/feed")
        def lab_feed(p):
            text, url = (p.get("text") or "").strip(), (p.get("url") or "").strip()
            if not text and not url:
                raise core.UserError("Paste English text or give a web address.")
            def run(prog, stop):
                prog(0, 2, "fetching %s" % url if url else "reading your text")
                body = text
                if url:
                    if not url.startswith(("http://", "https://")):
                        raise core.UserError("The address must start with http:// or https://")
                    body = _fetch_text(url)
                prog(1, 2, "Phase 1: learning structure from %d characters" % len(body))
                mx = self.lab.learn(body, ("Phase 1 · " + url) if url else "Phase 1 · your text")
                prog(2, 2, "gate %.0f%%" % mx["gate"]["progress"])
                return {"characters": len(body), "words_now": mx["distinct_words"], "gate_progress": mx["gate"]["progress"],
                        "gate_open": mx["gate"]["opened"]}
            return self.jobs.start("Read more English (Phase 1)", run)

        @a.get("/api/lab/word")
        def lab_word(p):
            return self.lab.word_card(p.get("w", ""))

        @a.get("/api/lab/recent")
        def lab_recent(p):
            return {"facts": self.lab.recent_facts(60)}

        @a.get("/api/lab/sources")
        def lab_sources(p):
            return {"sources": lab.C.SEED_SOURCES, "phases": lab.C.LANGUAGE_PHASES, "gate": lab.C.GATE, "starter_chunks": len(lab.C.STARTER_CORPUS)}

        @a.post("/api/lab/forget")
        def lab_forget(p):
            self.store.backup("before-lab-reset", force=True)
            self.lab.forget()
            return {"ok": True}

        @a.get("/api/old-store-hint")
        def old_store_hint(p):
            hints = core.old_store_hints()
            return {"folder": hints[0] if hints else "", "all": hints}

        @a.get("/api/old-store")
        def old_store(p):
            s = core.find_old_store(p.get("folder", ""))
            if not s:
                raise core.UserError("No old QueryBook store found there. Choose the folder that contains language_model.json.")
            return core.old_store_summary(s)

        @a.post("/api/import-old")
        def import_old(p):
            folder = p.get("folder", "")
            if not core.find_old_store(folder):
                raise core.UserError("No old QueryBook store found there. Choose the folder that contains language_model.json.")
            return self.jobs.start("Import from the old store", lambda prog, stop: self.import_old(folder, prog, stop))

        @a.get("/api/old-words")
        def old_words(p):
            return {"total": self.store.scalar("SELECT count(*) FROM old_words", default=0),
                    "top": self.store.query("SELECT word, seen FROM old_words WHERE lang = 'en' ORDER BY seen DESC LIMIT 60")}

        @a.post("/api/old-words/add")
        def old_words_add(p):
            return self.add_old_words(p.get("lang"), max(1, min(200, int(p.get("limit") or 20))))

        @a.get("/api/job")
        def job(p):
            return self.jobs.status()

        @a.post("/api/job/stop")
        def job_stop(p):
            self.jobs.stop()
            return {"ok": True}

        @a.post("/api/backup")
        def backup(p):
            return {"backup": os.path.basename(self.store.backup("manual", force=True) or "")}

        @a.get("/api/backups")
        def backups(p):
            return {"backups": [{"name": b["name"], "kb": b["bytes"] // 1024} for b in self.store.backups()], "folder": self.store.backup_dir}


def _fetch_text(url):
    """One user-chosen page, as text (same polite single fetch as the prototype)."""
    import re, urllib.request, html as _h
    req = urllib.request.Request(url, headers={"User-Agent": "QueryBook-LanguageLab/1.3 (+structural language learning; single manual fetch)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read(3_000_000)
            ctype = r.headers.get("Content-Type", "")
    except Exception as e:
        raise core.UserError("Could not fetch %s: %s" % (url, e))
    m = re.search(r"charset=([\w-]+)", ctype)
    text = raw.decode(m.group(1) if m else "utf-8", "replace")
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = _h.unescape(re.sub(r"<[^>]+>", " ", text))
    return " ".join(text.split())


_fetch = _fetch_text


VENDOR = ["three/three.module.min.js", "three/VRButton.js", "three/LICENSE", "mediapipe/vision_bundle.mjs", "mediapipe/wasm/vision_wasm_internal.js",
          "mediapipe/wasm/vision_wasm_internal.wasm", "mediapipe/face_landmarker.task", "mediapipe/LICENSE"]


def voicedsp_is_wav(b):
    import voicedsp
    return voicedsp.is_wav(b)


def lipread_active_version():
    import lipread
    return lipread.ACTIVE.get("version")


def vendor_missing():
    """Bundled browser libraries (3D face, face tracker) that are missing or empty."""
    d = os.path.join(HERE, "ui", "vendor")
    return [f for f in VENDOR if not os.path.isfile(os.path.join(d, f)) or os.path.getsize(os.path.join(d, f)) < 100]


def bundle_missing():
    """Files of the bundled Windows espeak-ng that are not where they should be."""
    need = ["espeak-ng.exe", "libespeak-ng.dll", "msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"] + [
        "espeak-ng-data/" + f for f in ("phontab", "phonindex", "phondata", "intonations")] + [
        "espeak-ng-data/%s_dict" % c for c in ("en", "es", "fr", "de", "it", "pt", "nl", "sv", "da", "no", "fi", "pl", "cs", "el", "ro", "hu", "ca")] + [
        "espeak-ng-data/voices/!v/whisper", "espeak-ng-data/voices/!v/croak", "espeak-ng-data/voices/!v/grandpa"]
    return [f for f in need if not os.path.isfile(os.path.join(speech.BUNDLED, f))]


def open_app(folder=None):
    return App(folder or core.data_folder(APP_ID, HERE))


# ---------------------------------------------------------------------- self-test
def selftest():
    c = core.Checks()
    c.check("shared core matches the master copy", core.core_matches_master(HERE))
    c.check("verification: code imports only the standard library and its own modules", verify.import_audit()["ok"])
    c.check("verification: every input is declared with a SHA-256", len(verify.inputs_manifest()) >= 7 and all(len(f["sha256"]) == 64 for f in verify.inputs_manifest()))
    import socket as _s
    with verify._NoNetwork() as _net:
        try:
            _s.create_connection(("127.0.0.1", 9), 1)
            blocked = False
        except OSError:
            blocked = True
    c.check("verification: the network block refuses connections", blocked and len(_net.attempts) == 1)
    c.check("17 languages, English first", list(vocab.LANGUAGES)[0] == "en" and len(vocab.LANGUAGES) == 17)
    for code in vocab.OTHERS:
        d = vocab.deck(code)
        c.check("%s word list loaded (%d words)" % (vocab.LANGUAGES[code]["name"], len(d)), len(d) > 1500 and all(w["tr"] for w in d[:50]))
    c.check("most common words come first", vocab.deck("es")[0]["rank"] <= vocab.deck("es")[50]["rank"])
    c.check("junk entries removed", not any(w["en"].startswith("#") for w in vocab.deck("sv")))
    c.check("Webster 1913 definitions loaded", len(vocab.definitions()) > 5000)
    ck = vocab.check_answer
    c.check("typed answer: exact", ck("capacidad", ["capacidad", "habilidad"])["result"] == "correct")
    c.check("typed answer: case and spaces ignored", ck("  Capacidad ", ["capacidad"])["result"] == "correct")
    c.check("typed answer: missing accent forgiven with a note", ck("etre", ["être"])["result"] == "accent")
    c.check("typed answer: one letter off is 'close' (counted wrong)", ck("capacidat", ["capacidad"])["result"] == "close")
    c.check("typed answer: wrong", ck("perro", ["gato"])["result"] == "wrong")
    c.check("speaking similarity", vocab.similarity("buenos días", "buenos dias") == 100 and vocab.similarity("gato", "perro") < 50)
    lk = vocab.lookup("ability")
    c.check("dictionary lookup English", lk["english"] and lk["english"]["translations"]["es"] and lk["english"]["translations"]["pl"] and lk["english"]["definition"])
    c.check("dictionary lookup foreign", any(f["lang"] == "es" and "ability" in f["english"] for f in vocab.lookup("capacidad")["foreign"]))
    with tempfile.TemporaryDirectory() as tmp:
        clock = {"d": "2026-10-16"}
        app = App(os.path.join(tmp, "data"), clock=lambda: clock["d"])
        # object scan: observations saved as numbers, questions answered from them
        sv = app.scan.save({"label": "test walk", "source": "camera", "started": "2026-10-18T09:00:00Z", "seconds": 60, "frames": 600,
                            "tracks": [{"label": "cup", "first_s": 2, "last_s": 9.5, "frames": 70, "score": 0.82, "box": [.1, .2, .1, .1]},
                                       {"label": "person", "first_s": 0, "last_s": 50, "frames": 400, "score": 0.9, "followed": True},
                                       {"label": "dog", "first_s": 1, "last_s": 1.1, "frames": 2, "score": 0.5}]})
        c.check("Object scan: a scan is saved without one-frame glimpses", sv["objects"] == 2 and sv["summary"] == "1 cup, 1 person", sv)
        qa = lambda q: (app.scan.answer(q, 0, {"label": "cup", "score": 0.8}) or {}).get("answer", "")
        c.check("Object scan: when did I last see a mug (synonym)", "from 2.0 s to 9.5 s" in qa("When did I last see a mug?"), qa("When did I last see a mug?"))
        c.check("Object scan: what did I see in session N", qa("what did I see in session %d" % sv["session_id"]).endswith("1 cup, 1 person."))
        c.check("Object scan: no record is said plainly", qa("did I see a dog") == "No, I have no dogs on record.")
        c.check("Object scan: what is this in Spanish", qa("what is this in Spanish") == "That looks like a cup (80% sure). In Spanish: taza or copa.", qa("what is this in Spanish"))
        c.check("Object scan: unrelated questions are left to the other answers", app.scan.answer("how do you say dog in French") is None)
        c.check("Object scan: questions reach Ask by voice", "cup" in app.speech._answer("when did I last see a cup", {"words": [], "language_name": "English"}))
        c.check("Object scan: detector model bundled", os.path.getsize(os.path.join(HERE, "ui", "vendor", "mediapipe", "efficientdet_lite0.tflite")) > 4000000)
        c.check("harvest team attached to the shared database (Commons)", app.team is not None and ("GET", "/api/commons/status") in app.api.routes and ("GET", "/api/harvest/status") in app.api.routes and app.commons.registry.source("webster-1913") is not None
                and app.commons.store.path.startswith(os.environ.get("QB_COMMONS_DATA", "?")))
        app.set_settings("es", 5)
        s = app.session("es", "type")
        c.check("first session offers 5 new words", s["new"] == 5 and s["due"] == 0 and len(s["items"]) == 5, s["new"])
        first = s["items"][0]
        r = app.answer("es", first["en"], "type", "from_native", first["accepted"][0])
        c.check("correct answer moves the word to box 1, due tomorrow", r["correct"] and r["box"] == 1 and r["next_review"] == "2026-10-17", r)
        r2 = app.answer("es", s["items"][1]["en"], "type", "from_native", "zzz")
        c.check("wrong answer stays due today", not r2["correct"] and r2["next_review"] == "2026-10-16")
        for it in s["items"][2:]:
            app.answer("es", it["en"], "cards", "from_native", knew=True)
        s2 = app.session("es", "type")
        c.check("same day: the missed word comes back, no new words beyond the daily limit", s2["due"] == 1 and s2["new"] == 0, (s2["due"], s2["new"]))
        clock["d"] = "2026-10-17"
        s3 = app.session("es", "choice")
        c.check("next day: yesterday's words are due and 5 new words arrive", s3["due"] == 5 and s3["new"] == 5, (s3["due"], s3["new"]))
        ch = s3["items"][0]["choices"]
        c.check("multiple choice has 4 different options including the answer",
                len(ch) == 4 and len({vocab.fold(x) for x in ch}) == 4 and s3["items"][0]["accepted"][0] in ch, ch)
        c.check("choices are the same every time for the same day", app.session("es", "choice")["items"][0]["choices"] == ch)
        sp = app.answer("es", first["en"], "speak", "from_native", first["all_foreign"][0].upper() + "!")
        c.check("speaking: recognised text close enough counts", sp["correct"] and sp["similarity"] >= SPEAK_PASS, sp)
        for _ in range(7):
            app.answer("es", first["en"], "cards", "from_native", knew=True)
        c.check("box never goes beyond the last interval", app.store.scalar("SELECT box FROM cards WHERE word = ?", (first["en"],)) == len(INTERVALS) - 1)
        app.answer("es", first["en"], "type", "from_native", "wrong answer")
        row = app.store.one("SELECT box, lapses FROM cards WHERE word = ?", (first["en"],))
        c.check("forgetting a mastered word sends it back to box 1 and counts a lapse", row["box"] == 1 and row["lapses"] == 1, row)
        app.api.routes[("POST", "/api/custom/add")]({"lang": "es", "target_word": "abuela", "native_word": "grandmother"})
        app.set_settings("es", 10)
        s4 = app.session("es", "type")
        c.check("your own words are taught first", s4["items"] and any(i["custom"] and i["foreign"] == "abuela" and i["new"] for i in s4["items"]),
                [(i["en"], i["new"]) for i in s4["items"]][:3])
        # English as the language learned, by a Spanish speaker
        try:
            app.session("en")
            c.check("English cannot be 'learned' while you speak English", False)
        except core.UserError:
            c.check("English cannot be 'learned' while you speak English", True)
        app.set_native("es")
        e = app.session("en", "type")
        it = e["items"][0]
        c.check("learning English from Spanish: Spanish prompt, English answer", it["prompt"] in vocab.forms("es", it["en"]) and it["accepted"] == [it["en"]], it)
        r = app.answer("en", it["en"], "type", None, it["en"])
        c.check("learning English: correct answer scheduled", r["correct"] and r["next_review"] == add_days(clock["d"], 1))
        e2 = app.session("en", "type", "to_native")
        c.check("learning English: reverse direction asks for the Spanish meaning", e2["items"][0]["prompt"] == e2["items"][0]["en"]
                and e2["items"][0]["accepted"] == vocab.forms("es", e2["items"][0]["en"]))
        c.check("English learner sees the English definition", bool(e["items"][0]["definition"]))
        ch = app.session("en", "choice")["items"][0]["choices"]
        c.check("learning English: multiple choice offers English words", len(ch) == 4 and all(x in vocab.rank() for x in ch), ch)
        c.check("Spanish speaker's own English-Spanish words are kept apart", not any(i["custom"] for i in e["items"]))
        app.set_native("de")
        g = app.session("el", "type")
        c.check("Greek for a German speaker (linked through English)", g["items"] and g["items"][0]["accepted"] == vocab.forms("el", g["items"][0]["en"])
                and g["items"][0]["prompt"] in vocab.forms("de", g["items"][0]["en"]))
        langs = app.language_summary()
        c.check("summary lists English first and marks the spoken language", langs[0]["code"] == "en" and [l["code"] for l in langs if l["is_native"]] == ["de"])
        app.set_native("en")
        c.check("progress report", app.progress("es")["streak"] == 2 and sum(app.progress("es")["boxes"]) >= 5)
        old = os.path.join(tmp, "old")
        os.makedirs(old)
        with open(os.path.join(old, "language_model.json"), "w", encoding="utf-8") as f:
            json.dump({"words": {"ability": 50, "water": 40, "the": 900, "zzzq": 3}, "total_tokens": 993}, f)
        with open(os.path.join(old, "language_model.json.bak"), "w", encoding="utf-8") as f:
            f.write("{damaged")
        before = open(os.path.join(old, "language_model.json"), encoding="utf-8").read()
        res = app.import_old(old, lambda *a: None, lambda: False)
        c.check("old language model words recorded (damaged backup file skipped)", res["words_recorded"] == 4 and res["language_model_files"] == 1, res)
        c.check("old store untouched", open(os.path.join(old, "language_model.json"), encoding="utf-8").read() == before)
        added = app.add_old_words("es", 10)
        c.check("old store's most-seen words with a translation join the lessons", added["added"] >= 1, added)
        c.check("database integrity", app.store.scalar("PRAGMA integrity_check") == "ok")
        c.check("user interface present", os.path.exists(os.path.join(HERE, "ui", "index.html")))
        # a database from version 1.0/1.1 is upgraded in place, keeping your own words
        import sqlite3
        v1 = os.path.join(tmp, "v1")
        os.makedirs(v1)
        db = sqlite3.connect(os.path.join(v1, APP_ID + ".sqlite"))
        db.executescript(SCHEMA[0] + ";CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);INSERT INTO meta VALUES('schema_version','1');"
                         "INSERT INTO custom_words(lang, english, foreign_word, note, created) VALUES('fr','grandmother','grand-mère',NULL,'x');"
                         "INSERT INTO settings VALUES('fr', 7, 'to_english');")
        db.close()
        up = App(v1, clock=lambda: clock["d"])
        c.check("older database upgraded: your own words kept", up.store.meta_get("schema_version") == str(len(SCHEMA)) and
                up.store.scalar("SELECT count(*) FROM custom_pairs WHERE target_word = 'grand-mère' AND native = 'en'") == 1)
        c.check("older settings understood", up.settings("fr") == {"new_per_day": 7, "direction": "to_native"})
    # Language Lab: same logic as prototype v9.50 — sub-language first, gate, then meaning
    with tempfile.TemporaryDirectory() as tmp:
        app = App(os.path.join(tmp, "data"))
        L = app.lab
        try:
            L.ground_words(["water"])
            c.check("Lab: meaning is refused before the Transition Gate opens", False)
        except lab.GateClosed:
            c.check("Lab: meaning is refused before the Transition Gate opens", True)
        cycles = 0
        while not L.gate_open() and cycles < 200:
            L.learn(lab.C.corpus_chunk(cycles), "test")
            cycles += 1
        stt = L.status()
        c.check("Lab: starter text opens the gate the same way as the prototype (36 cycles)", cycles == 36 and all(v["pass"] for v in stt["gate"]["checks"].values()), cycles)
        g = L.ground_words(L.learned_words(400))
        c.check("Lab: Phase 2 grounds learned words in the 1913 dictionary", g["words_grounded"] > 50 and L.word_card("water")["facts"])
        a3 = L.acquire_language("es", L.learned_words(400))
        c.check("Lab: Phase 3 maps learned words to another language", a3["mapped"] > 50)
        sp = L.speech_analyze(L.learned_words(50), "en")
        c.check("Lab: Phase 4 pronunciation of learned words", sp["analyzed"] > 20 and L.analyze_pronunciation("phonics")["ipa"] == "/fɒnɪks/")
        ll = L.learn_language("es", L.corpus_words("es")[:120])
        c.check("Lab: learns another language's words with meanings and pronunciation", ll["vocab_added"] > 100 and ll["pron_added"] > 100)
        old = {"words": {"the": 10, "cat": 2}, "total_tokens": 12, "gate_opened": False}
        c.check("Lab: an old model is not merged over learning already done", not L.adopt_old_model(old, "x")["adopted"])
        L.forget()
        c.check("Lab: continues from the old prototype's English model when starting fresh", L.adopt_old_model(old, "x")["adopted"] and L.load_model()["total_tokens"] == 12)
    st = speech.status()
    c.check("offline voice (espeak-ng): %s" % ("found" if st["espeak"] else "not installed — browser voices are used"), True)
    c.check("Default voice: the bundled espeak-ng 1.51 (Windows) is complete — program, runtime, 17 languages, variants", not bundle_missing(), ", ".join(bundle_missing()[:5]))
    if speech.find_espeak() and not speech.bundled_in_use():
        import subprocess as _sp
        okl = []
        for code, v in vocab.LANGUAGES.items():
            r = _sp.run([speech.find_espeak(), "--path=" + speech.BUNDLED, "-q", "--ipa", "-v", v["espeak"], "test"], capture_output=True, timeout=20)
            okl.append(r.returncode == 0 and r.stdout.strip() and not r.stderr.strip())
        c.check("Default voice: the bundled data speaks all 17 languages (checked with this computer's espeak-ng)", all(okl), sum(okl))
    if speech.find_espeak():
        import struct as _st
        w = speech.speak_wav("Testing the default voice.", "en-us")
        c.check("Default voice: audio is written through a file (whole 16-bit samples, true length in the header)",
                w and (len(w) - 44) % 2 == 0 and _st.unpack("<I", w[40:44])[0] == len(w) - 44)
        damaged = w[:44] + w[44:].replace(b"\n", b"\r\n")             # what Windows text mode did to stdout audio
        try:
            speech.check_wav(damaged)
            c.check("Default voice: audio damaged by Windows text mode is refused, never played", False)
        except RuntimeError:
            c.check("Default voice: audio damaged by Windows text mode is refused, never played", True)
    _speech_selftest(c)
    _viseme_selftest(c)
    _coach_selftest(c)
    _persona_selftest(c)
    _photoreal_selftest(c)
    _silent_selftest(c)
    _vse_selftest(c)
    return c.report(APP_NAME)


def _vse_selftest(c):
    """Visual Speech Engine (stage 1): audio analysis, lip-sync motion, lip reading, face analysis, determinism."""
    import voicedsp
    wav = voicedsp.formant_wav(["pæt", "mɛt", "bʌb"])
    a = vse.aps(wav, "pat met bob")
    c.check("VSE audio: phoneme timeline with times", len(a["phonemes"]["phonemes"]) >= 6 and all(p["end_time"] > p["start_time"] for p in a["phonemes"]["phonemes"]))
    c.check("VSE audio: prosody at 100 frames per second", abs(len(a["prosody"]["frames"]) - int(a["measure"]["analysed_s"] * 100)) <= 1)
    c.check("VSE audio: 8-dimension emotion vector", all(k in a["emotion"] for k in vse.EMOTION_KEYS))
    e1, e2 = a["speaker_embedding"], vse.speaker_embedding(voicedsp.formant_wav(["pæt", "mɛt", "bʌb"], f0=230.0))
    c.check("VSE audio: voice fingerprint (same voice 1.0, a different pitch lower)", e1 and len(e1) == 50 and vse.cosine(e1, e1) > 0.999 and vse.cosine(e1, e2) < 0.999,
            vse.cosine(e1, e2))
    tr = vse.timing_from_text("bob you")
    ls = vse.lip_sync(tr, None, None, fps=100, seed="t")
    fr = ls["motion"]["frames"]
    pp = [s_ for s_ in tr["visemes"] if s_["v"] == "PP"]
    mid = lambda s_: fr[int((s_["start"] + s_["end"]) / 2 * 100)]["mouth"]
    c.check("VSE lip sync: every p, b and m closes the lips", pp and all(mid(s_)[0] < 0.02 for s_ in pp), [round(mid(s_)[0], 3) for s_ in pp])
    u = next(s_ for s_ in tr["visemes"] if s_["v"] == "U")
    pk = vse.PARAMS.index("mouthPucker")
    c.check("VSE lip sync: lips round ahead of 'oo' (coarticulation)", fr[int((u["start"] - 0.03) * 100)]["mouth"][pk] > 0.3 * vse.TARGETS["U"][pk])
    c.check("VSE lip sync: deterministic", json.dumps(vse.lip_sync(tr, None, None, fps=100, seed="t")) == json.dumps(ls))
    c.check("VSE lip sync: ARKit blendshape export", vse.arkit_csv(ls["motion"]).startswith("time_s,jawOpen,mouthClose"))
    rnd = vse._rng("selftest")
    spk = {"scale": 1.0, "offset": [0.0] * len(vse.PARAMS), "rate": 4.5, "noise": 0.02, "jitter": 0.0, "fps": 30}
    frames, truth, _ = vse.synthetic_frames("please open the window", spk, rnd)
    right = vse.lip_read(frames, "en", (), "please open the window")["script"]["agreement"]
    wrong = vse.lip_read(frames, "en", (), "we love music and books")["script"]["agreement"]
    c.check("VSE lip reading: the right script scores far above a wrong one", right >= 60 and right - wrong >= 30, (right, wrong))
    got = vse.lip_read(frames, "en", ("please", "open", "the", "window"))["lipread"]["text"].split()
    ok = sum(1 for w in got if w in ("please", "open", "the", "window"))
    c.check("VSE lip reading: reads at least half the words of a clear clip", ok >= 2, got)
    v = vse.vps([{"t": i / 30, "face": True, "pose": [5, -2, 1, 0, 0, -50], "box": [0.5, 0.5, 0.4], "sh": [0.6, 0.1, 0.05, 0.3],
                  "geo": [1.0 + 0.001 * (i % 3)] * 19} for i in range(40)])
    c.check("VSE face analysis: pose, camera, lighting, identity", v["head_pose_deg"]["yaw"]["mean"] == 5 and v["camera_motion"]["verdict"] == "steady"
            and v["lighting_sh1"]["from"] == "front" and v["identity"]["same_face_throughout"] is True, v)
    eng = vse.Engine()
    j = eng.submit("lip_sync", lambda prog: vse.lip_sync(vse.timing_from_text("hello there"), fps=30))
    for _ in range(200):
        if eng.status(j["job_id"])["status"] in ("completed", "failed"):
            break
        time.sleep(0.02)
    c.check("VSE jobs: a lip-sync job runs in the background and completes", eng.status(j["job_id"])["status"] == "completed")


def _coach_selftest(c):
    """The ingestion reservoir learns: a speaker whose mouth moves more subtly than the rules expect is read far
    better after teaching, proven on held-back recordings; versions roll back; the reservoir exports and imports."""
    import random, lipread as LR
    if not speech.find_espeak():
        c.check("Learning: skipped (needs espeak-ng to speak the teaching sentences)", True)
        return
    subtle = {"P": (0.01, {"mouthClose": 0.15, "mouthPressLeft": 0.2, "mouthPressRight": 0.2}), "F": (0.03, {"mouthRollLower": 0.22, "mouthUpperUpLeft": 0.2, "mouthUpperUpRight": 0.2}),
              "W": (0.09, {"mouthFunnel": 0.22, "mouthPucker": 0.25}), "A": (0.2, {"jawOpen": 0.26}),
              "E": (0.07, {"mouthSmileLeft": 0.18, "mouthSmileRight": 0.18, "mouthStretchLeft": 0.12, "mouthStretchRight": 0.12}),
              "T": (0.06, {"jawOpen": 0.08}), "-": (0.01, {"mouthClose": 0.1})}

    def frames_for(text, wav, seed):
        rnd, tr, out = random.Random(seed), visemes.align(text, wav, "en"), []
        for i in range(int(tr["duration"] * 30)):
            v = next((x["v"] for x in tr["visemes"] if x["start"] <= i / 30 < x["end"]), "sil")
            g, b = subtle[LR.FROM_VISEME[v]]
            out.append({"t": i / 30, "face": True, "gap": max(0, g + rnd.gauss(0, 0.01)), "bs": {k: max(0, x + rnd.gauss(0, 0.03)) for k, x in b.items()},
                        "mouth_px": 170, "face_h": 0.5, "yaw": 3, "pitch": 2, "light": 0.5})
        return out
    info = {"width": 1920, "height": 1080, "fps": 60}
    saved = dict(LR.ACTIVE)
    try:
        with tempfile.TemporaryDirectory() as d:
            inst = App(d)
            C = inst.coach
            dep = [C.deposit(frames_for(t, w, k), t, "en", "teach", w, info=info) for k, (t, w) in
                   enumerate((t, speech.speak_wav(t, "en-us")) for t in lipcoach.TEACH)]
            c.check("Learning: teaching recordings go into the ingestion reservoir (speech-visual), about 1 in 4 held back",
                    all(r["stored"] and r["domain"] == "speech-visual" for r in dep) and 1 <= sum(r["split"] == "test" for r in dep) <= 6)
            again = C.deposit(frames_for(lipcoach.TEACH[0], speech.speak_wav(lipcoach.TEACH[0], "en-us"), 0), lipcoach.TEACH[0], "en", "teach",
                              speech.speak_wav(lipcoach.TEACH[0], "en-us"), info=info)
            c.check("Learning: the same recording is not stored twice", not again["stored"])
            long_w = speech.speak_wav("Many people met at the warm mountain lake and talked about the weather for a long time.", "en-us")
            wrong_ = C.deposit(frames_for("Hi.", long_w, 5), "Hi.", "en", "teach", long_w, info=info)
            c.check("Learning: a recording that is not the sentence (wrong line read) is kept out of the reservoir", not wrong_["stored"] and "syllables" in wrong_["reason"], wrong_)
            while C.training:
                time.sleep(0.1)
            m = C.train()["metrics"]
            c.check("Learning: the learned reader beats the built-in rules on held-back recordings and is switched on",
                    m["reader_switched_on"] and m["learned_accuracy"] >= m["rules_accuracy"] + 0.3, "%s vs %s" % (m["learned_accuracy"], m["rules_accuracy"]))
            c.check("Learning: lips agree better with the true words after learning (held-back recordings)",
                    m["agreement_learned"] >= m["agreement_rules"] + 15, "%s vs %s" % (m["agreement_learned"], m["agreement_rules"]))
            new = "My brave father was very happy to see you."
            fr = frames_for(new, speech.speak_wav(new, "en-us"), 99)
            right, rules = LR.script_agreement(LR.classes_of(fr)[0], new)["agreement"], LR.script_agreement(LR.classes_of(fr, model="rules")[0], new, costs={})["agreement"]
            wrong = LR.script_agreement(LR.classes_of(fr)[0], "the cat sat on a big brown log today")["agreement"]
            c.check("Learning: on a new sentence the right words now agree and wrong words still do not", right >= rules + 20 and wrong < 25, (rules, right, wrong))
            c.check("Learning: the talking face gets mouth shapes learned from real mouths", len(C.mouth) >= 3)
            v = LR.ACTIVE["version"]
            C.use("rules")
            off = LR.ACTIVE["model"] is None
            C.use(v)
            c.check("Learning: any version can be switched off (rules only) and back on", off and LR.ACTIVE["version"] == v and LR.ACTIVE["model"])
            m2 = C.train()["metrics"]
            c.check("Learning: same reservoir, same result (deterministic)", m2["learned_accuracy"] == m["learned_accuracy"] and m2["agreement_learned"] == m["agreement_learned"])
            al = []                                        # timing: recordings whose exact word times follow other weights
            for k, t in enumerate(lipcoach.TEACH[:6]):
                w = speech.speak_wav(t, "en-us")
                visemes.WEIGHT.update({"vowel": 1.6, "long": 2.4, "cons": 0.36}); visemes.WORD_BASE = 0.6
                exact = [{"word": x["word"], "start_s": x["start"], "end_s": x["end"]} for x in visemes.align(t, w, "en")["words"]]
                visemes.WEIGHT.clear(); visemes.WEIGHT.update(visemes.DEFAULT_WEIGHT); visemes.WORD_BASE = visemes.DEFAULT_WORD_BASE
                al.append({"id": k, "text": t, "lang": "en", "audio": inst.speech._save_audio(w, "teach"), "word_times": json.dumps(exact)})
            _, am = C._tune_align(al)
            c.check("Learning: lip-sync timing weights are tuned from exact word times (error goes down)", am["improved"] and am["after_ms"] < am["before_ms"], am)
            ex = C.export()
            other = App(os.path.join(d, "second-computer"))
            imp = other.coach.import_(ex)
            m3 = other.coach.train()["metrics"]
            c.check("Learning: the reservoir exports and imports (pooling between computers) and learns there too",
                    imp["added"] == len(lipcoach.TEACH) and m3["reader_switched_on"] and "frames" in json.dumps(ex) and ex["rows"] and "audio" not in ex["rows"][0])
    finally:
        LR.ACTIVE.clear(); LR.ACTIVE.update(saved)
        visemes.WEIGHT.clear(); visemes.WEIGHT.update(visemes.DEFAULT_WEIGHT); visemes.WORD_BASE = visemes.DEFAULT_WORD_BASE


def _persona_selftest(c):
    """Author Narrator: consent rules, voice by clone or offline match, video by HeyGen, D-ID or a local model —
    every cloud request checked against a stand-in server; keys never logged."""
    import http.server, threading as _th
    if not speech.find_espeak():
        c.check("Author narrator: skipped (needs espeak-ng)", True)
        return
    seen = {"paths": [], "auth": []}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj, ctype="application/json"):
            body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
            self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n)
            seen["paths"].append(self.path); seen["auth"].append(self.headers.get("xi-api-key") or self.headers.get("X-Api-Key") or self.headers.get("Authorization"))
            if self.path == "/v1/voices/add":
                return self._send({"voice_id": "VOICE123"} if b"sample.wav" in body else {"detail": "no file"})
            if self.path == "/v1/talking_photo":
                return self._send({"data": {"talking_photo_id": "TP1"}})
            if self.path == "/v1/asset":
                return self._send({"data": {"id": "AS1"}})
            if self.path == "/v2/video/generate":
                b = json.loads(body)
                ok = b["video_inputs"][0]["character"]["talking_photo_id"] == "TP1" and b["video_inputs"][0]["voice"]["audio_asset_id"] == "AS1"
                return self._send({"data": {"video_id": "VID1" if ok else "BAD"}})
            if self.path in ("/images", "/audios"):
                return self._send({"url": "s3://stand-in" + self.path})
            if self.path == "/talks":
                b = json.loads(body)
                return self._send({"id": "TLK1" if b["source_url"] == "s3://stand-in/images" and b["script"]["audio_url"] == "s3://stand-in/audios" else "BAD"})
            self._send({"error": "no route"})

        def do_GET(self):
            seen["paths"].append(self.path)
            if self.path.startswith("/v1/video_status.get"):
                seen["polls"] = seen.get("polls", 0) + 1
                return self._send({"data": {"status": "completed", "video_url": base + "/files/v.mp4"} if seen["polls"] > 1 else {"status": "processing"}})
            if self.path == "/talks/TLK1":
                return self._send({"status": "done", "result_url": base + "/files/d.mp4"})
            if self.path.startswith("/files/"):
                return self._send(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 3000, "video/mp4")
            self._send({"error": "no route"})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    _th.Thread(target=srv.serve_forever, daemon=True).start()
    env = {k: base for k in ("QB_TTS_BASE_ELEVENLABS", "QB_TTS_BASE_HEYGEN", "QB_TTS_BASE_HEYGEN_UPLOAD", "QB_TTS_BASE_DID")}
    env["QB_POLL_S"] = "0.05"
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        with tempfile.TemporaryDirectory() as d:
            inst = App(d)
            P = inst.personas
            sample = speech.speak_wav("This is the author reading a passage aloud so that the narrator can learn the voice. " * 3, "en-us")
            photo = b"\xff\xd8\xff\xe0" + b"\x00" * 2000
            for args, why in (((("Ada Author", "Ada Author", False, photo, sample)), "consent box"), (("Ada Author", "Someone Else", True, photo, sample), "signer is not the author"),
                              (("Ada Author", "Ada Author", True, photo, speech.speak_wav("Too short.", "en-us")), "short sample")):
                try:
                    P.create(*args)
                    c.check("Author narrator: refused without proper consent (%s)" % why, False)
                except ValueError:
                    c.check("Author narrator: refused without proper consent (%s)" % why, True)
            pe = P.create("Ada Author", "Ada Author", True, photo, sample, landmarks=[[0.5, 0.5]] * 478)
            cons = pe["consent"]
            import hashlib as _h
            c.check("Author narrator: consent recorded with signer, date, statement and fingerprints of both samples",
                    cons["signer"] == "Ada Author" and cons["date_utc"] and "AI-generated" in cons["statement"] and cons["photo_sha256"] == _h.sha256(photo).hexdigest()
                    and cons["sample_sha256"] == _h.sha256(sample).hexdigest())
            v = P.set_voice(pe["id"], "offline")
            c.check("Author narrator: offline voice tuned to the author's sample (pitch, speed, loudness)", v["engine"] == "espeak" and v["profile"] and v["target"]["pitch_hz"] > 50)
            inst.speech.keys.save("elevenlabs", {"api_key": "el-TESTKEY-0123456789"})
            v = P.set_voice(pe["id"], "elevenlabs")
            c.check("Author narrator: ElevenLabs voice clone made from the sample (stand-in server)", v["voice"] == "VOICE123" and "/v1/voices/add" in seen["paths"])
            P.set_voice(pe["id"], "offline")
            r = P.narrate(pe["id"], "Welcome to my book. Let me read the first chapter to you.")
            c.check("Author narrator: photo narration returns the voice and the timed mouth track at once", r["status"] == "done" and r["audio"] and len(r["track"]["visemes"]) > 10 and "AI narrator" in r["label"])

            def wait(nid):
                for _ in range(200):
                    n = P.narration(nid)
                    if n["status"] in ("done", "failed"):
                        return n
                    time.sleep(0.05)
                return P.narration(nid)
            inst.speech.keys.save("heygen", {"api_key": "hg-TESTKEY-0123456789"})
            inst.speech.keys.save("did", {"api_key": "did-TESTKEY-0123456789"})
            P.set_face(pe["id"], "heygen")
            n1 = wait(P.narrate(pe["id"], "This chapter is about rivers.")["id"])
            c.check("Author narrator: HeyGen talking-photo video made, polled and saved (stand-in server)",
                    n1["status"] == "done" and n1["video"] and os.path.getsize(P.file_path(pe["id"], n1["video"])) > 1000 and "/v2/video/generate" in seen["paths"], n1["detail"])
            n2 = wait(P.narrate(pe["id"], "This chapter is about rivers.", "did")["id"])
            c.check("Author narrator: D-ID talk video made and saved (stand-in server)", n2["status"] == "done" and n2["video"] and "/talks" in seen["paths"], n2["detail"])
            script = os.path.join(d, "fake model.py")
            with open(script, "w") as f:
                f.write("import sys, os\nface, audio, out = sys.argv[1:4]\nassert os.path.getsize(face) > 0 and os.path.getsize(audio) > 0\n"
                        "open(out, 'wb').write(bytes(5000))\n")
            P.set_face(pe["id"], "local", {"command": '"%s" "%s" {face} {audio} {out}' % (sys.executable, script)})
            n3 = wait(P.narrate(pe["id"], "This chapter is about rivers.")["id"])
            c.check("Author narrator: a local model (Wav2Lip-style command, paths with spaces) makes the video", n3["status"] == "done" and n3["video"], n3["detail"])
            script2 = os.path.join(d, "folder_model.py")
            with open(script2, "w") as f:
                f.write("import sys, os\nd = os.path.join(sys.argv[1], 'run'); os.makedirs(d)\nopen(os.path.join(d, 'result.mp4'), 'wb').write(bytes(5000))\n")
            P.set_face(pe["id"], "local", {"command": '"%s" "%s" {outdir}' % (sys.executable, script2)})
            n4 = wait(P.narrate(pe["id"], "This chapter is about rivers.")["id"])
            c.check("Author narrator: a model that writes into a folder (SadTalker-style) is found", n4["status"] == "done", n4["detail"])
            P.set_face(pe["id"], "local", {"command": '"%s" -c "import sys; sys.exit(3)"' % sys.executable})
            n5 = wait(P.narrate(pe["id"], "This chapter is about rivers.")["id"])
            c.check("Author narrator: a failing model is reported, not hidden", n5["status"] == "failed" and "exit 3" in n5["detail"])
            logs = json.dumps(inst.store.query("SELECT * FROM qb_activity")) + json.dumps(inst.speech.history(500)) + json.dumps(inst.store.query("SELECT * FROM narrations"))
            c.check("Author narrator: no provider key appears in any log", not any(k in logs for k in ("el-TESTKEY", "hg-TESTKEY", "did-TESTKEY")))
            dl = P.delete(pe["id"])
            c.check("Author narrator: deleting a persona removes its samples and narrations", dl["deleted"] and not os.path.isdir(os.path.join(P.dir, str(pe["id"]))) and not inst.store.query("SELECT 1 FROM narrations"))
    finally:
        srv.shutdown()
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _photoreal_selftest(c):
    """Photo Real Lab: one perfect sample → the author's mouth model → any rendering measured against what the
    author would do for the same words; the gate catches bad sync and wrong shapes; calibration converges; the
    proven settings hold for new text; findings are QueryBook (UFCS) fact packets."""
    import math as _m, random as _r
    if not speech.find_espeak():
        c.check("Photo Real Lab: skipped (needs espeak-ng)", True)
        return
    author = {"gap_gain": 1.0, "width_gain": 1.0, "lead_ms": 70, "smooth_ms": 45, "closure_hold_ms": 60, "blink_per_min": 17, "head_sd_deg": 1.2,
              "shapes": {"PP": {"gap": 0.0, "width": 0.36}, "FF": {"gap": 0.05, "width": 0.38}, "aa": {"gap": 0.55, "width": 0.40}, "E": {"gap": 0.3, "width": 0.43},
                         "I": {"gap": 0.16, "width": 0.45}, "O": {"gap": 0.42, "width": 0.31}, "U": {"gap": 0.18, "width": 0.27}, "DD": {"gap": 0.16, "width": 0.38},
                         "kk": {"gap": 0.22, "width": 0.38}, "SS": {"gap": 0.08, "width": 0.41}, "nn": {"gap": 0.12, "width": 0.38}, "RR": {"gap": 0.15, "width": 0.33},
                         "CH": {"gap": 0.14, "width": 0.32}, "TH": {"gap": 0.13, "width": 0.38}}}

    def render(params, track, seed, noise=0.01):
        """What the face tracker reads from a face driven like photoface.js (the same model: lead, response, shapes)."""
        rnd, st, out = _r.Random(seed), {"gap": 0.0, "w": 0.37, "t": None, "closed": -1}, []
        for i in range(int(track["duration"] * 30)):
            t = i / 30.0
            tt = t + params["lead_ms"] / 1000.0
            v = next((x["v"] for x in track["visemes"] if x["start"] <= tt < x["end"]), "sil")
            sh = params["shapes"].get(v)
            g, w = (sh["gap"] * params["gap_gain"], sh["width"] * params["width_gain"]) if sh else (0.02 * params["gap_gain"], 0.37)
            if v == "PP":
                st["closed"] = tt + params.get("closure_hold_ms", 0) / 1000.0
            if tt < st["closed"]:
                g = 0
            dt = 1 / 30.0 if st["t"] is None else t - st["t"]
            st["t"] = t
            a = 1 - _m.exp(-dt / max(0.005, params["smooth_ms"] / 1000.0))
            st["gap"] += (g - st["gap"]) * a; st["w"] += (w - st["w"]) * a
            rot = params["head_sd_deg"] * (0.8 * _m.sin(t * 0.53) + 0.6 * _m.sin(t * 1.31 + 1.1))
            out.append({"t": t, "face": True, "gap": max(0, st["gap"] + rnd.gauss(0, noise)), "mouth_px": st["w"] * 0.5 * 720, "face_h": 0.5,
                        "yaw": rot, "pitch": rot * 0.6, "bs": {"jawOpen": st["gap"] * 0.8}})
        return out
    info = {"width": 1920, "height": 720, "fps": 30}
    text = photoreal.REFERENCE_PASSAGE
    wav = speech.speak_wav(text, "en-us")
    track = visemes.align(text, wav, "en")
    with tempfile.TemporaryDirectory() as d:
        inst = App(d)
        L, P = inst.prlab, inst.personas
        pe = P.create("Ada Author", "Ada Author", True, b"\xff\xd8" + b"\x00" * 100,
                      speech.speak_wav("This is the author reading a passage aloud for the narrator. " * 5, "en-us"))
        ref = L.set_reference(pe["id"], render(author, track, 1), wav, text, "en", info)
        md = ref["model"]
        c.check("Photo Real Lab: the perfect sample becomes the author's mouth model (lead, response time, a shape per sound)",
                abs(md["tau_ms"] - 45) <= 15 and abs(md["lead_ms"] - 70) <= 30 and md["explained"] >= 0.8 and len(md["gap"]) >= 12, md)
        take2 = L.measure(pe["id"], render(author, track, 2), wav, text, "real footage (second take)", "en", info)["score"]
        c.check("Photo Real Lab: a second take of the real author passes the gate", take2["passed"], take2["verdict"])
        bad = L.measure(pe["id"], render(dict(author, lead_ms=-80), track, 3), wav, text, "bad sync", "en", info)["score"]
        flat = L.measure(pe["id"], render(dict(author, gap_gain=0.35), track, 4), wav, text, "flat mouth", "en", info)["score"]
        c.check("Photo Real Lab: bad sync and a flat mouth fail, each on the right dimension",
                not bad["passed"] and any("timing" in f for f in bad["failed"]) and not flat["passed"] and any("lip opening" in f for f in flat["failed"]))
        params = dict(photoreal.DEFAULT_PARAMS, shapes={v: {"gap": x["gap"] * 0.6, "width": x["width"] * 1.15} for v, x in author["shapes"].items()}, lead_ms=0, smooth_ms=120)
        rounds = 0
        for rounds in range(1, 7):
            r = L.calibrate(pe["id"], render(params, track, 10 + rounds), wav, text, params, "en", info, rounds)
            if r["passed"]:
                break
            params = r["next_params"]
        c.check("Photo Real Lab: calibration takes a wrongly set renderer to PASS (closed loop)", r["passed"] and rounds <= 4, "%d rounds" % rounds)
        new = "Please bring the big map to the meeting tomorrow morning, and thank you for your help."
        w2 = speech.speak_wav(new, "en-us")
        t2 = visemes.align(new, w2, "en")
        nt = L.measure(pe["id"], render(params, t2, 21), w2, new, "photo", "en", info)["score"]
        c.check("Photo Real Lab: the proven settings pass on new words never seen in the reference", nt["passed"], nt["verdict"])
        f = L.findings(pe["id"])
        c.check("Photo Real Lab: findings rank the methods by pass rate and name their failures",
                f["methods"][0]["pass_rate"] >= f["methods"][-1]["pass_rate"] and any(m["most_common_failures"] for m in f["methods"]))
        row = L.graph(limit=1)[0]
        import hashlib as _h
        fp = _h.sha256("|".join([" ".join(str(x).strip().lower().split()) for x in (row["subject"], row["predicate"], row["object"])] + ["+"]).encode()).hexdigest()
        lines = L.export_ufcs().strip().split("\n")
        pk = json.loads(lines[0])
        kf = inst.personas.get(pe["id"])["reference"]["keyframes"]
        mdl_g = md["gap"]
        frames_ref = render(author, track, 1)
        lead = md["lead_ms"] / 1000.0
        good = 0
        for v_, t_ in kf.items():
            if v_ in ("rest", "blink"):
                continue
            f_ = min(frames_ref, key=lambda f: abs(f["t"] - t_))
            seg = [x for x in track["visemes"] if x["v"] == v_ and x["start"] <= t_ + lead <= x["end"]]
            good += bool(seg) and abs(f_["gap"] - mdl_g[v_]) < 0.08
        c.check("Photo Real Lab: the real-mouth library picks, for each sound, a frame inside that sound that matches the author's model",
                "rest" in kf and good >= 0.8 * (len(kf) - 1 - ("blink" in kf)), "%d of %d" % (good, len(kf)))
        lm = [[0.5, 0.5]] * 478
        jpg = "data:image/jpeg;base64," + __import__("base64").b64encode(b"\xff\xd8\xff\xe0" + bytes(500)).decode()
        lib = P.set_library(pe["id"], [{"v": v_, "image_b64": jpg, "landmarks": lm} for v_ in kf] + [{"v": "nonsense", "image_b64": jpg, "landmarks": lm}])
        c.check("Photo Real Lab: the library stores the author's own frames (only the chosen ones)", lib["count"] == len(kf) and "nonsense" not in lib["frames"])
        closed = [[0.5, 0.5]] * 478
        closed[13], closed[14], closed[61], closed[291], closed[1], closed[234], closed[454] = [0.5, 0.60], [0.5, 0.605], [0.4, 0.6], [0.6, 0.6], [0.5, 0.45], [0.3, 0.45], [0.7, 0.45]
        opened = [list(x) for x in closed]; opened[14] = [0.5, 0.66]
        c.check("Author narrator: the photo check flags an open mouth and passes a closed one",
                persona.photo_check(closed) == [] and any("open" in x for x in persona.photo_check(opened)))
        c.check("Photo Real Lab: every finding is a UFCS 1.0 fact packet with the QueryBook store's fingerprint",
                row["fingerprint"] == fp and pk["ufcs_version"] == "1.0" and pk["domain"] == "photoreal" and len(lines) == f["facts"])


def _silent_selftest(c):
    """Silent questions: a question mouthed without sound is matched to the questions QueryBook answers; in guided
    mode the mouthed word is found among the words that look alike."""
    import lipread as LR
    if not speech.find_espeak():
        c.check("Silent questions: skipped (needs espeak-ng)", True)
        return
    bs = {"P": (0.0, {"mouthClose": 0.4}), "F": (0.02, {"mouthRollLower": 0.5}), "W": (0.15, {"mouthPucker": 0.6}), "A": (0.45, {"jawOpen": 0.6}),
          "E": (0.12, {"mouthStretchLeft": 0.4, "mouthStretchRight": 0.4}), "T": (0.1, {}), "-": (0.0, {"mouthClose": 0.3})}

    def mouthed(text):
        tr, out = visemes.align(text, speech.speak_wav(text, "en-us"), "en"), []
        for i in range(int(tr["duration"] * 30)):
            t = i / 30.0
            v = next((x["v"] for x in tr["visemes"] if x["start"] <= t < x["end"]), None)
            v = v or min(tr["visemes"], key=lambda x: min(abs(t - x["start"]), abs(t - x["end"])))["v"]
            g, b = bs[LR.FROM_VISEME[v]]
            out.append({"t": t, "face": True, "gap": g, "bs": b})
        return LR.classes_of(out)[0]
    hits = 0
    for w in ("house", "money", "time", "water", "good"):
        r = silent.decode_word(mouthed(w))
        hits += any(w == x["word"] or w in x["same_on_lips"] for x in r["readings"][:5])
    c.check("Silent questions (guided): the mouthed word is among the top 5 look-alike groups", hits >= 4, "%d of 5" % hits)
    q = "translate time to italian"
    r = silent.decode(mouthed(q))
    top = [x["question"].lower() for x in r["readings"]]
    c.check("Silent questions: a mouthed question is matched to the right pattern and offered among the top readings",
            q in top and r["readings"][0]["pattern"] == "translate", top[:3])


def _viseme_selftest(c):
    """Lip-sync: sounds map to the right mouth shapes, the track is ordered and covers the audio, exports are well formed."""
    import voicedsp as V
    vs = [v for _, v, _ in visemes.phonemes("pʌtʃ fɪʃ θɪŋk")]
    c.check("Lip-sync: p → lips pressed, tʃ → CH, f → FF, θ → TH", vs[0] == "PP" and "CH" in vs and "FF" in vs and "TH" in vs, vs)
    text = "Hello there. Welcome to the talking face."
    wav = speech.speak_wav(text, "en-us") if speech.find_espeak() else V.tone_wav(f0=140, seconds=3, gaps=((1.2, 1.5),))
    tr = visemes.align(text, wav, "en")
    seq = tr["visemes"]
    c.check("Lip-sync: every word timed, in order", len(tr["words"]) == 7 and all(a["end"] <= b["start"] + 1e-6 for a, b in zip(tr["words"], tr["words"][1:])))
    c.check("Lip-sync: mouth shapes in order, inside the audio", seq and all(v["start"] <= v["end"] for v in seq) and
            all(a["start"] <= b["start"] for a, b in zip(seq, seq[1:])) and seq[-1]["end"] <= tr["duration"] + 0.01)
    c.check("Lip-sync: jaw curve at 100 per second covers the audio", abs(len(tr["jaw"]) - tr["duration"] * 100) <= 2 and max(tr["jaw"]) <= 1)
    rh = visemes.rhubarb_tsv(tr).strip().split("\n")
    c.check("Lip-sync: Rhubarb export ends at rest (X)", rh[-1].endswith("\tX") and all(len(r.split("\t")) == 2 for r in rh))
    cs = visemes.csv_text(tr).strip().split("\n")
    c.check("Lip-sync: CSV export has a header and one row per sound", cs[0].startswith("start_s,") and len(cs) - 1 == len(tr["phonemes"]))
    c.check("Face & video: bundled 3D library and face tracker present", not vendor_missing(), ", ".join(vendor_missing()))
    # lip-reading and sync on frames made from a known track
    import lipread as LR
    BS = {"P": (0.0, {"mouthClose": 0.4}), "F": (0.02, {"mouthRollLower": 0.5}), "W": (0.15, {"mouthPucker": 0.6}), "A": (0.45, {"jawOpen": 0.6}),
          "E": (0.12, {"mouthStretchLeft": 0.4, "mouthStretchRight": 0.4}), "T": (0.1, {}), "-": (0.0, {"mouthClose": 0.3})}
    c.check("Lip-reading: each mouth shape is read from the face's blendshapes",
            all(LR.frame_class({"gap": g, "bs": b}) == (k if k != "-" else "P") for k, (g, b) in BS.items()))
    said = "hello my friend thank you very much"
    w2 = speech.speak_wav(said, "en-us") if speech.find_espeak() else V.tone_wav(f0=140, seconds=3)
    t2 = visemes.align(said, w2, "en")
    frames = []
    for i in range(int(t2["duration"] * 30)):
        v = next((x["v"] for x in t2["visemes"] if x["start"] <= i / 30 < x["end"]), "sil")
        g, b = BS[LR.FROM_VISEME[v]]
        frames.append({"t": i / 30, "face": True, "gap": g, "bs": b, "mouth_px": 170, "face_h": 0.5, "yaw": 3, "pitch": 2, "light": 0.5})
    good = LR.analyse(frames, {"width": 1920, "height": 1080, "fps": 60}, t2["jaw"], 100, script=said, read_lips=False)
    bad = LR.analyse(frames, {}, None, script="please send me the report by friday", read_lips=False)
    c.check("Lip-reading: the right script agrees with the lips, a wrong one does not",
            good["script"]["agreement"] >= 40 and bad["script"]["agreement"] < 25, "%d vs %d" % (good["script"]["agreement"], bad["script"]["agreement"]))
    c.check("Capture check: a well-framed 1080p 60 fps face scores 100", good["quality"]["score"] == 100, good["quality"]["score"])
    poor = LR.quality({"width": 640, "height": 360, "fps": 15}, [dict(f, face_h=0.15, mouth_px=40) for f in frames])
    c.check("Capture check: a small, low-resolution, 15 fps face is flagged item by item", poor["score"] < 50 and
            {i["item"] for i in poor["items"] if i["status"] == "bad"} >= {"framing", "mouth size", "resolution", "frame rate"})
    env = t2["jaw"]
    late = LR.av_sync([0.0] * 8 + env[:-8], env)                 # lips 80 ms after the sound
    c.check("Sync check: sound 80 ms ahead of the lips is measured as -80 ms and flagged", late["offset_ms"] == -80 and "EARLY" in late["verdict"], late)
    c.check("Sync check: matching sound and lips read as in sync", LR.av_sync(env, env)["offset_ms"] == 0)
    # camera + sound together: the lips choose the right reading, the face settles crying vs laughing, the speaker check
    cls, gaps = LR.classes_of(frames)
    rk = LR.rank_candidates(cls, [{"text": "hello my friend thank you very much", "confidence": 0.6, "source": "b"},
                                  {"text": "jello by trend tank ewe berry mud", "confidence": 0.8, "source": "a"}][::-1], 100)
    c.check("Camera + sound: the lips pick the right reading over a more confident wrong one", rk["chosen"] == said and rk["changed_by_lips"], rk["candidates"])
    happy = [dict(f, bs=dict(f["bs"], mouthSmileLeft=0.6, mouthSmileRight=0.6, cheekSquintLeft=0.4, cheekSquintRight=0.4)) for f in frames]
    sad = [dict(f, bs=dict(f["bs"], browInnerUp=0.6, mouthFrownLeft=0.4, mouthFrownRight=0.4)) for f in frames]
    c.check("Camera + sound: expressions read from the face (smiling, sad, neutral)",
            LR.expression(happy)["label"] == "smiling / laughing" and LR.expression(sad)["label"] == "sad / tearful" and LR.expression(frames)["label"] == "neutral")
    vc = {"label": "crying", "confidence": "uncertain", "scores": [{"mode": "crying", "score": 60}, {"mode": "laughing", "score": 50}]}
    c.check("Camera + sound: 'crying' heard with a laughing face is corrected to laughing; with a sad face it is confirmed",
            LR.fuse_mode(vc, LR.expression(happy))["label"] == "laughing" and LR.fuse_mode(vc, LR.expression(sad))["confidence"] == "confirmed by the face")
    still = [dict(f, gap=0.05, bs={}) for f in frames]
    ok_ = LR.fuse(frames, {"label": "speaking"}, None, [{"text": said, "confidence": 0.9}], {"width": 1920, "height": 1080, "fps": 60})["speaker_check"]["trust"]
    dub = LR.fuse(frames, {"label": "speaking"}, None, [{"text": "please send me the report by friday", "confidence": 0.9}], {"width": 1920, "height": 1080, "fps": 60})["speaker_check"]["trust"]
    mute = LR.fuse(still, {"label": "speaking"}, None, [{"text": said, "confidence": 0.9}], {"width": 1920, "height": 1080, "fps": 60})["speaker_check"]["trust"]
    c.check("Speaker check: own voice trusted; other words or still lips flagged as not this face", (ok_, dub, mute) == ("high", "low", "low"), (ok_, dub, mute))
    rd = LR.analyse(frames, {}, env, 100, read_lips=True)["lipread"]
    c.check("Lip-reading: free reading gives words, each with the words that look the same", rd["segments"] and all("same_on_lips" in w for s in rd["segments"] for w in s["words"]))


def _speech_selftest(c):
    """Speech Lab: measurement finds what was put in; effects and matching work; every cloud provider's
    request is checked against a stand-in server; keys never reach the log."""
    import http.server, threading as _th, voicedsp as V, base64 as _b
    c.check("Speech: pitch measured exactly (150 Hz test voice)", abs(V.measure(V.tone_wav(f0=150, seconds=2))["pitch"]["mean_hz"] - 150) < 2)
    tr = V.measure(V.tone_wav(f0=150, seconds=3, vibrato_hz=6, vibrato_st=0.6))["quality"]["tremor_pitch"]
    c.check("Speech: a 6 Hz tremble is found at 6 Hz", tr["detected"] and abs(tr["freq_hz"] - 6) < 0.7, tr.get("freq_hz"))
    cl = V.measure(V.tone_wav(f0=150, seconds=3))["indicators"]["hoarseness"]["level"]
    no = V.measure(V.tone_wav(f0=150, seconds=3, noise=0.1))["indicators"]["hoarseness"]["level"]
    c.check("Speech: a noisy voice reads hoarser than a clean one", no > cl + 20, "%s vs %s" % (no, cl))
    ps = V.measure(V.tone_wav(f0=150, seconds=3, gaps=((1.0, 1.5), (2.0, 2.3))))["pauses"]
    c.check("Speech: pauses found where they are (2 pauses, ~0.8 s)", ps["count"] == 2 and abs(ps["total_s"] - 0.8) < 0.15, ps["total_s"])
    if speech.find_espeak():
        w = speech.speak_wav("Hello there. This is a short test of the voice.", "en-us+whisper")
        c.check("Speech: a whisper is recognised as whispering", V.measure(w)["vocal_mode"]["label"] == "whispering")
        w = speech.speak_wav("Hello there. This is a short test of the voice.", "en-us")
        c.check("Speech: ordinary speech is recognised as speaking", V.measure(w)["vocal_mode"]["label"] == "speaking")
    with tempfile.TemporaryDirectory() as d:
        inst = App(d)
        S = inst.speech
        if speech.find_espeak():
            m = S.match("The quick brown fox jumps over the lazy dog.", {"pitch_hz": 160, "volume_dbfs": -24}, {}, "espeak")
            c.check("Speech: generate → measure → adjust reaches a pitch and loudness target", m["matched"], "%d rounds" % len(m["rounds"]))
        if speech.find_espeak():
            orig = speech.speak_wav("Good morning. I would like to talk about the weather today.", "en-us+m3")
            try:
                S.overdub(orig, "Hello", consent=False)
                c.check("Overdub: refused without consent", False)
            except ValueError:
                c.check("Overdub: refused without consent", True)
            od = S.overdub(orig, "Good evening. Let us discuss the football match.", {}, "espeak", consent=True)
            mo, md = V.measure(orig), V.measure(open(S.audio_path(od["audio"]), "rb").read())
            mv = V.measure(open(S.audio_path(od["voice_audio"]), "rb").read())
            c.check("Overdub: the new words fill the original's speaking time (within 0.3 s)",
                    abs(md["duration_s"] - mo["duration_s"]) < 0.3 and od["phrases"] and all(0.6 <= p["stretch"] <= 1.6 for p in od["phrases"]), od["mode"])
            c.check("Overdub: stretching keeps the voice's pitch (within 5%)", abs(md["pitch"]["mean_hz"] - mv["pitch"]["mean_hz"]) < 0.05 * mv["pitch"]["mean_hz"],
                    "%s vs %s Hz" % (md["pitch"]["mean_hz"], mv["pitch"]["mean_hz"]))
            c.check("Overdub: labelled synthetic and logged", "SYNTHETIC" in od["label"] and S.history(1, "overdub"))
        if speech.find_espeak():
            q_said = "how do you say house in spanish"
            qw = speech.speak_wav(q_said, "en-us")
            qt = visemes.align(q_said, qw, "en")
            qf = []
            for i in range(int(qt["duration"] * 30)):
                v = next((x["v"] for x in qt["visemes"] if x["start"] <= i / 30 < x["end"]), "sil")
                g_, b_ = {"P": (0.0, {"mouthClose": 0.4}), "F": (0.02, {"mouthRollLower": 0.5}), "W": (0.15, {"mouthPucker": 0.6}), "A": (0.45, {"jawOpen": 0.6}),
                          "E": (0.12, {"mouthStretchLeft": 0.4, "mouthStretchRight": 0.4}), "T": (0.1, {}), "-": (0.0, {"mouthClose": 0.3})}[__import__("lipread").FROM_VISEME[v]]
                qf.append({"t": i / 30, "face": True, "gap": g_, "bs": b_, "mouth_px": 170, "face_h": 0.5, "yaw": 3, "pitch": 2, "light": 0.5})
            vid = {"frames": qf, "info": {"width": 1920, "height": 1080, "fps": 60}, "alternatives": [{"text": q_said, "confidence": 0.7}]}
            qa = S.query("how do you say mouse in finnish", qw, {"lang": "en"}, video=vid)
            c.check("Query with the camera: a misheard question is corrected by the lips and answered right",
                    qa["question"] == q_said and "casa" in qa["answer"], qa["answer"])
            ig = S.ingest(qw, "how do you say mouse in finnish", lang="en", video=vid)
            c.check("Ingestion with the camera: transcript chosen by the lips, fused vocal mode, sync and speaker check recorded",
                    ig["transcript"] == q_said and "lips" in ig["heard_by"] and ig["face"]["speaker_check"]["trust"] == "high" and ig["face"]["sync"]["ok"]
                    and S.history(1, "ingest")[0]["result"]["speaker_check"])
        g = S.generate("Fail over", {}, "elevenlabs")                      # no key → next voice in the chain
        c.check("Speech: when a voice cannot be used the next one speaks, and every attempt is recorded",
                g["summary"]["engine_used"] in ("espeak", "sapi", "say", "formant") and g["summary"]["attempts"][0]["result"] == "skipped")
        saved_found = speech._found
        speech._found = ""                                                    # espeak missing → the built-in voice still speaks
        try:
            g = S.generate("Fail over", {}, "espeak")
            c.check("Speech: with espeak-ng missing the built-in voice still speaks", g["summary"]["engine_used"] in ("sapi", "say", "formant"))
        finally:
            speech._found = saved_found
        dg = {x["id"]: x for x in inst._health()}
        c.check("Diagnostics: speech checks cover voice, languages, failover, measurement, audio I/O, providers and log",
                all(k in dg for k in ("sp_failover", "sp_measure", "sp_audio", "sp_log", "sp_elevenlabs", "build", "proof", "voice_bundle")))
        g = S.generate("Testing the formant voice", {"tremble": 0.5}, "formant")
        c.check("Speech: the no-install formant voice speaks, with tremble added", g["summary"]["bytes"] > 1000 and any("tremble" in x for x in g["effects"]["applied"]))
        # stand-in cloud: answers like each provider and records what it was sent
        seen = []
        pcm = b"".join(int(8000 * __import__("math").sin(i / 8.0)).to_bytes(2, "little", signed=True) for i in range(24000))
        wav = V.pcm16_to_wav(pcm, 24000)

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                seen.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                if self.path.startswith("/v1/speech:recognize"):
                    out, ct = json.dumps({"results": [{"alternatives": [{"transcript": "good morning", "confidence": 0.9, "words": [
                        {"word": "good", "startTime": "0.20s", "endTime": "0.50s", "confidence": 0.92}, {"word": "morning", "startTime": "0.55s", "endTime": "1.10s", "confidence": 0.88}]}],
                        "languageCode": "en-us"}]}).encode(), "application/json"
                elif "generateContent" in self.path:
                    out, ct = json.dumps({"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/L16;rate=24000", "data": _b.b64encode(pcm).decode()}}]}}]}).encode(), "application/json"
                elif "text:synthesize" in self.path:
                    out, ct = json.dumps({"audioContent": _b.b64encode(wav).decode()}).encode(), "application/json"
                elif "text-to-speech" in self.path or "/v1/speech" in self.path:
                    out, ct = pcm, "application/octet-stream"
                else:
                    out, ct = wav, "audio/wav"
                self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(out))); self.end_headers()
                self.wfile.write(out)
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        _th.Thread(target=srv.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        saved = {k: os.environ.get(k) for k in ("NO_PROXY", "no_proxy")}
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
        secrets = {"google_gemini": {"api_key": "gem-SECRET-123456"}, "google_cloud": {"api_key": "gcp-SECRET-123456"},
                   "elevenlabs": {"api_key": "el-SECRET-123456"}, "openai": {"api_key": "oa-SECRET-123456"},
                   "azure": {"api_key": "az-SECRET-123456", "region": "westeurope"},
                   "polly": {"access_key_id": "AKIDSECRET123456", "secret_access_key": "aws-SECRET-123456", "region": "eu-west-1"}}
        prof = {"emotion": "sad", "intensity": 0.8, "age": 0.7, "tremble": 0.3, "pause_scale": 1.5}
        try:
            for prov, vals in secrets.items():
                os.environ["QB_TTS_BASE_" + prov.upper()] = base
                S.keys.save(prov, vals)
                n0 = len(seen)
                r = S.generate("I am so sorry, this is hard to say.", prof, prov, fallback=False, measure=False)
                req = seen[n0] if len(seen) > n0 else {"headers": {}, "body": b""}
                body = req["body"].decode("utf-8", "replace")
                checks = {"google_gemini": lambda: "sad" in body.lower() and "elderly" in body and req["headers"].get("x-goog-api-key") == vals["api_key"],
                          "google_cloud": lambda: "<prosody" in body and "volumeGainDb" in body and req["headers"].get("x-goog-api-key") == vals["api_key"],
                          "elevenlabs": lambda: '"stability"' in body and '"style"' in body and "output_format=pcm_24000" in req["path"] and req["headers"].get("xi-api-key") == vals["api_key"],
                          "openai": lambda: '"instructions"' in body and "sad" in body.lower() and req["headers"].get("authorization") == "Bearer " + vals["api_key"],
                          "azure": lambda: "style='sad'" in body and "OlderAdult" in body and req["headers"].get("ocp-apim-subscription-key") == vals["api_key"],
                          "polly": lambda: '"TextType": "ssml"' in body and "AWS4-HMAC-SHA256 Credential=AKIDSECRET123456/" in req["headers"].get("authorization", "")}
                c.check("Speech: %s request carries the voice profile and its key, audio comes back" % prov, r["summary"]["engine_used"] == prov and checks[prov]())
            os.environ["QB_GCP_BASE_SPEECH"] = base
            S.google.s.save({"api_key": "AIzaSTTSECRET-123456"})
            w = V.tone_wav(f0=150, seconds=1.5)
            r = S.ingest(w, "", "", "stt test", "auto", "en")
            c.check("Speech: with no browser transcript, Google Speech-to-Text supplies the words, with timings and confidence",
                    r["heard_by"] == "Google Speech-to-Text" and r["transcript"] == "good morning" and r["semantics"]["words"][1].get("start_s") == 0.55)
            r = S.ingest(w, "typed words", "", "stt test", "browser", "en")
            c.check("Speech: 'browser only' never calls Google", r["heard_by"] == "browser / typed")
            long_w = V.tone_wav(f0=140, seconds=125, gaps=tuple((k * 10 - 0.6, k * 10) for k in range(1, 13)))
            lr = S.transcribe_long(long_w, "en", "pieces")
            pt = lr.get("piece_times") or []
            c.check("Speech: a 2-minute recording is cut at pauses into pieces of at most 50 s, each word placed at its time in the whole recording",
                    lr.get("pieces", 0) >= 3 and all(b - a <= 50.01 for a, b in pt) and len(lr["words"]) == 2 * len(pt)
                    and [round(w_["start_s"], 2) for w_ in lr["words"][::2]] == [round(a + 0.2, 2) for a, _ in pt], lr.get("method"))
            auto = S.transcribe(long_w, "en")
            c.check("Speech: recordings over 50 s are transcribed whole automatically (no 55-second cut-off)", auto.get("pieces", 0) >= 3 and auto["duration_s"] > 120)
            tk = S.start_transcription(long_w, "en", "pieces")["task"]
            for _ in range(400):
                st_ = S.transcription(tk)
                if st_["state"] != "running":
                    break
                time.sleep(0.05)
            c.check("Speech: whole-file transcription runs as its own background task with progress (never waits for other jobs)",
                    st_["state"] == "finished" and st_["result"]["pieces"] >= 3 and st_["overall"] == 1.0, st_.get("message"))
            cp = S.caption_piece(V.tone_wav(f0=140, seconds=3), "en", 12.5)
            c.check("Speech: a live-caption piece comes back with each word's time in the whole file", cp["words"][0]["start_s"] == 12.7 and cp["transcript"] == "good morning")
            try:
                S.transcribe_long(long_w, "en", "storage")
                c.check("Speech: long-audio mode without the service account says what is missing", False)
            except ValueError as e_:
                c.check("Speech: long-audio mode without the service account says what is missing", "service account" in str(e_))
            os.environ["QB_GCP_BASE_SPEECH"] = "http://127.0.0.1:9"
            r = S.ingest(w, "", "", "stt test", "auto", "en")
            c.check("Speech: when Google Speech-to-Text fails, analysis still completes and says why", "failed" in r["heard_by"] and r["measure"]["pitch"])
            os.environ.pop("QB_GCP_BASE_SPEECH", None)
            logged = json.dumps(S.history(200)) + json.dumps(inst.store.activities(500))
            c.check("Speech: no provider key appears in the speech log or activity log",
                    not any(v in logged for vals in secrets.values() for v in vals.values() if "SECRET" in v) and "AIzaSTTSECRET" not in logged)
            c.check("Speech: provider settings are reported without their keys", "SECRET" not in json.dumps(S.keys.public()))
        finally:
            srv.shutdown()
            for prov in secrets:
                os.environ.pop("QB_TTS_BASE_" + prov.upper(), None)
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        with tempfile.TemporaryDirectory() as old:
            with open(os.path.join(old, "qb_tts_keys.json"), "w") as f:
                json.dump({"google": {"key": "OLDGOOGLE-KEY-777777", "voice": "Kore", "custom_voices": {"Me": {"cloning_key": "CLONE-KEY-888888", "language": "en-US"}}},
                           "elevenlabs": {"key": "OLDELEVEN-KEY-999999"}}, f)
            for prov in ("google_gemini", "google_cloud", "elevenlabs"):
                S.keys.forget(prov)
            r = S.keys.import_prototype(old)
            k = S.keys
            c.check("Speech: the old QueryBook's Google and ElevenLabs keys (and custom voices) are imported",
                    k.get("google_gemini")["api_key"] == "OLDGOOGLE-KEY-777777" and k.get("google_cloud")["api_key"] == "OLDGOOGLE-KEY-777777"
                    and k.get("elevenlabs")["api_key"] == "OLDELEVEN-KEY-999999" and "Me" in k.get("google_cloud")["custom_voices"], r["imported"])
            pub = json.dumps(k.public()) + json.dumps(r)
            c.check("Speech: imported keys are never shown", "OLDGOOGLE" not in pub and "OLDELEVEN" not in pub and "CLONE-KEY" not in pub)
            with tempfile.TemporaryDirectory() as empty:
                c.check("Speech: a folder without the old key file is reported as not found", not S.keys.import_prototype(empty)["imported"]
                        or bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("ELEVENLABS_API_KEY")))
        rows = S.history(500)
        c.check("Speech: every process is logged with timestamps to 0.01 s and timed stages",
                rows and all(re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d\dZ$", r["started"]) and r["stages"] is not None for r in rows))


if __name__ == "__main__":
    sys.exit(core.run_cli(sys.modules[__name__]))
