"""Names in the news — the extractor of the news lattice (qbbulk.NewsNames).

The user: "harvest all names recorded in daily news publications from America's newspaper archives; I want to record the
reason they were in the news, time, date, etc."

The text is the machine reading (OCR) of old newspaper pages: no punctuation, broken words, stray letters. This module
finds people's names in it by rule and says why each was in the news — from the words printed around the name, nothing
else. It is pure (no network, no store) so it can be tested on text and ported.

What it claims, and what it does not:
  - a NAME AS PRINTED is recorded: "Harvey Jordan". It is not matched to a person. Two men of one name are one name here.
  - the REASON is a label for the words around the name ("to speak", "died", "arrested or tried, as reported"); the
    paper's own words are kept beside it so the label can be checked. A report of an arrest or a charge is a report, not
    a finding: the label always says "as reported".
  - a name is kept only when it is shaped like one: a title or a known given name, then a surname. Much is missed on
    purpose; what is kept should be a name.
"""
from __future__ import annotations

import re

# titles that announce a person; (as printed, how it is written out, is it an office that may stand with a surname alone)
TITLES: dict[str, tuple[str, bool]] = {
    "mr": ("Mr.", False), "mrs": ("Mrs.", False), "miss": ("Miss", False), "messrs": ("", False), "dr": ("Dr.", True), "rev": ("Rev.", True),
    "hon": ("Hon.", True), "gen": ("Gen.", True), "general": ("Gen.", True), "col": ("Col.", True), "colonel": ("Col.", True),
    "maj": ("Maj.", True), "major": ("Maj.", True), "capt": ("Capt.", True), "captain": ("Capt.", True), "lieut": ("Lieut.", True),
    "lieutenant": ("Lieut.", True), "sergt": ("Sgt.", True), "sergeant": ("Sgt.", True), "sen": ("Senator", True), "senator": ("Senator", True),
    "gov": ("Governor", True), "governor": ("Governor", True), "pres": ("President", True), "president": ("President", True),
    "judge": ("Judge", True), "justice": ("Justice", True), "mayor": ("Mayor", True), "prof": ("Prof.", True), "professor": ("Prof.", True),
    "sheriff": ("Sheriff", True), "bishop": ("Bishop", True), "father": ("Father", False), "congressman": ("Congressman", True),
    "representative": ("Representative", True), "secretary": ("Secretary", True), "admiral": ("Admiral", True), "commodore": ("Commodore", True),
    "supt": ("Supt.", True), "superintendent": ("Supt.", True), "detective": ("Detective", True), "officer": ("Officer", True),
    "alderman": ("Alderman", True), "attorney": ("Attorney", True), "coroner": ("Coroner", True), "deputy": ("Deputy", True),
    "postmaster": ("Postmaster", True), "elder": ("Elder", True), "pastor": ("Pastor", True), "dean": ("Dean", True), "chief": ("Chief", True),
    "king": ("King", True), "queen": ("Queen", True), "prince": ("Prince", True), "princess": ("Princess", True), "lord": ("Lord", True),
    "sir": ("Sir", False), "lady": ("Lady", False), "madame": ("Madame", False), "mme": ("Mme.", False), "commissioner": ("Commissioner", True),
    "councilman": ("Councilman", True), "constable": ("Constable", True), "marshal": ("Marshal", True), "ambassador": ("Ambassador", True),
    "minister": ("Minister", True), "cardinal": ("Cardinal", True), "pope": ("Pope", True), "czar": ("Czar", True), "emperor": ("Emperor", True),
    "speaker": ("Speaker", True), "chairman": ("Chairman", True), "treasurer": ("Treasurer", True), "auditor": ("Auditor", True),
    "engineer": ("Engineer", False), "conductor": ("Conductor", False), "editor": ("Editor", True), "principal": ("Principal", True),
}
GIVEN = frozenset(
    "aaron abel abner abraham adam adolph albert alexander alfred allen alonzo alvin ambrose amos andrew anthony anton archibald arthur asa "
    "august augustus benjamin bernard bert calvin carl cecil charles chester christian clarence claude clyde cornelius cyrus daniel david "
    "dennis donald douglas earl edgar edmund edward edwin eli elias elijah elmer emil emmett enoch ernest eugene everett ezra felix "
    "ferdinand floyd francis frank franklin fred frederick george gilbert glenn grover gustave guy harold harry harvey henry herbert "
    "herman homer horace howard hugh hugo ira isaac israel jacob james jasper jerome jesse joel john jonathan joseph joshua julius "
    "kenneth lawrence lee leo leon leonard leroy leslie levi lewis lloyd louis luther mark marshall martin matthew max michael milton "
    "morris moses nathan nathaniel nelson nicholas noah norman oliver oscar otto owen patrick paul perry peter philip ralph raymond "
    "reuben richard robert roger roy rudolph rufus russell samuel sidney silas simon solomon stanley stephen sylvester theodore thomas "
    "timothy ulysses victor vincent virgil walter warren wesley wilbur wilfred will willard william willis woodrow zachariah "
    "ada adelaide agnes alice alma amanda amelia amy anna anne annie augusta barbara beatrice bertha bessie blanche caroline carrie "
    "catherine charlotte clara cora daisy delia dora dorothy edith edna eleanor eliza elizabeth ella ellen elsie emily emma esther "
    "ethel etta eva evelyn fannie flora florence frances georgia gertrude grace hannah harriet hattie hazel helen henrietta ida irene "
    "isabel isabella jane jennie jessie josephine julia kate katherine laura lena lillian lillie louisa louise lucy lula lydia mabel "
    "maggie mamie margaret maria marie marion martha mary matilda maud maude may mildred minnie mollie myrtle nancy nellie nettie nora "
    "olive pauline pearl rachel rebecca rosa rose ruth sadie sallie sarah sophia stella susan susie viola virginia winifred".split())
