"""The four-state Fact Unit: one source of wording for every QueryBook document.

The Bible (Pass 121, Chapter 132), the Composite Feature Registry v72 (features 408-422, ALG-26 to ALG-29, FIG. 60-61) and the
provisional (FIG. 60-61, claims 375-386) are all generated from this file, so they say the same thing. The code it describes is
in the one-window QueryBook (branch claude/pensive-knuth-7t7jzm, querybook-one/): apps/_core/sense.py (truth_state, rate, tally,
STATE_CODE, combine, pack_states, identity_state, match_mention, weigh_mentions, period), apps/_core/qbbulk.py
(statement_context, the context table, fill_dates, NewsNames, the demand table), apps/_core/qbcommons.py, apps/facts/app.py,
apps/shell/ask.py and ui/askpage.js; tests in querybook-one/tests/test_sense.py and test_news.py.
The claims are a draft for the applicant's patent attorney.
"""
DATE = "November 14, 2026"
DATE_ISO = "2026-11-14"
CITE = "FSU 2026-11-14"
FIG_S, FIG_I = 60, 61
FIG_S_TITLE = "Four-State Fact Unit: Truth State, Backing, Weight and Two-Bit Evidence Code"
FIG_I_TITLE = "Fact Unit Identity State, Statement Context Beside the Fact, and Mention Weighing"
BUILT = "Built — applications (QueryBook one window, engine 1.56)"
BUILT_F = "Built — function and tests (engine 1.56); not yet used in the store's file format"
SPEC = "Specified"
MOD_S = "sense (applications' shared core); qbbulk, qbcommons, facts, shell/ask"
MOD_I = "sense, qbbulk, qbnews (applications' shared core); shell/ask"

STATES = [  # state, code (for-bit, against-bit), meaning, hardware counterpart
    ("true", "10", "confirming evidence, none against", "logic 1"),
    ("false", "01", "found to be wrong", "logic 0"),
    ("undetermined", "00", "no confirming evidence either way", "Z — nothing drives the line"),
    ("conflicting", "11", "evidence for and evidence against", "X — drivers disagree"),
]
BACKINGS = [  # backing, state, weight, reason
    ("verified", "true", "1.0", "checked and confirmed"),
    ("computed", "true", "1.0", "calculated, and the calculation can be repeated"),
    ("corroborated", "true", "0.9", "two or more different sources agree"),
    ("sourced", "undetermined", "0.75", "one named source says so; not yet confirmed by a second"),
    ("reported", "undetermined", "0.4", "a report says so; not confirmed"),
    ("unsourced", "undetermined", "0.2", "no source is recorded"),
    ("disputed", "conflicting", "0.3", "sources disagree"),
    ("rejected", "false", "0.0", "found to be wrong"),
]
BACKING_LINE = "; ".join(f"{b} {w} ({s})" for b, s, w, _ in BACKINGS)

