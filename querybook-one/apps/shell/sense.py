"""A grasp of reality for the Ask box: WHAT KIND of thing each match is, which one the person means, and how to say who
or what it is.

The store may hold many things with one name: Babe Ruth the man, a museum's baseball card called "Babe Ruth", a film,
an award, a stadium. Before, the first match found was "the answer" — Babe Ruth was a baseball card. Here every match is
given its kind from its own facts (a human has a birth date and an occupation; a card is an instance of "baseball card"
that depicts someone), the question says what kind it expects ("who" expects a person), a thing made ABOUT something
(a card, a portrait, a film, a statue, a prize) ranks below the thing itself, and the best known of the right kind wins.
When only a thing-about is held, the answer says so instead of pretending.

Pure functions over plain data (no I/O, no reflection): Rust-ready, like ask.py and modes.py.
"""
from __future__ import annotations

import math
import re

QID = re.compile(r"\s*\(Q\d+\)")
YEAR = re.compile(r"(?<!\d)(-?\d{3,4})(?!\d)")

# what an "instance of" value says about the kind of thing (first match wins; checked on lower-case words)
CLASS_KIND: list[tuple[str, tuple[str, ...]]] = [
    ("human", ("human", "person", "fictional human", "biblical figure", "mythical character", "human biblical figure")),
    ("depiction", ("baseball card", "trading card", "card", "photograph", "portrait", "painting", "print", "drawing", "poster", "postage stamp",
                   "statue", "sculpture", "bust", "engraving", "lithograph", "caricature", "collectible", "artwork", "work of art", "figurine",
                   "action figure", "medal", "coin", "banknote", "wax figure", "museum object", "archival", "manuscript", "collection item")),
    ("work", ("film", "television series", "television program", "episode", "book", "novel", "song", "album", "single", "play", "musical",
              "documentary", "biography", "biographical", "literary work", "poem", "video game", "opera", "podcast", "magazine", "comic")),
    ("award", ("award", "prize", "trophy", "honor", "honour")),
    ("event", ("war", "battle", "election", "revolution", "disaster", "earthquake", "tournament", "season", "games", "festival", "treaty",
               "assassination", "event", "massacre", "expedition", "protest", "strike", "pandemic", "ceremony")),
    ("organization", ("organization", "organisation", "company", "business", "university", "college", "school", "agency", "party", "church",
                      "denomination", "team", "club", "band", "musical group", "newspaper", "network", "museum", "library", "hospital",
                      "institution", "foundation", "government", "association", "union", "league", "orchestra", "studio", "label")),
    ("place", ("city", "town", "village", "country", "state", "province", "county", "island", "mountain", "river", "lake", "park", "monument",
               "memorial", "building", "bridge", "stadium", "street", "square", "tower", "castle", "palace", "temple", "cathedral", "airport",
               "station", "neighborhood", "region", "continent", "ocean", "sea", "desert", "valley", "volcano", "tourist attraction", "landmark",
               "skyscraper", "dam", "canal", "cemetery", "theater", "theatre", "arena", "district", "capital", "settlement", "site")),
    ("species", ("taxon", "species", "breed", "genus")),
    ("substance", ("chemical compound", "chemical element", "mineral", "drug", "medication", "alloy")),
]
HUMAN_PREDS = ("date of birth", "place of birth", "date of death", "place of death", "occupation", "sex or gender", "given name", "family name",
               "spouse", "father", "mother", "educated at", "country of citizenship")
PLACE_PREDS = ("coordinate location", "population", "located in the administrative territorial entity", "capital", "elevation above sea level")
ABOUT_PREDS = ("depicts", "main subject", "named after", "dedicated to", "based on", "commemorates", "cast member", "characters")
# what a question expects; None = anything
EXPECTS: dict[str, tuple[str, ...]] = {"who": ("human", "organization"), "where": ("place", "organization", "event"), "whose": ("human",)}
# the kinds that are things made ABOUT other things: never preferred over the thing itself
ABOUT_KINDS = ("depiction", "work", "award")
KIND_WORD = {"human": "a person", "depiction": "an object depicting someone or something", "work": "a creative work", "award": "an award",
             "event": "an event", "organization": "an organization", "place": "a place", "species": "a living thing", "substance": "a substance",
             "thing": "a thing"}

# predicates that identify a record in some other database: true, and of no use in an answer
ID_END = (" id", " identifier", " number", " code", " username", " handle", " profile", " url", " uri", " slug", " key", " entry", " record")
ID_ANY = ("identifier", "authority", "viaf", "isni", "imdb", "freebase", "musicbrainz", "library of congress", "find a grave", "wikitree",
          "commons category", "commons gallery", "image", "signature", "logo", "pronunciation audio", "topic's main", "described at url",
          "official website", "google ", "facebook", "twitter", "instagram", "youtube", "tiktok", "spotify", "discogs", "allmusic", "geni.com",
          "familysearch", "nndb", "catalog", "catalogue", "archive", "encyclop", "britannica", "dictionary", "gnd", "bnf", "ndl", "nkc", "selibr",
          "worldcat", "open library", "goodreads", "quora", "reddit", "wikimedia", "wikipedia", "wikidata", "on focus list", "permanent duplicated",
          "described by source", "has works in the collection", "copyright status", "different from", "said to be the same", "retrosheet",
          "baseball-reference", "sports-reference", "fangraphs", "mlb.com", "nfl.com", "nba.com", "transfermarkt", "olympedia", "espn", "tmdb",
          "rotten tomatoes", "metacritic", "allmovie", "letterboxd", "kinopoisk", "filmportal", "ibdb", "playbill")
