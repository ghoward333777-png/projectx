"""The one Ask box: understands the question, asks every application at once, and composes a cited answer.

understand() and rank() are pure functions (Rust-ready: plain data in and out, no I/O). answer() does the asking:
  * Language Builder  GET  /api/lookup?q=          word meanings (Webster 1913) and translations
  * Math, Science & E. POST /api/ask {q}            calculations, conversions, molar masses, elements
  * History & News    GET  /api/facts?q=           sourced historical facts
  * Control Panel     POST /api/commons/facts {q}  the shared facts (with status and evidence)
                      GET  /api/bulk/search?q=     the bulk datasets (Wikidata, PubChem, ...): subjects are stored as
                                                   "Label (Q123)", so the subject is looked up by its name as a prefix
Nothing is invented: every line of the answer is a fact one of the applications returned, with where it came from.
"""
from __future__ import annotations

import json
import re
import threading
from typing import Callable
import urllib.parse
import urllib.request

import sense

LEADS = (
    "what is the meaning of", "what's the meaning of", "what does", "meaning of", "definition of", "define", "how do you say",
    "tell me about", "who invented", "who discovered", "who founded", "who wrote", "who created", "who was", "who is",
    "when was", "when did", "when is", "where is", "where was", "where did", "what is", "what was", "what are", "what were",
    "how old is", "how many", "how much", "which", "who", "when", "where", "what",
)
TRAILS = ("mean", "means", "invented", "discovered", "founded", "born", "built", "written", "created", "made", "first made",
          "started", "begin", "began", "die", "died", "located", "published", "released", "happen", "happened")
ARTICLES = ("the", "a", "an")
HINTS = {  # question word / verb -> words that appear in the predicates that answer it
    "when": ("date", "time", "inception", "year", "founded", "start", "point in time", "publication", "born", "birth", "death", "discover", "invention"),
    "who": ("inventor", "discoverer", "founder", "creator", "author", "developer", "designer", "architect", "manufacturer"),
    "where": ("location", "country", "place", "located", "headquarters", "coordinate", "region", "continent"),
    "invented": ("inventor", "invention", "discover", "inception", "date"),
    "discovered": ("discoverer", "discover", "date"),
    "founded": ("founder", "inception", "founded", "date"),
    "born": ("birth", "born"),
    "died": ("death", "died"),
}
MATH = re.compile(r"(\d\s*[-+*/×÷^%]\s*\d)|(\d+(\.\d+)?\s*[a-zA-Zµ°/]+\s+(to|in)\s+[a-zA-Zµ°/]+)|^(molar mass|molecular weight|element|convert|sqrt|solve)\b|\d\s*[=]", re.I)


def understand(question: str) -> dict:
    """The kind of question, the subject to look up (with variants) and the predicate words that would answer it."""
    q = " ".join((question or "").strip().split())
    low = q.lower().rstrip("?!. ")
    if not low:
        return {"question": q, "kind": "empty", "subject": "", "variants": [], "hints": []}
    if MATH.search(low):
        return {"question": q, "kind": "math", "subject": q, "variants": [q], "hints": []}
    hints: list[str] = []
    s = low
    for lead in LEADS:
        if s.startswith(lead + " ") or s == lead:
            first = lead.split()[0]
            hints += list(HINTS.get(first, ()))
            for w in lead.split()[1:]:
                hints += list(HINTS.get(w, ()))
            s = s[len(lead):].strip()
            break
    words = s.split()
    while words and words[0] in ARTICLES + ("is", "was", "are", "were", "did", "does", "do"):
        words = words[1:]
    trailed = False
    while words and words[-1] in TRAILS:
        hints += list(HINTS.get(words[-1], ()))
        words = words[:-1]
        trailed = True
    if not trailed and low.startswith(("who is ", "who was ", "who are ", "who were ", "what is ", "what was ", "tell me about ")):
        hints = []                                   # "Who was Babe Ruth?" asks who he WAS, not who invented him
    subject = " ".join(words).strip(" '\"“”")
    m = re.search(re.escape(subject), q, re.I) if subject else None
    if m:                                            # keep the case the question used ("DNA", "Marie Curie")
        subject = m.group(0)
    wh = low.split()[0]
    if wh in ("when", "who", "where"):               # the question word decides: "when … invented" wants a date, not the inventor
        hints = [h for h in hints if h in HINTS[wh]] or hints
    kind = "word" if (len(words) == 1 and ("mean" in low or "defin" in low or len(low.split()) == 1)) else "fact"
    if "mean" in low or low.startswith(("define", "definition")):
        kind = "word" if len(words) <= 3 else kind
    variants = list(dict.fromkeys(v for v in (subject, subject[:1].upper() + subject[1:], subject.title(),
                                              subject[:1].upper() + subject[1:].lower()) if v))
    return {"question": q, "kind": kind, "subject": subject, "variants": variants, "hints": list(dict.fromkeys(hints))}


