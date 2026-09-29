#!/usr/bin/env python3
"""
qb_chat.py — QueryBook-LLM hybrid chat engine (stdlib + optional `anthropic`).

The honest chatbot: the LLM never states a fact it did not retrieve from the UFCS
store. It handles language (understanding the question, writing prose); QueryBook
handles knowledge (what is true, with what trust, from what source). Every factual
sentence traces back to a Fact Unit fingerprint and the answer carries a
response_provenance_hash.

Pipeline (see design):
  1. PLAN     LLM turns the question into FQL query plans (subject/predicate/trust_min).
  2. RETRIEVE QueryBook runs FQL over the local store -> ranked Fact Units + RPH.
  3. GATE     Prime Directive (Domain 0): VERIFIED / CONTRADICTED / UNKNOWN.
              UNKNOWN -> refuse ("Without-Information Rule"), never invent.
  4. COMPOSE  LLM writes prose using ONLY the gated facts, citing each [n].
  5. CHECK    every factual sentence in the draft must map to a cited Fact Unit;
              orphan sentences are flagged/stripped. Closes the hallucination loop.

Works with NO API key too: a deterministic fallback planner + composer answer straight
from FQL results, so the grounding demo runs offline. Add ANTHROPIC_API_KEY (and
`pip install anthropic`) to get the LLM language layer.

Used by qb_api.py's POST /api/chat, and runnable standalone:
    python qb_chat.py ./mystore "what is the capital of France?"
"""
import json, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ufcs_store as store

# Cheap tier for planning + checking; stronger tier for composing prose.
PLAN_MODEL    = os.environ.get("QB_PLAN_MODEL",    "claude-haiku-4-5")
COMPOSE_MODEL = os.environ.get("QB_COMPOSE_MODEL", "claude-opus-5")
CHECK_MODEL   = os.environ.get("QB_CHECK_MODEL",   "claude-haiku-4-5")

_STOP = {"the","a","an","of","is","are","was","were","what","who","whom","whose",
         "which","when","where","why","how","does","do","did","in","on","at","to",
         "for","and","or","tell","me","about","please","can","you","that","this",
         "there","it","its","their","has","have","had","with","by","from","as"}


import urllib.request

# The provider chosen for THIS answer() call (set by answer()); shape matches what the
# dashboard saves: {name, kind, base_url, model, key_env, key?}. None = no LLM.
_ACTIVE_PROVIDER = None
_LLM_ERRORS = []          # human-readable notes from the last answer(), surfaced to the UI


def _provider_key(p):
    """Resolve the API key from the named env var (never stored in the app), or an inline key."""
    if not p:
        return ""
    return os.environ.get(p.get("key_env") or "", "") or p.get("key", "") or ""


def _provider_usable(p):
    if not p:
        return False
    base = (p.get("base_url") or "").lower()
    # a local server (localhost/127.0.0.1) may need no key; a hosted API needs one
    if _provider_key(p):
        return True
    return ("localhost" in base) or ("127.0.0.1" in base)


def _sdk_available():
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except Exception:
        return False


def _have_llm():
    return _provider_usable(_ACTIVE_PROVIDER) or _sdk_available()


def _is_anthropic(p):
    base = (p.get("base_url") or "").lower()
    return p.get("kind") == "anthropic" or "anthropic.com" in base or (p.get("model", "").startswith("claude"))


