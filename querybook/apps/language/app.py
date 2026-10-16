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
import datetime, hashlib, json, os, sys, tempfile, threading, time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import qbcore as core
import lab
import speech
import verify
import vocab

APP_ID = "language"
APP_NAME = "QueryBook Language Builder"
VERSION = "1.4.0"
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
""", lab.SCHEMA]


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
        self.CLI_COMMANDS = {"build": self._cli_build, "verify": self._cli_verify}
        self.api = core.Api()
        self.diag = core.Diagnostics(APP_ID, APP_NAME, VERSION, HERE, self.store, self.log, self.jobs, self._health)
        self.monitor = core.Monitor(folder, APP_ID, APP_NAME, VERSION, self.log)
        self.log.hooks.append(self.monitor.on_error)
        core.add_diagnostics(self.api, self.diag, self.monitor, HERE)
        self._routes()
        try:
            self.store.backup("startup")
        except Exception as e:
            self.log("startup backup failed:", e)
        threading.Thread(target=self._warm, daemon=True).start()

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
        out.append(C("voice", "Offline voice (espeak-ng)", "ok", "installed" if sp["espeak"] else "not installed — the browser's voices are used"))
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
    return c.report(APP_NAME)


if __name__ == "__main__":
    sys.exit(core.run_cli(sys.modules[__name__]))
