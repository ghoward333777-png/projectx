#!/usr/bin/env python3
"""Generate clean, labeled patent-style drawings (SVG) for the LEL provisional,
plus a Brief Description of the Drawings and a Reference Numerals key. Black line
art on white, each figure on its own sheet, every element carries a reference
numeral consistent with the specification."""
import html

# ---- SVG primitives (patent style: white ground, black 1.6px line, black text) ----
def esc(s): return html.escape(str(s))

def svg_open(w, h):
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:100%;height:auto;'
            f'background:#fff;border:1px solid #000" xmlns="http://www.w3.org/2000/svg">'
            f'<defs><marker id="ah" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" '
            f'markerUnits="strokeWidth"><path d="M0,0 L8,3 L0,6 z" fill="#000"/></marker></defs>'
            f'<rect x="0" y="0" width="{w}" height="{h}" fill="#fff"/>')

def box(x, y, w, h, lines, ref, dashed=False, r=4):
    d = ' stroke-dasharray="6 4"' if dashed else ''
    o = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="#fff" stroke="#000" stroke-width="1.6"{d}/>'
    n = len(lines)
    lh = 15
    ty = y + h/2 - (n-1)*lh/2 + 4
    for i, ln in enumerate(lines):
        weight = 'font-weight="700"' if i == 0 else ''
        o += (f'<text x="{x+w/2}" y="{ty+i*lh}" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" '
              f'font-size="12.5" fill="#000" {weight}>{esc(ln)}</text>')
    if ref is not None:
        # reference numeral OUTSIDE the box (just above the top-right corner) with a short
        # leader tick, so it never overlaps the element label — patent-drawing convention.
        o += f'<line x1="{x+w}" y1="{y}" x2="{x+w+10}" y2="{y-12}" stroke="#000" stroke-width="1"/>'
        o += (f'<text x="{x+w+12}" y="{y-9}" text-anchor="start" font-family="Helvetica,Arial,sans-serif" '
              f'font-size="12" font-weight="700" fill="#000">{esc(ref)}</text>')
    return o

def label(x, y, text, size=12, anchor="start", bold=False):
    b = 'font-weight="700"' if bold else ''
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="Helvetica,Arial,sans-serif" '
            f'font-size="{size}" fill="#000" {b}>{esc(text)}</text>')

def arrow(x1, y1, x2, y2):
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#000" stroke-width="1.6" marker-end="url(#ah)"/>'

def line(x1, y1, x2, y2, dashed=False):
    d = ' stroke-dasharray="5 4"' if dashed else ''
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#000" stroke-width="1.4"{d}/>'

def numeral(x, y, ref):
    return label(x, y, ref, size=12, bold=True)


FIGS = []   # (num, title, svg)

# ===================== FIG. 1 — System architecture =====================
w, h = 720, 560
s = svg_open(w, h)
s += box(280, 20, 160, 46, ["Sub-Language", "Priming Layer (SLPL)"], "110")
s += arrow(360, 66, 360, 96)
s += box(255, 96, 210, 60, ["Language Expression", "Layer (LEL)", "learned parameters"], "120")
# transition gate to the right governing LEL
s += box(510, 100, 170, 52, ["Transition Gate", "(one-way, 4 thresholds)"], "130")
s += line(465, 126, 510, 126); s += arrow(510, 126, 508, 126)
s += arrow(595, 152, 595, 182)
s += box(510, 182, 170, 50, ["Phase Two: semantic-", "communicative learning"], "140")
s += line(595, 232, 595, 250); s += line(595, 250, 360, 250); s += arrow(360, 250, 360, 254)
# from LEL down to three outputs
s += arrow(360, 156, 360, 190)
s += box(255, 190, 210, 46, ["Developmental control", "(Phase 1 → gate → Phase 2)"], None, dashed=True)
s += arrow(360, 236, 360, 268)
# branch: multilingual, speech, co-grounding
s += box(40, 300, 180, 56, ["Multilingual Delta", "Acquisition Module"], "150")
s += box(270, 300, 180, 56, ["Speech Output", "Pipeline"], "160")
s += box(500, 300, 180, 56, ["Co-Grounding", "Interface"], "170")
s += line(360, 268, 360, 284); s += line(130, 284, 590, 284)
s += arrow(130, 284, 130, 300); s += arrow(360, 284, 360, 300); s += arrow(590, 284, 590, 300)
s += label(270, 296, "speech out", 11, "middle")
# co-grounding to FQL/UFCS chain
s += arrow(590, 356, 590, 386)
s += box(500, 386, 180, 40, ["Federated Query", "Language (FQL)"], "180")
s += arrow(590, 426, 590, 452)
s += box(500, 452, 180, 40, ["Universal Federated", "Connectivity Sys (UFCS)"], "190")
s += arrow(590, 492, 590, 518)
s += box(500, 518, 180, 34, ["Federated data sources"], "195")
# speech waveform out
s += arrow(360, 356, 360, 392)
s += box(285, 392, 150, 34, ["Natural speech"], "165")
s += '</svg>'
FIGS.append((1, "QueryBook LEL — Overall System Architecture", s))

# ===================== FIG. 2 — Sub-Language Priming Layer =====================
w, h = 720, 500
s = svg_open(w, h)
s += box(250, 16, 220, 40, ["Sub-Language Priming Layer", "(SLPL)"], "200")
comps = [
    ("210", ["Acoustic phonetic", "processing"], "211", "feature embedding"),
    ("220", ["Phonics / phonemic", "awareness"], "221", "phoneme-boundary segmenter"),
    ("230", ["Communication-science", "foundations"], "231", "communicative-salience weight"),
    ("240", ["Prosody & rhythm", "processing"], "241", "prosodic contour vector"),
    ("250", ["Information-theoretic", "grounding"], "251", "information weighting"),
    ("260", ["Neurolinguistic", "chunking"], "261", "chunk segments"),
]
s += label(360, 72, "no semantics extracted — structural / pre-semantic only", 11, "middle", True)
y0 = 96
for i, (ref, lines, oref, oname) in enumerate(comps):
    col = i % 2
    row = i // 2
    x = 40 + col * 360
    y = y0 + row * 118
    s += box(x, y, 200, 46, lines, ref)
    s += arrow(x + 100, y + 46, x + 100, y + 66)
    s += box(x, y + 66, 240, 30, [oname], oref)
# multimedia input
s += box(40, y0 + 3*118 - 6, 640, 30, ["Multimedia input (film, TV, dialogue) — licensed / lawful only"], "270")
s += '</svg>'
FIGS.append((2, "Sub-Language Priming Layer (SLPL) and Its Measurable Outputs", s))

# ===================== FIG. 3 — Developmental sequence + Transition Gate =====================
w, h = 720, 470
s = svg_open(w, h)
s += box(250, 16, 220, 34, ["Developmental Learning Sequence"], "300")
s += box(60, 74, 260, 120, ["Phase One:", "Structural-Acoustic"], "310")
s += box(80, 108, 220, 24, ["Sound discrimination"], "311")
s += box(80, 136, 220, 24, ["Syllabic segmentation"], "312")
s += box(80, 164, 220, 24, ["Word-as-acoustic-object"], "313")
s += label(190, 205, "semantics SUPPRESSED", 11, "middle", True); s += numeral(305, 205, "314")
# gate
s += box(360, 74, 300, 200, ["Transition Gate (one-way)"], "320")
gates = [("Phonemic inventory completeness  ≥ τ1", "321"),
         ("Lexical stability  ≥ τ2", "322"),
         ("Co-occurrence density  ≥ τ3", "323"),
         ("Pattern saturation  < ε over window W", "324")]
for i, (t, r) in enumerate(gates):
    yy = 108 + i*36
    s += box(378, yy, 240, 26, [t], r)
s += label(510, 262, "opens only when all four are met", 10.5, "middle")
s += arrow(320, 134, 360, 134)
# phase two
s += box(230, 320, 260, 120, ["Phase Two:", "Semantic-Communicative"], "330")
s += box(250, 354, 220, 24, ["Word-to-referent grounding"], "331")
s += box(250, 382, 220, 24, ["Communicative discovery"], "332")
s += box(250, 410, 220, 24, ["Emergent grammar / syntax"], "333")
s += line(510, 274, 510, 300); s += line(510, 300, 360, 300); s += arrow(360, 300, 360, 320)
s += '</svg>'
FIGS.append((3, "Developmental Learning Sequence and One-Way Transition Gate", s))

# ===================== FIG. 4 — Multilingual Delta Acquisition =====================
w, h = 740, 440
s = svg_open(w, h)
s += box(260, 16, 220, 34, ["Delta Acquisition Model"], "400")
s += box(40, 74, 250, 170, [], "410")
s += label(165, 94, "L1 foundation (reused)", 12.5, "middle", True)
for i, t in enumerate(["Phonemic discrimination", "Prosodic sensitivity", "Morphological awareness",
                       "Communicative understanding", "Grammatical meta-knowledge", "Semantic inventory"]):
    s += label(56, 120 + i*20, "• " + t, 11)
