"""qbgather — the fact gatherer: an LLM with web search finds facts, QueryBook checks each one on the page itself.

The admin's rule (2026-10-27): facts *gathered* by an LLM may be used; facts *generated* by one may not. So the LLM only
points: it searches the web and proposes short facts. Nothing it writes becomes a fact. For each proposal QueryBook
  1. takes the pages the provider's own search returned — never a URL the model typed — and follows any redirect,
  2. fetches each page itself (robots.txt respected, blocked sites skipped, at most 2 MB),
  3. keeps the fact only when the page states the value (dates and numbers in their usual written forms) within a few
     hundred characters of the thing it is about,
and stores it in the Commons with each confirming page as its source (method "source": one site → sourced, two or more
→ corroborated). The provider and the question go into the fact's reasoning; no wording from any page is stored.

Providers (each needs its key under Harvesting → API keys): gemini (Google Search grounding), perplexity (Sonar),
openai (Responses API web search), anthropic (Claude web search; needs the `anthropic` package). Runs outside the
applications, like the exemplar generator; daily request budgets per provider; every run is in the harvest log.

Run: python qbgather.py ask --commons <shared folder> --provider gemini --area history "question"
"""
import html, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request, urllib.robotparser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qbcore as core  # noqa: E402

VERSION = "1.0.0"
UA = "QueryBook-gatherer/%s (+https://github.com/ghoward333777-png/projectx; checks facts on cited pages)" % VERSION
SOURCE_KEY = "llm-gathered-web"
AREAS = {"language": "language", "stem": "stem", "history": "facts"}            # area -> the application that keeps the facts
MODELS = {"gemini": "gemini-3.5-flash", "perplexity": "agent-fast", "openai": "gpt-5", "anthropic": "claude-opus-5-5"}
BUDGET = {"gemini": 200, "perplexity": 100, "openai": 100, "anthropic": 100}     # requests a day per provider
PAGE_MAX = 2 << 20
WINDOW = 600                                                                     # characters around the value to find the subject
PROMPT = """Use web search to answer: {q}
{hint}
Reply with only a JSON array (no other text) of at most {n} facts you found on the web pages, each
{{"subject": "...", "predicate": "...", "object": "..."}}. The object must be short: a name, a number, a place, or a date
written YYYY-MM-DD (or YYYY-MM, or YYYY). Use the full proper name of the subject. Only facts the pages state."""


EXTRACT = """Turn the answer below into at most {n} facts, using only what the answer states.{hint} Reply with only a JSON array
of {{"subject": "...", "predicate": "...", "object": "..."}}. The object must be short: a name, a number, a place, or a date
written YYYY-MM-DD (or YYYY-MM, or YYYY). Use the full proper name of the subject.

Answer:
{answer}"""


HINT = {}                                               # slot mode: the exact subject and predicate the scaffold uses


class GatherError(Exception):
    pass


# ------------------------------------------------------------------------------------------------ providers
def _post(url, body, headers, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=dict({"Content-Type": "application/json", "User-Agent": UA}, **headers))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise GatherError("%s answered HTTP %d: %s" % (urllib.parse.urlsplit(url).netloc, e.code, e.read()[:300].decode("utf-8", "replace")))


def ask_gemini(key, question, n, model=None):
    """two steps: (1) the question with Google Search on — a grounded answer and the pages Google returned (asked for JSON
    straight away, Gemini tends to answer from memory without searching); (2) that grounded answer, and only it, turned into
    short facts. Proposals from an answer that used no search are discarded."""
    model = model or MODELS["gemini"]
    url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model
    r = _post(url, {"contents": [{"role": "user", "parts": [{"text": question + " Search the web and answer with the specific names, places, "
                                                                     "numbers and dates."}]}], "tools": [{"google_search": {}}]}, {"x-goog-api-key": key})
    cand = (r.get("candidates") or [{}])[0]
    answer = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
    gm = cand.get("groundingMetadata") or {}
    pages = [c["web"]["uri"] for c in gm.get("groundingChunks", []) if c.get("web", {}).get("uri")]
    if not pages:
        return "", [], model                          # no search happened: nothing to check, nothing proposed
    r2 = _post(url, {"contents": [{"role": "user", "parts": [{"text": EXTRACT.format(n=n, answer=answer, hint=HINT.get("text", ""))}]}]},
              {"x-goog-api-key": key})
    text = "".join(p.get("text", "") for p in ((r2.get("candidates") or [{}])[0].get("content") or {}).get("parts", []))
    return text, pages, model


