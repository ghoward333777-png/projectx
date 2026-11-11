"""The twelve AI capabilities (apps/shell/caps.py — rules; assist.py — the worker, with a stand-in for the model and the
Language app). Rule-based results use only the text's own words; a model's work is labelled; nothing is lost."""
import http.server
import json
import os
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "apps", "shell"))
import assist  # noqa: E402
import caps  # noqa: E402

PRESS = """The printing press was invented by Johannes Gutenberg around 1440 in Mainz. It used movable metal type, which let a printer set a page quickly. Before the press, books were copied by hand, and a single Bible could take a scribe more than a year.

Within fifty years, presses were running in more than 200 European cities. They had printed about 20 million books by 1500. Prices fell, and ordinary people could own a book for the first time.

Historians link the press to the spread of the Reformation and of science. Luther's pamphlets sold in hundreds of thousands of copies. Scientists could now share exact tables and diagrams. Dr. Smith said so on 3 March 2020."""


class CatalogueTest(unittest.TestCase):
    def test_the_twelve_capabilities_in_order(self):
        self.assertEqual([c["name"] for c in caps.CAPABILITIES],
                         ["Ask / Search", "Summarize", "Write / Create", "Organize", "Analyze", "Develop / Project", "Tools", "Processes / Workflows",
                          "Agent(s)", "Chatbot", "Translate / Languages", "Learn / Study"])
        self.assertEqual([c["n"] for c in caps.CAPABILITIES], list(range(1, 13)))
        ids = [t["id"] for c in caps.CAPABILITIES for t in c["tasks"]]
        self.assertEqual(len(ids), len(set(ids)))
        for c in caps.CAPABILITIES:
            for t in c["tasks"]:
                self.assertIn(t["input"], ("text", "brief", "question", "goal", "chat", "none"))
                if t["input"] == "none" and not t["id"].startswith(("proj.", "wf.")):
                    self.assertIn(t.get("opens"), ("ask", "bookquery", "stem", "video", "harvest", "language", "translate"))

    def test_every_workflow_step_and_starter_is_runnable(self):
        for w in caps.STARTER_WORKFLOWS:
            self.assertEqual(caps.check_workflow(w["steps"]), [dict(s) for s in w["steps"]])
        self.assertEqual(caps.check_workflow([{"do": "rm -rf"}, {"do": "sum.brief", "option": "x"}]), [{"do": "sum.brief"}])


