#!/usr/bin/env python3
"""
qb_api.py — a tiny read-only HTTP API over a local UFCS store (stdlib only).

Serves FQL / verify / get / stats over the content-addressed fact store built by
ufcs_store.py. Meant to sit behind nginx (which handles TLS + auth). Binds to
127.0.0.1 by default so it is only reachable through the reverse proxy.

  GET  /api/stats
  GET  /api/fql?subject=France&predicate=has_capital&trust_min=0.7&limit=10
  GET  /api/verify?subject=France&predicate=has_capital&object=Paris
  GET  /api/get?fp=<semantic_fingerprint>
  POST /api/chat   {"question": "...", "trust_min": 0.5, "limit": 8}
       QueryBook-LLM hybrid: answers ONLY from retrieved Fact Units, with
       citations + response_provenance_hash. Grounded by the LLM language layer
       when ANTHROPIC_API_KEY is set; deterministic fallback otherwise.

Env:
  QB_DATA_DIR        path to the store directory (default ./mystore)
  QB_BIND            host:port to listen on (default 127.0.0.1:8099)
  ANTHROPIC_API_KEY  optional; enables the LLM plan/compose/check layer for /api/chat
"""
import json, os, sys, time, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ufcs_store as store
import qb_chat
import qb_agents
import qb_selftest
import qb_keepawake
import qb_language
import qb_mirror
MIRROR = qb_mirror.MIRROR
import qb_log

DATA_DIR = os.environ.get("QB_DATA_DIR", "./mystore")
BIND = os.environ.get("QB_BIND", "127.0.0.1:8099")
AGENTS = qb_agents.AgentManager(DATA_DIR)

def open_store():
    return store.UFCSStore(DATA_DIR)

# ---- background harvest control (so the dashboard can start harvesting) ----
HARVEST = {"running": False, "target": 0, "done": 0, "started_at": 0.0, "error": None,
           "stop": False, "continuous": False, "samples": [], "peak_fps": 0.0, "ended_at": 0.0}
_HLOCK = threading.Lock()

# Per-Fact-Unit creation cost, measured once at startup (build + fingerprint + fuid of a
# packet, the CPU work per fact). Reported so the dashboard can show µs/fact.
PERF = {"per_fact_create_us": None}

# Cached self-test result. The full battery is expensive (real harvest ~seconds), so it
# runs at startup and only on explicit /api/selftest — never on the frequent health poll.
LAST_SELFTEST = {}

def _measure_per_fact():
    try:
        import timeit
        n = 5000
        t = timeit.timeit(lambda: store.make_packet("bench %d" % 1, "equals", "1", "+", "mathematics"), number=n)
        PERF["per_fact_create_us"] = round(t / n * 1e6, 2)
    except Exception:
        PERF["per_fact_create_us"] = None

def harvest_meter():
    """Live throughput metering: elapsed, average/instant/peak facts-per-second, µs/fact."""
    st_at = HARVEST.get("started_at") or 0.0
    if not st_at:
        return {"elapsed_s": 0, "facts_run": 0, "avg_fps": 0, "now_fps": 0,
                "peak_fps": round(HARVEST.get("peak_fps", 0), 1),
                "per_fact_us": PERF["per_fact_create_us"], "per_fact_us_live": None}
    end = HARVEST["ended_at"] if (not HARVEST["running"] and HARVEST["ended_at"]) else time.time()
    elapsed = max(1e-6, end - st_at)
    done = HARVEST.get("done", 0)
    avg = done / elapsed
    samples = HARVEST.get("samples", [])
    now = 0.0
    if len(samples) >= 2:
        (t0, n0), (t1, n1) = samples[0], samples[-1]
        if t1 > t0:
            now = (n1 - n0) / (t1 - t0)
    if now > HARVEST["peak_fps"]:
        HARVEST["peak_fps"] = now
    return {"elapsed_s": round(elapsed, 1), "facts_run": done,
            "avg_fps": round(avg, 1), "now_fps": round(now, 1),
            "peak_fps": round(HARVEST["peak_fps"], 1),
            "per_fact_us": PERF["per_fact_create_us"],
            "per_fact_us_live": round(1e6 / avg, 2) if avg > 0 else None}

