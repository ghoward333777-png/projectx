"""qbcampaign — harvest campaigns, the master On/Off switch, and the Google exemplar tools.

A campaign is a named selection of what to harvest — applications, online harvesters (open sources the admin approved) and
Google exemplar tools — started and stopped together, with its progress measured from the harvest record and the exemplar
library since it started. Starting a campaign runs only its selection; stopping it stops only its selection. The master
switch starts or stops everything at once.

The Google tools (Gemini Omni, Veo, the TTS, image, text and transcription models) make *examples*, never facts: their output
goes to the exemplar library as learning objects, measured by QueryBook and approved by the admin. They are run by the admin's
generator (tools/generate_exemplars.py, `run-campaign`), a separate program the Control Panel starts — never inside the
applications or their agents, which stay free of AI models. Each tool is off until the admin switches it on (passphrase), and
only while the registry source "google-generative-exemplars" is approved (its licence class is terms-of-service, so approving
it needs the admin's explicit acceptance). Each has a daily request budget; the generator never exceeds it.

Standard library only.
"""
import json, os, time

VERSION = "1.0.0"
SOURCE_KEY = "google-generative-exemplars"
GOOGLE_TOOLS = {
    "omni-speech-video": {"title": "Talking-face speech clips — Gemini Omni 1.1 Flash", "model": "gemini-omni-1.1-flash", "kind": "video",
                          "makes": "10-second videos of an avatar saying one line of the speech test script: her speech motion library and the lip-reading curriculum",
                          "budget": 100, "plan_hint": "a speech-script plan with the avatar's image (generate_exemplars.py plan --script …)"},
    "veo-speech-video": {"title": "Talking-face and movement clips — Veo 3 Fast", "model": "veo-3.0-fast-generate-001", "kind": "video",
                         "makes": "a second video source when Omni's daily limit is spent; body moves for the motion library",
                         "budget": 10, "plan_hint": "a speech-script or movement plan with the avatar's image"},
    "tts-pronunciation": {"title": "Reference pronunciations — Gemini 3.8 Flash TTS", "model": "gemini-3.8-flash-tts", "kind": "audio",
                          "makes": "a stock voice saying single words and sentences: pronunciation and syllable-timing references for Language Builder",
                          "budget": 100, "plan_hint": "a word-list plan (tools/plans/pronunciation-en.json)"},
    "image-mouth-shapes": {"title": "Mouth-shape stills — Nano Banana 2 (Gemini 3.1 Flash Image)", "model": "gemini-3.1-flash-image", "kind": "image",
                           "makes": "stills of an avatar holding one mouth shape (oo, ee, f, th …): target shapes per viseme",
                           "budget": 1000, "plan_hint": "a mouth-shape plan with the avatar's image (tools/plans/mouth-shapes.json + --image)"},
    "image-pro-poses": {"title": "Pose and angle stills — Nano Banana Pro (Gemini 3 Pro Image)", "model": "gemini-3-pro-image", "kind": "image",
                        "makes": "an avatar seen from other angles: turnaround references",
                        "budget": 250, "plan_hint": "a pose plan with the avatar's image"},
    "text-drills": {"title": "Drill texts — Gemini 3.8 Flash", "model": "gemini-3.8-flash", "kind": "text",
                    "makes": "minimal pairs, graded sentences and look-alike word lists for the lip-reading and pronunciation curricula (checked by the dictionary)",
                    "budget": 10000, "plan_hint": "a drill plan (tools/plans/drills-en.json)"},
    "transcribe-check": {"title": "Second-opinion transcripts — Gemini 3.5 Transcribe", "model": "gemini-3.5-transcribe", "kind": "transcribe",
                         "makes": "a second transcript of each exemplar clip, beside QueryBook's own word check (never the only judge)",
                         "budget": 100, "plan_hint": "none needed: it checks the exemplar clips already in the library"},
}