s += arrow(290, 159, 340, 159)
s += box(340, 100, 200, 50, ["L2 delta detector", "(novel vs. shared)"], "420")
s += arrow(440, 150, 440, 176)
s += box(340, 176, 200, 54, ["Targeted training:", "novel phonemes / grammar /", "idioms / prosody"], "430")
s += arrow(540, 125, 590, 125)
s += box(560, 96, 140, 60, ["Multilingual", "semantic alignment", "(bridge L2→L1)"], "440")
s += box(40, 300, 660, 100, [], "450")
s += label(370, 320, "Acceleration flywheel", 12.5, "middle", True)
s += box(60, 344, 300, 34, ["Negative-transfer detection & retraining"], "451")
s += label(400, 362, "Each further language generally needs a smaller", 11)
s += label(400, 378, "delta (directional, not strictly monotonic).", 11)
s += line(440, 230, 440, 300)
s += '</svg>'
FIGS.append((4, "Multilingual Transfer — Delta Acquisition and Acceleration Flywheel", s))

# ===================== FIG. 5 — Speech Output Pipeline =====================
w, h = 720, 470
s = svg_open(w, h)
s += box(250, 16, 220, 34, ["Speech Output Pipeline"], "500")
stages = [("510", "Lexical selection (no dictionary lookup)"),
          ("520", "Grapheme-to-phoneme conversion (context-sensitive)"),
          ("530", "Coarticulation modeling"),
          ("540", "Prosody generation (syllable/word/phrase/sentence/discourse)"),
          ("550", "Register & affect calibration"),
          ("560", "Self-monitoring feedback loop (naturalness metric)"),
          ("570", "Neural vocoder rendering")]
y = 70
for r, t in stages:
    s += box(120, y, 480, 34, [t], r)
    if y + 34 < 70 + 7*46:
        s += arrow(360, y + 34, 360, y + 46)
    y += 46
s += box(255, y, 210, 34, ["Natural speech waveform"], "580")
s += '</svg>'
FIGS.append((5, "Speech Output Pipeline (Seven Learned Stages)", s))

# ===================== FIG. 6 — Co-grounded integration =====================
w, h = 740, 360
s = svg_open(w, h)
s += box(250, 16, 220, 34, ["Co-Grounded Integration"], "600")
s += box(40, 80, 150, 50, ["Natural-language", "input (any language)"], "610")
s += arrow(190, 105, 226, 105)
s += box(226, 80, 150, 50, ["LEL analysis", "(meaning)"], "620")
s += arrow(376, 105, 412, 105)
s += box(412, 80, 130, 50, ["FQL operations"], "630")
s += arrow(542, 105, 578, 105)
s += box(560, 80, 140, 50, ["UFCS execution"], "640")
s += arrow(630, 130, 630, 156)
s += box(560, 156, 140, 40, ["Federated sources"], "650")
s += arrow(630, 196, 630, 220); s += line(630, 220, 470, 220)
s += box(360, 220, 220, 40, ["Results"], "660")
s += arrow(360, 240, 226, 240); s += line(226, 240, 115, 240); s += line(115, 240, 115, 130)
s += arrow(115, 130, 115, 130)
s += box(40, 220, 260, 40, ["Render to NL / speech", "in the input language"], "670")
s += label(360, 300, "language-agnostic: any input language → same FQL representation", 11, "middle", True)
s += numeral(600, 300, "680")
s += '</svg>'
FIGS.append((6, "Co-Grounded Integration with FQL and UFCS", s))

# ===================== FIG. 7 — Reduced-to-practice prototype =====================
w, h = 740, 500
s = svg_open(w, h)
s += box(210, 14, 320, 40, ["PROTOTYPE EMBODIMENT (Section VII)", "QueryBook Language Lab — Phases One & Two"], "700")
s += box(40, 78, 200, 60, ["Corpus source:", "bundled corpus / user", "text / fetched URL"], "710")
s += arrow(240, 108, 276, 108)
s += box(276, 78, 180, 60, ["Phase-One structural", "agent (scheduler,", "24×7)"], "720")
s += arrow(456, 108, 492, 108)
s += box(492, 70, 200, 150, [], "730")
s += label(592, 90, "Structural analyzer", 12.5, "middle", True)
for i, (t, r) in enumerate([("Grapheme inventory", "731"), ("Rule-seeded G2P", "732"),
                            ("Syllabifier", "733"), ("Lexical stability", "734"),
                            ("Co-occurrence density", "735"), ("Prosody proxy", "736")]):
    s += label(505, 112 + i*18, "• " + t + "  (" + r + ")", 10.5)
s += arrow(392, 138, 392, 250)
s += box(276, 250, 180, 56, ["Fact Unit store", "(content-addressed,", "deduped, provenance)"], "740")
s += arrow(592, 220, 592, 250)
s += box(492, 250, 200, 56, ["Transition Gate metrics", "(4) → one-way latch"], "750")
s += numeral(468, 300, "751")
s += line(492, 278, 456, 278); s += arrow(456, 278, 456, 278)
s += box(40, 356, 660, 128, [], "760")
s += label(370, 378, "Phase agents on shared agent manager", 12.5, "middle", True)
s += box(60, 408, 150, 60, ["Phase 1", "structural", "IMPLEMENTED"], "761")
s += box(230, 408, 150, 60, ["Phase 2 semantic", "grounding (dictionary", "+ store) IMPLEMENTED"], "762")
s += box(400, 408, 150, 60, ["Phase 3 multilingual", "delta —", "declines (spec-only)"], "763")
s += box(560, 408, 120, 60, ["Phase 4 speech", "— declines", "(spec-only)"], "764")
s += '</svg>'
FIGS.append((7, "Reduced-to-Practice Embodiment — Language Lab Phases One and Two Prototype", s))

# ===================== FIG. 8 — Deterministic Phase-Two semantic grounding =====================
w, h = 720, 624
s = svg_open(w, h)
s += box(150, 28, 420, 40, ["DETERMINISTIC PHASE-TWO SEMANTIC GROUNDING",
                            "(prototype embodiment — no LLM)"], "800")
# central spine: vocabulary -> grounder
s += box(275, 88, 170, 52, ["Phase-One vocabulary", "(learned words,", "by frequency)"], "810")
s += arrow(360, 140, 360, 160)
s += box(275, 160, 170, 58, ["Deterministic", "grounder", "(per word)"], "820")
# fork to two auditable meaning sources
s += arrow(300, 218, 200, 280)
s += arrow(420, 218, 560, 280)
s += box(40, 280, 240, 60, ["Public-domain dictionary", "(Webster's 1913, bundled —", "offline, no network)"], "830")
s += box(440, 280, 240, 60, ["Self-grounding:", "UFCS store lookup", "(verified Fact Units)"], "840")
# labeled Fact-Unit outputs under each source
s += label(46, 360, 'writes  english word "w" · means · <definition>', 10)
s += label(46, 375, 'trust 0.9 · source = dictionary', 10); s += numeral(250, 375, "831")
s += label(446, 360, 'writes  english word "w" · grounded_by_fact', 10)
s += label(446, 375, '· <subject predicate object>', 10); s += numeral(650, 375, "841")
# join into the Fact Unit store
s += arrow(160, 388, 300, 430)
s += arrow(560, 388, 420, 430)
s += box(245, 430, 230, 60, ["Fact Unit store", "(content-addressed, deduped,", "provenance — domain 'language')"], "850")
# excluded LLM path + future suggestor gate (both dashed = not in the deterministic path)
s += box(40, 520, 320, 74, ["LLM meaning source — EXCLUDED", "a live API check proves the link works,",
                            "not that a meaning is TRUE"], "860", dashed=True)
s += box(380, 520, 300, 74, ["Optional 'suggestor' (future):", "LLM proposes; ACCEPTED only if it",
                             "agrees with the bundled dictionary"], "870", dashed=True)
s += '</svg>'
FIGS.append((8, "Deterministic Phase-Two Semantic Grounding — Dictionary and Store (No LLM)", s))

# ===================== FIG. 9 — Advanced multilingual pronunciation + self-contained speech =====================
w, h = 745, 720
s = svg_open(w, h)
s += box(120, 16, 480, 42, ["ADVANCED MULTILINGUAL PRONUNCIATION &",
                            "SELF-CONTAINED SPEECH (prototype — no LLM)"], "900")
