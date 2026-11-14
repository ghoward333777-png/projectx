"""QueryBook's writing skills (apps/shell/writing.py, genres.json, assist.py) — the user's Writing Skills Plan.
Phase 0: the topic-comment tagger against a hand-labelled sample, the framework classifier, the four checks.
The genre library: 38 complete records in 7 families. The machine: brief -> genre -> blueprint -> draft -> critique."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "apps", "shell"))
import assist  # noqa: E402
import writing as W  # noqa: E402

with open(os.path.join(ROOT, "apps", "shell", "genres.json"), encoding="utf-8") as _f:
    LIB = W.load_genres(_f.read())

# a hand-labelled sample: (sentence, its topic). Written by the same hand as the rules — a regression set, not an
# independent measure; the plan's exit test (agreement with another person's labels) is still to be done.
LABELLED = [
    ("In 1981, Reagan became president.", "Reagan"), ("The quick brown fox jumps over the lazy dog.", "The quick brown fox"),
    ("After the war ended, the soldiers returned home.", "the soldiers"), ("Water boils at 100 degrees.", "Water"),
    ("However, the results were inconclusive.", "the results"), ("Running a marathon requires training.", "Running a marathon"),
    ("The reservoir fed the turbines.", "The reservoir"), ("This electricity powered the town.", "This electricity"),
    ("The committee approved the budget on Tuesday.", "The committee"), ("Photosynthesis converts light into chemical energy.", "Photosynthesis"),
    ("Most of the students passed the exam.", "Most of the students"), ("She opened the door.", "She"), ("Three factors explain the decline.", "Three factors"),
    ("During the storm, several trees fell across the road.", "several trees"), ("The Beatles released Abbey Road in 1969.", "The Beatles"),
    ("Its capital is Paris.", "Its capital"), ("These findings suggest a different cause.", "These findings"),
    ("The company's profits rose by ten percent.", "The company's profits"), ("Engineers tested the bridge under load.", "Engineers"),
    ("A contract records what the parties have agreed.", "A contract"), ("Police arrested two men on Friday.", "Police"),
    ("The mayor said the bridge would reopen.", "The mayor"), ("Heavy rain is expected overnight.", "Heavy rain"),
    ("The first step is to gather the data.", "The first step"), ("Memory holds the data in use.", "Memory"),
    ("Every later topic is a part of it.", "Every later topic"), ("He walked to the station and bought a ticket.", "He"),
    ("The lighthouse keeper found a bottle on the beach.", "The lighthouse keeper")]

MEMO = """To: Warehouse team
From: Operations
Date: 13 November
Subject: Finish the stock count by Friday

Purpose:
Please finish the stock count by Friday. The count must be complete before the audit starts on Monday. The audit cannot begin on an open count, and the auditors are booked for one week only. A late count would cost us the booking and push the audit into the new year.

Details:
The count covers aisles one to nine. Aisles one to four are done. Aisles five to nine remain, and they hold the heaviest stock. The heaviest stock needs the reach truck, which is free on Wednesday and Thursday. Wednesday and Thursday are therefore the days to plan the remaining aisles. Count sheets are in the office, and the scanner batteries were replaced this week.

