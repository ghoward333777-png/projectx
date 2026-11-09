"""Pronunciation resolution — decide how each word is said BEFORE any speech engine sees the text.

Heteronyms are words spelled alike and said differently ("I live in Seattle" /lɪv/, "a live concert" /laɪv/). Every
speech engine guesses them its own way; this module decides instead, by fixed rules (no AI model, same answer every
time), and then tells each engine in the form it obeys:

    SSML <phoneme alphabet="ipa">     Google Cloud, Microsoft Azure, Amazon Polly, Windows (SAPI)
    espeak-ng [[phoneme mnemonics]]   espeak-ng (the default offline voice)
    macOS [[inpt PHON]] … [[inpt TEXT]]  macOS say
    CMU ARPABET <phoneme> tags        ElevenLabs models that honour them (Flash v2, Turbo v2, English v1)
    respelling ("liv", "lyve", "red") Google Gemini TTS, OpenAI, other ElevenLabs models — text-only engines
    IPA per word                      QueryBook's own formant voice and the talking face's mouth shapes

How a word is decided, highest priority first:
    1. inline, in the text itself:   "I {live|verb} in Seattle", "{live|/laɪv/}", "{SQL|sequel}"
    2. the pronunciation lexicon:    the admin's own terms (company names, people, acronyms), saved in the data folder
    3. the word's own rules:         collocations ("bass guitar", "lead pipe", "wind turbine", "tears of joy")
    4. grammar cues:                 the words around it ("to live" verb, "a live" adjective, "had read" past)
    5. the word's usual reading      (low confidence: NOT forced — the engine is left to decide, and it is flagged)

A decision is forced on the engine only at confidence ≥ FORCE (or from 1–2). Each decision carries its reason.
"""
import json, os, re, threading

FORCE = 0.7

