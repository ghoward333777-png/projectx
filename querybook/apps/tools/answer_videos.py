#!/usr/bin/env python3
"""Answer videos: the script for each answer is built from facts, never written by a model.

For each question in a batch file, the answer comes from a sourced fact (Wikidata, CC0: the item's best-ranked
statement, fetched live) or from QueryBook's own computation (primes, weekdays, conversions). A fixed sentence pattern
turns the fact into one spoken line. The output is
  * a script in the exemplar generator's format (one row per answer, the fixed instructions for the persona), and
  * a manifest: for every answer the question, the line, and the facts it states with their source and the date read.
A video model then only performs the line; generate_exemplars.py makes the clips and checks every word against it.

  python tools/answer_videos.py build --batch tools/plans/answers-batch1.json --out answers-batch1   (writes .md and .json)
"""
import argparse, datetime, json, math, os, re, sys, time, urllib.error, urllib.parse, urllib.request

UA = "QueryBook-answer-videos/1.0 (+https://github.com/ghoward333777-png/projectx)"
ENTITY = "https://www.wikidata.org/wiki/Special:EntityData/%s.json"
LABELS = "https://www.wikidata.org/w/api.php?action=wbgetentities&ids=%s&props=labels&languages=en&format=json"
UNITS = {"Q11573": "metres", "Q828224": "kilometres", "Q573": "days", "Q7727": "minutes", "Q25235": "hours", "Q11574": "seconds",
         "Q712226": "square kilometres", "Q11570": "kilograms"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
FIXED = ("Use the attached image: this exact woman — same face, hair, skin, lips and teeth. Do not change her identity.\n\n"
         "Shot: head and shoulders, facing the camera straight on, eyes level with the lens. The camera does not move, zoom or cut. "
         "Soft, even, front lighting with no hard shadows across the mouth. Plain, still background. Her whole mouth and chin stay in "
         "view the entire time; no hands, hair or objects in front of the face.\n\n"
         "Performance: she answers a question, speaking clearly in natural American English at a calm, friendly pace, looking into "
         "the camera, with a warm, neutral expression. Natural blinking and small natural head movements only. She says exactly the "
         "words given — no extra words, no humming, no music, no other sounds. No captions, subtitles or any text on screen.\n\n"
         "Timing: she starts with her lips gently closed for half a second, speaks the line, then closes her lips and holds still "
         "for half a second at the end.\n\nShe says exactly:")


def _get(url, tries=6):
    """Wikidata asks for a slower pace with 429 (and has the odd 5xx): wait as asked, then try again"""
    for n in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or n == tries - 1:
                raise
            time.sleep(max(int(e.headers.get("Retry-After") or 0), 5 * (n + 1)))


_CACHE = {}


def entity(qid):
    if qid not in _CACHE:
        _CACHE[qid] = _get(ENTITY % qid)["entities"][qid]
        time.sleep(1.0)                          # one item a second: within Wikidata's limits
    return _CACHE[qid]


def labels(qids):
    qids = [q for q in dict.fromkeys(qids) if q]
    out = {}
    for i in range(0, len(qids), 50):
        d = _get(LABELS % "|".join(qids[i:i + 50]))["entities"]
        out.update({q: ((v.get("labels") or {}).get("en") or {}).get("value") for q, v in d.items()})
    return out


def best(qid, pid):
    """truthy statements: preferred rank if any, else normal; never deprecated"""
    sts = (entity(qid).get("claims") or {}).get(pid, [])
    pref = [s for s in sts if s.get("rank") == "preferred"]
    return pref or [s for s in sts if s.get("rank") == "normal"]


# a place someone was born or died in is said as its town: a building (a hospital, a house) is replaced by the settlement it is in
SETTLEMENT = {"Q515", "Q1549591", "Q3957", "Q532", "Q486972", "Q15284", "Q5119", "Q1093829", "Q3301053", "Q1637706", "Q200250",
              "Q1906268", "Q2989398", "Q7930989", "Q1115575", "Q484170", "Q747074", "Q262166", "Q42744322", "Q22865", "Q3184121"}


def settlement(qid, hops=4):
    for _ in range(hops):
        classes = {((s_.get("mainsnak") or {}).get("datavalue") or {}).get("value", {}).get("id") for s_ in best(qid, "P31")}
        if classes & SETTLEMENT:
            return qid
        up = [((s_.get("mainsnak") or {}).get("datavalue") or {}).get("value", {}).get("id") for s_ in best(qid, "P131")]
        if not up or not up[0]:
            return qid
        qid = up[0]
    return qid


def number(x, unit=""):
    v = float(x)
    if v >= 100 and v != int(v):
        s, about = "{:,}".format(round(v)), True
    else:
        s, about = ("{:,}".format(int(v)) if v == int(v) else ("%g" % v)), False
    return ("about " if about else "") + s + ((" " + unit) if unit else "")


def value(st, lab):
    dv = (st.get("mainsnak") or {}).get("datavalue") or {}
    t, v = dv.get("type"), dv.get("value")
    if t == "wikibase-entityid":
        return lab.get(v["id"]) or v["id"], v["id"]
    if t == "time":
        if v.get("calendarmodel", "").endswith("Q1985786"):
            raise ValueError("a Julian-calendar date: left out (it needs both calendars to be said correctly)")
        y, m, d = v["time"][1:].split("T")[0].split("-")
        p = v.get("precision", 11)
        y = int(y)
        return ("%d %s %d" % (int(d), MONTHS[int(m) - 1], y) if p >= 11 else "%s %d" % (MONTHS[int(m) - 1], y) if p == 10 else str(y)), None
    if t == "quantity":
        u = v.get("unit", "1").rsplit("/", 1)[-1]
        return number(v["amount"].lstrip("+"), UNITS.get(u, "")), None
    if t == "string":
        return v, None
    if t == "monolingualtext":
        return v["text"], None
    raise ValueError("unsupported value type %s" % t)


WORDS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def say_number(n):
    return WORDS[n] if n < 20 else TENS[n // 10] + ("" if n % 10 == 0 else "-" + WORDS[n % 10]) if n < 100 else str(n)


def spoken(kind, v):
    """the way a value is said: a symbol letter by letter ("Au" → "A, U"), a formula with its counts ("C₆H₁₂O₆" → "C six H twelve O six")"""
    if kind == "spell":
        return ", ".join(c.upper() for c in v)
    if kind == "formula":
        return " ".join(say_number(int(t.translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")))) if t[0] in "₀₁₂₃₄₅₆₇₈₉" else t
                        for t in re.findall(r"[A-Z][a-z]?|[₀-₉]+", v))
    return v


def join(xs):
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


# ------------------------------------------------------------------------------------------------ QueryBook's own computation
def computed(rule, args):
    if rule == "sqrt":
        r = math.isqrt(int(args["n"]))
        assert r * r == int(args["n"])
        return {"v": str(r)}, "the square root of an exact square"
    if rule == "prime":
        n = int(args["n"])
        ok = n > 1 and all(n % k for k in range(2, math.isqrt(n) + 1))
        return {"v": "is" if ok else "is not", "why": "it has no divisors other than 1 and itself" if ok else "it has other divisors"}, "trial division"
    if rule == "weekday":
        d = datetime.date.fromisoformat(args["date"])
        return {"v": d.strftime("%A"), "date": "%d %s %d" % (d.day, MONTHS[d.month - 1], d.year)}, "the Gregorian calendar"
    if rule == "leap-days":
        return {"v": "366"}, "a leap year has 366 days (the Gregorian calendar)"
    if rule == "f-to-c":
        c = (float(args["f"]) - 32) * 5 / 9
        return {"v": ("%.1f" % c).rstrip("0").rstrip(".")}, "°C = (°F − 32) × 5/9"
    if rule == "seconds-day":
        return {"v": "{:,}".format(24 * 60 * 60)}, "24 hours × 60 minutes × 60 seconds"
    raise ValueError("unknown rule " + rule)


# ------------------------------------------------------------------------------------------------ building a batch
def build(batch):
    today = datetime.date.today().isoformat()
    out, problems = [], []
    for q in batch["questions"]:
        try:
            if q.get("rule"):
                vals, how = computed(q["rule"], q.get("args") or {})
                facts = [{"computed": q["rule"], "how": how, "args": q.get("args") or {}}]
            else:
                vals, facts = {}, []
                need = []
                place = set(q.get("places") or [])
                sts_of = {}
                for name, (qid, pid) in q["facts"].items():
                    sts = best(qid, pid)
                    if name in place:              # follow a building up to its town (a copy: the cached statement stays as read)
                        sts = [json.loads(json.dumps(st)) for st in sts]
                        for st in sts:
                            dv = (st.get("mainsnak") or {}).get("datavalue") or {}
                            if dv.get("type") == "wikibase-entityid":
                                dv["value"]["id"] = settlement(dv["value"]["id"])
                    sts_of[name] = sts
                    for st in sts:
                        dv = (st.get("mainsnak") or {}).get("datavalue") or {}
                        if dv.get("type") == "wikibase-entityid":
                            need.append(dv["value"]["id"])
                lab = labels(need)
                for name, (qid, pid) in q["facts"].items():
                    sts = sts_of[name]
                    if not sts:
                        raise ValueError("%s has no %s" % (qid, pid))
                    got = [value(st, lab) for st in sts]
                    vals[name] = join(sorted({g[0] for g in got}, key=[g[0] for g in got].index))
                    facts.append({"item": qid, "property": pid, "value": vals[name],
                                  "value_items": [g[1] for g in got if g[1]], "source": "https://www.wikidata.org/wiki/" + qid,
                                  "licence": "CC0 1.0 (Wikidata)", "read": today})
            if any(re.fullmatch(r"Q\d+", x) for v in vals.values() for x in re.split(r", | and ", str(v))):
                raise ValueError("a value has no English name on Wikidata — never said as an ID")
            shown = q["say"].format(**vals)
            line = q["say"].format(**{k: spoken((q.get("speak") or {}).get(k), v) for k, v in vals.items()})
            out.append({"code": q["code"], "question": q["question"], "domain": q["domain"], "line": line, "caption": shown, "facts": facts})
        except Exception as e:
            problems.append({"code": q["code"], "question": q["question"], "why": str(e)})
    return out, problems


def write(answers, problems, base, persona):
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump({"made": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "persona": persona,
                   "answers": answers, "left_out": problems}, f, indent=1, ensure_ascii=False)
    rows = "\n".join('| %s | "%s" | %s — %s |' % (a["code"], a["line"], a["domain"], a["question"]) for a in answers)
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write("# %s: answer videos, batch 1\n\nEach line is built from a sourced or computed fact (see %s.json). "
                "The video model only performs it.\n\n## Fixed instructions (paste before every clip)\n\n```\n%s\n```\n\n"
                "## Clips\n\n| Code | Line | Covers |\n|---|---|---|\n%s\n" % (persona, os.path.basename(base), FIXED, rows))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("build")
    b.add_argument("--batch", required=True)
    b.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    batch = json.load(open(a.batch, encoding="utf-8"))
    answers, problems = build(batch)
    write(answers, problems, a.out, batch.get("persona", "Pamela"))
    for x in answers:
        print("%s  %s\n      %s" % (x["code"], x["question"], x["line"]))
    for p in problems:
        print("LEFT OUT %s  %s — %s" % (p["code"], p["question"], p["why"]))
    print("\n%d answers, %d left out" % (len(answers), len(problems)))


if __name__ == "__main__":
    sys.exit(main())
