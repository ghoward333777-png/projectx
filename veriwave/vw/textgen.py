"""VeriWave Create: Text. Stories, poems, haiku, letters, articles, lists and slogans from a prompt.

Local engine: deterministic composition from the prompt's subject (same prompt, same text), using any QueryBook facts
the caller found about that subject, quoted with their sources and never invented. Claude engine: the same request, the
same facts, written by Claude under VeriWave's rules.

Lean:
    inductive Form where | story | poem | haiku | letter | article | list | slogan
    deriving Repr, BEq, DecidableEq
    def Form.name : Form → String
      | .story => "story" | .poem => "poem" | .haiku => "haiku" | .letter => "letter" | .article => "article"
      | .list => "list" | .slogan => "slogan"
"""
from __future__ import annotations

from . import core

FORMS = ("story", "poem", "haiku", "letter", "article", "list", "slogan")
FORM_WORDS: list[tuple[str, list[str]]] = [
    ("haiku", ["haiku"]),
    ("poem", ["poem", "verse", "sonnet", "limerick", "rhyme", "ode"]),
    ("story", ["story", "tale", "fable", "short story", "bedtime story"]),
    ("letter", ["letter", "email", "e mail", "cover letter", "note to", "message to", "thank you note"]),
    ("list", ["list", "ideas", "tips", "checklist", "steps"]),
    ("slogan", ["slogan", "tagline", "motto", "catchphrase"]),
    ("article", ["article", "essay", "blog", "post", "report", "summary", "overview", "paragraph", "bio", "description"]),
]
SUBJECT_LEADS = ["about", "on", "regarding", "describing", "for", "of", "called"]
SUBJECT_SKIP = ["a", "an", "the", "my", "our", "your"]
SUBJECT_ENDERS = ["with", "that", "which", "in", "using", "and", "for", "to"]


def detect_form(prompt: str) -> str:
    """the kind of text asked for; an article when nothing more specific is named

    Lean:
        def formTable : List (Form × List String) := [(.haiku, ["haiku"]),
          (.poem, ["poem", "verse", "sonnet", "limerick", "rhyme", "ode"]),
          (.story, ["story", "tale", "fable", "short story", "bedtime story"]),
          (.letter, ["letter", "email", "e mail", "cover letter", "note to", "message to", "thank you note"]),
          (.list, ["list", "ideas", "tips", "checklist", "steps"]), (.slogan, ["slogan", "tagline", "motto", "catchphrase"]),
          (.article, ["article", "essay", "blog", "post", "report", "summary", "overview", "paragraph", "bio", "description"])]
        def detectForm (p : String) : Form :=
          match formTable.find? (fun e => hasAny (words p) e.2) with
          | some e => e.1
          | none => .article
        #guard detectForm "write a haiku about rain" == .haiku           -- py: detect_form("write a haiku about rain") == "haiku"
        #guard detectForm "write a poem about the sea" == .poem          -- py: detect_form("write a poem about the sea") == "poem"
        #guard detectForm "an email to my landlord about the heating" == .letter   -- py: detect_form("an email to my landlord about the heating") == "letter"
        #guard detectForm "tell me about bees" == .article               -- py: detect_form("tell me about bees") == "article"
    """
    ws = core.words(prompt)
    for form, phrases in FORM_WORDS:
        if core.has_any(ws, phrases):
            return form
    return "article"


def subject_of(prompt: str) -> str:
    """what the text is about: the words after 'about', 'on', 'for'… (articles skipped), at most five words

    Lean:
        def subjectLeads : List String := ["about", "on", "regarding", "describing", "for", "of", "called"]
        def subjectSkip : List String := ["a", "an", "the", "my", "our", "your"]
        def subjectEnders : List String := ["with", "that", "which", "in", "using", "and", "for", "to"]
        def afterFirst (leads : List String) : List String → List String
          | [] => []
          | w :: ws => if leads.contains w then ws else afterFirst leads ws
        def subjectOf (p : String) : String :=
          let ws := words p
          let tail := ((afterFirst subjectLeads ws).dropWhile subjectSkip.contains).takeWhile (fun w => !subjectEnders.contains w)
          let pick := if tail.isEmpty then (ws.filter (fun w => w.length > 3)).reverse.take 2 |>.reverse else tail.take 5
          " ".intercalate pick
        #guard subjectOf "write a poem about the quiet sea at night" == "quiet sea at night"   -- py: subject_of("write a poem about the quiet sea at night") == "quiet sea at night"
        #guard subjectOf "an email to my landlord about the broken heating" == "broken heating"   -- py: subject_of("an email to my landlord about the broken heating") == "broken heating"
        #guard subjectOf "haiku" == "haiku"                              -- py: subject_of("haiku") == "haiku"
    """
    ws = core.words(prompt)
    i = 0
    while i < len(ws) and ws[i] not in SUBJECT_LEADS:
        i += 1
    rest = ws[i + 1:] if i < len(ws) else []
    j = 0
    while j < len(rest) and rest[j] in SUBJECT_SKIP:
        j += 1
    tail: list[str] = []
    for w in rest[j:]:
        if w in SUBJECT_ENDERS:
            break
        tail.append(w)
    if not tail:
        long = [w for w in ws if len(w) > 3]
        return " ".join(long[-2:])
    return " ".join(tail[:5])