def _get(c, key, default=None):
    v = c.setting(key)
    if v is None:
        return default
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return v


def _put(c, key, value, db=None):
    c.set_setting(key, json.dumps(value) if not isinstance(value, str) else value, db)


def master_running(c):
    return c.setting("harvest:master", "running") != "stopped"


def source_approved(c):
    try:
        return bool(c.registry.check(SOURCE_KEY)[0])
    except Exception:
        return False


def runner_status(c):
    p = os.path.join(c.folder, "exemplars", "_runner.json")
    try:
        with open(p, encoding="utf-8") as f:
            r = json.load(f)
        r["alive"] = time.time() - float(r.get("heartbeat", 0)) < 120
        return r
    except (OSError, ValueError):
        return {"alive": False}


def tools(c):
    run = runner_status(c)
    out = []
    for tid, t in GOOGLE_TOOLS.items():
        plan = c.setting("gtool-plan:%s" % tid) or ""
        on = c.setting("gtool:%s" % tid, "off") == "on"
        state = ("off" if not on else "waiting for the admin to approve the Google source" if not source_approved(c)
                 else "needs a plan" if not plan and t["kind"] != "transcribe" else "waiting — harvesting is stopped" if not master_running(c)
                 else "running" if run.get("alive") else "on — start the exemplar generator (Harvesting page or Control Panel)")
        out.append(dict(t, id=tid, on=on, plan=plan, state=state, made_today=(run.get("today") or {}).get(t["model"], 0)))
    return out


def set_tool(c, tid, on, passphrase, plan=None):
    """switch one Google tool on or off (on needs the admin and the approved Google source); set its plan"""
    if tid not in GOOGLE_TOOLS:
        raise ValueError("No such tool: %s" % tid)
    if on or plan is not None:
        c.approvals._require(passphrase or "")
    if on and not source_approved(c):
        raise ValueError("Approve the source “Google Gemini API — generated exemplars” in the policy registry first "
                         "(its terms are a condition, so approving it needs your explicit acceptance).")
    with c.store.write() as db:
        if plan is not None:
            _put(c, "gtool-plan:%s" % tid, str(plan).strip(), db)
        _put(c, "gtool:%s" % tid, "on" if on else "off", db)
        c.agent_log(db, "engine", "Google tool %s switched %s" % (tid, "on" if on else "off"))
    return tools(c)


def generator_path(program_dir):
    """the exemplar generator beside the applications: tools/ in the source tree, extras/exemplar-generator/ in the suite"""
    up = os.path.dirname(os.path.abspath(program_dir))
    for p in (os.path.join(up, "tools", "generate_exemplars.py"), os.path.join(up, "extras", "exemplar-generator", "generate_exemplars.py")):
        if os.path.isfile(p):
            return p
    return None


