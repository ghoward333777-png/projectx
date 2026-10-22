"""The Self-Knowledge Layer (SKL): one source of wording for every QueryBook document.

The Core Technology Overview §56, the Bible, the provisional (FIG. 57, claims 358-362) and the Composite Feature
Registry v70 (features 383-391) are all generated from this file, so they say the same thing. The code it describes:
querybook/apps/_core/qbselfknow.py (applications) and querybook/QueryBook-v9.64/qb_selfknow.py (prototype v9.64).
"""
DATE = "October 22, 2026"
DATE_ISO = "2026-10-22"
CITE = "SKL 2026-10-22"
FIG = 57
FIG_TITLE = "Self-Knowledge Layer: Accurate Self-Description with Sources"
BUILT = "Built — prototype v9.64"
MODULE = "qb_selfknow (v9.64); qbselfknow (applications)"

# ------------------------------------------------------------------------------------------- Overview §56 / Bible
TITLE = "The Self-Knowledge Layer (SKL)"
INTRO = [
    "The Self-Knowledge Layer (SKL) is the part of QueryBook that describes QueryBook. Asked what it is, how it reasons, "
    "whether it is neuromorphic, whether it predicts, or whether it improves itself, the system answers from three verified "
    "layers and from nothing else: the specification (the numbered sections of this Overview), the implementation (the module "
    "and symbol that carry out each section, checked against the program's own source files at the moment of asking), and the "
    "evidence (the host application's own self-tests, diagnostics and measured scores). The layer never generates its "
    "self-description with a language model, and it never repeats a claim its own code does not support.",
    "The SKL follows from the Prime Directive (§10): a system that refuses to state an unsupported fact about the world must "
    "not state an unsupported fact about itself. It is the self-referential application of the Fact Unit discipline (§1) — every "
    "statement QueryBook makes about itself carries a status and its sources, exactly as a Fact Unit carries provenance.",
]
SUBSECTIONS = [
    ("56.1 Three layers of self-knowledge",
     ["Specification. Every numbered section of the Core Technology Overview (§1 through §56) is indexed by number and title. "
      "A self-question that names a capability is resolved to the sections that specify it.",
      "Implementation. For each section and each reasoning aspect, the layer holds evidence pairs — a source file and a symbol "
      "that must appear in it (for example, the function that computes Fact Unit identifiers). The pairs are checked against the "
      "running program's files every time they are used. The layer reads source files as text and imports nothing it describes, "
      "so the check is fast, deterministic and safe.",
      "Evidence. The host application may pass in its own check results (self-test, diagnostics, quality measurements); the "
      "layer reports them beside the code evidence."]),
    ("56.2 Capability status labels",
     ["Every statement carries exactly one of five labels: built and tested; partly built; specified, not yet built; not planned "
      "(by design); not in this application. A sixth marker, description, not a capability, is used for sections that describe "
      "rather than define behaviour (for example §42, Comparison With Human Cognition). A capability is labelled built only "
      "when all of its evidence is present; a specified capability is never described as built."]),
    ("56.3 The reasoning aspects",
     ["Twelve aspects of QueryBook reasoning are described at three levels of detail (brief, user, engineer), each with its "
      "status and sources: deterministic reasoning (§6, §1); atomic knowledge, the Fact Unit (§1, §12); the World-View Model "
      "(§11); predictive cognition (§21, §27); the neuromorphic layer (§3, §35); hypothesis generation and simulation (§23, §29); "
      "deduction, induction and abduction (§23); feedback loops (§26, §27); supervised self-improvement (§26); recursive "
      "self-improvement (§10); and self-knowledge itself (§56).",
      "In the present prototypes deterministic reasoning, deduction over verified premises, hypothesis and simulation agents "
      "(proposing only, kept apart at low trust), measured feedback loops and supervised self-improvement are built; the Fact "
      "Unit is partly built; the World-View Model, the Predictive Cognitive Architecture and the Neuromorphic Cognitive Layer "
      "are specified and not yet built. Recursive self-improvement — a change to the program without a person's approval — is "
      "not planned, by design: every calibration and every code change proposed by the Engineer is tested on a copy and "
      "applied only with the administrator's approval."]),
    ("56.4 The process model",
     ["The layer describes QueryBook's own process in eight steps, each tied to its sections: ingest (§7, §43, §50); atomise into "
      "Fact Units (§1); verify against the store, keeping AI-proposed content apart (§4, §10, §40); store immutably with a "
      "hash-chained record (§6, §53); reason, where only deduction asserts (§23, §29); answer with citations or refuse (§10, §31); "
      "measure against references (§26, §56); improve with approval (§26)."]),
    ("56.5 Self-consistency check",
     ["Before it speaks, the layer checks itself. A claim labelled built or partly built whose evidence is missing from the "
      "program is reported as a contradiction and is not repeated. A capability labelled specified whose implementation names "
      "(for example, an attractor or world-view class) appear in the program is also reported, so the description is updated "
      "when the code moves ahead of it. The check is part of every self-test."]),
    ("56.6 Gap agenda",
     ["Every section that is specified but not built, or only partly built, is listed with its number, title and nearest built "
      "component. The list is the system's development agenda: it says what QueryBook does not yet do, in the system's own words, "
      "and it is never presented as capability."]),
    ("56.7 Answering questions about itself",
     ["Self-questions (\"Are you neuromorphic?\", \"Do you improve yourself?\", \"What is §21?\") are matched by rule to an aspect "
      "or a section number and answered with the label and the sources: the section numbers and the file and symbol evidence. "
      "Answers are deterministic: the same question about the same program gives the same answer. A disclosure filter removes "
      "anything in an answer that resembles a key or credential, and the layer never reads settings or keys."]),
    ("56.8 Interfaces",
     ["The layer is available in prototype v9.64 and in each application (Language, STEM, History and News, Control Panel) as "
      "GET /api/self (summary, label counts, aspects, process, sections, contradictions, gaps) and GET /api/self/ask?q=…&level=… "
      "(one answer with its sources); as the Self-knowledge page in v9.64 and the Self-knowledge tab of the Control Panel; and as "
      "a rule of the Control Panel assistant."]),
    ("56.9 Status",
     ["The Self-Knowledge Layer is built and tested in prototype v9.64 (qb_selfknow.py, 1.0.0) and in the shared core of the "
      "applications (qbselfknow.py, 1.0.0). Its self-test (28 checks) runs inside every application's self-test; at release it "
      "reported no contradictions in either codebase."]),
]