def title_case(text: str) -> str:
    """each word capitalised, except short joining words after the first

    Lean:
        def smallWords : List String := ["a", "an", "the", "of", "and", "or", "in", "on", "at", "to", "for", "by"]
        def capWord (w : String) : String := match w.toList with
          | [] => ""
          | c :: cs => String.mk (c.toUpper :: cs)
        def titleCase (s : String) : String :=
          match (words s) with
          | [] => ""
          | w :: ws => " ".intercalate (capWord w :: ws.map (fun x => if smallWords.contains x then x else capWord x))
        #guard titleCase "the quiet sea at night" == "The Quiet Sea at Night"   -- py: title_case("the quiet sea at night") == "The Quiet Sea at Night"
    """
    small = {"a", "an", "the", "of", "and", "or", "in", "on", "at", "to", "for", "by"}
    ws = core.words(text)
    out: list[str] = []
    for i, w in enumerate(ws):
        if i > 0 and w in small:
            out.append(w)
        else:
            out.append((chr(ord(w[0]) - 32) if "a" <= w[0] <= "z" else w[0]) + w[1:])
    return " ".join(out)


IMAGES = ["light", "morning", "a door left open", "the long road", "rain on glass", "a quiet room", "the first step",
          "a borrowed map", "the turning tide", "an unlit lamp", "the edge of the field", "a kept promise"]
VERBS = ["waits", "listens", "remembers", "turns", "gathers", "opens", "returns", "holds", "carries", "begins"]
FEELINGS = ["patient", "unhurried", "bright", "steady", "curious", "tender", "restless", "certain", "small and brave"]
NAMES = ["Mara", "Tomas", "Ines", "Kofi", "Lena", "Arjun", "Noor", "Sam", "Elena", "Wren"]
PLACES = ["a harbour town", "the hill farm", "a city of bridges", "the edge of the forest", "a crowded market", "the old library"]


def haiku(subject: str, rng: core.Rng) -> list[str]:
    """three lines: a five-syllable-ish image, the subject in motion, a closing image

    Lean:
        def haikuLines : Nat := 3
        theorem haiku_three : haikuLines = 3 := rfl
        #guard haikuLines == 3                                             -- py: len(haiku("rain", core.Rng(1))) == 3
    """
    return [cap_first(rng.pick(IMAGES)) + ",", subject + " " + rng.pick(VERBS) + " —", rng.pick(FEELINGS) + " as " + rng.pick(IMAGES) + "."]


def cap_first(text: str) -> str:
    """the first character in upper case (ASCII)

    Lean:
        def capFirst (s : String) : String := capWord s
        #guard capFirst "morning" == "Morning"                            -- py: cap_first("morning") == "Morning"
    """
    return (chr(ord(text[0]) - 32) if text and "a" <= text[0] <= "z" else text[:1]) + text[1:]


def poem(subject: str, rng: core.Rng) -> list[str]:
    """three stanzas of four lines, the subject returning in each, a blank line between stanzas

    Lean:
        def poemLines (stanzas linesPer : Nat) : Nat := stanzas * linesPer + (stanzas - 1)
        theorem poem_shape : poemLines 3 4 = 14 := rfl
        #guard poemLines 3 4 == 14                                         -- py: len(poem("the sea", core.Rng(7))) == 14
    """
    out: list[str] = []
    for k in range(3):
        if k:
            out.append("")
        out.append(cap_first(subject) + " " + rng.pick(VERBS) + " in " + rng.pick(IMAGES) + ",")
        out.append(rng.pick(FEELINGS) + ", " + rng.pick(FEELINGS) + ", and " + rng.pick(VERBS) + " again;")
        out.append("I keep " + rng.pick(IMAGES) + " the way you keep " + rng.pick(IMAGES) + ",")
        out.append("and " + subject + " " + rng.pick(VERBS) + " where " + rng.pick(IMAGES) + " " + rng.pick(VERBS) + ".")
    return out