# ------------------------------------------------------------------------------------------- Bible Chapter 132
TITLE = "The Four-State Fact Unit"
INTRO = [
    "A Fact Unit is no longer read as simply held or not held. Every Fact Unit that QueryBook returns now stands in exactly one of "
    "four truth states — true, false, undetermined or conflicting — and carries, beneath that state, the backing that explains it "
    "and a weight. A fact with nothing recorded about its evidence is undetermined; it is never assumed true. A second, separate "
    "field records identity: whether the subject of the fact is resolved to one known entity, unresolved, ambiguous or conflicting. "
    "A name printed in a newspaper is true as printed and unresolved as to who.",
    "The four truth states are the two-valued reading of the evidence pair of Chapter 3: one bit records that confirming evidence "
    "exists, the other that the assertion has been found wrong. Neither bit set is undetermined; the first alone is true; the "
    "second alone is false; both are conflicting. This is the four-valued logic known in the literature as Belnap's, and it is the "
    "same shape as the four-state logic used to describe digital hardware, in which a line is 1, 0, undriven (Z) or driven two ways "
    "at once (X). The correspondence is exact enough to compute with: evidence from separate records is joined by a bitwise OR.",
]
SUBSECTIONS = [
    ("132.1 The four truth states",
     ["True: the assertion is confirmed and nothing stands against it. False: the assertion was checked and found wrong; the record "
      "is kept, marked, so that the error is not harvested again as new. Undetermined: no confirming evidence either way — the "
      "assertion may have a source, but one source is a report, not a confirmation. Conflicting: there is evidence for the assertion "
      "and evidence against it, or the sources disagree. The states are exhaustive and exclusive; every Fact Unit has exactly one.",
      "The rule that decides between undetermined and true is deliberately strict. One source leaves a fact undetermined however "
      "eminent the source. A fact becomes corroborated, and so true, when its own record names two or more different sources (the "
      "work a statement is stated in, or failing that the site of its address). Nothing else promotes a report: not popularity, "
      "not demand, not the number of times the same source repeats it (Chapter 3's self-corroboration bar)."]),
    ("132.2 Backing and weight beneath the state",
     ["The state is the summary; the backing is the reason. Eight backings are kept, each with its state and weight: "
      + BACKING_LINE + ". The backing is derived from the status the fact was stored with, the sources named in its own record and "
      "whether another record contradicts it; a status the engine does not know is treated as unsourced. A contradicted fact is "
      "conflicting whatever its backing, except a rejected one, which stays false.",
      "The weight is a fixed table, not a learned score. It lets an answer prefer a confirmed fact to a reported one and lets a "
      "reader see at a glance how far a statement can be leaned on. It does not replace the evidence pair and Beta posterior of "
      "Chapter 3 and §41.6.2, which remain the confidence model where observations are counted; the weight is the value used when "
      "only the backing is known, as it is for facts harvested in bulk."]),
    ("132.3 Every fact is rated",
     ["Rating is not a feature of one page. Wherever facts are returned — the bulk store's entity search, the Commons, History & "
      "News, the Ask box — each fact carries its state, backing, weight, the reason in words and its two-bit code, and an answer "
      "carries a tally of how many of its facts stand in each state. A new place that returns facts must rate them. The rating is "
      "computed from the stored record each time it is returned; nothing in the facts table and no fingerprint is changed by it, so "
      "the identity of a Fact Unit (Chapter 3) is exactly as before."]),
    ("132.4 The two-bit evidence code and the join",
     ["Each state has a two-bit code: undetermined 00, false 01, true 10, conflicting 11. The first bit means confirming evidence "
      "exists; the second means the assertion has been found wrong. When two records speak to the same assertion their states are "
      "joined by OR-ing the codes: true joined with false is conflicting; undetermined joined with anything is that thing; "
      "conflicting stays conflicting. The join does not depend on the order in which evidence arrives, and joining the same "
      "evidence twice changes nothing, so stores can be merged in any order and re-merged safely.",
      "Because the code is two bits, 32 Fact Unit states fit one 64-bit word, and one OR instruction joins 32 states with 32 "
      "others. The eight backings fit three bits, and since the backing determines the state, three bits carry both. These packed "
      "forms are built and tested as pure functions; the store's file format does not yet use them — the state is computed when a "
      "fact is returned."]),
    ("132.5 Compatibility with processors, present and future",
     ["Present processors are binary, and the four-state Fact Unit needs nothing else. It is defined as logic, not as a voltage: "
      "two bits per state on any binary machine, combined by the OR instruction every processor has, 32 states to a 64-bit register "
      "and proportionally more in wider vector registers. Four-state logic is already familiar to chip designers — hardware "
      "description languages simulate lines as 0, 1, Z and X — but that is a correspondence of meaning, not a dependency: QueryBook "
      "does not require a tri-state bus or any special circuit.",
      "If future processors or memories offer digits with four levels, one digit holds one state and the join becomes a single "
      "four-level operation; memory cells that hold four levels (two bits per cell) already exist in flash storage. If they offer "
      "more than four levels, the extra levels carry the backing: an eight-level digit holds the backing, and with it the state. If "
      "they never offer more than two levels, nothing changes. In every case the stored meaning, the tables and the answers are "
      "identical, because the hardware changes only how many bits or digits a state occupies, never what the state is.",
      "Further states can be added without disturbing the four: a wider code keeps the first two bits as they are. The design does "
      "not need them today; the fuller distinctions people want (verified, corroborated, reported and so on) are the backing."]),
    ("132.6 Identity is a separate state",
     ["Whether a statement is true and who or what it is about are different questions, and each has its own four states. Identity "
      "is resolved when the subject carries its record's own identifier; unresolved when it is only a name; ambiguous when several "
      "known entities answer to it; conflicting when identifiers disagree. A name harvested from a newspaper page is recorded as "
      "printed — true as printed, status reported — and its identity is unresolved: it stands for whoever bore that name. It is "
      "shown apart from any known person of the same name and is never merged by name alone."]),
    ("132.7 Weighing a mention against a known person",
     ["When a newspaper name could be a known person, each mention is weighed against that person's own facts: was the person "
      "alive, and no longer a child, when it was printed; does the paper name an office the person held; is the paper from one of "
      "the person's places; does it report a death in the year the person died, or an appointment in the year the person took "
      "office. The result is likely, possible or impossible, with its reasons. After the person's death a mention is never more "
      "than possible. This is an analysis shown beside the answer; a mention is never merged into the person's record."]),
    ("132.8 Earlier Fact Unit changes recorded here: context beside the fact",
     ["Since engine 1.48 every statement harvested from a structured source keeps its context — start, end and point in time, "
      "other qualifiers, rank and sources — stored beside the fact, keyed by item, predicate and stored value, in a context table. "
      "The facts table and the fingerprint are untouched, so a Fact Unit's identity does not change when its dates arrive. A date "
      "is shown only when the store holds one; a missing date is never supplied. The Fill Dates action reads one subject's record "
      "from the source its facts cite and adds dates, rank and sources beside the facts; it never adds a fact, and a fact for "
      "which the source states no date says so. The sources kept here are what the corroboration rule of 132.1 counts."]),
    ("132.9 Earlier Fact Unit changes recorded here: what is not a fact",
     ["Four kinds of record are never mixed: an observed measurement (how often a subject was read in a period), an observed "
      "navigation, an inferred intent (always labelled as inferred) and a verified fact — the only one that is a Fact Unit "
      "assertion. Demand decides what to harvest first; it never raises a fact's state, weight or confidence. A ranking or a "
      "prominence score is an analytical output stored apart from facts. An as-printed news fact (name, date, newspaper and town, "
      "page, reason, the paper's own words, linked to its page) is a fact about what was printed, with status reported."]),
    ("132.10 What is built and what is not",
     ["Built and tested in the one-window QueryBook (engine 1.56): the four truth states, eight backings and weights; the "
      "corroboration rule; rating of every returned fact with tally; the two-bit code, the join and the packed forms as pure "
      "functions; the identity state and the unresolved zone; mention weighing; the context table, Fill Dates and dated display. "
      "Not built: packed states in the store's file format; the join applied automatically across datasets; the ambiguous and "
      "conflicting identity states beyond their definitions; any hardware beyond ordinary binary processors, which is all the "
      "design requires. The correspondence with four-state hardware logic is a correspondence of meaning (Chapter 101's method): "
      "named, bounded, and claimed no further than the join it makes computable."]),
]
BIBLE_CORR = [
    "The four-state Fact Unit extends Chapter 3 (Fact Unit Structure): the truth state and its two-bit code are the coarse reading "
    "of the Layer 7 evidence pair, the backing is the reason beneath it, and the context table is where a statement's dates, rank "
    "and sources are kept without altering the immutable record. Chapter 5 (Provenance Ledger) supplies the sources the "
    "corroboration rule counts. §41.6.2 (the Beta posterior) remains the confidence model wherever observations are counted.",
    "Governance is unchanged and made visible. Under Domain 0 (the Prime Directive) an unconfirmed statement is shown as "
    "undetermined rather than asserted; a report is never promoted by repetition or demand; a name is never taken for a person. "
    "The rating changes no stored fact and no fingerprint.",
    f"Registry and claims: Composite Feature Registry v72, features 408–422 (algorithms ALG-26 to ALG-29); provisional application, "
    f"FIG. 60 (reference numerals 6000–6099), FIG. 61 (6100–6199) and claims 375–386. (Drafting record, Pass 121, {DATE}.)",
]