# the predicates worth showing first, by kind (earlier = more telling)
IMPORTANT: dict[str, tuple[str, ...]] = {
    "human": ("description", "occupation", "also known as", "date of birth", "place of birth", "date of death", "place of death", "cause of death",
              "country of citizenship", "position held", "member of sports team", "sport", "position played", "notable work", "field of work",
              "award received", "educated at", "employer", "member of political party", "spouse", "child", "father", "mother", "sibling",
              "religion", "military branch", "genre", "instrument", "record label", "nominated for", "member of", "residence", "native language",
              "languages spoken", "birth name", "nickname", "height", "work period (start)", "work period (end)", "place of burial"),
    "place": ("description", "instance of", "country", "located in the administrative territorial entity", "capital", "population", "area",
              "coordinate location", "inception", "elevation above sea level", "architect", "architectural style", "height", "heritage designation",
              "named after", "official language", "head of government", "head of state", "currency", "continent", "time zone", "also known as"),
    "organization": ("description", "instance of", "inception", "founded by", "headquarters location", "country", "industry", "chief executive officer",
                     "chairperson", "parent organization", "owned by", "member count", "employees", "students count", "motto", "league",
                     "home venue", "product or material produced", "dissolved, abolished or demolished date", "also known as"),
    "event": ("description", "instance of", "point in time", "start time", "end time", "location", "country", "participant", "winner",
              "successful candidate", "number of deaths", "cause", "has effect", "part of", "follows", "followed by", "also known as"),
    "thing": ("description", "instance of", "subclass of", "inception", "creator", "author", "director", "performer", "publication date",
              "country of origin", "genre", "depicts", "main subject", "named after", "collection", "location", "made from material",
              "discoverer or inventor", "time of discovery or invention", "part of", "has part", "use", "also known as"),
}


def clean(s: object) -> str:
    return " ".join(QID.sub("", str(s or "")).split())


def is_identifier(predicate: str, value: str) -> bool:
    """a record number in somebody's database, a web address, a file name: true but not an answer"""
    p = " " + predicate.lower().strip()
    v = value.strip().lower()
    if v.startswith(("http://", "https://", "www.")) or v.endswith((".jpg", ".jpeg", ".png", ".svg", ".ogg", ".tif", ".webm", ".gif", ".pdf")):
        return True
    return p.endswith(ID_END) or any(w in p for w in ID_ANY)


def kind_of(facts: list[dict]) -> str:
    """the kind of thing these facts describe, from what they say it is (instance of) and what is recorded about it"""
    preds = [str(f.get("predicate") or "").lower() for f in facts]
    classes = [clean(f.get("object")).lower() for f in facts if str(f.get("predicate") or "").lower() == "instance of"]
    for kind, words in CLASS_KIND:
        for c in classes:
            cw = c.split()
            if c in words or any(w in words for w in (c, " ".join(cw[-2:]), cw[-1] if cw else "")):
                return kind
    if sum(1 for p in set(preds) if p in HUMAN_PREDS) >= 2:
        return "human"
    if sum(1 for p in set(preds) if p in PLACE_PREDS) >= 1:
        return "place"
    return "thing"


def expects(question: str) -> tuple[str, ...]:
    words = question.lower().split()
    return EXPECTS.get(words[0] if words else "", ())


