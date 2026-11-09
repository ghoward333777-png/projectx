"""VeriWave Create: Image. Pictures from a prompt, as scalable vector images (SVG).

Local engine: a deterministic scene painter. The prompt's words choose the time of day, the palette and the elements
(sun or moon, stars, clouds, mountains, sea, beach, desert, snow, forest, trees, meadow and flowers, city, house,
lighthouse, boat, birds); anything else gets an abstract composition. Integer coordinates, seeded from the prompt, so
the same prompt paints the same picture in Python, Rust and Lean. Claude engine: Claude draws the SVG itself.

Lean:
    def W : Int := 1024
    def H : Int := 640
    def HORIZON : Int := 400
"""
from __future__ import annotations

from . import core

W = 1024
H = 640
HORIZON = 400
ELEMENTS = ["sun", "moon", "stars", "clouds", "mountains", "sea", "beach", "desert", "snow", "forest", "trees", "meadow",
            "flowers", "city", "house", "lighthouse", "boat", "birds"]
TRIGGERS: dict[str, list[str]] = {
    "sun": ["sun", "sunny", "sunrise", "sunset", "dawn", "summer"],
    "moon": ["moon", "moonlit", "moonlight"],
    "stars": ["star", "stars", "starry", "galaxy", "space", "milky way"],
    "clouds": ["cloud", "clouds", "cloudy", "sky", "storm"],
    "mountains": ["mountain", "mountains", "peak", "peaks", "alps", "hills", "hill", "valley"],
    "sea": ["sea", "ocean", "lake", "water", "harbor", "harbour", "bay", "coast", "waves", "lighthouse", "boat", "ship", "sail"],
    "beach": ["beach", "shore", "sand", "island", "tropical"],
    "desert": ["desert", "dune", "dunes", "sahara", "cactus"],
    "snow": ["snow", "snowy", "winter", "ice", "frozen"],
    "forest": ["forest", "woods", "woodland", "jungle", "pines"],
    "trees": ["tree", "trees", "park", "orchard", "garden"],
    "meadow": ["meadow", "field", "fields", "grass", "countryside", "farm", "garden", "flowers", "flower"],
    "flowers": ["flower", "flowers", "garden", "bloom", "blossom", "tulips", "roses", "spring"],
    "city": ["city", "skyline", "town", "buildings", "skyscrapers", "street", "downtown", "urban"],
    "house": ["house", "home", "cabin", "cottage", "farm", "barn", "village"],
    "lighthouse": ["lighthouse"],
    "boat": ["boat", "ship", "sail", "sailboat", "yacht", "harbor", "harbour"],
    "birds": ["bird", "birds", "gulls", "seagulls", "flock", "eagle"],
}
PALETTES: dict[str, list[str]] = {
    # sky top, sky bottom, far land, near land, water, accent, ink
    "day": ["#5aa6e8", "#cfe8fb", "#7f9cb8", "#4f8a4b", "#2f78b5", "#ffd34d", "#1d2330"],
    "sunset": ["#3b2a6b", "#ff9a5c", "#6d4a7a", "#3f3550", "#c4627a", "#ffcf5a", "#1b1426"],
    "night": ["#070b1f", "#24325e", "#1d2747", "#121a33", "#1a2c57", "#f4f1d0", "#e7eaf0"],
    "dawn": ["#8db7e8", "#ffd6c2", "#9aa7c9", "#6c8f6a", "#7aa6cf", "#ffe08a", "#1d2330"],
    "winter": ["#a9c6e3", "#eef4fa", "#c8d6e5", "#f4f8fc", "#7fa6c9", "#ffffff", "#2a3442"],
    "desert": ["#6fb3e0", "#f7e2b5", "#d9a86c", "#e8b978", "#3d8fc4", "#fff1a8", "#4a2f1a"],
}


