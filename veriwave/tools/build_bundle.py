#!/usr/bin/env python3
"""Build VeriWave.zip: VeriWave, every QueryBook application, the Feature Registry and (for Windows) Python itself.

    python tools/build_bundle.py [embed-zip] [out.zip]

Unzips to one folder:

  VeriWave/START-VeriWave.bat           double-click on Windows (uses the Python inside: nothing to install)
  VeriWave/START-VeriWave.command       double-click on a Mac (uses the Mac's python3)
  VeriWave/README.txt                   how to start, where the data lives
  VeriWave/python/                      python.org's embeddable Python 3.13 for Windows (SHA-256 checked), as QueryBook's bundle
  VeriWave/app/veriwave/                VeriWave (with its own copy of the Feature Registry)
  VeriWave/app/querybook-one/apps/      QueryBook's applications and one-window shell, as VeriWave expects to find them
  VeriWave/app/querybook-one/apps/data-folder.txt   D:\\QB, QueryBook's data drive
  VeriWave/app/*.php, app/data/         the Book Intelligence Studio (starts only where PHP is installed)

The embeddable Python and its one adjustment (the ._pth file and sitecustomize.py) come from QueryBook one's own
bundle builder (querybook-one/tools/build_bundle.py), so both bundles behave the same. Deterministic: the same
sources give a byte-identical zip.
"""
from __future__ import annotations

import importlib.util
import io
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
VW = os.path.dirname(HERE)
REPO = os.path.dirname(VW)
QB_TOOL = os.path.join(REPO, "querybook-one", "tools", "build_bundle.py")
APPS = os.path.join(REPO, "querybook-one", "apps")
APP_DIRS = ["shell", "_core", "control", "language", "stem", "facts", "video"]
REGISTRY = os.path.join(REPO, "docs", "querybook-rebuild", "feature-inventory-v71.json")
SKIP_DIRS = {"__pycache__", ".pytest_cache", "data-local", "target", ".lake", "tests"}
SKIP_SUFFIX = (".pyc", ".pt")
SKIP_FILES = {"config.json"}
FIXED = (2026, 11, 9, 0, 0, 0)

START_BAT = (
    "@echo off\r\n"
    "rem VeriWave - double-click to start. Python is included (python folder); nothing to install.\r\n"
    "title VeriWave\r\n"
    "cd /d \"%~dp0\"\r\n"
    "\"%~dp0python\\python.exe\" -X utf8 \"%~dp0app\\veriwave\\veriwave.py\" %*\r\n"
    "if errorlevel 1 pause\r\n"
)
START_MAC = ("#!/bin/bash\n# VeriWave - double-click to start (first time: right-click > Open > Open).\n"
             "cd \"$(dirname \"$0\")\"\nexec python3 app/veriwave/veriwave.py \"$@\"\n")
README = (
    "VeriWave - the QueryBook AI model\r\n"
    "=================================\r\n\r\n"
    "INSTALL (once)\r\n"
    "  1. Right-click VeriWave.zip > Extract All... > Extract.\r\n"
    "     (Any folder works, for example your Desktop or C:\\VeriWave.)\r\n\r\n"
    "START (every time)\r\n"
    "  2. Close any old QueryBook windows (VeriWave starts QueryBook itself, on the same ports).\r\n"
    "  3. Open the VeriWave folder and double-click START-VeriWave.bat\r\n"
    "     If Windows shows \"Windows protected your PC\", click More info > Run anyway.\r\n"
    "  4. Your browser opens VeriWave at http://127.0.0.1:8095/\r\n"
    "     Keep the black window open while you use it. Close it to stop everything.\r\n\r\n"
    "WHAT YOU GET\r\n"
    "  Chat (the default), plus Answer, Code, Create (Text, Image, Video, Audio), QueryBook (every QueryBook\r\n"
    "  screen, on demand), Workspace (screens side by side) and the Feature Registry (all 407 features).\r\n\r\n"
    "YOUR FACTS\r\n"
    "  VeriWave connects to the facts on D:\\QB by default and reads them directly (read-only, never changed):\r\n"
    "  UFCS stores (index.sqlite), QueryBook's shared facts (commons) and its bulk datasets (commons\\shards).\r\n"
    "  The Answer and QueryBook screens show how many facts are connected. To use another folder, set the\r\n"
    "  VERIWAVE_FACTS environment variable to it.\r\n\r\n"
    "YOUR DATA\r\n"
    "  QueryBook's facts stay on D:\\QB (app\\querybook-one\\apps\\data-folder.txt), exactly as with QueryBook.\r\n"
    "  If that drive is not connected, VeriWave still opens, but QueryBook's applications do not start;\r\n"
    "  connect the drive and start again, or put another folder's path in data-folder.txt.\r\n"
    "  What VeriWave makes (apps, pictures, films, audio) is saved in D:\\QB\\veriwave.\r\n\r\n"
    "OPTIONAL\r\n"
    "  Claude engine: set the ANTHROPIC_API_KEY environment variable before starting VeriWave.\r\n"
    "  Speech: install espeak-ng (https://github.com/espeak-ng/espeak-ng/releases).\r\n"
    "  Book Studio: install PHP and it starts with VeriWave.\r\n\r\n"
    "Mac: double-click START-VeriWave.command (needs python3 from python.org).\r\n"
)