def group(facts: list[dict]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    for f in facts:
        by.setdefault(str(f.get("subject") or ""), []).append(f)
    return by


def is_about(kind: str, facts: list[dict]) -> bool:
    """a thing made about something else: a card, a portrait, a film, a prize — or anything that says it depicts, is named
    after or is dedicated to something"""
    if kind in ABOUT_KINDS:
        return True
    return kind != "human" and any(str(f.get("predicate") or "").lower() in ABOUT_PREDS for f in facts)


def choose(question: str, entities: list[dict], facts: list[dict]) -> dict:
    """which match is meant. entities: [{"subject", "facts": n, "fame": n|None}] (find_entities); facts: all their facts.
    Score: the kind the question expects (who -> a person) first; the thing itself above things made about it; then how
    well known (Wikipedias with an article, else how much is recorded). Returns {"subject", "kind", "why", "ranked":
    [...], "only_about": bool}."""
    by = group(facts)
    want = expects(question)
    ranked: list[dict] = []
    for e in entities:
        s = str(e.get("subject") or "")
        fs = by.get(s) or []
        k = kind_of(fs)
        about = is_about(k, fs)
        fame = float(e.get("fame") or 0)
        views = float(e.get("views") or 0)
        n = float(e.get("facts") or len(fs) or 0)
        # the kind asked for, then the thing itself, then how much it is read (Wikipedia page views), how widely it is
        # written about (Wikipedias with an article) and how much is held about it
        # a thing named exactly as asked has an edge over one found by another name or by part of its name — an edge a
        # well-known thing overcomes ("Dodgers" is the Los Angeles Dodgers, not an obscure item called just "Dodgers")
        # a full name typed out and matched exactly ("Ed Sullivan") is a far stronger sign than one word that many share
        full = len(clean(s).split()) >= 2
        exact = (600.0 if full else 150.0) if e.get("exact", True) else 0.0
        # the famous one is meant: a well-known name a letter or two from what was typed stands level with a name typed exactly,
        # so that being well known decides — the president, not an obscure man whose name happens to be the misspelling
        if e.get("assumed_from_spelling"):
            exact = 600.0 if full else 150.0
        score = (1000.0 if want and k in want else 0.0) + (0.0 if about else 300.0) + exact + 60.0 * math.log10(1.0 + views) \
            + 6.0 * min(fame, 150.0) + 40.0 * math.log10(1.0 + n)
        said = next((clean(f.get("object")) for f in fs if str(f.get("predicate") or "").lower() == "description"), "") or \
            next((clean(f.get("object")) for f in fs if str(f.get("predicate") or "").lower() in ("instance of", "occupation")), "")
        ranked.append({"subject": s, "kind": k, "about": about, "score": round(score, 1), "fame": e.get("fame"), "views": e.get("views"),
                       "facts": int(n), "what": said, "exact": bool(e.get("exact", True)), "assumed": str(e.get("assumed_from_spelling") or "")})
    ranked.sort(key=lambda r: (-r["score"], r["subject"]))
    if not ranked:
        return {"subject": "", "kind": "", "why": "", "ranked": [], "only_about": False}
    top = ranked[0]
    only_about = bool(top["about"]) and not any(not r["about"] for r in ranked)
    why = "%s is %s" % (clean(top["subject"]), KIND_WORD.get(top["kind"], "a thing"))
    if top.get("assumed"):
        why = "no well-known subject is spelled that way, so the well-known %s is assumed: " % top["assumed"] + why
    elif not top.get("exact", True):
        why = "the best-known thing by that name: " + why
    if top.get("views"):
        why += ", among the most-read subjects on Wikipedia"
    if top.get("fame"):
        why += ", with an article in %d Wikipedias" % int(top["fame"])
    if len(ranked) > 1:
        why += " — the best known of %d things with this name" % len(ranked)
    return {"subject": top["subject"], "kind": top["kind"], "why": why, "ranked": ranked[:8], "only_about": only_about}


def arrange(facts: list[dict], kind: str) -> list[dict]:
    """the facts worth reading first: the telling predicates in order, then the rest; record numbers and web addresses last
    (kept, since they are true — but never the answer)"""
    order = IMPORTANT.get(kind) or IMPORTANT["thing"]
    rank = {p: i for i, p in enumerate(order)}

    def key(item: tuple[int, dict]) -> tuple[int, int, int]:
        i, f = item
        p = str(f.get("predicate") or "").lower()
        ident = is_identifier(p, str(f.get("object") or ""))
        return (2 if ident else 0 if p in rank else 1, rank.get(p, 999), i)
    return [f for _, f in sorted(enumerate(facts), key=key)]


def first(facts: list[dict], predicate: str) -> str:
    for f in facts:
        if str(f.get("predicate") or "").lower() == predicate:
            return clean(f.get("object"))
    return ""


def several(facts: list[dict], predicate: str, n: int = 3) -> list[str]:
    out: list[str] = []
    for f in facts:
        if str(f.get("predicate") or "").lower() == predicate:
            v = clean(f.get("object"))
            if v and v not in out:
                out.append(v)
    return out[:n]


# ---- the states of a fact unit. The user: "We have true, false, undetermined, and conflicting status? Are these the new 4 states
# of fact units? … we put them in a 'we don't know' zone." Two different questions are kept apart:
#   TRUTH    is the statement true?        true / false / undetermined / conflicting
#   IDENTITY do we know who or what it is about?   resolved / unresolved / ambiguous / conflicting
# "The Greenville Times printed the name Harvey Jordan on 4 March 1905" is TRUE and its identity is UNRESOLVED: the page
# is there to read, but which Harvey Jordan is not known. Marking the whole fact "undetermined" would throw away what is known.
# The fuller status a fact already carries (how it is backed) stays underneath as the reason for its truth state.
TRUTH_STATES = ("true", "false", "undetermined", "conflicting")
IDENTITY_STATES = ("resolved", "unresolved", "ambiguous", "conflicting")
TRUTH_OF = {"verified": "true", "corroborated": "true", "computed": "true", "rejected": "false", "disputed": "conflicting",
            "sourced": "undetermined", "reported": "undetermined", "unsourced": "undetermined"}
TRUTH_WHY = {"verified": "checked and confirmed", "corroborated": "two or more independent sources agree", "computed": "calculated, and the calculation can be repeated",
             "rejected": "found to be wrong", "disputed": "sources disagree", "sourced": "one named source says so; not yet confirmed by a second",
             "reported": "a report says so; not confirmed", "unsourced": "no source is recorded"}


def independent_sources(fact: dict) -> int:
    """how many different sources a fact's own record names (the work it is stated in, else the address's site)"""
    seen: list[str] = []
    for x in fact.get("sources") or []:
        if not isinstance(x, dict):
            continue
        key = clean(x.get("stated in")) or re.sub(r"^https?://(?:www\.)?([^/]+).*$", r"\1", str(x.get("url") or "")) or clean(x.get("title"))
        if key and key not in seen:
            seen.append(key)
    return len(seen)


def truth_state(fact: dict) -> dict:
    """{"state": one of TRUTH_STATES, "backing": the fuller status, "why"} for one fact. A fact one source states becomes
    corroborated — and so true — when its own record names two or more different sources; nothing else is promoted."""
    backing = str(fact.get("status") or "unsourced").lower()
    if backing == "sourced" and independent_sources(fact) >= 2:
        backing = "corroborated"
    if backing not in TRUTH_OF:
        backing = "unsourced"
    return {"state": TRUTH_OF[backing], "backing": backing, "why": TRUTH_WHY[backing]}


def identity_state(subject: str, facts: list[dict]) -> dict:
    """{"state": one of IDENTITY_STATES, "why"} for a subject: resolved when it carries its record's own identifier; a name
    printed in a newspaper is unresolved — it stands for whoever bore that name, and is never taken for a known person"""
    if any(str(f.get("predicate") or "").lower() == "in the news" for f in facts) and not QID.search(subject):
        return {"state": "unresolved", "why": "a name as printed in a newspaper: which person of that name is not known"}
    return {"state": "resolved", "why": "identified by its source's own record"}


# ---- is a newspaper's name THIS person? Never decided by the name alone. Each mention is weighed against what the store holds
# about the person: was the person alive then; does the office the paper gives match one the person held; is the paper's place
# one of the person's places; does a report of a death fall at the person's death. The verdict is one of three, with its
# reasons, and it is an ANALYSIS shown beside the answer — the mention is never merged into the person's record.
MENTION = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) — (.*?), p\. (\d+) — (.*?) — “(.*)”$")
STATE_ABBR = {"ala": "Alabama", "alaska": "Alaska", "ariz": "Arizona", "ark": "Arkansas", "cal": "California", "calif": "California", "colo": "Colorado",
              "conn": "Connecticut", "del": "Delaware", "d.c": "District of Columbia", "fla": "Florida", "ga": "Georgia", "hawaii": "Hawaii",
              "idaho": "Idaho", "ill": "Illinois", "ind": "Indiana", "iowa": "Iowa", "kan": "Kansas", "kans": "Kansas", "ky": "Kentucky", "la": "Louisiana",
              "me": "Maine", "md": "Maryland", "mass": "Massachusetts", "mich": "Michigan", "minn": "Minnesota", "miss": "Mississippi", "mo": "Missouri",
              "mont": "Montana", "neb": "Nebraska", "nebr": "Nebraska", "nev": "Nevada", "n.h": "New Hampshire", "n.j": "New Jersey", "n.m": "New Mexico",
              "n.y": "New York", "n.c": "North Carolina", "n.d": "North Dakota", "ohio": "Ohio", "okla": "Oklahoma", "or": "Oregon", "ore": "Oregon",
              "pa": "Pennsylvania", "r.i": "Rhode Island", "s.c": "South Carolina", "s.d": "South Dakota", "tenn": "Tennessee", "tex": "Texas",
              "utah": "Utah", "vt": "Vermont", "va": "Virginia", "wash": "Washington", "w. va": "West Virginia", "w.va": "West Virginia",
              "wis": "Wisconsin", "wyo": "Wyoming"}
