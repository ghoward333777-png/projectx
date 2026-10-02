"""QueryBook Scene Reconstructor (a.k.a. Scene Replayer)  [deterministic director]

Turns any prose/script/article excerpt into a director-controlled 15–30s video *plan* and
Gemini-ready prompt bundle, with style, cultural context, perspective, silhouette handling for
extra characters, and an automatic mood-matched music cue sheet.

It is a LAYER on top of the foundational Scene Director (qb_gemini): this module adds
text→FU parsing, the StyleProfile catalog + application, context/culture/POV enrichment,
silhouette policy, the MusicSelector/CueEngine/AudioMixer plan, and the single
render_scene_from_text() entry point. qb_gemini is not modified (foundational stability).

COVENANT BOUNDARY (important): a reconstructed clip is an INTERPRETIVE RENDERING of the source
text, never an asserted fact. Every result carries a provenance note (source hash + "visualized
interpretation, not asserted truth") and, when qb_integrity is present, a tamper-evident seal.
Cultural enrichment follows the dialect safety stance: render features, never caricature.
Prompt generation is pure deterministic templating — no LLM asserts anything.
"""

import re as _re

import qb_gemini

# ==========================================================================
# 1. StyleProfile catalog (15 styles).  silhouette_policy: none | extras | all_non_primary
# ==========================================================================
def _rig(type_, position, intensity, color, mood=None):
    r = {"type": type_, "position": position, "intensity": intensity, "color": color}
    if mood: r["mood"] = mood
    return r