# words that look like a surname in old print and are not one
NOT_SURNAME = frozenset(
    "january february march april may june july august september october november december monday tuesday wednesday thursday friday "
    "saturday sunday street avenue county city state states united company co bros brothers sons church school court house senate "
    "congress bank hotel railroad railway river lake island north south east west new york washington america american union national "
    "the and for with from that this was were has have had his her their our your who whom which will would said says told made went "
    "came left took gave died born last next first second third fourth one two three four five six seven eight nine ten per cent "
    "esq jr sr inc ltd dept department committee association society club board office store shop mill mine farm ranch home hall "
    "building block road bridge park square station depot port fort mount saint san los las santa des del "
    "roosevelts mckinleys day night week month year years time today yesterday tomorrow morning evening afternoon noon "
    "general president governor judge mayor senator doctor colonel captain major "
    "jan feb mar apr jun jul aug sep sept oct nov dec weather bureau strike attempts sworn inaugurated administers passes event social "
    "hearing speech takes oath election session meeting report bill law order news notes notice sale price prices market wanted lost "
    "found rent free cash goods stock trade works line service system power light water gas ice coal oil land lands lot lots acres "
    "editor manager publisher proprietor agent dentist attorney physician surgeon druggist grocer dealer clerk cashier "
    "tells says asks urges calls names wins loses dies kills holds makes takes gets gives finds sees opens closes plans seeks faces "
    "back down over under after before again still also only just even ever never very much many most some more less than then when "
    "where while what whose there here they them these those been being into upon about above below between against during without "
    "message letter statement telegram interview article story column page edition issue paper press times herald journal gazette "
    "tribune post sun star globe record review register courier dispatch democrat republican independent bulletin chronicle".split())
NOT_SURNAME = NOT_SURNAME | frozenset(
    "alabama alaska arizona arkansas california colorado connecticut delaware florida georgia hawaii idaho illinois indiana iowa kansas "
    "kentucky louisiana maine maryland massachusetts michigan minnesota mississippi missouri montana nebraska nevada hampshire jersey "
    "mexico carolina dakota ohio oklahoma oregon pennsylvania rhode tennessee texas utah vermont virginia wisconsin wyoming canada england "
    "france germany russia japan china spain italy ireland scotland europe africa asia chicago boston philadelphia baltimore denver "
    "detroit cleveland cincinnati pittsburgh louisville memphis atlanta richmond seattle portland omaha".split())
NOT_INITIALS = frozenset(("u s", "d c", "p o", "n y", "u s a", "r r", "s s", "a m", "p m", "n c", "s c", "n j", "n h", "r i", "w va", "u s s", "y m c", "b c", "a d"))
BAD_END = ("ed", "ing", "tion", "ment", "ness", "ly", "ous", "ive")
INITIAL = re.compile(r"^[A-Z]$")
CAP = re.compile(r"^[A-Z][a-z]{2,}(?:[-'][A-Z]?[a-z]+)?$|^(?:Mc|Mac|O'|De|Van|Von|La|Le|St)[A-Z][a-z]+$")
ALLCAP = re.compile(r"^[A-Z]{3,}$")

