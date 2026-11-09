"""Object scan: what the camera saw, kept for ingestion and answered for queries.

The page recognizes objects on this computer (MediaPipe Object Detector, EfficientDet-Lite0, bundled,
80 everyday kinds of object from the COCO set), follows them from frame to frame and can zoom on one.
What reaches this module is numbers only — never a picture: each followed object ("track") with its
kind, when it was first and last seen, in how many frames, how sure the detector was and where it was.

These are machine observations, not facts: they are never added to the shared Commons as sourced facts.

Queries (typed, or spoken through Ask by voice) are answered deterministically from the log:
  when did I last see a cup?        did I see a dog today?        how many people did I see yesterday?
  what did I see in the last 30 minutes?        what did I see in session 3?
  what is this (in Spanish)?        — about the object the camera is following right now
"""
import datetime, json, re

import vocab

SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_sessions (
  id INTEGER PRIMARY KEY, label TEXT NOT NULL, source TEXT NOT NULL, started TEXT NOT NULL, seconds REAL NOT NULL,
  frames INTEGER NOT NULL, objects INTEGER NOT NULL, model TEXT, created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scan_tracks (
  id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES scan_sessions(id) ON DELETE CASCADE, label TEXT NOT NULL,
  first_s REAL NOT NULL, last_s REAL NOT NULL, first_at TEXT NOT NULL, last_at TEXT NOT NULL, frames INTEGER NOT NULL,
  score REAL NOT NULL, x REAL, y REAL, w REAL, h REAL, followed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS scan_tracks_label ON scan_tracks(label, last_at)
"""

MODEL = "MediaPipe Object Detector, EfficientDet-Lite0 (COCO, 80 kinds, Apache 2.0)"
LABELS = ["person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light", "fire hydrant",
          "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe",
          "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite", "baseball bat",
          "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl",
          "banana", "apple", "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
          "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
          "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush"]
# everyday words people use for a detector kind
SYNONYMS = {"people": "person", "persons": "person", "man": "person", "men": "person", "woman": "person", "women": "person",
            "someone": "person", "somebody": "person", "child": "person", "children": "person", "kid": "person", "kids": "person",
            "bike": "bicycle", "motorbike": "motorcycle", "plane": "airplane", "aeroplane": "airplane", "lorry": "truck",
            "phone": "cell phone", "mobile": "cell phone", "smartphone": "cell phone", "telephone": "cell phone",
            "television": "tv", "telly": "tv", "computer": "laptop", "notebook": "laptop", "sofa": "couch", "table": "dining table",
            "plant": "potted plant", "glass": "wine glass", "ball": "sports ball", "bag": "handbag", "purse": "handbag",
            "fridge": "refrigerator", "doughnut": "donut", "teddy": "teddy bear", "hairdryer": "hair drier", "hair dryer": "hair drier",
            "racket": "tennis racket", "racquet": "tennis racket", "mug": "cup", "remote control": "remote", "puppy": "dog", "kitten": "cat"}
# the dictionary word for a kind, where it is unambiguous (used for meanings and translations)
WORD = {"airplane": "plane", "couch": "sofa", "laptop": "computer", "cell phone": "telephone", "handbag": "bag", "dining table": "table",
        "potted plant": "plant", "wine glass": "glass", "sports ball": "ball", "stop sign": "sign", "tv": "television"}
NO_WORD = {"teddy bear", "traffic light", "baseball bat", "baseball glove", "hot dog", "fire hydrant", "parking meter", "hair drier", "tie"}


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def kind_of(text):
    """The detector kind meant by a word or phrase, or None."""
    t = " ".join(str(text or "").lower().replace("-", " ").split())
    t = re.sub(r"^(?:a|an|the|my|any|some)\s+", "", t)
    for cand in (t, t[:-1] if t.endswith("s") else None, t[:-2] if t.endswith("es") else None, t[:-3] + "y" if t.endswith("ies") else None):
        if not cand:
            continue
        if cand in LABELS:
            return cand
        if cand in SYNONYMS:
            return SYNONYMS[cand]
    return None


def plural(label, n):
    if n == 1:
        return label
    return {"person": "people", "mouse": "mice", "knife": "knives", "skis": "skis", "sheep": "sheep", "scissors": "scissors",
            "bus": "buses", "couch": "couches", "sandwich": "sandwiches", "glass": "glasses", "wine glass": "wine glasses",
            "toothbrush": "toothbrushes", "hair drier": "hair driers"}.get(label, label + "s")


def _when(ts, tz_min):
    t = datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ") + datetime.timedelta(minutes=tz_min)
    return t.strftime("%d %b %Y, %H:%M:%S").lstrip("0")


class Scan:
    def __init__(self, store, log=lambda *a: None):
        self.store = store
        self.log = log

    # ------------------------------------------------------------------ ingestion
    def save(self, p):
        tracks = [t for t in p.get("tracks") or [] if kind_of(t.get("label")) and int(t.get("frames") or 0) >= int(p.get("min_frames") or 3)]
        started = p.get("started") or now_iso()
        try:
            t0 = datetime.datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            raise ValueError("started must be a UTC time like 2026-10-18T10:00:00Z")
        at = lambda s: (t0 + datetime.timedelta(seconds=float(s))).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.store.write() as db:
            sid = db.execute("""INSERT INTO scan_sessions(label, source, started, seconds, frames, objects, model, created)
                                VALUES(?,?,?,?,?,?,?,?)""", (str(p.get("label") or "scan")[:200], str(p.get("source") or "camera")[:60], started,
                                                            float(p.get("seconds") or 0), int(p.get("frames") or 0), len(tracks), MODEL, now_iso())).lastrowid
            for t in tracks:
                box = t.get("box") or [None] * 4
                db.execute("""INSERT INTO scan_tracks(session_id, label, first_s, last_s, first_at, last_at, frames, score, x, y, w, h, followed)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (sid, kind_of(t["label"]), float(t["first_s"]), float(t["last_s"]), at(t["first_s"]), at(t["last_s"]), int(t["frames"]),
                            round(float(t.get("score") or 0), 3), *[None if v is None else round(float(v), 4) for v in box[:4]], 1 if t.get("followed") else 0))
        self.store.activity("Object scan saved", "ok", "%s: %d objects" % (p.get("label") or "scan", len(tracks)), items=len(tracks))
        return {"session_id": sid, "objects": len(tracks), "summary": self.session_summary(sid)}

    def session_summary(self, sid):
        rows = self.store.query("SELECT label, count(*) AS n FROM scan_tracks WHERE session_id = ? GROUP BY label ORDER BY n DESC, label", (sid,))
        return ", ".join("%d %s" % (r["n"], plural(r["label"], r["n"])) for r in rows) or "nothing recognized"

    def sessions(self, limit=50):
        out = self.store.query("SELECT * FROM scan_sessions ORDER BY id DESC LIMIT ?", (limit,))
        for s in out:
            s["summary"] = self.session_summary(s["id"])
        return out

    def delete(self, sid):
        with self.store.write() as db:
            db.execute("DELETE FROM scan_tracks WHERE session_id = ?", (sid,))
            n = db.execute("DELETE FROM scan_sessions WHERE id = ?", (sid,)).rowcount
        return {"deleted": n}

    # ------------------------------------------------------------------ what is this?
    def what_is(self, label, score=None, lang=None):
        k = kind_of(label)
        if not k:
            return {"answer": "I can't tell what that is.", "label": None}
        word = None if k in NO_WORD else WORD.get(k, k)
        tr = {}
        if word:
            for code in vocab.OTHERS:
                f = vocab.forms(code, word)
                if f:
                    tr[code] = {"language": vocab.LANGUAGES[code]["name"], "forms": f[:3]}
        d = vocab.definitions().get(word) if word else None
        sure = (" (%d%% sure)" % round(100 * float(score))) if score is not None else ""
        ans = "That looks like %s %s%s." % ("an" if k[0] in "aeiou" else "a", k, sure)
        if lang in tr:
            ans += " In %s: %s." % (tr[lang]["language"], " or ".join(tr[lang]["forms"][:2]))
        elif lang and lang in vocab.LANGUAGES and lang != "en":
            ans += " I have not learned it in %s yet." % vocab.LANGUAGES[lang]["name"]
        return {"answer": ans, "label": k, "word": word, "definition": (d or "").split(";")[0][:240] or None, "translations": tr,
                "source": "detector: %s; words: %s" % (MODEL, "; ".join(vocab.SOURCES.values()))}

    # ------------------------------------------------------------------ questions about what was seen
    def _period(self, t, tz_min):
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        local = now + datetime.timedelta(minutes=tz_min)
        day0 = local.replace(hour=0, minute=0, second=0, microsecond=0) - datetime.timedelta(minutes=tz_min)
        fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
        m = re.search(r"in the (?:last|past) (\d+|an?|one) (minute|hour|day)s?", t)
        if m:
            n = 1 if m.group(1) in ("a", "an", "one") else int(m.group(1))
            secs = n * {"minute": 60, "hour": 3600, "day": 86400}[m.group(2)]
            return fmt(now - datetime.timedelta(seconds=secs)), fmt(now + datetime.timedelta(seconds=1)), m.group(0)
        if "yesterday" in t:
            return fmt(day0 - datetime.timedelta(days=1)), fmt(day0), "yesterday"
        if "today" in t:
            return fmt(day0), fmt(now + datetime.timedelta(seconds=1)), "today"
        if "this week" in t:
            return fmt(day0 - datetime.timedelta(days=local.weekday())), fmt(now + datetime.timedelta(seconds=1)), "this week"
        return None, None, ""

    def answer(self, text, tz_min=0, live=None):
        """Answer a question about what was seen. Returns None when the question is not about that."""
        t = " ".join(str(text or "").lower().strip(" ?!.").split())
        names = {v["name"].lower(): k for k, v in vocab.LANGUAGES.items()}
        m = re.match(r"^(?:what(?:'s| is) (?:this|that|it)|what am i (?:looking at|seeing)|what do you see)(?: in (\w+))?$", t)
        if m:
            lang = names.get(m.group(1) or "")
            if not live or not live.get("label"):
                return {"kind": "what", "answer": "Point the camera at something and let the scan follow it first."}
            r = self.what_is(live["label"], live.get("score"), lang)
            r["kind"] = "what"
            return r
        lo, hi, period = self._period(t, tz_min)
        where, args = [], []
        if lo:
            where.append("t.last_at >= ? AND t.first_at < ?")
            args += [lo, hi]
        m = re.search(r"in (?:session|scan|recording) (\d+)", t)
        if m:
            where.append("t.session_id = ?")
            args.append(int(m.group(1)))
            period = "in session %s" % m.group(1)
        cond = (" AND " + " AND ".join(where)) if where else ""
        # what did I see?
        if re.match(r"^(?:what|which (?:things|objects)) (?:did i see|have i seen|was there|did the camera see)", t):
            rows = self.store.query("SELECT t.label, count(*) AS n FROM scan_tracks t WHERE 1=1%s GROUP BY t.label ORDER BY n DESC, t.label" % cond, args)
            if not rows:
                return {"kind": "list", "answer": "Nothing was recognized %s." % (period or "yet"), "counts": []}
            return {"kind": "list", "counts": rows, "answer": "%s you saw %s." % ((period or "So far").capitalize(),
                    ", ".join("%d %s" % (r["n"], plural(r["label"], r["n"])) for r in rows[:12]))}
        # find the object the question is about
        m = (re.search(r"(?:see|seen|saw|spot|spotted|was there|were there|is there|find|show me|many)\s+(?:a|an|the|my|any|some)?\s*([a-z][a-z ]*?)(?:\s+(?:today|yesterday|this week|in the|in session|in scan|in recording|did|were|was|have|last|$))", t + " ")
             or re.search(r"(?:where|when).* (?:my|the|a|an) ([a-z ]+?)(?: today| yesterday|$)", t))
        k = kind_of(m.group(1).strip()) if m else None
        if not k:
            k = next((kind_of(w) for w in re.findall(r"[a-z]+(?: [a-z]+)?", t) if kind_of(w)), None) if re.search(r"\b(see|seen|saw|spot|when|where|how many|show)\b", t) else None
        if not k:
            return None
        rows = self.store.query("""SELECT t.*, s.label AS session_label, s.source FROM scan_tracks t JOIN scan_sessions s ON s.id = t.session_id
                                   WHERE t.label = ?%s ORDER BY t.last_at DESC, t.id DESC LIMIT 50""" % cond, [k] + args)
        n = len(rows)
        pl = plural(k, 2)
        if t.startswith("how many"):
            return {"kind": "count", "label": k, "count": n, "matches": rows[:10],
                    "answer": "You saw %d %s%s." % (n, plural(k, n), (" " + period) if period else "")}
        if re.match(r"^(?:did|have) i (?:see|seen|spot)", t) or t.startswith("was there") or t.startswith("were there"):
            if not n:
                return {"kind": "yesno", "label": k, "count": 0, "matches": [], "answer": "No, I have no %s on record%s." % (pl, (" " + period) if period else "")}
            r = rows[0]
            return {"kind": "yesno", "label": k, "count": n, "matches": rows[:10],
                    "answer": "Yes — %d time%s%s; the last in “%s” at %s (%.1f s into it)." % (n, "" if n == 1 else "s", (" " + period) if period else "",
                                                                                        r["session_label"], _when(r["last_at"], tz_min), r["last_s"])}
        if not n:
            return {"kind": "when", "label": k, "count": 0, "matches": [], "answer": "I have no %s on record%s." % (pl, (" " + period) if period else "")}
        r = rows[0]
        return {"kind": "when", "label": k, "count": n, "matches": rows[:10],
                "answer": "The last %s was in “%s” at %s, from %.1f s to %.1f s into it (%d%% sure)%s." % (
                    k, r["session_label"], _when(r["last_at"], tz_min), r["first_s"], r["last_s"], round(100 * r["score"]),
                    (" — %d sightings in all" % n) if n > 1 else "")}

    def stats(self):
        return {"sessions": self.store.scalar("SELECT count(*) FROM scan_sessions", default=0),
                "objects": self.store.scalar("SELECT count(*) FROM scan_tracks", default=0),
                "kinds": self.store.query("SELECT label, count(*) AS n FROM scan_tracks GROUP BY label ORDER BY n DESC LIMIT 20"),
                "model": MODEL, "labels": LABELS}
