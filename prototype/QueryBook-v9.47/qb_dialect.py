"""QueryBook — Dialect Parameter Clusters (DPCs)  [deterministic, no LLM]

Dialects are first-class linguistic systems here, not tags on a parent language. Each
Dialect Parameter Cluster (DPC) is a *deterministic* data object the Language Integration
Layer conditions on:

    phonology   — ordered IPA rewrite rules (allophony / phonotactics / cluster rules)
    lexicon     — dialect surface form -> standard form + FU meaning atom + register
    morphosyntax— documented construction notes (e.g. habitual 'be', 'fixin' to')
    prosody     — offline voice variant + rate/pitch + contour note
    sociolect   — regions, registers, typical contexts
    safety      — guidelines + restricted/sensitive usage (avoid caricature)

Everything is rule-based and reproducible: the same text + dialect always yields the same
IPA, the same normalization, and the same detection score. No model asserts facts; the
phonology/lexicon rules are approximate and are labelled as such — the same honesty level
as the rest of the engine's rule-seeded G2P. Pronunciation steering is rendering, not fact
assertion, so the QueryBook covenant is unaffected.

The DPCs below encode well-documented, rule-governed features of each variety. They are
intentionally conservative (a handful of signature features each) and carry sociolect +
safety metadata so output is never a stereotype or a caricature.
"""

import re as _re

# FU meaning atoms a dialect construction can anchor to (dialect-agnostic meaning).
#   FUTURE_INTENT, SECOND_PERSON_PLURAL, HABITUAL_ASPECT, NEGATION, AFFIRMATION,
#   SMALL/INTENSIFIER, KNOW, THERE_DISTAL  — surface differs, meaning is shared.

# --------------------------------------------------------------------------
# Phonology rule helpers. A rule is (compiled_pattern, replacement, note). Rules run in
# order on the bare IPA string (stress marks/slashes stripped first, re-added by caller).
# We treat both 'r' and 'ɹ' as the English rhotic; vowels come from the shared IPA set.
# --------------------------------------------------------------------------
_VOW = "iyɨʉɯuɪʏʊeøɘɵɤoəɛœɜɞʌɔæɐaɶɑɒ"
_RHOTIC = "rɹ"

def _ph(rules):
    return [(_re.compile(p), r, note) for (p, r, note) in rules]

# Non-rhotic: drop a coda rhotic (word-final, or before a consonant). Leaves onset r intact.
_NONRHOTIC = [
    (r"[rɹ](?=[^%s]|$)" % _VOW, "", "non-rhotic: coda /r/ dropped"),
]
# Southern / AAE: pin-pen merger (ɛ -> ɪ before a nasal); final -ing -> -in; cluster reduction.
_PINPEN = [(r"ɛ(?=[mnŋ])", "ɪ", "pin–pen merger: /ɛ/→/ɪ/ before a nasal")]
_GDROP  = [(r"ŋ$", "n", "g-dropping: final /ŋ/→/n/")]
_CLUSTER_RED = [
    (r"(?<=[%s])s?t$" % "szʃʒfvθðpk", "", "final consonant-cluster reduction"),
    (r"(?<=n)d$", "", "final consonant-cluster reduction (nd→n)"),
]
# Cockney / Estuary: th-fronting, h-dropping, t-glottalization.
_THFRONT = [(r"θ", "f", "th-fronting: /θ/→/f/"), (r"ð", "v", "th-fronting: /ð/→/v/")]
_HDROP   = [(r"^h", "", "h-dropping: initial /h/ dropped")]
_TGLOT   = [(r"t(?=[%s])" % _VOW, "ʔ", "t-glottalization: intervocalic /t/→/ʔ/"),
            (r"t$", "ʔ", "t-glottalization: final /t/→/ʔ/")]
# Scottish: strongly rhotic (ensure rhotic kept as a tap/trill 'r').
_SCOT = [(r"ɹ", "r", "rhotic: /ɹ/ realized as a tap/trill /r/")]
# Rioplatense Spanish: sheísmo/zheísmo — /ʝ/ and /ʎ/ → /ʃ/.
_RIOPLATENSE = [(r"ʝ", "ʃ", "sheísmo: /ʝ/→/ʃ/"), (r"ʎ", "ʃ", "sheísmo: /ʎ/→/ʃ/")]