# why a name was in the news: (label, the words that say so). The nearest such word to the name gives the reason.
REASONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("died", ("died", "dead", "death", "funeral", "buried", "burial", "obituary", "deceased", "passed", "drowned", "killed", "suicide", "remains", "widow")),
    ("arrested or tried, as reported", ("arrested", "arrest", "charged", "indicted", "accused", "convicted", "sentenced", "guilty", "jail", "trial",
                                         "prisoner", "robbery", "murder", "murdered", "assault", "burglary", "larceny", "stole", "stolen", "shot", "stabbed",
                                         "pleaded", "acquitted", "warrant", "detectives", "police")),
    ("married", ("married", "marriage", "wedding", "bride", "groom", "wed", "betrothed", "engagement", "nuptials")),
    ("born", ("born", "birth", "christened", "baptized")),
    ("elected or appointed", ("elected", "election", "appointed", "appointment", "nominated", "nomination", "candidate", "inaugurated", "inauguration",
                              "sworn", "reelected", "confirmed", "resigned", "resignation", "succeeds", "successor", "delegate")),
    ("spoke", ("speak", "spoke", "speaks", "speech", "address", "addressed", "lecture", "lectured", "sermon", "preached", "preach", "oration", "remarks")),
    ("travelled or visited", ("visited", "visiting", "visit", "arrived", "returned", "guest", "guests", "sailed", "trip", "journey", "left", "leaves",
                              "spent", "vacation", "tour")),
    ("in court or a legal matter", ("suit", "sued", "court", "verdict", "judgment", "estate", "administrator", "executor", "petition", "divorce",
                                    "plaintiff", "defendant", "testified", "testimony", "witness", "injunction", "probate")),
    ("hurt or in an accident", ("injured", "injury", "accident", "hurt", "wreck", "wrecked", "burned", "fire", "explosion", "fell", "collision", "wounded")),
    ("ill", ("ill", "illness", "sick", "hospital", "recovering", "operation", "fever", "pneumonia", "improving")),
    ("in business", ("purchased", "bought", "sold", "sale", "opened", "firm", "partnership", "contract", "store", "company", "business", "invested",
                     "proprietor", "manager", "bankrupt")),
    ("won or was honoured", ("won", "winner", "prize", "champion", "defeated", "awarded", "medal", "honor", "honored", "victory", "record")),
    ("in military service", ("regiment", "enlisted", "promoted", "commanded", "troops", "battle", "army", "navy", "soldier", "wounded", "captured")),
    ("in church or school", ("pastor", "ordained", "church", "congregation", "graduated", "graduate", "teacher", "pupil", "school", "college", "university")),
    ("entertained or performed", ("entertained", "party", "reception", "dinner", "concert", "sang", "played", "performance", "recital", "ball", "dance")),
)
CUE: dict[str, str] = {w: label for label, words in REASONS for w in words}
WINDOW = 14


def _cap(tok: str) -> str:
    """a token as a name part: 'JORDAN' -> 'Jordan', 'Jordan' -> 'Jordan'; '' when it is not shaped like one"""
    t = tok.strip(".,;:()[]\"'“”‘’")
    t = re.sub(r"['’]s$", "", t)                        # "Heath's" names Heath
    if CAP.match(t):
        return t
    if ALLCAP.match(t):
        return t[0] + t[1:].lower()
    return ""


def surname_like(word: str) -> bool:
    """is this token shaped like a surname? — a vowel, no long run of consonants (broken machine reading), not an everyday
    word, not ending as verbs and abstract nouns do"""
    w = word.lower()
    if len(w) < 3 or w in NOT_SURNAME or w in TITLES or w.endswith(BAD_END):
        return False
    if not re.search(r"[aeiouy]", w) or re.search(r"[^aeiouy]{5}", w) or re.search(r"(.)\1\1", w):
        return False
    return True