def time_of(ws: list[str]) -> str:
    """the light: night, sunset, dawn, winter, desert or day

    Lean:
        def timeOf (ws : List String) : String :=
          if hasAny ws ["night", "midnight", "moon", "moonlit", "stars", "starry", "galaxy", "space", "dark"] then "night"
          else if hasAny ws ["sunset", "dusk", "evening", "twilight"] then "sunset"
          else if hasAny ws ["dawn", "sunrise", "morning"] then "dawn"
          else if hasAny ws ["snow", "snowy", "winter", "ice", "frozen"] then "winter"
          else if hasAny ws ["desert", "dune", "dunes", "sahara", "cactus"] then "desert"
          else "day"
        #guard timeOf (words "a lighthouse at sunset") == "sunset"       -- py: time_of(core.words("a lighthouse at sunset")) == "sunset"
        #guard timeOf (words "a cat") == "day"                            -- py: time_of(core.words("a cat")) == "day"
    """
    if core.has_any(ws, ["night", "midnight", "moon", "moonlit", "stars", "starry", "galaxy", "space", "dark"]):
        return "night"
    if core.has_any(ws, ["sunset", "dusk", "evening", "twilight"]):
        return "sunset"
    if core.has_any(ws, ["dawn", "sunrise", "morning"]):
        return "dawn"
    if core.has_any(ws, ["snow", "snowy", "winter", "ice", "frozen"]):
        return "winter"
    if core.has_any(ws, ["desert", "dune", "dunes", "sahara", "cactus"]):
        return "desert"
    return "day"


def elements_of(ws: list[str], light: str) -> list[str]:
    """the scene's elements, in painting order (back to front); the sun or moon follows the light

    Lean:
        def addSky (light : String) (els : List String) : List String :=
          let e1 := if light == "night" && !els.contains "moon" then "moon" :: els else els
          let e2 := if light == "night" && !e1.contains "stars" then "stars" :: e1 else e1
          if (light == "sunset" || light == "dawn" || light == "desert") && !e2.contains "sun" then "sun" :: e2 else e2
        theorem addSky_keeps (l : String) (els : List String) (e : String) (h : e ∈ els) : e ∈ addSky l els := by
          have k : ∀ (c : Bool) (x : String) (L : List String), e ∈ L → e ∈ (if c = true then x :: L else L) := by
            intro c x L hL; cases c <;> simp [hL]
          simp only [addSky]
          apply k; apply k; apply k; exact h
        #guard (addSky "night" []).contains "moon"                       -- py: "moon" in elements_of([], "night")
    """
    found = [e for e in ELEMENTS if core.has_any(ws, TRIGGERS[e])]
    if light == "night":
        for extra in ("moon", "stars"):
            if extra not in found:
                found.append(extra)
        found = [e for e in found if e != "sun"]
    if light in ("sunset", "dawn", "desert") and "sun" not in found:
        found.append("sun")
    return [e for e in ELEMENTS if e in found]


def svg_open(light: str) -> list[str]:
    """the picture's frame and sky gradient

    Lean:
        def svgHeader : String := "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 1024 640\" width=\"1024\" height=\"640\">"
        #guard svgHeader.startsWith "<svg"                                -- py: svg_open("day")[0].startswith("<svg") and 'viewBox="0 0 1024 640"' in svg_open("day")[0]
    """
    p = PALETTES[light]
    return ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d">' % (W, H, W, H),
            '<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="%s"/>'
            '<stop offset="1" stop-color="%s"/></linearGradient></defs>' % (p[0], p[1]),
            '<rect width="%d" height="%d" fill="url(#sky)"/>' % (W, H)]