# ------------------------------------------------------------------------------------------------- registry v70
# (name, domain, figs, surface, role, function, rule, worked expression, status, module); numerals in NUMERAL
NEW = [
 ("Self-Knowledge Specification Index", "Platform Governance & Evolution", [57], "System", "Any user",
  "Index every numbered section of the Core Technology Overview by number and title as the specification layer of the system's self-description, and resolve a self-question to the sections that specify it.",
  "A self-description cites the section that specifies the capability; a capability with no section is not described.",
  '=IF(ISNUMBER(SEARCH("neuromorphic","Are you neuromorphic?")),"§3, §35","no section")', BUILT, MODULE),
 ("Evidence-Checked Implementation Map", "Platform Governance & Evolution", [57], "System", "Engineer",
  "Hold, for each section and reasoning aspect, evidence pairs (source file, symbol that must appear in it) and check them against the running program's own files at the moment of use, reading files as text without importing them.",
  "Evidence is checked every time it is used; a cached or remembered claim is never reported.",
  '=IF(AND(TRUE,TRUE),"evidence present","contradiction")', BUILT, MODULE),
 ("Capability Status Labels", "Platform Governance & Evolution", [57], "System", "Any user",
  "Label every self-statement built and tested, partly built, specified (not yet built), not planned (by design) or not in this application, with a separate marker for descriptive sections.",
  "A capability is labelled built only when all its evidence is present; a specified capability is never described as built.",
  '=IF(3=3,"built and tested",IF(3>0,"partly built","specified, not yet built"))', BUILT, MODULE),
 ("Reasoning-Aspect Self-Description", "Retrieval & Response", [57], "System", "Any user",
  "Describe twelve reasoning aspects — deterministic, atomic, world model, predictive, neuromorphic, hypothesis, simulation, deduction, feedback, supervised self-improvement, recursive self-improvement, self-knowledge — at brief, user and engineer level, each with its status and sources.",
  "The status in the description is the status the evidence check returns, never a fixed text.", None, BUILT, MODULE),
 ("Self-Consistency Check", "Platform Governance & Evolution", [57, 53], "System", "Engineer / Auditor",
  "Report as a contradiction any claim labelled built or partly built whose evidence is missing, and any capability labelled specified whose implementation names appear in the program.",
  "A contradicted claim is withheld from answers until the description or the code is corrected; the check runs inside every self-test.",
  '=IF(AND("built"="built",FALSE),"consistent","contradiction")', BUILT, MODULE),
 ("Self-Knowledge Gap Agenda", "Platform Governance & Evolution", [57], "System", "Operator",
  "List every section specified but not built, or partly built, with number, title and nearest built component, as the system's development agenda.",
  "The agenda is never presented as capability.", None, BUILT, MODULE),
 ("Rule-Based Self-Question Answering with Sources", "Retrieval & Response", [57, 48], "System", "Any user",
  "Answer questions about the system itself by rule — aspect patterns and section numbers — returning the status label, the section numbers and the file and symbol evidence.",
  "No language model is used; the same question about the same program gives the same answer.", None, BUILT, MODULE),
 ("Self-Description Disclosure Filter", "Access, Rights & Retention", [57, 52], "System", "Any user",
  "Remove from every self-description anything that resembles a key, token or credential, and never read settings or key files while describing the system.",
  "A filtered value is replaced by [withheld]; the filter cannot be disabled by a query.",
  '=IF(LEFT("AIzaXXXX",4)="AIza","[withheld]","shown")', BUILT, MODULE),
 ("Self-Knowledge Interfaces", "External Integration & Analysis", [57, 49], "System", "Any user / Developer",
  "Expose the layer as GET /api/self (summary, label counts, aspects, process, sections, contradictions, gaps) and GET /api/self/ask (one answer with sources), as a Self-knowledge page and Control Panel tab, and as an assistant rule.",
  "Read-only: the interfaces never change the program, the store or any setting.", None, BUILT,
  "qb_api, self.html (v9.64); qbselfknow, control/ui (applications)"),
]
NUMERAL = [5710, 5720, 5730, 5740, 5750, 5760, 5770, 5780, 5790]
assert len(NUMERAL) == len(NEW)

