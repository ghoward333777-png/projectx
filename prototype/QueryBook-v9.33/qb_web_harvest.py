#!/usr/bin/env python3
"""
qb_web_harvest.py — polite, domain-scoped web harvester -> UFCS Fact Units.

Crawls ONLY the domains you list, obeys robots.txt, rate-limits per host, and extracts
Fact Units. Two extractors:
  * structured (default, stdlib, free, high-precision): JSON-LD / schema.org, OpenGraph.
  * llm (optional): sends page text to Claude to extract S-P-O triples. Requires the
    `anthropic` package + an API key; skipped automatically if unavailable.

Facts are written into the UFCS store (blocks -> USB, index -> SSD, dedupe by fingerprint).

CLI:
  python qb_web_harvest.py <store> --seeds https://example.org/a,https://example.org/b \
      --max-pages 500 --rate 1.0 --concurrency 4 --extractor structured
  # add --extractor both --llm-model claude-haiku-4-5   (needs ANTHROPIC_API_KEY)

Only harvest domains you have the right to crawl. This tool respects robots.txt and
rate limits by default.
"""
import argparse, json, os, re, sys, threading, time, html.parser
import urllib.parse, urllib.request, urllib.robotparser
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ufcs_store as store

UA = "QueryBookHarvester/1.0 (+respects robots.txt)"