def ridge(rng: core.Rng, base: int, amp: int, step: int) -> str:
    """a closed polygon: a jagged ridge line across the width, filled down to the bottom edge

    Lean:
        def ridgeCount (step : Nat) (h : 0 < step) : Nat := 1024 / step + 1
        theorem ridge_points_bound (y base amp : Int) (h : 0 ≤ amp) : clamp 0 640 (base - y) ≤ 640 :=
          (clamp_in 0 640 (base - y) (by decide)).2
        #guard clamp 0 640 (400 - 900) == 0                               -- py: all(0 <= int(p.split(",")[1]) <= 640 for p in ridge(core.Rng(1), 400, 900, 64).split(" "))
    """
    pts = ["0,%d" % H]
    x = 0
    while x <= W:
        y = core.clamp(0, H, base - rng.between(0, amp))
        pts.append("%d,%d" % (x, y))
        x += step
    pts.append("%d,%d" % (W, H))
    return " ".join(pts)


def paint(prompt: str) -> dict:
    """the picture for a prompt: SVG text, the light, the elements painted, deterministic

    Lean:
        def sceneKind (els : List String) : String := if els.isEmpty then "abstract" else "scene"
        #guard sceneKind [] == "abstract"                                 -- py: paint("an idea")["kind"] == "abstract"
        #guard sceneKind ["sea"] == "scene"                               -- py: paint("a lighthouse by the sea at sunset")["kind"] == "scene"
    """
    ws = core.words(prompt)
    light = time_of(ws)
    els = elements_of(ws, light)
    rng = core.Rng(core.seed_of(prompt))
    p = PALETTES[light]
    out = svg_open(light)
    scene = [e for e in els if e not in ("sun", "moon", "stars", "clouds", "birds")]
    if not scene and not els:
        out += abstract(rng, p)
        out.append("</svg>")
        return {"svg": "\n".join(out), "light": light, "elements": [], "kind": "abstract", "engine": "local"}
    horizon = HORIZON if ("sea" in els or "beach" in els) else HORIZON + 30
    if "stars" in els:
        for _ in range(90):
            x, y, r = rng.below(W), rng.below(horizon - 40), 1 + rng.below(2)
            out.append('<circle cx="%d" cy="%d" r="%d" fill="#ffffff" opacity="0.%d"/>' % (x, y, r, 5 + rng.below(5)))
    if "sun" in els:
        sx, sy = 180 + rng.below(660), (horizon - 70) if light in ("sunset", "dawn") else 110 + rng.below(80)
        out.append('<circle cx="%d" cy="%d" r="110" fill="%s" opacity="0.25"/>' % (sx, sy, p[5]))
        out.append('<circle cx="%d" cy="%d" r="62" fill="%s"/>' % (sx, sy, p[5]))
    if "moon" in els:
        mx, my = 700 + rng.below(220), 90 + rng.below(80)
        out.append('<circle cx="%d" cy="%d" r="46" fill="%s"/>' % (mx, my, p[5]))
        out.append('<circle cx="%d" cy="%d" r="40" fill="%s"/>' % (mx + 18, my - 10, p[0]))
    if "clouds" in els or light == "day":
        for _ in range(3 + rng.below(3)):
            cx, cy = rng.below(W), 60 + rng.below(160)
            for k in range(4):
                out.append('<ellipse cx="%d" cy="%d" rx="%d" ry="%d" fill="#ffffff" opacity="0.8"/>' % (cx + k * 38 - 60, cy + (k % 2) * 8, 48 + rng.below(20), 24 + rng.below(10)))
    if "mountains" in els or "snow" in els:
        out.append('<polygon points="%s" fill="%s"/>' % (ridge(rng, horizon - 30, 220, 96), p[2]))
        if "snow" in els:
            out.append('<polygon points="%s" fill="#ffffff" opacity="0.9"/>' % ridge(rng, horizon - 20, 40, 64))
    if "desert" in els:
        for k in range(3):
            out.append('<ellipse cx="%d" cy="%d" rx="%d" ry="%d" fill="%s"/>' % (rng.below(W), horizon + 40 + k * 60, 380, 70, p[3 if k % 2 else 2]))
    if "city" in els:
        x = 0
        while x < W:
            bw, bh = 40 + rng.below(70), 80 + rng.below(220)
            out.append('<rect x="%d" y="%d" width="%d" height="%d" fill="%s"/>' % (x, horizon - bh, bw, bh + 40, p[2] if light != "night" else "#1b2240"))
            for wy in range(horizon - bh + 12, horizon - 10, 22):
                for wx in range(x + 8, x + bw - 10, 16):
                    if rng.below(3) == 0:
                        out.append('<rect x="%d" y="%d" width="7" height="10" fill="%s" opacity="0.85"/>' % (wx, wy, p[5]))
            x += bw + 4
    if "sea" in els:
        out.append('<rect x="0" y="%d" width="%d" height="%d" fill="%s"/>' % (horizon, W, H - horizon, p[4]))
        for k in range(14):
            y = horizon + 14 + k * 16
            out.append('<path d="M%d %d q 30 -8 60 0 t 60 0" stroke="#ffffff" stroke-width="2" fill="none" opacity="0.%d"/>' % (rng.below(W - 120), y, 2 + rng.below(4)))
    land_y = horizon + (150 if "sea" in els else 0)
    if "beach" in els:
        out.append('<path d="M0 %d Q 512 %d 1024 %d L1024 640 L0 640 Z" fill="#f1d9a7"/>' % (land_y + 40, land_y - 10, land_y + 30))
    elif "sea" not in els or any(e in els for e in ("meadow", "forest", "trees", "house", "flowers")):
        out.append('<path d="M0 %d Q 512 %d 1024 %d L1024 640 L0 640 Z" fill="%s"/>' % (land_y + 20, land_y - 30, land_y + 10, p[3]))
    if "forest" in els:
        for _ in range(26):
            tx, ty, th = rng.below(W), land_y + rng.below(70), 70 + rng.below(70)
            out.append('<polygon points="%d,%d %d,%d %d,%d" fill="%s"/>' % (tx, ty - th, tx - 26, ty, tx + 26, ty, "#25502a" if light != "night" else "#0f1d16"))
    if "trees" in els:
        for _ in range(5):
            tx, ty = rng.below(W), land_y + 30 + rng.below(60)
            out.append('<rect x="%d" y="%d" width="12" height="54" fill="#6b4a2b"/>' % (tx - 6, ty - 54))
            out.append('<circle cx="%d" cy="%d" r="%d" fill="#3f7a3a"/>' % (tx, ty - 70, 30 + rng.below(16)))
    if "house" in els:
        hx, hy = 300 + rng.below(380), land_y + 40
        out.append('<rect x="%d" y="%d" width="120" height="80" fill="#c9533d"/>' % (hx, hy - 80))
        out.append('<polygon points="%d,%d %d,%d %d,%d" fill="#5b2b22"/>' % (hx - 12, hy - 80, hx + 60, hy - 130, hx + 132, hy - 80))
        out.append('<rect x="%d" y="%d" width="24" height="40" fill="#3a2418"/>' % (hx + 48, hy - 40))
        out.append('<rect x="%d" y="%d" width="22" height="20" fill="%s"/>' % (hx + 14, hy - 66, p[5]))
    if "flowers" in els or "meadow" in els:
        for _ in range(60 if "flowers" in els else 20):
            fx, fy = rng.below(W), land_y + 30 + rng.below(H - land_y - 30)
            col = rng.pick(["#ff6b8b", "#ffd34d", "#ffffff", "#b07cff", "#ff8a3d"]) if "flowers" in els else "#7fbf6a"
            out.append('<circle cx="%d" cy="%d" r="%d" fill="%s"/>' % (fx, fy, 4 + rng.below(4), col))
    if "lighthouse" in els:
        lx = 120 + rng.below(160)
        ly = horizon + 10
        out.append('<polygon points="%d,%d %d,%d %d,%d %d,%d" fill="#f3f1ea"/>' % (lx - 30, ly, lx + 30, ly, lx + 18, ly - 220, lx - 18, ly - 220))
        for k in range(3):
            out.append('<rect x="%d" y="%d" width="%d" height="22" fill="#c43b33"/>' % (lx - 28 + k * 4, ly - 60 - k * 60, 56 - k * 8))
        out.append('<rect x="%d" y="%d" width="44" height="30" fill="%s"/>' % (lx - 22, ly - 252, p[5]))
        out.append('<polygon points="%d,%d %d,%d %d,%d" fill="%s" opacity="0.25"/>' % (lx, ly - 238, lx + 560, ly - 300, lx + 560, ly - 170, p[5]))
    if "boat" in els:
        bx, by = 520 + rng.below(300), horizon + 70
        out.append('<path d="M%d %d L%d %d L%d %d L%d %d Z" fill="#5b3a29"/>' % (bx - 70, by, bx + 70, by, bx + 50, by + 24, bx - 50, by + 24))
        out.append('<polygon points="%d,%d %d,%d %d,%d" fill="#ffffff"/>' % (bx, by - 110, bx, by - 6, bx + 60, by - 6))
    if "birds" in els or "sea" in els:
        for _ in range(4 + rng.below(4)):
            bx, by = rng.below(W), 80 + rng.below(160)
            out.append('<path d="M%d %d q 10 -10 20 0 q 10 -10 20 0" stroke="%s" stroke-width="3" fill="none"/>' % (bx, by, p[6]))
    out.append("</svg>")
    return {"svg": "\n".join(out), "light": light, "elements": els, "kind": "scene", "engine": "local"}


