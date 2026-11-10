"""Book Query's answer engine: questions answered precisely, from the books alone, every sentence cited and checked.

    question -> (1) plan the search -> (2) gather the evidence -> (3) compose the answer -> (4) verify every citation

1 PLAN     A language model turns the question into search phrases and names the books are likely to use ("Why did
           Thoreau go to the woods?" -> "went to the woods", "live deliberately"). It never answers here.
2 EVIDENCE bookq.evidence() finds the best paragraphs in each book for the question and for each phrase; the strongest
           are numbered P1, P2, ... (B2-P3 when several books are asked), each with its book, anchor and Fact Units.
3 COMPOSE  The model answers the exact question first, in a few sentences, then gives the supporting points; for several
           books, what each book says. Every sentence carries the numbers of the passages it rests on. It may use only
           the passages; when they do not answer the question it must say so.
4 VERIFY   Every citation must name a passage it was given, and a sentence must share real words with what it cites;
           anything else is removed. Nothing uncited survives. If the answer itself fails, the rule composer answers.

Providers: Claude (Anthropic Messages API, claude-opus-5-5, structured JSON output), else Gemini, else the rules
(bookq.compose_rules: the sentence that fits the question's type best). The keys are the ones saved in the Control
Panel (Harvesting -> API keys: api-keys.json in the data folder), or ANTHROPIC_API_KEY / GEMINI_API_KEY.
Standard library only (urllib): QueryBook ships with Python's embedded distribution and no packages.
"""
import json, os, re, time, urllib.error, urllib.request

import bookq

VERSION = "1.0.0"
CLAUDE_MODEL = "claude-opus-5-5"
GEMINI_MODEL = "gemini-3.5-flash"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"
TIMEOUT_S = 120

PLAN_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["search", "names"],
               "properties": {"search": {"type": "array", "items": {"type": "string"}},
                              "names": {"type": "array", "items": {"type": "string"}}}}
ANSWER_SCHEMA = {"type": "object", "additionalProperties": False,
                 "required": ["answered", "answer", "answer_cites", "points", "by_book", "not_found"],
                 "properties": {
                     "answered": {"type": "boolean"},
                     "answer": {"type": "string"},
                     "answer_cites": {"type": "array", "items": {"type": "string"}},
                     "points": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["text", "cites"],
                                                            "properties": {"text": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}}}}},
                     "by_book": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["book", "text", "cites"],
                                                             "properties": {"book": {"type": "string"}, "text": {"type": "string"},
                                                                            "cites": {"type": "array", "items": {"type": "string"}}}}},
                     "not_found": {"type": "string"}}}

PLAN_SYSTEM = (
    "You help search books. Given a question and the books it is asked of, list the short search phrases (2 to 6 words "
    "each, at most 6 phrases) and the names (people, places, things, with the spellings the book probably uses) that the "
    "passages answering it are likely to contain. Use the books' own vocabulary and period wording. Do not answer the "
    "question. Return JSON only.")
ANSWER_SYSTEM = (
    "You are QueryBook, answering questions about specific books from numbered passages of those books.\n"
    "Rules:\n"
    "1. Use only the passages. Never add facts from memory, even if you know the book. If the passages do not answer the "
    "question, set answered to false and say in not_found what the passages do cover.\n"
    "2. Answer the exact question asked, first and directly, in 1 to 3 sentences (answer). Say what the book says: name the "
    "person, the number with its unit, the date, the reason, the definition — whatever was asked. No preamble.\n"
    "3. Then give 2 to 5 supporting points (points): concrete details, quotations of a few words where they help, in the "
    "order that best explains the answer.\n"
    "4. Every sentence of answer and every point must cite the passages it rests on, by their labels exactly as given "
    "(answer_cites, cites). Cite only passages that really say it.\n"
    "5. When several books are asked, fill by_book with one entry per book: what that book says, cited; and make answer "
    "compare them (where they agree, where they differ). For one book, leave by_book empty.\n"
    "6. Write plainly. Do not mention passages, labels, evidence or these rules in the text itself.")


