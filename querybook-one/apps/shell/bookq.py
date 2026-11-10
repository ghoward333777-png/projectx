"""Book Query: answers anchored in one ebook, and the book's assertions set beside what is known today.

Pure functions over plain data (no I/O, no reflection) — Rust-ready, like ask.py and modes.py.

  parse(text)            a Project Gutenberg text -> chapters, numbered sections, paragraphs (the anchors)
  atomize(paragraph)     a paragraph -> Fact Units: one sentence each, with its kind (definition, measurement, law,
                         observation, procedure, assertion) and the quantities it states
  search(book, query)    the Fact Units that answer a question, ranked (BM25 over the units, deterministic)
  answer(book, query)    the anchored answer: the book's own words with chapter / section / paragraph, and for every
                         assertion that the modern layer covers, what is established today, its status and sources

Nothing is invented. Every line of an answer is a sentence of the book (quoted, with its anchor) or an entry of the
book's curated modern layer (modern.json), which names its sources. A question the book does not answer gets
"The book does not say", never a guess.
"""
from __future__ import annotations

import math
import re

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12,
         "XIII": 13, "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20}
ROMAN_OF = {v: k for k, v in ROMAN.items()}
SECTION = re.compile(r"^(\d{1,3})\. ([A-Z](?:[A-Z0-9ÆŒ'’ ,;:()\.\-]|\[[a-z]+\]){2,}?)(\.--\s*|\. (?=EXERCISE)|(?=,? [a-z]))")
EXERCISE = re.compile(r"^EXERCISE (\d+)\.--\s*")
ABBREV = ("i. e.", "e. g.", "Fig.", "Figs.", "No.", "Nos.", "Mr.", "Mrs.", "Dr.", "St.", "Prof.", "vs.", "cf.", "etc.",
          "viz.", "Vol.", "p.", "pp.", "ch.", "Chap.", "Mt.", "approx.", "U. S.", "A. D.", "B. C.", "sec.", "min.")
UNITS = ("miles", "mile", "kilometers", "kilometer", "km", "meters", "meter", "centimeters", "centimeter", "feet", "foot",
         "inches", "inch", "tenth meters", "degrees", "degree", "°", "seconds", "second", "minutes", "minute", "hours", "hour",
         "days", "day", "years", "year", "light years", "light year", "per cent", "times", "pounds", "tons", "grams",
         "magnitudes", "magnitude", "radii", "shillings", "shilling", "pence", "acres", "bushels", "ounces", "gallons",
         "leagues", "league", "stadia", "talents", "ducats", "francs", "roubles", "dollars", "cents", "paces", "diameters", "revolutions", "m.", "s.", "h.", "d.", "″", "′")
QTY = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?(?:\s*/\s*\d+)?)\s*(" +
                 "|".join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True)) + r")(?![a-z])", re.I)
STOP = frozenset("""a an the of and or to in on at by for with from as is are was were be been being it its this that these
those which who whom what when where why how than then there their his her he she they them we our you your i not no do does
did has have had will would can could may might shall should into upon about over under between through during before after
also such so very more most much many some any each other only same own just but if while because tell me show give
book chapter say says said come came get got happen happened go went""".split())
IMPERATIVE = ("observe", "note", "find", "measure", "let", "compute", "show", "determine", "draw", "mark", "plot", "compare",
              "estimate", "select", "record", "test", "examine", "look", "repeat", "count", "make", "use", "construct", "verify")


# --------------------------------------------------------------------------- parsing the ebook
def body(text: str) -> str:
    """the book itself, without Project Gutenberg's header and licence"""
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    a = t.find("*** START OF")
    if a >= 0:
        a = t.find("\n", a) + 1
    b = t.find("*** END OF")
    return t[max(0, a): b if b > 0 else len(t)]


COMSTOCK_RULES: dict = {"chapters": [r"CHAPTER [IVXL]+", r"APPENDIX"], "title_line": True, "stop": [r"INDEX"],
                        "sections": "comstock", "min_chars": 150, "parts": []}


def _full(patterns: list[str], line: str) -> bool:
    return any(re.fullmatch(p, line) for p in patterns)


ROMAN_RE = re.compile(r"(?=[MDCLXVI])M{0,3}(C[MD]|D?C{0,3})(X[CL]|L?X{0,3})(I[XV]|V?I{0,3})[.:]?")


def _cap(word: str) -> str:
    """one word of a heading in capitals -> capitalised ('HARKER’S' -> 'Harker’s'); roman numerals stay in capitals"""
    core = word.strip("[]()\"'“”‘’.,:;")
    if ROMAN_RE.fullmatch(core) or not core.isupper() or len(core) < 2:
        return word
    i = word.find(core)
    return word[:i] + core[0] + core[1:].lower() + word[i + len(core):]


def _title(line: str) -> str:
    """'DIFFERENT KINDS OF MEASUREMENT' -> 'Different Kinds Of Measurement'; mixed case is kept as written"""
    t = line.strip().strip(".").strip()
    return " ".join(_cap(w) for w in t.split(" "))


def _label(line: str) -> str:
    """'CHAPTER XIV.' -> 'Chapter XIV'; 'BOOK ONE: 1805' -> 'Book One: 1805'; roman numerals stay in capitals"""
    t = line.strip().rstrip(".]").strip()
    return " ".join(_cap(w) for w in t.split(" "))


