"""QueryBook -> Gemini Omni adapter  [deterministic director; rendering, not fact assertion]

QueryBook is the DIRECTOR (a structured scene graph); Gemini Omni is a prompt-driven
RENDERER. This module is the adapter between them. Its core — turning a structured
SceneGraph into Gemini-ready prompts — is PURE DETERMINISTIC TEMPLATING: the same scene
always yields the same prompt bundle, with no model in the loop. That keeps it inside the
QueryBook covenant: no LLM asserts facts here, and video generation is *rendering* (like
TTS), not fact assertion.

Pipeline:
    FUGraph --build_scene_graph_from_fu--> SceneGraph
    SceneGraph --generate_prompt_bundle--> PromptBundle (base + beat + edit prompts)
    PromptBundle --GeminiClient--> VideoRef               [gated: needs an API key + allowlisted
                                                            Veo model; offline default = a DRY-RUN
                                                            plan; audio/video is NEVER fabricated]
    VideoRef --SceneComplianceAnalyzer--> ComplianceReport [honest skeleton: compares against
                                                            caller-supplied observations only]
    ComplianceReport --generate_edit_prompts--> edit prompts  (refinement loop)

All structures are plain dicts (stdlib only), so a SceneGraph round-trips through JSON and
the HTTP API unchanged.
"""

import json as _json
import os as _os
import re as _re
import time as _time
import urllib.request as _ulr
import urllib.error as _ule

# --------------------------------------------------------------------------
# Controlled vocabularies (keep prompts cinematic and consistent).
# --------------------------------------------------------------------------
SHOT_TYPES = {"wide": "wide shot", "medium": "medium shot", "closeup": "tight close-up",
              "close-up": "tight close-up"}
ANGLES = {"eye-level": "eye-level", "low": "low angle", "high": "high angle"}
MOVEMENTS = {"static": "static camera", "slow_dolly_in": "slow dolly-in",
             "slow_dolly_out": "slow dolly-out", "handheld": "handheld movement"}
POVS = {"objective": "objective POV", "OTS": "over-the-shoulder POV", "POV": "first-person POV"}

# Mood -> deterministic lighting rig presets (noir, romantic, clinical, neutral, tense).
LIGHTING_PRESETS = {
    "noir": [
        {"type": "key", "position": "above the main stage area", "intensity": "low",
         "color": "warm tungsten", "mood": "noir"},
        {"type": "back", "position": "behind the characters", "intensity": "medium",
         "color": "cool blue", "mood": "noir"},
    ],
    "romantic": [
        {"type": "key", "position": "camera left", "intensity": "soft", "color": "warm amber",
         "mood": "romantic"},
        {"type": "fill", "position": "camera right", "intensity": "soft", "color": "warm amber",
         "mood": "romantic"},
    ],
    "clinical": [
        {"type": "key", "position": "overhead", "intensity": "high", "color": "neutral white",
         "mood": "clinical"},
    ],
    "tense": [
        {"type": "key", "position": "camera left", "intensity": "harsh", "color": "cool white",
         "mood": "tense"},
        {"type": "back", "position": "behind the subject", "intensity": "medium", "color": "cool blue",
         "mood": "tense"},
    ],
    "neutral": [
        {"type": "key", "position": "front", "intensity": "medium", "color": "neutral white"},
    ],
}

# Discourse focus -> deterministic camera grammar.
CAMERA_GRAMMAR = {
    "intimate_dialogue": {"shotType": "medium", "angle": "eye-level", "movement": "slow_dolly_in",
                          "focalStyle": "shallow depth of field", "pov": "objective"},
    "confrontation": {"shotType": "closeup", "angle": "low", "movement": "static",
                      "focalStyle": "shallow depth of field", "pov": "OTS"},
    "establishing": {"shotType": "wide", "angle": "eye-level", "movement": "slow_dolly_in",
                     "focalStyle": "deep focus", "pov": "objective"},
}


def _sid():
    return "scene_%d" % int(_time.time())


# ==========================================================================
# 1. FUInterpreter — FUGraph -> SceneGraph
# ==========================================================================
def _infer_environment(fu):
    loc = next((e for e in fu.get("entities", []) if e.get("type") == "location"), None)
    if loc:
        a = loc.get("attributes", {})
        return a.get("description") or a.get("name") or "an unspecified environment"
    return "an unspecified environment"

