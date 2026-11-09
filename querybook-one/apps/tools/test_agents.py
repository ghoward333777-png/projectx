#!/usr/bin/env python3
"""Agent hub: every sense agent, learning from exemplars (profile, scoring, advice, adoption), the non-LLM guard,
Open Claw skills from a ClawHub-compatible registry (search, full index, zip import), an Open Claw installation on
disk (agents, skills, tools; secrets never read; model instructions quarantined), uploads, live feeds and devices."""
import base64, io, json, math, os, struct, sys, tempfile, threading, wave, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "_core"))
import qbcore as core

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [OK]", name)
    else:
        FAIL += 1
        print("  [FAIL]", name, detail)


def wav(segments, sr=16000):
    """segments: (seconds, pitch_hz or 0 for silence, amplitude)."""
    import array
    a = array.array("h")
    t = 0
    for dur, f0, amp in segments:
        for i in range(int(dur * sr)):
            env = 0.6 + 0.4 * math.sin(2 * math.pi * 4.5 * i / sr) ** 2       # syllable-like loudness pulses
            v = amp * env * (math.sin(2 * math.pi * f0 * i / sr) + 0.5 * math.sin(4 * math.pi * f0 * i / sr)) if f0 else 0
            a.append(int(max(-32767, min(32767, v * 32767 + ((i * 7919) % 13 - 6)))))
        t += dur
    b = io.BytesIO()
    w = wave.open(b, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(a.tobytes()); w.close()
    return base64.b64encode(b.getvalue()).decode()


SKILL_MD = """---
name: weather-brief
description: Give a short weather briefing from a public forecast.
version: 1.2.0
metadata: {"openclaw": {"requires": {"bins": ["curl", "jq"], "env": ["WX_KEY"]}, "emoji": "x"}}
---
# Weather brief

You are a friendly weather assistant. Always respond with a cheerful tone.

## Steps
1. Fetch the forecast for the user's city.
2. Report temperature, wind and rain probability.
- Round temperatures to whole degrees.

```bash
curl -s https://api.weather.example/forecast?city=Oslo | jq .daily
```

Forecasts come from https://www.yr.no and are updated hourly.
Think step by step before you answer.
"""


def skill_zip(extra=None):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("weather-brief/SKILL.md", SKILL_MD)
        z.writestr("weather-brief/scripts/fetch.sh", "#!/bin/sh\ncurl -s $1\n")
        z.writestr("weather-brief/reference.md", "# Units\n- Wind in metres per second.\n- Ask the model to be concise.\n")
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return b.getvalue()


class FakeHub(BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data))); self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        from urllib.parse import urlsplit, parse_qs
        u = urlsplit(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        FakeHub.hits.append((u.path, q, self.headers.get("User-Agent")))
        if u.path == "/api/v1/search":
            return self._send(200, {"results": [{"slug": "weather-brief", "displayName": "Weather brief", "summary": "Weather", "version": "1.2.0", "ownerHandle": "wx"}]})
        if u.path == "/api/v1/skills":
            page = int(q.get("cursor") or 0)
            items = [{"slug": "s%d-%d" % (page, i), "displayName": "Skill %d-%d" % (page, i), "summary": "x", "latestVersion": {"version": "1.0.0"}} for i in range(3)]
            return self._send(200, {"items": items, "nextCursor": str(page + 1) if page < 2 else None})
        if u.path == "/api/v1/skills/weather-brief":
            return self._send(200, {"skill": {"slug": "weather-brief"}, "latestVersion": {"version": "1.2.0"}, "owner": {"handle": "wx"}})
        if u.path == "/api/v1/skills/bad-skill":
            return self._send(200, {"skill": {"slug": "bad-skill"}, "moderation": {"status": "flagged"}})
        if u.path == "/api/v1/download":
            return self._send(200, skill_zip(), "application/zip")
        if u.path == "/feed.json":
            return self._send(200, {"data": {"price": [1.0, 2.5]}})
        return self._send(404, b"not found", "text/plain")


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeHub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    os.environ["QB_CLAWHUB"] = base
    import qbagents as A
    A.CLAWHUB = base
    d = tempfile.mkdtemp()
    hub = A.Hub(d, "test")

    print("Senses")
    t1 = "You can do this. Start small! Then build a habit, one day at a time. Why wait? The best time is now, and the second best is tomorrow."
    f, _ = A.analyse("text", {"text": " ".join([t1] * 3)})
    check("text: sentences, questions, addressing the reader, reading ease", f["sentences"] == 15 and f["question_pct"] > 15 and f["you_per_100"] > 2 and 40 < f["reading_ease"] < 120, f)
    doc = io.BytesIO()
    with zipfile.ZipFile(doc, "w") as z:                          # a minimal .docx
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' +
                   "".join('<w:p><w:r><w:t>%s</w:t></w:r></w:p>' % s for s in ["The committee met on Tuesday.", "It was decided that the plan would be approved.", "We start in May."]) + "</w:body></w:document>")
    f2, det = A.analyse("text", {"file_b64": base64.b64encode(doc.getvalue()).decode(), "name": "minutes.docx"})
    check("text: any document through the Artifact Segmenter (Word here), passive voice found", det["format"] == "Word document" and f2["passive_pct"] > 0, (det, f2))
    calm = wav([(0.9, 180, .3), (0.6, 0, 0), (0.9, 200, .3), (0.6, 0, 0), (0.9, 170, .3), (0.6, 0, 0), (0.9, 210, .3)])
    rush = wav([(4.5, 150, .3)])
    fa, _ = A.analyse("audio", {"wav_b64": calm})
    fb, _ = A.analyse("audio", {"wav_b64": rush})
    check("audio: pauses found and timed, phrases measured", fa["pauses_per_min"] > 20 and 0.45 < fa["pause_mean_s"] < 0.75 and fb["pause_pct"] < 3, (fa, fb))
    check("audio: pitch found (melody wider when the voice moves)", 140 < fa["pitch_median_hz"] < 230 and fa["pitch_range_st"] > fb["pitch_range_st"], (fa, fb))
    frames = [{"motion": (8 if (i // 6) % 2 else 0.4) + (60 if i == 40 else 0), "bright": 120, "contrast": 40, "sat": 30, "smile": 0.2 + 0.1 * (i % 2)} for i in range(120)]
    fv, _ = A.analyse("video", {"frames": frames, "fps": 12})
    check("video: movement, stillness, a cut, rhythm, extra channels", fv["still_pct"] > 30 and fv["cuts_per_min"] > 0 and 0.8 < fv["motion_period_s"] < 1.2 and "smile.mean" in fv, fv)
    pts = [{"stroke": s, "t": s * 600 + i * 16, "x": 0.1 + i * 0.01, "y": 0.5 + 0.002 * i * i, "p": 0.4 + 0.05 * (i % 3)} for s in range(10) for i in range(20)]
    ft, _ = A.analyse("touch", {"points": pts, "force": [0, 1, 3, 6, 6, 5, 2, 0] * 5, "rate_hz": 20})
    check("touch: pressure, speed, smoothness, rhythm, force build-up", 0.4 < ft["pressure_mean"] < 0.5 and ft["rhythm_cv"] < 0.05 and ft["strokes_per_min"] > 50 and ft["force_peak_n"] >= 5 and ft["force_rise_n_s"] > 0, ft)
    acc = [9.8 + 2 * math.sin(2 * math.pi * 1.8 * i / 50) for i in range(500)]
    fm, _ = A.analyse("motion", {"acc": acc, "rate_hz": 50, "heart": [70, 72, 75], "fixations_ms": [200, 300]})
    check("body motion: cadence found from accelerometer, heart rate, gaze", 1.6 < fm["cadence_hz"] < 2.0 and fm["heart_mean"] > 70 and fm["fixation_ms_mean"] == 250, fm)
    fs, _ = A.analyse("sensor", {"csv": "time,ethanol,temp\n" + "\n".join("%d,%f,%f" % (i, 0.1 * i, 20 + math.sin(i)) for i in range(40)), "rate_hz": 1})
    check("any sensor: channels from CSV (time column skipped), trend", "ethanol.trend_per_s" in fs and abs(fs["ethanol.trend_per_s"] - 0.1) < 1e-6 and "time.mean" not in fs, fs)

    print("Learning from best-in-class exemplars")
    sk = hub.add_skill("Motivational writing", "text")
    masters = ["You can start today. Pick one small step! Why wait for perfect? Your future self will thank you, so begin now.",
               "Start where you are. Use what you have! What is stopping you? You already know the first step, so take it.",
               "Begin with one page. Then another! Where will you be in a year? You decide, today, with this next small step."]
    for i, m in enumerate(masters):
        r = hub.add_exemplar(sk["id"], "Master %d" % i, {"text": m}, "own", performer="Coach %d" % i, rating=5)
    check("exemplars build a profile with ranges and importance", r["profile"]["version"] == 3 and r["profile"]["measures"] >= 10, r["profile"])
    dup = hub.add_exemplar(sk["id"], "again", {"text": masters[0]}, "own")
    check("the same exemplar twice is kept once", dup["duplicate"])
    try:
        hub.add_exemplar(sk["id"], "x", {"text": masters[0]}, "")
        nolic = False
    except core.UserError:
        nolic = True
    check("an exemplar needs its licence (own, public domain, CC, government, permission)", nolic)
    good = hub.sample(sk["id"], {"text": "Start now. One step is enough! Why delay? You can do it, so go today and keep going."})
    bad = hub.sample(sk["id"], {"text": "It was decided by the committee that the implementation of the aforementioned organisational restructuring "
                                         "would be postponed until further consideration of the documentation had been completed by the relevant departments."})
    check("a sample like the masters scores high; an unlike one low", good["overall"] > bad["overall"] + 25 and good["overall"] >= 60, (good["overall"], bad["overall"]))
    check("advice names the measures furthest from the masters and the direction", bad["advice"] and any(k in a["text"] for a in bad["advice"] for k in ("shorter sentences", "active voice", "cut long words", "plainer")), bad["advice"])
    check("the closest exemplar is named", bad["closest_exemplar"] and bad["closest_exemplar"]["title"].startswith("Master"))
    check("deterministic: the same sample scores the same", hub.sample(sk["id"], {"text": "Start now. One step is enough! Why delay? You can do it, so go today and keep going."}, keep=False)["overall"] == good["overall"])
    pr = hub.profile(sk["id"])
    check("profiles are candidates until adopted", pr["status"].startswith("candidate"))
    hub.adopt(sk["id"], pr["version"])
    check("adopting a profile", hub.profile(sk["id"])["status"] == "adopted")
    check("samples are listed with their scores", len(hub.samples(sk["id"])) == 2)

    print("Pick and choose; the non-LLM commitment")
    hub.pick("text", False)
    try:
        hub.sample(sk["id"], {"text": masters[0]})
        off = False
    except core.UserError as e:
        off = "switched off" in str(e)
    hub.pick("text", True)
    check("a switched-off agent refuses work", off)
    refused = []
    for u in ("https://api.openai.com/v1/chat/completions", "https://api.anthropic.com/v1/messages", "https://generativelanguage.googleapis.com/v1/models",
              "https://openrouter.ai/api", "http://localhost:11434/api/generate", "https://www.youtube.com/watch?v=x"):
        try:
            A.fetch(u)
        except core.UserError as e:
            refused.append("Refused" in str(e))
    check("AI-model services (and YouTube) are refused by every agent", refused == [True] * 6, refused)
    try:
        hub.add_feed("x", "https://api.openai.com/v1/models")
        fr = False
    except core.UserError:
        fr = True
    check("a live feed cannot point at an AI-model service", fr)
    pur = hub.purity()
    check("purity audit: no model imports, hosts blocked", pur["ok"] and pur["llm_hosts_blocked"] >= 20 and pur["agents_using_models"] == 0, pur)
    k, q = A.purify(SKILL_MD.split("---", 2)[2])
    check("model instructions are quarantined; steps, commands and links kept", any("You are a friendly" in x["line"] for x in q) and any("step by step" in x["line"] for x in q)
          and any("Report temperature" in s for s in k["steps"]) and any(c.startswith("curl") for c in k["commands"]) and "https://www.yr.no" in k["links"], (k, q))

    print("Open Claw: ClawHub registry")
    s = hub.claw_search("weather")
    check("search ClawHub", s["results"][0]["slug"] == "weather-brief")
    ix = hub.claw_sync_index()
    check("every ClawHub skill indexed, page by page (cursor)", ix["indexed"] == 9 and ix["complete"] and hub.claw_index("Skill 2")["total"] == 3, ix)
    check("polite: the registry sees QueryBook's user agent, suspicious skills filtered", all("QueryBook-AgentHub" in (h[2] or "") for h in FakeHub.hits)
          and any(h[1].get("nonSuspiciousOnly") == "true" for h in FakeHub.hits))
    im = hub.claw_import("weather-brief")
    pb = hub.playbook(im["id"])
    check("import a ClawHub skill: frontmatter, requirements, tools", pb["name"] == "weather-brief" and pb["version"] == "1.2.0" and pb["data"]["requires"]["bins"] == ["curl", "jq"]
          and "curl" in pb["data"]["tools"], pb["data"]["requires"])
    check("its scripts are listed, never run; its model lines quarantined", any(r.get("note", "").startswith("script") for r in pb["data"]["resources"]) and pb["quarantined"] >= 3
          and any("never executed" in w for w in pb["warnings"]))
    try:
        hub.claw_import("bad-skill")
        fl = False
    except core.UserError as e:
        fl = "flagged" in str(e)
    check("a skill ClawHub has flagged is refused", fl)
    check("importing the same skill again is not duplicated", hub.claw_import("weather-brief")["duplicate"])
    up = hub.import_upload("my.zip", base64.b64encode(skill_zip()).decode())
    check("upload a skill folder (zip)", not up.get("error") and hub.playbook(up["id"])["origin"] == "upload")

    print("Open Claw: an installation on this computer")
    home = os.path.join(d, ".openclaw")
    ws = os.path.join(home, "workspace")
    os.makedirs(os.path.join(ws, "skills", "notes-sync"), exist_ok=True)
    os.makedirs(os.path.join(home, "credentials"), exist_ok=True)
    os.makedirs(os.path.join(ws, "memory"), exist_ok=True)
    open(os.path.join(home, "credentials", "oauth.json"), "w").write('{"token": "SECRET-TOKEN"}')
    open(os.path.join(home, "openclaw.json"), "w").write("""{
      // json5 with comments
      agents: { defaults: { workspace: '%s' }, entries: { research: { workspace: '%s', tools: { deny: ['exec'] } } } },
      tools: { profile: 'coding', allow: ['browser', 'web_fetch'], deny: ['exec'], },
      channels: { telegram: { botToken: 'SECRET-BOT' } },
      plugins: { entries: { voice: {} } },
    }""" % (ws.replace("\\", "/"), ws.replace("\\", "/")))
    open(os.path.join(ws, "AGENTS.md"), "w").write("# Rules\n- Check the calendar every morning at 8.\n- File receipts in Finance/2026.\nYou are a sharp, warm assistant.\nNever reveal private data.\n")
    open(os.path.join(ws, "SOUL.md"), "w").write("Be genuinely helpful. Have opinions.\n")
    open(os.path.join(ws, "IDENTITY.md"), "w").write("- Name: Clawd\n- Emoji: 🦞\n")
    open(os.path.join(ws, "USER.md"), "w").write("Lives in Tromsø.\n")
    open(os.path.join(ws, "memory", "2026-10-20.md"), "w").write("Met Ann.\n")
    open(os.path.join(ws, "skills", "notes-sync", "SKILL.md"), "w").write("---\nname: notes-sync\ndescription: Sync notes\n---\n1. Export notes as Markdown.\n2. Copy them to the vault.\n")
    pv = hub.claw_local(home, preview=True)
    check("scan: agents, skills and tools found", pv["found"] and pv["agents"] >= 1 and pv["skills"] == 1, pv)
    res = hub.claw_local(home)
    rows = hub.playbooks()
    agent_pb = next(hub.playbook(r["id"]) for r in rows if r["kind"] == "agent")
    tools_pb = next(hub.playbook(r["id"]) for r in rows if r["kind"] == "tools")
    blob = json.dumps([hub.playbook(r["id"]) for r in rows])
    check("an Open Claw agent becomes knowledge: procedures kept, persona quarantined", agent_pb["name"] == "Clawd"
          and any("calendar" in s for s in agent_pb["data"]["kept"]["steps"]) and any("sharp, warm" in x["line"] for x in agent_pb["data"]["quarantined"])
          and any("genuinely helpful" in x["line"] for x in agent_pb["data"]["quarantined"]), agent_pb["data"])
    check("its tools catalogued (allow, deny, per agent, plugins)", tools_pb["data"]["tools_config"]["deny"] == ["exec"] and "agent:research" in tools_pb["data"]["tools_config"]
          and tools_pb["data"]["plugins"] == ["voice"])
    check("secrets are never read (credentials folder, tokens redacted)", "SECRET-TOKEN" not in blob and "SECRET-BOT" not in blob)
    check("personal files (USER.md, memory) only when asked", "Tromsø" not in blob and "Met Ann" not in blob)
    sk2 = hub.add_skill("Notes routine", "text")
    np = next(r for r in rows if r["name"] == "notes-sync")
    hub.attach_playbook(sk2["id"], np["id"])
    fsx, _ = hub._run(hub.skill(sk2["id"]), {"text": "Export the notes as Markdown, then copy them into the vault. Done in five minutes."})
    check("a playbook attached to a skill: its terms are measured in samples", fsx.get("playbook_terms_pct", 0) > 50, fsx)
    hub.pick_playbook(np["id"], False)
    check("a playbook can be switched off (its terms are no longer used)", "playbook_terms_pct" not in hub._run(hub.skill(sk2["id"]), {"text": "Export the notes as Markdown now."})[0])
    hub.pick("claw", False)
    try:
        hub.claw_search("x")
        co = False
    except core.UserError:
        co = True
    hub.pick("claw", True)
    check("the Open Claw importer can be switched off", co)

    print("Live data and devices")
    fd = hub.add_feed("Price", base + "/feed.json", "data.price", 30)
    check("a live feed is read (JSON path, last value)", fd.get("value") == 2.5, fd)
    hub.poll(fd["id"])
    sk3 = hub.add_skill("Steady process", "live")
    r3 = hub.sample(sk3["id"], {"feed_id": fd["id"]}, keep=False)
    check("a live feed is measured by a skill", "Price.mean" in r3["features"], r3["features"])

    class Dev:
        def observations(self, kind=None, since=None, limit=0):
            return [{"value": "3.5"}, {"value": "4.5"}] if kind == "touch" else [{"value": "220"}]

        def minutes(self, kind=None, since=None, limit=0):
            return [{"mean": 10.5}, {"mean": 11.0}] if kind == "movement" else [{"mean": 72.0}]
    hub.devices = Dev()
    tch = hub.from_devices("touch")
    check("tactile sensors through the Device gateway become touch input", tch["force"] == [4.5, 3.5] and A.touch_features(tch)["force_mean_n"] == 4.0)
    mv = hub.from_devices("motion")
    check("body sensors through the Device gateway become motion input", mv["heart"] == [72.0] and A.motion_features(mv)["fixation_ms_mean"] == 220.0)

    print("Routes")
    api = core.Api()
    A.add_routes(api, hub)
    st = api.routes[("GET", "/api/agents/status")]({})
    check("status lists every agent as deterministic and model-free", len(st["agents"]) == len(A.AGENTS) and all(a["llm"] is False and a["deterministic"] for a in st["agents"]))
    an = api.routes[("POST", "/api/agents/analyse")]({"agent": "text", "input": {"text": t1}})
    check("analyse route", an["features"]["sentences"] == 5)
    srv.shutdown()
    print("\n%d of %d checks passed" % (PASS, PASS + FAIL))
    return FAIL == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