def parse(text: str, rules: dict) -> list[dict]:
    """chapters -> paragraphs, each paragraph knowing its part, chapter, numbered section and place in the section.
    rules (from the book's meta.json): parts / chapters (whole-line patterns, or exact headings), title_line (a short line
    under a bare chapter heading is its title), sections ("comstock": "12. TITLE.--"; "roman": "IV. text"; "arabic":
    "12. text"), stop (headings after which the book ends: an index), min_chars (a heading with less text than this before
    the next heading is a contents-page line and is dropped)."""
    lines = body(text).split("\n")
    parts_re: list[str] = rules.get("parts") or []
    chap_re: list[str] = rules.get("chapters") or []
    stop_re: list[str] = rules.get("stop") or []
    exact: list[str] = rules.get("headings") or []
    sec_mode = str(rules.get("sections") or "")
    subheads: list[str] = rules.get("subheads") or []
    min_chars = int(rules.get("min_chars") or 150)
    chapters: list[dict] = []
    part = ""
    cur: dict = {"n": 0, "label": "Front matter", "title": "", "part": "", "paragraphs": [], "figures": [], "chars": 0, "line": -1}
    heads: list[int] = []                                 # the line of every chapter heading, kept or not
    part_at: list[list] = []                              # [line, part label] of every part heading
    at = [0]
    block: list[str] = []
    sec_n, sec_title, sec_para = 0, "", 0

    def flush() -> None:
        nonlocal sec_n, sec_title, sec_para
        if not block:
            return
        raw = "\n".join(block).strip("\n")
        block.clear()
        if not raw.strip():
            return
        flat = " ".join(raw.split())
        if subheads and _full(subheads, flat):           # "I." inside a story: a numbered part of the chapter
            m = re.match(r"([IVXL]+|\d+)", flat)
            v = m.group(1) if m else ""
            sec_n = int(v) if v.isdigit() else ROMAN.get(v, 0)
            sec_title, sec_para = "", 0
            return
        if flat.startswith("[Illustration"):
            cur["figures"].append(flat.strip("[]"))
            return
        kind = "text"
        rows = [l for l in raw.split("\n") if l.strip()]
        if len(rows) > 1 and all(l.startswith("    ") for l in rows) and \
                (any(re.search(r"\S {3,}\S", l.strip()) for l in rows) or sum(len(l.strip()) for l in rows) / len(rows) < 42):
            kind = "table"                                 # columns (gaps of 3+ spaces) or short lines; indented prose is prose
        if kind == "text":
            if sec_mode == "comstock":
                m = SECTION.match(flat)
                if m:
                    sec_n, sec_title, sec_para = int(m.group(1)), m.group(2).strip(" .,").title(), 0
                    flat = flat[m.end():] if m.group(3).strip() else flat[len(m.group(1)) + 2:]
            elif sec_mode in ("roman", "arabic"):
                m = re.match(r"^([IVXL]+)\. (?=\S)" if sec_mode == "roman" else r"^(\d{1,3})\. (?=\S)", flat)
                if m:
                    v = m.group(1)
                    sec_n = ROMAN.get(v, 0) if sec_mode == "roman" else int(v)
                    sec_title, sec_para = "", 0
                    flat = flat[m.end():]
        ex = EXERCISE.match(flat)
        if ex and kind == "text":
            kind = "exercise"
        sec_para += 1
        cur["chars"] += len(flat)
        cur["paragraphs"].append({"section": sec_n, "section_title": sec_title, "para": sec_para, "kind": kind,
                                  "exercise": int(ex.group(1)) if ex else 0, "text": flat})

    def start(label: str, title: str) -> None:
        nonlocal cur, sec_n, sec_title, sec_para
        flush()
        if cur["chars"] >= min_chars or (cur["n"] == 0 and cur["paragraphs"]):
            chapters.append(cur)
        cur = {"n": 0, "label": label, "title": title, "part": part, "paragraphs": [], "figures": [], "chars": 0, "line": at[0]}
        heads.append(at[0])
        sec_n, sec_title, sec_para = 0, "", 0

    stop_at = len(lines)                                 # the book ends at the LAST stop heading (a contents page lists it too)
    for k in range(len(lines) - 1, -1, -1):
        if stop_re and lines[k].strip() and _full(stop_re, lines[k].strip()):
            stop_at = k
            break
    i = 0
    while i < len(lines):
        if i >= stop_at:
            break
        ln = lines[i].strip()
        if ln and parts_re and _full(parts_re, ln):
            flush()
            part = _label(ln)
            part_at.append([i, part])
            i += 1
            continue
        if ln and (_full(chap_re, ln) or ln in exact):
            title = ""
            j = i + 1
            if rules.get("wrap") and not ln.endswith((".", ")", "]")) and j < len(lines) and lines[j].strip():
                ln = ln + " " + lines[j].strip()           # a heading that runs onto a second line
                j += 1
            if rules.get("title_line"):
                while j < len(lines) and not lines[j].strip():
                    j += 1
                cand = lines[j].strip() if j < len(lines) else ""
                nxt = lines[j + 1].strip() if j + 1 < len(lines) else ""
                if cand and len(cand) <= 80 and not nxt and not _full(chap_re, cand) and not (parts_re and _full(parts_re, cand)):
                    title = _title(cand)
                    j += 1
            at[0] = i
            start(_label(ln), title)
            i = j
            continue
        if not ln:
            flush()
        else:
            block.append(lines[i])
        i += 1
    start("", "")
    # a heading met twice in the same part: the first was the contents page — its text goes to the front matter
    last: dict[str, int] = {}
    for k, c in enumerate(chapters):
        last[(c["part"] + "|" + c["label"]).lower()] = k
    kept: list[dict] = []
    for k, c in enumerate(chapters):
        if k and last[(c["part"] + "|" + c["label"]).lower()] != k:
            chapters[0]["paragraphs"] += c["paragraphs"]
            continue
        kept.append(c)
    chapters = kept
    # each chapter's part: the last part heading between the heading before it and its own (a contents page that lists
    # every volume in a row must not hand its last volume to the first chapter)
    prev_part = str(rules.get("first_part") or "")
    for c in chapters:
        if c["line"] < 0:
            continue
        before = [h for h in heads if h < c["line"]]
        lo = before[-1] if before else -1
        found = [lab for ln_, lab in part_at if lo < ln_ < c["line"]]
        c["part"] = found[-1] if found else prev_part
        prev_part = c["part"]
    for k, c in enumerate(chapters):
        c.pop("line", None)
        c["n"] = k + 1 if chapters[0]["label"] != "Front matter" else k
        c.pop("chars", None)
    return chapters