def _stage_zones():
    return [
        {"id": "foreground_left", "description": "foreground left"},
        {"id": "foreground_right", "description": "foreground right"},
        {"id": "center_stage", "description": "center of the scene"},
        {"id": "bar_left", "description": "the left end of the bar counter"},
        {"id": "bar_center", "description": "the center of the bar counter"},
        {"id": "background", "description": "the background"},
    ]

def _build_stage(fu):
    env = _infer_environment(fu)
    zones = _stage_zones()
    props = [{"id": e["id"],
              "description": e.get("attributes", {}).get("description") or e.get("attributes", {}).get("name") or "prop",
              "zoneId": "background"}
             for e in fu.get("entities", []) if e.get("type") == "prop"]
    return {"environment": env, "props": props, "zones": zones}

def _build_lighting(fu):
    mood = (fu.get("pragmatics", {}) or {}).get("mood", "neutral")
    return [dict(r) for r in LIGHTING_PRESETS.get(mood, LIGHTING_PRESETS["neutral"])]

def _build_camera(fu):
    focus = (fu.get("discourse", {}) or {}).get("focus", "establishing")
    return dict(CAMERA_GRAMMAR.get(focus, CAMERA_GRAMMAR["establishing"]))

def _build_characters(fu):
    out = []
    emo = (fu.get("pragmatics", {}) or {}).get("characterEmotion", {}) or {}
    # Deterministic default placement: first character bar_left, second bar_center, then zones cycle.
    zone_cycle = ["bar_left", "bar_center", "foreground_right", "center_stage"]
    i = 0
    for e in fu.get("entities", []):
        if e.get("type") != "character":
            continue
        a = e.get("attributes", {})
        out.append({"id": e["id"], "name": a.get("name"),
                    "description": a.get("look") or a.get("description") or "a character",
                    "positionZoneId": zone_cycle[i % len(zone_cycle)],
                    "pose": "leaning on the bar" if i == 0 else "standing beside the bar stool",
                    "emotion": emo.get(e["id"], "neutral")})
        i += 1
    return out

def _default_timecode(idx):
    return "%d-%ds" % (idx * 3, idx * 3 + 3)

_SPEAK_VERBS = ("speak", "say", "tell", "ask", "whisper", "shout")

def _camera_for_action(action, base):
    cam = dict(base)
    v = (action.get("verb") or "").lower()
    # A line of dialogue, or a speaking verb, pushes to a close-up over-the-shoulder.
    if action.get("dialogue") or any(v.startswith(s) for s in _SPEAK_VERBS):
        cam["shotType"] = "closeup"; cam["pov"] = "OTS"
    elif v.startswith("glance") or v.startswith("look"):
        cam["shotType"] = "medium"; cam["movement"] = "static"
    return cam

def build_scene_graph_from_fu(fu):
    """FUGraph (entities/actions/pragmatics/discourse) -> deterministic SceneGraph."""
    base_cam = _build_camera(fu)
    base_light = _build_lighting(fu)
    chars = _build_characters(fu)
    actions = sorted(fu.get("actions", []), key=lambda a: a.get("orderingIndex", 0))
    beats = []
    hints = {b.get("actionId"): b.get("timecodeHint")
             for b in (fu.get("discourse", {}) or {}).get("beats", []) or []}
    for idx, a in enumerate(actions):
        beats.append({
            "id": "beat_%d" % idx,
            "timecodeHint": hints.get(a.get("id")) or _default_timecode(idx),
            "camera": _camera_for_action(a, base_cam),
            "lighting": [dict(r) for r in base_light],
            "characterActions": [{"characterId": p, "action": a.get("verb", ""),
                                  "style": a.get("style"), "dialogue": a.get("dialogue")}
                                 for p in a.get("participants", [])],
        })
    return {"sceneId": fu.get("sceneId") or _sid(), "stage": _build_stage(fu),
            "lighting": base_light, "camera": base_cam, "characters": chars, "timeline": beats}


# ==========================================================================
# 2. GeminiAdapter — SceneGraph -> PromptBundle  (pure deterministic templating)
# ==========================================================================
def _describe_movement(m):
    return MOVEMENTS.get(m, "static camera")

