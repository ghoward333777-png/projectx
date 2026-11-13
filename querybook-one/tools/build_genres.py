#!/usr/bin/env python3
"""Build apps/shell/genres.json — QueryBook's genre library (the Writing Skills Plan, part 2).

One record per document type: purpose, reader, sections with the move each must make, the framework at document, section
and paragraph scale, register, evidence rules, hard constraints, and failure modes written as named checks
(apps/shell/writing.py runs them).

    python tools/build_genres.py            write the file
    python tools/build_genres.py --check    fail if the file is not what this table makes (run by the tests)

PROVENANCE, stated plainly: these records are QueryBook's FIRST DRAFT, written from general knowledge of each genre in
QueryBook's own words. They have not yet been reconciled with the sources (SOURCES below: none has been learned from —
each site's terms are checked first, at learning time). Every record says so. The user's decisions (2026-11-13): all
genres, in any order; all sources, learned once; the user reviews as a document is composed, so no separate review of
records at this stage; style is the user's own or a template from a growing library (STYLES below).
Adding a genre, a style or a source is adding a row here — the writer does not change.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "apps", "shell", "genres.json")
STATUS = "first draft from general knowledge of the genre — the sources have not been learned from yet"
TP, IX, LK, CT = "theme preview", "index", "linking", "constant theme"

FAMILIES = [
    ("academic", "Academic", TP, "Claim, evidence and citation discipline"),
    ("business", "Business", TP + " with conclusions first", "A decision-maker who reads only the top"),
    ("technical", "Technical", IX + ", with linking for procedures", "Exactness, consistent terminology, task order"),
    ("analytical", "Analytical and policy", IX + " over a stated question", "Separating finding from interpretation"),
    ("legal", "Legal", TP + " in a fixed form (issue, rule, application, conclusion)", "Defined terms, jurisdiction, no ambiguity"),
    ("everyday", "Everyday and professional", "most important first", "A reader with little time and no duty to read"),
    ("learning", "Teaching and learning", TP, "A learner who must be able to do something afterwards"),
    ("books", "Books", TP + " for non-fiction; " + LK + " for narrative", "Holding a reader across many chapters"),
    ("journalism", "Journalism", "most important first, then linking", "Verification, attribution, harm avoidance"),
    ("fiction", "Fiction and dramatic", LK + ", with previews deliberately withheld", "Tension, voice, subtext"),
]
LEGAL = ["This is a draft for a qualified lawyer to review; it is not legal advice", "The governing jurisdiction is named, and nothing is asserted about law outside it"]
NEWS = ["Every fact is attributed to a named source or to the reporter's own observation", "Nothing is published that was not verified",
        "Harm is weighed: victims, minors and people not charged are not identified without cause"]

# (id, name, other names, family, purpose, reader, (document, section, paragraph), sections, (person, tense, formality, hedging,
#  words lo, hi), evidence, constraints, failures)
# a section is "Name: the move it must make"; a leading "?" marks it optional; a trailing " @framework" overrides the paragraph default
G = [
    ("essay", "essay", ["academic essay"], "academic", "argue one claim and support it", "a marker or informed general reader", (TP, IX, LK),
     ["Introduction: state the question and the claim, and preview the reasons in order", "First reason: give the strongest reason with its evidence",
      "Second reason: give a further, independent reason with its evidence", "?Third reason: add a reason only if it is as strong as the others",
      "Counter-argument: state the best objection fairly and answer it", "Conclusion: restate the claim in the light of the argument, without new evidence"],
     ("third", "present", "formal", "some", 800, 2500), "claims rest on cited sources or stated reasoning; quotations are exact and referenced", [],
     [("Sources are used without citation", "citations"), ("The claim is not stated at the start", "conclusion_first")]),
    ("research-paper", "research paper", ["journal article", "scientific paper"], "academic", "report an original study so that it can be judged and repeated", "researchers in the field", (TP, IX, LK),
     ["Abstract: say the question, method, main result and what it means, in one paragraph @constant theme", "Introduction: set the problem in what is known, name the gap, state the aim",
      "Methods: say what was done precisely enough to repeat it", "Results: report what was found, without interpreting it",
      "Discussion: interpret the results, set them against earlier work, state the limits", "Conclusion: say what now follows", "References: list every work cited"],
     ("third", "past", "formal", "some", 3000, 8000), "every claim about earlier work is cited; data and method are reported so the result can be checked",
     ["Results are reported as found: nothing is selected or altered to fit", "Work by others is credited"],
     [("Claims about earlier work are not cited", "citations"), ("Results and interpretation are mixed", "")]),
    ("literature-review", "literature review", [], "academic", "show what is known on a question, how the work fits together, and what is missing", "researchers and students of the field", (TP, IX, IX),
     ["Introduction: state the question, the scope and how the review is organised", "Themes: group the work by idea, not by author, and compare the findings within each",
      "Disagreements: set out where the work conflicts and why", "Gaps: name what has not been studied", "Conclusion: say what the field now knows and what should be done next"],
     ("third", "present", "formal", "some", 2000, 8000), "every statement about a study cites it; the reviewer's own judgement is marked as such", [],
     [("Studies are listed one by one instead of compared", ""), ("Statements about the literature are not cited", "citations")]),
    ("abstract", "abstract", [], "academic", "let a reader decide in a minute whether to read the whole work", "a researcher scanning many papers", (CT, CT, CT),
     ["Abstract: say the problem, the method, the main result with its key number, and the conclusion"],
     ("third", "past", "formal", "none", 100, 300), "only what the full work supports; no citation, no undefined abbreviation", [],
     [("It is too long or too short", "abstract_length"), ("It promises instead of reporting the result", "")]),
    ("thesis-chapter", "thesis chapter", ["dissertation chapter", "thesis", "dissertation"], "academic", "carry one stage of a long argument and tie it to the whole", "examiners", (TP, TP, LK),
     ["Chapter introduction: say what this chapter does, how it follows the last, and preview its sections in order", "Body sections: develop each previewed part under its own heading, in the previewed order",
      "Synthesis: bring the sections together into the chapter's finding", "Chapter conclusion: state what has been established and what the next chapter takes up"],
     ("third", "present", "formal", "some", 5000, 15000), "every borrowed idea and datum is cited; the chapter's own contribution is distinguished from others' work",
     ["The work is the candidate's own, and every source is acknowledged"],
     [("The preview and the section headings do not match", ""), ("Sources are not cited", "citations")]),
    ("critique", "critique", ["critical review", "critical analysis"], "academic", "judge a work against stated criteria", "a marker or reader who has not read the work", (TP, IX, LK),
     ["Introduction: name the work and its author, say what it sets out to do, and give the overall judgement", "Summary: say briefly and fairly what the work argues",
      "Evaluation: judge it criterion by criterion, with evidence from the work", "Conclusion: give the final judgement and whom the work would serve"],
     ("third", "present", "formal", "some", 800, 2500), "every judgement points to a passage or feature of the work", [],
     [("It summarises without judging", ""), ("Judgements are not tied to the work", "citations")]),

    ("business-report", "business report", ["report"], "business", "give a decision-maker what was found and what to do", "a manager who may read only the first page", (TP, IX, LK),
     ["Executive summary: state the conclusion and the recommendation first", "Background: say why the report was asked for and what it covers",
      "Findings: set out what was found, one finding to a section", "Analysis: say what the findings mean for the decision",
      "Recommendations: say what to do, who does it and by when", "?Appendices: hold the supporting detail"],
     ("third", "present", "plain professional", "none", 800, 4000), "figures name their source and date; a finding is kept apart from the opinion drawn from it", [],
     [("The conclusion is buried", "conclusion_first"), ("Promotional or empty wording", "no_vague_praise")]),
    ("memo", "memo", ["memorandum"], "business", "tell colleagues one thing they need to know or do", "busy colleagues", (CT, CT, CT),
     ["Heading: To, From, Date, Subject — a subject line that says the point", "Purpose: say in the first sentence what the memo is for and what is wanted",
      "Details: give only what the reader needs to act", "Action: say who must do what by when"],
     ("first", "present", "plain professional", "none", 150, 600), "dates, amounts and names are exact", [],
     [("The request is not in the opening", "conclusion_first")]),
    ("proposal", "proposal", ["business proposal", "project proposal", "grant proposal"], "business", "win approval or funding for a piece of work", "a person who can say yes and will compare it with others", (TP, IX, LK),
     ["Summary: say what is proposed, what it will achieve and what it costs", "Problem: establish the need and what it costs to leave it",
      "Solution: describe the work proposed and why this approach", "Plan: give the stages, the people and the dates",
      "Budget: give the cost, itemised", "Benefits and risks: say what will be gained and what could go wrong", "Request: say exactly what decision is asked for"],
     ("first", "future", "plain professional", "none", 800, 5000), "every figure and claim of benefit can be traced to a source or a stated assumption",
     ["Costs and capabilities are stated truthfully"],
     [("The ask is not stated at the start", "conclusion_first"), ("Promotional or empty wording", "no_vague_praise")]),
    ("executive-summary", "executive summary", [], "business", "stand in for a longer document for the reader who will read nothing else", "a senior decision-maker", (CT, CT, CT),
     ["Summary: say the purpose, the main findings, the conclusion and the recommendation, in that order of importance"],
     ("third", "present", "plain professional", "none", 150, 500), "nothing appears here that is not in the full document", [],
     [("It introduces instead of concluding", "conclusion_first")]),
    ("white-paper", "white paper", ["whitepaper"], "business", "persuade an informed reader that a problem matters and that an approach solves it", "a professional weighing a decision in their own field", (TP, IX, LK),
     ["Title and summary: say the problem, the answer and who should read on", "Problem: establish the problem and the cost of leaving it alone",
      "Background: say what has been tried and why it falls short", "Solution: explain the approach and how it works",
      "Evidence: show that it works — data, cases, comparisons", "Conclusion: say what the reader should do next"],
     ("third", "present", "professional", "some", 1500, 5000), "claims are supported by data or named cases, each with its source; the product is not the argument",
     ["Evidence is reported fairly, including what it does not show"],
     [("It reads as an advertisement", "no_vague_praise"), ("Claims are not sourced", "citations")]),
    ("postmortem", "postmortem", ["post-mortem", "incident report", "incident review"], "business", "record what went wrong, why, and what will stop it happening again", "the team and those affected", (TP, LK, LK),
     ["Summary: say what happened, its effect and its duration", "Timeline: give the events in order with their times @linking",
      "Root cause: trace the failure to its cause, not to a person", "What went well and what did not: say both plainly",
      "Actions: list each fix with its owner and date"],
     ("first", "past", "plain professional", "none", 500, 3000), "times and effects come from logs and records, not memory",
     ["It is blameless: it names causes and conditions, not culprits"],
     [("The summary does not say what happened", "conclusion_first")]),

    ("technical-report", "technical report", ["engineering report"], "technical", "record a piece of technical work so that it can be used and checked", "engineers and a manager who reads the summary", (TP, IX, LK),
     ["Summary: say the aim, the method, the main result and the conclusion", "Introduction: state the problem, the scope and the layout of the report",
      "Method: describe the approach, equipment and conditions", "Results: present the data, each figure and table numbered and titled",
      "Discussion: interpret the results and state their accuracy and limits", "Conclusions: list what was established", "?Recommendations: say what should follow",
      "References: list the sources"],
     ("third", "past", "formal", "some", 1500, 8000), "every figure has units and a source; uncertainty is stated", [],
     [("A term changes name between sections", ""), ("Sources are not cited", "citations")]),
    ("tutorial", "tutorial", ["how-to", "how to guide", "getting started guide"], "technical", "take a beginner through doing one thing successfully for the first time", "a newcomer following along step by step", (TP, LK, LK),
     ["What you will build: say what the reader will have at the end and what they need first", "Steps: give one action to a step, in order, each with what to expect",
      "Check: show how to confirm it worked", "What next: point to the next thing to learn"],
     ("second", "present", "plain", "none", 500, 3000), "every command and value is exact and was run as written",
     ["A step that can lose data or cost money carries a warning before the step"],
     [("Steps are not numbered", "steps_numbered"), ("Steps do not begin with the action", "steps_imperative")]),
    ("procedure", "procedure", ["standard operating procedure", "instructions", "work instruction"], "technical", "let a trained person carry out a task the same way every time", "an operator doing the task now", (IX, LK, LK),
     ["Purpose and scope: say what the procedure is for and when it applies", "Before you start: list tools, materials, conditions and warnings",
      "Steps: give one action to a step, in order, with the expected result", "If something goes wrong: say what to do for each likely fault", "Records: say what to record and where"],
     ("second", "present", "plain", "none", 200, 2000), "values, limits and part names are exact",
     ["A warning comes before the step it applies to, never after"],
     [("Steps are not numbered", "steps_numbered"), ("Steps do not begin with the action", "steps_imperative")]),
    ("reference", "reference documentation", ["reference", "api reference", "reference manual"], "technical", "let a user look one thing up and find it complete and exact", "a practitioner who already knows the task", (IX, IX, CT),
     ["Overview: name the whole and list its parts", "Entries: describe each part in the same order of fields — what it is, its inputs, its result, its limits, an example"],
     ("third", "present", "plain", "none", 300, 10000), "every entry is checked against the thing it describes", [],
     [("Entries do not follow one pattern", ""), ("A term changes name between entries", "")]),
    ("specification", "specification", ["spec", "requirements specification", "requirements"], "technical", "state what must be built precisely enough to build and test it", "the people who will build and test it", (IX, IX, CT),
     ["Scope: say what is covered and what is not", "Definitions: define every term that the requirements use",
      "Requirements: state each requirement separately, numbered, testable, with must for what is mandatory", "Constraints: state the limits that the design must respect",
      "Acceptance: say how each requirement will be shown to be met"],
     ("third", "present", "formal", "none", 500, 10000), "each requirement can be tested; nothing is left to interpretation",
     ["\"must\" marks what is mandatory and \"should\" what is preferred, and neither is used loosely"],
     [("Terms are not defined", "defined_terms"), ("Vague wording", "no_vague_praise")]),
    ("overview", "overview", ["technical overview", "architecture overview", "introduction to"], "technical", "give a newcomer the shape of a system before the detail", "a capable reader new to this system", (IX, IX, CT),
     ["What it is: say in a sentence or two what the system is and what it is for", "The parts: name the whole and then each part, saying what each does",
      "How the parts work together: follow one typical task through the parts @linking", "Where to go next: point to the detail for each part"],
     ("third", "present", "plain", "none", 300, 2000), "names match the system's own names exactly", [],
     [("The parts are listed before the whole is named", "")]),

    ("analysis", "analysis", ["analytical report"], "analytical", "answer a stated question from evidence", "a reader who must rely on the answer", (IX, IX, LK),
     ["Question: state the question and why it matters", "Evidence: set out what is known, with its source and its quality",
      "Findings: say what the evidence shows", "Interpretation: say what the findings mean — kept apart from the findings",
      "Limits: say what the analysis cannot tell", "Conclusion: answer the question"],
     ("third", "present", "formal", "some", 800, 5000), "a finding states its evidence; an interpretation is marked as one", [],
     [("Finding and interpretation are mixed", ""), ("Evidence is not sourced", "citations")]),
    ("policy-brief", "policy brief", ["policy paper", "briefing note", "briefing"], "analytical", "give a decision-maker the options on an issue and a recommendation", "an official or legislator with a few minutes", (TP, IX, LK),
     ["Summary: say the issue, the recommendation and why, at the top", "The issue: say what the problem is, whom it affects and why now",
      "Options: set out the realistic choices with the costs and effects of each", "Recommendation: say which option and why", "Implementation: say what it would take to do it"],
     ("third", "present", "plain professional", "some", 600, 2500), "figures name their source and year; each option is described fairly",
     ["Options are presented fairly, including the one not recommended"],
     [("The recommendation is not at the top", "conclusion_first"), ("Evidence is not sourced", "citations")]),
    ("case-study", "case study", [], "analytical", "show what one real case teaches", "practitioners who face similar cases", (TP, LK, LK),
     ["Summary: say what the case is and its main lesson", "Background: describe the setting and the problem",
      "What was done: tell the events and decisions in order @linking", "Results: say what happened, with measures",
      "Lessons: say what carries over to other cases and what does not"],
     ("third", "past", "plain professional", "some", 800, 4000), "events and figures come from records or named accounts",
     ["People and organisations are named only with consent or from public record"],
     [("It tells the story without drawing the lesson", ""), ("Results have no measures or sources", "citations")]),
    ("review", "review", ["book review", "product review", "film review"], "analytical", "tell a reader whether something is worth their time or money, and why", "a member of the public deciding", (CT, IX, CT),
     ["Verdict: say what is being reviewed and the judgement, at the start", "What it is: describe it briefly, without spoiling it",
      "Strengths: say what it does well, with examples", "Weaknesses: say where it falls short, with examples", "Who it is for: say who should and should not choose it"],
     ("first", "present", "conversational", "some", 300, 1500), "judgements rest on stated examples from the thing reviewed",
     ["Any interest the reviewer has in the thing reviewed is declared"],
     [("The verdict is withheld to the end", "conclusion_first")]),

    ("legal-memo", "legal memo", ["legal memorandum", "memorandum of law"], "legal", "tell a lawyer what the law says about a client's question and how it is likely to apply", "a supervising lawyer", (TP, TP, LK),
     ["Heading: To, From, Date, Re", "Question presented: state the legal question on these facts", "Brief answer: answer it directly, with the main reason",
      "Facts: state the relevant facts neutrally, including the unfavourable ones", "Discussion: for each issue give the rule, apply it to the facts, and conclude",
      "Conclusion: say the likely outcome and what to do next"],
     ("third", "present", "formal", "some", 1000, 5000), "every statement of law cites its authority; facts are distinguished from inference", LEGAL,
     [("It does not say it is a draft for a lawyer", "lawyer_review"), ("Statements of law are not cited", "citations"), ("The answer is not given early", "conclusion_first")]),
    ("legal-brief", "brief", ["legal brief", "appellate brief", "trial brief"], "legal", "persuade a court to rule for one side", "a judge", (TP, TP, LK),
     ["Questions presented: state the issues as the court should see them", "Statement of the case: tell the facts and the procedure accurately, with record references",
      "Summary of argument: preview the argument's points in order", "Argument: under one heading per point, give the rule, apply it and answer the other side",
      "Conclusion: state exactly the relief sought"],
     ("third", "present", "formal", "none", 2000, 12000), "every statement of law and of record is cited; adverse authority is disclosed", LEGAL + ["Authority against the argument is disclosed to the court"],
     [("It does not say it is a draft for a lawyer", "lawyer_review"), ("Statements of law are not cited", "citations")]),
    ("case-analysis", "case analysis", ["case brief", "case note"], "legal", "record what a decided case held and why", "a law student or lawyer", (IX, CT, CT),
     ["Citation: name the case, the court and the year", "Facts: state the facts that mattered to the decision", "Issue: state the legal question the court answered",
      "Holding: state the court's answer", "Reasoning: explain why the court decided as it did", "Significance: say what the case changed or confirms"],
     ("third", "past", "formal", "none", 300, 1500), "holdings are stated as the court stated them; the writer's own view is kept apart", LEGAL[:1],
     [("Statements are not tied to the decision", "citations")]),
    ("contract", "contract", ["agreement", "terms and conditions"], "legal", "record what the parties have agreed so that it can be relied on and enforced", "the parties, and a court if they fall out", (IX, IX, CT),
     ["Parties and date: name each party exactly and the date", "Definitions: define every term the contract relies on",
      "Obligations: state what each party must do, one obligation to a clause", "Payment: state the amount, the timing and the method",
      "Term and termination: state when it starts, when it ends and how it may be ended", "Liability and disputes: state the limits of liability, the governing law and how disputes are settled",
      "Signatures: provide for each party to sign"],
     ("third", "present", "formal", "none", 500, 10000), "each term means one thing throughout; nothing depends on what a party meant to say", LEGAL,
     [("It does not say it is a draft for a lawyer", "lawyer_review"), ("Terms are not defined", "defined_terms")]),
    ("policy", "policy", ["company policy", "policy document"], "legal", "say what people in an organisation must and must not do, and what happens otherwise", "everyone the policy binds", (IX, IX, CT),
     ["Purpose: say what the policy is for", "Scope: say whom and what it covers", "Definitions: define the terms it uses",
      "Rules: state each rule separately and plainly", "Responsibilities: say who must do what", "Breaches: say what happens when a rule is broken",
      "Review: say who owns the policy and when it is next reviewed"],
     ("third", "present", "plain formal", "none", 300, 4000), "each rule can be followed and checked", LEGAL[:1],
     [("It does not say it is a draft for a lawyer", "lawyer_review"), ("Terms are not defined", "defined_terms")]),

    ("news-report", "news report", ["news story", "news article"], "journalism", "tell the public what happened, accurately and quickly", "a member of the public who may read one paragraph", (LK, LK, LK),
     ["Headline: say what happened in a few plain words", "Lead: say what happened, to whom, when and where, in one sentence",
      "Key details: give the next most important facts, each attributed", "Background: give what a reader needs to understand it", "?What next: say what is expected to happen"],
     ("third", "past", "plain", "none", 200, 900), "every fact is attributed; quotations are exact; numbers have a source", NEWS,
     [("The first sentence does not carry the news", "lead_5w"), ("Facts are not attributed", "attribution"), ("Opinion or promotional wording", "no_vague_praise")]),
    ("crime-report", "crime report", ["crime story", "court report"], "journalism", "report an offence or a court hearing without prejudging anyone", "the public", (LK, LK, LK),
     ["Headline: say what is alleged or what the court did", "Lead: say what happened, when and where, and what the police or court have said",
      "What is known: give the confirmed facts, each attributed to police, court or a named witness", "The accused: give only what is charged or found, as charged or found",
      "Background: give earlier events that are on record", "What next: give the next hearing or stage"],
     ("third", "past", "plain", "none", 200, 800), "every claim is attributed to police, court record or a named person", NEWS + [
         "A person accused is not called guilty: an allegation is reported as an allegation until a court decides",
         "Victims of sexual offences and children are not identified"],
     [("An accusation is reported as fact", "allegation_marked"), ("Facts are not attributed", "attribution"), ("The first sentence does not carry the news", "lead_5w")]),
    ("weather-report", "weather report", ["weather forecast", "forecast"], "journalism", "tell people what weather to expect and what to do about it", "the public, planning the next day or days", (LK, IX, CT),
     ["Headline: say the main thing to expect", "Outlook: say what is expected, where and when, the most important first",
      "Details: give temperatures, wind, rain or snow with times and amounts", "Warnings: state any official warning exactly as issued, with its source",
      "Advice: say what people should do"],
     ("third", "future", "plain", "some", 100, 500), "figures come from the named forecasting service; a warning is quoted as issued", NEWS[:2] + [
         "An official warning is given exactly as issued and attributed to the service that issued it"],
     [("The forecast does not say how likely or when", "hedged_forecast"), ("The source of the forecast is not named", "attribution")]),
    ("feature", "feature", ["feature article", "feature story", "profile"], "journalism", "let a reader understand a person, place or issue in depth", "a reader with time, who must be drawn in", (LK, LK, LK),
     ["Opening: begin with a scene, a person or a question that carries the subject", "The point: say, soon, what the piece is about and why it matters now",
      "Body: develop it through scenes, voices and facts, each leading to the next", "Wider meaning: set the subject in its larger setting",
      "Ending: close on an image or a line that completes the opening"],
     ("third", "present", "narrative", "some", 800, 4000), "every fact and quotation is real and attributed; scenes are reported, not imagined", NEWS,
     [("People are not quoted or sourced", "attribution")]),
    ("explainer", "explainer", ["explainer article", "backgrounder"], "journalism", "make a complicated subject in the news understandable", "an intelligent reader new to the subject", (TP, IX, LK),
     ["The question: say what the subject is and why it is in the news", "The short answer: answer it in a paragraph",
      "How it works: explain it part by part, in plain words", "What is disputed: say fairly where people disagree", "What happens next: say what to watch for"],
     ("third", "present", "plain", "some", 500, 2000), "facts are sourced; where experts disagree, both views are given", NEWS[:2],
     [("The short answer is not near the top", "conclusion_first"), ("Facts are not sourced", "attribution")]),

    ("scene", "scene", [], "fiction", "show one stretch of continuous action in which something changes", "a reader of the story", (LK, LK, LK),
     ["Opening: put a character in a place, wanting something", "Conflict: put something in the way", "Turn: let something change that cannot be undone",
      "Exit: end on the new situation, before it is explained"],
     ("third", "past", "narrative", "free", 300, 2000), "consistent with the story bible: who knows what, where everyone is, what has already happened", [],
     [("Nothing changes between the start and the end", "scene_turns"), ("No one speaks", "dialogue_present")]),
    ("short-story", "short story", ["story"], "fiction", "give a reader one complete experience of a character under pressure", "a reader of fiction", (LK, LK, LK),
     ["Opening: establish who, where and what is wanted, in motion", "Complication: raise an obstacle that matters", "Rising action: let each attempt make things harder or reveal more",
      "Climax: force the choice the story has been heading for", "Ending: show what has changed, without explaining it"],
     ("third", "past", "narrative", "free", 1000, 7500), "consistent with the story bible; every promise planted early is kept, often with a turn", [],
     [("Nothing changes for the character", "scene_turns"), ("No one speaks", "dialogue_present")]),
    ("novel-chapter", "novel chapter", ["chapter"], "fiction", "advance the story and leave the reader wanting the next chapter", "a reader of the novel", (LK, LK, LK),
     ["Hook: begin in a moment that raises a question", "Scenes: play out one or more scenes, each changing something", "Development: move the plot, the character or the reader's knowledge forward",
      "Close: end on a question, a decision or a reversal"],
     ("third", "past", "narrative", "free", 1500, 6000), "consistent with the story bible and with every earlier chapter", [],
     [("Nothing changes by the end of the chapter", "scene_turns")]),
    ("monologue", "monologue", ["soliloquy"], "fiction", "let one character speak at length and be changed by speaking", "an actor and an audience", (LK, LK, LK),
     ["Trigger: begin from something that has just happened to the speaker", "Want: make clear whom they are speaking to and what they want from them",
      "Shift: let the speaker discover or admit something part-way through", "Landing: end somewhere different from the start"],
     ("first", "present", "spoken", "free", 150, 700), "true to the character's voice, knowledge and situation in the story bible", [],
     [("The speaker ends where they began", "scene_turns")]),
    ("dialogue", "dialogue", ["conversation"], "fiction", "let two or more characters pursue different wants through what they say and do not say", "a reader or audience", (LK, LK, LK),
     ["Entry: begin late, with the characters already wanting different things", "Exchange: let each line answer the last while pursuing the speaker's own aim",
      "Subtext: keep the real subject under the spoken one", "Turn: let the balance between them shift"],
     ("third", "present", "spoken", "free", 150, 1500), "each voice is distinct and consistent with the character in the story bible", [],
     [("There is almost no speech", "dialogue_present"), ("The balance between the speakers never shifts", "scene_turns")]),
    ("script", "script", ["screenplay", "play", "teleplay"], "fiction", "set down a drama to be performed: what is seen and what is said", "actors, a director and a crew", (LK, LK, LK),
     ["Scene heading: say where and when", "Action: say only what can be seen and heard", "Dialogue: give each line under the name of its speaker",
      "Turn: let the scene change something", "Out: cut when the scene has done its work"],
     ("third", "present", "spoken", "free", 300, 5000), "consistent with the story bible; nothing is written that cannot be seen or heard", [],
     [("There is almost no speech", "dialogue_present"), ("Nothing changes in the scene", "scene_turns")]),
]


UNHEADED = ("abstract", "executive-summary", "review", "email", "letter", "cover-letter", "press-release", "speech", "blog-post", "op-ed",
            "obituary", "product-description", "personal-statement", "social-post", "announcement", "poem")

P1, P3 = "first", "third"
G += [
    ("email", "email", ["e-mail"], "everyday", "get one thing done by message", "a busy person who decides in seconds whether to act", (CT, CT, CT),
     ["Subject: say the point in the subject line", "Opening: say why you are writing and what you want, at once", "Details: give only what the reader needs to act",
      "Close: say what happens next and by when, then sign off"],
     (P1, "present", "plain", "none", 50, 300), "names, dates and amounts are exact", [], [("The request is not in the opening", "conclusion_first")]),
    ("letter", "letter", ["formal letter", "business letter"], "everyday", "put something on record, politely and clearly", "a named person or office", (CT, LK, LK),
     ["Heading: the sender's address, the date, the recipient's name and address", "Opening: say why you are writing", "Body: give the facts or the request in order",
      "Close: say what you would like to happen, then sign off"],
     (P1, "present", "polite", "none", 120, 500), "dates, references and amounts are exact", [], [("The purpose is not in the opening", "conclusion_first")]),
    ("cover-letter", "cover letter", ["application letter", "covering letter"], "everyday", "win an interview for a named job", "a recruiter with a pile of applications", (CT, CT, LK),
     ["Opening: name the job and say in a sentence why you fit it", "Evidence: give two or three things you have done that this job needs, with results",
      "Fit: say why this employer", "Close: ask for the interview and say how to reach you"],
     (P1, "present", "professional", "none", 200, 400), "every claim about yourself is true and specific", ["Nothing about your experience is invented or inflated"],
     [("Empty or promotional wording", "no_vague_praise")]),
    ("resume", "résumé", ["resume", "cv", "curriculum vitae"], "everyday", "show at a glance that a person is qualified", "a recruiter who gives it under a minute", (IX, IX, CT),
     ["Contact: name and how to reach you", "Summary: say in two lines what you do and your strongest result", "Experience: list each role, newest first, with what you achieved",
      "Education: list qualifications, newest first", "?Skills: list the skills the job asks for"],
     (P3, "past", "terse", "none", 250, 800), "dates, titles and results are true and checkable", ["Nothing is invented: no role, date, title or result"],
     [("Empty or promotional wording", "no_vague_praise")]),
    ("press-release", "press release", ["news release", "media release"], "everyday", "give journalists a story they can use as it stands", "a journalist deciding in one paragraph", (LK, LK, LK),
     ["Headline: say the news in plain words", "Lead: say who is doing what, when and where, and why it matters", "Details: give the facts that support it",
      "Quotation: give one named person's words", "About: say who the organisation is", "Contact: say whom to call"],
     (P3, "present", "plain", "none", 250, 600), "every fact is true and attributable; the quotation was really said and approved", ["Nothing is claimed that the organisation cannot support"],
     [("The first sentence does not carry the news", "lead_5w"), ("Promotional wording", "no_vague_praise")]),
    ("speech", "speech", ["talk", "address", "toast", "eulogy"], "everyday", "move a listening audience to feel, understand or act", "people who hear it once and cannot re-read", (TP, LK, LK),
     ["Opening: win attention and say what the speech is about", "Preview: tell them the points to come", "Points: make each point with a story or example, and say when you move on",
      "Close: return to the opening and leave one line to remember"],
     (P1, "present", "spoken", "none", 300, 2500), "stories and figures are true; quotations are exact and credited", [], [("Sentences too long to say aloud", "")]),
    ("blog-post", "blog post", ["blog", "article", "web article"], "everyday", "give a web reader something useful or interesting enough to finish", "a reader who arrived by search and may leave at once", (TP, IX, LK),
     ["Title: say what the reader will get", "Opening: say the point and why it matters to this reader", "Sections: develop it under plain subheadings",
      "Close: say what to do or think next"],
     (P1, "present", "conversational", "some", 500, 1800), "facts are linked or sourced", [], [("The point is not near the top", "conclusion_first")]),
    ("op-ed", "op-ed", ["opinion piece", "opinion article", "editorial", "column"], "everyday", "persuade the public of one opinion on a matter in the news", "a general reader who may disagree", (LK, LK, LK),
     ["Hook: tie the subject to something happening now", "Position: state the opinion plainly", "Reasons: give the evidence, strongest last",
      "The other side: state the best objection and answer it", "Close: say what should be done"],
     (P1, "present", "plain", "none", 600, 900), "facts are accurate and sourced; opinion is marked as opinion", ["Facts are accurate; any interest the writer has is declared"],
     [("The position is not stated early", "conclusion_first")]),
    ("newsletter", "newsletter", [], "everyday", "keep a group informed and wanting the next issue", "members or customers who chose to receive it", (IX, IX, CT),
     ["Top story: lead with the most useful item", "Items: give each further item its own short section", "Dates: list what is coming", "Contact: say how to reply or unsubscribe"],
     (P1, "present", "friendly", "none", 300, 1200), "dates, names and links are right", [], []),
    ("announcement", "announcement", ["notice"], "everyday", "tell people one thing that affects them", "everyone it affects", (CT, CT, CT),
     ["Headline: say what is happening", "What: say what is changing or happening", "When and where: give the date, time and place", "Who: say whom it affects",
      "What to do: say what the reader should do next"],
     (P3, "present", "plain", "none", 60, 300), "date, time and place are exact", [], [("What is happening is not said at once", "conclusion_first")]),
    ("minutes", "meeting minutes", ["minutes"], "everyday", "record what a meeting decided and who will do what", "members, including those who were absent", (IX, IX, CT),
     ["Heading: the meeting, date, place and who attended", "Items: for each item, say what was discussed in a line and what was decided",
      "Actions: list each action with its owner and date", "Next meeting: give the date"],
     (P3, "past", "plain", "none", 200, 1500), "decisions and names are recorded as they were", ["Decisions are recorded as made, not as the writer would have wished"], []),
    ("agenda", "agenda", ["meeting agenda"], "everyday", "let people prepare for a meeting and keep it on time", "the people attending", (IX, IX, CT),
     ["Heading: the meeting, date, time and place", "Items: list each item with its purpose, owner and time allowed", "Papers: say what to read beforehand"],
     (P3, "present", "terse", "none", 60, 400), "times add up; names are right", [], []),
    ("job-description", "job description", ["job posting", "job advert"], "everyday", "attract the right applicants and tell them truthfully what the job is", "someone deciding whether to apply", (IX, IX, CT),
     ["Title and summary: say what the job is and why it exists", "Responsibilities: list what the person will do", "Requirements: list what is truly needed, apart from what is merely welcome",
      "Terms: say pay, hours, place and how to apply"],
     ("second", "present", "plain", "none", 250, 700), "pay, hours and requirements are true", ["Requirements are those the job needs: none excludes people for reasons the job does not need"],
     [("Empty or promotional wording", "no_vague_praise")]),
    ("faq", "FAQ", ["frequently asked questions", "q&a"], "everyday", "answer the questions people really ask, where they can find them", "someone with one question", (IX, IX, CT),
     ["Questions: put each question as the reader would ask it, most asked first", "Answers: answer each in the first sentence, then add what is needed"],
     ("second", "present", "plain", "none", 200, 2000), "answers are correct and current", [], []),
    ("product-description", "product description", [], "everyday", "tell a buyer what a thing is, what it does for them and whether it fits", "a shopper comparing", (CT, CT, CT),
     ["What it is: say what the product is and whom it is for", "Benefits: say what it does for the buyer", "Details: give the facts — size, materials, what is in the box"],
     ("second", "present", "plain", "none", 60, 300), "every claim about the product is true and can be shown", ["No claim about the product is false or cannot be supported"],
     [("Empty or promotional wording", "no_vague_praise")]),
    ("readme", "README", ["read me"], "technical", "let a newcomer understand a project and get it running", "a developer seeing the project for the first time", (IX, LK, LK),
     ["What it is: say what the project does and for whom", "Install: give the steps to install it", "Use: show the simplest working example",
      "?Configure: list the settings that matter", "Help and licence: say where to ask and under what licence it is"],
     ("second", "present", "plain", "none", 150, 1500), "every command was run as written", [], [("Steps are not numbered", "steps_numbered")]),
    ("release-notes", "release notes", ["changelog", "change log"], "technical", "tell users what changed and what they must do", "a user deciding whether and how to update", (IX, IX, CT),
     ["Summary: say the version and the most important change", "New: list what was added", "Changed: list what behaves differently", "Fixed: list what was repaired",
      "?Action needed: say what the user must do"],
     (P3, "past", "terse", "none", 80, 800), "each change is real and described as the user will see it", ["A change that can break the user's work is stated first, not buried"], []),
    ("lab-report", "lab report", ["laboratory report"], "learning", "record an experiment so that it can be judged and repeated", "a teacher or fellow student", (TP, IX, LK),
     ["Aim: say what the experiment set out to find", "Method: say what was done, exactly", "Results: give the measurements, with units",
      "Discussion: say what the results mean and how sure they are", "Conclusion: answer the aim"],
     (P3, "past", "formal", "some", 400, 2500), "measurements are reported as taken, with units and uncertainty", ["Results are reported as measured: none is altered or left out to fit"],
     [("Results have no stated basis", "citations")]),
    ("lesson-plan", "lesson plan", [], "learning", "let a teacher run a lesson that gets learners to a stated goal", "the teacher, or a substitute", (IX, LK, LK),
     ["Objective: say what learners will be able to do by the end", "Materials: list what is needed", "Steps: give the activities in order, with the time for each",
      "Check: say how the teacher will know the objective was met", "?Follow-up: give homework or the next lesson"],
     ("second", "present", "plain", "none", 200, 1200), "times add up to the lesson; materials are complete", [], [("Steps are not numbered", "steps_numbered")]),
    ("study-guide", "study guide", ["revision guide", "summary notes"], "learning", "let a learner review a subject and test themselves", "a learner before an exam", (IX, IX, CT),
     ["Overview: name the subject and its parts", "Key ideas: explain each part briefly, with one example", "Terms: define the terms to know",
      "Questions: give questions to test understanding"],
     ("second", "present", "plain", "none", 300, 3000), "every statement matches the source being studied", [], []),
    ("personal-statement", "personal statement", ["statement of purpose", "admissions essay"], "learning", "show a selector who the applicant is and why they should be chosen", "an admissions reader with many to read", (LK, LK, LK),
     ["Opening: begin with something specific that shows why this subject", "Evidence: show what you have done, and what you learned from it",
      "Fit: say why this course or place", "Close: say what you will do with it"],
     (P1, "present", "personal", "none", 400, 1000), "everything said about yourself is true", ["Nothing is invented, and the words are the applicant's own"],
     [("Empty or promotional wording", "no_vague_praise")]),
    ("grant-proposal", "grant proposal", ["grant application", "funding application"], "business", "win funding by showing the work matters, can be done and is worth the cost", "reviewers scoring against the funder's criteria", (TP, IX, LK),
     ["Summary: say the need, the work, the result and the amount", "Need: show the problem with evidence", "Aims: state what the work will achieve, measurably",
      "Method: say how it will be done, by whom and when", "Budget: give the cost, itemised and justified", "Evaluation: say how success will be measured"],
     (P1, "future", "professional", "none", 1000, 6000), "need and capacity are supported by evidence with sources", ["Costs, capacity and results are stated truthfully"],
     [("The ask is not stated at the start", "conclusion_first"), ("Evidence is not sourced", "citations")]),
    ("obituary", "obituary", [], "journalism", "record a life and tell the community of a death", "family, friends and the public", (CT, LK, LK),
     ["Announcement: say who has died, when, where and at what age", "Life: tell the life in order — birth, family, work, what they were known for",
      "Survivors: name the close family", "Service: give the arrangements"],
     (P3, "past", "respectful", "none", 150, 800), "names, dates and places are confirmed with the family or record", ["Every fact is confirmed; the cause of death is given only with the family's agreement"],
     []),
    ("social-post", "social media post", ["social post", "tweet", "caption"], "everyday", "say one thing so that people stop, read and respond", "someone scrolling past", (CT, CT, CT),
     ["Hook: say the point in the first line", "Body: add the one thing that makes it worth reading", "?Call: say what to do — reply, read, come"],
     (P1, "present", "conversational", "none", 10, 120), "what is said is true; links go where they say", ["Nothing false is stated as fact"], []),
    ("poem", "poem", ["verse"], "fiction", "make an experience felt through image, sound and line", "a reader who will read it more than once", (LK, LK, LK),
     ["Opening image: begin in something seen, heard or felt", "Development: let each image or turn of thought lead to the next", "Turn: let the poem change direction",
      "Close: end on an image or line that stays, not an explanation"],
     (P1, "present", "poetic", "free", 20, 400), "true to its own images; nothing is explained that the images already say", [], []),
]


# books: the user's aim is every kind of book a reader can buy. These are the FORMS; the subject comes from the field (FIELDS)
G += [
    ("book-proposal", "book proposal", ["nonfiction book proposal"], "books", "persuade a publisher that a book should exist and that this author should write it", "an agent or editor deciding in minutes", (TP, IX, LK),
     ["Overview: say what the book is, why now and why you", "Readers: say who will buy it and how many there are", "Competing books: name the nearest books and how this one differs",
      "Author: say why you are the person to write it", "Chapter outline: give each chapter in a paragraph", "Sample: include one finished chapter"],
     (P1, "present", "professional", "none", 2500, 12000), "figures about readers and competing books are real and sourced", ["Sales figures and credentials are true"],
     [("Promotional wording", "no_vague_praise")]),
    ("nonfiction-chapter", "non-fiction book chapter", ["nonfiction chapter", "book chapter"], "books", "carry one stage of a book's argument or story and make the reader want the next", "a general reader who chose the book", (TP, LK, LK),
     ["Opening: begin with a scene, a question or a claim that earns attention", "Promise: say what this chapter will show", "Body: develop it in sections, each leading to the next",
      "Evidence: ground each claim in a source, a case or a person", "Close: say what has been shown and open the next chapter's question"],
     (P3, "present", "narrative", "some", 3000, 8000), "every fact, figure and quotation has a source in the notes", ["Nothing is presented as fact that is not sourced; people are quoted accurately"],
     [("Sources are not given", "citations")]),
    ("how-to-chapter", "how-to book chapter", ["advice chapter", "self-help chapter"], "books", "get a reader to do one thing differently", "a reader who wants a result, not a theory", (TP, LK, LK),
     ["The problem: name the difficulty as the reader feels it", "The principle: give the one idea that solves it", "The method: give the steps to apply it",
      "Example: show someone doing it", "Do this now: give one action to take today"],
     ("second", "present", "plain", "none", 2000, 6000), "advice rests on stated evidence or experience; health, legal or money advice says to consult a professional",
     ["Advice on health, law or money says plainly that it does not replace a professional"], [("Steps are not numbered", "steps_numbered")]),
    ("memoir-chapter", "memoir chapter", ["memoir", "autobiography chapter"], "books", "let a reader live through part of a real life and understand it", "a general reader", (LK, LK, LK),
     ["Scene: begin inside a moment", "Then: let the events unfold in order", "Reflection: say what the writer understands now that they did not then",
      "Close: end on a change, not a summary"],
     (P1, "past", "narrative", "free", 2000, 7000), "true as the writer remembers it; other people are treated fairly", ["It is the writer's own life and it is told truthfully; living people are treated fairly"],
     [("Nothing changes by the end", "scene_turns")]),
    ("biography-chapter", "biography chapter", ["biography"], "books", "tell part of another person's life accurately and vividly", "a general reader", (LK, LK, LK),
     ["Setting: place the person in a time and place", "Events: tell what happened, in order, from the record", "Character: show the person through what they did and said",
      "Meaning: say what this period made of them"],
     (P3, "past", "narrative", "some", 3000, 8000), "every event and quotation comes from a cited record or interview", ["Nothing is invented: no scene, thought or quotation without a source"],
     [("Sources are not given", "citations")]),
    ("picture-book", "children's picture book", ["picture book", "children's story", "childrens book"], "books", "give a young child a story to hear and see, again and again", "a child of three to seven, and the adult reading aloud", (LK, LK, LK),
     ["Meet: introduce one character with one want", "Try: let them try and fail, three times or so", "Turn: let them find their own way", "Home: end safe, with a line worth repeating"],
     (P3, "past", "simple", "free", 200, 800), "consistent with the pictures; every word a small child can follow by ear", ["Suitable for a young child: nothing frightening is left unresolved"],
     [("Nothing changes for the character", "scene_turns")]),
    ("young-adult-chapter", "young adult novel chapter", ["ya chapter", "young adult chapter", "middle grade chapter"], "books", "carry a young reader through a story that takes them seriously", "a reader of twelve to eighteen", (LK, LK, LK),
     ["Hook: begin with the character in trouble or in doubt", "Scenes: let each scene raise the stakes", "Voice: keep close to what the character thinks and notices",
      "Close: end on a decision or a discovery"],
     (P1, "present", "narrative", "free", 1500, 5000), "consistent with the story bible", [], [("Nothing changes by the end of the chapter", "scene_turns"), ("No one speaks", "dialogue_present")]),
    ("textbook-chapter", "textbook chapter", ["textbook section", "course chapter"], "books", "teach a body of knowledge so that a student can use it", "a student meeting the subject for the first time", (TP, IX, IX),
     ["Objectives: say what the student will be able to do", "Concepts: explain each idea in order, each with a worked example", "Summary: restate the main points",
      "Key terms: define them", "Exercises: give problems that test each objective"],
     (P3, "present", "plain", "none", 3000, 10000), "every statement matches the accepted knowledge of the field, with sources for data", ["Content is accurate to the field's accepted knowledge"],
     [("Sources for data are not given", "citations")]),
]

# ---------------------------------------------------------------------------------------------- fields: the subject a document is written in
# The user's aim: "all academic disciplines, all topics - universally". A document is a FORM (its genre) written in a FIELD.
# The field carries what its community expects: how sources are cited and what counts as evidence. The citation system named
# is the one customary in the field; a publisher's or teacher's own guide always overrides it. A field is a row: add them freely.
# (id, name, group, customary citation system, what counts as evidence)
FIELDS = [
    ("general", "General", "General", "name the source in the sentence", "named, checkable sources"),
    ("literature", "Literature", "Humanities", "MLA", "close reading of the text, quoted exactly"),
    ("history", "History", "Humanities", "Chicago notes and bibliography", "primary sources, weighed against each other"),
    ("philosophy", "Philosophy", "Humanities", "Chicago or MLA", "argument: premises stated, objections answered"),
    ("religion", "Religion and theology", "Humanities", "Chicago; scripture by book, chapter and verse", "texts and their interpretation, traditions named"),
    ("languages", "Languages and linguistics", "Humanities", "APA or the Unified Style Sheet for Linguistics", "examples from the language, glossed"),
    ("classics", "Classics", "Humanities", "Chicago; ancient works by standard book and line", "ancient texts and material evidence"),
    ("art-history", "Art history", "Humanities", "Chicago", "the work itself, described and compared"),
    ("music", "Music", "Arts", "Chicago", "the score or recording, cited by bar or time"),
    ("film-media", "Film and media studies", "Arts", "MLA or Chicago", "the work, cited by scene or time"),
    ("psychology", "Psychology", "Social sciences", "APA", "empirical studies: method, sample and effect reported"),
    ("sociology", "Sociology", "Social sciences", "ASA", "empirical data and stated theory"),
    ("anthropology", "Anthropology", "Social sciences", "Chicago author-date", "fieldwork and ethnographic record"),
    ("political-science", "Political science", "Social sciences", "APSA", "data, cases and stated theory"),
    ("economics", "Economics", "Social sciences", "Chicago author-date", "data and models, assumptions stated"),
    ("education", "Education", "Social sciences", "APA", "studies of learners, context described"),
    ("geography", "Geography", "Social sciences", "APA or Harvard", "spatial data and maps, sources named"),
    ("communication", "Communication and journalism", "Social sciences", "APA; AP style for news", "attributed sources"),
    ("law", "Law", "Professions", "The Bluebook (US); OSCOLA (UK)", "authority: statute, case and regulation, pinpoint cited"),
    ("business", "Business and management", "Professions", "APA or Harvard", "data, cases and financial records"),
    ("accounting-finance", "Accounting and finance", "Professions", "APA or Harvard", "financial statements and standards"),
    ("marketing", "Marketing", "Professions", "APA or Harvard", "market data and customer research"),
    ("medicine", "Medicine", "Health", "AMA or Vancouver", "clinical evidence, level of evidence stated"),
    ("nursing", "Nursing", "Health", "APA", "clinical evidence and practice guidelines"),
    ("public-health", "Public health", "Health", "AMA or Vancouver", "population data and studies"),
    ("biology", "Biology", "Sciences", "CSE", "experiment and observation, methods repeatable"),
    ("chemistry", "Chemistry", "Sciences", "ACS", "experimental data with conditions and uncertainty"),
    ("physics", "Physics", "Sciences", "AIP or APS", "measurement and derivation, uncertainty stated"),
    ("mathematics", "Mathematics", "Sciences", "AMS", "proof"),
    ("statistics", "Statistics", "Sciences", "APA or ASA", "data, method and uncertainty"),
    ("earth-science", "Earth and environmental science", "Sciences", "AGU or APA", "field and instrument data"),
    ("astronomy", "Astronomy", "Sciences", "AAS", "observation and model"),
    ("computer-science", "Computer science", "Engineering and technology", "IEEE or ACM", "proof, experiment or working system, reproducible"),
    ("engineering", "Engineering", "Engineering and technology", "IEEE", "calculation, test and standard"),
    ("architecture", "Architecture and design", "Engineering and technology", "Chicago", "the built work, drawings and codes"),
    ("agriculture", "Agriculture", "Sciences", "CSE or APA", "trials and field data"),
    ("sport", "Sport and exercise science", "Health", "APA", "measured performance and studies"),
    ("cooking", "Food and cooking", "Everyday", "name the source in the sentence", "tested quantities, times and temperatures"),
    ("travel", "Travel", "Everyday", "name the source in the sentence", "first-hand visit, dated"),
    ("technology", "Consumer technology", "Everyday", "link to the source", "tested behaviour and specifications"),
    ("personal-finance", "Personal finance", "Everyday", "name the source in the sentence", "figures with dates and sources; not personal advice"),
    ("parenting", "Parenting and family", "Everyday", "name the source in the sentence", "named research and experience, kept apart"),
]

# ---------------------------------------------------------------------------------------------- style templates (the growing library)
# a template is a named profile: the numbers a draft is asked to come near (apps/shell/writing.py measures the same ones).
# QueryBook's own templates describe a manner of writing — none copies a named author. A user's own style is measured from
# their own sample and saved beside these in their data folder.
# (id, name, about, sentence words, spread, short share, long share, word letters, long-word share, I/we, you, questions,
#  contractions, hedges, dashes per sentence, semicolons per sentence, sentences to a paragraph)
STYLES = [
    ("plain", "Plain", "Short common words, one idea to a sentence, nothing ornamental.", 14, 6, .25, .05, 4.4, .08, .005, .010, .02, .004, .003, .03, .00, 4),
    ("formal", "Formal", "Measured and impersonal, exact words, no contractions.", 23, 8, .05, .35, 5.3, .22, .000, .000, .00, .000, .008, .03, .12, 5),
    ("conversational", "Conversational", "As one person talking to another: you, contractions, a question now and then.", 13, 7, .35, .04, 4.2, .06, .030, .030, .10, .030, .006, .15, .00, 3),
    ("executive", "Executive", "The conclusion first, short paragraphs, no hedging, every word working.", 15, 5, .20, .03, 4.8, .14, .012, .004, .01, .000, .001, .02, .00, 3),
    ("journalistic", "Journalistic", "Most important first, short sentences and paragraphs, concrete nouns and active verbs.", 18, 7, .15, .12, 4.7, .12, .000, .000, .01, .002, .003, .06, .00, 2),
    ("academic", "Academic", "Careful claims, hedged where the evidence is uncertain, long sentences held together by structure.", 26, 9, .03, .45, 5.5, .26, .004, .000, .01, .000, .015, .04, .15, 6),
    ("technical", "Technical", "Exact and consistent: one name for one thing, short declarative sentences, no flourish.", 16, 5, .18, .06, 5.0, .18, .000, .008, .00, .000, .002, .01, .02, 4),
    ("persuasive", "Persuasive", "Direct address, rhythm, short sentences for weight, a question to carry the reader.", 15, 9, .32, .08, 4.5, .10, .020, .020, .12, .010, .001, .12, .02, 3),
    ("storyteller", "Storyteller", "Scene and movement: varied sentences, concrete detail, the voice of someone telling it.", 16, 11, .30, .15, 4.3, .07, .015, .002, .05, .012, .004, .20, .04, 5),
    ("warm", "Warm and personal", "Kind and direct, as to someone known: I and you, plain words, nothing stiff.", 14, 6, .28, .04, 4.2, .05, .035, .030, .04, .020, .006, .10, .00, 3),
    ("legal-formal", "Legal formal", "Precise and unambiguous: defined terms used unchanged, complete sentences, no figure of speech.", 28, 10, .02, .50, 5.4, .24, .000, .000, .00, .000, .002, .02, .20, 4),
    ("instructional", "Instructional", "The reader is doing the task now: one action to a sentence, you, the present tense.", 12, 4, .35, .01, 4.5, .09, .000, .035, .01, .004, .001, .02, .00, 3),
]

# ---------------------------------------------------------------------------------------------- sources to learn from, once
# The user's decisions: "All sources - we will eventually use 100s of sources to learn; only once", and "Find the top 10
# legal sources - use top universities and law repositories". This is the register. NOTHING has been collected: a source
# is learned from one page at a time (AI text gen → Learn from a source), after its robots rules are read; its rules are
# kept in QueryBook's own words with the page's address — no passage of the source is kept. An address is given only where
# it was found by search on 2026-11-13; the rest are located at learning time. A licence is recorded from the site's own
# page when it is learned from, never from memory.
# (id, name, wave, families, address or "")
SOURCES = [
    ("purdue-owl", "Purdue Online Writing Lab", 1, "academic business technical", ""), ("unc", "UNC Writing Center", 1, "academic", ""),
    ("monash", "Monash — Excel at Writing", 1, "academic business", ""), ("uw-madison", "UW–Madison Writer's Handbook", 1, "academic", ""),
    ("georgetown-law", "Georgetown Law Writing Center — guides and handouts", 1, "legal",
     "https://www.law.georgetown.edu/academics/academic-resources/the-writing-center/guides-and-handouts/"),
    ("iet", "IET technical report guide", 2, "technical", ""), ("google-tw", "Google Technical Writing", 2, "technical", ""),
    ("microsoft-style", "Microsoft Writing Style Guide", 2, "technical", ""), ("digital-gov", "Digital.gov", 2, "technical everyday", ""),
    ("plain-language-center", "Center for Plain Language", 2, "business everyday", ""), ("nngroup", "Nielsen Norman Group", 2, "technical everyday", ""),
    ("stc", "Society for Technical Communication", 2, "technical", ""), ("george-mason", "George Mason University — white-paper guide", 2, "business", ""),
    ("uagc", "UAGC — white-paper guide", 2, "business", ""),
    ("harvard", "Harvard College Writing Center", 3, "academic", ""), ("manchester-phrasebank", "Manchester Academic Phrasebank (rules only: no phrases are kept)", 3, "academic", ""),
    ("usc", "USC research guides", 3, "academic", ""), ("toronto", "University of Toronto writing advice", 3, "academic", ""), ("scribbr", "Scribbr", 3, "academic", ""),
    ("texas-am", "Texas A&M University Writing Center", 3, "academic", ""), ("mit", "MIT writing resources", 3, "academic technical", ""),
    ("stanford-hume", "Stanford Hume Center", 3, "academic", ""), ("michigan-sweetland", "Michigan Sweetland Center", 3, "academic", ""),
    ("melbourne", "University of Melbourne", 3, "academic", ""), ("sydney", "University of Sydney", 3, "academic", ""),
    ("queensland", "University of Queensland", 3, "academic analytical", ""), ("edinburgh", "University of Edinburgh", 3, "academic", ""),
    ("oxford", "University of Oxford", 3, "academic", ""),
    ("poynter", "Poynter", 4, "journalism", ""), ("media-helping-media", "Media Helping Media", 4, "journalism", ""),
    ("journalism-university", "Journalism University", 4, "journalism", ""), ("ams", "American Meteorological Society", 4, "journalism", ""),
    ("stagemilk", "StageMilk", 5, "fiction", ""), ("gutenberg-fiction", "Project Gutenberg fiction (public domain) — exemplars to tag, not advice", 5, "fiction", ""),
    # the ten legal sources (universities and public law repositories), each address found by search on 2026-11-13
    ("columbia-law", "Columbia Law School Writing Center — legal writing resources", 6, "legal",
     "https://www.law.columbia.edu/academics/experiential/legal-writing/writing-center/legal-writing-resources"),
    ("duke-law", "Duke Law — legal writing resources", 6, "legal", "https://law.duke.edu/study/legalwriting/resources"),
    ("yale-law", "Yale (Poorvu Center) — writing resources for law students", 6, "legal",
     "https://poorvucenter.yale.edu/writing/writing-resources-for-graduate-students/writing-resources-for-law-students"),
    ("cornell-lii", "Cornell Legal Information Institute — Wex and the introduction to legal citation", 6, "legal", ""),
    ("maryland-law", "University of Maryland Carey Law — Legal Writing Center", 6, "legal", "https://law.umaryland.edu/academics/advising--support/legal-writing-center/"),
    ("cuny-law", "CUNY School of Law — Legal Writing Center, student resources", 6, "legal",
     "https://www.law.cuny.edu/academics/academic-resources-support/legal-writing-center/student-resources/"),
    ("sec-plain-english", "U.S. Securities and Exchange Commission — A Plain English Handbook", 6, "legal business", "https://www.sec.gov/pdf/handbook.pdf"),
    ("federal-register", "Office of the Federal Register — plain language and drafting legal documents", 6, "legal",
     "https://www.archives.gov/federal-register/write/plain-language"),
    ("uk-opc", "UK Office of the Parliamentary Counsel — drafting guidance", 6, "legal", "https://www.gov.uk/government/collections/the-office-of-the-parliamentary-counsel-guidance"),
    ("us-courts-drafting", "U.S. Courts — essentials for drafting clear legal rules", 6, "legal", "https://www.uscourts.gov/node/62078/"),
]
WAVES = {1: "Broad base", 2: "Technical and business", 3: "Academic depth", 4: "Journalism", 5: "Fiction and dramatic", 6: "Legal — the ten"}


def build():
    genres = []
    for gid, name, also, fam, purpose, reader, fw, secs, reg, evidence, constraints, failures in G:
        sections = []
        for s in secs:
            opt = s.startswith("?")
            s = s[1:] if opt else s
            over = ""
            if " @" in s:
                s, over = s.rsplit(" @", 1)
            sec_name, move = s.split(": ", 1)
            sec = {"name": sec_name, "move": move, "required": not opt}
            if over:
                sec["framework"] = over
            sections.append(sec)
        genres.append({"id": gid, "name": name, "also": also, "family": fam, "purpose": purpose, "reader": reader,
                       "headed": fam not in ("journalism", "fiction") and gid not in UNHEADED,
                       "frameworks": {"document": fw[0], "section": fw[1], "paragraph": fw[2]}, "sections": sections,
                       "register": {"person": reg[0], "tense": reg[1], "formality": reg[2], "hedging": reg[3], "words": [reg[4], reg[5]]},
                       "evidence": evidence, "constraints": constraints, "failures": [{"failure": f, "check": c} for f, c in failures],
                       "provenance": {"status": STATUS, "sources": [], "variants": []}})
    feats = ("sentence_words", "sentence_spread", "short_sentences", "long_sentences", "word_letters", "long_words", "first_person",
             "second_person", "questions", "contractions", "hedges", "dashes", "semicolons", "paragraph_sentences")
    styles = [{"id": r[0], "name": r[1], "about": r[2], "by": "QueryBook", "profile": dict(zip(feats, r[3:]))} for r in STYLES]
    sources = [{"id": i, "name": n, "wave": w, "wave_name": WAVES[w], "families": fam.split(), "url": u, "status": "listed — not yet learned from",
                "licence": "to be recorded from the site's own page when it is learned from"} for i, n, w, fam, u in SOURCES]
    doc = {"version": "genres-0.2", "status": STATUS,
           "families": [{"id": i, "name": n, "framework": f, "demand": d} for i, n, f, d in FAMILIES], "genres": genres,
           "styles": styles, "sources": sources,
           "fields": [{"id": i, "name": n, "group": g, "citation": c, "evidence": e} for i, n, g, c, e in FIELDS]}
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def main(argv):
    text = build()
    if "--check" in argv:
        try:
            with open(OUT, encoding="utf-8") as f:
                same = f.read() == text
        except OSError:
            same = False
        if not same:
            print("genres.json is out of date — run python tools/build_genres.py")
            return 1
        print("genres.json is up to date")
        return 0
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    print("wrote %s: %d genres in %d families, %d styles, %d sources, %d fields" % (OUT, len(G), len(FAMILIES), len(STYLES), len(SOURCES), len(FIELDS)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