# --------------------------------------------------------------------------- Fact Units
def sentences(text: str) -> list[str]:
    """split a paragraph into sentences without breaking 'i. e.', 'Fig. 86', '8m. 18s.', '3.5' or initials"""
    t = text
    guard: list[str] = []
    for a in ABBREV:
        if a in t:
            guard.append(a)
            t = t.replace(a, "\x00%d\x00" % (len(guard) - 1))
    t = re.sub(r"\b([A-Z])\. (?=[A-Z])", "\\1\x01 ", t)              # initials: "G. C. Comstock"
    t = re.sub(r"(\d)([hmsd])\. (?=\d)", "\\1\\2\x01 ", t)            # "2h. 44.5m." in running text
    parts = re.split(r"(?<=[.?!])[\"”’)]?\s+(?=[\"“(]?[A-Z0-9_\[\x00])", t)
    out = []
    for p in parts:
        s = p.replace("\x01", ".")
        s = re.sub(r"\x00(\d+)\x00", lambda m: guard[int(m.group(1))], s)
        s = s.strip()
        if s:
            out.append(s)
    return out


def quantities(sentence: str) -> list[dict]:
    """numbers with their units: '93,000,000 miles', '5,400° C', '8m. 18s.', '1/81'"""
    out = []
    for m in QTY.finditer(sentence):
        raw = m.group(0).strip()
        num = m.group(1).replace(",", "").replace(" ", "")
        if "/" in num:
            a, b = num.split("/", 1)
            val = float(a) / float(b) if float(b) else 0.0
        else:
            val = float(num)
        out.append({"raw": raw, "value": val, "unit": m.group(2).lower()})
    return out


def kind_of(sentence: str, paragraph_kind: str) -> str:
    s = sentence.strip()
    low = s.lower()
    first = re.sub(r"[^a-z]", "", low.split(" ", 1)[0]) if low else ""
    if paragraph_kind == "exercise" or first in IMPERATIVE:
        return "procedure"
    if re.search(r"\b(is|are) (called|termed|named|known as|defined as)\b|\bwe call\b|\bis the name\b|\bmeans\b", low) or \
            re.search(r"\b_[a-z][a-z ]+_\b", s) and re.search(r"\b(is|are)\b", low):
        return "definition"
    if re.search(r"\blaws?\b|\bproportional\b|\bvaries as\b|\binversely\b|\bdirectly as\b|\bsquare of\b|=", low):
        return "law"
    if quantities(s):
        return "measurement"
    if re.search(r"\b(observ\w*|seen|visible|photograph\w*|telescope shows|appears?|was discovered|discovered)\b", low):
        return "observation"
    return "assertion"


def atomize(chapter: dict, paragraph: dict) -> list[dict]:
    """one Fact Unit per sentence (a table or formula block is one unit), anchored to chapter / § / paragraph"""
    texts = [paragraph["text"]] if paragraph["kind"] == "table" else sentences(paragraph["text"])
    note = bool(re.match(r"^\d+[a-z]? \(return\)|^\[?Footnote|^\d+ \[", paragraph["text"]))   # an editor's or the author's footnote
    units = []
    for k, s in enumerate(texts):
        kind = "table" if paragraph["kind"] == "table" else "note" if note else kind_of(s, paragraph["kind"])
        units.append({"chapter": chapter["n"], "section": paragraph["section"], "para": paragraph["para"], "n": k + 1,
                      "kind": kind, "text": s, "quantities": quantities(s) if kind != "table" else []})
    return units


def chapter_of(book: dict, n: int) -> dict:
    for c in book.get("chapters") or []:
        if c["n"] == n:
            return c
    return {}


