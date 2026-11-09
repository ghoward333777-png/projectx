"""Every user interface VeriWave can put on screen: its own modes and every QueryBook screen.

QueryBook's applications share one tab mechanism (`apps/_core/ui/qb.js`): `<app url>#<tab>` opens that tab directly, so
every tab of every application is its own interface here. VeriWave's own modes are built into its window. The Book
Intelligence Studio (this repository's PHP app) carries QueryBook's authoring and learning-plan features.

Pure data and pure functions: no I/O.

Lean:
    structure Iface where
      id : String
      app : String
      hash : String
      admin : Bool
    deriving Repr, BEq
"""
from __future__ import annotations

# group id -> display name, in rail order
GROUPS: dict[str, str] = {
    "veriwave": "VeriWave",
    "ask": "Ask & Answer",
    "language": "Language Builder",
    "stem": "Math, Science & Engineering",
    "history": "History & News",
    "video": "Video Studio",
    "author": "Author, Learn & Publish",
    "operate": "Operate (Control Panel)",
}

# (id, name, group, app, hash, admin_only, what it is for, registry ui_groups it serves)
_TABLE: tuple[tuple[str, str, str, str, str, bool, str, tuple[str, ...]], ...] = (
    # VeriWave's own modes
    ("vw-chat", "Chat", "veriwave", "veriwave", "chat", False,
     "One conversation for everything: VeriWave decides whether each message is a question, a coding job or a creation.", ("ask",)),
    ("vw-answer", "Answer", "veriwave", "veriwave", "answer", False,
     "Cite-or-refuse answers: a verdict (VERIFIED / CONTRADICTED / UNKNOWN), numbered citations with trust, a provenance hash.", ("ask", "trust")),
    ("vw-code", "Code", "veriwave", "veriwave", "code", False,
     "Describe an application; get its files, a live preview and a download.", ()),
    ("vw-text", "Create: Text", "veriwave", "veriwave", "text", False,
     "Stories, articles, poems, letters, summaries and lists from a prompt, grounded in QueryBook facts.", ("author",)),
    ("vw-image", "Create: Image", "veriwave", "veriwave", "image", False,
     "Pictures from a prompt, as scalable vector images.", ("video",)),
    ("vw-video", "Create: Video", "veriwave", "veriwave", "video", False,
     "Short videos from a prompt: a storyboard, an animated film and captions.", ("video",)),
    ("vw-audio", "Create: Audio", "veriwave", "veriwave", "audio", False,
     "Speech, music and sound effects from a prompt, as WAV audio.", ("language",)),
    ("vw-features", "Feature Registry", "veriwave", "veriwave", "features", False,
     "All 407 features of the QueryBook Composite Feature Registry v71: status, rule, formula and the screen that serves each.", ()),
    ("vw-workspace", "Workspace", "veriwave", "veriwave", "workspace", False,
     "Any set of the interfaces below, side by side, as tabs or a grid.", ()),
    # QueryBook: one-window shell
    ("qb-shell", "QueryBook one window", "ask", "shell", "", False,
     "QueryBook's own window: area rail, Reader/Author/Instructor/Admin switch and the Ask box.", ("ask",)),
    # Language Builder
    ("lang-learn", "Language Lab", "language", "language", "learn", False, "Pick, type or say, translate, hear and speak back.", ("language", "learn")),
    ("lang-lookup", "Look up", "language", "language", "lookup", False, "Word meanings (Webster 1913, 101,080 headwords) and translations.", ("language", "knowledge")),
    ("lang-translate", "Translate", "language", "language", "translate", False, "Offline translation with where every word came from.", ("language",)),
    ("lang-speech", "Speech", "language", "language", "speech", False, "Text to speech, any voice, speed or whisper; speech to text.", ("language",)),
    ("lang-science", "Speech science", "language", "language", "science", False, "Measurements behind speech: pitch, formants, whispers.", ("language",)),
    ("lang-photoreal", "Photo Real Lab", "language", "language", "photoreal", False, "Avatars, faces and lip-sync calibration.", ("language", "video")),
    ("lang-verify", "Verify (proof)", "language", "language", "verify", False, "Proof checks for the language data.", ("trust",)),
    ("lang-build", "Build", "language", "language", "build", True, "Build the word lists and dictionaries.", ("knowledge",)),
    ("lang-agents", "Language agents", "language", "language", "agents", True, "The application's agents.", ("system",)),
    ("lang-devices", "Language devices", "language", "language", "devices", True, "Devices and their API.", ("system",)),
    ("lang-commons", "Language harvesting", "language", "language", "commons", True, "Harvesting and the shared facts.", ("harvest",)),
    ("lang-data", "Language data & backups", "language", "language", "data", True, "Data and backups.", ("system",)),
    ("lang-diag", "Language diagnostics", "language", "language", "diag", True, "Diagnostics.", ("system",)),
    ("lang-help", "Language help", "language", "language", "help", False, "Help.", ()),
    # STEM
    ("stem-ask", "Calculate", "stem", "stem", "ask", False, "Calculations, conversions, molar masses and elements.", ("stem", "ask")),
    ("stem-formulas", "Formulas", "stem", "stem", "formulas", False, "The 35 STEM formulas, each solvable for any quantity (proved in Lean).", ("stem",)),
    ("stem-elements", "Elements", "stem", "stem", "elements", False, "The periodic table.", ("stem",)),
    ("stem-constants", "Constants", "stem", "stem", "constants", False, "Physical constants.", ("stem",)),
    ("stem-saved", "Saved answers", "stem", "stem", "saved", False, "Answers you kept.", ("stem",)),
    ("stem-agents", "STEM agents", "stem", "stem", "agents", True, "The application's agents.", ("system",)),
    ("stem-devices", "STEM devices", "stem", "stem", "devices", True, "Devices and their API.", ("system",)),
    ("stem-commons", "STEM harvesting", "stem", "stem", "commons", True, "Harvesting and the shared facts.", ("harvest",)),
    ("stem-data", "STEM data & backups", "stem", "stem", "data", True, "Data and backups.", ("system",)),
    ("stem-diag", "STEM diagnostics", "stem", "stem", "diag", True, "Diagnostics.", ("system",)),
    ("stem-help", "STEM help", "stem", "stem", "help", False, "Help.", ()),
    # History & News
    ("hist-search", "Search history", "history", "facts", "search", False, "Sourced historical facts.", ("history", "knowledge")),
    ("hist-timeline", "Timeline", "history", "facts", "timeline", False, "Facts on a timeline.", ("history", "insight")),
    ("hist-news", "News", "history", "facts", "news", False, "Headlines from your feeds, promotable to facts.", ("history",)),
    ("hist-sources", "Sources", "history", "facts", "sources", False, "Every source and what it supports.", ("trust",)),
    ("hist-add", "Add a fact", "history", "facts", "add", False, "Add a fact with its source.", ("knowledge",)),
    ("hist-agents", "History agents", "history", "facts", "agents", True, "The application's agents.", ("system",)),
    ("hist-devices", "History devices", "history", "facts", "devices", True, "Devices and their API.", ("system",)),
    ("hist-commons", "History harvesting", "history", "facts", "commons", True, "Harvesting and the shared facts.", ("harvest",)),
    ("hist-data", "History data & backups", "history", "facts", "data", True, "Data and backups.", ("system",)),
    ("hist-diag", "History diagnostics", "history", "facts", "diag", True, "Diagnostics.", ("system",)),
    ("hist-help", "History help", "history", "facts", "help", False, "Help.", ()),
    # Video Studio
    ("video-studio", "Studio", "video", "video", "studio", False, "Plan and render videos with personas, narration and lip-sync.", ("video",)),
    ("video-library", "Clip library", "video", "video", "library", False, "Your clips.", ("video",)),
    ("video-outputs", "Finished videos", "video", "video", "outputs", False, "Rendered videos.", ("video",)),
    ("video-settings", "Video settings", "video", "video", "settings", True, "Engines and keys.", ("system",)),
    ("video-diag", "Video diagnostics", "video", "video", "diag", True, "Diagnostics.", ("system",)),
    ("video-help", "Video help", "video", "video", "help", False, "Help.", ()),
    # Book Intelligence Studio (this repository's PHP app)
    ("book-writer", "Book Writer", "author", "books", "amazon-book-writer.php", False,
     "Outline to finished manuscript, Word/EPUB/print exports.", ("author",)),
    ("book-lab", "Book Lab (QueryBook learning plan)", "author", "books", "book-lab.php", False,
     "Quality certification and the QueryBook enhancement plan: quizzes and takeaways per chapter.", ("learn", "author", "insight")),
    ("book-projects", "Book projects", "author", "books", "book-projects.php", False, "Every generated book, saved.", ("author",)),
    ("book-guide", "Book Studio guide", "author", "books", "user-guide.php", False, "How the studio works.", ()),
    # Control Panel
    ("ctl-overview", "Overview", "operate", "control", "overview", True, "Live statistics, trends and gauges.", ("insight", "system")),
    ("ctl-bulk", "Harvest (bulk datasets)", "operate", "control", "bulk", True, "Wikidata, PubChem and other bulk loads.", ("harvest",)),
    ("ctl-target", "Harvest targets", "operate", "control", "target", True, "What to harvest next.", ("harvest",)),
    ("ctl-filter", "Filters", "operate", "control", "filter", True, "What is kept out.", ("harvest", "trust")),
    ("ctl-facts", "Knowledge (shared facts)", "operate", "control", "facts", True, "The shared facts with status and evidence.", ("knowledge",)),
    ("ctl-exemplars", "Exemplars", "operate", "control", "exemplars", True, "Worked examples.", ("knowledge",)),
    ("ctl-self", "Self-knowledge", "operate", "control", "self", True, "What QueryBook knows about itself.", ("system", "insight")),
    ("ctl-apis", "APIs & connections", "operate", "control", "apis", True, "Outside services and keys.", ("system",)),
    ("ctl-audit", "Trust & Security", "operate", "control", "audit", True, "Audit trail, rules and alerts.", ("trust",)),
    ("ctl-diag", "System", "operate", "control", "diag", True, "Diagnostics and repair.", ("system",)),
    ("ctl-help", "Control Panel help", "operate", "control", "help", False, "Help.", ()),
)