# input + selector
s += box(285, 72, 150, 44, ["Word / phrase", "+ language"], "910")
s += arrow(360, 116, 360, 138)
s += box(265, 138, 190, 48, ["Pronunciation", "preference ladder"], "920")
# three parallel paths out of the selector
s += arrow(300, 186, 130, 224); s += label(150, 214, "open-source present", 9)
s += arrow(360, 186, 360, 224); s += label(368, 214, "fallback", 9)
s += arrow(420, 186, 590, 224); s += label(545, 214, "neither", 9)
s += box(30, 224, 205, 54, ["Bundled open-source", "phonemizer", "(most accurate)"], "930")
s += box(258, 224, 205, 54, ["Rule-seeded G2P tables", "per language (es/fr/de/", "it/pt/nl/sv; longest-match)"], "940")
s += box(486, 224, 205, 54, ["No phonemizer and", "no table → explicit null", "(NOT fabricated)"], "960")
s += arrow(132, 278, 132, 300); s += box(30, 300, 205, 36, ["IPA transcription"], "931")
s += arrow(360, 278, 360, 300); s += box(258, 300, 205, 36, ["Approximate IPA (offline)"], "941")
s += box(30, 352, 205, 46, ["Call cache (memoized) +", "timeout / bounded log", "(never blocks UI)"], "932", dashed=True)
s += numeral(225, 372, "933")
# merge to syllable/stress derivation
s += arrow(132, 336, 300, 420); s += arrow(360, 336, 360, 420)
s += box(255, 420, 210, 48, ["Syllable count + primary", "stress (IPA nuclei / marks)"], "950")
# phrase-level transcription consistency
s += box(486, 420, 205, 48, ["Phrase-level single-call", "transcription"], "970")
s += arrow(588, 468, 588, 490)
s += box(470, 490, 230, 42, ["Displayed IPA == synthesized audio"], "971")
# self-contained speech band
s += line(30, 552, 690, 552)
s += label(30, 548, "SELF-CONTAINED SPEECH OUTPUT", 11, bold=True)
s += box(30, 562, 320, 140, ["Self-contained application bundle"], "980")
s += box(45, 606, 92, 80, ["open-source", "speech", "engine"], "981")
s += box(147, 606, 92, 80, ["runtime", "support", "libraries"], "982")
s += box(249, 606, 86, 80, ["phoneme", "data"], "983")
s += box(370, 562, 320, 140, ["Engine-selection ladder (per OS / language)"], "984")
s += box(385, 606, 95, 80, ["OS built-in", "voice service"], "985")
s += box(488, 606, 95, 80, ["culture-", "matched OS", "voice"], "986")
s += box(591, 606, 90, 80, ["honest", "refusal — no", "fabricated", "audio"], "987")
s += arrow(360, 532, 360, 562)  # from derivation/consistency into speech band
s += '</svg>'
FIGS.append((9, "Advanced Multilingual Pronunciation and Self-Contained Speech (No LLM)", s))

# ===================== FIG. 10 — Permanent pronunciation/speech QC battery =====================
w, h = 720, 500
s = svg_open(w, h)
s += box(150, 18, 420, 42, ["PERMANENT PRONUNCIATION / SPEECH QUALITY CONTROL",
                            "(deterministic, local, no LLM)"], "995")
s += arrow(360, 60, 360, 82)
s += box(210, 82, 300, 40, ["For each supported language"], None)
# three deterministic checks
s += arrow(260, 122, 150, 160); s += arrow(360, 122, 360, 160); s += arrow(460, 122, 575, 160)
s += box(40, 160, 200, 74, ["Check 1", "IPA produced for", "known words"], "996")
s += box(260, 160, 200, 74, ["Check 2", "syllable count within", "±1 of expected"], "997")
s += box(480, 160, 200, 74, ["Check 3", "phrase synthesizes to a", "VALID WAV (RIFF, length,", "duration)"], "998")
# merge to report
s += arrow(140, 234, 300, 296); s += arrow(360, 234, 360, 296); s += arrow(580, 234, 420, 296)
s += box(230, 296, 260, 66, ["Per-language report +", "overall pass score +", "all-pass flag"], "999")
# supporting controls
s += box(90, 392, 540, 60, ["Supporting: deterministic text hygiene · phonemizer self-test ·",
                            "runtime-dependency presence check (all inspectable, reproducible)"], None, dashed=True)
s += '</svg>'
FIGS.append((10, "Permanent Pronunciation and Speech Quality-Control Battery (No LLM)", s))

# ===================== FIG. 33 — LIL voiceprint enrollment/matching over the Fact-Unit identity graph =====================
w, h = 720, 700
s = svg_open(w, h)
s += box(110, 16, 500, 42, ["LIL — VOICEPRINT ENROLLMENT & MATCHING OVER THE",
                            "FACT-UNIT IDENTITY GRAPH (identity assertion: no fabrication)"], "1000")
s += box(40, 74, 230, 40, ["Consent gate (precondition)"], "1001", dashed=True)
s += arrow(155, 114, 155, 136)
s += box(40, 136, 230, 48, ["Capture: audio / video", "VAD · 16 kHz · segment"], "1002")
s += arrow(270, 160, 300, 160)
s += box(300, 136, 180, 48, ["Acoustic features", "(MFCC · formants · prosody)"], "1003")
s += arrow(390, 184, 390, 206)
s += box(300, 206, 180, 46, ["Speaker embedding", "(voiceprint vector)"], "1004")
s += arrow(300, 229, 270, 229); s += box(40, 206, 230, 46, ["Enrollment: aggregate N", "→ canonical voiceprint"], "1005")
s += arrow(390, 252, 390, 276)
s += box(255, 276, 270, 50, ["Match / score (cosine · PLDA)", "vs stored voiceprints"], "1006")
s += arrow(390, 326, 390, 350)
s += box(230, 350, 320, 52, ["QueryBook TRUST GATE →", "VERIFIED · CONTRADICTED · UNKNOWN (refuse)"], "1007")
s += arrow(390, 402, 390, 428)
s += box(150, 428, 470, 92, ["Fact-Unit identity graph (provenance + trust)"], "1008")
s += box(168, 470, 120, 42, ["person ↔", "voiceprint"], None)
s += box(298, 470, 120, 42, ["person ↔ face", "↔ email/site"], None)
s += box(428, 470, 120, 42, ["person ↔", "organization"], None)
s += box(40, 560, 300, 54, ["LEL cross-script name /", "entity resolution", "(the 'Language' in LIL)"], "1009")
s += arrow(190, 560, 300, 520)
s += box(390, 560, 290, 54, ["Provenance-tracked link Fact Unit", "(subject predicate object · trust · source)"], "1010")
s += arrow(500, 560, 470, 520)
s += '</svg>'
FIGS.append((33, "LIL — Voiceprint Enrollment and Matching over the Fact-Unit Identity Graph", s))

# ===================== FIG. 34 — LIL trust-gated voice authentication + anti-spoofing =====================
w, h = 720, 560
s = svg_open(w, h)
s += box(140, 16, 440, 42, ["LIL — TRUST-GATED VOICE AUTHENTICATION",
                            "(deterministic decision · anti-spoofing · no fabricated identity)"], "1020")
s += box(270, 74, 180, 44, ["Auth request", "(claimed identity)"], "1021")
s += arrow(360, 118, 360, 140)
s += box(270, 140, 180, 44, ["Capture phrase → embed"], None)
s += arrow(360, 184, 360, 206)
s += box(230, 206, 260, 46, ["Anti-spoofing: liveness ·", "replay · synthetic / deepfake"], "1022")
s += arrow(360, 252, 360, 274)
s += box(240, 274, 240, 46, ["Risk-scoring model", "(deterministic policy)"], "1023")
s += arrow(360, 320, 360, 344)
s += box(250, 344, 220, 50, ["DECISION GATE"], "1024")
s += arrow(250, 369, 120, 420); s += label(110, 414, "accept", 10)
s += arrow(360, 394, 360, 420); s += label(368, 414, "challenge", 10)
s += arrow(470, 369, 600, 420); s += label(560, 414, "reject", 10)
s += box(40, 420, 150, 44, ["Accept", "(score≥θ, risk low)"], None)
s += box(285, 420, 150, 44, ["Second factor", "(OTP · device)"], "1025")
s += box(540, 420, 150, 44, ["Reject · log", "· alert"], None)
s += box(210, 492, 300, 46, ["Auth event Fact Unit (score · risk ·", "decision · spoof flags · provenance)"], "1026")
s += arrow(360, 464, 360, 492)
s += '</svg>'
FIGS.append((34, "LIL — Trust-Gated Voice Authentication with Anti-Spoofing", s))

# ===================== FIG. 35 — UIAS sealing + cross-submission similarity over the Fact-Unit ledger =====================
w, h = 720, 680
s = svg_open(w, h)
s += box(110, 16, 500, 42, ["UIAS — PRE-DISPUTE SEALING & CROSS-SUBMISSION",
                            "SIMILARITY OVER THE FACT-UNIT LEDGER (independent evidence)"], "1100")
s += box(40, 74, 640, 42, ["Monitored system workflow (UNMODIFIED) — agents observe at each position"], "1101")
s += box(55, 150, 120, 44, ["Input", "boundary"], "1102")
s += box(195, 150, 120, 44, ["Processing", "layer"], "1103")
s += box(335, 150, 120, 44, ["Storage", "layer"], "1104")
s += box(475, 150, 120, 44, ["Output", "boundary / handoff"], "1105")
for x in (115,255,395,535):
    s += arrow(x,116,x,150); s += arrow(x,194,x,230)