DIALECTS = {
    "en-US-south": {
        "id": "en-US-south", "name": "Southern American English", "parent": "en",
        "summary": "Southern U.S. variety: vowel drawl/lengthening, pin–pen merger, "
                   "g-dropping, 2nd-person-plural 'y'all', 'fixin' to' future.",
        "espeak_voice": "en-us", "prosody": {"rate": 150, "pitch": 52,
            "contour": "drawl; lengthened, often diphthongized stressed vowels"},
        "phonology": _ph(_PINPEN + _GDROP),
        "lexicon": [
            {"surface": "y'all", "standard": "you all", "fu": "SECOND_PERSON_PLURAL", "register": "casual"},
            {"surface": "yall", "standard": "you all", "fu": "SECOND_PERSON_PLURAL", "register": "casual"},
            {"surface": "fixin'", "standard": "about", "fu": "FUTURE_INTENT", "register": "casual"},
            {"surface": "fixin", "standard": "about", "fu": "FUTURE_INTENT", "register": "casual"},
            {"surface": "reckon", "standard": "suppose", "fu": "EPISTEMIC_BELIEF", "register": "casual"},
            {"surface": "yonder", "standard": "over there", "fu": "THERE_DISTAL", "register": "casual"},
            {"surface": "ain't", "standard": "is not", "fu": "NEGATION", "register": "casual"},
        ],
        "morphosyntax": [
            {"pattern": "fixin' to + VERB", "note": "immediate future / intention (FUTURE_INTENT)"},
            {"pattern": "y'all / all y'all", "note": "2nd person plural; 'all y'all' = collective plural"},
            {"pattern": "double modal (might could)", "note": "layered modality, e.g. 'I might could do it'"},
        ],
        "markers": ["y'all", "yall", "fixin", "fixin'", "reckon", "yonder", "ain't", "finna"],
        "spelling_cues": [r"\by'?all\b", r"\bfixin'?\b", r"\breckon\b", r"\byonder\b"],
        "sociolect": {"regions": ["U.S. South"], "registers": ["casual", "intimate", "formal"],
                      "contexts": ["everyday conversation", "storytelling", "community speech"]},
        "safety": {"guidelines": "A full regional system; render features, never an exaggerated drawl "
                                 "or a comedic 'country' voice.",
                   "restricted": ["mock or comedic impersonation"], "sensitive": []},
    },
    "en-US-aae": {
        "id": "en-US-aae", "name": "African American English (AAE)", "parent": "en",
        "summary": "A fully rule-governed variety with its own phonology, a tense/aspect system "
                   "(habitual 'be', completive 'done'), cluster reduction, and distinctive lexicon.",
        "espeak_voice": "en-us", "prosody": {"rate": 155, "pitch": 54,
            "contour": "wide, expressive pitch range; even, resonant rhythm"},
        "phonology": _ph(_PINPEN + _GDROP + _CLUSTER_RED + [(r"ð", "d", "initial /ð/→/d/ (dis, dat)")]),
        "lexicon": [
            {"surface": "finna", "standard": "about", "fu": "FUTURE_INTENT", "register": "casual"},
            {"surface": "fin", "standard": "about", "fu": "FUTURE_INTENT", "register": "casual"},
            {"surface": "bouta", "standard": "about to", "fu": "FUTURE_INTENT", "register": "casual"},
            {"surface": "y'all", "standard": "you all", "fu": "SECOND_PERSON_PLURAL", "register": "casual"},
            {"surface": "ain't", "standard": "is not", "fu": "NEGATION", "register": "casual"},
        ],
        "morphosyntax": [
            {"pattern": "habitual BE (she be working)", "note": "habitual/recurring aspect — a grammatical "
                        "contrast Standard English lacks (HABITUAL_ASPECT)"},
            {"pattern": "completive DONE (he done finished)", "note": "completed action / perfect aspect"},
            {"pattern": "finna / bouta + VERB", "note": "near-future / immediate intention (FUTURE_INTENT)"},
            {"pattern": "copula absence (she tired)", "note": "zero copula where Standard English uses 'is/are'"},
        ],
        "markers": ["finna", "bouta", "y'all", "ain't"],
        "spelling_cues": [r"\bfinna\b", r"\bbout?a\b", r"\bdone\s+\w+ed\b"],
        "sociolect": {"regions": ["United States (nationwide)"], "registers": ["casual", "intimate", "formal"],
                      "contexts": ["everyday conversation", "community speech", "spoken-word / music"]},
        "safety": {"guidelines": "AAE is a legitimate, systematic variety — NOT 'broken English' and never "
                                 "a basis for parody. Represent its grammar faithfully; curate data with and "
                                 "defer to AAE speakers. Do not use it to caricature or to signal race.",
                   "restricted": ["caricature", "mock/comedic impersonation", "use as a racial signal"],
                   "sensitive": ["reclaimed in-group terms that are slurs out of group — never generated"]},
    },
    "en-GB-rp": {
        "id": "en-GB-rp", "name": "British English (General / RP)", "parent": "en",
        "summary": "Standard southern British: non-rhotic (dropped coda /r/), trap–bath split, "
                   "clear final /t/; 'cheers', 'brilliant', 'reckon'.",
        "espeak_voice": "en-gb", "prosody": {"rate": 165, "pitch": 50,
            "contour": "measured; crisp consonants, narrower pitch range"},
        "phonology": _ph(_NONRHOTIC),
        "lexicon": [
            {"surface": "cheers", "standard": "thanks", "fu": "GRATITUDE", "register": "casual"},
            {"surface": "brilliant", "standard": "excellent", "fu": "POSITIVE_EVALUATION", "register": "casual"},
            {"surface": "knackered", "standard": "exhausted", "fu": "TIRED", "register": "casual"},
            {"surface": "fortnight", "standard": "two weeks", "fu": "TWO_WEEKS", "register": "neutral"},
        ],
        "morphosyntax": [
            {"pattern": "'have got' possession", "note": "'I've got' preferred over 'I have'"},
            {"pattern": "collective plural agreement", "note": "'the team are' (plural verb with group nouns)"},
        ],
        "markers": ["cheers", "brilliant", "knackered", "fortnight", "whilst"],
        "spelling_cues": [r"\bcheers\b", r"\bwhilst\b", r"\bfortnight\b", r"\bknackered\b"],
        "sociolect": {"regions": ["England (south)"], "registers": ["formal", "neutral", "casual"],
                      "contexts": ["broadcast", "everyday conversation"]},
        "safety": {"guidelines": "One prestige variety among many British ones; not 'correct English'.",
                   "restricted": [], "sensitive": []},
    },
    "en-GB-scot": {
        "id": "en-GB-scot", "name": "Scottish English", "parent": "en",
        "summary": "Strongly rhotic (tapped/trilled /r/), distinctive vowels; 'wee', 'aye', 'ken', 'bonnie'.",
        "espeak_voice": "en-gb-scotland", "prosody": {"rate": 160, "pitch": 55,
            "contour": "rhythmic, rising terminals common; rolled /r/"},
        "phonology": _ph(_SCOT),
        "lexicon": [
            {"surface": "wee", "standard": "small", "fu": "SMALL", "register": "casual"},
            {"surface": "aye", "standard": "yes", "fu": "AFFIRMATION", "register": "casual"},
            {"surface": "ken", "standard": "know", "fu": "KNOW", "register": "casual"},
            {"surface": "bonnie", "standard": "pretty", "fu": "ATTRACTIVE", "register": "casual"},
            {"surface": "nae", "standard": "not", "fu": "NEGATION", "register": "casual"},
        ],
        "morphosyntax": [
            {"pattern": "negative 'nae' clitic (cannae, dinnae)", "note": "suffixed negation (NEGATION)"},
            {"pattern": "'wee' as diminutive/intensifier", "note": "'a wee bit' = a little"},
        ],
        "markers": ["wee", "aye", "ken", "bonnie", "nae", "cannae", "dinnae"],
        "spelling_cues": [r"\bwee\b", r"\baye\b", r"\bken\b", r"\b(can|din|wid)nae\b"],
        "sociolect": {"regions": ["Scotland"], "registers": ["casual", "neutral", "formal"],
                      "contexts": ["everyday conversation", "community speech"]},
        "safety": {"guidelines": "Render the rhotic + lexicon; avoid a theatrical 'Scotsman' caricature.",
                   "restricted": ["caricature"], "sensitive": []},
    },
    "en-GB-cockney": {
        "id": "en-GB-cockney", "name": "Cockney / Estuary English", "parent": "en",
        "summary": "London working-class / Estuary features: th-fronting (think→fink), h-dropping, "
                   "t-glottalization (butter→bu'er), non-rhotic.",
        "espeak_voice": "en-gb-x-gbcwmd", "prosody": {"rate": 170, "pitch": 53,
            "contour": "quick, clipped; glottal stops for /t/"},
        "phonology": _ph(_THFRONT + _HDROP + _TGLOT + _NONRHOTIC),
        "lexicon": [
            {"surface": "innit", "standard": "isn't it", "fu": "TAG_CONFIRM", "register": "casual"},
            {"surface": "mate", "standard": "friend", "fu": "ADDRESS_FRIEND", "register": "casual"},
            {"surface": "guv", "standard": "sir", "fu": "ADDRESS_RESPECT", "register": "casual"},
            {"surface": "bloke", "standard": "man", "fu": "MALE_PERSON", "register": "casual"},
        ],
        "morphosyntax": [
            {"pattern": "'innit' invariant tag", "note": "all-purpose confirmation tag (TAG_CONFIRM)"},
            {"pattern": "double negative (I didn't do nuffin)", "note": "negative concord (NEGATION)"},
        ],
        "markers": ["innit", "mate", "guv", "bloke", "blimey"],
        "spelling_cues": [r"\binnit\b", r"\bfink\b", r"\bnuffin'?\b", r"\bbruv\b"],
        "sociolect": {"regions": ["London / South-East England"], "registers": ["casual", "intimate"],
                      "contexts": ["everyday conversation", "informal community speech"]},
        "safety": {"guidelines": "A class-marked variety; present features neutrally, not as low-status comedy.",
                   "restricted": ["caricature", "class mockery"], "sensitive": []},
    },
    "es-AR": {
        "id": "es-AR", "name": "Rioplatense Spanish (Buenos Aires)", "parent": "es",
        "summary": "River Plate Spanish: sheísmo (ll/y → /ʃ/), voseo ('vos' + special verb forms), "
                   "aspirated/soft codas; 'che', 'vos', 'laburo'.",
        "espeak_voice": "es-419", "prosody": {"rate": 160, "pitch": 52,
            "contour": "Italian-influenced melody; strong phrase-final pitch movement"},
        "phonology": _ph(_RIOPLATENSE),
        "lexicon": [
            {"surface": "vos", "standard": "tú", "fu": "SECOND_PERSON_SINGULAR", "register": "casual"},
            {"surface": "che", "standard": "oye", "fu": "ADDRESS_ATTENTION", "register": "casual"},
            {"surface": "laburo", "standard": "trabajo", "fu": "WORK", "register": "casual"},
            {"surface": "quilombo", "standard": "lío", "fu": "MESS_CHAOS", "register": "casual"},
        ],
        "morphosyntax": [
            {"pattern": "voseo (vos tenés, vos sos)", "note": "2sg 'vos' with stressed verb endings "
                        "(SECOND_PERSON_SINGULAR)"},
        ],
        "markers": ["vos", "che", "laburo", "quilombo", "tenés", "sos"],
        "spelling_cues": [r"\bvos\b", r"\bche\b", r"\blaburo\b", r"\bten[eé]s\b", r"\bsos\b"],
        "sociolect": {"regions": ["Argentina", "Uruguay (River Plate)"],
                      "registers": ["casual", "neutral", "formal"],
                      "contexts": ["everyday conversation", "media"]},
        "safety": {"guidelines": "Render sheísmo + voseo; avoid tango/gaucho caricature.",
                   "restricted": ["caricature"], "sensitive": []},
    },
}

