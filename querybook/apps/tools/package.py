#!/usr/bin/env python3
"""Build one zip per application in dist/: QueryBook-Language-1.0.0.zip, QueryBook-STEM-1.0.0.zip, QueryBook-History-News-1.0.0.zip.

Each zip unpacks to a single folder that runs on its own. Runs every self-test first and stops if any fails.
"""
import os, subprocess, sys, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = {"language": "QueryBook-Language", "stem": "QueryBook-STEM", "facts": "QueryBook-History-News"}
SKIP_DIRS = {"__pycache__"}
SKIP_FILES = {"config.json"}

def _add_tree(z, src, arc_root, skip_dirs=SKIP_DIRS, skip_suffix=(".pyc", ".pt")):
    for d, dirs, files in os.walk(src):
        dirs[:] = sorted(x for x in dirs if x not in skip_dirs)
        for f in sorted(files):
            if f in SKIP_FILES or f.endswith(skip_suffix):
                continue
            p = os.path.join(d, f)
            _add_file(z, p, os.path.join(arc_root, os.path.relpath(p, src)))


def _add_file(z, path, arc):
    info = zipfile.ZipInfo(arc.replace(os.sep, "/"), date_time=(2026, 10, 16, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o755 if path.endswith((".command", ".py", ".bat")) else 0o644) << 16
    with open(path, "rb") as fh:
        z.writestr(info, fh.read())


def build_suite():
    """One installer with all three applications, start-all launchers, the release notes and the stage-2 extras."""
    vers = {app: next(l.split('"')[1] for l in open(os.path.join(ROOT, app, "app.py"), encoding="utf-8") if l.startswith("VERSION ="))
            for app in APPS}
    out = os.path.join(ROOT, "dist", "QueryBook-Suite-Language%s-STEM%s-History%s.zip" % (vers["language"], vers["stem"], vers["facts"]))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(os.path.join(ROOT, "suite"))):
            _add_file(z, os.path.join(ROOT, "suite", f), os.path.join("QueryBook", f))
        for app, name in APPS.items():
            _add_tree(z, os.path.join(ROOT, app), os.path.join("QueryBook", name))
        vse = os.path.join(os.path.dirname(ROOT), "vse")
        if os.path.isdir(vse):
            _add_tree(z, vse, os.path.join("QueryBook", "extras", "visual-speech-engine-stage2"),
                      skip_dirs=SKIP_DIRS | {"checkpoints", ".pytest_cache"})
    print("built", os.path.relpath(out, ROOT), "%d KB" % (os.path.getsize(out) // 1024))
    return out


if __name__ == "__main__":
    if subprocess.run([sys.executable, "-B", os.path.join(ROOT, "tools", "run_all_tests.py")]).returncode != 0:
        sys.exit("Tests failed — nothing packaged.")
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    for app, name in APPS.items():
        src = os.path.join(ROOT, app)
        version = next(l.split('"')[1] for l in open(os.path.join(src, "app.py"), encoding="utf-8") if l.startswith("VERSION ="))
        out = os.path.join(ROOT, "dist", "%s-%s.zip" % (name, version))
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for d, dirs, files in os.walk(src):
                dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
                for f in sorted(files):
                    if f in SKIP_FILES or f.endswith(".pyc"):
                        continue
                    p = os.path.join(d, f)
                    arc = os.path.join(name, os.path.relpath(p, src)).replace(os.sep, "/")
                    info = zipfile.ZipInfo(arc, date_time=(2026, 10, 16, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = (0o755 if f.endswith((".command", ".py")) else 0o644) << 16
                    with open(p, "rb") as fh:
                        z.writestr(info, fh.read())
        print("built", os.path.relpath(out, ROOT), "%d KB" % (os.path.getsize(out) // 1024))
    build_suite()
