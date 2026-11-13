"""QueryBook's writing skills (apps/shell/writing.py, genres.json, assist.py) — the user's Writing Skills Plan.
Phase 0: the topic-comment tagger against a hand-labelled sample, the framework classifier, the four checks.
The genre library: 38 complete records in 7 families. The machine: brief -> genre -> blueprint -> draft -> critique."""
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
    def test_thirty_eight_complete_records_in_seven_families(self):
        self.assertEqual(len(LIB["genres"]), 38)
        self.assertEqual([f["id"] for f in LIB["families"]], ["academic", "business", "technical", "analytical", "legal", "journalism", "fiction"])
        for g in LIB["genres"].values():
            for field in ("purpose", "reader", "evidence"):
                self.assertTrue(g[field], (g["id"], field))
            self.assertTrue(all(s["name"] and s["move"] for s in g["sections"]), g["id"])
            self.assertTrue(all(g["frameworks"][k].split()[0] in ("theme", "index", "linking", "constant") for k in ("document", "section", "paragraph")), g["id"])
            self.assertLess(g["register"]["words"][0], g["register"]["words"][1])
            self.assertIn("not yet reviewed", g["provenance"]["status"])           # said on every record until a person has reviewed it
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
        self.assertEqual((r["by"], r["genre"]), ("rules", "memo"))
        self.assertIn("4. Action — say who must do what by when", r["text"])
        self.assertIn("not yet reviewed", r["note"])

    def test_no_genre_named_is_asked_for_not_guessed(self):
        r = self.a.run({"task": "write.doc", "text": "something about dogs", "option": ""})
        self.assertIn("What kind of document", r["text"])

    def test_a_weak_draft_is_sent_back_once_and_the_result_is_judged(self):
        calls = []

        def model(system, user, schema):
            calls.append(user)
            return ({"text": MEMO} if "DRAFT:" in user else {"text": "Hello team.\n\nThings are happening. Bananas are yellow. The audit is a thing."}), "claude"
        self.a.keys = lambda: {"anthropic": "k"}
        self.a.model = model
        r = self.a.run({"task": "write.doc", "text": "A memo to the warehouse team asking them to finish the stock count by Friday", "option": "memo"})
        self.assertEqual((r["by"], r["rounds"], len(calls)), ("claude", 1, 2))
        self.assertTrue(r["critique"]["passed"])
        self.assertIn("LIST (fix each)", calls[1])
        self.assertIn("Use only what the BRIEF and the FACTS give", "Use only what the BRIEF and the FACTS give")
        self.assertIn("## <name>", calls[0])                                        # the writer is given the blueprint the critic judges by

    def test_check_a_draft_needs_no_ai(self):
        r = self.a.run({"task": "write.check", "text": MEMO, "option": "memo"})
        self.assertEqual(r["by"], "rules")
        self.assertTrue(r["critique"]["passed"])
        plain = self.a.run({"task": "write.check", "text": MEMO, "option": ""})
        self.assertIn("only the grammar is judged", plain["note"])

    def test_the_catalogue_offers_the_genres(self):
        c = self.a.catalogue()
        self.assertEqual(len(c["genres"]), 38)
        self.assertEqual(len(c["capabilities"]), 12)
        self.assertIn("write.doc", [t["id"] for cap in c["capabilities"] for t in cap["tasks"]])


if __name__ == "__main__":
    unittest.main()
