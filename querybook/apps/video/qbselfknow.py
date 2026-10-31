"""qbselfknow — the Self-Knowledge Layer (SKL): QueryBook's accurate self-description, with sources.

QueryBook describes itself only from three verified layers, never from generated text:
  * the specification — the sections of the Core Technology Overview (the Bible's detailed description), by number;
  * the implementation — for each section and each reasoning aspect, the module and symbol that implement it, checked
    against the program's own source files every time it is asked (a claim whose code is missing is reported as a
    contradiction, never repeated);
  * the evidence — the host application's own checks (self-test, diagnostics, measured scores), when it passes them in.

Every statement carries one of five labels — built and tested / partly built / specified, not yet built / not planned
(by design) / not in this application — and its sources (file and symbol, Overview section). Nothing specified is ever
described as built. The layer reads source files as text (it imports nothing it describes), so it is fast, deterministic
and safe; it never reads keys or settings, and a disclosure filter removes anything that looks like a secret.

The same file runs in QueryBook 9.64 (as qb_selfknow.py) and in the applications' shared core (as qbselfknow.py);
`codebase()` tells them apart. Standard library only. No AI model.
"""
import os, re

VERSION = "1.0.0"
HERE = os.path.dirname(os.path.abspath(__file__))

LABEL = {"built": "built and tested", "partial": "partly built", "specified": "specified, not yet built",
         "not_planned": "not planned (by design)", "absent": "not in this application", "descriptive": "description, not a capability"}
LEVELS = ("brief", "user", "engineer")

# ------------------------------------------------------------------------------------------------ the specification
# Core Technology Overview v15 (v14 addendum, October 8, 2026, plus Section 56): every numbered section.
SECTIONS = [
    (1, "The Fact Unit"), (1.5, "The Fact Unit Language"), (2, "What QueryBook Is and Is Not"), (3, "Neuromorphic Cognitive Layer (NCL) and Retrieval Stabilization"),
    (4, "Cross-Domain Consistency"), (5, "Confidence Calibration"), (6, "Deterministic Provenance"), (7, "Multimodal Ingestion"),
    (7.1, "Multi-Language and Translation Capability"), (8, "License-Scoped Query Restriction"), (9, "Live Interaction Voice Signal Analysis"),
    (10, "The Prime Directive"), (11, "World-View Model (WVM)"), (12, "Fact Unit Example"), (13, "Encryption and Access Control"),
    (14, "External System Integration — Directed Delegation"), (15, "Moderation Appeals"), (16, "Data Export and Portability"),
    (17, "Accessibility Suite"), (18, "Offline and Synchronized Operation"), (19, "Contextual Commerce Layer"), (20, "Ontology Mesh"),
    (21, "Predictive Cognitive Architecture (PCA)"), (22, "Domain and Layer Architecture"), (23, "Reasoning Mode Formalization"),
    (24, "The Interpretive Layer"), (25, "Expressive Register and Surface Realization"), (26, "Outcome Feedback and Operational Calibration"),
    (27, "Temporal Prediction Calibration"), (28, "Behavioural Probing and Analysis Quarantine"), (29, "Systematic Trial Architecture"),
    (30, "Programmatic Interfaces, Plugins and Versioning"), (31, "Interaction Surfaces"), (32, "Deployment Topology and Module Replacement"),
    (33, "Directed Capture Equipment Control"), (35, "Attractor Stabilization Beyond Retrieval"), (36, "Differentiated Propagation and Tri-Temporal Scope"),
    (37, "Coherence and the Context Lock"), (38, "Observation Diversity"), (39, "Computational Substrate Output as an Ingested Modality"),
    (40, "The AI-Engine Ingestion Module"), (41, "Exemplary Embodiments"), (42, "Comparison With Human Cognition"), (43, "Specialized Live Data Feeds"),
    (44, "Media Transformation: Compression, Expansion and Restoration"), (45, "Three-Dimensional and Immersive Presentation"),
    (46, "Robotic and Equipment Applications"), (47, "External Connections"), (48, "Analytical Applications and the Continuous Query Engine"),
    (49, "Defined Agents"), (50, "Open Claw Ingestion — Arbitrary Artefact Ingestion"), (51, "On-Chain Certification and Provenance NFTs"),
    (52, "Agent Protection and Deception Layer"), (53, "Tamper-Evident Security Record"), (54, "Agent Interoperability: The Model Context Protocol and OpenClaw"),
    (55, "Hybrid Transport: UFCS-FQL over TCP/IP"), (56, "The Self-Knowledge Layer (SKL)"),
]

