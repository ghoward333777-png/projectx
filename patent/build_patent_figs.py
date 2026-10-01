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
w, h = 720, 430
s = svg_open(w, h)
s += box(250, 16, 220, 34, ["Delta Acquisition Model"], "400")
s += box(40, 74, 250, 170, ["L1 foundation (reused)"], "410")
for i, t in enumerate(["Phonemic discrimination", "Prosodic sensitivity", "Morphological awareness",
                       "Communicative understanding", "Grammatical meta-knowledge", "Semantic inventory"]):
    s += label(56, 116 + i*20, "• " + t, 11)
s += arrow(290, 159, 340, 159)
s += box(340, 100, 200, 50, ["L2 delta detector", "(novel vs. shared)"], "420")
s += arrow(440, 150, 440, 176)
s += box(340, 176, 200, 54, ["Targeted training:", "novel phonemes / grammar /", "idioms / prosody"], "430")
s += arrow(540, 125, 590, 125)
s += box(560, 96, 140, 60, ["Multilingual", "semantic alignment", "(bridge L2→L1)"], "440")
s += box(40, 300, 660, 90, ["Acceleration flywheel"], "450")
s += label(60, 336, "Each further language generally needs a smaller delta (directional, not strictly monotonic).", 11)
s += box(60, 348, 300, 28, ["Negative-transfer detection & retraining"], "451")
s += line(360, 244, 360, 300)
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
w, h = 720, 360
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
w, h = 720, 500
s = svg_open(w, h)
s += box(200, 14, 320, 40, ["PROTOTYPE EMBODIMENT (Section VII)", "QueryBook Language Lab — Phases One & Two"], "700")
s += box(40, 78, 200, 60, ["Corpus source:", "bundled corpus / user", "text / fetched URL"], "710")
s += arrow(240, 108, 276, 108)
s += box(276, 78, 180, 60, ["Phase-One structural", "agent (scheduler,", "24×7)"], "720")
s += arrow(456, 108, 492, 108)
s += box(492, 70, 200, 150, ["Structural analyzer"], "730")
for i, (t, r) in enumerate([("Grapheme inventory", "731"), ("Rule-seeded G2P", "732"),
                            ("Syllabifier", "733"), ("Lexical stability", "734"),
                            ("Co-occurrence density", "735"), ("Prosody proxy", "736")]):
    s += label(505, 104 + i*18, "• " + t + "  (" + r + ")", 10.5)
s += arrow(392, 138, 392, 250)
s += box(276, 250, 180, 56, ["Fact Unit store", "(content-addressed,", "deduped, provenance)"], "740")
s += arrow(592, 220, 592, 250)
s += box(492, 250, 200, 56, ["Transition Gate metrics", "(4) → one-way latch"], "750")
s += numeral(505, 300, "751")
s += line(492, 278, 456, 278); s += arrow(456, 278, 456, 278)
s += box(40, 360, 660, 120, ["Phase agents on shared agent manager"], "760")
s += box(60, 400, 150, 60, ["Phase 1", "structural", "IMPLEMENTED"], "761")
s += box(230, 400, 150, 60, ["Phase 2 semantic", "grounding (dictionary", "+ store) IMPLEMENTED"], "762")
s += box(400, 400, 150, 60, ["Phase 3 multilingual", "delta —", "declines (spec-only)"], "763")
s += box(560, 400, 120, 60, ["Phase 4 speech", "— declines", "(spec-only)"], "764")
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
w, h = 720, 720
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