def runner(c, action, passphrase, program_dir):
    """start (admin) or stop the exemplar generator — a separate program; the applications never run a model themselves"""
    import subprocess, sys
    folder = os.path.join(c.folder, "exemplars")
    os.makedirs(folder, exist_ok=True)
    if action == "stop":
        open(os.path.join(folder, "_runner.stop"), "w").close()
        return {"summary": "the exemplar generator stops after its current request", **status(c)}
    c.approvals._require(passphrase or "")
    if runner_status(c).get("alive"):
        return {"summary": "the exemplar generator is already running", **status(c)}
    path = generator_path(program_dir)
    if not path:
        raise ValueError("The exemplar generator is not installed beside this application (extras/exemplar-generator).")
    kw = {"creationflags": 0x00000008 | 0x00000200} if os.name == "nt" else {"start_new_session": True}
    subprocess.Popen([sys.executable, path, "run-campaign", "--commons", c.folder], cwd=os.path.dirname(path), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    with c.store.write() as db:
        c.agent_log(db, "engine", "Exemplar generator started (Google tools, outside the applications)")
    return {"summary": "the exemplar generator is starting", **status(c)}


# ------------------------------------------------------------------------------------------------ campaigns
def _all(c):
    return _get(c, "campaigns", []) or []


def save_campaign(c, data, known_harvesters):
    name = " ".join(str(data.get("name") or "").split())[:80]
    if not name:
        raise ValueError("Give the campaign a name.")
    cs = _all(c)
    cid = data.get("id") or "c%d" % (max([int(x["id"][1:]) for x in cs] + [0]) + 1)
    camp = next((x for x in cs if x["id"] == cid), None)
    if camp is None:
        camp = {"id": cid, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "status": "ready"}
        cs.append(camp)
    camp.update(name=name, apps=[a for a in data.get("apps") or [] if a in ("language", "stem", "facts")],
                harvesters=[h for h in data.get("harvesters") or [] if h in known_harvesters],
                tools=[t for t in data.get("tools") or [] if t in GOOGLE_TOOLS],
                note=str(data.get("note") or "")[:300], goal=int(data.get("goal") or 0))
    if not (camp["apps"] or camp["harvesters"] or camp["tools"]):
        raise ValueError("Choose at least one application, harvester or Google tool.")
    _put(c, "campaigns", cs)
    return camp


def delete_campaign(c, cid):
    _put(c, "campaigns", [x for x in _all(c) if x["id"] != cid])
    if c.setting("campaign:active") == cid:
        _put(c, "campaign:active", "")
    return {"deleted": cid}


def start_campaign(c, cid, control, passphrase=""):
    """run only the campaign's selection (other harvesters stop); its Google tools switch on (admin)"""
    cs = _all(c)
    camp = next((x for x in cs if x["id"] == cid), None)
    if not camp:
        raise ValueError("No such campaign.")
    if camp["tools"]:
        c.approvals._require(passphrase or "")
        if not source_approved(c):
            raise ValueError("This campaign uses Google tools: approve the source “Google Gemini API — generated exemplars” first.")
    if camp["apps"] or camp["harvesters"]:
        control("start", "selected", camp["apps"], camp["harvesters"])
    else:
        control("stop", "all", [], [])                           # a tools-only campaign: harvesting rests …
        with c.store.write() as db:
            c.set_setting("harvest:master", "running", db)        # … but the master stays on so the tools may run
    with c.store.write() as db:
        for t in GOOGLE_TOOLS:
            _put(c, "gtool:%s" % t, "on" if t in camp["tools"] else "off", db)
    camp.update(status="running", started=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), stopped=None,
                mark=c.store.scalar("SELECT max(id) FROM harvest_log", default=0) or 0)
    _put(c, "campaigns", cs)
    _put(c, "campaign:active", cid)
    return status(c)


