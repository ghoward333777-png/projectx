#!/usr/bin/env python3
"""The universal document-type taxonomy -> apps/shell/doctypes.json.

    python tools/build_doctypes.py            write the file
    python tools/build_doctypes.py --check    fail if the file is not what the source makes

The source is tools/doctypes_source.txt: the user's own master list (2026-11-14), 45 domains, kept as they wrote it.
This tool only reads its shape: a numbered line is a domain; "Type<TAB>elements" is a type with its expected elements;
a short line is a type; a line of "a → b → c" is the expected structure of the type just named, or of the group above it;
in the Reports domain a sentence of comma-separated parts after a type is that type's elements. Nothing is added: a type
the list gives no elements for takes its group's structure when the list states one, and otherwise has none.
A type whose name is a kind of document QueryBook already holds a full record for (genres.json) is linked to it.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "tools", "doctypes_source.txt")
OUT = os.path.join(ROOT, "apps", "shell", "doctypes.json")
GENRES = os.path.join(ROOT, "apps", "shell", "genres.json")
# lines of the list that head a group of types rather than name a type
GROUPS = {"Strategy", "Executive communication", "Operations", "Projects", "Sales/marketing", "Financial statements", "Financial reports",
          "Analytical finance", "Architecture", "Specifications", "Patent-family documents", "Court pleadings", "Motions", "Briefs",
          "Evidence/discovery", "Judicial documents", "Transactional law", "Estate law", "Patient/clinical", "Healthcare research/administration",
          "Legislation"}
# the second dimension the list gives: what a document is for
PURPOSES = ["Inform", "Explain", "Describe", "Record", "Analyze", "Compare", "Argue", "Persuade", "Recommend", "Request", "Authorize", "Regulate",
            "Contract", "Prove/Evidence", "Teach", "Instruct", "Predict", "Evaluate", "Document/Archive", "Entertain"]
# what a draft in a domain must say about itself (QueryBook's standing rules)
CAUTION = {17: "a draft for a qualified lawyer, not legal advice", 16: "a draft for a registered patent attorney or agent",
           22: "not medical advice; for review by a qualified clinician", 12: "not investment advice", 29: "a draft for a licensed insurance professional"}
# a type of the list -> the genre record that already covers it, where the names differ
SAME = {"newspaper article": "news-report", "breaking-news report": "news-report", "feature article": "feature", "magazine feature": "feature",
        "academic essay": "essay", "argumentative essay": "essay", "business letter": "letter", "formal letter": "letter", "short story": "short-story",
        "screenplay": "script", "research paper": "research-paper", "literature review": "literature-review", "press release": "press-release",
        "whitepaper": "white-paper", "business plan": "business-plan", "cover letter": "cover-letter", "resume/cv": "resume",
        "poetry": "poem", "contract": "contract", "lesson plan": "lesson-plan", "study guide": "study-guide", "book report": "book-report"}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def parts(s):
    s = re.sub(r"^(Common elements include|Each can be modeled around some combination of)\s*", "", s.strip().rstrip("."))
    return [" ".join(p.split()) for p in (re.split(r"\s*→\s*", s) if "→" in s else re.split(r",\s*(?:and\s+)?|\s+and\s+(?=[a-z-]+$)", s)) if p.strip()]


def build():
    with open(GENRES, encoding="utf-8") as f:
        g = json.load(f)
    names = {}
    for x in g["genres"]:
        names[x["name"].lower()] = x["id"]
        names[x["id"].replace("-", " ")] = x["id"]
    ids = {x["id"] for x in g["genres"]}
    with open(SRC, encoding="utf-8") as f:
        lines = f.read().split("\n")
    domains, dom, fam, last, lone = [], None, None, None, False
    recent, lone_struct, subtypes, prose = [], [], False, ""     # types since the last boundary; a lone type's structure; under "Subtypes:"
    before, lone_type = [], None                                 # the list closed by the last "…:" line; the type last named alone on its line

    def family(name):
        nonlocal fam
        fam = {"name": name, "types": []}
        dom["families"].append(fam)

    def add(name, elements):
        nonlocal last
        name = " ".join(name.split())
        for f_ in dom["families"]:
            for t in f_["types"]:
                if t["name"].lower() == name.lower():        # named twice in one domain: one type
                    if elements and not t["elements"]:
                        t["elements"] = elements
                    last = t
                    recent.append(t)
                    return
        gid = names.get(name.lower()) or SAME.get(name.lower(), "")
        last = {"id": "%d-%s" % (dom["n"], slug(name)), "name": name, "elements": elements, "genre": gid if gid in ids else ""}
        if not elements and subtypes and lone_struct:        # a subtype of the type whose structure was just given
            last["elements"], last["from_group"] = list(lone_struct), True
        fam["types"].append(last)
        recent.append(last)

    for i, raw in enumerate(lines):
        s = raw.strip()
        if not s:
            continue
        m = re.match(r"^(\d+)\. (.+)$", s)
        if m:
            dom = {"n": int(m.group(1)), "name": m.group(2), "caution": CAUTION.get(int(m.group(1)), ""), "families": []}
            domains.append(dom)
            family("")
            last, recent, lone_struct, subtypes, prose, before, lone_type = None, [], [], False, "", [], None
            continue
        if "\t" in raw:
            a, b = raw.split("\t", 1)
            if a.strip() not in ("Document type", "Type"):
                add(a, parts(b))
            lone = False
            continue
        if "→" in s:
            st = parts(s)
            every = [t for f_ in dom["families"] for t in f_["types"]]
            named = sorted((t for t in every if prose.lower().startswith(t["name"].lower() + " ")), key=lambda t: -len(t["name"]))[:1]
            if lone_type is not None or named:               # the structure of the one type named: alone on its line, or by the sentence
                one = lone_type if lone_type is not None else named[0]
                one["elements"], lone_struct = st, st
                one.pop("from_group", None)
            else:
                for t in (recent or before):                 # the structure of the group listed above
                    if not t["elements"]:
                        t["elements"], t["from_group"] = list(st), True
            lone, recent, subtypes, lone_type, before = False, [], False, None, []
            continue
        if s in GROUPS:
            family(s)
            lone, recent, lone_struct, subtypes, lone_type, before = False, [], [], False, None, []
            continue
        prev_blank = i > 0 and not lines[i - 1].strip()
        next_blank = i + 1 >= len(lines) or not lines[i + 1].strip()
        if dom["n"] == 5 and last is not None and lone and s.endswith(".") and "," in s:
            last["elements"] = parts(s)                      # Reports: "Purpose, scope, methodology, …"
            lone = False
            continue
        if len(s.split()) > 7 or s.endswith((":", ".")) or s == "Subclasses include":
            starts_list = s.endswith(":") and not s.lower().startswith(("core", "typical", "common", "the underlying", "a practical"))
            subtypes = s.lower().startswith(("subtypes", "subclasses"))
            if starts_list:
                before, recent = recent, []                  # "Examples:", "Types include:", "Other types:" open a new list
            if not subtypes and starts_list:
                lone_struct = []
            prose, lone = s, False
            continue                                         # the list's own commentary: not a type
        add(s, [])
        after = next((x.strip() for x in lines[i + 1:] if x.strip()), "")
        # alone on its line — or followed by the list's "Common structure:" / "A practical content model is:", which speak of this one type
        lone = next_blank and (prev_blank or after in ("Common structure:", "A practical content model is:") or bool(re.match(r"^\d+\. ", lines[i - 1].strip())) and "→" in after)
        lone_type = last if lone else None
    for d in domains:
        d["families"] = [f_ for f_ in d["families"] if f_["types"]]
    doc = {"version": "doctypes-1", "source": "the user's universal document-type taxonomy, 2026-11-14 (tools/doctypes_source.txt)",
           "purposes": PURPOSES, "domains": domains}
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def main(argv):
    text = build()
    if "--check" in argv:
        with open(OUT, encoding="utf-8") as f:
            if f.read() != text:
                print("apps/shell/doctypes.json is not what tools/build_doctypes.py makes: run it")
                return 1
        return 0
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    d = json.loads(text)
    ts = [t for x in d["domains"] for f_ in x["families"] for t in f_["types"]]
    print("wrote %s: %d domains, %d types, %d with expected elements, %d linked to a full record" % (
        OUT, len(d["domains"]), len(ts), sum(1 for t in ts if t["elements"]), sum(1 for t in ts if t["genre"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
