#!/usr/bin/env python3
"""Copy the shared core (_core/qbcore.py, qbcommons.py and _core/ui/qb.css, qb.js) into each application.

Each application keeps its own copy so it can be shipped and run on its own.
Run this after editing anything in _core/, then run each app's self-test.
"""
import os, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = ["language", "stem", "facts", "control"]
FILES = [("qbcore.py", "qbcore.py"), ("qbcommons.py", "qbcommons.py"), ("qbharvest.py", "qbharvest.py"), ("qbonline.py", "qbonline.py"), ("qbdevices.py", "qbdevices.py"), ("qbagents.py", "qbagents.py"), ("qbartifact.py", "qbartifact.py"), ("qbengineer.py", "qbengineer.py"), ("qbcontrol.py", "qbcontrol.py"), ("qbselfknow.py", "qbselfknow.py"), ("qbexemplar.py", "qbexemplar.py"), ("qbcampaign.py", "qbcampaign.py"), ("qbbulk.py", "qbbulk.py"), ("qbscaffold.py", "qbscaffold.py"), ("qbapidoc.py", "qbapidoc.py"), ("gcloud.py", "gcloud.py"), (os.path.join("ui", "qb.css"), os.path.join("ui", "qb.css")),
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
    # QueryBook 9.64 carries the same online harvesters, exemplar library, generator and plans
    v964 = os.path.join(os.path.dirname(ROOT), "QueryBook-v9.64")
    if os.path.isdir(v964):
        for src, dst in ((os.path.join(ROOT, "_core", "qbonline.py"), "qb_online.py"), (os.path.join(ROOT, "_core", "qbselfknow.py"), "qb_selfknow.py"),
                         (os.path.join(ROOT, "_core", "qbexemplar.py"), "qbexemplar.py"), (os.path.join(ROOT, "tools", "generate_exemplars.py"), "generate_exemplars.py")):
            shutil.copyfile(src, os.path.join(v964, dst))
        shutil.copytree(os.path.join(ROOT, "tools", "plans"), os.path.join(v964, "plans"), dirs_exist_ok=True)
        print("synced QueryBook-v9.64")