# ------------------------------------------------------------------------------------------------ the implementation
# Evidence is (file, text that must appear in it). For QueryBook 9.64 files are relative to its folder; for the
# applications they are relative to the folder that holds the applications (language/, stem/, facts/, control/ — or
# QueryBook-Language/ … in the suite), with "*/" meaning "this application's own copy of the shared core".
# Per section: v964 = (status, evidence, note), apps = (status, evidence, note).
S = "specified"
COVERAGE = {
    1: (("partial", [("ufcs_store.py", "def fuid("), ("ufcs_store.py", "def make_packet(")],
         "Fact Units with a deterministic identifier, semantic fingerprint, sources, ingestion time, safety class and access list. Confidence is still a single trust score: the two-parameter (supporting / contradicting evidence) confidence, the governed predicate catalogue and the supersession chain are specified."),
        ("partial", [("*/qbcommons.py", "fingerprint")], "The Commons stores facts with their source and a fingerprint; the full Fact Unit record is in QueryBook 9.64.")),
    1.5: ((S, [], "The Fact Unit Language is specified."), (S, [], "")),
    2: (("descriptive", [], ""), ("descriptive", [], "")),
    3: ((S, [], "No neuromorphic or attractor code exists yet."), (S, [], "")),
    4: (("partial", [("qb_middleware.py", "contradict")], "Claims are checked against the store (corroborated / contradicted / open); cross-domain consistency rules are specified."),
        ("partial", [("*/qbcommons.py", "contradict")], "The Commons flags contradicting facts.")),
    5: ((S, [], "Calibration of confidence against outcomes is specified."), (S, [], "")),
    6: (("built", [("qb_integrity.py", "hash-chained")], "A local, hash-chained provenance ledger with seals."),
        ("partial", [("*/qbharvest.py", "policy")], "Every harvested fact keeps its source under the approved-source policy registry.")),
    7: (("partial", [("qb_openclaw.py", "def "), ("qb_audio.py", "def ")], "Text, web pages, 40+ file formats (Open Claw) and audio; image and video understanding are partial."),
        ("built", [("*/qbagents.py", "sense"), ("*/qbartifact.py", "def ")], "Agents take in text, sound, video, live data, touch and body motion; any file is read into addressable segments.")),
    7.1: (("partial", [("qb_agents.py", '"lang_multilingual"')], "Dictionary-based delta acquisition for Spanish and French."),
          ("partial", [("language/app.py", "lang")], "The Language Builder teaches several languages with speech.")),
    8: (("built", [("qb_rights.py", "def ")], "A local licence registry and rights-aware access gate."), ("absent", [], "In QueryBook 9.64.")),
    9: (("built", [("qb_pil.py", "def "), ("qb_audio.py", "def ")], "Deterministic acoustic features, voiceprint (consent-gated) and paralinguistic estimates."),
        ("built", [("language/speechlab.py", "def ")], "The Speech Lab measures pronunciation and voice.")),
    10: (("built", [("qb_chat.py", "never states a fact")], "The model never states a fact it did not retrieve from the store; it refuses instead."),
         ("built", [("*/qbagents.py", "LLM")], "No AI model asserts facts in the applications; agents are rule-based.")),
    11: ((S, [], "No world-view model or hypergraph code exists yet."), (S, [], "")),
    12: (("descriptive", [], ""), ("descriptive", [], "")),
    13: (("partial", [("ufcs_store.py", '"acl"')], "Every Fact Unit carries a safety class and access list; encryption at rest is specified."),
         ("partial", [("*/qbcore.py", "passphrase")], "Admin actions need the admin passphrase.")),
    14: ((S, [], ""), (S, [], "")),
    15: ((S, [], ""), (S, [], "")),
    16: (("partial", [("ufcs_store.py", "export")], "The store can be exported."), ("partial", [("*/qbcore.py", "backup")], "Every database is backed up and can be copied out.")),
    17: (("partial", [("qb_help.py", "def ")], "Plain-English help and voice output."), ("partial", [("language/tts.py", "def ")], "Spoken output.")),
    18: (("built", [("qb_mirror.py", "def ")], "Runs entirely offline on one computer; mirrors the store to an external drive."),
         ("built", [("*/qbcore.py", "def ")], "Each application runs offline on this computer; online sources are optional.")),
    19: ((S, [], ""), (S, [], "")),
    20: (("partial", [("qb_ontology.py", "def ")], "A concept graph built from Fact-Unit triples; the poly-hierarchical mesh and open/closed-world reasoning are specified."), (S, [], "")),
    21: ((S, [], "No predictive or prediction-error code exists yet."), (S, [], "")),
    22: ((S, [], ""), (S, [], "")),
    23: (("built", [("qb_agents.py", '"reasoning"')], "Deduction asserts (transitive closure over verified premises, each derived fact carrying its premises, trust decaying per hop); induction and abduction only propose."),
         ("absent", [], "In QueryBook 9.64.")),
    24: (("partial", [("qb_query.py", "def understand")], "Deterministic entity, predicate, intent and scope extraction."), (S, [], "")),
    25: ((S, [], ""), (S, [], "")),
    26: (("partial", [("qb_agents.py", '"watch"')], "The watch agent records when an answer changes as new facts arrive."),
         ("built", [("language/qualitylab.py", "def "), ("language/ui/review.js", "rvImprove"), ("*/qbengineer.py", "approve")],
          "Measured feedback loops: the Quality Lab, the delivery check with user flags, the calibration bench, and the Engineer's record of what the admin approves.")),
    27: ((S, [], ""), (S, [], "")),
    28: ((S, [], "Hypotheses and simulations are kept in isolated low-trust domains; behavioural-probing quarantine is specified."), (S, [], "")),
    29: ((S, [], ""), ("partial", [("language/ui/bench.js", "bnScore")], "The calibration bench runs controlled trials of a calibration against a reference clip.")),
    30: (("partial", [("qb_api.py", "/api/features")], "A documented local HTTP API; plugins and versioned interfaces are partial."),
         ("partial", [("*/qbcore.py", "/api/")], "Each application has a local HTTP API.")),
    31: (("built", [("chat.html", "<"), ("voice.html", "<"), ("console.html", "<")], "Chat, voice, console, dashboards and learner pages."),
         ("built", [("*/ui/index.html", "<")], "A web page per application and the Control Panel.")),
    32: (("partial", [("qb_editions.py", "def "), ("qb_embodiment.py", "def ")], "Light / medium / full editions and embodiments of one engine."), (S, [], "")),
    33: ((S, [], ""), ("partial", [("*/qbdevices.py", "camera")], "The device gateway takes in cameras, phones, glasses and robots; directed control is partial.")),
    35: ((S, [], ""), (S, [], "")),
    36: (("partial", [("ufcs_store.py", '"ingested"')], "Facts carry their ingestion time; the full tri-temporal scope is specified."), (S, [], "")),
    37: ((S, [], ""), (S, [], "")),
    38: ((S, [], ""), (S, [], "")),
    39: ((S, [], ""), ("partial", [("stem/science.py", "def ")], "Deterministic formulas and reference data in the STEM application.")),
    40: (("partial", [("qb_web_harvest.py", "extractor"), ("qb_gemini.py", "def ")], "An optional AI extractor and a renderer adapter; extracted claims are verified, never asserted directly."),
         ("absent", [], "In QueryBook 9.64.")),
    41: (("descriptive", [], ""), ("descriptive", [], "")),
    42: (("descriptive", [], ""), ("descriptive", [], "")),
    43: (("partial", [("qb_web_harvest.py", "robots")], "A polite, domain-scoped web harvester."),
         ("built", [("*/qbonline.py", "def ")], "Online harvesters for the sources the admin approved.")),
    44: ((S, [], ""), (S, [], "")),
    45: ((S, [], ""), ("partial", [("language/ui/face.js", "VR")], "Talking faces in 2D, 3D and VR.")),
    46: ((S, [], ""), ("partial", [("bridges/ros2_bridge.py", "ROS 2")], "Robots and sensors report observations through bridges; control is not built.")),
    47: (("partial", [("qb_mcp.py", "def ")], "MCP tool server."), ("partial", [("*/gcloud.py", "def ")], "Google Cloud services (speech, storage, monitoring) with the user's own key.")),
    48: (("partial", [("qb_agents.py", "Continuous Query")], "The watch agent is a light continuous query."),
         ("partial", [("*/qbagents.py", "def ")], "Agents run on a schedule and report changes.")),
    49: (("built", [("qb_agents.py", "ROLES")], "Defined agent roles; roadmap roles refuse rather than fabricate."),
         ("built", [("*/qbagents.py", "def ")], "The agent hub: agents you pick, LLM-free.")),
    50: (("built", [("qb_openclaw.py", "def ")], ""), ("built", [("*/qbartifact.py", "def ")], "Carried over from QueryBook 9.64.")),
    51: (("built", [("qb_nft.py", "def ")], ""), ("absent", [], "In QueryBook 9.64.")),
    52: (("built", [("qb_shield.py", "def "), ("qb_decoy.py", "def ")], ""), ("absent", [], "In QueryBook 9.64.")),
    53: (("built", [("qb_seclog.py", "def ")], ""), ("absent", [], "In QueryBook 9.64.")),
    54: (("built", [("qb_mcp.py", "def ")], ""), ("absent", [], "In QueryBook 9.64.")),
    55: ((S, [], ""), (S, [], "")),
    56: (("built", [("qb_selfknow.py", "def describe(")], "This layer."), ("built", [("*/qbselfknow.py", "def describe(")], "This layer.")),
}