def _run_harvest(count, domain="mathematics"):
    forever = int(count) <= 0
    HARVEST.update(running=True, target=(0 if forever else int(count)), done=0,
                   started_at=time.time(), error=None, stop=False, continuous=forever,
                   domain=domain, samples=[(time.time(), 0)], peak_fps=0.0, ended_at=0.0)
    qb_keepawake.acquire("harvest")   # don't let the PC sleep while harvesting
    qb_log.log("info", "harvest", "started domain=%s count=%s" % (domain, "24x7" if forever else count))
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        def prog(n, total):
            HARVEST["done"] = n
            s = HARVEST["samples"]
            s.append((time.time(), n))
            if len(s) > 8:                      # rolling window for instantaneous fps
                del s[0]
        store.harvest_into(DATA_DIR, int(count), "gzip", 1024,
                           progress=prog, should_stop=lambda: HARVEST.get("stop"),
                           domain=domain)
    except Exception as e:
        HARVEST["error"] = str(e)
    finally:
        HARVEST["running"] = False
        HARVEST["ended_at"] = time.time()
        qb_log.log("error" if HARVEST.get("error") else "ok", "harvest",
                   HARVEST.get("error") or ("stopped; %s facts this run" % HARVEST.get("done", 0)))
        qb_keepawake.release("harvest")   # allow the PC to sleep again

def start_harvest(count, domain="mathematics"):
    with _HLOCK:
        if HARVEST["running"]:
            return False
        threading.Thread(target=_run_harvest, args=(int(count), domain), daemon=True).start()
        return True

