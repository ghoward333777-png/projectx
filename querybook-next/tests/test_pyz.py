import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SingleFileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "tools"))
        import build_pyz
        cls.build = staticmethod(build_pyz.build)
        cls.tmp = Path(tempfile.mkdtemp(prefix="pyz-"))
        cls.pyz = cls.build(cls.tmp / "querybook-next.pyz")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_pyz(self, args, home):
        env = dict(os.environ, QB_CACHE_DIR=str(self.tmp / "cache"))
        return subprocess.run([sys.executable, str(self.pyz), "--home", str(home), *args],
                              capture_output=True, text=True, env=env, timeout=120, cwd=str(self.tmp))

    def test_build_is_deterministic(self):
        again = self.build(self.tmp / "again.pyz")
        self.assertEqual(again.read_bytes(), self.pyz.read_bytes())

    def test_runs_against_a_suite_store(self):
        from tests.suite_fixture import build_suite_folder
        folder = build_suite_folder(self.tmp / "DQB")
        info = self.run_pyz(["info"], folder)
        self.assertEqual(info.returncode, 0, info.stderr)
        self.assertIn('"store_connected": true', info.stdout)
        q = self.run_pyz(["fql", 'Facts.bySubject("Water").map(.object).toArray()'], folder)
        self.assertEqual(q.returncode, 0, q.stderr)
        self.assertIn("H2O", q.stdout)
        ask = self.run_pyz(["ask", "stem", "2 * (3 + 4)"], folder)
        self.assertIn('"value": 14', ask.stdout)

    def test_missing_data_drive_refuses(self):
        res = self.run_pyz(["info"], self.tmp / "not-connected")
        self.assertEqual(res.returncode, 1)
        self.assertIn("cannot be found", res.stderr)


if __name__ == "__main__":
    unittest.main()
