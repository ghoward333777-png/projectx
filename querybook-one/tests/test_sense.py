"""A grasp of reality (apps/_core/sense.py, used by the Ask box): the kind of thing each match is, which one is meant,
what to say — and what the Ask box does with it (apps/shell/ask.py), with a stand-in for the Control Panel."""
import http.server
import json
import os
import sys
import threading
import unittest
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "apps", "shell"))
import ask  # noqa: E402
import sense  # noqa: E402

MAN, CARD, FILM = "Babe Ruth (Q213812)", "Babe Ruth (Q99)", "Babe Ruth (Q777)"


def facts(subject, pairs):
    return [{"subject": subject, "predicate": p, "object": o, "dataset": "Wikidata"} for p, o in pairs]


F_MAN = facts(MAN, [("Baseball-Reference ID", "ruthba01"), ("image", "Babe Ruth2.jpg"), ("instance of", "human (Q5)"), ("date of birth", "1895-02-06"),
                    ("place of birth", "Baltimore (Q5092)"), ("date of death", "1948-08-16"), ("place of death", "New York City (Q60)"),
                    ("occupation", "baseball player (Q10871364)"), ("country of citizenship", "United States (Q30)"),
                    ("member of sports team", "New York Yankees (Q213417)"), ("official website", "http://www.baberuth.com")])
F_CARD = facts(CARD, [("instance of", "baseball card (Q809892)"), ("depicts", MAN), ("collection", "Metropolitan Museum of Art (Q160236)")])
F_FILM = facts(FILM, [("instance of", "television film (Q506240)"), ("publication date", "1991")])
ENTS = [{"subject": CARD, "facts": 3}, {"subject": FILM, "facts": 2}, {"subject": MAN, "facts": 11}]


class SenseTest(unittest.TestCase):
    def test_kinds_from_the_facts_themselves(self):
        self.assertEqual([sense.kind_of(f) for f in (F_MAN, F_CARD, F_FILM)], ["human", "depiction", "work"])
        self.assertEqual(sense.kind_of(facts("x", [("date of birth", "1900"), ("occupation", "painter")])), "human")     # no 'instance of'
        self.assertEqual(sense.kind_of(facts("x", [("instance of", "national park (Q46169)")])), "place")
        self.assertEqual(sense.kind_of(facts("x", [("instance of", "university (Q3918)")])), "organization")
        self.assertEqual(sense.kind_of(facts("x", [("instance of", "battle (Q178561)")])), "event")

    def test_babe_ruth_is_the_man_not_the_card(self):
        r = sense.answer_for("Who was Babe Ruth?", "Babe Ruth", ENTS, F_CARD + F_FILM + F_MAN)
        self.assertEqual((r["entity"]["subject"], r["entity"]["kind"], r["missing"]), (MAN, "human", ""))
        self.assertEqual([x["subject"] for x in r["entity"]["ranked"]], [MAN, CARD, FILM])
        self.assertTrue(r["said"].startswith("Babe Ruth (1895–1948) — baseball player from United States. Born 1895-02-06 in Baltimore."))
        self.assertIn("Played for New York Yankees", r["said"])

    def test_fame_decides_between_namesakes(self):
        a, b = "John Smith (Q1)", "John Smith (Q2)"
        fs = facts(a, [("instance of", "human (Q5)"), ("date of birth", "1950")]) + facts(b, [("instance of", "human (Q5)"), ("date of birth", "1580")])
        r = sense.choose("Who is John Smith?", [{"subject": a, "facts": 40, "fame": 2}, {"subject": b, "facts": 12, "fame": 60}], fs)
        self.assertEqual(r["subject"], b)
        self.assertIn("60 Wikipedias", r["why"])

    def test_what_people_read_decides_too(self):
        a, b = "Mercury (Q1)", "Mercury (Q2)"
        fs = facts(a, [("instance of", "planet (Q634)")]) + facts(b, [("instance of", "chemical element (Q11344)")])
        r = sense.choose("What is Mercury?", [{"subject": a, "facts": 30, "fame": 100, "views": 2000000}, {"subject": b, "facts": 30, "fame": 100}], fs)
        self.assertEqual(r["subject"], a)
        self.assertIn("most-read", r["why"])
        self.assertEqual(r["ranked"][0]["views"], 2000000)
        # being read a great deal never turns a film into the person: the kind asked for still comes first
        r2 = sense.choose("Who was Babe Ruth?", [dict(ENTS[1], views=9000000), ENTS[2]], F_FILM + F_MAN)
        self.assertEqual(r2["subject"], MAN)

    def test_only_the_card_is_held_says_so(self):
        r = sense.answer_for("Who was Babe Ruth?", "Babe Ruth", ENTS[:2], F_CARD + F_FILM)
        self.assertIn("no record of the person itself", r["missing"])
        self.assertEqual(sense.answer_for("Who is Ed Sullivan?", "Ed Sullivan", [], [])["missing"], "QueryBook holds no record of “Ed Sullivan” yet.")

    def test_record_numbers_and_web_addresses_come_last(self):
        order = [f["predicate"] for f in sense.arrange(F_MAN, "human")]
        self.assertEqual(order[:3], ["occupation", "date of birth", "place of birth"])
        self.assertEqual(set(order[-3:]), {"Baseball-Reference ID", "image", "official website"})
        for p, v in (("VIAF ID", "1"), ("IMDb ID", "nm1"), ("Commons category", "x"), ("image", "a.jpg"), ("official website", "http://x")):
            self.assertTrue(sense.is_identifier(p, v), p)
        for p in ("occupation", "date of birth", "country", "inception", "position held"):
            self.assertFalse(sense.is_identifier(p, "x"), p)

    def test_things_that_are_not_people(self):
        f = facts("Lincoln Memorial (Q213559)", [("instance of", "memorial (Q5003624)"), ("country", "United States (Q30)"),
                                                 ("located in the administrative territorial entity", "Washington, D.C. (Q61)"), ("inception", "1922")])
        r = sense.answer_for("What is the Lincoln Memorial?", "Lincoln Memorial", [{"subject": "Lincoln Memorial (Q213559)", "facts": 4}], f)
        self.assertEqual(r["entity"]["kind"], "place")
        self.assertEqual(r["said"], "Lincoln Memorial — a memorial in Washington, D.C., United States. Since: 1922.")
        d = facts("drinking fountain (Q1630622)", [("description", "fountain designed to provide drinking water"), ("subclass of", "fountain (Q483453)")])
        self.assertEqual(sense.identity("drinking fountain (Q1630622)", d, "thing"), "drinking fountain — fountain designed to provide drinking water.")