s += box(55, 230, 590, 54, ["Connector Agent (adapts to existing interface) → Ingestion Agent (seal at observation)"], "1106")
s += arrow(350, 284, 350, 308)
s += box(150, 308, 420, 58, ["SEAL = Fact Unit: content hash · one-way submitter-id hash ·",
                             "independent nanosecond timestamp · source fingerprint · agent id"], "1107")
s += arrow(240, 366, 240, 392); s += arrow(460, 366, 460, 392)
s += box(40, 392, 300, 50, ["Similarity Detection Agent", "(semantic signatures; no content)"], "1108")
s += box(360, 392, 320, 50, ["Fact-Unit audit ledger (UFCS store:", "content-addressed, append-only, immutable)"], "1109")
s += arrow(190, 442, 190, 468)
s += box(60, 468, 300, 46, ["Contemporaneous anomaly flag", "(cross-party similarity, pre-dispute)"], "1110")
s += arrow(520, 442, 520, 468)
s += box(400, 468, 280, 46, ["Verification Agent: continuous", "re-verification (self-evidencing)"], "1111")
s += box(150, 556, 420, 48, ["Content-not-stored · one-way identity (fact-level erasure)"], "1112", dashed=True)
s += arrow(350, 514, 350, 556)
s += '</svg>'
FIGS.append((35, "UIAS — Pre-Dispute Sealing and Cross-Submission Similarity over the Fact-Unit Ledger", s))

# ===================== FIG. 36 — UIAS signed Proof Package generation (independent, pre-dispute evidence) =====================
w, h = 720, 560
s = svg_open(w, h)
s += box(150, 16, 430, 42, ["UIAS — SIGNED PROOF PACKAGE GENERATION",
                            "(independent · pre-dispute · tamper-proof · complete · admissible)"], "1120")
s += box(260, 74, 200, 44, ["Accusation / inquiry", "(legal · regulatory)"], "1121")
s += arrow(360, 118, 360, 140)
s += box(250, 140, 220, 46, ["Proof Package Agent"], "1122")
s += arrow(250, 163, 120, 210); s += arrow(320, 186, 230, 210)
s += arrow(400, 186, 490, 210); s += arrow(470, 163, 600, 210)
s += box(40, 210, 160, 54, ["Sealed Fact Units", "+ verified seals"], "1123")
s += box(210, 210, 150, 54, ["Similarity log", "entry"], "1124")
s += box(370, 210, 150, 54, ["Chronological", "ledger extract (RPH)"], "1125")
s += box(530, 210, 150, 54, ["Arbitration Agent:", "factual determination", "(Prime-Directive gate)"], "1126")
for x in (120,285,445,605):
    s += arrow(x,264,360,316)
s += box(220, 316, 280, 52, ["Assemble + sign under", "UIAS independent identity"], "1127")
s += arrow(360, 368, 360, 394)
s += box(210, 394, 300, 46, ["Signed Proof Package", "(reproducible · independently verifiable)"], "1128")
s += box(150, 470, 420, 44, ["Factual determinations only —", "legal conclusions reserved to courts / regulators"], "1129", dashed=True)
s += arrow(360, 440, 360, 470)
s += '</svg>'
FIGS.append((36, "UIAS — Signed Proof Package Generation", s))

# ===================== FIG. 37 — PIL paralinguistic + pragmatic interpretation of an ingested voice =====================
w, h = 740, 700
s = svg_open(w, h)
s += box(90, 16, 540, 42, ["PIL — PARALINGUISTIC & PRAGMATIC INTERPRETATION",
                           "OF AN INGESTED VOICE (estimates labeled · frames sourced)"], "1200")
s += box(270, 72, 180, 44, ["Ingested voice", "(consent-gated)"], "1201")
s += arrow(360, 116, 360, 138)
s += box(230, 138, 260, 40, ["Transcription (words)"], "1202")
s += arrow(240, 178, 170, 210); s += arrow(480, 178, 560, 210)
# paralinguistic (left)
s += box(30, 210, 300, 46, ["Paralinguistic Analyzer (measured)"], "1203")
s += box(30, 262, 300, 64, ["tone/pitch/register · loudness(dB) ·", "pacing(rate,pauses) · emphasis ·",
                            "arousal ESTIMATE (labeled, conf.)"], "1204")
# pragmatic (right)
s += box(390, 210, 300, 46, ["Pragmatic Framer (sourced)"], "1205")
s += box(390, 262, 300, 64, ["context · perspective · ergonomics ·", "culture · social mores",
                             "(from provenance-tracked packs)"], "1206")
s += arrow(180, 326, 300, 372); s += arrow(540, 326, 420, 372)
s += box(210, 372, 300, 66, ["INTERPRETATION FRAME", "(labeled estimates + sourced frames,",
                             "with confidence/trust)"], "1207")
s += arrow(360, 438, 360, 464)
s += box(230, 464, 260, 46, ["Written as provenance-tracked", "Fact Units on the ingested content"], "1208")
s += box(90, 552, 540, 56, ["Covenant: estimates never asserted as true feelings; frames sourced &",
                            "correctable; unknown is marked, not guessed; consent; no feelings-dossier"], "1209", dashed=True)
s += arrow(360, 510, 360, 552)
s += '</svg>'
FIGS.append((37, "PIL — Paralinguistic and Pragmatic Interpretation of an Ingested Voice", s))

# ===================== FIG. 38 — PIL query interpretation (intent, register, clarify-or-answer gate) =====================
w, h = 720, 620
s = svg_open(w, h)
s += box(120, 16, 480, 42, ["PIL — HUMAN QUERY INTERPRETATION",
                            "(shapes WHICH question & HOW; facts still from the verified store)"], "1210")
s += box(270, 72, 180, 44, ["Human query", "(typed or spoken)"], "1211")
s += arrow(360, 116, 360, 138)
s += box(250, 138, 220, 44, ["Interpretation Frame", "(para + pragmatic)"], "1212")
s += arrow(360, 182, 360, 206)
s += box(240, 206, 240, 46, ["Intent disambiguation", "(context · perspective)"], "1213")
s += arrow(360, 252, 360, 276)
s += box(255, 276, 210, 48, ["AMBIGUITY GATE"], "1214")
s += arrow(255, 300, 110, 344); s += label(95, 338, "ambiguous", 10)
s += box(40, 344, 170, 48, ["Ask ONE clarifying", "question · stop"], "1215")
s += arrow(430, 324, 430, 352); s += label(438, 344, "resolved", 10)
s += box(330, 352, 220, 46, ["Register & ergonomic", "mode selector"], "1216")
s += box(560, 352, 120, 46, ["culture · mores ·", "ergonomics packs"], "1217")
s += arrow(560, 375, 550, 375)
s += arrow(440, 398, 440, 424)
s += box(250, 424, 300, 50, ["PLAN→RETRIEVE→GATE→COMPOSE→CHECK", "(verified Fact Units; cite or refuse)"], "1218")
s += arrow(400, 474, 400, 500)
s += box(230, 500, 340, 48, ["Answer composed IN the selected register/mode", "— facts unchanged, sourced or refused"], "1219")
s += '</svg>'
FIGS.append((38, "PIL — Human Query Interpretation and Covenant-Bound Answering", s))

# ===================== FIG. 39 — Lecture Query ingestion pipeline =====================
w, h = 720, 700
s = svg_open(w, h)
s += box(130, 16, 460, 42, ["LECTURE QUERY — INGESTION PIPELINE",
                            "(claims attributed, not asserted · emotion labeled · identity trust-gated)"], "1300")
s += box(250, 72, 220, 46, ["Live or recorded", "audio / video program"], "1301")
s += arrow(360, 118, 360, 140)
s += box(230, 140, 260, 44, ["Capture + consent gate"], "1302")
s += arrow(240, 184, 160, 214); s += arrow(480, 184, 560, 214)
s += box(40, 214, 250, 48, ["ASR transcription + diarization", "(untrusted input; shown)"], "1303")
s += box(440, 214, 240, 48, ["Video frames → faces (LIL)"], "1304")
s += arrow(165, 262, 165, 288); s += arrow(560, 262, 440, 340)
s += box(40, 288, 300, 64, ["PIL analysis (over time):", "tone · loudness · pacing ·",
                            "labeled arousal + pragmatic frame"], "1305")
s += box(360, 288, 320, 48, ["LEL: segment · structure ·", "extract claims & key points"], "1306")
s += arrow(190, 352, 300, 400); s += arrow(520, 336, 420, 400)
s += box(220, 400, 300, 48, ["Deterministic summary", "(TOC · key points · claim list)"], "1307")
s += arrow(360, 448, 360, 474)
s += box(170, 474, 400, 52, ["INGEST → LECTURE RECORD in Fact Unit library;",
                             "claims = ATTRIBUTED utterance facts (gate-verifiable)"], "1308")
s += arrow(360, 526, 360, 552)
s += box(70, 552, 580, 56, ["Forever-link (immutable, provenance, trust-gated via LIL):",
                            "speaker (voiceprint/face) · venue · event · organization · date"], "1309")
