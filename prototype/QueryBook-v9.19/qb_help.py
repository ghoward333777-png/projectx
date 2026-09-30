#!/usr/bin/env python3
"""
qb_help.py — the Claude-assisted UI help assistant's knowledge base + fallback.

Answers "how do I use this?" questions about the QueryBook prototype UI. When an
API provider is configured (the dashboard's API connector), qb_api calls the LLM
with HELP_SYSTEM as grounding; otherwise a deterministic keyword match over the
same sections answers offline. The assistant explains the UI only — it never
writes Fact Units, so it cannot affect the knowledge store (covenant-safe).
"""
import re

# Each section: keywords to match on, a short title, and the answer text.
SECTIONS = [
    {"k": "what is querybook overview about purpose",
     "t": "What QueryBook is",
     "a": "QueryBook is a deterministic, provenance-tracked knowledge engine. Every answer is "
          "backed by a sourced Fact Unit, and when it has no verified fact it refuses instead of "
          "guessing. It never hallucinates. Language understanding and learning use no LLM; an LLM "
          "may only help phrase answers or power this help assistant."},
    {"k": "pages navigate menu dashboard chat console guide language monitor top bar",
     "t": "The pages (top menu)",
     "a": "Top menu: Dashboard (harvest facts, stats, API key), Language Lab (teach the engine "
          "languages), Chat (ask grounded questions), Console (detailed panels), Guide (docs), and "
          "Monitor (live system state). The green BUILD badge shows the version you are running."},
    {"k": "harvest start collect facts gather 24x7 continuous run data collection",
     "t": "Collecting facts (Dashboard)",
     "a": "On the Dashboard click 'Start harvest' to begin collecting Fact Units, or 'Run 24x7' for "
          "continuous collection. 'Keep awake' stops the PC sleeping during long runs. The stats "
          "tiles show total facts, per-domain counts, and the collection rate."},
    {"k": "language lab english phase 1 2 3 4 build teach start building learn structural",
     "t": "Language Lab — phases",
     "a": "Click 'Start building English' to run Phase 1 (structural learning: letters, syllables, "
          "word patterns — no meaning yet). Phase 2 grounds meaning from a bundled public-domain "
          "dictionary. Phase 3 learns translations (Spanish/French bundled). Phase 4 is speech. "
          "Watch the Facts column climb as each agent runs."},
    {"k": "learn another language german french spanish portuguese italian swedish dutch new",
     "t": "Learn another language",
     "a": "On the Language Lab, use the 'Learn another language' card: pick a language and click "
          "'Start learning'. It builds that language's vocabulary from a bundled public-domain "
          "starter corpus and (with espeak-ng installed) each word's pronunciation. Facts climb in "
          "the Language agents table, just like English. Meaning/translation for new languages needs "
          "a licensed dictionary and is not included yet."},
    {"k": "speak pronounce pronunciation voice audio ipa analyze selector language phase 4",
     "t": "Analyze & Speak (Phase 4)",
     "a": "In the Phase 4 card, choose a language in the dropdown, type a word IN that language "
          "(e.g. German 'Haus'), and click 'Analyze & Speak'. You get the IPA, syllables and stress, "
          "plus audio. It pronounces the text — it does not translate it. English uses your built-in "
          "voice; other languages need espeak-ng (see below)."},
    {"k": "espeak espeak-ng install windows voice missing no phonemizer multilingual",
     "t": "Installing espeak-ng (multilingual voice)",
     "a": "Multilingual pronunciation and voices use espeak-ng (free). Windows: install the "
          "espeak-ng MSI from the espeak-ng GitHub releases, then restart QueryBook. macOS: 'brew "
          "install espeak-ng'. Linux: 'sudo apt install espeak-ng'. English works without it."},
    {"k": "chat ask question grounded answer cite verified unknown refuse",
     "t": "Asking questions (Chat)",
     "a": "The Chat page answers from verified Fact Units and cites them. If nothing meets the trust "
          "threshold it says UNKNOWN rather than inventing an answer. If facts disagree it shows the "
          "competing values without picking a winner."},
    {"k": "api key provider anthropic claude connector configure llm setup sk-ant add",
     "t": "Connecting an API key (provider)",
     "a": "The LLM layer (answer phrasing, hypothesis/simulation, and this help assistant) is "
          "optional. Add an Anthropic API key in the Dashboard's provider settings, or set the "
          "ANTHROPIC_API_KEY environment variable before starting. Note: a claude.ai chat "
          "subscription is NOT an API key — the API needs a key starting with 'sk-ant-' from "
          "console.anthropic.com. Without a key, QueryBook still works deterministically."},
    {"k": "agents kinds roles hypothesis simulation reasoning planner watch web deterministic",
     "t": "The agents",
     "a": "Agents each do one job: deterministic/web harvesters collect facts; grounded_qa/watch "
          "answer and monitor questions; hypothesis and simulation let an LLM propose ideas that the "
          "store must verify (never asserted); reasoning deduces new facts from verified ones; "
          "planner breaks a goal into steps; the language/lang_* agents run the four phases and "
          "language learning. See them live on the Monitor."},
    {"k": "monitor system state status store process subsystem health uptime",
     "t": "The System Monitor",
     "a": "The Monitor page shows live state: build and uptime, the store (total facts, per-domain "
          "counts, blocks, size, last verify), data collection rate, every agent with its status and "
          "facts, and each subsystem (keep-awake watchdog, mirror/offload, LLM provider, voice "
          "engine, self-test). It refreshes automatically."},
    {"k": "store facts fact unit provenance source fingerprint domain dedup",
     "t": "Fact Units & the store",
     "a": "Every piece of knowledge is a Fact Unit: subject-predicate-object plus a source, a trust "
          "score, and a content fingerprint. Identical facts dedup to one. Facts are grouped by "
          "domain (mathematics, language, derived, hypothesis, …). The store is plain files plus an "
          "index; you can copy the store folder to back it up."},
    {"k": "trouble dead link stale server 8090 version old not working refresh build badge",
     "t": "Troubleshooting",
     "a": "If a page looks old or a link seems dead, a previous server is still running on port 8090. "
          "Close the old server window and run the launcher again (it frees 8090), then hard-refresh "
          "the browser (Ctrl+F5). Confirm the green BUILD badge shows the version you expect."},
]