def anchor(book: dict, u: dict) -> str:
    """'Chapter X — The Sun, § 113 (Another Method Of Determining The Sun's Distance), ¶ 1' (with its part, if any)"""
    ch = chapter_of(book, u.get("chapter") or 0)
    label = ch.get("label") or "Chapter %d" % (u.get("chapter") or 0)
    if ch.get("title"):
        label += " — " + ch["title"]
    if ch.get("part"):
        label = ch["part"] + ", " + label
    sec = u.get("section") or 0
    s = ""
    if sec:
        title = (book.get("sections") or {}).get(str(sec), "")
        s = ("§ %d (%s), " % (sec, title)) if title else ("§ %d, " % sec)
    return "%s, %s¶ %d" % (label, s, u.get("para") or 0)


# --------------------------------------------------------------------------- retrieval
def stem(w: str) -> str:
    for suf in ("ations", "ation", "ings", "ing", "eries", "ery", "ies", "es", "ed", "ly", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "er" if suf in ("ery", "eries") else "")
    return w


FOLD = str.maketrans("àáâãäåāèéêëēìíîïīòóôõöøōùúûüūñçýÿšžčřěœæ", "aaaaaaaeeeeeiiiiiooooooouuuuuncyyszcreoa")
EXPAND = {"far": ["distance", "distant"], "away": ["distance"], "big": ["size", "diameter"], "large": ["size", "diameter"],
          "old": ["age"], "hot": ["temperature"], "cold": ["temperature"], "heavy": ["mass", "weight"], "fast": ["velocity", "speed"],
          "quick": ["velocity"], "long": ["length", "period", "duration"], "cost": ["price", "expense"], "cause": ["causes", "reason"],
          "why": ["cause", "reason"], "die": ["death", "died"], "born": ["birth"], "kill": ["killed", "murder"]}


def fold(s: str) -> str:
    """lower case without accents: 'Rostóv' -> 'rostov', 'Borodinó' -> 'borodino'"""
    return s.lower().translate(FOLD)


def terms(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-z]+", fold(text)) if w not in STOP and len(w) > 1]


def query_terms(query: str) -> list[str]:
    """the question's words plus what plain words mean in a book ('how far' -> distance, 'how old' -> age)"""
    ws = re.findall(r"[a-z]+", fold(query))
    out = terms(query)
    for w in ws:
        out += [stem(x) for x in EXPAND.get(w, [])]
    return list(dict.fromkeys(out))


def index(book: dict) -> dict:
    """built once per book: each Fact Unit's words (with its section title) and the document frequencies for BM25"""
    secs = book.get("sections") or {}
    sec_terms: dict[str, list[str]] = {}
    df: dict[str, int] = {}
    tfs: list[dict] = []
    lens: list[int] = []
    for u in book["units"]:
        key = str(u["section"])
        if key not in sec_terms:
            sec_terms[key] = terms(secs.get(key, ""))
        ts = terms(u["text"]) + sec_terms[key] if u["kind"] != "table" else []
        tf: dict[str, int] = {}
        for t in ts:
            tf[t] = tf.get(t, 0) + 1
        tfs.append(tf)
        lens.append(len(ts))
        for t in tf:
            df[t] = df.get(t, 0) + 1
    return {"df": df, "n": len(tfs), "avg": (sum(lens) / max(1, len(lens))), "tf": tfs, "len": lens}


def search(book: dict, idx: dict, query: str, chapter: int, limit: int) -> list[dict]:
    """BM25 (k1 = 1.4, b = 0.7) over the Fact Units, the section title counted with the unit; ties keep book order"""
    q = query_terms(query)
    if not q:
        return []
    k1, b = 1.4, 0.7
    n, avg, df = idx["n"], idx["avg"] or 1.0, idx["df"]
    idf = {t: math.log(1 + (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5)) for t in q}
    editorial = {c["n"] for c in book.get("chapters") or [] if c["n"] == 0 or c.get("editorial")}
    scored = []
    for i, u in enumerate(book["units"]):
        tf = idx["tf"][i]
        if not tf or (chapter and u["chapter"] != chapter):
            continue
        hit = [t for t in q if t in tf]
        if not hit:
            continue
        ln = idx["len"][i]
        s = 0.0
        for t in hit:
            f = tf[t]
            s += idf[t] * f * (k1 + 1) / (f + k1 * (1 - b + b * ln / avg))
        s *= 0.5 + len(hit) / len(q)
        if u["chapter"] in editorial:
            s *= 0.55                                      # an editor's preface or introduction answers less than the author's own text
        if u["kind"] == "note":
            s *= 0.7
        if u["kind"] == "procedure" or u["text"].rstrip().endswith("?"):
            s *= 0.5                                       # an exercise or a question asks; it does not answer
        elif u["kind"] in ("measurement", "definition"):
            s *= 1.15
        scored.append((-s, i))
    scored.sort()
    return [dict(book["units"][i], score=round(-sc, 3), idx=i) for sc, i in scored[:limit]]


# --------------------------------------------------------------------------- understanding the question
def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", s.lower()).split())


