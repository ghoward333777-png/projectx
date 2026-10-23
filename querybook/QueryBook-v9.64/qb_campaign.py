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
import json, os, subprocess, sys, threading, time

import qb_online as ol
import ufcs_store as store

VERSION = "1.0.0"
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
        ol._KEYS["folder"] = data_dir

    # ------------------------------------------------------------------ state
    def state(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                s = json.load(f)
        except (OSError, ValueError):
            s = {}
        s.setdefault("master", "off"); s.setdefault("sources", {}); s.setdefault("cursors", {}); s.setdefault("campaigns", [])
        s.setdefault("active", None); s.setdefault("tools", {}); s.setdefault("google_terms_accepted", False); s.setdefault("recent", [])
        s.setdefault("counts", {})
        return s

    def _save(self, s):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=1)
        os.replace(tmp, self.path)

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
        tools = [{"id": t, "title": v[0], "model": v[1], "budget": v[2], "on": (s["tools"].get(t) or {}).get("on", False),
                  "plan": (s["tools"].get(t) or {}).get("plan", ""), "made_today": (run.get("today") or {}).get(v[1], 0)} for t, v in GOOGLE_TOOLS.items()]
        for c in s["campaigns"]:
            c["progress"] = {n: s["counts"].get(n, 0) - (c.get("start_counts") or {}).get(n, 0) for n in c.get("sources", [])} if c.get("start_counts") is not None else None
            c["new_facts"] = sum((c["progress"] or {}).values())
        return {"version": VERSION, "master": s["master"], "active": s["active"], "sources": src, "campaigns": s["campaigns"], "tools": tools,
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

    def step(self):
        """one task: the next source of the selection, round robin (returns what it did, or None)"""
        s = self.state()
        if s["master"] != "on":
            return None
        sel = [n for n in self.selection(s) if self._backoff.get(n, 0) < time.time()]
        if not sel:
            return None
        k = int(s.get("turn", 0)) % len(sel)
        name = sel[k]
        added, detail = 0, ""
        try:
            if name.startswith("domain:"):
                if self.busy():
                    return None
                before = store.manifest_value(self.dir, "facts", 0)
                store.harvest_into(self.dir, 2000, "gzip", 1024, domain=name.split(":", 1)[1])
                added = store.manifest_value(self.dir, "facts", 0) - before
                detail = "%d generated facts" % added
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
            self._backoff[name] = time.time() + 600
            detail = "paused 10 min: %s" % e
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
        self.log("info", "campaign", "%s: %s" % (name, detail))
        return "%s: %s" % (name, detail)

    def _loop(self):
        while True:
            try:
                did = self.step()
            except Exception as e:
                did = None
                self.log("error", "campaign", repr(e))
            if self.state()["master"] != "on":
                break
            time.sleep(2 if did else 15)
        self._thread = None

    def ensure_running(self):
        if self.autorun and self._thread is None and self.state()["master"] == "on":
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
