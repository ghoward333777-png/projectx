"""The twelve things QueryBook's AI can do for a person, and the rule-based engine behind each.

    1 Ask / Search        5 Analyze              9 Agent
    2 Summarize           6 Develop / Project   10 Chatbot
    3 Write / Create      7 Tools               11 Translate / Languages
    4 Organize            8 Processes/Workflows 12 Learn / Study

Pure functions over plain data (no I/O, no reflection): Rust-ready, like ask.py and modes.py. Everything here works with
no AI key and invents nothing: a summary is the text's own sentences, an outline is built from the brief's own words, a
plan's steps are named for what they are. assist.py adds Claude / Gemini on top when a key is saved, and says so.
"""
from __future__ import annotations

import math
import re

# --------------------------------------------------------------------------- the catalogue (drawn by ui/capspage.js)
# task.input: "text" a pasted text · "brief" a short instruction · "question" one line · "goal" · "chat" · "none"
# task.opens: an area of the window (and, for Ask, the mode) that already does this
CAPABILITIES: list[dict] = [
    {"id": "ask", "n": 1, "icon": "🔎", "name": "Ask / Search", "about": "Ask anything; answers come from the facts, each with its source.",
     "tasks": [{"id": "ask.question", "name": "Ask a question", "input": "question", "placeholder": "When was the printing press invented?"},
               {"id": "ask.page", "name": "Open the Ask page", "input": "none", "opens": "ask", "about": "Every way to ask: speak, camera, video, photo, structured, watched questions."},
               {"id": "ask.book", "name": "Ask a book", "input": "none", "opens": "bookquery", "about": "Choose a book (or several) and ask it."}]},
    {"id": "summarize", "n": 2, "icon": "📝", "name": "Summarize", "about": "Paste a text and get the short version.",
     "tasks": [{"id": "sum.brief", "name": "Short summary", "input": "text"},
               {"id": "sum.points", "name": "Key points", "input": "text"},
               {"id": "sum.line", "name": "One sentence", "input": "text"}]},
    {"id": "write", "n": 3, "icon": "✍️", "name": "Write / Create", "about": "Say what you need and get a draft.",
     "tasks": [{"id": "write.doc", "name": "Any document", "input": "brief", "option": "genre",
                "placeholder": "A white paper for hospital managers on why hand-hygiene audits save money, about 2,000 words",
                "about": "Any kind of document in the library, in any field and style. You see the plan first, then the draft (checked at five layers), then revise it with your own notes."},
               {"id": "write.check", "name": "Check a draft", "input": "text", "option": "genre",
                "about": "Paste a draft and choose its kind: QueryBook judges it at five layers and says what to fix. No AI needed."},
               {"id": "write.voice", "name": "VOICE check", "input": "text",
                "about": "Paste a draft — yours or an AI's. QueryBook reads it against five standards: Verified (every claim to check), Owned (is it yours?), "
                         "Insightful (does it say something?), Clear, Engaging. It points and asks; it does not rewrite, and you make the final decisions."},
               {"id": "write.story_check", "name": "Story check", "input": "text",
                "about": "Paste a scene or a chapter. QueryBook reads it for six common habits: dialogue that is too formal, point of view that drifts, "
                         "stakes that stay vague, pacing at one speed, a first page that starts too early, and overwriting. It points; you edit."},
               {"id": "write.style", "name": "Learn my style", "input": "text", "option": "name",
                "about": "Paste a page or more of your own writing. QueryBook measures its habits and adds it to the style list — as numbers; none of your sentences is kept."},
               {"id": "write.learn", "name": "Learn from a source", "input": "brief", "option": "source", "placeholder": "https://… the address of one page of the source",
                "about": "One page of one source at a time, once. A model restates the page's advice as rules in its own words; rules that repeat the page's wording are dropped."},
               {"id": "write.grammar", "name": "Show the flow", "input": "text",
                "about": "See each sentence's topic and comment, and the pattern each paragraph follows."},
               {"id": "write.email", "name": "Email", "input": "brief", "placeholder": "Ask the landlord to fix the heating this week"},
               {"id": "write.letter", "name": "Letter", "input": "brief", "placeholder": "Thank the library volunteers for the summer programme"},
               {"id": "write.report", "name": "Report", "input": "brief", "placeholder": "Progress of the garden project: beds built, planting next month"},
               {"id": "write.essay", "name": "Essay", "input": "brief", "placeholder": "Why the printing press changed Europe"},
               {"id": "write.story", "name": "Story", "input": "brief", "placeholder": "A lighthouse keeper finds a message in a bottle"},
               {"id": "write.post", "name": "Announcement", "input": "brief", "placeholder": "The book club moves to Thursdays at 7"},
               {"id": "write.rewrite", "name": "Rewrite clearer", "input": "text"}]},
    {"id": "organize", "n": 4, "icon": "🗂️", "name": "Organize", "about": "Turn a messy list or notes into order.",
     "tasks": [{"id": "org.sort", "name": "Sort and remove repeats", "input": "text"},
               {"id": "org.group", "name": "Group into topics", "input": "text"},
               {"id": "org.outline", "name": "Make an outline", "input": "text"},
               {"id": "org.table", "name": "Make a table", "input": "text"},
               {"id": "org.actions", "name": "Find actions and dates", "input": "text"}]},
    {"id": "analyze", "n": 5, "icon": "📊", "name": "Analyze", "about": "Numbers, tables or text: what is in them.",
     "tasks": [{"id": "an.numbers", "name": "Numbers", "input": "text", "placeholder": "Paste numbers, or a table with a header row"},
               {"id": "an.text", "name": "A text", "input": "text"},
               {"id": "an.compare", "name": "Compare two texts", "input": "text", "placeholder": "First text\n---\nSecond text"},
               {"id": "an.claims", "name": "Check its claims", "input": "text", "about": "Each claim is checked against the facts."}]},
    {"id": "project", "n": 6, "icon": "🧭", "name": "Develop / Project", "about": "Turn a goal into a plan you can tick off.",
     "tasks": [{"id": "proj.plan", "name": "Plan a project", "input": "goal", "placeholder": "Open a community tool library by spring"},
               {"id": "proj.list", "name": "My projects", "input": "none"}]},
    {"id": "tools", "n": 7, "icon": "🧰", "name": "Tools", "about": "QueryBook's own tools, one tap each.",
     "tasks": [{"id": "tool.calc", "name": "Calculator", "input": "question", "placeholder": "12.5 * (3 + 4)"},
               {"id": "tool.convert", "name": "Unit converter", "input": "question", "placeholder": "60 mph to km/h"},
               {"id": "tool.word", "name": "Dictionary", "input": "question", "placeholder": "obsequious"},
               {"id": "tool.chem", "name": "Chemistry", "input": "question", "placeholder": "molar mass of H2O"},
               {"id": "tool.count", "name": "Word count", "input": "text"},
               {"id": "tool.check", "name": "Fact checker", "input": "text"},
               {"id": "tool.speak", "name": "Read aloud", "input": "text"},
               {"id": "tool.stem", "name": "STEM", "input": "none", "opens": "stem"},
               {"id": "tool.video", "name": "Video Studio", "input": "none", "opens": "video"}]},
    {"id": "workflow", "n": 8, "icon": "🔁", "name": "Processes / Workflows", "about": "Chain steps: the result of one is the input of the next. Save and reuse.",
     "tasks": [{"id": "wf.run", "name": "Run a workflow", "input": "text"},
               {"id": "wf.edit", "name": "Build a workflow", "input": "none"}]},
    {"id": "agent", "n": 9, "icon": "🤖", "name": "Agent(s)", "about": "Give a goal; the agent chooses the steps, does them, and shows each one.",
     "tasks": [{"id": "agent.run", "name": "Give the agent a goal", "input": "goal", "placeholder": "Summarize this and translate it into Spanish: …"},
               {"id": "agent.harvest", "name": "Harvest agents", "input": "none", "opens": "harvest", "about": "The agents that gather facts day and night."}]},
    {"id": "chat", "n": 10, "icon": "💬", "name": "Chatbot", "about": "Talk it through; follow-ups remember what you were talking about.",
     "tasks": [{"id": "chat.talk", "name": "Chat", "input": "chat", "placeholder": "Tell me about the Eiffel Tower"}]},
    {"id": "translate", "n": 11, "icon": "🌐", "name": "Translate / Languages", "about": "139 languages, spoken aloud, with an avatar.",
     "tasks": [{"id": "tr.quick", "name": "Translate a text", "input": "text"},
               {"id": "tr.lab", "name": "Words · Translate · Speech · Avatar", "input": "none", "opens": "language"},
               {"id": "tr.full", "name": "Translate (139 languages)", "input": "none", "opens": "translate"}]},
    {"id": "learn", "n": 12, "icon": "🎓", "name": "Learn / Study", "about": "Any subject taught in steps, then quiz yourself.",
     "tasks": [{"id": "learn.tutorial", "name": "Teach me", "input": "question", "placeholder": "Photosynthesis", "mode": "tutorial"},
               {"id": "learn.quiz", "name": "Quiz me", "input": "question", "placeholder": "Marie Curie", "mode": "quiz"},
               {"id": "learn.flashcards", "name": "Flashcards", "input": "question", "placeholder": "Mount Everest", "mode": "flashcards"},
               {"id": "learn.explore", "name": "Explore connections", "input": "question", "placeholder": "Ada Lovelace", "mode": "explore"},
               {"id": "learn.text", "name": "Study a text", "input": "text", "about": "Key points and questions made from your own text."},
               {"id": "learn.book", "name": "Study a book", "input": "none", "opens": "bookquery"}]},
]