def stop_campaign(c, cid, control):
    cs = _all(c)
    camp = next((x for x in cs if x["id"] == cid), None)
    if not camp:
        raise ValueError("No such campaign.")
    if camp["apps"] or camp["harvesters"]:
        control("stop", "selected", camp["apps"], camp["harvesters"])
    with c.store.write() as db:
        for t in camp["tools"]:
            _put(c, "gtool:%s" % t, "off", db)
    camp.update(status="stopped", stopped=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    _put(c, "campaigns", cs)
    if c.setting("campaign:active") == cid:
        _put(c, "campaign:active", "")
    return status(c)


def master(c, on, control):
    """the master On/Off: everything starts (every application and approved harvester; Google tools as switched) or stops"""
    control("start" if on else "stop", "all", [], [])
    if not on:
        cs = _all(c)
        for camp in cs:
            if camp.get("status") == "running":
                camp.update(status="stopped", stopped=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        _put(c, "campaigns", cs)
        _put(c, "campaign:active", "")
    return status(c)


def _progress(c, camp):
    if not camp.get("mark") and camp.get("mark") != 0:
        return None
    m = int(camp.get("mark") or 0)
    rows = c.store.query("""SELECT action, app, sum(new) AS new, sum(items) AS items, count(*) AS tasks, sum(decision = 'failed') AS failed
                            FROM harvest_log WHERE id > ? AND action NOT LIKE 'bulk:%' GROUP BY action, app""", (m,))   # bulk agents run outside campaigns
    per_h = {h: {"new": 0, "items": 0, "tasks": 0, "failed": 0} for h in camp["harvesters"]}
    per_a = {a: {"new": 0, "tasks": 0} for a in camp["apps"]}
    for r in rows:
        name = r["action"].split(":", 1)[1] if r["action"].startswith("online:") else None
        if name in per_h:
            per_h[name] = {k: r[k] or 0 for k in ("new", "items", "tasks", "failed")}
        if r["app"] in per_a and not name:
            per_a[r["app"]]["new"] += r["new"] or 0; per_a[r["app"]]["tasks"] += r["tasks"] or 0
    takes = 0
    try:
        import qbexemplar
        lib = qbexemplar.Library(os.path.join(c.folder, "exemplars"))
        models = {GOOGLE_TOOLS[t]["model"] for t in camp["tools"]}
        takes = sum(1 for x in lib.list() if x["origin"].get("model") in models and x["added"] >= (camp.get("started") or "9"))
    except Exception:
        pass
    new = sum(v["new"] for v in per_h.values()) + sum(v["new"] for v in per_a.values())
    return {"new_facts": new, "harvesters": per_h, "apps": per_a, "exemplar_takes": takes,
            "goal_reached": bool(camp.get("goal")) and new >= int(camp["goal"])}


def status(c):
    cs = _all(c)
    for camp in cs:
        camp["progress"] = _progress(c, camp)
    return {"version": VERSION, "master": "running" if master_running(c) else "stopped", "active": c.setting("campaign:active") or None,
            "campaigns": cs, "tools": tools(c), "source": {"key": SOURCE_KEY, "approved": source_approved(c)}, "runner": runner_status(c)}


def add_routes(api, c, control, known_harvesters, program_dir=None):
    g, p = api.get, api.post

    def guard(fn):
        def run(q):
            try:
                return fn(q)
            except ValueError as e:
                import qbcore as core
                raise core.UserError(str(e))
        return run
    g("/api/campaigns")(lambda q: status(c))
    p("/api/campaigns/save")(guard(lambda q: {"campaign": save_campaign(c, q, known_harvesters()), **status(c)}))
    p("/api/campaigns/delete")(guard(lambda q: (delete_campaign(c, q.get("id")), status(c))[1]))
    p("/api/campaigns/start")(guard(lambda q: start_campaign(c, q.get("id"), control, q.get("passphrase"))))
    p("/api/campaigns/stop")(guard(lambda q: stop_campaign(c, q.get("id"), control)))
    p("/api/harvest/master")(guard(lambda q: master(c, q.get("on") in (True, "true", "on", 1), control)))
    p("/api/gtools/runner")(guard(lambda q: runner(c, q.get("action"), q.get("passphrase"), program_dir)))
    p("/api/gtools/switch")(guard(lambda q: {"tools": set_tool(c, q.get("id"), q.get("on") in (True, "true", "on", 1), q.get("passphrase"),
                                                                q.get("plan") if "plan" in q else None)}))


def attach(app, program_dir=None):
    """the Harvesting page's campaigns, master switch and Google tools (applications: the team's own start/stop)"""
    try:
        import qbcommons as cm
        import qbonline as ol
        team, c = getattr(app, "team", None), getattr(app, "commons", None)
        if team is None or c is None:
            return None
        control = lambda action, scope, apps, harvesters: cm.harvest_control(team, action, scope, apps, harvesters)
        add_routes(app.api, c, control, lambda: set(ol.HARVESTERS), program_dir)
        return True
    except Exception as e:
        log = getattr(app, "log", None)
        if log:
            log("harvest campaigns unavailable:", repr(e))
        return None