# Dialects grouped by their parent language, for the UI picker.
def dialects_for(lang=None):
    out = []
    for d in DIALECTS.values():
        if lang and d["parent"] != lang:
            continue
        out.append({"id": d["id"], "name": d["name"], "parent": d["parent"], "summary": d["summary"]})
    return out

def list_dialects():
    return dialects_for(None)

def dialect_info(dialect_id):
    """Full DPC for the UI (rules rendered as human-readable notes; no compiled objects)."""
    d = DIALECTS.get(dialect_id)
    if not d:
        return None
    return {
        "id": d["id"], "name": d["name"], "parent": d["parent"], "summary": d["summary"],
        "espeak_voice": d["espeak_voice"], "prosody": d["prosody"],
        "phonology": [note for (_p, _r, note) in d["phonology"]],
        "lexicon": [{"surface": e["surface"], "standard": e["standard"], "fu": e["fu"],
                     "register": e["register"]} for e in d["lexicon"]],
        "morphosyntax": d["morphosyntax"], "sociolect": d["sociolect"], "safety": d["safety"],
    }


# --------------------------------------------------------------------------
# Phonology: rewrite an IPA string under a dialect's rules. Deterministic and reversible
# in intent; approximate by design. Stress marks and slashes are preserved around the core.
# --------------------------------------------------------------------------
def apply_phonology(ipa, dialect_id):
    """Return (new_ipa, [notes_fired]). `ipa` may be bare or wrapped in /slashes/ with stress
    marks; those wrappers/marks are preserved. No change if the dialect is unknown."""
    d = DIALECTS.get(dialect_id)
    if not d or not ipa:
        return ipa, []
    wrap = ipa.startswith("/") and ipa.endswith("/")
    core = ipa[1:-1] if wrap else ipa
    # Preserve leading stress mark position loosely: strip marks, transform, we don't re-insert
    # stress (it is advisory) — but we keep any that survive the regexes.
    fired = []
    for (pat, repl, note) in d["phonology"]:
        new = pat.sub(repl, core)
        if new != core:
            fired.append(note)
            core = new
    return (("/" + core + "/") if wrap else core), fired