class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a): pass  # quiet; nginx logs

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path not in ("/api/chat", "/api/harvest", "/api/agents", "/api/agents/control",
                          "/api/providers", "/api/provider_test", "/api/fact", "/api/keepawake",
                          "/api/language/ingest", "/api/language/speak", "/api/mirror"):
            return self._send(404, {"error": "unknown endpoint"})
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, {"error": "invalid JSON body"})
        if u.path == "/api/agents":
            a = AGENTS.create(body.get("name", ""), body.get("kind", "deterministic"),
                              body.get("target", ""), body.get("interval", 10),
                              body.get("chunk", 50000), body.get("provider"),
                              body.get("extractor", "structured"))
            return self._send(200, a)
        if u.path == "/api/agents/control":
            ok = AGENTS.control(body.get("id", ""), body.get("action", ""))
            return self._send(200 if ok else 404, {"ok": ok})
        if u.path == "/api/providers":
            AGENTS.set_providers(body.get("providers", []))
            return self._send(200, {"ok": True, "count": len(AGENTS.providers)})
        if u.path == "/api/provider_test":
            # Live diagnostic: make ONE minimal real API call and report the exact result,
            # so a "Phase 2 blocked" mystery becomes a precise, fixable cause. Uses the
            # in-memory provider (which holds the real key), never a key echoed from the UI.
            want = (body.get("name") or "").strip()
            provs = AGENTS.providers or []
            prov = None
            if want:
                prov = next((p for p in provs if p.get("name") == want), None)
            if prov is None:
                prov = next((p for p in provs if (p.get("kind") == "anthropic"
                             or "anthropic" in (p.get("base_url") or ""))), None) or (provs[0] if provs else None)
            if prov is None:
                return self._send(400, {"ok": False, "code": "no_provider",
                                        "detail": "No LLM provider is configured. Add one first, "
                                                  "then paste your Anthropic API key (sk-ant-…)."})
            res = qb_chat.provider_test(prov)
            qb_log.log("ok" if res.get("ok") else "error", "provider-test",
                       "%s → %s: %s" % (res.get("provider"), res.get("code"),
                                        (res.get("detail") or "")[:160]))
            return self._send(200, res)
        if u.path == "/api/fact":
            s = (body.get("subject") or "").strip()
            p = (body.get("predicate") or "").strip()
            o = (body.get("object") or "").strip()
            if not (s and p and o):
                return self._send(400, {"error": "subject, predicate and object are required"})
            src_name = (body.get("source") or "user entry").strip()
            domain = (body.get("domain") or "user").strip()
            try: trust = float(body.get("trust", 0.9) or 0.9)
            except Exception: trust = 0.9
            packet = store.make_packet(s, p, o, "+", domain,
                                       ("SRC-USER", src_name, "user", 1.0), trust)
            try:
                st = open_store()
                try:
                    added = st.add(packet)
                    st.flush()
                finally:
                    st.close()
            except Exception as e:
                return self._send(500, {"error": str(e)})
            return self._send(200, {"added": bool(added), "packet": packet})
        if u.path == "/api/keepawake":
            # Master 24x7 switch: keep the PC awake in ALL modes until turned off.
            if "display" in body:
                qb_keepawake.set_display(bool(body.get("display")))
            if "on" in body:
                st = (qb_keepawake.enable_always_on() if body.get("on")
                      else qb_keepawake.disable_always_on())
            else:
                st = qb_keepawake.status()
            return self._send(200, st)
        if u.path == "/api/mirror":
            if body.get("on") is False or body.get("stop"):
                return self._send(200, MIRROR.stop_mirror())
            dest = (body.get("dest") or "").strip()
            if not dest:
                return self._send(400, {"error": "dest (external drive path) required"})
            try:
                qb_log.log("info", "offload", "mirroring store → " + dest)
                return self._send(200, MIRROR.start(DATA_DIR, dest,
                                                     int(body.get("interval", 5) or 5)))
            except Exception as e:
                return self._send(500, {"error": "could not start mirror: " + str(e)})
        if u.path == "/api/language/speak":
            # Phase 4: deterministic pronunciation analysis of the text + real audio via the
            # OS's built-in TTS (base64 WAV). No LLM. If no engine, returns available:false.
            import base64
            text = (body.get("text") or "").strip()
            lang = (body.get("lang") or "en").lower()
            if not text:
                return self._send(400, {"error": "text required"})
            analysis = [qb_language.analyze_pronunciation(w, lang) for w in text.split()[:20]]
            prosody = qb_language._prosody(text)
            tts = qb_language.speak(text, lang=lang)
            out = {"text": text, "lang": lang, "speakable": qb_language.speakable_languages(),
                   "prosody": prosody, "analysis": analysis,
                   "tts": {"available": tts.get("available"), "engine": tts.get("engine"),
                           "lang": tts.get("lang"), "error": tts.get("error")}}
            if tts.get("wav_bytes"):
                out["audio_b64"] = base64.b64encode(tts["wav_bytes"]).decode("ascii")
                out["mime"] = tts.get("mime", "audio/wav")
            return self._send(200, out)
        if u.path == "/api/language/ingest":
            try:
                if body.get("preview"):
                    txt = (body.get("text") or "").strip()
                    if not txt:
                        return self._send(400, {"error": "no text to preview"})
                    res = qb_language.analyze_only(txt)
                    res["preview"] = True
                else:
                    res = qb_language.learn(DATA_DIR, text=body.get("text"),
                                            url=(body.get("url") or None),
                                            source=body.get("source"))
            except Exception as e:
                return self._send(502, {"error": "language ingest failed: " + str(e)})
            return self._send(200 if "error" not in res else 400, res)
        if u.path == "/api/harvest":
            if body.get("stop"):
                HARVEST["stop"] = True
                return self._send(200, {"stopping": True})
            try:
                count = int(body.get("count", 250000) or 250000)
            except Exception:
                return self._send(400, {"error": "count must be a number"})
            # count <= 0 means run forever (24x7) until stopped
            if count > 0:
                count = min(count, 5_000_000_000)
            domain = (body.get("domain") or "mathematics").strip().lower()
            if domain not in store.DOMAIN_GEN:
                return self._send(400, {"error": "unknown domain '%s'; choose one of: %s"
                                        % (domain, ", ".join(store.DOMAIN_GEN))})
            started = start_harvest(count, domain)
            return self._send(200, {"started": started, "running": HARVEST["running"],
                                    "target": HARVEST["target"], "continuous": HARVEST["continuous"],
                                    "domain": domain,
                                    "note": "already running" if not started else "harvest started"})
        question = (body.get("question") or "").strip()
        if not question:
            return self._send(400, {"error": "question required"})
        try:
            st = open_store()
            if st.no_fql:
                st.db.close()
                return self._send(409, {"error": "store built with --no-fql-index; chat needs the FQL index"})
            try:
                # Use the provider the user configured in the dashboard (POST body can
                # name one; otherwise prefer an Anthropic provider, else the first).
                provs = AGENTS.providers or []
                want = (body.get("provider") or "").strip()
                prov = None
                if want:
                    prov = next((p for p in provs if p.get("name") == want), None)
                if prov is None:
                    prov = next((p for p in provs if (p.get("kind") == "anthropic"
                                 or "anthropic" in (p.get("base_url") or ""))), None)
                if prov is None and provs:
                    prov = provs[0]
                res = qb_chat.answer(st, question,
                                     float(body.get("trust_min", 0.5) or 0.5),
                                     int(body.get("limit", 8) or 8),
                                     provider=prov)
                self._send(200, res)
            finally:
                st.db.close()
        except Exception as e:
            self._send(500, {"error": str(e)})

    def _send_html(self, path):
        try:
            with open(path, "rb") as fh:
                body = fh.read()
        except OSError:
            return self._send(404, {"error": "chat.html not found next to qb_api.py"})
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def _asset_path(self, env_var, filename):
        # explicit override, else PyInstaller bundle dir, else next to this file
        p = os.environ.get(env_var)
        if p and os.path.exists(p): return p
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, filename)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path in ("/", "/chat", "/chat.html"):
            return self._send_html(self._asset_path("QB_CHAT_HTML", "chat.html"))
        if u.path in ("/dashboard", "/dashboard.html", "/live"):
            return self._send_html(self._asset_path("QB_DASHBOARD_HTML", "dashboard.html"))
        if u.path in ("/console", "/console.html", "/dashboards"):
            return self._send_html(self._asset_path("QB_CONSOLE_HTML", "console.html"))
        if u.path in ("/language", "/language.html", "/lang"):
            return self._send_html(self._asset_path("QB_LANGUAGE_HTML", "language.html"))
        if u.path in ("/guide", "/guide.html", "/help", "/docs"):
            return self._send_html(self._asset_path("QB_GUIDE_HTML", "guide.html"))
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            st = open_store()
            try:
                if u.path == "/api/stats":
                    m = st.manifest
                    try: disk = st.compressed_bytes()
                    except Exception: disk = 0
                    self._send(200, {"facts": m.get("facts", 0), "blocks": m.get("blocks", 0),
                                     "duplicates": m.get("duplicates", 0), "codec": st.codec,
                                     "packed": st.pack, "fql_index": not st.no_fql,
                                     "disk_bytes": disk, "disk_mb": round(disk/1e6, 2),
                                     "data_dir": DATA_DIR, "last_verify": m.get("last_verify")})
                elif u.path == "/api/sample":
                    if st.no_fql: return self._send(200, {"results": []})
                    n = max(1, min(50, int(q.get("n", 8) or 8)))
                    rows = st.db.execute(
                        "SELECT subject, predicate, object, trust, fp FROM nuc ORDER BY rowid DESC LIMIT ?",
                        (n,)).fetchall()
                    self._send(200, {"results": [{"subject": r[0], "predicate": r[1], "object": r[2],
                                                  "trust": r[3], "fingerprint": r[4]} for r in rows]})
                elif u.path == "/api/harvest_status":
                    self._send(200, {**{k: v for k, v in HARVEST.items() if k != "samples"},
                                     "facts": st.manifest.get("facts", 0),
                                     "meter": harvest_meter(),
                                     "keepawake": qb_keepawake.status()})
                elif u.path == "/api/perf":
                    self._send(200, {"meter": harvest_meter(), "per_fact_create_us": PERF["per_fact_create_us"]})
                elif u.path == "/api/mirror":
                    self._send(200, MIRROR.status())
                elif u.path == "/api/log":
                    if q.get("clear"):
                        qb_log.clear(); qb_log.log("info", "diagnostics", "log cleared by user")
                    self._send(200, {"entries": qb_log.entries(int(q.get("limit", 120) or 120),
                                                               q.get("level") or None),
                                     "counts": qb_log.counts()})
                elif u.path == "/api/keepawake":
                    self._send(200, qb_keepawake.status())
                elif u.path == "/api/agents":
                    self._send(200, AGENTS.snapshot())
                elif u.path == "/api/agent_roles":
                    self._send(200, {"roles": AGENTS.roles()})
                elif u.path == "/api/selftest":
                    global LAST_SELFTEST
                    LAST_SELFTEST = qb_selftest.run_all(DATA_DIR)   # explicit, on-demand full battery
                    self._send(200, LAST_SELFTEST)
                elif u.path == "/api/domain_logic":
                    self._send(200, {"domains": store.domain_list()})
                elif u.path == "/api/language/status":
                    self._send(200, qb_language.status(DATA_DIR))
                elif u.path == "/api/language/phases":
                    self._send(200, qb_language.phases(DATA_DIR))
                elif u.path == "/api/language/sources":
                    self._send(200, {"sources": qb_language.SEED_SOURCES})
                elif u.path == "/api/language/grounding":
                    # Phase 2 deterministic grounding coverage (dictionary + store; no LLM).
                    self._send(200, qb_language.grounding_status(DATA_DIR))
                elif u.path == "/api/language/multilingual":
                    # Phase 3 deterministic delta coverage (bilingual dictionary; no LLM).
                    self._send(200, qb_language.multilingual_status(DATA_DIR))
                elif u.path == "/api/language/speech":
                    # Phase 4 status: pronunciation-analysis coverage + OS TTS availability.
                    self._send(200, qb_language.speech_status(DATA_DIR))
                elif u.path == "/api/hypotheses":
                    # LLM-proposed/projected, store-verified candidates (non-asserting; isolated domains).
                    items = []
                    if not st.no_fql:
                        rows = st.db.execute(
                            "SELECT subject, object, trust FROM nuc WHERE predicate='verification_status' "
                            "ORDER BY rowid DESC LIMIT 80").fetchall()
                        for subj, status, tr in rows:
                            kind = "hypothesis"
                            triple = subj
                            for pfx, k in (('hypothesis "', "hypothesis"), ('simulation "', "simulation"),
                                           ('reasoning "', "reasoning")):
                                if subj.startswith(pfx):
                                    kind = k; triple = subj[len(pfx):-1]; break
                            items.append({"type": kind, "candidate": triple, "status": status, "trust": tr})
                    self._send(200, {"hypotheses": items, "count": len(items),
                                     "note": "LLM proposals/projections verified against the store; never asserted as fact."})
                elif u.path == "/api/plans":
                    # NLPL planner output: ordered operational steps (non-asserting proposals).
                    plans = {}
                    if not st.no_fql:
                        rows = st.db.execute(
                            "SELECT subject, predicate, object FROM nuc WHERE predicate LIKE 'plan_step:%' "
                            "OR predicate='plan_status' ORDER BY subject, predicate").fetchall()
                        for subj, pred, obj in rows:
                            goal = subj[len('plan "'):-1] if subj.startswith('plan "') else subj
                            g = plans.setdefault(goal, {"goal": goal, "status": "", "steps": []})
                            if pred == "plan_status":
                                g["status"] = obj
                            else:
                                g["steps"].append(obj)
                    self._send(200, {"plans": list(plans.values()), "count": len(plans),
                                     "note": "Plans are non-asserting proposals; they assert no facts."})
                elif u.path == "/api/domains":
                    # real breakdown of what's actually stored, grouped by relation (predicate)
                    rows = []
                    if not st.no_fql:
                        rows = st.db.execute(
                            "SELECT predicate, COUNT(*) c FROM nuc GROUP BY predicate ORDER BY c DESC LIMIT 40"
                        ).fetchall()
                    self._send(200, {"by_relation": [{"predicate": r[0], "count": r[1]} for r in rows],
                                     "by_domain": store.domain_counts(DATA_DIR),
                                     "total": st.manifest.get("facts", 0)})
                elif u.path == "/api/health":
                    # CHEAP health: counters + errored agents + the CACHED startup self-test.
                    # It must NEVER re-run the self-test battery here — that battery does real
                    # harvesting and took ~7s, and polling it every few seconds saturated the
                    # server so the dashboard never finished loading. Full re-run is /api/selftest.
                    m = st.manifest
                    ags = AGENTS.snapshot().get("agents", [])
                    errored = [{"name": a["name"], "kind": a["kind"], "error": a.get("error"),
                                "retries": a.get("retries", 0)} for a in ags if a.get("status") == "error"]
                    stres = LAST_SELFTEST or {"all_ok": None, "passed": None, "total": None}
                    self._send(200, {
                        "ok": (stres.get("all_ok") is not False) and not errored,
                        "selftest": {"passed": stres.get("passed"), "total": stres.get("total"),
                                     "all_ok": stres.get("all_ok"), "cached": True},
                        "facts": m.get("facts", 0), "duplicates": m.get("duplicates", 0),
                        "blocks": m.get("blocks", 0), "last_verify": m.get("last_verify"),
                        "by_domain": store.domain_counts(DATA_DIR),
                        "agents_total": len(ags), "agents_errored": errored,
                        "data_dir": DATA_DIR})
                elif u.path == "/api/fql":
                    if st.no_fql: return self._send(409, {"error": "store built with --no-fql-index; FQL unavailable"})
                    rows, rph = st.fql(q.get("subject"), q.get("predicate"),
                                       float(q.get("trust_min", 0) or 0), int(q.get("limit", 10) or 10))
                    self._send(200, {"results": [{"subject": r[0], "predicate": r[1], "object": r[2],
                                                   "trust": r[3], "fingerprint": r[4]} for r in rows],
                                     "count": len(rows), "response_provenance_hash": rph})
                elif u.path == "/api/verify":
                    s, p, o = q.get("subject", ""), q.get("predicate", ""), q.get("object", "")
                    if not (s and p and o): return self._send(400, {"error": "subject, predicate, object required"})
                    fp = store.fingerprint(s, p, o)
                    rec = st.get(fp)
                    self._send(200, {"verdict": "VERIFIED" if rec else "UNKNOWN",
                                     "fingerprint": fp, "record": rec})
                elif u.path == "/api/get":
                    fp = q.get("fp", "")
                    if not fp: return self._send(400, {"error": "fp required"})
                    rec = st.get(fp)
                    self._send(200 if rec else 404, rec or {"error": "not found"})
                elif u.path == "/api/version":
                    self._send(200, {"build": "v9.16", "date": "2026-09-30",
                                     "features": ["language-lab", "phased-agents", "build-english-first",
                                                  "per-domain-counts", "self-heal", "store-health",
                                                  "provider-live-test", "phase2-deterministic-dictionary-store", "llm-lockout-enforced", "hypothesis-agent", "simulation-agent", "reasoning-agent", "gate-multivalued", "planner-agent", "phase3-multilingual-delta", "launcher-frees-port", "phase4-speech"]})
                elif u.path == "/api/":
                    self._send(200, {"ok": True, "data_dir": DATA_DIR})
                else:
                    self._send(404, {"error": "unknown endpoint"})
            finally:
                st.db.close()
        except Exception as e:
            self._send(500, {"error": str(e)})

