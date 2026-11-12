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
        exact = 150.0 if e.get("exact", True) else 0.0
        score = (1000.0 if want and k in want else 0.0) + (0.0 if about else 300.0) + exact + 60.0 * math.log10(1.0 + views) \
            + 6.0 * min(fame, 150.0) + 40.0 * math.log10(1.0 + n)
        said = next((clean(f.get("object")) for f in fs if str(f.get("predicate") or "").lower() == "description"), "") or \
            next((clean(f.get("object")) for f in fs if str(f.get("predicate") or "").lower() in ("instance of", "occupation")), "")
        ranked.append({"subject": s, "kind": k, "about": about, "score": round(score, 1), "fame": e.get("fame"), "views": e.get("views"),
                       "facts": int(n), "what": said, "exact": bool(e.get("exact", True))})
    ranked.sort(key=lambda r: (-r["score"], r["subject"]))
    if not ranked:
        return {"subject": "", "kind": "", "why": "", "ranked": [], "only_about": False}
    top = ranked[0]
    only_about = bool(top["about"]) and not any(not r["about"] for r in ranked)
    why = "%s is %s" % (clean(top["subject"]), KIND_WORD.get(top["kind"], "a thing"))
    if not top.get("exact", True):
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


def year(value: str) -> str:
    m = YEAR.search(value or "")
    return m.group(1) if m else ""


def a_an(phrase: str) -> str:
    return ("an " if phrase[:1].lower() in "aeiou" else "a ") + phrase


def identity(subject: str, facts: list[dict], kind: str) -> str:
    """who or what it is, in a sentence or two, from its own facts — its description when the store holds one, else built
    from what it is an instance of, what it does, and its dates and places. Nothing is added that a fact does not say."""
    name = clean(subject)
    desc = first(facts, "description")
    if kind == "human":
        born, died = first(facts, "date of birth"), first(facts, "date of death")
        span = (" (%s–%s)" % (year(born), year(died))) if year(born) and year(died) else (" (born %s)" % year(born)) if year(born) else ""
        jobs = several(facts, "occupation")
        nat = first(facts, "country of citizenship")
        what = desc or (", ".join(jobs) + (" from " + nat if nat else "") if jobs else "")
        out = name + span + (" — " + what if what else "") + "."
        bp, dp = first(facts, "place of birth"), first(facts, "place of death")
        if born:
            out += " Born %s%s." % (born, " in " + bp if bp else "")
        if died:
            out += " Died %s%s." % (died, " in " + dp if dp else "")
        teams = several(facts, "member of sports team", 4)
        if teams:
            out += " Played for %s." % ", ".join(teams)
        roles = several(facts, "position held", 3)
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
    return {"entity": pick, "facts": mine, "said": said, "missing": missing}
