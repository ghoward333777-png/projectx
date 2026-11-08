import shutil
import tempfile
import unittest
from pathlib import Path

from querybook.cli import Runtime


class RuntimeCase(unittest.TestCase):
    """A fresh QueryBook home (database + inbox) per test class, seeded with samples."""

    seed = True

    @classmethod
    def setUpClass(cls):
        cls.home = Path(tempfile.mkdtemp(prefix="querybook-test-"))
        cls.rt = Runtime(str(cls.home))
        if cls.seed:
            cls.rt.seed()

    @classmethod
    def tearDownClass(cls):
        cls.rt.store.close()
        shutil.rmtree(cls.home, ignore_errors=True)
