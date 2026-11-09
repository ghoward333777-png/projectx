"""VeriWave's router: which capability a chat message is asking for.

Pure and ordered: an explicit "/mode" prefix wins; then requests to open a QueryBook screen; then creation requests
(code before media, media before text, because "write code" and "make a video" also contain writing words); then
greetings and help; everything else is a question for the Answer engine.

Lean:
    inductive Route where
      | answer | code | text | image | video | audio | screen | chat
    deriving Repr, BEq, DecidableEq
    def Route.name : Route → String
      | .answer => "answer" | .code => "code" | .text => "text" | .image => "image"
      | .video => "video" | .audio => "audio" | .screen => "open" | .chat => "chat"
"""
from __future__ import annotations

from . import core

ROUTES = ("answer", "code", "text", "image", "video", "audio", "open", "chat")
MAKE = ["make", "build", "create", "code", "write", "generate", "program", "develop", "design", "produce", "compose", "draft",
        "give me", "i want", "i need", "can you make", "show me"]
CODE_NOUNS = ["app", "application", "website", "web site", "web page", "webpage", "landing page", "game", "program", "script",
              "function", "calculator", "to do", "todo", "tracker", "dashboard", "tool", "cli", "api", "code", "html",
              "javascript", "python", "stopwatch", "timer", "converter", "quiz app", "notes app", "class", "component"]
IMAGE_WORDS = ["image", "picture", "drawing", "draw", "paint", "painting", "illustration", "illustrate", "logo", "poster",
               "icon", "sketch", "artwork", "wallpaper", "photo", "landscape picture", "portrait"]
VIDEO_WORDS = ["video", "animation", "animate", "movie", "film", "clip", "trailer", "slideshow", "storyboard"]
AUDIO_WORDS = ["audio", "sound", "music", "song", "melody", "tune", "jingle", "speech", "narrate", "narration", "voice",
               "say", "read aloud", "podcast", "sound effect", "ringtone", "beat", "rain sounds", "ocean sounds"]
TEXT_WORDS = ["story", "poem", "essay", "article", "blog", "email", "letter", "summary", "summarize", "summarise", "list",
              "description", "speech text", "report", "outline", "haiku", "limerick", "tweet", "post", "paragraph", "bio",
              "cover letter", "toast", "slogan", "tagline", "recipe"]
OPEN_WORDS = ["open", "show", "go to", "switch to", "take me to", "launch"]
SCREEN_WORDS = ["language lab", "stem", "history", "video studio", "control panel", "book writer", "book lab", "workspace",
                "feature registry", "registry", "harvest", "translate", "formulas", "timeline", "elements", "querybook"]
GREETINGS = ["hi", "hello", "hey", "thanks", "thank you", "good morning", "good evening", "help", "who are you",
             "what can you do", "what are you"]


def explicit(message: str) -> str:
    """the route named by a leading '/answer', '/code', '/text', '/image', '/video', '/audio', '/open' or '/chat', or ''

    Lean:
        def routeOfName (n : String) : Option Route :=
          match n with
          | "answer" => some .answer | "code" => some .code | "text" => some .text | "image" => some .image
          | "video" => some .video | "audio" => some .audio | "open" => some .screen | "chat" => some .chat | _ => none
        def explicitRoute (msg : String) : Option Route :=
          let t := msg.trimLeft
          if t.startsWith "/" then routeOfName (lower ((t.drop 1).takeWhile (fun c => c != ' '))) else none
        #guard explicitRoute "/image a red fox" == some .image        -- py: explicit("/image a red fox") == "image"
        #guard explicitRoute "/nope x" == none                         -- py: explicit("/nope x") == ""
        #guard explicitRoute "hello" == none                           -- py: explicit("hello") == ""
    """
    t = message.lstrip()
    if not t.startswith("/"):
        return ""
    name = core.lower(t[1:].split(" ", 1)[0])
    return name if name in ROUTES else ""