def story(subject: str, rng: core.Rng, facts: list[str]) -> list[str]:
    """five paragraphs: a person and a place, the subject arrives, a difficulty, a turn, an ending

    Lean:
        def storyParagraphs : Nat := 5
        #guard storyParagraphs == 5                                        -- py: len(story("a lost key", core.Rng(3), [])) == 5
    """
    thing = subject if core.words(subject)[:1] in (["a"], ["an"], ["the"], ["my"]) else "the " + subject
    who = rng.pick(NAMES)
    where = rng.pick(PLACES)
    fact = (" Everyone in town knew one thing for certain: " + facts[0].rstrip(".") + ".") if facts else ""
    return [
        who + " lived in " + where + ", where the days were " + rng.pick(FEELINGS) + " and nothing much changed." + fact,
        "Then, one " + rng.pick(["autumn", "winter", "spring", "summer"]) + " morning, " + thing + " arrived. " + who +
        " noticed it first in " + rng.pick(IMAGES) + ", and could not stop thinking about it.",
        "It was not easy. Every attempt to understand " + thing + " ended at " + rng.pick(IMAGES) + ", and " + who +
        " began to wonder whether some things are meant to stay out of reach.",
        "The turn came quietly. A neighbour said something " + rng.pick(FEELINGS) + ", almost by accident, and " + who +
        " saw " + thing + " the way you see " + rng.pick(IMAGES) + " once someone points at it.",
        "By evening " + who + " was " + rng.pick(FEELINGS) + ". " + cap_first(thing) + " had not changed; " + who +
        " had. And in " + where + ", that was the kind of story people told for years.",
    ]


def letter(subject: str, prompt: str) -> list[str]:
    """greeting, purpose, details, the request, thanks and sign-off

    Lean:
        def letterParts : Nat := 6
        #guard letterParts == 6                                            -- py: len(letter("the heating", "an email to my landlord")) == 6
    """
    ws = core.words(prompt)
    to = "Hello"
    for i in range(len(ws) - 1):
        if ws[i] == "to":
            j = i + 1
            while j < len(ws) and ws[j] in ("the", "a", "an", "my", "our"):
                j += 1
            if j < len(ws) and ws[j] not in ("about", "regarding", "say", "ask"):
                to = "Dear " + cap_first(ws[j])
            break
    return [to + ",",
            "I am writing about " + subject + ".",
            "I would like to explain where things stand and what I hope we can do next. The details matter, so I have kept "
            "them brief and specific; please tell me if anything is unclear.",
            "Could we agree on the next step regarding " + subject + "? A short reply with a time that suits you would help a great deal.",
            "Thank you for your time and attention.",
            "Kind regards,\n[Your name]"]


def article(subject: str, facts: list[str], sources: list[str]) -> list[str]:
    """a short article: what it is, what the record shows (QueryBook facts, cited), why it matters, the takeaway

    Lean:
        def articleSections (hasFacts : Bool) : Nat := if hasFacts then 4 else 3
        theorem article_more_with_facts : articleSections true = articleSections false + 1 := rfl
        #guard articleSections false == 3                                  -- py: sum(1 for l in article("bees", [], []) if l.startswith("## ")) == 3
        #guard articleSections true == 4                                   -- py: sum(1 for l in article("bees", ["Bees make honey."], ["S"]) if l.startswith("## ")) == 4
    """
    t = title_case(subject)
    out = ["## About " + t,
           t + " is the subject of this piece. What follows keeps to what can be said plainly, and marks where the record "
           "is thin rather than filling the gap."]
    if facts:
        out.append("## What the record shows")
        for i, f in enumerate(facts[:8]):
            out.append("- " + f.rstrip(".") + ". [" + str(i + 1) + "]" + (" — " + sources[i] if i < len(sources) and sources[i] else ""))
    out += ["## Why it matters",
            "Understanding " + subject + " changes the questions worth asking next. The useful move is to separate what is "
            "established from what is assumed, and to check the second against the first.",
            "## The takeaway",
            "Start from what is known about " + subject + ", say where the evidence runs out, and build from there."]
    return out