# ------------------------------------------------------------------------------------------------ reasoning aspects
# How QueryBook reasons, aspect by aspect: the words people use to ask, the Overview sections, the status in each
# codebase with its evidence, and what to say at three levels of detail.
ASPECTS = [
    {"id": "deterministic", "name": "Deterministic reasoning", "words": r"determinis\w*|reproducib\w*|same (?:answer|result)|random",
     "sections": [6, 1], "v964": ("built", [("ufcs_store.py", "def fuid("), ("ufcs_store.py", "def fingerprint(")]),
     "apps": ("built", [("*/qbcore.py", "def "), ("language/vse.py", "_rng")]),
     "say": {"brief": "The same inputs always give the same result.",
             "user": "Facts get identifiers computed from their content and source, so the same fact always gets the same identity, and every rule I apply is fixed code, not a guess.",
             "engineer": "FUIDs and semantic fingerprints are SHA-256 over the canonicalised triple, source and ingestion time; generators and engines are seeded or rule-based; the self-tests assert identical output for identical input."}},
    {"id": "atomic", "name": "Atomic knowledge (the Fact Unit)", "words": r"atomic|fact units?|smallest unit|atom",
     "sections": [1, 12], "v964": ("partial", [("ufcs_store.py", "def make_packet(")]), "apps": ("partial", [("*/qbcommons.py", "fingerprint")]),
     "say": {"brief": "I store knowledge as single, sourced facts.",
             "user": "Each fact I keep says exactly one thing, with its source, when it was taken in, how far I trust it and who may see it. Confidence is still one trust score; the two-part confidence (evidence for and against) in my design is not built yet.",
             "engineer": "make_packet(): nucleus (subject, predicate, object), polarity, FUID, semantic fingerprint, sources, certification, temporal.ingested, safety + ACL. Missing against §1.1: Beta-pair confidence, source-class diversity, governed predicate catalogue validation, supersession chain."}},
    {"id": "world_model", "name": "World model", "words": r"world[- ]?(?:view|model)|wvm|hypergraph|model of the world",
     "sections": [11], "v964": ("specified", []), "apps": ("specified", []), "absent_needles": ["class WorldView", "def world_view", "class Hypergraph", "def hypergraph"],
     "say": {"brief": "My World-View Model is designed but not built yet.",
             "user": "My design (Overview §11) specifies a World-View Model: a hypergraph of concepts with concept formation and selective attention. It is not implemented in this version; today I answer from my fact store and concept graph.",
             "engineer": "Specified in §11.1–11.4; no hypergraph, concept-formation or attention code exists. Nearest built component: qb_ontology concept graph (§20, partial)."}},
    {"id": "predictive", "name": "Predictive cognition", "words": r"predict\w*|forecast\w*|anticipat\w*|pca\b",
     "sections": [21, 27], "v964": ("specified", []), "apps": ("specified", []), "absent_needles": ["def prediction_error", "class PredictiveCognitive", "def predictive_cognitive"],
     "say": {"brief": "Predictive cognition is designed but not built yet.",
             "user": "My design (Overview §21 and §27) specifies a Predictive Cognitive Architecture and calibration of my predictions over time. It is not implemented in this version, so I do not make predictions.",
             "engineer": "§21 (eight mechanisms, four additions, three amplifications) and §27 are specified; no prediction or prediction-error code exists."}},
    {"id": "neuromorphic", "name": "Neuromorphic layer", "words": r"neuro\w*morphic|neomorphic|ncl\b|attractor|spiking|brain[- ]like",
     "sections": [3, 35], "v964": ("specified", []), "apps": ("specified", []), "absent_needles": ["class Neuromorphic", "def neuromorphic", "def attractor", "class Attractor"],
     "say": {"brief": "My Neuromorphic Cognitive Layer is designed but not built yet.",
             "user": "My design (Overview §3 and §35) specifies a Neuromorphic Cognitive Layer that stabilises retrieval with attractor dynamics. It is not implemented in this version; retrieval today is deterministic look-up.",
             "engineer": "§3 NCL and §35 attractor stabilization are specified; no neuromorphic or attractor code exists."}},
    {"id": "hypothesis", "name": "Hypothesis generation", "words": r"hypothes\w*|conjectur\w*|propose (?:a )?(?:fact|idea)|creative",
     "sections": [23, 29], "v964": ("built", [("qb_agents.py", '"hypothesis"')]), "apps": ("absent", []),
     "say": {"brief": "I can propose hypotheses, but I never assert them.",
             "user": "My hypothesis agent asks an AI model to propose candidate facts, then checks each against my verified store as corroborated, contradicted or open. Hypotheses are kept apart at low trust and are never stated as fact. It needs an AI provider.",
             "engineer": "qb_agents ROLES['hypothesis']: LLM-proposed, store-verified, stored isolated in the 'hypothesis' domain at low trust; non-asserting by construction."}},
    {"id": "simulation", "name": "Simulation", "words": r"simulat\w*|what[- ]if|scenario|counterfactual",
     "sections": [29], "v964": ("built", [("qb_agents.py", '"simulation"')]), "apps": ("absent", []),
     "say": {"brief": "I can explore scenarios, but the results are never stated as fact.",
             "user": "My simulation agent asks an AI model for plausible consequences of a scenario, checks each against my verified store, and keeps them apart at low trust. It needs an AI provider. A full systematic-trial architecture (§29) is specified.",
             "engineer": "qb_agents ROLES['simulation']: LLM-projected consequences, store-verified, isolated 'simulation' domain; §29 Systematic Trial Architecture otherwise specified."}},
    {"id": "deduction", "name": "Reasoning (deduction, induction, abduction)", "words": r"reason\w*|deduc\w*|induc\w*|abduc\w*|infer\w*|logic",
     "sections": [23], "v964": ("built", [("qb_agents.py", '"reasoning"')]), "apps": ("absent", []),
     "say": {"brief": "I deduce new facts only from verified ones, and show how.",
             "user": "Deduction derives new facts from verified premises and keeps both premises as its evidence, with trust falling at each step. Induction and abduction only propose; they never assert.",
             "engineer": "qb_agents 'reasoning': transitive deductive closure over VERIFIED premises, derived facts carry two-premise provenance, trust decays per hop; induction/abduction are non-asserting."}},
    {"id": "feedback", "name": "Feedback loops", "words": r"feedback|loop|calibrat\w*|learn from (?:mistakes|results)|outcome",
     "sections": [26, 27], "v964": ("partial", [("qb_agents.py", '"watch"')]),
     "apps": ("built", [("language/qualitylab.py", "def "), ("language/ui/review.js", "rvImprove"), ("language/ui/bench.js", "bnScore"),
                        ("*/qbexemplar.py", "def best(")]),
     "say": {"brief": "I measure my results and propose corrections; a person approves them.",
             "user": "I measure what I produce against references (the Quality Lab, the delivery check, your flags, the calibration bench), propose a better calibration, and change nothing until the admin approves it.",
             "engineer": "qualitylab candidates + approvals; review.js delivery check / flags / rvImprove coordinate search; bench.js trials vs reference; qbexemplar keeps best-in-class examples (measured by QueryBook, approved by the admin, never facts); qbengineer learns from approve/reject counts. §26 outcome feedback in full and §27 are specified."}},
    {"id": "self_improvement", "name": "Supervised self-improvement", "words": r"self[- ]?improv\w*|improve (?:your|it)self|fix (?:your|it)self|self[- ]?modif\w*|engineer",
     "sections": [26], "v964": ("absent", []), "apps": ("built", [("*/qbengineer.py", "without the admin passphrase")]),
     "say": {"brief": "I improve myself only with a person's approval.",
             "user": "The Engineer reads my own program, proposes fixes with evidence, tests each change on a copy against my whole self-test, and applies nothing until the admin approves. Approved changes can be reverted in one click.",
             "engineer": "qbengineer: AST/JS analysis skills, unified-diff patches, copy + compile + full self-test before apply, backups, revert; approval-weighted skill ranking; three rejections mute a skill."}},
    {"id": "rsi", "name": "Recursive self-improvement", "words": r"recursive|\brsi\b|improve (?:itself|yourself) without|unsupervised improvement|self[- ]?evolv\w*",
     "sections": [10], "v964": ("not_planned", []), "apps": ("not_planned", []),
     "say": {"brief": "No: I do not change myself without a person's approval, by design.",
             "user": "Recursive self-improvement — changing my own program without a person in the loop — is excluded by design. I propose improvements with evidence; the admin decides. This follows my Prime Directive and approval gates.",
             "engineer": "No autonomous code modification path exists: qbengineer and the Quality Lab require the admin passphrase; every applied change is self-tested, backed up and revertible."}},
    {"id": "self_knowledge", "name": "Self-knowledge", "words": r"self[- ]?knowledge|know (?:about )?yourself|describe yourself|how do you know (?:what you can|yourself)|skl\b",
     "sections": [56], "v964": ("built", [("qb_selfknow.py", "def describe(")]), "apps": ("built", [("*/qbselfknow.py", "def describe(")]),
     "say": {"brief": "I describe myself only from what I can verify in my own program.",
             "user": "Everything I say about myself comes from my design document, checked against my own program files and my own tests. Each statement says whether it is built, partly built, specified or not planned, and where it comes from.",
             "engineer": "qbselfknow: SECTIONS (Overview) × COVERAGE (file, needle evidence) × host checks; consistency() reports any claim whose evidence is missing; gaps() lists unbuilt sections; answers carry labels and sources."}},
]