# the steps a workflow or an agent can chain: each takes a text and gives a text
STEPS: list[dict] = [
    {"id": "sum.brief", "name": "Summarize"}, {"id": "sum.points", "name": "Key points"}, {"id": "sum.line", "name": "One sentence"},
    {"id": "org.sort", "name": "Sort and remove repeats"}, {"id": "org.group", "name": "Group into topics"}, {"id": "org.outline", "name": "Outline"},
    {"id": "org.actions", "name": "Actions and dates"}, {"id": "an.text", "name": "Analyze the text"}, {"id": "an.numbers", "name": "Analyze the numbers"},
    {"id": "an.claims", "name": "Check the claims"}, {"id": "write.rewrite", "name": "Rewrite clearer"}, {"id": "learn.text", "name": "Study questions"},
    {"id": "tr.quick", "name": "Translate", "option": "language"},
]
STARTER_WORKFLOWS: list[dict] = [
    {"id": "brief", "name": "Brief me", "about": "A summary, then the actions and dates in it.", "steps": [{"do": "sum.brief"}, {"do": "org.actions"}]},
    {"id": "study", "name": "Study pack", "about": "Key points, then questions to test yourself.", "steps": [{"do": "sum.points"}, {"do": "learn.text"}]},
    {"id": "share", "name": "Summarize and translate", "about": "A short summary, translated.", "steps": [{"do": "sum.brief"}, {"do": "tr.quick", "option": "es"}]},
    {"id": "tidy", "name": "Tidy notes", "about": "Notes sorted into topics, then outlined.", "steps": [{"do": "org.group"}, {"do": "org.outline"}]},
    {"id": "trust", "name": "Check before sharing", "about": "The claims checked against the facts, then a summary.", "steps": [{"do": "an.claims"}, {"do": "sum.brief"}]},
]

