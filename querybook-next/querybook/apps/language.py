"""Language app — answers come back as a dictionary entry: headword, senses,
usage examples drawn from the whole shared corpus, and related words."""

from __future__ import annotations

import re
from typing import Any

from querybook.apps.base import DomainApp, QueryContext, fql_str, source_ref
from querybook.core.model import DOMAIN_COLLECTIONS
from querybook.core.text import STOPWORDS, keywords, sentences, tokenize

POS = r"noun|verb|adjective|adverb|pronoun|preposition|conjunction|interjection|n\.|v\.|adj\.|adv\."
POS_NAMES = {"n.": "noun", "v.": "verb", "adj.": "adjective", "adv.": "adverb"}
ENTRY = re.compile(rf"^\s*[\"“']?(?P<term>[A-Za-z][A-Za-z\- ]{{0,40}}?)[\"”']?\s*\((?P<pos>{POS})\)\s*[:\-—–]\s*(?P<def>.+)$",
                   re.I | re.M)
MEANS = re.compile(r"(?:^|[.;]\s+|\bword\s+)[\"“']?(?P<term>[A-Za-z][A-Za-z\-]{1,30})[\"”']?\s+"
                   r"(?:means|is defined as|refers to)\s+(?P<def>[^.;]{3,200})", re.I)
LEAD = re.compile(r"^(?:please\s+)?(?:define|definition of|meaning of|what does|what is the meaning of|"
                  r"synonyms? (?:for|of)|look up|what is|what's|explain the word)\s+", re.I)
TRAIL = re.compile(r"\s+(?:mean|means)\s*\??$|\?$", re.I)


def headword(query: str) -> str:
    q = LEAD.sub("", query.strip())
    q = TRAIL.sub("", q).strip().strip("\"'“”‘’").strip()
    return q.lower()


class LanguageApp(DomainApp):
    key = "language"
    title = "Language"
    collection = DOMAIN_COLLECTIONS["language"]
    tagline = "Definitions, usage in context and related words"
    placeholder = "Look up a word or phrase — e.g. ephemeral"
    examples = ("ephemeral", "what does etymology mean", "serendipity", "lexicon")

    def enrich(self, title: str, body: str) -> dict[str, Any]:
        text = f"{title}\n{body}"
        defs: list[dict[str, str]] = []
        for m in ENTRY.finditer(text):
            pos = m.group("pos").lower()
            defs.append({"term": m.group("term").strip().lower(), "pos": POS_NAMES.get(pos, pos),
                         "definition": m.group("def").strip()})
        for m in MEANS.finditer(text):
            term = m.group("term").lower()
            if term not in STOPWORDS and not any(d["term"] == term for d in defs):
                defs.append({"term": term, "pos": "", "definition": m.group("def").strip()})
        defs = defs[:20]
        letters = [c for c in text if c.isalpha()]
        out: dict[str, Any] = {
            "definitions": defs,
            "keywords": keywords(text, 10),
            "lang": "en" if letters and sum(c.isascii() for c in letters) / len(letters) > 0.9 else "und",
        }
        if defs:
            out.update(term=defs[0]["term"], pos=defs[0]["pos"], definition=defs[0]["definition"])
        return out

    def respond(self, ctx: QueryContext, query: str) -> dict[str, Any]:
        word = headword(query)
        if not word:
            return {"kind": "empty", "summary": "Type a word to look up."}
        pattern = re.compile(r"\b" + re.escape(word) + r"\b", re.I)
        exact = ctx.docs(f"Language.where(.term == {fql_str(word)}).take(10)")
        related_docs: list[dict[str, Any]] = []
        for coll in DOMAIN_COLLECTIONS.values():
            related_docs += ctx.docs(f"{coll}.search({fql_str(word)}).take(8)")

        senses: list[dict[str, str]] = []
        seen: set[str] = set()

        def add_sense(defn: str, pos: str, doc: dict[str, Any]) -> None:
            key = defn.lower().strip(" .")
            if key and key not in seen:
                seen.add(key)
                senses.append({"definition": defn.strip(), "pos": pos, "source": doc.get("title", ""),
                               "id": doc.get("id", ""), "coll": doc.get("coll", "")})

        for doc in exact + related_docs:
            for d in doc.get("definitions") or []:
                if isinstance(d, dict) and d.get("term") == word:
                    add_sense(d.get("definition", ""), d.get("pos", ""), doc)
            if doc.get("term") == word and doc.get("definition"):
                add_sense(doc["definition"], doc.get("pos", ""), doc)
        is_a = re.compile(r"\b" + re.escape(word) + r"\s+(?:is|are)\s+(?:an?|the)\s+([^.;]{3,160})", re.I)
        examples: list[dict[str, str]] = []
        cooccur: dict[str, int] = {}
        for doc in related_docs:
            for s in sentences(f"{doc.get('body', '')}"):
                if not pattern.search(s) or not 25 <= len(s) <= 260:
                    continue
                m = is_a.search(s)
                if m and len(senses) < 6:
                    add_sense(m.group(0)[len(word):].strip().capitalize(), "", doc)
                if len(examples) < 6 and all(e["text"] != s for e in examples):
                    examples.append({"text": s, "coll": doc.get("coll", ""), "source": doc.get("title", "")})
                for tok in tokenize(s):
                    if tok != word and len(tok) > 3 and tok not in STOPWORDS and not tok.isdigit():
                        cooccur[tok] = cooccur.get(tok, 0) + 1
        for s in senses:
            for tok in tokenize(s["definition"]):
                if tok != word and len(tok) > 3 and tok not in STOPWORDS:
                    cooccur[tok] = cooccur.get(tok, 0) + 2
        related = [w for w, _ in sorted(cooccur.items(), key=lambda kv: (-kv[1], kv[0]))[:10]]
        refs, seen_ids = [], set()
        for doc in exact + related_docs:
            if (doc.get("coll"), doc.get("id")) not in seen_ids:
                seen_ids.add((doc.get("coll"), doc.get("id")))
                refs.append(source_ref(doc))
        if senses or examples:
            summary = (f"{len(senses)} sense{'s' if len(senses) != 1 else ''} and {len(examples)} usage "
                       f"example{'s' if len(examples) != 1 else ''} from {len(refs)} source{'s' if len(refs) != 1 else ''}.")
        else:
            summary = f"No entry for “{word}” yet. Drop a glossary or article into the language inbox and it will appear here live."
        return {"kind": "lexicon", "summary": summary, "subject": word, "headword": word, "senses": senses,
                "examples": examples, "related": related, "sources": refs[:12]}