def qb_builder():
    """QueryBook one's bundle builder, for its embeddable Python, checksum and ._pth adjustment"""
    spec = importlib.util.spec_from_file_location("qb_build_bundle", QB_TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def walk(src: str, arc_root: str) -> list[tuple[str, bytes, int]]:
    out: list[tuple[str, bytes, int]] = []
    for d, dirs, files in os.walk(src):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for f in sorted(files):
            if f in SKIP_FILES or f.endswith(SKIP_SUFFIX):
                continue
            p = os.path.join(d, f)
            arc = arc_root + "/" + os.path.relpath(p, src).replace(os.sep, "/")
            with open(p, "rb") as fh:
                out.append((arc, fh.read(), 0o755 if f.endswith((".command", ".py", ".bat", ".exe", ".sh")) else 0o644))
    return out


def entries(embed_zip: bytes, qb: object) -> list[tuple[str, bytes, int]]:
    out: list[tuple[str, bytes, int]] = [
        ("VeriWave/START-VeriWave.bat", START_BAT.encode(), 0o755),
        ("VeriWave/START-VeriWave.command", START_MAC.encode(), 0o755),
        ("VeriWave/README.txt", README.encode(), 0o644),
        ("VeriWave/app/querybook-one/apps/data-folder.txt", b"D:\\QB\r\n", 0o644),
    ]
    for part in ("veriwave.py", "vw", "ui", "README.md", "lean", "rust", "contracts", "tools"):
        src = os.path.join(VW, part)
        if os.path.isdir(src):
            out += walk(src, "VeriWave/app/veriwave/" + part)
        else:
            with open(src, "rb") as fh:
                out.append(("VeriWave/app/veriwave/" + part, fh.read(), 0o644))
    with open(REGISTRY, "rb") as fh:
        out.append(("VeriWave/app/veriwave/data/feature-inventory-v71.json", fh.read(), 0o644))
    for app in APP_DIRS:
        out += walk(os.path.join(APPS, app), "VeriWave/app/querybook-one/apps/" + app)
    for f in sorted(os.listdir(REPO)):                          # the Book Intelligence Studio
        if f.endswith(".php"):
            with open(os.path.join(REPO, f), "rb") as fh:
                out.append(("VeriWave/app/" + f, fh.read(), 0o644))
    out += walk(os.path.join(REPO, "data"), "VeriWave/app/data")
    with zipfile.ZipFile(io.BytesIO(embed_zip)) as z:
        for name in sorted(z.namelist()):
            if name.endswith("/"):
                continue
            data = z.read(name)
            if name.endswith("._pth"):
                data = qb.PTH
            out.append(("VeriWave/python/" + name, data, 0o644))
    out.append(("VeriWave/python/sitecustomize.py", qb.SITECUSTOMIZE.encode(), 0o644))
    return out


def build(embed_zip: bytes, out: str, qb: object) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for arc, data, mode in entries(embed_zip, qb):
            info = zipfile.ZipInfo(arc, FIXED)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = mode << 16
            z.writestr(info, data)
    return out


if __name__ == "__main__":
    qb = qb_builder()
    src = sys.argv[1] if len(sys.argv) > 1 else None
    target = sys.argv[2] if len(sys.argv) > 2 else os.path.join(VW, "dist", "VeriWave.zip")
    path = build(qb.embed(src), target, qb)
    print("built %s (%.1f MB)" % (path, os.path.getsize(path) / 1e6))
