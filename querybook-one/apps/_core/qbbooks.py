"""The Book Harvester — the Harvesting Engine's library of books and documents for Book Query.

SOURCE -> Harvester -> Rights gate -> Metadata -> Format normalizer -> Document structure -> Fact Units -> QueryBook

Sources (SOURCES):
  1 Project Gutenberg     automated: the machine-readable catalog (pg_catalog.csv.gz), filtered by type, language, subject
                          and bookshelf, ranked by downloads (the OPDS search); plain text per book
  2 Internet Archive      scanned documents: the advanced-search API, the item's OCR text (_djvu.txt); rights are judged
                          from the publication date, never from the item's licence field (it labels Gutenberg texts "GPL")
  3 HathiTrust            research track: bulk access is for approved noncommercial research; volumes you are licensed to
                          use are imported from a local folder, and their Rights Record says so
  4 Standard Ebooks       selective: one book at a time by its address (bulk downloads are a Patrons Circle benefit); EPUB
  5 Government and other  one document at a time by its address (HTML or plain text), with the rights the admin declares
                          (a U.S. federal work is public domain under 17 U.S.C. § 105)

Every book gets a Rights Record kept apart from its content: work, author, source, source id and address, original
publication, rights status, territory, source file (address, format, size, SHA-256), ingestion date, transformation
(normaliser, parser version, OCR) and human review. Anything whose rights are not clear is HELD for review, not ingested.
Authors on the block list (Darwin, at the user's request) are never harvested.

The books are written to <data folder>/library/<id>/ in the same form as the bundled library (meta.json, text.txt.gz,
book.json.gz) and listed in its catalog.json; the one window's Book Query reads both. Standard library only.
"""
import csv, gzip, hashlib, html.parser, io, json, os, re, threading, time, urllib.parse, urllib.request, zipfile

import bookq

VERSION = "1.0.0"
UA = "QueryBook-BookHarvester/1.0 (public-domain library builder)"
PACE_S = 2.0                                  # seconds between two downloads from one site (Project Gutenberg asks for restraint)
CATALOG_MAX_AGE_S = 7 * 24 * 3600
MIN_CHARS = 20000                             # shorter texts are pamphlets, indexes or fragments: held, not ingested
PD_YEAR = 1930                                # published in or before this year: public domain in the USA (as of 2026)
BLOCKED_AUTHORS = ["Darwin, Charles"]         # the user's decision: nothing by Darwin

SOURCES = [
    {"id": "gutenberg", "name": "Project Gutenberg", "class": "ebook", "status": "active", "priority": 1,
     "scale": "79,000+ ebooks", "access": "Machine-readable catalog, OPDS search ranked by downloads, plain text per book",
     "rights": "Public domain in the USA; a book marked 'copyrighted' in its header is refused",
     "use": "The main library: automated discovery and harvesting"},
    {"id": "internet-archive", "name": "Internet Archive", "class": "scanned document (OCR)", "status": "active", "priority": 2,
     "scale": "Millions of scanned books and documents", "access": "Advanced-search API; the item's OCR text",
     "rights": "Ingested only when published in or before %d; otherwise held for review (the item's licence field is not trusted)" % PD_YEAR,
     "use": "Scanned historical books and documents: OCR text -> structure -> Fact Units"},
    {"id": "hathitrust", "name": "HathiTrust", "class": "research corpus", "status": "research only", "priority": 3,
     "scale": "Over 800,000 public-domain volumes in its research datasets", "access": "Approved noncommercial research access; then import the volumes from a folder",
     "rights": "Licensed for noncommercial research — recorded in every Rights Record; not for a commercial demonstration",
     "use": "Large-scale research experiments"},
    {"id": "standard-ebooks", "name": "Standard Ebooks", "class": "curated ebook (EPUB)", "status": "by address", "priority": 4,
     "scale": "About 1,000 carefully produced editions", "access": "One book at a time by its address (bulk ZIPs are for Patrons Circle members)",
     "rights": "Public-domain texts; the editions are dedicated to the public domain (CC0)",
     "use": "High-quality demonstration editions"},
    {"id": "government", "name": "Government and other public documents", "class": "document (HTML / text)", "status": "by address", "priority": 5,
     "scale": "Specialised authoritative documents", "access": "One document at a time by its address, with the rights the admin declares",
     "rights": "As declared: e.g. a U.S. federal government work is public domain (17 U.S.C. § 105); 'unknown' is held for review",
     "use": "Government, law, science and technical facts"},
]
RIGHTS_CHOICES = ["public domain in the USA", "U.S. federal government work (17 U.S.C. § 105)", "CC0 / public-domain dedication",
                  "licensed (open licence)", "licensed for noncommercial research", "unknown"]
PHASES = {
    "phase1": {"name": "Phase 1 — 100 books", "per_subject": 10,
               "subjects": ["History", "Science", "Philosophy", "Economics", "Politics", "Biography", "Literature",
                            "Detective and mystery stories", "Science fiction", "Children's literature"]},
    "phase2": {"name": "Phase 2 — 1,000 books", "per_subject": 100,
               "subjects": ["History", "Science", "Philosophy", "Economics", "Politics", "Biography", "Literature",
                            "Detective and mystery stories", "Science fiction", "Children's literature"]},
}