ALGOS = [
 ("ALG-20", "Self-description resolution",
  "Self-Knowledge Specification Index; Evidence-Checked Implementation Map; Capability Status Labels; Rule-Based Self-Question Answering with Sources", [57],
  "A self-question; detail level; host check results (optional)",
  "1. Match the question to a reasoning aspect by its word patterns, or to a section by number. 2. Read the aspect's or section's evidence pairs for this codebase and check each symbol in its file. 3. Label: built if all evidence is present and the declared status is built; partly built if declared partial; specified, not planned or not in this application as declared. 4. If declared evidence is missing, report a contradiction instead of the claim. 5. Compose the answer at the requested level with section numbers and file:symbol sources. 6. Apply the disclosure filter.",
  "Answer with label, sections and sources", "Yes", "qb_selfknow / qbselfknow"),
 ("ALG-21", "Self-consistency check and gap agenda",
  "Self-Consistency Check; Self-Knowledge Gap Agenda", [57],
  "Coverage table; the program's source tree",
  "1. For every section and aspect labelled built or partly built, check every evidence pair; a missing symbol is a contradiction. 2. For every capability labelled specified, search the source tree for its implementation names; a hit is a contradiction (the description lags the code). 3. List specified and partly built sections with their nearest built component as the gap agenda. 4. Fail the self-test if any contradiction is found.",
  "Contradictions; gap agenda", "Yes", "qb_selfknow / qbselfknow"),
]

# ------------------------------------------------------------------------------------------------- provisional
SUMMARY_H = [[("   h. A self-knowledge layer by which the system describes its own capabilities accurately and with sources: each "
               "statement about itself is resolved against the numbered specification, checked against the system's own program "
               "files and self-tests at the moment of asking, labelled built, partly built, specified, not planned or not present, "
               "and withheld as a contradiction when its evidence is missing (FIG. 57).", False)]]
SYSTEM_8 = [[("8. Accurate self-knowledge. Asked about itself — what it is, how it reasons, whether it predicts or improves itself — "
              "QueryBook answers only from its specification, its own program and its own tests, says for each capability whether "
              "it is built or only specified, and names its sources. See FIG. 57.", False)]]
