#!/usr/bin/env python3
"""
qb_agents.py — background harvesting agents for QueryBook (stdlib + optional LLM).

An agent is a saved job that harvests on its own schedule (24x7) into the store:
  * kind "deterministic": generates rule-based facts (math/science), growing each cycle.
  * kind "web": politely crawls its seed domains, extracting Fact Units, on a repeating
    interval. Optional LLM extraction uses whatever provider the user configured
    (Anthropic, any OpenAI-compatible API, or a local server URL).

State (agents + LLM providers) is saved to <store>/agents.json so it survives restarts.
Runtime control: start / pause / stop / delete. Everything is thread-based; no external deps.
"""
import json, os, time, threading, uuid

import ufcs_store
try:
    import qb_keepawake
except Exception:
    qb_keepawake = None
try:
    import qb_log
except Exception:
    qb_log = None

def _ev(level, source, msg, **kw):
    if qb_log:
        try: qb_log.log(level, source, msg, **kw)
        except Exception: pass

# ---------------------------------------------------------------------------
# Grounded agent roles. QueryBook agents are the GROUNDED version of each LLM
# agent type: every role inherits cite-or-refuse, halt-on-ambiguity, and
# reproducibility from the engine. "built" roles run today; "roadmap" roles are
# specified (LEL / reasoning / hypothesis / NLPL) and REFUSE rather than
# fabricate until their engines exist. See the QueryBook Agent Architecture doc.
# ---------------------------------------------------------------------------
ROLES = {
    "deterministic": {"title": "Domain harvester (domain-specific)", "status": "built",
                      "desc": "Per-domain rule-based fact generation, growing the store each cycle."},
    "web":           {"title": "Web harvester", "status": "built",
                      "desc": "Politely crawls seed domains and extracts Fact Units (optional LLM extractor)."},
    "grounded_qa":   {"title": "Grounded Q&A (reactive / conversational / domain answer)", "status": "built",
                      "desc": "Runs the grounded pipeline on a saved question each cycle: cited answer, verdict, refuses on unknown."},
    "watch":         {"title": "Watch / pondering-over-time (Continuous Query, lite)", "status": "built",
                      "desc": "Re-answers a standing question on each cycle and records when the verdict or answer CHANGES as new facts arrive."},
    "reasoning":     {"title": "Gated reasoning agent", "status": "roadmap",
                      "desc": "Deduction asserts; induction/abduction propose. Requires the gated reasoning engine (spec-only)."},
    "hypothesis":    {"title": "Hypothesis / creative agent (LLM-proposed, store-verified)", "status": "built",
                      "desc": "An LLM PROPOSES candidate facts; each is verified against the deterministic store (corroborated / contradicted / open) and stored isolated in a 'hypothesis' domain at low trust. Non-asserting: nothing the LLM proposes becomes a fact. Needs an LLM provider."},
    "simulation":    {"title": "Simulation agent (LLM-projected, store-verified)", "status": "built",
                      "desc": "An LLM projects plausible CONSEQUENCES of a scenario; each is verified against the deterministic store (corroborated / contradicted / open) and stored isolated in a 'simulation' domain at low trust. Non-asserting. Needs an LLM provider."},
    "planner":       {"title": "NLPL planner (task/goal-oriented)", "status": "roadmap",
                      "desc": "Decomposes an instruction into operational intents; halts on ambiguity. Requires the NLPL engine (spec-only)."},
    # ---- Language Lab phase agents ----
    "language":      {"title": "Language builder — Phase 1 (SLPL / structural)", "status": "built",
                      "desc": "Learns English STRUCTURE from a bundled corpus (or your material) each cycle, driving the four Transition-Gate thresholds until Phase 1 completes."},
    "lang_semantic": {"title": "Language Phase 2 — semantic grounding (dictionary + store)", "status": "built",
                      "desc": "Grounds Phase-1 words to auditable meanings: a bundled public-domain dictionary (Webster's 1913) plus self-grounding against the verified store. Fully deterministic, no internet, NO LLM. Runs to completion on its own."},
    "lang_multilingual": {"title": "Language Phase 3 — multilingual delta", "status": "roadmap",
                      "desc": "Acquire further languages by their delta over English. Requires the Delta Acquisition engine (spec-only)."},
    "lang_speech":   {"title": "Language Phase 4 — speech output", "status": "roadmap",
                      "desc": "Render meaning to speech via the seven-stage pipeline. Requires the neural speech engine (spec-only)."},
}
_ROADMAP_ENGINE = {"reasoning": "gated reasoning", "planner": "NLPL",
                   "lang_multilingual": "Delta Acquisition", "lang_speech": "neural speech"}