def ask_perplexity(key, question, n, model=None):
    """Perplexity's Agent API (Sonar chat completions were retired on 27 September 2026): effort "fast" searches the web;
    the answer is the message items' output_text, the pages are the search_results items' urls"""
    body = {"effort": "fast", "input": PROMPT.format(q=question, n=n, hint=HINT.get("text", ""))}
    if model and "/" in model:                # an Agent API model id ("openai/…"); otherwise the effort preset picks it
        body["model"] = model
    r = _post("https://api.perplexity.ai/v1/agent", body, {"Authorization": "Bearer " + key})
    text, pages = [], []
    for item in r.get("output") or []:
        if item.get("type") == "message":
            text += [c.get("text", "") for c in item.get("content") or [] if c.get("type") == "output_text"]
        elif item.get("type") == "search_results":
            pages += [x["url"] for x in item.get("results") or [] if x.get("url")]
    return "\n".join(text), list(dict.fromkeys(pages)), r.get("model") or "perplexity-agent (fast)"


def ask_openai(key, question, n, model=None):
    model = model or MODELS["openai"]
    r = _post("https://api.openai.com/v1/responses", {"model": model, "tools": [{"type": "web_search"}], "input": PROMPT.format(q=question, n=n, hint=HINT.get("text", ""))},
              {"Authorization": "Bearer " + key})
    text, pages = "", []
    for item in r.get("output") or []:
        for c in item.get("content") or []:
            if c.get("type") == "output_text":
                text += c.get("text", "")
                pages += [a["url"] for a in c.get("annotations") or [] if a.get("url")]
        for s in (item.get("action") or {}).get("sources") or []:
            if s.get("url"):
                pages.append(s["url"])
    return text, pages, model


def ask_anthropic(key, question, n, model=None):
    try:
        import anthropic
    except ImportError:
        raise GatherError("the Anthropic provider needs the 'anthropic' package: pip install anthropic")
    model = model or MODELS["anthropic"]
    client = anthropic.Anthropic(api_key=key)
    messages = [{"role": "user", "content": PROMPT.format(q=question, n=n, hint=HINT.get("text", ""))}]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}]
    for _ in range(4):                                  # server-side search may pause a long turn: resume it
        resp = client.messages.create(model=model, max_tokens=16000, messages=messages, tools=tools)
        if resp.stop_reason != "pause_turn":
            break
        messages = messages[:1] + [{"role": "assistant", "content": resp.content}]
    if resp.stop_reason == "refusal":
        raise GatherError("Claude declined the question")
    text, pages = "", []
    for b in resp.content:
        if b.type == "text":
            text += b.text
            pages += [c.url for c in (getattr(b, "citations", None) or []) if getattr(c, "url", None)]
        elif b.type == "web_search_tool_result" and isinstance(b.content, list):
            pages += [x.url for x in b.content if getattr(x, "url", None)]
    return text, pages, model


PROVIDERS = {"gemini": ask_gemini, "perplexity": ask_perplexity, "openai": ask_openai, "anthropic": ask_anthropic}


def parse_facts(text):
    """the model's proposals: a JSON array, possibly inside a code fence; anything malformed is dropped"""
    m = re.search(r"\[.*\]", text or "", re.S)
    try:
        arr = json.loads(m.group(0)) if m else []
    except ValueError:
        return []
    out = []
    for f in arr if isinstance(arr, list) else []:
        if isinstance(f, dict) and all(isinstance(f.get(k), (str, int, float)) and str(f.get(k)).strip() for k in ("subject", "predicate", "object")):
            out.append({k: " ".join(str(f[k]).split())[:300] for k in ("subject", "predicate", "object")})
    return out


