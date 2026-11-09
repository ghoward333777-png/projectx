#!/usr/bin/env python3
"""The Engineer: finds improvements in a program, applies none without the admin, tests every fix on a copy with the
program's own self-test, applies only what passes (with a backup), reverts, learns from rejections, carries a shared
core fix to every application, and reads errors and slow work from the program's own records."""
import json, os, sys, tempfile, textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "_core"))
import qbcore as core
import qbengineer as E

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [OK]", name)
    else:
        FAIL += 1
        print("  [FAIL]", name, detail)


class Approvals:
    def __init__(self):
        self.pw = None

    def admin_set(self):
        return bool(self.pw)

    def _require(self, p):
        if p != self.pw:
            raise core.UserError("Admin passphrase not correct — nothing was changed.")


APP = textwrap.dedent('''\
    import os, sys, json
    import helper

    def selftest():
        ok = helper.value() == 42 and "BROKEN" not in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "helper.py")).read()
        print("  1 of 1 checks passed" if ok else "  [FAIL] helper")
        return ok

    if __name__ == "__main__":
        if sys.argv[1:] == ["--selftest"]:
            sys.exit(0 if selftest() else 1)
    ''')
HELPER = textwrap.dedent('''\
    import re
    from collections import OrderedDict, Counter

    def value(x=None):
        if x == None:
            x = 42
        try:
            return int(x)
        except:
            return 0

    def broken_on_purpose():
        pass  # TODO: remove this function
    ''')
SHARED = "import math\nimport qbcore_stub\n\ndef f():\n    return qbcore_stub\n"
PAGE = "function used() { return 1; }\nfunction neverCalled() { return 2; }\nconsole.log(\"debug\");\nused();\n"


def make_suite(root):
    for app in ("one", "two"):
        d = os.path.join(root, app)
        os.makedirs(os.path.join(d, "ui"), exist_ok=True)
        open(os.path.join(d, "app.py"), "w").write(APP)
        open(os.path.join(d, "helper.py"), "w").write(HELPER)
        open(os.path.join(d, "qbcore.py"), "w").write(SHARED)          # a "shared core" file (same in both apps)
        open(os.path.join(d, "ui", "page.js"), "w").write(PAGE)
        open(os.path.join(d, "ui", "index.html"), "w").write("<button onclick=\"used()\">x</button>")
    os.makedirs(os.path.join(root, "_core"), exist_ok=True)
    open(os.path.join(root, "_core", "qbcore.py"), "w").write(SHARED)