APPS: dict[str, str] = {
    "veriwave": "VeriWave",
    "shell": "QueryBook one window",
    "language": "Language Builder",
    "stem": "Math, Science & Engineering",
    "facts": "History & News",
    "video": "Video Studio",
    "control": "Control Panel",
    "books": "Book Intelligence Studio",
}


def catalog() -> list[dict]:
    """every interface as plain data, in display order

    Lean:
        def catalogSize : Nat := 67
        #guard catalogSize == 67                              -- py: len(catalog()) == 67
        #guard catalogSize - 9 == 58                          -- py: sum(1 for i in catalog() if not i["builtin"]) == 58
    """
    return [{"id": i, "name": n, "group": g, "group_name": GROUPS[g], "app": a, "app_name": APPS[a], "hash": h,
             "admin": adm, "about": about, "serves": list(serves), "builtin": a == "veriwave"}
            for (i, n, g, a, h, adm, about, serves) in _TABLE]


def by_id(iid: str) -> dict | None:
    """the interface with this id, or None

    Lean:
        def byId (items : List Iface) (iid : String) : Option Iface := items.find? (·.id == iid)
        theorem byId_id (items : List Iface) (iid : String) (i : Iface) (h : byId items iid = some i) : i.id = iid := by
          have := List.find?_some h
          simpa using this
        #guard byId [⟨"a", "x", "", false⟩] "b" == none       -- py: by_id("no-such-screen") is None
    """
    for item in catalog():
        if item["id"] == iid:
            return item
    return None