PROCESS = [
    ("Ingest", "text, web pages, files (40+ formats), sound, video, sensors and devices are read deterministically", [7, 50, 43]),
    ("Atomise", "each assertion becomes one Fact Unit with its source, time, trust, safety class and access list", [1]),
    ("Verify", "new claims are checked against the store: corroborated, contradicted or open; AI-proposed content stays apart at low trust", [4, 10, 40]),
    ("Store", "facts are kept immutable with a hash-chained provenance record", [6, 53]),
    ("Reason", "deduction over verified premises asserts; induction, abduction, hypotheses and simulations only propose", [23, 29]),
    ("Answer", "every answer cites its facts, or I refuse rather than guess", [10, 31]),
    ("Measure", "results are measured against references and the program tests itself", [26, 56]),
    ("Improve", "corrections are proposed with evidence and applied only with the admin's approval", [26]),
]

SECRET = re.compile(r"(AIza[0-9A-Za-z_\-]{20,}|AQ\.[0-9A-Za-z_\-]{20,}|sk-[0-9A-Za-z_\-]{16,}|ghp_[0-9A-Za-z]{20,}|qbd_[0-9A-Za-z]{8,}|-----BEGIN [A-Z ]+KEY-----)")


# ------------------------------------------------------------------------------------------------ evidence checks
def codebase(here=HERE):
    """'v964' when running inside QueryBook 9.64 (its feature manifest sits beside this file), else 'apps'."""
    return "v964" if os.path.exists(os.path.join(here, "qb_features.py")) else "apps"


