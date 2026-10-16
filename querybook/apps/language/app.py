#!/usr/bin/env python3
"""QueryBook Language & Speech — a dedicated application for learning vocabulary, listening and speaking.

Seven languages taught from English (Spanish, French, German, Italian, Portuguese, Dutch, Swedish).
New words arrive a few at a time, most common first, and come back for review on a fixed
spaced-repetition schedule (1, 2, 4, 8, 16, 32, 64 days). Practise with flashcards, multiple
choice, typing, listening and speaking. Answers are checked by rule, never by an AI model.

Start:      python app.py            (opens http://127.0.0.1:8101/)
Self-test:  python app.py --selftest
More:       python app.py --help
"""
import datetime, hashlib, json, os, sys, tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import qbcore as core
import speech
import vocab

APP_ID = "language"
APP_NAME = "QueryBook Language & Speech"
VERSION = "1.0.0"
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
"""]


def today():
    return datetime.date.today().isoformat()


def add_days(day, n):
    return (datetime.date.fromisoformat(day) + datetime.timedelta(days=n)).isoformat()


class App:
    def __init__(self, folder, clock=today):
        os.makedirs(folder, exist_ok=True)
        self.folder = folder
        self.today = clock
        self.log = core.make_logger(folder, APP_ID)
        self.store = core.Store(folder, APP_ID, SCHEMA, self.log)
        self.jobs = core.Jobs(self.log)
        self.api = core.Api()
        self._routes()
        try:
            self.store.backup("startup")
        except Exception as e:
            self.log("startup backup failed:", e)

    # ------------------------------------------------------------------ words
    def _lang(self, lang):
        if lang not in vocab.LANGUAGES:
            raise core.UserError("Choose one of: " + ", ".join(v["name"] for v in vocab.LANGUAGES.values()))
        return lang

    def custom(self, lang):
        out = {}
        for r in self.store.query("SELECT english, foreign_word FROM custom_words WHERE lang = ? ORDER BY id", (lang,)):
            out.setdefault(r["english"].lower(), []).append(r["foreign_word"])
        return out

    def get_word(self, lang, en, custom=None):
        custom = self.custom(lang) if custom is None else custom
        w = vocab.word(lang, en)
        tr = list(custom.get(en, [])) + [t for t in (w["tr"] if w else []) if t not in custom.get(en, [])]
        if not tr:
            return None
        return {"en": en, "tr": tr, "rank": w["rank"] if w else None, "custom": en in custom}

    def settings(self, lang):
        r = self.store.one("SELECT new_per_day, direction FROM settings WHERE lang = ?", (lang,))
        return r or {"new_per_day": 10, "direction": "from_english"}

    def set_settings(self, lang, new_per_day=None, direction=None):
        s = self.settings(lang)
        n = s["new_per_day"] if new_per_day in (None, "") else int(new_per_day)
        d = direction or s["direction"]
        if not 0 <= n <= 100:
            raise core.UserError("New words per day must be between 0 and 100.")
        if d not in ("from_english", "to_english"):
            raise core.UserError("Unknown direction.")
        with self.store.write() as db:
            db.execute("INSERT OR REPLACE INTO settings(lang, new_per_day, direction) VALUES(?,?,?)", (lang, n, d))
        return {"new_per_day": n, "direction": d}

    def new_words(self, lang, n):
        """The next n words not yet introduced: your own words first, then the most common English words."""
        if n <= 0:
            return []
        known = {r["word"] for r in self.store.query("SELECT word FROM cards WHERE lang = ?", (lang,))}
        custom = self.custom(lang)
        out = [en for en in custom if en not in known][:n]
        for w in vocab.deck(lang):
            if len(out) >= n:
                break
            if w["en"] not in known and w["en"] not in out:
                out.append(w["en"])
        return out

    # ------------------------------------------------------------------ sessions
    def session(self, lang, mode="cards", direction=None, size=20):
        lang = self._lang(lang)
        if mode not in MODES:
            raise core.UserError("Unknown practice mode.")
        st = self.settings(lang)
        direction = direction or st["direction"]
        day = self.today()
        due = [r["word"] for r in self.store.query("SELECT word FROM cards WHERE lang = ? AND due <= ? ORDER BY due, box, word LIMIT ?",
                                                     (lang, day, size))]
        introduced_today = self.store.scalar("SELECT count(*) FROM cards WHERE lang = ? AND introduced = ?", (lang, day), 0)
        allowance = max(0, st["new_per_day"] - introduced_today)
        new = self.new_words(lang, min(allowance, max(0, size - len(due))))
        custom = self.custom(lang)
        items = []
        for en, is_new in [(w, False) for w in due] + [(w, True) for w in new]:
            w = self.get_word(lang, en, custom)
            if not w:
                continue
            items.append(self._item(lang, w, mode, direction, is_new, day))
        return {"lang": lang, "language": vocab.LANGUAGES[lang]["name"], "speech": vocab.LANGUAGES[lang]["speech"], "mode": mode,
                "direction": direction, "items": items, "due": len(due), "new": len(new),
                "new_left_today": max(0, allowance - len(new)), "settings": st}

    def _item(self, lang, w, mode, direction, is_new, day):
        defs = vocab.definitions()
        foreign = w["tr"][0]
        if mode in ("listen", "speak"):
            direction = "from_english"
        if direction == "to_english":
            prompt, accepted = foreign, sorted(set([w["en"]] + vocab.reverse_index(lang).get(vocab.fold(foreign), [])), key=lambda x: x != w["en"])
        else:
            prompt, accepted = w["en"], w["tr"]
        item = {"en": w["en"], "foreign": foreign, "all_foreign": w["tr"], "prompt": prompt, "accepted": accepted, "new": is_new,
                "definition": (defs.get(w["en"]) or "")[:300], "custom": w["custom"], "direction": direction}
        if mode == "choice":
            item["choices"] = self._choices(lang, w, direction, day)
        if mode == "listen":
            item["prompt"] = None              # the page plays the foreign word; the learner types what they hear
            item["accepted"] = w["tr"]
        return item

    def _choices(self, lang, w, direction, day):
        """Four options: the answer plus three nearby words, chosen the same way every time for this word and day."""
        d = vocab.deck(lang)
        pos = next((i for i, x in enumerate(d) if x["en"] == w["en"]), 0)
        seed = int(hashlib.sha256((lang + w["en"] + day).encode()).hexdigest(), 16)
        pool = [x for x in d[max(0, pos - 60): pos + 60] if x["en"] != w["en"]]
        picks = []
        while pool and len(picks) < 3:
            x = pool.pop(seed % len(pool))
            seed //= 7
            opt = x["en"] if direction == "to_english" else x["tr"][0]
            if vocab.fold(opt) not in {vocab.fold(p) for p in picks} and vocab.fold(opt) != vocab.fold(w["en"] if direction == "to_english" else w["tr"][0]):
                picks.append(opt)
        right = w["en"] if direction == "to_english" else w["tr"][0]
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
        item = self._item(lang, w, mode, direction or "from_english", False, self.today())
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
        for code, info in vocab.LANGUAGES.items():
            r = rows.get(code, {})
            out.append({"code": code, "name": info["name"], "native": info["native"], "words_available": len(vocab.deck(code)),
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
            rows = [w for w in vocab.deck(lang) if w["en"] not in known and (not q or q in w["en"] or any(q in vocab.fold(t) for t in w["tr"]))]
            return {"total": len(rows), "words": [{"word": w["en"], "foreign": ", ".join(w["tr"]), "box": None, "due": None} for w in rows[offset:offset + limit]]}
        where = {"learning": "", "mastered": " AND box >= %d" % MASTERED_BOX, "due": " AND due <= '%s'" % day}.get(which, "")
        rows = self.store.query("SELECT word, box, due, correct, wrong FROM cards WHERE lang = ?%s ORDER BY word" % where, (lang,))
        custom = self.custom(lang)
        out = []
        for r in rows:
            w = self.get_word(lang, r["word"], custom)
            r["foreign"] = ", ".join(w["tr"]) if w else ""
            if not q or q in r["word"] or q in vocab.fold(r["foreign"]):
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
        picked = [r["word"] for r in rows if r["word"] not in known and vocab.word(lang, r["word"])][:limit]
        with self.store.write() as db:
            db.executemany("INSERT OR IGNORE INTO cards(lang, word, box, due, introduced) VALUES(?,?,0,?,?)", [(lang, w, day, day) for w in picked])
        return {"added": len(picked), "words": picked}

    # ------------------------------------------------------------------ routes
    def _routes(self):
        a = self.api

        @a.get("/api/status")
        def status(p):
            return {"app": APP_NAME, "version": VERSION, "store": self.store.status(), "speech": speech.status(),
                    "reviews": self.store.scalar("SELECT count(*) FROM reviews", default=0),
                    "cards": self.store.scalar("SELECT count(*) FROM cards", default=0), "sources": vocab.SOURCES, "job": self.jobs.status()["state"]}

        @a.get("/api/languages")
        def languages(p):
            return {"languages": self.language_summary(), "modes": MODES, "intervals": INTERVALS}

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
            return {"words": self.store.query("SELECT * FROM custom_words WHERE lang = ? ORDER BY id DESC", (self._lang(p.get("lang")),))}

        @a.post("/api/custom/add")
        def custom_add(p):
            lang = self._lang(p.get("lang"))
            en, fw = vocab.clean(p.get("english")), " ".join(str(p.get("foreign") or "").split())
            if not en or not fw:
                raise core.UserError("Enter the English word and its translation.")
            if len(en) > 80 or len(fw) > 80:
                raise core.UserError("Keep each word or phrase under 80 characters.")
            with self.store.write() as db:
                db.execute("INSERT OR IGNORE INTO custom_words(lang, english, foreign_word, note, created) VALUES(?,?,?,?,?)",
                           (lang, en, fw, (p.get("note") or "").strip() or None, core.now_iso()))
            return {"ok": True}

        @a.post("/api/custom/delete")
        def custom_delete(p):
            with self.store.write() as db:
                db.execute("DELETE FROM custom_words WHERE id = ?", (int(p.get("id")),))
            return {"ok": True}

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


def open_app(folder=None):
    return App(folder or core.data_folder(APP_ID, HERE))


# ---------------------------------------------------------------------- self-test
def selftest():
    c = core.Checks()
    c.check("shared core matches the master copy", core.core_matches_master(HERE))
    for code in vocab.LANGUAGES:
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
    c.check("dictionary lookup English", lk["english"] and lk["english"]["translations"]["es"] and lk["english"]["definition"])
    c.check("dictionary lookup foreign", any(f["lang"] == "es" and "ability" in f["english"] for f in vocab.lookup("capacidad")["foreign"]))
    with tempfile.TemporaryDirectory() as tmp:
        clock = {"d": "2026-10-16"}
        app = App(os.path.join(tmp, "data"), clock=lambda: clock["d"])
        app.set_settings("es", 5)
        s = app.session("es", "type")
        c.check("first session offers 5 new words", s["new"] == 5 and s["due"] == 0 and len(s["items"]) == 5, s["new"])
        first = s["items"][0]
        r = app.answer("es", first["en"], "type", "from_english", first["accepted"][0])
        c.check("correct answer moves the word to box 1, due tomorrow", r["correct"] and r["box"] == 1 and r["next_review"] == "2026-10-17", r)
        r2 = app.answer("es", s["items"][1]["en"], "type", "from_english", "zzz")
        c.check("wrong answer stays due today", not r2["correct"] and r2["next_review"] == "2026-10-16")
        for it in s["items"][2:]:
            app.answer("es", it["en"], "cards", "from_english", knew=True)
        s2 = app.session("es", "type")
        c.check("same day: the missed word comes back, no new words beyond the daily limit", s2["due"] == 1 and s2["new"] == 0, (s2["due"], s2["new"]))
        clock["d"] = "2026-10-17"
        s3 = app.session("es", "choice")
        c.check("next day: yesterday's words are due and 5 new words arrive", s3["due"] == 5 and s3["new"] == 5, (s3["due"], s3["new"]))
        ch = s3["items"][0]["choices"]
        c.check("multiple choice has 4 different options including the answer",
                len(ch) == 4 and len({vocab.fold(x) for x in ch}) == 4 and s3["items"][0]["accepted"][0] in ch, ch)
        c.check("choices are the same every time for the same day", app.session("es", "choice")["items"][0]["choices"] == ch)
        sp = app.answer("es", first["en"], "speak", "from_english", first["all_foreign"][0].upper() + "!")
        c.check("speaking: recognised text close enough counts", sp["correct"] and sp["similarity"] >= SPEAK_PASS, sp)
        for _ in range(7):
            app.answer("es", first["en"], "cards", "from_english", knew=True)
        c.check("box never goes beyond the last interval", app.store.scalar("SELECT box FROM cards WHERE word = ?", (first["en"],)) == len(INTERVALS) - 1)
        app.answer("es", first["en"], "type", "from_english", "wrong answer")
        row = app.store.one("SELECT box, lapses FROM cards WHERE word = ?", (first["en"],))
        c.check("forgetting a mastered word sends it back to box 1 and counts a lapse", row["box"] == 1 and row["lapses"] == 1, row)
        app.api.routes[("POST", "/api/custom/add")]({"lang": "es", "english": "grandmother", "foreign": "abuela"})
        s4 = app.session("es", "type")
        c.check("your own words are taught first", any(i["en"] == "grandmother" and i["new"] for i in s4["items"]) or s4["new"] == 0)
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
    st = speech.status()
    c.check("offline voice (espeak-ng): %s" % ("found" if st["espeak"] else "not installed — browser voices are used"), True)
    return c.report(APP_NAME)


if __name__ == "__main__":
    sys.exit(core.run_cli(sys.modules[__name__]))