def visible(items: list[dict], role: str) -> list[dict]:
    """QueryBook's rule: Operate screens and admin tabs are for the Admin role only

    Lean:
        def visible (items : List Iface) (role : String) : List Iface := items.filter (fun i => role == "Admin" || !i.admin)
        theorem visible_admin (items : List Iface) : visible items "Admin" = items := by
          simp [visible]
        theorem visible_hides (items : List Iface) (role : String) (h : role ≠ "Admin") (i : Iface)
            (hi : i ∈ visible items role) : i.admin = false := by
          simp [visible, List.mem_filter] at hi
          rcases hi with ⟨_, h2⟩
          rcases h2 with h2 | h2
          · exact absurd h2 h
          · exact h2
        #guard (visible [⟨"a", "x", "", true⟩, ⟨"b", "x", "", false⟩] "Reader").length == 1   -- py: all(not i["admin"] for i in visible(catalog(), "Reader"))
    """
    return [i for i in items if role == "Admin" or not i["admin"]]


def url_for(item: dict, app_urls: dict[str, str]) -> str | None:
    """where an interface opens, given the running applications' base URLs; None while its application is not running

    Lean:
        def stripSlash (s : String) : String := if s.endsWith "/" then s.dropRight 1 else s
        def urlFor (i : Iface) (base : Option String) : Option String :=
          if i.app == "veriwave" then some ("#" ++ i.hash) else
          match base with
          | none => none
          | some b => if i.app == "books" then some (stripSlash b ++ "/" ++ i.hash)
                      else some (b ++ (if i.hash == "" then "" else "#" ++ i.hash))
        theorem urlFor_none (i : Iface) (h : i.app ≠ "veriwave") : urlFor i none = none := by
          simp [urlFor, h]
        #guard urlFor ⟨"stem-ask", "stem", "ask", false⟩ (some "http://127.0.0.1:8786/") == some "http://127.0.0.1:8786/#ask"   -- py: url_for(by_id("stem-ask"), {"stem": "http://127.0.0.1:8786/"}) == "http://127.0.0.1:8786/#ask"
        #guard urlFor ⟨"vw-code", "veriwave", "code", false⟩ none == some "#code"   -- py: url_for(by_id("vw-code"), {}) == "#code"
    """
    if item["app"] == "veriwave":
        return "#" + item["hash"]
    base = app_urls.get(item["app"])
    if not base:
        return None
    if item["app"] == "books":
        return base.rstrip("/") + "/" + item["hash"]
    return base + ("#" + item["hash"] if item["hash"] else "")


def primary_for_group(ui_group: str) -> str:
    """the interface that opens first for a registry ui_group

    Lean:
        def primaryForGroup (g : String) : String :=
          match g with
          | "ask" => "vw-answer" | "knowledge" => "ctl-facts" | "trust" => "ctl-audit" | "system" => "ctl-diag"
          | "harvest" => "ctl-bulk" | "insight" => "ctl-overview" | "author" => "book-writer" | "learn" => "book-lab"
          | "language" => "lang-learn" | "video" => "video-studio" | "stem" => "stem-ask" | "history" => "hist-search"
          | _ => "vw-features"
        #guard primaryForGroup "learn" == "book-lab"           -- py: primary_for_group("learn") == "book-lab"
        #guard primaryForGroup "?" == "vw-features"            -- py: primary_for_group("?") == "vw-features"
    """
    return {
        "ask": "vw-answer", "knowledge": "ctl-facts", "trust": "ctl-audit", "system": "ctl-diag", "harvest": "ctl-bulk",
        "insight": "ctl-overview", "author": "book-writer", "learn": "book-lab", "language": "lang-learn",
        "video": "video-studio", "stem": "stem-ask", "history": "hist-search",
    }.get(ui_group, "vw-features")