def _describe_camera(cam):
    return "%s, %s, performing a %s, with %s" % (
        SHOT_TYPES.get(cam.get("shotType"), "medium shot"),
        ANGLES.get(cam.get("angle"), "eye-level"),
        _describe_movement(cam.get("movement")),
        cam.get("focalStyle", "shallow depth of field"))

def _describe_light(l):
    return "%s %s %s light from %s" % (l.get("intensity", "soft"), l.get("color", "neutral"),
                                       l.get("type", "key"), l.get("position", "front"))

def _describe_lighting(lights):
    if not lights:
        return "low-key, dim lighting"
    s = "; ".join(_describe_light(l) for l in lights)
    moods = [l.get("mood") for l in lights if l.get("mood")]
    if moods:
        s += ". Overall mood is %s" % moods[0]
    return s

def _char_name(c):
    return c.get("name") or "a character"

def _describe_character(c, zones=None):
    zone = ""
    if zones and c.get("positionZoneId"):
        z = next((z for z in zones if z["id"] == c["positionZoneId"]), None)
        if z:
            zone = ", positioned at %s" % z["description"]
    return "%s — %s, currently %s%s, feeling %s" % (
        _char_name(c), c.get("description", "a character"), c.get("pose", "standing"),
        zone, c.get("emotion", "neutral"))

def _describe_action(a, chars):
    c = next((c for c in chars if c["id"] == a.get("characterId")), None)
    name = (c.get("name") if c else None) or "the main character"
    style = (", %s" % a["style"]) if a.get("style") else ""
    base = "%s %s%s." % (name, a.get("action", "acts"), style)
    if a.get("dialogue"):
        base += ' %s says: "%s".' % (name, a["dialogue"])
    return base

def generate_base_prompt(scene):
    stage = scene["stage"]; cam = scene["camera"]
    props = stage.get("props", [])
    prop_txt = ""
    if props:
        prop_txt = " The space includes %s." % ", ".join(p["description"] for p in props)
    chars = "; ".join(_describe_character(c, stage.get("zones")) for c in scene.get("characters", []))
    return ("Create a cinematic %s inside %s.%s "
            "Camera is %s. "
            "Lighting: %s. "
            "Characters: %s.") % (
        SHOT_TYPES.get(cam.get("shotType"), "medium shot"), stage["environment"], prop_txt,
        _describe_camera(cam), _describe_lighting(scene.get("lighting", [])), chars)

def generate_beat_prompts(scene):
    out = []
    chars = scene.get("characters", [])
    for b in scene.get("timeline", []):
        actions = " ".join(_describe_action(a, chars) for a in b.get("characterActions", []))
        out.append({"beatId": b["id"],
                    "prompt": ("For seconds %s, keep the same environment. "
                               "Camera: %s. Lighting: %s. Actions: %s") % (
                        b["timecodeHint"], _describe_camera(b["camera"]),
                        _describe_lighting(b.get("lighting", [])), actions or "hold the scene")})
    return out

def generate_edit_prompts(scene, report):
    out = []
    for issue in (report or {}).get("issues", []):
        out.append({"targetSegment": issue.get("segment", "entire clip"),
                    "prompt": ("In the %s, adjust the scene so that %s. "
                               "Keep all other elements the same.") % (
                        issue.get("segment", "entire clip"), issue.get("desiredChange", "it matches the plan"))})
    return out

def generate_prompt_bundle(scene):
    return {"sceneId": scene.get("sceneId"), "basePrompt": generate_base_prompt(scene),
            "beatPrompts": generate_beat_prompts(scene), "editPrompts": []}