class Panel(http.server.BaseHTTPRequestHandler):
    """the Control Panel's routes the Ask box uses"""
    demand: list = []
    world: dict = {}

    def log_message(self, *a):
        pass

    def _send(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.path == "/api/bulk/entity":
            return self._send(Panel.world.get(q.get("q", "").lower(), {"entities": [], "facts": []}))
        if u.path == "/api/bulk/search" and q.get("q", "").lower() == "dodgers":      # the old search: names that BEGIN with the words
            return self._send({"facts": facts("Dodgers–Giants rivalry (Q1)", [("instance of", "sports rivalry (Q2)")])})
        return self._send({"facts": []})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        if self.path == "/api/bulk/demand":
            Panel.demand.append(body)
            return self._send({"queued": True, "pending": len(Panel.demand)})
        return self._send({"facts": []})


class AskTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Panel)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.urls = {"control": "http://127.0.0.1:%d" % cls.srv.server_address[1]}
        Panel.world = {"babe ruth": {"entities": ENTS, "facts": F_CARD + F_FILM + F_MAN},
                       "card only": {"entities": ENTS[:1], "facts": F_CARD}}

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_who_was_asks_who_he_was(self):
        self.assertEqual(ask.understand("Who was Babe Ruth?")["hints"], [])
        self.assertEqual(ask.understand("Who is Ed Sullivan?")["hints"], [])
        self.assertIn("inventor", ask.understand("Who invented the telephone?")["hints"])      # unchanged
        self.assertIn("birth", ask.understand("When was Babe Ruth born?")["hints"])

    def test_the_ask_box_answers_with_the_man(self):
        Panel.demand = []
        r = ask.answer("Who was Babe Ruth?", self.urls)
        self.assertTrue(r["short"].startswith("Babe Ruth (1895–1948) — baseball player"))
        self.assertEqual((r["entity"]["kind"], r["missing"]), ("human", ""))
        items = r["sections"][-1]["items"]
        self.assertTrue(all(f["subject"] == MAN for f in items))                    # the card's facts are not mixed in
        self.assertEqual(items[0]["predicate"], "occupation")
        self.assertEqual(Panel.demand, [])
        self.assertEqual(ask.answer("When was Babe Ruth born?", self.urls)["short"], "Babe Ruth — date of birth: 1895-02-06")

    def test_what_is_not_held_is_said_and_sent_to_the_demand_agent(self):
        Panel.demand = []
        r = ask.answer("Who is Ed Sullivan?", self.urls)
        self.assertEqual(r["missing"], "QueryBook holds no record of “Ed Sullivan” yet.")
        self.assertIn("demand agent", r["learning"])
        self.assertEqual([(d["subject"], d["question"]) for d in Panel.demand], [("Ed Sullivan", "Who is Ed Sullivan?")])
        r2 = ask.answer("Who is card only?", self.urls)
        self.assertIn("no record of the person itself", r2["missing"])
        self.assertEqual(Panel.demand[-1]["subject"], "card only")


