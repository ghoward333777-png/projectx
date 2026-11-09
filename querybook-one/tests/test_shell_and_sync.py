"""Checks for the one-window shell's Ask logic and for the Lean files staying in step with the Python code."""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "apps", "shell"))
import ask  # noqa: E402


class AskUnderstandingTest(unittest.TestCase):
    def test_questions_become_subjects_and_hints(self):
        i = ask.understand("When was the printing press invented?")
        self.assertEqual((i["kind"], i["subject"]), ("fact", "printing press"))
        self.assertIn("Printing press", i["variants"])        # bulk subjects are stored as "Printing press (Q11223)"
        self.assertIn("date", i["hints"])
        self.assertNotIn("inventor", i["hints"])             # "when" wants a date, not a person
        self.assertIn("inventor", ask.understand("Who invented the printing press?")["hints"])
        self.assertEqual(ask.understand("What does obsequious mean?")["kind"], "word")
        self.assertEqual(ask.understand("obsequious")["subject"], "obsequious")
        self.assertEqual(ask.understand("60 mph to km/h")["kind"], "math")
        self.assertEqual(ask.understand("what is DNA")["subject"], "DNA")

    def test_ranking_and_short_answer(self):
        i = ask.understand("When was the printing press invented?")
        facts = [{"subject": "Printing press (Q11223)", "predicate": "inventor", "object": "Johannes Gutenberg (Q8958)"},
                 {"subject": "Printing press (Q11223)", "predicate": "time of discovery or invention", "object": "1440"}]
        ranked = ask.rank(facts, i)
        self.assertEqual(ranked[0]["object"], "1440")
        self.assertEqual(ask.short_answer(i, ranked), "Printing press — time of discovery or invention: 1440")
        who = ask.understand("Who invented the printing press?")
        self.assertEqual(ask.short_answer(who, ask.rank(facts, who)), "Printing press — inventor: Johannes Gutenberg")

    def test_nothing_invented_without_facts(self):
        i = ask.understand("When was the printing press invented?")
        self.assertEqual(ask.short_answer(i, []), "")


class LeanSyncTest(unittest.TestCase):
    def test_generated_lean_matches_python(self):
        for tool in ("gen_lean.py", "gen_rust.py"):
            r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", tool), "--check"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, tool + ": " + r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
