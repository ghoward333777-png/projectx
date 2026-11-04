"""LLM and AI usage: every call to a paid model, its time, tokens and estimated charge; the subscriptions they bill to.

Every QueryBook program records each call it makes to an LLM or another paid AI service (Gemini, OpenAI, Anthropic,
Perplexity; cloud voices; Speech-to-Text; video generation) in one ledger in the shared folder (ai-usage.sqlite):
when, which program, what for, the provider and model, tokens in and out (as the provider reported them), characters or
minutes for voice and speech recognition, how long the call took, whether it worked, and its estimated charge.

Charges are ESTIMATES from list prices (PRICES, editable in the Control Panel). The provider's own bill is
authoritative — its billing page is linked for every subscription. Unknown prices are shown as "not priced", never
guessed. No key, prompt or answer is ever stored here. Standard library only."""
import json, os, sqlite3, threading, time

FOLDER = {"path": None}
_LOCK = threading.Lock()

# provider: {model prefix: price} — USD. Tokens per 1 million; voice per 1 million characters; audio per minute; video per second.
PRICES = {
    "gemini": {"gemini-2.5-flash": {"in_per_m": 0.30, "out_per_m": 2.50}, "gemini-2.5-pro": {"in_per_m": 1.25, "out_per_m": 10.00},
               "gemini-2.0-flash": {"in_per_m": 0.10, "out_per_m": 0.40}},
    "openai": {"gpt-4.1-mini": {"in_per_m": 0.40, "out_per_m": 1.60}, "gpt-4.1": {"in_per_m": 2.00, "out_per_m": 8.00},
               "gpt-4o-mini": {"in_per_m": 0.15, "out_per_m": 0.60}, "gpt-4o": {"in_per_m": 2.50, "out_per_m": 10.00},
               "tts": {"per_m_chars": 15.00}},
    "anthropic": {"claude-haiku": {"in_per_m": 1.00, "out_per_m": 5.00}, "claude-sonnet": {"in_per_m": 3.00, "out_per_m": 15.00},
                  "claude-opus": {"in_per_m": 15.00, "out_per_m": 75.00}},
    "perplexity": {"sonar": {"in_per_m": 1.00, "out_per_m": 1.00}},
    "google-tts": {"standard": {"per_m_chars": 4.00}, "wavenet": {"per_m_chars": 16.00}, "neural2": {"per_m_chars": 16.00},
                   "chirp": {"per_m_chars": 30.00}, "": {"per_m_chars": 16.00}},
    "google-stt": {"": {"per_minute": 0.024}},
    "azure-tts": {"": {"per_m_chars": 16.00}},
    "polly": {"": {"per_m_chars": 16.00}},
}
PRICES_NOTE = ("List prices as known to QueryBook in 2025–2026 (the providers' public pricing pages); they change — check the provider's page and "
               "edit them here. ElevenLabs, HeyGen and D-ID bill by subscription credits: their usage is counted (characters, seconds) and "
               "charged through the subscription's monthly fee.")

PROVIDERS = {   # provider: (title, kind, billing page)
    "gemini": ("Google Gemini (AI Studio / Vertex)", "LLM", "https://aistudio.google.com/usage"),
    "openai": ("OpenAI", "LLM", "https://platform.openai.com/usage"),
    "anthropic": ("Anthropic Claude", "LLM", "https://console.anthropic.com/settings/billing"),
    "perplexity": ("Perplexity", "LLM", "https://www.perplexity.ai/account/api/billing"),
    "google-tts": ("Google Cloud Text-to-Speech", "voice", "https://console.cloud.google.com/billing"),
    "google-stt": ("Google Cloud Speech-to-Text", "speech recognition", "https://console.cloud.google.com/billing"),
    "elevenlabs": ("ElevenLabs", "voice", "https://elevenlabs.io/app/subscription"),
    "azure-tts": ("Azure Speech", "voice", "https://portal.azure.com/#view/Microsoft_Azure_CostManagement"),
    "polly": ("Amazon Polly", "voice", "https://console.aws.amazon.com/billing/home"),
    "veo": ("Google Veo / Gemini video", "video", "https://aistudio.google.com/usage"),
    "heygen": ("HeyGen", "video", "https://app.heygen.com/settings/billing"),
    "d-id": ("D-ID", "video", "https://studio.d-id.com/account-settings"),
}

SCHEMA = """CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY, at REAL NOT NULL, app TEXT, purpose TEXT, provider TEXT NOT NULL,
  model TEXT, input_tokens INTEGER, output_tokens INTEGER, units REAL, unit TEXT, seconds REAL, ok INTEGER, error TEXT, cost_usd REAL,
  priced INTEGER);
CREATE INDEX IF NOT EXISTS calls_at ON calls(at);"""


