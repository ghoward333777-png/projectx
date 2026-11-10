"""The Ask page's modes and formats (apps/shell/modes.py): every view is built from returned facts, nothing invented."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "apps", "shell"))
import ask  # noqa: E402
import modes  # noqa: E402

PRESS = [
    {"subject": "Printing press (Q11223)", "predicate": "instance of", "object": "machine (Q11019)", "where": "wikidata-dump-3", "status": "filed"},
    {"subject": "Printing press (Q11223)", "predicate": "time of discovery or invention", "object": "1440", "where": "wikidata-dump-3"},
    {"subject": "Printing press (Q11223)", "predicate": "inventor", "object": "Johannes Gutenberg (Q8958)", "where": "wikidata-dump-3"},
    {"subject": "Printing press", "predicate": "time of discovery or invention", "object": "1439", "where": "History & News", "status": "disputed"},
    {"subject": "Printing press", "predicate": "inventor", "object": "Johannes Gutenberg", "where": "History & News", "status": "verified"},
]
CURIE = [
    {"subject": "Marie Curie (Q7186)", "predicate": "date of birth", "object": "1867-11-07", "where": "wikidata"},
    {"subject": "Marie Curie (Q7186)", "predicate": "place of birth", "object": "Warsaw (Q270)", "where": "wikidata"},
    {"subject": "Marie Curie (Q7186)", "predicate": "date of death", "object": "1934-07-04", "where": "wikidata"},
    {"subject": "Marie Curie (Q7186)", "predicate": "award received", "object": "Nobel Prize in Physics (Q38104)", "where": "wikidata"},
]


def answer(question, facts, extra=()):
    return {"question": question, "understood": ask.understand(question), "short": "x",
            "sections": list(extra) + ([{"kind": "facts", "items": facts}] if facts else [])}


class FormatTest(unittest.TestCase):
    def test_format_follows_the_topic(self):
        self.assertEqual(modes.topic(ask.understand("Marie Curie"), answer("Marie Curie", CURIE)["sections"]), "person")
        self.assertEqual(modes.choose_format("auto", ask.understand("Marie Curie"), answer("Marie Curie", CURIE)["sections"]), "profile")
        self.assertEqual(modes.choose_format("auto", ask.understand("60 mph to km/h"),
                                             [{"kind": "math", "items": [{"text": "96.56 km/h"}]}]), "steps")
        self.assertEqual(modes.choose_format("timeline", ask.understand("x"), []), "timeline")   # a chosen format wins

    def test_timeline_in_order_with_sources(self):
        t = modes.timeline(CURIE)
        self.assertEqual([r["year"] for r in t], [1867, 1934])
        self.assertTrue(all(r["where"] == "wikidata" for r in t))

    def test_register_frames_but_never_rewords_the_fact(self):
        s = "Printing press — inventor: Johannes Gutenberg (Q8958)"
        self.assertTrue(modes.in_register(s, "formal").endswith(s))
        self.assertNotIn("(Q8958)", modes.in_register(s, "child"))
        self.assertEqual(modes.in_register("", "academic"), "")


class ModesTest(unittest.TestCase):
    def test_tutorial_simplest_first(self):
        steps = modes.tutorial(ask.understand("printing press"), answer("printing press", PRESS)["sections"])
        self.assertEqual(steps[0]["title"], "What it is")
        self.assertEqual([s["level"] for s in steps], sorted(s["level"] for s in steps))
        self.assertEqual([s["n"] for s in steps], list(range(1, len(steps) + 1)))

    def test_quiz_is_deterministic_and_answer_is_among_choices(self):
        a, b = modes.quiz(CURIE, 4, 7), modes.quiz(CURIE, 4, 7)
        self.assertEqual(a, b)
        for q in a:
            self.assertIn(q["answer"], q["choices"])
            self.assertEqual(len(set(q["choices"])), len(q["choices"]))
        self.assertEqual(modes.grade("warsaw", "Warsaw")["verdict"], "right")
        self.assertEqual(modes.grade("Nobel Prize", "Nobel Prize in Physics")["verdict"], "nearly")
        self.assertEqual(modes.grade("Paris", "Warsaw")["verdict"], "wrong")

    def test_discussion_shows_agreement_and_difference(self):
        d = modes.discussion(PRESS)
        self.assertEqual({v["source"] for v in d["viewpoints"]}, {"wikidata-dump-3", "History & News"})
        self.assertTrue(any(a["about"] == "inventor" for a in d["agree"]))
        self.assertTrue(any(x["about"] == "time of discovery or invention" for x in d["differ"]))
        self.assertEqual(modes.discussion([])["viewpoints"], [])

    def test_connections_are_names_not_numbers(self):
        c = modes.connections(ask.understand("Marie Curie"), CURIE)
        names = [x["name"] for x in c]
        self.assertIn("Warsaw", names)
        self.assertNotIn("1867-11-07", names)

    def test_guided_follow_up_resolves_it(self):
        g = modes.follow_up("When was it built?", [{"question": "Eiffel Tower", "subject": "Eiffel Tower"}])
        self.assertEqual(g["question"], "When was Eiffel Tower built?")
        self.assertGreater(modes.turn_weight(1), modes.turn_weight(5))
        self.assertEqual(modes.follow_up("Paris", [])["question"], "Paris")

    def test_claims_verified_contradicted_unknown(self):
        self.assertEqual(modes.claim_subject("The printing press was invented in 1440."), "printing press")
        self.assertEqual(modes.verdict("The printing press was invented in 1440.", PRESS[:3])["verdict"], "VERIFIED")
        self.assertEqual(modes.verdict("The printing press was invented in 1600.", PRESS[:3])["verdict"], "CONTRADICTED")
        self.assertEqual(modes.verdict("The printing press was invented in 1600.", [])["verdict"], "UNKNOWN")
        self.assertEqual(modes.split_claims("Paris is in France. Is it big? It has many people living there."),
                         ["Paris is in France.", "It has many people living there."])

    def test_what_the_camera_saw(self):
        rows = modes.seen_summary([{"label": "dog", "score": 0.9, "t": 12}, {"label": "dog", "score": 0.8, "t": 65},
                                   {"label": "cup", "score": 0.2, "t": 3}])
        self.assertEqual([r["label"] for r in rows], ["dog"])           # too unsure a guess is left out
        self.assertEqual(modes.seen_answer("when does the dog appear?", rows), "A dog appears from 0:12 to 1:05 (seen 2 times).")
        self.assertTrue(modes.seen_answer("is there a cup?", rows).startswith("That was not recognised"))

    def test_structured_query_narrows_to_what_is_wanted(self):
        r = modes.compose(answer("Marie Curie", CURIE), "qa", "auto", "plain", "award", 0)
        self.assertEqual([f["predicate"] for f in modes.facts_of(r["sections"])], ["award received"])

    def test_compose_adds_the_mode_view(self):
        for m, key in (("tutorial", "steps"), ("quiz", "quiz"), ("flashcards", "cards"), ("discussion", "discussion"), ("explore", "connections")):
            self.assertIn(key, modes.compose(answer("Marie Curie", CURIE), m, "auto", "plain", "", 0)["view"], m)
        v = modes.compose(dict(answer("printing press", PRESS), claim="The printing press was invented in 1440."), "verify", "auto", "plain", "", 0)
        self.assertEqual(v["view"]["verdict"]["verdict"], "VERIFIED")

    def test_clarify_when_a_name_means_several_things(self):
        facts = [{"subject": "Mercury (Q308)", "predicate": "instance of", "object": "planet"},
                 {"subject": "Mercury (Q925)", "predicate": "instance of", "object": "chemical element"}]
        self.assertTrue(modes.clarify(ask.understand("Mercury"), [{"kind": "facts", "items": facts}]).startswith("Which one do you mean"))
        self.assertEqual(modes.clarify(ask.understand("Marie Curie"), [{"kind": "facts", "items": CURIE}]), "")


if __name__ == "__main__":
    unittest.main()