# ------------------------------------------------------------------------------------------------ phoneme sets
VOWELS = {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW"}
IPA_V = {"AA": "ɑ", "AE": "æ", "AH": "ʌ", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ", "EH": "ɛ", "ER": "ɝ", "EY": "eɪ", "IH": "ɪ", "IY": "i",
         "OW": "oʊ", "OY": "ɔɪ", "UH": "ʊ", "UW": "u"}
IPA_C = {"B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "F": "f", "G": "ɡ", "HH": "h", "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n",
         "NG": "ŋ", "P": "p", "R": "ɹ", "S": "s", "SH": "ʃ", "T": "t", "TH": "θ", "V": "v", "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ"}
ESPEAK_V = {"AA": "A:", "AE": "a", "AH": "V", "AO": "O:", "AW": "aU", "AY": "aI", "EH": "E", "ER": "3:", "EY": "eI", "IH": "I", "IY": "i:",
            "OW": "oU", "OY": "OI", "UH": "U", "UW": "u:"}
ESPEAK_C = {"B": "b", "CH": "tS", "D": "d", "DH": "D", "F": "f", "G": "g", "HH": "h", "JH": "dZ", "K": "k", "L": "l", "M": "m", "N": "n",
            "NG": "N", "P": "p", "R": "r", "S": "s", "SH": "S", "T": "t", "TH": "T", "V": "v", "W": "w", "Y": "j", "Z": "z", "ZH": "Z"}
APPLE_C = {"B": "b", "CH": "C", "D": "d", "DH": "D", "F": "f", "G": "g", "HH": "h", "JH": "J", "K": "k", "L": "l", "M": "m", "N": "n",
           "NG": "N", "P": "p", "R": "r", "S": "s", "SH": "S", "T": "t", "TH": "T", "V": "v", "W": "w", "Y": "y", "Z": "z", "ZH": "Z"}
RESPELL_V = {"AA": "ah", "AE": "a", "AH": "uh", "AO": "aw", "AW": "ow", "AY": "eye", "EH": "eh", "ER": "er", "EY": "ay", "IH": "ih",
             "IY": "ee", "OW": "oh", "OY": "oy", "UH": "u", "UW": "oo"}
RESPELL_C = {"CH": "ch", "DH": "th", "HH": "h", "JH": "j", "NG": "ng", "SH": "sh", "TH": "th", "ZH": "zh", "Y": "y"}
# English onsets a syllable may start with (for placing the stress mark before the right consonants)
ONSETS = {"P R", "T R", "K R", "B R", "D R", "G R", "F R", "TH R", "SH R", "P L", "K L", "B L", "G L", "F L", "S L", "S T", "S P", "S K",
          "S M", "S N", "S W", "T W", "K W", "D W", "S T R", "S P R", "S K R", "S P L", "S K W", "P Y", "B Y", "K Y", "F Y", "M Y", "V Y",
          "HH Y", "G Y"}


def _split(arpa):
    out = []
    for t in arpa.split():
        base, stress = (t[:-1], t[-1]) if t[-1].isdigit() else (t, None)
        out.append((base, stress))
    return out


def _syllables(ph):
    """[(onset_start_index, vowel_index, stress)] with maximal legal onsets"""
    vs = [i for i, (b, _) in enumerate(ph) if b in VOWELS]
    res, prev_v = [], -1
    for v in vs:
        cons = list(range(prev_v + 1, v))
        start = v
        for k in range(len(cons)):                       # the longest legal onset ending at the vowel
            seq = " ".join(ph[j][0] for j in cons[k:])
            if len(cons) - k == 1 or seq in ONSETS:
                start = cons[k]
                break
        if prev_v < 0:
            start = 0
        res.append((start, v, ph[v][1]))
        prev_v = v
    return res


def arpa_to_ipa(arpa):
    ph = _split(arpa)
    marks = {}
    for start, v, st in _syllables(ph):
        if st in ("1", "2") and sum(1 for b, _ in ph if b in VOWELS) > 1 or st == "1":
            marks[start] = "ˈ" if st == "1" else "ˌ"
    out = []
    for i, (b, st) in enumerate(ph):
        out.append(marks.get(i, ""))
        if b == "AH" and st == "0":
            out.append("ə")
        elif b == "ER" and st == "0":
            out.append("ɚ")
        elif b in IPA_V:
            out.append(IPA_V[b])
        else:
            out.append(IPA_C.get(b, ""))
    return "".join(out)


def arpa_to_espeak(arpa):
    out = []
    for b, st in _split(arpa):
        if b in VOWELS:
            out.append({"1": "'", "2": ","}.get(st, ""))
            out.append("@" if b == "AH" and st == "0" else "3" if b == "ER" and st == "0" else ESPEAK_V[b])
        else:
            out.append(ESPEAK_C.get(b, ""))
    return "".join(out)


def arpa_to_apple(arpa):
    out = []
    for b, st in _split(arpa):
        if b in VOWELS:
            out.append({"1": "1", "2": "2"}.get(st, ""))
            out.append("AX" if b == "AH" and st == "0" else b)
        else:
            out.append(APPLE_C.get(b, b.lower()))
    return "".join(out)


def arpa_to_respell(arpa):
    """a rough English respelling for text-only engines ("L AY1 V" → "lyve")"""
    out, ph = [], _split(arpa)
    for i, (b, st) in enumerate(ph):
        if b in VOWELS:
            if b == "AY" and i > 0:
                out.append("y")
                if len(ph) - i == 2 and ph[-1][0] not in VOWELS:     # a final "y + consonant" reads as "yCe": lyve, ryde
                    out.append(RESPELL_C.get(ph[-1][0], ph[-1][0].lower()) + "e")
                    break
            else:
                out.append("uh" if b == "AH" and st == "0" else RESPELL_V[b])
        else:
            out.append(RESPELL_C.get(b, b.lower()))
    return "".join(out)


_IPA_TO_ARPA = sorted([(v, k) for k, v in IPA_V.items()] + [(v, k) for k, v in IPA_C.items()] +
                      [("ə", "AH"), ("ɚ", "ER"), ("ɜ", "ER"), ("r", "R"), ("g", "G"), ("i", "IY"), ("ɒ", "AA"), ("o", "OW"), ("e", "EY"),
                       ("a", "AE"), ("ɐ", "AH"), ("ɾ", "T"), ("ʔ", "T"), ("x", "K")], key=lambda kv: -len(kv[0]))


def ipa_to_arpa(ipa):
    """IPA → ARPABET (with stress digits), for entries given in IPA. None when a symbol is not understood."""
    s = ipa.strip().strip("/[]").replace("ː", "").replace(".", "").replace("ˑ", "")
    out, stress, i = [], None, 0
    while i < len(s):
        ch = s[i]
        if ch in "ˈˌ":
            stress = "1" if ch == "ˈ" else "2"
            i += 1
            continue
        if ch.isspace():
            i += 1
            continue
        for sym, arp in _IPA_TO_ARPA:
            if s.startswith(sym, i):
                if arp in VOWELS:
                    d = stress or ("0" if sym in ("ə", "ɚ") else "0")
                    out.append(arp + d)
                    stress = None
                else:
                    out.append(arp)
                i += len(sym)
                break
        else:
            return None
    if out and not any(t[-1] in "12" for t in out if t[-1].isdigit()):
        for k, t in enumerate(out):                      # one-syllable or unmarked: stress the first full vowel
            if t[-1] == "0" and not t.startswith(("AH0",)):
                out[k] = t[:-1] + "1"
                break
    return " ".join(out) if out else None


# ------------------------------------------------------------------------------------------------ word classes for the grammar cues
DET = {"the", "a", "an", "this", "that", "these", "those", "my", "your", "his", "its", "our", "their", "some", "any", "no", "every",
       "each", "another", "which", "what", "whose", "one", "many", "several", "few", "more", "most", "such", "first", "last", "next",
       "new", "old", "same", "other", "own", "two", "three", "four", "five", "ten", "great", "big", "small", "good", "bad"}
PREP = {"of", "in", "on", "at", "for", "with", "from", "by", "about", "into", "onto", "under", "over", "without", "between", "after",
        "before", "during", "against", "through", "within", "upon", "per", "like", "via"}
MODAL = {"will", "would", "can", "could", "should", "must", "might", "may", "shall", "do", "does", "did", "don't", "doesn't", "didn't",
         "won't", "wouldn't", "can't", "cannot", "couldn't", "shouldn't", "let's", "please", "i'll", "we'll", "you'll", "they'll",
         "i'd", "we'd", "you'd", "they'd", "he'll", "she'll", "to", "not", "never"}
SUBJ = {"i", "you", "we", "they"}
SUBJ3 = {"he", "she", "it", "who", "that", "which", "everyone", "someone", "nobody", "everybody", "somebody"}
OBJ = {"it", "them", "him", "me", "us", "this", "these", "those", "everything", "something", "nothing", "anything"}
ADV = {"also", "often", "never", "always", "usually", "sometimes", "rarely", "just", "still", "really", "actually", "generally",
       "typically", "then", "now", "already", "only", "even", "probably", "certainly", "carefully", "quickly"}
BE = {"is", "are", "was", "were", "be", "been", "being", "am", "seem", "seems", "seemed", "feel", "feels", "felt", "look", "looks",
      "become", "becomes", "became", "remain", "remains", "stay", "stays", "get", "gets", "got"}
INTENS = {"very", "so", "too", "quite", "extremely", "fairly", "rather", "pretty", "perfectly", "completely", "totally", "less", "as"}
HAVE = {"have", "has", "had", "having", "i've", "we've", "you've", "they've", "he's", "she's", "it's"}
PAST_TIME = {"yesterday", "ago", "last", "earlier", "previously", "formerly"}
NOW_TIME = {"every", "each", "always", "usually", "often", "daily", "now", "today", "tomorrow", "sometimes", "regularly", "tonight"}
PRESENT_MARK = {"every", "always", "usually", "often", "daily", "regularly", "sometimes", "now"}

# ------------------------------------------------------------------------------------------------ the heteronyms
# word → {senses: {sense: (arpa, respelling or None, gloss)}, pos: {verb/noun/adj: sense}, default, rules}
# rules: (kind, words, sense, confidence)  kind: next = the next word; prev = the word before; near = within 4 words either side;
#        next2 = one of the next two words; end = the word ends its clause and the word before is in `words`
# ARPABET is General American, written for this table (Wikidata lexemes, CC0, can extend it).
NOUN_STRESS = "noun"


def _nv(noun, verb, nr=None, vr=None, default="verb", extra=()):
    return {"senses": {"noun": (noun, nr, "noun / adjective: stress on the first syllable"), "verb": (verb, vr, "verb: stress on the second syllable")},
            "pos": {"noun": "noun", "adj": "noun", "verb": "verb"}, "default": default, "rules": list(extra)}


def _av(adj, verb, ar=None, vr=None, default="adj", extra=(), ag="adjective", vg="verb"):
    return {"senses": {"adj": (adj, ar, ag), "verb": (verb, vr, vg)}, "pos": {"noun": "adj", "adj": "adj", "verb": "verb"},
            "default": default, "rules": list(extra)}


LIVE_NOUNS = {"music", "show", "shows", "event", "events", "concert", "concerts", "performance", "performances", "broadcast", "broadcasts",
              "stream", "streams", "streaming", "audience", "audiences", "recording", "recordings", "album", "albums", "wire", "wires",
              "ammunition", "rounds", "bait", "animals", "animal", "coverage", "feed", "version", "band", "bands", "television", "tv",
              "radio", "game", "match", "demo", "session", "sessions", "chat", "update", "updates", "action", "theatre", "theater",
              "entertainment", "footage", "video", "webcast", "q&a", "blog", "tour", "set", "sound", "data", "traffic", "results",
              "score", "scores", "commentary", "studio", "orchestra", "plants", "plant", "cells", "vaccine", "oak", "coals", "steam",
              "electricity", "current", "circuit", "mic", "microphone", "camera", "cameras", "site", "environment", "system", "server",
              "demonstration", "auction", "poll", "vote", "telecast", "transmission", "show's", "issue"}
LIVE_AFTER_VERB = {"go", "goes", "went", "going", "gone", "broadcast", "broadcasts", "streamed", "stream", "streaming", "performed",
                   "perform", "performs", "played", "play", "plays", "aired", "air", "shown", "shot", "recorded", "sung", "sang", "sing",
                   "appeared", "appear", "appears", "watch", "watched", "televised", "is", "was", "are", "were", "be", "being", "been",
                   "it's", "we're", "they're", "you're", "i'm", "now", "still", "remains"}
LIVE_VERB_NEXT = {"in", "at", "with", "near", "together", "alone", "here", "there", "long", "abroad", "off", "life", "forever",
                  "happily", "independently", "comfortably", "without", "for", "by", "under", "among", "beside", "next", "close",
                  "longer", "well", "like", "a", "an", "to", "through", "apart", "where", "and", "inside", "outside", "nearby",
                  "simply", "lives", "the", "out", "up", "within", "rent", "frugally"}
METAL = {"pipe", "pipes", "paint", "poisoning", "poison", "pencil", "pencils", "weight", "weights", "shot", "bullet", "bullets",
         "acid", "levels", "level", "crystal", "ore", "mine", "mines", "balloon", "apron", "oxide", "glass", "free", "based",
         "lined", "ingot", "metal", "element", "toxic", "pb", "exposure", "contamination", "solder", "battery", "batteries",
         "plumbing", "sheet", "roof", "flashing", "smelter", "smelting", "isotope", "atomic", "heavy", "gasoline", "petrol", "dust",
         "contaminated", "particles", "fishing", "sinker", "sinkers", "content"}

H = {
    "live": {"senses": {"verb": ("L IH1 V", "liv", "to be alive; to reside"),
                        "adj": ("L AY1 V", "lyve", "alive; happening now; carrying current")},
             "pos": {"verb": "verb", "noun": "adj", "adj": "adj"}, "default": "verb",
             "rules": [("next", LIVE_NOUNS, "adj", 0.93), ("end", LIVE_AFTER_VERB, "adj", 0.88),
                       ("prev", {"go", "goes", "went", "going", "gone", "broadcast", "broadcasts", "streamed", "performed", "aired", "televised", "shown"}, "adj", 0.9), ("next", LIVE_VERB_NEXT, "verb", 0.8),
                       ("prev", {"on", "in"}, "adj", 0.75)]},
    "lives": {"senses": {"noun": ("L AY1 V Z", "lyves", "plural of life"), "verb": ("L IH1 V Z", "livs", "he/she lives: resides")},
              "pos": {"verb": "verb", "noun": "noun", "adj": "noun"}, "default": "noun",
              "rules": [("prev", SUBJ3 | {"one", "family", "man", "woman", "who", "nobody", "person", "cat", "dog", "still", "now", "currently"}, "verb", 0.88),
                        ("next", {"in", "at", "with", "near", "alone", "here", "there", "on", "abroad", "next", "together", "nearby", "by", "across"}, "verb", 0.84),
                        ("prev", {"their", "our", "your", "my", "his", "her", "its", "many", "saved", "save", "saving", "lost", "lose",
                                  "losing", "nine", "whose", "two", "three", "thousands", "millions", "everyday", "daily", "private",
                                  "personal", "changed", "change", "transform", "transformed", "risk", "risked", "claimed", "took"}, "noun", 0.92),
                        ("next", {"were", "are", "have", "had", "of", "lost", "saved", "matter", "depend"}, "noun", 0.85)]},
    "read": {"senses": {"present": ("R IY1 D", "reed", "present tense / infinitive"), "past": ("R EH1 D", "red", "past tense / past participle")},
             "pos": {}, "default": "present", "rules": []},                         # tense rules in _tense()
    "lead": {"senses": {"verb": ("L IY1 D", "leed", "to guide; a leading position"), "metal": ("L EH1 D", "led", "the metal Pb")},
             "pos": {"verb": "verb"}, "default": "verb",
             "rules": [("near", METAL, "metal", 0.86), ("next", {"to", "the", "a", "us", "them", "him", "her", "you", "me", "singer",
                                                                  "role", "actor", "actress", "investigator", "author", "guitarist",
                                                                  "vocalist", "story", "character", "by", "over", "in", "into", "on"}, "verb", 0.84),
                       ("prev", {"the", "a", "took", "take", "takes", "taking", "in", "lost", "extended", "narrow", "comfortable", "early", "slim"}, "verb", 0.8)]},
    "wind": {"senses": {"air": ("W IH1 N D", "winnd", "moving air"), "turn": ("W AY1 N D", "wynd", "to turn or coil")},
             "pos": {"verb": "turn", "noun": "air", "adj": "air"}, "default": "air",
             "rules": [("near", {"blow", "blows", "blowing", "blew", "gust", "gusts", "gusty", "turbine", "turbines", "power", "farm", "farms",
                                 "energy", "speed", "speeds", "chill", "mph", "storm", "breeze", "direction", "strong", "cold", "north",
                                 "south", "east", "west", "northerly", "southerly", "solar", "tunnel", "instrument", "instruments",
                                 "howling", "trade", "headwind", "sail", "sails", "rain", "weather", "knots"}, "air", 0.86),
                       ("next", {"up", "down", "back", "around", "round", "through", "along", "the", "your", "it", "them", "its"}, "turn", 0.84),
                       ("near", {"clock", "watch", "spring", "yarn", "thread", "rope", "cable", "reel", "spool", "coil", "crank"}, "turn", 0.85)]},
    "winds": {"senses": {"air": ("W IH1 N D Z", "winnds", "moving air"), "turn": ("W AY1 N D Z", "wynds", "turns or coils")},
              "pos": {"verb": "turn", "noun": "air"}, "default": "air",
              "rules": [("prev", {"road", "path", "river", "trail", "stream", "track", "route", "it", "he", "she", "that", "which", "who"}, "turn", 0.88),
                        ("next", {"its", "up", "down", "through", "along", "around", "round", "back", "the"}, "turn", 0.84),
                        ("prev", {"strong", "high", "cold", "trade", "prevailing", "gale", "gale-force", "hurricane", "fierce", "light", "the"}, "air", 0.9),
                        ("next", {"blew", "blow", "blowing", "of", "and", "were", "are", "gusting", "will", "from"}, "air", 0.82)]},
    "wound": {"senses": {"injury": ("W UW1 N D", "woond", "an injury"), "turned": ("W AW1 N D", "wownd", "past of wind: turned, coiled")},
              "pos": {"noun": "injury", "verb": "turned", "adj": "injury"}, "default": "injury",
              "rules": [("next", {"up", "around", "round", "down", "tightly", "through", "its", "the", "back", "itself", "tight"}, "turned", 0.88),
                        ("prev", {"a", "the", "his", "her", "my", "gunshot", "stab", "head", "open", "deep", "fatal", "flesh", "exit",
                                  "entry", "old", "mortal", "chest", "puncture", "surgical", "bullet", "knife", "wounds", "this", "that"}, "injury", 0.92),
                        ("near", {"heal", "healed", "healing", "bleeding", "bandage", "infection", "infected", "stitch", "stitches",
                                  "dress", "dressing", "clean", "suffered"}, "injury", 0.82)]},
    "tear": {"senses": {"cry": ("T IH1 R", "teer", "a drop from the eye"), "rip": ("T EH1 R", "tair", "to rip; a rip")},
             "pos": {"verb": "rip"}, "default": "cry",
             "rules": [("near", {"cry", "cried", "crying", "eye", "eyes", "cheek", "cheeks", "shed", "shedding", "joy", "sad", "sadness",
                                 "gas", "drop", "duct", "ducts", "rolled", "trickled", "single", "wipe", "wiped", "jerker", "sorrow"}, "cry", 0.88),
                       ("next", {"up", "down", "apart", "off", "open", "out", "into", "through", "it", "the", "them", "away", "at", "in"}, "rip", 0.82),
                       ("prev", {"and"}, "rip", 0.6),
                       ("near", {"fabric", "shirt", "paper", "ligament", "muscle", "rip", "torn", "jeans", "cloth", "sheet", "acl",
                                 "meniscus", "wear", "seam", "rotator", "cuff", "trousers", "pants", "sleeve", "tent", "sail"}, "rip", 0.86)]},
    "tears": {"senses": {"cry": ("T IH1 R Z", "teers", "drops from the eye"), "rip": ("T EH1 R Z", "tairs", "rips")},
              "pos": {"verb": "rip", "noun": "cry"}, "default": "cry",
              "rules": [("prev", {"in", "into", "of", "with", "her", "his", "my", "your", "their", "our", "crocodile", "happy", "fought",
                                  "back", "hold", "held", "shed", "through", "no", "the", "without", "wiped"}, "cry", 0.9),
                        ("next", {"of", "streamed", "rolled", "ran", "fell", "welled", "flowed", "in", "came", "were", "flowing"}, "cry", 0.88),
                        ("prev", SUBJ3, "rip", 0.82), ("next", {"up", "apart", "down", "off", "open", "through", "into", "at"}, "rip", 0.84)]},
    "bow": {"senses": {"bend": ("B AW1", "bough", "to bend forward; the front of a ship"),
                       "knot": ("B OW1", "boh", "a knot of ribbon; a weapon for arrows; a violin bow")},
            "pos": {"verb": "bend"}, "default": "knot",
            "rules": [("near", {"arrow", "arrows", "ribbon", "tie", "tied", "violin", "cello", "viola", "string", "strings", "rainbow",
                                "archery", "archer", "shoot", "hair", "crossbow", "longbow", "pink", "red", "gift", "present"}, "knot", 0.88),
                      ("near", {"ship", "stern", "deck", "boat", "vessel", "hull", "audience", "applause", "curtain", "head", "heads",
                                "respect", "king", "queen", "queen's", "majesty", "bowed", "kneel", "knee", "deeply", "humbly"}, "bend", 0.84),
                      ("prev", {"take", "took", "taking", "takes", "final", "deep"}, "bend", 0.86),
                      ("prev2", {"take", "took", "taking", "takes"}, "bend", 0.88)]},
    "bows": {"senses": {"bend": ("B AW1 Z", "boughs", "bends forward"), "knot": ("B OW1 Z", "bohs", "ribbons; archery bows")},
             "pos": {"verb": "bend"}, "default": "knot",
             "rules": [("prev", SUBJ3, "bend", 0.85), ("near", {"arrows", "ribbons", "ribbon", "hair", "violin", "violins", "archers", "gift", "tied"}, "knot", 0.86)]},
    "row": {"senses": {"line": ("R OW1", "roh", "a line; to propel a boat"), "quarrel": ("R AW1", "rau", "a quarrel (British)")},
            "pos": {"verb": "line"}, "default": "line",
            "rules": [("near", {"argue", "argued", "argument", "quarrel", "blazing", "furious", "public", "political", "diplomatic",
                                "bitter", "dispute", "erupted", "sparked", "embroiled", "spat"}, "quarrel", 0.82),
                      ("near", {"boat", "oar", "oars", "seat", "seats", "house", "houses", "column", "table", "front", "back", "first",
                                "second", "third", "last", "in", "spreadsheet", "cells", "trees", "crops"}, "line", 0.85)]},
    "rows": {"senses": {"line": ("R OW1 Z", "rohs", "lines"), "quarrel": ("R AW1 Z", "raus", "quarrels")}, "pos": {}, "default": "line",
             "rules": [("near", {"argument", "arguments", "furious", "political", "bitter", "disputes"}, "quarrel", 0.75)]},
    "bass": {"senses": {"music": ("B EY1 S", "base", "low musical range"), "fish": ("B AE1 S", "bas", "the fish")},
             "pos": {}, "default": "music",
             "rules": [("near", {"fish", "fishing", "fished", "caught", "catch", "catching", "lake", "largemouth", "smallmouth", "striped",
                                 "sea", "lure", "lures", "bait", "rod", "pond", "angler", "anglers", "trout", "pike", "fillet", "grilled",
                                 "species", "boat", "pound", "pounder", "spawning", "chilean", "black"}, "fish", 0.88),
                       ("near", {"guitar", "guitarist", "player", "line", "drum", "drums", "note", "notes", "clef", "voice", "singer",
                                 "amp", "speaker", "speakers", "music", "band", "boost", "treble", "baritone", "tenor", "double", "upright",
                                 "electric", "frequencies", "frequency", "subwoofer", "heavy", "deep", "solo", "riff", "kick", "drop"}, "music", 0.88)]},
    "dove": {"senses": {"bird": ("D AH1 V", "duv", "the bird"), "dived": ("D OW1 V", "dohv", "past of dive")},
             "pos": {"noun": "bird", "verb": "dived", "adj": "bird"}, "default": "bird",
             "rules": [("prev", SUBJ | SUBJ3 | {"then", "and", "quickly", "suddenly", "immediately", "both"}, "dived", 0.86),
                       ("next", {"into", "in", "under", "off", "from", "down", "after", "deep", "headfirst", "back", "for", "below", "beneath", "to", "straight", "through", "toward", "towards"}, "dived", 0.88),
                       ("prev", {"a", "the", "white", "mourning", "rock", "turtle", "peace", "grey", "gray", "of"}, "bird", 0.9)]},
    "does": {"senses": {"verb": ("D AH1 Z", "duz", "the verb do"), "deer": ("D OW1 Z", "doze", "female deer")},
             "pos": {}, "default": "verb",
             "rules": [("near", {"deer", "bucks", "buck", "fawns", "fawn", "hunting", "herd", "antlers", "rabbits", "hares", "venison", "rut"}, "deer", 0.86)]},
    "sow": {"senses": {"plant": ("S OW1", "so", "to plant seed"), "pig": ("S AW1", "sau", "a female pig")},
            "pos": {"verb": "plant"}, "default": "plant",
            "rules": [("near", {"pig", "pigs", "piglet", "piglets", "litter", "farrow", "boar", "hog", "hogs", "pen", "sty", "teats", "suckling"}, "pig", 0.88),
                      ("near", {"seed", "seeds", "field", "fields", "crop", "crops", "reap", "plant", "garden", "spring", "doubt", "discord", "seeds"}, "plant", 0.86)]},
    "sewer": {"senses": {"drain": ("S UW1 ER0", "sooer", "a drain"), "sewist": ("S OW1 ER0", "soh-er", "someone who sews")},
              "pos": {}, "default": "drain",
              "rules": [("near", {"seamstress", "needle", "needles", "sewing", "thread", "stitch", "stitches", "quilt", "quilter", "tailor", "fabric", "skilled"}, "sewist", 0.78)]},
    "minute": {"senses": {"time": ("M IH1 N AH0 T", "minnit", "sixty seconds"), "tiny": ("M AY0 N UW1 T", "my-noot", "very small")},
               "pos": {"noun": "time"}, "default": "time",
               "rules": [("next", {"detail", "details", "amount", "amounts", "quantities", "quantity", "traces", "trace", "particles",
                                   "fraction", "changes", "differences", "difference", "variations", "fragments", "particle", "organisms",
                                   "crystals", "examination", "inspection", "scale", "level", "attention", "parts"}, "tiny", 0.9),
                        ("prev", {"very", "so", "too", "extremely", "most", "a few", "in"}, "tiny", 0.7),
                        ("prev", {"a", "one", "every", "last", "next", "each", "per", "few", "the", "this", "that", "any", "half", "ten",
                                  "five", "two", "three", "fifteen", "twenty", "thirty", "single", "spare", "wait", "just"}, "time", 0.9)]},
    "number": {"senses": {"count": ("N AH1 M B ER0", None, "a numeral"), "numb": ("N AH1 M ER0", "nummer", "more numb")},
               "pos": {}, "default": "count",
               "rules": [("prev", {"even", "getting", "grew", "went"}, "numb", 0.72), ("near", {"cold", "colder", "anesthetic", "anaesthetic", "frozen", "feeling", "tingling"}, "numb", 0.6)]},
    "desert": {"senses": {"noun": ("D EH1 Z ER0 T", "dezzert", "a dry region"), "verb": ("D IH0 Z ER1 T", "dih-zurt", "to abandon")},
               "pos": {"noun": "noun", "adj": "noun", "verb": "verb"}, "default": "noun",
               "rules": [("near", {"sahara", "sand", "sands", "dry", "gobi", "island", "camel", "camels", "mojave", "arid", "dune", "dunes",
                                   "oasis", "cactus", "heat", "atacama", "kalahari", "sonoran", "rats", "storm"}, "noun", 0.88),
                         ("next", {"them", "him", "her", "us", "me", "you", "the", "their", "his", "our"}, "verb", 0.8),
                         ("prev", {"just"}, "verb", 0.7)]},
    "deserts": {"senses": {"noun": ("D EH1 Z ER0 T S", "dezzerts", "dry regions"), "verb": ("D IH0 Z ER1 T S", "dih-zurts", "abandons; what one deserves")},
                "pos": {"noun": "noun", "verb": "verb"}, "default": "noun", "rules": [("prev", {"just"}, "verb", 0.9)]},
    "present": _nv("P R EH1 Z AH0 N T", "P R IY0 Z EH1 N T", "prezzent", "prih-zent", default="noun",
                   extra=[("prev", {"at", "the", "for", "a", "birthday", "christmas", "past", "and", "until", "up"}, "noun", 0.9),
                          ("next", {"day", "tense", "moment", "time", "value", "company", "situation", "state", "position", "participle", "perfect"}, "noun", 0.9),
                          ("next", {"them", "it", "him", "her", "evidence", "findings", "results", "the", "their", "our", "his", "a", "an", "itself", "themselves", "yourself", "myself"}, "verb", 0.82)]),
    "presents": _nv("P R EH1 Z AH0 N T S", "P R IY0 Z EH1 N T S", "prezzents", "prih-zents", default="noun",
                    extra=[("prev", SUBJ3, "verb", 0.88), ("next", {"a", "an", "the", "his", "her", "its", "their", "evidence", "itself"}, "verb", 0.84)]),
    "record": _nv("R EH1 K ER0 D", "R IH0 K AO1 R D", "reckerd", "rih-cord", default="noun",
                  extra=[("next", {"label", "labels", "player", "players", "store", "stores", "high", "low", "number", "numbers", "time",
                                   "breaking", "holder", "holders", "company", "collection", "deal", "producer", "sales", "keeping", "book", "books", "levels", "temperatures", "heat", "year", "profits", "turnout", "crowd", "attendance", "highs", "lows", "speed"}, "noun", 0.92),
                         ("prev", {"world", "track", "criminal", "police", "medical", "public", "permanent", "historical", "off", "on", "new",
                                   "school", "voting", "court", "dental", "service", "personnel", "employment", "financial", "set", "broke", "break", "breaks", "beat", "hold", "holds", "held"}, "noun", 0.9)]),
    "records": _nv("R EH1 K ER0 D Z", "R IH0 K AO1 R D Z", "reckerdz", "rih-cords", default="noun",
                   extra=[("prev", SUBJ3 | {"camera", "machine", "device", "app", "system", "sensor", "it", "tape", "recorder", "meter"}, "verb", 0.88),
                          ("prev", {"medical", "public", "criminal", "court", "police", "dental", "financial", "historical", "his", "her",
                                    "their", "our", "your", "my", "keep", "kept", "keeping", "official", "school", "tax", "vinyl", "old",
                                    "broke", "broken", "set", "sets", "world", "several", "many", "two", "three", "of"}, "noun", 0.9)]),
    "object": _nv("AA1 B JH EH0 K T", "AH0 B JH EH1 K T", "obb-jekt", "ub-jekt", default="noun",
                  extra=[("next", {"to"}, "verb", 0.9), ("next", {"of", "is", "was", "in", "that", "lesson", "oriented", "code", "files", "file", "type", "types", "class", "detection", "permanence"}, "noun", 0.9)]),
    "objects": _nv("AA1 B JH EH0 K T S", "AH0 B JH EH1 K T S", "obb-jekts", "ub-jekts", default="noun",
                   extra=[("next", {"to"}, "verb", 0.9), ("prev", SUBJ3, "verb", 0.6)]),
    "project": _nv("P R AA1 JH EH0 K T", "P R AH0 JH EH1 K T", "prodj-ekt", "pruh-jekt", default="noun",
                   extra=[("next", {"manager", "management", "plan", "team", "budget", "goals", "deadline", "files", "lead", "proposal", "scope", "work", "managers", "funding", "is", "was", "will", "has", "had", "of"}, "noun", 0.92),
                          ("next", {"confidence", "power", "strength", "an", "onto", "on", "into", "images", "image", "growth", "sales", "earnings", "revenue", "the", "a", "that", "it", "their", "your"}, "verb", 0.78)]),
    "projects": _nv("P R AA1 JH EH0 K T S", "P R AH0 JH EH1 K T S", "prodj-ekts", "pruh-jekts", default="noun",
                    extra=[("next", {"confidence", "power", "an", "onto", "growth", "that", "images", "sales", "earnings", "revenue"}, "verb", 0.84)]),
    "produce": _nv("P R OW1 D UW0 S", "P R AH0 D UW1 S", "proh-doos", "pruh-doos", default="verb",
                   extra=[("near", {"fresh", "organic", "local", "section", "aisle", "farm", "vegetables", "fruit", "fruits", "market", "grocer", "grocery", "seasonal", "stand"}, "noun", 0.85)]),
    "permit": _nv("P ER1 M IH0 T", "P ER0 M IH1 T", "per-mitt", None, default="verb",
                  extra=[("prev", {"building", "work", "parking", "residence", "planning", "fishing", "hunting", "travel", "learner's", "special", "a", "the", "his", "her", "their", "your", "our", "my"}, "noun", 0.92),
                         ("next", {"holder", "holders", "application", "fee", "fees", "office", "process", "requirements"}, "noun", 0.9)]),
    "permits": _nv("P ER1 M IH0 T S", "P ER0 M IH1 T S", None, None, default="verb",
                   extra=[("prev", {"building", "work", "parking", "residence", "planning", "fishing", "hunting", "travel", "issued", "issue", "issues", "grant", "granted", "for", "of"}, "noun", 0.9)]),
    "conduct": _nv("K AA1 N D AH0 K T", "K AH0 N D AH1 K T", "kon-dukt", "kun-dukt", default="verb",
                   extra=[("prev", {"code", "of", "good", "bad", "professional", "his", "her", "their", "misconduct", "disorderly", "personal", "ethical", "proper", "improper", "the"}, "noun", 0.9),
                          ("next", {"a", "an", "the", "research", "interviews", "business", "surveys", "tests", "experiments", "electricity", "heat", "an", "themselves", "yourself", "itself", "investigations", "inspections"}, "verb", 0.88)]),
    "contract": _nv("K AA1 N T R AE0 K T", "K AH0 N T R AE1 K T", "kon-trakt", "kun-trakt", default="noun",
                    extra=[("next", {"a", "an", "the", "malaria", "covid", "virus", "measles", "infection", "disease", "when", "as", "slightly", "and", "rapidly"}, "verb", 0.86),
                           ("next", {"law", "worker", "workers", "work", "terms", "negotiations", "price", "value", "dispute", "employee", "employees", "killer", "bridge", "manufacturing"}, "noun", 0.92)]),
    "content": _av("K AA1 N T EH0 N T", "K AH0 N T EH1 N T", "kon-tent", "kun-tent", default="adj",
                   extra=[("next", {"with", "to"}, "verb", 0.88), ("prev", {"feel", "felt", "seem", "seemed", "perfectly", "quite", "very", "more", "less", "be", "being", "remain", "remained", "is", "was", "are", "were", "am", "look", "looked"}, "verb", 0.84),
                          ("prev", {"the", "a", "its", "their", "our", "your", "his", "her", "of", "web", "online", "digital", "video", "new", "original", "fat", "sugar", "salt", "water", "moisture", "alcohol", "user", "media", "social", "this", "that", "high", "low", "carbon", "protein", "editorial", "explicit", "harmful", "lead", "copper", "iron"}, "adj", 0.9),
                          ("next", {"creator", "creators", "creation", "marketing", "management", "strategy", "moderation", "type", "types", "filter", "filters", "warning", "warnings", "delivery", "provider", "providers", "policy", "rating", "ratings", "writer", "writers", "library", "is", "was", "of"}, "adj", 0.9)],
                   ag="what something contains (noun)", vg="satisfied (adjective) / to satisfy"),
    "close": _av("K L OW1 S", "K L OW1 Z", "klohss", "klohz", default="verb",
                 extra=[("next", {"to", "by", "friend", "friends", "relative", "relatives", "call", "calls", "contact", "contacts", "together",
                                  "ally", "allies", "family", "attention", "relationship", "relationships", "race", "second", "match", "game",
                                  "range", "look", "behind", "up", "enough", "proximity", "encounter", "encounters", "shave", "quarters", "eye", "watch", "examination", "inspection", "personal", "knit"}, "adj", 0.88),
                        ("prev", {"very", "so", "too", "quite", "fairly", "pretty", "a", "as", "is", "was", "are", "were", "be", "been", "get", "got", "getting", "come", "came", "stay", "stayed", "keep", "kept", "hold", "held", "draw", "drew", "remain", "how"}, "adj", 0.84),
                        ("next", {"the", "this", "that", "it", "your", "my", "his", "her", "their", "our", "them", "down", "out", "off", "in", "at", "early", "today", "tonight", "tomorrow", "soon", "now", "a", "an", "all"}, "verb", 0.86),
                        ("prev", {"the", "at", "to"}, "verb", 0.55)]),
    "use": _nv("Y UW1 S", "Y UW1 Z", "yoos", "yooz", default="verb",
               extra=[("prev", {"of", "in", "no", "the", "for", "any", "its", "their", "our", "his", "her", "my", "your", "out", "into", "this",
                                "that", "much", "fair", "personal", "commercial", "drug", "land", "water", "energy", "daily", "frequent",
                                "proper", "intended", "widespread", "heavy", "first", "careful"}, "noun", 0.92),
                      ("next", {"of", "case", "cases", "is", "was", "by", "for"}, "noun", 0.84)]),
    "used": {"senses": {"accustomed": ("Y UW1 S T", "yoost", "used to: did habitually; accustomed"), "employed": ("Y UW1 Z D", "yoozd", "past of use")},
             "pos": {}, "default": "employed", "rules": []},                       # rules in _used()
    "house": _nv("HH AW1 S", "HH AW1 Z", "howss", "howz", default="noun",
                 extra=[("next", {"the", "a", "an", "up", "refugees", "over", "thousands", "hundreds", "more", "all", "many", "some", "several"}, "verb", 0.78),
                        ("prev", {"will", "can", "could", "to", "would", "which", "that"}, "verb", 0.8)]),
    "excuse": _nv("IH0 K S K Y UW1 S", "IH0 K S K Y UW1 Z", "ex-kyooss", "ex-kyooz", default="noun",
                  extra=[("next", {"me", "us", "him", "her", "them", "my", "the", "yourself", "myself"}, "verb", 0.92)]),
    "abuse": _nv("AH0 B Y UW1 S", "AH0 B Y UW1 Z", "uh-byooss", "uh-byooz", default="noun",
                 extra=[("prev", {"child", "drug", "substance", "alcohol", "sexual", "physical", "domestic", "verbal", "emotional", "elder", "of", "from", "against", "power"}, "noun", 0.92)]),
    "refuse": _nv("R EH1 F Y UW0 S", "R IH0 F Y UW1 Z", "reff-yooss", "rih-fyooz", default="verb",
                  extra=[("next", {"collection", "collector", "collectors", "bin", "bins", "truck", "trucks", "disposal", "dump", "site", "tip", "sack", "sacks", "heap"}, "noun", 0.92),
                         ("next", {"to"}, "verb", 0.92)]),
    "advocate": _nv("AE1 D V AH0 K AH0 T", "AE1 D V AH0 K EY2 T", "ad-vuh-kit", "ad-vuh-kayt", default="noun",
                    extra=[("next", {"for", "the", "a", "that", "change", "reform", "peace"}, "verb", 0.85)]),
    "estimate": _nv("EH1 S T AH0 M AH0 T", "EH1 S T AH0 M EY2 T", "est-uh-mit", "est-uh-mayt", default="noun",
                    extra=[("next", {"that", "the", "how", "what", "it", "its", "their", "your", "costs", "cost", "about", "around"}, "verb", 0.86)]),
    "estimates": _nv("EH1 S T AH0 M AH0 T S", "EH1 S T AH0 M EY2 T S", "est-uh-mits", "est-uh-mayts", default="noun",
                     extra=[("next", {"that", "the", "how", "what", "it", "its"}, "verb", 0.86), ("prev", SUBJ3 | {"report", "study", "agency", "government", "survey"}, "verb", 0.82)]),
    "graduate": _nv("G R AE1 JH UW0 AH0 T", "G R AE1 JH UW0 EY2 T", "grad-joo-it", "grad-joo-ayt", default="noun",
                    extra=[("next", {"from", "in", "with", "this", "next", "high", "summa", "magna", "cum"}, "verb", 0.88),
                           ("next", {"school", "student", "students", "degree", "program", "programme", "study", "studies", "level", "courses", "course", "research", "scheme", "position"}, "noun", 0.92)]),
    "separate": _av("S EH1 P ER0 AH0 T", "S EH1 P ER0 EY2 T", "sep-rit", "sep-uh-rayt", default="adj",
                    extra=[("next", {"the", "them", "it", "fact", "eggs", "yolks", "out", "from", "into", "us", "him", "her", "these", "those", "waste", "recycling"}, "verb", 0.84)]),
    "moderate": _av("M AA1 D ER0 AH0 T", "M AA1 D ER0 EY2 T", "mod-er-it", "mod-er-ayt", default="adj",
                    extra=[("next", {"the", "a", "debate", "discussion", "panel", "comments", "forum", "session", "their", "his", "her", "its"}, "verb", 0.86)]),
    "alternate": _av("AO1 L T ER0 N AH0 T", "AO1 L T ER0 N EY2 T", "all-ter-nit", "all-ter-nayt", default="adj",
                     extra=[("next", {"between", "with"}, "verb", 0.9)]),
    "appropriate": _av("AH0 P R OW1 P R IY0 AH0 T", "AH0 P R OW1 P R IY0 EY2 T", "uh-proh-pree-it", "uh-proh-pree-ayt", default="adj",
                       extra=[("next", {"funds", "money", "land", "the", "their", "his", "her"}, "verb", 0.8)]),
    "approximate": _av("AH0 P R AA1 K S AH0 M AH0 T", "AH0 P R AA1 K S AH0 M EY2 T", "uh-prok-suh-mit", "uh-prok-suh-mayt", default="adj"),
    "associate": _nv("AH0 S OW1 S IY0 AH0 T", "AH0 S OW1 S IY0 EY2 T", "uh-soh-see-it", "uh-soh-see-ayt", default="verb",
                     extra=[("next", {"professor", "director", "editor", "degree", "degrees", "producer", "member", "dean", "justice", "partner", "manager", "'s"}, "noun", 0.92),
                            ("next", {"with"}, "verb", 0.9)]),
    "duplicate": _av("D UW1 P L AH0 K AH0 T", "D UW1 P L AH0 K EY2 T", "doo-pluh-kit", "doo-pluh-kayt", default="adj"),
    "elaborate": _av("IH0 L AE1 B ER0 AH0 T", "IH0 L AE1 B ER0 EY2 T", "ih-lab-er-it", "ih-lab-er-ayt", default="adj",
                     extra=[("next", {"on", "upon", "further"}, "verb", 0.92)]),
    "intimate": _av("IH1 N T AH0 M AH0 T", "IH1 N T AH0 M EY2 T", "in-tuh-mit", "in-tuh-mayt", default="adj",
                    extra=[("next", {"that"}, "verb", 0.8)]),
    "deliberate": _av("D IH0 L IH1 B ER0 AH0 T", "D IH0 L IH1 B ER0 EY2 T", "dih-lib-er-it", "dih-lib-er-ayt", default="adj",
                      extra=[("next", {"on", "over", "about", "for", "whether"}, "verb", 0.88)]),
    "articulate": _av("AA0 R T IH1 K Y AH0 L AH0 T", "AA0 R T IH1 K Y AH0 L EY2 T", "ar-tik-yuh-lit", "ar-tik-yuh-layt", default="adj",
                      extra=[("next", {"the", "a", "their", "his", "her", "your", "what", "how", "why", "clearly", "it", "them"}, "verb", 0.86)]),
    "perfect": _av("P ER1 F IH0 K T", "P ER0 F EH1 K T", "per-fikt", "per-fekt", default="adj"),
    "invalid": {"senses": {"adj": ("IH0 N V AE1 L IH0 D", "in-val-id", "not valid"), "noun": ("IH1 N V AH0 L IH0 D", "in-vuh-lid", "a person made weak by illness")},
                "pos": {}, "default": "adj",
                "rules": [("next", {"password", "input", "argument", "arguments", "data", "entry", "entries", "request", "value", "values", "syntax",
                                    "format", "token", "ticket", "license", "licence", "signature", "address", "email", "option", "parameter",
                                    "parameters", "date", "number", "field", "key", "url", "file", "character", "characters", "credentials",
                                    "contract", "vote", "votes", "ballot", "ballots", "marriage", "will", "claim", "claims", "code", "type", "move", "selection", "response", "certificate", "id", "operation", "state"}, "adj", 0.95),
                          ("prev", {"is", "was", "are", "were", "be", "been", "becomes", "became", "deemed", "declared", "considered", "rendered", "found", "ruled", "being"}, "adj", 0.92),
                          ("near", {"nursed", "nursing", "bedridden", "chair", "cared", "invalids", "sickbed", "bed"}, "noun", 0.78)]},
    "polish": {"senses": {"shine": ("P AA1 L IH0 SH", "pol-ish", "to shine; a shine"), "poland": ("P OW1 L IH0 SH", "poh-lish", "of Poland")},
               "pos": {}, "default": "shine", "rules": []},                         # decided by the capital letter in _case()
    "august": {"senses": {"month": ("AO1 G AH0 S T", None, "the month"), "noble": ("AO0 G AH1 S T", "aw-gust", "respected and impressive")},
               "pos": {}, "default": "month", "rules": []},
    "nice": {"senses": {"pleasant": ("N AY1 S", None, "pleasant"), "city": ("N IY1 S", "neess", "the city in France")}, "pos": {}, "default": "pleasant", "rules": []},
    "resume": {"senses": {"verb": ("R IH0 Z UW1 M", "rih-zoom", "to continue"), "cv": ("R EH1 Z AH0 M EY2", "rez-uh-may", "a CV, résumé")},
               "pos": {"verb": "verb", "noun": "cv"}, "default": "verb",
               "rules": [("prev", {"your", "my", "his", "her", "their", "a", "the", "updated", "send", "sent", "submit", "submitted", "attach",
                                   "attached", "upload", "uploaded", "polished", "strong", "impressive", "our", "this", "professional"}, "cv", 0.9),
                         ("near", {"cover", "letter", "job", "jobs", "cv", "apply", "applying", "applicant", "applicants", "hiring", "recruiter", "interview", "linkedin"}, "cv", 0.82)]},
    "putting": {"senses": {"placing": ("P UH1 T IH0 NG", None, "placing"), "golf": ("P AH1 T IH0 NG", "putt-ing", "golf: tapping the ball")},
                "pos": {}, "default": "placing",
                "rules": [("near", {"green", "golf", "putter", "hole", "holes", "stroke", "strokes", "birdie", "par", "golfer", "golfers", "clubs", "course", "tee"}, "golf", 0.86)]},
    "learned": {"senses": {"past": ("L ER1 N D", None, "past of learn"), "scholarly": ("L ER1 N IH0 D", "ler-nid", "having much knowledge")},
                "pos": {}, "default": "past",
                "rules": [("prev", {"a", "the", "very", "most", "highly", "deeply", "more", "an"}, "scholarly", 0.85),
                          ("next", {"friend", "colleague", "scholar", "scholars", "judge", "man", "woman", "men", "society", "societies", "journal", "professor", "counsel"}, "scholarly", 0.88)]},
    "blessed": {"senses": {"past": ("B L EH1 S T", None, "past of bless"), "holy": ("B L EH1 S IH0 D", "bless-id", "holy; fortunate")},
                "pos": {}, "default": "past",
                "rules": [("prev", {"the", "a", "most", "thrice", "this"}, "holy", 0.84), ("next", {"virgin", "mother", "sacrament", "event", "day", "are", "be", "art", "relief", "peace", "silence"}, "holy", 0.84)]},
    "aged": {"senses": {"age": ("EY1 JH D", None, "of the age of; matured"), "old": ("EY1 JH IH0 D", "ay-jid", "very old")},
             "pos": {}, "default": "age",
             "rules": [("prev", {"the", "an", "very", "infirm"}, "old", 0.8), ("next", {"parents", "parent", "mother", "father", "relatives", "and"}, "old", 0.72)]},
    "moped": {"senses": {"vehicle": ("M OW1 P EH2 D", "moh-ped", "a small motorcycle"), "past": ("M OW1 P T", "mohpt", "past of mope")},
              "pos": {"noun": "vehicle", "verb": "past"}, "default": "vehicle",
              "rules": [("prev", SUBJ | SUBJ3 | {"just", "and"}, "past", 0.84), ("next", {"around", "about"}, "past", 0.84)]},
    "axes": {"senses": {"axe": ("AE1 K S IH0 Z", "ak-siz", "plural of axe"), "axis": ("AE1 K S IY0 Z", "ak-seez", "plural of axis")},
             "pos": {}, "default": "axe",
             "rules": [("near", {"graph", "graphs", "chart", "charts", "x", "y", "z", "coordinate", "coordinates", "plot", "horizontal", "vertical",
                                 "labels", "label", "rotation", "symmetry", "principal", "three", "both", "scale", "major", "minor"}, "axis", 0.86),
                       ("near", {"wood", "chop", "chopped", "sharpen", "sharpened", "battle", "fire", "lumberjack", "lumberjacks", "tree", "trees", "blades", "handles", "swung", "throwing"}, "axe", 0.86)]},
    "buffet": {"senses": {"meal": ("B AH0 F EY1", "buh-fay", "a self-service meal"), "strike": ("B AH1 F IH0 T", "buff-it", "to strike repeatedly")},
               "pos": {}, "default": "meal",
               "rules": [("prev", {"winds", "waves", "storms", "storm", "by"}, "strike", 0.8), ("next", {"the", "them", "it", "us"}, "strike", 0.7)]},
    "entrance": _nv("EH1 N T R AH0 N S", "IH0 N T R AE1 N S", "en-truns", "in-trans", default="noun",
                    extra=[("next", {"them", "him", "her", "us", "you", "audiences", "the", "listeners", "readers", "viewers"}, "verb", 0.86)]),
    "compact": _av("K AA1 M P AE0 K T", "K AH0 M P AE1 K T", "kom-pakt", "kum-pakt", default="adj"),
    "compound": _nv("K AA1 M P AW0 N D", "K AH0 M P AW1 N D", "kom-pownd", "kum-pownd", default="noun",
                    extra=[("next", {"the", "this", "that", "it", "its", "their", "problems", "matters", "interest"}, "verb", 0.8)]),
    "console": _nv("K AA1 N S OW0 L", "K AH0 N S OW1 L", "kon-sohl", "kun-sohl", default="noun",
                   extra=[("next", {"her", "him", "them", "you", "me", "us", "the", "his", "their", "herself", "himself", "themselves"}, "verb", 0.86)]),
    "combat": _nv("K AA1 M B AE0 T", "K AH0 M B AE1 T", "kom-bat", "kum-bat", default="noun",
                  extra=[("next", {"the", "this", "climate", "crime", "fraud", "disease", "poverty", "terrorism", "it", "them", "corruption", "misinformation", "inflation", "racism"}, "verb", 0.88)]),
    "conflict": _nv("K AA1 N F L IH0 K T", "K AH0 N F L IH1 K T", "kon-flikt", "kun-flikt", default="noun", extra=[("next", {"with"}, "verb", 0.72)]),
    "contest": _nv("K AA1 N T EH0 S T", "K AH0 N T EH1 S T", "kon-test", "kun-test", default="noun",
                   extra=[("next", {"the", "this", "that", "a", "an", "his", "her", "their"}, "verb", 0.75)]),
    "contrast": _nv("K AA1 N T R AE0 S T", "K AH0 N T R AE1 S T", "kon-trast", "kun-trast", default="noun", extra=[("next", {"with", "sharply"}, "verb", 0.84)]),
    "convert": _nv("K AA1 N V ER0 T", "K AH0 N V ER1 T", "kon-vert", "kun-vert", default="verb"),
    "convict": _nv("K AA1 N V IH0 K T", "K AH0 N V IH1 K T", "kon-vikt", "kun-vikt", default="verb", extra=[("prev", {"escaped", "former", "ex", "an"}, "noun", 0.92)]),
    "decrease": _nv("D IY1 K R IY0 S", "D IH0 K R IY1 S", "dee-krees", "dih-krees", default="noun", extra=[("next", {"in", "of"}, "noun", 0.9)]),
    "increase": _nv("IH1 N K R IY0 S", "IH0 N K R IY1 S", "in-krees", "in-krees", default="noun", extra=[("next", {"in", "of"}, "noun", 0.9)]),
    "digest": _nv("D AY1 JH EH0 S T", "D AY0 JH EH1 S T", "dye-jest", "dye-jest", default="verb", extra=[("prev", {"weekly", "daily", "monthly", "reader's", "news"}, "noun", 0.9)]),
    "discount": _nv("D IH1 S K AW0 N T", "D IH0 S K AW1 N T", "dis-kownt", "dis-kownt", default="noun",
                    extra=[("next", {"the", "this", "that", "it", "any", "rate", "store", "code", "codes", "price", "prices", "card", "on", "for", "of"}, "noun", 0.75),
                           ("next", {"the possibility", "them", "him", "her"}, "verb", 0.8)]),
    "escort": _nv("EH1 S K AO0 R T", "EH0 S K AO1 R T", None, None, default="noun", extra=[("next", {"them", "him", "her", "the", "you", "us", "me"}, "verb", 0.86)]),
    "export": _nv("EH1 K S P AO0 R T", "IH0 K S P AO1 R T", "ex-port", "ex-port", default="noun"),
    "import": _nv("IH1 M P AO0 R T", "IH0 M P AO1 R T", "im-port", "im-port", default="noun"),
    "exports": _nv("EH1 K S P AO0 R T S", "IH0 K S P AO1 R T S", None, None, default="noun", extra=[("prev", SUBJ3 | {"country", "china", "company"}, "verb", 0.82)]),
    "imports": _nv("IH1 M P AO0 R T S", "IH0 M P AO1 R T S", None, None, default="noun", extra=[("prev", SUBJ3 | {"country", "module", "file", "script", "company"}, "verb", 0.82)]),
    "extract": _nv("EH1 K S T R AE0 K T", "IH0 K S T R AE1 K T", "ex-trakt", "ex-trakt", default="verb",
                   extra=[("prev", {"vanilla", "yeast", "plant", "herbal", "malt", "almond", "an", "short"}, "noun", 0.92)]),
    "insert": _nv("IH1 N S ER0 T", "IH0 N S ER1 T", "in-sert", "in-sert", default="verb"),
    "insult": _nv("IH1 N S AH0 L T", "IH0 N S AH1 L T", "in-sult", "in-sult", default="noun", extra=[("next", {"them", "him", "her", "you", "me", "us", "the", "people"}, "verb", 0.86)]),
    "progress": _nv("P R AA1 G R EH0 S", "P R AH0 G R EH1 S", "prog-ress", "pruh-gress", default="noun",
                    extra=[("next", {"to", "through", "toward", "towards", "from", "beyond", "slowly", "quickly", "rapidly"}, "verb", 0.84),
                           ("next", {"report", "reports", "bar", "made", "has", "is", "was", "of", "in", "on"}, "noun", 0.88)]),
    "protest": _nv("P R OW1 T EH0 S T", "P R AH0 T EH1 S T", "proh-test", "pruh-test", default="noun", extra=[("next", {"against"}, "verb", 0.6)]),
    "rebel": _nv("R EH1 B AH0 L", "R IH0 B EH1 L", "reb-ul", "rih-bel", default="noun", extra=[("next", {"against"}, "verb", 0.92)]),
    "refund": _nv("R IY1 F AH0 N D", "R IH0 F AH1 N D", "ree-fund", "rih-fund", default="noun"),
    "reject": _nv("R IY1 JH EH0 K T", "R IH0 JH EH1 K T", "ree-jekt", "rih-jekt", default="verb"),
    "subject": _nv("S AH1 B JH IH0 K T", "S AH0 B JH EH1 K T", "sub-jikt", "sub-jekt", default="noun",
                   extra=[("next", {"to"}, "noun", 0.6), ("next", {"them", "him", "her", "us", "you", "it", "themselves", "himself", "herself"}, "verb", 0.88)]),
    "suspect": _nv("S AH1 S P EH0 K T", "S AH0 S P EH1 K T", "sus-pekt", "suh-spekt", default="verb",
                   extra=[("prev", {"prime", "main", "chief", "key", "murder", "a", "the", "only", "second", "possible"}, "noun", 0.9),
                          ("next", {"that", "foul", "him", "her", "them", "it"}, "verb", 0.9)]),
    "survey": _nv("S ER1 V EY0", "S ER0 V EY1", "ser-vay", "ser-vay", default="noun"),
    "transport": _nv("T R AE1 N S P AO0 R T", "T R AE0 N S P AO1 R T", "trans-port", "trans-port", default="noun",
                     extra=[("next", {"the", "them", "it", "goods", "passengers", "patients", "us", "you", "him", "her"}, "verb", 0.84)]),
    "upset": _nv("AH1 P S EH0 T", "AH0 P S EH1 T", "up-set", "up-set", default="verb",
                 extra=[("next", {"stomach", "tummy", "about", "by", "with", "that", "over"}, "verb", 0.92),
                        ("prev", {"an", "big", "major", "huge", "shock", "stunning", "surprise", "biggest"}, "noun", 0.9)]),
    "torment": _nv("T AO1 R M EH0 N T", "T AO0 R M EH1 N T", None, None, default="noun"),
    "segment": _nv("S EH1 G M AH0 N T", "S EH0 G M EH1 N T", None, None, default="noun", extra=[("next", {"the", "customers", "users", "markets", "it", "them"}, "verb", 0.84)]),
    "frequent": _av("F R IY1 K W AH0 N T", "F R IY0 K W EH1 N T", "free-kwent", "free-kwent", default="adj",
                    extra=[("next", {"the", "this", "that", "bars", "cafes", "restaurants", "clubs", "these", "those"}, "verb", 0.84)]),
    "attribute": _nv("AE1 T R AH0 B Y UW0 T", "AH0 T R IH1 B Y UW0 T", "at-ruh-byoot", "uh-trib-yoot", default="noun", extra=[("next", {"the", "it", "this", "that", "their", "his", "her", "its"}, "verb", 0.84)]),
    "affect": _nv("AE1 F EH0 K T", "AH0 F EH1 K T", "af-ekt", "uh-fekt", default="verb"),
    "incense": _nv("IH1 N S EH0 N S", "IH0 N S EH1 N S", "in-sens", "in-sens", default="noun", extra=[("next", {"them", "him", "her", "the", "us"}, "verb", 0.8)]),
    "address": _nv("AE1 D R EH0 S", "AH0 D R EH1 S", None, None, default="noun",
                   extra=[("next", {"the", "this", "these", "those", "it", "them", "issues", "concerns", "problems", "questions", "climate", "their", "your", "our"}, "verb", 0.88),
                          ("prev", {"email", "e-mail", "ip", "home", "mailing", "web", "postal", "street", "billing", "shipping", "return", "inaugural", "keynote", "an", "the", "your", "my", "our", "their", "his", "her", "new", "old"}, "noun", 0.92)]),
    "recount": _nv("R IY1 K AW0 N T", "R IH0 K AW1 N T", "ree-kownt", "rih-kownt", default="verb", extra=[("prev", {"a", "the", "full", "manual", "partial"}, "noun", 0.9)]),
}
# ARPABET and respellings are QueryBook's own transcriptions; senses with no reliable respelling (None) are left to
# the engine on text-only engines and say so.

# forms tagged by the grammar cues: kinds
for _w, _e in H.items():
    _e.setdefault("kind", "tense" if _w == "read" else "used" if _w == "used" else "case" if _w in ("polish", "august", "nice") else
                  "nv" if set(_e["senses"]) == {"noun", "verb"} else "av" if set(_e["senses"]) == {"adj", "verb"} else "sense")

WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)
TOKEN = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*|\d+(?:[.,]\d+)*|[.!?;:]|[,\"()\[\]—–-]", re.UNICODE)
INLINE = re.compile(r"\{([^{}|]+)\|([^{}]+)\}")
BOUNDARY = {".", "!", "?", ";", ":"}