def configure(folder):
    """the shared folder (each program's Commons sets it at start)"""
    if folder and os.path.isdir(folder):
        FOLDER["path"] = folder


def _path(folder=None):
    f = folder or FOLDER["path"] or os.environ.get("QB_COMMONS_DATA")
    return os.path.join(f, "ai-usage.sqlite") if f and os.path.isdir(f) else None


def _db(folder=None):
    p = _path(folder)
    if not p:
        return None
    db = sqlite3.connect(p, timeout=30)
    db.executescript(SCHEMA)
    return db


def prices(folder=None):
    out = json.loads(json.dumps(PRICES))
    f = folder or FOLDER["path"]
    try:
        with open(os.path.join(f, "ai-prices.json"), encoding="utf-8") as fh:
            for prov, models in (json.load(fh) or {}).items():
                out.setdefault(prov, {}).update(models)
    except (OSError, ValueError, TypeError):
        pass
    return out


def save_prices(edits, folder=None):
    f = folder or FOLDER["path"]
    p = os.path.join(f, "ai-prices.json")
    cur = {}
    try:
        with open(p, encoding="utf-8") as fh:
            cur = json.load(fh) or {}
    except (OSError, ValueError):
        pass
    for prov, models in (edits or {}).items():
        for model, pr in (models or {}).items():
            clean = {k: float(v) for k, v in (pr or {}).items() if k in ("in_per_m", "out_per_m", "per_m_chars", "per_minute", "per_second") and v not in (None, "")}
            if clean:
                cur.setdefault(str(prov), {})[str(model)] = clean
    with open(p + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(cur, fh, indent=1)
    os.replace(p + ".tmp", p)
    return prices(f)


def price_for(provider, model, table):
    t = table.get(provider) or {}
    m = (model or "").lower()
    best = None
    for k in t:
        if k and m.startswith(k.lower()) and (best is None or len(k) > len(best)):
            best = k
    if best is None and "" in t:
        best = ""
    return t.get(best) if best is not None else None


def estimate(provider, model, input_tokens=None, output_tokens=None, units=None, unit=None, table=None):
    pr = price_for(provider, model, table or PRICES)
    if not pr:
        return None
    c, used = 0.0, False
    if input_tokens is not None and "in_per_m" in pr:
        c += input_tokens * pr["in_per_m"] / 1e6; used = True
    if output_tokens is not None and "out_per_m" in pr:
        c += output_tokens * pr["out_per_m"] / 1e6; used = True
    if units is not None:
        k = {"characters": "per_m_chars", "minutes": "per_minute", "seconds": "per_second"}.get(unit)
        if k in pr:
            c += units * pr[k] / (1e6 if k == "per_m_chars" else 1); used = True
    return round(c, 6) if used else None


def tokens_from(provider, r):
    """(input, output) tokens from a provider's JSON answer, when it reports them"""
    if not isinstance(r, dict):
        return None, None
    if provider == "gemini":
        u = r.get("usageMetadata") or {}
        return (u.get("promptTokenCount"), (u.get("candidatesTokenCount") or 0) + (u.get("thoughtsTokenCount") or 0)) if u else (None, None)
    u = r.get("usage") or {}
    return (u.get("input_tokens", u.get("prompt_tokens")), u.get("output_tokens", u.get("completion_tokens"))) if u else (None, None)


def record(provider, model=None, app=None, purpose=None, input_tokens=None, output_tokens=None, units=None, unit=None, seconds=None,
           ok=True, error=None, folder=None):
    """one call; never raises (usage keeping must never break the work)"""
    try:
        db = _db(folder)
        if db is None:
            return None
        cost = estimate(provider, model, input_tokens, output_tokens, units, unit, prices(folder))
        with _LOCK, db:
            cur = db.execute("INSERT INTO calls(at, app, purpose, provider, model, input_tokens, output_tokens, units, unit, seconds, ok, error, cost_usd, priced) "
                             "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (time.time(), app or os.environ.get("QB_APP_ID") or "", (purpose or "")[:120], provider, (model or "")[:80],
                              input_tokens, output_tokens, units, unit, round(seconds, 3) if seconds is not None else None, 1 if ok else 0,
                              str(error)[:200] if error else None, cost, 1 if cost is not None else 0))
        db.close()
        return cur.lastrowid
    except Exception:
        return None