# --------------------------------------------------------------------------- where things live
def library_dir(commons_folder):
    """<data folder>/library — beside the commons (the commons folder is <data>/commons, or the data folder itself)"""
    c = os.path.abspath(commons_folder)
    return os.path.join(os.path.dirname(c) if os.path.basename(c).lower() == "commons" else c, "library")


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# --------------------------------------------------------------------------- building a book (shared with tools/build_library.py)
def fingerprint(book_id, u):
    """a Fact Unit's identity: its book, anchor and normalised text (sha256, first 16 hex)"""
    key = "%s|%d|%d|%d|%d|%s" % (book_id, u["chapter"], u["section"], u["para"], u["n"], " ".join(u["text"].split()).lower())
    return "FU-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def assemble(meta, text, modern=None):
    """meta.json + the text (+ modern.json) -> the book.json document (a string; deterministic)"""
    chapters = bookq.parse(text, meta["rules"])
    units, sections = [], {}
    for c in chapters:
        for p in c["paragraphs"]:
            if p["section"] and p["section_title"]:
                sections.setdefault(str(p["section"]), p["section_title"])
            for u in bookq.atomize(c, p):
                u["id"] = fingerprint(meta["id"], u)
                units.append(u)
    rows, new_since = [], []
    if modern:
        new_since = modern.get("new_since") or []
        for e in modern.get("entries") or []:
            idx = []
            for pat in e["match"]:
                r = re.compile(pat)
                found = [i for i, u in enumerate(units) if r.search(u["text"])]
                if not found:
                    raise ValueError("%s: modern entry %r: no sentence of the book matches %r" % (meta["id"], e["id"], pat))
                idx += [i for i in found[:6] if i not in idx]
            row = {k: v for k, v in e.items() if k != "match"}
            row["units"] = idx
            row["unit_ids"] = [units[i]["id"] for i in idx]
            rows.append(row)
    people = bookq.mentions(units, meta.get("characters") or [])
    known = [c["name"] for c in meta.get("characters") or []] + [a for c in meta.get("characters") or [] for a in c.get("aliases") or []]
    editorial = set(meta["rules"].get("editorial") or [])
    book = {k: v for k, v in meta.items() if k not in ("characters", "rules")}
    book.update({"chapters": [{"n": c["n"], "label": c["label"], "title": c["title"], "part": c["part"], "editorial": c["label"] in editorial,
                               "paragraphs": len(c["paragraphs"]), "figures": len(c["figures"])} for c in chapters],
                 "sections": sections, "units": units, "modern": rows, "new_since": new_since,
                 "people": people, "edges": bookq.network(units, people, 400),
                 "names": bookq.other_names(units, known, 200), "years": bookq.years(units, 6000),
                 "built_from": {"text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "units": len(units)}})
    return json.dumps(book, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"


def write_book(lib, meta, text):
    """one harvested book into <library>/<id>/: meta.json (with its Rights Record), text.txt.gz, book.json.gz"""
    folder = os.path.join(lib, meta["id"])
    os.makedirs(folder, exist_ok=True)
    data = assemble(meta, text)
    with gzip.GzipFile(os.path.join(folder, "text.txt.gz"), "wb", mtime=0) as g:
        g.write(text.encode("utf-8"))
    tmp = os.path.join(folder, "book.json.gz.tmp")
    with gzip.GzipFile(tmp, "wb", mtime=0) as g:
        g.write(data.encode("utf-8"))
    os.replace(tmp, os.path.join(folder, "book.json.gz"))
    with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    card = bookq.overview(json.loads(data))
    card.pop("chapters", None)
    card["rights_record"] = meta.get("rights_record")
    return card


def write_catalog(lib):
    """<library>/catalog.json: one card per harvested book (the one window lists them beside the bundled books)"""
    cards = []
    for name in sorted(os.listdir(lib)) if os.path.isdir(lib) else []:
        bp = os.path.join(lib, name, "book.json.gz")
        mp = os.path.join(lib, name, "meta.json")
        if not (os.path.isfile(bp) and os.path.isfile(mp)):
            continue
        try:
            with open(mp, encoding="utf-8") as f:
                meta = json.load(f)
            card = meta.get("card")
            if not card:
                with gzip.open(bp, "rb") as f:
                    card = bookq.overview(json.loads(f.read().decode("utf-8")))
                card.pop("chapters", None)
            card = dict(card, rights_record=meta.get("rights_record"), harvested=True)
            cards.append(card)
        except (OSError, ValueError, KeyError):
            continue
    cards.sort(key=lambda c: (0 if c.get("kind") == "nonfiction" else 1, c.get("title") or ""))
    os.makedirs(lib, exist_ok=True)
    tmp = os.path.join(lib, "catalog.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"books": cards}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(lib, "catalog.json"))
    return cards


def rights_record(work, author, source, source_id, url, published, status, territory, fmt, raw, normaliser, ocr=False):
    return {"work": work, "author": author, "source": source, "source_id": str(source_id), "source_url": url,
            "original_publication": published or "not recorded by the source", "rights_status": status, "territory": territory,
            "source_file": {"url": url, "format": fmt, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
            "ingested": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "transformation": {"normaliser": normaliser, "parser": "bookq (QueryBook Book Harvester %s)" % VERSION, "ocr": bool(ocr)},
            "human_review": {"status": "not reviewed", "by": "", "at": ""}}


def choose_rules(text):
    """the structure rules for a harvested text: the detected headings, unless they make an absurd chapter (an OCR scan's
    running heads or page numbers taken for headings) — then numbered sections of 60 paragraphs"""
    rules = bookq.auto_rules(text)
    chs = bookq.parse(text, rules)
    if rules["chapters"] and (len(chs) < 2 or max(len(c["paragraphs"]) for c in chs) > 600):
        rules = dict(rules, chapters=[], parts=[])
    return rules


def kind_from_subjects(subjects):
    s = (subjects or "").lower()
    return "fiction" if re.search(r"fiction|novel|stories|tales|drama|poetry|juvenile|fairy", s) else "nonfiction"


def blocked(author, extra=()):
    a = (author or "").lower()
    return any(b.lower().split(",")[0].strip() and b.lower() in a for b in list(BLOCKED_AUTHORS) + list(extra))


# --------------------------------------------------------------------------- 1. Project Gutenberg
PG_CATALOG = "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv.gz"
PG_OPDS = "https://www.gutenberg.org/ebooks/search.opds/?query=%s&sort_order=downloads&start_index=%d"
PG_TEXT = "https://www.gutenberg.org/cache/epub/%d/pg%d.txt"
_CAT = {}


def pg_catalog(lib, refresh=False, url=PG_CATALOG):
    """Project Gutenberg's machine-readable catalog (cached under <library>/_sources, refreshed weekly)"""
    d = os.path.join(lib, "_sources")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "pg_catalog.csv.gz")
    if refresh or not os.path.exists(p) or time.time() - os.path.getmtime(p) > CATALOG_MAX_AGE_S:
        raw = _get(url, timeout=120)
        with open(p + ".tmp", "wb") as f:
            f.write(raw)
        os.replace(p + ".tmp", p)
    mt = os.path.getmtime(p)
    if _CAT.get("p") != p or _CAT.get("mt") != mt:
        with gzip.open(p, "rt", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        _CAT.update(p=p, mt=mt, rows=rows, by={r["Text#"]: r for r in rows})
    return _CAT


def pg_popular(query, n, opds=PG_OPDS):
    """book numbers for a subject, most downloaded first (the OPDS search, 25 a page)"""
    ids = []
    start = 1
    while len(ids) < n and start < 2000:
        page = _get(opds % (urllib.parse.quote(query), start), timeout=60).decode("utf-8", "replace")
        found = [int(x) for x in re.findall(r'href="/ebooks/(\d+)\.opds"', page)]
        new = [x for x in dict.fromkeys(found) if x not in ids]
        if not new:
            break
        ids += new
        start += 25
        time.sleep(PACE_S / 2)
    return ids[:n]


def have_pg(lib, bundled_dirs=()):
    """Gutenberg numbers already in the library (bundled or harvested) — never harvested twice"""
    nums = set()
    for d in [lib] + list(bundled_dirs):
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            mp = os.path.join(d, name, "meta.json")
            if os.path.isfile(mp):
                try:
                    with open(mp, encoding="utf-8") as f:
                        src = json.load(f).get("provenance", {}).get("source", "")
                    m = re.search(r"#(\d+)", src)
                    if m:
                        nums.add(int(m.group(1)))
                except (OSError, ValueError):
                    pass
    return nums


def pg_discover(lib, subjects, language="en", per_subject=10, order="popular", bundled_dirs=(), extra_blocked=(), catalog=None, opds=PG_OPDS):
    """Public-domain status -> language -> subject -> popularity -> candidates (with why each was chosen)"""
    cat = catalog or pg_catalog(lib)
    have = have_pg(lib, bundled_dirs)
    out, seen = [], set()
    for subj in subjects:
        s = subj.strip()
        if not s:
            continue
        low = s.lower().rstrip("s")
        if order == "popular":
            ranked = [str(i) for i in pg_popular(s, per_subject * 4, opds)]
            rows = [cat["by"][i] for i in ranked if i in cat["by"]]
        else:
            rows = [r for r in cat["rows"] if low in (r["Subjects"] + "; " + r["Bookshelves"]).lower()]
        taken = 0
        for rank, r in enumerate(rows):
            if taken >= per_subject:
                break
            n = int(r["Text#"])
            why = []
            if r["Type"] != "Text":
                continue
            if language and r["Language"].split(";")[0].strip() != language:
                continue
            if n in seen:
                continue
            if blocked(r["Authors"], extra_blocked):
                continue
            seen.add(n)
            out.append({"source": "gutenberg", "id": n, "title": r["Title"], "author": r["Authors"], "subject": s,
                        "subjects": r["Subjects"], "bookshelves": r["Bookshelves"], "language": r["Language"], "issued": r["Issued"],
                        "rank": rank + 1 if order == "popular" else None, "have": n in have,
                        "kind": kind_from_subjects(r["Subjects"] + " " + r["Bookshelves"])})
            if n not in have:
                taken += 1
    return out


def pg_harvest(lib, cand, text_url=None):
    """one Gutenberg book: download, rights gate, normalise, structure, Fact Units, Rights Record"""
    n = int(cand["id"])
    url = (text_url or PG_TEXT) % (n, n)
    raw = _get(url)
    text = raw.decode("utf-8-sig", "replace")
    head = text[: text.find("*** START OF")] if "*** START OF" in text else text[:3000]
    if re.search(r"copyrighted project gutenberg", head, re.I):
        return {"held": True, "why": "the Gutenberg header marks this book as copyrighted"}
    if blocked(cand.get("author")):
        return {"held": True, "why": "author on the block list"}
    body = bookq.body(text).strip("\n") + "\n"
    if len(body) < MIN_CHARS:
        return {"held": True, "why": "too short to be a book (%d characters)" % len(body)}
    rules = choose_rules(body)
    bid = "pg-%d" % n
    meta = {"id": bid, "title": cand.get("title") or "Gutenberg #%d" % n, "author": cand.get("author") or "",
            "year": int((cand.get("issued") or "0000")[:4] or 0), "published": "not recorded (Gutenberg release %s)" % (cand.get("issued") or "?"),
            "kind": cand.get("kind") or "nonfiction", "subject": cand.get("subject") or "", "structure": "harvested automatically",
            "about": "Subjects: %s" % (cand.get("subjects") or "—"),
            "provenance": {"source": "Project Gutenberg eBook #%d" % n, "url": "https://www.gutenberg.org/ebooks/%d" % n,
                           "fetched": time.strftime("%Y-%m-%d", time.gmtime()),
                           "rights": "Public domain in the USA. This QueryBook edition keeps the public-domain text only (Project Gutenberg's header, licence and trademark removed); copyright status outside the USA can differ. Not endorsed by Project Gutenberg."},
            "text": "text.txt.gz", "rules": rules, "examples": [], "characters": [],
            "rights_record": rights_record(cand.get("title"), cand.get("author"), "Project Gutenberg", n, url, "",
                                           "public domain in the USA", "USA (elsewhere: check local law)", "text/plain", raw,
                                           "Gutenberg header and licence removed")}
    card = write_book(lib, meta, body)
    meta["card"] = card
    with open(os.path.join(lib, bid, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return {"book": bid, "units": card["units"], "chapters": len(bookq.parse(body, rules))}


# --------------------------------------------------------------------------- 2. Internet Archive (scanned documents)
IA_SEARCH = "https://archive.org/advancedsearch.php"
IA_TEXT = "https://archive.org/download/%s/%s_djvu.txt"


def ia_discover(subject, rows=20, search=IA_SEARCH, extra_blocked=()):
    q = 'subject:("%s") AND mediatype:texts AND language:(eng OR English)' % subject.replace('"', "")
    params = [("q", q), ("rows", str(rows)), ("output", "json"), ("sort[]", "downloads desc")] + \
             [("fl[]", f) for f in ("identifier", "title", "creator", "date", "year", "licenseurl", "language", "collection")]
    data = json.loads(_get(search + "?" + urllib.parse.urlencode(params), timeout=60).decode("utf-8"))
    out = []
    for d in data.get("response", {}).get("docs", []):
        creator = d.get("creator") or ""
        if isinstance(creator, list):
            creator = "; ".join(creator)
        if blocked(creator, extra_blocked):
            continue
        y = str(d.get("year") or d.get("date") or "")[:4]
        year = int(y) if y.isdigit() else 0
        out.append({"source": "internet-archive", "id": d.get("identifier"), "title": d.get("title") or d.get("identifier"),
                    "author": creator, "subject": subject, "year": year, "licenseurl": d.get("licenseurl") or "",
                    "rights": "public domain in the USA" if year and year <= PD_YEAR else "unknown",
                    "why": "published %d" % year if year else "no publication year recorded"})
    return out


def ocr_clean(text):
    """OCR text: rejoin words split at line ends, drop page numbers and running heads, keep paragraph breaks"""
    t = text.replace("\r\n", "\n").replace("\f", "\n\n")
    t = re.sub(r"(\w)-\n(\w)", r"\1\2", t)
    lines = [l for l in t.split("\n") if not re.fullmatch(r"\s*\d{1,4}\s*", l)]
    return "\n".join(lines)


def ia_harvest(lib, cand, text_url=None):
    if cand.get("rights") != "public domain in the USA":
        return {"held": True, "why": "rights unclear (%s) — held for review" % cand.get("why", "")}
    ident = cand["id"]
    url = (text_url or IA_TEXT) % (ident, ident)
    raw = _get(url, timeout=120)
    body = ocr_clean(raw.decode("utf-8", "replace")).strip("\n") + "\n"
    if len(body) < MIN_CHARS:
        return {"held": True, "why": "too short or no OCR text (%d characters)" % len(body)}
    bid = "ia-" + re.sub(r"[^a-z0-9]+", "-", ident.lower())[:60]
    meta = {"id": bid, "title": cand.get("title"), "author": cand.get("author"), "year": cand.get("year") or 0,
            "published": str(cand.get("year") or "not recorded"), "kind": "nonfiction", "subject": cand.get("subject") or "",
            "structure": "scanned document (OCR text)", "about": "Scanned by the Internet Archive; text from its OCR.",
            "provenance": {"source": "Internet Archive item %s" % ident, "url": "https://archive.org/details/%s" % ident,
                           "fetched": time.strftime("%Y-%m-%d", time.gmtime()),
                           "rights": "Public domain in the USA (published %s). OCR text; errors of recognition are possible. Not endorsed by the Internet Archive." % cand.get("year")},
            "text": "text.txt.gz", "rules": choose_rules(body), "examples": [], "characters": [],
            "rights_record": rights_record(cand.get("title"), cand.get("author"), "Internet Archive", ident, url, str(cand.get("year") or ""),
                                           "public domain in the USA", "USA (elsewhere: check local law)", "text/plain (OCR)", raw,
                                           "OCR clean-up (hyphenation, page numbers)", ocr=True)}
    meta["rights_record"]["source_licence_field"] = cand.get("licenseurl") or ""
    card = write_book(lib, meta, body)
    meta["card"] = card
    with open(os.path.join(lib, bid, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return {"book": bid, "units": card["units"]}


# --------------------------------------------------------------------------- 4 / 5. by address: EPUB (Standard Ebooks), HTML, text
class _Text(html.parser.HTMLParser):
    """HTML -> text with headings kept as '## Heading' lines (the structure engine reads them as chapters)"""
    BLOCK = {"p", "div", "br", "li", "tr", "blockquote", "section", "article", "table", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.head = [], 0, None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "header", "footer"):
            self.skip += 1
        elif tag in ("h1", "h2", "h3"):
            self.head = []
        elif tag in self.BLOCK:
            self.out.append("\n\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "header", "footer"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("h1", "h2", "h3") and self.head is not None:
            h = " ".join("".join(self.head).split())
            if h:
                self.out.append("\n\n## %s\n\n" % h)
            self.head = None
        elif tag in self.BLOCK:
            self.out.append("\n\n")

    def handle_data(self, data):
        if self.skip:
            return
        if self.head is not None:
            self.head.append(data)
        else:
            self.out.append(data)


def html_text(markup):
    p = _Text()
    p.feed(markup)
    t = "".join(p.out)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n[ \t]+", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip() + "\n"


def epub_text(raw):
    """an EPUB (zip): the reading order from its OPF spine, each XHTML document turned into text"""
    z = zipfile.ZipFile(io.BytesIO(raw))
    container = z.read("META-INF/container.xml").decode("utf-8", "replace")
    opf_path = re.search(r'full-path="([^"]+)"', container).group(1)
    opf = z.read(opf_path).decode("utf-8", "replace")
    base = os.path.dirname(opf_path)
    items = dict(re.findall(r'<item\b[^>]*\bid="([^"]+)"[^>]*\bhref="([^"]+)"', opf))
    items.update({i: h for h, i in re.findall(r'<item\b[^>]*\bhref="([^"]+)"[^>]*\bid="([^"]+)"', opf)})
    spine = re.findall(r'<itemref\b[^>]*\bidref="([^"]+)"', opf)
    parts = []
    for idref in spine:
        href = items.get(idref)
        if not href:
            continue
        name = os.path.normpath(os.path.join(base, urllib.parse.unquote(href))).replace("\\", "/")
        try:
            parts.append(html_text(z.read(name).decode("utf-8", "replace")))
        except KeyError:
            continue
    return "\n\n".join(parts)


def standard_ebooks_epub_url(page):
    """https://standardebooks.org/ebooks/jane-austen/pride-and-prejudice -> .../downloads/jane-austen_pride-and-prejudice.epub"""
    u = urllib.parse.urlsplit(page)
    path = [x for x in u.path.split("/") if x]
    if len(path) < 3 or path[0] != "ebooks":
        raise ValueError("A Standard Ebooks address looks like https://standardebooks.org/ebooks/<author>/<title>.")
    return "%s://%s/%s/downloads/%s.epub" % (u.scheme or "https", u.netloc, "/".join(path[:]), "_".join(path[1:]))


def by_address(lib, url, rights, title="", author="", source="government", year=0):
    """one document by its address: EPUB, HTML or plain text, with the rights the admin declares"""
    if rights not in RIGHTS_CHOICES:
        raise ValueError("Choose the rights status.")
    if rights == "unknown":
        return {"held": True, "why": "rights unknown — held for review; choose the rights status once known"}
    if blocked(author):
        return {"held": True, "why": "author on the block list"}
    if source == "standard-ebooks" and "standardebooks.org/ebooks/" in url and not url.endswith(".epub"):
        url = standard_ebooks_epub_url(url)
    raw = _get(url, timeout=120)
    low = url.lower().split("?")[0]
    if low.endswith(".pdf") or raw[:5] == b"%PDF-":
        return {"held": True, "why": "PDF needs text extraction or OCR, which is the next stage — use an HTML, text or EPUB version, or the Internet Archive's OCR text"}
    if low.endswith(".epub") or raw[:2] == b"PK":
        text, fmt, norm = epub_text(raw), "application/epub+zip", "EPUB spine -> text, headings kept"
    elif b"<html" in raw[:2000].lower() or low.endswith((".htm", ".html")):
        text, fmt, norm = html_text(raw.decode("utf-8", "replace")), "text/html", "HTML -> text, headings kept"
    else:
        text, fmt, norm = raw.decode("utf-8-sig", "replace"), "text/plain", "as received"
    text = bookq.body(text).strip("\n") + "\n"
    if len(text) < 2000:
        return {"held": True, "why": "too little text found (%d characters)" % len(text)}
    if not title:
        m = re.search(r"^## (.+)$", text, re.M)
        title = m.group(1) if m else os.path.basename(urllib.parse.urlsplit(url).path) or url
    bid = ("se-" if source == "standard-ebooks" else "doc-") + hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    src_name = {"standard-ebooks": "Standard Ebooks", "hathitrust": "HathiTrust"}.get(source, "Public document")
    meta = {"id": bid, "title": title, "author": author, "year": int(year or 0), "published": str(year or "not recorded"),
            "kind": "nonfiction", "subject": "", "structure": "harvested by address", "about": "From %s" % url,
            "provenance": {"source": "%s — %s" % (src_name, url), "url": url, "fetched": time.strftime("%Y-%m-%d", time.gmtime()),
                           "rights": "%s (declared by the administrator)." % rights},
            "text": "text.txt.gz", "rules": choose_rules(text), "examples": [], "characters": [],
            "rights_record": rights_record(title, author, src_name, url, url, str(year or ""), rights,
                                           "as declared", fmt, raw, norm)}
    card = write_book(lib, meta, text)
    meta["card"] = card
    with open(os.path.join(lib, bid, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return {"book": bid, "units": card["units"]}


def import_folder(lib, folder, rights, source="hathitrust"):
    """the research track: plain-text volumes you are licensed to use, from a local folder (one book per .txt file)"""
    if rights not in RIGHTS_CHOICES or rights == "unknown":
        raise ValueError("Choose the rights status under which you hold these volumes.")
    if not os.path.isdir(folder):
        raise ValueError("No such folder: %s" % folder)
    done = []
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith(".txt"):
            continue
        p = os.path.join(folder, name)
        with open(p, "rb") as f:
            raw = f.read()
        text = raw.decode("utf-8-sig", "replace").strip("\n") + "\n"
        if len(text) < MIN_CHARS:
            continue
        bid = "ht-" + re.sub(r"[^a-z0-9]+", "-", os.path.splitext(name)[0].lower())[:50]
        title = os.path.splitext(name)[0]
        meta = {"id": bid, "title": title, "author": "", "year": 0, "published": "not recorded", "kind": "nonfiction", "subject": "",
                "structure": "research volume", "about": "Imported from a local research dataset.",
                "provenance": {"source": "HathiTrust research volume %s" % title, "url": "", "fetched": time.strftime("%Y-%m-%d", time.gmtime()),
                               "rights": "%s — imported under the researcher's own HathiTrust access; noncommercial research only." % rights},
                "text": "text.txt.gz", "rules": choose_rules(text), "examples": [], "characters": [],
                "rights_record": rights_record(title, "", "HathiTrust", title, p, "", rights, "as licensed", "text/plain", raw, "as received")}
        card = write_book(lib, meta, text)
        meta["card"] = card
        with open(os.path.join(lib, bid, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        done.append(bid)
    write_catalog(lib)
    return {"imported": done}


# --------------------------------------------------------------------------- the harvesting job (background, resumable)
class Harvest:
    """A queue of candidates harvested one at a time in a background thread, two seconds apart. The state is kept in
    <library>/_harvest.json, so a restart resumes where it stopped; Stop finishes the current book first."""

    def __init__(self, lib, bundled_dirs=()):
        self.lib = lib
        self.bundled = list(bundled_dirs)
        self.lock = threading.Lock()
        self.thread = None
        self.stop_flag = False
        os.makedirs(lib, exist_ok=True)

    def _path(self):
        return os.path.join(self.lib, "_harvest.json")

    def state(self):
        try:
            with open(self._path(), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"queue": [], "done": [], "held": [], "failed": [], "log": [], "running": False, "current": None}

    def _save(self, st):
        tmp = self._path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._path())

    def add(self, cands):
        with self.lock:
            st = self.state()
            have = {(c["source"], str(c["id"])) for c in st["queue"] + st["done"]}
            added = 0
            for c in cands:
                k = (c["source"], str(c["id"]))
                if k in have or c.get("have"):
                    continue
                st["queue"].append(c)
                have.add(k)
                added += 1
            self._save(st)
        self.start()
        return added

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_flag = False
        self.thread = threading.Thread(target=self._run, daemon=True, name="qb-book-harvest")
        self.thread.start()

    def stop(self):
        self.stop_flag = True

    def _log(self, st, msg):
        st["log"] = (st.get("log") or [])[-199:] + [{"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "msg": msg}]

    def _run(self):
        while not self.stop_flag:
            with self.lock:
                st = self.state()
                if not st["queue"]:
                    st["running"], st["current"] = False, None
                    self._save(st)
                    return
                cand = st["queue"][0]
                st["running"], st["current"] = True, cand
                self._save(st)
            t0 = time.time()
            try:
                if cand["source"] == "gutenberg":
                    r = pg_harvest(self.lib, cand)
                elif cand["source"] == "internet-archive":
                    r = ia_harvest(self.lib, cand)
                else:
                    r = by_address(self.lib, cand["id"], cand.get("rights") or "unknown", cand.get("title") or "",
                                   cand.get("author") or "", cand["source"], cand.get("year") or 0)
                err = None
            except Exception as e:                       # one bad book never stops the harvest
                r, err = None, "%s: %s" % (type(e).__name__, e)
            with self.lock:
                st = self.state()
                st["queue"] = [c for c in st["queue"] if not (c["source"] == cand["source"] and str(c["id"]) == str(cand["id"]))]
                row = dict(cand, seconds=round(time.time() - t0, 1))
                if err:
                    st["failed"] = (st.get("failed") or [])[-499:] + [dict(row, error=err)]
                    self._log(st, "failed: %s — %s" % (cand.get("title"), err))
                elif r.get("held"):
                    st["held"] = (st.get("held") or [])[-999:] + [dict(row, why=r["why"])]
                    self._log(st, "held for review: %s — %s" % (cand.get("title"), r["why"]))
                else:
                    st["done"] = (st.get("done") or []) + [dict(row, book=r["book"], units=r.get("units"))]
                    self._log(st, "harvested: %s (%s Fact Units)" % (cand.get("title"), format(r.get("units") or 0, ",")))
                    write_catalog(self.lib)
                st["current"] = None
                self._save(st)
            time.sleep(PACE_S)
        with self.lock:
            st = self.state()
            st["running"], st["current"] = False, None
            self._log(st, "stopped (the queue is kept and resumes on Start)")
            self._save(st)

    def review(self, book_id, by, status):
        mp = os.path.join(self.lib, book_id, "meta.json")
        with open(mp, encoding="utf-8") as f:
            meta = json.load(f)
        meta["rights_record"]["human_review"] = {"status": status, "by": by, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        with open(mp, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        write_catalog(self.lib)
        return meta["rights_record"]

    def remove(self, book_id):
        folder = os.path.join(self.lib, book_id)
        if not re.fullmatch(r"(pg|ia|se|doc|ht)-[a-z0-9-]+", book_id) or not os.path.isdir(folder):
            raise ValueError("Only harvested books can be removed here.")
        for name in os.listdir(folder):
            os.remove(os.path.join(folder, name))
        os.rmdir(folder)
        write_catalog(self.lib)
        return {"removed": book_id}


# --------------------------------------------------------------------------- Control Panel routes
def add_routes(api, commons, program_dir):
    """Control Panel -> Harvesting -> Books: /api/books, /api/books/discover, /api/books/harvest, /api/books/stop,
    /api/books/address, /api/books/import, /api/books/review, /api/books/remove"""
    import qbcore as core
    lib = library_dir(commons.folder)
    shell = [os.path.join(os.path.dirname(program_dir), d, "library") for d in ("shell", "QueryBook-Shell")]
    job = Harvest(lib, [d for d in shell if os.path.isdir(d)])
    if job.state().get("queue"):
        job.start()                                       # resume after a restart

    def user(fn):
        def run(p):
            try:
                return fn(p)
            except ValueError as e:
                raise core.UserError(str(e))
            except OSError as e:
                raise core.UserError("The source could not be reached: %s" % e)
        return run

    @api.get("/api/books")
    def books_status(p):
        st = job.state()
        try:
            with open(os.path.join(lib, "catalog.json"), encoding="utf-8") as f:
                books = json.load(f)["books"]
        except (OSError, ValueError, KeyError):
            books = []
        bundled = 0
        for d in job.bundled:
            try:
                with open(os.path.join(d, "catalog.json"), encoding="utf-8") as f:
                    bundled += len(json.load(f)["books"])
            except (OSError, ValueError, KeyError):
                pass
        return {"version": VERSION, "sources": SOURCES, "rights_choices": RIGHTS_CHOICES, "phases": PHASES, "blocked_authors": BLOCKED_AUTHORS,
                "library": lib, "books": books, "bundled": bundled, "running": bool(job.thread and job.thread.is_alive()),
                "queue": st["queue"][:50], "queued": len(st["queue"]), "current": st.get("current"),
                "done": len(st.get("done") or []), "held": (st.get("held") or [])[-50:], "failed": (st.get("failed") or [])[-50:],
                "log": (st.get("log") or [])[-40:]}

    @api.post("/api/books/discover")
    def books_discover(p):
        def go(p):
            src = p.get("source") or "gutenberg"
            subjects = p.get("subjects") or []
            if isinstance(subjects, str):
                subjects = [s for s in re.split(r"[,;\n]", subjects) if s.strip()]
            if p.get("phase") in PHASES:
                ph = PHASES[p["phase"]]
                subjects, per = ph["subjects"], ph["per_subject"]
            else:
                per = max(1, min(200, int(p.get("per_subject") or 10)))
            if not subjects:
                raise ValueError("Name at least one subject (for example: astronomy, history of Rome, detective stories).")
            if src == "internet-archive":
                found = []
                for s in subjects:
                    found += ia_discover(s, per)
                return {"candidates": found}
            return {"candidates": pg_discover(lib, subjects, p.get("language") or "en", per, p.get("order") or "popular", job.bundled)}
        return user(go)(p)

    @api.post("/api/books/harvest")
    def books_harvest(p):
        return {"added": job.add([c for c in p.get("candidates") or [] if isinstance(c, dict) and c.get("source") and c.get("id")])}

    @api.post("/api/books/stop")
    def books_stop(p):
        job.stop()
        return {"ok": True}

    @api.post("/api/books/start")
    def books_start(p):
        job.start()
        return {"ok": True}

    @api.post("/api/books/address")
    def books_address(p):
        def go(p):
            url = str(p.get("url") or "").strip()
            if not re.match(r"https?://", url):
                raise ValueError("Give the full address, starting with https://")
            return {"added": job.add([{"source": p.get("source") or "government", "id": url, "title": p.get("title") or url,
                                       "author": p.get("author") or "", "rights": p.get("rights") or "unknown", "year": p.get("year") or 0}])}
        return user(go)(p)

    @api.post("/api/books/import")
    def books_import(p):
        if not p.get("agree"):
            raise core.UserError("Confirm that you hold these volumes under HathiTrust's research terms (or another licence) first.")
        return user(lambda q: import_folder(lib, str(q.get("folder") or ""), str(q.get("rights") or "")))(p)

    @api.post("/api/books/review")
    def books_review(p):
        return user(lambda q: job.review(str(q.get("book") or ""), str(q.get("by") or "admin"), str(q.get("status") or "reviewed")))(p)

    @api.post("/api/books/remove")
    def books_remove(p):
        return user(lambda q: job.remove(str(q.get("book") or "")))(p)


# --------------------------------------------------------------------------- self-test (a stand-in for every site: nothing leaves this computer)
def self_test(verbose=True):
    import http.server, shutil, socketserver, tempfile
    results = []

    def ok(name, cond, detail=""):
        results.append((name, bool(cond)))
        if verbose:
            print("  [%s] %s%s" % ("OK" if cond else "FAIL", name, "" if cond else " — %s" % (detail,)))

    chapters = "".join("\n\nCHAPTER %s\n\nTHE %s PART\n\n" % (r, w) + ("The comet passed the sun in 1835 at a distance of 50,000,000 miles. " * 40 + "\n\n") * 3
                       for r, w in (("I", "FIRST"), ("II", "SECOND"), ("III", "THIRD"), ("IV", "FOURTH")))
    book = ("The Project Gutenberg eBook of Comets\n\n*** START OF THE PROJECT GUTENBERG EBOOK COMETS ***\n\nCOMETS\n" + chapters +
            "\n*** END OF THE PROJECT GUTENBERG EBOOK COMETS ***\nlicence text")
    copyrighted = "This is a COPYRIGHTED Project Gutenberg eBook\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\n" + chapters + "\n*** END OF"
    cat = "Text#,Type,Issued,Title,Language,Authors,Subjects,LoCC,Bookshelves\n" \
          "101,Text,1999-01-01,Comets,en,\"Halley, E.\",Comets; Astronomy,QB,Science\n" \
          "102,Text,1999-01-01,On the Origin,en,\"Darwin, Charles, 1809-1882\",Evolution; Astronomy,QH,Science\n" \
          "103,Text,1999-01-01,Les Astres,fr,\"Flammarion\",Astronomy,QB,Science\n" \
          "104,Sound,1999-01-01,Comets read aloud,en,\"Halley, E.\",Astronomy,QB,Science\n" \
          "105,Text,1999-01-01,Secret Stars,en,\"Modern, A.\",Astronomy,QB,Science\n"
    opf = ('<?xml version="1.0"?><package><manifest><item id="c1" href="text/one.xhtml" media-type="application/xhtml+xml"/>'
           '<item id="c2" href="text/two.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>')
    eb = io.BytesIO()
    with zipfile.ZipFile(eb, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="epub/content.opf"/></rootfiles></container>')
        z.writestr("epub/content.opf", opf)
        for k, name in enumerate(("one", "two", "three")):
            z.writestr("epub/text/%s.xhtml" % name, "<html><body><h2>Part %d</h2>" % (k + 1) + "<p>A sentence about the moon and the tides. </p>" * 120 + "</body></html>")
    seen = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            seen.append(self.path)
            p = self.path
            if p.startswith("/cat.csv.gz"):
                body, ct = gzip.compress(cat.encode("utf-8")), "application/gzip"
            elif p.startswith("/opds"):
                body, ct = ('<feed><link href="/ebooks/102.opds"/><link href="/ebooks/101.opds"/><link href="/ebooks/103.opds"/>'
                            '<link href="/ebooks/104.opds"/><link href="/ebooks/105.opds"/></feed>' if "start_index=1&" in p + "&" else "<feed></feed>").encode(), "application/atom+xml"
            elif p.startswith("/pg/101"):
                body, ct = book.encode("utf-8"), "text/plain"
            elif p.startswith("/pg/105"):
                body, ct = copyrighted.encode("utf-8"), "text/plain"
            elif p.startswith("/ia/search"):
                docs = [{"identifier": "oldcomets1880", "title": "Old Comets", "creator": "Smyth", "year": "1880", "licenseurl": "http://www.gnu.org/licenses/gpl.html"},
                        {"identifier": "newcomets1990", "title": "New Comets", "creator": "Jones", "year": "1990"}]
                body, ct = json.dumps({"response": {"docs": docs}}).encode(), "application/json"
            elif p.startswith("/ia/text/oldcomets1880"):
                body, ct = (("COMETS OF OLD\n\n" + "The comet re-\nturned in the year 1759 as Halley fore-\ntold it would.\n\n12\n\n") * 300).encode(), "text/plain"
            elif p.startswith("/se/") and p.endswith(".epub"):
                body, ct = eb.getvalue(), "application/epub+zip"
            elif p.startswith("/doc.pdf"):
                body, ct = b"%PDF-1.4 binary", "application/pdf"
            elif p.startswith("/gov.html"):
                body, ct = ("<html><body><nav>menu</nav><h1>Report on the Tides</h1>" + "<p>The tide rises twice each lunar day. </p>" * 200 + "</body></html>").encode(), "text/html"
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    tmp = tempfile.mkdtemp(prefix="qbbooks-")
    global PACE_S
    old_pace = PACE_S
    PACE_S = 0.0
    try:
        lib = library_dir(os.path.join(tmp, "commons"))
        ok("the library lives beside the commons, in <data>/library", lib == os.path.join(tmp, "library"), lib)
        cat_ = pg_catalog(lib, refresh=True, url=base + "/cat.csv.gz")
        ok("Project Gutenberg's catalog is read (Text#, type, language, authors, subjects, bookshelves)", len(cat_["rows"]) == 5 and cat_["by"]["101"]["Title"] == "Comets")
        found = pg_discover(lib, ["astronomy"], "en", 10, "popular", catalog=cat_, opds=base + "/opds?query=%s&start_index=%d")
        ids = [c["id"] for c in found]
        ok("discovery: ranked by downloads; Darwin never chosen (block list); other languages and recordings left out", ids == [101, 105], ids)
        r1 = pg_harvest(lib, found[0], text_url=base + "/pg/%d?%d")
        meta = json.load(open(os.path.join(lib, "pg-101", "meta.json"), encoding="utf-8"))
        rr = meta["rights_record"]
        ok("a Gutenberg book becomes a QueryBook edition: chapters found by themselves, Fact Units, header and licence removed",
           r1.get("book") == "pg-101" and r1["chapters"] >= 4 and r1["units"] > 50 and
           "licence text" not in gzip.open(os.path.join(lib, "pg-101", "text.txt.gz")).read().decode(), r1)
        ok("every book carries a Rights Record (work, author, source, id, rights, territory, source file with SHA-256, ingestion, transformation, human review)",
           all(k in rr for k in ("work", "author", "source", "source_id", "original_publication", "rights_status", "territory", "source_file",
                                 "ingested", "transformation", "human_review")) and len(rr["source_file"]["sha256"]) == 64 and rr["human_review"]["status"] == "not reviewed")
        r2 = pg_harvest(lib, found[1], text_url=base + "/pg/%d?%d")
        ok("a book marked copyrighted in its Gutenberg header is held, not ingested", r2.get("held") and not os.path.exists(os.path.join(lib, "pg-105")), r2)
        again = pg_discover(lib, ["astronomy"], "en", 10, "popular", catalog=cat_, opds=base + "/opds?query=%s&start_index=%d")
        ok("a book already in the library is never harvested twice", next(c for c in again if c["id"] == 101)["have"])
        ia = ia_discover("comets", 5, search=base + "/ia/search")
        ok("Internet Archive: rights from the publication year — 1880 public domain, 1990 unknown (its 'GPL' licence field is not trusted)",
           [c["rights"] for c in ia] == ["public domain in the USA", "unknown"], ia)
        r3 = ia_harvest(lib, ia[0], text_url=base + "/ia/text/%s?%s")
        t3 = gzip.open(os.path.join(lib, "ia-oldcomets1880", "text.txt.gz")).read().decode()
        ok("a scanned book's OCR text is cleaned (split words rejoined, page numbers dropped) and recorded as OCR",
           r3.get("book") and "returned" in t3 and "fore-" not in t3 and "\n12\n" not in t3 and
           json.load(open(os.path.join(lib, "ia-oldcomets1880", "meta.json")))["rights_record"]["transformation"]["ocr"], r3)
        ok("a scanned item with unclear rights is held for review", ia_harvest(lib, ia[1]).get("held"))
        ok("Standard Ebooks: the book's address gives its EPUB download",
           standard_ebooks_epub_url("https://standardebooks.org/ebooks/jane-austen/pride-and-prejudice") ==
           "https://standardebooks.org/ebooks/jane-austen/pride-and-prejudice/downloads/jane-austen_pride-and-prejudice.epub")
        r4 = by_address(lib, base + "/se/book.epub", "CC0 / public-domain dedication", "Moon and Tides", "Anon", "standard-ebooks")
        b4 = json.loads(gzip.open(os.path.join(lib, r4["book"], "book.json.gz")).read())
        ok("an EPUB is read in spine order, its headings become chapters", [c["label"] for c in b4["chapters"] if c["n"]] == ["Part 1", "Part 2"],
           [c["label"] for c in b4["chapters"]])
        r5 = by_address(lib, base + "/gov.html", "U.S. federal government work (17 U.S.C. § 105)")
        b5 = json.loads(gzip.open(os.path.join(lib, r5["book"], "book.json.gz")).read())
        ok("a government HTML page: menus dropped, its title found, the declared rights recorded",
           b5["title"] == "Report on the Tides" and not any("menu" in u["text"] for u in b5["units"]) and
           json.load(open(os.path.join(lib, r5["book"], "meta.json")))["rights_record"]["rights_status"].startswith("U.S. federal"))
        ok("a document whose rights are unknown is held, never ingested", by_address(lib, base + "/gov.html", "unknown").get("held"))
        cards = write_catalog(lib)
        ok("the library's catalog lists every harvested book with its Rights Record", len(cards) == 4 and all(c.get("rights_record") for c in cards), len(cards))
        h = Harvest(lib)
        PACE_S = 0.0
        h.add([dict(found[0], have=False), {"source": "gutenberg", "id": 105, "title": "Secret Stars", "author": "Modern, A."}])
        PG_TEXT_SAVE = globals()["PG_TEXT"]
        globals()["PG_TEXT"] = base + "/pg/%d?%d"
        try:
            h.thread.join(10)
        finally:
            globals()["PG_TEXT"] = PG_TEXT_SAVE
        st = h.state()
        ok("the background harvest works through its queue, keeps going past a failure, and writes its log",
           not st["queue"] and len(st["log"]) >= 2 and not st["running"], st)
        rv = h.review("pg-101", "Ada", "reviewed")
        ok("an administrator's review is written into the Rights Record", rv["human_review"]["status"] == "reviewed" and rv["human_review"]["by"] == "Ada")
        ok("only harvested books can be removed", h.remove("pg-101")["removed"] == "pg-101" and not os.path.exists(os.path.join(lib, "pg-101")))
        rp = by_address(lib, base + "/doc.pdf", "public domain in the USA")
        ok("a PDF is held with an explanation (text extraction / OCR is the next stage)", rp.get("held") and "PDF" in rp["why"], rp)
    finally:
        PACE_S = old_pace
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    passed = sum(1 for _, c in results if c)
    if verbose:
        print("\n  %d of %d checks passed" % (passed, len(results)))
    return passed, len(results)


if __name__ == "__main__":
    import sys
    p, n = self_test()
    sys.exit(0 if p == n else 1)