def chapter_in(book: dict, query: str) -> int:
    """'Chapter VII' / 'chapter 7' / a story's or chapter's own title ('A Scandal in Bohemia') -> that chapter's number"""
    q = query.lower()
    m = re.search(r"\bchapter\s+([ivxlc]+|\d+)\b", q)
    chs = book.get("chapters") or []
    if m:
        v = m.group(1).upper()
        num = int(v) if v.isdigit() else ROMAN.get(v, 0)
        for c in chs:
            lab = _norm(c["label"]).split()
            if len(lab) >= 2 and lab[0] == "chapter" and (lab[1] == str(num) or lab[1].upper() == ROMAN_OF.get(num, "?")):
                bm = re.search(r"\bbook\s+(\w+)", q)
                if bm and bm.group(1) not in _norm(c.get("part") or ""):
                    continue
                return c["n"]
        return 0
    nq = _norm(query)
    best, blen = 0, 0
    for c in chs:
        for t in (c.get("title") or "", re.sub(r"^[ivxlc]+\s+", "", _norm(c["label"]))):
            nt = _norm(t)
            if len(nt) >= 8 and nt in nq and len(nt) > blen:
                best, blen = c["n"], len(nt)
    return best


def person_in(book: dict, query: str) -> dict:
    """the listed character the question names (the longest matching name or alias)"""
    best, blen = {}, 0
    for p in book.get("people") or []:
        for a in [p["name"]] + list(p.get("aliases") or []):
            if len(a) > blen and re.search(r"(?<![\w])" + re.escape(fold(a)) + r"(?![\w])", fold(query)):
                best, blen = p, len(a)
    return best


def family_in(book: dict, query: str) -> str:
    q = fold(query)
    for p in book.get("people") or []:
        f = p.get("family") or ""
        if f and re.search(r"\b" + re.escape(fold(f)) + r"s?\b", q):
            return f
    return ""


def intent(query: str) -> str:
    q = query.lower()
    if re.search(r"(discovered|corrected|changed|learned|wrong|outdated|superseded|added).{0,40}since|since.{0,40}(published|1903|1901|written|book)", q):
        return "since"
    if re.search(r"still (considered )?(correct|true|accepted|valid|right)|remain(s)? accurate|confirmed", q):
        return "still_correct"
    if re.search(r"(current|modern|today'?s|accepted|present)[- ](accepted )?values?|revised|every (astronomical )?measurement", q):
        return "values"
    if re.search(r"reasonable in \d{4}|no longer accepted|why (was|did|were).{0,60}(believe|think|reasonable)|why .{0,40}(wrong|superseded|abandoned)", q):
        return "why"
    if re.search(r"beside the modern|modern (view|interpretation|verified)|compare .{0,40}modern|alongside", q):
        return "modern"
    if re.search(r"fictional .{0,30}historical|historical .{0,30}fictional|real (people|history|historical)|historical (figures|personalities|context)", q):
        return "historical"
    if re.search(r"network|connected to|relationships?|who (is|are) .{0,30}(close|related)", q):
        return "network"
    if re.search(r"\btrace\b|\bfollow\b|through the (book|novel|story)|across the novel", q):
        return "trace"
    if re.search(r"\btimeline\b|chronolog|in (what|which) order|dates?\b.{0,20}events|which .{0,30}ruled|between \d{2,4} and \d{2,4}", q):
        return "timeline"
    if re.search(r"first (appear|meet|mention)|where does .{0,40} first|when does .{0,40} first", q):
        return "first"
    if re.search(r"\bclues?\b|evidence|deduc|observ\w* .{0,20}(evidence|from)|reasoning", q):
        return "evidence"
    if re.search(r"who (narrates|tells|wrote each)|narrators?|each (diary|letter|journal)|letters?, diar", q):
        return "structure"
    if re.search(r"^(list|who are) (the )?(characters|people)|main characters|cast of characters", q.strip()):
        return "characters"
    if re.search(r"^(what is|what are|define|definition of|what does .* mean)", q.strip()):
        return "define"
    return "passages"


def assertion_view(book: dict, entry: dict) -> dict:
    """one book-vs-today row: the book's sentence(s) with anchors, the modern statement, status, sources, relationship"""
    us = [book["units"][i] for i in entry.get("units") or [] if 0 <= i < len(book["units"])]
    return {"id": entry["id"], "topic": entry["topic"], "status": entry["status"],
            "book": [{"text": u["text"], "anchor": anchor(book, u), "chapter": u["chapter"], "unit": u.get("id") or ""} for u in us[:3]],
            "modern": entry["modern"], "value": entry.get("value") or "", "sources": entry.get("sources") or [],
            "relationship": entry.get("relationship") or "", "why_then": entry.get("why_then") or "",
            "chapters": sorted({u["chapter"] for u in us})}


def passage(book: dict, i: int) -> dict:
    u = book["units"][i]
    return {"text": u["text"], "anchor": anchor(book, u), "kind": u["kind"], "quantities": u.get("quantities") or [],
            "unit": u.get("id") or "", "chapter": u["chapter"]}


def _chap_name(book: dict, n: int) -> str:
    c = chapter_of(book, n)
    s = c.get("label") or ""
    if c.get("title"):
        s += " — " + c["title"]
    if c.get("part"):
        s = c["part"] + ", " + s
    return s