class RulesTest(unittest.TestCase):
    def test_summary_is_the_texts_own_sentences(self):
        all_s = caps.sentences(PRESS)
        self.assertEqual(len(all_s), 10)                       # 'Dr. Smith' does not end a sentence
        for kind in ("brief", "points", "line"):
            r = caps.summarize(PRESS, kind)
            self.assertTrue(r["sentences"] and all(s in all_s for s in r["sentences"]))
            self.assertLess(r["words_out"], r["words_in"])
        self.assertEqual(len(caps.summarize(PRESS, "line")["sentences"]), 1)
        self.assertIn("Gutenberg", caps.summarize(PRESS, "line")["text"])

    def test_organize(self):
        r = caps.sort_items("pears\n- apples\n2. Bananas\napples")
        self.assertEqual((r["items"], r["removed"]), (["apples", "Bananas", "pears"], 1))
        g = caps.group_items("buy milk\ncall the bank about the loan\nbuy bread\nemail the bank statement\nwalk the dog")
        topics = {x["topic"]: x["items"] for x in g["groups"]}
        self.assertEqual(topics["Bank"], ["call the bank about the loan", "email the bank statement"])
        self.assertEqual(sorted(i for v in topics.values() for i in v), sorted(caps.items("buy milk\ncall the bank about the loan\nbuy bread\nemail the bank statement\nwalk the dog")))
        self.assertEqual(len(caps.outline(PRESS)["sections"]), 3)
        t = caps.table("Name, Age\nAnn, 31\nBob, 45")
        self.assertEqual((t["header"], t["rows"]), (["Name", "Age"], [["Ann", "31"], ["Bob", "45"]]))
        a = caps.actions("Call the plumber on Monday.\nThe meeting went well.\nWe must send the report by 12 March.")
        self.assertEqual([x["do"] for x in a["actions"]], ["Call the plumber on Monday", "We must send the report by 12 March"])
        self.assertEqual([d["when"] for d in a["dates"]], ["Monday", "12 March"])

    def test_analyze(self):
        n = caps.analyze_numbers("Name, Age, Score\nAnn, 31, 88.5\nBob, 45, 72\nCy, 28, 91")
        age = next(c for c in n["columns"] if c["name"] == "Age")
        self.assertEqual((age["count"], age["sum"], age["median"], age["min"], age["max"]), (3, 104, 31, 28, 45))
        self.assertEqual(caps.analyze_numbers("We sold 1,200 units, then 950 and 1,430.")["columns"][0]["sum"], 3580)
        self.assertEqual(caps.stats([2, 4, 4, 4, 5, 5, 7, 9])["mean"], 5)
        t = caps.analyze_text(PRESS)
        self.assertEqual((t["sentences"], t["paragraphs"]), (10, 3))
        self.assertEqual(t["top_terms"][0]["term"], "press")
        c = caps.compare(PRESS, PRESS)
        self.assertEqual((c["similarity"], c["same_sentences"]), (1.0, 10))
        self.assertLess(caps.compare(PRESS, "The telescope was invented in 1608.")["similarity"], 0.2)

    def test_write_skeleton_and_project_plan_use_only_the_brief(self):
        s = caps.skeleton("email", "Ask the landlord to fix the heating by Friday")
        self.assertEqual(s["parts"][0], {"part": "Subject", "note": "Ask the landlord to fix the heating by Friday"})
        self.assertEqual(next(p["note"] for p in s["parts"] if p["part"] == "By when"), "Friday")
        p = caps.project_plan("Open a community tool library by spring")
        self.assertEqual((p["target"], len(p["phases"]), caps.progress(p)["total"]), ("by spring", 5, 17))
        self.assertIn("Open a community tool library by spring", p["phases"][0]["tasks"][0]["text"])
        p["phases"][0]["tasks"][0]["done"] = True
        self.assertEqual(caps.progress(p)["done"], 1)
        self.assertIn("☑", caps.plan_text(p))

    def test_study_questions_are_answered_by_the_text(self):
        st = caps.study(PRESS)
        self.assertTrue(st["questions"])
        for q in st["questions"]:
            self.assertIn("_____", q["question"])
            self.assertEqual(q["question"].replace("_____", q["answer"], 1), q["from"])
            self.assertIn(q["from"], caps.sentences(PRESS))

    def test_agent_planning_by_rules(self):
        self.assertEqual(caps.plan_steps("Summarize this and translate it into French"), [{"do": "sum.brief"}, {"do": "tr.quick", "option": "fr"}])
        self.assertEqual(caps.plan_steps("give me the key points and the action items"), [{"do": "sum.points"}, {"do": "org.actions"}])
        g = caps.split_goal("Summarize and translate into Spanish: The press was invented in 1440 and it changed Europe.")
        self.assertEqual(g, {"instruction": "Summarize and translate into Spanish", "material": "The press was invented in 1440 and it changed Europe."})
        self.assertEqual(caps.small_talk("Hello!")[:5], "Hello")
        self.assertEqual(caps.small_talk("When was the press invented?"), "")