STYLE_PROFILES = {
    "film_noir": {"name": "Film Noir", "color_grade": "monochrome, high contrast",
        "lighting_preset": "low-key, strong key + rim", "camera_behavior": "slow dolly, OTS, dramatic angles",
        "texture": "grainy 1940s film", "silhouette_policy": "extras",
        "prompt_tags": ["high-contrast noir lighting", "deep shadows", "grainy monochrome film", "moody, tense atmosphere"],
        "mood": "noir",
        "rigs": [_rig("key", "above the subject", "low", "warm tungsten", "noir"),
                 _rig("back", "behind the subject", "medium", "cool blue", "noir")]},
    "period_1920s": {"name": "1920s Period", "color_grade": "sepia, warm amber",
        "lighting_preset": "soft incandescent, smoky interiors", "camera_behavior": "static or slow pan",
        "texture": "film grain, slight flicker", "silhouette_policy": "extras",
        "prompt_tags": ["1920s period look", "sepia tone", "vintage film grain", "era-accurate wardrobe and props"],
        "mood": "nostalgic", "rigs": [_rig("key", "camera left", "soft", "warm amber", "nostalgic")]},
    "period_1950s": {"name": "1950s Period", "color_grade": "muted pastels, warm tungsten",
        "lighting_preset": "soft key, gentle fill", "camera_behavior": "classic Hollywood framing",
        "texture": "clean film stock", "silhouette_policy": "extras",
        "prompt_tags": ["1950s Americana", "warm tungsten lighting", "retro color palette"],
        "mood": "warm", "rigs": [_rig("key", "camera left", "soft", "warm tungsten", "warm")]},
    "period_1980s": {"name": "1980s Period", "color_grade": "neon, saturated blues/pinks",
        "lighting_preset": "strong colored practicals", "camera_behavior": "handheld or slow push-in",
        "texture": "VHS grain optional", "silhouette_policy": "extras",
        "prompt_tags": ["1980s neon aesthetic", "retro synthwave lighting", "saturated colors"],
        "mood": "energetic", "rigs": [_rig("practical", "behind the subject", "strong", "neon magenta", "energetic")]},
    "color_1k": {"name": "1K Color", "color_grade": "soft, low-resolution palette",
        "lighting_preset": "neutral", "camera_behavior": "simple static or slow dolly",
        "texture": "slightly blurred edges", "silhouette_policy": "none",
        "prompt_tags": ["soft low-resolution color", "gentle gradients"], "mood": "neutral",
        "rigs": [_rig("key", "front", "medium", "neutral white")]},
    "color_4k": {"name": "4K Color", "color_grade": "ultra-sharp, HDR",
        "lighting_preset": "crisp, high-fidelity", "camera_behavior": "smooth dolly, stabilized",
        "texture": "hyper-detailed", "silhouette_policy": "none",
        "prompt_tags": ["ultra-detailed 4K look", "high dynamic range color"], "mood": "neutral",
        "rigs": [_rig("key", "camera left", "medium", "neutral white"), _rig("fill", "camera right", "soft", "neutral white")]},
    "cartoon": {"name": "Cartoon", "color_grade": "bright, saturated",
        "lighting_preset": "flat, minimal shadows", "camera_behavior": "simple pans, zooms",
        "texture": "cell-shaded, bold outlines", "silhouette_policy": "extras",
        "prompt_tags": ["cartoon style", "bold outlines", "flat saturated colors"], "mood": "playful",
        "rigs": [_rig("key", "front", "soft", "bright white", "playful")]},
    "sketch": {"name": "Sketch", "color_grade": "monochrome or minimal color",
        "lighting_preset": "pencil shading implied", "camera_behavior": "static or simple pans",
        "texture": "pencil/charcoal strokes", "silhouette_policy": "extras",
        "prompt_tags": ["hand-drawn sketch style", "pencil lines", "charcoal shading"], "mood": "reflective",
        "rigs": [_rig("key", "front", "soft", "graphite grey", "reflective")]},
    "silhouette": {"name": "Silhouette", "color_grade": "high contrast black-and-white",
        "lighting_preset": "strong backlight", "camera_behavior": "slow dolly or static",
        "texture": "crisp outlines", "silhouette_policy": "all_non_primary",
        "prompt_tags": ["silhouette animation", "characters shown only as dark outlines", "no facial detail"],
        "mood": "tense", "rigs": [_rig("back", "directly behind the subjects", "high", "white", "tense")]},
    "watercolor": {"name": "Watercolor", "color_grade": "soft gradients, pastel washes",
        "lighting_preset": "diffuse, gentle", "camera_behavior": "slow pans",
        "texture": "watercolor bleed, paper grain", "silhouette_policy": "none",
        "prompt_tags": ["watercolor painting style", "soft edges", "subtle gradients"], "mood": "gentle",
        "rigs": [_rig("key", "overhead", "soft", "warm amber", "gentle")]},
    "hyperreal": {"name": "Hyperrealism", "color_grade": "extremely detailed, lifelike",
        "lighting_preset": "physically accurate", "camera_behavior": "cinematic realism",
        "texture": "high-resolution skin, fabric, surfaces", "silhouette_policy": "none",
        "prompt_tags": ["hyperrealistic detail", "photorealistic lighting"], "mood": "neutral",
        "rigs": [_rig("key", "camera left", "medium", "daylight"), _rig("fill", "camera right", "soft", "daylight")]},
    "minimalist": {"name": "Minimalist", "color_grade": "muted, monochrome",
        "lighting_preset": "soft, even", "camera_behavior": "static",
        "texture": "clean, simple shapes", "silhouette_policy": "extras",
        "prompt_tags": ["minimalist aesthetic", "simple clean lines"], "mood": "calm",
        "rigs": [_rig("key", "front", "soft", "neutral white", "calm")]},
    "surreal": {"name": "Surreal / Dreamlike", "color_grade": "pastel or neon dream palette",
        "lighting_preset": "ethereal, floating", "camera_behavior": "drifting, slow float",
        "texture": "soft blur, glow", "silhouette_policy": "none",
        "prompt_tags": ["dreamlike surreal atmosphere", "ethereal lighting"], "mood": "dreamlike",
        "rigs": [_rig("key", "overhead", "soft", "pastel violet", "dreamlike")]},
    "documentary": {"name": "Documentary", "color_grade": "naturalistic",
        "lighting_preset": "practical lighting", "camera_behavior": "handheld, observational",
        "texture": "grain optional", "silhouette_policy": "extras",
        "prompt_tags": ["documentary realism", "handheld camera movement"], "mood": "neutral",
        "rigs": [_rig("practical", "ambient", "medium", "available light")]},
    "anime": {"name": "Anime", "color_grade": "vibrant, stylized",
        "lighting_preset": "dramatic highlights", "camera_behavior": "dynamic zooms, pans",
        "texture": "anime shading, line art", "silhouette_policy": "extras",
        "prompt_tags": ["anime style", "cel shading", "vibrant colors"], "mood": "energetic",
        "rigs": [_rig("key", "camera left", "strong", "vivid white", "energetic"),
                 _rig("back", "behind the subject", "medium", "cool blue", "energetic")]},
}