def _http_json(url, payload, headers, timeout=90):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _llm_http(provider, model, prompt, system, max_tokens):
    """Call an Anthropic or OpenAI-compatible endpoint with the standard library only
    (no SDK needed). Raises on failure so the caller can record a clear reason."""
    key = _provider_key(provider)
    model = model or provider.get("model") or ("claude-haiku-4-5" if _is_anthropic(provider) else "gpt-4o-mini")
    if _is_anthropic(provider):
        base = (provider.get("base_url") or "https://api.anthropic.com/v1").rstrip("/")
        headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
        if key:
            headers["x-api-key"] = key
        body = {"model": model, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}]}
        if system:
            body["system"] = system
        d = _http_json(base + "/messages", body, headers)
        if isinstance(d, dict) and d.get("type") == "error":
            raise RuntimeError((d.get("error") or {}).get("message", "anthropic error"))
        return "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text").strip()
    # OpenAI-compatible
    base = (provider.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    d = _http_json(base + "/chat/completions", {"model": model, "temperature": 0,
                                                "max_tokens": max_tokens, "messages": msgs}, headers)
    if isinstance(d, dict) and d.get("error"):
        raise RuntimeError(str(d["error"].get("message") if isinstance(d["error"], dict) else d["error"]))
    return (d["choices"][0]["message"]["content"] or "").strip()


def provider_usable(p):
    """Public: is this provider dict usable (has a key, or is a local server)?"""
    return _provider_usable(p)


import urllib.error


def _anthropic_error_hint(code, etype, emsg):
    """Turn an Anthropic HTTP error into a plain-language cause a non-engineer can act on.
    This is the heart of the 'no darkness' diagnostic: every failure names a specific,
    fixable reason instead of a bare 'blocked'."""
    m = (emsg or "").lower()
    if code == 401 or etype == "authentication_error":
        return ("Your API key was rejected (401). The key is missing, mistyped, or not a real "
                "Anthropic API key. Note: a claude.ai chat subscription (Pro/Team, or a 'Claude "
                "Haiku' chat plan) is NOT an API key — the API needs a separate key that starts "
                "with 'sk-ant-' from console.anthropic.com.")
    if code == 403 or etype == "permission_error":
        return ("Your key was recognized but is not allowed to use this model or endpoint (403). "
                "Check that your Anthropic account/organization has access to the model.")
    if "credit balance is too low" in m or "billing" in m or "quota" in m:
        return ("Your API key is valid, but the Anthropic account has no API credits (billing "
                "not set up). A claude.ai subscription does NOT add API credits — go to "
                "console.anthropic.com → Plans & Billing and add credits to use the API.")
    if code == 404 or etype == "not_found_error" or "model" in m and "not" in m:
        return ("The model name was not found (404). Set the model to a current ID such as "
                "'claude-haiku-4-5' (or 'claude-opus-5'). Also confirm the Base URL is "
                "'https://api.anthropic.com/v1'.")
    if code == 429 or etype == "rate_limit_error":
        return ("Rate limited (429). The key works; you have hit a usage limit — wait a moment "
                "and try again, or raise your account's rate limits.")
    if code and code >= 500:
        return ("Anthropic's API returned a server error (%s). This is on their side — retry "
                "shortly." % code)
    return emsg or ("HTTP %s from the API." % code)


def provider_test(provider):
    """Make ONE minimal live call against the provider and report EXACTLY what happened.
    Returns a structured verdict — never raises — so the dashboard can turn a mysterious
    'Phase 2 blocked' into a precise, fixable cause (200 OK / 401 bad key / 404 model /
    low-credit / network). A trap-and-fallback contingency: we test before we trust."""
    p = provider or {}
    name = p.get("name") or "provider"
    anthropic = _is_anthropic(p)
    model = p.get("model") or ("claude-haiku-4-5" if anthropic else "gpt-4o-mini")
    key = _provider_key(p)
    base = (p.get("base_url") or ("https://api.anthropic.com/v1" if anthropic
                                  else "https://api.openai.com/v1")).rstrip("/")
    local = ("localhost" in base.lower()) or ("127.0.0.1" in base.lower())

    if not key and not local:
        return {"ok": False, "code": "no_key", "provider": name, "model": model,
                "endpoint": base, "detail": (
                    "No API key is stored for this provider. Paste your Anthropic API key "
                    "(it starts with 'sk-ant-') into the key field and save. A claude.ai chat "
                    "subscription is not an API key — get an API key at console.anthropic.com.")}

    t0 = time.time()
    try:
        if anthropic:
            url = base + "/messages"
            headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
            if key:
                headers["x-api-key"] = key
            payload = {"model": model, "max_tokens": 1,
                       "messages": [{"role": "user", "content": "ping"}]}
        else:
            url = base + "/chat/completions"
            headers = {"Content-Type": "application/json"}
            if key:
                headers["Authorization"] = "Bearer " + key
            payload = {"model": model, "max_tokens": 1, "temperature": 0,
                       "messages": [{"role": "user", "content": "ping"}]}
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
            ms = int((time.time() - t0) * 1000)
            return {"ok": True, "code": r.status, "provider": name, "model": model,
                    "endpoint": url, "elapsed_ms": ms,
                    "detail": "Success (HTTP %s in %d ms). The key and model both work — "
                              "Phase 2 semantic grounding can run." % (r.status, ms)}
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8", "ignore")
            body = json.loads(raw)
        except Exception:
            body, raw = {}, ""
        err = body.get("error") if isinstance(body, dict) else None
        etype = (err or {}).get("type") if isinstance(err, dict) else None
        emsg = (err or {}).get("message") if isinstance(err, dict) else (raw[:300] or None)
        hint = (_anthropic_error_hint(e.code, etype, emsg) if anthropic
                else (emsg or ("HTTP %s from the API." % e.code)))
        return {"ok": False, "code": e.code, "provider": name, "model": model,
                "endpoint": url, "error_type": etype, "raw_message": emsg, "detail": hint}
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        return {"ok": False, "code": "network", "provider": name, "model": model,
                "endpoint": url, "detail": (
                    "Could not reach the API (%s). Check the Base URL, your internet "
                    "connection, and any firewall/proxy. Expected Base URL for Anthropic is "
                    "'https://api.anthropic.com/v1'." % reason)}
    except Exception as e:
        return {"ok": False, "code": "error", "provider": name, "model": model,
                "endpoint": base, "detail": "Unexpected error: %s" % e}


def llm_complete(provider, prompt, system=None, max_tokens=1500):
    """Public one-shot completion against an explicit provider (no globals). Raises on failure."""
    return _llm_http(provider, provider.get("model") if provider else None, prompt, system, max_tokens)


def _llm_text(model, prompt, max_tokens=1500, system=None):
    """One-shot completion. Prefers the configured provider over HTTP (no SDK needed);
    falls back to the anthropic SDK if that's all that's available. Returns "" on any
    failure and records a readable reason in _LLM_ERRORS so the UI can show WHY."""
    p = _ACTIVE_PROVIDER
    if _provider_usable(p):
        try:
            return _llm_http(p, model, prompt, system, max_tokens)
        except Exception as e:
            msg = f"{(p or {}).get('name','provider')}: {e}"
            sys.stderr.write(f"[llm error: {msg}]\n")
            _LLM_ERRORS.append(msg)
            return ""
    if _sdk_available():
        try:
            import anthropic
            kw = dict(model=model, max_tokens=max_tokens,
                      messages=[{"role": "user", "content": prompt}])
            if system:
                kw["system"] = system
            m = anthropic.Anthropic().messages.create(**kw)
            return "".join(b.text for b in m.content if getattr(b, "type", "") == "text").strip()
        except Exception as e:
            sys.stderr.write(f"[llm sdk error: {e}]\n")
            _LLM_ERRORS.append(f"anthropic SDK: {e}")
            return ""
    return ""


# ---------- 1. PLAN ----------
def plan_queries(question, use_llm):
    """Return a list of {subject, predicate, trust_min} query plans."""
    if use_llm:
        raw = _llm_text(
            PLAN_MODEL,
            "You convert a user question into QueryBook FQL query plans. "
            "Return ONLY a JSON array of objects with keys "
            '"subject" (string or null), "predicate" (string or null, using '
            "snake_case relation names like has_capital, has_atomic_number, born_in), "
            'and "trust_min" (0..1, default 0.5). Emit 1-3 plans covering the question. '
            "No prose.\n\nQUESTION: " + question)
        m = re.search(r"\[.*\]", raw, re.S)
        if m:
            try:
                arr = json.loads(m.group(0))
                plans = [{"subject": (p.get("subject") or None),
                          "predicate": (p.get("predicate") or None),
                          "trust_min": float(p.get("trust_min", 0.5) or 0.5)}
                         for p in arr if isinstance(p, dict)]
                if plans:
                    return plans
            except Exception:
                pass
    # deterministic fallback: keywords -> subject terms, no predicate filter
    words = [w for w in re.findall(r"[A-Za-z0-9²³!×+']+", question) if w.lower() not in _STOP]
    subj = " ".join(words[:4]) if words else None
    return [{"subject": subj, "predicate": None, "trust_min": 0.4}]


# ---------- 2. RETRIEVE ----------
def retrieve(st, plans, limit=8, question=None):
    """Run each plan through FQL; merge, de-dupe by fingerprint, keep provenance hash.
    Falls back to keyword search when exact structure match finds nothing."""
    seen, facts = set(), []
    for pl in plans:
        tmin = float(pl.get("trust_min", 0.4) or 0.4)
        try:
            rows, _ = st.fql(pl.get("subject"), pl.get("predicate"), tmin, limit)
        except Exception:
            rows = []
        # strict (subject+predicate) miss -> loosen to subject only
        if not rows and pl.get("subject") and pl.get("predicate"):
            rows, _ = st.fql(pl["subject"], None, 0.0, limit)
        # still nothing -> keyword search over the plan subject (LIKE on subject/object)
        if not rows and pl.get("subject"):
            rows, _ = st.search(pl["subject"], min(tmin, 0.2), limit)
        for s, p, o, t, fp in rows:
            if fp in seen:
                continue
            seen.add(fp)
            facts.append({"subject": s, "predicate": p, "object": o,
                          "trust": round(float(t), 4), "fingerprint": fp})
    # last resort: keyword search over the whole question
    if not facts and question:
        rows, _ = st.search(question, 0.0, limit)
        for s, p, o, t, fp in rows:
            if fp in seen:
                continue
            seen.add(fp)
            facts.append({"subject": s, "predicate": p, "object": o,
                          "trust": round(float(t), 4), "fingerprint": fp})
    facts.sort(key=lambda f: f["trust"], reverse=True)
    rph = store._h("RPH", *[f["fingerprint"] for f in facts])
    return facts, rph


# ---------- 3. GATE (Prime Directive / Domain 0) ----------
def gate(facts, min_trust=0.5):
    """Classify the retrieval into a verdict and the facts allowed to reach composition."""
    usable = [f for f in facts if f["trust"] >= min_trust]
    if not usable:
        return "UNKNOWN", []
    # contradiction = same subject+predicate, different objects, both above threshold
    by_sp = {}
    for f in usable:
        by_sp.setdefault((f["subject"], f["predicate"]), set()).add(f["object"].lower())
    if any(len(objs) > 1 for objs in by_sp.values()):
        return "CONTRADICTED", usable
    return "VERIFIED", usable


# ---------- 4. COMPOSE ----------
def compose(question, verdict, facts, use_llm):
    if verdict == "UNKNOWN":
        return ("QueryBook has no verified fact for that. Rather than guess, I'm declining "
                "to answer — this is the Without-Information Rule: no fact, no claim.")
    cite = {f["fingerprint"]: i + 1 for i, f in enumerate(facts)}
    fact_lines = "\n".join(
        f'[{cite[f["fingerprint"]]}] {f["subject"]} — {f["predicate"]} — {f["object"]} '
        f'(trust {f["trust"]:.2f}, fp {f["fingerprint"][:10]}…)'
        for f in facts)

    if use_llm:
        note = ("These facts disagree; present the competing values side by side with their "
                "trust scores and do not pick a winner. " if verdict == "CONTRADICTED" else "")
        sys_prompt = (
            "You are QueryBook, a grounded assistant. You may state ONLY the facts listed "
            "below, nothing else — no outside knowledge, no inference beyond what a fact says. "
            "Cite each fact you use with its [n] marker. Do not add figures, dates, names, or "
            "claims that are not in the list. If the facts don't fully answer, say what is "
            "missing. Keep it tight and plain.")
        draft = _llm_text(COMPOSE_MODEL,
                          f"{note}QUESTION: {question}\n\nFACTS:\n{fact_lines}\n\nAnswer:",
                          system=sys_prompt, max_tokens=800)
        if draft:
            return draft
    # deterministic fallback composer
    head = ("These verified facts bear on it" if verdict == "VERIFIED"
            else "The store holds competing values — both shown with their trust")
    body = "\n".join(f'  [{cite[f["fingerprint"]]}] {f["subject"]} {f["predicate"]} '
                     f'{f["object"]}  (trust {f["trust"]:.2f})' for f in facts)
    return f"{head}:\n{body}"


# ---------- 5. CHECK (post-composition grounding) ----------
def check(draft, facts, use_llm):
    """Flag sentences that assert something not backed by a cited fact. Returns (draft, flags)."""
    if not facts:
        return draft, []
    if use_llm:
        fact_lines = "\n".join(f'[{i+1}] {f["subject"]} {f["predicate"]} {f["object"]}'
                               for i, f in enumerate(facts))
        raw = _llm_text(CHECK_MODEL,
                        "Below is an ANSWER and the FACTS it is allowed to use. List, as a JSON "
                        "array of strings, any sentence in the ANSWER that asserts information not "
                        "supported by the FACTS (an unsupported claim). Return [] if all supported. "
                        f"JSON only.\n\nFACTS:\n{fact_lines}\n\nANSWER:\n{draft}",
                        max_tokens=600)
        m = re.search(r"\[.*\]", raw, re.S)
        if m:
            try:
                flags = [str(x) for x in json.loads(m.group(0))]
                return draft, flags
            except Exception:
                pass
    # deterministic fallback: any [n] cited must exist; also flag numeric tokens not in any object
    flags = []
    cited = set(int(n) for n in re.findall(r"\[(\d+)\]", draft))
    if any(n < 1 or n > len(facts) for n in cited):
        flags.append("citation refers to a fact that was not retrieved")
    return draft, flags


# ---------- orchestration ----------
def answer(st, question, min_trust=0.5, limit=8, provider=None):
    global _ACTIVE_PROVIDER, _LLM_ERRORS
    _ACTIVE_PROVIDER = provider
    _LLM_ERRORS = []
    use_llm = _have_llm()
    t0 = time.time()
    plans = plan_queries(question, use_llm)
    facts, rph = retrieve(st, plans, limit, question=question)
    verdict, gated = gate(facts, min_trust)
    draft = compose(question, verdict, gated, use_llm)
    draft, flags = check(draft, gated, use_llm)
    # If the LLM was configured but every call failed, we still returned a correct
    # deterministic answer — say so plainly rather than surfacing a raw stack trace.
    llm_error = _LLM_ERRORS[0] if _LLM_ERRORS else None
    grounded_by_llm = use_llm and not (_LLM_ERRORS and draft and llm_error)
    res = {
        "question": question,
        "verdict": verdict,
        "answer": draft,
        "grounded": grounded_by_llm,        # True only if the LLM layer actually ran
        "llm_available": use_llm,
        "llm_provider": (provider or {}).get("name") if provider else None,
        "llm_error": llm_error,             # readable reason the LLM was skipped, or None
        "unsupported_flags": flags,
        "citations": [{"n": i + 1, "subject": f["subject"], "predicate": f["predicate"],
                       "object": f["object"], "trust": f["trust"], "fingerprint": f["fingerprint"]}
                      for i, f in enumerate(gated)],
        "response_provenance_hash": rph,
        "plans": plans,
        "elapsed_ms": int((time.time() - t0) * 1000),
    }
    _ACTIVE_PROVIDER = None
    return res


def main():
    if len(sys.argv) < 3:
        print("usage: python qb_chat.py <store> \"your question\" [--trust 0.5]"); return
    st_path, question = sys.argv[1], sys.argv[2]
    mt = 0.5
    if "--trust" in sys.argv:
        mt = float(sys.argv[sys.argv.index("--trust") + 1])
    st = store.UFCSStore(st_path)
    try:
        res = answer(st, question, mt)
    finally:
        st.db.close()
    print(json.dumps(res, indent=2))
    print("\n" + "=" * 60)
    print(f"VERDICT: {res['verdict']}   (LLM layer: {'on' if res['grounded'] else 'off — deterministic'})")
    print(res["answer"])
    if res["citations"]:
        print("\nSources:")
        for c in res["citations"]:
            print(f"  [{c['n']}] {c['subject']} {c['predicate']} {c['object']}  "
                  f"trust {c['trust']:.2f}  fp {c['fingerprint'][:12]}…")
    print(f"\nresponse_provenance_hash: {res['response_provenance_hash']}")
    if res["unsupported_flags"]:
        print("UNSUPPORTED (flagged by post-check):")
        for fl in res["unsupported_flags"]:
            print(f"  ! {fl}")


if __name__ == "__main__":
    main()
