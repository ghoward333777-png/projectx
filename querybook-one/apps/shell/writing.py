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
    if bp["fiction"]:
        for v in FICTION_RULES:                              # the user's tips for stories bind whoever drafts
            lines.append("STORY: %s." % v)
    if bp.get("genre") in ESSAY_GENRES:
        for v in ESSAY_RULES:                                # the user's tips on structure for the reader
            lines.append("STRUCTURE: %s." % v)
    if not bp["fiction"]:
        for v in VOICE_RULES:                                # the user's VOICE guidelines bind whoever drafts
            lines.append("VOICE: %s." % v)
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


# ================================================================================================ VOICE
# The user's guidelines (2026-11-14, "Writing With AI Without Losing Your Voice"): five pitfalls of AI writing answered by
# five standards — Verified, Owned, Insightful, Clear, Engaging — with the person responsible for truth, perspective,
# meaning and the final decision. Here: the questions asked BEFORE drafting (the interview and the thesis), the rules a
# drafter is bound by, and a rule-based audit of a draft. The audit never calls a claim verified: only a person who has
# opened the source can. It finds what to look at and asks the questions; it rewrites nothing.
VOICE = ("verified", "owned", "insightful", "clear", "engaging")
VOICE_QUESTION = {
    "verified": "Is this real, accurate, current, properly attributed and supported by evidence?",
    "owned": "Could this have come from anyone, or does it carry this writer's own experience, judgment and evidence?",
    "insightful": "What does this help the reader see, understand or reconsider?",
    "clear": "Will the intended reader understand the meaning without having to guess?",
    "engaging": "Does each section create a reason to continue?"}
VOICE_PITFALL = {"verified": "confident inaccuracy", "owned": "the broken record (familiar patterns)", "insightful": "smart but empty",
                 "clear": "clarity lost in noise", "engaging": "predictable and boring"}
CLAIM_LABELS = ("verified", "unverified", "disputed", "outdated", "interpretive", "opinion")
INTERVIEW = (
    "What did you personally see?", "What did you do?", "What happened as a result?", "What did you believe at first?",
    "What changed your mind?", "What did you misunderstand?", "What do others usually miss?",
    "Which details do you still remember — a place, a number, a sentence someone said?", "What would you do differently now?",
    "Why does this matter to you?")
THESIS = ("Most people believe …", "I believe …", "My evidence is …", "The difference matters because …", "The strongest objection is …",
          "My claim is limited by …")
ASSIGNMENT = ("purpose", "intended reader", "desired outcome", "format and length", "evidence standard", "tone", "where it will be published",
              "what goes wrong if it is mistaken", "what you must contribute yourself")
VOICE_RULES = (
    "Use only the facts, experiences, quotations and sources supplied. Invent no personal experience, quotation, source, statistic, "
    "interview, credential or event",
    "Where a claim needs evidence that was not supplied, write the claim narrowly and mark the place [needs evidence: what is missing]",
    "Match each claim to its evidence: 'found' or 'suggests', not 'proves'; 'is associated with', not 'causes', unless causation is shown; "
    "no 'always', 'everyone' or 'the first' without support",
    "Keep the writer's own details, names, examples and wording; do not swap them for more familiar ones",
    "No stock openings, closings or filler: say the thing itself. Every claim that sounds deep must be stated in ordinary words, with an "
    "example or the reason it holds",
    "Name who does what. Prefer the verb to the abstract noun. Keep the technical terms the subject needs, and define them",
    "Every paragraph adds something new; none restates an earlier one. The ending delivers what the opening promised")
STOCK = ("in today's", "rapidly changing world", "ever-changing", "ever-evolving", "fast-paced world", "it is important to remember", "it is important to note",
         "it's important to note", "it is worth noting", "at the end of the day", "the key takeaway", "key takeaways", "in conclusion,", "when it comes to",
         "plays a crucial role", "plays a vital role", "a testament to", "delve into", "navigate the", "unlock the", "unlocking", "the landscape of",
         "landscape", "journey", "game changer", "game-changer", "tapestry", "in the realm of", "it goes without saying", "needless to say",
         "more than ever", "now more than ever", "not just", "not only", "let's dive in", "embark on", "harness the power", "the power of",
         "paradigm shift", "moving forward", "going forward", "look no further", "stands as a", "serves as a reminder")
JARGON = ("leverage", "utilize", "utilise", "synergy", "synergies", "stakeholder", "stakeholders", "paradigm", "holistic", "robust", "facilitate",
          "optimize", "optimise", "ecosystem", "scalable", "actionable", "impactful", "seamless", "seamlessly", "empower", "streamline", "operationalize",
          "strategic", "alignment", "aligned", "deliverables", "learnings", "bandwidth", "ideate", "incentivize", "in order to", "with regard to",
          "in terms of", "due to the fact that", "at this point in time", "a wide range of")
ABSTRACT_END = ("tion", "sion", "ment", "ness", "ity", "ance", "ence", "ship", "ism")
WEAK_VERB = re.compile(r"\b(is|are|was|were|has|have|had|provides?|enables?|involves?|represents?|constitutes?)\b", re.I)
GROUNDED = re.compile(r"\b(because|for example|for instance|such as|so that|which means|when|if|unless|therefore|after|before)\b|\d", re.I)
RESEARCH = re.compile(r"\b(research|stud(?:y|ies)|surveys?|data|experts?|scientists?|analysts?|reports?|evidence|statistics)\s+(?:shows?|suggests?|agrees?|"
                      r"finds?|found|says?|confirms?|proves?|indicates?|demonstrates?|reveals?)\b|\bit is (?:well )?known that\b|\bstudies have shown\b", re.I)
SUPERLATIVE = re.compile(r"\bthe (?:first|last|only)\b(?! (?:line|step|time|part|thing|place|page|paragraph|sentence|section|day|week|month|year|one|two|few)\b)|"
                         r"\bthe (?:largest|smallest|biggest|oldest|newest|best|worst|fastest|highest|lowest|leading|most \w+|least \w+)\b", re.I)
CAUSAL = re.compile(r"\b(causes?|caused|proves?|proved|proven|leads? to|led to|results? in|resulted in|guarantees?|ensures?|is responsible for)\b", re.I)
ABSOLUTE = re.compile(r"\b(always|never|everyone|everybody|no one|nobody|all (?:people|experts|studies)|every (?:one|time)|undeniabl[ey]|without (?:a )?doubt|"
                      r"certainly|definitely)\b", re.I)
QUOTED = re.compile(r"[“\"][^”\"]{12,}[”\"]")
NUMBER = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?:\s?%|\s?percent|\s?(?:million|billion|thousand))?")
YEAR4 = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
OPINION = re.compile(r"\b(i (?:think|believe|feel|suspect|doubt)|in my (?:view|opinion|experience)|should|ought to|must)\b", re.I)
COUNTER = re.compile(r"\b(however|but|yet|although|though|critics|objection|on the other hand|unless|except|not always|limit(?:s|ed|ation)?)\b", re.I)
CONTRAST = re.compile(r"\b(but|yet|however|although|instead|until|except)\b", re.I)