def strip_explicit(message: str) -> str:
    """the message without its '/mode' prefix

    Lean:
        def stripExplicit (msg : String) : String :=
          match explicitRoute msg with
          | some _ => ((msg.trimLeft.dropWhile (fun c => c != ' ')).trimLeft)
          | none => msg
        #guard stripExplicit "/image a red fox" == "a red fox"          -- py: strip_explicit("/image a red fox") == "a red fox"
    """
    if not explicit(message):
        return message
    t = message.lstrip()
    i = t.find(" ")
    return t[i:].lstrip() if i >= 0 else ""


def wants_making(ws: list[str]) -> bool:
    """whether the message asks VeriWave to make something

    Lean:
        def makeWords : List String := ["make", "build", "create", "code", "write", "generate", "program", "develop",
          "design", "produce", "compose", "draft", "give me", "i want", "i need", "can you make", "show me"]
        def wantsMaking (ws : List String) : Bool := hasAny ws makeWords
        #guard wantsMaking (words "Please build a timer")              -- py: wants_making(core.words("Please build a timer"))
        #guard !wantsMaking (words "When was Rome founded?")          -- py: not wants_making(core.words("When was Rome founded?"))
    """
    return core.has_any(ws, MAKE)


def route(message: str) -> str:
    """the capability a chat message asks for

    Lean:
        def codeNouns : List String := ["app", "application", "website", "web site", "web page", "webpage", "landing page",
          "game", "program", "script", "function", "calculator", "to do", "todo", "tracker", "dashboard", "tool", "cli",
          "api", "code", "html", "javascript", "python", "stopwatch", "timer", "converter", "quiz app", "notes app",
          "class", "component"]
        def imageWords : List String := ["image", "picture", "drawing", "draw", "paint", "painting", "illustration",
          "illustrate", "logo", "poster", "icon", "sketch", "artwork", "wallpaper", "photo", "landscape picture", "portrait"]
        def videoWords : List String := ["video", "animation", "animate", "movie", "film", "clip", "trailer", "slideshow", "storyboard"]
        def audioWords : List String := ["audio", "sound", "music", "song", "melody", "tune", "jingle", "speech", "narrate",
          "narration", "voice", "say", "read aloud", "podcast", "sound effect", "ringtone", "beat", "rain sounds", "ocean sounds"]
        def textWords : List String := ["story", "poem", "essay", "article", "blog", "email", "letter", "summary", "summarize",
          "summarise", "list", "description", "speech text", "report", "outline", "haiku", "limerick", "tweet", "post",
          "paragraph", "bio", "cover letter", "toast", "slogan", "tagline", "recipe"]
        def openWords : List String := ["open", "show", "go to", "switch to", "take me to", "launch"]
        def screenWords : List String := ["language lab", "stem", "history", "video studio", "control panel", "book writer",
          "book lab", "workspace", "feature registry", "registry", "harvest", "translate", "formulas", "timeline", "elements", "querybook"]
        def greetings : List String := ["hi", "hello", "hey", "thanks", "thank you", "good morning", "good evening", "help",
          "who are you", "what can you do", "what are you"]
        def routeWords (ws : List String) : Route :=
          if ws.isEmpty then .chat
          else if hasAny ws openWords && hasAny ws screenWords && decide (ws.length ≤ 8) then .screen
          else if wantsMaking ws && hasAny ws codeNouns then .code
          else if hasAny ws ["draw", "paint", "sketch", "illustrate"] || (wantsMaking ws && hasAny ws imageWords) then .image
          else if hasAny ws ["animate"] || (wantsMaking ws && hasAny ws videoWords) then .video
          else if hasAny ws ["narrate", "read aloud"] || (hasAny ws ["say"] && decide (ws.length ≤ 3)) ||
                  (wantsMaking ws && hasAny ws audioWords) then .audio
          else if wantsMaking ws && hasAny ws textWords then .text
          else if decide (ws.length ≤ 4) && hasAny ws greetings then .chat
          else .answer
        def route (msg : String) : Route :=
          match explicitRoute msg with
          | some r => r
          | none => routeWords (words msg)
        theorem route_explicit (msg : String) (r : Route) (h : explicitRoute msg = some r) : route msg = r := by
          simp [route, h]
        theorem routeWords_nil : routeWords [] = .chat := rfl
        #guard route "Build me a to-do app" == .code                    -- py: route("Build me a to-do app") == "code"
        #guard route "Draw a lighthouse at sunset" == .image            -- py: route("Draw a lighthouse at sunset") == "image"
        #guard route "make a short video about bees" == .video          -- py: route("make a short video about bees") == "video"
        #guard route "compose a calm melody" == .audio                  -- py: route("compose a calm melody") == "audio"
        #guard route "write a poem about the sea" == .text              -- py: route("write a poem about the sea") == "text"
        #guard route "When was the printing press invented?" == .answer  -- py: route("When was the printing press invented?") == "answer"
        #guard route "open the language lab" == .screen                   -- py: route("open the language lab") == "open"
        #guard route "hello" == .chat                                   -- py: route("hello") == "chat"
        #guard route "/code a timer" == .code                           -- py: route("/code a timer") == "code"
        #guard route "write a python script that counts words" == .code -- py: route("write a python script that counts words") == "code"
    """
    e = explicit(message)
    if e:
        return e
    ws = core.words(message)
    if not ws:
        return "chat"
    if core.has_any(ws, OPEN_WORDS) and core.has_any(ws, SCREEN_WORDS) and len(ws) <= 8:
        return "open"
    making = wants_making(ws)
    if making and core.has_any(ws, CODE_NOUNS):
        return "code"
    if core.has_any(ws, ["draw", "paint", "sketch", "illustrate"]) or (making and core.has_any(ws, IMAGE_WORDS)):
        return "image"
    if core.has_any(ws, ["animate"]) or (making and core.has_any(ws, VIDEO_WORDS)):
        return "video"
    if (core.has_any(ws, ["narrate", "read aloud"]) or (core.has_any(ws, ["say"]) and len(ws) <= 3)
            or (making and core.has_any(ws, AUDIO_WORDS))):
        return "audio"
    if making and core.has_any(ws, TEXT_WORDS):
        return "text"
    if len(ws) <= 4 and core.has_any(ws, GREETINGS):
        return "chat"
    return "answer"