class PartOfANameTest(unittest.TestCase):
    TEAM, FILM2 = "Los Angeles Dodgers (Q334634)", "Dodgers (Q777001)"

    def test_the_well_known_thing_beats_an_obscure_exact_name(self):
        fs = facts(self.TEAM, [("instance of", "baseball team (Q13027888)"), ("description", "baseball team in Los Angeles, California")]) + \
            facts(self.FILM2, [("instance of", "film (Q11424)")])
        ents = [{"subject": self.FILM2, "facts": 1, "exact": True}, {"subject": self.TEAM, "facts": 2, "fame": 70, "exact": False, "by_part_of_name": True}]
        r = sense.answer_for("What are the Dodgers", "Dodgers", ents, fs)
        self.assertEqual(r["entity"]["subject"], self.TEAM)
        self.assertEqual(r["entity"]["kind"], "organization")
        self.assertIn("best-known thing by that name", r["entity"]["why"])
        self.assertEqual(r["said"], "Los Angeles Dodgers — baseball team in Los Angeles, California.")
        # between two equally obscure things, the one named exactly as asked wins
        r2 = sense.choose("What is Dodgers", [{"subject": "A (Q1)", "facts": 2, "exact": False}, {"subject": "Dodgers (Q2)", "facts": 2, "exact": True}],
                          facts("A (Q1)", [("instance of", "x")]) + facts("Dodgers (Q2)", [("instance of", "x")]))
        self.assertEqual(r2["subject"], "Dodgers (Q2)")


class KnownForTest(unittest.TestCase):
    """several occupations: the one the person is best known for, from the person's own facts"""

    @staticmethod
    def facts(rows):
        return [{"subject": "X (Q1)", "predicate": p, "object": o} for p, o in rows]

    def test_the_description_names_it(self):
        k = sense.known_for(self.facts([("description", "American television host (1901-1974)"), ("occupation", "journalist"),
                                        ("occupation", "television presenter"), ("occupation", "columnist"), ("occupation", "actor")]))
        self.assertEqual(k["best"], "television presenter")
        self.assertIn("description", k["why"])
        self.assertEqual(k["also"][0], "journalist")

    def test_high_office_outranks_an_earlier_career(self):
        rows = [("description", "president of the United States from 1981 to 1989"), ("occupation", "actor"), ("occupation", "politician"),
                ("occupation", "screenwriter"), ("position held", "Governor of California"), ("position held", "President of the United States")]
        k = sense.known_for(self.facts(rows))
        self.assertEqual((k["best"], k["role"]), ("politician", "President of the United States"))
        said = sense.identity("Ronald Reagan (Q9960)", self.facts(rows), "human")
        self.assertIn("Best known as President of the United States; also actor", said)

    def test_the_record_backs_it_up_when_no_description(self):
        k = sense.known_for(self.facts([("occupation", "baseball player"), ("occupation", "actor"), ("occupation", "basketball player"),
                                        ("occupation", "entrepreneur"), ("member of sports team", "Chicago Bulls"), ("sport", "basketball"),
                                        ("award received", "NBA Most Valuable Player Award")]))
        self.assertIn(k["best"], ("baseball player", "basketball player"))     # the athlete, not the actor or the entrepreneur
        self.assertNotIn(k["best"], ("actor", "entrepreneur"))

    def test_order_in_the_description(self):
        k = sense.known_for(self.facts([("description", "Austrian-American actor, businessman, bodybuilder and politician"),
                                        ("occupation", "bodybuilder"), ("occupation", "politician"), ("occupation", "actor")]))
        self.assertEqual(k["best"], "actor")

    def test_one_occupation_or_none_is_said_plainly(self):
        self.assertEqual(sense.known_for(self.facts([("occupation", "poet")]))["best"], "poet")
        self.assertEqual(sense.known_for([])["best"], "")
        self.assertNotIn("Best known", sense.identity("X (Q1)", self.facts([("occupation", "poet")]), "human"))


class PrefixOnlyTest(AskTest):
    def test_names_that_only_begin_with_the_words_are_not_an_answer(self):
        Panel.demand = []
        r = ask.answer("What are the Dodgers", self.urls)
        self.assertIn("nothing named “Dodgers” itself", r["missing"])
        self.assertIn("demand agent", r["learning"])
        self.assertEqual(Panel.demand[-1]["subject"], "Dodgers")
        self.assertTrue(r["sections"])                                   # what was found is still shown, said for what it is


if __name__ == "__main__":
    unittest.main()