def main():
    root = tempfile.mkdtemp()
    make_suite(root)
    data = tempfile.mkdtemp()
    logf = os.path.join(data, "one.log")
    open(logf, "w").write('2026-10-21T10:00:00Z  JOB FAILED Traceback (most recent call last):\n  File "%s", line 8, in value\n'
                          '    return int(x)\nValueError: invalid literal for int()\n' % os.path.join(root, "one", "helper.py") * 3)
    log = lambda *a: None
    log.path = logf
    store = core.Store(data, "one", [], log)
    with store.write() as db:
        for i in range(4):
            db.execute("INSERT INTO qb_activity(at, task, status, ms) VALUES(?,?,?,?)", ("2026-10-21", "Build the dictionary", "ok", 9000 + i))
    eng = E.Engineer(data, "one", os.path.join(root, "one"), log, store)
    eng.approvals = Approvals()

    print("Skills")
    r = eng.scan()
    ps = eng.proposals()
    by = {}
    for p in ps:
        by.setdefault(p["skill"], []).append(p)
    check("finds unused imports (only the unused names), == None, bare except", len(by.get("py-unused-import", [])) >= 3 and by.get("py-none-compare") and by.get("py-bare-except"),
          {k: len(v) for k, v in by.items()})
    check("finds console.log and a page function nothing calls (onclick in the page counts as a use)",
          by.get("js-console") and [p for p in by.get("js-unused-function", []) if "neverCalled" in p["title"]] and not [p for p in by.get("js-unused-function", []) if "used()" in p["title"]])
    check("finds a TODO, errors in its own log (by file and line), slow work in its activity record",
          by.get("code-todo") and by.get("run-errors") and "3 time" in by["run-errors"][0]["title"] and by.get("run-slow"))
    check("a fix carries its exact change (unified diff); advice carries evidence", all(p["fixable"] for p in by["py-unused-import"])
          and "-from collections import OrderedDict, Counter" in eng.proposal(next(p["id"] for p in by["py-unused-import"] if "OrderedDict" in p["title"]))["patch"]
          and not by["run-errors"][0]["fixable"])
    check("scanning again repeats nothing", eng.scan()["new"] == 0)

    print("Nothing without the admin")
    pid = next(p["id"] for p in by["py-none-compare"])
    try:
        eng.approve(pid, "x"); ok = False
    except core.UserError as e:
        ok = "admin passphrase first" in str(e)
    check("refused while no admin passphrase is set", ok)
    eng.approvals.pw = "admin-pass-1"
    try:
        eng.approve(pid, "wrong"); ok = False
    except core.UserError:
        ok = True
    check("refused with a wrong passphrase", ok and open(os.path.join(root, "one", "helper.py")).read() == HELPER)

    print("Tested, applied, reverted")
    p = eng.approve(pid, "admin-pass-1", wait=True)
    h = open(os.path.join(root, "one", "helper.py")).read()
    check("an approved fix is tested on a copy (self-test passes) and applied, with a backup", p["status"] == "applied" and "if x is None:" in h
          and p["test"]["selftest"]["passed"] and os.path.isfile(os.path.join(p["backup"], "manifest.json")), p.get("test"))
    p2 = eng.approve(next(x["id"] for x in by["py-bare-except"]), "admin-pass-1", wait=True)
    check("a second fix on the same file is made on the file as it is now", p2["status"] == "applied" and "except Exception:" in open(os.path.join(root, "one", "helper.py")).read()
          and "if x is None:" in open(os.path.join(root, "one", "helper.py")).read())
    r = eng.revert(p2["id"], "admin-pass-1")
    check("revert restores the file", r["status"] == "reverted" and "except:" in open(os.path.join(root, "one", "helper.py")).read())
    # a fix whose result fails the self-test is not applied
    with open(os.path.join(root, "one", "helper.py"), "a") as f:
        f.write("# BROKEN marker added by the test (the self-test fails while it is present)\n")
    before = open(os.path.join(root, "one", "helper.py")).read()
    eng.scan()
    imp = next(x for x in eng.proposals("open") if x["skill"] == "py-unused-import" and x["file"] == "helper.py")
    f = eng.approve(imp["id"], "admin-pass-1", wait=True)
    check("a fix whose copy fails the self-test is not applied — the file is untouched", f["status"] == "failed" and open(os.path.join(root, "one", "helper.py")).read() == before
          and not f["test"]["selftest"]["passed"], f.get("test"))
    with open(os.path.join(root, "one", "helper.py"), "w") as fh:
        fh.write(before.replace("# BROKEN marker added by the test (the self-test fails while it is present)\n", ""))

    print("Shared core files")
    eng.scan()
    sh = next(x for x in eng.proposals("open") if x["file"] == "qbcore.py" and x["skill"] == "py-unused-import")
    s = eng.approve(sh["id"], "admin-pass-1", wait=True)
    texts = [open(os.path.join(root, d, "qbcore.py")).read() for d in ("one", "two", "_core")]
    check("a fix to a shared core file is made in every application and the master copy", s["status"] == "applied" and all("import math" not in t for t in texts)
          and len(set(texts)) == 1, s.get("test"))

    print("Advice and learning")
    adv = next(x for x in eng.proposals("open") if x["skill"] == "run-errors")
    a = eng.approve(adv["id"], "admin-pass-1")
    check("approved advice becomes a to-do item with its evidence, then done", a["status"] == "accepted" and eng.done(adv["id"], "admin-pass-1")["status"] == "done")
    todo = [x for x in eng.proposals("open") if x["skill"] == "js-console"] + [x for x in eng.proposals("open") if x["skill"] == "js-unused-function"] + \
           [x for x in eng.proposals("open") if x["skill"] == "code-todo"]
    for sk in ("code-todo",):
        ids = [x["id"] for x in eng.proposals("open") if x["skill"] == sk]
    # three rejections of one skill (never approved) mute it
    with open(os.path.join(root, "one", "helper.py"), "a") as fh:
        fh.write("# TODO: second note\n# TODO: third note\n")
    eng.scan()
    ids = [x["id"] for x in eng.proposals("open") if x["skill"] == "code-todo"]
    for i in ids[:3]:
        eng.reject(i, "admin-pass-1", "not wanted")
    st = {s["id"]: s["stats"] for s in eng.status()["skills"]}
    check("after three rejections and no approval a skill is muted; the admin can unmute it",
          st["code-todo"].get("muted") == 1 and eng.unmute("code-todo", "admin-pass-1")["muted"] is False, st.get("code-todo"))
    pr = eng.proposals()
    check("proposals are ranked by severity and by the admin's record", pr == sorted(pr, key=lambda r: ({"testing": 0, "open": 1, "accepted": 2, "failed": 3, "applied": 4}.get(r["status"], 9), -r["priority"], r["id"])))

    print("Routes")
    api = core.Api()
    E.add_routes(api, eng)
    st = api.routes[("GET", "/api/engineer/status")]({})
    check("status lists the skills with their record", len(st["skills"]) == len(E.SKILLS) and st["admin_set"])
    print("\n%d of %d checks passed" % (PASS, PASS + FAIL))
    return FAIL == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
