#!/usr/bin/env python3
"""Add public-domain English Bibles to the Book Query library, as QueryBook editions.

    python tools/build_bibles.py            fetch the sources and write apps/shell/library/bible-*/ (text.txt.gz, meta.json)
    python tools/build_library.py           then build every book.json.gz and the catalog

Only translations that are in the public domain are here: the King James Version (1611; Project Gutenberg #10), the
American Standard Version (1901; eBible.org) and the World English Bible (a modern public-domain translation; eBible.org).
The New American Standard, the New International, the English Standard and the other modern versions on Bible Gateway
are under copyright (and Bible Gateway's terms forbid copying its pages): they are NOT added, by the library's rights rule.

Every edition has the same shape, so a quotation is cited as book, chapter and verse:

    The Old Testament          a part
    Genesis                    a chapter of the library = a book of the Bible
    1. 1:1 In the beginning    "1." opens section 1 = chapter 1; each verse is its own paragraph and keeps its number

Deterministic: the same sources give the same files.
"""
import gzip
import io
import json
import os
import re
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "apps", "shell", "library")
UA = "QueryBook-library-build/1.0"
FETCHED = "2026-11-13"

BOOKS = [("GEN", "Genesis"), ("EXO", "Exodus"), ("LEV", "Leviticus"), ("NUM", "Numbers"), ("DEU", "Deuteronomy"), ("JOS", "Joshua"),
         ("JDG", "Judges"), ("RUT", "Ruth"), ("1SA", "1 Samuel"), ("2SA", "2 Samuel"), ("1KI", "1 Kings"), ("2KI", "2 Kings"),
         ("1CH", "1 Chronicles"), ("2CH", "2 Chronicles"), ("EZR", "Ezra"), ("NEH", "Nehemiah"), ("EST", "Esther"), ("JOB", "Job"),
         ("PSA", "Psalms"), ("PRO", "Proverbs"), ("ECC", "Ecclesiastes"), ("SOL", "Song of Solomon"), ("ISA", "Isaiah"),
         ("JER", "Jeremiah"), ("LAM", "Lamentations"), ("EZE", "Ezekiel"), ("DAN", "Daniel"), ("HOS", "Hosea"), ("JOE", "Joel"),
         ("AMO", "Amos"), ("OBA", "Obadiah"), ("JON", "Jonah"), ("MIC", "Micah"), ("NAH", "Nahum"), ("HAB", "Habakkuk"),
         ("ZEP", "Zephaniah"), ("HAG", "Haggai"), ("ZEC", "Zechariah"), ("MAL", "Malachi"),
         ("MAT", "Matthew"), ("MAR", "Mark"), ("LUK", "Luke"), ("JOH", "John"), ("ACT", "Acts"), ("ROM", "Romans"),
         ("1CO", "1 Corinthians"), ("2CO", "2 Corinthians"), ("GAL", "Galatians"), ("EPH", "Ephesians"), ("PHI", "Philippians"),
         ("COL", "Colossians"), ("1TH", "1 Thessalonians"), ("2TH", "2 Thessalonians"), ("1TI", "1 Timothy"), ("2TI", "2 Timothy"),
         ("TIT", "Titus"), ("PHM", "Philemon"), ("HEB", "Hebrews"), ("JAM", "James"), ("1PE", "1 Peter"), ("2PE", "2 Peter"),
         ("1JO", "1 John"), ("2JO", "2 John"), ("3JO", "3 John"), ("JUD", "Jude"), ("REV", "Revelation")]
NEW_TESTAMENT_AT = 39

EXAMPLES = ["Who was Moses?", "What are the ten commandments?", "love", "What does it say about wisdom?", "the good Samaritan",
            "In the beginning"]
PEOPLE = [("Moses", ["Moses"]), ("Abraham", ["Abraham", "Abram"]), ("David", ["David"]), ("Jesus", ["Jesus", "Christ"]),
          ("Paul", ["Paul", "Saul of Tarsus"]), ("Peter", ["Peter", "Simon Peter", "Cephas"]), ("Solomon", ["Solomon"]),
          ("Noah", ["Noah"]), ("Jacob", ["Jacob"]), ("Joseph", ["Joseph"]), ("Mary", ["Mary"]), ("Elijah", ["Elijah", "Elias"])]

