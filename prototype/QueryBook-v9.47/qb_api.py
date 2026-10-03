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
import qb_help

BUILD = "v9.60"
BUILD_DATE = "2026-10-03"
DATA_DIR = os.environ.get("QB_DATA_DIR", "./mystore")
BIND = os.environ.get("QB_BIND", "127.0.0.1:8099")
AGENTS = qb_agents.AgentManager(DATA_DIR)
START_TIME = time.time()   # server start, for the System Monitor uptime

# No security: the app is always open (no password, no login). Bind to 0.0.0.0 to reach
# it from other devices on your network; bind to 127.0.0.1 to keep it to this machine.


def _local_ipv4s():
    """Detect this machine's own IPv4 addresses (LAN + Tailscale), so the app can print
    complete, ready-to-click monitor links instead of asking the user to build a URL."""
    import socket
    ips = []
    seen = set()
    def add(ip):
        if ip and ip not in seen and not ip.startswith("127.") and ":" not in ip:
            seen.add(ip); ips.append(ip)
    # primary route IP (the LAN address other devices use)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8", 80))
        add(s.getsockname()[0]); s.close()
    except Exception:
        pass
    # every address bound to the hostname (picks up Tailscale 100.x, extra NICs)
    try:
        for res in socket.getaddrinfo(socket.gethostname(), None):
            add(res[4][0])
    except Exception:
        pass
    # Tailscale addresses sort first (most useful for remote), then other LAN IPs
    ips.sort(key=lambda x: (not x.startswith("100."), x))
    return ips


def access_urls():
    """Full monitor URLs for every way to reach this server from a device."""
    port = BIND.split(":")[-1]
    urls = ["http://localhost:%s/monitor" % port]
    for ip in _local_ipv4s():
        urls.append("http://%s:%s/monitor" % (ip, port))
    return urls


# ---- Zero-config auto-discovery ------------------------------------------------
# The learning STATION announces itself on the local network with a small UDP
# beacon. Any other device on the same network (your dev machine) can find it
# with `python qb_api.py discover` — no IP typing, no URL building, no static IP.
# Pure stdlib UDP broadcast on 255.255.255.255; works on any LAN / hotspot / VPN
# that passes broadcast. Nothing leaves the local network.
QB_BEACON_PORT = int(os.environ.get("QB_BEACON_PORT", "48900"))
QB_BEACON_MAGIC = "QUERYBOOK-STATION/1"


def _beacon_payload():
    import socket as _s, json as _j
    port = BIND.split(":")[-1]
    return (QB_BEACON_MAGIC + " " + _j.dumps({
        "magic": QB_BEACON_MAGIC,
        "name": _s.gethostname(),
        "build": BUILD,
        "port": port,
        "secure": False,
        "ips": _local_ipv4s(),
        "urls": access_urls(),
    })).encode("utf-8")


def _start_beacon():
    """Broadcast this station's presence every few seconds so other devices find it."""
    import socket, threading
    def loop():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except Exception:
            return
        while True:
            try:
                sock.sendto(_beacon_payload(), ("255.255.255.255", QB_BEACON_PORT))
            except Exception:
                pass
            time.sleep(3)
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


def discover_stations(timeout=6.0):
    """Listen for station beacons on this network and return what we hear."""
    import socket, json
    found = {}
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except Exception:
            pass
        sock.bind(("", QB_BEACON_PORT))
        sock.settimeout(1.0)
    except Exception as e:
        return {"error": str(e), "stations": []}
    end = time.time() + timeout
    while time.time() < end:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            continue
        except Exception:
            break
        txt = data.decode("utf-8", "replace")
        if not txt.startswith(QB_BEACON_MAGIC):
            continue
        try:
            info = json.loads(txt[len(QB_BEACON_MAGIC):].strip())
        except Exception:
            continue
        # build URLs the finding device can actually reach: the sender's source IP
        src = addr[0]
        port = info.get("port", "8099")
        urls = ["http://%s:%s/monitor" % (src, port)]
        for ip in info.get("ips", []):
            u = "http://%s:%s/monitor" % (ip, port)
            if u not in urls:
                urls.append(u)
        info["reachable_urls"] = urls
        info["source_ip"] = src
        found[info.get("name", src) + "@" + src] = info
    try:
        sock.close()
    except Exception:
        pass
    return {"error": None, "stations": list(found.values())}

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

