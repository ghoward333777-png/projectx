"""The Lean 4 specification (lean/) must describe the Python code exactly.

Lean itself is checked by `lake build` (the GitHub workflow querybook-next.yml). These tests
check the other direction without Lean installed: every `example` in the Lean files is
re-run against the real Python code, so the spec cannot drift from the implementation.
"""

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from querybook.core.fql import run_fql
from querybook.core.fql.evaluator import WHOLE_SET_METHODS
from querybook.core.model import DOMAINS
from querybook.core.text import pick

LEAN = Path(__file__).resolve().parents[1] / "lean" / "QueryBookSpec"


class LeanClassifyTest(unittest.TestCase):
    def test_examples_match_python(self):
        src = (LEAN / "Classify.lean").read_text(encoding="utf-8")
        cases = re.findall(r"example : classify ⟨(\d+), (\d+), (\d+), (\d+)⟩ = \.(\w+) := by decide", src)
        self.assertGreaterEqual(len(cases), 9)
        for *nums, expected in cases:
            scores = dict(zip(DOMAINS, map(int, nums)))
            with self.subTest(scores=scores):
                self.assertEqual(pick(scores), expected)

    def test_domain_order_matches(self):
        src = (LEAN / "Classify.lean").read_text(encoding="utf-8")
        order = re.search(r"inductive Domain where\s*\|\s*([\w |]+)", src).group(1).split("|")
        self.assertEqual(tuple(x.strip() for x in order), DOMAINS)


class LeanGuardTest(unittest.TestCase):
    FQL = {"where_": '.where(.subject != "")', "map": ".map(.object)", "take": ".take(3)", "first": ".first()",
           "count": ".count()", "order": ".order(.subject)", "toArray": ".toArray()"}

    @classmethod
    def setUpClass(cls):
        from querybook.cli import Runtime
        from tests.suite_fixture import build_suite_folder
        cls.folder = build_suite_folder(Path(tempfile.mkdtemp(prefix="dqb-lean-")))
        cls.rt = Runtime(str(cls.folder))

    @classmethod
    def tearDownClass(cls):
        cls.rt.store.close()
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_whole_set_methods_match(self):
        src = (LEAN / "Guard.lean").read_text(encoding="utf-8")
        line = re.search(r"\| (\.order[^=]+)=> true", src).group(1)
        self.assertEqual({m.strip(" .") for m in line.split("|")}, set(WHOLE_SET_METHODS))

    def test_examples_match_the_evaluator(self):
        src = (LEAN / "Guard.lean").read_text(encoding="utf-8")
        cases = re.findall(r"example : run \.unbounded \[([^\]]*)\] = (none|some \.\w+) := by decide", src)
        self.assertGreaterEqual(len(cases), 6)
        for methods, outcome in cases:
            chain = "".join(self.FQL[m.strip(" .")] for m in methods.split(","))
            res = run_fql(self.rt.store, "Facts.all()" + chain, readonly=True, legacy=self.rt.legacy)
            with self.subTest(query=chain):
                if outcome == "none":
                    self.assertEqual(res["error"]["code"], "unbounded_set")
                else:
                    self.assertTrue(res["ok"], res)


if __name__ == "__main__":
    unittest.main()