def _apps_root(here):
    """the folder holding the applications: this file is in <root>/<app>/ or <root>/_core/"""
    return os.path.dirname(here)


_APP_DIRS = {"language": ("language", "QueryBook-Language"), "stem": ("stem", "QueryBook-STEM"), "facts": ("facts", "QueryBook-History-News"),
             "control": ("control", "QueryBook-Control-Panel"), "bridges": ("bridges",)}


def _resolve(rel, cb, here):
    if cb == "v964":
        return [os.path.join(here, rel)]
    if rel.startswith("*/"):                      # this application's own file (from the master copy: any application's)
        root = _apps_root(here)
        return [os.path.join(here, rel[2:])] + [os.path.join(root, d, rel[2:]) for ds in _APP_DIRS.values() for d in ds]
    head, _, tail = rel.partition("/")
    root = _apps_root(here)
    return [os.path.join(root, d, tail) for d in _APP_DIRS.get(head, (head,))]


_cache = {}


def _read(path):
    if path not in _cache:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                _cache[path] = f.read()
        except OSError:
            _cache[path] = None
    return _cache[path]


def check(evidence, cb=None, here=HERE):
    """each (file, needle): found where? -> list of {file, needle, found, line}"""
    cb = cb or codebase(here)
    out = []
    for rel, needle in evidence:
        hit = None
        for p in _resolve(rel, cb, here):
            t = _read(p)
            if t is not None and needle in t:
                hit = (os.path.basename(os.path.dirname(p)) + "/" + os.path.basename(p) if cb == "apps" else rel, t[:t.index(needle)].count("\n") + 1)
                break
        out.append({"file": hit[0] if hit else rel.replace("*/", ""), "needle": needle, "found": bool(hit), "line": hit[1] if hit else None})
    return out