CORE = [
 [("12. Self-Knowledge Layer (FIG. 57). ", True),
  ("A self-question (5700) from a user, the assistant or an application is received by the self-knowledge layer (5705). A "
   "specification index (5710) holds the numbered sections of the specification and resolves the question to the sections that "
   "specify the capability asked about. An implementation map (5720) holds, for each section and each reasoning aspect, evidence "
   "pairs consisting of a source file and a symbol that must appear in it; the pairs are checked against the program's own source "
   "files (5795) at the moment of use, the files being read as text and not executed, and the host application's self-test and "
   "measurement results (5797) are attached as further evidence. A status labeller (5730) assigns exactly one of the labels built "
   "and tested, partly built, specified and not yet built, not planned by design, and not in this application; a capability is "
   "labelled built only when all of its evidence is present. An aspect describer (5740) describes reasoning aspects — "
   "deterministic reasoning, atomic Fact Units, world model, predictive cognition, neuromorphic layer, hypothesis generation, "
   "simulation, deduction, feedback loops, supervised self-improvement, recursive self-improvement and self-knowledge — at "
   "selectable levels of detail. A consistency checker (5750) reports as a contradiction any claim labelled built whose evidence is "
   "missing, and any capability labelled specified whose implementation names are found in the program; a contradicted claim is "
   "withheld. A gap agenda (5760) lists the specified and partly built sections with their nearest built components. A rule-based "
   "answerer (5770) composes the answer with its label, section numbers and file-and-symbol sources, and a disclosure filter (5780) "
   "removes anything resembling a key or credential. Interfaces (5790) expose the summary and single answers to applications, a "
   "self-knowledge page and an administrative panel. No language model is used: the same question about the same program gives "
   "the same answer.", False)],
 [("13. Status. ", True),
  ("The self-knowledge layer of FIG. 57 is implemented in prototype v9.64 and in the shared core of the Language, STEM, History "
   "and News and Control Panel applications, and is exercised by their self-tests.", False)],
]
ARCH = [[("Referring to FIG. 57: the self-knowledge layer is a read-only governance service. It reads the specification index, "
          "the program's own source files and the self-test results, and it never changes the program, the store or any setting; "
          "improvements it identifies pass through the existing approval gates.", False)]]
BRIEF = [[("FIG. 57 ", True),
          ("is a block diagram of the self-knowledge layer, showing a self-question resolved through a specification index, an "
           "evidence-checked implementation map over the program's own source files and self-test results, a status labeller, "
           "an aspect describer, a consistency checker and gap agenda, a rule-based answerer with a disclosure filter, and the "
           "interfaces through which the answer, with its label and sources, is returned.", False)]]
NOTE = [[("[Drafting note: FIG. 57 is added to the drawing set, which now comprises FIG. 1–57, one figure per sheet. FIG. 57 of "
          "this application is the self-knowledge layer and supersedes the earlier draft figure of that number.]", False)]]
CLAIMS = [
 ("358.  ", "The method of claim 1, further comprising receiving a question about a capability of the system itself; resolving the "
  "question to one or more numbered sections of a specification of the system; retrieving, for said capability, evidence pairs each "
  "comprising a source file of the system and a symbol required to appear therein; checking each evidence pair against the source "
  "files of the running system at the time of the question; and returning an answer comprising a status label selected from built, "
  "partly built, specified and not yet built, not planned, and not present, together with the section numbers and the evidence "
  "pairs as sources."),
 ("359.  ", "The method of claim 358, wherein a capability is labelled built only when every evidence pair for it is present, and "
  "wherein a capability declared built or partly built for which an evidence pair is absent is reported as a contradiction and its "
  "description is withheld from the answer."),
 ("360.  ", "The method of claim 358, further comprising searching the source files for implementation names of each capability "
  "declared specified and not yet built, and reporting a contradiction when such a name is found, whereby the self-description is "
  "corrected when the implementation advances beyond it."),
 ("361.  ", "The method of claim 358, wherein the answer is composed by fixed rules without a language model such that the same "
  "question about the same program yields the same answer; wherein the source files are read as text without being executed; and "
  "wherein any portion of the answer resembling a key or credential is removed before the answer is returned."),
 ("362.  ", "The method of claim 358, further comprising describing reasoning aspects of the system, including deterministic reasoning, "
  "atomic knowledge records, a world model, predictive cognition, a neuromorphic layer, hypothesis generation, simulation, deduction, "
  "feedback loops and self-improvement, each with its status label and sources; listing the sections specified but not built as a "
  "development agenda; and reporting any self-modification of the system without an administrator's approval as not provided."),
]
CLAIM_NOTE = ("[Drafting note: claims 358–362 are added for the self-knowledge layer (FIG. 57); the claim count in the Claim Set "
              "heading is to be read as 362.]")

# ------------------------------------------------------------------------------------------------- FIG. 57 key
FIG_KEY = [
 ("5700", "Self-question (user, assistant or application)"), ("5705", "Self-knowledge layer"),
 ("5710", "Specification index: numbered sections §1–§56"), ("5720", "Evidence-checked implementation map: (file, symbol) pairs"),
 ("5730", "Status labeller: built / partly built / specified / not planned / not present"),
 ("5740", "Reasoning-aspect describer: twelve aspects, three levels"), ("5750", "Self-consistency checker: contradictions withheld"),
 ("5760", "Gap agenda: specified and partly built sections"), ("5770", "Rule-based answerer: label, sections, sources"),
 ("5780", "Disclosure filter: keys and credentials removed"), ("5790", "Interfaces: /api/self, /api/self/ask, page, panel, assistant"),
 ("5795", "The program's own source files (read as text)"), ("5797", "Self-tests and measurements of the host application"),
 ("5799", "Answer with status label and sources"),
]