def abstract_count(sentence: str) -> int:
    """how many abstract nouns (by ending) a sentence carries — the cloud a simple idea gets lost in"""
    return sum(1 for w in WORD.findall(sentence.lower()) if len(w) > 6 and w.endswith(ABSTRACT_END))


def claims(text: str) -> list[dict]:
    """every sentence that makes a checkable claim: {"sentence", "kinds", "label", "todo"}. The label is one of CLAIM_LABELS and
    is never "verified": a claim with a citation is still unverified until a person has opened the source."""
    out: list[dict] = []
    for s in sentences(text):
        kinds: list[str] = []
        if QUOTED.search(s):
            kinds.append("quotation")
        if NUMBER.search(YEAR4.sub("", s)):
            kinds.append("number")
        if YEAR4.search(s):
            kinds.append("date")
        if RESEARCH.search(s):
            kinds.append("research or experts")
        if SUPERLATIVE.search(s):
            kinds.append("superlative")
        if CAUSAL.search(s):
            kinds.append("cause")
        if ABSOLUTE.search(s):
            kinds.append("absolute")
        if not kinds:
            continue
        cited = bool(CITATION.search(s) or ATTRIBUTION.search(s))
        if OPINION.search(s) and kinds in (["cause"], ["absolute"], ["superlative"]):
            label, todo = "opinion", "a judgment: say it is yours, or support it"
        elif FIRST_PERSON.search(s) and not cited and all(k in ("number", "date") for k in kinds):
            label, todo = "unverified", "your own account: only you can vouch for it — check it against your own records"
        elif kinds == ["cause"] or kinds == ["absolute"]:
            label, todo = "interpretive", "a conclusion, not a record: say what it rests on, or narrow it"
        else:
            label = "unverified"
            todo = ("a source is named: open it and check it exists, says this, and supports this wording" if cited
                    else "no source is given: find the strongest one (the original record first), or cut or narrow the claim")
        out.append({"sentence": s, "kinds": kinds, "label": label, "cited": cited, "todo": todo})
    return out