# ------------------------------------------------------------------------------------------------ lexicon
class Lexicon:
    """The admin's pronunciation lexicon (organisation scope), kept as JSON in the data folder. Entries:
       {term, ipa?, arpa?, respell?, alias?, case_sensitive?, note?} — alias = say these words instead (SQL → sequel)."""

    def __init__(self, folder=None):
        self.path = os.path.join(folder, "pronunciation-lexicon.json") if folder else None
        self.lock = threading.Lock()
        self._mtime, self._entries = None, []

    def entries(self):
        if not self.path or not os.path.exists(self.path):
            return []
        m = os.path.getmtime(self.path)
        if m != self._mtime:
            try:
                with open(self.path, encoding="utf-8") as f:
                    self._entries = [e for e in json.load(f).get("entries", []) if e.get("term")]
            except (OSError, ValueError):
                self._entries = []
            self._mtime = m
        return list(self._entries)

    def put(self, entry):
        e = normalise_entry(entry)
        with self.lock:
            items = [x for x in self.entries() if x["term"].lower() != e["term"].lower()] + [e]
            self._write(items)
        return e

    def remove(self, term):
        with self.lock:
            items = [x for x in self.entries() if x["term"].lower() != str(term).lower()]
            self._write(items)
        return {"removed": term}

    def _write(self, items):
        if not self.path:
            raise ValueError("no data folder for the lexicon")
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"entries": sorted(items, key=lambda x: x["term"].lower())}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)
        self._mtime = None


