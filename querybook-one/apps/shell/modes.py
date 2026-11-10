"""The ways to ask QueryBook and the shapes an answer can take — pure functions over the facts ask.answer() gathered.

Every function here takes plain data and returns plain data (no I/O, no reflection): Rust-ready, like ask.py.
Nothing is invented: a tutorial step, a quiz question, a viewpoint, a timeline row or a verdict is always built from a
fact an application returned, and carries where it came from. Feature numbers are the Composite Feature Registry v71
(docs/querybook-rebuild/feature-inventory-v71.csv).
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- the catalogue shown on the Ask page
INPUTS: list[dict] = [
    {"id": "type", "name": "Type", "features": [1, 362], "about": "Type a question, a word, a name or a calculation."},
    {"id": "speak", "name": "Speak", "features": [167, 96], "about": "Say the question; the microphone is used only while you hold the button."},
    {"id": "camera", "name": "Live camera", "features": [105, 166], "about": "Point the camera at things; QueryBook names what it sees and answers about it."},
    {"id": "video", "name": "Video file", "features": [353, 74], "about": "Open a video; QueryBook finds what appears and when, and answers about it."},
    {"id": "photo", "name": "Photo", "features": [74, 294], "about": "Open a picture; QueryBook names what is in it and answers about it."},
    {"id": "check", "name": "Paste text to check", "features": [110, 114], "about": "Paste any text (an article, another AI's answer); each claim is checked against the facts."},
    {"id": "structured", "name": "Structured query", "features": [19, 66], "about": "Name a subject and what you want to know about it, e.g. Marie Curie + award."},
    {"id": "watch", "name": "Watch a question", "features": [78], "about": "Save a question; QueryBook asks it again and shows you when the answer changes."},
]
MODES: list[dict] = [
    {"id": "qa", "name": "Q&A", "features": [1, 362], "about": "A direct answer with every fact's source."},
    {"id": "guided", "name": "Guided follow-ups", "features": [2, 68], "about": "Ask follow-ups (\"when was it built?\"); earlier questions keep shaping the answer."},
    {"id": "discussion", "name": "Discussion", "features": [3, 119], "about": "What each source says, where they agree and where they differ, with how well grounded each is."},
    {"id": "tutorial", "name": "Tutorial", "features": [4, 113], "about": "The subject taught in steps, simplest first, each step from a fact."},
    {"id": "quiz", "name": "Quiz", "features": [5], "about": "Questions made from the facts; answer and see whether you were right, with the fact."},
    {"id": "flashcards", "name": "Flashcards", "features": [9], "about": "Study cards from the facts; flip each one."},
    {"id": "explore", "name": "Explore connections", "features": [6], "about": "The people, places and things this subject is connected to; follow any of them."},
    {"id": "verify", "name": "Check a claim", "features": [114, 110], "about": "Say something you believe; see whether the facts support it, contradict it, or are silent."},
]
FORMATS: list[dict] = [
    {"id": "auto", "name": "Best for the topic", "features": [69, 202]},
    {"id": "short", "name": "Short answer", "features": [200]},
    {"id": "full", "name": "Full, with sources", "features": [1]},
    {"id": "table", "name": "Table", "features": [19]},
    {"id": "timeline", "name": "Timeline", "features": [252]},
    {"id": "steps", "name": "Step by step", "features": [4]},
    {"id": "cards", "name": "Cards", "features": [9]},
    {"id": "spoken", "name": "Spoken", "features": [107]},
]
REGISTERS: list[dict] = [
    {"id": "plain", "name": "Plain"},
    {"id": "formal", "name": "Formal"},
    {"id": "academic", "name": "Academic"},
    {"id": "child", "name": "For a child"},
]

QID = re.compile(r"\s*\(Q\d+\)")
YEAR = re.compile(r"(?<!\d)(-?\d{3,4})(?!\d)")
PERSON = ("date of birth", "place of birth", "date of death", "occupation", "sex or gender", "father", "mother", "spouse", "born", "died")
PLACE = ("coordinate location", "country", "located in", "population", "capital", "continent", "area", "elevation")
CHEM = ("chemical formula", "molar mass", "mass", "density", "melting point", "boiling point", "atomic number", "element symbol", "formula")
WHEN = ("date", "time", "inception", "year", "founded", "born", "birth", "death", "publication", "start", "end", "invention", "discover")
DEFINE = ("instance of", "subclass of", "description", "is a", "category", "type")
PRONOUNS = ("it", "its", "he", "she", "they", "them", "his", "her", "their", "this", "that", "there")


def clean(s: object) -> str:
    """'Johannes Gutenberg (Q8958)' -> 'Johannes Gutenberg'"""
    return " ".join(QID.sub("", str(s or "")).split())


def norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w\s.-]", " ", clean(s).lower()).split())


def fact_value(f: dict) -> str:
    return clean(f.get("object") or f.get("statement") or "")


def year_of(f: dict) -> int | None:
    """the year a fact is about: its date field, else a 3-4 digit year in a date-like value"""
    p = str(f.get("predicate") or "").lower()
    datelike = any(w in p for w in WHEN) and not p.startswith(("place", "cause", "manner"))
    for v in (f.get("date"), f.get("object") if datelike else None):
        m = YEAR.search(clean(v))
        if m:
            return int(m.group(1))
    return None


def facts_of(sections: list[dict]) -> list[dict]:
    for s in sections:
        if s.get("kind") == "facts":
            return list(s.get("items") or [])
    return []


def kind_of(sections: list[dict], kind: str) -> dict | None:
    for s in sections:
        if s.get("kind") == kind:
            return s
    return None


# --------------------------------------------------------------------------- format: chosen by the topic
def topic(intent: dict, sections: list[dict]) -> str:
    """math, word, person, place, chemistry, event (dated facts) or general"""
    if intent.get("kind") == "math" or kind_of(sections, "math"):
        return "math"
    facts = facts_of(sections)
    preds = [str(f.get("predicate") or "").lower() for f in facts]

    def has(words: tuple[str, ...]) -> int:
        return sum(1 for p in preds if any(w in p for w in words))
    if intent.get("kind") == "word" and kind_of(sections, "word"):
        return "word"
    if has(PERSON) >= 2:
        return "person"
    if has(CHEM) >= 2:
        return "chemistry"
    if has(PLACE) >= 2:
        return "place"
    if sum(1 for f in facts if year_of(f) is not None) >= 3:
        return "event"
    if kind_of(sections, "word") and not facts:
        return "word"
    return "general"


AUTO = {"math": "steps", "word": "cards", "person": "profile", "place": "profile", "chemistry": "table", "event": "timeline", "general": "full"}


def choose_format(fmt: str, intent: dict, sections: list[dict]) -> str:
    """the format asked for, or for 'auto' the one that suits the topic (Registry #69 vocabulary and structure by audience)"""
    known = [f["id"] for f in FORMATS] + ["profile"]
    if fmt and fmt != "auto" and fmt in known:
        return fmt
    return AUTO.get(topic(intent, sections), "full")


def timeline(facts: list[dict]) -> list[dict]:
    """dated facts in order, earliest first (each row keeps its source)"""
    rows = []
    for i, f in enumerate(facts):
        y = year_of(f)
        if y is not None:
            rows.append({"year": y, "text": "%s — %s: %s" % (clean(f.get("subject")), f.get("predicate") or "", fact_value(f)),
                         "where": f.get("where") or "", "order": i})
    rows.sort(key=lambda r: (r["year"], r["order"]))
    return rows


def profile(facts: list[dict]) -> list[dict]:
    """one line per kind of fact (the first value of each predicate), the defining ones first"""
    seen: dict[str, dict] = {}
    for f in facts:
        p = str(f.get("predicate") or "").strip()
        if p and p.lower() not in seen:
            seen[p.lower()] = {"label": p, "value": fact_value(f), "where": f.get("where") or ""}
    rows = list(seen.values())
    rows.sort(key=lambda r: 0 if any(w in r["label"].lower() for w in DEFINE) else 1)
    return rows


def map_link(facts: list[dict]) -> str:
    """an OpenStreetMap link for the first coordinate among the facts, else empty"""
    for f in facts:
        if "coordinate" in str(f.get("predicate") or "").lower():
            nums = re.findall(r"-?\d+(?:\.\d+)?", str(f.get("object") or ""))
            if len(nums) >= 2:
                a, b = float(nums[0]), float(nums[1])
                lat, lon = (b, a) if "point(" in str(f.get("object") or "").lower() else (a, b)   # WKT Point(lon lat)
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    return "https://www.openstreetmap.org/?mlat=%s&mlon=%s#map=10/%s/%s" % (lat, lon, lat, lon)
    return ""


LEAD = {
    "plain": "{s}",
    "formal": "According to the sources held, {s}",
    "academic": "The recorded evidence indicates the following: {s}",
    "child": "Here is the answer, simply: {s}",
}


def in_register(short: str, register: str) -> str:
    """the short answer said in the chosen register (Registry #200: exactly one register per answer); the fact itself is
    never reworded — only the frame around it changes, so nothing is added that a source did not say"""
    if not short:
        return short
    s = short
    if register == "child":
        s = re.sub(r"\s*\([^)]*\)", "", s)               # brackets and codes are the first thing a child stumbles on
        if len(s) > 160:
            cut = s[:160]
            s = cut[:cut.rfind(" ")] + "…" if " " in cut else cut + "…"
    return LEAD.get(register, "{s}").replace("{s}", s)


# --------------------------------------------------------------------------- tutorial, quiz, flashcards
def difficulty(f: dict) -> int:
    """1 = what it is, 2 = when and where, 3 = who and how, 4 = everything else (more specialised)"""
    p = str(f.get("predicate") or "").lower()
    if any(w in p for w in DEFINE):
        return 1
    if any(w in p for w in WHEN + ("country", "location", "place")):
        return 2
    if any(w in p for w in ("inventor", "founder", "author", "creator", "discoverer", "developer", "member", "part of", "uses")):
        return 3
    return 4


STEP_TITLE = {1: "What it is", 2: "When and where", 3: "Who and how", 4: "Going further"}


def tutorial(intent: dict, sections: list[dict], limit: int = 12) -> list[dict]:
    """ordered steps of increasing difficulty (Registry #4); the meaning first when Language Builder has one"""
    steps: list[dict] = []
    w = kind_of(sections, "word")
    if w:
        for it in w.get("items") or []:
            if it.get("text") and it.get("word"):
                steps.append({"level": 1, "title": "What the word means", "text": "%s: %s" % (it["word"], str(it["text"]).split("\n")[0][:300]),
                              "where": it.get("source") or "Language Builder"})
                break
    m = kind_of(sections, "math")
    if m:
        for it in m.get("items") or []:
            steps.append({"level": 1, "title": "The result", "text": str(it.get("text") or ""), "where": "Math, Science & Engineering"})
            if it.get("how"):
                steps.append({"level": 2, "title": "How it is worked out", "text": str(it["how"]), "where": "Math, Science & Engineering"})
    used: set[str] = set()
    for f in sorted(facts_of(sections), key=difficulty):
        key = str(f.get("predicate") or "").lower()
        if key in used or not fact_value(f):
            continue
        used.add(key)
        lv = difficulty(f)
        steps.append({"level": lv, "title": STEP_TITLE[lv], "text": "%s — %s: %s" % (clean(f.get("subject")), f.get("predicate"), fact_value(f)),
                      "where": f.get("where") or ""})
        if len(steps) >= limit:
            break
    for i, s in enumerate(steps):
        s["n"] = i + 1
    return steps


def _mix(seed: int, i: int) -> int:
    """a small deterministic mixer (same inputs, same quiz) — Rust: wrapping u32 arithmetic"""
    x = (seed * 1103515245 + 12345 + i * 2654435761) & 0xFFFFFFFF
    x ^= x >> 13
    return (x * 1597334677) & 0xFFFFFFFF


def quiz(facts: list[dict], n: int = 5, seed: int = 0) -> list[dict]:
    """questions made from facts (Registry #5): 'What is the <predicate> of <subject>?' with up to three other values
    held for other questions as choices. The answer is the fact's own value; the fact is shown after answering."""
    pool = []
    seen: set[str] = set()
    for f in facts:
        v, p, s = fact_value(f), str(f.get("predicate") or "").strip(), clean(f.get("subject"))
        if not v or not p or not s or len(v) > 80 or p.lower() in seen:
            continue
        seen.add(p.lower())
        pool.append({"subject": s, "predicate": p, "answer": v, "where": f.get("where") or ""})
    values = [q["answer"] for q in pool]
    out = []
    for i, q in enumerate(pool[:n]):
        others = [v for v in values if norm(v) != norm(q["answer"])]
        picks: list[str] = []
        for j in range(len(others)):
            if len(picks) >= 3:
                break
            cand = others[_mix(seed, i * 7 + j) % len(others)]
            if cand not in picks:
                picks.append(cand)
        choices = picks + [q["answer"]]
        k = _mix(seed, 1000 + i) % len(choices)
        choices[k], choices[-1] = choices[-1], choices[k]
        out.append({"n": i + 1, "question": "What is the %s of %s?" % (q["predicate"], q["subject"]), "choices": choices,
                    "answer": q["answer"], "where": q["where"]})
    return out


def grade(given: str, expected: str) -> dict:
    """right, nearly right (most of the words) or not right — words compared, case and punctuation ignored"""
    g, e = norm(given), norm(expected)
    if not g:
        return {"verdict": "blank", "score": 0.0, "expected": expected}
    if g == e:
        return {"verdict": "right", "score": 1.0, "expected": expected}
    gw, ew = set(g.split()), set(e.split())
    score = len(gw & ew) / max(1, len(ew))
    if e and (e in g or (len(g) >= 4 and g in e)):
        score = max(score, 0.8)
    verdict = "right" if score >= 0.99 else "nearly" if score >= 0.6 else "wrong"
    return {"verdict": verdict, "score": round(score, 2), "expected": expected}


def flashcards(intent: dict, sections: list[dict], limit: int = 20) -> list[dict]:
    cards = []
    w = kind_of(sections, "word")
    if w:
        for it in w.get("items") or []:
            if it.get("word") and it.get("text"):
                cards.append({"front": str(it["word"]), "back": str(it["text"]).split("\n")[0][:300], "where": it.get("source") or "Language Builder"})
            if it.get("translations"):
                for lang, words in list(it["translations"].items())[:6]:
                    vals = words if isinstance(words, list) else [words]
                    cards.append({"front": "%s in %s" % (intent.get("subject") or "", lang), "back": ", ".join(str(x) for x in vals[:3]),
                                  "where": "Language Builder"})
    for q in quiz(facts_of(sections), limit, 0):
        cards.append({"front": q["question"], "back": q["answer"], "where": q["where"]})
    return cards[:limit]


# --------------------------------------------------------------------------- discussion: what each source says
GROUNDED = ("verified", "corroborated", "accepted", "trusted", "filed")


def discussion(facts: list[dict], threshold: float = 0.5) -> dict:
    """Registry #3: each source a viewpoint, with how well grounded it is (the share of its facts verified or corroborated,
    or held in a documented dataset); where sources agree (same thing, same value) and where they differ (same thing,
    different values). A viewpoint below the threshold is shown as not grounded enough to adopt."""
    by: dict[str, list[dict]] = {}
    for f in facts:
        by.setdefault(str(f.get("where") or "unknown source"), []).append(f)
    views = []
    for src, fs in by.items():
        ok = sum(1 for f in fs if str(f.get("status") or "").lower() in GROUNDED or (not f.get("status") and src not in ("unknown source",)))
        g = round(ok / max(1, len(fs)), 2)
        views.append({"source": src, "facts": len(fs), "groundedness": g, "adopted": g >= threshold,
                      "says": ["%s: %s" % (f.get("predicate") or "", fact_value(f)) for f in fs[:6]]})
    views.sort(key=lambda v: (-v["groundedness"], -v["facts"], v["source"]))
    claims: dict[str, dict[str, list[str]]] = {}
    for f in facts:
        p = str(f.get("predicate") or "").strip().lower()
        v = norm(fact_value(f))
        if p and v:
            claims.setdefault(p, {}).setdefault(v, [])
            src = str(f.get("where") or "")
            if src not in claims[p][v]:
                claims[p][v].append(src)
    agree, differ = [], []
    for p, vals in claims.items():
        if len(vals) == 1:
            (v, srcs), = vals.items()
            if len(srcs) >= 2:
                agree.append({"about": p, "value": v, "sources": srcs})
        elif p not in ("instance of", "subclass of", "occupation", "award received", "child", "member of", "part of", "has part", "has part(s)"):
            differ.append({"about": p, "values": [{"value": v, "sources": s} for v, s in vals.items()][:6]})
    return {"viewpoints": views, "agree": agree[:12], "differ": differ[:12], "threshold": threshold}


# --------------------------------------------------------------------------- explore connections
def connections(intent: dict, facts: list[dict], limit: int = 24) -> list[dict]:
    """Registry #6: the named things this subject's facts point to (values that are names, not numbers or dates), ranked by
    how many facts link to them; each can be asked about next"""
    subj = norm(intent.get("subject") or "")
    count: dict[str, dict] = {}
    for f in facts:
        raw = str(f.get("object") or "")
        v = clean(raw)
        if not v or len(v) > 60 or YEAR.fullmatch(v.strip()) or re.fullmatch(r"[-+\d.,:/ %eE]+", v) or norm(v) == subj:
            continue
        named = bool(QID.search(raw)) or v[:1].isupper()
        if not named:
            continue
        k = v.lower()
        c = count.setdefault(k, {"name": v, "links": 0, "how": []})
        c["links"] += 1
        p = str(f.get("predicate") or "")
        if p and p not in c["how"]:
            c["how"].append(p)
    rows = sorted(count.values(), key=lambda c: (-c["links"], c["name"]))
    top = rows[0]["links"] if rows else 1
    for r in rows:
        r["strength"] = round(r["links"] / max(1, top), 2)
    return rows[:limit]


# --------------------------------------------------------------------------- guided follow-ups
def turn_weight(distance: int, lam: float = 0.6) -> float:
    """Registry #2: an earlier question's weight falls with distance, w(d) = lam^d, 0 < lam < 1, so w(5) < w(1)"""
    return round(lam ** max(0, distance), 4)


def follow_up(question: str, turns: list[dict]) -> dict:
    """A follow-up like "when was it built?" uses the subject of the most recent earlier turn that had one. Returns the
    question to ask (pronoun replaced) and the earlier turns with their weights, nearest first."""
    q = " ".join((question or "").split())
    weights = [{"question": t.get("question") or "", "subject": t.get("subject") or "", "weight": turn_weight(i + 1)}
               for i, t in enumerate(reversed(turns[-6:]))]
    subject = next((w["subject"] for w in weights if w["subject"]), "")
    words = q.split()
    uses = [i for i, w in enumerate(words) if w.lower().strip("?,.!") in PRONOUNS]
    if subject and uses:
        i = uses[0]
        tail = words[i][len(words[i].rstrip("?,.!")):]
        poss = words[i].lower().strip("?,.!") in ("its", "his", "her", "their")
        words[i] = subject + ("'s" if poss else "") + tail
        return {"question": " ".join(words), "resolved": subject, "earlier": weights}
    if subject and len(words) <= 3 and not any(w[:1].isupper() for w in words):   # "and the inventor?" -> about the same subject
        return {"question": q.rstrip("?") + " of " + subject + "?", "resolved": subject, "earlier": weights}
    return {"question": q, "resolved": "", "earlier": weights}


def clarify(intent: dict, sections: list[dict]) -> str:
    """Registry #68: one clarifying question when the subject names several different things, else empty"""
    facts = facts_of(sections)
    subj = norm(intent.get("subject") or "")
    if not subj or intent.get("kind") == "math":
        return ""
    names: dict[str, str] = {}
    for f in facts:
        raw = str(f.get("subject") or "")
        m = re.search(r"\((Q\d+)\)", raw)
        if m and norm(raw) == subj:
            names.setdefault(m.group(1), clean(raw))
    if len(names) < 2:
        return ""
    descr: dict[str, str] = {}
    for f in facts:
        m = re.search(r"\((Q\d+)\)", str(f.get("subject") or ""))
        if m and m.group(1) in names and str(f.get("predicate") or "").lower() in ("instance of", "description", "occupation"):
            descr.setdefault(m.group(1), fact_value(f))
    opts = ["%s (%s)" % (names[k], descr[k]) if k in descr else "%s [%s]" % (names[k], k) for k in list(names)[:4]]
    return "Which one do you mean: " + "; ".join(opts) + "?"


# --------------------------------------------------------------------------- checking claims
def split_claims(text: str, limit: int = 20) -> list[str]:
    """sentences of a pasted text that state something (questions and very short fragments are skipped)"""
    t = " ".join((text or "").split())
    parts = re.split(r"(?<=[.!;?])\s+(?=[A-Z0-9\"“])", t)
    return [p.strip() for p in parts if len(p.split()) >= 3 and not p.strip().endswith("?")][:limit]


def claim_subject(claim: str) -> str:
    """the subject of a statement: the words before its first verb ('The printing press was invented in 1440' ->
    'The printing press' -> 'printing press')"""
    words = claim.rstrip(".!;").split()
    verbs = ("is", "was", "are", "were", "has", "had", "invented", "discovered", "founded", "wrote", "built", "created",
             "became", "died", "lived", "won", "made", "developed", "designed", "began", "started", "contains", "means")
    for i, w in enumerate(words):
        if w.lower() in verbs and i > 0:
            s = words[:i]
            while s and s[0].lower() in ("the", "a", "an"):
                s = s[1:]
            return " ".join(s).strip(" ,\"“”")
    return ""


def verdict(claim: str, facts: list[dict]) -> dict:
    """VERIFIED when a fact about the claim's subject has a value the claim states; CONTRADICTED when facts about that
    subject give a different value for the very thing the claim's words name (e.g. a different year of invention);
    otherwise UNKNOWN. The facts that decided it are returned with their sources."""
    c = norm(claim)
    cwords = set(c.split())
    support, against = [], []
    for f in facts:
        v = norm(fact_value(f))
        p = norm(str(f.get("predicate") or ""))
        if not v:
            continue
        if (len(v) >= 3 or v.isdigit()) and re.search(r"(?<![\w])" + re.escape(v) + r"(?![\w])", c):
            support.append(f)
            continue
        pw = [w for w in p.split() if len(w) >= 4 and w not in ("time", "date", "point")]
        stems = {w[:5] for w in cwords if len(w) >= 5}
        named = any(w in cwords or (len(w) >= 5 and w[:5] in stems) for w in pw)
        claim_years = set(YEAR.findall(c))
        if named and ((claim_years and YEAR.search(v)) or (not claim_years and not YEAR.search(v))):
            against.append(f)
    if support:
        state = "VERIFIED"
    elif against:
        state = "CONTRADICTED"
    else:
        state = "UNKNOWN"
    pick = support if support else against
    return {"claim": claim, "verdict": state,
            "facts": [{"text": "%s — %s: %s" % (clean(f.get("subject")), f.get("predicate") or "", fact_value(f)), "where": f.get("where") or ""}
                      for f in pick[:4]]}


# --------------------------------------------------------------------------- what the camera / a video / a photo saw
def seen_summary(detections: list[dict], min_score: float = 0.4) -> list[dict]:
    """detections [{label, score, t}] -> one row per thing: how many times seen, first and last time, best score"""
    rows: dict[str, dict] = {}
    for d in detections:
        lab = str(d.get("label") or "").strip().lower()
        sc = float(d.get("score") or 0)
        if not lab or sc < min_score:
            continue
        t = float(d.get("t") or 0)
        r = rows.setdefault(lab, {"label": lab, "count": 0, "first": t, "last": t, "best": 0.0})
        r["count"] += 1
        r["first"] = min(r["first"], t)
        r["last"] = max(r["last"], t)
        r["best"] = max(r["best"], round(sc, 2))
    return sorted(rows.values(), key=lambda r: (-r["count"], r["first"], r["label"]))


def seen_answer(question: str, rows: list[dict]) -> str:
    """'when does the dog appear?', 'is there a cup?', 'what is in the video?' answered from what was detected"""
    q = norm(question)
    if not rows:
        return "Nothing was recognised yet."
    for r in rows:
        if r["label"] in q or (r["label"] + "s") in q:
            if q.startswith(("when", "at what", "what time")):
                return "A %s appears from %s to %s (seen %d time%s)." % (r["label"], clock(r["first"]), clock(r["last"]), r["count"], "" if r["count"] == 1 else "s")
            return "Yes — a %s, seen %d time%s, first at %s." % (r["label"], r["count"], "" if r["count"] == 1 else "s", clock(r["first"]))
    if any(w in q.split() for w in ("what", "which", "everything", "list")):
        return "Seen: " + ", ".join("%s (%d)" % (r["label"], r["count"]) for r in rows[:12]) + "."
    return "That was not recognised. Seen: " + ", ".join(r["label"] for r in rows[:8]) + "."


def clock(t: float) -> str:
    s = int(max(0, t))
    return "%d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60) if s >= 3600 else "%d:%02d" % (s // 60, s % 60)


def structured(subject: str, want: str) -> str:
    """the structured query (subject + what to know) as the question ask.understand() reads"""
    s, w = " ".join((subject or "").split()), " ".join((want or "").split())
    if not s:
        return ""
    return ("what is the %s of %s" % (w, s)) if w else s


def apply_want(facts: list[dict], want: str) -> list[dict]:
    """the structured query's 'what to know' keeps only the facts whose predicate names it"""
    w = norm(want)
    if not w:
        return facts
    return [f for f in facts if w in norm(str(f.get("predicate") or ""))]


def changed(before: dict, after: dict) -> bool:
    """a watched question's answer changed: its short answer, or the set of facts behind it"""
    return (before.get("short") or "") != (after.get("short") or "") or sorted(before.get("facts") or []) != sorted(after.get("facts") or [])


# --------------------------------------------------------------------------- one answer, shaped for the mode and format
def compose(r: dict, mode: str, fmt: str, register: str, want: str, seed: int) -> dict:
    """ask.answer()'s result -> the same result plus what the chosen mode and format need. Pure: the facts are not
    changed, only arranged (and narrowed to 'want' for a structured query)."""
    out = dict(r)
    sections = [dict(s) for s in (r.get("sections") or [])]
    intent = r.get("understood") or {}
    if want:
        for s in sections:
            if s.get("kind") == "facts":
                s["items"] = apply_want(list(s.get("items") or []), want)
        sections = [s for s in sections if s.get("kind") != "facts" or s.get("items")]
    out["sections"] = sections
    facts = facts_of(sections)
    out["mode"] = mode if mode in [m["id"] for m in MODES] else "qa"
    out["topic"] = topic(intent, sections)
    out["format"] = choose_format(fmt, intent, sections)
    out["register"] = register if register in [x["id"] for x in REGISTERS] else "plain"
    out["said"] = in_register(r.get("short") or "", out["register"])
    out["clarify"] = clarify(intent, sections)
    view: dict = {}
    f_ = out["format"]
    if f_ == "timeline":
        view["timeline"] = timeline(facts)
    if f_ == "profile":
        view["profile"] = profile(facts)
        view["map"] = map_link(facts)
        view["timeline"] = timeline(facts)
    if f_ == "steps":
        view["steps"] = tutorial(intent, sections)
    if f_ == "cards":
        view["cards"] = flashcards(intent, sections)
    if f_ == "table":
        view["profile"] = profile(facts)
    m_ = out["mode"]
    if m_ == "tutorial":
        view["steps"] = tutorial(intent, sections)
    if m_ == "quiz":
        view["quiz"] = quiz(facts, 6, seed)
    if m_ == "flashcards":
        view["cards"] = flashcards(intent, sections)
    if m_ == "discussion":
        view["discussion"] = discussion(facts)
    if m_ == "explore":
        view["connections"] = connections(intent, facts)
    if m_ == "verify":
        view["verdict"] = verdict(str(r.get("claim") or r.get("question") or ""), facts)
    out["view"] = view
    return out