class AgentManager:
    def __init__(self, store_dir):
        self.store_dir = store_dir
        self.path = os.path.join(store_dir, "agents.json")
        self.lock = threading.Lock()
        self.agents = {}        # id -> dict
        self.providers = []     # [{name, kind, base_url, model, key_env}]
        self.threads = {}       # id -> Thread
        self.stop = {}          # id -> bool
        self._sup = None        # self-heal supervisor thread
        self._load()

    MAX_RESTARTS = 6            # per agent before it stays errored for a human to look at

    # ---------- persistence ----------
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            self.agents = {a["id"]: a for a in d.get("agents", [])}
            self.providers = d.get("providers", [])
            for a in self.agents.values():
                if a.get("status") == "running":
                    a["status"] = "stopped"   # nothing runs until explicitly started
        except Exception:
            pass

    def _save(self):
        try:
            os.makedirs(self.store_dir, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"agents": list(self.agents.values()), "providers": self.providers}, f, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    # ---------- CRUD ----------
    def create(self, name, kind, target="", interval=10, chunk=50000, provider=None, extractor="structured"):
        name = name or ""
        target = target or ""
        with self.lock:
            # Idempotent: repeated "Start all"/"Start agent" clicks must NOT pile up
            # duplicate jobs. If an agent with the same (kind, target, name) already
            # exists, reuse it — clear any stale error so it can start cleanly.
            for ex in self.agents.values():
                if ex.get("kind") == kind and (ex.get("target") or "") == target and (ex.get("name") or "") == name:
                    if ex.get("status") in ("error", "roadmap"):
                        ex["status"] = "stopped"; ex["error"] = None
                    self._save()
                    return ex
            aid = uuid.uuid4().hex[:8]
            a = {"id": aid, "name": name or ("agent-" + aid), "kind": kind, "target": target,
                 "interval": max(1, int(interval)), "chunk": max(1, int(chunk)),
                 "provider": provider, "extractor": extractor,
                 "status": "stopped", "facts": 0, "cycles": 0, "last_run": None,
                 "error": None, "created": time.time(), "auto_restart": True, "retries": 0}
            self.agents[aid] = a
            self._save()
        return a

    def prune(self):
        """Remove agents that are finished/errored and not currently running.
        One click clears the mess left by earlier crashes or duplicate creates."""
        removed = 0
        with self.lock:
            for aid in list(self.agents.keys()):
                a = self.agents[aid]
                alive = bool(self.threads.get(aid) and self.threads[aid].is_alive())
                if not alive and a.get("status") in ("stopped", "error", "roadmap"):
                    self.stop[aid] = True
                    self.agents.pop(aid, None)
                    removed += 1
            self._save()
        return removed

    def control(self, aid, action):
        if action == "prune":
            return {"removed": self.prune()}
        a = self.agents.get(aid)
        if not a and action != "delete":
            return False
        if action == "start":
            self._start(a)
        elif action == "pause":
            a["status"] = "paused"; self._save()
        elif action == "stop":
            self.stop[aid] = True; a["status"] = "stopped"; self._save()
        elif action == "resume":
            self._start(a)
        elif action == "delete":
            self.stop[aid] = True
            with self.lock:
                self.agents.pop(aid, None); self._save()
        return True

    def set_providers(self, providers):
        with self.lock:
            # Preserve a previously-stored key when the incoming provider omits it — the UI
            # never receives the key back (redacted in snapshot), so a plain re-save of the
            # list must NOT wipe the stored key.
            prev = {p.get("name"): p for p in (self.providers or [])}
            FIELDS = ("name", "kind", "base_url", "model", "key_env", "key")
            merged = []
            for raw in (providers or []):
                p = {k: raw[k] for k in FIELDS if k in raw}
                if not p.get("key"):
                    old = prev.get(p.get("name"))
                    if old and old.get("key"):
                        p["key"] = old["key"]      # keep the stored secret across redacted round-trips
                merged.append(p)
            self.providers = merged
            self._save()
            _ev("info", "providers", "saved %d provider(s): %s" % (
                len(merged), ", ".join("%s%s" % (p.get("name"), " (key)" if (p.get("key") or p.get("key_env")) else "")
                                        for p in merged)))

    def roles(self):
        """The grounded agent-role catalog (for the dashboard / API)."""
        return ROLES

    def snapshot(self):
        out = []
        for a in self.agents.values():
            d = {k: v for k, v in a.items() if not k.startswith("_")}
            d["alive"] = bool(self.threads.get(a["id"]) and self.threads[a["id"]].is_alive())
            out.append(d)
        out.sort(key=lambda x: x.get("created", 0))
        # Redact keys: never echo a stored secret back to the browser. Report has_key/usable.
        provs = []
        for p in self.providers:
            q = {k: v for k, v in p.items() if k != "key"}
            q["has_key"] = bool(p.get("key"))
            q["usable"] = bool(p.get("key") or (p.get("key_env") and os.environ.get(p.get("key_env")))
                               or "localhost" in (p.get("base_url") or "") or "127.0.0.1" in (p.get("base_url") or ""))
            provs.append(q)
        return {"agents": out, "providers": provs}

    # ---------- runtime ----------
    def _start(self, a):
        aid = a["id"]
        if self.threads.get(aid) and self.threads[aid].is_alive():
            a["status"] = "running"; self._save(); return
        self.stop[aid] = False
        a["status"] = "running"; a["error"] = None
        t = threading.Thread(target=self._loop, args=(aid,), daemon=True)
        self.threads[aid] = t; t.start()
        _ev("info", "agent:" + a.get("name", aid), "started (%s)" % a.get("kind"))
        self._save()

    # ---------- self-heal supervisor ----------
    def start_supervisor(self, interval=15):
        """Background watchdog: auto-restart agents that errored transiently, with an
        exponential backoff and a bounded retry budget. Roadmap agents (which refuse on
        purpose) and cleanly stopped agents are left alone."""
        if self._sup and self._sup.is_alive():
            return
        def loop():
            while True:
                try:
                    self._heal_once()
                except Exception:
                    pass
                time.sleep(interval)
        self._sup = threading.Thread(target=loop, daemon=True)
        self._sup.start()

    def _heal_once(self):
        now = time.time()
        for aid, a in list(self.agents.items()):
            if a.get("status") != "error" or not a.get("auto_restart", True):
                continue
            if a.get("kind") in _ROADMAP_ENGINE:   # these refuse by design — never "heal"
                continue
            retries = int(a.get("retries", 0))
            if retries >= self.MAX_RESTARTS:
                continue
            backoff = min(120, 2 ** retries)        # 1,2,4,…,120s
            if now - float(a.get("error_at", 0)) < backoff:
                continue
            a["retries"] = retries + 1
            a["error"] = None
            a["heal_note"] = "auto-restarted (attempt %d/%d) after: %s" % (
                a["retries"], self.MAX_RESTARTS, str(a.get("_last_err", ""))[:120])
            _ev("warn", "self-heal", "restarting '%s' (attempt %d/%d)" % (a.get("name"), a["retries"], self.MAX_RESTARTS))
            self._start(a)

    def _provider_for(self, name):
        for p in self.providers:
            if p.get("name") == name:
                return p
        return None

    def _best_provider(self, prefer=None):
        """Pick a usable LLM provider: a named one, else an Anthropic one, else the first."""
        provs = self.providers or []
        if prefer:
            p = self._provider_for(prefer)
            if p: return p
        for p in provs:
            if p.get("kind") == "anthropic" or "anthropic" in (p.get("base_url") or ""):
                return p
        return provs[0] if provs else None

    def _loop(self, aid):
        if qb_keepawake:                       # keep the PC awake while this agent runs
            qb_keepawake.acquire("agent:" + aid)
        try:
            self._run_loop(aid)
        finally:
            if qb_keepawake:
                qb_keepawake.release("agent:" + aid)

    def _run_loop(self, aid):
        while not self.stop.get(aid):
            a = self.agents.get(aid)
            if not a:
                break
            if a["status"] == "paused":
                time.sleep(1); continue
            if a["status"] != "running":
                break
            try:
                if a["kind"] == "deterministic":
                    # RESUMING per-domain harvest adds NEW facts every cycle. chunk<=0 = 24x7.
                    # The agent's target names the domain (mathematics/geometry/arithmetic); each
                    # domain agent runs its own logic in parallel = the throughput multiplier.
                    dom = (a.get("target") or "mathematics").strip().lower()
                    if dom not in ufcs_store.DOMAIN_GEN:
                        dom = "mathematics"
                    stopf = lambda: (self.stop.get(aid) or
                                     self.agents.get(aid, {}).get("status") != "running")
                    total = ufcs_store.harvest_into(self.store_dir, a["chunk"], "gzip", 1024,
                                                    should_stop=stopf, domain=dom, verify=False)
                    # Show the facts THIS agent's domain has contributed, not the store total.
                    a["facts"] = ufcs_store.manifest_value(self.store_dir, "facts_dom_" + dom, total)
                    a["store_total"] = total
                elif a["kind"] == "web":
                    import qb_web_harvest as web
                    st = ufcs_store.UFCSStore(self.store_dir)
                    try:
                        seeds = [s.strip() for s in str(a["target"]).replace("\n", ",").split(",") if s.strip()]
                        prov = self._provider_for(a.get("provider"))
                        h = web.Harvester(st, seeds, 1.0, a.get("extractor", "structured"),
                                          (prov or {}).get("model", "claude-haiku-4-5"))
                        h.provider = prov      # web harvester uses this if it supports it
                        pages = min(max(int(a["chunk"]), 1), 300)
                        h.run(seeds, pages)
                        a["facts"] = a.get("facts", 0) + getattr(h, "stored", 0)
                    finally:
                        st.close()
                elif a["kind"] == "language":
                    # Phase 1: each cycle ingests the next starter-corpus chunk (or the
                    # agent's own target material) to advance English structural learning
                    # toward the Transition Gate. Built — this is what "finish English" runs.
                    import qb_language as L
                    idx = int(a.get("_chunk", 0))
                    tgt = (a.get("target") or "").strip()
                    if tgt.startswith("http"):
                        res = L.learn(self.store_dir, url=tgt, source="Phase 1 · " + tgt)
                    elif tgt:
                        res = L.learn(self.store_dir, text=tgt, source="Phase 1 · custom corpus")
                    else:
                        res = L.learn(self.store_dir, text=L.corpus_chunk(idx),
                                      source="Phase 1 · starter corpus #%d" % (idx % len(L.STARTER_CORPUS)))
                    a["_chunk"] = idx + 1
                    g = res.get("gate", {}) if isinstance(res, dict) else {}
                    a["facts"] = ufcs_store.manifest_value(self.store_dir, "facts_dom_language", 0)
                    a["gate_progress"] = g.get("progress")
                    a["gate_ready"] = g.get("ready")
                    a["gate_opened"] = g.get("opened")
                    if g.get("opened"):
                        # Phase 1 is finished — stop cycling (re-ingesting the same corpus adds
                        # nothing once the gate is open). Terminal "complete" state, not an error;
                        # the self-heal supervisor leaves it alone. Restart it to feed new material.
                        a["cycles"] = a.get("cycles", 0) + 1
                        a["last_run"] = time.time(); a["error"] = None; a["retries"] = 0
                        a["phase"] = "Phase 1 COMPLETE — Transition Gate OPEN"
                        a["status"] = "complete"
                        _ev("ok", "agent:" + a["name"], "Phase 1 COMPLETE — Transition Gate OPEN")
                        self._save(); break
                    a["phase"] = "Phase 1 — %.0f%% to gate" % (g.get("progress") or 0)
                elif a["kind"] in ("grounded_qa", "watch"):
                    # GROUNDED roles: run the cite-or-refuse pipeline on a saved question.
                    # Adds no facts; records the verdict/answer/citations. "watch" also
                    # flags when the answer changes over time (offline pondering, lite).
                    import qb_chat
                    q = (a.get("target") or "").strip()
                    if not q:
                        a["error"] = "this agent needs a question in 'target'"; a["status"] = "error"; self._save(); break
                    st = ufcs_store.UFCSStore(self.store_dir)
                    try:
                        res = qb_chat.answer(st, q, 0.5, 8)
                    finally:
                        st.close()
                    prev = a.get("last_verdict")
                    a["last_verdict"] = res.get("verdict")
                    a["last_answer"] = (res.get("answer") or "")[:2000]
                    a["citations"] = len(res.get("citations", []))
                    a["unsupported"] = res.get("unsupported_flags", [])
                    a["grounded"] = res.get("grounded", False)
                    if a["kind"] == "watch":
                        changed = (prev is not None and prev != a["last_verdict"]) or \
                                  (a.get("_prev_answer") is not None and a["_prev_answer"] != a["last_answer"])
                        a["_prev_answer"] = a["last_answer"]
                        if changed:
                            a["changes"] = a.get("changes", 0) + 1
                            a["last_change"] = time.time()
                elif a["kind"] == "lang_semantic":
                    # Phase 2 (DETERMINISTIC): ground Phase-1 words to meanings from sources
                    # QueryBook can point to — a bundled PUBLIC-DOMAIN dictionary + self-grounding
                    # against the verified store. NO LLM, no network, no provider, no blocking.
                    # Every meaning carries an auditable source; runs to completion on its own.
                    import qb_language as L
                    done = set(a.get("_grounded") or [])
                    vocab = L.learned_words(self.store_dir, 400)
                    if not vocab:
                        a["status"] = "blocked"
                        a["error"] = ("No Phase-1 vocabulary yet — run Phase 1 (Build English first) "
                                      "until the engine has learned words, then start Phase 2.")
                        _ev("blocked", "agent:" + a["name"], a["error"]); self._save(); break
                    batch = [w for w in vocab if w not in done][:40]
                    if not batch:
                        cov = L.grounding_status(self.store_dir)
                        a["status"] = "complete"
                        a["phase"] = ("Phase 2 complete — %d words defined (dictionary), %d store-links"
                                      % (cov["defined"], cov["store_links"]))
                        _ev("ok", "agent:" + a["name"], a["phase"]); self._save(); break
                    res = L.ground_words(self.store_dir, batch, use_dictionary=True, use_store=True)
                    for w in batch:
                        done.add(w)
                    a["_grounded"] = sorted(done)
                    a["facts"] = a.get("facts", 0) + res["facts_added"]
                    cov = L.grounding_status(self.store_dir)
                    a["phase"] = ("Phase 2 (dictionary + store) — %d/%d words grounded, %d defined"
                                  % (len(done), len(vocab), cov["defined"]))
                    a["last_grounded"] = [g["word"] for g in res["grounded"]][:12]
                    a["error"] = None
                    _ev("ok", "agent:" + a["name"], "grounded %d words (+%d facts) from dictionary+store"
                        % (res["words_grounded"], res["facts_added"]))
                elif a["kind"] == "hypothesis":
                    # LLM-backed HYPOTHESIS agent — a PERMITTED, strictly non-asserting role.
                    # The LLM only PROPOSES candidate facts; each candidate is then VERIFIED
                    # against the deterministic store and stored isolated in a 'hypothesis'
                    # domain at low trust (< the 0.5 assertion threshold), so nothing the LLM
                    # proposes is ever asserted as a fact. This is exactly the sanctioned use:
                    # an LLM may help QueryBook *wonder*, never decide what is true.
                    import qb_chat, json as _json, re as _re
                    prov = self._best_provider(a.get("provider"))
                    if not (qb_chat.provider_usable(prov) or qb_chat._sdk_available()):
                        a["status"] = "blocked"
                        a["error"] = ("Hypothesis agent needs an LLM provider (this is a permitted, "
                                      "non-asserting role). Open LLM Providers, paste your API key, press "
                                      "Test, then start. Nothing the LLM proposes becomes a fact without "
                                      "independent verification against the store.")
                        _ev("blocked", "agent:" + a["name"], a["error"]); self._save(); break
                    # gather context: verified facts (seeded by target subject, else a random sample)
                    st = ufcs_store.UFCSStore(self.store_dir)
                    try:
                        seed = (a.get("target") or "").strip()
                        rows = []
                        if not st.no_fql:
                            if seed:
                                rows, _ = st.search(seed, 0.5, 12)
                            if not rows:
                                rows = st.db.execute("SELECT subject,predicate,object FROM nuc "
                                                     "WHERE trust>=0.7 ORDER BY RANDOM() LIMIT 12").fetchall()
                        context = "\n".join("%s | %s | %s" % (r[0], r[1], r[2]) for r in rows)
                    finally:
                        st.close()
                    prompt = ("You are a HYPOTHESIS generator for a fact engine. Given the VERIFIED facts "
                              "below, propose up to 6 NEW candidate facts that are plausible and testable "
                              "but NOT already listed, as a JSON array of {subject,predicate,object} using "
                              "snake_case predicates. These are PROPOSALS ONLY, to be verified independently; "
                              "do not assert them as true. Return ONLY the JSON array.\n\nVERIFIED FACTS:\n"
                              + (context or "(store is empty — propose foundational candidates)"))
                    try:
                        raw = qb_chat.llm_complete(prov, prompt,
                                                   system="Propose testable hypotheses. JSON array only.",
                                                   max_tokens=700)
                    except Exception as e:
                        diag = qb_chat.provider_test(prov)
                        a["status"] = "blocked"
                        a["error"] = "LLM call failed (%s). %s" % (e, diag.get("detail", ""))
                        _ev("error", "agent:" + a["name"], a["error"]); self._save(); break
                    m = _re.search(r"\[.*\]", raw or "", _re.S)
                    props = []
                    if m:
                        try: props = _json.loads(m.group(0))
                        except Exception: props = []
                    HYP_SRC = ("SRC-LLM-HYP", "LLM hypothesis (unverified proposal via %s)"
                               % (prov.get("name") if prov else "LLM"), "llm-proposed", 0.15)
                    st = ufcs_store.UFCSStore(self.store_dir)
                    corrob = contra = openh = 0; samples = []
                    try:
                        for pr in (props or []):
                            if not isinstance(pr, dict):
                                continue
                            s = str(pr.get("subject", "")).strip()
                            p = str(pr.get("predicate", "")).strip()
                            o = str(pr.get("object", "")).strip()
                            if not (s and p and o):
                                continue
                            status, trust = "open", 0.15
                            try:
                                if st.get(ufcs_store.fingerprint(s, p, o)):
                                    status, trust = "corroborated", 0.20   # already independently verified
                                elif not st.no_fql:
                                    hit, _ = st.fql(s, p, 0.5, 5)
                                    if hit and all(str(r[2]).lower() != o.lower() for r in hit):
                                        status, trust = "contradicted", 0.05
                            except Exception:
                                pass
                            # store PROPOSAL isolated in the 'hypothesis' domain (predicate namespaced,
                            # low trust) so it can never be returned as a VERIFIED fact
                            st.add(ufcs_store.make_packet(s, "hypothesis:" + p, o, "+", "hypothesis", HYP_SRC, trust))
                            st.add(ufcs_store.make_packet('hypothesis "%s %s %s"' % (s, p, o),
                                                          "verification_status", status, "+", "hypothesis", HYP_SRC, trust))
                            if status == "corroborated": corrob += 1
                            elif status == "contradicted": contra += 1
                            else: openh += 1
                            if len(samples) < 6:
                                samples.append({"triple": "%s %s %s" % (s, p, o), "status": status})
                        st.flush()
                    finally:
                        st.close()
                    total = corrob + contra + openh
                    a["facts"] = a.get("facts", 0) + total
                    a["phase"] = ("Hypothesis — %d proposed (%d corroborated, %d contradicted, %d open); "
                                  "none asserted" % (total, corrob, contra, openh))
                    a["last_hypotheses"] = samples
                    a["error"] = None
                    _ev("ok", "agent:" + a["name"], a["phase"])
                elif a["kind"] == "simulation":
                    # LLM-backed SIMULATION agent — PERMITTED, strictly non-asserting. The LLM
                    # projects plausible CONSEQUENCES of a scenario; each projected consequence is
                    # verified against the deterministic store and stored isolated in a 'simulation'
                    # domain at low trust. Nothing projected is asserted as a fact.
                    import qb_chat, json as _json, re as _re
                    prov = self._best_provider(a.get("provider"))
                    if not (qb_chat.provider_usable(prov) or qb_chat._sdk_available()):
                        a["status"] = "blocked"
                        a["error"] = ("Simulation agent needs an LLM provider (permitted, non-asserting "
                                      "role). Open LLM Providers, paste your API key, press Test, then start. "
                                      "Projected consequences are verified against the store, never asserted.")
                        _ev("blocked", "agent:" + a["name"], a["error"]); self._save(); break
                    st = ufcs_store.UFCSStore(self.store_dir)
                    try:
                        seed = (a.get("target") or "").strip()
                        rows = []
                        if not st.no_fql:
                            if seed:
                                rows, _ = st.search(seed, 0.5, 12)
                            if not rows:
                                rows = st.db.execute("SELECT subject,predicate,object FROM nuc "
                                                     "WHERE trust>=0.7 ORDER BY RANDOM() LIMIT 12").fetchall()
                        context = "\n".join("%s | %s | %s" % (r[0], r[1], r[2]) for r in rows)
                    finally:
                        st.close()
                    scenario = seed or "the current state described by the verified facts"
                    prompt = ("You are a SIMULATION engine for a fact engine. Given the VERIFIED facts below "
                              "and the scenario \"%s\", project up to 6 plausible CONSEQUENCES as a JSON array "
                              "of {subject,predicate,object} using snake_case predicates. These are PROJECTIONS "
                              "ONLY, to be verified independently; do not assert them as true. Return ONLY the "
                              "JSON array.\n\nVERIFIED FACTS:\n%s" % (scenario, context or "(none yet)"))
                    try:
                        raw = qb_chat.llm_complete(prov, prompt,
                                                   system="Project testable consequences. JSON array only.",
                                                   max_tokens=700)
                    except Exception as e:
                        diag = qb_chat.provider_test(prov)
                        a["status"] = "blocked"
                        a["error"] = "LLM call failed (%s). %s" % (e, diag.get("detail", ""))
                        _ev("error", "agent:" + a["name"], a["error"]); self._save(); break
                    m = _re.search(r"\[.*\]", raw or "", _re.S)
                    props = []
                    if m:
                        try: props = _json.loads(m.group(0))
                        except Exception: props = []
                    SIM_SRC = ("SRC-LLM-SIM", "LLM simulation (unverified projection via %s)"
                               % (prov.get("name") if prov else "LLM"), "llm-projected", 0.15)
                    st = ufcs_store.UFCSStore(self.store_dir)
                    corrob = contra = openh = 0; samples = []
                    try:
                        for pr in (props or []):
                            if not isinstance(pr, dict):
                                continue
                            s = str(pr.get("subject", "")).strip()
                            p = str(pr.get("predicate", "")).strip()
                            o = str(pr.get("object", "")).strip()
                            if not (s and p and o):
                                continue
                            status, trust = "open", 0.15
                            try:
                                if st.get(ufcs_store.fingerprint(s, p, o)):
                                    status, trust = "corroborated", 0.20
                                elif not st.no_fql:
                                    hit, _ = st.fql(s, p, 0.5, 5)
                                    if hit and all(str(r[2]).lower() != o.lower() for r in hit):
                                        status, trust = "contradicted", 0.05
                            except Exception:
                                pass
                            st.add(ufcs_store.make_packet(s, "sim:" + p, o, "+", "simulation", SIM_SRC, trust))
                            st.add(ufcs_store.make_packet('simulation "%s %s %s"' % (s, p, o),
                                                          "verification_status", status, "+", "simulation", SIM_SRC, trust))
                            if status == "corroborated": corrob += 1
                            elif status == "contradicted": contra += 1
                            else: openh += 1
                            if len(samples) < 6:
                                samples.append({"triple": "%s %s %s" % (s, p, o), "status": status})
                        st.flush()
                    finally:
                        st.close()
                    total = corrob + contra + openh
                    a["facts"] = a.get("facts", 0) + total
                    a["phase"] = ("Simulation — %d projected (%d corroborated, %d contradicted, %d open); "
                                  "none asserted" % (total, corrob, contra, openh))
                    a["last_hypotheses"] = samples
                    a["error"] = None
                    _ev("ok", "agent:" + a["name"], a["phase"])
                elif a["kind"] in _ROADMAP_ENGINE:
                    # Roadmap roles REFUSE rather than fabricate: the engine is spec-only.
                    a["status"] = "roadmap"
                    a["error"] = ("'%s' agent is specified but not yet implemented — it requires the %s engine "
                                  "(spec-only per the coverage audit). Refusing to run rather than fabricate."
                                  % (a["kind"], _ROADMAP_ENGINE[a["kind"]]))
                    _ev("blocked", "agent:" + a["name"], "roadmap — needs %s engine (declined, not an error)"
                        % _ROADMAP_ENGINE[a["kind"]])
                    self._save(); break
                else:
                    a["error"] = "unknown kind"; a["status"] = "error"; self._save(); break
                a["cycles"] += 1; a["last_run"] = time.time(); a["error"] = None
                a["retries"] = 0                      # a clean cycle resets the retry budget
                self._save()
            except Exception as e:
                a["error"] = str(e); a["_last_err"] = str(e)
                a["status"] = "error"; a["error_at"] = time.time()
                _ev("error", "agent:" + a["name"], "cycle failed: %s" % e)
                self._save(); break
            # wait the interval (seconds), checking stop frequently
            for _ in range(max(1, int(a.get("interval", 10)))):
                if self.stop.get(aid) or self.agents.get(aid, {}).get("status") != "running":
                    break
                time.sleep(1)
        a = self.agents.get(aid)
        if a and a["status"] == "running":
            a["status"] = "stopped"; self._save()
