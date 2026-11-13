"""QueryBook's writing skills — the user's Writing Skills Plan (docs/querybook-rebuild/writing-skills-plan.md).

Writing knowledge is held as structured rules at five layers, and a document is produced by plan -> draft -> critique ->
revise. This module is the part that needs no AI and invents nothing:

  phase 0, the grammar   every sentence has a TOPIC (what the reader already holds) and a COMMENT (what is new); a paragraph
                         relates its topics in one of four ways — constant theme, linking, index, theme preview. A tagger,
                         a classifier and the four checks.
  the genre library      one record per document type (genres.json): purpose, reader, sections and their moves, the
                         framework at each scale, register, evidence rules, hard constraints, failure modes.
  the machine's plan     brief -> genre -> blueprint, and the critic: a draft judged at all five layers against the same
                         record it was planned from.

Pure and rule-based (in the Rust-compat list). The tagger is a set of rules, not a parser: it is measured against a
hand-labelled sample in the tests, and what it cannot tell it marks as unsure rather than guessing.
"""
from __future__ import annotations

import json
import re

FRAMEWORKS = ("constant theme", "linking", "index", "theme preview")
LAYERS = ("sentence flow", "paragraph pattern", "document structure", "rhetorical situation", "domain convention")

# ---------------------------------------------------------------------------------------------- words the rules need
AUX = frozenset("is are was were be been being am has have had do does did will would can could may might must shall should "
                "isn't aren't wasn't weren't hasn't haven't hadn't doesn't don't didn't won't wouldn't can't cannot couldn't "
                "shouldn't mustn't 's 're".split())
VERBS = frozenset(
    "accept add affect agree allow answer appear apply argue arrive ask become begin believe belong break bring build buy call carry "
    "cause change check choose claim close collect come compare consider consist contain continue control cost count cover create cut "
    "decide define depend describe design develop die differ discover divide draw drive drop eat end enter establish exist expect "
    "explain express fail fall feel fill find finish fit follow form gain get give go grow happen hear help hold hope identify "
    "include increase indicate influence introduce involve join keep kill know lead learn leave let lie like limit link list listen "
    "live look lose make mark matter mean measure meet mention move name need note occur offer open operate order organise organize "
    "own pass pay perform place plan play point prefer prepare present prevent produce protect prove provide publish pull push put "
    "raise reach read receive record reduce refer reflect remain remember remove replace report represent require rest result return "
    "reveal rise run save say see seem sell send serve set share show sit solve sound speak spend stand start state stay stop store "
    "study suggest support suppose take talk teach tell tend test thank think throw touch train travel treat try turn understand use "
    "visit wait walk want watch wear win wish wonder work write "
    "absorb act announce approve arrest attack attend avoid beat boil burn calculate catch charge climb combine compete complete "
    "confirm connect convert cross deliver demand deny destroy detect direct earn elect employ enable enjoy escape estimate examine "
    "expand feed fight flow fly found freeze generate govern guide hang hit improve invent invest jump launch lift manage marry melt "
    "miss notice observe obtain orbit paint pick power pour predict press print promise pump rain recommend reject release rely "
    "repeat request resist respond reveal ride ring rule sail score search select separate shake shine shoot sign sing sink sleep "
    "smile spread steal strike struggle succeed suffer supply survive swim teach tear translate trust vote warn wash weigh wonder".split())
IRREGULAR = frozenset(
    "became began brought built bought came chose cut did drew drove ate fell felt found gave went grew heard held kept knew led "
    "learnt left let lay lost made meant met paid put read ran said saw sold sent set showed shown sat spoke spent stood took told "
    "thought threw understood wore won wrote written given taken known seen done gone become begun broken chosen driven eaten "
    "fallen grown spoken thrown rose risen fed fled sped shot hurt sang drank swam flew blew struck hung dug stuck taught caught fought "
    "sought slept wept swept bent lent dealt burnt shook woke froze stole rode hid bit tore swore bore forgave forgot withdrew "
    "overcame arose sank rang shone fought beaten stolen frozen ridden hidden torn sworn borne forgotten flown blown sung drunk swum".split())
PRONOUNS = frozenset("it he she they we you i this that these those its his her their".split())
POINTERS = frozenset("this that these those such".split())
FRONT = frozenset("in on at by for from with without after before during since until when while although though because if as "
                  "despite under over between among through throughout within however therefore moreover furthermore thus then "
                  "first second third finally next meanwhile today yesterday later earlier instead consequently similarly also to".split())
STOP = frozenset("the a an of and or but to in on at by for from with as is are was were be been it its this that these those "
                 "their his her they he she we you i not no so than then there which who whom whose what when where how".split())
NUMBER_WORDS = frozenset("two three four five six seven eight nine ten several many various multiple".split())
UMBRELLA = ("consists of", "is made of", "is made up of", "comprises", "includes", "has", "have", "contains", "is divided into",
            "are divided into", "falls into", "fall into", "kinds of", "types of", "parts", "components", "stages", "layers", "steps",
            "categories", "elements", "factors", "reasons", "ways")
WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*|\d+(?:[.,]\d+)*", re.UNICODE)


def sentences(text: str) -> list[str]:
    """split one paragraph into sentences without breaking 'Dr. Smith', '3.5' or 'e.g.'"""
    flat = " ".join(text.split())
    out: list[str] = []
    start = 0
    for m in re.finditer(r"[.!?]+[\"'”’)\]]*\s+(?=[\"'“‘(\[]?[A-Z0-9])", flat):
        before = flat[start:m.start()].split()
        last = before[-1].lower().rstrip(".") if before else ""
        if last in ("mr", "mrs", "ms", "dr", "prof", "st", "vs", "etc", "e.g", "i.e", "no", "fig", "jr", "sr", "inc", "ltd", "co") or (len(last) == 1 and last.isalpha()):
            continue
        out.append(flat[start:m.end()].strip())
        start = m.end()
    if flat[start:].strip():
        out.append(flat[start:].strip())
    return out


def paragraphs(text: str) -> list[str]:
    return [" ".join(p.split()) for p in re.split(r"\n\s*\n", text.replace("\r\n", "\n")) if p.strip()]