s += '</svg>'
FIGS.append((39, "Lecture Query — Ingestion Pipeline", s))

# ===================== FIG. 40 — the forever-linked Lecture Record in the Fact-Unit graph + query =====================
w, h = 720, 600
s = svg_open(w, h)
s += box(170, 16, 380, 42, ["THE FOREVER-LINKED LECTURE RECORD",
                            "(queryable · attributed · tamper-evident)"], "1310")
s += box(280, 74, 160, 56, ["LECTURE RECORD", "(content-addressed)"], "1311")
# entity links around it
s += box(40, 170, 150, 44, ["Speaker (LIL:", "voiceprint/face)"], "1312")
s += box(210, 170, 150, 44, ["Venue"], "1313")
s += box(380, 170, 150, 44, ["Event"], "1314")
s += box(550, 170, 130, 44, ["Organization", "· date"], "1315")
for x in (115,285,455,615):
    s += line(360,130,x,170); s += arrow(x,168,x,170)
s += box(90, 250, 250, 48, ["Transcript + diarization"], "1316")
s += box(380, 250, 250, 48, ["PIL track (tone/pacing over time)"], "1317")
s += arrow(250,130,215,250); s += arrow(470,130,505,250)
s += box(150, 330, 420, 50, ["Attributed claims (per speaker@event):", "gate → corroborated / contradicted / open"], "1318")
s += arrow(360,298,360,330)
s += arrow(360,380,360,406)
s += box(170, 406, 380, 48, ["FQL / Q&A: 'what did X say about Y at Z?' ·", "'where did A and B disagree?' · 'tone during Q&A?'"], "1319")
s += arrow(360,454,360,480)
s += box(200, 480, 320, 46, ["Answer: cited to the record, attributed,", "refused where unknown (covenant)"], "1320")
s += '</svg>'
FIGS.append((40, "Lecture Query — The Forever-Linked Lecture Record and Its Querying", s))

# ===================== FIG. 41 — Deterministic Multilingual Acquisition (No Generative Model) =====================
w, h = 720, 470
s = svg_open(w, h)
s += box(60, 20, 260, 40, ["Public-domain corpus (lawful)"], "4101")
s += box(400, 20, 260, 40, ["Governed bilingual dictionary"], "4102")
s += arrow(190, 60, 300, 110); s += arrow(530, 60, 420, 110)
s += box(255, 110, 210, 46, ["Per-language learning agent", "(deterministic)"], "4110")
s += label(360, 92, "NO large / generative language model in the grounding path", 11, "middle", True)
s += arrow(360, 156, 360, 182)
s += box(40, 182, 190, 44, ["Vocabulary"], "4111")
s += box(265, 182, 190, 44, ["Phonology / IPA"], "4112")
s += box(490, 182, 190, 44, ["Grammar regularities"], "4113")
s += line(135,182,135,170); s += line(135,170,585,170); s += line(585,170,585,182)
s += line(360,156,360,170)
s += arrow(135, 226, 135, 258); s += arrow(360, 226, 360, 258); s += arrow(585, 226, 585, 258)
s += box(255, 258, 210, 46, ["IPA verified against a", "reference phonemizer"], "4120")
s += line(135,258,135,281); s += line(135,281,255,281)
s += line(585,258,585,281); s += line(585,281,465,281)
s += arrow(300, 304, 240, 338); s += arrow(420, 304, 480, 338)
s += box(90, 338, 300, 44, ["Provenance-tracked lexical record", "(reproducible from same inputs)"], "4130")
s += box(430, 338, 230, 44, ["Withheld (not asserted)", "on verification failure"], "4131", dashed=True)
s += '</svg>'
FIGS.append((41, "Deterministic Multilingual Acquisition Without a Generative Model", s))

# ===================== FIG. 42 — Dialect Parameter Clusters (DPC) =====================
w, h = 720, 430
s = svg_open(w, h)
s += box(250, 18, 220, 40, ["Dialect Parameter Cluster", "(declared, versioned)"], "4201")
s += box(40, 96, 200, 40, ["Phonological parameters"], "4202")
s += box(260, 96, 200, 40, ["Lexical parameters"], "4203")
s += box(480, 96, 200, 40, ["Orthographic parameters"], "4204")
s += line(360,58,360,76); s += line(140,76,580,76)
s += arrow(140,76,140,96); s += arrow(360,76,360,96); s += arrow(580,76,580,96)
s += box(60, 196, 220, 40, ["Input utterance"], "4205")
s += arrow(280, 216, 330, 216)
s += box(330, 188, 240, 56, ["Parameter-match scorer", "(deterministic attribution)"], "4210")
s += arrow(450, 244, 450, 274)
s += box(330, 274, 240, 40, ["Dialect attribution"], "4220")
s += arrow(450, 314, 450, 344)
s += box(300, 344, 300, 40, ["Modulates EXPRESSION only"], "4230")
s += box(40, 300, 250, 84, ["Never alters admission,", "applicability scope, confidence,", "or governed vocabulary", "(declared, not inferred)"], "4231", dashed=True)
s += '</svg>'
FIGS.append((42, "Dialect Parameter Clusters (DPC) — Declared, Expression-Only Modulation", s))

# ===================== FIG. 43 — Grounded Scene Compilation to an External Generative Media Engine =====================
w, h = 760, 430
s = svg_open(w, h)
s += box(60, 24, 200, 40, ["Verified Fact Units"], "4301")
s += arrow(160, 64, 160, 96)
s += box(60, 96, 200, 46, ["Grounded scene", "representation"], "4310")
s += arrow(260, 119, 300, 119)
s += box(300, 92, 220, 56, ["Prompt-bundle compiler", "+ validator"], "4320")
s += arrow(520, 119, 560, 119)
s += box(540, 92, 160, 56, ["External generative", "video engine"], "4330", dashed=True)
s += label(620, 84, "external", 10, "middle")
s += arrow(620, 148, 620, 190)
s += box(520, 190, 200, 44, ["Returned media"], "4340")
s += arrow(620, 234, 620, 266)
s += box(470, 266, 250, 44, ["Marked: derived artifact /", "reconstruction"], "4341")
s += arrow(470, 288, 300, 288)
s += box(60, 266, 230, 44, ["NEVER admitted as a", "grounding source"], "4342", dashed=True)
s += label(360, 356, "Extends Derived-Artifact-Only Extraction + Reconstruction Marking", 11, "middle", True)
s += '</svg>'
FIGS.append((43, "Grounded Scene Compilation to an External Generative Media Engine", s))

# ===================== FIG. 44 — Key-Safe External-Service Mediation =====================
w, h = 760, 420
s = svg_open(w, h)
s += line(360, 20, 360, 400, dashed=True)
s += label(360, 14, "query / presentation boundary", 11, "middle", True)
s += box(60, 80, 230, 56, ["Requesting client", "(no credential ever)"], "4401")
s += box(430, 60, 240, 56, ["Mediation server", "(query-side)"], "4410")
s += box(445, 140, 210, 40, ["Credential vault (server-held)"], "4411")
s += line(550,116,550,140)
s += arrow(670, 88, 700, 88); s += box(560, 210, 150, 46, ["External service", "(video / speech)"], "4420", dashed=True)
s += line(655,116,655,210); s += arrow(655,206,655,210)
s += box(430, 300, 240, 44, ["Media cached by opaque id"], "4412")
s += line(610,256,610,300); s += arrow(610,296,610,300)
s += arrow(430, 322, 290, 322)
s += box(60, 300, 230, 44, ["Client receives media", "by opaque id only"], "4413")
s += label(360, 384, "credential never crosses the boundary", 11, "middle", True)
s += '</svg>'
FIGS.append((44, "Key-Safe External-Service Mediation", s))

# ===================== FIG. 45 — Scene Reconstruction From Prose =====================
w, h = 720, 410
s = svg_open(w, h)
s += box(260, 20, 200, 40, ["Prose source"], "4501")
s += arrow(360, 60, 360, 92)
s += box(255, 92, 210, 46, ["Deterministic", "reconstructor"], "4510")
s += arrow(360, 138, 360, 164)
s += box(40, 164, 200, 44, ["Shot sequence"], "4511")
s += box(260, 164, 200, 44, ["Timed prompt sequence"], "4512")
s += box(480, 164, 200, 44, ["Pacing / music cues"], "4513")
s += line(140,164,140,152); s += line(140,152,580,152); s += line(580,152,580,164); s += line(360,138,360,152)
s += arrow(260, 208, 360, 250); s += arrow(360,208,360,250); s += arrow(460,208,360,250)
s += box(220, 250, 280, 44, ["Non-identified participant", "rendered as SILHOUETTE"], "4520")
s += arrow(360, 294, 360, 320)
s += box(240, 320, 240, 40, ["Marked as a reconstruction"], "4530")
s += '</svg>'
FIGS.append((45, "Scene Reconstruction From Prose — Bounded, Silhouette-Protected", s))

