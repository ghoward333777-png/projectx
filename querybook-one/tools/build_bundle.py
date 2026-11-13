#!/usr/bin/env python3
"""Build QueryBook.zip: every application, the one-window shell and (for Windows) Python itself.

    python tools/build_bundle.py [embed-zip] [out.zip]

Unzips to one folder, laid out the way the suite expects (data-folder.txt beside the program folders):

  QueryBook/START-QueryBook.bat         double-click on Windows (uses the Python inside, nothing to install)
  QueryBook/START-QueryBook.command     double-click on a Mac (uses the Mac's python3)
  QueryBook/data-folder.txt             D:\\QB — the existing QueryBook data drive
  QueryBook/python/                     python.org's embeddable Python 3.13 for Windows, unchanged (SHA-256 checked)
  QueryBook/QueryBook-Shell/            the one window
  QueryBook/QueryBook-Language/ … -STEM/ … -History-News/ … -Video-Studio/ … -Control-Panel/
Deterministic: the same sources give a byte-identical zip.
"""
from __future__ import annotations

import hashlib
import io
import os
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = os.path.join(ROOT, "apps")
FOLDERS = {"shell": "QueryBook-Shell", "language": "QueryBook-Language", "stem": "QueryBook-STEM", "facts": "QueryBook-History-News",
           "video": "QueryBook-Video-Studio", "control": "QueryBook-Control-Panel"}
PY_VERSION = "3.13.17"
EMBED_URL = "https://www.python.org/ftp/python/%s/python-%s-embed-amd64.zip" % (PY_VERSION, PY_VERSION)
EMBED_SHA256 = "9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38"   # python.org SBOM for 3.13.17
SKIP_DIRS = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIX = (".pyc", ".pt")
SKIP_FILES = {"config.json", "watches.json", "workflows.json", "projects.json", "styles.json", "learned.json"}   # per-computer settings and saved personal files
FIXED = (2026, 11, 9, 0, 0, 0)

START_BAT = (
    "@echo off\r\n"
    "rem QueryBook - double-click to start every application in one window. Python is included (python folder).\r\n"
    "title QueryBook\r\n"
    "cd /d \"%~dp0\"\r\n"
    "\"%~dp0python\\python.exe\" -X utf8 \"%~dp0QueryBook-Shell\\shell.py\" %*\r\n"
    "if errorlevel 1 pause\r\n"
)
START_MAC = "#!/bin/bash\n# QueryBook - double-click to start (first time: right-click > Open > Open).\ncd \"$(dirname \"$0\")\"\nexec python3 QueryBook-Shell/shell.py \"$@\"\n"
README = (
    "QueryBook\r\n=========\r\n\r\n"
    "1. Unzip this file (right-click > Extract All).\r\n"
    "2. Close the old QueryBook windows if they are open (they use the same data and the same ports).\r\n"
    "3. Open the QueryBook folder and double-click START-QueryBook.bat\r\n"
    "4. Your browser opens QueryBook: every application in one window. Keep the black window open while you use it.\r\n\r\n"
    "Your data stays on D:\\QB (data-folder.txt). If the drive is not connected, nothing starts.\r\n"
    "Python is included for Windows - nothing to install. On a Mac, double-click START-QueryBook.command (needs python3).\r\n"
)


# The embeddable Python's ._pth file switches off adding a script's own folder to sys.path. The suite's programs
# import their neighbouring files (and the bulk harvester starts itself as a separate program), so the bundle turns
# the standard `import site` line on and restores that one behaviour in sitecustomize.py. Nothing else changes.
PTH = b"python313.zip\r\n.\r\n\r\n# QueryBook: site runs so sitecustomize.py can add the running script's folder to sys.path\r\nimport site\r\n"
SITECUSTOMIZE = (
    '"""QueryBook bundle: put the running script\'s folder first on sys.path, as a normal Python install does."""\n'
    "import os, sys\n"
    "if sys.argv and sys.argv[0] and sys.argv[0].endswith('.py') and os.path.isfile(sys.argv[0]):\n"
    "    sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[0])))\n"
)


def embed(path: str | None) -> bytes:
    data = open(path, "rb").read() if path else urllib.request.urlopen(EMBED_URL, timeout=180).read()
    if hashlib.sha256(data).hexdigest() != EMBED_SHA256:
        raise SystemExit("Embeddable Python checksum mismatch")
    return data


def entries(embed_zip: bytes) -> list[tuple[str, bytes, int]]:
    out: list[tuple[str, bytes, int]] = [
        ("QueryBook/START-QueryBook.bat", START_BAT.encode(), 0o755), ("QueryBook/START-QueryBook.command", START_MAC.encode(), 0o755),
        ("QueryBook/data-folder.txt", b"D:\\QB\r\n", 0o644), ("QueryBook/README.txt", README.encode(), 0o644)]
    for app, folder in FOLDERS.items():
        src = os.path.join(APPS, app)
        for d, dirs, files in os.walk(src):
            dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
            for f in sorted(files):
                if f in SKIP_FILES or f.endswith(SKIP_SUFFIX):
                    continue
                p = os.path.join(d, f)
                arc = "QueryBook/%s/%s" % (folder, os.path.relpath(p, src).replace(os.sep, "/"))
                with open(p, "rb") as fh:
                    out.append((arc, fh.read(), 0o755 if f.endswith((".command", ".py", ".bat", ".exe")) else 0o644))
    with zipfile.ZipFile(io.BytesIO(embed_zip)) as z:
        for name in sorted(z.namelist()):
            if name.endswith("/"):
                continue
            data = z.read(name)
            if name.endswith("._pth"):
                data = PTH                                 # the one file changed: run site, so sitecustomize below runs
            out.append(("QueryBook/python/" + name, data, 0o644))
    out.append(("QueryBook/python/sitecustomize.py", SITECUSTOMIZE.encode(), 0o644))
    return out


def build(embed_zip: bytes, out: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for arc, data, mode in entries(embed_zip):
            info = zipfile.ZipInfo(arc, FIXED)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = mode << 16
            z.writestr(info, data)
    return out


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else None
    target = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "dist", "QueryBook.zip")
    path = build(embed(src), target)
    print("built %s (%.1f MB)" % (path, os.path.getsize(path) / 1e6))