def abstract(rng: core.Rng, p: list[str]) -> list[str]:
    """an abstract composition: overlapping translucent circles and bands in the palette

    Lean:
        def abstractShapes : Nat := 18
        #guard abstractShapes == 18                                        -- py: len(abstract(core.Rng(4), PALETTES["day"])) == 18
    """
    out: list[str] = []
    for k in range(12):
        out.append('<circle cx="%d" cy="%d" r="%d" fill="%s" opacity="0.%d"/>' % (rng.below(W), rng.below(H), 40 + rng.below(180), p[2 + k % 4], 3 + rng.below(5)))
    for _ in range(6):
        y = rng.below(H)
        out.append('<rect x="0" y="%d" width="%d" height="%d" fill="%s" opacity="0.2"/>' % (y, W, 10 + rng.below(40), rng.pick(p[2:6])))
    return out


IMAGE_SYSTEM = ("You are VeriWave's image engine. Draw the picture the user describes as ONE complete SVG document: "
                "viewBox=\"0 0 1024 640\", no external references, no scripts, no text unless asked. Return only the SVG.")


def safe_svg(svg: str) -> str:
    """an SVG made safe to show: must start with <svg and end with </svg>, no scripts, event handlers or external links; '' if not

    Lean:
        def banned : List String := ["<script", "javascript:", "onload=", "onclick=", "onerror=", "onmouseover=", "href=\"http", "<foreignobject"]
        def safeSvg (s : String) : String :=
          let t := s.trim
          let low := lower t
          if low.startsWith "<svg" && low.endsWith "</svg>" && !banned.any (fun b => (low.splitOn b).length > 1) then t else ""
        #guard safeSvg "<svg><circle/></svg>" == "<svg><circle/></svg>"    -- py: safe_svg("<svg><circle/></svg>") == "<svg><circle/></svg>"
        #guard safeSvg "<svg onload=\"x()\"></svg>" == ""                  -- py: safe_svg('<svg onload="x()"></svg>') == ""
    """
    t = svg.strip()
    low = core.lower(t)
    bad = ["<script", "javascript:", "onload=", "onclick=", "onerror=", "onmouseover=", 'href="http', "<foreignobject"]
    if low.startswith("<svg") and low.endswith("</svg>") and not any(b in low for b in bad):
        return t
    return ""