# ===================== FIG. 46 — Modular Edition Packaging =====================
w, h = 720, 410
s = svg_open(w, h)
s += box(270, 18, 180, 40, ["Edition selector", "(at launch)"], "4601")
s += line(360,58,360,74); s += line(140,74,580,74)
s += arrow(140,74,140,100); s += arrow(360,74,360,100); s += arrow(580,74,580,100)
s += box(50, 100, 180, 44, ["Light edition"], "4610")
s += box(270, 100, 180, 44, ["Medium edition"], "4620")
s += box(490, 100, 180, 44, ["Full edition"], "4630")
s += box(50, 156, 180, 40, ["declared subset A"], "4611", dashed=True)
s += box(270, 156, 180, 40, ["declared subset B"], "4621", dashed=True)
s += box(490, 156, 180, 40, ["declared subset C"], "4631", dashed=True)
s += line(140,144,140,156); s += line(360,144,360,156); s += line(580,144,580,156)
s += box(110, 280, 500, 70, ["Invariant base across EVERY edition:", "Prime Directive (Domain 0) + deterministic reasoning core"], "4640")
s += arrow(140, 196, 300, 280); s += arrow(360, 196, 360, 280); s += arrow(580, 196, 420, 280)
s += label(360, 372, "an edition changes which subsystems are present, never the governing constraints", 11, "middle", True)
s += '</svg>'
FIGS.append((46, "Modular Edition Packaging — Nested Capability Editions", s))

# ===================== FIG. 47 — Version-Independent, Provenance-Continuous Store =====================
w, h = 720, 410
s = svg_open(w, h)
s += box(250, 150, 220, 64, ["Canonical store location", "(version-independent)"], "4701")
s += box(265, 230, 190, 34, ["Provenance-tracked records"], "4702")
s += line(360,214,360,230)
s += box(40, 40, 150, 40, ["Software v(n)"], "4710")
s += box(285, 40, 150, 40, ["Software v(n+1)"], "4711")
s += box(530, 40, 150, 40, ["Software v(n+2)"], "4712")
s += arrow(115, 80, 300, 150); s += arrow(360, 80, 360, 150); s += arrow(605, 80, 420, 150)
s += label(360, 110, "all versions bind to the SAME store", 11, "middle", True)
s += box(150, 300, 420, 48, ["Refuse to substitute an empty store", "where a populated store exists"], "4720", dashed=True)
s += arrow(360, 264, 360, 300)
s += label(360, 372, "a version change never re-initializes or orphans the records", 11, "middle", True)
s += '</svg>'
FIGS.append((47, "Version-Independent, Provenance-Continuous Store", s))

# ===================== FIG. 48 — Cited Q&A / ChatBot application =====================
w, h = 775, 560
s = svg_open(w, h)
s += box(255, 16, 230, 34, ["Cited Q&A / ChatBot application"], "4800")
s += box(60, 80, 200, 46, ["User question", "(typed or spoken)"], "4801")
s += arrow(260, 103, 300, 103)
s += box(300, 78, 200, 50, ["Query interpretation", "(intent · register)"], "4810")
s += arrow(500, 103, 540, 103)
s += box(540, 80, 170, 46, ["FQL retrieval over", "verified Fact Units"], "4820")
s += arrow(625, 126, 625, 158)
s += box(255, 158, 230, 54, ["PRIME-DIRECTIVE GATE", "(evidence sufficient?)"], "4830")
s += line(625, 158, 625, 140); s += line(625, 140, 485, 140); s += line(485, 140, 370, 158)
s += arrow(255, 185, 110, 230); s += label(95, 224, "no / insufficient", 10)
s += arrow(485, 185, 620, 230); s += label(600, 224, "yes · cited", 10)
s += box(40, 230, 190, 56, ["Honest UNKNOWN", "(refuse — never guess)"], "4841")
s += box(520, 230, 200, 56, ["Composed answer with", "per-fact citations"], "4840")
s += line(135, 286, 135, 330); s += line(620, 286, 620, 330); s += line(135, 330, 620, 330)
s += arrow(360, 330, 360, 360)
s += box(235, 360, 270, 50, ["Delivered to ChatBot / assistant", "surface (same contract)"], "4850")
s += box(120, 470, 500, 56, ["No LLM asserts a fact: every answer is a citation to a verified",
                             "Fact Unit or an honest UNKNOWN — the covenant holds end to end"], "4860", dashed=True)
s += arrow(360, 410, 360, 470)
s += '</svg>'
FIGS.append((48, "Cited Q&A / ChatBot Application — Citation-or-UNKNOWN End to End", s))

# ===================== FIG. 49 — Application & deployment surfaces over the invariant core =====================
w, h = 920, 470
s = svg_open(w, h)
s += box(320, 20, 280, 40, ["Invariant QueryBook core", "(Fact Units · UFCS · FQL · Prime Directive)"], "4900")
# five evenly spaced surface boxes: x = 40, 212, 384, 556, 728 (width 150, gap ~22)
xs = [40, 212, 384, 556, 728]
centers = [x + 75 for x in xs]
s += line(460, 60, 460, 92); s += line(centers[0], 92, centers[-1], 92)
for cx in centers:
    s += arrow(cx, 92, cx, 120)
s += box(40,  120, 150, 74, ["On-device", "eBook / document", "Q&A (micro-", "encapsulated)"], "4910")
s += box(212, 120, 150, 74, ["SaaS / API", "service"], "4920")
s += box(384, 120, 150, 74, ["Fact-Unit", "compressed", "search engine"], "4930")
s += box(556, 120, 150, 74, ["Deterministic", "LLM-hybrid adjunct", "(gated suggestor)"], "4940")
s += box(728, 120, 150, 74, ["Private / offline", "analysis", "(air-gapped)"], "4950")
s += label(460, 250, "every surface inherits the same citation-or-UNKNOWN contract and provenance", 11, "middle", True)
s += box(240, 300, 440, 60, ["Each surface is a presentation of the SAME governed Fact Units;",
                             "no surface can assert a fact the core would refuse"], "4960", dashed=True)
s += arrow(460, 194, 460, 300)
s += '</svg>'
FIGS.append((49, "Application and Deployment Surfaces over the Invariant Core", s))

# ---------------- assemble the DRAWINGS section ----------------
draw = ['<h2 id="drawings">Drawings</h2>',
        '<p style="font-size:12px;color:#5a554b;font-family:Helvetica,Arial,sans-serif">Formal patent drawings — black line art. Each figure is on its own sheet and every element is identified by a reference numeral used consistently in the Brief Description of the Drawings, the Reference Numerals key, and the Detailed Description. Figures are draft; counsel/draftsperson to finalize to USPTO drawing standards (37 CFR 1.84) before filing.</p>']
for num, title, svg in FIGS:
    draw.append(f'<div style="page-break-inside:avoid;margin:18px 0 26px">'
                f'<div style="font-family:Helvetica,Arial,sans-serif;font-weight:700;font-size:13px;margin:0 0 6px">'
                f'FIG. {num}</div>{svg}'
                f'<div style="font-family:Helvetica,Arial,sans-serif;font-size:11.5px;color:#333;margin-top:6px;text-align:center">'
                f'FIG. {num} — {esc(title)}</div></div>')
open("ppa_drawings.html", "w", encoding="utf-8").write("\n".join(draw))