def section_title(n):
    return next((t for k, t in SECTIONS if k == n), "")


def _sec(n):
    return "§%s %s" % (("%g" % n), section_title(n))


# ------------------------------------------------------------------------------------------------ the layer
def describe(aspect_id, level="user", cb=None, here=HERE):
    """one reasoning aspect: its label, what to say at the chosen level, sources (checked now), Overview sections"""
    a = next(x for x in ASPECTS if x["id"] == aspect_id)
    cb = cb or codebase(here)
    status, ev = a[cb]
    srcs = check(ev, cb, here)
    verified = all(s["found"] for s in srcs) if status in ("built", "partial") else True
    text = a["say"].get(level if level in LEVELS else "user")
    if status == "absent":
        text = "Not in this application: %s is part of QueryBook 9.64. %s" % (a["name"].lower(), a["say"]["brief"])
    if not verified:
        text = "I cannot confirm this: the code that should implement it was not found. " + text
    return {"id": a["id"], "name": a["name"], "status": status, "label": LABEL[status], "text": _filter(text), "verified": verified,
            "sources": srcs, "sections": [_sec(n) for n in a["sections"]]}


def sections(cb=None, here=HERE):
    """every Overview section with its status in this codebase and its evidence, checked now"""
    cb = cb or codebase(here)
    rows = []
    for n, title in SECTIONS:
        v, ap = COVERAGE.get(n, ((S, [], ""), (S, [], "")))
        status, ev, note = v if cb == "v964" else ap
        srcs = check(ev, cb, here)
        rows.append({"section": "%g" % n, "title": title, "status": status, "label": LABEL[status], "note": note, "sources": srcs,
                     "verified": all(s["found"] for s in srcs) if status in ("built", "partial") else True})
    return rows


def consistency(cb=None, here=HERE):
    """contradictions between what the layer would say and the program as it is: a built/partial claim whose evidence is
    missing, or a 'specified' aspect for which implementing code has appeared (the description is out of date)"""
    cb = cb or codebase(here)
    issues = []
    for r in sections(cb, here):
        if not r["verified"]:
            issues.append("§%s %s is described as %s, but %s" % (r["section"], r["title"], r["label"],
                          "; ".join("%s lacks '%s'" % (s["file"], s["needle"]) for s in r["sources"] if not s["found"])))
    for a in ASPECTS:
        d = describe(a["id"], "brief", cb, here)
        if not d["verified"]:
            issues.append("%s is described as %s, but its code was not found" % (a["name"], d["label"]))
        if a[cb][0] == "specified":
            for needle in a.get("absent_needles", []):
                found = _search_tree(needle, cb, here)
                if found:
                    issues.append("%s is described as specified, but '%s' now appears in %s — update its status" % (a["name"], needle, found))
    for s in SECTIONS:
        if s[0] not in COVERAGE:
            issues.append("§%g has no coverage entry" % s[0])
    return issues