def _store_health_banner():
    """At boot: show the ABSOLUTE store path and how many facts/languages are in it,
    self-repair a stale fact counter from the index, and — if the store is empty —
    shout about it and point at any non-empty store found next to this folder, so a
    week of data is NEVER silently reported as 'gone' again."""
    try:
        import ufcs_store
        abspath = os.path.abspath(DATA_DIR)
        # Self-heal a stale/zero counter from the real index (never deletes anything).
        rec = None
        try:
            rec = ufcs_store.reconcile_manifest(DATA_DIR)
        except Exception:
            rec = None
        facts = 0
        try:
            with open(os.path.join(DATA_DIR, "manifest.json"), encoding="utf-8") as f:
                facts = int(json.load(f).get("facts", 0))
        except Exception:
            facts = (rec or {}).get("now", 0) or 0
        langs = ""
        try:
            lm = os.path.join(DATA_DIR, "language_model.json")
            if os.path.isfile(lm):
                with open(lm, encoding="utf-8") as f:
                    m = json.load(f)
                words = len(m.get("words") or {})
                ingests = m.get("ingests", 0)
                langs = f"language model present ({words:,} words, {ingests} ingest(s))"
        except Exception:
            langs = ""
        print("  " + "-" * 56, flush=True)
        print(f"  STORE: {abspath}", flush=True)
        print(f"  DATA:  {facts:,} facts" + (f"  ·  languages: {langs}" if langs else ""), flush=True)
        if rec and rec.get("was") != rec.get("now"):
            print(f"  (repaired fact counter {rec['was']:,} → {rec['now']:,} from the on-disk index)", flush=True)
        if facts == 0:
            print("  " + "!" * 56, flush=True)
            print("  WARNING: this store is EMPTY. Your data is NOT lost — it lives in", flush=True)
            print("  the `mystore` folder of whichever QueryBook folder you ran before.", flush=True)
            # Fast, shallow scan for a real store: look at this app folder, its parent,
            # and the sibling version folders next to it (…/QueryBook-vX.YZ/mystore).
            found = []
            try:
                appdir = os.path.dirname(abspath.rstrip(os.sep))     # …/QueryBook-vX.YZ
                cands = []
                for base in (appdir, os.path.dirname(appdir)):        # app folder + grandparent
                    if not os.path.isdir(base):
                        continue
                    cands += [os.path.join(base, "mystore"), os.path.join(base, "store")]
                    try:
                        for name in os.listdir(base):
                            p = os.path.join(base, name)
                            if os.path.isdir(p):
                                cands += [p, os.path.join(p, "mystore"), os.path.join(p, "store")]
                    except OSError:
                        pass
                seen = set()
                for c in cands:
                    c = os.path.abspath(c)
                    if c in seen or c == abspath:
                        continue
                    seen.add(c)
                    if os.path.isdir(os.path.join(c, "blocks")):
                        n = 0
                        try:
                            with open(os.path.join(c, "manifest.json"), encoding="utf-8") as f:
                                n = int(json.load(f).get("facts", 0))
                        except Exception:
                            n = 0
                        if n > 0:
                            found.append((n, c))
            except Exception:
                pass
            found.sort(reverse=True)
            if found:
                n, best = found[0]
                print(f"  FOUND your data: {n:,} facts at  {best}", flush=True)
                if os.name == "nt":
                    print(f"  Start against it:   set QB_DATA_DIR={best}  &&  python qb_api.py", flush=True)
                else:
                    print(f"  Start against it:   QB_DATA_DIR='{best}' python3 qb_api.py", flush=True)
            else:
                print("  Find it with:   python3 qb_find_store.py", flush=True)
            print("  " + "!" * 56, flush=True)
    except Exception as e:
        print(f"  (store health check skipped: {e})", flush=True)

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
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, {"error": "invalid JSON body"})
        if u.path not in ("/api/chat", "/api/harvest", "/api/agents", "/api/agents/control",
                          "/api/providers", "/api/provider_test", "/api/fact", "/api/keepawake",
                          "/api/language/ingest", "/api/language/speak", "/api/language/translate",
                          "/api/language/teach", "/api/language/teach_all", "/api/language/run_all",
                          "/api/language/go", "/api/language/tts_key", "/api/language/voices",
                          "/api/language/custom_voice", "/api/language/dialects",
                          "/api/language/dialect_detect", "/api/mirror", "/api/help") \
                and not u.path.startswith("/api/director/") \
                and not u.path.startswith("/api/scene/") \
                and not u.path.startswith("/api/lil/") \
                and not u.path.startswith("/api/pil/") \
                and not u.path.startswith("/api/query/") \
                and not u.path.startswith("/api/rights/") \
                and not u.path.startswith("/api/integrity/") \
                and not u.path.startswith("/api/middleware/") \
                and not u.path.startswith("/api/edu/") \
                and not u.path.startswith("/api/collab/") \
                and not u.path.startswith("/api/saas/") \
                and u.path not in ("/api/ontology", "/api/assess", "/api/webhooks", "/api/video/poll"):
            return self._send(404, {"error": "unknown endpoint"})
        if u.path == "/api/agents":
            a = AGENTS.create(body.get("name", ""), body.get("kind", "deterministic"),
                              body.get("target", ""), body.get("interval", 10),
                              body.get("chunk", 50000), body.get("provider"),
                              body.get("extractor", "structured"))
            return self._send(200, a)
        if u.path == "/api/agents/control":
            ok = AGENTS.control(body.get("id", ""), body.get("action", ""))
            return self._send(200 if ok else 404, {"ok": ok})
        if u.path == "/api/help":
            # Claude-assisted UI help: answer how-to questions about the prototype's interface,
            # using the configured API provider when present, else a deterministic reference match.
            # It explains the UI only and writes nothing to the store.
            q = (body.get("question") or "").strip()
            if not q:
                return self._send(400, {"error": "question required"})
            provs = AGENTS.providers or []
            prov = next((p for p in provs if (p.get("kind") == "anthropic"
                         or "anthropic" in (p.get("base_url") or ""))), None) or (provs[0] if provs else None)
            if prov is None and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
                # honor a plain env key even when no provider was configured in the dashboard
                prov = {"kind": "anthropic", "key_env": "ANTHROPIC_API_KEY", "model": "claude-haiku-4-5"}
            if prov and qb_chat.provider_usable(prov):
                try:
                    ans = qb_chat.llm_complete(prov, "USER QUESTION: " + q,
                                               system=qb_help.HELP_SYSTEM, max_tokens=700)
                    if ans:
                        return self._send(200, {"answer": ans, "source": "claude",
                                                "model": prov.get("model") or "(provider default)"})
                except Exception as e:
                    qb_log.log("warn", "help", "LLM help failed, using reference: %s" % e)
            return self._send(200, {"answer": qb_help.answer_fallback(q), "source": "reference"})
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
            # Whole-phrase analysis: ONE espeak call (accurate, matches the audio) when espeak
            # is present, else the instant rule phonemizer. Never one process per word.
            # Optional dialect (DPC): overlays deterministic phonology on the IPA and steers
            # the voice (accent via cloud style / espeak voice variant).
            dialect = body.get("dialect") or None
            analysis = qb_language.analyze_phrase(text, lang, max_words=12, dialect=dialect)
            prosody = qb_language._prosody(text)
            # Optional cloud voice provider ('google'|'elevenlabs'); open-source stays the default
            # and the offline fallback. 'provider' empty/omitted => open-source engine.
            provider = (body.get("provider") or "").lower() or None
            voice = body.get("voice") or None
            # Google natural-language style steering (tone/emotion/accent/pace/acting direction);
            # ElevenLabs voice-control settings; a locally-built Google custom (cloned) voice.
            style = body.get("style") or None
            settings = body.get("settings") if isinstance(body.get("settings"), dict) else None
            custom_voice = body.get("custom_voice") or None
            model = body.get("model") or None
            tts = qb_language.speak(text, lang=lang, provider=provider, voice=voice, style=style,
                                    settings=settings, custom_voice=custom_voice, model=model,
                                    dialect=dialect)  # ONE call
            out = {"text": text, "lang": lang, "speakable": qb_language.speakable_languages(),
                   "prosody": prosody, "analysis": analysis, "dialect": dialect,
                   "tts": {"available": tts.get("available"), "engine": tts.get("engine"),
                           "lang": tts.get("lang"), "error": tts.get("error"),
                           "cloud_error": qb_language._CLOUD_ERR[0]}}
            if tts.get("wav_bytes"):
                out["audio_b64"] = base64.b64encode(tts["wav_bytes"]).decode("ascii")
                out["mime"] = tts.get("mime", "audio/wav")
            return self._send(200, out)
        if u.path == "/api/language/tts_key":
            # Save a cloud voice provider key/voice LOCALLY (git-ignored file). The key is a
            # secret: it is stored on this machine only and is NEVER returned to the client.
            provider = (body.get("provider") or "").lower()
            key = body.get("key")
            voice = body.get("voice")
            model = body.get("model")
            settings = body.get("settings") if isinstance(body.get("settings"), dict) else None
            r = {"ok": True, "provider": provider}
            if key or voice or model or settings:
                r = qb_language.save_tts_key(provider, key=key, voice=voice, model=model, settings=settings)
            # Optionally make this the default voice engine (e.g. Google), or set default only.
            if body.get("make_default") or body.get("default_only"):
                d = qb_language.set_default_provider(provider)
                r["default_provider"] = d.get("default_provider")
                if not d.get("ok"):
                    r["ok"] = False; r["error"] = d.get("error")
            return self._send(200 if r.get("ok") else 400, r)
        if u.path == "/api/language/voices":
            # List selectable voices for a provider (Google = 30 prebuilt + local custom voices;
            # ElevenLabs = live account lookup). Never returns any key.
            provider = (body.get("provider") or "google").lower()
            return self._send(200, qb_language.list_voices(provider))
        if u.path == "/api/language/custom_voice":
            # Build a Google custom (cloned) voice from an uploaded voice SAMPLE. Gated on
            # explicit consent (covenant). The cloning key is stored locally and NEVER returned.
            import base64 as _b64
            action = (body.get("action") or "build").lower()
            if action == "delete":
                return self._send(200, qb_language.delete_custom_voice(body.get("name") or ""))
            name = (body.get("name") or "").strip()
            consent = bool(body.get("consent"))
            audio_b64 = body.get("audio_b64") or ""
            mime = body.get("mime") or ""
            lang = body.get("language") or "en-US"
            if not audio_b64:
                return self._send(400, {"ok": False, "error": "a voice sample (audio_b64) is required"})
            try:
                audio = _b64.b64decode(audio_b64)
            except Exception:
                return self._send(400, {"ok": False, "error": "invalid audio_b64"})
            r = qb_language.google_build_custom_voice(name, audio, consent=consent, language=lang, mime=mime)
            return self._send(200 if r.get("ok") else 400, r)
        if u.path == "/api/language/translate":
            # Deterministic dictionary translation (no LLM). text + src + dst.
            # src defaults to "auto" — the source language is auto-sensed.
            text = (body.get("text") or "").strip()
            src = (body.get("src") or "auto").lower()
            dst = (body.get("dst") or "en").lower()
            dialect = body.get("dialect") or None
            if not text:
                return self._send(400, {"error": "text required"})
            # If a source dialect is named, normalize dialect surface forms to their standard
            # forms (+ record FU meaning atoms) BEFORE the deterministic translator runs, so a
            # dialect word carries its shared meaning across languages.
            dialect_norm = None
            try:
                import qb_dialect
                if dialect and dialect in qb_dialect.DIALECTS:
                    std, hits = qb_dialect.normalize_lexicon(text, dialect)
                    if hits:
                        text = std; dialect_norm = {"standardized": std, "hits": hits}
            except Exception:
                pass
            r = qb_language.translate(text, src, dst)
            if dialect_norm:
                r["dialect_normalization"] = dialect_norm
            return self._send(200 if "error" not in r else 400, r)
        if u.path == "/api/language/dialects":
            # List available Dialect Parameter Clusters (optionally for one parent language), or
            # the full DPC for one dialect when 'id' is given.
            import qb_dialect
            did = body.get("id")
            if did:
                info = qb_dialect.dialect_info(did)
                return self._send(200 if info else 404, info or {"error": "unknown dialect"})
            return self._send(200, {"dialects": qb_dialect.dialects_for(body.get("lang") or None)})
        if u.path == "/api/language/dialect_detect":
            # Deterministic dialect detection: rank DPCs by lexical markers + orthographic cues.
            import qb_dialect
            text = (body.get("text") or "").strip()
            if not text:
                return self._send(400, {"error": "text required"})
            return self._send(200, {"text": text,
                "candidates": qb_dialect.detect_dialect(text, body.get("lang") or None)})
        if u.path.startswith("/api/director/"):
            # QueryBook -> Gemini Omni adapter (deterministic scene director). Prompt generation
            # is pure templating (no LLM, covenant-safe); video rendering is gated + offline-first.
            import qb_gemini
            tail = u.path[len("/api/director/"):]
            if tail == "example":
                return self._send(200, {"fu": qb_gemini.NOIR_BAR_FU})
            if tail == "qc":
                return self._send(200, qb_gemini.qc())
            if tail == "scenegraph":
                fu = body.get("fu") or body
                return self._send(200, qb_gemini.build_scene_graph_from_fu(fu))
            if tail == "prompts":
                # Accept either a SceneGraph ('scene') or an FUGraph ('fu').
                scene = body.get("scene") or (qb_gemini.build_scene_graph_from_fu(body.get("fu") or {})
                                              if (body.get("fu") or body.get("entities")) else None)
                if not scene and body.get("entities"):
                    scene = qb_gemini.build_scene_graph_from_fu(body)
                if not scene:
                    return self._send(400, {"error": "provide 'fu' or 'scene'"})
                return self._send(200, {"scene": scene,
                    "validation": qb_gemini.validate_scene_graph(scene),
                    "promptBundle": qb_gemini.generate_prompt_bundle(scene)})
            if tail == "validate":
                scene = body.get("scene") or qb_gemini.build_scene_graph_from_fu(body.get("fu") or body)
                return self._send(200, qb_gemini.validate_scene_graph(scene))
            if tail == "render":
                fu = body.get("fu") or body
                if not fu.get("entities"):
                    return self._send(400, {"error": "provide 'fu' with entities"})
                return self._send(200, qb_gemini.render_scene_from_fu(
                    fu, base_media=body.get("base_media"),
                    observed_per_iteration=body.get("observed_per_iteration"),
                    model=body.get("model") or "veo-3.1-fast-generate-preview"))
            return self._send(404, {"error": "unknown director endpoint"})
        if u.path.startswith("/api/scene/"):
            # Scene Reconstructor: prose/script → director-controlled video plan + prompts + music.
            import qb_scene
            tail = u.path[len("/api/scene/"):]
            if tail == "styles":
                return self._send(200, {"styles": qb_scene.list_styles()})
            if tail == "example":
                return self._send(200, {"sourceText": qb_scene.NOIR_TEXT})
            if tail == "qc":
                return self._send(200, qb_scene.qc())
            if tail == "render":
                text = (body.get("sourceText") or body.get("text") or "").strip()
                if not text:
                    return self._send(400, {"error": "sourceText required"})
                r = qb_scene.render_scene_from_text(
                    text, style=body.get("styleId") or body.get("style") or "film_noir",
                    duration=int(body.get("durationSeconds") or body.get("duration") or 20),
                    perspective=body.get("perspective") or "objective",
                    period=body.get("periodHint") or body.get("period"),
                    culture=body.get("cultureHint") or body.get("culture"),
                    social=body.get("socialConditionsHint") or body.get("social"),
                    enforce_silhouette_for_extras=body.get("enforceSilhouetteForExtras", True),
                    music=body.get("music", True),
                    model=body.get("model") or "veo-3.1-fast-generate-preview")
                return self._send(200 if r.get("ok") else 400, r)
            return self._send(404, {"error": "unknown scene endpoint"})
        if u.path.startswith("/api/lil/"):
            # LIL voiceprint (consent-gated, deterministic). audio_b64 = 16-bit PCM WAV.
            import qb_lil
            tail = u.path[len("/api/lil/"):]
            audio = body.get("audio_b64")
            if tail == "enroll":
                return self._send(200, qb_lil.enroll(body.get("name"), audio,
                    consent=bool(body.get("consent")), email=body.get("email"),
                    venue=body.get("venue"), event=body.get("event")))
            if tail == "match":
                return self._send(200, qb_lil.match(audio))
            if tail == "authenticate":
                return self._send(200, qb_lil.authenticate(body.get("name"), audio))
            if tail == "profiles":
                return self._send(200, qb_lil.list_profiles())
            if tail == "delete":
                return self._send(200, qb_lil.delete(body.get("name")))
            return self._send(404, {"error": "unknown lil endpoint"})
        if u.path == "/api/pil/analyze":
            # PIL paralinguistic estimate from audio (+ optional transcript).
            import qb_pil
            return self._send(200, qb_pil.analyze(body.get("audio_b64"), body.get("text")))
        if u.path == "/api/pil/interpret":
            import qb_pil
            text = (body.get("text") or "").strip()
            if not text:
                return self._send(400, {"error": "text required"})
            return self._send(200, qb_pil.interpret_query(text))
        if u.path == "/api/query/understand":
            # Deterministic query plan (entities/predicate/intent/scope/expansion/pragmatics).
            import qb_query
            text = (body.get("text") or "").strip()
            if not text:
                return self._send(400, {"error": "text required"})
            return self._send(200, qb_query.understand(text))
        if u.path == "/api/ontology":
            # Concept graph from the store (or supplied triples). type=path for a concept path.
            import qb_ontology
            tris = body.get("triples")
            g = qb_ontology.build([tuple(t) for t in tris]) if tris else qb_ontology.from_store(DATA_DIR, int(body.get("limit", 3000)))
            if body.get("from") and body.get("to"):
                return self._send(200, {"path": qb_ontology.concept_path(g, body["from"], body["to"]),
                                        "counts": g.get("counts", {})})
            return self._send(200, qb_ontology.public(g))
        if u.path == "/api/assess":
            # Generate assessment items from the store (or supplied triples).
            import qb_assess
            tris = body.get("triples")
            if tris:
                items = qb_assess.items_from_triples([tuple(t) for t in tris],
                                                     max_items=int(body.get("count", 20)))
            else:
                items = qb_assess.from_store(DATA_DIR, max_items=int(body.get("count", 20)),
                                             domain=body.get("domain"))
            return self._send(200, {"items": items, "count": len(items)})
        if u.path.startswith("/api/rights/"):
            import qb_rights
            tail = u.path[len("/api/rights/"):]
            if tail == "grant":
                return self._send(200, qb_rights.grant(body.get("resource"), body.get("territories"),
                    body.get("editions"), body.get("expires"), body.get("holder")))
            if tail == "revoke":
                return self._send(200, qb_rights.revoke(body.get("resource")))
            if tail == "check":
                return self._send(200, qb_rights.check(body.get("resource"),
                    body.get("territory", "*"), body.get("edition", "*")))
            if tail == "registry":
                return self._send(200, qb_rights.registry())
            return self._send(404, {"error": "unknown rights endpoint"})
        if u.path.startswith("/api/integrity/"):
            import qb_integrity
            tail = u.path[len("/api/integrity/"):]
            if tail == "mint":
                return self._send(200, qb_integrity.mint(body.get("kind", "seal"),
                    body.get("ref", ""), body.get("meta")))
            if tail == "seal":
                return self._send(200, qb_integrity.seal(body.get("text", ""), body.get("author", "anonymous")))
            if tail == "similarity":
                return self._send(200, qb_integrity.similarity(body.get("a", ""), body.get("b", "")))
            if tail == "proof":
                return self._send(200, qb_integrity.proof_package(body.get("seal_id", "")))
            if tail == "verify":
                return self._send(200, qb_integrity.verify_chain())
            return self._send(404, {"error": "unknown integrity endpoint"})
        if u.path == "/api/webhooks":
            # Minimal webhook registry (deployment/integration feature 177). Local, in-memory.
            act = (body.get("action") or "list").lower()
            global WEBHOOKS
            try: WEBHOOKS
            except NameError: WEBHOOKS = []
            if act == "register":
                WEBHOOKS.append({"event": body.get("event", "*"), "url": body.get("url", "")})
                return self._send(200, {"ok": True, "count": len(WEBHOOKS)})
            if act == "clear":
                WEBHOOKS = []
                return self._send(200, {"ok": True})
            return self._send(200, {"webhooks": WEBHOOKS})
        if u.path.startswith("/api/edu/"):
            import qb_education
            tail = u.path[len("/api/edu/"):]
            if tail == "lesson":
                return self._send(200, qb_education.generate_lesson(body.get("domain", "history"),
                    int(body.get("count", 5)), store_dir=DATA_DIR))
            if tail == "grade":
                return self._send(200, qb_education.grade_attempt(body.get("learner"),
                    body.get("domain", "history"), body.get("answers") or [],
                    class_id=body.get("class_id"), store_dir=DATA_DIR))
            if tail == "learner":
                return self._send(200, qb_education.learner_state(body.get("learner")))
            if tail == "class":
                return self._send(200, qb_education.class_analytics(body.get("class_id")))
            if tail == "study_guide":
                return self._send(200, qb_education.study_guide(body.get("domain", "history"), store_dir=DATA_DIR))
            return self._send(404, {"error": "unknown edu endpoint"})
        if u.path.startswith("/api/collab/"):
            import qb_collab
            tail = u.path[len("/api/collab/"):]
            if tail == "resource":
                return self._send(200, qb_collab.add_resource(body.get("title"), body.get("owner", "anonymous"),
                    body.get("body", ""), tenant=body.get("tenant")))
            if tail == "resources":
                return self._send(200, qb_collab.list_resources(tenant=body.get("tenant")))
            if tail == "annotate":
                return self._send(200, qb_collab.add_annotation(body.get("resource"), body.get("author", "anonymous"),
                    body.get("text", ""), anchor=body.get("anchor")))
            if tail == "annotations":
                return self._send(200, qb_collab.list_annotations(body.get("resource")))
            if tail == "post":
                return self._send(200, qb_collab.post_thread(body.get("resource"), body.get("author", "anonymous"),
                    body.get("text", ""), parent=body.get("parent")))
            if tail == "thread":
                return self._send(200, qb_collab.get_thread(body.get("root")))
            if tail == "activity":
                return self._send(200, qb_collab.activity(int(body.get("limit", 30))))
            return self._send(404, {"error": "unknown collab endpoint"})
        if u.path.startswith("/api/saas/"):
            import qb_saas
            tail = u.path[len("/api/saas/"):]
            if tail == "tenant":
                return self._send(200, qb_saas.create_tenant(body.get("name"), body.get("plan", "team"),
                    owner_email=body.get("owner_email")))
            if tail == "tenants":
                return self._send(200, qb_saas.list_tenants())
            if tail == "plan":
                return self._send(200, qb_saas.set_plan(body.get("tenant_id"), body.get("plan")))
            if tail == "user":
                return self._send(200, qb_saas.add_user(body.get("tenant_id"), body.get("email"), body.get("role", "reader")))
            if tail == "usage":
                return self._send(200, qb_saas.record_usage(body.get("tenant_id"), body.get("metric", "api"), int(body.get("n", 1))))
            if tail == "summary":
                return self._send(200, qb_saas.tenant_summary(body.get("tenant_id")))
            return self._send(404, {"error": "unknown saas endpoint"})
        if u.path == "/api/video/poll":
            # Poll a Veo operation; when done, download the MP4 SERVER-SIDE (key never reaches the
            # browser) and cache it under a random id served by GET /api/video/get.
            import qb_gemini, base64 as _b64, uuid as _uuid
            op = body.get("operation")
            r = qb_gemini.poll_operation(op)
            if r.get("done") and r.get("video_uri") and not r.get("error"):
                try:
                    data, mime = qb_gemini.download_video(r["video_uri"])
                    global VIDEO_CACHE
                    try: VIDEO_CACHE
                    except NameError: VIDEO_CACHE = {}
                    vid = _uuid.uuid4().hex[:16]
                    VIDEO_CACHE[vid] = (data, mime)
                    # keep the cache bounded
                    if len(VIDEO_CACHE) > 12:
                        for k in list(VIDEO_CACHE)[:-12]: VIDEO_CACHE.pop(k, None)
                    return self._send(200, {"done": True, "ready": True, "id": vid,
                                            "bytes": len(data), "mime": mime,
                                            "url": "/api/video/get?id=" + vid})
                except Exception as ex:
                    return self._send(200, {"done": True, "error": "download failed: %s" % ex})
            return self._send(200, r)
        if u.path == "/api/middleware/verify":
            import qb_middleware
            return self._send(200, qb_middleware.verify_claim(body.get("text", ""), store_dir=DATA_DIR))
        if u.path == "/api/middleware/guard":
            import qb_middleware
            return self._send(200, qb_middleware.guard(body.get("text", ""), store_dir=DATA_DIR))
        if u.path == "/api/language/teach":
            # One-click automation: start (or resume) the complete learner for a language —
            # vocabulary + pronunciation + translation — without the user wiring agents by hand.
            lang = (body.get("lang") or "es").lower()
            name = "Learn " + qb_language.LANG_NAMES.get(lang, lang)
            try:
                existing = next((a for a in AGENTS.snapshot().get("agents", [])
                                 if a.get("kind") == "lang_learn" and (a.get("target") or "").lower() == lang), None)
                if existing:
                    AGENTS.control(existing["id"], "resume")
                    aid = existing["id"]
                else:
                    a = AGENTS.create(name, "lang_learn", target=lang, interval=2)
                    aid = a["id"]
                    AGENTS.control(aid, "start")
                total = len(qb_language._corpus_words(lang))
                return self._send(200, {"ok": True, "agent_id": aid, "lang": lang,
                                        "language": qb_language.LANG_NAMES.get(lang, lang),
                                        "words_to_learn": total})
            except Exception as e:
                return self._send(500, {"error": "could not start learner: " + str(e)})
        if u.path == "/api/language/teach_all":
            # Start (or resume) the complete learner for EVERY non-English language at once.
            langs = [lg for lg in sorted(qb_language.LANG_NAMES) if lg != "en"]
            started = []
            try:
                snap = AGENTS.snapshot().get("agents", [])
                for lang in langs:
                    ex = next((a for a in snap if a.get("kind") == "lang_learn"
                               and (a.get("target") or "").lower() == lang), None)
                    if ex:
                        AGENTS.control(ex["id"], "resume"); aid = ex["id"]
                    else:
                        a = AGENTS.create("Learn " + qb_language.LANG_NAMES.get(lang, lang),
                                          "lang_learn", target=lang, interval=2)
                        aid = a["id"]; AGENTS.control(aid, "start")
                    started.append({"lang": lang, "language": qb_language.LANG_NAMES.get(lang, lang),
                                    "agent_id": aid, "words_to_learn": len(qb_language._corpus_words(lang))})
                return self._send(200, {"ok": True, "started": started,
                                        "message": "All languages are now learning automatically."})
            except Exception as e:
                return self._send(500, {"error": "could not start learners: " + str(e)})
        if u.path == "/api/language/go":
            # THE button: start one orchestrator that does English Phases 1-4 and every
            # language, one at a time, with no further operator input. Resumes if present.
            try:
                ex = next((a for a in AGENTS.snapshot().get("agents", [])
                           if a.get("kind") == "lang_pipeline"), None)
                if ex:
                    AGENTS.control(ex["id"], "resume"); aid = ex["id"]
                else:
                    a = AGENTS.create("Language pipeline — everything", "lang_pipeline", interval=1)
                    aid = a["id"]; AGENTS.control(aid, "start")
                return self._send(200, {"ok": True, "agent_id": aid,
                                        "message": "Running everything automatically: English Phases 1-4, then every language."})
            except Exception as e:
                return self._send(500, {"error": "could not start pipeline: " + str(e)})
        if u.path == "/api/language/run_all":
            # One-click automation of the whole English pipeline: Phase 1 (structure) →
            # Phase 2 (meaning) → Phase 3 (translation) → Phase 4 (speech). Each is a
            # deterministic agent; we start (or resume) all four. Idiot-proof: one button.
            plan = [("language", "English — Phase 1 (structure)"),
                    ("lang_semantic", "English — Phase 2 (meaning)"),
                    ("lang_multilingual", "English — Phase 3 (translation)"),
                    ("lang_speech", "English — Phase 4 (speech)")]
            started = []
            try:
                snap = AGENTS.snapshot().get("agents", [])
                for kind, name in plan:
                    ex = next((a for a in snap if a.get("kind") == kind), None)
                    if ex:
                        AGENTS.control(ex["id"], "resume"); started.append({"kind": kind, "id": ex["id"], "reused": True})
                    else:
                        a = AGENTS.create(name, kind, interval=2)
                        AGENTS.control(a["id"], "start"); started.append({"kind": kind, "id": a["id"], "reused": False})
                return self._send(200, {"ok": True, "started": started,
                                        "message": "All four English phases are running automatically."})
            except Exception as e:
                return self._send(500, {"error": "could not start English phases: " + str(e)})
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

    def _send_static(self, filename, ctype):
        try:
            with open(self._asset_path("", filename), "rb") as fh:
                body = fh.read()
        except OSError:
            return self._send(404, {"error": filename + " not found"})
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        # Shared design system (theme tokens + toggle) served to every page.
        if u.path == "/api/video/get":
            # Serve a cached, server-downloaded MP4 by id (no key exposed to the browser).
            vid = (urllib.parse.parse_qs(u.query).get("id", [""]) or [""])[0]
            try: cache = VIDEO_CACHE
            except NameError: cache = {}
            ent = cache.get(vid)
            if not ent:
                return self._send(404, {"error": "no such video"})
            data, mime = ent
            self.send_response(200)
            self.send_header("Content-Type", mime or "video/mp4")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try: self.wfile.write(data)
            except Exception: pass
            return
        if u.path == "/favicon.ico":
            # Tiny inline SVG favicon — silences the browser's automatic /favicon.ico 404.
            ico = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
                   b'<rect width="16" height="16" rx="3" fill="#0c7a5c"/>'
                   b'<text x="8" y="12" font-size="11" font-family="Georgia,serif" '
                   b'font-weight="700" fill="#fff" text-anchor="middle">Q</text></svg>')
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(ico)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            try:
                self.wfile.write(ico)
            except Exception:
                pass
            return
        if u.path == "/qb-theme.css":
            return self._send_static("qb-theme.css", "text/css; charset=utf-8")
        if u.path == "/qb-ui.js":
            return self._send_static("qb-ui.js", "application/javascript; charset=utf-8")
        if u.path in ("/", "/home", "/home.html"):
            return self._send_html(self._asset_path("QB_HOME_HTML", "home.html"))
        if u.path in ("/chat", "/chat.html"):
            return self._send_html(self._asset_path("QB_CHAT_HTML", "chat.html"))
        if u.path in ("/ingest", "/ingest.html", "/ingestion"):
            return self._send_html(self._asset_path("QB_INGEST_HTML", "ingest.html"))
        if u.path in ("/dashboard", "/dashboard.html", "/live"):
            return self._send_html(self._asset_path("QB_DASHBOARD_HTML", "dashboard.html"))
        if u.path in ("/console", "/console.html", "/dashboards"):
            return self._send_html(self._asset_path("QB_CONSOLE_HTML", "console.html"))
        if u.path in ("/language", "/language.html", "/lang"):
            return self._send_html(self._asset_path("QB_LANGUAGE_HTML", "language.html"))
        if u.path in ("/guide", "/guide.html", "/help", "/docs"):
            return self._send_html(self._asset_path("QB_GUIDE_HTML", "guide.html"))
        if u.path in ("/monitor", "/monitor.html", "/status"):
            return self._send_html(self._asset_path("QB_MONITOR_HTML", "monitor.html"))
        if u.path in ("/voice", "/voice.html"):
            return self._send_html(self._asset_path("QB_VOICE_HTML", "voice.html"))
        if u.path in ("/director", "/director.html", "/studio"):
            return self._send_html(self._asset_path("QB_DIRECTOR_HTML", "director.html"))
        if u.path in ("/reconstructor", "/reconstructor.html", "/replayer", "/scene"):
            return self._send_html(self._asset_path("QB_RECONSTRUCTOR_HTML", "reconstructor.html"))
        if u.path in ("/learn", "/learn.html", "/reader"):
            return self._send_html(self._asset_path("QB_LEARN_HTML", "learn.html"))
        if u.path in ("/educator", "/educator.html"):
            return self._send_html(self._asset_path("QB_EDUCATOR_HTML", "educator.html"))
        if u.path in ("/collab", "/collab.html", "/workspace"):
            return self._send_html(self._asset_path("QB_COLLAB_HTML", "collab.html"))
        if u.path in ("/admin", "/admin.html", "/tenants"):
            return self._send_html(self._asset_path("QB_ADMIN_HTML", "admin.html"))
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
                elif u.path == "/api/monitor":
                    import platform as _pf
                    m = st.manifest
                    try: disk = st.compressed_bytes()
                    except Exception: disk = 0
                    domains = {k[len("facts_dom_"):]: v for k, v in m.items()
                               if k.startswith("facts_dom_")}
                    langs = {}
                    prefmap = {lg: ('english word "' if lg == "en"
                                    else qb_language.LANG_NAMES.get(lg, lg).lower() + ' word "')
                               for lg in qb_language.speakable_languages()}
                    indexed = False
                    if not st.no_fql:
                        for lg, pref in prefmap.items():
                            try:
                                voc = st.db.execute("SELECT COUNT(DISTINCT subject) FROM nuc WHERE predicate='attested_in' AND subject LIKE ?", (pref + "%",)).fetchone()[0]
                                pron = st.db.execute("SELECT COUNT(*) FROM nuc WHERE predicate='pronunciation' AND subject LIKE ?", (pref + "%",)).fetchone()[0]
                                indexed = True
                            except Exception:
                                voc = pron = 0
                            if voc or pron:
                                langs[lg] = {"language": qb_language.LANG_NAMES.get(lg, lg),
                                             "vocab": voc, "pronounced": pron}
                    # Fallback (no index, or index empty while blocks exist): ONE pass over the
                    # blocks tallies every language — so the monitor never shows 0 when it isn't.
                    if (not indexed or not langs) and st.manifest.get("blocks", 0):
                        tally = {lg: {"subs": set(), "pron": 0} for lg in prefmap}
                        try:
                            for rec in st.iter_all():
                                n = rec.get("nucleus") or {}
                                s = n.get("subject", ""); p = n.get("predicate", "")
                                for lg, pref in prefmap.items():
                                    if s.startswith(pref):
                                        if p == "attested_in": tally[lg]["subs"].add(s)
                                        elif p == "pronunciation": tally[lg]["pron"] += 1
                                        break
                        except Exception:
                            pass
                        for lg, t in tally.items():
                            if t["subs"] or t["pron"]:
                                langs[lg] = {"language": qb_language.LANG_NAMES.get(lg, lg),
                                             "vocab": len(t["subs"]), "pronounced": t["pron"]}
                    provs = AGENTS.providers or []
                    active = next((p for p in provs if p.get("kind") == "anthropic"
                                   or "anthropic" in (p.get("base_url") or "")), None) or (provs[0] if provs else None)
                    tts = qb_language.tts_status()
                    self._send(200, {
                        "build": BUILD, "date": BUILD_DATE,
                        "access": {"urls": access_urls(), "secure": False,
                                   "ips": _local_ipv4s(),
                                   "beacon": True, "beacon_port": QB_BEACON_PORT},
                        "uptime_s": round(time.time() - START_TIME, 1),
                        "host": {"platform": _pf.system(), "release": _pf.release(),
                                 "python": _pf.python_version(), "cpus": os.cpu_count()},
                        "store": {"data_dir": DATA_DIR, "facts": m.get("facts", 0),
                                  "blocks": m.get("blocks", 0), "duplicates": m.get("duplicates", 0),
                                  "disk_mb": round(disk / 1e6, 2), "last_verify": m.get("last_verify"),
                                  "fql_index": not st.no_fql, "domains": domains},
                        "collection": {**{k: v for k, v in HARVEST.items() if k != "samples"},
                                       "meter": harvest_meter(), "per_fact_us": PERF["per_fact_create_us"]},
                        "agents": AGENTS.snapshot().get("agents", []),
                        "subsystems": {
                            "keepawake": qb_keepawake.status(),
                            "mirror": MIRROR.status(),
                            "llm": {"configured": bool(active),
                                    "usable": bool(active and qb_chat.provider_usable(active)),
                                    "provider": (active or {}).get("name"),
                                    "model": (active or {}).get("model"),
                                    "have_llm": qb_chat._have_llm()},
                            "voice": {"engine": tts.get("engine"), "available": tts.get("available"),
                                      "espeak_ng": bool(qb_language._espeak_exe()),
                                      "speakable": qb_language.speakable_languages()},
                            "selftest": globals().get("LAST_SELFTEST") or {"note": "run /api/selftest"},
                            "remote": {"secure": False, "bind": BIND},
                        },
                        "languages": langs,
                    })
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
                elif u.path == "/api/edition":
                    import qb_editions
                    self._send(200, qb_editions.info())
                elif u.path == "/api/embodiments":
                    import qb_embodiment
                    self._send(200, qb_embodiment.info())
                elif u.path == "/api/features":
                    import qb_features
                    self._send(200, qb_features.catalog())
                elif u.path == "/api/ingest/strategy":
                    import qb_ingest_strategy
                    self._send(200, qb_ingest_strategy.status(DATA_DIR))
                elif u.path == "/api/system":
                    # Two-system overview for the home page: Ingestion + Query, edition, embodiments.
                    import qb_editions, qb_embodiment, qb_ingest_strategy
                    ed = qb_editions.info()
                    enabled = set(ed["enabled"])
                    def grp(keys):
                        return [{"key": k, "label": qb_editions.FEATURES[k], "enabled": k in enabled}
                                for k in keys if k in qb_editions.FEATURES]
                    self._send(200, {
                        "build": BUILD, "edition": ed["edition"], "edition_name": ed["name"],
                        "systems": {
                            "ingestion": {"title": "Ingestion", "subtitle": "Build the knowledge base, staged and automated",
                                "features": grp([k for k in qb_editions.FEATURES if k.startswith("ingest.")]),
                                "strategy": qb_ingest_strategy.status(DATA_DIR)},
                            "query": {"title": "Query", "subtitle": "Ask, translate, speak, direct — grounded or UNKNOWN",
                                "features": grp([k for k in qb_editions.FEATURES if k.startswith("query.")])},
                        },
                        "embodiments": qb_embodiment.matrix()})
                elif u.path == "/api/language/diag":
                    # One-click diagnostics for "the word count never increases" — reports the
                    # vocabulary source, the store/index state, and a live write+reread test.
                    lang = (q.get("lang") or "es").lower()
                    d = qb_language.diagnostics(DATA_DIR, lang)
                    d["build"] = BUILD
                    try:
                        d["agents"] = [{"name": a.get("name"), "kind": a.get("kind"),
                                        "target": a.get("target"), "status": a.get("status"),
                                        "cycles": a.get("cycles"), "facts": a.get("facts"),
                                        "phase": a.get("phase"), "error": a.get("error"),
                                        "learned": len(a.get("_learned") or [])}
                                       for a in AGENTS.snapshot().get("agents", [])
                                       if a.get("kind") == "lang_learn"]
                    except Exception as e:
                        d["agents"] = [{"error": repr(e)}]
                    self._send(200, d)
                elif u.path == "/api/language/activity":
                    # Live feed of words being learned right now (word · IPA · translation · rate).
                    since = float(q.get("since", 0) or 0)
                    limit = max(1, min(200, int(q.get("limit", 60) or 60)))
                    act = qb_language.recent_activity(limit, since)
                    pipe = next((a for a in AGENTS.snapshot().get("agents", [])
                                 if a.get("kind") == "lang_pipeline"), None)
                    act["pipeline"] = ({"status": pipe.get("status"), "phase": pipe.get("phase"),
                                        "facts": pipe.get("facts")} if pipe else None)
                    self._send(200, act)
                elif u.path == "/api/language/espeak":
                    # Troubleshooting: espeak-ng status at any time (found/path/version/self-test/log).
                    self._send(200, qb_language.espeak_status())
                elif u.path == "/api/language/qc":
                    # Permanent pronunciation/speech quality control battery (per language).
                    only = q.get("lang")
                    self._send(200, qb_language.pronunciation_qc([only.lower()] if only else None))
                elif u.path == "/api/language/tts_providers":
                    # Which voice engines are available: open-source (offline) + any configured
                    # cloud providers (Google / ElevenLabs). NEVER returns the keys themselves.
                    self._send(200, qb_language.tts_status())
                elif u.path == "/api/language/readiness":
                    # Per-language readiness matrix for the UI (words, translation, speech).
                    self._send(200, qb_language.language_readiness(DATA_DIR))
                elif u.path == "/api/language/detect":
                    self._send(200, qb_language.detect_language(q.get("text", "")))
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
                elif u.path == "/api/language/words":
                    # Live learning detail: every learned word with its phonic elements
                    # (IPA, syllables, stress, source) + a phoneme inventory. For the monitor.
                    lang = (q.get("lang") or "en").lower()
                    prefix = ('english word "' if lang == "en"
                              else qb_language.LANG_NAMES.get(lang, lang).lower() + ' word "')
                    words = {}
                    def _absorb(s, p, o):
                        w = s[len(prefix):-1] if (s.startswith(prefix) and s.endswith('"')) else s
                        d = words.setdefault(w, {"word": w})
                        if p == "pronunciation": d["ipa"] = o
                        elif p == "syllable_count": d["syllables"] = o
                        elif p == "stress_syllable": d["stress"] = o
                        elif p == "attested_in": d["attested"] = True
                        elif p == "means": d["means"] = str(o)[:140]
                        elif p.startswith("translation_"): d.setdefault("translations", []).append(o)
                    rows = []
                    if not st.no_fql:
                        try:
                            rows = st.db.execute(
                                "SELECT subject, predicate, object, trust FROM nuc WHERE subject LIKE ? LIMIT 60000",
                                (prefix + "%",)).fetchall()
                        except Exception:
                            rows = []
                    if rows:
                        for s, p, o, t in rows:
                            _absorb(s, p, o)
                    elif st.manifest.get("blocks", 0):
                        # No index (or it returned nothing) — scan the blocks so the detail and
                        # the count still reflect what was actually learned. Fix for stuck count.
                        for rec in st.iter_all():
                            n = rec.get("nucleus") or {}
                            s = n.get("subject", "")
                            if s.startswith(prefix):
                                _absorb(s, n.get("predicate", ""), n.get("object", ""))
                    items = sorted(words.values(), key=lambda x: x["word"])
                    inv = {}
                    for it in items:
                        for ch in (it.get("ipa") or "").strip("/"):
                            if ch not in " ˈˌː.":
                                inv[ch] = inv.get(ch, 0) + 1
                    phon = sorted(({"ipa": k, "count": v} for k, v in inv.items()), key=lambda x: -x["count"])
                    self._send(200, {"lang": lang, "language": qb_language.LANG_NAMES.get(lang, lang),
                                     "count": len(items), "pronounced": sum(1 for i in items if i.get("ipa")),
                                     "phonemes": phon, "words": items[:3000]})
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
                    self._send(200, {"build": BUILD, "date": BUILD_DATE,
                                     "features": ["language-lab", "phased-agents", "build-english-first",
                                                  "per-domain-counts", "self-heal", "store-health",
                                                  "provider-live-test", "phase2-deterministic-dictionary-store", "llm-lockout-enforced", "hypothesis-agent", "simulation-agent", "reasoning-agent", "gate-multivalued", "planner-agent", "phase3-multilingual-delta", "launcher-frees-port", "phase4-speech", "auto-discovery", "no-security-open", "dictionary-translation", "one-click-teach", "index-free-counts"]})
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
    # Auto-discovery: broadcast this station on the local network so your other
    # device finds it with `python qb_api.py discover` — no URL typing, no static IP.
    try:
        _start_beacon()
        print(f"  AUTO-DISCOVERY: broadcasting on your network (UDP {QB_BEACON_PORT}) — "
              f"on your OTHER device run:  python qb_api.py discover", flush=True)
    except Exception as e:
        print(f"  auto-discovery beacon could not start: {e}", flush=True)
    print("=" * 60, flush=True)
    print(f"  QueryBook  BUILD {BUILD} · {BUILD_DATE}  (Phase 4 multilingual speech: en/es/fr/de/pt/it/sv/nl)", flush=True)
    print("=" * 60, flush=True)
    qb_log.log("info", "server", "QueryBook BUILD " + BUILD + " started on http://" + BIND)
    llm = "on" if qb_chat._have_llm() else "off (deterministic fallback)"
    _store_health_banner()
    print(f"qb_api serving {os.path.abspath(DATA_DIR)} on http://{BIND}", flush=True)
    # Full, ready-to-click monitor links for every address this machine has.
    print("  " + "-" * 56, flush=True)
    print("  OPEN THE MONITOR — click one of these (full links, no typing):", flush=True)
    for u in access_urls():
        print("      " + u, flush=True)
    print("  From your OTHER device, use one of the http://<ip>:... links above,", flush=True)
    print("  or just run  python qb_api.py discover  there to find this station.", flush=True)
    print("  " + "-" * 56, flush=True)
    print(f"  Dashboard: http://{BIND}/dashboard   ·   Language Lab: http://{BIND}/language", flush=True)
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