def stem(w: str) -> str:
    """a crude stem, enough to see that 'teams' and 'team', 'divided' and 'divide' are one word"""
    w = w.lower().replace("’", "'")
    for suf in ("'s", "ies", "ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[:-len(suf)] + ("y" if suf == "ies" else "")
    return w


def content(text: str) -> list[str]:
    return [stem(w) for w in WORD.findall(text) if w.lower() not in STOP and not w.isdigit()]


def is_verb(word: str, first: bool) -> bool:
    w = word.lower().replace("’", "'")
    if w in AUX:
        return True
    if first:
        return False
    if w in IRREGULAR or w in VERBS:
        return True
    for suf in ("ed", "es", "s", "d"):
        if w.endswith(suf) and w[:-len(suf)] in VERBS:
            return True
    if w.endswith("ies") and w[:-3] + "y" in VERBS:
        return True
    return False


# ---------------------------------------------------------------------------------------------- phase 0: the tagger
def tag(sentence: str) -> dict:
    """one sentence -> {"frame", "topic", "comment", "pointer", "pronoun", "sure"}.
    topic: the subject the sentence opens on (after any framing phrase such as "In 1981,"); comment: what is said of it.
    sure is False when no verb was found — the sentence is then left whole in the topic and nothing is claimed about it."""
    s = " ".join(sentence.split())
    frame = ""
    m = re.match(r"^([^,;:]{2,60}),\s+(.*)$", s)
    if m and m.group(1).split()[0].lower() in FRONT and len(m.group(2).split()) >= 2:
        frame, s = m.group(1), m.group(2)
    toks = s.split()
    cut = -1
    for i, t in enumerate(toks):
        w = t.strip("\"'“”‘’()[],;:.!?")
        nxt = toks[i + 1].lower().strip("\"'“”‘’(") if i + 1 < len(toks) else ""
        if w and is_verb(w, i == 0) and not (i > 0 and toks[i - 1].lower().strip("\"'“”") in ("the", "a", "an", "to", "of", "in", "on", "for", "by")) \
                and not (w.lower() not in AUX and nxt in AUX):          # "rain is expected": a word before an auxiliary is the subject's noun
            cut = i
            break
    if cut <= 0:                                        # no known verb: the first word shaped like one, followed by what a verb is followed by
        after = frozenset("the a an at in on over to from through by with into for about of his her its their this that these those".split())
        for i in range(1, len(toks)):
            w = toks[i].strip("\"'“”‘’()[],;:.!?").lower()
            nxt = toks[i + 1].lower().strip("\"'“”‘’(") if i + 1 < len(toks) else ""
            shaped = (w.endswith("ed") and len(w) > 4) or (w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 3)
            last = i + 1 == len(toks)
            if shaped and (nxt in after or nxt[:1].isdigit() or (last and w.endswith("ed"))) and not toks[i - 1].endswith(",") \
                    and toks[i - 1].lower() not in ("the", "a", "an", "of"):
                cut = i
                break
    if cut <= 0:
        return {"frame": frame, "topic": s.rstrip(".!?"), "comment": "", "pointer": False, "pronoun": False, "sure": False}
    topic = " ".join(toks[:cut]).strip(" ,")
    first = toks[0].lower().strip("\"'“”‘’(")
    return {"frame": frame, "topic": topic, "comment": " ".join(toks[cut:]).rstrip(), "pointer": first in POINTERS,
            "pronoun": first in PRONOUNS and len(toks[:cut]) <= 2, "sure": True}


def overlap(a: list[str], b: list[str]) -> bool:
    return bool(set(a) & set(b))


# ---------------------------------------------------------------------------------------------- phase 0: the classifier
def framework(paragraph: str) -> dict:
    """which of the four frameworks a paragraph follows, with the evidence: {"framework", "sentences": [...tags with how each
    topic relates to what came before...], "same", "linked", "members", "of", "check": {"ok", "why"}}.
    framework is "" for a single sentence or when no pattern holds for most sentences ("mixed")."""
    sents = sentences(paragraph)
    tags = [tag(s) for s in sents]
    n = len(tags)
    if n < 2:
        return {"framework": "", "sentences": tags, "same": 0, "linked": 0, "members": 0, "of": max(0, n - 1), "check": {"ok": True, "why": "one sentence"}}
    t1 = content(tags[0]["topic"])
    c1 = content(tags[0]["comment"])
    low1 = sents[0].lower()
    umbrella = (any(u in low1 for u in UMBRELLA) and (any(w in NUMBER_WORDS for w in low1.replace(":", " ").split()) or ":" in sents[0]
                                                      or re.search(r"\b\d+\b", low1) is not None or "," in tags[0]["comment"]))
    same = linked = members = 0
    for i in range(1, n):
        t = tags[i]
        topic = content(t["topic"])
        prev_topic, prev_comment = content(tags[i - 1]["topic"]), content(tags[i - 1]["comment"])
        rel = ""
        if t["pronoun"] and not t["pointer"]:
            rel = "same"
        elif overlap(topic, t1):
            rel = "same"
        if t["pointer"] or (overlap(topic, prev_comment) and not overlap(topic, prev_topic)):
            rel = "linked" if rel != "same" or t["pointer"] else rel
        if umbrella and overlap(topic, c1) and not overlap(topic, t1):
            rel = "member"
        t["relation"] = rel
        same += rel == "same"
        linked += rel == "linked"
        members += rel == "member"
    of = n - 1
    name = ""
    if umbrella and members >= max(1, round(0.6 * of)):
        name = "index"
    elif same >= max(1, round(0.7 * of)):
        name = "constant theme"
    elif linked >= max(1, round(0.6 * of)):
        name = "linking"
    out = {"framework": name, "sentences": tags, "same": same, "linked": linked, "members": members, "of": of}
    out["check"] = check_paragraph(out)
    return out


def check_paragraph(f: dict) -> dict:
    """the plan's automatic check for the paragraph's framework"""
    name, of = f["framework"], f["of"]
    if name == "constant theme":
        if of + 1 > 6:
            return {"ok": False, "why": "%d sentences open on the same subject: the paragraph is static — move to a new aspect or link forward" % (of + 1)}
        return {"ok": True, "why": "every sentence opens on the same subject"}
    if name == "linking":
        broken = [i + 2 for i, t in enumerate(f["sentences"][1:]) if t.get("relation") != "linked"]
        return {"ok": not broken, "why": "each sentence opens on what the one before ended with" if not broken
                else "the chain breaks at sentence %s" % ", ".join(str(b) for b in broken)}
    if name == "index":
        stray = [i + 2 for i, t in enumerate(f["sentences"][1:]) if t.get("relation") != "member"]
        return {"ok": not stray, "why": "the whole is named first and every later sentence opens on a part of it" if not stray
                else "sentence %s does not open on a part named in the first sentence" % ", ".join(str(b) for b in stray)}
    if of < 1:
        return {"ok": True, "why": "one sentence"}
    return {"ok": False, "why": "no pattern: the sentences open on unrelated subjects — keep one subject, or open each sentence on what the last one introduced"}


def preview_terms(text: str) -> list[str]:
    """the destinations an opening announces: the items of the first list in it ("accuracy, speed and reliability")"""
    opening = [s for p in paragraphs(text)[:3] if not re.match(r"^#{1,6}\s", p) for s in sentences(p)]
    for s in opening[:4]:
        m = re.search(r"(?::|\b(?:covers?|discuss(?:es)?|describes?|examines?|presents?|explains?|sets? out|looks? at|are|follow(?:s|ing)?)\b)\s*(.+)$", s)
        if not m:
            continue
        parts = [p.strip(" .;") for p in re.split(r",\s*(?:and\s+|or\s+)?|\s+and\s+|;\s*", m.group(1)) if p.strip(" .;")]
        parts = [re.sub(r"^(?:the|a|an|its|their|then|finally|first|second|third)\s+", "", p, flags=re.I) for p in parts]
        if len(parts) >= 2 and all(1 <= len(p.split()) <= 6 for p in parts):
            return parts
    return []


def headings(text: str) -> list[str]:
    """the section headings of a draft: Markdown '# ', a line ending in ':' alone, or a short line of Capitalised Words alone"""
    out: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        ln = line.strip()
        if not ln:
            continue
        m = re.match(r"^#{1,6}\s+(.+?)\s*#*$", ln)
        if m:
            out.append(m.group(1).strip())
        elif re.match(r"^(?:\d+[.)]\s+)?[A-Z][^.!?]{1,70}:?$", ln) and len(ln.split()) <= 9 and not ln.endswith(",") \
                and (ln.endswith(":") or ln == ln.title() or ln.isupper() or re.match(r"^\d+[.)]\s", ln) is not None):
            out.append(re.sub(r"^\d+[.)]\s+", "", ln).rstrip(":").strip())
    return out


def check_preview(text: str) -> dict:
    """theme preview: the destinations announced are visited under the same words, in the same order"""
    terms = preview_terms(text)
    heads = headings(text)
    if not terms:
        return {"ok": True, "previewed": [], "headings": heads, "why": "no preview is announced"}
    low = [h.lower() for h in heads]
    found = [next((i for i, h in enumerate(low) if t.lower() in h or h in t.lower()), -1) for t in terms]
    missing = [t for t, i in zip(terms, found) if i < 0]
    order = [i for i in found if i >= 0]
    if missing:
        return {"ok": False, "previewed": terms, "headings": heads,
                "why": "announced but not found as a heading in the same words: %s" % ", ".join(missing)}
    if order != sorted(order):
        return {"ok": False, "previewed": terms, "headings": heads, "why": "the sections are not in the order they were announced"}
    return {"ok": True, "previewed": terms, "headings": heads, "why": "every announced part has its section, in the same words and order"}


# ---------------------------------------------------------------------------------------------- the genre library
def load_genres(raw: str) -> dict:
    """genres.json -> {"families": [...], "genres": {id: record}}"""
    d = json.loads(raw)
    return {"families": d["families"], "genres": {g["id"]: g for g in d["genres"]}, "status": d.get("status", ""), "version": d.get("version", ""),
            "styles": {x["id"]: x for x in d.get("styles") or []}, "sources": {x["id"]: x for x in d.get("sources") or []},
            "fields": {x["id"]: x for x in d.get("fields") or []}}


def select_genre(brief: str, library: dict) -> dict:
    """the genre a brief asks for: {"id", "why", "blend": id or ""} — by the document type it names; "" when it names none
    (the machine then asks, it does not guess)"""
    low = " " + " ".join(brief.lower().split()) + " "
    hits: list[tuple[int, int, str]] = []
    for gid, g in library["genres"].items():
        for name in [g["name"]] + list(g.get("also") or []):
            at = low.find(" " + name.lower())
            if at >= 0:
                hits.append((at, -len(name), gid))
    if not hits:
        return {"id": "", "why": "the brief does not name a kind of document", "blend": ""}
    hits.sort()
    first = hits[0][2]
    end = hits[0][0] + (-hits[0][1])                    # a name inside the first name ("report" in "crime report") is not a second genre
    other = next((h[2] for h in hits[1:] if h[2] != first and h[0] >= end), "")
    return {"id": first, "why": "the brief asks for %s" % library["genres"][first]["name"], "blend": other}


def brief_gaps(brief: str) -> list[str]:
    """what a brief leaves out — asked for, never guessed"""
    low = brief.lower()
    gaps: list[str] = []
    if not re.search(r"\b(for|to|readers?|audience|aimed at|customers?|students?|board|managers?|team|public|clients?|judge|editor)\b", low):
        gaps.append("who will read it")
    if not re.search(r"\b(so that|in order to|to (?:decide|persuade|explain|inform|report|teach|record|propose|request|argue)|because|purpose|goal)\b", low):
        gaps.append("what it is for (what the reader should know or do afterwards)")
    if not re.search(r"\b\d+\s*(?:words?|pages?|minutes?|paragraphs?)\b|\b(short|brief|long|one[- ]page|full[- ]length)\b", low):
        gaps.append("how long it should be")
    return gaps


def with_field_and_style(bp: dict, field: dict, style: dict) -> dict:
    """the blueprint for a document written in a FIELD and a STYLE (either may be empty): the field brings its citation
    system and its standard of evidence; the style brings the habits the draft is asked to come near"""
    out = dict(bp)
    if field:
        out["field"] = field
    if style:
        out["style"] = style
    return out


def blueprint(genre: dict, brief: str) -> dict:
    """the plan a draft is written against and judged by: sections in order with the move each must make, the framework at
    document, section and paragraph scale, the fixed terms the preview will promise, register, evidence, hard constraints"""
    secs = [{"n": i + 1, "section": s["name"], "move": s["move"], "required": bool(s.get("required", True)),
             "framework": s.get("framework") or genre["frameworks"]["paragraph"]} for i, s in enumerate(genre["sections"])]
    terms = [s["section"] for s in secs if s["required"]][1:]
    return {"genre": genre["id"], "name": genre["name"], "family": genre["family"], "purpose": genre["purpose"], "reader": genre["reader"],
            "frameworks": genre["frameworks"], "sections": secs, "fixed_terms": terms, "register": genre["register"],
            "evidence": genre["evidence"], "constraints": genre.get("constraints") or [], "failure_modes": genre.get("failures") or [],
            "headed": bool(genre.get("headed", True)), "learned": list(genre.get("learned") or []),
            "asks": brief_gaps(brief), "fiction": genre["family"] == "fiction"}


def plain_blueprint() -> dict:
    """no genre chosen: the grammar layers alone are judged (sentence flow and paragraph pattern)"""
    return {"genre": "", "name": "text", "family": "", "purpose": "", "reader": "the intended reader", "sections": [], "fixed_terms": [],
            "frameworks": {"document": "", "section": "", "paragraph": ""}, "register": {"person": "any", "tense": "any", "formality": "any",
                                                                                         "hedging": "free", "words": [0, 10 ** 9]},
            "evidence": "", "constraints": [], "failure_modes": [], "asks": [], "fiction": False, "headed": True}


def writer_brief(bp: dict) -> str:
    """the blueprint as instructions for whoever drafts — a model or a person: the same record the critic will judge by"""
    r = bp["register"]
    lines = ["Write %s. Reader: %s. Purpose: %s." % (a_an(bp["name"]), bp["reader"], bp["purpose"]),
             "Sections, in this order, each under a line '## <name>' with the name exactly as given:"]
    for s in bp["sections"]:
        lines.append("  %d. %s%s — it must %s. Paragraphs here: %s." % (s["n"], s["section"], "" if s["required"] else " (only if the brief gives material for it)",
                                                                       s["move"], FRAMEWORK_HOW[s["framework"]]))
    if bp["frameworks"]["document"].startswith("theme preview") and len(bp["fixed_terms"]) >= 2:
        lines.append("Early on, announce the parts to come in one sentence, using the section names word for word and in order. Never rename a part later.")
    lines.append("Register: %s person, %s tense, %s; %s. Length about %d to %d words." % (
        r["person"], r["tense"], r["formality"], {"none": "no hedging", "some": "hedge only where the evidence is uncertain", "free": "the voice is yours"}[r["hedging"]],
        r["words"][0], r["words"][1]))
    lines.append("Evidence: %s." % bp["evidence"])
    lines.append("Sentences: open each on something the reader already holds, and put what is new at the end. Name the whole before its parts.")
    for c in bp["constraints"]:
        lines.append("Hard rule: %s." % c)
    f = bp.get("field")
    if f:
        lines.append("Field: %s. Evidence in this field: %s. Cite in the field's customary way (%s) only where the brief or the facts give a source; never invent one."
                     % (f["name"], f["evidence"], f["citation"]))
    for u in (bp.get("learned") or [])[:12]:
        lines.append("Learned rule%s: %s" % (" (%s)" % u["section"] if u.get("section") else "", u["rule"]))
    if bp.get("style"):
        lines.append(style_brief(bp["style"]))
    return "\n".join(lines)


FRAMEWORK_HOW = {"constant theme": "keep one subject at the head of each sentence, for at most six sentences",
                 "linking": "open each sentence on what the sentence before introduced",
                 "index": "name the whole first, then open each later sentence on one of its parts",
                 "theme preview": "announce the parts, then take them in the announced order"}


def a_an(phrase: str) -> str:
    return ("an " if phrase[:1].lower() in "aeiou" else "a ") + phrase


def blueprint_text(bp: dict) -> str:
    lines = ["%s — blueprint" % bp["name"].capitalize(), "For: %s" % bp["reader"], "Purpose: %s" % bp["purpose"],
             "Shape: %s across the document; %s within a section; %s within a paragraph" % (
                 bp["frameworks"]["document"], bp["frameworks"]["section"], bp["frameworks"]["paragraph"]), ""]
    for s in bp["sections"]:
        lines.append("%d. %s%s — %s" % (s["n"], s["section"], "" if s["required"] else " (optional)", s["move"]))
    r = bp["register"]
    lines += ["", "Register: %s person, %s tense, %s; about %d–%d words." % (r["person"], r["tense"], r["formality"], r["words"][0], r["words"][1]),
              "Evidence: %s" % bp["evidence"]]
    if bp["constraints"]:
        lines += ["Cannot be traded away:"] + ["  • " + c for c in bp["constraints"]]
    if bp.get("field"):
        lines.append("Field: %s — evidence: %s; cited in %s." % (bp["field"]["name"], bp["field"]["evidence"], bp["field"]["citation"]))
    if bp.get("style"):
        lines.append("Style: %s%s" % (bp["style"]["name"], " — " + bp["style"]["about"] if bp["style"].get("about") else ""))
    if bp.get("learned"):
        lines += ["Rules learned from sources:"] + ["  • %s  [%s]" % (u["rule"], u.get("source", "")) for u in bp["learned"][:12]]
    if bp["asks"]:
        lines += ["", "The brief does not say: " + "; ".join(bp["asks"]) + "."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------- the critic
UNHEADED_SECTIONS = frozenset(("heading", "headline", "title and summary", "parties and date", "signatures", "citation", "scene heading"))
FIRST_PERSON = re.compile(r"\b(i|me|my|mine|we|us|our|ours)\b", re.I)
SECOND_PERSON = re.compile(r"\b(you|your|yours)\b", re.I)
CITATION = re.compile(r"\(\s*[A-Z][^()]{1,60}?,?\s+\d{4}[a-z]?(?:,\s*p+\.\s*\d+)?\s*\)|\[\d+(?:[,–-]\s*\d+)*\]|\bet al\.|\bibid\b|https?://", re.I)
ATTRIBUTION = re.compile(r"\b(said|says|according to|told|stated|reported|confirmed|announced|police said|officials said)\b", re.I)
HEDGE = re.compile(r"\b(may|might|could|perhaps|possibly|appears? to|seems? to|suggests?|likely)\b", re.I)
VAGUE = re.compile(r"\b(very|really|quite|basically|actually|clearly|obviously|world[- ]class|cutting[- ]edge|best[- ]in[- ]class|revolutionary|game[- ]chang\w+)\b", re.I)
STEP_LINE = re.compile(r"^\s*(?:\d+[.)]|step \d+[:.)]?)\s+(\S+)", re.I | re.M)
ALLEGED = re.compile(r"\b(alleged(?:ly)?|accused of|charged with|suspected of|is suspected|police say|according to police|pleaded)\b", re.I)


def run_check(check: str, text: str, bp: dict) -> dict:
    """one testable failure mode of a genre: {"ok": bool|None, "why"} — None when it needs a person to judge"""
    words = WORD.findall(text)
    sents = [s for p in paragraphs(text) for s in sentences(p)]
    opening = [s for p in paragraphs(text) if len(sentences(p)) >= 2 for s in sentences(p)] or sents
    head = " ".join(opening[:max(2, len(opening) // 6)])
    if check == "conclusion_first":
        ok = re.search(r"\b(recommend\w*|conclud\w*|we should|should|must|please|ask(?:s|ing)?|needs? to|decision|the answer is|in short|result|"
                       r"found that|proposes?|request\w*|verdict|worth)\b", head, re.I) is not None
        return {"ok": ok, "why": "the opening states the conclusion or the request" if ok else "the opening does not state the conclusion, recommendation or request — a reader who stops there learns nothing"}
    if check == "no_first_person":
        n = len(FIRST_PERSON.findall(text))
        return {"ok": n == 0, "why": "no first person" if n == 0 else "%d uses of I / we / our in a genre that is written impersonally" % n}
    if check == "citations":
        n = len(CITATION.findall(text))
        return {"ok": n > 0, "why": "%d citations" % n if n else "no citation: claims drawn from sources are not attributed"}
    if check == "attribution":
        n = len(ATTRIBUTION.findall(text))
        need = max(1, len(sents) // 6)
        return {"ok": n >= need, "why": "%d attributions in %d sentences" % (n, len(sents)) if n >= need else "only %d attribution%s in %d sentences: say who said or confirmed each thing" % (n, "" if n == 1 else "s", len(sents))}
    if check == "lead_5w":
        lead = opening[0] if opening else ""          # the first sentence of the story itself, not its headline
        has = sum(1 for pat in (r"\b[A-Z][a-z]+", r"\b(?:on|at|in|yesterday|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{4})\b",
                                r"\b(?:in|at|near|outside)\s+[A-Z]") if re.search(pat, lead))
        ok = has >= 2 and len(lead.split()) <= 40
        return {"ok": ok, "why": "the first sentence says who or what, and when or where, in %d words" % len(lead.split()) if ok
                else "the first sentence should say what happened, to whom, when and where, in 40 words or fewer (it has %d)" % len(lead.split())}
    if check == "steps_numbered":
        n = len(STEP_LINE.findall(text))
        return {"ok": n >= 2, "why": "%d numbered steps" % n if n >= 2 else "the steps are not numbered one action to a line"}
    if check == "steps_imperative":
        firsts = [w.lower() for w in STEP_LINE.findall(text)]
        bad = [w for w in firsts if w in PRONOUNS or w in ("the", "a", "an", "there", "next", "then") or w.endswith("ing")]
        if not firsts:
            return {"ok": None, "why": "no numbered steps to check"}
        return {"ok": not bad, "why": "every step begins with the action" if not bad else "%d step%s do not begin with the action to take" % (len(bad), "" if len(bad) == 1 else "s")}
    if check == "lawyer_review":
        ok = re.search(r"\b(qualified|licensed|admitted)\s+(lawyer|attorney|solicitor|counsel)\b|\bnot legal advice\b|\breview(?:ed)? by (?:a |an )?(?:lawyer|attorney|solicitor|counsel)\b", text, re.I) is not None
        return {"ok": ok, "why": "it says it is a draft for a qualified lawyer" if ok else "a legal document must say it is a draft for a qualified lawyer to review"}
    if check == "defined_terms":
        defined = set(re.findall(r"[\"“]([A-Z][A-Za-z ]{1,40})[\"”]\s+means\b|\(\s*(?:the\s+)?[\"“]([A-Z][A-Za-z ]{1,40})[\"”]\s*\)", text))
        n = len([d for pair in defined for d in pair if d])
        return {"ok": n > 0, "why": "%d defined terms" % n if n else "no defined terms: name each party and key term once (\"Supplier\" means …) and use it unchanged"}
    if check == "no_vague_praise":
        hits = sorted({m.group(0).lower() for m in VAGUE.finditer(text)})
        return {"ok": not hits, "why": "no empty intensifiers or sales words" if not hits else "empty or promotional words: %s" % ", ".join(hits[:8])}
    if check == "allegation_marked":
        crime = re.search(r"\b(arrest\w*|murder\w*|robb\w*|assault\w*|stabb\w*|shot|shooting|theft|stole|burglar\w*|fraud|suspect)\b", text, re.I)
        if not crime:
            return {"ok": True, "why": "no accusation is reported"}
        ok = ALLEGED.search(text) is not None
        return {"ok": ok, "why": "accusations are marked as accusations and attributed" if ok
                else "an offence is reported without \"alleged\", \"charged with\" or \"police say\": an accusation is not a finding of guilt"}
    if check == "hedged_forecast":
        n = len(re.findall(r"\b(\d{1,3}\s?%|percent chance|chance of|likely|expected|forecast\w*|probab\w+)\b", text, re.I))
        return {"ok": n > 0, "why": "the forecast states its likelihood" if n else "a forecast must state how likely it is and for when"}
    if check == "abstract_length":
        n = len(words)
        return {"ok": 100 <= n <= 300, "why": "%d words" % n if 100 <= n <= 300 else "%d words: an abstract runs 100 to 300" % n}
    if check == "dialogue_present":
        n = len(re.findall(r"[\"“][^\"”]{2,}[\"”]", text))
        return {"ok": n >= 2, "why": "%d lines of dialogue" % n if n >= 2 else "almost no dialogue: let the characters speak"}
    if check == "scene_turns":
        ok = re.search(r"\b(but|until|then|suddenly|instead|only to|when)\b", text, re.I) is not None and len(sents) >= 4
        return {"ok": ok if ok else None, "why": "something turns in the scene" if ok else "a person should check that something changes between the scene's start and its end"}
    return {"ok": None, "why": "for a person to judge"}


def critique(text: str, bp: dict) -> dict:
    """a draft judged at all five layers against the blueprint it was planned from: {"passed", "layers": [{"layer", "ok",
    "checks": [{"check", "ok", "why"}]}], "revise": [what to fix, most serious first], "sections_failing": [...]}.
    ok None means the check is for a person (the plan keeps a human check at every layer)."""
    paras = paragraphs(text)
    body = [p for p in paras if len(sentences(p)) >= 2 and not re.match(r"^#{1,6}\s", p)]
    sents = [s for p in body for s in sentences(p)]
    words = WORD.findall(text)
    fiction = bool(bp.get("fiction"))
    layers: list[dict] = []
    # 1 sentence flow
    known = total = 0
    for p in body:
        f = framework(p)
        for t in f["sentences"][1:]:
            total += 1
            known += t.get("relation") in ("same", "linked", "member")
    share = known / total if total else 1.0
    lens = [len(WORD.findall(s)) for s in sents]
    longest = max(lens) if lens else 0
    avg = sum(lens) / len(lens) if lens else 0.0
    c1 = [{"check": "sentences open on something the reader already holds", "ok": share >= (0.4 if fiction else 0.6) if total else None,
           "why": "%d of %d sentences (%d%%)" % (known, total, round(100 * share)) if total else "too short to judge"},
          {"check": "sentence length", "ok": longest <= 45 and avg <= 28 if lens else None,
           "why": "average %d words, longest %d" % (round(avg), longest) + ("" if longest <= 45 and avg <= 28 else " — split the longest")}]
    layers.append({"layer": LAYERS[0], "checks": c1})
    # 2 paragraph pattern
    c2: list[dict] = []
    static = 0
    for i, p in enumerate(body):
        f = framework(p)
        # the critic flags a paragraph with NO pattern, or a static one; a chain with one loose link is ordinary prose
        if (not f["framework"] and f["of"] >= 2 and f["same"] + f["linked"] + f["members"] < (f["of"] + 1) // 2) or \
                (f["framework"] == "constant theme" and not f["check"]["ok"]):
            c2.append({"check": "paragraph %d" % (i + 1), "ok": False, "why": f["check"]["why"], "paragraph": i + 1})
        static += f["framework"] == "constant theme"
    if fiction and body and static > len(body) / 2:
        c2.append({"check": "movement", "ok": False, "why": "most paragraphs hold on one subject: long runs stall a story — let action lead to consequence"})
    if not c2:
        c2.append({"check": "each paragraph follows one pattern", "ok": True if body else None, "why": "%d paragraphs checked" % len(body)})
    layers.append({"layer": LAYERS[1], "checks": c2})
    # 3 document structure
    heads = [h.lower() for h in headings(text)]
    c3: list[dict] = []
    failing: list[str] = []
    at = -1
    order_ok = True
    headed = bool(bp.get("headed", True)) and not fiction
    for s in bp["sections"]:
        key = s["section"].lower()
        i = next((k for k, h in enumerate(heads) if key in h or h in key or overlap(content(key), content(h))), -1)
        if i < 0:
            if s["required"] and headed and key not in UNHEADED_SECTIONS:
                c3.append({"check": "section: " + s["section"], "ok": False, "why": "missing — it must %s" % s["move"]})
                failing.append(s["section"])
        else:
            if i < at:
                order_ok = False
            at = max(at, i)
    if fiction:
        c3.append({"check": "the scene changes something", "ok": None, "why": "for a person: does each scene end somewhere different from where it began?"})
    elif not headed:                                     # a news story or an abstract makes its moves without headings
        c3.append({"check": "the moves, in order", "ok": None, "why": "for a person: does it %s?" % "; then ".join(s["move"] for s in bp["sections"][:5])})
    else:
        if not order_ok:
            c3.append({"check": "order of sections", "ok": False, "why": "the sections are not in the blueprint's order"})
        if not any(c["ok"] is False for c in c3):
            c3.append({"check": "every required section is present, in order", "ok": True, "why": "%d sections" % len(bp["sections"])})
        pv = check_preview(text)
        if pv["previewed"]:
            c3.append({"check": "the preview is kept", "ok": pv["ok"], "why": pv["why"]})
    layers.append({"layer": LAYERS[2], "checks": c3})
    # 4 rhetorical situation
    r = bp["register"]
    lo, hi = r["words"]
    n = len(words)
    c4 = [{"check": "length", "ok": lo * 0.6 <= n <= hi * 1.4, "why": "%d words; this genre runs about %d to %d" % (n, lo, hi)}]
    fp, sp = len(FIRST_PERSON.findall(text)), len(SECOND_PERSON.findall(text))
    if r["person"] == "third" and not fiction:
        c4.append({"check": "person", "ok": fp == 0, "why": "written in the third person" if fp == 0 else "%d uses of I / we in a genre written in the third person" % fp})
    elif r["person"] == "second":
        c4.append({"check": "person", "ok": sp > 0, "why": "speaks to the reader as \"you\"" if sp else "this genre speaks to the reader directly (\"you\") and the draft never does"})
    hd = len(HEDGE.findall(text))
    if r.get("hedging") == "none" and sents:
        c4.append({"check": "hedging", "ok": hd <= max(1, len(sents) // 10), "why": "%d hedges in %d sentences" % (hd, len(sents))})
    if bp.get("style") and n >= STYLE_MIN_WORDS:
        sc = style_check(text, bp["style"])
        c4.append({"check": "style", "ok": sc["ok"], "why": sc["why"]})
    c4.append({"check": "pitched for the reader", "ok": None, "why": "for a person: would %s find it pitched correctly?" % bp["reader"]})
    layers.append({"layer": LAYERS[3], "checks": c4})
    # 5 domain convention: the genre's own failure modes, each a named check
    c5: list[dict] = []
    for fm in bp.get("failure_modes") or []:
        res = run_check(fm.get("check", ""), text, bp)
        c5.append({"check": fm["failure"], "ok": res["ok"], "why": res["why"]})
    for c in bp.get("constraints") or []:
        c5.append({"check": "hard constraint: " + c, "ok": None, "why": "for an expert to confirm before use"})
    if bp.get("field"):
        c5.append({"check": "the field's conventions (%s)" % bp["field"]["name"], "ok": None,
                   "why": "for a person: are sources cited in %s, and is the evidence of the kind the field accepts (%s)?" % (bp["field"]["citation"], bp["field"]["evidence"])})
    layers.append({"layer": LAYERS[4], "checks": c5})
    revise: list[str] = []
    for L in (layers[2], layers[4], layers[3], layers[1], layers[0]):          # structure first: a planning failure costs most
        L["ok"] = not any(c["ok"] is False for c in L["checks"])
        revise += ["%s — %s: %s" % (L["layer"], c["check"], c["why"]) for c in L["checks"] if c["ok"] is False]
    human = ["%s — %s" % (L["layer"], c["why"]) for L in layers for c in L["checks"] if c["ok"] is None]
    return {"passed": not revise, "layers": layers, "revise": revise, "sections_failing": failing, "for_a_person": human,
            "words": n, "paragraphs": len(body)}


def critique_text(c: dict) -> str:
    lines = ["The critic's reading: " + ("passes every automatic check at all five layers." if c["passed"] else "%d thing%s to fix." % (len(c["revise"]), "" if len(c["revise"]) == 1 else "s"))]
    for L in c["layers"]:
        lines.append("")
        lines.append("%s — %s" % (L["layer"].capitalize(), "passes" if L["ok"] else "to fix"))
        for ch in L["checks"]:
            lines.append("  %s %s: %s" % ("✔" if ch["ok"] else "•" if ch["ok"] is None else "✖", ch["check"], ch["why"]))
    return "\n".join(lines)


def explain(paragraph: str) -> str:
    """the grammar of one paragraph in plain words: each sentence's topic and comment, and the pattern they make"""
    f = framework(paragraph)
    lines = ["Pattern: %s — %s" % (f["framework"] or "none", f["check"]["why"])]
    for i, t in enumerate(f["sentences"]):
        rel = {"same": "same subject", "linked": "picks up the last sentence", "member": "a part of the whole", "": "new subject"}.get(t.get("relation", ""), "") if i else "opens the paragraph"
        lines.append("%d. [%s] %s%s  ⟶  %s" % (i + 1, rel, (t["frame"] + ", ") if t["frame"] else "", t["topic"], t["comment"] or "(no verb found)"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------- style: measured, then matched
# The user's decision: "adapt to user's style or apply a style template - based on a growing library of style templates."
# A style is held as NUMBERS measured from text, never as borrowed sentences: how long the sentences run and how much they
# vary, how often the writer says I or you, asks a question, contracts, hedges, reaches for a long word, uses a dash or a
# semicolon. A profile is measured from a sample; a template is a profile with a name. The drafter is told the targets in
# plain words; the critic measures the draft and says which habits are furthest off.
STYLE_FEATURES = ("sentence_words", "sentence_spread", "short_sentences", "long_sentences", "word_letters", "long_words", "first_person",
                  "second_person", "questions", "contractions", "hedges", "dashes", "semicolons", "paragraph_sentences")
STYLE_SCALE = {"sentence_words": 8.0, "sentence_spread": 6.0, "short_sentences": 0.2, "long_sentences": 0.2, "word_letters": 0.6, "long_words": 0.1,
               "first_person": 0.03, "second_person": 0.03, "questions": 0.1, "contractions": 0.03, "hedges": 0.02, "dashes": 0.3, "semicolons": 0.15,
               "paragraph_sentences": 3.0}
STYLE_SAY = {"sentence_words": "sentence length", "sentence_spread": "variety of sentence length", "short_sentences": "share of short sentences",
             "long_sentences": "share of long sentences", "word_letters": "word length", "long_words": "share of long words",
             "first_person": "use of I and we", "second_person": "use of you", "questions": "questions", "contractions": "contractions",
             "hedges": "hedging", "dashes": "dashes", "semicolons": "semicolons", "paragraph_sentences": "sentences to a paragraph"}
CONTRACTION = re.compile(r"\b\w+(?:n't|'re|'ve|'ll|'d|'m)\b|\b(?:it|that|there|he|she|what|who|let)'s\b", re.I)
STYLE_MIN_WORDS = 150


def style_profile(text: str) -> dict:
    """the measurable habits of a text: {"words", "enough": bool, feature: number ...}. Rates are per word or per sentence."""
    t = text.replace("’", "'")
    paras = [p for p in paragraphs(t) if not re.match(r"^#{1,6}\s", p)]
    sents = [s for p in paras for s in sentences(p)]
    words = [w for w in WORD.findall(t) if not w[0].isdigit()]
    n, ns = max(1, len(words)), max(1, len(sents))
    lens = [len(WORD.findall(s)) for s in sents] or [0]
    mean = sum(lens) / len(lens)
    spread = (sum((x - mean) ** 2 for x in lens) / len(lens)) ** 0.5
    return {"words": len(words), "enough": len(words) >= STYLE_MIN_WORDS,
            "sentence_words": round(mean, 1), "sentence_spread": round(spread, 1),
            "short_sentences": round(sum(1 for x in lens if x <= 8) / len(lens), 3), "long_sentences": round(sum(1 for x in lens if x >= 25) / len(lens), 3),
            "word_letters": round(sum(len(w) for w in words) / n, 2), "long_words": round(sum(1 for w in words if len(w) >= 9) / n, 3),
            "first_person": round(len(FIRST_PERSON.findall(t)) / n, 4), "second_person": round(len(SECOND_PERSON.findall(t)) / n, 4),
            "questions": round(sum(1 for s in sents if s.rstrip("\"'”)").endswith("?")) / ns, 3),
            "contractions": round(len(CONTRACTION.findall(t)) / n, 4), "hedges": round(len(HEDGE.findall(t)) / n, 4),
            "dashes": round(len(re.findall(r"\s[—–-]{1,2}\s|—", t)) / ns, 3), "semicolons": round(t.count(";") / ns, 3),
            "paragraph_sentences": round(len(sents) / max(1, len(paras)), 1)}


def style_distance(a: dict, b: dict) -> dict:
    """how far one profile is from another: {"distance": 0 = the same habits, about 1 = a different writer, "furthest":
    [(feature, a's value, b's value), ...]} — each habit weighed on its own scale"""
    gaps = sorted(((min(3.0, abs(float(a.get(f, 0)) - float(b.get(f, 0))) / STYLE_SCALE[f]), f) for f in STYLE_FEATURES), reverse=True)
    dist = (sum(g * g for g, _f in gaps) / len(gaps)) ** 0.5
    return {"distance": round(dist, 2), "furthest": [(f, a.get(f, 0), b.get(f, 0)) for g, f in gaps[:4] if g >= 0.75]}


def style_brief(style: dict) -> str:
    """a style's targets in plain words, for whoever drafts"""
    p = style["profile"]
    bits = ["Style — %s." % style["name"]]
    if style.get("about"):
        bits.append(style["about"])
    bits.append("Sentences average about %d words%s." % (round(p["sentence_words"]), ", and vary a good deal: mix short ones with long" if p["sentence_spread"] >= 9
                                                         else ", fairly even in length" if p["sentence_spread"] <= 5 else ""))
    if p["short_sentences"] >= 0.3:
        bits.append("Use short sentences often.")
    if p["long_sentences"] <= 0.05:
        bits.append("Avoid sentences over 25 words.")
    bits.append("Prefer %s words." % ("short, common" if p["word_letters"] <= 4.5 else "exact, even when long" if p["word_letters"] >= 5.2 else "plain"))
    bits.append("Say I or we freely." if p["first_person"] >= 0.02 else "Do not say I or we." if p["first_person"] <= 0.002 else "Say I or we sparingly.")
    if p["second_person"] >= 0.015:
        bits.append("Speak to the reader as you.")
    bits.append("Use contractions." if p["contractions"] >= 0.012 else "Do not use contractions." if p["contractions"] <= 0.002 else "Use few contractions.")
    if p["questions"] >= 0.08:
        bits.append("Ask the reader a question now and then.")
    if p["hedges"] <= 0.003:
        bits.append("State things without hedging.")
    if p["dashes"] >= 0.2:
        bits.append("Dashes are part of the voice.")
    bits.append("Paragraphs run about %d sentences." % max(1, round(p["paragraph_sentences"])))
    return " ".join(bits)


def style_check(text: str, style: dict) -> dict:
    """a draft measured against the style it was asked to follow"""
    d = style_distance(style_profile(text), style["profile"])
    ok = d["distance"] <= 1.0
    far = "; ".join("%s is %s (the style: %s)" % (STYLE_SAY[f], a, b) for f, a, b in d["furthest"])
    return {"ok": ok, "distance": d["distance"],
            "why": "close to “%s” (distance %s)" % (style["name"], d["distance"]) if ok else "not yet in “%s” (distance %s): %s" % (style["name"], d["distance"], far or "many small differences")}


# ---------------------------------------------------------------------------------------------- learning from a source, once
def page_text(html: str) -> str:
    """a web page as plain text: scripts, styles and tags removed"""
    t = re.sub(r"(?is)<(script|style|nav|footer|header|noscript)\b.*?</\1>", " ", html)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    for a, b in (("&amp;", "&"), ("&nbsp;", " "), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'"), ("&rsquo;", "'"), ("&ldquo;", '"'), ("&rdquo;", '"')):
        t = t.replace(a, b)
    return " ".join(t.split())


def copies(rule: str, page: str, run: int = 7) -> bool:
    """does a rule repeat a run of the page's own words? (rules are kept in QueryBook's words; a rule that copies is dropped)"""
    w = [x.lower() for x in WORD.findall(rule)]
    low = " ".join(x.lower() for x in WORD.findall(page))
    return any(" ".join(w[i:i + run]) in low for i in range(0, max(0, len(w) - run + 1)))


def keep_units(units: list[dict], page: str, genre_ids: list[str]) -> dict:
    """the rule units worth keeping from what was extracted: {"kept": [...], "dropped": [(rule, why), ...]}"""
    kept: list[dict] = []
    dropped: list[tuple[str, str]] = []
    for u in units:
        rule = " ".join(str(u.get("rule") or "").split())
        gid = str(u.get("genre") or "")
        if len(rule.split()) < 4:
            dropped.append((rule, "too short to be a rule"))
        elif gid not in genre_ids and gid != "any":
            dropped.append((rule, "names no known kind of document"))
        elif copies(rule, page):
            dropped.append((rule, "repeats the source's own words"))
        elif any(rule.lower() == k["rule"].lower() for k in kept):
            dropped.append((rule, "said twice"))
        else:
            layer = str(u.get("layer") or "")
            kept.append({"genre": gid, "layer": layer if layer in LAYERS else "", "section": " ".join(str(u.get("section") or "").split())[:60],
                         "rule": rule[:300], "reason": " ".join(str(u.get("reason") or "").split())[:300],
                         "failure": " ".join(str(u.get("failure") or "").split())[:200]})
    return {"kept": kept, "dropped": dropped}