def normalise_entry(entry):
    term = " ".join(str(entry.get("term") or "").split())
    if not term or len(term) > 80:
        raise ValueError("Give the word or term (up to 80 characters).")
    e = {"term": term, "case_sensitive": bool(entry.get("case_sensitive")), "note": str(entry.get("note") or "")[:200]}
    ipa, arpa, alias = (str(entry.get(k) or "").strip() for k in ("ipa", "arpa", "alias"))
    respell = str(entry.get("respell") or "").strip()
    if arpa:
        arpa = " ".join(arpa.upper().split())
        if any(_split(arpa)[i][0] not in VOWELS | set(IPA_C) for i in range(len(_split(arpa)))):
            raise ValueError("ARPABET symbols not recognised: %s" % arpa)
    elif ipa:
        arpa = ipa_to_arpa(ipa) or ""
    if not (ipa or arpa or alias or respell):
        raise ValueError("Give a pronunciation: IPA (/lɪv/), ARPABET (L IH1 V), a respelling (liv) or words to say instead (sequel).")
    e.update({k: v for k, v in (("ipa", ipa.strip("/[] ") or (arpa_to_ipa(arpa) if arpa else "")), ("arpa", arpa), ("alias", alias),
                                ("respell", respell or (arpa_to_respell(arpa) if arpa and not alias else ""))) if v})
    return e