OFFICE_WORDS = ("president", "senator", "governor", "judge", "justice", "mayor", "general", "colonel", "admiral", "secretary", "bishop",
                "professor", "congressman", "representative", "ambassador", "sheriff", "king", "queen", "pope", "minister", "captain")
PLACE_PREDS = ("place of birth", "place of death", "residence", "work location", "place of burial", "headquarters location", "educated at")


def mention_parts(obj: str) -> dict:
    """a news-lattice fact's value taken apart: {"year", "date", "paper", "town", "state", "page", "reason", "context"}; {} when it is not one"""
    m = MENTION.match(clean(obj) if "(Q" in obj else obj)
    if not m:
        return {}
    paper = m.group(4)
    pm = re.search(r"\(([^()]*)\)\s*$", paper)
    town, state = "", ""
    if pm:
        bits = [b.strip() for b in pm.group(1).replace("[", "").replace("]", "").split(",")]
        town = bits[0] if bits else ""
        if len(bits) > 1:
            state = STATE_ABBR.get(bits[-1].lower().rstrip("."), bits[-1].rstrip("."))
    return {"year": int(m.group(1)), "date": "%s-%s-%s" % (m.group(1), m.group(2), m.group(3)), "paper": paper, "town": town, "state": state,
            "page": int(m.group(5)), "reason": m.group(6), "context": m.group(7)}