def answer(book: dict, idx: dict, query: str, limit: int = 8) -> dict:
    """the anchored answer to one question about one book"""
    q = " ".join((query or "").split())
    out: dict = {"book": book.get("id"), "title": book.get("title"), "query": q, "intent": intent(q), "chapter": chapter_in(book, q),
                 "lead": "", "passages": [], "assertions": [], "new_since": [], "people": [], "edges": [], "timeline": [],
                 "chapters": [], "provenance": book.get("provenance") or {}}
    if not q:
        return out
    ch = out["chapter"]
    chname = _chap_name(book, ch) if ch else ""
    modern = book.get("modern") or []
    in_ch = [e for e in modern if not ch or ch in assertion_view(book, e)["chapters"]]
    it = out["intent"]
    people = book.get("people") or []
    who = person_in(book, q)
    if it in ("since", "still_correct", "values", "why", "modern") and not modern:
        out["lead"] = "This book has no modern verified layer yet, so QueryBook cannot set its statements beside today's knowledge. Here is what the book itself says:"
        it = "passages"
    if it == "since":
        rows = [assertion_view(book, e) for e in in_ch if e["status"] in ("Refined", "Superseded", "Incorrect")]
        out["assertions"] = rows
        out["new_since"] = (book.get("new_since") or []) if not ch else []
        out["lead"] = "%d checked statement%s in %s %s been refined, superseded or shown wrong since %s; %d discover%s the book could not mention %s listed after them." % (
            len(rows), "" if len(rows) == 1 else "s", chname or "the book", "has" if len(rows) == 1 else "have", book.get("year"),
            len(out["new_since"]), "y" if len(out["new_since"]) == 1 else "ies", "is" if len(out["new_since"]) == 1 else "are")
        return out
    if it == "still_correct":
        rows = [assertion_view(book, e) for e in in_ch if e["status"] in ("Confirmed", "Historically significant")]
        out["assertions"] = rows
        out["lead"] = "%d checked statement%s in %s %s still accepted today." % (
            len(rows), "" if len(rows) == 1 else "s", chname or "the book", "is" if len(rows) == 1 else "are")
        if ch:
            k = len(in_ch) - len(rows)
            out["lead"] += " %d other checked statement%s of this chapter %s been revised." % (k, "" if k == 1 else "s", "has" if k == 1 else "have")
        return out
    if it == "values":
        units = [i for i, u in enumerate(book["units"]) if u["kind"] == "measurement" and (not ch or u["chapter"] == ch)]
        linked = {i for e in in_ch for i in e.get("units") or []}
        out["assertions"] = [assertion_view(book, e) for e in in_ch if e.get("value")]
        out["passages"] = [dict(passage(book, i), checked=i in linked) for i in units[:60]]
        out["lead"] = "%s states %d measurement%s; %d %s a current accepted value below (the rest are worked examples, exercises or descriptions)." % (
            chname or "The book", len(units), "" if len(units) == 1 else "s", len(out["assertions"]), "has" if len(out["assertions"]) == 1 else "have")
        return out
    if it == "modern":
        out["assertions"] = [assertion_view(book, e) for e in in_ch]
        out["lead"] = "%d of the book's assertions set beside what is established today:" % len(out["assertions"])
        return out
    if it == "historical" and people:
        hist = [p for p in people if p["historical"]]
        fic = [p for p in people if not p["historical"]]
        out["people"] = [dict(_person_row(book, p), group="historical") for p in sorted(hist, key=lambda p: -p["count"])] + \
                        [dict(_person_row(book, p), group="fictional") for p in sorted(fic, key=lambda p: -p["count"])]
        out["assertions"] = [assertion_view(book, e) for e in modern]
        out["lead"] = ("%d of the listed people are real historical figures and %d are fictional characters (QueryBook's curated list for this book)." % (len(hist), len(fic))
                       if hist else "The listed characters are all fictional; the real events the story is set in are shown with their dates and sources.")
        return out
    if it == "network" and who:
        es = [e for e in book.get("edges") or [] if who["name"] in (e[0], e[1])]
        out["edges"] = [{"with": e[1] if e[0] == who["name"] else e[0], "together": e[2]} for e in es[:16]]
        out["people"] = [_person_row(book, who)]
        out["lead"] = "%s appears with %d of the listed characters; the strongest ties are with %s (counted as paragraphs in which both are named)." % (
            who["name"], len(es), ", ".join("%s (%d)" % (x["with"], x["together"]) for x in out["edges"][:3]) or "no one")
        return out
    fam = family_in(book, q)
    if it == "trace" and (who or fam):
        group = [who] if who else [p for p in people if p.get("family") == fam]
        out["people"] = [_person_row(book, p) for p in group]
        per: dict[int, list[int]] = {}
        for p in group:
            for i in p["units"]:
                per.setdefault(book["units"][i]["chapter"], []).append(i)
        out["chapters"] = [{"chapter": n, "name": _chap_name(book, n), "mentions": len(v), "first": passage(book, min(v))}
                           for n, v in sorted(per.items())]
        out["lead"] = "%s %s named in %d of the book's %d chapters, first in %s." % (
            who["name"] if who else "The %s family" % fam, "is" if who else "are", len(per), sum(1 for c in book.get("chapters") or [] if c["n"]),
            out["chapters"][0]["name"] if out["chapters"] else "—")
        return out
    if it == "first" and who and who["units"]:
        out["people"] = [_person_row(book, who)]
        out["passages"] = [passage(book, who["units"][0])]
        out["lead"] = "%s is first named in %s." % (who["name"], out["passages"][0]["anchor"])
        return out
    if it == "characters" and people:
        out["people"] = [_person_row(book, p) for p in sorted(people, key=lambda p: -p["count"])]
        out["lead"] = "%d listed characters, most often named first." % len(people)
        return out
    if it == "structure":
        out["chapters"] = [{"chapter": c["n"], "name": _chap_name(book, c["n"]), "mentions": c.get("paragraphs") or 0} for c in book.get("chapters") or []]
        out["lead"] = "How the book is put together, part by part (in letters, journals and diaries the chapter titles name who is writing):"
        return out
    if it == "timeline":
        ys = [y for y in book.get("years") or [] if not ch or book["units"][y[1]]["chapter"] == ch]
        m = re.search(r"between (\d{2,4}) and (\d{2,4})", q)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            ys = [y for y in ys if lo <= y[0] <= hi]
        seen: set = set()
        rows = []
        for y, i in sorted(ys, key=lambda t: (t[0], t[1])):
            if (y, i) in seen:
                continue
            seen.add((y, i))
            rows.append(dict(passage(book, i), year=y))
        out["timeline"] = rows[:120]
        out["lead"] = "%d dated statement%s%s, in order of the year named (each quoted with its place in the book)." % (
            len(rows), "" if len(rows) == 1 else "s", (" in " + chname) if ch else "")
        if rows:
            return out
    hits = search(book, idx, q, ch, limit)
    if it == "evidence" and (ch or hits):
        pool = [i for i, u in enumerate(book["units"]) if u["chapter"] == ch] if ch else sorted(h["idx"] for h in search(book, idx, q, 0, 80))
        rows = [dict(passage(book, i), reasoning=reasoning_kind(book["units"][i]["text"])) for i in pool]
        rows = [r for r in rows if r["reasoning"]]
        out["passages"] = rows[:80]
        out["lead"] = "%d passage%s%s in story order, each marked as observed evidence or as a deduction drawn from it (a reading of the words, shown with the sentence itself)." % (
            len(out["passages"]), "" if len(out["passages"]) == 1 else "s", (" from " + chname) if ch else "")
        return out
    if it == "why":
        best = None
        for e in modern:
            if e["status"] in ("Superseded", "Incorrect", "Refined") and any(h["idx"] in (e.get("units") or []) for h in hits):
                best = e
                break
        rows = [assertion_view(book, best)] if best else [assertion_view(book, e) for e in in_ch if e["status"] in ("Superseded", "Incorrect")]
        out["assertions"] = rows
        out["lead"] = (rows[0]["why_then"] or rows[0]["relationship"]) if len(rows) == 1 else \
            "%d statements of the book are no longer accepted; for each, why it was reasonable when written:" % len(rows)
        return out
    if it == "define":
        hits.sort(key=lambda h: (0 if h["kind"] == "definition" else 1, -h["score"]))
    out["passages"] = [dict(passage(book, h["idx"]), score=h["score"]) for h in hits]
    qt = set(query_terms(q))

    def on_topic(e: dict) -> bool:
        tt = set(terms(e["topic"]))
        return bool(tt) and len(tt & qt) >= min(2, len(tt))
    out["assertions"] = [assertion_view(book, e) for e in modern
                         if on_topic(e) or any(h["idx"] in (e.get("units") or []) for h in hits)]
    named = {p["name"] for p in people for h in hits if h["idx"] in p["units"]}
    out["people"] = [_person_row(book, p) for p in people if p["name"] in named]
    topical = [e for e in modern if on_topic(e) and e.get("units")]
    if topical and it in ("passages", "define"):
        lead_i = topical[0]["units"][0]                    # the book's own sentence on the very topic asked about
        out["passages"] = [passage(book, lead_i)] + [p for p in out["passages"] if p["unit"] != book["units"][lead_i].get("id")]
        out["lead"] = out["lead"] or book["units"][lead_i]["text"]
    if not out["lead"]:
        out["lead"] = hits[0]["text"] if hits else "The book does not say. No passage of %s answers this." % (book.get("title") or "this book")
    return out