def _search_tree(needle, cb, here):
    roots = [here] if cb == "v964" else [os.path.join(_apps_root(here), d) for d in os.listdir(_apps_root(here))]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if d not in ("vendor", "node_modules", "__pycache__", "dist", "espeak")]
            for f in fn:
                if f.endswith((".py", ".js")) and not f.startswith(("qbselfknow", "qb_selfknow")):
                    t = _read(os.path.join(dp, f))
                    if t and needle in t:
                        return os.path.relpath(os.path.join(dp, f), os.path.dirname(root))
    return None


def gaps(cb=None, here=HERE):
    """the learning agenda: what the design specifies that this codebase has not built, then what is only partly built"""
    rows = sections(cb, here)
    return {"specified": [{"section": r["section"], "title": r["title"]} for r in rows if r["status"] == "specified"],
            "partial": [{"section": r["section"], "title": r["title"], "note": r["note"]} for r in rows if r["status"] == "partial"]}


def summary(cb=None, here=HERE, checks=None):
    """the whole self-description: counts by label, the aspects, the process, the gaps and the consistency report.
    checks: the host's own evidence (e.g. {"self-test": "215 of 215 passed"}), shown as given."""
    cb = cb or codebase(here)
    rows = sections(cb, here)
    counts = {}
    for r in rows:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    return {"layer": "Self-Knowledge Layer (SKL)", "version": VERSION, "codebase": "QueryBook 9.64" if cb == "v964" else "QueryBook applications",
            "counts": counts, "aspects": [describe(a["id"], "user", cb, here) for a in ASPECTS], "sections": rows,
            "process": [{"step": s, "what": w, "sections": [_sec(n) for n in ns]} for s, w, ns in PROCESS],
            "gaps": gaps(cb, here), "contradictions": consistency(cb, here), "evidence": checks or {},
            "rule": "Every statement is labelled and sourced; nothing specified is described as built."}


# ------------------------------------------------------------------------------------------------ talking about itself
INTENTS = [
    ("capabilities", r"what can you do|your (?:capabilit\w*|abilities|features)|what are you able|what do you do"),
    ("limits", r"what can'?t you|what (?:are|is) (?:not|missing)|limit\w*|weak\w*|not (?:yet )?built|what don'?t you|gaps?|learning agenda|what next"),
    ("process", r"how do you (?:work|think|reason|answer)|your (?:process|pipeline|architecture)|how are you (?:built|made)"),
    ("whatis", r"what are you|who are you|what is querybook|tell me about (?:yourself|querybook)|describe yourself"),
    ("honesty", r"(?:do|can) you (?:lie|hallucinat\w*|make (?:things|stuff) up|invent)|how do (?:i|we) know (?:you'?re|this is) (?:true|right|accurate)"),
]


def _filter(text):
    """disclosure filter: never let anything that looks like a key, token or private key out"""
    return SECRET.sub("[withheld]", text)