# ---------- HTML parsing (stdlib) ----------
class Extract(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.jsonld = []; self.links = []; self.text = []
        self._ld = False; self._buf = []; self._skip = 0
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and a.get("type", "").strip().lower() == "application/ld+json":
            self._ld = True; self._buf = []
        elif tag in ("script", "style"): self._skip += 1
        elif tag == "a" and a.get("href"): self.links.append(a["href"])
    def handle_endtag(self, tag):
        if tag == "script" and self._ld:
            self._ld = False
            try: self.jsonld.append(json.loads("".join(self._buf)))
            except Exception: pass
        elif tag in ("script", "style") and self._skip: self._skip -= 1
    def handle_data(self, data):
        if self._ld: self._buf.append(data)
        elif not self._skip:
            t = data.strip()
            if t: self.text.append(t)

def reg_domain(netloc):
    return netloc.lower().split(":")[0].lstrip("www.") if netloc else ""

def same_scope(url, scopes):
    host = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    return any(host == s or host.endswith("." + s) for s in scopes)

# ---------- structured extraction (JSON-LD / schema.org) ----------
def facts_from_jsonld(obj, out):
    def walk(o):
        if isinstance(o, list):
            for x in o: walk(x)
        elif isinstance(o, dict):
            subj = o.get("name") or o.get("@id") or o.get("headline")
            if isinstance(subj, str) and subj.strip():
                for k, v in o.items():
                    if k.startswith("@") or k == "name": continue
                    if isinstance(v, (str, int, float)) and str(v).strip():
                        out.append((subj.strip(), k, str(v).strip()))
                    elif isinstance(v, dict):
                        nm = v.get("name") or v.get("@id")
                        if isinstance(nm, str): out.append((subj.strip(), k, nm.strip()))
            for v in o.values():
                if isinstance(v, (list, dict)): walk(v)
    walk(obj)

def extract_structured(ex):
    out = []
    for blk in ex.jsonld: facts_from_jsonld(blk, out)
    # dedupe within page
    seen = set(); res = []
    for s, p, o in out:
        key = (s.lower(), p.lower(), o.lower())
        if key in seen: continue
        seen.add(key); res.append((s, p, o))
    return res

# ---------- optional LLM extraction ----------
def extract_llm(text, url, model):
    try:
        import anthropic
    except Exception:
        return []
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return []
    try:
        client = anthropic.Anthropic()
        prompt = ("Extract atomic facts from the text as a JSON array of objects "
                  '{"subject","predicate","object"} — concrete, verifiable statements only, '
                  "no opinions. Return ONLY the JSON array.\n\nTEXT:\n" + text[:6000])
        msg = client.messages.create(model=model, max_tokens=2000,
                                     messages=[{"role": "user", "content": prompt}])
        parts = [b.text for b in msg.content if getattr(b, "type", "") == "text"]
        raw = "".join(parts)
        m = re.search(r"\[.*\]", raw, re.S)
        arr = json.loads(m.group(0)) if m else []
        return [(str(d["subject"]), str(d["predicate"]), str(d["object"]))
                for d in arr if d.get("subject") and d.get("predicate") and d.get("object")]
    except Exception as e:
        sys.stderr.write(f"[llm extract error: {e}]\n"); return []

def extract_openai(text, url, provider):
    """Extract facts via ANY OpenAI-compatible API or local server (OpenAI, Groq,
    Together, Ollama/llama.cpp with /v1, etc.). provider = {base_url, model, key_env, key}."""
    base = (provider.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    key = os.environ.get(provider.get("key_env", "OPENAI_API_KEY")) or provider.get("key", "")
    model = provider.get("model", "gpt-4o-mini")
    if not key and "api.openai.com" in base:
        return []   # a hosted API needs a key; a local server may not
    prompt = ("Extract atomic facts from the text as a JSON array of "
              '{"subject","predicate","object"} — concrete, verifiable only. Return ONLY the JSON array.'
              "\n\nTEXT:\n" + text[:6000])
    payload = json.dumps({"model": model, "temperature": 0,
                          "messages": [{"role": "user", "content": prompt}]}).encode()
    headers = {"Content-Type": "application/json"}
    if key: headers["Authorization"] = "Bearer " + key
    try:
        req = urllib.request.Request(base + "/chat/completions", data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=90) as r:
            d = json.loads(r.read().decode("utf-8", "ignore"))
        content = d["choices"][0]["message"]["content"]
        m = re.search(r"\[.*\]", content, re.S)
        arr = json.loads(m.group(0)) if m else []
        return [(str(x["subject"]), str(x["predicate"]), str(x["object"]))
                for x in arr if x.get("subject") and x.get("predicate") and x.get("object")]
    except Exception as e:
        sys.stderr.write(f"[openai-compatible extract error: {e}]\n"); return []

# ---------- crawler ----------
class Harvester:
    def __init__(self, st, seeds, rate, extractor, llm_model, trust=0.5):
        self.st = st; self.rate = rate; self.extractor = extractor; self.llm_model = llm_model; self.trust = trust
        self.scopes = sorted({reg_domain(urllib.parse.urlparse(s).netloc) for s in seeds})
        self.robots = {}; self.last = {}; self.lock = threading.Lock()
        self.visited = set(); self.stored = 0; self.pages = 0
        self.provider = None   # set by the agent manager for "any LLM" extraction

    def allowed(self, url):
        host = urllib.parse.urlparse(url).netloc
        rp = self.robots.get(host)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            try:
                rp.set_url(f"{urllib.parse.urlparse(url).scheme}://{host}/robots.txt"); rp.read()
            except Exception: pass
            self.robots[host] = rp
        try: return rp.can_fetch(UA, url)
        except Exception: return True

    def polite_wait(self, host):
        with self.lock:
            dt = time.time() - self.last.get(host, 0)
            if dt < self.rate: time.sleep(self.rate - dt)
            self.last[host] = time.time()

    def fetch(self, url):
        host = urllib.parse.urlparse(url).netloc
        self.polite_wait(host)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=25) as r:
            ct = r.headers.get("Content-Type", "")
            if "html" not in ct: return None
            return r.read(2_000_000).decode("utf-8", "ignore")

    def store_facts(self, triples, url):
        added = 0
        for s, p, o in triples:
            rec = {"fact_type": "assertion", "domain": reg_domain(urllib.parse.urlparse(url).netloc),
                   "nucleus": {"subject": s[:200], "predicate": p[:80], "object": o[:400]}, "polarity": "+",
                   "sources": [{"id": "SRC-WEB", "name": url, "class": "web"}],
                   "certification": {"authority_class": "web", "trust_score": self.trust}}
            if self.st.add(rec): added += 1
        self.stored += added; return added

    def run(self, seeds, max_pages, log=print):
        from collections import deque
        q = deque(seeds)
        while q and self.pages < max_pages:
            url = q.popleft()
            if url in self.visited or not same_scope(url, self.scopes): continue
            self.visited.add(url)
            if not self.allowed(url):
                log(f"  robots-blocked: {url}"); continue
            try:
                html_text = self.fetch(url)
            except Exception as e:
                log(f"  fetch error {url}: {e}"); continue
            if not html_text: continue
            self.pages += 1
            ex = Extract(); ex.feed(html_text)
            triples = extract_structured(ex)
            if self.extractor in ("llm", "both"):
                prov = getattr(self, "provider", None)
                if prov and (prov.get("kind") == "openai" or prov.get("base_url")):
                    triples += extract_openai(" ".join(ex.text), url, prov)
                else:
                    triples += extract_llm(" ".join(ex.text), url, self.llm_model)
            a = self.store_facts(triples, url)
            log(f"  [{self.pages}/{max_pages}] {url}  +{a} facts (total {self.stored})")
            for href in ex.links:
                nxt = urllib.parse.urljoin(url, href).split("#")[0]
                if nxt.startswith("http") and nxt not in self.visited and same_scope(nxt, self.scopes):
                    q.append(nxt)
            if self.pages % 50 == 0: self.st.flush()
        self.st.flush()
        log(f"done: crawled {self.pages} pages, stored {self.stored} facts from {self.scopes}")

def main():
    ap = argparse.ArgumentParser(description="Domain-scoped web harvester -> UFCS store (respects robots.txt).")
    ap.add_argument("store"); ap.add_argument("--seeds", required=True, help="comma-separated start URLs")
    ap.add_argument("--max-pages", type=int, default=200); ap.add_argument("--rate", type=float, default=1.0,
                    help="min seconds between requests to the same host")
    ap.add_argument("--extractor", choices=["structured", "llm", "both"], default="structured")
    ap.add_argument("--llm-model", default="claude-haiku-4-5", help="bulk extractor model (cheap tier by default)")
    ap.add_argument("--block-mb", type=int, default=1024); ap.add_argument("--codec", default="bz2")
    a = ap.parse_args()
    seeds = [s.strip() for s in a.seeds.split(",") if s.strip()]
    st = store.UFCSStore(a.store, a.block_mb, a.codec)
    h = Harvester(st, seeds, a.rate, a.extractor, a.llm_model)
    print(f"scope domains: {h.scopes} · extractor={a.extractor}")
    try: h.run(seeds, a.max_pages)
    finally: st.close()

if __name__ == "__main__":
    main()