_ACTIVE = {"lexicon": Lexicon(None)}


def set_folder(folder):
    _ACTIVE["lexicon"] = Lexicon(folder)


def active_lexicon():
    return _ACTIVE["lexicon"]


# ------------------------------------------------------------------------------------------------ resolution
class Item(dict):
    pass


def _ctx(toks, i):
    """the words around token i inside its clause: (prev, prev2, next, next2, window) — lower case, punctuation stops"""
    def back(k):
        j, n = i - 1, 0
        while j >= 0:
            if toks[j]["t"] in BOUNDARY or toks[j]["t"] in (",", "—", "–", "(", ")", '"'):
                return None
            n += 1
            if n == k:
                return toks[j]["l"]
            j -= 1
        return None

    def fwd(k):
        j, n = i + 1, 0
        while j < len(toks):
            if toks[j]["t"] in BOUNDARY or toks[j]["t"] in (",", "—", "–", "(", ")", '"'):
                return None
            n += 1
            if n == k:
                return toks[j]["l"]
            j += 1
        return None
    win = [toks[j]["l"] for j in range(max(0, i - 5), min(len(toks), i + 6)) if j != i and toks[j]["word"]]
    return back(1), back(2), fwd(1), fwd(2), win


def _pos(word, p1, p2, n1, n2, kind):
    """grammar cues → (part of speech, confidence, reason) or None"""
    plural = word.endswith("s") and word not in ("does", "lives", "tears", "winds", "bows", "rows", "axes")
    if p1 in MODAL:
        return ("verb", 0.86 if p1 == "to" else 0.92, "after '%s'" % p1)
    if p1 in SUBJ:
        return ("verb", 0.9, "after the subject '%s'" % p1)
    if p1 in SUBJ3 and plural:
        return ("verb", 0.88, "after '%s' with -s" % p1)
    if p1 == "who" and not plural:
        return ("verb", 0.8, "after 'who'")
    if p1 in ADV and (p2 in SUBJ | SUBJ3 | MODAL):
        return ("verb", 0.85, "after '%s %s'" % (p2, p1))
    if p1 in HAVE and kind != "nv":
        return ("verb", 0.85, "after '%s'" % p1)
    if p1 in DET:
        return ("adj" if kind == "av" else "noun", 0.88, "after '%s'" % p1)
    if p1 in PREP:
        return ("adj" if kind == "av" else "noun", 0.8, "after the preposition '%s'" % p1)
    if p1 in INTENS and kind == "av":
        return ("adj", 0.86, "after '%s'" % p1)
    if p1 in BE:
        return ("adj" if kind == "av" else "noun", 0.72, "after '%s'" % p1)
    if p1 and p1.isdigit():
        return ("noun", 0.85, "after a number")
    if p1 is None and n1 in DET | OBJ | {"your", "her", "the", "all"}:
        return ("verb", 0.78, "starts the clause before '%s' (an instruction)" % n1)
    if n1 in OBJ - {"this", "these", "those"} and p1 not in DET:
        return ("verb", 0.8, "before the object '%s'" % n1)
    if n1 == "of" and kind != "av":
        return ("noun", 0.75, "before 'of'")
    if p1 and p1.endswith("'s"):
        return ("noun", 0.8, "after a possessive")
    return None