class StandIn(http.server.BaseHTTPRequestHandler):
    """Claude's Messages API (structured output) and the Language app's translation route"""
    seen: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        StandIn.seen.append((self.path, body))
        if self.path.startswith("/api/lablang/cloudtr"):
            out = {"text": "[%s] %s" % (body["tgt"], body["text"]), "by": "Google Translate"}
        else:
            props = body["output_config"]["format"]["schema"]["properties"]
            user = body["messages"][0]["content"]
            if "phases" in props:
                j = {"name": "Tool library", "target": "spring", "risks": ["Too few tools donated"],
                     "phases": [{"name": "Prepare", "tasks": ["Find a room", "Collect tools"]}, {"name": "Open", "tasks": ["Invite the neighbours", "Open the doors"]}]}
            elif "steps" in props:
                j = {"steps": [{"do": "sum.points", "option": ""}, {"do": "tr.quick", "option": "fr"}]}
            elif "reply" in props:
                j = {"reply": "It was invented around 1440.", "from_facts": True}
            elif "groups" in props:
                its = user.split("ITEMS:\n", 1)[1].split("\n")
                j = {"groups": [{"topic": "Errands", "items": its[:2]}, {"topic": "Rest", "items": its[2:]}]} if "LOSE" not in user else {"groups": [{"topic": "x", "items": its[:1]}]}
            else:
                j = {"text": "AI wrote this."}
            out = {"content": [{"type": "text", "text": json.dumps(j)}], "stop_reason": "end_turn", "usage": {}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


FACTS = [{"subject": "Printing press (Q11223)", "predicate": "time of discovery or invention", "object": "1440", "where": "wikidata"},
         {"subject": "Printing press (Q11223)", "predicate": "inventor", "object": "Johannes Gutenberg (Q8958)", "where": "wikidata"}]


def fake_ask(body, urls):
    known = "press" in body["q"].lower()
    return {"question": body["q"], "understood": {"subject": "Printing press" if known else ""}, "short": "1440" if known else "",
            "sections": [{"kind": "facts", "items": FACTS}] if known else []}


def fake_check(text, urls):
    return {"claims": [{"claim": "The press was invented in 1440.", "verdict": "VERIFIED", "facts": FACTS[:1]}], "tally": {"VERIFIED": 1, "CONTRADICTED": 0, "UNKNOWN": 0}}


class AssistTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        cls.old = os.environ.get("QB_TEST_ANTHROPIC_URL")
        os.environ["QB_TEST_ANTHROPIC_URL"] = cls.base + "/v1/messages"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        if cls.old is None:
            os.environ.pop("QB_TEST_ANTHROPIC_URL", None)
        else:
            os.environ["QB_TEST_ANTHROPIC_URL"] = cls.old

    def make(self, key=True, language=True):
        return assist.Assist(tempfile.mkdtemp(), lambda: {"anthropic": "k"} if key else {}, lambda: {"language": self.base} if language else {}, fake_ask, fake_check)

    def test_without_a_key_everything_is_rules_and_says_so(self):
        a = self.make(key=False)
        r = a.run({"task": "sum.brief", "text": PRESS})
        self.assertEqual((r["by"], r["by_label"][:9]), ("rules", "QueryBook"))
        self.assertTrue(all(s in caps.sentences(PRESS) for s in r["sentences"]))
        w = a.run({"task": "write.email", "text": "Ask the landlord to fix the heating by Friday"})
        self.assertEqual(w["by"], "rules")
        self.assertIn("No AI key", w["note"])
        self.assertIn("Subject: Ask the landlord", w["text"])
        self.assertIn("needs an AI key", a.run({"task": "write.rewrite", "text": PRESS})["note"])
        self.assertEqual(a.run({"task": "org.sort", "text": "b\na\nb"})["text"], "a\nb")
        with self.assertRaises(ValueError):
            a.run({"task": "sum.brief", "text": ""})
        with self.assertRaises(ValueError):
            a.run({"task": "nope", "text": "x"})

    def test_with_a_key_the_model_is_labelled_and_the_rule_result_kept(self):
        a = self.make()
        r = a.run({"task": "sum.brief", "text": PRESS})
        self.assertEqual((r["by"], r["by_label"], r["text"]), ("claude", "Claude", "AI wrote this."))
        self.assertTrue(r["rules_text"] and r["rules_text"] in " ".join(caps.sentences(PRESS)) or r["rules_text"])
        self.assertEqual(a.run({"task": "sum.brief", "text": PRESS, "ai": False})["by"], "rules")   # 'Use AI' off
        w = a.run({"task": "write.email", "text": "Ask the landlord to fix the heating"})
        self.assertEqual(w["by"], "claude")
        self.assertNotIn("note", w)
        n = a.run({"task": "an.numbers", "text": "4, 8, 15, 16, 23, 42"})
        self.assertEqual((n["by"], n["columns"][0]["sum"], n["insight"], n["insight_by"]), ("rules", 108, "AI wrote this.", "Claude"))   # the numbers are computed, the model only comments

    def test_a_model_grouping_that_loses_an_item_is_refused(self):
        a = self.make()
        ok = a.run({"task": "org.group", "text": "buy milk\nbuy bread\nwalk the dog"})
        self.assertEqual((ok["by"], [g["topic"] for g in ok["groups"]]), ("claude", ["Errands", "Rest"]))
        bad = a.run({"task": "org.group", "text": "buy milk\nbuy bread\nLOSE this one"})
        self.assertEqual(bad["by"], "rules")
        self.assertIn("lost or changed", bad["note"])

    def test_facts_and_translation(self):
        a = self.make(key=False)
        c = a.run({"task": "an.claims", "text": "The press was invented in 1440."})
        self.assertEqual((c["by"], c["tally"]["VERIFIED"]), ("facts", 1))
        t = a.run({"task": "tr.quick", "text": "Good morning", "option": "fr"})
        self.assertEqual((t["text"], t["by"]), ("[fr] Good morning", "language"))
        self.assertIn("Google Translate", t["note"])
        with self.assertRaises(ValueError):
            self.make(key=False, language=False).run({"task": "tr.quick", "text": "Good morning", "option": "fr"})

    def test_projects_are_saved_ticked_and_deleted(self):
        a = self.make(key=False)
        r = a.run({"task": "proj.plan", "text": "Open a community tool library by spring"})
        pid = r["project"]["id"]
        self.assertEqual((r["by"], r["project"]["progress"]["total"]), ("rules", 17))
        ai = self.make().run({"task": "proj.plan", "text": "Open a community tool library by spring"})
        self.assertEqual((ai["by"], [p["name"] for p in ai["project"]["phases"]], ai["project"]["risks"]), ("claude", ["Prepare", "Open"], ["Too few tools donated"]))
        rows = a.run({"task": "proj.toggle", "id": pid, "phase": 0, "item": 1})["projects"]
        self.assertEqual(rows[0]["progress"]["done"], 1)
        rows = a.run({"task": "proj.add", "id": pid, "phase": 2, "text": "Order shelves"})["projects"]
        self.assertEqual(rows[0]["phases"][2]["tasks"][-1], {"text": "Order shelves", "done": False})
        self.assertEqual(a.run({"task": "proj.list"})["projects"][0]["id"], pid)
        self.assertEqual(a.run({"task": "proj.delete", "id": pid})["projects"], [])

    def test_workflows_chain_and_are_saved(self):
        a = self.make(key=False)
        listed = a.run({"task": "wf.list"})["workflows"]
        self.assertEqual([w["id"] for w in listed], [w["id"] for w in caps.STARTER_WORKFLOWS])
        r = a.run({"task": "wf.run", "id": "share", "text": PRESS})
        self.assertEqual([(t["do"], t["by"]) for t in r["trace"]], [("sum.brief", "rules"), ("tr.quick", "language")])
        self.assertEqual(r["trace"][1]["text"], "[es] " + r["trace"][0]["text"][:2000])       # step 2 worked on step 1's result
        self.assertEqual((r["done"], r["of"]), (2, 2))
        saved = a.run({"task": "wf.save", "name": "Mine", "steps": [{"do": "sum.points"}, {"do": "bogus"}, {"do": "learn.text"}]})["workflows"]
        mine = next(w for w in saved if w["name"] == "Mine")
        self.assertEqual(mine["steps"], [{"do": "sum.points"}, {"do": "learn.text"}])
        self.assertEqual(len(a.run({"task": "wf.run", "id": mine["id"], "text": PRESS})["trace"]), 2)
        self.assertNotIn("Mine", [w["name"] for w in a.run({"task": "wf.delete", "id": mine["id"]})["workflows"]])
        stopped = self.make(key=False, language=False).run({"task": "wf.run", "id": "share", "text": PRESS})   # a failing step stops the chain and says why
        self.assertEqual((stopped["done"], stopped["of"]), (1, 2))
        self.assertIn("not running", stopped["trace"][1]["error"])

    def test_agent_plans_runs_and_shows_every_step(self):
        a = self.make(key=False)
        r = a.run({"task": "agent.run", "text": "Give me the key points and translate into French: " + PRESS})
        self.assertEqual((r["planner"], [t["do"] for t in r["trace"]]), ("rules", ["sum.points", "tr.quick"]))
        self.assertTrue(r["text"].startswith("[fr] •"))
        look = a.run({"task": "agent.run", "text": "Find out about the printing press and translate it into Spanish"})
        self.assertEqual([t["do"] for t in look["trace"]], ["ask.question", "tr.quick"])        # no material: the facts first
        self.assertIn("1440", look["trace"][0]["text"])
        none = a.run({"task": "agent.run", "text": "Find out about zzyzx and summarize it"})
        self.assertIn("no facts", none["note"])
        ai = self.make().run({"task": "agent.run", "text": "Do something useful with this: " + PRESS})
        self.assertEqual((ai["planner"], [t["do"] for t in ai["trace"]]), ("claude", ["sum.points", "tr.quick"]))

    def test_chat_answers_from_facts_and_remembers_the_subject(self):
        a = self.make(key=False)
        self.assertEqual(a.run({"task": "chat.talk", "text": "hello"})["by"], "rules")
        r = a.run({"task": "chat.talk", "text": "When was the printing press invented?"})
        self.assertEqual((r["reply"], r["by"], r["turn"]["subject"]), ("1440", "facts", "Printing press"))
        self.assertEqual(r["facts"][0]["where"], "wikidata")
        follow = a.run({"task": "chat.talk", "text": "who invented it?", "turns": [r["turn"]]})
        self.assertIn("rinting press", follow["asked"])
        self.assertIn("no facts", a.run({"task": "chat.talk", "text": "Tell me about zzyzx"})["reply"])
        ai = self.make().run({"task": "chat.talk", "text": "When was the printing press invented?"})
        self.assertEqual((ai["reply"], ai["by"]), ("It was invented around 1440.", "facts+claude"))
        self.assertIn("QueryBook's facts", ai["by_label"])
        blank = self.make().run({"task": "chat.talk", "text": "Tell me about zzyzx"})                # the model says 'from facts' but there were none
        self.assertIn("not from QueryBook's facts", blank["by_label"])


if __name__ == "__main__":
    unittest.main()