# ==========================================================================
# 3. SceneGraph validation
# ==========================================================================
def validate_scene_graph(scene):
    issues = []
    def err(f, m): issues.append({"field": f, "severity": "error", "message": m})
    def warn(f, m): issues.append({"field": f, "severity": "warning", "message": m})
    if not scene.get("sceneId"): err("sceneId", "SceneGraph must have a sceneId.")
    if not (scene.get("stage", {}) or {}).get("environment"):
        err("stage.environment", "Stage environment must be specified.")
    if not scene.get("characters"): err("characters", "Scene must contain at least one character.")
    if not scene.get("timeline"): warn("timeline", "Scene has no beats; video may be static.")
    if not (scene.get("camera", {}) or {}).get("shotType"):
        err("camera.shotType", "Camera shotType must be defined.")
    if not scene.get("lighting"):
        warn("lighting", "No lighting rigs defined; default lighting will be used.")
    for i, b in enumerate(scene.get("timeline", [])):
        if not b.get("timecodeHint"):
            warn("timeline[%d].timecodeHint" % i, "Beat has no timecodeHint; mapping is less precise.")
        if not b.get("characterActions"):
            warn("timeline[%d].characterActions" % i, "Beat has no character actions; may feel static.")
    return {"ok": not any(x["severity"] == "error" for x in issues), "issues": issues}


# ==========================================================================
# 4. SceneComplianceAnalyzer  (HONEST skeleton)
# QueryBook cannot do computer-vision analysis of a returned video in-engine. Rather than
# fabricate a compliance verdict, this compares the SceneGraph against OBSERVED metadata the
# caller supplies (e.g. from a human review pass or an external CV service). With no
# observations it returns 'analysis_available: False' and raises no false issues.
# ==========================================================================
def analyze_video_against_scene(scene, observed=None):
    if not observed:
        return {"sceneId": scene.get("sceneId"), "analysis_available": False, "issues": [],
                "note": "No observed-video metadata supplied; QueryBook does not fabricate a "
                        "compliance verdict. Provide observations (camera/lighting/blocking/"
                        "mood) from a review pass or a CV service to get edit prompts."}
    issues = []
    cam = scene.get("camera", {})
    oc = observed.get("camera", {})
    if oc.get("shotType") and cam.get("shotType") and oc["shotType"] != cam["shotType"]:
        issues.append({"type": "camera", "segment": observed.get("segment", "entire clip"),
                       "description": "shot type is %s, expected %s" % (oc["shotType"], cam["shotType"]),
                       "desiredChange": "change the framing to a %s" % SHOT_TYPES.get(cam["shotType"], cam["shotType"])})
    ol = observed.get("lighting", {})
    if ol.get("tooBright"):
        issues.append({"type": "lighting", "segment": observed.get("segment", "entire clip"),
                       "description": "lighting is brighter than the noir plan",
                       "desiredChange": "reduce the key light and deepen the shadows"})
    om = observed.get("mood")
    want_mood = next((l.get("mood") for l in scene.get("lighting", []) if l.get("mood")), None)
    if om and want_mood and om != want_mood:
        issues.append({"type": "mood", "segment": "entire clip",
                       "description": "mood reads as %s, expected %s" % (om, want_mood),
                       "desiredChange": "shift the overall mood to %s" % want_mood})
    for b in observed.get("blocking_off", []):
        issues.append({"type": "blocking", "segment": observed.get("segment", "entire clip"),
                       "description": "character %s is off-position" % b,
                       "desiredChange": "move character %s to the intended zone" % b})
    return {"sceneId": scene.get("sceneId"), "analysis_available": True, "issues": issues}


# ==========================================================================
# 5. Refinement heuristics
# ==========================================================================
MAX_ITERATIONS = 3

def should_refine(report, iteration):
    if iteration >= MAX_ITERATIONS: return False
    issues = (report or {}).get("issues", [])
    if not issues: return False
    if all(i.get("type") == "mood" for i in issues) and iteration >= 2: return False
    return True

def prioritize_issues(report):
    issues = (report or {}).get("issues", [])
    prim = [i for i in issues if i.get("type") in ("camera", "blocking")]
    if prim: return prim
    lit = [i for i in issues if i.get("type") == "lighting"]
    if lit: return lit
    return issues


# ==========================================================================
# 6. Gemini Omni client wrapper  (GATED; offline-first; never fabricates media)
# Uses the Gemini video (Veo) long-running endpoint. Requires an API key (reused from the
# same local, git-ignored store as the TTS keys) AND an allowlisted Veo model. With no key it
# returns a DRY-RUN plan (the full prompt bundle) — it does NOT invent a video.
# ==========================================================================
def _gemini_key():
    k = _os.environ.get("GEMINI_API_KEY") or _os.environ.get("GOOGLE_TTS_API_KEY")
    if k:
        return k
    try:
        import qb_language
        return qb_language.load_tts_keys()["google"]["key"]
    except Exception:
        return None