# ------------------------------------------------------------------------------------------- Registry v72 rows
# name, domain, figs, surface, role, function, rule, worked expression, status, module
NEW = [
 ("Four-State Truth Value of a Fact Unit", "Knowledge Substrate", [60], "System", "Any user",
  "Give every Fact Unit exactly one of four truth states: true, false, undetermined or conflicting.",
  "A fact with nothing recorded about its evidence is undetermined; it is never assumed true.",
  '=IF(AND(1=1,0=0),"true",IF(AND(1=0,0=1),"false",IF(AND(1=0,0=0),"undetermined","conflicting")))', BUILT, MOD_S),
 ("Backing Beneath the Truth State", "Knowledge Substrate", [60], "System", "Any user",
  "Keep beneath each state one of eight backings that explain it — verified, computed, corroborated, sourced, reported, unsourced, disputed, rejected — with the reason in words.",
  "An unknown status is treated as unsourced; a contradicted fact is conflicting unless rejected.", None, BUILT, MOD_S),
 ("Evidence Weight per Backing", "Inference, Prediction & Calibration", [60], "System", "Any user",
  "Attach to every fact the fixed weight of its backing: " + BACKING_LINE + ".",
  "The weight is a fixed table, never raised by demand or popularity; the evidence pair remains the confidence model where observations are counted.",
  "=0.9*1", BUILT, MOD_S),
 ("Two-Source Corroboration Rule", "Knowledge Substrate", [60], "System", "System",
  "Promote a sourced fact to corroborated, and so to true, only when its own record names two or more different sources.",
  "One source leaves a fact undetermined; repetition by the same source is not corroboration.",
  '=IF(2>=2,"corroborated","sourced")', BUILT, MOD_S),
 ("Rating of Every Returned Fact", "Retrieval & Response", [60], "System", "Any user",
  "Add state, backing, weight, reason and code to every fact returned by the bulk store, the Commons, History & News and the Ask box, and a tally of the four states to every answer.",
  "A new place that returns facts must rate them; rating changes no stored fact and no fingerprint.", None, BUILT, MOD_S),
 ("Two-Bit Evidence Code", "Knowledge Substrate", [60], "System", "System",
  "Encode each state in two bits — confirming evidence exists; found wrong — as undetermined 00, false 01, true 10, conflicting 11.",
  "The code is the same on every machine; the eight backings fit three bits and determine the state.",
  "=BIN2DEC(10)", BUILT, MOD_S),
 ("Evidence Join by Bitwise OR over Packed States", "Inference, Prediction & Calibration", [60], "System", "System",
  "Join the states of one assertion from separate records by OR-ing their codes, and join 32 packed states per 64-bit word in one operation.",
  "The join is the same in any order and unchanged by repetition.",
  "=BITOR(2,1)", BUILT_F, MOD_S),
 ("Hardware-Independent State Mapping", "Platform Governance & Evolution", [60], "System", "Administrator",
  "Define the four states as logic so that a state occupies two bits on a binary processor, one digit on a four-level device, and shares a digit with its backing on a device of eight or more levels.",
  "No special hardware is required; the stored meaning and the answers are identical on every device.", None, SPEC, MOD_S),
 ("Identity State Separate from Truth State", "Knowledge Substrate", [61], "System", "Any user",
  "Record for a subject one of four identity states — resolved, unresolved, ambiguous, conflicting — apart from the truth state of its facts.",
  "A subject is resolved only by its record's own identifier, never by its name.", None, BUILT, MOD_I),
 ("Unresolved-Name Zone", "Retrieval & Response", [61], "Ask page", "Any user",
  "Show facts about a name that is not resolved to an entity in a zone of their own, apart from a known person of the same name.",
  "A name alone never merges two records and never says who a person is.", None, BUILT, MOD_I),
 ("Mention Weighing Against a Person's Own Facts", "Inference, Prediction & Calibration", [61], "Ask page", "Any user",
  "Weigh each newspaper mention of a name against a known person's dates, offices and places and report likely, possible or impossible with reasons.",
  "An analysis only: a mention is never merged into a record; after the person's death it is at most possible.", None, BUILT, MOD_I),
 ("Statement Context Beside the Fact", "Knowledge Substrate", [61], "System", "System",
  "Keep each harvested statement's start, end and point in time, qualifiers, rank and sources in a context table keyed by item, predicate and stored value.",
  "The facts table and the fingerprint are never changed for it; a missing date is never supplied.", None, BUILT, MOD_I),
 ("Fill Dates from the Cited Source", "Ingestion & Sensory Intake", [61], "Ask page", "Any user",
  "On request, read one subject's record from the source its facts cite and add dates, rank and sources beside the facts.",
  "It never adds a fact; a fact for which the source states no date says so.", None, BUILT, MOD_I),
 ("As-Printed News Fact", "Ingestion & Sensory Intake", [61], "System", "System",
  "Record a name printed in a newspaper as a fact of what was printed — date, newspaper and town, page, reason and the paper's own words, linked to its page — with status reported.",
  "Only issues more than 95 full years old; a reason about crime reads 'arrested or tried, as reported'.", None, BUILT, MOD_I),
 ("Separation of Measurements, Inferences and Facts", "Platform Governance & Evolution", [61], "System", "Administrator / Auditor",
  "Store observed measurements by period, observed navigation and inferred intent apart from verified facts, and scores apart from all of them.",
  "Demand decides harvest order only; it never raises a fact's state, weight or confidence.", None, BUILT, MOD_I),
]
NUMERAL = [6010, 6020, 6030, 6040, 6050, 6060, 6070, 6080, 6110, 6120, 6130, 6140, 6150, 6160, 6170]
assert len(NUMERAL) == len(NEW)