def own_details(own: str) -> list[str]:
    """the particular things in the writer's own material: names, numbers and their rarer words"""
    seen: list[str] = []
    for m in re.finditer(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\b|\d+(?:[.,]\d+)*", own):
        w = m.group(0)
        if w.lower() not in STOP and w not in seen:
            seen.append(w)
    return seen[:60]


def voice_audit(text: str, own: str) -> dict:
    """a draft read against the five standards. `own` is the writer's own material (brief, notes, answers to the interview) or "".
    Returns {"parts": [{"standard", "question", "pitfall", "ok", "found": [...], "ask": [...]}], "for_the_writer": [...], "claims"}.
    Rule-based: it points and asks. It never says a claim is true and never rewrites."""
    sents, paras = sentences(text), paragraphs(text)
    low = text.lower().replace("’", "'")
    parts: list[dict] = []
    # ---- Verified
    cl = claims(text)
    unver = [c for c in cl if c["label"] == "unverified"]
    found = ["%s — %s: “%s”" % (", ".join(c["kinds"]), c["todo"], c["sentence"][:160]) for c in cl[:14]]
    if len(cl) > 14:
        found.append("… and %d more claims to check" % (len(cl) - 14))
    parts.append({"standard": "verified", "ok": not cl, "found": found,
                  "ask": ["Have you opened each source yourself?", "Does each source support the whole claim, in these words?",
                          "Is anything out of date, or disputed by another credible source?"] if cl else []})
    # ---- Owned
    stock = [p for p in STOCK if p in low]
    found = ["stock phrase: “%s”" % p for p in stock[:10]]
    details = own_details(own)
    kept = [d for d in details if d.lower() in low]
    if details:
        found.append("%d of your %d own details (names, numbers) appear in the draft%s" % (
            len(kept), len(details), "" if kept else " — it could have been written without you"))
        lost = [d for d in details if d.lower() not in low][:8]
        if lost and len(kept) < len(details):
            found.append("of yours, not in the draft: " + ", ".join(lost))
    elif not FIRST_PERSON.search(text) and not any(re.search(r"\b[A-Z][a-z]+\b", s[1:]) or re.search(r"\d", s) for s in sents):
        found.append("no name, number or first-hand detail anywhere: nothing here could only have come from this writer")
    owned_ok = not stock and (not details or len(kept) * 2 >= len(details)) and not (found and not details)
    parts.append({"standard": "owned", "ok": owned_ok, "found": found,
                  "ask": [] if owned_ok else ["Which detail, example or wording of your own belongs here?", "Does it sound like you when read aloud?",
                                              "Did a familiar example replace one of yours?"]})
    # ---- Insightful
    empty = [s for s in sents if len(WORD.findall(s)) >= 8 and abstract_count(s) >= 3 and not GROUNDED.search(s)
             and not re.search(r"\b[A-Z][a-z]+\b", s[1:])]
    found = ["sounds deep, says what? “%s”" % s[:170] for s in empty[:8]]
    has_claim = any(re.search(r"\b(because|therefore|so|which is why|this means)\b", s, re.I) for s in sents)
    if len(sents) >= 6 and not has_claim:
        found.append("no sentence gives a reason (because, therefore, this means): a subject is described, but no claim is argued")
    if len(sents) >= 10 and not COUNTER.search(text):
        found.append("no objection, exception or limit is mentioned")
    parts.append({"standard": "insightful", "ok": not found, "found": found,
                  "ask": ["What does it mean in ordinary words?", "What particular case shows it?", "What causes it?", "When would it not be true?",
                          "What should the reader do differently — so what?"] if found else []})
    # ---- Clear
    found = []
    for s in sents:
        n = len(WORD.findall(s))
        if n > 35:
            found.append("%d words in one sentence: “%s…”" % (n, s[:110]))
        elif abstract_count(s) >= 3 and WEAK_VERB.search(s):
            found.append("abstract nouns on a weak verb — who does what? “%s”" % s[:150])
    jar = [j for j in JARGON if re.search(r"\b%s\b" % re.escape(j), low)]
    if jar:
        found.append("words that sound official: " + ", ".join(jar[:12]) + " — keep only the terms the subject needs, and define those")
    parts.append({"standard": "clear", "ok": not found, "found": found[:12],
                  "ask": ["What is the shortest accurate version?", "Who acts, and what do they do?", "What is the reader asked to do?"] if found else []})
    # ---- Engaging
    found = []
    cps = [set(content(p)) for p in paras]
    for i in range(1, len(cps)):
        for j in range(i):
            if len(cps[i]) >= 6 and len(cps[i] & cps[j]) * 10 >= len(cps[i]) * 7:
                found.append("paragraph %d says again what paragraph %d said" % (i + 1, j + 1))
                break
    firsts = [WORD.findall(s.lower())[:1] for s in sents]
    for i in range(len(firsts) - 2):
        if firsts[i] and firsts[i] == firsts[i + 1] == firsts[i + 2]:
            found.append("three sentences in a row open with “%s”" % firsts[i][0])
            break
    if paras and len(sents) >= 5:
        first = paras[0]
        if not ("?" in first or re.search(r"\d", first) or CONTRAST.search(first) or re.search(r"\b[A-Z][a-z]+\b", first[1:])):
            found.append("the opening has no question, no particular person or number and no tension: nothing is left open for the reader")
        if len(paras) >= 3 and len(cps[0]) >= 4 and not (cps[0] & cps[-1]):
            found.append("the ending shares nothing with the opening: was the opening's promise kept?")
    parts.append({"standard": "engaging", "ok": not found, "found": found[:10],
                  "ask": ["Does the reader need the next line?", "What is at stake, and for whom?", "Can this paragraph go without loss?"] if found else []})
    for p in parts:
        p["question"], p["pitfall"] = VOICE_QUESTION[p["standard"]], VOICE_PITFALL[p["standard"]]
    writer = ["Truth: am I prepared to stand behind every claim? Did I open the sources myself?",
              "Fairness and privacy: are people and sources represented fairly, and is anything private protected?",
              "Meaning: is this what I think, or only what sounds right?",
              "Decision: the final editorial choices are mine."]
    return {"parts": parts, "claims": cl, "unverified": len(unver), "passed": all(p["ok"] for p in parts), "for_the_writer": writer}


def voice_text(a: dict) -> str:
    lines = ["VOICE — %s" % ("nothing found by the rules; the four questions at the end are still yours."
                             if a["passed"] else "things to look at, by standard. Nothing is rewritten; a rule can point, only you can decide.")]
    for p in a["parts"]:
        lines.append("")
        lines.append("%s — %s" % (p["standard"].upper(), p["question"]))
        if not p["found"]:
            lines.append("  ✔ nothing found by the rules")
        for f in p["found"]:
            lines.append("  • " + f)
        for q in p["ask"]:
            lines.append("  ? " + q)
    lines.append("")
    lines.append("FOR YOU, NOT A MACHINE")
    lines += ["  □ " + w for w in a["for_the_writer"]]
    return "\n".join(lines)


def voice_interview(brief: str) -> dict:
    """what the writer is asked before a word is drafted: what the assignment leaves unsaid, the interview, the thesis to complete"""
    low = brief.lower()
    said = {"intended reader": ("for ", "audience", "reader"), "format and length": ("word", "page", "short", "long", "brief"),
            "tone": ("tone", "formal", "informal", "warm", "plain", "friendly"), "purpose": (" to ", "so that", "why", "explain", "persuade", "ask")}
    missing = [k for k in ASSIGNMENT if k in said and not any(w in low for w in said[k])]
    return {"missing": missing, "interview": list(INTERVIEW), "thesis": list(THESIS)}


def interview_text(iv: dict) -> str:
    lines = ["BEFORE IT IS WRITTEN — your own material", "The draft can only be yours if it starts from what you know. Answer what applies, in a few words each:"]
    lines += ["  %d. %s" % (i + 1, q) for i, q in enumerate(iv["interview"])]
    lines.append("Your claim (complete what you can):")
    lines += ["  " + t for t in iv["thesis"]]
    if iv["missing"]:
        lines.append("The brief does not say: " + ", ".join(iv["missing"]) + ".")
    return "\n".join(lines)


# ================================================================================================ fiction habits
# The user's tips for stories (2026-11-14, from their notes on a talk about common habits in manuscripts; in QueryBook's words).
# VOICE is for non-fiction; a story is read for these instead. Rules point and ask; the decisions are made in the edit, by the writer.
FICTION_RULES = (
    "Dialogue: people talk messily — contractions, fragments, interruptions, things left unsaid. No one explains their feelings in full, tidy sentences",
    "Point of view: one scene, one head. Stay inside one character's thoughts until the scene breaks",
    "Stakes: say exactly what this person stands to lose — a person, a place, a promise — never 'everything'",
    "Pacing: match sentence length to the heat of the moment — short when it is tense, longer when it settles",
    "Opening: start where the trouble starts, not with waking up or a routine",
    "Description: trust nouns and verbs; one chosen detail, not a stack of adjectives; break paragraphs and leave white space",
    # the unfinished holds the reader (the user's second set of tips, 2026-11-14): what is left open is remembered
    "A coming event: lead the story toward one particular event the reader can see coming, with a clock on it",
    "Chapter endings: end each chapter or scene on something open — a question, a threat, a decision not yet made — never on tidy rest",
    "Planted things: bring in early the object, secret or fear that will matter later, and pay each one off")
FICTION_HABITS = ("dialogue", "point of view", "stakes", "pacing", "opening", "overwriting", "coming event", "chapter endings", "planted things")
CLOCK = re.compile(r"(by (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|morning|noon|midnight|nightfall|dawn|tomorrow|the end of)|"
                   r"until|before the|in (?:two|three|four|five|six|seven|ten|\d+) (?:days|hours|weeks|minutes|months)|tomorrow|tonight|deadline|"
                   r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|the (?:wedding|trial|election|funeral|hearing|race|final|auction|launch|"
                   r"opening|exam|vote|duel|storm|eclipse|festival|verdict)|days? (?:left|away)|hours? (?:left|away)|countdown|when the)\b", re.I)
FLAT_END = re.compile(r"\b(fell asleep|went to (?:bed|sleep)|drifted off|slept|went home|all was well|at peace|everything was (?:fine|all right|okay)|"
                      r"smiled(?: to (?:himself|herself|themselves))?|sighed contentedly|and that was that|the day was over|turned off the light|"
                      r"safe at last|nothing more to (?:say|do)|happily)\b[^.!?]*[.!?”\"]*\s*$", re.I)
OPEN_END = re.compile(r"\?[”\"]?\s*$|—[”\"]?\s*$|\b(but|until|unless|if|not yet|still|then (?:he|she|they|it) (?:saw|heard|knew)|someone|something|gone|"
                      r"wrong|too late|never|no one|knock|door|phone|blood|missing|friday|tomorrow)\b[^.!?]*[.!?”\"]*\s*$", re.I)
SPOKEN = re.compile(r"[“\"]([^”\"]{2,})[”\"]")
UNCONTRACTED = re.compile(r"\b(do not|does not|did not|cannot|can not|will not|would not|could not|should not|is not|are not|was not|were not|have not|has not|"
                          r"i am|i will|i have|i would|you are|you will|you have|we are|we will|they are|it is|that is|there is|let us)\b", re.I)
THERAPY = re.compile(r"\b(i feel (?:that|like|as)|it makes me feel|i hear (?:you|what)|i understand (?:that|how|why) you|i need you to (?:understand|know)|"
                     r"i want you to know|what i(?:'m| am) trying to say|i appreciate (?:that|you|your)|thank you for sharing|i(?:'m| am) sorry (?:that )?you feel|"
                     r"my feelings|your feelings|communicat\w+|boundar(?:y|ies)|process(?:ing)? (?:this|my|your))\b", re.I)
MESSY = re.compile(r"—|–|\.\.\.|…|-\s*$|\b(uh|um|er|hm+|well|look|listen|wait|no|yeah|nah|okay|ok)\b", re.I)
THOUGHT = re.compile(r"\b([A-Z][a-z]+) (?:thought|wondered|felt|knew|realized|realised|remembered|hoped|feared|wished|decided|suspected|supposed|doubted|"
                     r"believed|imagined|worried|sensed)\b")
NOT_NAMES = frozenset("He She They It We You I The But And Then When Nobody Everyone Someone No Each".split())
VAGUE_STAKES = re.compile(r"\b(everything (?:would|will|could|might) be lost|los[et] everything|all (?:would|will) be lost|everything (?:was|is) at stake|"
                          r"the fate of the (?:world|universe|kingdom)|nothing would ever be the same|the end of everything|everything (?:would|will) change|"
                          r"(?:it|all) would be over|too much (?:was|is) at stake|the stakes (?:were|are|had never been) (?:high|higher))\b", re.I)
ROUTINE = ("woke", "awoke", "alarm", "yawned", "stretched", "shower", "brushed", "toothbrush", "breakfast", "coffee", "dressed", "mirror", "snooze",
           "sunlight", "curtains", "pillow", "blinked", "rubbed")
SCENE_BREAK = re.compile(r"^\s*(?:\*\s*\*\s*\*|#{1,3}\s.*|—{3,}|-{3,}|\*{3,})\s*$", re.M)
ADJ_END = ("ous", "ful", "less", "ive", "ish", "ent", "ant", "ic", "al", "ary", "en")
ADJ_STACK = re.compile(r"\b(\w{4,}), (\w{4,})(?:,? and \w{4,}|, \w{4,})? (\w+)\b")


def scenes(text: str) -> list[str]:
    return [s.strip() for s in SCENE_BREAK.split(text) if s.strip()]


def fiction_audit(text: str) -> dict:
    """a story read for six common habits: {"parts": [{"habit", "rule", "ok", "found": [...], "ask": [...]}], "passed"}.
    Rule-based: it can count and point, not judge a scene. Nothing is rewritten."""
    sents, paras, words = sentences(text), paragraphs(text), WORD.findall(text)
    parts: list[dict] = []
    # ---- dialogue too formal
    lines = [m.group(1) for m in SPOKEN.finditer(text) if len(WORD.findall(m.group(1))) >= 2]
    found: list[str] = []
    if len(lines) >= 3:
        stiff = [l for l in lines if UNCONTRACTED.search(l)]
        if len(stiff) * 2 >= len(lines):
            found.append("%d of %d spoken lines avoid contractions (“%s”) — people say “don't”, “I'm”" % (len(stiff), len(lines), stiff[0][:70]))
        therapy = [l for l in lines if THERAPY.search(l)]
        for l in therapy[:3]:
            found.append("explains feelings like a counselling session: “%s”" % l[:110])
        every = [m.group(1) for m in SPOKEN.finditer(text)]
        if not any(MESSY.search(l) or len(WORD.findall(l)) <= 3 for l in every):
            found.append("no one interrupts, trails off or hesitates in %d spoken lines" % len(lines))
        long_ = [l for l in lines if len(WORD.findall(l)) > 30]
        if len(long_) * 3 >= len(lines):
            found.append("%d spoken lines run past 30 words: speeches, not talk" % len(long_))
    parts.append({"habit": "dialogue", "found": found, "ask": ["What would they really say — and what would they not say?", "Who cuts in?"] if found else []})
    # ---- point of view drift
    found = []
    for n, sc in enumerate(scenes(text)):
        heads: list[str] = []
        for m in THOUGHT.finditer(sc):
            if m.group(1) not in NOT_NAMES and m.group(1) not in heads:
                heads.append(m.group(1))
        if len(heads) >= 2:
            found.append("scene %d is inside %s — one scene, one head" % (n + 1, " and ".join(heads[:4])))
    parts.append({"habit": "point of view", "found": found, "ask": ["Whose scene is this?", "How would that one person see what the other is feeling?"] if found else []})
    # ---- stakes that never land
    found = ["vague stakes: “%s”" % m.group(0) for m in list(VAGUE_STAKES.finditer(text))[:5]]
    parts.append({"habit": "stakes", "found": found, "ask": ["What exactly does this person lose — who, what, by when?", "What does it cost them, personally?"] if found else []})
    # ---- pacing plateau
    found = []
    lens = [len(WORD.findall(s)) for s in sents]
    if len(lens) >= 12:
        mean = sum(lens) / len(lens)
        spread = (sum((x - mean) ** 2 for x in lens) / len(lens)) ** 0.5
        if spread < 0.3 * mean or (max(lens) - min(lens)) <= 8:
            found.append("the sentences are all about %d words (shortest %d, longest %d): one speed from start to end" % (round(mean), min(lens), max(lens)))
    parts.append({"habit": "pacing", "found": found, "ask": ["Where is the scene hottest? Are the sentences shortest there?"] if found else []})
    # ---- starts too early
    found = []
    head = " ".join(words[:150]).lower()
    hits = [w for w in ROUTINE if re.search(r"\b%s\b" % w, head)]
    if len(hits) >= 2 and not SPOKEN.search(text[:160]):
        found.append("the first page is a routine (%s): the story has not started yet" % ", ".join(hits[:5]))
    parts.append({"habit": "opening", "found": found, "ask": ["Where does the trouble begin? Can the story open on that line?"] if found else []})
    # ---- overwritten
    found = []
    ly = [w for w in words if len(w) > 4 and w.lower().endswith("ly") and w.lower() not in ("only", "early", "family", "really", "reply", "supply", "apply", "belly", "holly")]
    if len(words) >= 80 and len(ly) * 100 > len(words) * 4:
        found.append("%d “-ly” words in %d (%s …): let the verb carry it" % (len(ly), len(words), ", ".join(ly[:5])))
    stacks = [m.group(0) for m in ADJ_STACK.finditer(text) if m.group(1).lower().endswith(ADJ_END) or m.group(2).lower().endswith(ADJ_END)]
    for s_ in stacks[:3]:
        found.append("stacked description: “%s” — choose the one detail that matters" % s_)
    big = [p for p in paras if len(WORD.findall(p)) > 170]
    if big:
        found.append("%d paragraph%s over 170 words with no break: give the page some white space" % (len(big), "" if len(big) == 1 else "s"))
    parts.append({"habit": "overwriting", "found": found, "ask": ["Which noun and verb do the work here?", "What can go without the reader missing it?"] if found else []})
    # ---- a coming event with a clock on it
    found = []
    if len(words) >= 250 and not CLOCK.search(text):
        found.append("nothing is coming: no day, deadline or named event the story is heading for in %d words" % len(words))
    parts.append({"habit": "coming event", "found": found, "ask": ["What is the one event everything leads to?", "When is it — and does the reader know?"] if found else []})
    # ---- chapter and scene endings
    found = []
    scs = scenes(text)
    for n, sc in enumerate(scs):
        ss = sentences(sc)
        if len(ss) < 3:
            continue
        last = ss[-1]
        if FLAT_END.search(last) and not OPEN_END.search(last.replace("smiled", "")):
            found.append("%s %d ends at rest: “%s”" % ("scene" if len(scs) > 1 else "the piece", n + 1, last[-110:]))
    parts.append({"habit": "chapter endings", "found": found[:5], "ask": ["What is still open when the chapter stops?", "Could it end one beat earlier?"] if found else []})
    # ---- planted things: rules cannot see a payoff across a book; the questions are the writer's
    parts.append({"habit": "planted things", "found": [], "ask": []})
    for p, rule in zip(parts, FICTION_RULES):
        p["rule"], p["ok"] = rule, not p["found"]
    return {"parts": parts, "passed": all(p["ok"] for p in parts),
            "for_the_writer": ["Planted things: which object, secret or fear appears early — and where is each one paid off? (Rules cannot follow a thread across a book.)"]}


def fiction_text(a: dict) -> str:
    lines = ["STORY CHECK — six common habits. " + ("None found by the rules." if a["passed"] else "These are habits of good writers too; the fix is made in the edit, by you.")]
    for p in a["parts"]:
        lines.append("")
        lines.append("%s — %s." % (p["habit"].upper(), p["rule"]))
        if not p["found"]:
            lines.append("  ✔ nothing found by the rules")
        for f in p["found"]:
            lines.append("  • " + f)
        for q in p["ask"]:
            lines.append("  ? " + q)
    lines.append("")
    lines.append("FOR YOU, NOT A MACHINE")
    lines += ["  □ " + w for w in a.get("for_the_writer", [])]
    return "\n".join(lines)


# ================================================================================================ essay structure for the reader
# The user's tips (2026-11-14, from their notes on a talk about structuring an essay around the reader's needs; QueryBook's words).
# Five elements: a title that builds curiosity, an introduction that poses a problem, index-and-discussion at every level,
# a constellation of key terms, and a conclusion that returns to the problem and widens it.
ESSAY_GENRES = ("essay", "critique", "explainer", "feature", "nonfiction-chapter", "research-paper", "literature-review")
ESSAY_RULES = (
    "Title: build curiosity — pose a question, promise something not widely known, or go against what is expected; no private joke, nothing cryptic",
    "Introduction: do not go from general to specific or from background to thesis. Pose a problem the reader has or should have, and set your idea as its answer",
    "Index and discussion, at every level: the first one to three sentences of the essay, of each section and of each paragraph say how to read what follows; "
    "the rest develops it",
    "Key terms: carry a small set of terms (and their near-synonyms) from the introduction through every part, so the pieces are felt to belong together",
    "Conclusion: do not merely summarise. Return to the problem from the introduction and show what the answer changes or adds to the wider conversation")
ESSAY_ELEMENTS = ("title", "introduction", "index and discussion", "key terms", "conclusion")
SCHOOL_OPENING = re.compile(r"\b(since the dawn of|throughout (?:human )?history|from the beginning of time|in today's society|in the modern world|"
                            r"dictionary defines|in this essay,? i will|this essay will|for centuries|many people (?:think|believe|say)|it is often said)\b", re.I)
PROBLEM = re.compile(r"\?|\b(but|yet|however|problem|puzzle|question|why|fail\w*|wrong|missing|despite|although|mistake\w*|trouble|gap|struggle\w*|"
                     r"paradox|surpris\w+|contradict\w+|nobody|no one|cannot|can't|hard to|difficult)\b", re.I)
CURIOUS = re.compile(r"\?|\d|^(?:how|why|what|when|who|where)\b|\b(secret|hidden|myth|wrong|mistake|never|nobody|without|versus|vs|against|untold|real|"
                     r"really|actually|not|isn't|doesn't|won't|truth|lie|unexpected|surprising|case for|case against|problem with|end of|death of)\b", re.I)
SUMMARY_ONLY = re.compile(r"^\s*(in conclusion|to conclude|to sum up|in summary|to summari[sz]e|in closing|all in all|overall,|as (?:shown|discussed|stated) above)\b", re.I)
SO_WHAT = re.compile(r"\b(so|therefore|means|matters?|should|must|next|beyond|larger|broader|wider|changes?|changed|question|if we|the lesson|suggests|implies|"
                     r"otherwise|until|no longer)\b", re.I)


def title_of(text: str) -> tuple[str, str]:
    """(title, the rest): the first line when it is short and is not a sentence, or a '# ' heading; else ("", text)"""
    lines = text.strip().split("\n")
    first = lines[0].strip() if lines else ""
    bare = first.lstrip("# ").strip()
    if first and (first.startswith("#") or (len(WORD.findall(bare)) <= 16 and not bare.endswith((".", ",", ";")) and len(lines) > 1)):
        return bare, "\n".join(lines[1:]).strip()
    return "", text.strip()


def essay_audit(text: str) -> dict:
    """an essay read for the five structural elements: {"parts": [{"element", "rule", "ok", "found", "ask"}], "terms", "passed"}"""
    title, body = title_of(text)
    paras = [p for p in paragraphs(body) if not p.lstrip().startswith("#")]
    parts: list[dict] = []
    stems = [set(content(p)) for p in paras]
    allwords = [w for p in paras for w in content(p)]
    # ---- title
    found: list[str] = []
    if not title:
        found.append("no title found on the first line")
    else:
        tw = set(content(title))
        if len(WORD.findall(title)) <= 2:
            found.append("“%s” is a label, not a reason to read" % title)
        elif tw and not (tw & set(allwords)):
            found.append("no word of “%s” comes back in the essay: a private reference?" % title)
        if not CURIOUS.search(title):
            found.append("the title asks nothing, promises nothing unknown and crosses no expectation")
    parts.append({"element": "title", "found": found, "ask": ["What would make a stranger want the answer?"] if found else []})
    # ---- introduction
    found = []
    intro = paras[0] if paras else ""
    if intro:
        m = SCHOOL_OPENING.search(intro)
        if m:
            found.append("opens the way school taught (“%s …”): general first, the point later" % m.group(0))
        if not PROBLEM.search(intro):
            found.append("poses no problem: nothing is wrong, missing or puzzling yet, so there is nothing for your idea to solve")
    parts.append({"element": "introduction", "found": found, "ask": ["What problem does the reader have — or not yet know they have?",
                                                                     "How is your idea the answer to it?"] if found else []})
    # ---- index and discussion
    found = []
    for n, p in enumerate(paras):
        ss = sentences(p)
        if len(ss) < 4:
            continue
        index = set(content(" ".join(ss[:2])))
        later = ss[2:]
        tied = sum(1 for s in later if index & set(content(s)))
        if tied * 10 < len(later) * 4:
            found.append("paragraph %d: its first sentences do not set up what follows (%d of %d later sentences pick up none of their words)" % (n + 1, len(later) - tied, len(later)))
    parts.append({"element": "index and discussion", "found": found[:6], "ask": ["What must the reader know first to read this part the right way?"] if found else []})
    # ---- key terms
    found = []
    seed = [w for w in content(title + " " + intro)]
    counts: dict[str, int] = {}
    for w in allwords:
        counts[w] = counts.get(w, 0) + 1
    terms = sorted({w for w in seed if counts.get(w, 0) >= 2 and len(w) > 3}, key=lambda w: (-counts[w], w))[:6]
    if len(paras) >= 4:
        if not terms:
            found.append("no term from the title or introduction returns later: nothing ties the parts together")
        else:
            loose = [n + 1 for n, st in enumerate(stems) if n and not (st & set(terms))]
            if len(loose) * 10 > (len(paras) - 1) * 4:
                found.append("paragraphs %s carry none of the essay's key terms (%s)" % (", ".join(map(str, loose[:8])), ", ".join(terms)))
    parts.append({"element": "key terms", "found": found, "ask": ["Which three or four terms are this essay's own? Do they recur, in the same words?"] if found else []})
    # ---- conclusion
    found = []
    if len(paras) >= 3:
        end = paras[-1]
        if SUMMARY_ONLY.search(end):
            found.append("the ending announces a summary (“%s …”)" % SUMMARY_ONLY.search(end).group(0).strip())
        if stems[0] and not (stems[0] & stems[-1]):
            found.append("the ending does not return to the problem the introduction posed")
        if not SO_WHAT.search(end):
            found.append("the ending restates; it does not say what the answer changes or where it leads")
    parts.append({"element": "conclusion", "found": found, "ask": ["What does the reader now see differently?", "What larger conversation does this join?"] if found else []})
    for p, rule in zip(parts, ESSAY_RULES):
        p["rule"], p["ok"] = rule, not p["found"]
    return {"parts": parts, "terms": terms, "title": title, "passed": all(p["ok"] for p in parts)}


def essay_text(a: dict) -> str:
    lines = ["STRUCTURE FOR THE READER — five elements. " + ("All five are in place, as far as rules can see." if a["passed"] else "What to look at:")]
    for p in a["parts"]:
        lines.append("")
        lines.append("%s — %s." % (p["element"].upper(), p["rule"]))
        if not p["found"]:
            lines.append("  ✔ nothing found by the rules")
        for f in p["found"]:
            lines.append("  • " + f)
        for q in p["ask"]:
            lines.append("  ? " + q)
    if a["terms"]:
        lines.append("")
        lines.append("The essay's key terms, as the rules see them: " + ", ".join(a["terms"]) + ".")
    return "\n".join(lines)


# ================================================================================================ the universal document types
# The user's taxonomy (2026-11-14; tools/doctypes_source.txt -> doctypes.json): 45 domains, their families and types, the parts each
# type is expected to have, and the purposes a document can serve. The person is ASKED for the type before anything is planned,
# written or judged. A type QueryBook holds a full record for uses that record; any other type is planned from the list's own parts.
def load_doctypes(raw: str) -> dict:
    """doctypes.json -> {"domains": [...], "purposes": [...], "types": {id: type + its domain, family and caution}}"""
    d = json.loads(raw)
    types: dict[str, dict] = {}
    for dom in d["domains"]:
        for fam in dom["families"]:
            for t in fam["types"]:
                types[t["id"]] = dict(t, domain=dom["name"], domain_n=dom["n"], family=fam["name"], caution=dom.get("caution", ""))
    return {"domains": d["domains"], "purposes": d["purposes"], "types": types}


GENERAL_SHAPE = (("Opening", "say what this document is and what it is for"), ("Body", "give what the reader needs, the most important first"),
                 ("Close", "say what happens next, or what is asked of the reader"))
CREATIVE_DOMAINS = (42,)


def genre_from_type(t: dict) -> dict:
    """a document type of the taxonomy as a record the planner and the critic can use: its sections are the parts the list
    expects, in the list's order. Where the list gives no parts, a general shape is used and said to be general."""
    els = [str(e) for e in t.get("elements") or []]
    secs = [{"name": e[:1].upper() + e[1:], "move": "give the " + e.lower(), "required": True} for e in els] or \
           [{"name": n, "move": m, "required": True} for n, m in GENERAL_SHAPE]
    fiction = int(t.get("domain_n") or 0) in CREATIVE_DOMAINS
    status = ("type from the document-type list with the list's own parts" if els and not t.get("from_group") else
              "type from the document-type list, with the parts the list gives for its group" if els else
              "type from the document-type list, which gives it no parts: a general shape is used") + "; no source has been learned for it yet"
    return {"id": t["id"], "name": t["name"].lower(), "also": [], "family": "fiction" if fiction else "doctype",
            "purpose": "serve as %s (%s)" % (a_an(t["name"].lower()), t.get("domain", "")), "reader": "the reader this kind of document is written for",
            "headed": not fiction, "frameworks": {"document": "index", "section": "index", "paragraph": "index"}, "sections": secs,
            "register": {"person": "any", "tense": "any", "formality": "any", "hedging": "some", "words": [0, 10 ** 9]},
            "evidence": "only what the brief, the writer's own material and the supplied facts give",
            "constraints": ["say plainly that this is " + t["caution"]] if t.get("caution") else [], "failures": [],
            "provenance": {"status": status, "sources": [], "variants": []}}


# ================================================================================================ analysis and the writer's controls
# The user (2026-11-14): the engine is for ANALYSIS and GENERATION alike — find the type, goal, voice and tone of an existing
# document, and apply a chosen type, goal, voice and tone to a new one. "Every aspect of writing must be placed at the control of
# the user — so that the resulting text reads like human writing and not generic AI writing."
# What is read from a text is measured or matched by rule and labelled "likely"; where the rules cannot tell, it says so.
TONES = {
    "warm": ("thank", "thanks", "grateful", "glad", "happy", "welcome", "kind", "care", "wish", "hope", "pleased", "dear", "appreciate", "love"),
    "urgent": ("now", "immediately", "urgent", "today", "deadline", "at once", "asap", "must", "act", "last chance", "before it"),
    "confident": ("will", "certainly", "clearly", "proven", "sure", "definitely", "always", "never", "no doubt", "without question"),
    "cautious": ("may", "might", "could", "perhaps", "possibly", "appears", "seems", "suggests", "likely", "uncertain", "however"),
    "critical": ("fails", "failed", "wrong", "poor", "weak", "mistake", "flawed", "problem", "lacks", "ignores", "worse", "bad"),
    "optimistic": ("opportunity", "growth", "improve", "better", "progress", "promise", "bright", "success", "gain", "forward", "can"),
    "sombre": ("loss", "death", "died", "grief", "sorrow", "regret", "sadly", "mourn", "tragic", "suffer", "pain"),
    "playful": ("fun", "silly", "joke", "laugh", "oops", "wow", "hey", "guess what", "funny", "yay"),
    "respectful": ("please", "kindly", "respectfully", "sir", "madam", "honour", "honor", "would you", "may i", "sincerely"),
    "instructive": ("first", "then", "next", "step", "make sure", "do not", "remember to", "check", "follow", "use"),
    "persuasive": ("should", "imagine", "why not", "you deserve", "join", "because", "the reason", "consider", "need"),
    "neutral": ()}
PURPOSE_CUES = {
    "Instruct": ("step", "first", "then", "next", "make sure", "do not", "press", "click", "install"),
    "Persuade": ("should", "must", "join", "buy", "support", "vote", "imagine", "why not", "act now"),
    "Argue": ("because", "therefore", "however", "argue", "claim", "evidence", "objection", "thus"),
    "Analyze": ("analysis", "data", "trend", "factor", "compared", "percent", "finding", "findings", "pattern", "correlation", "correlated"),
    "Compare": ("whereas", "compared with", "in contrast", "both", "similar", "differ", "versus", "than"),
    "Recommend": ("recommend", "we advise", "should adopt", "best option", "suggest", "proposal"),
    "Request": ("please", "request", "could you", "would you", "i am writing to ask", "kindly", "apply"),
    "Record": ("minutes", "attended", "resolved", "recorded", "on the date", "hereby", "noted"),
    "Contract": ("shall", "party", "parties", "agreement", "hereby", "terms", "obligation", "warrant"),
    "Teach": ("learn", "lesson", "exercise", "example", "objective", "student", "practice", "understand"),
    "Explain": ("means", "that is", "in other words", "works by", "the reason", "how", "why"),
    "Entertain": ("said", "laughed", "once", "suddenly", "door", "night", "smiled", "whispered"),
    "Evaluate": ("criteria", "rating", "strength", "weakness", "score", "assessment", "overall", "review"),
    "Predict": ("forecast", "will likely", "expected to", "projection", "outlook", "by 20", "scenario"),
    "Inform": ("announce", "report", "according to", "said", "update", "news", "today")}
PASSIVE = re.compile(r"\b(?:is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?\w+(?:ed|en)\b", re.I)
CONTROLS = {
    "tone": tuple(TONES),
    "tone2": tuple(TONES),
    "person": ("first person — I", "first person — we", "second person — you", "third person"),
    "formality": ("very formal", "formal", "plain professional", "informal", "casual"),
    "sentences": ("short", "medium", "long", "mixed — short and long"),
    "reading": ("for anyone — everyday words", "general reader", "expert reader — keep the technical terms"),
    "contractions": ("yes", "no"),
    "feeling": ("restrained", "some feeling", "openly emotional"),
    "humour": ("none", "a light touch", "humorous"),
    "certainty": ("state plainly", "hedge where unsure", "tentative throughout"),
    "detail": ("only the essentials", "balanced", "rich in particulars and examples"),
    "opening": ("the point first", "a question", "a particular person or moment", "a surprising fact from my material"),
    "ending": ("an action to take", "back to the opening", "a question left open", "a plain summary")}
CONTROL_SAY = {"tone": "Tone", "tone2": "Second tone", "person": "Point of view", "formality": "Formality", "sentences": "Sentences", "reading": "Reader level",
               "contractions": "Contractions", "feeling": "Feeling", "humour": "Humour", "certainty": "Certainty", "detail": "Detail", "opening": "Open with",
               "ending": "End with"}


def cue_count(low: str, cues: tuple) -> int:
    return sum(len(re.findall(r"\b%s\b" % re.escape(c), low)) for c in cues)


def analyze_document(text: str, doctypes: dict, styles: dict) -> dict:
    """an existing document read for what it is and how it sounds: likely type(s), likely purpose, voice (person, active or
    passive, formality), tone, the nearest style templates and its measured habits. Rules only: every finding is 'likely' and
    carries what it rests on; nothing is asserted that the rules cannot see."""
    low = text.lower().replace("’", "'")
    words = WORD.findall(text)
    sents = sentences(text)
    n = max(1, len(words))
    heads = [h.lower() for h in headings(text)]
    title, _body = title_of(text)
    # ---- likely type: the types whose expected parts appear as headings or words, and whose name appears near the top
    top = (title + " " + " ".join(text.split("\n")[:6])).lower()
    scored: list[tuple[float, str, str]] = []
    for t in doctypes.get("types", {}).values():
        els = [str(e).lower() for e in t.get("elements") or []]
        hit = [e for e in els if any(p and (p in h) for h in heads for p in re.split(r"[/,]| and ", e) if len(p.strip()) > 3)]
        score = (len(hit) / len(els) if len(els) >= 3 else 0.0) + (0.8 if re.search(r"\b%s\b" % re.escape(t["name"].lower()), top) else 0.0)
        if score >= 0.5:
            scored.append((round(score, 2), t["id"], "%d of its %d expected parts are headings here%s" % (
                len(hit), len(els), "; it is named at the top" if score - (len(hit) / len(els) if len(els) >= 3 else 0) > 0 else "")))
    scored.sort(key=lambda x: (-x[0], x[1]))
    likely = [{"id": i, "name": doctypes["types"][i]["name"], "domain": doctypes["types"][i]["domain"], "why": why} for _s, i, why in scored[:3]]
    # ---- likely purpose
    pc = sorted(((cue_count(low, cues) * 1000 // n, p) for p, cues in PURPOSE_CUES.items()), reverse=True)
    purposes = [p for c, p in pc[:2] if c >= 8 and cue_count(low, PURPOSE_CUES[p]) >= 3]
    # ---- voice
    fp, sp = len(FIRST_PERSON.findall(text)), len(SECOND_PERSON.findall(text))
    we = len(re.findall(r"\b(we|us|our|ours)\b", low))
    person = ("first person — we" if we * 2 >= fp else "first person — I") if fp * 100 >= n * 2 and fp >= sp else \
        "second person — you" if sp * 100 >= n * 2 else "third person"
    passive = sum(1 for s in sents if PASSIVE.search(s))
    contr = len(CONTRACTION.findall(text))
    prof = style_profile(text) if len(words) >= 40 else {}
    wl = float(prof.get("word_letters", 4.6)) if prof else 4.6
    sw = float(prof.get("sentence_words", 16)) if prof else 16.0
    formality = "casual" if contr * 100 >= n * 3 else "informal" if contr * 100 >= n * 1.2 else \
        "very formal" if wl >= 5.3 and sw >= 24 and not contr else "formal" if wl >= 5.0 and not contr else "plain professional"
    # ---- tone
    tc = sorted(((cue_count(low, cues) * 1000 // n, tname) for tname, cues in TONES.items() if cues), reverse=True)
    tones = [tname for c, tname in tc[:2] if c >= 10] or ["neutral"]
    # ---- nearest style templates
    near: list[dict] = []
    if prof and len(words) >= STYLE_MIN_WORDS:
        ranked = sorted(((style_distance(prof, s["profile"])["distance"], s["id"], s["name"]) for s in styles.values() if s.get("profile")))
        near = [{"id": i, "name": nm, "distance": d} for d, i, nm in ranked[:3]]
    controls = {"tone": tones[0], "tone2": tones[1] if len(tones) > 1 else "", "person": person, "formality": formality,
                "sentences": "short" if sw <= 12 else "long" if sw >= 24 else "mixed — short and long" if prof and float(prof.get("sentence_spread", 0)) >= 9 else "medium",
                "contractions": "yes" if contr * 100 >= n * 1.2 else "no",
                "certainty": "tentative throughout" if len(HEDGE.findall(text)) * 100 >= n * 3 else "hedge where unsure" if HEDGE.search(text) else "state plainly",
                "reading": "expert reader — keep the technical terms" if wl >= 5.3 else "for anyone — everyday words" if wl <= 4.3 else "general reader"}
    return {"words": len(words), "sentences": len(sents), "likely_types": likely, "purposes": purposes, "person": person,
            "passive_share": round(passive / max(1, len(sents)), 2), "formality": formality, "tones": tones, "styles": near, "profile": prof,
            "controls": controls, "enough_for_style": len(words) >= STYLE_MIN_WORDS}


def analysis_text(a: dict) -> str:
    lines = ["WHAT THIS DOCUMENT IS — read by rules; every line is a likelihood, not a ruling", ""]
    if a["likely_types"]:
        lines.append("Type, likely:")
        lines += ["  • %s (%s) — %s" % (t["name"], t["domain"], t["why"]) for t in a["likely_types"]]
    else:
        lines.append("Type: the rules cannot tell — it has no headings or name that match a type in the list. Choose the type yourself.")
    lines.append("Purpose, likely: " + (", ".join(a["purposes"]).lower() if a["purposes"] else "the rules cannot tell") + ".")
    lines += ["", "HOW IT SOUNDS", "Point of view: %s." % a["person"], "Formality: %s." % a["formality"],
              "Tone, likely: %s." % " and ".join(a["tones"]),
              "Voice: %d%% of sentences are passive." % round(a["passive_share"] * 100)]
    p = a["profile"]
    if p:
        lines.append("Sentences: about %s words on average%s; words about %s letters; paragraphs about %s sentences." % (
            p["sentence_words"], ", varied" if p["sentence_spread"] >= 9 else ", even" if p["sentence_spread"] <= 5 else "", p["word_letters"], p["paragraph_sentences"]))
    if a["styles"]:
        lines.append("Nearest style templates: " + "; ".join("%s (%.2f away)" % (s["name"], s["distance"]) for s in a["styles"]) + ". (0 = the same habits.)")
    elif not a["enough_for_style"]:
        lines.append("Style: too short to measure against the templates (%d words; %d are needed)." % (a["words"], STYLE_MIN_WORDS))
    lines += ["", "TO WRITE LIKE THIS: use “Write with these settings” — the controls are set from this reading, and you can change any of them."]
    return "\n".join(lines)


def controls_brief(controls: dict) -> list[str]:
    """the person's own settings as instructions for whoever drafts; a setting left unset is left to the type and the style"""
    out: list[str] = []
    tones = [str(controls.get(k) or "") for k in ("tone", "tone2")]
    tones = [t for t in tones if t in TONES and t != "neutral"]
    if tones:
        out.append("Tone: %s — carried by word choice and rhythm, never announced" % " and ".join(tones))
    elif controls.get("tone") == "neutral":
        out.append("Tone: neutral — no colouring words")
    for k in ("person", "formality", "sentences", "reading", "feeling", "humour", "certainty", "detail", "opening", "ending"):
        v = str(controls.get(k) or "")
        if v in CONTROLS[k]:
            out.append("%s: %s" % (CONTROL_SAY[k], v))
    if controls.get("contractions") in ("yes", "no"):
        out.append("Contractions: " + ("use them" if controls["contractions"] == "yes" else "do not use them"))
    try:
        w = int(controls.get("words") or 0)
    except (TypeError, ValueError):
        w = 0
    if w > 0:
        out.append("Length: about %d words" % w)
    return out


def controls_check(text: str, controls: dict) -> list[dict]:
    """the settings a rule can measure, checked against the draft: [{"control", "ok", "why"}]"""
    out: list[dict] = []
    words = WORD.findall(text)
    n = max(1, len(words))
    a = analyze_document(text, {"types": {}}, {})
    want = str(controls.get("person") or "")
    if want in CONTROLS["person"]:
        ok = a["person"].split(" — ")[0] == want.split(" — ")[0]
        out.append({"control": "Point of view", "ok": ok, "why": "asked for %s; the draft reads as %s" % (want, a["person"])})
    if controls.get("contractions") in ("yes", "no"):
        c = len(CONTRACTION.findall(text))
        ok = (c > 0) if controls["contractions"] == "yes" else (c == 0)
        out.append({"control": "Contractions", "ok": ok, "why": "%d in the draft; asked: %s" % (c, controls["contractions"])})
    try:
        w = int(controls.get("words") or 0)
    except (TypeError, ValueError):
        w = 0
    if w > 0:
        out.append({"control": "Length", "ok": abs(len(words) - w) * 4 <= w, "why": "%d words; asked for about %d" % (len(words), w)})
    want = str(controls.get("sentences") or "")
    if want in ("short", "long") and a["profile"]:
        sw = float(a["profile"]["sentence_words"])
        out.append({"control": "Sentences", "ok": sw <= 14 if want == "short" else sw >= 20, "why": "average %s words; asked for %s" % (sw, want)})
    want = str(controls.get("tone") or "")
    if want in TONES and TONES[want]:
        c = cue_count(text.lower(), TONES[want])
        out.append({"control": "Tone", "ok": None, "why": "asked for %s; %d of its usual words appear — tone is for you to judge by ear" % (want, c)})
    return out