STOP = frozenset((
    "the a an and or but if then than that this these those of in on at to for from by with without as is are was were be been being it its "
    "he she they them his her their we you i our your my me not no do does did done have has had having will would can could should may might "
    "must shall there here what which who whom when where why how all any both each few more most other some such only own same so too very "
    "just also into over under again about after before between through during out up down off above below while because until against "
    "one two new said says per via etc around now within still even much many every often already").split())
ABBREV = ("mr", "mrs", "ms", "dr", "prof", "st", "vs", "etc", "e.g", "i.e", "no", "fig", "jr", "sr", "inc", "ltd", "co")
WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", re.UNICODE)
NUMBER = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w])|(?<![\w.])-?\d+(?:\.\d+)?(?![\w])")
MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
DATE = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?|(?:%s)\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?|\d{1,2}(?:st|nd|rd|th)?\s+(?:%s)\.?(?:\s+\d{4})?|"
                  r"(?:mon|tues|wednes|thurs|fri|satur|sun)day|today|tomorrow|tonight|next\s+(?:week|month|year)|by\s+(?:noon|midnight)|\d{1,2}(?::\d{2})?\s*(?:am|pm))\b" % (MONTHS, MONTHS), re.I)
ACTION = re.compile(r"^(?:please\s+|we\s+(?:must|should|need\s+to|have\s+to)\s+|i\s+(?:must|should|need\s+to|have\s+to|will)\s+|you\s+(?:must|should|need\s+to)\s+|"
                    r"(?:to\s*do|todo|action)\s*[:\-]\s*|\[\s?\]\s*)?"
                    r"(call|email|send|buy|book|pay|write|finish|fix|check|review|schedule|order|prepare|submit|update|ask|tell|remind|meet|bring|clean|"
                    r"make|plan|arrange|confirm|cancel|return|collect|pick|sign|print|post|renew|register|install|test|draft|read|visit|contact|file|"
                    r"reply|follow|organi[sz]e|complete|deliver|set|get|find|decide|invite|apply|hire|build|open|close|move|share|upload|back)\b", re.I)
OBLIGATION = re.compile(r"\b(must|need(?:s)? to|have to|has to|should|due|deadline|remember to|don't forget|do not forget)\b", re.I)


def fold(s: str) -> str:
    return " ".join(s.lower().split())


def words(text: str) -> list[str]:
    return [w.lower() for w in WORD.findall(text)]


def terms(text: str) -> list[str]:
    """the words that carry meaning: no stop words, no one-letter words"""
    return [w for w in words(text) if w not in STOP and len(w) > 2]


def sentences(text: str) -> list[str]:
    """split into sentences without breaking 'Dr. Smith', '3.5' or 'e.g.'"""
    out: list[str] = []
    for para in re.split(r"\n\s*\n|\r\n\s*\r\n", text):
        flat = " ".join(para.split())
        if not flat:
            continue
        start = 0
        for m in re.finditer(r"[.!?]+[\"'”’)\]]*\s+(?=[\"'“‘(\[]?[A-Z0-9¿¡À-Þ])", flat):
            before = flat[start:m.start()].split()
            last = before[-1].lower().rstrip(".") if before else ""
            if last in ABBREV or (len(last) == 1 and last.isalpha()):
                continue
            out.append(flat[start:m.end()].strip())
            start = m.end()
        if flat[start:].strip():
            out.append(flat[start:].strip())
    return out