EDITIONS = {
    "bible-kjv": {
        "title": "The Holy Bible, King James Version", "author": "Translated by the scholars appointed by King James I", "year": 1611,
        "published": "1611 (the text of the standard 1769 edition)", "source": "Project Gutenberg eBook #10",
        "url": "https://www.gutenberg.org/ebooks/10", "fetch": "https://www.gutenberg.org/cache/epub/10/pg10.txt", "form": "gutenberg",
        "rights": "Public domain in the USA. This QueryBook edition keeps the public-domain text only (Project Gutenberg's header, "
                  "licence and trademark removed) and sets it one verse to a paragraph; in the United Kingdom the King James Version "
                  "is under Crown letters patent. Not endorsed by Project Gutenberg."},
    "bible-asv": {
        "title": "The Holy Bible, American Standard Version", "author": "The American Revision Committee", "year": 1901,
        "published": "1901", "source": "eBible.org, American Standard Version (verse-per-line text)",
        "url": "https://ebible.org/find/details.php?id=eng-asv", "fetch": "https://ebible.org/Scriptures/eng-asv_vpl.zip", "form": "vpl",
        "rights": "Public domain (published 1901). The American Standard Version is the translation the New American Standard Bible "
                  "was revised from; the New American Standard itself is under copyright and is not in this library. Text as "
                  "distributed by eBible.org, set one verse to a paragraph. Not endorsed by eBible.org."},
    "bible-web": {
        "title": "The Holy Bible, World English Bible", "author": "Edited by Michael Paul Johnson and volunteers", "year": 2020,
        "published": "2000–2020 (2020 stable text)", "source": "eBible.org, World English Bible (verse-per-line text)",
        "url": "https://ebible.org/find/details.php?id=eng-web", "fetch": "https://ebible.org/Scriptures/eng-web_vpl.zip", "form": "vpl",
        "rights": "Public domain: dedicated to the public domain by its editors. \"World English Bible\" is a trademark of eBible.org, "
                  "used here because the text of the 66 books is unchanged (the deuterocanonical books of the source are not "
                  "included); only the layout is QueryBook's, one verse to a paragraph. Not endorsed by eBible.org."},
}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def verses_gutenberg(raw):
    """[(book index, chapter, verse, text)] from Project Gutenberg's King James text: 66 books, each beginning at a "1:1" """
    t = raw.decode("utf-8-sig").replace("\r\n", "\n")
    a, b = t.find("*** START OF"), t.find("*** END OF")
    t = t[t.find("\n", a) + 1:b]
    paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", t) if p.strip()]
    mark = re.compile(r"(?:^| )(\d+):(\d+) ")
    starts = [bool(re.match(r"\d+:\d+ ", p)) for p in paras]
    out, book = [], -1
    for k, flat in enumerate(paras):
        if not starts[k]:
            # a paragraph without a verse number at its head: the rest of the verse before it (the source breaks some
            # verses in two) — unless the next numbered paragraph opens a book ("1:1"), when it is that book's heading
            nxt = next((paras[j] for j in range(k + 1, len(paras)) if starts[j]), "")
            if not out or mark.search(flat) is None and (not nxt or nxt.startswith("1:1 ")):
                continue
            m = mark.search(flat)
            head = flat[:m.start()] if m else flat
            b0, c0, v0, t0 = out[-1]
            out[-1] = (b0, c0, v0, (t0 + " " + head).strip())
            flat = flat[m.start():].strip() if m else ""
            if not flat:
                continue
        bits = mark.split(flat)
        for i in range(1, len(bits) - 2, 3):
            c, v, text = int(bits[i]), int(bits[i + 1]), bits[i + 2].strip()
            if c == 1 and v == 1:
                book += 1
            out.append((book, c, v, text))
    return out


def verses_vpl(raw):
    """[(book index, chapter, verse, text)] from eBible.org's verse-per-line file: "GEN 1:1 In the beginning ..." """
    z = zipfile.ZipFile(io.BytesIO(raw))
    name = next(n for n in z.namelist() if n.endswith("_vpl.txt"))
    index = {code: i for i, (code, _) in enumerate(BOOKS)}
    out = []
    for line in z.read(name).decode("utf-8-sig").split("\n"):
        m = re.match(r"(\w{3}) (\d+):(\d+) (.*)$", line.strip())
        if m and m.group(1) in index and m.group(4).strip():
            out.append((index[m.group(1)], int(m.group(2)), int(m.group(3)), " ".join(m.group(4).split())))
    return out


def edition_text(verses):
    lines, book, chapter = [], -1, 0
    for b, c, v, text in verses:
        if b != book:
            if b in (0, NEW_TESTAMENT_AT):
                lines += ["The Old Testament" if b == 0 else "The New Testament", ""]
            lines += [BOOKS[b][1], ""]
            book, chapter = b, 0
        lead = ""
        if c != chapter:
            lead, chapter = "%d. " % c, c
        lines += ["%s%d:%d %s" % (lead, c, v, text), ""]
    return "\n".join(lines)


def main():
    for bid, e in EDITIONS.items():
        raw = fetch(e["fetch"])
        verses = verses_gutenberg(raw) if e["form"] == "gutenberg" else verses_vpl(raw)
        books = sorted({b for b, _, _, _ in verses})
        if books != list(range(66)) or len(verses) < 31080:
            raise SystemExit("%s: expected 66 books and about 31,100 verses, got %d books, %d verses" % (bid, len(books), len(verses)))
        folder = os.path.join(LIB, bid)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "text.txt.gz"), "wb") as f:
            with gzip.GzipFile(fileobj=f, mode="wb", mtime=0, filename="") as g:
                g.write(edition_text(verses).encode("utf-8"))
        meta = {"id": bid, "title": e["title"], "author": e["author"], "year": e["year"], "published": e["published"],
                "kind": "nonfiction", "subject": "Scripture: the Old and New Testaments",
                "structure": "scripture: books, chapters and verses",
                "provenance": {"source": e["source"], "url": e["url"], "fetched": FETCHED, "rights": e["rights"]},
                "text": "text.txt.gz",
                "rules": {"parts": ["The Old Testament", "The New Testament"], "headings": [n for _, n in BOOKS],
                          "standalone": True, "sections": "arabic", "min_chars": 100},
                "examples": EXAMPLES, "characters": [{"name": n, "aliases": a} for n, a in PEOPLE]}
        with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
            f.write(json.dumps(meta, ensure_ascii=False, indent=1) + "\n")
        print("%-10s %d verses" % (bid, len(verses)))


if __name__ == "__main__":
    sys.exit(main())