def _tense(toks, i, p1, p2, n1, win):
    """read: present or past"""
    if p1 in {"to", "will", "would", "can", "could", "should", "must", "might", "may", "shall", "do", "does", "don't", "doesn't",
              "won't", "can't", "cannot", "please", "let's", "i'll", "we'll", "you'll", "they'll"}:
        return ("present", 0.92, "after '%s'" % p1)
    if p1 in {"did", "didn't", "never", "not"} and p2 in {"did", "didn't"}:
        return ("present", 0.9, "after '%s'" % p1)
    if p1 in {"did", "didn't"}:
        return ("present", 0.92, "after '%s'" % p1)
    if p1 in HAVE | {"been", "was", "were", "is", "are", "be", "being", "am", "well", "widely", "already", "just", "had", "having",
                     "were", "gets", "got", "get", "once", "previously", "recently", "first", "badly", "poorly", "much", "most"} or \
            p2 in HAVE and p1 in ADV | SUBJ | {"he", "she", "it", "not", "never", "all", "already", "just", "everyone", "anyone"}:
        return ("past", 0.92, "past participle after '%s'" % p1)
    if p1 in {"he", "she", "it", "who", "someone", "everyone", "nobody", "that", "which"} | {"jane", "john"} and n1 != "s":
        return ("past", 0.88, "'%s read' (present would be 'reads')" % p1)
    past_t, now_t = any(w in PAST_TIME for w in win), any(w in PRESENT_MARK for w in win)
    if past_t and not now_t:
        return ("past", 0.84, "a past-time word nearby (%s)" % next(w for w in win if w in PAST_TIME))
    if now_t and not past_t:
        return ("present", 0.82, "a habitual-time word nearby (%s)" % next(w for w in win if w in PRESENT_MARK))
    if p1 is None and n1 in DET | OBJ | {"aloud", "out", "carefully", "this", "the"} and i == 0:
        return ("present", 0.8, "starts the sentence: an instruction")
    if p1 is None and n1 in DET | OBJ | {"aloud", "carefully"}:
        return ("present", 0.75, "starts the clause: an instruction")
    if n1 in {"aloud", "out"} and p1 in SUBJ:
        return ("present", 0.6, "habit or past: unclear")
    past_verbs = sum(1 for w in win if re.fullmatch(r"[a-z]+ed", w) or w in {"was", "were", "had", "did", "went", "said", "saw", "took", "came", "wrote", "told", "found", "felt", "gave", "made", "began", "knew", "thought"})
    if past_verbs:
        return ("past", 0.72, "past-tense verbs nearby")
    return None


def _used(p1, n1, n2):
    if n1 != "to":
        return ("employed", 0.92, "not followed by 'to'")
    if p1 in SUBJ | SUBJ3 | {"never", "always", "once", "didn't", "we", "people", "i", "it"} - {"that", "which"}:
        return ("accustomed", 0.88, "'%s used to': a past habit" % p1)
    if p1 in {"get", "got", "getting", "gets", "become", "became", "grow", "grew"}:
        return ("accustomed", 0.9, "'%s used to': become accustomed" % p1)
    if p1 in {"be", "is", "are", "was", "were", "been", "being", "am"}:
        if n2 in {"it", "this", "that", "them", "the", "a", "an", "being", "having", "working", "living", "doing", "getting", "seeing",
                  "hearing", "waiting", "people", "him", "her", "me", "us", "such"} or (n2 or "").endswith("ing"):
            return ("accustomed", 0.82, "'be used to %s': accustomed to" % n2)
        return ("employed", 0.8, "'be used to %s': used for a purpose" % n2)
    return ("employed", 0.6, "'used to' after '%s': unclear" % p1)


def _case(word_raw, at_start, n1, entry_key):
    cap = word_raw[:1].isupper()
    if entry_key == "polish":
        if cap and not at_start:
            return ("poland", 0.95, "capital letter mid-sentence: of Poland")
        if not cap:
            return ("shine", 0.95, "lower case: to shine")
        if n1 in {"the", "your", "my", "it", "them", "off", "up", "his", "her", "their", "our", "shoes", "furniture", "silver", "nails"}:
            return ("shine", 0.85, "starts a sentence before '%s'" % n1)
        if n1 in {"people", "language", "government", "city", "cuisine", "food", "history", "border", "president", "zloty", "sausage", "army", "citizens", "and", "is", "was", "writer", "poet"}:
            return ("poland", 0.85, "starts a sentence before '%s'" % n1)
        return None
    if entry_key == "august":
        if cap:
            return ("month", 0.95 if not at_start else 0.8, "capital letter: the month")
        return ("noble", 0.9, "lower case: respected and impressive")
    if entry_key == "nice":
        if cap and not at_start:
            return ("city", 0.92, "capital letter mid-sentence: the city")
        if not cap:
            return ("pleasant", 0.97, "lower case: pleasant")
        return None
    return None


def _rules(entry, word, toks, i, p1, p2, n1, n2, win):
    best = None
    for kind, words, sense, conf in entry["rules"]:
        hit = (kind == "next" and n1 in words) or (kind == "prev" and p1 in words) or (kind == "near" and any(w in words for w in win)) or \
              (kind == "next2" and (n1 in words or n2 in words)) or (kind == "end" and p1 in words and n1 is None) or \
              (kind == "prev2" and p2 in words)
        if hit and (best is None or conf > best[1]):
            what = {"next": "before '%s'" % n1, "prev": "after '%s'" % p1, "near": "near '%s'" % next((w for w in win if w in words), ""),
                    "next2": "before '%s'" % (n1 if n1 in words else n2), "end": "ends the phrase after '%s'" % p1,
                    "prev2": "after '%s %s'" % (p2, p1)}[kind]
            best = (sense, conf, what)
    return best


def _decide(entry, key, raw, toks, i):
    p1, p2, n1, n2, win = _ctx(toks, i)
    at_start = p1 is None and (i == 0 or toks[i - 1]["t"] in BOUNDARY or toks[i - 1]["t"] in ('"', "("))
    cands = []
    r = _rules(entry, key, toks, i, p1, p2, n1, n2, win)
    if r:
        cands.append((r[0], r[1] + 0.001, "word rule: " + r[2]))   # a word's own rule wins a tie
    k = entry["kind"]
    if k == "tense":
        t = _tense(toks, i, p1, p2, n1, win)
        if t:
            cands.append((t[0], t[1], "tense: " + t[2]))
    elif k == "used":
        t = _used(p1, n1, n2)
        cands.append((t[0], t[1], t[2]))
    elif k == "case":
        t = _case(raw, at_start, n1, key)
        if t:
            cands.append((t[0], t[1], t[2]))
    else:
        g = _pos(key, p1, p2, n1, n2, k)
        if g and entry["pos"].get(g[0]):
            cands.append((entry["pos"][g[0]], g[1], "grammar: %s %s" % (g[0], g[2])))
    if not cands:
        return entry["default"], 0.5, "no cue: the usual reading"
    sense, conf, why = max(cands, key=lambda c: c[1])
    return sense, round(min(conf, 0.99), 3), why


def _ipa_of(arpa):
    return arpa_to_ipa(arpa) if arpa else ""


def resolve(text, lexicon=None, lang="en"):
    """→ {"clean": text without inline marks, "items": [one per heteronym, lexicon term or inline mark]}. Deterministic."""
    lexicon = lexicon if lexicon is not None else active_lexicon()
    # 1. inline marks: {word|sense} {word|/ipa/} {word|alias words}
    clean, inline, pos = [], [], 0
    for m in INLINE.finditer(text or ""):
        clean.append(text[pos:m.start()])
        start = sum(len(x) for x in clean)
        word, spec = m.group(1).strip(), m.group(2).strip()
        clean.append(word)
        inline.append((start, start + len(word), word, spec))
        pos = m.end()
    clean.append((text or "")[pos:])
    clean = "".join(clean)
    items, taken = [], set()
    for start, end, word, spec in inline:
        e = H.get(word.lower())
        it = Item(start=start, end=end, word=word, source="inline", conf=1.0, reason="marked in the text", forced=True)
        if e and spec in e["senses"]:
            arpa, resp, gloss = e["senses"][spec]
            it.update(sense=spec, gloss=gloss, arpa=arpa, ipa=_ipa_of(arpa), respell=resp)
        elif spec.startswith("/") or any(ch in spec for ch in "ˈˌəɪʊæɑɔɛʃʒθðŋɹ"):
            ipa = spec.strip("/[] ")
            arpa = ipa_to_arpa(ipa)
            it.update(sense="ipa", gloss="", arpa=arpa, ipa=ipa, respell=arpa_to_respell(arpa) if arpa else None)
        else:
            it.update(sense="alias", gloss="said as '%s'" % spec, alias=spec, arpa=None, ipa=None, respell=None)
        items.append(it)
        taken.update(range(start, end))
    if lang != "en":
        return {"clean": clean, "items": items}
    # 2. lexicon terms (longest first; whole words)
    for e in sorted(lexicon.entries() if lexicon else [], key=lambda x: -len(x["term"])):
        flags = 0 if e.get("case_sensitive") else re.IGNORECASE
        for m in re.finditer(r"(?<![\w'’])%s(?![\w'’])" % re.escape(e["term"]), clean, flags):
            if any(k in taken for k in range(m.start(), m.end())):
                continue
            it = Item(start=m.start(), end=m.end(), word=m.group(0), source="lexicon", conf=1.0, reason="the pronunciation lexicon" +
                      (" (%s)" % e["note"] if e.get("note") else ""), forced=True, sense="lexicon", gloss=e.get("note", ""),
                      arpa=e.get("arpa") or None, ipa=e.get("ipa") or None, respell=e.get("respell") or None, alias=e.get("alias") or None)
            items.append(it)
            taken.update(range(m.start(), m.end()))
    # 3–5. heteronyms by rules
    toks = [{"t": m.group(0), "l": m.group(0).lower().replace("’", "'"), "s": m.start(), "e": m.end(), "word": bool(WORD.fullmatch(m.group(0)))}
            for m in TOKEN.finditer(clean)]
    for i, tk in enumerate(toks):
        if not tk["word"] or tk["s"] in taken:
            continue
        key = tk["l"]
        entry = H.get(key)
        if not entry:
            continue
        sense, conf, why = _decide(entry, key, tk["t"], toks, i)
        arpa, resp, gloss = entry["senses"][sense]
        alts = [{"sense": s, "ipa": _ipa_of(a), "gloss": g} for s, (a, _r, g) in entry["senses"].items() if s != sense]
        items.append(Item(start=tk["s"], end=tk["e"], word=tk["t"], source="rules" if conf > 0.5 else "default", sense=sense, gloss=gloss,
                          arpa=arpa, ipa=_ipa_of(arpa), respell=resp, conf=conf, reason=why, forced=conf >= FORCE,
                          ambiguous=conf < FORCE, alternatives=alts))
    items.sort(key=lambda x: x["start"])
    return {"clean": clean, "items": items}