def items(text: str) -> list[str]:
    """a list as the person wrote it: one item per line (bullets and numbers removed); one line → split on ; or ,"""
    lines = [re.sub(r"^\s*(?:[-*•·–—]+|\(?\d{1,3}[.)]|\[[ xX]?\])\s*", "", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    if len(lines) == 1:
        parts = [p.strip() for p in re.split(r"\s*;\s*", lines[0]) if p.strip()]
        if len(parts) < 3:
            parts = [p.strip() for p in re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+", lines[0]) if p.strip()] if lines[0].count(",") >= 2 else parts
        if len(parts) >= 3:
            return parts
        ss = sentences(lines[0])
        return ss if len(ss) > 1 else lines
    return lines


def top_terms(text: str, n: int = 10) -> list[dict]:
    count: dict[str, int] = {}
    for t in terms(text):
        count[t] = count.get(t, 0) + 1
    ranked = sorted(count.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"term": t, "count": c} for t, c in ranked[:n]]


# --------------------------------------------------------------------------- 2 Summarize
def score_sentences(text: str) -> list[dict]:
    """each sentence scored by how much of the text's own vocabulary it carries (frequency of its terms, length-normalised),
    with a small lift for coming first in its paragraph — extractive: the summary is the text's own sentences"""
    ss = sentences(text)
    freq: dict[str, int] = {}
    for t in terms(text):
        freq[t] = freq.get(t, 0) + 1
    top = max(freq.values()) if freq else 1
    firsts = {sentences(p)[0] for p in re.split(r"\n\s*\n", text) if sentences(p)}
    rows: list[dict] = []
    for i, s in enumerate(ss):
        ts = terms(s)
        if len(ts) < 3:
            rows.append({"i": i, "text": s, "score": 0.0})
            continue
        base = sum(freq.get(t, 0) / top for t in set(ts)) / math.sqrt(len(set(ts)))
        lift = 1.15 if s in firsts else 1.0
        lift *= 1.1 if i == 0 else 1.0
        rows.append({"i": i, "text": s, "score": round(base * lift, 4)})
    return rows


def summarize(text: str, kind: str = "brief") -> dict:
    """kind: 'brief' (about a fifth of the text, 2–6 sentences), 'points' (up to 7 key sentences), 'line' (the single best)"""
    rows = score_sentences(text)
    n_all = len(rows)
    if n_all == 0:
        return {"kind": kind, "sentences": [], "text": "", "of": 0, "words_in": 0, "words_out": 0}
    want = 1 if kind == "line" else min(7, max(3, n_all // 4)) if kind == "points" else min(6, max(2, round(n_all / 5)))
    want = min(want, n_all)
    chosen: list[dict] = []
    for r in sorted(rows, key=lambda r: (-r["score"], r["i"])):
        if len(chosen) >= want:
            break
        mine = set(terms(r["text"]))
        if any(len(mine & set(terms(c["text"]))) >= 0.7 * max(1, len(mine)) for c in chosen):
            continue                                       # says what a chosen sentence already says
        chosen.append(r)
    chosen.sort(key=lambda r: r["i"])
    picked = [c["text"] for c in chosen]
    out = "\n".join("• " + p for p in picked) if kind == "points" else " ".join(picked)
    return {"kind": kind, "sentences": picked, "text": out, "of": n_all, "words_in": len(words(text)), "words_out": len(words(out))}


# --------------------------------------------------------------------------- 4 Organize
def sort_items(text: str) -> dict:
    seen: dict[str, str] = {}
    repeats = 0
    for it in items(text):
        k = fold(re.sub(r"[.;,]+$", "", it))
        if k in seen:
            repeats += 1
        else:
            seen[k] = it
    rows = sorted(seen.values(), key=lambda s: fold(s))
    return {"items": rows, "removed": repeats, "text": "\n".join(rows)}


def group_items(text: str) -> dict:
    """items that share a meaningful word go together, the most shared word first; the rest are 'Other'"""
    its = items(text)
    owner: dict[str, list[int]] = {}
    for i, it in enumerate(its):
        for t in set(terms(it)):
            owner.setdefault(t, []).append(i)
    groups: list[dict] = []
    used: set[int] = set()
    for t, idx in sorted(owner.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        free = [i for i in idx if i not in used]
        if len(free) < 2:
            continue
        groups.append({"topic": t.capitalize(), "items": [its[i] for i in free]})
        used.update(free)
    rest = [its[i] for i in range(len(its)) if i not in used]
    if rest:
        groups.append({"topic": "Other", "items": rest})
    text_out = "\n\n".join(g["topic"] + "\n" + "\n".join("  • " + x for x in g["items"]) for g in groups)
    return {"groups": groups, "text": text_out}


def outline(text: str) -> dict:
    """paragraphs become sections named by their two commonest terms; each section's points are its key sentences"""
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) < 2:
        ss = sentences(text)
        size = max(2, math.ceil(len(ss) / 4)) if len(ss) > 4 else max(1, len(ss))
        paras = [" ".join(ss[i:i + size]) for i in range(0, len(ss), size)] or paras
    secs: list[dict] = []
    for p in paras:
        tt = [t["term"] for t in top_terms(p, 2)]
        title = " and ".join(tt).capitalize() if tt else "Section %d" % (len(secs) + 1)
        pts = summarize(p, "points")["sentences"][:3] or sentences(p)[:1]
        secs.append({"title": title, "points": pts})
    lines: list[str] = []
    for i, s in enumerate(secs):
        lines.append("%d. %s" % (i + 1, s["title"]))
        lines.extend("   %s. %s" % (chr(97 + j), pt) for j, pt in enumerate(s["points"]))
    return {"sections": secs, "text": "\n".join(lines)}


def table(text: str) -> dict:
    """rows from lines: tab, |, comma or 'key: value' — whichever splits every line the same way"""
    lines = [ln.strip().strip("|").strip() for ln in text.splitlines() if ln.strip() and not re.fullmatch(r"[\s|:\-]+", ln)]
    best: list[list[str]] = []
    for sep in ("\t", "|", ",", ";", ":", "  "):
        rows = [[c.strip() for c in (re.split(r"\s{2,}", ln) if sep == "  " else ln.split(sep, 1) if sep == ":" else ln.split(sep))] for ln in lines]
        widths = {len(r) for r in rows}
        if rows and len(widths) == 1 and len(rows[0]) > 1:
            best = rows
            break
    if not best:
        best = [[ln] for ln in lines]
    header = best[0] if len(best) > 1 and not any(NUMBER.fullmatch(c) for c in best[0]) and len(best[0]) > 1 else []
    body = best[1:] if header else best
    if not header and best and len(best[0]) == 2:
        header = ["Item", "Value"]
    return {"header": header, "rows": body, "text": "\n".join(" | ".join(r) for r in ([header] if header else []) + body)}


def actions(text: str) -> dict:
    """the things to do (imperatives and obligations) and every date or time mentioned, each with the line it came from"""
    acts: list[dict] = []
    dates: list[dict] = []
    for it in (sentences(text) if "\n" not in text.strip() else items(text)):
        when = [m.group(0) for m in DATE.finditer(it)]
        if ACTION.match(it) or OBLIGATION.search(it):
            acts.append({"do": it.rstrip("."), "when": when})
        for w in when:
            dates.append({"when": w, "line": it})
    lines = ["☐ " + a["do"] + ("  (" + ", ".join(a["when"]) + ")" if a["when"] else "") for a in acts]
    return {"actions": acts, "dates": dates, "text": "\n".join(lines) if lines else "No actions found."}


# --------------------------------------------------------------------------- 5 Analyze
def to_number(s: str) -> float:
    return float(s.replace(",", ""))


def stats(values: list[float]) -> dict:
    n = len(values)
    if n == 0:
        return {"count": 0}
    vs = sorted(values)
    mean = sum(vs) / n
    mid = vs[n // 2] if n % 2 else (vs[n // 2 - 1] + vs[n // 2]) / 2
    var = sum((v - mean) ** 2 for v in vs) / (n - 1) if n > 1 else 0.0
    return {"count": n, "sum": round(sum(vs), 6), "mean": round(mean, 6), "median": round(mid, 6), "min": vs[0], "max": vs[-1],
            "range": round(vs[-1] - vs[0], 6), "sd": round(math.sqrt(var), 6)}


def analyze_numbers(text: str) -> dict:
    """a table with a header row → statistics per numeric column; otherwise every number in the text"""
    t = table(text)
    cols: list[dict] = []
    if t["rows"] and len(t["rows"][0]) > 1:
        width = len(t["rows"][0])
        names = t["header"] if t["header"] and len(t["header"]) == width else ["Column %d" % (i + 1) for i in range(width)]
        for c in range(width):
            cells = [r[c].strip().rstrip("%").lstrip("$€£") for r in t["rows"] if c < len(r)]
            vals = [to_number(x) for x in cells if NUMBER.fullmatch(x)]
            if len(vals) >= max(2, len(cells) // 2):
                cols.append(dict({"name": names[c]}, **stats(vals)))
    if not cols:
        vals = [to_number(m.group(0)) for m in NUMBER.finditer(text)]
        if vals:
            cols.append(dict({"name": "All numbers"}, **stats(vals)))
    lines = ["%s: %d values · total %s · average %s · middle %s · lowest %s · highest %s · spread (sd) %s" % (
        c["name"], c["count"], fmt(c["sum"]), fmt(c["mean"]), fmt(c["median"]), fmt(c["min"]), fmt(c["max"]), fmt(c["sd"])) for c in cols]
    return {"columns": cols, "text": "\n".join(lines) if lines else "No numbers found."}


def fmt(v: float) -> str:
    return ("%.4f" % v).rstrip("0").rstrip(".") if v != int(v) else "{:,}".format(int(v))


def syllables(word: str) -> int:
    groups = re.findall(r"[aeiouy]+", word.lower())
    n = len(groups) - (1 if word.lower().endswith("e") and len(groups) > 1 and not word.lower().endswith(("le", "ee")) else 0)
    return max(1, n)


def analyze_text(text: str) -> dict:
    ws = words(text)
    ss = sentences(text)
    n_w, n_s = len(ws), max(1, len(ss))
    syl = sum(syllables(w) for w in ws)
    grade = 0.39 * (n_w / n_s) + 11.8 * (syl / max(1, n_w)) - 15.59 if n_w else 0.0     # Flesch–Kincaid grade level
    level = "very easy" if grade < 5 else "easy" if grade < 8 else "plain" if grade < 11 else "demanding" if grade < 14 else "hard"
    longest = max(ss, key=lambda s: len(words(s))) if ss else ""
    numbers = [m.group(0) for m in NUMBER.finditer(text)]
    dates = [m.group(0) for m in DATE.finditer(text)]
    out = {"words": n_w, "sentences": len(ss), "paragraphs": len([p for p in re.split(r"\n\s*\n", text) if p.strip()]),
           "characters": len(text), "unique_words": len(set(ws)), "words_per_sentence": round(n_w / n_s, 1),
           "reading_minutes": round(n_w / 230, 1), "speaking_minutes": round(n_w / 140, 1), "grade": round(max(0.0, grade), 1), "level": level,
           "top_terms": top_terms(text, 10), "longest_sentence": longest, "numbers": numbers[:40], "dates": dates[:40]}
    out["text"] = ("%d words in %d sentences (%s words a sentence) · about %s min to read, %s min to say aloud · reading level: %s (grade %s)\n"
                   "Most used: %s" % (n_w, len(ss), out["words_per_sentence"], out["reading_minutes"], out["speaking_minutes"], level, out["grade"],
                                      ", ".join("%s ×%d" % (t["term"], t["count"]) for t in out["top_terms"]) or "—"))
    return out


def compare(a: str, b: str) -> dict:
    ta, tb = set(terms(a)), set(terms(b))
    both = ta & tb
    sim = len(both) / max(1, len(ta | tb))
    fa = {t["term"]: t["count"] for t in top_terms(a, 400)}
    fb = {t["term"]: t["count"] for t in top_terms(b, 400)}
    only_a = sorted(ta - tb, key=lambda t: (-fa.get(t, 0), t))[:12]
    only_b = sorted(tb - ta, key=lambda t: (-fb.get(t, 0), t))[:12]
    shared = sorted(both, key=lambda t: (-(fa.get(t, 0) + fb.get(t, 0)), t))[:12]
    sa, sb = {fold(s) for s in sentences(a)}, {fold(s) for s in sentences(b)}
    out = {"similarity": round(sim, 3), "shared": shared, "only_first": only_a, "only_second": only_b, "same_sentences": len(sa & sb),
           "first": {"words": len(words(a)), "sentences": len(sa)}, "second": {"words": len(words(b)), "sentences": len(sb)}}
    out["text"] = ("The two texts share %d%% of their vocabulary and %d identical sentence(s).\nBoth talk about: %s\nOnly the first: %s\nOnly the second: %s"
                   % (round(sim * 100), out["same_sentences"], ", ".join(shared) or "—", ", ".join(only_a) or "—", ", ".join(only_b) or "—"))
    return out


def split_two(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n\s*(?:-{3,}|={3,}|\*{3,})\s*\n", text) if p.strip()]
    if len(parts) < 2:
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        half = len(paras) // 2
        parts = ["\n\n".join(paras[:half]), "\n\n".join(paras[half:])] if len(paras) >= 2 else [text, ""]
    return [parts[0], "\n\n".join(parts[1:])]


# --------------------------------------------------------------------------- 3 Write / Create (the rule-based skeleton)
SHAPES: dict[str, list[str]] = {
    "email": ["Subject", "Greeting", "Why I am writing", "What I am asking for", "By when", "Thanks and sign-off"],
    "letter": ["Date and greeting", "Opening: why I am writing", "The main point", "Details", "Closing wish", "Sign-off"],
    "report": ["Title", "Summary", "Background", "What was done", "What was found", "Next steps"],
    "essay": ["Title", "Opening: the claim", "First reason", "Second reason", "The other side", "Conclusion"],
    "story": ["Title", "Where and who", "What goes wrong", "What they try", "The turn", "How it ends"],
    "post": ["Headline", "What is happening", "When and where", "Who it is for", "What to do next"],
}


def skeleton(kind: str, brief: str) -> dict:
    """the shape of the piece with the brief's own words placed in it — an outline to write from, never invented prose"""
    shape = SHAPES.get(kind) or SHAPES["report"]
    key = [t["term"] for t in top_terms(brief, 6)]
    when = [m.group(0) for m in DATE.finditer(brief)]
    title = brief.strip().rstrip(".")
    title = title[:1].upper() + title[1:]
    notes: dict[str, str] = {shape[0]: title[:90]}
    for part in shape[1:]:
        low = part.lower()
        if "when" in low and when:
            notes[part] = ", ".join(when)
        elif "main" in low or "asking" in low or "claim" in low or "happening" in low or "wrong" in low:
            notes[part] = title
        else:
            notes[part] = ""
    lines = ["%s: %s" % (p, notes.get(p, "")) if notes.get(p) else "%s:" % p for p in shape]
    return {"kind": kind, "parts": [{"part": p, "note": notes.get(p, "")} for p in shape], "keywords": key,
            "text": "\n".join(lines) + ("\n\nWords to use: " + ", ".join(key) if key else "")}


# --------------------------------------------------------------------------- 6 Develop / Project
PHASES: list[dict] = [
    {"name": "Define", "tasks": ["Write the goal in one sentence: {goal}", "Say what done looks like and how it will be measured", "List who is involved and who decides",
                                 "Note the limits: money, time, people"]},
    {"name": "Plan", "tasks": ["Break the goal into its main pieces of work", "Put the pieces in order and mark what depends on what", "Give each piece an owner and a date",
                               "List what could go wrong and what would be done about it"]},
    {"name": "Do", "tasks": ["Start with the piece everything else depends on", "Check progress every week against the dates", "Write down each decision and why"]},
    {"name": "Check", "tasks": ["Test the result against what done looks like", "Ask the people it is for", "Fix what the test and the people found"]},
    {"name": "Finish", "tasks": ["Hand over: who looks after it now", "Write what worked and what to do differently", "Thank the people who helped"]},
]


def project_plan(goal: str) -> dict:
    """a plain five-phase plan for any goal; the goal's own deadline words become the target"""
    g = " ".join(goal.split()).rstrip(".")
    when = [m.group(0) for m in DATE.finditer(g)] + re.findall(r"\bby\s+(?:the\s+)?(?:end\s+of\s+)?(?:spring|summer|autumn|fall|winter|[A-Z][a-z]+(?:\s+\d{4})?|\d{4})\b", g)
    phases = [{"name": p["name"], "tasks": [{"text": t.replace("{goal}", g), "done": False} for t in p["tasks"]]} for p in PHASES]
    name = g[:60] + ("…" if len(g) > 60 else "")
    return {"name": name[:1].upper() + name[1:], "goal": g, "target": when[0] if when else "", "phases": phases, "risks": [], "by": "rules"}


def plan_text(plan: dict) -> str:
    lines = ["Project: %s" % plan.get("name", ""), "Goal: %s" % plan.get("goal", "")]
    if plan.get("target"):
        lines.append("Target: %s" % plan["target"])
    for i, p in enumerate(plan.get("phases") or []):
        lines.append("")
        lines.append("%d. %s" % (i + 1, p.get("name", "")))
        lines.extend("   %s %s" % ("☑" if t.get("done") else "☐", t.get("text", "")) for t in p.get("tasks") or [])
    if plan.get("risks"):
        lines.append("")
        lines.append("Risks")
        lines.extend("   • %s" % r for r in plan["risks"])
    return "\n".join(lines)


def progress(plan: dict) -> dict:
    tasks = [t for p in plan.get("phases") or [] for t in p.get("tasks") or []]
    done = sum(1 for t in tasks if t.get("done"))
    return {"done": done, "total": len(tasks), "percent": round(100 * done / len(tasks)) if tasks else 0}


# --------------------------------------------------------------------------- 12 Learn / Study (from the person's own text)
def study(text: str, n: int = 6) -> dict:
    """key points, and fill-the-gap questions made by hiding a sentence's most telling word — the answer is in the text"""
    pts = summarize(text, "points")["sentences"]
    freq = {t["term"]: t["count"] for t in top_terms(text, 400)}
    qs: list[dict] = []
    for s in pts:
        cands = [w for w in WORD.findall(s) if w.lower() in freq and len(w) > 3]
        num = NUMBER.search(s)
        if num and len(qs) % 2 == 1:
            hide = num.group(0)
        elif cands:
            hide = sorted(cands, key=lambda w: (freq[w.lower()], -len(w), w))[0]        # the rarest telling word
        else:
            continue
        gap = re.sub(r"(?<![\w])%s(?![\w])" % re.escape(hide), "_____", s, count=1)
        if gap != s:
            qs.append({"question": gap, "answer": hide, "from": s})
        if len(qs) >= n:
            break
    text_out = "Key points\n" + "\n".join("• " + p for p in pts) + ("\n\nTest yourself\n" + "\n".join("%d. %s" % (i + 1, q["question"]) for i, q in enumerate(qs)) +
                                                                     "\n\nAnswers: " + "; ".join("%d %s" % (i + 1, q["answer"]) for i, q in enumerate(qs)) if qs else "")
    return {"points": pts, "questions": qs, "text": text_out}


# --------------------------------------------------------------------------- 8 Workflows and 9 Agent
STEP_IDS = frozenset(s["id"] for s in STEPS)
LANG_WORDS: dict[str, str] = {
    "spanish": "es", "french": "fr", "german": "de", "italian": "it", "portuguese": "pt", "dutch": "nl", "swedish": "sv", "danish": "da", "norwegian": "no",
    "finnish": "fi", "polish": "pl", "czech": "cs", "greek": "el", "romanian": "ro", "hungarian": "hu", "catalan": "ca", "english": "en", "japanese": "ja",
    "chinese": "zh", "korean": "ko", "arabic": "ar", "hindi": "hi", "russian": "ru", "turkish": "tr", "swahili": "sw", "ukrainian": "uk", "vietnamese": "vi",
    "hebrew": "he", "thai": "th", "indonesian": "id"}
CUES: list[dict] = [
    {"do": "an.claims", "any": ("fact-check", "fact check", "check the claims", "check its claims", "check the facts", "verify", "is it true", "is this true")},
    {"do": "org.actions", "any": ("action", "to-do", "todo", "to do list", "tasks", "deadlines", "dates in")},
    {"do": "org.group", "any": ("group", "categor", "by topic", "into topics", "cluster")},
    {"do": "org.sort", "any": ("sort", "alphabet", "dedupe", "remove repeats", "remove duplicates", "duplicates")},
    {"do": "org.outline", "any": ("outline", "structure")},
    {"do": "an.numbers", "any": ("average", "statistics", "stats", "total", "mean of", "sum of", "the numbers")},
    {"do": "an.text", "any": ("analy", "reading level", "word count", "how long", "readab")},
    {"do": "write.rewrite", "any": ("rewrite", "clearer", "simplify", "plain english", "plain language", "reword")},
    {"do": "sum.line", "any": ("one sentence", "one line", "tl;dr", "tldr", "in a sentence")},
    {"do": "sum.points", "any": ("key points", "bullet", "main points", "takeaways")},
    {"do": "sum.brief", "any": ("summar", "shorten", "brief", "short version", "gist")},
    {"do": "learn.text", "any": ("quiz", "study", "test me", "questions", "flashcard", "revise", "learn")},
]


def check_workflow(steps: list[dict]) -> list[dict]:
    """only known steps, at most 8; a translate step keeps its language"""
    out: list[dict] = []
    for s in steps[:8]:
        do = str(s.get("do") or "")
        if do in STEP_IDS:
            out.append({"do": do, "option": str(s.get("option") or "")[:12]} if do == "tr.quick" else {"do": do})
    return out


def split_goal(goal: str) -> dict:
    """'Summarize this and translate into Spanish: <the text>' → the instruction and the material it applies to"""
    g = goal.strip()
    m = re.search(r":\s*\n|:\s+(?=\S)|\n\s*\n", g)
    if m and m.start() < 400 and len(g) - m.end() > 20:
        return {"instruction": g[:m.start()].strip(), "material": g[m.end():].strip()}
    return {"instruction": g, "material": ""}


def plan_steps(instruction: str) -> list[dict]:
    """the steps an instruction asks for, in the order its words appear; translation last (it works on the result)"""
    low = " " + fold(instruction) + " "
    found: list[tuple[int, str]] = []
    for c in CUES:
        at = min((low.find(k) for k in c["any"] if k in low), default=-1)
        if at >= 0 and not any(d == c["do"] or (d.startswith("sum.") and c["do"].startswith("sum.")) for _, d in found):
            found.append((at, c["do"]))
    steps = [{"do": d} for _, d in sorted(found)]
    if "translat" in low or re.search(r"\b(?:in|into|to)\s+(%s)\b" % "|".join(LANG_WORDS), low):
        lang = next((code for name, code in LANG_WORDS.items() if re.search(r"\b%s\b" % name, low)), "es")
        steps.append({"do": "tr.quick", "option": lang})
    return steps[:6]


def step_name(do: str) -> str:
    return next((s["name"] for s in STEPS if s["id"] == do), do)


def run_step(do: str, text: str) -> dict:
    """one rule-based step (assist.py handles the steps that need the facts, the Language app or a model)"""
    if do in ("sum.brief", "sum.points", "sum.line"):
        return summarize(text, do.split(".")[1])
    if do == "org.sort":
        return sort_items(text)
    if do == "org.group":
        return group_items(text)
    if do == "org.outline":
        return outline(text)
    if do == "org.table":
        return table(text)
    if do == "org.actions":
        return actions(text)
    if do == "an.numbers":
        return analyze_numbers(text)
    if do in ("an.text", "tool.count"):
        return analyze_text(text)
    if do == "an.compare":
        two = split_two(text)
        return compare(two[0], two[1])
    if do == "learn.text":
        return study(text)
    return {"text": text}


# --------------------------------------------------------------------------- 10 Chatbot (what can be said without a model)
GREET = ("hi", "hello", "hey", "good morning", "good afternoon", "good evening", "hiya", "greetings")
THANKS = ("thanks", "thank you", "cheers", "ta")


def small_talk(message: str) -> str:
    m = fold(re.sub(r"[!.?,]+", "", message))
    if m in GREET:
        return "Hello. Ask me about a person, a place, a word, a date or a calculation — I answer from QueryBook's facts and show where each one came from."
    if m in THANKS or m.startswith(("thanks ", "thank you ")):
        return "You're welcome."
    if m in ("who are you", "what are you", "what can you do", "help"):
        return ("I am QueryBook's assistant. I answer from the facts QueryBook holds and say where each came from; I can also summarize, write, "
                "organize, analyze, plan a project, run a workflow, translate and help you study — see the tiles on the AI Capabilities page.")
    return ""


def find(cap_id: str) -> dict:
    for c in CAPABILITIES:
        if c["id"] == cap_id:
            return c
    return {}


def task(task_id: str) -> dict:
    for c in CAPABILITIES:
        for t in c["tasks"]:
            if t["id"] == task_id:
                return dict(t, cap=c["id"])
    return {}