# ---------------- Brief Description of the Drawings ----------------
bd = ['<h2>Brief Description of the Drawings</h2>']
descr = {
 1: "is a block diagram of the overall QueryBook Language Expression Layer (LEL) system architecture.",
 2: "is a block diagram of the Sub-Language Priming Layer (SLPL) and the measurable representation produced by each of its six components.",
 3: "is a flow diagram of the developmental learning sequence and the one-way Transition Gate having four readiness thresholds.",
 4: "is a block diagram of the multilingual Delta Acquisition Model and the acquisition acceleration flywheel.",
 5: "is a block diagram of the seven-stage Speech Output Pipeline.",
 6: "is a data-flow diagram of the co-grounded integration of the LEL with the Federated Query Language (FQL) and the Universal Federated Connectivity System (UFCS).",
 7: "is a block diagram of a reduced-to-practice embodiment (the Language Lab) implementing Phase One, the Transition Gate, and a deterministic Phase Two, per Section VII.",
 8: "is a data-flow diagram of the deterministic Phase-Two semantic grounding of the reduced-to-practice embodiment, in which word meanings are attached only from auditable sources — a bundled public-domain dictionary and self-grounding against verified Fact Units in the store — with any large-language-model meaning source excluded from the grounding path.",
 9: "is a block diagram of the advanced multilingual pronunciation subsystem and self-contained speech output of the reduced-to-practice embodiment, showing the pronunciation preference ladder (bundled open-source phonemizer, then per-language rule-seeded grapheme-to-phoneme tables, then an explicit non-fabricated null), the single-call phrase transcription that keeps the displayed transcription consistent with the synthesized audio, and the self-contained bundle and engine-selection ladder that produce offline audio or an honest refusal without fabricating audio, per Section VIII.",
 10: "is a flow diagram of the permanent, deterministic pronunciation-and-speech quality-control battery of the reduced-to-practice embodiment, which, for each supported language and without a large language model, verifies that a phonemic transcription is produced, that the syllable count is within tolerance, and that a short phrase synthesizes to a valid audio waveform, returning a per-language report and an overall pass score, per Section VIII.",
 33: "is a data-flow diagram of the Language & Identity Linking (LIL) voiceprint enrollment and matching subsystem, in which a consent-gated capture produces an acoustic speaker embedding (voiceprint), a match against stored voiceprints is passed through a QueryBook trust gate returning VERIFIED, CONTRADICTED, or UNKNOWN, and verified identity links are written as provenance-tracked, trust-scored Fact Units in the identity graph, with cross-script name and entity resolution performed by the language subsystem, per Section IX.",
 34: "is a flow diagram of the LIL trust-gated voice authentication process, in which a claimed-identity verification produces a match score and anti-spoofing signals that feed a deterministic risk-scoring policy and a decision gate returning accept, challenge (second factor), or reject, each decision recorded as a provenance-tracked auth-event Fact Unit, per Section IX.",
 35: "is a block diagram of the Universal Integrity Audit Service (UIAS), in which connector and ingestion agents observe an unmodified monitored system at multiple workflow positions and seal each observable event as a content-addressed Fact Unit carrying a content hash, a one-way submitter-identity hash, an independent nanosecond timestamp, a source fingerprint, and the sealing agent's identity; a similarity-detection agent sets a contemporaneous cross-party anomaly flag over content signatures without storing content; and a verification agent continuously re-verifies the append-only Fact-Unit ledger, per Section X.",
 36: "is a flow diagram of the UIAS signed Proof Package generation, in which, on an accusation or inquiry, a proof-package agent assembles verified sealed Fact Units, the similarity-log entry, a chronological ledger extract bound by the response-provenance hash, and a factual determination from the arbitration agent under the Prime-Directive gate, and signs the package under the UIAS independent identity to produce independent, pre-dispute, tamper-proof, complete, and admissible evidence, per Section X.",
 37: "is a data-flow diagram of the Paralinguistic & Pragmatic Interpretation Layer (PIL) applied to an ingested voice, in which a paralinguistic analyzer produces measured acoustic readings and a labeled arousal estimate while a pragmatic framer applies sourced context, perspective, ergonomics, culture, and social-mores frames, the two combining into an Interpretation Frame written as provenance-tracked Fact Units, with estimates labeled and never asserted as true feelings, per Section XI.",
 38: "is a flow diagram of the PIL human-query interpretation, in which a query is reduced to an Interpretation Frame, intent is disambiguated from context and perspective, an ambiguity gate asks one clarifying question when intent is materially uncertain, a register-and-ergonomic-mode selector sets the reply style and delivery from sourced culture/mores/ergonomics packs, and the existing retrieve-gate-compose pipeline answers from verified Fact Units in that register without altering the facts, per Section XI.",
 39: "is a block diagram of the Lecture Query mode ingestion pipeline, in which a live or recorded audio/video program is captured under consent, transcribed and diarized, analyzed by the paralinguistic layer over time and by the language layer for structure and claims, summarized deterministically, and ingested as a Lecture Record whose claims are stored as attributed utterance facts and which is forever-linked to the speaker, venue, event, organization, and date by immutable provenance-tracked, trust-gated identity links, per Section XII.",
 40: "is a data-flow diagram of the forever-linked Lecture Record in the Fact-Unit identity graph and its querying, showing the record bound to speaker, venue, event, and organization entities and to the transcript and paralinguistic track, its attributed claims gated as corroborated, contradicted, or open, and a query answered with citations to the record and attribution to the speaker, refused where unknown, per Section XII.",
 41: "is a data-flow diagram of deterministic multilingual acquisition without a generative model, in which a per-language learning agent acquires vocabulary, phonology (IPA), and grammatical regularities from a lawful public-domain corpus and a governed bilingual dictionary, an IPA transcription is verified against a reference phonemizer and withheld rather than asserted when verification fails, and each accepted item is written as a provenance-tracked lexical record reproducible from the same inputs, with no large or generative language model in the grounding path.",
 42: "is a block diagram of a Dialect Parameter Cluster (DPC), a declared and versioned cluster of phonological, lexical, and orthographic parameters by which an input utterance is attributed to a dialect by a deterministic parameter-match score, the cluster modulating expression only and never altering admission, applicability scope, confidence, or the governed vocabulary.",
 43: "is a data-flow diagram of grounded scene compilation to an external generative media engine, in which a grounded scene representation derived from verified Fact Units is compiled and validated into a prompt bundle for an external generative video engine and any returned media is admitted only as a derived artifact marked as a reconstruction and never as a grounding source.",
 44: "is a block diagram of key-safe external-service mediation, in which a credential for an external service is held on the server side of the query/presentation boundary and never transmitted to the client, the server performing the external call and serving the result to the client by an opaque cache identifier so that the credential never crosses the boundary.",
 45: "is a flow diagram of scene reconstruction from prose, in which a deterministic reconstructor derives a shot sequence, a timed prompt sequence, and pacing and music cues as a bounded reconstruction, renders a participant who is not an identified subject as a silhouette so that no unverified identity is fabricated, and marks the whole as a reconstruction.",
 46: "is a block diagram of modular edition packaging, in which the system is deployable as one of a plurality of nested capability editions selected at launch, each edition enabling a declared subset of subsystems while the Prime Directive and the deterministic reasoning core remain invariant across every edition.",
 47: "is a block diagram of the version-independent, provenance-continuous store, in which the knowledge store resides at a canonical location independent of the deployment software version so that successive software versions bind to the same provenance-tracked records, a version change never re-initializes the store, and the system refuses to substitute an empty store where a populated store exists.",
 48: "is a data-flow diagram of a cited question-and-answer (ChatBot) application embodiment, in which a user question is interpreted for intent and register, answered by Federated Query Language retrieval over verified Fact Units, passed through the Prime-Directive gate, and returned either as a composed answer carrying per-fact citations or, where the evidence is insufficient, as an honest UNKNOWN, the same citation-or-UNKNOWN contract holding when the embodiment is deployed as a ChatBot or assistant surface.",
 49: "is a block diagram of the application and deployment surfaces of the system over its invariant core, in which a single governed body of Fact Units is presented through an on-device micro-encapsulated eBook or document question-and-answer surface, a software-as-a-service or application-programming-interface service, a Fact-Unit compressed search engine, a deterministic large-language-model-hybrid adjunct, and a private or offline analysis deployment, each surface inheriting the same citation-or-UNKNOWN contract and provenance and none able to assert a fact the core would refuse.",
}
for num, _, _ in FIGS:
    bd.append(f'<p class="pp"><b>FIG. {num}</b> {esc(descr[num])}</p>')
open("ppa_briefdesc.html", "w", encoding="utf-8").write("\n".join(bd))