# ------------------------------------------------------------------------------------------------ telling each engine
ENGINE_MODE = {"espeak": "espeak", "formant": "ipa-words", "sapi": "ssml", "say": "apple", "google_gemini": "respell",
               "google_cloud": "ssml", "elevenlabs": "respell", "openai": "respell", "azure": "ssml", "polly": "ssml"}
ELEVEN_PHONEME_MODELS = {"eleven_flash_v2", "eleven_turbo_v2", "eleven_monolingual_v1", "eleven_english_v1"}
MODE_NAME = {"ssml": "SSML <phoneme alphabet=\"ipa\"> tags", "espeak": "espeak-ng [[phoneme]] input", "apple": "macOS [[inpt PHON]] input",
             "respell": "respelled words (this engine takes text only)", "arpabet": "CMU ARPABET <phoneme> tags",
             "ipa-words": "IPA for each word (QueryBook's formant voice)"}


class Spoken(str):
    """the clean text, carrying its pronunciation decisions to the engine that will speak it"""
    res = None


def spoken(text, lexicon=None, lang="en"):
    res = resolve(text, lexicon, lang)
    s = Spoken(res["clean"])
    s.res = res
    return s


def mode_for(engine_id, model=""):
    if engine_id == "elevenlabs" and model in ELEVEN_PHONEME_MODELS:
        return "arpabet"
    return ENGINE_MODE.get(engine_id, "respell")


def _cap(src, rep):
    return rep[:1].upper() + rep[1:] if src[:1].isupper() and rep else rep


def render(s, mode, escape=None, between=None):
    """the text for one engine. escape/between: SSML escaping and the pause filter applied to the plain stretches."""
    res = getattr(s, "res", None)
    text = str(s)
    if not res or not res["items"]:
        return between(escape(text)) if mode == "ssml" and escape else text
    out, pos = [], 0
    plain = (lambda t: between(escape(t))) if mode == "ssml" and escape else (lambda t: t)
    for it in res["items"]:
        out.append(plain(text[pos:it["start"]]))
        w = text[it["start"]:it["end"]]
        out.append(_word_for(it, w, mode, escape))
        pos = it["end"]
    out.append(plain(text[pos:]))
    return "".join(out)


def _word_for(it, w, mode, escape=None):
    esc = escape or (lambda t: t)
    if not it.get("forced"):
        return esc(w)
    if it.get("alias"):
        if mode == "ssml":
            return '<sub alias="%s">%s</sub>' % (esc(it["alias"]).replace('"', "&quot;"), esc(w))
        return it["alias"]
    if mode == "ssml" and it.get("ipa"):
        return '<phoneme alphabet="ipa" ph="%s">%s</phoneme>' % (esc(it["ipa"]).replace('"', "&quot;"), esc(w))
    if mode == "arpabet" and it.get("arpa"):
        return '<phoneme alphabet="cmu-arpabet" ph="%s">%s</phoneme>' % (it["arpa"], w)
    if mode == "espeak" and it.get("arpa"):
        return "[[%s]]" % arpa_to_espeak(it["arpa"])
    if mode == "apple" and it.get("arpa"):
        return "[[inpt PHON]]%s[[inpt TEXT]]" % arpa_to_apple(it["arpa"])
    if mode in ("respell", "arpabet", "apple", "espeak") and it.get("respell"):
        return _cap(w, it["respell"])
    return esc(w)


def report(s, engine_id, model=""):
    """what the plan shows before anything is sent: each decision and how this engine will be told"""
    res = getattr(s, "res", None)
    if not res:
        return None
    mode = mode_for(engine_id, model)
    rows = []
    for it in res["items"]:
        told = _word_for(it, it["word"], mode) if it.get("forced") else None
        rows.append({"word": it["word"], "sense": it.get("sense"), "meaning": it.get("gloss"), "ipa": it.get("ipa"), "respell": it.get("respell"),
                     "alias": it.get("alias"), "confidence": it.get("conf"), "reason": it.get("reason"), "source": it.get("source"),
                     "forced": bool(it.get("forced")), "sent_as": told if (told and told != it["word"]) else
                     ("left to the engine (no respelling for this word)" if it.get("forced") else "left to the engine (uncertain — confirm it below)"),
                     "alternatives": it.get("alternatives", [])})
    return {"method": MODE_NAME[mode], "decisions": rows, "uncertain": sum(1 for r in rows if not r["forced"]),
            "text_sent": render(s, mode if mode != "ssml" else "respell") if mode in ("respell", "espeak", "apple", "arpabet") else None}


def word_ipa_overrides(text, lexicon=None, lang="en", pattern=None):
    """for the mouth shapes: {start offset in the clean text: (ipa or None, alias or None, reason)} for each forced decision"""
    res = resolve(text, lexicon, lang)
    return res["clean"], {it["start"]: (it.get("ipa"), it.get("alias"), it["reason"]) for it in res["items"] if it.get("forced")}


# ------------------------------------------------------------------------------------------------ the benchmark (also the self-test)
BENCH = [
    ("I live in Seattle.", "live", "verb"), ("The live concert starts tonight.", "live", "adj"), ("We went live at noon.", "live", "adj"),
    ("They live together in a small flat.", "live", "verb"), ("Watch the live stream on our channel.", "live", "adj"),
    ("Where do you live?", "live", "verb"), ("The band played live.", "live", "adj"), ("Careful, that is a live wire.", "live", "adj"),
    ("Long live the king.", "live", "verb"), ("Cats live longer indoors.", "live", "verb"), ("The show is broadcast live from London.", "live", "adj"),
    ("I want to live near the sea.", "live", "verb"), ("They sell live bait at the dock.", "live", "adj"), ("Is the website live yet?", "live", "adj"),
    ("She lives in Paris.", "lives", "verb"), ("The flood changed their lives.", "lives", "noun"), ("A cat has nine lives.", "lives", "noun"),
    ("He lives alone.", "lives", "verb"), ("Many lives were saved.", "lives", "noun"), ("Who lives here?", "lives", "verb"),
    ("I read every night.", "read", "present"), ("Yesterday I read the whole book.", "read", "past"), ("I have read that article.", "read", "past"),
    ("Please read the instructions.", "read", "present"), ("She read the letter aloud.", "read", "past"), ("I will read it tomorrow.", "read", "present"),
    ("The book was read by millions.", "read", "past"), ("Do you read French?", "read", "present"), ("He read it twice before signing.", "read", "past"),
    ("Read the first chapter.", "read", "present"), ("They had already read the report.", "read", "past"), ("I like to read on trains.", "read", "present"),
    ("Last week we read three poems.", "read", "past"), ("It is widely read in schools.", "read", "past"), ("Can you read this?", "read", "present"),
    ("I usually read before bed.", "read", "present"), ("She has never read it.", "read", "past"), ("We read the news every morning.", "read", "present"),
    ("Lead pipes were banned decades ago.", "lead", "metal"), ("She will lead the team.", "lead", "verb"), ("The paint contains lead.", "lead", "metal"),
    ("These roads lead to Rome.", "lead", "verb"), ("He took the lead in the second half.", "lead", "verb"), ("Lead poisoning is dangerous.", "lead", "metal"),
    ("Who is the lead singer?", "lead", "verb"), ("The atomic number of lead is 82.", "lead", "metal"), ("Follow my lead.", "lead", "verb"),
    ("The wind is strong today.", "wind", "air"), ("Wind the clock every Sunday.", "wind", "turn"), ("Don't forget to wind your watch.", "wind", "turn"),
    ("Wind power is growing fast.", "wind", "air"), ("The wind blew the door shut.", "wind", "air"), ("We need to wind down before bed.", "wind", "turn"),
    ("The road winds through the hills.", "winds", "turn"), ("Strong winds hit the coast.", "winds", "air"),
    ("The wound healed slowly.", "wound", "injury"), ("She wound the rope around the post.", "wound", "turned"), ("He has a deep wound.", "wound", "injury"),
    ("The path wound up the mountain.", "wound", "turned"), ("They cleaned the wound carefully.", "wound", "injury"),
    ("A tear ran down her cheek.", "tear", "cry"), ("Don't tear the paper.", "tear", "rip"), ("There is a tear in my shirt.", "tear", "rip"),
    ("Wear and tear is expected.", "tear", "rip"), ("He shed a tear of joy.", "tear", "cry"), ("Tear it up and start again.", "tear", "rip"),
    ("She burst into tears.", "tears", "cry"), ("He tears the tickets in half.", "tears", "rip"), ("Tears of joy filled his eyes.", "tears", "cry"),
    ("The actors bow at the end.", "bow", "bend"), ("She tied a red bow in her hair.", "bow", "knot"), ("He drew his bow and fired an arrow.", "bow", "knot"),
    ("The bow of the ship cut through the waves.", "bow", "bend"), ("Take a bow!", "bow", "bend"), ("The violin bow needs new hair.", "bow", "knot"),
    ("We sat in the front row.", "row", "line"), ("They row the boat across the lake.", "row", "line"), ("The couple had a blazing row.", "row", "quarrel"),
    ("Add a row to the table.", "row", "line"), ("A diplomatic row erupted over the visit.", "row", "quarrel"),
    ("He plays bass in a jazz band.", "bass", "music"), ("We caught a huge bass in the lake.", "bass", "fish"), ("Turn up the bass.", "bass", "music"),
    ("Sea bass is on the menu.", "bass", "fish"), ("The bass guitar is out of tune.", "bass", "music"), ("Largemouth bass like warm water.", "bass", "fish"),
    ("A white dove flew over the square.", "dove", "bird"), ("She dove into the pool.", "dove", "dived"), ("He dove for the ball.", "dove", "dived"),
    ("The dove is a symbol of peace.", "dove", "bird"),
    ("What does it mean?", "does", "verb"), ("The does grazed with their fawns.", "does", "deer"), ("She does her homework.", "does", "verb"),
    ("Farmers sow the seeds in spring.", "sow", "plant"), ("The sow fed her piglets.", "sow", "pig"),
    ("Wait a minute.", "minute", "time"), ("There were minute traces of gold.", "minute", "tiny"), ("Every minute counts.", "minute", "time"),
    ("The minute details matter.", "minute", "tiny"),
    ("The Sahara is the largest hot desert.", "desert", "noun"), ("Soldiers who desert face trial.", "desert", "verb"), ("Don't desert us now.", "desert", "verb"),
    ("He got his just deserts.", "deserts", "verb"),
    ("She bought a birthday present.", "present", "noun"), ("We will present the results tomorrow.", "present", "verb"), ("At present we have no plans.", "present", "noun"),
    ("Please present your ticket.", "present", "verb"), ("Everyone was present at the meeting.", "present", "noun"), ("The present situation is difficult.", "present", "noun"),
    ("She presents the evening news.", "presents", "verb"), ("The children opened their presents.", "presents", "noun"),
    ("She broke the world record.", "record", "noun"), ("Please record the meeting.", "record", "verb"), ("He bought a new record player.", "record", "noun"),
    ("They record every call.", "record", "verb"), ("It was a record high.", "record", "noun"), ("I want to record an album.", "record", "verb"),
    ("Keep your medical records safe.", "records", "noun"), ("The camera records in 4K.", "records", "verb"),
    ("I object to that remark.", "object", "verb"), ("The object is made of glass.", "object", "noun"), ("He picked up a strange object.", "object", "noun"),
    ("The project is due on Friday.", "project", "noun"), ("We project growth of five percent.", "project", "verb"), ("She is the project manager.", "project", "noun"),
    ("Buy fresh produce at the market.", "produce", "noun"), ("Bees produce honey.", "produce", "verb"),
    ("You need a building permit.", "permit", "noun"), ("The rules do not permit smoking.", "permit", "verb"),
    ("His conduct was excellent.", "conduct", "noun"), ("We conduct interviews every week.", "conduct", "verb"),
    ("Sign the contract today.", "contract", "noun"), ("Metals contract when cooled.", "contract", "verb"),
    ("The content of the course is online.", "content", "adj"), ("She seemed content with the result.", "content", "verb"),
    ("Please close the door.", "close", "verb"), ("We live close to the station.", "close", "adj"), ("She is a close friend.", "close", "adj"),
    ("The shops close at six.", "close", "verb"), ("That was too close.", "close", "adj"),
    ("What is the use of that?", "use", "noun"), ("You can use my pen.", "use", "verb"), ("This tool is in daily use.", "use", "noun"), ("I use it every day.", "use", "verb"),
    ("I used to live there.", "used", "accustomed"), ("She used a knife.", "used", "employed"), ("He is used to the cold.", "used", "accustomed"),
    ("This tool is used to cut glass.", "used", "employed"), ("We got used to it.", "used", "accustomed"),
    ("The house is old.", "house", "noun"), ("The museum will house the collection.", "house", "verb"),
    ("Excuse me, please.", "excuse", "verb"), ("That is a poor excuse.", "excuse", "noun"),
    ("The refuse collection is on Monday.", "refuse", "noun"), ("I refuse to answer.", "refuse", "verb"),
    ("Give me a rough estimate.", "estimate", "noun"), ("We estimate the cost at ten dollars.", "estimate", "verb"),
    ("She will graduate in June.", "graduate", "verb"), ("He is a graduate student.", "graduate", "noun"),
    ("Keep them in separate rooms.", "separate", "adj"), ("Separate the eggs carefully.", "separate", "verb"),
    ("The input is invalid.", "invalid", "adj"), ("Enter a valid password, not an invalid password.", "invalid", "adj"),
    ("He speaks Polish fluently.", "polish", "poland"), ("Polish your shoes before the interview.", "polish", "shine"), ("Use a little polish on the table.", "polish", "shine"),
    ("We met in August.", "august", "month"), ("It was an august assembly of scholars.", "august", "noble"),
    ("We spent a week in Nice.", "nice", "city"), ("What a nice day.", "nice", "pleasant"),
    ("Send me your resume.", "resume", "cv"), ("We will resume after lunch.", "resume", "verb"),
    ("He is a learned scholar.", "learned", "scholarly"), ("She learned French quickly.", "learned", "past"),
    ("The graph has two axes.", "axes", "axis"), ("The lumberjacks sharpened their axes.", "axes", "axe"),
    ("He is a rebel at heart.", "rebel", "noun"), ("They rebel against every rule.", "rebel", "verb"),
    ("The police arrested the suspect.", "suspect", "noun"), ("I suspect he knows.", "suspect", "verb"),
    ("The subject of the email is blank.", "subject", "noun"), ("Don't subject them to that.", "subject", "verb"),
    ("Please address the envelope.", "address", "verb"), ("What is your email address?", "address", "noun"),
    ("There was a big increase in sales.", "increase", "noun"), ("Prices will increase next year.", "increase", "verb"),
    ("The team made good progress.", "progress", "noun"), ("Patients progress at different rates.", "progress", "verb"),
    ("We need to combat climate change.", "combat", "verb"), ("He saw combat in the war.", "combat", "noun"),
    ("Please insert your card.", "insert", "verb"), ("The magazine had a glossy insert.", "insert", "noun"),
    ("It was a stunning upset.", "upset", "noun"), ("Don't upset your mother.", "upset", "verb"),
]


