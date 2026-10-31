#!/usr/bin/env python3
"""Run the core safety tests and every application's self-test. Exit code 0 only if all pass."""
import os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = [["tools/test_core.py"], ["tools/test_commons.py"], ["tools/test_devices.py"], ["tools/test_agents.py"], ["tools/test_engineer.py"], ["_core/qbbulk.py", "self-test"], ["_core/qbgather.py", "self-test"], ["_core/qbkeystone.py"], ["_core/qbconnections.py"], ["tools/answer_videos.py", "self-test"], ["language/app.py", "--selftest"], ["stem/app.py", "--selftest"], ["facts/app.py", "--selftest"], ["control/app.py", "--selftest"]]

if __name__ == "__main__":
    failed = []
    for r in RUNS:
        p = subprocess.run([sys.executable, "-B"] + r, cwd=ROOT, capture_output=True, text=True)
        last = [l for l in p.stdout.splitlines() if "checks passed" in l]
        print("%-28s %s" % (r[0], last[-1].strip() if last else "no result"))
        if p.returncode != 0:
            failed.append(r[0])
            print("\n".join(l for l in p.stdout.splitlines() if "[FAIL]" in l) or p.stderr[-2000:])
    print("\nALL PASSED" if not failed else "\nFAILED: " + ", ".join(failed))
    sys.exit(1 if failed else 0)