def _cli_discover():
    """Run on your DEV device to find the learning station automatically."""
    print("Searching your network for a QueryBook station (listening ~6s)…", flush=True)
    res = discover_stations(timeout=6.0)
    if res.get("error"):
        print("  Could not listen for stations: " + str(res["error"]), flush=True)
        print("  (Another QueryBook on THIS device may hold the discovery port — that's fine,", flush=True)
        print("   run discover from a device that is NOT also running the station.)", flush=True)
        return
    stations = res.get("stations", [])
    if not stations:
        print("  No station found. Make sure the station is running (START-WINDOWS.bat or", flush=True)
        print("  START-MAC.command) and that both devices are on the SAME network.", flush=True)
        return
    print("=" * 60, flush=True)
    print(f"  Found {len(stations)} station(s). Open one of these links:", flush=True)
    print("=" * 60, flush=True)
    for s in stations:
        print(f"  • {s.get('name','station')}  (build {s.get('build','?')})", flush=True)
        for u in s.get("reachable_urls", []):
            print("      " + u, flush=True)
    print("=" * 60, flush=True)


def _cli_diag():
    """Print full language-learning diagnostics to the terminal (copy/paste to send back)."""
    import sys, json as _j
    lang = sys.argv[2] if len(sys.argv) > 2 else "es"
    print("Running QueryBook language diagnostics for '%s' (store: %s)…\n" % (lang, DATA_DIR), flush=True)
    d = qb_language.diagnostics(DATA_DIR, lang)
    d["build"] = BUILD
    print("=" * 64)
    print("  PROBLEMS FOUND:" if not d.get("ok") else "  STATUS: OK")
    for pr in d.get("problems", []):
        print("   • " + pr)
    print("=" * 64)
    print(_j.dumps(d, indent=2, ensure_ascii=False))
    print("\n(Copy everything above and send it back.)", flush=True)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] in ("discover", "find", "--discover"):
        _cli_discover()
    elif len(sys.argv) > 1 and sys.argv[1] in ("diag", "diagnose", "--diag"):
        _cli_diag()
    else:
        main()