# ------------------------------------------------------------------------------------------------ checking on the page
_ROBOTS = {}


def _allowed(url):
    parts = urllib.parse.urlsplit(url)
    base = "%s://%s" % (parts.scheme, parts.netloc)
    if base not in _ROBOTS:
        rp = urllib.robotparser.RobotFileParser()
        try:
            with urllib.request.urlopen(urllib.request.Request(base + "/robots.txt", headers={"User-Agent": UA}), timeout=15) as r:
                rp.parse(r.read(200000).decode("utf-8", "replace").splitlines())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):                    # robots.txt refused: the site does not want robots
                rp.disallow_all = True
            else:                                       # no robots.txt: nothing is asked of us
                rp.allow_all = True
        except Exception:
            rp.allow_all = True                          # unreachable robots.txt: the page fetch decides
        _ROBOTS[base] = rp
    return _ROBOTS[base].can_fetch(UA, url)


def page_text(html_bytes):
    t = html_bytes.decode("utf-8", "replace")
    t = re.sub(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?s)<!--.*?-->", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return norm_text(html.unescape(t))


def norm_text(t):
    t = str(t).lower()
    for a, b in (("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"'), ("\u2013", "-"), ("\u2014", "-"), ("\u00a0", " "), ("\u2009", " ")):
        t = t.replace(a, b)
    return " ".join(t.split())


_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
_STOP = {"the", "and", "for", "with", "from", "that", "this", "was", "were", "are", "its", "his", "her", "their", "has", "had", "of", "in", "on", "at"}


def forms(obj):
    """the ways a value is commonly written on a page"""
    o = norm_text(obj).strip(" .")
    out = {o}
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", o)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12:
            mn = _MONTHS[mo - 1]
            out |= {"%d %s %d" % (d, mn, y), "%s %d, %d" % (mn, d, y), "%s %d %d" % (mn, d, y), "%s %d" % (mn, d), "%d %s" % (d, mn)}
    m = re.fullmatch(r"(\d{4})-(\d{2})", o)
    if m and 1 <= int(m.group(2)) <= 12:
        out.add("%s %s" % (_MONTHS[int(m.group(2)) - 1], m.group(1)))
    if re.fullmatch(r"\d{4,}", o):
        out.add("{:,}".format(int(o)))
    if re.fullmatch(r"\d{1,3}(,\d{3})+", o):
        out.add(o.replace(",", ""))
    return {f for f in out if len(f) >= 2}


# relations whose words a page uses: a fact about one of them needs one of its words close to the value (RELATION_WINDOW).
# Predicates naming a plain date, place, amount or name need none.
# Verbs (VERBS_AFTER) must follow the value — "Seattle Seahawks defeated…" — so a winner and a loser named side by side are
# not swapped; nouns ("champion", "runner-up") may stand on either side.
VERBS_AFTER = {"won", "win", "wins", "defeated", "beat", "lost", "fell to", "defeated by", "beaten by"}
VERB_REACH = 80
RELATIONS = [
    (r"\blos(?:er|ing|t)\b|runner", ("lost", "losing", "loser", "runner-up", "runners-up", "defeated by", "fell to", "beaten by")),
    (r"\bwin|\bwon\b|champion|victor", ("won", "win", "wins", "winner", "winners", "winning", "champion", "champions", "defeated", "beat",
                                         "victory", "victorious", "title")),
    (r"laureate|award|prize|honou?r|recipient", ("awarded", "laureate", "laureates", "prize", "won", "winner", "recipient", "honoured", "honored")),
    (r"\bborn\b|birth", ("born", "birth", "née")),
    (r"\bdied\b|death", ("died", "death", "passed away")),
    (r"releas|launch", ("release", "released", "launch", "launched", "available")),
    (r"found", ("founded", "founder", "established")),
    (r"coach", ("coach",)),
    (r"\bmvp\b|most valuable", ("mvp", "most valuable")),
    (r"capital", ("capital",)),
    (r"population|inhabitant", ("population", "inhabitants", "residents", "people")),
    (r"elect|president|governor|mayor", ("elected", "election", "president", "won", "inaugurated", "sworn")),
]
RELATION_WINDOW = 250
# winners and losers are named side by side on the same pages, so for them the sentence's structure decides: the winner is
# directly followed by "won / defeated / beat" or directly preceded by "champion: / winner: / won by"; the loser directly
# follows "defeated (the) / beat (the) / lost to / runner-up:" or is directly followed by "lost / fell to".
DIRECTED = {
    "win": (re.compile(r"^[\s,]*(?:(?:have|had|has|also|then|again|eventually)\s+)?(?:won|defeated|beat|wins|win)\b"),
            re.compile(r"(?:\bwinners?|\bchampions?|\bwon by|\bwinning team|\bvictory for|\btitle went to)\W{0,4}(?:the\s+)?$")),
    "lose": (re.compile(r"^[\s,]*(?:(?:were|was|had|have)\s+)?(?:lost|fell to|defeated by|beaten by)\b"),
             re.compile(r"(?:\bdefeated|\bbeat|\blost to|\brunners?-up|\blosing team|\bloser)\W{0,4}(?:the\s+)?$")),
}


def direction(predicate):
    p = norm_text(predicate)
    if re.search(r"\blos(?:er|ing|t)\b|runner", p):
        return "lose"
    if re.search(r"\bwin|\bwon\b|champion|victor", p):
        return "win"
    return None


def relation_words(predicate):
    p = norm_text(predicate)
    for pat, words in RELATIONS:
        if re.search(pat, p):
            return words
    return ()


def confirms(text, subject, obj, predicate=""):
    """the page states the value, with the subject's main words close by and — for a relation like winner, laureate or born —
    one of that relation's words right beside it: (True, how) or (False, why)"""
    words = [w for w in re.findall(r"[a-z0-9][a-z0-9'\-]{2,}", norm_text(subject)) if w not in _STOP]
    need = len(words) if len(words) <= 2 else max(2, int(len(words) * 0.6 + 0.999))
    rel, way = relation_words(predicate), direction(predicate)
    near_subject = False
    for f in forms(obj):
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(f) + r"(?![a-z0-9])")
        for m in pat.finditer(text):
            win = text[max(0, m.start() - WINDOW): m.end() + WINDOW]
            have = sum(1 for w in words if w in win)
            if have < need:
                continue
            near_subject = True
            if way:
                after_re, before_re = DIRECTED[way]
                if after_re.search(text[m.end(): m.end() + 40]) or before_re.search(text[max(0, m.start() - 40): m.start()]):
                    return True, "the page states “%s” with %d of %d words of the subject within %d characters, as the %s by the sentence's " \
                                 "structure" % (f, have, len(words), WINDOW, "winner" if way == "win" else "loser")
                continue
            if rel:
                close = text[max(0, m.start() - RELATION_WINDOW): m.end() + RELATION_WINDOW]
                after = text[m.end(): m.end() + VERB_REACH]
                cue = next((r for r in rel if re.search(r"(?<![a-z])" + re.escape(r) + r"(?![a-z])", after if r in VERBS_AFTER else close)), None)
                if not cue:
                    continue
                return True, "the page states “%s” with %d of %d words of the subject within %d characters and “%s” within %d" % (
                    f, have, len(words), WINDOW, cue, RELATION_WINDOW)
            return True, "the page states “%s” with %d of %d words of the subject within %d characters" % (f, have, len(words), WINDOW)
    if near_subject:
        return False, "the page names the value next to the subject, but not with a word for “%s”" % predicate
    return False, "the page does not state the value next to the subject"


def fetch(url):
    """(final url, normalised page text) — following redirects (search providers hand out redirect links)"""
    if not url.startswith(("http://", "https://")):
        raise GatherError("not a web page")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,text/plain"})
    with urllib.request.urlopen(req, timeout=30) as r:
        final = r.geturl()
        if not _allowed(final):
            raise GatherError("robots.txt asks us not to read this page")
        ctype = r.headers.get("Content-Type") or ""
        if ctype and not any(t in ctype for t in ("html", "text/plain", "xml")):
            raise GatherError("not a text page (%s)" % ctype.split(";")[0])
        return final, page_text(r.read(PAGE_MAX))


# ------------------------------------------------------------------------------------------------ one question
def _budget_path(folder):
    return os.path.join(folder, "gather", "_budget.json")


def _spend(folder, provider):
    p = _budget_path(folder)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        b = json.load(open(p))
    except (OSError, ValueError):
        b = {}
    day = time.strftime("%Y-%m-%d", time.gmtime())
    b = {d: v for d, v in b.items() if d >= time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 86400))}
    used = b.setdefault(day, {}).get(provider, 0)
    if used >= BUDGET.get(provider, 50):
        raise GatherError("today's budget for %s is spent (%d requests)" % (provider, BUDGET.get(provider, 50)))
    b[day][provider] = used + 1
    json.dump(b, open(p, "w"))