def match_mention(obj: str, person: list[dict]) -> dict:
    """does one newspaper mention fit this person? {"verdict": "likely" | "possible" | "impossible", "why": [...]}.
    impossible: printed before the person was born (or when a small child). likely: within the person's life AND something
    more agrees (an office, a place, the date of death). possible: nothing against it and nothing more for it — or printed
    after the person's death, when a paper may be writing about them or about someone else of the name."""
    mp = mention_parts(obj)
    if not mp:
        return {"verdict": "possible", "why": ["the mention carries no date"]}
    born, died = first(person, "date of birth"), first(person, "date of death")
    by, dy = year(born), year(died)
    why: list[str] = []
    if by and mp["year"] < int(by):
        return {"verdict": "impossible", "why": ["printed in %d, before the birth in %s" % (mp["year"], by)]}
    if by and mp["year"] < int(by) + 12 and mp["reason"] != "born":
        return {"verdict": "impossible", "why": ["printed in %d, when the person was a child of %d" % (mp["year"], mp["year"] - int(by))]}
    after = bool(dy) and mp["year"] > int(dy)
    low = (mp["context"] + " ").lower()
    held = " ".join(clean(f.get("object")).lower() for f in person if str(f.get("predicate") or "").lower() in ("position held", "occupation", "military rank", "noble title"))
    for w in OFFICE_WORDS:
        if w in low and w in held:
            why.append("the paper says “%s”, an office or calling the person had" % w)
            break
    places = " ".join(clean(f.get("object")).lower() for f in person if str(f.get("predicate") or "").lower() in PLACE_PREDS)
    for place in (mp["town"], mp["state"]):
        if place and len(place) > 3 and place.lower() in places:
            why.append("the paper is from %s, one of the person's places" % place)
            break
    if mp["reason"] == "died" and died and mp["date"] >= died[:10] and year(died) == str(mp["year"]):
        why.append("it reports a death, printed in the year the person died (%s)" % died[:10])
    if mp["reason"] == "born" and by and int(by) == mp["year"]:
        why.append("it reports a birth, in the person's year of birth")
    for f in person:
        if str(f.get("predicate") or "").lower() == "position held" and year(str(f.get("start") or "")) == str(mp["year"]) and mp["reason"] == "elected or appointed":
            why.append("it reports an election or appointment in %d, the year the person took office as %s" % (mp["year"], clean(f.get("object"))))
            break
    if after:
        return {"verdict": "possible", "why": ["printed in %d, after the person's death in %s: it may be about them, or someone else of the name" % (mp["year"], dy)] + why}
    if why and (by or dy):
        return {"verdict": "likely", "why": ["printed in %d, within the person's life" % mp["year"]] + why}
    if why:
        return {"verdict": "possible", "why": why + ["the person's dates are not held, so the time cannot be checked"]}
    return {"verdict": "possible", "why": ["printed in %d%s; nothing more ties it to this person" % (mp["year"], ", within the person's life" if by else "")]}


def weigh_mentions(news: list[dict], person: list[dict]) -> dict:
    """every newspaper mention of a name weighed against one known person: {"likely", "possible", "impossible", "of",
    "examples": [{"date", "paper", "reason", "verdict", "why"}], "say"} — an analysis, never a merge"""
    counts = {"likely": 0, "possible": 0, "impossible": 0}
    rows: list[dict] = []
    for f in news:
        mp = mention_parts(str(f.get("object") or ""))
        v = match_mention(str(f.get("object") or ""), person)
        counts[v["verdict"]] += 1
        if mp:
            rows.append({"date": mp["date"], "paper": mp["paper"], "reason": mp["reason"], "verdict": v["verdict"], "why": v["why"]})
    rows.sort(key=lambda r: ({"likely": 0, "impossible": 1, "possible": 2}[str(r["verdict"])], str(r["date"])))
    of = len(news)
    bits = []
    if counts["likely"]:
        bits.append("%d fit by date and by something more (likely this person)" % counts["likely"])
    if counts["possible"]:
        bits.append("%d have nothing against them and nothing more for them" % counts["possible"])
    if counts["impossible"]:
        bits.append("%d cannot be this person (printed before the birth, or in childhood)" % counts["impossible"])
    return dict(counts, of=of, examples=rows[:6], say="Of %d newspaper mention%s of the name: %s." % (of, "" if of == 1 else "s", "; ".join(bits)) if of else "")


def period(f: dict) -> str:
    """when a fact held, from its own context (1.48): "1981–1989", "since 2009", "until 1975", "1969" — or "" when the
    store holds no date for it. Never guessed."""
    a, b, at = year(str(f.get("start") or "")), year(str(f.get("end") or "")), year(str(f.get("at") or ""))
    if a and b:
        return a if a == b else "%s–%s" % (a, b)
    if a:
        return "since " + a
    if b:
        return "until " + b
    return at


