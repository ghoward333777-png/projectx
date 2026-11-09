"""Loaded only by tools/run_all_tests.py (never by the applications).

On Windows a file that is still open cannot be deleted, so a test's temporary folder can fail to clean up while one of
its databases is open — an error in the test's tidying, not in what it tested. There, temporary folders are told to
ignore such clean-up errors (Python 3.10+). Nothing changes on macOS or Linux.
"""
import os
import sys
import tempfile

if os.name == "nt" and sys.version_info >= (3, 10):
    _original_init = tempfile.TemporaryDirectory.__init__

    def _tolerant_init(self, suffix=None, prefix=None, dir=None, ignore_cleanup_errors=True, **kw):
        _original_init(self, suffix, prefix, dir, ignore_cleanup_errors=True, **kw)

    tempfile.TemporaryDirectory.__init__ = _tolerant_init
