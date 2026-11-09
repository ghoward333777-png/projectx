#!/usr/bin/env python3
"""Build language/data/webster_1913_full.json.gz: every headword of Webster's Unabridged Dictionary (1913, public domain)
with its part of speech and first senses, so a word outside the 5,052 most common ones (e.g. "obsequious") still has a
meaning.

    python tools/build_webster_full.py pg29765.txt

Input: Project Gutenberg eBook #29765 (https://www.gutenberg.org/ebooks/29765), plain text. Only the dictionary text
between the START/END markers is used; the Project Gutenberg licence text and name are not copied. Deterministic.
"""
import gzip, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "language", "data", "webster_1913_full.json.gz")
HEAD = re.compile(r"^[A-Z][A-Z0-9' \-;.]*[A-Z]$|^[A-Z]$")
POS = re.compile(r",\s*((?:v\. t\.|v\. i\.|n\.|a\.|adv\.|prep\.|conj\.|interj\.|pron\.|p\. p\.|p\. pr\.|imp\.|pl\.)(?:\s*(?:&|and)\s*(?:v\. t\.|v\. i\.|n\.|a\.))?)")
POS_NAME = {"n.": "noun", "a.": "adjective", "adv.": "adverb", "v. t.": "verb (transitive)", "v. i.": "verb (intransitive)",
            "prep.": "preposition", "conj.": "conjunction", "interj.": "interjection", "pron.": "pronoun", "pl.": "plural",
            "imp.": "past tense", "p. p.": "past participle", "p. pr.": "present participle"}
MAX_SENSES, MAX_CHARS = 3, 700


def parse(text):
    start = text.find("*** START OF")
    end = text.find("*** END OF")
    body = text[text.find("\n", start) + 1:end if end > 0 else None]
    lines = body.splitlines()
    out = {}
    i, n = 0, len(lines)
    while i < n:
        line = lines[i].strip()
        if HEAD.match(line) and (i == 0 or not lines[i - 1].strip()) and i + 1 < n and lines[i + 1].strip():
            heads = [h.strip().lower() for h in line.split(";") if h.strip()]
            j = i + 1
            block = []
            while j < n and not (HEAD.match(lines[j].strip()) and not lines[j - 1].strip() and j + 1 < n and lines[j + 1].strip()):
                block.append(lines[j])
                j += 1
            entry = entry_of(block)
            if entry:
                for h in heads:
                    if re.fullmatch(r"[a-z][a-z' \-]*", h) and h not in out:
                        out[h] = entry
            i = j
            continue
        i += 1
    return out


def entry_of(block):
    pron = block[0].strip() if block else ""
    m = POS.search(pron)
    pos = POS_NAME.get(m.group(1), m.group(1)) if m else ""
    paras, cur = [], []
    for l in block[1:]:
        if l.strip():
            cur.append(l.strip())
        elif cur:
            paras.append(" ".join(cur))
            cur = []
    if cur:
        paras.append(" ".join(cur))
    senses = []
    for p in paras:
        p = re.sub(r"\s+", " ", p)
        if p.startswith("Defn:"):
            senses.append(p[5:].strip())
        elif re.match(r"^\d+\.\s", p):
            senses.append(re.sub(r"^\d+\.\s*", "", p))
        elif re.match(r"^\([a-z]\)\s", p) and senses:
            continue
        if len(senses) >= MAX_SENSES:
            break
    senses = [s for s in senses if s and not s.startswith("Etym:")]
    if not senses:
        return None
    text = "\n".join("%d. %s" % (k + 1, s) if len(senses) > 1 else s for k, s in enumerate(senses))
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rsplit(" ", 1)[0] + "…"
    return {"pos": pos, "text": text}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    with open(sys.argv[1], encoding="utf-8") as f:
        d = parse(f.read())
    data = json.dumps(dict(sorted(d.items())), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.GzipFile(OUT, "wb", mtime=0) as gz:              # mtime 0: the same input gives byte-identical output
        gz.write(data)
    print("%d headwords -> %s (%d KB)" % (len(d), os.path.relpath(OUT, ROOT), os.path.getsize(OUT) // 1024))