def dated(facts: list[dict], predicate: str, n: int = 4) -> list[str]:
    """the values of a predicate with the period each held, the earliest first when dates are known ("Governor of
    California (1967–1975)"); those without a date keep their order after them"""
    rows: list[tuple[int, int, str]] = []
    seen: list[str] = []
    for i, f in enumerate(facts):
        if str(f.get("predicate") or "").lower() != predicate:
            continue
        v = clean(f.get("object"))
        if not v or v in seen:
            continue
        seen.append(v)
        p = period(f)
        y = year(str(f.get("start") or f.get("at") or f.get("end") or ""))
        rows.append((0 if y else 1, int(y) if y else i, v + (" (%s)" % p if p else "")))
    rows.sort(key=lambda r: (r[0], r[1]))
    return [r[2] for r in rows[:n]]


def year(value: str) -> str:
    m = YEAR.search(value or "")
    return m.group(1) if m else ""


def a_an(phrase: str) -> str:
    return ("an " if phrase[:1].lower() in "aeiou" else "a ") + phrase


# ---- what a person is BEST KNOWN as. A record lists every occupation a person ever had, in no order of importance: Boris Vian
# is "prose writer, poet, engineer"; Ronald Reagan is "actor, politician, trade unionist ..."; Arnold Schwarzenegger a
# bodybuilder, actor, politician and businessman. Four signs, all from the person's own facts, say which one the world knows:
#   1. the one-line description names it ("American television host") — written by people to say who this is: the strongest;
#   2. the record backs it up: teams and a sport for an athlete, positions held for a politician, instruments and labels for
#      a musician, awards and notable works whose names say the field;
#   3. the highest office outranks an occupation: a head of state is known as that;
#   4. the order the record lists them in — the weakest sign, a tie-break.
# (family, words in an occupation or description, predicates that back it up, words in awards / works / positions that back it up)
ROLES: tuple[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...] = (
    ("leader", ("politician", "statesman", "stateswoman", "president", "prime minister", "monarch", "king", "queen", "emperor", "senator",
                "governor", "chancellor", "dictator", "head of state", "pope", "mayor", "diplomat"),
     ("position held", "member of political party", "candidacy in election", "noble title"), ("president", "prime minister", "chancellor", "king", "queen", "emperor", "pope", "governor", "senator")),
    ("athlete", ("player", "athlete", "footballer", "boxer", "swimmer", "driver", "golfer", "wrestler", "runner", "cyclist", "skater",
                 "gymnast", "sprinter", "pitcher", "quarterback", "cricketer", "jockey", "skier"),
     ("member of sports team", "sport", "league or competition", "league", "position played on team / speciality", "drafted by", "sports discipline competed in"),
     ("most valuable player", "olympic", "hall of fame", "world cup", "ballon", "heisman", "wimbledon")),
    ("musician", ("singer", "musician", "songwriter", "composer", "rapper", "guitarist", "pianist", "drummer", "conductor", "band",
                  "vocalist", "violinist", "disc jockey", "record producer"),
     ("instrument", "record label", "voice type", "discography", "member of"), ("grammy", "rock and roll hall of fame", "brit award", "music")),
    ("actor", ("actor", "actress", "film director", "director", "filmmaker", "screenwriter", "film producer"),
     ("filmography",), ("academy award", "oscar", "emmy", "golden globe", "screen actors", "bafta", "tony award", "film")),
    ("presenter", ("presenter", "host", "broadcaster", "comedian", "announcer", "entertainer", "journalist", "anchor", "columnist"),
     ("presenter",), ("show", "peabody", "pulitzer", "television")),
    ("writer", ("writer", "author", "novelist", "poet", "playwright", "essayist", "dramatist", "historian", "philosopher"),
     ("notable work", "literary movement", "writing language"), ("literature", "booker", "pulitzer", "hugo award", "book")),
    ("scientist", ("physicist", "chemist", "mathematician", "scientist", "biologist", "inventor", "engineer", "astronomer", "physician",
                   "economist", "psychologist", "computer scientist", "astronaut", "explorer", "naturalist"),
     ("doctoral advisor", "doctoral student", "field of work", "academic degree", "astronaut mission", "doctoral thesis"),
     ("nobel prize in physics", "nobel prize in chemistry", "physiology or medicine", "fields medal", "turing award", "royal society", "medal")),
    ("soldier", ("officer", "general", "soldier", "commander", "admiral", "military"),
     ("military rank", "military branch", "conflict", "participated in conflict", "commander of (DEPRECATED)", "military or police rank"), ("medal of honor", "victoria cross", "war")),
    ("religious figure", ("prophet", "priest", "theologian", "bishop", "rabbi", "preacher", "apostle", "saint", "missionary", "monk", "imam", "religious"),
     ("religion or worldview", "religious order", "canonization status", "feast day", "consecrator"), ("saint",)),
    ("business figure", ("entrepreneur", "businessperson", "businessman", "businesswoman", "executive", "investor", "industrialist", "banker", "magnate", "founder"),
     ("net worth", "owner of", "chief executive officer", "founded by"), ("forbes", "business")),
    ("artist", ("painter", "sculptor", "artist", "architect", "photographer", "designer", "illustrator", "cartoonist", "model"),
     ("movement", "has works in the collection", "artist files at"), ("art", "pritzker")),
)
HIGH_OFFICE = ("president of", "prime minister", "king of", "queen of", "emperor", "pope", "chancellor of", "monarch of", "head of state", "sultan", "tsar")