ALGOS = [
 ("ALG-26", "Fact Unit rating (state, backing, weight)",
  "Four-State Truth Value of a Fact Unit; Backing Beneath the Truth State; Evidence Weight per Backing; Two-Source Corroboration Rule; Rating of Every Returned Fact", [60],
  "A fact with its stored status, the sources named in its record, and its contradiction mark",
  "1. Take the stored status, lower case; none is unsourced; 'needs checking' is reported, 'needs sources' is unsourced. 2. If the status is sourced and the record names two or more different sources (the work stated in, else the address's site, else the title), the backing is corroborated. 3. A status not in the table is unsourced. 4. If the fact is marked contradicted and is not rejected, the backing is disputed. 5. Look up the state, the reason, the weight and the two-bit code of the backing. 6. Return the fact with these added; count the states over the answer.",
  "The fact with state, backing, weight, reason, code; a tally of the four states", "Yes", "sense"),
 ("ALG-27", "Evidence join over packed states",
  "Two-Bit Evidence Code; Evidence Join by Bitwise OR over Packed States; Hardware-Independent State Mapping", [60],
  "Two lists of states for the same assertions, in the same order",
  "1. Encode each state in two bits: undetermined 00, false 01, true 10, conflicting 11. 2. Pack each list into words, the first state in the lowest bits, 32 states to a 64-bit word. 3. OR the two words. 4. Unpack: each two bits are the joined state. 5. Count each state when a tally is wanted.",
  "The joined states; their tally", "Yes", "sense"),
 ("ALG-28", "Mention weighing",
  "Identity State Separate from Truth State; Unresolved-Name Zone; Mention Weighing Against a Person's Own Facts; As-Printed News Fact", [61],
  "One as-printed mention (date, newspaper, town, page, reason, words); the known person's facts",
  "1. Read the mention's date, paper, place, reason and words. 2. Printed before the person's birth, or before the age of twelve unless it reports the birth: impossible. 3. Collect agreements: an office or calling the paper names that the person had; the paper's town or state among the person's places; a death reported in the year the person died; a birth in the year of birth; an election or appointment in the year the person took an office. 4. Printed after the person's death: possible, with the agreements. 5. Agreements and a known date of birth or death: likely. 6. Otherwise possible. 7. Over all mentions, count the three verdicts and list examples, likely first.",
  "likely / possible / impossible with reasons; counts and examples", "Yes", "sense"),
 ("ALG-29", "Statement context completion",
  "Statement Context Beside the Fact; Fill Dates from the Cited Source", [61],
  "A subject; the source its facts cite",
  "1. Read the subject's record from the cited source. 2. For each statement kept as a fact, take start, end and point in time, other qualifiers, rank and sources. 3. Store them in the context table under item, predicate and stored value; leave the facts table and fingerprints untouched. 4. A record that arrived without context stays listed for a later read. 5. Report, for each fact, the date held or that the source states none.",
  "Context rows beside the facts; a report per fact", "Yes", "qbbulk"),
]