# written after the rules were tuned. First run (before any change): 65 of 70 right (92.9%), 61 of 62 forced decisions
# right (98.4%). Two rules were then corrected from its failures ("have you read", a noun "row"), so it is no longer
# unseen — new sentences are needed for the next honest figure.
HELDOUT = [
    ("My grandparents live on a farm.", "live", "verb"), ("Tickets for the live final sold out.", "live", "adj"), ("You only live once.", "live", "verb"),
    ("The match will be shown live on TV.", "live", "adj"), ("Fish cannot live out of water.", "live", "verb"), ("The live audience cheered.", "live", "adj"),
    ("How long did they live there?", "live", "verb"), ("Keep away from live electrical cables.", "live", "adj"),
    ("He lives for his music.", "lives", "verb"), ("Doctors save lives every day.", "lives", "noun"), ("The war cost thousands of lives.", "lives", "noun"),
    ("I read your message last night.", "read", "past"), ("Kids should read more books.", "read", "present"), ("Have you read the news?", "read", "past"),
    ("She can read music.", "read", "present"), ("The report was read aloud in court.", "read", "past"), ("Every child must learn to read.", "read", "present"),
    ("We read about it in the paper.", "read", "past"), ("They read the terms before signing.", "read", "present"),
    ("Lead is a soft, heavy metal.", "lead", "metal"), ("The guide will lead us up the mountain.", "lead", "verb"), ("Old houses may have lead paint.", "lead", "metal"),
    ("Our team is in the lead.", "lead", "verb"),
    ("A cold wind blew from the north.", "wind", "air"), ("Wind the cable around the spool.", "wind", "turn"), ("The wind was howling all night.", "wind", "air"),
    ("He suffered a wound to the leg.", "wound", "injury"), ("The bandage was wound tightly.", "wound", "turned"),
    ("Please don't tear the label.", "tear", "rip"), ("A single tear rolled down his face.", "tear", "cry"), ("Her eyes filled with tears.", "tears", "cry"),
    ("The musicians bow to the audience.", "bow", "bend"), ("She wore a pink bow.", "bow", "knot"),
    ("We planted the trees in a row.", "row", "line"), ("They had a row about money.", "row", "quarrel"),
    ("The bass was too loud at the concert.", "bass", "music"), ("He went fishing for bass.", "bass", "fish"),
    ("The pigeon and the dove look alike.", "dove", "bird"), ("The goalkeeper dove to his left.", "dove", "dived"),
    ("It took a minute to load.", "minute", "time"), ("The microscope showed minute details.", "minute", "tiny"),
    ("The museum has a record of every visitor.", "record", "noun"), ("You should record your expenses.", "record", "verb"),
    ("Thank you for the lovely present.", "present", "noun"), ("The students will present their findings.", "present", "verb"),
    ("The new project starts next month.", "project", "noun"), ("Many object to the new rules.", "object", "verb"),
    ("Close the window, it's cold.", "close", "verb"), ("The station is close by.", "close", "adj"), ("The results were very close.", "close", "adj"),
    ("There is no use complaining.", "use", "noun"), ("We use solar panels.", "use", "verb"),
    ("They used to play tennis.", "used", "accustomed"), ("He used the money wisely.", "used", "employed"),
    ("Wait a minute, please.", "minute", "time"), ("The castle walls house a museum.", "house", "verb"),
    ("I refuse to give up.", "refuse", "verb"), ("The city collects refuse weekly.", "refuse", "noun"),
    ("We met in Nice last summer.", "nice", "city"), ("Polish the silver before dinner.", "polish", "shine"),
    ("Please resume your work.", "resume", "verb"), ("Update your resume before applying.", "resume", "cv"),
    ("The desert is cold at night.", "desert", "noun"), ("Prices increase every winter.", "increase", "verb"),
    ("The contract was signed yesterday.", "contract", "noun"), ("Copper wires conduct electricity.", "conduct", "verb"),
    ("She is content to wait.", "content", "verb"), ("Check the content before posting.", "content", "adj"),
    ("The suspect fled the scene.", "suspect", "noun"), ("Teachers address the class each morning.", "address", "verb"),
]


def benchmark(lexicon=None, sentences=None):
    """how often the resolver gets the benchmark sentences right — forced decisions and every decision (default included)"""
    lex = lexicon if lexicon is not None else Lexicon(None)
    rows, forced_ok, forced, all_ok = [], 0, 0, 0
    for text, word, want in (sentences or BENCH):
        res = resolve(text, lex)
        it = next((x for x in res["items"] if x["word"].lower() == word), None)
        got = it["sense"] if it else None
        ok = got == want
        all_ok += ok
        if it and it.get("forced"):
            forced += 1
            forced_ok += ok
        rows.append({"text": text, "word": word, "want": want, "got": got, "conf": it and it["conf"], "forced": bool(it and it.get("forced")),
                     "ok": ok, "reason": it and it["reason"]})
    n = len(sentences or BENCH)
    return {"sentences": n, "correct": all_ok, "accuracy": round(all_ok / n, 4), "forced": forced, "forced_correct": forced_ok,
            "forced_accuracy": round(forced_ok / forced, 4) if forced else None, "left_to_engine": n - forced,
            "wrong": [r for r in rows if not r["ok"]], "rows": rows}


def self_test():
    out = []

    def check(name, ok, detail=""):
        out.append((name, bool(ok), detail))
    b = benchmark()
    check("benchmark: %d heteronym sentences, %d%% right overall, %s%% of forced decisions right, %d left to the engine"
          % (b["sentences"], round(100 * b["accuracy"]), round(100 * (b["forced_accuracy"] or 0)), b["left_to_engine"]),
          b["accuracy"] >= 0.9 and (b["forced_accuracy"] or 0) >= 0.95, [(w["text"], w["want"], w["got"], w["reason"]) for w in b["wrong"]][:12])
    check("ARPABET → IPA with stress", arpa_to_ipa("R IH0 K AO1 R D") == "ɹɪˈkɔɹd" and arpa_to_ipa("R EH1 K ER0 D") == "ˈɹɛkɚd"
          and arpa_to_ipa("L IH1 V") == "ˈlɪv" and arpa_to_ipa("P R AA1 JH EH0 K T") == "ˈpɹɑdʒɛkt", [arpa_to_ipa("R IH0 K AO1 R D")])
    check("ARPABET → espeak-ng and macOS phonemes", arpa_to_espeak("L AY1 V") == "l'aIv" and arpa_to_apple("L IH1 V") == "l1IHv"
          and arpa_to_espeak("R IH0 K AO1 R D") == "rIk'O:rd")
    check("IPA → ARPABET (lexicon entries given in IPA)", ipa_to_arpa("ˈlɪv") == "L IH1 V" and ipa_to_arpa("/ˈsiːkwəl/") == "S IY1 K W AH0 L", ipa_to_arpa("/ˈsiːkwəl/"))
    s = spoken("I live in Seattle and love live music.")
    check("SSML: phoneme tags only on the heteronyms, text escaped", render(s, "ssml", lambda t: t.replace("&", "&amp;"), lambda t: t) ==
          'I <phoneme alphabet="ipa" ph="ˈlɪv">live</phoneme> in Seattle and love <phoneme alphabet="ipa" ph="ˈlaɪv">live</phoneme> music.',
          render(s, "ssml", lambda t: t, lambda t: t))
    check("text-only engines get respellings, espeak its own phonemes", render(s, "respell") == "I liv in Seattle and love lyve music."
          and render(s, "espeak") == "I [[l'Iv]] in Seattle and love [[l'aIv]] music.", render(s, "respell"))
    s2 = spoken("Yesterday I {read|present} it, then {SQL|sequel} and {live|/laɪv/}.")
    check("inline marks win and are removed from the text", str(s2) == "Yesterday I read it, then SQL and live." and
          [i["sense"] for i in s2.res["items"]] == ["present", "alias", "ipa"] and render(s2, "respell") == "Yesterday I reed it, then sequel and lyve.", render(s2, "respell"))
    check("SSML alias for words said differently", '<sub alias="sequel">SQL</sub>' in render(s2, "ssml", lambda t: t, lambda t: t))
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        lx = Lexicon(tmp)
        lx.put({"term": "Qlik", "ipa": "klɪk", "note": "the company"})
        lx.put({"term": "SQL", "alias": "sequel"})
        r = resolve("We moved from Qlik to SQL databases; qlik is fast.", lx)
        check("lexicon: terms matched as whole words, any case; IPA converted for every engine",
              [(i["word"], i["source"]) for i in r["items"]] == [("Qlik", "lexicon"), ("SQL", "lexicon"), ("qlik", "lexicon")]
              and r["items"][0]["arpa"] == "K L IH1 K", r["items"])
        lx.remove("Qlik")
        check("lexicon: entries removed", [e["term"] for e in lx.entries()] == ["SQL"])
    u = spoken("I think we should read it.")
    check("a clear cue is forced on the engine, with its reason", all(i["forced"] for i in u.res["items"]) and "should" in u.res["items"][0]["reason"])
    amb = resolve("I read it.")["items"][0]
    check("an unclear case is flagged and left to the engine", not amb["forced"] and amb["ambiguous"], amb)
    check("deterministic", resolve("The live show was read live.") == resolve("The live show was read live."))
    return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "bench":
        b = benchmark()
        for r in b["rows"]:
            if not r["ok"]:
                print("WRONG", r)
        print({k: v for k, v in b.items() if k not in ("rows", "wrong")})
    else:
        res = self_test()
        for n, ok, d in res:
            print(("  [OK]   " if ok else "  [FAIL] ") + n + ("" if ok else "  — %s" % (d,)))
        print("\n  %d of %d checks passed" % (sum(1 for r in res if r[1]), len(res)))