def role_family(occupation: str) -> int:
    """which family an occupation belongs to (its place in ROLES), or -1"""
    o = occupation.lower()
    for i, (_name, words, _preds, _signs) in enumerate(ROLES):
        if any(w in o for w in words):
            return i
    return -1


def known_for(facts: list[dict]) -> dict:
    """the occupation a person is best known for, from the person's own facts. Returns {"best": str, "role": str, "also":
    [...], "ranked": [{"occupation", "score", "signs": [...]}], "why": str}; best is "" when no occupation is recorded.
    role: the highest office held, when the person is known as a leader ("President of the United States")."""
    jobs = several(facts, "occupation", 40)
    desc = first(facts, "description").lower()
    preds: dict[str, int] = {}
    named: list[str] = []                                 # the names of awards, works and offices: they say the field
    for f in facts:
        p = str(f.get("predicate") or "").lower()
        preds[p] = preds.get(p, 0) + 1
        if p in ("award received", "nominated for", "notable work", "position held", "winner of", "member of"):
            named.append(clean(f.get("object")).lower())
    offices = several(facts, "position held", 40)
    high = next((o for o in offices if any(h in o.lower() for h in HIGH_OFFICE)), "")
    # 1. where the description names each occupation: word for word, by a telling word of it ("television host" for
    #    "television presenter"), or by a word of the same line of work. The description's own order ranks them.
    spot: list[tuple[int, float]] = []
    for job in jobs:
        fam = role_family(job)
        at, strength = (desc.find(job.lower()) if desc else -1), 3.0
        if at < 0 and desc:
            words = [w for w in job.lower().split() if len(w) > 3 and w in desc]
            if words:
                at, strength = desc.find(words[0]), 2.0
        if at < 0 and fam >= 0 and desc:
            hits = [desc.find(w) for w in ROLES[fam][1] if w in desc]
            if hits:
                at, strength = min(hits), 1.0
        spot.append((at, strength))
    order = sorted({a for a, _ in spot if a >= 0})
    ranked: list[dict] = []
    for i, job in enumerate(jobs):
        fam = role_family(job)
        signs: list[str] = []
        score = max(0.0, 10.0 - 2.0 * i)                  # 4. the record's own order: a tie-break
        at, strength = spot[i]
        if at >= 0:                                       # 1. the description names it; the earlier it does, the more so
            score += 300.0 - 25.0 * order.index(at) + 5.0 * strength
            signs.append("its description says so")
        if fam >= 0:
            backed = sum(preds.get(p, 0) for p in ROLES[fam][2]) + sum(1 for n in named if any(w in n for w in ROLES[fam][3]))
            if backed:                                    # 2. the record backs it up (never more than one place in the description)
                score += min(20.0, 4.0 * backed) if at >= 0 else min(60.0, 12.0 * backed)
                signs.append("%d fact%s of the record back it up" % (backed, "" if backed == 1 else "s"))
            if high and ROLES[fam][0] == "leader":        # 3. the highest office
                score += 20.0 if order else 80.0
                signs.append("held high office: " + high)
        ranked.append({"occupation": job, "score": round(score, 1), "signs": signs})
    ranked.sort(key=lambda r: (-float(r["score"]), jobs.index(str(r["occupation"]))))
    if not ranked:
        return {"best": "", "role": high, "also": [], "ranked": [], "why": ""}
    top = ranked[0]
    role = high if high and role_family(str(top["occupation"])) >= 0 and ROLES[role_family(str(top["occupation"]))][0] == "leader" else ""
    why = "best known as %s" % a_an(str(top["occupation"]))
    if top["signs"]:
        why += " (" + "; ".join(top["signs"]) + ")"
    elif len(ranked) > 1:
        why += " (listed first in the record; nothing else in it tells the occupations apart)"
    also: list[str] = []                                  # the other roles, without variants of one already said ("film actor")
    for r in ranked[1:]:
        o = str(r["occupation"])
        if not any(x.lower() in o.lower() for x in [str(top["occupation"])] + also) and len(also) < 5:
            also.append(o)
    return {"best": top["occupation"], "role": role, "also": also, "ranked": ranked[:8], "why": why}


