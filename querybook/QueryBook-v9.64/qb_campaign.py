"""qb_campaign — harvest campaigns, the master On/Off switch, open online sources and the Google exemplar tools (v9.64).

* Master switch: ON runs every switched-on source (or the active campaign's selection); OFF stops all of it.
* Sources: the built-in domain generators (mathematics, geometry, arithmetic …) and the open online sources of
  qb_online.py (Wikidata CC0, US government public-domain data, CC0 museum and library metadata) — each switched on or
  off on its own. Every online fact keeps its source, licence and page as provenance; no source wording is stored.
* Campaigns: a named selection of sources and Google tools with an optional goal (new facts), started and stopped together;
  starting one runs only its selection. Progress is counted from the moment it started.
* Google tools: Gemini Omni, Veo, TTS, image, text and transcription models that make *examples* (learning objects in the
  exemplar library), never facts. They run in the separate exemplar generator (generate_exemplars.py run-campaign
  --switches …), never in this server; each is off until switched on, and none runs until the admin has accepted the
  Gemini API terms here. The Gemini key is kept in api-keys.json (owner-only) in the data folder.

State lives in <data>/campaigns.json. Standard library only; deterministic apart from what the sources return.
"""
import collections, json, os, subprocess, sys, threading, time

import qb_online as ol
import ufcs_store as store

VERSION = "1.2.0"
HERE = os.path.dirname(os.path.abspath(__file__))
# the licence of each online source (the Composite Registry's classes; only unrestricted classes are harvested here)
LICENCE = {"wikidata": ("CC0 1.0", "cc0"), "natural-earth": ("Public domain", "public-domain"), "frus": ("US government work", "us-federal"),
           "met-open-access": ("CC0", "cc0"), "ncbi-taxonomy": ("US government work", "us-federal"), "smithsonian-open-access": ("CC0 (items marked CC0)", "cc0"),
           "usda-fooddata-central": ("CC0 1.0", "cc0"), "nara-catalog": ("Federal records: not copyrighted", "us-federal"), "dpla-metadata": ("CC0 (metadata)", "cc0"),
           "europeana-metadata": ("CC0 (metadata)", "cc0"), "usgs-earthquakes": ("US government work", "us-federal"),
           "federal-register": ("US government work; no restrictions on republication", "us-federal"), "pubchem-computed": ("US government work (computed properties)", "us-federal")}
TRUST = {"cc0": 0.9, "public-domain": 0.9, "us-federal": 0.92}
GOOGLE_TOOLS = {   # (the same catalogue as the applications' qbcampaign.py)
    "omni-speech-video": ("Talking-face speech clips — Gemini Omni 1.1 Flash", "gemini-omni-1.1-flash", 100),
    "veo-speech-video": ("Talking-face and movement clips — Veo 3 Fast", "veo-3.0-fast-generate-001", 10),
    "tts-pronunciation": ("Reference pronunciations — Gemini 3.8 Flash TTS", "gemini-3.8-flash-tts", 100),
    "image-mouth-shapes": ("Mouth-shape stills — Nano Banana 2", "gemini-3.1-flash-image", 1000),
    "image-pro-poses": ("Pose and angle stills — Nano Banana Pro", "gemini-3-pro-image", 250),
    "text-drills": ("Drill texts — Gemini 3.8 Flash", "gemini-3.8-flash", 10000),
    "transcribe-check": ("Second-opinion transcripts — Gemini 3.5 Transcribe", "gemini-3.5-transcribe", 100),
}