def _person_row(book: dict, p: dict) -> dict:
    us = p.get("units") or []
    return {"name": p["name"], "aliases": p.get("aliases") or [], "family": p.get("family") or "", "historical": p.get("historical", False),
            "mentions": len(us), "first": anchor(book, book["units"][us[0]]) if us else "", "last": anchor(book, book["units"][us[-1]]) if us else ""}


def overview(book: dict) -> dict:
    """the library card: what the book is, its structure, Fact Units by kind, its layers"""
    kinds: dict[str, int] = {}
    for u in book["units"]:
        kinds[u["kind"]] = kinds.get(u["kind"], 0) + 1
    status: dict[str, int] = {}
    for e in book.get("modern") or []:
        status[e["status"]] = status.get(e["status"], 0) + 1
    return {"id": book.get("id"), "title": book.get("title"), "author": book.get("author"), "year": book.get("year"),
            "published": book.get("published"), "kind": book.get("kind"), "subject": book.get("subject"),
            "structure": book.get("structure"), "about": book.get("about") or "", "provenance": book.get("provenance") or {},
            "chapters": [{"n": c["n"], "label": c["label"], "title": c["title"], "part": c.get("part") or ""} for c in book.get("chapters") or []],
            "units": len(book["units"]), "kinds": kinds, "modern": status, "new_since": len(book.get("new_since") or []),
            "people": len(book.get("people") or []), "historical": sum(1 for p in book.get("people") or [] if p.get("historical")),
            "examples": book.get("examples") or []}