def list_styles():
    return [{"id": k, "name": v["name"], "color_grade": v["color_grade"],
             "camera_behavior": v["camera_behavior"], "texture": v["texture"],
             "silhouette_policy": v["silhouette_policy"], "prompt_tags": v["prompt_tags"]}
            for k, v in STYLE_PROFILES.items()]


# ==========================================================================
# 2. Music palette catalog + CueEngine (beat-aware)
# ==========================================================================
MUSIC_PALETTES = {
    "film_noir": {"genre": "jazz_noir", "instrumentation": ["muted_trumpet", "upright_bass", "brushed_drums", "piano", "saxophone"]},
    "period_1920s": {"genre": "early_jazz", "instrumentation": ["stride_piano", "clarinet", "muted_brass", "upright_bass"]},
    "period_1950s": {"genre": "midcentury_jazz", "instrumentation": ["jazz_trio", "jukebox_rock", "crooner_vocals", "brushed_drums"]},
    "period_1980s": {"genre": "synthwave", "instrumentation": ["analog_synth", "gated_drums", "bass_synth", "pads"]},
    "color_1k": {"genre": "soft_ambient", "instrumentation": ["pads", "gentle_piano", "minimal_percussion"]},
    "color_4k": {"genre": "cinematic", "instrumentation": ["orchestra", "piano", "percussion", "bass_pulses"]},
    "cartoon": {"genre": "playful_orchestral", "instrumentation": ["pizzicato_strings", "bright_synths", "percussion"]},
    "sketch": {"genre": "minimal_piano", "instrumentation": ["piano", "soft_pads", "acoustic_guitar"]},
    "silhouette": {"genre": "minimal_ambient", "instrumentation": ["drones", "sparse_piano", "low_pulses"]},
    "watercolor": {"genre": "soft_ambient", "instrumentation": ["pads", "piano", "airy_textures"]},
    "hyperreal": {"genre": "cinematic_score", "instrumentation": ["orchestra", "percussion", "bass", "piano"]},
    "minimalist": {"genre": "minimal_ambient", "instrumentation": ["piano", "drones", "low_pulses"]},
    "surreal": {"genre": "ethereal", "instrumentation": ["pads", "bells", "reversed_textures"]},
    "documentary": {"genre": "neutral_underscore", "instrumentation": ["light_percussion", "ambient", "subtle_motifs"]},
    "anime": {"genre": "emotional_anime", "instrumentation": ["piano", "strings", "bright_synths", "drums"]},
}

def _beat_intensity(idx, n, mood):
    if idx == 0: return "low"
    if idx == n - 1: return "low" if mood not in ("tense", "noir", "oppressive") else "medium"
    if mood in ("tense", "noir", "oppressive", "energetic"): return "high"
    return "medium"

def _beat_motif(idx, n, beat):
    acts = " ".join((a.get("action", "") + " " + (a.get("dialogue") or "")).lower()
                    for a in beat.get("characterActions", []))
    if any(w in acts for w in ("pistol", "gun", "knife", "weapon", "blood")): return "danger_motif"
    if idx == 0: return "entrance_motif"
    if idx == n - 1: return "resolution_motif"
    if "?" in acts or "says" in acts: return "dialogue_motif"
    return None

def cue_map(scene, mood):
    beats = scene.get("timeline", [])
    n = len(beats) or 1
    cues = {}
    for i, b in enumerate(beats):
        start = i * 5; end = start + 5
        hint = b.get("timecodeHint", "")
        m = _re.match(r"(\d+)-(\d+)", hint)
        if m: start, end = int(m.group(1)), int(m.group(2))
        trans = "fade_in" if i == 0 else ("fade_out" if i == n - 1 else
                ("swell" if _beat_intensity(i, n, mood) == "high" else "cut"))
        cues[b["id"]] = {"startTime": start, "endTime": end,
                         "intensity": _beat_intensity(i, n, mood),
                         "motif": _beat_motif(i, n, b), "transition": trans}
    return cues