class Campaigns:
    def __init__(self, data_dir, harvest_busy=lambda: False, log=None, autorun=True):
        self.autorun = autorun
        self.dir = data_dir
        self.path = os.path.join(data_dir, "campaigns.json")
        self.busy = harvest_busy
        self.log = log or (lambda *a: None)
        self._lock = threading.Lock()
        self._thread = None
        self._backoff = {}
        self._good = None             # the last state read whole (a half-written or locked file never reads as "master off")
        self.heartbeat = 0.0          # when the harvesting loop last went round
        self._store_lock = threading.Lock()     # lanes fetch in parallel; one writes to the store at a time
        self._lanes = {}              # lane → its thread (one per site, plus "local" for the built-in generators)
        self._turn = {}               # lane → round-robin position
        self.lanes = {}               # lane → what it is doing now (shown in the status bar)
        self._made = collections.deque(maxlen=2000)     # (time, new facts) of recent tasks — the facts-a-minute rate
        ol._KEYS["folder"] = data_dir

    # ------------------------------------------------------------------ state
    def state(self):
        s = None
        for attempt in range(5):
            try:
                with open(self.path, encoding="utf-8") as f:
                    s = json.load(f)
                self._good = json.loads(json.dumps(s))
                break
            except FileNotFoundError:
                s = {}
                break
            except (OSError, ValueError):
                # Windows: the file is being replaced by another thread (sharing violation), or a reader caught it
                # half-written. Never take that for "master off": retry, then fall back to the last good state.
                time.sleep(0.05 * (attempt + 1))
        if s is None:
            s = json.loads(json.dumps(self._good)) if self._good is not None else {}
        s.setdefault("master", "off"); s.setdefault("sources", {}); s.setdefault("cursors", {}); s.setdefault("campaigns", [])
        s.setdefault("active", None); s.setdefault("tools", {}); s.setdefault("google_terms_accepted", False); s.setdefault("recent", [])
        s.setdefault("counts", {})
        return s

    def _save(self, s):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=1)
        for attempt in range(10):
            try:
                os.replace(tmp, self.path)
                break
            except PermissionError:                     # Windows: a reader has the file open for a moment
                if attempt == 9:
                    raise
                time.sleep(0.05 * (attempt + 1))
        self._good = json.loads(json.dumps(s))

    def sources(self):
        out = [{"name": "domain:" + d, "title": "Generated %s facts (built-in, deterministic)" % d, "kind": "generator", "licence": "computed by QueryBook",
                "class": "computed"} for d in sorted(store.DOMAIN_GEN)]
        for k, h in ol.HARVESTERS.items():
            lic = LICENCE.get(h[1])
            if not lic:
                continue
            out.append({"name": k, "title": h[2], "kind": "online", "why": h[3], "licence": lic[0], "class": lic[1], "source": h[1],
                        "needs_key": ol.NEEDS_KEY.get(k)})
        return out

    def view(self):
        s = self.state()
        src = self.sources()
        for x in src:
            x["on"] = s["sources"].get(x["name"]) == "on"
            x["cursor"] = s["cursors"].get(x["name"])
            x["facts"] = s["counts"].get(x["name"], 0)
            x["key_set"] = (not x.get("needs_key")) or bool(ol._key(x["needs_key"]))
        run = self.runner_status()
        self.ensure_running()                           # watchdog: master ON always has a live harvesting loop
        tools = [{"id": t, "title": v[0], "model": v[1], "budget": v[2], "on": (s["tools"].get(t) or {}).get("on", False),
                  "plan": (s["tools"].get(t) or {}).get("plan", ""), "made_today": (run.get("today") or {}).get(v[1], 0)} for t, v in GOOGLE_TOOLS.items()]
        for c in s["campaigns"]:
            c["progress"] = {n: s["counts"].get(n, 0) - (c.get("start_counts") or {}).get(n, 0) for n in c.get("sources", [])} if c.get("start_counts") is not None else None
            c["new_facts"] = sum((c["progress"] or {}).values())
        return {"version": VERSION, "master": s["master"], "active": s["active"], "pulse": self.pulse(), "sources": src, "campaigns": s["campaigns"], "tools": tools,
                "google_terms_accepted": s["google_terms_accepted"], "runner": run, "recent": s["recent"][:20],
                "gemini_key_set": bool(ol.load_keys(self.dir).get("gemini")), "keys": ol.key_status(self.dir)}

    # ------------------------------------------------------------------ switches
    def master(self, on):
        with self._lock:
            s = self.state()
            s["master"] = "on" if on else "off"
            if not on and s["active"]:
                for c in s["campaigns"]:
                    if c["id"] == s["active"]:
                        c["status"] = "stopped"
                s["active"] = None
            self._save(s)
        self.log("info", "campaign", "master %s" % ("ON" if on else "OFF"))
        if on:
            self.ensure_running()
        return self.view()

    def switch_source(self, name, on):
        if name not in {x["name"] for x in self.sources()}:
            raise ValueError("No such source.")
        with self._lock:
            s = self.state(); s["sources"][name] = "on" if on else "off"; self._save(s)
        return self.view()

    def switch_tool(self, tid, on, plan=None, accept_terms=False):
        if tid not in GOOGLE_TOOLS:
            raise ValueError("No such tool.")
        with self._lock:
            s = self.state()
            if accept_terms:
                s["google_terms_accepted"] = True
            if on and not s["google_terms_accepted"]:
                raise ValueError("Accept the Gemini API terms first (Google tools make examples only; paid tier; no use to build a competing model).")
            t = s["tools"].setdefault(tid, {})
            t["on"] = bool(on)
            if plan is not None:
                t["plan"] = str(plan).strip()
            self._save(s)
        return self.view()

    def save_key(self, key, service="gemini"):
        ol.save_key(self.dir, service or "gemini", key)      # api-keys.json in the data folder, owner-only; never logged
        return self.view()

    # ------------------------------------------------------------------ campaigns
    def save_campaign(self, data):
        name = " ".join(str(data.get("name") or "").split())[:80]
        if not name:
            raise ValueError("Give the campaign a name.")
        known = {x["name"] for x in self.sources()}
        with self._lock:
            s = self.state()
            cid = data.get("id") or "c%d" % (max([int(c["id"][1:]) for c in s["campaigns"]] + [0]) + 1)
            c = next((x for x in s["campaigns"] if x["id"] == cid), None)
            if c is None:
                c = {"id": cid, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "status": "ready"}
                s["campaigns"].append(c)
            c.update(name=name, sources=[x for x in data.get("sources") or [] if x in known], tools=[t for t in data.get("tools") or [] if t in GOOGLE_TOOLS],
                     goal=int(data.get("goal") or 0))
            if not (c["sources"] or c["tools"]):
                raise ValueError("Choose at least one source or Google tool.")
            self._save(s)
        return self.view()

    def delete_campaign(self, cid):
        with self._lock:
            s = self.state()
            s["campaigns"] = [c for c in s["campaigns"] if c["id"] != cid]
            if s["active"] == cid:
                s["active"] = None
            self._save(s)
        return self.view()

    def start_campaign(self, cid):
        with self._lock:
            s = self.state()
            c = next((x for x in s["campaigns"] if x["id"] == cid), None)
            if not c:
                raise ValueError("No such campaign.")
            if c["tools"] and not s["google_terms_accepted"]:
                raise ValueError("This campaign uses Google tools: accept the Gemini API terms first.")
            for x in s["campaigns"]:
                if x["status"] == "running":
                    x["status"] = "stopped"
            for t in GOOGLE_TOOLS:
                s["tools"].setdefault(t, {})["on"] = t in c["tools"]
            c.update(status="running", started=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     start_counts={n: s["counts"].get(n, 0) for n in c["sources"]})
            s["active"], s["master"] = cid, "on"
            self._save(s)
        self.ensure_running()
        return self.view()

    def stop_campaign(self, cid):
        with self._lock:
            s = self.state()
            for c in s["campaigns"]:
                if c["id"] == cid:
                    c["status"] = "stopped"
                    for t in c["tools"]:
                        s["tools"].setdefault(t, {})["on"] = False
            if s["active"] == cid:
                s["active"] = None
            self._save(s)
        return self.view()

    # ------------------------------------------------------------------ the harvesting loop
    def selection(self, s):
        if s["active"]:
            c = next((x for x in s["campaigns"] if x["id"] == s["active"]), None)
            if c:
                return c["sources"]
        return [n for n, v in s["sources"].items() if v == "on"]

    @staticmethod
    def lane_of(name):
        """Sources on the same site share a lane (and its politeness); different sites run side by side."""
        if name.startswith("domain:"):
            return "local"
        h = ol.HARVESTERS.get(name)
        return h[1] if h else name

    def _lane_set(self, lane, **kw):
        cur = self.lanes.get(lane) or {}
        cur.update(kw, at=time.time())
        self.lanes[lane] = cur

    def step(self, lane=None):
        """one task: the next due source of the selection (of one lane, when given), round robin (returns what it did, or None)"""
        s = self.state()
        if s["master"] != "on":
            return None
        sel = [n for n in self.selection(s) if self._backoff.get(n, 0) < time.time() and (lane is None or self.lane_of(n) == lane)]
        if not sel:
            return None
        key = lane or "*"
        k = self._turn.get(key, int(s.get("turn", 0))) % len(sel)
        self._turn[key] = k + 1
        name = sel[k]
        if lane:
            self._lane_set(lane, state="working", source=name)
        added, detail = 0, ""
        try:
            if name.startswith("domain:"):
                if self.busy():
                    return None
                info = {}
                with self._store_lock:
                    # verify=False: the full read-back proof scans the open block (up to 1 GB) and grows with the store —
                    # seconds at 300k facts, minutes at millions. Each batch is committed to the index before it returns.
                    store.harvest_into(self.dir, 2000, "gzip", 1024, domain=name.split(":", 1)[1], info=info, verify=False)
                added = int(info.get("made", 0))
                detail = "%d generated facts" % added
                if info.get("exhausted"):                 # a finite generator (history, news, culture, art) is complete
                    self._backoff[name] = time.time() + 6 * 3600
                    detail += " — every built-in fact of this domain is stored; switch on its online sources for more"
            else:
                h = ol.HARVESTERS[name]
                if name in ol.NEEDS_KEY and not ol._key(ol.NEEDS_KEY[name]):
                    self._backoff[name] = time.time() + 3600
                    return "%s waits for its free key" % name
                cur = int(s["cursors"].get(name, 0))
                if cur < 0:
                    return None
                items, nxt, detail = h[6](cur, 50)
                lic, cls = LICENCE[h[1]]
                with self._store_lock:
                    st = store.UFCSStore(self.dir)
                    try:
                        for it in items:
                            ev = it["evidence"][0]
                            pkt = store.make_packet(str(it["subject"])[:300], str(it["predicate"])[:200], str(it["object"])[:500], "+", "online",
                                                    ("SRC-" + h[1].upper(), ev["source"], cls, TRUST[cls]), TRUST[cls])
                            pkt["provenance"] = {"url": ev.get("url"), "licence": lic, "harvester": name, "why": (it.get("reasoning") or [""])[0]}
                            if st.add(pkt):
                                added += 1
                        st.flush()
                    finally:
                        st.close()
                with self._lock:
                    s2 = self.state(); s2["cursors"][name] = -1 if nxt is None else nxt; self._save(s2)
        except ol.SourceBusy as e:
            until = getattr(e, "until", None) or time.time() + 600     # RateLimited carries the site's own Retry-After
            self._backoff[name] = until
            detail = "waiting %d s: %s" % (max(1, until - time.time()), e)
        except Exception as e:
            self._backoff[name] = time.time() + 600
            detail = "failed: %s" % e
        with self._lock:
            s2 = self.state()
            s2["turn"] = int(s2.get("turn", 0)) + 1
            s2["counts"][name] = s2["counts"].get(name, 0) + added
            s2["recent"] = ([{"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source": name, "new": added, "detail": detail}] + s2["recent"])[:50]
            for c in s2["campaigns"]:
                if c["id"] == s2["active"] and c.get("goal") and sum(s2["counts"].get(n, 0) - (c.get("start_counts") or {}).get(n, 0) for n in c["sources"]) >= c["goal"]:
                    c["status"] = "goal reached"; s2["active"] = None
            self._save(s2)
        self._made.append((time.time(), added))
        if lane:
            self._lane_set(lane, state="idle", source=name, last="%s: %s" % (name, detail), until=self._backoff.get(name))
        self.log("info", "campaign", "%s: %s" % (name, detail))
        return "%s: %s" % (name, detail)

    def _loop(self):
        """Supervisor: keeps one harvesting lane per site of the selection, so a slow or rate-limited site never holds
        the others up; it ends (and so do the lanes) when the master switch goes OFF."""
        try:
            while True:
                self.heartbeat = time.time()
                try:
                    s = self.state()
                    if s["master"] != "on":
                        break
                    for lane in sorted({self.lane_of(n) for n in self.selection(s)}):
                        t = self._lanes.get(lane)
                        if t is None or not t.is_alive():
                            if t is not None:
                                self.log("warn", "campaign", "harvesting lane %s had stopped; restarting it" % lane)
                            t = threading.Thread(target=self._lane, args=(lane,), name="qb-lane-" + lane, daemon=True)
                            self._lanes[lane] = t
                            t.start()
                except Exception as e:                  # the supervisor must never die
                    self.log("error", "campaign", "supervisor: %r" % e)
                time.sleep(2.0)
        finally:
            if self._thread is threading.current_thread():
                self._thread = None

    def _lane(self, lane):
        """One site's tasks, one after another, for as long as the master is ON and the lane has sources."""
        try:
            while True:
                try:
                    s = self.state()
                    if s["master"] != "on":
                        break
                    mine = [n for n in self.selection(s) if self.lane_of(n) == lane]
                    if not mine:
                        break
                    did = self.step(lane)
                except Exception as e:
                    did = None
                    self.log("error", "campaign", "lane %s: %r" % (lane, e))
                if did:
                    time.sleep(0.2)                     # straight on to the next task while there is work
                else:                                   # nothing due: sleep until this lane's first wait is over (max 15 s)
                    waits = [self._backoff[n] - time.time() for n in mine if self._backoff.get(n, 0) > time.time()]
                    nap = max(1.0, min([15.0] + waits))
                    self._lane_set(lane, state="waiting" if waits else "idle", until=time.time() + nap)
                    time.sleep(nap)
        finally:
            self.lanes.pop(lane, None)
            if self._lanes.get(lane) is threading.current_thread():
                self._lanes.pop(lane, None)

    def pulse(self):
        """The master status bar: is harvesting running, how fast, and what each lane is doing."""
        now = time.time()
        made = list(self._made)                     # a snapshot: the lanes append while this reads
        recent = [(t, n) for t, n in made if now - t <= 600]
        last_new = max((t for t, n in made if n), default=None)
        live = self._thread is not None and self._thread.is_alive()
        lanes = []
        for lane, v in sorted(dict(self.lanes).items()):
            until = v.get("until") or 0
            lanes.append({"lane": lane, "state": v.get("state", "idle"), "source": v.get("source"), "last": v.get("last"),
                          "wait_s": round(until - now) if v.get("state") == "waiting" and until > now else 0,
                          "busy_s": round(now - v["at"]) if v.get("state") == "working" else 0})
        working = sum(1 for x in lanes if x["state"] == "working")
        return {"running": live, "heartbeat_s": round(now - self.heartbeat, 1) if self.heartbeat else None,
                "facts_10min": sum(n for _, n in recent), "facts_per_min": round(sum(n for _, n in recent if now - _ <= 60), 1),
                "tasks_10min": len(recent), "last_new_s": round(now - last_new) if last_new else None,
                "lanes": lanes, "working": working, "waiting": sum(1 for x in lanes if x["state"] == "waiting")}

    def ensure_running(self):
        """Start the harvesting loop when the master is ON — or restart it when it died."""
        t = self._thread
        if t is not None and not t.is_alive():
            self.log("warn", "campaign", "the harvesting loop had stopped; restarting it")
            self._thread = t = None
        if self.autorun and t is None and self.state()["master"] == "on":
            self._thread = threading.Thread(target=self._loop, name="qb-campaign", daemon=True)
            self._thread.start()

    # ------------------------------------------------------------------ the exemplar generator (Google tools)
    def runner_status(self):
        try:
            with open(os.path.join(self.dir, "exemplars", "_runner.json"), encoding="utf-8") as f:
                r = json.load(f)
            r["alive"] = time.time() - float(r.get("heartbeat", 0)) < 120
            return r
        except (OSError, ValueError):
            return {"alive": False}

    def runner(self, action):
        folder = os.path.join(self.dir, "exemplars")
        os.makedirs(folder, exist_ok=True)
        if action == "stop":
            open(os.path.join(folder, "_runner.stop"), "w").close()
            return {"summary": "the exemplar generator stops after its current request"}
        if self.runner_status().get("alive"):
            return {"summary": "already running"}
        gen = os.path.join(HERE, "generate_exemplars.py")
        kw = {"creationflags": 0x00000008 | 0x00000200} if os.name == "nt" else {"start_new_session": True}
        subprocess.Popen([sys.executable, gen, "--library", folder, "run-campaign", "--commons", self.dir, "--switches", self.path],
                         cwd=HERE, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
        return {"summary": "the exemplar generator is starting"}


def self_test(tmp=None):
    import tempfile, shutil
    d = tmp or tempfile.mkdtemp(prefix="qbcamp-")
    out = []
    ok = lambda n, c: out.append((n, bool(c)))
    try:
        C = Campaigns(d, autorun=False)
        names = {x["name"] for x in C.sources()}
        ok("every open online source is offered, with its licence", "usgs-earthquakes" in names and "wikidata-rivers" in names
           and all(x["class"] in ("cc0", "public-domain", "us-federal", "computed") for x in C.sources()))
        C.switch_source("wikidata-rivers", True)
        ok("sources switch on one at a time", [x["name"] for x in C.view()["sources"] if x["on"]] == ["wikidata-rivers"])
        try:
            C.switch_tool("tts-pronunciation", True); ok("Google tools need the terms accepted first", False)
        except ValueError:
            ok("Google tools need the terms accepted first", True)
        C.save_campaign({"name": "Rivers", "sources": ["wikidata-rivers", "usgs-earthquakes"], "goal": 10})
        v = C.start_campaign(C.view()["campaigns"][0]["id"])
        ok("a campaign starts its selection and the master switch", v["master"] == "on" and v["active"] == "c1")
        ok("sources on the same site share a lane; different sites and the generators run side by side",
           C.lane_of("wikidata-rivers") == C.lane_of("wikidata-countries") != C.lane_of("usgs-earthquakes") and C.lane_of("domain:mathematics") == "local")
        C._backoff["usgs-earthquakes"] = time.time() + 600
        ol_fn = ol.HARVESTERS["wikidata-rivers"][6]
        ol.HARVESTERS["wikidata-rivers"] = ol.HARVESTERS["wikidata-rivers"][:6] + (lambda cur, n: ([], None, "test: nothing"),)
        try:
            did = C.step(C.lane_of("wikidata-rivers"))
        finally:
            ol.HARVESTERS["wikidata-rivers"] = ol.HARVESTERS["wikidata-rivers"][:6] + (ol_fn,)
        p = C.pulse()
        ok("a lane takes only its own site's sources, and the status bar sees it", (did or "").startswith("wikidata-rivers")
           and C.step("usgs-earthquakes") is None and {"facts_per_min", "lanes", "working", "last_new_s"} <= set(p))
        C.master(False)
        ok("master OFF stops everything", C.view()["master"] == "off" and C.view()["active"] is None and C.step() is None)
    finally:
        if not tmp:
            shutil.rmtree(d, ignore_errors=True)
    return out


def qc():
    rows = [{"check": n, "pass": g} for n, g in self_test()]
    return {"ok": all(r["pass"] for r in rows), "passed": sum(r["pass"] for r in rows), "total": len(rows), "rows": rows}


if __name__ == "__main__":
    r = qc()
    for x in r["rows"]:
        print("  [%s] %s" % ("OK" if x["pass"] else "FAIL", x["check"]))
    print("  %d/%d checks passed" % (r["passed"], r["total"]))