def rank(facts: list[dict], intent: dict) -> list[dict]:
    """Facts whose predicate matches what was asked first; then facts about exactly that subject; stable otherwise."""
    hints = intent.get("hints") or []
    subj = (intent.get("subject") or "").lower()

    def score(f: dict) -> tuple[int, int]:
        pred = str(f.get("predicate") or "").lower()
        s = str(f.get("subject") or "").lower()
        exact = 1 if (s == subj or s.startswith(subj + " (")) else 0
        return (-(1 if any(h in pred for h in hints) else 0), -exact)

    return sorted(facts, key=score)


def short_answer(intent: dict, facts: list[dict]) -> str:
    """One plain sentence from the best-matching fact, or empty when no fact matches the question's predicate."""
    hints = intent.get("hints") or []
    for f in facts:
        pred = str(f.get("predicate") or "")
        if hints and any(h in pred.lower() for h in hints):
            subj = re.sub(r"\s*\(Q\d+\)$", "", str(f.get("subject") or ""))
            obj = re.sub(r"\s*\(Q\d+\)", "", str(f.get("object") or ""))
            return "%s — %s: %s" % (subj, pred, obj)
    return ""


# --------------------------------------------------------------------------- asking the applications (I/O)
def _get(url: str, timeout: float = 6.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(url: str, body: dict, timeout: float = 6.0) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def answer(question: str, urls: dict[str, str]) -> dict:
    intent = understand(question)
    out: dict = {"question": intent["question"], "understood": intent, "short": "", "sections": [], "asked": [], "unavailable": []}
    if intent["kind"] == "empty":
        return out
    results: dict[str, object] = {}
    jobs = []

    def run(name: str, fn: Callable[[], object]) -> None:
        try:
            results[name] = fn()
        except Exception as e:                       # one application being slow or stopped never blocks the others
            results[name] = {"_error": "%s" % e}

    def base(pid: str) -> str | None:
        u = urls.get(pid)
        return u.rstrip("/") if u else None

    if intent["kind"] == "math" and base("stem"):
        jobs.append(("stem", lambda: _post(base("stem") + "/api/ask", {"q": intent["question"]})))
    if intent["kind"] in ("word", "fact") and base("language") and intent["subject"]:
        jobs.append(("language", lambda: _get(base("language") + "/api/lookup?" + urllib.parse.urlencode({"q": intent["subject"]}))))
    if intent["kind"] == "fact":
        if base("facts"):
            jobs.append(("history", lambda: _get(base("facts") + "/api/facts?" + urllib.parse.urlencode({"q": intent["subject"], "limit": 20}))))
        if base("control"):
            jobs.append(("commons", lambda: _post(base("control") + "/api/panel/search", {"q": intent["subject"], "limit": 20})))

            def bulk() -> dict:
                found: list[dict] = []
                for v in intent["variants"][:3]:
                    r = _get(base("control") + "/api/bulk/search?" + urllib.parse.urlencode({"q": v, "limit": 60}), timeout=15)
                    found += [f for f in (r.get("facts") or []) if f not in found]
                    if len(found) >= 60:
                        break
                return {"facts": found}

            def entity() -> dict:
                """who or what is meant: every thing with this name, best known first, with all its facts (engine 1.40);
                an older engine has no such route, and then the prefix search above answers as before"""
                try:
                    r = _get(base("control") + "/api/bulk/entity?" + urllib.parse.urlencode({"q": intent["subject"], "top": 6}), timeout=20)
                    if r.get("entities"):
                        return {"facts": r.get("facts") or [], "entities": r.get("entities") or []}
                except Exception:
                    pass
                r = bulk()
                r["prefix_only"] = True                 # nothing is named this: only names that BEGIN with the words were found
                return r
            jobs.append(("bulk", entity))
    threads = [threading.Thread(target=run, args=job, daemon=True) for job in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    out["asked"] = [j[0] for j in jobs]
    for name, r in results.items():
        if isinstance(r, dict) and r.get("_error"):
            out["unavailable"].append({"source": name, "reason": r["_error"]})

    stem = results.get("stem")
    if isinstance(stem, dict) and not stem.get("_error") and stem.get("answer"):
        out["short"] = str(stem.get("display") or stem.get("answer"))
        out["sections"].append({"source": "Math, Science & Engineering", "app": "stem", "kind": "math",
                                "items": [{"text": stem.get("display") or stem.get("answer"), "how": stem.get("method"), "exact": stem.get("exact")}]})
    lang = results.get("language")
    if isinstance(lang, dict) and not lang.get("_error"):
        eng = lang.get("english") or {}
        items = []
        if eng.get("definition"):
            items.append({"text": eng["definition"], "word": eng.get("word"), "pos": eng.get("part_of_speech"),
                          "source": "Webster's Revised Unabridged Dictionary (1913, public domain)"})
        tr = {k: v for k, v in (eng.get("translations") or {}).items() if v}
        if tr:
            items.append({"translations": tr})
        for f in lang.get("foreign") or []:
            items.append({"text": "%s (%s) means: %s" % (f.get("word"), f.get("language"), ", ".join(f.get("english") or []))})
        if items:
            out["sections"].append({"source": "Language Builder", "app": "language", "kind": "word", "items": items})
            if intent["kind"] == "word" and eng.get("definition") and not out["short"]:
                out["short"] = "%s: %s" % (eng.get("word"), eng["definition"].split("\n")[0][:400])
    facts: list[dict] = []
    com = results.get("commons")
    if isinstance(com, dict) and not com.get("_error"):
        for f in com.get("facts") or []:
            facts.append({"subject": f.get("subject"), "predicate": f.get("predicate"), "object": f.get("object"),
                          "statement": f.get("statement"), "where": "Shared facts (Commons)", "status": f.get("status"), "id": f.get("id")})
    bulk = results.get("bulk")
    if isinstance(bulk, dict) and not bulk.get("_error"):
        bfacts = [dict({"subject": f.get("subject"), "predicate": f.get("predicate"), "object": f.get("object"),
                        "where": f.get("dataset"), "status": f.get("status"), "link": f.get("link"), "provenance": f.get("provenance")},
                       **{k: f[k] for k in ("start", "end", "at", "rank", "qualifiers", "sources") if f.get(k)},     # 1.7.8: its dates, rank, sources
                       **({"context_read": bool(f["context_read"])} if "context_read" in f else {}))               # 1.8.1: False -> Fill Dates is offered
                  for f in bulk.get("facts") or []]
        if bulk.get("entities"):                     # a grasp of reality: which match is meant, and what kind of thing it is
            judged = sense.answer_for(intent["question"], intent["subject"], bulk["entities"], bfacts)
            out["entity"] = judged["entity"]
            out["missing"] = judged["missing"]
            out["known_for"] = judged.get("known_for") or {}
            if judged["said"] and not intent["hints"] and not out["short"] and not judged["missing"]:
                out["short"] = judged["said"]
            out["identity"] = judged["said"]
            bfacts = judged["facts"]
        elif bulk.get("prefix_only") and bfacts and intent["subject"]:
            # 1.43: "Dodgers" found only "Dodgers–Giants rivalry", "Dodgers Stadium"...: shown, but said plainly, and the
            # subject itself is sent for (it used to pass as an answer, so nothing went and fetched the team)
            exact = intent["subject"].casefold()
            if not any(sense.clean(f.get("subject")).casefold() == exact for f in bfacts):
                out["missing"] = ("QueryBook holds nothing named “%s” itself yet — only things whose names begin with it, listed below."
                                  % intent["subject"])
        facts += bfacts
    hist = results.get("history")
    if isinstance(hist, dict) and not hist.get("_error"):
        for f in hist.get("facts") or []:
            facts.append({"subject": f.get("subject"), "predicate": f.get("predicate") or f.get("category"), "object": f.get("object"),
                          "statement": f.get("statement"), "date": f.get("date"), "where": "History & News", "status": f.get("status")})
    facts = rank(facts, intent)
    if facts:
        out["sections"].append({"source": "Facts", "app": "control", "kind": "facts", "items": facts[:40]})
        if not out["short"]:
            out["short"] = short_answer(intent, facts) or str(out.get("identity") or "")
    # what QueryBook could not answer is what it must learn next: the subject goes to the demand agent, which fetches its
    # record from Wikidata now (engine 1.40) — so the same question is answered the next time it is asked
    if intent["kind"] == "fact" and intent["subject"] and base("control") and (out.get("missing") or not facts):
        out["missing"] = str(out.get("missing") or "QueryBook holds no record of “%s” yet." % intent["subject"])
        try:
            d = _post(base("control") + "/api/bulk/demand", {"subject": intent["subject"], "question": intent["question"], "why": out["missing"]}, timeout=4)
            if d.get("queued"):
                out["learning"] = "It has been sent to the demand agent, which is fetching it now. Ask again in a few minutes."
        except Exception:
            pass
    return out