def select_music(scene, style_id):
    """MusicSelector: pick a palette + build a beat-aware cue map from the scenegraph + style."""
    pal = MUSIC_PALETTES.get(style_id, {"genre": "neutral", "instrumentation": []})
    mood = next((l.get("mood") for l in scene.get("lighting", []) if l.get("mood")), "neutral")
    return {"track": {"id": "music_%s_%s" % (style_id, mood),
                      "uri": "/audio/%s_%s.mp3" % (style_id, mood),
                      "genre": pal["genre"], "mood": mood, "instrumentation": pal["instrumentation"]},
            "cueMap": cue_map(scene, mood),
            "note": "Deterministic selection: style→palette, mood→intensity, beats→cues. "
                    "Audio is NOT bundled; the mixer below returns a plan, not rendered sound."}

def mix_plan(video_ref, music):
    """AudioMixer: produce an honest MIX PLAN (cue sheet + ffmpeg command template). It does NOT
    render audio — real mixing needs ffmpeg + a licensed track. Gemini video may ship silent."""
    cues = music.get("cueMap", {})
    sheet = [{"beat": k, **v} for k, v in sorted(cues.items())]
    ffmpeg = ("ffmpeg -i <video> -i <music:%s> -filter_complex "
              "\"[1:a]volume=0.6,afade=t=in:st=%d:d=1,afade=t=out:st=%d:d=1[m];"
              "[0:a][m]amix=inputs=2:duration=first[a]\" -map 0:v -map \"[a]\" <out.mp4>"
              % (music["track"]["uri"],
                 (sheet[0]["startTime"] if sheet else 0),
                 (sheet[-1]["endTime"] if sheet else 20)))
    return {"ok": True, "rendered": False, "cue_sheet": sheet, "ffmpeg": ffmpeg,
            "note": "Mix PLAN only (no bundled audio). Duck music under dialogue; boost in silent beats."}


# ==========================================================================
# 3. Text → FU graph  (deterministic shallow scene parser)
# ==========================================================================
_ROLE_NOUNS = ("bartender", "man", "woman", "boy", "girl", "child", "narrator", "stranger",
               "soldier", "waiter", "waitress", "detective", "officer", "driver", "doctor",
               "teacher", "king", "queen", "guard", "patron", "crowd", "band")
_PLACE_NOUNS = ("bar", "kitchen", "street", "club", "room", "alley", "office", "cafe", "diner",
                "church", "station", "market", "field", "forest", "beach", "rooftop", "hall")
_MOOD_LEX = {
    "tense": ("tense", "wary", "nervous", "threat", "danger", "pistol", "gun", "fear", "silence"),
    "noir": ("smoke", "neon", "shadow", "rain", "dark", "cigarette"),
    "oppressive": ("heavy", "pressing", "weight", "suffocating", "trapped"),
    "romantic": ("love", "kiss", "tender", "embrace", "longing", "warm"),
    "joyful": ("laugh", "smile", "celebrate", "bright", "dance", "happy"),
    "somber": ("grief", "mourn", "tears", "funeral", "loss", "quiet"),
}
_SPEAK_VERBS = ("said", "asked", "whispered", "shouted", "muttered", "replied", "answered", "called")
_STOP = set("the a an of to in on at for and or but is are was were be with from into he she "
            "they him her his them it as by his her their".split())

def _sentences(text):
    return [s.strip() for s in _re.split(r"(?<=[.!?\"])\s+", (text or "").strip()) if s.strip()]

def _detect_characters(text):
    counts = {}
    # proper nouns (capitalized words not at sentence start — approximate)
    for s in _sentences(text):
        toks = _re.findall(r"[A-Za-z']+", s)
        for i, w in enumerate(toks):
            if i > 0 and w[0].isupper() and w.lower() not in _STOP and len(w) > 2:
                counts[w] = counts.get(w, 0) + 2
    low = text.lower()
    for role in _ROLE_NOUNS:
        c = len(_re.findall(r"\b" + role + r"\b", low))
        if c: counts[role.capitalize()] = counts.get(role.capitalize(), 0) + c
    if _re.search(r"\b(he|she|i|him|her)\b", low) and not counts:
        counts["Narrator"] = 3
    elif _re.search(r"\b(he|she|i)\b", low):
        counts.setdefault("Narrator", 2)
    # rank by frequency
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    return [n for n, _ in ranked][:8]

