"""Loaded only by tools/run_all_tests.py (never by the applications).

On Windows a file that is still open cannot be deleted. The tests often read a database with a one-line connection
(sqlite3.connect(p).execute(...)) that Python closes only at its next garbage collection, so a later delete in the
same test can find the file still open: an error in the test's tidying, not in what it tested. On Windows only:
  * a delete or rename refused that way collects garbage (closing those connections) and tries again; a file that
    is really still open is still refused, so the applications' own "file busy" handling is tested as before;
  * temporary folders ignore clean-up errors (Python 3.10+).
Nothing changes on macOS or Linux.
"""
import gc
import os
import sys
import tempfile
import time

if os.name == "nt":
    def _retrying(fn):
        def call(*a, **kw):
            try:
                return fn(*a, **kw)
            except PermissionError:
                gc.collect()
                time.sleep(0.05)
                return fn(*a, **kw)
        return call

    os.remove = _retrying(os.remove)
    os.unlink = _retrying(os.unlink)
    os.replace = _retrying(os.replace)
    os.rename = _retrying(os.rename)

if os.name == "nt" and sys.version_info >= (3, 10):
    _original_init = tempfile.TemporaryDirectory.__init__

    def _tolerant_init(self, suffix=None, prefix=None, dir=None, ignore_cleanup_errors=True, **kw):
        _original_init(self, suffix, prefix, dir, ignore_cleanup_errors=True, **kw)

    tempfile.TemporaryDirectory.__init__ = _tolerant_init