def _running(commons_folder, **kw):
    """the gatherer's live state for the Control Panel's progress bar (gather/_running.json)"""
    p = os.path.join(commons_folder, "gather", "_running.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        st = json.load(open(p))
    except (OSError, ValueError):
        st = {}
    if kw.pop("reset", False):
        st = {"pid": os.getpid(), "started": time.time()}
    st.update(kw, heartbeat=time.time())
    with open(p + ".tmp", "w") as f:
        json.dump(st, f)
    os.replace(p + ".tmp", p)


def gather(commons_folder, provider, question, area="history", n=8, model=None, key=None, save=True, subject=None, predicate=None):
    """Ask one question; check every proposal on the provider's own pages; save the confirmed ones. Returns a report.
    subject/predicate (slot mode): the scaffold's exact wording, which proposals must keep."""
    import qbcommons as cm, qbonline as ol, qbharvest as hv
    if provider not in PROVIDERS:
        raise GatherError("unknown provider: %s" % provider)
    app = AREAS.get(area)
    if not app:
        raise GatherError("area must be language, stem or history")
    c = cm.Commons(commons_folder, app)
    c.registry.ensure()
    ok, cls, why = c.registry.check(SOURCE_KEY)
    if not ok:
        raise GatherError("the source '%s' is not approved in the policy registry: %s" % (SOURCE_KEY, why))
    if not hv.master_running(c):
        raise GatherError("harvesting is switched off (master switch)")
    key = key or ol.load_keys(commons_folder).get(provider)
    if not key:
        raise GatherError("no %s key: save it under Harvesting → API keys" % provider)
    blocked = {d.strip().lower() for d in (c.setting("gather:blocked_domains") or "").split(",") if d.strip()}
    _spend(commons_folder, provider)
    t0 = time.time()
    HINT["text"] = (" Use exactly the subject \"%s\" and the predicate \"%s\", one fact for each one." % (subject, predicate)) if subject else ""
    _running(commons_folder, question=question, provider=provider, stage="asking %s" % provider, pages_done=0, pages_total=0)
    text, pages, used_model = PROVIDERS[provider](key, question, n, model)
    proposals = parse_facts(text)
    if subject:                                       # slot mode: only proposals in the scaffold's own wording
        proposals = [f for f in proposals if norm_text(f["subject"]) == norm_text(subject) and norm_text(f["predicate"]) == norm_text(predicate)]
    seen, fetched = [], {}
    uniq = list(dict.fromkeys(pages))
    for u in uniq:                                    # the provider's own pages, each fetched once
        if u in seen:
            continue
        seen.append(u)
        _running(commons_folder, stage="checking the pages", pages_done=len(seen) - 1, pages_total=len(uniq))
        try:
            final, body = fetch(u)
            host = urllib.parse.urlsplit(final).netloc.lower()
            if any(host == d or host.endswith("." + d) for d in blocked):
                fetched[u] = (final, None, "blocked by the admin's list")
            else:
                fetched[u] = (final, body, None)
        except Exception as e:
            fetched[u] = (u, None, str(e)[:160])
    report = {"provider": provider, "model": used_model, "question": question, "area": area, "pages": [], "facts": [], "seconds": None}
    for u, (final, body, err) in fetched.items():
        report["pages"].append({"url": final, "read": body is not None, "why": err})
    items = []
    for f in proposals:
        conf = []
        for u, (final, body, err) in fetched.items():
            if body is None:
                continue
            yes, how = confirms(body, f["subject"], f["object"], f["predicate"])
            if yes and final not in [x[0] for x in conf]:
                conf.append((final, how))
        row = dict(f, kept=bool(conf), pages=[x[0] for x in conf], why=conf[0][1] if conf else "no page the search returned states it")
        report["facts"].append(row)
        if conf:
            ev, hosts = [], set()
            for url, how in conf:
                host = urllib.parse.urlsplit(url).netloc.lower()
                if host in hosts:
                    continue                          # one piece of evidence per site: two sites corroborate, one site twice does not
                hosts.add(host)
                ev.append({"method": "source", "source": host, "source_key": SOURCE_KEY, "licence": "facts (stated on %s)" % host,
                           "url": url, "verdict": "supports", "detail": how})
            items.append({"subject": f["subject"], "predicate": f["predicate"], "object": f["object"], "evidence": ev,
                          "reasoning": ["Found by %s (%s) with web search, for the question: %s" % (provider, used_model, question),
                                        "Checked by QueryBook on the page%s itself: %s" % ("s" if len(ev) > 1 else "", "; ".join(e["url"] for e in ev))]})
    report["seconds"] = round(time.time() - t0, 1)
    if save:
        with c.store.write() as db:
            new = sum(c.save(db, it, "gatherer")[1] for it in items)
            c.harvest_log.write(db, app, "gather:" + provider, "LLM-gathered facts checked on their pages: %s" % question[:200], SOURCE_KEY, cls,
                                "harvested" if items else "skipped",
                                "%d proposed, %d confirmed on the cited pages, %d pages read of %d" % (len(proposals), len(items),
                                                                                                    sum(1 for p in report["pages"] if p["read"]), len(report["pages"])),
                                len(proposals), new, len(items) - new, report["seconds"])
        report["new"] = new
    report["kept"] = len(items)
    os.makedirs(os.path.join(commons_folder, "gather"), exist_ok=True)
    with open(os.path.join(commons_folder, "gather", "runs.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(report, at=core.now_iso()), ensure_ascii=False) + "\n")
    return report


SLOT_QUESTION = {"laureate": "Who received the {name} {year}?", "winner": "Who won the {name} {year}?",
                 "location": "Where was the {name} {year} held?", "awarded to": "Which film won the {name} in {year}?"}


def open_slots(commons_folder, series=None):
    """the scaffold's editions still open, newest first: [(series, year)]"""
    import qbbulk, qbscaffold as sc
    keys = [series] if series else list(sc.SERIES)
    filled = set()
    p = qbbulk.shard_path(commons_folder, "wikidata-series")
    if os.path.exists(p):
        db = qbbulk._ro(p)
        filled = {(a, b) for a, b in db.execute("SELECT series, year FROM slots WHERE filled = 1")}
        db.close()
    out = [(k, y) for k in keys for y in sc.expected_years(k) if (k, y) not in filled]
    return sorted(out, key=lambda x: -x[1])


def fill_slots(commons_folder, provider="gemini", series=None, limit=5, model=None):
    """ask about open editions in the scaffold's own wording; an edition is filled only by facts confirmed on the pages"""
    import qbbulk, qbscaffold as sc
    todo = open_slots(commons_folder, series)[:max(1, int(limit))]
    _running(commons_folder, reset=True, mode="slots", provider=provider, slots_total=len(todo), slots_done=0)
    results = []
    for i, (k, year) in enumerate(todo):
        name, pred = sc.SERIES[k][0], sc.SERIES[k][1]
        subject = "%s %d" % (name, year)
        q = SLOT_QUESTION.get(pred, "What is the {pred} of the {name} {year}?").format(name=name, year=year, pred=pred)
        _running(commons_folder, slots_done=i, slot=subject)
        try:
            r = gather(commons_folder, provider, q, "history", 6, model, subject=subject, predicate=pred)
        except GatherError as e:
            results.append({"slot": subject, "filled": False, "why": str(e)})
            if "budget" in str(e) or "key" in str(e):
                break
            continue
        kept = [f for f in r["facts"] if f["kept"]]
        if kept:
            sh = qbbulk.Shard(commons_folder, "wikidata-series")
            sh.db.execute("INSERT INTO slots(series, year, filled) VALUES(?, ?, 1) ON CONFLICT(series, year) DO UPDATE SET filled = 1", (k, year))
            sh.db.commit(); sh.db.close()
        results.append({"slot": subject, "filled": bool(kept), "values": [f["object"] for f in kept],
                        "why": None if kept else "no proposal was confirmed on the pages"})
    _running(commons_folder, slots_done=len(todo), stage="finished", finished=time.time())
    return results


def recent(commons_folder, limit=20):
    try:
        with open(os.path.join(commons_folder, "gather", "runs.jsonl"), encoding="utf-8") as f:
            return [json.loads(x) for x in f.readlines()[-limit:]][::-1]
    except (OSError, ValueError):
        return []


# ------------------------------------------------------------------------------------------------ the Control Panel
def running(commons_folder):
    try:
        st = json.load(open(os.path.join(commons_folder, "gather", "_running.json")))
    except (OSError, ValueError):
        return None
    alive = not st.get("finished") and time.time() - st.get("heartbeat", 0) < 180
    return dict(st, alive=alive)


def status(commons):
    import qbonline as ol, qbscaffold as sc
    keys = ol.load_keys(commons.folder)
    try:
        b = json.load(open(_budget_path(commons.folder))).get(time.strftime("%Y-%m-%d", time.gmtime()), {})
    except (OSError, ValueError):
        b = {}
    slots = open_slots(commons.folder)
    return {"version": VERSION, "approved": commons.registry.check(SOURCE_KEY)[0],
            "providers": [{"id": p, "model": MODELS[p], "key_set": p in keys, "used_today": b.get(p, 0), "budget": BUDGET[p]} for p in PROVIDERS],
            "running": running(commons.folder), "recent": recent(commons.folder, 10),
            "open_slots": {k: sum(1 for s, _ in slots if s == k) for k in sc.SERIES}, "series": {k: v[0] for k, v in sc.SERIES.items()}}


def start(commons, p, program_dir):
    """start a gathering run (admin: it spends money on the provider's account); a separate process, like the bulk agents"""
    import subprocess
    commons.approvals._require(p.get("passphrase") or "")
    st = running(commons.folder)
    if st and st.get("alive"):
        raise GatherError("a gathering run is already going")
    prov = p.get("provider") or "gemini"
    if prov not in PROVIDERS:
        raise GatherError("unknown provider")
    args = [sys.executable, os.path.join(program_dir, "qbgather.py")]
    if (p.get("mode") or "ask") == "slots":
        args += ["slots", "--commons", commons.folder, "--provider", prov, "--limit", str(max(1, min(int(p.get("limit") or 5), 50)))]
        if p.get("series"):
            args += ["--series", str(p["series"])]
    else:
        q = " ".join(str(p.get("question") or "").split())[:500]
        if len(q) < 8:
            raise GatherError("ask a question")
        args += ["ask", "--commons", commons.folder, "--provider", prov, "--area", p.get("area") or "history", q]
    kw = {"creationflags": 0x00000008 | 0x00000200} if os.name == "nt" else {"start_new_session": True}
    _running(commons.folder, reset=True, stage="starting", provider=prov)
    subprocess.Popen(args, cwd=program_dir, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    return {"summary": "the gatherer is starting (%s)" % prov, **status(commons)}


def add_routes(api, commons, program_dir):
    import qbcore as core_

    @api.get("/api/gather")
    def g_status(p):
        """the fact gatherer: providers (key set, used today), the run in progress, recent runs, open scaffold slots"""
        return status(commons)

    @api.post("/api/gather/start")
    def g_start(p):
        """ask a question, or fill open scaffold slots (admin passphrase: it spends on the provider's account)"""
        try:
            return start(commons, p, program_dir)
        except (GatherError, ValueError) as e:
            raise core_.UserError(str(e))


# ------------------------------------------------------------------------------------------------ self-test (no network)
def self_test():
    out = []
    ok = lambda n, c: out.append((n, bool(c)))
    page = page_text(b"<html><script>var x='1921';</script><p>The Nobel Prize in Physics 1921 was awarded to Albert&nbsp;Einstein "
                     b"\xe2\x80\x9cfor his services to Theoretical Physics\xe2\x80\x9d.</p><p>Milan Cortina: 6 February 2026 to 22 February 2026."
                     b" Population 1,371,498.</p></html>")
    ok("a page's script text is not read as content", "var x" not in page)
    ok("the value with the subject nearby is confirmed", confirms(page, "Nobel Prize in Physics 1921", "Albert Einstein")[0])
    ok("dates written ISO match the page's '6 February 2026'", confirms(page, "2026 Winter Olympics Milan Cortina", "2026-02-06")[0])
    ok("numbers match with thousands separators", confirms(page, "Milan Cortina population", "1371498")[0])
    ok("a value the page does not state is refused", not confirms(page, "Nobel Prize in Physics 1921", "Niels Bohr")[0])
    ok("part of a longer number is not a match", not confirms(page, "Nobel Prize in Physics", "92")[0])
    game = page_text(b"<p>Super Bowl LX was played on February 8, 2026. The Seattle Seahawks defeated the New England Patriots 29-13 to win "
                     b"their second Super Bowl title.</p><p>Francis Halzen was born in Tienen.</p>")
    ok("relation: the winner is the team before 'defeated'", confirms(game, "Super Bowl LX", "Seattle Seahawks", "winning team")[0])
    ok("relation: a swapped winner is refused", not confirms(game, "Super Bowl LX", "New England Patriots", "winning team")[0])
    ok("relation: 'born' must stand by a place of birth; a plain date needs no relation word",
       confirms(game, "Francis Halzen", "Tienen", "place of birth")[0] and confirms(game, "Super Bowl LX", "2026-02-08", "date")[0])
    ok("the model's reply is parsed from a code fence; malformed items are dropped",
       parse_facts('```json\n[{"subject": "A", "predicate": "b", "object": "C"}, {"subject": "", "predicate": "x", "object": "y"}]\n```')
       == [{"subject": "A", "predicate": "b", "object": "C"}])
    return out


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("ask")
    a.add_argument("--commons", required=True)
    a.add_argument("--provider", default="gemini", choices=sorted(PROVIDERS))
    a.add_argument("--area", default="history", choices=sorted(AREAS))
    a.add_argument("--n", type=int, default=8)
    a.add_argument("--model")
    a.add_argument("question")
    sl = sp.add_parser("slots")
    sl.add_argument("--commons", required=True)
    sl.add_argument("--provider", default="gemini", choices=sorted(PROVIDERS))
    sl.add_argument("--series")
    sl.add_argument("--limit", type=int, default=5)
    sp.add_parser("self-test")
    ns = ap.parse_args(argv)
    if ns.cmd == "ask":
        _running(ns.commons, reset=True, mode="ask", provider=ns.provider)
        try:
            print(json.dumps(gather(ns.commons, ns.provider, ns.question, ns.area, ns.n, ns.model), indent=1, ensure_ascii=False))
        finally:
            _running(ns.commons, stage="finished", finished=time.time())
    elif ns.cmd == "slots":
        print(json.dumps(fill_slots(ns.commons, ns.provider, ns.series, ns.limit), indent=1, ensure_ascii=False))
    else:
        res = self_test()
        for n, g in res:
            print(("  [OK]   " if g else "  [FAIL] ") + n)
        print("\n  %d of %d checks passed" % (sum(1 for x in res if x[1]), len(res)))
        return 0 if all(x[1] for x in res) else 1


if __name__ == "__main__":
    sys.exit(main())