# --------------------------------------------------------------------------- the narrative layer (characters, network, years)
YEAR_RE = re.compile(r"A\.\s?D\.\s?([1-9][0-9]{1,3})(?![\d,])|(?<![\d,.])([1-9][0-9]{1,3})\s?(B\.\s?C\.|A\.\s?D\.)|(?<![\d,.£$])(1[0-9]{3})(?![\d,])")


def alias_re(aliases: list[str]) -> str:
    """one pattern for every name a character goes by (whole words, longest first)"""
    alts = sorted({a for a in aliases if a}, key=len, reverse=True)
    return r"(?<![\w’'])(?:" + "|".join(re.escape(a) for a in alts) + r")(?![\w])"


def mentions(units: list[dict], characters: list[dict]) -> list[dict]:
    """for each listed character: the Fact Units that name them (any alias), in book order"""
    out = []
    for c in characters:
        r = re.compile(alias_re([c["name"]] + list(c.get("aliases") or [])))
        idx = [i for i, u in enumerate(units) if u["kind"] != "table" and u["chapter"] != 0 and r.search(u["text"])]   # not in an editor's front matter
        out.append({"name": c["name"], "aliases": c.get("aliases") or [], "family": c.get("family") or "",
                    "historical": bool(c.get("historical")), "units": idx, "count": len(idx)})
    return out


def network(units: list[dict], people: list[dict], limit: int) -> list[list]:
    """who appears with whom: two characters named in the same paragraph, counted once per paragraph"""
    where: list[set] = []
    for p in people:
        where.append({(units[i]["chapter"], units[i]["para"], units[i]["section"]) for i in p["units"]})
    edges = []
    for a in range(len(people)):
        for b in range(a + 1, len(people)):
            n = len(where[a] & where[b])
            if n:
                edges.append([people[a]["name"], people[b]["name"], n])
    edges.sort(key=lambda e: (-e[2], e[0], e[1]))
    return edges[:limit]


def other_names(units: list[dict], known: list[str], limit: int) -> list[dict]:
    """capitalised names that are not at the start of a sentence, most frequent first (people and places alike) — the
    book's own index of proper names beyond the listed characters"""
    skip = {w.lower() for k in known for w in k.split()}
    count: dict[str, int] = {}
    first: dict[str, int] = {}
    for i, u in enumerate(units):
        if u["kind"] == "table":
            continue
        for m in re.finditer(r"(?<=[a-z,;:] )([A-Z][a-zà-öø-ÿ’']+(?: (?:de |von |van |du |of |la )?[A-Z][a-zà-öø-ÿ’']+)*)", u["text"]):
            n = m.group(1).rstrip("’'")
            low = n.lower()
            if low in STOP or low in skip or len(n) < 3 or low in ("i", "god", "sir", "mr", "mrs", "miss", "lady", "lord"):
                continue
            count[n] = count.get(n, 0) + 1
            first.setdefault(n, i)
    rows = [{"name": n, "count": c, "first": first[n]} for n, c in count.items() if c >= 3]
    rows.sort(key=lambda r: (-r["count"], r["name"]))
    return rows[:limit]


def years(units: list[dict], limit: int) -> list[list]:
    """[year, unit] for every year a sentence names — 'A.D. 476', '44 B.C.' (negative), '1812' — in book order"""
    out = []
    for i, u in enumerate(units):
        if u["kind"] == "table":
            continue
        for m in YEAR_RE.finditer(u["text"]):
            if m.group(1):
                y = int(m.group(1))
            elif m.group(2):
                y = int(m.group(2)) * (-1 if m.group(3).startswith("B") else 1)
            else:
                y = int(m.group(4))
            out.append([y, i])
            if len(out) >= limit:
                return out
    return out


# --------------------------------------------------------------------------- reasoning (detective stories, arguments)
OBSERVED = re.compile(r"\b(I (saw|observed|noticed|perceived|remarked|found|heard)|there (was|were)|you (see|observe)|"
                      r"(left|right) (sleeve|shoe|hand|cuff|boot)|mark(s|ed)?\b|stain|trace|footprint|scratch|ash|mud|wear|worn)", re.I)
DEDUCED = re.compile(r"\b(therefore|deduce|deduction|infer|inference|conclude|conclusion|must have|it follows|"
                     r"obviously|evidently|clearly|plainly|hence|which proves|that is why|it is (clear|obvious|evident))\b", re.I)


def reasoning_kind(sentence: str) -> str:
    """'observed' (a fact seen or found), 'deduced' (an inference drawn from facts) or '' — a word-pattern reading,
    shown as such; the sentence itself is always quoted"""
    d, o = bool(DEDUCED.search(sentence)), bool(OBSERVED.search(sentence))
    return "deduced" if d else "observed" if o else ""
