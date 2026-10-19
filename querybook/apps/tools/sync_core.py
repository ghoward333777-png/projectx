#!/usr/bin/env python3
"""Copy the shared core (_core/qbcore.py, qbcommons.py and _core/ui/qb.css, qb.js) into each application.

Each application keeps its own copy so it can be shipped and run on its own.
Run this after editing anything in _core/, then run each app's self-test.
"""
import os, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = ["language", "stem", "facts"]
FILES = [("qbcore.py", "qbcore.py"), ("qbcommons.py", "qbcommons.py"), ("qbharvest.py", "qbharvest.py"), ("qbonline.py", "qbonline.py"), ("qbdevices.py", "qbdevices.py"), ("gcloud.py", "gcloud.py"), (os.path.join("ui", "qb.css"), os.path.join("ui", "qb.css")),
         (os.path.join("ui", "qb.js"), os.path.join("ui", "qb.js"))]

if __name__ == "__main__":
    for app in APPS:
        d = os.path.join(ROOT, app)
        if not os.path.isdir(d):
            continue
        for src, dst in FILES:
            os.makedirs(os.path.dirname(os.path.join(d, dst)) or d, exist_ok=True)
            shutil.copyfile(os.path.join(ROOT, "_core", src), os.path.join(d, dst))
        print("synced", app)