# ------------------------------------------------------------------------------------------- provisional
SUMMARY_J = [[("   j. A four-state Fact Unit in which every returned fact carries exactly one of four truth states — true, false, "
               "undetermined or conflicting — together with a backing and a weight, the states being encoded in two bits and joined "
               "across records by a bitwise OR on any binary processor or held one per digit on a multi-level device, and in which "
               "a separate identity state keeps an unresolved name apart from a known entity and a statement's dates, rank and "
               "sources are kept beside the fact without altering it (FIG. 60–61).", False)]]
SYSTEM_10 = [[("10. Four states for every fact. QueryBook does not present a statement merely because it holds it. Each fact is shown "
               "as true, false, undetermined or conflicting, with the reason and a weight; one source alone leaves a fact "
               "undetermined, and two different sources make it true. A name that is not tied to a known person is kept in a zone of "
               "its own. The states take two bits on today's processors and would take one digit on a four-level device. See FIG. 60 "
               "and FIG. 61.", False)]]
CORE = [
 [("18. Four-state Fact Unit (FIG. 60). ", True),
  ("A stored fact (6000) with its status, the sources named in its record and any contradiction mark enters a rating unit (6005). A "
   "backing selector (6020) derives one of eight backings — verified, computed, corroborated, sourced, reported, unsourced, disputed "
   "or rejected — applying a corroboration rule (6040) by which a sourced fact whose own record names two or more different sources "
   "is corroborated, and treating a contradicted fact as disputed unless it is rejected. A state table (6010) maps the backing to "
   "exactly one of four truth states: true, false, undetermined or conflicting; a fact with no recorded evidence is undetermined. A "
   "weight table (6030) attaches a fixed weight to the backing, in one embodiment 1.0 for verified and computed, 0.9 for "
   "corroborated, 0.75 for sourced, 0.4 for reported, 0.3 for disputed, 0.2 for unsourced and 0.0 for rejected. The rated fact "
   "(6050) is returned with its state, backing, weight, reason and code, and a tally of the four states accompanies the answer "
   "(6099). The rating is computed from the stored record and alters neither the record nor its identifier.", False)],
 [("19. Two-bit evidence code and hardware mapping (FIG. 60). ", True),
  ("An encoder (6060) represents each state by two bits, a first bit indicating that confirming evidence exists and a second bit "
   "indicating that the assertion has been found wrong: undetermined 00, false 01, true 10, conflicting 11. A join unit (6070) "
   "combines the states of one assertion drawn from separate records by a bitwise OR of their codes, the result being independent "
   "of the order of combination and unchanged by repetition; a plurality of codes is packed into a machine word, in one embodiment "
   "32 codes in a 64-bit word, so that a single OR operation joins the plurality. A hardware mapping (6080) places the same states "
   "on different devices: two bits per state on a binary processor; one digit per state on a device whose storage or logic element "
   "distinguishes four levels; and, on a device distinguishing eight or more levels, one digit holding the backing from which the "
   "state follows. The states correspond in meaning to the four values of hardware description — logic 1, logic 0, an undriven line "
   "and a line driven in conflict — without requiring any such circuit.", False)],
 [("20. Identity state, context beside the fact and mention weighing (FIG. 61). ", True),
  ("An identity unit (6110) assigns to the subject of a fact, apart from the truth state, one of four identity states: resolved, "
   "when the subject carries its record's own identifier; unresolved; ambiguous; or conflicting. An as-printed fact (6160) records "
   "a name printed in a publication together with the date, publication, place, page, a reason and the publication's own words; "
   "its truth state is that of a report and its identity state is unresolved, and it is presented in an unresolved zone (6120) "
   "apart from a known entity of the same name, a name alone never merging two records. A mention weigher (6130) compares each such "
   "mention with a known entity's own facts — dates of birth and death, offices, places — and reports likely, possible or "
   "impossible with reasons, as an analysis only. A context table (6140) holds, beside each fact and keyed by item, predicate and "
   "stored value, the statement's start, end and point in time, qualifiers, rank and sources, the fact and its identifier being "
   "unchanged; a fill unit (6150) reads a subject's record from the source its facts cite and adds such context on request, never "
   "adding a fact and never supplying a date the source does not state. A separation (6170) keeps observed measurements, observed "
   "navigation and inferred intent apart from facts, so that demand orders harvesting and never changes a fact's state or weight.", False)],
 [("21. Status. ", True),
  ("The rating, the corroboration rule, the code, the join and packed forms, the identity state, the unresolved zone, the mention "
   "weigher, the context table and the fill unit are implemented and tested in the shared core of the applications (engine 1.56). "
   "The packed form is not yet used in the store's file format, and the join is not yet applied automatically across datasets. No "
   "hardware other than an ordinary binary processor is used or required; the multi-level embodiments of item 19 are specified.", False)],
]
ARCH = [[("Referring to FIG. 60 and FIG. 61: the truth state and the identity state are properties read from a Fact Unit's record "
          "and its context; they never alter the record. The four truth states are the two-valued reading of the supporting and "
          "contradicting evidence parameters of FIG. 19, and their two-bit code is the same on every device.", False)]]