def calls(folder=None, since=0.0, limit=500):
    db = _db(folder)
    if db is None:
        return []
    rows = db.execute("SELECT id, at, app, purpose, provider, model, input_tokens, output_tokens, units, unit, seconds, ok, error, cost_usd, priced "
                      "FROM calls WHERE at >= ? ORDER BY at DESC LIMIT ?", (since, int(limit))).fetchall()
    db.close()
    keys = ("id", "at", "app", "purpose", "provider", "model", "input_tokens", "output_tokens", "units", "unit", "seconds", "ok", "error", "cost_usd", "priced")
    return [dict(zip(keys, r)) for r in rows]


def _month_start(now=None):
    t = time.localtime(now or time.time())
    return time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))


def summary(folder=None, now=None):
    """per provider and model, per period (today, this month, all time): calls, failures, tokens, units, time, charges"""
    db = _db(folder)
    out = {"periods": {}, "providers": PROVIDERS, "prices_note": PRICES_NOTE, "by_day": []}
    if db is None:
        return out
    now = now or time.time()
    t = time.localtime(now)
    day0 = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
    for name, since in (("today", day0), ("month", _month_start(now)), ("all", 0.0)):
        rows = db.execute("SELECT provider, model, count(*), sum(1 - ok), sum(input_tokens), sum(output_tokens), sum(units), max(unit), sum(seconds), "
                          "sum(cost_usd), sum(1 - priced) FROM calls WHERE at >= ? GROUP BY provider, model ORDER BY sum(cost_usd) DESC", (since,)).fetchall()
        out["periods"][name] = [{"provider": r[0], "model": r[1], "calls": r[2], "failed": r[3] or 0, "input_tokens": r[4] or 0, "output_tokens": r[5] or 0,
                                 "units": r[6], "unit": r[7], "seconds": round(r[8] or 0, 1), "cost_usd": round(r[9] or 0, 6), "unpriced_calls": r[10] or 0}
                                for r in rows]
    by_day = db.execute("SELECT date(at, 'unixepoch', 'localtime') AS d, provider, count(*), sum(input_tokens), sum(output_tokens), sum(cost_usd) FROM calls "
                        "WHERE at >= ? GROUP BY d, provider ORDER BY d DESC", (now - 31 * 86400,)).fetchall()
    out["by_day"] = [{"day": r[0], "provider": r[1], "calls": r[2], "input_tokens": r[3] or 0, "output_tokens": r[4] or 0, "cost_usd": round(r[5] or 0, 6)} for r in by_day]
    db.close()
    return out


# ------------------------------------------------------------------------------------------------ subscriptions
def _subs_path(folder=None):
    return os.path.join(folder or FOLDER["path"], "ai-subscriptions.json")


def subscriptions(folder=None):
    try:
        with open(_subs_path(folder), encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError, TypeError):
        return {}


def save_subscription(provider, plan=None, monthly_usd=None, renews=None, budget_usd=None, notes=None, folder=None):
    if provider not in PROVIDERS:
        raise ValueError("unknown provider")
    s = subscriptions(folder)
    cur = s.get(provider, {})
    for k, v in (("plan", plan), ("renews", renews), ("notes", notes)):
        if v is not None:
            cur[k] = str(v)[:120]
    for k, v in (("monthly_usd", monthly_usd), ("budget_usd", budget_usd)):
        if v not in (None, ""):
            cur[k] = round(float(v), 2)
    s[provider] = cur
    p = _subs_path(folder)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)
    os.replace(p + ".tmp", p)
    return cur


def overview(folder=None, keys_set=None, now=None):
    """the page: one row per provider — subscription, this month's usage and charges, budget used — plus totals"""
    sm, subs = summary(folder, now), subscriptions(folder)
    month = {}
    for r in sm["periods"].get("month", []):
        m = month.setdefault(r["provider"], {"calls": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0, "seconds": 0.0, "cost_usd": 0.0, "unpriced_calls": 0, "units": {}})
        for k in ("calls", "failed", "input_tokens", "output_tokens", "seconds", "cost_usd", "unpriced_calls"):
            m[k] += r[k]
        if r["units"]:
            m["units"][r["unit"]] = m["units"].get(r["unit"], 0) + r["units"]
    rows = []
    for p, (title, kind, billing) in PROVIDERS.items():
        u = month.get(p, {"calls": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0, "seconds": 0.0, "cost_usd": 0.0, "unpriced_calls": 0, "units": {}})
        sub = subs.get(p, {})
        total = round(u["cost_usd"] + float(sub.get("monthly_usd") or 0), 2)
        bud = sub.get("budget_usd")
        rows.append({"provider": p, "title": title, "kind": kind, "billing": billing, "key_set": (keys_set or {}).get(p), "subscription": sub,
                     "month": u, "month_total_usd": total, "budget_used": round(100 * total / bud, 1) if bud else None})
    return {"rows": rows, "summary": sm, "totals": {"month_usage_usd": round(sum(r["month"]["cost_usd"] for r in rows), 4),
                                                    "month_subscriptions_usd": round(sum(float(r["subscription"].get("monthly_usd") or 0) for r in rows), 2),
                                                    "month_calls": sum(r["month"]["calls"] for r in rows),
                                                    "month_tokens": sum(r["month"]["input_tokens"] + r["month"]["output_tokens"] for r in rows),
                                                    "month_seconds": round(sum(r["month"]["seconds"] for r in rows), 1)},
            "prices": prices(folder), "prices_note": PRICES_NOTE}