HELP_SYSTEM = (
    "You are the QueryBook help assistant. You help people USE the QueryBook prototype's user "
    "interface. Answer ONLY from the reference below, about how to use the app. Be concise and "
    "practical (a few sentences or short steps). If the answer is not in the reference, say you are "
    "not sure and point them to the Guide page. Do not invent features, keyboard shortcuts, menus, or "
    "facts. Never claim to change data.\n\n=== QUERYBOOK UI REFERENCE ===\n"
    + "\n".join("## %s\n%s" % (s["t"], s["a"]) for s in SECTIONS)
)

_STOP = set("the a an of to in on how do i use what is where can my for and or with it this that you "
            "your me please help".split())


def answer_fallback(question):
    """Deterministic keyword-overlap answer when no LLM provider is configured."""
    qwords = {w for w in re.findall(r"[a-z0-9-]+", (question or "").lower()) if w not in _STOP and len(w) > 2}
    scored = []
    for s in SECTIONS:
        keys = set(s["k"].split()) | set(re.findall(r"[a-z0-9-]+", s["t"].lower()))
        overlap = len(qwords_match(qwords, keys))
        if overlap:
            scored.append((overlap, s))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return ("I'm not sure from the question. Try the Guide page, or ask about: collecting facts, "
                "the Language Lab, learning a language, Analyze & Speak, connecting an API key, the "
                "agents, or the System Monitor.")
    top = scored[:2]
    return "\n\n".join("%s — %s" % (s["t"], s["a"]) for _, s in top)


def qwords_match(qwords, keys):
    hit = set()
    for q in qwords:
        for k in keys:
            if q == k or (len(q) > 3 and (q in k or k in q)):
                hit.add(q)
                break
    return hit