def main():
    host, port = BIND.split(":")
    if not os.path.isdir(DATA_DIR):
        print(f"WARNING: store dir {DATA_DIR} not found; /api/stats will error until you harvest.", flush=True)
    # One-time repair: make the on-disk fact counter match what's actually in the index,
    # fixing counters corrupted by the earlier concurrency race in existing stores.
    try:
        rc = store.reconcile_manifest(DATA_DIR)
        if rc and rc["was"] != rc["now"]:
            print(f"  COUNTER REPAIR: fact count {rc['was']:,} → {rc['now']:,} (matched to index)", flush=True)
    except Exception as e:
        print(f"  counter reconcile skipped: {e}", flush=True)
    # Self-heal supervisor: transiently-errored agents auto-restart with backoff.
    try:
        AGENTS.start_supervisor()
        print("  SELF-HEAL: agent supervisor on (auto-restart with backoff)", flush=True)
    except Exception as e:
        print(f"  supervisor could not start: {e}", flush=True)
    # Metering: measure per-Fact-Unit creation cost once.
    _measure_per_fact()
    print(f"  METER: per-Fact-Unit creation ~{PERF['per_fact_create_us']} µs (CPU)", flush=True)
    # Parallel drive offload: if QB_MIRROR_DIR is set, mirror the store to it in the background
    # so harvesting stays on the fast internal drive and the external copy fills concurrently.
    try:
        md = os.environ.get("QB_MIRROR_DIR")
        if md:
            MIRROR.start(DATA_DIR, md)
            print(f"  OFFLOAD: mirroring store → {md} (parallel)", flush=True)
    except Exception as e:
        print(f"  offload could not start: {e}", flush=True)
    srv = ThreadingHTTPServer((host, int(port)), H)
    # Watchdog + keep-awake: heartbeat to <store>/keepawake.log so we can PROVE
    # whether a black screen was a real sleep (time gap) or just display-off.
    # Restores the 24x7 master switch if it was left on last session.
    try:
        log = qb_keepawake.start_monitor(DATA_DIR)
        ka = qb_keepawake.status()
        print(f"  KEEP-AWAKE: watchdog on, log at {log}"
              + ("  ·  24x7 MODE: ON" if ka.get("engaged") and "mode:24x7" in ka.get("holders", []) else ""),
              flush=True)
    except Exception as e:
        print(f"  KEEP-AWAKE could not start: {e}", flush=True)
    print("=" * 60, flush=True)
    print("  QueryBook  BUILD v9.16 · 2026-09-30  (Phase 4 multilingual speech: en/es/fr/de/pt/it/sv/nl)", flush=True)
    print("=" * 60, flush=True)
    qb_log.log("info", "server", "QueryBook BUILD v9.16 started on http://" + BIND)
    llm = "on" if qb_chat._have_llm() else "off (deterministic fallback)"
    print(f"qb_api serving {DATA_DIR} on http://{BIND}", flush=True)
    print(f"  OPEN THIS:  http://{BIND}/dashboard   ·   Language Lab: http://{BIND}/language", flush=True)
    print(f"  GET /api/stats /api/fql /api/verify /api/get   ·   POST /api/chat (LLM layer: {llm})", flush=True)
    # Quality control: run the self-test battery ONCE at startup (cached for /api/health).
    global LAST_SELFTEST
    try:
        r = qb_selftest.run_all(DATA_DIR)
        LAST_SELFTEST = r
        print(f"  SELF-TEST: {r['passed']}/{r['total']} checks passed"
              + ("" if r["all_ok"] else "  *** SOME CHECKS FAILED ***"), flush=True)
        for c in r["checks"]:
            print(("    [PASS] " if c["ok"] else "    [FAIL] ") + c["name"], flush=True)
    except Exception as e:
        print(f"  SELF-TEST could not run: {e}", flush=True)
    srv.serve_forever()

if __name__ == "__main__":
    main()