def csv_text(folder=None):
    rows = calls(folder, 0, 100000)
    head = "time,app,purpose,provider,model,input_tokens,output_tokens,units,unit,seconds,ok,cost_usd_estimate\n"
    esc = lambda v: '"%s"' % str(v).replace('"', '""') if isinstance(v, str) and ("," in v or '"' in v) else ("" if v is None else str(v))
    return head + "".join(",".join(esc(x) for x in (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["at"])), r["app"], r["purpose"], r["provider"], r["model"],
                                                     r["input_tokens"], r["output_tokens"], r["units"], r["unit"], r["seconds"], r["ok"], r["cost_usd"])) + "\n" for r in reversed(rows))


def self_test():
    import tempfile, shutil
    out = []
    ok = lambda n, c, d="": out.append((n, bool(c), d))
    d = tempfile.mkdtemp()
    try:
        record("gemini", "gemini-2.5-flash", "facts", "gather", 1000, 500, seconds=2.0, folder=d)
        record("google-tts", "neural2", "language", "speak", units=2000, unit="characters", seconds=0.8, folder=d)
        record("elevenlabs", "eleven_multilingual_v2", "language", "speak", units=300, unit="characters", seconds=1.1, folder=d)
        record("openai", "gpt-4.1-mini", "facts", "gather", ok=False, error="HTTP 429", seconds=0.3, folder=d)
        s = summary(d)
        g = next(r for r in s["periods"]["month"] if r["provider"] == "gemini")
        ok("an LLM call is kept with its tokens, time and charge (1,000 in + 500 out on Gemini 2.5 Flash = $0.00155)",
           g["input_tokens"] == 1000 and g["output_tokens"] == 500 and abs(g["cost_usd"] - 0.00155) < 1e-6 and g["seconds"] == 2.0, g)
        t = next(r for r in s["periods"]["month"] if r["provider"] == "google-tts")
        ok("voice is charged by characters (2,000 Neural2 characters = $0.032)", abs(t["cost_usd"] - 0.032) < 1e-6, t)
        e = next(r for r in s["periods"]["month"] if r["provider"] == "elevenlabs")
        ok("a credit-billed service is counted but not priced (it bills through its subscription)", e["unpriced_calls"] == 1 and e["cost_usd"] == 0, e)
        save_subscription("elevenlabs", "Creator", 22, "2026-12-01", 30, folder=d)
        el = next(r for r in overview(d)["rows"] if r["provider"] == "elevenlabs")
        ok("a subscription's monthly fee joins the month's total and the budget used", el["month_total_usd"] == 22.0 and el["budget_used"] == 73.3, el)
        ok("failed calls are counted", next(r for r in s["periods"]["month"] if r["provider"] == "openai")["failed"] == 1)
        save_prices({"elevenlabs": {"": {"per_m_chars": 300}}}, d)
        ok("prices can be edited (and apply to new calls)", price_for("elevenlabs", "x", prices(d)) == {"per_m_chars": 300.0})
        ok("the CSV export has every call", csv_text(d).count("\n") == 5)
        ok("no folder: recording does nothing and never fails", record("gemini", "m", folder="/no/such/folder") is None)
        ok("tokens are read from Gemini and OpenAI answers", tokens_from("gemini", {"usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3}}) == (7, 3)
           and tokens_from("openai", {"usage": {"input_tokens": 5, "output_tokens": 2}}) == (5, 2))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return out


if __name__ == "__main__":
    res = self_test()
    for n, g, dd in res:
        print(("  [OK]   " if g else "  [FAIL] ") + n + ("" if g else "  — %s" % (dd,)))
    print("\n  %d of %d checks passed" % (sum(1 for x in res if x[1]), len(res)))