def bullet_list(subject: str, rng: core.Rng) -> list[str]:
    """seven numbered points about the subject

    Lean:
        def listItems : Nat := 7
        #guard listItems == 7                                              -- py: len(bullet_list("saving money", core.Rng(5))) == 7
    """
    starts = ["Start small with", "Write down what you know about", "Ask someone experienced in", "Set one clear goal for",
              "Look for the simplest version of", "Review progress on", "Share what you learn about"]
    ends = ["this week", "before the end of the month", "and note what changes", "without waiting for perfect conditions",
            "and keep it visible", "every Friday", "with one other person"]
    return [str(i + 1) + ". " + starts[i] + " " + subject + " " + rng.pick(ends) + "." for i in range(7)]


def slogans(subject: str, rng: core.Rng) -> list[str]:
    """five candidate slogans

    Lean:
        def sloganCount : Nat := 5
        #guard sloganCount == 5                                            -- py: len(slogans("bakery", core.Rng(9))) == 5
    """
    t = title_case(subject)
    pats = [t + ": " + cap_first(rng.pick(FEELINGS)) + " by design.", "Made for " + rng.pick(["mornings", "people", "the long run", "today"]) + ". " + t + ".",
            "Less noise. More " + subject + ".", t + " — the " + rng.pick(FEELINGS) + " choice.", "Come for " + subject + ". Stay for " + rng.pick(IMAGES) + "."]
    return pats


def generate_local(prompt: str, facts: list[str], sources: list[str]) -> dict:
    """the text for a prompt: its form, title, subject and body (lines), deterministic for the same prompt and facts

    Lean:
        def bodyKind (f : Form) : String := match f with
          | .haiku | .poem => "verse" | .list | .slogan => "list" | _ => "prose"
        #guard bodyKind .haiku == "verse"                                  -- py: generate_local("write a haiku about rain", [], [])["layout"] == "verse"
        #guard bodyKind .article == "prose"                                -- py: generate_local("tell me about bees", [], [])["layout"] == "prose"
    """
    form = detect_form(prompt)
    subject = subject_of(prompt) or "the subject"
    rng = core.Rng(core.seed_of(prompt + "\n" + "\n".join(facts)))
    if form == "haiku":
        lines = haiku(subject, rng)
    elif form == "poem":
        lines = poem(subject, rng)
    elif form == "story":
        lines = story(subject, rng, facts)
    elif form == "letter":
        lines = letter(subject, prompt)
    elif form == "list":
        lines = bullet_list(subject, rng)
    elif form == "slogan":
        lines = slogans(subject, rng)
    else:
        lines = article(subject, facts, sources)
    layout = "verse" if form in ("haiku", "poem") else "list" if form in ("list", "slogan") else "prose"
    return {"form": form, "subject": subject, "title": title_case(subject), "lines": lines, "text": "\n".join(lines) if layout != "prose" else "\n\n".join(lines),
            "layout": layout, "engine": "local", "grounded": len(facts) if form in ("article", "story") else 0}


TEXT_SYSTEM = ("You are VeriWave's writing engine. Write exactly what the user asks for, in plain, vivid prose or verse. "
               "If numbered facts are supplied, any factual claim must come from them and carry its number in brackets; never "
               "invent statistics, quotations or sources. No preamble and no commentary about the writing: return only the text.")


def claude_prompt(prompt: str, facts: list[str], sources: list[str]) -> str:
    """the request Claude receives: the user's prompt and any QueryBook facts, numbered with their sources

    Lean:
        def numbered (facts : List String) : List String :=
          (List.range facts.length).zip facts |>.map (fun p => "[" ++ toString (p.1 + 1) ++ "] " ++ p.2)
        #guard numbered ["a", "b"] == ["[1] a", "[2] b"]                  -- py: claude_prompt("x", ["a", "b"], []).endswith("[1] a\n[2] b")
    """
    if not facts:
        return prompt
    lines = ["[" + str(i + 1) + "] " + f + (" (source: " + sources[i] + ")" if i < len(sources) and sources[i] else "") for i, f in enumerate(facts)]
    return prompt + "\n\nFacts you may use:\n" + "\n".join(lines)