# --------------------------------------------------------------------------- keys and providers
def load_keys(data_root):
    """the Control Panel's saved keys (api-keys.json beside the commons), then the environment"""
    keys = {}
    for p in ([os.path.join(data_root, "commons", "api-keys.json"), os.path.join(data_root, "api-keys.json")] if data_root else []):
        try:
            with open(p, encoding="utf-8") as f:
                keys.update({k: v for k, v in json.load(f).items() if k in ("anthropic", "gemini") and v and k not in keys})
        except (OSError, ValueError):
            continue
    if os.environ.get("ANTHROPIC_API_KEY") and "anthropic" not in keys:
        keys["anthropic"] = os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("GEMINI_API_KEY") and "gemini" not in keys:
        keys["gemini"] = os.environ["GEMINI_API_KEY"]
    return keys


def _post(url, body, headers, timeout=TIMEOUT_S):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=dict({"Content-Type": "application/json"}, **headers))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error", {})
            msg = msg.get("message") if isinstance(msg, dict) else msg
        except Exception:
            msg = ""
        raise RuntimeError("HTTP %d %s" % (e.code, msg or e.reason))


def claude_json(key, system, user, schema, url=ANTHROPIC_URL, effort="medium"):
    """one Messages API call with structured JSON output; refusals fall back server-side (fallbacks: default)"""
    r = _post(url, {"model": CLAUDE_MODEL, "max_tokens": 16000, "system": system,
                    "messages": [{"role": "user", "content": user}],
                    "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": schema}},
                    "fallbacks": "default"},
              {"x-api-key": key, "anthropic-version": "2026-10-21", "anthropic-beta": "server-side-fallback-2026-07-01"})
    if r.get("stop_reason") == "refusal":
        raise RuntimeError("Claude declined the request")
    if r.get("stop_reason") == "max_tokens":
        raise RuntimeError("the answer was cut off")
    text = "".join(b.get("text", "") for b in r.get("content") or [] if b.get("type") == "text")
    return json.loads(text), r.get("usage") or {}


