#!/usr/bin/env python3
"""Build apps/shell/genres.json — QueryBook's genre library (the Writing Skills Plan, part 2).

One record per document type: purpose, reader, sections with the move each must make, the framework at document, section
and paragraph scale, register, evidence rules, hard constraints, and failure modes written as named checks
(apps/shell/writing.py runs them).

    python tools/build_genres.py            write the file
    python tools/build_genres.py --check    fail if the file is not what this table makes (run by the tests)

PROVENANCE, stated plainly: these 38 records are QueryBook's FIRST DRAFT, written from general knowledge of each genre in
QueryBook's own words. They have not yet been reconciled with the plan's 40 sources (no source has been collected: each
site's terms must be checked first) and no person has reviewed them. Every record says so, and so does every document
written from one. Adding a genre is adding a row here — the writer does not change.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "apps", "shell", "genres.json")
STATUS = "first draft from general knowledge of the genre — not yet reconciled with sources, not yet reviewed by a person"
TP, IX, LK, CT = "theme preview", "index", "linking", "constant theme"

FAMILIES = [
    ("academic", "Academic", TP, "Claim, evidence and citation discipline"),
    ("business", "Business", TP + " with conclusions first", "A decision-maker who reads only the top"),
    ("technical", "Technical", IX + ", with linking for procedures", "Exactness, consistent terminology, task order"),
    ("analytical", "Analytical and policy", IX + " over a stated question", "Separating finding from interpretation"),
    ("legal", "Legal", TP + " in a fixed form (issue, rule, application, conclusion)", "Defined terms, jurisdiction, no ambiguity"),
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


UNHEADED = ("abstract", "executive-summary", "review")      # written as running prose: their moves are made without section headings


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
    doc = {"version": "genres-0.1", "status": STATUS,
           "families": [{"id": i, "name": n, "framework": f, "demand": d} for i, n, f, d in FAMILIES], "genres": genres}
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
    print("wrote %s: %d genres in %d families" % (OUT, len(G), len(FAMILIES)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