# --------------------------------------------------------------------------
# Lexicon normalization: map dialect surface forms to standard forms + FU atoms. Used before
# translation and to annotate meaning. Case-insensitive, word-boundary, order-stable.
# --------------------------------------------------------------------------
def normalize_lexicon(text, dialect_id):
    """Return (standardized_text, [{surface, standard, fu, register}]) for the dialect forms
    found in `text`. Standardized text feeds the deterministic translator so a dialect word
    carries its shared meaning across languages."""
    d = DIALECTS.get(dialect_id)
    if not d or not text:
        return text, []
    hits = []
    out = text
    # Longest surface first so multiword forms win.
    for e in sorted(d["lexicon"], key=lambda e: -len(e["surface"])):
        pat = _re.compile(r"(?<!\w)" + _re.escape(e["surface"]) + r"(?!\w)", _re.IGNORECASE)
        if pat.search(out):
            hits.append({"surface": e["surface"], "standard": e["standard"],
                         "fu": e["fu"], "register": e["register"]})
            out = pat.sub(e["standard"], out)
    return out, hits


# --------------------------------------------------------------------------
# Dialect detection (deterministic): score each DPC by lexical markers + orthographic cues
# present in the input. Transparent keyword/feature scorer — NOT a neural classifier.
# --------------------------------------------------------------------------
def detect_dialect(text, lang=None, top=4):
    """Return a ranked list of {id, name, score, confidence, markers} for `text`. Confidence
    is the winner's share of total evidence (0..1). Honest: this is a rule-based cue counter."""
    if not text:
        return []
    low = text.lower()
    scored = []
    for d in DIALECTS.values():
        if lang and d["parent"] != lang:
            continue
        found = []
        for m in d["markers"]:
            if _re.search(r"(?<!\w)" + _re.escape(m.lower()) + r"(?!\w)", low):
                found.append(m)
        cues = 0
        for c in d.get("spelling_cues", []):
            if _re.search(c, low, _re.IGNORECASE):
                cues += 1
        score = len(found) * 2 + cues
        if score > 0:
            scored.append({"id": d["id"], "name": d["name"], "score": score,
                           "markers": found})
    scored.sort(key=lambda s: -s["score"])
    total = sum(s["score"] for s in scored) or 1
    for s in scored:
        s["confidence"] = round(s["score"] / total, 3)
    return scored[:top]