def _detect_environment(text):
    low = text.lower()
    for p in _PLACE_NOUNS:
        m = _re.search(r"([a-z]+\s+){0,2}\b" + p + r"\b", low)
        if m:
            return m.group(0).strip()
    return "an unspecified setting"

def _detect_mood(text):
    low = text.lower()
    best, score = "neutral", 0
    for mood, words in _MOOD_LEX.items():
        c = sum(low.count(w) for w in words)
        if c > score: best, score = mood, c
    return best

def _primary_count(style):
    return 1 if STYLE_PROFILES.get(style, {}).get("silhouette_policy") == "all_non_primary" else 2

def parse_text_to_fu(text, perspective="objective", period=None, culture=None, social=None,
                     duration=20, style=None):
    """Deterministic shallow parse of prose → FUGraph (entities/actions/pragmatics/discourse).
    Approximate by design and labelled as such — it is a staging aid, not literary analysis."""
    chars = _detect_characters(text) or ["Narrator"]
    env = _detect_environment(text)
    mood = _detect_mood(text)
    nprim = _primary_count(style)
    entities = [{"id": "loc", "type": "location", "attributes": {"description": env}}]
    for i, name in enumerate(chars):
        kind = "primary" if i < nprim else "extra"
        entities.append({"id": "c%d" % i, "type": "character",
                         "attributes": {"name": name, "look": name, "importance": kind}})
    # actions: one per sentence, subject = first character mentioned, dialogue = quoted
    acts = []
    sents = _sentences(text)
    for idx, s in enumerate(sents):
        dlg = None
        mq = _re.search(r'[\"“]([^\"”]{2,120})[\"”]', s)
        if mq: dlg = mq.group(1)
        subj = "c0"
        for e in entities:
            if e["type"] == "character" and e["attributes"]["name"].lower() in s.lower():
                subj = e["id"]; break
        verb = "speaks" if dlg else _first_verb(s)
        # Preserve a salient object (weapon/danger) in the action phrase so downstream beat
        # motifs and cinematography can react to it (otherwise only the bare verb survives).
        low_s = s.lower()
        for obj in ("pistol", "gun", "knife", "weapon", "blood", "letter", "phone", "glass"):
            if obj in low_s and not dlg:
                verb = "%s, revealing a %s" % (verb, obj)
                break
        acts.append({"id": "a%d" % idx, "verb": verb, "participants": [subj],
                     "dialogue": dlg, "orderingIndex": idx})
    # beats by duration
    nbeats = {15: 3, 20: 4, 30: 5}.get(int(duration), 4)
    beats = _distribute_beats(acts, nbeats, duration)
    pragmatics = {"mood": mood, "characterEmotion": {}}
    if social: pragmatics["social_conditions"] = social
    if culture: pragmatics["culture"] = culture
    if period: pragmatics["period"] = period
    discourse = {"focus": "intimate_dialogue" if any(a["dialogue"] for a in acts) else "establishing",
                 "beats": beats, "perspective": perspective}
    return {"sceneId": "scene_%d" % (abs(hash(text)) % 100000),
            "entities": entities, "actions": acts, "pragmatics": pragmatics, "discourse": discourse,
            "_parse": {"characters": chars, "environment": env, "mood": mood,
                       "note": "Deterministic shallow parser (approximate); not literary analysis."}}

_VERB_HINTS = ("push", "pull", "walk", "run", "turn", "watch", "cross", "slide", "enter", "exit",
               "open", "close", "look", "stare", "reach", "stand", "sit", "lean", "reveal", "raise")
def _first_verb(sentence):
    low = sentence.lower()
    for v in _VERB_HINTS:
        if _re.search(r"\b" + v + r"(s|ed|ing)?\b", low):
            return _re.search(r"\b(" + v + r"(?:s|ed|ing)?)\b", low).group(1)
    return "moves"

