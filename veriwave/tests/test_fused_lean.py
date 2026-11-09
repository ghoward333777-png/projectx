"""Every line of VeriWave's engine is fused with Lean: each function carries its Lean mirror, the extracted Lean project is
up to date, and every `#guard` vector holds in Python too (lake build checks the Lean side)."""
import ast
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import gen_lean  # noqa: E402


class FusedLeanTest(unittest.TestCase):
    def test_every_function_has_lean(self):
        self.assertEqual(gen_lean.missing(), [])

    def test_lean_files_up_to_date(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "gen_lean.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_guard_vectors_hold_in_python(self):
        failures, count = [], 0
        for mod in gen_lean.ORDER:
            path = os.path.join(ROOT, "vw", mod + ".py")
            if not os.path.isfile(path):
                continue
            module = __import__("vw." + mod, fromlist=["*"])
            env = dict(vars(module))
            with open(path, encoding="utf-8") as fh:
                lines = fh.read().split("\n")
            for i, line in enumerate(lines, 1):
                if "#guard" in line:
                    m = re.search(r"--\s*py:\s*(.+)$", line)
                    if not m:
                        failures.append("vw/%s.py:%d #guard without a '-- py:' twin" % (mod, i))
                        continue
                    count += 1
                    try:
                        ok = eval(m.group(1), env)  # test-only: the vector's Python side
                    except Exception as e:
                        ok = False
                        failures.append("vw/%s.py:%d %s raised %s" % (mod, i, m.group(1), e))
                        continue
                    if ok is not True:
                        failures.append("vw/%s.py:%d %s is %r" % (mod, i, m.group(1), ok))
        self.assertEqual(failures, [])
        self.assertGreater(count, 60)

    def test_lean_uses_core_only(self):
        """no Mathlib or sorry: the Lean must build on core Lean 4 alone and prove what it states"""
        for fn in os.listdir(os.path.join(ROOT, "lean", "VeriWave")):
            with open(os.path.join(ROOT, "lean", "VeriWave", fn), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("import Mathlib", text, fn)
            self.assertIsNone(re.search(r"\bsorry\b|\badmit\b|native_decide", text), fn)


if __name__ == "__main__":
    unittest.main()