# --------------------------------------------------------------------------
# Audio steering. Offline: espeak voice variant + rate/pitch. Cloud: a natural-language
# accent/register fragment appended to Google Gemini style steering.
# --------------------------------------------------------------------------
def espeak_opts(dialect_id):
    """{voice, rate, pitch} for the offline espeak-ng engine, or {} if the dialect is unknown."""
    d = DIALECTS.get(dialect_id)
    if not d:
        return {}
    p = d.get("prosody", {})
    return {"voice": d.get("espeak_voice"), "rate": p.get("rate"), "pitch": p.get("pitch")}

def cloud_style(dialect_id):
    """A natural-language style fragment (accent + cadence) for the Gemini style instruction."""
    d = DIALECTS.get(dialect_id)
    if not d:
        return ""
    contour = (d.get("prosody", {}) or {}).get("contour", "")
    frag = "in a %s accent" % d["name"]
    if contour:
        frag += " (%s)" % contour
    return frag


# --------------------------------------------------------------------------
# Deterministic QC battery for the dialect subsystem.
# --------------------------------------------------------------------------
_QC = [
    # (dialect, word, input_ipa, expected_substring_in_output)
    ("en-GB-rp", "car", "/kɑːr/", "kɑː"),          # non-rhotic drops coda r
    ("en-GB-cockney", "think", "/θɪŋk/", "fɪ"),    # th-fronting θ->f
    ("en-US-south", "pen", "/pɛn/", "pɪn"),         # pin-pen merger
    ("en-GB-scot", "right", "/ɹaɪt/", "r"),         # rhotic realized as r
    ("es-AR", "calle", "/kaʝe/", "kaʃe"),           # sheísmo ʝ->ʃ
]