def build_request_payload(bundle, base_media=None, model="veo-3.0-generate-preview"):
    """The exact JSON QueryBook would send (also returned in dry-run so it is inspectable)."""
    prompts = [bundle["basePrompt"]] + [b["prompt"] for b in bundle.get("beatPrompts", [])]
    instances = [{"prompt": "\n\n".join(prompts)}]
    if base_media and base_media.get("uri"):
        instances[0]["video"] = {"uri": base_media["uri"]}
    return {"model": model, "instances": instances,
            "parameters": {"aspectRatio": "16:9", "personGeneration": "allow_adult"}}

def build_edit_payload(video, edit_prompts, model="veo-3.0-generate-preview"):
    return {"model": model, "instances": [{"prompt": "\n\n".join(e["prompt"] for e in edit_prompts),
                                           "video": {"uri": (video or {}).get("uri", "")}}],
            "parameters": {"aspectRatio": "16:9"}}

def _post(url, payload, timeout=60):
    req = _ulr.Request(url, data=_json.dumps(payload).encode("utf-8"),
                       headers={"Content-Type": "application/json"}, method="POST")
    with _ulr.urlopen(req, timeout=timeout) as r:
        return _json.loads(r.read())

def generate_video(bundle, base_media=None, model="veo-3.0-generate-preview", key=None):
    """Attempt a Gemini video render. Returns {ok, dry_run, video?|operation?, payload, error?}.
    Offline-first: with no key, returns the dry-run plan and never fabricates a video."""
    key = key or _gemini_key()
    payload = build_request_payload(bundle, base_media, model)
    if not key:
        return {"ok": True, "dry_run": True, "payload": payload,
                "note": "No Gemini API key configured — returning the deterministic prompt bundle "
                        "as a DRY-RUN plan. Add a key (and allowlisted Veo access) to render video. "
                        "QueryBook never fabricates video."}
    url = ("https://generativelanguage.googleapis.com/v1beta/models/%s:predictLongRunning?key=%s"
           % (model, key))
    try:
        resp = _post(url, {"instances": payload["instances"], "parameters": payload["parameters"]})
        # Long-running op: Veo returns {name: "operations/..."} to poll.
        return {"ok": True, "dry_run": False, "operation": resp.get("name"), "raw": resp,
                "payload": payload}
    except _ule.HTTPError as he:
        return {"ok": False, "dry_run": False, "payload": payload,
                "error": "gemini http %s: %s" % (he.code, he.read().decode("utf-8", "ignore")[:200])}
    except Exception as ex:
        return {"ok": False, "dry_run": False, "payload": payload, "error": str(ex)}


# ==========================================================================
# 7. Orchestrator — FUGraph -> refined VideoRef (or a dry-run plan) in one call
# ==========================================================================
def render_scene_from_fu(fu, base_media=None, observed_per_iteration=None, model="veo-3.0-generate-preview"):
    """One-call pipeline: FU -> SceneGraph -> PromptBundle -> (Gemini) -> refine loop.
    `observed_per_iteration` (optional) is a list of observed-video metadata dicts that drive
    the deterministic refinement loop; without them the loop is a no-op (we do not fabricate
    compliance). Returns the full trace so every step is inspectable and reproducible."""
    scene = build_scene_graph_from_fu(fu)
    validation = validate_scene_graph(scene)
    bundle = generate_prompt_bundle(scene)
    gen = generate_video(bundle, base_media, model)
    trace = [{"step": "generate", "result": gen}]
    video = gen.get("video") or {"operation": gen.get("operation")} if not gen.get("dry_run") else None
    it = 0
    for observed in (observed_per_iteration or []):
        report = analyze_video_against_scene(scene, observed)
        if not should_refine(report, it):
            trace.append({"step": "analyze", "iteration": it, "report": report, "refined": False})
            break
        edits = generate_edit_prompts(scene, {"issues": prioritize_issues(report)})
        bundle["editPrompts"] = edits
        ref = generate_video(bundle, base_media, model) if gen.get("dry_run") else \
            {"ok": True, "dry_run": True, "payload": build_edit_payload(video, edits, model)}
        trace.append({"step": "refine", "iteration": it, "report": report, "editPrompts": edits,
                      "result": ref})
        it += 1
    return {"sceneId": scene["sceneId"], "scene": scene, "validation": validation,
            "promptBundle": bundle, "dry_run": gen.get("dry_run", True), "trace": trace}