def _distribute_beats(acts, nbeats, duration):
    beats = []
    per = max(1, (len(acts) + nbeats - 1) // nbeats)
    step = duration // nbeats
    for i in range(nbeats):
        chunk = acts[i * per:(i + 1) * per]
        if not chunk and i >= len(acts):
            break
        start = i * step; end = min(duration, start + step)
        for a in chunk:
            beats.append({"actionId": a["id"], "timecodeHint": "%d-%ds" % (start, end)})
    return beats


# ==========================================================================
# 4. Context enrichment + style application + silhouettes
# ==========================================================================
def _enrich_environment(scene, period, culture, social):
    env = scene["stage"]["environment"]
    bits = [env]
    if period: bits.append("in %s" % period)
    if culture: bits.append("(%s)" % culture)
    scene["stage"]["environment"] = " ".join(bits)
    if social:
        scene.setdefault("context", {})["social_conditions"] = social
    return scene

def apply_style(scene, style_id, enforce_silhouette_for_extras=True):
    """Transform the scenegraph's VISUAL realization per the StyleProfile (never its meaning)."""
    sp = STYLE_PROFILES.get(style_id)
    if not sp:
        return scene
    # lighting preset replaces rigs
    scene["lighting"] = [dict(r) for r in sp["rigs"]]
    # record style block for prompt augmentation
    scene["style"] = {"id": style_id, "name": sp["name"], "color_grade": sp["color_grade"],
                      "texture": sp["texture"], "camera_behavior": sp["camera_behavior"],
                      "prompt_tags": sp["prompt_tags"], "silhouette_policy": sp["silhouette_policy"]}
    # silhouette policy on characters
    policy = sp["silhouette_policy"]
    if enforce_silhouette_for_extras and policy == "none":
        policy = "extras"
    prims = [c for c in scene["characters"]][: _primary_count(style_id)]
    prim_ids = {c["id"] for c in prims}
    if policy in ("extras", "all_non_primary"):
        for c in scene["characters"]:
            is_extra = c["id"] not in prim_ids
            if (policy == "extras" and is_extra) or (policy == "all_non_primary" and is_extra):
                c["description"] = "a silhouetted figure (dark outline, no facial detail)"
                c["emotion"] = "indistinct"
    scene["_silhouettes"] = [c["id"] for c in scene["characters"]
                             if "silhouetted" in (c.get("description") or "")]
    return scene

def scene_prompt_bundle(scene):
    """qb_gemini bundle, augmented with the style line, silhouette rule, and context tags."""
    bundle = qb_gemini.generate_prompt_bundle(scene)
    st = scene.get("style")
    prefix = []
    if st:
        prefix.append("Render in %s style: %s; texture %s." % (st["name"], st["color_grade"], st["texture"]))
    ctx = scene.get("context", {})
    if ctx.get("social_conditions"):
        prefix.append("Social context: %s (render respectfully; never caricature)." % ctx["social_conditions"])
    base = bundle["basePrompt"]
    if prefix:
        base = " ".join(prefix) + " " + base
    if scene.get("_silhouettes"):
        base += (" Any additional characters appear ONLY as silhouettes — dark shapes with no "
                 "facial detail, just clear outlines in the background.")
    if st and st.get("prompt_tags"):
        base += " Style cues: " + ", ".join(st["prompt_tags"]) + "."
    bundle["basePrompt"] = base
    bundle["styleId"] = st["id"] if st else None
    return bundle


# ==========================================================================
# 5. Orchestrator — render_scene_from_text
# ==========================================================================
def _provenance(text):
    try:
        import qb_integrity
        s = qb_integrity.seal(text, author="scene_reconstructor")
        return {"sealed": True, "seal_id": s["seal_id"], "text_hash": s["text_hash"]}
    except Exception:
        import hashlib
        return {"sealed": False, "text_hash": hashlib.sha256((text or "").encode()).hexdigest()}

def render_scene_from_text(text, style="film_noir", duration=20, perspective="objective",
                           period=None, culture=None, social=None,
                           enforce_silhouette_for_extras=True, music=True,
                           base_media=None, model="veo-3.0-generate-preview"):
    """One call: text → FU → SceneGraph → context → style → silhouettes → prompts → (Gemini
    dry-run) → compliance → music cue sheet → mix plan. Returns the full inspectable result.
    The clip is an INTERPRETIVE RENDERING of the source text, not an asserted fact."""
    if not (text or "").strip():
        return {"ok": False, "error": "source text required"}
    if style not in STYLE_PROFILES:
        return {"ok": False, "error": "unknown style '%s'" % style}
    fu = parse_text_to_fu(text, perspective, period, culture, social, duration, style)
    scene = qb_gemini.build_scene_graph_from_fu(fu)
    scene = _enrich_environment(scene, period, culture, social)
    scene = apply_style(scene, style, enforce_silhouette_for_extras)
    validation = qb_gemini.validate_scene_graph(scene)
    bundle = scene_prompt_bundle(scene)
    gen = qb_gemini.generate_video(bundle, base_media, model)
    result = {"ok": True, "sceneId": scene["sceneId"], "scene": scene, "validation": validation,
              "promptBundle": bundle, "dry_run": gen.get("dry_run", True), "generation": gen,
              "style": scene.get("style"), "duration": duration, "perspective": perspective,
              "period": period, "culture": culture, "social_conditions": social,
              "parse": fu.get("_parse"),
              "provenance": _provenance(text),
              "covenant": "Interpretive visualization of the source text — NOT an asserted fact. "
                          "Cultural rendering follows the no-caricature safety stance."}
    if music:
        ms = select_music(scene, style)
        result["music"] = ms
        if not gen.get("dry_run") and gen.get("video"):
            result["mix"] = mix_plan(gen.get("video"), ms)
        else:
            result["mix"] = mix_plan({"uri": "<video>"}, ms)
    return result


# ==========================================================================
# 6. QC — the noir bar stress test, end to end
# ==========================================================================
NOIR_TEXT = ("He pushed open the door to the small LA bar, the neon sign buzzing above him. "
             "Inside, smoke hung low over chipped tables and tired faces. The bartender watched "
             "him with a wary eye as he crossed the room. At the far end of the bar, a man in a "
             "wrinkled suit turned just enough to show the glint of a pistol under his coat. "
             '"You\'re late," the bartender said.')

def qc():
    r = render_scene_from_text(NOIR_TEXT, style="film_noir", duration=20, perspective="first_person",
                               period="1950s LA", culture="working-class bar culture",
                               social="post-war America")
    checks = []
    ck = lambda n, c: checks.append({"check": n, "pass": bool(c)})
    ck("render ok", r.get("ok"))
    ck("valid scenegraph", r["validation"]["ok"])
    ck("characters detected", len(r["scene"]["characters"]) >= 2)
    ck("silhouettes applied to extras", len(r["scene"].get("_silhouettes", [])) >= 1)
    ck("base prompt carries film noir", "Film Noir style" in r["promptBundle"]["basePrompt"])
    ck("base prompt carries period", "1950s LA" in r["promptBundle"]["basePrompt"])
    ck("silhouette rule in prompt", "silhouettes" in r["promptBundle"]["basePrompt"])
    ck("beats present", len(r["promptBundle"]["beatPrompts"]) >= 3)
    ck("music selected (jazz_noir)", r["music"]["track"]["genre"] == "jazz_noir")
    ck("cue map has entrance motif", any(c.get("motif") == "entrance_motif" for c in r["music"]["cueMap"].values()))
    ck("danger motif on pistol beat", any(c.get("motif") == "danger_motif" for c in r["music"]["cueMap"].values()))
    ck("mix plan produced", r["mix"]["ok"] and r["mix"]["rendered"] is False)
    ck("provenance recorded", bool(r["provenance"]["text_hash"]))
    ck("15 styles in catalog", len(STYLE_PROFILES) == 15)
    passed = sum(1 for c in checks if c["pass"])
    return {"passed": passed, "total": len(checks), "ok": passed == len(checks), "rows": checks}


if __name__ == "__main__":
    import json, sys
    if "--show" in sys.argv:
        r = render_scene_from_text(NOIR_TEXT, style="film_noir", duration=20, period="1950s LA")
        print("BASE:\n" + r["promptBundle"]["basePrompt"] + "\n")
        print("MUSIC:", json.dumps(r["music"]["track"]))
        print("CUES:", json.dumps(r["music"]["cueMap"], indent=2))
    else:
        print(json.dumps(qc(), indent=2))