def identity(subject: str, facts: list[dict], kind: str) -> str:
    """who or what it is, in a sentence or two, from its own facts — its description when the store holds one, else built
    from what it is an instance of, what it does, and its dates and places. Nothing is added that a fact does not say."""
    name = clean(subject)
    desc = first(facts, "description")
    news = sorted(clean(f.get("object")) for f in facts if str(f.get("predicate") or "").lower() == "in the news")
    if news and not desc and kind != "human":
        # a name printed in old newspapers (the news lattice): said as exactly that — a name as printed, not a known person
        years = sorted({year(x[:10]) for x in news if year(x[:10])})
        span = years[0] if len(years) == 1 else "%s to %s" % (years[0], years[-1]) if years else ""
        out = "%s — a name printed in American newspapers%s: %d mention%s held. It is a name as printed, not matched to a person; several people can share it." % (
            name, " in " + span if span else "", len(news), "" if len(news) == 1 else "s")
        for x in news[:3]:
            bits = x.split(" — ")
            if len(bits) >= 3:
                out += " %s: %s (%s)." % (bits[0], bits[2], bits[1])
        return out
    if kind == "human":
        born, died = first(facts, "date of birth"), first(facts, "date of death")
        span = (" (%s–%s)" % (year(born), year(died))) if year(born) and year(died) else (" (born %s)" % year(born)) if year(born) else ""
        known = known_for(facts)
        jobs = ([str(known["best"])] + [str(x) for x in known["also"]])[:3] if known["best"] else []
        nat = first(facts, "country of citizenship")
        what = desc or (", ".join(jobs) + (" from " + nat if nat else "") if jobs else "")
        out = name + span + (" — " + what if what else "") + "."
        if known["best"] and known["also"]:               # several occupations: say which one the world knows
            out += " Best known as %s%s; also %s." % (a_an(str(known["role"] or known["best"])) if not known["role"] else str(known["role"]),
                                                     "", ", ".join(str(x) for x in known["also"][:4]))
        bp, dp = first(facts, "place of birth"), first(facts, "place of death")
        if born:
            out += " Born %s%s." % (born, " in " + bp if bp else "")
        if died:
            out += " Died %s%s." % (died, " in " + dp if dp else "")
        teams = dated(facts, "member of sports team", 4)
        if teams:
            out += " Played for %s." % ", ".join(teams)
        roles = dated(facts, "position held", 4)
        if roles:
            out += " Held the position of %s." % ", ".join(roles)
        works = several(facts, "notable work", 3)
        if works:
            out += " Known for %s." % ", ".join(works)
        return out
    what = desc or first(facts, "instance of")
    where = first(facts, "located in the administrative territorial entity") or first(facts, "location")
    country = first(facts, "country")
    when = first(facts, "inception") or first(facts, "point in time") or first(facts, "start time") or first(facts, "publication date")
    out = name + (" — " + (what if desc else a_an(what)) if what else "")
    place = ", ".join(x for x in dict.fromkeys((where, country)) if x)
    if place and place.lower() not in out.lower():
        out += " in " + place
    out += "."
    if when:
        out += " %s: %s." % ("Date" if kind == "event" else "Since" if kind in ("organization", "place") else "From", when)
    about = first(facts, "depicts") or first(facts, "main subject") or first(facts, "named after")
    if about and about.lower() != name.lower():
        out += " It is about %s." % about
    return out


def answer_for(question: str, subject: str, entities: list[dict], facts: list[dict]) -> dict:
    """the whole judgement for one question: the match meant, its facts in telling order, and what to say.
    Returns {"entity": choose(...), "facts": [...], "said": str, "missing": str}. missing: set when QueryBook holds nothing,
    or only things ABOUT the subject (the card, not the man) — the honest thing to say, and the signal to go and fetch it."""
    pick = choose(question, entities, facts)
    if not pick["subject"]:
        return {"entity": pick, "facts": [], "said": "", "missing": "QueryBook holds no record of “%s” yet." % subject}
    mine = arrange(group(facts).get(pick["subject"]) or [], pick["kind"])
    said = identity(pick["subject"], mine, pick["kind"])
    missing = ""
    want = expects(question)
    if pick["only_about"] or (want and pick["kind"] not in want and pick["kind"] in ABOUT_KINDS):
        missing = ("QueryBook holds %s named “%s”, but no record of the %s itself yet." % (
            KIND_WORD.get(pick["kind"], "a thing"), clean(pick["subject"]), "person" if "human" in want else "subject"))
    known = known_for(mine) if pick["kind"] == "human" else {}
    ident = identity_state(pick["subject"], mine)
    # the "we don't know" zone: the same name printed in newspapers, kept APART from the known subject — never merged by name
    apart = [e for e in entities if str(e.get("subject") or "") != pick["subject"] and clean(e.get("subject")).lower() == clean(pick["subject"]).lower()
             and identity_state(str(e.get("subject") or ""), group(facts).get(str(e.get("subject") or "")) or [])["state"] == "unresolved"]
    zone = {}
    if apart and ident["state"] == "resolved":
        n = sum(int(e.get("facts") or 0) for e in apart)
        zone = {"name": clean(apart[0]["subject"]), "mentions": n,
                "why": "The name “%s” is also printed in newspapers (%d mention%s held). Those are unresolved: they may be this %s or someone else of the name." % (
                    clean(apart[0]["subject"]), n, "" if n == 1 else "s", "person" if pick["kind"] == "human" else "subject")}
        if pick["kind"] == "human":                       # each mention weighed against the person's own facts — shown, never merged
            news = [f for e in apart for f in group(facts).get(str(e.get("subject") or "")) or [] if str(f.get("predicate") or "").lower() == "in the news"]
            w = weigh_mentions(news, mine)
            if w["of"]:
                zone["weighed"] = w
                zone["why"] += " " + w["say"] + " They are kept apart from the record either way."
    return {"entity": pick, "facts": mine, "said": said, "missing": missing, "known_for": known, "identity": ident, "unresolved": zone}