def qc():
    """Verify each signature phonology rule fires and that lexicon→FU + detection work.
    Deterministic, local, no audio, no cost. Returns a pass/fail report."""
    rows, passed = [], 0
    for (did, word, ipa, expect) in _QC:
        out, fired = apply_phonology(ipa, did)
        ok = expect in out
        passed += 1 if ok else 0
        rows.append({"dialect": did, "word": word, "in": ipa, "out": out,
                     "expect": expect, "rules": fired, "pass": ok})
    # lexicon + FU
    std, hits = normalize_lexicon("y'all finna leave", "en-US-aae")
    lex_ok = any(h["fu"] == "FUTURE_INTENT" for h in hits)
    rows.append({"check": "lexicon→FU (finna→FUTURE_INTENT)", "standard": std, "pass": lex_ok})
    passed += 1 if lex_ok else 0
    # detection
    det = detect_dialect("Aye, it's a wee bit cold, ken?")
    det_ok = bool(det) and det[0]["id"] == "en-GB-scot"
    rows.append({"check": "detect Scottish from markers", "top": (det[0]["id"] if det else None),
                 "pass": det_ok})
    passed += 1 if det_ok else 0
    total = len(_QC) + 2
    return {"passed": passed, "total": total, "rate": round(100.0 * passed / total, 1),
            "ok": passed == total, "rows": rows}


if __name__ == "__main__":
    import json
    print(json.dumps(qc(), indent=2, ensure_ascii=False))
