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
MODELS = {"gemini": "gemini-3.5-flash", "perplexity": "sonar-pro", "openai": "gpt-5", "anthropic": "claude-opus-5-5"}
BUDGET = {"gemini": 200, "perplexity": 100, "openai": 100, "anthropic": 100}     # requests a day per provider
PAGE_MAX = 2 << 20
WINDOW = 600                                                                     # characters around the value to find the subject
PROMPT = """Use web search to answer: {q}

Reply with only a JSON array (no other text) of at most {n} facts you found on the web pages, each
{{"subject": "...", "predicate": "...", "object": "..."}}. The object must be short: a name, a number, a place, or a date
written YYYY-MM-DD (or YYYY-MM, or YYYY). Use the full proper name of the subject. Only facts the pages state."""


EXTRACT = """Turn the answer below into at most {n} facts, using only what the answer states. Reply with only a JSON array
of {{"subject": "...", "predicate": "...", "object": "..."}}. The object must be short: a name, a number, a place, or a date
written YYYY-MM-DD (or YYYY-MM, or YYYY). Use the full proper name of the subject.

Answer:
{answer}"""


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
    r2 = _post(url, {"contents": [{"role": "user", "parts": [{"text": EXTRACT.format(n=n, answer=answer)}]}]}, {"x-goog-api-key": key})
    text = "".join(p.get("text", "") for p in ((r2.get("candidates") or [{}])[0].get("content") or {}).get("parts", []))
    return text, pages, model


def ask_perplexity(key, question, n, model=None):
    model = model or MODELS["perplexity"]
    r = _post("https://api.perplexity.ai/chat/completions", {"model": model, "messages": [{"role": "user", "content": PROMPT.format(q=question, n=n)}]},
              {"Authorization": "Bearer " + key})
    text = ((r.get("choices") or [{}])[0].get("message") or {}).get("content", "")
    pages = list(r.get("citations") or []) + [s["url"] for s in r.get("search_results") or [] if s.get("url")]
    return text, pages, model


def ask_openai(key, question, n, model=None):
    model = model or MODELS["openai"]
    r = _post("https://api.openai.com/v1/responses", {"model": model, "tools": [{"type": "web_search"}], "input": PROMPT.format(q=question, n=n)},
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
    messages = [{"role": "user", "content": PROMPT.format(q=question, n=n)}]
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


def confirms(text, subject, obj):
    """the page states the value, with the subject's main words close by: (True, how) or (False, why)"""
    words = [w for w in re.findall(r"[a-z0-9][a-z0-9'\-]{2,}", norm_text(subject)) if w not in _STOP]
    need = len(words) if len(words) <= 2 else max(2, int(len(words) * 0.6 + 0.999))
    for f in forms(obj):
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(f) + r"(?![a-z0-9])")
        for m in pat.finditer(text):
            win = text[max(0, m.start() - WINDOW): m.end() + WINDOW]
            have = sum(1 for w in words if w in win)
            if have >= need:
                return True, "the page states “%s” with %d of %d words of the subject within %d characters" % (f, have, len(words), WINDOW)
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


def gather(commons_folder, provider, question, area="history", n=8, model=None, key=None, save=True):
    """Ask one question; check every proposal on the provider's own pages; save the confirmed ones. Returns a report."""
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
    text, pages, used_model = PROVIDERS[provider](key, question, n, model)
    proposals = parse_facts(text)
    seen, fetched = [], {}
    for u in pages:                                   # the provider's own pages, each fetched once
        if u in seen:
            continue
        seen.append(u)
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
            yes, how = confirms(body, f["subject"], f["object"])
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


def recent(commons_folder, limit=20):
    try:
        with open(os.path.join(commons_folder, "gather", "runs.jsonl"), encoding="utf-8") as f:
            return [json.loads(x) for x in f.readlines()[-limit:]][::-1]
    except (OSError, ValueError):
        return []


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
    sp.add_parser("self-test")
    ns = ap.parse_args(argv)
    if ns.cmd == "ask":
        print(json.dumps(gather(ns.commons, ns.provider, ns.question, ns.area, ns.n, ns.model), indent=1, ensure_ascii=False))
    else:
        res = self_test()
        for n, g in res:
            print(("  [OK]   " if g else "  [FAIL] ") + n)
        print("\n  %d of %d checks passed" % (sum(1 for x in res if x[1]), len(res)))
        return 0 if all(x[1] for x in res) else 1


if __name__ == "__main__":
    sys.exit(main())