def screen_for(message: str) -> str:
    """the interface id an 'open …' message names, or ''

    Lean:
        def screenTable : List (String × String) := [("language lab", "lang-learn"), ("translate", "lang-translate"),
          ("video studio", "video-studio"), ("control panel", "ctl-overview"), ("book writer", "book-writer"),
          ("book lab", "book-lab"), ("feature registry", "vw-features"), ("registry", "vw-features"), ("workspace", "vw-workspace"),
          ("harvest", "ctl-bulk"), ("formulas", "stem-formulas"), ("elements", "stem-elements"), ("timeline", "hist-timeline"),
          ("history", "hist-search"), ("stem", "stem-ask"), ("querybook", "qb-shell")]
        def screenFor (msg : String) : String :=
          match screenTable.find? (fun p => hasPhrase (words msg) (words p.1)) with
          | some p => p.2
          | none => ""
        #guard screenFor "open the language lab" == "lang-learn"        -- py: screen_for("open the language lab") == "lang-learn"
        #guard screenFor "open the moon" == ""                           -- py: screen_for("open the moon") == ""
    """
    table = [("language lab", "lang-learn"), ("translate", "lang-translate"), ("video studio", "video-studio"),
             ("control panel", "ctl-overview"), ("book writer", "book-writer"), ("book lab", "book-lab"),
             ("feature registry", "vw-features"), ("registry", "vw-features"), ("workspace", "vw-workspace"),
             ("harvest", "ctl-bulk"), ("formulas", "stem-formulas"), ("elements", "stem-elements"),
             ("timeline", "hist-timeline"), ("history", "hist-search"), ("stem", "stem-ask"), ("querybook", "qb-shell")]
    ws = core.words(message)
    for phrase, iid in table:
        if core.has_phrase(ws, core.words(phrase)):
            return iid
    return ""