def _section_ref(q):
    m = re.search(r"(?:§|section|sec\.?)\s*(\d{1,2}(?:\.\d)?)", q, re.I)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def answer(question, level="user", cb=None, here=HERE, checks=None):
    """a question about QueryBook itself -> {answer, label, sources, sections}. Rule-based: it recognises aspects, Overview
    sections and a few general questions; anything else gets an honest 'I can only answer about …'."""
    cb = cb or codebase(here)
    q = (question or "").strip()
    ql = q.lower()
    level = level if level in LEVELS else "user"
    n = _section_ref(q)
    if n is not None and any(k == n for k, _ in SECTIONS):
        r = next(x for x in sections(cb, here) if float(x["section"]) == n)
        src = "; ".join("%s (%s, line %s)" % (s["file"], s["needle"], s["line"]) for s in r["sources"] if s["found"])
        return _out("§%s %s: %s.%s" % (r["section"], r["title"], r["label"], (" " + r["note"]) if r["note"] else ""), r["label"], r["sources"], ["§" + r["section"]], src)
    hits = [a for a in ASPECTS if re.search(a["words"], ql)]
    if hits:
        parts, srcs, secs, labels = [], [], [], []
        for a in hits[:3]:
            d = describe(a["id"], level, cb, here)
            parts.append("%s — %s. %s" % (d["name"], d["label"], d["text"]))
            srcs += d["sources"]; secs += d["sections"]; labels.append(d["label"])
        src = "; ".join("%s (%s)" % (s["file"], s["needle"]) for s in srcs if s["found"])
        return _out(" ".join(parts), ", ".join(dict.fromkeys(labels)), srcs, secs, src)
    intent = next((i for i, pat in INTENTS if re.search(pat, ql)), None)
    rows = sections(cb, here)
    if intent == "capabilities":
        built = [r for r in rows if r["status"] == "built"]
        return _out("Built and tested in this codebase: " + "; ".join("§%s %s" % (r["section"], r["title"]) for r in built) +
                    ". Partly built: %d sections. Specified but not yet built: %d sections — ask \"what can't you do?\"." %
                    (sum(r["status"] == "partial" for r in rows), sum(r["status"] == "specified" for r in rows)), "summary",
                    [s for r in built for s in r["sources"]], ["§" + r["section"] for r in built], "Overview sections checked against the program now")
    if intent == "limits":
        g = gaps(cb, here)
        return _out("Specified in my design but not built yet: " + "; ".join("§%s %s" % (x["section"], x["title"]) for x in g["specified"]) +
                    ". Partly built: " + "; ".join("§%s %s" % (x["section"], x["title"]) for x in g["partial"]) + ".", "learning agenda", [],
                    ["§" + x["section"] for x in g["specified"]], "the gap report")
    if intent == "process":
        return _out(" → ".join("%s: %s" % (s, w) for s, w, _ in PROCESS) + ".", "built (process as implemented)", [],
                    sorted({_sec(n) for _, _, ns in PROCESS for n in ns}), "the process map")
    if intent == "honesty":
        d = describe("self_knowledge", level, cb, here)
        return _out("I do not describe myself from memory or imagination. " + d["text"] + " Ask about any part — for example \"are you neuromorphic?\" or \"section 21\".",
                    d["label"], d["sources"], d["sections"], "the Self-Knowledge Layer")
    if intent == "whatis":
        c = summary(cb, here, checks)["counts"]
        return _out("I am QueryBook: a deterministic, provenance-tracked knowledge system built from atomic Fact Units, which answers with citations "
                    "or refuses. Of the %d sections of my design, %s." % (len(SECTIONS), ", ".join("%d %s" % (v, k) for k, v in c.items())),
                    "summary", [], ["§2 " + section_title(2)], "Overview §2 and the section count, checked now")
    return _out("I can only describe myself from verified records. Ask about an aspect (deterministic, atomic facts, world model, predictive, "
                "neuromorphic, hypothesis, simulation, reasoning, feedback, self-improvement, recursive self-improvement, self-knowledge), "
                "about a section of my design (\"section 21\"), or \"what can you do?\" / \"what can't you do?\" / \"how do you work?\".",
                "—", [], [], "")


def _out(text, label, sources, secs, src_text):
    return {"answer": _filter(text), "label": label, "sources": [s for s in sources if s.get("found")], "sections": list(dict.fromkeys(secs)),
            "source_text": _filter(src_text)}


def self_test(here=HERE):
    """the layer's own checks: no contradictions; specified aspects are never called built; every aspect answer is labelled
    and sourced; secrets never pass the filter. Returns (passed, total, failures)."""
    cb = codebase(here)
    fails = []
    issues = consistency(cb, here)
    if issues:
        fails.append("contradictions: " + " | ".join(issues))
    for a in ASPECTS:
        d = describe(a["id"], "user", cb, here)
        if a[cb][0] == "specified" and "built" in d["label"].replace("not yet built", ""):
            fails.append(a["id"] + " specified but labelled built")
        if a[cb][0] in ("built", "partial") and not any(s["found"] for s in d["sources"]):
            fails.append(a["id"] + " has no source")
    r = answer("Are you neuromorphic?", cb=cb, here=here)
    if "not yet built" not in r["label"]:
        fails.append("neuromorphic not answered as specified: " + r["label"])
    r = answer("Can you improve yourself recursively?", cb=cb, here=here)
    if "not planned" not in r["label"]:
        fails.append("RSI not answered as not planned: " + r["label"])
    if "[withheld]" not in _filter("key AIza" + "x" * 30):
        fails.append("disclosure filter let a key through")
    total = 4 + 2 * len(ASPECTS)
    return total - len(fails), total, fails


# ------------------------------------------------------------------------------------------------ in an application
def add_routes(api, checks_fn=None):
    """GET /api/self — the whole self-description; GET /api/self/ask?q=…&level=brief|user|engineer — one answer"""
    ev = lambda: (checks_fn() if checks_fn else {})
    api.get("/api/self")(lambda q: summary(checks=ev()))
    api.get("/api/self/ask")(lambda q: answer(q.get("q") or "", q.get("level") or "user", checks=ev()))


def attach(app, app_id=None, version=None):
    """Give an application its Self-Knowledge Layer. Never stops the application if it cannot be added."""
    try:
        add_routes(app.api, lambda: {"application": app_id or getattr(app, "APP_ID", ""), "version": version or getattr(app, "VERSION", "")})
    except Exception as e:
        log = getattr(app, "log", None)
        if log:
            log("self-knowledge layer unavailable:", repr(e))


def qc(here=HERE):
    """QueryBook 9.64's module-check contract: {ok, passed, total, rows: [{check, pass}]}"""
    ok, total, fails = self_test(here)
    rows = [{"check": f, "pass": False} for f in fails] + [{"check": "self-knowledge check", "pass": True}] * ok
    return {"ok": not fails, "passed": ok, "total": total, "rows": rows}