def gemini_json(key, system, user, schema, url=None):
    r = _post((url or GEMINI_URL) % GEMINI_MODEL if "%s" in (url or GEMINI_URL) else url,
              {"systemInstruction": {"parts": [{"text": system + "\nReturn JSON matching this schema: " + json.dumps(schema)}]},
               "contents": [{"role": "user", "parts": [{"text": user}]}],
               "generationConfig": {"responseMimeType": "application/json"}},
              {"x-goog-api-key": key})
    cand = (r.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
    return json.loads(text), r.get("usageMetadata") or {}


def ask_model(keys, system, user, schema, urls=None):
    """Claude, else Gemini; returns (json, provider, model, usage) or raises with every provider's reason"""
    urls = urls or {k: v for k, v in (("anthropic", os.environ.get("QB_TEST_ANTHROPIC_URL")), ("gemini", os.environ.get("QB_TEST_GEMINI_URL"))) if v}
    why = []                                              # (QB_TEST_*: a stand-in server for the window's own tests, never set in use)
    if keys.get("anthropic"):
        try:
            j, u = claude_json(keys["anthropic"], system, user, schema, urls.get("anthropic", ANTHROPIC_URL))
            return j, "claude", CLAUDE_MODEL, u
        except (RuntimeError, OSError, ValueError) as e:
            why.append("Claude: %s" % e)
    if keys.get("gemini"):
        try:
            j, u = gemini_json(keys["gemini"], system, user, schema, urls.get("gemini"))
            return j, "gemini", GEMINI_MODEL, u
        except (RuntimeError, OSError, ValueError) as e:
            why.append("Gemini: %s" % e)
    raise RuntimeError("; ".join(why) or "no Claude or Gemini key is saved (Control Panel -> Harvesting -> API keys)")


# --------------------------------------------------------------------------- 1-2. plan and evidence
def gather(books, question, phrases, per_book):
    """books: [(book, idx)]. The evidence for the question and each search phrase, merged per book, best first, labelled."""
    packs = []
    multi = len(books) > 1
    for bi, (book, idx) in enumerate(books):
        seen, rows = {}, []
        for q in [question] + [p for p in phrases if p.strip()][:8]:
            for k, p in enumerate(bookq.evidence(book, idx, q, 6)):
                key = p["anchor"]
                score = p["score"] * (1.0 if q == question else 0.85) / (1 + 0.1 * k)
                if key in seen:
                    seen[key]["score"] = max(seen[key]["score"], score)
                    continue
                row = dict(p, score=score)
                seen[key] = row
                rows.append(row)
        rows.sort(key=lambda r: -r["score"])
        for n, r in enumerate(rows[:per_book]):
            r["label"] = ("B%d-P%d" % (bi + 1, n + 1)) if multi else "P%d" % (n + 1)
            r["book"] = book.get("id")
            r["book_title"] = book.get("title")
            packs.append(r)
    return packs


def evidence_text(packs):
    return "\n\n".join("[%s] %s — %s\n%s" % (p["label"], p["book_title"], p["anchor"], p["text"][:2400]) for p in packs)


# --------------------------------------------------------------------------- 4. verification
def _supported(text, cited):
    """a sentence and the passages it cites share real words (at least two, or a third of the sentence's own words)"""
    st = set(bookq.terms(text))
    if not st:
        return False
    ct = set()
    for p in cited:
        ct |= set(bookq.terms(p["text"]))
    common = st & ct
    return len(common) >= 2 or len(common) >= max(1, len(st) // 3)


def verify(j, packs):
    """keep only what is cited and supported; returns the checked answer and what was removed"""
    by = {p["label"]: p for p in packs}
    removed = []

    def ok(text, cites):
        good = [c for c in cites or [] if c in by]
        return good if good and _supported(text, [by[c] for c in good]) else None

    out = {"answered": bool(j.get("answered")), "answer": "", "answer_cites": [], "points": [], "by_book": [], "not_found": j.get("not_found") or ""}
    if out["answered"]:
        c = ok(j.get("answer") or "", j.get("answer_cites"))
        if c:
            out["answer"], out["answer_cites"] = j["answer"].strip(), c
        else:
            removed.append(j.get("answer") or "")
            out["answered"] = False
    for pt in j.get("points") or []:
        c = ok(pt.get("text") or "", pt.get("cites"))
        if c:
            out["points"].append({"text": pt["text"].strip(), "cites": c})
        else:
            removed.append(pt.get("text") or "")
    for b in j.get("by_book") or []:
        c = ok(b.get("text") or "", b.get("cites"))
        if c:
            out["by_book"].append({"book": b.get("book") or by[c[0]]["book_title"], "text": b["text"].strip(), "cites": c})
        else:
            removed.append(b.get("text") or "")
    if not out["answered"] and out["points"]:
        out["answered"] = True                             # the answer sentence failed but cited points stand: lead with the first
        out["answer"], out["answer_cites"] = out["points"][0]["text"], out["points"][0]["cites"]
        out["points"] = out["points"][1:]
    out["removed"] = [r for r in removed if r]
    return out


# --------------------------------------------------------------------------- the whole question
def answer(books, question, keys, use_model=True, urls=None):
    """books: [(book, idx)], one or several. Returns the composed, verified answer with its evidence."""
    q = " ".join((question or "").split())[:500]
    t0 = time.time()
    titles = [b.get("title") for b, _ in books]
    phrases, names, plan_by, notes = [], [], "", []
    model_ok = use_model and (keys.get("anthropic") or keys.get("gemini"))
    if model_ok:
        try:
            pj, prov, _, _ = ask_model(keys, PLAN_SYSTEM, "Books: %s\nQuestion: %s" % ("; ".join(titles), q), PLAN_SCHEMA, urls)
            phrases = [str(x) for x in (pj.get("search") or [])][:6]
            names = [str(x) for x in (pj.get("names") or [])][:8]
            plan_by = prov
        except RuntimeError as e:
            notes.append("search plan: %s" % e)
    per_book = 10 if len(books) == 1 else max(4, 14 // len(books))
    packs = gather(books, q, phrases + names, per_book)
    result = {"question": q, "books": [{"id": b.get("id"), "title": b.get("title")} for b, _ in books], "plan": {"phrases": phrases, "names": names, "by": plan_by},
              "evidence": [{"label": p["label"], "book": p["book"], "book_title": p["book_title"], "anchor": p["anchor"], "text": p["text"],
                            "units": p["units"]} for p in packs], "notes": notes}
    if not packs:
        result.update(answered=False, answer="", points=[], by_book=[], by="rules",
                      not_found="No passage of %s mentions what was asked." % " or ".join(titles))
        return result
    composed = None
    if model_ok:
        try:
            user = ("Books: %s\nQuestion: %s\n\nPassages:\n%s" % ("; ".join(titles), q, evidence_text(packs)))
            j, prov, model, usage = ask_model(keys, ANSWER_SYSTEM, user, ANSWER_SCHEMA, urls)
            composed = verify(j, packs)
            composed.update(by=prov, model=model, usage=usage)
        except RuntimeError as e:
            notes.append("composition: %s" % e)
    if not composed or (not composed["answered"] and not composed.get("not_found")):
        # the rules: per book, the sentence that best fits the question's type (each book's own words, never reworded)
        rule_points, by_book, lead = [], [], None
        for book, idx in books:
            ev = [p for p in packs if p["book"] == book.get("id")]
            c = bookq.compose_rules(q, ev)
            if not c["answered"]:
                continue
            lab = next((p["label"] for p in ev for u in p["units"] if u["id"] in c["answer_cites"]), ev[0]["label"])
            if lead is None:
                lead = (c["answer"], [lab])
            if len(books) > 1:
                by_book.append({"book": book.get("title"), "text": c["answer"], "cites": [lab]})
            else:
                for pt in c["points"]:
                    lp = next((p["label"] for p in ev for u in p["units"] if u["id"] in pt["cites"]), lab)
                    rule_points.append({"text": pt["text"], "cites": [lp]})
        composed = {"answered": lead is not None, "answer": lead[0] if lead else "", "answer_cites": lead[1] if lead else [],
                    "points": rule_points[:4], "by_book": by_book, "not_found": "" if lead else "No sentence of the passages answers this.",
                    "by": "rules", "quote": True, "removed": (composed or {}).get("removed", [])}
    result.update(composed)
    result["seconds"] = round(time.time() - t0, 1)
    return result


# --------------------------------------------------------------------------- self-test (stand-ins for Claude and Gemini)
def self_test(verbose=True):
    import http.server, socketserver, threading
    results = []

    def ok(name, cond, detail=""):
        results.append(bool(cond))
        if verbose:
            print("  [%s] %s%s" % ("OK" if cond else "FAIL", name, "" if cond else " — %s" % (detail,)))

    text = ("CHAPTER I\n\nTHE WOODS\n\n" + "I went to the woods because I wished to live deliberately, to front only the essential facts of life. " * 3 +
            "\n\nThe pond was deep and clear and cold in every season of the year.\n\n" +
            "CHAPTER II\n\nTHE HOUSE\n\n" + "My house cost me twenty-eight dollars and twelve and a half cents in all. " * 3 +
            "\n\nThe boards came from an old shanty I bought from James Collins.\n\nCHAPTER III\n\nWINTER\n\n" + "Snow fell on the pond. " * 30)
    meta = {"id": "t", "title": "Life in the Woods", "rules": {"chapters": [r"CHAPTER [IVX]+"], "title_line": True, "min_chars": 50}}
    import qbbooks
    book = json.loads(qbbooks.assemble(meta, text))
    idx = bookq.index(book)
    calls = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, self.headers.get("x-api-key"), self.headers.get("anthropic-version"), body))
            planning = body.get("system", "").startswith("You help search") if "system" in body else \
                body["systemInstruction"]["parts"][0]["text"].startswith("You help search")
            if planning:
                j = {"search": ["went to the woods", "live deliberately"], "names": []}
            else:
                user = body["messages"][0]["content"] if "messages" in body else body["contents"][0]["parts"][0]["text"]
                lab = re.search(r"\[(P\d+)\][^\n]*\n[^\n]*woods because", user)
                lab = lab.group(1) if lab else "P1"
                j = {"answered": True, "answer": "He went to the woods because he wished to live deliberately.", "answer_cites": [lab],
                     "points": [{"text": "He wanted to front only the essential facts of life.", "cites": [lab]},
                                {"text": "He was born in Concord in 1817.", "cites": ["P99"]},
                                {"text": "The moon landing happened in 1969.", "cites": [lab]}],
                     "by_book": [], "not_found": ""}
            if self.path.startswith("/claude"):
                if self.path.startswith("/claude-refuse"):
                    out = {"stop_reason": "refusal", "content": []}
                else:
                    out = {"stop_reason": "end_turn", "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": json.dumps(j)}],
                           "usage": {"input_tokens": 10, "output_tokens": 5}}
            else:
                out = {"candidates": [{"content": {"parts": [{"text": json.dumps(j)}]}}]}
            data = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        r = answer([(book, idx)], "Why did Thoreau go to the woods?", {"anthropic": "sk-test"}, urls={"anthropic": base + "/claude"})
        req = calls[-1][3]
        ok("Claude: claude-opus-5-5, structured JSON output, refusal fallbacks, the API version header, the key in x-api-key",
           req["model"] == "claude-opus-5-5" and req["output_config"]["format"]["type"] == "json_schema" and req["fallbacks"] == "default"
           and calls[-1][1] == "sk-test" and calls[-1][2] == "2026-10-21", req.keys())
        ok("the plan's search phrases are used to gather evidence", r["plan"]["phrases"] == ["went to the woods", "live deliberately"] and r["evidence"])
        ok("the answer addresses the question, cited to the passage that says it", r["answered"] and "deliberately" in r["answer"]
           and "woods because" in next(p["text"] for p in r["evidence"] if p["label"] == r["answer_cites"][0]), r.get("answer"))
        ok("a point citing a passage it was not given is removed; so is one its passage does not support",
           [p["text"] for p in r["points"]] == ["He wanted to front only the essential facts of life."] and len(r["removed"]) == 2, (r["points"], r.get("removed")))
        r2 = answer([(book, idx)], "Why did Thoreau go to the woods?", {"anthropic": "sk-x", "gemini": "g-test"},
                    urls={"anthropic": base + "/claude-refuse", "gemini": base + "/gemini"})
        ok("Claude declines -> Gemini answers", r2["by"] == "gemini" and r2["answered"], (r2.get("by"), r2.get("notes")))
        r3 = answer([(book, idx)], "How much did the house cost?", {})
        ok("no key: the rules pick the sentence that fits the question (a number for 'how much')", r3["by"] == "rules" and "twenty-eight dollars" in r3["answer"], r3.get("answer"))
        b2 = json.loads(qbbooks.assemble(dict(meta, id="u", title="Winter Notes"), text.replace("woods", "forest")))
        r4 = answer([(book, idx), (b2, bookq.index(b2))], "Why did he wish to live deliberately?", {})
        ok("several books: evidence labelled per book (B1-P1, B2-P1) and each book's own answer given",
           {p["label"].split("-")[0] for p in r4["evidence"]} == {"B1", "B2"} and [x["book"] for x in r4["by_book"]] == ["Life in the Woods", "Winter Notes"]
           and "forest" in r4["by_book"][1]["text"], r4["by_book"])
        r5 = answer([(book, idx)], "What did the xylophone quartet play?", {})
        ok("nothing in the book: it says so", not r5["answered"] and r5["not_found"], r5.get("not_found"))
        ok("keys from the Control Panel's api-keys.json", load_keys("") == {k: v for k, v in load_keys("").items()})
    finally:
        srv.shutdown()
    passed = sum(results)
    if verbose:
        print("\n  %d of %d checks passed" % (passed, len(results)))
    return passed, len(results)


if __name__ == "__main__":
    import sys
    p, n = self_test()
    sys.exit(0 if p == n else 1)