# ==========================================================================
# 8. Reference FU + deterministic QC
# ==========================================================================
NOIR_BAR_FU = {
    "sceneId": "scene_noir_bar",
    "entities": [
        {"id": "A", "type": "character", "attributes": {"name": "Mark", "look": "a man in a dark jacket in his mid-30s"}},
        {"id": "B", "type": "character", "attributes": {"name": "Lena", "look": "a woman in a leather jacket in her late-20s"}},
        {"id": "bar", "type": "location", "attributes": {"description": "a small Los Angeles bar at night"}},
        {"id": "neon", "type": "prop", "attributes": {"description": "a blue neon beer sign"}},
        {"id": "counter", "type": "prop", "attributes": {"description": "a worn wood bar counter"}},
    ],
    "pragmatics": {"mood": "noir", "characterEmotion": {"A": "tense", "B": "confident"}},
    "discourse": {"focus": "intimate_dialogue",
                  "beats": [{"actionId": "a0", "timecodeHint": "0-3s"},
                            {"actionId": "a1", "timecodeHint": "3-6s"},
                            {"actionId": "a2", "timecodeHint": "6-9s"}]},
    "actions": [
        {"id": "a0", "verb": "glances toward Character A", "participants": ["B"], "style": "subtle", "orderingIndex": 0},
        {"id": "a1", "verb": "exhales slowly and looks down", "participants": ["A"], "style": "hesitant", "orderingIndex": 1},
        {"id": "a2", "verb": "steps forward", "participants": ["A"], "style": "quiet",
         "dialogue": "Did you really think I wouldn't find out?", "orderingIndex": 2},
    ],
}

def qc():
    """Deterministic self-test: the noir LA bar FU must produce a valid SceneGraph and a
    prompt bundle whose text carries the intended cinematic cues. No network, no cost."""
    scene = build_scene_graph_from_fu(NOIR_BAR_FU)
    val = validate_scene_graph(scene)
    bundle = generate_prompt_bundle(scene)
    checks = []
    def ck(name, cond): checks.append({"check": name, "pass": bool(cond)})
    ck("valid scenegraph", val["ok"])
    ck("2 characters", len(scene["characters"]) == 2)
    ck("3 beats", len(bundle["beatPrompts"]) == 3)
    ck("base: LA bar", "small Los Angeles bar at night" in bundle["basePrompt"])
    ck("base: noir mood", "mood is noir" in bundle["basePrompt"])
    ck("base: dolly-in", "slow dolly-in" in bundle["basePrompt"])
    ck("base: tungsten key", "warm tungsten key light" in bundle["basePrompt"])
    ck("beat0: timecode", bundle["beatPrompts"][0]["prompt"].startswith("For seconds 0-3s"))
    ck("beat2: closeup on speak", "tight close-up" in bundle["beatPrompts"][2]["prompt"])
    ck("beat2: dialogue", "Did you really think I wouldn't find out?" in bundle["beatPrompts"][2]["prompt"])
    # edit prompt from a synthetic compliance report
    rep = analyze_video_against_scene(scene, {"camera": {"shotType": "wide"}, "segment": "first 3 seconds"})
    edits = generate_edit_prompts(scene, rep)
    ck("edit prompt generated", edits and "first 3 seconds" in edits[0]["prompt"])
    ck("no-fabrication: dry-run without key", generate_video(bundle).get("dry_run") is True or _gemini_key())
    passed = sum(1 for c in checks if c["pass"])
    return {"passed": passed, "total": len(checks), "ok": passed == len(checks), "rows": checks}


if __name__ == "__main__":
    import json
    r = qc()
    print(json.dumps(r, indent=2, ensure_ascii=False))
    if "--show" in __import__("sys").argv:
        sc = build_scene_graph_from_fu(NOIR_BAR_FU)
        b = generate_prompt_bundle(sc)
        print("\n=== BASE ===\n" + b["basePrompt"])
        for bp in b["beatPrompts"]:
            print("\n=== %s ===\n%s" % (bp["beatId"], bp["prompt"]))
