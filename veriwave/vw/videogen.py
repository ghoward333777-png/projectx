"""VeriWave Create: Video. A short film from a prompt: a storyboard, an animated picture sequence and captions.

Local engine: the prompt's subject becomes a four-to-eight-scene storyboard (opening, setting, detail, change,
close…); each scene is painted by the image engine and the film is one animated SVG (cross-fades and a slow zoom per
scene, captions on screen) that plays in any browser and can be downloaded. QueryBook's Video Studio renders MP4 with
personas and narration; the film's storyboard can be taken there. Claude engine: Claude writes the storyboard.

Lean:
    structure Scene where
      caption : String
      picture : String
      start : Nat
      length : Nat
    deriving Repr, BEq
"""
from __future__ import annotations

import html

from . import core, imagegen, textgen

BEATS = [("Opening", "wide view of {s}"), ("Setting", "{s} in its place, early light"), ("Detail", "close detail of {s}"),
         ("Movement", "{s} in motion, clouds"), ("Change", "{s} at sunset"), ("Night", "{s} at night with stars"),
         ("Return", "{s} at dawn"), ("Close", "a quiet wide view of {s} at dusk")]


def scene_count(prompt: str) -> int:
    """how many scenes: named ('6 scenes'), from a length (one scene per five seconds), else four; always 3 to 8

    Lean:
        def sceneCountOf (named secs : Option Nat) : Nat :=
          match named, secs with
          | some n, _ => max 3 (min 8 n)
          | none, some t => max 3 (min 8 (t / 5))
          | none, none => 4
        theorem sceneCount_range (a b : Option Nat) : 3 ≤ sceneCountOf a b ∧ sceneCountOf a b ≤ 8 := by
          unfold sceneCountOf; split <;> omega
        #guard sceneCountOf (some 12) none == 8                             -- py: scene_count("12 scenes about bees") == 8
        #guard sceneCountOf none (some 30) == 6                             -- py: scene_count("a 30 second video about bees") == 6
        #guard sceneCountOf none none == 4                                  -- py: scene_count("a video about bees") == 4
    """
    ws = core.words(prompt)
    for i in range(len(ws) - 1):
        if ws[i].isdigit() and ws[i].isascii() and ws[i + 1] in ("scenes", "scene", "shots", "shot"):
            return core.clamp(3, 8, int(ws[i]))
    for i in range(len(ws) - 1):
        if ws[i].isdigit() and ws[i].isascii() and ws[i + 1] in ("second", "seconds", "sec", "secs", "s"):
            return core.clamp(3, 8, int(ws[i]) // 5)
    return 4


def storyboard(prompt: str) -> list[dict]:
    """the scenes: caption, picture prompt, start and length (tenths of a second); five seconds each

    Lean:
        def timeline (n : Nat) : List (Nat × Nat) := (List.range n).map (fun i => (i * 50, 50))
        theorem timeline_len (n : Nat) : (timeline n).length = n := by simp [timeline]
        #guard timeline 3 == [(0, 50), (50, 50), (100, 50)]                 -- py: [(s["start"], s["length"]) for s in storyboard("3 scenes about a harbour")] == [(0, 50), (50, 50), (100, 50)]
    """
    n = scene_count(prompt)
    subject = textgen.subject_of(prompt) or "the world"
    picks = [0, 1, 2, 4] if n == 4 else list(range(n))
    out: list[dict] = []
    for k, i in enumerate(picks[:n]):
        name, pic = BEATS[i]
        out.append({"caption": name + ": " + textgen.cap_first(pic.replace("{s}", subject)), "picture": pic.replace("{s}", subject),
                    "start": k * 50, "length": 50})
    return out


def inner_svg(svg: str) -> str:
    """the drawing inside an <svg> document (between its opening tag and </svg>)

    Lean:
        def innerSvg (s : String) : String :=
          match s.splitOn ">" with
          | _ :: rest => ((">".intercalate rest).dropRight "</svg>".length)
          | [] => ""
        #guard innerSvg "<svg a=\"1\"><circle/></svg>" == "<circle/>"        -- py: inner_svg('<svg a="1"><circle/></svg>') == "<circle/>"
    """
    start = svg.find(">")
    end = svg.rfind("</svg>")
    return svg[start + 1:end] if start >= 0 and end > start else ""


def key_times(k: int, n: int) -> tuple[str, str]:
    """when scene k of n is visible, as SMIL keyTimes and opacity values: fade in over half a second, hold, fade out

    Lean:
        -- permille of the whole film: scene k covers [k*1000/n, (k+1)*1000/n]
        def window (k n : Nat) : Nat × Nat := (k * 1000 / n, (k + 1) * 1000 / n)
        theorem window_ordered (k n : Nat) : (window k n).1 ≤ (window k n).2 := by
          unfold window; exact Nat.div_le_div_right (by omega)
        #guard window 1 4 == (250, 500)                                      -- py: key_times(1, 4)[0].startswith("0.0000;0.2500;")
    """
    total = n * 50
    a = k * 50
    b = a + 50
    f = 5
    if n == 1:
        pts, vals = [0, total], ["1", "1"]
    elif k == 0:
        pts, vals = [0, b - f, b, total], ["1", "1", "0", "0"]
    elif k == n - 1:
        pts, vals = [0, a, a + f, total], ["0", "0", "1", "1"]
    else:
        pts, vals = [0, a, a + f, b - f, b, total], ["0", "0", "1", "1", "0", "0"]
    return ";".join(_ratio(x, total) for x in pts), ";".join(vals)


def _ratio(p: int, total: int) -> str:
    """p/total as a decimal with up to 4 places, for SMIL

    Lean:
        def ratioStr (p total : Nat) : String := decimalDigits p total 4
        #guard ratioStr 1 4 == "0.2500"                                      -- py: _ratio(1, 4) == "0.2500"
    """
    whole = p // total
    frac = (p % total) * 10000 // total
    return str(whole) + "." + str(frac).rjust(4, "0")


def film(prompt: str, scenes: list[dict]) -> str:
    """the film: every scene's picture stacked, each fading in and out on its window, slowly zooming, with its caption

    Lean:
        def filmSeconds (n : Nat) : Nat := n * 5
        #guard filmSeconds 4 == 20                                           -- py: 'dur="20s"' in film("x", storyboard("a video about bees"))
    """
    n = len(scenes)
    secs = n * 5
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 640" width="1024" height="640">', '<rect width="1024" height="640" fill="#000"/>']
    for k, sc in enumerate(scenes):
        pic = imagegen.paint(sc["picture"])["svg"]
        times, vals = key_times(k, n)
        zoom_from = "1 1" if k % 2 == 0 else "1.08 1.08"
        zoom_to = "1.08 1.08" if k % 2 == 0 else "1 1"
        out.append('<g opacity="%s"><animate attributeName="opacity" dur="%ds" repeatCount="indefinite" keyTimes="%s" values="%s"/>' % ("1" if k == 0 else "0", secs, times, vals))
        out.append('<g><animateTransform attributeName="transform" type="scale" dur="%ds" repeatCount="indefinite" values="%s;%s" additive="sum"/>' % (secs, zoom_from, zoom_to))
        out.append(inner_svg(pic).replace('id="sky"', 'id="sky%d"' % k).replace("url(#sky)", "url(#sky%d)" % k))
        out.append("</g>")
        cap = html.escape(sc["caption"])
        out.append('<rect x="0" y="560" width="1024" height="80" fill="#000" opacity="0.45"/>')
        out.append('<text x="512" y="610" text-anchor="middle" font-family="system-ui, sans-serif" font-size="30" fill="#fff">%s</text>' % cap)
        out.append("</g>")
    out.append("</svg>")
    return "\n".join(out)


def generate_local(prompt: str) -> dict:
    """storyboard plus film for a prompt

    Lean:
        #guard filmSeconds (sceneCountOf none none) == 20                    -- py: generate_local("a video about bees")["seconds"] == 20
    """
    scenes = storyboard(prompt)
    return {"scenes": scenes, "svg": film(prompt, scenes), "seconds": len(scenes) * 5, "engine": "local",
            "subject": textgen.subject_of(prompt)}


VIDEO_SYSTEM = ("You are VeriWave's video engine. Write a storyboard for the short film the user describes. Return ONLY a "
                "JSON object: {\"scenes\": [{\"caption\": \"<on-screen caption, under 60 characters>\", \"picture\": \"<a "
                "picture description using plain scene words: sky, sun, moon, stars, clouds, mountains, sea, beach, desert, "
                "snow, forest, trees, meadow, flowers, city, house, lighthouse, boat, birds, and a time of day>\"}]} with "
                "3 to 8 scenes.")


def from_claude(prompt: str, data: dict) -> dict:
    """a film from Claude's storyboard: its captions and picture prompts, at most eight scenes, timed like the local ones

    Lean:
        def capScenes (n : Nat) : Nat := min 8 n
        #guard capScenes 12 == 8                                              -- py: len(from_claude("x", {"scenes": [{"caption": "c", "picture": "sea"}] * 12})["scenes"]) == 8
    """
    raw = [s for s in (data.get("scenes") or []) if isinstance(s, dict)][:8]
    scenes = [{"caption": core.cut(str(s.get("caption") or ""), 80), "picture": str(s.get("picture") or prompt), "start": k * 50, "length": 50}
              for k, s in enumerate(raw)]
    if not scenes:
        return generate_local(prompt)
    return {"scenes": scenes, "svg": film(prompt, scenes), "seconds": len(scenes) * 5, "engine": "claude", "subject": textgen.subject_of(prompt)}