# ---------------- Reference Numerals key ----------------
REFS = [
 ("100","QueryBook LEL system"),("110","Sub-Language Priming Layer (SLPL)"),
 ("120","Language Expression Layer (LEL)"),("130","Transition Gate"),
 ("140","Phase Two semantic-communicative learning"),("150","Multilingual Delta Acquisition module"),
 ("160","Speech Output Pipeline"),("165","natural speech output"),("170","co-grounding interface"),
 ("180","Federated Query Language (FQL)"),("190","Universal Federated Connectivity System (UFCS)"),
 ("195","federated data sources"),
 ("200","SLPL"),("210","acoustic phonetic processing"),("211","signal-level feature embedding"),
 ("220","phonics / phonemic awareness"),("221","phoneme-boundary segmenter"),
 ("230","communication-science foundations"),("231","communicative-salience weight"),
 ("240","prosody & rhythm processing"),("241","prosodic contour vector"),
 ("250","information-theoretic grounding"),("251","information weighting"),
 ("260","neurolinguistic chunking"),("261","chunk segments"),("270","licensed multimedia input"),
 ("300","developmental learning sequence"),("310","Phase One (structural-acoustic)"),
 ("311","sound discrimination"),("312","syllabic segmentation"),("313","word-as-acoustic-object"),
 ("314","semantics suppressed"),("320","Transition Gate (one-way)"),("321","phonemic-inventory completeness ≥ τ1"),
 ("322","lexical stability ≥ τ2"),("323","co-occurrence density ≥ τ3"),("324","pattern saturation < ε"),
 ("330","Phase Two (semantic-communicative)"),("331","word-to-referent grounding"),
 ("332","communicative discovery"),("333","emergent grammar / syntax"),
 ("400","Delta Acquisition Model"),("410","reused L1 foundation"),("420","L2 delta detector"),
 ("430","targeted training of novel elements"),("440","multilingual semantic alignment"),
 ("450","acquisition acceleration flywheel"),("451","negative-transfer detection & retraining"),
 ("500","Speech Output Pipeline"),("510","lexical selection"),("520","grapheme-to-phoneme conversion"),
 ("530","coarticulation modeling"),("540","prosody generation"),("550","register & affect calibration"),
 ("560","self-monitoring feedback loop"),("570","neural vocoder rendering"),("580","natural speech waveform"),
 ("600","co-grounded integration"),("610","natural-language input"),("620","LEL analysis"),
 ("630","FQL operations"),("640","UFCS execution"),("650","federated sources"),("660","results"),
 ("670","render to NL / speech in input language"),("680","language-agnostic resolution"),
 ("700","Language Lab prototype embodiment"),("710","corpus source"),("720","Phase-One structural agent"),
 ("730","structural analyzer"),("731","grapheme inventory"),("732","rule-seeded G2P"),
 ("733","syllabifier"),("734","lexical-stability metric"),("735","co-occurrence density metric"),
 ("736","prosody proxy"),("740","Fact Unit store"),("750","Transition-Gate metrics"),
 ("751","one-way latch"),("760","phase agents on shared manager"),("761","Phase-1 agent (implemented)"),
 ("762","Phase-2 agent — deterministic dictionary + store grounding (implemented)"),
 ("763","Phase-3 agent (declines — spec-only)"),
 ("764","Phase-4 agent (declines — spec-only)"),
 ("800","deterministic Phase-Two semantic grounding"),("810","Phase-One vocabulary (learned words)"),
 ("820","deterministic grounder (per word)"),("830","bundled public-domain dictionary source"),
 ("831","dictionary meaning Fact Unit (means, trust 0.9)"),("840","self-grounding store-lookup source"),
 ("841","store-link Fact Unit (grounded_by_fact)"),("850","Fact Unit store (provenance, domain language)"),
 ("860","excluded large-language-model meaning source"),
 ("870","optional future dictionary-gated suggestor"),
 ("900","advanced multilingual pronunciation subsystem"),("910","pronunciation request (word/phrase, language)"),
 ("920","pronunciation preference-ladder selector"),("930","bundled open-source phonemizer"),
 ("931","phonemizer IPA transcription"),("932","phonemizer call cache"),
 ("933","bounded call log / timeout guard"),("940","rule-seeded G2P tables (per language)"),
 ("941","approximate rule-seeded IPA (offline)"),("950","syllable count + primary-stress derivation"),
 ("960","explicit null result (not fabricated)"),("970","phrase-level single-call transcription"),
 ("971","displayed transcription consistent with synthesized audio"),
 ("980","self-contained application bundle"),("981","bundled open-source speech engine"),
 ("982","runtime-support libraries"),("983","bundled phoneme data"),
 ("984","engine-selection ladder (per OS / language)"),("985","host OS built-in voice service"),
 ("986","culture-matched OS voice (when installed)"),("987","honest refusal with remedy (no fabricated audio)"),
 ("990","deterministic translator (through English)"),("991","bundled open-source bilingual dictionary"),
 ("992","coverage accounting + unknown-word passthrough (flagged)"),
 ("993","deterministic language detector"),("995","permanent quality-control battery"),
 ("996","IPA-produced check"),("997","syllable-sanity check (±1)"),
 ("998","valid-waveform synthesis check"),("999","per-language QC report + overall pass score"),
 ("1000","LIL voiceprint & identity subsystem"),("1001","consent gate (precondition)"),
 ("1002","audio/video capture + VAD/segmentation"),("1003","acoustic feature extraction"),
 ("1004","speaker embedding (voiceprint vector)"),("1005","enrollment — canonical voiceprint"),
 ("1006","match / score (cosine · PLDA)"),("1007","QueryBook trust gate (VERIFIED/CONTRADICTED/UNKNOWN)"),
 ("1008","Fact-Unit identity graph"),("1009","LEL cross-script name/entity resolution"),
 ("1010","provenance-tracked link Fact Unit"),("1020","voice authentication request"),
 ("1021","capture phrase + embed"),("1022","anti-spoofing (liveness/replay/synthetic)"),
 ("1023","deterministic risk-scoring policy"),("1024","authentication decision gate"),
 ("1025","second-factor challenge"),("1026","auth-event Fact Unit (provenance)"),
 ("1100","UIAS integrity audit service"),("1101","monitored system workflow (unmodified)"),
 ("1102","input-boundary position"),("1103","processing-layer position"),
 ("1104","storage-layer position"),("1105","output-boundary / handoff position"),
 ("1106","Connector + Ingestion agents (seal at observation)"),
 ("1107","seal = Fact Unit (hash · id-hash · independent timestamp · source · agent)"),
 ("1108","Similarity Detection Agent (semantic signatures)"),
 ("1109","Fact-Unit audit ledger (UFCS, append-only, immutable)"),
 ("1110","contemporaneous cross-party anomaly flag"),("1111","Verification Agent (continuous re-verification)"),
 ("1112","content-not-stored / one-way identity (fact-level erasure)"),
 ("1120","UIAS signed Proof Package generation"),("1121","accusation / inquiry"),
 ("1122","Proof Package Agent"),("1123","sealed Fact Units + verified seals"),
 ("1124","cross-submission similarity log entry"),("1125","chronological ledger extract (RPH)"),
 ("1126","Arbitration Agent (factual determination; Prime-Directive gate)"),
 ("1127","assemble + sign under UIAS independent identity"),("1128","signed Proof Package"),
 ("1129","factual-only determination (legal reserved to courts/regulators)"),
 ("1200","PIL paralinguistic & pragmatic interpretation"),("1201","ingested voice (consent-gated)"),
 ("1202","transcription (words)"),("1203","Paralinguistic Analyzer (measured)"),
 ("1204","tone/loudness/pacing/emphasis + labeled arousal estimate"),
 ("1205","Pragmatic Framer (sourced)"),
 ("1206","context · perspective · ergonomics · culture · social mores"),
 ("1207","Interpretation Frame (labeled estimates + sourced frames)"),
 ("1208","Fact Units on ingested content"),("1209","covenant: estimates not asserted; frames sourced; consent"),
 ("1210","PIL human query interpretation"),("1211","human query (typed/spoken)"),
 ("1212","Interpretation Frame (para + pragmatic)"),("1213","intent disambiguation (context/perspective)"),
 ("1214","ambiguity gate"),("1215","ask one clarifying question / stop"),
 ("1216","register & ergonomic mode selector"),("1217","culture/mores/ergonomics packs"),
 ("1218","retrieve-gate-compose (verified Fact Units; cite or refuse)"),
 ("1219","answer in selected register/mode (facts unchanged)"),
 ("1300","Lecture Query ingestion pipeline"),("1301","live or recorded audio/video program"),
 ("1302","capture + consent gate"),("1303","ASR transcription + diarization (untrusted input)"),
 ("1304","video frames → faces (LIL)"),("1305","PIL analysis over time (tone/pacing/arousal + frame)"),
 ("1306","LEL segment/structure/extract claims"),("1307","deterministic summary (TOC/key points/claims)"),
 ("1308","ingest → Lecture Record; claims = attributed utterance facts"),
 ("1309","forever-link: speaker/venue/event/org/date (immutable, trust-gated)"),
 ("1310","forever-linked Lecture Record (queryable)"),("1311","Lecture Record (content-addressed)"),
 ("1312","speaker entity (LIL voiceprint/face)"),("1313","venue entity"),("1314","event entity"),
 ("1315","organization + date"),("1316","transcript + diarization"),("1317","PIL track (tone/pacing over time)"),
 ("1318","attributed claims → corroborated/contradicted/open"),("1319","FQL / Q&A over the record"),
 ("1320","answer: cited, attributed, refused where unknown"),
 ("4800","cited Q&A / ChatBot application"),("4801","user question (typed/spoken)"),
 ("4810","query interpretation (intent/register)"),("4820","FQL retrieval over verified Fact Units"),
 ("4830","Prime-Directive gate (evidence sufficiency)"),("4840","composed answer with per-fact citations"),
 ("4841","honest UNKNOWN (refuse, never guess)"),("4850","ChatBot/assistant delivery surface"),
 ("4860","citation-or-UNKNOWN covenant held end to end"),
 ("4900","invariant QueryBook core"),("4910","on-device eBook/document Q&A (micro-encapsulated)"),
 ("4920","SaaS / API service surface"),("4930","Fact-Unit compressed search engine"),
 ("4940","deterministic LLM-hybrid adjunct (gated suggestor)"),("4950","private/offline analysis deployment"),
 ("4960","all surfaces inherit the governed-fact contract"),
]
rk = ['<h3>Reference Numerals</h3>',
      '<table><thead><tr><th>No.</th><th>Element</th><th>No.</th><th>Element</th></tr></thead><tbody>']
half = (len(REFS) + 1)//2
for i in range(half):
    a = REFS[i]; b = REFS[i+half] if i+half < len(REFS) else ("","")
    rk.append(f'<tr><td>{a[0]}</td><td>{esc(a[1])}</td><td>{b[0]}</td><td>{esc(b[1])}</td></tr>')
rk.append('</tbody></table>')
open("ppa_refkey.html", "w", encoding="utf-8").write("\n".join(rk))
print("generated %d figures + brief description + reference key" % len(FIGS))