def mentions(text: str) -> list[dict]:
    """the names in a page's text: [{"name", "title", "reason", "context", "at": token index}] — one per name and reason on
    the page (a name printed five times for one reason is one mention). Order: as printed."""
    toks = text.split()
    low = [t.strip(".,;:()[]\"'").lower() for t in toks]
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    i, n = 0, len(toks)
    while i < n:
        title = TITLES.get(low[i]) if toks[i][:1].isupper() else None
        j = i + 1 if title else i
        parts: list[str] = []
        k = j
        # initials and a given name, then the surname:  [A] [M] Shelby | Harvey Jordan | E G Tutt | John W Smith
        while k < n and len(parts) < 4:
            t = toks[k].strip(".,;:()[]\"'")
            if INITIAL.match(t) and (parts or title or (k + 1 < n and (INITIAL.match(toks[k + 1].strip(".")) or _cap(toks[k + 1])))):
                parts.append(t + ".")
                k += 1
                continue
            c = _cap(toks[k])
            if c and c.lower() not in NOT_SURNAME and c.lower() not in TITLES:
                parts.append(c)
                k += 1
                if len(parts) >= 2 and not c.endswith(".") and not (k < n and INITIAL.match(toks[k].strip(".")) and len(parts) < 3):
                    nxt = _cap(toks[k]) if k < n else ""
                    if not (nxt and parts[-1].lower() in GIVEN and nxt.lower() not in NOT_SURNAME):
                        break
                continue
            break
        # a title before two capitalised words that are not given name + surname ("Judge Robinson Hearing", "Justice Fuller
        # Fairbanks"): the first is the surname, the second is the next thing on the page
        if title and len(parts) >= 2 and not parts[0].endswith(".") and parts[0].lower() not in GIVEN:
            parts, k = parts[:1], j + 1
        inits = " ".join(p[0].lower() for p in parts if p.endswith("."))
        if (inits in NOT_INITIALS and not (title and inits in ("a m", "p m", "b c", "a d", "s s", "r r"))) or sum(1 for p in parts if p.endswith(".")) > 3:
            parts = []
        named = [p for p in parts if not p.endswith(".")]
        surname = parts[-1] if parts and not parts[-1].endswith(".") else ""
        if surname and not surname_like(surname):
            surname = ""
        first_given = bool(named) and named[0].lower() in GIVEN
        ok = False
        if surname and len(parts) >= 2 and (title or first_given or parts[0].endswith(".")):
            ok = True                                   # Mr A M Shelby | Harvey Jordan | E G Tutt (two initials or a title)
            if not title and not first_given and sum(1 for p in parts if p.endswith(".")) < 2:
                ok = False                              # "A Shelby" alone is too little to be sure of
        elif surname and len(parts) == 1 and title and title[1] and len(surname) >= 4:
            ok = True                                   # Judge Robinson | Senator Smith: an office and a surname
        if ok and surname.lower() not in GIVEN or (ok and len(parts) >= 2):
            name = " ".join(parts)
            shown = (title[0] + " " + name).strip() if title and (len(parts) == 1) else name
            a, b = max(0, i - WINDOW), min(n, k + WINDOW)
            reason, best = "mentioned", WINDOW + 1
            for x in range(a, b):
                lab = CUE.get(low[x])
                if lab:
                    d = (i - x) if x < i else (x - k + 1) if x >= k else 0
                    if d < best:
                        reason, best = lab, d
            key = (shown.lower(), reason)
            if key not in seen:
                seen.add(key)
                out.append({"name": shown, "title": title[0] if title else "", "reason": reason,
                            "context": " ".join(toks[max(0, i - 10):min(n, k + 16)])[:240], "at": i})
            i = k
            continue
        i += 1
    return out


def paper_of(title: str) -> str:
    """'Image 1 of The Greenville times (Greenville, Miss.), March 4, 1905' -> 'The Greenville times (Greenville, Miss.)'"""
    m = re.match(r"^Image \d+ of (.+?),\s+[A-Z][a-z]+ \d{1,2}, \d{4}", title or "")
    return m.group(1).strip() if m else re.sub(r"^Image \d+ of ", "", title or "").strip()


def fact_object(date: str, paper: str, page: int, mention: dict) -> str:
    """what is recorded for one mention: the date first (so mentions sort in time), the paper and page, the reason, and the
    paper's own words"""
    return "%s — %s, p. %d — %s — “%s”" % (date, paper, page, mention["reason"], mention["context"])


def text_address(image_url: str) -> str:
    """the address of a page's whole machine-read text, from the address of its image as the archive lists it:
    '…/iiif/service:ndnp:msar:batch_x:data:sn85034374:00295877728:1905030401:0035/full/…' ->
    '/service/ndnp/msar/batch_x/data/sn85034374/00295877728/1905030401/0035.xml'; '' when the image is not of that kind"""
    m = re.search(r"/iiif/(service:ndnp:[A-Za-z0-9_:.-]+)/", image_url or "")
    return "/" + m.group(1).replace(":", "/") + ".xml" if m else ""