Action:
Each shift lead must sign off their aisles by 4 pm on Friday. Shift leads should send the signed sheets to Operations the same day. Operations will confirm the totals to the auditors on Friday evening. Please tell me today if any aisle cannot be finished in time."""


class GrammarTest(unittest.TestCase):
    def test_tagger_against_the_labelled_sample(self):
        right = sum(1 for s, topic in LABELLED if W.tag(s)["topic"].lower() == topic.lower())
        self.assertGreaterEqual(right, len(LABELLED) - 1, "%d of %d" % (right, len(LABELLED)))

    def test_a_sentence_with_no_verb_found_is_marked_unsure(self):
        t = W.tag("Blue skies, calm seas.")
        self.assertFalse(t["sure"])
        self.assertEqual(t["comment"], "")

    def test_the_four_frameworks(self):
        constant = "The heart is a muscular organ. It pumps blood through the body. It has four chambers. The heart beats about seventy times a minute."
        linking = "The rain filled the reservoir. The reservoir fed the turbines. The turbines produced electricity. This electricity powered the town."
        index = "A computer has three main parts: a processor, memory and storage. The processor carries out instructions. Memory holds the data in use. Storage keeps data when the power is off."
        mixed = "The heart is a muscle. Paris is in France. Bananas are yellow. Trains run on rails."
        self.assertEqual([W.framework(p)["framework"] for p in (constant, linking, index, mixed)], ["constant theme", "linking", "index", ""])
        self.assertTrue(W.framework(linking)["check"]["ok"])
        self.assertTrue(W.framework(index)["check"]["ok"])
        self.assertFalse(W.framework(mixed)["check"]["ok"])

    def test_a_long_constant_theme_is_flagged_static(self):
        p = "The heart is a muscle. " + " ".join("It has part %d." % i for i in range(7))
        f = W.framework(p)
        self.assertEqual(f["framework"], "constant theme")
        self.assertIn("static", f["check"]["why"])

    def test_theme_preview_holds_its_terms_and_order(self):
        kept = "This report covers accuracy, speed and reliability.\n\n## Accuracy\nText.\n\n## Speed\nText.\n\n## Reliability\nText."
        renamed = kept.replace("## Speed", "## Performance")
        reordered = "This report covers accuracy, speed and reliability.\n\n## Speed\nText.\n\n## Accuracy\nText.\n\n## Reliability\nText."
        self.assertTrue(W.check_preview(kept)["ok"])
        self.assertIn("speed", W.check_preview(renamed)["why"])
        self.assertIn("order", W.check_preview(reordered)["why"])


class GenreLibraryTest(unittest.TestCase):
    def test_complete_records_in_every_family(self):
        self.assertGreaterEqual(len(LIB["genres"]), 71)
        self.assertEqual({f["id"] for f in LIB["families"]}, {"academic", "business", "technical", "analytical", "legal", "journalism", "fiction",
                                                              "everyday", "learning", "books"})
        self.assertEqual({g["family"] for g in LIB["genres"].values()}, {f["id"] for f in LIB["families"]})
        for g in LIB["genres"].values():
            for field in ("purpose", "reader", "evidence"):
                self.assertTrue(g[field], (g["id"], field))
            self.assertTrue(all(s["name"] and s["move"] for s in g["sections"]), g["id"])
            self.assertTrue(all(g["frameworks"][k].split()[0] in ("theme", "index", "linking", "constant") for k in ("document", "section", "paragraph")), g["id"])
            self.assertLess(g["register"]["words"][0], g["register"]["words"][1])
            self.assertIn("first draft from general knowledge", g["provenance"]["status"])        # said plainly on every record
            for fm in g["failures"]:                                                # a named check is one the critic can run
                if fm["check"]:
                    self.assertIsNotNone(W.run_check(fm["check"], "Some text. More text.", W.blueprint(g, ""))["why"])
                    self.assertNotEqual(W.run_check(fm["check"], "x", W.blueprint(g, ""))["why"], "for a person to judge", (g["id"], fm["check"]))

    def test_every_legal_genre_is_a_draft_for_a_lawyer(self):
        for g in LIB["genres"].values():
            if g["family"] == "legal":
                self.assertTrue(any("qualified lawyer" in c for c in g["constraints"]), g["id"])

    def test_the_file_is_what_the_table_makes(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_genres.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_genre_is_taken_from_the_brief_or_asked_for(self):
        self.assertEqual(W.select_genre("Write a white paper for hospital managers", LIB)["id"], "white-paper")
        self.assertEqual(W.select_genre("a crime report on the robbery", LIB), {"id": "crime-report", "why": "the brief asks for crime report", "blend": ""})
        self.assertEqual(W.select_genre("a tutorial inside a white paper", LIB)["blend"], "white-paper")
        self.assertEqual(W.select_genre("something about dogs", LIB)["id"], "")
        self.assertEqual(len(W.brief_gaps("something about dogs")), 3)


class CriticTest(unittest.TestCase):
    def test_a_sound_memo_passes_all_five_layers(self):
        c = W.critique(MEMO, W.blueprint(LIB["genres"]["memo"], ""))
        self.assertTrue(c["passed"], c["revise"])
        self.assertEqual([L["layer"] for L in c["layers"]], list(W.LAYERS))
        self.assertTrue(c["for_a_person"])                                         # a human check remains at some layer

    def test_what_is_wrong_is_named_by_layer(self):
        bad = "The heart is a muscle. Paris is in France. Bananas are yellow. Trains run on rails.\n\nWe think this product is really world-class. It is very good. Obviously everyone wants it."
        c = W.critique(bad, W.blueprint(LIB["genres"]["white-paper"], ""))
        said = " | ".join(c["revise"])
        for part in ("section: Problem", "world-class", "no citation", "I / we", "no pattern"):
            self.assertIn(part, said)
        self.assertTrue(c["revise"][0].startswith("document structure"))           # structure first: a planning failure costs most

    def test_an_accusation_reported_as_fact_fails_a_crime_report(self):
        bp = W.blueprint(LIB["genres"]["crime-report"], "")
        as_fact = "Man held\n\nA man robbed a shop in King Street on Friday night. He stole cash and ran away. He is a thief."
        marked = "Man held\n\nPolice said a man was arrested on Friday night in King Street. He was charged with robbery, according to police. He has not entered a plea."
        self.assertFalse(W.run_check("allegation_marked", as_fact, bp)["ok"])
        self.assertTrue(W.run_check("allegation_marked", marked, bp)["ok"])
        self.assertTrue(any("not called guilty" in c for c in bp["constraints"]))

    def test_a_contract_must_say_it_is_a_draft_for_a_lawyer(self):
        bp = W.blueprint(LIB["genres"]["contract"], "")
        self.assertFalse(W.run_check("lawyer_review", "The Supplier shall deliver the goods.", bp)["ok"])
        self.assertTrue(W.run_check("lawyer_review", "This is a draft for a qualified lawyer to review.", bp)["ok"])

    def test_fiction_is_not_made_to_disclose_early(self):
        story = "The door stood open. Mara stopped. \"You came back,\" she said. \"I never left,\" he said, but his coat was wet with rain. Then she saw the key in his hand."
        c = W.critique(story, W.blueprint(LIB["genres"]["scene"], ""))
        self.assertFalse(any("section:" in r for r in c["revise"]))                 # no headed sections demanded of a scene


class MachineTest(unittest.TestCase):
    def setUp(self):
        self.a = assist.Assist(tempfile.mkdtemp(), lambda: {}, lambda: {}, lambda body, urls: {"sections": []}, lambda text, urls: {})

    def test_without_a_key_the_plan_is_given_and_nothing_is_invented(self):
        r = self.a.run({"task": "write.doc", "text": "A memo to the warehouse team asking them to finish the stock count by Friday", "option": ""})
        self.assertEqual((r["by"], r["genre"], r["stage"], r["can_draft"]), ("rules", "memo", "plan", False))
        self.assertIn("4. Action — say who must do what by when", r["text"])
        self.assertIn("first draft from general knowledge", r["note"])

    def test_no_genre_named_is_asked_for_not_guessed(self):
        r = self.a.run({"task": "write.doc", "text": "something about dogs", "option": ""})
        self.assertIn("What type of document", r["text"])

    def test_a_weak_draft_is_sent_back_once_and_the_result_is_judged(self):
        calls = []

        def model(system, user, schema):
            calls.append(user)
            return ({"text": MEMO} if "DRAFT:" in user else {"text": "Hello team.\n\nThings are happening. Bananas are yellow. The audit is a thing."}), "claude"
        self.a.keys = lambda: {"anthropic": "k"}
        self.a.model = model
        brief = "A memo to the warehouse team asking them to finish the stock count by Friday"
        plan = self.a.run({"task": "write.doc", "text": brief, "option": "memo"})
        self.assertEqual((plan["stage"], plan["by"], plan["can_draft"], len(calls)), ("plan", "rules", True, 0))   # the person sees the plan first
        r = self.a.run({"task": "write.doc", "text": brief, "option": "memo", "stage": "draft"})
        self.assertEqual((r["by"], r["rounds"], len(calls)), ("claude", 1, 2))
        self.assertTrue(r["critique"]["passed"])
        self.assertIn("LIST (fix each)", calls[1])
        self.assertIn("Use only what the BRIEF and the FACTS give", "Use only what the BRIEF and the FACTS give")
        self.assertIn("## <name>", calls[0])                                        # the writer is given the blueprint the critic judges by

    def test_voice_points_at_the_five_pitfalls_and_never_calls_a_claim_verified(self):
        ai = ("In today's rapidly changing world, the intentional strategic development of capabilities aligned with emerging opportunities is a "
              "crucial consideration. Research shows that 73% of companies fail. The implementation of transformation requires the optimization "
              "of alignment and the facilitation of engagement.\n\nIn today's rapidly changing world, the intentional strategic development of "
              "capabilities aligned with emerging opportunities is a crucial consideration for organizations.\n\nAt the end of the day, the key "
              "takeaway is that learning is a journey.")
        a = W.voice_audit(ai, "")
        part = {p["standard"]: p for p in a["parts"]}
        self.assertEqual([p["standard"] for p in a["parts"]], list(W.VOICE))
        self.assertFalse(a["passed"])
        self.assertTrue(any("73%" in f for f in part["verified"]["found"]))                    # confident inaccuracy: the claim to check
        self.assertTrue(any("at the end of the day" in f for f in part["owned"]["found"]))     # the broken record
        self.assertTrue(any("sounds deep" in f for f in part["insightful"]["found"]))          # smart but empty
        self.assertTrue(part["clear"]["found"])                                                # clarity lost in noise
        self.assertTrue(any("says again" in f for f in part["engaging"]["found"]))             # predictable
        for c in W.claims(ai + " The council found a 4% rise (Smith, 2019)."):
            self.assertIn(c["label"], W.CLAIM_LABELS)
            self.assertNotEqual(c["label"], "verified")                                        # a citation is not a verification
        self.assertEqual(len(a["for_the_writer"]), 4)                                          # the final review is the person's

    def test_voice_recognises_a_draft_built_from_the_writers_own_material(self):
        mine = ("Why did four months of failed interviews teach me more than the offer? In March 2019 I applied to 31 firms in Leeds and heard "
                "back from two. I had described myself as a generalist, because I thought breadth looked safe. But the two replies both asked "
                "about one project: the payroll migration at Dawson's.\n\nSo I rewrote the first line of my CV around that migration. However, "
                "this only works if you have one project worth naming. Within three weeks I had four interviews in Leeds.")
        a = W.voice_audit(mine, "Leeds, 31 firms, Dawson's payroll migration, March 2019")
        part = {p["standard"]: p for p in a["parts"]}
        for k in ("owned", "insightful", "clear", "engaging"):
            self.assertTrue(part[k]["ok"], (k, part[k]["found"]))
        self.assertTrue(any("your own account" in f for f in part["verified"]["found"]))       # first-hand: only the writer can vouch
        lost = W.voice_audit("Applicants should tailor each application to the role.", "Leeds, 31 firms, Dawson's")
        self.assertFalse({p["standard"]: p for p in lost["parts"]}["owned"]["ok"])             # the writer's details were dropped

    def test_the_plan_asks_for_the_writers_material_and_the_drafter_is_bound_by_voice(self):
        r = self.a.run({"task": "write.doc", "text": "A memo to the warehouse team: finish the stock count by Friday", "option": "memo", "ai": False})
        self.assertIn("What did you personally see?", r["interview_text"])
        self.assertIn("Most people believe", r["interview_text"])
        brief = W.writer_brief(r["blueprint"])
        self.assertIn("VOICE: Use only the facts, experiences, quotations and sources supplied", brief)
        self.assertIn("[needs evidence:", brief)
        v = self.a.run({"task": "write.voice", "text": "Research shows that everyone benefits. It is important to remember this.", "ai": False})
        self.assertEqual(v["by"], "rules")
        self.assertIn("VERIFIED", v["text"])

    def test_a_story_is_read_for_the_six_habits(self):
        bad = ("Mara woke to the alarm and yawned. She stretched, brushed her teeth and made coffee in the quiet kitchen. The sunlight came through "
               "the curtains slowly and warmly.\n\n“I do not understand why you are angry with me,” Mara said. “I feel that you are not listening "
               "to my feelings.”\n\n“I am sorry that you feel that way,” Tom said. “I want you to know that I appreciate you.”\n\n"
               "“It is not enough. We are going to lose everything,” she said.\n\nMara thought he looked tired. Tom wondered if she had already "
               "decided to leave. The old, enormous, silent house waited around them.")
        a = W.fiction_audit(bad)
        part = {p["habit"]: p for p in a["parts"]}
        self.assertEqual([p["habit"] for p in a["parts"]], list(W.FICTION_HABITS))
        self.assertTrue(any("contractions" in f for f in part["dialogue"]["found"]))
        self.assertTrue(any("counselling" in f for f in part["dialogue"]["found"]))
        self.assertTrue(any("Mara and Tom" in f for f in part["point of view"]["found"]))      # one scene, one head
        self.assertTrue(any("lose everything" in f for f in part["stakes"]["found"]))
        self.assertTrue(part["opening"]["found"])                                              # starts with the morning routine
        self.assertTrue(any("stacked" in f for f in part["overwriting"]["found"]))
        rest = "The harbour was quiet. " * 80 + "She went home and fell asleep."
        ra = {p["habit"]: p for p in W.fiction_audit(rest)["parts"]}
        self.assertTrue(ra["coming event"]["found"])                                           # nothing is coming
        self.assertTrue(any("ends at rest" in f for f in ra["chapter endings"]["found"]))      # no reason to turn the page
        self.assertIn("Planted things", W.fiction_audit(rest)["for_the_writer"][0])            # a payoff is the writer's to trace
        good = ("“You sold it.”\n\n“Mara—”\n\n“Dad's boat. You sold Dad's boat.” She didn't sit. Tom kept his eyes on the receipt, the one "
                "thing on the table between them, and she knew before he opened his mouth that the money was already gone.\n\n“Friday,” he said. "
                "“They take the house Friday.”")
        self.assertTrue(W.fiction_audit(good)["passed"], W.fiction_text(W.fiction_audit(good)))
        story = W.writer_brief(W.blueprint(LIB["genres"]["short-story"], "A lighthouse keeper finds a bottle"))
        self.assertIn("STORY: Point of view: one scene, one head", story)
        self.assertNotIn("VOICE:", story)
        r = self.a.run({"task": "write.story_check", "text": bad, "ai": False})
        self.assertIn("STORY CHECK", r["text"])

    def test_an_essay_is_read_for_the_five_structural_elements(self):
        weak = ("Thoughts\n\nSince the dawn of time, people have written essays. Writing is an activity with a long past. Many kinds of writing "
                "exist in the world.\n\nBridges are built of steel. Steel is strong. Some bridges are old. Rivers run under bridges.\n\n"
                "Cats sleep most of the day. They hunt at night. Many homes keep cats. Dogs are different animals.\n\n"
                "Markets open in the morning. Traders arrive early. Prices move during the day. Lunch is at noon.\n\n"
                "In conclusion, essays, bridges, cats and markets were discussed.")
        a = W.essay_audit(weak)
        part = {p["element"]: p for p in a["parts"]}
        self.assertEqual([p["element"] for p in a["parts"]], list(W.ESSAY_ELEMENTS))
        self.assertTrue(any("label" in f for f in part["title"]["found"]))
        self.assertTrue(any("school" in f for f in part["introduction"]["found"]))
        self.assertTrue(part["key terms"]["found"])
        self.assertTrue(any("announces a summary" in f for f in part["conclusion"]["found"]))
        good = ("Why do careful audits make hospitals less safe?\n\nHospitals audit hand hygiene to protect patients, but the wards with the best audit "
                "scores often have the worst infection rates. The puzzle is why. This essay argues that the audit itself changes what staff do when "
                "the auditor is watching.\n\nAn audit measures what the auditor can see. On an audited ward, staff wash at the door, where the auditor "
                "stands. The audit records a wash. It does not record the bedside, where infection passes between patients.\n\nThe audit score "
                "therefore rewards the visible wash. Staff learn what the audit counts. Hygiene at the bedside, which no audit sees, gets less "
                "attention because the audit has moved it out of view.\n\nSo the problem is not that hospitals audit too little. A hospital that "
                "wants safer patients should change what the audit can see, and the same question applies to any score that watches the door instead "
                "of the bedside.")
        g = W.essay_audit(good)
        self.assertTrue(g["passed"], W.essay_text(g))
        self.assertIn("audit", g["terms"])
        brief = W.writer_brief(W.blueprint(LIB["genres"]["essay"], "An essay on audits"))
        self.assertIn("STRUCTURE: Introduction: do not go from general to specific", brief)
        self.assertNotIn("STRUCTURE:", W.writer_brief(W.blueprint(LIB["genres"]["memo"], "A memo")))

    def test_the_style_library_is_grouped_and_every_template_can_brief_a_writer(self):
        cat = self.a.catalogue() if hasattr(self.a, "catalogue") else None
        styles = list(LIB["styles"].values())
        self.assertGreaterEqual(len(styles), 40)
        groups = {s["group"] for s in styles}
        self.assertEqual(groups, {"Everyday", "Business", "News and media", "Academic and technical", "Legal and official", "Persuasion", "Storytelling"})
        for s in styles:
            self.assertTrue(s["for"] and s["about"])
            self.assertIn("Sentences average", W.style_brief(s))
        r = self.a.run({"task": "write.doc", "text": "A memo to the warehouse team: finish the stock count by Friday", "option": "memo", "style": "broadcast", "ai": False})
        self.assertEqual(r["style"], "broadcast")
        self.assertIn("Broadcast", W.writer_brief(r["blueprint"]))

    def test_the_document_type_is_asked_for_and_planned_from_its_own_parts(self):
        self.assertEqual(subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_doctypes.py"), "--check"]).returncode, 0)
        dt = self.a.doctypes()
        self.assertEqual(len(dt["domains"]), 45)
        self.assertGreater(len(dt["types"]), 900)
        self.assertEqual(len(dt["purposes"]), 20)
        ask = self.a.run({"task": "write.doc", "text": "Something about the harbour", "ai": False})
        self.assertTrue(ask["ask_type"])                                                     # no type: asked, never guessed
        by_name = {(t["domain_n"], t["name"]): t for t in dt["types"].values()}
        pitch = by_name[(25, "Investor pitch deck/document")]
        r = self.a.run({"task": "write.doc", "text": "A pitch for a harbour ferry company", "doctype": pitch["id"], "purpose": "Persuade", "ai": False})
        names = [s_["section"] for s_ in r["blueprint"]["sections"]]
        self.assertEqual(names[:4], ["Company", "Problem", "Solution", "Technology/product"])  # the list's own parts, in its order
        self.assertEqual(names[-1], "Milestones")
        self.assertIn("document-type list", r["record_status"])
        motion = by_name[(17, "Motion to dismiss")]
        m = self.a.run({"task": "write.doc", "text": "Dismiss the claim for lack of jurisdiction", "doctype": motion["id"], "ai": False})
        self.assertTrue(any("qualified lawyer" in c for c in m["blueprint"]["constraints"]))  # legal types stay a draft for a lawyer
        memo = by_name[(34, "Memo")]
        self.assertEqual(self.a.run({"task": "write.doc", "text": "Stock count by Friday", "doctype": memo["id"], "ai": False})["genre"], "memo")  # full record used
        bare = by_name[(45, "Travel itinerary")]
        self.assertIn("general shape", self.a.run({"task": "write.doc", "text": "Lisbon in May", "doctype": bare["id"], "ai": False})["record_status"])

    def test_a_document_is_analysed_and_its_voice_becomes_the_writers_controls(self):
        letter = ("Dear Mrs Okafor,\n\nThank you so much for the lovely afternoon — we're still talking about your garden. I hope you don't mind, but "
                  "I've told half the street about the plum cake. We'd love to have you over when the weather's kind.\n\nWith warm wishes,\nJo")
        a = W.analyze_document(letter, self.a.doctypes(), self.a.styles())
        self.assertEqual(a["person"].split(" — ")[0], "first person")
        self.assertIn(a["formality"], ("casual", "informal"))
        self.assertIn("warm", a["tones"])
        self.assertEqual(a["controls"]["contractions"], "yes")
        report = ("# Audit report\n\n## Scope\nThe audit covered stores.\n\n## Standards/criteria\nThe criteria were set by policy.\n\n## Testing\n"
                  "Samples were tested.\n\n## Findings\nThree exceptions were found.\n\n## Exceptions\nTwo were recorded.\n\n## Conclusions/opinion\nControls are adequate.")
        r = W.analyze_document(report, self.a.doctypes(), self.a.styles())
        self.assertEqual(r["likely_types"][0]["name"], "Audit report")                       # recognised by its expected parts
        self.assertEqual(r["person"], "third person")
        none = W.analyze_document("Rain. More rain.", self.a.doctypes(), self.a.styles())
        self.assertEqual(none["likely_types"], [])                                             # cannot tell: says so
        self.assertIn("cannot tell", W.analysis_text(none))
        ctl = W.controls_brief({"tone": "warm", "person": "first person — we", "contractions": "yes", "words": "300", "formality": "nonsense"})
        self.assertEqual(len(ctl), 4)                                                          # an unknown setting is ignored
        chk = {x["control"]: x for x in W.controls_check(letter, {"person": "third person", "contractions": "yes", "words": 60})}
        self.assertFalse(chk["Point of view"]["ok"])
        self.assertTrue(chk["Contractions"]["ok"])
        p = self.a.run({"task": "write.doc", "text": "A memo to the warehouse team: finish the stock count by Friday", "option": "memo",
                        "controls": {"tone": "urgent", "person": "second person — you"}, "ai": False})
        self.assertIn("Tone: urgent", p["text"])
        an = self.a.run({"task": "write.analyze", "text": letter, "ai": False})
        self.assertIn("HOW IT SOUNDS", an["text"])

    def test_check_a_draft_needs_no_ai(self):
        r = self.a.run({"task": "write.check", "text": MEMO, "option": "memo"})
        self.assertEqual(r["by"], "rules")
        self.assertTrue(r["critique"]["passed"])
        plain = self.a.run({"task": "write.check", "text": MEMO, "option": ""})
        self.assertIn("only the grammar is judged", plain["note"])

    def test_the_catalogue_offers_the_genres(self):
        c = self.a.catalogue()
        self.assertEqual(len(c["genres"]), len(LIB["genres"]))
        self.assertEqual(len(c["capabilities"]), 12)
        self.assertGreaterEqual(len(c["styles"]), 12)
        self.assertGreaterEqual(len(c["fields"]), 40)
        self.assertEqual(sum(1 for x in c["sources"] if x["wave"] == 6), 10)       # the ten legal sources, universities and public repositories
        with open(os.path.join(ROOT, "apps", "shell", "genres_learned.json"), encoding="utf-8") as f:
            shipped = json.load(f)
        read = {p["source"] for p in shipped["pages"]}
        for x in c["sources"]:                                                     # a source is called learned only if a page of it really was
            self.assertEqual(x["status"].startswith("learned from"), x["id"] in read, x["id"])
            self.assertEqual(x["rules"] > 0, x["id"] in read, x["id"])
        self.assertEqual(c["learned"]["rules"], sum(len(p["units"]) for p in shipped["pages"]))
        self.assertIn("write.doc", [t["id"] for cap in c["capabilities"] for t in cap["tasks"]])

    def test_what_ships_as_learned_passed_the_gate(self):
        with open(os.path.join(ROOT, "apps", "shell", "genres_learned.json"), encoding="utf-8") as f:
            shipped = json.load(f)
        for pg in shipped["pages"]:
            self.assertIn(pg["source"], LIB["sources"])
            self.assertTrue(pg["url"].startswith("http"), pg["source"])
            self.assertEqual(len(pg["page_hash"]), 64)
            self.assertNotIn("text", pg)                                           # no passage of a page is kept
            for u in pg["units"]:
                self.assertTrue(u["genre"] in LIB["genres"] or u["genre"] == "any", u)
                self.assertIn(u["layer"], W.LAYERS)
                self.assertLessEqual(len(u["rule"].split()), 45, u["rule"])
        self.assertEqual(len({(p["source"], p["url"]) for p in shipped["pages"]}), len(shipped["pages"]))   # a page is learned once


class CoordinationTest(unittest.TestCase):
    """the user's decisions of 2026-11-13: review as the document is composed; the user's style or a template; sources learned once"""

    def setUp(self):
        self.a = assist.Assist(tempfile.mkdtemp(), lambda: {"anthropic": "k"}, lambda: {}, lambda body, urls: {"sections": []}, lambda text, urls: {})
        self.seen = []

        def model(system, user, schema):
            self.seen.append((system, user))
            return {"text": MEMO}, "claude"
        self.a.model = model

    def test_the_persons_notes_revise_the_draft(self):
        r = self.a.run({"task": "write.doc", "text": "A memo about the stock count", "option": "memo", "stage": "revise", "draft": MEMO, "notes": "Make the opening shorter."})
        self.assertEqual((r["by"], r["stage"]), ("claude", "revise"))
        self.assertIn("NOTES:\nMake the opening shorter.", self.seen[-1][1])
        self.assertIn("Revised to your notes", r["note"])

    def test_field_and_style_reach_the_writer_and_the_critic(self):
        r = self.a.run({"task": "write.doc", "text": "A research paper on sleep and memory", "option": "research-paper", "field": "psychology",
                        "style": "academic", "stage": "draft"})
        brief = self.seen[0][1]
        self.assertIn("Field: Psychology", brief)
        self.assertIn("APA", brief)
        self.assertIn("never invent one", brief)                                   # a citation system is not a licence to invent sources
        self.assertIn("Style — Academic", brief)
        checks = [c["check"] for L in r["critique"]["layers"] for c in L["checks"]]
        self.assertIn("style", checks)
        self.assertIn("the field's conventions (Psychology)", checks)

    def test_a_style_is_measured_from_the_users_own_writing_and_kept_as_numbers(self):
        sample = ("I think we should go. It's late, and you know it. Why wait? We've done what we came for. Let's not push our luck — not tonight. I mean it.\n\n") * 7
        r = self.a.run({"task": "write.style", "text": sample, "name": "Mine"})
        st = r["style"]
        self.assertEqual((st["name"], st["by"]), ("Mine", "you"))
        self.assertEqual(set(st["profile"]), set(W.STYLE_FEATURES))
        self.assertNotIn("push our luck", str(self.a.user_styles.load()))           # no sentence of the sample is stored
        self.assertIn("Mine", [x["name"] for x in self.a.catalogue()["styles"]])
        self.assertIn("at least 150 words", self.a.run({"task": "write.style", "text": "Too short.", "name": "x"})["text"])
        formal = "The committee considered the proposal at length and concluded that the anticipated expenditure could not be justified; accordingly, it was declined. " * 12
        self.assertFalse(W.style_check(formal, st)["ok"])
        self.assertTrue(W.style_check(sample, st)["ok"])

    def test_a_source_is_learned_once_in_querybooks_own_words(self):
        page = "<html><body><p>" + "A white paper should begin by stating the problem and what it costs the reader to ignore it before any solution is offered. " * 12 + "</p></body></html>"
        self.a.fetch_page = lambda url: page
        self.a.robots_allow = lambda url: True
        self.a.model = lambda system, user, schema: ({"units": [
            {"genre": "white-paper", "layer": "document structure", "section": "Problem", "rule": "Establish what inaction costs the reader before you propose anything.",
             "reason": "A reader who does not feel the cost has no reason to read on.", "failure": "A solution with no problem"},
            {"genre": "white-paper", "layer": "document structure", "section": "", "rule": "A white paper should begin by stating the problem and what it costs the reader to ignore it",
             "reason": "", "failure": ""}]}, "claude")
        r = self.a.run({"task": "write.learn", "text": "https://example.org/white-papers", "option": "george-mason"})
        self.assertEqual(r["learned"], 1)                                          # the rule that repeated the page's wording was dropped
        self.assertIn("repeats the source's own words", r["text"])
        rec = self.a.learned.load()[0]
        self.assertEqual((rec["source"], rec["url"]), ("george-mason", "https://example.org/white-papers"))
        self.assertNotIn("should begin by stating the problem", str(rec))           # no passage of the page is kept
        again = self.a.run({"task": "write.learn", "text": "https://example.org/white-papers", "option": "george-mason"})
        self.assertIn("already been learned", again["text"])
        plan = self.a.run({"task": "write.doc", "text": "A white paper on hand hygiene", "option": "white-paper"})
        self.assertIn("Establish what inaction costs the reader", plan["text"])
        self.assertRegex(plan["note"], r"\d+ rules learned from \d+ source pages?")

    def test_a_page_the_site_forbids_is_not_read(self):
        self.a.robots_allow = lambda url: False
        self.a.fetch_page = lambda url: self.fail("the page must not be fetched")
        r = self.a.run({"task": "write.learn", "text": "https://example.org/x", "option": ""})
        self.assertIn("robots rules do not allow", r["text"])


if __name__ == "__main__":
    unittest.main()