BRIEF_S = [[("FIG. 60 ", True),
            ("is a block diagram of the four-state Fact Unit, showing a stored fact entering a rating unit with a backing selector, a "
             "corroboration rule, a state table of four truth states and a weight table, the rated fact and tally returned, a two-bit "
             "evidence encoder, a join unit operating by bitwise OR over packed states, and a hardware mapping to binary, four-level "
             "and higher-level devices.", False)]]
BRIEF_I = [[("FIG. 61 ", True),
            ("is a block diagram of the identity state and the context of a Fact Unit, showing an identity unit with four identity "
             "states, an as-printed fact and an unresolved zone, a mention weigher, a context table held beside the facts, a fill "
             "unit reading the cited source, and the separation of measurements and inferences from facts.", False)]]
NOTE = [[("[Drafting note: FIG. 60 and FIG. 61 are added to the drawing set, which now comprises FIG. 1–61, one figure per sheet.]", False)]]
CLAIMS = [
 ("375.  ", "The method of claim 1, further comprising, for each fact unit returned in response to a query, determining from the "
  "fact unit's stored record exactly one of four truth states consisting of a true state, a false state, an undetermined state and a "
  "conflicting state, and returning the fact unit together with its truth state, wherein a fact unit whose record holds no confirming "
  "evidence is assigned the undetermined state."),
 ("376.  ", "The method of claim 375, wherein determining the truth state comprises selecting a backing from a plurality of backings "
  "according to a stored status of the fact unit, the sources named in the fact unit's record and an indication that another record "
  "contradicts it, each backing being associated with one of the four truth states and with a predetermined weight, and returning the "
  "backing and the weight with the fact unit."),
 ("377.  ", "The method of claim 376, wherein a fact unit stated by a single source is assigned the undetermined state, and is "
  "assigned the true state when its own record names at least two different sources."),
 ("378.  ", "The method of claim 375, further comprising returning with a response a count of the fact units of the response in each "
  "of the four truth states, wherein determining the truth state alters neither the stored record nor an identifier derived from it."),
 ("379.  ", "The method of claim 375, further comprising representing each truth state by a two-bit code having a first bit "
  "indicating that confirming evidence exists and a second bit indicating that the assertion has been found wrong, and combining the "
  "truth states of one assertion obtained from different records by a bitwise OR of their codes."),
 ("380.  ", "The method of claim 379, further comprising packing the codes of a plurality of fact units into a machine word and "
  "combining the plurality with a corresponding plurality by a single bitwise OR of two machine words."),
 ("381.  ", "The method of claim 379, wherein, on a device having storage or logic elements that distinguish at least four levels, "
  "each truth state is held in one such element, and wherein the truth states and the responses produced are the same as on a "
  "binary device."),
 ("382.  ", "The method of claim 375, further comprising determining for a subject of a fact unit, separately from the truth state, "
  "one of a plurality of identity states including a resolved state, in which the subject carries an identifier of its record, and "
  "an unresolved state; and presenting fact units whose subject is in the unresolved state apart from fact units of a resolved "
  "entity having the same name, without merging them."),
 ("383.  ", "The method of claim 382, further comprising recording a name printed in a publication as a fact unit comprising the "
  "name as printed, a date, the publication, a page and words of the publication, the fact unit having the undetermined truth state "
  "and the unresolved identity state."),
 ("384.  ", "The method of claim 383, further comprising comparing the date and content of the recorded fact unit with facts of a "
  "resolved entity having the same name, including dates of birth and death, offices and places, and reporting, with reasons and "
  "without merging, whether the recorded fact unit is likely, possibly or impossibly about the resolved entity."),
 ("385.  ", "The method of claim 375, further comprising storing, beside a fact unit and keyed to it, a context comprising at least "
  "one of a start time, an end time, a point in time, a rank and one or more sources of the statement from which the fact unit was "
  "made, without altering the fact unit or its identifier, and using the sources of the context in determining the truth state."),
 ("386.  ", "The method of claim 385, further comprising, on request, reading a record of a subject from a source cited by its fact "
  "units and adding the context to the fact units already held, without adding a fact unit and without supplying a time the source "
  "does not state."),
]
CLAIM_NOTE = ("[Drafting note: claims 375–386 are added for the four-state Fact Unit, its two-bit evidence code, the identity state and "
              "the context beside the fact (FIG. 60–61); the claim count in the Claim Set heading is to be read as 386. Draft for "
              "review by the applicant's patent attorney.]")

# ------------------------------------------------------------------------------------------------- figure keys
FIG_KEY_S = [
 ("6000", "Stored fact: status, sources named in its record, contradiction mark"), ("6005", "Rating unit"),
 ("6010", "State table: true · false · undetermined · conflicting"),
 ("6020", "Backing selector: verified, computed, corroborated, sourced, reported, unsourced, disputed, rejected"),
 ("6030", "Weight table: fixed weight per backing"), ("6040", "Corroboration rule: two different sources in the fact's own record"),
 ("6050", "Rated fact: state, backing, weight, reason, code"), ("6060", "Two-bit evidence encoder: 00, 01, 10, 11"),
 ("6070", "Join unit: bitwise OR over packed states (32 per 64-bit word)"),
 ("6080", "Hardware mapping: binary · four-level · eight or more levels"), ("6099", "Answer with tally of the four states"),
]
FIG_KEY_I = [
 ("6100", "Subject of a fact"), ("6105", "Identity and context layer"),
 ("6110", "Identity unit: resolved · unresolved · ambiguous · conflicting"), ("6120", "Unresolved zone: shown apart, never merged by name"),
 ("6130", "Mention weigher: likely · possible · impossible, with reasons"),
 ("6140", "Context table beside the facts: start, end, point in time, qualifiers, rank, sources"),
 ("6150", "Fill unit: reads the cited source; adds context only"), ("6160", "As-printed fact: name, date, publication, page, reason, words"),
 ("6170", "Separation: measurements, navigation and inferred intent apart from facts"), ("6199", "Answer: known entity, mention analysis, unresolved zone"),
]
